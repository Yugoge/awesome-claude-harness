"""The stamp of a /dev-overnight cycle's pipelines is code's, one per cycle (commands/dev-overnight.md Step 6).

Step 6's builder call, run as the text writes it, passes `-` for the stamp: scripts/build-pipelines-from-triage.py
takes the created_at of the cycle's contract, which hooks/posttool-subagent-track.py writes once per cycle when PM
TRIAGE returns, always later than the previous cycle's. So no agent types a time, every reader of a cycle sees one
stamp, and two cycles of one run never share one: the dev-report aggregation (scripts/aggregate-dev-report.py), which
keys a task on its stamp, keeps their pipelines apart. A call with a typed stamp (the text of earlier sessions) still
builds `<ts>-<index>`. Throwaway roots only; neutral values.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
REPO = HOOKS.parent
BUILDER = REPO / "scripts" / "build-pipelines-from-triage.py"
SID = "sess-pipeline-stamp"
sys.path.insert(0, str(HOOKS))
from lib import contract_runtime  # noqa: E402

LABELS = [label for label, _call in contract_runtime.overnight_steps()]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _iso(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def root(tmp_path):
    """A project that is its own working root, with the session's overnight record."""
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    root = tmp_path / "main"
    root.mkdir()
    for args in (["init", "-q", "-b", "trunk"], ["commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True, timeout=30)
    (root / ".claude").mkdir()
    record = {"session_id": SID, "end_time": _iso(60), "current_phase": "exploring", "isolation_active_until": _iso(60),
              "isolation_released_at": None, "protected_branch": "trunk", "main_root": str(root),
              "worktree_path": str(root), "addressed_issues": []}
    (root / ".claude" / f"overnight-state-{SID}.json").write_text(json.dumps(record))
    return root


def _transcript(root: Path, cycles: int) -> None:
    """/dev-overnight, then a checklist per cycle, the last at Step 4 (PM TRIAGE) in progress."""
    def todos(current=None, done_all=False):
        before, out = True, []
        for n in LABELS:
            before = before and n != current
            status = "in_progress" if n == current else "completed" if done_all or (before and current) else "pending"
            out.append({"content": f"Step {n}: x", "activeForm": f"Step {n}", "status": status})
        return out
    lists = [todos()]
    for _ in range(cycles - 1):
        lists += [todos(LABELS[-1]), todos(done_all=True), todos()]
    lists.append(todos("4"))
    records = [{"type": "user", "uuid": "u-open", "message": {"role": "user", "content": "/dev-overnight 2h"}}]
    for n, item in enumerate(lists):
        records += [{"type": "assistant", "message": {"role": "assistant", "content": [
                        {"type": "tool_use", "id": f"tw{n}", "name": "TodoWrite", "input": {"todos": item}}]}},
                    {"type": "user", "message": {"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": f"tw{n}", "content": "ok"}]}}]
    (root / "transcript.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))


def _cycle(root: Path, n: int) -> Path:
    """Cycle n's PM TRIAGE returns (its report on disk, then the hook's run); the earlier cycles ended (retros)."""
    base = root / "docs" / "dev" / "overnight" / SID
    base.mkdir(parents=True, exist_ok=True)
    for done in range(1, n):
        (base / f"retro-report-cycle{done}.json").write_text("{}")
    issues = [{"triage_index": i, "pipeline_recommendation": "fix", "description": f"c{n} d{i}", "location": f"l{i}"}
              for i in range(2)]
    triage = base / f"triage-report-cycle{n}.json"
    triage.write_text(json.dumps({"issues": issues, "pipeline_order": [0, 1]}))
    _transcript(root, n)
    payload = {"session_id": SID, "tool_name": "Agent", "cwd": str(root), "transcript_path": str(root / "transcript.jsonl"),
               "tool_input": {"subagent_type": "pm", "prompt": "PM_MODE: TRIAGE", "description": "x"}}
    hook = subprocess.run([sys.executable, str(HOOKS / "posttool-subagent-track.py")], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=str(root), timeout=60,
                          env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)})
    assert hook.returncode == 0 and (base / f"cycle-{n}" / "cycle-contract.json").is_file(), hook.stdout + hook.stderr
    return triage


