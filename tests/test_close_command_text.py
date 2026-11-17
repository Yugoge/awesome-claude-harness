"""commands/close.md as P4 decided it: one disposition call, in-turn questions, the native rating.

Each test hands the text to the code that consumes it (the obligation reader, the listing script,
the close-verdict classifier) and asserts on that code's answer, so the text and its consumer cannot
drift apart (P15 L7). Rules no code consumes live in the command itself and in its behavioural tests.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEXT = (REPO / "commands" / "close.md").read_text(encoding="utf-8")
TASK = "20260101-000000"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dev_lifecycle_fixtures import (  # noqa: E402
    ba_qa_report, completion_md, dev_dir, dev_report, make_project, qa_report, write_json, write_text,
    write_ticket_fixture,
)
from hooks.lib import obligation  # noqa: E402

_spec = importlib.util.spec_from_file_location("close_verdict_text_under_test", REPO / "hooks" / "lib" / "close-verdict.py")
close_verdict = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(close_verdict)
SCHEMA_IDS = frozenset(json.loads((REPO / "schemas" / "registry.json").read_text(encoding="utf-8"))["schemas"])


def _section(heading: str, text: str = TEXT) -> str:
    start = text.index(heading)
    nxt = text.find("\n## ", start + 1)
    sub = text.find("\n### ", start + 1)
    ends = [e for e in (nxt, sub) if e > 0]
    return text[start:min(ends)] if ends else text[start:]


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


def _do_route_dispatch(text: str) -> object:
    """What the hooks' obligation reader makes of the /do bullet's dispatch, its placeholders bound."""
    routes = _section("### Routes", text)
    [item] = [it for it in re.split(r"\n(?=- )", routes) if it.startswith("- A `/do` task")]
    block = re.search(r'`(<obligation v="1">\{.*?\}</obligation>)`', item).group(1)
    filled = re.sub(r'"<ISO-8601[^"]*>"', '"2026-01-01T00:00:00Z"', block.replace("<TASK_ID>", TASK))
    return obligation.parse_obligation(f"Complete the /do work.\n{filled}\n", known_schema_ids=SCHEMA_IDS)


def test_commit_routes_a_do_task_with_the_obligation_close_routes_it_with() -> None:
    """Q7 in /commit: the /do bullet of both commands' Routes gives a dispatch the obligation reader accepts,
    the same dev obligation for the same task, concluded by dev's own report."""
    commit = (REPO / "commands" / "commit.md").read_text(encoding="utf-8")
    close_read, commit_read = _do_route_dispatch(TEXT), _do_route_dispatch(commit)
    assert isinstance(close_read, obligation.ParsedObligation), close_read
    assert isinstance(commit_read, obligation.ParsedObligation), commit_read
    assert close_read.obligation == commit_read.obligation and close_read.undischarged == ()
    doc = close_read.obligation
    assert (doc["task_id"], doc["role"], doc["pipeline"], doc["profile"]) == (TASK, "dev", "do", "singular")
    assert [(a["path"], a["schema"]) for a in doc["artifacts"]] == [
        (f"docs/dev/dev-report-{TASK}.json", "dev-report.v2")]


def test_which_task_runs_the_listing_it_names_and_offers_the_task_it_skips(tmp_path: Path) -> None:
    """**Which task?**: the listing call as close.md spells it, run from the harness home, prints the
    closeable task on stdout and the skipped task (a gap no dispatch owes) on stderr in the form the
    paragraph names, which is where the question's candidates come from."""
    para = next(p for p in TEXT.split("\n\n") if p.startswith("**Which task?**"))
    [call] = [c for c in re.findall(r"`([^`]+)`", para) if "dev-lifecycle.py" in c]
    [form] = [c for c in re.findall(r"`([^`]+)`", para) if "skipped" in c]
    project = make_project(tmp_path)
    old, passing = "20250101-000001", "20260101-000010"
    write_json(dev_dir(project) / f"dev-report-{old}.json", dev_report(old))
    write_ticket_fixture(project, passing)
    write_json(dev_dir(project) / f"ba-qa-report-{passing}.json", ba_qa_report(passing, top_verdict="pass"))
    write_json(dev_dir(project) / f"dev-report-{passing}.json", dev_report(passing))
    write_json(dev_dir(project) / f"qa-report-{passing}.json", qa_report(passing))
    write_text(dev_dir(project) / f"completion-{passing}.md", completion_md(passing))
    done = subprocess.run(["bash", "-c", call.replace("<PROJECT_ROOT>", str(project))], capture_output=True,
                          text=True, timeout=120, env={**os.environ, "CLAUDE_HOME": str(REPO)})
    assert done.returncode == 0, done.stderr
    assert [line.split(" ", 1)[0] for line in done.stdout.splitlines()] == [passing]
    shape = re.escape(form).replace(re.escape("<task-id>"), r"(\S+)").replace(re.escape("<reason>"), r"(.+)")
    [skipped] = done.stderr.splitlines()
    matched = re.fullmatch(shape, skipped)
    assert matched and matched.group(1) == old, skipped


def _qa_prompt() -> str:
    step2 = _section("### Step 2:")
    return re.search(r"```\n(FIRST ACTION:.*?)\n```", step2, re.S).group(1)


def test_a_degraded_codex_consultation_lands_the_close_for_each_failed_status() -> None:
    """QA's branch 6: each `codex_status` it names gives a verdict line the close-verdict classifier (the one
    every close-report reader applies) reads as a landed close."""
    branch6 = next(line for line in _qa_prompt().splitlines() if line.startswith("6. Codex unavailable"))
    statuses = re.findall(r"`(failed_\w+)`", branch6)
    [verdict] = [c for c in re.findall(r"`([^`]+)`", branch6) if c.startswith("CLOSE:")]
    assert len(statuses) == 3, branch6
    for status in statuses:
        assert close_verdict.classify_line(verdict.replace("<value>", status)) == "yes", (verdict, status)
