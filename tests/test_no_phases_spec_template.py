"""templates/spec-template.md keeps the structure its consumers parse.

The nine section headings, each section's `### Cycle 1` (or `### 9.N`) subsections and placeholders, and the one-line
comments are what scripts/spec-write.py, the spec resolver, the split/verify tooling and the replay drivers read. The
writer is run here: a spec created from the template takes an append to each placeholder-only section in place of
its `_Not yet populated._` line, which holds only while every comment of that section is a single `<!-- ... -->` line.

This file used to also grep Section 7's comment for the owner's no-phases ruling (D33). No hook, script or replay
reads that comment, so those greps were deleted (P15-L8); the ruling lives in prompt text only (agents/shared/
no-phases.md and the lines that point at it). Its one code consumer, the replay /spec driver's split-QA check, is run
by tests/test_no_phases_spec_command.py.

SPEC_TEMPLATE_UNDER_TEST=<path> points the file at another copy of the template; the default is
templates/spec-template.md.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = Path(os.environ.get("SPEC_TEMPLATE_UNDER_TEST") or REPO / "templates" / "spec-template.md")
TEXT = TEMPLATE_PATH.read_text(encoding="utf-8")
SPEC_WRITE = REPO / "scripts" / "spec-write.py"

HEADINGS = [
    "## Section 1: Before",
    "## Section 2: What Was Attempted",
    "## Section 3: What Was Changed",
    "## Section 4: Current State",
    "## Section 5: User's Acceptance Criterion",
    "## Section 6: Why Not Met",
    "## Section 7: What Must Be Done",
    "## Section 8: Attention Notes",
    "## Section 9: Design & Evidence References",
]
CYCLE_SECTIONS = {1, 2, 3, 4, 6, 7}  # each holds "### Cycle 1" + the placeholder
PLACEHOLDER = "_Not yet populated._"
# The sections whose only body is the placeholder: spec-write.py's append replaces it there.
PLACEHOLDER_ONLY = {"5": "## Section 5:", "8": "## Section 8:", "9.1": "### 9.1:", "9.2": "### 9.2:"}


def _section(n: int) -> str:
    start = TEXT.index(HEADINGS[n - 1])
    end = TEXT.find("\n## Section ", start + 1)
    return TEXT[start:end if end != -1 else len(TEXT)]


def _spec_write(*args: str, stdin: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SPEC_WRITE), *args], input=stdin, capture_output=True, text=True,
                          check=False)


# ------------------------------------------- the structure the consumers parse

def test_the_nine_section_headings_are_unchanged_and_in_order():
    found = re.findall(r"^## Section .*$", TEXT, re.M)
    assert found == HEADINGS


@pytest.mark.parametrize("n", range(1, 10))
def test_section_cycle_subsections_and_placeholders(n):
    block = _section(n)
    if n in CYCLE_SECTIONS:
        assert re.search(rf"^### Cycle 1\n\n{re.escape(PLACEHOLDER)}\n", block, re.M)
        assert re.findall(r"^### .*$", block, re.M) == ["### Cycle 1"]
    elif n == 9:
        assert re.findall(r"^### .*$", block, re.M) == ["### 9.1: Design References", "### 9.2: Evidence References"]
        assert block.count("<!-- consumers: [all] -->\n" + PLACEHOLDER) == 2
    else:
        assert not re.findall(r"^### .*$", block, re.M)
        assert PLACEHOLDER in block


@pytest.mark.parametrize("section", sorted(PLACEHOLDER_ONLY))
def test_spec_write_appends_in_place_of_the_placeholder(tmp_path, section):
    """scripts/spec-write.py treats a line that does not start with '<!--' as section body when it decides whether
    the placeholder is the section's only content: a comment spread over two lines makes the append land below the
    placeholder instead of replacing it."""
    spec = tmp_path / "docs" / "dev" / "specs" / "toy.md"
    spec.parent.mkdir(parents=True)
    created = _spec_write("create", "--spec", str(spec), stdin=TEXT)
    assert created.returncode == 0, created.stderr
    line = f"Appended to {section} by the test."
    appended = _spec_write("append", "--spec", str(spec), "--section", section, stdin=line + "\n")
    assert appended.returncode == 0, appended.stderr
    at = TEXT.index(PLACEHOLDER, TEXT.index(PLACEHOLDER_ONLY[section]))
    assert spec.read_text(encoding="utf-8") == TEXT[:at] + line + TEXT[at + len(PLACEHOLDER):]


def test_the_overnight_spec_path_consumers_copy_reaches_the_same_text():
    """/spec, /spec-update and /dev-overnight copy templates/overnight-spec.md (a link to this file)."""
    copied = (REPO / "templates" / "overnight-spec.md").read_text(encoding="utf-8")
    assert copied == (REPO / "templates" / "spec-template.md").read_text(encoding="utf-8")
