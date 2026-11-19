"""G1's order rule (R17, hooks/pretool-obligation-gate.py) reads every way a dispatched agent's end comes
back, not only its own Agent call's result.

The owner's /commit was refused at its changelog-analyst plan dry-run: "reason=producer_not_stopped
artifact=docs/dev/close-report-<task>.md: declared by dispatch <id> (qa), which has not returned a
result", while that close QA had come back with CLOSE: YES and written its report. R17 took a dispatch
as returned only when its own Agent call had an ok tool_result. The CLI (2.1.326, recorded by
scripts/cli-fixture-record.sh in tests/fixtures/cli) brings an agent's end back otherwise too:

  - a background launch's result comes back at once ("async_launched") while the agent runs; its end
    is the task-notification the CLI delivers later (a turn of its own, or an attachment of type
    queued_command inside a running turn);
  - an agent cut off (an interrupt: an is_error result; the session's end: the CLI's is_error result
    for the call, written when the session resumes) and resumed with SendMessage (Lesson 16) runs
    again from that SendMessage's result; its end is the task-notification naming the agent, whose
    tool-use-id is the SendMessage's;
  - an agent cut off after it stopped by itself: its own transcript records that stop (an end_turn
    reply, then its SubagentStop hooks' record), the main session's result for the call does not;
  - a session continued in another file keeps its agents' files under the first file's directory;
  - a compaction leaves every record before its boundary in the file.

Every record below is a recorded CLI record (tests/cli_shapes.py synthesize, recording), values filled.
The landing cases at the end run the gate of each harness tree on the same transcripts: the owner-era
base tree (no R17), master before this fix, and this tree.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from tests import cli_shapes  # noqa: E402  (every record below is a recorded CLI record, values filled)
from tests.cli_shapes import synthesize  # noqa: E402
from tests.replay import landing  # noqa: E402  (a harness tree from git history, as the live-landing replays)

HOOK = Path("hooks") / "pretool-obligation-gate.py"
TASK = "20261019-103000"
CLOSE_REPORT = f"docs/dev/close-report-{TASK}.md"
QA_AGENT = "a0c105e0a0c105e0a"
SID = "11111111-2222-3333-4444-555555555555"
DISPATCH = "toolu_g1_changelog_analyst"
ORDER = "OBLIGATION GATE ORDER"
REFUSAL = (f"reason=producer_not_stopped artifact={CLOSE_REPORT}: declared by dispatch {{qa}} (qa), "
           "which has not returned a result")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _block(doc: dict) -> str:
    return '<obligation v="1">' + json.dumps(doc) + "</obligation>"


def _qa_prompt(close_md: str | None = None) -> str:
    """The close QA dispatch prompt from commands/close.md's obligation template (``close_md``: another
    tree's text of it), its placeholders filled."""
    text = close_md if close_md is not None else (REPO / "commands" / "close.md").read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if l.startswith('{"task_id":"<TASK_ID>","role":"qa","pipeline":"close"'))
    doc = json.loads(line.replace("<TASK_ID>", TASK))
    doc["dispatched_at"] = _now()
    return f"You are the close QA.\n{_block(doc)}\nWrite the judgment to {CLOSE_REPORT}."


def _analyst_prompt(commit_md: str | None = None) -> str:
    """commands/commit.md Step 6's planning dispatch (``commit_md``: another tree's text of it): Step 7's
    prompt with DRYRUN=true and the template's obligation, its placeholders filled, naming the
    close-report among the chain's artifacts."""
    text = commit_md if commit_md is not None else (REPO / "commands" / "commit.md").read_text(encoding="utf-8")
    template = next(part.split("</obligation>")[0] for part in text.split('<obligation v="1">')[1:]
                    if '"role": "changelog-analyst"' in part.split("</obligation>")[0])
    for pattern, value in ((r'<"\$TASK_ID"[^>]*>', json.dumps(TASK)), (r'<"commit-landing"[^>]*>', '"commit-landing"'),
                           (r'"<ISO-8601[^"]*>"', json.dumps(_now())), (r"<the JSON array[^>]*>", '["/work/toy"]')):
        template = re.sub(pattern, lambda _m, v=value: v, template)
    doc = json.loads(template)
    chain = {"commit_whitelist_artifacts": [CLOSE_REPORT]}
    return f"ARTIFACT_CHAIN={json.dumps(chain)}\nTASK_ID={TASK}\nBULK=false\nDRYRUN=true\n{_block(doc)}"


def _block_of(rec: dict, kind: str) -> dict:
    return next(b for b in rec["message"]["content"] if b.get("type") == kind)


