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
import sys
from datetime import datetime, timezone
from pathlib import Path

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

def cmd_lease_acquire(args, root, now):
    require_root(root)
    lease_path = root / "lease.json"
    ttl = args.ttl_seconds
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
    lease["heartbeat_at"] = iso(now)
    lease["expires_at"] = iso(datetime.fromtimestamp(now.timestamp() + args.ttl_seconds, tz=timezone.utc))
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
    s.add_argument("--ttl-seconds", type=int, default=3600)
    s.set_defaults(fn=cmd_lease_acquire)
    s = sub.add_parser("lease-renew")
    s.add_argument("--holder", required=True)
    s.add_argument("--ttl-seconds", type=int, default=3600)
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
    return p


def main():
    args = build_parser().parse_args()
    root = Path(args.root)
    now = parse_aware(args.now, "--now") if args.now else datetime.now(timezone.utc)
    args.fn(args, root, now)


if __name__ == "__main__":
    main()
