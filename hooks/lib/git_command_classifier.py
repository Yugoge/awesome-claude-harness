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
#   scan cannot clear is the residual `unresolved_shell_string`.
#
# Git-shaped `-c` strings only (2026-11-08, PR #15 review finding 1): that
#   residual refused `bash -c "cd $DIR && npm test"`, text the scan could not
#   lex and every here-document body.  A string holding a run-time value is a
#   residual only when it is git-shaped (_may_run_git), and a here-document is
#   shell text only when a shell may read it (_reads_as_shell).
#
# Run-time code in a `-c` layer (2026-11-08, train 2): that narrowing let a
#   layer hand its run-time text to a shell or an interpreter inside it
#   (`bash -c "echo $X | sh"`, `bash -c "python3 -c $P"`, `bash -c "watch $X"`).
#   Such a layer is also a residual when a command in it may run text computed
#   at run time as shell or code (_runs_runtime_code).
#
# Fail closed on the unknown (2026-11-08, train 2): a list of dangerous programs
#   can never be complete, so _command_runs_runtime_code now refuses a run-time
#   word given to a program it does NOT model, keeping it only for the programs
#   known to treat their words as data (_DATA_ONLY_COMMANDS).  So a layer running
#   `octave --eval $X`, `erl -eval $X`, `chroot / $X`, `strace $X` or
#   `find . -exec $X \\;` is a residual, a run-time environment assignment to a
#   command (`BASH_ENV=$F bash …`, `NODE_OPTIONS=--require=$F node …`) is one
#   unless the variable cannot load code (_SAFE_ENV_VARS), and a run-time `-c`
#   value the outer shell built by running code (`bash -c "y=$(echo $X | sh)"`)
#   is one.  echo/printf/grep and the data commands keep their run-time word.

CLI usage:
  printf 'command text\\n' | python3 hooks/lib/git_command_classifier.py
  CMD_INPUT='command text' python3 hooks/lib/git_command_classifier.py
  Output: JSON array of {"subcommand": str, "args": list, "path_qualified": bool,
  "nested": bool}; `nested` marks an invocation inside a shell `-c` string.

Prefilter hint for callers:
  printf '%s\\n' "$COMMAND_CONTEXT_STRIPPED" | grep -q 'git' before spawning
  python3 to avoid unnecessary subprocess overhead.

Normalization contract:
  iter_git_invocations() and classify_git_command() normalise their own input,
  in CLI mode too, so a caller passes the command as written (see
  iter_git_invocations). pretool-bash-safety.sh's COMMAND_CONTEXT_STRIPPED, an
  already-normalised command, reads the same. That view no longer shows where
  a `-c` string ends, so with CMD_RAW=stdin the caller writes the view, a NUL,
  then the raw command: the strings are resolved from the raw command and each
  one is normalized the same way before it is classified.
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
    dangerous under-block direction.  Only _residual_shapes() and
    iter_git_invocations() read the flag.

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


# The git global-option table: the options git accepts between `git` and the
# subcommand, as git parses them. git 2.43 accepts each form below but
# --super-prefix (dropped before it), --shallow-file=<file> (it takes the two-word
# form only), --no-lazy-fetch and --no-advice (added after 2.43); the table keeps
# them for the gits that take them. Every hook that locates a git subcommand or
# reads a global option uses it.
#   GIT_GLOBAL_VALUE_OPTS  take a value as the next word, the long ones also as
#                          `--opt=<value>`; git rejects `-C<dir>` and `-cname=value`.
#   GIT_GLOBAL_FLAGS       take no separate value; `--exec-path` and `--list-cmds`
#                          take theirs only as `=<value>` (a bare `git --exec-path`
#                          prints the path and exits).
GIT_GLOBAL_VALUE_OPTS = frozenset({
    '-C', '-c', '--git-dir', '--work-tree', '--namespace', '--super-prefix',
    '--config-env', '--attr-source', '--shallow-file',
})
GIT_GLOBAL_FLAGS = frozenset({
    '-p', '--paginate', '-P', '--no-pager', '--bare', '--no-replace-objects',
    '--literal-pathspecs', '--no-literal-pathspecs', '--glob-pathspecs',
    '--noglob-pathspecs', '--icase-pathspecs', '--no-optional-locks',
    '--no-lazy-fetch', '--no-advice', '--html-path', '--man-path', '--info-path',
    '-v', '--version', '-h', '--help', '--exec-path', '--list-cmds',
})
# The value options' name before the table split, for the code that still imports
# it (the privilege guard's commit reads and the branch hook on another stream):
# every lookup is "does this option take the next word?", which the table answers.
# The old set differed: it held --exec-path, whose value git takes only as
# `--exec-path=<dir>` (a bare one prints the path and exits, running no
# subcommand), and lacked --attr-source and --shallow-file, so it read
# `git --attr-source HEAD commit` as the subcommand `HEAD`.
_GIT_GLOBAL_VALUE = GIT_GLOBAL_VALUE_OPTS


