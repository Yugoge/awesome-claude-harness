"""P5 acceptance A12's three cases that had no test of their own (follow-ups P5-25, P5-26, P5-27).

A12 (prompts/P5.md acceptance 12; prompts/short/P5.md A12) says, of the overnight time-lock:

  - end_time = now+1h, under TZ=Asia/Shanghai and TZ=America/Los_Angeles, any span -> rc 2;
  - a forged helper-auth token plus break-overnight-lock.py -> still rc 2;
  - break-overnight-lock.py touches no todos file (R13 dropped its todo force-complete).

The rc is the Stop's: each case runs the Stop hook as settings.json registers it
(hooks/stop-launch.py, which runs the coordinator and its completion phase, the gate's step 4),
on the real hooks/lib/overnight.py and scripts/break-overnight-lock.py, with a scratch HOME,
state dir (CLAUDE_STATE_DIR, where the /stop guard mints the token) and git repository.
P2's own time-lock cases (test_overnight_window.py) run the gate alone with no span.

Run: python3 -m pytest hooks/tests/test_overnight_a12_timelock_cases.py -q
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
LAUNCHER = REPO / "hooks" / "stop-launch.py"  # the registered Stop hook (settings.json, P5 R12)
BREAK_LOCK = REPO / "scripts" / "break-overnight-lock.py"
SID = "a12c0de5-7d3e-4b1a-9f20-5e6d7c8b9a01"
OTHER = "b0b0b0b0-1111-4222-8333-944444444444"
LOCK_TEXT = "COMMAND_GATE time-lock: overnight window open until "


# ---------------------------------------------------------------- the sandbox
@pytest.fixture
def sandbox(tmp_path):
    """A scratch HOME (with a CLI todos dir), state dir and project repository, and the
    environment every process of a case runs with (nothing of the real HOME or state)."""
    home, state, project = tmp_path / "home", tmp_path / "state", tmp_path / "project"
    for d in (home, state, project, tmp_path / "tmp"):
        d.mkdir()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE", "GIT_", "LANEB_")) and k not in ("TZ", "HOME", "TMPDIR")}
    env.update({
        "HOME": str(home), "TMPDIR": str(tmp_path / "tmp"), "CLAUDE_STATE_DIR": str(state),
        "CLAUDE_PROJECT_DIR": str(project), "CLAUDE_SESSION_ID": SID,
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    })
    for args in (("init", "-q", "-b", "main"), ("commit", "-q", "--allow-empty", "-m", "init")):
        subprocess.run(["git", *args], cwd=str(project), env=env, check=True, capture_output=True)
    return {"home": home, "state": state, "project": project, "env": env, "tmp": tmp_path}


def _z(hours: float) -> str:
    """A time as the launcher writes it (create-overnight-state.sh: UTC with Z)."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state(sb: dict, **fields) -> Path:
    project = sb["project"]
    record = {"session_id": SID, "start_time": _z(-1), "end_time": _z(1), "current_phase": "exploring",
              "main_root": str(project), "worktree_path": str(project), "protected_branch": "main",
              "isolation_active_until": _z(1)}
    record.update(fields)
    path = project / ".claude" / f"overnight-state-{SID}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(record))
    return path


def _typed(name: str, args: str = "") -> dict:
    """A human-typed slash command record, as the CLI writes it."""
    return {"type": "user", "isSidechain": False, "sessionId": SID, "origin": {"kind": "human"},
            "message": {"role": "user", "content": f"<command-message>{name}</command-message>\n"
                        f"<command-name>/{name}</command-name>\n<command-args>{args}</command-args>"}}


def _prompt(text: str) -> dict:
    return {"type": "user", "isSidechain": False, "sessionId": SID, "origin": {"kind": "human"},
            "message": {"role": "user", "content": text}}


def _tool(name: str, tool_input: dict, n: int, result: str = "ok") -> list:
    return [{"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": f"toolu_{n:02d}", "name": name, "input": tool_input}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"toolu_{n:02d}", "content": result}]}}]


def _todo(n: int, done: bool) -> list:
    status = "completed" if done else "pending"
    return _tool("TodoWrite", {"todos": [{"content": "step one", "status": status, "activeForm": "step one"},
                                         {"content": "step two", "status": status, "activeForm": "step two"}]}, n)


