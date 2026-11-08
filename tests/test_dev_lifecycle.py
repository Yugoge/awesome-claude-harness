"""Canonical test suite for scripts/dev-lifecycle.py (task 20260808-035658-lanel).

Covers the pure state-derivation/table logic against fixture docs/dev/
directory trees, entirely without slash-command invocation (QA is globally
denied Skill(close:*)/Skill(commit:*) -- see AC-L21). AC-specific assertions
live in tests/generated/20260808-035658-lanel/test_AC_L*.py; this file is the
broader/standalone suite named in the BA ticket's files_to_create list.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _dev_lifecycle_fixtures import (  # noqa: E402
    REPO_ROOT,
    close_report_text,
    completion_md,
    dev_dir,
    dev_report,
    dlc,
    do_report,
    git_commit_all,
    init_git_repo,
    make_project,
    qa_report,
    ticket_md,
    write_json,
    write_text,
    write_ticket_fixture,
)


def _chain(project, task_id):
    """The chain function's own result, called directly."""
    return dlc._load_resolver_module().resolve_chain(project, task_id)


def _passing_singular(project, task_id):
    write_ticket_fixture(project, task_id)
    write_json(dev_dir(project) / f"dev-report-{task_id}.json", dev_report(task_id))
    write_json(dev_dir(project) / f"qa-report-{task_id}.json", qa_report(task_id))
    write_text(dev_dir(project) / f"completion-{task_id}.md", completion_md(task_id))


# --------------------------------------------------------------------------
# ba_qa_verdict / do_report_lite_preflight -- pure dict predicates
# --------------------------------------------------------------------------


def test_ba_qa_verdict_prefers_top_level():
    assert dlc.ba_qa_verdict({"verdict": "pass", "qa": {"status": "fail"}}) == "pass"


def test_ba_qa_verdict_falls_back_to_nested():
    assert dlc.ba_qa_verdict({"qa": {"status": "fail"}}) == "fail"


def test_ba_qa_verdict_none_when_neither_present():
    assert dlc.ba_qa_verdict({}) is None


def test_do_report_lite_preflight_valid():
    assert dlc.do_report_lite_preflight(do_report("t1")) is None


@pytest.mark.parametrize(
    "doc,expected_field",
    [
        ({"source": "not-do", "do": {"status": "completed", "files_modified": []}}, "source"),
        ({"source": "do", "do": "not-a-dict"}, "do"),
        ({"source": "do", "do": {"status": "in_progress", "files_modified": []}}, "do.status"),
        # Terminal but not done, and the status no schema declares any more (E8):
        # only "completed" lets the do track treat the work as done.
        ({"source": "do", "do": {"status": "blocked", "files_modified": []}}, "do.status"),
        ({"source": "do", "do": {"status": "pending", "files_modified": []}}, "do.status"),
        ({"source": "do", "do": {"status": "completed", "files_modified": "not-a-list"}}, "do.files_modified"),
    ],
)
def test_do_report_lite_preflight_rejects_malformed(doc, expected_field):
    assert dlc.do_report_lite_preflight(doc) == expected_field


# --------------------------------------------------------------------------
# classify_walk_outcome (AC-L18 / AC-L19)
# --------------------------------------------------------------------------


def test_classify_walk_outcome_hook_deny():
    text = "PreToolUse:pretool-tool-policy.py hook error: BLOCKED by tool-policy.v1: ..."
    assert dlc.classify_walk_outcome(text) == "hook_deny"


def test_classify_walk_outcome_success_close():
    assert dlc.classify_walk_outcome("...\nCLOSE: YES\n") == "success"


def test_classify_walk_outcome_reads_the_close_verdict_of_the_last_line_only():
    # A round-open last line is not landed, whatever an earlier line quotes.
    assert dlc.classify_walk_outcome("CLOSE: YES (prior attempt)\nCLOSE_FINDINGS: 2 items\n") == "ordinary_reject"


def test_classify_walk_outcome_success_commit():
    assert dlc.classify_walk_outcome("...\nCOMMIT: APPROVE\n") == "success"


def test_classify_walk_outcome_ordinary_reject_default():
    assert dlc.classify_walk_outcome("resolver exit 2: status=fail") == "ordinary_reject"


def test_classify_walk_outcome_partial_abort_overrides():
    assert (
        dlc.classify_walk_outcome("CLOSE: YES", partial_multi_repo_commit=True)
        == "partial_abort"
    )


