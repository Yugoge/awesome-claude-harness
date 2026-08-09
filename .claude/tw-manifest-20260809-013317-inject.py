#!/usr/bin/env python3
"""Write the per-task manifest and defensively upsert the global index.

Three sibling lanes upsert tests/generated/manifest.json concurrently, so the
index is read-modify-written under an exclusive flock, re-read fresh INSIDE the
lock, and every entry that is not this task's is asserted byte-identical to
what was read before the write is allowed to land.
"""
import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/dev/shm/dev-workspace/dot-claude")
TASK_ID = "20260809-013317-inject"
OUT_DIR = ROOT / "tests" / "generated" / TASK_ID
INDEX = ROOT / "tests" / "generated" / "manifest.json"
LOCK = ROOT / "tests" / "generated" / ".manifest-index.lock"
REL_MANIFEST = "tests/generated/%s/manifest.json" % TASK_ID

NOTES = (
    "COMPLEX / risk=high lane 'inject': the overnight continuation block must be delivered at a "
    "bounded cadence rather than on every prompt. 11 criteria, ac_uid RECOMPUTED AND VERIFIED for "
    "all 11 against the declared formula "
    "sha256(type+given+when+then+json.dumps(check,separators=(',',':'),ensure_ascii=False))[:16] - "
    "all 11 match the values in the AC file. "
    "CHECK VOCABULARY: the BA check objects use {kind, <kind-specific payload>} with kinds "
    "subprocess_repeat / table / discrimination / e2e_subprocess / boundary / isolation / "
    "measurement_record / conditional / scope_confinement / test_module / ordering_and_measurement, "
    "none of which are the four narrow canonical shapes (ui/api/data/hook) in agents/test-writer.md. "
    "Schema validation was applied against that richer vocabulary (kind present and non-empty plus "
    "at least one payload key, true for all 11), so NO entry is marked deferred_invalid_schema on "
    "the narrow-shape ground. "
    "DISCREPANCIES RECORDED, NOT ENCODED: review under this lane found four defects. Three are "
    "criterion-level and are carried into the affected skeletons as TEST_WRITER_DISCREPANCY comment "
    "blocks with the 2026-08-09 measurements that establish them, per the standing rule that where a "
    "criterion as written cannot discriminate, the skeleton is generated against the criterion's "
    "STATED INTENT and the discrepancy is reported rather than encoded as an assertion that cannot "
    "fail. D1 (AC-1): per_prompt_min_chars=1500 is unreachable inside the fixture AC-1 itself "
    "mandates, because _load_overnight_todos() resolves step labels from "
    "Path.home()/.claude/scripts/todo/dev-overnight.py and the fixture's mandated HOME=<tmp> makes "
    "that path non-existent; measured light block 893-1348 chars across four state shapes, all "
    "below the floor, versus 1873-2328 with step labels reachable. D2 (AC-1 cumulative window, "
    "AC-7 baselines): bounds pinned to constants that this lane's own recommended landing order "
    "invalidates - AC-7 names include-expander as the residual owner and "
    "docs/reference/monolith-split-plan.md:30 recommends landing that expander FIRST, which shrinks "
    "commands/dev-overnight.md; AC-7's baseline_boundary_chars=127846 and "
    "baseline_steady_state_chars=2497 are ALREADY stale against the current worktree (measured "
    "127656 and 2274-2328), and AC-1's cumulative_min=130000 has only 6752 chars of margin while "
    "the explicitly-enumerated duplicate blocks in this one file total ~4665 chars. D3 (AC-8, "
    "inherited by AC-3 rows 3.3/3.4): the R-a/R-b conditional's two branches exhaust the outcome "
    "space, so if the implemented reading is inferred from observed behaviour the criterion cannot "
    "fail; the skeleton directs that the reading be pinned to an independently-readable declaration "
    "and the behaviour asserted against it, and notes that self_heal_pointer_equals / "
    "self_heal_pointer_hardcoded=false are the already-falsifiable half. "
    "UNCOVERED RISK G1: the fourth defect is a COVERAGE GAP with no owning criterion - nothing in "
    "AC-1..AC-11 checks that the delivery marker can actually be written at its chosen location. "
    "AC-11 covers a transient marker-write failure (exit 0, next prompt heavy) but not a PERSISTENT "
    "one, under which every prompt re-delivers heavy, the lane's benefit is exactly zero, the "
    "process still exits 0 and all eleven criteria still pass because each builds its own writable "
    "temp fixture. G1 is RECORDED here and in the report with a recommended criterion; it is "
    "deliberately NOT generated as a skeleton, because adding a criterion absent from the AC file "
    "is outside the test-writer authority chain. The BA owns adopting it. "
    "SCOPE: no production code was written, no Playwright run, no live API call. The generated tree "
    "is opt-in behind the `generated` pytest marker (root conftest.py), so the default suite is "
    "unaffected; `pytest tests/generated/20260809-013317-inject -m generated` reports 11 xfailed, "
    "which is the correct TEST_INCOMPLETE signal for QA Phase 5. The global index "
    "tests/generated/manifest.json was upserted under an exclusive flock with every other lane's "
    "entry asserted byte-identical."
)


def write_task_manifest():
    active = json.loads((OUT_DIR / "_active.json").read_text())
    manifest = {
        "schema_version": "1.1",
        "task_id": TASK_ID,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_acceptance_criteria":
            "docs/dev/acceptance-criteria-20260809-013317-inject.json",
        "complexity_tier": "COMPLEX",
        "risk_level": "high",
        "lane": "inject",
        "trigger_gate": {
            "complexity_tier": "COMPLEX",
            "risk_level": "high",
            "fired": True,
            "rule": "runs when complexity_tier >= STANDARD OR risk_level == high; both hold",
        },
        "notes": NOTES,
        "active_tests": active,
        "archived_tests": [],
    }
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def upsert_index():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            # Re-read FRESH inside the lock - a sibling lane may have landed
            # between our earlier read and now.
            before_raw = INDEX.read_text(encoding="utf-8")
            doc = json.loads(before_raw)
            tasks = doc.get("tasks", [])
            others_before = [t for t in tasks if t.get("task_id") != TASK_ID]

            entry = {"task_id": TASK_ID, "manifest_path": REL_MANIFEST}
            found = False
            for i, t in enumerate(tasks):
                if t.get("task_id") == TASK_ID:
                    tasks[i] = entry
                    found = True
                    break
            if not found:
                tasks.append(entry)
            doc["tasks"] = tasks

            # Every entry that is not ours must survive byte-identically.
            others_after = [t for t in doc["tasks"] if t.get("task_id") != TASK_ID]
            assert others_after == others_before, "sibling-lane entries were mutated"
            assert json.dumps(others_after, sort_keys=False) == \
                json.dumps(others_before, sort_keys=False), "sibling-lane bytes differ"
            assert doc.get("kind") == "index", "global manifest is not an index"
            assert "active_tests" not in doc, "global index must not carry active_tests"

            payload = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
            fd, tmp = tempfile.mkstemp(dir=str(INDEX.parent), prefix=".manifest-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, INDEX)
            except BaseException:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
            return {"action": "updated" if found else "appended",
                    "siblings_preserved": len(others_before)}
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    m = write_task_manifest()
    r = upsert_index()
    print(json.dumps({"active_tests": len(m["active_tests"]), "index": r}, indent=2))
