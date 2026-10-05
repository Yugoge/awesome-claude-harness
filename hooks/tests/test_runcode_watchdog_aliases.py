"""Direct lifecycle parity tests for both browser run-code provider names."""

import importlib.util
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PRE = _load("pretool_runcode_watchdog", ROOT / "hooks/pretool-runcode-watchdog.py")
POST = _load("posttool_runcode_watchdog", ROOT / "hooks/posttool-runcode-watchdog.py")
ALIASES = ("mcp__playwright__browser_run_code", "mcp__paseo__browser_run_code")


@pytest.mark.parametrize("tool_name", ALIASES)
def test_each_alias_starts_exactly_one_watchdog(monkeypatch, tool_name):
    starts = []
    stale = []
    monkeypatch.setattr(PRE.sys, "stdin", io.StringIO(json.dumps({"tool_name": tool_name})))
    monkeypatch.setattr(PRE, "_kill_stale_watchdog", lambda path: stale.append(path))
    monkeypatch.setattr(PRE.subprocess, "Popen", lambda *a, **k: starts.append((a, k)))
    with pytest.raises(SystemExit) as exc:
        PRE.main()
    assert exc.value.code == 0
    assert len(stale) == 1
    assert len(starts) == 1


@pytest.mark.parametrize("tool_name", ALIASES)
def test_each_alias_cancels_and_checks_exactly_once(monkeypatch, tool_name):
    cancelled = []
    markers = []
    monkeypatch.setattr(POST.sys, "stdin", io.StringIO(json.dumps({"tool_name": tool_name})))
    monkeypatch.setattr(POST.os.path, "exists", lambda path: True)
    monkeypatch.setattr(POST, "_cancel_watchdog", lambda path: cancelled.append(path))
    monkeypatch.setattr(POST, "_check_timeout_marker", lambda path: markers.append(path))
    with pytest.raises(SystemExit) as exc:
        POST.main()
    assert exc.value.code == 0
    assert len(cancelled) == len(markers) == 1


@pytest.mark.parametrize("module", (PRE, POST))
def test_unrelated_tool_is_inert(monkeypatch, module):
    actions = []
    monkeypatch.setattr(
        module.sys,
        "stdin",
        io.StringIO(json.dumps({"tool_name": "mcp__paseo__browser_navigate"})),
    )
    if module is PRE:
        monkeypatch.setattr(module, "_kill_stale_watchdog", lambda path: actions.append(path))
        monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: actions.append(a))
    else:
        monkeypatch.setattr(module, "_cancel_watchdog", lambda path: actions.append(path))
        monkeypatch.setattr(module, "_check_timeout_marker", lambda path: actions.append(path))
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 0
    assert actions == []


def test_template_and_live_settings_preserve_full_alias_parity():
    template_text = (ROOT / "settings.template.json").read_text()
    template = json.loads(template_text)
    live = json.loads((ROOT / "settings.json").read_text())
    rendered = json.loads(template_text.replace("{{CLAUDE_HOME}}", "/root/.claude"))
    assert live == rendered
    assert {"mcp__playwright__*", "mcp__paseo__*"} <= set(
        template["permissions"]["allow"]
    )
    matcher = "mcp__playwright__browser_run_code|mcp__paseo__browser_run_code"
    for event in ("PreToolUse", "PostToolUse"):
        matching = [group for group in template["hooks"][event] if group.get("matcher") == matcher]
        assert len(matching) == 1
