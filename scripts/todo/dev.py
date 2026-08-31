#!/usr/bin/env python3
"""Canonical nine-phase checklist for the ordinary ``/dev`` workflow.

``get_todos`` must stay a single ``return`` of a **pure literal** list whose
items carry only ``content``/``activeForm``/``status``/``subagent_call``: the
codex-native harness reads this file as data (``ast.literal_eval``, never
imported or executed) and degrades to an empty step table on any violation,
which silently zeroes step-completion projection.  Legacy-step coverage
therefore lives in the module-level ``PHASE_COVERS_OLD_STEPS`` map instead of
inside the TodoWrite items.  The accounting regression consumes that map
without changing the generic todo validators: one initial TodoWrite + eight
combined boundaries + one final completion = ten calls, independent of lane
fan-out.
"""


# Legacy procedure steps covered by each macro phase (phase -> old step ids).
PHASE_COVERS_OLD_STEPS = {
    1: [1, 2, 3],
    2: [4, 5, 6],
    3: [7, 8],
    4: [9],
    5: [10, 11],
    6: [12],
    7: [13, 14, 16],
    8: [15],
    9: [17],
}


def get_todos():
    """Return the complete TodoWrite-compatible nine-phase checklist."""
    return [
        {
            "content": "Step 1: Intake and pre-BA discovery",
            "activeForm": "Step 1: Running intake and pre-BA discovery",
            "status": "pending",
        },
        {
            "content": "Step 2: BA contract, clarification and validation",
            "activeForm": "Step 2: Building and validating the BA contract",
            "status": "pending",
            "subagent_call": {"agent": "ba", "subagent_type": "ba"},
        },
        {
            "content": "Step 3: BA-QA and repair loop",
            "activeForm": "Step 3: Running BA-QA and its repair loop",
            "status": "pending",
            "subagent_call": {"agent": "qa", "subagent_type": "qa"},
        },
        {
            "content": "Step 4: Graphify enrichment",
            "activeForm": "Step 4: Running graphify enrichment",
            "status": "pending",
            "subagent_call": {"agent": "graphify", "subagent_type": "graphify"},
        },
        {
            "content": "Step 5: Dev fanout and canonical aggregation",
            "activeForm": "Step 5: Running Dev fanout and canonical aggregation",
            "status": "pending",
            "subagent_call": {"agent": "dev", "subagent_type": "dev"},
        },
        {
            "content": "Step 6: Validate Dev implementation",
            "activeForm": "Step 6: Validating the Dev implementation",
            "status": "pending",
        },
        {
            "content": "Step 7: QA, result processing and iteration",
            "activeForm": "Step 7: Running QA, processing results, and iterating",
            "status": "pending",
            "subagent_call": {"agent": "qa", "subagent_type": "qa"},
        },
        {
            "content": "Step 8: Settings reconciliation",
            "activeForm": "Step 8: Reconciling settings permissions",
            "status": "pending",
        },
        {
            "content": "Step 9: Completion report and spec/temp update",
            "activeForm": "Step 9: Generating the completion report and spec/temp update",
            "status": "pending",
        },
    ]


if __name__ == "__main__":
    import json

    print(json.dumps(get_todos(), indent=2, ensure_ascii=False))
