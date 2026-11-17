"""A QA report the main agent wrote is not the QA's evidence, by any route (AUDIT section 5, CD-6).

The orchestrator could forge ``docs/dev/qa-report-*.json`` (an ``e2e_enforcement.status`` of
"performed") with a Bash heredoc into ``awk``, ``sort -o``, ``sed w``, a computed path, an archive,
a script... and hooks/subagentstop-e2e-enforce.py trusted whatever file sat at the declared path.
No reading of a command line lists every route, so the writer is measured: every call's PreToolUse
(hooks/pretool-tool-policy.py) records, per session, who changed each qa-report since the session
last looked (hooks/lib/report_provenance.py), and the e2e gate refuses a QA whose declared report
holds exactly what an observation of the main agent recorded, unless the QA's own transcript writes
it. Each forgery below really runs (bash in a throwaway project), then the main agent's next call
(the QA's dispatch) runs the real PreToolUse hook, then the QA stops without writing: the gate must
refuse. The QA's own writes, by any route, still pass, as on the base.

Also here: the main agent's harmless reads that the first CD-6 rule refused pass the whole PreToolUse
launcher again, and the main agent's Write/Edit/MultiEdit/NotebookEdit of a qa-report or ba-qa-report
is refused at PreToolUse.
"""

from __future__ import annotations

import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import uuid
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "hooks" / "pretool-tool-policy.py"
LAUNCH = ROOT / "hooks" / "pretool-launch.py"
E2E = ROOT / "hooks" / "subagentstop-e2e-enforce.py"
PRODUCER_GATE = ROOT / "hooks" / "subagentstop-producer-gate.py"
TASK = "20261028-101010"
N = f"qa-report-{TASK}.json"
Q = f"docs/dev/{N}"
FORGED = '{"task_id": "20261028-101010", "e2e_enforcement": {"status": "performed"}, "qa": {"status": "pass"}}'
HONEST = '{"task_id": "20261028-101010", "e2e_enforcement": {"status": "skipped_without_justification"}}'
OWN = '{"task_id": "20261028-101010", "e2e_enforcement": {"status": "ran"}, "qa": {"status": "pass"}}'
PROVENANCE = "written by the main agent"
DISPATCH = {"description": "qa", "prompt": "You are qa.", "subagent_type": "qa", "run_in_background": False}


def _slug(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path.resolve()))


