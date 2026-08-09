"""Decision-table unit tests for hooks/lib/git_clean_guard.py.

The pre-clean WIP snapshot guard (task dev-20260719-150041-c, lane r03-c) is
fail-closed: a destructive `git clean` may only proceed through a human-grant
exit after write_checkpoint succeeded, and ONLY when the clean's target is
provably the hook's own working directory.

These vectors pin the two directions that matter:
  * SNAPSHOT must never be returned for a redirected or indeterminate clean
    (that would snapshot the wrong tree and then allow the deletion).
  * NONE must never be returned for a clean that actually deletes (that would
    let a granted clean through with no snapshot at all).

Regression anchor: `git clean -fd -e -n` DELETES — `-e` consumes the following
token as its exclude pattern, so the trailing `-n` is a pattern, not a dry run.
An earlier revision of the detector read that `-n` as a dry run and returned
NONE, silently skipping the snapshot on a destructive clean.

Two further anchors, both found by adversarial review AFTER every acceptance
criterion passed (the criterion set had the same blind spot the code did):
  * CX-1 `git clean -n --no-dry-run -fd` DELETES — git applies the dry-run flag
    and its generated negation last-wins, so a first-match scan returned NONE
    and a GRANTED destructive clean reached exit 0 with no snapshot.
  * CX-4 `env -C <dir> git clean -fd` runs the clean in another tree — the
    shared tokenizer stops at the wrapper's own option, so the git invocation
    was invisible and the clean was allowed under a grant, unsnapshotted.
"""

import pathlib
import shlex
import sys

import pytest

_HOOKS_LIB = pathlib.Path(__file__).resolve().parents[1] / "hooks" / "lib"
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

from git_clean_guard import decide  # noqa: E402


def _nest(payload, depth):
    """`sh -c '...'` nested `depth` deep, quoted by shlex so the vector is a
    real shell equivalent. A hand-rolled nester produces strings bash does NOT
    reduce to a clean, and a vector built that way pins a quoting mistake."""
    for _ in range(depth):
        payload = "sh -c " + shlex.quote(payload)
    return payload


SNAPSHOT_CASES = [
    "git clean -fd",
    "git clean -df",
    "git clean -d -f",
    "git clean -fdx",
    '"/usr/bin/git" clean -fd',
    "/usr/bin/git clean -fd",
    "env git clean -fd",
    "sudo git clean -fd",
    # -c is CONFIG, not the -C chdir redirect.
    "git -c clean.requireForce=false clean -d",
    # `-e` swallows the next token: these all still delete.
    "git clean -fd -e -n",
    "git clean -fd --exclude -n",
    "git clean -fde build",
    "git clean -fd --exclude=build",
    # CX-1: the dry-run flag is LAST-WINS, so a later negation re-arms deletion.
    "git clean -n --no-dry-run -fd",
    "git clean --dry-run --no-dry-run -fd",
    "git clean -nd --no-dry-run -f",
    # ...and git accepts any unambiguous ABBREVIATION of that negation.
    "git clean -n --no-dry -fd",
    "git clean -n --no-d -fd",
    "git clean --dry-run --no-dry-r -fd",
    # An abbreviated exclude swallows the following token exactly like `-e`,
    # so the trailing -n is its pattern and the clean still deletes.
    "git clean -fd --exc -n",
    "git clean -fd --exclud -n",
    # A non-redirecting env ASSIGNMENT through a wrapper is still the hook cwd.
    "env FOO=bar git clean -fd",
    # Lexical dress must not buy an exemption: the negation survives quoting and
    # backslash escaping, and the bounded normalizer erasing quoted content must
    # not lose it either (both parses are unioned fail-closed).
    'git clean -n "--no-dry-run" -fd',
    r"git clean -n --no-dry\-run -fd",
    r"git clean -f --no-dry-run \-- -n",
    # `--` before any flag means the following -n is a PATHSPEC, not a dry run.
    "git clean -- -n",
    # A wrapper option TERMINATOR leaves the cwd alone, so this is provable.
    "env -- git clean -fd",
    # Deliberate asymmetry: an unrecognised POSITIVE spelling reads as
    # destructive. `--dry` is a real dry run, so this snapshot is superfluous —
    # that is the safe direction and is preferred over risking a wrong exemption.
    "git clean --dry",
]

