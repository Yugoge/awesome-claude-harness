#!/usr/bin/env python3
"""PostToolUse (a dispatch tool): the returned lane's state and its gated command's open gaps, added to the return.

handback(payload) is the content, for the orchestrator (no agent_id) inside a gated command's span
(command_span.GATED_COMMANDS), else None: each report the dispatch's obligation declares, read from
disk (its status at the schema's terminal field, its blocking_issues, the declared paths that are
gaps by declared_absence.absent), then the Stop gate's own text for this moment: hooks/stop-command-gate.py
run as the Stop runs it, its process group ended at BOUND seconds, when one line says so. A foreground
dispatch's PostToolUse prints it as additionalContext (main); a dispatch moved to the background has
not run yet there, and gets it when its child ends, from the point that sees that end calling
handback() with the dispatch's payload. It reads; it writes nothing.
"""
import json
import os
import signal
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import command_span, declared_absence, obligation  # noqa: E402
from lib.subagent import DISPATCH_TOOLS  # noqa: E402

GATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stop-command-gate.py")
BOUND = 20.0  # seconds; the Stop predicate took 10-15 s on the largest recorded session
SHOWN, CUT = 5, 200  # entries shown per list, characters per entry


def _listed(name: str, items: list) -> str:
    shown = [(i if isinstance(i, str) else json.dumps(i, ensure_ascii=False))[:CUT] for i in items[:SHOWN]]
    more = f"; ... {len(items) - SHOWN} more" if len(items) > SHOWN else ""
    return f"{name} {len(items)}" + (": " + "; ".join(shown) + more if items else "")


def _report(root: str, artifact: dict) -> str:
    path, schema = artifact["path"], artifact.get("schema")
    try:
        with open(os.path.join(root, path), encoding="utf-8") as handle:
            record = json.load(handle) if artifact["kind"] == "json" else None
    except FileNotFoundError:
        return f"- {path}: absent"
    except (OSError, ValueError) as exc:
        return f"- {path}: unreadable ({type(exc).__name__})"
    if not isinstance(record, dict):
        return f"- {path}: present"
    dotted = next(iter(obligation.TERMINAL_VOCABULARY.get(schema, {})), "status")
    value = record
    for part in dotted.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    terminal = "" if obligation.terminal_status(schema, record) else " (not terminal)"
    section = next((v for v in record.values() if isinstance(v, dict) and "blocking_issues" in v), {})
    blockers = record.get("blocking_issues", section.get("blocking_issues"))
    gone = declared_absence.absent(root, record) if declared_absence.declared(record) else []
    return (f"- {path}: {dotted} {value!r}{terminal}; "
            f"{_listed('blocking_issues', blockers if isinstance(blockers, list) else [])}; "
            f"{_listed('declared paths absent', gone)}")


def lane_state(root: str, tool_input: dict) -> str:
    parsed = obligation.parse_obligation(str(tool_input.get("prompt") or ""))
    head = f"Returned dispatch ({tool_input.get('subagent_type') or 'general-purpose'}"
    if not isinstance(parsed, obligation.ParsedObligation):
        why = "no obligation block" if isinstance(parsed, obligation.NoBlock) else f"obligation refused: {parsed.reason}"
        return f"{head}): declares no report ({why})\n"
    doc = parsed.obligation
    lines = [_report(root, a) for a in doc["artifacts"] if isinstance(a.get("path"), str)]
    return f"{head}, lane {doc.get('lane') or '-'}, task {doc.get('task_id')}):\n" + "".join(f"{x}\n" for x in lines)


def gaps(payload: dict) -> str:
    """The Stop gate's text for this moment (empty: it would allow), or one line when it took over BOUND s."""
    stop = {k: payload.get(k) for k in ("session_id", "transcript_path", "cwd", "permission_mode")}
    proc = subprocess.Popen([sys.executable, GATE, "--mode", "block"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, start_new_session=True)
    try:
        return proc.communicate(json.dumps({**stop, "hook_event_name": "Stop"}).encode(), timeout=BOUND)[1] \
            .decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        return f"COMMAND_GATE open gaps not listed: the Stop gate took over {BOUND:g} s; they are listed at the Stop.\n"


def handback(payload: dict) -> str | None:
    """The text a returned dispatch of the orchestrator carries inside a gated command; None elsewhere."""
    if payload.get("agent_id") or payload.get("tool_name") not in DISPATCH_TOOLS:
        return None
    span = command_span.active_span(payload.get("transcript_path") or "")
    if span is None or span.command not in command_span.GATED_COMMANDS:
        return None
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    try:
        state = lane_state(root, tool_input)
    except Exception as exc:  # the gaps below still come
        state = f"Returned dispatch: its report could not be read: {type(exc).__name__}: {exc}\n"
    if os.environ.get("CLAUDE_COMMAND_GATE") == "off":
        return state
    return state + (gaps(payload) or f"COMMAND_GATE /{span.command}: the Stop gate lists no open gap now.\n")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        response = payload.get("tool_response")
        moved = (payload.get("tool_input") or {}).get("run_in_background") in (True, "true") or (
            isinstance(response, dict) and response.get("status") == "async_launched")
        text = None if moved else handback(payload)  # a background child has not run yet: its end hands it over
    except Exception:
        return 0  # the return is never held up
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
