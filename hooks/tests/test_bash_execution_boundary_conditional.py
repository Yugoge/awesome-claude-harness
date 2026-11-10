"""FR-1: `&&`, `||`, `!`, `(` and `)` inside `[[ ... ]]` are not command boundaries.

Before this fix the walk split `[[ "$A" != "." && "$A" != ".." ]]` at its `&&`
and then read the operand `"$A"` as the head of a second command, refusing a
plain string test as `UNRESOLVED dynamic_command_head`. Inside the conditional
compound command the shell reads a conditional expression: its `&&`, `||`, `!`,
`(` and `)` are operators and every operand is a word, never a command head.

The fix keeps every real command head refused: an expansion in command position
before or after a real `&&` / `||` outside the brackets, inside a `$( )` or
backquote within the brackets, or after the closing `]]`; and every spelling in
which `[[` is NOT the reserved word (quoted, after an assignment or a
redirection, as an argument, under sh / dash / ash, as a case pattern, after an
alias or `disable` builtin) keeps the old reading, in which `&&` and `||` are
boundaries.

ZERO EXECUTION: every command below is a string handed to the analyzer, or to
the hook as JSON on stdin with a scratch HOME. Nothing here runs a command.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "hooks", "lib"))

import bash_execution_boundary as eb  # noqa: E402

HOOK = os.path.join(REPO_ROOT, "hooks", "pretool-bash-safety.sh")

OWNER = '[[ "$A" != "." && "$A" != ".." ]]'

# Each of these is refused on the base as `dynamic_command_head` (an operand
# after an inner `&&` / `||` read as a command head) and is a plain test.
CONDITIONALS = {
    "owner": OWNER,
    "or": '[[ "$A" != "." || "$A" != ".." ]]',
    "not": '[[ ! "$A" == "." && ! "$A" == ".." ]]',
    "grouping": '[[ ( "$A" == x || "$A" == y ) && ! ( "$B" == z ) ]]',
    "nested_grouping": '[[ ( ( "$A" == x ) ) || "$B" == y ]]',
    "if": 'if [[ "$A" != "." && "$A" != ".." ]]; then echo ok; fi',
    "elif": 'if false; then :; elif [[ "$A" == x || "$B" == y ]]; then echo ok; fi',
    "while": 'while [[ "$A" != "." && "$A" != ".." ]]; do echo ok; break; done',
    "until": 'until [[ "$A" == "." || "$A" == ".." ]]; do break; done',
    "while_not": 'while ! [[ "$A" == x && "$B" == y ]]; do break; done',
    "and_chain_outside": 'echo a && [[ "$A" != "." && "$A" != ".." ]] && echo b',
    "or_chain_outside": 'false || [[ "$A" != "." && "$A" != ".." ]] || echo b',
    "two_conditionals": '[[ "$A" == x ]] && [[ "$B" == y || "$C" == z ]] && echo ok',
    "brace_group": '{ [[ "$A" == x || "$B" == y ]]; }',
    "subshell": '( [[ "$A" == x || "$B" == y ]] )',
    "line_break_after_and": '[[ "$A" == x &&\n   "$B" == y ]] && echo ok',
    "in_command_substitution": 'echo "$( [[ "$A" == x && "$B" == y ]] && echo yes )"',
    "bash_c": "bash -c '[[ \"$A\" != \".\" && \"$A\" != \"..\" ]]'",
    "bash_c_if": "bash -c 'if [[ \"$A\" == x || \"$B\" == y ]]; then echo ok; fi'",
    "zsh_c": "zsh -c '[[ \"$A\" == x || \"$B\" == y ]]'",
    "eval": "eval '[[ \"$A\" == x && \"$B\" == y ]]'",
}

# An expansion in command position stays refused. The refusal reason is the
# same one the base gives these strings.
DYNAMIC_HEADS = {
    "after_and": '[[ -n "$A" ]] && $CMD',
    "after_or": '[[ -n "$A" ]] || $CMD',
    "before_and": '$CMD && [[ -n x ]]',
    "before_or": '$CMD || [[ -n x ]]',
    "around": '$CMD && [[ "$A" == x || "$B" == y ]] && $CMD2',
    "after_semicolon": '[[ "$A" == x && "$B" == y ]]; $CMD',
    "after_line_break": '[[ "$A" == x && "$B" == y ]]\n$CMD',
    "after_pipe": '[[ "$A" == x ]] | $CMD',
    "after_close_no_space": '[[ "$A" == x ]]&&$CMD',
    "after_close_redirect": '[[ "$A" == x ]] >/dev/null || $CMD',
    "after_quoted_close": '[[ "$A" == "]]" && $CMD ]]',
    "after_second_conditional": '[[ -n x ]] && [[ -n y ]] && $CMD',
    "then_body": 'if [[ "$A" == x && "$B" == y ]]; then $CMD; fi',
    "brace_body": '[[ "$A" == x ]] || { $CMD; }',
    "substitution_inside": '[[ -n $($CMD) ]]',
    "substitution_after_inner_and": '[[ -n x && $($CMD) == y ]]',
    "substitution_before_inner_or": '[[ $($CMD) == y || -n x ]]',
    "backquote_inside": '[[ -n x && `$CMD` == y ]]',
    "process_substitution_inside": '[[ -n x && <($CMD) == y ]]',
    "bash_c_after": "bash -c '[[ -n \"$A\" ]] && $CMD'",
    "bash_c_inside_substitution": "bash -c '[[ -n $($CMD) && x ]]'",
    # `[[` that is not the reserved word: the `&&` / `||` is a real boundary.
    "quoted_opener": '"[[" a || $CMD ]]',
    "single_quoted_opener": "'[[' a || $CMD ]]",
    "escaped_opener": '\\[[ a || $CMD ]]',
    "assignment_before": 'A=1 [[ a || $CMD ]]',
    "redirection_before": '>/dev/null [[ a || $CMD ]]',
    "argument": 'echo [[ a || $CMD ]]',
    "wrapper_argument": 'sudo [[ a || $CMD ]]',
    "for_word_list": 'for x in [[ a || $CMD ]]; do :; done',
    "sh_c": "sh -c '[[ a || $CMD ]]'",
    "dash_c": "dash -c '[[ a || $CMD ]]'",
    "ash_c": "ash -c '[[ a || $CMD ]]'",
    "find_exec_sh_c": "find . -exec sh -c '[[ -n x && $CMD ]]' \\;",
    "ssh_remote_shell": "ssh host '[[ a || $CMD ]]'",
    "su_c": "su -c '[[ a || $CMD ]]'",
    "case_pattern": 'case x in\n[[) $CMD;; esac',
    "case_pattern_same_line": 'case x in [[) $CMD;; esac',
    "case_pattern_alternative": 'case x in [[|y) $CMD;; esac',
    "case_pattern_parenthesised": 'case x in ([[) $CMD;; esac',
    "unbalanced_close_paren": '[[ ( a ) ) || $CMD ]]',
    "inner_semicolon": '[[ a; $CMD ]]',
    "inner_pipe": '[[ a | $CMD ]]',
    "inner_background": '[[ a & $CMD ]]',
    # An alias named `[[` (or zsh's `disable -r`) makes `[[` a simple command.
    "alias_defined": "shopt -s expand_aliases; alias '[['=false\n[[ a || $CMD ]]",
    "alias_escaped_name": "shopt -s expand_aliases; builtin al\\ias '[['=false\n[[ a || $CMD ]]",
    "bash_aliases_array": "BASH_ALIASES[x]=false\n[[ a || $CMD ]]",
    "alias_in_bash_c": "bash -c \"alias '[['=false\n[[ a || \\$CMD ]]\"",
    "disable_reserved_word": "disable -r '[['\n[[ a || $CMD ]]",
    "disable_escaped_name": "dis\\able -r '[['\n[[ a || $CMD ]]",
}

# A removal outside the brackets is still a removal.
REMOVALS = {
    "after_or": '[[ "$A" == x && "$B" == y ]] || rm -rf qa-fr1-target',
    "inside_substitution": '[[ -n $(rm -rf qa-fr1-target) && x ]]',
}

# Single-bracket `[` and `test` keep their verdicts (each is one simple command;
# its `&&` / `||` are real boundaries).
SINGLE_BRACKET_ALLOWED = (
    '[ "$A" != "." ] && [ "$A" != ".." ]',
    '[ "$A" != "." -a "$A" != ".." ]',
    'test "$A" != "." && test "$A" != ".."',
)
SINGLE_BRACKET_REFUSED = (
    '[ -n "$A" ] && $CMD',
    'test -n "$A" || $CMD',
)


# ── The analyzer ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("command", list(CONDITIONALS.values()), ids=list(CONDITIONALS))
def test_a_conditional_expression_is_one_command(command):
    result = eb.analyze(command)
    assert result["allowed"] is True, (command, result["verdict"], result["reason"])
    assert result["verdict"] == eb.PROVEN_INERT


def test_the_owner_string_had_its_operand_read_as_a_command_head():
    # The base refused the owner string at the operand after `&&`; that operand
    # is now a word of the `[[` command and no boundary names it.
    result = eb.analyze(OWNER)
    assert not any(b["reason"] == "dynamic_command_head" for b in result["boundaries"])
    assert [b["reason"] for b in result["boundaries"]] == [
        "named_program_no_removal_reference"]


@pytest.mark.parametrize("command", list(DYNAMIC_HEADS.values()), ids=list(DYNAMIC_HEADS))
def test_a_dynamic_command_head_stays_refused(command):
    result = eb.analyze(command)
    assert result["allowed"] is False, command
    assert result["verdict"] == eb.UNRESOLVED, (command, result["reason"])
    assert result["reason"].startswith("dynamic_command_head:"), (command, result["reason"])


@pytest.mark.parametrize("command", list(REMOVALS.values()), ids=list(REMOVALS))
def test_a_removal_beside_a_conditional_stays_forbidden(command):
    result = eb.analyze(command)
    assert result["verdict"] == eb.FORBIDDEN_REMOVAL, (command, result["reason"])


@pytest.mark.parametrize("command", SINGLE_BRACKET_ALLOWED)
def test_single_bracket_tests_keep_their_allow(command):
    assert eb.analyze(command)["allowed"] is True, command


@pytest.mark.parametrize("command", SINGLE_BRACKET_REFUSED)
def test_single_bracket_tests_keep_their_refusal(command):
    result = eb.analyze(command)
    assert result["allowed"] is False, command
    assert result["reason"].startswith("dynamic_command_head:"), result["reason"]


def test_a_shell_this_file_cannot_name_keeps_the_old_reading():
    # analyze_code's default is the old reading: a caller that hands code to a
    # shell other than the command's own has to say it is a COND_SHELLS shell.
    az = eb.Analyzer(OWNER)
    az.analyze_code(eb.Src.from_raw(OWNER), eb.Env())
    assert any(b["reason"] == "dynamic_command_head" for b in az.boundaries)


# ── The real hook, for the main agent and a subagent ─────────────────────────

@pytest.fixture(scope="module")
def scratch_home(tmp_path_factory):
    return str(tmp_path_factory.mktemp("home"))


def _hook_exit(command, home, agent):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    if agent:
        payload.update({"agent_id": "fr1-subagent", "agent_type": "dev"})
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": home}
    proc = subprocess.run(["bash", HOOK], input=json.dumps(payload), text=True,
                          capture_output=True, cwd=REPO_ROOT, env=env, timeout=120)
    return proc.returncode, proc.stderr


HOOK_ALLOWED = [CONDITIONALS[k] for k in (
    "owner", "or", "not", "grouping", "if", "while", "and_chain_outside", "bash_c")]
HOOK_REFUSED = [DYNAMIC_HEADS[k] for k in (
    "after_and", "before_and", "around", "after_line_break", "substitution_inside",
    "substitution_after_inner_and", "bash_c_after", "quoted_opener", "sh_c",
    "case_pattern", "alias_defined")]


@pytest.mark.parametrize("agent", [False, True], ids=["main", "subagent"])
@pytest.mark.parametrize("command", HOOK_ALLOWED)
def test_the_hook_allows_the_conditional(command, agent, scratch_home):
    code, err = _hook_exit(command, scratch_home, agent)
    assert code == 0, (command, err[:300])


@pytest.mark.parametrize("agent", [False, True], ids=["main", "subagent"])
@pytest.mark.parametrize("command", HOOK_REFUSED)
def test_the_hook_refuses_a_dynamic_command_head(command, agent, scratch_home):
    code, err = _hook_exit(command, scratch_home, agent)
    assert code == 2, (command, err[:300])
    assert "dynamic_command_head" in err, (command, err[:300])
