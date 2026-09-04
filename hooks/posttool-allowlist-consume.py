#!/usr/bin/env python3
"""
PostToolUse Hook: /allow grant consumption.

Atomically deletes the /allow grant file after a tool executes successfully.
PreToolUse hooks are now read-only grant checkers; this hook is the sole
consume point. Applies to any matching PostToolUse event (subagent or
main-agent); legacy grant cleanup is unconditional. Subagent write-grant
firewall remains in `hooks/userprompt-consent-allowlist.sh` Step 0.

PostToolUse fires only when all PreToolUse hooks exit 0 (tool was allowed).
If any PreToolUse hook exits 2, PostToolUse never fires — grant persists
for retry. This is correct UX: user can retry with the same grant.

PostToolUse additionally fires only for tool calls that RETURNED. A Bash
command whose non-benign exit code makes the tool throw fires the separate
PostToolUseFailure event (payload: tool_name/tool_input/tool_use_id/error/
is_interrupt — no tool_response), so this hook is registered under BOTH
events in settings.json (audit R2-1): the failure event is what restores a
deferred commit grant for retry and consumes sentinels on failed commands.

Sentinel-grant consume-on-any-terminal-result semantic (task 20260519-211515
R2 / AC2): in addition to consuming the legacy pattern-string grant, this
hook also unlinks any sentinel grant at /tmp/claude-grants/<task_id>.json
when ANY terminal result is observed for the wrapped tool. The four mandated
terminal-consumption cases are: success (exit 0), failure / non_zero exit
(1..255), malformed grant JSON, and comment_only attack (the magic phrase
appears in the command but no sentinel JSON exists). All four unlink the
sentinel grant unconditionally — this is the consume-on-any-terminal-result
contract documented verbatim below.

Exit 0 always (fail-open). Silently exits if no grant or no match.
"""

import glob as _glob
import json
import os
import re as _re
import stat as _stat
import sys
import time
from pathlib import Path

# Pattern to detect git commit commands (used by deferred-grant finalization).
_GIT_COMMIT_CMD_RE = _re.compile(r'\bgit\b.*\bcommit\b', _re.DOTALL)

# Pointer files written by pretool-git-privilege-guard.py::_lock_grant_for_posttool.
# Named constants rather than inline literals so a test can redirect the whole pointer
# namespace: it is a single shared /tmp namespace, and a test that scanned the real one
# could consume a live session's in-flight commit grant. The template must stay
# character-identical to the guard's _COMMIT_GRANT_ACTIVE_TEMPLATE.
_COMMIT_GRANT_POINTER_TEMPLATE = '/tmp/claude-commit-grant-active-{sid}.json'
_COMMIT_GRANT_POINTER_GLOB = '/tmp/claude-commit-grant-active-*.json'

# Mirror of pretool-git-privilege-guard.py::_EVENT_KEY_UNSAFE_RE. The two hooks are
# separate programs with no shared import, so the derivation is duplicated exactly as
# the pointer template above already is; test_posttool_commit_grant_finalize.py imports
# BOTH modules and pins them to the same output.
_EVENT_KEY_UNSAFE_RE = _re.compile(r'[^A-Za-z0-9_-]')

# A pointer older than the commit grant's own TTL (30 min --
# scripts/write-commit-grant.py::GRANT_TTL_MINUTES) can only belong to an event that
# never reached PostToolUse, and the grant it locks has necessarily expired by then.
_POINTER_STALE_SECONDS = 1800

# "The process table has not been consulted yet on this sweep" — distinct from the
# None that _live_commit_repos returns for "it could not be consulted at all", so
# one sweep probes at most once and an undecidable probe is not retried per entry.
_UNPROBED = object()


def _raw_tool_use_id(data) -> str:
    """The UNSANITIZED tool_use_id from the payload, or '' when unavailable.

    Mirror of pretool-git-privilege-guard.py::_raw_tool_use_id (audit R2-2): the
    derived key below is lossy (safe-alphabet fold + length cap), so ownership of
    a pointer is proven by comparing THIS value against the raw id the guard
    recorded inside the pointer — never by comparing derived names, which two
    distinct raw ids can share.
    """
    try:
        return str(data.get('tool_use_id') or '').strip()
    except Exception:
        return ''


def _event_key(data) -> str:
    """Per-event pointer key for this tool invocation, or '' when unavailable.

    Mirror of pretool-git-privilege-guard.py::_event_key — read that one for why
    `tool_use_id` is the correlator and a session id is not. In short: claude-code hands
    the SAME `tool_use_id` to the PreToolUse and PostToolUse payloads of one tool call,
    so it names the EVENT, whereas a session id names only the session and is therefore
    claimable by an unrelated later commit under that same session.
    """
    raw = _raw_tool_use_id(data)
    if not raw:
        return ''
    safe = _EVENT_KEY_UNSAFE_RE.sub('-', raw)[:96]
    return 'tu-' + safe if safe.strip('-') else ''


# Upper bound for any read out of the world-writable pointer/grant namespace.
# Real pointers and grants are a few hundred bytes; anything larger is not ours.
_UNTRUSTED_READ_LIMIT = 65536


