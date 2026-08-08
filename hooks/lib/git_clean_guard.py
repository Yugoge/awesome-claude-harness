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
    """Reduce a raw token to the static word bash would hand the program.

    Strips balanced surrounding quotes (`"/usr/bin/git"` -> /usr/bin/git), then
    any remaining stray quote characters at either end (`'git` -> git, as a
    whitespace split of `env -S 'git clean -fd'` produces), then backslash
    escapes (`--no-dry\\-run` -> --no-dry-run). Every one of those reductions is
    fail-CLOSED for this module: it can only make a token look MORE like a git
    token or a destructive flag, never less, so a token bash would not actually
    reduce this way costs at most a superfluous snapshot or deny."""
    t = tok.strip()
    while len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
        t = t[1:-1]
    t = t.strip("'\"")
    return t.replace("\\", "")


def _region_word(tok: str) -> str:
    """The static word a WRAPPER-REGION token contributes. A wrapper option can
    carry an embedded command in its value (`env --split-string='git clean
    -fd'`), so the post-`=` value is what matters there."""
    return _unquote(tok.split("=", 1)[1]) if "=" in tok else _unquote(tok)


def _is_redirect_config(kv: str) -> bool:
    return _unquote(kv).split("=", 1)[0].strip().lower() in _REDIRECT_CONFIG_KEYS


def _abbrev_of(tok: str, full: str, min_len: int) -> bool:
    """True when git parse-options would accept `tok` as an abbreviation of the
    long option `full`. Unambiguous prefixes are accepted by git (verified:
    `git status --no-col` and `--unt=no` both parse), and `git clean`'s option
    set is small enough that `--no-dry` and `--e` are unambiguous. Used only in
    the fail-CLOSED direction — to CLEAR a dry-run exemption and to consume an
    exclude's operand — so a prefix git would actually reject can at worst cause
    a superfluous snapshot, never a skipped one."""
    return min_len <= len(tok) <= len(full) and full.startswith(tok)


def _is_dry_run(rest: list) -> bool:
    """True only for a PROVEN dry run. A force flag is NOT the destructiveness
    test (`git -c clean.requireForce=false clean -d` deletes without `-f`), so
    everything that is not `-n`/`--dry-run` counts as destructive-or-uncertain.

    git parse-options applies the dry-run flag and its generated `--no-dry-run`
    negation LAST-WINS, so the scan is STATEFUL rather than first-match: `git
    clean -n --no-dry-run -fd` DELETES, and an early `return True` on the first
    `-n` skipped the snapshot on it (CX-1). The negation and the exclude are
    matched as ABBREVIATIONS too (`--no-dry`, `--exc <pat>`), because git accepts
    any unambiguous prefix; both directions of that are fail-closed, so an
    abbreviation git would reject only costs a superfluous snapshot. The
    positive `-n` / `--dry-run` stays exact-match for the same reason: an
    unrecognised spelling must read as destructive, never as exempt.

    A separate-value exclude consumes the FOLLOWING token as its pattern, so a
    trailing `-n` there is an exclude pattern and NOT a dry run: `git clean -fd
    -e -n` DELETES. Treating it as exempt would skip the snapshot on a
    destructive clean, so `-e` / `--exclude` operands are skipped, and inside a
    short cluster only an `n` occurring BEFORE the first `e` counts (everything
    after an `e` is that exclude's argument). Scanning stops at `--` so a
    pathspec literally named `-n` cannot exempt either."""
    dry = False
    i, n = 0, len(rest)
    while i < n:
        tok = rest[i]
        if tok == "--":
            break  # everything after is a pathspec, not a flag
        if tok in ("-n", "--dry-run"):
            dry = True
        elif _abbrev_of(tok, "--no-dry-run", 6):
            dry = False  # last-wins negation, `--no-d` upwards
        elif "=" in tok and _abbrev_of(tok.split("=", 1)[0], "--exclude", 3):
            i += 1  # self-contained `--exclude=<pat>`, consumes nothing
            continue
        elif tok == "-e" or _abbrev_of(tok, "--exclude", 3):
            i += 2  # the next token is this exclude's pattern, not a flag
            continue
        elif tok.startswith("-") and not tok.startswith("--"):
            cluster = tok[1:]
            e_pos = cluster.find("e")
            n_pos = cluster.find("n")
            if n_pos >= 0 and (e_pos < 0 or n_pos < e_pos):
                dry = True
            if e_pos == len(cluster) - 1 and e_pos >= 0:
                i += 2  # cluster ends in `e` -> next token is its pattern
                continue
        i += 1
    return dry


