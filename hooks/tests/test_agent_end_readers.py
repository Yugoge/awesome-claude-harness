"""Every hook that asks whether a dispatched agent has returned (hooks/lib/agent_returns.py):
the /commit --bulk Stop, the close rating and ask-first read its end as G1 does.

G1's R17 took a dispatch as returned only when its own Agent call had an ok tool_result; it now reads
every way the CLI (2.1.326, tests/fixtures/cli) brings an agent's end back (test_obligation_gate_returns.py):
a background launch ends in its task-notification, a cut agent resumed with SendMessage in the
notification naming it (whose tool-use-id is the SendMessage's), a cut agent that had stopped by itself
in its own transcript's stop. Three more readers held the old assumption, each with its own failure:

  - the /commit --bulk Stop (hooks/stop-command-gate.py _bulk_block) read the status block of the
    span's last ok commit-bulk dispatch's own result: a landing analyst cut and resumed (/restart, the
    overnight wake) was not that dispatch, so the planning dry-run's "dryrun" block passed the Stop
    whatever the landing reported; a background landing's block was never read;
  - the close rating (hooks/lib/close_rating.py _landed) read the close QA's CLOSE: YES from its ok
    Agent result only: a QA that landed through any other channel required no rating, and /close
    ended without asking it;
  - ask-first (hooks/lib/requirement_round.py ask_first) held a dispatch for the owner's questions only
    when their producer's latest Agent call had come back ok: a BA cut and resumed writes its round, and
    the next dispatch went out without the owner being asked it.

Two readers are unaffected, and cases below show it: requirement_round.asked reads the main
agent's own AskUserQuestion calls (never a dispatched agent), after the line close_rating gives it; and
spec_path reads the main agent's own Write, Edit and Bash calls (the spec's writer runs as the main
agent's Bash, commands/spec.md Step 4). The replay's /restart (tests/replay/recovery.py) now writes the
resumed agent's end as the CLI does: its SendMessage's result names the agent, and its notification
answers the SendMessage and is delivered into the running turn.

Every record below is a recorded CLI record (tests/cli_shapes.py synthesize, recording, notification),
values filled; the stop gate's transcript writer and fixtures are test_stop_command_gate.py's, the
round files test_requirement_round.py's, the agents' recorded tails test_obligation_gate_returns.py's.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_obligation_gate_returns as g1  # noqa: E402  (hooks/tests on sys.path)
import test_requirement_round as rrt  # noqa: E402
import test_stop_command_gate as sg  # noqa: E402
from test_requirement_round import project  # noqa: E402,F401  (its fixture: a scratch project)
from test_stop_command_gate import env, real  # noqa: E402,F401  (its fixtures: a project, the gate's fakes)

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from tests import cli_shapes  # noqa: E402
from tests.cli_shapes import synthesize  # noqa: E402

FAMILY = sg.FAMILY
YES = "Round 1 judged: every criterion holds.\n\nCLOSE: YES"
BLOCK = ("--- CHANGELOG-ANALYST-STATUS-BEGIN ---", "--- CHANGELOG-ANALYST-STATUS-END ---")


class Main:
    """The main session's records on a transcript writer (test_stop_command_gate's TX: this session's
    id, cwd and clock), and its agents' own files beside the transcript."""

    def __init__(self, tx):
        self.tx, self.n = tx, 0

    def use(self, name: str, tool_input: dict) -> str:
        self.n += 1
        ident = f"toolu_end_{self.n:04d}"
        rec = synthesize("assistant", "tool_use")
        g1._block_of(rec, "tool_use").update(id=ident, name=name, input=tool_input)
        self.tx.add(rec)
        return ident

    def result(self, ident: str, variant: str, content=None, **values) -> None:
        rec = synthesize("user", variant, **values)
        block = g1._block_of(rec, "tool_result")
        block["tool_use_id"] = ident
        if content is not None:
            block["content"] = content
        self.tx.add(rec)

    def dispatch(self, role: str, doc: dict, background: bool = False) -> str:
        prompt = f"You are the {role}.\n" + '<obligation v="1">' + json.dumps(doc) + "</obligation>"
        return self.use("Agent", {"subagent_type": role, "description": role, "prompt": prompt,
                                  "run_in_background": background})

    def returned(self, ident: str, agent: str, reply: str) -> None:
        text = [{"type": "text", "text": reply}]
        self.result(ident, "agent_result", content=text, toolUseResult__agentId=agent, toolUseResult__content=text)

    def launched(self, ident: str, agent: str) -> None:
        self.result(ident, "agent_launched", toolUseResult__agentId=agent)

    def cut(self, ident: str) -> None:
        self.result(ident, "cut")

    def refused(self, ident: str) -> None:
        """The CLI's error result for a call a PreToolUse hook refused (CLI 2.1.322: permissionDecision reject by a
        hook): the call never ran."""
        self.cut(ident)
        records = [json.loads(line) for line in self.tx.path.read_text().splitlines()]
        records[-1]["permissionDecision"] = {"decision": "reject", "source": "hook", "reasonType": "hook"}
        self.tx.path.write_text("".join(json.dumps(r) + "\n" for r in records))

    def resume(self, agent: str) -> str:
        ident = self.use("SendMessage", {"to": agent, "message": "Continue from where you were cut."})
        self.result(ident, "resumed", toolUseResult__resumedAgentId=agent, toolUseResult__revivedAgentId=agent)
        return ident

    def notified(self, agent: str, tool_use_id: str, reply: str, status: str = "completed",
                 mid_turn: bool = False) -> None:
        text = cli_shapes.notification(agent, tool_use_id, status, result=reply)
        self.tx.add(synthesize("attachment/queued_command", attachment__prompt=text) if mid_turn
                    else synthesize("user", "task_notification", message__content=text))

    def say(self) -> None:
        self.tx.add(synthesize("assistant", "text"))

    def agent_files(self, agent: str, tool_use_id: str, role: str, records: list) -> None:
        folder = self.tx.path.with_suffix("") / "subagents"
        folder.mkdir(parents=True, exist_ok=True)
        for rec in records:
            rec["agentId"] = agent
        (folder / f"agent-{agent}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
        meta = cli_shapes.load_records("meta:subagent")
        meta.update(toolUseId=tool_use_id, agentType=role)
        (folder / f"agent-{agent}.meta.json").write_text(json.dumps(meta))


def _stopped(reply: str) -> list:
    """The recorded subagent transcript, whole (a stop blocked once, then a stop its hooks let stand),
    its last reply's text ``reply``."""
    records = g1._stopped_tail()
    last = next(r for r in reversed(records) if r["type"] == "assistant")
    g1._block_of(last, "text")["text"] = reply
    return records


# ------------------------------------------------------------------ how the agent's end comes back
# Each dispatches ``doc``'s role, brings its agent's end back one way (or not) with ``reply`` as its last
# text, and returns the dispatch's id and whether the agent has stopped.

def returned(m, role, doc, agent, reply):
    call = m.dispatch(role, doc)
    m.returned(call, agent, reply)
    return call, True


def background_running(m, role, doc, agent, reply):
    call = m.dispatch(role, doc, background=True)
    m.launched(call, agent)
    m.say()
    return call, False


def background_notified(m, role, doc, agent, reply):
    call = m.dispatch(role, doc, background=True)
    m.launched(call, agent)
    m.say()
    m.notified(agent, call, reply)
    return call, True


def background_notified_mid_turn(m, role, doc, agent, reply):
    call = m.dispatch(role, doc, background=True)
    m.launched(call, agent)
    m.notified(agent, call, reply, mid_turn=True)
    return call, True


def background_failed(m, role, doc, agent, reply):
    call = m.dispatch(role, doc, background=True)
    m.launched(call, agent)
    m.notified(agent, call, reply, status="failed")
    return call, False


def cut_resumed_notified(m, role, doc, agent, reply):
    call = m.dispatch(role, doc)
    m.cut(call)
    m.notified(agent, m.resume(agent), reply)
    m.agent_files(agent, call, role, _stopped(reply))
    return call, True


def cut_resumed_running(m, role, doc, agent, reply):
    call = m.dispatch(role, doc)
    m.cut(call)
    m.resume(agent)
    m.say()
    m.agent_files(agent, call, role, g1._cut_prefix("tool_use"))
    return call, False


def cut_after_its_stop(m, role, doc, agent, reply):
    call = m.dispatch(role, doc)
    m.cut(call)
    m.agent_files(agent, call, role, _stopped(reply))
    return call, True


def cut_mid_turn(m, role, doc, agent, reply):
    call = m.dispatch(role, doc)
    m.cut(call)
    m.agent_files(agent, call, role, g1._cut_prefix("tool_use"))
    return call, False


CHANNELS = [returned, background_running, background_notified, background_notified_mid_turn, background_failed,
            cut_resumed_notified, cut_resumed_running, cut_after_its_stop, cut_mid_turn]


def ids(channel) -> str:
    return channel.__name__


def test_the_records_each_channel_writes_have_the_recorded_shapes(tmp_path):
    for channel in CHANNELS:
        (tmp_path / channel.__name__).mkdir()
        tx = sg.TX(tmp_path / channel.__name__ / f"{sg.SID}.jsonl")
        tx.command("close", FAMILY)
        channel(Main(tx), "qa", _close_qa(), "a0c105e0a0c105e0a", YES)
        records = [json.loads(line) for path in [tx.path, *tx.path.parent.glob("*/subagents/*.jsonl")]
                   for line in path.read_text().splitlines()]
        assert [p for rec in records for p in cli_shapes.check_record(rec)] == [], channel.__name__


# ------------------------------------------------------------------ /commit --bulk: the landing's own report
def _analyst() -> dict:
    return {"task_id": None, "role": "changelog-analyst", "pipeline": "commit", "profile": "commit-bulk",
            "dispatched_at": "2026-11-01T09:00:00Z",
            "artifacts": [{"kind": "response_block", "begin": BLOCK[0], "end": BLOCK[1], "format": "json",
                           "schema": "changelog-status.v1", "repo_roots": None}]}


def _status(**fields) -> str:
    return f"Landed.\n{BLOCK[0]}\n{json.dumps(fields)}\n{BLOCK[1]}"


def _bulk(env, channel, landing: str, planned: bool = True):
    """A /commit --bulk span: Step 6's planning dispatch (DRYRUN=true) came back with its "dryrun" block;
    Step 7's landing dispatch's analyst reports ``landing`` and its end comes back by ``channel``."""
    m = Main(env.tx)
    env.tx.command("commit", "--bulk")
    if planned:
        m.returned(m.dispatch("changelog-analyst", _analyst()), "a0dry0000000000001", _status(commit_status="dryrun"))
    return channel(m, "changelog-analyst", _analyst(), "a0land00000000001", landing)[1]


@pytest.mark.parametrize("channel", CHANNELS, ids=ids)
def test_commit_bulk_holds_its_stop_to_the_report_its_landing_analyst_stopped_with(env, channel):
    """The landing reports a failed commit: its Stop names that report once the analyst stopped, by any
    channel; while it runs (or ran nothing it reported) there is no block to read. On the base tree the
    cut-and-resumed or cut-after-stop landing was no ok dispatch, so the dry-run's "dryrun" block passed
    the Stop (exit 0, no text); a background landing's notification was never read."""
    stopped = _bulk(env, channel, _status(commit_status="failed", failure_code="grant_missing",
                                          failure_reason="no bulk sentinel"))
    code, text = sg.run(env)
    assert code == 2, text
    if stopped:
        assert "commit --bulk: changelog-analyst reports 'failed': grant_missing no bulk sentinel" in text, text
    else:
        assert "commit --bulk: no changelog-analyst status block in this /commit" in text, text


@pytest.mark.parametrize("channel", CHANNELS, ids=ids)
def test_commit_bulk_ends_once_its_landing_analyst_stopped_with_a_landing(env, channel):
    """Without a planning block before it: the landing analyst's committed report ends the /commit
    whichever way it came back. On the base tree the background or cut landing's report was not read:
    "commit --bulk: no changelog-analyst status block in this /commit" held the Stop."""
    stopped = _bulk(env, channel, _status(commit_status="committed"), planned=False)
    code, text = sg.run(env)
    assert (code, text) == (0, "") if stopped else (
        code == 2 and "commit --bulk: no changelog-analyst status block in this /commit" in text), text


def test_commit_bulk_a_landing_refused_before_it_ran_leaves_the_last_analyst_that_ran(env):
    """A dispatch refused before its agent ran (an is_error result, no agent behind it) is no landing:
    the last analyst that ran decides, as before."""
    m = Main(env.tx)
    env.tx.command("commit", "--bulk")
    m.returned(m.dispatch("changelog-analyst", _analyst()), "a0land00000000001", _status(commit_status="committed"))
    m.cut(m.dispatch("changelog-analyst", _analyst()))  # no meta file, no notification: refused, never ran
    assert sg.run(env) == (0, "")


# ------------------------------------------------------------------ /close: the rating follows a landed close QA
def _close_qa(task: str = FAMILY) -> dict:
    return {"task_id": task, "role": "qa", "pipeline": "close", "profile": "final_verification",
            "dispatched_at": "2026-11-01T09:00:00Z",
            "artifacts": [{"kind": "markdown", "path": f"docs/dev/close-report-{task}.md", "identity_anchor": task,
                           "terminal_line_regex": "^CLOSE: YES.*$"}],
            "consistency": "verdict_class"}


def _rate(m, task: str = FAMILY) -> None:
    ident = m.use("AskUserQuestion", {"questions": [{"question": "How well?", "header": "Rating", "multiSelect": False,
                                                     "options": [{"label": "5 - Fully met", "description": "d"}]}],
                                      "metadata": {"source": f"close-rating:{task}"}})
    m.result(ident, "tool_result", content="The user did not answer the questions.")


@pytest.mark.parametrize("channel", CHANNELS, ids=ids)
def test_close_rating_is_required_once_the_close_qa_landed_by_any_channel(env, channel):
    close_rating = importlib.import_module("lib.close_rating")
    m = Main(env.tx)
    env.tx.command("close", FAMILY)
    _call, stopped = channel(m, "qa", _close_qa(), "a0c105e0a0c105e0a", YES)
    span = lambda: sg.command_span.active_span(env.tx.path)  # noqa: E731
    assert close_rating.rating_required(span(), FAMILY) is stopped
    assert not close_rating.rating_asked(env.tx.path, FAMILY)
    _rate(m)
    assert close_rating.rating_asked(env.tx.path, FAMILY) is stopped


def test_close_rating_asked_before_the_qa_s_end_came_back_is_not_asked(env):
    """requirement_round.asked reads the main agent's own AskUserQuestion calls after the line
    close_rating gives it, which is now the line the QA's end came back at: a rating asked while the
    resumed QA still ran is not the rating of its landing."""
    close_rating = importlib.import_module("lib.close_rating")
    m = Main(env.tx)
    env.tx.command("close", FAMILY)
    call = m.dispatch("qa", _close_qa())
    m.cut(call)
    resume = m.resume("a0c105e0a0c105e0a")
    _rate(m)
    m.notified("a0c105e0a0c105e0a", resume, YES)
    m.agent_files("a0c105e0a0c105e0a", call, "qa", _stopped(YES))
    assert close_rating.rating_required(sg.command_span.active_span(env.tx.path), FAMILY)
    assert not close_rating.rating_asked(env.tx.path, FAMILY)
    _rate(m)
    assert close_rating.rating_asked(env.tx.path, FAMILY)


@pytest.mark.parametrize("channel", [cut_resumed_notified, cut_after_its_stop, background_notified], ids=ids)
def test_close_stop_holds_for_the_rating_of_a_qa_that_landed_by_another_channel(real, channel):
    """The Stop of a /close whose checklist is done and whose chain passes (P3's real --stage close), its
    close QA landed CLOSE: YES through a resume, a cut after its stop or a background notification:
    the rating question is owed. On the base tree the Stop passed (exit 0) without it."""
    sg.chain_on_disk(real.project, close="CLOSE: YES")
    m = Main(real.tx)
    real.tx.command("close", FAMILY)
    real.tx.todos(sg.canonical("close", FAMILY), len(sg.canonical("close", FAMILY)))
    channel(m, "qa", _close_qa(), "a0c105e0a0c105e0a", YES)
    code, text = sg.run(real)
    assert code == 2 and f"close {FAMILY}: the close-rating question (AskUserQuestion) was not asked" in text, text
    _rate(m)
    assert sg.run(real) == (0, "")


# ------------------------------------------------------------------ ask-first: the owner's questions before the next dispatch
def _dev(tmp_path) -> Main:
    tx = sg.TX(tmp_path / f"{sg.SID}.jsonl")
    tx.command("dev", "a request", context=f"DEV_SESSION_ID pre-initialized by hook: dev-{rrt.TASK}\n",
               body="body of dev: its requirement-round is asked first")
    return Main(tx)


def _ask(m, doc: dict) -> None:
    from hooks.lib import requirement_round as rr
    ident = m.use("AskUserQuestion", {"questions": rr.ask_view(doc),
                                      "metadata": {"source": f"requirement-round:{rrt.TASK}:r{doc['round']}"}})
    m.result(ident, "tool_result", content="The user did not answer the questions.")


@pytest.mark.parametrize("channel", CHANNELS, ids=ids)
def test_ask_first_holds_the_next_dispatch_for_round_1_once_its_ba_stopped(project, tmp_path, channel):
    """BA wrote round 1 and stopped: the next dispatch asks it first, by its file. While BA runs the
    round is not yet its to ask. On the base tree a BA whose end came back by another channel left the
    refusal to name no round at all ("dispatch BA intake for ...": a replacement of the resumed BA)."""
    from hooks.lib import requirement_round as rr
    m = _dev(tmp_path)
    _call, stopped = channel(m, "ba", rrt.obligation_doc("ba", [rrt.ROUND1]), "a0ba00000000000001", "Round 1 written.")
    rrt.put(project, rrt.ROUND1, rrt.round_doc())
    refusal = rr.ask_first(sg.command_span.active_span(m.tx.path), project, rrt.obligation_doc("ba", [rrt.CONTEXT]))
    if stopped:
        assert refusal == (f'ASK_FIRST: ask {rrt.ROUND1} with one AskUserQuestion, metadata.source '
                           f'"requirement-round:{rrt.TASK}:r1", questions exactly as written; then dispatch.')
    else:
        assert refusal.startswith(f"ASK_FIRST: no requirement round r1 of task {rrt.TASK} has been asked")


@pytest.mark.parametrize("channel", CHANNELS, ids=ids)
def test_ask_first_holds_the_next_dispatch_for_round_2_once_its_ba_stopped(project, tmp_path, channel):
    """Round 1 asked; BA wrote round 2 and stopped: the next dispatch asks round 2 first. On the base tree
    a round-2 BA cut and resumed (or cut after its stop, or in the background) let the next dispatch
    through (None) without the owner being asked round 2."""
    from hooks.lib import requirement_round as rr
    m = _dev(tmp_path)
    first = rrt.round_doc()
    rrt.put(project, rrt.ROUND1, first)
    m.returned(m.dispatch("ba", rrt.obligation_doc("ba", [rrt.ROUND1])), "a0ba00000000000001", "Round 1 written.")
    _ask(m, first)
    _call, stopped = channel(m, "ba", rrt.obligation_doc("ba", [rrt.ROUND2]), "a0ba00000000000002", "Round 2 written.")
    rrt.put(project, rrt.ROUND2, rrt.round_doc(2, [rrt.q(1, "scope", "Which of the two screens comes first?")]))
    refusal = rr.ask_first(sg.command_span.active_span(m.tx.path), project, rrt.obligation_doc("ba", [rrt.CONTEXT]))
    assert refusal == ((f'ASK_FIRST: ask {rrt.ROUND2} with one AskUserQuestion, metadata.source '
                        f'"requirement-round:{rrt.TASK}:r2", questions exactly as written; then dispatch.')
                       if stopped else None)


# ------------------------------------------------------------------ unaffected: spec_path
def test_spec_path_reads_the_main_agents_own_writes_whatever_its_agents_do(project, tmp_path):
    """spec_path.last_spec_write reads the main session's own Write/Edit/MultiEdit and Bash calls: the
    spec's one writer is spec-write.py, run as the main agent's Bash (commands/spec.md Step 4), and no
    dispatch writes a spec (commands/dev-overnight.md "One writer per spec"). A dispatched agent's end,
    by any channel, is no spec write, nor is an agent's reply that prints the writer's line; the spec
    the main agent wrote stays the last one."""
    from hooks.lib import spec_path
    spec = str(project / "docs" / "dev" / "specs" / "spec-20261109-120000.md")
    m = Main(sg.TX(tmp_path / f"{sg.SID}.jsonl"))
    m.tx.command("spec", "a request")
    ident = m.use("Bash", {"command": f"python3 scripts/spec-write.py create --spec {spec}"})
    m.result(ident, "tool_result", content=f"spec-write: create {spec}")
    echo = f"spec-write: create {project}/docs/dev/specs/spec-other.md"
    for channel in CHANNELS:
        channel(m, "Explore", {"task_id": None, "role": "Explore"}, f"a0{channel.__name__[:14]:0<15}", echo)
    assert spec_path.last_spec_write(str(m.tx.path), str(project)) == spec


# ------------------------------------------------------------------ the replay's /restart writes what the CLI records
def test_the_replays_resumed_agent_ends_as_the_cli_records_it(tmp_path, monkeypatch):
    """tests/replay/recovery.py's /restart: the SendMessage's result names the resumed agent, and the
    agent's end is the notification that answers that SendMessage, delivered into the running turn as
    the recording's busy-turn delivery (enqueue, queued_command attachment, remove). It wrote a lone
    queue-operation answering the cut Agent call, which no reader of the session takes for a turn's
    record: G1 then read the resumed agent as stopped only through the /restart journal."""
    from tests.replay import recovery, replay
    aid, project = "a0d5e7000000000001", tmp_path / "project"
    session = object.__new__(replay.Session)
    session.rp = SimpleNamespace(layout=SimpleNamespace(project=str(project)), ids=SimpleNamespace(add=lambda *a: None))
    session.sid, session.tdir, session.parent, session._agent_parent = sg.SID, str(tmp_path), None, {}
    session.tpath = str(tmp_path / f"{sg.SID}.jsonl")
    tx = sg.TX(Path(session.tpath))
    tx.command("dev", "a request")
    m = Main(tx)
    call = m.dispatch("dev", {"task_id": rrt.TASK, "role": "dev"})
    m.cut(call)
    send = m.use("SendMessage", {"to": aid, "message": "resume"})
    m.result(send, "tool_result", toolUseResult=recovery.resumed(aid))
    m.agent_files(aid, call, "dev", _stopped("DONE"))
    stand_in = SimpleNamespace(sub=SimpleNamespace(aid=aid, s=session, role="agent:dev", last_final="DONE"),
                               cut_step={"input": {}}, d=SimpleNamespace(final_line=""), resume=lambda: None)
    cuts = object.__new__(recovery.Cuts)
    cuts.rp = SimpleNamespace(fault_records=[{"agent": aid}], layout=SimpleNamespace(project=str(project)))
    cuts.parked = [stand_in]
    monkeypatch.setattr(recovery, "_record", lambda rp, rec=None: None)  # faults.json is a replay run's
    session.parent = json.loads(Path(session.tpath).read_text().splitlines()[-1])["uuid"]  # Session.append's chain
    cuts.resume(aid, "resume", send)
    records = [json.loads(line) for line in Path(session.tpath).read_text().splitlines()]
    tail = [cli_shapes.record_kind(r) + ("/" + r["operation"] if r["type"] == "queue-operation" else "")
            for r in records[-3:]]
    assert tail == ["queue-operation/enqueue", "attachment/queued_command", "queue-operation/remove"]
    assert [p for r in records for p in cli_shapes.check_record(r)] == []
    span = sg.command_span.active_span(session.tpath)
    [end] = span.agent_ends()
    assert (end.agent, end.tool_use_id, end.status, end.result) == (aid, send, "completed", "DONE")
    returns = importlib.import_module("lib.agent_returns").Returns(span, session_id="no-restart-journal")
    dispatch = next(c for c in span.calls("Agent") if c.id == call)
    assert returns.line(dispatch) == end.line and returns.reply(dispatch) == "DONE"


# ------------------------------------------------------------------ a dispatch a hook refused never ran
# command_span.refused_calls: a call a PreToolUse hook refused declares nothing, is no producer's latest dispatch,
# no verdict and no landing. Every reader of dispatches takes Span.dispatch_calls / dispatches, which leave it out.

def test_ask_first_round_1_a_ba_dispatch_a_hook_refused_after_the_round_is_not_its_latest(project, tmp_path):
    """BA wrote round 1 and returned; a second BA dispatch was refused by a hook. The round is due: ask it. On
    a5aff80e4 the refused call was BA's latest dispatch, never returned, so the round was not yet due and the
    refusal sent the agent to dispatch BA intake again."""
    from hooks.lib import requirement_round as rr
    m = _dev(tmp_path)
    m.returned(m.dispatch("ba", rrt.obligation_doc("ba", [rrt.ROUND1])), "a0ba00000000000001", "Round 1 written.")
    m.refused(m.dispatch("ba", rrt.obligation_doc("ba", [rrt.ROUND1])))
    rrt.put(project, rrt.ROUND1, rrt.round_doc())
    refusal = rr.ask_first(sg.command_span.active_span(m.tx.path), project, rrt.obligation_doc("ba", [rrt.CONTEXT]))
    assert refusal == (f'ASK_FIRST: ask {rrt.ROUND1} with one AskUserQuestion, metadata.source '
                       f'"requirement-round:{rrt.TASK}:r1", questions exactly as written; then dispatch.')


def test_ask_first_round_2_a_ba_dispatch_a_hook_refused_after_the_round_is_not_its_latest(project, tmp_path):
    """Round 1 asked; BA wrote round 2 and returned; a later BA dispatch was refused by a hook. Round 2 is still
    owed. On a5aff80e4 the next dispatch went through (None) without the owner being asked round 2."""
    from hooks.lib import requirement_round as rr
    m = _dev(tmp_path)
    first = rrt.round_doc()
    rrt.put(project, rrt.ROUND1, first)
    m.returned(m.dispatch("ba", rrt.obligation_doc("ba", [rrt.ROUND1])), "a0ba00000000000001", "Round 1 written.")
    _ask(m, first)
    m.returned(m.dispatch("ba", rrt.obligation_doc("ba", [rrt.ROUND2])), "a0ba00000000000002", "Round 2 written.")
    m.refused(m.dispatch("ba", rrt.obligation_doc("ba", [rrt.ROUND2])))
    rrt.put(project, rrt.ROUND2, rrt.round_doc(2, [rrt.q(1, "scope", "Which of the two screens comes first?")]))
    refusal = rr.ask_first(sg.command_span.active_span(m.tx.path), project, rrt.obligation_doc("ba", [rrt.CONTEXT]))
    assert refusal == (f'ASK_FIRST: ask {rrt.ROUND2} with one AskUserQuestion, metadata.source '
                       f'"requirement-round:{rrt.TASK}:r2", questions exactly as written; then dispatch.')


def test_close_rating_a_close_qa_a_hook_refused_after_the_landing_changes_nothing(env):
    """Positive control for "nothing follows": the landed QA's rating is owed with or without a later refused
    close-QA dispatch; a refused one alone owes none."""
    close_rating = importlib.import_module("lib.close_rating")
    m = Main(env.tx)
    env.tx.command("close", FAMILY)
    m.refused(m.dispatch("qa", _close_qa()))
    assert not close_rating.rating_required(sg.command_span.active_span(env.tx.path), FAMILY)
    m.returned(m.dispatch("qa", _close_qa()), "a0c105e0a0c105e0a", YES)
    m.refused(m.dispatch("qa", _close_qa()))
    assert close_rating.rating_required(sg.command_span.active_span(env.tx.path), FAMILY)


def test_commit_bulk_a_landing_a_hook_refused_leaves_the_last_analyst_that_ran(env):
    m = Main(env.tx)
    env.tx.command("commit", "--bulk")
    m.returned(m.dispatch("changelog-analyst", _analyst()), "a0land00000000001", _status(commit_status="committed"))
    m.refused(m.dispatch("changelog-analyst", _analyst()))
    assert sg.run(env) == (0, "")


def test_dispatch_records_leave_out_a_dispatch_a_hook_refused(tmp_path):
    """obligation.dispatch_obligations (declaring_dispatch's records: who owes a task's artifact, the gitignore
    preflight's declared-artifact exemption, the chain resolver's unowed gap): a refused dispatch declares
    nothing. On a5aff80e4 its record stood beside the one that ran."""
    from hooks.lib import obligation
    m = _dev(tmp_path)
    ran = m.dispatch("ba", rrt.obligation_doc("ba", [rrt.ROUND1]))
    m.returned(ran, "a0ba00000000000001", "Round 1 written.")
    m.refused(m.dispatch("ba", rrt.obligation_doc("ba", [rrt.ROUND2])))
    assert [r["tool_use_id"] for r in obligation.dispatch_obligations(m.tx.path)] == [ran]
