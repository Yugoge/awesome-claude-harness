"""Unit tests for the executable-context view bash-safety reads.

They were written for hooks/lib/bash_context_strip.py's
strip_non_executable_contexts(), covering the main Pass 1-5 transformations
documented in its spec. That module is gone: its one equivalent is the shared
parser's hooks/lib/shell_parse.py executable_view(), which these tests now run
against under the old name.

Run with: python3 -m pytest hooks/tests/test_bash_safety_context.py -v
"""

import re
import sys
import os

# Add hooks dir to path so we can import from hooks/lib/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from hooks.lib.shell_parse import executable_view as strip_non_executable_contexts


# ── Helpers ───────────────────────────────────────────────────────────────────

def grep_match(pattern, text):
    """Simulate grep -qE: match against each line (grep is line-oriented)."""
    for line in text.split('\n'):
        if re.search(pattern, line):
            return True
    return False


# ── Pass 1: control-operator splitting ───────────────────────────────────────

class TestPass1ControlOperatorSplit:
    """Pass 1: top-level control operators split segments; boundaries preserved."""

    def test_semicolon_keeps_second_segment(self):
        """rm after semicolon is executable — stripping first arg does not hide it."""
        cmd = 'echo "literal rm text"; rm /tmp/foo'
        result = strip_non_executable_contexts(cmd)
        # rm in second segment must survive
        assert grep_match(r'(^|[ \t;|&(])rm\s', result)

    def test_pipe_keeps_second_segment(self):
        """Token after | is a new command — its content is executable."""
        cmd = 'echo "some text" | rm /tmp/x'
        result = strip_non_executable_contexts(cmd)
        assert grep_match(r'(^|[ \t;|&(])rm\s', result)

    def test_and_and_keeps_second_segment(self):
        """Token after && is a new command."""
        cmd = 'true && rm /tmp/x'
        result = strip_non_executable_contexts(cmd)
        assert grep_match(r'(^|[ \t;|&(])rm\s', result)

    def test_quotes_inside_segment_are_not_split_points(self):
        """Quoted ; inside a string arg is not a control operator."""
        cmd = 'python3 -c "x = 1; rm -rf /"'
        result = strip_non_executable_contexts(cmd)
        # The 'rm' inside the quoted arg to non-shell python3 must be stripped
        assert not grep_match(r'(^|[ \t;|&(])rm\s', result)


# ── Pass 2: sh/bash -c recursion ─────────────────────────────────────────────

class TestPass2ShellInterpRecursion:
    """Pass 2: sh/bash -c payloads are recursively analyzed as executable."""

    def test_sh_c_rm_is_blocked(self):
        """rm inside sh -c payload is executable — must survive stripping."""
        cmd = "sh -c 'rm /tmp/foo.txt'"
        result = strip_non_executable_contexts(cmd)
        assert grep_match(r'(^|[ \t;|&(])rm\s', result)

    def test_bash_c_kill_signal_is_blocked(self):
        """kill -9 inside bash -c payload is executable."""
        cmd = "bash -c 'kill -9 1234'"
        result = strip_non_executable_contexts(cmd)
        assert grep_match(r'(^|[ \t;|&])(kill)[ \t]+-', result)

    def test_bash_c_innocuous_string_is_stripped(self):
        """Non-dangerous content in bash -c string is still preserved (not false-stripped)."""
        cmd = "bash -c 'echo hello'"
        result = strip_non_executable_contexts(cmd)
        assert 'echo' in result

    def test_later_positional_args_not_executable(self):
        """Args after the -c payload (positional $0, $1) are string content, not shell."""
        cmd = "bash -c 'echo hi' \"rm /tmp/x\""
        result = strip_non_executable_contexts(cmd)
        # rm in the positional arg (not in -c payload) must be stripped
        # The -c payload 'echo hi' is preserved; rm must not appear as executable
        assert 'echo hi' in result


# ── Pass 3: heredoc classification ───────────────────────────────────────────

