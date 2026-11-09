#!/usr/bin/env python3
"""
Preloaded TodoList for /test workflow.

Test validation workflow with edge case detection and quality enforcement.
"""


def get_todos():
    """
    Return list of todo items for TodoWrite.

    Returns:
        list[dict]: Todo items with content, activeForm, status
    """
    return [
        {"content": "Step 1: Initialize workflow", "activeForm": "Step 1: Initializing workflow", "status": "pending"},
        {"content": "Step 2: Analyze git history for edge cases", "activeForm": "Step 2: Analyzing git history for edge cases", "status": "pending"},
        {"content": "Step 3: Migrate test/ to tests/ (if needed)", "activeForm": "Step 3: Migrating test/ to tests/", "status": "pending"},
        {"content": "Step 4: Cleanup tests/ from git history", "activeForm": "Step 4: Cleaning up tests/ from git history", "status": "pending"},
        {"content": "Step 5: Check test folder exists", "activeForm": "Step 5: Checking test folder", "status": "pending"},
        {"content": "Step 6: Discover validators", "activeForm": "Step 6: Discovering validators", "status": "pending"},
        {"content": "Step 7: Build validation context", "activeForm": "Step 7: Building validation context", "status": "pending"},
        {"content": "Step 8: Invoke test validator", "activeForm": "Step 8: Invoking test validator", "status": "pending"},
        {"content": "Step 9: Process validation results", "activeForm": "Step 9: Processing validation results", "status": "pending"},
        {"content": "Step 10: Build execution context", "activeForm": "Step 10: Building execution context", "status": "pending"},
        {"content": "Step 11: Create safety checkpoint", "activeForm": "Step 11: Creating safety checkpoint", "status": "pending"},
        {"content": "Step 12: Invoke test executor", "activeForm": "Step 12: Invoking test executor", "status": "pending"},
        {"content": "Step 13: Process execution results", "activeForm": "Step 13: Processing execution results", "status": "pending"},
        {"content": "Step 14: Present test failures to user", "activeForm": "Step 14: Presenting test failures", "status": "pending"},
        {"content": "Step 15: Fix failures and re-run", "activeForm": "Step 15: Fixing failures and re-running", "status": "pending"},
        {"content": "Step 16: Generate completion report", "activeForm": "Step 16: Generating completion report", "status": "pending"}
    ]



if __name__ == "__main__":
    # CLI: print todos as formatted list
    import json
    todos = get_todos()
    print(json.dumps(todos, indent=2, ensure_ascii=False))
