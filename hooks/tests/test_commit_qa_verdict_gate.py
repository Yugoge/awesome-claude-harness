"""The pre-commit QA verdict must decide whether a /commit grant can be spent.

What it pins (each case is a commit by the changelog-analyst the pipeline dispatched, with
a live grant of pipeline provenance and a hook-written dispatch attestation, i.e. every
other check the privilege guard makes passes):

  * a commit-qa-report whose last line is `COMMIT: REJECT - ...`   -> refused
  * no commit-qa-report at all                                     -> refused
  * a `COMMIT: APPROVE` older than the plan the grant was minted on -> refused (earlier attempt)
  * a fresh `COMMIT: APPROVE`                                      -> allowed (control)
  * /commit --bulk: the main agent's own `auto-bulk:` commit       -> refused
  * /commit --bulk: the analyst needs this run's approval on the bulk report

The location the test puts the verdict at is the one commands/commit.md names:
docs/dev/commit-qa-report-<TASK_ID or "bulk">.md in the control root's repository (here the
one repository of the plan).
"""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
# The guard under test; a red run points it at an older copy of the file.
GUARD = Path(os.environ.get("COMMIT_QA_VERDICT_GUARD") or HOOKS / "pretool-git-privilege-guard.py")
TASK = "20261028-100000"
SID = "sid-orchestrator"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def world(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (tmp_path / "project").mkdir()
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(state))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "project"))
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "CLAUDE_SESSION_ID",
                 "CLAUDE_CODE_SESSION_ID", "CLAUDE_TASK_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.syspath_prepend(str(HOOKS))
    import lib.commit_journal as CJ  # noqa: PLC0415
    import lib.commit_pipeline as CP  # noqa: PLC0415
    monkeypatch.setattr(CJ, "JOURNAL_ROOT", str(tmp_path / "commit-events"))
    monkeypatch.setattr(CJ, "POINTER_TEMPLATE", str(state / (CJ.POINTER_PREFIX + "{key}.json")))
    monkeypatch.setattr(CJ, "POINTER_GLOB", str(state / (CJ.POINTER_PREFIX + "*.json")))
    guard = _load(GUARD, "guard_commit_qa_verdict")
    return {"tmp": tmp_path, "state": state, "CP": CP, "guard": guard}


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def make_repo(path):
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "master")
    git(path, "config", "user.email", "t@example.invalid")
    git(path, "config", "user.name", "test")
    git(path, "config", "commit.gpgsign", "false")
    (path / "f.txt").write_text("base\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "base")
    (path / "f.txt").write_text("change\n")
    return path


def session_dir():
    slug = str(Path(os.environ["CLAUDE_PROJECT_DIR"]).resolve()).replace("/", "-")
    return Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / slug


def mint(w, repo, manifest_at):
    """A grant shaped as scripts/write-commit-grant.py writes it, evidence included."""
    now = datetime.now(timezone.utc)
    nonce = os.urandom(8).hex()
    grant = {"task_id": TASK, "sid": SID, "nonce": nonce, "repo_root": git(repo, "rev-parse", "--show-toplevel"),
             "branch": git(repo, "branch", "--show-current"), "expected_head": git(repo, "rev-parse", "HEAD"),
             "created_at": (now - timedelta(seconds=2)).isoformat(),
             "expires_at": (now + timedelta(minutes=30)).isoformat(),
             "minted_by": {"origin": w["CP"].PIPELINE_ORIGIN,
                           "evidence": {"manifest_dispatched_at": manifest_at.isoformat(),
                                        "plan_repo_root": str(repo)}}}
    path = w["state"] / f"claude-commit-grant-{SID}-{nonce}.json"
    path.write_text(json.dumps(grant))
    return path


def dispatch(w, prompt):
    """The records a real changelog-analyst dispatch leaves (as hooks/tests/test_commit_event_pointer.py)."""
    w["CP"].write_attestation(SID, task_id=TASK, dryrun=False,
                              prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest())
    root = session_dir()
    agent_id = "a" + os.urandom(8).hex()
    tool_use_id = "toolu_" + os.urandom(8).hex()
    (root / SID / "subagents").mkdir(parents=True, exist_ok=True)
    with open(root / f"{SID}.jsonl", "a") as handle:
        handle.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tool_use_id, "name": "Agent",
             "input": {"subagent_type": "changelog-analyst", "prompt": prompt}}]}}) + "\n")
    (root / SID / "subagents" / f"agent-{agent_id}.jsonl").write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
    (root / SID / "subagents" / f"agent-{agent_id}.meta.json").write_text(
        json.dumps({"agentType": "changelog-analyst", "toolUseId": tool_use_id}))
    return agent_id


