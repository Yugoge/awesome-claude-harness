"""A command separator inside a quoted commit message is message text, to the pipeline commit grant.

The pipeline commit grant (`claude-commit-grant-*`, changelog-analyst's) reads the message through
the classifier's own segmenter. Its cases here pin that it passes for the one dispatched analyst and
refuses the main agent, a dev and another task. (The owner's /allow grant is decided in one place,
lib/hook_launch.release_refused, whatever the command: hooks/tests/test_allow_releases_anything.py.)

Every case runs the real hook files against a scratch HOME, state directory and repository; nothing
commits anywhere real.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(HOOKS))

import lib.commit_pipeline as CP  # noqa: E402

SID, TASK = "sid-fr2", "20261109-000000"
TASK_LINE = f"Task-id: {TASK}"


# --------------------------------------------------------------------------------------------
# The real hook files, in a scratch HOME, state directory and repository
# --------------------------------------------------------------------------------------------

def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def world(tmp_path, monkeypatch):
    home, state, project = tmp_path / "home", tmp_path / "state", tmp_path / "project"
    for d in (home / ".claude", state, project):
        d.mkdir(parents=True)
    for k in list(os.environ):
        if k.startswith("CLAUDE") or k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"):
            monkeypatch.delenv(k)
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(state))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("HOME", str(home))
    return tmp_path


def make_repo(path):
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "master")
    for key, value in (("user.email", "t@example.invalid"), ("user.name", "t"), ("commit.gpgsign", "false")):
        git(path, "config", key, value)
    (path / "f.txt").write_text("base\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "base")
    return path


def session_dir():
    return Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / str(
        Path(os.environ["CLAUDE_PROJECT_DIR"]).resolve()).replace("/", "-")


def mint(repo, task=TASK):
    """A pipeline commit grant exactly as scripts/write-commit-grant.py shapes it."""
    now = datetime.now(timezone.utc)
    nonce = os.urandom(8).hex()
    grant = {"task_id": task, "sid": SID, "nonce": nonce, "repo_root": git(repo, "rev-parse", "--show-toplevel"),
             "branch": git(repo, "branch", "--show-current"), "expected_head": git(repo, "rev-parse", "HEAD"),
             "created_at": (now - timedelta(seconds=2)).isoformat(),
             "expires_at": (now + timedelta(minutes=30)).isoformat(),
             "minted_by": {"origin": CP.PIPELINE_ORIGIN,
                           "evidence": {"manifest_dispatched_at": (now - timedelta(seconds=30)).isoformat()}}}
    path = Path(os.environ["CLAUDE_STATE_DIR"]) / f"claude-commit-grant-{SID}-{nonce}.json"
    path.write_text(json.dumps(grant))
    # The pre-commit review approved this round (commands/commit.md Step 6); docs/dev stays out of the commit.
    (Path(repo) / "docs" / "dev").mkdir(parents=True, exist_ok=True)
    (Path(repo) / "docs" / "dev" / f"commit-qa-report-{task}.md").write_text("# pre-commit QA\n\nCOMMIT: APPROVE\n")
    with open(Path(repo) / ".git" / "info" / "exclude", "a") as handle:
        handle.write("docs/dev/\n")
    return path


def dispatch(prompt, subagent_type):
    """The records a real dispatch leaves; for a changelog-analyst also the hook-written attestation."""
    if subagent_type == "changelog-analyst":
        CP.write_attestation(SID, task_id=TASK, dryrun=False, prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest())
    root, agent = session_dir(), "a" + os.urandom(8).hex()
    call = "toolu_" + os.urandom(8).hex()
    (root / SID / "subagents").mkdir(parents=True, exist_ok=True)
    with open(root / f"{SID}.jsonl", "a") as handle:
        handle.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": call, "name": "Agent",
             "input": {"subagent_type": subagent_type, "prompt": prompt}}]}}) + "\n")
    (root / SID / "subagents" / f"agent-{agent}.jsonl").write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
    (root / SID / "subagents" / f"agent-{agent}.meta.json").write_text(
        json.dumps({"agentType": subagent_type, "toolUseId": call}))
    return agent


GUARD_HOOKS = ["pretool-git-privilege-guard.py", "pretool-bash-safety.sh", "pretool-block-branch-pr-worktree.py"]


def replay(command, repo, role=None):
    """Every commit-relevant PreToolUse hook on one Bash payload: {hook: (exit code, stderr)}.
    ``role`` is None for the main agent, else (agent_id, agent_type) as the CLI sends them."""
    payload = {"tool_name": "Bash", "session_id": SID, "cwd": str(repo), "hook_event_name": "PreToolUse",
               "tool_use_id": "toolu_" + uuid.uuid4().hex[:12],
               "transcript_path": str(session_dir() / f"{SID}.jsonl"), "tool_input": {"command": command}}
    if role:
        payload.update(agent_id=role[0], agent_type=role[1])
    env = dict(os.environ, CLAUDE_HOME=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    out = {}
    for hook in GUARD_HOOKS:
        runner = ["bash"] if hook.endswith(".sh") else [sys.executable]
        proc = subprocess.run(runner + [str(HOOKS / hook)], input=json.dumps(payload), capture_output=True,
                              text=True, env=env, cwd=str(repo), timeout=120)
        out[hook] = (proc.returncode, proc.stderr)
    return out


def refused(results):
    return {hook: err for hook, (code, err) in results.items() if code != 0}


MESSAGES = [  # a separator in a quoted message, per commit shape: {R} the repository, {M} a message file
    'git -C "{R}" commit -m "fix(x): a; b" -m "%s"' % TASK_LINE,
    "git -C \"{R}\" commit -m 'fix(x): a; b' -m '%s'" % TASK_LINE,
    "git -C \"{R}\" commit -m $'fix(x): a; b' -m '%s'" % TASK_LINE,
    'git -C "{R}" commit -m "fix(x): a && b" -m "%s"' % TASK_LINE,
    'git -C "{R}" commit -m "fix(x): a || b | c & d" -m "%s"' % TASK_LINE,
    'git -C "{R}" commit -m "fix(x): \\"a; b\\"" -m "%s"' % TASK_LINE,
    'git -C "{R}" commit -m "fix(x): a\nb; c\n\n%s"' % TASK_LINE,
    'git -C "{R}" commit -F "{M}"',
]


def message_file(world_dir):
    path = world_dir / f"msg-{uuid.uuid4().hex[:6]}.txt"
    path.write_text(f"fix(x): a; b && c || d | e\n\n{TASK_LINE}\n")
    return path


ANALYST_PROMPT = 'TASK_ID=%s\nDRYRUN=false\n<obligation v="1">{}</obligation>' % TASK


@pytest.mark.parametrize("template", MESSAGES)
def test_the_pipeline_grant_is_spent_by_its_analyst_only(world, template):
    repo = make_repo(world / "repo")
    command = template.replace("{R}", str(repo)).replace("{M}", str(message_file(world)))
    grant = mint(repo)
    analyst = (dispatch(ANALYST_PROMPT, "changelog-analyst"), "changelog-analyst")
    dev = (dispatch("dev prompt", "dev"), "dev")
    assert "pretool-git-privilege-guard.py" in refused(replay(command, repo))           # the main agent
    assert "pretool-git-privilege-guard.py" in refused(replay(command, repo, dev))     # a dev
    assert grant.exists(), "a refused caller must not spend the grant"
    assert refused(replay(command, repo, analyst)) == {}                                 # the dispatched analyst
    assert not grant.exists()


def test_the_pipeline_grant_stays_bound_to_its_task_and_its_commit_count(world):
    repo = make_repo(world / "repo")
    grant = mint(repo)
    analyst = (dispatch(ANALYST_PROMPT, "changelog-analyst"), "changelog-analyst")
    other_task = f'git -C "{repo}" commit -m "fix(x): a; b" -m "Task-id: 20260101-000000"'
    assert "pretool-git-privilege-guard.py" in refused(replay(other_task, repo, analyst))
    two = f'git -C "{repo}" commit -m "fix(x): a; b" -m "{TASK_LINE}"; git -C "{repo}" commit -m "again" -m "{TASK_LINE}"'
    assert "pretool-git-privilege-guard.py" in refused(replay(two, repo, analyst))
    assert grant.exists()


