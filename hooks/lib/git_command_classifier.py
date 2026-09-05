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

# Known scope boundaries (arch-F7) — CLOSED 2026-09-03, see below.
#   - `env -i/-u/-P` flags before the git token: NOW handled, via
#     _WRAPPER_VALUE_FLAGS / _WRAPPER_POSITIONALS in _command_token_index().
#   - Leading shell redirections (e.g. `2>/dev/null git push`): NOW handled,
#     via _REDIRECT_RE in _command_token_index().
#   - Shell reserved words in front of the command word (`if ! git …`,
#     `then git …`, `do git …`, `while ! git …`): NOW handled, via
#     _SHELL_PREFIX_KEYWORDS.  Before this fix _command_token_index() returned
#     the index of the KEYWORD, whose basename is never 'git', so
#     iter_git_invocations() yielded NOTHING and every guard built on it was a
#     no-op for those forms — including `if ! git commit …`, which is this
#     repository's own documented error-handling idiom.
#
# Residual (accepted, documented, and DETECTED rather than silently dropped):
#   A command whose command-token cannot be resolved statically — an obfuscated
#   token (`g\\it`, `gi""t`), a parameter expansion (`$GIT push`), or a
#   command-position command-substitution (`$(which git) push`) — is reported
#   through classify_git_command()'s `residuals` channel so a caller can fail
#   closed instead of mistaking an unparseable command for a git-free one.

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
    return [seg for seg, _kind, _in_quote in _segments_with_kind(c)]


def _segments_with_kind(c):
    """_segments(), but each segment is paired with the boundary that OPENED it.

    Returns a list of (segment_text, kind, in_quote) where kind is one of:
      'start'          — the first segment of the string
      'separator'      — opened by ; \\n | & && || or a subshell/substitution `(`
      'subst_close'    — opened by the `)` that closed a command substitution
                         whose introducer sat in COMMAND POSITION

    Only 'subst_close' is new information, and it exists for one reason: the
    text after such a `)` is the ARGUMENT LIST of a command whose NAME was
    produced by the substitution (`$(which git) push --force`).  The command
    name is therefore unknowable statically, and the classifier must be able to
    say "unknown", not "no git" — see _residual_shapes().  A substitution that
    was NOT in command position (`echo $(date) status`) continues an existing
    argument list and is reported as 'separator', so it raises nothing.

    `in_quote` (added 2026-09-03) is True when the boundary that OPENED this
    segment fell inside an unterminated ' or " — i.e. the segment is a
    continuation line of a MULTI-LINE string literal, not a command.  It is
    computed by a PASSIVE OBSERVER: quote state is tracked alongside the scan
    but is never consulted when deciding where to split.  That is deliberate
    and load-bearing.  Making the splitter itself quote-aware would stop
    carving `git push --force` out of a multi-line quoted body, silently
    REMOVING an enumeration that iter_git_invocations() reports today — the
    dangerous under-block direction.  Only _residual_shapes() reads the flag.
    """
    out, buf, i, n = [], [], 0, len(c)
    # Stack of bools: was this open-paren's introducer in command position?
    subshell_stack = []
    kind = 'start'
    # Passive quote tracking; see `in_quote` in the docstring.
    sq = dq = esc = False
    in_quote = False

    def _buf_is_cmd_position():
        return all(ch.isspace() for ch in buf)

    def _flush(next_kind, cmd_pos_close=False):
        nonlocal buf, kind, in_quote, esc
        out.append((''.join(buf), kind, in_quote))
        buf = []
        kind = 'subst_close' if cmd_pos_close else next_kind
        # The NEXT segment opens in whatever quote state we are in right now.
        in_quote = sq or dq
        # Every separator branch routes through here, so this is the one place
        # a dangling escape (a `\` immediately before a separator) is cleared.
        esc = False

    while i < n:
        two = c[i:i + 2]
        if two in ('&&', '||'):
            _flush('separator'); i += 2; continue
        # Command/process substitution introducers open a command boundary; the
        # introducer char (`$`/`<`/`>`) is dropped from the outer segment.
        if two in ('$(', '<(', '>('):
            subshell_stack.append(_buf_is_cmd_position())
            _flush('separator'); i += 2; continue
        ch = c[i]
        if ch in ';\n|&`':
            _flush('separator'); i += 1; continue
        if ch == '(' and _buf_is_cmd_position():
            subshell_stack.append(False)
            _flush('separator'); i += 1; continue
        if ch == ')' and subshell_stack:
            was_cmd_position = subshell_stack.pop()
            _flush('separator', cmd_pos_close=was_cmd_position); i += 1; continue
        # Quote/escape bookkeeping. Reached only for chars that are NOT
        # separators, so it cannot influence where a split happens.
        if esc:
            esc = False
        elif ch == '\\' and not sq:
            esc = True
        elif ch == "'" and not dq:
            sq = not sq
        elif ch == '"' and not sq:
            dq = not dq
        buf.append(ch); i += 1
    out.append((''.join(buf), kind, in_quote))
    return out


