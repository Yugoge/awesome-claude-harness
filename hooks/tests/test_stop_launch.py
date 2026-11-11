"""Tests for hooks/stop-launch.py, the one registered Stop hook (P5 R10, R12; A10, A11, A22).

The launcher runs the Stop coordinator and relays it; when the coordinator cannot decide it
decides alone on the transcript reader (hooks/lib/command_span.py) and the overnight window
(hooks/lib/overnight.py's window_open, P2's, run as merged on the session's own state record).
Each case runs a scratch copy of the launcher with the modules it loads and a scratch
coordinator (broken, slow, passing), so no case touches the tree's own files.

Run with: python3 -m pytest hooks/tests/test_stop_launch.py -q
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "hooks"
LAUNCHER = HOOKS / "stop-launch.py"
SID = "8b2f4c1d-6a3e-4f70-9d12-3c5e7a9b0f14"
LINE = "COMMAND_GATE instrument failure: {}. The gate is broken; the human can type /stop\n"


def _typed(name: str, args: str = "") -> dict:
    return {"type": "user", "sessionId": SID, "message": {"role": "user", "content":
            f"<command-message>{name}</command-message>\n<command-name>/{name}</command-name>\n"
            f"<command-args>{args}</command-args>"}}


def _transcript(path: Path, *commands: str) -> Path:
    records = []
    for name in commands:
        records += [{"type": "queue-operation", "operation": "enqueue", "content": f"/{name}"}, _typed(name),
                    {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}]
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def _scratch(tmp_path: Path, coordinator: str | None, *, timeout: int | None = None,
             whole: bool = False) -> Path:
    """A scratch harness: the launcher and the modules it loads (``whole``: all of hooks/
    and commands/), the coordinator replaced by ``coordinator`` source (None: missing)."""
    home = tmp_path / "harness"
    hooks = home / "hooks"
    if whole:
        shutil.copytree(HOOKS, hooks, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    else:
        (hooks / "lib").mkdir(parents=True)
        shutil.copy(LAUNCHER, hooks / LAUNCHER.name)
        for name in ("command_span.py", "stop-commands.json", "overnight.py"):
            shutil.copy(HOOKS / "lib" / name, hooks / "lib" / name)
    shutil.copytree(REPO / "commands", home / "commands", dirs_exist_ok=True)
    if timeout is not None:
        text = (hooks / LAUNCHER.name).read_text(encoding="utf-8")
        assert "COORDINATOR_TIMEOUT = 280" in text
        (hooks / LAUNCHER.name).write_text(text.replace("COORDINATOR_TIMEOUT = 280", f"COORDINATOR_TIMEOUT = {timeout}"))
    target = hooks / "stop-workflow-coordinator.py"
    if coordinator is None:
        target.unlink(missing_ok=True)
    else:
        target.write_text(coordinator, encoding="utf-8")
    return hooks


def _stop(tmp_path: Path, hooks: Path, *commands: str, gate: str | None = "block") -> subprocess.CompletedProcess:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    transcript = _transcript(tmp_path / "transcript.jsonl", *commands)
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_COMMAND_GATE"}
    env.update({"CLAUDE_PROJECT_DIR": str(project), "HOME": str(tmp_path / "home")})
    if gate is not None:
        env["CLAUDE_COMMAND_GATE"] = gate
    payload = {"session_id": SID, "transcript_path": str(transcript), "cwd": str(project),
               "hook_event_name": "Stop", "stop_hook_active": False}
    return subprocess.run([sys.executable, str(hooks / LAUNCHER.name)], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=str(project), env=env, timeout=120)


BROKEN = "def broken(:\n"
SLOW = "import time\ntime.sleep(5)\n"


# ---------------------------------------------------------------- A10: a coordinator that cannot decide
@pytest.mark.parametrize("case", ["syntax error", "missing", "timeout"])
def test_a10_a_coordinator_that_cannot_decide_blocks_a_gated_span_naming_stop(tmp_path, case):
    source = {"syntax error": BROKEN, "missing": None, "timeout": SLOW}[case]
    hooks = _scratch(tmp_path, source, timeout=1 if case == "timeout" else None)
    done = _stop(tmp_path, hooks, "dev")
    assert done.returncode == 2, done.stderr
    assert done.stderr.startswith("COMMAND_GATE instrument failure: stop-workflow-coordinator.py ")
    assert done.stderr.endswith(". The gate is broken; the human can type /stop\n")
    assert {"syntax error": "exited 1 (SyntaxError", "missing": "is missing",
            "timeout": "ran past 1 s"}[case] in done.stderr
    assert "Traceback" not in done.stderr and done.stdout == ""


@pytest.mark.parametrize("case", ["syntax error", "timeout"])
@pytest.mark.parametrize("commands", [("dev", "stop"), ("spec",), ()])
def test_a10_after_the_humans_stop_or_with_no_gated_command_it_allows(tmp_path, case, commands):
    hooks = _scratch(tmp_path, BROKEN if case == "syntax error" else SLOW, timeout=1)
    done = _stop(tmp_path, hooks, *commands)
    assert (done.returncode, done.stderr, done.stdout) == (0, "", "")


def _state(tmp_path: Path, hours: float) -> None:
    """The session's own overnight record in the project, its end_time ``hours`` from now (UTC)."""
    claude = tmp_path / "project" / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    end = (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (claude / f"overnight-state-{SID}.json").write_text(json.dumps({"session_id": SID, "end_time": end}))


@pytest.mark.parametrize("gate", ["block", None])
def test_a10_an_open_window_blocks_whatever_the_latest_command(tmp_path, gate):
    """P2's window_open as merged, on the session's record: its end_time ahead and no human
    /stop since the /dev-overnight, a latest human /spec still blocks."""
    hooks = _scratch(tmp_path, BROKEN)
    _state(tmp_path, 1)
    done = _stop(tmp_path, hooks, "dev-overnight", "spec", gate=gate)
    assert done.returncode == 2 and done.stderr.startswith("COMMAND_GATE instrument failure: ")


@pytest.mark.parametrize(("hours", "commands", "code"), [
    (1, ("dev-overnight", "spec"), 2),   # the window open: blocked naming the failure and /stop
    (1, ("dev-overnight", "stop"), 0),   # the human's /stop closes the window
    (-1, ("dev-overnight", "spec"), 0),  # end_time passed: the window closed
    (None, ("spec",), 0),                # an ungated session with no overnight record
])
def test_a10_the_fallback_decides_on_the_merged_overnight_window(tmp_path, hours, commands, code):
    """The launcher's fallback with the tree's own merged hooks/lib/overnight.py and
    command_span.py loaded by path (no fake): window_open reaches timelock_released through
    command_span, the one transcript reader, so an open window blocks naming /stop, a closed
    one allows, and an ungated session allows."""
    hooks = _scratch(tmp_path, BROKEN)
    assert (hooks / "lib" / "overnight.py").read_bytes() == (HOOKS / "lib" / "overnight.py").read_bytes()
    if hours is not None:
        _state(tmp_path, hours)
    done = _stop(tmp_path, hooks, *commands)
    assert done.returncode == code, done.stderr
    assert done.stderr == (LINE.format("stop-workflow-coordinator.py exited 1 (SyntaxError: invalid syntax)")
                           if code else ""), done.stderr


def test_a10_a11_off_allows_even_a_broken_coordinator_and_an_open_window(tmp_path):
    hooks = _scratch(tmp_path, BROKEN)
    _state(tmp_path, 1)
    for commands in (("dev",), ("dev-overnight",)):
        assert _stop(tmp_path, hooks, *commands, gate="off").returncode == 0


@pytest.mark.parametrize("gate", [None, "advisory", "block"])
def test_a11_after_p5_d_any_value_but_off_blocks(tmp_path, gate):
    """A11 (P5-d): unset, `advisory` or `block`, a broken coordinator under a gated span
    blocks naming /stop; the human's /stop allows."""
    hooks = _scratch(tmp_path, BROKEN)
    assert _stop(tmp_path, hooks, "dev", gate=gate).returncode == 2
    assert _stop(tmp_path, hooks, "dev", "stop", gate=gate).returncode == 0


def test_a11_the_launcher_marks_the_coordinator_it_runs(tmp_path):
    """Arming option 1: the coordinator the launcher runs carries CLAUDE_STOP_LAUNCHER=1, which
    arms its gate; a session that loaded an older hook list runs the coordinator unmarked."""
    probe = "import os, sys\nsys.stdin.read()\nprint(os.environ.get('CLAUDE_STOP_LAUNCHER'))\n"
    hooks = _scratch(tmp_path, probe)
    done = _stop(tmp_path, hooks, "dev")
    assert (done.returncode, done.stdout) == (0, "1\n")


def test_a10_a_broken_stop_contract_leaves_the_launcher_deciding(tmp_path):
    """A10: with a syntax error in a scratch stop_contract.py and the real coordinator, a
    /dev span still blocks, the human's /stop allows, an ungated session allows; the
    launcher and the reader import nothing from stop_contract.py."""
    hooks = _scratch(tmp_path, (HOOKS / "stop-workflow-coordinator.py").read_text(), whole=True)
    (hooks / "lib" / "stop_contract.py").write_text(BROKEN)
    assert _stop(tmp_path, hooks, "dev").returncode == 2
    assert _stop(tmp_path, hooks, "dev", "stop").returncode == 0
    assert _stop(tmp_path, hooks, "spec").returncode == 0


def test_a9_a_broken_obligation_module_is_named_by_the_gate_and_stop_releases_it(tmp_path):
    """A9: a syntax error in a scratch obligation.py: an ungated session stops; a /dev span is
    blocked by the gate itself, naming the import error; after the human's /stop it stops."""
    hooks = _scratch(tmp_path, (HOOKS / "stop-workflow-coordinator.py").read_text(), whole=True)
    (hooks / "lib" / "obligation.py").write_text(BROKEN)
    assert _stop(tmp_path, hooks, "spec").returncode == 0
    done = _stop(tmp_path, hooks, "dev")
    assert done.returncode == 2 and done.stderr.startswith("COMMAND_GATE /dev: not complete"), done.stderr
    assert "gate instrument failure: SyntaxError" in done.stderr
    assert _stop(tmp_path, hooks, "dev", "stop").returncode == 0


# ---------------------------------------------------------------- A10: a deciding coordinator is relayed
@pytest.mark.parametrize("code", [0, 2])
def test_a10_the_coordinators_exit_stdout_and_stderr_are_relayed_verbatim(tmp_path, code):
    out = json.dumps({"status": "pass", "systemMessage": "Checkpoint snapshot refused: settings.json"})
    source = (f"import sys\nsys.stdin.read()\nsys.stdout.write({out!r} + '\\n')\n"
              f"sys.stderr.write('COMMAND_GATE /dev: not complete\\n')\nsys.exit({code})\n")
    hooks = _scratch(tmp_path, source)
    done = _stop(tmp_path, hooks, "dev")
    assert (done.returncode, done.stdout, done.stderr) == (code, out + "\n", "COMMAND_GATE /dev: not complete\n")


def test_a10_the_launcher_loads_only_stdlib_and_the_two_modules_and_copies_no_rule():
    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    # harness_switch: the harness switch's one test, the first statement of every registered hook
    assert imported <= set(sys.stdlib_module_names) | {"harness_switch"}, imported
    loads = {c.args[0].value for c in ast.walk(tree) if isinstance(c, ast.Call)
             and getattr(c.func, "id", "") == "_load" and isinstance(c.args[0], ast.Constant)}
    assert loads == {"command_span", "overnight"}
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert not defined & {"prompt_text", "span_opener", "slash_command", "active_command", "timelock_released",
                          "is_human_prompt", "window_open", "state_verdicts"}
    overnight = ast.parse((HOOKS / "lib" / "overnight.py").read_text(encoding="utf-8"))
    top = {a.name.split(".")[0] for n in overnight.body if isinstance(n, ast.Import) for a in n.names}
    top |= {n.module.split(".")[0] for n in overnight.body if isinstance(n, ast.ImportFrom) and n.module}
    assert top <= set(sys.stdlib_module_names) | {"__future__"}, top


# ---------------------------------------------------------------- A22: the Stop registration, the stubs
def test_a22_the_stop_group_is_one_entry_the_launcher_with_timeout_300():
    settings = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))
    hooks = [h for group in settings["hooks"]["Stop"] for h in group["hooks"]]
    launcher = [h for h in hooks if h["command"] == 'python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/stop-launch.py"']
    assert len(launcher) == 1 and launcher[0]["timeout"] == 300
    text = (REPO / "settings.json").read_text(encoding="utf-8")
    assert len(settings["hooks"]["Stop"]) == 1 and len(hooks) == 1
    for retired in ("stop-completion-gate", "stop-obligation-gate", "stop-do-report-gate", "stop-workflow-coordinator",
                    "stop-overnight-timelock", "CLAUDE_COMMAND_GATE"):  # the todo hooks: lane E's R19
        assert retired not in text, retired