def _step6(root: Path, triage: Path) -> list[dict]:
    """Step 6's builder call as commands/dev-overnight.md writes it, its placeholders bound as the session binds them."""
    text = (REPO / "commands" / "dev-overnight.md").read_text(encoding="utf-8")
    step = text[text.index("### Step 6"):text.index("### Step 7")]
    [call] = [b for b in re.findall(r"```bash\n(.*?)\n```", step, re.S) if "build-pipelines-from-triage.py" in b]
    for slot, value in (("<HARNESS_ROOT>", str(REPO)), ("<triage-report>", str(triage)),
                        ("<addressed-issues>", "<(echo '[]')"), ("<session_id>", SID)):
        call = call.replace(slot, value)
    run = subprocess.run(["bash", "-c", call], capture_output=True, text=True, cwd=str(root), timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads((root / "docs" / "dev" / "overnight" / SID / "pipelines.json").read_text())


def _stamp(created_at: str) -> str:
    return re.sub(r"[-:Z]", "", created_at).replace("T", "-")


def test_two_cycles_of_one_run_get_their_own_stamp_from_code(root):
    stamps = []
    for n in (1, 2):
        pipes = _step6(root, _cycle(root, n))
        contract = json.loads((root / "docs" / "dev" / "overnight" / SID / f"cycle-{n}" / "cycle-contract.json")
                              .read_text())
        assert [p["timestamp_suffix"] for p in pipes] == [f"{_stamp(contract['created_at'])}-{j}" for j in (0, 1)]
        stamps.append(_stamp(contract["created_at"]))
    assert stamps[0] != stamps[1] and stamps[0] < stamps[1], stamps  # even when both hook runs fall in one second


def test_the_aggregation_keeps_the_pipelines_of_two_cycles_apart(root):
    agg = _load("scripts/aggregate-dev-report.py", "aggregate_pipeline_cycle_stamp")
    ids = [p["timestamp_suffix"] for n in (1, 2) for p in _step6(root, _cycle(root, n))]
    dev = root / "docs" / "dev"
    for task_id in ids:
        (dev / f"dev-report-{task_id}-l1.json").write_text(json.dumps({"task_id": f"{task_id}-l1"}))
    for task_id in ids:
        lanes = sorted(p.name for _, p in agg._scan_shards(dev, agg._bare_task_id(task_id), task_id))
        assert lanes == [f"dev-report-{task_id}-l1.json"], (task_id, lanes)
    assert agg._bare_task_id(ids[0]) == agg._bare_task_id(ids[1]) != agg._bare_task_id(ids[2])


def test_a_typed_stamp_still_builds_its_pipelines(tmp_path):
    triage = tmp_path / "triage.json"
    triage.write_text(json.dumps({"issues": [{"triage_index": 0, "pipeline_recommendation": "fix"}]}))
    (tmp_path / "addressed.json").write_text("[]")
    out = subprocess.run([sys.executable, str(BUILDER), str(triage), str(tmp_path / "addressed.json"),
                          "20990101-000000", "s1"], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and json.loads(out.stdout)[0]["timestamp_suffix"] == "20990101-000000-0", out.stderr


def test_without_its_cycle_contract_the_builder_names_what_is_missing(tmp_path):
    triage = tmp_path / "triage-report-cycle3.json"
    triage.write_text(json.dumps({"issues": []}))
    (tmp_path / "addressed.json").write_text("[]")
    out = subprocess.run([sys.executable, str(BUILDER), str(triage), str(tmp_path / "addressed.json"), "-", "s1"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode != 0 and "cycle-3/cycle-contract.json" in out.stderr and not out.stdout, out
