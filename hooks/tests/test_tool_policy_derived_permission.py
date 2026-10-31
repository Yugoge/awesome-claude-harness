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

    def refused(self, prompt: str, subagent_type: str | None = None) -> None:
        """An Agent call a PreToolUse hook refused: its record and its error result; the CLI started no
        child, so it keeps no subagent files for it."""
        call_id = "toolu_" + uuid.uuid4().hex[:20]
        tool_input = {"description": "d", "prompt": prompt}
        if subagent_type:
            tool_input["subagent_type"] = subagent_type
        self._append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": call_id, "name": "Agent", "input": tool_input}]}})
        self._append({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call_id, "is_error": True,
             "content": "PreToolUse:Agent hook error: refused"}]}})

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
    record = policy._Record(s.transcript)
    try:
        calls = policy._dispatch_calls(record)
        assert [c.line for c in calls] == [starts[1], starts[3]]
        assert record.command_before(calls[0].line) == "do"
        assert record.command_before(calls[-1].line) == "dev"
    finally:
        record.close()


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
    read = []
    real = policy._Record
    monkeypatch.setattr(policy, "_Record", lambda path: read.append(path) or real(path))
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
    monkeypatch.setattr(policy, "_declarations",
                        lambda record, calls, targets=None: seen.append([c.id for c in calls]) or real(record, calls, targets))
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


# -- a declared-path write in a long session (review item 2, round 3) --------------------------------
#
# The oracle below is the reading the hook made before it read the transcript in pieces: the whole file
# in memory, every "Agent"/"Task" line decoded, every user record scanned for span openers, every
# dispatch's template read. The hook must decide every write as it does.

def _oracle_calls(data: bytes) -> list:
    from lib import command_span

    calls = []
    for begin, end in command_span._Lines(data).offsets((b'"Agent"', b'"Task"')):
        for block in command_span._blocks(command_span._decode(data[begin:end])):
            if (block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task")
                    and isinstance(block.get("input"), dict)):
                calls.append(command_span.Call(id=block.get("id") or "", name=block["name"], input=block["input"],
                                               line=begin, result_line=0, ok=False))
    return calls


def _oracle_openers(data: bytes) -> list:
    from lib import command_span, stop_contract

    commands, openers = stop_contract.harness_commands(), []
    for begin, end in command_span._Lines(data).offsets(command_span._USER_RECORD, unless=command_span._RESULT_BLOCK):
        record = command_span._decode(data[begin:end])
        opener = stop_contract.span_opener(record, commands) if record else None
        if opener:
            openers.append((begin, opener[0]))
    return openers


def _oracle(policy, data: bytes, calls: list) -> list:
    """(parts, role, task, id) of every path the dispatches declare, read as the hook read them before."""
    from lib import dispatch_template, obligation

    openers, out = _oracle_openers(data), []
    for call in calls:
        prompt = call.input.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            continue
        subagent_type = call.input.get("subagent_type") or "general-purpose"
        parsed = obligation.parse_obligation(prompt)
        own = parsed.obligation if isinstance(parsed, obligation.ParsedObligation) else None
        paths, role, task_id = [], subagent_type, None
        if own is not None:
            role, task_id = own.get("role"), own.get("task_id")
            paths += policy._declared_paths(own)
            template = dispatch_template.template_obligation(own.get("pipeline"), subagent_type, prompt)
            if template and all(template.get(k) == own.get(k) for k in ("role", "profile")):
                paths += policy._declared_paths(template)
            if role in policy._question_roles() and isinstance(task_id, str) and task_id:
                paths.append(policy._QUESTION_PATH.format(task_id=task_id, role=role))
        else:
            command = next((name for offset, name in reversed(openers) if offset < call.line), None)
            template = dispatch_template.template_obligation(command, subagent_type, prompt) if command else None
            if template:
                role, task_id = template.get("role") or role, template.get("task_id")
                paths += policy._declared_paths(template)
        for path in dict.fromkeys(paths):
            parts = policy._parts(path)
            if parts and ".." not in parts and not path.startswith("/"):
                out.append((parts, role, task_id, call.id))
    return out


def _long_session(root: Path, rounds: int = 6, spaced: bool = True, back: bool = True) -> "Session":
    """Commands, plain prompts, tool results that quote commands and paths, dispatches with and without
    an obligation (the current /dev BA template carrying none among them, and with ``back`` one whose
    value "x/../note" makes its ticket docs/dev/note.md), a control command: the shapes a long
    session's record has, in the CLI's compact spelling or Python's spaced one."""
    prompt, _context = _template_prompt()
    s = Session(root)
    dump = (lambda r: json.dumps(r)) if spaced else (lambda r: json.dumps(r, separators=(",", ":")))
    s._append = lambda record: s.transcript.open("a").write(dump(record) + "\n")
    for k in range(rounds):
        task = f"20261028-1{k:05d}"
        s.command(["dev", "do", "allow", "close"][k % 4])
        s._append({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"toolu_r{k}", "content": "<command-name>/dev</command-name>"}]}})
        s._append({"type": "user", "message": {"role": "user", "content": "please also check docs/dev/ for /dev"}})
        s.dispatch("You are the BA subagent.\n" + _block(_obligation("ba", "singular", f"docs/dev/context-{task}.json",
                                                                     task=task)), "ba")
        s.dispatch(prompt.replace(TASK, task), "ba")
        if back and k == 0:
            s.dispatch(prompt.replace(TASK, "x/../note"), "ba")
        s.dispatch("You are the dev subagent.\n" + _block(_obligation("dev", "singular", f"src/mod{k}.py",
                                                                      f"docs/dev/notes-{k}", task=task)), "dev")
        s.dispatch("Describe the toy package.", "general-purpose")
    return s


def _decision(policy, s, tool, tool_input, agent=None):
    targets = policy._extract_targets(tool, tool_input)
    try:
        return ("own", sorted(policy._check_declared_writes(agent[1] if agent else None, tool, targets,
                                                            _payload(s, tool, tool_input, agent))))
    except SystemExit as stop:
        return ("exit", stop.code)


