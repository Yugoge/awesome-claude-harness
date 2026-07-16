#!/usr/bin/env python3
"""
PreToolUse Hook: Agent git-privilege guard.

Scope: Runs on EVERY Bash tool call in agent (subagent + main-agent
orchestrator) contexts, regardless of whether the session is overnight
or interactive. The b5d447e regression (2026-04-21 17:45 UTC) which
this guard exists to prevent - a 93-file `git commit` + `git push`
sweep authored by the orchestrator with no human signoff - happened in
an INTERACTIVE session (JSONL message 293 of session
962de59f-fe0b-416e-b88b-7345fdf569e2, prompt `全部commit push`,
no overnight-state-*.json present). Gating this hook on overnight-
context only would let that exact regression class pass through; the
guard must be always-on per spec 5.2.4 line 240-241.

The whitelists below preserve the legitimate paths:
  - `^auto-bulk: end-of-cycle commit for ` blessed bridge from /merge
  - CLAUDE_MERGE_COMMAND_ACTIVE=1 env exemption for git merge
  - reset to HEAD (non-destructive)
  - human-driven commits: the human exits the agent context and runs
    git commit at their own shell; this hook does not see those calls.

Forbidden agent operations:
  - git commit -m '<msg>' whose message does NOT match
    `^auto-bulk: end-of-cycle commit for ` (the blessed bridge from
    /merge per spec section 5.2.1.2 R2). Stderr literal:
    `BLOCKED: agent git commit`.
  - git merge unless the env var `CLAUDE_MERGE_COMMAND_ACTIVE=1` is
    set by /merge at start. Stderr literal: `BLOCKED: agent git merge`.
  - git push (any form). Stderr literal:
    `BLOCKED: agent git push`.
  - every hard reset form. Stderr literal:
    `BLOCKED: agent git reset --hard`.
  - direct ref mutation (`git update-ref`, branch force/delete/rename,
    or writable HEAD symbolic-ref changes).

Allowed: git add, git status, git log, git diff, git show, git blame,
git ls-files, git ls-tree, git restore (working-tree only), git branch
(list), git rev-list, git rev-parse, git symbolic-ref, git for-each-ref,
and git stash list/show/pop (non-destructive forms). Hard reset and direct
ref mutation are not agent-accessible.

Spec: spec-20260424-233926 section 5.2.4 (R4.3) line 233-249.

Revision history:
  2026-04-25 (Scheme 6 manifest-validation): added two narrow
  authorized-exemption paths for `git push` and `git commit` driven by
  the new `/push` and `/commit` slash-command wrappers. Each path
  requires BOTH:
    1. an OS-level env var (`CLAUDE_PUSH_COMMAND_ACTIVE=1` for push,
       `CLAUDE_COMMIT_COMMAND_ACTIVE=1` for commit) set by the wrapper
       in the child's environment (NOT inline-prepended on the agent
       command line), AND
    2. a single-use grant manifest at
       `/tmp/claude-{push|commit}-grant-<sid>.json` whose contents
       bind the operation to a specific branch + expected_head + remote
       (push) or task_id + allowed_files + expected_message_sha256
       (commit).
  Inline-env injection (e.g. `CLAUDE_PUSH_COMMAND_ACTIVE=1 git push ...`
  on a single Bash call) is rejected by literal-substring scan of the
  raw command text BEFORE the env-var check, defeating the b5d447e
  attack class even if the agent learns the env name. The grant file
  is unlinked on first valid consumption (single-use); validation
  failures DO NOT consume the grant (forensics + brute-force resistance).
  Cross-bypass is blocked: the push env name does NOT bypass commit,
  and vice versa.  Authority: spec ba-spec-20260425-redev2.md §4.1
  (AC-A1..AC-A17), close-report-20260425-push-commit-debate.md
  (Scheme 6 verdict CLOSE: YES).
  2026-04-25 (Option alpha): made always-on. Removed the overnight-
  context gate after confirming b5d447e occurred in an interactive
  session - the gate would have let the regression through. The
  `_is_overnight_active()` helper is retained as dead code for
  reference but is no longer consulted by main().
  2026-04-25 (earlier): replaced the dead-code `CLAUDE_OVERNIGHT_ACTIVE`
  env-var path with the canonical state-file probe.
  2026-07-15 (repo/branch/HEAD parity fix): `_evaluate_commit` previously
  validated ONLY `expires_at` before honoring a commit grant -- unlike
  `_evaluate_push`, which additionally binds `branch` (_validate_push_grant_branch),
  `expected_head` (_validate_push_grant_head), and `remote`
  (_validate_push_grant_remote) to the grant's issuance-time values. A
  validly-issued, unexpired commit grant could therefore authorize a commit
  in a different repository/branch/commit than the one it was written for.
  Added `_validate_commit_grant_repo` / `_validate_commit_grant_branch` /
  `_validate_commit_grant_head`, mirroring the push-grant validators, plus
  `_extract_commit_dash_c_dir` to resolve the actual target directory of the
  commit invocation (changelog-analyst always commits via
  `git -C "${GIT_ROOT}" commit ...`, never a bare `git commit` in its own
  CWD -- validating against the hook's own CWD unconditionally would
  wrongly reject every nested ~/.claude repo commit). `write-commit-grant.py`
  now records `repo_root`/`branch`/`expected_head` at issuance time.
  2026-07-16 (commit-grant redirect-vector closure): the 2026-07-15 binding
  only inspected `-C <dir>`, so a commit could still land in a DIFFERENT repo
  via (1) `--git-dir`/`--work-tree`/`--namespace` global flags, (2) inline
  `GIT_DIR=`/`GIT_WORK_TREE=`/`GIT_COMMON_DIR=` env assignment, (3) ambient
  GIT_DIR/GIT_WORK_TREE env, or (4) a second chained `git -C <other> commit`
  (only the first invocation was validated). `_enforce_commit_grant_binding`
  now: blocks ambient redirect env; enumerates EVERY commit invocation via
  `_iter_commit_invocations` (segment + token aware); hard-blocks any
  flag/inline-env redirect (fail closed, mirroring "multiple -C -> block");
  and validates repo/branch/HEAD per invocation against its own resolved -C
  target. The parallel PUSH-grant redirect hole is documented as a separate
  follow-up (see comment atop `_evaluate_push`) and intentionally left unfixed.

Exit codes:
  0: Allow tool use
  2: Block tool use
"""

