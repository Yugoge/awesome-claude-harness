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
           On-disk presence alone is NOT health: any inventory timer found
           with status=paused is reported under the `deviations` key (id,
           pausedAt, and the exact `resume` command shape to recover it) —
           ensure NEVER reports zero deviation for a paused timer UNLESS it
           just auto-resolved it (see --ledger-root below), and it never
           rebuilds or overwrites an active registration. A prior incident
           (task 20260926-111239 follow-up): four timers sat paused for 5
           days after a drain because bootstrap's `ensure` saw `created: []`
           and nobody inspected `status`; the `deviations` field was that
           fix. A SECOND incident (task 20261004-050913): `deviations` still
           required a HUMAN to run `resume` -- the four timers then sat
           paused for 6 more days after a daemon restart, because nobody
           did. `--ledger-root` (optional; omitting it reproduces the FIRST
           fix's behavior exactly, zero auto-mutation) closes that gap:
           when given, ensure queries `scripts/paseo-daemon-ledger.py
           teardown-status` and auto-resumes (via the SAME core as `resume`
           below) any paused timer, and re-arms the tick wake channel, ONLY
           when the ledger's LATEST teardown-declare carries `for_restart`
           with no `keep_down` -- a deliberate maintenance pause (no
           for_restart marker) is STILL never silently reverted. The result
           is reported under `auto_recovery`, and any key it actually
           resumed is removed from `deviations` (it is no longer a
           deviation once fixed). Absence of a ledger-root, an
           uninitialized/unreadable ledger, or no declared teardown at all
           are ALL treated as "not authorized" -- positive evidence only,
           never fail-open.
  drain    safety-ordered stop of all four: watchdog first (a mid-teardown
           watchdog fire would judge the controller dead and escalate),
           then sweep, tick, reinject (DRAIN_ORDER). Prefers `pause`
           (reversible) via backup -> temp-write -> parse-validate ->
           atomic os.replace; never deletes. Finishes with exactly one
           `scripts/paseo-daemon-ledger.py teardown-declare` call against
           --ledger-root to journal the teardown; `--for-restart` /
           `--keep-down` pass through to that call verbatim (see `ensure`
           above for what they authorize on the next bootstrap).
  resume   paired with drain: restores any paused timer (within the
           four-entry inventory only) back to status=active, in the exact
           reverse of DRAIN_ORDER — reinject, sweep, tick, watchdog last.
           Watchdog resumes last so it never wakes before the rest of the
           control plane is back online; an early watchdog fire against a
           still-recovering fleet would judge it dead and escalate (the
           same hazard DRAIN_ORDER's watchdog-first avoids, mirrored for the
           opposite direction). Same file-safety chain as drain: backup ->
           temp-write -> parse-validate -> atomic os.replace. Idempotent: an
           already-active (or missing) timer is a no-op. This is the same
           core `ensure --ledger-root` calls automatically when authorized.
  status   read-only: existence / active-vs-paused / nextRunAt / deviation
           from the inventory for each of the four — a paused timer always
           carries `"paused"` in its `deviations` list, never a silent
           active-looking entry. Never creates, modifies, or deletes any
           file under --registry-dir.

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

# resume iterates THIS constant, never DRAIN_ORDER or INVENTORY order --
# exact reverse of DRAIN_ORDER; see the module docstring's `resume` entry
# for why watchdog goes last.
RESUME_ORDER = list(reversed(DRAIN_ORDER))


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


def find_all_matches(entry, registrations):
    """Every registration matching `entry`, not just the first (task
    20261004-085212): `find_match`'s first-match-wins semantics is exactly
    what hides a duplicate from `ensure`/`status`/`drain`/`resume`'s normal
    by_key path -- e.g. a stale PAUSED registration sharing the live tick
    channel's exact `name` (and therefore channel_id) sits invisibly behind
    whichever of the two `scan_registry`'s filename sort happens to return
    first. `resume`'s pre-flight collision check scans this list instead of
    trusting a single match."""
    return [(path, obj) for path, obj in registrations if timer_matches(entry, obj.get("name", ""))]


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


def paused_deviation(registry_dir, entry, path, obj):
    """A present-but-paused inventory timer is a deviation, not a silent
    pass (see module docstring's `ensure` entry for why). ensure never
    auto-resumes (that would make a bootstrap reconciliation able to
    silently revert a deliberate maintenance pause) -- the deviation
    instead names the exact `resume` command shape an operator runs to
    recover it."""
    return {
        "key": entry["key"],
        "id": path.stem,
        "status": "paused",
        "pausedAt": obj.get("pausedAt"),
        "recovery_command": f"scripts/paseo-daemon-timers.py --registry-dir {registry_dir} resume",
    }


def ledger_teardown_status(ledger_root):
    """Read-only query of the ledger's latest teardown declaration, via the
    ledger CLI subprocess -- timers.py never reads ledger-root files
    directly, same loose-coupling discipline as cmd_drain's existing
    teardown-declare call. Returns None on ANY failure (ledger-root
    unreachable, uninitialized, corrupt output, or nothing ever declared):
    absence of positive proof never authorizes auto-resume (see module
    docstring's `ensure` entry)."""
    cmd = [sys.executable, str(LEDGER_SCRIPT), "--root", str(ledger_root), "teardown-status"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        status = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not status.get("declared"):
        return None
    return status


def rearm_tick_wake_channel(ledger_root, resumed, now):
    """Called ONLY when `resumed` (the list `resume_paused_timers` just
    flipped from paused to active) contains the "tick" key -- the ledger's
    wake.json bookkeeping for that channel is now stale (its watermark
    never advanced during the outage) and must be fenced with a fresh
    arming. --token-delivery disk-read (task 20261004-050913): the tick
    channel's live registration is the one known to be invisible to the
    schedule-query surface (module docstring's CRITICAL dedup constraint),
    so its external prompt can never be refreshed with a freshly-minted
    token -- arming prompt-capture here would make every future delivery
    permanently superseded_arming. The channel id is reused from the
    resumed registration's own name suffix (continuity of identity), never
    freshly minted when one is available. --self-heal-authorized (task
    20261004-085212): the ledger CLI's wake-arm now refuses every caller
    that is not the current, unexpired lease holder -- which this call,
    running precisely to recover from an outage, generally is not. The flag
    makes wake-arm independently re-derive the SAME teardown-status
    eligibility auto_recover_paused_timers already required before ever
    reaching this function, rather than needing a lease identity it has no
    business claiming."""
    tick_item = next((item for item in resumed if item["key"] == "tick"), None)
    name = tick_item["name"] if tick_item else None
    channel_id = None
    if name and " " in name:
        channel_id = name.split(" ", 1)[1]
    if not channel_id:
        channel_id = f"hbtick-{compact_iso(now)}-{secrets.token_hex(2)}"
    tick_entry = next(e for e in INVENTORY if e["key"] == "tick")
    cmd = [sys.executable, str(LEDGER_SCRIPT), "--root", str(ledger_root), "--now", iso(now),
           "wake-arm", "--self-heal-authorized",
           "--channel-kind", "paseo_heartbeat", "--channel-id", channel_id,
           "--cron", tick_entry["cron"], "--timezone", tick_entry.get("timezone", "UTC"),
           "--role", "tick", "--token-delivery", "disk-read"]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
    if result.returncode != 0:
        return {"ok": False, "channel_id": channel_id, "error": result.stderr.strip()}
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    payload = json.loads(lines[-1]) if lines else {}
    return {"ok": True, "channel_id": channel_id, "arming_token": payload.get("arming_token")}


def auto_recover_paused_timers(args, registry_dir, deviations, now):
    """Ledger-driven restart-recovery path (task 20261004-050913; see
    module docstring's `ensure` entry). Authorized ONLY by the ledger's
    LATEST teardown-declare carrying `for_restart` with no `keep_down` --
    never inferred from the mere presence of a paused timer, which is
    exactly as consistent with "deliberate maintenance pause, still
    pending" as with "restart recovery owed". Absence of --ledger-root, an
    unreachable/uninitialized ledger, or no declared teardown at all are
    ALL "not authorized"; this function never raises and never partially
    authorizes."""
    result = {"eligible": False, "reason": None, "resumed": [], "wake_armed": None}
    if not deviations:
        result["reason"] = "no_paused_timers"
        return result
    ledger_root = getattr(args, "ledger_root", None)
    if not ledger_root:
        result["reason"] = "ledger_root_not_provided"
        return result
    status = ledger_teardown_status(ledger_root)
    if status is None:
        result["reason"] = "no_teardown_declared"
        return result
    if status.get("keep_down") is True:
        result["reason"] = "keep_down_declared"
        return result
    if status.get("for_restart") is not True:
        result["reason"] = "last_teardown_not_for_restart"
        return result
    result["eligible"] = True
    resumed, refused = resume_paused_timers(registry_dir, now)
    result["resumed"] = resumed
    result["refused"] = refused
    if any(item["key"] == "tick" for item in resumed):
        result["wake_armed"] = rearm_tick_wake_channel(ledger_root, resumed, now)
    return result


def cmd_ensure(args):
    registry_dir = Path(args.registry_dir)
    registrations = scan_registry(registry_dir)

    missing = []
    deviations = []
    for entry in INVENTORY:
        match = find_match(entry, registrations)
        if match is None:
            missing.append(entry)
            continue
        path, obj = match
        if obj.get("status") == "paused":
            deviations.append(paused_deviation(registry_dir, entry, path, obj))

    now = resolve_now(args.now)
    auto_recovery = auto_recover_paused_timers(args, registry_dir, deviations, now)
    recovered_keys = {item["key"] for item in auto_recovery["resumed"]}
    if recovered_keys:
        deviations = [d for d in deviations if d["key"] not in recovered_keys]

    if not missing:
        print(json.dumps({"ok": True, "created": [], "deviations": deviations,
                          "auto_recovery": auto_recovery}))
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

    print(json.dumps({"ok": True, "created": created, "deviations": deviations,
                      "auto_recovery": auto_recovery}))


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
        if obj.get("status") == "paused":
            # A paused timer is always a deviation, never a silent
            # active-looking entry (see module docstring's `ensure` entry).
            deviations.append("paused")
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
    if getattr(args, "for_restart", False):
        ledger_cmd.append("--for-restart")
    if getattr(args, "keep_down", False):
        ledger_cmd.append("--keep-down")
    result = subprocess.run(ledger_cmd, capture_output=True, text=True, cwd=REPO_ROOT)
    if result.returncode != 0:
        fail(EXIT_REFUSED, f"teardown-declare failed (rc={result.returncode}): {result.stderr.strip()}")

    declare = json.loads(result.stdout) if result.stdout.strip() else None
    print(json.dumps({"ok": True, "drained": drained, "teardown_declare": declare}))


def channel_collision(entry, registrations, picked_path):
    """Pre-resume safety check (task 20261004-085212): refuse to flip
    `picked_path` to active when some OTHER registration matching the SAME
    inventory entry is already active. `find_match`'s by_key path only ever
    looks at the first match, so it cannot see this on its own -- e.g. a
    stale PAUSED duplicate of the live tick registration, same `name` (and
    therefore the same wake-arm channel_id, since that id is embedded in
    `name`), sitting under a different file/timer id. Resuming the paused
    one in that situation would leave TWO simultaneously-active
    registrations delivering under the identical channel_id, with no way
    for an observer to attribute a fire to either. Returns the list of
    OTHER active registrations (empty list = no collision)."""
    matches = find_all_matches(entry, registrations)
    return [(path, obj) for path, obj in matches
            if path != picked_path and obj.get("status") != "paused"]


def resume_paused_timers(registry_dir, now, targets=None):
    """Shared RESUME_ORDER mutation core (task 20261004-050913): the single
    implementation behind both the `resume` subcommand and `ensure
    --ledger-root`'s auto-recovery path, so a correctness fix is applied
    exactly once and the two call sites can never drift apart (same
    discipline as compute_inbox_drain_staleness in the ledger CLI). Scoped
    to the four-entry INVENTORY only, same as drain's own by_key filter --
    never touches any other *.json file in registry_dir. Idempotent: an
    entry that is missing, or already not paused, is a no-op and is never
    included in the returned list. Each resumed entry carries `name` (not
    just `key`/`id`) so a caller -- notably the ledger CLI's watchdog-check
    self-heal branch -- can derive the tick channel's wake-arm channel id
    from the live registration's name suffix without a second read.

    `targets` (task 20261004-085212; optional, default None = all four):
    restricts which INVENTORY keys are even considered -- an operator who
    wants ONLY the unrelated, days-paused watchdog back can ask for exactly
    that without ever touching tick, sidestepping any collision on a key
    they did not ask for. Keys actually touched still follow RESUME_ORDER
    (filtered to the requested set), never the caller's own order. Before
    flipping any key, channel_collision() re-checks for an already-active
    OTHER registration under the same inventory entry; a hit is reported in
    the second return value (`refused`) and that key is left untouched --
    everything else requested still proceeds."""
    registrations = scan_registry(registry_dir)
    by_key = {}
    for entry in INVENTORY:
        match = find_match(entry, registrations)
        if match is not None:
            by_key[entry["key"]] = match
    entries_by_key = {entry["key"]: entry for entry in INVENTORY}

    order = [k for k in RESUME_ORDER if targets is None or k in targets]
    resumed = []
    refused = []
    for key in order:
        if key not in by_key:
            continue
        path, obj = by_key[key]
        if obj.get("status") != "paused":
            continue
        conflicts = channel_collision(entries_by_key[key], registrations, path)
        if conflicts:
            refused.append({"key": key, "id": path.stem, "reason": "channel_id_collision",
                            "conflicting_ids": [p.stem for p, _ in conflicts]})
            continue
        updated = dict(obj)
        updated["status"] = "active"
        updated["pausedAt"] = None
        updated["updatedAt"] = iso(now)
        try:
            atomic_write_registration(path, updated, backup=True, now=now)
        except TimerWriteValidationError as exc:
            fail(EXIT_REFUSED, str(exc))
        resumed.append({"key": key, "id": path.stem, "name": obj.get("name")})
    return resumed, refused


def cmd_resume(args):
    """Paired with drain: restore paused timers back to active, in
    RESUME_ORDER (the exact reverse of DRAIN_ORDER -- watchdog last). Scoped
    to the four-entry INVENTORY only, same as drain's own by_key filter --
    never touches any other *.json file in --registry-dir. Idempotent: an
    entry that is missing, or already not paused, is a no-op. `--target`
    (repeatable; omit for all four) and the pre-flight channel_id collision
    refusal are documented on resume_paused_timers, this command's thin CLI
    wrapper (see its docstring)."""
    registry_dir = Path(args.registry_dir)
    now = resolve_now(args.now)
    targets = set(args.target) if args.target else None
    resumed, refused = resume_paused_timers(registry_dir, now, targets=targets)
    for item in resumed:
        print(json.dumps({"op": "resume", "key": item["key"], "id": item["id"],
                          "name": item["name"]}))
    for item in refused:
        print(json.dumps({"op": "resume-refused", **item}))
    print(json.dumps({"ok": not refused, "resumed": [item["key"] for item in resumed],
                      "refused": [item["key"] for item in refused]}))
    if refused:
        sys.exit(EXIT_REFUSED)


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
    s.add_argument("--ledger-root", default=None,
                   help="when given, enables the ledger-driven auto-resume path: any "
                        "paused inventory timer is auto-resumed (and the tick wake "
                        "channel re-armed) ONLY when this ledger's latest teardown-declare "
                        "was --for-restart with no --keep-down. Omitting this flag "
                        "reproduces the pre-20261004-050913 behavior exactly: deviations "
                        "are reported, never auto-resolved")
    s.set_defaults(fn=cmd_ensure)

    s = sub.add_parser("status")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("drain")
    s.add_argument("--ledger-root", required=True,
                   help="ledger root for the final teardown-declare call (no default: M6)")
    s.add_argument("--reason", default="paseo-daemon-timers.py drain: scheduled fleet teardown",
                   help="non-empty --reason forwarded to teardown-declare")
    s.add_argument("--for-restart", action="store_true",
                   help="forwarded to teardown-declare verbatim: this drain is ahead of a "
                        "planned daemon restart, authorizing a later ensure/watchdog-check "
                        "auto-resume unless --keep-down is also given")
    s.add_argument("--keep-down", action="store_true",
                   help="forwarded to teardown-declare verbatim: explicit long-term "
                        "deactivation, never auto-resumed")
    s.set_defaults(fn=cmd_drain)

    s = sub.add_parser("resume")
    s.add_argument("--target", action="append", default=None,
                   choices=[entry["key"] for entry in INVENTORY],
                   help="inventory key to resume (repeatable); omit to consider all four. "
                        "Before flipping any key, refuses (EXIT_REFUSED, reported per-key "
                        "under the 'refused' output key, never silently skipped) if another "
                        "registration matching the SAME inventory entry is already active -- "
                        "e.g. a stale paused duplicate sharing the live tick channel's exact "
                        "name/channel_id -- rather than creating two simultaneously-active "
                        "schedules delivering under one channel_id")
    s.set_defaults(fn=cmd_resume)

    return p


def main():
    args = build_parser().parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
