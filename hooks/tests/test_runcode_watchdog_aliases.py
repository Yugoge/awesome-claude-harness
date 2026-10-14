"""Direct lifecycle parity tests for both browser run-code provider names."""

import importlib.util
import io
import json
import shutil
import subprocess
import sys
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


PLAYWRIGHT_MATCHER = "mcp__playwright__browser_run_code"
PASEO_MATCHER = "mcp__paseo__browser_run_code"
WATCHDOG_HOOKS = {
    "PreToolUse": "pretool-runcode-watchdog.py",
    "PostToolUse": "posttool-runcode-watchdog.py",
}


def _watchdog_groups(settings, event):
    script = WATCHDOG_HOOKS[event]
    return [
        group for group in settings["hooks"][event]
        if any(script in hook.get("command", "") for hook in group.get("hooks", []))
    ]


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, timeout=60,
                          check=False)


def _clean_form_text():
    """The tracked clean form of settings.json. In a checkout whose settings filter is
    registered the working file is the machine form, so read the index blob (else HEAD's);
    outside a git checkout the working file is the clean form."""
    try:
        top = _git("rev-parse", "--show-toplevel")
        if top.returncode == 0 and Path(top.stdout.decode().strip()).resolve() == ROOT:
            for spec in (":settings.json", "HEAD:settings.json"):
                blob = _git("show", spec)
                if blob.returncode == 0:
                    return blob.stdout.decode("utf-8")
    except (OSError, subprocess.SubprocessError):
        pass
    return (ROOT / "settings.json").read_text(encoding="utf-8")


def _smudge(tmp_path, overlay):
    """Render the machine form of the tracked clean form with render-settings smudge,
    run from an isolated copy whose home holds only the given overlay."""
    home = tmp_path / "render-home"
    script = home / "scripts" / "install" / "render-settings"
    script.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "install" / "render-settings", script)
    (home / "settings.machine.json").write_text(json.dumps(overlay), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(script), "smudge"],
        input=_clean_form_text().encode("utf-8"),
        capture_output=True, cwd=home, timeout=60, check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert b"render-settings:" not in proc.stderr, proc.stderr.decode("utf-8", "replace")
    return json.loads(proc.stdout.decode("utf-8"))


def test_clean_settings_register_the_playwright_watchdog_only():
    clean = json.loads(_clean_form_text())
    allow = clean["permissions"]["allow"]
    assert "mcp__playwright__*" in allow
    assert "mcp__paseo__*" not in allow
    for event in WATCHDOG_HOOKS:
        groups = _watchdog_groups(clean, event)
        assert len(groups) == 1, (event, groups)
        assert groups[0].get("matcher") == PLAYWRIGHT_MATCHER
        assert len(groups[0]["hooks"]) == 1


def test_paseo_module_render_adds_the_paseo_alternative(tmp_path):
    rendered = _smudge(tmp_path, {"modules": {"paseo": True}})
    assert {"mcp__playwright__*", "mcp__paseo__*"} <= set(rendered["permissions"]["allow"])
    for event in WATCHDOG_HOOKS:
        groups = _watchdog_groups(rendered, event)
        assert len(groups) == 1, (event, groups)
        assert groups[0].get("matcher") == f"{PLAYWRIGHT_MATCHER}|{PASEO_MATCHER}"
        assert len(groups[0]["hooks"]) == 1


def test_render_without_the_paseo_module_keeps_the_clean_matchers(tmp_path):
    rendered = _smudge(tmp_path, {"modules": {"paseo": False}})
    assert "mcp__paseo__*" not in rendered["permissions"]["allow"]
    for event in WATCHDOG_HOOKS:
        groups = _watchdog_groups(rendered, event)
        assert len(groups) == 1, (event, groups)
        assert groups[0].get("matcher") == PLAYWRIGHT_MATCHER
