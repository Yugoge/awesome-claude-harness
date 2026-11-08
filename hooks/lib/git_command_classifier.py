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
#
# Shell `-c` strings (2026-11-07): `bash -c "git commit -m y"` runs git under
#   the command token `bash`.  Each shell's `-c` string is resolved and
#   classified as a command line of its own (see _shell_layers()); one the
#   scan cannot resolve is the residual `unresolved_shell_string`.

CLI usage:
  printf 'command text\\n' | python3 hooks/lib/git_command_classifier.py
  CMD_INPUT='command text' python3 hooks/lib/git_command_classifier.py
  Output: JSON array of {"subcommand": str, "args": list, "path_qualified": bool,
  "nested": bool}; `nested` marks an invocation inside a shell `-c` string.

Prefilter hint for callers:
  printf '%s\\n' "$COMMAND_CONTEXT_STRIPPED" | grep -q 'git' before spawning
  python3 to avoid unnecessary subprocess overhead.

Normalization contract:
  In CLI mode this module does NOT call bash_context_strip/_norm before
  _segments().  Normalization is the CALLER's responsibility.
  pretool-bash-safety.sh MUST feed COMMAND_CONTEXT_STRIPPED (already
  normalized by bash_context_strip.py at lines 733-743), NOT raw $COMMAND.
  That view no longer shows where a `-c` string ends, so with CMD_RAW=stdin
  the caller writes the view, a NUL, then the raw command: the strings are
  resolved from the raw command and each one is normalized the same way
  before it is classified.
