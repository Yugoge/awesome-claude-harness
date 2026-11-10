"""Read-only span reader for a main-session transcript (TC-4), and the one
rule of which transcript record is a prompt the human typed.

The span is the records after the latest human-typed harness command outside
CONTROL_COMMANDS. Every plain prompt continues it; built-in and plugin
commands, CONTROL commands and every record not typed by the human
(Skill-tool expansions, scheduled prompts, subagent records, tool results,
queue-operation and attachment records) never change it. P1 ships the span
itself, whose command G1 reads. P1b's E7 added the span's calls() and
last_todos(): every TodoWrite and Agent call the CLI ran is in the record, so
the checklist readers take them from here and no hook keeps a copy of them in
a file.

write_set() is TC-46's one write-set reader, for any transcript (a main
session's from its span opener on, or a subagent's whole file): the record the
CLI writes of the agent's own tool calls, never an agent's report of them.
P1b's E6 took it as the producer of "which files this agent wrote".

Stdlib only, importing no harness module (P5 R10): the Stop launcher loads
this module alone, so a broken stop_contract.py or coordinator leaves it
loadable. stop_contract.py re-exports the human-record rule from here. The
command sets live in stop-commands.json beside this file, which the launcher
reads too. Only human-typed records count; no CLI error or cancellation
record is read (D4c), and nothing an agent writes opens, replaces or closes a
span.
"""
from __future__ import annotations

import json
import os
import re
import stat
from collections import namedtuple
from datetime import datetime
from pathlib import Path

COMMANDS_DIR = Path(__file__).resolve().parent.parent.parent / "commands"
COMMAND_SETS_FILE = Path(__file__).resolve().parent / "stop-commands.json"


def _command_sets() -> tuple[tuple, tuple]:
    sets = json.loads(COMMAND_SETS_FILE.read_text(encoding="utf-8"))
    return tuple(sets["GATED_COMMANDS"]), tuple(sets["CONTROL_COMMANDS"])


# The commands a Stop gate guards, and the commands that never open a span.
GATED_COMMANDS, CONTROL_COMMANDS = _command_sets()

# Markers a typed prompt never carries: a Skill-tool expansion (isMeta,
# sourceToolUseID), a subagent's own records (isSidechain), a tool result, a
# compaction's summary (isCompactSummary; no isMeta or origin).
_NON_HUMAN_KEYS = ("isMeta", "isSidechain", "sourceToolUseID", "toolUseResult", "isCompactSummary")
# The CLI records a typed command as <command-message>..</command-message>
# <command-name>/x</command-name><command-args>..</command-args> at the start.
_CMD_TAG_RE = re.compile(
    r"\s*(?:<command-message>.*?</command-message>\s*)?<command-name>/?([A-Za-z0-9:_-]+)</command-name>", re.S
)
_ARGS_TAG_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
_SLASH_RE = re.compile(r"\s*/([A-Za-z0-9:_-]+)(?:\s+(.*))?\Z", re.S)


def harness_commands() -> frozenset:
    """commands/*.md stems of this harness, INDEX and README excluded."""
    try:
        return frozenset(p.stem for p in COMMANDS_DIR.glob("*.md") if p.stem not in ("INDEX", "README"))
    except OSError:
        return frozenset()


def prompt_text(record) -> str | None:
    """Text of a human-typed prompt record, else None (TC-4)."""
    if not isinstance(record, dict) or record.get("type") != "user":
        return None
    if any(record.get(key) for key in _NON_HUMAN_KEYS):
        return None
    for key in ("origin", "turnOrigin"):  # a typed prompt records origin kind "human"
        value = record.get(key)
        kind = value.get("kind") if isinstance(value, dict) else value
        if kind is not None and kind != "human":
            return None
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if not isinstance(content, list) or any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return None
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text") or None


def is_human_prompt(record) -> bool:
    return prompt_text(record) is not None


def slash_command(text: str) -> tuple[str, str] | None:
    """(name, args) of a slash command typed as ``/x`` or recorded as
    ``<command-name>/x</command-name>``, else None."""
    match = _CMD_TAG_RE.match(text)
    if match:
        args = _ARGS_TAG_RE.search(text)
        return match.group(1), (args.group(1).strip() if args else "")
    match = _SLASH_RE.match(text)
    return (match.group(1), (match.group(2) or "").strip()) if match else None


