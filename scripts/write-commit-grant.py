#!/usr/bin/env python3
"""Write a single-use /commit privilege-guard grant manifest.

Invoked from `commands/commit.md` Step 5 (non-bulk mode) to author a
short-lived authorization token consumed by
`/root/.claude/hooks/pretool-git-privilege-guard.py` (see
`_end_time_passed` at lines 377-384; ISO-8601 contract preserved).

The script writes a JSON file at
`<output-dir>/claude-commit-grant-<sid>-<nonce>.json` containing:
  - task_id       : --task-id argument (REQUIRED)
  - sid           : --sid argument OR CLAUDE_SESSION_ID env var
  - nonce         : 16-char hex (secrets.token_hex(8))
  - repo_root     : `git rev-parse --show-toplevel` resolved at --repo-root
                     (or CWD when --repo-root is omitted) -- binds the grant
                     to ONE repository, mirroring hooks/push.sh's "branch" /
                     "expected_head" binding fields for push grants (2026-07-15
                     repo/branch/HEAD parity fix).
  - branch        : `git branch --show-current` in repo_root at write time
  - expected_head : `git rev-parse HEAD` in repo_root at write time
  - created_at    : ISO-8601 timezone-aware UTC at write time
  - expires_at    : created_at + GRANT_TTL_MINUTES (named module constant)

Both timestamps are produced from `datetime.now(timezone.utc)` and are
fromisoformat-parseable by the privilege guard. Epoch ints/floats and
naive datetimes are silently rejected by the guard.

The privilege guard's `_validate_commit_grant_repo` / `_validate_commit_grant_branch`
/ `_validate_commit_grant_head` reject the commit outright if repo_root,
branch, or expected_head no longer match the live git state at commit time
(pretool-git-privilege-guard.py) -- so a grant lacking these fields (e.g.
written by a stale copy of this script) is treated as invalid, never as
"binding not enforced".

Exit codes:
  0  success (grant written)
  2  CLAUDE_SESSION_ID unresolved (neither --sid nor env var supplied), or
     repo_root/branch/expected_head could not be resolved via git
  argparse-default 2 when --task-id is omitted (handled by argparse)
"""

import argparse
import json
import os
import secrets
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Grant validity window. The privilege guard expires the grant at
# created_at + GRANT_TTL_MINUTES; do not duplicate this literal at the
# operational call site (use the constant symbolically).
GRANT_TTL_MINUTES = 30

# Deferred-consume pointer namespace written by pretool-git-privilege-guard.py::
# _lock_grant_for_posttool. Since the event-keyed rename (pointers are named for
# the tool_use_id of the commit's own tool event, audit R2-4), revocation CANNOT
# reconstruct a pointer's name — this script never sees a tool_use_id. It instead
# enumerates the namespace and matches each pointer's RECORDED grant paths
# (original_path / locked_path) against the grant being revoked. Must stay
# glob-compatible with the guard's _COMMIT_GRANT_ACTIVE_TEMPLATE.
COMMIT_GRANT_POINTER_GLOB = "/tmp/claude-commit-grant-active-*.json"


# Upper bound for any read out of the world-writable grant/pointer namespace.
# Real grants and pointers are a few hundred bytes; anything larger is not ours.
_UNTRUSTED_READ_LIMIT = 65536


def _read_identified(path: str, limit: int = _UNTRUSTED_READ_LIMIT):
    """`(parsed_json_or_None, (st_dev, st_ino)_or_None)` for an untrusted path.

    Revocation reads grant files and deferred-consume pointers out of /tmp,
    where any local user can plant a FIFO (open blocks until a writer appears)
    or a symlink aimed elsewhere. A plain `open()` would follow the symlink and
    then report the TARGET's identity while the unlink acted on the LINK — so
    the safe open is not incidental hardening here, it is what makes the
    identity mean anything at all.

    The identity is of the inode the decision is about (audit F8): the fstat of
    the descriptor the bytes came from when the file was opened, the lstat
    otherwise. Only a failed lstat returns None, which forbids acting. Never
    raises; None parse result is the caller's "could not process" case,
    reported exactly as the previous JSONDecodeError/OSError path was.
    """
    try:
        st = os.lstat(path)
    except OSError:
        return None, None
    ident = (st.st_dev, st.st_ino)
    if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
        return None, ident
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_NONBLOCK", 0))
    try:
        fd = os.open(path, flags)
    except OSError:
        return None, ident
    try:
        fst = os.fstat(fd)
        if not stat.S_ISREG(fst.st_mode):
            return None, ident
        ident = (fst.st_dev, fst.st_ino)
        raw = b""
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
        return json.loads(raw.decode("utf-8")), ident
    except (UnicodeDecodeError, ValueError):
        return None, ident


