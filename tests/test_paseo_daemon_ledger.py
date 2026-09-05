"""BUILD-AC05 + BUILD-AC06 facade — ledger local-persistence invariants.

MANDATORY pytest facade for lane 20260828-112025-b: collects EVERY test
binding a BUILD-AC05 or BUILD-AC06 invariant of scripts/paseo-daemon-ledger.py
(docs/dev/acceptance-criteria-20260828-112025-b.json). All tests run against
TEMPORARY ledger roots (tmp_path) with a fake clock (--now) and crash
injection (--inject-crash) — never the live .claude/paseo-daemon/, and never
by invoking /dev, /close, /commit, or human-only /restart (fixtures only).
"""

import io
import json
import subprocess
import sys
import tokenize
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEDGER = REPO / "scripts" / "paseo-daemon-ledger.py"
SCHEMA = REPO / "schemas" / "paseo-dossier.v1.json"

T0 = "2026-08-28T12:00:00Z"
SHA_A, SHA_B, SHA_C, SHA_D = "a" * 64, "b" * 64, "c" * 64, "d" * 64


def run(root, *args, now=T0, stdin=None):
    cmd = [sys.executable, str(LEDGER), "--root", str(root)]
    if now is not None:
        cmd += ["--now", now]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True, input=stdin, cwd=REPO)


def ok(root, *args, **kw):
    r = run(root, *args, **kw)
    assert r.returncode == 0, f"{args}: rc={r.returncode} stderr={r.stderr}"
    return json.loads(r.stdout) if r.stdout.strip().startswith(("{", "[")) else r.stdout


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
