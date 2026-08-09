#!/usr/bin/env python3
"""Generator for tests/generated/20260809-013317-inject/ skeletons.

Run once by the test-writer subagent. Not part of the shipped test suite.
"""
import json
import os
import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/dev/shm/dev-workspace/dot-claude")
TASK_ID = "20260809-013317-inject"
AC_PATH = "docs/dev/acceptance-criteria-20260809-013317-inject.json"
OUT_DIR = ROOT / "tests" / "generated" / TASK_ID

SUMMARY = {
    "AC-1": "5-prompt cadence - prompt 1 heavy with spec, prompts 2-5 light, per-prompt and cumulative bounds",
    "AC-2": "11-row marker-state table - heavy in every row except the exact four-field match, no exception escapes",
    "AC-3": "validity-key discrimination - 4 mutations re-deliver, control and the non-isCompactSummary negative do not",
    "AC-4": "e2e subprocess - exit 0, one OVERNIGHT CONTINUATION, spec on invocation 1 only, codex runtime silent",
    "AC-5": "cycle-advance boundary - full spec re-delivered, header Cycle N+2, marker rewritten to N+1",
    "AC-6": "session isolation - a foreign session does not consume the marker, filename/field mismatch rejected",
    "AC-7": "measurement record for P in {1,2,3,5,10,20} with requirement_c_verdict, no 'requirement (C) delivered' claim",
    "AC-8": "context-reset conditional (R-a / R-b) and the self-heal pointer equals the read_command_spec resolution",
    "AC-9": "scope confinement - only the 3 permitted symbols edited, 2 byte-unchanged, only 2 files touched",
    "AC-10": "the new test module runs clean and covers AC-1..AC-6 and AC-11 with HOME in a temp dir",
    "AC-11": "ordering - no marker on emission failure, a failing marker write leaves exit 0 and re-delivers",
}

