"""Tests for hooks/lib/obligation.py declaring_dispatch (P1b E3): the one reader
of who owes an artifact of a task, from the task's dispatch records in every
session the project's transcript store holds, else the canonical todo step of
a command the task ran, else (a product file) the dispatch whose own tool
calls wrote it. The store is a throwaway account root; the command files and
canonical todo scripts are the tree's own, read at run time."""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from hooks.lib import obligation  # noqa: E402
from hooks.lib.subagent_restart import project_slug  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK = "20261028-120000"


def _obligation(task_id, role, artifacts, lane=None, lane_set=None, profile="singular",
                pipeline="dev", at="2026-10-28T12:00:00Z"):
    return {"task_id": task_id, "lane": lane, "lane_set": lane_set, "role": role,
            "pipeline": pipeline, "profile": "fanout-lane" if lane else profile,
            "dispatched_at": at, "artifacts": artifacts}


def _json(path, schema):
    return {"kind": "json", "path": path, "schema": schema, "identity": {"task_id": TASK}}


def _dispatch(use_id, subagent_type, doc):
    prompt = "FIRST ACTION: register.\n" + obligation.serialize_obligation(doc) + "\nDo the work."
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": use_id, "name": "Agent",
         "input": {"subagent_type": subagent_type, "prompt": prompt}}]}}


def _typed(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


class Store:
    """One account root holding the project's session transcripts."""

    def __init__(self, tmp_path):
        self.project = tmp_path / "proj"
        self.project.mkdir()
        self.root = tmp_path / "projects"
        self.slug_dir = self.root / project_slug(self.project)
        self.slug_dir.mkdir(parents=True)

    def session(self, sid, records):
        path = self.slug_dir / f"{sid}.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        return path

    def agent(self, sid, agent_id, use_id, records):
        sub = self.slug_dir / sid / "subagents"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / f"agent-{agent_id}.meta.json").write_text(json.dumps({"toolUseId": use_id}), encoding="utf-8")
        (sub / f"agent-{agent_id}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")

    def ask(self, path, task=TASK):
        return obligation.declaring_dispatch(task, path, self.project, roots=[self.root])


def _fanout_dev_session(store, sid="s-dev", qa_lanes=("l1", "l2")):
    lanes = ["l1", "l2"]
    records = [_typed("/dev build the thing")]
    for lane in lanes:
        lid = f"{TASK}-{lane}"
        records.append(_dispatch(f"toolu_ba_{lane}", "ba", _obligation(lid, "ba", [
            _json(f"docs/dev/context-{lid}.json", "context.v1"),
            {"kind": "markdown", "path": f"docs/dev/ticket-{lid}.md", "identity_anchor": lid}],
            lane=lane, lane_set=lanes)))
        records.append(_dispatch(f"toolu_dev_{lane}", "dev", _obligation(lid, "dev", [
            _json(f"docs/dev/dev-report-{lid}.json", "dev-report.v2")], lane=lane, lane_set=lanes)))
    for lane in qa_lanes:
        lid = f"{TASK}-{lane}"
        records.append(_dispatch(f"toolu_qa_{lane}", "qa", _obligation(lid, "qa", [
            _json(f"docs/dev/qa-report-{lid}.json", "qa-report.v2")], lane=lane, lane_set=lanes,
            profile="final_verification")))
    return store.session(sid, records)


def test_a_dispatch_of_an_earlier_session_is_found_from_a_later_one(tmp_path):
    store = Store(tmp_path)
    _fanout_dev_session(store)
    store.session("s-close", [_typed(f"/close {TASK}")])

    answer = store.ask(f"docs/dev/qa-report-{TASK}-l2.json")

    assert answer["source"] == "dispatch"
    assert (answer["role"], answer["subagent_type"], answer["lane"], answer["task_id"]) == (
        "qa", "qa", "l2", f"{TASK}-l2")
    assert answer["session_id"] == "s-dev" and answer["tool_use_id"] == "toolu_qa_l2"
    assert "<obligation" in answer["prompt"]
    # An absolute path inside the project is the same artifact.
    assert store.ask(str(store.project / f"docs/dev/ticket-{TASK}-l1.md"))["tool_use_id"] == "toolu_ba_l1"