"""

import collections
import functools
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

    A `\\` immediately followed by a newline is a line CONTINUATION, not a
    separator: both characters are folded away before the newline can open a
    boundary, so a single logical command written across multiple physical
    lines (`python3 x.py \\\n  --flag a \\\n  --flag b`) stays one segment and
    its trailing flags are not orphaned into segments of their own (root cause
    of the 2026-10-05 execute-push grant-guard false rejection — see
    `_segments_with_kind()` for the exact fold condition).
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

    Backslash-newline folding (2026-10-05) is a NARROW exception to the
    "never consulted when deciding where to split" rule above, and it does
    not weaken it: a `\\<newline>` pair is not a quoted separator being
    suppressed, it is a construct bash itself deletes before the separator
    would ever exist, in or out of double quotes (`a="x\\<newline>y"` -> `xy`;
    verified against bash directly). The fold fires only when `esc` is true
    at a `\n`, i.e. the immediately preceding character was a single
    unescaped backslash NOT inside single quotes (the `not sq` guard on
    `esc`'s own assignment below). That precisely excludes the two shapes
    that must NOT fold:
      * a backslash INSIDE single quotes (`'line1\\<newline>line2'`) never
        sets `esc` (bash: single quotes suppress all escaping), so the
        newline still opens a real 'separator' boundary — unchanged, and
        still the deliberate quote-blind split the ENUMERATION MONOTONICITY
        tests above depend on;
      * a backslash that is itself ESCAPED (`\\\\<newline>`, i.e. a literal
        trailing backslash) consumes its OWN escape one character earlier
        (the `if esc: esc = False` branch) and leaves `esc` False by the
        time the newline is reached, so that newline also still splits.
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
        # Backslash-newline is a real shell LINE CONTINUATION, not a command
        # boundary: bash deletes both characters and joins the next physical
        # line onto this one (verified: `a="x\<newline>y"` -> `xy`, no space
        # inserted). `esc` is true here iff the immediately preceding char was
        # an unescaped backslash outside single quotes -- exactly bash's own
        # continuation condition: a backslash inside '...' never sets esc (the
        # `not sq` guard below), so a single-quoted multi-line literal keeps
        # splitting on its embedded newline exactly as before (quote-blind by
        # design, see the class docstring); an ESCAPED backslash (`\\`) before
        # the newline consumes its own escape one char earlier and leaves esc
        # False, so a literal trailing `\\` still splits as a real boundary.
        # Because esc can only just have been set by the previous character,
        # buf's last char is always the backslash that set it.
        if ch == '\n' and esc:
            buf.pop()
            esc = False
            i += 1
            continue
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
    control-flow analysis.
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


# ---------------------------------------------------------------------------
# Shell `-c` strings
# ---------------------------------------------------------------------------
# A shell's `-c` string is a command line the shell parses again, so the
# segment walk above sees only the shell's name as the command token.  The scan
# below reads the command text with the shell's own quoting rules, finds each
# shell in command position and its `-c` string, and returns that string as a
# command line of its own; iter_git_invocations() and _residual_shapes() then
# treat it exactly as they treat a plain command.  A string the scan cannot
# know is a residual, never "no git": one holding an expansion or substitution
# the OUTER shell performs (outside single quotes; the inner shell parses its
# run-time value as commands), one whose quoting the scan cannot follow, and
# one nested deeper than _MAX_SHELL_DEPTH.

_MAX_SHELL_DEPTH = 4
# A shell is known by the SHAPE of its name (bash, sh, dash, zsh, ksh93, rbash,
# ...), as pretool-bash-safety.sh's clean rule knows it: a name list is what let
# unlisted shells through there.  No dot before `sh`: `deploy.sh` is a script.
_SHELL_NAME_RE = re.compile(r'[^/\s.]*sh[0-9.]*\Z')
_SHELL_HINT_RE = re.compile(r'sh[0-9.]*["\']?\s')
# A shell word, its options, then an option cluster holding `c`: what makes a
# text the scan cannot lex a residual rather than git-free.
_SHELL_C_SHAPE_RE = re.compile(r'sh[0-9.]*["\']?\s+(?:[-+]\S*\s+(?:\w+\s+)?)*-[A-Za-z]*c')
_REDIR_OP_RE = re.compile(r'&>>?|<<<|<<-|<<|>>|>&|<&|>\||<>|>|<')
_RUNTIME = '\x00'  # stands for text the shell computes at run time


def _skip_backtick(text, i):
    """Index just past the backtick closing a substitution whose body starts at i."""
    while i < len(text):
        if text[i] == '\\':
            i += 2
        elif text[i] == '`':
            return i + 1
        else:
            i += 1
    raise ValueError('unterminated backtick')


def _skip_dquote(text, i):
    """Index just past the `"` closing a double-quoted string whose body starts at i."""
    while i < len(text):
        ch = text[i]
        if ch == '\\':
            i += 2
        elif ch == '"':
            return i + 1
        elif ch == '`':
            i = _skip_backtick(text, i + 1)
        elif text.startswith(('$(', '${'), i):
            i = _skip_group(text, i + 2, ')' if text[i + 1] == '(' else '}')
        else:
            i += 1
    raise ValueError('unterminated double quote')


def _skip_group(text, i, close):
    """Index just past the `close` ending a $( ) or ${ } whose body starts at i."""
    opener, depth = '(' if close == ')' else '{', 1
    while i < len(text):
        ch = text[i]
        if ch == '\\':
            i += 2
            continue
        if ch == "'":
            j = text.find("'", i + 1)
            if j < 0:
                raise ValueError('unterminated single quote')
            i = j + 1
            continue
        if ch == '"':
            i = _skip_dquote(text, i + 1)
            continue
        if ch == '`':
            i = _skip_backtick(text, i + 1)
            continue
        if ch == opener:
            depth += 1
        elif ch == close:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError('unterminated substitution')


def _expansion(text, i, quoted=False):
    """(end, body) of the expansion at text[i] (`$` or a backtick), or None for a plain `$`.

    body is the text a substitution runs as commands (None for a parameter).
    quoted: text[i] is inside double quotes, where `$'` and `$"` are a plain `$`.
    """
    if text[i] == '`':
        end = _skip_backtick(text, i + 1)
        return end, re.sub(r'\\([\\`$])', r'\1', text[i + 1:end - 1])
    nxt = text[i + 1:i + 2]
    if nxt in ('(', '{'):
        end = _skip_group(text, i + 2, ')' if nxt == '(' else '}')
        return end, text[i + 2:end - 1]
    if quoted and nxt in ('"', "'"):
        return None
    if nxt == "'":  # $'...': its escapes are not modelled, so its value is unknown here
        j = i + 2
        while j < len(text) and text[j] != "'":
            j += 2 if text[j] == '\\' else 1
        if j >= len(text):
            raise ValueError("unterminated $'")
        return j + 1, None
    if nxt == '"':  # $"...": a translated string
        return _skip_dquote(text, i + 2), None
    if nxt.isdigit() or (nxt and nxt in '@*#?-$!'):
        return i + 2, None
    if nxt.isalpha() or nxt == '_':
        j = i + 2
        while j < len(text) and (text[j].isalnum() or text[j] == '_'):
            j += 1
        return j, None
    return None


def _shell_words(text):
    """Split shell text into simple commands of words, with the shell's quoting.

    Returns (commands, bodies).  A command is a list of (value, runtime) words:
    value is the word as the command receives it, quotes and escapes removed and
    each expansion replaced by _RUNTIME; runtime is True when it holds one.
    bodies are texts that run as commands of their own: the bodies of $( ),
    backtick and <( ) >( ) substitutions, and of here-documents.  Raises
    ValueError on quoting the scan cannot follow.
    """
    cmds, words, bodies, heredocs = [], [], [], []
    st = {'buf': [], 'runtime': False, 'inword': False, 'pending': None}

    def add(part, runtime=False):
        st['buf'].append(part)
        st['inword'] = True
        st['runtime'] = st['runtime'] or runtime

    def end_word():
        if st['inword']:
            value = ''.join(st['buf'])
            if st['pending']:
                heredocs.append((value, st['pending'] == '<<-'))
                st['pending'] = None
            elif value.lstrip('0123456789') in ('<<', '<<-'):
                st['pending'] = value.lstrip('0123456789')
            words.append((value, st['runtime']))
        st.update(buf=[], runtime=False, inword=False)

    def end_cmd():
        end_word()
        if words:
            cmds.append(list(words))
        del words[:]

    def expand(i, quoted=False):
        exp = _expansion(text, i, quoted)
        if exp is None:
            add('$')
            return i + 1
        end, body = exp
        if body is not None:
            bodies.append(body)
        add(_RUNTIME, runtime=True)
        return end

    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '\\':
            if text[i + 1:i + 2] != '\n':  # a backslash-newline joins the lines
                add(text[i + 1:i + 2])
            i += 2
        elif ch == "'":
            j = text.find("'", i + 1)
            if j < 0:
                raise ValueError('unterminated single quote')
            add(text[i + 1:j])
            i = j + 1
        elif ch == '"':
            add('')
            i += 1
            while text[i:i + 1] != '"':
                if i >= n:
                    raise ValueError('unterminated double quote')
                if text[i] == '\\' and text[i + 1:i + 2] in ('$', '`', '"', '\\', '\n'):
                    add(text[i + 1].replace('\n', ''))
                    i += 2
                elif text[i] in '$`':
                    i = expand(i, quoted=True)
                else:
                    add(text[i])
                    i += 1
            i += 1
        elif ch in '$`':
            i = expand(i)
        elif ch in ' \t':
            end_word()
            i += 1
        elif ch == '#' and not st['inword']:
            j = text.find('\n', i)
            i = n if j < 0 else j
        elif ch == '\n':
            end_cmd()
            i += 1
            for delim, tabs in heredocs:  # the body follows the line that opened it
                body = []
                while i < n:
                    j = text.find('\n', i)
                    j = n if j < 0 else j
                    line, i = text[i:j], j + 1
                    if (line.lstrip('\t') if tabs else line) == delim:
                        break
                    body.append(line)
                bodies.append('\n'.join(body))
            del heredocs[:]
        elif ch in '<>' and text[i + 1:i + 2] == '(':
            end = _skip_group(text, i + 2, ')')
            bodies.append(text[i + 2:end - 1])
            add(_RUNTIME, runtime=True)
            i = end
        elif ch in '<>' or text.startswith('&>', i):
            if st['inword'] and not ''.join(st['buf']).isdigit():
                end_word()
            m = _REDIR_OP_RE.match(text, i)
            add(m.group())
            i = m.end()
            end_word()
        elif ch in ';&|()':
            end_cmd()
            i += 1
        else:
            add(ch)
            i += 1
    end_cmd()
    return cmds, bodies


def _shell_c_operand(words, i):
    """Index of the `-c` command string among a shell's arguments from words[i], or None."""
    seen_c = maybe_c = False
    while i < len(words):
        value, runtime = words[i]
        if runtime:
            if seen_c:  # the -c string itself
                break
            maybe_c = True  # an unknown word may be any option, -c included
            i += 1
            continue
        if value in ('--', '-'):
            i += 1
            break
        if value.startswith('--'):
            i += 2 if value in ('--rcfile', '--init-file') else 1
        elif len(value) > 1 and value[0] in '-+':
            seen_c = seen_c or 'c' in value[1:]
            # -o / -O take an option name each
            i += 1 + value[1:].count('o') + value[1:].count('O')
        else:
            break
    return i if (seen_c or maybe_c) and i < len(words) else None