# --------------------------------------------------------------------------
# validate_auto_flag_combination (Must-Have #8)
# --------------------------------------------------------------------------


def test_auto_flag_combination_clean():
    assert dlc.validate_auto_flag_combination(True, None, False, False) is None


def test_auto_flag_combination_rejects_explicit_task_id():
    assert dlc.validate_auto_flag_combination(True, "20260101-000000", False, False) is not None


def test_auto_flag_combination_rejects_force():
    assert dlc.validate_auto_flag_combination(True, None, True, False) is not None


def test_auto_flag_combination_rejects_bulk():
    assert dlc.validate_auto_flag_combination(True, None, False, True) is not None


def test_auto_flag_combination_noop_when_not_auto():
    assert dlc.validate_auto_flag_combination(False, "x", True, True) is None


# --------------------------------------------------------------------------
# render_table
# --------------------------------------------------------------------------


def test_render_table_includes_header_and_rows():
    rows = [
        {"task_id": "t1", "kind": "ticket", "state": "close_pending", "next_action": "close",
         "parent_task_id": None, "parent_spec_id": None},
    ]
    table = dlc.render_table(rows)
    assert "task_id" in table
    assert "t1" in table
    assert "close_pending" in table


# --------------------------------------------------------------------------
# derive_state integration smoke tests (a few key paths)
# --------------------------------------------------------------------------


def test_derive_state_analyzed_when_nothing_exists(tmp_path):
    project = make_project(tmp_path)
    row = dlc.derive_state(project, "20260101-000001")
    assert row["state"] == "analyzed"
    assert row["next_action"] == "develop"


def test_derive_state_a_passing_chain_is_close_pending_with_the_chain_verbatim(tmp_path):
    project = make_project(tmp_path)
    task_id = "20260101-000002"
    _passing_singular(project, task_id)
    row = dlc.derive_state(project, task_id)
    assert (row["state"], row["next_action"], row["invoke_resolver"]) == ("close_pending", "close", True)
    assert row["artifact_chain"] == _chain(project, task_id)
    assert row["artifact_chain"]["status"] == "pass"


@pytest.mark.parametrize(
    "dev_status,qa_status",
    [("blocked", "pass"), ("completed", None), ("completed", "fail")],
    ids=["dev-blocked", "qa-missing", "qa-fail"],
)
def test_derive_state_an_unfinished_chain_is_close_pending_with_the_chain_verbatim(tmp_path, dev_status, qa_status):
    # The lifecycle derives no stage of its own: dev and QA status reach the
    # row only as the chain's errors, used verbatim; /close completes the cycle (D7).
    project = make_project(tmp_path)
    task_id = "20260101-000003"
    _passing_singular(project, task_id)
    write_json(dev_dir(project) / f"dev-report-{task_id}.json", dev_report(task_id, status=dev_status))
    qa_path = dev_dir(project) / f"qa-report-{task_id}.json"
    if qa_status is None:
        qa_path.unlink()
    else:
        write_json(qa_path, qa_report(task_id, status=qa_status))
    row = dlc.derive_state(project, task_id)
    assert (row["state"], row["next_action"]) == ("close_pending", "close") and "blocker" not in row
    assert row["artifact_chain"] == _chain(project, task_id)
    assert row["artifact_chain"]["status"] == "fail"
    assert row["artifact_chain"]["errors"] != []


def test_derive_state_never_crashes_on_garbage(tmp_path):
    project = make_project(tmp_path)
    dd = dev_dir(project)
    task_id = "20260101-000005"
    write_text(dd / f"dev-report-{task_id}.json", "{not json")
    row = dlc.derive_state(project, task_id)
    # The disposition takes a malformed dev-report as a gap dev repairs: /close completes it.
    assert (row["state"], row["next_action"]) == ("close_pending", "close")
    assert "MALFORMED_JSON" in {error["code"] for error in row["artifact_chain"]["errors"]}


def test_an_instrument_failure_of_the_chain_stays_blocked(tmp_path, monkeypatch):
    # The disposition's dev-chain check raises on it (a failing aggregator): no close for it.
    project = make_project(tmp_path)
    task_id = "20260101-000004"
    _passing_singular(project, task_id)

    def unimportable():
        raise ImportError("aggregator unimportable")

    monkeypatch.setattr(dlc._load_resolver_module(), "_load_aggregate_module", unimportable)
    row = dlc.derive_state(project, task_id)
    assert (row["state"], row["next_action"]) == ("blocked", "inspect")
    assert "AGGREGATE_IMPLEMENTATION_ERROR" in row["blocker"]
    assert dlc.actionable_parents(dlc.scan(project), "close") == []


