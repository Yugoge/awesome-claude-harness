"""Canonical test suite for scripts/dev-lifecycle.py (task 20260808-035658-lanel).

Covers the pure state-derivation/table logic against fixture docs/dev/
directory trees, entirely without slash-command invocation (QA is globally
denied Skill(close:*)/Skill(commit:*) -- see AC-L21). AC-specific assertions
live in tests/generated/20260808-035658-lanel/test_AC_L*.py; this file is the
broader/standalone suite named in the BA ticket's files_to_create list.
"""

from __future__ import annotations

import json
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
def test_derive_state_an_unfinished_chain_is_the_chain_s_own_failure(tmp_path, dev_status, qa_status):
    # The lifecycle derives no stage of its own: dev and QA status reach the
    # row only as the chain's errors, used verbatim.
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
    assert (row["state"], row["next_action"], row["blocker"]) == ("blocked", "inspect", "RESOLVER_FAIL")
    assert row["artifact_chain"] == _chain(project, task_id)
    assert row["artifact_chain"]["status"] == "fail"
    assert row["artifact_chain"]["errors"] != []


def test_derive_state_never_crashes_on_garbage(tmp_path):
    project = make_project(tmp_path)
    dd = dev_dir(project)
    task_id = "20260101-000005"
    write_text(dd / f"dev-report-{task_id}.json", "{not json")
    row = dlc.derive_state(project, task_id)
    assert row["state"] == "blocked"
    assert row["next_action"] == "inspect"


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


def test_scan_marks_lane_rows_non_actionable(tmp_path):
    project = make_project(tmp_path)
    dd = dev_dir(project)
    parent = "20260101-000008"
    write_text(dd / f"ticket-{parent}.md", f"Task-id: {parent}\n")
    write_json(dd / f"dev-report-{parent}.json",
               dev_report(parent, parallel_workers=["a", "b"]))
    for worker in ("a", "b"):
        lane_id = f"{parent}-{worker}"
        write_text(dd / f"ticket-{lane_id}.md", f"Task-id: {lane_id}\n")
        write_json(dd / f"dev-report-{lane_id}.json", dev_report(lane_id))
        write_json(dd / f"qa-report-{lane_id}.json", qa_report(lane_id))

    rows = dlc.scan(project)
    by_id = {r["task_id"]: r for r in rows}
    parent_row = by_id[parent]
    # The lanes are the ones the parent's chain lists; its state is the chain's.
    assert parent_row["artifact_chain"] == _chain(project, parent)
    assert parent_row["artifact_chain"]["mode"] == "fanout"
    assert [lane["task_id"] for lane in parent_row["lanes"]] == [f"{parent}-a", f"{parent}-b"]
    for worker in ("a", "b"):
        lane_row = by_id[f"{parent}-{worker}"]
        assert lane_row["kind"] == "lane"
        assert lane_row["next_action"] == "none"
        assert lane_row["parent_task_id"] == parent


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
