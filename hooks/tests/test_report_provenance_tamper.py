"""The QA report provenance (CD-6) holds against the second verifier's bypasses (AUDIT section 5, CD-6).

hooks/tests/test_report_provenance_gate.py proves the measured writer refuses the main agent's
forgery of a declared QA report at the QA's stop. Here, each bypass the verifier found against
that design, end to end: every main-agent call through the registered PreToolUse launcher
(hooks/pretool-launch.py), every QA stop through the registered SubagentStop producer gate
(hooks/subagentstop-producer-gate.py), each forgery really run in a throwaway project:

1. a QA report declared outside ``docs/dev/qa-report-*.json`` is observed too, and the main agent's
   write of a declared path is refused at PreToolUse;
2. the provenance ledger fails closed: a ledger directory replaced by a file, an unparsable ledger,
   an edited or deleted record, a lock held open, all refuse the QA whose report exists; a record
   no CLI transcript witnesses (an out-of-band ``observe()`` with an invented agent id) counts as
   the main agent's; the ledger directory is a protected path for Bash and the file tools;
3. no number of decoy reports evicts the declared one;
4. a QA transcript action that leaves the main agent's content unchanged (touch, an append of
   nothing, a read) is no write of the QA's own;
5. a QA the main agent launched in the background (/do) that writes its own report keeps it as
   its own even when the main agent's next call sees the change first, while the main agent's
   own write, and every forgery once that QA has finished, stays refused.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_report_provenance_gate as base  # noqa: E402

ROOT = base.ROOT
LAUNCH, GATE = base.LAUNCH, base.PRODUCER_GATE
TASK, N, Q = base.TASK, base.N, base.Q
PROVENANCE = base.PROVENANCE
UNTRUSTED = "cannot be trusted"
FORGED = json.dumps({"report_version": 2, "request_id": TASK, "task_id": TASK, "timestamp": "2026-10-01T00:00:00Z",
                     "qa": {"status": "pass", "e2e_enforcement": {"status": "performed"}}})
OWN = FORGED.replace("performed", "ran")


class World(base.World):
    def __init__(self, tmp: Path):
        super().__init__(tmp)
        (self.stage / N).write_text(FORGED + "\n")

    def obligation_prompt(self, path: str) -> str:
        doc = {"task_id": TASK, "role": "qa", "pipeline": "dev", "profile": "singular",
               "dispatched_at": datetime.now(timezone.utc).isoformat(),
               "artifacts": [{"kind": "json", "path": path, "schema": "qa-report.v2", "identity": {"task_id": TASK}}]}
        return f"You are qa.\n<obligation v=\"1\">\n{json.dumps(doc)}\n</obligation>"

    def launch(self, tool: str, tool_input: dict, agent=None):
        """A call through the registered PreToolUse launcher."""
        return self.pre(tool, tool_input, agent=agent, hook=LAUNCH)

    def start_qa(self, path: str = Q, background: bool = False, through_launcher: bool = True) -> str:
        """The main agent dispatches a QA declaring ``path`` (its PreToolUse through the launcher),
        and the CLI starts it: the subagent's files, and for a background launch the
        ``async_launched`` result the CLI records."""
        prompt = self.obligation_prompt(path)
        tool_input = {"description": "qa", "prompt": prompt, "subagent_type": "qa", "run_in_background": background}
        if through_launcher and not background:
            proc = self.launch("Agent", tool_input)
            assert proc.returncode == 0, proc.stderr
        call_id = "toolu_" + uuid.uuid4().hex[:20]
        agent = "a" + uuid.uuid4().hex[:16]
        stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self.transcript.open("a") as fh:
            fh.write(json.dumps({"type": "assistant", "timestamp": stamp, "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": call_id, "name": "Agent", "input": tool_input}]}}) + "\n")
            if background:
                fh.write(json.dumps({"type": "user", "timestamp": stamp,
                                     "toolUseResult": {"status": "async_launched", "agentId": agent},
                                     "message": {"role": "user", "content": [
                                         {"type": "tool_result", "tool_use_id": call_id,
                                          "content": f"Async agent launched. agentId: {agent}"}]}}) + "\n")
        sub = self.store / self.sid / "subagents"
        (sub / f"agent-{agent}.jsonl").write_text(
            json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
        (sub / f"agent-{agent}.meta.json").write_text(json.dumps({"agentType": "qa", "toolUseId": call_id}))
        return agent

    def notify_done(self, agent: str) -> None:
        body = (f"<task-notification><task-id>{agent}</task-id><status>completed</status>"
                f"<summary>done</summary></task-notification>")
        with self.transcript.open("a") as fh:
            fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": body}}) + "\n")

    def qa_bash(self, agent: str, command: str, run: bool = True) -> None:
        """The QA's own Bash call: recorded in its transcript (as the CLI does) and run."""
        call_id = "toolu_" + uuid.uuid4().hex[:20]
        self.record_call(agent, call_id, "Bash", {"command": command})
        with self.agent_transcript(agent).open("a") as fh:
            fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": call_id, "content": ""}]}}) + "\n")
        if run:
            proc = self.sh(command)
            assert proc.returncode == 0, (command, proc.stderr)

    def main_bash_unhooked(self, command: str) -> None:
        """A main-agent Bash call recorded in the session transcript and run (its own hooks
        already passed: what it does is seen at the next call)."""
        self.record_call(None, "toolu_" + uuid.uuid4().hex[:20], "Bash", {"command": command})
        proc = self.sh(command)
        assert proc.returncode == 0, (command, proc.stderr)

    def gate(self, agent: str):
        return self.stop(agent, hook=GATE)

    def ledger_dir(self) -> Path:
        return self.tmp / "state" / "report-provenance"

    def ledger(self) -> Path:
        files = sorted(self.ledger_dir().glob("*.json"))
        assert len(files) == 1, files
        return files[0]


