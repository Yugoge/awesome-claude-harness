#!/usr/bin/env python3
"""Preloaded TodoList for /close: commands/close.md's "### Step 0" to "### Step 3b",
the same five steps under every prompt (--auto walks each step over its parents;
--force is accepted and ignored).

Under --late-repair, Step 0 also declares the effective report finalize writes
(the main agent's own step), so a gap on that report routes back to Step 0.
"""

import os


_STEPS = [
    ("0", "Resolve the disposition; complete the cycle when incomplete",
     "Resolving the disposition; completing the cycle when incomplete", None),
    ("1", "Dispatch three inspectors in parallel", "Dispatching three inspectors in parallel", None),
    ("2", "Delegate close debate to QA subagent", "Delegating close debate to QA subagent", {"subagent_call": {"agent": "qa", "subagent_type": "qa"}}),
    ("3", "Echo the verdict and name the next step", "Echoing the verdict and naming the next step", None),
    ("3b", "Ask the user to rate each landed cycle", "Asking the user to rate each landed cycle", None),
]

_LATE_REPAIR_STEP_0 = {"artifacts": [{"kind": "json", "path": "docs/dev/dev-report-<task>.effective.json"}]}


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
    late_repair = "--late-repair" in os.environ.get("CLAUDE_TODO_PROMPT", "").split()
    return [_build_step(label, desc, active, _LATE_REPAIR_STEP_0 if late_repair and label == "0" else meta)
            for label, desc, active, meta in _STEPS]


if __name__ == "__main__":
    import json
    print(json.dumps(get_todos(), indent=2, ensure_ascii=False))
