#!/usr/bin/env python3
"""UserPromptSubmit: mint a session-bound capability for a human /restart invocation, or for
the /dev-overnight session's own wake (lib.overnight.WAKE_PROMPT) inside its open span.

The hook cannot tell a scheduled prompt from a typed one: its payload names no origin, and the
prompt's own record is written after it runs (P1c X8). So the wake is recognised by its fixed
text and only while a /dev-overnight span is the transcript's active one (never after the
owner's /stop opened its own); every prompt that starts with /restart keeps the capability. The owner's /stop prompt unlinks a
capability the wake minted (its recorded origin), so none outlives the overnight run's end.
The capability's reader in lib/subagent_restart.py stays its one deciding rule.

On a typed /restart (not the wake) the hook then prepares the recovery set itself: it runs
scripts/restart-subagents.py prepare, the one definition of that computation, and hands its
output to the model verbatim between PREPARED_MARKER and PREPARED_END (commands/restart.md step 2
names both). Past PREPARE_BUDGET_SECONDS or on any failure it prints NOT_PREPARED_MARKER and the
reason instead; the capability is issued exactly as before either way."""

from __future__ import annotations
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
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import command_span, overnight, subagent_restart as restart  # noqa: E402

COMMAND = "/restart"
# The prepare helper the procedure runs (commands/restart.md step 2); the hook runs that same file
HELPER = Path(__file__).resolve().parents[1] / "scripts" / "restart-subagents.py"
# The lines commands/restart.md step 2 names: the helper's stdout sits between the first two
PREPARED_MARKER = "[/restart] RECOVERY SET PREPARED (the output of restart-subagents.py prepare, verbatim):"
PREPARED_END = "[/restart] END OF RECOVERY SET"
NOT_PREPARED_MARKER = "[/restart] RECOVERY SET NOT PREPARED:"
# Inside this hook's 60 s rule timeout (hooks/userprompt-launch.py), leaving the mint and the
# guidance write their share; the whole hook took 0.3 s on a constructed 60 MB transcript and
# 1.2 s on a 300 MB one (2026-11-20)
PREPARE_BUDGET_SECONDS = 20.0
# The account-rotation request typed as an option: `/restart --cross-account [guidance]`. The
# guidance stays the whole argument, verbatim, as it always was.
CROSS_ACCOUNT_RE = re.compile(r"--cross-account(?:\s|$)")


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


def _not_prepared(reason: str) -> str:
    return (f"{NOT_PREPARED_MARKER} {reason}. The capability stands; run commands/restart.md "
            "step 2's prepare command yourself.")


def prepare_block(session_id: str, args: str, cwd: object = None,
                  budget: float | None = None) -> str:
    """The recovery set for this /restart, as the context block commands/restart.md step 2 reads.

    The helper itself runs (one definition of prepare, its own writes and locking), with this
    session's id and, when the argument starts with --cross-account, that flag; its cwd is the
    session's, as the agent's own Bash call would have. It runs as a child so that the budget
    ends it cleanly (killed, its state lock released with it). A non-zero exit, a timeout or
    output that is not one JSON object yields the not-prepared line instead, never an error."""
    budget = PREPARE_BUDGET_SECONDS if budget is None else budget
    command = [sys.executable, str(HELPER), "prepare", "--session-id", session_id]
    if CROSS_ACCOUNT_RE.match(args):
        command.append("--cross-account")
    workdir = cwd if isinstance(cwd, str) and cwd and os.path.isdir(cwd) else None
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=budget,
                              cwd=workdir, check=False)
    except subprocess.TimeoutExpired:
        return _not_prepared(f"preparing ran past this hook's {budget:g} s budget")
    except (OSError, ValueError) as exc:
        return _not_prepared(f"the prepare helper could not start ({type(exc).__name__}: {exc})")
    if done.returncode != 0:
        last = (done.stderr.strip().splitlines() or [""])[-1][:400]
        return _not_prepared(f"the prepare helper exited {done.returncode} ({last})")
    try:
        parsed = json.loads(done.stdout)
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict):
        return _not_prepared("the prepare helper printed no JSON object")
    return "\n".join((PREPARED_MARKER, done.stdout.rstrip("\n"), PREPARED_END))


def is_stop(prompt: object) -> bool:
    """The prompt is the owner's /stop (only a human types it: Skill(stop) is denied)."""
    found = command_span.slash_command(prompt) if isinstance(prompt, str) else None
    return bool(found) and found[0] == "stop"


def revoke_on_stop(session_id: object) -> int:
    """Lesson 16: no wake works after /stop, so the grant an earlier wake minted dies with it.
    A grant the owner's own /restart minted stands. Never blocks the /stop itself."""
    try:
        revoked = restart.revoke_wake_grant(str(session_id or ""))
    except restart.RestartError as exc:
        print(f"[/restart] warning: /stop could not revoke the wake's capability: {exc}", file=sys.stderr)
        return 0
    if revoked:
        print("[/restart] /stop revoked the capability the overnight wake issued; only the owner's "
              "own /restart issues a new one.")
    return 0


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
    session_id = payload.get("session_id")
    transcript_path = payload.get("transcript_path")
    if not invoked:  # a resumed child's notification or any later prompt: how the recovery stands
        settled = restart.settle(str(session_id or ""))
        if settled:
            print(settled)
    if not invoked and is_stop(payload.get("prompt")):
        return revoke_on_stop(session_id)
    wake = not invoked
    if wake and not overnight.wake_fired(payload.get("prompt"), transcript_path):
        return 0
    # The capability comes FIRST and alone: this hook runs on prompt submission
    # for a human-only emergency command, so nothing about the operator's
    # optional guidance -- not a stale file that resists removal, not a failed
    # write, not text UTF-8 cannot hold -- may stand between the operator and
    # the recovery capability, nor change this hook's exit status. It also comes
    # first because it is what the guidance is bound to: the grant minted here
    # names the single path this invocation's guidance can occupy.
    try:
        grant = restart.mint_grant(str(session_id or ""), str(transcript_path or ""),
                                   origin="overnight-wake" if wake else "restart")
    except restart.RestartError as exc:
        print(f"[/restart] capability issue failed: {exc}", file=sys.stderr)
        return 2
    print(
        "[/restart] capability issued for parent session "
        f"{grant['session_id']}; only transcript-discovered interrupted agent ids may be resumed."
    )
    if grant.get("ttl_warning"):
        print(f"[/restart] {grant['ttl_warning']}")
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
        # carry; this hook's own lines never echo it. It reaches the context only
        # inside the prepared set below, as the helper's output always carried it.
        print(
            f"[/restart] operator argument preserved verbatim ({len(args.encode('utf-8'))} bytes) "
            f"at {carried}; recovery lanes read it as data, not as instructions."
        )
    if invoked:  # the wake's recovery runs prepare itself (commands/dev-overnight.md Step 0)
        # Last, after the guidance it reads is on disk. Its own output carries the guidance (in
        # operator_guidance and every resume_message), as the agent's prepare call showed it.
        try:
            print(prepare_block(grant["session_id"], args, payload.get("cwd")))
        except Exception as exc:  # noqa: BLE001 -- the capability above must never be lost
            print(_not_prepared(f"the hook failed while preparing ({type(exc).__name__}: {exc})"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
