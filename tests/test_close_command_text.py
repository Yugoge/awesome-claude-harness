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


def test_step4_asks_the_native_rating_once_and_leaves_the_answer_alone() -> None:
    step4 = _section("### Step 4:")
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


# --- P12: the slimmed text keeps its rules; D31's Codex review loop in Step 2 ---------------------------------

def _qa_prompt() -> str:
    step2 = _section("### Step 2:")
    return re.search(r"```\n(FIRST ACTION:.*?)\n```", step2, re.S).group(1)


def test_no_stamps_dead_references_or_history_are_left() -> None:
    for stamp in ("spec-2026", "task 2026", "ba-spec-2026", "AC-2.6", "AC-12.1", "Section 5.", "Trap 11", "BUG-CLOSE",
                  "FINDING-4", "R4 —", "R1's route", "Must-Have", "venv/bin/activate", "close-overrides.log",
                  "deprecated", "Cross-reference"):
        assert stamp not in TEXT, stamp
    assert len(re.findall(r"CRITICAL|MANDATORY|NON-NEGOTIABLE|HARD RULE|PARAMOUNT", TEXT)) <= 3


def test_force_effect_is_stated_once() -> None:
    assert TEXT.count("is accepted and ignored") == 2  # the frontmatter description and the Invocation line
    assert "it changes nothing and nothing is logged" in TEXT


def test_which_task_offers_the_skipped_tasks_of_stderr() -> None:
    para = next(p for p in TEXT.split("\n\n") if p.startswith("**Which task?**"))
    assert "`<task-id>: skipped: <reason>` stderr line" in para and "`/close <task-id>` takes it" in para


def test_a_do_task_without_a_do_report_is_still_a_do_task() -> None:
    resolution = _section("### Task-id resolution")
    assert "or when a GAP line of Step 0 names it" in resolution
    assert "`DO_REPORT` to `docs/dev/do-report-<TASK_ID>.json`" in resolution


def test_a_do_task_has_no_registry_so_its_dispatches_leave_first_action_out() -> None:
    step1 = _section("### Step 1:")
    assert "A `/do` task (`DO_REPORT` set) has no registry directory" in step1
    assert "leave the FIRST ACTION line out of every dispatch of Steps 1 and 2" in step1


def test_every_dev_dispatch_without_a_record_names_its_template() -> None:
    routes = _section("### Routes")
    assert "from the cycle command's dev template" in routes
    cycle = next(p for p in routes.split("\n\n") if p.startswith("**Cycle templates.**"))
    for part in ("`commands/dev.md`", "`commands/dev-command.md`", "Step 4 for BA", "Step 10 for dev", "Step 13"):
        assert part in cycle, part
    late = _section("### Late-repair route")
    assert 'each from the cycle command\'s own template (Routes, "Cycle templates")' in late


def test_the_inspector_dispatches_and_qa_prompt_have_one_disposition_line() -> None:
    assert "- Disposition: chain_pass (Step 0's last run)\n" in _qa_prompt()
    assert "verify-disclosure" not in _qa_prompt()


def test_codex_review_follows_the_shared_include_and_the_d31_loop() -> None:
    prompt = _qa_prompt()
    assert "templates/prompt-includes/codex-consultation.md" in prompt
    for rule in (
        "QA decides the verdict; Codex has no veto.",
        "Round 1 is one complete pass",
        "Flip items are the blocker, high and medium findings with a realistic trigger that you classify in_scope_real_bug.",
        "Rounds 2 and 3 are re-reviews",
        "only new blocker or high defects the fix itself introduced",
        "Never ask for a new complete pass.",
        "After round 3 nothing below blocker reopens the cycle",
        "goes to the follow-up list and the close lands",
        "A blocker still open is a finding (branch 3)",
        "ask Codex once more for that line; if that fails too, your own verdict stands with a note",
        "USER REQUIREMENT", "SCOPE", "OUT OF SCOPE",
    ):
        assert rule in prompt, rule
    for word in ("in_scope_real_bug", "in_scope_minor", "out_of_scope", "nitpick", "blocker", "high", "medium", "edge",
                 "style"):
        assert word in prompt, word


def test_the_old_codex_loop_is_gone() -> None:
    prompt = _qa_prompt()
    for old in ("2–5", "2-5", "flip your verdict", "manual scan", "manual parse", "Skill tool", "Skill(codex)",
                "UNANIMOUS", "cleanliness/style violations", "Round 3 (skip", "Round 2 (skip"):
        assert old not in prompt, old


def test_failed_parse_is_a_degraded_consultation_like_quota_and_timeout() -> None:
    branch6 = next(line for line in _qa_prompt().splitlines() if line.startswith("6. Codex unavailable"))
    for status in ("failed_quota", "failed_timeout", "failed_parse"):
        assert status in branch6
    assert "CLOSE: YES - degraded codex consultation: codex_status=<value>" in branch6


def test_the_verdict_branch_that_agents_qa_cites_keeps_its_number_and_clauses() -> None:
    branch2 = next(line for line in _qa_prompt().splitlines() if line.startswith("2. AC-deviation PASS"))
    for clause in ("(a)", "(b)", "(c)", "(d)", "ac_deviation_with_user_need_satisfied: true"):
        assert clause in branch2, clause
