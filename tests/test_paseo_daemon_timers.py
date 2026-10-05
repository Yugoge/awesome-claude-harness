"""tests/test_paseo_daemon_timers.py — pytest suite for
scripts/paseo-daemon-timers.py (task 20260926-111239).

Subprocess-driven against the real, unmodified CLI, mirroring
tests/test_paseo_daemon_ledger.py's run()/ok() conventions. Every
--registry-dir and --ledger-root used here is a pytest tmp_path fixture --
this suite MUST NEVER reference the real on-disk schedule registry path or
the real ledger path (AC10 -- see
test_ac10_suite_never_references_real_registry_path below, which asserts
this file's own source contains no such literal).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TIMERS = REPO / "scripts" / "paseo-daemon-timers.py"
LEDGER = REPO / "scripts" / "paseo-daemon-ledger.py"
COMMAND_DOC = REPO / "commands" / "paseo-daemon.md"

T0 = "2026-09-26T11:12:39Z"
CONTROLLER_AGENT_ID = "5805a4d1-d832-4cae-aa5a-e4bc9015d96b"
FOUR_KEYS = ("tick", "reinject", "watchdog", "sweep")
NAME_TO_KEY = {
    "paseo-daemon-tick": "tick",
    "ctrl-core-reinject": "reinject",
    "paseo-daemon-watchdog": "watchdog",
    "reader-board-sweep": "sweep",
}
KEY_TO_CRON = {
    "tick": "12,57 * * * *",
    "reinject": "41 */4 * * *",
    "watchdog": "23,53 * * * *",
    "sweep": "37 */4 * * *",
}


def run(registry_dir, *args, now=T0):
    cmd = [sys.executable, str(TIMERS), "--registry-dir", str(registry_dir)]
    if now is not None:
        cmd += ["--now", now]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)


def ok(registry_dir, *args, **kw):
    r = run(registry_dir, *args, **kw)
    assert r.returncode == 0, f"{args}: rc={r.returncode} stderr={r.stderr}"
    # drain prints one JSON line per paused timer plus a final summary line;
    # ensure/status print a single JSON object. The final line is always the
    # summary in every subcommand.
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    last = lines[-1] if lines else ""
    return json.loads(last) if last.startswith("{") else r.stdout


def ledger_init(tmp_path, accounts="orchestrade,yugetang,yugoge"):
    root = tmp_path / "ledger"
    r = subprocess.run(
        [sys.executable, str(LEDGER), "--root", str(root), "--now", T0,
         "init", "--accounts", accounts],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    return root


def make_prompts_dir(tmp_path, keys=FOUR_KEYS, name="prompts"):
    """Distinguishable, non-empty per-key fixture content (ticket Edge Cases:
    fixtures must not be empty/identical so a byte-equality assertion
    actually exercises real content propagation, not a vacuous pass)."""
    d = tmp_path / name
    d.mkdir()
    for key in keys:
        d.joinpath(f"{key}.prompt.txt").write_text(
            f"SYNTHETIC FIXTURE PROMPT for {key} -- distinguishable, not the real prompt\n")
    return d


def registry_snapshot(registry_dir):
    if not registry_dir.exists():
        return {}
    return {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in registry_dir.glob("*.json")}


def by_name(registry_dir):
    out = {}
    for p in registry_dir.glob("*.json"):
        obj = json.loads(p.read_text())
        out[obj["name"]] = (p, obj)
    return out


def write_registration(registry_dir, timer_id, name, cron, target, status="active", prompt=None,
                        paused_at=None):
    registry_dir.mkdir(parents=True, exist_ok=True)
    obj = {
        "id": timer_id, "name": name, "prompt": prompt or f"real prompt for {name}",
        "cadence": {"type": "cron", "expression": cron, "timezone": "UTC"},
        "target": target, "status": status,
        "createdAt": "2026-09-01T00:00:00Z", "updatedAt": "2026-09-01T00:00:00Z",
        "nextRunAt": "2026-09-26T20:41:00Z", "lastRunAt": "2026-09-26T16:41:01Z",
        "pausedAt": paused_at, "expiresAt": None, "maxRuns": None, "runs": [],
    }
    path = registry_dir / f"{timer_id}.json"
    path.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")
    return path


def seed_all_four(registry_dir, tick_name="paseo-daemon-tick hbtick-20260902T1158Z-c7d1"):
    """Seeds the registry with all four live-shaped registrations, using the
    REAL suffixed tick name (M2/R-DECIDE-1) -- not the clean canonical one."""
    write_registration(registry_dir, "9a4501fd", tick_name, KEY_TO_CRON["tick"],
                        {"type": "agent", "agentId": CONTROLLER_AGENT_ID})
    write_registration(registry_dir, "5d7152bb", "ctrl-core-reinject", KEY_TO_CRON["reinject"],
                        {"type": "agent", "agentId": CONTROLLER_AGENT_ID})
    write_registration(registry_dir, "a814a9a0", "paseo-daemon-watchdog", KEY_TO_CRON["watchdog"],
                        {"type": "new-agent", "config": {"provider": "claude"}})
    write_registration(registry_dir, "754bb5da", "reader-board-sweep", KEY_TO_CRON["sweep"],
                        {"type": "agent", "agentId": CONTROLLER_AGENT_ID})


# ---------------- AC1: ensure -- empty directory creates all four ----------------

def test_ac1_ensure_empty_directory_creates_all_four_with_fixture_prompts(tmp_path):
    registry = tmp_path / "registry"
    prompts = make_prompts_dir(tmp_path)

    ok(registry, "ensure", "--controller-agent-id", CONTROLLER_AGENT_ID,
       "--prompts-dir", str(prompts))

    files = list(registry.glob("*.json"))
    assert len(files) == 4
    found = by_name(registry)
    assert set(found) == set(NAME_TO_KEY)
    for name, (_, obj) in found.items():
        key = NAME_TO_KEY[name]
        assert obj["cadence"]["expression"] == KEY_TO_CRON[key]
        fixture = (prompts / f"{key}.prompt.txt").read_text().rstrip("\n")
        assert obj["prompt"] == fixture


# ---------------- AC2: ensure -- full directory is a no-op, suffixed tick ----------------

def test_ac2_ensure_full_directory_is_noop_with_suffixed_tick_name(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    before = registry_snapshot(registry)

    # Deliberately no --prompts-dir: nothing needs creation, so the M11
    # create-time prompt-sourcing branch must never be entered (round-2
    # correction: a spurious fail-closed here would ALSO be zero-write, so
    # exit_code == 0 is what distinguishes a true no-op).
    r = run(registry, "ensure")
    after = registry_snapshot(registry)

    assert r.returncode == 0, r.stderr
    assert before == after
    assert len(after) == 4


# ---------------- AC3: ensure -- exactly one missing timer ----------------

def test_ac3_ensure_creates_exactly_one_missing_timer(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    prompts = make_prompts_dir(tmp_path, keys=("sweep",))

    sweep_path, _ = by_name(registry)["reader-board-sweep"]
    os.remove(sweep_path)
    other_before = {name: obj for name, (_, obj) in by_name(registry).items()}
    assert len(other_before) == 3

    ok(registry, "ensure", "--controller-agent-id", CONTROLLER_AGENT_ID,
       "--prompts-dir", str(prompts))

    files = list(registry.glob("*.json"))
    assert len(files) == 4
    after = by_name(registry)
    for name, obj in other_before.items():
        _, after_obj = after[name]
        assert after_obj == obj, f"{name} was mutated by ensure"

    new_obj = after["reader-board-sweep"][1]
    fixture = (prompts / "sweep.prompt.txt").read_text().rstrip("\n")
    assert new_obj["prompt"] == fixture


# ---------------- AC4: drain -- watchdog-first ordering ----------------

def test_ac4_drain_stops_watchdog_before_sweep_tick_reinject(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    ledger_root = ledger_init(tmp_path)

    r = run(registry, "drain", "--ledger-root", str(ledger_root))
    assert r.returncode == 0, r.stderr

    call_order = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("op") == "pause":
            call_order.append(rec["key"])

    assert call_order[0] == "watchdog"
    assert call_order[1:] == ["sweep", "tick", "reinject"]


# ---------------- AC5: status after drain reports all stopped ----------------

def test_ac5_status_after_drain_reports_all_four_paused(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    ledger_root = ledger_init(tmp_path)
    ok(registry, "drain", "--ledger-root", str(ledger_root))

    status = ok(registry, "status")
    for key in FOUR_KEYS:
        entry = status["timers"][key]
        assert entry["status"] == "paused"
        # a paused timer is always a deviation, never []
        assert entry["deviations"] == ["paused"]


# ---------------- AC6: fail closed on corrupt JSON ----------------

@pytest.mark.parametrize("subcmd", ["ensure", "status"])
def test_ac6_fail_closed_on_corrupt_json(tmp_path, subcmd):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    corrupt = registry / "deadbeef.json"
    corrupt.write_text("{not valid json")
    before = registry_snapshot(registry)

    extra = ["--controller-agent-id", "x"] if subcmd == "ensure" else []
    r = run(registry, subcmd, *extra)
    after = registry_snapshot(registry)

    assert r.returncode != 0
    assert "deadbeef.json" in r.stderr
    assert before == after


# ---------------- AC7: status is read-only ----------------

def test_ac7_status_never_mutates_registry_dir(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    before = registry_snapshot(registry)

    r = run(registry, "status")

    after = registry_snapshot(registry)
    assert r.returncode == 0
    assert before == after


# ---------------- AC8: teardown-declare called exactly once ----------------

def test_ac8_drain_calls_teardown_declare_exactly_once(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    ledger_root = ledger_init(tmp_path)

    ok(registry, "drain", "--ledger-root", str(ledger_root))

    journal_lines = (ledger_root / "journal.ndjson").read_text().splitlines()
    teardown_records = [json.loads(line) for line in journal_lines
                        if json.loads(line).get("op") == "teardown-declare"]
    assert len(teardown_records) == 1
    assert teardown_records[0]["reason"]


# ---------------- AC9: command doc wiring ----------------

def test_ac9_command_doc_names_ensure_in_bootstrap_and_drain_in_new_section():
    text = COMMAND_DOC.read_text()
    bootstrap_start = text.index("## Bootstrap (F6)")
    bootstrap_end = text.index("\n## ", bootstrap_start + 1)
    bootstrap_section = text[bootstrap_start:bootstrap_end]

    assert "paseo-daemon-timers.py ensure" in bootstrap_section
    assert "paseo-daemon-timers.py drain" in text


# ---------------- AC10: this suite never touches the real registry ----------------

def test_ac10_suite_never_references_real_registry_path():
    source = Path(__file__).read_text()
    real_registry_path = "/" + "root/.paseo/schedules"
    assert real_registry_path not in source


# ---------------- AC11: ensure fails closed when prompt source unavailable ----------------

def test_ac11_ensure_fails_closed_when_prompts_dir_incomplete(tmp_path):
    registry = tmp_path / "registry"
    # Only 2 of 4 fixtures provided -- the other 2 keys must be named in the
    # error, and zero files must be written (all-or-nothing, M11).
    prompts = make_prompts_dir(tmp_path, keys=("tick", "watchdog"))

    r = run(registry, "ensure", "--controller-agent-id", CONTROLLER_AGENT_ID,
            "--prompts-dir", str(prompts))

    assert r.returncode != 0
    assert "reinject" in r.stderr
    assert "sweep" in r.stderr
    assert registry_snapshot(registry) == {}


def test_ac11_ensure_fails_closed_when_prompts_dir_entirely_absent(tmp_path):
    registry = tmp_path / "registry"

    r = run(registry, "ensure", "--controller-agent-id", CONTROLLER_AGENT_ID)

    assert r.returncode != 0
    for key in FOUR_KEYS:
        assert key in r.stderr
    assert registry_snapshot(registry) == {}


# ---------------- paused-timer detection (idempotency-gap fix, task 20260926-111239 followup) ----------------

def test_status_flags_paused_timer_as_deviation(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    write_registration(registry, "754bb5da", "reader-board-sweep", KEY_TO_CRON["sweep"],
                        {"type": "agent", "agentId": CONTROLLER_AGENT_ID},
                        status="paused", paused_at="2026-09-28T02:36:43Z")

    status = ok(registry, "status")
    entry = status["timers"]["sweep"]
    assert entry["status"] == "paused"
    assert entry["deviations"] == ["paused"]


def test_ensure_reports_deviation_for_paused_existing_timer_with_id_and_pausedAt(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    sweep_path, sweep_obj = by_name(registry)["reader-board-sweep"]
    paused_at = "2026-09-28T02:36:43Z"
    write_registration(registry, sweep_path.stem, "reader-board-sweep", KEY_TO_CRON["sweep"],
                        sweep_obj["target"], status="paused", paused_at=paused_at)
    before = registry_snapshot(registry)

    result = ok(registry, "ensure")

    after = registry_snapshot(registry)
    assert before == after, "ensure must never mutate an existing (even paused) registration"
    assert result["created"] == []
    deviations = {d["key"]: d for d in result["deviations"]}
    assert set(deviations) == {"sweep"}
    dev = deviations["sweep"]
    assert dev["id"] == sweep_path.stem
    assert dev["status"] == "paused"
    assert dev["pausedAt"] == paused_at
    assert "resume" in dev["recovery_command"]
    assert str(registry) in dev["recovery_command"]


def test_ensure_reports_paused_deviation_while_also_creating_a_missing_timer(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    tick_path, _ = by_name(registry)["paseo-daemon-tick hbtick-20260902T1158Z-c7d1"]
    os.remove(tick_path)
    sweep_path, sweep_obj = by_name(registry)["reader-board-sweep"]
    write_registration(registry, sweep_path.stem, "reader-board-sweep", KEY_TO_CRON["sweep"],
                        sweep_obj["target"], status="paused", paused_at="2026-09-28T02:36:43Z")
    prompts = make_prompts_dir(tmp_path, keys=("tick",))

    result = ok(registry, "ensure", "--controller-agent-id", CONTROLLER_AGENT_ID,
                "--prompts-dir", str(prompts))

    assert [c["key"] for c in result["created"]] == ["tick"]
    assert [d["key"] for d in result["deviations"]] == ["sweep"]


def test_ac2_style_ensure_noop_still_reports_empty_deviations_when_all_active(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)

    result = ok(registry, "ensure")

    assert result["created"] == []
    assert result["deviations"] == []


# ---------------- resume (paired with drain, idempotency-gap fix) ----------------

def test_resume_restores_all_paused_timers_in_reverse_drain_order(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    ledger_root = ledger_init(tmp_path)
    ok(registry, "drain", "--ledger-root", str(ledger_root))

    r = run(registry, "resume")
    assert r.returncode == 0, r.stderr

    call_order = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("op") == "resume":
            call_order.append(rec["key"])

    # exact reverse of DRAIN_ORDER (watchdog last)
    assert call_order == ["reinject", "tick", "sweep", "watchdog"]

    status = ok(registry, "status")
    for key in FOUR_KEYS:
        entry = status["timers"][key]
        assert entry["status"] == "active"
        assert entry["deviations"] == []


def test_resume_is_idempotent_on_already_active_entries(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)  # all active, nothing paused
    before = registry_snapshot(registry)

    result = ok(registry, "resume")

    after = registry_snapshot(registry)
    assert result["resumed"] == []
    assert before == after


def test_resume_running_twice_after_drain_is_idempotent_on_second_run(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    ledger_root = ledger_init(tmp_path)
    ok(registry, "drain", "--ledger-root", str(ledger_root))

    first = ok(registry, "resume")
    assert set(first["resumed"]) == set(FOUR_KEYS)
    before = registry_snapshot(registry)

    second = ok(registry, "resume")

    after = registry_snapshot(registry)
    assert second["resumed"] == []
    assert before == after


def test_resume_only_touches_the_four_inventory_timers(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    ledger_root = ledger_init(tmp_path)
    ok(registry, "drain", "--ledger-root", str(ledger_root))
    stray = registry / "not-an-inventory-timer.json"
    stray.write_text(json.dumps({"id": "stray", "name": "unrelated-schedule",
                                 "status": "paused"}) + "\n")
    before_stray = stray.read_bytes()

    ok(registry, "resume")

    assert stray.read_bytes() == before_stray


def test_resume_clears_pausedAt_back_to_none(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    ledger_root = ledger_init(tmp_path)
    ok(registry, "drain", "--ledger-root", str(ledger_root))

    ok(registry, "resume")

    for name, (_, obj) in by_name(registry).items():
        assert obj["status"] == "active"
        assert obj["pausedAt"] is None


def test_resume_output_line_includes_name_field(tmp_path):
    # Additive field (task 20261004-050913): watchdog-check's self-heal
    # branch derives the tick channel's wake-arm channel id from this name
    # suffix without a second read. Existing tests only assert on `key`, so
    # this is purely additive.
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    ledger_root = ledger_init(tmp_path)
    ok(registry, "drain", "--ledger-root", str(ledger_root))

    r = run(registry, "resume")
    lines = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
    resume_lines = {l["key"]: l for l in lines if l.get("op") == "resume"}
    assert resume_lines["tick"]["name"] == "paseo-daemon-tick hbtick-20260902T1158Z-c7d1"
    assert resume_lines["reinject"]["name"] == "ctrl-core-reinject"


# ---------------- resume --target + channel_id collision guard (task 20261004-085212) ----------------

def test_resume_target_restores_only_the_requested_key(tmp_path):
    # The real motivating scenario: the unrelated, days-paused watchdog (the
    # only safety net) must be recoverable on its own, without a bare
    # `resume` touching tick at all.
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    ledger_root = ledger_init(tmp_path)
    ok(registry, "drain", "--ledger-root", str(ledger_root))

    result = ok(registry, "resume", "--target", "watchdog")

    assert result["resumed"] == ["watchdog"]
    status = ok(registry, "status")
    assert status["timers"]["watchdog"]["status"] == "active"
    for key in ("tick", "reinject", "sweep"):
        assert status["timers"][key]["status"] == "paused"


def test_resume_target_repeatable_for_multiple_keys(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    ledger_root = ledger_init(tmp_path)
    ok(registry, "drain", "--ledger-root", str(ledger_root))

    result = ok(registry, "resume", "--target", "watchdog", "--target", "sweep")

    assert set(result["resumed"]) == {"watchdog", "sweep"}
    status = ok(registry, "status")
    assert status["timers"]["tick"]["status"] == "paused"
    assert status["timers"]["reinject"]["status"] == "paused"


def test_resume_refuses_channel_id_collision_with_already_active_duplicate(tmp_path):
    # Reproduces the actual incident: a stale PAUSED registration sharing
    # the live (active) tick channel's exact `name` -- and therefore
    # channel_id, which is embedded in `name` -- sits in the registry under
    # a second file/timer id. A bare resume must refuse to also activate
    # the duplicate rather than silently creating two live schedules under
    # one channel_id.
    # Filenames deliberately chosen so scan_registry's sorted-glob order (and
    # therefore find_match/by_key's first-match-wins pick for "tick") lands
    # on the PAUSED duplicate, not the active one -- this is the exact
    # unsafe ordering a bare resume would otherwise act on.
    registry = tmp_path / "registry"
    registry.mkdir()
    tick_name = "paseo-daemon-tick hbtick-20260902T1158Z-c7d1"
    write_registration(registry, "0000beef", tick_name, KEY_TO_CRON["tick"],
                        {"type": "agent", "agentId": CONTROLLER_AGENT_ID}, status="paused",
                        paused_at="2026-09-20T00:00:00Z")
    write_registration(registry, "9a4501fd", tick_name, KEY_TO_CRON["tick"],
                        {"type": "agent", "agentId": CONTROLLER_AGENT_ID}, status="active")
    before = registry_snapshot(registry)

    r = run(registry, "resume", "--target", "tick")

    assert r.returncode == 2
    lines = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
    refused = [l for l in lines if l.get("op") == "resume-refused"]
    assert len(refused) == 1
    assert refused[0]["key"] == "tick"
    assert refused[0]["reason"] == "channel_id_collision"
    assert "9a4501fd" in refused[0]["conflicting_ids"]
    assert registry_snapshot(registry) == before  # the paused duplicate is left untouched


def test_resume_target_sidesteps_an_unrelated_keys_collision(tmp_path):
    # The real fix: an operator who wants ONLY the unrelated watchdog back
    # can get it even while the tick duplicate sits unresolved, because
    # --target never even considers "tick".
    registry = tmp_path / "registry"
    registry.mkdir()
    tick_name = "paseo-daemon-tick hbtick-20260902T1158Z-c7d1"
    write_registration(registry, "9a4501fd", tick_name, KEY_TO_CRON["tick"],
                        {"type": "agent", "agentId": CONTROLLER_AGENT_ID}, status="active")
    write_registration(registry, "deadbeef", tick_name, KEY_TO_CRON["tick"],
                        {"type": "agent", "agentId": CONTROLLER_AGENT_ID}, status="paused",
                        paused_at="2026-09-20T00:00:00Z")
    write_registration(registry, "a814a9a0", "paseo-daemon-watchdog", KEY_TO_CRON["watchdog"],
                        {"type": "new-agent", "config": {"provider": "claude"}}, status="paused",
                        paused_at="2026-09-20T00:00:00Z")

    result = ok(registry, "resume", "--target", "watchdog")

    assert result["resumed"] == ["watchdog"]
    assert result["refused"] == []
    status = ok(registry, "status")
    assert status["timers"]["watchdog"]["status"] == "active"


# ---------------- ensure --ledger-root auto-recovery (task 20261004-050913) ----------------
# Incident: four timers sat paused for 6 days after a daemon restart
# because bootstrap's `ensure` only ever REPORTED the paused deviation --
# nobody ran `resume`. `--ledger-root` closes the gap: authorized ONLY by
# the ledger's latest teardown-declare (for_restart=true, keep_down not
# true), never by the mere presence of a paused timer alone.

def ledger_teardown_declare(ledger_root, *, reason="operator-ordered restart",
                            for_restart=False, keep_down=False, now=T0):
    cmd = [sys.executable, str(LEDGER), "--root", str(ledger_root), "--now", now,
           "teardown-declare", "--reason", reason]
    if for_restart:
        cmd.append("--for-restart")
    if keep_down:
        cmd.append("--keep-down")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_drain_forwards_for_restart_and_keep_down_to_teardown_declare(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    ledger_root = ledger_init(tmp_path)

    ok(registry, "drain", "--ledger-root", str(ledger_root),
       "--reason", "operator-ordered restart", "--for-restart", "--keep-down")

    r = subprocess.run([sys.executable, str(LEDGER), "--root", str(ledger_root),
                        "teardown-status"], capture_output=True, text=True, cwd=REPO)
    status = json.loads(r.stdout)
    assert status["for_restart"] is True
    assert status["keep_down"] is True


def test_ensure_without_ledger_root_never_auto_recovers_even_when_restart_declared(tmp_path):
    # Regression pin: omitting --ledger-root reproduces the pre-20261004
    # behavior EXACTLY, even if a qualifying restart teardown exists.
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    ledger_root = ledger_init(tmp_path)
    ok(registry, "drain", "--ledger-root", str(ledger_root), "--for-restart")
    before = registry_snapshot(registry)

    result = ok(registry, "ensure")

    after = registry_snapshot(registry)
    assert before == after
    assert {d["key"] for d in result["deviations"]} == set(FOUR_KEYS)
    assert result["auto_recovery"] == {"eligible": False, "reason": "ledger_root_not_provided",
                                       "resumed": [], "wake_armed": None}


def test_ensure_auto_recovery_ineligible_when_no_teardown_declared(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    ledger_root = ledger_init(tmp_path)
    ok(registry, "drain", "--ledger-root", str(ledger_root))  # no --for-restart

    result = ok(registry, "ensure", "--ledger-root", str(ledger_root))

    assert result["auto_recovery"]["eligible"] is False
    assert result["auto_recovery"]["reason"] == "last_teardown_not_for_restart"
    assert {d["key"] for d in result["deviations"]} == set(FOUR_KEYS)


def test_ensure_auto_recovery_ineligible_when_keep_down_declared(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    ledger_root = ledger_init(tmp_path)
    ok(registry, "drain", "--ledger-root", str(ledger_root), "--for-restart", "--keep-down")

    result = ok(registry, "ensure", "--ledger-root", str(ledger_root))

    assert result["auto_recovery"]["eligible"] is False
    assert result["auto_recovery"]["reason"] == "keep_down_declared"
    assert {d["key"] for d in result["deviations"]} == set(FOUR_KEYS)
    status = ok(registry, "status")
    for key in FOUR_KEYS:
        assert status["timers"][key]["status"] == "paused"


def test_ensure_auto_recovery_ineligible_when_ledger_root_uninitialized(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    sweep_path, sweep_obj = by_name(registry)["reader-board-sweep"]
    write_registration(registry, sweep_path.stem, "reader-board-sweep", KEY_TO_CRON["sweep"],
                        sweep_obj["target"], status="paused", paused_at="2026-09-28T02:36:43Z")
    never_initialized = tmp_path / "ledger-never-initialized"

    result = ok(registry, "ensure", "--ledger-root", str(never_initialized))

    assert result["auto_recovery"] == {"eligible": False, "reason": "no_teardown_declared",
                                       "resumed": [], "wake_armed": None}
    assert result["deviations"][0]["key"] == "sweep"


def test_ensure_auto_recovery_full_incident_reproduction_resumes_all_and_rearms_tick(tmp_path):
    # The exact accident chain from the task: drain --for-restart, then
    # (days later, after a daemon restart) a bootstrap `ensure --ledger-root`
    # call alone -- zero human commands -- brings all four back to active
    # AND re-arms the tick wake channel.
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    ledger_root = ledger_init(tmp_path)
    ok(registry, "drain", "--ledger-root", str(ledger_root),
       "--reason", "operator-ordered restart", "--for-restart", now="2026-09-28T02:05:00Z")

    status_after_drain = ok(registry, "status", now="2026-09-28T02:05:00Z")
    for key in FOUR_KEYS:
        assert status_after_drain["timers"][key]["status"] == "paused"

    result = ok(registry, "ensure", "--ledger-root", str(ledger_root),
                now="2026-10-04T05:04:00Z")  # 6 days later, daemon restarted

    assert result["deviations"] == []
    assert result["auto_recovery"]["eligible"] is True
    assert {item["key"] for item in result["auto_recovery"]["resumed"]} == set(FOUR_KEYS)
    assert result["auto_recovery"]["wake_armed"]["ok"] is True
    assert result["auto_recovery"]["wake_armed"]["channel_id"] == "hbtick-20260902T1158Z-c7d1"

    status_after_ensure = ok(registry, "status", now="2026-10-04T05:04:00Z")
    for key in FOUR_KEYS:
        assert status_after_ensure["timers"][key]["status"] == "active"
        assert status_after_ensure["timers"][key]["deviations"] == []


def test_ensure_auto_recovery_rearm_uses_disk_read_token_delivery(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    ledger_root = ledger_init(tmp_path)
    ok(registry, "drain", "--ledger-root", str(ledger_root), "--for-restart")

    ok(registry, "ensure", "--ledger-root", str(ledger_root))

    wake = json.loads((ledger_root / "wake.json").read_text())
    assert wake["token_delivery"] == "disk-read"


def test_ensure_auto_recovery_skips_rearm_when_tick_was_not_paused(tmp_path):
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    ledger_root = ledger_init(tmp_path)
    # Pause only reinject directly (bypassing drain, which pauses all four)
    reinject_path, reinject_obj = by_name(registry)["ctrl-core-reinject"]
    write_registration(registry, reinject_path.stem, "ctrl-core-reinject", KEY_TO_CRON["reinject"],
                        reinject_obj["target"], status="paused", paused_at=T0)
    ledger_teardown_declare(ledger_root, for_restart=True)

    result = ok(registry, "ensure", "--ledger-root", str(ledger_root))

    assert [item["key"] for item in result["auto_recovery"]["resumed"]] == ["reinject"]
    assert result["auto_recovery"]["wake_armed"] is None
    assert not (ledger_root / "wake.json").exists()


def test_ensure_auto_recovery_deliberate_maintenance_pause_still_never_reverted(tmp_path):
    # The ORIGINAL guarantee (task 20260926-111239) must survive: a paused
    # timer with no for_restart-flagged teardown is STILL just a reported
    # deviation, never auto-resumed, even with --ledger-root given.
    registry = tmp_path / "registry"
    registry.mkdir()
    seed_all_four(registry)
    sweep_path, sweep_obj = by_name(registry)["reader-board-sweep"]
    write_registration(registry, sweep_path.stem, "reader-board-sweep", KEY_TO_CRON["sweep"],
                        sweep_obj["target"], status="paused", paused_at="2026-09-28T02:36:43Z")
    ledger_root = ledger_init(tmp_path)
    ledger_teardown_declare(ledger_root, reason="manual maintenance pause, duration unknown")
    before = registry_snapshot(registry)

    result = ok(registry, "ensure", "--ledger-root", str(ledger_root))

    after = registry_snapshot(registry)
    assert before == after
    assert result["deviations"][0]["key"] == "sweep"
    assert result["auto_recovery"]["eligible"] is False