def _scan_segment(seg: str, ignore_dry_run: bool = False):
    """Return (destructive_clean_present, target_redirect_present) for a segment.

    Tokens are reduced to static shell words FIRST, so a quoted wrapper or
    command token (`"/usr/bin/env" -C <dir> "git" clean -fd`) is seen for what
    bash will actually execute rather than for its punctuation."""
    toks = [_unquote(t) for t in seg.split()]
    if not toks:
        return (False, False)
    idx = _command_token_index(toks)
    if idx is None:
        return (False, False)
    if toks[idx] == "--":
        # A wrapper's option TERMINATOR: everything after it is the command and
        # no cwd-changing option preceded it, so `env -- git clean -fd` is a
        # provable hook-cwd clean and must snapshot rather than deny.
        idx += 1
        if idx >= len(toks):
            return (False, False)
    elif toks[idx].startswith("-"):
        # A WRAPPER's own option region. _command_token_index steps over the
        # wrapper token but stops at its first option, so `env -C <dir> git
        # clean -fd` resolves to `-C` and the git invocation is invisible
        # (CX-4). Re-scan from EVERY git-basenamed token in the region, not
        # just the first: a wrapper OPERAND can itself basename to git
        # (`sudo -u git git clean -fd` on a host with a git service account),
        # and an argument can too (`... git clean -fd /srv/git`). Any candidate
        # that yields a destructive clean denies, because the option region is
        # an unprovable target: `-C` / `--chdir` move the child's cwd outright,
        # and an option this module does not model cannot be proven not to.
        region = [_region_word(t) for t in toks[idx:]]
        for j in range(len(region)):
            if os.path.basename(region[j]) != "git":
                continue
            if _scan_segment(" ".join(region[j:]), ignore_dry_run)[0]:
                return (True, True)
        return (False, False)
    if os.path.basename(_unquote(toks[idx])) != "git":
        return (False, False)

    redirect = False
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


def _has_env_redirect(segments: list) -> bool:
    """True when ANY segment assigns a work-tree-redirecting git environment
    variable. Scanned across the whole command, not just the git segment's own
    leading assignments, so `export GIT_DIR=<other> && git clean -fd` is caught
    as well as the inline `GIT_WORK_TREE=<other> git clean -fd` form."""
    for seg in segments:
        for tok in seg.split():
            stripped = _unquote(tok)
            if (_ENV_ASSIGN_RE.match(stripped)
                    and stripped.split("=", 1)[0] in _REDIRECT_ENV):
                return True
    return False


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

    segments = _segments(normalized)
    destructive = False
    redirect = False
    for seg in segments:
        seg_destructive, seg_redirect = _scan_segment(seg)
        if seg_destructive:
            destructive = True
            redirect = redirect or seg_redirect

    if not destructive:
        return ("NONE", "")
    redirect = redirect or _has_env_redirect(segments)
    if redirect:
        return ("DENY", "target-redirecting git global or unprovable wrapper "
                        "option present (-C / --git-dir / --work-tree / GIT_DIR / "
                        "GIT_WORK_TREE / -c core.worktree / env -C / env --chdir) - "
                        "the clean target is not provably the hook's own working "
                        "directory")
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
