"""Contracts for the live ``/spec-update`` command policy, as the harness reads the command file.

The README facts (scripts/readme_facts.py) read the command's front matter into its command row: the
command is human-only (`disable-model-invocation: true`) and its argument hint offers the three modes.
settings.json denies it to the Skill tool, the barrier the front matter alone is not (CLAUDE.md lesson
15). The rename history (`/spec-continue` became `/spec-update`) lives in CHANGELOG.md; no code reads
where that note sits, so it has no test.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_command_policy() -> None:
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "readme_facts.py"), "--fact", "command_rows"],
                         capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert run.returncode == 0, run.stderr
    [row] = [r for r in json.loads(run.stdout)["facts"]["command_rows"] if r["name"] == "spec-update"]
    assert (row["human_only"], row["group"]) == (True, "Spec")
    assert set(re.findall(r"--[a-z]+", row["argument_hint"])) == {"--update", "--continue", "--temp", "--spec"}
    deny = json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))["permissions"]["deny"]
    assert deny.count("Skill(spec-update:*)") == 1
