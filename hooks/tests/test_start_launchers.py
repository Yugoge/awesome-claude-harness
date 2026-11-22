"""hooks/sessionstart-launch.py and hooks/subagentstart-launch.py: prompt-workflow.py at SessionStart (P2-4)
and SubagentStart (P2-3), as rules of the one Python registration each event has (P12-L7, lib/hook_launch.py).

- settings.json registers each launcher, once, in place of the event's existing Python hook (check-todo-md-sync.py,
  subagentstart-record.py), on every source and every agent type, and no other Python process on the event.
- The one launcher process runs both hooks at the same time, each in a fork of it (lib/rule_fork: no interpreter
  starts again, no two hook files share one), the existing one first in the table: the per-hook record (the channel
  the replay suite reads) names both, in that order, each run as a fork, not as a process of its own. Neither has
  ``after``: neither writes a file on these events (each run leaves the session's home, state, temp and project
  directories as they were), so neither reads what the other writes.
- The existing hook's own result (exit status, stdout, stderr) is what it gives alone, and its text reaches the
  model as before, now beside prompt-workflow.py's PROJECT_ROOT and HARNESS_ROOT lines; when it prints nothing the
  launcher's answer is prompt-workflow.py's alone, byte for byte.
- SubagentStart's third rule, subagentstart-scratch.py, makes the agent's own scratch directory (a directory, no
  file) and prints nothing (LATER).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(HOOKS))

from lib import hook_launch, launch_settings  # noqa: E402

PW = "prompt-workflow.py"
LAUNCHERS = {"SessionStart": ("sessionstart-launch.py", "check-todo-md-sync.py"),
             "SubagentStart": ("subagentstart-launch.py", "subagentstart-record.py")}
COMMAND = 'python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/%s"'
# Rules after those two: SubagentStart's makes the agent's own scratch directory and prints nothing.
LATER = {"SessionStart": [], "SubagentStart": [("subagentstart-scratch.py", None, 5)]}


def _env(tmp_path: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_"))}
    (tmp_path / "state").mkdir(exist_ok=True)
    env.update(HOME=str(tmp_path / "home"), CLAUDE_CONFIG_DIR=str(tmp_path / "home" / ".claude"),
               CLAUDE_STATE_DIR=str(tmp_path / "state"), TMPDIR=str(tmp_path),
               GIT_CEILING_DIRECTORIES=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    return env


def _payload(tmp_path: Path, event: str, **extra) -> dict:
    transcript = tmp_path / "transcript.jsonl"
    transcript.touch()
    (tmp_path / "proj").mkdir(exist_ok=True)
    return {"session_id": "s1", "transcript_path": str(transcript), "cwd": str(tmp_path / "proj"),
            "hook_event_name": event, **extra}


def _alone(script: Path, payload: dict, env: dict):
    p = subprocess.run([sys.executable, str(script)], input=json.dumps(payload).encode(), capture_output=True,
                       env=env, cwd=payload["cwd"], timeout=120)
    return p.returncode, p.stdout.decode(), p.stderr.decode()


def _launched(launcher: Path, payload: dict, env: dict):
    """The launcher's (exit status, stdout, stderr) and its per-hook records (lib/hook_launch.py RECORD_ENV)."""
    before = _files(Path(env["TMPDIR"]))
    r, w = os.pipe()
    try:
        p = subprocess.run([sys.executable, str(launcher)], input=json.dumps(payload).encode(), capture_output=True,
                           env=dict(env, **{hook_launch.RECORD_ENV: str(w)}), pass_fds=(w,), cwd=payload["cwd"],
                           timeout=240)
    finally:
        os.close(w)
    with os.fdopen(r, "rb") as fh:
        records = [json.loads(line) for line in fh.read().decode().splitlines()]
    assert _files(Path(env["TMPDIR"])) == before, "a start hook wrote a file (a rule reading it would need after)"
    return (p.returncode, p.stdout.decode(), p.stderr.decode()), records


def _context(stdout: str, event: str) -> str:
    out = json.loads(stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == event, out
    return out["hookSpecificOutput"]["additionalContext"]


def _roots(project: str, harness: Path) -> str:
    return f"PROJECT_ROOT={project}\nHARNESS_ROOT={harness}"


def _files(root: Path) -> dict:
    """Every file under `root` with its size and mtime: what a run wrote there."""
    return {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}


def _one_process_both_hooks(records, existing: str, alone, later=()) -> None:
    assert [r["hook"] for r in records] == ["hooks/" + existing, "hooks/" + PW] + ["hooks/" + f for f in later], records
    # each in a fork of the launcher (lib/hook_launch.py `how`): no process of its own ("process", the fallback)
    assert {r["how"] for r in records} == {"fork"}, records
    assert all((r["rc"], r["stdout"], r["stderr"]) == (0, "", "") for r in records[2:]), records
    first = records[0]
    assert (first["rc"], first["stdout"], first["stderr"]) == alone, (first, alone)
    assert records[1]["rc"] == 0 and records[1]["stderr"] == "", records[1]


# ------------------------------------------------------------------ registrations

@pytest.mark.parametrize("event", sorted(LAUNCHERS))
def test_the_event_registers_its_launcher_once_for_every_source_and_no_other_python(event):
    launcher, existing = LAUNCHERS[event]
    groups = json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))["hooks"][event]
    commands = [h["command"] for g in groups for h in g["hooks"]]
    pythons = [c for c in commands if c.startswith("python")]
    assert pythons == [COMMAND % launcher], pythons
    group = next(g for g in groups if any(h["command"] == COMMAND % launcher for h in g["hooks"]))
    assert group.get("matcher", "") in ("", "*"), group  # every source, every agent type
    assert launch_settings.rules(str(ROOT), "hooks/" + launcher) == [(existing, None, 60), (PW, None, 60)] + LATER[event]
    expanded = launch_settings.expand({"hooks": {event: groups}}, str(ROOT))["hooks"][event]
    names = [h["command"] for g in expanded for h in g["hooks"]]
    at = commands.index(COMMAND % launcher)  # the existing hook keeps its place, prompt-workflow.py after it
    n = 2 + len(LATER[event])
    assert names[at:at + n] == [COMMAND % f for f in (existing, PW, *(r[0] for r in LATER[event]))], names
    assert names[:at] + names[at + n:] == commands[:at] + commands[at + 1:], names


