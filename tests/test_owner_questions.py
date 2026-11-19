"""The owner is asked only what he wants (2026-11-19). The kinds requirement_round.KEPT keeps are the only
AskUserQuestion calls hooks/pretool-tool-policy.py lets through, for the main agent alone and each in the step that
owns it; and no file under commands/ or agents/, nor CLAUDE.md, tells an agent to ask the owner after a refusal."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "pretool-tool-policy.py"
sys.path.insert(0, str(ROOT / "hooks"))
from lib import requirement_round  # noqa: E402

TASK = "20261119-120000"
ROUND_Q = {"question": "What should the page show?", "header": "Page", "multiSelect": False,
           "options": [{"label": "All jobs", "description": "every one"}, {"label": "Open jobs", "description": "x"}]}


def ask(project: Path, source, agent: bool = False, questions=None) -> subprocess.CompletedProcess:
    tin = {"questions": questions or [ROUND_Q]}
    if source is not None:
        tin["metadata"] = {"source": source}
    payload = {"tool_name": "AskUserQuestion", "tool_input": tin, "cwd": str(project), "session_id": "s",
               "transcript_path": str(project / "t.jsonl"), "tool_use_id": "toolu_1",
               **({"agent_id": "a1", "agent_type": "ba"} if agent else {})}
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project), "CLAUDE_STATE_DIR": str(project / "state")}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True,
                          env=env, timeout=60)


@pytest.fixture
def project(tmp_path):
    dev = tmp_path / "docs" / "dev"
    dev.mkdir(parents=True)
    (dev / f"requirement-round-{TASK}-r1.json").write_text(json.dumps(
        {"task_id": TASK, "round": 1, "questions": [{**ROUND_Q, "id": "q1", "dimension": "scope", "assume": "All jobs",
                                                     "options": [{**o, "ba": "A"} for o in ROUND_Q["options"]]}]}))
    (dev / f"producer-question-{TASK}-ba.json").write_text("{}")
    (tmp_path / "t.jsonl").write_text("")
    return tmp_path


def test_the_kept_kinds_are_the_three_the_owner_designed():
    assert set(requirement_round.KEPT) == {"requirement-round", "producer-question", "close-rating"}


@pytest.mark.parametrize("source", [f"requirement-round:{TASK}:r1", f"producer-question:{TASK}:ba"])
def test_a_kept_kind_in_its_step_reaches_the_owner(project, source):
    done = ask(project, source)
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("source", [None, "", "owner-decision:x:seed", "owner-confirmation:x:r04",
                                    "hook-rejection:x:r07-dispatch-gate", "do", "Requirement-round:x:r1",
                                    f"requirement-round:{TASK}:r2", f"producer-question:{TASK}:dev",
                                    f"close-rating:{TASK}", f"requirement-round-x:{TASK}:r1"])
def test_every_other_question_is_refused_with_what_to_do_instead(project, source):
    done = ask(project, source)
    assert done.returncode == 2, (source, done.stderr)
    assert "BLOCKED by tool-policy.v1" in done.stderr and "is not retried, disguised or worked around" in done.stderr
    assert "with the hook's own output" in done.stderr


def test_a_round_asked_otherwise_than_written_is_refused(project):
    altered = {**ROUND_Q, "question": "Which jobs do you want on the page?"}
    assert ask(project, f"requirement-round:{TASK}:r1", questions=[altered]).returncode == 2


@pytest.mark.parametrize("source", [f"requirement-round:{TASK}:r1", f"producer-question:{TASK}:ba", "x"])
def test_a_subagent_asks_nobody(project, source):
    done = ask(project, source, agent=True)
    assert done.returncode == 2 and "a subagent asks nobody" in done.stderr, done.stderr


# ---------------------------------------------------------------- no instruction asks the owner after a refusal
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_REFUSAL = re.compile(r"(?i)\brefus|\breject|hook rejection|\bdenied\b|\bdenial\b")
_ASKS = re.compile(r"(?i)AskUserQuestion|\bask(?:s|ed|ing)?\b[^.]{0,40}\b(?:owner|user|human)\b|"
                   r"\bowner (?:question|decision)s?\b|\bthe pause\b|\bescalat\w* to the (?:user|owner)")
_SAYS_NOT = re.compile(r"(?i)\bnobody\b|\bnever ask|\bno agent asks|refuses (?:every|an) `?AskUserQuestion|not asked|"
                       r"asks nothing|never a question|without a question|never about a refusal")


def asks_after_refusal(text: str) -> list:
    """The sentences (paragraphs joined) that name a refusal and tell someone to ask the owner."""
    return [s for para in re.split(r"\n\s*\n", text) for s in _SENTENCE.split(" ".join(para.split()))
            if _REFUSAL.search(s) and _ASKS.search(s) and not _SAYS_NOT.search(s)]


def test_the_text_check_finds_the_old_instructions():
    """Positive control: passages these files held before 2026-11-19."""
    for old in (
        "Outside `/dev-overnight` the pause is one specific in-turn `AskUserQuestion` naming the rejected operation "
        "and the exact command.",
        "**Refusals.** Where a step below refuses, ask ONE AskUserQuestion in this turn instead of exiting: the\n"
        "question is the refusal's message with its facts.",
        "the cleaner's `git commit` runs again only after the owner's `/allow` grant for it.\nThe orchestrator then "
        "asks the owner one AskUserQuestion inside the turn that names each refused action.",
        "A hook rejection, or another decision only the owner can\n   make, is one AskUserQuestion naming that "
        "parent and the decision.",
        "On a hook rejection ask one specific AskUserQuestion inside the turn naming the operation.",
    ):
        assert asks_after_refusal(old), old
    assert not asks_after_refusal("A refused operation is reported; nobody is asked about it.")


def test_no_instruction_tells_an_agent_to_ask_the_owner_after_a_refusal():
    files = sorted((ROOT / "commands").glob("*.md")) + sorted((ROOT / "agents").rglob("*.md")) + [ROOT / "CLAUDE.md"]
    assert len(files) > 20
    found = {f.relative_to(ROOT).as_posix(): hits for f in files
             if (hits := asks_after_refusal(f.read_text(encoding="utf-8")))}
    assert found == {}
