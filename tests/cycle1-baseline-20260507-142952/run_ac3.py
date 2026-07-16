#!/usr/bin/env python3
"""AC-3 verification: agent_resolver.py inactive cp-state non-authoritative + collision fail-closed."""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

# We'll spawn a subprocess that imports agent_resolver with a controlled CLAUDE_PROJECT_DIR
RUNNER_SRC = """
import sys, os
sys.path.insert(0, '/root/.claude/hooks/lib')
from agent_resolver import resolve_agent_type, _resolve_by_id, _scan_cp_state_files, _FAIL_CLOSED
import json
payload = json.loads(sys.argv[1])
result = resolve_agent_type(payload)
internal = _scan_cp_state_files(payload.get('agent_id', ''), os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
print(json.dumps({
    'resolve': result,
    'internal_is_fail_closed': internal is _FAIL_CLOSED,
    'internal_is_str': isinstance(internal, str),
    'internal_value': internal if isinstance(internal, str) else None,
    'internal_is_none': internal is None,
}))
"""


def setup_env(spec_id, role, agent_id, is_running, agent_type, agent_index_value=None):
    p = tempfile.mkdtemp(prefix="qa-resolver-", dir="/tmp/qa-20260507-142952")
    os.makedirs(f"{p}/.claude/specs/{spec_id}", exist_ok=True)
    os.makedirs(f"{p}/.claude/dev-registry", exist_ok=True)
    cp = f"{p}/.claude/specs/{spec_id}/cp-state-{role}.json"
    with open(cp, "w") as f:
        json.dump({
            "agent_id": agent_id,
            "agent_type": agent_type,
            "is_running": is_running,
            # STALE-1 (2026-07-15): real production writers always pair
            # is_running=true with a fresh checked_in_at; a fixture missing
            # it no longer reflects on-disk reality and would trip the new
            # staleness fail-safe in hooks/lib/agent_resolver.py. Include a
            # fresh timestamp so this baseline still verifies the original
            # AC-3 contract's intent (active-cp-state / collision behavior)
            # rather than an now-unrealistic malformed-fixture shape.
            "checked_in_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "checkpoints": [],
        }, f)
    if agent_index_value:
        idx = f"{p}/.claude/dev-registry/agent-index.json"
        with open(idx, "w") as f:
            json.dump(agent_index_value, f)
    return p


