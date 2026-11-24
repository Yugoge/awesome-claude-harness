"""hooks/lib/allowlist.py's grant file and /do consent: the one writer, the reader, the reaper.

Whether a grant releases a call is decided in one place (lib/hook_launch.release_refused, tested in
hooks/tests/test_allow_releases_anything.py); these tests pin the file it reads: its one writer, a
malformed file releasing nothing and staying, the stop-time reaper, and has_do_consent.
"""

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

# Add hooks dir to path for lib.allowlist import
HOOKS_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, HOOKS_DIR)

from lib.allowlist import (  # noqa: E402
    ANY,
    has_do_consent,
    load_sentinel_grant_for_task,
    reap_expired_sentinel_grants,
    release,
    sentinel_grant_path,
    write_sentinel_grant,
)
from lib.harness_state_dir import harness_state_dir  # noqa: E402

SCOPE = {"kind": ANY}


def _payload(session_id):
    return {"hook_event_name": "PreToolUse", "session_id": session_id, "tool_name": "Bash",
            "tool_input": {"command": "true"}}


class TestWriteSentinelGrant(unittest.TestCase):
    """write_sentinel_grant: the one writer of /allow's grant and the demo's."""

    def setUp(self):
        self.task_id = f"test-writer-{os.getpid()}-{int(time.time() * 1000)}"
        self.path = sentinel_grant_path(self.task_id)

    def tearDown(self):
        if self.path.exists():
            self.path.unlink()

    def test_writes_a_grant_the_reader_accepts(self):
        path = write_sentinel_grant(self.task_id, "s1", SCOPE)
        self.assertEqual(path, self.path)
        grant = load_sentinel_grant_for_task(self.task_id)
        self.assertEqual(grant["scope"], SCOPE)
        self.assertEqual(grant["session_id"], "s1")
        self.assertNotIn("expires_at", grant, "a grant has no clock limit")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            [p for p in path.parent.iterdir() if p.name.startswith(f".{path.name}")], [],
            "the temp file outlived the rename")

    def test_default_write_replaces_the_tasks_grant(self):
        write_sentinel_grant(self.task_id, "s1", SCOPE)
        write_sentinel_grant(self.task_id, "s1", {"kind": "tool", "tool": "Write"})
        self.assertEqual(load_sentinel_grant_for_task(self.task_id)["scope"], {"kind": "tool", "tool": "Write"})

    def test_exclusive_write_refuses_an_existing_grant(self):
        write_sentinel_grant(self.task_id, "s1", SCOPE, exclusive=True)
        with self.assertRaises(FileExistsError):
            write_sentinel_grant(self.task_id, "s1", {"kind": "tool", "tool": "Write"}, exclusive=True)
        self.assertEqual(load_sentinel_grant_for_task(self.task_id)["scope"], SCOPE)


MALFORMED = {
    "invalid-json": "{not valid json",
    "empty": "",
    "not-an-object": '[{"kind": "any"}]',
    "no-scope": json.dumps({"task_id": "t", "session_id": "t", "created_at": 0}),
    "unknown-kind": json.dumps({"task_id": "t", "session_id": "t", "scope": {"kind": "everything"}}),
    "old-format": json.dumps({"task_id": "t", "session_id": "t", "allowed_operations": [{"op": "*"}],
                              "created_at": 0, "expires_at": 9e9}),
    "truncated": '{"task_id": "t", "session_id": "t", "scope": {"kind": "an',
}


class TestMalformedGrantReleasesNothing(unittest.TestCase):
    """A grant file the reader rejects is no grant: release() lets nothing through, never raises,
    and leaves the file where it is (only the reaper removes it)."""

    def test_each_malformed_shape(self):
        nonce = f"{os.getpid()}-{int(time.time() * 1000)}"
        for name, body in MALFORMED.items():
            with self.subTest(shape=name):
                sid = f"test-malformed-{name}-{nonce}"
                path = sentinel_grant_path(sid)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body.replace('"t"', json.dumps(sid)), encoding="utf-8")
                try:
                    self.assertIsNone(load_sentinel_grant_for_task(sid))
                    self.assertIsNone(release(_payload(sid)))
                    self.assertTrue(path.exists())
                finally:
                    path.unlink(missing_ok=True)

    def test_a_valid_grant_of_the_same_shape_is_released_once(self):
        sid = f"test-malformed-control-{os.getpid()}-{int(time.time() * 1000)}"
        path = write_sentinel_grant(sid, sid, SCOPE)
        try:
            self.assertEqual(release(_payload(sid))["scope"], SCOPE)
            self.assertFalse(path.exists())
            self.assertIsNone(release(_payload(sid)))
        finally:
            path.unlink(missing_ok=True)


class TestReapTakesTheReadersVerdict(unittest.TestCase):
    """reap_expired_sentinel_grants removes every grant the reader rejects and
    keeps every grant it accepts."""

    def test_rejected_grants_go_and_live_ones_stay(self):
        nonce = f"{os.getpid()}-{int(time.time() * 1000)}"
        live = write_sentinel_grant(f"test-reap-live-{nonce}", "s", SCOPE)
        rejected = dict(MALFORMED)
        paths = []
        for name, body in rejected.items():
            path = sentinel_grant_path(f"test-reap-{name}-{nonce}")
            path.write_text(body, encoding="utf-8")
            paths.append(path)
        try:
            self.assertGreaterEqual(reap_expired_sentinel_grants(), len(rejected))
            self.assertEqual([p for p in paths if p.exists()], [])
            self.assertTrue(live.exists())
        finally:
            for path in paths + [live]:
                if path.exists():
                    path.unlink()


class TestHasDoConsent(unittest.TestCase):
    """has_do_consent: the one /do consent decision, and its shell entry point."""

    def setUp(self):
        self.sid = f"test-do-consent-{os.getpid()}-{int(time.time() * 1000)}"
        self.flag = Path(harness_state_dir(), f"claude-orchestrator-consent-{self.sid}.flag")

    def tearDown(self):
        if self.flag.exists():
            self.flag.unlink()

    def _entry_point(self, payload):
        return subprocess.run(
            [sys.executable, os.path.join(HOOKS_DIR, "lib", "allowlist.py"), "consent"],
            input=payload, capture_output=True, text=True, timeout=20,
        ).returncode

    def test_main_agent_with_the_flag_holds_consent(self):
        self.flag.write_text("true\n")
        payload = {"session_id": self.sid}
        self.assertTrue(has_do_consent(payload))
        self.assertEqual(self._entry_point(json.dumps(payload)), 0)

    def test_a_subagent_never_holds_consent(self):
        self.flag.write_text("true")
        payload = {"session_id": self.sid, "agent_id": "a1"}
        self.assertFalse(has_do_consent(payload))
        self.assertEqual(self._entry_point(json.dumps(payload)), 1)

    def test_no_flag_other_content_or_no_session_is_no_consent(self):
        self.assertFalse(has_do_consent({"session_id": self.sid}))
        self.flag.write_text("")
        self.assertFalse(has_do_consent({"session_id": self.sid}))
        self.flag.write_text("true")
        self.assertFalse(has_do_consent({"session_id": self.sid + "-other"}))
        self.assertFalse(has_do_consent({}))
        self.assertFalse(has_do_consent(["not", "a", "payload"]))
        self.assertEqual(self._entry_point("not json"), 1)


if __name__ == "__main__":
    unittest.main()
