"""Tests for git-global-option normalization in the sentinel grant matcher.

Regression cover for task 20260928-133915: `/allow git commit` could never match
the canonical `git -C <dir> commit -F <msgfile>` shape this repo emits, because
args_contain is a POSITIONAL PREFIX anchored immediately after the head token and
the real command's first argument is `-C`, not the subcommand.

The fix adds a second match view with repo-retargeting global options removed.
The security boundary under test: options carrying a code-execution vector
(-c, --config-env, --exec-path) are NEVER skipped, so a command bearing one
fails closed against a shorter grant.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

HOOKS_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, HOOKS_DIR)

from lib.allowlist import (  # noqa: E402
    _strip_git_global_opts,
    match_sentinel_grant_for_bash_command,
)

GIT = "git"
VERB = "commit"
TASK = "t-selftest"


def derive(pattern):
    """Mirror of the literal branch in userprompt-consent-allowlist.sh:726-737."""
    parts = pattern.split(None, 1)
    op = parts[0] if parts else pattern
    rest = parts[1] if len(parts) >= 2 else ""
    entry = {"op": op}
    if op == "Write" and rest:
        entry["target"] = rest
    elif rest:
        entry["args_contain"] = rest.split()
    return entry


def match(grant_pattern, command):
    """Match `command` against the sentinel a literal /allow would have written."""
    grant = {"allowed_operations": [derive(grant_pattern)]}
    with patch("lib.allowlist.load_sentinel_grant_for_task", return_value=grant):
        return match_sentinel_grant_for_bash_command(TASK, command)


class TestStripGitGlobalOpts(unittest.TestCase):
    def test_separated_value_option_skipped(self):
        self.assertEqual(_strip_git_global_opts(["-C", "/p", VERB]), [VERB])

    def test_attached_value_option_skipped(self):
        self.assertEqual(_strip_git_global_opts(["--git-dir=/p", VERB]), [VERB])

    def test_attached_dash_C_form_is_not_skipped(self):
        # `-C/p` (attached, no `=`) is not real git syntax for `-C` (git
        # itself rejects it: "unknown option: -C/p"), so it must NOT be
        # treated as a skippable global option. Only the separated `-C <dir>`
        # form (see test_separated_value_option_skipped) is valid.
        self.assertEqual(_strip_git_global_opts(["-C/p", VERB]), ["-C/p", VERB])

    def test_valueless_flag_skipped(self):
        self.assertEqual(_strip_git_global_opts(["--no-pager", VERB]), [VERB])

    def test_stacked_options_skipped(self):
        self.assertEqual(
            _strip_git_global_opts(["-C", "/p", "--no-pager", "--work-tree=/w", VERB]),
            [VERB],
        )

    def test_dangling_option_does_not_run_off_end(self):
        self.assertEqual(_strip_git_global_opts(["-C"]), ["-C"])

    def test_bare_dash_C_not_treated_as_attached(self):
        # `-C` with no value is malformed, not an attached `-C<dir>`.
        self.assertEqual(_strip_git_global_opts(["-C"]), ["-C"])

    def test_exec_vector_options_are_not_skipped(self):
        for opt in (["-c", "core.pager=x"], ["--config-env=core.pager=X"],
                    ["--exec-path=/tmp/evil"], ["--super-prefix", "s"]):
            with self.subTest(opt=opt):
                self.assertEqual(_strip_git_global_opts(opt + [VERB]), opt + [VERB])

    def test_unknown_option_stops_the_skip(self):
        self.assertEqual(
            _strip_git_global_opts(["--totally-unknown", VERB]),
            ["--totally-unknown", VERB],
        )


class TestShortGrantReachesCanonicalShape(unittest.TestCase):
    """The bug this task fixes."""

    def test_short_grant_matches_dash_C_form(self):
        self.assertIsNotNone(
            match(f"{GIT} {VERB}", f"{GIT} -C /path {VERB} -F /tmp/m")
        )

    def test_attached_dash_C_form_does_not_match_short_grant(self):
        # `-C/path` (attached, no `=`) is not real git syntax for `-C` — git
        # itself rejects it ("unknown option: -C/path") — so it must NOT be
        # treated as a skippable global option. The separated form is already
        # covered by test_short_grant_matches_dash_C_form above.
        self.assertIsNone(match(f"{GIT} {VERB}", f"{GIT} -C/path {VERB} -F /tmp/m"))

    def test_short_grant_matches_git_dir_form(self):
        self.assertIsNotNone(
            match(f"{GIT} {VERB}", f"{GIT} --git-dir=/p/.git {VERB} -F /tmp/m")
        )

    def test_short_grant_still_matches_plain_form(self):
        self.assertIsNotNone(match(f"{GIT} {VERB}", f'{GIT} {VERB} -m "x"'))

    def test_path_qualified_git_head_normalizes_too(self):
        self.assertIsNotNone(
            match(f"/usr/bin/{GIT} {VERB}", f"/usr/bin/{GIT} -C /path {VERB}")
        )


class TestNoRegressionOnExplicitlyPinnedGrants(unittest.TestCase):
    """The verbatim view must survive, so a pinned grant is never widened."""

    def test_full_command_grant_still_matches(self):
        cmd = f"{GIT} -C /path {VERB} -F /tmp/m"
        self.assertIsNotNone(match(cmd, cmd))

    def test_pinned_repo_does_not_match_a_different_repo(self):
        self.assertIsNone(
            match(f"{GIT} --git-dir=/a {VERB}", f"{GIT} --git-dir=/b {VERB}")
        )

    def test_pinned_dash_C_does_not_match_a_different_dir(self):
        self.assertIsNone(match(f"{GIT} -C /a {VERB}", f"{GIT} -C /b {VERB}"))

    def test_wrong_order_still_rejected(self):
        self.assertIsNone(match(f"{GIT} /path {VERB}", f"{GIT} -C /path {VERB}"))

    def test_different_subcommand_still_rejected(self):
        self.assertIsNone(match(f"{GIT} {VERB}", f"{GIT} -C /path push origin main"))


class TestFailClosedOnExecVectorOptions(unittest.TestCase):
    """A short grant must never inherit a command carrying an exec vector."""

    def test_dash_c_config_not_inherited(self):
        self.assertIsNone(
            match(f"{GIT} {VERB}", f"{GIT} -c core.pager=evil {VERB} -F /tmp/m")
        )

    def test_config_env_not_inherited(self):
        self.assertIsNone(
            match(f"{GIT} {VERB}", f"{GIT} --config-env=core.pager=EVIL {VERB}")
        )

    def test_exec_path_not_inherited(self):
        self.assertIsNone(
            match(f"{GIT} {VERB}", f"{GIT} --exec-path=/tmp/evil {VERB}")
        )

    def test_explicit_dash_c_grant_still_matches_itself(self):
        cmd = f"{GIT} -c core.pager=x {VERB}"
        self.assertIsNotNone(match(cmd, cmd))


class TestNonGitHeadUnaffected(unittest.TestCase):
    def test_non_git_head_keeps_verbatim_semantics(self):
        self.assertIsNone(match("zzz save", "zzz -C /path save -F /tmp/m"))
        self.assertIsNotNone(match("zzz -C /path save", "zzz -C /path save -F /tmp/m"))


class TestCompoundGuardStillApplies(unittest.TestCase):
    """Normalization must not weaken the single-subcommand guarantee."""

    def test_chained_command_refused(self):
        self.assertIsNone(
            match(f"{GIT} {VERB}", f"{GIT} -C /path {VERB} -F /tmp/m && echo hi")
        )

    def test_multiline_command_refused(self):
        self.assertIsNone(
            match(f"{GIT} {VERB}", f"{GIT} -C /path {VERB} -F /tmp/m\necho hi")
        )


if __name__ == "__main__":
    unittest.main()