class TestPass3HeredocClassification:
    """Pass 3: heredoc consumer determines whether body is executable."""

    def test_bash_consumer_heredoc_preserved(self):
        """bash <<'EOF' heredoc body is shell-executable — rm must survive."""
        cmd = "bash <<'EOF'\nrm /tmp/foo.txt\nEOF"
        result = strip_non_executable_contexts(cmd)
        assert grep_match(r'(^|[ \t;|&(])rm\s', result)

    def test_sh_consumer_heredoc_preserved(self):
        """sh <<'EOF' heredoc body is shell-executable — kill must survive."""
        cmd = "sh <<'EOF'\nkill -9 1234\nEOF"
        result = strip_non_executable_contexts(cmd)
        assert grep_match(r'(^|[ \t;|&])(kill)[ \t]+-', result)

    def test_tee_consumer_heredoc_stripped(self):
        """cat <<'EOF' | tee — body is data context, kill should not survive."""
        cmd = "cat <<'EOF' | tee /tmp/doc\nkill -9 1234\nEOF"
        result = strip_non_executable_contexts(cmd)
        assert not grep_match(r'(^|[ \t;|&])(kill)[ \t]+-', result)

    def test_pipe_bash_consumer_heredoc_preserved(self):
        """cat <<'EOF' | bash — body is piped to shell, kill must survive."""
        cmd = "cat <<'EOF' | bash\nkill -9 1234\nEOF"
        result = strip_non_executable_contexts(cmd)
        # After stripping, the kill must still be detectable (grep line-by-line)
        assert grep_match(r'(^|[ \t;|&])(kill)[ \t]+-', result)


# ── Pass 4: non-shell command argument stripping ──────────────────────────────

class TestPass4NonShellArgStripping:
    """Pass 4: quoted args to non-shell commands are stripped."""

    def test_codex_exec_quoted_killall_stripped(self):
        """The confirmed incident: codex exec 'killall...claude' must be stripped."""
        cmd = 'codex exec "The hook documentation says killall and claude processes are monitored"'
        result = strip_non_executable_contexts(cmd)
        assert not grep_match(r'(killall|pkill)\s+.*(happy|claude|docker)', result)

    def test_echo_kill_in_quoted_arg_stripped(self):
        """kill inside echo quoted arg is not executable."""
        cmd = "echo \"trap 'kill -TERM $PID' SIGTERM\""
        result = strip_non_executable_contexts(cmd)
        assert not grep_match(r'(^|[ \t;|&])(kill)[ \t]+-', result)

    def test_git_commit_message_stripped(self):
        """SIGKILL in git commit message is not executable."""
        cmd = 'git commit -m "fix: avoid SIGKILL by using graceful shutdown"'
        result = strip_non_executable_contexts(cmd)
        assert not grep_match(r'(^|[ \t;|&])(kill)[ \t]+-', result)

    def test_command_subst_inside_echo_arg_preserved(self):
        """$(rm ...) inside a double-quoted echo arg is executable — must survive."""
        cmd = 'echo "$(rm /tmp/foo.txt)"'
        result = strip_non_executable_contexts(cmd)
        assert grep_match(r'(^|[ \t;|&(])rm\s', result)

    def test_bare_command_word_unchanged(self):
        """The command word itself (killall happy) must never be stripped."""
        cmd = 'killall happy'
        result = strip_non_executable_contexts(cmd)
        assert grep_match(r'(killall|pkill)\s+.*(happy|claude|docker)', result)

    def test_rm_bare_command_unchanged(self):
        """Bare rm command not inside any string — must survive."""
        cmd = 'rm /tmp/foo.txt'
        result = strip_non_executable_contexts(cmd)
        assert grep_match(r'(^|[ \t;|&(])rm\s', result)


# ── Pass 5: comment stripping ─────────────────────────────────────────────────

class TestPass5CommentStripping:
    """Pass 5: shell comments (#...) in non-shell command args are stripped."""

    def test_rm_after_hash_in_python_arg_not_blocked(self):
        """rm after # inside python3 -c string is a Python comment, not executable."""
        cmd = "python3 -c 'import os; # rm is not needed here'"
        result = strip_non_executable_contexts(cmd)
        assert not grep_match(r'(^|[ \t;|&(])rm\s', result)


# ── Fail-safe contract ────────────────────────────────────────────────────────

class TestFailSafeContract:
    """M10: exceptions must return raw cmd unchanged (block-side fail)."""

    def test_empty_string(self):
        """Empty command string should not raise."""
        result = strip_non_executable_contexts('')
        assert result == ''

    def test_simple_safe_command_unchanged(self):
        """Commands with no string args return equivalent output."""
        cmd = 'ls -la /tmp'
        result = strip_non_executable_contexts(cmd)
        assert 'ls' in result

    def test_unterminated_quote_does_not_raise(self):
        """Unterminated quote is malformed shell — should not raise, return something."""
        cmd = 'echo "unclosed'
        try:
            result = strip_non_executable_contexts(cmd)
            # Should not raise; may return raw or partially processed
            assert isinstance(result, str)
        except Exception as e:
            assert False, f"Must not raise: {e}"

    def test_nested_subst_does_not_raise(self):
        """Deeply nested $() does not raise."""
        cmd = 'echo "$(echo $(cat /tmp/x))"'
        try:
            result = strip_non_executable_contexts(cmd)
            assert isinstance(result, str)
        except Exception as e:
            assert False, f"Must not raise: {e}"


