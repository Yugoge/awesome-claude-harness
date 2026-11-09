#!/usr/bin/env python3
# STUB: settings.json no longer registers it; pretool-todo-validate.py decides every TodoWrite step rule before the call runs.
"""PostToolUse hook (TodoWrite step sequence), retired to a no-op.

It re-checked, after a TodoWrite had run, the step rules
pretool-todo-validate.py had already checked before it ran, plus the first
list's statuses (nothing completed, Step 0 the only in_progress step), a rule
pretool-todo-validate.py now applies to a span's first list itself (P5 R19).
A running session keeps the hook list it loaded, so the file stays as an
exit-0 stub that reads nothing and decides nothing."""
import sys

sys.exit(0)
