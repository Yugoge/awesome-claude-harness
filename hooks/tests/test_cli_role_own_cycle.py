"""P6 R4: the hooks that compare a role take it from Claude Code's record and
their cycle from the agent's own dispatch obligation.

subagentstop-e2e-enforce.py (qa), subagentstop-codex-enforce.py and its ledger
producer posttool-codex-skill-ledger.py read the role through
lib.agent_resolver.resolve_agent_type and the cycle registry through
lib/agent_cycle.py: the registry the obligation's task id names, else the
dispatching session's (/dev-overnight's), and agent-index.json only for a
dispatch without an obligation. pretool-overnight-hook-guard.py binds a child
to the session that dispatched it, reading an index entry only for a dispatch
without an obligation. So a QA that Read dev.json is still judged as a QA, and
codex enforcement, the e2e flag gate and the overnight child binding keep
working for agents no index names (acceptance A6).

The cycle is set up as /dev sets it up: scripts/write-enforce-flag.sh arms
.claude/dev-registry/dev-<ts>/, each dispatch has its transcript, its CLI meta
file and its Agent call in the parent transcript, and payloads carry agent_id
and agent_type.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "hooks"
TS = "20261012-000000"
CYCLE = f"dev-{TS}"
SESSION = "p6-r4-session"


class Cycle:
    """A project, its transcript store and the hooks run against them."""

    def __init__(self, tmp_path: Path, session: str = SESSION):
        self.project = tmp_path / "project"
        self.project.mkdir(parents=True, exist_ok=True)
        self.config = tmp_path / "home" / ".claude"
        self.session = session
        slug = str(self.project.resolve()).replace("/", "-")
        self.store = self.config / "projects" / slug
        self.env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.project), "HOME": str(tmp_path / "home"),
                    "CLAUDE_CONFIG_DIR": str(self.config), "PYTHONDONTWRITEBYTECODE": "1"}
        self.env.pop("CLAUDE_RESTART_ACCOUNTS_ROOT", None)

    def arm(self, name: str = CYCLE, command: str = "dev") -> Path:
        """The registry's flags, written by the one writer /dev's start runs."""
        subprocess.run([str(REPO / "scripts" / "write-enforce-flag.sh"), "--source-command", command,
                        "--session-id", name, "--flag", "e2e", "--flag", "artifact-contract", "--flag", "codex"],
                       check=True, capture_output=True, env=self.env, timeout=30)
        return self.project / ".claude" / "dev-registry" / name

    def dispatch(self, agent_id: str, role: str, prompt: str) -> Path:
        """The subagent's transcript and meta file, and the parent's Agent call."""
        subagents = self.store / self.session / "subagents"
        subagents.mkdir(parents=True, exist_ok=True)
        transcript = subagents / f"agent-{agent_id}.jsonl"
        transcript.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n",
                              encoding="utf-8")
        call = f"toolu_{agent_id}"
        (subagents / f"agent-{agent_id}.meta.json").write_text(
            json.dumps({"agentType": role, "toolUseId": call}), encoding="utf-8")
        record = {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": call, "name": "Agent",
             "input": {"description": role, "prompt": prompt, "subagent_type": role}}]}}
        with open(self.store / f"{self.session}.jsonl", "a", encoding="utf-8") as parent:
            parent.write(json.dumps(record) + "\n")
        return transcript

    def index(self, agent_id: str, role: str, name: str = CYCLE) -> None:
        """An agent-index.json entry as origin/master's check-in wrote it."""
        path = self.project / ".claude" / "dev-registry" / "agent-index.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({agent_id: {"agent_type": role, "dev_session_id": name}}), encoding="utf-8")

    def hook(self, name: str, payload: dict) -> subprocess.CompletedProcess:
        payload = {"session_id": self.session, **payload}
        return subprocess.run([sys.executable, str(HOOKS / name)], input=json.dumps(payload),
                              capture_output=True, text=True, env=self.env, timeout=60)

    def stop(self, name: str, agent_id: str, role: str, transcript: Path | None = None):
        payload = {"hook_event_name": "SubagentStop", "agent_id": agent_id, "agent_type": role}
        if transcript is not None:
            payload["agent_transcript_path"] = str(transcript)
        return self.hook(name, payload)

    def codex_call(self, agent_id: str, role: str) -> subprocess.CompletedProcess:
        return self.hook("posttool-codex-skill-ledger.py", {
            "hook_event_name": "PostToolUse", "agent_id": agent_id, "agent_type": role, "tool_name": "Skill",
            "tool_input": {"skill": "codex"}, "tool_response": {"output": "ok"}, "tool_use_id": "toolu_codex"})