def _read_untrusted_json_ident(path, limit=_UNTRUSTED_READ_LIMIT):
    """Parse JSON from an untrusted world-writable path, WITH the read inode's identity.

    Every pointer and locked-grant path this hook reads lives in /tmp, where any
    local user can plant a FIFO (open blocks until a writer appears) or a symlink
    to a blocking device — either stalls finalization before the caller's own
    pointer is processed (audit F10). Discipline: lstat first and require a
    regular non-symlink file no larger than `limit`; open with
    O_NOFOLLOW|O_NONBLOCK where available so a racing swap after the lstat
    cannot re-introduce the block; fstat the open descriptor to close the
    lstat/open race entirely; bound the read.

    Returns `(parsed_or_None, identity_or_None)`. The identity is
    `(st_dev, st_ino)` of THE INODE THE DECISION IS ABOUT (audit F8), and it is
    what `_unlink_verified` / `_rename_verified` re-confirm before acting, so a
    validated instance can only ever be acted on as itself:

      - when the file was opened, the identity comes from the FSTAT of the very
        descriptor the bytes were read from, so content and identity provably
        describe one inode even if the name was swapped between lstat and open;
      - when it could not be opened (non-regular, oversized, unreadable) the
        identity comes from the lstat, because the decision in that case is not
        about content at all — it is "the entry at this name is not a usable
        pointer", a judgement about exactly that entry;
      - only a failed lstat yields None, which forbids acting entirely.

    Parse result is None for ANY refusal — missing, non-regular, symlink,
    oversized, unreadable, undecodable, unparseable. Callers treat None exactly
    as they treated the corrupt case before. Never raises.
    """
    try:
        st = os.lstat(path)
    except OSError:
        return None, None
    ident = (st.st_dev, st.st_ino)
    if not _stat.S_ISREG(st.st_mode) or st.st_size > limit:
        return None, ident
    flags = (os.O_RDONLY
             | getattr(os, 'O_NOFOLLOW', 0)
             | getattr(os, 'O_NONBLOCK', 0))
    try:
        fd = os.open(path, flags)
    except OSError:
        return None, ident
    try:
        fst = os.fstat(fd)
        if not _stat.S_ISREG(fst.st_mode):
            return None, ident
        ident = (fst.st_dev, fst.st_ino)
        raw = b''
        while len(raw) <= limit:
            chunk = os.read(fd, limit + 1 - len(raw))
            if not chunk:
                break
            raw += chunk
        if len(raw) > limit:
            return None, ident
    except OSError:
        return None, ident
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        return json.loads(raw.decode('utf-8')), ident
    except (UnicodeDecodeError, ValueError):
        return None, ident


def _read_untrusted_json(path, limit=_UNTRUSTED_READ_LIMIT):
    """Identity-free form of _read_untrusted_json_ident, for reads that only
    need the content (the journal's grant payload). Never raises."""
    return _read_untrusted_json_ident(path, limit)[0]


def _dir_fd_capable():
    """True when this platform can express directory-relative stat+unlink+rename.

    `os.unlink(name, dir_fd=)` is `unlinkat(2)` and `os.stat(name, dir_fd=,
    follow_symlinks=False)` is `fstatat(2)`; using them pins the whole
    resolution to one already-opened directory, so no path COMPONENT above the
    final name can be swapped between the check and the act. Linux has both.
    """
    supported = getattr(os, 'supports_dir_fd', frozenset())
    return (os.unlink in supported and os.stat in supported
            and os.rename in supported)


