"""The write permission of a declared artifact, derived from the session's dispatch records (P1b E3).

hooks/pretool-tool-policy.py runs it before the role rows, for every caller, the main agent
included: a path a dispatch of the session declares (its obligation's artifacts, the producer
question that obligation names, what the template it was dispatched from declares in the current
command files) is written by that dispatch only; any other caller's write of it exits 2 naming
the path and the declaring obligation's role, also when a surviving prefix (dev's '*',
general-purpose's '*/docs/dev/*') allows it; an undeclared path keeps the rows.

Each case runs the real hook as a subprocess on a transcript store shaped as the CLI keeps it:
the session's Agent calls, each child's first record (its prompt) and the meta naming its call.
The project lies outside /tmp and /var/tmp (the scratch rule denies every role there) and is
never created; only paths are judged.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-tool-policy.py"
PROJECT = Path("/nonexistent-p1b-derived-permission") / "proj"
TASK = "20261028-101010"
BLOCK = "BLOCKED by tool-policy.v1: "


def _obligation(role: str, profile: str, *paths: str, task: str = TASK) -> dict:
    return {"task_id": task, "role": role, "pipeline": "dev", "profile": profile,
            "dispatched_at": "2026-10-28T10:10:10Z",
            "artifacts": [{"kind": "markdown", "path": p, "identity_anchor": task} for p in paths]}


def _block(doc: dict) -> str:
    return f'<obligation v="1">\n{json.dumps(doc)}\n</obligation>'


class Session:
    def __init__(self, root: Path):
        self.root = root
        self.sid = "sess-" + uuid.uuid4().hex[:8]
        self.transcript = root / f"{self.sid}.jsonl"
        self.subagents = root / self.sid / "subagents"
        self.subagents.mkdir(parents=True)
        self.transcript.write_text("")

    def _append(self, record: dict) -> None:
        with self.transcript.open("a") as fh:
            fh.write(json.dumps(record) + "\n")

    def command(self, name: str) -> None:
        """A human-typed slash command record (it opens a span)."""
        self._append({"type": "user", "message": {"role": "user", "content":
                      f"<command-message>{name} is running…</command-message>\n"
                      f"<command-name>/{name}</command-name>\n<command-args>x</command-args>"}})

    def dispatch(self, prompt: str, subagent_type: str | None = None, meta: bool = True) -> str:
        """An Agent call and the child the CLI starts for it; returns the child's agent id."""
        call_id = "toolu_" + uuid.uuid4().hex[:20]
        tool_input = {"description": "d", "prompt": prompt}
        if subagent_type:
            tool_input["subagent_type"] = subagent_type
        self._append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": call_id, "name": "Agent", "input": tool_input}]}})
        agent_id = "a" + uuid.uuid4().hex[:16]
        (self.subagents / f"agent-{agent_id}.jsonl").write_text(
            json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
        if meta:
            (self.subagents / f"agent-{agent_id}.meta.json").write_text(
                json.dumps({"agentType": subagent_type or "general-purpose", "toolUseId": call_id}))
        return agent_id

    def run(self, tmp_path: Path, tool: str, tool_input: dict, agent: tuple | None = None):
        payload = {"session_id": self.sid, "transcript_path": str(self.transcript), "cwd": str(PROJECT),
                   "hook_event_name": "PreToolUse", "permission_mode": "default", "tool_name": tool,
                   "tool_input": tool_input, "tool_use_id": "toolu_" + uuid.uuid4().hex[:24]}
        if agent:
            # agent_id/agent_type as the CLI sends them; subagent_type is the label
            # resolve_agent_type reads first (no registry exists here).
            payload.update(agent_id=agent[0], agent_type=agent[1], subagent_type=agent[1])
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
        env.update({"HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
                    "CLAUDE_STATE_DIR": str(tmp_path / "state"), "CLAUDE_PROJECT_DIR": str(PROJECT),
                    "PYTHONDONTWRITEBYTECODE": "1"})
        proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                              text=True, cwd=str(tmp_path), env=env, timeout=60)
        assert not PROJECT.parent.exists(), "the policy check must not create the project"
        return proc


def _write(path: str) -> dict:
    return {"file_path": str(PROJECT / path), "content": "x"}


