"""Regression net for the cp/mv verb readings of hooks/lib/bash_write_targets.py, per consumer.

The library used to read a word that merely begins `cp-`/`mv-` (a checkpoint id such as `cp-01`, a
tool name such as `mv-tool`) and the variable name of a `for`/`select` loop spelled cp or mv as the
copy/move verb, so marking commands such as `spec-check.py mark ... --cp-id cp-01 2>&1` produced a
phantom write target (`2`, `ID`, `cp-09`) that the guards then refused. The reading is narrowed
only where the command segment holds no word that may be the verb; every real copy or move stays
reported, including one whose verb is a quoted expansion (`"$CP"`) inside a `case` arm.

Every test goes through the ENTRY POINT of one consumer, never through the library alone:
  * tool_policy - hooks/pretool-tool-policy.py, run as the real hook process
  * overnight   - hooks/pretool-overnight-hook-guard.py, the six decision functions that consume it
  * noncaller   - hooks/pretool-cp-state-write-guard.py, which reads no Bash command, and
                  hooks/pretool-wrapper-userintent.py, which only strips heredoc bodies: both unaffected
Kinds: `no_phantom` (a command that writes nothing yields no target: red on the unmodified library),
`still_detected` (a real copy or move is still refused, destination named: green on the unmodified
library and red on a library that drops detection) and `unchanged`.

The harness under test is read from HARNESS_ROOT_UNDER_TEST (default: the tree this file is in). It
needs `hooks/`, `policies/`, `scripts/` and `settings.json` together. Standard library and pytest
only; nothing is written outside pytest temporary directories.
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("HARNESS_ROOT_UNDER_TEST") or PROJECT).resolve()
HOOKS = ROOT / "hooks"

TOOL_POLICY_HOOK = "pretool-tool-policy.py"
OVERNIGHT_HOOK = "pretool-overnight-hook-guard.py"
CP_STATE_GUARD_HOOK = "pretool-cp-state-write-guard.py"
USERINTENT_HOOK = "pretool-wrapper-userintent.py"

DEST = "/srv/data/out"  # outside every ba/qa write prefix and not exempt in the overnight guard
M = "spec-check.py mark --spec-id S --agent ba --agent-id ID"
ROLES = ["ba", "qa"]

# ---- commands that write nothing: no phantom target may come out of them ------------------------
REDIRECT_MARKING = [
    M + " --cp-id cp-01 2>&1 | tail -5",
    M + " --cp-id cp-01 2>&1",
    "spec-check.py mark --spec-id S --agent qa --cp-id cp-01 --agent-id ID 2>&1 | tail -5",
    M + " --cp-id cp-01 --note 'cp done' 2>&1",
    "spec-check.py mark --spec-id S --agent ba --cp-id cp-01 --agent-id ID",
]
DOCUMENTED_MARKING = (
    'source "${CLAUDE_HOME:-$HOME/.claude}/venv/bin/activate" && python3 "${CLAUDE_HOME:-$HOME/.claude}'
    '/scripts/spec-check.py" mark --spec-id S --agent ba --agent-id "$CLAUDE_AGENT_ID" --cp-id cp-01 2>&1 | tail -3'
)
LOOP_MARKING = [
    "for %s in cp-01 cp-02 cp-09; do %s --cp-id $%s; done" % (v, M, v) for v in ("cp", "mv", "id", "c")
] + [
    "for cp in a b c; do echo $cp; done",
    "for mv in a b c; do echo $mv; done",
    "for cp in cp-01 cp-02 cp-09; do %s --cp-id $cp 2>&1 | tail -1; done" % M,
]
TOOL_NAME_WORDS = ["mv-tool src " + DEST, "cp-tool a " + DEST]

# ---- real copies and moves: still reported, destination named -------------------------------------
REAL_PLAIN = [
    "cp src " + DEST, "mv src " + DEST, "/bin/cp src " + DEST,
    "for f in a b; do cp $f " + DEST + "; done",
    "sudo -u for cp a " + DEST, "xargs -I for cp a " + DEST,
]
# a real copy in the same command as a cp-named loop: on the unmodified library the loop's phantom
# word is refused instead of (or before) the destination
BESIDE_REAL = [
    "for cp in a b; do cp x " + DEST + "; done",
    "for cp in cp-01 cp-02; do " + M + " --cp-id $cp; done; mv src " + DEST,
]
REAL_CHECKPOINT_SOURCE = [
    "cp cp-01 " + DEST, "sudo cp cp-01 " + DEST, "cp -r cp-01 " + DEST, "cp -a mv-tool " + DEST,
    "\\cp -R cp-01 " + DEST, M + " --cp-id cp-01 && cp src " + DEST,
]
REAL_ABSOLUTE_QUOTED = [
    "sudo /bin/cp cp-01 " + DEST, "time /bin/cp cp-01 " + DEST, "{ /bin/cp cp-01 " + DEST + "; }",
    "env A=1 /bin/mv mv-tool " + DEST, "sudo -u X /bin/mv mv-tool " + DEST,
    'sudo "cp" cp-01 ' + DEST, "sudo c\\p cp-01 " + DEST,
]
REAL_EXPANSION_SPELLED = [
    "$CP cp-01 " + DEST, "sudo $CP cp-01 " + DEST, "${CP} -r cp-01 " + DEST,
    '"$CP" cp-01 ' + DEST, 'sudo "$CP" cp-01 ' + DEST, 'sudo -u X "$CP" cp-01 ' + DEST,
    'time -p "$CP" cp-01 ' + DEST, 'nice -n 5 "$CP" -r mv-tool ' + DEST, 'env A=1 "$MV" mv-tool ' + DEST,
    "c$X -a cp-01 " + DEST, "sudo /usr/bin/$CMD -a cp-01 " + DEST, 'c"$X" cp-01 ' + DEST,
]
# a real copy or move inside a `case` arm, verb spelled with a quoted expansion (`"$CP"`, `c"$X"`), an
# unquoted expansion or plainly; `@@` is the destination and the second field the copy or move mechanism
CASE_ARM_ROWS = [
    ('case x in x) "${CP}" -r mv-tool @@ ;; esac', "mv-dest"), ('case x in x) "$C$P" -- cp-01 @@ ;; esac', "cp-dest"),
    ('case x in x) c"$X" -- mv-tool @@ ;; esac', "mv-dest"), ('case x in x) "$CP" -r cp-01 @@ ;; esac', "cp-dest"),
    ('case "$V" in x) "$CP" cp-01 @@ ;; esac', "cp-dest"), ('case x in (x) "$CP" cp-01 @@ ;; esac', "cp-dest"),
    ('case x in y) true ;; x) "$MV" mv-tool @@ ;; esac', "mv-dest"),
    ('case x in y) true ;; (x) "$CP" cp-01 @@ ;; esac', "cp-dest"), ('case x in a|b) "$CP" cp-01 @@ ;; esac', "cp-dest"),
    ('if true; then case x in x) "$CP" cp-01 @@ ;; esac; fi', "cp-dest"),
    ("case x in x) $CP -r mv-tool @@ ;; esac", "mv-dest"), ("case x in x) $C$P -- cp-01 @@ ;; esac", "cp-dest"),
    ("case x in x) c$X -- mv-tool @@ ;; esac", "mv-dest"), ("case x in x) cp -r mv-tool @@ ;; esac", "mv-dest"),
    ("case x in x) mv -- cp-01 @@ ;; esac", "mv-dest"), ("case x in x) /bin/cp cp-01 @@ ;; esac", "cp-dest"),
    # `;;`, `;&`, `in` and `case` that do not belong to an arm must not hide a real quoted-expansion verb
    ('# note;;\n"$CP" cp-01 @@', "cp-dest"), ('echo a\\;; "$CP" cp-01 @@', "cp-dest"),
    ('find . -exec ls {} \\;; "$CP" cp-01 @@', "cp-dest"), ('echo in\n"$CP" cp-01 @@', "cp-dest"),
    # a case arm's optional pattern-leading `(` is no grouping subshell, whether a `|` alternative or a
    # newline follows it
    ('case x in (y|x) "$CP" cp-01 @@ ;; esac', "cp-dest"),
    ('case x in\n(x) "$CP" cp-01 @@\n;; esac', "cp-dest"),
    ('case b in (a|b|c) "$CP" cp-01 @@ ;; esac', "cp-dest"),
]
REAL_CASE_ARM = [row.replace("@@", DEST) for row, _ in CASE_ARM_ROWS]
# a marking command or a copy-less word inside a case arm writes nothing
CASE_MARKING = [
    "case x in x) " + M + " --cp-id cp-01 2>&1 ;; esac",
    'case "$1" in start) python3 "$SC" mark --spec-id S --agent ba --agent-id "$ID" --cp-id cp-01 2>&1 | tail -3 ;; esac',
    "case x in x) for id in cp-01 cp-09; do echo $id; done ;; esac",
    "case x in y) true ;; (x) " + M + " --cp-id cp-01 2>&1 ;; esac",
    'case "$CP" in x) echo cp-01 ' + DEST + " ;; esac",
]


# ---- consumer 1: the real tool-policy hook process ----------------------------------------------
def _run_policy(role: str, command: str):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "agent_type": role,
               "agent_id": "a" + role + "verbnarrow", "session_id": "verbnarrow-sess"}
    proc = subprocess.run([sys.executable, str(HOOKS / TOOL_POLICY_HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=str(PROJECT), timeout=90)
    return proc.returncode, proc.stderr


def _policy_target(stderr: str):
    m = re.search(r"BLOCKED by tool-policy\.v1: (\{.*\})", stderr)
    if not m:
        return None
    try:
        return json.loads(m.group(1)).get("target")
    except ValueError:
        return None


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", REDIRECT_MARKING)
def test_tool_policy_no_phantom_redirect_marking(role, command):
    rc, err = _run_policy(role, command)
    assert rc == 0, "marking command refused for %s with target %r: %r" % (role, _policy_target(err), command)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", LOOP_MARKING)
def test_tool_policy_no_phantom_loop_marking(role, command):
    rc, err = _run_policy(role, command)
    assert rc == 0, "loop refused for %s with target %r: %r" % (role, _policy_target(err), command)


@pytest.mark.parametrize("role", ROLES)
def test_tool_policy_no_phantom_documented_marking_form(role):
    rc, err = _run_policy(role, DOCUMENTED_MARKING)
    assert rc == 0, "documented marking command refused for %s, target %r" % (role, _policy_target(err))


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", TOOL_NAME_WORDS)
def test_tool_policy_no_phantom_tool_name_word(role, command):
    rc, err = _run_policy(role, command)
    assert rc == 0, "a tool name that starts with cp-/mv- was read as the verb: target %r" % _policy_target(err)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", BESIDE_REAL)
def test_tool_policy_no_phantom_beside_real_copy(role, command):
    rc, err = _run_policy(role, command)
    assert (rc, _policy_target(err)) == (2, DEST), "the refused target must be the real destination: %r" % command


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", REAL_PLAIN)
def test_tool_policy_still_detected_real_copy_and_move(role, command):
    rc, err = _run_policy(role, command)
    assert (rc, _policy_target(err)) == (2, DEST), "real copy not refused for %s: %r" % (role, command)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", REAL_CHECKPOINT_SOURCE)
def test_tool_policy_still_detected_checkpoint_source(role, command):
    rc, err = _run_policy(role, command)
    assert (rc, _policy_target(err)) == (2, DEST), "real copy with a cp-/mv- source not refused: %r" % command


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", REAL_ABSOLUTE_QUOTED)
def test_tool_policy_still_detected_absolute_and_quoted_verb(role, command):
    rc, err = _run_policy(role, command)
    assert (rc, _policy_target(err)) == (2, DEST), "absolute or quoted verb not refused: %r" % command


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", REAL_EXPANSION_SPELLED)
def test_tool_policy_still_detected_expansion_spelled_verb(role, command):
    rc, err = _run_policy(role, command)
    assert (rc, _policy_target(err)) == (2, DEST), "expansion-spelled verb not refused: %r" % command


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", CASE_MARKING)
def test_tool_policy_no_phantom_case_arm_marking(role, command):
    rc, err = _run_policy(role, command)
    assert rc == 0, "a case arm that writes nothing was refused for %s, target %r: %r" % (role, _policy_target(err), command)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", REAL_CASE_ARM)
def test_tool_policy_still_detected_case_arm_verb(role, command):
    rc, err = _run_policy(role, command)
    assert (rc, _policy_target(err)) == (2, DEST), "real copy in a case arm not refused for %s: %r" % (role, command)


# ---- a case arm whose pattern opens with its optional `(` -----------------------------------------
# Bash runs the copy in each of these arms: the pattern's leading `(` is the arm's, not a subshell's,
# whether a `|` alternative follows on the same line, the pattern sits on the line after `case X in`,
# or the pattern has three alternatives.
SHAPE_1_SAME_LINE_ALTERNATION = 'case x in (y|x) "$CP" cp-01 ' + DEST + ' ;; esac'
SHAPE_2_NEXT_LINE = 'case x in\n(x) "$CP" cp-01 ' + DEST + '\n;; esac'
# subject `b` matches one alternative of (a|b|c), so bash runs the copy
SHAPE_3_MULTI_ALTERNATION = 'case b in (a|b|c) "$CP" cp-01 ' + DEST + ' ;; esac'
# CONTROL: `(x)` with no `|` alternative, on the same line as `case ... in` (also a row of
# CASE_ARM_ROWS), asserted on its own so a regression in this one shape is never masked by the others.
CONTROL_PAREN_NO_ALTERNATIVE = 'case x in (x) "$CP" cp-01 ' + DEST + ' ;; esac'


@pytest.mark.parametrize("role", ROLES)
def test_tool_policy_case_arm_shape1_same_line_alternation(role):
    """Bash runs this copy; tool_policy refuses it and names the real destination, as for every row
    in CASE_ARM_ROWS."""
    rc, err = _run_policy(role, SHAPE_1_SAME_LINE_ALTERNATION)
    assert (rc, _policy_target(err)) == (2, DEST), (
        "real copy in case-arm shape 1 (y|x) not refused for %s: %r" % (role, SHAPE_1_SAME_LINE_ALTERNATION))


@pytest.mark.parametrize("role", ROLES)
def test_tool_policy_case_arm_shape2_next_line(role):
    """As shape 1, with the parenthesized pattern on the line after `case X in`."""
    rc, err = _run_policy(role, SHAPE_2_NEXT_LINE)
    assert (rc, _policy_target(err)) == (2, DEST), (
        "real copy in case-arm shape 2 (next-line) not refused for %s: %r" % (role, SHAPE_2_NEXT_LINE))


@pytest.mark.parametrize("role", ROLES)
def test_tool_policy_case_arm_shape3_multi_alternation(role):
    """Shapes 1-2 with a three-way `(a|b|c)` alternation; subject `b` matches one alternative."""
    rc, err = _run_policy(role, SHAPE_3_MULTI_ALTERNATION)
    assert (rc, _policy_target(err)) == (2, DEST), (
        "real copy in case-arm shape 3 (a|b|c) not refused for %s: %r" % (role, SHAPE_3_MULTI_ALTERNATION))


@pytest.mark.parametrize("role", ROLES)
def test_tool_policy_control_case_arm_paren_no_alternative_still_detected(role):
    """CONTROL. `(x)` with no `|` alternative, on the same line as `case ... in`, is refused."""
    rc, err = _run_policy(role, CONTROL_PAREN_NO_ALTERNATIVE)
    assert (rc, _policy_target(err)) == (2, DEST), (
        "CONTROL regressed: (x) with no alternative must still be detected and refused: %r"
        % CONTROL_PAREN_NO_ALTERNATIVE)


# ---- a bare `in` or an escaped `\;;` is no case arm --------------------------------------------------
# Neither an ordinary word `in` with no `case` before it nor an escaped, literal `\;;` opens a case
# arm, so the subshell after it is a real one. Bash runs the `cp` in both commands below.
@pytest.mark.parametrize("role", ROLES)
def test_tool_policy_case_lead_heuristic_ignores_bare_in_before_real_subshell(role):
    """REGRESSION GUARD. `echo in` is an ordinary command with no case statement anywhere; the
    subshell on the next line is real and must still be refused, not silently swallowed because the
    heuristic mistook the preceding bare `in` for a case arm's `case X in`."""
    command = "echo in\n(cp x " + DEST + ") | cat"
    rc, err = _run_policy(role, command)
    assert (rc, _policy_target(err)) == (2, DEST), "bare `in` before a real subshell not refused: %r" % command


