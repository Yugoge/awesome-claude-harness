#!/usr/bin/env python3
"""PreToolUse:Agent -- witness a real changelog-analyst dispatch.

Writes `<state-dir>/claude-commit-dispatch-<sid>-<nonce>.json` when, and only
when, the harness is actually about to dispatch the `changelog-analyst`
subagent. `hooks/pretool-git-privilege-guard.py` then refuses to honor a
commit grant unless such an attestation exists and the committing caller is
the subagent that claimed it.

WHY A HOOK AND NOT THE ORCHESTRATOR. The orchestrator can write any file it
likes, so a manifest it authors proves only that it chose to author one. This
hook fires on the `Agent` tool event itself, so an artifact it writes exists
only because a dispatch really happened, and this hook is the only INTENDED
writer of the namespace. The Bash-layer block
(`hooks/pretool-bash-safety.sh` Layer 1.E3) intercepts the ordinary
file-writing verbs that would impersonate it, which raises the cost of
forging one; being a verb blacklist, it is not an absolute barrier. The
structural barrier is on the consume side: the privilege guard honors an
attestation only when the caller is a dispatched subagent (non-empty
`agent_id`) claiming it under its own identity. Together that is what closes
the hole where a seat lit the `/commit` user-intent sentinel, minted a grant,
and committed 14 times with changelog-analyst never dispatched at all.

THIS HOOK IS A WITNESS, NOT A GATE. It exits 0 on every path, including every
internal failure: it must never be able to refuse an `Agent` dispatch. A
crash here would otherwise take out /dev, /spec and every other dispatching
flow in the harness, on a hook whose entire job is to leave a note. If it
cannot write its note, the privilege guard fails closed later -- the commit
is refused, nothing is wrongly allowed, and the diagnostic names this hook.

Exit codes:
  0  always
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _dryrun_from_prompt(prompt: str):
    """Best-effort `DRYRUN` reading from the dispatch prompt.

    Forensic only. /commit Step 6 dispatches changelog-analyst with
    DRYRUN=true and Step 7 with DRYRUN=false, and it is useful for an auditor
    to see which dispatch a commit rode on. Nothing gates on this value:
    under DRYRUN the analyst's own guard forbids committing, and a parser
    keyed on prompt wording is exactly the kind of check that starts silently
    mis-answering the day the prompt is reworded.
    """
    lowered = prompt.lower()
    for needle, value in (("dryrun=true", True), ("dryrun=false", False),
                          ('"dryrun": true', True), ('"dryrun": false', False)):
        if needle in lowered:
            return value
    return None


def _task_id_from_prompt(prompt: str) -> str:
    """Best-effort task-id reading from the dispatch prompt. Forensic only."""
    import re
    match = re.search(r'\b(20\d{6}-\d{6})\b', prompt)
    return match.group(1) if match else ""


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0

    if data.get("tool_name") not in ("Agent", "Task"):
        return 0

    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0

    from lib import commit_pipeline

    if str(tool_input.get("subagent_type") or "").strip() != commit_pipeline.CHANGELOG_ANALYST:
        return 0

    sid = str(data.get("session_id") or "").strip()
    if not sid:
        # Without a session id the attestation cannot be addressed to the
        # grant that will reference it. Fail closed by writing nothing: the
        # guard refuses the commit and names the missing attestation.
        sys.stderr.write(
            "[commit-dispatch-attest] NOTE: changelog-analyst dispatch seen with no "
            "session_id in the hook payload; no attestation written, so the privilege "
            "guard will refuse the resulting commit.\n"
        )
        return 0

    prompt = tool_input.get("prompt")
    prompt = prompt if isinstance(prompt, str) else ""

    try:
        path = commit_pipeline.write_attestation(
            sid,
            task_id=_task_id_from_prompt(prompt),
            dryrun=_dryrun_from_prompt(prompt),
            dispatcher_agent_id=str(data.get("agent_id") or ""),
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest() if prompt else "",
        )
    except Exception as exc:  # witness, never a gate -- see module docstring
        sys.stderr.write(
            f"[commit-dispatch-attest] WARNING: could not record the changelog-analyst "
            f"dispatch attestation ({exc.__class__.__name__}: {exc}). The dispatch "
            f"proceeds; the privilege guard will refuse the resulting commit for lack of "
            f"an attestation.\n"
        )
        return 0

    if os.environ.get("CLAUDE_COMMIT_ATTEST_VERBOSE", "") == "1":
        sys.stderr.write(f"[commit-dispatch-attest] wrote {path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
