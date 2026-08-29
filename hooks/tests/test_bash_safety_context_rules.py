"""End-to-end should-block / should-not-block tests for the two Item A rules
converted to COMMAND_CONTEXT_STRIPPED in hooks/pretool-bash-safety.sh.

These drive the real hook process via piped JSON (the Claude Code PreToolUse
protocol) and assert on the hook's exit code:
  - exit 2  => the command is BLOCKED
  - exit 0  => the command is ALLOWED

Converted rules under test (dev-20260529-092512 Item A):
  1. dd|mkfs|fdisk|shred destructive-disk rule  (command-word-anchored)
  2. kill <PID> rule                            (kill is in DANGER_COMMANDS, args exposed)

A rule is only safe to read the stripped view if its match is IDENTICAL
raw-vs-stripped on real dangerous commands (should-block) while quoted/echoed
mentions stop matching (should-not-block). Both polarities are asserted per rule.

Run with: python3 -m pytest hooks/tests/test_bash_safety_context_rules.py -v
"""

import json
import os
import shutil
import subprocess

import pytest

HOOK = os.path.join(os.path.dirname(__file__), "..", "pretool-bash-safety.sh")


def run_hook(command: str, hook: str = HOOK) -> int:
    """Invoke the real hook with a Bash tool_input and return its exit code."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    proc = subprocess.run(
        ["bash", hook],
        input=payload,
        text=True,
        capture_output=True,
    )
    return proc.returncode


BLOCK = 2
ALLOW = 0


# ── Rule 1: dd|mkfs|fdisk|shred (command-word-anchored) ──────────────────────

class TestDestructiveDiskRule:
    """The verb itself is the danger signal; preserved verbatim by the stripper."""

    def test_dd_real_command_is_blocked(self):
        assert run_hook("dd if=/dev/zero of=/dev/sda") == BLOCK

    def test_mkfs_real_command_is_blocked(self):
        assert run_hook("mkfs.ext4 /dev/sda1") == BLOCK

    def test_dd_in_quoted_echo_is_not_blocked(self):
        # echo "dd if=..." -> echo "" after stripping: must NOT false-positive.
        assert run_hook('echo "dd if=/dev/zero of=/dev/sda"') == ALLOW

    def test_mkfs_in_quoted_echo_is_not_blocked(self):
        assert run_hook('echo "mkfs.ext4 /dev/sda1"') == ALLOW


# ── Rule 2: kill <PID> (kill already in DANGER_COMMANDS, args exposed) ───────

class TestKillPidRule:
    """kill's args are unquoted by the stripper, so kill "1234" -> kill 1234."""

    def test_kill_bare_pid_is_blocked(self):
        assert run_hook("kill 1234") == BLOCK

    def test_kill_quoted_pid_is_blocked(self):
        # kill "1234" -> kill 1234 after stripping (DANGER_COMMANDS exposure).
        assert run_hook('kill "1234"') == BLOCK

    def test_kill_pid_in_quoted_echo_is_not_blocked(self):
        # echo "kill 1234" -> echo "" after stripping: must NOT false-positive.
        assert run_hook('echo "kill 1234"') == ALLOW


# ── Execution-aware destructive-reset classification ────────────────────────

