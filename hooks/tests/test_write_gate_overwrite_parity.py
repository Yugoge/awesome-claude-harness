"""lib/write_gate/overwrite.py decides as hooks/pretool-write-guard.sh did, message for message.

The write gate runs the Python form. The shell hook is an exit-0 stub since the gate's registration
landed (D15), so it runs here as the P12 base shipped it (hooks/tests/retired_hooks.py). Both run as
processes, on one corpus: the main agent and a subagent,
/do consent on and off, an /allow grant naming the target, naming another one, or none,
an existing and a new file, the bulk-commit sentinel's name, NotebookEdit, other tools,
and payloads that do not parse. Each case must give the same exit status, stderr and stdout.
"""
from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import retired_hooks

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / "hooks" / "lib" / "write_gate" / "overwrite.py"
SID = "sess-overwrite-parity"


def _env(tmp_path: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
    env.update(HOME=str(tmp_path / "home"), CLAUDE_STATE_DIR=str(tmp_path / "state"),
               CLAUDE_HOME=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    return env


def _run(cmd, raw: str, env: dict, cwd: Path):
    p = subprocess.run(cmd, input=raw, capture_output=True, text=True, env=env, cwd=cwd, timeout=60)
    return p.returncode, p.stderr, p.stdout


def _setup(tmp_path: Path, consent: bool, grant: str | None, existing: Path, new: Path):
    state = tmp_path / "state"
    (state / "claude-grants").mkdir(parents=True, exist_ok=True)
    (tmp_path / "home").mkdir(exist_ok=True)
    flag = state / f"claude-orchestrator-consent-{SID}.flag"
    if consent:
        flag.write_text("true\n")
    elif flag.exists():
        flag.unlink()
    gfile = state / "claude-grants" / f"{SID}.json"
    if gfile.exists():
        gfile.unlink()
    if grant is not None:
        target = {"existing": str(existing), "other": str(new.with_name("other.txt")), "bare": None}[grant]
        op = {"op": "Write"} if target is None else {"op": "Write", "target": target}
        gfile.write_text(json.dumps({"task_id": SID, "session_id": SID, "allowed_operations": [op],
                                     "created_at": int(time.time()), "expires_at": int(time.time()) + 300}))


def _payloads(existing: Path, new: Path, sentinel: Path):
    for tool, target, agent in itertools.product(
            ("Write", "NotebookEdit", "Edit", "Bash"), (existing, new, sentinel), (None, "a1")):
        key = "notebook_path" if tool == "NotebookEdit" else "file_path"
        d = {"tool_name": tool, "session_id": SID, "tool_input": {key: str(target), "content": "x"}}
        if agent:
            d["agent_id"] = agent
        yield json.dumps(d)
    yield json.dumps({"tool_name": "Write", "session_id": SID, "tool_input": {"file_path": None}})
    yield json.dumps({"tool_name": "Write", "session_id": SID, "tool_input": {}})
    yield json.dumps({"tool_name": "Write", "session_id": SID, "tool_input": "not-a-dict"})
    yield json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(existing)}})  # no session id
    yield json.dumps({"tool_name": "Write", "session_id": SID, "task_id": SID,
                      "tool_input": {"file_path": "relative-existing.txt"}})
    yield json.dumps(["not", "an", "object"])
    yield "{not json"
    yield ""


@pytest.mark.parametrize("consent", [False, True])
@pytest.mark.parametrize("grant", [None, "existing", "other", "bare"])
def test_the_port_answers_as_the_shell_hook(tmp_path, consent, grant):
    proj = tmp_path / "proj"
    proj.mkdir()
    existing = proj / "existing.txt"
    existing.write_text("old\n")
    (proj / "relative-existing.txt").write_text("old\n")
    new = proj / "new.txt"
    sentinel = tmp_path / "state" / "claude-bulk-commit-sentinel-s-n.json"
    _setup(tmp_path, consent, grant, existing, new)
    env = _env(tmp_path)
    compared = 0
    shell_hook = retired_hooks.materialize("pretool-write-guard.sh", tmp_path / "retired")
    for raw in _payloads(existing, new, sentinel):
        shell = _run(["bash", str(shell_hook)], raw, env, proj)
        port = _run([sys.executable, str(PORT)], raw, env, proj)
        assert port == shell, raw
        compared += 1
    assert compared == 32


def test_the_corpus_reaches_every_decision(tmp_path):
    """The corpus is not vacuous: across consent and grants it meets each refusal and each allow."""
    proj = tmp_path / "proj"
    proj.mkdir()
    existing, new = proj / "existing.txt", proj / "new.txt"
    existing.write_text("old\n")
    sentinel = tmp_path / "state" / "claude-bulk-commit-sentinel-s-n.json"
    seen = set()
    for consent, grant in itertools.product((False, True), (None, "existing", "other")):
        _setup(tmp_path, consent, grant, existing, new)
        for raw in _payloads(existing, new, sentinel):
            rc, err, _ = _run([sys.executable, str(PORT)], raw, _env(tmp_path), proj)
            seen.add((rc, err.splitlines()[0][:40] if err else ""))
    firsts = {first for rc, first in seen if rc == 2}
    assert any(f.startswith("BLOCKED: bulk-commit-sentinel-write") for f in firsts)
    assert any(f.startswith("[Write Guard] BLOCKED: File already exi") for f in firsts)
    assert any(f.startswith("[Write Guard] BLOCKED: sentinel grant d") for f in firsts)
    assert (0, "") in seen
