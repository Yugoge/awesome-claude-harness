"""Temp files follow the dispatch during which they were made (hooks/lib/dispatch_temp.py).

Every case runs the real hooks: session-scratch-init.sh writes the env file line, the dispatch gate
opens a foreground dispatch, the dispatch record's PostToolUse and the PostToolUseFailure launcher
close it, sessionend-scratch-sweep.sh ends the session. A shell command runs as the CLI runs one:
the env file's content, then the command. All roots are throwaway directories under $TMPDIR.
"""
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent
SID = "dispatch-temp-sid"


class DispatchTempTests(unittest.TestCase):
    def setUp(self):
        self.box = Path(tempfile.mkdtemp(prefix="dispatch-temp-"))
        self.addCleanup(shutil.rmtree, self.box, ignore_errors=True)
        self.root = self.box / "scratch"
        self.env_file = self.box / "session-env"
        for sub in ("state", "home", "project"):
            (self.box / sub).mkdir()
        self.env = dict(os.environ, TMPDIR=str(self.root), CLAUDE_CODE_SESSION_ID=SID,
                        CLAUDE_PID=str(os.getpid()), CLAUDE_ENV_FILE=str(self.env_file),
                        CLAUDE_STATE_DIR=str(self.box / "state"), HOME=str(self.box / "home"),
                        XDG_STATE_HOME=str(self.box / "home"), CLAUDE_PROJECT_DIR=str(self.box / "project"))
        self.start()
        self.session = Path(os.path.realpath(self.root / SID))

    def start(self):
        done = subprocess.run(["bash", str(HOOKS / "session-scratch-init.sh")], input="{}", text=True,
                              env=self.env, capture_output=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)

    def hook(self, script, event, tid, **fields):
        payload = dict(hook_event_name=event, session_id=SID, tool_name="Agent", tool_use_id=tid,
                       cwd=str(self.box / "project"), **fields)
        payload.setdefault("tool_input", {"description": "d", "prompt": "p", "subagent_type": "general-purpose",
                                          "run_in_background": False})
        subprocess.run(["python3", str(HOOKS / script)], input=json.dumps(payload), text=True, env=self.env,
                       cwd=str(self.box / "project"), capture_output=True, timeout=120)

    def open(self, tid, **fields):
        self.hook("pretool-dispatch-gate.py", "PreToolUse", tid, **fields)

    def close(self, tid, status="completed"):
        self.hook("posttool-dispatch-record.py", "PostToolUse", tid, tool_response={"status": status})

    def command(self, script, prelude=""):
        """`script` run as the CLI runs a Bash command; its stdout."""
        line = f"{prelude}true && {self.env_file.read_text()}\n: && eval {shlex.quote(script)}"
        env = {k: v for k, v in self.env.items() if k != "CLAUDE_ENV_FILE"}
        done = subprocess.run(["bash", "-c", line], text=True, env=env, capture_output=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def test_files_made_during_a_dispatch_are_gone_after_it_returns(self):
        self.open("t1")
        made = Path(self.command("mktemp"))
        self.assertTrue(made.is_file())
        self.assertNotEqual(made.parent, self.session)
        self.assertEqual(made.parent.parent, self.session)
        self.close("t1")
        self.assertFalse(made.parent.exists())
        self.assertEqual(self.command('printf %s "$TMPDIR"'), str(self.session))

    def test_no_dispatch_open_uses_the_session_root(self):
        self.assertEqual(self.command('printf %s "$TMPDIR"'), str(self.session))
        self.open("bg", tool_input={"description": "d", "prompt": "p", "run_in_background": True})
        self.assertEqual(self.command('printf %s "$TMPDIR"'), str(self.session))

    def test_a_directory_a_live_process_uses_survives_until_the_next_return(self):
        self.open("t1")
        held = Path(self.command('printf %s "$TMPDIR"'))
        worker = subprocess.Popen(["sleep", "60"], cwd=str(held))
        self.addCleanup(worker.wait)
        self.addCleanup(worker.kill)
        handle = open(held / "open-file", "w")  # an open file, the second way of use
        self.close("t1")
        self.assertTrue(held.is_dir())
        self.assertEqual(self.command('printf %s "$TMPDIR"'), str(self.session))
        worker.kill()
        worker.wait()
        self.open("t2")
        self.close("t2")
        self.assertTrue(held.is_dir())  # the open file still holds it
        handle.close()
        self.open("t3")
        self.close("t3")
        self.assertFalse(held.exists())

    def test_parallel_dispatches_share_one_removed_after_the_last(self):
        self.open("a")
        self.open("b")
        shared = self.command('printf %s "$TMPDIR"')
        self.close("a")
        self.assertTrue(Path(shared).is_dir())
        self.assertEqual(self.command('printf %s "$TMPDIR"'), shared)
        self.close("b")
        self.assertFalse(Path(shared).exists())

    def test_a_failed_dispatch_closes_too(self):
        self.open("t1")
        temp = Path(self.command('printf %s "$TMPDIR"'))
        self.hook("posttool-failure-launch.py", "PostToolUseFailure", "t1", error="boom")
        self.assertFalse(temp.exists())

    def test_a_missing_end_keeps_the_directory_until_the_session_ends(self):
        self.open("lost")
        self.open("t2")
        temp = Path(self.command("mktemp")).parent
        self.close("t2")
        self.assertTrue(temp.is_dir())
        self.open("moved")
        self.close("lost", status="async_launched")  # an agent moved to the background is never seen to end
        self.close("moved")
        self.assertTrue(temp.is_dir())
        subprocess.run(["bash", str(HOOKS / "sessionend-scratch-sweep.sh")],
                       input=json.dumps({"session_id": SID}), text=True, env=self.env, timeout=60)
        self.assertFalse(self.session.exists())

    def test_leftovers_of_a_dead_session_process_go_at_its_next_start(self):
        self.open("t1")
        temp = Path(self.command('printf %s "$TMPDIR"'))
        self.close("t1", status="async_launched")  # its agent went on in the background
        self.start()  # the same process starts again (clear, compact): a background agent's directory is kept
        self.assertTrue(temp.is_dir())
        gone = subprocess.Popen(["true"])
        gone.wait()
        self.env["CLAUDE_PID"] = str(gone.pid)
        owner = json.loads((self.session / ".owner").read_text())
        (self.session / ".owner").write_text(json.dumps(dict(owner, pid=str(gone.pid))))
        self.start()
        self.assertFalse(temp.exists())
        self.assertEqual(self.command('printf %s "$TMPDIR"'), str(self.session))

    def test_the_env_line_never_breaks_a_command(self):
        strict = "set -euo pipefail; "
        self.assertEqual(self.command("echo ok", strict), "ok")  # no pointer
        self.open("t1")
        temp = Path(self.command('printf %s "$TMPDIR"', strict))
        shutil.rmtree(temp)  # pointer to a missing directory
        self.assertEqual(self.command('printf %s "$TMPDIR"', strict), str(self.session))
        (self.session / ".dispatch-tmp").write_text("")  # an empty pointer
        self.assertEqual(self.command('printf %s "$TMPDIR"', strict), str(self.session))
        shutil.rmtree(self.session)  # the session root has gone: the inherited TMPDIR stays
        self.assertEqual(self.command('printf %s "$TMPDIR"', strict), str(self.root))
        for shell in ("sh", "zsh", "dash"):
            if shutil.which(shell):
                done = subprocess.run([shell, "-c", f"set -eu; true && {self.env_file.read_text()}\n: && echo ok"],
                                      text=True, capture_output=True, env=self.env, timeout=60)
                self.assertEqual((done.returncode, done.stdout.strip()), (0, "ok"), (shell, done.stderr))


if __name__ == "__main__":
    unittest.main()
