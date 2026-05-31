#!/usr/bin/env python3
"""
Preloaded TodoList for /dev workflow.

BA-delegated development workflow with quality gates.
"""


def get_todos():
    """
    Return list of todo items for TodoWrite.

    Returns:
        list[dict]: Todo items with content, activeForm, status
    """
    return [
        {"content": "Step 1: Parse development requirement", "activeForm": "Step 1: Parsing development requirement", "status": "pending"},
        # graphify pre-BA Bash hydrator (advisory) — Step 2, runs after Parse before specialists
        {"content": "Step 2: Graphify pre-BA: run graphify-query.py Bash hydrator (advisory)", "activeForm": "Step 2: Running graphify-query.py Bash hydrator", "status": "pending"},
        {"content": "Step 3: Consult specialists (optional)", "activeForm": "Step 3: Consulting specialists", "status": "pending"},
        {"content": "Step 4: Delegate to BA subagent", "activeForm": "Step 4: Delegating to BA subagent", "status": "pending", "subagent_call": {"agent": "ba", "subagent_type": "ba"}},
        {"content": "Step 5: BA clarification loop (if needed)", "activeForm": "Step 5: Running BA clarification loop", "status": "pending"},
        {"content": "Step 6: Validate BA output", "activeForm": "Step 6: Validating BA output", "status": "pending"},
        {"content": "Step 7: QA validates BA conclusions", "activeForm": "Step 7: QA validating BA conclusions", "status": "pending", "subagent_call": {"agent": "qa", "subagent_type": "qa"}},
        {"content": "Step 8: BA-QA iteration loop (if QA rejects BA)", "activeForm": "Step 8: Iterating BA analysis based on QA objections", "status": "pending"},
        # graphify enrichment subagent (advisory) — folded in place as Step 9
        {"content": "Step 9: Graphify enrichment: dispatch graphify subagent (advisory)", "activeForm": "Step 9: Dispatching graphify subagent", "status": "pending", "subagent_call": {"agent": "graphify", "subagent_type": "graphify"}},
        {"content": "Step 10: Delegate to dev subagent", "activeForm": "Step 10: Delegating to dev subagent", "status": "pending", "subagent_call": {"agent": "dev", "subagent_type": "dev"}},
        {"content": "Step 11: Write canonical aggregate dev-report (parallel-dev only)", "activeForm": "Step 11: Writing canonical aggregate dev-report", "status": "pending"},
        {"content": "Step 12: Validate dev implementation", "activeForm": "Step 12: Validating dev implementation", "status": "pending"},
        {"content": "Step 13: Delegate to QA subagent", "activeForm": "Step 13: Delegating to QA subagent", "status": "pending", "subagent_call": {"agent": "qa", "subagent_type": "qa"}},
        {"content": "Step 14: Process QA results", "activeForm": "Step 14: Processing QA results", "status": "pending"},
        {"content": "Step 15: Update settings.json permissions", "activeForm": "Step 15: Updating settings.json permissions", "status": "pending"},
        {"content": "Step 16: Iteration loop (if QA fails)", "activeForm": "Step 16: Iterating based on QA feedback", "status": "pending"},
        {"content": "Step 17: Generate completion report and spec/temp update", "activeForm": "Step 17: Generating completion report and spec/temp update", "status": "pending"}
    ]



if __name__ == "__main__":
    # CLI: print todos as formatted list
    import json
    todos = get_todos()
    print(json.dumps(todos, indent=2, ensure_ascii=False))