NONE_CASES = [
    "git clean -n",
    "git clean --dry-run",
    "git clean -nd",
    "git clean -n --exclude=build",
    "git config --get clean.requireForce",
    "git status",
    "npm run clean",
    "echo nothing to do here",
    # Last-wins in the other direction: the trailing -n IS the effective flag.
    "git clean --no-dry-run -n",
    "git clean --no-dry -n",
    # An abbreviated exclude in `=` form consumes nothing, so -n still applies.
    "git clean -n --exc=build",
    # A pathspec after `--` cannot un-dry a dry run.
    "git clean -n -- -fd",
    # A redirected clean that deletes nothing needs neither snapshot nor deny.
    "env -C /tmp/B git clean -n",
    # A wrapper option on a NON-git command must not be read as a clean at all.
    "env -C /tmp/B ls -la",
]

DENY_CASES = [
    # Target-redirecting globals (presence only — never resolved).
    "git -C /tmp/B clean -fd",
    "git -C/tmp/B clean -fd",
    "/usr/bin/git -C /tmp/B clean -fd",
    "git --git-dir=/tmp/B/.git --work-tree=/tmp/B clean -fd",
    "git --work-tree /tmp/B clean -fd",
    "git -C /tmp/A -C /tmp/B clean -fd",
    "git -c core.worktree=/tmp/B clean -fd",
    "GIT_WORK_TREE=/tmp/B git clean -fd",
    "GIT_DIR=/tmp/B/.git git clean -fd",
    "export GIT_DIR=/tmp/B/.git && git clean -fd",
    # Indeterminate effective cwd.
    "cd /tmp/B && git clean -fd",
    "( cd /tmp/B && git clean -fd )",
    "echo $(git clean -fd)",
    "pushd /tmp/B && git clean -fd",
    # One redirected clean in a multi-clean payload poisons the whole command.
    "git clean -fd && git -C /tmp/B clean -fd",
    # CX-4: a cwd-changing WRAPPER option before the git binary. The shared
    # tokenizer stops at the option, so these were invisible and snapshot-free.
    "env -C /tmp/B git clean -fd",
    "env -C/tmp/B git clean -fd",
    "env --chdir=/tmp/B git clean -fd",
    "env --chdir /tmp/B git clean -fd",
    "env -C /tmp/B git clean -n --no-dry-run -fd",
    # Generalisation of the same rule: a wrapper option this module does not
    # model cannot be proven NOT to move the cwd, so it denies rather than
    # snapshotting a tree that may not be the one being cleaned.
    "sudo -u root git clean -fd",
    # The wrapper's own OPERAND can itself basename to git (a git service
    # account), so the region is re-scanned from every candidate, not the first.
    "sudo -u git git clean -fd",
    "env -u GIT_DIR git clean -fd",
    "env -C /tmp/git git clean -fd",
    # Quoted wrapper words: bash strips these before exec, so the wrapper, its
    # option and the git token must all be seen through their punctuation.
    '"/usr/bin/env" -C /tmp/B git clean -fd',
    'env "-C" /tmp/B git clean -fd',
    'env -C /tmp/B "git" clean -fd',
    # A wrapper option can carry the whole command in its VALUE.
    "env -S 'git clean -fd'",
    "env --split-string='git clean -fd'",
    # Substitution in the flag region: the effective flags are unprovable, so
    # the dry-run exemption cannot be granted.
    "git clean -n $(printf -- --no-dry-run) -fd",
    # A nested wrapper AFTER an option terminator still gets analysed.
    "env -- env -C /tmp/B git clean -fd",
    # ACCEPTED over-block, pinned so the posture stays deliberate: argument text
    # that looks like a clean denies, because telling it apart from a wrapper
    # operand that IS the git binary needs a per-wrapper operand table, and
    # being wrong there re-opens `sudo -u git git clean -fd`.
    "sudo -u root echo git clean -fd",
]


# ---------------------------------------------------------------------------
# Iteration-5 vectors: every spelling QA measured reaching a grant exit with a
# destructive clean and NO snapshot. Named individually so a regression names
# the class it reopened rather than just incrementing a failure count.
# ---------------------------------------------------------------------------

