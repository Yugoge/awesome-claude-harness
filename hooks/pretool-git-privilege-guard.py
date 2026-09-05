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
  2026-08-31 (single-use closure, audit round 3 F4/F5/F6): three semantic holes
  in the commit grant's single-use guarantee.
    F4 - "expected_head neutralizes a left-in-place grant" was false. A grant
    that cannot be deferred to PostToolUse (no per-event key, rename failure,
    pointer-write failure) is left in place, and the claim that a successful
    commit moves HEAD past it does not hold: `git reset --soft <expected_head>`
    (an operation this guard permits) restores the matching tuple, and a
    deterministic `--amend` (fixed author/committer dates) reproduces the SAME
    sha so HEAD never moves at all. Both were reproduced against real repos.
    Spentness is therefore no longer INFERRED from repo state; the guard writes
    its own validation-time use record (`<grant>.json.use`) holding an
    APPEND-ONLY witness of the target repo. See `_repo_use_witness`.
    F5 - every commit invocation in one Bash call was validated against the same
    pre-execution HEAD and the grant locked once, so one grant authorized N
    commits in one call. Now refused; see `_enforce_commit_grant_binding`.
    F6 - the auto-bulk deferral honored ANY parseable unexpired grant file with
    no repo/branch/HEAD binding check, so a dead leftover or a foreign-repo
    grant blocked auto-bulk for its whole TTL. The deferral now applies the same
    binding + spent test the commit validation applies; see
    `_grant_can_authorize_here`.

Exit codes:
  0: Allow tool use
  2: Block tool use