@pytest.mark.parametrize("stub", ["stop-overnight-timelock.py", "stop-obligation-gate.py", "stop-completion-gate.py",
                                  "stop-do-report-gate.py"])
def test_a22_each_retired_stop_hook_is_a_one_line_stub_exiting_0(stub):
    text = (HOOKS / stub).read_text(encoding="utf-8")
    assert sum(line.startswith("# STUB:") for line in text.splitlines()) == 1
    done = subprocess.run([sys.executable, str(HOOKS / stub)], input="", capture_output=True, text=True)
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")


def test_a22_no_awaiting_input_or_g4_decider_remains():
    g4 = "evaluate_" + "required_values"  # spelled apart: A22's own grep of hooks/ and scripts/ finds nothing
    awaiting = subprocess.run(["git", "-C", str(REPO), "grep", "-n", "AWAITING_INPUT", "--", "commands/merge.md",
                               "commands/push.md", "commands/do.md", "hooks", ":!hooks/tests"], capture_output=True, text=True)
    decider = subprocess.run(["git", "-C", str(REPO), "grep", "-n", g4, "--", "hooks", "scripts"],
                             capture_output=True, text=True)
    assert (awaiting.returncode, awaiting.stdout, decider.returncode, decider.stdout) == (1, "", 1, "")
