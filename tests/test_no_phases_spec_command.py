"""commands/spec.md carries the owner's "no phases" ruling (D33).

Parallel lanes inside one cycle stay. A spec, a view or a hand-off note never splits a requested outcome into
sequential phases, deferred parts, a "phase 2", an "MVP first" or work for a later cycle: every requested outcome is
delivered in the same cycle. The split QA of Step 6 is where that is checked, so its prompt must carry a criterion
that fails such a split; and the rest of the command must not invite phasing or deferral in its own words.

SPEC_COMMAND_UNDER_TEST=<path> points the file at another copy of the command; the default is commands/spec.md.
Pointing it at the pre-ruling text (`git show d64fa96:commands/spec.md`) must fail the rule tests and pass the
structure tests.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PATH = Path(os.environ.get("SPEC_COMMAND_UNDER_TEST") or REPO / "commands" / "spec.md")
TEXT = PATH.read_text(encoding="utf-8")
LINES = TEXT.split("\n")

# What the criterion must forbid, each as the pattern that names it.
FORBIDDEN = {
    "sequential phases": r"\bsequential phases\b",
    "phase 2": r"\bphase 2\b",
    "MVP first": r"\bMVP first\b",
    "deferred parts": r"\bdeferred parts\b",
    "a later cycle": r"\b(?:a|for a) later cycle\b",
}
VOCABULARY = re.compile(r"\bphases?\b|\bMVP\b|\bdeferred\b|\blater cycle\b", re.I)
CRITERION = re.compile(r"^[ \t]*(\d+)\.[ \t]+([A-Z][A-Z0-9 &()/-]*):")
JSON_LINE = "Return JSON: {verdict: pass|fail, issues: [...], summary: '...'}"


def fenced_blocks(text: str) -> list[tuple[int, str]]:
    """(1-based line of the opening fence, body) of each fenced block."""
    out, start, body = [], None, []
    for number, line in enumerate(text.split("\n"), 1):
        if re.match(r"^\s*```", line):
            if start is None:
                start, body = number, []
            else:
                out.append((start, "\n".join(body)))
                start = None
        elif start is not None:
            body.append(line)
    return out


def qa_prompt() -> tuple[int, str]:
    found = [(n, b) for n, b in fenced_blocks(TEXT) if "Validate the spec split" in b]
    assert len(found) == 1, f"{len(found)} blocks hold the split-QA prompt"
    return found[0]


def criteria() -> list[tuple[int, str, str, int]]:
    """(number, name, text, first line in the file) of each criterion of the split-QA prompt."""
    first, body = qa_prompt()
    rows: list[list] = []
    for offset, line in enumerate(body.split("\n")):
        match = CRITERION.match(line)
        if match:
            rows.append([int(match.group(1)), match.group(2), line, first + 1 + offset])
        elif rows and not line.strip().startswith("Return JSON"):
            rows[-1][2] += "\n" + line
        elif line.strip().startswith("Return JSON"):
            break
    return [tuple(row) for row in rows]


def no_phasing() -> tuple[int, str, str, int]:
    found = [c for c in criteria() if re.search(r"\bphase 2\b", c[2])]
    assert len(found) == 1, f"{len(found)} criteria of the split QA name a 'phase 2'"
    return found[0]


# ------------------------------------------------------------ the split QA keeps its shape
def test_the_criteria_are_numbered_one_to_n_with_no_gap():
    numbers = [c[0] for c in criteria()]
    assert len(numbers) >= 6 and numbers == list(range(1, len(numbers) + 1)), numbers


def test_the_qa_returns_the_same_pass_fail_json_after_the_last_criterion():
    _, body = qa_prompt()
    assert body.count(JSON_LINE) == 1
    assert body.index(JSON_LINE) > body.index(criteria()[-1][1])


def test_the_first_six_criteria_keep_their_names():
    names = [c[1] for c in criteria()][:6]
    assert names == ["ROLE MANDATE", "AGENT SELECTION", "COVERAGE", "CONTENT RELEVANCE", "FUNCTIONAL COMPLETENESS",
                     "SECTION 9 (DESIGN & EVIDENCE REFERENCES)"]


# ------------------------------------------------------------ the ruling (D33)
def test_the_seventh_criterion_is_the_one_that_fails_phasing():
    number, name, text, _ = no_phasing()
    assert number == 7, f"the no-phases criterion is number {number}"
    assert re.search(r"\bfail\b", text, re.I), "the criterion does not say the split fails"
    assert re.search(r"\b(?:the spec or any view|any view)\b", text), "the criterion does not cover the views and the spec"


@pytest.mark.parametrize("name", FORBIDDEN)
def test_the_criterion_forbids(name):
    _, _, text, _ = no_phasing()
    assert re.search(FORBIDDEN[name], re.sub(r"\s+", " ", text), re.I), f"the criterion does not forbid {name!r}"


def test_the_criterion_says_every_requested_outcome_is_delivered_in_one_cycle():
    _, _, text, _ = no_phasing()
    assert re.search(r"every requested outcome is delivered in (?:one|the same) cycle", re.sub(r"\s+", " ", text), re.I)


def test_the_criterion_keeps_parallel_lanes_inside_one_cycle():
    _, _, text, _ = no_phasing()
    assert re.search(r"parallel lanes inside one cycle are fine", re.sub(r"\s+", " ", text), re.I)


def test_the_criterion_is_as_terse_as_the_others():
    longest_other = max(len(c[2].split()) for c in criteria() if c[0] != 7)
    assert len(no_phasing()[2].split()) <= longest_other


# ------------------------------------------------------------ nothing else in the command invites phasing
def allowed_lines() -> set[int]:
    number, _, text, first = no_phasing()
    allowed = set(range(first, first + text.count("\n") + 1))
    start = next(i for i, line in enumerate(LINES, 1) if re.match(r"^### Step 7\b", line))
    end = next((i for i, line in enumerate(LINES, 1) if i > start and re.match(r"^(#{2,3}) ", line)), len(LINES) + 1)
    return allowed | set(range(start, end))


def test_no_other_line_speaks_of_phases_deferral_or_an_mvp():
    allowed = allowed_lines()
    stray = [f"{n}: {line.strip()[:100]}" for n, line in enumerate(LINES, 1) if VOCABULARY.search(line) and n not in allowed]
    assert not stray, "lines outside the criterion and Step 7 speak of phasing or deferral:\n" + "\n".join(stray)


def test_step_7_only_mentions_phases_to_forbid_them():
    start = next(i for i, line in enumerate(LINES) if re.match(r"^### Step 7\b", line))
    section = "\n".join(LINES[start:])
    section = section[:section.index("\n## ")] if "\n## " in section else section
    sentences = [s for s in re.split(r"(?<=[.;:])\s+", re.sub(r"\s+", " ", section)) if VOCABULARY.search(s)]
    assert sentences, "Step 7 no longer says the hand-off never phases or defers a requested outcome"
    assert all(re.search(r"\bnever\b|\bno\b|\bnot\b", s, re.I) for s in sentences), sentences


def test_step_7_hands_off_to_the_run_that_implements_the_spec_not_to_a_next_phase():
    start = next(i for i, line in enumerate(LINES) if re.match(r"^### Step 7\b", line))
    section = "\n".join(LINES[start:start + 6])
    assert "the `/dev` run that implements this spec" in section
    assert not re.search(r"\bnext (?:phase|stage|cycle)\b", TEXT, re.I)
