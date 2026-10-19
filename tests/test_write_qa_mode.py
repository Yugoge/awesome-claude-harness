"""Root selection and zero-write failure tests for write-qa-mode.sh.

Contract (scripts/write-qa-mode.sh:35, :73-85): the registry root is
CLAUDE_PROJECT_DIR, never the script's own (harness home) location, and the
qa.json sentinel must already exist (pre-created by the launcher) with
agent_type "qa" and the matching session_id. Every refusal touches nothing.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WRITER = ROOT / "scripts/write-qa-mode.sh"
SESSION = "root-fixture"
SENTINEL = {"agent_type": "qa", "session_id": SESSION}


def _sentinel_path(root):
    return root / ".claude/dev-registry" / SESSION / "qa.json"


def _seed_sentinel(root):
    path = _sentinel_path(root)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(SENTINEL) + "\n")
    return path


def _fixture(tmp_path, with_registry=True):
    """Return (harness home holding the writer copy, project root)."""
    home = tmp_path / "harness"
    (home / "scripts").mkdir(parents=True)
    shutil.copy2(WRITER, home / "scripts/write-qa-mode.sh")
    # A sentinel at the script's own root: it must never be the write target.
    _seed_sentinel(home)
    project = tmp_path / "proj"
    project.mkdir()
    if with_registry:
        _seed_sentinel(project)
    return home, project


def _env(tmp_path, project_dir):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    # Keep the global venv fallback (write-qa-mode.sh:55) out of the real home.
    env["HOME"] = str(tmp_path / "home")
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    return env


def _run(script, env, cwd):
    return subprocess.run(
        ["bash", str(script), "--session-id", SESSION, "--mode", "ba_validation"],
        text=True,
        capture_output=True,
        env=env,
        cwd=cwd,
    )


def _assert_untouched(home):
    assert json.loads(_sentinel_path(home).read_text()) == SENTINEL


def test_env_unset_refuses_and_never_writes_script_root(tmp_path):
    home, project = _fixture(tmp_path)
    proc = _run(home / "scripts/write-qa-mode.sh", _env(tmp_path, None), project)
    assert proc.returncode != 0
    assert "CLAUDE_PROJECT_DIR not set" in proc.stderr
    _assert_untouched(home)
    assert json.loads(_sentinel_path(project).read_text()) == SENTINEL


def test_symlinked_writer_resolves_same_primary_root(tmp_path):
    home, project = _fixture(tmp_path)
    link = tmp_path / "linked-writer"
    link.symlink_to(home / "scripts/write-qa-mode.sh")
    proc = _run(link, _env(tmp_path, project), tmp_path)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(_sentinel_path(project).read_text())
    assert data == {**SENTINEL, "qa_mode": "ba_validation"}
    _assert_untouched(home)


def test_unrelated_ambient_root_cannot_redirect_write(tmp_path):
    home, project = _fixture(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    proc = _run(home / "scripts/write-qa-mode.sh", _env(tmp_path, unrelated), project)
    assert proc.returncode == 1
    assert "qa sentinel missing" in proc.stderr
    assert not (unrelated / ".claude").exists()
    _assert_untouched(home)
    assert json.loads(_sentinel_path(project).read_text()) == SENTINEL


def test_missing_session_registry_fails_before_write(tmp_path):
    home, project = _fixture(tmp_path, with_registry=False)
    proc = _run(home / "scripts/write-qa-mode.sh", _env(tmp_path, project), project)
    assert proc.returncode == 1
    assert "qa sentinel missing" in proc.stderr
    assert not (project / ".claude").exists()
    _assert_untouched(home)
