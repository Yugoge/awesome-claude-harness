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


def _transcript(path: Path, *commands: str, extra=()) -> Path:
    records = []
    for name in commands:
        records += [{"type": "queue-operation", "operation": "enqueue", "content": f"/{name}"}, _typed(name),
                    {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}]
    path.write_text("".join(json.dumps(r) + "\n" for r in [*records, *extra]), encoding="utf-8")
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


def _stop(tmp_path: Path, hooks: Path, *commands: str, gate: str | None = "block", extra=()) -> subprocess.CompletedProcess:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    transcript = _transcript(tmp_path / "transcript.jsonl", *commands, extra=extra)
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_COMMAND_GATE", "CLAUDE_SUBAGENT_TIME_LIMIT_MINUTES")}
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
    assert "Traceback" not in done.stderr and done.stdout == ""
    if case == "timeout":  # no verdict, as the coordinator says of its gate out of time
        assert done.stderr == "".join(_coordinator().no_verdict_text("stop-workflow-coordinator.py", 1))
        return
    assert done.stderr.startswith("COMMAND_GATE instrument failure: stop-workflow-coordinator.py ")
    assert done.stderr.endswith(". The gate is broken; the human can type /stop\n")
    assert {"syntax error": "exited 1 (SyntaxError", "missing": "is missing"}[case] in done.stderr


def test_a10_a_session_record_that_cannot_be_read_in_time_blocks_as_no_verdict(tmp_path):
    """A coordinator out of time and a transcript whose reading never returns (a FIFO no one writes: open
    blocks, whatever the machine's speed): the fallback's reading is bounded by READ_LIMIT (1 s here), and the
    stop is decided as a coordinator with no verdict: exit 2 and the same text, nothing verified."""
    hooks = _scratch(tmp_path, SLOW, timeout=1)
    launcher = hooks / LAUNCHER.name
    launcher.write_text(launcher.read_text(encoding="utf-8").replace("READ_LIMIT = 5", "READ_LIMIT = 1"))
    project = tmp_path / "project"
    project.mkdir()
    fifo = tmp_path / "transcript.jsonl"
    os.mkfifo(fifo)
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_COMMAND_GATE"}
    env.update({"CLAUDE_PROJECT_DIR": str(project), "HOME": str(tmp_path / "home"), "CLAUDE_COMMAND_GATE": "block"})
    payload = {"session_id": SID, "transcript_path": str(fifo), "cwd": str(project), "hook_event_name": "Stop",
               "stop_hook_active": False}
    done = subprocess.run([sys.executable, str(launcher)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=str(project), env=env, timeout=30)  # the old launcher never returns
    assert (done.returncode, done.stdout) == (2, ""), done.stderr
    assert done.stderr == "".join(_coordinator().no_verdict_text("stop-workflow-coordinator.py", 1))


def test_a10_the_launchers_worst_case_fits_its_registration():
    """The coordinator's limit, then the fallback's bounded reading and the refusal record's process: their sum
    stays under the Stop registration's timeout."""
    launcher = _launcher_module()
    settings = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))
    registered = settings["hooks"]["Stop"][0]["hooks"][0]["timeout"]
    assert launcher.COORDINATOR_TIMEOUT + launcher.READ_LIMIT + launcher.RECORD_LIMIT < registered


def _launch_with_overnight(tmp_path, overnight_source, *commands):
    """A scratch launcher whose coordinator cannot decide and whose overnight.py is ``overnight_source``."""
    hooks = _scratch(tmp_path, BROKEN)
    (hooks / "lib" / "overnight.py").write_text(overnight_source, encoding="utf-8")
    return _stop(tmp_path, hooks, *commands)


@pytest.mark.parametrize("commands", [("dev",), ("help",)])
def test_a10_a_launcher_that_cannot_load_overnight_py_blocks_and_names_it(tmp_path, commands):
    """No window can be read: no verdict, as for a record not read in time (exit 2, the existing text), for a gated
    span and for a session with no gated command alike, and the text names the module and why it failed."""
    done = _launch_with_overnight(tmp_path, "def broken(:\n", *commands)
    assert done.returncode == 2, done.stderr
    assert done.stderr.startswith("COMMAND_GATE instrument failure: stop-workflow-coordinator.py exited 1")
    assert "; overnight.py could not be loaded (SyntaxError" in done.stderr
    assert done.stderr.endswith(". The gate is broken; the human can type /stop\n") and done.stdout == ""


def test_a10_the_failed_load_is_in_the_refusal_record_text(monkeypatch):
    launcher = _launcher_module()
    recorded = []
    monkeypatch.setattr(launcher, "record", lambda raw, hook, text: recorded.append(text))
    monkeypatch.setattr(launcher, "_load", lambda name, path=None: launcher.FAILED.update({name: "OSError: x"}))
    monkeypatch.delenv("CLAUDE_COMMAND_GATE", raising=False)
    assert launcher.fallback(b"{}", "stop-workflow-coordinator.py", 280) == 2
    assert len(recorded) == 1 and "overnight.py could not be loaded (OSError: x)" in recorded[0]