class World:
    """A throwaway project, HOME, state dir and session; the hooks run as subprocesses."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.project = tmp / "project"
        (self.project / "docs" / "dev").mkdir(parents=True)
        (self.project / "docs" / "zz").mkdir(parents=True)
        (self.project / "src").mkdir()
        self.home = tmp / "home"
        self.sid = "sess-" + uuid.uuid4().hex[:8]
        self.store = self.home / ".claude" / "projects" / _slug(self.project)
        (self.store / self.sid / "subagents").mkdir(parents=True)
        self.transcript = self.store / f"{self.sid}.jsonl"
        self.transcript.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": "go"}}) + "\n")
        self.scratch = tmp / "scratch"
        self.scratch.mkdir()
        self.stage = tmp / "stage"  # the forged report the copy forms copy from
        self.stage.mkdir()
        (self.stage / N).write_text(FORGED + "\n")
        with tarfile.open(self.scratch / "r.tar", "w") as tar:
            tar.add(self.stage / N, arcname=N)

    def env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
        env.update({"HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
                    "CLAUDE_STATE_DIR": str(self.tmp / "state"), "CLAUDE_PROJECT_DIR": str(self.project),
                    "TMPDIR": str(self.scratch), "PYTHONDONTWRITEBYTECODE": "1"})
        return env

    def sh(self, command: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", "-c", command], cwd=str(self.project), env=self.env(),
                              capture_output=True, text=True, timeout=60)

    def dispatch(self) -> str:
        """A QA dispatched with an obligation declaring the report at Q."""
        doc = {"task_id": TASK, "role": "qa", "pipeline": "dev", "profile": "singular",
               "dispatched_at": datetime.now(timezone.utc).isoformat(),
               "artifacts": [{"kind": "json", "path": Q, "schema": "qa-report.v2", "identity": {"task_id": TASK}}]}
        prompt = f"You are qa.\n<obligation v=\"1\">\n{json.dumps(doc)}\n</obligation>"
        agent = "a" + uuid.uuid4().hex[:16]
        call_id = "toolu_" + uuid.uuid4().hex[:20]
        with self.transcript.open("a") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": call_id, "name": "Agent",
                 "input": {"description": "qa", "prompt": prompt, "subagent_type": "qa"}}]}}) + "\n")
        sub = self.store / self.sid / "subagents"
        (sub / f"agent-{agent}.jsonl").write_text(
            json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
        (sub / f"agent-{agent}.meta.json").write_text(json.dumps({"agentType": "qa", "toolUseId": call_id}))
        return agent

    def agent_transcript(self, agent: str) -> Path:
        return self.store / self.sid / "subagents" / f"agent-{agent}.jsonl"

    def pre(self, tool: str, tool_input: dict, agent: str | None = None, hook: Path = POLICY):
        data = {"session_id": self.sid, "transcript_path": str(self.transcript), "cwd": str(self.project),
                "hook_event_name": "PreToolUse", "permission_mode": "default", "tool_name": tool,
                "tool_input": tool_input, "tool_use_id": "toolu_" + uuid.uuid4().hex[:24]}
        if agent:
            data.update(agent_id=agent, agent_type="qa")
        return subprocess.run([sys.executable, str(hook)], input=json.dumps(data), capture_output=True,
                              text=True, cwd=str(self.tmp), env=self.env(), timeout=120)

    def main_dispatches(self):
        """The main agent's next call: the QA's dispatch (its PreToolUse observes the reports)."""
        proc = self.pre("Agent", DISPATCH)
        assert proc.returncode == 0, proc.stderr
        return proc

    def stop(self, agent: str, hook: Path = E2E):
        data = {"session_id": self.sid, "agent_id": agent, "hook_event_name": "SubagentStop",
                "transcript_path": str(self.transcript)}
        return subprocess.run([sys.executable, str(hook)], input=json.dumps(data), capture_output=True,
                              text=True, cwd=str(self.project), env=self.env(), timeout=120)


@pytest.fixture()
def world(tmp_path):
    return World(tmp_path)


@pytest.fixture(scope="module")
def http_root(tmp_path_factory):
    """A local HTTP server for the wget form (wget reads no file:// URL)."""
    root = tmp_path_factory.mktemp("served")
    (root / N).write_text(FORGED + "\n")
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(http.server.SimpleHTTPRequestHandler, directory=str(root)))
    server.RequestHandlerClass.log_message = lambda *a, **k: None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()


HD = f"<<'EOF'\n{FORGED}\nEOF"
# name -> (command template, tools it needs, whether a QA's failing report already sits at Q)
FORGERIES = {
    # the seven heredoc forms the verifier ran for real
    "heredoc-awk-print": (f"awk '{{print > \"{Q}\"}}' {HD}", ("awk",), False),
    "heredoc-sort-o": (f"sort -o {Q} {HD}", ("sort",), False),
    "heredoc-sed-w": (f"sed -n 'w {Q}' {HD}", ("sed",), False),
    "heredoc-uniq": (f"uniq - {Q} {HD}", ("uniq",), False),
    "heredoc-bash-c-positional": (f"bash -c 'cat > \"$1\"' _ {Q} {HD}", (), False),
    "heredoc-printf-v": (f"printf -v P %s {Q}; cat > \"$P\" {HD}", (), False),
    "heredoc-glob-dir": (f"cat > docs/de[v]/{N} {HD}", (), True),
    # brace, glob, variable and directory forms
    "brace-name-tee": (f"tee docs/dev/{{qa,zz}}-report-{TASK}.json >/dev/null {HD}", ("tee",), False),
    "brace-dir-tee": (f"tee docs/{{dev,zz}}/{N} >/dev/null {HD}", ("tee",), False),
    "glob-dir-star": (f"cat {{stage}}/{N} > do*/dev/{N}", (), True),
    "glob-dir-question": (f"cp {{stage}}/{N} docs/d?v/{N}", ("cp",), True),
    "cdpath": (f"CDPATH=docs cd dev && cat {{stage}}/{N} > {N}", (), False),
    "cd-computed": (f"D=docs/dev; cd \"$D\" && cat {{stage}}/{N} > {N}", (), False),
    "cd-dash": (f"cd docs/dev && cd {{scratch}} && cd - >/dev/null && cat {{stage}}/{N} > {N}", (), False),
    "computed-dir": (f"D=docs/dev; cat {{stage}}/{N} > \"$D/{N}\"", (), False),
    "bash-procsub": (f"bash <(echo 'cat {{stage}}/{N} > {Q}')", (), False),
    "eval-var": (f"C='cat {{stage}}/{N} > {Q}'; eval \"$C\"", (), False),
    "xargs-built-name": (f"echo report-{TASK}.json | xargs -I@ cp {{stage}}/{N} docs/dev/qa-@", ("xargs", "cp"), False),
    "script-written-then-run": (f"printf 'cat {{stage}}/{N} > {Q}\\n' > {{scratch}}/w.sh && sh {{scratch}}/w.sh", (), False),
    # downloaders and copiers into the directory
    "curl-O-after-cd": (f"cd docs/dev && curl -sS -O file://{{stage}}/{N}", ("curl",), False),
    "curl-output-dir": (f"curl -sS --output-dir docs/dev -O file://{{stage}}/{N}", ("curl",), False),
    "wget-P": (f"wget -q -P docs/dev http://127.0.0.1:{{port}}/{N}", ("wget",), False),
    "openssl-out": (f"openssl enc -in {{stage}}/{N} -out {Q}", ("openssl",), False),
    "tar-x-C": ("tar -xf {scratch}/r.tar -C docs/dev", ("tar",), False),
    "cp-r-dir-contents": ("cp -r {stage}/. docs/dev/", ("cp",), False),
    # interpreters
    "node-cpSync": (f"node -e \"require('fs').cpSync('{{stage}}/{N}','{Q}')\"", ("node",), False),
    "python-concat": (f"python3 -c \"open('docs/dev/qa-'+'report-{TASK}.json','w').write(open('{{stage}}/{N}').read())\"",
                      ("python3",), False),
    "python-env": (f"P={Q} python3 -c \"import os; open(os.environ['P'],'w').write(open('{{stage}}/{N}').read())\"",
                   ("python3",), False),
}


