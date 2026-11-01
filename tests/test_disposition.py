"""The disposition of a task at the dev, close and commit stages
(scripts/resolve-dev-artifact-chain.py ``disposition`` and ``--disposition``).

Every fixture is a scratch ``docs/dev/`` tree under ``tmp_path``; each write is
strictly newer than the one before it, so "newer" in a case is the order its
artifacts were written in.  Commit-stage fixtures are scratch git repositories
with a local bare origin and a fixed test identity.  Session transcripts, where
a case needs them, live in the per-test CLAUDE_CONFIG_DIR the root conftest
sets, written in the record shapes the CLI writes.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from hooks.lib import obligation  # noqa: E402
from hooks.lib.subagent_restart import project_slug  # noqa: E402

RESOLVER_PATH = REPO_ROOT / "scripts" / "resolve-dev-artifact-chain.py"
TASK = "20260724-120000"
LANES = ("l1", "l2")
GIT_ENV = {
    "GIT_AUTHOR_NAME": "Disposition Fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "Disposition Fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
}
HEADER_RE = re.compile(r"DISPOSITION=(chain_pass|incomplete) STAGE=(dev|close|commit) TASK=(\S+)")
_VALUE = r'"(?:[^"\\]|\\.)*"'
GAP_RE = re.compile(
    rf"GAP artifact=(?P<artifact>{_VALUE}|[!#-\[\]-~]+) "
    rf"problem=(?P<problem>{_VALUE}|[!#-\[\]-~]+?): (?P<message>.*) "
    rf"lane=(?P<lane>{_VALUE}|[!#-\[\]-~]+)"
)


def _load_resolver():
    spec = importlib.util.spec_from_file_location("disposition_resolver", RESOLVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RESOLVER = _load_resolver()


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


class Tree:
    """A project whose docs/dev artifacts are written in order, each newer
    than the one before."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.dev = root / "docs" / "dev"
        self.dev.mkdir(parents=True)
        self.clock = time.time() - 100_000

    def write(self, name: str, value) -> Path:
        path = self.dev / name
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
        self.clock += 10
        os.utime(path, (self.clock, self.clock))
        return path

    def rel(self, name: str) -> str:
        return f"docs/dev/{name}"


def dev_report(tid, status="completed", files=("scripts/one.py",), **top):
    return {
        "request_id": tid,
        "task_id": tid,
        "baseline_head_sha": "0123456789abcdef",
        "baseline_dirty_snapshot": "",
        "dev": {
            "status": status,
            "tasks_completed": ["t"],
            "scripts_created": [],
            "permissions_to_add": [],
            "files_modified": list(files),
            "files_created": [],
            "observed_preexisting": [],
        },
        "blocking_issues": [],
        "recommendations": [],
        **top,
    }


def qa_report(tid, status="pass"):
    return {"request_id": tid, "task_id": tid, "qa": {"status": status}}


def ba_qa_report(tid, verdict="pass"):
    return {"task_id": tid, "verdict": verdict, "objections": [], "summary": "s"}


def ticket(tid):
    return f"# Ticket\n\n**TASK-ID**: `{tid}`\n"


def context(tid):
    return {"request_id": tid, "task_id": tid}


def write_unit(tree: Tree, tid: str, files=("scripts/one.py",), **dev_top) -> None:
    """One lane's (or a singular chain's) artifacts in production order; no
    completion note, which is no gap."""
    for path in files:
        (tree.root / path).parent.mkdir(parents=True, exist_ok=True)
        (tree.root / path).touch()
    tree.write(f"ticket-{tid}.md", ticket(tid))
    tree.write(f"context-{tid}.json", context(tid))
    tree.write(f"ba-qa-report-{tid}.json", ba_qa_report(tid))
    tree.write(f"dev-report-{tid}.json", dev_report(tid, files=files, **dev_top))
    tree.write(f"qa-report-{tid}.json", qa_report(tid))


def singular(tmp_path: Path) -> Tree:
    tree = Tree(tmp_path / "proj")
    write_unit(tree, TASK)
    return tree