# ---------------------------------------------------------------------------
# Per-AC test-writer annotations. Only the four criteria carrying a recorded
# discrepancy get one; every other skeleton is generated straight from the AC.
# ---------------------------------------------------------------------------
DISCREPANCY = {
    "AC-1": {
        "id": "D1",
        "defect": "per_prompt_min_chars floor is unreachable inside the fixture this criterion itself mandates",
        "mechanism": (
            "build_overnight_continuation() line 596 renders 'Canonical steps: {step_labels}' from "
            "_load_overnight_todos() (line 566), which loads its module from "
            "$CLAUDE_DEV_OVERNIGHT_TODO or, unset, from Path.home()/'.claude/scripts/todo/dev-overnight.py'. "
            "This criterion's GIVEN mandates 'HOME set to a temp dir', which makes that path non-existent, "
            "so the loader returns [] and step_labels collapses to the empty string. The single largest "
            "contributor to the light block (~980 chars) is removed by the fixture itself."
        ),
        "measured_2026_08_09": {
            "note": "light block = full block minus the '--- COMMAND SPECIFICATION ---\\n\\n<spec>\\n\\n' section",
            "step_labels_unreachable_fixture_as_mandated": {
                "in_place_with_env_helper": 1294,
                "in_place_without_env_helper": 1107,
                "validated_worktree": 1348,
                "hard_abort_no_worktree": 893,
                "verdict": "ALL FOUR below the 1500 floor",
            },
            "step_labels_reachable_CLAUDE_DEV_OVERNIGHT_TODO_set": {
                "in_place_with_env_helper": 2274,
                "in_place_without_env_helper": 2087,
                "validated_worktree": 2328,
                "hard_abort_no_worktree": 1873,
                "verdict": "ALL FOUR inside [1500, 3000]",
            },
            "divergence_from_review": (
                "The review reported the floor breached in two of three state shapes. Measured here it is "
                "breached in FOUR of four, which is strictly stronger. The shape set differs (this "
                "measurement splits in_place by env_helper presence and includes the hard-abort shape); "
                "the mechanism and the conclusion are the same."
            ),
        },
        "resolution": (
            "The floor is a proxy for 'the light block is not degenerate or truncated'. Assert that intent "
            "through the five required marker strings (which ARE discriminating and ARE in the criterion) "
            "and through per_prompt_max_chars. Do NOT encode a >= 1500 assertion that the mandated fixture "
            "guarantees will fail. Either the fixture must point CLAUDE_DEV_OVERNIGHT_TODO at the repo's "
            "scripts/todo/dev-overnight.py so step labels resolve, or the floor must be re-derived from a "
            "measurement taken inside the fixture actually used. Whichever is chosen must be recorded."
        ),
    },
    "AC-1-cumulative": {
        "id": "D2",
        "defect": "cumulative_min / cumulative_max are pinned to constants that this lane's own recommended landing order invalidates",
        "mechanism": (
            "The cumulative window [130000, 145000] is dominated by the single boundary block, which is "
            "dominated by the dev-overnight spec string. AC-7 names 'include-expander' as the residual "
            "owner of the boundary-block gap, and docs/reference/monolith-split-plan.md:30 recommends "
            "building that expander FIRST as the safe move for the markdown monoliths, with MD-1 (line 65) "
            "making it the mechanism by which extracted blocks are re-injected. Landing it and collapsing "
            "the duplicated blocks enumerated at monolith-split-plan.md:233-237 shrinks commands/"
            "dev-overnight.md - and therefore drives cumulative DOWN through the floor, failing this "
            "criterion for making the block smaller, which is the lane's entire purpose."
        ),
        "measured_2026_08_09": {
            "read_command_spec_dev_overnight_chars": 125349,
            "commands_dev_overnight_md_raw_chars": 125528,
            "boundary_block_chars": 127656,
            "cumulative_5_prompts_chars": 136752,
            "margin_above_cumulative_min": 6752,
            "named_dedup_candidates_in_this_file_chars": "~4665 non-overlapping (Four Contracts 3846 + JSON Storage Policy ~819)",
            "verdict": "the explicitly-enumerated duplicates alone consume ~69% of the available margin",
        },
        "resolution": (
            "Derive the expected window at run time from the spec string actually resolved by "
            "read_command_spec('dev-overnight') in the fixture under test, and assert the RATIO the lane "
            "is about (one boundary block plus N-1 light blocks, light << heavy), not an absolute char "
            "count frozen against one repo revision. Keep the literal constants recorded as the "
            "2026-08-09 measurement, not as pass/fail gates."
        ),
    },
    "AC-7": {
        "id": "D2",
        "defect": "baseline constants are already stale and are invalidated by the recommended landing order",
        "mechanism": (
            "Same root cause as D2 on AC-1: both baselines are frozen against one revision of "
            "commands/dev-overnight.md, and the include-expander that AC-7 itself names as the residual "
            "owner changes that file."
        ),
        "measured_2026_08_09": {
            "baseline_boundary_chars_as_written": 127846,
            "boundary_measured": 127656,
            "boundary_drift": -190,
            "baseline_steady_state_chars_as_written": 2497,
            "steady_state_measured": "2274 (in_place+helper) .. 2328 (validated worktree)",
            "steady_state_drift": "-169 .. -223",
            "verdict": "both pinned baselines are already wrong against the current worktree, before the lane lands",
        },
        "resolution": (
            "This criterion is a measurement_record, so the honest form is to RE-MEASURE the baseline "
            "inside the run and record both the fresh reading and the AC's frozen constant, flagging "
            "drift. Do not gate pass/fail on equality with 127846 / 2497. The four "
            "requirement_c_verdict fields, the forbidden_claims strings and must_name_residual_owner ARE "
            "discriminating and must be asserted as written."
        ),
    },
    "AC-8": {
        "id": "D3",
        "defect": "the conditional as written cannot discriminate - its two branches exhaust the outcome space, so no observation can fail it",
        "mechanism": (
            "The GIVEN is 'the implemented reading (R-a or R-b per the user decision on M4)' and the check "
            "is {R-b_expect: heavy, R-a_expect: light_only}. If the test infers which reading was "
            "implemented from the behaviour it observes, then observing heavy classifies the run as R-b "
            "and passes, and observing light_only classifies it as R-a and passes. Every possible outcome "
            "is a pass. The same defect propagates to AC-3 rows 3.3 (conditional_on 'M4 / reading R-b') "
            "and 3.4 (conditional_on 'S1'), which become vacuous if their condition is inferred from the "
            "behaviour rather than read independently."
        ),
        "resolution": (
            "Split the criterion at its seam. (1) The implemented reading must be pinned to a fact "
            "readable INDEPENDENTLY of the behaviour under test - a declared module-level constant or "
            "decision record in hooks/prompt-workflow.py naming R-a or R-b. (2) The behaviour is then "
            "asserted AGAINST that declaration, so a hook that declares R-b and behaves like R-a FAILS. "
            "(3) The R-a branch's report obligations are asserted only when the declaration says R-a. "
            "(4) self_heal_pointer_equals and self_heal_pointer_hardcoded=false are ALREADY "
            "discriminating and must be asserted unconditionally - they are the falsifiable half of this "
            "criterion as written."
        ),
    },
}

