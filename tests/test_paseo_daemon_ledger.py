"""BUILD-AC05 + BUILD-AC06 facade — ledger local-persistence invariants.

MANDATORY pytest facade for lane 20260828-112025-b: collects EVERY test
binding a BUILD-AC05 or BUILD-AC06 invariant of scripts/paseo-daemon-ledger.py
(docs/dev/acceptance-criteria-20260828-112025-b.json). All tests run against
TEMPORARY ledger roots (tmp_path) with a fake clock (--now) and crash
injection (--inject-crash) — never the live .claude/paseo-daemon/, and never
by invoking /dev, /close, /commit, or human-only /restart (fixtures only).
"""

import ast
import copy
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LEDGER = REPO / "scripts" / "paseo-daemon-ledger.py"
SCHEMA = REPO / "schemas" / "paseo-dossier.v1.json"
COMMAND_DOC = REPO / "commands" / "paseo-daemon.md"
VENDOR_VECTORS_PATH = REPO / "tests" / "fixtures" / "paseo_cron_vendor_vectors.json"

# The single registry of premise literals this cycle DELETED from the engine.
# Nodes that must prove those premises are gone read them from here instead of
# spelling them, so an asserter of an absence never becomes a carrier of it.
DELETED_PREMISE_LITERALS = [
    "hours_restricted",
    "CRON_SEARCH_HORIZON_DAYS",
    "146097",
    "no cron occurrence within 400 Gregorian years",
    "fires[:-1]",
]

T0 = "2026-08-28T12:00:00Z"
SHA_A, SHA_B, SHA_C, SHA_D = "a" * 64, "b" * 64, "c" * 64, "d" * 64


def run(root, *args, now=T0, stdin=None, env=None):
    cmd = [sys.executable, str(LEDGER), "--root", str(root)]
    if now is not None:
        cmd += ["--now", now]
    cmd += list(args)
    child_env = None
    if env is not None:
        child_env = dict(os.environ)
        child_env.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, input=stdin,
                          cwd=REPO, env=child_env)


def ok(root, *args, **kw):
    r = run(root, *args, **kw)
    assert r.returncode == 0, f"{args}: rc={r.returncode} stderr={r.stderr}"
    return json.loads(r.stdout) if r.stdout.strip().startswith(("{", "[")) else r.stdout


def wake_record(root):
    return json.loads((root / "wake.json").read_text())


def put_wake_record(root, record):
    (root / "wake.json").write_text(
        json.dumps(record, indent=1, ensure_ascii=False, sort_keys=True) + "\n")


def set_config(root, **knobs):
    path = root / "config.json"
    cfg = json.loads(path.read_text())
    cfg.update(knobs)
    path.write_text(json.dumps(cfg, indent=1, sort_keys=True) + "\n")


def ledger(tmp_path, accounts="orchestrade,yugetang,yugoge"):
    root = tmp_path / "ledger"
    ok(root, "init", "--accounts", accounts)
    return root


# ---------------- init layout ----------------

def test_init_creates_documented_layout(tmp_path):
    root = ledger(tmp_path)
    for d in ["inbox/pending", "inbox/plans", "inbox/acked", "actions",
              "reservations", "backlog", "recovery", "generations", "dossiers",
              "sessions"]:
        assert (root / d).is_dir(), d
    assert (root / "accounts.json").is_file()
    assert (root / "config.json").is_file()
    wm = json.loads((root / "inbox" / "watermark.json").read_text())
    assert wm == {"processed_count": 0, "last_event_id": None}
    accounts = json.loads((root / "accounts.json").read_text())["accounts"]
    assert set(accounts) == {"orchestrade", "yugetang", "yugoge"}


# ---------------- inbox: consume -> plan -> ack exactly once ----------------

def append(root, event_id):
    return ok(root, "inbox-append", "--event-id", event_id, "--payload", "{}")


def test_inbox_duplicate_event_id_processed_once(tmp_path):
    root = ledger(tmp_path)
    assert append(root, "ev-1")["duplicate"] is False
    assert append(root, "ev-1")["duplicate"] is True
    assert len(list((root / "inbox" / "pending").glob("*.json"))) == 1


def test_inbox_crash_between_consume_and_commit_leaves_event_pending(tmp_path):
    root = ledger(tmp_path)
    append(root, "ev-1")
    r = run(root, "inbox-consume", "--planned-outcome", "dispatch-qa",
            "--inject-crash", "after-consume")
    assert r.returncode == 9
    assert (root / "inbox" / "pending" / "ev-1.json").exists()
    assert not (root / "inbox" / "plans" / "ev-1.json").exists()  # no plan committed
    # re-consume after the crash plans it exactly once
    out = ok(root, "inbox-consume", "--planned-outcome", "dispatch-qa")
    assert out["consumed"] == "ev-1" and out["replayed"] is False


def test_inbox_never_planned_twice(tmp_path):
    root = ledger(tmp_path)
    append(root, "ev-1")
    r = run(root, "inbox-consume", "--planned-outcome", "dispatch-qa",
            "--inject-crash", "after-plan")
    assert r.returncode == 9  # crashed after plan commit, before ack
    plan1 = (root / "inbox" / "plans" / "ev-1.json").read_bytes()
    out = ok(root, "inbox-consume", "--planned-outcome", "DIFFERENT-OUTCOME")
    assert out["replayed"] is True  # existing plan returned, not re-planned
    assert (root / "inbox" / "plans" / "ev-1.json").read_bytes() == plan1


def test_inbox_ack_without_plan_forbidden(tmp_path):
    root = ledger(tmp_path)
    append(root, "ev-1")
    r = run(root, "inbox-ack", "--event-id", "ev-1")
    assert r.returncode == 2  # never ACKed without its planned outcome recorded


def test_inbox_ack_exactly_once_and_reack_idempotent(tmp_path):
    root = ledger(tmp_path)
    append(root, "ev-1")
    ok(root, "inbox-consume", "--planned-outcome", "dispatch-qa")
    assert ok(root, "inbox-ack", "--event-id", "ev-1")["already_acked"] is False
    wm = json.loads((root / "inbox" / "watermark.json").read_text())
    assert wm["processed_count"] == 1 and wm["last_event_id"] == "ev-1"
    assert ok(root, "inbox-ack", "--event-id", "ev-1")["already_acked"] is True
    wm2 = json.loads((root / "inbox" / "watermark.json").read_text())
    assert wm2["processed_count"] == 1  # re-ack does not double-count


# ---------------- action FSM idempotency key ----------------

def transition(root, to, attempt="1", **kw):
    return run(root, "action-transition", "--logical-session", "sess-1",
               "--phase", "qa", "--attempt", attempt, "--to", to, **kw)


def test_fsm_refuses_duplicate_dispatch_for_existing_key(tmp_path):
    root = ledger(tmp_path)
    assert transition(root, "planned").returncode == 0
    assert transition(root, "dispatched").returncode == 0
    r = transition(root, "dispatched")
    assert r.returncode == 2 and "never re-sent" in r.stderr


def test_fsm_terminal_requires_machine_readable_evidence(tmp_path):
    root = ledger(tmp_path)
    transition(root, "planned")
    transition(root, "dispatched")
    transition(root, "acknowledged")
    assert transition(root, "terminal").returncode == 2  # idle/finish alone never completes
    r = run(root, "action-transition", "--logical-session", "sess-1", "--phase", "qa",
            "--attempt", "1", "--to", "terminal", "--evidence", "docs/qa-report.json")
    assert r.returncode == 0


def test_reservation_in_flight_single_writer(tmp_path):
    root = ledger(tmp_path)
    r = run(root, "reserve", "--reservation-id", "res-1", "--account", "orchestrade",
            "--logical-session", "sess-1")
    assert r.returncode == 0
    assert run(root, "reserve", "--reservation-id", "res-1", "--account", "orchestrade",
               "--logical-session", "sess-1").returncode == 2


# ---------------- lease ----------------

def test_lease_foreign_unexpired_refused_expired_succeeds(tmp_path):
    root = ledger(tmp_path)
    ok(root, "lease-acquire", "--holder", "ctl-A", "--ttl-seconds", "3600", now=T0)
    r = run(root, "lease-acquire", "--holder", "ctl-B", "--ttl-seconds", "3600",
            now="2026-08-28T12:30:00Z")
    assert r.returncode == 2  # unexpired foreign lease
    out = ok(root, "lease-acquire", "--holder", "ctl-B", "--ttl-seconds", "3600",
             now="2026-08-28T13:00:01Z")
    assert out["incarnation"] == 2  # takeover only after expiry


# ---------------- F8 error classification ----------------

def test_error_texts_map_to_five_f8_classes(tmp_path):
    root = ledger(tmp_path)
    cases = {
        "You have hit your weekly usage limit.": ("hard_usage_limit", "account_blocked_until"),
        "HTTP 429: too many requests, retry later": ("transient", "retry_backoff_in_place"),
        "401 unauthorized: invalid api key": ("auth", "escalate_class_5"),
        "requested model does not exist": ("model", "model_change_same_account"),
        "segfault in flux capacitor": ("unknown", "mark_suspect"),
    }
    for text, (cls, action) in cases.items():
        out = ok(root, "classify-error", "--text", text)
        assert out == {"class": cls, "action": action}, text


# ---------------- probation ----------------

def test_blocked_probation_eligible_requires_recorded_success(tmp_path):
    root = ledger(tmp_path)
    ok(root, "account-init", "--account", "orchestrade", "--weekly-reset", "2026-09-03T18:00:00Z")
    ok(root, "account-block", "--account", "orchestrade", "--until", "2026-09-03T18:00:00Z")
    # canary result while still blocked (not probation) is refused
    assert run(root, "account-canary-result", "--account", "orchestrade",
               "--result", "success").returncode == 2
    # before the reset instant: not moved
    out = ok(root, "account-observe-reset", now="2026-09-03T17:59:00Z")
    assert out["moved_to_probation"] == []
    out = ok(root, "account-observe-reset", now="2026-09-03T18:00:01Z")
    assert out["moved_to_probation"] == ["orchestrade"]
    out = ok(root, "account-canary-result", "--account", "orchestrade", "--result", "success")
    assert out["state"] == "eligible"


# ---------------- aware-UTC timestamps ----------------

def test_naive_timestamps_rejected(tmp_path):
    root = ledger(tmp_path)
    assert run(root, "lease-status", now="2026-08-28T12:00:00").returncode == 3
    assert run(root, "account-init", "--account", "orchestrade",
               "--weekly-reset", "2026-09-03T18:00:00").returncode == 3


# ---------------- resume-nonce reset-instant gate ----------------

def recovery_setup(tmp_path):
    root = ledger(tmp_path)
    ok(root, "account-init", "--account", "orchestrade", "--weekly-reset", "2026-09-03T18:00:00Z")
    ok(root, "account-block", "--account", "orchestrade", "--until", "2026-09-03T18:00:00Z")
    ok(root, "recovery-record", "--session", "sess-1", "--account", "orchestrade",
       "--original-agent-ids", "agent-orig-1,agent-orig-2",
       "--last-artifact", "docs/dev/dev-report-x.json")
    return root


def test_resume_nonce_gated_on_reset_instant(tmp_path):
    root = recovery_setup(tmp_path)
    # BEFORE the reset instant: queued, ZERO dispatches, no sent-marker, nonce unchanged
    for _ in range(2):
        out = ok(root, "recovery-demand", "--session", "sess-1", now="2026-09-03T17:00:00Z")
        assert out["status"] == "queued_pre_reset"
        assert out["dispatches"] == 0 and out["sent_marker"] is None
        assert out["nonce_consumed"] is False
    rec = json.loads((root / "recovery" / "sess-1.json").read_text())
    assert rec["nonce_consumed"] is False and rec["dispatches"] == 0
    # AFTER the instant: exactly one dispatch, exactly one nonce consumption
    out = ok(root, "recovery-demand", "--session", "sess-1", now="2026-09-03T18:00:05Z")
    assert out["status"] == "dispatched" and out["dispatches"] == 1
    out = ok(root, "recovery-demand", "--session", "sess-1", now="2026-09-03T19:00:00Z")
    assert out["status"] == "nonce_already_consumed" and out["dispatches"] == 1


# ---------------- three-account distinct-reset probation fixture ----------------

RESETS = {  # pairwise-distinct weekly reset instants (live-observed pattern)
    "orchestrade": "2026-09-03T18:00:00Z",
    "yugoge": "2026-09-02T14:00:00Z",
    "yugetang": "2026-09-01T09:00:00Z",
}


def three_blocked_accounts(tmp_path):
    root = ledger(tmp_path)
    assert len(set(RESETS.values())) == 3  # pairwise distinct
    for name, reset in RESETS.items():
        ok(root, "account-init", "--account", name, "--weekly-reset", reset)
        ok(root, "account-block", "--account", name, "--until", reset)
    return root


def test_only_the_crossed_account_enters_probation_success_reopens(tmp_path):
    root = three_blocked_accounts(tmp_path)
    # advance the fake clock across ONE reset (yugetang) only
    out = ok(root, "account-observe-reset", now="2026-09-01T09:00:01Z")
    assert out["moved_to_probation"] == ["yugetang"]
    accounts = json.loads((root / "accounts.json").read_text())["accounts"]
    assert accounts["yugetang"]["state"] == "probation"
    assert accounts["yugetang"]["probation_concurrency"] == 1  # single-concurrency
    assert accounts["orchestrade"]["state"] == "blocked_until"
    assert accounts["yugoge"]["state"] == "blocked_until"
    out = ok(root, "account-canary-result", "--account", "yugetang", "--result", "success")
    assert out["state"] == "eligible"  # one recorded success reopens


def test_canary_failure_reblocks_without_busy_loop(tmp_path):
    root = three_blocked_accounts(tmp_path)
    ok(root, "account-observe-reset", now="2026-09-01T09:00:01Z")
    out = ok(root, "account-canary-result", "--account", "yugetang", "--result", "failure",
             now="2026-09-01T09:30:00Z")
    assert out["state"] == "blocked_until"
    # no busy-loop: an immediate re-sweep does NOT re-probate the failed account
    out = ok(root, "account-observe-reset", now="2026-09-01T09:31:00Z")
    assert "yugetang" not in out["moved_to_probation"]
    accounts = json.loads((root / "accounts.json").read_text())["accounts"]
    assert accounts["yugetang"]["state"] == "blocked_until"


# ---------------- scheduling-decision fixtures (M9 contract) ----------------

def ingest_remaining(root, remaining_pct):
    providers = [{"providerId": "claude", "displayName": "Claude · orchestrade",
                  "status": "available",
                  "windows": [{"id": "weekly", "usedPct": 100 - remaining_pct,
                               "remainingPct": remaining_pct,
                               "resetsAt": "2026-09-03T18:00:00Z"}]}]
    ok(root, "usage-ingest", stdin=json.dumps(providers))


def decide(root, task_class):
    return ok(root, "scheduling-decision", "--account", "orchestrade",
              "--task-class", task_class)


def test_scheduling_plentiful_quality_uses_fable_5(tmp_path):
    root = ledger(tmp_path)
    ingest_remaining(root, 86)  # plentiful (>= 50)
    out = decide(root, "quality")
    assert (out["tier"], out["action"], out["model"]) == ("plentiful", "dispatch", "fable 5")


def test_scheduling_fast_sonnet_general_opus(tmp_path):
    root = ledger(tmp_path)
    ingest_remaining(root, 86)
    assert decide(root, "fast")["model"] == "sonnet 5"
    assert decide(root, "general")["model"] == "opus 5"


def test_scheduling_ladder_degrades_as_tiers_tighten(tmp_path):
    root = ledger(tmp_path)
    seen = []
    for remaining in (86, 30, 10):  # plentiful -> normal -> near_limit
        ingest_remaining(root, remaining)
        seen.append(decide(root, "quality")["model"])
    assert seen == ["fable 5", "opus 5", "sonnet 5"]  # the exact user-verbatim ladder


def test_scheduling_near_limit_boundary_switch_or_degrade(tmp_path):
    root = ledger(tmp_path)
    ingest_remaining(root, 10)  # near_limit (<= 15)
    out = decide(root, "general")
    assert out["tier"] == "near_limit" and out["action"] == "switch_or_degrade"
    assert out["switch_boundary_only"] is True


def test_scheduling_hard_limit_stop_or_switch_never_same_account_degrade(tmp_path):
    root = ledger(tmp_path)
    ingest_remaining(root, 3)  # exhausted (<= 5)
    out = decide(root, "quality")
    assert out["action"] == "stop_or_switch"
    assert out["model"] is None  # no same-account degrade offered
    assert out["same_account_degrade_forbidden"] is True


# ---------------- RUNTIME-AC14: recovery identity, full criterion ----------------

def test_ac14_positive_exact_persisted_set_judged_recovered(tmp_path):
    root = recovery_setup(tmp_path)  # persists TWO original subagent IDs
    rec = json.loads((root / "recovery" / "sess-1.json").read_text())
    assert rec["original_agent_ids"] == ["agent-orig-1", "agent-orig-2"]  # comparator
    r = run(root, "recovery-judge", "--session", "sess-1",
            "--evidence", json.dumps(["agent-orig-1", "agent-orig-2"]))
    assert r.returncode == 0  # an always-reject implementation fails here
    assert json.loads(r.stdout)["recovered"] is True


def test_ac14_one_missing_original_judged_failure(tmp_path):
    root = recovery_setup(tmp_path)
    r = run(root, "recovery-judge", "--session", "sess-1",
            "--evidence", json.dumps(["agent-orig-1"]))
    assert r.returncode != 0
    v = json.loads(r.stdout)
    assert v["recovered"] is False and v["missing_original_ids"] == ["agent-orig-2"]


def test_ac14_replacement_agent_id_judged_failure(tmp_path):
    root = recovery_setup(tmp_path)
    r = run(root, "recovery-judge", "--session", "sess-1",
            "--evidence", json.dumps(["agent-orig-1", "agent-REPLACEMENT"]))
    assert r.returncode != 0
    v = json.loads(r.stdout)
    assert v["recovered"] is False and "agent-REPLACEMENT" in v["unexpected_ids"]


def test_ac14_outer_session_only_judged_failure(tmp_path):
    root = recovery_setup(tmp_path)
    r = run(root, "recovery-judge", "--session", "sess-1",
            "--evidence", json.dumps(["outer-session-resumed"]))
    assert r.returncode != 0
    assert json.loads(r.stdout)["recovered"] is False


def test_ac14_in_session_quota_hit_asserts_class_5_escalation(tmp_path):
    root = recovery_setup(tmp_path)
    rec = json.loads((root / "recovery" / "sess-1.json").read_text())
    assert rec["escalation"]["class"] == 5  # human-only /restart domain (F10)


# ---------------- dossier + generation journal (BUILD-AC06 / RUNTIME-AC16) ----------------

def valid_dossier():
    """Composed per RUNTIME-AC16's own adversarial scenario: multiple lanes,
    a pending permission, a superseded decision record, an interrupted child."""
    return {
        "schema": "paseo-dossier.v1",
        "logical_task_id": "task-20260828-112025",
        "session_incarnations": [
            {"kind": "paseo_agent", "id": "agent-1"},
            {"kind": "claude_session", "id": "claude-sess-1"},
        ],
        "spec_fingerprint": {"command_sha256": SHA_A, "spec_sha256": SHA_B},
        "lanes": [
            {"lane_id": "R-A", "status": "done", "retries": 0},
            {"lane_id": "R-B", "status": "in_progress", "retries": 1},
        ],
        "ac_status": [{"ac_id": "BUILD-AC01", "status": "pass"}],
        "artifacts": [{"path": "docs/dev/dev-report-x.json", "sha256": SHA_C}],
        "event_watermark": {"processed_count": 3, "last_event_id": "ev-3",
                            "observed_at": T0},
        "last_confirmed_action": {"action": "dispatched lane R-B",
                                  "artifact": "docs/dev/dev-report-x.json"},
        "side_effects": [{"desc": "wrote dev report", "at": T0}],
        "permissions": [{"id": "perm-1", "state": "pending"}],
        "routing_generation": {"account": "orchestrade", "model": "fable 5",
                               "generation": 2},
        "next_legal_transition": "qa-verify",
        "interrupted_children": [{"agent_id": "child-1", "reason": "quota interrupt"}],
        "verbatim_zone": {"entries": [
            {"ts": T0, "kind": "user_requirement",
             "text": "三个账号每个账号每周重置时间不同", "sha256": SHA_D},
        ]},
        "derived_zone": {"entries": [{"derived_summary": True, "text": "summary"}]},
        "decision_journal": [
            {"actor": "controller", "time": T0, "scope": "lane R-B",
             "rationale": "initial plan", "evidence": "ticket", "supersedes": None,
             "status": "superseded"},
            {"actor": "controller", "time": "2026-08-28T12:30:00Z", "scope": "lane R-B",
             "rationale": "revised plan", "evidence": "qa report", "supersedes": "0",
             "status": "active"},
        ],
    }


