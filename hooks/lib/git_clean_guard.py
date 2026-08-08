#!/usr/bin/env python3
"""Pre-clean WIP-snapshot decision for pretool-bash-safety.sh grant exits.

Classifies ONE Bash command for the fail-closed pre-clean guard woven into the
four human-grant/consent `exit 0` escapes of pretool-bash-safety.sh:

  NONE     - no destructive-or-uncertain `git clean` in the command
  SNAPSHOT - a destructive clean whose target is PROVABLY the hook's own cwd
  DENY     - target-redirected or indeterminate clean (fail-closed)

Why presence-detection and not target resolution: the shared classifier
(git_command_classifier.py::_git_subcommand) consumes and DISCARDS the
target-redirecting globals (`i += 2`), so `git -C B clean -fd` and
`git clean -fd` are byte-identical in its output. Resolving an arbitrary git
target (cumulative -C, --work-tree vs --git-dir, relative paths, symlinks) is
the failure class that would snapshot the WRONG repo while ALLOWING the clean.
This module therefore only detects redirect PRESENCE and denies, which is a
decidable token scan and strictly at-least-as-protective.

Reuses the shared tokenizer (`_segments`, `_command_token_index`,
`_ENV_ASSIGN_RE`) and the bounded normalizer (`strip_non_executable_contexts`)
rather than a bespoke raw-command regex. git_command_classifier.py is NOT
modified: `_git_subcommand`'s return signature is imported directly by
pretool-block-branch-pr-worktree.py and must stay stable.

Coverage bounds (deliberate, documented):
  - Ignored-file (`-x`/`-X`) CONTENT protection is out of scope; the snapshot
    still fires for `-x` cleans to preserve the untracked-non-ignored WIP.
  - A dynamically-named git token (`$GIT clean -fd`, where the command token is
    not literally basenamed `git`) is not classified as a clean here. Such a
    command carries a `$` operand and is covered by the sibling deny lane's
    general `git clean` rule, not by this grant-residual snapshot lane.

Exit codes (CLI): 0 = NONE, 10 = SNAPSHOT, 11 = DENY. Reason text on stdout.
"""

from __future__ import annotations

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from git_command_classifier import (  # noqa: E402  (path bootstrap above)
    _ENV_ASSIGN_RE,
    _command_token_index,
    _segments,
)

try:
    from bash_context_strip import strip_non_executable_contexts  # noqa: E402
except ImportError:  # normalizer unavailable -> parse the raw command instead
    strip_non_executable_contexts = None  # type: ignore[assignment]


# git globals that point the invocation at a DIFFERENT repository / work tree.
_REDIRECT_FLAGS = frozenset({"-C", "--git-dir", "--work-tree"})
# git globals that consume an operand but do NOT redirect the target.
_NEUTRAL_GLOBALS_WITH_ARG = frozenset({
    "--namespace", "--exec-path", "--super-prefix",
})
# Leading environment assignments that redirect the target (QA obs-1: these
# aim at ANOTHER tree, so mis-detection would be safe, but denying them keeps
# the "deny ANY redirect" invariant honest rather than merely safe-by-accident).
_REDIRECT_ENV = frozenset({"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"})
# `-c key=value` config keys that redirect the work tree. NOTE `-c` is config,
# NOT `-C` chdir: `-c clean.requireForce=false` is NOT a redirect.
_REDIRECT_CONFIG_KEYS = frozenset({"core.worktree", "core.gitdir"})

# Shell constructs that make the effective working directory indeterminate.
_CWD_MUTATORS = frozenset({"cd", "pushd", "popd"})
_SUBST_MARKERS = ("$(", "<(", ">(", "`")
_SUBSHELL_RE = re.compile(r"(?:^|[;&|(\n])\s*\(")

_VERDICT_EXIT = {"NONE": 0, "SNAPSHOT": 10, "DENY": 11}


def _unquote(tok: str) -> str:
    """Strip balanced surrounding quotes so `"/usr/bin/git"` basenames to git."""
    t = tok.strip()
    while len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
        t = t[1:-1]
    return t


def _is_redirect_config(kv: str) -> bool:
    return _unquote(kv).split("=", 1)[0].strip().lower() in _REDIRECT_CONFIG_KEYS


def _is_dry_run(rest: list) -> bool:
    """True only for a PROVEN dry run. A force flag is NOT the destructiveness
    test (`git -c clean.requireForce=false clean -d` deletes without `-f`), so
    everything that is not `-n`/`--dry-run` counts as destructive-or-uncertain.
    Scanning stops at `--` so a pathspec literally named `-n` cannot exempt."""
    for tok in rest:
        if tok == "--":
            return False
        if tok in ("-n", "--dry-run"):
            return True
        if tok.startswith("-") and not tok.startswith("--") and "n" in tok[1:]:
            return True
    return False


