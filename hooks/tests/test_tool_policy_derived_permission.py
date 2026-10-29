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

import importlib.util
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


def test_dispatch_records_are_ordered_by_their_offsets_and_no_line_is_numbered(tmp_path, monkeypatch):
    # Only the order of dispatches and span openers decides which command's template applies, so the
    # long-transcript reader compares offsets and never counts lines (P1b latency lane).
    s = Session(tmp_path / "projects")
    s.command("do")
    s.dispatch("Describe the toy package.")
    s.command("dev")
    s.dispatch("You are the dev subagent.\n" + _block(_obligation("dev", "singular", REPORT)))
    spec = importlib.util.spec_from_file_location("tool_policy_offsets", HOOK)
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    from lib import command_span

    def numbered(self, pos):
        raise AssertionError("a line was numbered")

    monkeypatch.setattr(command_span._Lines, "_number", numbered)
    data = s.transcript.read_bytes()
    starts = [0] + [i + 1 for i, b in enumerate(data) if b == 10][:-1]
    calls = policy._dispatch_calls(data)
    assert [c.line for c in calls] == [starts[1], starts[3]]
    assert policy._span_commands(data, calls[-1].line) == [(starts[0], "do"), (starts[2], "dev")]
    assert policy._span_commands(data, calls[0].line) == [(starts[0], "do")]


# -- a target no template can declare: no transcript read (review item 2) ----------------------------

def _policy(name="tool_policy_shapes"):
    spec = importlib.util.spec_from_file_location(name, HOOK)
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    policy._bootstrap_security()
    return policy