@pytest.mark.parametrize(("name", "text", "blocker"), [
    ("ba-qa-report", "{not json", "MALFORMED_BA_QA_REPORT"),
    ("do-report", "{not json", "MALFORMED_DO_REPORT"),
    ("do-report", '{"source": "spec"}', "MALFORMED_DO_REPORT_FIELD:source"),
])
def test_a_malformed_record_the_scan_reads_itself_stays_blocked(tmp_path, name, text, blocker):
    project = make_project(tmp_path)
    task_id = "20260101-000013"
    write_text(dev_dir(project) / f"{name}-{task_id}.json", text)
    row = dlc.derive_state(project, task_id)
    assert (row["state"], row["next_action"], row["blocker"]) == ("blocked", "inspect", blocker)


def test_derive_state_close_failed_on_no_verdict(tmp_path):
    project = make_project(tmp_path)
    dd = dev_dir(project)
    task_id = "20260101-000006"
    write_json(dd / f"dev-report-{task_id}.json", dev_report(task_id))
    write_json(dd / f"qa-report-{task_id}.json", qa_report(task_id))
    write_text(dd / f"close-report-{task_id}.md", close_report_text(task_id, "CLOSE: NO - dissent"))
    row = dlc.derive_state(project, task_id)
    assert row["state"] == "close_failed"
    assert row["next_action"] == "resume_close"


def test_derive_state_committed_end_to_end(tmp_path):
    project = make_project(tmp_path)
    init_git_repo(project)
    (project / "owned.txt").write_text("hello\n", encoding="utf-8")
    dd = dev_dir(project)
    task_id = "20260101-000007"
    write_json(dd / f"dev-report-{task_id}.json", dev_report(task_id, files_modified=["owned.txt"]))
    write_json(dd / f"qa-report-{task_id}.json", qa_report(task_id))
    write_text(dd / f"close-report-{task_id}.md", close_report_text(task_id, "CLOSE: YES"))
    git_commit_all(project, f"chore: cycle\n\nTask-id: {task_id}\n")

    row = dlc.derive_state(project, task_id)
    assert row["state"] == "committed"
    assert row["next_action"] == "none"


def test_derive_state_an_uncommitted_closed_task_is_commit_pending(tmp_path):
    # After /close and before /commit the task's owned file is dirty and no commit carries its
    # trailer: /commit --auto must find it (commit_pending), not report a partial commit.
    project = make_project(tmp_path)
    init_git_repo(project)
    (project / "owned.txt").write_text("hello\n", encoding="utf-8")
    git_commit_all(project, "chore: before the cycle\n")
    (project / "owned.txt").write_text("hello, cycle\n", encoding="utf-8")
    task_id = "20260101-000014"
    write_json(dev_dir(project) / f"dev-report-{task_id}.json", dev_report(task_id, files_modified=["owned.txt"]))
    write_text(dev_dir(project) / f"close-report-{task_id}.md", close_report_text(task_id, "CLOSE: YES"))
    row = dlc.derive_state(project, task_id)
    assert (row["state"], row["next_action"]) == ("commit_pending", "commit")
    assert _list_actionable(project, "commit") == [task_id]


def test_derive_state_a_trailer_with_dirty_owned_content_is_a_partial_commit(tmp_path):
    project = make_project(tmp_path)
    init_git_repo(project)
    (project / "owned.txt").write_text("hello\n", encoding="utf-8")
    task_id = "20260101-000015"
    write_json(dev_dir(project) / f"dev-report-{task_id}.json", dev_report(task_id, files_modified=["owned.txt"]))
    write_text(dev_dir(project) / f"close-report-{task_id}.md", close_report_text(task_id, "CLOSE: YES"))
    git_commit_all(project, f"chore: cycle\n\nTask-id: {task_id}\n")
    (project / "owned.txt").write_text("hello, after the commit\n", encoding="utf-8")
    row = dlc.derive_state(project, task_id)
    assert (row["state"], row["next_action"], row["blocker"]) == ("blocked", "inspect", "PARTIAL_COMMIT")


