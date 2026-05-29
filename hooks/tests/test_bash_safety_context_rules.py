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
import subprocess

HOOK = os.path.join(os.path.dirname(__file__), "..", "pretool-bash-safety.sh")


def run_hook(command: str) -> int:
    """Invoke the real hook with a Bash tool_input and return its exit code."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    proc = subprocess.run(
        ["bash", HOOK],
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


# ── Regression guard: untouched raw-$COMMAND git rule still blocks ───────────

class TestGitRuleStaysRaw:
    """git reset --hard must STILL block: it was deliberately NOT converted, so a
    quoted --hard would otherwise strip to 'git reset ' and create a false negative.
    This guards against an accidental future conversion of the git rules."""

    def test_git_reset_hard_is_blocked(self):
        assert run_hook("git reset --hard HEAD~1") == BLOCK