import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.allowlist import read_grant_for_git_command, match_sentinel_grant_for_bash_command  # noqa: E402
from lib.git_command_classifier import iter_git_invocations, GitInvocation  # noqa: E402
# Segment/tokenization primitives reused (read-only) so the commit-grant binding
# can enumerate EVERY git-commit invocation in a chained command string and
# inspect each invocation's leading env-assignments + global-option flags
# token-aware (precise, no false match on the word "commit" inside a message).
# These are consumed, NOT modified — the shared classifier stays untouched
# (scope: this fix is the COMMIT grant path only).
from lib.git_command_classifier import (  # noqa: E402
    _segments as _shell_segments,
    _command_token_index as _cmd_token_index,
    _ENV_ASSIGN_RE as _ENV_ASSIGN_RE,
    _GIT_GLOBAL_VALUE as _GIT_GLOBAL_VALUE,
)


BLESSED_BRIDGE_RE = re.compile(r'auto-bulk:\s*end-of-cycle commit for\b')

GIT_GLOBAL_OPTION_RE = (
    r'(?:\s+(?:-[Cc]\s+\S+|-[Cc]\S+|'
    r'--(?:git-dir|work-tree|namespace|exec-path|super-prefix|config-env)'
    r'(?:=\S+|\s+\S+)|'
    r'--(?:bare|no-pager|paginate|no-replace-objects|literal-pathspecs|'
    r'glob-pathspecs|noglob-pathspecs|icase-pathspecs|no-optional-locks)|'
    r'-[pP]))*'
)
GIT_COMMAND_RE = r'(?:^|[\s;&|()`])git' + GIT_GLOBAL_OPTION_RE + r'\s+'

# Matches a `git <global-options>* commit` invocation and CAPTURES the
# global-options span (group 1) so `_extract_commit_dash_c_dir` can pull an
# explicit `-C <dir>` out of it. Reuses the exact GIT_GLOBAL_OPTION_RE grammar
# above (kept in sync intentionally) so a change to one does not silently
# desync from the other.
#
# The optional `(?:\S*/)?` before `git` lets a PATH-QUALIFIED invocation
# (`/usr/bin/git`, `./git`) expose its `-C <dir>` span too. Without it the
# leading anchor class `[\s;&|()`]` (which excludes `/`) failed to match a
# path-qualified git, so `git -C <other-repo> commit` written as
# `/usr/bin/git -C <other-repo> commit` yielded an EMPTY options span -> the
# `-C` redirect was invisible and the commit validated against the hook's cwd
# instead of <other-repo> (codex adversarial finding, 2026-07-16).
GIT_COMMIT_INVOCATION_RE = re.compile(
    r'(?:^|[\s;&|()`])(?:\S*/)?git(' + GIT_GLOBAL_OPTION_RE + r')\s+commit\b'
)

# `-C` (capital only) is "run as if git was started in <dir>". Lowercase `-c`
# is an unrelated config override (`-c name=value`) and must never be
# mistaken for a directory. Matches both `-C dir` and glued `-Cdir` forms,
# and quoted values (`-C "a b"` / `-C 'a b'`).
DASH_CAPITAL_C_RE = re.compile(r'-C\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+))')

# Repo/work-tree REDIRECT vectors for a `git commit`. Any of these repoints the
# commit's EFFECTIVE target repository/work-tree away from the invocation's cwd,
# so the grant's repo/branch/HEAD binding cannot be soundly verified against the
# live git state the commit will actually mutate. `-C <dir>` is deliberately NOT
# in this set: `-C` is the ONE legitimate redirect (changelog-analyst commits the
# nested repo via `git -C <nested> commit`), and it is resolved + validated
# against the grant rather than blocked. Everything below is FAIL-CLOSED
# (hard block), mirroring the existing "multiple -C flags -> hard block"
# philosophy: no legitimate committer in this repo uses --git-dir / --work-tree /
# --namespace or a GIT_DIR / GIT_WORK_TREE / GIT_COMMON_DIR env redirect, and a
# commit we cannot unambiguously locate must be rejected, not guessed.
_GIT_REDIRECT_ENV_VARS = ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR')
_GIT_REDIRECT_FLAGS = ('--git-dir', '--work-tree', '--namespace')

# Shell builtins that change the effective cwd for a LATER git commit in the
# same command string. The guard probes repo/branch/HEAD from its OWN cwd (or a
# `-C <dir>`), so a `cd <other-repo> && git commit` runs the real commit in a
# cwd the probe never sees -> the grant would validate against the hook's cwd
# while the commit lands elsewhere (codex adversarial finding, 2026-07-16).
# Any such builtin preceding a commit -> fail closed (block).
_CWD_CHANGE_CMDS = ('cd', 'pushd', 'popd')


def _block(message):
    sys.stderr.write(message)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Scheme 6 manifest-validation helpers (added 2026-04-25)
# ---------------------------------------------------------------------------

def _get_session_id(data):
    """Extract session_id from the parsed PreToolUse stdin payload.

    Returns empty string when missing.  Used to compute the per-session
    grant-file path /tmp/claude-{kind}-grant-<sid>.json.
    """
    try:
        sid = data.get('session_id', '') or ''
        return str(sid)
    except Exception:
        return ''


def _has_do_consent(data: dict) -> bool:
    """Return True if main agent has /do consent for this turn."""
    if data.get('agent_id'):  # subagents cannot use /do
        return False
    sid = _get_session_id(data)
    if not sid:
        return False
    try:
        flag = Path(f'/tmp/claude-orchestrator-consent-{sid}.flag')
        return flag.exists() and flag.read_text().strip() == 'true'
    except Exception:
        return False


def _check_git_allowlist(command: str, data: dict) -> bool:
    """Check /allow grant for non-push git operations. Read-only.

    Main-agent only for LEGACY grants. Sentinel grants (task 20260524-133650):
    extend to subagents — mirrors M2 decision in pretool-bash-safety.sh:484.
    IS_SUBAGENT check preserved for legacy path only.
    """
    sid = _get_session_id(data)
    if not sid:
        return False
    # Sentinel grant check (task 20260524-133650): NOT gated by subagent firewall.
    # User-granted sentinels must be honored in subagent context per M2 (20260521-090200).
    task_id = os.environ.get('CLAUDE_TASK_ID') or sid
    if match_sentinel_grant_for_bash_command(task_id, command) is not None:
        return True
    # Legacy grant check: subagent firewall preserved (original behavior).
    if data.get('agent_id'):
        return False
    return read_grant_for_git_command(command, sid)