"""

import glob
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.allowlist import read_grant_for_git_command, match_sentinel_grant_for_bash_command  # noqa: E402
from lib.git_command_classifier import (  # noqa: E402
    iter_git_invocations, GitInvocation, classify_git_command)
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


# ---------------------------------------------------------------------------
# Validation-time use record (audit round 3, F4)
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS. The deferred path (PreToolUse locks the grant aside, PostToolUse
# consumes on success / restores on failure) already gives a true single use: the
# .lck name is invisible to every grant search, so a second event cannot find it.
# The hole is the UNDEFERRABLE fallback — no per-event key, rename failure, or a
# pointer write that failed — where the grant is deliberately LEFT IN PLACE so a
# failed commit can still retry. The safety argument for leaving it was that
# expected_head neutralizes reuse because a successful commit moves HEAD. It does
# not:
#   - `git reset --soft <expected_head>` is permitted by this guard and puts the
#     repo/branch/HEAD tuple back exactly as the grant recorded it, re-arming the
#     leftover for another commit — and it can be repeated;
#   - a deterministic `git commit --amend` (fixed GIT_AUTHOR_DATE and
#     GIT_COMMITTER_DATE, unchanged tree/parent/message) reproduces the IDENTICAL
#     sha, so HEAD never moves and the grant never goes stale at all.
# Both were reproduced against real repositories before this fix.
#
# WHAT REPLACES IT. Spentness is no longer inferred from repo state, which the
# above shows is restorable. The guard records, at validation time, a witness of
# the target repo that only ever moves FORWARD: the HEAD sha plus the HEAD reflog
# entry COUNT. The reflog is append-only under every operation an agent can reach
# here — a commit appends `commit:`, a reset appends `reset:`, an amend appends
# `commit (amend):` — so the count rises even when the sha is put back or never
# moves. A later authorization is honored ONLY while the witness still equals the
# recorded one, i.e. only while nothing has been committed since. That is exactly
# the retry-after-FAILURE case the leave-in-place decision was made to protect
# (a failed commit creates no reflog entry), and it fails closed the moment a
# commit actually lands.
#
# RESIDUALS, stated rather than hidden:
#   - Two authorizations that both happen BEFORE either commit lands still both
#     pass: at validation time they are indistinguishable from one retry. The
#     window is now bounded by _MAX_GRANT_USE_ATTEMPTS instead of running to TTL.
#   - `git reflog delete HEAD@{0}` would restore the witness. It is not blocked
#     here because `git reflog expire` is a legitimate operation in this repo
#     (scripts/checkpoint-prune.sh), and narrowing that is a separate change.
#   - A record whose grant is consumed by the finalizer is orphaned in /tmp until
#     the >7d sweep; expired-grant records are reaped in _evaluate_commit.
_GRANT_USE_SUFFIX = '.use'

# How many authorizations one grant may receive while its witness is UNCHANGED
# (i.e. while no commit has landed). Retry after a failed commit needs more than
# one; nothing legitimate needs many. Bounds the pre-landing window above.
_MAX_GRANT_USE_ATTEMPTS = 3


def _use_record_path(grant_path):
    """Sidecar path for a grant's use record.

    Deliberately `<grant>.json.use`, which matches NONE of the existing globs:
    not the grant searches (`*-*.json`), not the in-flight check (`*.json` /
    `*.lck`), and not the Stop sweep's pointer/locked globs. The record must be
    inert to every reader that already scans this namespace.
    """
    return grant_path + _GRANT_USE_SUFFIX


def _repo_use_witness(repo_root):
    """Append-only witness of "has anything been committed in this repo".

    (HEAD sha, HEAD reflog entry count). The count is what carries the property:
    it rises on commit, on reset, and on amend, so neither a soft reset back to
    expected_head nor a same-sha amend can return it to a previously recorded
    value. Returns '' when either component is unreadable (unborn HEAD, reflogs
    disabled, or the repo is gone) — the caller treats '' as "cannot prove the
    grant is unspent" and fails closed.
    """
    head = _commit_target_git_output(repo_root, 'rev-parse', 'HEAD')
    entries = _commit_target_git_output(
        repo_root, 'rev-list', '--walk-reflogs', '--count', 'HEAD')
    # `entries == '0'` is the reflogs-disabled case, and it must be treated as
    # UNREADABLE, not as a reading of zero. `not '0'` is False in Python, so the
    # docstring's promise above ("returns '' when ... reflogs disabled") was not
    # kept: the witness came back as '<sha>:0', which is a CONSTANT — it cannot
    # rise on commit, reset or amend, so recorded == current would hold forever
    # and _grant_use_permitted() would re-authorize a spent grant up to the
    # attempt cap instead of failing closed. Verified 2026-09-03 against a bare
    # clone (core.logAllRefUpdates unset): `rev-list --walk-reflogs --count HEAD`
    # prints exactly `0`.
    if not head or not entries or entries == '0':
        return ''
    return '%s:%s' % (head, entries)


def _grant_use_permitted(grant, grant_path):
    """False iff a previous authorization of THIS grant already produced a commit.

    No record means the grant has never been authorized on the undeferrable path,
    so this is a first use and nothing is in question. With a record, the grant is
    honored only while the target repo's witness still equals the one captured at
    that first use, and only up to _MAX_GRANT_USE_ATTEMPTS. Every failure mode
    (unreadable witness, unparseable counter) resolves to False: an unprovable
    grant is refused, not guessed.
    """
    record = _load_grant(_use_record_path(grant_path))
    if record is None:
        return True
    recorded = record.get('witness') or ''
    current = _repo_use_witness(grant.get('repo_root') or '')
    if not recorded or not current or recorded != current:
        return False
    try:
        uses = int(record.get('uses'))
    except (TypeError, ValueError):
        return False
    return uses < _MAX_GRANT_USE_ATTEMPTS


def _record_undeferrable_grant_use(grant, grant_path):
    """Record an authorization that could NOT be deferred to PostToolUse.

    Only this path writes a record: on the deferred path the rename-aside is
    itself the single-use enforcement, and writing here would change a lifecycle
    that is pinned byte-for-byte by the finalizer tests.

    The witness is captured ONCE, at first use, and never refreshed — refreshing
    it on a later use would re-arm a grant whose commit had already landed, which
    is the whole defect. Best effort: a record that cannot be written leaves the
    pre-existing (weaker) behavior rather than blocking a commit already
    authorized.
    """
    path = _use_record_path(grant_path)
    prior = _load_grant(path) or {}
    try:
        uses = int(prior.get('uses'))
    except (TypeError, ValueError):
        uses = 0
    record = {
        'grant_path': grant_path,
        'repo_root': grant.get('repo_root') or '',
        'witness': prior.get('witness') or _repo_use_witness(grant.get('repo_root') or ''),
        'uses': uses + 1,
        'expires_at': grant.get('expires_at') or '',
    }
    tmp_path = '%s.wip.%d.%s' % (path, os.getpid(), os.urandom(4).hex())
    try:
        with open(tmp_path, 'w') as fp:
            json.dump(record, fp)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp_path, path)
    except (OSError, ValueError, TypeError):
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _grant_can_authorize_here(grant, grant_path, command):
    """True iff `grant` could authorize a commit for `command` right now.

    Applies the same two tests the commit validation applies — is the grant
    unspent (_grant_use_permitted), and is it bound to this target
    (_grant_matches_commit_target) — but in a NON-BLOCKING form, because the
    deferral is a scheduling decision and must never turn into an exit-2 on a
    command the pre-fix code would merely have deferred. The commit path keeps
    its own blocking copy of the same tests, which stays the single source of
    truth for the allow.

    Audit round 3, F6: before this, the deferral honored ANY parseable unexpired
    grant file, so a post-success leftover or a grant belonging to a completely
    different repository blocked auto-bulk here for its whole TTL.

    Fail closed on doubt: an empty command, or a command whose target cannot be
    resolved without blocking (multiple -C, unresolved ${VAR} — conditions that
    make _grant_matches_commit_target _block()), counts as "could authorize", so
    this can only ever NARROW deferral, never allow an auto-bulk commit that the
    pre-fix code would have deferred for a reason that still holds. Swallowing
    that SystemExit leaves the _block() message it already wrote on stderr while
    the hook goes on to exit 0 — cosmetic only (PreToolUse blocks on the exit
    code, not on stderr), and it only occurs for a malformed auto-bulk command.
    """
    if grant_path.endswith('.lck'):
        grant_path = grant_path[:-len('.lck')]
    if not _grant_use_permitted(grant, grant_path):
        return False
    if not command:
        return True
    try:
        return _grant_matches_commit_target(grant, command)
    except SystemExit:
        return True
    except Exception:
        return True


# Pointer-file path template for deferred commit-grant consumption (Fix B).
# PreToolUse locks the grant (rename → .lck) and writes this pointer so
# PostToolUse can locate it for finalization.
#
# The `{sid}` slot holds a PER-EVENT key (see _event_key), not a session id. The
# literal must stay character-identical to _COMMIT_GRANT_POINTER_TEMPLATE in
# hooks/posttool-allowlist-consume.py, and must keep matching the
# `/tmp/claude-commit-grant-active-*.json` glob that hooks/stop-cleanup-allowlist.sh
# sweeps at session end; both are pinned by
# hooks/tests/test_posttool_commit_grant_finalize.py.
_COMMIT_GRANT_ACTIVE_TEMPLATE = '/tmp/claude-commit-grant-active-{sid}.json'

# Characters kept verbatim from a tool_use_id when it becomes a filename. Everything
# else folds to '-', so a payload value can neither escape the /tmp pointer namespace
# (path separators, `..`) nor smuggle a glob metacharacter into the reader's scan.
_EVENT_KEY_UNSAFE_RE = re.compile(r'[^A-Za-z0-9_-]')


def _raw_tool_use_id(data):
    """The UNSANITIZED tool_use_id from the payload, or '' when unavailable.

    Recorded verbatim inside the pointer (audit R2-2): the filename derivation in
    _event_key is deliberately lossy (safe-alphabet fold + length cap), so two
    DISTINCT raw ids can share a derived key. The filename may stay lossy — it only
    has to be a safe /tmp name — but the ownership check inside the pointer must
    not be, or a colliding second event could finalize the first event's grant.
    """
    try:
        return str(data.get('tool_use_id') or '').strip()
    except Exception:
        return ''


def _event_key(data):
    """Per-event pointer key for this tool invocation, or '' when unavailable.

    `tool_use_id` is the one identifier the runtime hands to BOTH hook events of a
    single tool call. claude-code 2.1.239 builds the two payloads as
    `{...,hook_event_name:"PreToolUse",tool_name,tool_input,tool_use_id:t}` and
    `{...,hook_event_name:"PostToolUse",...,tool_use_id:t}`, and one tool-execution
    frame passes the SAME `t` into both. It is the `toolu_...` id of the assistant's
    tool_use block: unique per event, and assigned by the API rather than by the
    committing agent.

    A session id is NOT a substitute, and replacing it is the point. It proves only
    that two things share a session, so a later unrelated commit under the same
    session -- an auto-bulk commit, which mints no grant and no pointer at all --
    could claim an earlier event's pointer.

    The derivation is NOT injective (audit R2-2): the fold and the cap can map two
    distinct raw ids to one name. That is acceptable for the FILENAME only because
    the pointer also records the raw id (_raw_tool_use_id) and the finalizer
    compares raw values; a filename collision therefore degrades to an O_EXCL
    refusal on the write side (handled by restoring the grant), never to a
    cross-finalization.

    Returns '' when the payload carries no usable id; _lock_grant_for_posttool then
    declines to defer rather than write a pointer nobody can bind to this event.
    """
    raw = _raw_tool_use_id(data)
    if not raw:
        return ''
    safe = _EVENT_KEY_UNSAFE_RE.sub('-', raw)[:96]
    return 'tu-' + safe if safe.strip('-') else ''


def _restore_locked_grant(locked_path, grant_path):
    """Best-effort rename of a just-locked grant back to its original name.

    Used when the deferral pointer cannot be written AFTER the rename-aside
    already happened (audit R2-3b): a .lck referenced by no pointer is a
    stranded grant nothing will ever finalize. If the restore itself fails the
    .lck remains — and with no pointer naming it, the finalizer's stale reaper
    cannot reach it (that reaper discovers locked grants only through pointers).
    The residual is reaped by hooks/stop-cleanup-allowlist.sh, which globs .lck
    files directly (session-owned or over-age), and by the >7d /tmp sweep.
    """
    try:
        os.rename(locked_path, grant_path)
    except OSError:
        pass


def _lock_grant_for_posttool(grant_path, event_key, raw_event_id=''):
    """Lock a commit grant for deferred PostToolUse consumption (Fix B).

    Renames grant_path → grant_path + ".lck" to atomically remove it from
    _find_grant / _find_grant_any searches (prevents double-use), then writes a
    pointer named for THIS EVENT so posttool-allowlist-consume.py can finalize:
      - success terminal result → journal the commit event, unlink the .lck (consumed)
      - any other terminal      → rename .lck back to original (preserved for retry)
    The finalizer classifies that result from the payload SHAPE, not from an exit
    code — a successful Bash tool_response carries no exit_code, and a thrown call
    fires PostToolUseFailure, under which the finalizer is also registered (see
    _classify_terminal_result in posttool-allowlist-consume.py).

    The pointer records BOTH the derived event_key (its own name, so a squatter
    file merely occupying the name is refutable) and the RAW tool_use_id (audit
    R2-2): the filename derivation is lossy, so ownership is proven by the raw
    id, which the finalizer compares verbatim. Two distinct raw ids that share a
    derived name can therefore never finalize each other's grant.

    Returns True iff the grant was actually deferred (locked aside AND a pointer
    published for it). A False return is the caller's signal that this
    authorization will never reach PostToolUse, so the caller records a
    validation-time use instead (audit round 3 F4 — the leave-in-place cases
    below are exactly where the single-use guarantee used to evaporate).

    When the grant cannot be deferred it is LEFT IN PLACE, not destroyed
    (audit R2-3a — this reverses the earlier "spend it so it is never left
    reusable" call):
      - no per-event key, or rename failure: the commit this PreToolUse just
        authorized is about to run; destroying the grant here meant a FAILED
        commit could never retry and a successful one had nothing to journal.
        Reuse-after-success is stopped by the caller's use record, NOT by the
        expected_head binding: that binding was believed sufficient because a
        successful commit moves HEAD, but a permitted `git reset --soft
        <expected_head>` puts the tuple back and a deterministic `--amend`
        reproduces the same sha, so the leftover stayed live (audit round 3 F4).
        Residual: no journal entry for this event (inherent — no key means no
        pointer to finalize).
      - pointer write failure AFTER the rename (O_EXCL name collision, ENOSPC,
        permission, serialization error): the .lck would be referenced by
        nothing (audit R2-3b), so the rename is undone and the grant restored.
        Same use-record protection as above.

    The pointer is published ATOMICALLY (audit F7): the content is fully
    written and fsynced under a private temp name in the same directory, then
    linked into the final name. Writing into an O_EXCL-opened final name let a
    concurrently colliding event read PARTIAL JSON and reap the still-being-
    written pointer as corrupt, stranding the owner's .lck with no journal
    record. link(2) atomically materialises the complete inode at the final
    name and fails EEXIST when the name is taken — the same no-clobber O_EXCL
    provided, so a name is still only ever published by the event that owns it
    and no writer can overwrite another event's -- or another session's --
    token (a taken name is a duplicate PreToolUse for one tool_use_id, or a
    lossy-name collision between two distinct raw ids). rename(2) was rejected
    because it silently REPLACES an existing destination (no-clobber lost);
    O_EXCL-probe-then-rename was rejected for its probe-to-rename race, in
    which a concurrent publisher's just-linked pointer would be clobbered.
    The temp name matches neither the pointer glob nor the .lck glob, so no
    reaper or sweep can observe it; a crash-orphaned temp file is inert and
    falls to the >7d /tmp cron.
    """
    if not event_key:
        return False
    locked_path = grant_path + '.lck'
    try:
        os.rename(grant_path, locked_path)
    except OSError:
        return False
    pointer_path = _COMMIT_GRANT_ACTIVE_TEMPLATE.format(sid=event_key)
    tmp_path = '%s.wip.%d.%s' % (pointer_path, os.getpid(), os.urandom(4).hex())
    try:
        handle = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        _restore_locked_grant(locked_path, grant_path)
        return False
    deferred = False
    try:
        with os.fdopen(handle, 'w') as fp:
            json.dump({'locked_path': locked_path,
                       'original_path': grant_path,
                       'event_key': event_key,
                       'tool_use_id': raw_event_id}, fp)
            fp.flush()
            os.fsync(fp.fileno())
        os.link(tmp_path, pointer_path)
        deferred = True
    except (OSError, ValueError, TypeError):
        _restore_locked_grant(locked_path, grant_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return deferred


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
    if len(invocations) > 1:
        _block(
            '\nBLOCKED: agent git commit - %d commit invocations in ONE command; '
            'a commit grant authorizes exactly ONE commit.\n' % len(invocations)
            + 'Command excerpt: %s\n' % command[:200]
            + 'Every invocation in one call is validated against the SAME '
            'pre-execution HEAD and the grant is locked once, so a second commit '
            'here would ride the first one\'s authorization (audit round 3, F5). '
            'The authorized committer is already required to issue a minimal '
            '`git commit -F <msgfile>` with nothing chained on that command line '
            '(agents/changelog-analyst.md, command-line purity), so no legitimate '
            'caller reaches this. Issue each commit as its own call under its own '
            'grant.\n'
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


def _has_active_commit_grant(command=''):
    """Return True if a commit grant that could authorize a commit HERE is
    pending or in-flight (Fix E, narrowed by audit round 3 F6).

    Used to defer auto-bulk commits while a concurrent /commit cycle is active.
    Checks .json (written, not yet locked) and .lck (locked by PreToolUse;
    git commit subprocess is running) grant files.

    F6: this used to honor ANY parseable unexpired grant file, with none of the
    repo/branch/HEAD binding the commit validation itself applies. A grant that
    could not possibly authorize a commit here — a post-success leftover on the
    undeferrable path, or one belonging to an entirely different repository —
    therefore blocked auto-bulk in THIS repo for its whole TTL, and an
    artificially long expiry blocked it indefinitely. Observed in the wild: a
    live grant bound to /root deferred an auto-bulk commit in an unrelated
    checkout. `command` supplies the auto-bulk commit's own target so the same
    binding + spent test decides both; an empty command (or an unresolvable
    target) keeps the old defer-on-doubt behavior.
    """
    for pattern in ('/tmp/claude-commit-grant-*.json',
                    '/tmp/claude-commit-grant-*.lck'):
        try:
            for path in glob.glob(pattern):
                grant = _load_grant(path)
                if grant is None or _end_time_passed(grant.get('expires_at', '')):
                    continue
                if _grant_can_authorize_here(grant, path, command):
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
            if _has_active_commit_grant(command):
                _block(
                    '\nDEFERRED: auto-bulk commit skipped — an active single-use '
                    'commit grant exists (/tmp/claude-commit-grant-*.json or *.lck) '
                    'that is bound to THIS repo/branch/HEAD and still unspent.\n'
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
    live = []
    for path, grant in _collect_commit_grant_candidates():
        if _end_time_passed(grant.get('expires_at', '')):
            # An expired grant can never authorize again, so its use record has
            # nothing left to protect — reap it here rather than leaving /tmp
            # litter for the >7d sweep.
            _unlink_grant(_use_record_path(path))
            continue
        live.append((path, grant))
    for grant_path, grant in live:
        # A grant already spent on the undeferrable path is not a candidate at
        # all (audit round 3, F4). Checked BEFORE the target match so a spent
        # grant falls through to the next candidate / default-deny instead of
        # being selected and then blocked on a confusing binding diagnostic.
        if not _grant_use_permitted(grant, grant_path):
            continue
        if _grant_matches_commit_target(grant, command):
            # Authoritative binding re-check (redirect vectors + repo/branch/HEAD
            # across EVERY invocation): a matching grant passes; any redirect
            # still _block()s (exit 2). Single source of truth for the allow.
            _enforce_commit_grant_binding(grant, command)
            # Key the pointer on THIS EVENT, not on any session id: the grant's sid
            # and the finalizer's sid legitimately differ (see _find_grant_any), and
            # a session-named pointer is claimable by an unrelated later commit.
            # The RAW tool_use_id rides along so ownership survives the lossy
            # filename derivation (audit R2-2).
            if not _lock_grant_for_posttool(grant_path, _event_key(data),
                                            _raw_tool_use_id(data)):
                # Undeferrable: this authorization will never reach PostToolUse,
                # so the grant stays on disk with nothing to consume it. Record
                # the use now — that record, not the (restorable) expected_head
                # binding, is what refuses the second one (audit round 3, F4).
                _record_undeferrable_grant_use(grant, grant_path)
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


# ---------------------------------------------------------------------------
# Residual-refusal recovery route (2026-09-03)
#
# The residual refusal below is the ONE block in this guard that left an agent
# nothing: it fires before the invocation list, the allowlist cannot reach it
# (see the ordering note in _evaluate_command), and /do is main-agent-only. A
# stuck subagent is how guards get disabled wholesale, so the refusal needs a
# route -- WITHOUT becoming a laundering channel.
#
# Binding. The refusal exists BECAUSE the command did not parse, so the route
# cannot bind to operations the way a sentinel grant does: there is no op to
# name. The only thing left to bind to is the command's exact bytes. The
# override therefore carries sha256 of the FULL command text -- the full text,
# not the residual segment, because a segment binding would leave every other
# segment free to be appended after authorization. Full-text digest means the
# authorized command and the executed command are the same string by
# construction, with zero degrees of freedom.
#
# Reach. An override may only ANSWER a refusal this guard already emitted and
# journaled (_digest_was_refused). It cannot be minted pre-emptively for a
# command that was never refused, and it is single-use and short-lived.
#
# What this route does NOT claim. It does not claim an agent cannot forge the
# file. This repository has already MEASURED that it can -- see route_id
# "grant-self-minting" in hooks/tests/fixtures/overwrite_corpus.json: a grant
# under /tmp is an ordinary JSON file, creating a path that does not yet exist
# is never denied, so any agent with Bash can mint one. That finding is
# declared there rather than claimed closed, and this route inherits exactly
# that declared limitation and adds no new surface. What the route does supply
# is the property forgery cannot erase: honoring an override emits a
# non-suppressible stderr audit record naming who authorized it, why, and what
# was refused, so a forged authorization is visible in the transcript rather
# than silent.
# ---------------------------------------------------------------------------

_RESIDUAL_OVERRIDE_DIR = '/tmp/claude-git-residual-override'
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


def _audit_residual_override(path, ovr, command, kinds, segments, digest, data):
    """Emit the honor record. stderr first: the transcript is the durable copy."""
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
    _append_residual_record('audit.jsonl', {
        'event': 'residual_override_honored',
        'at': datetime.now(timezone.utc).isoformat(),
        'override_path': str(path),
        'authorized_by': ovr.get('authorized_by', ''),
        'reason': ovr.get('reason', ''),
        'origin': ovr.get('origin', ''),
        'issued_session_id': ovr.get('session_id', ''),
        'used_session_id': _get_session_id(data),
        'used_agent_id': str(data.get('agent_id') or ''),
        'command_sha256': digest,
        'command_excerpt': command[:200],
        'residual_kinds': kinds,
        'residual_segments': [s.strip()[:200] for s in segments],
        'created_at': ovr.get('created_at', ''),
        'expires_at': ovr.get('expires_at', ''),
    })


def _evaluate_command(command, data):
    # Classify once: build invocations list for all _looks_like_* and _evaluate_* calls.
    # iter_git_invocations uses token-aware parsing so path-qualified forms like
    # /usr/bin/git are detected alongside bare 'git' (closes RISK-3 bypass).
    invocations, residuals = classify_git_command(command)
    # An EMPTY invocation list is not proof that no git runs. Two distinct cases
    # hide behind it, and conflating them is what made this guard a no-op:
    #   * genuinely git-free (`echo hi`, `grep git .`) — must stay fast and
    #     permissive; this hook sees EVERY Bash call in the harness.
    #   * git-shaped but unparseable (`g\it push`, `$GIT push`, `$(which git)
    #     push`) — the command token cannot be resolved statically, so NO check
    #     below can be trusted to judge it. Refuse rather than fall through.
    # Checked BEFORE the invocation list and WITHOUT an allowlist bypass: a
    # grant is bound to a specific repo/branch/HEAD, and a command whose binary
    # is unknowable cannot be shown to be the command the grant authorized.
    #
    # That ordering is LOAD-BEARING, and measurably so: the two sides use
    # DIFFERENT splitters. lib/allowlist.py::_bash_subcommands (the grant
    # matcher) splits on && || ; | but NOT on `&`, while
    # lib/git_command_classifier.py::_segments (the residual detector) does
    # split on `&`. So `git status & $GIT push --force origin master` is ONE
    # grant-matchable subcommand whose head token is `git status` -- which a
    # structural sentinel grant satisfies -- while carrying an unresolvable
    # `$GIT push --force` the guard cannot judge. Run the allowlist first and
    # authority earned for `git status` is spent on a force-push through an
    # unknown binary. The recovery route below therefore sits INSIDE this
    # branch rather than reordering it, and binds to the command's bytes
    # instead of to operations the allowlist could match.
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
            _audit_residual_override(
                ovr_path, ovr, command, kinds, segments, digest, data)
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