def _transcript(sb: dict, records: list) -> Path:
    path = sb["tmp"] / "transcript.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def _stop(sb: dict, transcript: Path | None, tz: str | None = None) -> subprocess.CompletedProcess:
    """One Stop of the main session through the registered Stop hook."""
    env = dict(sb["env"])
    if tz is not None:
        env["TZ"] = tz
    payload = {"session_id": SID, "cwd": str(sb["project"]), "hook_event_name": "Stop",
               "stop_hook_active": False}
    if transcript is not None:
        payload["transcript_path"] = str(transcript)
    return subprocess.run([sys.executable, str(LAUNCHER)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=str(sb["project"]), env=env, timeout=240)


def _lock_held(done: subprocess.CompletedProcess, end_time: str) -> None:
    """rc 2 by the time-lock, naming the record's end_time in UTC whatever TZ is."""
    assert done.returncode == 2, (done.returncode, done.stderr)
    assert done.stderr.startswith(LOCK_TEXT + end_time + ", 0h 59m left"), done.stderr


# -------------------------------------- P5-25: end_time = now+1h in two time zones, any span
SPANS = {
    "no transcript": None,
    "no command typed": [_prompt("hello")],
    "dev-overnight, checklist open": [_typed("dev-overnight", "8h"), *_todo(1, done=False)],
    "dev-overnight, checklist complete": [_typed("dev-overnight", "8h"), *_todo(1, done=True)],
    "dev-overnight then a plain prompt": [_typed("dev-overnight", "8h"), _prompt("keep going")],
    "dev-overnight then /dev": [_typed("dev-overnight", "8h"), _typed("dev", "fix x"), *_todo(1, done=True)],
    "dev-overnight then /do": [_typed("dev-overnight", "8h"), _typed("do", "y")],
    "dev-overnight then /commit": [_typed("dev-overnight", "8h"), _typed("commit")],
    "dev-overnight then /spec": [_typed("dev-overnight", "8h"), _typed("spec", "z")],
    "/stop, then a new dev-overnight": [_typed("dev-overnight", "2h"), _typed("stop"),
                                        _typed("dev-overnight", "1h")],
    "/dev with no dev-overnight record": [_typed("dev", "fix x")],
}


@pytest.mark.parametrize("span", list(SPANS))
@pytest.mark.parametrize("tz", ["Asia/Shanghai", "America/Los_Angeles"])
def test_a12_end_time_an_hour_ahead_holds_in_both_time_zones_in_any_span(sandbox, tz, span):
    end_time = _z(1)
    _state(sandbox, end_time=end_time)
    records = SPANS[span]
    _lock_held(_stop(sandbox, None if records is None else _transcript(sandbox, records), tz), end_time)


@pytest.mark.parametrize("tz", ["Asia/Shanghai", "America/Los_Angeles"])
def test_a12_the_time_zone_moves_neither_side_of_the_hour(sandbox, tz):
    """The control: the same record an hour past, under each TZ, holds nothing (no span, so
    nothing else blocks): end_time is read in UTC, never in local time."""
    _state(sandbox, end_time=_z(-1))
    passed = _stop(sandbox, None, tz)
    assert passed.returncode == 0 and LOCK_TEXT not in passed.stderr, passed.stderr


# -------------------------------------- P5-26: a forged helper-auth token plus the helper
def _helper(sb: dict, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {**sb["env"], **(extra_env or {})}
    return subprocess.run([sys.executable, str(BREAK_LOCK)], capture_output=True, text=True,
                          cwd=str(sb["project"]), env=env, timeout=60)


@pytest.mark.parametrize("expires_in", [30, 10 ** 9], ids=["minted-ttl", "far-future"])
def test_a12_a_forged_helper_auth_token_plus_the_helper_still_holds(sandbox, expires_in):
    """The agent writes the token itself, in the place and shape the /stop guard mints it
    (no human /stop, no user-intent sentinel), and runs the helper. The helper takes it and
    records its fields, but the time-lock is the transcript's human-typed /stop alone: rc 2."""
    end_time = _z(1)
    state_file = _state(sandbox, end_time=end_time)
    token = sandbox["state"] / f"claude-stop-helper-auth-{SID}.json"
    token.write_text(json.dumps({"cmd": "stop", "session_id": SID, "expires_at": int(time.time()) + expires_in}))
    helper = _helper(sandbox)
    assert helper.returncode == 0, helper.stderr  # observed: the forged token is taken
    assert not token.exists()
    after = json.loads(state_file.read_text())
    assert after["end_time"] == end_time and after["current_phase"] == "completed"
    run = f"python3 {BREAK_LOCK}"
    transcript = _transcript(sandbox, [
        _typed("dev-overnight", "8h"), *_todo(1, done=False),
        *_tool("Write", {"file_path": str(token), "content": "{}"}, 2),
        *_tool("Bash", {"command": run}, 3, helper.stdout)])
    for tz in (None, "Asia/Shanghai", "America/Los_Angeles"):
        _lock_held(_stop(sandbox, transcript, tz), end_time)
    # The human types /stop: the same record, the same state file, now released.
    with transcript.open("a") as handle:
        handle.write(json.dumps(_typed("stop")) + "\n")
    released = _stop(sandbox, transcript)
    assert released.returncode == 0 and LOCK_TEXT not in released.stderr, released.stderr


def test_a12_a_forged_token_of_another_session_holds_too(sandbox):
    """A token named for another session is found by the helper's fallback glob; still rc 2."""
    end_time = _z(1)
    _state(sandbox, end_time=end_time)
    (sandbox["state"] / f"claude-stop-helper-auth-{OTHER}.json").write_text(
        json.dumps({"cmd": "stop", "session_id": OTHER, "expires_at": int(time.time()) + 30}))
    assert _helper(sandbox).returncode == 0
    transcript = _transcript(sandbox, [_typed("dev-overnight", "8h"), _prompt("go on")])
    _lock_held(_stop(sandbox, transcript, "America/Los_Angeles"), end_time)


# -------------------------------------- P5-27: the helper touches no todos file
# Runs the helper in-process under an audit hook that logs every file event (open, list,
# remove, rename, chmod, utime, ...) and every subprocess, so a read of a todos file counts too.
AUDITED = """
import json, os, runpy, sys
log_fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
script = sys.argv[2]
EVENTS = ("open", "os.listdir", "os.scandir", "glob.glob", "os.remove", "os.rename", "os.replace",
          "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.utime", "os.truncate", "os.link",
          "os.symlink", "shutil.copyfile", "shutil.copytree", "shutil.rmtree", "shutil.move",
          "subprocess.Popen", "os.exec", "os.posix_spawn", "os.system")
seen = []
def hook(event, args):
    if event in EVENTS:
        seen.append([event, [a if isinstance(a, (str, int, type(None))) else repr(a) for a in args]])
sys.addaudithook(hook)
sys.argv = [script]
code = 0
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit as exc:
    code = exc.code if isinstance(exc.code, int) else 1
os.write(log_fd, json.dumps({"code": code, "events": seen}).encode())
os.close(log_fd)
sys.exit(code)
"""


def _tree(*roots: Path, skip: Path | None = None) -> dict:
    snap = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            if skip is not None and path == skip:
                continue
            st = path.lstat()  # a directory's mtime moves with the state record's rename: not compared
            snap[str(path)] = ((st.st_mode, st.st_mtime_ns, path.read_bytes()) if path.is_file()
                               else (st.st_mode, None, None))
    return snap


@pytest.mark.parametrize("case", ["no overnight state", "state, no token", "state and a token"])
def test_a12_break_overnight_lock_touches_no_todos_file(sandbox, case):
    config = sandbox["tmp"] / "config"
    todos_dirs = [sandbox["home"] / ".claude" / "todos", config / "todos"]
    pending = [{"content": "step one", "status": "pending", "activeForm": "step one"},
               {"content": "step two", "status": "in_progress", "activeForm": "step two"}]
    for d in todos_dirs:
        d.mkdir(parents=True)
        for sid in (SID, OTHER):
            (d / f"{sid}-agent-{sid}.json").write_text(json.dumps(pending))
    old = time.time() - 3600
    for d in todos_dirs:
        for f in d.iterdir():
            os.utime(f, (old, old))
    state_file = None
    if case != "no overnight state":
        state_file = _state(sandbox)
    if case == "state and a token":
        (sandbox["state"] / f"claude-stop-helper-auth-{SID}.json").write_text(
            json.dumps({"cmd": "stop", "session_id": SID, "expires_at": int(time.time()) + 30}))
    before = _tree(sandbox["home"], config, sandbox["project"], skip=state_file)
    log = sandbox["tmp"] / "audit.json"
    env = {**sandbox["env"], "CLAUDE_CONFIG_DIR": str(config)}
    done = subprocess.run([sys.executable, "-c", AUDITED, str(log), str(BREAK_LOCK)], capture_output=True,
                          text=True, cwd=str(sandbox["project"]), env=env, timeout=60)
    expected = {"no overnight state": 0, "state, no token": 3, "state and a token": 0}[case]
    assert done.returncode == expected, done.stderr
    audit = json.loads(log.read_text())
    assert audit["code"] == expected
    # Nothing on disk under HOME, the config dir or the project changed but the state record.
    assert _tree(sandbox["home"], config, sandbox["project"], skip=state_file) == before
    # And no file event or subprocess of the helper names a todos file or directory.
    marks = [str(d) for d in todos_dirs] + ["/todos/", "/todos"]
    touched = [e for e in audit["events"]
               if any(isinstance(a, str) and any(m in a for m in marks) for a in e[1])]
    assert touched == [], touched
    assert any(e[0] == "open" for e in audit["events"])  # the hook did see the helper's files
    if state_file is not None:
        assert json.loads(state_file.read_text())["current_phase"] == "completed"
