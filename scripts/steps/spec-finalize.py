#!/usr/bin/env python3
"""/spec Step 6's two mechanical calls: the checks before the split, and the marker after its last QA verdict.

    spec-finalize.py prepare  --spec PATH [--project-dir DIR]
    spec-finalize.py complete --spec PATH [--project-dir DIR]

The project is --project-dir, else $CLAUDE_PROJECT_DIR, else the git top level of the current directory. The spec's
de-prefixed id is `candidates[0]` of scripts/resolve-spec-artifacts.py, the one place that derives it. Facts go to
stdout as key=value lines; the exit status is 0 for every state below, 1 when the id cannot be resolved (or, for
`complete`, the split folder is missing), 2 for wrong arguments.

prepare   spec_id=<id>  monolith_lines=<newline count of the spec, what `wc -l` prints>
          references=<distinct design/evidence paths Section 9 lists>
          dangling=<path>   one line per listed path with no file under docs/dev/specs/<id>/ and no limitation line
                            in Section 9 that carries it
          status=ok|dangling
          Section 9 runs from `## Section 9` to the next `## ` heading. A line that opens with `- (inline)`,
          `- (unpersisted)` or `- (unpersisted design)` is a limitation record, not a path to check; a listed path
          that such a line carries counts as converted.
complete  Writes `docs/dev/specs/<id>/.split-complete` ("split-complete: <local ISO time>"), then runs
          scripts/lint-spec-id-centralization.py over this harness's commands/dev*.md, close.md and spec.md.
          The lint is advisory: spec_id=<id> marker=<path> lint=ok|flagged|skipped, and a WARNING on stderr
          when it flags.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[2]
RESOLVER = HARNESS / "scripts" / "resolve-spec-artifacts.py"
LINT = HARNESS / "scripts" / "lint-spec-id-centralization.py"
SENTINEL = re.compile(r"^\s*-\s*\((?:inline|unpersisted design|unpersisted)\)\s")
REFERENCE = re.compile(r"`(docs/dev/specs/[^`]+/(?:design|evidence)/[^`]+)`")
WARNING = ("WARNING: centralization lint flagged inline spec-id derivation in a consumer command file: a /dev*/spec "
           "command re-derives the spec-id in prose instead of calling resolve-spec-artifacts.py. Fix before the "
           "next commit that touches those files.")


def emit(**facts: object) -> None:
    for key, value in facts.items():
        print(f"{key}={str(value).replace(chr(10), ' ')}")


def project_dir(given: str | None) -> Path:
    if given:
        return Path(given).resolve()
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(top.stdout.strip() if top.returncode == 0 and top.stdout.strip() else os.getcwd()).resolve()


def spec_dir_id(spec: str, project: Path) -> str:
    """candidates[0] of the resolver's JSON. Its exit status is not read: the id is in the JSON whenever the spec
    file is readable, and a split that is not valid yet (no marker) does not change it."""
    proc = subprocess.run([sys.executable, str(RESOLVER), "--spec-path", spec, "--project-dir", str(project)],
                          capture_output=True, text=True)
    try:
        return str(json.loads(proc.stdout)["candidates"][0])
    except (ValueError, KeyError, IndexError, TypeError):
        sys.stderr.write(proc.stderr or "spec-finalize: the resolver gave no candidates\n")
        raise SystemExit(1)


def section9(text: str) -> list[str]:
    lines = text.split("\n")
    start = next((i for i, line in enumerate(lines) if re.match(r"^## Section 9\b", line)), None)
    if start is None:
        return []
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start:end]


def prepare(spec: str, project: Path) -> int:
    spec_id = spec_dir_id(spec, project)
    path = Path(spec) if os.path.isabs(spec) else project / spec
    try:
        data = path.read_bytes()
    except OSError as exc:
        sys.stderr.write(f"spec-finalize: cannot read {path}: {exc.strerror or exc}\n")
        return 1
    lines = section9(data.decode("utf-8", errors="replace"))
    records = [line for line in lines if SENTINEL.search(line)]
    refs = list(dict.fromkeys(ref for line in lines if not SENTINEL.search(line) for ref in REFERENCE.findall(line)))
    bound = (project / "docs" / "dev" / "specs" / spec_id).resolve()
    dangling = []
    for ref in refs:
        target = (project / ref).resolve()
        inside = target == bound or bound in target.parents
        if not (inside and target.exists()) and not any(ref in record for record in records):
            dangling.append(ref)
    emit(spec_id=spec_id, monolith_lines=data.count(b"\n"), references=len(refs))
    for ref in dangling:
        emit(dangling=ref)
    emit(status="dangling" if dangling else "ok")
    return 0


def complete(spec: str, project: Path) -> int:
    spec_id = spec_dir_id(spec, project)
    folder = project / "docs" / "dev" / "specs" / spec_id
    if not folder.is_dir():
        sys.stderr.write(f"spec-finalize: {folder} does not exist: the spec subagent has not written the split\n")
        return 1
    marker = folder / ".split-complete"
    marker.write_text(f"split-complete: {datetime.now().astimezone().isoformat(timespec='seconds')}\n",
                      encoding="utf-8")
    commands = HARNESS / "commands"
    files = [str(path) for path in [*sorted(commands.glob("dev*.md")), commands / "close.md", commands / "spec.md"]
             if path.is_file()]
    if not LINT.is_file() or not files:
        verdict = "skipped"
    else:
        proc = subprocess.run([sys.executable, str(LINT), "--paths", *files], capture_output=True, text=True)
        verdict = "ok" if proc.returncode == 0 else "flagged"
        if verdict == "flagged":
            sys.stderr.write(proc.stderr + proc.stdout + WARNING + "\n")
    emit(spec_id=spec_id, marker=marker.relative_to(project).as_posix(), lint=verdict)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="spec-finalize.py")
    parser.add_argument("action", choices=("prepare", "complete"))
    parser.add_argument("--spec", required=True)
    parser.add_argument("--project-dir")
    args = parser.parse_args(argv)
    project = project_dir(args.project_dir)
    return (prepare if args.action == "prepare" else complete)(args.spec, project)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