def span_opener(record, commands: frozenset) -> tuple[str, str] | None:
    """(command, args) when ``record`` is a human-typed harness command outside
    CONTROL_COMMANDS; built-in and plugin commands never qualify."""
    text = prompt_text(record)
    found = slash_command(text) if text is not None else None
    if found and found[0] in commands and found[0] not in CONTROL_COMMANDS:
        return found
    return None


def active_command(transcript_path) -> str | None:
    """The latest human-typed harness command outside CONTROL_COMMANDS in the
    whole transcript, or None (no such prompt, or the file is unreadable)."""
    found = openers(transcript_path)
    return found[-1][1] if found else None


def openers(transcript_path, commands: frozenset | None = None) -> list[tuple[int, str, str]]:
    """(line, command, args) of each human-typed harness command outside
    CONTROL_COMMANDS in the whole transcript, in order; [] when it cannot be
    read. ``commands`` defaults to this harness's commands/*.md stems."""
    commands = harness_commands() if commands is None else commands
    found = []
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, 1):
                if '"user"' not in line:
                    continue
                try:
                    opener = span_opener(json.loads(line), commands)
                except ValueError:
                    continue
                if opener:
                    found.append((number, opener[0], opener[1]))
    except (OSError, TypeError, ValueError):
        return []
    return found


def timelock_released(transcript_path) -> bool:
    """True iff the latest human-typed /stop or /dev-overnight record of the
    transcript is /stop: the human's /stop follows the session's latest
    /dev-overnight."""
    span = active_span(transcript_path, frozenset(("stop", "dev-overnight")))
    return span is not None and span.command == "stop"


class Call(namedtuple("Call", "id name input line result_line ok")):
    """One tool use of the main session and how it came back: its id, name
    and input, line (its tool_use record), result_line (its tool_result
    record; 0 while none came back) and ok (a non-error tool_result came
    back). Not a dataclass: the hooks that read a span run at every tool call,
    and importing dataclasses was a large share of what they cost."""
    __slots__ = ()


class Use(namedtuple("Use", "id name input ok result_at")):
    """A Call without line numbers: result_at is the offset in the transcript
    of the line holding its tool_result (None while none came back). The
    checklist readers order and filter calls but never name a line, and a
    span read from the end of a long transcript has not counted the lines
    before it."""
    __slots__ = ()


# A record is decoded only when it can matter, so a long session's transcript
# is not decoded whole at every tool call: its lines are picked by byte search.
# Quotes inside a JSON string are escaped, so text that merely mentions a
# needle never matches it.
_USER_RECORD = (b'"type":"user"', b'"type": "user"')
_RESULT_BLOCK = b'"tool_result"'
# Both spellings of a user record hold this one needle (its "type" and its
# message's "role"), so a reader from the end searches once, not once per
# spelling; each line it finds is then held to _USER_RECORD.
_USER_WORD = b'"user"'
_TAIL_CHUNK = 1 << 20  # the first read from the end; each further read doubles
_TAIL_LIMIT = 4 << 20  # the largest chunk read; a longer span is searched in a read of the whole file


def _read(transcript_path) -> bytes:
    with open(transcript_path, "rb") as handle:
        return handle.read()