def _open_dir(path):
    """Descriptor for the directory holding `path`, or None. Never raises."""
    try:
        return os.open(os.path.dirname(path) or '.',
                       os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    except OSError:
        return None


def _still_is(path, ident, dir_fd):
    """True iff `path` STILL names the inode `ident` identifies (lstat semantics)."""
    try:
        if dir_fd is None:
            st = os.lstat(path)
        else:
            st = os.stat(os.path.basename(path), dir_fd=dir_fd,
                         follow_symlinks=False)
    except OSError:
        return False
    return (st.st_dev, st.st_ino) == ident


def _unlink_verified(path, ident):
    """Unlink `path` ONLY while that name still resolves to the validated inode.

    THE DEFECT THIS CLOSES (audit F8). Every cleanup path here validated a
    pathname — read its JSON, judged its age, proved its ownership — and then
    unlinked BY NAME, with the whole journal write and a git subprocess sitting
    inside the gap. If the validated entry was removed in that gap and a
    colliding live event re-created the same name (pointer names are derived
    from `tool_use_id` by a deliberately LOSSY fold, so two distinct raw ids can
    legitimately land on one name), the unlink destroyed the REPLACEMENT: a live
    pointer, or a locked grant belonging to another event, which then has
    nothing to finalize and no journal attribution.

    The fix is that a decision made about a specific file INSTANCE can only ever
    act on that instance. `ident` comes from the inode that was actually
    validated (see _read_untrusted_json_ident); this re-confirms the name still
    resolves to it, directory-relative where the platform offers unlinkat, and
    unlinks in the same resolution.

    RESIDUAL, stated rather than hidden: POSIX has no unlink-by-inode, so the
    fstatat and the unlinkat cannot be made one atomic operation. A window
    remains between those two ADJACENT syscalls, with no filesystem work of our
    own inside it. That is a hard floor of the interface, and it replaces a
    window that previously spanned a JSON parse, a journal append and a `git`
    subprocess — microseconds to tens of milliseconds — with two consecutive
    syscalls.

    Returns True iff the unlink happened. False means the name no longer holds
    what was validated, so the artifact is LEFT ALONE: cleanup that cannot prove
    it is acting on its own decision does not act. Never raises.
    """
    if not ident:
        return False
    if not os.path.basename(path):
        return False
    dir_fd = _open_dir(path) if _dir_fd_capable() else None
    try:
        if not _still_is(path, ident, dir_fd):
            return False
        try:
            if dir_fd is None:
                os.unlink(path)
            else:
                os.unlink(os.path.basename(path), dir_fd=dir_fd)
        except OSError:
            return False
        return True
    finally:
        if dir_fd is not None:
            try:
                os.close(dir_fd)
            except OSError:
                pass


def _rename_verified(src, dst, ident):
    """Rename `src`→`dst` ONLY while `src` still resolves to the validated inode.

    The restore path has the same ABA exposure as the unlink one (audit F8): the
    old code tested `os.path.exists(locked_path)` and then renamed by name, so a
    .lck that was swapped in between — revoked and re-locked by a concurrent
    event on a colliding name — got MOVED out from under its owner. Same
    identity discipline, same residual (the fstatat/renameat pair is not atomic;
    the two syscalls are adjacent).

    Directory-relative only when src and dst share a directory, which is always
    true for the grant/.lck pair this hook restores; a cross-directory pointer
    (only reachable from a forged pointer) falls back to whole-path rename with
    the identity check still applied. Never raises.
    """
    if not ident:
        return False
    same_dir = os.path.dirname(src) == os.path.dirname(dst)
    dir_fd = _open_dir(src) if (_dir_fd_capable() and same_dir) else None
    try:
        if not _still_is(src, ident, dir_fd):
            return False
        try:
            if dir_fd is None:
                os.rename(src, dst)
            else:
                os.rename(os.path.basename(src), os.path.basename(dst),
                          src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        except OSError:
            return False
        return True
    finally:
        if dir_fd is not None:
            try:
                os.close(dir_fd)
            except OSError:
                pass


def _live_commit_repos():
    """Repositories a `git ... commit` is running in RIGHT NOW, or None.

    THE DEFECT THIS CLOSES (audit F9). Both reapers treated "older than
    _POINTER_STALE_SECONDS" as "the event has terminated". Age proves no such
    thing: a commit that runs past the bound is ordinary — repository hooks,
    commit signing, or a large tree all take arbitrary time — and reaping its
    pointer and locked grant mid-flight leaves the commit landing with nothing
    to finalize and no journal attribution. Worse, this reaper runs on EVERY
    terminal commit event, so an unrelated fast commit destroys a peer's slow
    one.

    What replaces "age implies dead" is positive evidence of LIVENESS, taken
    from state that already exists rather than from a new heartbeat: the running
    commit's own process. A `git` process with `commit` in its argv, running as
    THIS user (only this user's commits can be inside these 0600 /tmp
    artifacts), whose working directory — or `-C` target — is inside a repo, is
    a commit that has not terminated. Age remains, but only as a backstop for
    artifacts no live commit claims.

    Returns a set of resolved directory paths, or None when the process table
    cannot be enumerated at all. None means UNDECIDABLE, and the callers treat
    it the way this whole mechanism treats undecidable: leave the artifact
    alone. That is the constraint (cleanup that cannot decide liveness must not
    delete) and its cost is stated in the caller.

    Matching is by repository, not by event: any commit running in a repo
    protects every artifact bound to that repo. Over-protection is the fail-open
    direction. Never raises.
    """
    try:
        pids = [name for name in os.listdir('/proc') if name.isdigit()]
    except OSError:
        return None
    repos = set()
    for pid in pids:
        try:
            with open('/proc/%s/cmdline' % pid, 'rb') as fp:
                argv = fp.read(_UNTRUSTED_READ_LIMIT).split(b'\0')
        except (OSError, ValueError):
            continue
        argv = [part.decode('utf-8', 'replace') for part in argv if part]
        if len(argv) < 2 or os.path.basename(argv[0]) != 'git':
            continue
        if 'commit' not in argv[1:]:
            continue
        try:
            # A foreign-uid process's cwd is unreadable, and a foreign-uid
            # commit can never be the owner of one of these artifacts, so an
            # unreadable cwd is skipped rather than treated as undecidable.
            cwd = os.readlink('/proc/%s/cwd' % pid)
        except OSError:
            continue
        target = cwd
        for index, token in enumerate(argv[:-1]):
            if token == '-C':
                target = os.path.join(cwd, argv[index + 1])
                break
        try:
            repos.add(os.path.realpath(target))
        except OSError:
            continue
    return repos


def _repo_is_committing(repo_root: str, live_repos) -> bool:
    """True iff a live commit is running inside `repo_root` (or below it).

    An empty repo_root is checked FIRST and is never protected: there is nothing
    for a commit to be live ABOUT, so an unreadable or non-grant target still
    falls through to the age backstop even on a host where liveness cannot be
    probed at all. Otherwise `live_repos` of None (undecidable) → True, so an
    unprovable liveness state protects the artifact instead of condemning it.
    """
    if not repo_root:
        return False
    if live_repos is None:
        return True
    try:
        root = os.path.realpath(repo_root)
    except OSError:
        return False
    return any(cwd == root or cwd.startswith(root + os.sep)
               for cwd in live_repos)


def _locked_grant_repo(locked: str) -> str:
    """The repo a locked grant is bound to, or '' when it cannot be read."""
    grant = _read_untrusted_json(locked)
    if isinstance(grant, dict):
        return str(grant.get('repo_root') or '')
    return ''


def _stale_locked_grant_reapable(locked: str, now: float):
    """The identity to reap `locked` under, or None when it must be left alone.

    True-equivalent (an `(st_dev, st_ino)` tuple, which is always truthy) only
    when `locked` is something the pointer mechanism itself created AND no live
    commit can still be inside it (audit R2-5). Returning the IDENTITY rather
    than a bare bool is what lets the caller unlink the very inode this
    judgement was made about (audit F8) instead of whatever later occupies the
    name.

    The pointer this path was read from lives in world-writable /tmp and is
    UNTRUSTED input: a forged or corrupted stale pointer can record ANOTHER
    event's FRESH locked grant as its `locked_path`, so the recorded path proves
    nothing by itself — the old suffix-only check let an unrelated finalizer
    destroy a live commit's grant through the cleanup path. Ownership is
    therefore proven by two properties of the TARGET, not of the pointer:

      - its basename has the exact shape the guard's rename-aside produces
        (`claude-commit-grant-*.json.lck`, and never the pointer namespace's
        `claude-commit-grant-active-` prefix), so no bystander file is
        reachable; and
      - the file ITSELF is older than _POINTER_STALE_SECONDS, by lstat so a
        symlink cannot proxy an old mtime for a fresh target (non-regular
        files are refused outright). Grants predate their pointers —
        scripts/write-commit-grant.py mints the file before PreToolUse renames
        it aside, and rename(2) preserves mtime — so every legitimately stale
        pointer's grant is at least as old as the pointer, while a fresh grant
        named by a forged stale pointer fails the bound.

    Undecidable (missing, unstatable, non-regular) is None: cleanup that
    cannot prove ownership leaves the artifact alone (fail-open for cleanup =
    do not delete); the session-end sweep and the >7d /tmp cron are the
    backstops. Never raises.
    """
    base = os.path.basename(locked)
    if not (base.startswith('claude-commit-grant-')
            and base.endswith('.json.lck')
            and not base.startswith('claude-commit-grant-active-')):
        return None
    try:
        st = os.lstat(locked)
    except OSError:
        return None
    if not _stat.S_ISREG(st.st_mode):
        return None
    if now - st.st_mtime < _POINTER_STALE_SECONDS:
        return None
    return (st.st_dev, st.st_ino)


def _reap_stale_pointers(keep_path: str) -> None:
    """Drop pointers left by events that never reached PostToolUse.

    While the pointer namespace was scanned by wildcard, an abandoned pointer was
    cleared BY ACCIDENT by the next unrelated commit's finalizer. Binding a pointer to
    its event removes that accident, so the reap has to become deliberate. This is the
    mid-session reaper; hooks/stop-cleanup-allowlist.sh unlinks the session's OWN
    `claude-commit-grant-active-*.json` / `claude-commit-grant-*.json.lck` files (plus
    any over-age ones) at session end (audit R2-6 — the event-keyed names still match
    both of its globs), and the >7d /tmp sweep in scripts/install/tmp-cleanup-install.sh
    is the backstop.

    Age is a BACKSTOP here, never the whole case (audit F9). A commit that runs past
    _POINTER_STALE_SECONDS is ordinary — hooks, signing, a large tree — and this reaper
    fires on every terminal commit event, so an unrelated fast commit used to destroy a
    slow peer's live coordination state. A pointer whose grant names a repository with a
    commit RUNNING IN IT RIGHT NOW (_live_commit_repos) is therefore out of scope
    entirely, at any age; only artifacts no live commit claims fall through to the bound.
    The caller's own pointer is excluded by name regardless. The locked grant is UNLINKED
    rather than restored because at that age its `expires_at` has passed, so restoring it
    would re-materialise a file that authorizes nothing; that is what the session-end
    reaper already does with the same files.

    Residual: an artifact whose grant is UNREADABLE (junk, a forged pointer naming a
    non-grant, a FIFO) has no repo_root to be live about, so it is still reaped on age
    alone. That is correct — such a pointer names nothing any event could finalize — but
    it means liveness protection is only as good as the grant payload's readability. And
    an artifact genuinely abandoned WHILE a commit runs in the same repo survives until
    that commit exits, then ages out on a later event.

    Never raises: this runs after a commit has landed.
    """
    now = time.time()
    try:
        paths = _glob.glob(_COMMIT_GRANT_POINTER_GLOB)
    except Exception:
        return
    live_repos = _UNPROBED
    for path in paths:
        if path == keep_path:
            continue
        # lstat, not stat (audit F10): a symlink planted in the namespace must
        # be judged by its OWN age, or an old target could proxy staleness for
        # a fresh link — and stat on a hostile target is a read we never need.
        try:
            if now - os.lstat(path).st_mtime < _POINTER_STALE_SECONDS:
                continue
        except OSError:
            continue
        # Bounded non-blocking read (audit F10): a FIFO or symlink squatting on
        # a pointer name refuses to parse (None) and is reaped WITHOUT ever
        # being opened blockingly, so it cannot stall this sweep. The identity
        # rides along (audit F8) so the unlink below can only ever remove THIS
        # instance, never a live replacement that took the name in between.
        pointer, pointer_ident = _read_untrusted_json_ident(path)
        locked = ''
        if isinstance(pointer, dict):
            locked = str(pointer.get('locked_path') or '')
        # The recorded path is read out of a file this reaper does not own, so the
        # TARGET must independently prove it is an expired grant of this mechanism's
        # own making (audit R2-5): grant-shaped basename AND itself older than the
        # stale bound. A forged stale pointer naming a FRESH .lck fails the age
        # check and the fresh grant survives; only the pointer itself is reaped.
        if locked:
            if live_repos is _UNPROBED:
                live_repos = _live_commit_repos()  # probed at most once per sweep
            if _repo_is_committing(_locked_grant_repo(locked), live_repos):
                # A commit is running in this grant's repository (audit F9): the
                # event may still be in flight, so neither its grant nor the
                # pointer that finalizes it is ours to remove, at any age.
                continue
        locked_ident = _stale_locked_grant_reapable(locked, now)
        if locked_ident:
            _unlink_verified(locked, locked_ident)
        _unlink_verified(path, pointer_ident)


def _finalize_deferred_commit_grant(event_key: str, raw_event_id: str,
                                    session_id: str,
                                    terminal_result: str) -> None:
    """Consume or restore the commit grant locked for THIS tool event (Fix B).

    PreToolUse renamed the grant to <path>.lck and wrote a pointer named for the
    `tool_use_id` of the very invocation this PostToolUse call completes. This acts on
    THAT pointer and no other:
      - terminal_result='success'          → journal the commit event, then unlink
        the .lck (grant consumed)
      - terminal_result='unknown_terminal' → NOTHING (audit F2). That label is a
        NONTERMINAL background-launch receipt: the command is still running, so
        no outcome exists to act on. No consume, no restore, no pointer deletion,
        no stale sweep — everything survives intact. No later PostToolUse ever
        fires for a backgrounded tool_use_id (completion arrives as a
        conversation task-notification, not a hook event), so the preserved
        state is reaped by the session's own Stop sweep
        (hooks/stop-cleanup-allowlist.sh, ownership-bound), by this reaper on a
        later commit event once over-age (>= _POINTER_STALE_SECONDS), or by the
        >7d /tmp cron.
      - any other terminal result          → rename .lck back to original (retry OK)
    and removes the pointer on both terminal outcomes.

    AN EVENT WITH NO POINTER OF ITS OWN ACTS ON NOTHING. That is the fix. This used to
    resolve the pointer by SESSION id and, failing that, by an untargeted wildcard scan,
    with the journal write contained to the by-name case. But a session id proves only
    that two things share a session. An auto-bulk commit mints no grant and no pointer at
    all (_evaluate_commit returns before _lock_grant_for_posttool), and an event whose
    pointer write failed is in the same state — either could reach a stale or concurrent
    ordinary grant living under the same session id, journal a record mixing that grant's
    task_id/branch/parent_head with this event's session id, and consume or restore a
    grant belonging to someone else. When the two commits happened to share a parent that
    record also passed _parent_linkage_verified, making it SPENDABLE as a push-gate token
    rather than merely inert. Keying on the event removes the ambiguity at its source
    instead of detecting it after the fact: there is no fallback left to fall back to.

    The recorded `event_key` is checked against the name before anything is touched, so a
    pointer that merely occupies the expected filename is left strictly alone. The
    recorded RAW `tool_use_id` is then checked against `raw_event_id` (audit R2-2):
    the derived key is lossy (safe-alphabet fold + length cap), so two DISTINCT raw
    ids can share a derived name, and a derived-value comparison would let the second
    event finalize the first event's pointer — recreating the exact mixed-record /
    wrong-grant defect the event binding exists to close. Ownership is therefore
    proven raw-for-raw; a pointer recording a different raw id (or none, as pre-R2-2
    pointers do — those age out via the stale sweep) is not ours to act on.

    Fail-open: never raises, and never disturbs a commit that has already landed.
    """
    if terminal_result == 'unknown_terminal':
        # Nonterminal receipt (audit F2): finalize NOTHING, including no stale
        # sweep — "finalize nothing" means zero deletions of any kind on this
        # event. Returns before the pointer is even read.
        return
    pointer_path = (_COMMIT_GRANT_POINTER_TEMPLATE.format(sid=event_key)
                    if event_key else '')
    _reap_stale_pointers(pointer_path)
    if not pointer_path:
        return

    # The identity of the pointer inode this event's decisions are made ABOUT
    # (audit F8). Every unlink below is verified against it, so a pointer that
    # was removed and re-created by a colliding live event between this read and
    # the unlink is left strictly alone instead of being destroyed — the derived
    # pointer name is deliberately lossy, so a legitimate second event landing on
    # the same name is a real case, not a hypothetical.
    pointer, pointer_ident = _read_untrusted_json_ident(pointer_path)
    if not isinstance(pointer, dict) or not all(
            isinstance(pointer.get(field), str) and pointer.get(field)
            for field in ('locked_path', 'original_path', 'event_key')):
        # Absent is the ordinary case for every commit that never locked a grant.
        # Corrupt, non-regular, oversized (all read as None — audit F10) or
        # FIELD-INCOMPLETE ones are reaped here so they cannot accumulate under
        # a dead event key. A pointer that parses but lacks a path/claim field
        # the guard always writes carries the same trust as one that does not
        # parse (audit F7): torn by a non-atomic writer or foreign junk, and in
        # either reading never actionable — and only the POINTER is unlinked, so
        # a live .lck it might half-name survives for the ownership-bound sweeps.
        _unlink_verified(pointer_path, pointer_ident)
        return
    if pointer.get('event_key') != event_key:
        # Occupies our name but does not claim our event: not ours to act on.
        return
    if not raw_event_id \
            or str(pointer.get('tool_use_id') or '') != raw_event_id:
        # Shares our DERIVED name but was written for a different RAW id — a
        # sanitize- or cap-collision (audit R2-2). The lossy filename proves
        # nothing; only the verbatim raw id does. Not ours to act on.
        return

    locked_path = pointer.get('locked_path', '')
    original_path = pointer.get('original_path', '')

    if terminal_result == 'success':
        # Commit-event journal (hooks/lib/commit_journal.py). This is the ONLY moment in
        # the whole lifecycle at which a non-agent observer holds both a session id for
        # the committing session (harness-supplied when the payload carried one,
        # env-fallback otherwise — see append_commit_event's docstring) and a sha for what
        # that commit produced, so it is the only place a durable, HOOK-WRITTEN
        # attribution record can be created. The sha is LIVE HEAD read after the
        # committing shell call exited and the commit lock was released, so it is the
        # committing actor's own commit only when no peer landed one in that window;
        # `_parent_linkage_verified` refuses the rest at match time. Hook-written is the
        # whole claim: parts of the recorded content remain actor-influenced. Read the
        # grant BEFORE the unlink below destroys it. Wrapped and fail-open: a journal
        # defect must never disturb a commit that has already landed.
        #
        # No containment clause is needed here any more. Reaching this line already means
        # the pointer named THIS event and claimed it in its contents, so the grant being
        # read is the one the guard locked for this very invocation. The claim in
        # hooks/lib/commit_journal.py's header that bulk/auto-bulk commits are never
        # journaled holds a fortiori — they mint no pointer, and no other event's pointer
        # is reachable from here (that docstring is owned by another lane — do not edit it
        # here).
        #
        # The grant is read ONCE, and the identity of the inode those bytes came
        # from is what the unlink below is verified against (audit F8). The gap
        # between this read and that unlink contains the whole journal append —
        # a `git` subprocess — which is exactly the interval in which a
        # concurrent revocation plus a re-lock could put a DIFFERENT, live grant
        # at the same name for the pure-name unlink to destroy.
        locked_ident = None
        try:
            from lib.commit_journal import append_commit_event
            # Bounded non-blocking read (audit F10): locked_path came out of a
            # /tmp pointer, so a forged pointer naming a FIFO or symlink must
            # not stall the hook; an unreadable grant just skips the journal.
            grant, locked_ident = _read_untrusted_json_ident(locked_path)
            if isinstance(grant, dict):
                append_commit_event(grant, session_id)
        except Exception:
            pass
        _unlink_verified(locked_path, locked_ident)
    elif locked_path and original_path:
        # Same discipline on the restore path: capture the identity of the .lck
        # being restored, then rename only while the name still resolves to it.
        # The old `os.path.exists()` probe proved a name was occupied, never
        # that it was occupied by the instance this event locked.
        try:
            st = os.lstat(locked_path)
            locked_ident = ((st.st_dev, st.st_ino)
                            if _stat.S_ISREG(st.st_mode) else None)
        except OSError:
            locked_ident = None
        if locked_ident and not _rename_verified(locked_path, original_path,
                                                 locked_ident):
            # Restore failed — unlink to prevent stale .lck accumulation, but
            # only if the name still holds the instance we tried to restore.
            _unlink_verified(locked_path, locked_ident)

    _unlink_verified(pointer_path, pointer_ident)

sys.path.insert(0, str(Path(__file__).parent))
from lib.allowlist import (  # noqa: E402
    consume_grant_for_posttool,
    consume_sentinel_grant_on_terminal_result,
    match_sentinel_grant_for_write,
)


def _classify_terminal_result(data: dict) -> str:
    """Classify the posttool terminal-result for sentinel consumption.

    Implements consume-on-any-terminal-result: every TERMINAL outcome
    (success, failure, non_zero exit, malformed grant, comment_only attack)
    unlinks the sentinel. "unknown_terminal" is the one NONTERMINAL label
    (audit F2): a background-launch receipt means the command is still
    running, so nothing is consumed, restored, or deleted for it — the state
    survives for the terminal event or the age-bounded sweeps.

    Precedence (audit F3): nonterminal and interrupted signals DOMINATE any
    exit code. The shipped binary's explicit-background and timeout-
    background paths both return {stdout:"", stderr:"", code:0,
    interrupted:false, backgroundTaskId} — a receipt CARRIES a zero exit
    code — and an SDK-style payload can carry exit_code alongside either
    signal, so an exit_code branch evaluated first would classify a
    still-running or interrupted command as a finished one.

    REAL PAYLOAD SHAPES (audit R2-1, settled against the shipped harness
    binary's BashOutput schema and live-session transcript records): a
    successful Bash call's tool_response is {stdout, stderr, interrupted,
    ...} with NO exit_code and NO is_error field — the harness only fires
    PostToolUse for tool calls that returned; a non-benign non-zero exit
    makes the Bash tool THROW, which fires PostToolUseFailure instead,
    whose payload carries an `error` string and no tool_response at all.
    Success is therefore derived from the shape that is actually present,
    and the failure event is recognized by its hook_event_name. The
    is_error / exit_code branches are kept for SDK-style payloads.

    Returns one of: "success", "failure", "non_zero", "malformed",
                    "comment_only", "unknown_terminal".
    """
    if data.get("hook_event_name") == "PostToolUseFailure":
        # The tool threw (Bash: non-benign non-zero exit or pre-spawn
        # error). Terminal failure; there is no tool_response to inspect.
        return "failure"
    response = data.get("tool_response") or {}
    if isinstance(response, dict):
        if response.get("backgroundTaskId"):
            # Background-launch receipt: the command is still running, so no
            # terminal result exists yet for this event. Checked FIRST (audit
            # F3): the receipt carries code 0, and combined with `interrupted`
            # it is ambiguous — nonterminal wins because leaving state alone
            # is the recoverable reading (fail-open toward the commit).
            return "unknown_terminal"
        if response.get("interrupted") is True:
            # Interrupted dominates any exit code (audit F3): an interrupted
            # command has no trustworthy outcome regardless of the code an
            # SDK-style payload reports next to it.
            return "failure"
        if response.get("is_error"):
            return "failure"
        exit_code = response.get("exit_code")
        if isinstance(exit_code, int):
            if exit_code == 0:
                return "success"
            if 1 <= exit_code <= 255:
                return "non_zero"
        if isinstance(response.get("stdout"), str) \
                and isinstance(response.get("stderr"), str):
            # The real harness success shape (BashOutput). Reaching
            # PostToolUse with this shape IS the success signal.
            return "success"
    return "unknown_terminal"


def main() -> None:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        # Malformed posttool input — still reap the sentinel for the
        # comment_only / malformed terminal case. Mirror writer priority:
        # CLAUDE_TASK_ID > CLAUDE_SESSION_ID (session_id fallback).
        _env_tid = os.environ.get("CLAUDE_TASK_ID", "")
        _env_sid = os.environ.get("CLAUDE_SESSION_ID", "default")
        task_id = _env_tid if _env_tid else _env_sid
        if task_id:
            consume_sentinel_grant_on_terminal_result(task_id, "malformed")
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    session_id = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "default")

    if tool_name == "Bash":
        command = (data.get("tool_input") or {}).get("command", "")
    else:
        command = ""

    # Legacy grant: always consume on any terminal result, regardless of context.
    # Both main-agent and subagent Bash executions unlink the legacy grant so
    # the main agent cannot reuse a stale grant after a subagent consumed the sentinel.
    consume_grant_for_posttool(session_id, tool_name, command)

    # Sentinel-grant consume-on-any-terminal-result (task 20260519-211515 R2 / AC2).
    #
    # CF-2 scoping (codex iter-1 BLOCKER): the sentinel grants bash-command
    # authorization. PostToolUse fires for EVERY tool (matcher "*"), so an
    # unrelated Read/Grep/Glob call after `/allow` could otherwise unlink the
    # sentinel before the intended Bash call. We restrict sentinel consumption
    # to Bash terminal results AND only when the sentinel actually matched
    # this command structurally (`match_sentinel_grant_for_bash_command`).
    # The four mandated terminal cases (success/failure/non_zero/malformed)
    # are all hit only when Bash itself fires; non-Bash tool events skip the
    # sentinel-consume path entirely.
    env_task_id = os.environ.get("CLAUDE_TASK_ID", "")
    task_id = env_task_id if env_task_id else session_id
    if task_id and tool_name == "Bash":
        try:
            from lib.allowlist import (  # noqa: E402
                match_sentinel_grant_for_bash_command,
                load_sentinel_grant_for_task,
                _enumerate_sentinel_grant_files,
            )
        except Exception:
            match_sentinel_grant_for_bash_command = None
            load_sentinel_grant_for_task = None
            _enumerate_sentinel_grant_files = None
        terminal_result = _classify_terminal_result(data)
        should_consume = False
        if match_sentinel_grant_for_bash_command is not None:
            try:
                m = match_sentinel_grant_for_bash_command(task_id, command)
                if m is not None:
                    should_consume = True
            except Exception:
                should_consume = True
                terminal_result = "malformed"
        # Malformed-grant terminal case: a sentinel file exists for this task
        # but load_sentinel_grant_for_task returned None (parse failure or
        # expired). The AC2 contract requires unlink on malformed.
        if (not should_consume) and load_sentinel_grant_for_task is not None \
                and _enumerate_sentinel_grant_files is not None:
            try:
                if _enumerate_sentinel_grant_files(task_id) and load_sentinel_grant_for_task(task_id) is None:
                    should_consume = True
                    terminal_result = "malformed"
            except Exception:
                pass
        # Nonterminal background receipt (audit F2): the command is still
        # running, so a structurally matched sentinel must SURVIVE for the
        # real terminal event — consume nothing, unlink nothing. The two
        # malformed overrides above are unaffected: "malformed" is itself a
        # terminal-consumption case and has already replaced the label.
        if terminal_result == "unknown_terminal":
            should_consume = False
        if should_consume:
            consume_sentinel_grant_on_terminal_result(task_id, terminal_result)
        # Sentinel consumed — also unlink legacy grant unconditionally.
        # Closes the whitespace-normalization divergence: sentinel uses tokenized
        # matching (handles "git   push") but legacy uses literal substring match.
        if should_consume:
            legacy_path = Path(f"/tmp/claude-bash-allowlist-{session_id}.json")
            try:
                legacy_path.unlink()
            except (FileNotFoundError, OSError):
                pass
            # Cross-SID: orchestrator SID may differ from subagent SID.
            # Unlink orchestrator's legacy grant too if the SIDs diverge.
            orch_sid = os.environ.get("CLAUDE_SESSION_ID", "")
            if orch_sid and orch_sid != session_id:
                orch_legacy = Path(f"/tmp/claude-bash-allowlist-{orch_sid}.json")
                try:
                    orch_legacy.unlink()
                except (FileNotFoundError, OSError):
                    pass
    # Deferred commit grant finalization (Fix B): PostToolUse is the sole
    # consume point for commit grants.  PreToolUse locked the grant (.lck);
    # here we either delete it (success) or restore it (failure, retry OK).
    if tool_name == "Bash" and command and _GIT_COMMIT_CMD_RE.search(command):
        _finalize_deferred_commit_grant(_event_key(data), _raw_tool_use_id(data),
                                        session_id, _classify_terminal_result(data))

    elif tool_name == "Write":
        # Sentinel-grant consume for Write-overwrite grants (task 20260522-080646-B).
        # Uses tool_input.file_path (not command — Write has no command field).
        #
        # 3-candidate task_id lookup (iter3 B1 fix): mirrors pretool write-guard.sh
        # candidate list so we find the sentinel regardless of whether userprompt-
        # consent-allowlist.sh keyed it by CLAUDE_TASK_ID or by session_id.
        # Candidate order must match writer: [CLAUDE_TASK_ID or session_id, data.task_id, session_id].
        env_task_id = os.environ.get("CLAUDE_TASK_ID", "")
        writer_primary = env_task_id if env_task_id else session_id
        data_task_id = data.get("task_id") or ""
        seen: set = set()
        candidates = []
        for c in [writer_primary, data_task_id, session_id]:
            if c and c not in seen:
                seen.add(c)
                candidates.append(c)
        file_path = (data.get("tool_input") or {}).get("file_path", "")
        terminal_result = _classify_terminal_result(data)
        should_consume = False
        consumed_task_id = ""
        for candidate in candidates:
            try:
                m = match_sentinel_grant_for_write(candidate, session_id, file_path)
                if m is not None:
                    should_consume = True
                    consumed_task_id = candidate
                    break
            except Exception:
                should_consume = True
                consumed_task_id = candidate
                terminal_result = "malformed"
                break
        # Malformed-grant fallback: sentinel exists for some candidate but
        # load/match failed (expired, parse error).
        if not should_consume:
            try:
                from lib.allowlist import (  # noqa: E402
                    load_sentinel_grant_for_task,
                    _enumerate_sentinel_grant_files,
                )
                for candidate in candidates:
                    if _enumerate_sentinel_grant_files(candidate) and load_sentinel_grant_for_task(candidate) is None:
                        should_consume = True
                        consumed_task_id = candidate
                        terminal_result = "malformed"
                        break
            except Exception:
                pass
        if should_consume:
            consume_sentinel_grant_on_terminal_result(consumed_task_id or session_id, terminal_result)
    sys.exit(0)


if __name__ == "__main__":
    main()