def call_resolver(project_dir, payload):
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = project_dir
    proc = subprocess.run(
        ["python3", "-c", RUNNER_SRC, json.dumps(payload)],
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        return {"error": proc.stderr}
    return json.loads(proc.stdout.strip())


cases = []


# === AC-3.1 critical: INACTIVE ba cp-state with agent_id=AID, no agent-index, no subagent_type
#     Expected: resolver returns None (NOT 'ba')
def case_ac3_1():
    p = setup_env("spec-x", "ba", "aid-1", is_running=False, agent_type="ba")
    out = call_resolver(p, {"agent_id": "aid-1"})
    ok = out.get("resolve") is None and out.get("internal_is_none") is True
    return ("AC-3.1 inactive cp-state alone returns None", ok, out)


cases.append(case_ac3_1)


# === AC-3.2: INACTIVE ba cp-state + agent-index entry mapping AID->dev
#     Expected: resolver returns 'dev' (agent-index wins)
def case_ac3_2():
    p = setup_env("spec-x", "ba", "aid-2", is_running=False, agent_type="ba",
                  agent_index_value={"aid-2": "dev"})
    out = call_resolver(p, {"agent_id": "aid-2"})
    ok = out.get("resolve") == "dev"
    return ("AC-3.2 inactive cp-state + agent-index dev: resolver returns 'dev'", ok, out)


cases.append(case_ac3_2)


# === AC-3.3: ACTIVE ba cp-state, no agent-index. Expected: resolver returns 'ba'.
def case_ac3_3():
    p = setup_env("spec-x", "ba", "aid-3", is_running=True, agent_type="ba")
    out = call_resolver(p, {"agent_id": "aid-3"})
    ok = out.get("resolve") == "ba" and out.get("internal_is_str") and out.get("internal_value") == "ba"
    return ("AC-3.3 active cp-state alone returns 'ba'", ok, out)


cases.append(case_ac3_3)


# === AC-3.4: ACTIVE collision — two active cp-state files with different agent_types,
#     both agent_id=AID. Expected: _scan_cp_state_files returns _FAIL_CLOSED sentinel,
#     and _resolve_by_id returns None (do NOT consult agent-index even if it says 'dev').
def case_ac3_4():
    p = tempfile.mkdtemp(prefix="qa-resolver-collision-", dir="/tmp/qa-20260507-142952")
    os.makedirs(f"{p}/.claude/specs/spec-a", exist_ok=True)
    os.makedirs(f"{p}/.claude/specs/spec-b", exist_ok=True)
    os.makedirs(f"{p}/.claude/dev-registry", exist_ok=True)
    # STALE-1 (2026-07-15): fresh checked_in_at on both -- see setup_env comment.
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    with open(f"{p}/.claude/specs/spec-a/cp-state-ba.json", "w") as f:
        json.dump({"agent_id": "aid-collision", "agent_type": "ba", "is_running": True, "checked_in_at": now, "checkpoints": []}, f)
    with open(f"{p}/.claude/specs/spec-b/cp-state-qa.json", "w") as f:
        json.dump({"agent_id": "aid-collision", "agent_type": "qa", "is_running": True, "checked_in_at": now, "checkpoints": []}, f)
    with open(f"{p}/.claude/dev-registry/agent-index.json", "w") as f:
        json.dump({"aid-collision": "dev"}, f)
    out = call_resolver(p, {"agent_id": "aid-collision"})
    # Codex follow-up #2: collision must NOT fall through to agent-index
    ok = (
        out.get("resolve") is None
        and out.get("internal_is_fail_closed") is True
    )
    return ("AC-3.4 active cross-role collision = FAIL_CLOSED, agent-index NOT consulted", ok, out)


cases.append(case_ac3_4)


# === AC-3.5: subagent_type set directly takes priority over cp-state lookup.
def case_ac3_5():
    p = setup_env("spec-x", "ba", "aid-5", is_running=True, agent_type="ba")
    out = call_resolver(p, {"agent_id": "aid-5", "subagent_type": "qa"})
    ok = out.get("resolve") == "qa"
    return ("AC-3.5 subagent_type takes priority over cp-state", ok, out)


cases.append(case_ac3_5)


# === AC-3.6: no cp-state, no agent-index, agent_id present. Expected: None.
def case_ac3_6():
    p = tempfile.mkdtemp(prefix="qa-resolver-empty-", dir="/tmp/qa-20260507-142952")
    os.makedirs(f"{p}/.claude/specs", exist_ok=True)
    out = call_resolver(p, {"agent_id": "no-such-aid"})
    ok = out.get("resolve") is None
    return ("AC-3.6 no cp-state and no agent-index returns None", ok, out)


cases.append(case_ac3_6)


# === AC-3.7: legacy single-match-only INACTIVE pattern (the original Bug 3 trigger).
#     spec-20260506-203755 had a single inactive ba cp-state with agent_id=A, dev arrived
#     with same agent_id A and was misclassified ba. Verify resolver no longer returns 'ba'.
def case_ac3_7():
    p = setup_env("spec-old", "ba", "shared-aid-z", is_running=False, agent_type="ba")
    # The dev subagent arrives later: registers in agent-index as "dev"
    # but hasn't yet (the original bug 3 forensic shape was: agent-index entry IS there
    # but cp-state shadows it because of legacy fallback).
    idx = f"{p}/.claude/dev-registry/agent-index.json"
    with open(idx, "w") as f:
        json.dump({"shared-aid-z": "dev"}, f)
    out = call_resolver(p, {"agent_id": "shared-aid-z"})
    ok = out.get("resolve") == "dev"  # MUST resolve to dev, not ba
    return ("AC-3.7 LIVE BUG 3 SHAPE: inactive ba cp-state + agent-index dev = 'dev'", ok, out)


cases.append(case_ac3_7)


# === Run
passed = failed = 0
results = []
for c in cases:
    name, ok, detail = c()
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}")
    if not ok:
        print(f"    detail: {detail}")
    results.append({"case": name, "passed": ok, "detail": detail})
    if ok:
        passed += 1
    else:
        failed += 1

print(f"\nAC-3 summary: {passed} passed, {failed} failed of {len(cases)}")
with open("/tmp/qa-20260507-142952/ac3-results.json", "w") as f:
    json.dump({"passed": passed, "failed": failed, "total": len(cases), "results": results}, f, indent=2)
sys.exit(0 if failed == 0 else 1)
