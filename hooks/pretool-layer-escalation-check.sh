#!/usr/bin/env bash
# STUB: settings.json no longer registers it (P12); hooks/lib/dev_loop_checks.py advice() gives its
# advice as a rule of hooks/pretool-dispatch-gate.py (PreToolUse Agent), tied to the dev dispatch's
# own task.
# It warned, before a dev dispatch, when the cycle was about to retry a layer that had failed two or
# more prior attempts. It guessed its task from the newest docs/dev/context-*.json, wrote to stderr
# and exited 0, so its warning reached no model. A running session keeps the hook list it loaded, so
# the file stays at its path as an exit-0 stub that reads nothing and decides nothing (D15).
exit 0
