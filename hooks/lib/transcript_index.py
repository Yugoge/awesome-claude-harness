"""What a saved conversation said, kept so that a later read takes only what was added.

A conversation only grows. extend() keeps, per (conversation, kind of reading), the state a reading had at the end
of the last complete line it consumed, with the offset, the line count and a check of the bytes before the offset
(a digest of the first and of the last WINDOW bytes: the file is a continuation only while both are as they were,
and not shorter). A later call reads from the offset: the new complete lines advance the kept state, and an
unfinished last line is folded into a copy and kept nowhere. A file that is no continuation is read whole again.
A reading that finds a carriage return in the bytes it reads is left to the caller's whole read (a text reader
splits lines there, a byte split does not). The record is replaced at once after each conversation, so a run that is
cut off keeps what it finished. A record lives in `transcript-index/<digest>.json` under the folder the caller names
(the state root's); one older than KEEP goes at the next write. This module is the one writer and reader.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

DIR = "transcript-index"
KEEP = 7 * 86400
VERSION = 1
WINDOW = 65536
_SWEPT: set[str] = set()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record(folder: Path, transcript: Path, kind: str) -> Path:
    return folder / (hashlib.sha256(f"{kind}\0{transcript}".encode()).hexdigest()[:32] + ".json")


def _kept(record: Path, salt: str, handle, size: int) -> dict | None:
    """The kept entry at ``record`` while the file is its continuation; the bytes read to tell are counted
    in ``entry["checked"]``."""
    try:
        entry = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(entry, dict) or entry.get("version") != VERSION or entry.get("salt") != salt \
            or entry.get("cr") or not isinstance(entry.get("offset"), int) or entry["offset"] > size:
        return None
    head, tail = _windows(handle, entry["offset"])
    if _digest(head) != entry.get("head") or _digest(tail) != entry.get("tail"):
        return None
    entry["checked"] = len(head) + len(tail)
    return entry


def _windows(handle, offset: int) -> tuple[bytes, bytes]:
    """The first and the last WINDOW bytes before ``offset``."""
    handle.seek(0)
    head = handle.read(min(WINDOW, offset))
    handle.seek(max(0, offset - WINDOW))
    return head, handle.read(min(WINDOW, offset))


def _write(folder: Path, record: Path, entry: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    if str(folder) not in _SWEPT:
        _SWEPT.add(str(folder))
        now = time.time()
        for old in folder.glob("*.json"):
            try:
                if old.stat().st_mtime < now - KEEP:
                    old.unlink()
            except OSError:
                pass
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(entry, handle)
    os.replace(tmp, record)


def extend(folder, transcript, kind: str, salt: str, empty, step):
    """(state, read): the state of reading ``transcript`` as ``kind`` over its whole text, and the number of
    bytes read to get it; None when the bytes hold a carriage return (read it whole). ``empty()`` is the state of
    no lines; ``step(state, data, first)`` is the state after ``data`` (bytes of whole lines, the first of them
    line ``first``, or an unfinished last line) and must not change ``state``. ``salt`` names what the state
    depends on besides the file: another salt discards the kept entry. OSError when the file cannot be read."""
    folder = Path(folder) / DIR
    transcript = Path(transcript)
    record = _record(folder, transcript, kind)
    with open(transcript, "rb") as handle:
        size = os.fstat(handle.fileno()).st_size
        entry = _kept(record, salt, handle, size)
        spent = entry.pop("checked") if entry else 0
        offset, lines, state = (entry["offset"], entry["lines"], entry["state"]) if entry else (0, 0, empty())
        handle.seek(offset)
        data = handle.read()
    spent += len(data)
    if b"\r" in data:
        return None
    cut = data.rfind(b"\n") + 1
    whole, rest = data[:cut], data[cut:]
    if whole:
        state = step(state, whole, lines + 1)
        lines += whole.count(b"\n")
        offset += cut
        with open(transcript, "rb") as handle:  # the digests of what is now consumed
            head, tail = _windows(handle, offset)
        spent += len(head) + len(tail)
        try:
            _write(folder, record, {"version": VERSION, "salt": salt, "offset": offset, "lines": lines,
                                    "head": _digest(head), "tail": _digest(tail), "state": state})
        except OSError:  # an unwritable folder keeps nothing; the reading stands
            pass
    return (step(copy.copy(state), rest, lines + 1) if rest else state), spent