@pytest.mark.parametrize("role", ROLES)
def test_tool_policy_case_lead_heuristic_ignores_escaped_terminator_before_real_subshell(role):
    """REGRESSION GUARD. `\\;;` is an ESCAPED, literal `;;` (not a case-arm terminator); the subshell
    on the next line is real and must still be refused, not silently swallowed because the heuristic
    mistook the escaped terminator for a genuine case-arm `;;`."""
    command = "echo a\\;;\n(cp x " + DEST + ") | cat"
    rc, err = _run_policy(role, command)
    assert (rc, _policy_target(err)) == (2, DEST), (
        "escaped ;; before a real subshell not refused: %r" % command)


# ---- a comment that mentions case syntax ---------------------------------------------------------------
# A `#`-comment mentioning `case`/`esac`/`;;`/`;&`/`;;&` is dead to bash, so a real subshell after it
# is read as one. Bash runs the `cp` in all four commands below.
CASE_LEAD_COMMENT_ROWS = [
    "# case fake ;;\n(cp x " + DEST + ") | cat",
    "# case fake ;&\n(cp x " + DEST + ") | cat",
    "# case fake ;;&\n(cp x " + DEST + ") | cat",
    "case x in x) :;; esac\n# case ;;&\n(cp x " + DEST + ") | cat",
]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", CASE_LEAD_COMMENT_ROWS)
def test_tool_policy_case_lead_heuristic_ignores_comment_mentioning_case_syntax(role, command):
    """A `#`-comment mentioning case/esac/terminator-like text has no bearing on bash's parse; a
    real subshell right after it is refused."""
    rc, err = _run_policy(role, command)
    assert (rc, _policy_target(err)) == (2, DEST), (
        "comment-mentioned case/terminator text wrongly suppressed real-subshell detection: %r" % command)