def _git_subcommand(args):
    """Return (subcommand, remaining_args) skipping git global options."""
    i = 0
    while i < len(args):
        a = args[i]
        if a in GIT_GLOBAL_VALUE_OPTS:
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
# treat it exactly as they treat a plain command.
#
# A string holding an expansion or substitution the OUTER shell performs
# (outside single quotes; the inner shell parses its run-time value as
# commands) is read the same way, each run-time value a placeholder.  It is the
# residual `unresolved_shell_string` only when it is git-shaped
# (_may_run_git): the narrow test the plain-text residual uses finds git in it,
# or one of its command words is a run-time value with no static word after it
# that clears it.  So `bash -c "git $SUB"` and `bash -c "$CMD"` are residuals,
# and `bash -c "cd $DIR && npm test"` runs npm, as `cd $DIR && npm test` does.
# Text whose quoting the scan cannot follow is a residual when what follows its
# shell `-c` is git-shaped; a string nested deeper than _MAX_SHELL_DEPTH always
# is.  A here-document is shell text only when a shell may read it
# (_reads_as_shell); for any other reader it runs only the substitutions the
# outer shell performs to expand it, and none when its delimiter is quoted.
#
# A string holding a run-time value is also the residual when it, or a string
# it runs, may run text computed at run time as shell or code
# (_runs_runtime_code), as a run-time command word already is: a shell or an
# interpreter fed that text through a pipe, a here-string, a here-document or a
# file, or given it as its script or code; source and `.` given a run-time
# file; eval, trap and the launchers that hand their arguments to a shell given
# a run-time word.  `bash -c "echo $X | sh"` is a residual, as dfc90534 had it,
# while `echo $X | sh` alone keeps its plain-text decision (P9-31).  Because a
# list of dangerous programs can never be complete, the rule fails closed: a
# program it does not model, given a run-time word, runs it (so the layer is a
# residual) unless the program keeps its words as data (_DATA_ONLY_COMMANDS); a
# run-time environment assignment to a command may load code unless the variable
# cannot (_SAFE_ENV_VARS); and a run-time `-c` value the outer shell built by
# running code (`bash -c "y=$(echo $X | sh)"`) is a residual too.

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
_REDIR_WORD_RE = re.compile(r'[0-9]*(?:%s)' % _REDIR_OP_RE.pattern)
_RUNTIME = '\x00'  # stands for text the shell computes at run time
# A run-time value as a layer's text shows it: an expansion no assignment pins.
_RUNTIME_PLACEHOLDER = '${__runtime__}'
_RUNTIME_PLACEHOLDER_RE = re.compile(re.escape(_RUNTIME_PLACEHOLDER))
# Commands that hand their standard input to a shell, besides the shells.
_STDIN_SHELL_COMMANDS = frozenset({
    'ssh', 'su', 'runuser', 'source', '.', 'at', 'batch', 'parallel', 'script',
})

# _runs_runtime_code's tables.  Commands that run their arguments as shell text
# or code, or hand them to a shell, in ways the scan does not model (builtins
# that keep shell text for later, launchers, GNU sed's `e`, an editor's -c):
# any run-time word among their arguments, and any input fed to them, may run.
_RUNTIME_ARG_COMMANDS = frozenset({
    'alias', 'trap', 'at', 'batch', 'parallel', 'runuser', 'screen', 'script',
    'ssh', 'su', 'tmux', 'watch', 'sed', 'gsed', 'ex', 'nvim', 'vi', 'view', 'vim',
})
# A list of dangerous programs can never be complete, so _command_runs_runtime_code
# fails closed: a program it does not otherwise model, given a run-time word, is
# assumed to run it as a command or as code.  _DATA_ONLY_COMMANDS names the
# programs known to keep their words (and input) as data — a filename, a URL, a
# host, a number, a target — never a command or code to execute.  Anything not
# listed and not modelled elsewhere (a shell, an interpreter, source/`.`, the
# _RUNTIME_ARG_COMMANDS, a launcher naming a shell) is refused on a run-time word.
# Membership is the safe-to-add test: a program belongs here only when NO option
# or operand of it runs a command or loads code.  So `tar` (--to-command/`-I`),
# `rsync`/`nc`/`scp` (their command options), `find` (-exec), `sort`
# (--compress-program), `wget` (--use-askpass), and every interpreter and
# launcher are deliberately absent; a run-time word to any of them stays refused.
_DATA_ONLY_COMMANDS = frozenset({
    # the file, text and information utilities whose operands are data
    'cat', 'tee', 'cd', 'pwd', 'ls', 'head', 'tail', 'wc', 'uniq', 'cut',
    'tr', 'rev', 'tac', 'nl', 'fold', 'paste', 'join', 'comm', 'column', 'cp', 'mv',
    'rm', 'ln', 'mkdir', 'rmdir', 'touch', 'chmod', 'chown', 'chgrp', 'stat', 'file',
    'readlink', 'realpath', 'basename', 'dirname', 'mktemp', 'truncate', 'du', 'df',
    'date', 'seq', 'true', 'false', 'test', 'sleep', 'diff', 'cmp', 'base64', 'cksum',
    'md5sum', 'sha1sum', 'sha256sum', 'od', 'hexdump', 'xxd', 'strings',
    # network fetch and lookups whose operands are a URL or a host, not a command
    'curl', 'ping', 'host', 'dig', 'nslookup',
    # a container client: its sub-command is data (`docker push $IMAGE`); a shell it
    # is told to run (`docker exec c bash -c $X`) is caught by the launcher scan.
    'docker', 'podman', 'kubectl',
})
# Variables whose run-time value, assigned to a command's environment, cannot load
# code.  The inverse of _DATA_ONLY_COMMANDS: a run-time environment assignment is
# refused unless the variable is listed, because BASH_ENV, ENV, NODE_OPTIONS,
# PERL5OPT, PYTHONSTARTUP, RUBYOPT, LD_PRELOAD and their kind each turn a run-time
# value into code the next command runs, and such a list can never be complete.
_SAFE_ENV_VARS = frozenset({
    'LANG', 'LANGUAGE', 'LC_ALL', 'LC_CTYPE', 'LC_COLLATE', 'LC_MESSAGES',
    'LC_NUMERIC', 'LC_TIME', 'TZ', 'TERM', 'COLUMNS', 'LINES', 'HOME', 'PWD',
    'OLDPWD', 'USER', 'LOGNAME', 'HOSTNAME', 'TMPDIR', 'DISPLAY', 'NO_COLOR',
    'FORCE_COLOR', 'CLICOLOR', 'CLICOLOR_FORCE',
})
# A shell named among another command's words (`find -exec sh -c`, `docker exec
# c bash`), by name: the shape _SHELL_NAME_RE reads also matches `push`.
_EMBEDDED_SHELL_RE = re.compile(r'(?:ba|rba|da|a|z|k|mk|c|tc|fi|y|pw)?sh[0-9.]*\Z')
# Interpreters whose option grammar the scan does not model: as above.
_OPAQUE_INTERPRETERS = frozenset({
    'bun', 'deno', 'elixir', 'expect', 'groovy', 'guile', 'irb', 'julia',
    'osascript', 'powershell', 'racket', 'sbcl', 'scala', 'ts-node', 'tsx',
})
# Interpreters by the shape of their name, and how each is told its program
# (_interpreter_runs_runtime).  program: short options whose value is the
# program (inline code, or a file or module it runs); value: short options
# whose value may load code, unless `data` names them; both take the rest of
# their cluster, else the next word.  attached: short options whose value is
# only the rest of their cluster.  long_program, long_value: the long forms,
# `--opt=value` or `--opt value`.  stdin: with no program named it reads one
# from standard input.  stop: an option naming the program ends the options.
# The first operand is the program unless an option named one; the words after
# the program are its arguments.  An option no table names takes no value.
_Interpreter = collections.namedtuple(
    '_Interpreter', 'program value attached long_program long_value data stdin stop')
