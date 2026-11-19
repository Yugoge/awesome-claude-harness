"""When a dispatched agent stopped, and what it said then, read from what the CLI records:
the one reading of whether a dispatch has returned, for every hook that asks.

Its readers: G1's order rule (R17, hooks/pretool-obligation-gate.py), the /commit --bulk status block
(hooks/stop-command-gate.py), the landed close QA the close rating follows (close_rating.py) and the
producer whose owner questions come first (requirement_round.ask_first). Each took a dispatch as
returned only when its own Agent call had an ok tool_result; what the CLI records (2.1.326,
tests/fixtures/cli) brings an agent's end back otherwise too:
  - a background launch: its result ("async_launched") comes back at once, while the agent runs; the
    agent's end is its task-notification (command_span Span.agent_ends);
  - a SendMessage resume of the agent (Lesson 16's /restart, the /dev-overnight wake, or any other):
    the agent runs again from that SendMessage's result on, and its end is the task-notification that
    follows, naming the agent (<task-id>; its <tool-use-id> is the SendMessage's);
  - a cut call (an is_error result: an interrupt, the CLI's result for a call the session's end cut
    off) whose agent is not resumed: it stopped by itself only when its own transcript records that
    stop (_final_reply); an agent cut mid-turn did not.
A /restart journal that saw its resumes' responses (resumed_returns) counts as well. The agent stopped
when its latest stop follows its latest start (the dispatch, each resume); a failed or stopped
notification is no stop: no result came back. What it said at that stop is the text of that stop: its
Agent call's result, the notification's <result>, the resume's result, or its own last reply.

Stdlib only; subagent_restart (the /restart journal and account-root reader) is imported when asked.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path


def _lib(name: str):
    return importlib.import_module(f".{name}" if __package__ else name, __package__ or None)


def resumed_returns(span, session_id, before=None) -> dict:
    """{id of an Agent call that never came back: the ok SendMessage call whose result its agent's
    resume returned at} for the agents the /restart recovery resumed and saw come back
    (subagent_restart.completed_resumes, the journal Gate 4 reads; P1c R15): that call is its step's
    dispatch, with no replacement call (commands/restart.md, Lesson 16), and it returned when its
    resume did. Only the SendMessage calls ahead of call ``before`` count."""
    try:
        journal = _lib("subagent_restart").completed_resumes(session_id) if session_id else {}
    except Exception:
        return {}
    returns = {}
    for message in span.iter_calls("SendMessage", before=before) if journal else ():
        original = journal.get(str((message.input or {}).get("to")))
        if original and message.result_line and message.ok:
            returns[original] = message
    return returns


def meta_agent(transcript_path, tool_use_id: str) -> str:
    """The agent id whose meta file (agent-<id>.meta.json, which the CLI writes beside the agent's
    transcript when it starts) names ``tool_use_id``: a cut Agent call's result carries no agentId.
    The session's own subagents directory first, then the project's other sessions' (a session
    continued in another file keeps its agents under the first file's directory)."""
    main = Path(transcript_path)
    for pattern in (f"{main.stem}/subagents/agent-*.meta.json", "*/subagents/agent-*.meta.json"):
        for meta in main.parent.glob(pattern):
            try:
                if json.loads(meta.read_text(encoding="utf-8")).get("toolUseId") == tool_use_id:
                    return meta.name[len("agent-"):-len(".meta.json")]
            except (OSError, ValueError, AttributeError):
                continue
    return ""


def agent_transcript(transcript_path, agent: str):
    """The fullest copy of agent ``agent``'s own transcript (None when there is none): under this
    session's directory, else another session's of the project (a session continued in another
    file), and each other account root's copy of it (subagent_restart._child_transcript_copies, the
    reader /restart uses). Account roots each keep a partial view; the longest holds the most."""
    main = Path(transcript_path)
    found = [p for p in [main.with_suffix("") / "subagents" / f"agent-{agent}.jsonl"] if p.is_file()] or \
        sorted(main.parent.glob(f"*/subagents/agent-{agent}.jsonl"))
    try:
        copies = [Path(c) for path in found for c in _lib("subagent_restart")._child_transcript_copies(path)]
    except Exception:
        copies = found
    sizes = {c: c.stat().st_size for c in dict.fromkeys(copies) if c.is_file()}
    return max(sizes, key=sizes.get) if sizes else None


