"""Shapes of recorded Claude Code CLI records, and the diff between two shapes.

The rule (P15 section 2(d)):
- a record's kind is its source plus `type`, plus `attachment.type` or `subtype`
  (``transcript:attachment/hook_success``, ``subagent:system/stop_hook_summary``, ``stdin:Stop``);
- its shape is every dotted key path, 3 levels deep, with ``[]`` marking list items, mapped to the
  set of JSON types seen there (records of one kind are merged);
- values are never compared;
- an added or removed kind, an added or removed key path, and a changed type set are diffs.

Usage:
    python3 tests/cli_shapes.py shape <fixture-dir>          # prints the shapes JSON
    python3 tests/cli_shapes.py diff <old> <new>             # each a fixture dir or a shapes.json
Exit codes: 0 = same shape; 1 = a diff (each change printed on its own line); 2 = bad usage.
"""
from __future__ import annotations

import functools
import json
import pathlib
import re
import sys

DEPTH = 3
SOURCES = (("transcript", "transcript.jsonl"), ("subagent", "subagent.jsonl"))
# The file the CLI writes beside a subagent's transcript (agent-<id>.meta.json): kind meta:subagent.
META = "subagent.meta.json"


def json_type(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def record_kind(rec: dict) -> str:
    kind = str(rec.get("type"))
    attachment = rec.get("attachment")
    if isinstance(attachment, dict) and "type" in attachment:
        return f"{kind}/{attachment['type']}"
    if "subtype" in rec:
        return f"{kind}/{rec['subtype']}"
    return kind


def _walk(value, path: str, level: int, out: dict) -> None:
    if path:
        out.setdefault(path, set()).add(json_type(value))
    if level >= DEPTH:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            _walk(child, f"{path}.{key}" if path else key, level + 1, out)
    elif isinstance(value, list) and path:
        for child in value:
            _walk(child, path + "[]", level, out)


def record_shape(rec) -> dict:
    """Dotted key path -> set of JSON types, 3 key levels deep."""
    out: dict = {}
    _walk(rec, "", 0, out)
    return out


def _merge(shapes: dict, kind: str, rec) -> None:
    into = shapes.setdefault(kind, {})
    for path, types in record_shape(rec).items():
        into.setdefault(path, set()).update(types)


def fixture_shapes(fixture_dir) -> dict:
    """The shape of a fixture dir: {kind: {path: sorted [types]}}."""
    root = pathlib.Path(fixture_dir)
    shapes: dict = {}
    for source, name in SOURCES:
        f = root / name
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                _merge(shapes, f"{source}:{record_kind(rec)}", rec)
    for f in sorted((root / "stdin").glob("*.json")):
        _merge(shapes, f"stdin:{f.stem}", json.loads(f.read_text()))
    if (root / META).exists():
        _merge(shapes, "meta:subagent", json.loads((root / META).read_text()))
    return {k: {p: sorted(t) for p, t in sorted(v.items())} for k, v in sorted(shapes.items())}


FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "cli"


def current_version(root=FIXTURES) -> str:
    """The CLI version whose recording the tests read (tests/fixtures/cli/CURRENT)."""
    return (pathlib.Path(root) / "CURRENT").read_text().strip()


def load_records(kind: str, version: str | None = None, root=FIXTURES):
    """Recorded CLI records of one kind, as fresh copies.

    `kind` is a kind of `fixture_shapes`: ``transcript:attachment/hook_success``,
    ``subagent:attachment/hook_success``, ``transcript:system/stop_hook_summary``, ... (a list of
    records, in recording order), ``stdin:<Event>`` (the one hook stdin dict) or ``meta:subagent`` (the
    meta file the CLI writes beside the first subagent's transcript). A kind without a
    source prefix reads the parent transcript. An unknown kind raises KeyError, never returns [].
    """
    fixture = pathlib.Path(root) / (version or current_version(root))
    source, _, record = kind.rpartition(":")
    source = source or "transcript"
    if source == "meta" and record == "subagent":
        if not (fixture / META).exists():
            raise KeyError(kind)
        return json.loads((fixture / META).read_text())
    if source == "stdin":
        f = fixture / "stdin" / f"{record}.json"
        if not f.exists():
            raise KeyError(kind)
        return json.loads(f.read_text())
    files = dict(SOURCES)
    if source not in files:
        raise KeyError(kind)
    out = [json.loads(line) for line in (fixture / files[source]).read_text().splitlines()
           if line.strip()]
    out = [rec for rec in out if record_kind(rec) == record]
    if not out:
        raise KeyError(kind)
    return out


def load_shapes(path) -> dict:
    """A fixture dir's computed shape, or a shapes.json as written."""
    p = pathlib.Path(path)
    if p.is_dir():
        return fixture_shapes(p)
    return json.loads(p.read_text())


def diff_shapes(old: dict, new: dict) -> list[str]:
    """One line per change from old to new; empty when the shapes are equal."""
    lines = []
    for kind in sorted(set(old) - set(new)):
        lines.append(f"removed kind {kind}")
    for kind in sorted(set(new) - set(old)):
        lines.append(f"added kind {kind}")
    for kind in sorted(set(old) & set(new)):
        a, b = old[kind], new[kind]
        for path in sorted(set(a) - set(b)):
            lines.append(f"{kind}: removed key {path}")
        for path in sorted(set(b) - set(a)):
            lines.append(f"{kind}: added key {path}")
        for path in sorted(set(a) & set(b)):
            if sorted(a[path]) != sorted(b[path]):
                lines.append(f"{kind}: type of {path} changed {sorted(a[path])} -> {sorted(b[path])}")
    return lines


# -- synthesizing a record from the recording (P15 L3) ------------------------------------------------
# Every test and the replay build a CLI record with `synthesize`, never by hand: a fresh copy of a
# recorded record, values filled in at key paths the CLI recorded. A path it did not record raises.

def _content(rec):
    message = rec.get("message")
    return message.get("content") if isinstance(message, dict) else None


def _blocks(rec) -> set:
    content = _content(rec)
    return {b.get("type") for b in content if isinstance(b, dict)} if isinstance(content, list) else set()


def _use(rec) -> dict:
    """A tool_result record's toolUseResult object ({} for any other record)."""
    value = rec.get("toolUseResult") if "tool_result" in _blocks(rec) else None
    return value if isinstance(value, dict) else {}


def _errored(rec) -> bool:
    content = _content(rec)
    return isinstance(content, list) and any(isinstance(b, dict) and b.get("is_error") is True for b in content)


# The recorded forms of one kind, told apart by structure (never by the redacted text).
VARIANTS = {
    "user": {
        "command": lambda r: isinstance(_content(r), str) and "promptSource" not in r,  # a typed slash command
        "prompt": lambda r: isinstance(_content(r), str) and "promptSource" in r,       # a typed plain prompt
        "meta": lambda r: bool(r.get("isMeta")) and "sourceToolUseID" not in r,         # a typed command's body
        "skill": lambda r: bool(r.get("isMeta")) and "sourceToolUseID" in r,            # a Skill call's expansion
        "tool_result": lambda r: "tool_result" in _blocks(r),
        # How a dispatched agent's end comes back (P15 L3's recorder runs 4-10):
        "agent_result": lambda r: _use(r).get("status") == "completed" and "agentId" in _use(r),  # its Agent call's
        "agent_launched": lambda r: _use(r).get("isAsync") is True,          # a background launch's result
        "resumed": lambda r: "resumedAgentId" in _use(r),                     # a SendMessage's result
        "cut": lambda r: "toolDenialKind" in r and _errored(r),               # an interrupt, or the end of the session
        "task_notification": lambda r: (r.get("origin") or {}).get("kind") == "task-notification",
        "compact_summary": lambda r: bool(r.get("isCompactSummary")),
    },
    "assistant": {
        "tool_use": lambda r: "tool_use" in _blocks(r),
        "text": lambda r: _blocks(r) == {"text"},
    },
    "queue-operation": {
        "enqueue": lambda r: r.get("operation") == "enqueue",
        "dequeue": lambda r: r.get("operation") == "dequeue",
        "remove": lambda r: r.get("operation") == "remove",  # a queued notification delivered mid-turn
    },
}


def template(kind: str, variant: str | None = None, version: str | None = None, root=FIXTURES) -> dict:
    """The first recorded record of ``kind`` (``subagent:<kind>`` for the subagent's transcript) whose
    form is ``variant`` (VARIANTS), as a fresh copy."""
    test = VARIANTS.get(kind.rpartition(":")[2], {}).get(variant) if variant else None
    if variant and test is None:
        raise KeyError(f"{kind}: no recorded form {variant!r}")
    for rec in load_records(kind, version, root):
        if test is None or test(rec):
            return rec
    raise KeyError(f"{kind}: the recording has no {variant!r} form")


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def synthesize(kind: str, variant: str | None = None, **values) -> dict:
    """A record of ``kind`` as the installed CLI writes it: the recorded record with ``values`` set at
    their key paths (``attachment__content`` for ``attachment.content``). Its uuid is fresh and its
    timestamp now unless given. A key path the CLI did not record raises KeyError."""
    import uuid

    rec = template(kind, variant)
    if "uuid" in rec:
        rec["uuid"] = str(uuid.uuid4())
    if "timestamp" in rec:
        rec["timestamp"] = _now()
    for dotted, value in values.items():
        node, keys = rec, dotted.split("__")
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                raise KeyError(f"{kind}: the CLI records no {'.'.join(keys)}")
            parent, node = node, node[key]
        parent[keys[-1]] = value
    return rec


def recording(source: str = "transcript", version: str | None = None, root=FIXTURES) -> list:
    """Every recorded record of one source (``transcript`` or ``subagent``), in recording order, as
    fresh copies: a real sequence, for a reader of a transcript's order (an agent's tail)."""
    path = pathlib.Path(root) / (version or current_version(root)) / dict(SOURCES)[source]
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


_NOTIFICATION_TAG = re.compile(r"<(task-id|tool-use-id|status)>(.*?)</\1>")
_NOTIFICATION_RESULT = re.compile(r"<result>.*?</result>", re.S)


def notification(task_id: str, tool_use_id: str, status: str = "completed", result: str | None = None) -> str:
    """The text of a task-notification as the CLI writes it (the first recorded one: its tags, in
    their order, the redacted text left in place) with these values in its header tags and, when
    ``result`` is given, that text (the agent's own last reply) in its <result> tag."""
    text = template("user", "task_notification")["message"]["content"]
    values = {"task-id": task_id, "tool-use-id": tool_use_id, "status": status}
    text = _NOTIFICATION_TAG.sub(lambda m: f"<{m.group(1)}>{values[m.group(1)]}</{m.group(1)}>", text)
    if result is None:
        return text
    if len(_NOTIFICATION_RESULT.findall(text)) != 1:
        raise KeyError("user: the recorded task-notification holds no one <result>")
    return _NOTIFICATION_RESULT.sub(lambda _m: f"<result>{result}</result>", text)


# Before each model request the CLI (2.1.322, tests/fixtures/cli-request-copies) writes an api-request-blob
# record for each message of the request it has not written before: the message as sent, its tool_use and
# tool_result blocks with their ids. A call's copy follows its result; a turn's last message's, the next prompt.
REQUEST_COPIES = FIXTURES.parent / "cli-request-copies" / "transcript-2.1.322.jsonl"


def with_request_copies(records: list) -> list:
    """``records`` (one transcript's, in order) with the api-request-blob records the CLI writes among them:
    after each user record that a model request follows (the next message is the model's), a copy of
    each message before it not yet copied, the assistant records in a row as one message (the recorded
    copy, its values filled). The user record itself is copied at the next request, as the recording's
    tool result is; the messages of a turn no request followed (an agent's last), after the next prompt."""
    import hashlib

    blob = next(r for r in map(json.loads, REQUEST_COPIES.read_text().splitlines()) if r["type"] == "api-request-blob")
    said = [k for k, rec in enumerate(records) if rec.get("type") in ("user", "assistant") and _content(rec) is not None]
    out, pending = [], []
    for k, rec in enumerate(records):
        out.append(rec)
        if k not in said:
            continue
        content = _content(rec) if isinstance(_content(rec), list) else [{"type": "text", "text": _content(rec)}]
        if pending and pending[-1][0] == rec["type"] == "assistant":
            pending[-1][1].extend(content)
        else:
            pending.append((rec["type"], list(content), rec))
        after = [records[j]["type"] for j in said if j > k][:1]
        if rec["type"] != "user" or after != ["assistant"]:
            continue
        for role, blocks, first in pending[:-1]:
            message = dict(blob["message"], role=role, content=blocks)
            copy = dict(blob, sessionId=first.get("sessionId"), message=message,
                        hash=hashlib.sha256(json.dumps(message, sort_keys=True).encode()).hexdigest())
            out.append(dict(copy, agentId=first["agentId"]) if "agentId" in first else copy)
        pending = pending[-1:]
    return out


def add_request_copies(path) -> None:
    """Write the CLI's api-request-blob records into the transcript at ``path`` (with_request_copies)."""
    path = pathlib.Path(path)
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    path.write_text("".join(json.dumps(r) + "\n" for r in with_request_copies(records)))


@functools.lru_cache(maxsize=None)
def _recorded_shapes(fixture_dir: str) -> dict:
    return fixture_shapes(fixture_dir)


def check_record(rec: dict, version: str | None = None, root=FIXTURES) -> list[str]:
    """Why ``rec`` is not of a shape the CLI records for its kind (in either transcript): a kind, a
    key path or a JSON type the recording lacks. [] when it is."""
    shapes = _recorded_shapes(str(pathlib.Path(root) / (version or current_version(root))))
    kind = record_kind(rec)
    known: dict = {}
    for source, _ in SOURCES:
        for path, types in shapes.get(f"{source}:{kind}", {}).items():
            known.setdefault(path, set()).update(types)
    if not known:
        return [f"kind not recorded: {kind}"]
    return [f"{kind}: " + (f"key not recorded: {path}" if path not in known else
                           f"type {sorted(types)} of {path} not recorded ({sorted(known[path])})")
            for path, types in sorted(record_shape(rec).items())
            if path not in known or not types <= known[path]]


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "shape":
        print(json.dumps(fixture_shapes(argv[1]), indent=1, sort_keys=True))
        return 0
    if len(argv) == 3 and argv[0] == "diff":
        lines = diff_shapes(load_shapes(argv[1]), load_shapes(argv[2]))
        for line in lines:
            print(line)
        return 1 if lines else 0
    print(__doc__.split("Usage:")[1].split("Exit codes")[0].rstrip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