_NODE_VALUE_OPTIONS = frozenset({  # `node --help`, v22: the options shown with `=...`
    '--allow-fs-read', '--allow-fs-write', '--build-snapshot-config', '--conditions',
    '--cpu-prof-dir', '--cpu-prof-interval', '--cpu-prof-name', '--diagnostic-dir',
    '--disable-proto', '--disable-warning', '--dns-result-order', '--env-file',
    '--env-file-if-exists', '--experimental-config-file', '--experimental-default-type',
    '--experimental-loader', '--experimental-sea-config', '--experimental-test-isolation',
    '--heap-prof-dir', '--heap-prof-interval', '--heap-prof-name',
    '--heapsnapshot-near-heap-limit', '--heapsnapshot-signal', '--icu-data-dir', '--import',
    '--input-type', '--inspect-publish-uid', '--loader', '--localstorage-file',
    '--max-http-header-size', '--max-old-space-size-percentage',
    '--network-family-autoselection-attempt-timeout', '--openssl-config',
    '--redirect-warnings', '--report-filename', '--report-signal', '--require',
    '--secure-heap', '--secure-heap-min', '--snapshot-blob', '--test-concurrency',
    '--test-coverage-branches', '--test-coverage-exclude', '--test-coverage-functions',
    '--test-coverage-include', '--test-coverage-lines', '--test-name-pattern',
    '--test-reporter', '--test-reporter-destination', '--test-shard', '--test-skip-pattern',
    '--test-timeout', '--title', '--tls-cipher-list', '--tls-keylog',
    '--trace-event-categories', '--trace-event-file-pattern', '--trace-require-module',
    '--unhandled-rejections', '--use-largepages', '--v8-pool-size', '--watch-kill-signal',
    '--watch-path',
})
_INTERPRETERS = (
    (re.compile(r'(?:python|pypy)[0-9.]*\Z'),
     _Interpreter('cm', 'QWX', '', (), ('--check-hash-based-pycs',), (), True, True)),
    (re.compile(r'perl[0-9.]*\Z'),
     _Interpreter('Ee', 'IMm', '0CDFVdilx', (), (), (), True, False)),
    (re.compile(r'ruby[0-9.]*\Z'),
     _Interpreter('e', 'CEIr', '0FKTWx', (), (), (), True, False)),
    (re.compile(r'node(?:js)?[0-9.]*\Z'),
     _Interpreter('ep', 'Cr', '', ('--eval', '--print', '--run'), _NODE_VALUE_OPTIONS, (), True, False)),
    (re.compile(r'php[0-9.]*\Z'),
     _Interpreter('FRfr', 'BEcdtSz', '', (), (), (), True, False)),
    (re.compile(r'lua(?:jit)?[0-9.]*\Z'),
     _Interpreter('', 'el', '', (), (), (), True, False)),
    (re.compile(r'[gmn]?awk\Z'),
     _Interpreter('Eef', 'FWilv', 'DLdop', ('--exec', '--file', '--source'),
                  ('--assign', '--field-separator', '--include', '--load'),
                  ('-F', '-v', '--assign', '--field-separator'), False, False)),
    (re.compile(r'Rscript\Z'), _Interpreter('e', '', '', (), (), (), False, False)),
)
# Paths that name standard input as a program or script.
_STDIN_PATHS = frozenset({'-', '/dev/stdin', '/dev/fd/0', '/proc/self/fd/0'})
_MAX_CODE_DEPTH = 64


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


