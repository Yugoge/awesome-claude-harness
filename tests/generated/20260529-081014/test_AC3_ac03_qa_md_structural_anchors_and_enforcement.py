"""AC3: agents/qa.md carries vacuity invariant in BOTH structural regions, replaces smoking-gun example, and binds guard exit code to qa.status.

Source: docs/dev/acceptance-criteria-20260529-081014.json AC3.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
QAMD = REPO / "agents" / "qa.md"


@pytest.fixture(scope="module")
def md_text() -> str:
    return QAMD.read_text()


def _phase5_region(md: str) -> str:
    lines = md.split("\n")
    start = next((i for i, ln in enumerate(lines)
                  if re.match(r"^#### Phase 5: Manifest Verification", ln)), None)
    assert start is not None, "cannot find ^#### Phase 5: anchor"
    end = None
    for j in range(start + 1, len(lines)):
        if re.match(r"^#{1,4}\s+", lines[j]) and not lines[j].startswith("#####"):
            end = j
            break
    if end is None:
        end = len(lines)
    return "\n".join(lines[start:end])


def _manifest_verification_region(md: str) -> str:
    m = re.search(r'"manifest_verification":\s*\{', md)
    assert m, "cannot find manifest_verification JSON object start"
    brace_start = m.end() - 1
    depth = 0
    in_str = False
    esc = False
    for k in range(brace_start, len(md)):
        c = md[k]
        if esc:
            esc = False
            continue
        if c == "\\" and in_str:
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return md[brace_start:k + 1]
    raise AssertionError("brace-counted region did not close")


def test_token_in_procedural_region(md_text: str):
    region = _phase5_region(md_text)
    assert re.search(r"vacuous_due_to_empty_active_set", region)


def test_token_in_schema_docblock(md_text: str):
    region = _manifest_verification_region(md_text)
    assert re.search(r"vacuous_due_to_empty_active_set", region)


def test_forbid_phrase_in_procedural(md_text: str):
    region = _phase5_region(md_text)
    pat = re.compile(
        r"active_tests_count\s*==\s*0[^\n]{0,400}(MUST NOT|forbid|禁止)[^\n]{0,200}pytest_collected_ok",
        re.DOTALL,
    )
    assert pat.search(region)


def test_guard_script_reference(md_text: str):
    region = _phase5_region(md_text)
    assert re.search(r"scripts/qa-manifest-guard\.py", region)


def test_guard_enforcement_exit_code_2_binds_qa_status_fail(md_text: str):
    region = _phase5_region(md_text)
    pat = re.compile(r"exit code 2[^\n]{0,400}qa\.status[^\n]{0,200}fail", re.DOTALL)
    assert pat.search(region)


def test_guard_enforcement_primary_cause_qa_oversight(md_text: str):
    region = _phase5_region(md_text)
    pat = re.compile(r"primary_cause[^\n]{0,200}qa_oversight", re.DOTALL)
    assert pat.search(region)


def test_guard_enforcement_qa_failures_within_proximity(md_text: str):
    region = _phase5_region(md_text)
    pat = re.compile(r"exit code 2[\s\S]{0,600}qa\.failures", re.DOTALL)
    assert pat.search(region)


def test_no_smoking_gun_example_in_schema_docblock(md_text: str):
    region = _manifest_verification_region(md_text)
    has_count_zero = bool(re.search(r'"active_tests_count"\s*:\s*0', region))
    has_ok_true = bool(re.search(r'"pytest_collected_ok"\s*:\s*true', region))
    assert not (has_count_zero and has_ok_true), \
        "smoking-gun shape (active_tests_count:0 AND pytest_collected_ok:true) found in manifest_verification JSON object"