def write_dossier(tmp_path, obj, name="dossier.json"):
    p = tmp_path / name
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1))
    return p


def committed_root(tmp_path):
    root = ledger(tmp_path)
    d = write_dossier(tmp_path, valid_dossier())
    ok(root, "generation-commit", "--dossier", str(d))
    return root


def generation_snapshot(root):
    """Byte-level snapshot of (generation set, current-generation content
    digest, committed markers) — file names AND file bytes."""
    gen_dir = root / "generations"
    snap = {}
    for p in sorted(gen_dir.iterdir()):
        snap[p.name] = p.read_bytes()
    return snap


def test_valid_dossier_commits_and_verifies(tmp_path):
    root = committed_root(tmp_path)
    assert (root / "generations" / "current").read_text().strip() == "1"
    assert (root / "generations" / "1.committed").exists()
    assert run(root, "generation-verify").returncode == 0


F12_REQUIRED = [
    "schema", "logical_task_id", "session_incarnations", "spec_fingerprint",
    "lanes", "ac_status", "artifacts", "event_watermark", "last_confirmed_action",
    "side_effects", "permissions", "routing_generation", "next_legal_transition",
    "verbatim_zone", "derived_zone", "decision_journal",
]


def mutations():
    for field in F12_REQUIRED:
        obj = valid_dossier()
        del obj[field]
        yield f"missing:{field}", obj
    # malformed decision-journal records (F13: all seven fields, valid status)
    obj = valid_dossier()
    del obj["decision_journal"][0]["rationale"]
    yield "journal:missing-rationale", obj
    obj = valid_dossier()
    obj["decision_journal"][1]["status"] = "not-a-status"
    yield "journal:bad-status", obj
    obj = valid_dossier()
    obj["decision_journal"][0]["time"] = "2026-08-28T12:00:00"  # naive ts
    yield "journal:naive-time", obj
    obj = valid_dossier()
    obj["decision_journal"][0]["time"] = "2026-02-30T12:00:00Z"  # impossible date
    yield "journal:impossible-date", obj


def test_every_mutation_fails_validation_and_blocks_publication(tmp_path):
    root = committed_root(tmp_path)
    before = generation_snapshot(root)
    for label, obj in mutations():
        d = write_dossier(tmp_path, obj, name="mutated.json")
        rv = run(root, "dossier-validate", "--file", str(d))
        assert rv.returncode != 0, f"{label}: validation must fail"
        rc = run(root, "generation-commit", "--dossier", str(d))
        assert rc.returncode != 0, f"{label}: generation-commit must fail"
        after = generation_snapshot(root)
        assert after == before, (
            f"{label}: generation set / current digest / committed markers "
            f"must be byte-identical after a rejected commit"
        )


def test_generation_commit_crash_leaves_prior_generation_current(tmp_path):
    root = committed_root(tmp_path)
    d = write_dossier(tmp_path, valid_dossier(), name="gen2.json")
    crashed_gen_bytes = {}
    for point in ("after-write", "after-rename", "before-pointer"):
        r = run(root, "generation-commit", "--dossier", str(d), "--inject-crash", point)
        assert r.returncode == 9, point
        cur = (root / "generations" / "current").read_text().strip()
        assert cur == "1", f"{point}: prior generation must stay current"
        # an uncommitted generation is never published as current
        assert run(root, "generation-verify").returncode == 0
        for p in (root / "generations").glob("*.json"):
            if p.stem.isdigit() and p.stem != "1":
                crashed_gen_bytes[p.name] = p.read_bytes()
    # a clean retry allocates a FRESH generation above everything on disk —
    # crash leftovers are retained, never reused or overwritten
    out = ok(root, "generation-commit", "--dossier", str(d))
    final_gen = out["generation"]
    assert final_gen > 1
    assert (root / "generations" / "current").read_text().strip() == str(final_gen)
    assert run(root, "generation-verify").returncode == 0
    for name, before in crashed_gen_bytes.items():
        if name != f"{final_gen}.json":
            assert (root / "generations" / name).read_bytes() == before, (
                f"{name}: crash-leftover generation must never be overwritten"
            )


def test_generation_hash_mismatch_fails_validation(tmp_path):
    root = committed_root(tmp_path)
    gen = root / "generations" / "1.json"
    rec = json.loads(gen.read_text())
    rec["dossier"]["logical_task_id"] = "tampered"
    gen.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    assert run(root, "generation-verify").returncode != 0


# ---------------- codex-review hardening (task 20260828-112025-b consult) ----------------

def test_inbox_ack_crash_points_are_repairable(tmp_path):
    """codex finding 3: the ACK record is authoritative; re-ACK repairs the
    pending unlink and the derived watermark after a crash at either
    post-commit boundary."""
    root = ledger(tmp_path)
    append(root, "ev-1")
    ok(root, "inbox-consume", "--planned-outcome", "dispatch-qa")
    r = run(root, "inbox-ack", "--event-id", "ev-1", "--inject-crash", "after-acked-write")
    assert r.returncode == 9
    assert (root / "inbox" / "acked" / "ev-1.json").exists()
    assert (root / "inbox" / "pending" / "ev-1.json").exists()  # unlink not yet done
    out = ok(root, "inbox-ack", "--event-id", "ev-1")  # idempotent repair
    assert out["already_acked"] is True
    assert not (root / "inbox" / "pending" / "ev-1.json").exists()
    wm = json.loads((root / "inbox" / "watermark.json").read_text())
    assert wm == {"processed_count": 1, "last_event_id": "ev-1"}
    # second crash boundary: watermark rebuild interrupted
    append(root, "ev-2")
    ok(root, "inbox-consume", "--planned-outcome", "dispatch-qa")
    r = run(root, "inbox-ack", "--event-id", "ev-2", "--inject-crash", "after-pending-unlink")
    assert r.returncode == 9
    wm = json.loads((root / "inbox" / "watermark.json").read_text())
    assert wm["processed_count"] == 1  # stale, but repairable
    ok(root, "inbox-ack", "--event-id", "ev-2")
    wm = json.loads((root / "inbox" / "watermark.json").read_text())
    assert wm == {"processed_count": 2, "last_event_id": "ev-2"}


def test_blocked_account_never_dispatches_even_with_plentiful_reading(tmp_path):
    """codex finding 4: eligibility state gates the scheduling decision
    before the usage tier."""
    root = ledger(tmp_path)
    ingest_remaining(root, 86)  # plentiful reading persisted
    ok(root, "account-block", "--account", "orchestrade", "--until", "2026-09-03T18:00:00Z")
    out = decide(root, "quality")
    assert out["state"] == "blocked_until"
    assert out["action"] == "stop_or_switch" and out["model"] is None
    assert out["same_account_degrade_forbidden"] is True


def test_classify_error_with_account_persists_consequence(tmp_path):
    root = ledger(tmp_path)
    ok(root, "account-init", "--account", "orchestrade", "--weekly-reset", "2026-09-03T18:00:00Z")
    out = ok(root, "classify-error", "--text", "You have hit your weekly usage limit.",
             "--account", "orchestrade")
    assert out["account_state"] == "blocked_until"
    accounts = json.loads((root / "accounts.json").read_text())["accounts"]
    assert accounts["orchestrade"]["state"] == "blocked_until"
    assert accounts["orchestrade"]["blocked_until"] == "2026-09-03T18:00:00Z"
    out = ok(root, "classify-error", "--text", "segfault in flux capacitor",
             "--account", "yugoge")
    assert out["account_state"] == "suspect"


def test_probation_reservation_is_single_concurrency(tmp_path):
    """codex finding 6: one active canary reservation while in probation."""
    root = three_blocked_accounts(tmp_path)
    ok(root, "account-observe-reset", now="2026-09-01T09:00:01Z")  # yugetang -> probation
    r = run(root, "reserve", "--reservation-id", "res-1", "--account", "yugetang",
            "--logical-session", "sess-1")
    assert r.returncode == 0
    r = run(root, "reserve", "--reservation-id", "res-2", "--account", "yugetang",
            "--logical-session", "sess-2")
    assert r.returncode == 2 and "single-concurrency probation" in r.stderr


def test_recovery_demand_without_reliable_gate_fails_closed(tmp_path):
    """codex finding 7: no reset instant / nextEligibleAt -> the gate cannot
    be confirmed passed; the demand queues as class-5 blockage, nonce intact."""
    root = ledger(tmp_path)  # orchestrade never account-init'ed: no gate at all
    ok(root, "recovery-record", "--session", "sess-1", "--account", "orchestrade",
       "--original-agent-ids", "agent-orig-1,agent-orig-2")
    out = ok(root, "recovery-demand", "--session", "sess-1", now="2026-09-09T00:00:00Z")
    assert out["status"] == "queued_no_reliable_gate"
    assert out["escalation_class"] == 5
    assert out["dispatches"] == 0 and out["sent_marker"] is None
    assert out["nonce_consumed"] is False


def test_fsm_exact_successor_and_terminal_immutability(tmp_path):
    """codex finding 10: no skipped edges; terminal is immutable."""
    root = ledger(tmp_path)
    transition(root, "planned")
    r = transition(root, "acknowledged")  # skips dispatched
    assert r.returncode == 2 and "exact successor" in r.stderr
    transition(root, "dispatched")
    transition(root, "acknowledged")
    r = run(root, "action-transition", "--logical-session", "sess-1", "--phase", "qa",
            "--attempt", "1", "--to", "terminal", "--evidence", "docs/qa-report.json")
    assert r.returncode == 0
    r = run(root, "action-transition", "--logical-session", "sess-1", "--phase", "qa",
            "--attempt", "1", "--to", "terminal", "--evidence", "docs/other.json")
    assert r.returncode == 2 and "immutable" in r.stderr


def test_cross_generation_append_only_invariants(tmp_path):
    """codex finding 13: verbatim prefix, journal supersession-only changes,
    monotonic watermark — all judged against the current generation."""
    root = committed_root(tmp_path)
    before = generation_snapshot(root)
    # (a) verbatim entry rewritten -> refused
    obj = valid_dossier()
    obj["verbatim_zone"]["entries"][0]["text"] = "REWRITTEN"
    obj["verbatim_zone"]["entries"][0]["sha256"] = SHA_A
    d = write_dossier(tmp_path, obj, name="vz-rewrite.json")
    r = run(root, "generation-commit", "--dossier", str(d))
    assert r.returncode == 2 and "append-only" in r.stderr
    # (b) watermark lowered -> refused
    obj = valid_dossier()
    obj["event_watermark"]["processed_count"] = 1
    d = write_dossier(tmp_path, obj, name="wm-lower.json")
    r = run(root, "generation-commit", "--dossier", str(d))
    assert r.returncode == 2 and "monotonic" in r.stderr
    assert generation_snapshot(root) == before  # nothing published
    # (c) legal evolution: append verbatim entry, supersede a decision,
    # append the superseding record, advance the watermark
    obj = valid_dossier()
    obj["verbatim_zone"]["entries"].append(
        {"ts": "2026-08-28T13:00:00Z", "kind": "revision", "text": "追加修订", "sha256": SHA_B})
    obj["decision_journal"][1]["status"] = "superseded"
    obj["decision_journal"].append(
        {"actor": "controller", "time": "2026-08-28T13:00:00Z", "scope": "lane R-B",
         "rationale": "supersede r2", "evidence": "new qa report", "supersedes": "1",
         "status": "active"})
    obj["event_watermark"]["processed_count"] = 4
    d = write_dossier(tmp_path, obj, name="legal-evolution.json")
    assert run(root, "generation-commit", "--dossier", str(d)).returncode == 0


def test_intent_queue_resolve_lifecycle(tmp_path):
    """codex finding 1: co-drive intents reach their terminal states through
    the sole mutation surface."""
    root = ledger(tmp_path)
    ok(root, "intent-queue", "--intent-id", "int-1", "--session", "sess-1",
       "--payload", "{\"prompt\": \"continue\"}", "--observed-state", "user_turn_running")
    r = run(root, "intent-queue", "--intent-id", "int-1", "--session", "sess-1",
            "--payload", "{}", "--observed-state", "idle")
    assert r.returncode == 2  # duplicate intent id
    out = ok(root, "intent-resolve", "--intent-id", "int-1", "--outcome", "superseded")
    assert out["status"] == "superseded"
    r = run(root, "intent-resolve", "--intent-id", "int-1", "--outcome", "applied")
    assert r.returncode == 2  # terminal intents are immutable


def test_session_flag_suspect_persists_turn_and_updatecount(tmp_path):
    root = ledger(tmp_path)
    r = run(root, "session-flag", "--session", "sess-1", "--flag", "suspect")
    assert r.returncode == 1  # turn-id + update-count required
    ok(root, "session-flag", "--session", "sess-1", "--flag", "suspect",
       "--turn-id", "turn-9", "--update-count", "73662")
    rec = json.loads((root / "sessions" / "sess-1.json").read_text())
    assert rec["suspect"]["active_turn_id"] == "turn-9"
    assert rec["suspect"]["update_count"] == 73662
    assert rec["suspect"]["suspect_since"] == "2026-08-28T12:00:00Z"
    ok(root, "session-flag", "--session", "sess-1", "--flag", "clear")
    rec = json.loads((root / "sessions" / "sess-1.json").read_text())
    assert "suspect" not in rec


def test_dossier_write_publishes_only_valid_sidecars(tmp_path):
    root = ledger(tmp_path)
    md = tmp_path / "dossier.md"
    md.write_text("# session dossier\n")
    bad = valid_dossier()
    del bad["lanes"]
    bad_path = write_dossier(tmp_path, bad, name="bad-sidecar.json")
    r = run(root, "dossier-write", "--session", "sess-1", "--md-file", str(md),
            "--sidecar-file", str(bad_path))
    assert r.returncode == 2
    assert list((root / "dossiers").iterdir()) == []  # nothing published
    good_path = write_dossier(tmp_path, valid_dossier(), name="good-sidecar.json")
    ok(root, "dossier-write", "--session", "sess-1", "--md-file", str(md),
       "--sidecar-file", str(good_path))
    assert (root / "dossiers" / "sess-1.md").exists()
    assert (root / "dossiers" / "sess-1.json").exists()


def test_rehydration_barrier_blocks_mutations_until_full_attestation(tmp_path):
    """RUNTIME-AC21 made executable: while the barrier is set every pipeline
    mutation refuses; clearing requires all four reload attestations; the
    usage-read reload path stays open."""
    root = ledger(tmp_path)
    ok(root, "barrier-enter")
    r = transition(root, "planned")
    assert r.returncode == 2 and "rehydration barrier" in r.stderr
    r = run(root, "inbox-append", "--event-id", "ev-1", "--payload", "{}")
    assert r.returncode == 2
    ingest_remaining(root, 86)  # live-state reload is allowed under the barrier
    r = run(root, "barrier-clear", "--spec-reloaded", "--generation-reloaded")
    assert r.returncode == 2  # partial attestation refused
    ok(root, "barrier-clear", "--spec-reloaded", "--generation-reloaded",
       "--anchors-reloaded", "--live-state-reloaded")
    assert transition(root, "planned").returncode == 0


def test_canary_failure_after_multi_week_downtime_advances_gate_past_now(tmp_path):
    """codex finding 18: the re-block gate is always strictly in the future."""
    root = ledger(tmp_path)
    ok(root, "account-init", "--account", "orchestrade", "--weekly-reset", "2026-08-06T00:00:00Z")
    ok(root, "account-block", "--account", "orchestrade", "--until", "2026-08-06T00:00:00Z")
    ok(root, "account-observe-reset", now="2026-09-01T00:00:00Z")
    out = ok(root, "account-canary-result", "--account", "orchestrade", "--result", "failure",
             now="2026-09-01T00:00:00Z")
    assert out["state"] == "blocked_until"
    accounts = json.loads((root / "accounts.json").read_text())["accounts"]
    from datetime import datetime, timezone
    gate = datetime.fromisoformat(accounts["orchestrade"]["blocked_until"].replace("Z", "+00:00"))
    assert gate > datetime(2026, 9, 1, tzinfo=timezone.utc)  # strictly future, no busy-loop


# ---------------- source audit: forbidden slash-command invocations ----------------

