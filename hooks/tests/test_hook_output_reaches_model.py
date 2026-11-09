"""Each hook P12-L4 fixed speaks on a channel that reaches the model for its event, or says nothing.

The CLI (code.claude.com/docs/en/hooks): plain stdout reaches the model on SessionStart and
UserPromptSubmit only; on PreToolUse and PostToolUse a hookSpecificOutput.additionalContext JSON
does (none of these hooks adds a blocking site); stderr on exit 0 reaches no one, nor does
anything a SessionEnd hook prints; at SubagentStop any output that reaches a model keeps the subagent
running. Each case drives the real hook as a process on an input that makes it speak.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"


def _env(tmp_path: Path, **extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "GIT_"))}
    env.update(HOME=str(tmp_path / "home"), CLAUDE_STATE_DIR=str(tmp_path / "state"), PYTHONDONTWRITEBYTECODE="1",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e.invalid", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@e.invalid", **extra)
    for d in ("home", "state"):
        (tmp_path / d).mkdir(exist_ok=True)
    return env


def _run(hook: str, payload, env: dict, cwd: Path):
    cmd = ["bash", str(HOOKS / hook)] if hook.endswith(".sh") else [sys.executable, str(HOOKS / hook)]
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(cmd, input=raw, capture_output=True, text=True, env=env, cwd=cwd, timeout=60)


def _context(stdout: str, event: str) -> str:
    out = json.loads(stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == event
    return out["additionalContext"]


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    return r


def test_session_info_tells_the_model(tmp_path, repo):
    p = _run("session-info.sh", "{}", _env(tmp_path), repo)
    assert p.returncode == 0 and p.stderr == ""
    assert p.stdout.startswith("Session info:\n  Dir: ") and "Git: main" in p.stdout


def test_tmpfs_banner_tells_the_model_only_over_the_threshold(tmp_path, repo):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for pct, expect in (("91%", True), ("12%", False)):
        (bin_dir / "df").write_text("#!/bin/sh\necho 'Filesystem Size Used Avail Use% Mounted on'\n"
                                    f"echo 'tmpfs 1G 1G 0 {pct} /tmp'\n")
        (bin_dir / "df").chmod(0o755)
        p = _run("session-tmpfs-banner.sh", "{}", _env(tmp_path, PATH=f"{bin_dir}:{os.environ['PATH']}"), repo)
        assert p.returncode == 0 and p.stderr == ""
        assert (p.stdout == f"WARN tmpfs over 75%: tmpfs 1G 1G 0 {pct} /tmp\n") if expect else p.stdout == ""


def test_scratch_init_tells_the_model_what_it_could_not_set_up(tmp_path, repo):
    p = _run("session-scratch-init.sh", json.dumps({"session_id": "../escape"}),
             _env(tmp_path, TMPDIR=str(tmp_path / "scratch")), repo)
    assert p.returncode == 0
    assert p.stdout == "session-scratch-init: unsafe session id '../escape' — skipping\n"


def test_git_init_is_silent_when_off_and_plain_when_on(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    off = _run("session-git-init.sh", "{}", _env(tmp_path), empty)
    assert (off.returncode, off.stdout, off.stderr) == (0, "", "")
    on = _run("session-git-init.sh", "{}", _env(tmp_path, CLAUDE_SESSION_GIT_INIT="1", CLAUDE_AUTO_CREATE_REPO="false"),
              empty)
    assert "Git repository initialized" in on.stdout or "Created .gitignore" in on.stdout, on.stdout + on.stderr
    assert "\x1b[" not in on.stdout


def test_bulk_commit_capability_tells_the_model(tmp_path, repo):
    p = _run("userprompt-bulk-commit-capability.py", {"prompt": "/commit --bulk", "session_id": ""},
             _env(tmp_path), repo)
    assert p.returncode == 0 and p.stderr == ""
    assert "[bulk-commit-capability] /commit --bulk seen but no session_id" in p.stdout


def test_quality_gate_warns_through_additional_context(tmp_path, repo):
    content = "\n".join(["x = 1"] * 900)
    p = _run("pretool-quality-gate.py", {"tool_name": "Write", "tool_input": {"file_path": str(repo / "a.py"),
                                                                              "content": content}},
             _env(tmp_path), repo)
    assert p.returncode == 0 and p.stderr == ""
    assert _context(p.stdout, "PreToolUse").startswith(f"QUALITY GATE WARNING — {repo / 'a.py'}:")


def test_bulk_commit_detector_warns_through_additional_context(tmp_path, repo):
    for part in ("hooks", "commands", "scripts"):
        (repo / part).mkdir()
        (repo / part / "f.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    p = _run("pretool-bulk-commit-detector.py",
             {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'chore(claude): sync all uncommitted'"}},
             _env(tmp_path), repo)
    assert p.returncode == 0 and p.stderr == ""
    assert "WARN (bulk-commit-detector, not blocking)" in _context(p.stdout, "PreToolUse")


def test_prompt_purity_warns_the_orchestrator_through_additional_context(tmp_path, repo):
    prompt = "Fix the parser. Run `grep -rn foo src && pytest -q` first."
    p = _run("pretool-orchestrator-prompt-purity.py",
             {"tool_name": "Agent", "tool_input": {"prompt": prompt, "subagent_type": "dev"}}, _env(tmp_path), repo)
    assert p.returncode == 0 and p.stderr == ""
    assert "category:" in _context(p.stdout, "PreToolUse")
    sub = _run("pretool-orchestrator-prompt-purity.py", {"tool_name": "Agent", "agent_id": "a1",
                                                         "tool_input": {"prompt": prompt}}, _env(tmp_path), repo)
    assert (sub.returncode, sub.stdout) == (0, "")


def test_a_broken_command_file_is_told_to_the_model(tmp_path, repo):
    cmd = repo / ".claude" / "commands" / "x.md"
    cmd.parent.mkdir(parents=True)
    cmd.write_text("no frontmatter\n")
    p = _run("posttool-command-frontmatter-validate.py", {"tool_name": "Write", "tool_input": {"file_path": str(cmd)}},
             _env(tmp_path), repo)
    assert p.returncode == 0 and p.stderr == ""
    assert _context(p.stdout, "PostToolUse").startswith("INVALID: x.md was written with invalid command frontmatter")


def test_a_run_code_timeout_is_told_to_the_model(tmp_path, repo):
    env = _env(tmp_path, CLAUDE_SESSION_ID="s1", PLAYWRIGHT_RUNCODE_TIMEOUT="30")
    (tmp_path / "state" / ".runcode-watchdog-s1.pid.timeout").write_text("")
    p = _run("posttool-runcode-watchdog.py", {"tool_name": "mcp__playwright__browser_run_code"}, env, repo)
    assert p.returncode == 0 and p.stderr == ""
    assert _context(p.stdout, "PostToolUse") == "browser_run_code was terminated after 30s timeout"


def test_untracked_files_after_a_commit_are_told_to_the_model(tmp_path, repo):
    (repo / "stray.txt").write_text("x\n")
    (repo / "docs" / "dev").mkdir(parents=True)
    for name in ("dev-report-20261109-101010.json", "qa-report-20261109-101010.json"):
        (repo / "docs" / "dev" / name).write_text("{}\n")
    env = _env(tmp_path, GIT_WARN_UNTRACKED="1")
    p = _run("posttool-git-warn.sh", {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}}, env, repo)
    text = _context(p.stdout, "PostToolUse")
    assert text.startswith("Warning: 3 untracked file(s) after this commit, in: docs/ (2), stray.txt\n")
    assert "20261109-101010" not in p.stdout  # no id it was not handed: it mints none
    assert "--amend" not in text and "git add ." not in text
    for other in ({"tool_name": "Bash", "tool_input": {"command": "ls commit"}},
                  {"tool_name": "Bash", "tool_input": {"command": "echo git commit-tree"}}):
        assert _run("posttool-git-warn.sh", other, env, repo).stdout == ""
    assert _run("posttool-git-warn.sh", {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}},
                _env(tmp_path), repo).stdout == ""


@pytest.mark.parametrize("hook, payload", [
    ("sessionend-scratch-sweep.sh", {"session_id": "s-none"}),
    ("subagentstop-restart-track.py", {"session_id": "s-none", "agent_id": "a1"}),
])
def test_observers_on_events_that_reach_no_model_print_nothing(tmp_path, repo, hook, payload):
    p = _run(hook, payload, _env(tmp_path, TMPDIR=str(tmp_path / "scratch")), repo)
    assert (p.returncode, p.stdout, p.stderr) == (0, "", "")