def _fanout(project, parent):
    dd = dev_dir(project)
    write_text(dd / f"ticket-{parent}.md", f"Task-id: {parent}\n")
    write_json(dd / f"dev-report-{parent}.json",
               dev_report(parent, parallel_workers=["a", "b"]))
    for worker in ("a", "b"):
        lane_id = f"{parent}-{worker}"
        write_text(dd / f"ticket-{lane_id}.md", f"Task-id: {lane_id}\n")
        write_json(dd / f"dev-report-{lane_id}.json", dev_report(lane_id))
        write_json(dd / f"qa-report-{lane_id}.json", qa_report(lane_id))


def test_scan_marks_lane_rows_non_actionable(tmp_path):
    project = make_project(tmp_path)
    parent = "20260101-000008"
    _fanout(project, parent)
    rows = dlc.scan(project)
    by_id = {r["task_id"]: r for r in rows}
    parent_row = by_id[parent]
    # The lanes are the ones the parent's chain lists.
    assert parent_row["artifact_chain"] == _chain(project, parent)
    assert parent_row["artifact_chain"]["mode"] == "fanout"
    assert [lane["task_id"] for lane in parent_row["lanes"]] == [f"{parent}-a", f"{parent}-b"]
    for worker in ("a", "b"):
        lane_row = by_id[f"{parent}-{worker}"]
        assert lane_row["kind"] == "lane"
        assert lane_row["next_action"] == "none"
        assert lane_row["parent_task_id"] == parent


def test_a_fanout_whose_lane_qa_never_ran_is_close_actionable(tmp_path):
    # D7: /close completes the cycle, its disposition naming the lane's qa-report as a gap, so the
    # --auto discovery offers the parent (never its lanes), as /close <task> completes it.
    project = make_project(tmp_path)
    parent = "20260101-000009"
    _fanout(project, parent)
    (dev_dir(project) / f"qa-report-{parent}-b.json").unlink()
    row = {r["task_id"]: r for r in dlc.scan(project)}[parent]
    assert (row["state"], row["next_action"]) == ("close_pending", "close")
    assert ("MISSING_ARTIFACT", f"docs/dev/qa-report-{parent}-b.json") in {
        (error["code"], error["path"]) for error in row["artifact_chain"]["errors"]}
    assert [line.split(" ", 1)[0] for line in _list_actionable(project, "close")] == [parent]


def test_actionable_parents_excludes_lanes_and_specs():
    rows = [
        {"task_id": "p1", "kind": "ticket", "next_action": "close"},
        {"task_id": "p1-a", "kind": "lane", "next_action": "none"},
        {"task_id": None, "kind": "spec", "next_action": None},
        {"task_id": "p2", "kind": "ticket", "next_action": "commit"},
    ]
    assert dlc.actionable_parents(rows, "close") == ["p1"]
    assert dlc.actionable_parents(rows, "commit") == ["p2"]


# --------------------------------------------------------------------------
# list-actionable: the --auto discovery and the walked task's step share one
# chain call (the step takes the discovery's result)
# --------------------------------------------------------------------------


def _list_actionable(project, next_action):
    done = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "dev-lifecycle.py"), "list-actionable",
         "--next-action", next_action, "--project-dir", str(project)],
        capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.splitlines()


def test_list_actionable_close_hands_each_dev_parent_its_chain_result(tmp_path):
    project = make_project(tmp_path)
    task_id = "20260101-000011"
    _passing_singular(project, task_id)
    write_json(dev_dir(project) / "do-report-20260101-000012.json", do_report("20260101-000012"))
    lines = _list_actionable(project, "close")
    assert [line.split(" ", 1)[0] for line in lines] == [task_id, "20260101-000012"]
    head, chain = lines[0].split(" ", 1)
    resolver_cli = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "resolve-dev-artifact-chain.py"),
         "--task-id", task_id, "--project-dir", str(project)],
        capture_output=True, text=True, timeout=120,
    )
    assert chain == resolver_cli.stdout.strip()
    assert json.loads(chain)["status"] == "pass"
    assert lines[1] == "20260101-000012"  # a /do parent: no chain


@pytest.mark.parametrize("with_dev", [False, True], ids=["no-dev-report", "dev-report"])
def test_a_blocked_do_task_is_close_actionable_with_or_without_dev_s_report(tmp_path, with_dev):
    # Q7: /close routes the do-report to dev, whose report concludes the task (the disposition's /do
    # branch); neither row is blocked, nor run through the /dev chain, so /close --auto offers it.
    project = make_project(tmp_path)
    task_id = "20260101-000014"
    write_json(dev_dir(project) / f"do-report-{task_id}.json", do_report(task_id, status="blocked"))
    if with_dev:
        write_json(dev_dir(project) / f"dev-report-{task_id}.json", dev_report(task_id))
    row = dlc.derive_state(project, task_id)
    assert (row["state"], row["next_action"], row["invoke_resolver"]) == ("close_pending", "close", False)
    assert "blocker" not in row and "artifact_chain" not in row
    assert _list_actionable(project, "close") == [task_id]