def test_the_latest_dispatch_declaring_a_path_wins(tmp_path):
    store = Store(tmp_path)
    path = f"docs/dev/dev-report-{TASK}.json"
    store.session("s-dev", [
        _typed("/dev build it"),
        _dispatch("toolu_first", "dev", _obligation(TASK, "dev", [_json(path, "dev-report.v2")])),
        _dispatch("toolu_again", "dev", _obligation(TASK, "dev", [_json(path, "dev-report.v2")],
                                                    at="2026-10-28T12:30:00Z")),
    ])
    assert store.ask(path)["tool_use_id"] == "toolu_again"


def test_another_task_s_dispatch_is_not_the_owner(tmp_path):
    store = Store(tmp_path)
    other = "20261028-130000"
    path = f"docs/dev/qa-report-{other}.json"
    store.session("s-other", [
        _typed("/dev other"),
        _dispatch("toolu_x", "qa", _obligation(other, "qa", [_json(path, "qa-report.v2")])),
    ])
    assert store.ask(path, task=other)["tool_use_id"] == "toolu_x"
    assert store.ask(path) is None


def test_a_lane_qa_never_dispatched_names_the_canonical_todo_step(tmp_path):
    store = Store(tmp_path)
    _fanout_dev_session(store, qa_lanes=("l1",))

    answer = store.ask(f"docs/dev/qa-report-{TASK}-l2.json")

    assert answer["source"] == "todo_step"
    assert answer["command"] == "dev"
    assert answer["step"].startswith("Step 13:")
    assert answer["subagent_call"]["subagent_type"] == "qa"
    template = answer["template"]
    assert (template["role"], template["pipeline"]) == ("qa", "dev")
    assert template["artifacts"][0]["path"] == f"docs/dev/qa-report-{TASK}-l2.json"


def test_a_test_writer_artifact_takes_its_template_s_role_not_its_step_s(tmp_path):
    """The test-writer template sits under /dev Step 10, whose entry names dev:
    the step keeps what its entry names and the answer carries the template."""
    store = Store(tmp_path)
    _fanout_dev_session(store)
    answer = store.ask(f"docs/dev/test-writer-report-{TASK}-l1.json")
    assert answer["source"] == "todo_step" and answer["step"].startswith("Step 10:")
    assert answer["subagent_call"]["subagent_type"] == "dev"
    assert answer["template"]["role"] == "test-writer"


def test_close_late_repair_step_0_owns_finalize_s_effective_report(tmp_path):
    store = Store(tmp_path)
    store.session("s-close", [
        _typed(f"/close --late-repair {TASK}"),
        _dispatch("toolu_ba", "ba", _obligation(TASK, "ba", [_json(f"docs/dev/context-{TASK}.json", "context.v1")])),
    ])
    answer = store.ask(f"docs/dev/dev-report-{TASK}.effective.json")
    assert answer["source"] == "todo_step"
    assert (answer["command"], answer["arguments"]) == ("close", f"--late-repair {TASK}")
    assert answer["step"].startswith("Step 0:")
    assert answer["subagent_call"] is None and answer["template"] is None


def test_a_product_file_goes_to_the_dispatch_whose_tool_calls_wrote_it(tmp_path):
    store = Store(tmp_path)
    _fanout_dev_session(store)
    write = {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "w1", "name": "Write",
         "input": {"file_path": str(store.project / "src/app.py"), "content": "x = 1\n"}}]}}
    ok = {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "w1", "content": "written"}]}}
    store.agent("s-dev", "a-dev-l2", "toolu_dev_l2", [write, ok])

    answer = store.ask("src/app.py")
    assert answer["source"] == "writer"
    assert (answer["tool_use_id"], answer["lane"]) == ("toolu_dev_l2", "l2")
    # A product file no dispatch of the task wrote has no owner.
    assert store.ask("src/other.py") is None


def test_a_transcript_that_never_names_the_task_is_not_parsed(tmp_path, monkeypatch):
    store = Store(tmp_path)
    _fanout_dev_session(store)
    store.session("s-unrelated", [_typed("/dev something else")])
    walked = []
    real = obligation.dispatch_obligations
    monkeypatch.setattr(obligation, "dispatch_obligations",
                        lambda path, *a, **k: walked.append(Path(path).stem) or real(path, *a, **k))
    store.ask(f"docs/dev/dev-report-{TASK}-l1.json")
    assert walked == ["s-dev"]


