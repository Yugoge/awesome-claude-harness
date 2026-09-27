"""Tests for allow-6 consolidation: hooks/lib/allowlist.py new functions.

Covers AC8 IS_SUBAGENT firewall scenarios and matching semantics invariants.

Task: 20260518-155948 — consolidate 5 independent grant-read implementations.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add hooks dir to path for lib.allowlist import
HOOKS_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, HOOKS_DIR)

from lib.allowlist import (
    MatchResult,
    _match_loaded_grant,
    _load_and_match,
    read_grant,
    read_grant_for_git_command,
    match_grant_for_bash_command,
    consume_grant_for_posttool,
    load_sentinel_grant_for_task,
    match_sentinel_grant_for_bash_command,
    match_sentinel_grant_for_write,
    consume_sentinel_grant_on_terminal_result,
    reap_expired_sentinel_grants,
    SENTINEL_GRANT_DIR,
)


class TestAllowSettingsPreflight(unittest.TestCase):
    """Known file-based settings DENYs resolve before either grant channel writes."""

    def _invoke(self, prompt, task_id, session_id, env_updates=None):
        hook = os.path.join(HOOKS_DIR, "userprompt-consent-allowlist.sh")
        payload = json.dumps({"prompt": prompt, "session_id": session_id})
        env = dict(os.environ)
        env["CLAUDE_TASK_ID"] = task_id
        env.update(env_updates or {})
        return subprocess.run(
            ["bash", hook], input=payload, capture_output=True, text=True,
            env=env, timeout=10,
        )

    def _paths(self, task_id, session_id):
        return (
            os.path.join(SENTINEL_GRANT_DIR, f"{task_id}.json"),
            f"/tmp/claude-bash-allowlist-{session_id}.json",
        )

    def _assert_hard_deny_record(
        self, result, *, origin, matched_rule, earlier_pending_grant_cleared
    ):
        self.assertIn("decision_class=hard_deny", result.stderr)
        self.assertIn("decision_actor=file_based_settings", result.stderr)
        self.assertIn(f"source_origin={origin}", result.stderr)
        self.assertIn(f"matched_rule={matched_rule}", result.stderr)
        self.assertIn("grant_written=false", result.stderr)
        self.assertIn("grant_consumed=false", result.stderr)
        self.assertIn("retry_with_allow=false", result.stderr)
        self.assertIn(
            f"earlier_pending_grant_cleared={str(earlier_pending_grant_cleared).lower()}",
            result.stderr,
        )
        self.assertIn("Repeating /allow cannot override the matched rule", result.stderr)
        self.assertIn("genuinely semantically safer operation", result.stderr)
        self.assertIn("human user to execute", result.stderr)
        self.assertIn("human user to explicitly change the permission policy", result.stderr)
        self.assertIn("Claude/Codex parity consequences", result.stderr)
        self.assertIn("abandon the operation", result.stderr)
        self.assertIn("must not use a syntactic rewrite", result.stderr)
        self.assertNotIn("Choose a non-denied alternative", result.stderr)
        self.assertNotIn("retry /allow", result.stderr.lower())

    def test_hard_deny_issues_no_grant_and_offers_no_allow_retry(self):
        task_id = "test-allow-hard-deny"
        session_id = "test-allow-hard-deny-session"
        paths = self._paths(task_id, session_id)
        for path in paths:
            if os.path.exists(path):
                os.unlink(path)
        try:
            result = self._invoke(
                "/allow rm -rf /tmp/non-grantable-target", task_id, session_id
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("absolute settings DENY", result.stderr)
            self.assertNotIn("retry /allow", result.stderr)
            self.assertFalse(any(os.path.exists(path) for path in paths))
        finally:
            for path in paths:
                if os.path.exists(path):
                    os.unlink(path)

    def test_ask_only_selector_keeps_one_use_grant_route(self):
        task_id = "test-allow-ask"
        session_id = "test-allow-ask-session"
        paths = self._paths(task_id, session_id)
        for path in paths:
            if os.path.exists(path):
                os.unlink(path)
        try:
            result = self._invoke("/allow rm -rf relative-target", task_id, session_id)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Grant recorded", result.stdout)
            self.assertTrue(all(os.path.exists(path) for path in paths))
        finally:
            for path in paths:
                if os.path.exists(path):
                    os.unlink(path)

    def test_trailing_colon_star_preserves_command_word_boundary(self):
        selectors = (
            "/allow ddrescue --help",
            "/allow sudoersctl --help",
            "/allow sum file",
            "/allow re:^ddrescue$",
        )
        for index, selector in enumerate(selectors):
            with self.subTest(selector=selector):
                task_id = f"test-allow-boundary-near-miss-{index}"
                session_id = f"test-allow-boundary-near-miss-session-{index}"
                paths = self._paths(task_id, session_id)
                for path in paths:
                    if os.path.exists(path):
                        os.unlink(path)
                try:
                    result = self._invoke(selector, task_id, session_id)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("Grant recorded", result.stdout)
                    self.assertNotIn("absolute settings DENY", result.stderr)
                    self.assertTrue(all(os.path.exists(path) for path in paths))
                finally:
                    for path in paths:
                        if os.path.exists(path):
                            os.unlink(path)

    def test_trailing_colon_star_still_denies_real_command_invocations(self):
        selectors = (
            "/allow dd if=/dev/zero of=/tmp/allow-boundary-test",
            "/allow sudo -n true",
            "/allow su root",
            r"/allow re:^dd\s+if=/dev/zero$",
        )
        for index, selector in enumerate(selectors):
            with self.subTest(selector=selector):
                task_id = f"test-allow-boundary-deny-{index}"
                session_id = f"test-allow-boundary-deny-session-{index}"
                paths = self._paths(task_id, session_id)
                for path in paths:
                    if os.path.exists(path):
                        os.unlink(path)
                try:
                    result = self._invoke(selector, task_id, session_id)
                    self.assertEqual(result.returncode, 0)
                    self.assertIn("absolute settings DENY", result.stderr)
                    self.assertNotIn("Grant recorded", result.stdout)
                    self.assertFalse(any(os.path.exists(path) for path in paths))
                finally:
                    for path in paths:
                        if os.path.exists(path):
                            os.unlink(path)

    def test_missing_configured_python_fails_closed_and_removes_stale_grants(self):
        task_id = "test-allow-missing-python"
        session_id = "test-allow-missing-python-session"
        paths = self._paths(task_id, session_id)
        for path in paths:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text("{}", encoding="utf-8")
        try:
            result = self._invoke(
                "/allow rm -rf relative-target",
                task_id,
                session_id,
                {"CLAUDE_PYTHON_BIN": "/definitely/missing/claude-python"},
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("configured Python interpreter is unavailable", result.stderr)
            self.assertFalse(any(os.path.exists(path) for path in paths))
        finally:
            for path in paths:
                if os.path.exists(path):
                    os.unlink(path)

    def test_live_config_dir_without_interpreter_still_records_grant(self):
        """Live shape: CLAUDE_CONFIG_DIR names a per-account runtime state dir
        that contains NO interpreter anywhere and CLAUDE_PYTHON_BIN is unset.
        The hook must resolve its interpreter structurally
        (hooks/lib/claude_home.sh) instead of deriving it from
        CLAUDE_CONFIG_DIR, so an explicit narrow selector still records the
        grant on BOTH channels (legacy flag + structured sentinel)."""
        with tempfile.TemporaryDirectory() as temp:
            config_dir = Path(temp) / "account-state"
            project_dir = Path(temp) / "project"
            config_dir.mkdir()
            project_dir.mkdir()
            # The account dir still participates in the settings-deny preflight
            # exactly as in production; it just carries no interpreter.
            (config_dir / "settings.json").write_text(
                json.dumps({"permissions": {"deny": []}}), encoding="utf-8"
            )

            task_id = "test-allow-live-config-dir"
            session_id = "test-allow-live-config-dir-session"
            paths = self._paths(task_id, session_id)
            for path in paths:
                if os.path.exists(path):
                    os.unlink(path)

            hook = os.path.join(HOOKS_DIR, "userprompt-consent-allowlist.sh")
            payload = json.dumps(
                {"prompt": "/allow git stash", "session_id": session_id}
            )
            env = dict(os.environ)
            env["CLAUDE_TASK_ID"] = task_id
            env["CLAUDE_CONFIG_DIR"] = str(config_dir)
            env["CLAUDE_PROJECT_DIR"] = str(project_dir)
            # The live defect shape has NO interpreter override: this test must
            # not inject one (that is what masked the defect elsewhere).
            env.pop("CLAUDE_PYTHON_BIN", None)
            try:
                result = subprocess.run(
                    ["bash", hook], input=payload, capture_output=True,
                    text=True, env=env, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn(
                    "configured Python interpreter is unavailable", result.stderr
                )
                self.assertIn("Grant recorded", result.stdout)
                self.assertTrue(all(os.path.exists(path) for path in paths))
            finally:
                for path in paths:
                    if os.path.exists(path):
                        os.unlink(path)

    def test_each_file_based_settings_source_denies_before_grant_write(self):
        source_names = ("user", "project_shared", "project_local")
        for index, denied_source in enumerate(source_names):
            with self.subTest(source=denied_source), tempfile.TemporaryDirectory() as temp:
                temp_root = Path(temp)
                config_dir = temp_root / "config"
                project_dir = temp_root / "project"
                project_settings_dir = project_dir / ".claude"
                config_dir.mkdir()
                project_settings_dir.mkdir(parents=True)
                source_paths = {
                    "user": config_dir / "settings.json",
                    "project_shared": project_settings_dir / "settings.json",
                    "project_local": project_settings_dir / "settings.local.json",
                }
                for source_name, source_path in source_paths.items():
                    source_path.write_text(
                        json.dumps({
                            "permissions": {
                                "deny": ["Bash(blockedcmd:*)"]
                                if source_name == denied_source else []
                            }
                        }),
                        encoding="utf-8",
                    )

                task_id = f"test-allow-settings-source-{index}"
                session_id = f"test-allow-settings-source-session-{index}"
                paths = self._paths(task_id, session_id)
                for path in paths:
                    if os.path.exists(path):
                        os.unlink(path)
                try:
                    result = self._invoke(
                        "/allow blockedcmd argument",
                        task_id,
                        session_id,
                        {
                            "CLAUDE_CONFIG_DIR": str(config_dir),
                            "CLAUDE_PROJECT_DIR": str(project_dir),
                            "CLAUDE_PYTHON_BIN": sys.executable,
                        },
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("known file-based absolute settings DENY", result.stderr)
                    self._assert_hard_deny_record(
                        result,
                        origin=denied_source,
                        matched_rule="Bash(blockedcmd:*)",
                        earlier_pending_grant_cleared=False,
                    )
                    self.assertNotIn("Grant recorded", result.stdout)
                    self.assertFalse(any(os.path.exists(path) for path in paths))
                finally:
                    for path in paths:
                        if os.path.exists(path):
                            os.unlink(path)

    def test_hard_deny_discloses_that_all_stale_grants_were_cleared(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            config_dir = temp_root / "config"
            project_dir = temp_root / "project"
            config_dir.mkdir()
            project_dir.mkdir()
            (config_dir / "settings.json").write_text(
                json.dumps({"permissions": {"deny": ["Bash(blockedcmd:*)"]}}),
                encoding="utf-8",
            )

            task_id = "test-allow-hard-deny-stale"
            session_id = "test-allow-hard-deny-stale-session"
            paths = self._paths(task_id, session_id) + (
                os.path.join(SENTINEL_GRANT_DIR, f"{task_id}-older.json"),
            )
            for path in paths:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_text("{}", encoding="utf-8")
            try:
                result = self._invoke(
                    "/allow blockedcmd argument",
                    task_id,
                    session_id,
                    {
                        "CLAUDE_CONFIG_DIR": str(config_dir),
                        "CLAUDE_PROJECT_DIR": str(project_dir),
                        "CLAUDE_PYTHON_BIN": sys.executable,
                    },
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self._assert_hard_deny_record(
                    result,
                    origin="user",
                    matched_rule="Bash(blockedcmd:*)",
                    earlier_pending_grant_cleared=True,
                )
                self.assertNotIn("Grant recorded", result.stdout)
                self.assertFalse(any(os.path.exists(path) for path in paths))
            finally:
                for path in paths:
                    if os.path.exists(path):
                        os.unlink(path)

    def test_absent_optional_project_sources_do_not_invent_a_denial(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            config_dir = temp_root / "config"
            project_dir = temp_root / "project"
            config_dir.mkdir()
            project_dir.mkdir()
            (config_dir / "settings.json").write_text(
                json.dumps({"permissions": {"deny": []}}), encoding="utf-8"
            )

            task_id = "test-allow-absent-optional-settings"
            session_id = "test-allow-absent-optional-settings-session"
            paths = self._paths(task_id, session_id)
            for path in paths:
                if os.path.exists(path):
                    os.unlink(path)
            try:
                result = self._invoke(
                    "/allow unobstructedcmd argument",
                    task_id,
                    session_id,
                    {
                        "CLAUDE_CONFIG_DIR": str(config_dir),
                        "CLAUDE_PROJECT_DIR": str(project_dir),
                        "CLAUDE_PYTHON_BIN": sys.executable,
                    },
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Grant recorded", result.stdout)
                self.assertTrue(all(os.path.exists(path) for path in paths))
            finally:
                for path in paths:
                    if os.path.exists(path):
                        os.unlink(path)

    def test_malformed_participating_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            config_dir = temp_root / "config"
            project_dir = temp_root / "project"
            project_settings_dir = project_dir / ".claude"
            config_dir.mkdir()
            project_settings_dir.mkdir(parents=True)
            (config_dir / "settings.json").write_text(
                json.dumps({"permissions": {"deny": []}}), encoding="utf-8"
            )
            (project_settings_dir / "settings.json").write_text(
                "{not-valid-json", encoding="utf-8"
            )

            task_id = "test-allow-malformed-settings"
            session_id = "test-allow-malformed-settings-session"
            paths = self._paths(task_id, session_id)
            for path in paths:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_text("{}", encoding="utf-8")
            try:
                result = self._invoke(
                    "/allow unobstructedcmd argument",
                    task_id,
                    session_id,
                    {
                        "CLAUDE_CONFIG_DIR": str(config_dir),
                        "CLAUDE_PROJECT_DIR": str(project_dir),
                        "CLAUDE_PYTHON_BIN": sys.executable,
                    },
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(
                    "participating file-based settings source could not be evaluated",
                    result.stderr,
                )
                self.assertNotIn("Grant recorded", result.stdout)
                self.assertFalse(any(os.path.exists(path) for path in paths))
            finally:
                for path in paths:
                    if os.path.exists(path):
                        os.unlink(path)


class TestMatchLoadedGrant(unittest.TestCase):
    """Unit tests for _match_loaded_grant (pure match, no I/O)."""

    def _grant(self, pattern, is_regex=False):
        return {"pattern": pattern, "is_regex": is_regex}

    def test_exact_or_substr_exact_match(self):
        result = _match_loaded_grant(
            self._grant("Write"), ["Write"], "exact_or_substr", None
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.pattern, "Write")
        self.assertFalse(result.is_regex)
        self.assertEqual(result.matched_sub, "Write")

    def test_exact_or_substr_substring_match(self):
        result = _match_loaded_grant(
            self._grant("git"), ["git push origin"], "exact_or_substr", None
        )
        self.assertIsNotNone(result)

    def test_substr_only_no_exact_match(self):
        # substr_only: "Write" must be IN the candidate as a substring
        # "Write" is not a substring of "TodoWrite" being checked differently —
        # here we test that "Write" IN "TodoWrite" is True (which it is),
        # but the policy difference is: exact_or_substr also allows pattern == cand
        result = _match_loaded_grant(
            self._grant("write"), ["git commit -m write something"], "substr_only", None
        )
        self.assertIsNotNone(result)

    def test_substr_only_rejects_no_substr(self):
        result = _match_loaded_grant(
            self._grant("push"), ["git pull"], "substr_only", None
        )
        self.assertIsNone(result)

    def test_regex_match(self):
        result = _match_loaded_grant(
            self._grant(r"git\s+push", True), ["git push origin"], "substr_only", None
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.is_regex)

    def test_invalid_pattern_returns_none(self):
        result = _match_loaded_grant({"pattern": "", "is_regex": False}, ["anything"], "exact_or_substr", None)
        self.assertIsNone(result)

    def test_missing_pattern_key_returns_none(self):
        result = _match_loaded_grant({}, ["anything"], "exact_or_substr", None)
        self.assertIsNone(result)

    def test_first_candidate_wins(self):
        result = _match_loaded_grant(
            self._grant("b"), ["a", "b", "c"], "exact_or_substr", None
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.matched_sub, "b")


class TestLoadAndMatch(unittest.TestCase):
    """Unit tests for _load_and_match (blocking-lock wrapper)."""

    def _write_grant(self, path, pattern, is_regex=False):
        with open(path, "w") as f:
            json.dump({"pattern": pattern, "is_regex": is_regex}, f)

    def test_match_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            grant_path = os.path.join(tmpdir, "claude-bash-allowlist-testsid.json")
            self._write_grant(grant_path, "git push")
            with patch("lib.allowlist.Path") as MockPath:
                MockPath.return_value = Path(grant_path)
                result = _load_and_match("testsid", ["git push origin"], "substr_only", None)
            self.assertIsNotNone(result)

    def test_missing_file_returns_none(self):
        result = _load_and_match("nonexistent_sid_xyz", ["anything"], "exact_or_substr", None)
        self.assertIsNone(result)


class TestReadGrant(unittest.TestCase):
    """Unit tests for read_grant (public API, exact_or_substr semantics)."""

    def _write_grant(self, path, pattern, is_regex=False):
        with open(path, "w") as f:
            json.dump({"pattern": pattern, "is_regex": is_regex}, f)

    def test_exact_match_returns_true(self):
        with tempfile.NamedTemporaryFile(
            dir="/tmp", prefix="claude-bash-allowlist-rg1.", suffix=".json",
            mode="w", delete=False
        ) as f:
            sid = f.name.split("claude-bash-allowlist-rg1.")[1].replace(".json", "")
            # Reconstruct proper filename
            proper_path = f"/tmp/claude-bash-allowlist-rg1.{sid}.json"
        # Use a controlled SID
        test_sid = "test-read-grant-unit"
        grant_path = f"/tmp/claude-bash-allowlist-{test_sid}.json"
        try:
            self._write_grant(grant_path, "Write")
            self.assertTrue(read_grant("Write", test_sid))
        finally:
            if os.path.exists(grant_path):
                os.unlink(grant_path)

    def test_no_match_returns_false(self):
        test_sid = "test-read-grant-nomatch"
        grant_path = f"/tmp/claude-bash-allowlist-{test_sid}.json"
        try:
            with open(grant_path, "w") as f:
                json.dump({"pattern": "Bash", "is_regex": False}, f)
            self.assertFalse(read_grant("Write", test_sid))
        finally:
            if os.path.exists(grant_path):
                os.unlink(grant_path)

    def test_missing_grant_returns_false(self):
        self.assertFalse(read_grant("Write", "sid-that-does-not-exist-abc123"))

    # AC-D1 regression (cycle 20260519-211515 Item D): read_grant is exact_only.
    # Substring grants (e.g. '/allow Re') MUST NOT match the tool name 'Read'
    # at PreTool. This closes the PreTool/PostTool asymmetry that allowed
    # grant leakage past single-use.
    def test_read_grant_exact_only_rejects_substring(self):
        """Grant pattern 'Re' must NOT match tool name 'Read' (AC-D1)."""
        test_sid = "test-read-grant-exact-only"
        grant_path = f"/tmp/claude-bash-allowlist-{test_sid}.json"
        try:
            with open(grant_path, "w") as f:
                json.dump({"pattern": "Re", "is_regex": False}, f)
            # Pre-cycle behavior: exact_or_substr would have returned True
            # ("Re" in "Read"). New exact_only semantics returns False.
            self.assertFalse(read_grant("Read", test_sid))
            # Grant file MUST still exist (read-only, no unlink).
            self.assertTrue(os.path.exists(grant_path))
        finally:
            if os.path.exists(grant_path):
                os.unlink(grant_path)

    # AC-D1 additional regression: '/allow Write' must NOT match 'TodoWrite'
    # at PreTool (was the original asymmetry — PostTool was already exact-only
    # via Branch 3 of consume_grant_for_posttool, but PreTool was substr).
    def test_read_grant_exact_only_rejects_write_against_todowrite(self):
        """Grant pattern 'Write' must NOT match tool name 'TodoWrite' (AC-D1)."""
        test_sid = "test-read-grant-write-vs-todowrite"
        grant_path = f"/tmp/claude-bash-allowlist-{test_sid}.json"
        try:
            with open(grant_path, "w") as f:
                json.dump({"pattern": "Write", "is_regex": False}, f)
            self.assertFalse(read_grant("TodoWrite", test_sid))
        finally:
            if os.path.exists(grant_path):
                os.unlink(grant_path)


class TestReadGrantForGitCommand(unittest.TestCase):
    """Unit tests for read_grant_for_git_command (substr_only semantics)."""

    def test_substring_match(self):
        test_sid = "test-git-grant-1"
        grant_path = f"/tmp/claude-bash-allowlist-{test_sid}.json"
        try:
            with open(grant_path, "w") as f:
                json.dump({"pattern": "git push", "is_regex": False}, f)
            # substr_only: "git push" in "git push origin main"
            self.assertTrue(read_grant_for_git_command("git push origin main", test_sid))
        finally:
            if os.path.exists(grant_path):
                os.unlink(grant_path)

    def test_no_match(self):
        test_sid = "test-git-grant-2"
        grant_path = f"/tmp/claude-bash-allowlist-{test_sid}.json"
        try:
            with open(grant_path, "w") as f:
                json.dump({"pattern": "git push", "is_regex": False}, f)
            self.assertFalse(read_grant_for_git_command("git pull origin main", test_sid))
        finally:
            if os.path.exists(grant_path):
                os.unlink(grant_path)


class TestMatchGrantForBashCommand(unittest.TestCase):
    """Unit tests for match_grant_for_bash_command (NB-flock + subcommand split)."""

    def test_compound_command_match(self):
        test_sid = "test-bash-grant-1"
        grant_path = f"/tmp/claude-bash-allowlist-{test_sid}.json"
        try:
            with open(grant_path, "w") as f:
                json.dump({"pattern": "git stash", "is_regex": False}, f)
            result = match_grant_for_bash_command(
                "ls -la && git stash pop", test_sid
            )
            self.assertIsNotNone(result)
            self.assertEqual(result.pattern, "git stash")
        finally:
            if os.path.exists(grant_path):
                os.unlink(grant_path)

    def test_no_match(self):
        test_sid = "test-bash-grant-2"
        grant_path = f"/tmp/claude-bash-allowlist-{test_sid}.json"
        try:
            with open(grant_path, "w") as f:
                json.dump({"pattern": "git push", "is_regex": False}, f)
            result = match_grant_for_bash_command("ls -la && echo hello", test_sid)
            self.assertIsNone(result)
        finally:
            if os.path.exists(grant_path):
                os.unlink(grant_path)

    def test_missing_grant_returns_none(self):
        result = match_grant_for_bash_command("any command", "sid-does-not-exist-xyz")
        self.assertIsNone(result)


class TestConsumeGrantForPosttool(unittest.TestCase):
    """Unit tests for consume_grant_for_posttool (AC5, AC8 scenarios)."""

    def _write_grant(self, sid, pattern, is_regex=False):
        path = f"/tmp/claude-bash-allowlist-{sid}.json"
        with open(path, "w") as f:
            json.dump({"pattern": pattern, "is_regex": is_regex}, f)
        return path

    # AC8(b): /allow Write does NOT consume a TodoWrite call (exact-only non-Bash)
    def test_non_bash_literal_exact_only_no_consume_for_todowrite(self):
        """Grant 'Write' (literal) must NOT match tool_name 'TodoWrite'."""
        test_sid = "test-posttool-exact-1"
        grant_path = self._write_grant(test_sid, "Write")
        try:
            result = consume_grant_for_posttool(test_sid, "TodoWrite", "")
            self.assertFalse(result)
            # Grant should still exist (not consumed)
            self.assertTrue(os.path.exists(grant_path))
        finally:
            if os.path.exists(grant_path):
                os.unlink(grant_path)

    # AC8(b) positive: /allow Write DOES consume a Write call
    def test_non_bash_literal_exact_match_write(self):
        """Grant 'Write' (literal) matches tool_name 'Write' exactly."""
        test_sid = "test-posttool-exact-2"
        grant_path = self._write_grant(test_sid, "Write")
        try:
            result = consume_grant_for_posttool(test_sid, "Write", "")
            self.assertTrue(result)
            # Grant should be consumed (unlinked)
            self.assertFalse(os.path.exists(grant_path))
        finally:
            if os.path.exists(grant_path):
                os.unlink(grant_path)

    # AC8(c): Bash compound command is consumed correctly
    def test_bash_compound_command_consumed(self):
        """Bash compound command containing granted substring is consumed."""
        test_sid = "test-posttool-bash-1"
        grant_path = self._write_grant(test_sid, "git stash")
        try:
            result = consume_grant_for_posttool(
                test_sid, "Bash", "ls -la && git stash pop"
            )
            self.assertTrue(result)
            self.assertFalse(os.path.exists(grant_path))
        finally:
            if os.path.exists(grant_path):
                os.unlink(grant_path)

    def test_bash_no_match_not_consumed(self):
        """Bash command not matching grant pattern — grant preserved."""
        test_sid = "test-posttool-bash-2"
        grant_path = self._write_grant(test_sid, "git push")
        try:
            result = consume_grant_for_posttool(test_sid, "Bash", "ls -la")
            self.assertFalse(result)
            self.assertTrue(os.path.exists(grant_path))
        finally:
            if os.path.exists(grant_path):
                os.unlink(grant_path)

    def test_missing_grant_returns_false(self):
        result = consume_grant_for_posttool("sid-nonexistent-xyz", "Bash", "ls")
        self.assertFalse(result)

    def test_bash_exact_tool_name_fallback(self):
        """Grant pattern 'Bash' (literal) matches tool_name 'Bash' via fallback."""
        test_sid = "test-posttool-bash-fallback"
        grant_path = self._write_grant(test_sid, "Bash")
        try:
            result = consume_grant_for_posttool(test_sid, "Bash", "some-unmatched-command")
            self.assertTrue(result)
            self.assertFalse(os.path.exists(grant_path))
        finally:
            if os.path.exists(grant_path):
                os.unlink(grant_path)


class TestCheckGitAllowlistSubagentFirewall(unittest.TestCase):
    """AC8(a): subagent payload passed to git-guard returns False (IS_SUBAGENT firewall)."""

    def test_subagent_payload_returns_false(self):
        """_check_git_allowlist returns False for payloads with agent_id set."""
        # Import the function under test
        sys.path.insert(0, HOOKS_DIR)
        # We test the IS_SUBAGENT logic directly via the guard's _check_git_allowlist
        # by importing and calling it with a mock data dict containing agent_id
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "pretool_git_privilege_guard",
            os.path.join(HOOKS_DIR, "pretool-git-privilege-guard.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        # We only need _check_git_allowlist; loading the module runs no side effects
        # because it only defines functions at module level (no top-level execution)
        try:
            spec.loader.exec_module(mod)
        except SystemExit:
            pass  # Some guard modules may sys.exit(0) early on import in test context

        if hasattr(mod, "_check_git_allowlist"):
            # Subagent payload: agent_id present
            result = mod._check_git_allowlist(
                "git push origin main",
                {"agent_id": "some-agent-uuid", "session_id": "test-session"},
            )
            self.assertFalse(result)
        else:
            self.skipTest("_check_git_allowlist not accessible in test context")


class TestSentinelGrantLifecycle(unittest.TestCase):
    """Tests for sentinel-grant lifecycle (task 20260519-211515 R2 / AC2).

    Covers the consume-on-any-terminal-result contract for the four mandatory
    terminal-consumption cases: success, failure, non_zero, malformed,
    comment_only, and a terminal_consume integration round-trip.

    Each test asserts the corresponding grant file under SENTINEL_GRANT_DIR
    is unlinked after consumption — this is the post-condition invariant.
    """

    def setUp(self):
        os.makedirs(SENTINEL_GRANT_DIR, exist_ok=True)

    def _write_sentinel(self, task_id, ops=None, ttl=300, nonce=""):
        path = os.path.join(SENTINEL_GRANT_DIR, f"{task_id}{nonce}.json")
        now = time.time()
        grant = {
            "task_id": task_id,
            "session_id": "test-session",
            "allowed_operations": ops or [{"op": "ls"}],
            "created_at": now,
            "expires_at": now + ttl,
        }
        with open(path, "w") as f:
            json.dump(grant, f)
        return path

    def test_terminal_consume_success(self):
        """Sentinel grant is unlinked on terminal_result='success' (exit 0)."""
        task_id = "test-sentinel-success"
        path = self._write_sentinel(task_id)
        try:
            self.assertTrue(os.path.exists(path))
            self.assertTrue(consume_sentinel_grant_on_terminal_result(task_id, "success"))
            self.assertFalse(os.path.exists(path))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_terminal_consume_failure(self):
        """Sentinel grant is unlinked on terminal_result='failure' (is_error=True)."""
        task_id = "test-sentinel-failure"
        path = self._write_sentinel(task_id)
        try:
            self.assertTrue(consume_sentinel_grant_on_terminal_result(task_id, "failure"))
            self.assertFalse(os.path.exists(path))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_terminal_consume_non_zero(self):
        """Sentinel grant is unlinked on terminal_result='non_zero' (exit 1..255)."""
        task_id = "test-sentinel-non-zero"
        path = self._write_sentinel(task_id)
        try:
            self.assertTrue(consume_sentinel_grant_on_terminal_result(task_id, "non_zero"))
            self.assertFalse(os.path.exists(path))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_terminal_consume_malformed(self):
        """Malformed JSON grant is unlinked at posttool / reap time."""
        task_id = "test-sentinel-malformed"
        path = os.path.join(SENTINEL_GRANT_DIR, f"{task_id}.json")
        with open(path, "w") as f:
            f.write("{not valid json")
        try:
            # consume_sentinel_grant_on_terminal_result reaps unconditionally —
            # even malformed grants are unlinked when terminal_result is provided.
            self.assertTrue(consume_sentinel_grant_on_terminal_result(task_id, "malformed"))
            self.assertFalse(os.path.exists(path))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_comment_only_attack_pretool_denied_no_leftover(self):
        """comment_only: pretool denies (no sentinel exists for current task),
        AND posttool consume with terminal_result='comment_only' must NOT
        leave leftover state. The grant file simply does not exist, and
        consume returns False without raising.
        """
        task_id = "test-sentinel-comment-only-attack-nonexistent"
        # No sentinel file exists for this task_id.
        path = os.path.join(SENTINEL_GRANT_DIR, f"{task_id}.json")
        self.assertFalse(os.path.exists(path))
        # Pretool match against a malicious command containing the magic phrase
        # in a comment — no grant, structural match returns None.
        result = match_sentinel_grant_for_bash_command(
            task_id, "echo hello # /allow rm -rf /"
        )
        self.assertIsNone(result)
        # Posttool consume on comment_only terminal_result is a no-op,
        # returns False, and leaves zero leftover state.
        consumed = consume_sentinel_grant_on_terminal_result(task_id, "comment_only")
        self.assertFalse(consumed)
        self.assertFalse(os.path.exists(path))

    def test_terminal_consume_round_trip_unlinks_grant(self):
        """End-to-end: write sentinel → pretool match → posttool consume on
        any terminal result → assert grant file removed.

        This is the canonical terminal_consume integration scenario.
        """
        task_id = "test-sentinel-terminal-consume-round-trip"
        path = self._write_sentinel(
            task_id, ops=[{"op": "ls", "target": "-la"}]
        )
        try:
            # Pretool: structural match succeeds for matching op+target.
            m = match_sentinel_grant_for_bash_command(task_id, "ls -la /tmp")
            self.assertIsNotNone(m)
            self.assertEqual(m.get("op"), "ls")
            # Posttool: consume on terminal_result='success' unlinks.
            self.assertTrue(consume_sentinel_grant_on_terminal_result(task_id, "success"))
            self.assertFalse(os.path.exists(path))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_sentinel_predicate_never_substring_matches_command_line(self):
        """AC2 invariant: predicate never substring-matches against the raw
        command line. A literal 'rm -rf' in the command must NOT trigger
        a match for an unrelated 'ls' op grant.
        """
        task_id = "test-sentinel-no-substring-match"
        path = self._write_sentinel(task_id, ops=[{"op": "ls"}])
        try:
            # Command mentions 'ls' inside an unrelated string — structural
            # match would still succeed because the first sub-token IS 'ls'.
            # The real invariant test: a malicious command whose head op
            # differs must NOT match even if it contains 'ls' as substring.
            self.assertIsNone(
                match_sentinel_grant_for_bash_command(task_id, "rm -rf /; echo ls")
            )
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_expired_grant_treated_as_missing(self):
        """expires_at in the past → load_sentinel_grant_for_task returns None
        (deny-by-default). Reap should remove it."""
        task_id = "test-sentinel-expired"
        path = os.path.join(SENTINEL_GRANT_DIR, f"{task_id}.json")
        now = time.time()
        with open(path, "w") as f:
            json.dump({
                "task_id": task_id,
                "session_id": "x",
                "allowed_operations": [{"op": "ls"}],
                "created_at": now - 600,
                "expires_at": now - 300,
            }, f)
        try:
            self.assertIsNone(load_sentinel_grant_for_task(task_id))
            count = reap_expired_sentinel_grants()
            self.assertGreaterEqual(count, 1)
            self.assertFalse(os.path.exists(path))
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestMatchSentinelGrantForWrite(unittest.TestCase):
    """Tests for match_sentinel_grant_for_write (task 20260522-080646-B / AC1).

    Covers the four canonical cases: match, session mismatch, target mismatch,
    and expired sentinel.
    """

    def setUp(self):
        os.makedirs(SENTINEL_GRANT_DIR, exist_ok=True)

    def _write_sentinel(self, task_id, session_id, ops, ttl=300):
        path = os.path.join(SENTINEL_GRANT_DIR, f"{task_id}.json")
        now = time.time()
        grant = {
            "task_id": task_id,
            "session_id": session_id,
            "allowed_operations": ops,
            "created_at": now,
            "expires_at": now + ttl,
        }
        with open(path, "w") as f:
            json.dump(grant, f)
        return path

    def test_match_returns_entry(self):
        """Session and target both match — returns the matched entry dict."""
        task_id = "test-write-match"
        session_id = "test-session-w1"
        target = "/tmp/test-match-target.json"
        path = self._write_sentinel(task_id, session_id, [{"op": "Write", "target": target}])
        try:
            result = match_sentinel_grant_for_write(task_id, session_id, target)
            self.assertIsNotNone(result)
            self.assertEqual(result.get("op"), "Write")
            self.assertEqual(result.get("target"), target)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_session_mismatch_returns_none(self):
        """Wrong session_id — returns None regardless of target."""
        task_id = "test-write-session-mismatch"
        session_id = "correct-session"
        target = "/tmp/test-session-mismatch.json"
        path = self._write_sentinel(task_id, session_id, [{"op": "Write", "target": target}])
        try:
            result = match_sentinel_grant_for_write(task_id, "wrong-session", target)
            self.assertIsNone(result)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_target_mismatch_returns_none(self):
        """Correct session but wrong target path — returns None."""
        task_id = "test-write-target-mismatch"
        session_id = "test-session-w3"
        target = "/tmp/correct-target.json"
        path = self._write_sentinel(task_id, session_id, [{"op": "Write", "target": target}])
        try:
            result = match_sentinel_grant_for_write(task_id, session_id, "/tmp/other-target.json")
            self.assertIsNone(result)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_expired_sentinel_returns_none(self):
        """Expired sentinel (expires_at in the past) — load returns None."""
        task_id = "test-write-expired"
        session_id = "test-session-w4"
        target = "/tmp/test-expired-target.json"
        path = os.path.join(SENTINEL_GRANT_DIR, f"{task_id}.json")
        now = time.time()
        with open(path, "w") as f:
            json.dump({
                "task_id": task_id,
                "session_id": session_id,
                "allowed_operations": [{"op": "Write", "target": target}],
                "created_at": now - 600,
                "expires_at": now - 300,
            }, f)
        try:
            result = match_sentinel_grant_for_write(task_id, session_id, target)
            self.assertIsNone(result)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_op_mismatch_returns_none(self):
        """Grant has op='ls' not 'Write' — returns None even on target match."""
        task_id = "test-write-op-mismatch"
        session_id = "test-session-w5"
        target = "/tmp/test-op-mismatch.json"
        path = self._write_sentinel(task_id, session_id, [{"op": "ls", "target": target}])
        try:
            result = match_sentinel_grant_for_write(task_id, session_id, target)
            self.assertIsNone(result)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_targetless_wildcard_matches_any_path(self):
        """Sentinel with no 'target' field acts as wildcard — matches any write target.

        Root cause (task 20260522-080646-B): entry_target is None (absent key) and
        None == target_path evaluated False, causing CF-1 denial for all targetless
        grants. Fix at allowlist.py:521-523: entry_target is None or entry_target ==
        target_path. This test proves the wildcard path.
        """
        task_id = "test-write-wildcard"
        session_id = "test-session-w6"
        # Sentinel has no 'target' key — targetless grant (wildcard)
        path = self._write_sentinel(task_id, session_id, [{"op": "Write"}])
        try:
            result = match_sentinel_grant_for_write(task_id, session_id, "/any/path/file.py")
            self.assertIsNotNone(result)
            self.assertEqual(result.get("op"), "Write")
            self.assertNotIn("target", result)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    # ── AC4: legacy args_contain sentinel — exact equality denies other path ──

    def test_ac4_legacy_args_contain_denies_other_path(self):
        """AC4: Legacy broken-schema sentinel {op:Write, args_contain:[/specific/path]}
        must return None for a different path (exact equality, no substring).

        Regression for task 20260524-125300-B ORIGINAL bug: old writer emitted
        args_contain instead of target; matcher must enforce exact equality for
        this legacy shape.
        """
        task_id = "test-ac4-args-contain-deny"
        session_id = "test-session-ac4"
        path = self._write_sentinel(task_id, session_id,
                                    [{"op": "Write", "args_contain": ["/specific/path"]}])
        try:
            result = match_sentinel_grant_for_write(task_id, session_id, "/other/path")
            self.assertIsNone(result)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    # ── AC5: exploit-shape regression — no wildcard leakage from args_contain ──

    def test_ac5_exploit_shape_regression_no_wildcard_leakage(self):
        """AC5: Legacy args_contain sentinel allows exact path, denies others including
        prefix-suffix paths. Prevents privilege escalation via substring matching.

        Tests three sub-cases: (a) exact match → non-None, (b) different path → None,
        (c) path-suffix → None (substring must not match).
        """
        task_id = "test-ac5-exploit-shape"
        session_id = "test-session-ac5"
        path = self._write_sentinel(task_id, session_id,
                                    [{"op": "Write", "args_contain": ["/specific/path"]}])
        try:
            # (a) exact match allows
            result_a = match_sentinel_grant_for_write(task_id, session_id, "/specific/path")
            self.assertIsNotNone(result_a)
            # (b) different path denies
            result_b = match_sentinel_grant_for_write(task_id, session_id, "/other/path")
            self.assertIsNone(result_b)
            # (c) path-suffix denies — no prefix substring matching
            result_c = match_sentinel_grant_for_write(task_id, session_id, "/specific/path-suffix")
            self.assertIsNone(result_c)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    # ── AC6: bare /allow Write sentinel preserves wildcard behavior ──

    def test_ac6_bare_write_sentinel_wildcard_preserved(self):
        """AC6 (non-regression): Bare {op:Write} sentinel (no target, no args_contain)
        still matches any file path — intentional wildcard shape is preserved.
        """
        task_id = "test-ac6-bare-wildcard"
        session_id = "test-session-ac6"
        path = self._write_sentinel(task_id, session_id, [{"op": "Write"}])
        try:
            result = match_sentinel_grant_for_write(task_id, session_id, "/any/file.py")
            self.assertIsNotNone(result)
            self.assertEqual(result.get("op"), "Write")
        finally:
            if os.path.exists(path):
                os.unlink(path)

    # ── AC7: end-to-end — /allow --tool "Write /tmp/file.json" writes scoped sentinel ──

    def test_ac7_e2e_tool_flag_dotted_path_sentinel(self):
        """AC7: Full stack test — userprompt-consent-allowlist.sh invoked via subprocess
        with /allow --tool "Write /tmp/file.json" produces a sentinel with
        target=/tmp/file.json (not args_contain, not missing).

        Verifies CRITICAL-2 fix (is_regex=False for --tool) and ORIGINAL fix (target field).
        Then verifies the matcher allows the named file and denies others.
        """
        task_id = "test-ac7-e2e-tool-dotted"
        session_id = "test-session-ac7"
        sentinel_path = os.path.join(SENTINEL_GRANT_DIR, f"{task_id}.json")
        legacy_path = f"/tmp/claude-bash-allowlist-{session_id}.json"
        # Clean up any leftover from a previous run
        for p in (sentinel_path, legacy_path):
            if os.path.exists(p):
                os.unlink(p)

        hook = os.path.join(HOOKS_DIR, "userprompt-consent-allowlist.sh")
        payload = json.dumps({
            "prompt": '/allow --tool "Write /tmp/file.json"',
            "session_id": session_id,
        })
        env = dict(os.environ)
        env["CLAUDE_TASK_ID"] = task_id
        try:
            result = subprocess.run(
                ["bash", hook],
                input=payload,
                capture_output=True,
                text=True,
                env=env,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0,
                             f"Hook exited non-zero: {result.stderr}")
            # Sentinel must exist
            self.assertTrue(os.path.exists(sentinel_path),
                            f"Sentinel file missing: {sentinel_path}\nhook stdout: {result.stdout}")
            with open(sentinel_path) as f:
                grant = json.load(f)
            ops = grant.get("allowed_operations", [])
            self.assertEqual(len(ops), 1, f"Expected 1 op entry, got: {ops}")
            entry = ops[0]
            self.assertEqual(entry.get("op"), "Write")
            self.assertEqual(entry.get("target"), "/tmp/file.json",
                             f"Expected target=/tmp/file.json, got entry={entry}")
            self.assertNotIn("args_contain", entry,
                             f"args_contain must not be present: {entry}")
            # Matcher allow/deny
            allow_result = match_sentinel_grant_for_write(task_id, session_id, "/tmp/file.json")
            self.assertIsNotNone(allow_result,
                                 "Matcher should allow /tmp/file.json but returned None")
            # Reload sentinel (matcher consumed it? No — matcher is read-only)
            # Re-write for the deny check since matcher is non-destructive
            deny_result = match_sentinel_grant_for_write(task_id, session_id, "/tmp/other.json")
            self.assertIsNone(deny_result,
                              "Matcher should deny /tmp/other.json but returned non-None")
        finally:
            for p in (sentinel_path, legacy_path):
                if os.path.exists(p):
                    os.unlink(p)

    # ── AC8: end-to-end — bare /allow Write /tmp/file.json writes scoped sentinel ──

    def test_ac8_e2e_bare_syntax_scoped_sentinel(self):
        """AC8: Full stack test — userprompt-consent-allowlist.sh invoked via subprocess
        with bare /allow Write /tmp/file.json produces a sentinel with target=/tmp/file.json
        (not a bare wildcard {op:Write}).

        Verifies CRITICAL-1 fix (bare Write /path treated as path, not comment).
        Then verifies the matcher allows the named file and denies others.
        """
        task_id = "test-ac8-e2e-bare-syntax"
        session_id = "test-session-ac8"
        sentinel_path = os.path.join(SENTINEL_GRANT_DIR, f"{task_id}.json")
        legacy_path = f"/tmp/claude-bash-allowlist-{session_id}.json"
        for p in (sentinel_path, legacy_path):
            if os.path.exists(p):
                os.unlink(p)

        hook = os.path.join(HOOKS_DIR, "userprompt-consent-allowlist.sh")
        payload = json.dumps({
            "prompt": "/allow Write /tmp/file.json",
            "session_id": session_id,
        })
        env = dict(os.environ)
        env["CLAUDE_TASK_ID"] = task_id
        try:
            result = subprocess.run(
                ["bash", hook],
                input=payload,
                capture_output=True,
                text=True,
                env=env,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0,
                             f"Hook exited non-zero: {result.stderr}")
            self.assertTrue(os.path.exists(sentinel_path),
                            f"Sentinel file missing: {sentinel_path}\nhook stdout: {result.stdout}")
            with open(sentinel_path) as f:
                grant = json.load(f)
            ops = grant.get("allowed_operations", [])
            self.assertEqual(len(ops), 1, f"Expected 1 op entry, got: {ops}")
            entry = ops[0]
            self.assertEqual(entry.get("op"), "Write")
            self.assertEqual(entry.get("target"), "/tmp/file.json",
                             f"Expected target=/tmp/file.json, got entry={entry}")
            self.assertNotIn("args_contain", entry,
                             f"args_contain must not be present: {entry}")
            # Sentinel must not be bare wildcard — 'target' key required
            self.assertIn("target", entry, "Entry must have 'target' key (not bare wildcard)")
            # Matcher allow/deny
            allow_result = match_sentinel_grant_for_write(task_id, session_id, "/tmp/file.json")
            self.assertIsNotNone(allow_result,
                                 "Matcher should allow /tmp/file.json but returned None")
            deny_result = match_sentinel_grant_for_write(task_id, session_id, "/tmp/other.json")
            self.assertIsNone(deny_result,
                              "Matcher should deny /tmp/other.json but returned non-None")
        finally:
            for p in (sentinel_path, legacy_path):
                if os.path.exists(p):
                    os.unlink(p)


class TestArgumentLessAllowUnrestrictedGrant(unittest.TestCase):
    """The argument-less `/allow` form is the owner-authorized match-all grant.

    Owner directive (2026-09-26): "allow with no remark means allow everything
    ... but only once". Commit e713beff had removed the match-all grant; the
    owner reversed that specific decision. These tests pin the reinstated
    behaviour AND the properties that must survive it: single-use consumption,
    the human-only firewall, and the refusal of every EXPLICIT universal
    selector (an explicit selector must never decay into match-all).
    """

    HOOK = os.path.join(HOOKS_DIR, "userprompt-consent-allowlist.sh")
    PRETOOL = os.path.join(HOOKS_DIR, "pretool-bash-safety.sh")
    POSTTOOL = os.path.join(HOOKS_DIR, "posttool-allowlist-consume.py")

    def setUp(self):
        # Unique ids per test so no probe ever needs a pre-run deletion.
        self.nonce = f"{os.getpid()}-{int(time.time() * 1000)}"
        self.paths = []

    def tearDown(self):
        for path in self.paths:
            if os.path.exists(path):
                os.unlink(path)

    def _track(self, task_id, session_id):
        sentinel = os.path.join(SENTINEL_GRANT_DIR, f"{task_id}.json")
        legacy = f"/tmp/claude-bash-allowlist-{session_id}.json"
        self.paths.extend([sentinel, legacy])
        return sentinel, legacy

    def _live_env(self, temp, task_id, extra=None):
        """The live environment shape: CLAUDE_CONFIG_DIR names a per-account
        runtime state dir that carries NO interpreter, and CLAUDE_PYTHON_BIN is
        NOT set. The hook must still resolve its interpreter structurally."""
        config_dir = Path(temp) / "account-state"
        project_dir = Path(temp) / "project"
        config_dir.mkdir()
        project_dir.mkdir()
        (config_dir / "settings.json").write_text(
            json.dumps({"permissions": {"deny": []}}), encoding="utf-8"
        )
        env = dict(os.environ)
        env["CLAUDE_TASK_ID"] = task_id
        env["CLAUDE_CONFIG_DIR"] = str(config_dir)
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
        env.pop("CLAUDE_PYTHON_BIN", None)
        env.update(extra or {})
        return env

    def _consent(self, payload, env):
        return subprocess.run(
            ["bash", self.HOOK], input=json.dumps(payload), capture_output=True,
            text=True, env=env, timeout=10,
        )

    # ── (a) argument-less form records the grant on BOTH channels ──

    def test_argument_less_allow_records_match_all_grant_on_both_channels(self):
        task_id = f"test-allow-matchall-a-{self.nonce}"
        session_id = task_id
        sentinel, legacy = self._track(task_id, session_id)
        self.assertFalse(os.path.exists(sentinel))
        self.assertFalse(os.path.exists(legacy))

        consent_log = Path(os.environ.get("HOME", "/root")) / ".claude" / "logs" / "bash-consent.log"
        log_offset = consent_log.stat().st_size if consent_log.exists() else 0

        with tempfile.TemporaryDirectory() as temp:
            env = self._live_env(temp, task_id)
            result = self._consent(
                {"prompt": "/allow", "session_id": session_id}, env
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("configured Python interpreter is unavailable", result.stderr)
        self.assertNotIn("ERROR: refused", result.stderr)
        self.assertIn("Grant recorded", result.stdout)
        self.assertIn("UNRESTRICTED grant", result.stdout)

        # Legacy channel: the representation the legacy matcher already
        # understands for an unrestricted entry.
        self.assertTrue(os.path.exists(legacy), result.stdout + result.stderr)
        with open(legacy) as fh:
            flag = json.load(fh)
        self.assertEqual(flag, {"pattern": ".*", "is_regex": True})

        # Sentinel channel: op="*" regex entry — the existing schema, no new
        # channel, no new grant shape.
        self.assertTrue(os.path.exists(sentinel))
        with open(sentinel) as fh:
            grant = json.load(fh)
        self.assertEqual(grant["allowed_operations"], [{"op": "*", "regex": ".*"}])
        self.assertEqual(grant["session_id"], session_id)
        self.assertEqual(grant["task_id"], task_id)
        # TTL must still bound the grant (requirement 2).
        self.assertGreater(grant["expires_at"], grant["created_at"])
        self.assertLessEqual(grant["expires_at"] - grant["created_at"], 300)

        # The grant really is unrestricted for the structural matcher.
        self.assertIsNotNone(
            match_sentinel_grant_for_bash_command(task_id, "git stash")
        )
        self.assertIsNotNone(
            match_sentinel_grant_for_bash_command(task_id, "echo anything-at-all")
        )

        # (requirement 5) the match-all bypass is distinguishable in the audit log.
        if consent_log.exists():
            # Slice by BYTES: the log carries multibyte comments, so a
            # character-offset slice would silently read past the end.
            appended = consent_log.read_bytes()[log_offset:].decode(
                "utf-8", errors="replace"
            )
            self.assertIn("GRANTED_MATCH_ALL", appended)
            self.assertIn("scope=unrestricted", appended)
            self.assertIn(f"sid={session_id}", appended)

    # ── (b) end-to-end: blocked command permitted ONCE, then blocked again ──

    def test_match_all_grant_permits_blocked_command_exactly_once(self):
        task_id = f"test-allow-matchall-b-{self.nonce}"
        session_id = task_id
        sentinel, legacy = self._track(task_id, session_id)
        # Bare `git stash` is genuinely blocked by pretool-bash-safety.sh and is
        # never executed here — only the hook is invoked.
        command = "git stash"
        pretool_payload = json.dumps({
            "session_id": session_id,
            "tool_name": "Bash",
            "tool_input": {"command": command},
        })
        env = dict(os.environ)
        env["CLAUDE_TASK_ID"] = task_id

        def run_pretool():
            return subprocess.run(
                ["bash", self.PRETOOL], input=pretool_payload, capture_output=True,
                text=True, env=env, timeout=20,
            )

        # 1. No grant -> blocked.
        before = run_pretool()
        self.assertEqual(before.returncode, 2, before.stdout + before.stderr)
        self.assertIn("BLOCKED", before.stderr)

        # 2. Argument-less /allow.
        with tempfile.TemporaryDirectory() as temp:
            consent = self._consent(
                {"prompt": "/allow", "session_id": session_id},
                self._live_env(temp, task_id),
            )
        self.assertEqual(consent.returncode, 0, consent.stderr)
        self.assertTrue(os.path.exists(sentinel))
        self.assertTrue(os.path.exists(legacy))

        # 3. Same command is now permitted.
        granted = run_pretool()
        self.assertEqual(granted.returncode, 0, granted.stdout + granted.stderr)
        self.assertIn("permissionDecision", granted.stdout)
        self.assertIn("allow", granted.stdout)
        self.assertNotIn("BLOCKED", granted.stderr)

        # 4. PostToolUse terminal result consumes the grant on BOTH channels.
        consumed = subprocess.run(
            [sys.executable, self.POSTTOOL],
            input=json.dumps({
                "session_id": session_id,
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "tool_response": {"stdout": "", "stderr": ""},
            }),
            capture_output=True, text=True, env=env, timeout=20, cwd=HOOKS_DIR,
        )
        self.assertEqual(consumed.returncode, 0, consumed.stderr)
        self.assertFalse(os.path.exists(sentinel), "sentinel survived consumption")
        self.assertFalse(os.path.exists(legacy), "legacy flag survived consumption")

        # 5. Second equivalent attempt is blocked again — single-use holds.
        after = run_pretool()
        self.assertEqual(after.returncode, 2, after.stdout + after.stderr)
        self.assertIn("BLOCKED", after.stderr)

    # ── (c) the human-only property survives ──

    def test_argument_less_allow_from_subagent_writes_nothing(self):
        task_id = f"test-allow-matchall-c-{self.nonce}"
        session_id = task_id
        sentinel, legacy = self._track(task_id, session_id)
        with tempfile.TemporaryDirectory() as temp:
            result = self._consent(
                {
                    "prompt": "/allow",
                    "session_id": session_id,
                    "agent_id": "agent-subagent-probe",
                },
                self._live_env(temp, task_id),
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")
        self.assertFalse(os.path.exists(sentinel),
                         "subagent minted a sentinel match-all grant")
        self.assertFalse(os.path.exists(legacy),
                         "subagent minted a legacy match-all grant")

    # ── explicit selectors keep refusing: no decay into match-all ──

    def test_explicit_universal_selectors_still_refuse_after_reinstatement(self):
        selectors = (
            "re:.*", ".*", "^", "re:", "--tool", "re:git", r"re:[\s\S]*",
            "删冗余文件", "re:^(a+)+$",
        )
        for index, selector in enumerate(selectors):
            with self.subTest(selector=selector), tempfile.TemporaryDirectory() as temp:
                task_id = f"test-allow-matchall-refuse-{index}-{self.nonce}"
                session_id = task_id
                sentinel, legacy = self._track(task_id, session_id)
                result = self._consent(
                    {"prompt": f"/allow {selector}", "session_id": session_id},
                    self._live_env(temp, task_id),
                )
                self.assertEqual(result.returncode, 0)
                self.assertNotIn("Grant recorded", result.stdout)
                self.assertNotIn("UNRESTRICTED grant", result.stdout)
                self.assertFalse(os.path.exists(sentinel),
                                 f"{selector} wrote a sentinel grant")
                self.assertFalse(os.path.exists(legacy),
                                 f"{selector} wrote a legacy grant")


class TestCorruptedGrantFailClosedOnReadPath(unittest.TestCase):
    """A corrupted grant file is NO-GRANT-AT-ALL on the enforcement READ path.

    The suite already pins malformed-grant handling on the consume/reap path
    (TestSentinelGrantLifecycle.test_terminal_consume_malformed) and a
    malformed settings SOURCE (test_malformed_participating_source_fails_closed).
    This class pins the remaining leg: the ENFORCEMENT READ PATH. For every
    corruption shape, on BOTH grant channels (legacy per-session flag file +
    structured sentinel under SENTINEL_GRANT_DIR):

      1. the grant readers in lib/allowlist.py report no-match and never raise;
      2. pretool-bash-safety.sh still BLOCKS (exit 2) a command it genuinely
         blocks — bare `git stash` — while the corrupted grant is the only
         grant present. The command exists only as payload text on the hook's
         stdin; it is never executed;
      3. the read path is READ-ONLY: the corrupted file survives untouched
         (deletion belongs exclusively to the consume/reap path).

    Each hook-boundary test opens with a positive control (a VALID grant on
    the identical harness shape is honored, rc 0 + canonical approval JSON),
    so the per-shape rc-2 results are attributable to the corruption being
    treated as no-grant — not to a harness misconfiguration that blocks
    everything unconditionally.
    """

    PRETOOL = os.path.join(HOOKS_DIR, "pretool-bash-safety.sh")

    def setUp(self):
        os.makedirs(SENTINEL_GRANT_DIR, exist_ok=True)
        # Unique ids per test run; per-shape ids derive from this nonce so no
        # probe ever needs a pre-run deletion.
        self.nonce = f"{os.getpid()}-{int(time.time() * 1000)}"
        self.paths = []

    def tearDown(self):
        # Removes exactly the files this test created (grant files written
        # here, plus the .lock sidecar the legacy matcher creates as a direct
        # consequence of this test's own invocation).
        for path in self.paths:
            if os.path.exists(path):
                os.unlink(path)

    def _track(self, *paths):
        self.paths.extend(paths)

    # ── corruption corpora ────────────────────────────────────────────────

    @staticmethod
    def _legacy_corruption_shapes():
        """Corruption shapes for /tmp/claude-bash-allowlist-<sid>.json
        (expected well-formed shape: {"pattern": str, "is_regex": bool})."""
        return (
            ("invalid_json_bytes", "{not valid json"),
            ("empty_file", ""),
            ("json_array_not_object", '["git stash"]'),
            ("bare_string_not_object", '"git stash"'),
            ("object_missing_pattern_field", '{"is_regex": false}'),
            ("pattern_field_wrong_type", '{"pattern": 123, "is_regex": false}'),
        )

    _SENTINEL_SHAPE_NAMES = (
        "invalid_json_bytes",
        "empty_file",
        "json_array_not_object",
        "bare_string_not_object",
        "object_missing_allowed_operations",
        "unexpired_but_operations_not_a_list",
        "match_all_truncated_mid_write",
    )

    @staticmethod
    def _sentinel_corruption_body(name, task_id, session_id):
        """Corruption shapes for SENTINEL_GRANT_DIR/<task_id>.json."""
        now = time.time()
        bodies = {
            "invalid_json_bytes": "{not valid json",
            "empty_file": "",
            "json_array_not_object": '[{"op": "*", "regex": ".*"}]',
            "bare_string_not_object": '"allow everything"',
            # Required keys otherwise valid, timestamps unexpired, but the
            # operations list is absent entirely.
            "object_missing_allowed_operations": json.dumps({
                "task_id": task_id, "session_id": session_id,
                "created_at": now, "expires_at": now + 300,
            }),
            # The loader distinguishes this combination: every required key
            # present and expires_at genuinely in the future, but
            # allowed_operations is not a list — still no-grant.
            "unexpired_but_operations_not_a_list": json.dumps({
                "task_id": task_id, "session_id": session_id,
                "allowed_operations": "*",
                "created_at": now, "expires_at": now + 300,
            }),
            # The unrestricted match-all sentinel (op="*" regex=".*", the
            # argument-less /allow shape) cut mid-write: byte-truncated
            # inside the expires_at key.
            "match_all_truncated_mid_write": (
                '{"task_id": "%s", "session_id": "%s", '
                '"allowed_operations": [{"op": "*", "regex": ".*"}], '
                '"created_at": %f, "expires_' % (task_id, session_id, now)
            ),
        }
        return bodies[name]

    def _run_pretool(self, session_id, task_id):
        payload = json.dumps({
            "session_id": session_id,
            "tool_name": "Bash",
            "tool_input": {"command": "git stash"},
        })
        env = dict(os.environ)
        env["CLAUDE_TASK_ID"] = task_id
        return subprocess.run(
            ["bash", self.PRETOOL], input=payload, capture_output=True,
            text=True, env=env, timeout=20,
        )

    # ── (1) reader level: no-match, no exception, no unlink ──────────────

    def test_corrupted_legacy_flag_readers_report_no_match_and_never_raise(self):
        for index, (name, body) in enumerate(self._legacy_corruption_shapes()):
            with self.subTest(shape=name):
                sid = f"test-corrupt-legacy-lib-{index}-{self.nonce}"
                flag = f"/tmp/claude-bash-allowlist-{sid}.json"
                self._track(flag, flag + ".lock")
                with open(flag, "w") as f:
                    f.write(body)
                # Every legacy reader reports no-match; a raised exception
                # would escape into the calling hook and fail this test.
                self.assertFalse(read_grant("Write", sid))
                self.assertFalse(read_grant_for_git_command("git stash", sid))
                self.assertIsNone(match_grant_for_bash_command("git stash", sid))
                # Read path never unlinks — even a corrupted grant.
                self.assertTrue(os.path.exists(flag),
                                f"reader unlinked corrupted grant ({name})")

    def test_corrupted_sentinel_readers_report_no_match_and_never_raise(self):
        for index, name in enumerate(self._SENTINEL_SHAPE_NAMES):
            with self.subTest(shape=name):
                task_id = f"test-corrupt-sentinel-lib-{index}-{self.nonce}"
                session_id = task_id
                path = os.path.join(SENTINEL_GRANT_DIR, f"{task_id}.json")
                self._track(path)
                with open(path, "w") as f:
                    f.write(self._sentinel_corruption_body(name, task_id, session_id))
                self.assertIsNone(load_sentinel_grant_for_task(task_id))
                self.assertIsNone(
                    match_sentinel_grant_for_bash_command(task_id, "git stash")
                )
                self.assertIsNone(
                    match_sentinel_grant_for_write(task_id, session_id, "/tmp/x")
                )
                self.assertTrue(os.path.exists(path),
                                f"reader unlinked corrupted sentinel ({name})")

    # ── (2) hook boundary: enforcement keeps blocking ─────────────────────

    def test_pretool_still_blocks_when_corrupted_legacy_flag_is_only_grant(self):
        # Positive control: a VALID legacy grant on this exact harness shape
        # is honored (unlink deferred to PostToolUse, so teardown reaps it).
        control_sid = f"test-corrupt-legacy-hook-control-{self.nonce}"
        control_flag = f"/tmp/claude-bash-allowlist-{control_sid}.json"
        self._track(control_flag, control_flag + ".lock")
        with open(control_flag, "w") as f:
            json.dump({"pattern": "git stash", "is_regex": False}, f)
        control = self._run_pretool(control_sid, control_sid)
        self.assertEqual(control.returncode, 0, control.stdout + control.stderr)
        self.assertIn("permissionDecision", control.stdout)

        for index, (name, body) in enumerate(self._legacy_corruption_shapes()):
            with self.subTest(shape=name):
                sid = f"test-corrupt-legacy-hook-{index}-{self.nonce}"
                flag = f"/tmp/claude-bash-allowlist-{sid}.json"
                self._track(flag, flag + ".lock")
                with open(flag, "w") as f:
                    f.write(body)
                result = self._run_pretool(sid, sid)
                self.assertEqual(result.returncode, 2,
                                 f"{name}: {result.stdout}{result.stderr}")
                self.assertIn("BLOCKED", result.stderr)
                self.assertNotIn("permissionDecision", result.stdout)
                self.assertTrue(os.path.exists(flag),
                                f"hook unlinked corrupted grant ({name})")

    def test_pretool_still_blocks_when_corrupted_sentinel_is_only_grant(self):
        # Positive control: a VALID unrestricted sentinel on this exact
        # harness shape is honored (consume deferred to PostToolUse).
        control_task = f"test-corrupt-sentinel-hook-control-{self.nonce}"
        control_path = os.path.join(SENTINEL_GRANT_DIR, f"{control_task}.json")
        self._track(control_path)
        now = time.time()
        with open(control_path, "w") as f:
            json.dump({
                "task_id": control_task, "session_id": control_task,
                "allowed_operations": [{"op": "*", "regex": ".*"}],
                "created_at": now, "expires_at": now + 300,
            }, f)
        control = self._run_pretool(control_task, control_task)
        self.assertEqual(control.returncode, 0, control.stdout + control.stderr)
        self.assertIn("permissionDecision", control.stdout)

        for index, name in enumerate(self._SENTINEL_SHAPE_NAMES):
            with self.subTest(shape=name):
                task_id = f"test-corrupt-sentinel-hook-{index}-{self.nonce}"
                session_id = task_id
                path = os.path.join(SENTINEL_GRANT_DIR, f"{task_id}.json")
                self._track(path)
                with open(path, "w") as f:
                    f.write(self._sentinel_corruption_body(name, task_id, session_id))
                result = self._run_pretool(session_id, task_id)
                self.assertEqual(result.returncode, 2,
                                 f"{name}: {result.stdout}{result.stderr}")
                self.assertIn("BLOCKED", result.stderr)
                self.assertNotIn("permissionDecision", result.stdout)
                self.assertTrue(os.path.exists(path),
                                f"hook unlinked corrupted sentinel ({name})")


if __name__ == "__main__":
    unittest.main()
