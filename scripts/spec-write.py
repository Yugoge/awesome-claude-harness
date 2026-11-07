#!/usr/bin/env python3
"""spec-write.py -- the one writer of a spec monolith (docs/dev/specs/<name>.md).

Every write of a spec file runs through this script: /spec's own writes (the
first write, the `### 5.N` appends, the Section 9 reference lines, Section 1
findings), /spec-update's continuation and --update modes, and /commit Step 8's
continuation agent. A dispatch's section text (dev's report, QA's
`qa.spec_section_updates`, BA's context, the PM retro's report) stays in that
dispatch's own report; the continuation reads it and writes here.

Usage:
  spec-write.py create --spec PATH                  < text   (the whole new file; refuses an existing one)
  spec-write.py append --spec PATH --section N[.M]  < text

append adds the text at the end of `## Section N` (or of its `### N.M`
subsection), above the section's closing `---`. A section whose only content
is the template's `_Not yet populated._` line gets the text in place of that
line. Every successful write prints `spec-write: <create|append> <absolute
path>`; prompt-workflow.py reads that line from the session transcript as a
write of the spec (the spec path it decides at UserPromptSubmit).

Exit codes: 0 written, 1 refused (nothing written), 2 usage.
"""

import argparse
import contextlib
import fcntl
import os
import re
import sys
import tempfile
from pathlib import Path

PLACEHOLDER = "_Not yet populated._"
_NOT_SPECS = ("INDEX.md", "README.md")


def _spec_file(raw):
    """The absolute path of a spec monolith, or None when PATH is not one:
    a direct .md child of a docs/dev/specs directory, INDEX.md and README.md
    excluded (the doc-sync indexes, not specs)."""
    path = Path(os.path.abspath(os.path.expanduser(raw)))
    parent = path.parent
    if path.suffix != ".md" or path.name in _NOT_SPECS:
        return None
    if parent.name != "specs" or parent.parent.name != "dev" or parent.parent.parent.name != "docs":
        return None
    return path


@contextlib.contextmanager
def _locked(directory):
    """Serialize writers of one specs directory (two continuations on one spec
    must not read the same old text). The directory itself is the lock: no
    lock file is created."""
    fd = os.open(directory, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _replace(path, text):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o7777)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _heading_re(section):
    if "." in section:
        return re.compile(rf"^###\s+{re.escape(section)}\b")
    return re.compile(rf"^##\s+Section\s+{re.escape(section)}\b")


def _section_range(lines, section):
    """(heading index, end index) of the section, end exclusive: the next
    heading of the same or a higher level, or the end of the file."""
    level = 3 if "." in section else 2
    pattern = _heading_re(section)
    start = next((i for i, line in enumerate(lines) if pattern.match(line)), None)
    if start is None:
        return None
    for i in range(start + 1, len(lines)):
        hashes = len(lines[i]) - len(lines[i].lstrip("#"))
        if 2 <= hashes <= level and lines[i][hashes:hashes + 1] == " ":
            return start, i
    return start, len(lines)


def _append(text, section, block):
    lines = text.split("\n")
    found = _section_range(lines, section)
    if found is None:
        return None
    start, end = found
    body = [i for i in range(start + 1, end)
            if lines[i].strip() and not lines[i].strip().startswith("<!--") and lines[i].strip() != "---"]
    block_lines = block.rstrip("\n").split("\n")
    if len(body) == 1 and lines[body[0]].strip() == PLACEHOLDER:
        return "\n".join(lines[:body[0]] + block_lines + lines[body[0] + 1:])
    insert = end
    while insert > start + 1 and (not lines[insert - 1].strip() or lines[insert - 1].strip() == "---"):
        insert -= 1
    tail = lines[insert:end]
    if not tail or tail[0].strip():
        tail = [""] + tail
    return "\n".join(lines[:insert] + [""] + block_lines + tail + lines[end:])


def main(argv=None):
    ap = argparse.ArgumentParser(description="The one writer of a spec monolith.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    create = sub.add_parser("create", help="write a new spec from stdin")
    create.add_argument("--spec", required=True)
    append = sub.add_parser("append", help="append stdin to a section of an existing spec")
    append.add_argument("--spec", required=True)
    append.add_argument("--section", required=True, help="N for '## Section N', N.M for '### N.M'")
    args = ap.parse_args(argv)

    path = _spec_file(args.spec)
    if path is None:
        sys.stderr.write(f"spec-write: refused: {args.spec} is not a spec monolith "
                         "(a .md file directly under docs/dev/specs/, INDEX.md and README.md excluded)\n")
        return 2
    if args.cmd == "append" and not re.fullmatch(r"\d+(?:\.\d+)?", args.section):
        sys.stderr.write(f"spec-write: refused: --section {args.section!r} is not N or N.M\n")
        return 2
    block = sys.stdin.read()
    if not block.strip():
        sys.stderr.write("spec-write: refused: nothing on stdin; nothing was written\n")
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locked(path.parent):
        if args.cmd == "create":
            if path.exists():
                sys.stderr.write(f"spec-write: refused: {path} exists; append to it instead\n")
                return 1
            _replace(path, block if block.endswith("\n") else block + "\n")
        else:
            try:
                old = path.read_text(encoding="utf-8")
            except OSError as exc:
                sys.stderr.write(f"spec-write: refused: cannot read {path}: {exc}\n")
                return 1
            new = _append(old, args.section, block)
            if new is None:
                sys.stderr.write(f"spec-write: refused: {path} has no section {args.section}; nothing was written\n")
                return 1
            _replace(path, new)
    print(f"spec-write: {args.cmd} {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
