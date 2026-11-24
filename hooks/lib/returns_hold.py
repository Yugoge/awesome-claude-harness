#!/usr/bin/env python3
"""Returns held: the background children of one orchestrator come back to it as one batch (UserPromptSubmit).

Each return of a background child wakes the orchestrator, and each wake re-reads its whole context. This rule
of hooks/userprompt-launch.py holds a return while a sibling still runs and hands everything held over with the
prompt that passes next: the last sibling's return, the batch's deadline notice, any other notice, or a message
the owner typed.

Off unless switched on: the hold is not yet proven in a live session (its live check must pass before it is
switched on), so with CLAUDE_RETURNS_HOLD absent, or any value but ``on`` (the process env, which the CLI fills
from settings.json env), nothing is held, nothing is written and the waker does nothing; a batch held while it
was on is still handed over with the next prompt.

Held (a ``block`` of the prompt) only when all hold: the setting CLAUDE_RETURNS_HOLD is ``on``; the prompt is
one task-notification of an agent (task-id ``a...``, a tool-use-id, status completed, the closing tag, the final
note, nothing else); it wakes an idle orchestrator (the transcript's last queue-operation record is the dequeue
of it; one drained between tool calls rides a request that comes anyway); a sibling still runs, as the Stop gate
reads it (hooks/stop-command-gate.py background_children of the active span, its bound included), apart from this
child and those already held; and the batch's deadline can be set: the deadline waker is registered (an
asyncRewake UserPromptSubmit entry of hooks/userprompt-returns-deadline.sh in the harness's settings.json) and
the state file is written. Any doubt (unreadable state or transcript, a notice of another shape, an interim
notice, no span, no sibling running, a fault) delivers.

State: <harness state dir>/returns-hold/<session>.json, written only here (``_save``): the batch's opening time,
its deadline (opening + WINDOW) and each held notice (id, tool-use-id, time held, its text). Lifetime: from a
batch's first hold to its hand-over, where ``decide`` removes it (at most WINDOW plus the next prompt); the empty
``<session>.json.lock`` beside it stays (removing it would race a concurrent hold). Deadline: the waker (``deadline``, run as ``--deadline`` by the shell entry on every agent-shaped
notice, in the background) sleeps WINDOW and, if the batch it was armed for is still open, exits 2: the CLI
then wakes the session with a notice carrying DEADLINE_MARK, which is never held and delivers everything held,
naming the siblings still silent. Returned: the hand-over's context (its head is lib/command_span.py HANDOVER)
is where the Stop gate and every reader of lib/agent_returns.py find each held return delivered. The record: the
launcher writes the hold as a refusal of the prompt; at the hand-over ``_record`` replaces that line with a HELD
one carrying the seconds held (lib/refusal_record.py; scripts/refusals counts holds apart from refusals).
"""
from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import re
import sys
import time

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTING = "CLAUDE_RETURNS_HOLD"            # "on" holds; absent or anything else: nothing held (what is held is delivered)
WINDOW = 30 * 60                           # seconds from a batch's first hold to its deadline (cache lives 60 min)
WAKER = "userprompt-returns-deadline.sh"
DEADLINE_MARK = "RETURNS_HOLD_DEADLINE"
RESULT_MAX = 6000                          # characters of one held <result> handed over; the output file holds all
TAIL = 1 << 20                             # bytes of the transcript read from its end
_ONE = re.compile(r"\A<task-notification>\n<task-id>(a[0-9a-f]+)</task-id>\n<tool-use-id>(toolu_[A-Za-z0-9_]+)"
                  r"</tool-use-id>\n(?:<output-file>[^<\n]*</output-file>\n)?<status>completed</status>\n"
                  r"<summary>[^<]*</summary>\n<note>A task-notification fires each time this agent stops with no "
                  r"live background children of its own\.[^<]*</note>\n(?:<result>.*</result>\n)?"
                  r"(?:<usage>(?:<(\w+)>\d+</\3>)*</usage>\n)?</task-notification>\s*\Z", re.S)


def _notice(prompt: str):
    """The (task-id, tool-use-id) match of a holdable return, or None: any other shape is delivered."""
    return _ONE.match(prompt) if prompt.count("<task-notification>") == 1 else None


