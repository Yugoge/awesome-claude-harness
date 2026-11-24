"""A21 and the arming experiment (P5 "Arming"): a session that loaded the pre-update hook list meets
this tree's files.

A running session keeps the hook list it loaded (D15) while the files those hooks name are this
tree's. The pre-update list is origin/master's: settings.json's Stop group runs
hooks/stop-workflow-coordinator.py directly, with stop-do-report-gate.py and stop-obligation-gate.py
beside it (it was found in the tree's own history: the newest settings.json whose Stop group runs
the coordinator directly, 84de49b). The state and transcripts are such a session's: an
in-flight /dev cycle, an in-flight /do (its consent sidecar, no completed do-report), a /merge span
whose analysis came back blocked, an open /dev-overnight window, an ungated session. Each Stop runs
every hook the list registers, as registered (tests/replay/hookrun.py); a PreToolUse TodoWrite runs
pretool-tool-policy.py and pretool-todo-validate.py on the old transcript.

The cases that play the pre-update list are retired (policies/replay-hook-lists.v1.json, `retired`): no
running session holds it, and it names stop-do-report-gate.py and stop-obligation-gate.py, which this tree
deleted. What remains replays the five sessions' state under this tree's list (and so does
tests/replay/test_a21_old_bookmarks.py); the reader of the pre-update list and the option-2 mark went with
those cases. The experiment below decided option 1 before its retirement.

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

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.cli_shapes import synthesize
from tests.replay import hookrun, sites

REPO = Path(__file__).resolve().parents[2]
SID = {name: f"a21{k:05d}-2222-3333-4444-555555555555" for k, name in
       enumerate(("dev", "do", "merge", "window", "ungated"))}
DO_ID = "20261101-091500"
SPANS = ("dev", "do", "merge")  # the pre-update spans a gated command opened


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout


def stop_hooks(settings: dict) -> list[str]:
    """The Stop hook files `settings` registers, in its order, each once (hookrun.hook_name): the hooks a Stop of
    a session holding these settings runs."""
    out = []
    for group in settings["hooks"]["Stop"]:
        for h in group["hooks"]:
            name = hookrun.hook_name(h.get("command", ""))
            if name not in out:
                out.append(name)
    return out


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
        """Write ``record`` (synthesized from the recorded CLI fixture) with this session's values."""
        self.clock += timedelta(seconds=1)
        record["timestamp"] = self.clock.isoformat().replace("+00:00", "Z")
        record["sessionId"] = SID[name]
        if "cwd" in record:
            record["cwd"] = str(self.project)
        with self.transcripts[name].open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def command(self, name, command, args="", context=None):
        self.add(name, synthesize("queue-operation", "enqueue", content=f"/{command} {args}".strip()))
        self.add(name, synthesize("user", "command", turnOrigin="human", message__content=(
            f"<command-message>{command}</command-message>\n<command-name>/{command}</command-name>\n"
            f"<command-args>{args}</command-args>")))
        self.add(name, synthesize("user", "meta", message__content=[{"type": "text", "text": f"body of /{command}"}]))
        if context:  # the UserPromptSubmit hook's plain stdout, as the CLI records it
            self.add(name, synthesize("attachment/hook_success", attachment__content=context.rstrip("\n"),
                                      attachment__stdout=context))

    def tool(self, name, tool, tool_input, result="ok"):
        ident = f"toolu_{name}_{len(self.transcripts[name].read_text().splitlines()):04d}"
        self.add(name, synthesize("assistant", "tool_use", message__content=[
            {"type": "tool_use", "id": ident, "name": tool, "input": tool_input}]))
        self.add(name, synthesize("user", "tool_result", message__content=[
            {"type": "tool_result", "tool_use_id": ident, "content": result, "is_error": False}]))

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
        # The BA analysis call as the checklist's Step 4 states it (scripts/todo/dev.py ROUND_CALLS, read from the
        # canonical list as Gate 4 does): its role and the `Mode:` line its prompt carries.
        call = next(c for t in self.canonical("dev") if isinstance(t.get("subagent_call"), list)
                    for c in t["subagent_call"] if not c.get("optional"))
        self.tool("dev", "Agent", {"subagent_type": call["subagent_type"], "description": "analyse",
                                   "prompt": f"Mode: {call['prompt_mode']}\nAnalyse it."})

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
        self.add("ungated", synthesize("user", "prompt", turnOrigin="human", message__content="summarise the open issues"))

    # -- running hooks
    def env(self, settings):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
        env.update(hookrun.settings_env(settings))
        env.update({"HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
                    "CLAUDE_STATE_DIR": str(self.state), "CLAUDE_PROJECT_DIR": str(self.project),
                    "TMPDIR": str(self.tmp / "tmp"), "CLAUDE_CODE_TMPDIR": str(self.tmp / "tmp")})
        return env

    def payload(self, name):
        return {"session_id": SID[name], "transcript_path": str(self.transcripts[name]), "cwd": str(self.project),
                "stop_hook_active": False, "permission_mode": "default"}

    def run_stop(self, name, settings):
        return hookrun.run_event(settings, "Stop", self.payload(name), self.env(settings), str(self.project))


