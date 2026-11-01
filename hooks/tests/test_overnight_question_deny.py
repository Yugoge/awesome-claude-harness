"""The overnight AskUserQuestion deny (P2 R10, TC-45; D20, D23).

hooks/pretool-overnight-hook-guard.py denies AskUserQuestion to every caller of
a /dev-overnight session, its main agent and its subagents, from the session's
human-typed /dev-overnight record to the next human-typed prompt in its main
transcript. A subagent is tied to its session by the transcript_path its
payload carries (the session's main transcript, or its own file under
<sid>/subagents/), so it is denied before any FIRST ACTION registration. No
state file decides: another session, even in the same repository and with a
live overnight state there, asks freely.

The hook runs as the CLI runs it: the payload as JSON on stdin. Transcripts use
CLI 2.1.303 record shapes (hooks/tests/test_command_span.py).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from tests.replay import hookrun  # noqa: E402

HOOK = REPO_ROOT / "hooks" / "pretool-overnight-hook-guard.py"
SID = "5f0c2d8e-1b7a-4c39-9e64-2a8d0b3f7c11"
OTHER_SID = "9a4e6b10-73c2-4d5f-8e1b-c06f2a9d3e48"
AGENT_ID = "a1b2c3d4e5f60718"

MAIN_MESSAGE = (
    "Overnight is unattended; nobody answers. Decide (experiment, else the question's default), record the "
    "decision in the cycle log and in the summary's 'Decisions made without the owner', and continue."
)
SUBAGENT_MESSAGE = (
    "Nobody answers overnight. Decide by experiment if one can be run, else take the question's default; "
    "record the decision, its options, the evidence or experiment and the chosen option in your report, "
    "and write your report."
)
QUESTION = {"questions": [{"question": "Which layer?", "header": "Layer", "multiSelect": False,
                           "options": [{"label": "A", "description": "a"}, {"label": "B", "description": "b"}]}]}


def _command(name, args=""):
    return (f"<command-message>{name}</command-message>\n<command-name>/{name}</command-name>\n"
            f"<command-args>{args}</command-args>")


class _Transcript:
    """A main-session transcript under <root>/<sid>.jsonl, appended record by record."""

    def __init__(self, root: Path, sid: str = SID):
        self.sid, self.path = sid, root / f"{sid}.jsonl"
        self.records = [{"type": "queue-operation", "operation": "dequeue", "sessionId": sid}]

    def _add(self, **fields):
        record = {"parentUuid": None, "isSidechain": False, "type": "user", "userType": "external",
                  "uuid": f"uuid-{len(self.records):04d}", "sessionId": self.sid, "version": "2.1.303"}
        record.update(fields)
        self.records.append(record)
        self.path.write_text("".join(json.dumps(r) + "\n" for r in self.records), encoding="utf-8")
        return self

    def typed(self, content):
        return self._add(message={"role": "user", "content": content}, origin={"kind": "human"},
                         promptSource="sdk", turnOrigin="human")

    def command(self, name, args=""):
        self.typed(_command(name, args))
        return self._add(isMeta=True, message={"role": "user", "content": [{"type": "text", "text": f"# /{name}"}]})

    def skill(self, text):
        """A Skill tool's expansion record: isMeta, sourceToolUseID."""
        return self._add(isMeta=True, turnCompanion=True, sourceToolUseID="toolu_0009",
                         message={"role": "user", "content": [{"type": "text", "text": text}]})

    def scheduled(self, text):
        """A CronCreate firing: isMeta, turnOrigin scheduled, promptSource system, no origin."""
        return self._add(isMeta=True, promptSource="system", turnOrigin="scheduled",
                         message={"role": "user", "content": text})

    def meta(self, text):
        return self._add(isMeta=True, message={"role": "user", "content": [{"type": "text", "text": text}]})

    def assistant_tool_use(self, name="Bash"):
        self.records.append({"type": "assistant", "sessionId": self.sid, "message": {
            "role": "assistant", "content": [{"type": "tool_use", "id": "toolu_0001", "name": name, "input": {}}]}})
        return self._add(message={"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_0001", "content": "ok"}]}, toolUseResult={"stdout": "ok"})


@pytest.fixture()
def project(tmp_path):
    root = tmp_path / "proj"
    (root / ".claude").mkdir(parents=True)
    return root


@pytest.fixture()
def store(tmp_path):
    root = tmp_path / "projects" / "-proj"
    root.mkdir(parents=True)
    return root


def _overnight(store):
    tx = _Transcript(store)
    tx.command("dev-overnight", "--hours 8")
    return tx.assistant_tool_use()


def _ask(project, transcript_path, sid=SID, agent_id=""):
    payload = {"session_id": sid, "transcript_path": str(transcript_path), "cwd": str(project),
               "hook_event_name": "PreToolUse", "permission_mode": "default",
               "tool_name": "AskUserQuestion", "tool_input": QUESTION, "tool_use_id": "toolu_0002"}
    if agent_id:
        payload.update(agent_id=agent_id, agent_type="general-purpose")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), PWD=str(project))
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, cwd=str(project), timeout=60)


