"""Differential test: the write gate's `combine` answers exactly as it did before its refactor.

hooks/lib/write_gate/__init__.py's `combine` (cyclomatic complexity 37) was split into helpers
with no behaviour change. tests/differential/combine_legacy.py holds a verbatim copy of the
function as it stood at commit cc22f78. Every case below runs both on the same (Rule, RuleRun)
pairs and asserts the same Answer: exit code, stdout and stderr, byte for byte.

The inputs cover every branch of the frozen copy: run errors under a fail-closed and a fail-open
rule; exit codes 0, 2 and others; stdout that is empty, not JSON, a JSON non-object, an empty
object, and every hookSpecificOutput field (each decision and an unknown one, reasons of every
type, updatedInput as an object and as something else, additionalContext truthy and falsy); the
deprecated block/approve form; and sequences of up to five rules, the real rule table's included.
test_every_line_of_the_frozen_copy_runs guards that the cases keep reaching all of it.
"""
from __future__ import annotations

import copy
import importlib.util
import itertools
import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hooks"))

from lib import write_gate  # noqa: E402
from lib.rule_runner import RuleRun  # noqa: E402


def _load_legacy():
    spec = importlib.util.spec_from_file_location(
        "write_gate_combine_legacy", Path(__file__).with_name("combine_legacy.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LEGACY = _load_legacy()


def _rule(name: str, fail: str) -> write_gate.Rule:
    return write_gate.Rule(name, f"{name}.py", None, "both", fail, (), 5.0)


RULES = [_rule("alpha", "open"), _rule("beta", "closed")] + list(write_gate.RULES)

_HSO_DECISIONS = [None, "deny", "defer", "ask", "allow", "bogus"]
_REASONS = [None, "", "why", 7, "why\n"]
_UPDATED = [None, {}, {"command": "ls"}, ["not", "a", "dict"], "text"]
_CONTEXTS = [None, "", "context", 0, ["a"], {"k": 1}]


def _hso_shapes():
    """Every hookSpecificOutput the rules can print, and a few they should not."""
    shapes = [None, "not-a-dict", ["list"], 5]
    for decision, reason, updated, context in itertools.product(
            _HSO_DECISIONS, _REASONS, _UPDATED, _CONTEXTS):
        hso = {"hookEventName": "PreToolUse"}
        if decision is not None:
            hso["permissionDecision"] = decision
        if reason is not None:
            hso["permissionDecisionReason"] = reason
        if updated is not None:
            hso["updatedInput"] = updated
        if context is not None:
            hso["additionalContext"] = context
        shapes.append(hso)
    return shapes


def _stdouts():
    """Exit-status text a rule can print: nothing, junk, JSON of every relevant shape."""
    texts = ["", "   ", "not json", "{not json", "[1, 2]", '"a string"', "{}", '{"other": 1}', "null"]
    for deprecated, reason in itertools.product([None, "block", "approve", "other"], [None, "", "blocked"]):
        out = {}
        if deprecated is not None:
            out["decision"] = deprecated
        if reason is not None:
            out["reason"] = reason
        if out:
            texts.append(json.dumps(out))
            texts.append(json.dumps({**out, "hookSpecificOutput": {"permissionDecision": "ask",
                                                                    "permissionDecisionReason": "asked"}}))
    for hso in _hso_shapes():
        out = {} if hso is None else {"hookSpecificOutput": hso}
        texts.append(json.dumps(out))
    texts.append("  " + json.dumps({"hookSpecificOutput": {"permissionDecision": "allow"}}) + "\n")
    return texts


STDOUTS = _stdouts()
CODES = [0, 2, 1, 3, -9]
STDERRS = ["", "a refusal on stderr", "a message\n"]
ERRORS = ["", "raised ValueError: boom", "overran its 5.0 s budget"]


def _run(code, stdout, stderr, error) -> RuleRun:
    return RuleRun(code=code, stdout=stdout, stderr=stderr, error=error)


def _single_runs():
    """One run of every exit code, stdout, stderr and error, without the redundant error cases."""
    for code, stdout, stderr in itertools.product(CODES, STDOUTS, STDERRS):
        yield _run(code, stdout, stderr, "")
    for code, error, stderr in itertools.product(CODES, ERRORS[1:], STDERRS):
        yield _run(code, '{"hookSpecificOutput": {"permissionDecision": "deny"}}', stderr, error)


SINGLE_RUNS = list(_single_runs())


def _cases():
    """(Rule, RuleRun) sequences: every single run under every rule shape, then fixed-seed random
    sequences of up to five rules, then every pair of a smaller, branch-dense pool."""
    cases = [[]]
    for rule, run in itertools.product(RULES[:2], SINGLE_RUNS):
        cases.append([(rule, run)])
    rng = random.Random(20261110)
    for _ in range(6000):
        n = rng.randint(1, 5)
        cases.append([(rng.choice(RULES), rng.choice(SINGLE_RUNS)) for _ in range(n)])
    pool = [run for run in SINGLE_RUNS if run.stderr != "a message\n"][::61]
    for first, second in itertools.product(pool, repeat=2):
        cases.append([(RULES[0], first), (RULES[1], second)])
    return cases


CASES = _cases()


def _answer(fn, case):
    answer = fn(copy.deepcopy(case))
    return answer.code, answer.stdout, answer.stderr


def test_there_are_thousands_of_cases():
    assert len(CASES) > 5000


def test_live_combine_answers_exactly_as_the_frozen_copy():
    mismatches = []
    for index, case in enumerate(CASES):
        old, new = _answer(LEGACY.combine, case), _answer(write_gate.combine, case)
        if old != new:
            mismatches.append((index, case, old, new))
    assert not mismatches, f"{len(mismatches)} of {len(CASES)} cases differ; first: {mismatches[0]}"


@pytest.mark.parametrize("decision", ["deny", "defer", "ask", "allow"])
def test_each_decision_alone_agrees(decision):
    run = _run(0, json.dumps({"hookSpecificOutput": {"permissionDecision": decision,
                                                     "permissionDecisionReason": decision}}), "", "")
    case = [(RULES[0], run)]
    assert _answer(LEGACY.combine, case) == _answer(write_gate.combine, case)


def test_every_line_of_the_frozen_copy_runs():
    """The cases reach every line of the frozen function, so a narrowed corpus cannot pass."""
    code = LEGACY.combine.__code__
    seen: set[int] = set()

    def tracer(frame, event, arg):
        if frame.f_code is code:
            if event == "line":
                seen.add(frame.f_lineno)
            return tracer
        return None

    sys.settrace(tracer)
    try:
        for case in CASES[: 1 + 2 * len(SINGLE_RUNS)]:
            LEGACY.combine(case)
    finally:
        sys.settrace(None)
    body = {line for _, _, line in code.co_lines() if line is not None and line > code.co_firstlineno}
    assert body - seen == set(), f"lines of the frozen combine never run: {sorted(body - seen)}"
