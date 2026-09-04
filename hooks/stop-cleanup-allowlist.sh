#!/usr/bin/env bash
# Stop Hook: Wipe any unconsumed /allow grant at turn end.
# Registered LAST in Stop hooks array so earlier hook failures do not block cleanup.
# Exits 0 always (cleanup is best-effort; never blocks agent stop).
# NOTE: NO `set -e` — missing flag file is expected and must not error out.
set -u

INPUT=$(cat)
SID=$(echo "$INPUT" | python3 -c \
  "import json,sys,os; d=json.load(sys.stdin); print(d.get('session_id','') or os.environ.get('CLAUDE_SESSION_ID','default'))" \
  2>/dev/null)
[ -z "$SID" ] && SID="default"

# DEFECT 1 fix (task-id 20260509-113838): hoist CONSENT_LOG above both
# cleanup branches. Previously CONSENT_LOG was bound only inside the /allow
# branch; under `set -u` the /do branch aborted with "unbound variable"
# whenever the /allow branch did not run, leaving /do consent flags on disk
# across turns. Hoisting binds the variable unconditionally.
CONSENT_LOG="$HOME/.claude/logs/bash-consent.log"
mkdir -p "$(dirname "$CONSENT_LOG")"

FLAG="/tmp/claude-bash-allowlist-${SID}.json"
if [ -f "$FLAG" ]; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) sid=$SID EXPIRED (turn ended without consumption)" >> "$CONSENT_LOG"
  rm -f "$FLAG"
fi

# Also clear /do consent flag - single-turn scope per 2026-04-28 boundary update.
# /do unlocks tool combinations the main agent normally avoids (context-saving);
# it must be re-granted explicitly each turn.
DO_FLAG="/tmp/claude-orchestrator-consent-${SID}.flag"
if [ -f "$DO_FLAG" ]; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) sid=$SID DO_CONSENT_EXPIRED (turn ended)" >> "$CONSENT_LOG"
  rm -f "$DO_FLAG"
fi
rm -f "/tmp/claude-tool-streak-${SID}.json"

# ── Sentinel-grant reap (task 20260519-211515 R2 / AC2) ──
# At session stop, sweep /tmp/claude-grants/*.json: unlink any sentinel
# whose expires_at has elapsed OR whose JSON is malformed. Bounded
# best-effort; never blocks agent stop. The reaper delegates to
# hooks/lib/allowlist.reap_expired_sentinel_grants().
HOOK_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
python3 -c "
import sys
sys.path.insert(0, '${HOOK_DIR}')
from lib.allowlist import reap_expired_sentinel_grants
print('[stop-cleanup] reaped', reap_expired_sentinel_grants(), '/tmp/claude-grants/* sentinel grants', file=sys.stderr)
" 2>>"$CONSENT_LOG" || true

# ── Bulk-commit sentinel reap ──
# /commit --bulk writes /tmp/claude-bulk-commit-sentinel-<sid>-<nonce>.json
# (30 min TTL, multi-use). Reap any that have expired at session end.
python3 -c "
import glob, json, os
from datetime import datetime, timezone
reaped = 0
for p in glob.glob('/tmp/claude-bulk-commit-sentinel-*.json'):
    try:
        d = json.loads(open(p).read())
        exp = d.get('expires_at', '')
        end = datetime.fromisoformat(exp.replace('Z', '+00:00'))
        if datetime.now(timezone.utc) > end:
            os.unlink(p)
            reaped += 1
    except Exception:
        pass
print('[stop-cleanup] reaped', reaped, 'bulk-commit sentinels', flush=True)
" 2>>"$CONSENT_LOG" || true

# ── Deferred commit-grant reap (Fix B; ownership-bound, audit R2-6) ──
# PreToolUse renames grants to .lck for PostToolUse finalization. Stop fires
# when THIS agent finishes responding — not when the machine's last session
# ends (the shipped binary builds the Stop payload as the common hook input
# {session_id, transcript_path, cwd} plus {hook_event_name:"Stop",
# stop_hook_active, last_assistant_message?}) — so an unscoped sweep deleted a
# CONCURRENT session's live pointer and locked grant mid-commit. The sweep now
# removes only artifacts this session OWNS, or artifacts older than the grant
# TTL (1800 s, mirroring _POINTER_STALE_SECONDS in posttool-allowlist-consume.py
# and GRANT_TTL_MINUTES in scripts/write-commit-grant.py) — old enough that no
# live commit can still be inside and the locked grant has expired anyway.
# Ownership evidence: a .lck grant payload records the minting session's `sid`
# (scripts/write-commit-grant.py); a pointer records no sid of its own, so it
# is owned exactly when the locked grant it records is owned — the recorded
# locked_path is READ for that proof, never used as a delete target (R2-5).
# Pointers are swept before .lck files so ownership can still be read.
# Undecidable ownership (unreadable, foreign, missing sid) leaves the artifact
# alone for its own session's Stop or the finalizer's mid-session stale reaper.
# Residual (accepted): a crashed session's unowned artifacts now persist up to
# 30 min instead of dying at the next unrelated agent's Stop; the finalizer's
# age-bounded reaper and the >7d /tmp cron sweep are the backstops.
# CLAUDE_COMMIT_GRANT_SWEEP_DIR is a test seam (defaults to /tmp) so the suite
# can exercise this sweep by execution without touching live /tmp artifacts.
CLAUDE_STOP_SWEEP_SID="$SID" python3 - <<'PYSWEEP' 2>>"$CONSENT_LOG" || true
import glob, json, os, stat, time
sid = os.environ.get('CLAUDE_STOP_SWEEP_SID', '')
root = os.environ.get('CLAUDE_COMMIT_GRANT_SWEEP_DIR') or '/tmp'
STALE = 1800
now = time.time()
UNPROBED = object()

