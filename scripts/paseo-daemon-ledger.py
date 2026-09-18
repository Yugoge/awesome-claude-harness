#!/usr/bin/env python3
"""paseo-daemon-ledger.py — SOLE mutation surface for the /paseo-daemon ledger.

Deterministic CLI realizing blueprint F6/F8/F10/F11/F14 local-persistence
invariants for the .claude/paseo-daemon/ runtime state directory (never
committed). Every controller mutation of the ledger maps to a named
subcommand here; ad-hoc direct writes into the ledger directory are
forbidden by commands/paseo-daemon.md. Read-only inspection is allowed.

Usage: paseo-daemon-ledger.py --root <ledger-root> [--now <aware-iso8601>] <subcommand> ...

Subcommands:
  init                         create the documented ledger layout
  lease-acquire / lease-renew / lease-status
  inbox-append / inbox-consume / inbox-ack        (consume->plan->ack, exactly-once)
  action-transition            FSM planned->dispatched->acknowledged->terminal
  reserve                      in_flight reservation record (single-writer)
  account-init / account-block / account-observe-reset / account-canary-result
  classify-error               F8 five-class error-text classification
  usage-ingest                 adapter stdout JSON -> persisted per-account state
  scheduling-decision          (tier, task class) -> dispatch/switch/degrade/stop
  inbox-check-staleness        R1: self-bootstrapping inbox_drain_stale judge
                               (oldest pending by appended_at, no plan, past
                               threshold) persisted into the ledger itself
  wake-arm / wake-observe / wake-status    recurring wake-channel arming state:
                               delivery-proof observations + watermark ageing
  watchdog-check                R1 AC-1.2: ONE Bash call combining wake-status +
                               lease-status + inbox-check-staleness + conditional
                               escalation inbox-append, so the watchdog's full
                               check-and-maybe-escalate sequence stays within the
                               5-consecutive-Bash-call orchestrator-gate budget
  teardown-declare             session-end drain-or-declare teardown record
  recovery-record / recovery-demand / recovery-judge   (resume nonce + AC14 identity)
  dossier-validate             fail-closed schema validation (F12/F13)
  generation-commit / generation-verify           crash-safe generation journal (F14)

Exit codes: 0=success, 1=CLI/usage error, 2=invariant/validation refusal,
            3=naive (timezone-less) timestamp rejected, 9=injected crash (tests only).

All timestamps are timezone-aware UTC (repo defect history:
tests/test_prompt_workflow_liveness_tz.py); naive timestamps are rejected.
The --now flag is the deterministic fake clock used by pytest.
--inject-crash simulates a process death at a named commit point (tests only).
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_REFUSED = 2
EXIT_NAIVE_TS = 3
EXIT_CRASH = 9

MODEL_LADDER = ["fable 5", "opus 5", "sonnet 5"]
TASK_CLASS_BASE_MODEL = {"fast": "sonnet 5", "general": "opus 5", "quality": "fable 5"}
ACCOUNT_STATES = ["unknown", "eligible", "suspect", "blocked_until", "probation"]
ERROR_CLASSES = ["hard_usage_limit", "transient", "auth", "model", "unknown"]
ERROR_CLASS_ACTION = {
    "hard_usage_limit": "account_blocked_until",
    "transient": "retry_backoff_in_place",
    "auth": "escalate_class_5",
    "model": "model_change_same_account",
    "unknown": "mark_suspect",
}
# Usage-tier classification contract (M9): ordered remainingPct thresholds.
# These are tunable knob DEFAULTS (config.json overrides); the contract SHAPE
# (ordered thresholds; unavailable/missing -> unknown) is normative.
DEFAULT_TIER_THRESHOLDS = {"plentiful_min": 50, "near_limit_max": 15, "exhausted_max": 5}
DEFAULT_ACCOUNTS = ["orchestrade", "yugetang", "yugoge"]
# Inbox-drain staleness judge (R1, spec-20260910-164747 AC-1.1): the default
# threshold is proportional to heartbeat_minutes, never a hardcoded absolute
# -- 3 tick periods is long enough that one missed/late tick never
# false-positives, short enough that a genuinely stalled drain (observed
# live: 5+ days silently stalled) is caught well within a day.
INBOX_DRAIN_STALE_TICK_MULTIPLIER = 3


def fail(code, msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def parse_aware(ts, what="timestamp"):
    """Parse an ISO-8601 timestamp; reject naive (timezone-less) values."""
    if not isinstance(ts, str):
        fail(EXIT_NAIVE_TS, f"{what}: not a string: {ts!r}")
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        fail(EXIT_NAIVE_TS, f"{what}: unparseable: {ts!r}")
    if dt.tzinfo is None:
        fail(EXIT_NAIVE_TS, f"{what}: naive (timezone-less) timestamp rejected: {ts!r}")
    return dt.astimezone(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def canonical_dossier_bytes(obj):
    """Canonical serialization used for generation hashing and verification."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")


def atomic_write_json(path, obj):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(tmp, path)


def read_json(path):
    return json.loads(path.read_text())


def journal_append(root, record, now):
    record = dict(record)
    record["at"] = iso(now)
    with (root / "journal.ndjson").open("a") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def maybe_crash(args, point):
    if getattr(args, "inject_crash", None) == point:
        print(f"CRASH-INJECT: simulated process death at {point}", file=sys.stderr)
        sys.exit(EXIT_CRASH)


LAYOUT_DIRS = [
    "inbox/pending", "inbox/plans", "inbox/acked",
    "actions", "reservations", "backlog", "recovery",
    "generations", "dossiers", "sessions",
]


def check_barrier(root):
    """Rehydration barrier (F14/RUNTIME-AC21): while the barrier marker is
    set, every pipeline mutation is refused until barrier-clear attests that
    command spec, dossier current generation, verbatim anchors, AND live
    state have all been reloaded."""
    if (root / "barrier").exists():
        fail(EXIT_REFUSED, "rehydration barrier active: mutations prohibited until "
                           "barrier-clear attests full reload (spec + generation + "
                           "anchors + live state)")


def cmd_init(args, root, now):
    root.mkdir(parents=True, exist_ok=True)
    for d in LAYOUT_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    accounts = [a.strip() for a in args.accounts.split(",") if a.strip()]
    if not accounts:
        fail(EXIT_USAGE, "at least one account name required")
    accounts_path = root / "accounts.json"
    if not accounts_path.exists():
        atomic_write_json(accounts_path, {
            "accounts": {
                name: {
                    "state": "unknown",
                    "weekly_reset_at": None,
                    "blocked_until": None,
                    "tier": "unknown",
                    "usage": None,
                    "observed_at": None,
                } for name in accounts
            }
        })
    config_path = root / "config.json"
    if not config_path.exists():
        atomic_write_json(config_path, {
            "tier_thresholds": DEFAULT_TIER_THRESHOLDS,
            "heartbeat_minutes": 45,
            "stall_threshold_minutes": 30,
            "confirm_window_minutes": 10,
            "max_switches_per_task": 2,
            "min_account_residency_minutes": 30,
            "switch_hysteresis_signals": 2,
            # wake-channel / lease coupling knobs (task 20260831-031316): the
            # defaults satisfy lease_ttl_seconds >= (tolerated_missed_fires+1)
            # x heartbeat_minutes x 60 + wake_slack_minutes x 60 (7200 >= 6300);
            # pre-existing ledgers lack these keys, so every reader uses
            # .get(key, default) fallbacks — never direct-key reads.
            "lease_ttl_seconds": 7200,
            "tolerated_missed_fires": 1,
            "wake_slack_minutes": 15,
            # timezone rule-source verification (M14/M15): same config surface
            # as wake_slack_minutes, never a second configuration path.
            "wake_verify_window_days": WAKE_VERIFY_WINDOW_DEFAULT_DAYS,
            "wake_vendor_node_path": WAKE_VENDOR_NODE_PATH_DEFAULT,
            # R1 (spec-20260910-164747 AC-1.1): default is documented as
            # heartbeat_minutes x INBOX_DRAIN_STALE_TICK_MULTIPLIER (45x3=135);
            # pre-existing ledgers lack this key, so inbox_drain_stale_threshold_minutes()
            # always reads it with the same .get(key, default) fallback as every
            # other wake/lease knob above -- never a direct-key read.
            "inbox_drain_stale_threshold_minutes": 45 * INBOX_DRAIN_STALE_TICK_MULTIPLIER,
            # R1 substate (b) (spec-20260910-164747 AC-1.1, QA close-debate
            # task 20260911-011102 iteration 3 correction): a plan's OWN
            # ack-timeout window, independently tunable from the key above;
            # same default formula and same .get(key, default) fallback.
            "plan_ack_stale_threshold_minutes": 45 * INBOX_DRAIN_STALE_TICK_MULTIPLIER,
        })
    wm = root / "inbox" / "watermark.json"
    if not wm.exists():
        atomic_write_json(wm, {"processed_count": 0, "last_event_id": None})
    journal_append(root, {"op": "init", "accounts": accounts}, now)
    print(json.dumps({"ok": True, "root": str(root)}))


def require_root(root):
    if not (root / "inbox" / "pending").is_dir():
        fail(EXIT_USAGE, f"ledger root not initialized (run init first): {root}")


# ---------------- lease (F6 leader succession) ----------------

def load_config(root):
    """Knob reads tolerate a missing config.json AND missing keys: every new
    knob is read with .get(key, default) so pre-existing ledgers keep working
    (never the read_json(...)["key"] direct-key pattern of cmd_usage_ingest —
    older ledgers lack the wake/lease knobs seeded by newer inits)."""
    path = root / "config.json"
    return read_json(path) if path.exists() else {}


def effective_lease_ttl(args, config):
    if args.ttl_seconds is not None:
        return args.ttl_seconds
    return config.get("lease_ttl_seconds", 3600)


def warn_ttl_cadence_coupling(config, ttl):
    """Lease-safety bound (task 20260831-031316 M6): the TTL must survive
    tolerated_missed_fires lost wake fires plus slack, or one lost fire
    expires the lease and forces a spurious succession (observed live
    2026-08-30: TTL 3600 s at 45-min cadence tolerated zero misses).
    Warning, never an error — existing callers keep working."""
    required = ((config.get("tolerated_missed_fires", 1) + 1)
                * config.get("heartbeat_minutes", 45) * 60
                + config.get("wake_slack_minutes", 15) * 60)
    if ttl < required:
        print(f"WARNING: lease TTL {ttl}s violates the TTL/cadence coupling "
              f"invariant: required >= {required}s = (tolerated_missed_fires+1)"
              f" x heartbeat_minutes x 60 + wake_slack_minutes x 60",
              file=sys.stderr)


def cmd_lease_acquire(args, root, now):
    require_root(root)
    lease_path = root / "lease.json"
    config = load_config(root)
    ttl = effective_lease_ttl(args, config)
    warn_ttl_cadence_coupling(config, ttl)
    if lease_path.exists():
        lease = read_json(lease_path)
        expires = parse_aware(lease["expires_at"], "lease.expires_at")
        if lease["holder"] != args.holder and now < expires:
            fail(EXIT_REFUSED,
                 f"lease held by {lease['holder']} (incarnation {lease['incarnation']}) "
                 f"until {lease['expires_at']}; takeover only after expiry")
        incarnation = lease["incarnation"] + 1
    else:
        incarnation = 1
    atomic_write_json(lease_path, {
        "holder": args.holder,
        "incarnation": incarnation,
        "heartbeat_at": iso(now),
        "expires_at": iso(datetime.fromtimestamp(now.timestamp() + ttl, tz=timezone.utc)),
    })
    journal_append(root, {"op": "lease-acquire", "holder": args.holder, "incarnation": incarnation}, now)
    print(json.dumps({"ok": True, "holder": args.holder, "incarnation": incarnation}))


def cmd_lease_renew(args, root, now):
    require_root(root)
    lease_path = root / "lease.json"
    if not lease_path.exists():
        fail(EXIT_REFUSED, "no lease to renew")
    lease = read_json(lease_path)
    if lease["holder"] != args.holder:
        fail(EXIT_REFUSED, f"lease held by {lease['holder']}, not {args.holder}")
    config = load_config(root)
    ttl = effective_lease_ttl(args, config)
    warn_ttl_cadence_coupling(config, ttl)
    lease["heartbeat_at"] = iso(now)
    lease["expires_at"] = iso(datetime.fromtimestamp(now.timestamp() + ttl, tz=timezone.utc))
    atomic_write_json(lease_path, lease)
    print(json.dumps({"ok": True}))


def cmd_lease_status(args, root, now):
    require_root(root)
    lease_path = root / "lease.json"
    if not lease_path.exists():
        print(json.dumps({"held": False}))
        return
    lease = read_json(lease_path)
    expires = parse_aware(lease["expires_at"], "lease.expires_at")
    print(json.dumps({"held": now < expires, **lease}))


# ---------------- inbox: consume -> plan -> ack, exactly once (F1/F2) ----------------

def cmd_inbox_append(args, root, now):
    require_root(root)
    check_barrier(root)
    pending = root / "inbox" / "pending" / f"{args.event_id}.json"
    acked = root / "inbox" / "acked" / f"{args.event_id}.json"
    if pending.exists() or acked.exists():
        # duplicate event id: processed once — append is an idempotent no-op
        print(json.dumps({"ok": True, "duplicate": True, "event_id": args.event_id}))
        return
    payload = json.loads(args.payload)
    atomic_write_json(pending, {"event_id": args.event_id, "payload": payload, "appended_at": iso(now)})
    journal_append(root, {"op": "inbox-append", "event_id": args.event_id}, now)
    print(json.dumps({"ok": True, "duplicate": False, "event_id": args.event_id}))


