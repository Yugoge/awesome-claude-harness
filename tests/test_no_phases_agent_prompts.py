"""No phases, no deferral: the rule in the agent prompts, and what QA fails.

Parallel lanes inside one /dev cycle stay. Sequential phases, deferred parts and "later cycle" plans never
do: every requested outcome is delivered in the same cycle. ba, spec, dev and qa carry the rule in one line and
point at agents/shared/no-phases.md, which defines it; QA fails a plan or a cycle that breaks it in three places
(the BA-QA check, the spec-split check and the close gate).

What a test can show here: a replay plays an agent's text through the hooks, it does not run a model, so no
replay can show whether a model splits a task into phases. These tests pin what decides it: the rule text, the
three QA fail conditions, and that the old wording that let QA pass a narrowed cycle is gone. They also hold the
two charter lines every agent carries to one text, so the copies cannot drift apart.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
AGENTS = REPO / "agents"
SHARED = AGENTS / "shared" / "no-phases.md"
FOUR = ("ba", "spec", "dev", "qa")

RULE_LINE = (
    '**No phases.** Every outcome the user requested is delivered in this cycle: parallel lanes are fine; '
    'sequential phases, deferred parts and "later cycle" plans are not. Definition and what QA fails: '
    '`${CLAUDE_HOME:-$HOME/.claude}/agents/shared/no-phases.md`.'
)
# A line that names one of these forms must be a line that forbids or fails it.
PHASE_FORMS = ('"phase 2"', '"mvp first"', '"later cycle"', '"follow-up task"', '"next /dev"')
FORBIDS = ("no-phases.md", "fail", "objection", "not.")
CHARTER = ("**Requirement baseline (charter", "**Scope authority (charter")


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _agent_files():
    return sorted(p for p in AGENTS.glob("*.md") if p.name not in ("README.md", "INDEX.md"))


def test_the_shared_file_defines_the_rule():
    text = SHARED.read_text(encoding="utf-8")
    for needle in (
        "Parallel lanes inside one cycle are fine",
        "never allowed",
        "another /dev session",
        '"phase 1"', '"phase 2"', '"MVP first"', '"later cycle"', '"a follow-up task"',
        "Won't have",
        "out_of_scope_observations",
        "BA-QA (`scope_alignment`)",
        "Spec-split QA",
        "Final and close QA",
        '"Partially addressed" is not a pass',
    ):
        assert needle in text, f"agents/shared/no-phases.md lost: {needle}"


@pytest.mark.parametrize("name", FOUR)
def test_each_of_the_four_agents_carries_the_one_line_rule(name):
    lines = _text(f"agents/{name}.md").splitlines()
    assert any(l.startswith(RULE_LINE) for l in lines), f"agents/{name}.md has no '**No phases.**' line"
    assert SHARED.is_file()


def test_qa_fails_a_plan_that_phases_or_defers_in_the_ba_qa_check():
    qa = _text("agents/qa.md")
    line = next(l for l in qa.splitlines() if l.startswith("2. **`scope_alignment`**"))
    assert "sequential phases" in line and "blocking objection" in line
    assert "MVP first" in line and "later cycle" in line


def test_qa_fails_a_spec_split_that_phases_or_defers():
    qa = _text("agents/qa.md")
    assert "## Spec-split validation (dispatched by /spec)" in qa
    body = qa.split("## Spec-split validation (dispatched by /spec)", 1)[1].split("\n## ", 1)[0]
    assert "fails the split" in body and "sequential phases" in body


def test_qa_fails_a_close_that_leaves_an_outcome_for_later():
    qa = _text("agents/qa.md")
    body = qa.split("**Close-gate lane-matrix exception", 1)[1].split("\n---", 1)[0]
    flat = re.sub(r"\s+", " ", body)
    assert "fail the parent close when any requested outcome is left for a later cycle" in flat
    assert '"partially addressed" is not a pass' in flat


def test_qa_no_longer_passes_a_narrowed_cycle():
    qa = _text("agents/qa.md")
    for old in ("QA can pass the cycle scope", "A spec may have narrowed the current cycle's scope",
                "Cycle N scope: PASS", "Cycle scope: PASS. Original bug scope: PARTIALLY ADDRESSED"):
        assert old not in qa, f"agents/qa.md still lets QA pass a narrowed cycle: {old}"
    p7 = next(l for l in qa.splitlines() if l.startswith("**7. "))
    assert "whole requirement" in p7 and "`fail`" in p7 and "is not a pass" in p7
    p10 = next(l for l in qa.splitlines() if l.startswith("**10. "))
    assert '"later cycle"' in p10 and "`fail`" in p10


def test_ba_sorts_only_additions_into_should_could_wont():
    ba = _text("agents/ba.md")
    step6 = ba.split("### Step 6:", 1)[1].split("### Step 7:", 1)[0]
    assert "Everything the user requested is Must have" in step6
    assert "sort only what you propose beyond the request" in step6
    assert "no phase, no deferred part and no narrower scope" in step6


def test_dev_completed_means_every_requested_outcome_is_delivered():
    dev = _text("agents/dev.md")
    assert "`completed` means every requested outcome is delivered" in dev
    assert '"remaining" or "next phase" list' in dev


@pytest.mark.parametrize("name", FOUR)
def test_no_line_of_the_four_names_a_phase_form_without_forbidding_it(name):
    for i, line in enumerate(_text(f"agents/{name}.md").splitlines(), 1):
        low = line.lower()
        if any(form in low for form in PHASE_FORMS):
            assert any(f in low for f in FORBIDS), f"agents/{name}.md:{i} names a phase form without forbidding it"


def test_the_charter_lines_are_one_text_in_every_agent():
    seen = {key: {} for key in CHARTER}
    for path in _agent_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for key in CHARTER:
            found = [l for l in lines if l.startswith(key)]
            assert len(found) == 1, f"{path.name} must carry exactly one line starting {key}"
            seen[key].setdefault(found[0], []).append(path.name)
    for key, variants in seen.items():
        assert len(variants) == 1, f"{key}) differs between agents: " + "; ".join(
            f"{names[:3]}" for names in variants.values())