def _unlink_identified(path: str, ident) -> bool:
    """Unlink `path` only while that name still resolves to `ident`.

    THE DEFECT THIS CLOSES (audit F8). Revocation loaded a file, decided from
    its CONTENTS that it was revocable, and then unlinked BY NAME. Between the
    two, a concurrent PreToolUse can rename a grant aside and publish a pointer
    for it, or the finalizer can restore one — the same names are reused across
    the lock/restore cycle by construction — so the pure-name unlink could
    delete a grant or pointer that had become LIVE for a different event since
    the decision was made, leaving that commit with nothing to finalize and no
    journal attribution. Identity turns "the file called X" into "the file I
    read", and directory-relative unlinkat keeps the resolution pinned to the
    directory that was inspected.

    Residual: POSIX offers no unlink-by-inode, so the fstatat and the unlinkat
    are adjacent syscalls rather than one atomic operation; that pair is the
    irreducible window, and it replaces one that spanned a full open/read/parse.

    Returns True iff the unlink happened. False leaves the artifact alone —
    cleanup that cannot prove it is acting on its own decision does not act.
    """
    if not ident or not os.path.basename(path):
        return False
    supported = getattr(os, "supports_dir_fd", frozenset())
    dir_fd = None
    if os.unlink in supported and os.stat in supported:
        try:
            dir_fd = os.open(os.path.dirname(path) or ".",
                             os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            dir_fd = None
    try:
        try:
            if dir_fd is None:
                current = os.lstat(path)
            else:
                current = os.stat(os.path.basename(path), dir_fd=dir_fd,
                                  follow_symlinks=False)
            if (current.st_dev, current.st_ino) != ident:
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


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="write-commit-grant.py",
        description="Write a single-use /commit privilege-guard grant manifest.",
    )
    parser.add_argument(
        "--task-id",
        required=True,
        help="Task-id from the /commit invocation (e.g. 20260519-160856).",
    )
    parser.add_argument(
        "--revoke-only",
        action="store_true",
        help=(
            "Revoke (delete) any existing grant for --task-id + sid and EXIT "
            "WITHOUT writing a fresh grant. Used by /commit Step 6c stop paths "
            "(QA REJECT / dry-run / unparseable) so a blocked gate leaves no live "
            "commit authorization lingering."
        ),
    )
    parser.add_argument(
        "--sid",
        default=None,
        help="Claude session id. Defaults to the CLAUDE_SESSION_ID env var.",
    )
    parser.add_argument(
        "--output-dir",
        default="/tmp",
        help="Directory to write the grant JSON into. Default: /tmp.",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help=(
            "Directory to resolve the repo/branch/HEAD binding fields from "
            "(passed to git as `-C <dir>`). Defaults to the invoking "
            "process's CWD when omitted. Use this to write a grant for a "
            "DIFFERENT repository than CWD (e.g. the nested ~/.claude repo) "
            "without cd'ing there first -- matches changelog-analyst's own "
            "`git -C <dir> commit ...` invocation form."
        ),
    )
    parser.add_argument(
        "--revoke-existing-for-task",
        metavar="TASK_ID_TO_REVOKE",
        default=None,
        help=(
            "Before writing a new grant, revoke (delete) any existing stale grants "
            "in --output-dir whose task_id matches TASK_ID_TO_REVOKE. "
            "Use the same value as --task-id for the normal retry flow. "
            "Revocation is best-effort: individual delete failures are logged but "
            "do not abort grant creation."
        ),
    )
    return parser.parse_args(argv)


def _revoke_pointers_for_grant(candidate: str) -> None:
    """Delete any deferred-consume pointer that references the revoked grant.

    Pointers are event-keyed (named for a tool_use_id this script never sees),
    so the old session-named unlink could never match one (audit R2-4): revoking
    a locked grant left its pointer behind, and a later flow on the same tool
    event then hit the pointer's O_EXCL no-clobber. Discovery is therefore by
    CONTENT: enumerate the namespace and match each pointer's recorded
    original_path / locked_path against the grant file being revoked (either its
    .json or its .json.lck form). Best-effort: unreadable pointers are skipped —
    the finalizer's stale sweep and the session-end reaper own those.
    """
    import glob as _glob

    base = candidate[: -len(".lck")] if candidate.endswith(".lck") else candidate
    locked = base + ".lck"
    for pointer_path in _glob.glob(COMMIT_GRANT_POINTER_GLOB):
        # Identity-bound read (audit F8): the pointer instance whose CONTENTS
        # authorize this deletion is the only instance the deletion may act on.
        pointer, ident = _read_identified(pointer_path)
        if not isinstance(pointer, dict):
            continue
        if pointer.get("original_path") == base or pointer.get("locked_path") == locked:
            if _unlink_identified(pointer_path, ident):
                print(
                    f"[revoke] Deleted grant pointer: {pointer_path}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[revoke] SKIPPED grant pointer (name no longer holds the "
                    f"instance that was read): {pointer_path}",
                    file=sys.stderr,
                )


