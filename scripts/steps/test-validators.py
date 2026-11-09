#!/usr/bin/env python3
"""Steps 5-6 of /test: check the tests/ structure, then discover the validators.

    test-validators.py check    [--project-root DIR]
    test-validators.py discover --request-id ID [--project-root DIR]

The project root defaults to the current directory. Facts go to stdout as key=value lines; the exit
status is 0 for every state below (2 for wrong arguments).

check     status=ok|structure_incomplete|no_validators, missing=<comma list of tests/scripts,
          tests/reports that are absent|none>, script_validators, instruction_validators,
          total_validators. A missing prerequisite is a fact for the command to repair, not an exit.
discover  Writes tests/reports/validator-registry-<ID>.json and prints registry=<that path>,
          validators, script_validators, instruction_validators.

Validators: script validators are tests/scripts/**/validate-*.py; instruction validators are
tests/instructions/**/*.md without the files named *guide.md. Metadata comes from the first 20 lines
of each file: edge_case is the first EC<3 digits> ("" when none), priority a `Priority:` header
(critical, high, medium or low; medium when absent), description the `Purpose:` header ("" when none).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED = ("tests/scripts", "tests/reports")
PRIORITIES = ("critical", "high", "medium", "low")
HEADER_LINES = 20


def emit(**facts: object) -> None:
    for key, value in facts.items():
        print(f"{key}={str(value).replace(chr(10), ' ')}")


def find_validators(root: Path) -> tuple[list[Path], list[Path]]:
    scripts_dir, instructions_dir = root / "tests" / "scripts", root / "tests" / "instructions"
    scripts = sorted(p for p in scripts_dir.rglob("validate-*.py") if p.is_file()) if scripts_dir.is_dir() else []
    instructions = sorted(p for p in instructions_dir.rglob("*.md")
                          if p.is_file() and not p.name.endswith("guide.md")) if instructions_dir.is_dir() else []
    return scripts, instructions


def header_of(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            return "".join(line for _, line in zip(range(HEADER_LINES), handle))
    except OSError:
        return ""


def entry(root: Path, path: Path, kind: str) -> dict:
    head = header_of(path)
    edge = re.search(r"EC[0-9]{3}", head)
    priority = re.search(r"^\W*priority\W*:\s*(\w+)", head, re.I | re.M)
    purpose = re.search(r"^\W*purpose\W*:\s*(.+)$", head, re.I | re.M)
    level = priority.group(1).lower() if priority else ""
    return {
        "type": kind,
        "path": path.relative_to(root).as_posix(),
        "name": path.stem,
        "edge_case": edge.group(0) if edge else "",
        "priority": level if level in PRIORITIES else "medium",
        "description": purpose.group(1).strip().strip("*").strip() if purpose else "",
    }


def cmd_check(root: Path) -> None:
    missing = [rel for rel in REQUIRED if not (root / rel).is_dir()]
    scripts, instructions = find_validators(root)
    total = len(scripts) + len(instructions)
    status = "structure_incomplete" if missing else "no_validators" if total == 0 else "ok"
    emit(status=status, missing=",".join(missing) or "none", script_validators=len(scripts),
         instruction_validators=len(instructions), total_validators=total)


def cmd_discover(root: Path, request_id: str) -> None:
    scripts, instructions = find_validators(root)
    validators = [entry(root, p, "script") for p in scripts] + [entry(root, p, "instruction") for p in instructions]
    registry = root / "tests" / "reports" / f"validator-registry-{request_id}.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps({"validators": validators}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    emit(registry=registry.relative_to(root).as_posix(), validators=len(validators),
         script_validators=len(scripts), instruction_validators=len(instructions))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("step", choices=("check", "discover"))
    parser.add_argument("--request-id")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.project_root).resolve()
    if args.step == "check":
        cmd_check(root)
    elif not args.request_id:
        parser.error("discover needs --request-id")
    else:
        cmd_discover(root, args.request_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