def _inline_env_present(command, var_name):
    """True iff the raw command string contains literal `<var_name>=`.

    This is the literal-substring defense against the inline-env
    injection attack (e.g. `CLAUDE_PUSH_COMMAND_ACTIVE=1 git push ...`
    on a single Bash call).  We deliberately use plain substring
    matching on the raw command text - not a regex, not a normalized
    form - so that any encoding of the literal `VAR=` token in the
    command is caught.
    """
    if not command or not var_name:
        return False
    needle = var_name + '='
    return needle in command


def _find_grant(kind, sid):
    """Return (resolved_path, grant_dict) or (None, None) on miss/invalid.

    Per close-report-20260425-push-commit-debate.md §1-2, wrappers write
    per-nonce filenames `/tmp/claude-{kind}-grant-<sid>-<nonce>.json` so
    that two concurrent wrapper invocations under the same SID cannot
    collide on a single shared file.  The guard discovers the grant by
    glob, sorts by mtime descending, and returns the most recent
    JSON-parseable candidate.  The caller is responsible for unlinking
    the resolved path (single-use) on validation success.
    """
    pattern = '/tmp/claude-%s-grant-%s-*.json' % (kind, sid)
    try:
        candidates = glob.glob(pattern)
    except Exception:
        return (None, None)
    try:
        candidates.sort(key=lambda p: os.stat(p).st_mtime, reverse=True)
    except Exception:
        # If stat() races a concurrent unlink, fall back to lexical order.
        candidates.sort(reverse=True)
    for path in candidates:
        grant = _load_grant(path)
        if grant is not None:
            return (path, grant)
    return (None, None)


def _load_grant(grant_path):
    """Read and JSON-parse a grant file.

    Returns the parsed dict on success, or None on missing / empty /
    malformed / unreadable.  Catches all exceptions and fails closed
    (caller treats None as "no valid grant -> block").
    """
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


def _find_grant_any(kind):
    """Fallback grant search ignoring SID.

    Used when the subagent's session_id (from PreToolUse payload) differs
    from the orchestrator's CLAUDE_SESSION_ID used when writing the grant.
    Searches all grants of the given kind, returns the most recent valid one.
    """
    pattern = '/tmp/claude-%s-grant-*-*.json' % kind
    try:
        candidates = glob.glob(pattern)
    except Exception:
        return (None, None)
    try:
        candidates.sort(key=lambda p: os.stat(p).st_mtime, reverse=True)
    except Exception:
        candidates.sort(reverse=True)
    for path in candidates:
        grant = _load_grant(path)
        if grant is not None:
            return (path, grant)
    return (None, None)


def _collect_commit_grant_candidates():
    """Return ALL parseable commit-grant candidates as (path, grant) pairs,
    most-recent (highest mtime) first.

    Unlike _find_grant / _find_grant_any (which return only the single newest
    grant), this returns every candidate so _evaluate_commit can SELECT the
    grant whose repo_root/branch/expected_head match the commit's target repo
    instead of blindly trusting the newest one. /commit (BULK=false) writes TWO
    repo-bound grants -- one for CONTROL_ROOT and one for the nested ~/.claude
    repo (written second => newer mtime). The root-repo commit fires first and
    MUST bind to its OWN (older) grant; selecting by recency alone blocks it on
    a repository mismatch (docs/dev/peer-review-grant-parity.md CRITICAL).

    The any-SID glob is a superset of the SID-specific glob, so one glob covers
    both the fast path and the subagent SID-propagation fallback documented in
    _find_grant_any. Locked (.lck) grants are excluded (single-use in-flight),
    matching _find_grant / _find_grant_any.
    """
    pattern = '/tmp/claude-commit-grant-*-*.json'
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


def _unlink_grant(grant_path):
    """Remove the grant file, swallowing all errors.

    Single-use grant unlink: called ONLY on successful validation paths,
    NEVER on validation-failure paths (so failure does not consume the
    grant - this preserves forensic visibility and resists brute-force
    confirm/deny probing).
    """
    try:
        os.unlink(grant_path)
    except Exception:
        pass


# Pointer-file path template for deferred commit-grant consumption (Fix B).
# PreToolUse locks the grant (rename → .lck) and writes this pointer so
# PostToolUse can locate it for finalization.
_COMMIT_GRANT_ACTIVE_TEMPLATE = '/tmp/claude-commit-grant-active-{sid}.json'


def _lock_grant_for_posttool(grant_path, effective_sid):
    """Lock a commit grant for deferred PostToolUse consumption (Fix B).

    Renames grant_path → grant_path + ".lck" to atomically remove it from
    _find_grant / _find_grant_any searches (prevents double-use), then writes
    a pointer at _COMMIT_GRANT_ACTIVE_TEMPLATE so posttool-allowlist-consume.py
    can finalize:
      - exit 0  → unlink the .lck file (consumed)
      - non-zero → rename .lck back to original (grant preserved for retry)

    Falls back to immediate _unlink_grant if the rename fails (e.g., cross-
    device move or permission error) so the guard stays fail-closed.
    """
    locked_path = grant_path + '.lck'
    try:
        os.rename(grant_path, locked_path)
    except OSError:
        _unlink_grant(grant_path)
        return
    pointer_key = effective_sid or 'any'
    pointer_path = _COMMIT_GRANT_ACTIVE_TEMPLATE.format(sid=pointer_key)
    try:
        with open(pointer_path, 'w') as fp:
            json.dump({'locked_path': locked_path, 'original_path': grant_path}, fp)
    except OSError:
        pass


def _git_output(args):
    """Run `git <args...>` and return stripped stdout, or '' on any error.

    Used to read the current branch / HEAD / staged-set inside the
    guard.  Always runs in the agent's CWD (no `-C` override) so that
    the resolved values match what the agent's `git push|commit` call
    would see.
    """
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


def _extract_push_remote(invocation):
    """Best-effort extraction of the explicit remote argument from a push
    GitInvocation.  Returns the first positional token in invocation.args
    that is not a flag (does not start with `-`), or '' when not found.
    """
    for tok in invocation.args:
        if tok.startswith('-'):
            continue
        if tok.startswith('+') or tok.startswith(':'):
            continue
        return tok
    return ''