class _Lines:
    """The lines of a transcript read as bytes, found by needle, numbered from 1
    (from ``line`` at offset ``pos``, for a reader that starts mid-file)."""

    def __init__(self, data: bytes, pos: int = 0, line: int = 1):
        self.data, self._pos, self._line = data, pos, line

    def _number(self, pos: int) -> int:
        """Line number of offset ``pos``; offsets must come in increasing order."""
        self._line += self.data.count(b"\n", self._pos, pos)
        self._pos = pos
        return self._line

    def _bounds(self, pos: int) -> tuple[int, int]:
        end = self.data.find(b"\n", pos)
        return self.data.rfind(b"\n", 0, pos) + 1, end if end >= 0 else len(self.data)

    def offsets(self, needles, start: int = 0, unless: bytes = b""):
        """(begin, end) offsets of each line from offset ``start`` that holds a
        needle and not ``unless``, once per line, in order, found only as far as
        the caller reads. Not numbered: a reader that only orders lines
        compares offsets, and numbering the lines of a long transcript is a
        pass of its own."""
        found = {needle: self.data.find(needle, start) for needle in needles}
        while True:
            live = [pos for pos in found.values() if pos >= 0]
            if not live:
                return
            begin, end = self._bounds(min(live))
            if not (unless and self.data.find(unless, begin, end) >= 0):
                yield begin, end
            for needle, pos in found.items():  # past this line, once the caller reads on
                if 0 <= pos < end:
                    found[needle] = self.data.find(needle, end)

    def having(self, needles, after: int = 0, start: int = 0, unless: bytes = b""):
        """(number, end offset, line) of each line from offset ``start`` and
        after line ``after`` that holds a needle and not ``unless``, once per
        line, in order, found only as far as the caller reads."""
        for begin, end in self.offsets(needles, start, unless):
            number = self._number(begin)
            if number > after:
                yield number, end, self.data[begin:end]

    def having_back(self, needles, floor: int = 0, top: int | None = None):
        """(begin, end, line) of each line that starts at offset ``floor`` or
        later, ends by offset ``top`` and holds a needle, once per line, newest
        first: the lines having() yields, in reverse, without a pass over the
        lines before the ones the caller reads. A needle holds no newline, so
        the line of each find starts at or after ``floor``, a line start."""
        top = len(self.data) if top is None else top
        found = {needle: self.data.rfind(needle, floor, top) for needle in needles}
        while True:
            live = [pos for pos in found.values() if pos >= 0]
            if not live:
                return
            begin, end = self._bounds(max(live))
            yield begin, end, self.data[begin:end]
            for needle, pos in found.items():  # before this line, once the caller reads on
                if pos >= begin:
                    found[needle] = self.data.rfind(needle, floor, begin)

    def start_of(self, line: int) -> int:
        """Offset of the line after line ``line`` (past the end when there is none)."""
        pos = 0
        for _ in range(line):
            pos = self.data.find(b"\n", pos)
            if pos < 0:
                return len(self.data) + 1
            pos += 1
        return pos


def _decode(raw: bytes) -> dict | None:
    try:
        record = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def _blocks(record: dict | None):
    if not record or record.get("isSidechain"):  # a subagent's own record
        return ()
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else ()


def _uses(raw: bytes, names) -> list:
    """The main session's tool_use blocks in one record line (only ``names``
    when given)."""
    return [block for block in _blocks(_decode(raw))
            if block.get("type") == "tool_use" and isinstance(block.get("input"), dict)
            and (not names or block.get("name") in names)]


def _result(lines: _Lines, end: int, ident: str) -> tuple:
    """(offset of the line holding the tool_result of call ``ident``, ok) for
    a use whose line ends at offset ``end``; (None, False) while none came
    back. Its result comes later: a reader from the end of the use's line."""
    for begin, stop in (lines.offsets((json.dumps(ident).encode(),), start=end) if ident else ()):
        found, ok = None, False
        for result in _blocks(_decode(lines.data[begin:stop])):
            if result.get("type") == "tool_result" and result.get("tool_use_id") == ident:
                found, ok = begin, not result.get("is_error")
        if found is not None:
            return found, ok
    return None, False


def _call(lines: _Lines, number: int, end: int, block: dict) -> Call:
    """The Call of a tool_use block on line ``number``, which ends at offset
    ``end``, and how it came back."""
    ident = block.get("id") or ""
    found, ok = _result(lines, end, ident)
    result_line = 0 if found is None else number + lines.data.count(b"\n", end, found)
    return Call(id=ident, name=block.get("name") or "", input=block["input"],
                line=number, result_line=result_line, ok=ok)


# An id of these characters is written in the record as its JSON string, the
# way a call's result is found by it; any other id is read call by call.
_PLAIN_ID = re.compile(r"[A-Za-z0-9_-]+\Z")
_UNREAD = object()


def _first_use(lines: _Lines, needles, names, floor: int, ident: str):
    """(begin, end, the calls ahead of it) of the line holding the first call
    from offset ``floor`` on that has id ``ident``; None when no call has it,
    _UNREAD when the id may be written otherwise. Only the lines that hold the
    id and a needle are decoded."""
    if not _PLAIN_ID.match(ident):
        return _UNREAD
    token = json.dumps(ident).encode()
    pos = lines.data.find(token, floor)
    while pos >= 0:
        begin, end = lines._bounds(pos)
        raw = lines.data[begin:end]
        if any(needle in raw for needle in needles):
            uses = _uses(raw, names)
            for k, block in enumerate(uses):
                if (block.get("id") or "") == ident:
                    return begin, end, uses[:k]
        pos = lines.data.find(token, end)
    return None