CASE_LEAD_COMMAND_WORD_CONTROL_ROWS = [
    "echo case x in\n(cp x " + DEST + ") | cat",
    "printf case x in\n(cp x " + DEST + ") | cat",
]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", CASE_LEAD_COMMAND_WORD_CONTROL_ROWS)
def test_tool_policy_case_lead_heuristic_ignores_case_in_as_plain_arguments(role, command):
    """CONTROL. `case`/`in` as ordinary command arguments open no case statement."""
    rc, err = _run_policy(role, command)
    assert (rc, _policy_target(err)) == (2, DEST), (
        "case/in as plain arguments wrongly suppressed real-subshell detection: %r" % command)


# ---- an unmatched quote inside a comment -------------------------------------------------------------
# A quote character inside a `#`-comment (an apostrophe in "don't", an unterminated double quote) opens
# no quoted region: comment text is dead to bash. Bash runs the write in every row below.
UNMATCHED_QUOTE_COMMENT_ROWS = [
    "# don't do that\necho x > " + DEST,
    '# he said "watch out\necho x | tee ' + DEST,
    "# isn't obvious\nmv src " + DEST,
    '# he said "watch out\n(cp src ' + DEST + ") | cat",
]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", UNMATCHED_QUOTE_COMMENT_ROWS)
def test_tool_policy_unmatched_quote_in_comment_does_not_suppress_write_detection(role, command):
    """An unmatched quote character inside a `#`-comment (an apostrophe in prose, or an unterminated
    double quote) has no bearing on bash's parse; a real write later in the command is refused."""
    rc, err = _run_policy(role, command)
    assert (rc, _policy_target(err)) == (2, DEST), (
        "unmatched quote in comment wrongly suppressed real write detection: %r" % command)