def _forge(world: World, name: str, port=None) -> None:
    template, needs, pre_existing = FORGERIES[name]
    missing = [t for t in needs if shutil.which(t) is None]
    if missing:
        pytest.skip(f"{missing} not installed")
    if pre_existing:
        # A QA's honest, failing report from an earlier round; the main agent overwrites it.
        (world.project / Q).write_text(HONEST + "\n")
        earlier = world.dispatch()
        assert world.pre("Read", {"file_path": str(world.project / Q)}, agent=earlier).returncode == 0
    command = template.replace("{stage}", str(world.stage)).replace("{scratch}", str(world.scratch))
    command = command.replace("{port}", str(port))
    proc = world.sh(command)
    assert proc.returncode == 0, (command, proc.stderr)
    assert json.loads((world.project / Q).read_text())["e2e_enforcement"]["status"] == "performed", command


@pytest.mark.parametrize("name", list(FORGERIES))
def test_a_report_the_main_agent_forged_is_refused_at_the_qas_stop(world, http_root, name):
    _forge(world, name, http_root)
    world.main_dispatches()
    qa = world.dispatch()
    # The QA works (its own calls observe nothing new) and stops without writing its report.
    assert world.pre("Bash", {"command": f"cat {Q}"}, agent=qa).returncode == 0
    proc = world.stop(qa)
    assert proc.returncode == 2, proc.stderr
    assert "E2E_ENFORCE_BLOCKED" in proc.stderr and PROVENANCE in proc.stderr, proc.stderr
    assert Q in proc.stderr


def test_the_forgery_end_to_end_through_the_registered_hooks(world):
    """The heredoc forgery through the registered launcher and the registered SubagentStop gate."""
    proc = world.sh(f"sort -o {Q} {HD}")
    assert proc.returncode == 0, proc.stderr
    launched = world.pre("Agent", DISPATCH, hook=LAUNCH)
    assert launched.returncode == 0, launched.stderr
    qa = world.dispatch()
    proc = world.stop(qa, hook=PRODUCER_GATE)
    assert proc.returncode == 2, proc.stderr
    assert PROVENANCE in proc.stderr, proc.stderr


# -- the QA's own report, by any route, passes as on the base ----------------------------------------
def test_the_qas_own_heredoc_report_passes(world):
    world.main_dispatches()
    qa = world.dispatch()
    assert world.sh(f"cat > {Q} <<'EOF'\n{OWN}\nEOF").returncode == 0
    proc = world.stop(qa)
    assert proc.returncode == 0, proc.stderr


def test_the_qas_rewrite_by_a_script_of_a_forged_report_passes(world):
    """The QA rewrites the orchestrator's file with its own findings, by a script the parser cannot read."""
    assert world.sh(f"cat > {Q} {HD}").returncode == 0
    world.main_dispatches()
    qa = world.dispatch()
    (world.scratch / "w.py").write_text(f"open({str(world.project / Q)!r}, 'w').write({OWN!r})\n")
    assert world.sh(f"python3 {world.scratch}/w.py").returncode == 0
    assert world.stop(qa).returncode == 0


