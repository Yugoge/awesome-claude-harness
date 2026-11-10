#!/usr/bin/env bash
# Write one or more enforcement-flag sentinels into a dev-registry session dir.
#
# The E2E gate has no flag (hooks/subagentstop-e2e-enforce.py judges every
# cycle's QA): its old wrapper, write-e2e-enforce.sh, is an exit-0 stub that
# writes nothing.
#
# --flag is repeatable, and that is the point: one invocation writes every flag
# a cycle's registry needs (hooks/prompt-workflow.py _arm_registry). A flag
# says only that its gate is armed for the session; which agents a gate applies
# to is the gate's own decision, never a list here.
#
# Usage: write-enforce-flag.sh --source-command <dev|dev-command|redev|dev-overnight> \
#                              --session-id <DEV_SESSION_ID> \
#                              --flag codex [--flag <...>]
# Exits 1 on failure; callers must abort if this script fails.
#
# The arguments, the registry directory (obligation.registry_dir_named, the
# one rule) and the write are hooks/prompt-workflow.py's (write-enforce-flags):
# the path is then the rule's own code, which the artifact check reads (a path
# this script took from the rule's printed output, it could not follow, and
# the flag's reader, hooks/subagentstop-codex-enforce.py, had no writer).
set -euo pipefail

exec python3 -B "$(cd "$(dirname "$0")/.." && pwd)/hooks/prompt-workflow.py" write-enforce-flags "$@"
