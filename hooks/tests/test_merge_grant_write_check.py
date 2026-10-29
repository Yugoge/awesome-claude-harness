"""The merge-analyst grant's one validator runs on the merge-analyst's own Write.

Experiment E11: the privilege guard's merge-grant check sat behind
CLAUDE_MERGE_COMMAND_ACTIVE=1 in the hook's own environment, which the compliant /merge
never produces (hooks/merge.sh exports it to its own subprocess only), so the check moved
to the producer's tool call: hooks/posttool-allowlist-consume.py runs
hooks/lib/merge_grant.py at the PostToolUse of that Write and returns a fault to the
merge-analyst; /merge reads the verdict as written. The guard refuses every agent
`git merge`, with or without the variable.
"""

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FINALIZER = _load(HOOKS / "posttool-allowlist-consume.py", "posttool_merge_grant_check")
GUARD = _load(HOOKS / "pretool-git-privilege-guard.py", "guard_merge_refusal")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def merge_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp_path / "state"))
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "test")
    (repo / "f.txt").write_text("x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "checkout", "-q", "-b", "feat")
    (repo / "g.txt").write_text("y\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "feat")
    git(repo, "checkout", "-q", "master")
    root = os.path.realpath(git(repo, "rev-parse", "--show-toplevel"))
    repo_hash = hashlib.sha256(root.encode()).hexdigest()[:16]
    grant = {"verdict": "approved", "risks": [], "analysis_summary": "clean", "repo_root": root,
             "branch": "feat", "source_tip": git(repo, "rev-parse", "feat"), "default_branch": "master",
             "default_tip": git(repo, "rev-parse", "master"), "session_id": "sid-merge", "nonce": "req1",
             "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    path = tmp_path / "state" / "agentic-commit" / "merge-analyst" / repo_hash / "sid-merge" / "req1.json"
    path.parent.mkdir(parents=True)
    return repo, path, grant


def post_write(path, grant):
    Path(path).write_text(json.dumps(grant))
    payload = {"tool_name": "Write", "session_id": "sid-merge", "agent_id": "amergeanalyst",
               "hook_event_name": "PostToolUse", "tool_input": {"file_path": str(path), "content": ""},
               "tool_response": {"filePath": str(path)}}
    saved_stdin, saved_stderr = sys.stdin, sys.stderr
    sys.stdin, sys.stderr = io.StringIO(json.dumps(payload)), io.StringIO()
    try:
        FINALIZER.main()
    except SystemExit as exc:
        return exc.code, sys.stderr.getvalue()
    finally:
        captured = sys.stderr.getvalue()
        sys.stdin, sys.stderr = saved_stdin, saved_stderr
    return None, captured


def test_a_valid_grant_write_passes(merge_setup):
    _, path, grant = merge_setup
    assert post_write(path, grant) == (0, "")
    assert path.exists()


@pytest.mark.parametrize("field,value", [
    ("nonce", "req2"), ("session_id", "sid-other"), ("source_tip", "0" * 40),
    ("default_tip", "0" * 40), ("verdict", "warn"), ("risks", "none"),
    ("expires_at", "2000-01-01T00:00:00Z"), ("repo_root", "/nonexistent"),
])
def test_each_fault_returns_to_the_merge_analyst(merge_setup, field, value):
    _, path, grant = merge_setup
    code, stderr = post_write(path, dict(grant, **{field: value}))
    assert code == 2
    assert stderr.startswith("MERGE_GRANT_INVALID:") and f"`{field}`" in stderr
    assert not path.exists(), "a faulty grant never stays for /merge to read"
    assert post_write(path, grant) == (0, ""), "the merge-analyst can Write it again"


def test_a_write_elsewhere_is_not_checked(tmp_path):
    other = tmp_path / "notes.json"
    assert post_write(other, {"verdict": "nonsense"}) == (0, "")


def test_the_guard_refuses_agent_git_merge_even_with_the_variable(merge_setup, monkeypatch):
    repo, path, grant = merge_setup
    path.write_text(json.dumps(grant))
    monkeypatch.setenv("CLAUDE_MERGE_COMMAND_ACTIVE", "1")
    with pytest.raises(SystemExit) as exc:
        GUARD._evaluate_merge(f"git -C {repo} merge --no-edit feat", {"session_id": "sid-merge"})
    assert exc.value.code == 2
    assert path.exists(), "the guard no longer reads or spends the merge-analyst grant"
