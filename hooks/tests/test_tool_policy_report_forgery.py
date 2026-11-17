"""The main agent never writes a gate-read QA or dev report (AUDIT section 5, CD-6).

hooks/subagentstop-e2e-enforce.py (inside hooks/subagentstop-producer-gate.py) judges the
``e2e_enforcement.status`` of ``docs/dev/qa-report-*.json``; hooks/pretool-obligation-gate.py and
hooks/lib/obligation.py read the ``verdict`` of ``docs/dev/ba-qa-report-*.json`` and the status of
``docs/dev/dev-report-*.json`` (hooks/lib/dev_loop_checks.py, hooks/lib/dev_report_shard_patterns.py).
The derived write permission of hooks/pretool-tool-policy.py already refuses the main agent's write of
such a path once a dispatch of the session declares it; before that dispatch exists (or for a report
no dispatch declares) the orchestrator could forge one with a Bash heredoc and the gates would trust a
report the producer never wrote. The tool-policy now refuses every main-agent Bash write of one,
whatever the session's dispatch records say, the target read from the call's directory and every
``cd``. Subagents keep exactly the base behaviour. The main agent's Write tool of an undeclared report
stays as on the base (an existing test pins it; an owner decision).

Each case runs the real hook as a subprocess (as tests/test_tool_policy_derived_permission.py does);
the project lies outside /tmp and is never created; only paths are judged.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-tool-policy.py"
LAUNCH = ROOT / "hooks" / "pretool-launch.py"
PROJECT = Path("/nonexistent-cd6-report-forgery") / "proj"
TASK = "20261028-101010"
QA = f"docs/dev/qa-report-{TASK}.json"
BAQA = f"docs/dev/ba-qa-report-{TASK}.json"
DEV = f"docs/dev/dev-report-{TASK}.json"
BLOCK = "BLOCKED by tool-policy.v1: "
FORGED = '{"e2e_enforcement": {"status": "performed"}, "qa": {"status": "pass"}}'


class Session:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.sid = "sess-" + uuid.uuid4().hex[:8]
        self.transcript = root / f"{self.sid}.jsonl"
        self.subagents = root / self.sid / "subagents"
        self.subagents.mkdir(parents=True)
        self.transcript.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": "go"}}) + "\n")

    def dispatch(self, role: str, path: str, schema: str) -> str:
        doc = {"task_id": TASK, "role": role, "pipeline": "dev", "profile": "singular",
               "dispatched_at": "2026-10-28T10:10:10Z",
               "artifacts": [{"kind": "json", "path": path, "schema": schema, "identity": {"task_id": TASK}}]}
        prompt = f"You are {role}.\n<obligation v=\"1\">\n{json.dumps(doc)}\n</obligation>"
        call_id = "toolu_" + uuid.uuid4().hex[:20]
        with self.transcript.open("a") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": call_id, "name": "Agent",
                 "input": {"description": "d", "prompt": prompt, "subagent_type": role}}]}}) + "\n")
        agent_id = "a" + uuid.uuid4().hex[:16]
        (self.subagents / f"agent-{agent_id}.jsonl").write_text(
            json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
        (self.subagents / f"agent-{agent_id}.meta.json").write_text(
            json.dumps({"agentType": role, "toolUseId": call_id}))
        return agent_id

    def payload(self, tool: str, tool_input: dict, agent=None, cwd: Path = PROJECT) -> dict:
        data = {"session_id": self.sid, "transcript_path": str(self.transcript), "cwd": str(cwd),
                "hook_event_name": "PreToolUse", "permission_mode": "default", "tool_name": tool,
                "tool_input": tool_input, "tool_use_id": "toolu_" + uuid.uuid4().hex[:24]}
        if agent:
            data.update(agent_id=agent[0], agent_type=agent[1], subagent_type=agent[1])
        return data

    def env(self, tmp_path: Path) -> dict:
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
        env.update({"HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
                    "CLAUDE_STATE_DIR": str(tmp_path / "state"), "CLAUDE_PROJECT_DIR": str(PROJECT),
                    "PYTHONDONTWRITEBYTECODE": "1"})
        return env

    def run(self, tmp_path: Path, tool: str, tool_input: dict, agent=None, hook: Path = HOOK, cwd: Path = PROJECT):
        proc = subprocess.run([sys.executable, str(hook)], input=json.dumps(self.payload(tool, tool_input, agent, cwd)),
                              capture_output=True, text=True, cwd=str(tmp_path), env=self.env(tmp_path), timeout=60)
        assert not PROJECT.parent.exists(), "the policy check must not create the project"
        return proc


@pytest.fixture()
def session(tmp_path):
    return Session(tmp_path / "projects")


def _bash(command: str) -> dict:
    return {"command": command}


def _refused(proc) -> dict:
    assert proc.returncode == 2, (proc.returncode, proc.stderr)
    first = proc.stderr.splitlines()[0]
    assert first.startswith(BLOCK), proc.stderr
    denial = json.loads(first[len(BLOCK):])
    assert denial["role"] == "main"
    assert "gate-read" in denial["deny_reason"], denial
    return denial


# -- the forms the main agent's Bash must not write a report with ------------------------------------
HEREDOC = f"cat > {QA} <<'EOF'\n{FORGED}\nEOF"
REFUSED = {
    "heredoc-cat": HEREDOC,
    "heredoc-unquoted-delim": f"cat > {QA} <<EOF\n{FORGED}\nEOF",
    "heredoc-tee": f"tee {QA} >/dev/null <<'EOF'\n{FORGED}\nEOF",
    "echo-truncate": f"echo '{FORGED}' > {QA}",
    "echo-append": f"echo '{FORGED}' >> {QA}",
    "printf-clobber": f"printf '%s' x >| {QA}",
    "attached-redirect": f"echo x>{QA}",
    "fd-redirect": f"echo x 1>{QA}",
    "amp-redirect": f"echo x &>{QA}",
    "exec-fd": f"exec 3>{QA}",
    "tee": f"echo x | tee {QA}",
    "tee-append-second": f"echo x | tee -a /tmp/y {QA}",
    "cp": f"cp /tmp/x {QA}",
    "cp-target-directory": "cp -t docs/dev /tmp/qa-report-1.json",
    "cp-target-directory-long": "cp --target-directory=docs/dev /tmp/qa-report-1.json",
    "cp-into-dir": "cp /tmp/qa-report-1.json docs/dev/",
    "mv": f"mv /tmp/x {QA}",
    "mv-into-dir": "mv /tmp/dev-report-1.json docs/dev",
    "install": f"install -m 644 /tmp/x {QA}",
    "ln": f"ln -sf /tmp/x {QA}",
    "rsync": f"rsync /tmp/x {QA}",
    "sed-i": f"sed -i 's/fail/pass/' {QA}",
    "sed-i-long": f"sed --in-place=.bak 's/fail/pass/' {QA}",
    "dd": f"dd if=/tmp/x of={QA}",
    "truncate": f"truncate -s 0 {QA}",
    "curl-o": f"curl -sSo {QA} http://127.0.0.1/x",
    "ba-qa-report": f"echo '{{\"verdict\": \"pass\"}}' > {BAQA}",
    "dev-report": f"echo '{{\"dev\": {{\"status\": \"completed\"}}}}' > {DEV}",
    "dev-report-lane-shard": "echo x > docs/dev/dev-report-dev-20261028-101010-w1.json",
    "absolute": f"echo x > {PROJECT / QA}",
    "project-dir-var": f"echo x > \"$CLAUDE_PROJECT_DIR/{QA}\"",
    "dotdot": f"echo x > docs/specs/../dev/qa-report-{TASK}.json",
    "dot-slash": f"echo x > ./docs//dev/./qa-report-{TASK}.json",
    "worktree": f"echo x > /srv/wt/feature/{QA}",
    "cd-then-heredoc": f"cd docs/dev && cat > qa-report-{TASK}.json <<'EOF'\n{FORGED}\nEOF",
    "cd-chain": f"cd docs && cd dev && echo x > qa-report-{TASK}.json",
    "cd-absolute": f"cd {PROJECT}/docs/dev; echo x > qa-report-{TASK}.json",
    "cd-subshell": f"(cd docs/dev && echo x > qa-report-{TASK}.json)",
    "pushd": f"pushd docs/dev >/dev/null && echo x > qa-report-{TASK}.json",
    "cd-computed": f"cd \"$D\" && echo x > qa-report-{TASK}.json",
    "cd-dash": f"cd - && echo x > qa-report-{TASK}.json",
    "computed-dir": f"echo x > \"$D/qa-report-{TASK}.json\"",
    "quoted-pieces": f"echo x > \"docs/dev/\"'qa-report-{TASK}'.json",
    "backslash-escaped": f"echo x > docs/dev/qa\\-report-{TASK}.json",
    "link-then-write": f"ln -s docs/dev /tmp/d9 && echo x > /tmp/d9/qa-report-{TASK}.json",
    "xargs-cp": f"echo {QA} | xargs -I{{}} cp /tmp/x {{}}",
    "env-wrapper": f"env A=1 cp /tmp/x {QA}",
    "command-wrapper": f"command tee {QA} < /tmp/x",
    "exec-wrapper": f"exec cp /tmp/x {QA}",
    "nice-wrapper": f"nice -n 5 cp /tmp/x {QA}",
    "timeout-wrapper": f"timeout 5 cp /tmp/x {QA}",
    "setsid-wrapper": f"setsid cp /tmp/x {QA}",
    "nohup-wrapper": f"nohup cp /tmp/x {QA}",
    "bash-c": f"bash -c 'echo x > {QA}'",
    "sh-c-cd": f"sh -c 'cd docs/dev && cp /tmp/x qa-report-{TASK}.json'",
    "eval": f"eval 'echo x > {QA}'",
    "procsub": f"echo x > >(tee {QA})",
    "cmdsub": f"echo $(cp /tmp/x {QA})",
    "python-c": f"python3 -c \"open('{QA}', 'w').write('{{}}')\"",
    "python-c-mode-kw": f"python3 -c \"import json; json.dump({{}}, open('{QA}', mode='w'))\"",
    "python-pathlib": f"python3 -c \"import pathlib; pathlib.Path('{QA}').write_text('x')\"",
    "python-shutil": f"python3 -c \"import shutil; shutil.copy('/tmp/x', '{QA}')\"",
    "python-heredoc": f"python3 - <<'EOF'\nopen('{QA}', 'w').write('x')\nEOF",
    "python-piped": f"echo \"open('{QA}', 'w').write('x')\" | python3",
    "python-cd": f"cd docs/dev && python3 -c \"open('qa-report-{TASK}.json', 'w').write('x')\"",
    "node-e": f"node -e \"require('fs').writeFileSync('{QA}', 'x')\"",
    "perl-i": f"perl -i -pe 's/fail/pass/' {QA}",
    "perl-open": f"perl -e 'open(my $f, \">\", \"{QA}\"); print $f 1'",
    "ruby-e": f"ruby -e \"File.write('{QA}', 'x')\"",
}


@pytest.mark.parametrize("command", list(REFUSED.values()), ids=list(REFUSED))
def test_the_main_agents_bash_write_of_a_gate_read_report_is_refused(tmp_path, session, command):
    _refused(session.run(tmp_path, "Bash", _bash(command)))


def test_the_heredoc_forgery_is_refused_by_the_whole_pretooluse_launcher(tmp_path, session):
    """The red evidence's shape: the registered Python PreToolUse launcher (write gate included)."""
    proc = session.run(tmp_path, "Bash", _bash(HEREDOC), hook=LAUNCH)
    assert proc.returncode == 2, proc.stderr
    assert "gate-read" in proc.stderr