def verdict(repo, line, mtime=None, name=TASK):
    report = Path(repo) / "docs" / "dev" / f"commit-qa-report-{name}.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(f"# pre-commit QA\n\n- f.txt: reviewed\n\n{line}\n")
    if mtime is not None:
        os.utime(report, (mtime, mtime))
    return report


def evaluate(w, repo, agent_id, message=f"fix: change\n\nTask-id: {TASK}\n", agent=True):
    msg = Path(repo).parent / "msg.txt"
    msg.write_text(message)
    payload = {"tool_name": "Bash", "session_id": SID, "cwd": str(repo), "tool_use_id": "toolu_commit",
               "transcript_path": str(session_dir() / f"{SID}.jsonl"),
               "tool_input": {"command": f'git -C {repo} add -A && git -C {repo} commit -F "{msg}"'}}
    if agent:
        payload.update(agent_id=agent_id, agent_type="changelog-analyst")
    try:
        w["guard"]._evaluate_commit(payload["tool_input"]["command"], payload)
    except SystemExit as exc:
        return exc.code
    return 0


PROMPT = f"TASK_ID={TASK}\nDRYRUN=false\n<obligation v=\"1\">{{}}</obligation>"


def test_control_a_fresh_approve_is_spent(world):
    repo = make_repo(world["tmp"] / "toy")
    grant = mint(world, repo, datetime.now(timezone.utc) - timedelta(seconds=30))
    analyst = dispatch(world, PROMPT)
    verdict(repo, "COMMIT: APPROVE")
    assert evaluate(world, repo, analyst) == 0
    assert not grant.exists(), "the approved commit spends its grant"


def test_a_reject_verdict_refuses_the_commit(world):
    repo = make_repo(world["tmp"] / "toy")
    grant = mint(world, repo, datetime.now(timezone.utc) - timedelta(seconds=30))
    analyst = dispatch(world, PROMPT)
    verdict(repo, "COMMIT: REJECT - f.txt is not ready to land")
    assert evaluate(world, repo, analyst) == 2, "a commit after COMMIT: REJECT was admitted"
    assert grant.exists(), "a refused commit must not spend the grant"


def test_a_missing_verdict_refuses_the_commit(world):
    repo = make_repo(world["tmp"] / "toy")
    mint(world, repo, datetime.now(timezone.utc) - timedelta(seconds=30))
    analyst = dispatch(world, PROMPT)
    assert evaluate(world, repo, analyst) == 2, "a commit with no pre-commit QA verdict was admitted"


def test_an_approve_of_an_earlier_attempt_refuses_the_commit(world):
    repo = make_repo(world["tmp"] / "toy")
    plan_at = datetime.now(timezone.utc) - timedelta(seconds=30)
    mint(world, repo, plan_at)
    analyst = dispatch(world, PROMPT)
    verdict(repo, "COMMIT: APPROVE", mtime=(plan_at - timedelta(minutes=10)).timestamp())
    assert evaluate(world, repo, analyst) == 2, "an APPROVE older than the plan the grant was minted on was honoured"


def bulk_sentinel(w, created_at):
    CP = w["CP"]
    sentinel = w["state"] / f"{CP.BULK_SENTINEL_PREFIX}{SID}-{os.urandom(8).hex()}.json"
    sentinel.write_text(json.dumps({"kind": CP.BULK_SENTINEL_KIND, "origin": CP.BULK_SENTINEL_ORIGIN,
                                    "sid": SID, "created_at": created_at.isoformat(),
                                    "expires_at": (created_at + timedelta(minutes=30)).isoformat()}))
    return sentinel


BULK = "auto-bulk: end-of-cycle commit for master\n"


