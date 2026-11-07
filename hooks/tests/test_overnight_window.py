"""P2 rows 7-9, 11 and 14: the overnight time-lock's one parser, one locator,
window_open, closeout_gaps, stop_contract.timelock_released and the /stop helper.

Acceptance 6 (time-lock in any timezone, the locator per isolation kind),
8 (a forged token releases nothing; a human-typed /stop does) and 10 (the
closeout on disk) at unit level and through the real hooks as subprocesses,
on throwaway git repositories.

Run: python3 -m pytest hooks/tests/test_overnight_window.py -q
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "hooks"
sys.path.insert(0, str(HOOKS))
from lib import overnight, stop_contract  # noqa: E402

TIMELOCK = HOOKS / "stop-overnight-timelock.py"
LOOP = HOOKS / "posttool-overnight-loop.py"
BREAK_LOCK = REPO / "scripts" / "break-overnight-lock.py"
SID = "6f1e2d3c-4b5a-4978-8a6b-5c4d3e2f1a0b"


def _utc(hours: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def _z(hours: float) -> str:
    """A time as the launcher writes it (create-overnight-state.sh: ...Z)."""
    return _utc(hours).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state(root: Path, sid: str = SID, **fields) -> Path:
    record = {"session_id": sid, "end_time": _z(1), "start_time": _z(-1),
              "current_phase": "exploring", "worktree_path": str(root)}
    record.update(fields)
    path = root / ".claude" / f"overnight-state-{sid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    return path


def _record(text: str, **fields) -> dict:
    record = {"type": "user", "isSidechain": False, "origin": {"kind": "human"},
              "message": {"role": "user", "content": text}}
    record.update(fields)
    return record


def _command(name: str, args: str = "", **fields) -> dict:
    return _record(f"<command-message>{name}</command-message>\n<command-name>/{name}</command-name>\n"
                   f"<command-args>{args}</command-args>", **fields)


def _transcript(path: Path, *records: dict) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def _git(*args: str, cwd: Path) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    subprocess.run(["git", *args], cwd=str(cwd), env=env, check=True, capture_output=True)


def _run(hook: Path, payload: dict, env: dict | None = None, project: Path | None = None):
    environment = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    if project is not None:
        environment["CLAUDE_PROJECT_DIR"] = str(project)
    environment.update(env or {})
    return subprocess.run([sys.executable, str(hook)], input=json.dumps(payload), capture_output=True,
                          text=True, env=environment, timeout=30)


def _closeout(root: Path, sid: str = SID, summary_mtime: float | None = None) -> None:
    retro = root / "docs" / "dev" / "overnight" / sid / "retro-report-cycle1.json"
    retro.parent.mkdir(parents=True, exist_ok=True)
    retro.write_text("{}")
    summary = root / "docs" / "dev" / "overnight-summary-2026-11-01.md"
    summary.write_text("summary")
    if summary_mtime is not None:
        os.utime(summary, (summary_mtime, summary_mtime))


# ---------------------------------------------------------------- the parser


@pytest.mark.parametrize("value, expected", [
    ("2026-11-01T08:00:00Z", datetime(2026, 11, 1, 8, tzinfo=timezone.utc)),
    ("2026-11-01T16:00:00+08:00", datetime(2026, 11, 1, 8, tzinfo=timezone.utc)),
    ("2026-11-01T01:00:00-07:00", datetime(2026, 11, 1, 8, tzinfo=timezone.utc)),
    ("2026-11-01T08:00:00", datetime(2026, 11, 1, 8, tzinfo=timezone.utc)),  # naive = UTC
    ("not-a-date", None), ("", None), (None, None), (17, None),
])
def test_parse_end_time_is_utc(value, expected):
    parsed = overnight.parse_end_time(value)
    assert parsed == expected
    assert parsed is None or parsed.utcoffset() == timedelta(0)


@pytest.mark.parametrize("fields", [
    {"current_phase": "completed"}, {"status": "cancelled"},
    {"terminal_status": "cancelled_by_user"}, {"isolation_released_at": "2026-11-01T00:00:00Z"},
])
def test_no_state_field_closes_the_window(fields):
    verdicts = overnight.state_verdicts({"session_id": SID, "end_time": _z(1), **fields})
    assert verdicts.before_end


@pytest.mark.parametrize("end_time", [_z(-1), "not-a-date", None])
def test_a_passed_or_unreadable_end_time_closes_the_window(end_time):
    assert not overnight.state_verdicts({"session_id": SID, "end_time": end_time}).before_end


# ------------------------------------------------- acceptance 6: the time-lock


@pytest.mark.parametrize("tz", ["Asia/Shanghai", "America/Los_Angeles", "UTC"])
@pytest.mark.parametrize("form", ["z", "naive-utc"])
def test_the_lock_holds_about_an_hour_in_any_timezone(tmp_path, tz, form):
    end = _z(1) if form == "z" else _utc(1).replace(tzinfo=None).isoformat()
    _state(tmp_path, end_time=end)
    result = _run(TIMELOCK, {"session_id": SID}, {"TZ": tz}, project=tmp_path)
    assert result.returncode == 2, result.stderr
    assert "TIME-LOCK ACTIVE" in result.stderr and "Time remaining: 0h 59m" in result.stderr


def test_a_human_spec_inside_the_window_still_blocks(tmp_path):
    _state(tmp_path)
    transcript = _transcript(tmp_path / "t.jsonl", _command("dev-overnight", "8h"), _command("spec", "x"),
                             _record("and keep going"))
    result = _run(TIMELOCK, {"session_id": SID, "transcript_path": str(transcript)}, project=tmp_path)
    assert result.returncode == 2 and "TIME-LOCK ACTIVE" in result.stderr


def test_after_end_time_the_closeout_gaps_are_named_on_stderr(tmp_path):
    _state(tmp_path, end_time=_z(-0.1), current_phase="completed", status="done")
    result = _run(TIMELOCK, {"session_id": SID}, project=tmp_path)
    assert result.returncode == 2
    gaps = overnight.closeout_gaps(json.loads((tmp_path / ".claude" / f"overnight-state-{SID}.json")
                                              .read_text()), tmp_path)
    assert len(gaps) == 2 and all(gap in result.stderr for gap in gaps)


def test_stop_hook_active_frees_nothing(tmp_path):
    _state(tmp_path)
    assert _run(TIMELOCK, {"session_id": SID, "stop_hook_active": True}, project=tmp_path).returncode == 2
    _state(tmp_path, end_time=_z(-0.1))
    assert _run(TIMELOCK, {"session_id": SID, "stop_hook_active": True}, project=tmp_path).returncode == 2


def test_another_sessions_state_is_never_used(tmp_path):
    _state(tmp_path, sid="other-session")
    assert overnight.locate(SID, {"cwd": str(tmp_path)}) == (None, None)
    result = _run(TIMELOCK, {"session_id": SID, "cwd": str(tmp_path)}, project=tmp_path)
    assert result.returncode == 0 and result.stderr == ""
    path = _state(tmp_path, sid=SID)
    path.write_text(json.dumps({"session_id": "other-session", "end_time": _z(1)}))
    assert _run(TIMELOCK, {"session_id": SID}, project=tmp_path).returncode == 0


@pytest.fixture
def isolation(tmp_path):
    """A main checkout with the session's state, a linked worktree, a fresh clone
    under <main root>/.claude/overnight-fresh-clones/ and one outside it, each a
    local clone of the main repository as the launcher makes it."""
    main = tmp_path / "main"
    main.mkdir()
    _git("init", "-q", "-b", "main", cwd=main)
    (main / "README.md").write_text("toy\n")
    _git("add", "README.md", cwd=main)
    _git("commit", "-q", "-m", "init", cwd=main)
    worktree = tmp_path / "wt"
    _git("worktree", "add", "-q", "-b", "overnight-wt", str(worktree), cwd=main)
    inner = main / ".claude" / "overnight-fresh-clones" / "night-1"
    outer = tmp_path / "elsewhere" / "night-1"
    for clone in (inner, outer):
        clone.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "-q", "--local", str(main / ".git"), str(clone), cwd=tmp_path)
    (main / "sub").mkdir()
    _state(main, worktree_path=str(worktree))
    return main, {"main root": main, "main subdirectory": main / "sub", "linked worktree": worktree,
                  "fresh clone inside": inner, "fresh clone outside": outer}


@pytest.mark.parametrize("kind", ["main root", "main subdirectory", "linked worktree",
                                  "fresh clone inside", "fresh clone outside"])
@pytest.mark.parametrize("channel", ["project dir", "payload cwd"])
def test_the_locator_finds_the_main_roots_state(isolation, kind, channel, monkeypatch):
    main, starts = isolation
    start = starts[kind]
    if channel == "project dir":
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(start))
        payload = {"session_id": SID}
    else:
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        payload = {"session_id": SID, "cwd": str(start)}
    monkeypatch.chdir(isolation[0].parent)
    state_file, record = overnight.locate(SID, payload)
    assert state_file == (main / ".claude" / f"overnight-state-{SID}.json").resolve()
    assert record["session_id"] == SID
    assert overnight.window_open(payload)
    assert overnight.locate("another-session", payload) == (None, None)


def test_a_session_whose_project_dir_is_the_worktree_is_locked(isolation):
    main, starts = isolation
    result = _run(TIMELOCK, {"session_id": SID, "cwd": str(starts["linked worktree"])},
                  project=starts["linked worktree"])
    assert result.returncode == 2 and "TIME-LOCK ACTIVE" in result.stderr


# ---------------------------------------- acceptance 8: what releases the lock


def test_timelock_released_reads_only_human_typed_records(tmp_path):
    released = stop_contract.timelock_released
    assert not released(tmp_path / "missing.jsonl")
    assert not released(_transcript(tmp_path / "a.jsonl", _command("dev-overnight", "8h")))
    assert released(_transcript(tmp_path / "b.jsonl", _command("dev-overnight", "8h"), _command("stop"),
                                _record("thanks")))
    assert released(_transcript(tmp_path / "c.jsonl", _command("dev-overnight", "8h"), _record("/stop")))
    # A later /dev-overnight opens a new window.
    assert not released(_transcript(tmp_path / "d.jsonl", _command("dev-overnight", "8h"), _command("stop"),
                                    _command("dev-overnight", "2h")))
    not_typed = {
        "isMeta": {"isMeta": True},
        "skill": {"isMeta": True, "sourceToolUseID": "toolu_01"},
        "scheduled": {"origin": {"kind": "scheduled"}},
        "subagent": {"isSidechain": True},
    }
    for name, fields in not_typed.items():
        path = _transcript(tmp_path / f"{name}.jsonl", _command("dev-overnight", "8h"), _command("stop", **fields))
        assert not released(path), name


def test_a_forged_token_and_the_helper_release_nothing_a_typed_stop_does(tmp_path):
    state_file = _state(tmp_path)
    end_time = json.loads(state_file.read_text())["end_time"]
    tokens = tmp_path / "state-dir"
    tokens.mkdir()
    (tokens / f"claude-stop-helper-auth-{SID}.json").write_text(
        json.dumps({"cmd": "stop", "session_id": SID, "expires_at": int(time.time()) + 30}))
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID")}
    env.update({"CLAUDE_PROJECT_DIR": str(tmp_path), "CLAUDE_USERINTENT_SENTINEL_DIR": str(tokens)})
    helper = subprocess.run([sys.executable, str(BREAK_LOCK)], capture_output=True, text=True, env=env,
                            cwd=str(tmp_path), timeout=30)
    assert helper.returncode == 0, helper.stderr
    after = json.loads(state_file.read_text())
    assert after["end_time"] == end_time and after["current_phase"] == "completed"
    session = _transcript(tmp_path / "t.jsonl", _command("dev-overnight", "8h"))
    payload = {"session_id": SID, "transcript_path": str(session)}
    held = _run(TIMELOCK, payload, project=tmp_path)
    assert held.returncode == 2 and "TIME-LOCK ACTIVE" in held.stderr
    todos = {**payload, "tool_name": "TodoWrite",
             "tool_input": {"todos": [{"content": "a", "status": "completed", "activeForm": "a"}]}}
    assert "OVERNIGHT LOOP" in _run(LOOP, todos, project=tmp_path).stdout
    # The same /stop text in a Skill-produced, scheduled or isMeta record releases nothing.
    _transcript(session, _command("dev-overnight", "8h"), _command("stop", isMeta=True),
                _command("stop", isMeta=True, sourceToolUseID="toolu_01"),
                _command("stop", origin={"kind": "scheduled"}))
    assert _run(TIMELOCK, payload, project=tmp_path).returncode == 2
    # The human types /stop: released with no closeout check (none is on disk).
    _transcript(session, _command("dev-overnight", "8h"), _command("stop"))
    released = _run(TIMELOCK, payload, project=tmp_path)
    assert released.returncode == 0 and "CLOSEOUT" not in released.stderr, released.stderr
    loop = _run(LOOP, todos, project=tmp_path)
    assert "OVERNIGHT LOOP" not in loop.stdout and "OVERNIGHT SESSION COMPLETE" in loop.stdout


# ------------------------------------------------- acceptance 10: the closeout


def test_closeout_on_disk_allows_with_a_dirty_tree(isolation):
    main, starts = isolation
    worktree = starts["linked worktree"]
    _state(main, end_time=_z(-0.1), start_time=_z(-2), worktree_path=str(worktree))
    (worktree / "README.md").write_text("uncommitted change\n")
    _closeout(worktree)
    result = _run(TIMELOCK, {"session_id": SID, "cwd": str(worktree)}, project=worktree)
    assert result.returncode == 0, result.stderr


def test_closeout_gaps_name_a_missing_retro_and_a_stale_summary(tmp_path):
    state = json.loads(_state(tmp_path, end_time=_z(-0.1), start_time=_z(-2)).read_text())
    assert overnight.closeout_gaps(state, tmp_path) == [
        f"{tmp_path}/docs/dev/overnight/{SID}/retro-report-cycle*.json: no PM retrospective report",
        f"{tmp_path}/docs/dev/overnight-summary-*.md: no summary written since start_time {state['start_time']}",
    ]
    _closeout(tmp_path, summary_mtime=_utc(-3).timestamp())  # written before this session started
    gaps = overnight.closeout_gaps(state, tmp_path)
    assert len(gaps) == 1 and "overnight-summary-*.md" in gaps[0]
    result = _run(TIMELOCK, {"session_id": SID}, project=tmp_path)
    assert result.returncode == 2 and gaps[0] in result.stderr
    (tmp_path / "docs" / "dev" / "overnight" / SID / "retro-report-cycle1.json").unlink()
    _closeout(tmp_path)
    (tmp_path / "docs" / "dev" / "overnight" / SID / "retro-report-cycle1.json").unlink()
    result = _run(TIMELOCK, {"session_id": SID}, project=tmp_path)
    assert result.returncode == 2 and "retro-report-cycle*.json: no PM retrospective report" in result.stderr
    _closeout(tmp_path)
    assert overnight.closeout_gaps(state, tmp_path) == []
    assert _run(TIMELOCK, {"session_id": SID}, project=tmp_path).returncode == 0
