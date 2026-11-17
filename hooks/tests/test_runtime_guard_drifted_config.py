#!/usr/bin/env python3
"""A drifted protected-runtime file no longer wedges node/npm; an unusable one names its repair.

A schema-1 file that lacks some REQUIRED_KEYS lists (written before a key existed, or
hand-edited) is read with those keys as empty lists, which is exactly what
`scripts/bootstrap --steps 4` writes when it repairs the file: every entry the file
declares is still enforced and nothing more is assumed. Any other unusable file (absent,
not JSON, not an object, another schema_version, a key that is not a list) stays
fail-closed (STEP1), and the refusal now names the defect and the recovery without the
file's resolved path.

Every case runs the real hook entry (hooks/pretool-bash-safety.sh) on a PreToolUse
payload, with a throwaway HOME, state dir and data file under pytest's tmp_path.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

HOOKS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HOOK = os.path.join(HOOKS, "pretool-bash-safety.sh")

FULL = {"schema_version": 1, **{k: [] for k in (
    "protected_cmds", "protected_launch_paths", "protected_services",
    "protected_hotfiles", "protected_statefiles", "protected_endpoint_paths",
    "protected_proc_idents", "protected_global_bins",
    "protected_build_workspaces", "protected_build_paths")}}


@pytest.fixture
def guard(tmp_path):
    home, state, work = tmp_path / "home", tmp_path / "state", tmp_path / "work"
    for d in (home, state, work):
        d.mkdir()
    data = tmp_path / "pr.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "GIT_"))}
    env.update(HOME=str(home), CLAUDE_STATE_DIR=str(state), CLAUDE_PROTECTED_RUNTIME_FILE=str(data),
               GIT_CONFIG_GLOBAL=str(tmp_path / "gitconfig"), GIT_CONFIG_NOSYSTEM="1")

    def run(content, command):
        if content is None:
            if data.exists():
                data.unlink()
        else:
            data.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command, "cwd": str(work)}})
        return subprocess.run(["bash", HOOK], input=payload, text=True, capture_output=True,
                              cwd=str(work), env=env, timeout=120)

    run.tmp = str(tmp_path)
    return run


# ── Red on the base: a schema-1 file missing keys refused every node/npm command ──

@pytest.mark.parametrize("command", ["node --version", "npm test", "npx --version", "ls"])
def test_schema1_file_missing_keys_does_not_wedge_node_or_npm(guard, command):
    proc = guard({"schema_version": 1}, command)
    assert proc.returncode == 0, proc.stderr


def test_partial_file_matches_the_full_file_bootstrap_would_write(guard):
    partial = {"schema_version": 1, "protected_services": ["demo-daemon"]}
    full = dict(FULL, protected_services=["demo-daemon"])
    for command in ("node --version", "npm run build", "systemctl restart demo-daemon"):
        a, b = guard(partial, command), guard(full, command)
        assert (a.returncode, a.stderr) == (b.returncode, b.stderr), command


# ── Protection the file declares is never lost ───────────────────────────────

@pytest.mark.parametrize("command", ["systemctl restart demo-daemon", "sudo systemctl stop demo-daemon.service"])
def test_declared_service_in_a_partial_file_is_still_enforced(guard, command):
    proc = guard({"schema_version": 1, "protected_services": ["demo-daemon"]}, command)
    assert proc.returncode == 2
    assert "protected-runtime-guard" in proc.stderr and "STEP1" not in proc.stderr


# ── Must still refuse: unusable files stay fail-closed, now with the cause and recovery ──

@pytest.mark.parametrize("content,cause", [
    ({"schema_version": 2, **{k: v for k, v in FULL.items() if k != "schema_version"}},
     "the file has schema_version 2; this guard reads only schema_version 1"),
    ("{ not json", "the file is not valid JSON"),
    ("[1, 2]", "the file's top level is not a JSON object"),
    ({"protected_cmds": []}, "the file has no schema_version"),
    ({"schema_version": "1"}, "has a schema_version that is not an integer"),
    (dict(FULL, protected_services="demo-daemon"), "key(s) protected_services are not JSON lists"),
    ({"schema_version": 1, "protected_cmds": {"a": 1}}, "key(s) protected_cmds are not JSON lists"),
])
@pytest.mark.parametrize("command", ["node --version", "npm test", "systemctl restart demo-daemon"])
def test_unusable_file_stays_fail_closed_and_names_cause_and_recovery(guard, content, cause, command):
    proc = guard(content, command)
    assert proc.returncode == 2, proc.stderr
    assert "BLOCK STEP1: indeterminate policy" in proc.stderr
    assert cause in proc.stderr
    assert "scripts/bootstrap --steps 4" in proc.stderr and '"schema_version": 1' in proc.stderr
    assert "its policy file is unusable" in proc.stderr
    assert guard.tmp not in proc.stderr, "no resolved private path in the refusal"


def test_absent_file_stays_fail_closed_and_names_the_create_step(guard):
    proc = guard(None, "node --version")
    assert proc.returncode == 2
    assert "the file does not exist" in proc.stderr
    assert "run `scripts/bootstrap --steps 4` from the harness home" in proc.stderr
    assert guard.tmp not in proc.stderr


@pytest.mark.parametrize("content", ['{"schema_version": 2}', "{ not json", None])
def test_commands_outside_the_families_still_run_on_an_unusable_file(guard, content):
    assert guard(content, "ls").returncode == 0