def test_a_symlinked_directory_is_read_through(tmp_path, session):
    """A link that already points at a docs/dev directory is followed."""
    real = tmp_path / "other" / "docs" / "dev"
    real.mkdir(parents=True)
    link = tmp_path / "lnk"
    link.symlink_to(real)
    _refused(session.run(tmp_path, "Bash", _bash(f"echo x > {link}/qa-report-{TASK}.json")))


# -- what the main agent still does -------------------------------------------------------------------
PASSES = {
    "cat": f"cat {QA}",
    "jq": f"jq -r '.e2e_enforcement.status' {QA}",
    "grep": f"grep -c pass {QA} docs/dev/dev-report-*.json",
    "python-read": f"python3 -c \"import json; json.load(open('{QA}'))\"",
    "python-read-print": f"python3 -c \"import json; print(json.dumps(json.load(open('{QA}'))['qa'], indent=2))\"",
    "python-read-pipe": f"cat {QA} | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"qa\"][\"status\"])'",
    "ls": "ls -la docs/dev/",
    "diff-to-tmp": f"diff {QA} /tmp/old.json > /tmp/report.diff",
    "copy-out": f"cp {QA} /tmp/qa-copy.json",
    "jq-out": f"jq . {QA} > /tmp/pretty.json",
    "notes-md": "echo x > docs/dev/notes.md",
    "context": f"echo '{{}}' > docs/dev/context-{TASK}.json",
    "do-report": f"echo '{{}}' > docs/dev/do-report-{TASK}.json",
    "commit-qa-transcript": f"echo x > docs/dev/commit-qa-report-{TASK}.md",
    "report-md": f"echo x > docs/dev/qa-report-{TASK}.md",
    "tmp-json": "echo '{}' > /tmp/qa.json",
    "tmp-report-name": f"echo '{{}}' > /tmp/x/qa-report-{TASK}.json",
    "cp-into-docs-dev": "cp /tmp/notes.md docs/dev/",
    "cd-elsewhere": f"cd /tmp && echo x > qa-report-{TASK}.json",
    "aggregator-script": f"python3 scripts/aggregate-dev-report.py --task-id {TASK}",
    "lint-script": f"python3 scripts/qa-report-stale-iter-lint.py {QA}",
    "heredoc-to-scratch": f"cat > /tmp/notes.md <<'EOF'\nsee {QA}, verdict pass\nEOF",
    "git-commit-message": f"git commit -m 'qa: {QA} written by qa'",
}