class Span:
    """The command that opened the span, its arguments and its opener's line.
    It keeps the bytes active_span read, so its calls come from that one read
    of a transcript the CLI keeps appending to. Compared and shown by command,
    args and start_line only; a plain class for the reason Call is not a
    dataclass.

    active_span reads a long transcript from its end and keeps only the bytes
    from the last chunk it read on (``base`` is their offset in the file), so
    a span costs what the span costs, not what the session costs. Its
    start_line then counts the lines before those bytes when first asked:
    only a reader that numbers lines pays for the lines before the span."""
    __slots__ = ("command", "args", "_start_line", "transcript_path", "_data", "_floor", "_base", "_ahead")

    def __init__(self, command: str, args: str, start_line: int | None, transcript_path: str = "",
                 data: bytes | None = None, floor: int | None = None, base: int = 0, ahead=None):
        self.command, self.args, self._start_line = command, args, start_line
        self.transcript_path = transcript_path
        self._data = data  # None: read transcript_path when asked
        self._floor = floor  # offset of the line after start_line in data; None: found when asked
        self._base = base  # offset of data in the transcript
        self._ahead = ahead  # (open transcript, offset of the opener in data) while start_line is None

    @property
    def start_line(self) -> int:
        if self._start_line is None:
            handle, opener = self._ahead
            with handle:  # the file the span was read from, so the count is of the same bytes
                self._start_line = 1 + _newlines(handle, self._base) + self._data.count(b"\n", 0, opener)
            self._ahead = None
        return self._start_line

    def __del__(self):  # a span whose lines nobody numbered closes the file it kept for that
        ahead = getattr(self, "_ahead", None)
        if ahead is not None:
            ahead[0].close()

    def __repr__(self):
        return (f"{self.__class__.__qualname__}(command={self.command!r}, args={self.args!r}, "
                f"start_line={self.start_line!r})")

    def __eq__(self, other):
        if self is other:
            return True
        if other.__class__ is self.__class__:
            return self.command == other.command and self.args == other.args and self.start_line == other.start_line
        return NotImplemented

    __hash__ = None

    def calls(self, *names: str) -> list[Call]:
        """The main session's tool uses in the span (only ``names`` when
        given), in transcript order. A subagent's own records (isSidechain)
        are not the session's calls."""
        return list(self.iter_calls(*names))

    def _lines(self):
        """(_Lines over the span's bytes, offset of the line after the opener)."""
        lines = _Lines(self._data if self._data is not None else _read(self.transcript_path))
        if self._data is not None and self._floor is not None:
            return lines, self._floor
        return lines, lines.start_of(self.start_line)

    def iter_calls(self, *names: str, newest_first: bool = False, before: str | None = None):
        """calls() one at a time, newest first on request; with ``before`` (a
        tool use id) only the calls ahead of the first call that has it. A
        record is decoded when the reader reaches it, so a reader that stops
        at the first call it wants leaves the rest of a long span undecoded,
        and a reader from the end finds its lines from the end: the newest
        call of a long session costs no pass over the lines before it."""
        try:
            lines, floor = self._lines()
        except (OSError, TypeError, ValueError):
            return
        # A line's number counts the newlines before it, once: from the
        # span's first line to the first line read, then on from there.
        pos = number = None
        for begin, end, block in _found(lines, floor, names, newest_first, before):
            if number is None:
                number = self.start_line + 1 + lines.data.count(b"\n", floor, begin)
            elif begin >= pos:
                number += lines.data.count(b"\n", pos, begin)
            else:
                number -= lines.data.count(b"\n", begin, pos)
            pos = begin
            yield _call(lines, number, end, block)

    def uses(self, *names: str, newest_first: bool = False, before: str | None = None):
        """iter_calls() as Use records: the same calls in the same order, with
        their results' offsets in place of line numbers, so a reader that
        orders and filters calls never counts the lines before the span."""
        try:
            lines, floor = self._lines()
        except (OSError, TypeError, ValueError):
            return
        for _begin, end, block in _found(lines, floor, names, newest_first, before):
            ident = block.get("id") or ""
            found, ok = _result(lines, end, ident)
            yield Use(id=ident, name=block.get("name") or "", input=block["input"], ok=ok,
                      result_at=None if found is None else self._base + found)

    def last_todos(self, before: str | None = None) -> list | None:
        """The todos of the span's last ok TodoWrite, or None before the
        first; with ``before``, of the last one issued before that tool use
        (a PostToolUse reader names its own call, already in the record)."""
        todos = None
        for call in self.calls("TodoWrite"):
            if before and call.id == before:
                break
            if call.ok and isinstance(call.input.get("todos"), list):
                todos = call.input["todos"]
        return todos

    def result_text(self, ident: str) -> str:
        """The text of call ``ident``'s tool_result in the span ('' while none came back); an Agent
        call's is the agent's own reply, its record's toolUseResult content without the agentId trailer."""
        try:
            lines, floor = self._lines()
        except (OSError, TypeError, ValueError):
            return ""
        for begin, end in lines.offsets((json.dumps(ident).encode(),), floor):
            record = _decode(lines.data[begin:end])
            for block in _blocks(record):
                if block.get("type") == "tool_result" and block.get("tool_use_id") == ident:
                    own = record.get("toolUseResult")
                    content = own["content"] if isinstance(own, dict) and isinstance(own.get("content"), list) \
                        else block.get("content")
                    return content if isinstance(content, str) else "\n".join(
                        b.get("text") or "" for b in (content if isinstance(content, list) else ())
                        if isinstance(b, dict) and b.get("type") == "text")
        return ""

    def obligations(self) -> list:
        """(call, obligation) of each ok Agent/Task dispatch whose prompt parses to an obligation, in span order."""
        ob = _obligation()
        parsed = ((c, ob.parse_obligation(c.input.get("prompt"))) for c in self.calls("Agent", "Task") if c.ok)
        return [(call, found.obligation) for call, found in parsed if isinstance(found, ob.ParsedObligation)]

    def session_families(self) -> set:
        """The task families (obligation.task_family) of the span's ok
        dispatches whose artifacts are the task's: a dispatch whose file
        artifacts are all named otherwise (a session-level report: an
        overnight triage, a retrospective) stamps an id but works on no task."""
        ob, families = _obligation(), set()
        for _call, doc in self.obligations():
            task = ob.canonical_task_id(doc.get("task_id"))
            paths = [a.get("path") for a in doc.get("artifacts") or () if isinstance(a, dict) and a.get("path")]
            if task and (not paths or any(task in str(path) for path in paths)):
                families.add(ob.task_family(task))
        return families

    def opened_at(self) -> float | None:
        """The time the CLI recorded for the opener (seconds since the epoch);
        None when its record carries none."""
        lines, floor = self._lines()
        end = min(floor, len(lines.data) + 1) - 1  # the opener line's end
        record = _decode(lines.data[lines.data.rfind(b"\n", 0, max(end, 0)) + 1:end]) or {}
        try:
            return datetime.fromisoformat(str(record.get("timestamp")).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None

    def minted_id(self) -> str | None:
        """The task id the UserPromptSubmit hook printed for the opener
        (MINTED_LINE_RE): the first in the opener's hook context."""
        return next((found.group(1) for found in self._opener_context(MINTED_LINE_RE)), None)

    def opener_heads(self) -> list:
        """(branch, commit) of each HEAD line the UserPromptSubmit hook printed for a /push opener
        (OPENER_HEAD_LINE_RE; branch None: HEAD detached), in order; [] for an opener with none
        (one typed before the hook printed it)."""
        return [(None if found.group(1) == "detached" else found.group(1)[len("refs/heads/"):], found.group(2))
                for found in self._opener_context(OPENER_HEAD_LINE_RE)]

    def opener_remotes(self) -> dict | None:
        """{remote: (URL digest, the branch HEAD was on or "-", that branch's tracking ref's commit or
        None, the branch's upstream ref there or None)} of the remote lines the UserPromptSubmit hook
        printed for a /push opener (OPENER_REMOTE_LINE_RE); a remote printed twice unlike is left out (a
        line another hook echoes can only take that remote out of what releases the Stop); None for an
        opener with none (typed before the hook printed them, or a hook that prints none)."""
        found = {}
        for match in self._opener_context(OPENER_REMOTE_LINE_RE):
            record = (match.group(2), match.group(3), None if match.group(4) == "none" else match.group(4),
                      match.group(5))
            found[match.group(1)] = record if found.get(match.group(1), record) == record else ()
        return {name: record for name, record in found.items() if record} if found else None

    def _opener_context(self, regex):
        """The matches of ``regex`` in the opener's hook context: the context
        records the CLI writes after the typed prompt and before the turn's
        first assistant record. An agent's echo of a line (its text, a tool
        result) is never read."""
        lines, pos = self._lines()
        data = lines.data
        while pos < len(data):
            end = data.find(b"\n", pos)
            end = len(data) if end < 0 else end
            raw = data[pos:end]
            if b'"type":"assistant"' in raw or b'"type": "assistant"' in raw:
                return
            attachment = (_decode(raw) or {}).get("attachment") if b"hook_additional_context" in raw else None
            if isinstance(attachment, dict) and attachment.get("type") == "hook_additional_context":
                content = attachment.get("content")
                if isinstance(content, list):
                    content = "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
                yield from regex.finditer(content) if isinstance(content, str) else ()
            pos = end + 1

    def write_set(self, project_dir, actor: str | None = "main", stop_line: int | None = None):
        """write_set() of the span: the files written or named after its
        opener and before line ``stop_line`` (the next opener, when given), by
        ``actor``: "main", the main session's own calls (no subagent's
        isSidechain record), or None, every record."""
        return write_set(self.transcript_path, project_dir, self.start_line, stop_line=stop_line,
                         main_only=actor == "main")


    def body(self) -> str | None:
        """The command's text as this session loaded it: the isMeta record the
        CLI writes when the command is typed, whose parentUuid is the opener's
        uuid (CLI 2.1.319: commands/<command>.md minus its frontmatter, with
        $ARGUMENTS filled in). It is written once, so a later edit of the file
        leaves it as it was: a session that started before an update follows
        this text, not the file on disk. None when no such record follows the
        opener."""
        try:
            lines, floor = self._lines()
        except (OSError, TypeError, ValueError):
            return None
        opener = _decode(lines.data[lines.data.rfind(b"\n", 0, floor - 1) + 1:floor - 1])
        ident = opener.get("uuid") if opener else None
        if not isinstance(ident, str) or not ident:
            return None
        for begin, end in lines.offsets((json.dumps(ident).encode(),), floor):
            record = _decode(lines.data[begin:end])
            if not record or record.get("parentUuid") != ident:
                continue
            if record.get("type") != "user" or not record.get("isMeta"):
                return None
            content = record["message"].get("content") if isinstance(record.get("message"), dict) else None
            if isinstance(content, str):
                return content
            return "".join(b.get("text", "") for b in _blocks(record) if b.get("type") == "text")
        return None


# The task-id lines the UserPromptSubmit hook prints for a /do and a /dev-family opener.
MINTED_LINE_RE = re.compile(
    r"^(?:\[/do\] task-id minted|DEV_SESSION_ID pre-initialized by hook): ([A-Za-z0-9._-]+)", re.M)
# The HEAD line it prints for a /push opener (prompt-workflow.py print_push_head).
OPENER_HEAD_LINE_RE = re.compile(r"^\[/push\] HEAD at the opener: (refs/heads/\S+|detached) ([0-9a-f]{40}(?:[0-9a-f]{24})?)$",
                                 re.M)


# Its remote lines for that opener (P5-61; prompt-workflow.py print_push_head is to print them): an opener
# without them has the /push Stop read the remotes from the repository.
OPENER_REMOTE_LINE_RE = re.compile(r"^\[/push\] remote at the opener: (\S+) ([0-9a-f]{16}) (\S+) "
                                   r"([0-9a-f]{40}(?:[0-9a-f]{24})?|none)(?: upstream (refs/\S+))?$", re.M)


def _obligation():  # imported when first asked: a reader that needs none loads none of it
    import importlib
    return importlib.import_module(f"{__package__}.obligation" if __package__ else "obligation")


def _found(lines: _Lines, floor: int, names, newest_first: bool, before: str | None):
    """(begin, end, block) of each main-session tool_use block from offset
    ``floor`` on (only ``names`` when given), in the order Span.iter_calls
    yields them; with ``before`` only those ahead of the first that has it."""
    needles = [f'"{n}"'.encode() for n in names] if names else [b'"tool_use"']
    if not newest_first:
        for begin, end in lines.offsets(needles, floor):
            for block in _uses(lines.data[begin:end], names):
                if before and (block.get("id") or "") == before:
                    return
                yield begin, end, block
        return
    top, cut = None, None
    if before:
        first = _first_use(lines, needles, names, floor, before)
        if first is _UNREAD:  # the record may spell the id otherwise: read it as calls() does
            yield from reversed(list(_found(lines, floor, names, False, before)))
            return
        if first is not None:
            cut = first  # the first call with the id: its line's calls ahead of it are the newest
            top = cut[1]
    for begin, end, raw in lines.having_back(needles, floor, top):
        uses = cut[2] if cut is not None and begin == cut[0] else _uses(raw, names)
        for block in reversed(uses):
            yield begin, end, block


def _newlines(handle, stop: int) -> int:
    """The newlines in the first ``stop`` bytes of an open file."""
    handle.seek(0)
    count, left = 0, stop
    while left > 0:
        piece = handle.read(min(left, 8 * _TAIL_CHUNK))
        if not piece:
            break
        count += piece.count(b"\n")
        left -= len(piece)
    return count


def _records(transcript_path: str | Path) -> list[tuple[int, dict]]:
    records = []
    with open(transcript_path, encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, 1):
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                records.append((number, record))
    return records


def _last_opener(data: bytes, lo: int, hi: int, commands: frozenset):
    """(begin, end, (command, args)) of the last human-typed harness command
    among the whole lines of data[lo:hi], or None. Lines are read from the end
    and decoded only when they hold a user record and no tool result (a tool
    result is never typed). A tool result's line is told by the result token
    near its start, so the search for its end is left out: in a long span
    most lines are read once, by the search for the next user record."""
    pos = data.rfind(_USER_WORD, lo, hi)
    while pos >= 0:
        newline = data.rfind(b"\n", lo, pos)
        begin = newline + 1 if newline >= 0 else lo
        result = data.find(_RESULT_BLOCK, begin, hi)
        if result < 0 or data.find(b"\n", begin, result) >= 0:  # no tool result on this line
            end = data.find(b"\n", pos, hi)
            end = hi if end < 0 else end
            if any(data.find(needle, begin, end) >= 0 for needle in _USER_RECORD):
                record = _decode(data[begin:end])
                opener = span_opener(record, commands) if record else None
                if opener:
                    return begin, end, opener
        pos = data.rfind(_USER_WORD, lo, begin)
    return None


def _piece(handle, base: int, chunk: int) -> bytes | None:
    """The ``chunk`` bytes before offset ``base`` (fewer at the start of the
    file); None when the file no longer holds them (it shrank since it was
    sized)."""
    start = max(0, base - chunk)
    handle.seek(start)
    piece = handle.read(base - start)
    return piece if len(piece) == base - start else None


def active_span(transcript_path: str | Path, commands: frozenset | None = None) -> Span | None:
    """The active span, or None when no human-typed harness command opened one
    or the transcript cannot be read. ``commands`` defaults to this harness's
    commands/*.md stems.

    The last opener is the first one a reader from the end meets, so the
    transcript is read from its end, in chunks that double up to
    _TAIL_LIMIT, and searched back until it is met: the lines before the span
    are neither read nor decoded. A span longer than those chunks is searched
    in one read of the whole file, as copying ever larger chunks together
    would cost more than reading the file once."""
    commands = harness_commands() if commands is None else commands
    try:
        handle = open(transcript_path, "rb")
        info = os.fstat(handle.fileno())
        # A file with no end to read from (not a regular file) is read whole.
        data, base = (b"", info.st_size) if stat.S_ISREG(info.st_mode) else (handle.read(), 0)
    except (OSError, TypeError, ValueError):
        return None
    size, chunk = base + len(data), _TAIL_CHUNK
    top = size  # the lines from offset top on hold no opener
    while True:
        if base == 0:
            found = _last_opener(data, 0, top, commands)
            break
        try:
            piece = _piece(handle, base, chunk) if chunk <= _TAIL_LIMIT else None
            if piece is None:  # the whole file as it was sized, in one read
                handle.seek(0)
                data, base = handle.read(size), 0
                if len(data) < size:  # it shrank since: search all of it, as one read of it would
                    top = len(data)
                continue
        except (OSError, ValueError):
            handle.close()
            return None
        data, base, chunk = piece + data, base - len(piece), chunk * 2
        if base == 0:
            continue
        newline = data.find(b"\n", 0, top - base)  # the line before it may start in an earlier chunk
        if newline < 0:
            continue
        found = _last_opener(data, newline + 1, top - base, commands)
        if found:
            break
        top = base + newline + 1
    if not found:
        handle.close()
        return None
    begin, end, (command, args) = found
    if base == 0:
        handle.close()
        return Span(command=command, args=args, start_line=1 + data.count(b"\n", 0, begin),
                    transcript_path=str(transcript_path), data=data, floor=end + 1)
    return Span(command=command, args=args, start_line=None, transcript_path=str(transcript_path),
                data=data, floor=end + 1, base=base, ahead=(handle, begin))


def transcript_span(transcript_path) -> Span:
    """The whole transcript read as one span from its first line, for a decider on the session's
    calls whatever span is active (the overnight time-lock's wake check)."""
    return Span("", "", 0, str(transcript_path))


def recorded_result(transcript_path, use) -> dict:
    """The toolUseResult the CLI recorded beside ``use``'s tool_result (a CronCreate's job id),
    {} while none came back or it holds none."""
    try:
        with open(transcript_path, "rb") as handle:
            handle.seek(use.result_at)
            record = _decode(handle.readline())
    except (OSError, TypeError, ValueError):
        return {}
    value = record.get("toolUseResult") if record else None
    return value if isinstance(value, dict) else {}


EDIT_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path",
              "NotebookEdit": "notebook_path"}