def cmd_inbox_consume(args, root, now):
    """Consume the oldest pending event: record its planned outcome atomically.

    Commit point = the atomic rename publishing inbox/plans/<id>.json.
    A crash BEFORE that rename (--inject-crash after-consume) leaves the event
    pending with no plan — the event is re-consumable, never lost.
    If a plan already exists the existing plan is returned (never planned twice).
    """
    require_root(root)
    check_barrier(root)
    pending_dir = root / "inbox" / "pending"
    events = sorted(pending_dir.glob("*.json"))
    if not events:
        print(json.dumps({"ok": True, "consumed": None}))
        return
    event_path = events[0]
    event = read_json(event_path)
    event_id = event["event_id"]
    plan_path = root / "inbox" / "plans" / f"{event_id}.json"
    if plan_path.exists():
        print(json.dumps({"ok": True, "consumed": event_id, "plan": read_json(plan_path), "replayed": True}))
        return
    maybe_crash(args, "after-consume")  # dies BEFORE the plan commit: event stays pending
    plan = {"event_id": event_id, "planned_outcome": args.planned_outcome, "planned_at": iso(now)}
    atomic_write_json(plan_path, plan)  # the commit
    maybe_crash(args, "after-plan")     # dies AFTER plan commit, BEFORE ack: pending+planned
    journal_append(root, {"op": "inbox-consume", "event_id": event_id}, now)
    print(json.dumps({"ok": True, "consumed": event_id, "plan": plan, "replayed": False}))


def rebuild_watermark(root):
    """The ACK record is authoritative; the watermark is DERIVED from the
    acked set so it can always be rebuilt after a crash (codex finding 3)."""
    acked_dir = root / "inbox" / "acked"
    records = [read_json(p) for p in acked_dir.glob("*.json")]
    last = None
    if records:
        last = max(records, key=lambda r: (r.get("acked_at", ""), r["event_id"]))["event_id"]
    atomic_write_json(root / "inbox" / "watermark.json",
                      {"processed_count": len(records), "last_event_id": last})


def cmd_inbox_ack(args, root, now):
    """ACK protocol: (1) write the authoritative acked record (commit point);
    (2) unlink pending; (3) rebuild the derived watermark. Re-ACK repairs
    steps 2-3 idempotently, so a crash between commits can never
    head-of-line-block the inbox or leave the watermark stale."""
    require_root(root)
    check_barrier(root)
    event_id = args.event_id
    pending = root / "inbox" / "pending" / f"{event_id}.json"
    plan_path = root / "inbox" / "plans" / f"{event_id}.json"
    acked = root / "inbox" / "acked" / f"{event_id}.json"
    if acked.exists():
        # idempotent repair: finish the interrupted post-commit steps
        if pending.exists():
            os.unlink(pending)
        rebuild_watermark(root)
        print(json.dumps({"ok": True, "event_id": event_id, "already_acked": True}))
        return
    if not plan_path.exists():
        fail(EXIT_REFUSED, f"event {event_id} has no recorded planned outcome; ACK without plan is forbidden")
    if not pending.exists():
        fail(EXIT_REFUSED, f"event {event_id} is not pending")
    record = read_json(pending)
    record["plan"] = read_json(plan_path)
    record["acked_at"] = iso(now)
    atomic_write_json(acked, record)   # the ACK commit
    maybe_crash(args, "after-acked-write")
    os.unlink(pending)
    maybe_crash(args, "after-pending-unlink")
    rebuild_watermark(root)
    journal_append(root, {"op": "inbox-ack", "event_id": event_id}, now)
    print(json.dumps({"ok": True, "event_id": event_id, "already_acked": False}))


def inbox_drain_stale_threshold_minutes(config):
    """Configurable staleness threshold (AC-1.1). A freshly-inited ledger
    carries the key explicitly (see cmd_init); a pre-existing ledger from
    before this knob existed falls back to heartbeat_minutes x
    INBOX_DRAIN_STALE_TICK_MULTIPLIER -- same .get(key, default) convention
    as every other wake/lease knob (never a direct-key read)."""
    if "inbox_drain_stale_threshold_minutes" in config:
        return config["inbox_drain_stale_threshold_minutes"]
    return config.get("heartbeat_minutes", 45) * INBOX_DRAIN_STALE_TICK_MULTIPLIER


def drain_status_path(root):
    return root / "inbox" / "drain_status.json"


def plan_ack_stale_threshold_minutes(config):
    """Configurable threshold (AC-1.1 substate b) for how long a plan may sit
    un-acked before its OWN timeout is breached -- independent of (and not
    satisfied merely by the existence of a plan under)
    inbox_drain_stale_threshold_minutes above, which only governs the
    no-plan-yet substate. spec-20260910-164747 R1/AC-1.1 documents the same
    default formula (3 x heartbeat_minutes) for this substate as (a)'s; kept
    as its OWN config key (not reusing (a)'s) so the two windows remain
    independently tunable, per the same .get(key, default) convention as
    every other wake/lease/staleness knob (never a direct-key read). A
    ledger that already customized inbox_drain_stale_threshold_minutes but
    predates this key falls back to THAT value (not straight to the raw
    heartbeat formula), so an operator's existing intent carries forward
    instead of being silently overridden by an unrelated default (codex
    review, task 20260911-011102 iteration 3)."""
    if "plan_ack_stale_threshold_minutes" in config:
        return config["plan_ack_stale_threshold_minutes"]
    return inbox_drain_stale_threshold_minutes(config)


def oldest_unplanned_pending(root):
    """Oldest pending event (by its `appended_at` FIELD -- never filename;
    cmd_inbox_consume's `sorted(pending_dir.glob("*.json"))` is a latent
    filename-sort bug, flagged out-of-scope for R1, that this judge must not
    inherit) that has NO `inbox/plans/<id>.json` entry yet -- AC-1.1 substate
    (a) candidate. Scanned independently of oldest_unacked_planned below so
    neither substate can mask the other, per spec-20260910-164747 R1 AC-1.1
    (the two staleness substates must be independently triggerable and
    neither may mask the other). Returns None when no such event exists."""
    pending_dir = root / "inbox" / "pending"
    plans_dir = root / "inbox" / "plans"
    events = []
    for p in pending_dir.glob("*.json"):
        event = read_json(p)
        if not (plans_dir / f"{event['event_id']}.json").exists():
            events.append((parse_aware(event["appended_at"], f"{p.name}.appended_at"), event))
    if not events:
        return None
    events.sort(key=lambda pair: pair[0])
    return events[0]


def oldest_unacked_planned(root):
    """Oldest-by-`planned_at` pending event that HAS an `inbox/plans/` entry
    but is still sitting in `inbox/pending` (inbox-ack removes the pending
    file on commit) -- AC-1.1 substate (b) candidate: a plan can itself age
    past its own timeout without ever progressing to inbox-ack, a state
    transition independent of substate (a). Previously the shipped judge
    treated any existing plan as permanently non-stale (QA close-debate,
    task 20260911-011102); this helper is the fix.

    Excludes events that already have an authoritative `inbox/acked/<id>.json`
    record: cmd_inbox_ack's commit point is the acked write, BEFORE it
    unlinks the pending file (see its `after-acked-write` crash-injection
    point); a crash in that narrow window leaves an event ALREADY acked yet
    still physically present in inbox/pending as cleanup residue, which must
    never be misclassified as `plan_not_acked` (codex review, task
    20260911-011102 iteration 3). Returns None when no such event exists."""
    pending_dir = root / "inbox" / "pending"
    plans_dir = root / "inbox" / "plans"
    acked_dir = root / "inbox" / "acked"
    events = []
    for p in pending_dir.glob("*.json"):
        event = read_json(p)
        event_id = event["event_id"]
        if (acked_dir / f"{event_id}.json").exists():
            continue  # already ACKed; pending file is unlinked cleanup residue
        plan_path = plans_dir / f"{event_id}.json"
        if plan_path.exists():
            plan = read_json(plan_path)
            planned_at = parse_aware(plan["planned_at"], f"{event_id}.planned_at")
            events.append((planned_at, event))
    if not events:
        return None
    events.sort(key=lambda pair: pair[0])
    return events[0]


def compute_inbox_drain_staleness(root, config, now):
    """R1 AC-1.1: the unified `inbox_drain_stale` verdict, covering the two
    independent stale substates spec-20260910-164747 R1 names explicitly --
    (a) `no_plan`: oldest unplanned pending event aged past
    inbox_drain_stale_threshold_minutes; (b) `plan_not_acked`: a plan exists
    for some pending event but has itself aged past
    plan_ack_stale_threshold_minutes without ever progressing to inbox-ack.
    Each is computed from its own independent scan (oldest_unplanned_pending /
    oldest_unacked_planned) so neither can mask the other and both may be
    true at once; `stale_reasons` names whichever fired. Shared verbatim by
    cmd_inbox_check_staleness and cmd_watchdog_check so a correctness fix
    here is applied exactly once, never duplicated or allowed to drift
    between the two call sites."""
    threshold_minutes = inbox_drain_stale_threshold_minutes(config)
    plan_ack_threshold_minutes = plan_ack_stale_threshold_minutes(config)
    result = {
        "checked_at": iso(now),
        "threshold_minutes": threshold_minutes,
        "plan_ack_threshold_minutes": plan_ack_threshold_minutes,
        "inbox_drain_stale": False,
        "stale_reasons": [],
        "oldest_pending_event_id": None,
        "oldest_pending_appended_at": None,
        "age_minutes": None,
        "has_plan": None,
        "oldest_unacked_planned_event_id": None,
        "oldest_unacked_planned_at": None,
        "plan_age_minutes": None,
    }

    unplanned = oldest_unplanned_pending(root)
    unplanned_appended_at = None
    if unplanned is not None:
        unplanned_appended_at, event = unplanned
        age_minutes = (now - unplanned_appended_at).total_seconds() / 60.0
        if age_minutes > threshold_minutes:
            result["stale_reasons"].append("no_plan")

    unacked_planned = oldest_unacked_planned(root)
    unacked_appended_at = None
    if unacked_planned is not None:
        planned_at, planned_event = unacked_planned
        unacked_appended_at = parse_aware(planned_event["appended_at"],
                                           f"{planned_event['event_id']}.appended_at")
        plan_age_minutes = (now - planned_at).total_seconds() / 60.0
        result.update({
            "oldest_unacked_planned_event_id": planned_event["event_id"],
            "oldest_unacked_planned_at": iso(planned_at),
            "plan_age_minutes": round(plan_age_minutes, 6),
        })
        if plan_age_minutes > plan_ack_threshold_minutes:
            result["stale_reasons"].append("plan_not_acked")

    # The legacy oldest_pending_event_id/age_minutes/has_plan fields must
    # name the TRUE oldest-by-appended_at pending event across BOTH
    # candidates -- not unconditionally prefer the unplanned one -- so
    # journal/escalation evidence never cites a younger event while an
    # older planned-but-unacked one is what actually triggered the verdict
    # (codex review, task 20260911-011102 iteration 3).
    if unplanned is not None and (unacked_planned is None or unplanned_appended_at <= unacked_appended_at):
        _, event = unplanned
        result.update({
            "oldest_pending_event_id": event["event_id"],
            "oldest_pending_appended_at": iso(unplanned_appended_at),
            "age_minutes": round((now - unplanned_appended_at).total_seconds() / 60.0, 6),
            "has_plan": False,
        })
    elif unacked_planned is not None:
        _, planned_event = unacked_planned
        result.update({
            "oldest_pending_event_id": planned_event["event_id"],
            "oldest_pending_appended_at": iso(unacked_appended_at),
            "age_minutes": round((now - unacked_appended_at).total_seconds() / 60.0, 6),
            "has_plan": True,
        })

    result["inbox_drain_stale"] = bool(result["stale_reasons"])
    return result


def cmd_inbox_check_staleness(args, root, now):
    """R1 (spec-20260910-164747 AC-1.1): consume->plan->ack (Step 3 of the
    Tick loop) is specified as an ordinary step INSIDE the same loop it is
    meant to protect -- a step embedded inside a loop cannot, by
    construction, detect that same loop silently failing to run it (measured
    live: watermark frozen 5+ days, zero alarm). This judge is the
    independent, self-bootstrapping check: it persists its verdict into the
    ledger itself (inbox/drain_status.json), queryable without any external
    monitor, so AC-1.2's watchdog (a schedule outside the main tick loop)
    can read it even when the tick loop is the thing that stopped. Covers
    BOTH AC-1.1 substates (no_plan, plan_not_acked) via
    compute_inbox_drain_staleness -- see that function for the substate
    definitions the previous revision only covered the first of (QA
    close-debate, task 20260911-011102)."""
    require_root(root)
    check_barrier(root)
    config = load_config(root)
    result = compute_inbox_drain_staleness(root, config, now)
    atomic_write_json(drain_status_path(root), result)
    journal_append(root, {"op": "inbox-check-staleness",
                          "inbox_drain_stale": result["inbox_drain_stale"],
                          "stale_reasons": result["stale_reasons"],
                          "oldest_pending_event_id": result["oldest_pending_event_id"],
                          "age_minutes": result["age_minutes"]}, now)
    print(json.dumps({"ok": True, **result}))


# ---------------- action FSM + idempotency key (F11) ----------------

FSM_ORDER = ["planned", "dispatched", "acknowledged", "terminal"]


