"""commands/dev.md: a relayed producer question has one route when it goes unanswered, and the dev
re-dispatch carries the answer in the same lines as Step 5's BA re-dispatch (group 3 findings on #27:
c6735512020 item 2, c6737075938 item 2). The replay's /dev devquestion and P5 A20's ask=skip|decline|none
runs play this text: the question's `default` taken as a recorded assumption, carried in
`Previous answers`, and the dev re-dispatch's `Clarification round:` / `Previous answers:` lines after
`Context file:`."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _step(text: str, n: int) -> str:
    m = re.search(rf"^### Step {n}:.*?(?=^### Step )", text, flags=re.M | re.S)
    assert m, f"commands/dev.md has no Step {n}"
    return m.group(0)


def test_step5_names_the_unanswered_route():
    step5 = _step((ROOT / "commands" / "dev.md").read_text(encoding="utf-8"), 5)
    relay = next(l for l in step5.splitlines() if l.startswith("1. Relay it with ONE AskUserQuestion"))
    for form in ("skipped", "denied", "no AskUserQuestion offered"):
        assert form in relay, f"Step 5's relay names no route for an unanswered question ({form})"
    assert "take the artifact's `default` as an assumption" in relay
    assert '"assumption": "no answer (<why>); the question\'s default taken"' in relay
    # where the producer records it: the fields agents/ba.md and agents/dev.md name
    assert "the `assumptions` list it returns" in relay and "`implementation_notes`" in relay
    assert "`Clarification round:` and `Previous answers:` lines" in step5


def test_step12_dev_redispatch_carries_step5_lines():
    step12 = _step((ROOT / "commands" / "dev.md").read_text(encoding="utf-8"), 12)
    line = next(l for l in step12.splitlines() if l.startswith("If dev wrote its question artifact"))
    assert "right after its `Context file:` line" in line
    assert "`Clarification round: <N>`" in line and "`Previous answers: <JSON array of {question, answer} pairs>`" in line
    # the lines it names are Step 5's own, and Step 10's template has the `Context file:` anchor
    text = (ROOT / "commands" / "dev.md").read_text(encoding="utf-8")
    assert "  Clarification round: <N>\n  Previous answers: <JSON array of {question, answer} pairs>" in _step(text, 5)
    assert "  Context file: docs/dev/context-<timestamp>.json" in _step(text, 10)


def test_dev_agent_reads_previous_answers():
    agent = (ROOT / "agents" / "dev.md").read_text(encoding="utf-8")
    assert "re-dispatches dev with the answer in its `Previous answers:` line" in agent
