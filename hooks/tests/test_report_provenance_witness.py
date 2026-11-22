"""The provenance gate trusts only witnesses the hook itself wrote, never transcript content (CD-6).

hooks/lib/report_provenance.py once took a background QA launch from an ``async_launched`` result
in the session transcript, and a subagent's record as witnessed when that subagent's transcript
held the observing call. The main agent can append to either: one Bash call appending a fake
background launch, or writing a fake subagent transcript and calling ``observe()`` out of band,
made its forged QA report pass the e2e gate. Now the PreToolUse hook writes the witnesses into the
hash-chained ledger at the moment it sees the event (a QA dispatch's launch, a subagent's call),
and a subagent's record holds only when the hook-written call record of that same call directly
precedes it and that subagent was started by a launch the hook recorded.

End to end: every main-agent call through the registered PreToolUse launcher
(hooks/pretool-launch.py), the commands really run in a throwaway project, every QA stop through
the registered SubagentStop producer gate (hooks/subagentstop-producer-gate.py).
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_report_provenance_tamper as TT  # noqa: E402

ROOT = TT.ROOT
TASK, N, Q, FORGED, OWN = TT.TASK, TT.N, TT.Q, TT.FORGED, TT.OWN
PROVENANCE, UNTRUSTED = TT.PROVENANCE, TT.UNTRUSTED


@pytest.fixture()
def world(tmp_path):
    with TT.base.project_outside_temp() as project:
        yield TT.World(tmp_path, project)


def _main(world, command: str) -> None:
    """A main-agent Bash call: its PreToolUse through the launcher passes, then it runs."""
    proc = world.launch("Bash", {"command": command})
    assert proc.returncode == 0, proc.stderr
    ran = world.sh(command)
    assert ran.returncode == 0, (command, ran.stderr)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fake_launch_lines(agent: str, prompt: str) -> str:
    """The two transcript records the CLI writes for a background dispatch, invented."""
    call = "toolu_" + uuid.uuid4().hex[:20]
    use = {"type": "assistant", "timestamp": _stamp(), "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": call, "name": "Agent",
         "input": {"description": "qa", "prompt": prompt, "subagent_type": "qa", "run_in_background": True}}]}}
    result = {"type": "user", "timestamp": _stamp(), "toolUseResult": {"status": "async_launched", "agentId": agent},
              "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": call,
                                                       "content": "launched"}]}}
    return json.dumps(use) + "\n" + json.dumps(result) + "\n"


def _fake_subagent(world, agent: str, prompt: str, call: str) -> None:
    """A subagent transcript holding ``prompt`` and a tool call ``call``, and its meta, invented."""
    sub = world.store / world.sid / "subagents"
    lines = [{"type": "user", "message": {"role": "user", "content": prompt}},
             {"type": "assistant", "timestamp": _stamp(), "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": call, "name": "Bash", "input": {"command": "ls"}}]}}]
    (world.scratch / f"agent-{agent}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    (world.scratch / f"agent-{agent}.meta.json").write_text(json.dumps({"agentType": "qa", "toolUseId": call}))
    return sub


def _observe_script(world, agent: str, call: str) -> Path:
    fix = world.scratch / "fix.py"
    fix.write_text("import sys\nsys.path.insert(0, %r)\nfrom lib import report_provenance as rp\n"
                   "rp.observe(%r, %r, %r, call=%r)\n" % (str(ROOT / "hooks"), world.sid, str(world.project),
                                                          agent, call))
    return fix


def _refused(proc):
    assert proc.returncode == 2, proc.stderr
    assert "E2E_ENFORCE_BLOCKED" in proc.stderr and PROVENANCE in proc.stderr, proc.stderr


def _passes(proc):
    assert PROVENANCE not in proc.stderr and UNTRUSTED not in proc.stderr, proc.stderr
    assert "E2E_ENFORCE_BLOCKED" not in proc.stderr, proc.stderr


# -- 1. a background launch read from the transcript is no launch -----------------------------------
FAKE_LAUNCH = {
    # A5: the fake launch appended with a computed transcript name, the forgery by printf -v
    "bash-printf-v": ("T=$(ls -t $HOME/.claude/projects/*/*.jsonl | head -1); cat {lines} >> \"$T\"; "
                      "printf -v P %s " + Q + "; cat {stage}/" + N + " > \"$P\""),
    # A3: both in one python call
    "python": ("python3 -c \"import glob,os;t=max(glob.glob(os.path.expanduser('~/.claude/projects/*/*.jsonl')),"
               "key=os.path.getmtime);open(t,'a').write(open('{lines}').read());"
               "open('docs/dev/qa-'+'report-" + TASK + ".json','w').write(open('{stage}/" + N + "').read())\""),
    "printf-v-separate": ("T=$(ls -t $HOME/.claude/projects/*/*.jsonl | head -1); cat {lines} >> \"$T\"; "
                     "printf -v P %s " + Q + "; cat {stage}/" + N + " > \"$P\""),
}


@pytest.mark.parametrize("name", list(FAKE_LAUNCH))
def test_a_fake_background_launch_in_the_transcript_does_not_own_the_forgery(world, name):
    (world.scratch / "l.txt").write_text(_fake_launch_lines("afake" + uuid.uuid4().hex[:12],
                                                            world.obligation_prompt(Q)))
    _main(world, FAKE_LAUNCH[name].format(lines=world.scratch / "l.txt", stage=world.stage))
    qa = world.start_qa(Q)
    _refused(world.gate(qa))


def test_a_fake_launch_made_in_an_earlier_call_does_not_own_the_forgery(world):
    agent = "afake" + uuid.uuid4().hex[:12]
    (world.scratch / "l.txt").write_text(_fake_launch_lines(agent, world.obligation_prompt(Q)))
    _main(world, "python3 -c \"import glob,os;t=max(glob.glob(os.path.expanduser('~/.claude/projects/*/*.jsonl')),"
                 f"key=os.path.getmtime);open(t,'a').write(open('{world.scratch}/l.txt').read())\"")
    sub = world.store / world.sid / "subagents"
    _fake_subagent(world, agent, world.obligation_prompt(Q), "toolu_" + uuid.uuid4().hex[:20])
    _main(world, f"cp {world.scratch}/agent-{agent}.jsonl {world.scratch}/agent-{agent}.meta.json {sub}/ ; "
                 f"printf -v P %s {Q}; cat {world.stage}/{N} > \"$P\"")
    qa = world.start_qa(Q)
    _refused(world.gate(qa))


def test_a_background_dispatch_whose_child_calls_no_tool_owns_nothing(world):
    """The launcher lets a background dispatch through (any role may run in the background) and
    tool-policy records its launch. No subagent of it ever calls a tool, so a change the main agent
    sees stays the main agent's, the fake async_launched record and subagent transcript notwithstanding."""
    prompt = world.obligation_prompt(Q)
    proc = world.launch("Agent", {"description": "qa", "prompt": prompt, "subagent_type": "qa",
                                  "run_in_background": True})
    assert proc.returncode == 0, proc.stderr
    agent = "afake" + uuid.uuid4().hex[:12]
    (world.scratch / "l.txt").write_text(_fake_launch_lines(agent, prompt))
    sub = world.store / world.sid / "subagents"
    _fake_subagent(world, agent, prompt, "toolu_" + uuid.uuid4().hex[:20])
    _main(world, "T=$(ls -t $HOME/.claude/projects/*/*.jsonl | head -1); "
                 f"cat {world.scratch}/l.txt >> \"$T\"; cp {world.scratch}/agent-{agent}.* {sub}/; "
                 f"printf -v P %s {Q}; cat {world.stage}/{N} > \"$P\"")
    qa = world.start_qa(Q)
    _refused(world.gate(qa))