def _shell_words(text, info=None):
    """Split shell text into simple commands of words, with the shell's quoting.

    Returns (commands, bodies).  A command is a list of (value, runtime) words:
    value is the word as the command receives it, quotes and escapes removed and
    each expansion replaced by _RUNTIME; runtime is True when it holds one (text
    already holding _RUNTIME keeps it run-time, whatever quotes it).
    bodies are texts that run as commands of their own: the bodies of $( ),
    backtick and <( ) >( ) substitutions, and what here-documents run
    (_here_doc_texts).  Raises ValueError on quoting the scan cannot follow.

    info, a dict, receives what may feed run-time text to each command's
    standard input: info['feeds'] holds a set per command, of 'pipe' (a pipe,
    or a group a pipe feeds), 'here-document' (one whose body holds a run-time
    value), 'here-string' and 'file' (a run-time word); info['body_fed'] holds
    a flag per body, True when the body's commands may read such input (a
    >( ) body, a substitution in a command a pipe feeds, what a shell runs
    from a run-time here-document).
    """
    cmds, words, bodies, heredocs, docs = [], [], [], [], []
    # The command each body belongs to (None: a >( ) body) and whether it is
    # fed besides; whether a pipe feeds each command, and each open group.
    owners, piped, groups = [], [], []
    st = {'buf': [], 'runtime': False, 'inword': False, 'quoted': False,
          'pending': None, 'sep': None, 'opener': None}

    def add(part, runtime=False, quoted=False):
        st['buf'].append(part)
        st['inword'] = True
        st['runtime'] = st['runtime'] or runtime or _RUNTIME in part
        st['quoted'] = st['quoted'] or quoted
        st['sep'] = None

    def end_word():
        if st['inword']:
            value = ''.join(st['buf'])
            if st['pending']:
                # The command this word belongs to is cmds[len(cmds)] once it ends.
                heredocs.append((value, st['pending'] == '<<-', st['quoted'], len(cmds)))
                st['pending'] = None
            elif value.lstrip('0123456789') in ('<<', '<<-'):
                st['pending'] = value.lstrip('0123456789')
            words.append((value, st['runtime']))
        st.update(buf=[], runtime=False, inword=False, quoted=False)

    def end_cmd():
        end_word()
        if not words:
            return False
        fed = st['opener'] in ('|', '|&') or any(groups)
        cmds.append(list(words))
        piped.append(fed)
        if words[0][0] == '{':
            groups.append(fed)
        elif words[0][0] == '}' and groups:
            groups.pop()
        del words[:]
        return True

    def expand(i, quoted=False):
        exp = _expansion(text, i, quoted)
        if exp is None:
            add('$')
            return i + 1
        end, body = exp
        if body is not None:
            bodies.append(body)
            owners.append((len(cmds), False))
        add(_RUNTIME, runtime=True)
        return end

    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '\\':
            if text[i + 1:i + 2] != '\n':  # a backslash-newline joins the lines
                add(text[i + 1:i + 2], quoted=True)
            i += 2
        elif ch == "'":
            j = text.find("'", i + 1)
            if j < 0:
                raise ValueError('unterminated single quote')
            add(text[i + 1:j], quoted=True)
            i = j + 1
        elif ch == '"':
            add('', quoted=True)
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
            # A line ending in `|`, `&&` or `||` goes on past the bodies below.
            dangling = st['sep'] in ('|', '|&', '&&', '||')
            if not dangling:
                st['opener'] = None
            for delim, tabs, quoted, owner in heredocs:  # the body follows the line that opened it
                body = []
                while i < n:
                    j = text.find('\n', i)
                    j = n if j < 0 else j
                    line, i = text[i:j], j + 1
                    if (line.lstrip('\t') if tabs else line) == delim:
                        break
                    body.append(line)
                docs.append(('\n'.join(body), quoted, owner, len(cmds) + (1 if dangling else 0)))
            del heredocs[:]
        elif ch in '<>' and text[i + 1:i + 2] == '(':
            end = _skip_group(text, i + 2, ')')
            bodies.append(text[i + 2:end - 1])
            owners.append((None if ch == '>' else len(cmds), False))
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
            ended = end_cmd()
            op = text[i:i + 2] if text[i:i + 2] in ('&&', '||', '|&') else ch
            if op == '(':  # a group opened where a pipe's reader starts is fed by it
                groups.append(st['opener'] in ('|', '|&') and not ended)
            elif op == ')' and groups:
                groups.pop()
            st['sep'] = st['opener'] = op
            i += len(op)
        else:
            add(ch)
            i += 1
    end_cmd()
    # A here-document's readers: the commands of the line that opened it, from
    # its own on (a pipe or a group there may hand it on), and the command after
    # the body when that line goes on past it.
    doc_fed = [False] * len(cmds)
    # Every body appended so far is a substitution ($( ), backtick, <( ) >( ))
    # the shell runs to build a word; the here-document bodies come after it.
    n_subst = len(bodies)
    for body, quoted, owner, stop in docs:
        texts = _here_doc_texts(body, quoted, any(map(_reads_as_shell, cmds[owner:stop])))
        bodies.extend(texts)
        runtime = info is not None and _here_doc_is_runtime(body, quoted)
        for k in range(owner, min(stop, len(cmds))):
            doc_fed[k] = doc_fed[k] or runtime
        owners.extend([(owner, runtime)] * len(texts))
    if info is not None:
        feeds = []
        for k, cmd in enumerate(cmds):
            kinds = {'pipe'} if piped[k] else set()
            if doc_fed[k]:
                kinds.add('here-document')
            for (op, _runtime), (_target, runtime) in zip(cmd, cmd[1:]):
                bare = op.lstrip('0123456789')
                if runtime and bare == '<<<':
                    kinds.add('here-string')
                elif runtime and bare in ('<', '<>') and op[:len(op) - len(bare)] in ('', '0'):
                    kinds.add('file')
            feeds.append(kinds)
        info['feeds'] = feeds
        info['body_fed'] = [owner is None or extra or (owner < len(piped) and piped[owner])
                            for owner, extra in owners]
        # The command each body is a substitution/here-document of (None: a >( )
        # body, which belongs to no one command), and how many leading bodies are
        # substitutions.  A run-time `-c` operand whose value the OUTER shell built
        # by running a substitution (`-c "y=$(sh <<< $X)"`) inherits that body's
        # run-time code, which the collapsed operand hides; a here-document is
        # input, not part of the operand word, so it is excluded.
        info['body_owner'] = [owner for owner, _extra in owners]
        info['body_subst_count'] = n_subst
    return cmds, bodies


def _reads_as_shell(words):
    """True iff the simple command `words` may run its standard input as shell commands.

    A shell (by the shape of its name), a command named at run time, a
    command that hands its input to a shell (_STDIN_SHELL_COMMANDS), one that
    names a shell among its words (`ssh host bash -s`, `docker exec -i c sh`),
    and a wrapper with no command (`sudo -i`, `sudo -s`) may; `cat`, `tee`,
    `python3` and `git commit -F -` read it as data.
    """
    values = [value for value, _runtime in words]
    idx = _command_token_index(values)
    if idx is None:
        return any(_basename(value) in _WRAPPERS for value in values)
    if words[idx][1]:
        return True
    names = [_basename(value) for value in values[idx:]]
    return names[0] in _STDIN_SHELL_COMMANDS or any(_SHELL_NAME_RE.match(name) for name in names)