def _extract_dash_c_from_span(options_span, command_excerpt):
    """Resolve the single `-C <dir>` value from a commit invocation's
    global-options span, or '' when no explicit `-C` is present.

    changelog-analyst's canonical commit form is `git -C "${GIT_ROOT}" commit
    -F <msgfile>` (agents/changelog-analyst.md) for BOTH the root repo and
    the nested ~/.claude repo -- it never `cd`s, only ever passes `-C`. The
    guard's own CWD is therefore CONTROL_ROOT for the entire session, even
    while committing the nested repo. Scoping repo/branch/HEAD validation to
    this extracted directory (instead of blindly using the hook's CWD, as
    `_git_output`'s docstring describes for push) is required so the nested-
    repo commit is validated against ITS OWN repo, not CONTROL_ROOT's.

    Codex adversarial review (2026-07-15) found two sharp edges, both handled
    here by blocking rather than guessing:
      - Multiple `-C` options: git applies each in sequence (a later ABSOLUTE
        `-C` fully overrides an earlier one -- verified empirically), so
        naively taking the first match would validate one directory while
        the commit actually lands in another. Since no legitimate caller in
        this repo ever passes more than one `-C` to a commit invocation,
        ambiguity is treated as a hard block rather than an attempt to
        replicate git's full (and, for relative paths, chained) -C semantics.
      - An unresolved shell variable reference (e.g. `${GIT_ROOT}` never
        substituted with a concrete path before the command reached the
        Bash tool): subprocess.run() does not perform shell expansion, so
        passing this literally to `git -C` would fail and could otherwise
        surface as a confusing generic "repository mismatch". Blocked here
        with a distinct, clearer message instead.
    """
    matches = list(DASH_CAPITAL_C_RE.finditer(options_span))
    if not matches:
        return ''
    if len(matches) > 1:
        _block(
            '\nBLOCKED: agent git commit - multiple -C directory overrides '
            'in one commit invocation are not supported.\n'
            'Command excerpt: %s\n' % command_excerpt[:200]
            + 'Re-issue the commit with exactly one -C <dir> (or none).\n'
        )
    dm = matches[0]
    value = dm.group(1) or dm.group(2) or dm.group(3) or ''
    if '$' in value:
        _block(
            '\nBLOCKED: agent git commit - the -C argument %r looks like an '
            'unresolved shell variable reference, not a concrete path.\n' % value
            + 'Command excerpt: %s\n' % command_excerpt[:200]
            + 'Substitute the concrete resolved absolute directory before '
            'submitting the commit command.\n'
        )
    return value


def _extract_commit_dash_c_dir(command):
    """Back-compat single-invocation `-C <dir>` extractor (whole command).

    Retained for external/test callers; the live binding path now enumerates
    EVERY commit invocation via `_iter_commit_invocations` and calls
    `_extract_dash_c_from_span` per invocation.
    """
    m = GIT_COMMIT_INVOCATION_RE.search(command)
    if not m:
        return ''
    return _extract_dash_c_from_span(m.group(1), command)


def _ambient_git_redirect_present():
    """True iff the guard's OWN environment carries a GIT_DIR / GIT_WORK_TREE /
    GIT_COMMON_DIR redirect.

    An ambient redirect repoints the effective target repo/work-tree of a bare
    `git commit` (and of the guard's own `_git_output` probes) away from the
    invocation cwd, so the grant's repo/branch/HEAD binding cannot be soundly
    verified. Fail closed: block rather than validate against an ambiguous
    target. No legitimate agent commit path sets these in the ambient env.
    """
    return any(os.environ.get(v) for v in _GIT_REDIRECT_ENV_VARS)


def _iter_commit_invocations(command):
    """Yield one descriptor dict per `git ... commit` invocation in `command`.

    Segment-aware (reuses the canonical shell segmenter) so EVERY commit in a
    chained / `&&`-joined / newline-separated / multi-invocation command string
    is enumerated -- not just the first. This closes the "second chained commit
    runs unvalidated" hole. Token-aware within each segment (skips leading
    env-assignments + command wrappers, basename-matches the git token, walks
    git global options) so the word "commit" appearing inside a -m message is
    never mistaken for a second invocation.

    Each descriptor:
      segment              : the raw shell segment (for -C extraction + excerpts)
      options_span         : global-options text between `git` and `commit`
      inline_env_redirect  : True iff a GIT_DIR/GIT_WORK_TREE/GIT_COMMON_DIR
                             assignment is inline-prefixed before the git token
      flag_redirect        : True iff --git-dir/--work-tree/--namespace appears
                             as a git global option before the commit subcommand
      cwd_redirected       : True iff a cd/pushd/popd segment executes BEFORE
                             this commit in the same command string (the probe
                             cannot see the post-cd cwd -> fail closed)

    Segments are visited in execution order so `cwd_redirected` reflects only a
    cwd change that PRECEDES the commit; a `cd` after the commit is harmless and
    does not taint it.
    """
    cwd_redirected = False
    for seg in _shell_segments(command):
        toks = seg.split()
        if not toks:
            continue
        idx = _cmd_token_index(toks)
        if idx is None:
            continue
        # A cd/pushd/popd segment redirects the cwd for every LATER git commit.
        if os.path.basename(toks[idx].strip('\'"')) in _CWD_CHANGE_CMDS:
            cwd_redirected = True
            continue
        if os.path.basename(toks[idx]) != 'git':
            continue
        after_git = toks[idx + 1:]
        # Split git global options from the subcommand (mirrors classifier's
        # _git_subcommand, but retains the global-option token list).
        i = 0
        while i < len(after_git):
            a = after_git[i]
            if a in _GIT_GLOBAL_VALUE:
                i += 2
                continue
            if a.startswith('-'):
                i += 1
                continue
            break
        global_opts = after_git[:i]
        subcommand = after_git[i] if i < len(after_git) else None
        if subcommand != 'commit':
            continue
        inline_env_redirect = any(
            _ENV_ASSIGN_RE.match(t) and t.split('=', 1)[0] in _GIT_REDIRECT_ENV_VARS
            for t in toks[:idx]
        )
        flag_redirect = any(
            t.split('=', 1)[0] in _GIT_REDIRECT_FLAGS for t in global_opts
        )
        m = GIT_COMMIT_INVOCATION_RE.search(seg)
        options_span = m.group(1) if m else ''
        yield {
            'segment': seg,
            'options_span': options_span,
            'inline_env_redirect': inline_env_redirect,
            'flag_redirect': flag_redirect,
            'cwd_redirected': cwd_redirected,
        }