# Unmodelled wrapper NAMES. The previous revision only stepped over the 12 names
# in the shared `_WRAPPERS` set; anything else made the clean invisible. These
# must DENY - the prefix cannot be proven inert, so the target cannot be proven.
QA5_UNMODELLED_PREFIX_DENY = [
    "timeout 60 git clean -fd",
    "flock /tmp/x git clean -fd",
    "chrt -b 0 git clean -fd",
    "strace -f git clean -fd",
    "bash -c 'git clean -fd'",
    "sh -c 'git clean -fd'",
    # One unmodelled word in front also reopened the CX-4 redirect.
    "timeout 60 env -C /tmp/other git clean -fd",
    # Names that exist nowhere in this codebase: the point is that membership of
    # any list must stop deciding visibility.
    "qqzzx git clean -fd",
    "./wrapper.sh git clean -fd",
    "/opt/tools/run git clean -fd",
]

# Quote/backslash splices of the command word. These run a clean in the hook's
# OWN cwd, so the correct verdict is SNAPSHOT: they used to be invisible only
# because a raw-text substring prefilter sat in front of the detector.
QA5_SPLICED_SNAPSHOT = [
    "g''it clean -fd",
    'g""it clean -fd',
    "git cl''ean -fd",
    r"g\it clean -fd",
    r"git cl\ean -fd",
    "git $'clean' -fd",
    "git \\\nclean -fd",
    # The CX-1 negation fragmented across a quote boundary: a per-token unquote
    # cannot rejoin the fragments, so the -n exemption wrongly survived.
    'git clean -n --no-""dry-run -fd',
    # Shell grammar the previous revision did not model at all.
    ">hook.log git clean -fd",
    "2>/dev/null git clean -fd",
    "! git clean -fd",
    "{ git clean -fd; }",
]

# Allow-with-wrong-snapshot: these used to snapshot tree A, print the success
# message, and allow a clean of tree B. Worse in kind than no guard, because the
# operator is told the work is recoverable when the deleted tree was never
# snapshotted.
QA5_WRONG_TREE_DENY = [
    "! cd /tmp/other || git clean -fd",
    "command -- cd /tmp/other && git clean -fd",
    "time -p cd /tmp/other && git clean -fd",
    "git --work-'tree'=/tmp/other clean -fd",
    'git --work-"tree"=/tmp/other clean -fd',
]

# The inversion must not become a blunt instrument.
QA5_STILL_EXEMPT = [
    "git config --get clean.requireForce",
    "make clean",
    "npm run clean",
    "git clean -n",
    "git clean --no-dry-run -n",
    "cd /tmp && ls",
    "timeout 60 python3 script.py",
]


# ---------------------------------------------------------------------------
# Iteration-6 vectors. Three classes QA measured reaching a grant exit with a
# destructive clean and NO snapshot, each execution-proved before being
# believed. All three are the same structural pattern the inversion was meant to
# remove - "cannot statically reduce it, therefore allow" - surviving in the
# three places the inversion did not reach.
# ---------------------------------------------------------------------------

# (1) A FUSED short option carrying the payload. The spaced and --split-string=
# spellings already denied; only the fused one re-parsed to the command word
# `-Sgit`, which is neither inert nor a git basename, so the clean vanished.
QA6_FUSED_OPTION_DENY = [
    "env -S'git clean -fd'",
    "env -vS'git clean -fd'",
    "env -iS'git clean -fd'",
    "env -u FOO -S'git clean -fd'",
    "env -Sgit clean -fd",
    "env -S'/usr/bin/git clean -fd'",
    "env -S'sh -c \"git clean -fd\"'",
    # ...and the same option's OWN separator escapes, which contain no shell
    # whitespace whatsoever. Found by adversarial review AFTER the fix above was
    # green, using this lane's own shell oracle: `env -S` splits on `\_`, so bash
    # hands over ONE word, "is this multi-word?" answered no, and the payload was
    # invisible. This is the counter-example to "only the first token can hide a
    # command word" - true of shell words, false before env re-splits them.
    r"env -S'git\_clean\_-fd'",
    r"env -vS'git\_clean\_-fd'",
    r"env -S'FOO=1\_git\_clean\_-fd'",
    r"env --split-string='git\_clean\_-fd'",
    r"env -S'git\tclean\t-fd'",
]

