#!/usr/bin/env python3
"""
Validator: validate-step-numbering
Edge Case: EC004
Purpose: Detect decimal and lettered step numbering - ensures workflow steps use integer numbering only

Root Cause: User explicitly prohibited decimal steps (1.1, 1.2) but /clean used Step 3.5.
This validator prevents EC004 by scanning command .md files for decimal and lettered (Step 4a)
step patterns; tests/test_step_numbering.py runs it over the harness's own commands/ folder.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Dict


def validate(project_root: Path) -> Dict:
    """
    Validate step numbering across command files.

    Scans commands/*.md for step numbering patterns and detects decimal numbering.

    Args:
        project_root: Root directory of project to validate

    Returns:
        dict: Validation result with status and violations
    """
    violations = []

    # Pattern: Step followed by a decimal (Step 1.1, Step 2.5) or a lettered number (Step 4a, Step 10A)
    decimal_step_pattern = re.compile(r'(Steps?\s+\d+(?:\.\d+|[A-Za-z])\b)', re.IGNORECASE)

    commands_dir = project_root / "commands"
    if not commands_dir.exists():
        return {
            "validator": "validate-step-numbering",
            "edge_case": "EC004",
            "status": "pass",
            "violations": [],
            "summary": {
                "total_files_checked": 0,
                "violations_found": 0
            },
            "recommendations": []
        }

    files_checked = 0

    for md_file in commands_dir.glob("*.md"):
        files_checked += 1

        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    match = decimal_step_pattern.search(line)
                    if match:
                        violations.append({
                            "file": str(md_file.relative_to(project_root)),
                            "line": line_num,
                            "pattern": match.group(1),
                            "expected": "Use integer step numbering: Step 1, Step 2, Step 3",
                            "severity": "critical",
                            "context": line.strip()
                        })
        except Exception:
            continue

    return {
        "validator": "validate-step-numbering",
        "edge_case": "EC004",
        "status": "pass" if not violations else "fail",
        "violations": violations,
        "summary": {
            "total_files_checked": files_checked,
            "violations_found": len(violations)
        },
        "recommendations": [
            "Renumber steps to use sequential integers only",
            "Update todo scripts (scripts/todo/*.py) to match step count",
            "See agents/dev.md Quality Checklist for enforcement"
        ] if violations else []
    }


def main():
    parser = argparse.ArgumentParser(
        description="Validate step numbering (EC004 prevention)"
    )
    parser.add_argument(
        "--project-root",
        required=True,
        help="Project root directory"
    )
    args = parser.parse_args()

    project_root = Path(args.project_root)
    if not project_root.exists():
        print(json.dumps({"error": "Project root does not exist"}), file=sys.stderr)
        sys.exit(1)

    result = validate(project_root)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    sys.exit(0 if result["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
