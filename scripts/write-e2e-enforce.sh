#!/usr/bin/env bash
# Writes e2e-enforce.json into the dev-registry for the given session.
# Activates the E2E gate for QA: QA must perform live browser verification.
# Usage: write-e2e-enforce.sh --source-command <dev|dev-overnight> --session-id <DEV_SESSION_ID>
# Exits 1 on failure; callers must abort if this script fails.
#
# Thin wrapper: the body now lives in write-enforce-flag.sh, which writes any
# number of enforcement sentinels per invocation. This entry point is kept
# because commands/dev.md, commands/dev-command.md and
# hooks/prompt-workflow.py:_init_dev_registry call it by name.
set -euo pipefail
# This entry point writes exactly the e2e sentinel, as it always did. A
# caller-supplied --flag would silently widen that to other enforcement gates,
# which the original script had no way to do — reject it rather than forward it.
for arg in "$@"; do
  [[ "$arg" == "--flag" ]] && {
    echo "ERROR: --flag is not accepted here; use write-enforce-flag.sh directly" >&2
    exit 1; }
done
exec "$(dirname "$0")/write-enforce-flag.sh" --flag e2e "$@"
