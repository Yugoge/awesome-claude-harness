"""commands/close.md as P4 decided it: one disposition call, in-turn questions, the native rating."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TEXT = (REPO / "commands" / "close.md").read_text(encoding="utf-8")
# P13-2 B6: the producer side reads and mentions no score log (the acceptance test's grep, word for word)
PRODUCERS = ("commands/close.md", "commands/commit.md", "agents/changelog-analyst.md")
SCORE_LOG_WORDS = re.compile(r"score_log|lifecycle\.jsonl|score-(inject|update)")


def _section(heading: str) -> str:
    start = TEXT.index(heading)
    nxt = TEXT.find("\n## ", start + 1)
    sub = TEXT.find("\n### ", start + 1)
    ends = [e for e in (nxt, sub) if e > 0]
    return TEXT[start:min(ends)] if ends else TEXT[start:]


def test_retired_routing_and_scoring_vocabulary_is_gone() -> None:
    for word in ("close-route-select", "route_finding", "artifact_role", "aggregate-dev-report.py", "write-enforce-flag",
                 "pass_with_exceptions", "<options>", "user_rating", "score-update",
                 "arbitration", "ARBITRATION", "AWAITING_INPUT", "R15", "FORCED", "jq ", "continue-cycle.md"):
        assert word not in TEXT, word
    assert not re.search(r"awaiting.input", TEXT, re.I)


def test_step0_is_one_disposition_call_with_one_retry_then_a_stall_line() -> None:
    step0 = _section("### Step 0:")
    assert TEXT.count("resolve-dev-artifact-chain.py --disposition") == 1
    assert "--disposition --stage dev" in step0
    assert "run the same call once more" in step0
    assert "`OPERATION_STALLED: <the stderr reason>`" in step0
    assert "no question, no verdict line, no close-report section" in step0


def test_force_is_named_only_where_the_rule_allows() -> None:
    lines = [line for line in TEXT.splitlines() if "--force" in line]
    allowed = ("description:", "is accepted and ignored", "<!-- Cross-reference", "validate_auto_flag_combination",
               "`--late-repair` with `--force`")
    assert lines and all(any(a in line for a in allowed) for line in lines), lines


def test_every_wait_is_an_owner_question_with_a_short_header() -> None:
    assert "exactly one AskUserQuestion call: a header of at most 12 characters, 2-4 options" in TEXT
    assert "no option offers to stop, to end, or to leave the cycle unfinished" in TEXT
    headers = re.findall(r"header `([^`]+)`", TEXT)
    assert {"Close mode", "Task", "Repair mode", "Request", "Scope", "Append", "Authorize"} <= set(headers)
    assert all(len(h) <= 12 for h in headers)


def test_step3b_asks_the_native_rating_once_and_leaves_the_answer_alone() -> None:
    step4 = _section("### Step 3b:")
    block = re.search(r"```json\n(.*?)```", step4, re.S).group(1)
    ask = json.loads(block.replace("<task-id>", "20260101-000000"))
    [question] = ask["questions"]
    assert question["question"] == "How well did cycle 20260101-000000 meet what you asked for?"
    assert question["header"] == "Rating" and question["multiSelect"] is False
    assert [o["label"] for o in question["options"]] == ["5 - Fully met", "4 - Minor gaps", "3 - Major gaps",
                                                          "1-2 - Not met"]
    assert ask["metadata"] == {"source": "close-rating:20260101-000000"}
    assert "Skip" not in json.dumps(question)
    assert "does nothing with the answer" in step4
    assert "one per landed parent, each with its own source" in step4


def test_a_do_task_is_completed_by_dev_whose_own_report_concludes_it() -> None:
    """Q7: Routes' /do bullet dispatches dev with a template obligation naming dev's own report, never the
    do-report (the /do main agent stays its one producer); the /close orchestrator writes no report."""
    routes = _section("### Routes")
    [item] = [line for line in routes.splitlines() if line.startswith("- A `/do` task")]
    block = re.search(r'`<obligation v="1">(\{.*?\})</obligation>`', item).group(1)
    ob = json.loads(re.sub(r"<[^>\"]*>", "x", block))
    assert {k: ob[k] for k in ("role", "pipeline", "profile")} == {"role": "dev", "pipeline": "do",
                                                                   "profile": "singular"}
    [art] = ob["artifacts"]
    assert (art["path"], art["schema"]) == ("docs/dev/dev-report-x.json", "dev-report.v2")
    assert "do-report" not in block
    assert "concludes a `/do` task whose do-report is not `completed`" in item
    assert "the `/close` orchestrator writes no report" in item


def test_commit_routes_a_do_task_with_the_close_template_and_rule() -> None:
    """Q7 in /commit: Routes' /do bullet spells /close's template verbatim and the same conclusion rule."""
    commit = (Path(__file__).resolve().parent.parent / "commands" / "commit.md").read_text(encoding="utf-8")
    routes = commit[commit.index("### Routes"):commit.index("### Step 3:")]
    [item] = [it for it in re.split(r"\n(?=- )", routes) if it.startswith("- A `/do` task")]
    template = re.compile(r'`(<obligation v="1">\{.*?\}</obligation>)`')
    [close_item] = [line for line in _section("### Routes").splitlines() if line.startswith("- A `/do` task")]
    assert template.search(item).group(1) == template.search(close_item).group(1)
    flat = " ".join(item.split())
    assert "concludes a `/do` task whose do-report is not `completed` (Step 3's call takes it)" in flat
    assert "the `/commit` orchestrator writes no report" in flat


def _score_log_mentions(root: Path) -> list[str]:
    """The producer files under `root` with a line the acceptance grep would print."""
    return [name for name in PRODUCERS if SCORE_LOG_WORDS.search((root / name).read_text(encoding="utf-8"))]


def test_the_producer_side_mentions_no_score_log() -> None:
    assert _score_log_mentions(REPO) == []


@pytest.mark.parametrize("word", ["score_log", "lifecycle.jsonl", "score-inject", "score-update"])
@pytest.mark.parametrize("name", PRODUCERS)
def test_the_b6_check_fails_on_a_copy_that_mentions_the_score_log(tmp_path: Path, name: str, word: str) -> None:
    for each in PRODUCERS:  # copies: the real files are never edited
        (tmp_path / each).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / each, tmp_path / each)
    assert _score_log_mentions(tmp_path) == []
    with open(tmp_path / name, "a", encoding="utf-8") as copy:
        copy.write(f"\nRead {word} first.\n")
    assert _score_log_mentions(tmp_path) == [name]
