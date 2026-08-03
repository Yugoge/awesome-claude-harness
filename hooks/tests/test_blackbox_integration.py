#!/usr/bin/env python3
"""Component black-box suite: drives the guards at the SUBPROCESS boundary.

WHAT THIS PROVES, AND WHAT IT EXPLICITLY DOES NOT
--------------------------------------------------
Every other module under `hooks/tests/` imports guard internals and calls them as Python
functions. This one does not import anything from the guards. It spawns the real hook script
as a child process, feeds it a synthetic PreToolUse payload on stdin exactly as the Claude Code
hook protocol specifies, and asserts the real exit code and stderr.

That earns `proof_layer: component-tested` in `docs/ENFORCEMENT-LEDGER.md` and nothing stronger.
It does **NOT** satisfy "black-box integration tests against real supported Claude Code builds"
(requirement R3), because a subprocess invocation of a hook script is not a real Claude Code
event dispatch: it proves the *script's* behavior, not that the dispatcher routed to it, nor
that the host honors the exit code by aborting the call. R3's status is
`incomplete -- not satisfiable in this environment`, recorded as such in the ledger, and this
suite must never be cited as closing it.

SAFETY
------
No payload in the corpus is ever executed. Each one is handed to a guard as *inspection input*
and the guard's own verdict is read. Every case additionally carries a side-effect oracle that
asserts the repository HEAD sha is byte-identical before and after the invocation, so a case
that somehow did mutate state would fail loudly rather than pass quietly. The detection-witness
cases all use the harmless `status` subcommand -- a disclosed substitution that is valid because
both `_command_token_index()` and the regex anchor classes are subcommand-independent.

FALSIFICATION CLAUSE
--------------------
`expected_verdict` in the corpus is a HYPOTHESIS this suite confirms or refutes. If an observed
outcome disagrees with the published one, the correct response is to fix the PUBLISHED claim to
match reality -- not to relax this assertion. A lane whose product is "verified, not asserted"
may not make its own analysis unfalsifiable.

Run: python3 -m pytest hooks/tests/test_blackbox_integration.py -q
Side effect: writes the run manifest consumed by
`scripts/check-enforcement-evidence.py --coverage`.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = ROOT / "hooks" / "tests" / "fixtures" / "adversarial_corpus.json"
MANIFEST_PATH = ROOT / "hooks" / "tests" / ".enforcement-run-manifest.json"
CLASSIFIER = ROOT / "hooks" / "lib" / "git_command_classifier.py"
BASH_SAFETY = ROOT / "hooks" / "pretool-bash-safety.sh"
GIT_GUARD = ROOT / "hooks" / "pretool-git-privilege-guard.py"

CORPUS = json.loads(CORPUS_PATH.read_text(encoding="utf8"))

# Results accumulate here and are flushed to the manifest by the session-scoped fixture below,
# so `executed` (what actually ran) and `emitted` (what the manifest contains) are the same
# object by construction. --coverage asserts executed == emitted == corpus.
_RESULTS: list[dict] = []
_EXECUTED: list[str] = []


def _head_sha():
    """Side-effect oracle: the repository HEAD, read before and after every invocation."""
    proc = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                          capture_output=True, text=True, timeout=30)
    return proc.stdout.strip() or "unborn"


def _clean_env():
    """No overnight actor, no inherited grant -- the least-privileged interactive shape."""
    env = dict(os.environ)
    for key in ("CLAUDE_OVERNIGHT_ACTOR", "CLAUDE_ALLOW_TASK_ID", "CP_ENFORCE_MODE"):
        env.pop(key, None)
    return env


def _anchor_classes():
    """Read both anchor classes from source rather than restating them here."""
    sh_line = next(l for l in BASH_SAFETY.read_text(encoding="utf8").split("\n")
                   if l.startswith("GIT_CMD_RE="))
    py_line = next(l for l in GIT_GUARD.read_text(encoding="utf8").split("\n")
                   if l.startswith("GIT_COMMAND_RE"))

    def first_quoted(line):
        start = line.find("'")
        return line[start + 1:line.find("'", start + 1)]

    return first_quoted(sh_line), first_quoted(py_line)


ERE_ANCHOR, PY_ANCHOR = _anchor_classes()


def _run_classifier(payload):
    proc = subprocess.run([sys.executable, str(CLASSIFIER)], input=payload + "\n",
                          capture_output=True, text=True, timeout=60, env=_clean_env())
    try:
        parsed = json.loads(proc.stdout) if proc.returncode == 0 else None
    except json.JSONDecodeError:
        parsed = None
    return proc, parsed


def _run_hook(script, payload):
    """Drive a real hook script with a synthetic PreToolUse payload on stdin."""
    stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": payload}})
    argv = ["bash", str(script)] if script.suffix == ".sh" else [sys.executable, str(script)]
    return subprocess.run(argv, input=stdin, capture_output=True, text=True,
                          timeout=120, env=_clean_env(), cwd=str(ROOT))


def _observe(case):
    """Return (observed_verdict, provenance) from REAL captured process evidence."""
    payload = case["payload"]
    arch = case.get("gate_architecture")

    if case["case_class"] in ("gate_deny", "boundary_control"):
        script = GIT_GUARD if case["table_row"] == "H-031" else BASH_SAFETY
        proc = _run_hook(script, payload)
        verdict = "deny" if proc.returncode == 2 else (
            "allow" if proc.returncode == 0 else f"error_exit_{proc.returncode}")
        provenance = {
            "captured_from": f"subprocess exit code + stderr of {script.name}",
            "exit_code": proc.returncode,
            "stderr_head": proc.stderr.strip().split("\n")[0][:180] if proc.stderr.strip() else "",
            "stdout_head": proc.stdout.strip().split("\n")[0][:180] if proc.stdout.strip() else "",
        }
        return verdict, provenance

    # Detection witnesses: measure the detection layer, then apply the gate-architecture rule.
    proc, parsed = _run_classifier(payload)
    detected = bool(parsed)
    anchor = re.search(PY_ANCHOR, payload) is not None
    grep = subprocess.run(["grep", "-qE", ERE_ANCHOR + "[[:space:]]+"],
                          input=payload + "\n", capture_output=True, text=True, timeout=30)
    ere = grep.returncode == 0
    assert anchor == ere, (
        f"the two anchor engines disagree on {payload!r} (python={anchor}, ere={ere}); that is "
        f"RISK-2's drift class and must fail rather than be averaged away"
    )
    # Architecture A suppresses the regex fallback whenever the classifier parse succeeds, so
    # reachability there is classifier-only. Architecture B ORs the two unconditionally.
    reachable = detected if arch == "A" else (detected or anchor)
    provenance = {
        "captured_from": f"subprocess exit code + stdout of {CLASSIFIER.name}, "
                         f"plus both anchor classes read from guard source",
        "exit_code": proc.returncode,
        "classifier_detected": detected,
        "anchor_match": anchor,
        "gate_architecture": arch,
        "stdout_head": proc.stdout.strip()[:180],
    }
    return ("deny" if reachable else "not_detected"), provenance


def _record(case, observed, provenance):
    _EXECUTED.append(case["case_id"])
    _RESULTS.append({
        "case_id": case["case_id"],
        "release_or_commit": os.environ.get("GITHUB_SHA") or _head_sha(),
        "os_runtime": f"{platform.system()} {platform.release()} {platform.machine()} / "
                      f"Python {platform.python_version()}",
        "event": case["lifecycle_event"],
        "matcher_or_hook": case["guard_chain"],
        "expected_outcome": case["expected_verdict"],
        "observed_outcome": observed,
        "observed_source": provenance,
        "exit_stdout_stderr_summary": (
            f"exit={provenance.get('exit_code')} "
            f"stderr={provenance.get('stderr_head', '')!r} "
            f"stdout={provenance.get('stdout_head', '')!r}"
        ),
        "side_effect_oracle_result": case["_oracle_result"],
        "verdict": "pass" if observed == case["expected_verdict"] else "fail",
        "table_row": case["table_row"],
        "matrix_cell": case["matrix_cell"],
        "gate_architecture": case["gate_architecture"],
    })


@pytest.fixture(scope="session", autouse=True)
def _manifest(request):
    """Delete any stale manifest BEFORE the run, write the fresh one after.

    Deleting first is what makes the artifact evidence of execution rather than evidence of
    authorship: a fabricated-but-complete manifest left in the tree cannot survive the run.
    """
    MANIFEST_PATH.unlink(missing_ok=True)
    yield
    collected = getattr(request.session, "testscollected", 0)
    MANIFEST_PATH.write_text(json.dumps({
        "schema": "enforcement-run-manifest/v1",
        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "commit_sha": os.environ.get("GITHUB_SHA", _head_sha()),
        "os_runtime": f"{platform.system()} {platform.release()} {platform.machine()} / "
                      f"Python {platform.python_version()}",
        "collected_tests": int(collected),
        "executed_case_ids": _EXECUTED,
        "results": _RESULTS,
        "proof_layer": "component-tested",
        "not_a_substitute_for": "black-box integration tests against real supported Claude Code "
                               "builds (R3) -- a subprocess invocation is not an event dispatch",
    }, indent=2) + "\n", encoding="utf8")


@pytest.mark.parametrize("case", CORPUS, ids=[c["case_id"] for c in CORPUS])
def test_corpus_case_matches_published_expectation(case):
    """Drive one corpus case at the subprocess boundary and assert the published expectation."""
    before = _head_sha()
    observed, provenance = _observe(case)
    after = _head_sha()

    case = dict(case)
    case["_oracle_result"] = (
        "unchanged" if before == after else f"MUTATED {before} -> {after}"
    )
    _record(case, observed, provenance)

    assert before == after, (
        f"side-effect oracle tripped for {case['case_id']}: repository HEAD moved during a "
        f"guard invocation. Payloads are inspection input and must never be executed."
    )
    assert observed == case["expected_verdict"], (
        f"{case['case_id']}: published expected_verdict={case['expected_verdict']!r} but the "
        f"guard chain actually produced {observed!r}. Evidence: {provenance}. Per this lane's "
        f"falsification clause, correct the PUBLISHED claim to match reality."
    )


def test_every_mandated_witness_is_present_in_the_corpus():
    """The corpus may not silently drop a witness the published matrix mandates."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_enforcement_evidence", ROOT / "scripts" / "check-enforcement-evidence.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    mandated = {w["id"] for w in module.MANDATED_WITNESSES}
    present = {c.get("witness_id") for c in CORPUS if c.get("witness_id")}
    assert mandated <= present, (
        f"corpus is missing mandated cell witnesses {sorted(mandated - present)}; the published "
        f"residual matrix, the corpus and the drift probe must consume one declared source"
    )


def test_boundary_controls_exist_for_every_component_tested_row():
    """A deny-only corpus cannot distinguish enforcement from a guard that blocks everything."""
    deny_rows = {c["table_row"] for c in CORPUS if c["case_class"] == "gate_deny"}
    boundary_rows = {c["table_row"] for c in CORPUS if c["case_class"] == "boundary_control"}
    assert deny_rows, "corpus contains no gate-deny case at all"
    assert deny_rows == boundary_rows, (
        f"rows with a deny case but no boundary control: {sorted(deny_rows - boundary_rows)}; "
        f"rows with a boundary control but no deny case: {sorted(boundary_rows - deny_rows)}"
    )
