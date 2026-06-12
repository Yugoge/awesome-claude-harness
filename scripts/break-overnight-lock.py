#!/usr/bin/env python3
"""Break every active overnight time-lock + workflow-enforce.

Backdates end_time on every active overnight-state-*.json so
stop-overnight-timelock.py releases, and marks all todos completed so
stop-workflow-enforce.py releases.

Used by /stop slash command (commands/stop.md → hooks/stop.sh → here).

fix-4 (Cycle-2): helper-side sentinel VALIDATION before mutation (defense in
depth). Even if the PreTool sentinel guard (hooks/pretool-wrapper-userintent.py)
is bypassed, this helper refuses to set `isolation_released_at` unless a fresh,
unexpired helper-auth token minted by that guard for a real /stop is present,
and it CONSUMES the token one-shot so a replay cannot re-release.
"""
import glob
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

CLAUDE_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", "/root")) / ".claude"
TODOS_DIR = Path.home() / ".claude" / "todos"

# Where the PreTool user-intent guard mints the helper-auth token
# (claude-stop-helper-auth-<sid>.json). Overridable for sandbox tests.
_SENTINEL_DIR = os.environ.get("CLAUDE_USERINTENT_SENTINEL_DIR", "/tmp")


def _consume_helper_auth() -> bool:
    """fix-4 components (c)+(d): validate + one-shot consume the helper-auth
    token the PreTool /stop guard minted. Returns True iff a fresh, unexpired
    token for this session existed and was consumed. No token / expired /
    already-consumed -> False (the helper then refuses to release isolation)."""
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
            return True
    return False


def _backdate(sf: Path, past: str, release_isolation: bool) -> str:
    d = json.loads(sf.read_text())
    sid = d.get("session_id", "?")
    old = d.get("end_time", "?")
    d["end_time"] = past
    d["current_phase"] = "completed"
    # M10/AC8 + fix-4: this user `/stop` release path is the ONLY sanctioned
    # setter of isolation_released_at and the closer of isolation_active_until.
    # update-overnight-state.sh rejects --set on these fields. The release of the
    # isolation guarantee fields happens here ONLY when a valid /stop user-intent
    # helper-auth token was consumed (release_isolation); otherwise the helper
    # MUST NOT touch isolation_released_at / isolation_active_until — so an
    # overnight actor that reaches this helper directly (bypassing the PreTool
    # guard) still cannot self-release isolation.
    if release_isolation:
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        d["isolation_released_at"] = now_iso
        if "isolation_active_until" in d:
            d["isolation_active_until"] = past
        sf.write_text(json.dumps(d, indent=2))
        print(f"  state {sid[:8]}: end_time {old} -> {past}; isolation_released_at={now_iso}")
    else:
        sf.write_text(json.dumps(d, indent=2))
        print(f"  state {sid[:8]}: end_time {old} -> {past}; isolation_released_at WITHHELD "
              "(no valid /stop user-intent token — actors cannot self-release isolation)")
    return sid


def _complete_todos(sid: str) -> None:
    todos = TODOS_DIR / f"{sid}-agent-{sid}.json"
    if not todos.exists():
        return
    items = json.loads(todos.read_text())
    for t in items:
        if isinstance(t, dict):
            t["status"] = "completed"
    todos.write_text(json.dumps(items))
    print(f"  todos {sid[:8]}: marked all {len(items)} completed")


def main() -> int:
    states = sorted(CLAUDE_DIR.glob("overnight-state-*.json"))
    if not states:
        print("no overnight state files found — nothing to unlock")
        return 0
    # fix-4 (c)+(d): helper-side validation before mutation. Releasing the
    # isolation guarantee fields requires a fresh /stop helper-auth token; the
    # consume is one-shot so a replayed token cannot re-release.
    release_isolation = _consume_helper_auth()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for sf in states:
        sid = _backdate(sf, past, release_isolation)
        _complete_todos(sid)
    if release_isolation:
        print("done — both Stop hooks released; session can now terminate")
        return 0
    # No valid /stop user intent: the time-lock backdate still releases the Stop
    # hooks (so a stuck session is not wedged), but isolation_released_at is
    # WITHHELD and we exit non-zero so the unsanctioned caller is signalled.
    print("WARNING: isolation_released_at WITHHELD (no valid /stop user-intent "
          "token). An overnight actor cannot self-release isolation.",
          file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