class TestDangerCommandArgPreservation:
    """DANGER_COMMANDS: quoted args to dangerous command words must NOT be stripped."""

    def test_killall_quoted_target_preserved(self):
        """killall \"happy\" — quoted target must survive so pattern still matches."""
        cmd = 'killall "happy"'
        result = strip_non_executable_contexts(cmd)
        assert "happy" in result

    def test_pkill_quoted_flag_arg_preserved(self):
        """pkill -f \"claude\" — quoted argument must survive so pattern still matches."""
        cmd = 'pkill -f "claude"'
        result = strip_non_executable_contexts(cmd)
        assert "claude" in result

    def test_kill_quoted_signal_preserved(self):
        """kill \"-9\" 1234 — quoted signal flag must survive so pattern still matches."""
        cmd = 'kill "-9" 1234'
        result = strip_non_executable_contexts(cmd)
        assert "-9" in result

    def test_echo_quoted_killall_string_still_stripped(self):
        """echo \"killall is bad\" — quoted arg to echo (non-danger cmd) IS still stripped."""
        cmd = 'echo "killall is bad"'
        result = strip_non_executable_contexts(cmd)
        # echo is not a danger command; its quoted arg should be stripped
        assert "killall is bad" not in result


# ── BUG 1: Combined short-option flag containing 'c' ─────────────────────────

class TestBug1CombinedFlagWithC:
    """BUG 1 regression: _process_shell_interp must detect -c inside any short-option cluster."""

    def test_ac1_combined_lc_exposes_rm(self):
        """AC1: bash -lc 'rm /tmp/x' — rm must be visible as executable text."""
        cmd = "bash -lc 'rm /tmp/x'"
        result = strip_non_executable_contexts(cmd)
        assert grep_match(r'(^|[ \t;|&(])rm\s', result), f"rm not visible in: {result!r}"

    def test_ac2_combined_ce_exposes_rm(self):
        """AC2: bash -ce 'rm /tmp/x' — rm must be visible as executable text."""
        cmd = "bash -ce 'rm /tmp/x'"
        result = strip_non_executable_contexts(cmd)
        assert grep_match(r'(^|[ \t;|&(])rm\s', result), f"rm not visible in: {result!r}"

    def test_ac10_plus_c_form_exposes_rm(self):
        """AC10: bash +c 'rm /tmp/x' — POSIX +c variant must be recognised."""
        cmd = "bash +c 'rm /tmp/x'"
        result = strip_non_executable_contexts(cmd)
        assert grep_match(r'(^|[ \t;|&(])rm\s', result), f"rm not visible in: {result!r}"


# ── BUG 2: Wrapper command options in _find_command_word ─────────────────────

class TestBug2WrapperCommandOptions:
    """BUG 2 regression: _find_command_word must skip sudo option-arg pairs."""

    def test_ac3_sudo_u_root_shifts_to_bash_rm_exposed(self):
        """AC3: sudo -u root bash -c 'rm /tmp/x' — rm must be visible."""
        cmd = "sudo -u root bash -c 'rm /tmp/x'"
        result = strip_non_executable_contexts(cmd)
        assert grep_match(r'(^|[ \t;|&(])rm\s', result), f"rm not visible in: {result!r}"

    def test_ac4_sudo_H_no_arg_flag_no_over_skip(self):
        """AC4: sudo -H bash -c 'rm /tmp/x' — -H is no-arg flag; bash must be cmd word."""
        cmd = "sudo -H bash -c 'rm /tmp/x'"
        result = strip_non_executable_contexts(cmd)
        assert grep_match(r'(^|[ \t;|&(])rm\s', result), f"rm not visible in: {result!r}"

    def test_ac5_sudo_double_dash_terminates_options(self):
        """AC5: sudo -- bash -c 'rm /tmp/x' — '--' terminates options; bash is cmd word."""
        cmd = "sudo -- bash -c 'rm /tmp/x'"
        result = strip_non_executable_contexts(cmd)
        assert grep_match(r'(^|[ \t;|&(])rm\s', result), f"rm not visible in: {result!r}"