# Trees an agent writes as the pipeline's own bookkeeping, not as product files.
EXCLUDED_TREES = ("docs/dev/", ".claude/dev-registry/", ".claude/scratch/")
_PATH_RUN = re.compile(r"[A-Za-z0-9_.@%+~/-]+")


class WriteSet(namedtuple("WriteSet", "written named")):
    """written: the Write/Edit/MultiEdit/NotebookEdit targets with an ok
    tool_result; named: the paths the transcript's own Bash commands name."""
    __slots__ = ()


def _project_relative(raw: str, cwd: str, root: str, excluded=EXCLUDED_TREES) -> str | None:
    path = os.path.expanduser(raw)
    if not os.path.isabs(path):
        path = os.path.join(cwd or root, path)
    rel = os.path.relpath(os.path.normpath(path), root)
    if rel in (".", "..", ".git") or rel.startswith(("../", ".git/")):
        return None
    return None if excluded and rel.startswith(tuple(excluded)) else rel


def _bash_named(command: str, cwd: str, root: str) -> set[str]:
    # A shell command's writes cannot be parsed (interpreters write from inside
    # code), so every path the text names counts: a run of path characters that
    # is a file inside the project now, or has a directory part and a dotted name.
    named = set()
    for token in _PATH_RUN.findall(command):
        if token in (".", "..") or token.startswith("-"):
            continue
        rel = _project_relative(token, cwd, root)
        if rel is None:
            continue
        shaped = "/" in token and "." in os.path.basename(token).strip(".")
        if shaped or os.path.isfile(os.path.join(root, rel)):
            named.add(rel)
    return named


