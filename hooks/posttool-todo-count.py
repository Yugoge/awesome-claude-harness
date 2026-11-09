#!/usr/bin/env python3
# STUB: settings.json no longer registers it; pretool-todo-validate.py refuses a short list at a span's first list or a length change before the call runs.
"""PostToolUse hook (TodoWrite step count), retired to a no-op.

It refused, after a TodoWrite had run, a list shorter than the command's
canonical list at a first list or a change of its length. pretool-todo-
validate.py compares those lists with the canonical one, count included,
before the call runs (P5 R19). A running session keeps the hook list it
loaded, so the file stays as an exit-0 stub that reads nothing and decides
nothing."""
import sys

sys.exit(0)