def _oracle_decision(policy, s, tool, tool_input, agent=None):
    """What the hook decided before, from the oracle's reading of the same record."""
    data = s.transcript.read_bytes()
    payload = _payload(s, tool, tool_input, agent)
    writes = policy._write_targets(tool, policy._extract_targets(tool, tool_input))
    shapes = policy._declarable_shapes()
    if not writes or not any(policy._could_be_declared(shapes, policy._target_forms(t, payload)) for t in writes):
        return ("own", [])
    calls = _oracle_calls(data)
    if not calls:
        return ("own", [])
    mine, own = None, set()
    if payload.get("agent_id"):
        mine = policy._caller_dispatches(payload, policy._session_transcript(payload), calls)
        declared = _oracle(policy, data, [c for c in calls if c.id in mine]) if mine else []
        own = {t for t in writes if any(policy._covers(d[0], f) for f in policy._target_forms(t, payload)
                                       for d in declared)}
    declarations = _oracle(policy, data, calls)
    for t in [t for t in writes if t not in own]:
        covering = [d for d in declarations if any(policy._covers(d[0], f) for f in policy._target_forms(t, payload))]
        if not covering:
            continue
        if mine is None:
            mine = policy._caller_dispatches(payload, policy._session_transcript(payload), calls)
        if any(d[3] in mine for d in covering):
            own.add(t)
            continue
        return ("exit", 2)
    return ("own", sorted(own))


