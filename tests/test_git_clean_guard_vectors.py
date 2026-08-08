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
import sys

import pytest

_HOOKS_LIB = pathlib.Path(__file__).resolve().parents[1] / "hooks" / "lib"
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

from git_clean_guard import decide  # noqa: E402


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
    # A non-redirecting env ASSIGNMENT through a wrapper is still the hook cwd.
    "env FOO=bar git clean -fd",
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
]


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
