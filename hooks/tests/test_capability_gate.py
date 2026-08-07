#!/usr/bin/env python3
"""Behavioural tests for the host-capability gate (lane 20260719-163852-a).

Every test drives the real artefacts: the library, the PreToolUse gate hook as a
subprocess over a synthetic envelope, the handshake orchestrator, and
`doctor --strict`. Nothing here asserts on a mock of the thing under test.

Two disciplines are load-bearing and deliberately explicit:

  * NO MUTATION OF THE LIVE SECURITY BOUNDARY. The settings-render test copies
    the template and the rendered file into an isolated config root and drives
    `render-settings` with explicit --template/--out targets. A postcondition
    asserts the real settings.json, settings.template.json and the effective
    permission sets are byte-for-byte unchanged. Mutate-and-restore against the
    live boundary is forbidden, not merely discouraged.
  * THE INDEPENDENCE MATRIX VARIES GATE EFFICACY, NOT ONLY GATE REGISTRATION.
    A matrix that only ever adds/removes the settings entry never visits the real
    threat host -- one whose settings list the gate while the host never
    dispatches it. `inert` is that cell: the canonical registration is preserved
    VERBATIM and dispatch is suppressed by a means independent of settings
    content (the host simply does not run it), and the consumer must still
    enforce independently at BOTH state values.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "hooks" / "lib"))
import capability_state as cs  # noqa: E402

GATE = REPO / "hooks" / "pretool-capability-gate.py"
HANDSHAKE = REPO / "scripts" / "capability-handshake.py"
DOCTOR = REPO / "scripts" / "doctor"
MANIFEST_SRC = REPO / "policies" / cs.MANIFEST_RELPATH.split("/")[-1]

# The canonical production registration, byte-identical in the REGISTERED and
# INERT fixtures so "registered" can never be distinguished by content.
CANONICAL_GATE_ENTRY = {
    "type": "command",
    "command": 'python3 "$HOME/.claude/hooks/pretool-capability-gate.py"',
}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, sort_keys=True), encoding="utf-8")


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    """An isolated harness home. The live tree is never written to."""
    h = tmp_path / "home"
    (h / "policies").mkdir(parents=True)
    (h / ".claude").mkdir()
    _write(h / "settings.json", {"hooks": {"PreToolUse": []}})
    _write(h / "settings.local.json", {"permissions": {"allow": []}})
    _write(h / ".claude" / "settings.local.json", {"env": {}})
    (h / "VERSION").write_text("9.9.9-test\n", encoding="utf-8")
    # Every artefact the canonical binding covers must exist in the isolated home,
    # because a missing enforcement artefact is (correctly) non-passing.
    for rel in cs.BOUND_ARTIFACTS:
        dst = h / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, dst)
    return h


@pytest.fixture()
def statedir(tmp_path: Path) -> Path:
    d = tmp_path / "run"
    d.mkdir(mode=0o700)
    return d


def _settings_fixture(home: Path, registration: str) -> None:
    """registration in {'registered', 'removed', 'inert'}.

    'registered' and 'inert' are BYTE-IDENTICAL: the difference between them is
    whether the host dispatches the gate, which is a property of the host, not of
    settings content. That is exactly the threat host the matrix must visit.
    """
    entries = [] if registration == "removed" else [dict(CANONICAL_GATE_ENTRY)]
    _write(home / "settings.json", {"hooks": {"PreToolUse": [{"hooks": entries}]}})


def _passing_state(home: Path, session_id: str) -> dict:
    binding = cs.canonical_binding(home)
    run_id = "run-fixture-0001"
    events = []
    for i, label in enumerate(cs.RELIED_UPON_EVENTS):
        events.append({
            "event_label": label,
            "nonce": f"{i:02d}" + "a" * 30,
            "run_id": run_id,
            "host_receipt": {
                "session_id": session_id,
                "transcript_path": f"/tmp/{session_id}.jsonl",
                "cwd": str(home),
                "hook_event_name": label,
                "permission_mode": cs.ABSENT,
            },
            "outcome": "PASS",
            "failure_reason": None,
            "event_discriminator": "event_key_nonce",
            "event_identity_strength": "registration_bound",
            # PreToolUse is the blocking-capable event and must carry a PROVEN
            # block; the rest were observed non-blocking.
            "blocking_action": "blocked_confirmed" if label == "PreToolUse" else "not_applicable",
            "observation": "synthetic fully-PASS fixture for aggregate-formula tests",
        })
    deep = {n: {"status": "pass", "evidence": "fixture"} for n in cs.DEEP_CHECKS}
    deep["hook_ordering"]["properties"] = {
        p: {"status": "pass", "reason": "fixture"} for p in cs.ORDERING_PROPERTIES
    }
    return {
        "schema_version": cs.SCHEMA_VERSION,
        "status": "PASS",
        "session_id": session_id,
        "run_id": run_id,
        "nonce": "n" * 32,
        "start_time": cs.now_iso(),
        "completion_time": cs.now_iso(),
        "binding": binding,
        "events": events,
        "deep_checks": deep,
        "status_surface": {"status": "observed", "channel": "tmux capture-pane", "ansi_red": True},
        "overall": "PASS",
        "failure_reason": None,
        "activation_eligible": True,
    }


def _publish(statedir: Path, session_id: str, state: dict) -> Path:
    p = cs.state_path(session_id, statedir)
    cs.write_state_atomic(p, state)
    return p


def _gate(envelope: dict, home: Path, statedir: Path, session_id: str):
    env = dict(os.environ,
               CLAUDE_HOME=str(home),
               CLAUDE_CAPABILITY_STATE_DIR=str(statedir),
               CLAUDE_SESSION_ID=session_id)
    return subprocess.run([sys.executable, str(GATE)], input=json.dumps(envelope),
                          capture_output=True, text=True, env=env, timeout=60, check=False)


# --------------------------------------------------------------------------- #
# AC-CAPGATE-03 — canonical binding + the 6 invalidating mutations
# --------------------------------------------------------------------------- #
def test_binding_shape_and_sources(home: Path):
    b = cs.canonical_binding(home)
    assert [r["path"] for r in b["settings_records"]] == list(cs.SETTINGS_LAYERS)
    assert len(b["settings_records"]) == 3
    for r in b["settings_records"]:
        assert set(r) == {"path", "present", "sha256"}
        assert isinstance(r["present"], bool)
    assert b["harness_version"] == (home / "VERSION").read_text().strip()
    assert b["host_build"] and b["host_build"].lower() != "unknown"
    assert cs.binding_failure(b) is None


def test_absent_layer_is_recorded_not_skipped(home: Path):
    (home / "settings.local.json").unlink()
    rec = [r for r in cs.canonical_binding(home)["settings_records"]
           if r["path"] == "settings.local.json"][0]
    assert rec == {"path": "settings.local.json", "present": False, "sha256": None}


def test_unreadable_but_present_layer_fails_closed(home: Path, monkeypatch):
    monkeypatch.setattr(cs, "read_host_build", lambda: "2.0.0")
    b = cs.canonical_binding(home)
    b["settings_records"][0]["sha256"] = None  # present-but-unreadable
    assert cs.binding_failure(b) == "binding_layer_unreadable"


def test_host_build_unknown_is_non_passing(home: Path, monkeypatch):
    monkeypatch.setattr(cs, "read_host_build", lambda: "unknown")
    assert cs.binding_failure(cs.canonical_binding(home)) == "binding_host_build_unknown"
    monkeypatch.setattr(cs, "read_host_build", lambda: None)
    assert cs.binding_failure(cs.canonical_binding(home)) == "binding_host_build_unknown"


@pytest.mark.parametrize("layer", list(cs.SETTINGS_LAYERS))
def test_mutation_abc_each_settings_layer_invalidates(home: Path, layer: str):
    stored = cs.canonical_binding(home)
    p = home / layer
    p.write_text(p.read_text() + "\n", encoding="utf-8")
    assert not cs.binding_matches(stored, cs.canonical_binding(home))


def test_mutation_d_version_invalidates(home: Path):
    stored = cs.canonical_binding(home)
    (home / "VERSION").write_text("9.9.10-test\n", encoding="utf-8")
    assert not cs.binding_matches(stored, cs.canonical_binding(home))


def test_mutation_e_host_build_invalidates(home: Path, monkeypatch):
    stored = cs.canonical_binding(home)
    monkeypatch.setattr(cs, "read_host_build", lambda: "0.0.1-other")
    assert not cs.binding_matches(stored, cs.canonical_binding(home))


def test_mutation_f_render_regeneration_invalidates_without_touching_live_boundary(tmp_path: Path):
    """Mutation (f): a render-settings regeneration that alters settings.json bytes.

    Executed against an ISOLATED copied config root with explicit --template/--out
    targets. Mutate-and-restore against the live permission boundary is forbidden:
    the live file's allow-list is already divergent from its template, so a render
    aimed at it would strip broadened allow entries and re-add deny entries as a
    side effect of an acceptance step -- on the very surface this lane protects.

    Mechanism, stated correctly: on the RENDER path the loss mode is a SILENT
    OVERWRITE (the output is derived from the template, so a settings-only hook
    registration is simply replaced). The ABORT is the --check mode's behaviour,
    where an already-rendered file is compared against the template and a parity
    violation refuses.
    """
    live_settings = REPO / "settings.json"
    live_template = REPO / "settings.template.json"
    renderer = REPO / "scripts" / "install" / "render-settings"
    if not (live_settings.is_file() and live_template.is_file() and renderer.is_file()):
        pytest.skip("render pipeline not present in this checkout")

    pre = {p: _sha(p) for p in (live_settings, live_template)}
    pre_perms = json.loads(live_settings.read_text(encoding="utf-8")).get("permissions")

    iso = tmp_path / "isolated-config-root"
    iso.mkdir()
    shutil.copy2(live_template, iso / "settings.template.json")
    shutil.copy2(live_settings, iso / "settings.json")
    fake_home = tmp_path / "fake-install-home"
    fake_home.mkdir()

    def render() -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(renderer), str(fake_home),
             "--template", str(iso / "settings.template.json"),
             "--out", str(iso / "settings.json")],
            capture_output=True, text=True, timeout=120, check=False)

    r1 = render()
    assert r1.returncode == 0, f"baseline isolated render failed: {r1.stderr}"

    # Bind over the isolated root, then regenerate from a modified template.
    iso_home = tmp_path / "isohome"
    (iso_home / ".claude").mkdir(parents=True)
    shutil.copy2(iso / "settings.json", iso_home / "settings.json")
    (iso_home / "settings.local.json").write_text("{}", encoding="utf-8")
    (iso_home / ".claude" / "settings.local.json").write_text("{}", encoding="utf-8")
    (iso_home / "VERSION").write_text("9.9.9-test\n", encoding="utf-8")
    stored = cs.canonical_binding(iso_home)

    tpl = json.loads((iso / "settings.template.json").read_text(encoding="utf-8"))
    tpl["cleanupPeriodDays"] = int(tpl.get("cleanupPeriodDays") or 30) + 7
    (iso / "settings.template.json").write_text(json.dumps(tpl, indent=2), encoding="utf-8")
    r2 = render()
    assert r2.returncode == 0, f"isolated regeneration failed: {r2.stderr}"
    shutil.copy2(iso / "settings.json", iso_home / "settings.json")

    assert not cs.binding_matches(stored, cs.canonical_binding(iso_home)), \
        "an installer-originated render that altered settings.json bytes must invalidate"

    # POSTCONDITION: the real boundary is byte-for-byte untouched.
    for p, digest in pre.items():
        assert _sha(p) == digest, f"live boundary file mutated by an acceptance step: {p}"
    assert json.loads(live_settings.read_text(encoding="utf-8")).get("permissions") == pre_perms


# --------------------------------------------------------------------------- #
# AC-CAPGATE-09 — state provenance and atomicity
# --------------------------------------------------------------------------- #
def test_state_is_0600_and_atomic(home: Path, statedir: Path):
    p = _publish(statedir, "s1", _passing_state(home, "s1"))
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    assert not list(statedir.glob(".caphs.*"))


def test_handwritten_pass_is_rejected(statedir: Path):
    """Both hand-written shapes are rejected: the bare one on schema version, and
    the more careful one (right schema_version, still no receipts) on partiality."""
    p = cs.state_path("s2", statedir)
    p.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    os.chmod(p, 0o600)
    assert cs.load_state(p) == (None, "state_schema_version_mismatch")

    q = cs.state_path("s2b", statedir)
    q.write_text(json.dumps({"status": "PASS", "schema_version": cs.SCHEMA_VERSION}),
                 encoding="utf-8")
    os.chmod(q, 0o600)
    assert cs.load_state(q) == (None, "state_partial")


def test_symlinked_state_rejected(tmp_path: Path, statedir: Path, home: Path):
    real = tmp_path / "real.json"
    cs.write_state_atomic(real, _passing_state(home, "s3"))
    link = statedir / "capability-handshake-s3.json"
    link.symlink_to(real)
    assert cs.load_state(link)[1] == "state_symlink"


def test_wrong_owner_rejected(statedir: Path, home: Path):
    if os.geteuid() != 0:
        pytest.skip("chown to another uid requires root")
    p = _publish(statedir, "s4", _passing_state(home, "s4"))
    os.chown(p, 65534, 65534)
    assert cs.load_state(p)[1] == "state_wrong_owner"


def test_insecure_mode_rejected(statedir: Path, home: Path):
    p = _publish(statedir, "s5", _passing_state(home, "s5"))
    os.chmod(p, 0o644)
    assert cs.load_state(p)[1] == "state_insecure_mode"


def test_wrong_session_and_stale_pending_rejected(statedir: Path, home: Path):
    p = _publish(statedir, "s6", _passing_state(home, "s6"))
    assert cs.load_state(p, expected_session_id="other")[1] == "state_wrong_session"
    st = _passing_state(home, "s7")
    st["status"] = "PENDING"
    q = _publish(statedir, "s7", st)
    assert cs.load_state(q, now=cs._epoch(st["start_time"]) + cs.PENDING_TIMEOUT_SEC + 1)[1] \
        == "state_pending_timeout"


def test_interrupted_run_leaves_pending_not_stale_pass(home: Path, statedir: Path, monkeypatch):
    """A run killed mid-execution must leave PENDING and the gate must block."""
    sid = "s8"
    _publish(statedir, sid, _passing_state(home, sid))  # a prior PASS exists
    monkeypatch.setenv("CLAUDE_CAPABILITY_STATE_DIR", str(statedir))
    monkeypatch.setenv("CLAUDE_HOME", str(home))
    import importlib.util
    spec = importlib.util.spec_from_file_location("caphs_mod", HANDSHAKE)
    hs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hs)
    monkeypatch.setattr(hs, "collect_receipts", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        hs.run_handshake(sid, home, cs.state_path(sid, statedir), 1)
    state, err = cs.load_state(cs.state_path(sid, statedir))
    assert err is None and state["status"] == "PENDING"
    assert cs.aggregate_verdict(state, home) == ("UNPROTECTED", "state_pending")


# --------------------------------------------------------------------------- #
# AC-CAPGATE-04 — aggregate formula through the real gate, synthetic envelope
# --------------------------------------------------------------------------- #
ENVELOPE = {"tool_name": "SlashCommand", "tool_input": {"command": "/dev --focus x"}}


def test_gate_blocks_absent_state(home: Path, statedir: Path):
    r = _gate(dict(ENVELOPE, session_id="g0"), home, statedir, "g0")
    assert r.returncode == 2
    assert json.loads(r.stderr.splitlines()[0])["failure_reason"].endswith("state=state_absent")


@pytest.mark.parametrize("mutate,expect", [
    (lambda s: s.update(status="PENDING"), "state_pending"),
    (lambda s: s.update(status="FAIL"), "state_status_fail"),
    (lambda s: s["binding"]["settings_records"][0].update(sha256="0" * 64), "binding_mismatch"),
    (lambda s: s["events"].pop(), "missing_event_record"),
    (lambda s: s["deep_checks"]["hook_ordering"]["properties"]
        ["declared_order_and_exit2_short_circuit"].update(status="unsupported_self_check"),
     "deep_check_unsupported"),
    (lambda s: s["deep_checks"]["permission_deny"].update(status="unsupported_self_check"),
     "deep_check_unsupported"),
    (lambda s: s["status_surface"].update(status="unsupported"), "status_surface_unobservable"),
])
def test_gate_blocks_every_non_pass_state(home: Path, statedir: Path, mutate, expect):
    sid = "g1"
    st = _passing_state(home, sid)
    mutate(st)
    _publish(statedir, sid, st)
    r = _gate(dict(ENVELOPE, session_id=sid), home, statedir, sid)
    assert r.returncode == 2, r.stdout
    assert expect in r.stderr, r.stderr
    assert "UNPROTECTED HOST" in r.stderr


def test_gate_allows_only_fully_pass(home: Path, statedir: Path):
    sid = "g2"
    _publish(statedir, sid, _passing_state(home, sid))
    r = _gate(dict(ENVELOPE, session_id=sid), home, statedir, sid)
    assert r.returncode == 0, r.stderr


def test_gate_fails_closed_on_internal_error(home: Path, statedir: Path):
    """A gate that cannot evaluate must block, never silently allow."""
    sid = "g3"
    (home / "policies" / MANIFEST_SRC.name).write_text("{ not json", encoding="utf-8")
    _publish(statedir, sid, _passing_state(home, sid))
    r = _gate(dict(ENVELOPE, session_id=sid), home, statedir, sid)
    assert r.returncode == 2
    assert "manifest_unreadable" in r.stderr


# --------------------------------------------------------------------------- #
# AC-CAPGATE-08 — manifest coverage + fail-closed default
# --------------------------------------------------------------------------- #
def test_every_manifest_route_is_gated(home: Path, statedir: Path):
    manifest, err = cs.load_manifest(home)
    assert err is None and manifest["routes"]
    sid = "m1"
    st = _passing_state(home, sid)
    st["status"] = "FAIL"
    _publish(statedir, sid, st)
    for entry in manifest["routes"]:
        rec = cs.evaluate_activation(entry["route"], home=home, session_id=sid,
                                     state_file=cs.state_path(sid, statedir))
        if entry.get("human_consent_escape_hatch"):
            # Deliberately exempt — asserted positively so the carve-out can never
            # widen silently: an escape hatch must PERMIT and must say why.
            assert rec["decision"] == "PERMIT", entry["route"]
            assert rec["exemption"] == "human_consent_escape_hatch", entry["route"]
        else:
            assert rec["decision"] == "REFUSE", entry["route"]


def test_escape_hatch_set_is_exactly_the_two_documented_consent_routes(home: Path):
    """The carve-out is the one place this gate can be widened by editing data
    alone, so its membership is pinned by a test rather than by review."""
    manifest, err = cs.load_manifest(home)
    assert err is None
    exempt = {e["route"] for e in manifest["routes"] if e.get("human_consent_escape_hatch")}
    assert exempt == {"slashcommand:/do", "slashcommand:/allow"}
    # Every exempt route must justify itself in the manifest.
    for entry in manifest["routes"]:
        if entry.get("human_consent_escape_hatch"):
            assert entry.get("why_exempt"), entry["route"]


@pytest.mark.parametrize("command", ["/do", "/allow git push"])
def test_escape_hatches_survive_absent_state(home: Path, statedir: Path, command: str):
    """THE decisive anti-self-sealing property: with NO state on disk at all, a
    human must still be able to authorise a repair through the harness."""
    sid = "hatch"
    assert not cs.state_path(sid, statedir).exists()
    r = _gate({"tool_name": "SlashCommand", "tool_input": {"command": command},
               "session_id": sid}, home, statedir, sid)
    assert r.returncode == 0, r.stderr


def test_escape_hatch_definition_cannot_drift_across_its_three_copies(home: Path):
    """The hatch set is written down three times — the gate hook's pre-import
    literal, capability_state's manifest-failure fallback, and the manifest flags.
    Editing one alone would either strand a human or widen the carve-out."""
    manifest, err = cs.load_manifest(home)
    assert err is None
    from_manifest = {e["route"] for e in manifest["routes"] if e.get("human_consent_escape_hatch")}
    assert set(cs.HUMAN_CONSENT_ESCAPE_HATCH_ROUTES) == from_manifest
    hook_src = GATE.read_text(encoding="utf-8")
    literal = hook_src.split("ESCAPE_HATCH_COMMANDS = (", 1)[1].split(")", 1)[0]
    from_hook = {f"slashcommand:{c.strip().strip(chr(34) + chr(39))}"
                 for c in literal.split(",") if c.strip()}
    assert from_hook == from_manifest


# --------------------------------------------------------------------------- #
# The REPAIR FLOOR — the closed set that keeps a degraded host repairable
# --------------------------------------------------------------------------- #
# The canonical floor, written out here as a literal so the test does NOT import
# its own oracle from the code under test. Changing the production constant
# alone must fail; changing both together is a deliberate act that has to edit
# this line too.
CANONICAL_REPAIR_FLOOR = {
    "tool:Read", "tool:Edit", "tool:Write", "tool:Bash", "tool:Glob", "tool:Grep",
}

# A GREEDY floor: the canonical six plus five routes a dev under repair pressure
# might reach for. It is the negative control for the equality guard, and it is
# also fully DISJOINT from the shipped protected surface — which is precisely why
# disjointness cannot be the guard.
GREEDY_REPAIR_FLOOR = CANONICAL_REPAIR_FLOOR | {
    "tool:Agent", "tool:Task", "tool:WebFetch", "tool:NotebookEdit", "tool:WebSearch",
}

# The three broken-manifest states. `missing` and `malformed_json` deliberately
# BOTH resolve to manifest_unreadable; `not_a_list` is the only fixture that
# reaches manifest_malformed. Each state asserts the reason the loader actually
# returned, so two fixtures can never silently exercise one branch.
BROKEN_MANIFEST_STATES = [
    ("missing", None, "manifest_unreadable"),
    ("malformed_json", "{not json", "manifest_unreadable"),
    ("not_a_list", '{"routes": {}}', "manifest_malformed"),
]


def _break_manifest(home: Path, content: str | None) -> None:
    mpath = home / cs.MANIFEST_RELPATH
    if content is None:
        mpath.unlink()
    else:
        mpath.write_text(content, encoding="utf-8")


def _floor_collisions(manifest: dict, floor) -> set[str]:
    """Floor routes that land INSIDE the effective protected surface.

    Derived, never hardcoded: it asks the production resolver `route_lookup()`
    about every floor route, so it inherits the real exact-routes-before-prefixes
    resolution order. A floor route collides if it is exact-listed in routes[] OR
    matched by a protected_surface_prefix — the union that forms the effective
    protected set. Empty result == disjoint.
    """
    return {route for route in floor if cs.route_lookup(manifest, route)[1]}


def _is_canonical_floor(candidate) -> bool:
    """The bounding predicate: set EQUALITY, not membership."""
    return set(candidate) == CANONICAL_REPAIR_FLOOR


def _floor_from_gate_source() -> set[str]:
    literal = GATE.read_text(encoding="utf-8").split("REPAIR_FLOOR_TOOLS = (", 1)[1].split(")", 1)[0]
    return {f"tool:{t.strip().strip(chr(34) + chr(39))}" for t in literal.split(",") if t.strip()}


def test_repair_floor_is_exactly_the_canonical_closed_set():
    """AC-CAP-02: the floor is CLOSED. Every member is permanently outside the
    protected surface, so the set is pinned by equality rather than by review."""
    assert _is_canonical_floor(cs.REPAIR_FLOOR_ROUTES)
    assert len(cs.REPAIR_FLOOR_ROUTES) == len(set(cs.REPAIR_FLOOR_ROUTES)), "duplicate member"
    # No member may be admitted without a recorded reason for being permanently open.
    assert set(cs.REPAIR_FLOOR_RATIONALE) == CANONICAL_REPAIR_FLOOR
    for route, why in cs.REPAIR_FLOOR_RATIONALE.items():
        assert why and len(why) > 40, route


def test_repair_floor_cannot_drift_between_its_two_copies():
    """The floor is written down twice — the gate hook's pre-import literal and
    capability_state's constant. Two copies exist because the library is itself a
    bound artifact and cannot be the sole home of its own recovery path; editing
    either alone would either re-brick the degraded host or widen the carve-out."""
    assert _floor_from_gate_source() == set(cs.REPAIR_FLOOR_ROUTES)
    assert _is_canonical_floor(_floor_from_gate_source())


def test_a_greedy_floor_fails_the_equality_guard_though_it_passes_disjointness():
    """The guard has teeth, and disjointness is NOT that guard.

    A greedy floor that swallows Agent, Task, WebFetch, NotebookEdit and
    WebSearch is a namespace-wide fail-open on the degraded path. It is fully
    disjoint from the shipped protected surface — because that surface is
    entirely slashcommand:/skill: while every floor member is tool: — so a
    disjointness test waves it straight through. Only set equality rejects it.
    """
    manifest, err = cs.load_manifest(REPO)
    assert err is None
    assert _floor_collisions(manifest, GREEDY_REPAIR_FLOOR) == set(), \
        "disjointness alone cannot bound the floor — that is why equality is the guard"
    assert not _is_canonical_floor(GREEDY_REPAIR_FLOOR), \
        "the equality guard must REJECT a widened floor"
    assert _is_canonical_floor(cs.REPAIR_FLOOR_ROUTES)


def test_effective_protected_set_is_disjoint_from_the_repair_floor():
    """AC-CAP-03 limb (a): no shipped protected route is on the floor."""
    manifest, err = cs.load_manifest(REPO)
    assert err is None
    assert _floor_collisions(manifest, cs.REPAIR_FLOOR_ROUTES) == set()


def test_disjointness_helper_detects_an_exact_listed_floor_route():
    """AC-CAP-03 limb (b), as a PASSING assertion that the helper caught it.

    Mirroring `protected_surface_prefixes` as a constant would NOT be sufficient:
    route_lookup matches the exact routes[] list FIRST and only then tests
    prefixes, so a manifest that exact-lists tool:Read re-seals the host without
    ever declaring a tool: prefix. This is that manifest.
    """
    manifest, err = cs.load_manifest(REPO)
    assert err is None
    assert "tool:" not in manifest["protected_surface_prefixes"]
    manifest["routes"].append({
        "id": "adversarial-floor-collision", "route": "tool:Read",
        "route_type": "Tool", "entrypoint": "n/a", "why_protected": "fixture",
    })
    collisions = _floor_collisions(manifest, cs.REPAIR_FLOOR_ROUTES)
    assert collisions == {"tool:Read"}, collisions


@pytest.mark.parametrize("label,content,expect_reason", BROKEN_MANIFEST_STATES)
def test_escape_hatches_survive_a_broken_manifest(
        home: Path, statedir: Path, label: str, content: str | None, expect_reason: str):
    """codex #1: the carve-out originally sat BEHIND the manifest read, so a
    corrupt manifest re-sealed the host. Recovery must not live inside the
    failure domain it exists to recover from.

    The hatches were only ever half of that. They record human consent; they do
    not perform the Edit that repairs the manifest. So this also asserts the
    repair floor is open and — decisively — that a NON-floor route is still shut,
    which is what distinguishes a bounded floor from a blanket fail-open.
    """
    _break_manifest(home, content)
    # The states are distinct fixtures; assert the branch each actually reaches.
    assert cs.load_manifest(home)[1] == expect_reason, label
    sid = "brk"
    for route in cs.HUMAN_CONSENT_ESCAPE_HATCH_ROUTES:
        rec = cs.evaluate_activation(route, home=home, session_id=sid,
                                     state_file=cs.state_path(sid, statedir))
        assert rec["decision"] == "PERMIT", route
    # ...while every other route still fails closed on the same broken manifest.
    other = cs.evaluate_activation("slashcommand:/dev", home=home, session_id=sid,
                                   state_file=cs.state_path(sid, statedir))
    assert other["decision"] == "REFUSE"
    # THE REPAIR FLOOR, end to end through the hook: exit 0 for all six.
    for route in sorted(CANONICAL_REPAIR_FLOOR):
        tool = route.split(":", 1)[1]
        r = _gate({"tool_name": tool, "tool_input": {}, "session_id": sid}, home, statedir, sid)
        assert r.returncode == 0, f"{label}/{tool}: {r.stderr}"
    # THE NON-FLOOR NEGATIVE CONTROL. tool:Agent exits 0 under a HEALTHY manifest
    # and must exit 2 here. The asymmetry is deliberate: with no readable manifest
    # the gate cannot know what is protected, so everything off the floor fails
    # closed. Admitting Agent to the floor to "smooth" this would reintroduce the
    # unbounded-floor defect and must fail the equality guard above.
    r = _gate({"tool_name": "Agent", "tool_input": {}, "session_id": sid}, home, statedir, sid)
    assert r.returncode == 2, f"{label}/Agent must stay refused: {r.stdout}"


@pytest.mark.parametrize("label,content,expect_reason", BROKEN_MANIFEST_STATES)
def test_repair_floor_branch_is_reached_inside_the_library(
        home: Path, statedir: Path, label: str, content: str | None, expect_reason: str):
    """The floor probe above runs through the gate SUBPROCESS, which answers from its
    pre-import literal and never reaches evaluate_activation() -- so deleting the
    library's own floor branch leaves the whole suite green. `capability-doctor-strict.py
    --route` consumes the LIBRARY, not the gate: without that branch a degraded-state
    repair route flips NOT_PROTECTED/exit 3 to REFUSE/exit 1. Asserted DIRECTLY here,
    because an invariant only the gate copy can fail is still a review obligation."""
    _break_manifest(home, content)
    assert cs.load_manifest(home)[1] == expect_reason, label
    sid = "floorlib"
    st = cs.state_path(sid, statedir)
    for route in sorted(CANONICAL_REPAIR_FLOOR):
        rec = cs.evaluate_activation(route, home=home, session_id=sid, state_file=st)
        assert (rec["decision"], rec["exemption"]) == ("NOT_PROTECTED", "repair_floor"), \
            f"{label}/{route}: {rec}"
    # Negative control: an off-floor tool stays shut, so a namespace-wide fail-open
    # cannot satisfy this test either.
    agent = cs.evaluate_activation("tool:Agent", home=home, session_id=sid, state_file=st)
    assert (agent["decision"], agent["exemption"]) == ("REFUSE", None), f"{label}: {agent}"


@pytest.mark.parametrize("mode", ["raises_on_import", "absent"])
def test_repair_floor_survives_an_unresolvable_library(tmp_path: Path, home: Path,
                                                       statedir: Path, mode: str):
    """The library is itself a BOUND_ARTIFACTS member, so "capability_state.py is
    broken" is a reachable state — and the state in which a floor declared only
    inside that module would be unreachable. Hence the gate's pre-import literal.

    The gate resolves its library from `Path(__file__).parent/'lib'` — its OWN
    parent, never CLAUDE_HOME — so gate and library must be co-located in one
    isolated root or the mutation is never imported. Probing /do here would prove
    nothing either: the hatch returns 0 before any import is attempted.
    """
    root = tmp_path / f"isolated-{mode}"
    (root / "lib").mkdir(parents=True)
    gate = root / GATE.name
    shutil.copy2(GATE, gate)
    lib = root / "lib" / "capability_state.py"
    if mode == "raises_on_import":
        lib.write_text("raise ImportError('boom')\n", encoding="utf-8")
    # 'absent' leaves lib/ empty, so the import fails with ModuleNotFoundError.
    sid = "libgone"

    def _run(tool: str):
        env = dict(os.environ, CLAUDE_HOME=str(home),
                   CLAUDE_CAPABILITY_STATE_DIR=str(statedir), CLAUDE_SESSION_ID=sid)
        return subprocess.run(
            [sys.executable, str(gate)],
            input=json.dumps({"tool_name": tool, "tool_input": {}, "session_id": sid}),
            capture_output=True, text=True, env=env, timeout=60, check=False)

    assert not lib.exists() or "ImportError" in lib.read_text(encoding="utf-8")
    for route in sorted(CANONICAL_REPAIR_FLOOR):
        r = _run(route.split(":", 1)[1])
        assert r.returncode == 0, f"{mode}/{route}: {r.stderr}"
    agent = _run("Agent")
    assert agent.returncode == 2, f"{mode}/Agent must stay refused: {agent.stdout}"
    assert "library_unavailable" in agent.stderr, agent.stderr


@pytest.mark.parametrize("name", ["Read", "Bash"])
def test_skill_named_like_a_floor_tool_is_not_on_the_floor(home: Path, statedir: Path, name: str):
    """The floor is keyed on the exact tool route, so a Skill of the same name
    must not inherit it — the same property the hatches are pinned to."""
    sid = "skf"
    r = _gate({"tool_name": "Skill", "tool_input": {"skill": name}, "session_id": sid},
              home, statedir, sid)
    assert r.returncode == 2, r.stdout
    rec = cs.evaluate_activation(f"skill:{name}", home=home, session_id=sid,
                                 state_file=cs.state_path(sid, statedir))
    assert rec["decision"] == "REFUSE"
    assert rec["exemption"] is None


@pytest.mark.parametrize("command", ["/do\n/dev fix", "/allow x\r/commit", "/do\x00/push"])
def test_control_characters_cannot_smuggle_a_command_behind_a_hatch(
        home: Path, statedir: Path, command: str):
    """codex #3: `.split()` splits on newlines, so a multi-command payload would
    classify on its exempt first token. Any control character forfeits the fast
    path and the call is evaluated on state like anything else."""
    sid = "smug"
    r = _gate({"tool_name": "SlashCommand", "tool_input": {"command": command},
               "session_id": sid}, home, statedir, sid)
    assert r.returncode == 2, r.stdout


@pytest.mark.parametrize("name", ["do", "allow"])
def test_skill_named_like_a_hatch_is_not_exempt(home: Path, statedir: Path, name: str):
    """codex #2: the exemption is keyed on the exact SlashCommand route, so a
    Skill call of the same name must not inherit it."""
    sid = "skl"
    _publish(statedir, sid, _passing_state(home, sid))
    rec = cs.evaluate_activation(f"skill:{name}", home=home, session_id=sid,
                                 state_file=cs.state_path(sid, statedir))
    assert rec["decision"] == "REFUSE"
    assert rec["exemption"] is None


def _entrypoint_text(entrypoint: str) -> str:
    """An entrypoint is a file or a directory of files; return all of its text."""
    p = REPO / entrypoint
    if p.is_file():
        return p.read_text(encoding="utf-8", errors="replace")
    if p.is_dir():
        return "\n".join(f.read_text(encoding="utf-8", errors="replace")
                         for f in sorted(p.rglob("*")) if f.is_file())
    return ""


def test_independent_enforcement_claims_match_reality(home: Path):
    """AC-CAP-07: `independent_enforcement` is a COVERAGE annotation, and an
    untrue one is worse than an absent one — it is the field a reader consults to
    ask "is this route enforced anywhere the hook cannot be silently no-opped?".

    Every route claimed true while ZERO entrypoints invoked the per-route
    preflight. This asserts the claim against reality in whichever direction the
    tree moves: flipping a route to true without wiring its entrypoint fails
    here, and so does wiring an entrypoint while leaving the claim false.
    """
    manifest, err = cs.load_manifest(home)
    assert err is None
    preflight = Path(manifest["independent_enforcement_callsite"].split()[0]).name
    assert preflight, "the manifest must name its independent callsite"
    for entry in manifest["routes"]:
        invokes = preflight in _entrypoint_text(entry["entrypoint"])
        assert bool(entry.get("independent_enforcement", False)) == invokes, (
            f"{entry['route']}: claims independent_enforcement="
            f"{entry.get('independent_enforcement')} but entrypoint "
            f"{entry['entrypoint']!r} {'does' if invokes else 'does not'} invoke {preflight}"
        )


@pytest.mark.parametrize("tool", ["Agent", "Task"])
def test_dispatch_routes_are_outside_the_protected_surface(home: Path, statedir: Path, tool: str):
    """Regression for the unrecoverable-lockout defect, recorded as an OPEN
    coverage reduction rather than as a resolved one.

    VERIFIED FACT: no non-hook enforcement point for direct subagent dispatch
    exists in this harness today, so refusing the route refused it on grounds no
    state could ever satisfy — zero protection on the threat host, a permanent
    block on a healthy one.

    POLICY INFERENCE, stated separately because clause (E) denies it: that this
    licenses REMOVING the routes from the surface rather than reporting them
    unsupported. This test pins the current behaviour; it does not endorse the
    inference. Direct dispatch is therefore UNGATED on every host — it is not
    gated transitively through the manifested workflows, because a direct Agent
    or Task call never presents a SlashCommand envelope. Restoration condition:
    a reachable live PASS plus an entrypoint consumer that invokes the per-route
    preflight; until both exist, restoring the routes would only re-create the
    unsatisfiable refusal.

    tool:Agent is additionally the NON-FLOOR NEGATIVE CONTROL for the repair
    floor (see test_escape_hatches_survive_a_broken_manifest): admitting it to
    the floor would make this already-open reduction permanent in the degraded
    state too.
    """
    sid = "disp"
    r = _gate({"tool_name": tool, "tool_input": {}, "session_id": sid}, home, statedir, sid)
    assert r.returncode == 0, r.stderr
    rec = cs.evaluate_activation(f"tool:{tool}", home=home, session_id=sid,
                                 state_file=cs.state_path(sid, statedir))
    assert rec["decision"] == "NOT_PROTECTED"
    assert "route_outside_protected_surface" in rec["failure_reason"]


def test_unmanifested_route_in_surface_is_blocked_fail_closed(home: Path, statedir: Path):
    sid = "m2"
    _publish(statedir, sid, _passing_state(home, sid))  # fully PASS on purpose
    env = dict(ENVELOPE, session_id=sid)
    env["tool_input"] = {"command": "/synthetic-unmanifested-route"}
    r = _gate(env, home, statedir, sid)
    assert r.returncode == 2
    assert "unmanifested_route" in r.stderr


def test_route_outside_protected_surface_is_not_this_gates_business(home: Path, statedir: Path):
    sid = "m3"
    r = _gate({"tool_name": "Read", "tool_input": {"file_path": "/etc/hosts"}, "session_id": sid},
              home, statedir, sid)
    assert r.returncode == 0, r.stderr


def test_gate_only_route_is_satisfiable_by_state_not_refused_unconditionally(
        home: Path, statedir: Path):
    """`independent_enforcement: false` is a COVERAGE annotation, not a verdict.

    The old contract refused such a route BEFORE loading state, so no state could
    satisfy it — zero protection on the threat host (where the gate never runs)
    and a permanent block on a healthy one. The route must now be decided by the
    handshake: REFUSE while unprotected, PERMIT on a fresh PASS.
    """
    sid = "m4"
    manifest, err = cs.load_manifest(home)
    assert err is None
    manifest["routes"].append({
        "id": "synthetic-gate-only", "route": "skill:gate-only-probe",
        "route_type": "Skill", "entrypoint": "n/a",
        "independent_enforcement": False, "why_protected": "fixture",
    })
    _write(home / cs.MANIFEST_RELPATH, manifest)
    sp = cs.state_path(sid, statedir)

    def _rec():
        return cs.evaluate_activation("skill:gate-only-probe", home=home,
                                      session_id=sid, state_file=sp)

    refused = _rec()
    assert refused["decision"] == "REFUSE"
    assert "state=state_absent" in refused["failure_reason"]
    assert refused["enforcement_mode"] == "gate_only"
    # ...and the SAME route flips to PERMIT once the handshake passes, which is
    # what "satisfiable" means and what the old code made impossible.
    _publish(statedir, sid, _passing_state(home, sid))
    permitted = _rec()
    assert permitted["decision"] == "PERMIT", permitted["failure_reason"]
    assert permitted["enforcement_mode"] == "gate_only"


def test_preflight_cli_is_a_real_non_hook_callsite(home: Path, statedir: Path):
    """The documented non-circular enforcement point must be genuinely reachable
    from the callsite the manifest names — not merely asserted in a docstring."""
    manifest, err = cs.load_manifest(home)
    assert err is None
    assert manifest["independent_enforcement_callsite"].startswith(
        "scripts/capability-doctor-strict.py --route")
    sid = "pf"
    env = dict(os.environ, CLAUDE_HOME=str(home),
               CLAUDE_CAPABILITY_STATE_DIR=str(statedir), CLAUDE_SESSION_ID=sid)
    strict = REPO / "scripts" / "capability-doctor-strict.py"

    def _run(route):
        r = subprocess.run([sys.executable, str(strict), "--home", str(home),
                            "--session-id", sid, "--route", route],
                           capture_output=True, text=True, env=env, timeout=60, check=False)
        return r.returncode, json.loads(r.stdout)

    rc, rec = _run("slashcommand:/dev")
    assert rc == 1 and rec["decision"] == "REFUSE"
    assert rec["component"] == "preflight_consumer"
    rc, rec = _run("slashcommand:/do")
    assert rc == 0 and rec["exemption"] == "human_consent_escape_hatch"
    # codex #9: NOT_PROTECTED must not share exit 0 with PERMIT, or a mistyped
    # route reads as approval.
    rc, rec = _run("tool:Agent")
    assert rc == 3 and rec["decision"] == "NOT_PROTECTED"
    rc, rec = _run("tool:Typoed-Route")
    assert rc == 3
    # Preflight must never mint state — it reads the handshake, it is not one.
    assert not cs.state_path(sid, statedir).exists()


# --------------------------------------------------------------------------- #
# AC-CAPGATE-10 — independence matrix over gate REGISTRATION *and* gate EFFICACY
# --------------------------------------------------------------------------- #
ROUTE = "slashcommand:/dev"


def _cell(home: Path, statedir: Path, registration: str, passing: bool, sid: str):
    """Materialise one matrix cell and return (gate_result|None, consumer_record).

    The binding is RECOMPUTED over the settings fixture in EVERY cell, so binding
    validity is true by construction and can never confound a result.
    """
    _settings_fixture(home, registration)
    st = _passing_state(home, sid)          # binding recomputed here, post-fixture
    if not passing:
        st["status"] = "FAIL"
        st["overall"] = "UNPROTECTED"
        st["activation_eligible"] = False
    _publish(statedir, sid, st)

    gate_result = None
    if registration == "registered":
        # Only a genuinely dispatching host runs the gate. 'inert' preserves the
        # registration verbatim and does NOT dispatch.
        gate_result = _gate(dict(ENVELOPE, session_id=sid), home, statedir, sid)
    consumer = cs.evaluate_activation(ROUTE, home=home, session_id=sid,
                                      state_file=cs.state_path(sid, statedir))
    return gate_result, consumer


@pytest.mark.parametrize("registration", ["registered", "removed", "inert"])
@pytest.mark.parametrize("passing", [True, False])
def test_independence_matrix(home: Path, statedir: Path, registration: str, passing: bool):
    sid = f"x-{registration}-{int(passing)}"
    gate, consumer = _cell(home, statedir, registration, passing, sid)

    if registration == "registered" and not passing:
        # Cell (D): blocked UPSTREAM by the registered gate -> a GATE decision
        # record is required here, never a fictitious consumer-read record.
        assert gate.returncode == 2
        rec = json.loads(gate.stderr.splitlines()[0])
        assert rec["component"] == "capability_gate" and rec["decision"] == "REFUSE"

    if registration == "registered" and passing:
        # Cell (C): a permitted activation necessarily REACHES the entrypoint, so
        # the consumer decision record is required in this cell too.
        assert gate.returncode == 0
        assert consumer["decision"] == "PERMIT"
        assert consumer["state_input"]["run_id"] and consumer["state_input"]["nonce"]
        assert consumer["state_input"]["digest"].startswith("sha256:")

    expected = "PERMIT" if passing else "REFUSE"
    assert consumer["decision"] == expected, (registration, passing, consumer)
    if not passing:
        assert consumer["failure_reason"].startswith("independent_consumer_refused: state=")


def test_state_sensitivity_holding_registration_constant(home: Path, statedir: Path):
    """The falsifiable form of non-circularity, evaluated at EVERY registration
    condition -- including 'inert', the real threat host."""
    for registration in ("removed", "registered", "inert"):
        _, refuse = _cell(home, statedir, registration, False, f"ss-{registration}-0")
        _, permit = _cell(home, statedir, registration, True, f"ss-{registration}-1")
        assert refuse["decision"] == "REFUSE" and permit["decision"] == "PERMIT", registration
        assert refuse["state_input"]["digest"] != permit["state_input"]["digest"]


def test_consumer_decision_is_invariant_to_gate_registration(home: Path, statedir: Path):
    """Defeats the named cheat directly: a consumer that keys on gate presence
    would differ across these three conditions at a FIXED state value."""
    for passing in (True, False):
        decisions = set()
        for registration in ("registered", "removed", "inert"):
            _, rec = _cell(home, statedir, registration, passing, f"inv-{registration}-{int(passing)}")
            decisions.add(rec["decision"])
        assert len(decisions) == 1, f"consumer decision varied with gate registration: {decisions}"


def test_consumer_never_reads_hook_registration(home: Path):
    """Structural guarantee, asserted so a later refactor cannot quietly break it."""
    src = (REPO / "hooks" / "lib" / "capability_state.py").read_text(encoding="utf-8")
    for forbidden in ('["hooks"]', "['hooks']", 'get("hooks")', "get('hooks')"):
        assert forbidden not in src, f"consumer must not parse hook arrays: {forbidden!r}"
    # Settings layers are consumed as raw BYTES for hashing only.
    assert "p.read_bytes()" in src
    assert "json.load" not in src.split("def settings_records")[1].split("def read_harness")[0]


# --------------------------------------------------------------------------- #
# AC-CAPGATE-01 — missing-event negative test + fixture falsifiability
# --------------------------------------------------------------------------- #
def test_missing_event_unit_path_no_settings_touched(home: Path):
    """Unit path: 6/7 receipts, no settings file touched, so no binding involved."""
    before = {layer: _sha(home / layer) for layer in cs.SETTINGS_LAYERS}
    st = _passing_state(home, "u1")
    st["events"] = st["events"][:-1]
    overall, reason = cs.aggregate_verdict(st, home)
    assert overall != "PASS" and reason == "missing_event_record"
    assert {layer: _sha(home / layer) for layer in cs.SETTINGS_LAYERS} == before


def test_missing_event_integration_path_reports_missing_not_binding(home: Path):
    """Integration path: suppress one event in a settings FIXTURE, recompute the
    binding over that fixture so it is valid by construction, and assert the
    failure class is missing_event_record and explicitly NOT binding_mismatch."""
    _settings_fixture(home, "removed")
    st = _passing_state(home, "u2")           # binding recomputed post-fixture
    st["events"] = [e for e in st["events"] if e["event_label"] != "Notification"]
    overall, reason = cs.aggregate_verdict(st, home)
    assert overall != "PASS"
    assert reason == "missing_event_record"
    assert reason != "binding_mismatch"


def test_failure_reasons_are_distinguishable(home: Path):
    """A run reporting only a boolean non-PASS fails the AC; prove the classes differ."""
    reasons = set()
    for mutate in (
        lambda s: s["events"].pop(),
        lambda s: s["binding"]["settings_records"][0].update(sha256="1" * 64),
        lambda s: s["deep_checks"]["permission_deny"].update(status="unsupported_self_check"),
        lambda s: s["status_surface"].update(status="unsupported"),
        lambda s: s.update(status="PENDING"),
    ):
        st = _passing_state(home, "u3")
        mutate(st)
        reasons.add(cs.aggregate_verdict(st, home)[1])
    assert len(reasons) == 5, reasons


def test_tier3_field_silently_omitted_fails(home: Path):
    st = _passing_state(home, "u4")
    del st["events"][0]["host_receipt"]["permission_mode"]
    assert cs.aggregate_verdict(st, home) == ("UNPROTECTED", "host_receipt_tier3_field_omitted")


def test_tier3_absent_marker_is_accepted(home: Path):
    st = _passing_state(home, "u5")
    st["events"][0]["host_receipt"]["permission_mode"] = cs.ABSENT
    st["events"][0]["host_receipt"]["hook_event_name"] = cs.ABSENT
    assert cs.aggregate_verdict(st, home)[0] == "PASS"


def test_shared_event_nonce_is_rejected(home: Path):
    st = _passing_state(home, "u6")
    st["events"][1]["nonce"] = st["events"][0]["nonce"]
    assert cs.aggregate_verdict(st, home) == ("UNPROTECTED", "receipt_nonce_not_event_distinct")


def test_replayed_receipt_from_prior_run_is_rejected(home: Path):
    st = _passing_state(home, "u7")
    st["events"][2]["run_id"] = "run-from-a-previous-execution"
    assert cs.aggregate_verdict(st, home) == ("UNPROTECTED", "receipt_run_id_mismatch")


def test_fixture_path_is_diagnostic_only_and_cannot_pass(tmp_path: Path, home: Path):
    """The falsifiability proof: the synthetic-envelope technique produces receipts
    yet provably cannot satisfy cross-checks 3-5 without fabricating a transcript."""
    env = dict(os.environ, CLAUDE_CAPABILITY_STATE_DIR=str(tmp_path / "fx"),
               CLAUDE_HOME=str(home))
    r = subprocess.run([sys.executable, str(HANDSHAKE), "--home", str(home),
                        "--session-id", "fx1", "--fixture-diagnostic"],
                       capture_output=True, text=True, env=env, timeout=180, check=False)
    assert r.returncode != 0, "a fixture run must never exit 0"
    out = json.loads(r.stdout)
    assert out["mode"] == "diagnostic_only"
    assert out["receipts_produced"] == len(cs.RELIED_UPON_EVENTS)
    assert out["overall"] == "UNPROTECTED"
    assert all(e["outcome"] != "PASS" for e in out["events"])
    assert {e["failure_reason"] for e in out["events"]} <= {
        "transcript_absent", "transcript_stem_mismatch", "session_id_not_ambient",
        "transcript_missing_run_nonce", "transcript_mtime_stale", "transcript_session_mismatch",
    }


def test_probe_fixtures_cleaned_on_every_exit_path(tmp_path: Path, home: Path):
    d = tmp_path / "fx2"
    env = dict(os.environ, CLAUDE_CAPABILITY_STATE_DIR=str(d), CLAUDE_HOME=str(home))
    subprocess.run([sys.executable, str(HANDSHAKE), "--home", str(home),
                    "--session-id", "fx2", "--timeout", "1"],
                   capture_output=True, text=True, env=env, timeout=180, check=False)
    leftovers = [p.name for p in d.iterdir() if p.name.startswith(("probe-", "receipts-", "sentinels-"))]
    assert leftovers == [], leftovers


# --------------------------------------------------------------------------- #
# AC-CAPGATE-06 — doctor --strict runs fresh and stays short
# --------------------------------------------------------------------------- #
def _doctor_strict(home: Path, statedir: Path, sid: str, verbose: bool = False):
    args = [str(DOCTOR), "--strict"] + (["--verbose"] if verbose else [])
    env = dict(os.environ, CLAUDE_HOME=str(home), CLAUDE_CAPABILITY_STATE_DIR=str(statedir),
               CLAUDE_SESSION_ID=sid)
    return subprocess.run(["bash"] + args, capture_output=True, text=True, env=env,
                          timeout=300, check=False)


def test_doctor_strict_ignores_preseeded_pass(home: Path, statedir: Path):
    sid = "d1"
    _publish(statedir, sid, _passing_state(home, sid))   # stale preseeded PASS
    r = _doctor_strict(home, statedir, sid)
    assert r.returncode != 0, "a preseeded PASS must not be trusted as proof"
    assert "VERDICT UNPROTECTED" in r.stdout
    state, _ = cs.load_state(cs.state_path(sid, statedir))
    assert state["run_id"] != _passing_state(home, sid)["run_id"], "run was not fresh"


def test_doctor_strict_default_report_is_short(home: Path, statedir: Path):
    r = _doctor_strict(home, statedir, "d2")
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(lines) <= 20, f"default report is {len(lines)} lines: {lines}"
    labels = [ln.split()[0] for ln in lines]
    for ev in cs.RELIED_UPON_EVENTS:
        assert ev in labels, f"missing per-event line for {ev}"
    assert sum(1 for ln in lines if ln.startswith("VERDICT ")) == 1


def test_doctor_strict_verbose_carries_the_detail(home: Path, statedir: Path):
    r = _doctor_strict(home, statedir, "d3", verbose=True)
    detail = json.loads(r.stdout)
    for key in ("binding", "events", "deep_checks", "status_surface", "independent_consumer"):
        assert key in detail
    assert detail["fresh_run"]["nonce_prefix"]


def test_doctor_strict_is_an_independent_enforcement_point(home: Path, statedir: Path):
    """It must reach a verdict with no hook dispatch anywhere in the path."""
    _settings_fixture(home, "removed")
    r = _doctor_strict(home, statedir, "d4", verbose=True)
    detail = json.loads(r.stdout)
    assert detail["independent_consumer"], "no independent consumer records emitted"
    assert all(rec["component"] == "independent_consumer" for rec in detail["independent_consumer"])
    assert r.returncode != 0


# --------------------------------------------------------------------------- #
# AC-CAPGATE-05 — status surface (unobservable => unsupported, never stdout)
# --------------------------------------------------------------------------- #
def test_status_line_emits_red_marker_when_unprotected(home: Path, statedir: Path):
    sl = REPO / "scripts" / "capability-status-line.sh"
    env = dict(os.environ, CLAUDE_HOME=str(home), CLAUDE_CAPABILITY_STATE_DIR=str(statedir))
    r = subprocess.run(["bash", str(sl)], input=json.dumps({"session_id": "sl1"}),
                       capture_output=True, text=True, env=env, timeout=120, check=False)
    assert r.returncode == 0, "a status line must never be able to wedge a session"
    assert "UNPROTECTED HOST" in r.stdout
    assert "\x1b[1;31m" in r.stdout


# --------------------------------------------------------------------------- #
# Fixes driven by the codex adversarial pass (docs/codex/dev-20260719-193823-a/dev.txt)
# --------------------------------------------------------------------------- #
def test_canary_liveness_alone_cannot_reach_pass(home: Path):
    """codex #3 (selective dispatch). Every canary exits 0 by construction, so a
    host that dispatches all seven canaries while skipping the blocking gate must
    NOT reach PASS. An unestablished blocking classification is non-passing."""
    st = _passing_state(home, "c1")
    for ev in st["events"]:
        ev["blocking_action"] = "not_established"
    assert cs.aggregate_verdict(st, home) == ("UNPROTECTED", "blocking_capability_not_established")


def test_no_event_proving_a_block_cannot_reach_pass(home: Path):
    st = _passing_state(home, "c2")
    for ev in st["events"]:
        ev["blocking_action"] = "not_applicable"
    assert cs.aggregate_verdict(st, home) == ("UNPROTECTED", "no_blocking_capability_proven")


@pytest.mark.parametrize("artifact", list(cs.BOUND_ARTIFACTS))
def test_every_enforcement_artifact_is_bound(home: Path, artifact: str):
    """codex #6. Editing the manifest to move a protected route outside every
    surface prefix must NOT preserve an existing PASS."""
    stored = cs.canonical_binding(home)
    p = home / artifact
    p.write_bytes(p.read_bytes() + b"\n# tamper\n")
    assert not cs.binding_matches(stored, cs.canonical_binding(home))


def test_missing_enforcement_artifact_is_non_passing(home: Path):
    (home / "policies" / MANIFEST_SRC.name).unlink()
    assert cs.binding_failure(cs.canonical_binding(home)) == "binding_artifact_missing"


def test_pass_expires_on_wall_clock_age(home: Path):
    """codex #10. Same-session equality does not survive a host restart."""
    st = _passing_state(home, "c3")
    assert cs.aggregate_verdict(st, home)[0] == "PASS"
    stale = cs._epoch(st["completion_time"]) + cs.PASS_MAX_AGE_SEC + 1
    assert cs.aggregate_verdict(st, home, now=stale) == ("UNPROTECTED", "pass_expired")


def test_malformed_slash_route_lands_inside_the_protected_surface(home: Path, statedir: Path):
    """codex #9. A malformed/empty slash command must block, not fall outside the
    surface and be treated as ordinary traffic."""
    sid = "c4"
    _publish(statedir, sid, _passing_state(home, sid))
    r = _gate({"tool_name": "SlashCommand", "tool_input": {"command": ""}, "session_id": sid},
              home, statedir, sid)
    assert r.returncode == 2
    assert "unmanifested_route" in r.stderr


def test_transcript_nonce_before_probe_offset_is_rejected(tmp_path: Path):
    """codex #8. A nonce already present in the transcript must not satisfy
    cross-check 4; only an appearance past the probe-open offset counts."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("caphs_off", HANDSHAKE)
    hs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hs)

    sid = "11111111-2222-3333-4444-555555555555"
    nonce = "deadbeef" * 8
    tr = tmp_path / f"{sid}.jsonl"
    tr.write_text(json.dumps({"sessionId": sid, "text": nonce}) + "\n", encoding="utf-8")
    rec = {"event_label": "PreToolUse", "nonce": "n1",
           "host_receipt": {"session_id": sid, "transcript_path": str(tr), "cwd": "/",
                            "hook_event_name": "PreToolUse", "permission_mode": cs.ABSENT}}
    probe = {"nonce": nonce, "event_nonces": {"PreToolUse": "n1"},
             "transcript_offsets": {str(tr): tr.stat().st_size}}
    outcome, reason, _ = hs.cross_check_event(rec, "PreToolUse", probe, 0.0, sid)
    assert (outcome, reason) == ("FAIL", "transcript_missing_run_nonce")


def test_event_identity_strength_is_recorded(home: Path):
    st = _passing_state(home, "c5")
    assert all(e["event_identity_strength"] in
               ("host_attested", "registration_bound", "none") for e in st["events"])


def test_unobservable_surface_classifies_unsupported_not_pass(home: Path):
    st = _passing_state(home, "sl2")
    st["status_surface"] = {"status": "unsupported", "reason": "no attached pane"}
    assert cs.aggregate_verdict(st, home) == ("UNPROTECTED", "status_surface_unobservable")
