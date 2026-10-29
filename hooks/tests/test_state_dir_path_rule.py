"""Hook state is written and read in one directory, also when CLAUDE_STATE_DIR is set.

Each test pairs a state file's writer with its reader: with CLAUDE_STATE_DIR pointing
at a fresh directory, the file the writer makes is the file the reader finds. The
agent prose that writes a grant resolves the same directory as the code that reads it.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
SCRIPTS = ROOT / "scripts"


def _load(path, name):
    if str(HOOKS) not in sys.path:
        sys.path.insert(0, str(HOOKS))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def state(tmp_path, monkeypatch):
    directory = tmp_path / "state"
    directory.mkdir()
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(directory))
    monkeypatch.delenv("CLAUDE_USERINTENT_SENTINEL_DIR", raising=False)
    return directory


def _env(state, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "ANTHROPIC_"))}
    env.update(CLAUDE_STATE_DIR=str(state), PYTHONDONTWRITEBYTECODE="1", **extra)
    return env


def test_do_consent_written_by_the_prompt_hook_is_read_by_the_guard(state):
    workflow = _load(HOOKS / "prompt-workflow.py", "prompt_workflow_path_rule")
    workflow.handle_do_consent("sid-path-rule")
    assert (state / "claude-orchestrator-consent-sid-path-rule.flag").read_text().strip() == "true"
    sidecar = state / "claude-do-task-sid-path-rule.json"
    assert json.loads(sidecar.read_text())["task_id"]
    guard = _load(HOOKS / "pretool-git-privilege-guard.py", "privilege_guard_path_rule_consent")
    # The guard decides through lib/allowlist.py has_do_consent, every consent reader's one rule.
    assert guard.has_do_consent({"session_id": "sid-path-rule"})
    assert not guard.has_do_consent({"session_id": "sid-path-rule", "agent_id": "a1"})


def test_bulk_sentinel_writer_and_guard_share_the_state_dir(state):
    out = subprocess.run([sys.executable, str(SCRIPTS / "write-bulk-commit-sentinel.py"), "--sid", "sid-bulk",
                          "--origin", "userpromptsubmit-hook"],
                         capture_output=True, text=True, env=_env(state), check=True).stdout.strip()
    assert Path(out).parent == state
    guard = _load(HOOKS / "pretool-git-privilege-guard.py", "privilege_guard_path_rule_bulk")
    assert guard._has_bulk_commit_sentinel({"session_id": "sid-bulk"})


def test_residual_override_writer_and_guard_share_the_state_dir(state):
    writer = _load(SCRIPTS / "write-git-residual-override.py", "residual_override_path_rule")
    guard = _load(HOOKS / "pretool-git-privilege-guard.py", "privilege_guard_path_rule_override")
    assert writer.DEFAULT_DIR == guard._RESIDUAL_OVERRIDE_DIR == str(state / "claude-git-residual-override")


def test_commit_grant_writer_default_is_the_guard_glob_root(state):
    writer = _load(SCRIPTS / "write-commit-grant.py", "commit_grant_path_rule")
    args = writer._parse_args(["--task-id", "20260101-000000"])
    assert Path(args.output_dir) == state


def test_stop_userintent_writer_and_reader_share_the_state_dir(state):
    writer = _load(HOOKS / "pretool-wrapper-userintent.py", "wrapper_userintent_path_rule")
    reader = _load(SCRIPTS / "break-overnight-lock.py", "break_overnight_lock_path_rule")
    assert writer._SENTINEL_DIR == reader._SENTINEL_DIR == str(state)


def _prose_state_dir(agent: str, state: Path, tmp_path: Path) -> str:
    """Run the STATE_DIR line of an analyst's prose as its Bash call would."""
    text = (ROOT / "agents" / f"{agent}.md").read_text(encoding="utf-8")
    lines = sorted({m.group(0) for m in re.finditer(r"^STATE_DIR=\$\(.*\)$", text, re.M)})
    assert len(lines) == 1, lines
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    if not (home / ".claude").exists():
        (home / ".claude").symlink_to(ROOT)
    return subprocess.run(["bash", "-c", lines[0] + '\nprintf %s "$STATE_DIR"'], capture_output=True,
                          text=True, env=_env(state, HOME=str(home)), check=True).stdout


def test_push_analyst_prose_writes_where_its_validator_looks(state, tmp_path):
    prose = _prose_state_dir("push-analyst", state, tmp_path)
    assert prose == str(state)
    executor = _load(SCRIPTS / "execute-push.py", "execute_push_path_rule")
    assert executor._SENTINEL_BASE == f"{prose}/agentic-commit/push-analyst"


def test_merge_analyst_prose_writes_where_its_check_looks(state, tmp_path):
    prose = _prose_state_dir("merge-analyst", state, tmp_path)
    merge_grant = _load(HOOKS / "lib" / "merge_grant.py", "merge_grant_path_rule")
    grant = Path(prose) / "agentic-commit" / "merge-analyst" / "0123456789abcdef" / "sid-merge" / "nonce.json"
    assert merge_grant.grant_root() == str(Path(prose) / "agentic-commit" / "merge-analyst")
    assert merge_grant.is_grant_path(str(grant))


def test_push_gate_token_writer_writes_where_push_sh_reads(state, tmp_path):
    writer = _load(SCRIPTS / "write-push-gate-token.py", "push_gate_token_path_rule")
    path = writer.token_path(str(tmp_path), "main", "sid-token")
    assert path.parents[2] == state / "agentic-commit" / "push"
    assert '_TOKEN_BASE_DIR="$(harness_state_dir)/agentic-commit/push/${_REPO_HASH}"' in (
        HOOKS / "push.sh").read_text()


@pytest.mark.parametrize("command,expected", [
    ("cat {d}/claude-bulk-commit-sentinel-sid-n.json", 0),
    ("echo x > {d}/claude-bulk-commit-sentinel-sid-n.json", 2),
    ("cp /dev/null {d}/claude-bulk-commit-sentinel-sid-n.json", 2),
])
def test_bash_safety_protects_the_sentinel_name_in_the_state_dir(state, command, expected):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command.format(d=state)}})
    proc = subprocess.run(["bash", str(HOOKS / "pretool-bash-safety.sh")], input=payload, text=True,
                          capture_output=True, env=_env(state))
    assert proc.returncode == expected, proc.stderr