def _basename(tok):
    return tok.rsplit('/', 1)[-1]


def _unquote_token(tok):
    """Strip balanced surrounding quotes: `"/usr/bin/git"` -> `/usr/bin/git`.

    Added 2026-08-08 (task dev-20260719-150041-a). Bash removes quotes before
    exec, so `"/usr/bin/git" clean -fd` runs git — but the raw token basenames
    to `git"`, so iter_git_invocations() recorded NO invocation and every guard
    built on it (bash-safety, git-privilege, runtime_guard) silently missed the
    command. Additive: a new helper, no existing signature or behaviour of
    _basename / _git_subcommand / _command_token_index is changed
    (pretool-block-branch-pr-worktree.py imports _git_subcommand directly).
    """
    t = tok.strip()
    while len(t) >= 2 and t[0] == t[-1] and t[0] in ('"', "'"):
        t = t[1:-1]
    return t


# Command WRAPPERS that prefix the real command token (basename match). The real
# command token is the first token after skipping leading env-var assignments
# (NAME=VALUE) and any of these wrappers. Only that one command token is
# classified — text that merely mentions git/gh later in the segment (e.g.
# `echo gh pr new`) is therefore NOT a creation.
_WRAPPERS = {
    'sudo', 'doas', 'env', 'xargs', 'time', 'nohup', 'setsid', 'stdbuf',
    'ionice', 'command', 'builtin', 'nice',
    # Added 2026-09-03: these also put the NEXT word in command position.
    'exec', 'eval', 'timeout', 'flock', 'chrt', 'taskset', 'unbuffer',
}

# Shell RESERVED WORDS (and the `!` negation operator) that may be followed
# IMMEDIATELY by a command word in the same segment.  Sourced from bash(1)
# "RESERVED WORDS": ! case coproc do done elif else esac fi for function if in
# select then time until while { } [[ ]].
#
# Included only where the grammar puts a COMMAND after the word.  Deliberately
# EXCLUDED, because the following token is a NAME/WORD and skipping it would
# manufacture a false git invocation out of e.g. `for git in a b; do …`:
#   for, select, case, in, function
# Also excluded because they TERMINATE a construct rather than introduce a
# command: fi, done, esac, }, ]], [[.
# `time` is already covered by _WRAPPERS above.
_SHELL_PREFIX_KEYWORDS = {
    'if', 'elif', 'then', 'else', 'while', 'until', 'do', '!', '{', 'coproc',
}

# Leading redirections, attached (`2>/dev/null`, `>out`, `&>log`, `{fd}>f`) and
# bare-operator (`2> /dev/null` — operator token, then its target token).
_REDIRECT_RE = re.compile(
    r'^(?:\{[A-Za-z_][A-Za-z0-9_]*\}|\d+)?'
    r'(?:<<<|<<-|<<|>>|&>>|&>|>&|<&|>\||<>|>|<)'
)

# Wrapper flags that consume the FOLLOWING token as their value.  Keyed by
# wrapper basename because the same short flag means different things to
# different wrappers: `sudo -n` is --non-interactive and takes NO value, while
# `nice -n` is the adjustment and DOES.  A single flat set would eat the `git`
# token of `sudo -n git status` and silently reopen the bypass.
_WRAPPER_VALUE_FLAGS = {
    'env': {'-u', '--unset'},
    'sudo': {'-u', '--user', '-g', '--group', '-U', '--other-user',
             '-p', '--prompt', '-r', '--role', '-t', '--type',
             '-C', '--close-from', '-h', '--host'},
    'doas': {'-u', '-C'},
    'nice': {'-n', '--adjustment'},
    'ionice': {'-c', '--class', '-n', '--classdata', '-p', '--pid'},
    'chrt': {'-p'},
    'taskset': {'-p', '-c', '--cpu-list'},
    'xargs': {'-n', '--max-args', '-P', '--max-procs', '-I', '--replace',
              '-L', '--max-lines', '-s', '--max-chars', '-d', '--delimiter',
              '-E', '-a', '--arg-file'},
    'timeout': {'-s', '--signal', '-k', '--kill-after'},
    'flock': {'-w', '--wait', '-E', '--conflict-exit-code'},
    'exec': {'-a'},
}

