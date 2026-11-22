#!/usr/bin/env python3
"""Regression detectors for the shell-prefix enumeration defect (2026-09-03).

THE DEFECT
----------
`_command_token_index()` skipped only env-var assignments and bare command
wrappers. Every other construct the shell permits before a command word — the
reserved words (`if`, `then`, `else`, `do`, `while`, `until`, `!`, `{`), leading
redirections, and a wrapper's OWN option flags — resolved the command token to
the PREFIX instead of to `git`. `iter_git_invocations()` therefore yielded
nothing, and `pretool-git-privilege-guard.py::_evaluate_command()` returned at

    invocations = list(iter_git_invocations(command))
    if not invocations:
        return                      # <-- the whole guard, skipped

BEFORE the dispatch of every check it owns. The guard was a complete no-op for
`if ! git commit …` — which is this repository's own documented error-handling
idiom, present twice in the committed text of agents/changelog-analyst.md.

WHY THESE TESTS ARE SHAPED THIS WAY
-----------------------------------
A test that merely asserts "this command is blocked" can later pass for the
WRONG REASON — a different check firing, a coarse regex fallback, or a blanket
deny. Each test here asserts the two things that actually distinguish a working
enumerator from a no-op:

  1. the invocation was ENUMERATED (subcommand and args recovered), and
  2. the SPECIFIC dispatch ran — verified by recording which `_evaluate_*`
     function the guard called, not by matching stderr text.

Dispatch recording also makes the suite independent of live /tmp grant state:
no test here reads or writes a grant, a pointer, or any file under
/tmp/agentic-commit.

Run: python3 -m pytest hooks/tests/test_git_prefix_enumeration.py -q
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
GUARD_PATH = HOOKS / "pretool-git-privilege-guard.py"
CLASSIFIER_PATH = HOOKS / "lib" / "git_command_classifier.py"

sys.path.insert(0, str(HOOKS))

from lib.git_command_classifier import (  # noqa: E402
    _SHELL_PREFIX_KEYWORDS,
    _command_token_index,
    classify_git_command,
    iter_git_invocations,
)


def _load_guard():
    spec = importlib.util.spec_from_file_location("git_privilege_guard_uut", GUARD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GUARD = _load_guard()

DISPATCHERS = (
    "_evaluate_commit", "_evaluate_push", "_evaluate_reset_hard",
    "_evaluate_merge", "_evaluate_forbidden_plumbing",
    "_evaluate_direct_ref_mutation",
)


def dispatches(command):
    """Return the set of _evaluate_* dispatchers the guard invokes for `command`.

    Every dispatcher is replaced by a recorder, so the result depends ONLY on
    what the enumerator produced. The guard reads no /allow grant (the launcher
    releases a refused call), so no grant file can change the result.
    """
    called = set()
    saved = {name: getattr(GUARD, name) for name in DISPATCHERS}
    saved_block = GUARD._block
    blocked = []

    def recorder(name):
        return lambda *a, **k: called.add(name)

    try:
        for name in DISPATCHERS:
            setattr(GUARD, name, recorder(name))
        GUARD._block = lambda msg: blocked.append(msg)
        GUARD._evaluate_command(command, {"tool_name": "Bash",
                                          "tool_input": {"command": command}})
    finally:
        for name, fn in saved.items():
            setattr(GUARD, name, fn)
        GUARD._block = saved_block
    if blocked:
        called.add("_block")
    return called


# ---------------------------------------------------------------------------
# The eighteen forms. (id, command, expected subcommand, expected dispatcher)
# ---------------------------------------------------------------------------

FORMS = [
    ("F01-if-negated", "if ! git commit -m x; then echo no; fi", "commit", "_evaluate_commit"),
    ("F02-if-plain", "if git diff --quiet; then echo clean; fi", "diff", None),
    ("F03-while-negated", "while ! git push; do sleep 1; done", "push", "_evaluate_push"),
    ("F04-until", "until git fetch; do sleep 1; done", "fetch", None),
    ("F05-then-via-if", "if true; then git commit -m y; fi", "commit", "_evaluate_commit"),
    ("F06-else", "if false; then :; else git reset --hard HEAD~1; fi", "reset",
     "_evaluate_reset_hard"),
    ("F07-for-do", "for f in a; do git commit -m x; done", "commit", "_evaluate_commit"),
    ("F08-bang", "! git push --force", "push", "_evaluate_push"),
    ("F09-exec", "exec git commit -m z", "commit", "_evaluate_commit"),
    ("F10-eval", "eval git push", "push", "_evaluate_push"),
    ("F11-env-i", "env -i git commit -m q", "commit", "_evaluate_commit"),
    ("F12-redirection", "2>/dev/null git push", "push", "_evaluate_push"),
    ("F13-if-test-then", "if [ -f x ]; then git commit -m y; fi", "commit", "_evaluate_commit"),
    ("F14-then", "then git commit -m a", "commit", "_evaluate_commit"),
    ("F15-else-bare", "else git commit -m b", "commit", "_evaluate_commit"),
    ("F16-do-bare", "do git commit -m c", "commit", "_evaluate_commit"),
    ("F17-while-commit", "while ! git commit -m d; do sleep 1; done", "commit",
     "_evaluate_commit"),
    ("F18-until-commit", "until git commit -m e; do sleep 1; done", "commit",
     "_evaluate_commit"),
]


@pytest.mark.parametrize("cid,command,subcommand,dispatcher", FORMS,
                         ids=[f[0] for f in FORMS])
def test_prefix_form_is_enumerated(cid, command, subcommand, dispatcher):
    """DETECTOR 1: the invocation is actually ENUMERATED, not merely blocked.

    Asserting only "the guard blocks this" would keep passing if the enumerator
    regressed and some coarser mechanism started denying instead.
    """
    invocations = list(iter_git_invocations(command))
    assert invocations, (
        f"{cid}: iter_git_invocations({command!r}) yielded NOTHING. This is the exact "
        f"2026-09-03 defect: a shell prefix resolved the command token away from `git`, "
        f"so every guard built on this enumerator becomes a no-op for this form."
    )
    assert subcommand in [inv.subcommand for inv in invocations], (
        f"{cid}: expected subcommand {subcommand!r}, got "
        f"{[i.subcommand for i in invocations]!r}"
    )


@pytest.mark.parametrize("cid,command,subcommand,dispatcher", FORMS,
                         ids=[f[0] for f in FORMS])
def test_prefix_form_reaches_its_specific_dispatch(cid, command, subcommand, dispatcher):
    """DETECTOR 2: the SPECIFIC check runs — named, not inferred from a verdict.

    `dispatcher is None` means the form carries a read-only subcommand that the
    guard deliberately permits (`git diff`, `git fetch`). Those must reach
    dispatch and be judged on their merits, i.e. NO dispatcher fires and the
    command is not blocked. That is a real assertion: a guard that blanket-denied
    every newly-visible invocation would fail it.
    """
    called = dispatches(command)
    if dispatcher is None:
        assert called == set(), (
            f"{cid}: a read-only git invocation must reach dispatch and be ALLOWED, "
            f"but these fired: {sorted(called)}"
        )
    else:
        assert dispatcher in called, (
            f"{cid}: expected {dispatcher} to run for {command!r}; dispatchers that "
            f"actually ran: {sorted(called) or 'NONE — the guard was a no-op'}"
        )


def test_every_check_the_guard_owns_is_reachable_behind_a_keyword():
    """DETECTOR 3: the amplification is closed for EVERY check, not just commit.

    The defect skipped the whole dispatch block, so each check must be shown
    reachable behind a prefix independently.
    """
    expected = {
        "if ! git reset --hard HEAD~3; then :; fi": "_evaluate_reset_hard",
        "if ! git merge origin/main; then :; fi": "_evaluate_merge",
        "then git rebase -i HEAD~2": "_evaluate_forbidden_plumbing",
        "do git update-ref refs/heads/m HEAD": "_evaluate_direct_ref_mutation",
        "! git push --force": "_evaluate_push",
        "while ! git commit -m x; do :; done": "_evaluate_commit",
    }
    for command, dispatcher in expected.items():
        called = dispatches(command)
        assert dispatcher in called, (
            f"{command!r} did not reach {dispatcher}; ran: {sorted(called) or 'NONE'}"
        )


def test_empty_invocation_list_is_not_silently_equivalent_to_no_git():
    """DETECTOR 4: the shape of the defect itself must not survive.

    A git-shaped command the parser cannot resolve must be refused, not dropped
    through the early return.
    """
    # OB-L26: `g\\it commit` is read as the git commit it runs, so it is no residual.
    for command in ("${G}it commit -m x", "$GIT commit -m x", "$(which git) push --force"):
        invocations, residuals = classify_git_command(command)
        assert not invocations, f"{command!r} unexpectedly parsed cleanly"
        assert residuals, (
            f"{command!r} produced NO invocation AND NO residual — that is the exact "
            f"'empty list means no git here' equivalence this fix removed"
        )
        assert "_block" in dispatches(command), (
            f"{command!r} raised a residual but the guard did not refuse it"
        )


def test_git_free_traffic_stays_fast_and_permissive():
    """DETECTOR 5: the fail-closed branch must NOT become a blanket deny.

    This guard sees EVERY Bash call in the harness. Measured against 71,598
    unique real commands from the harness transcripts, the residual branch fired
    on 2 (0.003%). These shapes are the common ones and must stay silent.
    """
    for command in (
        "echo hello world",
        "grep -rn git .",
        "echo 'git status'",
        'echo "if ! git commit -m x; then"',
        "cat git.md",
        "gitk --all",
        "for git in a b; do echo $git; done",
        'grep -n "ls-files\\|git\\|tracked" f.py',
        "ls -la /usr/bin/git",
        "docker run --rm alpine/git status",
    ):
        invocations, residuals = classify_git_command(command)
        assert not invocations, f"{command!r} must not enumerate a git invocation"
        assert not residuals, (
            f"{command!r} raised residual {residuals!r}; the fail-closed branch would "
            f"hard-block ordinary traffic"
        )
        assert dispatches(command) == set(), f"{command!r} must reach no dispatcher"


def test_prefix_keyword_set_excludes_words_that_introduce_a_name():
    """DETECTOR 6: the skip set is curated, not 'skip any leading word'.

    `for git in a b` binds a loop VARIABLE named git and runs nothing. If these
    words were skipped, the guard would manufacture invocations out of them.
    """
    for word in ("for", "select", "case", "in", "function", "done", "fi", "esac"):
        assert word not in _SHELL_PREFIX_KEYWORDS, (
            f"{word!r} must NOT be a skippable prefix: the token after it is a NAME or "
            f"a construct terminator, never a command word"
        )
    assert _command_token_index("for git in a b".split()) == 0
    assert not list(iter_git_invocations("for git in a b; do echo hi; done"))


def test_guard_source_still_routes_through_the_residual_aware_entry_point():
    """DETECTOR 7: a silent revert to the old early return must fail LOUDLY.

    Behavioural tests above can all be satisfied by a future refactor that
    reinstates `if not invocations: return` ahead of the residual check. This
    asserts the source shape directly, because that regression is exactly the
    one that recurred here.
    """
    src = GUARD_PATH.read_text(encoding="utf8")
    body = src[src.index("def _evaluate_command("):]
    body = body[:body.index("\ndef ")]

    assert "classify_git_command(" in body, (
        "_evaluate_command() no longer calls classify_git_command(); an empty "
        "invocation list is once again indistinguishable from 'no git here'"
    )
    residual_pos = body.index("if residuals:")
    early_return = re.search(r"if not invocations:\s*\n\s*return", body)
    assert early_return is not None, "expected the git-free fast path to still exist"
    assert residual_pos < early_return.start(), (
        "the empty-invocation early return sits BEFORE the residual check, so a "
        "git-shaped-but-unparseable command falls through it again — this is the "
        "original defect, reintroduced"
    )


@pytest.mark.parametrize("command", [
    "env -u FOO git push", "nice -n 5 git push", "timeout 30 git push",
    "2>/dev/null git push", "2> /dev/null git push",
    "if ! git push; then :; fi", "while git push; do :; done",
])
def test_classifier_reads_the_closed_boundaries(command):
    """DETECTOR 8: wrapper flags, redirections and reserved words before git stay closed."""
    assert [inv.subcommand for inv in iter_git_invocations(command)] == ["push"]


# ---------------------------------------------------------------------------
# The classifier normalises its own input, and one git global-option table
# serves every git-reading hook (P9 R6).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    'echo "tip; git commit -m x"',
    'echo "git commit"',
    "echo 'tip; git push --force'",
    'printf \'%s\\n\' "x; git commit -n"',
])
def test_quoted_text_is_not_an_invocation(command):
    assert list(iter_git_invocations(command)) == []
    assert dispatches(command) == set()


@pytest.mark.parametrize("command,dispatcher", [
    ('bash -c "cd x; git commit -m y"', "_evaluate_commit"),
    ('timeout 5 bash -c "cd x; git commit -m y"', "_evaluate_commit"),
    ('echo "$(git commit -m x)"', "_evaluate_commit"),
    ('echo "$(echo " \'$(git commit -n)\' ")"', "_evaluate_commit"),
    ("# don't\ngit commit -m x", "_evaluate_commit"),
    ('env -i "git" commit -m x', "_evaluate_commit"),
])
def test_code_in_or_beside_a_quote_is_still_an_invocation(command, dispatcher):
    assert dispatcher in dispatches(command)


def test_a_quoted_message_hides_no_second_invocation():
    command = 'git commit -m "fix; git push --force"'
    assert [inv.subcommand for inv in iter_git_invocations(command)] == ["commit"]
    assert dispatches(command) == {"_evaluate_commit"}


def test_invocation_keeps_its_tokens_as_written():
    (inv,) = iter_git_invocations('git -C "/r" commit -F "/tmp/m.txt"')
    assert inv.args == ["-F", '"/tmp/m.txt"']


@pytest.mark.parametrize("options", [
    "--exec-path", "--exec-path=/x", "--attr-source HEAD", "--attr-source=HEAD",
    "--config-env x=y", "--config-env=x=y", "--shallow-file f", "-C /r", "-c a=b",
])
def test_option_table_finds_the_subcommand(options):
    (inv,) = iter_git_invocations("git %s commit -m x" % options)
    assert inv.subcommand == "commit"


def test_guard_commit_reader_skips_the_option_table():
    (rec,) = GUARD._commit_records("git --attr-source HEAD -C /o commit -m x")
    assert rec["dirs"] == ["/o"] and rec["args"] == ["-m", "x"]


# ---------------------------------------------------------------------------
# A quoted git invocation is text only under a command known to leave its
# arguments unexecuted; a launcher's payload is code, and an unknown launcher
# fails closed (P9, PR #16 review comment 6716077369, finding 1).
# ---------------------------------------------------------------------------

LAUNCHED = [
    ("python3 -c \"import os; os.system('cd x; git push origin HEAD:main')\"", "push",
     "agent git push"),
    ('su -c "cd x; git commit -m y"', "commit", "agent git commit"),
    ('echo "cd x; git commit -m y" | sh', "commit", "agent git commit"),
    ("find . -exec sh -c 'cd x; git commit -m y' \\;", "commit", "agent git commit"),
]
QUOTED_TEXT = ['echo "tip; git commit -m x"', 'printf \'%s\\n\' "x; git commit -n"']


@pytest.mark.parametrize("command,subcommand,_reason", LAUNCHED)
def test_a_launched_payload_is_an_invocation(command, subcommand, _reason):
    assert [inv.subcommand for inv in iter_git_invocations(command)] == [subcommand]


@pytest.mark.parametrize("command,subcommands", [
    ('eval echo "x; git commit -m y"', ["commit"]),
    ('{ echo "x; git commit -m y"; } | sh', ["commit"]),
    ('echo "x; git commit -m y" |& sh', ["commit"]),
    ('echo "x; git commit -m y" | xargs -I{} sh -c {}', ["commit"]),
    ('ssh host "cd x; git push origin main"', ["push"]),
    ('xargs sh -c "cd x; git push origin main"', ["push"]),
    ('git -c core.editor=vi commit -m "a; git push origin main"', ["commit"]),
    ('echo "x; git commit -m y" | grep x', []),
    ('grep -e "a; git push" notes.md', []),
    ('git -C "/r" commit -m "a; git push"', ["commit"]),
])
def test_only_a_known_text_command_makes_quoted_git_text(command, subcommands):
    assert [inv.subcommand for inv in iter_git_invocations(command)] == subcommands


@pytest.fixture(scope="module")
def guard_env(tmp_path_factory):
    """A scratch HOME, state dir and repository: the real ~/.claude is never read."""
    base = tmp_path_factory.mktemp("guard-launch")
    repo = base / "repo"
    for path in (repo, base / "home", base / "state"):
        path.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_"))}
    env.update(HOME=str(base / "home"), CLAUDE_STATE_DIR=str(base / "state"),
               CLAUDE_PROJECT_DIR=str(repo), PYTHONDONTWRITEBYTECODE="1")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "init"],
                   cwd=repo, env=env, check=True)
    transcript = base / "transcript.jsonl"
    transcript.write_text("")
    return repo, transcript, env


def _run_guard(command, agent, guard_env):
    repo, transcript, env = guard_env
    payload = {"session_id": "p9-launch-test-0001", "cwd": str(repo),
               "transcript_path": str(transcript), "hook_event_name": "PreToolUse",
               "permission_mode": "default", "tool_name": "Bash",
               "tool_input": {"command": command}}
    if agent == "subagent":
        payload.update(agent_id="agent-p9-launch-0001", agent_type="general-purpose")
    return subprocess.run([sys.executable, str(GUARD_PATH)], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=repo, env=env, timeout=120)


@pytest.mark.parametrize("agent", ["main", "subagent"])
@pytest.mark.parametrize("command,_subcommand,reason", LAUNCHED)
def test_the_guard_blocks_a_launched_git_command(command, _subcommand, reason, agent, guard_env):
    proc = _run_guard(command, agent, guard_env)
    assert proc.returncode == 2 and reason in proc.stderr, (proc.returncode, proc.stderr)


@pytest.mark.parametrize("agent", ["main", "subagent"])
@pytest.mark.parametrize("command", QUOTED_TEXT)
def test_the_guard_passes_quoted_text(command, agent, guard_env):
    proc = _run_guard(command, agent, guard_env)
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