def test_bulk_main_agent_auto_bulk_commit_is_refused(world):
    """/commit --bulk: a live bulk sentinel, a REJECT on the bulk report, and the main agent (no agent_id,
    no changelog-analyst dispatch) commits with the auto-bulk subject."""
    repo = make_repo(world["tmp"] / "toy")
    bulk_sentinel(world, datetime.now(timezone.utc))
    verdict(repo, "COMMIT: REJECT - f.txt is junk", name="bulk")
    code = evaluate(world, repo, "", message=BULK, agent=False)
    assert code == 2, "the main agent's own auto-bulk commit was admitted after COMMIT: REJECT"


@pytest.mark.parametrize("line, age, admitted", [
    ("COMMIT: APPROVE", None, True),                                  # the analyst, this run's approval
    ("COMMIT: REJECT - f.txt is junk", None, False),                  # the analyst after a rejection
    ("COMMIT: APPROVE", timedelta(minutes=10), False),                # an approval of an earlier bulk run
])
def test_bulk_needs_the_analyst_and_this_runs_approval(world, line, age, admitted):
    repo = make_repo(world["tmp"] / "toy")
    opened = datetime.now(timezone.utc) - timedelta(seconds=30)
    bulk_sentinel(world, opened)
    verdict(repo, line, name="bulk", mtime=None if age is None else (opened - age).timestamp())
    code = evaluate(world, repo, "a" + os.urandom(8).hex(), message=BULK)
    assert (code == 0) is admitted, (line, age, code)


def test_bulk_main_agent_is_refused_even_after_an_approval(world):
    repo = make_repo(world["tmp"] / "toy")
    bulk_sentinel(world, datetime.now(timezone.utc) - timedelta(seconds=30))
    verdict(repo, "COMMIT: APPROVE", name="bulk")
    assert evaluate(world, repo, "", message=BULK, agent=False) == 2


def test_the_refusal_names_the_report_and_its_verdict(world, capsys):
    repo = make_repo(world["tmp"] / "toy")
    mint(world, repo, datetime.now(timezone.utc) - timedelta(seconds=30))
    analyst = dispatch(world, PROMPT)
    verdict(repo, "COMMIT: REJECT - f.txt is not ready to land")
    assert evaluate(world, repo, analyst) == 2
    err = capsys.readouterr().err
    assert f"commit-qa-report-{TASK}.md" in err and "COMMIT: REJECT - f.txt is not ready to land" in err, err


def test_the_refusal_is_recorded_and_the_owners_allow_releases_it(world):
    """A refusal like any other: the pre-tool launcher records it, and the owner's /allow releases the next one."""
    repo = make_repo(world["tmp"] / "toy")
    mint(world, repo, datetime.now(timezone.utc) - timedelta(seconds=30))
    analyst = dispatch(world, PROMPT)
    verdict(repo, "COMMIT: REJECT - f.txt is not ready to land")
    msg = Path(repo).parent / "msg.txt"
    msg.write_text(f"fix: change\n\nTask-id: {TASK}\n")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

    def launch(n):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": SID, "cwd": str(repo),
                   "tool_use_id": f"toolu_commit_{n}", "agent_id": analyst, "agent_type": "changelog-analyst",
                   "transcript_path": str(session_dir() / f"{SID}.jsonl"),
                   "tool_input": {"command": f'git -C {repo} commit -F "{msg}"'}}
        return subprocess.run([sys.executable, str(HOOKS / "pretool-launch.py")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=600)

    first = launch(1)
    assert first.returncode == 2 and "the pre-commit review does not approve this commit" in first.stderr, first
    rows = [json.loads(line) for f in Path(os.environ["HOME"]).rglob("refusals-*.jsonl")
            for line in f.read_text().splitlines() if line.strip()]
    assert any(r.get("tool_use_id") == "toolu_commit_1" and r.get("kind") != "released" for r in rows), rows
    owner = {"hook_event_name": "UserPromptSubmit", "session_id": SID, "prompt": "/allow", "cwd": str(repo)}
    typed = subprocess.run(["bash", str(HOOKS / "userprompt-consent-allowlist.sh")], input=json.dumps(owner),
                           capture_output=True, text=True, env=env, timeout=60)
    assert typed.returncode == 0, typed.stderr
    second = launch(2)
    assert second.returncode == 0 and "RELEASED" in second.stdout, second
