"""D30: every CI job is gated on repository visibility, and the triggers that gate relies on hold.

The private repository (full history) and the public one (the clean tree as one commit per
publish) carry the same .github/workflows/ files, and a trigger cannot test visibility, so each
job tests it. A job runs where the event payload says the repository is public; a workflow that
declares workflow_dispatch also runs on a manual dispatch, the only way anything runs on the
private repository. The private flag is compared through toJSON() because expression equality
coerces null to 0: `private == false` would count a payload with no repository object (a
schedule's) as public. A job may AND the gate with its own condition (a draft pull request
runs nothing, a status check), so the gate is the whole condition or one top-level `&&` term in
parentheses. Conditions are read from PARSED YAML, so a comment quoting the gate cannot satisfy
them, and a duplicate key fails: PyYAML keeps the last of two `if:` keys, GitHub refuses the file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.y*ml"))
PUBLIC = "toJSON(github.event.repository.private) == 'false'"
DISPATCH_OR_PUBLIC = f"github.event_name == 'workflow_dispatch' || {PUBLIC}"


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses a mapping with a duplicate key."""

    def construct_mapping(self, node, deep=False):
        keys = [self.construct_object(k, deep=deep) for k, _ in node.value]
        dup = sorted({str(k) for k in keys if keys.count(k) > 1})
        if dup:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate key(s) {dup}", node.start_mark)
        return super().construct_mapping(node, deep=deep)


def _load(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictLoader)


def _terms(cond: str) -> list[str]:
    """The top-level `&&` terms of an expression (parentheses and quotes respected)."""
    terms, depth, quote, start = [], 0, False, 0
    for i, ch in enumerate(cond):
        if ch == "'":
            quote = not quote
        elif not quote and ch in "()":
            depth += 1 if ch == "(" else -1
        elif not quote and depth == 0 and cond.startswith("&&", i):
            terms.append(cond[start:i].strip())
            start = i + 2
    return terms + [cond[start:].strip()]


def _on(doc: dict) -> dict:
    """The trigger map. PyYAML resolves the bare key `on:` to the boolean True (YAML 1.1)."""
    on = doc["on"] if "on" in doc else doc.get(True)
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return dict.fromkeys(on)
    return dict(on or {})


def _condition(job: dict) -> str:
    cond = " ".join(str(job.get("if", "")).split())
    if cond.startswith("${{") and cond.endswith("}}"):
        cond = cond[3:-2].strip()
    return cond


def test_both_workflows_are_present() -> None:
    assert {p.name for p in WORKFLOWS} >= {"baseline.yml", "release.yml"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_job_carries_the_visibility_gate(path: Path) -> None:
    doc = _load(path)
    want = DISPATCH_OR_PUBLIC if "workflow_dispatch" in _on(doc) else PUBLIC
    jobs = doc.get("jobs") or {}
    assert jobs, f"{path.name} declares no jobs"
    wrong = {jid: cond for jid, job in jobs.items()
             if (cond := _condition(job)) != want and f"({want})" not in _terms(cond)}
    assert not wrong, f"{path.name}: jobs without the D30 gate `{want}`: {wrong}"


def test_baseline_keeps_its_triggers_and_has_no_schedule() -> None:
    on = _on(_load(WORKFLOW_DIR / "baseline.yml"))
    assert "main" in ((on.get("push") or {}).get("branches") or []), "baseline.yml lost push on main"
    for trigger in ("pull_request", "workflow_call", "workflow_dispatch"):
        assert trigger in on, f"baseline.yml lost its {trigger} trigger"
    assert "schedule" not in on, "a schedule payload has no repository object, so the gate skips it"


def test_release_stays_tag_triggered() -> None:
    on = _on(_load(WORKFLOW_DIR / "release.yml"))
    assert set(on) == {"push"}, f"release.yml must run on tag pushes only, got {sorted(on)}"
    push = on["push"] or {}
    assert "v*" in (push.get("tags") or []) and "branches" not in push
