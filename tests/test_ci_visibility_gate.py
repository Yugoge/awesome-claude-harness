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

import re
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


_PYTEST_CALL = re.compile(r"(?:-m\s+pytest|^\s*pytest)\b", re.MULTILINE)
_STUCK_TEST_BOUND = re.compile(r"-o\s+faulthandler_timeout=[1-9][0-9]*\b")


def _run_text(step: dict) -> str:
    """A step's script without its comment lines."""
    return "\n".join(line for line in str(step.get("run", "")).splitlines() if not line.lstrip().startswith("#"))


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_job_has_a_time_limit_and_every_test_run_a_stuck_test_bound(path: Path) -> None:
    """A hung job must not run to the hosting service's six hours without saying where it stands.

    Every job that runs steps carries its own timeout-minutes (a job that only calls a reusable
    workflow, `uses:`, cannot: the called jobs carry theirs), and every step that runs the test
    runner passes `-o faulthandler_timeout=<seconds>`, so that a test running longer than the bound
    prints its name and stack into the log (the runner prints no test names in its quiet mode).
    Read from the parsed files: no number and no job name is fixed here.
    """
    jobs = _load(path).get("jobs") or {}
    no_limit = [jid for jid, job in jobs.items()
                if "uses" not in job and not (isinstance(job.get("timeout-minutes"), int) and job["timeout-minutes"] > 0)]
    unbounded = [f"{jid}: {step.get('name', '?')}" for jid, job in jobs.items() for step in job.get("steps") or []
                 if len(_PYTEST_CALL.findall(_run_text(step))) > len(_STUCK_TEST_BOUND.findall(_run_text(step)))]
    assert not no_limit, f"{path.name}: jobs without a timeout-minutes of their own: {no_limit}"
    assert not unbounded, f"{path.name}: test-runner steps without -o faulthandler_timeout=<seconds>: {unbounded}"


_WORKERS = re.compile(r"(?<!\S)(?:-n\s*\S|--numprocesses\b|--dist\b)")
_NO_WORKER_RESTART = re.compile(r"--max-worker-restart=0\b")


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_test_run_with_workers_ends_when_a_worker_dies(path: Path) -> None:
    """A worker that dies mid-run must fail the run on the spot and name its test.

    With --dist loadfile and files still queued for it, xdist waits for the dead worker until the
    job's time limit and prints nothing. Every step that runs the test runner with workers
    (-n, --numprocesses, --dist) passes --max-worker-restart=0 once per runner call; the runner then
    stops at the crash with "worker 'gwN' crashed while running '<test>'". Read from the parsed files.
    """
    jobs = _load(path).get("jobs") or {}
    lacking = [f"{jid}: {step.get('name', '?')}" for jid, job in jobs.items() for step in job.get("steps") or []
               if _PYTEST_CALL.search(_run_text(step)) and _WORKERS.search(_run_text(step))
               and len(_PYTEST_CALL.findall(_run_text(step))) > len(_NO_WORKER_RESTART.findall(_run_text(step)))]
    assert not lacking, f"{path.name}: test-runner steps with workers lacking --max-worker-restart=0: {lacking}"