def cmd_action_transition(args, root, now):
    require_root(root)
    check_barrier(root)
    key = f"{args.logical_session}__{args.phase}__{args.attempt}"
    path = root / "actions" / f"{key}.json"
    target = args.to
    if target not in FSM_ORDER:
        fail(EXIT_USAGE, f"unknown state {target}")
    if path.exists():
        rec = read_json(path)
        cur = rec["state"]
        if cur == "terminal":
            fail(EXIT_REFUSED, f"action {key} is terminal and immutable")
        if target == "dispatched" and FSM_ORDER.index(cur) >= FSM_ORDER.index("dispatched"):
            fail(EXIT_REFUSED,
                 f"idempotency key ({args.logical_session}, {args.phase}, {args.attempt}) "
                 f"already {cur}: dispatched-but-not-terminal is never re-sent")
        # exact-successor discipline (codex finding 10): no skipped edges
        if FSM_ORDER.index(target) != FSM_ORDER.index(cur) + 1:
            fail(EXIT_REFUSED, f"illegal transition {cur} -> {target}: exact successor required")
    else:
        if target != "planned":
            fail(EXIT_REFUSED, f"action must start at planned, not {target}")
        rec = {"logical_session": args.logical_session, "phase": args.phase,
               "attempt": args.attempt, "state": None, "history": []}
    rec["state"] = target
    rec["history"].append({"state": target, "at": iso(now)})
    if target == "terminal":
        if not args.evidence:
            fail(EXIT_REFUSED,
                 "terminal requires machine-readable evidence (completion report / QA verdict / "
                 "close artifact); idle or a finish notification alone never completes")
        rec["evidence"] = args.evidence
    atomic_write_json(path, rec)
    journal_append(root, {"op": "action-transition", "key": key, "to": target}, now)
    print(json.dumps({"ok": True, "key": key, "state": target}))


def cmd_reserve(args, root, now):
    require_root(root)
    check_barrier(root)
    path = root / "reservations" / f"{args.reservation_id}.json"
    if path.exists():
        fail(EXIT_REFUSED, f"reservation {args.reservation_id} already in_flight")
    # probation is single-concurrency (M8): one active canary reservation only
    data = load_accounts(root)
    acc = get_account(data, args.account)
    if acc["state"] == "probation":
        active = [p for p in (root / "reservations").glob("*.json")
                  if read_json(p).get("account") == args.account
                  and read_json(p).get("state") == "in_flight"]
        if active:
            fail(EXIT_REFUSED, f"account {args.account} is in single-concurrency probation "
                               f"and already has an in_flight reservation")
    atomic_write_json(path, {
        "reservation_id": args.reservation_id,
        "account": args.account,
        "logical_session": args.logical_session,
        "state": "in_flight",
        "reserved_at": iso(now),
    })
    journal_append(root, {"op": "reserve", "reservation_id": args.reservation_id, "account": args.account}, now)
    print(json.dumps({"ok": True}))


# ---------------- accounts: state machine + probation (F7/F8) ----------------

def load_accounts(root):
    return read_json(root / "accounts.json")


def save_accounts(root, data):
    atomic_write_json(root / "accounts.json", data)


def get_account(data, name):
    if name not in data["accounts"]:
        fail(EXIT_USAGE, f"unknown account {name}")
    return data["accounts"][name]


def cmd_account_init(args, root, now):
    require_root(root)
    data = load_accounts(root)
    acc = get_account(data, args.account)
    reset_at = parse_aware(args.weekly_reset, "weekly_reset")
    acc["weekly_reset_at"] = iso(reset_at)
    if acc["state"] == "unknown":
        acc["state"] = "eligible"
    save_accounts(root, data)
    journal_append(root, {"op": "account-init", "account": args.account, "weekly_reset_at": iso(reset_at)}, now)
    print(json.dumps({"ok": True, "account": args.account, "state": acc["state"]}))


def cmd_account_block(args, root, now):
    require_root(root)
    check_barrier(root)
    data = load_accounts(root)
    acc = get_account(data, args.account)
    until = parse_aware(args.until, "until")
    acc["state"] = "blocked_until"
    acc["blocked_until"] = iso(until)
    save_accounts(root, data)
    journal_append(root, {"op": "account-block", "account": args.account, "until": iso(until)}, now)
    print(json.dumps({"ok": True, "account": args.account, "state": "blocked_until"}))


def cmd_account_observe_reset(args, root, now):
    """Reset-instant sweep: ONLY an account whose own reset instant (or
    blocked_until) has passed moves to single-concurrency probation."""
    require_root(root)
    data = load_accounts(root)
    moved = []
    for name, acc in data["accounts"].items():
        if acc["state"] != "blocked_until":
            continue
        gate = acc.get("blocked_until") or acc.get("weekly_reset_at")
        if gate is None:
            continue
        if now >= parse_aware(gate, f"{name} reset gate"):
            acc["state"] = "probation"
            acc["probation_concurrency"] = 1
            moved.append(name)
    save_accounts(root, data)
    journal_append(root, {"op": "account-observe-reset", "moved": moved}, now)
    print(json.dumps({"ok": True, "moved_to_probation": moved}))


def cmd_account_canary_result(args, root, now):
    require_root(root)
    data = load_accounts(root)
    acc = get_account(data, args.account)
    if acc["state"] != "probation":
        fail(EXIT_REFUSED, f"account {args.account} is {acc['state']}, not probation; "
                           f"eligible requires a recorded probation success")
    if args.result == "success":
        acc["state"] = "eligible"
        acc["blocked_until"] = None
        acc.pop("probation_concurrency", None)
    else:
        # failure: re-block until the NEXT weekly reset STRICTLY after now —
        # advance whole weekly periods so multi-week downtime cannot busy-loop
        # (codex finding 18)
        nxt = acc.get("weekly_reset_at")
        if nxt:
            gate = parse_aware(nxt, "weekly_reset_at")
            while gate <= now:
                gate = datetime.fromtimestamp(gate.timestamp() + 7 * 86400, tz=timezone.utc)
            nxt = iso(gate)
            acc["weekly_reset_at"] = nxt
        acc["state"] = "blocked_until"
        acc["blocked_until"] = nxt
    save_accounts(root, data)
    journal_append(root, {"op": "account-canary-result", "account": args.account,
                          "result": args.result, "state": acc["state"]}, now)
    print(json.dumps({"ok": True, "account": args.account, "state": acc["state"]}))


# ---------------- F8 error classification ----------------

ERROR_PATTERNS = [
    # The CJK alternation below (limit/quota phrases in Chinese) is a FUNCTIONAL
    # input matcher: platform quota-limit errors can surface in Chinese, and
    # dropping that branch would misclassify them as "unknown" instead of
    # hard_usage_limit. Exempt from Standard 6 (english-only) as pattern DATA,
    # not prose — see the functional input-matcher exemption in
    # agents/style-inspector.md (authoring cycle: task-id 20260829-104922,
    # close flip F2 for cycle 20260828-112025).
    ("hard_usage_limit", re.compile(r"usage limit|hard limit|quota exhausted|out of quota|限额|额度已用完", re.I)),
    ("transient", re.compile(r"\b429\b|\b529\b|timeout|timed out|overloaded|temporarily", re.I)),
    ("auth", re.compile(r"auth|unauthorized|forbidden|invalid.*key|credential|\b401\b|\b403\b", re.I)),
    ("model", re.compile(r"model.*(not (found|exist|available)|unknown)|unknown model|no such model", re.I)),
]


def classify_error_text(text):
    for cls, pat in ERROR_PATTERNS:
        if pat.search(text):
            return cls
    return "unknown"


def cmd_classify_error(args, root, now):
    """Classify an error text into the five F8 classes. With --account, the
    account-state consequence is PERSISTED (codex finding 4): hard_usage_limit
    blocks the account until its reset instant; unknown marks it suspect.
    transient/auth/model do not change account state (retry-in-place /
    class-5 escalation / model-change are dispatch-time behaviors)."""
    cls = classify_error_text(args.text)
    result = {"class": cls, "action": ERROR_CLASS_ACTION[cls]}
    if args.account:
        require_root(root)
        check_barrier(root)
        data = load_accounts(root)
        acc = get_account(data, args.account)
        if cls == "hard_usage_limit":
            acc["state"] = "blocked_until"
            acc["blocked_until"] = acc.get("weekly_reset_at")
            result["account_state"] = "blocked_until"
        elif cls == "unknown":
            acc["state"] = "suspect"
            result["account_state"] = "suspect"
        save_accounts(root, data)
        journal_append(root, {"op": "classify-error", "account": args.account,
                              "class": cls}, now)
    print(json.dumps(result))


# ---------------- usage ingest + tier classification (M8/M9/M18) ----------------

def account_from_provider(provider_id, display_name, known_accounts):
    """Account identity: providerId PRIMARY (claude / claude-<account>), display
    label containing the account name as the tie-breaker for the bare id.
    Label punctuation is non-normative."""
    if provider_id.startswith("claude-"):
        candidate = provider_id[len("claude-"):]
        return candidate if candidate in known_accounts else None
    if provider_id == "claude":
        label = display_name or ""
        for name in known_accounts:
            if name in label:
                return name
    return None


def classify_tier(remaining_pct, status, thresholds, hard_limit=False):
    if status != "available" or remaining_pct is None:
        return "unknown"
    if hard_limit or remaining_pct <= thresholds["exhausted_max"]:
        return "exhausted"
    if remaining_pct <= thresholds["near_limit_max"]:
        return "near_limit"
    if remaining_pct >= thresholds["plentiful_min"]:
        return "plentiful"
    return "normal"


def cmd_usage_ingest(args, root, now):
    """Ingest adapter stdout JSON (providers[] from provider.usage.list.response).

    A row with status != available, or a missing account row, IS the fetcher
    blind window: that account's tier becomes `unknown` (amended RUNTIME-AC07).
    Ingest NEVER changes eligibility state on a blind-window artifact — no
    account switch is ever triggered by unavailable/missing readings alone.
    """
    require_root(root)
    raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text()
    providers = json.loads(raw)
    if isinstance(providers, dict):
        providers = providers.get("providers", [])
    data = load_accounts(root)
    thresholds = read_json(root / "config.json")["tier_thresholds"]
    known = list(data["accounts"].keys())
    seen = set()
    for row in providers:
        account = account_from_provider(row.get("providerId", ""), row.get("displayName", ""), known)
        if account is None:
            continue
        seen.add(account)
        acc = data["accounts"][account]
        status = row.get("status")
        weekly = next((w for w in row.get("windows", []) if w.get("id") == "weekly"), None)
        remaining = weekly.get("remainingPct") if weekly else None
        acc["usage"] = {
            "providerId": row.get("providerId"),
            "status": status,
            "windows": row.get("windows", []),
        }
        acc["tier"] = classify_tier(remaining, status, thresholds)
        acc["observed_at"] = iso(now)
        if weekly and weekly.get("resetsAt"):
            acc["weekly_reset_at"] = iso(parse_aware(weekly["resetsAt"], "resetsAt"))
    for name in known:
        if name not in seen:  # missing account row = blind window -> unknown tier
            data["accounts"][name]["tier"] = "unknown"
            data["accounts"][name]["observed_at"] = iso(now)
    save_accounts(root, data)
    # ingested = accounts with a usable (available) reading; unavailable rows
    # and missing rows are BOTH the fetcher blind window (tier unknown)
    ingested = sorted(n for n in known if data["accounts"][n]["tier"] != "unknown")
    blind = sorted(n for n in known if data["accounts"][n]["tier"] == "unknown")
    journal_append(root, {"op": "usage-ingest", "ingested": ingested, "blind_window": blind}, now)
    print(json.dumps({"ok": True, "ingested": ingested, "blind_window": blind}))


def degrade(model):
    i = MODEL_LADDER.index(model)
    return MODEL_LADDER[min(i + 1, len(MODEL_LADDER) - 1)]


def cmd_scheduling_decision(args, root, now):
    """Deterministic scheduling decision (M9 classification contract).

    Inputs: persisted account tier + task class. Output: one decision object.
    Account rotation and model degradation stay INDEPENDENT decisions: a hard
    usage limit / exhausted tier is NEVER resolved by same-account degrade.
    """
    require_root(root)
    data = load_accounts(root)
    acc = get_account(data, args.account)
    tier = acc.get("tier", "unknown")
    task_class = args.task_class
    base = TASK_CLASS_BASE_MODEL[task_class]
    state = acc.get("state", "unknown")
    # Eligibility state gates the decision BEFORE the usage tier (codex
    # finding 4): a hard-blocked account must never dispatch, even when a
    # stale reading still says plentiful.
    if state == "blocked_until":
        print(json.dumps({"account": args.account, "tier": tier, "task_class": task_class,
                          "state": state, "action": "stop_or_switch", "model": None,
                          "same_account_degrade_forbidden": True}))
        return
    if state == "suspect":
        print(json.dumps({"account": args.account, "tier": tier, "task_class": task_class,
                          "state": state, "action": "hold_conservative", "model": None,
                          "switch_account": False}))
        return
    # Ladder degradation as tiers tighten (user verbatim: fable 5 -> opus 5 ->
    # sonnet 5). normal tier degrades quality work one step; near_limit
    # degrades one further step from the normal-tier model.
    model_at_normal = degrade(base) if task_class == "quality" else base
    decision = {"account": args.account, "tier": tier, "task_class": task_class,
                "state": state}
    if state == "probation":
        decision["probation_single_concurrency"] = True
    if tier == "unknown":
        # fetcher blind window: conservative — no new heavy dispatch, NO switch
        decision.update({"action": "hold_conservative", "model": None, "switch_account": False})
    elif tier == "exhausted":
        # out of quota: stop dispatching or switch account — never burn to hard
        # cutoff, never same-account degrade alone
        decision.update({"action": "stop_or_switch", "model": None,
                         "same_account_degrade_forbidden": True})
    elif tier == "near_limit":
        # proactive boundary switch OR degrade — both remain independent choices
        decision.update({"action": "switch_or_degrade", "model": degrade(model_at_normal),
                         "switch_boundary_only": True})
    elif tier == "plentiful":
        decision.update({"action": "dispatch", "model": base})
    else:  # normal
        decision.update({"action": "dispatch", "model": model_at_normal})
    print(json.dumps(decision))


