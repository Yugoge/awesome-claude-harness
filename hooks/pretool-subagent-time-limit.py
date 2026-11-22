#!/usr/bin/env python3
"""PreToolUse (every tool, subagents only): the time limit of a dispatched subagent.

The orchestrator's prompt cache lives one hour, so a subagent that returns later makes its
orchestrator write its whole context anew. A subagent's clock starts at the CLI's record of its
latest dispatch in the subagent's own transcript: its first record (the dispatch's prompt), or the
latest message a coordinator delivered to it (a resume by SendMessage, or a message to a running
child), whichever is later. The CLI writes those records and their timestamps; nothing the agent
writes or types is read. Foreground and background dispatches alike.

- Before LIMIT - lead: nothing. The lead is the longest a foreground Bash call may run (the tool's
  ceiling, 10 min), so a command started before the notice ends by LIMIT.
- From LIMIT - lead on: a foreground Bash call whose own timeout (or the tool's default, 2 min, when
  none is given) would end after LIMIT is refused (exit 2); every other call goes through, with the
  notice (additionalContext) to write the report and stop.
- From LIMIT on: only the report is let through, a Write or a Read of a .md or .json file that the
  dispatch's prompt or its latest message names by its path (not a link). Every other call is refused
  (exit 2), an /allow grant releasing one as it releases any refusal (lib/hook_launch.release_refused).
  The stop is no tool call: this rule never sees it, and the stop's own checks judge the report.

LIMIT is CLAUDE_SUBAGENT_TIME_LIMIT_MINUTES (default 55). A call of the main agent, a payload
without an agent id, a transcript that cannot be read: nothing. The hook writes nothing.
"""
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
import re
import time
from datetime import datetime

LIMIT_ENV, DEFAULT_LIMIT = "CLAUDE_SUBAGENT_TIME_LIMIT_MINUTES", 55.0
BASH_DEFAULT, BASH_MAX = ("BASH_DEFAULT_TIMEOUT_MS", 120000), ("BASH_MAX_TIMEOUT_MS", 600000)  # the CLI's own
REPORT_PATH = re.compile(r"[\w./~+-]*\w\.(?:md|json)\b")
AGENT_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


def limit_minutes() -> float:
    try:
        value = float(os.environ.get(LIMIT_ENV) or DEFAULT_LIMIT)
    except ValueError:
        return DEFAULT_LIMIT
    return value if value > 0 else DEFAULT_LIMIT


def _bash_minutes(setting) -> float:
    try:
        value = float(os.environ.get(setting[0]) or setting[1])
    except ValueError:
        value = setting[1]
    return (value if value > 0 else setting[1]) / 60000


def _shell_runs(data):
    """Minutes a foreground Bash call may run: its timeout, else the tool's default, at most the ceiling."""
    ask = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    if data.get("tool_name") != "Bash" or ask.get("run_in_background") is True:
        return None
    try:
        given = float(ask.get("timeout") or 0) / 60000
    except (TypeError, ValueError):
        given = 0
    return min(given if given > 0 else _bash_minutes(BASH_DEFAULT), _bash_minutes(BASH_MAX))


def _seconds(stamp):
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def _text(record) -> str:
    """The dispatch's or message's text a delivery record carries."""
    attachment = record.get("attachment") if isinstance(record.get("attachment"), dict) else {}
    content = attachment.get("prompt") or (record.get("message") or {}).get("content")
    if isinstance(content, list):
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content if isinstance(content, str) else ""


def latest_dispatch(transcript):
    """(seconds, texts) of the subagent's latest dispatch (lib/obligation.latest_delivery): the CLI's
    time on that record, and the texts of the first prompt and of that record; None when there is none."""
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    try:
        from lib import obligation
    finally:
        sys.path.pop(0)
    first, latest = obligation.latest_delivery(transcript)
    if first is None:
        return None
    start, texts = _seconds(first.get("timestamp")), [_text(first)]
    at = _seconds(latest.get("timestamp")) if latest is not None else None
    if at is not None and (start is None or at > start):
        start, texts = at, texts + [_text(latest)]
    return None if start is None else (start, texts)


def _report_target(data, texts) -> bool:
    """A Write or Read of a .md/.json file the dispatch's texts name, not through a link."""
    path = (data.get("tool_input") or {}).get("file_path") if data.get("tool_name") in ("Write", "Read") else None
    if not isinstance(path, str) or not REPORT_PATH.fullmatch(os.path.basename(path)) or os.path.islink(path):
        return False
    cwd, want = data.get("cwd") or os.getcwd(), os.path.normpath(os.path.join(data.get("cwd") or os.getcwd(), path))
    named = {os.path.normpath(os.path.join(cwd, os.path.expanduser(m))) for t in texts for m in REPORT_PATH.findall(t)}
    return want in named


def _dispatch_of(data):
    """latest_dispatch of the calling subagent, whose transcript the CLI keeps beside its parent's."""
    agent, parent = data.get("agent_id"), data.get("transcript_path")
    if not (data.get("tool_name") and isinstance(agent, str) and AGENT_ID.fullmatch(agent) and isinstance(parent, str) and parent):
        return None
    own = f"agent-{agent}.jsonl"
    return latest_dispatch(parent if os.path.basename(parent) == own else
                           os.path.join(os.path.splitext(parent)[0], "subagents", own))


def main() -> int:
    try:
        data = json.load(sys.stdin)
        found = _dispatch_of(data)
    except (OSError, ValueError, TypeError, AttributeError, ImportError):
        return 0
    if found is None:
        return 0
    limit, minutes = limit_minutes(), (time.time() - found[0]) / 60
    left = limit - minutes
    if left > _bash_minutes(BASH_MAX):
        return 0
    say = (f"In your report, say that the time limit stopped you and list what is left: in a dev report as an "
           f"entry of blocking_issues (\"time limit: stopped after {minutes:.0f} min; left: ...\"), and as the "
           f"first line of your final reply (\"Stopped by the {limit:g}-minute time limit.\").")
    runs = _shell_runs(data) if left > 0 else None
    if runs is not None and runs > left:
        sys.stderr.write(
            f"[subagent time limit] REFUSED: this command may run {runs:g} min (its timeout, or the Bash default "
            f"when none is given), but only {left:.1f} min are left before the {limit:g}-minute limit. Give it a "
            f"shorter timeout (under {int(left * 60000)} ms) or write your report now. {say}\n")
        return 2
    if left > 0:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": (
            f"[subagent time limit] {minutes:.0f} of {limit:g} minutes since your dispatch, {left:.1f} left. Write "
            f"your report now and stop: a shell command must end before minute {limit:g} (give it a timeout under "
            f"the time left), and from minute {limit:g} on only the Write of your report is let through. {say}")}}))
        return 0
    if _report_target(data, found[1]):
        return 0
    sys.stderr.write(
        f"[subagent time limit] REFUSED: {minutes:.0f} min since your dispatch, over the {limit:g}-minute limit "
        f"({LIMIT_ENV}). Only the report is let through: a Write (or a Read) of the .md or .json report your "
        f"dispatch names by its path. Write it now and stop. {say}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