def _block_commit_redirect(segment, vector):
    _block(
        '\nBLOCKED: agent git commit - %s redirect detected.\n' % vector
        + 'A commit grant is bound to a specific repo/branch/HEAD resolved at '
        'issuance time; --git-dir / --work-tree / --namespace flags and '
        'GIT_DIR / GIT_WORK_TREE / GIT_COMMON_DIR env assignments repoint the '
        'commit at a DIFFERENT target the grant never authorized. Only a bare '
        '`git commit` or `git -C <dir> commit` (validated against the grant) '
        'is permitted.\n'
        + 'Command excerpt: %s\n' % segment[:200]
        + 'Spec: pretool-git-privilege-guard.py 2026-07-16 commit-grant '
        'redirect-vector closure (fail closed, mirrors "multiple -C -> block").\n'
    )


def _enforce_commit_grant_binding(grant, command):
    """Validate the grant's repo/branch/HEAD binding against EVERY commit
    invocation in `command`, failing CLOSED on any unresolvable redirect.

    Order of checks (each _block()s exit 2 on failure; a full pass returns):
      1. Ambient GIT_DIR/GIT_WORK_TREE/GIT_COMMON_DIR redirect -> block.
      2. For each enumerated commit invocation:
         a. inline-env or flag redirect (--git-dir/--work-tree/--namespace,
            GIT_DIR=/GIT_WORK_TREE=/GIT_COMMON_DIR=) -> block.
         b. resolve its -C target dir, then validate repo/branch/HEAD.
      3. If the classifier saw a commit but this enumerator resolved ZERO
         invocations, the commit's target is unlocatable -> block.
    """
    if _ambient_git_redirect_present():
        _block(
            '\nBLOCKED: agent git commit - ambient GIT_DIR/GIT_WORK_TREE/'
            'GIT_COMMON_DIR environment redirect present.\n'
            'The commit target repo cannot be verified against the grant '
            'binding while these are set. Unset them and re-run /commit.\n'
            'Spec: pretool-git-privilege-guard.py 2026-07-16 commit-grant '
            'redirect-vector closure (fail closed).\n'
        )
    invocations = list(_iter_commit_invocations(command))
    if not invocations:
        _block(
            '\nBLOCKED: agent git commit - a commit was detected but its '
            'effective target repository could not be resolved for grant '
            'validation.\n'
            'Command excerpt: %s\n' % command[:200]
            + 'Fail closed: an unlocatable commit target is rejected, not '
            'guessed.\n'
        )
    for inv in invocations:
        if inv['inline_env_redirect']:
            _block_commit_redirect(inv['segment'], 'inline-env GIT_DIR/GIT_WORK_TREE')
        if inv['flag_redirect']:
            _block_commit_redirect(inv['segment'], '--git-dir/--work-tree/--namespace flag')
        if inv.get('cwd_redirected'):
            _block_commit_redirect(inv['segment'], 'cd/pushd cwd-change before commit')
        target_dir = _extract_dash_c_from_span(inv['options_span'], inv['segment'])
        _validate_commit_grant_repo(grant, target_dir)
        _validate_commit_grant_branch(grant, target_dir)
        _validate_commit_grant_head(grant, target_dir)


def _commit_target_git_output(target_dir, *args):
    """Like _git_output, but scoped to `target_dir` via `-C` when non-empty.

    target_dir is the (possibly empty) result of _extract_commit_dash_c_dir.
    Empty target_dir falls back to the hook's own CWD, matching the
    no-override push-grant precedent.
    """
    prefix = ['-C', target_dir] if target_dir else []
    return _git_output(prefix + list(args))


def _validate_commit_grant_repo(grant, target_dir):
    """Grant.repo_root must match the toplevel of the commit's target repo.

    New binding (2026-07-15): closes the gap where a commit grant issued for
    one repository could authorize a `git commit` in a completely different
    repository, since only expires_at was previously checked. `target_dir` is
    the resolved `-C <dir>` for THIS commit invocation ('' = hook cwd), so a
    chained second commit is validated against its OWN target (2026-07-16).
    """
    grant_repo = grant.get('repo_root') or ''
    current_repo = _commit_target_git_output(target_dir, 'rev-parse', '--show-toplevel')
    if not grant_repo or not current_repo or grant_repo != current_repo:
        _block(
            '\nBLOCKED: agent git commit - repository mismatch.\n'
            'Grant repo_root  : %r\n' % grant_repo
            + 'Current repo_root: %r\n' % current_repo
            + 'A commit grant issued for one repository may not authorize a '
            'commit in another. Re-run /commit from within the target repository.\n'
            + 'Spec: pretool-git-privilege-guard.py 2026-07-15 repo/branch/HEAD '
            'parity fix (mirrors _validate_push_grant_branch/_head/_remote).\n'
        )


def _validate_commit_grant_branch(grant, target_dir):
    """AC-A7-equivalent for commit: grant.branch must match the current branch
    of the commit's target repo (mirrors _validate_push_grant_branch)."""
    grant_branch = grant.get('branch') or ''
    current_branch = _commit_target_git_output(target_dir, 'branch', '--show-current')
    if not grant_branch or grant_branch != current_branch:
        _block(
            '\nBLOCKED: agent git commit - branch mismatch.\n'
            'Grant branch  : %r\n' % grant_branch
            + 'Current branch: %r\n' % current_branch
            + 'Spec: pretool-git-privilege-guard.py 2026-07-15 repo/branch/HEAD '
            'parity fix (mirrors _validate_push_grant_branch).\n'
        )


