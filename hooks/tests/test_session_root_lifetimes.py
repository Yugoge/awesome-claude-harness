"""What of a session root lives how long (hooks/sessionend-scratch-sweep.sh, hooks/lib/dispatch_temp.py,
hooks/pretool-tool-policy.py, hooks/lib/harness_temp_state.py).

A session's process ends and the same session is resumed: its agents' own scratch and its roles' drafts (the role
directories) are still there, its main agent's top-level temp files are not. A dispatch whose end is never seen
(a cancelled turn fires no hook) is closed at the owner's next prompt. The dispatch temp's state is control state.
Every root is a throwaway directory; the real hooks run as subprocesses.
"""
import json
import os
import subprocess
import sys
import tempfile
import shutil
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent
SID = "lifetimes-sid"


class SessionRootLifetimes(unittest.TestCase):
    def setUp(self):
        self.box = Path(tempfile.mkdtemp(prefix="lifetimes-"))
        self.addCleanup(shutil.rmtree, self.box, ignore_errors=True)
        self.root = self.box / "scratch"
        for sub in ("state", "home", "project"):
            (self.box / sub).mkdir()
        self.env = dict(os.environ, TMPDIR=str(self.root), CLAUDE_CODE_SESSION_ID=SID, CLAUDE_PID=str(os.getpid()),
                        CLAUDE_STATE_DIR=str(self.box / "state"), HOME=str(self.box / "home"),
                        XDG_STATE_HOME=str(self.box / "home"), CLAUDE_PROJECT_DIR=str(self.box / "project"))
        self.env.pop("CLAUDE_ENV_FILE", None)
        self.run_hook("session-scratch-init.sh", {})
        self.session = Path(os.path.realpath(self.root / SID))

    def run_hook(self, script, payload, **fields):
        payload = dict(payload, session_id=SID, cwd=str(self.box / "project"), **fields)
        runner = ["bash"] if script.endswith(".sh") else [sys.executable]
        return subprocess.run(runner + [str(HOOKS / script)], input=json.dumps(payload), text=True, env=self.env,
                              cwd=str(self.box / "project"), capture_output=True, timeout=120)

    def dispatch(self, event, script, tid, **fields):
        tool_input = {"description": "d", "prompt": "p", "subagent_type": "general-purpose", "run_in_background": False}
        self.run_hook(script, {"hook_event_name": event, "tool_name": "Agent", "tool_use_id": tid,
                               "tool_input": tool_input}, **fields)

    def pointer(self):
        path = self.session / ".dispatch-tmp"
        return path.read_text().splitlines()[0] if path.is_file() else ""

    def prompt(self):
        self.run_hook("lib/dispatch_temp.py", {"hook_event_name": "UserPromptSubmit", "prompt": "next"})

    # -- R2 and R3: the session-end sweep --------------------------------------------------------------------------
    def test_a_resumed_session_keeps_its_agents_scratch_and_drafts_but_not_its_top_level_temp(self):
        own = self.session / "qa" / "a1b2c3"
        own.mkdir(parents=True)
        (own / "notes.txt").write_text("agent scratch")
        (self.session / "qa" / "draft.md").write_text("role draft")
        (self.session / "tmp.Main").mkdir()
        (self.session / "tmp.Main" / "f").write_text("x")
        (self.session / "top.txt").write_text("x")
        (self.session / ".hidden").write_text("x")
        self.run_hook("sessionend-scratch-sweep.sh", {"hook_event_name": "SessionEnd"})
        self.assertEqual((own / "notes.txt").read_text(), "agent scratch")
        self.assertEqual((self.session / "qa" / "draft.md").read_text(), "role draft")
        self.assertEqual(sorted(p.name for p in self.session.iterdir()), [".owner", "qa"])
        self.run_hook("session-scratch-init.sh", {})  # resumed
        self.assertTrue((own / "notes.txt").is_file() and (self.session / "qa" / "draft.md").is_file())

    def test_a_session_without_role_directories_goes_whole(self):
        (self.session / "plain").mkdir()  # a directory holding no agent's own directory is the main agent's
        (self.session / "plain" / "x").write_text("x")
        self.run_hook("sessionend-scratch-sweep.sh", {"hook_event_name": "SessionEnd"})
        self.assertFalse(self.session.exists())

    # -- R1: a dispatch whose end is never seen ---------------------------------------------------------------------
    def test_a_cancelled_dispatch_is_closed_at_the_next_prompt(self):
        self.dispatch("PreToolUse", "pretool-dispatch-gate.py", "lost")
        temp = Path(self.pointer())
        self.assertEqual(temp.parent, self.session)
        (temp / "made").write_text("x")
        worker = subprocess.Popen(["sleep", "60"], cwd=str(temp))
        self.addCleanup(worker.wait)
        self.addCleanup(worker.kill)
        self.prompt()
        self.assertEqual(self.pointer(), "")  # closed: later commands use the session root
        self.assertTrue(temp.is_dir())  # a live process works in it
        worker.kill()
        worker.wait()
        self.prompt()
        self.assertFalse(temp.exists())
        self.assertFalse((self.session / ".dispatch-tmp").exists())

    def test_a_start_of_the_same_process_closes_a_lost_dispatch(self):
        self.dispatch("PreToolUse", "pretool-dispatch-gate.py", "lost")
        temp = Path(self.pointer())
        self.run_hook("session-scratch-init.sh", {})  # clear, compact
        self.assertFalse(temp.exists())
        self.assertEqual(self.pointer(), "")

    def test_the_prompt_rule_is_registered(self):
        text = (HOOKS / "userprompt-launch.py").read_text()
        self.assertIn("Rule('dispatch-temp', 'lib/dispatch_temp.py'", text)

    # -- R4: the dispatch temp's state is control state -------------------------------------------------------------
    def policy(self, tool, tool_input):
        return self.run_hook("pretool-tool-policy.py", {"hook_event_name": "PreToolUse", "tool_name": tool,
                                                        "tool_input": tool_input})

    def test_no_agent_writes_moves_or_removes_the_dispatch_temp_state(self):
        self.dispatch("PreToolUse", "pretool-dispatch-gate.py", "t1")
        state = self.session / ".dispatch-tmp"
        self.assertTrue(state.is_file())
        cases = [("Write", {"file_path": str(state), "content": "x\n{}\n"}),
                 ("Bash", {"command": f"rm -f {state}"}),
                 ("Bash", {"command": f"mv {self.session / 'notes'} {state}"}),
                 ("Bash", {"command": f"printf x > {state}"}),
                 ("Bash", {"command": f"rm -rf {self.session}"})]
        for tool, tool_input in cases:
            done = self.policy(tool, tool_input)
            self.assertEqual(done.returncode, 2, (tool_input, done.stderr))
            self.assertIn("the dispatch temp's state", done.stderr, tool_input)
        done = self.policy("Write", {"file_path": str(self.session / "notes.txt"), "content": "x"})
        self.assertNotIn("the dispatch temp's state", done.stderr)

    def test_it_is_in_the_inventory_of_control_state(self):
        sys.path.insert(0, str(HOOKS / "lib"))
        try:
            import harness_temp_state as hts
        finally:
            sys.path.pop(0)
        old = os.environ.get("TMPDIR")
        os.environ["TMPDIR"] = str(self.root)  # the session scratch root, a name root
        try:
            loc = hts.classify(str(self.session / ".dispatch-tmp"))
        finally:
            os.environ.pop("TMPDIR") if old is None else os.environ.__setitem__("TMPDIR", old)
        self.assertIsNotNone(loc)
        self.assertEqual((loc.name, loc.kind), ("dispatch-temp-state", hts.CONTROL))


if __name__ == "__main__":
    unittest.main()
