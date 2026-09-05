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
import re
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

    Every dispatcher is replaced by a recorder and `_check_git_allowlist` is
    pinned False, so the result depends ONLY on what the enumerator produced —
    never on grant files, sentinels, or any other machine state.
    """
    called = set()
    saved = {name: getattr(GUARD, name) for name in DISPATCHERS}
    saved_allow = GUARD._check_git_allowlist
    saved_block = GUARD._block
    blocked = []

    def recorder(name):
        return lambda *a, **k: called.add(name)

    try:
        for name in DISPATCHERS:
            setattr(GUARD, name, recorder(name))
        GUARD._check_git_allowlist = lambda c, d: False
        GUARD._block = lambda msg: blocked.append(msg)
        GUARD._evaluate_command(command, {"tool_name": "Bash",
                                          "tool_input": {"command": command}})
    finally:
        for name, fn in saved.items():
            setattr(GUARD, name, fn)
        GUARD._check_git_allowlist = saved_allow
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
    for command in ("g\\it commit -m x", "$GIT commit -m x", "$(which git) push --force"):
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


# ---------------------------------------------------------------------------
# Adjacent finding, same guard, same fail-closed class (2026-09-03).
# Not part of the enumeration defect; included here because it is the same
# "a falsy-looking value was never actually falsy" mistake.
# ---------------------------------------------------------------------------

def test_repo_use_witness_treats_a_zero_reflog_count_as_unreadable():
    """`entries == '0'` is reflogs-disabled, not a reading of zero.

    `not '0'` is False in Python, so the old guard let a reflog-less repo produce
    the witness `<sha>:0`. That value is CONSTANT — it cannot rise on commit,
    reset or amend — so `_grant_use_permitted()` would find recorded == current
    forever and re-authorize an already-spent grant up to the attempt cap,
    instead of taking the fail-closed branch its docstring promises.

    Verified against a real bare clone (core.logAllRefUpdates unset):
    `git rev-list --walk-reflogs --count HEAD` prints exactly `0`.
    """
    saved = GUARD._commit_target_git_output
    try:
        GUARD._commit_target_git_output = lambda repo, *a: (
            "deadbeef" if a[0] == "rev-parse" else "0")
        assert GUARD._repo_use_witness("/some/repo") == "", (
            "a reflog count of '0' must yield the empty witness so the caller "
            "fails closed; returning 'deadbeef:0' silently re-arms a spent grant"
        )
        GUARD._commit_target_git_output = lambda repo, *a: (
            "deadbeef" if a[0] == "rev-parse" else "7")
        assert GUARD._repo_use_witness("/some/repo") == "deadbeef:7", (
            "a real reflog count must still produce a witness — the fix must not "
            "break the ordinary path"
        )
    finally:
        GUARD._commit_target_git_output = saved


def test_classifier_documents_the_closed_boundaries():
    """DETECTOR 8: the module may not re-publish the closed gaps as accepted."""
    src = CLASSIFIER_PATH.read_text(encoding="utf8")
    head = src[:src.index("import collections")]
    assert "CLOSED" in head, (
        "the arch-F7 scope-boundary note must record that the wrapper-flag, "
        "redirection and reserved-word gaps are closed; leaving them published as "
        "accepted limitations is how this defect survived twenty-four cycles"
    )
