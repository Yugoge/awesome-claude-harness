#!/usr/bin/env python3
"""
PreToolUse Hook: Agent git-privilege guard.

Runs on every Bash call, for subagents and the main agent, in interactive and
overnight sessions alike.

Refused for an agent:
  - git commit, unless a /commit grant bound to the commit's repository,
    branch and HEAD authorizes it, or its subject is
    `auto-bulk: end-of-cycle commit for <branch>` while a /commit --bulk
    sentinel is live. Stderr literal: `BLOCKED: agent git commit`.
  - git merge (any form; /merge merges inside hooks/merge.sh, whose subprocess
    no hook sees). Stderr literal: `BLOCKED: agent git merge`.
  - git push (any form; /push pushes inside hooks/push.sh). Stderr literal:
    `BLOCKED: agent git push`. A push that forces, deletes or mirrors refs is
    refused before /allow and /do are consulted.
  - git reset --hard. Stderr literal: `BLOCKED: agent git reset --hard`.
  - direct ref mutation (`git update-ref`, branch force/delete/rename, a
    writable HEAD symbolic-ref change) and commit-object plumbing.

/allow grants one matching call. /do consent (hooks/lib/allowlist.py
has_do_consent: main agent, one turn) releases the rules on git merge,
forbidden plumbing, hard reset and direct ref mutation, and adds none. What one
of them refuses without it stays refused when it can move the protected
branch's ref, or when the guard cannot tell the branch it lands on
(_moves_protected_branch). git commit, git push and a git command the guard
cannot classify are judged as without it. Each block then names the commands
that land them (/close then /commit, /push, /merge).

Exit codes:
  0: Allow tool use
  2: Block tool use

An error the guard does not expect, an import that fails at module load
included, refuses a Bash call that may run git (exit 2, naming the error); it
is not a policy refusal, and no grant or /do consent lifts it. Another tool,
and a command that cannot run git (_may_run_git), still exit 0. Unreadable
input (not a JSON object) is judged on its raw text the same way.
"""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)

import glob
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# Fail closed. The code from here to the first hooks/lib import uses the standard
# library alone, so it still decides when a lib module fails to load or anything
# later raises; Python's own exit 1 there is a non-blocking hook error, and the
# harness would run the command unjudged.
_STDIN = None
_MAY_RUN_GIT_RE = re.compile(r'git|[$`]|[<>]\(', re.IGNORECASE)


def _read_stdin():
    """The raw hook payload, read once, by main or by the load-failure hook."""
    global _STDIN
    if _STDIN is None:
        try:
            stream = getattr(sys.stdin, 'buffer', None)
            _STDIN = stream.read().decode('utf-8', 'replace') if stream else sys.stdin.read()
        except Exception:
            _STDIN = ''
    return _STDIN


def _may_run_git(text):
    """False only when text cannot run git as this guard reads a command.

    The guard refuses only what classify_git_command finds: a command word that
    names git, one that spells it with quotes or backslashes (`g\\it`, `gi""t`),
    or one built at run time (`$GIT`, `$(which git)`, a backquote, `<(...)`). With
    quotes, backslashes and line continuations removed, text holding no `git` in
    any letter case, no `$`, no backquote and no `<(` or `>(` has none of them.
    """
    flat = text.replace('\\\n', '')
    for ch in '\\\'"':
        flat = flat.replace(ch, '')
    return bool(_MAY_RUN_GIT_RE.search(flat))


def _judged_text(raw):
    """What an error is judged on: None for another tool's call, a Bash call's
    command, and the raw payload when it does not read as a tool call."""
    try:
        data = json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(data, dict):
        return raw
    if data.get('tool_name', '') != 'Bash':
        return None
    tool_input = data.get('tool_input')
    command = tool_input.get('command') if isinstance(tool_input, dict) else None
    return command if isinstance(command, str) else raw


def _internal_error_exit(exc, what='internal error'):
    """2, naming exc on stderr, when the call may run git; else 0."""
    text = _judged_text(_read_stdin())
    if text is None or not _may_run_git(text):
        return 0
    sys.stderr.write(
        '\nBLOCKED: git-privilege guard %s, not a policy refusal: %s: %s\n'
        % (what, type(exc).__name__, str(exc)[:300])
        + 'The guard could not judge this command, which may run git, so it refuses '
        'it; no /allow grant or /do consent lifts this. Report it.\n')
    return 2


def _refuse_on_load_failure(exc_type, exc, tb):
    """sys.excepthook while this file runs as the hook: an exception escaping the
    module (a hooks/lib import that fails, any module-level error) exits through
    _internal_error_exit instead of Python's exit 1."""
    try:
        code = _internal_error_exit(exc)
    except BaseException:
        code = 2
    try:
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)


if __name__ == '__main__':
    sys.excepthook = _refuse_on_load_failure

sys.path.insert(0, str(Path(__file__).parent))
from lib.allowlist import has_do_consent, match_sentinel_grant_for_bash_command  # noqa: E402
from lib.agent_resolver import resolve_agent_type  # noqa: E402
from lib.harness_state_dir import harness_state_dir  # noqa: E402
from lib.git_command_classifier import (  # noqa: E402
    iter_git_invocations, classify_git_command)
from lib.git_command_classifier import (  # noqa: E402
    _unquote_token,
    _segments as _shell_segments,
    _command_token_index as _cmd_token_index,
    _ENV_ASSIGN_RE as _ENV_ASSIGN_RE,
    GIT_GLOBAL_VALUE_OPTS, GIT_GLOBAL_FLAGS,
)
# Commit-grant provenance (minted_by) and the hook-written changelog-analyst
# dispatch attestation, shared with scripts/write-commit-grant.py and
# hooks/pretool-commit-dispatch-attest.py. See _grant_provenance_refusal.
from lib import commit_pipeline  # noqa: E402
# The per-event pointer a spent grant hands to the PostToolUse finalizer, which
# appends the commit-event journal entry from it.
from lib import commit_journal  # noqa: E402


BLESSED_BRIDGE_RE = re.compile(r'auto-bulk:\s*end-of-cycle commit for\b')


def _option_alternation(opts):
    return '|'.join(re.escape(o) for o in sorted(opts, key=lambda o: (-len(o), o)))


# A git command line up to its subcommand, built from the classifier's option
# table. The guard does not read commands with it; scripts/check-enforcement-evidence.py
# and the tests that compare it with pretool-bash-safety.sh's GIT_CMD_RE do.
GIT_GLOBAL_OPTION_RE = r'(?:\s+(?:(?:%s)\s*\S+|(?:%s)(?:=\S+|\s+\S+)|(?:%s)(?:=\S+)?))*' % (
    _option_alternation(o for o in GIT_GLOBAL_VALUE_OPTS if not o.startswith('--')),
    _option_alternation(o for o in GIT_GLOBAL_VALUE_OPTS if o.startswith('--')),
    _option_alternation(GIT_GLOBAL_FLAGS),
)
GIT_COMMAND_RE = r'(?:^|[\s;&|()`])git' + GIT_GLOBAL_OPTION_RE + r'\s+'

# What repoints a commit at another repository or work tree than its cwd or its
# one -C directory, where the grant's repo/branch/HEAD binding is checked. No
# committer uses them, so a commit under a grant that carries one is refused.
_GIT_REDIRECT_ENV_VARS = ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR')
_GIT_REDIRECT_FLAGS = ('--git-dir', '--work-tree', '--namespace')
# Builtins that move a later commit to another cwd than the guard probes.
_CWD_CHANGE_CMDS = ('cd', 'pushd', 'popd')


