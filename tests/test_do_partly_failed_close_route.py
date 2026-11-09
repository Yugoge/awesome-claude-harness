"""P5-62: a /do that failed partway must not hold /close with no way out.

The state: the /do main agent wrote src/a.py, listed it, and its turn ended with
the do-report short of `completed`; /close's Routes dispatched dev, which wrote
src/b.py and lists it (G2 makes dev list every file it wrote). On the route
without a transcript, the chain's do branch asked the do-report's lists to equal
dev's report. Only the do-report's producer, whose /do had ended, could change
them (D8), so no agent could release /close (D25). The rule now asks dev's
report, which concludes the task and feeds /commit's repository plan, to hold
each file the do-report lists; dev repairs it (a file it names counts at G2).
The /do Stop's checks, with the transcript, are unchanged.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RESOLVER = REPO / "scripts" / "resolve-dev-artifact-chain.py"
TASK = "20261109-120000"
DO_REL = f"docs/dev/do-report-{TASK}.json"
DEV_REL = f"docs/dev/dev-report-{TASK}.json"


def _load():
    spec = importlib.util.spec_from_file_location("resolver_p5_62", RESOLVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


resolver = _load()


def write(root: Path, rel: str, value) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
    return path


def do_report(status="blocked", modified=("src/a.py",), created=()):
    return {"report_version": 1, "task_id": TASK, "request_id": TASK, "source": "do", "request": "r",
            "do": {"status": status, "summary": "stopped after src/a.py", "files_modified": list(modified),
                   "files_created": list(created)}}


def dev_report(modified, created=(), status="completed"):
    return {"request_id": TASK, "task_id": TASK, "baseline_head_sha": "0123456789abcdef",
            "baseline_dirty_snapshot": "",
            "dev": {"status": status, "tasks_completed": ["t"], "scripts_created": [], "permissions_to_add": [],
                    "files_modified": list(modified), "files_created": list(created), "observed_preexisting": []},
            "blocking_issues": [], "recommendations": []}


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    (root / "docs" / "dev").mkdir(parents=True)
    (root / "src").mkdir()
    for name in ("a.py", "b.py"):
        (root / "src" / name).write_text("x\n", encoding="utf-8")
    write(root, f"docs/dev/close-report-{TASK}.md", "# Close\n\nCLOSE: YES — codex disabled by user\n")
    return root


def chain(root: Path, stage: str) -> tuple[str, list[str]]:
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    proc = subprocess.run([sys.executable, str(RESOLVER), "--disposition", "--stage", stage, "--task-id", TASK,
                           "--project-dir", str(root)], capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == 0, proc.stderr
    lines = [line for line in proc.stdout.splitlines() if not line.startswith("CHAIN=")]
    return lines[0].split()[0].split("=", 1)[1], lines[1:]


@pytest.mark.parametrize("stage", ["dev", "close"])
def test_a_partly_failed_do_is_released_by_dev_s_own_repair(project, stage):
    """The hold on the base: every report dev may write (its own file listed, the /do's file named
    and listed too) left the do-report's gap, which only its ended producer could clear."""
    write(project, DO_REL, do_report())
    write(project, DEV_REL, dev_report(["src/b.py"]))
    state, gaps = chain(project, stage)
    assert state == "incomplete"
    assert len(gaps) == 1 and f"artifact={DEV_REL} problem=FILES_NOT_DEV_REPORT:" in gaps[0], gaps
    assert DO_REL in gaps[0] and gaps[0].endswith(f'{json.dumps(["src/a.py"])} lane=-'), gaps
    assert not any(f"artifact={DO_REL}" in gap for gap in gaps)  # nothing asks the ended /do for a write
    write(project, DEV_REL, dev_report(["src/a.py", "src/b.py"]))  # dev names src/a.py and lists it
    assert chain(project, stage) == ("chain_pass", [])


@pytest.mark.parametrize("stage", ["dev", "close"])
def test_a_do_report_that_listed_nothing_holds_nothing(project, stage):
    write(project, DO_REL, do_report(modified=()))
    write(project, DEV_REL, dev_report(["src/b.py"], created=["src/c.py"]))
    assert chain(project, stage) == ("chain_pass", [])


