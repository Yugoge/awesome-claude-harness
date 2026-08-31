#!/usr/bin/env python3
"""UserPromptSubmit: mint bare recovery or exact human audit capabilities."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import subagent_restart as restart  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    if payload.get("agent_id"):
        return 0
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return 0
    session_id = payload.get("session_id")
    transcript_path = payload.get("transcript_path")
    try:
        if prompt == "/restart":
            grant = restart.mint_grant(str(session_id or ""), str(transcript_path or ""))
            print(
                "[/restart] capability issued for parent session "
                f"{grant['session_id']}; only transcript-discovered interrupted agent ids may be resumed."
            )
            return 0
        match = re.fullmatch(r"/restart confirm-unrecoverable ([0-9a-f]{64})", prompt)
        if not match:
            return 0
        capability = restart.mint_audit_capability(
            str(session_id or ""), match.group(1), prompt,
        )
    except restart.RestartError as exc:
        print(f"[/restart] capability issue failed: {exc}", file=sys.stderr)
        return 2
    print(
        "[/restart] human audit capability issued for parent session "
        f"{capability['session_id']} and audit {capability['audit_id']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
