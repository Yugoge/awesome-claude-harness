#!/usr/bin/env python3
"""Tests for the /do unique-task-id mint + session-keyed sidecar (collision fix).

Covers the root-cause fix for the do-report task-id collision (memory
do-task-id-collision): handle_do_consent must mint a globally-unique pure-timestamp
task-id (reservation-backed, no same-second collision) and expose it via a
session-keyed sidecar, WITHOUT changing the consent-flag trust root (content stays
"true"). The agent then resolves its own task-id via $CLAUDE_CODE_SESSION_ID instead
of `ls -t ...consent... | head -1` (which aliased parallel /do sessions). The hook
writes no do-report: the /do main agent is its one writer (E8 (a)).

Run: python3 hooks/tests/test_do_taskid_mint.py
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "prompt-workflow.py"

_spec = importlib.util.spec_from_file_location("prompt_workflow_under_test", HOOK)
pw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pw)

sys.path.insert(0, str(HOOK.parent / "lib"))
from harness_state_dir import harness_state_dir  # noqa: E402


def _state(name):
    """A state file under the root the hook resolves (CLAUDE_STATE_DIR), at call time."""
    return Path(harness_state_dir()) / name

TS_RE = re.compile(r"^\d{8}-\d{6}$")  # YYYYMMDD-HHMMSS — /close timestamp-pattern compatible


def _cleanup(sid):
    for p in (_state(f"claude-orchestrator-consent-{sid}.flag"),
              _state(f"claude-do-task-{sid}.json")):
        try:
            p.unlink()
        except OSError:
            pass


def test_minted_id_is_pure_timestamp():
    tid = pw._mint_unique_do_taskid()
    assert TS_RE.match(tid), f"task-id {tid!r} is not a pure YYYYMMDD-HHMMSS timestamp (would risk /close resolution)"


def test_reservation_prevents_same_second_collision():
    """Deterministically force the same-second case: pre-reserve the current
    second's flat marker, then mint must bump to a DIFFERENT id."""
    from datetime import datetime
    now_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    marker = _state(f"claude-do-resv-{now_ts}")
    fd = os.open(str(marker), os.O_CREAT | os.O_WRONLY, 0o600)  # occupy current second
    os.close(fd)
    minted = pw._mint_unique_do_taskid()
    assert minted != now_ts, f"mint returned {minted!r} == pre-reserved {now_ts!r}; reservation bump failed (collision possible)"
    assert TS_RE.match(minted), f"bumped id {minted!r} is not a pure timestamp"


def test_two_mints_differ():
    a = pw._mint_unique_do_taskid()
    b = pw._mint_unique_do_taskid()
    assert a != b, f"two consecutive mints collided: {a!r} == {b!r}"


def test_consent_flag_content_unchanged_and_sidecar_written():
    sid = "test-sid-" + next(tempfile._get_candidate_names())
    _cleanup(sid)
    try:
        pw.handle_do_consent(sid)
        flag = _state(f"claude-orchestrator-consent-{sid}.flag")
        sidecar = _state(f"claude-do-task-{sid}.json")
        # Trust root untouched: flag exists, content is exactly "true".
        assert flag.exists(), "consent flag not written"
        assert flag.read_text() == "true", f"consent flag content changed to {flag.read_text()!r} — breaks existence/true readers"
        # Sidecar carries the task-id, keyed by THIS session.
        assert sidecar.exists(), "task sidecar not written"
        data = json.loads(sidecar.read_text())
        assert data["session_id"] == sid, f"sidecar session_id {data.get('session_id')!r} != {sid!r}"
        assert TS_RE.match(data["task_id"]), f"sidecar task_id {data.get('task_id')!r} not a pure timestamp"
        assert "created_at" in data and data["created_at"], "sidecar missing created_at"
    finally:
        _cleanup(sid)


def test_distinct_sessions_get_distinct_sidecars():
    sid_a = "test-A-" + next(tempfile._get_candidate_names())
    sid_b = "test-B-" + next(tempfile._get_candidate_names())
    _cleanup(sid_a); _cleanup(sid_b)
    try:
        pw.handle_do_consent(sid_a)
        pw.handle_do_consent(sid_b)
        a = json.loads(_state(f"claude-do-task-{sid_a}.json").read_text())
        b = json.loads(_state(f"claude-do-task-{sid_b}.json").read_text())
        assert a["task_id"] != b["task_id"], f"two sessions aliased to one task-id {a['task_id']!r} — the collision is back"
        assert a["session_id"] == sid_a and b["session_id"] == sid_b
    finally:
        _cleanup(sid_a); _cleanup(sid_b)


def test_consent_writes_no_do_report():
    """E8 (a): the /do prompt's hook mints the id and writes the sidecar, and
    nothing else in the project: the do-report's one writer is the main agent
    (commands/do.md Step 5)."""
    sid = "test-sid-" + next(tempfile._get_candidate_names())
    _cleanup(sid)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            project = Path(tmp) / "project"
            project.mkdir()
            env = {**os.environ, "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
                   "CLAUDE_PROJECT_DIR": str(project), "PYTHONDONTWRITEBYTECODE": "1"}
            proc = subprocess.run(
                [sys.executable, str(HOOK)], capture_output=True, text=True, cwd=project, env=env,
                input=json.dumps({"session_id": sid, "cwd": str(project), "prompt": "/do fix the widget",
                                  "hook_event_name": "UserPromptSubmit"}), timeout=60)
            assert proc.returncode == 0, proc.stderr
            tid = json.loads(_state(f"claude-do-task-{sid}.json").read_text())["task_id"]
            assert f"[/do] task-id minted: {tid}" in proc.stdout, proc.stdout
            assert not (project / "docs").exists(), \
                f"the hook wrote a project artifact: {sorted(project.rglob('*'))}"
    finally:
        _cleanup(sid)


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