@pytest.mark.parametrize("command", list(PASSES.values()), ids=list(PASSES))
def test_the_main_agent_still_reads_reports_and_writes_other_files(tmp_path, session, command):
    proc = session.run(tmp_path, "Bash", _bash(command))
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("path", ["docs/dev/notes.md", f"docs/dev/context-{TASK}.json",
                                  f"docs/dev/do-report-{TASK}.json", "/tmp/qa.json"])
def test_the_main_agents_write_tool_of_another_file_passes(tmp_path, session, path):
    target = path if path.startswith("/") else str(PROJECT / path)
    assert session.run(tmp_path, "Write", {"file_path": target, "content": "{}"}).returncode == 0


# -- subagents keep the base behaviour ---------------------------------------------------------------
@pytest.mark.parametrize("tool", ["Write", "Bash"])
def test_the_qa_writes_its_own_report(tmp_path, session, tool):
    qa = session.dispatch("qa", QA, "qa-report.v2")
    tool_input = ({"file_path": str(PROJECT / QA), "content": FORGED} if tool == "Write" else _bash(HEREDOC))
    proc = session.run(tmp_path, tool, tool_input, (qa, "qa"))
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("tool", ["Write", "Bash"])
def test_the_dev_writes_its_own_report(tmp_path, session, tool):
    dev = session.dispatch("dev", DEV, "dev-report.v2")
    tool_input = ({"file_path": str(PROJECT / DEV), "content": "{}"} if tool == "Write"
                  else _bash(f"cat > {DEV} <<'EOF'\n{{}}\nEOF"))
    proc = session.run(tmp_path, tool, tool_input, (dev, "dev"))
    assert proc.returncode == 0, proc.stderr


def test_a_declared_report_keeps_its_declaring_dispatchs_refusal_for_the_main_agent(tmp_path, session):
    """The derived permission still speaks first, with its own text, on a declared report."""
    session.dispatch("qa", QA, "qa-report.v2")
    proc = session.run(tmp_path, "Bash", _bash(HEREDOC))
    assert proc.returncode == 2
    assert "only qa writes this artifact (D8)" in proc.stderr.splitlines()[0]