def test_a10_an_unloadable_library_file_leaves_the_fallback_able_to_read_the_window(tmp_path):
    """locations.py unloadable beside overnight.py: the module still loads (the standard library alone), the window
    is read, and a session with no gated command and no open window is let stop, with nothing said of a failed load."""
    hooks = _scratch(tmp_path, BROKEN)
    (hooks / "lib" / "locations.py").write_text(BROKEN, encoding="utf-8")
    done = _stop(tmp_path, hooks, "help")
    assert (done.returncode, done.stdout, done.stderr) == (0, "", ""), done.stderr


def _bare_overnight(tmp_path):
    """overnight.py alone in a directory: loaded with the standard library, nothing of the harness beside it."""
    import importlib.util
    only = tmp_path / "bare"
    only.mkdir()
    shutil.copy(HOOKS / "lib" / "overnight.py", only / "overnight.py")
    spec = importlib.util.spec_from_file_location("overnight_bare", only / "overnight.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a10_overnight_py_with_no_library_beside_it_still_finds_its_roots_and_the_root_is_no_top(tmp_path, monkeypatch):
    bare = _bare_overnight(tmp_path)
    monkeypatch.delitem(sys.modules, "locations", raising=False)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    assert bare._locations() is None
    assert bare._top(repo) == str(repo.resolve()) and bare._common_dir(repo) == str(repo.resolve() / ".git")
    assert str(repo.resolve()) in bare.candidate_project_dirs(str(repo))
    monkeypatch.setattr(bare, "_git", lambda where, *args: "/" if args[-1] == "--show-toplevel" else "/.git")
    assert bare._top("/anywhere") is None and bare._common_dir("/anywhere") is None  # a top at the root: none
    monkeypatch.undo()
    shared = bare._locations() or _shared_locations()
    assert (shared.repo_top(repo), shared.repo_common_dir(repo)) == (bare._top(repo), bare._common_dir(repo))


def _shared_locations():
    """locations.py as the fallback's comparison is held to it: the same answers on a repository."""
    sys.path.insert(0, str(HOOKS / "lib"))
    try:
        import locations
        return locations
    finally:
        sys.path.pop(0)


def _coordinator():
    import importlib.util
    spec = importlib.util.spec_from_file_location("stop_launch_test_coordinator", HOOKS / "stop-workflow-coordinator.py")
    module = sys.modules[spec.name] = importlib.util.module_from_spec(spec)  # its dataclass reads its module
    spec.loader.exec_module(module)
    return module


def test_a10_the_launchers_no_verdict_text_says_what_the_coordinators_says():
    """The launcher states its coordinator out of time with the coordinator's own text for its gate out of
    time: no verdict, not let through, the next stop continues the gate's work, /stop; never "broken"."""
    launcher = _launcher_module()
    for subject, limit in (("stop-workflow-coordinator.py", 280), ("the gate", 60)):
        assert launcher._texts(subject, limit) == _coordinator().no_verdict_text(subject, limit)
    assert "broken" not in "".join(launcher._texts("stop-workflow-coordinator.py", 280))


def _launcher_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("stop_launch_under_test", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _background_launch(minutes_ago: float) -> list:
    """The CLI's records of a background dev dispatch launched ``minutes_ago`` (its result: isAsync, agentbg1)."""
    sys.path.insert(0, str(REPO))
    from tests.cli_shapes import synthesize
    at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")
    return [synthesize("assistant", "tool_use", timestamp=at, sessionId=SID, message__content=[
                {"type": "tool_use", "id": "toolu_bg01", "name": "Agent", "input": {
                    "subagent_type": "dev", "description": "dev", "prompt": "work", "run_in_background": True}}]),
            synthesize("user", "agent_launched", timestamp=at, sessionId=SID, toolUseResult__agentId="agentbg1",
                       message__content=[{"type": "tool_result", "tool_use_id": "toolu_bg01",
                                          "content": "Async agent launched successfully"}])]


@pytest.mark.parametrize("minutes_ago, code", [(5, 0), (24 * 60, 2)])
def test_a10_a_failed_coordinator_while_a_child_runs_ends_the_turn_as_a_wait(tmp_path, minutes_ago, code):
    """The fallback reads the waiting state through the gate's own reading (waiting_for): a child that runs
    makes the stop a wait (exit 0, naming the failure and the child); one past its bound is not running and
    the fallback blocks as before."""
    hooks = _scratch(tmp_path, BROKEN, whole=True)
    done = _stop(tmp_path, hooks, "dev", extra=_background_launch(minutes_ago))
    assert done.returncode == code, done.stderr
    if code:
        assert done.stderr == LINE.format("stop-workflow-coordinator.py exited 1 (SyntaxError: invalid syntax)")
    else:
        assert done.stderr == ("COMMAND_GATE instrument failure: stop-workflow-coordinator.py exited 1 (SyntaxError: "
                               "invalid syntax); waiting for agentbg1, still running; not complete\n")
        assert json.loads(done.stdout) == {"systemMessage": done.stderr}


@pytest.mark.parametrize("minutes_ago, code", [(5, 0), (24 * 60, 2), (None, 2)])
def test_a10_inside_an_open_window_the_fallback_waits_as_the_gate_does(tmp_path, minutes_ago, code):
    """The window open (end_time an hour ahead) and /dev-overnight the latest command: a child launched 5 minutes
    ago makes the stop a wait, as in the gate; one a day old (lost) or none blocks naming the failure and /stop."""
    hooks = _scratch(tmp_path, BROKEN, whole=True)
    _state(tmp_path, 1)
    done = _stop(tmp_path, hooks, "dev-overnight", extra=_background_launch(minutes_ago) if minutes_ago else ())
    assert done.returncode == code, done.stderr
    failure = "stop-workflow-coordinator.py exited 1 (SyntaxError: invalid syntax)"
    if code:
        assert done.stderr == LINE.format(failure)
    else:
        assert done.stderr == f"COMMAND_GATE instrument failure: {failure}; waiting for agentbg1, still running; not complete\n"
        assert json.loads(done.stdout) == {"systemMessage": done.stderr}


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
    assert loads == {"command_span", "overnight", "stop_command_gate"}  # the gate: its waiting_for reading only
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert not defined & {"prompt_text", "span_opener", "slash_command", "active_command", "timelock_released",
                          "is_human_prompt", "window_open", "state_verdicts"}
    overnight = ast.parse((HOOKS / "lib" / "overnight.py").read_text(encoding="utf-8"))
    top = {a.name.split(".")[0] for n in overnight.body if isinstance(n, ast.Import) for a in n.names}
    top |= {n.module.split(".")[0] for n in overnight.body if isinstance(n, ast.ImportFrom) and n.module}
    assert top <= set(sys.stdlib_module_names) | {"__future__"}, top


def test_a10_the_span_reader_without_the_index_module_reads_the_conversation_whole(tmp_path, monkeypatch):
    """The fallback loads command_span.py by path with no library beside it, as the overnight reader is loaded; where a scan that
    keeps readings is open and the index module cannot be loaded, the reading is the whole read, with the same answer."""
    import importlib.util
    import types
    lib = tmp_path / "hooks" / "lib"
    lib.mkdir(parents=True)
    for name in ("command_span.py", "stop-commands.json"):
        shutil.copy(HOOKS / "lib" / name, lib / name)
    (tmp_path / "commands").mkdir()
    (tmp_path / "commands" / "dev.md").write_text("x", encoding="utf-8")
    spec = importlib.util.spec_from_file_location("span_alone", lib / "command_span.py")
    span = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(span)
    transcript = _transcript(tmp_path / "t.jsonl", "dev")
    whole = span.active_span(str(transcript), frozenset({"dev"}))
    assert whole is not None and whole.command == "dev"
    scan = types.SimpleNamespace(keep=tmp_path / "keep", memo={})
    fake = types.ModuleType("fake_obligation")
    fake.transcript_scan, fake._SCAN = object(), scan
    monkeypatch.setitem(sys.modules, "fake_obligation", fake)
    monkeypatch.setitem(sys.modules, "transcript_index", None)  # the module is not there to load
    kept = span.active_span(str(transcript), frozenset({"dev"}))
    assert kept is not None and (kept.command, kept.args, kept.start_line) == (whole.command, whole.args, whole.start_line)
    assert span.active_command(str(transcript), keep=tmp_path / "keep2") == span.active_command(str(transcript)) == "dev"


# ---------------------------------------------------------------- A22: the Stop registration
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


def test_a22_no_awaiting_input_or_g4_decider_remains():
    g4 = "evaluate_" + "required_values"  # spelled apart: A22's own grep of hooks/ and scripts/ finds nothing
    awaiting = subprocess.run(["git", "-C", str(REPO), "grep", "-n", "AWAITING_INPUT", "--", "commands/merge.md",
                               "commands/push.md", "commands/do.md", "hooks", ":!hooks/tests"], capture_output=True, text=True)
    decider = subprocess.run(["git", "-C", str(REPO), "grep", "-n", g4, "--", "hooks", "scripts"],
                             capture_output=True, text=True)
    assert (awaiting.returncode, awaiting.stdout, decider.returncode, decider.stdout) == (1, "", 1, "")