# The counter-direction for the same escape family: a PROVEN dry run written
# with env's separators must stay exempt, or the fix above is just a blanket
# denial of every backslash-bearing option word.
QA6_ENV_S_ESCAPE_STILL_EXEMPT = [
    r"env -S'git\_clean\_-n'",
    r"env -S'git\_status'",
    r"env -S'echo\_hello\_world'",
]

# (2) Recursion TRUNCATION. Depths 1-3 denied; the fourth `continue`d past the
# budget, which is indistinguishable from "this region holds no clean". The
# limit now denies, so the verdict is monotone in depth rather than flipping.
QA6_NESTED_PAYLOAD_DENY = [
    _nest("git clean -fd", depth) for depth in range(1, 10)
] + [
    # one more wrapper also used to re-open a target redirect
    _nest("env -C /tmp/other git clean -fd", 4),
    # ...and the budget must deny even when the payload is harmless, because at
    # truncation the module does not KNOW that it is harmless
    _nest("echo harmless", 8),
]

# (3) Argument text behind a GIT command word. `_git_invocation` returned early
# on any non-clean subcommand, so the region scan never inspected the arguments
# of a git command - while `git rebase -x` runs them, in the hook's own tree.
# This was the sharpest of the three: an ordinary developer command that
# destroys the incident file with neither deny nor snapshot.
QA6_GIT_ARGUMENT_DENY = [
    "git rebase -x 'git clean -fd' HEAD~1",
    "git rebase --exec 'git clean -fd' HEAD~1",
    "git rebase --exec='git clean -fd' HEAD~1",
    "git bisect run git clean -fd",
    "git submodule foreach 'git clean -fd'",
    "git filter-branch --tree-filter 'git clean -fd' HEAD",
]

# The consistency this buys, pinned as an EQUALITY rather than as two verdicts:
# the same text must be classified the same way wherever it sits. The old
# asymmetry (`echo '<clean>'` denies, `git commit -m '<clean>'` passes) was not
# a policy, it was the third fail-open wearing a policy's clothes.
QA6_SAME_TEXT_SAME_VERDICT = [
    ("echo 'git clean -fd'", "git commit -m 'git clean -fd'"),
    ("echo 'git clean -fd'", "git log --grep='git clean -fd'"),
]

# ---------------------------------------------------------------------------
# ITERATION 7 — the two carrier families QA measured live under a real grant
# after iteration 6 was green. These are the FAST detector-level pins; AC21
# carries the generated cross-product and the hook-level, four-channel,
# checkpoint-identity proof. Both layers are kept deliberately: if the oracle's
# environment ever breaks, AC21 errors loudly rather than silently narrowing,
# and these vectors still hold the line in milliseconds.
# ---------------------------------------------------------------------------

# (A) A payload delivered on STDIN. `_lex` marked the word after ANY redirection
# operator as a redirection target and `_split_segments` dropped it — right for a
# FILE operand, wrong for a here-string, whose operand is stdin CONTENT and is a
# script whenever its reader executes stdin. The command then reduced to nothing
# at all and a granted clean ran unsnapshotted. The heredoc form of the same
# thing already snapshotted, because its newline split the body into its own
# segment; one spelling of a family handled and its sibling not is what marks
# this a lexer-coverage gap rather than a policy. Note the reader is NOT
# enumerated anywhere in the fix: `xargs` and the read/eval loop below execute
# their stdin too, and both deny for the same structural reason.
QA7_STDIN_PAYLOAD_DENY = [
    "bash <<< 'git clean -fd'",
    "bash <<<'git clean -fd'",
    'bash <<< "git clean -fd"',
    "bash -s <<< 'git clean -fd'",
    "bash -e <<< 'git clean -fd'",
    "bash <<< $'git clean -fd'",
    "sh <<< 'git clean -fd'",
    "sh -s <<< 'git clean -fd'",
    ". /dev/stdin <<< 'git clean -fd'",
    "bash 0<<< 'git clean -fd'",
    "bash <<< 'git clean -fd' > out.log",
    "bash > out.log <<< 'git clean -fd'",
    "xargs <<< 'git clean -fd'",
    "while read -r l; do eval \"$l\"; done <<< 'git clean -fd'",
    "sh -c 'bash <<< \"git clean -fd\"'",
]