def _path(session: str) -> str | None:
    sys.path.insert(0, HOOKS)
    try:
        from lib.harness_state_dir import harness_state_dir
    finally:
        sys.path.pop(0)
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", session or "") or session.startswith("."):
        return None
    return os.path.join(harness_state_dir(), "returns-hold", f"{session}.json")


def _load(path) -> dict:
    """The open batch, {} when none; raises on a file that cannot be read as one (the caller delivers)."""
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        return {}
    if not (isinstance(state, dict) and isinstance(state.get("held"), list) and isinstance(state.get("deadline"), (int, float))):
        raise ValueError("returns-hold state of an unknown shape")
    return state


def _save(path, state) -> None:
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    temp = f"{path}.{os.getpid()}"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    os.replace(temp, path)


def switched_on() -> bool:
    return os.environ.get(SETTING) == "on"  # exactly as the waker's shell test reads it


def _stamp(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _idle_wake(transcript: str) -> bool:
    """True when the last queue-operation record of the transcript is a dequeue: the CLI took the notice off its
    queue to open a turn for it (a notice drained between tool calls is still enqueued when the hook runs)."""
    with open(transcript, "rb") as handle:
        size = os.fstat(handle.fileno()).st_size
        handle.seek(max(0, size - TAIL))
        lines = handle.read().splitlines()
    for line in reversed(lines):
        if b'"queue-operation"' in line:
            record = json.loads(line)
            if record.get("type") == "queue-operation":
                return record.get("operation") == "dequeue"
    return False


def _gate():
    spec = importlib.util.spec_from_file_location("returns_hold_stop_gate", os.path.join(HOOKS, "stop-command-gate.py"))
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, HOOKS)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def running_siblings(transcript: str, skip: set, now: float | None = None) -> list[str]:
    """The span's background children the Stop gate counts as running (its own reading, with its bound), but
    ``skip`` (this child and the held ones, whose notices the CLI wrote no delivery record of)."""
    gate = _gate()
    span = gate.command_span.active_span(transcript)
    if span is None:
        return []
    return [a for a in gate.background_children(span, now)[0] if a not in skip]


def waker_registered(settings_path: str | None = None) -> bool:
    """The deadline can be set: settings.json registers the waker on UserPromptSubmit with asyncRewake and a
    timeout past WINDOW."""
    sys.path.insert(0, HOOKS)
    try:
        from lib.claude_home import load_settings
    finally:
        sys.path.pop(0)
    settings, _problem = load_settings(settings_path or os.path.join(os.path.dirname(HOOKS), "settings.json"))
    try:
        groups = (settings or {})["hooks"]["UserPromptSubmit"]
        return any(WAKER in str(h.get("command")) and h.get("asyncRewake") is True
                   and float(h.get("timeout") or 0) > WINDOW for g in groups for h in g.get("hooks", []))
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def _handover(state: dict, now: float, silent: list[str], deadline: bool) -> str:
    held = state.get("held") or []
    parts = [f"HELD RETURNS ({len(held)}): returns of background children held since {_stamp(state['opened'])} so "
             "that the batch comes back in one wake; each is the task-notification the CLI sent, in arrival order."]
    for item in held:
        text = str(item.get("text") or "")
        cut = re.search(r"<result>(.*)</result>", text, re.S)
        if cut and len(cut.group(1)) > RESULT_MAX:
            text = text[:cut.start(1) + RESULT_MAX] + "\n(cut here; the output file holds the rest)" + text[cut.end(1):]
        parts.append(f"[held {round(now - item['at'])} s]\n{text}")
    if deadline:
        parts.append("The batch's deadline passed; still silent: " + (", ".join(silent) if silent else "none") + ".")
    elif silent:
        parts.append("Still running: " + ", ".join(silent) + ".")
    return "\n\n".join(parts)


def _record(payload: dict, state: dict, now: float) -> None:
    """Each return handed over into the refusal record as HELD with its seconds held: the line takes the place of
    the refusal line the launcher wrote for its hold (lib/refusal_record.py same), so a hold is no refusal."""
    sys.path.insert(0, HOOKS)
    try:
        from lib import refusal_record
    finally:
        sys.path.pop(0)
    me = os.path.join(HOOKS, "lib", "returns_hold.py")
    for item in state.get("held") or []:
        refusal_record.report({"hook_event_name": "UserPromptSubmit", "session_id": payload.get("session_id"),
                               "cwd": payload.get("cwd"), "prompt": item.get("text"), "held_seconds": now - item["at"]},
                              [(me, f"returns-hold: held the return of {item.get('id')}")], me, refusal_record.HELD)