def test_command_templates_read_both_template_forms():
    dev = obligation.command_templates("dev")
    assert {(t["step"], t["role"]) for t in dev} >= {("4", "ba"), ("10", "dev"), ("13", "qa")}
    close = obligation.command_templates("close")
    assert ("2", "qa") in {(t["step"], t["role"]) for t in close}
    commit = obligation.command_templates("commit")
    assert any(a.get("path", "").startswith("docs/dev/commit-qa-report-")
               for t in commit for a in t["artifacts"] if isinstance(a, dict))


def test_the_cli_prints_the_answer(tmp_path):
    store = Store(tmp_path)
    _fanout_dev_session(store)
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    env.pop("CLAUDE_RESTART_ACCOUNTS_ROOT", None)
    run = subprocess.run(
        [sys.executable, str(REPO_ROOT / "hooks" / "lib" / "obligation.py"), "declaring-dispatch",
         "--task-id", TASK, "--path", f"docs/dev/dev-report-{TASK}-l1.json", "--project-dir", str(store.project)],
        capture_output=True, text=True, env=env, timeout=60)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["tool_use_id"] == "toolu_dev_l1"
    run = subprocess.run(
        [sys.executable, str(REPO_ROOT / "hooks" / "lib" / "obligation.py"), "declaring-dispatch",
         "--task-id", TASK, "--path", "src/none.py", "--project-dir", str(store.project)],
        capture_output=True, text=True, env=env, timeout=60)
    assert run.returncode == 0 and json.loads(run.stdout) is None


def test_a_fan_out_s_canonical_aggregate_goes_back_through_a_lane_dispatch(tmp_path):
    """No dispatch declares the cycle-level dev report of a fan-out: the lanes'
    dev dispatches produce it together (the lane-completeness hook runs on a
    lane report's write), so the answer is the latest lane dev dispatch. A
    lane's own report never gets this answer."""
    store = Store(tmp_path)
    _fanout_dev_session(store)
    answer = store.ask(f"docs/dev/dev-report-{TASK}.json")
    assert answer["source"] == "lane"
    assert (answer["role"], answer["subagent_type"], answer["lane"]) == ("dev", "dev", "l2")
    assert store.ask(f"docs/dev/qa-report-{TASK}-l3.json")["source"] == "todo_step"


def test_a_transcript_last_written_before_the_task_was_minted_is_not_read(tmp_path, monkeypatch):
    store = Store(tmp_path)
    old = _fanout_dev_session(store)
    stamp = 1767225600  # 2026-01-01, months before TASK's timestamp
    os.utime(old, (stamp, stamp))
    assert store.ask(f"docs/dev/dev-report-{TASK}-l1.json") is None


def test_the_completion_report_is_dev_step_17_the_main_agent_s_own(tmp_path):
    """/dev Step 17 declares the completion report it writes: a gap on it is a
    step the asking main agent runs itself."""
    store = Store(tmp_path)
    _fanout_dev_session(store)
    answer = store.ask(f"docs/dev/completion-{TASK}.md")
    assert answer["source"] == "todo_step" and answer["step"].startswith("Step 17:")
    assert answer["subagent_call"] is None and answer["template"] is None


def test_a_write_outranks_a_later_dispatch_that_only_names_the_file(tmp_path):
    """QA's `git diff -- src/app.py` names the file after dev wrote it: the
    owner is the dev dispatch that wrote it."""
    store = Store(tmp_path)
    _fanout_dev_session(store)
    write = {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "w1", "name": "Write",
         "input": {"file_path": str(store.project / "src/app.py"), "content": "x = 1\n"}}]}}
    ok = {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "w1", "content": "written"}]}}
    store.agent("s-dev", "a-dev-l1", "toolu_dev_l1", [write, ok])
    diff = {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "git diff -- src/app.py"}}]}}
    store.agent("s-dev", "a-qa-l2", "toolu_qa_l2", [diff])
    answer = store.ask("src/app.py")
    assert (answer["source"], answer["tool_use_id"]) == ("writer", "toolu_dev_l1")