class TestGitResetExecutionClassification:
    """The structured view distinguishes executed argv from inert data."""

    @staticmethod
    def _fallback_hook(tmp_path, malformed_classifier=False):
        hook_dir = tmp_path / "hooks"
        (hook_dir / "lib").mkdir(parents=True)
        shutil.copy2(HOOK, hook_dir / "pretool-bash-safety.sh")
        shutil.copy2(
            os.path.join(os.path.dirname(HOOK), "lib", "bash_context_strip.py"),
            hook_dir / "lib" / "bash_context_strip.py",
        )
        # The execution-boundary analyzer is deliberately NOT staged: this
        # fixture exercises the CLASSIFIER fallback with the removal policy in
        # its degraded branch. That branch reads its removal-reference
        # predicate from a shared file (the single definition the AC-R02-10
        # differential test also consumes), so the file has to travel with the
        # hook — an absent predicate is itself a degraded deployment and denies
        # everything, which is asserted separately in
        # test_pol_generative_sweeps.py::test_missing_degraded_predicate_file_denies.
        shutil.copy2(
            os.path.join(os.path.dirname(HOOK), "lib",
                         "pol_degraded_removal_reference.ere"),
            hook_dir / "lib" / "pol_degraded_removal_reference.ere",
        )
        if malformed_classifier:
            classifier = hook_dir / "lib" / "git_command_classifier.py"
            classifier.write_text("print('not-json')\n")
        return str(hook_dir / "pretool-bash-safety.sh")

    @staticmethod
    def _assert_fallback_boundary(hook):
        dangerous = (
            "git reset --hard HEAD~1",
            "/usr/bin/git reset --hard HEAD~1",
        )
        inert = (
            "rg -n 'git reset --hard' docs",
            "rg -n '/usr/bin/git reset --hard' docs",
            "python3 checker.py 'git reset --hard'",
            "python3 checker.py '/usr/bin/git reset --hard'",
            'echo "never run git reset --hard in shared repositories"',
            'echo "never run /usr/bin/git reset --hard in shared repositories"',
        )
        for command in dangerous:
            assert run_hook(command, hook) == BLOCK, command
        for command in inert:
            assert run_hook(command, hook) == ALLOW, command

    def test_git_reset_hard_is_blocked(self):
        assert run_hook("git reset --hard HEAD~1") == BLOCK

    def test_path_qualified_execution_is_blocked(self):
        assert run_hook("/usr/bin/git reset --hard HEAD~1") == BLOCK

    def test_quoted_search_pattern_is_inert(self):
        assert run_hook("rg -n 'git reset --hard' docs") == ALLOW

    def test_python_argument_is_inert(self):
        assert run_hook("python3 checker.py 'git reset --hard'") == ALLOW

    def test_echo_documentation_is_inert(self):
        assert run_hook('echo "never run git reset --hard in shared repositories"') == ALLOW

    def test_missing_classifier_falls_back_closed_for_real_execution(self, tmp_path):
        hook = self._fallback_hook(tmp_path)
        self._assert_fallback_boundary(hook)

    def test_malformed_classifier_falls_back_closed_for_real_execution(self, tmp_path):
        hook = self._fallback_hook(tmp_path, malformed_classifier=True)
        self._assert_fallback_boundary(hook)


# ── Removal policy: historical control sets (LANE-POL, spec-20260808-035658) ──
# Ported verbatim from the iteration-5 worktree's terminal test file
# (overnight-20260809-685c203b, sha256 ad46f54c009b01be411e7eddc404a13578fdc8264
# adef1a5d78b03c8affc39ec). Commands and expected results are byte-identical to
# the source; only the surrounding module differs.
#
# These are the three historical control sets the removal-policy rewrite must
# keep green, in the order they were accumulated:
#   * the original iteration-3 constructive counterexamples
#     (test_structural_command_positions_fail_closed and its inert/safe twin)
#   * the iteration-4 exact-mismatch set: 41 forms that must block plus the one
#     safe `git rm --cached>/dev/null tracked.txt` that must be allowed
#     (test_iteration_five_structural_mismatches_are_blocked)
#   * the iteration-5 representation boundaries
#     (test_iteration_five_representation_boundaries)
# Every one of them is a form some earlier iteration got wrong. They exist to
# make a regression loud, so do not "simplify" a case to make it pass.

