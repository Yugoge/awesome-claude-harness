"""Built-in defaults that used to carry one owner's machine values are now empty
or derived; such values come back only through the environment (normally the
untracked settings overlay's env). Both halves are pinned here: with every knob
unset the rules are generic and safe, and with synthetic stand-ins set
explicitly each rule behaves as it did for the old built-in values.

Covers hooks/pretool-bash-safety.sh, hooks/lib/checkpoint-core.sh and
scripts/prune-orphaned-workflow-bookmarks.sh. Every run uses a scratch HOME,
CLAUDE_CONFIG_DIR, state dir and protected-runtime data file.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "pretool-bash-safety.sh"
CHECKPOINT_LIB = REPO / "hooks" / "lib" / "checkpoint-core.sh"
PRUNE = REPO / "scripts" / "prune-orphaned-workflow-bookmarks.sh"
sys.path.insert(0, str(REPO / "hooks"))
from lib.runtime_guard.config import REQUIRED_KEYS  # noqa: E402

KNOBS = (
    "CLAUDE_DEV_CONTAINERS", "CLAUDE_DEV_SYSTEMD", "CLAUDE_DAEMON_RESTART_GRANT_HELPER",
    "CLAUDE_PROTECTED_DAEMON_PREFIX", "CLAUDE_PROTECTED_DAEMON_TARGETS",
    "CLAUDE_PROTECTED_PROCESS_FAMILY", "CLAUDE_HARD_BANNED_SCRIPTS",
    "CLAUDE_DAEMON_RESTART_AUDIT_LOG", "CLAUDE_CHECKPOINT_EXTRA_TRAILER", "CHECKPOINT_LOG_DIR",
    "WORKFLOW_PRUNE_ACCOUNTS_DIR", "WORKFLOW_PRUNE_PROJECT_DIRNAME", "CLAUDE_HOME",
    "CLAUDE_PYTHON_BIN", "CLAUDE_TASK_ID",
)
STAND_INS = {
    "CLAUDE_PROTECTED_DAEMON_PREFIX": "demo-daemon",
    "CLAUDE_PROTECTED_DAEMON_TARGETS": "acct-a|acct-b",
    "CLAUDE_DAEMON_RESTART_GRANT_HELPER": "/opt/demo/bin/allow-restart",
    "CLAUDE_PROTECTED_PROCESS_FAMILY": "demo",
    "CLAUDE_DEV_CONTAINERS": "demo-web-dev",
}
SID = "env-defaults-test-sid"


@pytest.fixture
def sandbox(tmp_path):
    for name in ("home", "config", "grants", "state"):
        (tmp_path / name).mkdir()
    runtime = tmp_path / "protected-runtime.json"
    runtime.write_text(json.dumps({"schema_version": 1, **{k: [] for k in REQUIRED_KEYS}}))
    env = {k: v for k, v in os.environ.items() if k not in KNOBS}
    env.update({
        "HOME": str(tmp_path / "home"),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "config"),
        "CLAUDE_STATE_DIR": str(tmp_path / "state"),
        "CLAUDE_DAEMON_RESTART_GRANT_DIR": str(tmp_path / "grants"),
        "CLAUDE_PROTECTED_RUNTIME_FILE": str(runtime),
    })
    return tmp_path, env


def hook(env, command, **extra_env):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command},
                          "session_id": SID})
    return subprocess.run(["bash", str(HOOK)], input=payload, text=True, capture_output=True,
                          env={**env, **extra_env}, timeout=120)


# ---------------- pretool-bash-safety.sh ----------------

def test_unset_daemon_prefix_is_inert_and_never_matches_every_command(sandbox):
    _, env = sandbox
    r = hook(env, "systemctl restart demo-daemon-acct-a")
    assert r.returncode == 2
    assert "daemon-restart-prohibition" not in r.stderr
    assert "forbidden for production services" in r.stderr  # the systemctl guard still fires
    assert "gated by Layer 1.A" not in r.stderr
    r = hook(env, "timeout 5 bash -c 'echo restart'")
    assert "daemon-restart-wrapper" not in r.stderr
    assert hook(env, "ls /tmp").returncode == 0


def test_stand_in_daemon_is_gated_and_grantable(sandbox):
    tmp_path, env = sandbox
    env = {**env, **STAND_INS}
    r = hook(env, "systemctl restart demo-daemon-acct-a")
    assert r.returncode == 2
    assert "daemon-restart-prohibition" in r.stderr
    assert "/opt/demo/bin/allow-restart <target>" in r.stderr
    r = hook(env, "timeout 5 bash -c 'echo restart demo-daemon'")
    assert r.returncode == 2 and "daemon-restart-wrapper" in r.stderr
    r = hook(env, "systemctl restart demo-unit")
    assert r.returncode == 2
    assert "(and demo-daemon-* is gated by Layer 1.A)" in r.stderr

    flag = tmp_path / "grants" / "claude-allow-daemon-restart-acct-a.flag"
    flag.write_text(json.dumps({"target": "acct-a", "expires_at": "2099-01-01T00:00:00Z",
                                "session_id": SID}))
    r = hook(env, "systemctl restart demo-daemon-acct-a")
    assert r.returncode == 0, r.stderr
    assert not flag.exists()  # single-shot grant consumed
    audit = tmp_path / "config" / "logs" / "claude-daemon-restart-grants.log"
    assert "acct-a" in audit.read_text()  # audit log lives under CLAUDE_CONFIG_DIR


def test_unset_grant_helper_guidance_reads_sensibly(sandbox):
    _, env = sandbox
    env = {**env, **STAND_INS, "CLAUDE_DAEMON_RESTART_GRANT_HELPER": ""}
    r = hook(env, "systemctl restart demo-daemon-acct-b")
    assert r.returncode == 2
    assert "Hint: user must run <daemon-restart grant helper> <target>" in r.stderr


def test_process_family_rules(sandbox):
    _, env = sandbox
    r = hook(env, "docker restart demo-prod")
    assert "containers is forbidden" not in r.stderr  # no family configured: inert
    r = hook(env, "killall claude")
    assert r.returncode == 2 and "Killing claude/docker processes" in r.stderr
    r = hook(env, "pkill -f demo-daemon")
    assert "Killing" not in r.stderr

    env = {**env, **STAND_INS}
    assert hook(env, "docker restart demo-web-dev").returncode == 0
    r = hook(env, "docker restart demo-prod")
    assert r.returncode == 2
    assert "Stopping/restarting production demo containers is forbidden" in r.stderr
    assert "Hint: only demo-web-dev is allowed." in r.stderr
    r = hook(env, "killall demo-daemon")
    assert r.returncode == 2 and "Killing demo/claude/docker processes" in r.stderr


def test_hard_banned_scripts_default_and_configured(sandbox):
    _, env = sandbox
    for command in ("ls session-recovery.sh", "ls restart-all-sessions.sh"):
        r = hook(env, command)
        assert r.returncode == 2 and "PERMANENTLY FORBIDDEN" in r.stderr, command
    assert "'session-recovery'" in hook(env, "ls session-recovery.sh").stderr
    assert hook(env, "ls demo-restart.sh").returncode == 0

    env = {**env, "CLAUDE_HARD_BANNED_SCRIPTS": "demo-recovery|demo-restart||"}
    r = hook(env, "ls demo-restart.sh")
    assert r.returncode == 2 and "hard-banned script 'demo-restart'" in r.stderr
    assert hook(env, "ls session-recovery.sh").returncode == 0
    assert hook(env, "ls notes.txt").returncode == 0  # empty entries never match
    r = hook(env, "cat session_dirs.txt")
    assert r.returncode == 2 and "session_dirs.txt is PERMANENTLY FORBIDDEN" in r.stderr


def test_harness_home_resolves_from_the_hook_location(sandbox):
    tmp_path, env = sandbox
    env = {**env, "CLAUDE_HOME": str(tmp_path / "elsewhere")}
    canonical = "source venv/bin/activate && python3 {}/scripts/write-bulk-commit-sentinel.py"
    assert hook(env, canonical.format(REPO)).returncode == 0
    assert hook(env, canonical.format(tmp_path / "elsewhere")).returncode == 2


# ---------------- checkpoint-core.sh ----------------

def _checkpoint_message(tmp_path, env):
    repo = tmp_path / "repo"
    git_env = {**env, "GIT_AUTO_PUSH": "0", "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
               "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
               "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
    (tmp_path / "gitconfig").write_text("")
    (tmp_path / "config" / "logs").mkdir(exist_ok=True)  # the library expects its log dir
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], env=git_env, check=True)
    (repo / "notes.txt").write_text("checkpoint me\n")
    script = 'source "$1" || exit 90; write_checkpoint "$2" "env defaults test"'
    proc = subprocess.run(["bash", "-c", script, "bash", str(CHECKPOINT_LIB), str(repo)],
                          env=git_env, text=True, capture_output=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%B",
                           "refs/checkpoints/main"], env=git_env, text=True,
                          capture_output=True, check=True).stdout.rstrip("\n")


def test_checkpoint_commit_carries_only_the_claude_trailer_by_default(sandbox):
    tmp_path, env = sandbox
    message = _checkpoint_message(tmp_path, env)
    lines = message.splitlines()
    assert lines[-1] == "Co-Authored-By: Claude <noreply@anthropic.com>"
    assert sum(line.startswith("Co-Authored-By:") for line in lines) == 1
    assert not any(line.startswith("via [") for line in lines)
    assert (tmp_path / "config" / "logs" / "checkpoint.log").exists()  # CHECKPOINT_LOG_DIR default


def test_checkpoint_extra_trailer_is_appended_after_the_claude_one(sandbox):
    tmp_path, env = sandbox
    trailer = "Co-Authored-By: Demo Bot <demo-bot@example.invalid>"
    lines = _checkpoint_message(tmp_path, {**env, "CLAUDE_CHECKPOINT_EXTRA_TRAILER": trailer}).splitlines()
    assert lines[-2:] == ["Co-Authored-By: Claude <noreply@anthropic.com>", trailer]


# ---------------- prune-orphaned-workflow-bookmarks.sh ----------------

def _prune_checkout(tmp_path, env):
    home = tmp_path / "demo home.x"
    (home / "scripts").mkdir(parents=True)
    shutil.copy2(PRUNE, home / "scripts" / PRUNE.name)
    subprocess.run(["git", "init", "-q", str(home)], env=env, check=True)
    sid = "0f0e0d0c-1234-4abc-8def-acct00000001"
    (home / f"workflow-{sid}.json").write_text("{}\n")
    return home, sid


def test_prune_without_accounts_dir_refuses_and_never_scans_root(sandbox):
    tmp_path, env = sandbox
    home, _ = _prune_checkout(tmp_path, env)
    r = subprocess.run(["bash", str(home / "scripts" / PRUNE.name)], env=env, text=True,
                       capture_output=True, timeout=60)
    assert r.returncode == 1
    assert "WORKFLOW_PRUNE_ACCOUNTS_DIR" in r.stderr
    assert "Accounts checked" not in r.stdout


def test_prune_project_dirname_derives_from_the_harness_home(sandbox):
    tmp_path, env = sandbox
    home, sid = _prune_checkout(tmp_path, env)
    derived = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(home))
    transcript = tmp_path / "accounts" / "acct-a" / "claude" / "projects" / derived / f"{sid}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}\n")
    (tmp_path / "accounts" / "acct-b").mkdir()
    env = {**env, "WORKFLOW_PRUNE_ACCOUNTS_DIR": str(tmp_path / "accounts")}
    r = subprocess.run(["bash", str(home / "scripts" / PRUNE.name)], env=env, text=True,
                       capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert f"Project dirname: {derived}" in r.stdout
    assert "transcript found under account: acct-a" in r.stdout
    r = subprocess.run(["bash", str(home / "scripts" / PRUNE.name)], text=True,
                       env={**env, "WORKFLOW_PRUNE_PROJECT_DIRNAME": "-opt-demo"},
                       capture_output=True, timeout=60)
    assert "Project dirname: -opt-demo" in r.stdout
    assert "CANDIDATE" in r.stdout or "ORPHAN(young)" in r.stdout
