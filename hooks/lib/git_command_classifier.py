"""Shared git-command classifier for security hooks.

Provides iter_git_invocations() — a token-aware parser that detects git
invocations in shell command strings, including path-qualified forms such
as /usr/bin/git and ./git.  Closes RISK-3 (path-qualified git bypass) in
pretool-git-privilege-guard.py and pretool-bash-safety.sh.

Root cause (2026-07-04): GIT_COMMAND_RE / GIT_CMD_RE anchor classes
  [\\s;&|()`] / [[:space:];&|()`] omit '/', so path-qualified tokens like
  /usr/bin/git and ./git never matched the pattern.

Primitives moved from pretool-block-branch-pr-worktree.py (lines 115-219)
so they are importable by other hooks via lib.git_command_classifier.

# Known scope boundaries (arch-F7)
#   - `env -i/-u/-P` flags before the git token: not handled by
#     _command_token_index().  The speed-bump design accepts this; /do
#     and /allow escape hatches cover the rare edge case.
#   - Leading shell redirections (e.g. `2>/dev/null git push`): same limit.

CLI usage:
  printf 'command text\\n' | python3 hooks/lib/git_command_classifier.py
  CMD_INPUT='command text' python3 hooks/lib/git_command_classifier.py
  Output: JSON array of {"subcommand": str, "args": list, "path_qualified": bool}

Prefilter hint for callers:
  printf '%s\\n' "$COMMAND_CONTEXT_STRIPPED" | grep -q 'git' before spawning
  python3 to avoid unnecessary subprocess overhead.

Normalization contract:
  In CLI mode this module does NOT call bash_context_strip/_norm before
  _segments().  Normalization is the CALLER's responsibility.
  pretool-bash-safety.sh MUST feed COMMAND_CONTEXT_STRIPPED (already
  normalized by bash_context_strip.py at lines 733-743), NOT raw $COMMAND.
"""

import collections
import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# Primitives (moved verbatim from pretool-block-branch-pr-worktree.py:115-219)
# ---------------------------------------------------------------------------


def _segments(c):
    """Split on shell separators ; \\n | & && || ` ( ) into command segments.

    Parens open a new command segment in exactly THREE cases, all of which put
    an embedded command into command position:
      1. command-substitution / process-substitution introducers `$(`, `<(`, `>(`
         — the text after the opener is a command (e.g. `echo $(git checkout -b
         x)` must classify the inner `git checkout -b x`).
      2. a real subshell `(` in command position (the current buffer is empty or
         all whitespace), e.g. `(git checkout -b x)`.
    A matching `)` only closes a boundary we actually opened (depth-tracked).
    This avoids shredding argument-internal parens such as a git
    `--format %(refname)` / `--format=%(refname)` spec, whose `%(`/`)` are part of
    a single argument token (the `(` is preceded by `%`, not `$`/`<`/`>`, and is
    not in command position) — splitting those would orphan a trailing positional
    branch name (e.g. `git branch --format %(refname) nb`) into a segment without
    `git branch`, defeating creation detection (the dangerous under-block
    direction). Backtick substitution is split via the `` ` `` separator below.
    """
    out, buf, i, n = [], [], 0, len(c)
    subshell_depth = 0

    def _buf_is_cmd_position():
        return all(ch.isspace() for ch in buf)

    while i < n:
        two = c[i:i + 2]
        if two in ('&&', '||'):
            out.append(''.join(buf)); buf = []; i += 2; continue
        # Command/process substitution introducers open a command boundary; the
        # introducer char (`$`/`<`/`>`) is dropped from the outer segment.
        if two in ('$(', '<(', '>('):
            subshell_depth += 1
            out.append(''.join(buf)); buf = []; i += 2; continue
        ch = c[i]
        if ch in ';\n|&`':
            out.append(''.join(buf)); buf = []; i += 1; continue
        if ch == '(' and _buf_is_cmd_position():
            subshell_depth += 1
            out.append(''.join(buf)); buf = []; i += 1; continue
        if ch == ')' and subshell_depth > 0:
            subshell_depth -= 1
            out.append(''.join(buf)); buf = []; i += 1; continue
        buf.append(ch); i += 1
    out.append(''.join(buf))
    return out