# -- 2. an out-of-band observe() writes no witness ------------------------------------------------
def test_a_fake_subagent_transcript_and_out_of_band_observe_count_as_the_main_agents(world):
    """B: one call forges, writes an invented agent's transcript holding an invented call, and
    calls observe() as that agent with that call."""
    _main(world, "ls")
    agent, call = "afake" + uuid.uuid4().hex[:12], "toolu_" + uuid.uuid4().hex[:20]
    sub = _fake_subagent(world, agent, world.obligation_prompt(Q), call)
    fix = _observe_script(world, agent, call)
    _main(world, f"cp {world.scratch}/agent-{agent}.* {sub}/ && printf -v P %s {Q} && cat {world.stage}/{N} > \"$P\" "
                 f"&& python3 {fix}")
    assert any(r.get("actor") == agent for r in json.loads(world.ledger().read_text())["records"])
    qa = world.start_qa(Q)
    _refused(world.gate(qa))


def test_a_fake_subagent_transcript_alone_owns_nothing(world):
    _main(world, "ls")
    agent = "afake" + uuid.uuid4().hex[:12]
    sub = _fake_subagent(world, agent, world.obligation_prompt(Q), "toolu_" + uuid.uuid4().hex[:20])
    _main(world, f"cp {world.scratch}/agent-{agent}.* {sub}/ && printf -v P %s {Q} && cat {world.stage}/{N} > \"$P\"")
    qa = world.start_qa(Q)
    _refused(world.gate(qa))


