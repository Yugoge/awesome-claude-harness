#!/usr/bin/env python3
"""PostToolUse and PostToolUseFailure (every tool): the orchestrator gate's record of the calls that ran.

hooks/pretool-orchestrator-gate.py counts a main-agent call at PreToolUse, before the other hooks'
verdicts are known, and gives the slot back once the call is over without having run (OB-L02). This
hook is the evidence that a call ran: the CLI fires PostToolUse or PostToolUseFailure for every call
it ran (a non-zero exit, an error and an interrupted run fire PostToolUseFailure) and neither for a
call a PreToolUse hook refused. It appends the payload's tool_use_id, which the CLI sets, to
<state dir>/claude-tool-ran-<sid>.log (lib/allowlist.record_tool_ran); the prompt reset removes the
log with the streak. Nothing the call printed is read.

Main agent only (lib/subagent.is_subagent_context, as the gate decides). Never blocks: exit 0, or
exit 1 with the file, the error and the volume when the log cannot be appended to.
"""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0
    try:
        from lib.allowlist import record_tool_ran, state_entry_failure, tool_ran_path
        from lib.subagent import is_subagent_context
        if is_subagent_context(data):
            return 0
        # The session key the gate uses (pretool-orchestrator-gate.get_session_id).
        sid = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "") or "default"
        record_tool_ran(sid, data.get("tool_use_id"))
    except OSError as e:  # a non-blocking error: the user reads it
        sys.stderr.write(f"[Orchestrator Gate] The record that this call ran could not be written: "
                         f"{state_entry_failure(tool_ran_path(sid), e)}. If the call failed, the call limits "
                         f"give its slot back as if a hook had refused it.\n")
        return 1
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