def code_tokens(path):
    """Source with comments and string literals stripped (tokenize-based)."""
    out = []
    with open(path, "rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    return " ".join(out)


def test_source_audit_no_forbidden_slash_command_invocations():
    """Fixtures only: /dev, /close, /commit and human-only /restart are never
    invoked by these test files (agents/ba.md Forbidden Pattern 6). Audited on
    code tokens (comments/strings stripped), so naming them here is fine.
    Orchestrator-driven Agent-tool dispatch is normal control flow and is not
    in scope of this audit."""
    forbidden = ["/" + w for w in ("dev", "close", "commit", "restart")]
    for target in [Path(__file__), REPO / "tests" / "test_paseo_usage_read.py"]:
        code = code_tokens(target)
        for token in forbidden:
            assert token not in code, f"{target.name} invokes forbidden {token}"


# ---------------- wake channel: recurring arming + delivery proof +
# ---------------- watermark ageing + teardown (task 20260831-031316) ----------------

def wake_arm(root, *, kind="paseo_heartbeat", channel_id="hb-1",
             cron="12,57 * * * *", tz="UTC", role="tick", max_runs=None,
             verify_window_days=None, now=T0):
    args = ["wake-arm", "--channel-kind", kind, "--channel-id", channel_id,
            "--cron", cron, "--timezone", tz, "--role", role]
    if max_runs is not None:
        args += ["--max-runs", str(max_runs)]
    if verify_window_days is not None:
        args += ["--verify-window-days", str(verify_window_days)]
    return run(root, *args, now=now)


def armed_token(root):
    return wake_record(root)["arming_token"]


def delivered_claim(root, *, channel_id="hb-1", token=None):
    """argv for a delivery claim naming the CURRENTLY armed arming_token --
    the only claim that still certifies once proof is bound to the arming."""
    return ["wake-observe", "--delivered", "--channel-id", channel_id,
            "--arming-token", armed_token(root) if token is None else token]


def test_wake_arm_persists_record_and_journals(tmp_path):
    root = ledger(tmp_path)
    assert wake_arm(root).returncode == 0
    rec = json.loads((root / "wake.json").read_text())
    assert rec["channel_kind"] == "paseo_heartbeat"
    assert rec["channel_id"] == "hb-1"
    assert rec["cron"] == "12,57 * * * *"
    assert rec["timezone"] == "UTC"
    assert rec["role"] == "tick"
    # aware-UTC true-cron next fire: minutes {12, 57}, first strictly after 12:00Z
    assert rec["expected_next_fire"] == "2026-08-28T12:12:00Z"
    ops = [json.loads(line)["op"]
           for line in (root / "journal.ndjson").read_text().strip().splitlines()]
    assert "wake-arm" in ops


def test_wake_arm_tz_rule_source_default_now_resolution_verifies(tmp_path):
    """Regression: the ledger and vendor offset tables both stamp their FIRST
    run with the literal `now` instant, in the documented canonical form of
    whole-second integers only. The default now-resolution path (no --now at
    all, so the CLI resolves datetime.now(utc) itself, which carries
    microseconds) leaked that sub-second fraction into the vendor side only,
    so the SAME instant compared unequal at two precisions
    (e.g. ledger='1789442655:0' vendor='1789442655.201:0') and was misread as
    two disagreeing timezone rule sources."""
    root = ledger(tmp_path)
    r = wake_arm(root, cron="12,57 * * * *", now=None)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["tz_rule_source_verified"] is True


def test_wake_arm_tz_rule_source_explicit_subsecond_now_verifies(tmp_path):
    """Same false-disagreement precision mismatch as the default-now
    regression above, but hit via an explicit --now that itself carries a
    microsecond fraction -- the defect is in the comparison, not in how
    `now` was obtained."""
    root = ledger(tmp_path)
    r = wake_arm(root, cron="12,57 * * * *", now="2026-08-28T12:00:00.500000Z")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["tz_rule_source_verified"] is True


def test_wake_arm_refuses_tick_maxruns_one_but_allows_test_oneshot(tmp_path):
    root = ledger(tmp_path)
    r = wake_arm(root, max_runs=1)  # role=tick: one-shot arming forbidden
    assert r.returncode == 2 and "forbidden" in r.stderr
    assert not (root / "wake.json").exists()
    # one-shots are reserved for explicit channel tests (teardown + proof-by-delivery)
    assert wake_arm(root, role="test", max_runs=1).returncode == 0


def test_wake_arm_refuses_unsupported_cron_fail_closed(tmp_path):
    root = ledger(tmp_path)
    for bad in ["@hourly", "* * * *", "* * * * * *", "1-5/2 * * * *",
                "60 * * * *", "mon * * * *", "*/0 * * * *"]:
        assert wake_arm(root, cron=bad).returncode == 2, bad
    assert not (root / "wake.json").exists()
    assert wake_arm(root, tz="Not/AZone").returncode == 2  # unknown IANA timezone


def test_wake_arm_blocked_by_rehydration_barrier(tmp_path):
    root = ledger(tmp_path)
    ok(root, "barrier-enter")
    r = wake_arm(root)
    assert r.returncode == 2 and "rehydration barrier" in r.stderr


def test_wake_observe_missed_star45_true_cron_consolidated_event(tmp_path):
    root = ledger(tmp_path)
    assert wake_arm(root, cron="*/45 * * * *", now="2026-08-28T12:50:00Z").returncode == 0
    rec = json.loads((root / "wake.json").read_text())
    # TRUE cron: */45 means minutes {0, 45}; next after 12:50 is 13:00 (NOT 13:35)
    assert rec["expected_next_fire"] == "2026-08-28T13:00:00Z"
    out = ok(root, "wake-observe", now="2026-08-28T15:10:00Z")
    # scheduled fires 13:00, 13:45, 14:00, 14:45 (alternating 45/15-minute gaps)
    # all have deadline (+15 min slack) before 15:10; 15:00's deadline 15:15 has
    # not passed -> exactly 4 missed, consolidated into ONE inbox event
    assert out["verdict"] == "missed"
    assert out["missed_fires"] == 4
    assert out["needs_rearm"] is True
    # 15:00 is the newest fire in this batch and its OWN grace (deadline
    # 15:15) has not elapsed -- the watermark must stay AT 15:00, not jump
    # past it to 15:45, so a later observation still gets 15:00 its own fair
    # chance to resolve (on_time via --delivered, or missed once 15:15
    # genuinely passes). See test_wake_observe_newest_fire_survives_to_resolve.
    assert out["expected_next_fire"] == "2026-08-28T15:00:00Z"
    pend = list((root / "inbox" / "pending").glob("wake-missed-*.json"))
    assert len(pend) == 1
    payload = json.loads(pend[0].read_text())["payload"]
    assert payload["type"] == "wake_channel_missed"
    assert payload["missed_fires"] == 4
    assert "wake_channel_missed" in (root / "journal.ndjson").read_text()


def test_wake_observe_newest_fire_survives_to_resolve_after_older_miss(tmp_path):
    """Task 20260904-181435 (second, independent defect on this file): the
    watermark-advance branch used to jump straight to
    cron_next_fire(spec, now, tz) whenever ANY fire in the observed batch
    aged into 'missed' -- even when the batch's OWN newest fire had not yet
    had its grace period elapse. That orphaned the newest fire: a genuine
    --delivered claim arriving moments later, still well inside that fire's
    own slack window, found expected_next_fire already advanced past it
    (fires=[]) and was misreported 'non_proving' instead of 'on_time'.

    Live reproduction that pinned this exact timeline (real CLI, real
    ledger root): channel armed 2026-09-15T03:54:11Z on '12,57 * * * *';
    03:57 check (mid-window) -> pending, missed_fires=0; 04:12 check
    (next boundary) -> missed, missed_fires=1 (the 03:57 fire, whose own
    15-minute grace genuinely elapsed by 04:12) -- this part is CORRECT,
    doctrine-mandated behaviour (manual_wake_observation: without-delivered
    in commands/paseo-daemon.md's wake-doctrine block), not a bug: nothing
    ever certified 03:57's delivery, and a manual/non-delivered observation
    is never itself proof of delivery. The actual bug was one level deeper:
    the SAME 04:12 fire -- the batch's newest member, itself still fully
    inside its own 04:12-04:27 grace window at observation time -- got
    silently discarded by the watermark jumping straight to 04:57, so a
    delivery claim for 04:12 arriving seconds later could never resolve.
    """
    root = ledger(tmp_path)
    assert wake_arm(root, cron="12,57 * * * *",
                    now="2026-09-15T03:54:11Z").returncode == 0
    token = armed_token(root)

    # tick 1: mid-window manual check -- correctly pending, nothing aged out
    first = ok(root, "wake-observe", now="2026-09-15T03:57:05Z")
    assert first["verdict"] == "pending"
    assert first["missed_fires"] == 0
    assert first["expected_next_fire"] == "2026-09-15T03:57:00Z"

    # tick 2: next boundary -- 03:57's own grace (deadline 04:12:00) has
    # genuinely elapsed, so it correctly ages to missed. This is the ONLY
    # fire judged: 04:12:00 (the newest fire in this batch) is NOT itself
    # past its own grace (deadline 04:27:00) and must not be swept away.
    second = ok(root, "wake-observe", now="2026-09-15T04:12:03Z")
    assert second["verdict"] == "missed"
    assert second["missed_fires"] == 1
    assert second["needs_rearm"] is True
    # the fix: watermark stays AT the still-open newest fire, not past it
    assert second["expected_next_fire"] == "2026-09-15T04:12:00Z"

    # tick 3: the 04:12 fire actually delivers a few seconds later, well
    # inside its own grace (deadline 04:27:00). Pre-fix this reported
    # 'non_proving' (fires=[] because the watermark had already jumped to
    # 04:57); post-fix it must resolve on_time, because 04:12 was never
    # itself judged missed.
    third = ok(root, "wake-observe", "--delivered", "--channel-id", "hb-1",
              "--arming-token", token, now="2026-09-15T04:12:10Z")
    assert third["verdict"] == "on_time"
    assert third["expected_next_fire"] == "2026-09-15T04:57:00Z"


def test_wake_observe_parks_at_first_unjudged_fire_not_the_newest(tmp_path):
    """Task 20260904-181435 (third defect on this file, found by the
    independent QA review of the second fix): parking the watermark at
    `fires[-1]` rescued only the NEWEST still-open fire and silently dropped
    every OTHER fire that was also elapsed-but-still-in-grace. `missed_fires`
    is always a prefix of `fires`, so the unjudged remainder is
    fires[len(missed_fires):] -- which has more than one element exactly when
    the cron interval is SHORTER than wake_slack_minutes. Every earlier
    regression test for this branch used '12,57 * * * *' (gaps of 15 and 45
    minutes against a 15-minute slack), under which at most ONE fire is ever
    elapsed-but-in-grace; fires[len(missed_fires):-1] was therefore always
    empty and the gap was structurally unreachable from those crons.

    DISCRIMINATING BY CONSTRUCTION -- the same 3-tick timeline scores:
      advance past the batch (pre-both-fixes) : 14 + 14 + 14 = 42
      park at fires[-1]      (first attempt)  : 14 + 15 + 15 = 44
      park at fires[k], k=len(missed_fires)   : 14 + 30 + 30 = 74
    74 is the ground truth: armed 07:00 on a 1-minute cron, every fire from
    07:01 through 08:14 has had its own 15-minute grace expire by the final
    08:30 observation (59 fires in 07:01..07:59 plus 15 in 08:00..08:14).
    Undercounting here is a fail-open liveness result -- the same failure
    mode test_wake_observe_counts_fall_back_for_every_hour_form exists for.
    """
    root = ledger(tmp_path)
    assert wake_arm(root, cron="* * * * *", tz="UTC",
                    now="2026-09-15T07:00:00Z").returncode == 0
    assert wake_record(root)["expected_next_fire"] == "2026-09-15T07:01:00Z"

    # tick 1 -- fires 07:01..07:30. Judged missed are those past their own
    # 15-minute deadline, i.e. strictly before 07:15 -> 07:01..07:14 = 14.
    # The remaining 16 are still inside their own grace, so the watermark
    # parks at the FIRST of them (07:15), not at the newest (07:30).
    first = ok(root, "wake-observe", now="2026-09-15T07:30:00Z")
    assert first["verdict"] == "missed"
    assert first["missed_fires"] == 14
    assert first["expected_next_fire"] == "2026-09-15T07:15:00Z"

    # tick 2 -- the window resumes at 07:15, so the 15 fires 07:15..07:29
    # that fires[-1]-parking discarded are still present and age out here
    # with the rest: 07:15..07:44 = 30. Parking at fires[-1] scored 15.
    second = ok(root, "wake-observe", now="2026-09-15T08:00:00Z")
    assert second["verdict"] == "missed"
    assert second["missed_fires"] == 30
    assert second["expected_next_fire"] == "2026-09-15T07:45:00Z"

    # tick 3 -- 07:45..08:14 = 30
    third = ok(root, "wake-observe", now="2026-09-15T08:30:00Z")
    assert third["verdict"] == "missed"
    assert third["missed_fires"] == 30
    assert third["expected_next_fire"] == "2026-09-15T08:15:00Z"

    assert wake_record(root)["missed_total"] == 74

    # no fire counted twice and none silently dropped: the three consolidated
    # events tile 07:01..08:14 contiguously, with no gap and no overlap.
    pend = sorted((root / "inbox" / "pending").glob("wake-missed-*.json"))
    payloads = sorted((json.loads(p.read_text())["payload"] for p in pend),
                      key=lambda p: p["first_missed_fire"])
    assert [(p["first_missed_fire"], p["last_missed_fire"], p["missed_fires"])
            for p in payloads] == [
        ("2026-09-15T07:01:00Z", "2026-09-15T07:14:00Z", 14),
        ("2026-09-15T07:15:00Z", "2026-09-15T07:44:00Z", 30),
        ("2026-09-15T07:45:00Z", "2026-09-15T08:14:00Z", 30)]


def test_wake_observe_delivered_fire_not_retroactively_missed_by_next_manual_tick(tmp_path):
    """AC (a): a fire window that occurs ON TIME (proven by --delivered) must
    never be retroactively reclassified as 'missed' by a later observation
    tick, driven across the exact multi-tick timeline shape of the real
    2026-09-15 reproduction (channel armed on '12,57 * * * *', checked at
    the :57 and :12 boundaries) -- the difference from the buggy report
    being that here the :57 fire is actually PROVEN delivered, the doctrine-
    correct way to certify a scheduled arrival.

    HONEST SCOPE (QA finding F3, 2026-09-15): the '12,57' half below passes
    unchanged against every version of the watermark branch, because with
    gaps >= slack the delivered fire is the ONLY fire in its batch -- it is
    characterization, not regression. The sub-slack half added afterwards IS
    a regression test, and it pins the OTHER side of the branch: unlike the
    manual path, the delivered path must NOT park at the first unjudged fire.
    A delivery is scored against fires[-1], so parking below it re-presents
    an already-honoured fire for judgment on the next tick and counts a
    PROVEN on_time fire as missed. Measured against a variant that parks on
    both paths: this timeline returns expected_next_fire 03:57 instead of
    04:12 and then verdict 'missed' / needs_rearm True at 04:12:03."""
    root = ledger(tmp_path)
    assert wake_arm(root, cron="12,57 * * * *",
                    now="2026-09-15T03:54:11Z").returncode == 0
    token = armed_token(root)

    delivered = ok(root, "wake-observe", "--delivered", "--channel-id", "hb-1",
                   "--arming-token", token, now="2026-09-15T03:57:05Z")
    assert delivered["verdict"] == "on_time"
    assert delivered["needs_rearm"] is False
    assert delivered["expected_next_fire"] == "2026-09-15T04:12:00Z"

    # next boundary: a plain manual check of the NEW window must find it
    # pending -- the fire that was actually delivered must never resurface
    # as missed.
    later = ok(root, "wake-observe", now="2026-09-15T04:12:03Z")
    assert later["verdict"] == "pending"
    assert later["missed_fires"] == 0
    assert later["needs_rearm"] is False

    # SUB-SLACK CRON: the discriminating half. A 1-minute cron against the
    # 15-minute slack puts 16 fires in grace at once, so the delivered branch
    # really does have a fires[len(missed_fires):-1] remainder to decide about.
    sub = ledger(tmp_path / "sub-slack")
    assert wake_arm(sub, cron="* * * * *", tz="UTC",
                    now="2026-09-15T07:00:00Z").returncode == 0
    sub_token = armed_token(sub)

    # 07:30 delivers. 07:01..07:14 are past their own deadline and are missed
    # even though an arrival landed (a late arrival must never EXONERATE the
    # fire it failed to honour). The watermark advances past the WHOLE batch
    # to 07:31: parking at 07:15 instead would drag the just-proven 07:30
    # fire back into the next tick's window.
    proven = ok(sub, "wake-observe", "--delivered", "--channel-id", "hb-1",
                "--arming-token", sub_token, now="2026-09-15T07:30:00Z")
    assert proven["verdict"] == "on_time"
    assert proven["missed_fires"] == 14
    assert proven["expected_next_fire"] == "2026-09-15T07:31:00Z"

    # the next manual tick judges only 07:31..07:34; the proven 07:30 fire is
    # strictly outside every missed window and is never re-counted.
    after = ok(sub, "wake-observe", now="2026-09-15T07:50:00Z")
    assert after["verdict"] == "missed"
    assert after["missed_fires"] == 4
    assert after["expected_next_fire"] == "2026-09-15T07:35:00Z"
    windows = [json.loads(p.read_text())["payload"]
               for p in (sub / "inbox" / "pending").glob("wake-missed-*.json")]
    assert all(w["last_missed_fire"] < "2026-09-15T07:30:00Z"
               or w["first_missed_fire"] > "2026-09-15T07:30:00Z"
               for w in windows), windows


def test_wake_arming_survives_multiple_observation_ticks_without_a_miss(tmp_path):
    """AC (b): arming persistence across observation ticks. The 'arming only
    survives one observation' symptom reported alongside the reclassification
    bug is NOT a distinct defect and NOT a general one-observation-only
    design limit -- it was simply that the second observation in that
    specific reproduction happened to coincide with a genuine, correctly
    timed miss. needs_rearm only ever latches true from an ACTUAL missed (or
    late) fire (docstring at cmd_wake_observe: 'Latched: an arrival proves
    the channel is alive now but does not retire an earlier loss, so only a
    successful wake-arm clears this'); it is never set merely by the passage
    of ticks. A single arming demonstrably survives an arbitrary number of
    observation ticks -- delivered or pre-fire pending checks alike -- for as
    long as every fire is confirmed before its own grace elapses.

    CLASSIFICATION (QA finding F3, 2026-09-15, re-measured): F3 is right that
    this does NOT discriminate the manual-path watermark defect -- every fire
    here is confirmed inside its own grace, so no tick ever reaches the
    still-open-fire parking rule and the test passes unchanged against both
    the pre-fix and the park-at-fires[-1] engines. It is deliberately NOT
    strengthened toward that defect: a timeline containing a miss would stop
    testing 'a single arming survives with no miss'.

    But it is not inert either. Re-measured against a third engine variant --
    one that parks the DELIVERED path at the first unjudged fire too -- tick 4
    fails with needs_rearm True, because parking below a proven fire drags it
    back into the next tick's window and counts it missed. So this test is a
    live regression test for the delivered-path boundary (an arming must
    survive ticks precisely BECAUSE proven fires are never re-judged); it is
    characterization only with respect to the manual path. The manual path is
    pinned by test_wake_observe_parks_at_first_unjudged_fire_not_the_newest."""
    root = ledger(tmp_path)
    assert wake_arm(root, cron="12,57 * * * *",
                    now="2026-09-15T03:54:11Z").returncode == 0
    token = armed_token(root)

    # tick 1: pending check before the first fire is even due
    t1 = ok(root, "wake-observe", now="2026-09-15T03:55:00Z")
    assert t1["verdict"] == "pending" and t1["needs_rearm"] is False

    # tick 2: first fire delivered on time
    t2 = ok(root, "wake-observe", "--delivered", "--channel-id", "hb-1",
           "--arming-token", token, now="2026-09-15T03:57:02Z")
    assert t2["verdict"] == "on_time" and t2["needs_rearm"] is False

    # tick 3: pending check between fires
    t3 = ok(root, "wake-observe", now="2026-09-15T04:05:00Z")
    assert t3["verdict"] == "pending" and t3["needs_rearm"] is False

    # tick 4: second fire also delivered on time -- SAME arming_token, no
    # re-arm was ever needed
    t4 = ok(root, "wake-observe", "--delivered", "--channel-id", "hb-1",
           "--arming-token", token, now="2026-09-15T04:12:04Z")
    assert t4["verdict"] == "on_time" and t4["needs_rearm"] is False
    assert wake_record(root)["arming_token"] == token


def test_wake_observe_on_time_delivery_advances_without_missed_event(tmp_path):
    root = ledger(tmp_path)
    assert wake_arm(root, cron="*/45 * * * *", now="2026-08-28T12:50:00Z").returncode == 0
    out = ok(root, *delivered_claim(root),
             now="2026-08-28T13:05:00Z")
    assert out["verdict"] == "on_time"
    assert out["missed_fires"] == 0
    assert out["needs_rearm"] is False
    assert out["expected_next_fire"] == "2026-08-28T13:45:00Z"
    assert list((root / "inbox" / "pending").glob("wake-missed-*.json")) == []
    assert "wake_channel_missed" not in (root / "journal.ndjson").read_text()


def test_wake_observe_mismatched_channel_id_refused(tmp_path):
    root = ledger(tmp_path)
    assert wake_arm(root).returncode == 0
    r = run(root, "wake-observe", "--delivered", "--channel-id", "hb-OTHER",
            now="2026-08-28T12:20:00Z")
    assert r.returncode == 2 and "does not match" in r.stderr


def test_wake_observe_fixed_local_time_drifts_with_offset_change(tmp_path):
    root = ledger(tmp_path)
    # noon America/New_York daily, spanning the 2026-03-08 US spring-forward
    # transition: EST noon = 17:00Z, EDT noon = 16:00Z. This covers OFFSET
    # DRIFT only -- the gap and fold boundaries themselves are covered by the
    # four cron_next_fire tests below (this test was previously named
    # "..._across_dst_..." while exercising neither boundary).
    assert wake_arm(root, cron="0 12 * * *", tz="America/New_York",
                    now="2026-03-07T16:00:00Z").returncode == 0
    rec = json.loads((root / "wake.json").read_text())
    assert rec["expected_next_fire"] == "2026-03-07T17:00:00Z"
    out = ok(root, *delivered_claim(root),
             now="2026-03-07T17:00:30Z")
    assert out["verdict"] == "on_time"
    assert out["expected_next_fire"] == "2026-03-08T16:00:00Z"  # aware-UTC across DST


# US fall back 2026-11-01: 02:00 EDT -> 01:00 EST at 06:00Z, so 05:59Z is
# 01:59 EDT (fold=0), 06:00Z-06:59Z repeat 01:00-01:59 as EST (fold=1), and
# 07:00Z is 02:00 EST. US spring forward 2026-03-08: 02:00 EST -> 03:00 EDT at
# 07:00Z, so local 02:00-02:59 does not exist that day.
NY = "America/New_York"


def armed_next_fire(root, *, tz=NY, **kw):
    """wake-arm computes cron_next_fire(now) -- the engine probe used below."""
    assert wake_arm(root, tz=tz, **kw).returncode == 0
    return json.loads((root / "wake.json").read_text())["expected_next_fire"]


def test_cron_next_fire_fall_back_fold_never_returns_earlier_than_after(tmp_path):
    # Local-clock `+ timedelta` resets PEP 495 fold and walked BACKWARDS here,
    # returning 05:31Z for after=06:30Z -- a 59-minute reversal that breaks the
    # "strictly after" contract and re-walks the repeated hour.
    assert armed_next_fire(ledger(tmp_path), cron="* * * * *",
                           now="2026-11-01T06:30:00Z") == "2026-11-01T06:31:00Z"


def test_cron_next_fire_fall_back_repeated_hour_counted_for_wildcard_hour_field(tmp_path):
    # The old engine jumped 05:59Z -> 07:00Z, losing all 60 fires of the
    # repeated hour: wake-observe then UNDERCOUNTED misses across it, letting a
    # dead channel read healthier than it is. Every real instant of the
    # repeated hour is a fire the deployed scheduler delivers.
    assert armed_next_fire(ledger(tmp_path), cron="* * * * *",
                           now="2026-11-01T05:59:00Z") == "2026-11-01T06:00:00Z"


def test_cron_all_hour_spellings_fire_both_fall_back_occurrences(tmp_path):
    # Every hour spelling, wildcard or restricted, now counts BOTH occurrences
    # of a repeated wall time, because the deployed scheduler has no fold
    # handling and delivers both. The engine no longer classifies hour fields.
    m = load_engine()
    for hour_field in ["*", "*/1", "0-23", ",".join(str(h) for h in range(24))]:
        assert m.parse_cron(f"* {hour_field} * * *")["hours"] == set(range(24))
    # 05:30Z is 01:30 EDT (fold=0) and 06:30Z is 01:30 EST (fold=1): two real
    # instants of one repeated wall time. Every spelling that allows hour 1
    # must produce the second one.
    for index, hour_field in enumerate(["*", "1", "0-23", "0,1,2,3"]):
        assert armed_next_fire(
            ledger(tmp_path / f"spelling-{index}"), cron=f"30 {hour_field} * * *",
            now="2026-11-01T05:30:00Z") == "2026-11-01T06:30:00Z", hour_field


def test_cron_next_fire_restricted_dom_and_dow_are_conjunctive(tmp_path):
    # The deployed scheduler ANDs all five field predicates with no day-field
    # special case, so two restricted day fields INTERSECT. This one
    # expression also positively exercises step, range, and comma-list forms.
    m = load_engine()
    spec = m.parse_cron("*/15 8-9 13,27 9-10 1,3,5")
    assert spec["minutes"] == {0, 15, 30, 45}
    assert spec["hours"] == {8, 9}
    assert spec["dom"] == (True, {13, 27})
    assert spec["months"] == {9, 10}
    assert spec["dow"] == (True, {1, 3, 5})

    cron = "*/15 8-9 13,27 9-10 0"
    cases = [
        # 2026-09-13 is Sunday and the 13th: BOTH restricted day fields match,
        # so the day fires; the next minute in the step set is 08:15.
        ("both-match", "2026-09-13T08:13:00Z", "2026-09-13T08:15:00Z"),
        # 2026-09-14 is Monday: neither the 14th nor DOW 1 is allowed. Under
        # the old UNION rule 2026-09-27 was reachable from either field alone;
        # under the deployed AND it is reachable only because Sunday the 27th
        # satisfies both. 2026-10-13 and 2026-10-27 are Tuesdays and are now
        # correctly NOT produced.
        ("intersection-only", "2026-09-14T08:13:00Z", "2026-09-27T08:00:00Z"),
    ]
    for label, after, expected in cases:
        assert armed_next_fire(
            ledger(tmp_path / label), cron=cron, tz="UTC", now=after
        ) == expected, label


def test_cron_next_fire_counts_fold_for_every_hour_form(tmp_path):
    # Direct engine probe at the exact New York fall-back boundary: all three
    # forms allow every hour, so their next real minute after 01:59 EDT is the
    # repeated 01:00 EST at 06:00Z, not 02:00 EST at 07:00Z.
    all_hour_forms = ["*/1", "0-23", ",".join(str(hour) for hour in range(24))]
    for index, hour_field in enumerate(all_hour_forms):
        assert armed_next_fire(
            ledger(tmp_path / f"direct-form-{index}"),
            cron=f"* {hour_field} * * *",
            now="2026-11-01T05:59:00Z",
        ) == "2026-11-01T06:00:00Z", hour_field


def test_wake_observe_counts_fall_back_for_every_hour_form(tmp_path):
    # Skipping the fold=1 repeated hour reconciled only 16 misses instead of
    # 76 -- a fail-open liveness result. The deployed scheduler delivers all
    # 60 repeated-hour instants, so all 60 count as missed when nothing
    # arrives.
    all_hour_forms = ["*/1", "0-23", ",".join(str(hour) for hour in range(24))]
    for index, hour_field in enumerate(all_hour_forms):
        root = ledger(tmp_path / f"form-{index}")
        cron = f"* {hour_field} * * *"
        assert armed_next_fire(root, cron=cron,
                               now="2026-11-01T05:58:00Z") == "2026-11-01T05:59:00Z"
        out = ok(root, "wake-observe", now="2026-11-01T07:30:00Z")
        # Missed fires are 05:59Z..07:14Z inclusive. The 60 fold=1 instants
        # from 06:00Z..06:59Z are real interval fires and must all be counted.
        assert out["verdict"] == "missed", hour_field
        assert out["missed_fires"] == 76, hour_field
        # 16 fires (07:15Z..07:30Z) are elapsed but still inside their own
        # 15-minute grace. The watermark parks at the FIRST of them, 07:15Z --
        # not at the newest (07:30Z), which would drop 07:15..07:29 from every
        # future window, and not past the batch at 07:31Z, which would drop
        # all 16. Undercounting is the fail-open this test exists to catch.
        assert out["expected_next_fire"] == "2026-11-01T07:15:00Z", hour_field


def test_cron_next_fire_fixed_time_job_fires_twice_across_fall_back(tmp_path):
    root = ledger(tmp_path)
    # A restricted hour field fires at BOTH real instants of the repeated wall
    # time -- 01:30 EDT at 05:30Z and 01:30 EST at 06:30Z -- because the
    # deployed scheduler matches every whole-minute candidate it projects and
    # has no fold handling. Suppressing the second one made the ledger expect
    # one fewer fire per fall-back than the channel actually delivers.
    assert armed_next_fire(root, cron="30 1 * * *",
                           now="2026-11-01T04:00:00Z") == "2026-11-01T05:30:00Z"
    assert armed_next_fire(root, cron="30 1 * * *",
                           now="2026-11-01T05:30:00Z") == "2026-11-01T06:30:00Z"


def test_cron_next_fire_spring_forward_gap_time_never_fires(tmp_path):
    # 02:30 does not exist on 2026-03-08; the occurrence resumes the next day.
    assert armed_next_fire(ledger(tmp_path), cron="30 2 * * *",
                           now="2026-03-08T05:00:00Z") == "2026-03-09T06:30:00Z"


def test_cron_next_fire_finds_ordinary_leap_day_within_vendor_budget(tmp_path):
    # A leap day reachable inside the deployed scheduler's own candidate budget
    # resolves. Re-verified against the deployed scheduler, which returns
    # exactly this instant for this cadence and start.
    assert armed_next_fire(ledger(tmp_path), cron="0 0 29 2 *", tz="UTC",
                           now="2027-03-05T00:00:00Z",
                           verify_window_days=365) == "2028-02-29T00:00:00Z"


def test_cron_next_fire_nonleap_century_gap_exceeds_vendor_budget_refused(tmp_path):
    # 2100 is divisible by 100 but not 400, so the next leap day after 2096 is
    # 2104 -- an eight-year gap far outside the deployed budget. The deployed
    # scheduler throws for exactly this cadence and start, so the ledger must
    # refuse rather than watch a channel that can never be delivered.
    root = ledger(tmp_path)
    r = wake_arm(root, cron="0 0 29 2 *", tz="UTC", now="2096-03-01T00:00:00Z")
    assert r.returncode == 2, r.stdout
    assert "no cron occurrence within the deployed scheduler" in r.stderr
    assert not (root / "wake.json").exists()


def test_cron_next_fire_sparse_valid_fields_keep_exact_local_instant(tmp_path):
    # Exercise a genuinely sparse fixed minute/hour/month/day cadence in a
    # non-integral-offset zone, not merely a midnight-UTC leap-day special
    # case. 04:07 in Kolkata is 22:37Z on the preceding UTC date. The START
    # instant moved from 2096 into the deployed scheduler's candidate budget
    # (the 2096 -> 2104 gap is refused by the vendor itself); the asserted
    # local instant is unchanged and was re-verified against the vendor.
    assert armed_next_fire(ledger(tmp_path), cron="7 4 29 2 *", tz="Asia/Kolkata",
                           now="2027-03-05T00:00:00Z",
                           verify_window_days=365) == "2028-02-28T22:37:00Z"


def test_cron_next_fire_impossible_schedule_refused_within_vendor_budget(tmp_path):
    root = ledger(tmp_path)
    # February 31 can never match. Run the full bounded search in a subprocess
    # with a timeout: it must terminate and refuse, never hang or fabricate an
    # occurrence merely because the budget was exhausted. The refusal now
    # states the DEPLOYED meaning of exhaustion -- no occurrence inside the
    # window the scheduler itself searches -- rather than a global impossibility
    # claim the ledger is not entitled to make.
    proc = subprocess.run(
        [sys.executable, str(LEDGER), "--root", str(root), "--now",
         "2026-03-01T00:00:00Z", "wake-arm", "--channel-kind",
         "paseo_heartbeat", "--channel-id", "impossible", "--cron",
         "0 0 31 2 *", "--timezone", "UTC", "--role", "tick"],
        capture_output=True, text=True, cwd=REPO, timeout=60)
    assert proc.returncode == 2
    assert "527040-candidate window" in proc.stderr
    assert "the deployed scheduler would never fire this cadence" in proc.stderr
    assert not (root / "wake.json").exists()


def test_cron_next_fire_sub_hour_offset_shift_loses_no_fire(tmp_path):
    # Regression: the hour-boundary coarse skip is equivalent to UTC-minute
    # arithmetic ONLY while the offset is constant. Pacific/Chatham steps
    # +12:45 -> +13:45 on 2026-09-27 (local 02:45 jumps to 03:45), and an
    # unguarded skip jumped 13:30Z straight to 14:15Z, stepping over the 14:00Z
    # match of `45 3 * * *` -- a silently LOST fire, i.e. fail-open again.
    assert armed_next_fire(ledger(tmp_path), tz="Pacific/Chatham", cron="45 3 * * *",
                           now="2026-09-26T13:29:00Z") == "2026-09-26T14:00:00Z"


def test_wake_observe_counts_chatham_spring_forward_fire_as_missed(tmp_path):
    root = ledger(tmp_path)
    # This reaches the actual Pacific/Chatham transition: 14:00Z projects to
    # 03:45 after the +12:45 -> +13:45 jump. The unsafe coarse skip armed the
    # next DAY's 03:45 instead, so observe reported pending/zero and a dead
    # channel read healthy. Assert the reconciliation outcome, not just the
    # cron helper's answer, because undercounting misses is the protected
    # wake-channel invariant.
    assert wake_arm(root, cron="45 3 * * *", tz="Pacific/Chatham",
                    now="2026-09-26T13:29:00Z").returncode == 0
    assert json.loads((root / "wake.json").read_text())["expected_next_fire"] == (
        "2026-09-26T14:00:00Z")
    out = ok(root, "wake-observe", now="2026-09-26T14:16:00Z")
    assert out["verdict"] == "missed"
    assert out["missed_fires"] == 1
    assert out["needs_rearm"] is True
    assert out["expected_next_fire"] == "2026-09-27T14:00:00Z"
    event = json.loads(next((root / "inbox" / "pending").glob(
        "wake-missed-*.json")).read_text())
    assert event["payload"]["first_missed_fire"] == "2026-09-26T14:00:00Z"
    assert event["payload"]["last_missed_fire"] == "2026-09-26T14:00:00Z"


def load_engine():
    """Import the ledger's pure cron helpers in-process. Only pure functions
    are exercised here -- no ledger root is touched, so the temp-root rule of
    this facade still holds."""
    spec = importlib.util.spec_from_file_location("paseo_ledger_engine", LEDGER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# zones chosen for offset pathology, each with its OWN transition dates:
# sub-hour offsets (Chatham +12:45/+13:45, St_Johns -03:30/-02:30, Kathmandu
# +05:45, Kolkata +05:30), a 30-minute DST step (Lord Howe), a 2-hour step
# (Troll), plus ordinary and fixed-offset controls.
DIFFERENTIAL_ZONES = {
    "America/New_York": ["2026-03-07", "2026-10-31"],
    "America/St_Johns": ["2026-03-07", "2026-10-31"],
    "Australia/Lord_Howe": ["2026-04-04", "2026-10-03"],
    "Pacific/Chatham": ["2026-04-04", "2026-09-26"],
    "Antarctica/Troll": ["2026-03-28", "2026-10-24"],
    "Asia/Kathmandu": ["2026-03-07"],
    "Asia/Kolkata": ["2026-03-07"],
    "UTC": ["2026-03-07"],
}
DIFFERENTIAL_CRONS = ["* * * * *", "*/15 * * * *", "0 * * * *", "30 2 * * *",
                      "45 3 * * *", "0,30 1-4 * * *", "15 2-3 * * 0",
                      "0 12 * * *", "*/45 * * * *", "45 13 * * 1-5"]


def test_cron_next_fire_differential_vs_naive_scan_across_dst_zones_vendor_predicate():
    """Brute-force differential over both DST boundaries of eight zones.

    This is NOT a tautology: both sides evaluate the SAME field predicate, but
    the engine TRAVERSES with an hour-boundary coarse skip while the reference
    walks every single UTC minute. Any divergence therefore proves the skip
    jumped over a matching minute -- the exact defect class that produced both
    the original fall-back bug and the Chatham sub-hour-offset bug. It also
    asserts strict monotonicity, the contract the fold-reset violated.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    m = load_engine()

    def utc(day):
        return datetime.fromisoformat(day + "T00:00:00+00:00")

    def field_match(spec, cand, tz):
        # The reference predicate is now exactly the deployed scheduler's:
        # five field tests over the projected local fields, and NOTHING else.
        # It previously carried a fold suppression of its own, which made the
        # reference agree with a defect instead of judging it.
        local = cand.astimezone(tz)
        return (local.month in spec["months"] and m.cron_day_matches(spec, local)
                and local.hour in spec["hours"] and local.minute in spec["minutes"])

    divergences, checked = [], 0
    for zone, days in DIFFERENTIAL_ZONES.items():
        tz = ZoneInfo(zone)
        for day in days:
            start, end = utc(day), utc(day) + timedelta(days=3)
            for cron in DIFFERENTIAL_CRONS:
                spec = m.parse_cron(cron)
                reference, cand = [], start + timedelta(minutes=1)
                while cand <= end:  # every minute, no skipping
                    if field_match(spec, cand, tz):
                        reference.append(cand)
                    cand += timedelta(minutes=1)
                engine, cur = [], start
                while True:
                    cur = m.cron_next_fire(spec, cur, zone)
                    if cur > end:
                        break
                    assert cur > (engine[-1] if engine else start), (
                        f"non-monotonic {zone} {cron!r}: {cur}")
                    engine.append(cur)
                checked += len(reference)
                if engine != reference:
                    divergences.append(
                        f"{zone} {cron!r}: engine={len(engine)} naive={len(reference)}")
    assert checked > 50000, f"differential too small to be evidence: {checked}"
    assert not divergences, "coarse skip lost fires: " + "; ".join(divergences)


def test_wake_observe_expected_fire_inside_repeated_hour_terminates(tmp_path):
    root = ledger(tmp_path)
    # wake-observe walks `while fire <= now: fire = cron_next_fire(...)`. With a
    # persisted expected_next_fire inside the repeated hour the old backward-
    # walking engine never advanced past it -- this call HUNG rather than
    # merely miscounting, so it runs under an explicit timeout.
    assert armed_next_fire(root, cron="* * * * *",
                           now="2026-11-01T05:58:00Z") == "2026-11-01T05:59:00Z"
    proc = subprocess.run(
        [sys.executable, str(LEDGER), "--root", str(root), "--now",
         "2026-11-01T07:30:00Z", "wake-observe"],
        capture_output=True, text=True, cwd=REPO, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    # fires 05:59Z..07:30Z inclusive = 92; missed are those whose +15min slack
    # deadline has passed, i.e. fires before 07:15Z = 05:59Z..07:14Z = 76.
    # The 60 repeated-hour fires are INSIDE that count, not skipped.
    assert out["verdict"] == "missed"
    assert out["missed_fires"] == 76
    # the remaining 16 (07:15Z..07:30Z) are elapsed but still in grace, so the
    # watermark parks at the FIRST unjudged fire, 07:15Z -- not at the newest
    # (07:30Z) and not past the batch (07:31Z).
    assert out["expected_next_fire"] == "2026-11-01T07:15:00Z"


def test_wake_observe_delivered_requires_channel_id(tmp_path):
    root = ledger(tmp_path)
    assert wake_arm(root).returncode == 0
    # arrival is proved by the channel id the wake prompt carries; an unnamed
    # delivery claim would validate whichever channel happens to be armed
    r = run(root, "wake-observe", "--delivered", now="2026-08-28T12:20:00Z")
    assert r.returncode == 2 and "--delivered requires --channel-id" in r.stderr
    assert ok(root, *delivered_claim(root),
              now="2026-08-28T12:20:00Z")["verdict"] == "on_time"


def test_wake_arm_refuses_any_finite_maxruns_for_tick(tmp_path):
    root = ledger(tmp_path)
    for cap in (1, 2, 10):  # ANY cap leaves a last fire after which loss is permanent
        r = wake_arm(root, max_runs=cap)
        assert r.returncode == 2 and "forbidden" in r.stderr, cap
    assert not (root / "wake.json").exists()
    assert wake_arm(root, role="test", max_runs=2).returncode == 0  # tests may cap


def test_wake_arm_help_says_every_finite_tick_maxruns_is_refused(tmp_path):
    r = run(tmp_path, "wake-arm", "--help", now=None)
    assert r.returncode == 0, r.stderr
    assert "any finite value is refused for role=tick" in " ".join(r.stdout.split())


def test_wake_needs_rearm_latches_until_rearm(tmp_path):
    root = ledger(tmp_path)
    assert wake_arm(root, cron="*/45 * * * *", now="2026-08-28T12:50:00Z").returncode == 0
    assert json.loads((root / "wake.json").read_text())["needs_rearm"] is False
    assert ok(root, "wake-observe", now="2026-08-28T15:10:00Z")["needs_rearm"] is True
    # persisted, so a crash before the external re-arm cannot read fresh
    assert json.loads((root / "wake.json").read_text())["needs_rearm"] is True
    assert ok(root, "wake-status", now="2026-08-28T15:10:00Z")["needs_rearm"] is True
    # an arrival proves the channel is alive NOW but does not retire the loss
    assert ok(root, *delivered_claim(root),
              now="2026-08-28T15:46:00Z")["needs_rearm"] is True
    # only a successful re-arm clears it
    assert wake_arm(root, cron="*/45 * * * *", now="2026-08-28T15:50:00Z").returncode == 0
    assert json.loads((root / "wake.json").read_text())["needs_rearm"] is False


def test_wake_missed_event_id_is_crash_stable_across_retry(tmp_path):
    root = ledger(tmp_path)
    assert wake_arm(root, cron="*/45 * * * *", now="2026-08-28T12:50:00Z").returncode == 0
    saved = (root / "wake.json").read_text()
    first = ok(root, "wake-observe", now="2026-08-28T15:10:00Z")["inbox_event_id"]
    # simulate a crash AFTER the inbox append but BEFORE the wake.json advance
    (root / "wake.json").write_text(saved)
    # retry at a later wall time, still inside the same reconciled interval
    # (15:00's deadline 15:15 has not passed, so the same fires reconcile)
    second = ok(root, "wake-observe", now="2026-08-28T15:12:00Z")["inbox_event_id"]
    assert second == first, "id must derive from interval identity, not wall time"
    assert len(list((root / "inbox" / "pending").glob("wake-missed-*.json"))) == 1


# ---------------- arming identity: delivery proof binds to the ARMING,
# ---------------- not to the channel alone (task 20260904-181435-b) ----------

def last_wake_observe(root):
    entries = [json.loads(line) for line
               in (root / "journal.ndjson").read_text().strip().splitlines()]
    return [e for e in entries if e.get("op") == "wake-observe"][-1]


def strip_arming_identity(root):
    """A record armed before this change carries NO arming identity key at
    all -- not an empty one. Fixture construction, like strip_wake_knobs."""
    record = wake_record(root)
    record.pop("arming_token", None)
    put_wake_record(root, record)


def test_wake_arming_identity_minted(tmp_path):
    root = ledger(tmp_path)
    tokens = []
    # two armings on the SAME channel id and two at the SAME --now instant:
    # the pair that rules out armed_at, which is caller-supplied under --now
    for kwargs in ({"now": "2026-08-28T12:00:00Z"},
                   {"now": "2026-08-28T12:00:00Z"},
                   {"now": "2026-08-28T12:30:00Z"},
                   {"channel_id": "hb-2", "now": "2026-08-28T12:30:00Z"}):
        proc = wake_arm(root, cron="0 * * * *", **kwargs)
        assert proc.returncode == 0
        reported = json.loads(proc.stdout)["arming_token"]
        # reported for the wake prompt AND persisted under the bound key
        assert reported == wake_record(root)["arming_token"]
        tokens.append(reported)
    assert all(tokens), tokens
    assert len(set(tokens)) == len(tokens), tokens


def test_wake_delivery_claim_requires_arming_identity(tmp_path):
    root = ledger(tmp_path)
    assert wake_arm(root, cron="0 * * * *", now="2026-08-28T12:00:00Z").returncode == 0
    before = (root / "wake.json").read_bytes()
    unnamed = run(root, "wake-observe", "--delivered", "--channel-id", "hb-1",
                  now="2026-08-28T13:05:00Z")
    assert unnamed.returncode != 0
    assert (root / "wake.json").read_bytes() == before   # refusal mutates nothing
    # the pre-existing channel guard still fires FIRST: a foreign channel is
    # refused for the channel, never reaching the arming comparison
    foreign = run(root, "wake-observe", "--delivered", "--channel-id", "hb-OTHER",
                  now="2026-08-28T13:05:00Z")
    assert foreign.returncode == 2 and "does not match" in foreign.stderr
    assert (root / "wake.json").read_bytes() == before
    named = ok(root, *delivered_claim(root), now="2026-08-28T13:05:00Z")
    assert named["verdict"] == "on_time"


def test_wake_nonmatching_arming_grants_no_liveness(tmp_path):
    root = ledger(tmp_path)
    assert wake_arm(root, cron="0 * * * *", now="2026-08-28T12:00:00Z").returncode == 0
    token_a = armed_token(root)
    missed = ok(root, "wake-observe", now="2026-08-28T16:00:00Z")
    assert missed["verdict"] == "missed" and missed["missed_fires"] == 3
    assert missed["needs_rearm"] is True
    assert wake_arm(root, cron="0 * * * *", now="2026-08-28T16:05:00Z").returncode == 0
    token_b = armed_token(root)
    assert token_a != token_b
    # ONE state restored into TWO roots: two independently-built ledgers could
    # never compare equal, because every arming mints a different token
    stale_root, control_root = tmp_path / "stale", tmp_path / "control"
    shutil.copytree(root, stale_root)
    shutil.copytree(root, control_root)
    instant = "2026-08-28T17:20:00Z"
    out = ok(stale_root, "wake-observe", "--delivered", "--channel-id", "hb-1",
             "--arming-token", token_a, now=instant)
    control = ok(control_root, "wake-observe", now=instant)
    assert out["verdict"] == "superseded_arming"          # DIAGNOSIS channel
    assert last_wake_observe(stale_root)["verdict"] == "superseded_arming"
    assert control["verdict"] == "missed"
    stale_rec, control_rec = wake_record(stale_root), wake_record(control_root)
    # every key the non-delivery control carries, with an equal value; an
    # additional diagnostic persisted on the refusal path stays permitted
    for key, value in control_rec.items():
        assert stale_rec[key] == value, key
    assert stale_rec["last_verdict"] == "missed"          # PERSISTED channel
    entry = last_wake_observe(stale_root)
    assert entry["claimed_arming_token"] == token_a
    assert entry["armed_arming_token"] == token_b
    # no number of stale arrivals ever launders the health state
    for hour in ("18", "19", "20"):
        again = ok(stale_root, "wake-observe", "--delivered", "--channel-id",
                   "hb-1", "--arming-token", token_a,
                   now=f"2026-08-28T{hour}:20:00Z")
        assert again["verdict"] == "superseded_arming"
        assert again["needs_rearm"] is True
    laundered = wake_record(stale_root)
    assert laundered["missed_total"] >= stale_rec["missed_total"] >= 1
    assert laundered["needs_rearm"] is True
    assert laundered["last_verdict"] != "on_time"
    # POSITIVE CONTROL: the CURRENT arming can still certify on this ledger
    before_fire = laundered["expected_next_fire"]
    good = ok(stale_root, *delivered_claim(stale_root), now="2026-08-28T21:05:00Z")
    assert good["verdict"] == "on_time"
    assert last_wake_observe(stale_root)["verdict"] == "on_time"
    certified = wake_record(stale_root)
    assert certified["last_verdict"] == "on_time"
    assert certified["expected_next_fire"] != before_fire


def test_wake_legacy_record_no_liveness(tmp_path):
    root = ledger(tmp_path)
    assert wake_arm(root, cron="0 * * * *", now="2026-08-28T12:00:00Z").returncode == 0
    strip_arming_identity(root)
    # absence must TERMINATE the predicate, never compare equal to absence
    unnamed = ok(root, "wake-observe", "--delivered", "--channel-id", "hb-1",
                 now="2026-08-28T13:05:00Z")
    assert unnamed["verdict"] == "unversioned_arming"
    assert last_wake_observe(root)["verdict"] == "unversioned_arming"
    assert wake_record(root)["last_verdict"] == "pending"
    # a claim that DOES name a token grants no liveness against it either
    named = ok(root, "wake-observe", "--delivered", "--channel-id", "hb-1",
               "--arming-token", "a-claim-from-nowhere", now="2026-08-28T13:06:00Z")
    assert named["verdict"] == "unversioned_arming"
    assert last_wake_observe(root)["verdict"] == "unversioned_arming"
    assert wake_record(root)["last_verdict"] == "pending"
    # POSITIVE CONTROL: a re-arm migrates the record and restores liveness
    proc = wake_arm(root, cron="0 * * * *", now="2026-08-28T13:10:00Z")
    assert proc.returncode == 0
    minted = json.loads(proc.stdout)["arming_token"]
    before_fire = wake_record(root)["expected_next_fire"]
    good = ok(root, "wake-observe", "--delivered", "--channel-id", "hb-1",
              "--arming-token", minted, now="2026-08-28T14:05:00Z")
    assert good["verdict"] == "on_time"
    assert last_wake_observe(root)["verdict"] == "on_time"
    migrated = wake_record(root)
    assert migrated["last_verdict"] == "on_time"
    assert migrated["expected_next_fire"] != before_fire


def test_wake_fresh_replacement_not_certified(tmp_path):
    root = ledger(tmp_path)
    assert wake_arm(root, cron="0 * * * *", now="2026-08-28T12:00:00Z").returncode == 0
    token_a = armed_token(root)
    # re-arm with NO intervening missed observation: the replacement is still
    # inside its first cadence, so plain non-delivery returns pending
    assert wake_arm(root, cron="0 * * * *", now="2026-08-28T12:30:00Z").returncode == 0
    assert token_a != armed_token(root)
    stale_root = tmp_path / "stale"
    control_root = tmp_path / "control"
    certified_root = tmp_path / "certified"
    for clone in (stale_root, control_root, certified_root):
        shutil.copytree(root, clone)
    instant = "2026-08-28T13:05:00Z"
    out = ok(stale_root, "wake-observe", "--delivered", "--channel-id", "hb-1",
             "--arming-token", token_a, now=instant)
    control = ok(control_root, "wake-observe", now=instant)
    assert out["verdict"] == "superseded_arming"          # DIAGNOSIS channel
    assert last_wake_observe(stale_root)["verdict"] == "superseded_arming"
    assert control["verdict"] == "pending"
    stale_rec, control_rec = wake_record(stale_root), wake_record(control_root)
    for key, value in control_rec.items():
        assert stale_rec[key] == value, key
    assert stale_rec["last_verdict"] == "pending"         # never on_time
    # POSITIVE CONTROL from the SAME snapshot at the SAME instant, with
    # nothing latched that could mask the outcome
    good = ok(certified_root, *delivered_claim(certified_root), now=instant)
    assert good["verdict"] == "on_time"
    assert last_wake_observe(certified_root)["verdict"] == "on_time"
    certified_rec = wake_record(certified_root)
    assert certified_rec["last_verdict"] == "on_time"
    assert certified_rec["expected_next_fire"] != control_rec["expected_next_fire"]


def test_wake_liveness_still_granted_after_rearm(tmp_path):
    root = ledger(tmp_path)
    assert wake_arm(root, cron="0 * * * *", now="2026-08-28T12:00:00Z").returncode == 0
    assert wake_arm(root, cron="0 * * * *", now="2026-08-28T12:30:00Z").returncode == 0
    before_fire = wake_record(root)["expected_next_fire"]
    out = ok(root, *delivered_claim(root), now="2026-08-28T13:05:00Z")
    # the VERDICT VALUE on all three channels -- an advanced watermark alone
    # advances for every non-pending verdict and so would not discriminate
    assert out["verdict"] == "on_time"
    assert last_wake_observe(root)["verdict"] == "on_time"
    record = wake_record(root)
    assert record["last_verdict"] == "on_time"
    assert record["expected_next_fire"] != before_fire


def test_wake_backward_compatible_legacy_ledger(tmp_path):
    root = ledger(tmp_path)
    assert wake_arm(root, cron="0 * * * *", now="2026-08-28T12:00:00Z").returncode == 0
    strip_arming_identity(root)
    # the whole lifecycle against a record carrying none of the new keys, in an
    # order that keeps it un-migrated until the re-arm; ok() asserts each exit 0
    assert ok(root, "wake-observe", now="2026-08-28T13:05:00Z")["verdict"] == "pending"
    assert ok(root, "wake-observe", "--delivered", "--channel-id", "hb-1",
              now="2026-08-28T13:06:00Z")["verdict"] == "unversioned_arming"
    assert ok(root, "wake-status", now="2026-08-28T13:07:00Z")["armed"] is True
    proc = wake_arm(root, cron="0 * * * *", now="2026-08-28T13:10:00Z")
    assert proc.returncode == 0
    minted = json.loads(proc.stdout)["arming_token"]
    assert ok(root, "wake-observe", "--delivered", "--channel-id", "hb-1",
              "--arming-token", minted,
              now="2026-08-28T14:05:00Z")["verdict"] == "on_time"


def test_wake_unnamed_claim_against_armed_token_refused(tmp_path):
    # SEMANTIC ANCHOR: invokes only CLI surface that already existed, so what
    # fails against pre-fix code is the identity assertion itself rather than
    # the novelty of a new interface. The message embeds raw stdout verbatim.
    root = ledger(tmp_path)
    assert wake_arm(root, cron="0 * * * *", now="2026-08-28T12:00:00Z").returncode == 0
    proc = run(root, "wake-observe", "--delivered", "--channel-id", "hb-1",
               now="2026-08-28T13:05:00Z")
    assert proc.returncode != 0, (
        f"ARMING_IDENTITY_SEMANTIC_ASSERTION: a delivery claim naming no arming "
        f"token must not certify against a token-bearing record: {proc.stdout}")


def strip_wake_knobs(root):
    """Rewrite config.json to the pre-knob legacy shape (simulates a ledger
    seeded by an older init; fixture construction, like the tamper fixtures
    of the generation tests)."""
    cfg_path = root / "config.json"
    cfg = json.loads(cfg_path.read_text())
    for key in ("lease_ttl_seconds", "tolerated_missed_fires", "wake_slack_minutes"):
        cfg.pop(key)
    cfg_path.write_text(json.dumps(cfg))
    return cfg


def test_lease_ttl_fallback_on_legacy_config_warns_but_succeeds(tmp_path):
    root = ledger(tmp_path)
    strip_wake_knobs(root)
    r = run(root, "lease-acquire", "--holder", "ctl-A", now=T0)
    assert r.returncode == 0  # no KeyError: .get() fallback, never direct-key reads
    lease = json.loads((root / "lease.json").read_text())
    assert lease["expires_at"] == "2026-08-28T13:00:00Z"  # ultimate fallback 3600 s
    assert "WARNING" in r.stderr and "6300" in r.stderr  # invariant violated, op succeeds
    r = run(root, "lease-renew", "--holder", "ctl-A", now="2026-08-28T12:10:00Z")
    assert r.returncode == 0
    lease = json.loads((root / "lease.json").read_text())
    assert lease["expires_at"] == "2026-08-28T13:10:00Z"
    assert "WARNING" in r.stderr


def test_lease_ttl_default_from_seeded_config_satisfies_invariant(tmp_path):
    root = ledger(tmp_path)
    r = run(root, "lease-acquire", "--holder", "ctl-A", now=T0)
    assert r.returncode == 0
    lease = json.loads((root / "lease.json").read_text())
    assert lease["expires_at"] == "2026-08-28T14:00:00Z"  # seeded lease_ttl_seconds=7200
    assert "WARNING" not in r.stderr  # 7200 >= 6300: no coupling warning


def test_config_knobs_seeded_by_init_satisfy_coupling_invariant(tmp_path):
    root = ledger(tmp_path)
    cfg = json.loads((root / "config.json").read_text())
    assert cfg["lease_ttl_seconds"] == 7200
    assert cfg["tolerated_missed_fires"] == 1
    assert cfg["wake_slack_minutes"] == 15
    required = ((cfg["tolerated_missed_fires"] + 1) * cfg["heartbeat_minutes"] * 60
                + cfg["wake_slack_minutes"] * 60)
    assert cfg["lease_ttl_seconds"] >= required


def test_config_knobs_init_never_overwrites_existing_config(tmp_path):
    root = ledger(tmp_path)
    legacy = strip_wake_knobs(root)
    ok(root, "init", "--accounts", "orchestrade,yugetang,yugoge")  # idempotent re-init
    assert json.loads((root / "config.json").read_text()) == legacy


def test_teardown_declare_journals_pending_ids_reason_and_lease_disposition(tmp_path):
    root = ledger(tmp_path)
    append(root, "ev-1")
    append(root, "ev-2")
    ok(root, "lease-acquire", "--holder", "ctl-A", now=T0)
    out = ok(root, "teardown-declare", "--reason", "session ending: user stop",
             now="2026-08-28T12:30:00Z")
    assert out["pending_event_ids"] == ["ev-1", "ev-2"]
    assert out["lease_disposition"]["state"] == "held"
    last = json.loads((root / "journal.ndjson").read_text().strip().splitlines()[-1])
    assert last["op"] == "teardown-declare"
    assert last["pending_event_ids"] == ["ev-1", "ev-2"]
    assert last["reason"] == "session ending: user stop"
    assert last["lease_disposition"]["holder"] == "ctl-A"
    assert last["lease_disposition"]["incarnation"] == 1


def test_teardown_contract_text_mandates_drain_or_declare():
    text = (REPO / "commands" / "paseo-daemon.md").read_text()
    assert "teardown-declare" in text
    assert "drain" in text.lower()


def test_source_audit_no_live_ledger_path_in_test_functions():
    """tmp_path ledgers only: no function in this file may carry the live
    ledger directory in a string constant (needle assembled at runtime so
    this audit's own source stays clean; the module docstring is the single
    allowed mention and lives outside any function)."""
    needle = ".claude/" + "paseo-daemon"
    tree = ast.parse(Path(__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    assert needle not in sub.value, (
                        f"{node.name} references the live ledger path")


# ---------------- vendor parity: the deployed scheduler is the oracle
# ---------------- (task 20260904-181435-a, lane req-01) ----------------

VENDOR_VECTORS = json.loads(VENDOR_VECTORS_PATH.read_text())
UTC_SUFFIX = "+00:00"


def as_utc(text):
    from datetime import datetime
    return datetime.fromisoformat(text.replace("Z", UTC_SUFFIX))


def as_iso(moment):
    from datetime import timezone as tzmod
    return moment.astimezone(tzmod.utc).isoformat().replace(UTC_SUFFIX, "Z")


def engine_sequence(module, expression, zone, after, count):
    """Enumerate `count` consecutive occurrences with the LEDGER engine."""
    spec = module.parse_cron(expression)
    cursor = as_utc(after)
    out = []
    for _ in range(count):
        cursor = module.cron_next_fire(spec, cursor, zone)
        out.append(as_iso(cursor))
    return out


def vendor_vector(section, **match):
    for entry in VENDOR_VECTORS[section]:
        if all(entry[key] == value for key, value in match.items()):
            return entry
    raise AssertionError(f"no {section} vector matching {match}")


# ---------------- AC-01: the fall-back repeat is a real fire ----------------

def test_vendor_fold_both_occurrences_matches_deployed_instants():
    # The deployed scheduler has no fold handling: it projects each
    # whole-minute UTC candidate and matches the fields it reads, so a
    # restricted hour field fires at BOTH occurrences of the repeated wall
    # time. Scored against instants CAPTURED FROM that scheduler.
    vector = vendor_vector("positive", expression="30 1 * * *",
                           timezone="America/New_York")
    got = engine_sequence(load_engine(), vector["expression"],
                          vector["timezone"], vector["after"], vector["count"])
    assert got == vector["sequence"]
    assert "2026-11-01T05:30:00Z" in got and "2026-11-01T06:30:00Z" in got


def test_vendor_fold_both_occurrences_hours_restricted_gate_removed():
    # No code path gates fire enumeration on whether the hour field is
    # restricted. The forbidden identifier is read from the registry rather
    # than spelled, so this node proves an absence without carrying it.
    gate = DELETED_PREMISE_LITERALS[0]
    module = load_engine()
    assert gate not in module.parse_cron("30 1 * * *")
    assert gate not in code_tokens(LEDGER)
    # and the removal is observable, not merely textual: a restricted and an
    # unrestricted hour field agree on the repeated hour.
    restricted = engine_sequence(module, "30 1 * * *", "America/New_York",
                                 "2026-11-01T05:29:00Z", 2)
    unrestricted = engine_sequence(module, "30 * * * *", "America/New_York",
                                   "2026-11-01T05:29:00Z", 2)
    assert restricted == ["2026-11-01T05:30:00Z", "2026-11-01T06:30:00Z"]
    assert unrestricted[:2] == ["2026-11-01T05:30:00Z", "2026-11-01T06:30:00Z"]


# ---------------- AC-02a / AC-02b: the 25-hour fail-open window ----------------

def arm_fall_back_channel(tmp_path):
    """The armed-then-dead channel of AC-02: armed before the fall-back,
    its FIRST repeated-hour fire delivered on time, then silence."""
    root = ledger(tmp_path)
    assert wake_arm(root, cron="30 1 * * *", tz=NY,
                    now="2026-11-01T04:00:00Z").returncode == 0
    assert wake_record(root)["expected_next_fire"] == "2026-11-01T05:30:00Z"
    out = ok(root, *delivered_claim(root),
             now="2026-11-01T05:31:00Z")
    assert out["verdict"] == "on_time"
    # the watermark now points at the SECOND occurrence of the repeated hour
    assert out["expected_next_fire"] == "2026-11-01T06:30:00Z"
    return root


def test_fail_open_window_closed_observer_detects_death_at_second_fall_back_fire(tmp_path):
    root = arm_fall_back_channel(tmp_path)
    # 06:46Z is one minute past the second fall-back fire's deadline, roughly
    # 1h15m after the channel's last proof of life. Pre-fix the watermark had
    # skipped to 2026-11-02T06:30Z and this read healthy for 25h14m.
    out = ok(root, "wake-observe", now="2026-11-01T06:46:00Z")
    assert out["verdict"] == "missed"
    assert out["missed_fires"] >= 1
    assert out["needs_rearm"] is True


def test_fail_open_window_closed_observer_appends_missed_event_and_latches_rearm(tmp_path):
    root = arm_fall_back_channel(tmp_path)
    out = ok(root, "wake-observe", now="2026-11-01T06:46:00Z")
    pending = list((root / "inbox" / "pending").glob("wake-missed-*.json"))
    assert len(pending) == 1
    payload = json.loads(pending[0].read_text())["payload"]
    assert payload["type"] == "wake_channel_missed"
    assert payload["first_missed_fire"] == "2026-11-01T06:30:00Z"
    assert wake_record(root)["needs_rearm"] is True
    assert out["inbox_event_id"] is not None
    # and there is no surviving window through 2026-11-02 in which the channel
    # reads fresh with no misses -- the pre-fix reading for 25h14m
    later = ok(root, "wake-status", now="2026-11-02T00:00:00Z")
    assert not (later["stale"] is False and later["missed_total"] == 0)
    assert later["needs_rearm"] is True


def test_fail_open_window_closed_status_only_reads_unhealthy_after_deadline(tmp_path):
    # A consumer that only polls the status surface, and never runs the
    # observer, must still be unable to read a dead channel as healthy.
    root = arm_fall_back_channel(tmp_path)
    out = ok(root, "wake-status", now="2026-11-01T06:46:00Z")
    assert out["deadline"] == "2026-11-01T06:45:00Z"
    assert out["stale"] is True


# ---------------- AC-03: a late delivery no longer exonerates its fire ----------------

def arm_daily_utc(tmp_path, *, now="2026-03-01T00:00:00Z", **kw):
    root = ledger(tmp_path)
    assert wake_arm(root, cron="0 0 * * *", tz="UTC", now=now, **kw).returncode == 0
    return root


def test_late_latches_counts_the_unhonoured_fire(tmp_path):
    root = arm_daily_utc(tmp_path)
    # 11 hours after the 2026-03-02T00:00Z fire, far beyond wake_slack.
    out = ok(root, *delivered_claim(root),
             now="2026-03-02T11:00:00Z")
    assert out["verdict"] == "late"
    assert out["missed_fires"] == 1


def test_late_latches_needs_rearm_and_appends_event(tmp_path):
    root = arm_daily_utc(tmp_path)
    out = ok(root, *delivered_claim(root),
             now="2026-03-02T11:00:00Z")
    assert out["needs_rearm"] is True
    assert out["inbox_event_id"] is not None
    assert wake_record(root)["needs_rearm"] is True
    assert "wake_channel_missed" in (root / "journal.ndjson").read_text()


def test_late_latches_three_consecutive_days_cannot_read_healthy(tmp_path):
    root = arm_daily_utc(tmp_path)
    for day in ("02", "03", "04"):
        ok(root, *delivered_claim(root),
           now=f"2026-03-{day}T11:00:00Z")
    status = ok(root, "wake-status", now="2026-03-04T11:05:00Z")
    assert status["missed_total"] == 3
    assert status["needs_rearm"] is True


# ---------------- AC-04a / AC-04b: the on-time path does not regress ----------------

def test_on_time_single_elapsed_fire_delivery_within_slack_is_on_time(tmp_path):
    root = arm_daily_utc(tmp_path)
    out = ok(root, *delivered_claim(root),
             now="2026-03-02T00:05:00Z")
    assert out["verdict"] == "on_time"
    assert out["missed_fires"] == 0
    assert out["needs_rearm"] is False
    assert out["trust_state"] == "trusted"


def test_on_time_single_elapsed_fire_no_missed_event_and_watermark_advances(tmp_path):
    root = arm_daily_utc(tmp_path)
    out = ok(root, *delivered_claim(root),
             now="2026-03-02T00:05:00Z")
    assert out["inbox_event_id"] is None
    assert list((root / "inbox" / "pending").glob("wake-missed-*.json")) == []
    assert out["expected_next_fire"] == "2026-03-03T00:00:00Z"


def test_on_time_multi_elapsed_fires_older_expired_fire_counted_missed(tmp_path):
    root = arm_daily_utc(tmp_path)
    # 2026-03-02 and 2026-03-03 have both elapsed; only the latest is
    # delivered on time. Delivery and deadline expiry are independent facts.
    out = ok(root, *delivered_claim(root),
             now="2026-03-03T00:05:00Z")
    assert out["verdict"] == "on_time"
    assert out["missed_fires"] == 1
    assert ok(root, "wake-status", now="2026-03-03T00:06:00Z")["missed_total"] == 1


def test_on_time_multi_elapsed_fires_event_appended_and_rearm_latched(tmp_path):
    root = arm_daily_utc(tmp_path)
    out = ok(root, *delivered_claim(root),
             now="2026-03-03T00:05:00Z")
    assert out["inbox_event_id"] is not None
    assert out["needs_rearm"] is True
    payload = json.loads(next((root / "inbox" / "pending").glob(
        "wake-missed-*.json")).read_text())["payload"]
    assert payload["first_missed_fire"] == "2026-03-02T00:00:00Z"


# ---------------- AC-05: the two day fields intersect ----------------

def test_dom_dow_intersection_matches_deployed_scheduler():
    vector = vendor_vector("positive", expression="0 0 13 * 5")
    got = engine_sequence(load_engine(), vector["expression"],
                          vector["timezone"], vector["after"], vector["count"])
    assert got == vector["sequence"]
    assert got[0] == "2026-02-13T00:00:00Z"


def test_dom_dow_intersection_no_phantom_february_sixth():
    # 2026-02-06 is a Friday that is not the 13th. The union rule manufactured
    # it, and every phantom fire latched a re-arm demand whose remedy erased
    # missed_total, needs_rearm and last_verdict.
    got = engine_sequence(load_engine(), "0 0 13 * 5", "UTC",
                          "2026-02-01T00:00:00Z", 3)
    assert "2026-02-06T00:00:00Z" not in got
    vector = vendor_vector("positive", expression="0 0 13 * 5")
    assert "2026-02-06T00:00:00Z" not in vector["sequence"]


# ---------------- AC-06: day-of-week 7 is refused, as the vendor refuses it ----------------

def test_dow_seven_refused_at_arm_non_zero_exit(tmp_path):
    r = wake_arm(ledger(tmp_path), cron="0 0 * * 7", tz="UTC")
    assert r.returncode == 2
    assert "day-of-week" in r.stderr
    vector = vendor_vector("negative", kind="cron_dow_seven")
    assert vector["vendor_error"] == "Invalid cron day-of-week value"


def test_dow_seven_refused_no_armed_record_persisted(tmp_path):
    root = ledger(tmp_path)
    assert wake_arm(root, cron="0 0 * * 7", tz="UTC").returncode == 2
    assert not (root / "wake.json").exists()


# ---------------- AC-07: the deployed occurrence-search budget ----------------

def test_horizon_527040_budget_is_end_exclusive_at_both_boundaries():
    from datetime import timedelta
    module = load_engine()
    budget = module.VENDOR_OCCURRENCE_BUDGET_CANDIDATES
    assert budget == 366 * 24 * 60
    inside = vendor_vector("horizon", boundary="last_in_budget_candidate")
    outside = vendor_vector("horizon", boundary="first_out_of_budget_candidate")
    # the two vectors differ by exactly one minute of `after`, which is what
    # makes them a boundary pair rather than two unrelated cases
    assert as_utc(inside["after"]) - as_utc(outside["after"]) == timedelta(minutes=1)
    spec = module.parse_cron(inside["expression"])
    got = module.cron_next_fire(spec, as_utc(inside["after"]), inside["timezone"])
    assert as_iso(got) == inside["instant"]
    # END-EXCLUSIVE, stated as arithmetic: candidates start at
    # startOfNextMinute(after), so the SAME instant sits at index budget-1 for
    # the in-budget vector and at index budget for the out-of-budget one. An
    # inclusive bound would resolve the second and this pair would not split.
    assert as_utc(inside["instant"]) == (
        as_utc(inside["after"]) + timedelta(minutes=budget))
    assert as_utc(inside["instant"]) == (
        as_utc(outside["after"]) + timedelta(minutes=budget + 1))
    with pytest.raises(SystemExit) as exc:
        module.cron_next_fire(module.parse_cron(outside["expression"]),
                              as_utc(outside["after"]), outside["timezone"])
    assert exc.value.code == 2
    assert outside["vendor_error"].startswith("Unable to compute next run time")


def test_horizon_527040_unreachable_cadence_refused_at_arm(tmp_path):
    root = ledger(tmp_path)
    outside = vendor_vector("horizon", boundary="first_out_of_budget_candidate")
    r = wake_arm(root, cron=outside["expression"], tz=outside["timezone"],
                 now=outside["after"])
    assert r.returncode == 2
    assert "527040-candidate window" in r.stderr
    assert not (root / "wake.json").exists()


def test_horizon_527040_no_400_year_claim_remains_in_source():
    # The forbidden literals are ITERATED from the single registry, never
    # spelled here: a node that asserts an absence must not itself become the
    # last carrier of it.
    engine_source = LEDGER.read_text()
    doc_source = COMMAND_DOC.read_text()
    for literal in DELETED_PREMISE_LITERALS:
        assert literal not in engine_source, literal
        assert literal not in doc_source, literal
    for pattern in [r"400-year", r"146,?097", r"400\s+Gregorian"]:
        assert not re.search(pattern, engine_source), pattern
        assert not re.search(pattern, doc_source), pattern


# ---------------- AC-08: committed vendor-derived golden vectors ----------------

def test_vendor_golden_vectors_assert_unconditionally_without_node():
    # The vectors are COMMITTED, so absence of node or of the deployed module
    # cannot silently skip the differential. Proven by construction: this node
    # touches neither, and the file's own source carries no skip marker.
    assert VENDOR_VECTORS_PATH.is_file()
    provenance = VENDOR_VECTORS["provenance"]
    assert provenance["server_package"] == "@getpaseo/server 0.2.2"
    assert provenance["protocol_package"] == "@getpaseo/protocol 0.2.2"
    assert len(provenance["cron_js_sha256"]) == 64
    # needles assembled at runtime and matched against the token stream, so
    # this audit's own source cannot satisfy or defeat it
    tokens = code_tokens(Path(__file__))
    assert ("skip" + "if") not in tokens
    assert ("pytest" + " . " + "skip") not in tokens
    module = load_engine()
    vector = vendor_vector("positive", expression="12,57 * * * *")
    assert engine_sequence(module, vector["expression"], vector["timezone"],
                           vector["after"], vector["count"]) == vector["sequence"]


def test_vendor_golden_vectors_zero_divergence_across_transition_zones():
    module = load_engine()
    divergences = []
    for vector in VENDOR_VECTORS["positive"]:
        got = engine_sequence(module, vector["expression"], vector["timezone"],
                              vector["after"], vector["count"])
        if got != vector["sequence"]:
            divergences.append((vector["expression"], vector["timezone"], got,
                                vector["sequence"]))
    assert divergences == []
    covered = {vector["zone_class"] for vector in VENDOR_VECTORS["positive"]}
    assert {"fall_back", "spring_forward", "sub_hour_offset",
            "five_field_and"} <= covered


def test_vendor_golden_vectors_include_negative_parser_timezone_and_horizon_cases(tmp_path):
    module = load_engine()
    kinds = {vector["kind"] for vector in VENDOR_VECTORS["negative"]}
    assert {"cron_step", "cron_non_ascii_digit", "cron_dow_seven",
            "timezone"} <= kinds
    for vector in VENDOR_VECTORS["negative"]:
        assert vector["vendor_error"], vector
    # each expected-ERROR vector is refused by the ledger too, on its own root
    for index, vector in enumerate(VENDOR_VECTORS["negative"]):
        root = ledger(tmp_path / f"negative-{index}")
        r = wake_arm(root, cron=vector["expression"], tz=vector["timezone"],
                     now=vector["after"])
        assert r.returncode == 2, vector
        assert not (root / "wake.json").exists(), vector
    boundaries = {vector["boundary"] for vector in VENDOR_VECTORS["horizon"]}
    assert boundaries == {"last_in_budget_candidate",
                          "first_out_of_budget_candidate"}


# ---------------- AC-09: a pre-marker record is untrusted, never stranded ----------------

def legacy_wake_record():
    """A wake.json as the PRE-FIX engine wrote it: no engine-policy marker, no
    trust container, and an optimistic watermark that skipped the fall-back
    repeat at 2026-11-01T06:30Z straight to the next day."""
    return {
        "channel_kind": "paseo_heartbeat",
        "channel_id": "hb-1",
        "cron": "30 1 * * *",
        "timezone": NY,
        "role": "tick",
        "max_runs": None,
        "armed_at": "2026-11-01T04:00:00Z",
        "expected_next_fire": "2026-11-02T06:30:00Z",
        "last_observed_at": "2026-11-01T05:31:00Z",
        "last_verdict": "on_time",
        "missed_total": 0,
        "needs_rearm": False,
    }


def seed_legacy_ledger(tmp_path):
    root = ledger(tmp_path)
    put_wake_record(root, legacy_wake_record())
    return root


def test_legacy_record_untrusted_absent_marker_is_not_current_policy(tmp_path):
    root = seed_legacy_ledger(tmp_path)
    status = ok(root, "wake-status", now="2026-11-01T06:46:00Z")
    assert status["trust_state"] == "untrusted"
    assert status["trust_reason"] == "engine_policy_absent"
    # absence terminated the predicate: it never compared two missing values
    assert "engine_policy" not in wake_record(root)


def test_legacy_record_untrusted_pre_fix_deadline_cannot_read_healthy(tmp_path):
    root = seed_legacy_ledger(tmp_path)
    # its own optimistic deadline says nothing is due until 2026-11-02T06:45Z
    status = ok(root, "wake-status", now="2026-11-01T06:46:00Z")
    assert status["stale"] is False
    assert status["needs_rearm"] is True   # the trust predicate, not staleness
    observed = ok(root, "wake-observe", now="2026-11-01T06:46:00Z")
    assert observed["needs_rearm"] is True
    assert observed["trust_state"] == "untrusted"


def test_legacy_record_untrusted_no_stranded_state_directory(tmp_path):
    root = seed_legacy_ledger(tmp_path)
    original = legacy_wake_record()
    status = ok(root, "wake-status", now="2026-11-01T06:46:00Z")
    for key, value in original.items():
        assert key in status, key
        assert status[key] == value or key == "needs_rearm", key
    # and the record still loads through the mutating path without repair
    assert ok(root, "wake-observe", now="2026-11-01T06:46:00Z")["ok"] is True
    after = wake_record(root)
    for key in original:
        assert key in after, key


# ---------------- AC-12: a delivery with nothing due proves nothing ----------------

HEALTH_BEARING = ("last_observed_at", "last_verdict", "missed_total",
                  "needs_rearm", "expected_next_fire")


def arm_before_first_fire(tmp_path):
    root = ledger(tmp_path)
    assert wake_arm(root, cron="0 0 * * *", tz="UTC",
                    now="2026-03-01T00:00:00Z").returncode == 0
    assert wake_record(root)["expected_next_fire"] == "2026-03-02T00:00:00Z"
    return root


def test_prefire_delivery_non_proving_verdict_is_not_on_time(tmp_path):
    root = arm_before_first_fire(tmp_path)
    out = ok(root, *delivered_claim(root),
             now="2026-03-01T12:00:00Z")
    assert out["verdict"] != "on_time"
    assert out["verdict"] == "non_proving"
    assert out["missed_fires"] == 0


def test_prefire_delivery_non_proving_watermark_does_not_advance(tmp_path):
    # REGRESSION GUARD: this already held pre-fix. Retained so a later change
    # cannot start pushing the deadline forward on a non-proving claim.
    root = arm_before_first_fire(tmp_path)
    ok(root, *delivered_claim(root),
       now="2026-03-01T12:00:00Z")
    assert wake_record(root)["expected_next_fire"] == "2026-03-02T00:00:00Z"


def test_prefire_delivery_non_proving_health_fields_unchanged(tmp_path):
    root = arm_before_first_fire(tmp_path)
    instant = "2026-03-01T12:00:00Z"
    before_record = wake_record(root)
    before_status = ok(root, "wake-status", now=instant)
    ok(root, *delivered_claim(root), now=instant)
    after_record = wake_record(root)
    after_status = ok(root, "wake-status", now=instant)
    for field in HEALTH_BEARING:
        assert before_record.get(field) == after_record.get(field), field
        assert before_status[field] == after_status[field], field
    for field in ("stale", "deadline"):
        assert before_status[field] == after_status[field], field
    # last_observed_at is the field that would have carried a manufactured
    # proof of life: pre-fix it went null -> the claim instant.
    assert after_record["last_observed_at"] is None
    # the ONLY permitted difference is the explicit non-proving marker
    difference = {key for key in set(before_record) | set(after_record)
                  if before_record.get(key) != after_record.get(key)}
    assert difference == {"last_non_proving_claim_at"}


# ---------------- AC-13: the four measured vendor-rejected inputs ----------------

def refuse_and_persist_nothing(root, **kw):
    r = wake_arm(root, **kw)
    assert r.returncode == 2, r.stdout
    assert not (root / "wake.json").exists()
    return r


def test_accept_set_parity_zero_padded_step_refused(tmp_path):
    vector = vendor_vector("negative", kind="cron_step")
    assert vector["vendor_error"] == "Invalid cron minute step"
    r = refuse_and_persist_nothing(ledger(tmp_path), cron=vector["expression"],
                                   tz=vector["timezone"])
    assert "non-canonical cron minute step" in r.stderr


def test_accept_set_parity_non_ascii_digit_refused(tmp_path):
    # Python's \d admits every Unicode decimal digit; the vendor's /^\d+$/ is
    # ASCII-only, so this cadence is one it will never create.
    vector = vendor_vector("negative", kind="cron_non_ascii_digit")
    assert vector["vendor_error"] == "Invalid cron minute value"
    assert not vector["expression"].split()[0].isascii()
    refuse_and_persist_nothing(ledger(tmp_path), cron=vector["expression"],
                               tz=vector["timezone"])


def test_accept_set_parity_timezone_factory_refused(tmp_path):
    vector = vendor_vector("negative", kind="timezone", timezone="Factory")
    assert vector["vendor_error"] == "Invalid cron time zone: Factory"
    from zoneinfo import ZoneInfo
    ZoneInfo(vector["timezone"])   # the ledger's own rule source resolves it
    r = refuse_and_persist_nothing(ledger(tmp_path), cron=vector["expression"],
                                   tz=vector["timezone"])
    assert "deployed scheduler refuses timezone" in r.stderr


def test_accept_set_parity_timezone_localtime_refused(tmp_path):
    # Its OWN fresh root, so no single test can discharge the pair while the
    # other vector still persists a record.
    vector = vendor_vector("negative", kind="timezone", timezone="localtime")
    assert vector["vendor_error"] == "Invalid cron time zone: localtime"
    r = refuse_and_persist_nothing(ledger(tmp_path), cron=vector["expression"],
                                   tz=vector["timezone"])
    assert "deployed scheduler refuses timezone" in r.stderr


def test_accept_set_parity_no_armed_record_for_vendor_rejected_input(tmp_path):
    # Refusal precedes persistence for EVERY measured vector, so there is
    # never a window in which a falsely-armed record reads healthy.
    for index, vector in enumerate(VENDOR_VECTORS["negative"]):
        root = ledger(tmp_path / f"parity-{index}")
        refuse_and_persist_nothing(root, cron=vector["expression"],
                                   tz=vector["timezone"], now=vector["after"])


# ---------------- timezone rule-source trust: the bound on a divergence
# ---------------- that cannot be removed (AC-14, AC-15, AC-17 - AC-25) --------

NODE = "/usr/bin/node"
VENDOR_CRON_JS = ("/opt/paseo/node_modules/@getpaseo/server/dist/server"
                  "/server/schedule/cron.js")
# Candidate zones for the runtime-computed agreement partition. The PARTITION
# is measured, never assumed: nothing here declares which side a zone lands on.
PARTITION_CANDIDATE_ZONES = [
    "UTC", "America/New_York", "America/Edmonton", "Europe/London",
    "Australia/Lord_Howe", "Asia/Kolkata", "Africa/Casablanca",
    "Pacific/Chatham",
]
PARTITION_WINDOW_START = "2026-09-04T18:00:00Z"
PARTITION_WINDOW_DAYS = 90


def vendor_node_sequences(requests):
    """Enumerate occurrences with the DEPLOYED scheduler itself, one node
    process for the whole batch. Never used as a health signal -- only as the
    oracle the ledger engine is scored against."""
    script = (
        "const reqs=JSON.parse(process.argv[1]);"
        f"import({VENDOR_CRON_JS!r}).then(m=>{{const out=reqs.map(r=>{{"
        "let c=new Date(r.after);const s=[];"
        "for(let i=0;i<r.count;i+=1){c=m.computeNextRunAt({type:'cron',"
        "expression:r.expression,timezone:r.timezone},c);"
        "s.push(c.toISOString().replace('.000Z','Z'));}return s;});"
        "process.stdout.write(JSON.stringify(out));});")
    proc = subprocess.run([NODE, "-e", script, "--", json.dumps(requests)],
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def runtime_agreement_partition(module, zones, start, days):
    """Split `zones` by MEASURING both rule sources over one window. Returns
    (agreeing, diverging); nothing about the split is hardcoded."""
    from datetime import timedelta
    begin = as_utc(start)
    end = begin + timedelta(days=days)
    agreeing, diverging = [], []
    for zone in zones:
        status, vendor_table = module.vendor_offset_table(NODE, zone, begin, end)
        assert status == "ok", (zone, status)
        ledger_table = module.zone_offset_table(zone, begin, end)
        (agreeing if ledger_table == vendor_table else diverging).append(zone)
    return agreeing, diverging


def test_vendor_live_differential_agreeing_zone_set_computed_at_runtime():
    module = load_engine()
    agreeing, diverging = runtime_agreement_partition(
        module, PARTITION_CANDIDATE_ZONES, PARTITION_WINDOW_START,
        PARTITION_WINDOW_DAYS)
    assert agreeing, "no zone agrees: the partition instrument is broken"
    crons = ["0 12 * * *", "*/15 * * * *"]
    requests = [{"expression": cron, "timezone": zone,
                 "after": PARTITION_WINDOW_START, "count": 4}
                for zone in agreeing for cron in crons]
    vendor = vendor_node_sequences(requests)
    divergences = []
    for request, expected in zip(requests, vendor):
        got = engine_sequence(module, request["expression"], request["timezone"],
                              request["after"], request["count"])
        if got != expected:
            divergences.append((request, got, expected))
    assert divergences == []


def test_vendor_live_differential_complement_is_measured_and_nonempty():
    # The complement of the SAME runtime-computed partition. Asserting it is
    # non-empty is what keeps the agreeing-set differential from passing
    # vacuously by quietly excluding every interesting zone; asserting no
    # FIXED set is what keeps it from failing a correct implementation after
    # a tzdata or Node upgrade.
    module = load_engine()
    agreeing, diverging = runtime_agreement_partition(
        module, PARTITION_CANDIDATE_ZONES, PARTITION_WINDOW_START,
        PARTITION_WINDOW_DAYS)
    assert set(agreeing) | set(diverging) == set(PARTITION_CANDIDATE_ZONES)
    assert not set(agreeing) & set(diverging)
    assert diverging, (
        "the two rule sources now agree on every candidate zone over this "
        "window; the divergence set must be re-measured, not assumed gone")


# ---------------- AC-15: what arming proves, and over which window ----------------

DIVERGENT_ARM_NOW = "2026-10-25T00:00:00Z"
AGREEING_ARM_NOW = "2026-09-04T18:00:00Z"
WINDOW_SCOPED_ZONE = "America/Edmonton"


def test_tz_rule_source_divergent_zone_in_window_refused_no_record_written(tmp_path):
    root = ledger(tmp_path)
    r = wake_arm(root, cron="0 1 * * *", tz=WINDOW_SCOPED_ZONE,
                 now=DIVERGENT_ARM_NOW, verify_window_days=30)
    assert r.returncode == 2, r.stdout
    assert "timezone rule sources disagree" in r.stderr
    assert WINDOW_SCOPED_ZONE in r.stderr
    assert "first disagreeing run start" in r.stderr
    assert not (root / "wake.json").exists()


def test_tz_rule_source_agreeing_zone_in_window_arms_with_marker_and_window_bounds(tmp_path):
    root = ledger(tmp_path)
    assert wake_arm(root, cron="0 1 * * *", tz=WINDOW_SCOPED_ZONE,
                    now=AGREEING_ARM_NOW, verify_window_days=30).returncode == 0
    trust = wake_record(root)["tz_rule_source"]
    assert trust["verified"] is True
    assert trust["verified_from"] == AGREEING_ARM_NOW
    assert trust["verified_until"] == "2026-10-04T18:00:00Z"
    assert len(trust["fingerprint"]) == 64
    assert ok(root, "wake-status", now=AGREEING_ARM_NOW)["trust_state"] == "trusted"


def test_tz_rule_source_same_zone_arms_or_refuses_by_window_scope(tmp_path):
    # ONE zone, ONE start instant, two windows: the guarantee is window-scoped,
    # so neither outcome can be read as a property of the zone.
    short_root = ledger(tmp_path / "short")
    long_root = ledger(tmp_path / "long")
    assert wake_arm(short_root, cron="0 1 * * *", tz=WINDOW_SCOPED_ZONE,
                    now=AGREEING_ARM_NOW, verify_window_days=30).returncode == 0
    wide = wake_arm(long_root, cron="0 1 * * *", tz=WINDOW_SCOPED_ZONE,
                    now=AGREEING_ARM_NOW, verify_window_days=90)
    assert wide.returncode == 2, wide.stdout
    assert "timezone rule sources disagree" in wide.stderr
    assert not (long_root / "wake.json").exists()


def unconsultable_vendor_root(tmp_path, **kw):
    root = ledger(tmp_path)
    set_config(root, wake_vendor_node_path=str(tmp_path / "no-such-runtime"))
    assert wake_arm(root, **kw).returncode == 0
    return root


def test_tz_rule_source_unverifiable_vendor_arms_untrusted_never_delivering(tmp_path):
    root = unconsultable_vendor_root(tmp_path, cron="0 0 * * *", tz="UTC",
                                     now="2026-03-01T00:00:00Z")
    trust = wake_record(root)["tz_rule_source"]
    assert trust["verified"] is False
    assert trust["reason"] == "vendor_unconsultable"
    status = ok(root, "wake-status", now="2026-03-01T00:05:00Z")
    assert status["trust_state"] == "untrusted"
    assert status["trust_reason"] == "vendor_unconsultable"
    assert status["needs_rearm"] is True     # never a delivering reading
    observed = ok(root, *delivered_claim(root),
                  now="2026-03-02T00:05:00Z")
    assert observed["verdict"] == "on_time"
    assert observed["needs_rearm"] is True


def test_tz_rule_source_divergence_set_is_measured_not_assumed():
    module = load_engine()
    agreeing, diverging = runtime_agreement_partition(
        module, PARTITION_CANDIDATE_ZONES, PARTITION_WINDOW_START,
        PARTITION_WINDOW_DAYS)
    assert diverging, (
        "no candidate zone diverges over this window any more; re-measure the "
        "set rather than deleting the guarantee")
    # and the criterion asserts no FIXED membership: the same zone may sit on
    # either side depending only on the window examined
    narrow_agreeing, _ = runtime_agreement_partition(
        module, diverging[:1], PARTITION_WINDOW_START, 30)
    assert isinstance(narrow_agreeing, list)
    assert set(agreeing).isdisjoint(diverging)


# ---------------- AC-17: beyond the window the channel reads untrusted --------

def arm_trusted_daily(tmp_path, *, now="2026-03-01T00:00:00Z", days=30, **kw):
    root = ledger(tmp_path)
    assert wake_arm(root, cron="0 0 * * *", tz="UTC", now=now,
                    verify_window_days=days, **kw).returncode == 0
    assert wake_record(root)["tz_rule_source"]["verified"] is True
    return root


def test_tz_trust_window_expired_reads_untrusted_not_delivering(tmp_path):
    root = arm_trusted_daily(tmp_path)
    inside = ok(root, "wake-status", now="2026-03-30T00:00:00Z")
    assert inside["trust_state"] == "trusted"
    # the operative sentence, driven by the CLOCK and read off the OUTPUT
    outside = ok(root, "wake-status", now="2026-04-01T00:00:00Z")
    assert outside["trust_state"] == "untrusted"
    assert outside["trust_reason"] == "window_expired"
    assert outside["needs_rearm"] is True
    assert ok(root, "wake-observe", now="2026-04-01T00:00:00Z"
              )["needs_rearm"] is True


def test_tz_trust_window_absent_reads_untrusted_not_unbounded(tmp_path):
    root = arm_trusted_daily(tmp_path)
    record = wake_record(root)
    record["tz_rule_source"].pop("verified_until")
    put_wake_record(root, record)
    # an absent bound is EXPIRED, never infinite: even one minute after arming
    status = ok(root, "wake-status", now="2026-03-01T00:01:00Z")
    assert status["trust_state"] == "untrusted"
    assert status["trust_reason"] == "verification_window_absent"
    assert status["needs_rearm"] is True


# ---------------- AC-18: an in-window rule change is detected ----------------

def tzif_fixture(tmp_path, zone, donor):
    """Serve DIFFERENT rules under `zone`'s own name, by copying `donor`'s
    TZif into a private tz path. Proven constructible: America/New_York's
    rules under the name America/Edmonton flip Edmonton's 2026-11-01T08:00Z
    offset from -07:00 to -05:00."""
    root = tmp_path / "tzfixture"
    target = root / zone
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path("/usr/share/zoneinfo") / donor, target)
    return {"PYTHONTZPATH": str(root)}


def arm_trusted_edmonton(tmp_path):
    root = ledger(tmp_path)
    assert wake_arm(root, cron="0 1 * * *", tz=WINDOW_SCOPED_ZONE,
                    now=AGREEING_ARM_NOW, verify_window_days=30).returncode == 0
    return root


def test_tz_trust_fingerprint_change_reads_untrusted(tmp_path):
    root = arm_trusted_edmonton(tmp_path)
    inside = "2026-09-20T18:00:00Z"
    assert ok(root, "wake-status", now=inside)["trust_state"] == "trusted"
    env = tzif_fixture(tmp_path, WINDOW_SCOPED_ZONE, "America/New_York")
    changed = ok(root, "wake-status", now=inside, env=env)
    assert changed["trust_state"] == "untrusted"
    assert changed["trust_reason"] == "rule_source_changed"
    assert changed["needs_rearm"] is True


def test_tz_trust_fingerprint_tracks_served_rules_not_version_string(tmp_path):
    from datetime import timedelta
    module = load_engine()
    begin = as_utc(AGREEING_ARM_NOW)
    end = begin + timedelta(days=30)
    baseline = module.zone_offset_table(WINDOW_SCOPED_ZONE, begin, end)
    engine_before = hashlib.sha256(LEDGER.read_bytes()).hexdigest()
    env = tzif_fixture(tmp_path, WINDOW_SCOPED_ZONE, "America/New_York")
    probe = ("import json,sys;"
             "sys.path.insert(0, %r);"
             "import importlib.util as u;"
             "s=u.spec_from_file_location('eng', %r);"
             "m=u.module_from_spec(s);s.loader.exec_module(m);"
             "import datetime as d;"
             "b=d.datetime.fromisoformat('2026-09-04T18:00:00+00:00');"
             "print(json.dumps({'table': m.zone_offset_table(%r, b, "
             "b+d.timedelta(days=30)), 'version': __import__('importlib.metadata',"
             " fromlist=['x']).version('tzdata')}))"
             % (str(REPO), str(LEDGER), WINDOW_SCOPED_ZONE))
    plain = json.loads(subprocess.run([sys.executable, "-c", probe],
                                      capture_output=True, text=True,
                                      cwd=REPO).stdout)
    child_env = dict(os.environ)
    child_env.update(env)
    served = json.loads(subprocess.run([sys.executable, "-c", probe],
                                       capture_output=True, text=True,
                                       cwd=REPO, env=child_env).stdout)
    assert plain["table"] == baseline
    # the SERVED RULES changed ...
    assert served["table"] != plain["table"]
    # ... while the version string did not, and neither did the engine file:
    # a fingerprint over either channel would have seen nothing.
    assert served["version"] == plain["version"]
    assert hashlib.sha256(LEDGER.read_bytes()).hexdigest() == engine_before


# ---------------- AC-19: absence terminates the predicate ----------------

def test_tz_trust_absence_legacy_record_loads_and_reads_untrusted(tmp_path):
    root = arm_trusted_daily(tmp_path)
    full = wake_record(root)
    for missing in ("engine_policy", "tz_rule_source"):
        record = copy.deepcopy(full)
        record.pop(missing)
        put_wake_record(root, record)
        status = ok(root, "wake-status", now="2026-03-02T00:05:00Z")
        assert status["trust_state"] == "untrusted", missing
        assert status["needs_rearm"] is True, missing
        # no field removed, renamed, or required to exist for the load
        for key in record:
            assert key in status, (missing, key)
    for member in ("verified", "verified_from", "verified_until", "fingerprint",
                   "vendor_binary_path", "vendor_binary_digest"):
        record = copy.deepcopy(full)
        record["tz_rule_source"].pop(member)
        put_wake_record(root, record)
        status = ok(root, "wake-status", now="2026-03-02T00:05:00Z")
        assert status["trust_state"] == "untrusted", member


def test_tz_trust_absence_terminates_predicate_before_comparison(tmp_path):
    module = load_engine()
    calls = []
    original = module.zone_offset_table

    def spy(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    module.zone_offset_table = spy
    record = {
        "engine_policy": module.WAKE_ENGINE_POLICY,
        "timezone": "UTC",
        "tz_rule_source": {
            "verified": True,
            "verified_from": "2026-03-01T00:00:00Z",
            "verified_until": "2026-03-31T00:00:00Z",
            # fingerprint ABSENT, and the recomputation is therefore never
            # reached: two absent values are never compared
        },
    }
    state, reason = module.wake_trust_state(record, as_utc("2026-03-02T00:00:00Z"))
    assert (state, reason) == ("untrusted", "rule_source_fingerprint_absent")
    assert calls == [], "the predicate recomputed a fingerprint it had nothing to compare"


def test_tz_trust_absence_defaulting_accessor_not_used_for_evidence_fields():
    # MEASURED defect shape: the latched-health flag is read with a default,
    # so an absent flag reads HEALTHY. That idiom must not reach trust
    # evidence. Policy KNOBS may keep their defaults -- a knob is policy.
    tree = ast.parse(LEDGER.read_text())
    predicate = next(node for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef)
                     and node.name == "wake_trust_state")
    defaulted = [sub for sub in ast.walk(predicate)
                 if isinstance(sub, ast.Call)
                 and isinstance(sub.func, ast.Attribute)
                 and sub.func.attr == "get" and len(sub.args) > 1]
    assert defaulted == [], "trust evidence read through a defaulting accessor"
    knob_defaults = [sub for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef)
                     and node.name in ("cmd_wake_status", "cmd_wake_observe")
                     for sub in ast.walk(node)
                     if isinstance(sub, ast.Call)
                     and isinstance(sub.func, ast.Attribute)
                     and sub.func.attr == "get" and len(sub.args) > 1]
    assert knob_defaults, "the policy-knob idiom should still exist"


# ---------------- AC-20: untrusted is not launderable ----------------

def test_tz_trust_launder_rearm_without_verification_leaves_untrusted(tmp_path):
    root = arm_trusted_daily(tmp_path)
    set_config(root, wake_vendor_node_path=str(tmp_path / "no-such-runtime"))
    assert wake_arm(root, cron="0 0 * * *", tz="UTC",
                    now="2026-03-02T00:00:00Z").returncode == 0
    assert wake_record(root)["tz_rule_source"]["verified"] is False
    status = ok(root, "wake-status", now="2026-03-02T00:01:00Z")
    assert status["trust_state"] == "untrusted"
    assert status["needs_rearm"] is True


def test_tz_trust_launder_discharged_only_by_verification_success(tmp_path):
    root = arm_trusted_daily(tmp_path)
    set_config(root, wake_vendor_node_path=str(tmp_path / "no-such-runtime"))
    assert wake_arm(root, cron="0 0 * * *", tz="UTC",
                    now="2026-03-02T00:00:00Z").returncode == 0
    assert ok(root, "wake-status", now="2026-03-02T00:01:00Z"
              )["trust_state"] == "untrusted"
    set_config(root, wake_vendor_node_path=NODE)
    assert wake_arm(root, cron="0 0 * * *", tz="UTC",
                    now="2026-03-03T00:00:00Z").returncode == 0
    assert ok(root, "wake-status", now="2026-03-03T00:01:00Z"
              )["trust_state"] == "trusted"


def test_tz_trust_launder_read_paths_never_mutate_trust_fields(tmp_path):
    root = arm_trusted_daily(tmp_path)
    before_bytes = (root / "wake.json").read_bytes()
    ok(root, "wake-status", now="2026-03-02T00:05:00Z")
    assert (root / "wake.json").read_bytes() == before_bytes
    ok(root, *delivered_claim(root),
       now="2026-03-02T00:05:00Z")
    after = wake_record(root)
    before = json.loads(before_bytes)
    assert after["tz_rule_source"] == before["tz_rule_source"]
    assert after["engine_policy"] == before["engine_policy"]
    # and no read path healed the untrusted state of an unverified record
    set_config(root, wake_vendor_node_path=str(tmp_path / "no-such-runtime"))
    assert wake_arm(root, cron="0 0 * * *", tz="UTC",
                    now="2026-03-03T00:00:00Z").returncode == 0
    unverified = wake_record(root)["tz_rule_source"]
    ok(root, "wake-status", now="2026-03-04T00:05:00Z")
    ok(root, "wake-observe", now="2026-03-04T00:05:00Z")
    assert wake_record(root)["tz_rule_source"] == unverified


# ---------------- AC-21: the vendor binary is a negative-only signal --------

def test_tz_trust_vendor_digest_mismatch_forces_untrusted(tmp_path):
    root = arm_trusted_daily(tmp_path)
    other = tmp_path / "different-content"
    other.write_bytes(b"not the deployed runtime")
    record = wake_record(root)
    record["tz_rule_source"]["vendor_binary_path"] = str(other)
    put_wake_record(root, record)
    status = ok(root, "wake-status", now="2026-03-02T00:05:00Z")
    assert status["trust_state"] == "untrusted"
    assert status["trust_reason"] == "vendor_binary_digest_mismatch"
    assert status["needs_rearm"] is True


def test_tz_trust_vendor_digest_match_confers_no_trust_alone(tmp_path):
    root = arm_trusted_daily(tmp_path)
    # A NON-EXECUTABLE stand-in whose digest matches what the record carries:
    # if the read path executed the recorded binary this could never succeed,
    # so a trusted in-window reading here is also the proof that the read
    # DIGESTS and never executes.
    stand_in = tmp_path / "recorded-artifact"
    stand_in.write_bytes(b"deployed-runtime-stand-in")
    record = wake_record(root)
    record["tz_rule_source"]["vendor_binary_path"] = str(stand_in)
    record["tz_rule_source"]["vendor_binary_digest"] = hashlib.sha256(
        stand_in.read_bytes()).hexdigest()
    put_wake_record(root, record)
    assert ok(root, "wake-status", now="2026-03-02T00:05:00Z"
              )["trust_state"] == "trusted"
    # ... and the very same matching digest confers NOTHING once the window
    # has closed: trust is the conjunction, never this signal alone.
    expired = ok(root, "wake-status", now="2026-04-05T00:00:00Z")
    assert expired["trust_state"] == "untrusted"
    assert expired["trust_reason"] == "window_expired"


def test_tz_trust_vendor_digest_absent_binary_forces_untrusted(tmp_path):
    root = arm_trusted_daily(tmp_path)
    record = wake_record(root)
    record["tz_rule_source"]["vendor_binary_path"] = str(tmp_path / "absent")
    put_wake_record(root, record)
    status = ok(root, "wake-status", now="2026-03-02T00:05:00Z")
    assert status["trust_state"] == "untrusted"
    assert status["trust_reason"] == "vendor_binary_unreadable"


# ---------------- AC-22: the window is a knob with a floor and a ceiling ----

def test_tz_trust_verify_window_default_is_thirty_days(tmp_path):
    root = ledger(tmp_path)
    cfg = json.loads((root / "config.json").read_text())
    assert cfg["wake_verify_window_days"] == 30
    assert wake_arm(root, cron="0 0 * * *", tz="UTC",
                    now="2026-03-01T00:00:00Z").returncode == 0
    assert wake_record(root)["tz_rule_source"]["verified_until"] == \
        "2026-03-31T00:00:00Z"
    # read through load_config, not a constant: change the knob, see it move
    set_config(root, wake_verify_window_days=45)
    assert wake_arm(root, cron="0 0 * * *", tz="UTC",
                    now="2026-03-01T00:00:00Z").returncode == 0
    assert wake_record(root)["tz_rule_source"]["verified_until"] == \
        "2026-04-15T00:00:00Z"


def test_tz_trust_verify_window_shorter_than_next_fire_is_refused_at_arm(tmp_path):
    root = ledger(tmp_path)
    # monthly cadence, five-day window: the channel would go untrusted before
    # it could ever prove a delivery, so it is refused rather than armed.
    r = wake_arm(root, cron="0 0 1 * *", tz="UTC", now="2026-03-01T00:20:00Z",
                 verify_window_days=5)
    assert r.returncode == 2, r.stdout
    assert "before this channel could ever prove a delivery" in r.stderr
    assert not (root / "wake.json").exists()


def test_tz_trust_verify_window_beyond_ceiling_is_refused_at_arm(tmp_path):
    root = ledger(tmp_path)
    r = wake_arm(root, cron="0 0 * * *", tz="UTC", now="2026-03-01T00:00:00Z",
                 verify_window_days=366)
    assert r.returncode == 2, r.stdout
    assert "outside 1-365d" in r.stderr
    assert not (root / "wake.json").exists()


# ---------------- AC-23: blindness is measurable and non-resettable --------

def untrusted_by_policy_marker(root):
    record = wake_record(root)
    record["engine_policy"] = "policy-written-by-another-build"
    put_wake_record(root, record)


def test_tz_trust_blindness_total_is_monotone_across_rearm(tmp_path):
    root = arm_trusted_daily(tmp_path)
    untrusted_by_policy_marker(root)
    ok(root, "wake-observe", now="2026-03-02T00:20:00Z")
    ok(root, "wake-observe", now="2026-03-03T00:20:00Z")
    accumulated = wake_record(root)["untrusted_minutes_total"]
    assert accumulated == pytest.approx(24 * 60)
    assert wake_arm(root, cron="0 0 * * *", tz="UTC",
                    now="2026-03-04T00:00:00Z", verify_window_days=30
                    ).returncode == 0
    after_rearm = wake_record(root)["untrusted_minutes_total"]
    assert after_rearm >= accumulated       # a re-arm never resets it
    # unlike missed_total, which a re-arm does clear
    assert wake_record(root)["missed_total"] == 0


def test_tz_trust_blindness_total_accumulated_by_observe_not_status(tmp_path):
    root = arm_trusted_daily(tmp_path)
    untrusted_by_policy_marker(root)
    ok(root, "wake-observe", now="2026-03-02T00:20:00Z")
    before_bytes = (root / "wake.json").read_bytes()
    ok(root, "wake-status", now="2026-03-03T00:20:00Z")
    ok(root, "wake-status", now="2026-03-04T00:20:00Z")
    assert (root / "wake.json").read_bytes() == before_bytes
    ok(root, "wake-observe", now="2026-03-03T00:20:00Z")
    assert wake_record(root)["untrusted_minutes_total"] > \
        json.loads(before_bytes)["untrusted_minutes_total"]


# ---------------- AC-24 / AC-25: what a CONSUMER reads ----------------
#
# The de-confounded fixture. One monthly occurrence elapses before the window
# closes and it is DELIVERED ON TIME, so the pre-existing miss latch is
# quiescent; the two read instants straddle verified_until and differ in
# nothing else. Every cell is therefore a single-variable contrast against the
# shared null-injection control.

DECONFOUNDED_ARM = "2026-03-01T00:20:00Z"
DECONFOUNDED_DELIVERY = "2026-04-01T00:05:00Z"
IN_WINDOW_READ = "2026-04-01T00:10:00Z"
POST_WINDOW_READ = "2026-04-01T00:21:00Z"
WRONG_DIGEST = "0" * 64


def deconfounded_root(tmp_path):
    root = ledger(tmp_path / "deconfounded")
    assert wake_arm(root, cron="0 0 1 * *", tz="UTC", now=DECONFOUNDED_ARM,
                    verify_window_days=31).returncode == 0
    record = wake_record(root)
    assert record["expected_next_fire"] == "2026-04-01T00:00:00Z"
    assert record["tz_rule_source"]["verified_until"] == "2026-04-01T00:20:00Z"
    delivered = ok(root, *delivered_claim(root),
                   now=DECONFOUNDED_DELIVERY)
    assert delivered["verdict"] == "on_time"
    assert delivered["missed_fires"] == 0
    assert delivered["needs_rearm"] is False
    assert wake_record(root)["expected_next_fire"] == "2026-05-01T00:00:00Z"
    return root


def inject_window_expired(record):
    return record                      # the CLOCK is the variable, not a field


def inject_rule_source_changed(record):
    record["tz_rule_source"]["fingerprint"] = WRONG_DIGEST
    return record


def inject_engine_policy_absent(record):
    record.pop("engine_policy")
    return record


def inject_engine_policy_unknown(record):
    record["engine_policy"] = "policy-written-by-another-build"
    return record


def inject_rule_source_fingerprint_absent(record):
    record["tz_rule_source"].pop("fingerprint")
    return record


def inject_vendor_binary_digest_mismatch(record):
    record["tz_rule_source"]["vendor_binary_digest"] = WRONG_DIGEST
    return record


UNTRUST_CELLS = {
    "window_expired": (inject_window_expired, POST_WINDOW_READ),
    "rule_source_changed": (inject_rule_source_changed, IN_WINDOW_READ),
    "engine_policy_absent": (inject_engine_policy_absent, IN_WINDOW_READ),
    "engine_policy_unknown": (inject_engine_policy_unknown, IN_WINDOW_READ),
    "rule_source_fingerprint_absent": (inject_rule_source_fingerprint_absent,
                                       IN_WINDOW_READ),
    "vendor_binary_digest_mismatch": (inject_vendor_binary_digest_mismatch,
                                      IN_WINDOW_READ),
}


def cell_root(source, tmp_path, name, inject):
    """A private copy of the de-confounded fixture with ONE field injected."""
    target = tmp_path / f"cell-{name}"
    shutil.copytree(source, target)
    put_wake_record(target, inject(wake_record(target)))
    stored = wake_record(target)
    # the pre-existing miss latch is quiescent in every cell, so any
    # needs_rearm observed below is attributable to the trust predicate
    assert stored["needs_rearm"] is False
    assert stored["missed_total"] == 0
    assert stored["last_verdict"] == "on_time"
    return target


def test_tz_trust_consumer_surface_wake_status_untrusted_sets_needs_rearm(tmp_path):
    source = deconfounded_root(tmp_path)
    control = ok(source, "wake-status", now=IN_WINDOW_READ)
    assert control["needs_rearm"] is False          # null-injection control
    for name, (inject, instant) in UNTRUST_CELLS.items():
        root = cell_root(source, tmp_path, name, inject)
        status = ok(root, "wake-status", now=instant)
        assert status["needs_rearm"] is True, name
        assert status["trust_reason"] == name, name   # reason equality
        assert status["stale"] is False, name
        assert status["missed_total"] == 0, name
        assert wake_record(root)["needs_rearm"] is False, name


def test_tz_trust_consumer_surface_wake_observe_untrusted_sets_needs_rearm(tmp_path):
    source = deconfounded_root(tmp_path)
    control_root = tmp_path / "observe-control"
    shutil.copytree(source, control_root)
    assert ok(control_root, "wake-observe", now=IN_WINDOW_READ
              )["needs_rearm"] is False
    for name, (inject, instant) in UNTRUST_CELLS.items():
        root = cell_root(source, tmp_path, f"observe-{name}", inject)
        out = ok(root, "wake-observe", now=instant)
        assert out["missed_fires"] == 0, name
        assert out["needs_rearm"] is True, name
        assert out["trust_reason"] == name, name


def test_tz_trust_consumer_surface_new_key_alone_is_insufficient(tmp_path):
    # Every assertion here is on a field the ticket's health table names, on
    # the PARSED output. A build that carries the reason only in the trust
    # container fails all six cells.
    source = deconfounded_root(tmp_path)
    health_fields = ("armed", "stale", "needs_rearm", "missed_total",
                     "last_verdict")
    for name, (inject, instant) in UNTRUST_CELLS.items():
        root = cell_root(source, tmp_path, f"newkey-{name}", inject)
        status = ok(root, "wake-status", now=instant)
        assert set(health_fields) <= set(status), name
        assert status["needs_rearm"] is True, name
        assert ok(root, "wake-observe", now=instant)["needs_rearm"] is True, name


def test_tz_trust_consumer_surface_untrusted_does_not_inflate_missed_total(tmp_path):
    source = deconfounded_root(tmp_path)
    for name, (inject, instant) in UNTRUST_CELLS.items():
        root = cell_root(source, tmp_path, f"evidence-{name}", inject)
        before = wake_record(root)["missed_total"]
        status = ok(root, "wake-status", now=instant)
        observed = ok(root, "wake-observe", now=instant)
        assert status["missed_total"] == before == 0, name
        assert observed["missed_fires"] == 0, name
        assert wake_record(root)["missed_total"] == before, name
        # stale is not overloaded either: it stays the watermark formula
        assert status["stale"] is False, name


def test_tz_trust_delivering_in_window_wake_status_reads_delivering_row(tmp_path):
    # Read BEFORE any further wake-observe: an in-window observation rewrites
    # last_verdict to "pending" and would fail this row for a reason that has
    # nothing to do with trust.
    root = deconfounded_root(tmp_path)
    status = ok(root, "wake-status", now=IN_WINDOW_READ)
    assert status["armed"] is True
    assert status["stale"] is False
    assert status["needs_rearm"] is False
    assert status["missed_total"] == 0
    assert status["last_verdict"] == "on_time"
    assert status["trust_state"] == "trusted"


def test_tz_trust_delivering_in_window_wake_observe_needs_rearm_false(tmp_path):
    root = deconfounded_root(tmp_path)
    out = ok(root, "wake-observe", now=IN_WINDOW_READ)
    assert out["needs_rearm"] is False
    assert out["missed_fires"] == 0
    assert out["trust_state"] == "trusted"


def test_tz_trust_delivering_ab_pair_clock_is_the_only_variable(tmp_path):
    root = deconfounded_root(tmp_path)
    stored = (root / "wake.json").read_bytes()
    inside = ok(root, "wake-status", now=IN_WINDOW_READ)
    assert (root / "wake.json").read_bytes() == stored
    outside = ok(root, "wake-status", now=POST_WINDOW_READ)
    assert (root / "wake.json").read_bytes() == stored
    assert inside["needs_rearm"] is False
    assert outside["needs_rearm"] is True
    assert inside["trust_state"] == "trusted"
    assert outside["trust_reason"] == "window_expired"
    # everything the health table names except the derived flag is identical,
    # so the difference is attributable to the clock and to nothing else
    for field in ("armed", "missed_total", "last_verdict"):
        assert inside[field] == outside[field], field


# ---------------- AC-10 / AC-16: the doctrine block is the oracle ----------------

CANONICAL_DIRECTIVES = {
    "fall_back_fixed_time_job": "fires-at-both-occurrences",
    "late_delivery": "latches-needs-rearm",
    "occurrence_search_budget_candidates": "527040",
    "manual_wake_observation": "without-delivered",
    "scheduled_arrival_observation": "wake-observe --delivered --channel-id --arming-token",
    "accepted_divergences": "D4,D6",
    "stale_false_alone": "never-health",
    "rule_source_divergent": "refuse-at-arm",
    "rule_source_unverifiable": "arm-untrusted",
    "rule_source_fingerprint_changed": "read-untrusted",
    "verification_window_expired": "read-untrusted",
    "untrusted_discharged_by": "rearm-verification-success",
    "untrusted_reads": "needs-rearm-true-both-surfaces",
}

# published inversion battery: each entry must be REJECTED by the equality
DOCTRINE_INVERSION_BATTERY = [
    {"rule_source_unverifiable": "arm-trusted"},
    {"rule_source_unverifiable": "trusted-rather-than-untrusted"},
    {"rule_source_unverifiable": "keep-trusting"},
    {"rule_source_unverifiable": "fully-trusted"},
    {"rule_source_unverifiable": "log-untrusted-only"},
    {"rule_source_divergent": "refusal-removed"},
    {"rule_source_divergent": "refusal-deleted"},
    {"rule_source_divergent": "arms-normally"},
    {"__drop__": "rule_source_unverifiable"},
]


def parse_doctrine(body):
    directives = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition(":")
        directives[key.strip()] = value.strip()
    return directives


def doctrine_block():
    blocks = re.findall(r"^```wake-doctrine\n(.*?)^```", COMMAND_DOC.read_text(),
                        re.M | re.S)
    assert len(blocks) == 1, f"expected exactly one block, found {len(blocks)}"
    return parse_doctrine(blocks[0])


def test_wake_doctrine_block_parses_to_canonical_directives():
    assert doctrine_block() == CANONICAL_DIRECTIVES
    text = COMMAND_DOC.read_text()
    for pattern in [r"fires\s+ONCE,\s+at\s+the\s+first\s+occurrence",
                    r"400-year", r"146,?097",
                    r"both\s+fail-closed\s+for\s+miss\s+detection"]:
        assert not re.search(pattern, text), pattern


def test_wake_doctrine_block_rejects_published_inversion_battery():
    # exact equality has no span for an inversion to occupy: rebuild the block
    # for each published substitution and assert the check rejects it
    for entry in DOCTRINE_INVERSION_BATTERY:
        candidate = dict(CANONICAL_DIRECTIVES)
        if "__drop__" in entry:
            candidate.pop(entry["__drop__"])
        else:
            candidate.update(entry)
        rendered = "\n".join(f"{k}: {v}" for k, v in candidate.items())
        assert parse_doctrine(rendered) != CANONICAL_DIRECTIVES, entry
    # and the control: the untouched block IS accepted
    rendered = "\n".join(f"{k}: {v}" for k, v in CANONICAL_DIRECTIVES.items())
    assert parse_doctrine(rendered) == CANONICAL_DIRECTIVES


def vendor_validate_cron(expression):
    parser = ("/opt/paseo/node_modules/@getpaseo/protocol/dist/schedule"
              "/cron-expression.js")
    script = (f"import({parser!r}).then(m=>process.stdout.write("
              "JSON.stringify(m.validateCronExpression(process.argv[1]))));")
    proc = subprocess.run([NODE, "-e", script, "--", expression],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def drive_fall_back_fixed_time_job(value, tmp_path):
    both = value == "fires-at-both-occurrences"
    got = engine_sequence(load_engine(), "30 1 * * *", NY,
                          "2026-11-01T04:00:00Z", 2)
    assert (got == ["2026-11-01T05:30:00Z", "2026-11-01T06:30:00Z"]) is both


def drive_late_delivery(value, tmp_path):
    latches = value == "latches-needs-rearm"
    root = arm_daily_utc(tmp_path)
    out = ok(root, *delivered_claim(root),
             now="2026-03-02T11:00:00Z")
    assert (out["verdict"] == "late" and out["needs_rearm"] is True) is latches
    assert wake_record(root)["needs_rearm"] is latches


def drive_occurrence_search_budget_candidates(value, tmp_path):
    from datetime import timedelta
    budget = int(value)
    module = load_engine()
    assert module.VENDOR_OCCURRENCE_BUDGET_CANDIDATES == budget
    inside = vendor_vector("horizon", boundary="last_in_budget_candidate")
    target = as_utc(inside["instant"])
    # end-exclusive: the SAME target is reachable from target - budget minutes
    # and unreachable from one minute earlier
    spec = module.parse_cron(inside["expression"])
    reachable = module.cron_next_fire(spec, target - timedelta(minutes=budget),
                                      inside["timezone"])
    assert as_iso(reachable) == inside["instant"]
    with pytest.raises(SystemExit):
        module.cron_next_fire(spec, target - timedelta(minutes=budget + 1),
                              inside["timezone"])


def drive_manual_wake_observation(value, tmp_path):
    root = arm_daily_utc(tmp_path)
    argv = (["wake-observe"] if value == "without-delivered"
            else delivered_claim(root))
    out = ok(root, *argv, now="2026-03-02T11:00:00Z")
    # a manual observation reconciles without recording a delivery proof
    assert out["verdict"] == "missed"
    assert out["missed_fires"] == 1


def drive_scheduled_arrival_observation(value, tmp_path):
    tokens = value.split()
    assert tokens[0] == "wake-observe"
    root = arm_daily_utc(tmp_path)

    def argv(channel):
        # Drive EXACTLY the directive's own tokens: supply a value only for a
        # flag the directive itself names, never a flag it omits. Handing the
        # ledger an argument the directive does not carry would make the
        # oracle agree with a stale directive instead of detecting it.
        supplied = {"--channel-id": channel, "--arming-token": armed_token(root)}
        return [part for tok in tokens
                for part in ([tok, supplied[tok]] if tok in supplied else [tok])]

    mismatched = run(root, *argv("hb-OTHER"), now="2026-03-02T00:05:00Z")
    assert mismatched.returncode == 2
    assert "does not match" in mismatched.stderr
    matched = ok(root, *argv("hb-1"), now="2026-03-02T00:05:00Z")
    assert matched["verdict"] == "on_time"


def drive_accepted_divergences(value, tmp_path):
    for divergence in value.split(","):
        if divergence == "D4":
            # the vendor ACCEPTS a stepped range; the ledger refuses it. The
            # direction is refusal, never a health claim.
            assert vendor_validate_cron("1-10/3 * * * *") is None
            assert vendor_validate_cron("99 * * * *") == "Invalid cron minute value"
            r = wake_arm(ledger(tmp_path / "d4"), cron="1-10/3 * * * *")
            assert r.returncode == 2
            assert "unsupported cron minute element" in r.stderr
        elif divergence == "D6":
            # the vendor supports a cadence type the ledger exposes no surface
            # for, so such a channel cannot be armed here at all
            assert 'cadence.type === "every"' in Path(VENDOR_CRON_JS).read_text()
            help_text = " ".join(ok(tmp_path, "wake-arm", "--help",
                                    now=None).split())
            assert "--cadence-type" not in help_text
            assert "--cron" in help_text
        else:
            raise AssertionError(f"undriven divergence id {divergence!r}")


def drive_stale_false_alone(value, tmp_path):
    never_health = value == "never-health"
    root = arm_daily_utc(tmp_path)
    ok(root, *delivered_claim(root),
       now="2026-03-02T11:00:00Z")            # late: latches, then re-watermarks
    status = ok(root, "wake-status", now="2026-03-02T11:05:00Z")
    assert (status["stale"] is False
            and status["needs_rearm"] is True
            and status["missed_total"] == 1) is never_health


def drive_rule_source_divergent(value, tmp_path):
    refuse = value == "refuse-at-arm"
    root = ledger(tmp_path / "divergent")
    r = wake_arm(root, cron="0 1 * * *", tz=WINDOW_SCOPED_ZONE,
                 now=DIVERGENT_ARM_NOW, verify_window_days=30)
    assert (r.returncode == 2 and not (root / "wake.json").exists()) is refuse


def drive_rule_source_unverifiable(value, tmp_path):
    untrusted = value == "arm-untrusted"
    root = unconsultable_vendor_root(tmp_path, cron="0 0 * * *", tz="UTC",
                                     now="2026-03-01T00:00:00Z")
    status = ok(root, "wake-status", now="2026-03-01T00:05:00Z")
    assert (status["trust_state"] == "untrusted") is untrusted
    assert (status["needs_rearm"] is True) is untrusted


def drive_rule_source_fingerprint_changed(value, tmp_path):
    untrusted = value == "read-untrusted"
    root = arm_trusted_edmonton(tmp_path)
    env = tzif_fixture(tmp_path, WINDOW_SCOPED_ZONE, "America/New_York")
    status = ok(root, "wake-status", now="2026-09-20T18:00:00Z", env=env)
    assert (status["trust_state"] == "untrusted"
            and status["trust_reason"] == "rule_source_changed") is untrusted


def drive_verification_window_expired(value, tmp_path):
    untrusted = value == "read-untrusted"
    root = arm_trusted_daily(tmp_path)
    status = ok(root, "wake-status", now="2026-04-01T00:00:00Z")
    assert (status["trust_state"] == "untrusted"
            and status["trust_reason"] == "window_expired") is untrusted


def drive_untrusted_discharged_by(value, tmp_path):
    only_verification = value == "rearm-verification-success"
    root = arm_trusted_daily(tmp_path)
    set_config(root, wake_vendor_node_path=str(tmp_path / "no-such-runtime"))
    assert wake_arm(root, cron="0 0 * * *", tz="UTC",
                    now="2026-03-02T00:00:00Z").returncode == 0
    bare = ok(root, "wake-status", now="2026-03-02T00:01:00Z")
    set_config(root, wake_vendor_node_path=NODE)
    assert wake_arm(root, cron="0 0 * * *", tz="UTC",
                    now="2026-03-03T00:00:00Z").returncode == 0
    verified = ok(root, "wake-status", now="2026-03-03T00:01:00Z")
    assert (bare["trust_state"] == "untrusted"
            and verified["trust_state"] == "trusted") is only_verification


def drive_untrusted_reads(value, tmp_path):
    both = value == "needs-rearm-true-both-surfaces"
    source = deconfounded_root(tmp_path)
    root = cell_root(source, tmp_path, "doctrine", inject_engine_policy_unknown)
    status = ok(root, "wake-status", now=IN_WINDOW_READ)
    observed = ok(root, "wake-observe", now=IN_WINDOW_READ)
    assert (status["needs_rearm"] is True
            and observed["needs_rearm"] is True) is both


DOCTRINE_DRIVERS = {
    "fall_back_fixed_time_job": drive_fall_back_fixed_time_job,
    "late_delivery": drive_late_delivery,
    "occurrence_search_budget_candidates": drive_occurrence_search_budget_candidates,
    "manual_wake_observation": drive_manual_wake_observation,
    "scheduled_arrival_observation": drive_scheduled_arrival_observation,
    "accepted_divergences": drive_accepted_divergences,
    "stale_false_alone": drive_stale_false_alone,
    "rule_source_divergent": drive_rule_source_divergent,
    "rule_source_unverifiable": drive_rule_source_unverifiable,
    "rule_source_fingerprint_changed": drive_rule_source_fingerprint_changed,
    "verification_window_expired": drive_verification_window_expired,
    "untrusted_discharged_by": drive_untrusted_discharged_by,
    "untrusted_reads": drive_untrusted_reads,
}


@pytest.mark.parametrize("directive", sorted(CANONICAL_DIRECTIVES))
def test_wake_doctrine_directive_driven(directive, tmp_path):
    """The document is the ORACLE, not a word list: each node reads its own
    directive's value out of the shipped block and drives the ledger against
    what that value says. Substituting an inverted value makes the behavioural
    assertion fail, so a doctrine-inverting block cannot pass."""
    assert set(DOCTRINE_DRIVERS) == set(CANONICAL_DIRECTIVES)
    value = doctrine_block()[directive]
    DOCTRINE_DRIVERS[directive](value, tmp_path)
