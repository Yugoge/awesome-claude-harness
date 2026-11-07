#!/usr/bin/env python3
"""Record the human's /stop in the stopping session's own overnight state.

The time-lock is released by the human-typed /stop record itself
(hooks/lib/stop_contract.py timelock_released, which
hooks/stop-overnight-timelock.py reads), never by anything this script writes:
it writes no end_time. It records current_phase=completed in the stopping
session's record, found by hooks/lib/overnight.py's locator (no other
session's record is touched), which closes that record's share of the
session-agnostic overnight exemption (overnight.is_overnight_active). The CLI's
todo list is its own record: nothing here writes it (P1b E7).

Used by /stop (commands/stop.md -> hooks/stop.sh -> here).

The isolation guarantee fields, isolation_released_at and
isolation_active_until, are released only with a fresh helper-auth token, which
the PreTool user-intent guard (hooks/pretool-wrapper-userintent.py) mints for a
human-typed /stop; the token is consumed one-shot so a replay cannot release
again, and it gates nothing else.
"""
import glob
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# WS1: the state's locator and write path are the shared lib (this script
# lives at <harness home>/scripts/break-overnight-lock.py, so the lib is at
# ../hooks/lib). Never default to the author literal /root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks" / "lib"))
from harness_state_dir import harness_state_dir  # noqa: E402
import overnight  # noqa: E402

# Where the PreTool user-intent guard mints the helper-auth token
# (claude-stop-helper-auth-<sid>.json). Overridable for sandbox tests.
_SENTINEL_DIR = os.environ.get("CLAUDE_USERINTENT_SENTINEL_DIR", harness_state_dir())


def _consume_helper_auth() -> tuple:
    """fix-4 components (c)+(d): validate + one-shot consume the helper-auth
    token the PreTool /stop guard minted. Returns (valid, session id): valid iff
    a fresh, unexpired token existed and was consumed (no token / expired /
    already-consumed: the helper refuses to release isolation); the session is
    the environment's, else the consumed token's."""
    sid = os.environ.get("CLAUDE_SESSION_ID", "") or os.environ.get(
        "CLAUDE_CODE_SESSION_ID", "")
    candidates = []
    if sid:
        candidates.append(Path(_SENTINEL_DIR) / f"claude-stop-helper-auth-{sid}.json")
    # Fallback: any stop helper-auth token in the sentinel dir (the /stop guard
    # mints exactly one per release; sid may differ between the prompt hook's
    # session and the helper's env in some launch paths).
    candidates += [Path(p) for p in glob.glob(
        str(Path(_SENTINEL_DIR) / "claude-stop-helper-auth-*.json"))]
    seen = set()
    for path in candidates:
        rp = str(path)
        if rp in seen:
            continue
        seen.add(rp)
        try:
            if not path.exists():
                continue
            doc = json.loads(path.read_text())
            exp = int(doc.get("expires_at", 0))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        # Consume one-shot regardless of validity (a malformed/expired token is
        # still removed so it cannot accumulate).
        try:
            path.unlink()
        except OSError:
            pass
        if exp >= int(time.time()):
            return True, sid or str(doc.get("session_id") or "")
    return False, sid


def main() -> int:
    # fix-4 (c)+(d): helper-side validation before mutation; the consume is
    # one-shot so a replayed token cannot release isolation again.
    release_isolation, sid = _consume_helper_auth()
    # The stopping session's record only (CLAUDE_PROJECT_DIR, else the cwd: the
    # session's project directory, its worktree included).
    state_file, record = overnight.locate(sid) if sid else (None, None)
    if record is None:
        print("no overnight state for this session — nothing to record")
        return 0
    record["current_phase"] = "completed"
    if release_isolation:
        now = datetime.now(timezone.utc)
        record["isolation_released_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        if "isolation_active_until" in record:
            record["isolation_active_until"] = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    overnight.write_state(state_file, record)
    print(f"  state {sid[:8]}: current_phase=completed; end_time {record.get('end_time')} unchanged")
    if release_isolation:
        print("done — isolation released; the human's /stop record releases the time-lock")
        return 0
    # No valid /stop user intent: isolation_released_at is WITHHELD and we exit
    # non-zero so the unsanctioned caller is signalled.
    print("WARNING: isolation_released_at WITHHELD (no valid /stop user-intent "
          "token). An overnight actor cannot self-release isolation.",
          file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