# The uncovered risk. Deliberately NOT rendered as a skeleton: the authority
# chain forbids adding criteria absent from the AC file. Recorded in the
# manifest and the report so the BA can adopt it in a revision.
UNCOVERED_RISK = {
    "id": "G1",
    "gap": "no criterion checks that the delivery marker can actually be written at its chosen location",
    "why_it_matters": (
        "AC-11 asserts marker_write_fails -> {exit_code: 0, next_prompt: heavy}, which is correct "
        "fail-open behaviour for a TRANSIENT failure. Nothing anywhere in AC-1..AC-11 covers a "
        "PERSISTENT one. If the chosen marker location is not writable in the real deployment - a "
        "read-only .claude/, wrong ownership, a full tmpfs, or PROJECT_DIR unset so the marker lands "
        "somewhere unintended - then every prompt re-delivers the heavy block, the lane's entire "
        "benefit is exactly zero, the process still exits 0, and all eleven criteria still pass, "
        "because each one builds its own temp fixture in which the location IS writable. The "
        "regression is invisible to the suite by construction."
    ),
    "recommended_criterion": (
        "At the marker's chosen location, on the REAL project dir rather than a temp fixture: assert "
        "the directory exists and is writable, and that a marker write followed by a read-back "
        "round-trips. Additionally, assert that two consecutive deliveries under identical validity "
        "keys produce exactly one heavy block - a positive check that the cadence is actually in "
        "effect where the hook really runs, not merely that it fails open when it is not."
    ),
    "disposition": "recorded, not generated - adding an AC-12 is outside the test-writer authority chain",
}

HEADER_TMPL = """\
# Auto-generated by agents/test-writer.md from {ac_path}
# AC ID: {ac_id}  ac_uid: {ac_uid}  type: {ac_type}
# Dev is free to REPLACE the body of {fn}() with a real
# implementation that asserts the GIVEN/WHEN/THEN behaviour. The metadata
# above (AC_UID, AC_TYPE, docstring) MUST be preserved verbatim so QA can
# trace each test back to its source AC entry.
#
# Lane: inject - the overnight continuation block must be delivered at a
# bounded cadence rather than on every prompt.
# complexity_tier: COMPLEX   risk_level: high
"""

BODY_TMPL = '''

import pytest

AC_UID = "{ac_uid}"
AC_TYPE = "{ac_type}"

# Verbatim copy of this criterion's `check` object from the AC file. Dev must
# not edit it; it is the manifest's hook_check and QA reads it for traceability.
CHECK = {check}
{extra}

def {fn}():
    """
    GIVEN: {given}
    WHEN:  {when}
    THEN:  {then}
    """
    # TODO(dev): replace the line below with the real test body. While the
    # TEST_INCOMPLETE sentinel is present the test will hard-fail, marking
    # the AC as unimplemented for QA Phase 5.
    pytest.fail(f"TEST_INCOMPLETE: {{AC_UID}} — {summary}")
'''


def render_note(banner, payload):
    text = json.dumps(payload, indent=4, ensure_ascii=False)
    return "\n# " + banner + "\n" + "\n".join(
        ("# " + line).rstrip() for line in text.splitlines()
    ) + "\n"


def pyliteral(obj):
    """Render a JSON-derived object as readable, deterministic Python."""
    raw = json.dumps(obj, indent=4, ensure_ascii=False)
    raw = re.sub(r"\btrue\b", "True", raw)
    raw = re.sub(r"\bfalse\b", "False", raw)
    raw = re.sub(r"\bnull\b", "None", raw)
    return raw