def safe_load_json(path, limit=65536):
    # Audit F10: this sweep reads pointer/grant paths out of a world-writable
    # namespace, where a planted FIFO (open blocks for a writer) or a symlink
    # to a blocking device would stall the whole Stop hook. The script is
    # shell, but this sweep is embedded Python, so it applies the full
    # discipline directly — a pure-shell `test -f` would not do: -f follows
    # symlinks and proves nothing about what a later open() attaches to.
    # lstat + regular-non-symlink + size bound, open O_NOFOLLOW|O_NONBLOCK
    # where available, fstat the descriptor to close the lstat/open race,
    # bounded read. None for ANY refusal; the caller treats that as
    # undecidable and leaves the artifact alone. Never raises.
    #
    # Returns (parsed_or_None, identity_or_None, mtime, is_regular). The
    # identity is (st_dev, st_ino) of the inode THE DECISION IS ABOUT (audit
    # F8) — from the fstat of the descriptor the bytes came from when the file
    # was opened, from the lstat otherwise (the judgement is then about the
    # entry itself, not its content). Only a failed lstat gives None, which
    # forbids acting at all.
    try:
        st = os.lstat(path)
    except OSError:
        return None, None, 0.0, False
    ident = (st.st_dev, st.st_ino)
    reg = stat.S_ISREG(st.st_mode)
    if not reg or st.st_size > limit:
        return None, ident, st.st_mtime, reg
    flags = (os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
             | getattr(os, 'O_NONBLOCK', 0))
    try:
        fd = os.open(path, flags)
    except OSError:
        return None, ident, st.st_mtime, reg
    try:
        fst = os.fstat(fd)
        if not stat.S_ISREG(fst.st_mode):
            return None, ident, st.st_mtime, reg
        ident = (fst.st_dev, fst.st_ino)
        raw = b''
        while len(raw) <= limit:
            chunk = os.read(fd, limit + 1 - len(raw))
            if not chunk:
                break
            raw += chunk
        if len(raw) > limit:
            return None, ident, st.st_mtime, reg
    except OSError:
        return None, ident, st.st_mtime, reg
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        return json.loads(raw.decode('utf-8')), ident, st.st_mtime, reg
    except (UnicodeDecodeError, ValueError):
        return None, ident, st.st_mtime, reg