def _scan_segment(seg: str):
    """Return (destructive_clean_present, target_redirect_present) for a segment."""
    toks = seg.split()
    if not toks:
        return (False, False)
    idx = _command_token_index(toks)
    if idx is None:
        return (False, False)
    if os.path.basename(_unquote(toks[idx])) != "git":
        return (False, False)

    redirect = any(
        _ENV_ASSIGN_RE.match(t) and t.split("=", 1)[0] in _REDIRECT_ENV
        for t in toks[:idx]
    )

    subcommand = None
    sub_idx = None
    i, n = idx + 1, len(toks)
    while i < n:
        tok = _unquote(toks[i])
        if not tok:
            i += 1
            continue
        if tok in _REDIRECT_FLAGS:
            redirect = True
            i += 2
            continue
        if tok.startswith("-C") and len(tok) > 2:  # fused -C<dir>
            redirect = True
            i += 1
            continue
        if tok.startswith("--git-dir=") or tok.startswith("--work-tree="):
            redirect = True
            i += 1
            continue
        if tok in ("-c", "--config-env"):
            if i + 1 < n and _is_redirect_config(toks[i + 1]):
                redirect = True
            i += 2
            continue
        if tok.startswith("-c") and len(tok) > 2:  # fused -c<key=value>
            if _is_redirect_config(tok[2:]):
                redirect = True
            i += 1
            continue
        if tok.startswith("--config-env="):
            if _is_redirect_config(tok[len("--config-env="):]):
                redirect = True
            i += 1
            continue
        if tok in _NEUTRAL_GLOBALS_WITH_ARG:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        subcommand, sub_idx = tok, i
        break

    if subcommand != "clean":
        return (False, False)
    if _is_dry_run([_unquote(t) for t in toks[sub_idx + 1:]]):
        return (False, False)
    return (True, redirect)


def _has_cwd_mutation(normalized: str, raw: str) -> bool:
    """True when the effective cwd at the clean cannot be proven to be the hook
    cwd: a leading `cd`/`pushd`/`popd`, a subshell, or any command/process
    substitution. Substitution markers are scanned on the RAW command too, since
    the bounded normalizer may erase them (fail-closed direction)."""
    for text in (normalized, raw):
        if any(marker in text for marker in _SUBST_MARKERS):
            return True
        if _SUBSHELL_RE.search(text):
            return True
    for seg in _segments(normalized):
        toks = seg.split()
        if not toks:
            continue
        idx = _command_token_index(toks)
        if idx is None:
            continue
        if os.path.basename(_unquote(toks[idx])) in _CWD_MUTATORS:
            return True
    return False


def decide(command_text: str):
    """Return (verdict, reason) for one Bash command. Fail-closed by design:
    every clean in a multi-clean payload must be provably hook-cwd-targeted."""
    normalized = command_text
    if strip_non_executable_contexts is not None:
        try:
            normalized = strip_non_executable_contexts(command_text)
        except Exception:  # bounded normalizer failed -> parse the raw command
            normalized = command_text

    destructive = False
    redirect = False
    for seg in _segments(normalized):
        seg_destructive, seg_redirect = _scan_segment(seg)
        if seg_destructive:
            destructive = True
            redirect = redirect or seg_redirect

    if not destructive:
        return ("NONE", "")
    if redirect:
        return ("DENY", "target-redirecting git global present "
                        "(-C / --git-dir / --work-tree / GIT_DIR / GIT_WORK_TREE / "
                        "-c core.worktree) - the clean target is not provably the "
                        "hook's own working directory")
    if _has_cwd_mutation(normalized, command_text):
        return ("DENY", "effective working directory is indeterminate "
                        "(leading cd/pushd, subshell, or command substitution) - "
                        "the clean target is not provably the hook's own working "
                        "directory")
    return ("SNAPSHOT", "")


if __name__ == "__main__":
    cmd_text = os.environ.get("CMD_INPUT", "")
    if not cmd_text:
        cmd_text = sys.stdin.read()
    try:
        verdict, reason = decide(cmd_text)
    except Exception as exc:  # unparseable -> DENY, unless plainly not a git command
        if "git" not in cmd_text:
            sys.exit(_VERDICT_EXIT["NONE"])
        print("pre-clean guard could not classify the command "
              f"({exc.__class__.__name__}); denying fail-closed")
        sys.exit(_VERDICT_EXIT["DENY"])
    if reason:
        print(reason)
    sys.exit(_VERDICT_EXIT[verdict])
