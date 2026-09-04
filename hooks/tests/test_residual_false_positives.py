#!/usr/bin/env python3
"""Residual-detector precision: string DATA must not be refused as git.

Context (task 20260903-residual-fp). `classify_git_command()` returns a
`residuals` channel that callers treat as fail-closed: a residual means "this
might be git and I could not parse it", so the caller REFUSES.  Two cooperating
defects made that channel fire on ordinary string DATA:

  (a) the `dynamic_git_token` branch checked only "token looks like an expansion"
      AND "next word is a git verb".  It did NOT apply the quote-balance /
      escaped-quote structural filter that the OBFUSCATION branch already
      applies via `_is_obfuscation_candidate()`.  An unbalanced quote is the
      signature of `.split()` cutting a multi-word string literal in half — the
      shell never execs that fragment.

  (b) `_segments_with_kind()` splits on newlines without tracking quote state,
      so a continuation line of a MULTI-LINE quoted literal becomes a "segment"
      whose first token reads as a command word.

The generalisation was wide because the git subcommand set is full of ordinary
English verbs (init status log config add clean help describe pull show grep).

These detectors are written to FAIL against the pre-fix classifier.  Each
`test_fp_*` asserts a false positive is gone; each `test_control_*` asserts a
GENUINE residual still fires — the fail-closed property is the point of the
mechanism and must not be traded away to buy precision.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from git_command_classifier import (  # noqa: E402
    classify_git_command,
)

NL = '\n'
# Built, not written literally: a `"""` inside this source would terminate the
# module docstring grammar.  This is the same hazard the fix is about — a quote
# run that an embedding language cannot carry inline.
TQ = '"' * 3


def residual_kinds(command_text):
    _invocations, residuals = classify_git_command(command_text)
    return [kind for kind, _seg in residuals]


# ---------------------------------------------------------------------------
# FALSE POSITIVES — legitimate traffic that must stop being refused
# ---------------------------------------------------------------------------


def test_fp_unbalanced_quote_data_followed_by_git_verb():
    """Instance 1, isolated to mechanism (a).

    A single-quoted multi-word literal split by `.split()` leaves the fragment
    `'$RUNNER` carrying ONE unbalanced quote.  The segment is NOT inside an open
    quote (the preceding segment balances), so ONLY the (a) shape filter can
    suppress this — it isolates (a) from (b).
    """
    command = "grep -c x f.txt" + NL + "'$RUNNER clean -n' > /dev/null"
    assert residual_kinds(command) == []


def test_fp_python_list_literal_continuation_line():
    """Instance 1 as it actually appeared: a heredoc'd Python list literal."""
    command = (
        "python3 - <<'PY'" + NL
        + "CMDS = [" + NL
        + '    "$RUNNER clean -n",' + NL
        + "]" + NL
        + "PY"
    )
    assert residual_kinds(command) == []


def test_fp_multiline_triple_quoted_literal_isolates_mechanism_b():
    """Isolates mechanism (b).

    The token `$RUNNER` has BALANCED quotes (it has none), so the (a) shape
    filter passes it through.  The only thing that distinguishes this line from
    a command is that the triple-quote run on the previous line (built as TQ,
    never written inline) left a quote OPEN across the newline.  If this test
    passes while (b) is unimplemented, the detector is not testing what it
    claims.
    """
    command = (
        "python3 - <<'PY'" + NL
        + 'CMDS = ' + TQ + NL
        + "$RUNNER status --short" + NL
        + TQ + NL
        + "PY"
    )
    assert residual_kinds(command) == []


def test_fp_json_payload_containing_a_git_command_string():
    """Instance 3, verbatim shape from corpus idx 26155.

    `.split()` cuts the JSON payload at the space inside `'git reset --hard'`,
    so the command token ends `...{'pattern':'git` (7 single quotes — odd) and
    the next word is `reset`.
    """
    command = (
        'GRANT="/tmp/x.json"' + NL
        + 'python3 -c "import json; '
        + "open('$GRANT','w').write(json.dumps("
        + "{'pattern':'git reset --hard','is_regex':False}))\""
    )
    assert residual_kinds(command) == []


def test_fp_variable_holding_non_git_script_path():
    """Instance 2, verbatim shape from corpus idx 4675.

    `$L init` IS a real command line — it is not quoted data, so neither (a)
    nor (b) can reach it.  But the command text ITSELF assigns L two lines
    earlier, so the token is not actually unknown: it resolves to `python3`.
    Suppression here is evidence-based resolution, not a relaxation.
    """
    command = (
        "cd /dev/shm/dev-workspace/dot-claude" + NL
        + 'L="python3 scripts/paseo-daemon-ledger.py --root .claude/paseo-daemon"' + NL
        + '$L init' + NL
        + '$L lease-status'
    )
    assert residual_kinds(command) == []


# ---------------------------------------------------------------------------
# NEGATIVE CONTROLS — genuine residuals that MUST still fire
# ---------------------------------------------------------------------------


def test_control_unresolved_variable_still_refused():
    """No assignment anywhere in the text — the token stays genuinely unknown."""
    assert residual_kinds("$GIT push --force") == ['dynamic_git_token']


def test_control_variable_resolving_to_git_still_refused():
    """The evasion the fail-closed branch exists for."""
    command = "G=git" + NL + "$G push --force"
    assert residual_kinds(command) == ['dynamic_git_token']


def test_control_split_variable_reassembling_to_git_still_refused():
    """`${G}it` reassembles to `git` — resolution must re-check the WHOLE token."""
    command = "G=g" + NL + "${G}it commit -m x"
    assert residual_kinds(command) == ['dynamic_git_token']


def test_control_reassigned_variable_still_refused():
    """Last-write-wins is unknowable statically; ANY git-valued assignment refuses."""
    command = "L=git" + NL + "L=echo" + NL + "$L status"
    assert residual_kinds(command) == ['dynamic_git_token']


def test_control_quoted_value_resolving_to_git_still_refused():
    command = 'G="/usr/bin/git"' + NL + "$G clean -fd"
    assert residual_kinds(command) == ['dynamic_git_token']


def test_control_obfuscated_token_still_refused():
    assert residual_kinds('g\\it push --force') == ['obfuscated_git_token']


def test_control_substituted_command_name_still_refused():
    assert residual_kinds('$(which git) push --force') == ['substituted_git_token']


def test_control_dynamic_token_after_closed_quote_still_refused():
    """(b) must key on quote state, not merely on 'is a later line'."""
    command = 'echo "hello"' + NL + "$GIT push --force"
    assert residual_kinds(command) == ['dynamic_git_token']


# ---------------------------------------------------------------------------
# ENUMERATION MONOTONICITY — the characteristic self-inflicted wound
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", [
    "git push --force",
    'echo "x"' + NL + "git clean -fd",
    'python3 - <<PY' + NL + 'S = ' + TQ + NL + "git push --force" + NL + TQ + NL + 'PY',
    "sudo /usr/bin/git -C /repo reset --hard",
    'echo $(git checkout -b nb)',
])
def test_enumeration_unchanged_by_precision_work(command):
    """Precision work on the RESIDUAL channel must not remove an ENUMERATION.

    The third case is deliberate: `git push --force` inside a multi-line quoted
    literal is enumerated today because the segmenter is quote-blind.  Making
    the segmenter quote-AWARE for splitting would silently drop it.  Mechanism
    (b) must therefore be a passive observer that annotates segments, never one
    that moves a split boundary.
    """
    invocations, _residuals = classify_git_command(command)
    assert invocations, "enumeration lost for: %r" % (command,)
