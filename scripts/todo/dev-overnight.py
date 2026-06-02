#!/usr/bin/env python3
"""
Preloaded TodoList for /dev-overnight workflow.

Autonomous overnight development loop with continuous exploration and
fix cycles. State file is created by the UserPromptSubmit hook; Step 1
handles worktree setup.

PM is invoked 3 times per cycle: Plan (Step 2), Triage (Step 4),
Retro (Step 20). Step 2-5 form the exploration-phase contract slots
that cycle-contract.json's required_calls bookmark independently.
"""

# (label, content, activeForm, extra_meta) tuples for each step
_STEPS = [
    ("1", "Create worktree (first run only)", "Creating worktree", None),
    (
        "2",
        "PM Plan",
        "PM planning",
        {"subagent_call": {"agent": "pm", "subagent_type": "pm", "mode": "PLAN"}},
    ),
    (
        "3",
        "Run specialist subagents (per PM Plan)",
        "Running specialist subagents",
        None,
    ),
    (
        "4",
        "PM Triage",
        "PM triaging",
        {"subagent_call": {"agent": "pm", "subagent_type": "pm", "mode": "TRIAGE"}},
    ),
    ("5", "Create overnight spec files", "Creating overnight spec files", None),
    ("6", "Create parallel pipelines from PM triage", "Creating parallel pipelines from PM triage", None),
    ("7", "Convert focus to QA verification criteria", "Converting focus to QA verification criteria", None),
    (
        "8",
        "Run BA subagents (parallel)",
        "Running BA subagents in parallel",
        {"subagent_call": {"agent": "ba", "subagent_type": "ba"}},
    ),
    ("9", "Validate BA outputs", "Validating BA outputs", None),
    (
        "10",
        "QA validates BA conclusions (parallel)",
        "QA validating BA conclusions",
        {"subagent_call": {"agent": "qa", "subagent_type": "qa"}},
    ),
    ("11", "BA-QA iteration loop (if QA rejects BA)", "Iterating BA analysis based on QA objections", None),
    (
        "11g",
        "Graphify Dev-dispatch precondition (enrich before every Dev dispatch)",
        "Running graphify enrichment before Dev dispatch",
        {"subagent_call": {"agent": "graphify", "subagent_type": "graphify"}},
    ),
    (
        "12",
        "Run Dev subagents (parallel)",
        "Running Dev subagents in parallel",
        {"subagent_call": {"agent": "dev", "subagent_type": "dev"}},
    ),
    ("13", "Validate Dev implementations", "Validating Dev implementations", None),
    (
        "14",
        "Prepare QA environment (rebuild Docker + verification plans)",
        "Preparing QA environment and verification plans",
        None,
    ),
    (
        "15",
        "Run QA subagents (parallel)",
        "Running QA subagents in parallel",
        {"subagent_call": {"agent": "qa", "subagent_type": "qa"}},
    ),
    ("16", "Process QA results", "Processing QA results", None),
    ("17", "Run iteration loops for failed pipelines", "Running iteration loops for failed pipelines", None),
    ("18", "Update settings.json permissions (aggregated)", "Updating settings.json permissions", None),
    ("19", "Log cycle results and check time", "Logging cycle results and checking time", None),
    (
        "20",
        "PM Retrospective (cycle summary + next-cycle handoff)",
        "Running PM Retrospective",
        {"subagent_call": {"agent": "pm", "subagent_type": "pm", "mode": "RETRO"}},
    ),
    ("21", "Generate summary report or loop", "Generating summary report or looping", None),
]


def _build_step(label, desc, active, meta):
    """Build a single todo item dict from step tuple."""
    item = {
        "content": f"Step {label}: {desc}",
        "activeForm": f"Step {label}: {active}",
        "status": "pending",
    }
    if meta:
        item.update(meta)
    return item


def get_todos():
    """Return todo items for the dev-overnight workflow (21 integer steps + the
    letter-suffix Step 11g graphify Dev-dispatch precondition; the letter-suffix
    avoids cascading the integer Steps 12-21 and their contract step-ids)."""
    return [
        _build_step(label, desc, active, meta)
        for label, desc, active, meta in _STEPS
    ]


if __name__ == "__main__":
    import json
    print(json.dumps(get_todos(), indent=2, ensure_ascii=False))