def _here_doc_texts(body, quoted, shell_reads):
    """The texts a here-document's body runs as commands.

    With an unquoted delimiter the outer shell expands the body first, running
    its substitutions whoever reads it; a shell reading it then parses the
    expanded text, each expansion a run-time value.  A quoted delimiter leaves
    the body as written.  A body whose expansions the scan cannot follow is
    read as shell text, whoever reads it.
    """
    if quoted:
        return [body] if shell_reads else []
    try:
        text, subs = _expand_here_doc(body)
    except ValueError:
        return [body]
    return subs + ([text] if shell_reads else [])


def _expand_here_doc(body):
    """(text, substitutions) of a here-document body the outer shell expands, each expansion _RUNTIME.

    Raises ValueError on an expansion the scan cannot follow.
    """
    out, subs, i = [], [], 0
    while i < len(body):
        ch = body[i]
        # In such a body `\` quotes only $, `, \ and a newline; quotes are text.
        if ch == '\\' and body[i + 1:i + 2] in ('$', '`', '\\', '\n'):
            out.append(body[i + 1].replace('\n', ''))
            i += 2
            continue
        exp = _expansion(body, i, quoted=True) if ch in '$`' else None
        if exp is None:
            out.append(ch)
            i += 1
            continue
        end, sub = exp
        if sub is not None:
            subs.append(sub)
        out.append(_RUNTIME)
        i = end
    return ''.join(out), subs


def _here_doc_is_runtime(body, quoted):
    """True iff a here-document's text, as its reader gets it, may hold a value computed at run time."""
    if quoted:
        return _RUNTIME in body
    try:
        return _RUNTIME in _expand_here_doc(body)[0]
    except ValueError:
        return True


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


def _shell_c_strings(text, fed=False):
    """Yield (kind, string, fed, built_by_code) for each shell `-c` string text runs.

    kind 'text': a string the scan resolved.  'runtime': one holding a value the
    outer shell computes at run time, each such value _RUNTIME in it.
    'unlexable', with text itself: quoting the scan cannot follow, in text that
    has a shell's `-c` shape.  fed: the string's shell may read run-time text
    on its standard input (_shell_words' feeds, or text that is fed itself).
    built_by_code: a 'runtime' operand whose value the outer shell built by
    running a substitution that runs run-time code (`-c "y=$(echo $X | sh)"`);
    the collapsed operand no longer shows it, so the layer is a residual.
    """
    if not _SHELL_HINT_RE.search(text):
        return
    info = {}
    try:
        cmds, bodies = _shell_words(text, info)
    except Exception:  # quoting the scan cannot follow, or nesting past the interpreter's own limit
        if _SHELL_C_SHAPE_RE.search(text):
            yield 'unlexable', text, fed, False
        return
    owner, n_subst = info['body_owner'], info['body_subst_count']
    for k, (words, feeds) in enumerate(zip(cmds, info['feeds'])):
        values = [v for v, _runtime in words]
        idx = _command_token_index(values)
        if idx is None or words[idx][1] or not _SHELL_NAME_RE.match(_basename(values[idx])):
            continue
        op = _shell_c_operand(words, idx + 1)
        if op is None:
            continue
        value, runtime = words[op]
        built_by_code = runtime and any(
            owner[j] == k and _runs_runtime_code(bodies[j], info['body_fed'][j])
            for j in range(n_subst))
        yield ('runtime' if runtime else 'text'), value, fed or bool(feeds), built_by_code
    for body, body_fed in zip(bodies, info['body_fed']):
        yield from _shell_c_strings(body, fed or body_fed)


def _may_run_git(text, runtime_re=_RUNTIME_PLACEHOLDER_RE):
    """True iff text, read as plain command lines, runs git or may: git-shaped.

    The narrow test of the plain-text residual: a git invocation, or a command
    token _segment_residual_shapes() reports (`$G push`).  A command word that
    holds a run-time value (runtime_re) is git-shaped too unless a static word
    that is neither a git verb nor git follows it: with nothing static after
    it, the subcommand is part of the value (`$CMD`, `$X $Y`, `$SUDO git push`).
    Segments opened inside a quote are text, as there.
    """
    if any(True for _ in _segment_invocations(text)) or any(True for _ in _segment_residual_shapes(text)):
        return True
    for seg, _kind, in_quote in _segments_with_kind(text):
        toks = [] if in_quote else seg.split()
        idx = _command_token_index(toks) if toks else None
        if idx is None or not runtime_re.search(toks[idx]):
            continue
        nxt = toks[idx + 1] if idx + 1 < len(toks) else ''
        if (not nxt or runtime_re.search(nxt) or nxt in _GIT_SUBCOMMANDS
                or _basename(_unquote_token(nxt)) == 'git'):
            return True
    return False


def _unlexable_may_run_git(text):
    """True iff, in text the scan cannot lex, what follows a shell's `-c` is git-shaped.

    That text is read as _may_run_git() reads a string, its quote characters
    dropped and every expansion a run-time value.
    """
    for m in _SHELL_C_SHAPE_RE.finditer(text):
        rest = re.sub(r'\A\S*', '', text[m.end():])  # past the rest of the option word
        if _may_run_git(re.sub('[\'"]', '', rest), _EXPANSION_RE):
            return True
    return False