def _basename(tok):
    return tok.rsplit('/', 1)[-1]


# Command WRAPPERS that prefix the real command token (basename match). The real
# command token is the first token after skipping leading env-var assignments
# (NAME=VALUE) and any of these wrappers. Only that one command token is
# classified — text that merely mentions git/gh later in the segment (e.g.
# `echo gh pr new`) is therefore NOT a creation.
_WRAPPERS = {
    'sudo', 'doas', 'env', 'xargs', 'time', 'nohup', 'setsid', 'stdbuf',
    'ionice', 'command', 'builtin', 'nice',
}

_ENV_ASSIGN_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')


def _command_token_index(toks):
    """Return the index of the segment's COMMAND token, or None.

    Skips leading env-var assignments (NAME=VALUE) and known command wrappers
    (basename match). Returns the index of the first real command token.
    """
    i = 0
    n = len(toks)
    while i < n:
        t = toks[i]
        if _ENV_ASSIGN_RE.match(t):
            i += 1
            continue
        if _basename(t) in _WRAPPERS:
            i += 1
            continue
        return i
    return None


# git global options that consume a separate following value token.
_GIT_GLOBAL_VALUE = {
    '-C', '-c', '--git-dir', '--work-tree', '--namespace',
    '--exec-path', '--super-prefix', '--config-env',
}


def _git_subcommand(args):
    """Return (subcommand, remaining_args) skipping git global options."""
    i = 0
    while i < len(args):
        a = args[i]
        if a in _GIT_GLOBAL_VALUE:
            i += 2
            continue
        if a.startswith('-'):
            i += 1
            continue
        return a, args[i + 1:]
    return None, []


# ---------------------------------------------------------------------------
# GitInvocation and iter_git_invocations
# ---------------------------------------------------------------------------

GitInvocation = collections.namedtuple(
    'GitInvocation',
    ['cmd_token', 'path_qualified', 'subcommand', 'args'],
)


def iter_git_invocations(command_text):
    """Yield GitInvocation for every git invocation in command_text.

    Uses token-aware parsing: tokenizes each shell segment, skips wrappers
    and env-var assignments, then checks whether the command token is git
    (exact basename match via os.path.basename(token) == 'git').

    path_qualified is True when the token contains a '/' (e.g. /usr/bin/git),
    False for bare 'git'.  subcommand and args are computed by _git_subcommand()
    which skips git global options (-C, --git-dir, etc.) so that, e.g.,
    /usr/bin/git -C repo push --force correctly yields subcommand='push',
    args=['--force'].

    Normalization note: this function does NOT normalize the command string
    before segmenting.  Callers are responsible for passing normalized input
    (e.g. COMMAND_CONTEXT_STRIPPED from bash_context_strip.py) when the raw
    $COMMAND may contain multi-line quoted bodies that would produce false
    positives.
    """
    for seg in _segments(command_text):
        toks = seg.split()
        if not toks:
            continue
        idx = _command_token_index(toks)
        if idx is None:
            continue
        token = toks[idx]
        if os.path.basename(token) != 'git':
            continue
        after_git = toks[idx + 1:]
        subcommand, remaining_args = _git_subcommand(after_git)
        yield GitInvocation(
            cmd_token=token,
            path_qualified=('/' in token),
            subcommand=subcommand,
            args=remaining_args,
        )


# ---------------------------------------------------------------------------
# CLI __main__ — JSON output mode
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    # Read from CMD_INPUT env var or stdin.
    cmd_text = os.environ.get('CMD_INPUT', '')
    if not cmd_text:
        cmd_text = sys.stdin.read()

    results = []
    for inv in iter_git_invocations(cmd_text):
        results.append({
            'subcommand': inv.subcommand,
            'args': inv.args,
            'path_qualified': inv.path_qualified,
        })
    print(json.dumps(results))
    sys.exit(0)
