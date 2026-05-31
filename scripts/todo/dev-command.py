#!/usr/bin/env python3
"""Preloaded TodoList for /dev-command workflow.

This todo script generates workflow steps for the BA-delegated dev-command workflow
with command development best practices.
"""


# (label, content, activeForm, extra_meta) tuples for each step
# graphify integration adds two advisory items, folded in place as Step 2 (pre-BA) and Step 9 (enrichment)
_STEPS = [
    ("1", "Parse development requirement", "Parsing development requirement", None),
    # graphify pre-BA hydrator (advisory) — folded in place as Step 2
    ("2", "Graphify pre-BA: run graphify-query.py Bash hydrator (advisory)", "Running graphify-query.py Bash hydrator", None),
    ("3", "Consult specialists (optional)", "Consulting specialists", None),
    ("4", "Delegate to BA subagent", "Delegating to BA subagent", {"subagent_call": {"agent": "ba", "subagent_type": "ba"}}),
    ("5", "BA clarification loop (if needed)", "Running BA clarification loop", None),
    ("6", "Validate BA output", "Validating BA output", None),
    ("7", "QA validates BA conclusions", "QA validating BA conclusions", {"subagent_call": {"agent": "qa", "subagent_type": "qa"}}),
    ("8", "BA-QA iteration loop (if QA rejects BA)", "Iterating BA analysis based on QA objections", None),
    # graphify enrichment subagent (advisory) — folded in place as Step 9
    ("9", "Graphify enrichment: dispatch graphify subagent (advisory)", "Dispatching graphify subagent", {"subagent_call": {"agent": "graphify", "subagent_type": "graphify"}}),
    ("10", "Delegate to dev subagent", "Delegating to dev subagent", {"subagent_call": {"agent": "dev", "subagent_type": "dev"}}),
    ("11", "Validate dev implementation", "Validating dev implementation", None),
    ("12", "Delegate to QA subagent", "Delegating to QA subagent", {"subagent_call": {"agent": "qa", "subagent_type": "qa"}}),
    ("13", "Process QA results", "Processing QA results", None),
    ("14", "Update settings.json permissions", "Updating settings.json permissions", None),
    ("15", "Iteration loop (if QA fails)", "Executing iteration loop", None),
    ("16", "Generate completion report", "Generating completion report", None),
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
    """Return workflow steps as TodoWrite-compatible list."""
    return [
        _build_step(label, desc, active, meta)
        for label, desc, active, meta in _STEPS
    ]


if __name__ == "__main__":
    import json
    print(json.dumps(get_todos(), indent=2, ensure_ascii=False))
