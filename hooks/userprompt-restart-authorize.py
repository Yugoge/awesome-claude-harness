#!/usr/bin/env python3
"""UserPromptSubmit: mint a session-bound capability for exact bare /restart."""

from __future__ import annotations

import json
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
    if not isinstance(prompt, str) or prompt.strip() != "/restart":
        return 0
    session_id = payload.get("session_id")
    transcript_path = payload.get("transcript_path")
    project_dir = payload.get("cwd") or ""
    try:
        grant = restart.mint_grant(
            str(session_id or ""), str(transcript_path or ""), str(project_dir),
        )
    except restart.RestartError as exc:
        print(f"[/restart] authorization failed: {exc}", file=sys.stderr)
        return 2
    print(
        "[/restart] authenticated for parent session "
        f"{grant['session_id']}; only transcript-discovered interrupted agent ids may be resumed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