# ---------------- recovery: nonce + reset-instant gate + AC14 identity ----------------

def recovery_path(root, session):
    return root / "recovery" / f"{session}.json"


def cmd_recovery_record(args, root, now):
    require_root(root)
    check_barrier(root)
    ids = [x.strip() for x in args.original_agent_ids.split(",") if x.strip()]
    if not ids:
        fail(EXIT_USAGE, "at least one original agent id required")
    path = recovery_path(root, args.session)
    if path.exists():
        fail(EXIT_REFUSED, f"recovery record for {args.session} already exists")
    atomic_write_json(path, {
        "session": args.session,
        "account": args.account,
        "original_agent_ids": ids,
        "last_confirmed_artifact": args.last_artifact,
        "nonce": f"resume-{args.session}",
        "nonce_consumed": False,
        "dispatches": 0,
        "sent_marker": None,
        "queued_demands": 0,
        "escalation": {
            "class": 5,
            "reason": "in-session subagent quota interrupt: human-only /restart domain; "
                      "controller never self-services the recovery",
        },
        "recorded_at": iso(now),
    })
    journal_append(root, {"op": "recovery-record", "session": args.session,
                          "original_agent_ids": ids, "escalation_class": 5}, now)
    print(json.dumps({"ok": True, "session": args.session, "escalation_class": 5}))


def cmd_recovery_demand(args, root, now):
    """RESET-INSTANT GATE: the one-shot resume nonce is consumed ONLY after the
    account's reset instant / reliable nextEligibleAt has PASSED. A pre-reset
    demand stays queued: zero dispatches, no sent-marker, nonce unchanged."""
    require_root(root)
    check_barrier(root)
    path = recovery_path(root, args.session)
    if not path.exists():
        fail(EXIT_USAGE, f"no recovery record for {args.session}")
    rec = read_json(path)
    data = load_accounts(root)
    acc = get_account(data, rec["account"])
    gate = acc.get("blocked_until") or acc.get("weekly_reset_at")
    if gate is None:
        # FAIL CLOSED (codex finding 7): no reliable reset instant /
        # nextEligibleAt means the gate CANNOT be confirmed passed — the
        # demand stays queued as a class-5 blockage; the nonce is untouched.
        rec["queued_demands"] += 1
        atomic_write_json(path, rec)
        journal_append(root, {"op": "recovery-demand", "session": args.session,
                              "status": "queued_no_reliable_gate", "escalation_class": 5}, now)
        print(json.dumps({"status": "queued_no_reliable_gate", "escalation_class": 5,
                          "dispatches": rec["dispatches"], "sent_marker": rec["sent_marker"],
                          "nonce_consumed": rec["nonce_consumed"]}))
        return
    if now < parse_aware(gate, "reset gate"):
        rec["queued_demands"] += 1
        atomic_write_json(path, rec)
        journal_append(root, {"op": "recovery-demand", "session": args.session, "status": "queued_pre_reset"}, now)
        print(json.dumps({"status": "queued_pre_reset", "dispatches": rec["dispatches"],
                          "sent_marker": rec["sent_marker"], "nonce_consumed": rec["nonce_consumed"]}))
        return
    if rec["nonce_consumed"]:
        print(json.dumps({"status": "nonce_already_consumed", "dispatches": rec["dispatches"]}))
        return
    rec["nonce_consumed"] = True
    rec["dispatches"] += 1
    rec["sent_marker"] = iso(now)
    atomic_write_json(path, rec)
    journal_append(root, {"op": "recovery-demand", "session": args.session, "status": "dispatched"}, now)
    print(json.dumps({"status": "dispatched", "dispatches": rec["dispatches"],
                      "nonce_consumed": True}))


def cmd_recovery_judge(args, root, now):
    """RUNTIME-AC14: recovery identity is judged against the PERSISTED
    pre-interruption original agent ID set — response evidence from every
    original ID, exact set. Replacement IDs or outer-session-only evidence
    are judged failure."""
    require_root(root)
    path = recovery_path(root, args.session)
    if not path.exists():
        fail(EXIT_USAGE, f"no recovery record for {args.session}")
    rec = read_json(path)
    original = set(rec["original_agent_ids"])
    evidence = set(json.loads(args.evidence))
    missing = sorted(original - evidence)
    unexpected = sorted(evidence - original)
    recovered = not missing and not unexpected
    verdict = {
        "session": args.session,
        "recovered": recovered,
        "original_agent_ids": sorted(original),
        "evidence_ids": sorted(evidence),
        "missing_original_ids": missing,
        "unexpected_ids": unexpected,
    }
    print(json.dumps(verdict))
    sys.exit(EXIT_OK if recovered else EXIT_REFUSED)


# ---------------- dossier validation + generation journal (F12/F13/F14) ----------------

def default_schema_path():
    """The canonical registered schema. Publication is PINNED to it — no
    caller override exists, so a permissive schema can never bypass the
    fail-closed validation (codex finding 14)."""
    return Path(__file__).resolve().parent.parent / "schemas" / "paseo-dossier.v1.json"


def semantic_ts_errors(dossier):
    """Reject impossible/naive timestamps the schema regex cannot catch
    (codex finding 15): every known timestamp field must parse as a real,
    timezone-aware instant."""
    errs = []

    def chk(val, where):
        try:
            dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        except ValueError:
            errs.append(f"{where}: not a real timestamp: {val!r}")
            return
        if dt.tzinfo is None:
            errs.append(f"{where}: naive timestamp rejected")

    ew = dossier.get("event_watermark", {})
    if isinstance(ew, dict) and "observed_at" in ew:
        chk(ew["observed_at"], "event_watermark/observed_at")
    for i, se in enumerate(dossier.get("side_effects", []) or []):
        if isinstance(se, dict) and "at" in se:
            chk(se["at"], f"side_effects/{i}/at")
    vz = dossier.get("verbatim_zone", {})
    for i, e in enumerate((vz.get("entries", []) if isinstance(vz, dict) else []) or []):
        if isinstance(e, dict) and "ts" in e:
            chk(e["ts"], f"verbatim_zone/entries/{i}/ts")
    for i, r in enumerate(dossier.get("decision_journal", []) or []):
        if isinstance(r, dict) and "time" in r:
            chk(r["time"], f"decision_journal/{i}/time")
    return errs


def validate_dossier(dossier_path):
    import jsonschema
    schema = read_json(default_schema_path())
    try:
        dossier = read_json(Path(dossier_path))
    except (json.JSONDecodeError, OSError) as exc:
        return [f"dossier unreadable: {exc}"]
    validator = jsonschema.Draft202012Validator(schema)
    errors = [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
              for e in validator.iter_errors(dossier)]
    if not errors:
        errors = semantic_ts_errors(dossier)
    return errors


def cmd_dossier_validate(args, root, now):
    errors = validate_dossier(args.file)
    if errors:
        for e in errors:
            print(f"INVALID: {e}", file=sys.stderr)
        sys.exit(EXIT_REFUSED)
    print(json.dumps({"ok": True, "valid": True}))


def verbatim_prefix_ok(prev_entries, new_entries):
    """Verbatim zone is append-only across generations (F13): the previous
    entries must be a byte-identical prefix of the new entries."""
    return len(new_entries) >= len(prev_entries) and new_entries[:len(prev_entries)] == prev_entries


def journal_prefix_ok(prev_records, new_records):
    """Decision journal is append-only across generations, with the ONLY
    permitted in-place change being a status supersession
    (active -> superseded/reversed)."""
    if len(new_records) < len(prev_records):
        return False
    for old_rec, new_rec in zip(prev_records, new_records):
        o, n = dict(old_rec), dict(new_rec)
        o_status, n_status = o.pop("status", None), n.pop("status", None)
        if o != n:
            return False
        if o_status != n_status and not (
                o_status == "active" and n_status in ("superseded", "reversed")):
            return False
    return True


def current_generation(root):
    cur = root / "generations" / "current"
    if not cur.exists():
        return None
    return int(cur.read_text().strip())