def _denial(proc) -> dict:
    assert proc.returncode == 2, proc.stderr
    first = proc.stderr.splitlines()[0]
    assert first.startswith(BLOCK), proc.stderr
    return json.loads(first[len(BLOCK):])


CONTEXT = f"docs/dev/context-{TASK}.json"
REPORT = f"docs/dev/dev-report-{TASK}.json"


@pytest.fixture()
def cycle(tmp_path):
    """A /dev cycle's BA and dev dispatches, plus an ad hoc general-purpose agent."""
    s = Session(tmp_path / "projects")
    s.command("dev")
    s.ba = s.dispatch("You are the BA subagent.\n" + _block(_obligation("ba", "singular", CONTEXT)))
    s.dev = s.dispatch("You are the dev subagent.\n" + _block(_obligation("dev", "singular", REPORT)))
    s.gp = s.dispatch("Describe the toy package. DO NOT modify files.", "general-purpose")
    return s


def test_the_declaring_dispatch_writes_its_artifact_no_row_names(tmp_path, cycle):
    proc = cycle.run(tmp_path, "Write", _write(CONTEXT), (cycle.ba, "ba"))
    assert proc.returncode == 0, proc.stderr
    # The rows alone refuse it: the same write with no dispatch record.
    bare = Session(tmp_path / "bare")
    assert _denial(bare.run(tmp_path, "Write", _write(CONTEXT), (cycle.ba, "ba")))["deny_reason"].endswith(
        "not in allowed_write_path_prefixes")


@pytest.mark.parametrize("caller", ["dev", "general-purpose", "main"])
@pytest.mark.parametrize("tool", ["Write", "Edit", "Bash"])
def test_any_other_caller_is_denied_whatever_a_prefix_allows(tmp_path, cycle, caller, tool):
    agent = {"dev": (cycle.dev, "dev"), "general-purpose": (cycle.gp, "general-purpose"), "main": None}[caller]
    tool_input = (_write(CONTEXT) if tool == "Write"
                  else {"file_path": str(PROJECT / CONTEXT), "old_string": "a", "new_string": "b"}
                  if tool == "Edit" else {"command": f"printf x > {CONTEXT}"})
    denial = _denial(cycle.run(tmp_path, tool, tool_input, agent))
    target = str(PROJECT / CONTEXT) if tool != "Bash" else CONTEXT
    assert denial == {"role": "main" if caller == "main" else caller,
                      "tool": "Write" if tool == "Bash" else tool, "target": target,
                      "deny_reason": f"write target {target} is declared by the obligation of the ba "
                                     f"dispatch for task {TASK}; only that dispatch writes it"}


def test_the_denial_offers_no_workaround(tmp_path, cycle):
    proc = cycle.run(tmp_path, "Bash", {"command": f"printf x > {CONTEXT}"}, (cycle.dev, "dev"))
    _denial(proc)
    assert len(proc.stderr.strip().splitlines()) == 1, proc.stderr


def test_undeclared_paths_keep_the_rows(tmp_path, cycle):
    assert cycle.run(tmp_path, "Write", _write("toy/__init__.py"), (cycle.dev, "dev")).returncode == 0
    assert cycle.run(tmp_path, "Write", _write("docs/dev/notes.md"), None).returncode == 0
    denial = _denial(cycle.run(tmp_path, "Write", _write("toy/__init__.py"), (cycle.ba, "ba")))
    assert denial["deny_reason"].endswith("not in allowed_write_path_prefixes")


def test_the_role_denials_still_apply_to_a_declared_path(tmp_path):
    s = Session(tmp_path / "projects")
    declared = f"tests/{TASK}.md"  # QA's rows deny /tests/
    qa = s.dispatch("You are QA.\n" + _block(_obligation("qa", "final_verification", declared)), "qa")
    denial = _denial(s.run(tmp_path, "Write", _write(declared), (qa, "qa")))
    assert denial["deny_reason"].endswith("matches denied_write_path_prefixes")


def test_the_producer_question_its_obligation_names(tmp_path, cycle):
    question = f"docs/dev/producer-question-{TASK}-ba.json"
    assert cycle.run(tmp_path, "Write", _write(question), (cycle.ba, "ba")).returncode == 0
    assert _denial(cycle.run(tmp_path, "Write", _write(question), (cycle.dev, "dev")))["deny_reason"].startswith(
        f"write target {PROJECT / question} is declared by the obligation of the ba dispatch")
    # dev's question is the dev dispatch's, not BA's.
    theirs = f"docs/dev/producer-question-{TASK}-dev.json"
    assert "of the dev dispatch" in _denial(cycle.run(tmp_path, "Write", _write(theirs), (cycle.ba, "ba")))[
        "deny_reason"]