class TestCachedGitRmClassification:
    """Every rm occurrence must be a proven cached-Git or Docker removal."""

    def test_cached_index_removal_is_allowed(self):
        assert run_hook("git rm --cached tracked.txt") == ALLOW

    def test_path_qualified_repo_cached_removal_is_allowed(self):
        assert run_hook("/usr/bin/git -C repo rm -r --cached tracked.txt") == ALLOW

    def test_non_cached_git_rm_is_blocked(self):
        assert run_hook("git rm tracked.txt") == BLOCK

    def test_bare_rm_is_blocked(self):
        assert run_hook("rm tracked.txt") == BLOCK

    def test_cached_git_rm_mixed_with_bare_rm_is_blocked(self):
        assert run_hook("git rm --cached tracked.txt; rm other.txt") == BLOCK

    def test_docker_rm_is_allowed(self):
        assert run_hook("docker rm dev-container") == ALLOW

    def test_path_qualified_docker_rm_is_allowed(self):
        assert run_hook("/usr/bin/docker rm dev-container") == ALLOW

    def test_docker_rm_then_bare_rm_is_blocked(self):
        assert run_hook("docker rm dev-container; rm other.txt") == BLOCK

    def test_bare_rm_then_docker_rm_is_blocked(self):
        assert run_hook("rm other.txt; docker rm dev-container") == BLOCK

    def test_docker_rm_then_non_cached_git_rm_is_blocked(self):
        assert run_hook("docker rm dev-container; git rm tracked.txt") == BLOCK

    def test_non_cached_git_rm_then_docker_rm_is_blocked(self):
        assert run_hook("git rm tracked.txt; docker rm dev-container") == BLOCK

    def test_wrapped_docker_rm_then_bare_rm_is_blocked(self):
        assert run_hook('bash -lc "docker rm dev-container; rm other.txt"') == BLOCK

    def test_path_qualified_docker_rm_then_bare_rm_is_blocked(self):
        assert run_hook("/usr/bin/docker rm dev-container; rm other.txt") == BLOCK

    def test_docker_rm_with_cached_git_rm_is_allowed(self):
        assert run_hook("docker rm dev-container; git rm --cached tracked.txt") == ALLOW

    @pytest.mark.parametrize("command", (
        "/bin/rm tracked.txt",
        "/usr/bin/rm tracked.txt",
        "/bin/rm tracked.txt; docker rm dev-container",
        "docker rm dev-container; /bin/rm tracked.txt",
        "git rm --cached tracked.txt; /bin/rm other.txt",
        'bash -lc "/bin/rm tracked.txt"',
        "command /bin/rm tracked.txt",
    ))
    def test_path_qualified_filesystem_rm_is_blocked(self, command):
        assert run_hook(command) == BLOCK

    @pytest.mark.parametrize("malformed", (False, True))
    def test_path_qualified_rm_fails_closed_without_classifier(self, tmp_path, malformed):
        hook = TestGitResetExecutionClassification._fallback_hook(tmp_path, malformed)
        assert run_hook("/bin/rm tracked.txt", hook) == BLOCK

    @pytest.mark.parametrize(("command", "expected"), (
        ("'rm' tracked.txt", BLOCK),
        ('"rm" tracked.txt', BLOCK),
        ("'/bin/rm' tracked.txt", BLOCK),
        ('"/bin/rm" tracked.txt', BLOCK),
        ("command 'rm' tracked.txt", BLOCK),
        ('env FOO=1 "/bin/rm" tracked.txt', BLOCK),
        ('bash -lc "\'/bin/rm\' tracked.txt"', BLOCK),
        ("docker rm dev-container; '/bin/rm' tracked.txt", BLOCK),
        ('"/bin/rm" tracked.txt; docker rm dev-container', BLOCK),
        ("git rm --cached tracked.txt; '/bin/rm' other.txt", BLOCK),
        ("'/usr/bin/git' rm tracked.txt", BLOCK),
        ('"/usr/bin/git" rm tracked.txt', BLOCK),
        ("git 'rm' tracked.txt", BLOCK),
        ('git "rm" tracked.txt', BLOCK),
        ("r''m tracked.txt", BLOCK),
        (r"r\m tracked.txt", BLOCK),
        ("/bin/'rm' tracked.txt", BLOCK),
        ("command r''m tracked.txt", BLOCK),
        (r"env FOO=1 /bin/r\m tracked.txt", BLOCK),
        ("g''it r''m tracked.txt", BLOCK),
        (r"git r\m tracked.txt", BLOCK),
        ('eval "\'/bin/rm\' tracked.txt"', BLOCK),
        ("git 'rm' --cached tracked.txt", ALLOW),
        ('docker "rm" dev-container', ALLOW),
        ('echo "rm tracked.txt"', ALLOW),
        ("printf '%s' '/bin/rm tracked.txt'", ALLOW),
        ('python3 checker.py \'git "rm" tracked.txt\'', ALLOW),
    ))
    def test_shell_quote_and_escape_equivalence(self, command, expected):
        assert run_hook(command) == expected

    @pytest.mark.parametrize("command", (
        "$(printf r)$(printf m) tracked.txt", "r$(printf m) tracked.txt",
        "$(printf r)m tracked.txt", '"$(printf r)$(printf m)" tracked.txt',
        "`printf r``printf m` tracked.txt", 'R=r; M=m; "$R$M" tracked.txt',
        r"$'\x72\x6d' tracked.txt", r"$'\162\155' tracked.txt",
        "/bin/r? tracked.txt", "r\\\nm tracked.txt",
        "eval '$(printf r)$(printf m) tracked.txt'",
        "bash -c '$(printf r)$(printf m) tracked.txt'",
        "sh -lc 'r$(printf m) tracked.txt'",
        "EMPTY=; r${EMPTY}m tracked.txt", "command -p /bin/rm tracked.txt",
        "env -i /bin/rm tracked.txt", "exec /bin/rm tracked.txt",
        ">/dev/null /bin/rm tracked.txt", "! /bin/rm tracked.txt",
        "{ /bin/rm tracked.txt; }", "bash -O extglob -c '/bin/rm tracked.txt'",
        "eval -- '/bin/rm tracked.txt'", 'printf \'%s\' "$(\'/bin/rm\' tracked.txt)"',
        "find . -exec /bin/rm {} +", "printf x | xargs -n 1 /bin/rm",
    ))
    def test_structural_command_positions_fail_closed(self, command):
        assert run_hook(command) == BLOCK, command

    @pytest.mark.parametrize("command", (
        "printf '%s' '$(printf r)$(printf m) tracked.txt'",
        "python3 checker.py '$\\x72\\x6d tracked.txt'",
        "rg -n 'command -p /bin/rm' docs", "echo '/bin/r? tracked.txt'",
        "git rm --cached tracked.txt", "/usr/bin/git -C repo rm -r --cached tracked.txt",
        "command git rm --cached tracked.txt", "env -i git rm --cached tracked.txt",
        "bash -c 'git rm --cached tracked.txt'", "eval 'git rm --cached tracked.txt'",
        "docker rm dev-container", "/usr/bin/docker rm dev-container",
    ))
    def test_structural_classifier_preserves_inert_and_safe_controls(self, command):
        assert run_hook(command) == ALLOW, command

    @pytest.mark.parametrize("command", (
        "bash -O extglob -c '/bin/r@(m) tracked.txt'", "bash -O extglob -c '/bin/r+(m) tracked.txt'",
        "env -S '/bin/rm tracked.txt'", "env --split-string='/bin/rm tracked.txt'",
        "/usr/bin/time -f fmt /bin/rm tracked.txt", "sudo -p prompt /bin/rm tracked.txt",
        "coproc JOB { /bin/rm tracked.txt; }", "A+=x /bin/rm tracked.txt",
        "rm>/dev/null tracked.txt", "/bin/rm>/dev/null tracked.txt",
        "command >/dev/null -p /bin/rm tracked.txt", "env >/dev/null -i /bin/rm tracked.txt",
        "sudo >/dev/null -u root /bin/rm tracked.txt", "eval >/dev/null -- /bin/rm tracked.txt",
        "bash -c 'git rm -- --cached tracked.txt'", "bash -c 'rm>/dev/null tracked.txt'",
        "bash <<< '/bin/rm tracked.txt'", "printf '%s\\n' '/bin/rm tracked.txt' | bash",
        "eval 'rm>/dev/null tracked.txt'", "eval 'git rm -- --cached tracked.txt'",
        "printf tracked.txt | xargs -d x /bin/rm", "printf tracked.txt | xargs --delimiter x /bin/rm",
        r"find . -ok /bin/rm {} \;", r"find . -okdir /bin/rm {} \;",
        r"find . -exec env -S '/bin/rm {}' \;", 'echo "$(git rm -- --cached tracked.txt)"',
        'echo "$(rm>/dev/null tracked.txt)"', "echo $(( $(/bin/rm tracked.txt) + 1 ))",
        'echo "${X:-$(/bin/rm tracked.txt)}"', 'echo "${X:=$(/bin/rm tracked.txt)}"',
        "cat <<EOF\n$(/bin/rm tracked.txt)\nEOF", "cat <<EOF\n`/bin/rm tracked.txt`\nEOF",
        "cat <<EOF\n${X:-$(/bin/rm tracked.txt)}\nEOF", "cat <<EOF\n$(/bin/rm tracked.txt)",
        "echo ${X:-$(/bin/rm tracked.txt)", "echo $(( $(/bin/rm tracked.txt) + 1",
        "git rm -- --cached tracked.txt", "command git rm -- --cached tracked.txt",
        "git --literal-pathspecs rm -- --cached tracked.txt", "git rm --ignore-unmatch -- --cached tracked.txt",
        "docker rm dev; git rm -- --cached tracked.txt",
    ))
    def test_iteration_five_structural_mismatches_are_blocked(self, command):
        assert run_hook(command) == BLOCK, command

    @pytest.mark.parametrize(("command", "expected"), (
        ("git rm --cached>/dev/null tracked.txt", ALLOW), ("rm2>/dev/null tracked.txt", ALLOW),
        ("git rm --cached -- --cached", ALLOW), ("git rm \"$maybe\" --cached tracked.txt", BLOCK),
        ("env -S 'echo $(/bin/rm)'", ALLOW), ("printf '/bin/rm tracked.txt' | cat", ALLOW),
        ("A=rm echo ok", ALLOW), (r"find . -name rm", ALLOW), ("{r,echo}m tracked.txt", BLOCK),
        ("echo '${X:-$(/bin/rm tracked.txt)}'", ALLOW), ("cat <<'EOF'\n$(/bin/rm tracked.txt)\nEOF", ALLOW),
        ("cat <<EOF\n\\$(/bin/rm tracked.txt)\nEOF", ALLOW), ("bash <<'EOF'\n/bin/rm tracked.txt\nEOF", BLOCK),
    ))
    def test_iteration_five_representation_boundaries(self, command, expected):
        assert run_hook(command) == expected, command

    def test_quoted_reset_rule_data_and_sed_range_are_allowed(self):
        assert run_hook("echo 'permission: git reset --hard' >/dev/null") == ALLOW
        assert run_hook("sed -n '1,3p' README.md >/dev/null") == ALLOW