def decide(payload: dict, now: float | None = None) -> dict | None:
    """The rule's answer to one prompt: a block (held), additionalContext (delivered), or None (nothing to do)."""
    now = time.time() if now is None else now
    path = _path(str(payload.get("session_id") or ""))
    on = switched_on()
    if path is None or not (on or os.path.exists(path)):  # off: nothing held, nothing written
        return None
    prompt, transcript = str(payload.get("prompt") or ""), str(payload.get("transcript_path") or "")
    lock = open(path + ".lock", "a") if os.path.isdir(os.path.dirname(path)) else None
    try:
        if lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            state = _load(path)
        except (OSError, ValueError):
            return None
        held_ids = {i for item in state.get("held", []) for i in (item.get("id"), item.get("tool_use_id"))}
        one = _notice(prompt)
        hold = False
        if one and on and not (state and now >= state["deadline"]):
            try:
                hold = (_idle_wake(transcript) and waker_registered()
                        and bool(running_siblings(transcript, held_ids | {one.group(1), one.group(2)}, now)))
            except Exception:  # noqa: BLE001 - any doubt delivers
                hold = False
        if hold:
            batch = state or {"opened": now, "deadline": now + WINDOW, "held": []}
            batch = {**batch, "held": batch["held"] + [
                {"id": one.group(1), "tool_use_id": one.group(2), "at": now, "text": prompt}]}
            try:
                _save(path, batch)
            except OSError:  # no deadline without the file: this notice passes, with what was held
                pass
            else:
                state = batch
                return {"decision": "block", "suppressOriginalPrompt": True, "reason": (
                    f"returns-hold: held the return of {one.group(1)} ({len(state['held'])} held; batch opened "
                    f"{_stamp(state['opened'])}, deadline {_stamp(state['deadline'])}); everything held comes back "
                    "with the last sibling's return, the deadline, or your next message.")}
        if not state.get("held"):
            return None
        try:
            silent = running_siblings(transcript, held_ids | ({one.group(1), one.group(2)} if one else set()), now)
        except Exception:  # noqa: BLE001 - the hand-over goes out without the list
            silent = []
        text = _handover(state, now, silent, DEADLINE_MARK in prompt or now >= state["deadline"])
        try:
            os.unlink(path)
        except OSError:
            pass
        _record(payload, state, now)
        return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text},
                "systemMessage": f"returns-hold: {len(state['held'])} held return(s) handed over"}
    finally:
        if lock:
            lock.close()


def deadline(payload: dict, sleep=time.sleep, clock=time.time) -> tuple[int, str]:
    """The waker: armed on an agent-shaped notice, it sleeps WINDOW and fires (exit 2, the text on stderr) when
    the batch it was armed for (opened no later than its arming), or any batch a minute past its deadline,
    is still open. Writes nothing."""
    armed = clock()
    path = _path(str(payload.get("session_id") or ""))
    if path is None or not switched_on() or not _notice(str(payload.get("prompt") or "")):
        return 0, ""
    sleep(WINDOW + 5)
    try:
        state = _load(path)
    except (OSError, ValueError):
        return 0, ""
    now = clock()
    if not state.get("held") or now < state["deadline"] or not (state["opened"] >= armed - 5 or now >= state["deadline"] + 60):
        return 0, ""
    return 2, (f"{DEADLINE_MARK}: the deadline of the held background returns passed ({len(state['held'])} held "
               f"since {_stamp(state['opened'])}); they are handed over with this notice.\n")


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    if sys.argv[1:] == ["--deadline"]:
        code, text = deadline(payload)
        sys.stderr.write(text)
        return code
    try:
        answer = decide(payload)
    except Exception:  # noqa: BLE001 - the prompt goes on
        return 0
    if answer is not None:
        print(json.dumps(answer))
    return 0


if __name__ == "__main__":
    sys.exit(main())