def _write_state(project, sid, end_time):
    (project / ".claude" / f"overnight-state-{sid}.json").write_text(json.dumps({
        "session_id": sid, "isolation_kind": "in_place", "main_root": str(project),
        "worktree_path": str(project), "end_time": end_time, "isolation_active_until": end_time}))


def test_main_agent_in_the_window_is_told_to_decide(project, store):
    run = _ask(project, _overnight(store).path)
    assert run.returncode == 2
    assert run.stderr.strip() == MAIN_MESSAGE


def test_subagent_is_denied_before_any_first_action_registration(project, store):
    """No dev-registry exists: the payload's transcript_path alone ties it to the session."""
    tx = _overnight(store)
    assert not (project / ".claude" / "dev-registry").exists()
    run = _ask(project, tx.path, agent_id=AGENT_ID)
    assert run.returncode == 2
    assert run.stderr.strip() == SUBAGENT_MESSAGE


def test_subagent_naming_its_own_transcript_reads_the_main_one(project, store):
    tx = _overnight(store)
    own = store / SID / "subagents" / f"agent-{AGENT_ID}.jsonl"
    own.parent.mkdir(parents=True)
    own.write_text(json.dumps({"type": "user", "isSidechain": True, "agentId": AGENT_ID, "sessionId": SID,
                               "message": {"role": "user", "content": "dispatch prompt"}}) + "\n")
    run = _ask(project, own, agent_id=AGENT_ID)
    assert (run.returncode, run.stderr.strip()) == (2, SUBAGENT_MESSAGE)


@pytest.mark.parametrize("state", ["none", "past_end_time", "live"])
def test_no_state_file_decides_the_deny(project, store, state):
    """After end_time with no human-typed prompt the deny holds; is_overnight_active never decides."""
    if state != "none":
        _write_state(project, SID, "2000-01-01T00:00:00Z" if state == "past_end_time" else "2099-01-01T00:00:00Z")
    tx = _overnight(store)
    assert _ask(project, tx.path).returncode == 2
    assert _ask(project, tx.path, agent_id=AGENT_ID).returncode == 2


@pytest.mark.parametrize("prompt", ["stop", "spec", "plain"])
def test_the_next_human_typed_prompt_lifts_the_deny(project, store, prompt):
    tx = _overnight(store)
    _write_state(project, SID, "2099-01-01T00:00:00Z")
    if prompt == "plain":
        tx.typed("good morning, what happened overnight?")
    else:
        tx.command(prompt)
    tx.assistant_tool_use()
    for agent_id in ("", AGENT_ID):
        run = _ask(project, tx.path, agent_id=agent_id)
        assert (run.returncode, run.stderr) == (0, ""), agent_id


@pytest.mark.parametrize("record", ["skill", "scheduled", "isMeta"])
def test_stop_text_not_typed_by_the_human_lifts_nothing(project, store, record):
    tx = _overnight(store)
    getattr(tx, {"isMeta": "meta"}.get(record, record))(_command("stop"))
    getattr(tx, {"isMeta": "meta"}.get(record, record))("/stop")
    for agent_id in ("", AGENT_ID):
        assert _ask(project, tx.path, agent_id=agent_id).returncode == 2, agent_id


def test_a_retyped_dev_overnight_opens_the_window_again(project, store):
    tx = _overnight(store)
    tx.command("stop")
    assert _ask(project, tx.path).returncode == 0
    tx.command("dev-overnight", "--hours 2")
    assert (_ask(project, tx.path).returncode, _ask(project, tx.path).stderr.strip()) == (2, MAIN_MESSAGE)


def test_another_session_in_the_same_repository_asks_freely(project, store):
    tx = _overnight(store)
    _write_state(project, SID, "2099-01-01T00:00:00Z")
    other = _Transcript(store, OTHER_SID).command("spec", "a feature")
    for agent_id in ("", AGENT_ID):
        run = _ask(project, other.path, sid=OTHER_SID, agent_id=agent_id)
        assert (run.returncode, run.stderr) == (0, ""), agent_id
    assert _ask(project, store / "missing.jsonl", sid=OTHER_SID).returncode == 0
    assert _ask(project, tx.path).returncode == 2  # meanwhile the overnight session stays denied


def test_shipped_settings_route_ask_user_question_to_the_guard():
    """The CLI's matcher rule (hookrun.select, as runhook.py) sends a PreToolUse
    AskUserQuestion payload to the guard."""
    settings = json.loads((REPO_ROOT / "settings.json").read_text(encoding="utf-8"))
    hooks = [h["hook"] for h in hookrun.select(settings, "PreToolUse", {"tool_name": "AskUserQuestion"})]
    assert "hooks/pretool-overnight-hook-guard.py" in hooks
