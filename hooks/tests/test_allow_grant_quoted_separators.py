"""A command separator inside a quoted commit message is message text, to a commit grant too (FR-2).

The owner's report: a commit made under a valid grant was refused when its quoted message held a
semicolon (`git commit -m "fix(x): a; b"`). hooks/lib/allowlist.py::_bash_subcommands, the one place
the /allow grant matcher splits a command, cut at every `;`, `&&`, `||`, `|` and newline whether
quoted or not, so the quoted message made two "commands" and a grant authorizes exactly one. The
pretool-git-privilege-guard, pretool-bash-safety.sh and posttool-allowlist-consume all ask that one
matcher, so the splitter reads the quoting the way the shell does, where the quoting is purely
lexical, and splits every separator as before wherever it is not (a here-document, `$(`, a backquote,
a process substitution, an open quote).

The pipeline commit grant (`claude-commit-grant-*`, changelog-analyst's) never split the command that
way: it reads the message through the classifier's own segmenter. Its cases here pin that it keeps
passing for the one dispatched analyst and keeps refusing the main agent, a dev and another task.

Every case judges payload strings or runs the real hook files against a scratch HOME, state directory
and repository; nothing commits anywhere real.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import random
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(HOOKS))

import lib.commit_pipeline as CP  # noqa: E402


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AL = _load(HOOKS / "lib" / "allowlist.py", "allowlist_fr2")
SID, TASK = "sid-fr2", "20261109-000000"
TASK_LINE = f"Task-id: {TASK}"

# --------------------------------------------------------------------------------------------
# The splitter
# --------------------------------------------------------------------------------------------

ONE = [  # a separator in quoted text is text: one command
    'git commit -m "fix(x): a; b"',
    "git commit -m 'fix(x): a; b'",
    "git commit -m $'fix(x): a; b'",
    'git commit -m "fix(x): a && b"',
    'git commit -m "fix(x): a || b"',
    'git commit -m "fix(x): a | b"',
    'git commit -m "fix(x): a & b"',
    'git commit -m "fix(x): a\nb; c"',
    "git commit -m 'fix(x): a\nb; c'",
    'git commit -m "fix(x): \\"a; b\\" && c"',
    "git commit -m $'fix(x): it\\'s a; b'",
    "git commit -m 'fix(x): \"a; b\"'",
    'git commit -m "fix(x): it\'s a; b"',
    'git commit -m "fix(x): a; b" -m "' + TASK_LINE + '"',
    'git -C "/some/dir" commit -m "fix(x): a; b" -m "' + TASK_LINE + '"',
    "git commit -m 'fix(x): $(not run); `not run` << x'",
    'git commit -m "fix: a \\$(not run); b"',
    'git commit -m "fix(x): a; b" # a comment',
    'X=1 git commit -m "fix(x): a; b"',
    'git commit -F "/tmp/some; odd name.txt"',
]


@pytest.mark.parametrize("command", ONE)
def test_a_separator_inside_a_quoted_word_is_one_command(command):
    assert AL._bash_subcommands(command) == [command]


TWO = [  # a separator outside the quotes starts a second command, checked on its own
    ('git commit -m "a; b"; rm x', ['git commit -m "a; b"', "rm x"]),
    ('git commit -m "a; b" && rm x', ['git commit -m "a; b"', "rm x"]),
    ('git commit -m "a; b" || rm x', ['git commit -m "a; b"', "rm x"]),
    ('git commit -m "a; b" | rm x', ['git commit -m "a; b"', "rm x"]),
    ('git commit -m "a; b"\nrm x', ['git commit -m "a; b"', "rm x"]),
    ('rm x; git commit -m "a; b"', ["rm x", 'git commit -m "a; b"']),
    ("git commit -m 'a; b'; rm x", ["git commit -m 'a; b'", "rm x"]),
    ("git commit -m $'a\\'; b'; rm x", ["git commit -m $'a\\'; b'", "rm x"]),
    ('git commit -m "a\\"; b"; rm x', ['git commit -m "a\\"; b"', "rm x"]),
    ('git commit -m a; b', ["git commit -m a", "b"]),
    ("git commit -m a && b", ["git commit -m a", "b"]),
    ('git commit -m "a" ; git push', ['git commit -m "a"', "git push"]),
    ('git commit -m "a"; git commit -m "b; c"', ['git commit -m "a"', 'git commit -m "b; c"']),
    # a quote in a comment opens nothing: the separators after it are real
    ("git commit -m a # don't\nrm x; echo '", ["git commit -m a # don't", "rm x", "echo '"]),
    ("git commit -m a #it's; rm x", ["git commit -m a #it's", "rm x"]),
    # nothing in a comment opens a quote or an expansion
    ('git commit -m "a; b" # c\nrm x # ok" $(y', ['git commit -m "a; b" # c', 'rm x # ok" $(y']),
    # a backslash before a quote keeps it from opening one
    ("git commit -m a\\'; rm x; echo \\'", ["git commit -m a\\'", "rm x", "echo \\'"]),
    # an escaped separator outside quotes splits as before (the safe direction)
    ("git commit -m a\\; rm x", ["git commit -m a\\", "rm x"]),
]


@pytest.mark.parametrize("command,parts", TWO)
def test_a_separator_outside_quotes_starts_a_second_command(command, parts):
    assert AL._bash_subcommands(command) == parts


# What the scan cannot read as the shell does is split on every separator, quoted or not: as before.
UNREADABLE = [
    'git commit -m "$(echo a; rm x)"',
    'git commit -m "`echo a; rm x`"',
    'git commit -m "a; b" $(rm x; y)',
    'git commit -m "a; b" `rm x; y`',
    'git commit -m "a; b" <(rm x; y)',
    "git commit -F - <<'EOF'\na; b\nEOF",
    "git commit -F - <<'EOF'\ndon't\nEOF\nrm x; echo '",
    "git commit -m \"a; b",
    "git commit -m 'a; b",
    'git commit -m "a; b" "',
    "git commit -m $'a; b",
]


@pytest.mark.parametrize("command", UNREADABLE)
def test_what_the_scan_cannot_read_splits_as_before(command):
    legacy = command.replace("||", "\n").replace("&&", "\n").replace(";", "\n").replace("|", "\n")
    assert AL._bash_subcommands(command) == [p.strip() for p in legacy.split("\n") if p.strip()]


def test_text_with_no_quote_splits_exactly_as_before():
    rnd = random.Random(7)
    pieces = ["git", "commit", "-m", "x", "a;b", ";", "&&", "||", "|", "&", "\n", " ", "  ", "-C", "/d", "&&&", "|&", ";;"]
    for _ in range(3000):
        command = "".join(rnd.choice(pieces) for _ in range(rnd.randint(1, 12)))
        legacy = command.replace("||", "\n").replace("&&", "\n").replace(";", "\n").replace("|", "\n")
        expect = [p.strip() for p in legacy.split("\n") if p.strip()] or [command]
        assert AL._bash_subcommands(command) == expect, repr(command)


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash as the oracle")
def test_the_scan_never_finds_fewer_commands_than_bash_runs():
    """Differential: bash runs each fragment-built command with every unknown word counted once; the
    splitter must find at least that many sub-commands (a lone `&` is no separator, as before, so the
    fragments hold none)."""
    rnd = random.Random(20261109)
    frags = ["git commit -m ", "x ", "y", " ", "a;b", ";", "&&", "||", "|", "\n", '"', "'", "$'", "\\", "\\'",
             '\\"', "#", " #", "q", "fix: ", "; ", " && ", " | ", "<<", "<<EOF\nbody\nEOF\n", "\\;", "\\\n"]
    harness = "command_not_found_handle(){ echo C; return 0; }\n"
    checked = 0
    for _ in range(1500):
        command = "".join(rnd.choice(frags) for _ in range(rnd.randint(1, 9)))
        if subprocess.run(["bash", "-n", "-c", command], capture_output=True).returncode != 0:
            continue
        ran = subprocess.run(["bash", "-c", harness + command], capture_output=True, text=True, timeout=10,
                             stdin=subprocess.DEVNULL).stdout.count("C\n")
        checked += 1
        assert len(AL._bash_subcommands(command)) >= ran, repr(command)
    assert checked > 100


# --------------------------------------------------------------------------------------------
# The /allow grant matcher
# --------------------------------------------------------------------------------------------

@pytest.fixture
def grants(tmp_path, monkeypatch):
    monkeypatch.setattr(AL, "SENTINEL_GRANT_DIR", str(tmp_path / "claude-grants"))

    def write(ops, task=TASK):
        AL.write_sentinel_grant(task, "sess", ops)

    return write


@pytest.mark.parametrize("command", ONE[:16])
def test_a_commit_grant_covers_a_commit_with_a_separator_in_its_message(grants, command):
    grants([{"op": "git", "target": "commit"}])
    assert AL.match_sentinel_grant_for_bash_command(TASK, command) is not None


@pytest.mark.parametrize("command,_parts", TWO[:12])
def test_a_commit_grant_covers_no_second_command(grants, command, _parts):
    grants([{"op": "git", "target": "commit"}])
    assert AL.match_sentinel_grant_for_bash_command(TASK, command) is None


def test_the_grant_stays_bound_to_its_task_and_its_operation(grants):
    grants([{"op": "git", "target": "commit"}], task="other-task")
    command = 'git -C /d commit -m "fix(x): a; b"'
    assert AL.match_sentinel_grant_for_bash_command(TASK, command) is None
    grants([{"op": "git", "target": "push"}])
    assert AL.match_sentinel_grant_for_bash_command(TASK, command) is None
    grants([{"op": "echo"}])
    assert AL.match_sentinel_grant_for_bash_command(TASK, command) is None
    grants([{"op": "git", "target": "commit"}])
    assert AL.match_sentinel_grant_for_bash_command(TASK, command) is not None
    # a code-carrying global option still never inherits the shorter grant
    assert AL.match_sentinel_grant_for_bash_command(TASK, 'git -c core.pager=x commit -m "a; b"') is None


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
    monkeypatch.setattr(AL, "SENTINEL_GRANT_DIR", str(state / "claude-grants"))
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
             "minted_by": {"origin": CP.PIPELINE_ORIGIN}}
    path = Path(os.environ["CLAUDE_STATE_DIR"]) / f"claude-commit-grant-{SID}-{nonce}.json"
    path.write_text(json.dumps(grant))
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


GUARD_HOOKS = ["pretool-git-privilege-guard.py", "pretool-bash-safety.sh", "pretool-block-branch-pr-worktree.py",
               "pretool-push-analyst-grant-guard.py"]


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


@pytest.mark.parametrize("template", MESSAGES)
def test_the_hooks_let_a_main_agent_with_an_allow_grant_commit_with_a_separator_in_the_message(world, template):
    repo = make_repo(world / "repo")
    AL.write_sentinel_grant(SID, SID, [{"op": "git", "target": "commit"}])
    command = template.replace("{R}", str(repo)).replace("{M}", str(message_file(world)))
    assert refused(replay(command, repo)) == {}


@pytest.mark.parametrize("tail", ['; rm x', ' && rm x', ' || rm x', ' | tee x', '\nrm x'])
def test_the_hooks_still_refuse_a_second_command_after_the_message(world, tail):
    repo = make_repo(world / "repo")
    AL.write_sentinel_grant(SID, SID, [{"op": "git", "target": "commit"}])
    command = f'git -C "{repo}" commit -m "fix(x): a; b"{tail}'
    assert "pretool-git-privilege-guard.py" in refused(replay(command, repo))


def test_the_hooks_still_require_the_grant_and_its_task(world):
    repo = make_repo(world / "repo")
    command = f'git -C "{repo}" commit -m "fix(x): a; b"'
    assert "pretool-git-privilege-guard.py" in refused(replay(command, repo))         # no grant at all
    AL.write_sentinel_grant("some-other-task", SID, [{"op": "git", "target": "commit"}])
    assert "pretool-git-privilege-guard.py" in refused(replay(command, repo))         # another task's grant
    AL.write_sentinel_grant(SID, SID, [{"op": "git", "target": "push"}])
    assert "pretool-git-privilege-guard.py" in refused(replay(command, repo))         # another operation's


def test_the_allow_grant_is_spent_by_the_commit_it_let_through(world):
    """PostToolUse asks the same matcher, so a quoted-separator commit consumes the grant it matched."""
    repo = make_repo(world / "repo")
    path = AL.write_sentinel_grant(SID, SID, [{"op": "git", "target": "commit"}])
    command = f'git -C "{repo}" commit -m "fix(x): a; b"'
    payload = {"tool_name": "Bash", "session_id": SID, "cwd": str(repo), "hook_event_name": "PostToolUse",
               "tool_use_id": "toolu_fr2post", "tool_input": {"command": command},
               "tool_response": {"stdout": "", "stderr": "", "interrupted": False}}
    proc = subprocess.run([sys.executable, str(HOOKS / "posttool-allowlist-consume.py")], input=json.dumps(payload),
                          capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                          cwd=str(repo), timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert not path.exists()


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