def _validate_commit_grant_head(grant, target_dir):
    """AC-A6-equivalent for commit: grant.expected_head must match the
    current HEAD of the commit's target repo (mirrors _validate_push_grant_head).

    No tolerance for HEAD drift: a legitimate single /commit cycle never
    needs HEAD to move between grant issuance (Step 5) and grant consumption
    (Step 7) -- staging (`git add`) does not move HEAD, and the one documented
    multi-commit scenario (changelog-analyst's `nothing_to_commit_precommitted`
    recovery path, agents/changelog-analyst.md "Recovery step 3") reuses the
    SAME still-unconsumed grant only because no `git commit` fired earlier in
    that cycle -- HEAD is unchanged since Step 5 captured it. This is the same
    strict, no-tolerance behavior _validate_push_grant_head already applies.
    """
    grant_head = grant.get('expected_head') or ''
    current_head = _commit_target_git_output(target_dir, 'rev-parse', 'HEAD')
    if not grant_head or grant_head != current_head:
        _block(
            '\nBLOCKED: agent git commit - expected_head mismatch.\n'
            'Grant expected_head: %r\n' % grant_head
            + 'Current HEAD       : %r\n' % current_head
            + 'HEAD moved since the grant was issued; re-run /commit to '
            'obtain a fresh grant.\n'
            + 'Spec: pretool-git-privilege-guard.py 2026-07-15 repo/branch/HEAD '
            'parity fix (mirrors _validate_push_grant_head).\n'
        )


def _grant_matches_commit_target(grant, command):
    """Non-blocking predicate for grant SELECTION: True iff `grant`'s repo_root /
    branch / expected_head match EVERY commit invocation's target repo in
    `command`.

    Mirrors the per-invocation repo/branch/HEAD comparisons that
    _enforce_commit_grant_binding performs, but returns a bool instead of
    _block()ing, so _evaluate_commit can PREFER the grant bound to the commit's
    target repo when /commit has written several repo-bound grants. It does NOT
    re-implement the redirect fail-closed checks (those are grant-independent);
    the authoritative _enforce_commit_grant_binding still runs on the selected
    grant before the commit is allowed, so selection never widens acceptance --
    a grant missing any binding field, or mismatching on any invocation, is
    non-matching (fail closed). Note: a malformed invocation (multiple -C or an
    unresolved ${VAR}) still hard-blocks via _extract_dash_c_from_span, which is
    the correct fail-closed behavior regardless of grant.
    """
    grant_repo = grant.get('repo_root') or ''
    grant_branch = grant.get('branch') or ''
    grant_head = grant.get('expected_head') or ''
    if not grant_repo or not grant_branch or not grant_head:
        return False
    invocations = list(_iter_commit_invocations(command))
    if not invocations:
        return False
    for inv in invocations:
        target_dir = _extract_dash_c_from_span(inv['options_span'], inv['segment'])
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


def _push_has_forbidden_ref_mutation(invocation):
    for tok in invocation.args:
        if tok in ('--force', '-f', '--force-with-lease', '--delete', '-d', '--mirror'):
            return True
        if tok.startswith('--force-with-lease='):
            return True
        if tok.startswith('+') or tok.startswith(':'):
            return True
    return False


def _extract_commit_message(command):
    patterns = [
        r"-m\s*=?\s*'([^']*)'",
        r'-m\s*=?\s*"([^"]*)"',
        r'--message\s*=?\s*"([^"]*)"',
        r"--message\s*=?\s*'([^']*)'",
    ]
    for p in patterns:
        m = re.search(p, command)
        if m:
            return m.group(1)
    m = re.search(r'-m\s+(\S+)', command)
    if m:
        return m.group(1)
    # -F / --file: changelog-analyst always uses git commit -F <tmpfile>.
    # Read the subject line from the file so BLESSED_BRIDGE_RE can match.
    for p in [r'(?:^|\s)-F\s+(\S+)', r'--file[= ](\S+)']:
        m = re.search(p, command)
        if m:
            try:
                with open(m.group(1)) as fh:
                    return fh.readline().strip()
            except OSError:
                pass
    return ''


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


def _is_head_ref(ref):
    if not ref:
        return True
    return ref == 'HEAD'


def _end_time_passed(end_str):
    try:
        end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError):
        return True
    if end.tzinfo is None:
        return datetime.now() > end
    return datetime.now(timezone.utc) > end


def _state_file_is_live(sf):
    try:
        if sf.stat().st_size == 0:
            return False
        state = json.loads(sf.read_text())
    except (OSError, ValueError):
        return False
    if state.get('current_phase', '') in ('complete', 'completed'):
        return False
    if _end_time_passed(state.get('end_time', '')):
        return False
    return True


def _is_overnight_active():
    """True iff a live overnight-state-*.json exists in <project>/.claude/."""
    try:
        project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd())
        state_files = list((project_dir / '.claude').glob('overnight-state-*.json'))
        return any(_state_file_is_live(sf) for sf in state_files)
    except Exception:
        return False


def _block_default_deny_commit(msg):
    """AC-A13: default-deny block when commit env is unset."""
    _block(
        '\nBLOCKED: agent git commit - only the blessed /merge '
        'auto-bulk bridge or the /commit wrapper may commit from an '
        'agent context.\n'
        'Commit message excerpt: %r\n' % msg[:200]
        + 'Allowed pattern: ^auto-bulk: end-of-cycle commit for <branch>\n'
        'For closed dev tasks, use /commit <task-id>.\n'
        'For human-driven commits, exit the agent context and run '
        'git commit directly.\n'
        'Main agent may bypass with /allow <pattern> before the git commit command.\n'
        'Spec: spec-20260424-233926 section 5.2.4 (R4.3); '
        'ba-spec-20260425-redev2.md AC-A13.\n'
    )


def _has_bulk_commit_sentinel(data):
    """Return True if a valid non-expired bulk-commit sentinel exists.

    Written by /commit --bulk (scripts/write-bulk-commit-sentinel.py) before
    dispatching changelog-analyst. Multi-use: NOT consumed on validation so
    that multiple auto-bulk commits in a single session all succeed.
    Expires 30 minutes after creation (SENTINEL_TTL_MINUTES in the writer).

    SID fallback rationale (mirrors _find_grant_any for regular commits):
    changelog-analyst subagents carry a different session_id than the
    orchestrator that wrote the sentinel. The SID-specific glob is tried
    first (fast path); the global glob is the fallback so subagents can
    always find the sentinel written by the user's orchestrator session.
    Acceptable because: (a) sentinels require user-invoked /commit --bulk
    to be created at all; (b) 30-min TTL bounds exposure; (c) kind=
    'bulk-commit' check prevents other JSON files in /tmp from matching.
    """
    sid = _get_session_id(data)
    patterns = []
    if sid:
        patterns.append('/tmp/claude-bulk-commit-sentinel-%s-*.json' % sid)
    # Global fallback — see docstring above for rationale.
    patterns.append('/tmp/claude-bulk-commit-sentinel-*-*.json')
    seen = set()
    for pattern in patterns:
        try:
            candidates = glob.glob(pattern)
        except Exception:
            continue
        try:
            candidates.sort(key=lambda p: os.stat(p).st_mtime, reverse=True)
        except Exception:
            candidates.sort(reverse=True)
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            sentinel = _load_grant(path)
            if sentinel is None:
                continue
            if sentinel.get('kind') != 'bulk-commit':
                continue
            if sentinel.get('origin') != 'userpromptsubmit-hook':
                continue
            if not _end_time_passed(sentinel.get('expires_at', '')):
                return True
    return False