@pytest.mark.parametrize("stage", ["dev", "close"])
def test_the_compliant_do_task_still_passes(project, stage):
    write(project, DO_REL, do_report("completed", modified=("src/a.py",)))
    assert chain(project, stage) == ("chain_pass", [])


def test_dev_s_report_short_of_the_do_s_files_is_still_refused_naming_them(project):
    """A genuinely inconsistent conclusion: dev's report, which /commit builds its plan from, leaves
    out a file the do-report lists (created there, path absolute); one gap names dev's report and
    exactly the files it lacks."""
    write(project, DO_REL, do_report(modified=("src/a.py",), created=(str(project / "src/new.py"),)))
    write(project, DEV_REL, dev_report(["src/a.py"], created=["src/b.py"]))
    [(code, artifact, detail)] = resolver.do_report_gaps(project, TASK, project / DO_REL)
    assert (code, artifact) == ("FILES_NOT_DEV_REPORT", DEV_REL)
    assert detail.endswith(json.dumps(["src/new.py"]))
    write(project, DEV_REL, dev_report(["src/a.py"], created=["src/b.py", "src/new.py"]))
    assert resolver.do_report_gaps(project, TASK, project / DO_REL) == []


def test_dev_s_report_short_of_completed_still_holds_the_task(project):
    write(project, DO_REL, do_report())
    write(project, DEV_REL, dev_report(["src/a.py", "src/b.py"], status="blocked"))
    state, gaps = chain(project, "dev")
    assert state == "incomplete" and [g for g in gaps if f"artifact={DEV_REL} problem=INVALID_DEV_STATUS" in g]


# ---------------------------------------------------------------- the /do Stop's route (a transcript), unchanged
def transcript(path: Path, project: Path, writes) -> str:
    clock = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)
    records = [
        {"type": "queue-operation", "operation": "enqueue", "content": "/do make a change"},
        {"type": "user", "message": {"role": "user", "content": "<command-message>do is running…</command-message>\n"
                                     "<command-name>/do</command-name>\n<command-args>make a change</command-args>"}},
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": [{"type": "text", "text": "body"}]}},
        {"type": "attachment", "attachment": {"type": "hook_additional_context", "hookName": "UserPromptSubmit",
                                              "content": f"[/do] task-id minted: {TASK} — resolve via ..."}},
    ]
    for n, rel in enumerate(writes, 1):
        records.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": f"toolu_{n:04d}", "name": "Write",
             "input": {"file_path": str(project / rel), "content": "x"}}]}})
        records.append({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"toolu_{n:04d}", "content": "ok"}]}})
    with path.open("w", encoding="utf-8") as handle:
        for k, record in enumerate(records):
            record.update(timestamp=(clock + timedelta(seconds=k)).isoformat().replace("+00:00", "Z"),
                          sessionId="11111111-2222-3333-4444-555555555555")
            handle.write(json.dumps(record) + "\n")
    return str(path)


def test_the_do_stop_still_takes_lists_equal_to_the_write_set(project, tmp_path):
    tx = transcript(tmp_path / "s.jsonl", project, ["src/a.py", "src/b.py"])
    path = write(project, DO_REL, do_report("completed", modified=("src/a.py", "src/b.py")))
    assert resolver.do_report_gaps(project, TASK, path, tx) == []


def test_the_do_stop_still_refuses_lists_short_of_the_write_set(project, tmp_path):
    tx = transcript(tmp_path / "s.jsonl", project, ["src/a.py", "src/b.py"])
    path = write(project, DO_REL, do_report("completed", modified=("src/a.py",)))
    write(project, DEV_REL, dev_report(["src/a.py"]))  # a dev-report plays no part on this route
    [(code, artifact, detail)] = resolver.do_report_gaps(project, TASK, path, tx)
    assert (code, artifact) == ("FILES_NOT_WRITE_SET", DO_REL)
    assert detail.endswith(json.dumps(["src/a.py", "src/b.py"]))