def test_list_actionable_commit_selects_without_the_chain(tmp_path):
    project = make_project(tmp_path)
    init_git_repo(project)
    (project / "owned.txt").write_text("hello\n", encoding="utf-8")
    task_id = "20260101-000013"
    write_json(dev_dir(project) / f"dev-report-{task_id}.json", dev_report(task_id, files_modified=["owned.txt"]))
    write_text(dev_dir(project) / f"close-report-{task_id}.md", close_report_text(task_id, "CLOSE: YES"))
    git_commit_all(project, "chore: unrelated work, no task trailer\n")
    row = dlc.derive_state(project, task_id)
    assert (row["state"], row["next_action"]) == ("commit_pending", "commit")
    assert row["invoke_resolver"] is False
    assert "artifact_chain" not in row
    assert _list_actionable(project, "commit") == [task_id]


def _private_index_commit(project, paths, message):
    """A commit through a session-private index, as /commit's changelog-analyst makes it:
    the shared index stays behind HEAD."""
    env = dict(os.environ, GIT_INDEX_FILE=str(project / ".git" / "session.index"))
    for args in (["read-tree", "HEAD"], ["add", "--", *paths], ["commit", "-q", "-m", message]):
        subprocess.run(["git", *args], cwd=project, env=env, check=True, capture_output=True)


@pytest.mark.parametrize("landed, expected", [
    (None, ("commit_pending", "commit", None)),  # closed, not committed: its owned paths dirty
    ("all", ("committed", "none", None)),  # committed through a private index
    ("docs", ("blocked", "inspect", "PARTIAL_COMMIT")),  # a Task-id commit, the product edit left out
], ids=["closed-uncommitted", "private-index-commit", "partial-commit"])
def test_commit_detection_of_a_closed_task(tmp_path, landed, expected):
    project = make_project(tmp_path)
    init_git_repo(project)
    (project / "owned.txt").write_text("v1\n", encoding="utf-8")
    git_commit_all(project, "base\n")
    (project / "owned.txt").write_text("v2\n", encoding="utf-8")
    task_id = "20260101-000014"
    docs = [f"docs/dev/dev-report-{task_id}.json", f"docs/dev/close-report-{task_id}.md"]
    write_json(project / docs[0], dev_report(task_id, files_modified=["owned.txt"], files_created=docs))
    write_text(project / docs[1], close_report_text(task_id, "CLOSE: YES"))
    if landed:
        paths = docs + (["owned.txt"] if landed == "all" else [])
        _private_index_commit(project, paths, f"feat: cycle\n\nTask-id: {task_id}\n")
    row = dlc.derive_state(project, task_id)
    assert (row["state"], row["next_action"], row.get("blocker")) == expected
    assert _list_actionable(project, "commit") == ([task_id] if landed is None else [])


# --------------------------------------------------------------------------
# Records older code wrote still load: the chain fails on them (strict pass),
# and neither CLI entry point crashes on them.
# --------------------------------------------------------------------------


def _legacy_records(project):
    """A canonical aggregate older code wrote as `blocked` on a shard mismatch,
    and a singular dev-report older code left as `needs_review` with a
    status_rationale; returns their task-ids."""
    dd = dev_dir(project)
    fanout = "20260101-000021"
    write_text(dd / f"ticket-{fanout}.md", ticket_md(fanout))
    for worker, sha in (("a", "1" * 40), ("b", "2" * 40)):
        lane = f"{fanout}-{worker}"
        write_ticket_fixture(project, lane)
        write_json(dd / f"dev-report-{lane}.json", dev_report(lane, baseline_head_sha=sha))
        write_json(dd / f"qa-report-{lane}.json", qa_report(lane))
    canonical = dev_report(fanout, parallel_workers=["a", "b"], baseline_head_sha="1" * 40)
    canonical["dev"]["status"] = "blocked"
    canonical["blocking_issues"] = ["shard 'b': baseline_head_sha differs from shard 'a'"]
    write_json(dd / f"dev-report-{fanout}.json", canonical)

    singular = "20260101-000022"
    _passing_singular(project, singular)
    report = dev_report(singular, status="needs_review")
    report["dev"]["status_rationale"] = {
        "classification": "other_disclosed_handoff",
        "blocked_by": "a lane could not finish",
        "forbidden_action": "see the lane dev-report",
    }
    write_json(dd / f"dev-report-{singular}.json", report)
    return fanout, singular


