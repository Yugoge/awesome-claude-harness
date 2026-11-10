#!/usr/bin/env bash
# STUB: settings.json no longer registers it (P12); hooks/lib/dev_loop_checks.py advice() gives its
# advice as a rule of hooks/posttool-dispatch-record.py (PostToolUse Agent), tied to the dev
# dispatch's own task.
# It warned, at a subagent's stop, when the diff exceeded the minimum-diff threshold with no
# justification in the dev report. It guessed its task from the newest docs/dev/context-*.json,
# wrote to stderr and exited 0, so its warning reached no model. A running session keeps the hook
# list it loaded, so the file stays at its path as an exit-0 stub that reads nothing and decides
# nothing (D15).
exit 0