def _runs_runtime_code(text, fed=False, depth=0):
    """True iff text may run text computed at run time as shell commands or code.

    text is a -c layer as its shell reads it (_RUNTIME for each value the outer
    shell computes; the expansions the layer's own shell performs are run-time
    too).  fed: its standard input may carry run-time text, which every command
    in it inherits.  A command (_command_runs_runtime_code), or one in a
    substitution or here-document it runs, that may run such text makes it
    True; so does text the scan cannot lex even with its quotes dropped.
    """
    if depth > _MAX_CODE_DEPTH:
        return True
    info = {}
    try:
        cmds, bodies = _shell_words(text, info)
    except Exception:
        try:  # read as _unlexable_may_run_git() reads such text: quotes dropped
            cmds, bodies = _shell_words(re.sub(r'[\'"\\]', '', text), info)
        except Exception:
            return True
    if any(_command_runs_runtime_code(words, fed or bool(feeds))
           for words, feeds in zip(cmds, info['feeds'])):
        return True
    return any(_runs_runtime_code(body, fed or body_fed, depth + 1)
               for body, body_fed in zip(bodies, info['body_fed']))


def _command_runs_runtime_code(words, fed):
    """True iff the simple command `words` may run run-time text as shell or code.

    fed: its standard input may carry run-time text.  It may when eval comes
    before a run-time word; when a run-time value is assigned to its environment
    under a variable that can load code (_SAFE_ENV_VARS is the inverse list);
    when its program is named at run time and is fed, given a run-time word, or
    git-shaped as _may_run_git() reads it; when it is source or `.` given a
    run-time file or fed; when it is one of _RUNTIME_ARG_COMMANDS given a
    run-time word or fed; and when it is a shell or an interpreter, or one is
    named among its words, that may run such text (_runner_runs_runtime).  echo,
    printf and grep, and the _DATA_ONLY_COMMANDS, keep their words and input as
    data.  Any OTHER command is assumed, fail closed, to run a run-time word of
    its own as a command or as code: the list of dangerous programs can never be
    complete, so a program the scan does not know is refused on a run-time word.
    """
    words = _without_redirections(words)  # _shell_words' feeds read those
    values = [value for value, _runtime in words]
    idx = _command_token_index(values)
    # eval reads every word after it as shell text again, the command word too.
    for j in range(len(values) if idx is None else idx):
        if _basename(values[j]) == 'eval' and any(runtime for _v, runtime in words[j + 1:]):
            return True
    if idx is None:  # `sudo -i`, a bare xargs: a wrapper with no command reads its input
        return fed and any(_basename(value) in _WRAPPERS for value in values)
    # A run-time value assigned to the command's environment (NAME=<run-time>)
    # may be code the command loads (BASH_ENV, NODE_OPTIONS, ...).  Fail closed:
    # refuse unless the variable is one that cannot load code (_SAFE_ENV_VARS).
    for v, runtime in words[:idx]:
        if runtime and _ENV_ASSIGN_RE.match(v) and (
                v.split('=', 1)[0].rstrip('+').split('[', 1)[0] not in _SAFE_ENV_VARS):
            return True
    args = words[idx + 1:]
    if words[idx][1]:
        nxt = args[0][0] if args else None
        return bool(fed or nxt is None or any(runtime for _v, runtime in args)
                    or nxt in _GIT_SUBCOMMANDS or _basename(nxt) == 'git')
    name = _basename(values[idx])
    if name in _TEXT_ONLY_COMMANDS:
        return False
    if name in ('source', '.'):
        if args and args[0][0] == '--':
            args = args[1:]
        return bool(fed or (args and args[0][1]))
    if name in _RUNTIME_ARG_COMMANDS:
        return fed or any(runtime for _v, runtime in args)
    runs = _runner_runs_runtime(name, args, fed)
    if runs is not None:
        return runs
    # A launcher this module does not know: a shell or an interpreter among its words.
    if any(_runner_runs_runtime(_basename(value), words[p + 1:], fed, embedded=True)
           for p, (value, runtime) in enumerate(words) if p > idx and not runtime):
        return True
    # Fail closed on a program the scan does not otherwise model: a run-time word
    # of its own may be a command or code it runs (octave --eval, chroot, strace,
    # find -exec, ...).  The _DATA_ONLY_COMMANDS keep such a word as data.
    if name in _DATA_ONLY_COMMANDS:
        return False
    return any(runtime for _v, runtime in args)


def _without_redirections(words):
    """words without its redirection operators (_shell_words' own words) and their targets."""
    out, target = [], False
    for value, runtime in words:
        if target:
            target = False
        elif not runtime and _REDIR_WORD_RE.fullmatch(value):
            target = True
        else:
            out.append((value, runtime))
    return out


def _runner_runs_runtime(name, args, fed, embedded=False):
    """True iff the shell or interpreter `name`, given args, may run run-time text; None for any other name.

    embedded: name is one of another command's words; a shell is then known by
    name (_EMBEDDED_SHELL_RE) and its -c string is not a layer of its own.
    """
    if (_EMBEDDED_SHELL_RE if embedded else _SHELL_NAME_RE).match(name):
        return fed or _shell_args_run_runtime(args, as_command=not embedded)
    if name in _OPAQUE_INTERPRETERS:
        return fed or any(runtime for _v, runtime in args)
    for name_re, spec in _INTERPRETERS:
        if name_re.match(name):
            runtime, stdin = _interpreter_runs_runtime(spec, args)
            return runtime or (fed and stdin)
    return None


def _shell_args_run_runtime(args, as_command):
    """True iff a shell given args may run run-time text: as its script, its -c string or an option.

    A run-time word where the shell reads an option may be -c, -s or a script;
    --rcfile, --init-file, -o and -O take the next word.  as_command: the
    shell is a command word, whose -c string _shell_layers() reads as a layer
    of its own; otherwise a run-time -c string runs here.
    """
    i, seen_c, seen_s = 0, False, False
    while i < len(args):
        value, runtime = args[i]
        if runtime:
            return True
        if value in ('--', '-'):
            i += 1
            break
        if value.startswith('--'):
            n = 1 if value in ('--rcfile', '--init-file') else 0
        elif len(value) > 1 and value[0] in '-+':
            seen_c = seen_c or 'c' in value[1:]
            seen_s = seen_s or 's' in value[1:]
            n = value[1:].count('o') + value[1:].count('O')
        else:
            break
        if any(runtime for _v, runtime in args[i + 1:i + 1 + n]):
            return True
        i += 1 + n
    if i >= len(args):
        return False
    if seen_c:
        return not as_command and args[i][1]
    return not seen_s and args[i][1]


