#!/usr/bin/env python3
"""SubagentStop: a dev lane's blocking issues, shown to the lane once per dispatch.

A non-empty `blocking_issues` in a dev report holds the whole command at the
orchestrator's stop (scripts/resolve-dev-artifact-chain.py UNRESOLVED_BLOCKERS), and
the orchestrator cannot edit a lane's report. So the lane's own stop is held once,
with the list and one instruction: remove what is resolved or only informational.

- The report is the dev-report.v2 artifact the lane's own dispatch obligation
  declares (lib/obligation.resolve_own_obligation), read where it declares it.
- Once per dispatch: the hold is held already when the agent's transcript shows this
  hook's mark in a stop-hook feedback after the dispatch's latest prompt (its first
  record, or the latest message a coordinator delivered to it). The next stop passes
  with whatever remains: that is the lane's statement, judged at the orchestrator's stop.
- An agent that is no dev, an obligation that does not resolve, an absent or unreadable
  report, an empty list: exit 0, nothing printed. No switch; any error exits 0.

The hook writes nothing. Exit codes: 0 allow, 2 hold.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import obligation  # noqa: E402

MARK = "LANE_BLOCKERS_HOLD"
SHOWN, CHARS = 30, 300  # items listed, characters per item


def _held_this_dispatch(transcript: str) -> bool:
    held = False
    with open(transcript, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if MARK not in line and "coordinator" not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            attachment = record.get("attachment")
            origin = (attachment if isinstance(attachment, dict) else record).get("origin")
            if isinstance(origin, dict) and origin.get("kind") == "coordinator":
                held = False  # a new dispatch: its own one hold
            content = (record.get("message") or {}).get("content")
            if record.get("type") == "user" and record.get("isMeta") and isinstance(content, str) \
                    and content.startswith("Stop hook feedback") and MARK in content:
                held = True
    return held


def reasons(data: dict) -> list[str]:
    agent_id = data.get("agent_id")
    if not agent_id or data.get("agent_type") not in (None, "", "dev"):
        return []
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    mine = obligation.resolve_own_obligation(
        session_id=data.get("session_id") or data.get("sessionId"), agent_id=agent_id, project_dir=project_dir,
        payload_agent_transcript_path=data.get("agent_transcript_path"), expected_role="dev")
    transcript = getattr(mine, "transcript_path", "")
    if isinstance(mine, obligation.NoObligationInPrompt):  # a resume that restates no block: the first one's
        mine = obligation.parse_obligation(obligation.read_first_record_prompt(transcript) or "")
    doc = getattr(mine, "obligation", None) or {}
    if doc.get("role") != "dev":
        return []
    out = []
    for art in doc.get("artifacts") or []:
        if art.get("kind") != "json" or art.get("schema") != "dev-report.v2":
            continue
        try:
            items = json.loads((Path(project_dir) / art["path"]).read_text(encoding="utf-8")).get("blocking_issues")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(items, list) and items:
            listed = [f"  - {(i if isinstance(i, str) else json.dumps(i))[:CHARS]}" for i in items[:SHOWN]]
            more = [f"  ... and {len(items) - SHOWN} more"] if len(items) > SHOWN else []
            out.append(f"{MARK}: {art['path']} lists {len(items)} blocking issue(s):\n"
                       + "\n".join(listed + more))
    if not out or _held_this_dispatch(transcript):
        return []
    return out + ["Remove from blocking_issues what is resolved or only informational; what remains must need "
                  "action above this lane, since it holds the whole command at the orchestrator's stop. "
                  "Then stop again: that stop passes with what remains."]


def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
        found = reasons(data) if isinstance(data, dict) else []
    except Exception:  # noqa: BLE001 -- a fault never holds a lane
        return 0
    if found:
        sys.stderr.write("\n".join(found) + "\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
