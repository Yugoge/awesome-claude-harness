#!/usr/bin/env python3
"""Pre-clean WIP-snapshot decision for pretool-bash-safety.sh grant exits.

Classifies ONE Bash command for the fail-closed pre-clean guard woven into the
four human-grant/consent `exit 0` escapes of pretool-bash-safety.sh:

  NONE     - no statically reducible destructive `git clean` in the command
  SNAPSHOT - a destructive clean whose target is PROVABLY the hook's own cwd
  DENY     - anything else that still reduces to a destructive clean

THE TERMINAL DEFAULT IS DENY, NOT NONE. The previous revision asked "does the
command token resolve to git?" and answered NONE whenever it could not tell.
That inverted the burden of proof: an unmodelled prefix (`timeout 60 git clean
-fd`, `bash -c '...'`, `flock ... git clean -fd`) made the clean invisible and a
granted destructive clean proceeded with NO snapshot - the exact incident this
lane exists to prevent. Enumerating more wrapper names only moves that
boundary. This module instead asks "can a destructive clean be statically
reduced out of this command?" and, if so, demands POSITIVE proof that its
target is the hook's own working directory before allowing it.

Target resolution is still deliberately NOT attempted: an allowed clean whose
snapshot covered a DIFFERENT tree is worse than an honest denial, because the
operator is told their work is recoverable when it is not. Redirect PRESENCE is
decidable; redirect RESOLUTION is not.

ONE parse feeds every predicate. `_lex` is a small bash-aware static-word
extractor: it joins adjacent quoted/escaped fragments into a single word
(`--no-""dry-run` -> `--no-dry-run`, `g''it` -> `git`), decodes `$'...'`,
honours line continuations, comments and redirections, and marks command
substitution. The clean detector, the dry-run predicate, the git-global scan
and the cwd-mutation scan all consume THAT word list, so a splice can no longer
hide a negation, a `--work-tree` or a `cd` from one predicate while another
sees it.

git_command_classifier.py is NOT imported and NOT modified: its
`_git_subcommand` signature is imported directly by
pretool-block-branch-pr-worktree.py and must stay stable, and its `_WRAPPERS`
set is a closed 12-name enumeration that this module must no longer treat as
exhaustive.

Coverage bounds (deliberate, documented, and stated as the REAL bound):
  - Ignored-file (`-x`/`-X`) CONTENT protection is out of scope; the snapshot
    still fires for `-x` cleans to preserve the untracked-non-ignored WIP.
  - A command word that exists only after EXPANSION (`$GIT clean -fd`, an
    `alias.wipe=clean` indirection) is not statically reducible and yields
    NONE. Those are the accepted CX-2/CX-3 residuals and live in the shared
    classification layer, not in this grant-residual lane.
  - EVERYTHING else that still reduces to a destructive clean DENIES unless its
    target is proven. An unrecognised prefix denies; it does not fall through.

Accepted over-blocks (cost usability under an active grant, never data):
  - Argument text that reduces to a destructive clean outside a provably-inert
    git invocation denies (`echo git clean -fd`, `grep -r "git clean" .`).
  - A `cd`/`pushd`/`popd` word anywhere in a command that ALSO contains a
    destructive clean denies, even when the clean textually precedes it.

Exit codes (CLI): 0 = NONE, 10 = SNAPSHOT, 11 = DENY. Reason text on stdout.
"""

from __future__ import annotations

import os
import re
import sys

# git globals that point the invocation at a DIFFERENT repository / work tree.
_REDIRECT_FLAGS = frozenset({"-C", "--git-dir", "--work-tree"})
# git globals that consume an operand but do NOT redirect the target.
_NEUTRAL_GLOBALS_WITH_ARG = frozenset({
    "--namespace", "--exec-path", "--super-prefix",
})
# Environment assignments that redirect the target (QA obs-1: these aim at
# ANOTHER tree, so mis-detection would be safe, but denying them keeps the
# "deny ANY redirect" invariant honest rather than merely safe-by-accident).
_REDIRECT_ENV = frozenset({"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"})
# `-c key=value` config keys that redirect the work tree. NOTE `-c` is config,
# NOT `-C` chdir: `-c clean.requireForce=false` is NOT a redirect.
_REDIRECT_CONFIG_KEYS = frozenset({"core.worktree", "core.gitdir"})