def test_a_declared_directory_covers_what_lies_beneath_it(tmp_path):
    s = Session(tmp_path / "projects")
    views = "docs/dev/specs/spec-x/views"
    doc = {"task_id": TASK, "role": "spec", "pipeline": "spec", "profile": "singular",
           "dispatched_at": "2026-10-28T10:10:10Z",
           "artifacts": [{"kind": "spec_views", "path": views, "monolith": "docs/dev/specs/spec-x.md"}]}
    spec = s.dispatch("Split the spec.\n" + _block(doc), "spec")
    assert s.run(tmp_path, "Write", _write(f"{views}/ba.md"), (spec, "spec")).returncode == 0
    assert "of the spec dispatch" in _denial(s.run(tmp_path, "Write", _write(f"{views}/ba.md"), None))[
        "deny_reason"]
    assert s.run(tmp_path, "Write", _write("docs/dev/specs/spec-x.md"), None).returncode == 0


def test_a_caller_whose_dispatch_cannot_be_read_owns_nothing(tmp_path, cycle):
    stray = "a" + uuid.uuid4().hex[:16]  # no transcript, no meta
    assert _denial(cycle.run(tmp_path, "Write", _write(CONTEXT), (stray, "ba")))["role"] == "ba"
    # Without the meta the child's own first record still names its call.
    s = Session(tmp_path / "nometa")
    ba = s.dispatch("You are the BA subagent.\n" + _block(_obligation("ba", "singular", CONTEXT)), meta=False)
    assert s.run(tmp_path, "Write", _write(CONTEXT), (ba, "ba")).returncode == 0


def test_a_meta_naming_another_call_is_not_believed(tmp_path, cycle):
    meta = cycle.subagents / f"agent-{cycle.dev}.meta.json"
    ba_call = json.loads((cycle.subagents / f"agent-{cycle.ba}.meta.json").read_text())["toolUseId"]
    meta.write_text(json.dumps({"toolUseId": ba_call}))
    _denial(cycle.run(tmp_path, "Write", _write(CONTEXT), (cycle.dev, "dev")))


def _template_prompt() -> tuple[str, str]:
    """The current commands/dev.md template whose obligation declares the BA context,
    bound to TASK, with its obligation block removed: a dispatch that carries none."""
    text = (ROOT / "commands" / "dev.md").read_text()
    for body in re.findall(r"^[ \t]*```[^\n]*\n(.*?)^[ \t]*```", text, re.M | re.S):
        block = re.search(r'<obligation v="1">\s*(.*?)\s*</obligation>', body, re.S)
        try:
            doc = json.loads(block.group(1)) if block else None
        except ValueError:
            continue
        if doc and doc.get("role") == "ba":
            path = next(a["path"] for a in doc["artifacts"] if a["path"].startswith("docs/dev/context-"))
            bare = body[:block.start()] + body[block.end():]
            return bare.replace("<timestamp>", TASK), path.replace("<timestamp>", TASK)
    raise AssertionError("commands/dev.md declares no BA context in a literal obligation block")


def test_a_dispatch_carrying_none_gets_what_its_current_template_declares(tmp_path):
    prompt, context = _template_prompt()
    s = Session(tmp_path / "projects")
    s.command("dev")
    # The template names no subagent_type: it dispatches the role it declares.
    ba = s.dispatch(prompt, "ba")
    dev = s.dispatch("You are the dev subagent.\n" + _block(_obligation("dev", "singular", REPORT)))
    assert s.run(tmp_path, "Write", _write(context), (ba, "ba")).returncode == 0
    assert "of the ba dispatch" in _denial(s.run(tmp_path, "Write", _write(context), (dev, "dev")))[
        "deny_reason"]
    # The same prompt in a span of a command with no such template declares nothing.
    other = Session(tmp_path / "other")
    other.command("do")
    ba = other.dispatch(prompt)
    assert other.run(tmp_path, "Write", _write(context), (ba, "general-purpose")).returncode == 0
    assert other.run(tmp_path, "Write", _write(context), None).returncode == 0