@pytest.mark.parametrize("spaced", [True, False])
@pytest.mark.parametrize("piece", [64, 997, 1 << 22])
def test_every_declared_path_write_is_decided_as_the_whole_file_reading_decided_it(tmp_path, monkeypatch, spaced,
                                                                                  piece):
    # The transcript is read in pieces (as small as a fraction of one record here), forward for the
    # dispatches and back for span openers and the caller's own dispatch: the decision is the one the
    # whole-file reading took, for every caller, every declared path and paths no dispatch declares.
    policy = _policy(f"tool_policy_pieces_{piece}_{spaced}")
    monkeypatch.setattr(policy, "_PIECE", piece)
    monkeypatch.setattr(policy, "_BACK_PIECE", max(1, piece // 3))
    s = _long_session(tmp_path / "projects", spaced=spaced)
    _prompt, template_context = _template_prompt()
    agents = sorted(p.name[len("agent-"):-len(".meta.json")] for p in s.subagents.glob("*.meta.json"))
    kinds = {a: json.loads((s.subagents / f"agent-{a}.meta.json").read_text())["agentType"] for a in agents}
    callers = [None] + [(a, kinds[a]) for a in agents]
    paths = ["docs/dev/note.md", "src/mod1.py", "docs/dev/notes-2/x.md", "docs/dev/context-20261028-100003.json",
             template_context.replace(TASK, "20261028-100004"), "docs/dev/producer-question-20261028-100005-ba.json",
             "docs/dev/producer-question-20261028-100005-dev.json", "README.md"]
    seen = set()
    for caller in callers:
        for path in paths:
            for tool, tool_input in (("Write", _write(path)), ("Bash", {"command": f"printf x > {path}"})):
                got = _decision(policy, s, tool, tool_input, caller)
                assert got == _oracle_decision(policy, s, tool, tool_input, caller), (caller, path, tool)
                seen.add(got[0] if got[0] == "exit" else ("own" if got[1] else "none"))
    assert seen == {"exit", "own", "none"}


def test_a_subagents_own_declared_write_reads_only_the_newest_records(tmp_path, monkeypatch):
    # The caller's own dispatch is found back from the end of the session transcript: the dispatches
    # before it are neither scanned for nor decoded, whatever the session's length.
    policy = _policy("tool_policy_tail")
    s = _long_session(tmp_path / "projects", rounds=8)
    own = s.dispatch("You are the dev subagent.\n" + _block(_obligation("dev", "singular", REPORT)), "dev")
    monkeypatch.setattr(policy, "_dispatch_calls", lambda record: pytest.fail("the whole record was scanned"))
    monkeypatch.setattr(policy, "_BACK_PIECE", 512)  # the first read back is a small part of this session
    reads = []
    real_read = policy._Record._back

    def back(self, hi, floor=0):
        for data, base, lo in real_read(self, hi, floor):
            reads.append(len(data))
            yield data, base, lo

    monkeypatch.setattr(policy._Record, "_back", back)
    assert _decision(policy, s, "Write", _write(REPORT), (own, "dev")) == ("own", [str(PROJECT / REPORT)])
    assert reads and max(reads) < s.transcript.stat().st_size // 4, reads
    # A write its own dispatch does not declare still reads every dispatch (and is refused here).
    monkeypatch.undo()
    assert _decision(policy, s, "Write", _write("docs/dev/context-20261028-100003.json"), (own, "dev")) == ("exit", 2)


def test_a_template_that_cannot_declare_the_target_is_not_read(tmp_path, monkeypatch):
    # A dispatch's template is bound to its prompt only when a path of that template's shape could
    # cover the write; a dispatch's own obligation paths are always read.
    policy = _policy("tool_policy_templates")  # puts hooks/ on sys.path, as the hook does
    from lib import dispatch_template

    s = _long_session(tmp_path / "projects", rounds=2, back=False)
    read = []
    real = dispatch_template.template_obligation
    monkeypatch.setattr(dispatch_template, "template_obligation",
                        lambda command, subagent_type, prompt, *a: read.append(subagent_type) or real(
                            command, subagent_type, prompt, *a))
    # A path of /spec's template shape ("views"), which dev's own obligation covers (docs/dev/notes-1):
    # no template of these dispatches' types (ba, dev, general-purpose) can declare it.
    assert _decision(policy, s, "Write", _write("docs/dev/notes-1/views")) == ("exit", 2)
    assert read == [], read
    # BA's .md is docs/dev/ticket-<timestamp>.md: with no "/.." in a prompt, only a part that starts
    # "ticket-" can be one, so a note is not bound to any template ...
    assert _decision(policy, s, "Write", _write("docs/dev/note.md")) == ("own", [])
    assert read == [], read
    assert _decision(policy, s, "Write", _write("docs/dev/ticket-x.md")) == ("own", [])
    assert read and set(read) == {"ba"}, read  # only BA's template declares a .md
    # ... while a value with "/.." can make the ticket any .md: then the template is bound, and its
    # docs/dev/note.md is refused to the main agent as the whole-file reading refused it.
    read.clear()
    s2 = _long_session(tmp_path / "back", rounds=1, back=True)
    assert _decision(policy, s2, "Write", _write("docs/dev/note.md")) == ("exit", 2)
    assert _oracle_decision(policy, s2, "Write", _write("docs/dev/note.md")) == ("exit", 2)
    assert "ba" in read


@pytest.mark.parametrize("seed", range(40))
def test_the_piece_reader_finds_the_lines_the_whole_file_reader_finds(tmp_path, monkeypatch, seed):
    import random

    policy = _policy("tool_policy_lines")
    from lib import command_span

    rng = random.Random(seed)
    needle = b'"prompt"'
    lines = []
    for _ in range(rng.randrange(0, 40)):
        width = rng.choice([0, 1, 5, 30, 200])
        body = bytes(rng.choice(b'ab"\\pr{}:, ') for _ in range(rng.randrange(0, width + 1)))
        if rng.random() < 0.4:
            at = rng.randrange(0, len(body) + 1)
            body = body[:at] + needle * rng.choice([1, 2]) + body[at:]
        lines.append(body)
    data = b"\n".join(lines) + (b"\n" if rng.random() < 0.5 else b"")
    path = tmp_path / "t.jsonl"
    path.write_bytes(data)
    monkeypatch.setattr(policy, "_PIECE", rng.choice([1, 2, 3, 7, 16, 64]))
    record = policy._Record(path)
    try:
        got = list(record.lines(needle))
    finally:
        record.close()
    want = [(b, e, data[b:e]) for b, e in command_span._Lines(data).offsets((needle,))]
    assert got == want


# -- a declared-path write in a session several read pieces long (review 1 latency) ------------------
#
# Another caller's question is answered from the started dispatches' files, the caller's own from its
# record read back from the end; neither reads the session transcript forward. The decisions a large
# session gives, pinned at the hook's own piece sizes: a dispatch at the start of the file, one whose
# line crosses the first piece boundary, one at the end, and lines that hold every needle of a dispatch
# ("prompt", "Agent") without being one.

def _filler(k: int, width: int) -> str:
    call = f"toolu_f{k:08d}"
    body = ("def handler(payload):\n    return payload.get('x')  # Task, prompt, Agent\n" * width)[:width]
    return (json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": call, "name": "Read", "input": {"file_path": f"src/m{k}.py"}}]}}) + "\n"
            + json.dumps({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": call, "content": body}]}}) + "\n")


def _pad_to(s: "Session", offset: int) -> None:
    """Append filler until the transcript ends exactly at ``offset``."""
    size, k = s.transcript.stat().st_size, 0
    chunk = []
    while size + 8192 < offset:
        line = _filler(k, 4000)
        chunk.append(line)
        size, k = size + len(line.encode()), k + 1
    with s.transcript.open("a") as fh:
        fh.write("".join(chunk))
    bare = len(json.dumps({"type": "user", "message": {"role": "user", "content": ""}}).encode()) + 1
    s._append({"type": "user", "message": {"role": "user", "content": "x" * (offset - size - bare)}})
    assert s.transcript.stat().st_size == offset


def _no_forward_read(policy, monkeypatch) -> None:
    monkeypatch.setattr(policy._Record, "lines", lambda self, needle: pytest.fail("the transcript was read forward"))


def test_a_large_session_is_decided_from_its_started_dispatches_as_its_record_decided_it(tmp_path, monkeypatch):
    policy = _policy("tool_policy_large")
    piece = policy._PIECE
    s = Session(tmp_path / "projects")
    s.command("dev")
    first = "docs/dev/dev-report-20261028-200001.json"
    early = s.dispatch("You are the dev subagent.\n" + _block(_obligation("dev", "singular", first,
                                                                          task="20261028-200001")), "dev")
    # Lines that hold "prompt" and "Agent" and an obligation, and are no dispatch: a tool result's
    # record, another tool's call, a subagent's own (sidechain) Agent call. No subagent files name them.
    decoys = [f"docs/dev/decoy-{n}.md" for n in range(3)]
    fake = [_block(_obligation("dev", "singular", d, task="20261028-200009")) for d in decoys]
    s._append({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_x1", "content": "done"}]},
        "toolUseResult": {"name": "Agent", "prompt": fake[0], "status": "completed"}})
    s._append({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "toolu_x2", "name": "Bash",
         "input": {"command": "true", "prompt": fake[1], "description": "Agent"}}]}})
    s._append({"type": "assistant", "isSidechain": True, "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "toolu_x3", "name": "Agent", "input": {"description": "d", "prompt": fake[2]}}]}})
    # The next dispatch's line starts 64 bytes before the first piece ends.
    _pad_to(s, piece - 64)
    second = "docs/dev/context-20261028-200002.json"
    across = s.dispatch("You are the BA subagent.\n" + _block(_obligation("ba", "singular", second,
                                                                          task="20261028-200002")), "ba")
    assert s.transcript.stat().st_size > piece
    _pad_to(s, 2 * piece + 4096)
    third = "docs/dev/qa-report-20261028-200003.json"
    late = s.dispatch("You are the QA subagent.\n" + _block(_obligation("qa", "final_verification", third,
                                                                        task="20261028-200003")), "qa")
    assert s.transcript.stat().st_size > 2 * piece
    # Each dispatch started a subagent: its meta (its call, its type) and its transcript (its prompt).
    assert len(list(s.subagents.glob("agent-*.meta.json"))) == len(list(s.subagents.glob("agent-*.jsonl"))) == 3
    _no_forward_read(policy, monkeypatch)

    cases = [
        (None, first, ("exit", 2)),                       # far from the end, refused to the main agent
        ((early, "dev"), first, ("own", [first])),        # and its own dispatch's, read back that far
        ((late, "qa"), first, ("exit", 2)),               # refused to the newest dispatch
        (None, second, ("exit", 2)),                      # a dispatch line across the piece boundary
        ((across, "ba"), second, ("own", [second])),
        ((late, "qa"), third, ("own", [third])),
        ((early, "dev"), third, ("exit", 2)),
        (None, "docs/dev/note.md", ("own", [])),          # undeclared: no started dispatch declares it
    ] + [(None, d, ("own", [])) for d in decoys] + [((late, "qa"), d, ("own", [])) for d in decoys]
    for agent, path, want in cases:
        for tool, tool_input in (("Write", _write(path)), ("Bash", {"command": f"printf x > {path}"})):
            got = _decision(policy, s, tool, tool_input, agent)
            # A Write names the project path; the Bash command names it as typed.
            expected = want if want[0] == "exit" else ("own", [str(PROJECT / p) if tool == "Write" else p
                                                               for p in want[1]])
            assert got == expected, (agent, path, tool, got)
            # Every dispatch here started and carries an obligation: the whole record's reading agrees.
            assert got == _oracle_decision(policy, s, tool, tool_input, agent), (agent, path, tool)


# -- what another caller is held off: the started dispatches' files (review 1 latency) -------------

def test_a_dispatch_refused_at_pretooluse_declares_nothing(tmp_path):
    # A refused Agent call started no subagent: the CLI keeps no files for it, and G2, which runs at a
    # started subagent's stop, never acts on it. Its record still sits in the session transcript.
    policy = _policy("tool_policy_refused")
    s = Session(tmp_path / "projects")
    s.command("dev")
    ba = s.dispatch("You are the BA subagent.\n" + _block(_obligation("ba", "singular", CONTEXT)), "ba")
    s.refused("You are the dev subagent.\n" + _block(_obligation("dev", "singular", REPORT)), "dev")
    assert sorted(p.name for p in s.subagents.iterdir()) == [f"agent-{ba}.jsonl", f"agent-{ba}.meta.json"]
    question = f"docs/dev/producer-question-{TASK}-dev.json"
    for agent in (None, (ba, "ba")):
        for path in (REPORT, question):
            for tool, tool_input in (("Write", _write(path)), ("Bash", {"command": f"printf x > {path}"})):
                assert _decision(policy, s, tool, tool_input, agent) == ("own", []), (agent, path, tool)
                # The whole record's reading held it for the refused call.
                assert _oracle_decision(policy, s, tool, tool_input, agent) == ("exit", 2), (agent, path, tool)
    # The started dispatch's path is still held; the main agent's write of the refused call's report goes on.
    assert "of the ba dispatch" in _denial(s.run(tmp_path, "Write", _write(CONTEXT), None))["deny_reason"]
    assert s.run(tmp_path, "Write", _write(REPORT), None).returncode == 0


def test_a_started_dispatch_carrying_none_holds_its_types_templates_of_every_command(tmp_path):
    # Read from its subagent's files, a dispatch carrying no obligation is bound to each template of its
    # subagent type in every command file, not only its span's: a superset that only denies more to other
    # callers. Here the span is /do's, which has no such template; /dev's BA template declares the context.
    policy = _policy("tool_policy_every_command")
    prompt, context = _template_prompt()
    s = Session(tmp_path / "projects")
    s.command("do")
    ba = s.dispatch(prompt, "ba")
    gp = s.dispatch("Describe the toy package. DO NOT modify files.", "general-purpose")
    for agent in (None, (gp, "general-purpose")):
        assert _decision(policy, s, "Write", _write(context), agent) == ("exit", 2), agent
        assert _oracle_decision(policy, s, "Write", _write(context), agent) == ("own", []), agent  # its span's
    assert "of the ba dispatch" in _denial(s.run(tmp_path, "Write", _write(context), None))["deny_reason"]
    assert "of the ba dispatch" in _denial(s.run(tmp_path, "Bash", {"command": f"printf x > {context}"},
                                                 (gp, "general-purpose")))["deny_reason"]
    # The dispatch's own write is still decided from its record: its span's template declares nothing,
    # so the derived permission neither grants nor refuses it, and the BA rows decide, as before.
    assert _decision(policy, s, "Write", _write(context), (ba, "ba")) == ("own", [])
    assert _oracle_decision(policy, s, "Write", _write(context), (ba, "ba")) == ("own", [])
    assert _denial(s.run(tmp_path, "Write", _write(context), (ba, "ba")))["deny_reason"].endswith(
        "not in allowed_write_path_prefixes")
    # Another type's templates are not its: the same prompt as a general-purpose dispatch declares nothing.
    other = Session(tmp_path / "other")
    other.command("do")
    other.dispatch(prompt, "general-purpose")
    assert _decision(policy, other, "Write", _write(context)) == ("own", [])


def test_a_dispatch_at_the_start_of_a_large_session_holds_its_paths_for_other_callers(tmp_path, monkeypatch):
    # Its record is the transcript's first line, three read pieces before the end: other callers are held
    # off its paths from its subagent's files, and none of them reads the session transcript forward.
    policy = _policy("tool_policy_start")
    s = Session(tmp_path / "projects")
    ba = s.dispatch("You are the BA subagent.\n" + _block(_obligation("ba", "singular", CONTEXT)), "ba")
    assert s.transcript.read_bytes().count(b"\n") == 1
    _pad_to(s, 3 * policy._PIECE)
    dev = s.dispatch("You are the dev subagent.\n" + _block(_obligation("dev", "singular", REPORT)), "dev")
    size = s.transcript.stat().st_size
    _no_forward_read(policy, monkeypatch)
    monkeypatch.setattr(policy, "_BACK_PIECE", 512)
    reads = []
    real_back = policy._Record._back

    def back(self, hi, floor=0):
        for data, base, lo in real_back(self, hi, floor):
            reads.append(len(data))
            yield data, base, lo

    monkeypatch.setattr(policy._Record, "_back", back)
    for agent in (None, (dev, "dev")):
        for tool, tool_input in (("Write", _write(CONTEXT)), ("Bash", {"command": f"printf x > {CONTEXT}"})):
            assert _decision(policy, s, tool, tool_input, agent) == ("exit", 2), (agent, tool)
    # The newest subagent read back its own run's records only, never the record at the start.
    assert reads and max(reads) < size // 4, reads
    # The dispatch's own write is still its own, its record read back that far.
    assert _decision(policy, s, "Write", _write(CONTEXT), (ba, "ba")) == ("own", [str(PROJECT / CONTEXT)])


def test_a_subagents_own_dispatch_is_decided_from_its_record_as_before(tmp_path, monkeypatch):
    # Only the other dispatches are read from the subagents' files. What the caller's own dispatch
    # declares is decided from its record as before (its obligation, or its span's template, never every
    # command's), whatever its own files would declare: the own decisions are the whole record's.
    policy = _policy("tool_policy_own")
    prompt, context = _template_prompt()
    s = Session(tmp_path / "projects")
    s.command("do")
    in_do, in_dev = "20261028-300001", "20261028-300002"
    ba_do = s.dispatch(prompt.replace(TASK, in_do), "ba")
    s.command("dev")
    ba_dev = s.dispatch(prompt.replace(TASK, in_dev), "ba")
    dev = s.dispatch("You are the dev subagent.\n" + _block(_obligation("dev", "singular", REPORT)), "dev")
    s.refused("You are the QA subagent.\n" + _block(_obligation("qa", "final_verification", "docs/dev/qa.json")), "qa")
    paths = [context.replace(TASK, in_do), context.replace(TASK, in_dev), REPORT, "docs/dev/qa.json", "docs/dev/note.md"]
    widened = {(c, context.replace(TASK, in_do)) for c in (ba_dev, dev)}  # ba_do's /dev template, read from its files
    _no_forward_read(policy, monkeypatch)
    seen = set()
    for agent in ((ba_do, "ba"), (ba_dev, "ba"), (dev, "dev")):
        for path in paths:
            for tool, tool_input in (("Write", _write(path)), ("Bash", {"command": f"printf x > {path}"})):
                got = _decision(policy, s, tool, tool_input, agent)
                was = _oracle_decision(policy, s, tool, tool_input, agent)
                if (agent[0], path) in widened:
                    assert (was, got) == (("own", []), ("exit", 2)), (agent, path, tool)
                elif path == "docs/dev/qa.json":  # the refused dispatch's
                    assert (was, got) == (("exit", 2), ("own", [])), (agent, path, tool)
                else:
                    assert got == was, (agent, path, tool)
                seen.add(got[0] if got[0] == "exit" else ("own" if got[1] else "none"))
    assert seen == {"exit", "own", "none"}
    # Among them: ba_do's own context stays undeclared for it, ba_dev's and dev's are their own.
    assert _decision(policy, s, "Write", _write(context.replace(TASK, in_do)), (ba_do, "ba")) == ("own", [])
    assert _decision(policy, s, "Write", _write(context.replace(TASK, in_dev)), (ba_dev, "ba")) == (
        "own", [str(PROJECT / context.replace(TASK, in_dev))])
    assert _decision(policy, s, "Write", _write(REPORT), (dev, "dev")) == ("own", [str(PROJECT / REPORT)])


# -- the per-call cost: work a decision does not need is not done (review 1 latency, round 2) -------
#
# Each shortcut below is held to the reading it skips: the decisions (exit code and the denial's text)
# with it equal those without it, and the shortcut must fire, so a test cannot pass vacuously.

def _decided(policy, s, tool, tool_input, agent=None):
    """_decision with what the hook wrote to stderr."""
    import contextlib
    import io

    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        got = _decision(policy, s, tool, tool_input, agent)
    return got, err.getvalue()


def _mixed_session(root: Path) -> "Session":
    """Started dispatches of every kind the other-caller reading meets: valid obligations naming files,
    a directory and a producer question's role, invalid blocks (two of them, malformed JSON, an unknown
    field, a pattern field), the current /dev BA template carrying none (with and without a "/.." value
    that makes its ticket docs/dev/note.md), plain prompts, and a dispatch with no meta."""
    prompt, _context = _template_prompt()
    s = Session(root)
    s.command("dev")
    for k, (role, profile, path) in enumerate([("ba", "singular", "docs/dev/context-{t}.json"),
                                               ("dev", "singular", "docs/dev/dev-report-{t}.json"),
                                               ("qa", "final_verification", "docs/dev/qa-report-{t}.json"),
                                               ("dev", "singular", "docs/dev/notes-{t}"),
                                               ("spec", "singular", "src/mod{t}.py")]):
        task = f"20261028-4{k:05d}"
        s.dispatch(f"You are {role}.\n" + _block(_obligation(role, profile, path.format(t=task), task=task)), role)
    bad = _obligation("dev", "singular", "docs/dev/note.md", task="20261028-499999")
    s.dispatch("Two blocks.\n" + _block(bad) + "\n" + _block(bad), "dev")
    s.dispatch('Malformed.\n<obligation v="1">\n{"task_id": \n</obligation>', "dev")
    s.dispatch("Unknown field.\n" + _block(dict(bad, extra=1)), "dev")
    pattern = dict(bad, artifacts=[{"kind": "markdown", "path": "docs/dev/note.md", "identity_anchor": "x",
                                    "terminal_line_regex": "("}])
    s.dispatch("A pattern.\n" + _block(pattern), "dev")
    s.dispatch(prompt.replace(TASK, "20261028-488888"), "ba")
    s.dispatch(prompt.replace(TASK, "x/../note"), "ba")
    s.dispatch("Describe the toy package.", "general-purpose")
    s.dispatch("You are dev.\n" + _block(_obligation("dev", "singular", "docs/dev/nometa.md")), "dev", meta=False)
    return s


def test_a_dispatch_that_cannot_declare_the_target_decides_as_its_full_reading(tmp_path, monkeypatch):
    # A started dispatch whose obligation block (valid or not) names no path and no producer question
    # that covers the target, and whose templates cannot, is neither validated nor bound
    # (_obligation_may_declare, _template_bounds): every decision and denial equals the full reading's.
    policy = _policy("tool_policy_skip")
    from lib import declared_paths, obligation

    s = _mixed_session(tmp_path / "projects")
    agents = sorted(p.name[len("agent-"):-len(".meta.json")] for p in s.subagents.glob("*.meta.json"))
    kinds = {a: json.loads((s.subagents / f"agent-{a}.meta.json").read_text())["agentType"] for a in agents}
    callers = [None] + [(a, kinds[a]) for a in agents[::3]]
    paths = ["docs/dev/note.md", "docs/dev/context-20261028-400000.json", "docs/dev/qa-report-20261028-400002.json",
             "docs/dev/notes-20261028-400003/a.md", "docs/dev/producer-question-20261028-400000-ba.json",
             "src/mod20261028-400004.py", "docs/dev/ticket-20261028-488888.md", "docs/dev/nometa.md",
             "docs/dev/specs/s/views/v.md", "README.md"]
    parsed = []
    real_parse = obligation.parse_obligation
    monkeypatch.setattr(obligation, "parse_obligation", lambda prompt, *a: parsed.append(prompt) or real_parse(prompt, *a))
    cases = [(tool, tool_input, c) for c in callers for p in paths
             for tool, tool_input in (("Write", _write(p)), ("Bash", {"command": f"printf x > {p} && printf y > {p}.b"}))]
    shortcut = [_decided(policy, s, *case) for case in cases]
    skipped = len(parsed)
    with monkeypatch.context() as m:
        m.setattr(declared_paths, "_obligation_may_declare", lambda prompt, targets: True)
        m.setattr(declared_paths, "_template_bounds", lambda: declared_paths._ANY)
        parsed.clear()
        full = [_decided(policy, s, *case) for case in cases]
    assert shortcut == full
    assert len(parsed) > skipped, "the shortcut skipped no obligation"
    outcomes = {got[0] if got[0] == "exit" else ("own" if got[1] else "none") for got, _err in shortcut}
    assert outcomes == {"exit", "own", "none"} and any(err for _got, err in shortcut)


def test_a_block_whose_validation_raises_is_read_in_full(tmp_path, monkeypatch):
    # Validating a pattern field compiles it, and a repetition too large for re raises OverflowError,
    # not re.error: such a block is never skipped, so the decision is the full reading's (here, the
    # error the hook's __main__ handler turns into its fail-open exit) and not another dispatch's denial.
    policy = _policy("tool_policy_pattern")
    from lib import declared_paths

    s = Session(tmp_path / "projects")
    held = "docs/dev/held.md"  # a .md no template's path can be without a "/.." value: only BA's own block names it
    s.dispatch("You are BA.\n" + _block(_obligation("ba", "singular", held)), "ba")
    doc = _obligation("dev", "singular", "docs/dev/elsewhere.md", task="20261028-477777")
    doc["artifacts"][0]["terminal_line_regex"] = "a{99999999999}"
    s.dispatch("You are dev.\n" + _block(doc), "dev")
    with pytest.raises(OverflowError):
        _decision(policy, s, "Write", _write(held))
    with monkeypatch.context() as m:
        m.setattr(declared_paths, "_obligation_may_declare", lambda prompt, targets: True)
        with pytest.raises(OverflowError):
            _decision(policy, s, "Write", _write(held))
    proc = s.run(tmp_path, "Write", _write(held), None)
    assert (proc.returncode, proc.stderr.startswith("pretool-tool-policy: unexpected")) == (0, True), proc.stderr
    # Without the pattern field the dev block is skipped and BA's declaration decides.
    del doc["artifacts"][0]["terminal_line_regex"]
    s.dispatch("You are dev again.\n" + _block(doc), "dev")
    (s.subagents / next(p.name for p in s.subagents.glob("agent-*.jsonl")
                        if "a{99999999999}" in p.read_text())).unlink()
    assert _decision(policy, s, "Write", _write(held)) == ("exit", 2)


def test_a_value_that_takes_a_part_back_is_read_from_the_prompt(tmp_path, monkeypatch):
    # A "/.." in a prompt lets a bound value take a template's segment back, so a template path of
    # another name may come to cover the target. Bound values are text of the prompt's lines: where the
    # template's last segment binds one value, it covers a part p only through a value ending in "/" + p
    # without the tail, which the prompt then holds; a segment binding two is read whatever the prompt
    # holds. Every decision equals the full reading's, and both kinds of template make a denial.
    policy = _policy("tool_policy_back")
    from lib import declared_paths, stop_contract

    one = ("subagent_type: worker\nPart C: <c>\n", '{"role": "worker", "profile": "singular", "artifacts": '
           '[{"kind": "markdown", "path": "docs/dev/s-<c>.md", "identity_anchor": "<c>"}]}')
    two = ("subagent_type: maker\nPart A: <a>\nPart B: <b>\n", '{"role": "maker", "profile": "singular", "artifacts": '
           '[{"kind": "markdown", "path": "docs/dev/t-<a>-<b>.md", "identity_anchor": "<b>"}]}')
    configs = [
        (one, [("Part C: y/../note\n", "worker"),               # binds docs/dev/note.md; the prompt holds "/note"
               ("Part C: y/../other\nsee /../ too\n", "worker"),  # binds docs/dev/other.md
               ("Part C: plain\nsee /../note.md\n", "worker"),    # holds "/note" in a line no template line matches
               ("Plain prompt.\n", "worker")],
         {"docs/dev/note.md": 2, "docs/dev/other.md": 2, "docs/dev/elsewhere.md": 0, "docs/dev/s-z.md": 0}),
        (two, [("Part A: x/../no\nPart B: te\n", "maker"),      # docs/dev/no-te.md: "/no-te" is in no line
               ("Part A: k/..\nPart B: q/../w\n", "maker")],    # docs/dev/t-k/w.md
         {"docs/dev/no-te.md": 2, "docs/dev/w.md": 0, "docs/dev/t-a-b.md": 0}),
    ]
    for n, ((fence, example), prompts, want) in enumerate(configs):
        commands = tmp_path / f"commands{n}"
        commands.mkdir()
        monkeypatch.setattr(stop_contract, "COMMANDS_DIR", commands)
        (commands / "x.md").write_text("---\nname: x\n---\n```\n" + fence + "<obligation v=\"1\">\n" + example
                                       + "\n</obligation>\n```\n", encoding="utf-8")
        s = Session(tmp_path / f"projects{n}")
        s.command("x")
        for prompt, kind in prompts:
            s.dispatch(prompt, kind)
        cases = [(tool, tool_input, None) for t in want
                 for tool, tool_input in (("Write", _write(t)), ("Bash", {"command": f"printf x > {t}"}))]
        gated = []
        real = declared_paths._bounds_may_cover_back
        with monkeypatch.context() as m:
            m.setattr(declared_paths, "_bounds_may_cover_back", lambda *a: gated.append(real(*a)) or gated[-1])
            shortcut = [_decided(policy, s, *case) for case in cases]
        with monkeypatch.context() as m:
            m.setattr(declared_paths, "_template_bounds", lambda: declared_paths._ANY)
            m.setattr(declared_paths, "_obligation_may_declare", lambda prompt, targets: True)
            full = [_decided(policy, s, *case) for case in cases]
        assert shortcut == full, n
        for i, (target, code) in enumerate(want.items()):
            assert shortcut[2 * i][0] == (("exit", 2) if code else ("own", [])), (n, target)
        assert set(gated) == ({True, False} if n == 0 else {True}), (n, gated)  # skipped some, kept others


def _validation_fuzz_doc(rng, kinds):
    def value():
        return rng.choice([None, True, 0, 1.5, "", "x", "docs/dev/a.md", "/abs", "a/../b", "2026-10-28T10:10:10Z",
                           "20261028-101010", "dev", "singular", [], ["a"], ["a", "a"], {}, {"task_id": "x"},
                           {"task_id": 1}, [{"kind": "json"}]])
    doc = {}
    for key in ("task_id", "lane", "lane_set", "role", "pipeline", "profile", "dispatched_at", "artifacts",
                "consistency", "expected_absent", "extra"):
        if rng.random() < 0.8:
            doc[key] = value()
    if rng.random() < 0.7:
        doc.update(role=rng.choice(["dev", "ba", "nobody"]), pipeline=rng.choice(["dev", "spec", "none"]),
                   profile=rng.choice(["singular", "commit-qa", "nope"]), task_id=rng.choice([None, "20261028-101010", 3]))
    if rng.random() < 0.8:
        entries = []
        for _ in range(rng.randrange(0, 3)):
            entry = {"kind": rng.choice(kinds + ["nope", 3])} if rng.random() < 0.9 else {}
            for key in ("path", "schema", "identity", "identity_anchor", "begin", "end", "format", "monolith"):
                if rng.random() < 0.5:
                    entry[key] = value()
            entries.append(entry if rng.random() < 0.95 else rng.choice([None, "x", 3]))
        doc["artifacts"] = entries
    return doc


@pytest.mark.parametrize("seed", range(4))
def test_validation_raises_on_no_document_but_through_a_pattern(seed):
    # What _obligation_may_declare relies on: validating a parsed obligation that names no pattern field
    # never raises, so a block it does not validate cannot be one whose validation would have raised.
    import random

    _policy("tool_policy_validation")
    from lib import declared_paths, obligation, roster

    rng = random.Random(seed)
    kinds = sorted(obligation.ARTIFACT_KINDS)
    assert kinds and declared_paths._PATTERN_FIELDS
    with roster.held():
        for _ in range(3000):
            doc = _validation_fuzz_doc(rng, kinds)
            artifacts = doc.get("artifacts") if isinstance(doc.get("artifacts"), list) else []
            assert not any(isinstance(a, dict) and any(f in a for f in declared_paths._PATTERN_FIELDS) for a in artifacts)
            obligation.validate_obligation(doc)
            obligation.parse_obligation(_block(doc))


def _template_types(policy, text: str) -> set:
    from lib import dispatch_template

    return {kind for _body, kind, _roles, _profiles, _example in dispatch_template._parsed_fences(text)}


def test_the_template_bounds_hold_every_commands_template_shapes(tmp_path, monkeypatch):
    # _template_bounds reads every obligation block of every command file without parsing a fence; what
    # _template_shapes gives for any command and subagent type is among them, so a gate on the bounds
    # never skips a template that could cover a target. Held for the current files and for edge cases:
    # an opener with no close, two openers before one close, blocks outside any fence, spaces around
    # the JSON that only a Unicode-aware strip removes, and a path of any shape (then both are _ANY).
    policy = _policy("tool_policy_bounds")
    from lib import declared_paths, stop_contract

    def check():
        declared_paths._FENCE_SHAPES.clear()
        with declared_paths.decision():
            bounds = declared_paths._template_bounds()
            names = sorted(p.stem for p in stop_contract.COMMANDS_DIR.glob("*.md"))
            seen = 0
            for name in names + [None]:
                text = "".join((stop_contract.COMMANDS_DIR / f"{n}.md").read_text() for n in (names if name is None else [name]))
                for kind in _template_types(policy, text) | {"general-purpose", "nobody"}:
                    shapes = declared_paths._template_shapes(name, kind)
                    if shapes is declared_paths._ANY:
                        assert bounds is declared_paths._ANY, (name, kind)
                    else:
                        assert bounds is declared_paths._ANY or shapes <= bounds, (name, kind, shapes - bounds)
                        seen += len(shapes)
        declared_paths._FENCE_SHAPES.clear()
        return bounds, seen

    bounds, seen = check()
    assert bounds is not declared_paths._ANY and seen
    commands = tmp_path / "commands"
    commands.mkdir()
    monkeypatch.setattr(stop_contract, "COMMANDS_DIR", commands)
    example = '{"role": "ba", "profile": "singular", "artifacts": [{"kind": "markdown", "path": "docs/dev/%s-<t>.md"}]}'
    (commands / "a.md").write_text(
        "---\n---\n```\nsubagent_type: ba\n<obligation v=\"1\">  " + example % "one" + "　\n</obligation>\n```\n"
        "```\nsubagent_type: ba\n<obligation v=\"1\"> <obligation v=\"1\">" + example % "two" + "</obligation>\n```\n"
        "```\nsubagent_type: qa\n<obligation v=\"1\">" + example % "three" + "\n```\n"
        "<obligation v=\"1\">" + example % "loose" + "</obligation>\n", encoding="utf-8")
    bounds, seen = check()
    assert seen and {p for (kind, p), _prefix in bounds} >= {".md"}
    (commands / "b.md").write_text("```\nsubagent_type: ba\n<obligation v=\"1\">"
                                   '{"artifacts": [{"kind": "markdown", "path": "docs/dev/<t>"}]}'
                                   "</obligation>\n```\n", encoding="utf-8")
    assert check()[0] is declared_paths._ANY


def _line_reader_prompt(path):
    """read_first_record_prompt as it read every file before its first-line read (the oracle)."""
    record = None
    try:
        with Path(path).open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    candidate = json.loads(line)
                except ValueError:
                    return None
                if isinstance(candidate, dict) and candidate.get("type") in ("user", "assistant"):
                    record = candidate
                    break
    except OSError:
        return None
    if record is None or record.get("type") != "user":
        return None
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content or None
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text") or None
    return None


@pytest.mark.parametrize("seed", range(6))
def test_the_first_record_is_read_as_the_line_reader_read_it(tmp_path, seed):
    # obligation.read_first_record_prompt reads a subagent transcript's first line with raw reads and
    # falls back to the text reader where that line does not decide: the prompt (or None) is the text
    # reader's for any bytes, invalid UTF-8, carriage returns and lines longer than one read included.
    import random

    _policy("tool_policy_first_record")
    from lib import obligation

    rng = random.Random(seed)
    records = [
        {"type": "user", "message": {"role": "user", "content": "Prompt é— x"}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "a/"},
                                                                  {"type": "image"}, {"type": "text", "text": ".."}]}},
        {"type": "assistant", "message": {"content": "no"}}, {"type": "queue-operation"}, {"type": "user"},
        {"type": "user", "message": {"content": ""}}, [1, 2], "text",
    ]
    pieces = [b"\n", b"\r", b"\r\n", b"\xff", b"\xe2\x82", b"\xe2\x82\xac", b"{", b'"', b"x" * 70000, b" "]
    seen = set()
    for n in range(60):
        lines = []
        for _ in range(rng.randrange(0, 4)):
            line = json.dumps(rng.choice(records), ensure_ascii=rng.random() < 0.5).encode()
            if rng.random() < 0.3:
                at = rng.randrange(0, len(line) + 1)
                line = line[:at] + rng.choice(pieces) + line[at:]
            lines.append(line)
        data = b"\n".join(lines) + (b"\n" if rng.random() < 0.5 else b"")
        path = tmp_path / f"agent-{n}.jsonl"
        path.write_bytes(data)
        want = _line_reader_prompt(path)
        for spelled in (str(path), path, str(path) + "/", str(tmp_path) + "//" + path.name):
            assert obligation.read_first_record_prompt(spelled) == want, (data[:200], spelled)
        seen.add(want is None)
    assert seen == {True, False}
    user = {"type": "user", "message": {"role": "user", "content": "the prompt"}}
    edge = [
        b'{"type": "user",\r "message": {"content": "split at the CR"}}\n',  # the text reader ends a line at \r
        json.dumps(user).encode() + b"\r\n" + b"tail\r\n",  # CRLF line ends
        json.dumps({"type": "queue-operation"}).encode() + b"\n" + json.dumps(user).encode() + b"\n",
        json.dumps({"type": "user", "message": {"content": "x" * 200000}}).encode() + b"\n",  # longer than one read
        json.dumps(user).encode()[:-2] + b"\xe2\x82" + b'"}}\n',  # an incomplete sequence in the line
        json.dumps(user).encode() + b"\xe2\x82\n",  # ... and right before its newline
        b"", b"\n", b"\r", json.dumps(user).encode(),
    ]
    for n, data in enumerate(edge):
        path = tmp_path / f"edge-{n}.jsonl"
        path.write_bytes(data)
        assert obligation.read_first_record_prompt(str(path)) == _line_reader_prompt(path), data[:120]
    assert _line_reader_prompt(tmp_path / "edge-0.jsonl") is None and _line_reader_prompt(tmp_path / "edge-2.jsonl")
    assert obligation.read_first_record_prompt(str(tmp_path / "missing.jsonl")) is None
    assert obligation.read_first_record_prompt(str(tmp_path)) is None


@pytest.mark.parametrize("seed", range(4))
def test_the_raw_reads_give_what_the_text_reads_gave(tmp_path, seed):
    # _load_json (a started dispatch's meta) and _read_text (a command file, once per decision) read raw
    # bytes; each gives json.load(open()) and Path.read_text(encoding="utf-8")'s result or error class.
    import random

    _policy("tool_policy_raw_reads")
    from lib import declared_paths

    rng = random.Random(seed)
    pieces = [b"\r\n", b"\r", b"\n", b"\xff", b"\xef\xbb\xbf", b"\x01", b'"', b"\\", b"\xc3\xa9", b" "]
    doc = json.dumps({"agentType": "ba", "toolUseId": "toolu_x", "n": [1, {"a": "bé"}]}).encode()

    def outcome(fn, path):
        try:
            return ("ok", fn(path))
        except (OSError, ValueError) as e:
            return ("error", OSError if isinstance(e, OSError) else UnicodeDecodeError
                    if isinstance(e, UnicodeDecodeError) else ValueError)

    for n in range(80):
        data = doc
        for _ in range(rng.randrange(0, 3)):
            at = rng.randrange(0, len(data) + 1)
            data = data[:at] + rng.choice(pieces) + data[at:]
        path = tmp_path / f"f{n}"
        path.write_bytes(data)
        assert outcome(declared_paths._load_json, path) == outcome(lambda p: json.load(open(p)), path), data
        assert outcome(declared_paths._read_text, path) == outcome(lambda p: p.read_text(encoding="utf-8"), path), data
    assert declared_paths._TEXT_ENCODING is not None  # the raw reads were the ones compared
    for missing in (tmp_path / "missing", tmp_path):
        assert outcome(declared_paths._load_json, missing) == outcome(lambda p: json.load(open(p)), missing)


def test_the_declarable_shapes_decode_only_an_escaped_value(tmp_path, monkeypatch):
    # A path value with no backslash is taken as written; json.loads gave the same (or refused a control
    # character, and the raw text was taken). The shapes equal the ones decoding every value gave.
    policy = _policy("tool_policy_shape_values")
    from lib import declared_paths, stop_contract

    def decoded_every_value():
        shapes = {declared_paths._shape(declared_paths._QUESTION_PATH)}
        for file in sorted(stop_contract.COMMANDS_DIR.glob("*.md")):
            for raw in declared_paths._TEMPLATE_PATH_RE.findall(file.read_text(encoding="utf-8")):
                try:
                    value = json.loads(f'"{raw}"')
                except ValueError:
                    value = raw
                shapes.add(declared_paths._shape(value))
        return shapes

    assert policy._declarable_shapes() == decoded_every_value()
    commands = tmp_path / "commands"
    commands.mkdir()
    monkeypatch.setattr(stop_contract, "COMMANDS_DIR", commands)
    (commands / "x.md").write_text('"path": "a/b\\u002ec"\n"path": "d/e\\/f.md"\n"path": "g/h\tij.json"\n'
                                   '"path": "k/<l>\\\\m"\n"path": "n/\\q"\n', encoding="utf-8")
    with declared_paths.decision():
        assert declared_paths._declarable_shapes() == decoded_every_value()
    assert declared_paths._declarable_shapes() == decoded_every_value()


def test_the_roster_is_read_once_within_a_held_block(tmp_path):
    # Validating every started dispatch's obligation asks for the agent and command rosters once each:
    # within roster.held() a directory is listed and read once; outside it the roster follows the files.
    _policy("tool_policy_roster")
    from lib import roster

    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "ba.md").write_text("---\n", encoding="utf-8")
    with roster.held():
        assert roster.roles(agents) == {"ba"}
        (agents / "qa.md").write_text("---\n", encoding="utf-8")
        assert roster.roles(agents) == {"ba"}
        with roster.held():
            assert roster.roles(agents) == {"ba"}
        assert roster.roles(str(agents)) == {"ba", "qa"}  # another name for it is read once of its own
    assert roster.roles(agents) == {"ba", "qa"}
    assert roster._HELD is None


def test_a_hook_process_ends_with_the_status_and_output_it_decided(tmp_path, cycle):
    # Run as a script, the hook ends without the interpreter's teardown (_end); its exit status and
    # stderr are the ones it decided, a denial's and an allow's alike.
    denied = cycle.run(tmp_path, "Write", _write(CONTEXT), None)
    assert denied.returncode == 2 and denied.stderr.startswith(BLOCK) and denied.stderr.endswith("\n")
    assert len(denied.stderr.splitlines()) == 1
    allowed = cycle.run(tmp_path, "Write", _write("docs/dev/notes.md"), None)
    assert (allowed.returncode, allowed.stderr, allowed.stdout) == (0, "", "")