# Shell builtins that move the effective working directory.
_CWD_MUTATORS = frozenset({"cd", "pushd", "popd"})
_SUBST_MARKERS = ("$(", "<(", ">(", "`")

# Reserved words / decorators that never move the target and take no operand.
_RESERVED_DECORATORS = frozenset({
    "!", "{", "}", "then", "else", "elif", "do", "done", "fi", "esac",
})
# Wrapper NAMES whose OPTION-FREE form is target-transparent. Membership here is
# NO LONGER what makes a command visible: an unlisted name simply means "not
# provably inert", which now DENIES rather than disappearing.
_INERT_WRAPPERS = frozenset({
    "sudo", "doas", "env", "xargs", "time", "nohup", "setsid", "stdbuf",
    "ionice", "command", "builtin", "nice", "exec",
})

_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

_VERDICT_EXIT = {"NONE": 0, "SNAPSHOT": 10, "DENY": 11}
_MAX_EMBED_DEPTH = 3


class _Word:
    """One static shell word plus the provenance the predicates need."""

    __slots__ = ("text", "dynamic", "redir_target")

    def __init__(self, text, dynamic=False, redir_target=False):
        self.text = text
        self.dynamic = dynamic
        self.redir_target = redir_target

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"_Word({self.text!r}, dynamic={self.dynamic})"


def _decode_ansi_c(inner: str) -> str:
    """Decode a `$'...'` body. Falls back to the raw body, which is fail-closed:
    an undecoded body can only look LESS like `git`/`clean`, and a residual that
    still reduces to a clean is caught by the terminal DENY default."""
    try:
        return inner.encode("utf-8", "surrogateescape").decode("unicode_escape")
    except Exception:
        return inner


def _lex(text: str):
    """Return (tokens, info) for one command string.

    tokens: list of ("word", _Word) / ("op", str) / ("redir", str)
    info:   {"substitution": bool, "subshell": bool}

    Adjacent quoted/escaped fragments join into ONE word, which is what defeats
    the whole splice class (`g''it`, `--no-""dry-run`, `--work-'tree'=<B>`).
    Never raises: an unterminated quote consumes the remainder of the input."""
    tokens = []
    info = {"substitution": False, "subshell": False}
    buf = []
    dynamic = False
    started = False
    i, n = 0, len(text)

    def flush():
        nonlocal buf, dynamic, started
        if started or buf:
            tokens.append(("word", _Word("".join(buf), dynamic)))
        buf, dynamic, started = [], False, False

    def at_command_position():
        if started or buf:
            return False
        for kind, _payload in reversed(tokens):
            return kind == "op"
        return True

    while i < n:
        c = text[i]
        two = text[i:i + 2]

        # `#` starts a comment only at the beginning of a word.
        if c == "#" and not started and not buf:
            while i < n and text[i] != "\n":
                i += 1
            continue

        if c == "\\":
            if two == "\\\n":
                i += 2          # line continuation: joins adjacent fragments
                continue
            if i + 1 < n:
                buf.append(text[i + 1])
                started = True
                i += 2
                continue
            i += 1
            continue

        # ANSI-C quoting is STATIC: `git $'clean' -fd` really runs a clean.
        if two == "$'":
            j = i + 2
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "'":
                    break
                j += 1
            buf.append(_decode_ansi_c(text[i + 2:j]))
            started = True
            i = min(j + 1, n)
            continue

        if two == '$"':         # locale-translated string behaves like "..."
            i += 1
            continue

        if two in ("$(", "<(", ">("):
            info["substitution"] = True
            flush()
            tokens.append(("op", two))
            i += 2
            continue
        if c == "`":
            info["substitution"] = True
            flush()
            tokens.append(("op", "`"))
            i += 1
            continue

        if c == "$":            # parameter expansion contributes no static text
            dynamic = True
            started = True
            j = i + 1
            if j < n and text[j] == "{":
                depth, j = 1, j + 1
                while j < n and depth:
                    if text[j] == "{":
                        depth += 1
                    elif text[j] == "}":
                        depth -= 1
                    j += 1
            else:
                while j < n and (text[j].isalnum() or text[j] == "_"):
                    j += 1
                if j == i + 1 and j < n:
                    j += 1      # $?, $$, $1 ...
            i = j
            continue

        if c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                buf.append(text[i + 1:])
                started = True
                i = n
                continue
            buf.append(text[i + 1:j])
            started = True
            i = j + 1
            continue

        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    nxt = text[j + 1]
                    if nxt in '$`"\\':
                        buf.append(nxt)
                    elif nxt != "\n":
                        buf.append(text[j])
                        buf.append(nxt)
                    j += 2
                    continue
                if text[j] in "$`":
                    if text[j] == "`" or text[j:j + 2] == "$(":
                        info["substitution"] = True
                    dynamic = True
                    j += 1
                    continue
                buf.append(text[j])
                j += 1
            started = True
            i = j + 1
            continue

        if c in "<>":           # redirection, with an optional leading fd
            op = c
            j = i + 1
            while j < n and text[j] in "<>&" and len(op) < 3:
                op += text[j]
                j += 1
            if buf and all(ch.isdigit() for ch in buf):
                buf, started = [], False    # the fd belongs to the redirection
            else:
                flush()
            tokens.append(("redir", op))
            i = j
            continue

        if two in ("&&", "||", ";;"):
            flush()
            tokens.append(("op", two))
            i += 2
            continue

        if c in ";\n|&":
            flush()
            tokens.append(("op", c))
            i += 1
            continue

        if c == "(":
            if at_command_position():
                info["subshell"] = True
            flush()
            tokens.append(("op", "("))
            i += 1
            continue

        if c == ")":
            flush()
            tokens.append(("op", ")"))
            i += 1
            continue

        if c.isspace():
            flush()
            i += 1
            continue

        buf.append(c)
        started = True
        i += 1

    flush()

    # A redirection's operand is data, never a command word.
    for idx, (kind, _payload) in enumerate(tokens):
        if kind != "redir":
            continue
        for nxt_kind, nxt in tokens[idx + 1:]:
            if nxt_kind == "word":
                nxt.redir_target = True
            break
    return tokens, info