def _final_reply(path) -> dict | None:
    """The agent's last reply when its own transcript ends in a stop its SubagentStop hooks let stand:
    its last user or assistant record is an end_turn reply (no API error), followed by a SubagentStop
    hook record; else None. A stop a hook blocked is followed by the CLI's feedback record and more of
    the agent's turn, so its tail is not this one; nor is the tail of an agent cut mid-turn."""
    last, hooked = None, False
    turns = _lib("obligation").TURN_RECORD_TYPES
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                if record.get("type") in turns:
                    last, hooked = record, False
                elif record.get("type") == "attachment" and isinstance(record.get("attachment"), dict):
                    hooked = hooked or record["attachment"].get("hookEvent") == "SubagentStop"
    except OSError:
        return None
    message = last.get("message") if isinstance(last, dict) else None
    stopped = (hooked and isinstance(message, dict) and last.get("type") == "assistant"
               and not last.get("isApiErrorMessage") and message.get("stop_reason") == "end_turn")
    return message if stopped else None


def _text(message) -> str:
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, str) else "\n".join(
        b.get("text") or "" for b in (content if isinstance(content, list) else ())
        if isinstance(b, dict) and b.get("type") == "text")


class Returns:
    """When the agent of each dispatch in ``span`` stopped (a line of the transcript; 0 while it has
    not) and what it said then, read as this module's docstring says. ``before``: only the resumes,
    and the /restart journal's, ahead of that tool use count (G1 decides a dispatch before it runs).
    ``session_id`` names the /restart journal; by default the transcript's own name, which the CLI
    gives the session's file."""

    def __init__(self, span, session_id: str | None = None, before: str | None = None, transcript_path=None):
        self.span = span
        self.transcript = str(transcript_path or span.transcript_path or "")
        session = session_id or (Path(self.transcript).stem if self.transcript else None)
        self.journal = resumed_returns(span, session, before)
        self.ends = span.agent_ends()
        self.resumes = []
        for message in span.iter_calls("SendMessage", before=before):
            if message.ok and message.result_line:
                use = span.use_result(message.id)
                agent = use.get("resumedAgentId") or (message.input or {}).get("to")
                self.resumes.append((message.result_line, str(agent or "")))
        self.memo = {}

    def line(self, call) -> int:
        """The line at which the agent of dispatch ``call`` (a command_span Call) stopped; 0 while it
        has not: running, resumed and running again, cut mid-turn, failed, or never run (refused)."""
        return self._end(call)[0]

    def reply(self, call) -> str:
        """What the agent of dispatch ``call`` said when it stopped ('' while it has not)."""
        line, text = self._end(call)[:2]
        return text() if line else ""

    def agent(self, call) -> str:
        """The id of the agent dispatch ``call`` started ('' when none is known: a dispatch refused
        before it ran, or one whose agent left no record)."""
        return self._end(call)[2]

    def _end(self, call):
        if call.id not in self.memo:
            self.memo[call.id] = self._read(call)
        return self.memo[call.id]

    def _read(self, call):
        span = self.span
        use = span.use_result(call.id) if call.result_line else {}
        launched = use.get("isAsync") is True or use.get("status") == "async_launched"
        agent = str(use.get("agentId") or next(
            (e.agent for e in self.ends if e.tool_use_id == call.id and e.agent), "") or "")
        if not agent and call.result_line and not call.ok and self.transcript:
            agent = meta_agent(self.transcript, call.id)
        starts = [call.line] + [line for line, who in self.resumes if agent and who == agent and line > call.line]
        stops = [(call.result_line, lambda: span.result_text(call.id))] \
            if call.result_line and call.ok and not launched else []
        stops += [(e.line, lambda e=e: e.result) for e in self.ends if e.status == "completed" and e.line > call.line
                  and ((agent and e.agent == agent) or e.tool_use_id == call.id)]
        resumed = self.journal.get(call.id)
        stops += [(resumed.result_line, lambda: span.result_text(resumed.id))] if resumed else []
        stop = max(stops, key=lambda s: s[0], default=(0, None))
        if stop[0] and stop[0] >= max(starts):
            return stop[0], stop[1], agent
        if call.result_line and not call.ok and agent and max(starts) == call.line:
            own = agent_transcript(self.transcript, agent)
            final = _final_reply(own) if own is not None else None
            if final is not None:
                return call.result_line, lambda: _text(final), agent
        return 0, None, agent
