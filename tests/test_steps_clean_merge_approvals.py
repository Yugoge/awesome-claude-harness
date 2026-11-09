"""scripts/steps/clean-merge-approvals.py: /clean Step 16's merge of the approvals and the checkpoint into the
cleaner's context.

Every test runs the real script in a temp project (cwd), with no network and no dependence on the runner's
home. EXPECTED is the result of the `jq -s` expression the prompt used before the script existed, run over
the same two files: the script's output must equal it exactly, byte for byte (no jq needed at test time).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "steps" / "clean-merge-approvals.py"
COMMAND = REPO / "commands" / "clean.md"
RID = "clean-20261109-101010"

CONTEXT = {
    "request_id": RID,
    "timestamp": "2026-11-09T10:10:10Z",
    "orchestrator": {
        "requirement": "Inspect project for file organization issues and development standards violations",
        "analysis": {"project_root": "/proj", "project_type": "Python",
                     "constraints": ["preserve functional files"], "safety_checkpoint_created": False},
    },
    "full_context": {"file_counts": {"total": 3, "docs": 1, "scripts": 1, "tests": 1}},
    "parameters": {"docs_directory": "docs/"},
}
APPROVALS = {
    "request_id": RID,
    "mode": "execute_all",
    "user_approvals": {
        "total_issues_in_report": 2,
        "total_approved_actions": 2,
        "approved_actions": [
            {"action_id": "finding_1", "action": "move", "description": "usage-guide.md → docs/", "approved": True},
            {"action_id": "finding_2", "action": "delete", "description": "run-tests.sh.bak", "approved": True},
        ],
        "rejected_actions": [],
    },
}
# jq -s --arg commit abc123 '.[0] * {user_approvals: .[1].user_approvals}
#   * {orchestrator: {analysis: {safety_checkpoint_created: true, checkpoint_commit: $commit}}}' context approvals
EXPECTED = json.loads(json.dumps(CONTEXT))
EXPECTED["user_approvals"] = APPROVALS["user_approvals"]
EXPECTED["orchestrator"]["analysis"].update(safety_checkpoint_created=True, checkpoint_commit="abc123")


def project(tmp_path: Path, context=CONTEXT, approvals=APPROVALS) -> Path:
    clean = tmp_path / "docs" / "clean"
    clean.mkdir(parents=True)
    for name, body in ((f"context-{RID}.json", context), (f"user-approvals-{RID}.json", approvals)):
        if body is not None:
            (clean / name).write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return tmp_path


def run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True,
                          timeout=60)


def merged_path(cwd: Path) -> Path:
    return cwd / "docs" / "clean" / f"context-with-approvals-{RID}.json"


def test_merge_equals_the_jq_expression_it_replaces(tmp_path):
    done = run(project(tmp_path), RID, "abc123")

    assert done.returncode == 0, done.stderr
    assert done.stdout == f"context_with_approvals=docs/clean/context-with-approvals-{RID}.json\n"
    text = merged_path(tmp_path).read_text(encoding="utf-8")
    assert json.loads(text) == EXPECTED
    assert text == json.dumps(EXPECTED, indent=2, ensure_ascii=False) + "\n"  # jq's layout: 2 spaces, UTF-8 kept


def test_the_context_keys_survive_and_the_checkpoint_keys_overwrite(tmp_path):
    run(project(tmp_path), RID, "abc123")

    analysis = json.loads(merged_path(tmp_path).read_text(encoding="utf-8"))["orchestrator"]["analysis"]
    assert analysis["constraints"] == ["preserve functional files"] and analysis["project_root"] == "/proj"
    assert analysis["safety_checkpoint_created"] is True  # the context said False
    assert analysis["checkpoint_commit"] == "abc123"


def test_neither_input_file_is_changed(tmp_path):
    cwd = project(tmp_path)
    before = {p.name: p.read_bytes() for p in (cwd / "docs" / "clean").iterdir()}

    run(cwd, RID, "abc123")

    after = {p.name: p.read_bytes() for p in (cwd / "docs" / "clean").iterdir()}
    assert {k: v for k, v in after.items() if not k.startswith("context-with-approvals")} == before
    assert set(after) - set(before) == {merged_path(cwd).name}


def test_an_existing_merged_file_is_replaced(tmp_path):
    cwd = project(tmp_path)
    merged_path(cwd).write_text("stale", encoding="utf-8")

    assert run(cwd, RID, "abc123").returncode == 0
    assert json.loads(merged_path(cwd).read_text(encoding="utf-8")) == EXPECTED


def test_a_missing_input_stops_with_exit_1_and_writes_nothing(tmp_path):
    for missing in ("context", "approvals"):
        cwd = project(tmp_path / missing, context=None if missing == "context" else CONTEXT,
                      approvals=None if missing == "approvals" else APPROVALS)
        done = run(cwd, RID, "abc123")

        assert done.returncode == 1 and "cannot read" in done.stderr, (missing, done.stderr)
        assert not merged_path(cwd).exists()


def test_invalid_json_or_a_non_object_stops_with_exit_1(tmp_path):
    for n, (context, approvals, word) in enumerate([("{not json", APPROVALS, "not valid JSON"),
                                                    (CONTEXT, "[1, 2]", "not a JSON object")]):
        cwd = project(tmp_path / str(n), context=context, approvals=approvals)
        done = run(cwd, RID, "abc123")

        assert done.returncode == 1 and word in done.stderr, done.stderr
        assert not merged_path(cwd).exists()


def test_approvals_without_user_approvals_stop_with_exit_1(tmp_path):
    for n, approvals in enumerate([{"request_id": RID}, {"user_approvals": None}, {"user_approvals": ["x"]}]):
        cwd = project(tmp_path / str(n), approvals=approvals)
        done = run(cwd, RID, "abc123")

        assert done.returncode == 1 and "no user_approvals object" in done.stderr, done.stderr
        assert not merged_path(cwd).exists()


def test_wrong_argument_count_is_a_usage_error(tmp_path):
    cwd = project(tmp_path)
    for args in ((), (RID,), (RID, "abc123", "extra"), (RID, "")):
        done = run(cwd, *args)

        assert done.returncode == 2 and "usage" in done.stderr, args
    assert not merged_path(cwd).exists()


def test_clean_md_calls_the_script_with_the_arguments_it_takes():
    text = COMMAND.read_text(encoding="utf-8")
    call = next(line for line in text.splitlines() if "clean-merge-approvals.py" in line and line.startswith("python3"))

    assert call == 'python3 "<HARNESS_ROOT>/scripts/steps/clean-merge-approvals.py" {REQUEST_ID} <checkpoint_commit>'