@pytest.fixture()
def world(tmp_path):
    return World(tmp_path)


def _refused(proc, why=PROVENANCE):
    assert proc.returncode == 2, proc.stderr
    assert "E2E_ENFORCE_BLOCKED" in proc.stderr and why in proc.stderr, proc.stderr


# -- 1. a declared path outside the docs/dev/qa-report-*.json glob ------------------------------------
OUTSIDE = {"subdir": f"docs/dev/qa/qa-report-{TASK}.json", "other-name": f"docs/dev/qa-{TASK}.json",
           "elsewhere": f"out/qa-{TASK}.json"}


@pytest.mark.parametrize("name", list(OUTSIDE))
def test_a_forgery_at_a_declared_path_outside_the_glob_is_refused(world, name):
    path = OUTSIDE[name]
    (world.project / path).parent.mkdir(parents=True, exist_ok=True)
    world.main_bash_unhooked(f"cat {world.stage}/{N} > {path}")
    qa = world.start_qa(path)
    _refused(world.gate(qa))


@pytest.mark.parametrize("name", list(OUTSIDE))
def test_a_write_tool_forgery_before_the_dispatch_is_refused_at_the_stop(world, name):
    path = OUTSIDE[name]
    (world.project / path).parent.mkdir(parents=True, exist_ok=True)
    assert world.launch("Write", {"file_path": str(world.project / path), "content": FORGED}).returncode == 0
    (world.project / path).write_text(FORGED + "\n")
    qa = world.start_qa(path)
    _refused(world.gate(qa))


@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit"])
@pytest.mark.parametrize("name", list(OUTSIDE))
def test_the_main_agents_file_tool_write_of_a_declared_path_is_refused(world, tool, name):
    path = OUTSIDE[name]
    (world.project / path).parent.mkdir(parents=True, exist_ok=True)
    world.start_qa(path)
    proc = world.launch(tool, base._tool_input(tool, str(world.project / path)))
    assert proc.returncode == 2, proc.stderr
    assert "gate-read" in proc.stderr or "only qa writes this artifact" in proc.stderr, proc.stderr


