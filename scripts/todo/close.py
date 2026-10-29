#!/usr/bin/env python3
"""Preloaded TodoList for /close workflow.

Three user-visible TodoSteps (flat-integer per agents/style-inspector.md
Standard 4):
  1. Dispatch three inspectors in parallel
  2. Delegate close debate to QA subagent
  3. Generate close-report and spec/temp update

For --force path, returns a 2-step list (no QA dispatch — spec: "the primary
protection is that the todo list never contains a QA dispatch step").

For --late-repair, the three steps follow Step 0, finalize: the main agent's
own step, which writes the effective report it declares, so a gap on that
report routes back to finalize.

Flag handling (--codex / --force) and task-id resolution still happen in
commands/close.md body but are no longer TodoSteps — they are script
plumbing, not user-visible work.
"""

import os


_STEPS = [
    ("1", "Dispatch three inspectors in parallel", "Dispatching three inspectors in parallel", None),
    ("2", "Delegate close debate to QA subagent", "Delegating close debate to QA subagent", {"subagent_call": {"agent": "qa", "subagent_type": "qa"}}),
    ("3", "Generate close-report and spec/temp update", "Generating close-report and spec/temp update", None),
]

_STEPS_FORCED = [
    ("1", "Write forced close-report", "Writing forced close-report", None),
    ("2", "Write audit log + temp update + clean up sentinel", "Writing audit log + temp update + cleaning up sentinel", None),
]

_STEPS_LATE_REPAIR = [
    ("0", "Finalize the late repair", "Finalizing the late repair",
     {"artifacts": [{"kind": "json", "path": "docs/dev/dev-report-<task>.effective.json"}]}),
    *_STEPS,
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


def _prompt_has(flag):
    return flag in os.environ.get("CLAUDE_TODO_PROMPT", "").split()


def get_todos():
    if _prompt_has("--force"):
        steps = _STEPS_FORCED
    elif _prompt_has("--late-repair"):
        steps = _STEPS_LATE_REPAIR
    else:
        steps = _STEPS
    return [_build_step(label, desc, active, meta) for label, desc, active, meta in steps]


if __name__ == "__main__":
    import json
    print(json.dumps(get_todos(), indent=2, ensure_ascii=False))