def _obligation(role: str, profile: str, schema: str, path: str, task: str = TS, pipeline: str = "dev") -> str:
    doc = {"task_id": task, "lane": None, "lane_set": None, "role": role, "pipeline": pipeline,
           "profile": profile, "dispatched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "artifacts": [{"kind": "json", "path": path, "schema": schema, "identity": {"task_id": task}}]}
    return f'<obligation v="1">\n{json.dumps(doc)}\n</obligation>'


def _dev_prompt(task: str = TS, pipeline: str = "dev") -> str:
    return (_obligation("dev", "overnight" if pipeline == "dev-overnight" else "singular", "dev-report.v2",
                        f"docs/dev/dev-report-{task}.json", task, pipeline)
            + "\ncodex_required: true\nImplement the change.")


def _qa_prompt(task: str = TS, pipeline: str = "dev") -> str:
    return (_obligation("qa", "final_verification", "qa-report.v2", f"docs/dev/qa-report-{task}.json", task, pipeline)
            + "\nVerify the cycle.")


def _qa_report(cycle: Cycle, status: str, task: str = TS) -> None:
    path = cycle.project / "docs" / "dev" / f"qa-report-{task}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"task_id": task, "request_id": task, "qa": {"e2e_enforcement": {"status": status}}}),
                    encoding="utf-8")


# --------------------------------------------------------------------------- codex


def test_codex_dev_is_bound_without_an_index_entry_and_its_skill_call_releases_it(tmp_path):
    cycle = Cycle(tmp_path)
    registry = cycle.arm()
    transcript = cycle.dispatch("a-dev1", "dev", _dev_prompt())

    blocked = cycle.stop("subagentstop-codex-enforce.py", "a-dev1", "dev", transcript)
    assert blocked.returncode == 2, blocked.stderr
    assert f"CODEX_ENFORCE_BLOCKED: agent a-dev1 (type=dev) has not called codex skill in session {CYCLE}" \
        in blocked.stderr

    assert cycle.codex_call("a-dev1", "dev").returncode == 0
    entry = json.loads((registry / "codex-ledger" / "a-dev1.json").read_text(encoding="utf-8"))
    assert (entry["dev_session_id"], entry["agent_type"]) == (CYCLE, "dev")
    released = cycle.stop("subagentstop-codex-enforce.py", "a-dev1", "dev", transcript)
    assert released.returncode == 0, released.stderr


def test_codex_pre_pull_index_entry_names_the_cycle_and_the_cli_role_wins(tmp_path):
    """A dispatch carrying no obligation (made before the pull) whose index
    entry names another role: the entry names its cycle, the payload its role."""
    cycle = Cycle(tmp_path)
    registry = cycle.arm()
    transcript = cycle.dispatch("a-dev2", "dev", "Implement the change.\ncodex_required: true")
    cycle.index("a-dev2", "qa")

    blocked = cycle.stop("subagentstop-codex-enforce.py", "a-dev2", "dev", transcript)
    assert blocked.returncode == 2, blocked.stderr
    assert f"agent a-dev2 (type=dev) has not called codex skill in session {CYCLE}" in blocked.stderr
    assert cycle.codex_call("a-dev2", "dev").returncode == 0
    assert json.loads((registry / "codex-ledger" / "a-dev2.json").read_text(encoding="utf-8"))["agent_type"] == "dev"
    assert cycle.stop("subagentstop-codex-enforce.py", "a-dev2", "dev", transcript).returncode == 0


