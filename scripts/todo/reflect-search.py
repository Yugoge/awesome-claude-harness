#!/usr/bin/env python3
"""
Preloaded TodoList for /reflect-search workflow.

Reflection-driven iterative search with goal evaluation.
"""


def get_todos():
    """
    Return list of todo items for TodoWrite.

    Returns:
        list[dict]: Todo items with content, activeForm, status
    """
    return [
        {"content": "Step 1: Articulate Concrete Goal", "activeForm": "Step 1: Articulating Concrete Goal", "status": "pending"},
        {"content": "Step 2: Initial Search", "activeForm": "Step 2: Executing Initial Search", "status": "pending"},
        {"content": "Step 3: Reflection Loop (max 5 iterations)", "activeForm": "Step 3: Running Reflection Loop", "status": "pending"},
        {"content": "Step 4: Adaptive Search", "activeForm": "Step 4: Executing Adaptive Search", "status": "pending"},
        {"content": "Step 5: Final Synthesis", "activeForm": "Step 5: Generating Final Synthesis", "status": "pending"}
    ]



if __name__ == "__main__":
    import json
    todos = get_todos()
    print(json.dumps(todos, indent=2, ensure_ascii=False))