def _interpreter_runs_runtime(spec, args):
    """(runtime, stdin) for an interpreter (_INTERPRETERS) given args.

    runtime: a run-time value may be code it runs: a word where it reads an
    option, the value of an option that names its program or may load code, or
    its program operand.  The words after its program are the program's own.
    stdin: it reads its program from standard input.
    """
    named = False  # an option named the program: the first operand is an argument
    i = 0
    while i < len(args):
        value, runtime = args[i]
        if runtime:
            return True, False
        if value == '--':
            if named or i + 1 >= len(args):
                return False, not named and spec.stdin
            return args[i + 1][1], args[i + 1][0] in _STDIN_PATHS
        if value == '-' or not value.startswith('-'):
            return False, not named and value in _STDIN_PATHS
        option, operand, program = value, None, False
        if value.startswith('--'):
            name, eq, attached = value.partition('=')
            program = name in spec.long_program
            if program or name in spec.long_value:
                option = name
                if eq:
                    operand = (attached, False)
                elif i + 1 < len(args):
                    i += 1
                    operand = args[i]
                else:
                    operand = ('', False)
        else:
            letters = value[1:]
            for k, ch in enumerate(letters):
                if ch in spec.attached:
                    break
                if ch in spec.program or ch in spec.value:
                    option, program = '-' + ch, ch in spec.program
                    if letters[k + 1:]:
                        operand = (letters[k + 1:], False)
                    elif i + 1 < len(args):
                        i += 1
                        operand = args[i]
                    else:
                        operand = ('', False)
                    break
        i += 1
        if operand is None:
            continue
        if operand[1] and option not in spec.data:
            return True, False
        if program:
            if operand[0] in _STDIN_PATHS:
                return False, True
            named = True
            if spec.stop:
                return False, False
    return False, not named and spec.stdin


@functools.lru_cache(maxsize=32)
def _shell_layers(command_text):
    """(texts, unresolved) for command_text.

    texts: command_text, then the text of every shell `-c` string it runs, in
    the order they appear, resolved recursively up to _MAX_SHELL_DEPTH levels;
    a value the outer shell computes at run time reads as _RUNTIME_PLACEHOLDER.
    unresolved: the strings the scan cannot clear: a string holding a run-time
    value that is git-shaped (_may_run_git() over it and every string it runs)
    or may run run-time text as shell or code (_runs_runtime_code() over the
    same), text it cannot lex whose `-c` string is git-shaped, and a string
    nested past the limit.
    """
    texts, unresolved = [], []
    codes = []  # each text as its shell reads it, and whether its input is fed

    def visit(text, depth, fed=False):
        texts.append(text.replace(_RUNTIME, _RUNTIME_PLACEHOLDER))
        codes.append((text, fed))
        for kind, value, value_fed, built_by_code in _shell_c_strings(text, fed):
            if depth >= _MAX_SHELL_DEPTH:
                unresolved.append(value.replace(_RUNTIME, _RUNTIME_PLACEHOLDER))
            elif kind == 'unlexable':
                if _unlexable_may_run_git(value):
                    unresolved.append(value)
            else:
                first = len(texts)
                visit(value, depth + 1, value_fed)
                if kind == 'runtime' and (built_by_code or any(map(_may_run_git, texts[first:]))
                                          or any(_runs_runtime_code(*code) for code in codes[first:])):
                    unresolved.append(texts[first])

    try:
        visit(command_text, 0)
    except Exception:  # never let the scan cost the plain text its own checks
        shaped = _unlexable_may_run_git(command_text)
        return (command_text,), ((command_text,) if shaped else ())
    return tuple(texts), tuple(unresolved)


def iter_shell_texts(command_text):
    """Yield command_text, then the text of every shell `-c` string it runs."""
    return iter(_shell_layers(command_text)[0])