# ── Layer 1.F false-positive regression: protected name in quoted arg ─────────
# dev-20260529-210759: Layer 1.F entry gate switched from $COMMAND to
# $COMMAND_CONTEXT_STRIPPED so that quoted string arguments to unrelated commands
# do not trigger the sentinel-write block.

class TestBulkSentinelFalsePositive:
    """Commands whose quoted-string argument happens to mention write-bulk-commit-sentinel.py
    must NOT be blocked by Layer 1.F when the script is not actually being executed.

    AC1: graphify-query.py with --requirement arg containing the protected name → ALLOW
    AC2: codex exec with --prompt arg containing the protected name → ALLOW
    AC3: bare invocation (BARE_WRITER path removed in Stage-2 lockdown) → BLOCK
    AC4: compound command containing the invocation → BLOCK
    """

    def test_ac1_graphify_requirement_arg_not_blocked(self):
        # AC1: protected name appears only in --requirement string argument value.
        cmd = (
            'python3 scripts/graphify-query.py --requirement '
            '"Add positive regression test for CLAUDE_CODE_SESSION_ID fallback path '
            'in write-bulk-commit-sentinel.py"'
        )
        assert run_hook(cmd) == ALLOW

    def test_ac2_codex_prompt_arg_not_blocked(self):
        # AC2: protected name appears only in --prompt string argument value.
        cmd = (
            'codex exec --prompt '
            '"Please add a test for write-bulk-commit-sentinel.py fallback path"'
        )
        assert run_hook(cmd) == ALLOW

    def test_ac3_bare_invocation_blocked_by_stage2_lockdown(self):
        # AC3: after Stage-2 lockdown (commit 14f2ea58), the sentinel writer is NO LONGER
        # Bash-executable. The userprompt-bulk-commit-capability hook mints sentinels
        # in-process. Direct Bash invocation MUST be BLOCKED.
        cmd = "python3 scripts/write-bulk-commit-sentinel.py"
        assert run_hook(cmd) == BLOCK

    def test_ac4_compound_invocation_still_blocked(self):
        # AC4: compound command containing the invocation must still BLOCK.
        cmd = "echo test && python3 scripts/write-bulk-commit-sentinel.py --output-dir /tmp"
        assert run_hook(cmd) == BLOCK

    def test_ac5_bash_lc_wrapper_still_blocked(self):
        # AC5: bash -lc wrapping the writer must BLOCK (security regression check).
        cmd = 'bash -lc "python3 scripts/write-bulk-commit-sentinel.py"'
        assert run_hook(cmd) == BLOCK

    def test_ac6_bash_c_wrapper_still_blocked(self):
        # AC6: bash -c wrapping the writer must BLOCK.
        cmd = 'bash -c "python3 scripts/write-bulk-commit-sentinel.py"'
        assert run_hook(cmd) == BLOCK