def _has_active_commit_grant():
    """Return True if any single-use commit grant is pending or in-flight (Fix E).

    Used to defer auto-bulk commits while a concurrent /commit cycle is active.
    Checks .json (written, not yet locked) and .lck (locked by PreToolUse;
    git commit subprocess is running) grant files.
    """
    for pattern in ('/tmp/claude-commit-grant-*.json',
                    '/tmp/claude-commit-grant-*.lck'):
        try:
            for path in glob.glob(pattern):
                grant = _load_grant(path)
                if grant is not None and not _end_time_passed(
                        grant.get('expires_at', '')):
                    return True
        except Exception:
            pass
    return False


def _evaluate_commit(command, data):
    msg = _extract_commit_message(command)
    if msg and BLESSED_BRIDGE_RE.search(msg):
        # Require a valid bulk-commit sentinel (written by /commit --bulk).
        # Without it, any agent that knows the prefix could bypass the guard.
        if _has_bulk_commit_sentinel(data):
            # Fix E: defer auto-bulk if a single-use /commit grant is active.
            # A concurrent /commit cycle is in progress; let it finish first.
            if _has_active_commit_grant():
                _block(
                    '\nDEFERRED: auto-bulk commit skipped — an active single-use '
                    'commit grant exists (/tmp/claude-commit-grant-*.json or *.lck).\n'
                    'A /commit cycle is in progress; auto-bulk will retry on the '
                    'next scheduled cycle.\n'
                )
            return
        _block(
            '\nBLOCKED: auto-bulk commit requires a bulk-commit sentinel.\n'
            'The `auto-bulk:` prefix is only authorized when changelog-analyst '
            'is dispatched by the user via /commit --bulk, which writes '
            '/tmp/claude-bulk-commit-sentinel-<sid>-<nonce>.json (30 min TTL).\n'
            'To run bulk commits: invoke /commit --bulk from your Claude session.\n'
        )
    if _check_git_allowlist(command, data):
        return
    # Grant-file mechanism. /commit (BULK=false) writes TWO repo-bound grants
    # (CONTROL_ROOT + nested ~/.claude); the guard MUST bind to the grant whose
    # repo_root/branch/expected_head match the commit's target repo, NOT merely
    # the most-recent grant. Selecting by recency blocks the root commit (which
    # fires first) on a repository mismatch against the newer nested-repo grant
    # (docs/dev/peer-review-grant-parity.md CRITICAL). Collect every candidate
    # (the any-SID glob is a superset of the SID-specific one, covering the
    # subagent SID-propagation fallback) and pick the one bound to this target.
    sid = _get_session_id(data)
    live = [
        (path, grant)
        for (path, grant) in _collect_commit_grant_candidates()
        if not _end_time_passed(grant.get('expires_at', ''))
    ]
    for grant_path, grant in live:
        if _grant_matches_commit_target(grant, command):
            # Authoritative binding re-check (redirect vectors + repo/branch/HEAD
            # across EVERY invocation): a matching grant passes; any redirect
            # still _block()s (exit 2). Single source of truth for the allow.
            _enforce_commit_grant_binding(grant, command)
            _lock_grant_for_posttool(grant_path, grant.get('sid') or sid or 'any')
            return
    # Fail closed (security preserved): no unexpired grant is bound to this
    # commit's target repo/branch/HEAD. If a live-but-mismatched grant exists,
    # surface the precise diagnostic via the authoritative binding check (it
    # _block()s, exit 2); otherwise default-deny. Selection narrowed the FALSE
    # block above WITHOUT widening acceptance -- a mismatched-only grant set is
    # still rejected here.
    if live:
        _enforce_commit_grant_binding(live[0][1], command)
    # AC-A13: default-deny all other agent git commit calls.
    _block_default_deny_commit(msg)


def _evaluate_merge(command, data):
    if os.environ.get('CLAUDE_MERGE_COMMAND_ACTIVE') == '1':
        return
    if _check_git_allowlist(command, data):
        return
    _block(
        '\nBLOCKED: agent git merge - only the /merge slash command '
        'may run git merge from an overnight context.\n'
        'Command excerpt: %s\n' % command[:200]
        + 'To bypass: set env var CLAUDE_MERGE_COMMAND_ACTIVE=1.\n'
        'Spec: spec-20260424-233926 section 5.2.4 (R4.3).\n'
    )


def _block_inline_env_push(command):
    """AC-A1: literal-substring inline-env injection block for push."""
    _block(
        '\nBLOCKED: agent git push - inline-env injection blocked.\n'
        'Detected literal substring `CLAUDE_PUSH_COMMAND_ACTIVE=` in '
        'the raw command text; agents are not permitted to set this '
        'env var inline.  Only the /push wrapper may set it via '
        'subprocess + os.environ.\n'
        'Command excerpt: %s\n' % command[:200]
        + 'Spec: ba-spec-20260425-redev2.md AC-A1.\n'
    )


def _block_default_deny_push(command):
    """AC-A5: default-deny block when push env is unset."""
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


def _validate_push_grant_branch(grant):
    """AC-A7: grant.branch must match current branch."""
    grant_branch = grant.get('branch') or ''
    current_branch = _git_output(['branch', '--show-current'])
    if not grant_branch or grant_branch != current_branch:
        _block(
            '\nBLOCKED: agent git push - branch mismatch.\n'
            'Grant branch  : %r\n' % grant_branch
            + 'Current branch: %r\n' % current_branch
            + 'Spec: ba-spec-20260425-redev2.md AC-A7.\n'
        )