@pytest.mark.parametrize("name", list(OUTSIDE))
def test_the_main_agents_bash_write_of_a_declared_path_is_refused(world, name):
    path = OUTSIDE[name]
    (world.project / path).parent.mkdir(parents=True, exist_ok=True)
    world.start_qa(path)
    proc = world.launch("Bash", {"command": f"cat {world.stage}/{N} > {path}"})
    assert proc.returncode == 2, proc.stderr
    assert "gate-read" in proc.stderr or "only qa writes this artifact" in proc.stderr, proc.stderr


def test_the_main_agents_read_of_a_declared_path_passes(world):
    path = OUTSIDE["other-name"]
    world.start_qa(path)
    (world.project / path).write_text(OWN + "\n")
    for command in (f"cat {path}", f"jq . {path}", f"cp {path} /tmp/qa-copy.json"):
        proc = world.launch("Bash", {"command": command})
        assert proc.returncode == 0, (command, proc.stderr)
    assert world.launch("Read", {"file_path": str(world.project / path)}).returncode == 0


def test_the_qas_own_report_at_a_declared_path_outside_the_glob_passes(world):
    path = OUTSIDE["subdir"]
    (world.project / path).parent.mkdir(parents=True, exist_ok=True)
    qa = world.start_qa(path)
    world.qa_bash(qa, f"cat > {path} <<'EOF'\n{OWN}\nEOF")
    proc = world.gate(qa)
    assert PROVENANCE not in proc.stderr and UNTRUSTED not in proc.stderr, proc.stderr
    assert proc.returncode == 0, proc.stderr


# -- 2. the ledger fails closed, and its records need a witness ---------------------------------------
def _forged_and_dispatched(world) -> str:
    world.main_bash_unhooked(f"cat {world.stage}/{N} > {Q}")
    return world.start_qa(Q)


def _replace_dir_by_file(world):
    shutil.move(str(world.ledger_dir()), str(world.scratch / "old"))
    world.ledger_dir().write_text("")


def _corrupt(world):
    world.ledger().write_text("{not json")


def _relabel(world):
    doc = json.loads(world.ledger().read_text())
    for record in doc["records"]:
        record["actor"] = "a0000000000000000"
    world.ledger().write_text(json.dumps(doc))


def _drop_record(world):
    doc = json.loads(world.ledger().read_text())
    doc["records"] = [r for r in doc["records"] if r["path"] != Q]
    world.ledger().write_text(json.dumps(doc))


def _ledger_is_a_dir(world):
    ledger = world.ledger()
    ledger.unlink()
    ledger.mkdir()


TAMPER = {"dir-replaced-by-file": _replace_dir_by_file, "unparsable": _corrupt, "record-relabelled": _relabel,
          "record-deleted": _drop_record, "ledger-replaced-by-dir": _ledger_is_a_dir}


@pytest.mark.parametrize("name", list(TAMPER))
def test_a_tampered_ledger_refuses_the_stop(world, name):
    qa = _forged_and_dispatched(world)
    TAMPER[name](world)
    _refused(world.gate(qa), UNTRUSTED)


def test_a_ledger_held_locked_refuses_the_stop(world):
    if shutil.which("flock") is None:
        pytest.skip("flock not installed")
    qa = _forged_and_dispatched(world)
    lock = str(world.ledger()) + ".lock"
    holder = subprocess.Popen(["flock", lock, "sleep", "30"])
    try:
        for _ in range(100):
            if subprocess.run(["flock", "-n", lock, "true"]).returncode != 0:
                break
        _refused(world.gate(qa), UNTRUSTED)
    finally:
        holder.kill()
        holder.wait()