@pytest.mark.parametrize("role", ROLES)
def test_tool_policy_matched_quote_pair_in_comment_still_detected(role):
    """CONTROL. A comment holding a matched quote pair (`"watch out"`) hides no write either."""
    command = '# he said "watch out"\ncp src ' + DEST
    rc, err = _run_policy(role, command)
    assert (rc, _policy_target(err)) == (2, DEST), (
        "CONTROL regressed: a matched quote pair inside a comment must still be detected: %r" % command)


# ---- consumer 2: the overnight guard, six decision functions ------------------------------------
@pytest.fixture(scope="module")
def overnight():
    sys.path.insert(0, str(HOOKS))
    spec = importlib.util.spec_from_file_location("overnight_guard_under_test", HOOKS / OVERNIGHT_HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    granted = "/granted-verbnarrow/x"
    module._grant_skips_block = lambda target: target == granted
    module.GRANTED_FOR_TEST = granted
    return module


WORKTREE = "/nonexistent-worktree-verbnarrow"
MAIN = str(PROJECT)
GIT = os.path.join(MAIN, ".git")


def _call(fn, *args):
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            return "returned", fn(*args), ""
    except SystemExit as exc:
        return "exit", exc.code, " ".join(err.getvalue().split())


def _assert_hook(module, hook_name):
    """The module under test is the intended consumer hook of the harness root under test."""
    assert Path(module.__file__).name == hook_name and Path(module.__file__).parent == HOOKS


def _bash_sites(module):
    return [
        (module._enforce_bash_all_sessions, lambda c: ("Bash", {"command": c}, [WORKTREE])),
        (module._enforce_bash_worktree, lambda c: (c, WORKTREE)),
        (module._check_bash_string, lambda c: ({"command": c}, WORKTREE)),
    ]


@pytest.mark.parametrize("command", REDIRECT_MARKING + [DOCUMENTED_MARKING] + LOOP_MARKING + CASE_MARKING)
def test_overnight_no_phantom_marking_not_blocked(overnight, command):
    _assert_hook(overnight, OVERNIGHT_HOOK)
    for fn, make in _bash_sites(overnight):
        kind, value, text = _call(fn, *make(command))
        assert kind == "returned", "%s blocked a command that writes nothing: %s" % (fn.__name__, text[-120:])


@pytest.mark.parametrize("command", BESIDE_REAL)
def test_overnight_no_phantom_beside_real_copy(overnight, command):
    _assert_hook(overnight, OVERNIGHT_HOOK)
    for fn, make in _bash_sites(overnight):
        kind, value, text = _call(fn, *make(command))
        assert (kind, value) == ("exit", 2) and DEST in text, "%s must name %s for %r: %s" % (fn.__name__, DEST, command, text[-120:])


@pytest.mark.parametrize("command", [M + " --cp-id cp-01 2>&1 | tail -5", "for cp in a b c; do echo $cp; done"])
def test_overnight_no_phantom_grant_and_worktree_local(overnight, command):
    _assert_hook(overnight, OVERNIGHT_HOOK)
    granted = overnight.GRANTED_FOR_TEST
    assert _call(overnight._all_bash_targets_granted, command + " > " + granted)[1] is True
    assert _call(overnight._command_is_worktree_local, command + " > " + granted, MAIN, WORKTREE, GIT)[1] is True
    assert _call(overnight._raw_git_metadata_write_into_main, command, MAIN, WORKTREE, GIT)[1] is False


@pytest.mark.parametrize(
    "command", REAL_PLAIN + REAL_CHECKPOINT_SOURCE + REAL_ABSOLUTE_QUOTED + REAL_EXPANSION_SPELLED + REAL_CASE_ARM)
def test_overnight_still_detected_real_copy_refused(overnight, command):
    _assert_hook(overnight, OVERNIGHT_HOOK)
    for fn, make in _bash_sites(overnight):
        kind, value, text = _call(fn, *make(command))
        assert (kind, value) == ("exit", 2) and DEST in text, "%s did not refuse %r" % (fn.__name__, command)


@pytest.mark.parametrize("command", ["cp src", "cp cp-01", "sudo /bin/cp cp-01", '"$CP" cp-01', "c$X -a cp-01", "mv src"])
def test_overnight_still_detected_main_checkout_and_git_metadata(overnight, command):
    _assert_hook(overnight, OVERNIGHT_HOOK)
    assert _call(overnight._command_is_worktree_local, command + " " + MAIN + "/x", MAIN, WORKTREE, GIT)[1] is False
    assert _call(overnight._raw_git_metadata_write_into_main, command + " " + GIT + "/HEAD", MAIN, WORKTREE, GIT)[1] is True


# ---- the two importers that never call the extractor: unaffected by any state of the library ------
def _extractor_calls(tree):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and (
        (isinstance(n.func, ast.Name) and n.func.id == "extract_bash_write_paths")
        or (isinstance(n.func, ast.Attribute) and n.func.attr == "extract_bash_write_paths"))]


