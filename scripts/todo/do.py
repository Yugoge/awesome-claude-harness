#!/usr/bin/env python3
"""Preloaded TodoList for /do workflow.

Injects the 4-step /do workflow checklist via hook-todo-injection.
Step 3 (Codex audit) is always listed; the agent skips it when --codex is absent.
"""

_STEPS = [
    ("1", "Understand requirements", "Understanding requirements", None),
    ("2", "Develop", "Developing", None),
    ("3", "Codex audit (skip if --codex not in $ARGUMENTS)", "Running codex audit", None),
    ("4", "Summary", "Writing summary", None),
]


def _build_step(label, desc, active, meta):
    item = {
        "content": f"Step {label}: {desc}",
        "activeForm": f"Step {label}: {active}",
        "status": "pending",
    }
    if meta:
        item.update(meta)
    return item


def get_todos():
    return [
        _build_step(label, desc, active, meta)
        for label, desc, active, meta in _STEPS
    ]


if __name__ == "__main__":
    import json
    print(json.dumps(get_todos(), indent=2, ensure_ascii=False))
