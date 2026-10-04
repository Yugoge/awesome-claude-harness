#!/usr/bin/env python3
"""UserPromptSubmit hook: passively inject a per-account usage snapshot.

Passively injects a per-account usage snapshot (available/exhausted status,
session+weekly remaining %, reset time) into every user turn's context, with
zero active invocation required by the session.

Read source (single channel, per the standing constraint): this hook invokes
`node scripts/paseo-usage-read.mjs` -- the ONE read-only adapter documented in
commands/paseo-daemon.md Step 2 as "the ONLY controller-consumable usage
channel" -- and normalizes its stdout providers[] surface. It never opens a
websocket itself, never reads the daemon's persisted ledger (accounts.json;
that is a DIFFERENT consumer of the same adapter on the daemon's own ~45min
tick cadence, not this hook's channel), and never talks to /opt/paseo,
/usr/local/bin, or /root/bin directly.

Caching (latency/failure budget):
  CACHE_TTL_SECONDS = 300 (5 minutes). Reasoning: the adapter is a live RPC
  (not a cached read on the daemon side), so the cache exists ONLY to bound
  how often this hook spawns a new node+websocket process across rapid user
  turns -- not to track daemon-side freshness. 5 minutes keeps any decision
  gap within a single burst of turns to at most one stale read, while still
  avoiding a subprocess spawn on every turn of a fast back-and-forth
  conversation.
  READ_TIMEOUT_SECONDS = 5. The adapter has its own internal timeout (10s
  default, PASEO_USAGE_TIMEOUT_MS), but this hook bounds its OWN wait to 5s so
  a hung adapter process can never add more than 5s of visible latency to a
  user turn, and so this hook's own subprocess.run() call is what enforces
  "never blocks the session turn" -- it does not rely on the child's internal
  budget alone.

Degradation: a read failure or timeout NEVER raises, NEVER blocks, and NEVER
lets a stale reading pose as current -- a point-in-time value must carry its
own age/staleness marker next to it, not rely on a reader already knowing
which companion field governs its currency. On failure this hook emits
"unavailable" plus the last successful snapshot and that snapshot's own as_of
+ explicit STALE label; with no prior successful snapshot at all it says so
plainly.

Test seam: CLAUDE_USAGE_ADAPTER_CMD, when set, overrides the adapter command
(shlex-split) so sandboxed tests can simulate success/failure/timeout without
touching the real daemon or ledger. Production code path never sets it; the
default is always the real adapter invocation above.

Output contract: stdout is either empty (best-effort failure before any cache
state existed to report) or exactly one JSON object with
hookSpecificOutput.additionalContext -- agent-context only, no systemMessage,
so this never produces a per-turn banner in the user's own view.

Exit code: always 0. This hook must never block prompt submission.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.harness_state_dir import harness_state_dir  # noqa: E402

HOOK_EVENT_NAME = "UserPromptSubmit"
CACHE_TTL_SECONDS = 300
READ_TIMEOUT_SECONDS = 5
CACHE_FILENAME = "claude-usage-snapshot-cache.json"
ADAPTER_PATH = Path(__file__).resolve().parent.parent / "scripts" / "paseo-usage-read.mjs"
WINDOW_IDS = {"session": "five_hour", "weekly": "weekly"}


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cache_path() -> Path:
    return Path(harness_state_dir()) / CACHE_FILENAME


def _read_cache(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_cache(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".usage-cache-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
    except Exception:
        pass  # a cache write failure must never block the user turn


def _normalize_providers(raw) -> list[dict]:
    if isinstance(raw, dict):
        raw = raw.get("providers", [])
    if not isinstance(raw, list):
        return []

    def _window(windows_by_id: dict, window_id: str):
        w = windows_by_id.get(window_id)
        if not isinstance(w, dict):
            return None
        return {
            "remaining_pct": w.get("remainingPct"),
            "used_pct": w.get("usedPct"),
            "resets_at": w.get("resetsAt"),
        }

    out = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        windows = row.get("windows") or []
        by_id = {w.get("id"): w for w in windows if isinstance(w, dict)}
        out.append({
            "provider_id": row.get("providerId"),
            "display_name": row.get("displayName"),
            "status": row.get("status"),
            "session": _window(by_id, WINDOW_IDS["session"]),
            "weekly": _window(by_id, WINDOW_IDS["weekly"]),
        })
    return out


def _adapter_command() -> list[str]:
    override = os.environ.get("CLAUDE_USAGE_ADAPTER_CMD")
    if override:
        return shlex.split(override)
    return ["node", str(ADAPTER_PATH)]


def _run_adapter():
    """Returns (status, providers_or_None, note_or_None). Never raises."""
    cmd = _adapter_command()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=READ_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return "failed_timeout", None, f"adapter timed out after {READ_TIMEOUT_SECONDS}s"
    except Exception as exc:  # noqa: BLE001 - hook must never crash
        return "failed_error", None, f"adapter spawn failed: {exc}"

    if result.returncode != 0:
        stderr_lines = (result.stderr or "").strip().splitlines()
        note = stderr_lines[0] if stderr_lines else f"adapter exited {result.returncode}"
        return "failed_error", None, note

    try:
        parsed = json.loads(result.stdout)
    except Exception as exc:  # noqa: BLE001
        return "failed_error", None, f"adapter stdout parse failed: {exc}"

    return "ok", _normalize_providers(parsed), None


def _update_cache(cache: dict, now: float, status: str, providers, note) -> dict:
    cache = dict(cache) if isinstance(cache, dict) else {}
    cache["last_attempt_epoch"] = now
    cache["last_attempt_iso"] = _iso(now)
    cache["last_attempt_status"] = status
    cache["last_attempt_note"] = note
    if status == "ok":
        cache["last_success"] = {
            "as_of_epoch": now,
            "as_of_iso": _iso(now),
            "providers": providers,
        }
    return cache


def _format_providers(providers: list[dict]) -> list[str]:
    if not providers:
        return ["  (no provider rows in this reading)"]
    lines = []
    for p in providers:
        name = p.get("display_name") or p.get("provider_id") or "unknown"
        status = p.get("status") or "unknown"
        parts = [f"status={status}"]
        for label in ("session", "weekly"):
            window = p.get(label)
            if window and window.get("remaining_pct") is not None:
                resets = window.get("resets_at") or "unknown"
                parts.append(f"{label} {window['remaining_pct']}% remaining (resets {resets})")
            else:
                parts.append(f"{label} unknown")
        lines.append(f"  - {name}: " + ", ".join(parts))
    return lines


def _format_context(now: float, cache: dict) -> str:
    attempt_status = cache.get("last_attempt_status")
    attempt_note = cache.get("last_attempt_note")
    last_success = cache.get("last_success")

    if attempt_status == "ok" and isinstance(last_success, dict):
        age = now - last_success["as_of_epoch"]
        fresh = age < CACHE_TTL_SECONDS
        header = (
            f"[account-usage] snapshot as_of={last_success['as_of_iso']} "
            f"(age {max(int(age), 0)}s, {'fresh' if fresh else 'STALE'})"
        )
        return "\n".join([header, *_format_providers(last_success["providers"])])

    if isinstance(last_success, dict):
        age = now - last_success["as_of_epoch"]
        note_part = f" ({attempt_note})" if attempt_note else ""
        header = (
            f"[account-usage] live read {attempt_status or 'unavailable'}{note_part}; "
            f"showing last successful snapshot as_of={last_success['as_of_iso']} "
            f"(age {max(int(age), 0)}s, STALE)"
        )
        return "\n".join([header, *_format_providers(last_success["providers"])])

    note_part = f" (last attempt {attempt_status}: {attempt_note})" if attempt_status else ""
    return f"[account-usage] unavailable: no successful reading yet{note_part}"


def main() -> int:
    try:
        now = time.time()
        cache_path = _cache_path()
        cache = _read_cache(cache_path)
        last_attempt_epoch = cache.get("last_attempt_epoch")
        is_cache_fresh = (
            isinstance(last_attempt_epoch, (int, float))
            and (now - last_attempt_epoch) < CACHE_TTL_SECONDS
        )
        if not is_cache_fresh:
            status, providers, note = _run_adapter()
            cache = _update_cache(cache, now, status, providers, note)
            _write_cache(cache_path, cache)

        text = _format_context(now, cache)
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": HOOK_EVENT_NAME,
                "additionalContext": text,
            },
        }, ensure_ascii=True))
    except Exception:
        pass  # absolute backstop: a UserPromptSubmit hook must never block
    return 0


if __name__ == "__main__":
    sys.exit(main())
