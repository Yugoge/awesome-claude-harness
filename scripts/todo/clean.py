#!/usr/bin/env python3
"""
Preloaded TodoList for /clean workflow.

Aggressive project cleanup with orchestrated multi-agent workflow.
"""


def get_todos():
    """
    Return list of todo items for TodoWrite.

    Returns:
        list[dict]: Todo items with content, activeForm, status
    """
    return [
        {"content": "Step 1: Initialize workflow", "activeForm": "Step 1: Initializing workflow", "status": "pending"},
        {"content": "Step 2: Scan project structure", "activeForm": "Step 2: Scanning project structure", "status": "pending"},
        {"content": "Step 3: Build inspection context", "activeForm": "Step 3: Building inspection context", "status": "pending"},
        {"content": "Step 4: Rule inspection and README updates", "activeForm": "Step 4: Inspecting rules and updating READMEs", "status": "pending"},
        {"content": "Step 5: Invoke cleanliness inspector", "activeForm": "Step 5: Invoking cleanliness inspector", "status": "pending", "subagent_call": {"agent": "cleanliness-inspector", "subagent_type": "cleanliness-inspector"}},
        {"content": "Step 6: Invoke style inspector", "activeForm": "Step 6: Invoking style inspector", "status": "pending", "subagent_call": {"agent": "style-inspector", "subagent_type": "style-inspector"}},
        {"content": "Step 7: Plan style inspection", "activeForm": "Step 7: Planning style inspection", "status": "pending"},
        {"content": "Step 8: Launch parallel style inspectors", "activeForm": "Step 8: Launching parallel style inspectors", "status": "pending"},
        {"content": "Step 9: Collect and merge results", "activeForm": "Step 9: Collecting and merging results", "status": "pending"},
        {"content": "Step 10: Verify inspection coverage", "activeForm": "Step 10: Verifying inspection coverage", "status": "pending"},
        {"content": "Step 11: Merge inspection reports", "activeForm": "Step 11: Merging inspection reports", "status": "pending"},
        {"content": "Step 12: Present combined report to user", "activeForm": "Step 12: Presenting combined report to user", "status": "pending"},
        {"content": "Step 13: Collect user approval", "activeForm": "Step 13: Collecting user approval", "status": "pending"},
        {"content": "Step 14: Verify cleanup completeness (if Option 1)", "activeForm": "Step 14: Verifying cleanup completeness", "status": "pending"},
        {"content": "Step 15: Create safety checkpoint", "activeForm": "Step 15: Creating safety checkpoint", "status": "pending"},
        {"content": "Step 16: Invoke cleaner with approvals", "activeForm": "Step 16: Invoking cleaner with approvals", "status": "pending", "subagent_call": {"agent": "cleaner", "subagent_type": "cleaner"}},
        {"content": "Step 17: Verify cleanup results", "activeForm": "Step 17: Verifying cleanup results", "status": "pending"},
        {"content": "Step 18: Generate completion report", "activeForm": "Step 18: Generating completion report", "status": "pending"}
    ]



if __name__ == "__main__":
    # CLI: print todos as formatted list
    import json
    todos = get_todos()
    print(json.dumps(todos, indent=2, ensure_ascii=False))