# The counter-direction: stdin content that destroys nothing must stay exempt,
# or retaining the operand is just a blanket denial of every here-string.
QA7_STDIN_PAYLOAD_STILL_EXEMPT = [
    "bash <<< 'echo hi'",
    "sh <<< 'ls -la'",
    "cat <<'EOS'\nhello\nEOS",
    "bash <<'EOS'\ngit status\nEOS",
    "wc -l < file.txt",
]

# And the reason the operand becomes its OWN segment rather than an extra word
# of the command it feeds: git ignores its stdin, so these really DELETE. Folded
# into the flag region, that `-n` would read as a proven dry run and strip the
# snapshot — trading one fail-open for another.
QA7_STDIN_IS_NOT_AN_ARGUMENT_SNAPSHOT = [
    "git clean -fd <<< '-n'",
    "git clean -fd <<< '--dry-run'",
    "git clean -fd <<< 'anything at all'",
]

# (B) env's own separator escapes across the FULL {joined, separated} x {plain,
# escaped} x {-S, --split-string} grid. Iteration 6 unescaped only when the word
# began with a dash, which is true of the FUSED word `-Sgit\_clean\_-fd` and
# false of the SPACED payload word, so two cells of the grid were closed and the
# third stayed open and deleting. Generated here rather than listed, so a cell
# cannot go missing again — that omission was the whole defect.
QA7_ENV_SEPARATOR_GRID_DENY = [
    "env " + placement.format(v="'" + sep.join(("git", "clean", "-fd")) + "'")
    for placement in ("-S{v}", "-vS{v}", "-iS{v}", "-S {v}", "-u FOO -S {v}",
                      "-i -S {v}", "--split-string={v}", "--split-string {v}")
    for sep in (" ", r"\_", r"\t", r"\n", r"\f", r"\r", r"\v")
]


@pytest.mark.parametrize("command", QA6_FUSED_OPTION_DENY)
def test_qa6_fused_option_payload_denies(command):
    verdict, _reason = decide(command)
    assert verdict == "DENY", (
        f"{command!r} runs a destructive clean once env splits the fused "
        f"option's value; NONE here allows it unsnapshotted. Got {verdict}"
    )


@pytest.mark.parametrize("command", QA6_ENV_S_ESCAPE_STILL_EXEMPT)
def test_qa6_env_s_escapes_do_not_become_a_blanket_denial(command):
    verdict, _reason = decide(command)
    assert verdict == "NONE", (
        f"{command!r} destroys nothing once env re-splits it; translating env's "
        f"separators must not turn every escaped option word into a deny. "
        f"Got {verdict}"
    )


@pytest.mark.parametrize("command", QA6_NESTED_PAYLOAD_DENY)
def test_qa6_truncated_recursion_denies_rather_than_falling_through(command):
    verdict, _reason = decide(command)
    assert verdict == "DENY", (
        f"{command!r} nests an embedded payload; beyond the analysis budget the "
        f"answer is UNKNOWN and unknown must deny. Got {verdict}"
    )


@pytest.mark.parametrize("command", QA6_GIT_ARGUMENT_DENY)
def test_qa6_argument_text_behind_a_git_subcommand_denies(command):
    verdict, _reason = decide(command)
    assert verdict == "DENY", (
        f"{command!r} carries a clean in the argument of a git subcommand that "
        f"EXECUTES it, in this very working tree. Got {verdict}"
    )


@pytest.mark.parametrize("command", QA7_STDIN_PAYLOAD_DENY)
def test_qa7_a_payload_delivered_on_stdin_denies(command):
    verdict, _reason = decide(command)
    assert verdict == "DENY", (
        f"{command!r} hands a destructive clean to a reader that executes its "
        f"stdin; dropping the operand with the redirection made the whole "
        f"command reduce to nothing. Got {verdict}"
    )


@pytest.mark.parametrize("command", QA7_STDIN_PAYLOAD_STILL_EXEMPT)
def test_qa7_inert_stdin_content_is_not_a_blanket_denial(command):
    verdict, _reason = decide(command)
    assert verdict == "NONE", (
        f"{command!r} destroys nothing; retaining here-string operands must not "
        f"turn every redirection into a deny. Got {verdict}"
    )


