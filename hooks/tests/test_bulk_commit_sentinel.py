"""Tests for bulk-commit sentinel mechanism.

Covers:
  - _has_bulk_commit_sentinel: valid sentinel allows, missing/expired/wrong-kind blocks
  - _evaluate_commit: BLESSED_BRIDGE_RE match requires sentinel; regular commits use grant path
  - scripts/write-bulk-commit-sentinel.py: writes correct JSON with valid expiry

Task: /do bulk-commit sentinel enforcement (2026-05-24).
"""

import json
import os
import subprocess
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
        "origin": "userpromptsubmit-hook",
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
            # No candidate grants => the regular path fails closed (default-deny);
            # the key assertion is that the sentinel path is never consulted.
            # (Post grant-selection refactor _evaluate_commit collects candidates
            # via _collect_commit_grant_candidates, not _find_grant/_find_grant_any.)
            with patch.object(guard, "_collect_commit_grant_candidates", return_value=[]):
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


class TestCommitGrantRedirectBinding(unittest.TestCase):
    """Regression coverage for the 2026-07-16 commit-grant redirect-vector closure.

    A commit grant is bound to a specific repo/branch/HEAD. Before this fix the
    binding validated ONLY the first `-C <dir>`, so a commit could still land in
    a DIFFERENT repo via --git-dir/--work-tree flags, GIT_DIR/GIT_WORK_TREE env
    (inline or ambient), or a second chained `git -C <other> commit`. Each vector
    below is exercised against REAL git repos so the block/allow reflects the
    guard's true behavior, not a mock.
    """

    @classmethod
    def _init_repo(cls, path):
        import subprocess
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
        (path / "f.txt").write_text("x\n")
        subprocess.run(["git", "add", "."], cwd=path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=path,
                             capture_output=True, text=True).stdout.strip()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path,
                              capture_output=True, text=True).stdout.strip()
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=path,
                                capture_output=True, text=True).stdout.strip()
        return {"path": str(path), "top": top, "head": head, "branch": branch}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.A = self._init_repo(base / "repoA")
        self.B = self._init_repo(base / "repoB")
        # Run the guard's git probes as if cwd == repo A (the grant's repo).
        self._cwd = os.getcwd()
        os.chdir(self.A["path"])
        # Ensure no ambient redirect leaks in from the outer environment.
        self._saved_env = {k: os.environ.pop(k, None)
                           for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")}

    def tearDown(self):
        os.chdir(self._cwd)
        for k, v in self._saved_env.items():
            if v is not None:
                os.environ[k] = v
        self._tmp.cleanup()

    def _grant_for(self, repo):
        return {
            "task_id": "20260716-test",
            "repo_root": repo["top"],
            "branch": repo["branch"],
            "expected_head": repo["head"],
        }

    def _assert_blocks(self, command, grant):
        with self.assertRaises(SystemExit) as ctx:
            guard._enforce_commit_grant_binding(grant, command)
        self.assertEqual(ctx.exception.code, 2)

    def _assert_allows(self, command, grant):
        try:
            guard._enforce_commit_grant_binding(grant, command)
        except SystemExit as e:
            self.fail(f"binding unexpectedly blocked {command!r}: exit {e.code}")

    # ---- HOLE 1: --git-dir/--work-tree redirect ----
    def test_hole1_git_dir_work_tree_flag_redirect_blocks(self):
        cmd = (f'git --git-dir={self.B["path"]}/.git --work-tree={self.B["path"]} '
               f'commit -m "sneak into B"')
        self._assert_blocks(cmd, self._grant_for(self.A))

    def test_hole1_git_dir_flag_only_blocks(self):
        cmd = f'git --git-dir={self.B["path"]}/.git commit -m "sneak"'
        self._assert_blocks(cmd, self._grant_for(self.A))

    def test_namespace_flag_redirect_blocks(self):
        cmd = f'git --namespace=sneaky -C {self.A["path"]} commit -m "ns"'
        self._assert_blocks(cmd, self._grant_for(self.A))

    # ---- HOLE 2: inline + ambient GIT_DIR/GIT_WORK_TREE ----
    def test_hole2_inline_env_redirect_blocks(self):
        cmd = (f'GIT_DIR={self.B["path"]}/.git GIT_WORK_TREE={self.B["path"]} '
               f'git commit -m "sneak into B"')
        self._assert_blocks(cmd, self._grant_for(self.A))

    def test_hole2_inline_git_dir_only_blocks(self):
        cmd = f'GIT_DIR={self.B["path"]}/.git git commit -m "sneak"'
        self._assert_blocks(cmd, self._grant_for(self.A))

    def test_hole2_ambient_env_redirect_blocks(self):
        os.environ["GIT_DIR"] = f'{self.B["path"]}/.git'
        os.environ["GIT_WORK_TREE"] = self.B["path"]
        try:
            self._assert_blocks('git commit -m "sneak"', self._grant_for(self.A))
        finally:
            os.environ.pop("GIT_DIR", None)
            os.environ.pop("GIT_WORK_TREE", None)

    # ---- HOLE 3: second chained commit invocation ----
    def test_hole3_second_chained_commit_blocks(self):
        cmd = (f'git -C {self.A["path"]} commit -m "ok in A" ; '
               f'git -C {self.B["path"]} commit -m "sneak into B"')
        self._assert_blocks(cmd, self._grant_for(self.A))

    def test_hole3_ampersand_chained_commit_blocks(self):
        cmd = (f'git -C {self.A["path"]} commit -m "ok" && '
               f'git -C {self.B["path"]} commit -m "sneak"')
        self._assert_blocks(cmd, self._grant_for(self.A))

    def test_hole3_second_bare_commit_wrong_repo_blocks(self):
        # First invocation targets A (grant repo); second bare commit would run
        # in cwd (A) -> allowed only because it matches. Flip: grant bound to B
        # but a bare same-string commit runs in A -> must block.
        cmd = 'git commit -m "one" ; git commit -m "two"'
        self._assert_blocks(cmd, self._grant_for(self.B))

    # ---- enumerator correctness ----
    def test_enumerator_counts_every_commit(self):
        cmd = (f'git -C {self.A["path"]} commit -m "a" ; '
               f'git -C {self.B["path"]} commit -m "b"')
        invs = list(guard._iter_commit_invocations(cmd))
        self.assertEqual(len(invs), 2)

    def test_enumerator_ignores_commit_word_in_message(self):
        cmd = 'git commit -m "please git commit later and run git commit"'
        invs = list(guard._iter_commit_invocations(cmd))
        self.assertEqual(len(invs), 1)

    # ---- HAPPY paths must still ALLOW ----
    def test_happy_bare_same_repo_commit_allows(self):
        self._assert_allows('git commit -m "normal"', self._grant_for(self.A))

    def test_happy_dash_c_matching_repo_allows(self):
        cmd = f'git -C {self.A["path"]} commit -m "normal via -C"'
        self._assert_allows(cmd, self._grant_for(self.A))

    def test_happy_nested_repo_recovery_allows(self):
        # Grant bound to nested repo B; commit targets B via -C while hook cwd is A.
        cmd = f'git -C {self.B["path"]} commit -m "nested repo commit"'
        self._assert_allows(cmd, self._grant_for(self.B))

    def test_happy_multi_commit_all_matching_allows(self):
        cmd = (f'git -C {self.A["path"]} commit -m "one" ; '
               f'git -C {self.A["path"]} commit -m "two"')
        self._assert_allows(cmd, self._grant_for(self.A))

    # ---- fail-closed edges ----
    def test_multiple_dash_c_blocks(self):
        cmd = f'git -C {self.A["path"]} -C {self.B["path"]} commit -m "ambiguous"'
        self._assert_blocks(cmd, self._grant_for(self.A))

    def test_unresolved_shell_var_dash_c_blocks(self):
        cmd = 'git -C ${GIT_ROOT} commit -m "unexpanded"'
        self._assert_blocks(cmd, self._grant_for(self.A))


class TestCommitGrantRepoMatchingSelection(unittest.TestCase):
    """Regression (docs/dev/peer-review-grant-parity.md CRITICAL): the guard must
    SELECT the commit grant whose repo_root/branch/expected_head match the commit's
    TARGET repo -- not merely the most-recent grant.

    /commit (BULK=false) writes TWO repo-bound grants: grant1 -> CONTROL_ROOT, then
    grant2 -> ~/.claude (written second => newer mtime). The root-repo commit fires
    FIRST; picking by recency binds it to grant2 (~/.claude) and BLOCKS it on a repo
    mismatch. This test builds the real topology target-repo != ~/.claude (two
    throwaway git repos) so the bug is NOT masked as it is in the self-hosted
    checkout where realpath(~/.claude) == CWD. Exercises _evaluate_commit end-to-end
    (grant discovery + selection + binding), not just the binding validators.
    """

    def setUp(self):
        self._repos = []
        # _enforce_commit_grant_binding fails closed on an ambient GIT_DIR/
        # GIT_WORK_TREE/GIT_COMMON_DIR redirect; ensure none leak in from the
        # outer environment so the repo-match selection can be exercised.
        self._saved_env = {
            k: os.environ.pop(k, None)
            for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")
        }

    def tearDown(self):
        import shutil
        for d in self._repos:
            shutil.rmtree(d, ignore_errors=True)
        for k, v in self._saved_env.items():
            if v is not None:
                os.environ[k] = v

    def _init_repo(self):
        """Create a throwaway git repo with one commit; return its resolved
        toplevel/branch/HEAD (as git itself reports them, so grant.repo_root
        compares equal to `git rev-parse --show-toplevel`)."""
        d = tempfile.mkdtemp(prefix="grant-sel-")
        self._repos.append(d)
        subprocess.run(["git", "init", "-q", d], check=True)
        subprocess.run(["git", "-C", d, "config", "user.email", "t@example.com"], check=True)
        subprocess.run(["git", "-C", d, "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", d, "config", "commit.gpgsign", "false"], check=True)
        (Path(d) / "seed.txt").write_text("seed\n")
        subprocess.run(["git", "-C", d, "add", "-A"], check=True)
        subprocess.run(["git", "-C", d, "commit", "-q", "-m", "seed"], check=True)

        def _q(*args):
            return subprocess.run(
                ["git", "-C", d, *args], capture_output=True, text=True, check=True
            ).stdout.strip()

        return {
            "top": _q("rev-parse", "--show-toplevel"),
            "branch": _q("branch", "--show-current"),
            "head": _q("rev-parse", "HEAD"),
        }

    @staticmethod
    def _write_grant(dirpath, sid, repo_root, branch, head, mtime):
        import secrets
        nonce = secrets.token_hex(8)
        now = datetime.now(timezone.utc)
        grant = {
            "task_id": "grant-sel-test",
            "sid": sid,
            "nonce": nonce,
            "repo_root": repo_root,
            "branch": branch,
            "expected_head": head,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=30)).isoformat(),
        }
        path = Path(dirpath) / f"claude-commit-grant-{sid}-{nonce}.json"
        path.write_text(json.dumps(grant))
        os.utime(path, (mtime, mtime))
        return str(path)

    @staticmethod
    def _fake_glob_returning(grant_paths):
        """glob.glob replacement: yield the given commit-grant files for any
        commit-grant pattern, and delegate real globbing for everything else
        (so allowlist / sentinel internals are unaffected)."""
        import glob as _glob_mod
        real_glob = _glob_mod.glob

        def fake(pattern, *args, **kwargs):
            if "claude-commit-grant-" in pattern and not pattern.endswith(".lck"):
                return list(grant_paths)
            return real_glob(pattern, *args, **kwargs)

        return fake

    def test_selects_repo_matching_grant_over_newer_nonmatching(self):
        """POSITIVE: with two repo-bound grants (root=older, other=newer), a
        commit targeting the ROOT repo is AUTHORIZED and binds to the ROOT grant.
        FAILS against the pre-fix guard (it selects the newer non-matching grant
        and blocks on repo mismatch); PASSES once selection prefers the match."""
        root = self._init_repo()
        other = self._init_repo()
        sid = "grant-sel-sid"
        with tempfile.TemporaryDirectory() as gdir:
            base = time.time()
            g_root = self._write_grant(
                gdir, sid, root["top"], root["branch"], root["head"], mtime=base - 20
            )
            g_other = self._write_grant(
                gdir, sid, other["top"], other["branch"], other["head"], mtime=base
            )
            cmd = f'git -C {root["top"]} commit -m "chore: root commit"'
            data = _make_data(session_id=sid)
            with patch("glob.glob", side_effect=self._fake_glob_returning([g_root, g_other])):
                with patch.object(guard, "_lock_grant_for_posttool") as mock_lock:
                    try:
                        guard._evaluate_commit(cmd, data)
                    except SystemExit as exc:
                        self.fail(
                            "Guard BLOCKED a legitimate root commit (exit %s): it selected "
                            "the newer non-matching grant instead of the repo-matching one."
                            % exc.code
                        )
            mock_lock.assert_called_once()
            selected_path = mock_lock.call_args.args[0]
            self.assertEqual(
                selected_path,
                g_root,
                "Guard must select/lock the ROOT-repo grant, not the newer OTHER-repo grant.",
            )

    def test_blocks_when_no_grant_matches_target_repo(self):
        """NEGATIVE (security preserved): only an OTHER-repo grant exists; a commit
        targeting the ROOT repo is BLOCKED (exit 2) and no grant is locked."""
        root = self._init_repo()
        other = self._init_repo()
        sid = "grant-sel-sid-neg"
        with tempfile.TemporaryDirectory() as gdir:
            g_other = self._write_grant(
                gdir, sid, other["top"], other["branch"], other["head"], mtime=time.time()
            )
            cmd = f'git -C {root["top"]} commit -m "chore: root commit"'
            data = _make_data(session_id=sid)
            with patch("glob.glob", side_effect=self._fake_glob_returning([g_other])):
                with patch.object(guard, "_lock_grant_for_posttool") as mock_lock:
                    with self.assertRaises(SystemExit) as ctx:
                        guard._evaluate_commit(cmd, data)
                    self.assertEqual(ctx.exception.code, 2)
                    mock_lock.assert_not_called()

    def test_blocks_when_no_grant_present(self):
        """NEGATIVE (security preserved): no grant at all => default-deny (exit 2)."""
        root = self._init_repo()
        sid = "grant-sel-sid-empty"
        cmd = f'git -C {root["top"]} commit -m "chore: root commit"'
        data = _make_data(session_id=sid)
        with patch("glob.glob", side_effect=self._fake_glob_returning([])):
            with patch.object(guard, "_lock_grant_for_posttool") as mock_lock:
                with self.assertRaises(SystemExit) as ctx:
                    guard._evaluate_commit(cmd, data)
                self.assertEqual(ctx.exception.code, 2)
                mock_lock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
