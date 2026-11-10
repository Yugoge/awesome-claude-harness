"""templates/spec-template.md carries the owner's "no phases" ruling (D33) in Section 7.

Everything the user requested is done in the cycle; Section 7 lists the actions that
finish it and never phases, a "phase 2", an MVP first, deferred parts or work for a
later cycle. Parallel lanes inside one cycle stay. The second half of the file pins the
structure the spec consumers parse (scripts/spec-write.py, the spec resolver, the
split/verify tooling, the replay drivers), so the rule is added without moving it.

SPEC_TEMPLATE_UNDER_TEST=<path> points the file at another copy of the template; the
default is templates/spec-template.md. Pointing it at the pre-ruling text must fail the
rule tests and pass the structure tests.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = Path(os.environ.get("SPEC_TEMPLATE_UNDER_TEST") or REPO / "templates" / "spec-template.md")
TEXT = TEMPLATE_PATH.read_text(encoding="utf-8")

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

# What Section 7 must forbid, each as the pattern that names it.
FORBIDDEN = {
    "phases": r"\bphases\b",
    "phase 2": r"\bphase 2\b",
    "MVP first": r"\bMVP first\b",
    "deferred parts": r"\bdeferred parts\b",
    "a later cycle": r"\b(?:a|for a) later cycle\b",
}


def _section(n: int) -> str:
    start = TEXT.index(HEADINGS[n - 1])
    end = TEXT.find("\n## Section ", start + 1)
    return TEXT[start:end if end != -1 else len(TEXT)]


def _comments(block: str) -> list[str]:
    return [l.strip() for l in block.split("\n") if l.strip().startswith("<!--")]


def _rule_sentence() -> str:
    """The sentence of Section 7's comments that forbids (the one holding 'never')."""
    comments = " ".join(c[len("<!--"):-len("-->")].strip() for c in _comments(_section(7)))
    sentences = [s for s in re.split(r"(?<=[.;])\s+", comments) if re.search(r"\bnever\b", s, re.I)]
    assert sentences, "Section 7's comments hold no 'never ...' sentence"
    return sentences[0]


# --------------------------------------------------------------- the ruling (D33)

def test_section_7_says_everything_requested_is_done_in_this_cycle():
    comments = " ".join(_comments(_section(7)))
    assert re.search(r"everything the user requested is done in this cycle", comments, re.I)


@pytest.mark.parametrize("name", FORBIDDEN)
def test_section_7_forbids(name):
    sentence = _rule_sentence()
    never_at = re.search(r"\bnever\b", sentence, re.I).end()
    assert re.search(FORBIDDEN[name], sentence[never_at:], re.I), (
        f"Section 7 does not forbid {name!r}: {sentence!r}")


def test_section_7_keeps_parallel_lanes_inside_the_cycle():
    comments = " ".join(_comments(_section(7)))
    assert re.search(r"parallel lanes inside the cycle are fine", comments, re.I)


def test_no_other_comment_invites_deferral():
    """Only Section 7's rule may name a phase or a deferral, and only to forbid it. A retry of a
    failed cycle ("the next cycle's Dev must not repeat it") or a baseline "later cycles can compare"
    against is not a deferral and is not matched."""
    invites = re.compile(r"phase|\bMVP\b|defer|follow-?up|for (?:a|the) (?:later|next) cycle|backlog", re.I)
    for n in range(1, 10):
        for comment in _comments(_section(n)):
            if invites.search(comment):
                assert n == 7 and re.search(r"\bnever\b", comment, re.I), (
                    f"Section {n} comment invites deferral: {comment!r}")


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


def test_every_section_but_the_last_closes_with_a_rule_line():
    for n in range(1, 9):
        assert _section(n).rstrip("\n").endswith("\n---"), n
    assert _section(9).rstrip("\n").endswith(PLACEHOLDER)


def test_each_comment_is_one_line_that_opens_and_closes_itself():
    """scripts/spec-write.py treats a line that does not start with '<!--' as section body when it
    decides whether the placeholder is the section's only content; the splitter must copy each line."""
    for line in TEXT.split("\n"):
        if "<!--" in line or "-->" in line:
            assert line.startswith("<!--") and line.endswith("-->"), line


def test_section_7_keeps_its_writer_comment_for_the_consumers():
    who = [c for c in _comments(_section(7)) if "WHO WRITES" in c]
    assert len(who) == 1
    for needle in ("scripts/spec-write.py only", "qa.spec_section_updates.section_7", "unresolved_issues"):
        assert needle in who[0]
    assert any(c.startswith("<!-- WHAT:") for c in _comments(_section(7)))
    assert any(c.startswith("<!-- Example:") for c in _comments(_section(7)))


def test_the_overnight_spec_path_consumers_copy_reaches_the_same_text():
    """/spec, /spec-update and /dev-overnight copy templates/overnight-spec.md (a link to this file)."""
    copied = (REPO / "templates" / "overnight-spec.md").read_text(encoding="utf-8")
    assert copied == (REPO / "templates" / "spec-template.md").read_text(encoding="utf-8")