def _validate_push_grant_head(grant):
    """AC-A6: grant.expected_head must match current HEAD sha."""
    grant_head = grant.get('expected_head') or ''
    current_head = _git_output(['rev-parse', 'HEAD'])
    if not grant_head or grant_head != current_head:
        _block(
            '\nBLOCKED: agent git push - expected_head mismatch.\n'
            'Grant expected_head: %r\n' % grant_head
            + 'Current HEAD       : %r\n' % current_head
            + 'Spec: ba-spec-20260425-redev2.md AC-A6.\n'
        )


def _validate_push_grant_remote(grant, push_invocation):
    """AC-A6 (remote binding): explicit cmd remote must match grant.remote."""
    grant_remote = grant.get('remote') or ''
    cmd_remote = _extract_push_remote(push_invocation)
    if cmd_remote and grant_remote and cmd_remote != grant_remote:
        _block(
            '\nBLOCKED: agent git push - remote mismatch.\n'
            'Grant remote  : %r\n' % grant_remote
            + 'Command remote: %r\n' % cmd_remote
            + 'Spec: ba-spec-20260425-redev2.md AC-A6.\n'
        )


def _block_missing_push_grant(sid):
    """AC-A4: env present but no on-disk grant for this SID."""
    pattern = '/tmp/claude-push-grant-%s-*.json' % sid
    _block(
        '\nBLOCKED: agent git push - CLAUDE_PUSH_COMMAND_ACTIVE=1 '
        'is set but no valid grant manifest matching %s.\n' % pattern
        + 'Single-use grants are unlinked on first valid consumption; '
        'a missing grant means it was already used or never written.\n'
        'Spec: ba-spec-20260425-redev2.md AC-A4; '
        'close-report-20260425-push-commit-debate.md §1-2.\n'
    )


def _evaluate_push(command, invocations, data):
    # FOLLOW-UP (2026-07-16, out of scope for the commit-grant redirect fix):
    # _validate_push_grant_branch/_head resolve the current branch/HEAD via
    # _git_output (hook cwd) with NO target-dir resolution, so the SAME class of
    # redirect hole closed for commit still exists here -- `git --git-dir=B/.git
    # --work-tree=B push ...`, `GIT_DIR=B/.git git push ...`, ambient GIT_DIR/
    # GIT_WORK_TREE, and a second chained `git -C B push` all bypass the
    # branch/HEAD binding. Deliberately NOT fixed in this task (commit-grant
    # scope only); tracked as a separate follow-up. Mirror _enforce_commit_grant_binding
    # here (ambient-env block + per-invocation redirect-flag/inline-env block +
    # -C target resolution) when addressed.
    sid = _get_session_id(data)
    # AC-A1: literal-substring inline-env injection (precedes env check).
    if _inline_env_present(command, 'CLAUDE_PUSH_COMMAND_ACTIVE'):
        _block_inline_env_push(command)
    # Find the push invocation for ref-mutation and remote checks.
    push_inv = next((inv for inv in invocations if inv.subcommand == 'push'), None)
    if push_inv and _push_has_forbidden_ref_mutation(push_inv):
        _block(
            '\nBLOCKED: agent git push - force/delete/ref-rewrite push is forbidden.\n'
            'Command excerpt: %s\n' % command[:200]
            + 'Safety policy allows normal /push branch publication only; '
            'automatic backup must use namespaced recovery refs.\n'
        )
    if _check_git_allowlist(command, data):
        return
    # AC-A5: default-deny when env unset.
    if os.environ.get('CLAUDE_PUSH_COMMAND_ACTIVE') != '1':
        _block_default_deny_push(command)
    # AC-A4: env present but no grant -> block.  Per close-report §1-2,
    # filename is `<sid>-<nonce>.json` (per-nonce); glob+match.
    grant_path, grant = _find_grant('push', sid)
    if grant is None:
        _block_missing_push_grant(sid)
    # AC-A7 + AC-A6: branch / head / remote binding.
    _validate_push_grant_branch(grant)
    _validate_push_grant_head(grant)
    _validate_push_grant_remote(grant, push_inv)
    # All validations passed.  Consume grant (single-use), then allow.
    _unlink_grant(grant_path)


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
        + 'Spec: 2026-05-09 commit/push loss-prevention policy.\n'
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
    """R6: Ban agent direct invocation of git plumbing that creates commit objects.

    Defense-in-depth: most are already indirectly blocked (they call git commit
    or git update-ref internally). These explicit bans close the gap for R6.
    Uses token-aware classification so string literals in python -c code are
    not matched (only the command token is classified, not arguments).
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


def _evaluate_command(command, data):
    # Classify once: build invocations list for all _looks_like_* and _evaluate_* calls.
    # iter_git_invocations uses token-aware parsing so path-qualified forms like
    # /usr/bin/git are detected alongside bare 'git' (closes RISK-3 bypass).
    invocations = list(iter_git_invocations(command))
    if not invocations:
        return
    # Fast path: if /allow grant matches for non-push commands, allow immediately.
    # Push is excluded: its allowlist check must come AFTER _push_has_forbidden_ref_mutation
    # (force-push must stay blocked even with a broad /allow grant).
    if not _looks_like_git_push(invocations) and _check_git_allowlist(command, data):
        return
    if _looks_like_git_forbidden_plumbing(invocations):
        _evaluate_forbidden_plumbing(command, data)
    if _looks_like_git_reset_hard(invocations):
        _evaluate_reset_hard(command, invocations, data)
    if _looks_like_git_direct_ref_mutation(invocations):
        _evaluate_direct_ref_mutation(command, data)
    if _looks_like_git_push(invocations):
        _evaluate_push(command, invocations, data)
    if _looks_like_git_merge(invocations):
        _evaluate_merge(command, data)
    if _looks_like_git_commit(invocations):
        _evaluate_commit(command, data)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        if data.get('tool_name', '') != 'Bash':
            sys.exit(0)
        # Always-on per spec 5.2.4 line 240-241; overnight gate removed
        # 2026-04-25 (Option alpha) after b5d447e proved interactive
        # sessions need this guard too.
        command = (data.get('tool_input', {}) or {}).get('command', '') or ''
        if not command:
            sys.exit(0)
        # /do bypass: main-agent-only; subagents never benefit from consent flag.
        if _has_do_consent(data):
            sys.exit(0)
        _evaluate_command(command, data)
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
    sys.exit(0)


if __name__ == '__main__':
    main()