def _split_segments(tokens):
    """Split the token stream into command segments on shell separators,
    dropping redirection operators and their operands."""
    segments, current = [], []
    for kind, payload in tokens:
        if kind == "op":
            segments.append(current)
            current = []
            continue
        if kind == "redir" or payload.redir_target:
            continue
        current.append(payload)
    segments.append(current)
    return [seg for seg in segments if seg]


def _all_words(segments):
    return [word for seg in segments for word in seg]


def _is_redirect_config(kv: str) -> bool:
    return kv.split("=", 1)[0].strip().lower() in _REDIRECT_CONFIG_KEYS


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


def _git_invocation(words, start, ignore_dry_run=False):
    """words[start] basenames to `git`. Return (destructive_clean, redirect)."""
    redirect = False
    subcommand = None
    sub_idx = None
    i, n = start + 1, len(words)
    while i < n:
        tok = words[i].text
        if not tok:
            if words[i].dynamic:
                return (False, False)   # an expansion sits in global position
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
            if i + 1 < n and _is_redirect_config(words[i + 1].text):
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
    if not ignore_dry_run and _is_dry_run([_unquote(t) for t in toks[sub_idx + 1:]]):
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

    # BOTH parses, unioned fail-closed. The bounded normalizer erases quoted
    # content, so `git clean -n "--no-dry-run" -fd` loses its negation and reads
    # as a dry run; the raw text keeps it. Whichever parse sees a destructive
    # clean wins, so erasing text can never buy an exemption.
    segments = _segments(normalized)
    if command_text != normalized:
        segments = segments + _segments(command_text)
    destructive = False
    redirect = False
    for seg in segments:
        seg_destructive, seg_redirect = _scan_segment(seg)
        if seg_destructive:
            destructive = True
            redirect = redirect or seg_redirect

    if not destructive:
        # A clean whose flag region is built by substitution is not a PROVEN
        # dry run, and `_segments` has already carved the substitution into its
        # own segment, so the flag never reaches _is_dry_run.
        if any(marker in command_text for marker in _SUBST_MARKERS):
            for seg in segments:
                if _scan_segment(seg, ignore_dry_run=True)[0]:
                    return ("DENY", "a `git clean` carries command substitution "
                                    "in its flag region - the effective flags "
                                    "cannot be proven to be a dry run")
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