def unlink_verified(path, ident):
    # Audit F8: this sweep validated a NAME (read its ownership, judged its
    # age) and then unlinked by name. If the validated entry was removed in
    # that gap and a colliding live event re-created the same name — pointer
    # names come from a deliberately lossy fold of tool_use_id, and a grant can
    # be revoked and re-locked — the unlink destroyed the REPLACEMENT, which is
    # another session's live coordination state. Act only on the instance the
    # decision was made about: re-confirm the name still resolves to `ident`,
    # directory-relative where unlinkat/fstatat exist so no path component
    # above the final name can be swapped either.
    #
    # Residual: POSIX has no unlink-by-inode, so the fstatat and the unlinkat
    # are adjacent syscalls, not one atomic operation. The window that remains
    # is that pair; what it replaces spanned two file reads and a JSON parse.
    # Pure shell could not express this at all (`rm -f` re-resolves the name
    # with no identity check, and `test -f` follows symlinks) — which is why
    # this sweep is embedded Python rather than shell built-ins.
    if not ident or not os.path.basename(path):
        return False
    supported = getattr(os, 'supports_dir_fd', frozenset())
    dir_fd = None
    if os.unlink in supported and os.stat in supported:
        try:
            dir_fd = os.open(os.path.dirname(path) or '.',
                             os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        except OSError:
            dir_fd = None
    try:
        try:
            if dir_fd is None:
                cur = os.lstat(path)
            else:
                cur = os.stat(os.path.basename(path), dir_fd=dir_fd,
                              follow_symlinks=False)
            if (cur.st_dev, cur.st_ino) != ident:
                return False
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

def live_commit_repos():
    # Audit F9: age is not proof that an event has terminated. A `git` process
    # with `commit` in its argv, owned by this user (only this user's commits
    # can be inside these artifacts), is a commit that has NOT terminated; the
    # repository it runs in is off-limits to this sweep whatever the clock
    # says. None means the process table could not be read at all, which the
    # caller treats as undecidable. Never raises.
    try:
        pids = [n for n in os.listdir('/proc') if n.isdigit()]
    except OSError:
        return None
    repos = set()
    for pid in pids:
        try:
            with open('/proc/%s/cmdline' % pid, 'rb') as fp:
                argv = fp.read(65536).split(b'\0')
        except (OSError, ValueError):
            continue
        argv = [a.decode('utf-8', 'replace') for a in argv if a]
        if len(argv) < 2 or os.path.basename(argv[0]) != 'git':
            continue
        if 'commit' not in argv[1:]:
            continue
        try:
            cwd = os.readlink('/proc/%s/cwd' % pid)
        except OSError:
            continue
        target = cwd
        for i, tok in enumerate(argv[:-1]):
            if tok == '-C':
                target = os.path.join(cwd, argv[i + 1])
                break
        try:
            repos.add(os.path.realpath(target))
        except OSError:
            continue
    return repos

def repo_is_committing(repo_root, live):
    # Empty repo_root first: an unreadable or non-grant target has nothing for
    # a commit to be live ABOUT, so it still falls through to the age backstop
    # even where liveness cannot be probed.
    if not repo_root:
        return False
    if live is None:
        return True
    try:
        r = os.path.realpath(repo_root)
    except OSError:
        return False
    return any(c == r or c.startswith(r + os.sep) for c in live)

def real(path):
    try:
        return os.path.realpath(path)
    except OSError:
        return path

_live = [UNPROBED]

def live():
    if _live[0] is UNPROBED:
        _live[0] = live_commit_repos()
    return _live[0]

reaped = 0
# Pointers are swept FIRST so ownership can still be read through them, and so
# the set of pointers that SURVIVE this pass is known before any .lck is
# judged. That set is the audit-F9 fix for the Stop half: a locked grant
# carries its MINT mtime, not its lock time (write-commit-grant.py creates the
# file, it may sit for a while, and the rename-aside that locks it preserves
# mtime), so a grant minted 40 minutes ago and locked one second ago looked
# "over-age" and was deleted out from under a live commit. Its POINTER is the
# artifact whose timestamp really is the lock time — it is published by link(2)
# at lock time — so a surviving (un-owned, un-aged) pointer is the evidence
# that the lock is recent, and the grant it names is out of scope. Reading a
# different clock off the grant itself is not an alternative: st_ctime does
# track the rename, but any unrelated metadata operation bumps it too, and it
# cannot be set backwards by any caller, so it is neither trustworthy on its
# own nor attestable in a test.
protected = set()
for p in glob.glob(os.path.join(root, 'claude-commit-grant-active-*.json')):
    pointer, ident, mtime, reg = safe_load_json(p)
    locked = str(pointer.get('locked_path') or '') \
        if isinstance(pointer, dict) else ''
    grant, _gi, _gm, _gr = safe_load_json(locked) if locked \
        else (None, None, 0.0, False)
    gdata = grant if isinstance(grant, dict) else {}
    if repo_is_committing(str(gdata.get('repo_root') or ''), live()):
        # A commit is running in this grant's repository: the event may still
        # be in flight, so its pointer and grant are not ours to remove.
        protected.add(real(locked))
        continue
    owned = bool(sid) and bool(locked) and str(gdata.get('sid') or '') == sid
    if owned or (reg and now - mtime >= STALE):
        if unlink_verified(p, ident):
            reaped += 1
    elif locked:
        protected.add(real(locked))
for p in glob.glob(os.path.join(root, 'claude-commit-grant-*.json.lck')):
    grant, ident, mtime, reg = safe_load_json(p)
    gdata = grant if isinstance(grant, dict) else {}
    if real(p) in protected:
        continue
    if repo_is_committing(str(gdata.get('repo_root') or ''), live()):
        continue
    if (sid and str(gdata.get('sid') or '') == sid) \
            or (reg and now - mtime >= STALE):
        if unlink_verified(p, ident):
            reaped += 1
print('[stop-cleanup] reaped', reaped,
      'deferred commit-grant files (sid-owned or over-age)')
PYSWEEP

exit 0
