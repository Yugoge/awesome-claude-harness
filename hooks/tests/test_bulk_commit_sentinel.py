"""Tests for bulk-commit sentinel mechanism.

Covers:
  - _has_bulk_commit_sentinel: valid sentinel allows, missing/expired/wrong-kind blocks
  - _evaluate_commit: BLESSED_BRIDGE_RE match requires sentinel; regular commits use grant path
  - scripts/write-bulk-commit-sentinel.py: writes correct JSON with valid expiry

Task: /do bulk-commit sentinel enforcement (2026-05-24).
"""

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import importlib.util

HOOKS_DIR = Path(__file__).parent.parent
SCRIPTS_DIR = HOOKS_DIR.parent / "scripts"


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    # Add hooks dir to sys.path so the module's own imports work
    hooks_str = str(HOOKS_DIR)
    if hooks_str not in sys.path:
        sys.path.insert(0, hooks_str)
    spec.loader.exec_module(mod)
    return mod


guard = _load_module(HOOKS_DIR / "pretool-git-privilege-guard.py", "pretool_git_privilege_guard")


def _make_data(agent_id=None, session_id="test-sid-abc123"):
    return {
        "tool_name": "Bash",
        "session_id": session_id,
        **({"agent_id": agent_id} if agent_id else {}),
        "tool_input": {"command": ""},
    }


def _write_sentinel(tmpdir, sid="test-sid-abc123", kind="bulk-commit", expired=False):
    import secrets
    nonce = secrets.token_hex(8)
    now = datetime.now(timezone.utc)
    if expired:
        expires_at = (now - timedelta(minutes=1)).isoformat()
    else:
        expires_at = (now + timedelta(minutes=30)).isoformat()
    sentinel = {
        "kind": kind,
        "sid": sid,
        "nonce": nonce,
        "created_at": now.isoformat(),
        "expires_at": expires_at,
    }
    path = Path(tmpdir) / f"claude-bulk-commit-sentinel-{sid}-{nonce}.json"
    path.write_text(json.dumps(sentinel))
    return str(path)


class TestHasBulkCommitSentinel(unittest.TestCase):

    def test_valid_sentinel_returns_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_sentinel(tmpdir)
            with patch("glob.glob", side_effect=lambda p: [
                str(f) for f in Path(tmpdir).glob("claude-bulk-commit-sentinel-*.json")
            ]):
                result = guard._has_bulk_commit_sentinel(_make_data())
        self.assertTrue(result)

    def test_no_sentinel_returns_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("glob.glob", return_value=[]):
                result = guard._has_bulk_commit_sentinel(_make_data())
        self.assertFalse(result)

    def test_expired_sentinel_returns_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_sentinel(tmpdir, expired=True)
            with patch("glob.glob", side_effect=lambda p: [
                str(f) for f in Path(tmpdir).glob("claude-bulk-commit-sentinel-*.json")
            ]):
                result = guard._has_bulk_commit_sentinel(_make_data())
        self.assertFalse(result)

    def test_wrong_kind_returns_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_sentinel(tmpdir, kind="commit")  # regular grant kind, not bulk-commit
            with patch("glob.glob", side_effect=lambda p: [
                str(f) for f in Path(tmpdir).glob("claude-bulk-commit-sentinel-*.json")
            ]):
                result = guard._has_bulk_commit_sentinel(_make_data())
        self.assertFalse(result)

    def test_malformed_json_returns_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = Path(tmpdir) / "claude-bulk-commit-sentinel-test-sid-abc123-deadbeef.json"
            bad.write_text("{not valid json")
            with patch("glob.glob", side_effect=lambda p: [str(bad)]):
                result = guard._has_bulk_commit_sentinel(_make_data())
        self.assertFalse(result)

    def test_global_fallback_finds_different_sid(self):
        """Global fallback allows subagent (different SID) to find orchestrator's sentinel."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_sentinel(tmpdir, sid="orchestrator-sid-xyz")
            all_files = [str(f) for f in Path(tmpdir).glob("claude-bulk-commit-sentinel-*.json")]

            def fake_glob(pattern):
                if "subagent-sid" in pattern:
                    return []  # SID-specific miss
                return all_files   # global fallback hits

            with patch("glob.glob", side_effect=fake_glob):
                result = guard._has_bulk_commit_sentinel(_make_data(session_id="subagent-sid-999"))
        self.assertTrue(result)


class TestEvaluateCommitBlessedBridge(unittest.TestCase):

    BULK_CMD = 'git commit -m "auto-bulk: end-of-cycle commit for master"'
    REGULAR_CMD = 'git commit -m "feat(hooks): add new check"'

    def test_blessed_bridge_with_sentinel_allowed(self):
        with patch.object(guard, "_has_bulk_commit_sentinel", return_value=True):
            # Should not raise SystemExit(2)
            try:
                guard._evaluate_commit(self.BULK_CMD, _make_data())
            except SystemExit as e:
                self.fail(f"_evaluate_commit blocked with sentinel present: exit {e.code}")

    def test_blessed_bridge_without_sentinel_blocked(self):
        with patch.object(guard, "_has_bulk_commit_sentinel", return_value=False):
            with self.assertRaises(SystemExit) as ctx:
                guard._evaluate_commit(self.BULK_CMD, _make_data())
            self.assertEqual(ctx.exception.code, 2)

    def test_regular_commit_bypasses_sentinel_check(self):
        """Regular commits don't go through BLESSED_BRIDGE_RE path."""
        with patch.object(guard, "_has_bulk_commit_sentinel") as mock_sentinel:
            # Provide a valid grant so the regular path allows
            mock_grant_path = "/tmp/fake-grant.json"
            mock_grant = {
                "task_id": "20260524-000000",
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            }
            with patch.object(guard, "_find_grant", return_value=(None, None)):
                with patch.object(guard, "_find_grant_any", return_value=(mock_grant_path, mock_grant)):
                    with patch.object(guard, "_unlink_grant"):
                        try:
                            guard._evaluate_commit(self.REGULAR_CMD, _make_data())
                        except SystemExit:
                            pass  # blocked is also acceptable; key check is sentinel not called
            mock_sentinel.assert_not_called()


