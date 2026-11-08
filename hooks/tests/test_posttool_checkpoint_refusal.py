"""A snapshot the threshold path refuses is reported as one JSON systemMessage (P5 R16, A19).

Drives hooks/posttool-git-checkpoint.sh as settings.json registers it (PostToolUse on
Write|Edit|NotebookEdit|MultiEdit, the payload on stdin) in a throwaway copy of the harness
home (hooks/ plus the two engines a refusal runs). When write_checkpoint refuses the snapshot
(rc 3: the private-literal rule, or in the harness home the settings check), nothing is
written, the hook exits 0 and its whole stdout is one JSON object whose systemMessage is
auto-commit.sh's refusal notice, never "Checkpoint failed" and never the stand-in value.
An ordinary snapshot and a refusal-free failure keep their plain lines.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STANDIN = "acct-test-123"  # stand-in personal value / listed literal
LITERAL_RULE = "the private-literal rule"
SETTINGS_CHECK = "the settings check (render-settings check --staged)"


def _git(env: dict, repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], env=env, text=True, capture_output=True, check=True
    ).stdout.strip()


@pytest.fixture
def harness(tmp_path: Path) -> tuple[Path, dict]:
    home = tmp_path / "harness"
    shutil.copytree(
        ROOT / "hooks", home / "hooks", ignore=shutil.ignore_patterns("tests", "__pycache__")
    )
    for rel in ("scripts/check-public-core.sh", "scripts/install/render-settings"):
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, home / rel)
    (home / ".gitignore").write_text("/settings.machine.json\n/private-literals.txt\n")
    settings = {"permissions": {"allow": ["Bash(git status:*)"]}}
    (home / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    (tmp_path / "gitconfig").write_text("")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "HOME": str(tmp_path / "user-home"),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "config"),
        "TMPDIR": str(tmp_path / "tmp"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "GIT_CHECKPOINT_THRESHOLD": "1",  # one pending file reaches the threshold path
    }
    for key in ("HOME", "TMPDIR"):
        Path(env[key]).mkdir(parents=True)
    (tmp_path / "config" / "logs").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(home)], env=env, check=True)
    _git(env, home, "add", "-A")
    _git(env, home, "commit", "-q", "-m", "init")
    return home, env


def _post_tool_use(home: Path, env: dict, written: Path) -> subprocess.CompletedProcess:
    """One PostToolUse event for a Write, through the hook as settings.json registers it."""
    payload = {
        "session_id": "sess-r16-test",
        "cwd": str(home),
        "hook_event_name": "PostToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": str(written), "content": "x"},
        "tool_response": {"filePath": str(written), "success": True},
    }
    return subprocess.run(
        ["bash", str(home / "hooks" / "posttool-git-checkpoint.sh")],
        input=json.dumps(payload), text=True, capture_output=True, cwd=str(home),
        env={**env, "CLAUDE_PROJECT_DIR": str(home)}, timeout=120,
    )


def _machine_form(home: Path, env: dict) -> None:
    """settings.json as smudge renders it from an overlay holding the stand-in."""
    overlay = {"permissions": {"allow": [f"Bash(/home/{STANDIN}/bin/sync.sh:*)"]}}
    (home / "settings.machine.json").write_text(json.dumps(overlay, indent=2) + "\n")
    rendered = subprocess.run(
        ["python3", "scripts/install/render-settings", "smudge"],
        input=(home / "settings.json").read_bytes(), capture_output=True, cwd=str(home),
        env=env, check=True,
    ).stdout
    (home / "settings.json").write_bytes(rendered)


@pytest.mark.parametrize("case, rule", [("literal", LITERAL_RULE), ("settings", SETTINGS_CHECK)])
@pytest.mark.parametrize("silent", ["0", "1"])
def test_refused_threshold_snapshot_prints_its_notice_as_the_whole_stdout(
    harness, case: str, rule: str, silent: str
) -> None:
    home, env = harness
    env = {**env, "GIT_CHECKPOINT_SILENT": silent}
    if case == "literal":
        (home / "private-literals.txt").write_text(f"# stand-in list\n{STANDIN}\n")
        written = home / "leak.txt"
        written.write_text(f"ticket for {STANDIN}, demo only\n")
    else:  # machine form, no filter registered: the settings check refuses it
        _machine_form(home, env)
        written = home / "settings.json"

    proc = _post_tool_use(home, env, written)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout) == {
        "systemMessage": f"Checkpoint snapshot refused by {rule}: nothing written, see logs/checkpoint.log"
    }
    assert proc.stdout.count("\n") == 1, "the JSON object must be the hook's whole stdout"
    assert "Checkpoint failed" not in proc.stdout + proc.stderr
    assert STANDIN not in proc.stdout + proc.stderr
    assert _git(env, home, "for-each-ref", "refs/checkpoints") == ""
    log = (Path(env["CLAUDE_CONFIG_DIR"]) / "logs" / "checkpoint.log").read_text()
    assert f"snapshot refused by {rule}: nothing written" in log and STANDIN not in log


def test_ordinary_threshold_snapshot_keeps_its_plain_lines(harness) -> None:
    home, env = harness
    (home / "private-literals.txt").write_text(f"{STANDIN}\n")  # the rule runs and passes
    written = home / "notes.txt"
    written.write_text("ordinary note\n")
    proc = _post_tool_use(home, env, written)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "systemMessage" not in proc.stdout
    assert "Auto-checkpoint triggered: 1 files pending" in proc.stdout
    tip = _git(env, home, "rev-parse", "--short", "refs/checkpoints/main")
    assert f"Checkpoint saved: {tip} on refs/checkpoints/main" in proc.stdout
    assert _git(env, home, "show", "refs/checkpoints/main:notes.txt") == "ordinary note"


def test_refusal_free_failure_still_says_checkpoint_failed(harness) -> None:
    home, env = harness
    written = home / "notes.txt"
    written.write_text("ordinary note\n")
    log = Path(env["CLAUDE_CONFIG_DIR"]) / "logs" / "checkpoint.log"
    log.mkdir()  # every `2>>checkpoint.log` redirect fails: rc 1, not a refusal
    proc = _post_tool_use(home, env, written)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Checkpoint failed" in proc.stdout and "systemMessage" not in proc.stdout
    assert _git(env, home, "for-each-ref", "refs/checkpoints") == ""