def test_scan_and_list_actionable_load_legacy_blocked_and_needs_review_records(tmp_path):
    project = make_project(tmp_path)
    fanout, singular = _legacy_records(project)
    passing = "20260101-000023"
    _passing_singular(project, passing)
    script = str(REPO_ROOT / "scripts" / "dev-lifecycle.py")

    for argv in (["scan", "--project-dir", str(project)],
                 ["scan", "--format", "json", "--project-dir", str(project)],
                 ["list-actionable", "--next-action", "close", "--project-dir", str(project)]):
        done = subprocess.run([sys.executable, script, *argv], capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, done.stderr
        assert "Traceback" not in done.stderr

    rows = {row["task_id"]: row for row in dlc.scan(project)}
    for task_id in (fanout, singular):  # unfinished cycles /close completes (D7)
        row = rows[task_id]
        assert (row["state"], row["next_action"]) == ("close_pending", "close") and "blocker" not in row
        assert row["artifact_chain"]["status"] == "fail"
    assert [line.split(" ", 1)[0] for line in _list_actionable(project, "close")] == [fanout, singular, passing]


# --------------------------------------------------------------------------
# /dev-overnight: each pipeline whose QA passed is a /dev chain under its own
# task id; /close --auto's discovery lists it through the completion report the
# overnight's Step 16 has the main agent write (P2 acceptance 12)
# --------------------------------------------------------------------------


def _overnight_completion_template() -> tuple[str, str]:
    """The path and the markdown template commands/dev-overnight.md's Step 16 gives the main agent
    for a pipeline whose QA passed, read from the tree's text."""
    text = (REPO_ROOT / "commands" / "dev-overnight.md").read_text(encoding="utf-8")
    step = re.search(r"^### Step 16:.*?(?=^### )", text, re.M | re.S)
    assert step, "commands/dev-overnight.md has no Step 16"
    body = step.group(0)
    path = re.search(r"Write `([^`\s]*completion-[^`\s]*\.md)`", body)
    template = re.search(r"^```markdown\n(# Development Completion Report.*?)^```", body, re.M | re.S)
    assert path and template, "Step 16 gives no completion report for a pipeline whose QA passed"
    return path.group(1), template.group(1)


def test_list_actionable_close_lists_each_completed_overnight_pipeline(tmp_path):
    project = make_project(tmp_path)
    path_tpl, template = _overnight_completion_template()
    pipelines = [{"index": i, "timestamp_suffix": f"20260101-000021-{i}", "description": f"issue {i}"}
                 for i in (0, 1)]
    for p in pipelines:  # what the pipeline's BA, dev and QA dispatches wrote (QA passed)
        task_id = p["timestamp_suffix"]
        write_ticket_fixture(project, task_id)
        write_json(dev_dir(project) / f"dev-report-{task_id}.json", dev_report(task_id))
        write_json(dev_dir(project) / f"qa-report-{task_id}.json", qa_report(task_id))

    def fill(text, p):
        text = re.sub(r"\{pipeline\.(\w+)\}", lambda m: str(p[m.group(1)]), text)
        return (text.replace("<ISO-8601>", "2026-01-01T00:00:21Z").replace("<session_id>", "s-night")
                .replace("<N>", "1"))
    # No completion report yet: each chain fails on that one gap, and /close completes
    # an unfinished chain (D7), so each pipeline is already listed with its chain failing.
    before = _list_actionable(project, "close")
    assert [line.split(" ", 1)[0] for line in before] == [p["timestamp_suffix"] for p in pipelines]
    for line, p in zip(before, pipelines):
        chain = json.loads(line.split(" ", 1)[1])
        assert (chain["status"], chain["stage_gaps"]) == ("fail", [fill(path_tpl, p)])
    for p in pipelines:  # Step 16, as the main agent writes it
        write_text(project / fill(path_tpl, p), fill(template, p))
    lines = _list_actionable(project, "close")
    assert [line.split(" ", 1)[0] for line in lines] == [p["timestamp_suffix"] for p in pipelines]
    assert all(json.loads(line.split(" ", 1)[1])["status"] == "pass" for line in lines)
