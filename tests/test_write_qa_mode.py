"""Root selection and zero-write failure tests for write-qa-mode.sh."""

import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WRITER = ROOT / "scripts/write-qa-mode.sh"
RESOLVER = ROOT / "hooks/lib/claude_home.sh"
SESSION = "root-fixture"


def _fixture(tmp_path, with_registry=True):
    home = tmp_path / "harness"
    (home / "scripts").mkdir(parents=True)
    (home / "hooks/lib").mkdir(parents=True)
    (home / "policies").mkdir()
    shutil.copy2(WRITER, home / "scripts/write-qa-mode.sh")
    shutil.copy2(RESOLVER, home / "hooks/lib/claude_home.sh")
    (home / "settings.json").write_text("{}\n")
    if with_registry:
        registry = home / ".claude/dev-registry" / SESSION
        registry.mkdir(parents=True)
        (registry / "dev.json").write_text("{}\n")
    return home


def _run(script, env=None):
    return subprocess.run(
        ["bash", str(script), "--session-id", SESSION, "--mode", "ba_validation"],
        text=True,
        capture_output=True,
        env=env,
    )


def test_env_unset_uses_validated_script_root(tmp_path):
    home = _fixture(tmp_path)
    import os
    env = os.environ.copy()
    env.pop("CLAUDE_PROJECT_DIR", None)
    proc = _run(home / "scripts/write-qa-mode.sh", env)
    assert proc.returncode == 0, proc.stderr
    assert f"qa_mode_root={home}" in proc.stderr
    data = json.loads((home / ".claude/dev-registry" / SESSION / "qa.json").read_text())
    assert data["qa_mode"] == "ba_validation"


def test_symlinked_writer_resolves_same_primary_root(tmp_path):
    home = _fixture(tmp_path)
    link = tmp_path / "linked-writer"
    link.symlink_to(home / "scripts/write-qa-mode.sh")
    proc = _run(link)
    assert proc.returncode == 0, proc.stderr
    assert (home / ".claude/dev-registry" / SESSION / "qa.json").is_file()


def test_unrelated_ambient_root_cannot_redirect_write(tmp_path):
    import os
    home = _fixture(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(unrelated)
    proc = _run(home / "scripts/write-qa-mode.sh", env)
    assert proc.returncode == 0, proc.stderr
    assert not (unrelated / ".claude/dev-registry" / SESSION / "qa.json").exists()


def test_missing_session_registry_fails_before_write(tmp_path):
    home = _fixture(tmp_path, with_registry=False)
    proc = _run(home / "scripts/write-qa-mode.sh")
    assert proc.returncode == 1
    assert "session registry is absent" in proc.stderr
    assert not (home / ".claude/dev-registry" / SESSION / "qa.json").exists()