def _block(message):
    sys.stderr.write(message)
    sys.exit(2)


def _get_session_id(data):
    """The payload's session_id, or ''."""
    try:
        sid = data.get('session_id', '') or ''
        return str(sid)
    except Exception:
        return ''


def _check_git_allowlist(command: str, data: dict) -> bool:
    """True when a /allow grant matches this command (read-only; subagents included)."""
    sid = _get_session_id(data)
    if not sid:
        return False
    task_id = os.environ.get('CLAUDE_TASK_ID') or sid
    return match_sentinel_grant_for_bash_command(task_id, command) is not None


def _load_grant(grant_path):
    """The grant file as a dict, or None when missing, empty, malformed or unreadable."""
    try:
        with open(grant_path, 'r') as fp:
            text = fp.read()
        if not text.strip():
            return None
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            return None
        return parsed
    except Exception:
        return None


def _collect_commit_grant_candidates():
    """Every parseable commit grant as (path, grant), newest first.

    /commit writes one repository-bound grant per repository of its plan, and the
    commit picks the one bound to its own target. The glob takes any session id:
    a subagent's payload carries its parent's session_id, and the writer may be
    given another. A spent grant no longer exists."""
    pattern = os.path.join(harness_state_dir(), 'claude-commit-grant-*-*.json')
    try:
        paths = glob.glob(pattern)
    except Exception:
        return []
    try:
        paths.sort(key=lambda p: os.stat(p).st_mtime, reverse=True)
    except Exception:
        paths.sort(reverse=True)
    candidates = []
    for path in paths:
        grant = _load_grant(path)
        if grant is not None:
            candidates.append((path, grant))
    return candidates


def _spend_grant(grant_path):
    """Spend a single-use grant by deleting it; True when this call deleted it.

    Only a validated grant is spent. unlink succeeds for one caller, so two
    events racing for one grant cannot both spend it."""
    try:
        os.unlink(grant_path)
        return True
    except OSError:
        return False


def _grant_can_authorize_here(grant, command):
    """True when `grant` could authorize this command's commit now: the binding
    test of _grant_matches_commit_target, which never refuses here, since the
    auto-bulk deferral is scheduling. An empty command, or a target that cannot
    be resolved (two -C, a `$` in -C), counts as could, so deferral only narrows.
    The message such a target writes on stderr does not change the exit."""
    if not command:
        return True
    try:
        return _grant_matches_commit_target(grant, command)
    except SystemExit:
        return True
    except Exception:
        return True