def _payload(s: "Session", tool: str, tool_input: dict, agent: tuple | None = None) -> dict:
    data = {"session_id": s.sid, "transcript_path": str(s.transcript), "cwd": str(PROJECT),
            "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
    if agent:
        data.update(agent_id=agent[0], agent_type=agent[1], subagent_type=agent[1])
    return data


def test_a_write_no_template_can_declare_reads_no_transcript(tmp_path, cycle, monkeypatch):
    # The session's dispatch records grow with the session; a target that no path of the current
    # command files' templates (nor the producer question) can name costs the same in any session.
    policy = _policy()
    from lib import command_span

    read = []
    real = command_span._read
    monkeypatch.setattr(command_span, "_read", lambda path: read.append(path) or real(path))
    undeclarable = [("Write", _write("toy/__init__.py")), ("Edit", {"file_path": str(PROJECT / "toy/util.py")}),
                    ("Bash", {"command": "echo a > file"}), ("Bash", {"command": "printf x > toy/x.txt 2>&1"})]
    for tool, tool_input in undeclarable:
        targets = policy._extract_targets(tool, tool_input)
        assert policy._check_declared_writes("dev", tool, targets, _payload(cycle, tool, tool_input)) == set()
    assert read == [], "a write no template can declare read the session transcript"
    # A target a template can declare keeps the check, and its read.
    with pytest.raises(SystemExit) as stop:
        policy._check_declared_writes("dev", "Write", [str(PROJECT / CONTEXT)],
                                      _payload(cycle, "Write", _write(CONTEXT), (cycle.dev, "dev")))
    assert stop.value.code == 2 and read == [cycle.transcript]


def test_the_hook_never_opens_the_transcript_for_such_a_write(tmp_path):
    # Process-level: the session transcript is a FIFO nobody writes, so opening it would block.
    s = Session(tmp_path / "projects")
    s.transcript.unlink()
    os.mkfifo(s.transcript)
    for tool, tool_input in (("Write", _write("toy/__init__.py")), ("Bash", {"command": "echo a > file"})):
        assert s.run(tmp_path, tool, tool_input, None).returncode == 0


def test_the_declarable_shapes_are_read_from_the_command_files(tmp_path, monkeypatch):
    policy = _policy()
    from lib import stop_contract

    commands = tmp_path / "commands"
    commands.mkdir()
    monkeypatch.setattr(stop_contract, "COMMANDS_DIR", commands)
    forms = lambda target: policy._target_forms(target, {"cwd": str(PROJECT)})  # noqa: E731
    # No command file: only the producer question's shape (G2's rule) remains.
    shapes = policy._declarable_shapes()
    assert policy._could_be_declared(shapes, forms("docs/dev/producer-question-x-ba.json"))
    assert not policy._could_be_declared(shapes, forms("out/1.weird"))
    (commands / "x.md").write_text('```\n{"artifacts": [{"kind": "markdown", "path": "out/<task_id>.weird"},\n'
                                   ' {"kind": "spec_views", "path": "trees/{x.y}/leaf"}]}\n```\n')
    shapes = policy._declarable_shapes()
    for declarable in ("out/1.weird", "a/b/2.weird/child", "trees/z/leaf", "leaf/below.py"):
        assert policy._could_be_declared(shapes, forms(declarable)), declarable
    for undeclarable in ("out/1.weirdo", "src/leafy.py", "a.md"):
        assert not policy._could_be_declared(shapes, forms(undeclarable)), undeclarable
    # A command file that cannot be read: any target may be declared, so every write keeps the check.
    (commands / "broken.md").mkdir()
    assert policy._could_be_declared(policy._declarable_shapes(), forms("src/a.py"))


@pytest.mark.parametrize("value", ["20261028-101010", "a/b", "x/../../y", "/../../../z/w", "q/", "."])
def test_every_path_a_current_template_declares_is_declarable(value):
    # Whatever a dispatch binds a placeholder to ("/" and ".." included), the path it declares is one
    # the filter keeps the check for, in place and as the directory above a target.
    policy = _policy()
    shapes = policy._declarable_shapes()
    seen = 0
    for file in sorted((ROOT / "commands").glob("*.md")):
        for raw in policy._TEMPLATE_PATH_RE.findall(file.read_text(encoding="utf-8")):
            path = policy._SHAPE_PLACEHOLDER_RE.sub(value, json.loads(f'"{raw}"'))
            parts = policy._parts(path)
            if not parts or ".." in parts or path.startswith("/"):
                continue  # a path tool-policy never takes as declared
            seen += 1
            for target in ("/".join(parts), "/".join(parts) + "/below.txt", "nested/" + "/".join(parts)):
                assert policy._could_be_declared(shapes, policy._target_forms(target, {"cwd": str(PROJECT)})), \
                    (file.name, raw, value, target)
    assert seen


def test_a_subagents_own_declared_write_is_decided_by_its_own_dispatch(tmp_path, cycle, monkeypatch):
    # Whatever another dispatch declares, a path the caller's own dispatch declares is its own: that
    # dispatch's declarations decide it, not every dispatch's of a long session.
    policy = _policy()
    seen = []
    real = policy._declarations
    monkeypatch.setattr(policy, "_declarations", lambda data, calls: seen.append([c.id for c in calls]) or real(data, calls))
    ba_call = json.loads((cycle.subagents / f"agent-{cycle.ba}.meta.json").read_text())["toolUseId"]
    dev_call = json.loads((cycle.subagents / f"agent-{cycle.dev}.meta.json").read_text())["toolUseId"]
    own = policy._check_declared_writes("ba", "Write", [str(PROJECT / CONTEXT)],
                                        _payload(cycle, "Write", _write(CONTEXT), (cycle.ba, "ba")))
    assert own == {str(PROJECT / CONTEXT)} and seen == [[ba_call]]
    # Another caller's write of it still reads every dispatch, and is refused as before.
    seen.clear()
    with pytest.raises(SystemExit) as stop:
        policy._check_declared_writes("dev", "Write", [str(PROJECT / CONTEXT)],
                                      _payload(cycle, "Write", _write(CONTEXT), (cycle.dev, "dev")))
    assert stop.value.code == 2 and seen[0] == [dev_call] and len(seen[-1]) == 3