def test_the_qas_rewrite_seen_at_its_next_call_passes(world):
    assert world.sh(f"cat > {Q} {HD}").returncode == 0
    world.main_dispatches()
    qa = world.dispatch()
    assert world.sh(f"printf '%s' '{OWN}' | python3 -c 'import sys; open(\"{Q}\", \"w\").write(sys.stdin.read())'"
                    ).returncode == 0
    assert world.pre("Read", {"file_path": str(world.project / Q)}, agent=qa).returncode == 0
    assert world.stop(qa).returncode == 0


def test_the_qas_own_write_tool_of_the_same_content_passes(world):
    """Same bytes as the forgery, but the QA's own transcript writes them: the QA's evidence."""
    assert world.sh(f"cat > {Q} {HD}").returncode == 0
    world.main_dispatches()
    qa = world.dispatch()
    with world.agent_transcript(qa).open("a") as fh:
        fh.write(json.dumps({"type": "assistant", "cwd": str(world.project), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_w1", "name": "Write",
             "input": {"file_path": str(world.project / Q), "content": FORGED}}]}}) + "\n")
        fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_w1", "content": "ok"}]}}) + "\n")
    (world.project / Q).write_text(FORGED + "\n")
    assert world.stop(qa).returncode == 0


def test_a_touch_does_not_make_the_forgery_the_qas(world):
    assert world.sh(f"cat > {Q} {HD}").returncode == 0
    world.main_dispatches()
    qa = world.dispatch()
    assert world.sh(f"touch {Q}").returncode == 0
    assert world.pre("Read", {"file_path": str(world.project / Q)}, agent=qa).returncode == 0
    proc = world.stop(qa)
    assert proc.returncode == 2 and PROVENANCE in proc.stderr, proc.stderr


def test_a_sibling_qas_observation_is_not_the_main_agents(world):
    """Parallel lanes: QA B's call sees QA A's new report first; A's report is still not the main agent's."""
    world.main_dispatches()
    qa_a, qa_b = world.dispatch(), world.dispatch()
    assert world.sh(f"cat > {Q} <<'EOF'\n{OWN}\nEOF").returncode == 0
    assert world.pre("Bash", {"command": "ls"}, agent=qa_b).returncode == 0
    assert world.stop(qa_a).returncode == 0


def test_a_report_no_observation_recorded_is_judged_as_on_the_base(world):
    (world.project / Q).write_text(FORGED + "\n")
    qa = world.dispatch()
    assert world.stop(qa).returncode == 0


def test_the_observation_writes_nothing_into_the_project(world):
    assert world.sh(f"cat > {Q} {HD}").returncode == 0
    before = sorted(p.relative_to(world.project) for p in world.project.rglob("*"))
    world.main_dispatches()
    assert sorted(p.relative_to(world.project) for p in world.project.rglob("*")) == before
    assert list((world.tmp / "state" / "report-provenance").glob("*.json"))


# -- the main agent's reads pass the whole PreToolUse launcher (they were refused at 3dad5f73) ---------
READS = {
    "py-stdout-write": f"python3 -c \"import sys; sys.stdout.write(open('{Q}').read())\"",
    "py-print-stderr": f"python3 -c \"import sys,json; print(json.load(open('{Q}')), file=sys.stderr)\"",
    "py-get-default": f"python3 -c \"import json; print(json.load(open('{Q}')).get('verdict', 'a'))\"",
    "py-read-write-tmp": f"python3 -c \"import json; d=json.load(open('{Q}')); open('/tmp/s.txt','w').write(d['qa']['status'])\"",
    "pipe-py-stdout": f"cat {Q} | python3 -c 'import sys; sys.stdout.write(sys.stdin.read())'",
    "jq-pipe-py": f"jq . {Q} | python3 -c 'import sys; print(sys.stdin.read(), file=sys.stderr)'",
    "node-stdout-write": f"node -e \"process.stdout.write(require('fs').readFileSync('{Q}'))\"",
    "xargs-grep-tmp": "ls docs/dev/qa-report-*.json | xargs grep -l pass > /tmp/list.txt",
    "find-xargs-jq": "find docs/dev -name 'qa-report-*.json' | xargs -n1 jq -c .qa > /tmp/all.txt",
    "cd-mktemp-copy": "cd $(mktemp -d) && cp {project}/docs/dev/qa-report-1.json .",
    "cd-tmpdir-echo": "cd \"$TMPDIR\" && echo x > qa-report-1.json",
}