def fanout(tmp_path: Path, lanes=LANES, lane_sets=None) -> Tree:
    """A fan-out whose lanes echo their dispatch roster (lane, lane_set), and
    its canonical as the aggregator builds it."""
    tree = Tree(tmp_path / "proj")
    loaded = []
    for index, lane in enumerate(lanes):
        lane_set = (lane_sets or {}).get(lane, list(lanes))
        tid = f"{TASK}-{lane}"
        write_unit(tree, tid, files=(f"scripts/lane-{index}.py",), lane=lane, lane_set=lane_set)
        loaded.append((lane, json.loads((tree.dev / f"dev-report-{tid}.json").read_text())))
    tree.write(f"dev-report-{TASK}.json", RESOLVER._load_aggregate_module()._build_aggregate(loaded, TASK))
    return tree


def run_cli(root: Path, stage: str, *, script: Path = RESOLVER_PATH, cwd: Path | None = None, project_dir=True):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    argv = [sys.executable, str(script), "--disposition", "--stage", stage, "--task-id", TASK]
    if project_dir:
        argv += ["--project-dir", str(root)]
    return subprocess.run(argv, capture_output=True, text=True, env=env, cwd=str(cwd or root), timeout=120)


def _decode(value: str):
    return json.loads(value) if value.startswith('"') else value


def parse_gap(line: str) -> dict:
    match = GAP_RE.fullmatch(line)
    assert match, line
    lane = match["lane"]
    return {
        "artifact": _decode(match["artifact"]),
        "problem": _decode(match["problem"]),
        "message": _decode(match["message"]),
        "lane": None if lane == "-" else _decode(lane),
    }


def chain_line(stdout: str):
    """The chain's data the CLI prints on its last line (CHAIN=<json>), else None."""
    last = stdout.splitlines()[-1]
    return json.loads(last[len("CHAIN="):]) if last.startswith("CHAIN=") else None


def outcome(root: Path, stage: str = "dev", **kwargs):
    """(disposition, gaps) as the CLI prints them; every line must parse."""
    proc = run_cli(root, stage, **kwargs)
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    header = HEADER_RE.fullmatch(lines[0])
    assert header and header.group(2) == stage and header.group(3) == TASK, proc.stdout
    if chain_line(proc.stdout) is not None:
        lines = lines[:-1]
    gaps = [parse_gap(line) for line in lines[1:]]
    assert (header.group(1) == "chain_pass") == (gaps == [])
    return header.group(1), gaps


