"""prompt-workflow.py replays an exact /dev, /dev-command or /redev start
envelope only while its replay record is younger than 60 s, judged by the
record file's own mtime; after that the same text starts a new cycle (P3 R10).
/redev mints a fresh task id exactly as /dev (D22). Before R10 an identical
bare /redev replayed the first cycle's output for ever, unless that cycle's
dev-report had reached a terminal status (that case now lives in
test_dual_runtime_lifecycle_e2e.py).

Run with: python3 -m pytest hooks/tests/test_prompt_workflow_replay_window.py -v
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[2]
HOOKS = SOURCE_ROOT / "hooks"
PROMPT = HOOKS / "prompt-workflow.py"
SID = "replay-window"


def _project(tmp_path: Path, name: str = "project") -> Path:
    root = tmp_path / name
    (root / "scripts" / "todo").mkdir(parents=True)
    for script in ("dev.py", "redev.py"):
        shutil.copy2(SOURCE_ROOT / "scripts" / "todo" / script, root / "scripts" / "todo" / script)
    return root


def _payload(root: Path, prompt: str) -> bytes:
    return json.dumps({"session_id": SID, "cwd": str(root), "prompt": prompt}).encode("utf-8")


def _start(root: Path, prompt: str, clock: str = "") -> subprocess.CompletedProcess:
    """One UserPromptSubmit through the hook's real entry point."""
    env = {**os.environ, "HOME": str(root), "CLAUDE_CONFIG_DIR": str(root / ".claude"),
           "CLAUDE_PROJECT_DIR": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("CLAUDE_DEV_CLOCK_ISO", None)
    if clock:
        env["CLAUDE_DEV_CLOCK_ISO"] = clock
    result = subprocess.run([sys.executable, str(PROMPT)], input=_payload(root, prompt),
                            capture_output=True, env=env, check=False)
    assert result.returncode == 0, result.stderr
    assert b"Traceback" not in result.stderr, result.stderr
    return result


def _ids(root: Path) -> list[str]:
    return sorted(p.name for p in (root / ".claude" / "dev-registry").iterdir())


def _record(root: Path, prompt: str) -> Path:
    digest = hashlib.sha256(_payload(root, prompt)).hexdigest()
    return root / ".claude" / "dev-start-replays" / SID / f"{digest}.json"


def _age(path: Path, seconds: int) -> None:
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns - seconds * 10**9))


def _identity(task_id: str) -> bytes:
    return f"DEV_SESSION_ID pre-initialized by hook: {task_id}\n".encode()


def test_bare_redev_twice_within_60s_prints_the_first_output_byte_for_byte(tmp_path):
    root = _project(tmp_path)
    first = _start(root, "/redev")
    second = _start(root, "/redev")

    [task_id] = _ids(root)
    assert _identity(task_id) in first.stdout
    assert (second.stdout, second.stderr) == (first.stdout, first.stderr)
    assert _ids(root) == [task_id]


def test_bare_redev_after_its_record_aged_120s_starts_a_new_cycle(tmp_path):
    root = _project(tmp_path)
    _start(root, "/redev")
    [old_id] = _ids(root)
    _age(_record(root, "/redev"), 120)

    later = _start(root, "/redev")

    [new_id] = set(_ids(root)) - {old_id}
    assert _identity(new_id) in later.stdout
    assert old_id.encode() not in later.stdout
    # the new start's record is fresh, so the same envelope now replays it
    assert _start(root, "/redev").stdout == later.stdout
    assert len(_ids(root)) == 2


@pytest.mark.parametrize("record", [
    {"schema": "claude.ordinary-dev-start-replay/v1", "session_id": SID, "task_id": "dev-20261001-000000",
     "workflow_generation": 1, "stdout": "DEV_SESSION_ID pre-initialized by hook: dev-20261001-000000\n",
     "stderr": ""},
    {"schema": "claude.ordinary-dev-start-replay/v1", "task_id": "dev-20261001-000000"},
], ids=["well-formed", "no-stdout"])
def test_a_record_older_code_left_over_60s_ago_starts_a_new_cycle(tmp_path, record):
    root = _project(tmp_path)
    path = _record(root, "/redev")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))
    _age(path, 3600)

    started = _start(root, "/redev")

    [task_id] = _ids(root)
    assert _identity(task_id) in started.stdout
    assert b"dev-20261001-000000" not in started.stdout
    assert json.loads(path.read_text())["task_id"] == task_id


def test_redev_mints_a_fresh_id_exactly_as_dev(tmp_path):
    named = "dev-20261030-120000"
    seen = {}
    for command in ("dev", "redev"):
        root = _project(tmp_path, command)
        (root / ".claude" / "dev-registry" / named).mkdir(parents=True)
        # the clock's own second is the named task's id, already taken
        started = _start(root, f"/{command} {named}", clock="2026-10-30T12:00:00")
        fresh = sorted(set(_ids(root)) - {named})
        seen[command] = (
            started.stdout.replace(f"/{command.upper()}:".encode(), b"/DEV:"),
            fresh,
            sorted(p.name for p in (root / ".claude" / "dev-registry" / fresh[0]).iterdir()),
        )
    assert seen["redev"] == seen["dev"]
    assert seen["dev"][1] == ["dev-20261030-120001"]
    assert _identity("dev-20261030-120001") in seen["dev"][0]


class _FrozenTime:
    """The time module with time() held at one instant."""

    def __init__(self, now: float):
        self._now = now

    def time(self) -> float:
        return self._now

    def __getattr__(self, name):
        return getattr(time, name)


@pytest.mark.parametrize("age, replayed", [(59, True), (60, False)])
def test_the_replay_window_is_strictly_younger_than_60s(tmp_path, monkeypatch, capsys, age, replayed):
    monkeypatch.syspath_prepend(str(HOOKS))  # the hook loads its library as lib.<module>
    spec = importlib.util.spec_from_file_location("replay_window_prompt_workflow", PROMPT)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    ids = iter(["dev-20261030-000000", "dev-20261030-000001"])
    monkeypatch.setattr(hook, "PROJECT_DIR", tmp_path)
    monkeypatch.setattr(hook, "run_todo_script",
                        lambda cmd, prompt: [{"content": "Step 0", "status": "pending", "activeForm": "Step 0"}])
    monkeypatch.setattr(hook, "_check_workflow_conflict", lambda cmd: None)
    monkeypatch.setattr(hook, "_init_dev_registry", lambda cmd, prompt, sid, project: next(ids))
    monkeypatch.setattr(hook, "_start_identity", lambda task_id: f"Task id: {task_id}\n")
    monkeypatch.setattr(hook, "decide_spec_path", lambda explicit, sid: ("", "Spec: none"))

    hook._ordinary_dev_start("redev", "/redev", SID, "d1")
    first = capsys.readouterr().out
    now = 1_800_000_000
    os.utime(hook._dev_replay_path(SID, "d1"), (now - age, now - age))
    monkeypatch.setattr(hook, "time", _FrozenTime(float(now)))
    hook._ordinary_dev_start("redev", "/redev", SID, "d1")
    again = capsys.readouterr().out

    assert (again == first) is replayed
    assert ("Task id: dev-20261030-000001" in again) is not replayed
