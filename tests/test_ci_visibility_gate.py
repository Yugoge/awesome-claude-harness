"""D30: every CI job is gated on repository visibility, and the triggers that gate relies on hold.

The private repository (full history) and the public one (the clean tree as one commit per
publish) carry the same .github/workflows/ files, and a trigger cannot test visibility, so each
job tests it. A job runs where the event payload says the repository is public; a workflow that
declares workflow_dispatch also runs on a manual dispatch, the only way anything runs on the
private repository. The private flag is compared through toJSON() because expression equality
coerces null to 0: `private == false` would count a payload with no repository object (a
schedule's) as public. Conditions are read from PARSED YAML, so a comment quoting the gate
cannot satisfy them.
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


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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
    wrong = {jid: _condition(job) for jid, job in jobs.items() if _condition(job) != want}
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