def _shell_c_strings(text):
    """Yield ('text', string) for each shell `-c` string in text, ('unresolved', text) for one it cannot know."""
    if not _SHELL_HINT_RE.search(text):
        return
    try:
        cmds, bodies = _shell_words(text)
    except Exception:  # quoting the scan cannot follow, or nesting past the interpreter's own limit
        if _SHELL_C_SHAPE_RE.search(text):
            yield 'unresolved', text
        return
    for words in cmds:
        values = [v for v, _runtime in words]
        idx = _command_token_index(values)
        if idx is None or words[idx][1] or not _SHELL_NAME_RE.match(_basename(values[idx])):
            continue
        op = _shell_c_operand(words, idx + 1)
        if op is None:
            continue
        if words[op][1]:
            yield 'unresolved', ' '.join(values).replace(_RUNTIME, '$...')
        else:
            yield 'text', words[op][0]
    for body in bodies:
        yield from _shell_c_strings(body)


@functools.lru_cache(maxsize=32)
def _shell_layers(command_text):
    """(texts, unresolved) for command_text.

    texts: command_text, then the text of every shell `-c` string it runs, in
    the order they appear, resolved recursively up to _MAX_SHELL_DEPTH levels.
    unresolved: the `-c` strings that could not be resolved, and those nested
    past the limit.
    """
    texts, unresolved = [], []

    def visit(text, depth):
        texts.append(text)
        for kind, value in _shell_c_strings(text):
            if kind == 'unresolved' or depth >= _MAX_SHELL_DEPTH:
                unresolved.append(value)
            else:
                visit(value, depth + 1)

    try:
        visit(command_text, 0)
    except Exception:  # never let the scan cost the plain text its own checks
        shaped = _SHELL_C_SHAPE_RE.search(command_text)
        return (command_text,), ((command_text,) if shaped else ())
    return tuple(texts), tuple(unresolved)