# Wrappers taking a mandatory POSITIONAL argument before the command word:
# `timeout <duration> git …`, `flock <file|fd> git …`.
_WRAPPER_POSITIONALS = {'timeout': 1, 'flock': 1}

_ENV_ASSIGN_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(?:\[[^]]*\])?\+?=')


def _command_token_index(toks):
    """Return the index of the segment's COMMAND token, or None.

    Skips every construct the shell permits BEFORE a command word:
      * env-var assignments            FOO=1  FOO+=1  arr[0]=1
      * shell reserved words           if  elif  then  else  while  until  do
                                       !  {  coproc
      * redirections                   2>/dev/null   >out   2> /dev/null
      * command wrappers               sudo env time nice timeout flock exec …
      * a wrapper's own option flags   env -i   env -u FOO   nice -n 5
      * a wrapper's positional arg     timeout 30   flock /tmp/lock

    Returns the index of the first real command token.

    Before 2026-09-03 this skipped only assignments and bare wrappers, so the
    command token of `if ! git commit -m x` resolved to `if` and the segment was
    classified as non-git.  Every consumer of this function — and of
    iter_git_invocations() built on it — was therefore blind to the entire
    keyword/prefix family.
    """
    i = 0
    n = len(toks)
    pending_positionals = 0
    last_wrapper = None
    while i < n:
        t = toks[i]
        if pending_positionals and not t.startswith('-'):
            pending_positionals -= 1
            i += 1
            continue
        if _ENV_ASSIGN_RE.match(t):
            i += 1
            continue
        if t in _SHELL_PREFIX_KEYWORDS:
            i += 1
            continue
        m = _REDIRECT_RE.match(t)
        if m:
            # Attached target (`2>/dev/null`) consumes one token; a bare
            # operator (`2>`) consumes its target token as well.
            i += 1 if len(t) > m.end() else 2
            continue
        base = _basename(_unquote_token(t))
        if base in _WRAPPERS:
            last_wrapper = base
            pending_positionals = _WRAPPER_POSITIONALS.get(base, 0)
            i += 1
            continue
        # A wrapper's own flags sit between the wrapper and the command word.
        if last_wrapper and t.startswith('-') and t != '--':
            if t in _WRAPPER_VALUE_FLAGS.get(last_wrapper, ()):
                i += 2
            else:
                i += 1
            continue
        if last_wrapper and t == '--':
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


# Git subcommands, used ONLY by the residual detector below to decide whether an
# unresolvable command token is followed by something that looks like a git verb.
# It is a precision filter, not a policy list: it exists so that
# `$(cat f) status` is treated as suspicious while `$(cat f) --version` is not.
_GIT_SUBCOMMANDS = frozenset("""
add am annotate apply archive bisect blame branch bundle checkout cherry
cherry-pick citool clean clone commit commit-tree config count-objects
describe diff diff-tree difftool fast-export fast-import fetch filter-branch
filter-repo for-each-ref format-patch fsck gc grep hash-object help init
instaweb log ls-files ls-remote ls-tree merge merge-base merge-file mergetool
mktag mktree mv name-rev notes pack-objects pull push range-diff read-tree
rebase reflog remote repack replace request-pull reset restore revert rev-list
rev-parse rm send-email shortlog show show-branch show-ref sparse-checkout
stash status stripspace submodule switch symbolic-ref tag update-index
update-ref verify-commit verify-pack whatchanged worktree write-tree
""".split())

_EXPANSION_RE = re.compile(r'\$[A-Za-z_{(]|\$\d|`')

# A leading `NAME=VALUE` assignment, anchored to the START of a segment.  It is
# match()ed per-segment rather than searched over the whole command text so that
# a `;` inside a string literal (`echo "x;G=echo"`) cannot fabricate one.
_ASSIGN_RE = re.compile(
    r'^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)=("[^"]*"|\'[^\']*\'|\S*)')
