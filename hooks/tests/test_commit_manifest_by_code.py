"""/commit's dispatch-snapshot manifest is written by code: Step 5's plan call (scripts/steps/commit-plan.py)
writes it, the grant writer (scripts/write-commit-grant.py) mints from it, and the agent writes nothing.

The old text had the orchestrator write the manifest with the Write tool before every grant, while the
orchestrator gate allows one Write (and one Edit) per turn: a `/commit --auto` turn could mint grants for
about two tasks. Here a main session walks five tasks in one turn, each call through the hooks
settings.json registers, and mints five grants. A manifest a session holding the old text writes by hand
is still accepted.

HOME, config, state, project and TMPDIR live in tmp_path; the repositories are throwaway ones.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(HOOKS / "lib"))
import commit_pipeline  # noqa: E402

PRE = [HOOKS / "pretool-launch.py"]
PRE_BASH = PRE + [HOOKS / "pretool-bash-safety.sh"]
POST = HOOKS / "posttool-launch.py"
PLAN = 'python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/steps/commit-plan.py" --task-id '
MINT = 'python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/write-commit-grant.py" --task-id '
TASKS = [f"20990101-00000{i}" for i in range(1, 6)]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


class Session:
    """One main session in a throwaway world; each tool call runs as the CLI runs it."""

    def __init__(self, tmp: Path, prompt: str):
        self.tmp, self.sid, self.n = tmp, str(uuid.uuid4()), 0
        self.home, self.project, self.state = tmp / "home", tmp / "project", tmp / "state"
        for d in (self.state, tmp / "tmp", tmp / "attr"):
            d.mkdir(parents=True, exist_ok=True)
        self.project.mkdir()
        _git(self.project, "init", "-q")
        _git(self.project, "config", "user.email", "test@example.com")
        _git(self.project, "config", "user.name", "Test")
        (self.project / "seed.txt").write_text("seed\n", encoding="utf-8")
        _git(self.project, "add", "seed.txt")
        _git(self.project, "commit", "-q", "-m", "seed")
        tdir = self.home / ".claude" / "projects" / "-project"
        tdir.mkdir(parents=True)
        self.transcript = tdir / f"{self.sid}.jsonl"
        self.add({"type": "user", "message": {"role": "user", "content": prompt}})
        self.env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
                    "CLAUDE_HOME": str(ROOT), "CLAUDE_STATE_DIR": str(self.state), "TMPDIR": str(tmp / "tmp"),
                    "CLAUDE_PROJECT_DIR": str(self.project), "CLAUDE_CODE_SESSION_ID": self.sid,
                    "ATTRIBUTION_STATE_DIR": str(tmp / "attr"), "PYTHONDONTWRITEBYTECODE": "1"}
        submit = self.hook(HOOKS / "userprompt-launch.py", {"hook_event_name": "UserPromptSubmit", "prompt": prompt})
        assert submit.returncode == 0, submit.stderr

    def add(self, record: dict) -> None:
        with self.transcript.open("a") as handle:
            handle.write(json.dumps(record) + "\n")

    def hook(self, path: Path, body: dict):
        payload = {"session_id": self.sid, "transcript_path": str(self.transcript), "cwd": str(self.project),
                   "permission_mode": "default", **body}
        argv = ["bash", str(path)] if path.suffix == ".sh" else [sys.executable, str(path)]
        return subprocess.run(argv, input=json.dumps(payload), capture_output=True, text=True, env=self.env,
                              cwd=self.project, timeout=300)

    def call(self, tool: str, tool_input: dict) -> tuple[str | None, str]:
        """(the PreToolUse refusal or None, the call's output): the tool_use goes into the transcript, the
        registered PreToolUse hooks decide, the call runs (Bash commands for real), PostToolUse follows."""
        self.n += 1
        tid = f"toolu_{self.sid[:8]}{self.n:04d}"
        self.add({"type": "assistant", "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                  "message": {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": tool,
                                                                "input": tool_input}]}})
        body = {"tool_name": tool, "tool_input": tool_input, "tool_use_id": tid}
        refusals = [p.stderr for p in (self.hook(h, {"hook_event_name": "PreToolUse", **body})
                                       for h in (PRE_BASH if tool == "Bash" else PRE)) if p.returncode == 2]
        if refusals:
            self.add({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tid, "content": "".join(refusals), "is_error": True}]}})
            return "".join(refusals), ""
        output = "done"
        if tool == "Bash":
            run = subprocess.run(["bash", "-c", tool_input["command"]], capture_output=True, text=True,
                                 env=self.env, cwd=self.project, timeout=300)
            output = run.stdout + run.stderr
        elif tool == "Write":
            Path(tool_input["file_path"]).write_text(tool_input["content"], encoding="utf-8")
        post = self.hook(POST, {"hook_event_name": "PostToolUse", **body, "tool_response": {"stdout": output}})
        assert post.returncode in (0, 2), post.stderr
        self.add({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": output}]}})
        return None, output

    def task(self, task: str) -> None:
        """A closed task owning one changed file."""
        (self.project / f"{task}.txt").write_text("change\n", encoding="utf-8")
        dev = self.project / "docs" / "dev"
        dev.mkdir(parents=True, exist_ok=True)
        (dev / f"dev-report-{task}.json").write_text(json.dumps({
            "task_id": task, "request_id": task, "dev": {"files_modified": [f"{task}.txt"], "files_created": []},
            "owned_edits": {f"{task}.txt": [{"old": "x", "new": "y"}]}}), encoding="utf-8")
        (dev / f"close-report-{task}.md").write_text("# Close\n\nCLOSE: YES\n", encoding="utf-8")

    def grants(self) -> list[dict]:
        return [json.loads(p.read_text()) for p in self.state.glob(f"claude-commit-grant-{self.sid}-*.json")]

    def plan(self, task: str) -> dict:
        refused, out = self.call("Bash", {"command": PLAN + task, "description": "Plan the commit"})
        assert refused is None, refused
        return json.loads(out[out.index("{"):])

    def mint(self, task: str) -> str:
        refused, out = self.call("Bash", {"command": f"{MINT}{task} --repo-root {self.project}",
                                          "description": "Mint the commit grant"})
        assert refused is None, refused
        return out


@pytest.fixture()
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp_path / "state"))
    return Session(tmp_path, "/commit --auto")


def test_the_plan_call_writes_the_manifest_the_minter_mints_from(session):
    task = TASKS[0]
    session.task(task)
    out = session.plan(task)
    written = Path(commit_pipeline.planned_manifest_path(session.sid))
    manifest = json.loads(written.read_text(encoding="utf-8"))
    assert manifest == {"session_id": session.sid, "task_id": task, "repository_plan": out["repository_plan"],
                        "files_at_dispatch": out["files_at_dispatch"]}
    assert not Path(commit_pipeline.manifest_path(session.sid)).exists()  # nothing written by hand
    printed = session.mint(task)
    [grant] = session.grants()
    assert grant["task_id"] == task, printed
    assert grant["minted_by"]["evidence"]["manifest_path"] == str(written)


def test_step_5_as_written_mints_with_nothing_written_by_the_agent(session):
    """Step 5's own commands (its BULK=false bash blocks: the plan, then the mint), run in order through the
    hooks, are all the agent does: the plan's manifest is the one minted from, and no Write came between."""
    task = TASKS[0]
    session.task(task)
    text = (ROOT / "commands" / "commit.md").read_text(encoding="utf-8")
    plan, mint = re.findall(r"```bash\n(.*?)\n```", text[text.index("### Step 5"):text.index("### Step 6")], re.S)
    refused, out = session.call("Bash", {"command": plan.replace('"$TASK_ID"', task)})
    assert refused is None, refused
    [entry] = json.loads(out[out.index("{"):])["repository_plan"]["repositories"]
    refused, printed = session.call("Bash", {"command": mint.replace('"$TASK_ID"', task)
                                             .replace('"$PLANNED_REPO_ROOT"', entry["repo_root"])})
    [grant] = session.grants()
    assert refused is None and grant["task_id"] == task, (refused, printed)
    assert grant["minted_by"]["evidence"]["manifest_path"] == commit_pipeline.planned_manifest_path(session.sid)
    assert not Path(commit_pipeline.manifest_path(session.sid)).exists()  # nothing written by hand


def test_a_manifest_written_by_hand_with_the_old_text_is_not_refused(session):
    """The old Step 5: plan, then the Write tool writes manifest_path, then the mint."""
    task = TASKS[0]
    session.task(task)
    out = session.plan(task)
    Path(commit_pipeline.planned_manifest_path(session.sid)).unlink()  # only the hand-written one stands
    body = {"session_id": session.sid, "task_id": task, "repository_plan": out["repository_plan"],
            "files_at_dispatch": out["files_at_dispatch"]}
    refused, _ = session.call("Write", {"file_path": out["manifest_path"], "content": json.dumps(body)})
    assert refused is None, refused
    session.mint(task)
    [grant] = session.grants()
    assert grant["minted_by"]["evidence"]["manifest_path"] == out["manifest_path"]


def test_a_hand_written_manifest_beside_the_plan_calls_is_not_refused(session):
    """A session with the old text writes its manifest after the new plan call wrote one."""
    task = TASKS[0]
    session.task(task)
    out = session.plan(task)
    body = {"session_id": session.sid, "task_id": task, "repository_plan": out["repository_plan"]}
    assert session.call("Write", {"file_path": out["manifest_path"], "content": json.dumps(body)})[0] is None
    session.mint(task)
    assert [g["task_id"] for g in session.grants()] == [task]


def test_a_plan_manifest_for_another_task_still_refuses(session):
    task = TASKS[0]
    session.task(task)
    session.plan(task)
    # the plan call's manifest names another task: no hand manifest, the mint is refused with its reason
    planned = Path(commit_pipeline.planned_manifest_path(session.sid))
    planned.write_text(json.dumps({**json.loads(planned.read_text()), "task_id": "20990101-999999"}))
    out = session.mint(task)
    assert not session.grants() and "is for task '20990101-999999'" in out, out


def test_commit_auto_over_five_tasks_mints_five_grants_in_one_turn(session):
    """Per task: the plan call, the mint, the analyst's dispatch; no Write or Edit; nothing refused."""
    for task in TASKS:
        session.task(task)
    for task in TASKS:
        assert session.plan(task)["repository_plan"]["repositories"], task
        session.mint(task)
        refused, _ = session.call("Agent", {"subagent_type": "changelog-analyst", "description": "Commit",
                                            "prompt": f"TASK_ID={task}", "run_in_background": False})
        assert refused is None, refused
    assert sorted(g["task_id"] for g in session.grants()) == TASKS


def test_control_the_old_text_meets_the_per_turn_write_cap(session):
    """The same hooks refuse the old text's second hand-written manifest of the turn: the cap is live here."""
    outcomes = []
    for task in TASKS[:2]:
        session.task(task)
        out = session.plan(task)
        Path(out["manifest_path"]).unlink(missing_ok=True)  # (the write guard refuses a Write over an existing file)
        outcomes.append(session.call("Write", {"file_path": out["manifest_path"], "content": "{}"})[0])
    assert outcomes[0] is None and "Write used consecutively beyond limit (2/1)" in (outcomes[1] or ""), outcomes