_writer = _load_module(SCRIPTS_DIR / "write-bulk-commit-sentinel.py", "write_bulk_commit_sentinel")


class TestWriteBulkCommitSentinelScript(unittest.TestCase):

    def test_writes_valid_sentinel_file(self):
        writer = _writer
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"CLAUDE_SESSION_ID": "test-session-999"}):
                rc = writer.main(["--output-dir", tmpdir])
            self.assertEqual(rc, 0)
            files = list(Path(tmpdir).glob("claude-bulk-commit-sentinel-*.json"))
            self.assertEqual(len(files), 1)
            data = json.loads(files[0].read_text())
            self.assertEqual(data["kind"], "bulk-commit")
            self.assertEqual(data["sid"], "test-session-999")
            # expires_at must be ISO-8601 with timezone
            expires = datetime.fromisoformat(data["expires_at"])
            self.assertIsNotNone(expires.tzinfo)
            self.assertGreater(expires, datetime.now(timezone.utc))

    def test_succeeds_with_only_claude_code_session_id(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID")}
        env["CLAUDE_CODE_SESSION_ID"] = "test-code-session-abc"
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, env, clear=True):
                rc = _writer.main(["--output-dir", tmpdir])
            self.assertEqual(rc, 0)
            files = list(Path(tmpdir).glob("claude-bulk-commit-sentinel-*.json"))
            self.assertEqual(len(files), 1)
            data = json.loads(files[0].read_text())
            self.assertEqual(data["sid"], "test-code-session-abc")

    def test_fails_without_session_id(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID")}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(SystemExit) as ctx:
                _writer.main([])
            self.assertEqual(ctx.exception.code, 2)

    def test_ttl_is_30_minutes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"CLAUDE_SESSION_ID": "ttl-test"}):
                _writer.main(["--output-dir", tmpdir])
            files = list(Path(tmpdir).glob("claude-bulk-commit-sentinel-*.json"))
            data = json.loads(files[0].read_text())
            created = datetime.fromisoformat(data["created_at"])
            expires = datetime.fromisoformat(data["expires_at"])
            delta_minutes = (expires - created).total_seconds() / 60
            self.assertAlmostEqual(delta_minutes, 30, delta=0.1)


class TestExtractCommitMessageFFlag(unittest.TestCase):
    """Guard correctly extracts subject from -F <tmpfile> (changelog-analyst's real commit path)."""

    def test_f_flag_blessed_bridge_allowed_with_sentinel(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("auto-bulk: end-of-cycle commit for master — hooks updates\n\nsome body\n")
            tmppath = f.name
        try:
            cmd = f'git -C /tmp commit -F {tmppath}'
            with patch.object(guard, "_has_bulk_commit_sentinel", return_value=True):
                try:
                    guard._evaluate_commit(cmd, _make_data())
                except SystemExit as e:
                    self.fail(f"Blocked -F bulk commit with sentinel: {e}")
        finally:
            os.unlink(tmppath)

    def test_f_flag_blessed_bridge_blocked_without_sentinel(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("auto-bulk: end-of-cycle commit for master — hooks updates\n")
            tmppath = f.name
        try:
            cmd = f'git -C /tmp commit -F {tmppath}'
            with patch.object(guard, "_has_bulk_commit_sentinel", return_value=False):
                with self.assertRaises(SystemExit) as ctx:
                    guard._evaluate_commit(cmd, _make_data())
                self.assertEqual(ctx.exception.code, 2)
        finally:
            os.unlink(tmppath)

    def test_f_flag_nonexistent_file_does_not_crash(self):
        cmd = 'git commit -F /tmp/nonexistent-commit-msg-xyz.txt'
        with patch.object(guard, "_find_grant", return_value=(None, None)):
            with patch.object(guard, "_find_grant_any", return_value=(None, None)):
                with self.assertRaises(SystemExit) as ctx:
                    guard._evaluate_commit(cmd, _make_data())
                self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
