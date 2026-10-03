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
