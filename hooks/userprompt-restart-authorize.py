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


def _sweep_superseded(session_id: str, keep: Path | None) -> list[str]:
    """Best-effort removal of this session's earlier guidance files.

    Hygiene, not correctness -- see lib/subagent_restart.py guidance_path for
    why a leftover this cannot delete is already inert. Failures are collected
    and reported, never silently swallowed, so the operator learns which file
    resisted removal.
    """
    failures: list[str] = []
    for path in restart.superseded_guidance_paths(session_id, keep):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            failures.append(f"{path}: {exc}")
    return failures


def _persist_guidance(grant: dict, args: str) -> Path | None:
    """Store the operator argument verbatim, bound to the capability it is for.

    The argument is untrusted operator data, so it gets its own raw UTF-8 file:
    no character in it can be significant to the capability's JSON framing, and
    no quoting or escaping is applied that could lose bytes. Its path is bound
    to THIS invocation's capability (``guidance_path`` takes the grant just
    minted) -- see that function for why this keeps an earlier invocation's
    text out of a later resume. An empty argument therefore does not have to
    succeed at deleting anything to be honoured -- it simply writes no file for
    the live capability, and the reader finds none.

    Runs only AFTER the capability exists and reports every failure as a
    RestartError for the caller to downgrade to a warning: guidance is purely
    additive (see lib/subagent_restart.py load_guidance), so losing the
    operator's words must never cost the recovery itself. The path convention is
    the library's, never re-derived here, so the writer and the reader cannot
    drift apart.
    """
    session_id = str(grant.get("session_id", ""))
    path = restart.guidance_path(session_id, grant)
    if not args:
        failures = _sweep_superseded(session_id, None)
        if failures:
            raise restart.RestartError(
                "earlier guidance could not be deleted (it is already inert, since "
                f"only this capability's own path is read): {'; '.join(failures)}"
            )
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
    except (OSError, UnicodeError) as exc:
        # Operator text is deliberately unfiltered, so it can carry an unpaired
        # surrogate that UTF-8 cannot represent. That raises UnicodeError, not
        # OSError, so it has to be recognised here as one more way persistence
        # can fail -- never left to escape as a traceback. The unlink below is
        # hygiene for a half-made file; its failure changes no outcome.
        try:
            path.unlink()
        except OSError:
            pass
        raise restart.RestartError(
            f"cannot persist guidance at {path}: {type(exc).__name__}: {exc}"
        ) from exc
    for failure in _sweep_superseded(session_id, path):
        print(
            f"[/restart] note: an earlier guidance file could not be deleted ({failure}); "
            "it is inert -- only this capability's own guidance is read.",
            file=sys.stderr,
        )
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
    # The capability comes FIRST and alone: this hook runs on prompt submission
    # for a human-only emergency command, so nothing about the operator's
    # optional guidance -- not a stale file that resists removal, not a failed
    # write, not text UTF-8 cannot hold -- may stand between the operator and
    # the recovery capability, nor change this hook's exit status. It also comes
    # first because it is what the guidance is bound to: the grant minted here
    # names the single path this invocation's guidance can occupy.
    try:
        grant = restart.mint_grant(str(session_id or ""), str(transcript_path or ""))
    except restart.RestartError as exc:
        print(f"[/restart] capability issue failed: {exc}", file=sys.stderr)
        return 2
    print(
        "[/restart] capability issued for parent session "
        f"{grant['session_id']}; only transcript-discovered interrupted agent ids may be resumed."
    )
    try:
        carried = _persist_guidance(grant, args)
    except restart.RestartError as exc:
        carried = None
        print(
            f"[/restart] warning: operator guidance was not preserved: {exc}; "
            "the capability stands and recovery proceeds without it.",
            file=sys.stderr,
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