def test_codex_obligation_wins_over_a_pre_pull_index_entry(tmp_path):
    """An index entry naming another cycle (the agent Read that cycle's
    sentinel before the pull) does not move an agent its obligation places."""
    cycle = Cycle(tmp_path)
    cycle.arm()
    other = cycle.project / ".claude" / "dev-registry" / "dev-20261011-000000"
    other.mkdir(parents=True)
    transcript = cycle.dispatch("a-dev3", "dev", _dev_prompt())
    cycle.index("a-dev3", "qa", other.name)

    blocked = cycle.stop("subagentstop-codex-enforce.py", "a-dev3", "dev", transcript)
    assert blocked.returncode == 2, blocked.stderr
    assert f"in session {CYCLE}" in blocked.stderr


# --------------------------------------------------------------------------- e2e


def test_e2e_qa_is_judged_also_after_it_read_dev_json(tmp_path):
    cycle = Cycle(tmp_path)
    registry = cycle.arm()
    transcript = cycle.dispatch("a-qa1", "qa", _qa_prompt())
    _qa_report(cycle, "skipped_without_justification")

    first = cycle.stop("subagentstop-e2e-enforce.py", "a-qa1", "qa", transcript)
    assert first.returncode == 2, first.stderr
    assert "E2E_ENFORCE_BLOCKED: agent a-qa1 (type=qa)" in first.stderr

    read = cycle.hook("pretool-cp-checkin.py", {"hook_event_name": "PreToolUse", "agent_id": "a-qa1",
                                                "agent_type": "qa", "tool_name": "Read",
                                                "tool_input": {"file_path": str(registry / "dev.json")}})
    assert read.returncode == 0, read.stderr
    after_read = cycle.stop("subagentstop-e2e-enforce.py", "a-qa1", "qa", transcript)
    assert after_read.returncode == 2, after_read.stderr

    # The entry origin/master's check-in wrote for that Read: the CLI role wins.
    cycle.index("a-qa1", "dev")
    pre_pull = cycle.stop("subagentstop-e2e-enforce.py", "a-qa1", "qa", transcript)
    assert pre_pull.returncode == 2, pre_pull.stderr
    assert f"E2E_ENFORCE_BLOCKED: agent a-qa1 (type=qa) in session {CYCLE}" in pre_pull.stderr

    _qa_report(cycle, "performed")
    assert cycle.stop("subagentstop-e2e-enforce.py", "a-qa1", "qa", transcript).returncode == 0


def test_e2e_pre_pull_dispatch_without_obligation_resolves_its_cycle(tmp_path):
    cycle = Cycle(tmp_path)
    cycle.arm()
    transcript = cycle.dispatch("a-qa2", "qa", "Verify the cycle.")
    cycle.index("a-qa2", "dev")
    _qa_report(cycle, "skipped_without_justification")

    proc = cycle.stop("subagentstop-e2e-enforce.py", "a-qa2", "qa", transcript)
    assert proc.returncode == 2, proc.stderr
    assert f"(type=qa) in session {CYCLE} has e2e_enforcement.status='skipped_without_justification'" in proc.stderr


def test_e2e_flag_gate_holds_without_an_index_entry(tmp_path):
    cycle = Cycle(tmp_path)
    transcript = cycle.dispatch("a-qa3", "qa", _qa_prompt())
    _qa_report(cycle, "skipped_without_justification")
    (cycle.project / ".claude" / "dev-registry" / CYCLE).mkdir(parents=True)
    assert cycle.stop("subagentstop-e2e-enforce.py", "a-qa3", "qa", transcript).returncode == 0