def pairs(gaps) -> list[tuple[str, str]]:
    return [(gap["artifact"], gap["problem"]) for gap in gaps]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), env={**os.environ, **GIT_ENV},
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def repository(tree: Tree, tmp_path: Path) -> None:
    """The project as a git repository on main, pushed to a local bare origin."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tree.root, "init", "-q", "-b", "main")
    _git(tree.root, "remote", "add", "origin", str(origin))
    _git(tree.root, "add", "-A")
    _git(tree.root, "commit", "-q", "-m", "cycle artifacts")
    _git(tree.root, "push", "-q", "-u", "origin", "main")


def land(tree: Tree) -> None:
    (tree.root / "scripts" / "one.py").write_text("landed = True\n")
    _git(tree.root, "add", "-A")
    _git(tree.root, "commit", "-q", "-m", f"land the change\n\nTask-id: {TASK}")


def session(root: Path, sid: str, records: list[dict]) -> Path:
    directory = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / project_slug(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{sid}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def typed(command: str, args: str = "") -> dict:
    return {"type": "user", "message": {"role": "user", "content":
            f"<command-message>{command} is running…</command-message>\n"
            f"<command-name>/{command}</command-name>\n<command-args>{args}</command-args>"}}


def minted(task: str = TASK) -> dict:
    return {"type": "attachment", "attachment": {
        "type": "hook_additional_context", "hookName": "UserPromptSubmit",
        "content": f"[/do] Consent granted.\n[/do] task-id minted: {task} — resolve via the session sidecar."}}


def dispatch(use_id: str, subagent_type: str, doc: dict) -> dict:
    prompt = "Do the work.\n" + obligation.serialize_obligation(doc)
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": use_id, "name": "Agent",
         "input": {"subagent_type": subagent_type, "prompt": prompt}}]}}


def ob(tid, role, pipeline, profile, artifacts, lane=None, lane_set=None):
    return {"task_id": tid, "lane": lane, "lane_set": lane_set, "role": role, "pipeline": pipeline,
            "profile": profile, "dispatched_at": "2026-07-24T12:00:00Z", "artifacts": artifacts}


# --------------------------------------------------------------------------
# A2: the dev stage
# --------------------------------------------------------------------------


def test_a_full_singular_chain_is_chain_pass(tmp_path):
    tree = singular(tmp_path)
    proc = run_cli(tree.root, "dev")
    assert proc.returncode == 0
    assert proc.stdout.splitlines()[0] == f"DISPOSITION=chain_pass STAGE=dev TASK={TASK}"
    assert len(proc.stdout.splitlines()) == 2 and set(chain_line(proc.stdout)) == set(RESOLVER.CHAIN_FIELDS)


def test_the_chain_line_carries_the_resolved_chain_data(tmp_path):
    """Steps 1-3 of /close and /commit read mode, lanes, report paths, the canonical
    report, artifact paths, the commit whitelist and QA inputs from this one run."""
    tree = fanout(tmp_path)
    proc = run_cli(tree.root, "dev")
    chain = chain_line(proc.stdout)
    resolved = RESOLVER.resolve_chain(tree.root, TASK)
    assert chain == json.loads(json.dumps({key: resolved[key] for key in RESOLVER.CHAIN_FIELDS}))
    assert chain["lanes"], chain


def test_a_full_two_lane_fanout_chain_is_chain_pass(tmp_path):
    assert outcome(fanout(tmp_path).root) == ("chain_pass", [])


def test_a_missing_qa_report_is_a_missing_artifact_gap(tmp_path):
    tree = singular(tmp_path)
    (tree.dev / f"qa-report-{TASK}.json").unlink()
    assert pairs(outcome(tree.root)[1]) == [(tree.rel(f"qa-report-{TASK}.json"), "MISSING_ARTIFACT")]


@pytest.mark.parametrize("qa", [
    qa_report(TASK, "warning"),
    qa_report(TASK, "fail"),
    {**qa_report(TASK, "fail"), "iteration_needed": False, "qa": {"status": "fail", "disclosed_exception": {
        "classification": "shared_working_tree_concurrency", "evidence": ["log:1"],
        "attestation": "This is a disclosed, evidenced, non-defect exception -- not a defect in "
                       "this lane's deliverable."}}},
], ids=["warning", "fail", "environmental-disclosure"])
def test_a_qa_report_short_of_pass_is_invalid_qa_status(tmp_path, qa):
    tree = singular(tmp_path)
    tree.write(f"qa-report-{TASK}.json", qa)
    assert pairs(outcome(tree.root)[1]) == [(tree.rel(f"qa-report-{TASK}.json"), "INVALID_QA_STATUS")]


def test_a_ba_qa_verdict_fail_or_missing_is_a_gap_on_the_ba_qa_report(tmp_path):
    tree = singular(tmp_path)
    name = f"ba-qa-report-{TASK}.json"
    tree.write(name, ba_qa_report(TASK, "fail"))
    assert pairs(outcome(tree.root)[1]) == [(tree.rel(name), "INVALID_BA_QA_VERDICT")]
    (tree.dev / name).unlink()
    assert pairs(outcome(tree.root)[1]) == [(tree.rel(name), "MISSING_ARTIFACT")]


@pytest.mark.parametrize("report", [
    dev_report(TASK, "blocked", blocking_issues=["AC19: x"]),
    dev_report(TASK, "needs_review", blocking_issues=["awaiting commit"]) | {"dev": {
        **dev_report(TASK)["dev"], "status": "needs_review", "status_rationale": {
            "classification": "pending_commit_handoff", "blocked_by": "x", "forbidden_action": "y"}}},
], ids=["blocked", "status-rationale"])
def test_a_historic_dev_report_short_of_completed_is_invalid_dev_status(tmp_path, report):
    tree = singular(tmp_path)
    tree.write(f"dev-report-{TASK}.json", report)
    _, gaps = outcome(tree.root)
    assert (tree.rel(f"dev-report-{TASK}.json"), "INVALID_DEV_STATUS") in pairs(gaps)


def test_divergent_lane_set_echoes_are_one_gap_naming_both_rosters(tmp_path):
    tree = fanout(tmp_path, lane_sets={"l2": ["l1", "l2", "l3"]})
    _, gaps = outcome(tree.root)
    roster = [g for g in gaps if g["problem"] == "LANE_SET_MISMATCH"]
    assert len(roster) == 1
    assert roster[0]["artifact"] == tree.rel(f"dev-report-{TASK}.json")
    assert "['l1', 'l2']" in roster[0]["message"] and "['l1', 'l2', 'l3']" in roster[0]["message"]


def test_a_roster_lane_without_a_shard_and_a_shard_outside_the_roster_are_gaps(tmp_path):
    missing = fanout(tmp_path / "missing", lane_sets={lane: ["l1", "l2", "l3"] for lane in LANES})
    messages = [g["message"] for g in outcome(missing.root)[1] if g["problem"] == "LANE_SET_MISMATCH"]
    assert messages == ["roster lane 'l3' of lane_set ['l1', 'l2', 'l3'] has no shard"]

    outside = fanout(tmp_path / "outside", lanes=("l1", "l2", "l3"),
                     lane_sets={lane: ["l1", "l2"] for lane in ("l1", "l2", "l3")})
    messages = [g["message"] for g in outcome(outside.root)[1] if g["problem"] == "LANE_SET_MISMATCH"]
    assert messages == ["shard 'l3' is outside the recorded lane_set ['l1', 'l2']"]


def test_a_missing_completion_note_is_no_gap_and_escalation_records_are_never_read(tmp_path):
    tree = singular(tmp_path)
    tree.write(f"arbitration-{TASK}.json", {"verdict": "release"})
    registry = tree.root / ".claude" / "dev-registry" / f"dev-{TASK}" / "escalations"
    registry.mkdir(parents=True)
    (registry / "record.json").write_text("{}")
    assert outcome(tree.root) == ("chain_pass", [])


# --------------------------------------------------------------------------
# A2: the /do branch
# --------------------------------------------------------------------------


def do_report(status="completed", **extra):
    return {"report_version": 1, "task_id": TASK, "request_id": TASK, "source": "do", "request": "r",
            "do": {"status": status, "summary": "s", "files_modified": ["scripts/one.py"], "files_created": []},
            **extra}


def test_a_completed_do_report_is_chain_pass(tmp_path):
    tree = Tree(tmp_path / "proj")
    tree.write(f"do-report-{TASK}.json", do_report())
    assert outcome(tree.root) == ("chain_pass", [])


def test_a_minted_do_task_without_its_report_is_a_missing_do_report(tmp_path):
    tree = Tree(tmp_path / "proj")
    session(tree.root, "s-do", [typed("do", "make a change"), minted()])
    assert pairs(outcome(tree.root)[1]) == [(tree.rel(f"do-report-{TASK}.json"), "MISSING_ARTIFACT")]


def test_the_minted_record_is_found_from_a_later_session(tmp_path):
    tree = Tree(tmp_path / "proj")
    session(tree.root, "s-do", [typed("do", "make a change"), minted()])
    session(tree.root, "s-close", [typed("close", TASK)])
    tree.write(f"do-report-{TASK}.json", {**do_report(), "source": None})
    assert outcome(tree.root, "dev") == ("chain_pass", [])


@pytest.mark.parametrize("records", [
    [typed("dev", "x"), minted()],
    [typed("do", "x"), {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": f"[/do] task-id minted: {TASK}"}]}}],
], ids=["outside-a-do-span", "agent-text"])
def test_a_minted_line_outside_the_do_hook_record_is_no_do_task(tmp_path, records):
    tree = Tree(tmp_path / "proj")
    session(tree.root, "s", records)
    _, gaps = outcome(tree.root)
    assert (tree.rel(f"dev-report-{TASK}.json"), "MISSING_ARTIFACT") in pairs(gaps)
    assert tree.rel(f"do-report-{TASK}.json") not in [g["artifact"] for g in gaps]


@pytest.mark.parametrize("status,problem", [
    (None, "do.status:null"),
    ("blocked", "do.status:blocked"),
], ids=["skeleton-unwritten", "blocked"])
def test_a_do_report_short_of_completed_is_a_do_status_gap(tmp_path, status, problem):
    tree = Tree(tmp_path / "proj")
    report = do_report()
    if status is None:
        del report["do"]["status"]
    else:
        report["do"]["status"] = status
    tree.write(f"do-report-{TASK}.json", report)
    assert pairs(outcome(tree.root)[1]) == [(tree.rel(f"do-report-{TASK}.json"), problem)]


# Q7: dev, dispatched along the do-report's route (close.md Routes), concludes a /do task whose do-report is
# not completed in its own dev-report; no ticket, context or QA report is asked of a /do task.
@pytest.mark.parametrize("stage", ["dev", "close"])
def test_dev_s_report_concludes_a_do_task_whose_do_report_is_not_completed(tmp_path, stage):
    tree = Tree(tmp_path / "proj")
    tree.write(f"do-report-{TASK}.json", do_report("blocked"))
    tree.write(f"dev-report-{TASK}.json", dev_report(TASK))
    if stage == "close":
        tree.write(f"close-report-{TASK}.md", "# Close\n\nCLOSE: YES — codex disabled by user\n")
    assert outcome(tree.root, stage) == ("chain_pass", [])


def test_dev_s_report_short_of_completed_leaves_the_do_task_open_on_it(tmp_path):
    tree = Tree(tmp_path / "proj")
    tree.write(f"do-report-{TASK}.json", do_report("blocked"))
    tree.write(f"dev-report-{TASK}.json", dev_report(TASK, status="blocked"))
    assert pairs(outcome(tree.root)[1]) == [(tree.rel(f"dev-report-{TASK}.json"), "INVALID_DEV_STATUS")]


def test_a_completed_do_report_concludes_beside_dev_s_report(tmp_path):
    tree = Tree(tmp_path / "proj")
    tree.write(f"do-report-{TASK}.json", do_report())
    tree.write(f"dev-report-{TASK}.json", dev_report(TASK, status="blocked"))
    assert outcome(tree.root) == ("chain_pass", [])


# --------------------------------------------------------------------------
# A2: instrument failures are never a disposition
# --------------------------------------------------------------------------


def test_an_aggregator_that_raises_at_import_is_an_instrument_failure(tmp_path):
    harness = tmp_path / "harness"
    (harness / "scripts").mkdir(parents=True)
    shutil.copy(RESOLVER_PATH, harness / "scripts" / RESOLVER_PATH.name)
    (harness / "scripts" / "aggregate-dev-report.py").write_text(
        "raise ImportError('aggregator unimportable')\n", encoding="utf-8")
    (harness / "hooks").symlink_to(REPO_ROOT / "hooks", target_is_directory=True)
    tree = singular(tmp_path)

    proc = run_cli(tree.root, "dev", script=harness / "scripts" / RESOLVER_PATH.name)

    assert proc.returncode == RESOLVER.INSTRUMENT_FAILURE_EXIT != 0
    assert "DISPOSITION=" not in proc.stdout
    assert "AGGREGATE_IMPLEMENTATION_ERROR" in proc.stderr
    assert "aggregator unimportable" in proc.stderr


@pytest.mark.parametrize("argv", [["--stage", "review"], []], ids=["unknown-stage", "no-stage"])
def test_an_unusable_stage_is_an_instrument_failure(tmp_path, argv):
    tree = singular(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(RESOLVER_PATH), "--disposition", *argv, "--task-id", TASK,
         "--project-dir", str(tree.root)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "stage must be one of dev, close, commit" in proc.stderr


def test_the_importable_function_raises_on_an_instrument_failure(tmp_path, monkeypatch):
    tree = singular(tmp_path)
    module = _load_resolver()

    def unimportable():
        raise ImportError("aggregator unimportable")

    monkeypatch.setattr(module, "_load_aggregate_module", unimportable)
    with pytest.raises(RuntimeError, match="AGGREGATE_IMPLEMENTATION_ERROR"):
        module.disposition(tree.root, TASK, "dev")
    with pytest.raises(ValueError):
        module.disposition(tree.root, "../escape", "dev")


def test_the_importable_function_returns_the_disposition_the_cli_prints(tmp_path):
    tree = singular(tmp_path)
    tree.write(f"qa-report-{TASK}.json", qa_report(TASK, "fail"))
    result = RESOLVER.disposition(tree.root, TASK, "dev")
    assert set(result.pop("chain")) == set(RESOLVER.CHAIN_FIELDS)
    assert result == {
        "disposition": "incomplete",
        "stage": "dev",
        "task_id": TASK,
        "gaps": [{"artifact": tree.rel(f"qa-report-{TASK}.json"), "problem": "INVALID_QA_STATUS",
                  "message": "qa.status is 'fail'; expected 'pass'", "lane": None}],
    }
    assert outcome(tree.root)[1] == result["gaps"]


# --------------------------------------------------------------------------
# A3: each gap clears only when its producer writes again
# --------------------------------------------------------------------------


def test_a_failing_qa_report_clears_only_on_a_newer_passing_one(tmp_path):
    tree = singular(tmp_path)
    qa = tree.rel(f"qa-report-{TASK}.json")
    tree.write(f"qa-report-{TASK}.json", qa_report(TASK, "fail"))
    assert pairs(outcome(tree.root)[1]) == [(qa, "INVALID_QA_STATUS")]
    tree.write(f"dev-report-{TASK}.json", dev_report(TASK))
    assert pairs(outcome(tree.root)[1]) == [(qa, "INVALID_QA_STATUS")]
    tree.write(f"qa-report-{TASK}.json", qa_report(TASK))
    assert outcome(tree.root) == ("chain_pass", [])


def test_a_failing_ba_qa_verdict_clears_only_on_a_newer_pass(tmp_path):
    tree = singular(tmp_path)
    ba_qa = tree.rel(f"ba-qa-report-{TASK}.json")
    tree.write(f"ba-qa-report-{TASK}.json", ba_qa_report(TASK, "fail"))
    assert pairs(outcome(tree.root)[1]) == [(ba_qa, "INVALID_BA_QA_VERDICT")]
    tree.write(f"ticket-{TASK}.md", ticket(TASK))
    tree.write(f"context-{TASK}.json", context(TASK))
    assert pairs(outcome(tree.root)[1]) == [(ba_qa, "INVALID_BA_QA_VERDICT")]
    tree.write(f"ba-qa-report-{TASK}.json", ba_qa_report(TASK))
    assert outcome(tree.root) == ("chain_pass", [])


def producer_question(role: str) -> dict:
    return {"task_id": TASK, "role": role, "need": "which file format",
            "options": [{"label": "json", "description": "j"}, {"label": "yaml", "description": "y"}],
            "default": "json", "why": "the request names neither"}


@pytest.mark.parametrize("role,answers", [
    ("ba", (f"ticket-{TASK}.md", f"context-{TASK}.json")),
    ("dev", (f"dev-report-{TASK}.json",)),
], ids=["ba", "dev"])
def test_a_producer_question_is_unanswered_until_its_next_artifacts(tmp_path, role, answers):
    tree = singular(tmp_path)
    name = f"producer-question-{TASK}-{role}.json"
    tree.write(name, producer_question(role))
    assert pairs(outcome(tree.root)[1]) == [(tree.rel(name), "unanswered")]
    builders = {f"ticket-{TASK}.md": ticket(TASK), f"context-{TASK}.json": context(TASK),
                f"dev-report-{TASK}.json": dev_report(TASK)}
    for answer in answers[:-1]:
        tree.write(answer, builders[answer])
        assert pairs(outcome(tree.root)[1]) == [(tree.rel(name), "unanswered")]
    tree.write(answers[-1], builders[answers[-1]])
    assert outcome(tree.root) == ("chain_pass", [])


# --------------------------------------------------------------------------
# A5: the close stage
# --------------------------------------------------------------------------


def test_a_complete_dev_chain_without_a_close_report_is_one_close_gap(tmp_path):
    tree = singular(tmp_path)
    assert pairs(outcome(tree.root, "close")[1]) == [(tree.rel(f"close-report-{TASK}.md"), "INVALID_CLOSE_VERDICT")]


@pytest.mark.parametrize("last,passes", [
    ("CLOSE: YES", True),
    ("CLOSE: YES (FORCED)", True),
    ("CLOSE: NO", False),
    ("CLOSE_FINDINGS: 2 items", False),
], ids=["yes", "legacy-yes-form", "no", "round-open"])
def test_the_close_report_last_line_decides(tmp_path, last, passes):
    tree = singular(tmp_path)
    tree.write(f"close-report-{TASK}.md", f"# Close\n\nTask ID: {TASK}\n\nCLOSE: NO\n\n{last}\n\n")
    expected = [] if passes else [(tree.rel(f"close-report-{TASK}.md"), "INVALID_CLOSE_VERDICT")]
    assert pairs(outcome(tree.root, "close")[1]) == expected


def test_a_dev_stage_gap_is_listed_before_the_close_gap(tmp_path):
    tree = singular(tmp_path)
    tree.write(f"close-report-{TASK}.md", "CLOSE: YES (FORCED)\n")
    (tree.dev / f"qa-report-{TASK}.json").unlink()
    assert pairs(outcome(tree.root, "close")[1]) == [(tree.rel(f"qa-report-{TASK}.json"), "MISSING_ARTIFACT")]
    tree.write(f"close-report-{TASK}.md", "CLOSE: NO\n")
    assert pairs(outcome(tree.root, "close")[1]) == [
        (tree.rel(f"qa-report-{TASK}.json"), "MISSING_ARTIFACT"),
        (tree.rel(f"close-report-{TASK}.md"), "INVALID_CLOSE_VERDICT"),
    ]


# --------------------------------------------------------------------------
# A6: the commit stage
# --------------------------------------------------------------------------


@pytest.fixture
def closed(tmp_path):
    tree = singular(tmp_path)
    tree.write(f"close-report-{TASK}.md", "# Close\n\nCLOSE: YES\n")
    repository(tree, tmp_path)
    return tree


def test_no_task_id_commit_is_a_gap_naming_the_repository(closed):
    assert pairs(outcome(closed.root, "commit")[1]) == [(".", "MISSING_TASK_TRAILER")]


def test_a_task_id_commit_reachable_from_head_is_chain_pass_dirty_tree_or_not(closed):
    land(closed)
    assert outcome(closed.root, "commit") == ("chain_pass", [])
    (closed.root / "scripts" / "one.py").write_text("edited after landing\n")
    assert outcome(closed.root, "commit") == ("chain_pass", [])


def test_a_task_id_commit_on_another_branch_only_is_a_gap(closed):
    _git(closed.root, "checkout", "-q", "--detach")
    land(closed)
    _git(closed.root, "update-ref", "refs/heads/side", _git(closed.root, "rev-parse", "HEAD"))
    _git(closed.root, "checkout", "-q", "main")
    assert pairs(outcome(closed.root, "commit")[1]) == [(".", "MISSING_TASK_TRAILER")]


def test_a_do_task_commit_plan_reads_its_do_report(tmp_path):
    tree = Tree(tmp_path / "proj")
    (tree.root / "scripts").mkdir()
    (tree.root / "scripts" / "one.py").touch()
    tree.write(f"do-report-{TASK}.json", do_report())
    tree.write(f"close-report-{TASK}.md", "CLOSE: YES\n")
    repository(tree, tmp_path)
    assert pairs(outcome(tree.root, "commit")[1]) == [(".", "MISSING_TASK_TRAILER")]
    land(tree)
    assert outcome(tree.root, "commit") == ("chain_pass", [])


# --------------------------------------------------------------------------
# Fault replays: a gap names the artifact, its failing check and the lane of
# the dispatch that declared it, and clears when that producer writes again.
# --------------------------------------------------------------------------


def test_dev_stage_fault_replay(tmp_path):
    tree = fanout(tmp_path)
    lane_set = list(LANES)
    records = [typed("dev", "build the thing")]
    for lane in LANES:
        lid = f"{TASK}-{lane}"
        records.append(dispatch(f"toolu_qa_{lane}", "qa", ob(lid, "qa", "dev", "fanout-lane", [
            {"kind": "json", "path": f"docs/dev/qa-report-{lid}.json", "schema": "qa-report.v2",
             "identity": {"task_id": lid}}], lane=lane, lane_set=lane_set)))
    session(tree.root, "s-dev", records)
    qa = f"qa-report-{TASK}-l2.json"
    tree.write(qa, qa_report(f"{TASK}-l2", "fail"))

    _, gaps = outcome(tree.root)
    assert gaps == [{"artifact": tree.rel(qa), "problem": "INVALID_QA_STATUS",
                     "message": "qa.status is 'fail'; expected 'pass'", "lane": "l2"}]
    owner = obligation.declaring_dispatch(TASK, tree.rel(qa), tree.root)
    assert (owner["source"], owner["role"], owner["lane"]) == ("dispatch", "qa", "l2")

    tree.write(qa, qa_report(f"{TASK}-l2"))  # the declared QA's next round
    assert outcome(tree.root) == ("chain_pass", [])


def test_close_stage_fault_replay(tmp_path):
    tree = singular(tmp_path)
    close = f"close-report-{TASK}.md"
    session(tree.root, "s-close", [typed("close", TASK), dispatch("toolu_close_qa", "qa", ob(
        TASK, "qa", "close", "final_verification",
        [{"kind": "markdown", "path": f"docs/dev/{close}", "identity_anchor": TASK}]))])
    tree.write(close, "# Close\n\nCLOSE: NO\n")

    _, gaps = outcome(tree.root, "close")
    assert pairs(gaps) == [(tree.rel(close), "INVALID_CLOSE_VERDICT")]
    assert "'no'" in gaps[0]["message"]
    owner = obligation.declaring_dispatch(TASK, tree.rel(close), tree.root)
    assert (owner["source"], owner["role"], owner["tool_use_id"]) == ("dispatch", "qa", "toolu_close_qa")

    tree.write(close, "# Close\n\nCLOSE: NO\n\nCLOSE: YES\n")  # the close QA's next round
    assert outcome(tree.root, "close") == ("chain_pass", [])


def test_commit_stage_fault_replay(closed):
    _, gaps = outcome(closed.root, "commit")
    assert gaps == [{"artifact": ".", "problem": "MISSING_TASK_TRAILER",
                     "message": f"no commit reachable from HEAD carries the line 'Task-id: {TASK}'",
                     "lane": None}]
    land(closed)  # the landing producer's commit
    assert outcome(closed.root, "commit") == ("chain_pass", [])


# --------------------------------------------------------------------------
# Decided choices: lane fallback, gap-line quoting, the default project root
# --------------------------------------------------------------------------


def test_with_no_declaring_dispatch_a_lane_artifact_takes_its_resolver_lane(tmp_path):
    tree = fanout(tmp_path)
    qa = f"qa-report-{TASK}-l1.json"
    tree.write(qa, qa_report(f"{TASK}-l1", "fail"))
    assert obligation.declaring_dispatch(TASK, tree.rel(qa), tree.root) is None
    assert [(g["artifact"], g["lane"]) for g in outcome(tree.root)[1]] == [(tree.rel(qa), "l1")]


def test_a_gap_line_reads_back_exactly_whatever_its_values_hold():
    odd = {"artifact": 'repo dir/"quoted"', "problem": "do.status:half: done",
           "message": 'line one\nline two lane=x "q"', "lane": "lane with space"}
    plain = {"artifact": "docs/dev/qa-report-x.json", "problem": "do.status:blocked",
             "message": "qa.status is 'fail'; expected 'pass'", "lane": None}
    for gap in (odd, plain):
        line = RESOLVER.gap_line(gap)
        assert "\n" not in line and line.isascii()
        assert parse_gap(line) == gap
    assert RESOLVER.gap_line(plain) == (
        "GAP artifact=docs/dev/qa-report-x.json problem=do.status:blocked: "
        "qa.status is 'fail'; expected 'pass' lane=-")


def test_an_odd_do_status_prints_one_parseable_line(tmp_path):
    tree = Tree(tmp_path / "proj")
    report = do_report("stopped: waiting\n lane=x")
    tree.write(f"do-report-{TASK}.json", report)
    _, gaps = outcome(tree.root)
    assert gaps == RESOLVER.disposition(tree.root, TASK, "dev")["gaps"]
    assert gaps[0]["problem"] == "do.status:stopped: waiting\n lane=x"


def test_without_the_flag_the_project_root_is_the_working_directory_s_git_top_level(tmp_path):
    tree = singular(tmp_path)
    repository(tree, tmp_path)
    proc = run_cli(tree.root, "dev", cwd=tree.root / "scripts", project_dir=False)
    assert proc.returncode == 0
    assert proc.stdout.splitlines()[0] == f"DISPOSITION=chain_pass STAGE=dev TASK={TASK}"
    assert set(chain_line(proc.stdout)) == set(RESOLVER.CHAIN_FIELDS)
