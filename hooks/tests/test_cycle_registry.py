#!/usr/bin/env python3
"""The cycle's identity and registry have one producer (P1b Scope row 1).

hooks/prompt-workflow.py mints the task id at UserPromptSubmit and arms the
registry (one sentinel per role of the roster hooks/lib/roster.py computes from
agents/*.md, the user-requirement document, the enforcement flags). The main
agent that no longer holds the hook's output, or never got it, runs the same
start through `prompt-workflow.py start`; the overnight initializer arms its
registry through `prompt-workflow.py arm-registry`; command text that needs a
task's registry name asks `prompt-workflow.py registry-dir`. No command text
mints an id or writes a registry, requirement or flag itself.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "prompt-workflow.py"
OVERNIGHT_INIT = REPO_ROOT / "scripts" / "overnight-init.sh"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROSTER = _load("roster_under_test", REPO_ROOT / "hooks" / "lib" / "roster.py")


@pytest.fixture()
def env(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    values = dict(os.environ)
    values.update({
        "HOME": str(home),
        "CLAUDE_CONFIG_DIR": str(home / ".claude"),
        "CLAUDE_PROJECT_DIR": str(project),
        "CLAUDE_STATE_DIR": str(tmp_path / "state"),
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    values.pop("CLAUDE_CODE_SESSION_ID", None)
    values.pop("CLAUDE_SESSION_ID", None)
    return project, values


def _hook(project: Path, env: dict, sid: str, prompt: str) -> subprocess.CompletedProcess:
    payload = {"session_id": sid, "cwd": str(project), "prompt": prompt,
               "hook_event_name": "UserPromptSubmit"}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, cwd=project, timeout=60)


def _cli(project: Path, env: dict, args: list, stdin: str | bytes = "", sid: str | None = None):
    run_env = dict(env)
    if sid is not None:
        run_env["CLAUDE_CODE_SESSION_ID"] = sid
    return subprocess.run([sys.executable, str(HOOK), *args], input=stdin,
                          capture_output=True, text=isinstance(stdin, str), env=run_env,
                          cwd=project, timeout=60)


def _value(stdout: str, prefix: str) -> str:
    lines = [line[len(prefix):].strip() for line in stdout.splitlines() if line.startswith(prefix)]
    assert len(lines) == 1, stdout
    return lines[0]


def _registries(project: Path) -> list:
    root = project / ".claude" / "dev-registry"
    return sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []


# ---------------------------------------------------------------------------
# The roster
# ---------------------------------------------------------------------------


def test_roster_is_the_stems_of_agent_files_with_front_matter(tmp_path):
    (tmp_path / "ba.md").write_text("---\nname: ba\n---\nbody\n")
    (tmp_path / "qa.md").write_text("---\r\nname: qa\r\n---\r\n")
    (tmp_path / "INDEX.md").write_text("# agents\n")
    (tmp_path / "README.md").write_text("# agents\n")
    (tmp_path / "notes.txt").write_text("---\n")
    assert ROSTER.roles(tmp_path) == {"ba", "qa"}
    assert ROSTER.roles(tmp_path / "missing") == frozenset()


def test_the_harness_roster_is_its_agent_files():
    expected = {p.stem for p in (REPO_ROOT / "agents").glob("*.md")
                if p.read_text(encoding="utf-8").startswith("---")}
    assert ROSTER.roles() == expected
    assert {"graphify", "test-writer", "dev", "qa"} <= expected
    assert not {"INDEX", "README"} & expected


# ---------------------------------------------------------------------------
# The start: one task id, one registry, at the hook
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command,prefix", [("dev", "dev-"), ("dev-command", "dev-command-")])
def test_start_arms_the_registry_and_names_the_task_id(env, command, prefix):
    project, values = env
    result = _hook(project, values, "sess-a", f"/{command} add input validation --codex")
    assert result.returncode == 0, result.stderr
    name = _value(result.stdout, "DEV_SESSION_ID pre-initialized by hook:")
    assert name.startswith(prefix)
    # The task id artifacts are named with: obligation.canonical_task_id.
    assert _value(result.stdout, "Task id:") == name[len(prefix):]
    registry = project / ".claude" / "dev-registry" / name
    sentinels = {p.stem for p in registry.glob("*.json") if not p.name.endswith("-enforce.json")}
    assert sentinels == ROSTER.roles()
    for role in sentinels:
        assert json.loads((registry / f"{role}.json").read_text()) == {
            "agent_type": role, "session_id": name}
    flags = sorted(p.name for p in registry.glob("*-enforce.json"))
    assert flags == ["artifact-contract-enforce.json", "codex-enforce.json", "e2e-enforce.json"]
    for flag in flags:
        data = json.loads((registry / flag).read_text())
        assert data["enabled"] is True and data["dev_session_id"] == name
        assert "enforced_agent_types" not in data
    requirement = project / "docs" / "dev" / f"user-requirement-{name}.md"
    assert requirement.read_text() == f"/{command} add input validation"


@pytest.mark.parametrize("command", ["dev", "dev-command"])
def test_start_out_of_context_returns_the_hooks_start(env, command):
    """After a compaction the main agent asks the start function again: it gets
    the ids the hook recorded for this command, and nothing new is minted."""
    project, values = env
    text = f"/{command} keep the cycle"
    first = _hook(project, values, "sess-b", text)
    name = _value(first.stdout, "DEV_SESSION_ID pre-initialized by hook:")
    again = _cli(project, values, ["start"], text + "\n", sid="sess-b")
    assert again.returncode == 0, again.stderr
    assert _value(again.stdout, "DEV_SESSION_ID pre-initialized by hook:") == name
    assert _value(again.stdout, "Task id:") == _value(first.stdout, "Task id:")
    assert "CHECKLIST PRE-INITIALIZED" not in again.stdout
    assert _registries(project) == [name]


@pytest.mark.parametrize("command", ["dev", "dev-command"])
def test_start_after_a_hook_that_recorded_no_id_starts_the_cycle_once(env, command):
    project, values = env
    text = f"/{command} the hook failed"
    first = _cli(project, values, ["start"], text, sid="sess-c")
    assert first.returncode == 0, first.stderr
    name = _value(first.stdout, "DEV_SESSION_ID pre-initialized by hook:")
    assert _registries(project) == [name]
    assert "CHECKLIST PRE-INITIALIZED" in first.stdout
    bookmark = json.loads((project / ".claude" / "workflow-sess-c.json").read_text())
    assert bookmark["task_id"] == name and bookmark["command"] == command
    second = _cli(project, values, ["start"], text, sid="sess-c")
    assert _value(second.stdout, "DEV_SESSION_ID pre-initialized by hook:") == name
    assert _registries(project) == [name]


@pytest.mark.parametrize("text", ["/dev a later requirement", "/dev-command a later requirement"])
def test_start_never_takes_an_earlier_commands_id(env, text):
    """The session's bookmark still holds an earlier /dev's id; the hook
    recorded none for this command: the new cycle gets its own id."""
    project, values = env
    earlier = _hook(project, values, "sess-d", "/dev an earlier requirement")
    earlier_name = _value(earlier.stdout, "DEV_SESSION_ID pre-initialized by hook:")
    started = _cli(project, values, ["start"], text, sid="sess-d")
    assert started.returncode == 0, started.stderr
    name = _value(started.stdout, "DEV_SESSION_ID pre-initialized by hook:")
    assert name != earlier_name
    assert _registries(project) == sorted([earlier_name, name])


def test_start_refuses_without_a_session_or_a_dev_command(env):
    project, values = env
    assert _cli(project, values, ["start"], "/dev x").returncode == 2
    assert _cli(project, values, ["start"], "/do x", sid="sess-e").returncode == 2
    assert _registries(project) == []


# ---------------------------------------------------------------------------
# Overnight: the launcher's initializer arms through the same producer
# ---------------------------------------------------------------------------


def test_arm_registry_writes_the_handed_requirement_and_rearms_a_relaunch(env):
    project, values = env
    text = "focus line é\r\n\nUser spec path: docs/x.md\n".encode("utf-8")
    args = ["arm-registry", "--name", "sess-over", "--source-command", "dev-overnight",
            "--project-dir", str(project), "--flag", "e2e", "--flag", "codex"]
    armed = _cli(project, values, args, text)
    assert armed.returncode == 0, armed.stderr
    registry = project / ".claude" / "dev-registry" / "sess-over"
    assert {p.stem for p in registry.glob("*.json") if not p.name.endswith("-enforce.json")} \
        == ROSTER.roles()
    requirement = project / "docs" / "dev" / "user-requirement-sess-over.md"
    assert requirement.read_bytes() == text
    assert sorted(p.name for p in registry.glob("*-enforce.json")) == [
        "codex-enforce.json", "e2e-enforce.json"]
    assert json.loads((registry / "e2e-enforce.json").read_text())["source_command"] == "dev-overnight"
    # A relaunch in the same session without --codex leaves no codex flag armed.
    rearmed = _cli(project, values, args[:-2], b"second focus\n")
    assert rearmed.returncode == 0, rearmed.stderr
    assert sorted(p.name for p in registry.glob("*-enforce.json")) == ["e2e-enforce.json"]
    assert requirement.read_bytes() == b"second focus\n"


def test_arm_registry_refuses_a_symlinked_registry(env, tmp_path):
    project, values = env
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (project / ".claude" / "dev-registry").mkdir(parents=True)
    (project / ".claude" / "dev-registry" / "sess-link").symlink_to(elsewhere)
    refused = _cli(project, values, ["arm-registry", "--name", "sess-link", "--source-command",
                                     "dev-overnight", "--project-dir", str(project),
                                     "--flag", "e2e"], b"x\n")
    assert refused.returncode == 1
    assert list(elsewhere.iterdir()) == []


def test_overnight_init_hands_the_record_to_the_registry_producer(env, tmp_path):
    project, values = env
    state = tmp_path / "overnight-state-sess-o.json.tmp"
    state.write_text(json.dumps({"session_id": "sess-o", "main_root": str(project),
                                 "focus": "harden the parser", "codex_required": True}))
    verify = subprocess.run(["bash", str(OVERNIGHT_INIT), "--verify-only", "--state-file", str(state)],
                            capture_output=True, text=True, env=values, timeout=60)
    assert verify.returncode == 0, verify.stderr
    assert verify.stdout.splitlines()[-1] == "OVERNIGHT_INIT_OK"
    assert not (project / ".claude").exists()  # --verify-only writes nothing
    init = subprocess.run(["bash", str(OVERNIGHT_INIT), "--state-file", str(state)],
                          capture_output=True, text=True, env=values, timeout=60)
    assert init.returncode == 0, init.stderr
    assert init.stdout.splitlines()[-1] == "OVERNIGHT_INIT_OK"
    assert f"REGISTRY_DIR={project.resolve()}/.claude/dev-registry/sess-o" in init.stdout
    registry = project / ".claude" / "dev-registry" / "sess-o"
    assert {p.stem for p in registry.glob("*.json") if not p.name.endswith("-enforce.json")} \
        == ROSTER.roles()
    assert sorted(p.name for p in registry.glob("*-enforce.json")) == [
        "codex-enforce.json", "e2e-enforce.json"]
    assert (project / "docs" / "dev" / "user-requirement-sess-o.md").read_text() == "harden the parser\n"


# ---------------------------------------------------------------------------
# A task's registry name, by the one task-id rule
# ---------------------------------------------------------------------------


def test_registry_dir_names_the_cycle_registry(env):
    project, values = env
    registry = project / ".claude" / "dev-registry"
    stamp = "20260101-010101"
    assert _cli(project, values, ["registry-dir", stamp]).stdout.strip() == f"dev-{stamp}"
    (registry / f"dev-command-{stamp}").mkdir(parents=True)
    assert _cli(project, values, ["registry-dir", stamp]).stdout.strip() == f"dev-command-{stamp}"
    (registry / f"dev-{stamp}").mkdir()
    assert _cli(project, values, ["registry-dir", stamp]).stdout.strip() == f"dev-{stamp}"
    assert _cli(project, values, ["registry-dir", f"dev-command-{stamp}"]).stdout.strip() \
        == f"dev-command-{stamp}"
    assert _cli(project, values, ["registry-dir", "not-a-task"]).returncode == 2