def write_set(transcript_path: str | Path, project_dir: str | Path, start_line: int = 0,
              excluded=EXCLUDED_TREES, stop_line: int | None = None, main_only: bool = False) -> WriteSet | None:
    """The project-relative files the transcript's own tool calls after
    ``start_line`` (and before ``stop_line``) wrote or named (TC-46), outside
    ``excluded`` (a caller asking which reports an agent wrote passes none);
    with ``main_only`` a subagent's own records (isSidechain) are left out.
    None when the transcript cannot be read."""
    root = os.path.normpath(str(project_dir))
    try:
        records = _records(transcript_path)
    except (OSError, TypeError, ValueError):
        return None
    uses, ok = [], set()
    for number, record in records:
        if number <= start_line or (main_only and record.get("isSidechain")):
            continue
        if stop_line is not None and number >= stop_line:
            break
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else ():
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                uses.append((block.get("id"), block.get("name"), block["input"], record.get("cwd") or root))
            elif block.get("type") == "tool_result" and not block.get("is_error"):
                ok.add(block.get("tool_use_id"))
    written, named = set(), set()
    for use_id, name, tool_input, cwd in uses:
        if name in EDIT_TOOLS:
            target = tool_input.get(EDIT_TOOLS[name])
            rel = (_project_relative(target, cwd, root, excluded)
                   if use_id in ok and isinstance(target, str) and target else None)
            if rel:
                written.add(rel)
        elif name == "Bash" and isinstance(tool_input.get("command"), str):
            named |= _bash_named(tool_input["command"], cwd, root)
    return WriteSet(written=frozenset(written), named=frozenset(named))
