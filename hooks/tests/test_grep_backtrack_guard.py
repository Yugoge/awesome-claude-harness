"""Freeze safe grep shapes and the catastrophic embedded-engine control."""

import importlib.util
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "hooks/pretool-grep-backtrack-guard.py"
SPEC = importlib.util.spec_from_file_location("grep_backtrack_guard", PATH)
GUARD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(GUARD)


def _run(monkeypatch, command):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    monkeypatch.setattr(GUARD.sys, "stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc:
        GUARD.main()
    return exc.value.code


@pytest.mark.parametrize(
    "command",
    (
        "grep -E 'bounded.{0,10}value' README.md",
        "/usr/bin/grep -E 'a.*b.*c' README.md",
        "grep -F 'a.*b.*c' README.md",
    ),
)
def test_safe_current_controls_allow_without_probe(monkeypatch, command):
    monkeypatch.setattr(GUARD, "probe_explodes", lambda *a: (_ for _ in ()).throw(AssertionError()))
    assert _run(monkeypatch, command) == 0


def test_catastrophic_shape_blocks_when_same_engine_probe_explodes(monkeypatch):
    monkeypatch.setattr(GUARD, "probe_explodes", lambda *a: True)
    assert _run(monkeypatch, "grep -E 'a.*b.*c' README.md") == 2
