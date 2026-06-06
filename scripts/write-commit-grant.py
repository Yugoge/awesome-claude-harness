#!/usr/bin/env python3
"""Write a single-use /commit privilege-guard grant manifest.

Invoked from `commands/commit.md` Step 5 (non-bulk mode) to author a
short-lived authorization token consumed by
`/root/.claude/hooks/pretool-git-privilege-guard.py` (see
`_end_time_passed` at lines 377-384; ISO-8601 contract preserved).

The script writes a JSON file at
`<output-dir>/claude-commit-grant-<sid>-<nonce>.json` containing:
  - task_id    : --task-id argument (REQUIRED)
  - sid        : --sid argument OR CLAUDE_SESSION_ID env var
  - nonce      : 16-char hex (secrets.token_hex(8))
  - created_at : ISO-8601 timezone-aware UTC at write time
  - expires_at : created_at + GRANT_TTL_MINUTES (named module constant)

Both timestamps are produced from `datetime.now(timezone.utc)` and are
fromisoformat-parseable by the privilege guard. Epoch ints/floats and
naive datetimes are silently rejected by the guard.

Exit codes:
  0  success (grant written)
  2  CLAUDE_SESSION_ID unresolved (neither --sid nor env var supplied)
  argparse-default 2 when --task-id is omitted (handled by argparse)
"""

import argparse
import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Grant validity window. The privilege guard expires the grant at
# created_at + GRANT_TTL_MINUTES; do not duplicate this literal at the
# operational call site (use the constant symbolically).
GRANT_TTL_MINUTES = 30


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
        try:
            with open(candidate) as fp:
                data = json.load(fp)
            if data.get("task_id") == task_id_to_revoke and data.get("sid") == sid:
                Path(candidate).unlink()
                print(
                    f"[revoke] Deleted stale grant: {candidate}",
                    file=sys.stderr,
                )
                # Clean up pointer file left by _lock_grant_for_posttool (Fix B).
                pointer = Path(f"/tmp/claude-commit-grant-active-{sid}.json")
                try:
                    pointer.unlink()
                except (FileNotFoundError, OSError):
                    pass
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            print(
                f"[revoke] WARNING: could not process {candidate}: {exc}",
                file=sys.stderr,
            )


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
    nonce = secrets.token_hex(8)
    now = datetime.now(timezone.utc)
    grant = {
        "task_id": args.task_id,
        "sid": sid,
        "nonce": nonce,
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