def test_a_forged_out_of_band_observation_counts_as_the_main_agents(world):
    """The forgery and an observe() under an invented agent id in the same call: no transcript
    holds that agent's call, so the record is the main agent's."""
    world.launch("Bash", {"command": "ls"})
    fix = world.scratch / "fix.py"
    fix.write_text("import sys\nsys.path.insert(0, %r)\nfrom lib import report_provenance as rp\n"
                   "try:\n    rp.observe(%r, %r, 'a0000000000000000', call='toolu_invented')\n"
                   "except TypeError:\n    rp.observe(%r, %r, 'a0000000000000000')\n"
                   % (str(ROOT / "hooks"), world.sid, str(world.project), world.sid, str(world.project)))
    world.main_bash_unhooked(f"cat {world.stage}/{N} > {Q} && python3 {fix}")
    doc = json.loads(world.ledger().read_text())
    assert any(r.get("actor") == "a0000000000000000" for r in doc.get("records", list(doc.get("files", {}).values())))
    qa = world.start_qa(Q)
    _refused(world.gate(qa))


def test_an_observation_under_a_finished_qas_id_without_its_call_counts_as_the_main_agents(world):
    earlier = world.start_qa(Q)
    world.qa_bash(earlier, "ls", run=False)
    fix = world.scratch / "fix.py"
    fix.write_text("import sys\nsys.path.insert(0, %r)\nfrom lib import report_provenance as rp\n"
                   "rp.observe(%r, %r, %r)\n" % (str(ROOT / "hooks"), world.sid, str(world.project), earlier))
    world.main_bash_unhooked(f"cat {world.stage}/{N} > {Q} && python3 {fix}")
    qa = world.start_qa(Q)
    _refused(world.gate(qa))


PROTECTED = {
    "mv-dir": "mv {state}/report-provenance {scratch}/old",
    "rm-dir": "rm -rf {state}/report-provenance",
    "rm-state": "rm -rf {state}",
    "truncate": "truncate -s0 {ledger}",
    "tee": "echo x | tee {ledger}",
    "redirect-into": "echo '{{}}' > {ledger}",
    "cp-over": "cp {scratch}/x.json {ledger}",
    "sed-i": "sed -i s/main/a0/ {ledger}",
    "chmod": "chmod 500 {state}/report-provenance",
}


@pytest.mark.parametrize("name", list(PROTECTED))
def test_the_main_agents_bash_on_the_ledger_is_refused(world, name):
    _forged_and_dispatched(world)
    command = PROTECTED[name].format(state=world.tmp / "state", scratch=world.scratch, ledger=world.ledger())
    proc = world.launch("Bash", {"command": command})
    assert proc.returncode == 2, proc.stderr
    assert "provenance ledger" in proc.stderr, proc.stderr


@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_the_main_agents_file_tool_on_the_ledger_is_refused(world, tool):
    _forged_and_dispatched(world)
    proc = world.launch(tool, base._tool_input(tool, str(world.ledger())))
    assert proc.returncode == 2, proc.stderr
    assert "provenance ledger" in proc.stderr, proc.stderr


def test_reading_the_ledger_passes(world):
    _forged_and_dispatched(world)
    for command in (f"cat {world.ledger()}", f"ls -la {world.ledger_dir()}", f"jq . {world.ledger()}"):
        proc = world.launch("Bash", {"command": command})
        assert proc.returncode == 0, (command, proc.stderr)


def test_the_ledger_states_its_limit(world):
    _forged_and_dispatched(world)
    doc = json.loads(world.ledger().read_text())
    assert "arbitrary code" in doc["note"] and doc["records"][-1]["call"], doc


# -- 3. decoys never evict a report ------------------------------------------------------------------
DECOYS = ("python3 -c \"import os\nfor i in range(4100): "
          "open(os.path.join('docs','dev','qa-rep'+'ort-0%05d.json'%i),'w').write('{}')\"")