def _revoke_grants_for_task(output_dir: str, task_id_to_revoke: str, sid: str) -> None:
    """Delete stale grant files matching task_id_to_revoke AND sid in output_dir.

    Iterates over claude-commit-grant-*.json files; loads each to check
    task_id and sid; deletes matching files. Scoped to sid to avoid deleting
    grants that belong to other sessions (e.g. parallel /commit invocations).
    Best-effort: errors are printed to stderr but do not raise.
    """
    import glob as _glob

    # Revoke both active .json grants and in-flight .lck grants (Fix B deferred-consume).
    # .lck files are grants locked by PreToolUse; if revocation runs mid-commit the
    # PostToolUse handler will attempt to restore them — revoking here prevents that.
    patterns = [
        str(Path(output_dir) / "claude-commit-grant-*.json"),
        str(Path(output_dir) / "claude-commit-grant-*.json.lck"),
    ]
    candidates = []
    for pat in patterns:
        candidates.extend(_glob.glob(pat))
    for candidate in candidates:
        # Identity-bound read (audit F8): a grant name is reused across the
        # whole lock/restore cycle, so "the file called X" is not the same claim
        # as "the file whose task_id and sid I just checked". Deleting by name
        # could remove a grant that had become live for another event since.
        data, ident = _read_identified(candidate)
        if not isinstance(data, dict):
            print(
                f"[revoke] WARNING: could not process {candidate}: "
                f"unreadable, non-regular, oversized or unparseable",
                file=sys.stderr,
            )
            continue
        if data.get("task_id") == task_id_to_revoke and data.get("sid") == sid:
            if not _unlink_identified(candidate, ident):
                print(
                    f"[revoke] SKIPPED stale grant (name no longer holds the "
                    f"instance that was read): {candidate}",
                    file=sys.stderr,
                )
                continue
            print(
                f"[revoke] Deleted stale grant: {candidate}",
                file=sys.stderr,
            )
            # Clean up any event-keyed pointer left by _lock_grant_for_posttool
            # (Fix B / audit R2-4): matched by recorded grant path, since the
            # pointer's event-keyed NAME cannot be reconstructed here.
            _revoke_pointers_for_grant(candidate)


def _git_capture(args: list[str], cwd: str | None = None) -> str:
    """Run `git <args>` (optionally scoped to `cwd`) and return stripped stdout.

    Raises RuntimeError on any failure (non-zero exit, missing git, bad cwd)
    so the caller aborts grant-writing rather than silently writing a grant
    missing the repo/branch/HEAD binding fields.
    """
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except OSError as exc:
        raise RuntimeError(
            f"git {' '.join(args)} failed to execute (cwd={cwd!r}): {exc}"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} exited {result.returncode} (cwd={cwd!r}): "
            f"{(result.stderr or '').strip()}"
        )
    return (result.stdout or "").strip()


def _resolve_sid(cli_sid: str | None) -> str:
    if cli_sid:
        return cli_sid
    env_sid = os.environ.get("CLAUDE_SESSION_ID", "") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not env_sid:
        print(
            "Cannot write commit grant: CLAUDE_SESSION_ID and CLAUDE_CODE_SESSION_ID are not set and "
            "--sid was not supplied. Invoke /commit from within a Claude "
            "Code session or pass --sid explicitly.",
            file=sys.stderr,
        )
        sys.exit(2)
    return env_sid


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if not args.task_id.strip():
        print(
            "Cannot write commit grant: --task-id must be non-empty.",
            file=sys.stderr,
        )
        return 2
    # Resolve SID first — if SID is missing we cannot write a grant OR safely
    # scope revocation; fail before touching any grant files.
    sid = _resolve_sid(args.sid)
    # Revoke-only mode: delete this task's grant(s) for this sid and exit WITHOUT
    # writing a fresh grant (gate-blocked stop paths must leave no live authorization).
    if args.revoke_only:
        _revoke_grants_for_task(args.output_dir, args.task_id, sid)
        print("revoke-only: revoked existing commit grant(s) for task")
        return 0
    # Revoke stale grants for task before writing a fresh one (retry flow).
    # Scoped to current sid to avoid deleting grants for other sessions.
    if args.revoke_existing_for_task:
        _revoke_grants_for_task(args.output_dir, args.revoke_existing_for_task, sid)
    # Resolve the repo/branch/HEAD binding fields BEFORE writing anything --
    # a grant that cannot establish its own baseline is unusable and must not
    # be written (fail closed, mirroring the SID-resolution failure above).
    try:
        repo_root = _git_capture(["rev-parse", "--show-toplevel"], cwd=args.repo_root)
        branch = _git_capture(["branch", "--show-current"], cwd=repo_root)
        expected_head = _git_capture(["rev-parse", "HEAD"], cwd=repo_root)
    except RuntimeError as exc:
        print(
            f"Cannot write commit grant: unable to resolve repo/branch/HEAD "
            f"binding: {exc}",
            file=sys.stderr,
        )
        return 2
    nonce = secrets.token_hex(8)
    now = datetime.now(timezone.utc)
    grant = {
        "task_id": args.task_id,
        "sid": sid,
        "nonce": nonce,
        "repo_root": repo_root,
        "branch": branch,
        "expected_head": expected_head,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=GRANT_TTL_MINUTES)).isoformat(),
    }
    grant_path = Path(args.output_dir) / f"claude-commit-grant-{sid}-{nonce}.json"
    with open(grant_path, "w") as fp:
        json.dump(grant, fp)
    print(str(grant_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