def _git_output(args):
    """`git <args>` in the hook's cwd: stripped stdout, or '' on any error."""
    try:
        result = subprocess.run(
            ['git'] + list(args),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return ''
        return (result.stdout or '').strip()
    except Exception:
        return ''


def _ambient_git_redirect_present():
    """True when the guard's own environment points git at another repository or
    work tree, so neither a bare commit nor the guard's probes are where they look."""
    return any(os.environ.get(v) for v in _GIT_REDIRECT_ENV_VARS)


def _commit_target_dir(rec):
    """The one `-C` directory of a commit invocation, or '' for the hook's cwd.

    changelog-analyst commits every repository of its plan with
    `git -C "<root>" commit -F <msgfile>` from one cwd, so the grant is checked
    against the `-C` directory. Two `-C` options chain (a later absolute one
    overrides), and a `$` word reaches the hook unexpanded: both are refused
    rather than resolved here."""
    dirs = rec['dirs']
    if len(dirs) > 1:
        _block(
            '\nBLOCKED: agent git commit - multiple -C directory overrides '
            'in one commit invocation are not supported.\n'
            'Command excerpt: %s\n' % rec['text'][:200]
            + 'Re-issue the commit with exactly one -C <dir> (or none).\n'
        )
    value = dirs[0] if dirs else ''
    if '$' in value:
        _block(
            '\nBLOCKED: agent git commit - the -C argument %r looks like an '
            'unresolved shell variable reference, not a concrete path.\n' % value
            + 'Command excerpt: %s\n' % rec['text'][:200]
            + 'Substitute the concrete resolved absolute directory before '
            'submitting the commit command.\n'
        )
    return value


def _block_commit_redirect(rec, vector):
    _block(
        '\nBLOCKED: agent git commit - %s redirect detected.\n' % vector
        + 'A commit grant is bound to a specific repo/branch/HEAD resolved at '
        'issuance time; --git-dir / --work-tree / --namespace flags and '
        'GIT_DIR / GIT_WORK_TREE / GIT_COMMON_DIR env assignments repoint the '
        'commit at a DIFFERENT target the grant never authorized. Only a bare '
        '`git commit` or `git -C <dir> commit` (validated against the grant) '
        'is permitted.\n'
        + 'Command excerpt: %s\n' % rec['text'][:200]
    )


def _enforce_commit_grant_binding(grant, command):
    """Validate the grant's repo/branch/HEAD binding against the one commit
    invocation in `command`; every check that fails _block()s (exit 2).

    Refused: an ambient or inline GIT_DIR-style redirect, a --git-dir/--work-tree/
    --namespace option, a cd/pushd/popd before the commit, a commit the reader
    cannot locate, and more than one commit (one grant authorizes one commit, and
    every commit in a call would be checked against the same pre-call HEAD)."""
    if _ambient_git_redirect_present():
        _block(
            '\nBLOCKED: agent git commit - ambient GIT_DIR/GIT_WORK_TREE/'
            'GIT_COMMON_DIR environment redirect present.\n'
            'The commit target repo cannot be verified against the grant '
            'binding while these are set. Unset them and re-run /commit.\n'
        )
    records = _commit_records(command)
    if not records:
        _block(
            '\nBLOCKED: agent git commit - a commit was detected but its '
            'effective target repository could not be resolved for grant '
            'validation.\n'
            'Command excerpt: %s\n' % command[:200]
            + 'Fail closed: an unlocatable commit target is rejected, not '
            'guessed.\n'
        )
    if len(records) > 1:
        _block(
            '\nBLOCKED: agent git commit - %d commit invocations in ONE command; '
            'a commit grant authorizes exactly ONE commit.\n' % len(records)
            + 'Command excerpt: %s\n' % command[:200]
            + 'Every invocation in one call is validated against the SAME '
            'pre-execution HEAD, so a second commit here would ride the first '
            'one\'s authorization. The authorized committer issues a minimal '
            '`git commit -F <msgfile>` with nothing chained on that command line '
            '(agents/changelog-analyst.md, command-line purity). Issue each commit '
            'as its own call under its own grant.\n'
        )
    for rec in records:
        if rec['env_redirect']:
            _block_commit_redirect(rec, 'inline-env GIT_DIR/GIT_WORK_TREE')
        if rec['flag_redirect']:
            _block_commit_redirect(rec, '--git-dir/--work-tree/--namespace flag')
        if rec['cwd_changed']:
            _block_commit_redirect(rec, 'cd/pushd cwd-change before commit')
        target_dir = _commit_target_dir(rec)
        _validate_commit_grant_repo(grant, target_dir)
        _validate_commit_grant_branch(grant, target_dir)
        _validate_commit_grant_head(grant, target_dir)


def _commit_target_git_output(target_dir, *args):
    """_git_output in `target_dir` (`git -C`), or in the hook's cwd when it is ''."""
    prefix = ['-C', target_dir] if target_dir else []
    return _git_output(prefix + list(args))


def _validate_commit_grant_repo(grant, target_dir):
    """grant.repo_root must be the toplevel of the repository the commit lands in."""
    grant_repo = grant.get('repo_root') or ''
    current_repo = _commit_target_git_output(target_dir, 'rev-parse', '--show-toplevel')
    if not grant_repo or not current_repo or grant_repo != current_repo:
        _block(
            '\nBLOCKED: agent git commit - repository mismatch.\n'
            'Grant repo_root  : %r\n' % grant_repo
            + 'Current repo_root: %r\n' % current_repo
            + 'A commit grant issued for one repository may not authorize a '
            'commit in another. Re-run /commit from within the target repository.\n'
        )


def _validate_commit_grant_branch(grant, target_dir):
    """grant.branch must be the current branch of the commit's repository."""
    grant_branch = grant.get('branch') or ''
    current_branch = _commit_target_git_output(target_dir, 'branch', '--show-current')
    if not grant_branch or grant_branch != current_branch:
        _block(
            '\nBLOCKED: agent git commit - branch mismatch.\n'
            'Grant branch  : %r\n' % grant_branch
            + 'Current branch: %r\n' % current_branch
        )


def _validate_commit_grant_head(grant, target_dir):
    """grant.expected_head must be the commit repository's HEAD.

    No drift is tolerated: staging does not move HEAD between the mint and the
    commit, and changelog-analyst's recovery commit reuses an unspent grant only
    while no commit has run since the mint."""
    grant_head = grant.get('expected_head') or ''
    current_head = _commit_target_git_output(target_dir, 'rev-parse', 'HEAD')
    if not grant_head or grant_head != current_head:
        _block(
            '\nBLOCKED: agent git commit - expected_head mismatch.\n'
            'Grant expected_head: %r\n' % grant_head
            + 'Current HEAD       : %r\n' % current_head
            + 'HEAD moved since the grant was issued; re-run /commit to '
            'obtain a fresh grant.\n'
        )


def _grant_matches_commit_target(grant, command):
    """True when `grant`'s repo_root, branch and expected_head match the target of
    every commit invocation in `command`: selection among the grants /commit
    wrote (one per repository of its plan). A grant lacking a binding field
    matches nothing; the redirect refusals are _enforce_commit_grant_binding's,
    which still runs on the grant selected, so selection never widens what is
    allowed. A malformed -C (two of them, a `$`) still _block()s."""
    grant_repo = grant.get('repo_root') or ''
    grant_branch = grant.get('branch') or ''
    grant_head = grant.get('expected_head') or ''
    if not grant_repo or not grant_branch or not grant_head:
        return False
    records = _commit_records(command)
    if not records:
        return False
    for rec in records:
        target_dir = _commit_target_dir(rec)
        if _commit_target_git_output(target_dir, 'rev-parse', '--show-toplevel') != grant_repo:
            return False
        if _commit_target_git_output(target_dir, 'branch', '--show-current') != grant_branch:
            return False
        if _commit_target_git_output(target_dir, 'rev-parse', 'HEAD') != grant_head:
            return False
    return True


def _looks_like_git_commit(invocations):
    return any(inv.subcommand == 'commit' for inv in invocations)


def _looks_like_git_merge(invocations):
    # merge-base and mergetool are separate subcommand tokens from _git_subcommand;
    # they will have inv.subcommand == 'merge-base' or 'mergetool', not 'merge'.
    return any(inv.subcommand == 'merge' for inv in invocations)


def _looks_like_git_push(invocations):
    return any(inv.subcommand == 'push' for inv in invocations)


def _looks_like_git_reset_hard(invocations):
    return any(
        inv.subcommand == 'reset' and '--hard' in inv.args
        for inv in invocations
    )


def _looks_like_git_direct_ref_mutation(invocations):
    for inv in invocations:
        if inv.subcommand == 'update-ref':
            return True
        if inv.subcommand == 'symbolic-ref':
            # Block: symbolic-ref HEAD refs/...
            args = inv.args
            # Skip -m <msg> flag pairs
            i = 0
            while i < len(args):
                if args[i] == '-m':
                    i += 2
                    continue
                break
            if i < len(args) and args[i] == 'HEAD':
                if i + 1 < len(args) and args[i + 1].startswith('refs/'):
                    return True
        if inv.subcommand == 'branch':
            for tok in inv.args:
                if tok in ('--delete', '--force', '--move'):
                    return True
                if re.match(r'^-[fDdMm]+$', tok):
                    return True
    return False


# git push options that overwrite or delete remote refs, tags included. git takes
# any unambiguous prefix of a long option (`--forc`, `--del`, `--mir`) and fails
# on an ambiguous one, so a prefix of one of these names is read as it.
_PUSH_REWRITE_LONG = ('force', 'force-with-lease', 'force-if-includes', 'delete', 'mirror', 'prune')
_PUSH_REWRITE_SHORT = frozenset('fd')


def _push_forces_or_deletes(invocation):
    """True when a `git push` forces, deletes or mirrors a ref: a rewrite option
    (abbreviated, or a letter of a short-option cluster such as `-uf`), or a
    refspec that forces (`+src:dst`) or deletes (`:dst`)."""
    for tok in invocation.args:
        word = _unquote_token(tok)
        if word.startswith('--'):
            name = word[2:].partition('=')[0]
            if name and any(opt.startswith(name) for opt in _PUSH_REWRITE_LONG):
                return True
        elif word.startswith('-'):
            if _PUSH_REWRITE_SHORT & set(word[1:]):
                return True
        elif word.startswith(('+', ':')):
            return True
    return False


# Commit options whose value is the next word when it is not attached.
_COMMIT_VALUE_OPTS = {'-C', '-c', '-t', '--author', '--date', '--cleanup', '--fixup', '--squash',
                      '--reuse-message', '--reedit-message', '--template', '--trailer',
                      '--pathspec-from-file'}


def _simple_commands(command):
    """The command's simple commands as lists of shell-unquoted words, split at
    unquoted ; & | ( ) < > and newlines, with `#` comments dropped; None when a
    quote is left open."""
    cmds, words, word, i, n = [], [], None, 0, len(command)
    while i < n:
        ch = command[i]
        if command.startswith('\\\n', i):
            i += 2
            continue
        if ch in ' \t\r;&|()<>\n' or (ch == '#' and word is None):
            if word is not None:
                words.append(''.join(word))
                word = None
            if ch == '#':
                i = command.find('\n', i)
                i = n if i < 0 else i
                continue
            if ch not in ' \t\r' and words:
                cmds.append(words)
                words = []
            i += 1
            continue
        word = [] if word is None else word
        if ch in '\'"':
            j = i + 1
            while j < n and command[j] != ch:
                if ch == '"' and command[j] == '\\' and command[j + 1:j + 2] in ('"', '\\', '$', '`'):
                    j += 1
                word.append(command[j])
                j += 1
            if j >= n:
                return None
            i = j + 1
        elif ch == '\\' and i + 1 < n:
            word.append(command[i + 1])
            i += 2
        else:
            word.append(ch)
            i += 1
    if word is not None:
        words.append(''.join(word))
    return cmds + [words] if words else cmds


def _commit_records(command):
    """One record per `git ... commit` invocation in `command`, in shell order:
    text (its words), args (after `commit`), dirs (its -C values), env_redirect
    (an inline GIT_DIR-style assignment), flag_redirect (--git-dir, --work-tree,
    --namespace) and cwd_changed (a cd, pushd or popd runs before it, so the
    guard's probes would not look where it lands). An open quote yields none."""
    records, cwd_changed = [], False
    for words in _simple_commands(command) or []:
        idx = _cmd_token_index(words)
        if idx is None:
            continue
        name = os.path.basename(words[idx])
        if name in _CWD_CHANGE_CMDS:
            cwd_changed = True
            continue
        if name != 'git':
            continue
        dirs, flag_redirect, i = [], False, idx + 1
        while i < len(words) and words[i].startswith('-'):
            opt = words[i]
            flag_redirect |= opt.partition('=')[0] in _GIT_REDIRECT_FLAGS
            if opt in GIT_GLOBAL_VALUE_OPTS:
                if opt == '-C' and i + 1 < len(words):
                    dirs.append(words[i + 1])
                i += 2
                continue
            if opt.startswith('-C'):
                dirs.append(opt[2:])
            i += 1
        if words[i:i + 1] != ['commit']:
            continue
        records.append({
            'text': ' '.join(words), 'args': words[i + 1:], 'dirs': dirs,
            'flag_redirect': flag_redirect, 'cwd_changed': cwd_changed,
            'env_redirect': any(_ENV_ASSIGN_RE.match(w) and w.partition('=')[0] in _GIT_REDIRECT_ENV_VARS
                                for w in words[:idx]),
        })
    return records


def _commit_message(rec, cwd):
    """The whole message of one commit invocation: its -m/--message values as git
    joins them, or the whole -F/--file regular file (relative to its -C
    directory). None when the hook cannot read it: no message option, stdin or a
    file it cannot read, or -m with -F (git refuses that combination)."""
    base = cwd
    for d in rec['dirs']:
        base = os.path.join(base, d)
    texts, path, args, j = [], None, rec['args'], 0
    while j < len(args) and args[j] != '--':
        a, nxt = args[j], (args[j + 1] if j + 1 < len(args) else None)
        if a in ('-m', '--message', '-F', '--file'):
            opt, value, j = a, nxt, j + 2
        elif a.startswith(('--message=', '--file=')):
            (opt, value), j = a.split('=', 1), j + 1
        elif a in _COMMIT_VALUE_OPTS or not a.startswith('-') or a.startswith('--'):
            j += 2 if a in _COMMIT_VALUE_OPTS else 1
            continue
        else:
            # A short-option cluster (`-am msg`): the first value-taking letter takes the
            # rest of the word, else the next word; -u/-S take only an attached value.
            k = next((k for k in range(1, len(a)) if a[k] in 'mFCctuS'), None)
            if k is None or a[k] in 'uS':
                j += 1
                continue
            opt, value, j = '-' + a[k], a[k + 1:] or nxt, j + (1 if a[k + 1:] else 2)
            if opt[1] in 'Cct':
                continue
        if value is None or (opt in ('-F', '--file') and value == '-'):
            return None
        if opt in ('-m', '--message'):
            texts.append(value)
        else:
            path = os.path.join(base, value)
    if bool(texts) == bool(path):
        return None
    if path is None:
        return '\n\n'.join(texts)
    try:
        if not os.path.isfile(path):
            return None
        with open(path, encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except OSError:
        return None


def _commit_message_text(command, cwd):
    """The message of the command's one commit, or None (unreadable, or not one commit)."""
    records = _commit_records(command)
    return _commit_message(records[0], cwd) if len(records) == 1 else None


def _auto_bulk_subject(command, cwd):
    """The auto-bulk subject line when every commit in `command` carries one, else ''.

    Only the messages of the commits themselves are read: an `auto-bulk:` text in
    another command of the same call does not make a commit an auto-bulk one."""
    subjects = [(_commit_message(rec, cwd) or '').partition('\n')[0]
                for rec in _commit_records(command)]
    if subjects and all(BLESSED_BRIDGE_RE.search(s) for s in subjects):
        return subjects[0]
    return ''


def _task_id_refusal(grant, grant_path, command, data):
    """Why this grant may not authorize this commit's message, or '' when it may.

    A grant naming a task authorizes only a commit whose whole message carries
    that task's `Task-id: <task_id>` line -- the line /commit's completion and
    scripts/dev-lifecycle.py read back from history. A message the hook cannot
    read is refused rather than guessed."""
    if grant.get('task_id') is None:
        return ''
    line = f"Task-id: {grant['task_id']}"
    message = _commit_message_text(command, _hook_cwd(data))
    if message is not None and any(row.strip() == line for row in message.splitlines()):
        return ''
    return (
        f'\nBLOCKED: a commit under a /commit grant must carry the line `{line}` in its message.\n'
        f'  grant: {grant_path}\n'
        '  message: ' + ('lacks that line' if message is not None else
                         'unreadable (one readable -F/--file regular file or -m/--message values)')
        + '\nWrite the whole message, that line included, to the message file and commit it with '
        '`git commit -F <msgfile>` (agents/changelog-analyst.md, Phase 8).\n'
    )


def _hook_cwd(data):
    """The directory the command runs in: the payload's cwd, else the hook's own."""
    return str(data.get('cwd') or '') or os.getcwd()


def _extract_reset_target(invocation):
    """Extract the target ref from a reset --hard GitInvocation.

    Returns the first non-flag positional arg after --hard, or ''.
    """
    args = invocation.args
    try:
        hard_idx = args.index('--hard')
        for tok in args[hard_idx + 1:]:
            if not tok.startswith('-'):
                return tok
    except ValueError:
        pass
    return ''


def _end_time_passed(end_str):
    try:
        end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError):
        return True
    if end.tzinfo is None:
        return datetime.now() > end
    return datetime.now(timezone.utc) > end


def _block_default_deny_commit(msg):
    """Every other agent commit."""
    _block(
        '\nBLOCKED: agent git commit - only the blessed /merge '
        'auto-bulk bridge or the /commit wrapper may commit from an '
        'agent context.\n'
        'Commit message excerpt: %r\n' % msg[:200]
        + 'Allowed pattern: ^auto-bulk: end-of-cycle commit for <branch>\n'
        'For closed dev tasks, use /commit <task-id>.\n'
        'For human-driven commits, a human types /commit (or '
        '/allow git commit for one call).\n'
        'Main agent may bypass with /allow <pattern> before the git commit command.\n'
    )


def _has_bulk_commit_sentinel(data):
    """True when a live bulk-commit sentinel authorizes an auto-bulk commit now.

    /commit --bulk's UserPromptSubmit hook (scripts/write-bulk-commit-sentinel.py)
    writes it before dispatching changelog-analyst; it is not spent, so every
    auto-bulk commit of that run passes. commit_pipeline.bulk_commit_sentinel_live
    (kind, origin, expiry) decides each file, as the Stop cleanup's reap does.
    The session's own sentinels are read first, then any session's, since a
    subagent's payload carries its parent's session id."""
    sid = _get_session_id(data)
    patterns = []
    if sid:
        patterns.append(commit_pipeline.bulk_sentinel_glob(sid))
    patterns.append(commit_pipeline.bulk_sentinel_glob())
    seen = set()
    for pattern in patterns:
        try:
            candidates = glob.glob(pattern)
        except Exception:
            continue
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            if commit_pipeline.bulk_commit_sentinel_live(
                    commit_pipeline.safe_read_json(path)):
                return True
    return False


def _has_active_commit_grant(command=''):
    """True when an unspent, unexpired commit grant that could authorize this
    command's commit is pending: a /commit cycle is under way, and auto-bulk
    waits for it. The grant must match the commit's repository, branch and HEAD
    (_grant_can_authorize_here); an empty command, or a target that cannot be
    resolved, defers."""
    try:
        for path, grant in _collect_commit_grant_candidates():
            if _end_time_passed(grant.get('expires_at', '')):
                continue
            if _grant_can_authorize_here(grant, command):
                return True
    except Exception:
        pass
    return False


def _grant_provenance_refusal(grant, grant_path, data):
    """Why this caller may not spend this grant, or '' when it may.

    A grant that is unexpired, unspent and bound to this repo/branch/HEAD is
    still a bearer ticket unless the guard also asks who presents it and
    whether the pipeline it authorizes ran:

      1. minted_by.origin must be PIPELINE_ORIGIN (the writer checked a real
         /commit run planned this repository).
      2. The caller must be a dispatched subagent (non-empty agent_id).
      3. A hook-written changelog-analyst dispatch attestation, dated at or
         after the mint, must record the caller's CLI role and the digest of
         the prompt that dispatched this agent_id (read from its transcript).

    A reason is returned rather than a block, so one stale grant cannot shadow
    a valid one later in the candidate list."""
    minted_by = grant.get('minted_by')
    if not isinstance(minted_by, dict) or \
            minted_by.get('origin') != commit_pipeline.PIPELINE_ORIGIN:
        return (
            '\nBLOCKED: commit grant carries no /commit pipeline provenance.\n'
            f'  grant: {grant_path}\n'
            f'  minted_by: {minted_by!r}\n'
            'A commit grant must record minted_by.origin = '
            f'"{commit_pipeline.PIPELINE_ORIGIN}", written by '
            'scripts/write-commit-grant.py only after it has verified that a real '
            '/commit pipeline run planned this repository. An unsigned grant is a '
            'bearer ticket and is not honored.\n'
            'To commit: invoke /commit, which mints a grant with provenance and '
            'dispatches changelog-analyst to spend it.\n'
        )

    agent_id = str(data.get('agent_id') or '').strip()
    if not agent_id:
        return (
            '\nBLOCKED: a commit grant may only be spent by the subagent the /commit '
            'pipeline dispatched, not by the caller holding the grant.\n'
            f'  grant: {grant_path}\n'
            '  caller: main agent (no agent_id in the PreToolUse payload)\n'
            'This bare `git commit` is running in an orchestrator/main-agent context. '
            'Commits are made by changelog-analyst, which /commit dispatches as a '
            'subagent after its close gate, repository plan and pre-commit QA gate '
            'have all run; those phases are the point of the grant.\n'
            'To commit: invoke /commit and let it dispatch changelog-analyst. Do not '
            'mint a grant and commit directly -- that is the bypass this refusal '
            'exists to stop.\n'
        )

    sids = [str(grant.get('sid') or ''), _get_session_id(data)]
    prompt_digest, digest_why = commit_pipeline.caller_prompt_sha256(
        _get_session_id(data), agent_id,
        os.environ.get('CLAUDE_PROJECT_DIR') or str(data.get('cwd') or '') or os.getcwd(),
        str(data.get('agent_transcript_path') or '') or None,
        str(data.get('transcript_path') or '') or None)
    role = resolve_agent_type(data)
    attestation, why = commit_pipeline.select_dispatch_attestation(
        sids, str(grant.get('created_at') or ''), prompt_digest,
        caller_role=role, prompt_why=digest_why)
    if not attestation:
        return (
            '\nBLOCKED: no changelog-analyst dispatch attestation backs this commit '
            'grant for this caller.\n'
            f'  grant: {grant_path}\n'
            f'  caller agent_id: {agent_id}, role: {role or "unresolved"}\n'
            f'  reason: {why}\n'
            'The only intended writer of an attestation is '
            'hooks/pretool-commit-dispatch-attest.py, on the real PreToolUse:Agent '
            'event for a changelog-analyst dispatch; Bash writes into that namespace '
            'are intercepted verb by verb (hooks/pretool-bash-safety.sh Layer 1.E3), '
            'which raises the cost of forging one without being an absolute barrier. '
            'The requirement being enforced here is identity: an attestation counts '
            'only for the subagent whose own dispatch prompt it records. Its absence '
            'means the commit pipeline never dispatched this caller as '
            'changelog-analyst for this grant, so the grant is being spent by a bearer '
            'rather than by the pipeline.\n'
            'To commit: invoke /commit so the dispatch actually happens.\n'
        )
    return ''


def _evaluate_commit(command, data):
    cwd = _hook_cwd(data)
    if _auto_bulk_subject(command, cwd):
        # The auto-bulk subject authorizes nothing by itself: a live /commit --bulk
        # sentinel must back it, and a pending /commit grant for this target goes first.
        if _has_bulk_commit_sentinel(data):
            if _has_active_commit_grant(command):
                _block(
                    '\nDEFERRED: auto-bulk commit skipped — an active single-use '
                    'commit grant exists (<state dir>/claude-commit-grant-*.json) '
                    'that is bound to THIS repo/branch/HEAD and still unspent.\n'
                    'A /commit cycle is in progress; auto-bulk will retry on the '
                    'next scheduled cycle.\n'
                )
            return
        _block(
            '\nBLOCKED: auto-bulk commit requires a bulk-commit sentinel.\n'
            'The `auto-bulk:` prefix is only authorized when changelog-analyst '
            'is dispatched by the user via /commit --bulk, which writes '
            '<state dir>/claude-bulk-commit-sentinel-<sid>-<nonce>.json (30 min TTL).\n'
            'To run bulk commits: invoke /commit --bulk from your Claude session.\n'
        )
    if _check_git_allowlist(command, data):
        return
    # /commit writes one repository-bound grant per repository of its plan, so the
    # grant is selected by the commit's target, not by recency.
    live = [(path, grant) for path, grant in _collect_commit_grant_candidates()
            if not _end_time_passed(grant.get('expires_at', ''))]
    provenance_refusal = ''
    for grant_path, grant in live:
        if _grant_matches_commit_target(grant, command):
            # Who spends it and with what message, read only for a grant bound to
            # this target. A refusal is kept and the next grant tried, so one stale
            # grant cannot shadow a valid one; the first refusal is reported.
            refusal = (_grant_provenance_refusal(grant, grant_path, data)
                       or _task_id_refusal(grant, grant_path, command, data))
            if refusal:
                provenance_refusal = provenance_refusal or refusal
                continue
            _enforce_commit_grant_binding(grant, command)
            # Spent by an unlink only one event can win; the loser tries the next grant.
            if not _spend_grant(grant_path):
                continue
            # The finalizer's journal pointer is keyed by this event, not a session
            # id: the grant's sid and the finalizer's may differ.
            commit_journal.write_event_pointer(
                commit_journal.event_key(data), commit_journal.raw_tool_use_id(data),
                grant)
            return
    if provenance_refusal:
        _block(provenance_refusal)
    # A live grant bound elsewhere: its binding check names the mismatch.
    if live:
        _enforce_commit_grant_binding(live[0][1], command)
    message = _commit_message_text(command, cwd) or ''
    _block_default_deny_commit(message.partition('\n')[0])


def _evaluate_merge(command, data):
    """Every agent `git merge` is refused unless /allow grants it.

    /merge merges through hooks/merge.sh, whose own subprocess runs git merge,
    which no hook sees; the merge-analyst grant that decides /merge is checked
    at the merge-analyst's own Write of it (hooks/posttool-allowlist-consume.py,
    hooks/lib/merge_grant.py) and read verbatim by /merge.
    """
    if _check_git_allowlist(command, data):
        return
    _block(
        '\nBLOCKED: agent git merge - only /merge may merge, through its '
        'wrapper hooks/merge.sh.\n'
        'Command excerpt: %s\n' % command[:200]
        + 'Main agent may bypass with /allow <pattern> before the git merge command.\n'
    )


# Added to every block the guard emits while the main agent holds /do consent.
DO_NOT_COVERED = (
    '/do consent does not cover git commit, git push, a git operation this guard refuses '
    'without it that can move the protected branch, or a git command this guard cannot '
    'classify, which may be any of them: a commit lands through /close, then /commit; a '
    'push through /push; a merge into the protected branch through /merge.\n'
)

# With one of these words in a command, git may run in another directory
# than the hook's (_DIR_CHANGE_RE) or on another branch than the hook-time HEAD
# (_BRANCH_CHANGE_RE). Read anywhere in the command: `&`, `|`, loops, functions
# and traps run its parts in an order the text does not give. `\.` is the dot
# builtin (source).
_DIR_CHANGE_RE = re.compile(
    r'(?<![\w./-])(?:cd|pushd|popd|source|GIT_DIR|GIT_WORK_TREE|GIT_COMMON_DIR)(?![\w./-])'
    r'|(?:^|[;&|(){]|\b(?:then|do|else))\s*\.\s')
_BRANCH_CHANGE_RE = re.compile(r'(?<![\w./-])(?:checkout|switch|symbolic-ref)(?![\w./-])')
_EXPANSION = re.compile(r'[$`*?\[{]')  # a name the shell or git may expand


# The git subcommands that can move a branch ref: on HEAD's branch, or by name.
_MOVES_HEAD = frozenset({'merge', 'pull', 'rebase', 'cherry-pick', 'revert', 'am', 'reset'})
_MOVES_NAMED = frozenset({'pull', 'fetch', 'rebase', 'update-ref', 'symbolic-ref', 'branch',
                          'checkout', 'switch', 'worktree', 'filter-branch', 'filter-repo',
                          'fast-import'})


def _operands(words, takes_value=()):
    """The words that are not options, nor the value of an option in `takes_value`."""
    return [w for i, w in enumerate(words) if (not w.startswith('-') or w == '-')
            and not (i and words[i - 1] in takes_value)]


def _reset_moves(args):
    """`git reset <args>` moves HEAD's branch: one commit operand other than
    HEAD and no pathspec; an operand that names no commit is a path."""
    if '--' in args:
        if args[args.index('--') + 1:]:
            return False
        args = args[:args.index('--')]
    ops = _operands(args)
    if len(ops) != 1 or {'-p', '--patch'} & set(args) or any(
            a.startswith('--pathspec-from-file') for a in args):
        return False
    return ops[0] not in ('HEAD', '@') and bool(_EXPANSION.search(ops[0]) or _git_output(
        ['rev-parse', '-q', '--verify', ops[0] + '^{commit}']))


def _branch_writes(inv):
    """(moves the branch HEAD is on, [branch names it writes]) for one git
    invocation; the name `*` stands for refs the guard cannot list."""
    sub = inv.subcommand
    if sub not in _MOVES_HEAD | _MOVES_NAMED:
        return False, []
    try:  # the words as the shell passes them (ref names hold no space)
        args = shlex.split(' '.join(inv.args))
    except ValueError:  # the segment splitter cut a quoted word: its operands are unknown
        return sub in _MOVES_HEAD, ['*'] if sub in _MOVES_NAMED else []
    ops = _operands(args)
    if sub in ('cherry-pick', 'revert') and {'-n', '--no-commit'} & set(args):
        return False, []
    if sub in ('merge', 'cherry-pick', 'revert', 'am', 'reset'):
        return sub != 'reset' or _reset_moves(args), []
    if sub in ('pull', 'fetch'):  # a refspec's destination is a local ref
        return sub == 'pull', [o.rpartition(':')[2] for o in ops if ':' in o]
    if sub == 'rebase':
        ops = _operands(args, ('--onto', '-x', '--exec', '-s', '--strategy', '-X',
                               '--strategy-option'))
        branch = ops[:1] if '--root' in args else ops[1:2]
        return not branch, branch + (['*'] if '--update-refs' in args else [])
    if sub in ('update-ref', 'symbolic-ref'):
        ops = _operands(args, ('-m',))
        if '--stdin' in args:
            return False, ['*']
        if sub == 'symbolic-ref' and len(ops) < 2 and not {'-d', '--delete'} & set(args):
            return False, []
        if ops[:1] == ['HEAD']:  # update-ref HEAD writes HEAD's branch; symbolic-ref switches
            return sub == 'update-ref' and '--no-deref' not in args, []
        return False, ops[:1]
    if sub == 'branch':
        flags = {f for a in args if a.startswith('-') for f in (
            [a.partition('=')[0]] if a.startswith('--') else ['-' + c for c in a[1:]])}
        if flags & {'-d', '-D', '--delete'}:
            return False, ops
        if flags & {'-m', '-M', '--move'}:  # one operand renames HEAD's branch
            return len(ops) == 1, ops
        if flags & {'-c', '-C', '--copy'}:
            return False, ops[-1:]
        return False, ops[:1] if flags & {'-f', '--force'} else []
    if sub in ('checkout', 'switch', 'worktree'):  # -B/-C reset the branch they name
        return False, [args[i + 1] for i, a in enumerate(args[:-1])
                       if a in ('-B', '-C', '--force-create')] + [
                           a.partition('=')[2] for a in args if a.startswith('--force-create=')]
    return False, ['*'] if sub in ('filter-branch', 'filter-repo', 'fast-import') else []


def _names_protected(name, protected):
    """The branch `name` (a ref, a refspec destination) is or may be `protected`."""
    name = name.lstrip('+')
    if re.match(r'refs/(?!heads/)[\w.-]+/', name):
        return False
    name = re.sub(r'^(?:refs/)?heads/', '', name)
    return name == protected or bool(_EXPANSION.search(name))


def _protected_branch():
    """The branch refs/remotes/origin/HEAD names (local refs, as the overnight
    launcher resolves it), or ''. Full ref names: `--short` prints `heads/main`
    once a tag is named `main` too."""
    ref = _git_output(['symbolic-ref', 'refs/remotes/origin/HEAD'])
    return ref[len('refs/remotes/origin/'):] if ref.startswith('refs/remotes/origin/') else ''


def _moves_protected_branch(command, invocations):
    """True when a git operation in `command` can move the protected
    branch's ref (_branch_writes: one on HEAD's branch while HEAD is on it, or
    one that writes it by name), or the guard cannot tell where it lands: a
    directory change or GIT_DIR-style redirect in the command, a branch change
    in it for an operation on HEAD, a prefix or an option before the operation's
    subcommand, a detached HEAD, or an unset origin/HEAD."""
    writes = [_branch_writes(inv) for inv in invocations]
    on_head = any(head for head, _names in writes)
    names = [name for _head, named in writes for name in named]
    if not (on_head or names):
        return False
    if (_ambient_git_redirect_present() or _DIR_CHANGE_RE.search(command)
            or (on_head and _BRANCH_CHANGE_RE.search(command))):
        return True
    for seg in _shell_segments(command):
        toks = seg.split()
        if any(any(_branch_writes(inv)) and (
                _cmd_token_index(toks) or toks[1:2] != [inv.subcommand])
               for inv in iter_git_invocations(seg)):
            return True
    protected = _protected_branch()
    if not protected or any(_names_protected(name, protected) for name in names):
        return True
    head = _git_output(['symbolic-ref', '--quiet', 'HEAD']) if on_head else None
    return head in ('', 'refs/heads/' + protected)


def _evaluate_protected_move(command, data):
    if _check_git_allowlist(command, data):
        return
    _block(
        '\nBLOCKED: agent git ref move - this merge, plumbing, hard reset or ref '
        'mutation, refused without /do, can move the protected branch (%s), or the '
        'guard cannot tell the branch it lands on: a cd, pushd, popd, '
        'source or GIT_DIR-style redirect in it, a checkout, switch or symbolic-ref '
        'with an operation on HEAD, a prefix or an option before the subcommand, a '
        'detached HEAD or an unset origin/HEAD.\n'
        'Command excerpt: %s\n' % (_protected_branch() or 'unresolved', command[:200])
    )


def _block_default_deny_push(command):
    """Every agent push: /push pushes inside hooks/push.sh, which no hook sees.

    The text is quoted verbatim by the README's hero capture (.github/assets)."""
    _block(
        '\nBLOCKED: agent git push - agents are not authorized to push '
        'to remote from an agent context.\n'
        'Command excerpt: %s\n' % command[:200]
        + 'For automated push, use the /push slash command (which sets '
        'CLAUDE_PUSH_COMMAND_ACTIVE=1 and writes a single-use grant).\n'
        'For human-driven push, exit the agent context and run '
        'git push directly.\n'
        'Spec: spec-20260424-233926 section 5.2.4 (R4.3); '
        'ba-spec-20260425-redev2.md AC-A5.\n'
    )


def _evaluate_push(command, invocations, data):
    if any(_push_forces_or_deletes(inv) for inv in invocations if inv.subcommand == 'push'):
        _block(
            '\nBLOCKED: agent git push - force/delete/ref-rewrite push is forbidden.\n'
            'Command excerpt: %s\n' % command[:200]
            + 'Safety policy allows normal /push branch publication only; '
            'automatic backup must use namespaced recovery refs.\n'
        )
    if _check_git_allowlist(command, data):
        return
    _block_default_deny_push(command)


def _evaluate_reset_hard(command, invocations, data):
    if _check_git_allowlist(command, data):
        return
    reset_inv = next((inv for inv in invocations if inv.subcommand == 'reset'), None)
    target = _extract_reset_target(reset_inv) if reset_inv else ''
    _block(
        '\nBLOCKED: agent git reset --hard - hard reset is forbidden '
        'from agent flow.\n'
        + 'Command excerpt: %s\n' % command[:200]
        + 'Target: %r\n' % target
    )


def _evaluate_direct_ref_mutation(command, data):
    if _check_git_allowlist(command, data):
        return
    _block(
        '\nBLOCKED: agent direct git ref mutation - update-ref and '
        'branch force/delete/rename are forbidden.\n'
        'Command excerpt: %s\n' % command[:200]
        + 'Branch movement must go through expected-parent CAS wrappers.\n'
    )


def _looks_like_git_forbidden_plumbing(invocations):
    """git commands that write commits or move refs outside /commit and /merge.

    Read from the classified subcommand, so a word in a quoted argument is not one.
    """
    _FORBIDDEN_PLUMBING = {
        'commit-tree', 'cherry-pick', 'rebase', 'pull',
        'filter-branch', 'filter-repo', 'fast-import', 'revert', 'am',
    }
    for inv in invocations:
        if inv.subcommand in _FORBIDDEN_PLUMBING:
            return True
        if inv.subcommand == 'replace':
            if '-e' in inv.args or '--edit' in inv.args:
                return True
    return False


def _evaluate_forbidden_plumbing(command, data):
    if _check_git_allowlist(command, data):
        return
    _block(
        '\nBLOCKED: agent direct git plumbing is forbidden (R6).\n'
        'Command excerpt: %s\n' % command[:200]
        + 'Commit creation must go through the /commit slash command.\n'
    )


# The rules /do consent releases (_evaluate_command).
_DO_RELEASED = (_looks_like_git_merge, _looks_like_git_forbidden_plumbing,
                _looks_like_git_reset_hard, _looks_like_git_direct_ref_mutation)


# ---------------------------------------------------------------------------
# Residual-refusal recovery route
#
# A command whose git binary the classifier cannot resolve is refused before
# the invocation list is read, the allowlist cannot reach it, and /do is
# main-agent-only, so a subagent needs a route that cannot launder a command.
#
# Binding: there is no operation to name, so an override carries sha256 of the
# full command text; the authorized and the executed command are one string.
# Reach: an override answers only a refusal this guard already journaled
# (_digest_was_refused); it is single-use and short-lived.
# Limit: any agent with Bash can write the override file. Honoring one emits a
# stderr audit record naming who authorized it, why and what was refused, so a
# forged authorization shows in the transcript.
# ---------------------------------------------------------------------------

_RESIDUAL_OVERRIDE_DIR = os.path.join(harness_state_dir(), 'claude-git-residual-override')
_RESIDUAL_OVERRIDE_KIND = 'git-residual-override'
_RESIDUAL_HUMAN_ORIGIN = 'userpromptsubmit-hook'


def _residual_ns_path(name):
    """Path inside the override namespace. One constant, so tests repoint all."""
    return Path(_RESIDUAL_OVERRIDE_DIR) / name


def _command_digest(command):
    """sha256 of the FULL command text -- the override's only sound binding."""
    return hashlib.sha256(
        command.encode('utf-8', 'surrogateescape')).hexdigest()


def _append_residual_record(name, record):
    """Append one JSONL record. Best effort: audit must never crash the guard."""
    try:
        os.makedirs(_RESIDUAL_OVERRIDE_DIR, exist_ok=True)
        with open(_residual_ns_path(name), 'a') as fp:
            fp.write(json.dumps(record, sort_keys=True) + '\n')
    except Exception:
        pass


def _journal_residual_refusal(command, kinds, segments, digest, data):
    """Record that this exact command was refused, so an override can answer it.

    Also the human-facing record of WHAT to authorize: the digest printed in the
    refusal message is the key into this journal.
    """
    _append_residual_record('refusals.jsonl', {
        'event': 'residual_refusal',
        'at': datetime.now(timezone.utc).isoformat(),
        'command_sha256': digest,
        'command_excerpt': command[:200],
        'residual_kinds': kinds,
        'residual_segments': segments,
        'session_id': _get_session_id(data),
        'agent_id': str(data.get('agent_id') or ''),
    })


def _digest_was_refused(digest):
    """True iff this guard has already refused this exact command.

    Fails CLOSED: an unreadable/absent journal yields False, which leaves the
    refusal in place.
    """
    try:
        path = _residual_ns_path('refusals.jsonl')
        if not path.exists():
            return False
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if (rec.get('event') == 'residual_refusal'
                    and rec.get('command_sha256') == digest):
                return True
    except Exception:
        return False
    return False


def _find_residual_override(digest, kinds, was_refused):
    """Return (path, override) for a valid override answering this refusal.

    Every condition fails closed. `kinds` must be a SUBSET of what the human
    signed: an override issued for an obfuscated-token refusal cannot be spent
    on a command-substitution one.

    `was_refused` is the journal state as it stood BEFORE the current run
    journaled itself. Reading it after would make the property vacuous -- the
    run would satisfy its own precondition and a pre-minted override would fire
    on first contact.
    """
    if not was_refused:
        return None, None
    try:
        candidates = glob.glob(str(_residual_ns_path('*.json')))
        candidates.sort(key=lambda p: os.stat(p).st_mtime, reverse=True)
    except Exception:
        return None, None
    for path in candidates:
        ovr = _load_grant(path)
        if ovr is None:
            continue
        if ovr.get('kind') != _RESIDUAL_OVERRIDE_KIND:
            continue
        # Human-origin marker (a convention, not a guarantee -- see the header).
        if ovr.get('origin') != _RESIDUAL_HUMAN_ORIGIN:
            continue
        # WHO and WHY are structurally required, so no override can pass through
        # without an attributable authorizer and a stated justification.
        if not str(ovr.get('authorized_by') or '').strip():
            continue
        if not str(ovr.get('reason') or '').strip():
            continue
        if _end_time_passed(ovr.get('expires_at', '')):
            continue
        if ovr.get('command_sha256') != digest:
            continue
        signed = ovr.get('residual_kinds')
        if not isinstance(signed, list) or not set(kinds).issubset(set(signed)):
            continue
        return path, ovr
    return None, None


def _consume_residual_override(path):
    """Single-use: unlink BEFORE allowing, so a crash cannot leave it live."""
    try:
        os.unlink(path)
        return True
    except Exception:
        return False


def _audit_residual_override(path, ovr, kinds, segments, digest):
    """Emit the honor record on stderr: the transcript is the durable copy."""
    sys.stderr.write(
        '\nRESIDUAL-OVERRIDE HONORED: a human authorization cleared the '
        '"could not be statically classified" refusal for this command.\n'
        'Authorized by: %s\n' % ovr.get('authorized_by', '')
        + 'Reason: %s\n' % ovr.get('reason', '')
        + 'What was refused: %s\n' % ', '.join(kinds)
        + 'Refused segment(s): %s\n' % '; '.join(s.strip()[:80] for s in segments[:3])
        + 'Command sha256: %s\n' % digest
        + 'Override: %s (issued %s, expires %s, single-use -- now consumed)\n'
        % (path, ovr.get('created_at', ''), ovr.get('expires_at', ''))
        + 'This clears ONLY the unparseable-token refusal. Every other policy '
        'check still applies to every part of this command the guard can read.\n'
    )


def _evaluate_command(command, data, do_consent=False):
    # do_consent: the main agent holds /do consent, which releases the rules in
    # _DO_RELEASED and adds none: what one of them refuses stays refused when it
    # can move the protected branch or the guard cannot tell the branch it lands
    # on (_moves_protected_branch); git commit, git push and a git command the
    # guard cannot classify are judged as without it.
    invocations, residuals = classify_git_command(command)
    # A git-shaped command whose binary the classifier cannot resolve (`g\it push`,
    # `$GIT push`, `$(which git) push`) is refused before the invocation list and
    # before /allow: no grant can be shown to cover an unknown binary, and the
    # grant matcher may read `git status & $GIT push --force` as one `git status`.
    if residuals:
        kinds = sorted({kind for kind, _seg in residuals})
        segments = [seg for _k, seg in residuals]
        digest = _command_digest(command)
        # Read the journal BEFORE writing to it: an override must answer a
        # refusal from an EARLIER run, never the one this run is about to
        # record. Then journal unconditionally, so the attempt is auditable
        # whether or not it is subsequently cleared.
        was_refused = _digest_was_refused(digest)
        _journal_residual_refusal(command, kinds, segments, digest, data)
        ovr_path, ovr = _find_residual_override(digest, kinds, was_refused)
        if ovr is not None:
            # NOT a bypass. This clears the unparseable-token refusal only;
            # control falls through to every check below, so each part of the
            # command the guard CAN parse is still judged on its merits.
            _consume_residual_override(ovr_path)
            _audit_residual_override(ovr_path, ovr, kinds, segments, digest)
        else:
            _block(
                '\nBLOCKED: agent git command could not be statically classified.\n'
                'Command excerpt: %s\n' % command[:200]
                + 'Unresolvable command token(s): %s\n' % ', '.join(kinds)
                + 'Segment(s): %s\n' % '; '.join(seg.strip()[:80] for seg in segments[:3])
                + 'This command names its binary through a shell expansion, a '
                'substitution, or an escaped/quoted spelling, so the guard cannot '
                'prove which program runs or which git subcommand it receives.\n'
                + '\nTWO RECOVERY ROUTES, cheapest first:\n'
                + '  1. Re-issue it with the binary written literally (e.g. '
                '`git push` or `/usr/bin/git push`) so the policy checks can '
                'judge it on its merits. This is almost always the right fix '
                'and needs no authorization.\n'
                + '  2. If the binary genuinely cannot be written literally, ask '
                'your user for a residual override. Only the human can issue '
                'one -- you cannot authorize yourself and neither can another '
                'agent. It is bound to this exact command text, is single-use, '
                'expires, and its use is recorded in the transcript. The human '
                'runs:\n'
                + '       scripts/write-git-residual-override.py \\\n'
                + '         --command-sha256 %s \\\n' % digest
                + '         --residual-kinds %s \\\n' % ','.join(kinds)
                + '         --reason "<why this command must run as written>"\n'
                + '     Command sha256: %s\n' % digest
            )
    if not invocations:
        return
    # An /allow grant settles every command but a push, whose force/delete refusal
    # no grant lifts (_evaluate_push).
    if not _looks_like_git_push(invocations) and _check_git_allowlist(command, data):
        return
    if (do_consent and any(rule(invocations) for rule in _DO_RELEASED)
            and _moves_protected_branch(command, invocations)):
        _evaluate_protected_move(command, data)
    if not do_consent and _looks_like_git_forbidden_plumbing(invocations):
        _evaluate_forbidden_plumbing(command, data)
    if not do_consent and _looks_like_git_reset_hard(invocations):
        _evaluate_reset_hard(command, invocations, data)
    if not do_consent and _looks_like_git_direct_ref_mutation(invocations):
        _evaluate_direct_ref_mutation(command, data)
    if _looks_like_git_push(invocations):
        _evaluate_push(command, invocations, data)
    if not do_consent and _looks_like_git_merge(invocations):
        _evaluate_merge(command, data)
    if _looks_like_git_commit(invocations):
        _evaluate_commit(command, data)


def main():
    try:
        data = json.loads(_read_stdin())
    except ValueError as exc:
        # No tool or command to read: 0 as before, unless the raw text may run git
        # (the hook is registered for Bash calls alone).
        sys.exit(_internal_error_exit(exc, 'could not read its input'))
    try:
        if data.get('tool_name', '') != 'Bash':
            sys.exit(0)
        command = (data.get('tool_input', {}) or {}).get('command', '') or ''
        if not command:
            sys.exit(0)
        # /do consent (main agent only) releases rules and adds none (_evaluate_command).
        do_consent = has_do_consent(data)
        try:
            _evaluate_command(command, data, do_consent)
        except SystemExit as exc:
            if do_consent and exc.code == 2:
                sys.stderr.write(DO_NOT_COVERED)
            raise
    except SystemExit:
        raise
    except Exception as exc:
        # An error is no verdict: refuse what may run git (_internal_error_exit).
        sys.exit(_internal_error_exit(exc))
    sys.exit(0)


if __name__ == '__main__':
    main()
