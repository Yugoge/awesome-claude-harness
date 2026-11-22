"""Three values no agent reads off a clock with a command (/dev-overnight's <TS>, /commit's manifest
time, /spec's file name): code makes each at the owner's command or at the step's own tool call, and
a value made the old way (typed by the agent) still passes.

Every run uses throwaway home, state and config directories under tmp_path.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(HOOKS))
sys.path.insert(0, str(HOOKS / "lib"))

from lib import commit_pipeline, obligation  # noqa: E402

TEMPLATE = (ROOT / "templates" / "overnight-spec.md").read_text(encoding="utf-8")


def _env(tmp_path: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_"))}
    for name in ("home", "state", "config"):
        (tmp_path / name).mkdir(exist_ok=True)
    env.update(HOME=str(tmp_path / "home"), CLAUDE_STATE_DIR=str(tmp_path / "state"),
               CLAUDE_CONFIG_DIR=str(tmp_path / "config"), TMPDIR=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    return env


# ---------------------------------------------------------------- /spec: the file name and its header


def test_spec_writer_names_the_file_with_its_own_time(tmp_path):
    slot = tmp_path / "docs" / "dev" / "specs" / "spec-<YYYYMMDD-HHMMSS>.md"
    before = datetime.now(timezone.utc).replace(microsecond=0)
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "spec-write.py"), "create", "--spec", str(slot)],
                         input=TEMPLATE, text=True, capture_output=True, env=_env(tmp_path), timeout=30)
    assert run.returncode == 0, run.stderr
    written = Path(run.stdout.strip().removeprefix("spec-write: create "))
    stamp = written.name.removeprefix("spec-").removesuffix(".md")
    at = datetime.strptime(stamp, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
    assert before <= at <= datetime.now(timezone.utc) + timedelta(seconds=1)
    text = written.read_text(encoding="utf-8")
    assert "<ISO-8601>" not in text and f"**Created**: {at.strftime('%Y-%m-%dT%H:%M:%SZ')}" in text
    assert not slot.exists()


def test_spec_writer_keeps_a_typed_name(tmp_path):
    spec = tmp_path / "docs" / "dev" / "specs" / "spec-20261028-101010.md"
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "spec-write.py"), "create", "--spec", str(spec)],
                         input=TEMPLATE, text=True, capture_output=True, env=_env(tmp_path), timeout=30)
    assert run.returncode == 0, run.stderr
    assert spec.read_text(encoding="utf-8") == TEMPLATE


# ---------------------------------------------------------------- /commit: the manifest's time


def _manifest(tmp_path, monkeypatch, sid, recorded, typed=None):
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIRS", raising=False)
    path = Path(commit_pipeline.manifest_path(sid))
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"session_id": sid, "task_id": "dev-20261121-120000"}
    if typed is not None:
        body["dispatched_at"] = typed
    path.write_text(json.dumps(body), encoding="utf-8")
    transcript = tmp_path / "config" / "projects" / "-proj" / f"{sid}.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    record = {"type": "assistant", "timestamp": recorded.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
              "message": {"content": [{"type": "tool_use", "id": "toolu_1", "name": "Write",
                                       "input": {"file_path": str(path), "content": "{}"}}]}}
    transcript.write_text(json.dumps(record) + "\n", encoding="utf-8")
    return path


def _verify(sid):
    return commit_pipeline.verify_pipeline_dispatch(sid, "dev-20261121-120000", "/nonexistent", "main", "0" * 40)


def test_a_manifest_without_a_time_takes_the_cli_record_of_its_write(tmp_path, monkeypatch):
    recorded = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=2)
    _manifest(tmp_path, monkeypatch, "s1", recorded)
    ok, reason, evidence = _verify("s1")
    assert "window" not in reason, reason  # it goes on to the plan checks
    assert commit_pipeline._parse_iso(evidence["manifest_dispatched_at"]) == recorded


def test_an_old_typed_time_is_not_judged_the_record_is(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _manifest(tmp_path, monkeypatch, "s2", now, typed=(now - timedelta(hours=8)).isoformat())  # local time typed as UTC
    assert "window" not in _verify("s2")[1]
    _manifest(tmp_path, monkeypatch, "s3", now, typed=now.isoformat())  # the old way, right
    assert "window" not in _verify("s3")[1]


def test_a_stale_record_is_refused_whatever_is_typed(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _manifest(tmp_path, monkeypatch, "s4", now - timedelta(hours=2), typed=now.isoformat())
    ok, reason, _ = _verify("s4")
    assert not ok and "the CLI's record of the Write" in reason


# ---------------------------------------------------------------- /dev-overnight: <TS>


@pytest.mark.parametrize("start", ["2026-11-21T12:34:56Z"])
def test_the_overnight_launch_prints_the_stem_of_every_ts(tmp_path, start):
    code = (
        "import importlib.util, sys\n"
        f"sys.argv = ['prompt-workflow.py']\n"
        f"spec = importlib.util.spec_from_file_location('pw', {str(HOOKS / 'prompt-workflow.py')!r})\n"
        "pw = importlib.util.module_from_spec(spec); spec.loader.exec_module(pw)\n"
        "import overnight\n"
        f"overnight.locate = lambda sid, payload: ('x', {{'start_time': {start!r}, 'worktree_path': '/w'}})\n"
        "pw.print_roots('dev-overnight', 'night1')\n"
    )
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=_env(tmp_path),
                         cwd=tmp_path, timeout=60)
    assert run.returncode == 0, run.stderr
    stem = [ln for ln in run.stdout.splitlines() if ln.startswith("RUN_STAMP=")]
    assert stem == ["RUN_STAMP=20261121-123456"], run.stdout
    for slot in ("plan", "security", "product-owner", "triage", "retro"):
        task_id = f"20261121-123456-c1-{slot}"
        assert obligation.TASK_ID_RE.fullmatch(task_id) and obligation.task_stamp(task_id) == "20261121-123456"


def test_a_typed_ts_still_is_a_task_id():
    assert obligation.TASK_ID_RE.fullmatch("20261121-123456")