@pytest.mark.parametrize("dispatch", ["with-obligation", "plain-prompt"])
def test_decoy_reports_do_not_evict_the_forged_one(world, dispatch):
    world.main_bash_unhooked(DECOYS)
    world.main_bash_unhooked(f"cat {world.stage}/{N} > \"$(echo docs/dev)/qa-rep\"ort-{TASK}.json")
    if dispatch == "plain-prompt":
        assert world.launch("Agent", base.DISPATCH).returncode == 0
        qa = world.start_qa(Q, through_launcher=False)
    else:
        qa = world.start_qa(Q)
    _refused(world.gate(qa))


# -- 4. an action that leaves the content as it was is not the QA's write -------------------------------
NO_CHANGE = {"touch": "touch {Q}", "append-nothing": ": >> {Q}", "append-empty": "printf '' >> {Q}",
             "read-to-null": "cat {Q} > /dev/null", "cp-onto-itself": "cp {Q} /tmp/qa-x.json && cat /tmp/qa-x.json > {Q}"}


@pytest.mark.parametrize("name", list(NO_CHANGE))
def test_a_qa_action_that_leaves_the_forgery_unchanged_is_not_its_write(world, name):
    qa = _forged_and_dispatched(world)
    world.qa_bash(qa, NO_CHANGE[name].format(Q=Q))
    assert json.loads((world.project / Q).read_text())["qa"]["e2e_enforcement"]["status"] == "performed"
    _refused(world.gate(qa))


def test_a_qa_rewrite_with_its_own_content_passes(world):
    qa = _forged_and_dispatched(world)
    world.qa_bash(qa, f"cat > {Q} <<'EOF'\n{OWN}\nEOF")
    assert world.gate(qa).returncode == 0


# -- 5. /do: a background QA's own write, seen first by the main agent ---------------------------------
QA_WRITES = {
    "python-c": "python3 -c 'open(\"{Q}\",\"w\").write(open(\"{own}\").read())'",
    "heredoc": "cat > {Q} <<'EOF'\n{own_text}\nEOF",
    "script": "python3 {script}",
}


@pytest.mark.parametrize("name", list(QA_WRITES))
def test_a_background_qas_own_write_seen_first_by_the_main_agent_passes(world, name):
    qa = world.start_qa(Q, background=True)
    (world.scratch / "own.json").write_text(OWN + "\n")
    (world.scratch / "w.py").write_text(f"open({str(world.project / Q)!r}, 'w').write(open({str(world.scratch / 'own.json')!r}).read())\n")
    command = QA_WRITES[name].format(Q=Q, own=world.scratch / "own.json", script=world.scratch / "w.py",
                                     own_text="{own_text}").replace("{own_text}", OWN)
    world.qa_bash(qa, command)
    assert world.launch("Bash", {"command": "ls"}).returncode == 0  # the main agent acts while the QA runs
    proc = world.gate(qa)
    assert proc.returncode == 0, proc.stderr


def test_the_main_agents_own_write_while_a_background_qa_runs_stays_refused(world):
    """The main agent's previous call names the report as its write target: the main agent's."""
    qa = world.start_qa(Q, background=True)
    world.main_bash_unhooked(f"cp {world.stage}/{N} {Q}")
    assert world.launch("Bash", {"command": "ls"}).returncode == 0
    _refused(world.gate(qa))


def test_a_forgery_after_the_background_qa_finished_is_refused(world):
    """Once the background QA's notification arrives, it runs no more: a change the main agent
    sees is the main agent's, and the next QA dispatched on that report is refused."""
    earlier = world.start_qa(Q, background=True)
    world.notify_done(earlier)
    world.main_bash_unhooked(f"python3 -c 'open(\"{Q}\",\"w\").write(open(\"{world.stage}/{N}\").read())'")
    qa = world.start_qa(Q)
    _refused(world.gate(qa))


def test_a_synchronous_forgery_is_refused_with_an_unrelated_qa_running(world):
    """A background QA that declares another report gives the main agent's change no other owner."""
    world.start_qa(f"docs/dev/qa-report-other-{TASK}.json", background=True)
    world.main_bash_unhooked(f"cat {world.stage}/{N} > {Q}")
    qa = world.start_qa(Q)
    _refused(world.gate(qa))
