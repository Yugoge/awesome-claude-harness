"""A21 and the arming experiment (P5 "Arming"): a session that loaded the pre-update hook list meets
this tree's files.

A running session keeps the hook list it loaded (D15) while the files those hooks name are this
tree's. The pre-update list is origin/master's: settings.json's Stop group runs
hooks/stop-workflow-coordinator.py directly, with stop-do-report-gate.py and stop-obligation-gate.py
beside it (pre_update_settings finds it in the tree's own history: the newest settings.json whose
Stop group runs the coordinator directly). The state and transcripts are such a session's: an
in-flight /dev cycle, an in-flight /do (its consent sidecar, no completed do-report), a /merge span
whose analysis came back blocked, an open /dev-overnight window, an ungated session. Each Stop runs
every hook the list registers, as registered (tests/replay/hookrun.py); a PreToolUse TodoWrite runs
pretool-tool-policy.py and pretool-todo-validate.py on the old transcript.

The two options: option 1, the launcher marks the coordinator it runs
(stop-workflow-coordinator.LAUNCHER_MARK); unmarked, the coordinator runs completion advisory and
keeps the time-lock, and a forged mark only arms. Option 2, the coordinator is always armed,
emulated by the mark in the pre-update session's own environment. The experiment counts the Stops
blocked on a pre-update span under each option, the open window aside (it blocks under both):
none under option 2 would take option 2; any takes option 1.

The harness home is a copy of the tree under test (pre_update_home); a tree switch (P1c's live
landing machinery) can build the same states with origin/master's files and call run_stop on them.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.replay import hookrun

REPO = Path(__file__).resolve().parents[2]
SID = {name: f"a21{k:05d}-2222-3333-4444-555555555555" for k, name in
       enumerate(("dev", "do", "merge", "window", "ungated"))}
DO_ID = "20261101-091500"
SPANS = ("dev", "do", "merge")  # the pre-update spans a gated command opened


def _coordinator():
    spec = importlib.util.spec_from_file_location("a21_coordinator", REPO / "hooks" / "stop-workflow-coordinator.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look their module up
    spec.loader.exec_module(module)
    return module


MARK = _coordinator().LAUNCHER_MARK


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout


def _runs_coordinator_directly(settings: dict) -> bool:
    return any("hooks/stop-workflow-coordinator.py" in h.get("command", "")
               for group in settings["hooks"]["Stop"] for h in group["hooks"])


def pre_update_settings(tree: Path = REPO) -> dict:
    """origin/master's settings.json as a running session loaded it: the newest settings.json in the
    tree's history whose Stop group runs the coordinator directly."""
    for sha in _git(tree, "log", "--format=%H", "--", "settings.json").split():
        settings = json.loads(_git(tree, "show", f"{sha}:settings.json"))
        if _runs_coordinator_directly(settings):
            return settings
    raise AssertionError("no settings.json in the history runs the Stop coordinator directly")


