#!/usr/bin/env python3
"""PreToolUse hook: forbid branch / PR / worktree CREATION outside /dev-overnight.

Policy (user directive 2026-06-04; the verbatim user directive is preserved in
docs/dev/do-report-44e208af-b8b8-4266-a2ba-fcfc77f92d24.json, the sanctioned
artifact location for non-English user-binding quotes):
  Branch creation, pull-request creation, and worktree creation are forbidden by
  default. A live /dev-overnight session is the always-on exception. In addition,
  two human-authorized escape hatches are preserved (the user's explicit choice,
  mirroring pretool-block-enterworktree.sh and pretool-git-privilege-guard.py):
  /do consent and /allow grants.

Scope: the Bash surface only. The EnterWorktree tool is governed by the companion
hook pretool-block-enterworktree.sh (same bypass semantics, including the
overnight exception); keeping the two surfaces in separate hooks avoids
double-blocking EnterWorktree.

Only the COMMAND token of each shell segment is classified — the first token
after skipping leading env-var assignments (NAME=VALUE) and known wrappers
(sudo, doas, env, xargs, time, nohup, setsid, stdbuf, ionice, command, builtin,
nice). Text that merely MENTIONS the command as an argument (`echo git checkout
-b x`, `echo gh pr new`) is in argument position, never command position, so it
is NOT a creation. Path-qualified forms like /usr/bin/git, leading env-var
prefixes, and attached/clustered short options are all caught.

Blocked Bash operations:
  - git checkout -b/-B/--orphan/--guess <name>    (branch creation, incl. -bNAME)
  - git switch  -c/-C/--create/--force-create/--orphan/--guess  (incl. -cNAME)
  - git branch <name>  /  -c/-C/--copy            (branch creation)
      list / delete / rename / upstream / info forms remain allowed.
  - git worktree add ...                          (worktree creation)
  - gh pr create / gh pr new ...                  (PR creation, flags interspersed)
  - gh pr checkout <N>  (unless --detach)         (creates a local PR branch)
  - gh api repos/<o>/<r>/pulls  (POST)            (PR creation via the REST API)
  - git stash branch <name>                       (branch from a stash)
  - git fetch/pull <repo> <src>:refs/heads/<name> (refspec into a local branch)
  - git update-ref refs/heads/<name> <sha>        (plumbing branch creation)
Long-opt create flags are matched including git's unambiguous unique-prefix
abbreviations (e.g. `git switch --cr`, `git checkout --or`). Command- and
process-substitution boundaries (`$(...)`, `<(...)`, `>(...)`, `` `...` ``) are
split so an inner creation command is classified on its own.

Inherent limitations (a command-text guardrail CANNOT block these; they are
intentionally out-of-scope — this is an AGENT SPEED-BUMP, not an adversarial
sandbox, mitigated by the /do consent and /allow grant escape hatches):
  - a creation command hidden in a quoted string passed to an interpreter, e.g.
    `eval "git checkout -b x"`, `sh -c "..."`, `bash -c "..."`: the quoted string
    is context-stripped before tokenizing, so the inner command is never seen.
  - user-defined git aliases (`git co` → checkout, etc.): the alias name is
    opaque to a static token classifier.
  - a creation command read from a file or from stdin rather than the argv.
  - remote-branch creation via `git push <remote> <src>:refs/heads/x` is
    intentionally NOT handled here because pretool-git-privilege-guard.py already
    default-denies all agent `git push`.
  - a quoted-subcommand / backslash-escape evasion (`git 'checkout' -b x`,
    `\\git checkout -b x`): the quoted/escaped token is removed by _norm's
    context-strip before tokenizing, so the inner command is never seen — same
    class as the eval/sh -c interpreter-string limit above.
  - a wrapper that consumes its OWN value args before the command (e.g.
    `nice -n 5 git checkout -b x`): _command_token_index skips wrappers but not
    their value args, so the command token resolves to `5` and the segment is
    not classified. Exotic and accepted — escape hatches cover the rare case.
  - `git symbolic-ref HEAD refs/heads/x`: repoints HEAD but creates no branch
    ref object (the branch materializes only on the first commit) — out of scope.
  - `git init -b <name>`: creates a new repository, not a branch in the working
    repo — out of scope.

Bypass order (any one → allow):
  1. live /dev-overnight session   (lib.overnight.is_overnight_active)
  2. /do consent flag              (main agent only — subagents never qualify)
  3. /allow grant                  (sentinel grant: main + subagent;
                                    legacy pattern grant: main agent only)

Coexistence
  Purely additive. PreToolUse blocks if ANY hook exits 2, so this hook only ever
  tightens — it never loosens an existing block.

Exit codes
  0 = allow, 2 = block (stderr shown to the agent). Fails OPEN (exit 0) on any
  unexpected error so a parser bug never bricks a session — same fail-open
  convention as pretool-git-privilege-guard.py.
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from lib.bash_context_strip import strip_non_executable_contexts
except Exception:  # pragma: no cover - lib always present in repo
    strip_non_executable_contexts = None
from lib.allowlist import (  # noqa: E402
    match_grant_for_bash_command,
    match_sentinel_grant_for_bash_command,
)
from lib.overnight import is_overnight_active  # noqa: E402


# ---------------------------------------------------------------------------
# Command classification. Operates on whitespace tokens of each shell segment of
# the context-stripped command.
# ---------------------------------------------------------------------------
def _norm(command):
    if strip_non_executable_contexts:
        try:
            return strip_non_executable_contexts(command)
        except Exception:
            return command
    return command


def _segments(c):
    """Split on shell separators ; \n | & && || ` ( ) into command segments.

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


# Long-option name spaces for checkout/switch, split into CREATE vs NON-create.
# These drive git's real unambiguous-unique-prefix abbreviation rule (see
# _long_opt_creates): git accepts any `--X` that is a unique prefix of exactly
# one long option, so `--cr` resolves to `--create`, `--or` to `--orphan`, etc.
# Listing the NON-create options is required for disambiguation — without them a
# prefix that is actually ambiguous (e.g. `--c` for switch: --create/--conflict)
# would be wrongly treated as a create.
_CO_CREATE_LONG = {'--orphan', '--track', '--guess'}
_CO_NONCREATE_LONG = {
    '--ours', '--theirs', '--force', '--detach', '--merge', '--conflict',
    '--patch', '--quiet', '--progress', '--no-track', '--no-guess',
    '--ignore-other-worktrees', '--recurse-submodules', '--pathspec-from-file',
    '--pathspec-file-nul', '--overwrite-ignore', '--overlay', '--no-overlay',
}
_SW_CREATE_LONG = {'--create', '--force-create', '--orphan', '--track', '--guess'}
_SW_NONCREATE_LONG = {
    '--detach', '--discard-changes', '--force', '--merge', '--conflict',
    '--quiet', '--progress', '--no-guess', '--no-track', '--recurse-submodules',
    '--ignore-other-worktrees', '--no-recurse-submodules',
}


def _long_opt_creates(sub, base):
    """True iff long-opt token `base` (already stripped of any =value) is a
    CREATE flag for `sub`, including git's unambiguous unique-prefix
    abbreviations.

    `base` is a `--X` token. Per git: an abbreviation creates iff it is a unique
    prefix of EXACTLY ONE long option across the union of that subcommand's
    create + non-create options, and that one option is a CREATE option. Exact
    full-flag matches are a special case of this (cand == [base]).
    """
    if not base.startswith('--') or base == '--':
        return False
    if sub == 'checkout':
        create, noncreate = _CO_CREATE_LONG, _CO_NONCREATE_LONG
    else:
        create, noncreate = _SW_CREATE_LONG, _SW_NONCREATE_LONG
    allopts = create | noncreate
    cand = [opt for opt in allopts if opt == base or opt.startswith(base)]
    return len(cand) == 1 and cand[0] in create


def _is_co_sw_create(sub, sa):
    """True iff a `git checkout`/`git switch` invocation CREATES a branch.

    Creation triggers, for BOTH checkout and switch:
      --orphan                              (orphan branch)
      -t / --track                          (local tracking branch; creates one)
    Checkout-only short letters: -b / -B    (create / create-or-reset)
    Switch-only long opts: --create / --force-create / --orphan and --guess
      (--guess is switch's explicit "create from a remote-tracking name" flag).

    Long-opt ABBREVIATIONS: git accepts any unambiguous unique-prefix of a long
    option (`--cr` -> --create, `--or` -> --orphan, `--tr` -> --track,
    `--g` -> --guess, `--force-c` -> --force-create). _long_opt_creates resolves
    each `--X` token against the subcommand's real long-option name space and
    returns True only when the prefix is unique AND lands on a CREATE option, so
    `--force`/`--detach`/`--conflict`/`--no-track` (non-create) are NOT blocked.

    Handles bare and attached short options (-b, -bNAME, -fb, -tb), long options
    with or without an attached =value (base = token.split('=')[0], tolerant of a
    nonexistent --track=value form), short-option clusters containing a create
    letter or `t`, and stops at the `--` pathspec separator.

    KNOWN LIMITATION (intentionally NOT fixed — fixing would over-block): a BARE
    `git switch <name>` / `git checkout <name>` with no create flag uses git's
    default --guess, which CAN create a local branch when <name> matches exactly
    one remote-tracking branch. That is indistinguishable, without repo state,
    from switching to an existing local branch, and blocking it would break the
    legitimate `git switch master` / `git checkout master`. So a bare
    switch/checkout to a name stays ALLOWED. The limitation is ONLY about the
    BARE form: an EXPLICIT `git checkout --guess <name>` (or its unique-prefix
    abbreviation `--g`) IS in the checkout CREATE set and IS blocked — what we
    cannot distinguish is the implicit default-guess of a bare name.
    """
    create_letters = set('bB') if sub == 'checkout' else set('cC')
    create_letters.add('t')  # -t == --track creates a local tracking branch
    for x in sa:
        if x == '--':
            break  # pathspec separator — options named like -b after it are files
        if x.startswith('--'):
            base = x.split('=', 1)[0]  # strip attached =value for long options
            if _long_opt_creates(sub, base):
                return True
            continue
        if x.startswith('-') and len(x) > 1:
            # short-option cluster / attached value: -b, -bNAME, -fb, -tNAME ...
            if any(ch in create_letters for ch in x[1:]):
                return True
    return False


# `git branch` is overloaded — display/formatting flags are ORTHOGONAL to
# creation (they can accompany either a list OR a create), so they MUST NOT veto
# creation. The classifier below is a left-to-right token parser, not a set
# membership test, because value-consuming flags (--sort X, --format X,
# --points-at X, -u X, ...) take a separate following token that must NOT be
# mistaken for a positional branch name.

# Long-opt VETO flags → exclusive op or list/query mode → NOT creation.
_BRANCH_VETO_LONG = {
    '--delete', '--move', '--edit-description', '--list', '--all', '--remotes',
    '--show-current', '--merged', '--no-merged', '--contains', '--no-contains',
    '--points-at', '--set-upstream-to', '--unset-upstream', '--help',
}
# Short VETO letters (in a cluster, any of these → veto).
_BRANCH_VETO_SHORT = set('dDmMlaruh')
# Long-opt COPY flags → creation.
_BRANCH_COPY_LONG = {'--copy'}
# Short COPY letters → creation.
_BRANCH_COPY_SHORT = set('cC')
# Long flags that consume the NEXT token as their REQUIRED value (when not
# attached '='). git accepts both `--flag=value` AND `--flag value` for these, so
# the separate following token is the flag's value, NOT a positional branch name
# (e.g. `git branch --sort refname` is a LIST with no positional → allow).
#
# DELIBERATELY EXCLUDED: --color, --column, --abbrev. In git's parse-options these
# are OPTIONAL-attached-value flags (`--color[=<when>]`, `--column[=<options>]`,
# `--abbrev[=<n>]`): they accept ONLY the attached `--flag=value` form. A
# SPACE-separated following token is NOT their value — it is the next positional
# (the branch name). Empirically confirmed with live git (2026-06-05): each of
# `git branch --color zzc`, `git branch --column zzc`, `git branch --abbrev 7`
# CREATES the branch named by the following token. So these must NOT swallow the
# token here, or a real creation slips through as a list (the under-block bug).
# Their bare (`--color`) and attached (`--color=always`) forms remain list-mode:
# bare leaves no positional, attached is a single token — neither creates.
_BRANCH_VALUE_LONG = {
    '--contains', '--no-contains', '--merged', '--no-merged', '--points-at',
    '--sort', '--format', '--set-upstream-to',
}


def _branch_creates(sa):
    """Left-to-right parse of `git branch` args. Returns True iff it creates.

    VETO flag seen      -> False (exclusive op / list / query mode).
    else COPY flag seen -> True  (-c/-C/--copy copies => creation).
    else >=1 positional -> True  (a bare branch name => creation).
    else                -> False (list / display-only, no name).

    Value-consuming flags swallow their following token so a space-separated
    value (e.g. `--sort refname`, `--format %(refname)`) is never read as a
    positional branch name. Display/boolean flags (-v, --verbose, -q, --quiet,
    --no-color, --no-column, --no-abbrev, and any unrecognized -x) are ignored —
    they neither veto nor positional. Veto short-circuits immediately, so a veto
    flag's space-separated value is never mis-read as a positional.
    """
    saw_copy = False
    positionals = 0
    j = 0
    n = len(sa)
    while j < n:
        x = sa[j]
        if x == '--':
            # everything after is positional
            for t in sa[j + 1:]:
                if t:
                    positionals += 1
            break
        if x.startswith('--'):
            base = x.split('=', 1)[0]
            attached = '=' in x
            if base in _BRANCH_VETO_LONG:
                return False  # short-circuit; do not consume a value as positional
            if base in _BRANCH_COPY_LONG:
                saw_copy = True
            elif base in _BRANCH_VALUE_LONG and not attached:
                j += 1  # swallow the separate value token
            # else: display/boolean long flag (--verbose, --no-color, ...) ignored
        elif x.startswith('-') and len(x) > 1:
            cluster = set(x[1:])
            # -u (==--set-upstream-to) carries 'u' in the veto set, so it (and
            # any other veto cluster) short-circuits here; its space-separated
            # value is never reached/mis-read as a positional. Good.
            if cluster & _BRANCH_VETO_SHORT:
                return False
            if cluster & _BRANCH_COPY_SHORT:
                saw_copy = True
            # else: display/boolean short cluster (-v, -q, -vv, ...) ignored
        else:
            positionals += 1
        j += 1
    if saw_copy:
        return True
    return positionals > 0


def _stash_creates(sa):
    """True iff `git stash branch <name>` (creates a branch from a stash).

    Only the `branch` stash subcommand (appearing BEFORE any `--` pathspec
    separator) creates a branch. Bare `git stash` and the
    list/show/pop/push/drop/apply/clear/save/store/create subcommands do not.
    `git stash -- branch` is a pathspec literally named "branch", not the branch
    subcommand → NOT a creation.
    """
    for x in sa:
        if x == '--':
            break  # pathspec separator — a following `branch` token is a path
        if x.startswith('-'):
            continue
        return x == 'branch'
    return False


_SCP_LIKE_REMOTE_RE = re.compile(r'^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:')


def _refspec_creates(sa):
    """True iff a fetch/pull arg is a refspec writing into a LOCAL branch.

    `git fetch <repo> <src>:<dst>` (and the pull equivalent) create a local
    branch when <dst> resolves under refs/heads/. This covers BOTH the explicit
    `:refs/heads/<name>` form AND the standard BARE-destination shorthand
    (`main:newbranch`, `HEAD:heads/nb`, `main:foo/bar`) — git puts a bare fetch
    destination under refs/heads/. Plain fetch/pull (including `--all`, `origin`,
    `origin main`) carry no creating refspec and stay allowed.

    URL/remote tokens are NOT refspecs and must not be parsed as such: any token
    containing `://` (https://, ssh://, git://, file://) or an scp-like remote
    (`git@github.com:o/r.git`) is skipped. A destination under refs/remotes/,
    refs/tags/, or refs/notes/ is not a local branch → NOT creation; an empty
    destination (`main:`, a fetch to FETCH_HEAD) is NOT creation.

    `--dry-run` writes nothing, so a creating refspec under `--dry-run` creates
    no branch → NOT a creation (a later `--no-dry-run` re-arms it).
    """
    dry = False
    for x in sa:
        if x == '--dry-run':
            dry = True
        elif x == '--no-dry-run':
            dry = False
    if dry:
        return False
    for x in sa:
        if x.startswith('-'):
            continue  # flag token, not a refspec
        if '://' in x or _SCP_LIKE_REMOTE_RE.match(x):
            continue  # URL / scp-like remote, not a refspec
        if ':' not in x:
            continue
        token = x[1:] if x.startswith('+') else x  # strip a single leading force '+'
        _src, _, dst = token.partition(':')  # split on the FIRST ':'
        if not dst:
            continue  # fetch to FETCH_HEAD, no local branch
        if dst.startswith(('refs/remotes/', 'refs/tags/', 'refs/notes/')):
            continue  # not a local branch
        if dst.startswith('refs/heads/'):
            return True
        # bare destination with no refs/ prefix → git places it under refs/heads/
        return True
    return False


# update-ref flags that consume a separate following VALUE token; that value
# must not be mistaken for a positional ref. `-m <message>` is the common one
# (so `update-ref -m refs/heads/msg <ref> <sha>` is a reflog message, not a
# branch ref).
_UPDATE_REF_VALUE_FLAGS = {'-m', '--message'}


def _update_ref_creates(sa):
    """True iff `git update-ref refs/heads/<name> <sha>` creates a local branch.

    Creation requires a positional argument starting with `refs/heads/` and NO
    delete flag. `git update-ref -d refs/heads/x` (delete) and updates to
    `refs/remotes/...` (not a local branch) stay allowed. The value consumed by
    `-m`/`--message` (and any other value-flag) is skipped so a reflog message
    like `-m refs/heads/msg` is never misread as the target ref.
    """
    if any(x in ('-d', '--delete') for x in sa):
        return False
    i = 0
    n = len(sa)
    while i < n:
        x = sa[i]
        if x in _UPDATE_REF_VALUE_FLAGS:
            i += 2  # skip the flag AND its consumed value
            continue
        if x.startswith('-'):
            i += 1
            continue
        if x.startswith('refs/heads/'):
            return True
        i += 1
    return False


# gh global flags that consume a separate following value token.
_GH_GLOBAL_VALUE = {'-R', '--repo'}


def _gh_skip_flags(args, i):
    while i < len(args):
        a = args[i]
        if a in _GH_GLOBAL_VALUE:
            i += 2
            continue
        if a.startswith('-'):
            i += 1
            continue
        break
    return i


def _is_gh_pr_create(args):
    # `gh pr new` is the official alias of `gh pr create`; block both.
    i = _gh_skip_flags(args, 0)
    if i >= len(args) or args[i] != 'pr':
        return False
    i = _gh_skip_flags(args, i + 1)
    return i < len(args) and args[i] in ('create', 'new')


def _is_gh_pr_checkout(args):
    """True iff `gh pr checkout <N>` (checks out a PR by CREATING a local branch).

    `gh pr checkout` materializes a local branch for the PR, so it is creation —
    UNLESS `--detach` is present (detached HEAD, no branch ref created). The PR
    list/view/status/diff subcommands are read-only and are NOT matched here.
    """
    i = _gh_skip_flags(args, 0)
    if i >= len(args) or args[i] != 'pr':
        return False
    i = _gh_skip_flags(args, i + 1)
    if i >= len(args) or args[i] != 'checkout':
        return False
    # `--detach` anywhere in the checkout args downgrades to a detached HEAD.
    return '--detach' not in args[i + 1:]


# Write-method indicators for `gh api`: any of these makes the call a POST/write
# (gh defaults to POST when fields are present, and -X/--method set it
# explicitly).
_GH_API_WRITE_FLAGS = {'-f', '-F', '--field', '--raw-field', '--input'}
_GH_API_METHOD_FLAGS = {'-X', '--method'}


def _is_gh_api_pr_create(args):
    """True iff `gh api <pulls-endpoint>` is a PR-creation POST.

    Blocks when the endpoint path component ends in `/pulls` (optionally with a
    trailing slash) — i.e. `repos/<owner>/<repo>/pulls` — AND the call is a write
    (POST). A write is indicated by any of `-f/-F/--field/--raw-field/--input`,
    or `-X POST` / `--method POST`. An explicit `-X GET` / `--method GET` (a LIST)
    overrides the field-implied POST and is ALLOWED.
    """
    i = _gh_skip_flags(args, 0)
    if i >= len(args) or args[i] != 'api':
        return False
    rest = args[i + 1:]
    targets_pulls = False
    has_write_flag = False
    explicit_method = None  # last -X/--method value seen (upper-cased)
    j = 0
    n = len(rest)
    while j < n:
        a = rest[j]
        if a in _GH_API_METHOD_FLAGS:
            if j + 1 < n:
                explicit_method = rest[j + 1].upper()
            j += 2
            continue
        if a.startswith('-X') and len(a) > 2:  # attached form -XPOST
            explicit_method = a[2:].upper()
            j += 1
            continue
        if a.startswith('--method='):
            explicit_method = a.split('=', 1)[1].upper()
            j += 1
            continue
        if a in _GH_API_WRITE_FLAGS:
            has_write_flag = True
            j += 2  # these flags consume a following key=value token
            continue
        if a.startswith('-'):
            j += 1
            continue
        # positional → candidate endpoint path
        path = a.rstrip('/')
        last = path.rsplit('/', 1)[-1]
        if last == 'pulls':
            targets_pulls = True
        j += 1
    if not targets_pulls:
        return False
    # explicit method wins over field-implied POST
    if explicit_method is not None:
        return explicit_method == 'POST'
    return has_write_flag


def _classify_gh(args):
    """Return 'PR' if a gh invocation creates a PR / PR-branch, else None."""
    if _is_gh_pr_create(args):
        return 'PR'
    if _is_gh_pr_checkout(args):
        return 'branch'
    if _is_gh_api_pr_create(args):
        return 'PR'
    return None


def _classify_segment(seg):
    """Return the creation kind ('worktree'|'PR'|'branch') in seg, or None.

    Classifies ONLY the segment's COMMAND token (the first token after skipping
    leading env-var assignments and known wrappers). Tokens that merely MENTION
    git/gh as an argument (e.g. `echo gh pr new`, `echo git checkout -b x`) are
    in argument position, never command position, so they are not creations.
    """
    toks = seg.split()
    idx = _command_token_index(toks)
    if idx is None:
        return None
    base = _basename(toks[idx])
    if base == 'git':
        sub, sa = _git_subcommand(toks[idx + 1:])
        if sub == 'worktree':
            for x in sa:
                if not x.startswith('-'):
                    return 'worktree' if x == 'add' else None
            return None
        if sub in ('checkout', 'switch'):
            return 'branch' if _is_co_sw_create(sub, sa) else None
        if sub == 'branch':
            return 'branch' if _branch_creates(sa) else None
        if sub == 'stash':
            return 'branch' if _stash_creates(sa) else None
        if sub in ('fetch', 'pull'):
            return 'branch' if _refspec_creates(sa) else None
        if sub == 'update-ref':
            return 'branch' if _update_ref_creates(sa) else None
        return None
    if base == 'gh':
        return _classify_gh(toks[idx + 1:])
    return None


def _detect(command):
    c = _norm(command)
    for seg in _segments(c):
        kind = _classify_segment(seg)
        if kind:
            return kind
    return None


# ---------------------------------------------------------------------------
# Bypass checks (overnight handled inline in main; these are the two
# human-authorized escape hatches the user chose to preserve).
# ---------------------------------------------------------------------------
def _get_session_id(data):
    try:
        return str(data.get('session_id', '') or '')
    except Exception:
        return ''


def _has_do_consent(data):
    """True iff the main agent holds /do consent for this session."""
    if data.get('agent_id'):  # subagents never qualify for /do
        return False
    sid = _get_session_id(data)
    if not sid:
        return False
    try:
        flag = Path(f'/tmp/claude-orchestrator-consent-{sid}.flag')
        return flag.exists() and flag.read_text().strip() == 'true'
    except Exception:
        return False


def _allow_grant_matches(command, data):
    """True iff a /allow grant authorizes this command.

    Sentinel grants reach subagents and the main agent (mirrors the M2 decision
    in pretool-git-privilege-guard.py); the legacy pattern grant is
    main-agent-only.
    """
    sid = _get_session_id(data)
    task_id = os.environ.get('CLAUDE_TASK_ID') or sid
    try:
        if task_id and match_sentinel_grant_for_bash_command(task_id, command) is not None:
            return True
    except Exception:
        pass
    if data.get('agent_id'):
        return False
    if not sid:
        return False
    try:
        return match_grant_for_bash_command(command, sid) is not None
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Blocking.
# ---------------------------------------------------------------------------
_POLICY = (
    'Policy (2026-06-04): branch / PR / worktree creation is forbidden outside a '
    'live /dev-overnight session.\n'
    'Escape hatches: run it inside /dev-overnight, or (main agent) use /do, or '
    '/allow the specific command first.\n'
)


def _block(kind, command, data):
    lines = [
        '',
        f'BLOCKED: {kind} creation is forbidden outside /dev-overnight.',
    ]
    if command:
        lines.append(f'Command excerpt: {command[:200]}')
    lines.append('')
    lines.append(_POLICY.rstrip('\n'))
    if data.get('agent_id'):
        lines.append(
            'You are a subagent: PAUSE and report this block to the user per '
            'Subagent Hook Discipline — do NOT attempt to work around it.')
    sys.stderr.write('\n'.join(lines) + '\n')
    sys.exit(2)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        if data.get('tool_name', '') != 'Bash':
            sys.exit(0)
        command = (data.get('tool_input', {}) or {}).get('command', '') or ''
        if not command.strip():
            sys.exit(0)
        kind = _detect(command)
        if not kind:
            sys.exit(0)
        # Bypasses — any one allows the operation.
        if is_overnight_active(data.get('cwd')):
            sys.exit(0)
        if _has_do_consent(data):
            sys.exit(0)
        if _allow_grant_matches(command, data):
            sys.exit(0)
        _block(kind, command, data)
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
    sys.exit(0)


if __name__ == '__main__':
    main()
