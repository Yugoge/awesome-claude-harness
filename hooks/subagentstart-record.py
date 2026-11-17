#!/usr/bin/env python3
"""SubagentStart: shows the starting subagent its own record (D29, D32): score, rank and trend, its newest good event and newest miss as facts, and the
rank's reminder (hooks/lib/score_log.py), of at most 3 lines and 400 bytes; one line for a role with no rows. No record in a /close, /commit, /merge or /push
span, or for an agent outside agents/. Then, for a subagent of a role tool-policy.v1.json lists and lets write, one line naming its own scratch directory,
<project>/.claude/scratch/<session>/<role>/<agent_id>/ (hooks/lib/dispatch_scratch.py), which it creates with its tmp/, the dispatch's TMPDIR: the one
temp location hooks/pretool-tool-policy.py lets that dispatch alone write. Both go out as additionalContext. Reads the score log, never blocks, exits 0 on every
path, prints nothing on an error."""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)

import json  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))


def scratch_line(payload):
    """The line naming the starting dispatch's own scratch directory, which it creates; None for a role no policy row lists or an unsafe id."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from lib import agent_resolver, claude_home, dispatch_scratch, policy_registry
    role = agent_resolver.resolve_agent_type(payload)
    policy = policy_registry.get_role_policy(role) if role else {"_unknown_role": True}
    if policy.get("_unknown_role") or policy_registry._check_tool_lists(policy, "Write") is not None:
        return None  # no role row, or a role that writes nothing (its Bash writes are judged as Write)
    project = claude_home.project_dir()
    path = dispatch_scratch.scratch_dir(project, payload.get("session_id"), role, payload.get("agent_id"))
    if path is None or not dispatch_scratch.ensure_scratch(path, project):
        return None
    return (f"Your scratch, this dispatch's alone: {path}/ -- put temp files and logs there; for a tool that uses TMPDIR (mktemp included) "
            f"start the command with: export TMPDIR={path}/tmp && ... Shared /tmp names, other dispatches' scratch and harness state are refused.")


def main() -> None:
    try:
        import score_view
        payload = json.load(sys.stdin)
        text = None
        try:
            text = score_view.dispatch_context(payload)
        except Exception:
            pass
        try:
            line = scratch_line(payload)
        except Exception:
            line = None
        text = "\n".join(t for t in (text, line) if t)
        if text:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": text}}))
    except Exception:
        pass


if __name__ == "__main__":
    main()
