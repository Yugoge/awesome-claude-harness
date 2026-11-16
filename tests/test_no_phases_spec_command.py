"""commands/spec.md's split QA carries the owner's "no phases" ruling (D33), shown by the code that reads it.

Parallel lanes inside one cycle stay. A spec or a view never splits a requested outcome into sequential phases,
deferred parts, a "phase 2", an "MVP first" or work for a later cycle. The split QA of Step 6 is where /spec checks
that, through criterion 7 of its prompt. No hook or script judges a phased plan: the QA is a model. The one code that
reads the ruling is the replay /spec driver (tests/replay/drivers/spec.py, SpecRun.split_qa): it renders Step 6's
split-QA dispatch from the command text and refuses to dispatch it (cmdtext.TextNotFound) unless one criterion fails
phased or deferred work and keeps parallel lanes. These tests run that step on the command under test, which must
dispatch, and on a phased variant of it (criterion 7 rewritten to license an MVP first, a 'phase 2' and deferred parts
for a later cycle; or criterion 7 dropped), which must be refused. The driver's check is word-level: it shows the
criterion is there, not how a QA model applies it.

The structure tests keep the prompt's criteria parseable (numbered 1 to N, the first six names, which the driver's
check 3 slicing reads).

SPEC_COMMAND_UNDER_TEST=<path> points the file at another copy of the command; the default is commands/spec.md.
Pointing it at the pre-ruling text (`git show d64fa96:commands/spec.md`, no criterion 7) fails the dispatch test
(the driver refuses it), fails the variant tests (nothing to rewrite) and passes the structure tests.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import types
from pathlib import Path

import pytest

from tests.replay import cmdtext
from tests.replay.drivers import spec as spec_driver

REPO = Path(__file__).resolve().parents[1]
PATH = Path(os.environ.get("SPEC_COMMAND_UNDER_TEST") or REPO / "commands" / "spec.md")
TEXT = PATH.read_text(encoding="utf-8")

CRITERION = re.compile(r"^[ \t]*(\d+)\.[ \t]+([A-Z][A-Z0-9 &()/-]*):")

# Criterion 7 as a phased plan would have it: it names every form of phasing, and licenses it.
PHASED_CRITERION = (
    "     7. DELIVERY PLAN: The spec may deliver an MVP first and leave deferred parts, a 'phase 2',\n"
    "        for a later cycle. List each deferred part in `issues`.")


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


def qa_prompt(text: str = TEXT) -> tuple[int, str]:
    found = [(n, b) for n, b in fenced_blocks(text) if "Validate the spec split" in b]
    assert len(found) == 1, f"{len(found)} blocks hold the split-QA prompt"
    return found[0]


def criteria(text: str = TEXT) -> list[tuple[int, str, str, int]]:
    """(number, name, text, first line in the file) of each criterion of the split-QA prompt."""
    first, body = qa_prompt(text)
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


def without_criterion_7(text: str, replacement: str | None) -> str:
    """`text` with criterion 7 of the split-QA prompt (its lines up to the blank line before Return JSON) replaced by
    `replacement`, or dropped when it is None."""
    number, _, body, first = next(c for c in criteria(text) if c[0] == 7)
    lines = text.split("\n")
    count = len(body.rstrip("\n").split("\n"))
    new = [] if replacement is None else replacement.split("\n")
    return "\n".join(lines[:first - 1] + new + lines[first - 1 + count:])


class _Session:
    """The replay session's dispatch, recorded instead of played."""

    def __init__(self):
        self.dispatches: list[tuple[str, str, dict]] = []

    def dispatch(self, atype, prompt, **kw):
        self.dispatches.append((atype, prompt, kw))


def split_qa(command_text: str, tmp_path: Path) -> tuple[str, _Session]:
    """Run the replay /spec driver's Step 6 split QA on `command_text` as commands/spec.md of a harness home in
    `tmp_path`; returns its verdict and the recorded session."""
    harness, project = tmp_path / "harness", tmp_path / "project"
    (harness / "commands").mkdir(parents=True)
    (harness / "agents").mkdir()
    (project / "docs" / "dev" / "specs").mkdir(parents=True)
    (harness / "commands" / "spec.md").write_text(command_text, encoding="utf-8")
    shutil.copy(REPO / "agents" / "spec.md", harness / "agents" / "spec.md")
    session = _Session()
    rp = types.SimpleNamespace(layout=types.SimpleNamespace(harness=str(harness), project=str(project)),
                               acting=lambda who: contextlib.nullcontext(), session=lambda: session)
    run = spec_driver.SpecRun(rp, "plain")
    run.spec_id, run.path = "toy-spec", str(project / "docs" / "dev" / "specs" / "toy-spec.md")
    return run.split_qa(), session


# ------------------------------------------------------------ the split QA keeps its shape
def test_the_criteria_are_numbered_one_to_n_with_no_gap():
    numbers = [c[0] for c in criteria()]
    assert len(numbers) >= 6 and numbers == list(range(1, len(numbers) + 1)), numbers


def test_the_first_six_criteria_keep_their_names():
    names = [c[1] for c in criteria()][:6]
    assert names == ["ROLE MANDATE", "AGENT SELECTION", "COVERAGE", "CONTENT RELEVANCE", "FUNCTIONAL COMPLETENESS",
                     "SECTION 9 (DESIGN & EVIDENCE REFERENCES)"]


# ------------------------------------------------------------ the ruling (D33), as the replay driver reads it
def test_the_replay_dispatches_the_split_qa_of_the_command_under_test(tmp_path):
    verdict, session = split_qa(TEXT, tmp_path)
    assert verdict == "pass"
    assert [(atype, kw["label"]) for atype, _, kw in session.dispatches] == [("qa", "Step 6 Agent(qa) split QA round 1")]
    result = session.dispatches[0][2]["result"]
    assert json.loads(result.split("\n\n")[0])["verdict"] == "pass"
    assert result.split("\n")[-1] == "SPLIT QA: pass"


@pytest.mark.parametrize("replacement", [PHASED_CRITERION, None], ids=["licenses-phases", "dropped"])
def test_the_replay_refuses_a_split_qa_that_does_not_fail_phased_work(tmp_path, replacement):
    phased = without_criterion_7(TEXT, replacement)
    assert [c[0] for c in criteria(phased)][-1] == (7 if replacement else 6)
    with pytest.raises(cmdtext.TextNotFound, match="no criterion that fails phased or deferred work"):
        split_qa(phased, tmp_path)