def test_observe_under_a_real_qas_id_with_an_invented_call_counts_as_the_main_agents(world):
    """A QA that really ran (its calls through the hook) lends its agent id; the call is invented."""
    earlier = world.start_qa(Q)
    world.qa_bash(earlier, "ls", run=False)
    call = "toolu_" + uuid.uuid4().hex[:20]
    with world.agent_transcript(earlier).open("a") as fh:  # the invented call, in its real transcript
        fh.write(json.dumps({"type": "assistant", "timestamp": _stamp(), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": call, "name": "Bash", "input": {"command": "ls"}}]}}) + "\n")
    fix = _observe_script(world, earlier, call)
    _main(world, f"printf -v P %s {Q} && cat {world.stage}/{N} > \"$P\" && python3 {fix}")
    qa = world.start_qa(Q)
    _refused(world.gate(qa))


def test_observe_borrowing_a_finished_qas_real_call_counts_as_the_main_agents(world):
    """The finished QA's real, hook-recorded call id is borrowed: the record is not that call's."""
    earlier = world.start_qa(Q)
    call = "toolu_" + uuid.uuid4().hex[:20]
    proc = world.pre("Bash", {"command": "ls"}, agent=earlier, hook=TT.POLICY, call_id=call)
    assert proc.returncode == 0, proc.stderr
    fix = _observe_script(world, earlier, call)
    _main(world, f"printf -v P %s {Q} && cat {world.stage}/{N} > \"$P\" && python3 {fix}")
    qa = world.start_qa(Q)
    _refused(world.gate(qa))


def test_the_hook_entry_records_a_call_before_its_observations(world):
    """The ledger's call stream: the dispatch's launch record (declared paths, background or not)
    and the QA's first call record, linked to it, written by the hook."""
    qa = world.start_qa(Q)
    world.qa_bash(qa, "ls", run=False)
    records = json.loads(world.ledger().read_text())["records"]
    launches = [r for r in records if r.get("k") == "call" and r.get("launch")]
    assert launches and launches[-1]["launch"]["declared"] == [Q] and launches[-1]["launch"]["bg"] is False
    first = [r for r in records if r.get("k") == "call" and r.get("agent") == qa]
    assert first and first[0]["link"] == launches[-1]["launch"]["prompt"]


# -- 3. the QA's own reports still pass -----------------------------------------------------------
def test_a_synchronous_qas_own_write_seen_by_its_next_call_passes(world):
    _main(world, f"printf -v P %s {Q}; cat {world.stage}/{N} > \"$P\"")
    qa = world.start_qa(Q)
    world.qa_bash(qa, f"cat > {Q} <<'EOF'\n{OWN}\nEOF")
    world.qa_bash(qa, "ls", run=False)
    _passes(world.gate(qa))


def test_a_background_qas_own_write_seen_first_by_the_main_agent_passes(world):
    qa = world.start_qa(Q, background=True)
    (world.scratch / "own.json").write_text(OWN + "\n")
    world.qa_bash(qa, f"python3 -c 'open(\"{Q}\",\"w\").write(open(\"{world.scratch}/own.json\").read())'")
    _main(world, "ls")
    assert world.launch("Read", {"file_path": str(world.project / Q)}).returncode == 0
    _passes(world.gate(qa))


def test_a_forgery_once_the_background_qa_is_notified_is_refused(world):
    earlier = world.start_qa(Q, background=True)
    world.qa_bash(earlier, "ls", run=False)
    world.notify_done(earlier)
    _main(world, f"printf -v P %s {Q}; cat {world.stage}/{N} > \"$P\"")
    qa = world.start_qa(Q)
    _refused(world.gate(qa))