def current_settings(tree: Path = REPO) -> dict:
    return json.loads((tree / "settings.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- the pre-update session's world
class World:
    """A harness home (a copy of the tree), a project repository and the five sessions' state and
    transcripts, as a session running before the update left them."""

    def __init__(self, tmp: Path, tree: Path = REPO):
        self.tmp, self.home, self.project, self.state = tmp, tmp / "home", tmp / "project", tmp / "state"
        shutil.copytree(tree, self.home / ".claude", symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "tests", "docs", "__pycache__", "venv"))
        self.state.mkdir()
        (tmp / "tmp").mkdir()
        self.project.mkdir()
        for args in (("init", "-q", "-b", "master"), ("config", "user.name", "t"),
                     ("config", "user.email", "t@example.invalid")):
            _git(self.project, *args)
        (self.project / "README.md").write_text("toy\n")
        _git(self.project, "add", "-A")
        _git(self.project, "commit", "-qm", "init")
        _git(self.project, "checkout", "-qb", "feature-x")
        (self.project / "feature.txt").write_text("x\n")
        _git(self.project, "add", "-A")
        _git(self.project, "commit", "-qm", "feature")
        _git(self.project, "checkout", "-q", "master")
        self.transcripts = {}
        self.clock = datetime.now(timezone.utc) - timedelta(minutes=30)
        for name in SID:
            self.transcripts[name] = self.home / ".claude" / "projects" / "-project" / f"{SID[name]}.jsonl"
            self.transcripts[name].parent.mkdir(parents=True, exist_ok=True)
            self.transcripts[name].write_text("")
            getattr(self, f"_{name}")()

    # -- records in the CLI's shapes
    def add(self, name, record):
        self.clock += timedelta(seconds=1)
        record.setdefault("timestamp", self.clock.isoformat().replace("+00:00", "Z"))
        record.setdefault("sessionId", SID[name])
        with self.transcripts[name].open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def command(self, name, command, args="", context=None):
        self.add(name, {"type": "queue-operation", "operation": "enqueue", "content": f"/{command} {args}".strip()})
        self.add(name, {"type": "user", "message": {"role": "user", "content":
                 f"<command-message>{command}</command-message>\n<command-name>/{command}</command-name>\n"
                 f"<command-args>{args}</command-args>"}})
        self.add(name, {"type": "user", "isMeta": True, "message": {"role": "user", "content": [
            {"type": "text", "text": f"body of /{command}"}]}})
        if context:
            self.add(name, {"type": "attachment", "attachment": {"type": "hook_additional_context",
                                                                 "content": context, "hookName": "UserPromptSubmit"}})

    def tool(self, name, tool, tool_input, result="ok"):
        ident = f"toolu_{name}_{len(self.transcripts[name].read_text().splitlines()):04d}"
        self.add(name, {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": ident, "name": tool, "input": tool_input}]}})
        self.add(name, {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": ident, "content": result}]}})

    def canonical(self, command):
        out = subprocess.run([sys.executable, str(self.home / ".claude" / "scripts" / "todo" / f"{command}.py")],
                             capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def todos(self, name, steps, done):
        self.tool(name, "TodoWrite", {"todos": [
            {"content": s["content"], "activeForm": s.get("activeForm", s["content"]),
             "status": "completed" if k < done else ("in_progress" if k == done else "pending")}
            for k, s in enumerate(steps)]})

    # -- the five sessions
    def _dev(self):
        self.command("dev", "dev", "fix the flaky test", context="DEV_SESSION_ID pre-initialized by hook: "
                     "dev-20261101-090000\nTask id: 20261101-090000\n")
        self.todos("dev", self.canonical("dev"), 3)

    def _do(self):
        self.command("do", "do", "rename the heading", context=f"[/do] task-id minted: {DO_ID}\n")
        (self.state / f"claude-do-task-{SID['do']}.json").write_text(json.dumps({"task_id": DO_ID}))

    def _merge(self):
        self.command("merge", "merge", "feature-x")
        self.tool("merge", "Agent", {"subagent_type": "merge-analyst", "description": "analyse",
                                     "prompt": "analyse feature-x"},
                  result="MERGE_ANALYSIS: blocked (risk: an unreviewed migration)")

    def _window(self):
        self.command("window", "dev-overnight", "1h harden the toy package")
        end = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        start = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        (self.project / ".claude").mkdir(exist_ok=True)
        (self.project / ".claude" / f"overnight-state-{SID['window']}.json").write_text(json.dumps(
            {"session_id": SID["window"], "start_time": start, "end_time": end, "current_phase": "exploring",
             "worktree_path": str(self.project), "main_root": str(self.project)}))

    def _ungated(self):
        self.add("ungated", {"type": "user", "message": {"role": "user", "content": "summarise the open issues"}})

    # -- running hooks
    def env(self, settings, mark=False):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
        env.update(hookrun.settings_env(settings))
        env.update({"HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
                    "CLAUDE_STATE_DIR": str(self.state), "CLAUDE_PROJECT_DIR": str(self.project),
                    "TMPDIR": str(self.tmp / "tmp"), "CLAUDE_CODE_TMPDIR": str(self.tmp / "tmp")})
        env.update({MARK: "1"} if mark else {})
        return env

    def payload(self, name):
        return {"session_id": SID[name], "transcript_path": str(self.transcripts[name]), "cwd": str(self.project),
                "stop_hook_active": False, "permission_mode": "default"}

    def run_stop(self, name, settings, mark=False):
        return hookrun.run_event(settings, "Stop", self.payload(name), self.env(settings, mark), str(self.project))


def _blocked(event) -> bool:
    return any(h["verdict"] == "block" for h in event["hooks"])


def _healthy(event) -> list:
    return [f"{h['hook']}: rc {h['rc']} {h['stderr'][-300:]}" for h in event["hooks"]
            if h["verdict"] == "error" or "Traceback (most recent call last)" in h["stderr"]]


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return World(tmp_path_factory.mktemp("a21"))


# ---------------------------------------------------------------- the arming experiment
def test_arming_experiment_decides_option_1(world):
    """Per option, the Stops blocked on a pre-update span (the open window aside): option 2 (the
    coordinator always armed) blocks the in-flight /dev, /do and /merge spans of a session that
    never ran the update's commands, so option 1 is taken (the default)."""
    old = pre_update_settings()
    counts, rows = {}, []
    for option, mark in (("option 1", False), ("option 2", True)):
        blocked = [name for name in SPANS if _blocked(world.run_stop(name, old, mark))]
        counts[option] = len(blocked)
        rows.append(f"{option}: {len(blocked)} of {len(SPANS)} pre-update spans blocked {blocked}")
    print("\narming experiment (pre-update hook list, this tree's files):\n  " + "\n  ".join(rows))
    assert counts["option 1"] == 0, rows
    assert counts["option 2"] > 0, rows  # option 2 would be taken only at 0


# ---------------------------------------------------------------- A21 under option 1
def test_a21_pre_update_hook_list_runs_every_stop_hook_and_holds_no_span(world):
    """Every Stop hook the pre-update list registers runs on this tree's files: the coordinator
    directly (completion advisory: `would block` on stderr, exit 0), the retired gates as exit-0
    stubs; no hook errs or prints a traceback; the ungated session stops."""
    old = pre_update_settings()
    for name in SPANS + ("ungated",):
        event = world.run_stop(name, old)
        hooks = [h["hook"] for h in event["hooks"]]
        assert hooks == ["hooks/stop-workflow-coordinator.py", "hooks/stop-do-report-gate.py",
                         "hooks/stop-obligation-gate.py"], hooks
        assert not _healthy(event) and not _blocked(event), (name, event["hooks"])
        coordinator = event["hooks"][0]
        assert ("would block" in coordinator["stderr"]) == (name in SPANS), (name, coordinator["stderr"])
        assert all((h["rc"], h["stdout"], h["stderr"]) == (0, "", "") for h in event["hooks"][1:])


def test_a21_this_trees_hook_list_enforces_the_same_spans(world):
    """The same states under this tree's settings.json: the launcher arms the coordinator, so each
    gated span blocks naming its command (and its compliant path: the gaps, or the human's /stop),
    the ungated session stops."""
    new = current_settings()
    for name in SPANS + ("ungated",):
        event = world.run_stop(name, new)
        assert [h["hook"] for h in event["hooks"]] == ["hooks/stop-launch.py"]
        assert not _healthy(event), event["hooks"]
        launcher = event["hooks"][0]
        if name in SPANS:
            assert launcher["rc"] == 2 and launcher["stderr"].startswith(f"COMMAND_GATE /{name}: not complete"), \
                launcher["stderr"]
        else:
            assert launcher["rc"] == 0, launcher["stderr"]


@pytest.mark.parametrize("which", ["pre-update", "this tree"])
def test_a21_the_open_window_blocks_under_both_hook_lists(world, which):
    """The open /dev-overnight window blocks the Stop under either list (the time-lock is kept
    unmarked). It reads P2's overnight.window_open: waits for P2's merge."""
    settings = pre_update_settings() if which == "pre-update" else current_settings()
    event = world.run_stop("window", settings)
    assert not _healthy(event), event["hooks"]
    assert _blocked(event) and "overnight window open until" in event["hooks"][0]["stderr"], event["hooks"]


@pytest.mark.parametrize("which", ["pre-update", "this tree"])
def test_a21_the_tool_hooks_accept_the_old_transcript(world, which):
    """pretool-tool-policy.py and pretool-todo-validate.py on the in-flight /dev cycle's transcript:
    its next TodoWrite (step 4 in progress) is accepted, no traceback."""
    settings = pre_update_settings() if which == "pre-update" else current_settings()
    steps = world.canonical("dev")
    todos = [{"content": s["content"], "activeForm": s.get("activeForm", s["content"]),
              "status": "completed" if k < 4 else ("in_progress" if k == 4 else "pending")}
             for k, s in enumerate(steps)]
    payload = dict(world.payload("dev"), tool_name="TodoWrite", tool_input={"todos": todos},
                   tool_use_id="toolu_a21_next")
    event = hookrun.run_event(settings, "PreToolUse", payload, world.env(settings), str(world.project))
    mine = [h for h in event["hooks"] if h["hook"] in ("hooks/pretool-tool-policy.py", "hooks/pretool-todo-validate.py")]
    assert len(mine) == 2, [h["hook"] for h in event["hooks"]]
    assert all(h["verdict"] == "ok" and "Traceback" not in h["stderr"] for h in mine), mine
