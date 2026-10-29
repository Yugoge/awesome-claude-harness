"""Read-only span reader for a main-session transcript (TC-4).

The span is the records after the latest human-typed harness command outside
stop_contract.CONTROL_COMMANDS. Every plain prompt continues it; built-in and
plugin commands, CONTROL commands and every record not typed by the human
(Skill-tool expansions, subagent records, tool results, queue-operation and
attachment records) never change it. The opener rule lives in stop_contract.
P1 ships the span itself, whose command G1 reads. P1b's E7 added the span's
calls() and last_todos(): every TodoWrite and Agent call the CLI ran is in the
record, so the checklist readers take them from here and no hook keeps a copy
of them in a file.

write_set() is TC-46's one write-set reader, for any transcript (a main
session's from its span opener on, or a subagent's whole file): the record the
CLI writes of the agent's own tool calls, never an agent's report of them.
P1b's E6 took it as the producer of "which files this agent wrote".
"""
from __future__ import annotations

import json
import os
import re
from collections import namedtuple
from pathlib import Path

try:  # imported as hooks.lib.command_span (tests) or lib.command_span (hooks)
    from . import stop_contract
except ImportError:  # hooks/lib placed directly on sys.path
    import stop_contract  # type: ignore[no-redef]


class Call(namedtuple("Call", "id name input line result_line ok")):
    """One tool use of the main session and how it came back: its id, name
    and input, line (its tool_use record), result_line (its tool_result
    record; 0 while none came back) and ok (a non-error tool_result came
    back). Not a dataclass: the hooks that read a span run at every tool call,
    and importing dataclasses was a large share of what they cost."""
    __slots__ = ()


# A record is decoded only when it can matter, so a long session's transcript
# is not decoded whole at every tool call: its lines are picked by byte search.
# Quotes inside a JSON string are escaped, so text that merely mentions a
# needle never matches it.
_USER_RECORD = (b'"type":"user"', b'"type": "user"')
_RESULT_BLOCK = b'"tool_result"'


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

    def having(self, needles, after: int = 0, start: int = 0, unless: bytes = b""):
        """(number, end offset, line) of each line from offset ``start`` and
        after line ``after`` that holds a needle and not ``unless``, once per
        line, in order, found only as far as the caller reads."""
        found = {needle: self.data.find(needle, start) for needle in needles}
        while True:
            live = [pos for pos in found.values() if pos >= 0]
            if not live:
                return
            begin, end = self._bounds(min(live))
            if not (unless and self.data.find(unless, begin, end) >= 0):
                number = self._number(begin)
                if number > after:
                    yield number, end, self.data[begin:end]
            for needle, pos in found.items():  # past this line, once the caller reads on
                if 0 <= pos < end:
                    found[needle] = self.data.find(needle, end)


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


class Span:
    """The command that opened the span, its arguments and its opener's line.
    It keeps the bytes active_span read, so its calls come from that one read
    of a transcript the CLI keeps appending to. Compared and shown by command,
    args and start_line only; a plain class for the reason Call is not a
    dataclass."""
    __slots__ = ("command", "args", "start_line", "transcript_path", "_data")

    def __init__(self, command: str, args: str, start_line: int, transcript_path: str = "",
                 data: bytes | None = None):
        self.command, self.args, self.start_line = command, args, start_line
        self.transcript_path = transcript_path
        self._data = data  # None: read transcript_path when asked

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

    def iter_calls(self, *names: str, newest_first: bool = False):
        """calls() one at a time, newest first on request. A record is
        decoded when the reader reaches it, so a reader that stops at the
        first call it wants leaves the rest of a long span undecoded."""
        try:
            lines = _Lines(self._data if self._data is not None else _read(self.transcript_path))
        except (OSError, TypeError, ValueError):
            return
        needles = [f'"{n}"'.encode() for n in names] if names else [b'"tool_use"']
        found = lines.having(needles, self.start_line)
        for number, end, raw in (reversed(list(found)) if newest_first else found):
            uses = [block for block in _blocks(_decode(raw))
                    if block.get("type") == "tool_use" and isinstance(block.get("input"), dict)
                    and (not names or block.get("name") in names)]
            for block in (reversed(uses) if newest_first else uses):
                ident, result_line, ok = block.get("id") or "", 0, False
                # Its result comes later: a reader from the end of the use's line.
                after = _Lines(lines.data, end, number)
                for later, _end, line in (after.having((json.dumps(ident).encode(),), start=end) if ident else ()):
                    for result in _blocks(_decode(line)):
                        if result.get("type") == "tool_result" and result.get("tool_use_id") == ident:
                            result_line, ok = later, not result.get("is_error")
                    if result_line:
                        break
                yield Call(id=ident, name=block.get("name") or "", input=block["input"],
                           line=number, result_line=result_line, ok=ok)

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


def active_span(transcript_path: str | Path, commands: frozenset | None = None) -> Span | None:
    """The active span, or None when no human-typed harness command opened one
    or the transcript cannot be read. ``commands`` defaults to this harness's
    commands/*.md stems."""
    commands = stop_contract.harness_commands() if commands is None else commands
    try:
        lines = _Lines(_read(transcript_path))
    except (OSError, TypeError, ValueError):
        return None
    span = None
    # A tool result is never typed.
    for number, _end, raw in lines.having(_USER_RECORD, unless=_RESULT_BLOCK):
        record = _decode(raw)
        opener = stop_contract.span_opener(record, commands) if record else None
        if opener:
            span = Span(command=opener[0], args=opener[1], start_line=number,
                        transcript_path=str(transcript_path), data=lines.data)
    return span


EDIT_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path",
              "NotebookEdit": "notebook_path"}
# Trees an agent writes as the pipeline's own bookkeeping, not as product files.
EXCLUDED_TREES = ("docs/dev/", ".claude/dev-registry/", ".claude/scratch/")
_PATH_RUN = re.compile(r"[A-Za-z0-9_.@%+~/-]+")


class WriteSet(namedtuple("WriteSet", "written named")):
    """written: the Write/Edit/MultiEdit/NotebookEdit targets with an ok
    tool_result; named: the paths the transcript's own Bash commands name."""
    __slots__ = ()


def _project_relative(raw: str, cwd: str, root: str) -> str | None:
    path = os.path.expanduser(raw)
    if not os.path.isabs(path):
        path = os.path.join(cwd or root, path)
    rel = os.path.relpath(os.path.normpath(path), root)
    if rel in (".", "..", ".git") or rel.startswith(("../", ".git/")):
        return None
    return None if rel.startswith(EXCLUDED_TREES) else rel


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


def write_set(transcript_path: str | Path, project_dir: str | Path, start_line: int = 0) -> WriteSet | None:
    """The project-relative files the transcript's own tool calls after
    ``start_line`` wrote or named (TC-46), outside EXCLUDED_TREES; None when
    the transcript cannot be read."""
    root = os.path.normpath(str(project_dir))
    try:
        records = _records(transcript_path)
    except (OSError, TypeError, ValueError):
        return None
    uses, ok = [], set()
    for number, record in records:
        if number <= start_line:
            continue
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
            rel = _project_relative(target, cwd, root) if use_id in ok and isinstance(target, str) and target else None
            if rel:
                written.add(rel)
        elif name == "Bash" and isinstance(tool_input.get("command"), str):
            named |= _bash_named(tool_input["command"], cwd, root)
    return WriteSet(written=frozenset(written), named=frozenset(named))