class Session:
    """A main-session transcript in a project directory, and its agents' files beside it."""

    def __init__(self, project: Path, sid: str = SID):
        self.project, self.sid, self.n = project, sid, 0
        self.path = project / f"{sid}.jsonl"
        self.path.write_text("", encoding="utf-8")

    def add(self, record: dict) -> dict:
        if "sessionId" in record:
            record["sessionId"] = self.sid
        if "cwd" in record:
            record["cwd"] = str(self.project)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        return record

    def command(self, name: str = "commit") -> None:
        self.add(synthesize("queue-operation", "enqueue", content=f"/{name} {TASK}"))
        self.add(synthesize("user", "command", turnOrigin="human", message__content=(
            f"<command-message>{name} is running…</command-message>\n<command-name>/{name}</command-name>\n"
            f"<command-args>{TASK}</command-args>")))
        self.add(synthesize("user", "meta", message__content=[{"type": "text", "text": f"body of {name}"}]))

    def use(self, name: str, tool_input: dict, ident: str | None = None) -> str:
        self.n += 1
        ident = ident or f"toolu_{self.n:04d}"
        rec = synthesize("assistant", "tool_use")
        _block_of(rec, "tool_use").update(id=ident, name=name, input=tool_input)
        self.add(rec)
        return ident

    def result(self, ident: str, variant: str, **values) -> None:
        rec = synthesize("user", variant, **values)
        _block_of(rec, "tool_result")["tool_use_id"] = ident
        self.add(rec)

    def qa(self, background: bool = False, close_md: str | None = None) -> str:
        return self.use("Agent", {"description": "close QA", "subagent_type": "qa", "prompt": _qa_prompt(close_md),
                                  "run_in_background": background})

    def returned(self, ident: str) -> None:
        self.result(ident, "agent_result", toolUseResult__agentId=QA_AGENT)

    def launched(self, ident: str) -> None:
        self.result(ident, "agent_launched", toolUseResult__agentId=QA_AGENT)

    def cut(self, ident: str) -> None:
        self.result(ident, "cut")

    def resume(self) -> str:
        ident = self.use("SendMessage", {"to": QA_AGENT, "message": "Continue the close judgment."})
        self.result(ident, "resumed", toolUseResult__resumedAgentId=QA_AGENT, toolUseResult__revivedAgentId=QA_AGENT)
        return ident

    def notified(self, tool_use_id: str, status: str = "completed", mid_turn: bool = False) -> None:
        text = cli_shapes.notification(QA_AGENT, tool_use_id, status)
        self.add(synthesize("attachment/queued_command", attachment__prompt=text) if mid_turn
                 else synthesize("user", "task_notification", message__content=text))

    def compact(self) -> None:
        self.add(synthesize("system/compact_boundary"))
        self.add(synthesize("user", "compact_summary"))

    def say(self) -> None:
        self.add(synthesize("assistant", "text"))

    def agent_files(self, tool_use_id: str, records: list, under: str | None = None) -> None:
        """The QA agent's own transcript and meta file, under session ``under``'s directory (default this one's)."""
        folder = self.project / (under or self.sid) / "subagents"
        folder.mkdir(parents=True, exist_ok=True)
        for rec in records:
            rec["agentId"] = QA_AGENT
        (folder / f"agent-{QA_AGENT}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
        meta = cli_shapes.load_records("meta:subagent")
        meta.update(toolUseId=tool_use_id, agentType="qa")
        (folder / f"agent-{QA_AGENT}.meta.json").write_text(json.dumps(meta))

    def payload(self, commit_md: str | None = None) -> dict:
        prompt = _analyst_prompt(commit_md)
        tool_input = {"subagent_type": "changelog-analyst", "description": "plan dry-run", "prompt": prompt,
                      "run_in_background": False}
        self.use("Agent", tool_input, ident=DISPATCH)
        return {"session_id": self.sid, "transcript_path": str(self.path), "cwd": str(self.project),
                "hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_input": tool_input,
                "tool_use_id": DISPATCH}


def _stopped_tail() -> list:
    """The recorded subagent transcript, whole: its first stop blocked once by a SubagentStop hook (the
    CLI's feedback record), it goes on and stops again, the hooks letting that stop stand."""
    return cli_shapes.recording("subagent")


def _cut_prefix(at: str) -> list:
    """The recorded subagent transcript up to (and with) its first record of form ``at``: a real
    agent's records as they stood when its session ended there."""
    records, out = cli_shapes.recording("subagent"), []
    for rec in records:
        out.append(rec)
        content = (rec.get("message") or {}).get("content")
        if at == "tool_use" and rec["type"] == "assistant" and any(
                isinstance(b, dict) and b.get("type") == "tool_use" for b in content or ()):
            return out
        if at == "feedback" and rec["type"] == "user" and rec.get("isMeta"):
            return out
    raise AssertionError(f"the recording has no {at}")


def run_gate(tree: Path, home: Path, payload: dict) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "CODEX_", "OPENAI_AGENT"))}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_PROJECT_DIR=payload["cwd"],
               CLAUDE_OBLIGATION_GATE="block", CLAUDE_RESTART_STATE_DIR=str(home / "restart-state"),
               PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_GLOBAL="/dev/null")
    return subprocess.run([sys.executable, str(tree / HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=payload["cwd"], env=env, timeout=60)


# ------------------------------------------------------------------ each channel, one transcript each
# Each builds a /commit span through Step 3's close QA dispatch to Step 6's planning dispatch; it returns
# the session, the QA dispatch's id and whether the QA's agent has stopped.

def returned(s):
    qa = s.qa()
    s.returned(qa)
    return qa, True


def background_running(s):
    qa = s.qa(background=True)
    s.launched(qa)
    s.say()
    return qa, False


def background_notified(s):
    qa = s.qa(background=True)
    s.launched(qa)
    s.say()
    s.notified(qa)
    return qa, True


def background_notified_mid_turn(s):
    qa = s.qa(background=True)
    s.launched(qa)
    s.notified(qa, mid_turn=True)
    return qa, True


def background_failed(s):
    qa = s.qa(background=True)
    s.launched(qa)
    s.notified(qa, status="failed")
    return qa, False


def cut_resumed_notified(s):
    """Cut mid-turn, resumed: its end is the notification naming it, its tool-use-id the SendMessage's.
    The cut call's result names no agent; the meta file the CLI wrote when the agent started does."""
    qa = s.qa()
    s.cut(qa)
    s.notified(s.resume())
    s.agent_files(qa, _stopped_tail())
    return qa, True


def cut_resumed_running(s):
    qa = s.qa()
    s.cut(qa)
    s.resume()
    s.say()
    s.agent_files(qa, _cut_prefix("tool_use"))
    return qa, False


def returned_then_resumed_running(s):
    qa = s.qa()
    s.returned(qa)
    s.resume()
    return qa, False


def resumed_twice_one_notification(s):
    qa = s.qa()
    s.cut(qa)
    s.notified(s.resume())
    s.resume()
    s.agent_files(qa, _stopped_tail())
    return qa, False


def cut_after_its_stop(s):
    qa = s.qa()
    s.cut(qa)
    s.agent_files(qa, _stopped_tail())
    return qa, True


def cut_mid_turn(s):
    qa = s.qa()
    s.cut(qa)
    s.agent_files(qa, _cut_prefix("tool_use"))
    return qa, False


def cut_in_a_blocked_stop(s):
    qa = s.qa()
    s.cut(qa)
    s.agent_files(qa, _cut_prefix("feedback"))
    return qa, False


def cut_without_agent_files(s):
    qa = s.qa()
    s.cut(qa)
    return qa, False


def running(s):
    return s.qa(), False


def compacted_after_return(s):
    qa = s.qa()
    s.returned(qa)
    s.compact()
    return qa, True


def compacted_while_in_background(s):
    qa = s.qa(background=True)
    s.launched(qa)
    s.compact()
    s.notified(qa)
    return qa, True


def continued_in_another_file(s):
    """The session went on in a file of its own (a resumed, forked session): its records up to here are
    copied into it, its agents' files stay under the first file's directory."""
    qa = s.qa()
    s.cut(qa)
    s.agent_files(qa, _stopped_tail(), under="00000000-0000-0000-0000-00000000f1e5")
    return qa, True


CHANNELS = [returned, background_running, background_notified, background_notified_mid_turn, background_failed,
            cut_resumed_notified, cut_resumed_running, returned_then_resumed_running, resumed_twice_one_notification,
            cut_after_its_stop, cut_mid_turn, cut_in_a_blocked_stop, cut_without_agent_files, running,
            compacted_after_return, compacted_while_in_background, continued_in_another_file]


def _world(tmp_path: Path, channel, sid: str = SID, commit_md: str | None = None):
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir(parents=True, exist_ok=True)
    project.mkdir(parents=True, exist_ok=True)
    s = Session(project, sid)
    s.command("commit")
    s.say()
    qa, stopped = channel(s)
    return home, s.payload(commit_md), qa, stopped


@pytest.mark.parametrize("channel", CHANNELS, ids=lambda c: c.__name__)
def test_a_dispatch_counts_as_returned_exactly_when_its_agent_stopped(tmp_path, channel):
    home, payload, qa, stopped = _world(tmp_path, channel)
    result = run_gate(REPO, home, payload)
    if stopped:
        assert result.returncode == 0 and result.stderr == "", result.stderr
    else:
        assert result.returncode == 2 and ORDER in result.stderr, result.stderr
        assert REFUSAL.format(qa=qa) in result.stderr, result.stderr


@pytest.mark.parametrize("channel", CHANNELS, ids=lambda c: c.__name__)
def test_the_cli_s_request_copies_change_no_answer(tmp_path, channel):
    """CLI 2.1.322 repeats each message of its next model request in an api-request-blob record, a
    tool_use block (same id) among them, after the call's result (tests/fixtures/cli-request-copies). A
    dispatch counts as returned exactly as it does without them, and one still running is still refused."""
    home, payload, qa, stopped = _world(tmp_path, channel)
    for path in [Path(payload["transcript_path"]), *Path(payload["cwd"]).glob("*/subagents/*.jsonl")]:
        cli_shapes.add_request_copies(path)
    assert '"api-request-blob"' in Path(payload["transcript_path"]).read_text()
    result = run_gate(REPO, home, payload)
    if stopped:
        assert result.returncode == 0 and result.stderr == "", result.stderr
    else:
        assert result.returncode == 2 and REFUSAL.format(qa=qa) in result.stderr, result.stderr


def test_the_records_each_channel_writes_have_the_recorded_shapes(tmp_path):
    for channel in CHANNELS:
        home, payload, _qa, _stopped = _world(tmp_path / channel.__name__, channel)
        records = [json.loads(l) for l in Path(payload["transcript_path"]).read_text().splitlines()]
        records += [json.loads(l) for p in Path(payload["cwd"]).glob("*/subagents/*.jsonl")
                    for l in p.read_text().splitlines()]
        assert [p for rec in records for p in cli_shapes.check_record(rec)] == [], channel.__name__


def test_a_session_continued_after_a_compaction_has_no_span_to_hold(tmp_path):
    """A forked session copies only what follows the compaction's boundary (the recording's fork): the
    /commit opener is not in its file, so there is no span and nothing to order."""
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    project.mkdir()
    s = Session(project)
    s.compact()
    qa = s.qa()
    s.cut(qa)
    s.resume()
    assert run_gate(REPO, home, s.payload()).returncode == 0


# ------------------------------------------------------------------ the landing (old-harness in-flight state)
# The owner's home pulls or lands a newer harness while a session runs (tests/replay/landing.py). The
# close QA was dispatched from the base tree's commands/close.md; the gate that reads the span at the
# planning dispatch is the landed tree's. Each tree's gate runs on the same transcript.
BASE = "2acc29b0c8149c32d8e424e58c6af55d073eac20"  # the owner's home before train 1 (test_live_landing's "master")
MASTER = "83c3b352"  # master before this fix: R17 and the /restart journal, nothing else
TREES = {"base": BASE, "master": MASTER}
# (channel, base gate refuses, master gate refuses, this tree's gate refuses)
LANDING = [(returned, False, False, False), (cut_resumed_notified, False, True, False),
           (cut_after_its_stop, False, True, False), (background_running, False, False, True),
           (cut_resumed_running, False, True, True)]


@pytest.fixture(scope="module")
def trees(tmp_path_factory):
    root = tmp_path_factory.mktemp("trees")
    try:
        return {name: Path(landing.base_tree(str(REPO), rev, str(root / name))) for name, rev in TREES.items()}
    except (RuntimeError, subprocess.CalledProcessError) as exc:  # a shallow checkout lacks the history
        pytest.skip(f"git history of the landing trees is not in this checkout: {exc}")


@pytest.mark.parametrize("channel,base_refuses,master_refuses,refuses", LANDING,
                         ids=[c[0].__name__ for c in LANDING])
def test_the_landing_reads_an_old_harness_qa_dispatch_as_this_tree_does(tmp_path, trees, channel, base_refuses,
                                                                        master_refuses, refuses):
    """The session typed /commit on the base home and follows the text it loaded (D15): the close QA
    and the planning dispatch are written from the base's commands/close.md and commit.md, whose
    obligations declare and name the close-report as this tree's do. The landed gate reads that
    QA dispatch as it reads its own; what the landing changes is that R17 reads its end at all."""
    base_close = (trees["base"] / "commands" / "close.md").read_text(encoding="utf-8")
    base_commit = (trees["base"] / "commands" / "commit.md").read_text(encoding="utf-8")

    def old_qa(s, background=False, close_md=None):
        return Session.qa(s, background=background, close_md=base_close)

    home, payload, qa, _stopped = _world(tmp_path, lambda s: channel(_with(s, qa=old_qa)), commit_md=base_commit)
    for name, tree, refused in (("base", trees["base"], base_refuses), ("master", trees["master"], master_refuses),
                                ("this", REPO, refuses)):
        result = run_gate(tree, home, payload)
        assert (result.returncode == 2) == refused, (name, result.stderr)
        if refused:
            assert REFUSAL.format(qa=qa) in result.stderr, (name, result.stderr)
        else:
            assert result.stderr == "", (name, result.stderr)


def _with(s: Session, **methods) -> Session:
    for name, fn in methods.items():
        setattr(s, name, fn.__get__(s, Session))
    return s
