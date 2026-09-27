#!/usr/bin/env python3
"""paseo-daemon-timers.py — declarative inventory + safe reconciler for the
four paseo-daemon timer schedules (tick, ctrl-core-reinject, watchdog,
reader-board-sweep).

Today these four are half-provisioned by an old bootstrap step and half by
manual controller creation, with no machine-checkable inventory and no safe
combined stop path. This CLI is the reconciler.

CRITICAL dedup constraint (read before touching `ensure`): identity/dedup
checks MUST be performed ONLY against on-disk `--registry-dir/*.json` files.
NEVER dedup via any MCP/CLI schedule-query surface — that surface returns
"Schedule not found" for at least two of the four live registrations
(measured live, this cycle), so any implementation that trusts it will
duplicate-create a schedule that already exists on disk. This script never
calls any such query surface; it reads the registry directory directly.

Subcommands:
  ensure   idempotent reconciliation: creates any of the four timers missing
           from --registry-dir (on-disk-only dedup, see above); never
           rebuilds or overwrites an already-present registration or its
           `prompt` field. Creating an `agent`-target timer needs
           --controller-agent-id; creating any timer needs a per-timer
           `prompt` value sourced from --prompts-dir/<key>.prompt.txt (the
           static inventory below never embeds prompt text — only a
           reference to where it lives). Both inputs are optional but
           required-when-needed: if a timer needs creating and either input
           is unavailable for it, the ENTIRE invocation fails closed
           (non-zero exit, every blocked timer key named, zero files
           written) rather than partially creating some and not others.
  drain    safety-ordered stop of all four: watchdog first (a mid-teardown
           watchdog fire would judge the controller dead and escalate),
           then sweep, tick, reinject (DRAIN_ORDER). Prefers `pause`
           (reversible) via backup -> temp-write -> parse-validate ->
           atomic os.replace; never deletes. Finishes with exactly one
           `scripts/paseo-daemon-ledger.py teardown-declare` call against
           --ledger-root to journal the teardown.
  status   read-only: existence / active-vs-paused / nextRunAt / deviation
           from the inventory for each of the four. Never creates, modifies,
           or deletes any file under --registry-dir.

Exit codes: 0=success, 1=usage error (missing/invalid CLI input), 2=refused
(corrupt registry data, or a downstream failure such as teardown-declare
exiting non-zero).

--registry-dir defaults to /root/.paseo/schedules (the real, live registry).
Every test MUST override it to a pytest tmp_path; --ledger-root has no
default at all (see M6) to avoid a footgun that could reach the real
ledger from a stray invocation.
"""

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_REFUSED = 2

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER_SCRIPT = Path(__file__).resolve().parent / "paseo-daemon-ledger.py"

# Static declarative inventory (R1/M1). No prompt text lives here -- steady
# state sources it from the on-disk registration's own `prompt` field;
# create-time sources it from --prompts-dir/<key>.prompt.txt (M11).
INVENTORY = [
    {
        "key": "tick",
        "name": "paseo-daemon-tick",
        # Live registration is "paseo-daemon-tick hbtick-20260902T1158Z-c7d1"
        # (a wake-arm channel-id suffix), not the clean canonical name --
        # exact-string dedup would duplicate it (M2/R-DECIDE-1).
        "match_mode": "prefix",
        "cron": "12,57 * * * *",
        "timezone": "UTC",
        "target_type": "agent",
    },
    {
        "key": "reinject",
        "name": "ctrl-core-reinject",
        "match_mode": "exact",
        "cron": "41 */4 * * *",
        "timezone": "UTC",
        "target_type": "agent",
    },
    {
        "key": "watchdog",
        "name": "paseo-daemon-watchdog",
        "match_mode": "exact",
        "cron": "23,53 * * * *",
        "timezone": "UTC",
        # Fully self-contained -- no controller agentId needed to create it
        # (captured verbatim from the live a814a9a0.json registration).
        "target_type": "new-agent",
        "target_config": {
            "provider": "claude",
            "cwd": "/root/.claude",
            "modeId": "bypassPermissions",
            "model": "claude-sonnet-4-6@yugoge",
            "featureValues": {},
        },
    },
    {
        "key": "sweep",
        "name": "reader-board-sweep",
        "match_mode": "exact",
        "cron": "37 */4 * * *",
        "timezone": "UTC",
        "target_type": "agent",
    },
]

# Structurally separate from INVENTORY's own order (M4) -- drain iterates
# THIS constant, never INVENTORY.keys()/order. Watchdog first, always.
DRAIN_ORDER = ["watchdog", "sweep", "tick", "reinject"]