def iter_shell_texts(command_text):
    """Yield command_text, then the text of every shell `-c` string it runs."""
    return iter(_shell_layers(command_text)[0])


def _residual_shapes(command_text):
    """Yield (kind, segment) for command tokens that MIGHT be git but did not parse.

    Every shell `-c` string the text runs is examined like the text itself, and
    one that cannot be resolved is the kind `unresolved_shell_string`.
    """
    texts, unresolved = _shell_layers(command_text)
    for text in texts:
        yield from _segment_residual_shapes(text)
    for text in unresolved:
        yield ('unresolved_shell_string', text)


RESIDUAL_KINDS = frozenset({'obfuscated_git_token', 'dynamic_git_token',
                            'substituted_git_token', 'unresolved_shell_string'})


def _segment_residual_shapes(command_text):
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

    The text of every shell `-c` string command_text runs is walked the same
    way, after command_text's own segments (see _shell_layers()).
    """
    for text in iter_shell_texts(command_text):
        yield from _segment_invocations(text)


def _segment_invocations(command_text):
    """iter_git_invocations() for command_text's own segments only."""
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

    if os.environ.get('CMD_RAW') == 'stdin':
        # A normalized view, a NUL, then the raw command it was made from: the
        # view no longer shows where a `-c` string ends (normalization contract).
        cmd_text, _nul, raw = cmd_text.partition('\0')
        try:
            from bash_context_strip import strip_non_executable_contexts as _norm
        except Exception:
            _norm = str
        layers = [cmd_text] + [_norm(text) for text in list(iter_shell_texts(raw))[1:]]
    else:
        layers = list(iter_shell_texts(cmd_text))
    results = []
    for k, text in enumerate(layers):
        for inv in _segment_invocations(text):
            results.append({
                'subcommand': inv.subcommand,
                'args': inv.args,
                'path_qualified': inv.path_qualified,
                'nested': k > 0,
            })
    print(json.dumps(results))
    sys.exit(0)