def _residual_shapes(command_text):
    """Yield (kind, segment) for command tokens that MIGHT be git but did not parse.

    Every shell `-c` string the text runs is examined like the text itself, and
    one the scan cannot clear (_shell_layers) is the kind `unresolved_shell_string`.
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


def _invocation(seg):
    """The GitInvocation of a segment whose command token is git, else None."""
    toks = seg.split()
    idx = _command_token_index(toks) if toks else None
    if idx is None:
        return None
    token = toks[idx]
    # Unquote before basenaming: bash strips the quotes before exec, so
    # `"/usr/bin/git"` and `'git'` are git invocations (fail-closed fix).
    if os.path.basename(_unquote_token(token)) != 'git':
        return None
    subcommand, remaining_args = _git_subcommand(toks[idx + 1:])
    return GitInvocation(cmd_token=token, path_qualified=('/' in token),
                         subcommand=subcommand, args=remaining_args)


def iter_git_invocations(command_text):
    """Yield GitInvocation for every git invocation in command_text.

    Each shell segment's command token is found past wrappers, env-var
    assignments, reserved words and redirections; it is git when its basename,
    balanced surrounding quotes stripped, is `git` (/usr/bin/git, "git").
    path_qualified is True when the token contains a '/'. _git_subcommand()
    skips git's global options: `/usr/bin/git -C repo push --force` -> 'push',
    ['--force'].

    The input is normalised here, so callers pass the command as written. The
    splitter is quote-blind, so a segment it opens inside a quote may be text
    (`echo "tip; git commit -m x"`) or code (`bash -c "cd x; git push"`,
    `python3 -c "os.system('cd x; git push')"`, `su -c "..."`). Such a segment
    counts unless the command owning the quote is known to leave its arguments
    unexecuted (_is_text_only: `echo`, `printf`, `grep`, `git commit`), the
    command is one line without command substitution, and no `|` in it feeds a
    command not known to leave its input unexecuted (`echo "..." | sh` runs the
    text). Any other owner, a launcher this module does not know included,
    fails closed. Elsewhere (an unclosed quote, a quote across lines, a
    substitution, where a comment, a heredoc or nested quoting can mislead a
    static reading) every segment counts. Each invocation keeps its tokens as
    written.

    The text of every shell `-c` string command_text runs is walked the same
    way, after command_text's own segments (see _shell_layers()). An
    invocation in such a string is then read twice: in the string's own text,
    as the shell runs it, and by the quote-blind scan of the text holding the
    string, its words cut at the quote (`bash -c "cd x; git push"` reads
    `push"`). That in-quote reading is not yielded again when a later text
    yields the same invocation, quotes and backslashes aside, one for one; an
    in-quote invocation no later text yields (the inner shell reads it as
    text, the string went unresolved, a launcher that is not a shell) is
    yielded as the scan read it.
    """
    layers = [list(_segment_invocations(text, tagged=True)) for text in iter_shell_texts(command_text)]
    for k, layer in enumerate(layers):
        later = collections.Counter(_bare_invocation(inv) for rest in layers[k + 1:] for inv, _q in rest)
        for inv, quoted in layer:
            key = _bare_invocation(inv)
            if quoted and later[key]:
                later[key] -= 1
                continue
            yield inv


def _bare_invocation(inv):
    """inv's words with quotes and backslashes removed: what two readings of one invocation share."""
    words = [re.sub(r'[\'"\\]', '', w) for w in [inv.cmd_token, inv.subcommand or ''] + list(inv.args)]
    return tuple(w for w in words if w)


def _segment_invocations(command_text, tagged=False):
    """iter_git_invocations() for command_text's own segments only.

    tagged: yield (invocation, quoted) instead, quoted when the segment holding
    the invocation was opened inside a quote."""
    # The appended ';' opens a last, empty segment that is in a quote exactly
    # when command_text ends inside one.
    text = command_text + ';'
    segments = _segments_with_kind(text)
    starts = [i for i, (_seg, _kind, in_quote) in enumerate(segments) if not in_quote]
    droppable = (not re.search(r'\n|\$\(|<\(|>\(|`', command_text)
                 and not _pipes_into_unknown(segments, text))
    for start, end in zip(starts, starts[1:] + [len(segments)]):
        for inv, quoted in _owned_invocations([seg for seg, _kind, _q in segments[start:end]],
                                              droppable and end < len(segments)):
            yield (inv, quoted) if tagged else inv


def _owned_invocations(group, droppable):
    """(invocation, quoted) of a segment opened outside quotes and the in-quote ones after it.

    The in-quote ones are text, and dropped, only when `droppable` and the
    segment's command is known to leave its arguments unexecuted.
    """
    written = [_invocation(seg) for seg in group]
    if written[0]:
        yield written[0], False
    if droppable and _is_text_only(group[0]):
        return
    yield from ((inv, True) for inv in written[1:] if inv)


# Commands known to leave their arguments and their standard input unexecuted.
# Measured over the P9 R6 corpus (the hooks' tests, adversarial-runs.md, the A6
# strings): `echo` and `printf` are the only non-git commands there owning a
# quoted git invocation that is text; `grep` reads its quoted pattern as text.
# Every other command is unknown, so a launcher (`python3 -c`, `su -c`,
# `find -exec`, `ssh`, `watch`, `xargs sh -c`) fails closed.
_TEXT_ONLY_COMMANDS = frozenset({'echo', 'printf', 'grep'})
# git subcommands whose quoted arguments are text (`git commit -m "a; git push"`).
_TEXT_ONLY_GIT_SUBCOMMANDS = frozenset({'commit'})


def _is_text_only(seg):
    """True iff seg's command is known to leave its arguments and input unexecuted."""
    toks = seg.split()
    idx = _command_token_index(toks) if toks else None
    if idx is None:
        return False
    # `eval echo "x; git push"` reads echo's quoted text again as shell code.
    if any(_basename(_unquote_token(t)) == 'eval' for t in toks[:idx]):
        return False
    word = _basename(_unquote_token(toks[idx]))
    if word != 'git':
        return word in _TEXT_ONLY_COMMANDS
    sub, rest = _git_subcommand(toks[idx + 1:])
    options = toks[idx + 1:len(toks) - len(rest) - 1]
    # A config value can name a program git runs (core.editor, an alias).
    return (sub in _TEXT_ONLY_GIT_SUBCOMMANDS
            and not any(o.startswith(('-c', '--config-env')) for o in options))


def _pipes_into_unknown(segments, text):
    """True iff a `|` outside quotes feeds a command that is not _is_text_only.

    `text` is the one-line, substitution-free string `segments` was split from,
    so the segments and the separators between them rebuild it exactly; a
    separator that does not read back fails closed.
    """
    pos, sep = 0, ''
    for seg, _kind, in_quote in segments:
        if sep == '|' and not in_quote and not _is_text_only(seg):
            return True
        pos += len(seg)
        sep = text[pos:pos + 2] if text[pos:pos + 2] in ('&&', '||') else text[pos:pos + 1]
        if pos < len(text) and sep not in ('&&', '||', ';', '|', '&', '(', ')'):
            return True
        pos += len(sep)
    return False


def classify_git_command(command_text):
    """Return (invocations, residuals) — the fail-closed-capable entry point.

    `invocations` is exactly `list(iter_git_invocations(command_text))`.
    `residuals` is a list of (kind, segment) from _residual_shapes(): command
    tokens that could not be resolved statically but look like they could be
    git. That scan reads the command as written, skipping segments opened in a
    quote: the normaliser's view empties the quoted command words
    (`env -i "$GIT" push`) it exists to report.

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