def cmd_generation_commit(args, root, now):
    """Crash-safe generation commit (F14):
    1. fail-closed dossier validation — an invalid dossier writes NOTHING;
    2. write generations/<n>.json.partial (crash point: after-write);
    3. atomic rename to generations/<n>.json + hash re-verify;
    4. write generations/<n>.committed marker (crash point: after-rename fires
       before this);
    5. atomic current-pointer switch (crash point: before-pointer fires
       before this) — the previous valid generation stays current until here.
    """
    require_root(root)
    check_barrier(root)
    errors = validate_dossier(args.dossier)
    if errors:
        for e in errors:
            print(f"INVALID: {e}", file=sys.stderr)
        print("REFUSED: invalid dossier publishes no generation", file=sys.stderr)
        sys.exit(EXIT_REFUSED)
    dossier_obj = read_json(Path(args.dossier))
    digest = sha256_bytes(canonical_dossier_bytes(dossier_obj))
    parent = current_generation(root)
    gen_dir = root / "generations"
    # Cross-generation append-only invariants (F13/F14, codex finding 13):
    # judged against the CURRENT generation's dossier before anything is written.
    if parent is not None:
        prev = read_json(gen_dir / f"{parent}.json")["dossier"]
        prev_vz = prev.get("verbatim_zone", {}).get("entries", [])
        new_vz = dossier_obj.get("verbatim_zone", {}).get("entries", [])
        if not verbatim_prefix_ok(prev_vz, new_vz):
            fail(EXIT_REFUSED, "verbatim zone is append-only: previous entries must be "
                               "a byte-identical prefix of the new entries")
        if not journal_prefix_ok(prev.get("decision_journal", []),
                                 dossier_obj.get("decision_journal", [])):
            fail(EXIT_REFUSED, "decision journal is append-only: records may only be "
                               "appended, or superseded in place (active -> superseded/reversed)")
        prev_wm = prev.get("event_watermark", {}).get("processed_count", 0)
        new_wm = dossier_obj.get("event_watermark", {}).get("processed_count", 0)
        if new_wm < prev_wm:
            fail(EXIT_REFUSED, f"event watermark must be monotonic: {new_wm} < {prev_wm}")
    # Generation allocation (codex finding 11): never reuse or overwrite an
    # existing final generation — allocate above the maximum on disk, so a
    # committed-but-unpointed generation from a pre-pointer crash is retained.
    existing = [int(p.stem) for p in gen_dir.glob("*.json") if p.stem.isdigit()]
    gen = max(existing + [parent or 0]) + 1
    wm = read_json(root / "inbox" / "watermark.json")
    record = {
        "generation": gen,
        "parent": parent,
        "source_watermark": wm,
        "sha256": digest,
        "dossier": dossier_obj,
        "written_at": iso(now),
    }
    final = gen_dir / f"{gen}.json"
    if final.exists():
        fail(EXIT_REFUSED, f"generation {gen} already exists; final generations are never overwritten")
    partial = gen_dir / f"{gen}.json.partial"
    partial.write_text(json.dumps(record, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    maybe_crash(args, "after-write")      # partial only: not in the generation set
    os.replace(partial, final)
    # actual re-hash of the reread dossier content (codex finding 12), not a
    # mere stored-field comparison
    reread = read_json(final)
    if sha256_bytes(canonical_dossier_bytes(reread["dossier"])) != digest:
        fail(EXIT_REFUSED, "hash re-verification after write failed")
    maybe_crash(args, "after-rename")     # committed marker + pointer both absent
    (gen_dir / f"{gen}.committed").write_text(digest + "\n")
    maybe_crash(args, "before-pointer")   # marker present, prior generation still current
    tmp = gen_dir / "current.tmp"
    tmp.write_text(str(gen) + "\n")
    os.replace(tmp, gen_dir / "current")  # atomic pointer switch
    journal_append(root, {"op": "generation-commit", "generation": gen, "sha256": digest}, now)
    print(json.dumps({"ok": True, "generation": gen, "sha256": digest}))


def cmd_generation_verify(args, root, now):
    require_root(root)
    gen = args.generation if args.generation is not None else current_generation(root)
    if gen is None:
        fail(EXIT_REFUSED, "no committed generation")
    final = root / "generations" / f"{gen}.json"
    marker = root / "generations" / f"{gen}.committed"
    if not final.exists() or not marker.exists():
        fail(EXIT_REFUSED, f"generation {gen} incomplete (file or committed marker missing)")
    rec = read_json(final)
    actual = sha256_bytes(canonical_dossier_bytes(rec["dossier"]))
    recorded = rec["sha256"]
    if actual != recorded:
        fail(EXIT_REFUSED, f"generation {gen} hash mismatch: content {actual} != recorded {recorded}")
    marker_hash = marker.read_text().strip()
    if marker_hash != recorded:
        fail(EXIT_REFUSED, f"generation {gen} committed-marker hash mismatch")
    if args.expect_sha256 and args.expect_sha256 != recorded:
        fail(EXIT_REFUSED, f"generation {gen} hash mismatch: recorded {recorded}, expected {args.expect_sha256}")
    print(json.dumps({"ok": True, "generation": gen, "sha256": recorded}))


# ---------------- co-drive intents, session flags, dossier publication,
# ---------------- rehydration barrier (codex finding 1: every state the
# ---------------- command mandates is reachable through the sole surface)

INTENT_OUTCOMES = ["applied", "superseded", "preempted", "discarded"]


def cmd_intent_queue(args, root, now):
    """F3 co-drive: a controller intent observed during a user turn is queued
    in the durable backlog with its observed_state."""
    require_root(root)
    check_barrier(root)
    path = root / "backlog" / f"{args.intent_id}.json"
    if path.exists():
        fail(EXIT_REFUSED, f"intent {args.intent_id} already exists")
    atomic_write_json(path, {
        "intent_id": args.intent_id,
        "session": args.session,
        "payload": json.loads(args.payload),
        "observed_state": args.observed_state,
        "status": "queued",
        "queued_at": iso(now),
    })
    journal_append(root, {"op": "intent-queue", "intent_id": args.intent_id}, now)
    print(json.dumps({"ok": True, "intent_id": args.intent_id, "status": "queued"}))


def cmd_intent_resolve(args, root, now):
    require_root(root)
    check_barrier(root)
    path = root / "backlog" / f"{args.intent_id}.json"
    if not path.exists():
        fail(EXIT_USAGE, f"unknown intent {args.intent_id}")
    rec = read_json(path)
    if rec["status"] != "queued":
        fail(EXIT_REFUSED, f"intent {args.intent_id} already terminal ({rec['status']})")
    rec["status"] = args.outcome
    rec["resolved_at"] = iso(now)
    atomic_write_json(path, rec)
    journal_append(root, {"op": "intent-resolve", "intent_id": args.intent_id,
                          "outcome": args.outcome}, now)
    print(json.dumps({"ok": True, "intent_id": args.intent_id, "status": args.outcome}))


def cmd_session_flag(args, root, now):
    """F4/F10 per-session flags: SUSPECT persists active_turn_id + observed
    updateCount + suspect_since; switch_pending records a mid-run switch
    demand; clear removes the flag."""
    require_root(root)
    check_barrier(root)
    path = root / "sessions" / f"{args.session}.json"
    rec = read_json(path) if path.exists() else {"session": args.session}
    if args.flag == "suspect":
        if args.turn_id is None or args.update_count is None:
            fail(EXIT_USAGE, "suspect requires --turn-id and --update-count")
        rec["suspect"] = {"active_turn_id": args.turn_id,
                          "update_count": args.update_count,
                          "suspect_since": iso(now)}
    elif args.flag == "switch_pending":
        rec["switch_pending"] = {"since": iso(now)}
    else:  # clear
        rec.pop("suspect", None)
        rec.pop("switch_pending", None)
    atomic_write_json(path, rec)
    journal_append(root, {"op": "session-flag", "session": args.session,
                          "flag": args.flag}, now)
    print(json.dumps({"ok": True, "session": args.session, "flag": args.flag}))


def cmd_dossier_write(args, root, now):
    """F12 dossier publication through the sole mutation surface: the sidecar
    must validate fail-closed BEFORE either file lands in dossiers/."""
    require_root(root)
    check_barrier(root)
    errors = validate_dossier(args.sidecar_file)
    if errors:
        for e in errors:
            print(f"INVALID: {e}", file=sys.stderr)
        fail(EXIT_REFUSED, "invalid sidecar publishes no dossier")
    md_src = Path(args.md_file)
    if not md_src.is_file():
        fail(EXIT_USAGE, f"markdown dossier not found: {md_src}")
    dest_md = root / "dossiers" / f"{args.session}.md"
    dest_json = root / "dossiers" / f"{args.session}.json"
    tmp_md = dest_md.with_name(dest_md.name + ".tmp")
    tmp_md.write_text(md_src.read_text())
    os.replace(tmp_md, dest_md)
    tmp_json = dest_json.with_name(dest_json.name + ".tmp")
    tmp_json.write_text(Path(args.sidecar_file).read_text())
    os.replace(tmp_json, dest_json)
    journal_append(root, {"op": "dossier-write", "session": args.session}, now)
    print(json.dumps({"ok": True, "session": args.session,
                      "md": str(dest_md), "sidecar": str(dest_json)}))


def cmd_barrier_enter(args, root, now):
    require_root(root)
    (root / "barrier").write_text(json.dumps({"entered_at": iso(now)}) + "\n")
    journal_append(root, {"op": "barrier-enter"}, now)
    print(json.dumps({"ok": True, "barrier": "active"}))


def cmd_barrier_clear(args, root, now):
    """RUNTIME-AC21: clearing the barrier requires attesting ALL FOUR
    reloads — command spec, dossier current generation, verbatim anchors,
    live session/account state."""
    require_root(root)
    if not (root / "barrier").exists():
        print(json.dumps({"ok": True, "barrier": "not_active"}))
        return
    missing = [name for name, val in [
        ("--spec-reloaded", args.spec_reloaded),
        ("--generation-reloaded", args.generation_reloaded),
        ("--anchors-reloaded", args.anchors_reloaded),
        ("--live-state-reloaded", args.live_state_reloaded),
    ] if not val]
    if missing:
        fail(EXIT_REFUSED, f"barrier-clear requires full reload attestation; missing: {missing}")
    os.unlink(root / "barrier")
    journal_append(root, {"op": "barrier-clear"}, now)
    print(json.dumps({"ok": True, "barrier": "cleared"}))


# ---------------- wake channel (task 20260831-031316 M1-M5, M7): recurring
# ---------------- arming state + delivery proof + watermark ageing +
# ---------------- session-end drain-or-declare teardown

WAKE_CHANNEL_KINDS = ["paseo_heartbeat", "paseo_schedule"]
WAKE_ROLES = ["tick", "test"]
# Supported 5-field cron subset (anything else refused fail-closed at
# wake-arm): numeric, "*", "*/N", comma lists, "a-b" ranges per field; fields
# are minute hour day-of-month month day-of-week, with the deployed parser's
# bounds (dow 0-6; 7 is refused there and so is refused here).  All five field
# predicates are ANDed, exactly as the deployed scheduler ANDs them.
CRON_FIELD_SPECS = [("minute", 0, 59), ("hour", 0, 23), ("day-of-month", 1, 31),
                    ("month", 1, 12), ("day-of-week", 0, 6)]
# The deployed scheduler's own occurrence-search budget, read at
# /opt/paseo/node_modules/@getpaseo/server/dist/server/server/schedule/cron.js:68
# as `const limit = 366 * 24 * 60`, evaluated END-EXCLUSIVE from
# startOfNextMinute(after).  A cadence the vendor cannot reach inside this
# budget is one it will never fire, so the ledger must refuse it rather than
# watch a channel that can never be delivered.
VENDOR_OCCURRENCE_BUDGET_CANDIDATES = 366 * 24 * 60

# Bumped whenever the enumeration policy of this engine changes.  An armed
# record that does not carry THIS marker was written by a different policy and
# is never read as trusted (M6): absence is not equivalence.
WAKE_ENGINE_POLICY = "vendor-parity-2026-09"

# Verification-window knob (M15): default via load_config, computed floor at
# expected_next_fire + wake_slack, fixed ceiling so the bound stays meaningful.
WAKE_VERIFY_WINDOW_DEFAULT_DAYS = 30
WAKE_VERIFY_WINDOW_MAX_DAYS = 365
# Resolved through load_config so a test can record the digest of a fixture it
# owns; the deployed absolute path is only the default (M14).
WAKE_VENDOR_NODE_PATH_DEFAULT = "/usr/bin/node"

# The vendor rule-source probe.  Runs in the DEPLOYED runtime and reports the
# zone's whole-minute UTC-offset table in the canonical form of M13:
# newline-joined "<epoch_seconds>:<offset_seconds>" run starts, integers only.
# A canonical integer form is mandatory -- comparing the two runtimes' ISO
# renderings reports every zone as divergent, because Node emits milliseconds
# and Python does not.  Exit 3 means the vendor REJECTS the zone (its
# assertValidTimeZone would throw), which is a refusal and not an outage.
VENDOR_TZ_PROBE_JS = r"""
const zone = process.argv[1], fromMs = Number(process.argv[2]),
      untilMs = Number(process.argv[3]);
let dtf;
try {
  dtf = new Intl.DateTimeFormat("en-US", {timeZone: zone, hourCycle: "h23",
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit",
    minute: "2-digit", second: "2-digit"});
  dtf.format(new Date(0));
} catch (e) { process.stderr.write("invalid timezone"); process.exit(3); }
function offsetSeconds(ms) {
  const p = {};
  for (const part of dtf.formatToParts(new Date(ms)))
    if (part.type !== "literal") p[part.type] = part.value;
  return Math.round((Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour,
                              +p.minute, +p.second) - ms) / 1000);
}
const runs = [];
let previous = null;
for (let ms = fromMs; ms < untilMs; ms += 60000) {
  const offset = offsetSeconds(ms);
  if (offset !== previous) { runs.push((ms / 1000) + ":" + offset); previous = offset; }
}
process.stdout.write(runs.join("\n"));
"""


def parse_cron_field(text, what, lo, hi):
    """Return (restricted, allowed-values set). TRUE cron semantics: '*/45'
    in the minute field means minutes {0, 45} — alternating 45/15-minute
    gaps — NEVER 'every 45 minutes'; an arithmetic `expected += cadence`
    model is wrong for cron channels and is deliberately not implemented."""
    if text == "*":
        return False, set(range(lo, hi + 1))
    # ASCII digits only, in every field form below: the pinned vendor parser
    # tests with the JavaScript /^\d+$/, which is ASCII-only, while Python's
    # \d admits every Unicode decimal digit -- so a cron the vendor rejects
    # outright would otherwise arm here.
    m = re.fullmatch(r"\*/([0-9]+)", text)
    if m:
        step = int(m.group(1))
        # The vendor requires the CANONICAL spelling (String(step) === source),
        # so "*/01" is "Invalid cron minute step" there and must not normalise
        # through int() here.
        if m.group(1) != str(step):
            fail(EXIT_REFUSED,
                 f"non-canonical cron {what} step in {text!r}: the deployed "
                 f"parser requires {str(step)!r} and refuses zero-padded steps")
        if step < 1 or step > hi:
            fail(EXIT_REFUSED, f"unsupported cron {what} step in {text!r}")
        return True, set(range(lo, hi + 1, step))
    values = set()
    for part in text.split(","):
        m = re.fullmatch(r"([0-9]+)-([0-9]+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if not lo <= a <= b <= hi:
                fail(EXIT_REFUSED, f"cron {what} range {part!r} outside {lo}-{hi}")
            values.update(range(a, b + 1))
            continue
        if re.fullmatch(r"[0-9]+", part):
            v = int(part)
            if not lo <= v <= hi:
                fail(EXIT_REFUSED, f"cron {what} value {part!r} outside {lo}-{hi}")
            values.add(v)
            continue
        fail(EXIT_REFUSED,
             f"unsupported cron {what} element {part!r}; supported subset: "
             f"numeric, *, */N, comma lists, a-b ranges")
    return True, values


def parse_cron(expr):
    fields = expr.split()
    if len(fields) != 5:
        fail(EXIT_REFUSED, f"cron needs exactly 5 fields, got {len(fields)}: {expr!r}")
    parsed = [parse_cron_field(text, what, lo, hi)
              for text, (what, lo, hi) in zip(fields, CRON_FIELD_SPECS)]
    return {
        "minutes": parsed[0][1],
        "hours": parsed[1][1],
        "dom": parsed[2],
        "months": parsed[3][1],
        "dow": parsed[4],
    }


def cron_day_matches(spec, local_dt):
    """Unconditional conjunction of the two day fields, matching the deployed
    scheduler, which ANDs all five field predicates at cron.js:72-76 with no
    day-field special case. The classic Vixie union rule manufactured fires
    the vendor will never deliver, and each phantom fire latched a re-arm
    demand whose remedy erased the real miss evidence."""
    dom_values = spec["dom"][1]
    dow_values = spec["dow"][1]
    dom_ok = local_dt.day in dom_values
    dow_ok = (local_dt.weekday() + 1) % 7 in dow_values  # cron: Sunday == 0
    return dom_ok and dow_ok


def cron_next_fire(spec, after, tzname):
    """Next occurrence STRICTLY after `after` (aware UTC in, aware UTC out).

    The candidate advances MONOTONICALLY IN UTC and is projected into the IANA
    zone only to evaluate cron fields. Local-clock arithmetic is never used:
    `local_dt + timedelta` resets the PEP 495 `fold` flag, which at a fall-back
    transition walks BACKWARDS (returning instants earlier than `after`, in
    breach of this contract) and skips the repeated hour outright -- fail-open
    miss detection, the precise failure this engine exists to prevent.

    DST policy, explicit in both directions:
      * spring-forward gap -- a wall time that does not exist that day never
        fires; walking real UTC instants simply never projects onto it, and the
        occurrence resumes on the next day that has the wall time.
      * fall-back repeated hour -- EVERY real instant fires, for every hour
        field. The deployed scheduler carries no fold handling at all: it
        projects each whole-minute UTC candidate through Intl.DateTimeFormat
        and matches the fields it reads, so both the fold=0 and the fold=1
        occurrence of a repeated wall time are real fires there. Suppressing
        the repeat here made the ledger expect FEWER fires than the channel
        actually delivers, which is exactly how a dead channel read healthy.
    """
    tz = ZoneInfo(tzname)
    cand = (after.astimezone(timezone.utc).replace(second=0, microsecond=0)
            + timedelta(minutes=1))
    try:
        # End-exclusive, exactly as cron.js:70 evaluates `index < limit` over
        # candidates spaced 60 s apart from startOfNextMinute(after).
        budget_end = cand + timedelta(
            minutes=VENDOR_OCCURRENCE_BUDGET_CANDIDATES)
    except OverflowError:
        # Refuse rather than claim an occurrence search was authoritative when
        # Python cannot represent the bound the deployed scheduler evaluates.
        fail(EXIT_REFUSED,
             "cannot search the deployed scheduler's "
             f"{VENDOR_OCCURRENCE_BUDGET_CANDIDATES}-candidate occurrence "
             f"window after {iso(after)}")
    while cand < budget_end:
        local = cand.astimezone(tz)
        if (local.month not in spec["months"] or not cron_day_matches(spec, local)
                or local.hour not in spec["hours"]):
            step = timedelta(minutes=60 - local.minute)  # next local hour boundary
            # The coarse skip is sound ONLY while the UTC offset is constant
            # across it: local-minute arithmetic equals UTC-minute arithmetic
            # only then, and the whole jumped span then shares one non-matching
            # local hour. When the offset shifts INSIDE the jump the local hour
            # can turn into a matching one mid-jump and the skip would silently
            # lose that fire -- e.g. Pacific/Chatham (+12:45 -> +13:45, 2026-09-27)
            # jumped 13:30Z straight to 14:15Z, stepping over the 14:00Z match of
            # `45 3 * * *`. Fall back to minute granularity across the shift.
            # Assumes no IANA zone changes offset twice inside 60 minutes (none
            # does; the tightest real steps are single 30/45/60/120-minute ones).
            if (cand + step).astimezone(tz).utcoffset() != local.utcoffset():
                step = timedelta(minutes=1)
            cand += step
            continue
        if local.minute in spec["minutes"]:
            return cand
        cand += timedelta(minutes=1)
    fail(EXIT_REFUSED,
         "no cron occurrence within the deployed scheduler's "
         f"{VENDOR_OCCURRENCE_BUDGET_CANDIDATES}-candidate window after "
         f"{iso(after)}: the deployed scheduler would never fire this cadence")


def wake_path(root):
    return root / "wake.json"


# ---------------- timezone rule-source trust (M11-M16) ----------------
#
# The ledger reads /usr/share/zoneinfo (dpkg tzdata) while the deployed
# scheduler reads the tz rules compiled into its own runtime.  Those two rule
# sources are not the same artifact and cannot be made the same one from here,
# so exact behavioural alignment is impossible IN PRINCIPLE.  The divergence is
# therefore BOUNDED instead of removed: arming proves agreement over an
# explicit window and records what it proved, and every READ re-evaluates that
# proof.  Nothing about this is a health claim -- it can only ever withhold
# one.

def zone_offset_table(tzname, start, end):
    """The zone's whole-minute UTC-offset table over [start, end), in the
    canonical comparison form: newline-joined '<epoch_seconds>:<offset_seconds>'
    RUN STARTS, integers only. Returns None when the zone cannot be resolved
    from this runtime's rule source at all."""
    try:
        tz = ZoneInfo(tzname)
    except (KeyError, ValueError, OSError):
        return None
    runs = []
    previous = None
    cand = start
    step = timedelta(minutes=1)
    while cand < end:
        offset = int(cand.astimezone(tz).utcoffset().total_seconds())
        if offset != previous:
            runs.append(f"{int(cand.timestamp())}:{offset}")
            previous = offset
        cand += step
    return "\n".join(runs)


def vendor_offset_table(node_path, tzname, start, end):
    """Run the vendor rule-source probe in the DEPLOYED runtime.

    Returns (status, table): status 'ok' with the canonical table, 'rejected'
    when the deployed runtime refuses the zone identifier outright (its own
    assertValidTimeZone would throw, so it will never schedule that channel),
    or 'unconsultable' when the runtime cannot be reached at all."""
    try:
        proc = subprocess.run(
            [node_path, "-e", VENDOR_TZ_PROBE_JS, "--", tzname,
             str(int(start.timestamp() * 1000)), str(int(end.timestamp() * 1000))],
            capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return "unconsultable", None
    if proc.returncode == 3:
        return "rejected", None
    if proc.returncode != 0:
        return "unconsultable", None
    return "ok", proc.stdout


def first_table_disagreement(ledger_table, vendor_table):
    """The first run-start line the two tables do not share, or None."""
    ledger_runs = ledger_table.split("\n") if ledger_table else []
    vendor_runs = vendor_table.split("\n") if vendor_table else []
    for index in range(max(len(ledger_runs), len(vendor_runs))):
        mine = ledger_runs[index] if index < len(ledger_runs) else None
        theirs = vendor_runs[index] if index < len(vendor_runs) else None
        if mine != theirs:
            return {"ledger": mine, "vendor": theirs}
    return None


def file_digest(path):
    """sha256 of a file's bytes, or None when it is absent or unreadable.
    Reads the file; NEVER executes it (M14, Adjudication 1)."""
    try:
        with open(path, "rb") as fh:
            digest = hashlib.sha256()
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
            return digest.hexdigest()
    except OSError:
        return None


def wake_trust_state(record, now):
    """The single read-time trust predicate (M12).

    A POSITIVE-EVIDENCE conjunction: every input must be PRESENT before it is
    examined, and an absent input TERMINATES the predicate with a reason code
    before any comparison is reached. Two absent values are therefore never
    compared and can never compare equal -- the defect shape that already cost
    this workstream one fail-open. No evidence field is read through a
    defaulting accessor; a default would reintroduce exactly that hole.
    Executes nothing: the vendor runtime is never launched from a read path.
    """
    policy = record.get("engine_policy")
    if policy is None:
        return "untrusted", "engine_policy_absent"
    if policy != WAKE_ENGINE_POLICY:
        return "untrusted", "engine_policy_unknown"
    container = record.get("tz_rule_source")
    if not isinstance(container, dict):
        return "untrusted", "trust_container_absent"
    if container.get("verified") is not True:
        return "untrusted", container.get("reason") or "rule_source_unverified"
    verified_from = container.get("verified_from")
    verified_until = container.get("verified_until")
    if verified_from is None or verified_until is None:
        return "untrusted", "verification_window_absent"
    window_start = parse_aware(verified_from, "wake.tz_rule_source.verified_from")
    window_end = parse_aware(verified_until, "wake.tz_rule_source.verified_until")
    if not window_start <= now < window_end:
        return "untrusted", "window_expired"
    recorded = container.get("fingerprint")
    if recorded is None:
        return "untrusted", "rule_source_fingerprint_absent"
    tzname = record.get("timezone")
    if tzname is None:
        return "untrusted", "timezone_absent"
    current = zone_offset_table(tzname, window_start, window_end)
    if current is None:
        return "untrusted", "rule_source_unreadable"
    if sha256_bytes(current.encode("utf-8")) != recorded:
        return "untrusted", "rule_source_changed"
    binary_path = container.get("vendor_binary_path")
    binary_digest = container.get("vendor_binary_digest")
    if binary_path is None or binary_digest is None:
        return "untrusted", "vendor_binary_reference_absent"
    actual = file_digest(binary_path)
    if actual is None:
        return "untrusted", "vendor_binary_unreadable"
    if actual != binary_digest:
        return "untrusted", "vendor_binary_digest_mismatch"
    return "trusted", None


def wake_verify_window_days(args, config):
    """M15: the window is a knob read through the ledger's existing config
    surface, never a second configuration path."""
    if getattr(args, "verify_window_days", None) is not None:
        return args.verify_window_days
    return config.get("wake_verify_window_days", WAKE_VERIFY_WINDOW_DEFAULT_DAYS)


def cmd_wake_arm(args, root, now):
    """Persist the armed wake channel so arming is reconstructable and a
    successor can distinguish 'wake missed' from 'nothing armed' (the
    2026-08-30 dry-run could not). Every finite role=tick maxRuns is refused
    fail-closed: any cap leaves a last fire after which delivery loss is
    permanent (observed: one lost fire, 3h20m43s strand)."""
    require_root(root)
    check_barrier(root)
    # The rule-source comparison below stamps its FIRST run with the literal
    # `now` instant on both sides (zone_offset_table's canonical form is
    # integer seconds; see its docstring), but the deployed vendor probe
    # inherits whatever sub-second fraction `now` carries and does not round
    # it away. A sub-second `now` -- the default datetime.now() resolution,
    # or an explicit fractional --now -- then leaks through as e.g.
    # ledger='1789442655:0' vendor='1789442655.201:0': the SAME instant at
    # two precisions, misread as disagreeing rule sources. Normalize once,
    # up front, so every downstream use (armed_at, verified_from, and both
    # offset tables) shares one precision.
    now = now.replace(microsecond=0)
    if args.role == "tick" and args.max_runs is not None:
        fail(EXIT_REFUSED,
             f"recurring-cadence-only: a finite maxRuns ({args.max_runs}) on the tick "
             "channel is forbidden -- the cadence must repeat indefinitely, and ANY "
             "cap leaves a last fire after which loss is permanent; one-shots and "
             "capped runs are reserved for explicit channel tests with teardown and "
             "proof-by-delivery")
    try:
        ZoneInfo(args.timezone)
    except (KeyError, ValueError, OSError) as exc:
        fail(EXIT_REFUSED, f"unknown IANA timezone {args.timezone!r}: {exc}")
    spec = parse_cron(args.cron)
    expected = cron_next_fire(spec, now, args.timezone)
    config = load_config(root)
    window_days = wake_verify_window_days(args, config)
    if window_days < 1 or window_days > WAKE_VERIFY_WINDOW_MAX_DAYS:
        fail(EXIT_REFUSED,
             f"verification window {window_days}d outside 1-"
             f"{WAKE_VERIFY_WINDOW_MAX_DAYS}d: a window beyond the ceiling "
             "would make the vendor-side bound vacuous")
    verified_until = now + timedelta(days=window_days)
    slack = timedelta(minutes=config.get("wake_slack_minutes", 15))
    if verified_until < expected + slack:
        fail(EXIT_REFUSED,
             f"verification window ends {iso(verified_until)}, before this "
             f"channel could ever prove a delivery ({iso(expected + slack)}): "
             "arming it would go untrusted before its first fire")
    node_path = config.get("wake_vendor_node_path", WAKE_VENDOR_NODE_PATH_DEFAULT)
    status, vendor_table = vendor_offset_table(node_path, args.timezone,
                                               now, verified_until)
    if status == "rejected":
        fail(EXIT_REFUSED,
             f"deployed scheduler refuses timezone {args.timezone!r}: it would "
             "never create this channel, so the ledger must not watch one")
    ledger_table = zone_offset_table(args.timezone, now, verified_until)
    if status == "ok":
        disagreement = first_table_disagreement(ledger_table, vendor_table)
        if disagreement is not None:
            # M11 branch 1: provable disagreement inside the window. The two
            # rule sources cannot be reconciled from here, so refuse BEFORE any
            # record exists that a consumer could read as healthy.
            fail(EXIT_REFUSED,
                 f"timezone rule sources disagree for {args.timezone!r} within "
                 f"[{iso(now)}, {iso(verified_until)}): first disagreeing run "
                 f"start ledger={disagreement['ledger']!r} "
                 f"vendor={disagreement['vendor']!r}")
        trust = {
            "verified": True,
            "reason": None,
            "verified_from": iso(now),
            "verified_until": iso(verified_until),
            "fingerprint": sha256_bytes(ledger_table.encode("utf-8")),
            "vendor_binary_path": str(Path(node_path).resolve()),
            "vendor_binary_digest": file_digest(node_path),
        }
        if trust["vendor_binary_digest"] is None:
            trust["verified"] = False
            trust["reason"] = "vendor_binary_unreadable"
    else:
        # M11 branch 2: the vendor could not be consulted at all. Arm, because
        # refusing would strand the channel, but arm UNTRUSTED -- an
        # unconsultable rule source is not an agreeing one.
        trust = {
            "verified": False,
            "reason": "vendor_unconsultable",
            "verified_from": iso(now),
            "verified_until": iso(verified_until),
            "fingerprint": None,
            "vendor_binary_path": None,
            "vendor_binary_digest": None,
        }
    # M16: blindness is measurable, so the counter survives re-arming. Re-arm
    # clears the MISS latch, never the accumulated untrusted time.
    previous = read_json(wake_path(root)) if wake_path(root).exists() else {}
    carried = previous.get("untrusted_minutes_total")
    # Per-arming identity: an opaque token compared only by EQUALITY, never
    # ordered. Drawn from the OS entropy pool, so no caller -- notably not the
    # --now fake clock, which makes armed_at caller-supplied -- can force a
    # collision. Collision-RESISTANT, not collision-proof.
    arming_token = secrets.token_hex(16)
    atomic_write_json(wake_path(root), {
        "channel_kind": args.channel_kind,
        "channel_id": args.channel_id,
        "cron": args.cron,
        "timezone": args.timezone,
        "role": args.role,
        "max_runs": args.max_runs,
        "armed_at": iso(now),
        "arming_token": arming_token,
        "expected_next_fire": iso(expected),
        "last_observed_at": None,
        "last_verdict": None,
        "missed_total": 0,
        # Latched health flag: set by any observed miss, cleared ONLY here by a
        # successful re-arm. Persisted so a crash between the observation and
        # the external re-arm cannot let wake-status read fresh.
        "needs_rearm": False,
        # Engine-policy marker (M6): what enumeration policy wrote this record.
        "engine_policy": WAKE_ENGINE_POLICY,
        # What arming actually PROVED about the two rule sources, and over
        # which window. Untrusted is discharged only by the SUCCESS of this
        # verification, never by the act of re-arming (M16).
        "tz_rule_source": trust,
        "untrusted_minutes_total": 0 if carried is None else carried,
        "untrusted_since": None,
    })
    journal_append(root, {"op": "wake-arm", "channel_kind": args.channel_kind,
                          "channel_id": args.channel_id, "cron": args.cron,
                          "timezone": args.timezone, "role": args.role,
                          "expected_next_fire": iso(expected),
                          "tz_rule_source_verified": trust["verified"]}, now)
    print(json.dumps({"ok": True, "channel_id": args.channel_id,
                      # Reported so the operator can capture it into the wake
                      # prompt at ARMING time; the prompt must never re-read it.
                      "arming_token": arming_token,
                      "expected_next_fire": iso(expected),
                      "tz_rule_source_verified": trust["verified"],
                      "verified_until": trust["verified_until"]}))


def append_wake_missed_event(root, record, missed_fires, slack_minutes, now):
    """ONE consolidated schema'd inbox event per observe invocation carrying
    the missed-fire count — never one event per missed period (a long strand
    must not flood the inbox). Duplicate event ids are idempotent no-ops,
    mirroring cmd_inbox_append.

    The id is derived from INTERVAL IDENTITY — channel, arming generation
    (armed_at), and the first/last reconciled missed fire — never from
    observation wall time: a crash after the inbox append but before wake.json
    advances re-reconciles the SAME interval, so the retry must produce the
    SAME id and collapse into the idempotent no-op above instead of appending a
    second event for one interval."""
    missed = len(missed_fires)
    fmt = "%Y%m%dT%H%M%SZ"
    armed_at = parse_aware(record["armed_at"], "wake.armed_at")
    event_id = (f"wake-missed-{record['channel_id']}-{armed_at.strftime(fmt)}"
                f"-{missed_fires[0].strftime(fmt)}-{missed_fires[-1].strftime(fmt)}")
    pending = root / "inbox" / "pending" / f"{event_id}.json"
    acked = root / "inbox" / "acked" / f"{event_id}.json"
    if pending.exists() or acked.exists():
        return event_id
    atomic_write_json(pending, {"event_id": event_id, "appended_at": iso(now), "payload": {
        "type": "wake_channel_missed",
        "channel_kind": record["channel_kind"],
        "channel_id": record["channel_id"],
        "cron": record["cron"],
        "missed_fires": missed,
        "first_missed_fire": iso(missed_fires[0]),
        "last_missed_fire": iso(missed_fires[-1]),
        "expected_next_fire": record["expected_next_fire"],
        "wake_slack_minutes": slack_minutes,
        "observed_at": iso(now),
    }})
    journal_append(root, {"op": "inbox-append", "event_id": event_id}, now)
    return event_id


def cmd_wake_observe(args, root, now):
    """Delivery-proof + watermark ageing: ARRIVAL is the only proof of
    channel health (create-API success is not). Runs at every wake —
    scheduled or manual. Verdict against expected_next_fire + wake_slack:
    on_time / late when delivered against an elapsed occurrence, non_proving
    when the claim names no due occurrence at all, missed / pending when the
    observation is manual (no --delivered); a miss journals
    wake_channel_missed, appends the consolidated inbox event, and demands
    re-arm. Deterministic under the --now fake clock."""
    require_root(root)
    check_barrier(root)
    if args.delivered and args.channel_id is None:
        fail(EXIT_REFUSED,
             "--delivered requires --channel-id: arrival is proved by the channel id "
             "the wake prompt carries, so a delivery claim must NAME the channel it "
             "proves; an unnamed claim would validate whichever channel happens to be "
             "armed and turn proof-by-delivery into an assertion")
    path = wake_path(root)
    if not path.exists():
        fail(EXIT_REFUSED, "nothing armed: run wake-arm first (an absent armed record "
                           "must never read as a healthy channel)")
    record = read_json(path)
    if args.channel_id is not None and args.channel_id != record["channel_id"]:
        fail(EXIT_REFUSED, f"observed channel {args.channel_id!r} does not match armed "
                           f"channel {record['channel_id']!r}; re-arm before observing")
    # Delivery proof binds to the ARMING, not to the channel alone: a late wake
    # belonging to a superseded arming must never certify the arming that
    # replaced it. Compared by EQUALITY only -- the token carries no order.
    # ABSENCE TERMINATES the predicate before any comparison, so an
    # identity-less legacy record and a claim that names nothing can never
    # match by both being absent -- the fail-open shape this workstream has
    # already paid for once.
    armed_token = record.get("arming_token")
    arming_verdict = None
    if args.delivered:
        if armed_token is None:
            arming_verdict = "unversioned_arming"
        elif args.arming_token is None:
            fail(EXIT_REFUSED,
                 "--delivered requires --arming-token against a record that carries "
                 "an arming token: a delivery claim must name the ARMING it proves, "
                 "not merely the channel; a claim bound to the channel id alone "
                 "would validate whichever arming happens to be current and let a "
                 "superseded wake certify a replacement that may itself be dead")
        elif args.arming_token != armed_token:
            arming_verdict = "superseded_arming"
    # A non-certifying arrival proves nothing, so it is scored EXACTLY as the
    # plain non-delivery observation it is: the persisted health state is
    # whatever non-delivery would have written. The distinct classification
    # reaches only the DIAGNOSIS channels (stdout + journal) below.
    delivered = args.delivered and arming_verdict is None
    config = load_config(root)
    slack_minutes = config.get("wake_slack_minutes", 15)
    slack = timedelta(minutes=slack_minutes)
    spec = parse_cron(record["cron"])
    expected = parse_aware(record["expected_next_fire"], "wake.expected_next_fire")
    fires = []
    fire = expected
    while fire <= now:
        fires.append(fire)
        fire = cron_next_fire(spec, fire, record["timezone"])
    if delivered and not fires:
        # M9: a delivery claim naming no due occurrence proves nothing about a
        # scheduled channel, so it is NON-PROVING and changes no health-bearing
        # field. Recording it as on_time (or merely stamping last_observed_at)
        # would manufacture a proof of life out of an arrival nobody scheduled.
        record["last_non_proving_claim_at"] = iso(now)
        atomic_write_json(path, record)
        state, reason = wake_trust_state(record, now)
        journal_append(root, {"op": "wake-observe",
                              "channel_id": record["channel_id"],
                              "verdict": "non_proving", "missed_fires": 0,
                              "needs_rearm": bool(record.get("needs_rearm"))}, now)
        print(json.dumps({
            "ok": True, "verdict": "non_proving", "missed_fires": 0,
            "needs_rearm": bool(record.get("needs_rearm")) or state != "trusted",
            "expected_next_fire": record["expected_next_fire"],
            "inbox_event_id": None, "trust_state": state, "trust_reason": reason}))
        return
    # ONE miss rule for delivered and undelivered observations alike: every
    # elapsed fire whose slack has expired is missed. Excluding the delivered
    # fire let a late arrival EXONERATE the very fire it failed to honour.
    missed_fires = [f for f in fires if f + slack < now]
    if delivered:
        delivered_fire = fires[-1]
        verdict = "on_time" if now <= delivered_fire + slack else "late"
    else:
        verdict = "missed" if missed_fires else "pending"
    # M3 channel separation: the record takes the non-delivery verdict, so the
    # health state really is identical; only the diagnosis channels see the
    # distinct classification.
    reported_verdict = verdict if arming_verdict is None else arming_verdict
    missed = len(missed_fires)
    # Latched: an arrival proves the channel is alive NOW but does not retire an
    # earlier loss, so only a successful wake-arm clears this. Persisting it is
    # what makes the demand survive a crash before the external re-arm.
    needs_rearm = bool(record.get("needs_rearm", False)) or missed > 0
    event_id = None
    if missed:
        event_id = append_wake_missed_event(root, record, missed_fires, slack_minutes, now)
    record["last_observed_at"] = iso(now)
    record["last_verdict"] = verdict
    record["missed_total"] = record.get("missed_total", 0) + missed
    record["needs_rearm"] = needs_rearm
    if verdict != "pending":
        # A resolving verdict only proves the fate of fires this call actually
        # judged. `missed_fires` is always a PREFIX of `fires`: both are
        # ordered and `f + slack < now` is monotone in f. So the UNJUDGED
        # remainder is exactly fires[len(missed_fires):] -- every fire still
        # inside its own legitimate grace window. Advancing past them to
        # cron_next_fire(now) orphans them: they can never be counted missed
        # once their own grace finally expires, and a later --delivered claim
        # finds no due occurrence at all (fires=[]) and reports non_proving
        # instead of on_time. So the watermark parks at the FIRST unjudged
        # fire. Parking at fires[-1] instead rescues only the newest of them
        # and silently discards the rest whenever two or more fires are
        # simultaneously elapsed-but-still-in-grace -- which is every cron
        # whose interval is shorter than wake_slack_minutes.
        #
        # The delivered branch deliberately does NOT park: an arrival is
        # scored against fires[-1], so parking below it would re-present an
        # ALREADY-HONOURED fire for judgment on the next tick and count a
        # delivered fire as missed. Advancing past the whole batch is the
        # correct treatment there.
        if delivered or len(missed_fires) == len(fires):
            # every fire in the batch is judged -- advance to the next TRUE
            # cron occurrence strictly after now
            record["expected_next_fire"] = iso(cron_next_fire(spec, now, record["timezone"]))
        else:
            # index is in range precisely because the branch above consumed
            # the all-judged case
            record["expected_next_fire"] = iso(fires[len(missed_fires)])
    state, reason = wake_trust_state(record, now)
    # M16: accumulate the time this channel has spent unable to prove its rule
    # source, in the command that already writes. wake-status must not, so the
    # counter lives here and only here; a re-arm carries it forward.
    if state != "trusted":
        since = record.get("untrusted_since")
        if since is not None:
            elapsed = (now - parse_aware(since, "wake.untrusted_since")
                       ).total_seconds() / 60.0
            if elapsed > 0:
                carried = record.get("untrusted_minutes_total")
                record["untrusted_minutes_total"] = round(
                    (0 if carried is None else carried) + elapsed, 6)
        record["untrusted_since"] = iso(now)
    else:
        record["untrusted_since"] = None
    atomic_write_json(path, record)
    journal_entry = {"op": "wake-observe", "channel_id": record["channel_id"],
                     "verdict": reported_verdict, "missed_fires": missed,
                     "needs_rearm": needs_rearm, "trust_state": state}
    if arming_verdict is not None:
        # Both tokens in BOUND roles: 'both values appear somewhere' would be
        # satisfied by a swapped or ambiguous pair.
        journal_entry["claimed_arming_token"] = args.arming_token
        journal_entry["armed_arming_token"] = armed_token
    if missed:
        journal_entry["event"] = "wake_channel_missed"
    journal_append(root, journal_entry, now)
    print(json.dumps({"ok": True, "verdict": reported_verdict,
                      "missed_fires": missed,
                      # The consumer surface, not the stored latch: an
                      # untrusted rule source cannot prove delivery, so the
                      # documented loop must re-arm on it too.
                      "needs_rearm": needs_rearm or state != "trusted",
                      "expected_next_fire": record["expected_next_fire"],
                      "inbox_event_id": event_id,
                      "trust_state": state, "trust_reason": reason}))


def cmd_wake_status(args, root, now):
    """Read-only ageing snapshot (mirrors lease-status): the armed record plus
    the current watermark verdict and the current trust reading; never
    mutates, never journals, never executes the vendor runtime.

    The stored record is splatted FIRST and every computed field is written
    AFTER it. The reverse order silently returns the stored value for any key
    the surface also computes, which is precisely how this surface came to
    carry no trust computation at all."""
    require_root(root)
    path = wake_path(root)
    if not path.exists():
        print(json.dumps({"armed": False}))
        return
    record = read_json(path)
    config = load_config(root)
    slack = timedelta(minutes=config.get("wake_slack_minutes", 15))
    expected = parse_aware(record["expected_next_fire"], "wake.expected_next_fire")
    state, reason = wake_trust_state(record, now)
    print(json.dumps({
        **record,
        "armed": True,
        # stale stays exactly 'now > expected_next_fire + wake_slack'.
        # Overloading it with untrustedness would make a late-but-trusted
        # channel indistinguishable from a punctual-but-unproven one.
        "stale": now > expected + slack,
        "deadline": iso(expected + slack),
        "needs_rearm": bool(record.get("needs_rearm")) or state != "trusted",
        "trust_state": state,
        "trust_reason": reason,
    }))


def cmd_watchdog_check(args, root, now):
    """R1 AC-1.2 (QA 20260911-011102 iteration 2 correction): the watchdog
    agent's full liveness-check + staleness-check + conditional-escalation
    sequence must fit within hooks/pretool-orchestrator-gate.py's
    5-consecutive-Bash-call budget even when escalation fires. QA measured
    that it did not: driving wake-status, lease-status, inbox-check-staleness
    and the conditional inbox-append as SEPARATE Bash calls let the sequence
    exceed the cap, and classified 6/13 (46%) of historical genuine
    DEAD/STRANDED/inbox_drain_stale escalation attempts across a814a9a0's run
    history as blocked by exactly this — both the pre-existing step-4 path
    (run d7786d71, 2026-09-10) and the new step-1b path (run eac446fc,
    2026-09-11).

    This subcommand performs all of: read wake status, read lease status,
    re-evaluate inbox-check-staleness, decide whether escalation is
    warranted, and (only if so) append ONE inbox event recording the
    evidence — as a SINGLE Bash invocation, so the watchdog prompt needs at
    most one Bash call for the entire read+judge+append sequence. Messaging
    the controller session remains a paseo-tool (non-Bash) step the watchdog
    performs itself afterward using this command's output — that step was
    never the thing exceeding the Bash-call cap and is intentionally left
    outside this CLI (see commands/paseo-daemon.md).

    Escalation is warranted when EITHER the controller looks DEAD/STRANDED
    (wake watermark stale, unarmed, or lease not held — the same ALIVE test
    ==  'wake watermark fresh AND lease unexpired'  already named in
    a814a9a0's own step 2/3 prompt text) OR inbox_drain_stale is true (R1's
    judge) — the two conditions are independent by design (BA's
    ac_1_2_schedule_design_decision.decisive_evidence: the wake/lease check
    is orthogonal to inbox_drain_stale, not a superset of it).

    Deliberately duplicates (does not import/call) cmd_wake_status's and
    cmd_lease_status's read logic rather than refactoring those functions to
    share a helper: QA's iteration-2 correction explicitly scoped that fix to
    a NEW consolidated entry point and asked dev not to re-touch those two
    read-only commands; leaving them untouched keeps that same
    zero-regression-risk posture. The inbox-drain-staleness computation, by
    contrast, calls compute_inbox_drain_staleness() -- the single shared
    implementation of BOTH AC-1.1 substates (no_plan, plan_not_acked) also
    used by cmd_inbox_check_staleness -- so a correctness fix to the judge is
    applied exactly once and the two call sites can never drift apart (task
    20260911-011102, QA close-debate iteration 3 correction).
    """
    require_root(root)
    check_barrier(root)
    config = load_config(root)

    wake_record_path = wake_path(root)
    if wake_record_path.exists():
        wake_record = read_json(wake_record_path)
        slack = timedelta(minutes=config.get("wake_slack_minutes", 15))
        expected = parse_aware(wake_record["expected_next_fire"], "wake.expected_next_fire")
        trust_state, trust_reason = wake_trust_state(wake_record, now)
        wake_status = {
            **wake_record,
            "armed": True,
            "stale": now > expected + slack,
            "deadline": iso(expected + slack),
            "needs_rearm": bool(wake_record.get("needs_rearm")) or trust_state != "trusted",
            "trust_state": trust_state,
            "trust_reason": trust_reason,
        }
    else:
        wake_status = {"armed": False}

    lease_path = root / "lease.json"
    if lease_path.exists():
        lease = read_json(lease_path)
        expires = parse_aware(lease["expires_at"], "lease.expires_at")
        lease_status = {"held": now < expires, **lease}
    else:
        lease_status = {"held": False}

    staleness = compute_inbox_drain_staleness(root, config, now)
    atomic_write_json(drain_status_path(root), staleness)
    journal_append(root, {"op": "inbox-check-staleness",
                          "inbox_drain_stale": staleness["inbox_drain_stale"],
                          "stale_reasons": staleness["stale_reasons"],
                          "oldest_pending_event_id": staleness["oldest_pending_event_id"],
                          "age_minutes": staleness["age_minutes"]}, now)

    # ALIVE == wake watermark fresh (armed AND not stale) AND lease held.
    # DEAD/STRANDED is the negation -- exactly a814a9a0's own step 2/3 text.
    wake_fresh = wake_status.get("armed", False) and not wake_status.get("stale", True)
    lease_ok = lease_status.get("held", False)
    controller_dead_or_stranded = not (wake_fresh and lease_ok)
    escalation_needed = controller_dead_or_stranded or staleness["inbox_drain_stale"]

    escalation_reasons = []
    if controller_dead_or_stranded:
        escalation_reasons.append("controller_dead_or_stranded")
    if staleness["inbox_drain_stale"]:
        escalation_reasons.append("inbox_drain_stale")

    result = {
        "ok": True,
        "checked_at": iso(now),
        "wake_status": wake_status,
        "lease_status": lease_status,
        "staleness": staleness,
        "escalation_needed": escalation_needed,
        "escalation_reasons": escalation_reasons,
        "escalation_event_id": None,
        "escalation_event_appended": False,
    }

    if escalation_needed:
        fmt = "%Y%m%dT%H%M%SZ"
        event_id = f"watchdog-escalation-{now.strftime(fmt)}"
        pending = root / "inbox" / "pending" / f"{event_id}.json"
        acked = root / "inbox" / "acked" / f"{event_id}.json"
        result["escalation_event_id"] = event_id
        if pending.exists() or acked.exists():
            result["escalation_event_appended"] = False  # duplicate id: already recorded
        else:
            payload = {
                "type": "watchdog_escalation",
                "reasons": escalation_reasons,
                "wake_status": wake_status,
                "lease_status": lease_status,
                "staleness": staleness,
            }
            atomic_write_json(pending, {"event_id": event_id, "payload": payload, "appended_at": iso(now)})
            journal_append(root, {"op": "inbox-append", "event_id": event_id}, now)
            result["escalation_event_appended"] = True

    print(json.dumps(result))


def cmd_teardown_declare(args, root, now):
    """Session-end drain-or-declare (M7): journal the pending event ids, the
    reason, and the lease disposition so a successor can distinguish a clean
    handoff from a crash. Deliberately NOT barrier-gated: refusing the
    declaration under an active rehydration barrier would force the silent
    abandonment this record exists to prevent (lease ops are likewise
    ungated)."""
    require_root(root)
    pending_ids = sorted(p.stem for p in (root / "inbox" / "pending").glob("*.json"))
    lease_path = root / "lease.json"
    if lease_path.exists():
        lease = read_json(lease_path)
        expires = parse_aware(lease["expires_at"], "lease.expires_at")
        disposition = {"state": "held" if now < expires else "expired",
                       "holder": lease["holder"], "incarnation": lease["incarnation"]}
    else:
        disposition = {"state": "none"}
    journal_append(root, {"op": "teardown-declare", "pending_event_ids": pending_ids,
                          "reason": args.reason, "lease_disposition": disposition}, now)
    print(json.dumps({"ok": True, "pending_event_ids": pending_ids,
                      "reason": args.reason, "lease_disposition": disposition}))


# ---------------- argument parsing ----------------

def build_parser():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--root", required=True, help="ledger root directory (e.g. .claude/paseo-daemon)")
    p.add_argument("--now", default=None, help="fake clock: aware ISO-8601 timestamp (tests)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init")
    s.add_argument("--accounts", default=",".join(DEFAULT_ACCOUNTS),
                   help="comma-separated account names (default: the three claude accounts)")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("lease-acquire")
    s.add_argument("--holder", required=True)
    s.add_argument("--ttl-seconds", type=int, default=None,
                   help="lease TTL seconds; default: config lease_ttl_seconds (fallback 3600)")
    s.set_defaults(fn=cmd_lease_acquire)
    s = sub.add_parser("lease-renew")
    s.add_argument("--holder", required=True)
    s.add_argument("--ttl-seconds", type=int, default=None,
                   help="lease TTL seconds; default: config lease_ttl_seconds (fallback 3600)")
    s.set_defaults(fn=cmd_lease_renew)
    s = sub.add_parser("lease-status")
    s.set_defaults(fn=cmd_lease_status)

    s = sub.add_parser("inbox-append")
    s.add_argument("--event-id", required=True)
    s.add_argument("--payload", required=True, help="event payload JSON")
    s.set_defaults(fn=cmd_inbox_append)
    s = sub.add_parser("inbox-consume")
    s.add_argument("--planned-outcome", required=True)
    s.add_argument("--inject-crash", choices=["after-consume", "after-plan"])
    s.set_defaults(fn=cmd_inbox_consume)
    s = sub.add_parser("inbox-ack")
    s.add_argument("--event-id", required=True)
    s.add_argument("--inject-crash", choices=["after-acked-write", "after-pending-unlink"])
    s.set_defaults(fn=cmd_inbox_ack)
    s = sub.add_parser("inbox-check-staleness")
    s.set_defaults(fn=cmd_inbox_check_staleness)

    s = sub.add_parser("action-transition")
    s.add_argument("--logical-session", required=True)
    s.add_argument("--phase", required=True)
    s.add_argument("--attempt", required=True)
    s.add_argument("--to", required=True)
    s.add_argument("--evidence", default=None,
                   help="machine-readable completion evidence path (required for terminal)")
    s.set_defaults(fn=cmd_action_transition)

    s = sub.add_parser("reserve")
    s.add_argument("--reservation-id", required=True)
    s.add_argument("--account", required=True)
    s.add_argument("--logical-session", required=True)
    s.set_defaults(fn=cmd_reserve)

    s = sub.add_parser("account-init")
    s.add_argument("--account", required=True)
    s.add_argument("--weekly-reset", required=True)
    s.set_defaults(fn=cmd_account_init)
    s = sub.add_parser("account-block")
    s.add_argument("--account", required=True)
    s.add_argument("--until", required=True)
    s.set_defaults(fn=cmd_account_block)
    s = sub.add_parser("account-observe-reset")
    s.set_defaults(fn=cmd_account_observe_reset)
    s = sub.add_parser("account-canary-result")
    s.add_argument("--account", required=True)
    s.add_argument("--result", required=True, choices=["success", "failure"])
    s.set_defaults(fn=cmd_account_canary_result)

    s = sub.add_parser("classify-error")
    s.add_argument("--text", required=True)
    s.add_argument("--account", default=None,
                   help="persist the account-state consequence of the classification")
    s.set_defaults(fn=cmd_classify_error)

    s = sub.add_parser("usage-ingest")
    s.add_argument("--input", default="-", help="providers[] JSON file, or - for stdin")
    s.set_defaults(fn=cmd_usage_ingest)

    s = sub.add_parser("scheduling-decision")
    s.add_argument("--account", required=True)
    s.add_argument("--task-class", required=True, choices=sorted(TASK_CLASS_BASE_MODEL))
    s.set_defaults(fn=cmd_scheduling_decision)

    s = sub.add_parser("recovery-record")
    s.add_argument("--session", required=True)
    s.add_argument("--account", required=True)
    s.add_argument("--original-agent-ids", required=True,
                   help="comma-separated pre-interruption subagent ids")
    s.add_argument("--last-artifact", default=None)
    s.set_defaults(fn=cmd_recovery_record)
    s = sub.add_parser("recovery-demand")
    s.add_argument("--session", required=True)
    s.set_defaults(fn=cmd_recovery_demand)
    s = sub.add_parser("recovery-judge")
    s.add_argument("--session", required=True)
    s.add_argument("--evidence", required=True, help="JSON array of agent ids with response evidence")
    s.set_defaults(fn=cmd_recovery_judge)

    s = sub.add_parser("dossier-validate")
    s.add_argument("--file", required=True)
    s.set_defaults(fn=cmd_dossier_validate)

    s = sub.add_parser("generation-commit")
    s.add_argument("--dossier", required=True)
    s.add_argument("--inject-crash", choices=["after-write", "after-rename", "before-pointer"])
    s.set_defaults(fn=cmd_generation_commit)

    s = sub.add_parser("intent-queue")
    s.add_argument("--intent-id", required=True)
    s.add_argument("--session", required=True)
    s.add_argument("--payload", required=True, help="intent payload JSON")
    s.add_argument("--observed-state", required=True)
    s.set_defaults(fn=cmd_intent_queue)
    s = sub.add_parser("intent-resolve")
    s.add_argument("--intent-id", required=True)
    s.add_argument("--outcome", required=True, choices=INTENT_OUTCOMES)
    s.set_defaults(fn=cmd_intent_resolve)

    s = sub.add_parser("session-flag")
    s.add_argument("--session", required=True)
    s.add_argument("--flag", required=True, choices=["suspect", "switch_pending", "clear"])
    s.add_argument("--turn-id", default=None)
    s.add_argument("--update-count", type=int, default=None)
    s.set_defaults(fn=cmd_session_flag)

    s = sub.add_parser("dossier-write")
    s.add_argument("--session", required=True)
    s.add_argument("--md-file", required=True)
    s.add_argument("--sidecar-file", required=True)
    s.set_defaults(fn=cmd_dossier_write)

    s = sub.add_parser("barrier-enter")
    s.set_defaults(fn=cmd_barrier_enter)
    s = sub.add_parser("barrier-clear")
    s.add_argument("--spec-reloaded", action="store_true")
    s.add_argument("--generation-reloaded", action="store_true")
    s.add_argument("--anchors-reloaded", action="store_true")
    s.add_argument("--live-state-reloaded", action="store_true")
    s.set_defaults(fn=cmd_barrier_clear)
    s = sub.add_parser("generation-verify")
    s.add_argument("--generation", type=int, default=None)
    s.add_argument("--expect-sha256", default=None)
    s.set_defaults(fn=cmd_generation_verify)

    s = sub.add_parser("wake-arm")
    s.add_argument("--channel-kind", required=True, choices=WAKE_CHANNEL_KINDS)
    s.add_argument("--channel-id", required=True)
    s.add_argument("--cron", required=True,
                   help="5-field cron; supported subset: numeric, *, */N, comma lists, a-b ranges")
    s.add_argument("--timezone", default="UTC", help="IANA timezone for the cron cadence")
    s.add_argument("--role", required=True, choices=WAKE_ROLES)
    s.add_argument("--max-runs", type=int, default=None,
                   help="declared maxRuns of the armed channel; any finite value is refused for role=tick")
    s.add_argument("--verify-window-days", type=int, default=None,
                   help="timezone rule-source verification window in days "
                        f"(default: config wake_verify_window_days, else "
                        f"{WAKE_VERIFY_WINDOW_DEFAULT_DAYS}; refused beyond "
                        f"{WAKE_VERIFY_WINDOW_MAX_DAYS})")
    s.set_defaults(fn=cmd_wake_arm)
    s = sub.add_parser("wake-observe")
    s.add_argument("--delivered", action="store_true",
                   help="a wake actually arrived (the prompt carried the channel id)")
    s.add_argument("--channel-id", default=None,
                   help="channel id carried by the arriving wake; must match the armed record")
    s.add_argument("--arming-token", default=None,
                   help="arming token the wake prompt captured at arming time; compared "
                        "by equality against the armed record, so a superseded arming "
                        "cannot certify the arming that replaced it")
    s.set_defaults(fn=cmd_wake_observe)
    s = sub.add_parser("wake-status")
    s.set_defaults(fn=cmd_wake_status)
    s = sub.add_parser("watchdog-check")
    s.set_defaults(fn=cmd_watchdog_check)
    s = sub.add_parser("teardown-declare")
    s.add_argument("--reason", required=True)
    s.set_defaults(fn=cmd_teardown_declare)
    return p


def main():
    args = build_parser().parse_args()
    root = Path(args.root)
    now = parse_aware(args.now, "--now") if args.now else datetime.now(timezone.utc)
    args.fn(args, root, now)


if __name__ == "__main__":
    main()