class TimerWriteValidationError(Exception):
    """Raised when a just-written temp registration file fails to parse
    back as JSON (M5 fail-closed write-validation step)."""


def fail(code, msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def resolve_now(now_str):
    if now_str is None:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(now_str.replace("Z", "+00:00"))
    except ValueError:
        fail(EXIT_USAGE, f"--now: unparseable: {now_str!r}")
    if dt.tzinfo is None:
        fail(EXIT_USAGE, f"--now: naive (timezone-less) timestamp rejected: {now_str!r}")
    return dt.astimezone(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def compact_iso(dt):
    """BA-authored backup-suffix format (M5): the live repo's own `.bak-*`
    files use two inconsistent timestamp formats across only 2/4 files --
    not an established convention (see ticket Reference Source table) -- so
    this defines its own: <UTC compact ISO>, e.g. 20260926T111239Z."""
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def timer_matches(entry, name):
    if not isinstance(name, str):
        return False
    if entry["match_mode"] == "exact":
        return name == entry["name"]
    if entry["match_mode"] == "prefix":
        return name == entry["name"] or name.startswith(entry["name"] + " ")
    raise ValueError(f"unknown match_mode {entry['match_mode']!r} for key {entry['key']!r}")


def scan_registry(registry_dir):
    """Read every *.json file under registry-dir. Fail closed (M9): on the
    first unparseable file, name it and abort -- write nothing, for either
    ensure or status."""
    registrations = []
    if not registry_dir.is_dir():
        return registrations
    for path in sorted(registry_dir.glob("*.json")):
        try:
            obj = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            fail(EXIT_REFUSED, f"corrupt registration file (invalid JSON): {path} ({exc})")
        registrations.append((path, obj))
    return registrations


def find_match(entry, registrations):
    for path, obj in registrations:
        if timer_matches(entry, obj.get("name", "")):
            return path, obj
    return None


def atomic_write_registration(path, obj, *, backup, now):
    """Shared file-safety chain for both create (ensure) and pause (drain):
    optional backup -> write temp in same dir -> parse temp back to confirm
    well-formed (fail-closed: delete temp, raise, touch nothing else) ->
    os.replace onto the final path (atomic)."""
    if backup and path.exists():
        backup_path = path.with_name(path.name + f".bak-{compact_iso(now)}")
        shutil.copy2(path, backup_path)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    try:
        json.loads(tmp_path.read_text())
    except json.JSONDecodeError as exc:
        tmp_path.unlink(missing_ok=True)
        raise TimerWriteValidationError(f"temp write for {path} failed JSON validation: {exc}")
    os.replace(tmp_path, path)


def read_prompt_fixture(prompts_dir, key):
    """Optional per-timer create-time prompt source (M11/R-DECIDE-4):
    --prompts-dir/<key>.prompt.txt, at most one trailing newline stripped.
    Returns None if unavailable (absent dir, absent file, empty/whitespace
    content) -- never a default; the caller fails closed on None."""
    if not prompts_dir:
        return None
    p = Path(prompts_dir) / f"{key}.prompt.txt"
    if not p.is_file():
        return None
    content = p.read_text()
    if content.endswith("\n"):
        content = content[:-1]
    if not content.strip():
        return None
    return content


def new_timer_id(existing_ids):
    for _ in range(1000):
        candidate = secrets.token_hex(4)
        if candidate not in existing_ids:
            return candidate
    fail(EXIT_REFUSED, "could not allocate a unique timer id")


def build_registration(entry, timer_id, prompt, controller_agent_id, now):
    if entry["target_type"] == "agent":
        target = {"type": "agent", "agentId": controller_agent_id}
    else:
        target = {"type": "new-agent", "config": dict(entry["target_config"])}
    return {
        "id": timer_id,
        "name": entry["name"],
        "prompt": prompt,
        "cadence": {
            "type": "cron",
            "expression": entry["cron"],
            "timezone": entry.get("timezone", "UTC"),
        },
        "target": target,
        "status": "active",
        "createdAt": iso(now),
        "updatedAt": iso(now),
        "nextRunAt": None,
        "lastRunAt": None,
        "pausedAt": None,
        "expiresAt": None,
        "maxRuns": None,
        "runs": [],
    }


def cmd_ensure(args):
    registry_dir = Path(args.registry_dir)
    registrations = scan_registry(registry_dir)

    missing = [entry for entry in INVENTORY if find_match(entry, registrations) is None]
    if not missing:
        print(json.dumps({"ok": True, "created": []}))
        return

    problems = {}
    prompts = {}
    for entry in missing:
        issues = []
        if entry["target_type"] == "agent" and not args.controller_agent_id:
            issues.append("missing --controller-agent-id")
        prompt = read_prompt_fixture(args.prompts_dir, entry["key"])
        if prompt is None:
            issues.append("missing prompt source (--prompts-dir/<key>.prompt.txt)")
        else:
            prompts[entry["key"]] = prompt
        if issues:
            problems[entry["key"]] = issues

    if problems:
        detail = "; ".join(f"{k}: {', '.join(v)}" for k, v in sorted(problems.items()))
        fail(EXIT_USAGE, f"cannot create missing timer(s), zero files written: {detail}")

    now = resolve_now(args.now)
    registry_dir.mkdir(parents=True, exist_ok=True)
    existing_ids = {path.stem for path, _ in registrations}
    created = []
    for entry in missing:
        timer_id = new_timer_id(existing_ids)
        existing_ids.add(timer_id)
        obj = build_registration(entry, timer_id, prompts[entry["key"]],
                                  args.controller_agent_id, now)
        path = registry_dir / f"{timer_id}.json"
        atomic_write_registration(path, obj, backup=False, now=now)
        created.append({"key": entry["key"], "id": timer_id, "name": entry["name"]})

    print(json.dumps({"ok": True, "created": created}))


def cmd_status(args):
    registry_dir = Path(args.registry_dir)
    registrations = scan_registry(registry_dir)

    timers = {}
    for entry in INVENTORY:
        match = find_match(entry, registrations)
        if match is None:
            timers[entry["key"]] = {
                "exists": False, "status": None, "next_run_at": None,
                "deviations": ["missing"],
            }
            continue
        _, obj = match
        deviations = []
        cadence = obj.get("cadence") or {}
        if cadence.get("expression") != entry["cron"]:
            deviations.append("cron_mismatch")
        target = obj.get("target") or {}
        if target.get("type") != entry["target_type"]:
            deviations.append("target_type_mismatch")
        timers[entry["key"]] = {
            "exists": True,
            "status": obj.get("status"),
            "next_run_at": obj.get("nextRunAt"),
            "deviations": deviations,
        }

    print(json.dumps({"timers": timers}))


def cmd_drain(args):
    registry_dir = Path(args.registry_dir)
    registrations = scan_registry(registry_dir)
    by_key = {}
    for entry in INVENTORY:
        match = find_match(entry, registrations)
        if match is not None:
            by_key[entry["key"]] = match

    now = resolve_now(args.now)
    drained = []
    for key in DRAIN_ORDER:
        if key not in by_key:
            continue
        path, obj = by_key[key]
        if obj.get("status") == "paused":
            continue
        updated = dict(obj)
        updated["status"] = "paused"
        updated["pausedAt"] = iso(now)
        updated["updatedAt"] = iso(now)
        try:
            atomic_write_registration(path, updated, backup=True, now=now)
        except TimerWriteValidationError as exc:
            fail(EXIT_REFUSED, str(exc))
        drained.append(key)
        print(json.dumps({"op": "pause", "key": key, "id": path.stem}))

    ledger_cmd = [sys.executable, str(LEDGER_SCRIPT), "--root", str(args.ledger_root)]
    if args.now:
        ledger_cmd += ["--now", args.now]
    ledger_cmd += ["teardown-declare", "--reason", args.reason]
    result = subprocess.run(ledger_cmd, capture_output=True, text=True, cwd=REPO_ROOT)
    if result.returncode != 0:
        fail(EXIT_REFUSED, f"teardown-declare failed (rc={result.returncode}): {result.stderr.strip()}")

    declare = json.loads(result.stdout) if result.stdout.strip() else None
    print(json.dumps({"ok": True, "drained": drained, "teardown_declare": declare}))


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--registry-dir", default="/root/.paseo/schedules",
                   help="on-disk schedule registry directory (tests MUST use a tmp_path)")
    p.add_argument("--now", default=None, help="fake clock: aware ISO-8601 timestamp (tests)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ensure")
    s.add_argument("--controller-agent-id", default=None,
                   help="required only when an agent-type timer needs creating")
    s.add_argument("--prompts-dir", default=None,
                   help="dir of <key>.prompt.txt fixtures; required only when a timer "
                        "needs creating and its prompt has no other source")
    s.set_defaults(fn=cmd_ensure)

    s = sub.add_parser("status")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("drain")
    s.add_argument("--ledger-root", required=True,
                   help="ledger root for the final teardown-declare call (no default: M6)")
    s.add_argument("--reason", default="paseo-daemon-timers.py drain: scheduled fleet teardown",
                   help="non-empty --reason forwarded to teardown-declare")
    s.set_defaults(fn=cmd_drain)

    return p


def main():
    args = build_parser().parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