def _blocked(event) -> bool:
    return any(h["verdict"] == "block" for h in event["hooks"])


def _healthy(event) -> list:
    return [f"{h['hook']}: rc {h['rc']} {h['stderr'][-300:]}" for h in event["hooks"]
            if h["verdict"] == "error" or "Traceback (most recent call last)" in h["stderr"]]


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return World(tmp_path_factory.mktemp("a21"))


# ---------------------------------------------------------------- A21 under option 1
# The pre-update list's own cases (the arming experiment, the pre-update Stop list, the [pre-update] window and
# tool-hook cases) are retired: no session that can still exist holds that list (policies/replay-hook-lists.v1.json).
def test_a21_this_trees_hook_list_enforces_the_same_spans(world):
    """The same states under this tree's settings.json: the launcher arms the coordinator, so each
    gated span blocks naming its command (and its compliant path: the gaps, or the human's /stop),
    the ungated session stops."""
    new = current_settings()
    for name in SPANS + ("ungated",):
        event = world.run_stop(name, new)
        assert [h["hook"] for h in event["hooks"]] == stop_hooks(new) and stop_hooks(new)[0] == "hooks/stop-launch.py"
        assert not _healthy(event), event["hooks"]
        launcher = event["hooks"][0]
        if name in SPANS:
            assert launcher["rc"] == 2 and launcher["stderr"].startswith(f"COMMAND_GATE /{name}: not complete"), \
                launcher["stderr"]
        else:
            assert launcher["rc"] == 0, launcher["stderr"]


@pytest.mark.parametrize("which", ["this tree"])
def test_a21_the_open_window_blocks_under_both_hook_lists(world, which):
    """The open /dev-overnight window blocks the Stop under this tree's list. It reads P2's
    overnight.window_open: waits for P2's merge."""
    settings = current_settings()
    event = world.run_stop("window", settings)
    assert not _healthy(event), event["hooks"]
    assert _blocked(event) and "overnight window open until" in event["hooks"][0]["stderr"], event["hooks"]


@pytest.mark.parametrize("which", ["this tree"])
def test_a21_the_tool_hooks_accept_the_old_transcript(world, which):
    """pretool-tool-policy.py and pretool-todo-validate.py on the in-flight /dev cycle's transcript:
    its next TodoWrite (Step 4 completed after its BA dispatch came back, the next step in progress)
    is accepted, no traceback. Each is found as the hook the list registers to run it (tool-policy is
    a rule of the write gate in this tree's list: sites.reporter)."""
    settings = current_settings()
    steps = world.canonical("dev")
    todos = [{"content": s["content"], "activeForm": s.get("activeForm", s["content"]),
              "status": "completed" if k < 4 else ("in_progress" if k == 4 else "pending")}
             for k, s in enumerate(steps)]
    payload = dict(world.payload("dev"), tool_name="TodoWrite", tool_input={"todos": todos},
                   tool_use_id="toolu_a21_next")
    event = hookrun.run_event(settings, "PreToolUse", payload, world.env(settings), str(world.project))
    wanted = [sites.reporter(str(REPO), rule, settings) for rule in
              ("hooks/pretool-tool-policy.py", "hooks/pretool-todo-validate.py")]
    mine = [h for h in event["hooks"] if h["hook"] in wanted]
    assert len(mine) == 2, [h["hook"] for h in event["hooks"]]
    assert all(h["verdict"] == "ok" and "Traceback" not in h["stderr"] for h in mine), mine