# ------------------------------------------------------------------ SessionStart

def _drifted_home(tmp_path: Path) -> Path:
    """A harness home whose /drift command's text has a step its todo script lacks: check-todo-md-sync.py warns."""
    home = tmp_path / "harness"
    shutil.copytree(HOOKS, home / "hooks", ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "settings.json", home / "settings.json")
    (home / "policies").mkdir()
    (home / "scripts" / "todo").mkdir(parents=True)
    (home / "commands").mkdir()
    (home / "scripts" / "todo" / "drift.py").write_text(
        "import json\nprint(json.dumps([{'content': 'Step 1: a', 'status': 'pending', 'activeForm': 'a'}]))\n")
    (home / "commands" / "drift.md").write_text("### Step 1: a\n### Step 2: b\n")
    return home


@pytest.mark.parametrize("source", ["startup", "resume", "clear", "compact"])
def test_session_start_runs_the_drift_check_and_the_roots_in_one_process(tmp_path, source):
    home = _drifted_home(tmp_path)
    env, payload = _env(tmp_path), _payload(tmp_path, "SessionStart", source=source)
    alone = _alone(home / "hooks" / "check-todo-md-sync.py", payload, env)
    assert alone == (0, "[todo-md-sync] drift: missing in .py — Step 2\n", ""), alone
    (code, out, err), records = _launched(home / "hooks" / "sessionstart-launch.py", payload, env)
    assert code == 0 and err == "", (code, err)
    _one_process_both_hooks(records, "check-todo-md-sync.py", alone)
    # the warning reaches the model as before (a SessionStart hook's plain stdout is context), the roots after it
    assert _context(out, "SessionStart") == alone[1].strip() + "\n" + _roots(payload["cwd"], home)
    assert _context(records[1]["stdout"], "SessionStart") == _roots(payload["cwd"], home)


def test_session_start_in_sync_answers_with_the_roots_alone(tmp_path):
    env, payload = _env(tmp_path), _payload(tmp_path, "SessionStart", source="compact")
    alone = _alone(HOOKS / "check-todo-md-sync.py", payload, env)
    assert alone == (0, "", ""), alone  # this tree's todo scripts and command texts agree
    (code, out, err), records = _launched(HOOKS / "sessionstart-launch.py", payload, env)
    _one_process_both_hooks(records, "check-todo-md-sync.py", alone)
    assert (code, err) == (0, "") and out == records[1]["stdout"] == _alone(HOOKS / PW, payload, env)[1]
    assert _context(out, "SessionStart") == _roots(payload["cwd"], ROOT)


# ------------------------------------------------------------------ SubagentStart

def test_subagent_start_joins_the_record_and_the_roots_in_one_process(tmp_path):
    env, payload = _env(tmp_path), _payload(tmp_path, "SubagentStart", agent_id="a1", agent_type="dev")
    alone = _alone(HOOKS / "subagentstart-record.py", payload, env)
    assert alone[0] == 0 and alone[2] == "" and "dev" in _context(alone[1], "SubagentStart"), alone
    (code, out, err), records = _launched(HOOKS / "subagentstart-launch.py", payload, env)
    assert code == 0 and err == "", (code, err)
    _one_process_both_hooks(records, "subagentstart-record.py", alone, ["subagentstart-scratch.py"])
    assert _context(out, "SubagentStart") == \
        _context(alone[1], "SubagentStart") + "\n" + _roots(payload["cwd"], ROOT)


def test_subagent_start_outside_the_roster_answers_with_the_roots_alone(tmp_path):
    env, payload = _env(tmp_path), _payload(tmp_path, "SubagentStart", agent_id="a2", agent_type="general-purpose")
    alone = _alone(HOOKS / "subagentstart-record.py", payload, env)
    assert alone == (0, "", ""), alone  # no record for an agent outside agents/
    (code, out, err), records = _launched(HOOKS / "subagentstart-launch.py", payload, env)
    _one_process_both_hooks(records, "subagentstart-record.py", alone, ["subagentstart-scratch.py"])
    assert (code, err) == (0, "") and out == records[1]["stdout"] == _alone(HOOKS / PW, payload, env)[1]
    assert _context(out, "SubagentStart") == _roots(payload["cwd"], ROOT)
