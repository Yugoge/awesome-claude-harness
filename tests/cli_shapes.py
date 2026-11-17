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

import json
import pathlib
import sys

DEPTH = 3
SOURCES = (("transcript", "transcript.jsonl"), ("subagent", "subagent.jsonl"))


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
    return {k: {p: sorted(t) for p, t in sorted(v.items())} for k, v in sorted(shapes.items())}


FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "cli"


def current_version(root=FIXTURES) -> str:
    """The CLI version whose recording the tests read (tests/fixtures/cli/CURRENT)."""
    return (pathlib.Path(root) / "CURRENT").read_text().strip()


def load_records(kind: str, version: str | None = None, root=FIXTURES):
    """Recorded CLI records of one kind, as fresh copies.

    `kind` is a kind of `fixture_shapes`: ``transcript:attachment/hook_success``,
    ``subagent:attachment/hook_success``, ``transcript:system/stop_hook_summary``, ... (a list of
    records, in recording order), or ``stdin:<Event>`` (the one hook stdin dict). A kind without a
    source prefix reads the parent transcript. An unknown kind raises KeyError, never returns [].
    """
    fixture = pathlib.Path(root) / (version or current_version(root))
    source, _, record = kind.rpartition(":")
    source = source or "transcript"
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