@pytest.mark.parametrize("name", list(READS))
def test_the_main_agents_reads_pass_the_whole_launcher(world, name):
    (world.project / Q).write_text(OWN + "\n")
    (world.project / "docs" / "dev" / "qa-report-1.json").write_text(OWN + "\n")
    command = READS[name].replace("{project}", str(world.project))
    proc = world.pre("Bash", {"command": command}, hook=LAUNCH)
    assert proc.returncode == 0, proc.stderr


# -- the main agent's file tools on a QA or BA-QA report are refused at PreToolUse ---------------------
def _tool_input(tool: str, path: str) -> dict:
    if tool == "Write":
        return {"file_path": path, "content": FORGED}
    if tool == "Edit":
        return {"file_path": path, "old_string": "a", "new_string": "b"}
    if tool == "MultiEdit":
        return {"file_path": path, "edits": [{"old_string": "a", "new_string": "b"}]}
    return {"notebook_path": path, "new_source": "x"}


@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit", "NotebookEdit"])
@pytest.mark.parametrize("name", [N, f"ba-qa-report-{TASK}.json"])
def test_the_main_agents_file_tool_of_a_qa_or_ba_qa_report_is_refused(world, tool, name):
    proc = world.pre(tool, _tool_input(tool, str(world.project / "docs" / "dev" / name)))
    assert proc.returncode == 2, proc.stderr
    assert "gate-read" in proc.stderr, proc.stderr



# -- the forms the PreToolUse reading also refuses early, before the gate (passed at 3dad5f73) ---------
EARLY = {
    "heredoc-sort-o": f"sort -o {Q} {HD}",
    "heredoc-sed-w": f"sed -n 'w {Q}' {HD}",
    "sed-s-w": f"sed 's/a/b/w {Q}' /tmp/x",
    "heredoc-awk-print": f"awk '{{print > \"{Q}\"}}' {HD}",
    "heredoc-uniq": f"uniq - {Q} {HD}",
    "heredoc-brace-name": f"cat > docs/dev/{{qa,zz}}-report-{TASK}.json {HD}",
    "brace-dir-tee": f"echo x | tee docs/{{dev,zz}}/{N}",
    "openssl-out": f"openssl enc -in /tmp/x -out {Q}",
    "curl-O-after-cd": f"cd docs/dev && curl -O http://127.0.0.1/{N}",
    "curl-output-dir": f"curl --output-dir docs/dev -O http://127.0.0.1/{N}",
    "wget-P": f"wget -P docs/dev http://127.0.0.1/{N}",
    "node-cpSync": f"node -e \"require('fs').cpSync('/tmp/x','{Q}')\"",
    "python-argv": f"python3 -c \"import sys; open(sys.argv[1],'w').write('x')\" {Q}",
    "python-os-open": f"python3 -c \"import os; os.write(os.open('{Q}', os.O_WRONLY|os.O_CREAT), b'x')\"",
    "cd-pwd": f"cd $PWD/docs/dev && echo x > {N}",
}


@pytest.mark.parametrize("name", list(EARLY))
def test_the_forms_read_for_certain_are_refused_at_pretooluse(world, name):
    proc = world.pre("Bash", {"command": EARLY[name]}, hook=LAUNCH)
    assert proc.returncode == 2, proc.stderr
    assert "gate-read" in proc.stderr, proc.stderr


EARLY_PASSES = {
    "sort-o-tmp": f"sort -o /tmp/sorted.json {Q}",
    "sed-print": f"sed -n '/status/p' {Q}",
    "awk-print-tmp": f"awk '{{print > \"/tmp/x.txt\"}}' {Q}",
    "uniq-to-tmp": f"uniq {Q} /tmp/u.json",
    "openssl-to-tmp": f"openssl enc -in {Q} -out /tmp/q.json",
    "curl-O-tmp": f"cd /tmp && curl -O http://127.0.0.1/{N}",
    "wget-P-tmp": f"wget -P /tmp http://127.0.0.1/{N}",
    "node-cp-out": f"node -e \"require('fs').cpSync('{Q}','/tmp/q.json')\"",
    "python-argv-read": f"python3 -c \"import sys; print(open(sys.argv[1]).read())\" {Q}",
}


@pytest.mark.parametrize("name", list(EARLY_PASSES))
def test_the_same_writers_aimed_elsewhere_pass(world, name):
    proc = world.pre("Bash", {"command": EARLY_PASSES[name]}, hook=LAUNCH)
    assert proc.returncode == 0, proc.stderr