def main():
    ac_doc = json.loads((ROOT / AC_PATH).read_text())
    items = ac_doc["acceptance_criteria"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    active = []
    created = []
    for item in items:
        ac_id = item["id"]
        norm = re.sub(r"[^0-9A-Za-z_]", "_", ac_id)
        fn = "test_" + norm
        fname = "test_%s_%s.py" % (norm, item["ac_uid"])
        rel = "tests/generated/%s/%s" % (TASK_ID, fname)

        header = HEADER_TMPL.format(
            ac_path=AC_PATH, ac_id=ac_id, ac_uid=item["ac_uid"],
            ac_type=item["type"], fn=fn,
        )

        notes = []
        annotations = []
        if ac_id == "AC-1":
            notes.append(render_note(
                "TEST-WRITER DISCREPANCY D1 - DO NOT ENCODE per_prompt_min_chars AS AN ASSERTION",
                DISCREPANCY["AC-1"]))
            notes.append(render_note(
                "TEST-WRITER DISCREPANCY D2 - cumulative bounds are order-dependent",
                DISCREPANCY["AC-1-cumulative"]))
            annotations = ["D1", "D2"]
        elif ac_id == "AC-7":
            notes.append(render_note(
                "TEST-WRITER DISCREPANCY D2 - baselines already stale, re-measure instead of pinning",
                DISCREPANCY["AC-7"]))
            annotations = ["D2"]
        elif ac_id == "AC-8":
            notes.append(render_note(
                "TEST-WRITER DISCREPANCY D3 - this conditional cannot fail as written",
                DISCREPANCY["AC-8"]))
            annotations = ["D3"]
        elif ac_id == "AC-3":
            notes.append(render_note(
                "TEST-WRITER NOTE - rows 3.3 and 3.4 inherit discrepancy D3 (see AC-8's skeleton)",
                {
                    "id": "D3-inherited",
                    "rows": ["3.3 (conditional_on 'M4 / reading R-b')", "3.4 (conditional_on 'S1')"],
                    "defect": (
                        "a row whose condition is inferred from the behaviour it is meant to test "
                        "cannot fail: skipping on 'the condition did not hold' and passing on 'it "
                        "did' covers the whole outcome space"
                    ),
                    "resolution": (
                        "read the condition from the independent declaration required by D3's "
                        "resolution on AC-8, then run the row unconditionally against it. AC-10 "
                        "requires all 4 mutations plus the negative row to be COVERED, so neither "
                        "row may be silently skipped."
                    ),
                }))
            annotations = ["D3-inherited"]
        elif ac_id == "AC-11":
            notes.append(render_note(
                "TEST-WRITER NOTE - uncovered risk G1 sits adjacent to this criterion",
                UNCOVERED_RISK))
            annotations = ["G1-adjacent"]

        extra = "".join(notes)
        if annotations:
            extra += "\nTEST_WRITER_ANNOTATIONS = %s\n" % pyliteral(annotations)

        source = header + BODY_TMPL.format(
            ac_uid=item["ac_uid"], ac_type=item["type"], fn=fn,
            check=pyliteral(item["check"]), extra=extra,
            given=item["given"], when=item["when"], then=item["then"],
            summary=SUMMARY[ac_id],
        )
        (OUT_DIR / fname).write_text(source, encoding="utf-8")
        created.append(rel)

        entry = {
            "task_id": TASK_ID,
            "ac_id": ac_id,
            "ac_uid": item["ac_uid"],
            "type": item["type"],
            "file": rel,
            "status": "active",
            "skeleton_functions": [fn],
            "check_kind": item["check"].get("kind"),
            "schema_validation": {
                # The four narrow canonical shapes in agents/test-writer.md
                # (ui/api/data/hook) do not describe these check objects: the BA
                # uses a richer {kind, <kind-specific payload>} vocabulary. Every
                # entry was validated against THAT vocabulary - kind present and
                # non-empty, plus at least one kind-specific payload key - so no
                # entry is marked deferred_invalid_schema on the narrow-shape
                # ground alone.
                "vocabulary": "ba_extended",
                "kind_present": bool(item["check"].get("kind")),
                "payload_keys": len([k for k in item["check"] if k != "kind"]),
                "result": (
                    "valid"
                    if item["check"].get("kind")
                    and len([k for k in item["check"] if k != "kind"]) > 0
                    else "deferred_invalid_schema"
                ),
            },
            "hook_check": item["check"],
        }
        if annotations:
            entry["test_writer_annotations"] = annotations
        active.append(entry)

    print(json.dumps({"created": created, "count": len(created)}, indent=2))
    (OUT_DIR / "_active.json").write_text(json.dumps(active, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