_VARREF_RE = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)')


def _assignments(segments):
    """Map NAME -> set of statically-visible values assigned in this command text.

    Only segments that are NOT inside a quote contribute, so string DATA that
    happens to contain `NAME=value` cannot seed the map.
    """
    out = {}
    for seg, _kind, in_quote in segments:
        if in_quote:
            continue
        m = _ASSIGN_RE.match(seg)
        if m:
            out.setdefault(m.group(1), set()).add(_unquote_token(m.group(2)))
    return out


def _resolves_to_non_git(tok, assigns):
    """True iff tok's expansions are pinned BY THIS SAME TEXT to something not git.

    This does not relax the fail-closed rule, it discharges it: the rule is
    "unknown command token => refuse", and a token whose value the command text
    assigns two lines earlier is not unknown.  `L="python3 ledger.py"; $L init`
    runs python3, and `init` being spelled the same as a git verb is a
    coincidence of English.

    Every path where the value is not pinned returns False (keep refusing):
    no assignment in this text, MORE THAN ONE distinct assigned value (ordering
    is unknowable statically), an empty value, or a value that is itself an
    expansion.  Substitution is applied to the WHOLE token and re-checked, so
    `G=g; ${G}it push` still reassembles to `git` and is still refused.

    Known limitation: an assignment that is syntactically present but does not
    execute (`false && G=echo`) is treated as pinning.  Closing that requires
    control-flow analysis; it is strictly narrower than the pre-existing hole
    that a single-line `bash -c "git push"` raises nothing at all.
    """
    refs = _VARREF_RE.findall(tok)
    if not refs:
        return False
    resolved = tok
    for braced, bare in refs:
        name = braced or bare
        values = assigns.get(name)
        if not values or len(values) != 1:
            return False
        value = next(iter(values))
        if not value or _EXPANSION_RE.search(value):
            return False
        resolved = resolved.replace('${%s}' % name if braced else '$%s' % name, value)
    if _EXPANSION_RE.search(resolved):
        return False
    words = resolved.split()
    return bool(words) and os.path.basename(_unquote_token(words[0])) != 'git'


def _dequote_all(tok):
    """Remove EVERY quote and escape char, as the shell would before exec.

    `_unquote_token` only strips BALANCED surrounding quotes, so it correctly
    resolves `"git"` but not `g\\it`, `gi""t` or `"gi"t` — all three of which the
    shell executes as `git`.  This is deliberately more aggressive than
    `_unquote_token` and is used ONLY to RAISE SUSPICION (never to classify an
    invocation), so its over-eagerness cannot create a silent allow.
    """
    return tok.replace('"', '').replace("'", '').replace('\\', '')


def _is_command_name_shaped(tok):
    """True iff tok could be a COMMAND NAME at all, rather than a shard of prose.

    Measured against 71,598 real harness commands: a naive `.split()` breaks a
    multi-word quoted string (`"git clean -n "`, `'git ls-files ...`) into a
    leading token carrying ONE unbalanced quote.  Those are string literals
    inside embedded Python/JSON heredocs, not command names — the shell never
    execs them — and they accounted for 147 of 150 raw residual hits.  Three
    structural tests separate them from real command names:

      * quotes must BALANCE.  `gi""t` / `"gi"t` / `''git` are all `git` to the
        shell and balance; `"git` (an opened string) does not.
      * no BACKSLASH-ESCAPED QUOTE (`\\"`).  A backslash before a quote is
        string-literal escaping from an embedding language; a backslash before
        an ordinary character (`g\\it`) is shell escaping of a command name.
      * no TRAILING backslash.  It escapes nothing inside the token, so it
        cannot be part of a command NAME.  In practice it is _segments()
        splitting a grep alternation (`grep "ls-files\\|git\\|tracked"`) at the
        `|`, leaving the fragment `git\\`.  No genuine obfuscation (`g\\it`,
        `\\git`, `gi""t`) ends in a backslash.

    Extracted from _is_obfuscation_candidate() 2026-09-03 so the DYNAMIC branch
    of _residual_shapes() can apply the same test.  That branch previously
    checked only "looks like an expansion" + "next word is a git verb", so any
    line of string DATA beginning with an expansion-shaped shard was refused —
    and the git subcommand set is full of ordinary English verbs (init status
    log config add clean help describe pull show grep mv rm tag).
    """
    if tok.count('"') % 2 or tok.count("'") % 2:
        return False
    if '\\"' in tok or "\\'" in tok:
        return False
    if tok.endswith('\\'):
        return False
    return True