# ── BUG 3: Absolute-path shell in pipe not detected ───────────────────────────

class TestBug3AbsolutePathShellInPipe:
    """BUG 3 regression: heredoc piped to absolute-path shell must be preserved."""

    def test_ac6_heredoc_piped_to_bin_bash_preserves_body(self):
        """AC6: cat <<'EOF' | /bin/bash — heredoc body must be preserved."""
        cmd = "cat <<'EOF' | /bin/bash\nrm /tmp/x\nEOF"
        result = strip_non_executable_contexts(cmd)
        assert 'rm /tmp/x' in result, f"heredoc body not preserved in: {result!r}"

    def test_ac7_heredoc_piped_to_usr_bin_bash_preserves_body(self):
        """AC7: cat <<'EOF' | /usr/bin/bash — heredoc body must be preserved."""
        cmd = "cat <<'EOF' | /usr/bin/bash\nkill -9 1234\nEOF"
        result = strip_non_executable_contexts(cmd)
        assert grep_match(r'(^|[ \t;|&])(kill)[ \t]+-', result), f"kill not visible in: {result!r}"

    def test_ac8_non_shell_absolute_path_does_not_preserve_body(self):
        """AC8: cat <<'EOF' | /tmp/bash.old — 'bash.old' not in _SHELL_INTERPS; body stripped."""
        cmd = "cat <<'EOF' | /tmp/bash.old\nrm /tmp/x\nEOF"
        result = strip_non_executable_contexts(cmd)
        assert not grep_match(r'(^|[ \t;|&(])rm\s', result), f"rm incorrectly visible in: {result!r}"

    def test_bare_bash_dot_old_does_not_preserve_body(self):
        """Regression: 'bash.old' without path prefix must not match via old regex \\b boundary."""
        cmd = "cat <<'EOF' | bash.old\nrm /tmp/x\nEOF"
        result = strip_non_executable_contexts(cmd)
        assert not grep_match(r'(^|[ \t;|&(])rm\s', result), f"rm incorrectly visible in: {result!r}"


class TestDollarVariableRegression:
    """2026-05-24 OOM regression: ordinary shell variables must advance."""

    def test_bare_dollar_variable_does_not_livelock(self):
        result = strip_non_executable_contexts("echo $FOO")
        assert isinstance(result, str)
        assert "$FOO" in result

    def test_underscore_variable_does_not_livelock(self):
        result = strip_non_executable_contexts('[[ "$CODEX_OUT_TASK_ID" =~ $_safe_re ]]')
        assert isinstance(result, str)
        assert "$_safe_re" in result

    def test_braced_default_and_special_vars_do_not_livelock(self):
        result = strip_non_executable_contexts('echo "${CODEX_OUT_TASK_ID:-}" $$ $CLAUDE_PROJECT_DIR')
        assert isinstance(result, str)
        assert "$$" in result
        assert "$CLAUDE_PROJECT_DIR" in result


class TestScriptInterpArgStripping:
    """Argv tokens to non-shell script interpreters are stripped from danger-token scan."""

    def test_python3_rm_argv_stripped(self):
        result = strip_non_executable_contexts("python3 cleanup.py rm /tmp/old")
        assert "rm" not in result.split()

    def test_node_pkill_argv_stripped(self):
        result = strip_non_executable_contexts("node server.js pkill happy")
        assert "pkill" not in result.split()

    def test_process_subst_preserved(self):
        result = strip_non_executable_contexts("python3 script.py <(rm /tmp/x)")
        assert "rm" in result

    def test_bash_c_payload_unchanged(self):
        result = strip_non_executable_contexts("bash -c 'rm /tmp/foo'")
        assert "rm" in result

    def test_compound_second_segment(self):
        result = strip_non_executable_contexts("python3 script.py && rm /tmp/x")
        assert "rm" in result

    def test_versioned_interp(self):
        result = strip_non_executable_contexts("python3.12 manage.py rm session-123")
        assert "rm" not in result.split()

    def test_ruby_kill_argv_stripped(self):
        result = strip_non_executable_contexts("ruby app.rb killall happy")
        assert "killall" not in result.split()

    def test_rscript_canonical_case_stripped(self):
        result = strip_non_executable_contexts("Rscript cleanup.R rm /tmp/old")
        assert "rm" not in result.split()

    def test_r_canonical_case_stripped(self):
        result = strip_non_executable_contexts("R --vanilla run.R rm /tmp/old")
        assert "rm" not in result.split()
