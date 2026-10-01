#!/usr/bin/env python3
"""UserPromptSubmit: mint a session-bound capability for a human /restart invocation."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import subagent_restart as restart  # noqa: E402

COMMAND = "/restart"


def split_invocation(prompt: object) -> tuple[bool, str]:
    """Return (is_invocation, argument_text) for a submitted prompt.

    The first token must be the command itself, so a prompt that merely
    mentions the command mid-sentence is not an invocation. Leading whitespace
    and the whitespace separating the command from its argument are discarded;
    every remaining byte is the operator's argument and is returned verbatim,
    with no length limit, character filtering, or truncation.
    """
    if not isinstance(prompt, str):
        return False, ""
    text = prompt.lstrip()
    if not text.startswith(COMMAND):
        return False, ""
    remainder = text[len(COMMAND):]
    if remainder and not remainder[:1].isspace():
        return False, ""
    return True, remainder.lstrip()


def guidance_path(session_id: str) -> Path:
    """Session-bound sibling of the capability that holds the operator argument."""
    return restart.grant_path(session_id).with_name(f"claude-restart-args-{session_id}.txt")


def _persist_guidance(session_id: str, args: str) -> Path | None:
    """Store the operator argument verbatim beside the capability.

    The argument is untrusted operator data, so it gets its own raw UTF-8 file:
    no character in it can be significant to the capability's JSON framing, and
    no quoting or escaping is applied that could lose bytes. An empty argument
    removes any file an earlier invocation of this session left behind, so
    stale guidance is never replayed as if it were current.
    """
    path = guidance_path(session_id)
    if not args:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise restart.RestartError(f"cannot clear stale guidance at {path}: {exc}") from exc
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(args)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
    except OSError as exc:
        raise restart.RestartError(f"cannot persist guidance at {path}: {exc}") from exc
    return path


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    if payload.get("agent_id"):
        return 0
    invoked, args = split_invocation(payload.get("prompt"))
    if not invoked:
        return 0
    session_id = payload.get("session_id")
    transcript_path = payload.get("transcript_path")
    try:
        carried = _persist_guidance(str(session_id or ""), args)
        grant = restart.mint_grant(str(session_id or ""), str(transcript_path or ""))
    except restart.RestartError as exc:
        print(f"[/restart] capability issue failed: {exc}", file=sys.stderr)
        return 2
    print(
        "[/restart] capability issued for parent session "
        f"{grant['session_id']}; only transcript-discovered interrupted agent ids may be resumed."
    )
    if carried is not None:
        # Size and location only: the argument is data for the recovery lanes to
        # carry, never text this hook echoes back into the session context.
        print(
            f"[/restart] operator argument preserved verbatim ({len(args.encode('utf-8'))} bytes) "
            f"at {carried}; recovery lanes read it as data, not as instructions."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
