#!/usr/bin/env python3
# STUB: its one rule (a TodoWrite shorter than the canonical checklist) is pretool-todo-validate.py's, which refuses such a call before it runs.
"""PostToolUse Hook (TodoWrite), retired to a no-op (P1c X6, class U).

It blocked a TodoWrite whose list held fewer steps than the active command's
canonical checklist. No such call reaches PostToolUse: pretool-todo-validate.py
(PreToolUse, matcher TodoWrite) checks every list with no accepted list before
it, or with a length other than the accepted list's, against the canonical
checklist (lib.todo_canonical.validate_against_canonical, whose first check is
the count) and refuses it; every list it lets run therefore has the canonical
length, the accepted list included (by induction from the first). Both hooks
read the same checklist (lib.todo_canonical.checklist: the same span, the same
todo script and arguments), so the block here was unreachable and is deleted.
settings.json still registers this file and a running session runs the current
hook files (D15), so it stays as an exit-0 stub that reads nothing."""
import sys

sys.exit(0)