def test_noncaller_unchanged_cp_state_write_guard_imports_no_bash_reader():
    source = (HOOKS / CP_STATE_GUARD_HOOK).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module
               and ("bash_write_targets" in n.module or "shell_parse" in n.module)]
    assert imports == [] and _extractor_calls(tree) == [], "the guard reads no Bash command"
    for command in REDIRECT_MARKING + [DOCUMENTED_MARKING, "cp src dest", "mv src " + DEST]:
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, "agent_type": "ba",
                   "agent_id": "abaverbnarrow", "session_id": "verbnarrow-sess"}
        proc = subprocess.run([sys.executable, str(HOOKS / CP_STATE_GUARD_HOOK)], input=json.dumps(payload),
                              capture_output=True, text=True, cwd=str(PROJECT), timeout=90)
        assert proc.returncode == 0, "the cp-state guard changed its Bash behaviour for %r" % command
    write = {"tool_name": "Write", "tool_input": {"file_path": str(PROJECT / ".claude" / "specs" / "S-vn" / "cp-state-ba.json"),
                                                    "content": "{}"}, "agent_type": "ba", "agent_id": "abaverbnarrow",
             "session_id": "verbnarrow-sess"}
    proc = subprocess.run([sys.executable, str(HOOKS / CP_STATE_GUARD_HOOK)], input=json.dumps(write),
                          capture_output=True, text=True, cwd=str(PROJECT), timeout=90)
    assert proc.returncode == 2, "a direct subagent write to a cp-state file must stay denied"


def test_noncaller_unchanged_wrapper_userintent_imports_only_the_heredoc_stripper():
    text = (HOOKS / USERINTENT_HOOK).read_text(encoding="utf-8")
    assert "extract_bash_write" not in text
    assert "from lib.shell_parse import without_heredoc_bodies" in text
    spec = importlib.util.spec_from_file_location("shell_parse_for_noncaller", HOOKS / "lib" / "shell_parse.py")
    lib = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lib)
    assert lib.without_heredoc_bodies("cat > /x <<EOF\nbody > /y\nEOF") == "cat > /x <<EOF"
    assert lib.without_heredoc_bodies("echo hi") == "echo hi"