@pytest.mark.parametrize("command", QA7_STDIN_IS_NOT_AN_ARGUMENT_SNAPSHOT)
def test_qa7_stdin_content_never_reaches_the_flag_region(command):
    verdict, _reason = decide(command)
    assert verdict == "SNAPSHOT", (
        f"{command!r} really deletes in THIS tree - git ignores its stdin - so "
        f"it must snapshot. Anything else means the here-string leaked into the "
        f"dry-run scan and cost a snapshot. Got {verdict}"
    )


@pytest.mark.parametrize("command", QA7_ENV_SEPARATOR_GRID_DENY)
def test_qa7_env_separator_grid_denies_in_every_cell(command):
    verdict, _reason = decide(command)
    assert verdict == "DENY", (
        f"{command!r} runs a destructive clean once env re-splits its value; the "
        f"unescape must key on the REGION, not on whether the word happens to "
        f"start with a dash. Got {verdict}"
    )


@pytest.mark.parametrize("behind_echo,behind_git", QA6_SAME_TEXT_SAME_VERDICT)
def test_qa6_the_same_argument_text_is_judged_the_same_behind_git(behind_echo, behind_git):
    assert decide(behind_echo)[0] == decide(behind_git)[0], (
        "argument text that denies behind `echo` must not pass behind `git`: "
        "the difference was never a policy, it was the fail-open that let "
        "`git rebase -x '<clean>'` through"
    )


@pytest.mark.parametrize("command", QA5_UNMODELLED_PREFIX_DENY)
def test_qa5_unmodelled_prefix_denies_instead_of_vanishing(command):
    verdict, reason = decide(command)
    assert verdict == "DENY", (
        f"{command!r} still reduces to a destructive clean behind a prefix that "
        f"cannot be proven inert; NONE here means a granted clean runs with no "
        f"snapshot. Got {verdict}"
    )
    assert reason, "a DENY verdict must carry a human-readable reason"


@pytest.mark.parametrize("command", QA5_SPLICED_SNAPSHOT)
def test_qa5_spliced_or_decorated_hook_cwd_clean_snapshots(command):
    verdict, _reason = decide(command)
    assert verdict == "SNAPSHOT", (
        f"{command!r} deletes in the hook cwd once bash removes the quoting or "
        f"decoration, so it must be snapshotted first. Got {verdict}"
    )


@pytest.mark.parametrize("command", QA5_WRONG_TREE_DENY)
def test_qa5_wrong_tree_forms_deny_rather_than_snapshot_the_hook_cwd(command):
    verdict, _reason = decide(command)
    assert verdict == "DENY", (
        f"{command!r} aims the clean at another tree; snapshotting the hook cwd "
        f"and allowing it manufactures false assurance. Got {verdict}"
    )


@pytest.mark.parametrize("command", QA5_STILL_EXEMPT)
def test_qa5_inversion_does_not_over_block_ordinary_work(command):
    verdict, _reason = decide(command)
    assert verdict == "NONE", (
        f"{command!r} destroys nothing; the fail-closed default must stay narrow "
        f"or it is just a denial machine. Got {verdict}"
    )


@pytest.mark.parametrize("command", SNAPSHOT_CASES)
def test_destructive_hook_cwd_clean_snapshots(command):
    verdict, _reason = decide(command)
    assert verdict == "SNAPSHOT", (
        f"{command!r} deletes in the hook cwd and must be snapshotted first, got {verdict}"
    )


@pytest.mark.parametrize("command", NONE_CASES)
def test_non_destructive_forms_are_exempt(command):
    verdict, _reason = decide(command)
    assert verdict == "NONE", (
        f"{command!r} destroys nothing and must not trigger the guard, got {verdict}"
    )


@pytest.mark.parametrize("command", DENY_CASES)
def test_redirected_or_indeterminate_clean_denies(command):
    verdict, reason = decide(command)
    assert verdict == "DENY", (
        f"{command!r} is not provably a hook-cwd clean and must deny fail-closed, got {verdict}"
    )
    assert reason, "a DENY verdict must carry a human-readable reason"
