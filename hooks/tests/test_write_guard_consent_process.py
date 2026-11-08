"""hooks/pretool-write-guard.sh takes the /do consent decision in the interpreter it already starts.

The /do bypass is hooks/lib/allowlist.py has_do_consent (main agent only); the hook takes it in the same
python3 process that reads whether a subagent calls, so a Write starts one interpreter less (P1b latency,
review item 2). The decisions stay as they were: consent lets any Write through, a subagent never holds
consent, and a Write onto an existing file without it is refused. Each case runs the real hook under bash
with a sandboxed home and state directory; a python3 shim first on PATH counts the interpreters it starts.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-write-guard.sh"
SID = "sess-write-guard-consent"


def _run(tmp_path: Path, payload, consent: bool):
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    flag = state / f"claude-orchestrator-consent-{SID}.flag"
    if consent:
        flag.write_text("true\n")
    elif flag.exists():
        flag.unlink()
    shim = tmp_path / "bin"
    shim.mkdir(exist_ok=True)
    log = tmp_path / "python3.log"
    (shim / "python3").write_text(f'#!/bin/sh\necho x >> "{log}"\nexec "{sys.executable}" "$@"\n')
    (shim / "python3").chmod(0o755)
    if log.exists():
        log.unlink()
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update({"HOME": str(tmp_path / "home"), "CLAUDE_STATE_DIR": str(state), "PYTHONDONTWRITEBYTECODE": "1",
                "PATH": f"{shim}{os.pathsep}{env.get('PATH', '/usr/bin:/bin')}"})
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    proc = subprocess.run(["bash", str(HOOK)], input=raw, capture_output=True, text=True, env=env,
                          cwd=str(tmp_path), timeout=60)
    starts = len(log.read_text().splitlines()) if log.exists() else 0
    return proc.returncode, proc.stderr, starts


def _write(path: Path, **extra) -> dict:
    return {"session_id": SID, "tool_name": "Write", "tool_input": {"file_path": str(path), "content": "x"}, **extra}


@pytest.fixture()
def existing(tmp_path):
    path = tmp_path / "exists.txt"
    path.write_text("old")
    return path


def test_consent_lets_the_main_agents_overwrite_through(tmp_path, existing):
    assert _run(tmp_path, _write(existing), consent=True)[0] == 0
    rc, err, _ = _run(tmp_path, _write(existing), consent=False)
    assert rc == 2 and "File already exists" in err


@pytest.mark.parametrize("agent_id", ["a1", "0"])
def test_consent_is_the_main_agents_alone(tmp_path, existing, agent_id):
    # has_do_consent reads "0" as no agent id (lib.subagent), while the guard's own subagent test reads
    # any id; both readings stay as they were.
    rc, err, _ = _run(tmp_path, _write(existing, agent_id=agent_id), consent=True)
    assert (rc, "File already exists" in err) == ((2, True) if agent_id == "a1" else (0, False))


def test_one_interpreter_decides_consent_and_the_caller(tmp_path):
    # A new file's Write: the tool name, the bulk-sentinel target, the path, the task id, then consent and
    # the caller in one process; the main agent adds its session id and the sentinel-grant lookup.
    new = tmp_path / "new.txt"
    assert _run(tmp_path, _write(new, agent_id="a1"), consent=False)[::2] == (0, 5)
    assert _run(tmp_path, _write(new), consent=False)[::2] == (0, 7)
    assert _run(tmp_path, _write(new), consent=True)[::2] == (0, 5)
