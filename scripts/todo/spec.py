#!/usr/bin/env python3
"""Preloaded TodoList for /spec workflow.

Mirrors the ask.py structure in the knowledge-system scripts/todo directory.

/spec has a single mode: Spec Creation Mode. It acts immediately on whatever
the user provides, accumulates multiple requirements into one spec file per
session, and finalizes only on a natural-conclusion strong signal.
"""

import json
import sys


_SPEC_STEPS = (
    ("1", "Parse arguments",
           "Parsing arguments"),
    ("2", "Clarify requirement (max 3 rounds)",
           "Clarifying requirement"),
    ("3", "Write first spec and dispatch exploration",
           "Writing spec and dispatching exploration"),
    ("3a", "Requirement round: BA panel, panel QA, ask, copy the answers",
            "Running the requirement round"),
    ("4", "Accumulate requirements (multi-turn loop)",
           "Accumulating requirements"),
    ("5", "Detect natural conclusion",
           "Detecting natural conclusion"),
    ("6", "Finalize spec (split + checkpoints + QA)",
           "Finalizing spec"),
    ("7", "Display result and workflow update",
           "Displaying result and writing workflow update"),
)


def _build_step(label: str, desc: str, active: str) -> dict:
    """Build a single todo item dict from a step tuple."""
    return {
        "content": f"Step {label}: {desc}",
        "activeForm": f"Step {label}: {active}",
        "status": "pending",
    }


def get_todos() -> list:
    """Return the Spec Creation Mode todo list (Steps 1-7, with Step 3a)."""
    return [_build_step(label, desc, active) for label, desc, active in _SPEC_STEPS]


def get_blocking_count() -> int:
    """Steps 1-3a must complete before Claude can stop.
    (Parse, Clarify, Write first spec + dispatch Explore, the requirement round)
    Steps 4-7 are session-duration: multi-turn loop, conclusion detection,
    finalize, and display -- these run until natural-conclusion signal fires.
    """
    return 4


if __name__ == "__main__":
    print(json.dumps(get_todos(), indent=2, ensure_ascii=False))
    sys.exit(0)