def _is_obfuscation_candidate(tok):
    """True iff tok is a plausibly-obfuscated COMMAND NAME rather than prose."""
    return _is_command_name_shaped(tok) and os.path.basename(_dequote_all(tok)) == 'git'


def _residual_shapes(command_text):
    """Yield (kind, segment) for command tokens that MIGHT be git but did not parse.

    This is the answer to "an empty invocation list must not mean 'no git'".
    It is deliberately NARROW: it fires only on the segment's COMMAND TOKEN, so
    the overwhelmingly common `grep git .` / `echo "git status"` / `cat git.md`
    shapes — git in ARGUMENT position, behind a resolvable command name — raise
    nothing at all and stay on the fast permissive path.

    Kinds:
      obfuscated_git_token  — the command token de-obfuscates to `git` but did
                              not classify as git (`g\\it push`, `gi""t push`)
      dynamic_git_token     — the command token contains an unexpanded
                              parameter/command expansion and the next word is a
                              git verb (`$GIT push`, `${G}it commit`)
      substituted_git_token — the segment's command NAME was produced by a
                              command substitution in command position and the
                              first word here is a git verb (`$(which git) push`)
    """
    segments = _segments_with_kind(command_text)
    assigns = _assignments(segments)
    for seg, kind, in_quote in segments:
        if in_quote:
            # Mechanism (b): this segment is a continuation line of a multi-line
            # string literal, so its first token is DATA, not a command word.
            continue
        toks = seg.split()
        if not toks:
            continue
        idx = _command_token_index(toks)
        if idx is None:
            continue
        tok = toks[idx]
        if os.path.basename(_unquote_token(tok)) == 'git':
            continue  # resolved normally; iter_git_invocations already has it
        sub, _rest = _git_subcommand(toks[idx + 1:])
        if _is_obfuscation_candidate(tok):
            yield ('obfuscated_git_token', seg)
        elif (_EXPANSION_RE.search(tok) and sub in _GIT_SUBCOMMANDS
                # Mechanism (a): the shape filter the obfuscation branch has
                # always applied. An unbalanced quote means `.split()` cut a
                # string literal in half; the shell never execs that shard.
                and _is_command_name_shaped(tok)
                and not _resolves_to_non_git(tok, assigns)):
            yield ('dynamic_git_token', seg)
        elif kind == 'subst_close' and idx == 0 and tok in _GIT_SUBCOMMANDS:
            yield ('substituted_git_token', seg)


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
    (basename match after stripping balanced surrounding quotes, so both
    /usr/bin/git and "/usr/bin/git" are recognised).

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
        # Unquote before basenaming: bash strips the quotes before exec, so
        # `"/usr/bin/git"` and `'git'` are git invocations (fail-closed fix).
        if os.path.basename(_unquote_token(token)) != 'git':
            continue
        after_git = toks[idx + 1:]
        subcommand, remaining_args = _git_subcommand(after_git)
        yield GitInvocation(
            cmd_token=token,
            path_qualified=('/' in token),
            subcommand=subcommand,
            args=remaining_args,
        )


def classify_git_command(command_text):
    """Return (invocations, residuals) — the fail-closed-capable entry point.

    `invocations` is exactly `list(iter_git_invocations(command_text))`.
    `residuals` is a list of (kind, segment) from _residual_shapes(): command
    tokens that could not be resolved statically but look like they could be
    git.

    Callers that enforce policy MUST NOT treat an empty `invocations` list as
    proof that no git runs.  The correct fail-closed test is:

        invocations, residuals = classify_git_command(cmd)
        if residuals:
            refuse(...)          # unparseable AND git-shaped
        if not invocations:
            return               # genuinely git-free: stay fast and permissive

    Splitting the two keeps the permissive fast path intact for the vast
    majority of traffic (no git token in command position at all) while denying
    the narrow, precise case the old `if not invocations: return` swallowed.
    """
    return list(iter_git_invocations(command_text)), list(_residual_shapes(command_text))


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