def test_another_cli_role_is_not_judged_as_qa(tmp_path):
    """The CLI names it dev; a QA obligation in its prompt does not make it QA."""
    cycle = Cycle(tmp_path)
    cycle.arm()
    transcript = cycle.dispatch("a-dev4", "dev", _qa_prompt())
    _qa_report(cycle, "skipped_without_justification")
    assert cycle.stop("subagentstop-e2e-enforce.py", "a-dev4", "dev", transcript).returncode == 0


# --------------------------------------------------------------------------- /dev-overnight


def test_overnight_children_use_their_sessions_registry(tmp_path):
    """/dev-overnight arms its registry under its session id; its dispatches'
    task ids (<ts>-<n>) name no registry, so their cycle is that session's."""
    cycle = Cycle(tmp_path, session="p6-r4-overnight")
    registry = cycle.arm(cycle.session, "dev-overnight")
    task = f"{TS}-1"
    qa = cycle.dispatch("a-oqa", "qa", _qa_prompt(task, "dev-overnight"))
    _qa_report(cycle, "skipped_without_justification", task)
    assert cycle.stop("subagentstop-e2e-enforce.py", "a-oqa", "qa", qa).returncode == 2

    dev = cycle.dispatch("a-odev", "dev", _dev_prompt(task, "dev-overnight"))
    assert cycle.stop("subagentstop-codex-enforce.py", "a-odev", "dev", dev).returncode == 2
    assert cycle.codex_call("a-odev", "dev").returncode == 0
    assert (registry / "codex-ledger" / "a-odev.json").is_file()
    assert cycle.stop("subagentstop-codex-enforce.py", "a-odev", "dev", dev).returncode == 0


def _guard(monkeypatch, cycle: Cycle):
    for key in ("CLAUDE_PROJECT_DIR", "HOME", "CLAUDE_CONFIG_DIR"):
        monkeypatch.setenv(key, cycle.env[key])
    path = HOOKS / "pretool-overnight-hook-guard.py"
    spec = importlib.util.spec_from_file_location("overnight_guard_r4", path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(HOOKS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(HOOKS))
    return module


def _overnight_state(cycle: Cycle, session: str) -> None:
    worktree = cycle.project / ".claude" / "worktrees" / session
    worktree.mkdir(parents=True)
    (cycle.project / ".claude" / f"overnight-state-{session}.json").write_text(json.dumps({
        "schema_version": 9, "session_id": session, "isolation_kind": "isolated",
        "main_root": str(cycle.project), "main_git_dir": str(cycle.project / ".git"),
        "worktree_path": str(worktree), "worktree_branch": "work-branch", "protected_branch": "master",
        "end_time": "2099-01-01T00:00:00Z", "isolation_active_until": "2099-01-01T00:00:00Z",
        "current_cycle": 1}), encoding="utf-8")


def test_overnight_dev_child_resolves_its_sessions_state(tmp_path, monkeypatch):
    cycle = Cycle(tmp_path, session="p6-r4-overnight")
    _overnight_state(cycle, cycle.session)
    _overnight_state(cycle, "p6-r4-other")
    cycle.dispatch("a-child", "dev", _dev_prompt(f"{TS}-1", "dev-overnight"))
    guard = _guard(monkeypatch, cycle)
    child = {"agent_id": "a-child", "agent_type": "dev", "session_id": cycle.session}

    assert guard._resolve_child_session(child)["session_id"] == cycle.session
    # An entry naming another session (a sentinel Read before the pull) does
    # not move a child its own obligation places.
    cycle.index("a-child", "qa", "p6-r4-other")
    assert guard._resolve_child_session(child)["session_id"] == cycle.session
    # A payload whose own dispatch cannot be read keeps the pre-pull binding.
    assert guard._resolve_child_session({**child, "session_id": ""})["session_id"] == "p6-r4-other"
