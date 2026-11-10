"""T2-9: hooks/lib/spec_path.py reads the session transcript through command_span, the one
transcript reader the Stop gate decides on, and finds the spec the old parser of its own
found, in every case the CLI writes.

`_old_last_spec_write` below is spec_path.last_spec_write as it was at d64fa96 (its own
transcript parser), kept verbatim as the reference. The first attempt at this change took
each call from command_span alone and resolved a relative target against the hook's cwd;
a command_span Call carries no record cwd, so test_spec_path.py's
test_relative_paths_resolve_against_the_record_cwd failed and the attempt was set aside.
The record-cwd cases are pinned here first.

What command_span's rule decides differently is pinned at the end: none of it is a shape
the CLI writes (a subagent's records live in subagents/agent-<id>.jsonl, a tool_use id is
unique to its call, every content block is typed, a Bash result's toolUseResult holds no
content list)."""
from __future__ import annotations

import json
import os
import random
import re
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS / "lib"))
import command_span  # noqa: E402
import spec_path  # noqa: E402

PROJECT = "/work/proj"
SPECS = [f"{PROJECT}/docs/dev/specs/spec-2026102{n}-101010.md" for n in range(3)]


# --- the reference: spec_path.last_spec_write at d64fa96 -----------------------------------
_EDIT_TOOLS = ("Write", "Edit", "MultiEdit")
_WRITER = "spec-write.py"
_WRITER_LINE = re.compile(r"^spec-write: (?:create|append) (/\S+)$", re.M)


def _old_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def _old_last_spec_write(transcript_path, cwd=""):
    uses, results = [], {}
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                message = record.get("message") if isinstance(record, dict) else None
                content = message.get("content") if isinstance(message, dict) else None
                for block in content if isinstance(content, list) else ():
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                        uses.append((block.get("id"), block.get("name"), block["input"],
                                     record.get("cwd") or cwd))
                    elif block.get("type") == "tool_result" and not block.get("is_error"):
                        results[block.get("tool_use_id")] = _old_text(block.get("content"))
    except (OSError, TypeError):
        return None
    found = None
    for use_id, name, tool_input, base in uses:
        if use_id not in results:
            continue
        if name in _EDIT_TOOLS:
            target = tool_input.get("file_path")
            if isinstance(target, str) and target:
                target = os.path.normpath(os.path.join(base or os.sep, os.path.expanduser(target)))
                if spec_path.is_spec_file(target):
                    found = target
        elif name == "Bash" and _WRITER in str(tool_input.get("command", "")):
            for target in _WRITER_LINE.findall(results[use_id]):
                if spec_path.is_spec_file(target):
                    found = target
    return found


# --- CLI-shaped transcripts ------------------------------------------------------------
class T:
    """A main-session transcript as the CLI writes it: compact JSON, one record per line,
    each record with its cwd, each call's result in a later user record."""

    def __init__(self, cwd=PROJECT):
        self.records, self.cwd, self._n = [], cwd, 0
        self.prompt("/spec add a thing")

    def prompt(self, text):
        self.records.append({"type": "user", "cwd": self.cwd, "message": {"role": "user", "content": text}})
        return self

    def use(self, name, tool_input):
        self._n += 1
        ident = f"toolu_01{self._n:022d}"
        self.records.append({"type": "assistant", "cwd": self.cwd, "message": {
            "role": "assistant", "content": [{"type": "tool_use", "id": ident, "name": name, "input": tool_input}]}})
        return ident

    def result(self, ident, content="ok", is_error=False, **extra):
        block = {"type": "tool_result", "tool_use_id": ident, "content": content}
        if is_error:
            block["is_error"] = True
        self.records.append({"type": "user", "cwd": self.cwd, "message": {"role": "user", "content": [block]},
                             **extra})
        return self

    def call(self, name, tool_input, content="ok", is_error=False):
        return self.result(self.use(name, tool_input), content, is_error)

    def write(self, path, name="Write"):
        return self.call(name, {"file_path": path, "content": "x"} if name == "Write" else {"file_path": path})

    def spec_write(self, path, op="append", as_list=False):
        text = f"spec-write: {op} {path}\n"
        return self.call("Bash", {"command": f'python3 "/h/scripts/spec-write.py" {op} --spec {path} --section 5'},
                         [{"type": "text", "text": text}] if as_list else text)

    def save(self, tmp_path, name="t.jsonl", spaced=False):
        path = tmp_path / name
        sep = None if spaced else (",", ":")
        path.write_text("".join(json.dumps(r, separators=sep) + "\n" for r in self.records), encoding="utf-8")
        return str(path)


def _same(path, *cwds):
    """The new answer, after checking it equals the old one for each hook cwd."""
    answers = set()
    for cwd in cwds or ("", PROJECT):
        old, new = _old_last_spec_write(path, cwd), spec_path.last_spec_write(path, cwd)
        assert new == old, (cwd, old, new)
        answers.add(new)
    assert len(answers) == 1 or not cwds
    return new


# The cases that set the first attempt aside: a relative target is resolved against the cwd
# of its own tool_use record, whatever cwd the hook passes.
def test_a_relative_target_resolves_against_its_record_cwd(tmp_path):
    t = T()
    t.write("docs/dev/specs/spec-20261020-101010.md", "MultiEdit")
    assert _same(t.save(tmp_path), "", "/elsewhere") == SPECS[0]


def test_a_relative_target_after_a_cd_takes_the_cwd_recorded_then(tmp_path):
    t = T()
    t.write(SPECS[1])
    t.cwd = f"{PROJECT}/docs/dev"
    t.write("specs/spec-20261020-101010.md", "Edit")
    t.cwd = "/work"
    t.call("Read", {"file_path": "proj/README.md"})
    assert _same(t.save(tmp_path), "", PROJECT) == SPECS[0]


def test_a_record_without_cwd_falls_back_to_the_hooks_cwd_then_the_root(tmp_path):
    t = T(cwd=None)
    t.write("docs/dev/specs/spec-20261020-101010.md")
    path = t.save(tmp_path)
    for cwd in ("", PROJECT, "/other"):
        assert spec_path.last_spec_write(path, cwd) == _old_last_spec_write(path, cwd)
    assert spec_path.last_spec_write(path, PROJECT) == SPECS[0]
    assert spec_path.last_spec_write(path, "") == "/docs/dev/specs/spec-20261020-101010.md"  # from the root


def test_a_home_relative_target_expands(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/work/proj")
    t = T()
    t.write("~/docs/dev/specs/spec-20261022-101010.md")
    assert _same(t.save(tmp_path)) == SPECS[2]


# The rest of what the CLI writes.
def test_the_last_ok_spec_write_wins_across_tools(tmp_path):
    t = T()
    t.write(SPECS[0]).spec_write(SPECS[1], "create").write(SPECS[2], "Edit").spec_write(SPECS[1])
    assert _same(t.save(tmp_path)) == SPECS[1]
    t.write(SPECS[0], "MultiEdit")
    assert _same(t.save(tmp_path, "t2.jsonl", spaced=True)) == SPECS[0]


def test_what_is_not_a_spec_write(tmp_path):
    t = T()
    t.write(SPECS[0])
    t.call("Write", {"file_path": SPECS[1], "content": "x"}, "denied", True)
    t.use("Edit", {"file_path": SPECS[1]})                                   # no result yet
    t.call("Read", {"file_path": SPECS[1]})
    for name in ("INDEX.md", "README.md", "20261020-101010/views/ba.md", "spec.txt"):
        t.write(f"{PROJECT}/docs/dev/specs/{name}")
    t.write(f"{PROJECT}/docs/specs/spec-x.md")
    t.call("Bash", {"command": f"echo spec-write: append {SPECS[1]}"}, f"spec-write: append {SPECS[1]}\n")
    t.call("Bash", {"command": "python3 spec-write.py append --spec x --section 5"}, "refused", True)
    t.call("Bash", {"command": "python3 spec-write.py append --spec x"}, f"spec-write: append {PROJECT}/README.md\n")
    t.call("Bash", {"command": "python3 spec-write.py append --spec x"}, f"note: spec-write: append {SPECS[1]}\n")
    assert _same(t.save(tmp_path)) == SPECS[0]


def test_several_writer_lines_in_one_output_and_a_listed_content(tmp_path):
    t = T()
    t.call("Bash", {"command": "python3 spec-write.py create --spec a && python3 spec-write.py append --spec b"},
           f"spec-write: create {SPECS[0]}\nother\nspec-write: append {SPECS[2]}\nspec-write: append /x/notes.md\n")
    assert _same(t.save(tmp_path)) == SPECS[2]
    t.spec_write(SPECS[1], as_list=True)
    assert _same(t.save(tmp_path, "t2.jsonl")) == SPECS[1]


def test_parallel_calls_whose_results_come_later(tmp_path):
    t = T()
    first = t.use("Write", {"file_path": SPECS[0], "content": "x"})
    second = t.use("Edit", {"file_path": SPECS[1]})
    t.result(second).result(first)
    assert _same(t.save(tmp_path)) == SPECS[1]
    # two calls in one assistant record, the later one refused
    t = T()
    t.records.append({"type": "assistant", "cwd": PROJECT, "message": {"role": "assistant", "content": [
        {"type": "text", "text": "writing"},
        {"type": "tool_use", "id": "toolu_a", "name": "Write", "input": {"file_path": SPECS[2], "content": "x"}},
        {"type": "tool_use", "id": "toolu_b", "name": "Edit", "input": {"file_path": SPECS[0]}}]}})
    t.records.append({"type": "user", "cwd": PROJECT, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_a", "content": "ok"},
        {"type": "tool_result", "tool_use_id": "toolu_b", "content": "no", "is_error": True}]}})
    assert _same(t.save(tmp_path, "t2.jsonl")) == SPECS[2]


def test_a_resumed_history_copied_into_the_file(tmp_path):
    t = T()
    t.write(SPECS[0]).spec_write(SPECS[2])
    t.records += [dict(r) for r in t.records]
    t.prompt("/dev go")
    assert _same(t.save(tmp_path)) == SPECS[2]


def test_unparsable_lines_records_and_blocks_are_skipped(tmp_path):
    t = T()
    t.write(SPECS[1])
    path = Path(t.save(tmp_path))
    junk = b"\n".join([b'{"type":"assistant"', b"[1,2]", b'"text"', b'{"message":"plain"}',
                       b'{"type":"assistant","message":{"content":["tool_use",{"type":"tool_use","name":"Write"}]}}',
                       b'{"type":"assistant","message":{"content":[{"type":"tool_use","id":"z","name":"Write",'
                       b'"input":"x"}]}}', b"\xff\xfe not utf-8 \xc3"]) + b"\n"
    path.write_bytes(junk + path.read_bytes() + junk)
    assert _same(str(path)) == SPECS[1]


def test_a_long_transcript_with_the_write_far_back(tmp_path):
    t = T()
    t.spec_write(SPECS[0], "create")
    for n in range(3000):
        t.call("Read", {"file_path": f"{PROJECT}/src/f{n}.py"}, "x" * 200)
    t.prompt("/dev next")
    assert _same(t.save(tmp_path)) == SPECS[0]


def test_no_write_and_no_transcript(tmp_path):
    assert _same(T().save(tmp_path)) is None
    for path in (str(tmp_path / "absent.jsonl"), str(tmp_path), "", None):
        assert spec_path.last_spec_write(path) is None
        assert _old_last_spec_write(path) is None
    assert spec_path.last_spec_write(tmp_path / "absent.jsonl") is None


def test_random_cli_shaped_sessions_agree(tmp_path):
    rng = random.Random(9)
    cwds = [PROJECT, f"{PROJECT}/docs/dev", "/work", None]
    targets = SPECS + ["docs/dev/specs/spec-20261020-101010.md", "specs/spec-20261021-101010.md",
                       f"{PROJECT}/docs/dev/specs/INDEX.md", f"{PROJECT}/src/a.py"]
    for case in range(300):
        t = T(cwd=rng.choice(cwds))
        late = []
        for _ in range(rng.randint(0, 8)):
            t.cwd = rng.choice(cwds)
            name = rng.choice(["Write", "Edit", "MultiEdit", "Bash", "Read", "Agent"])
            target = rng.choice(targets)
            if name == "Bash":
                ident = t.use(name, {"command": f"python3 spec-write.py append --spec {target} --section 5"})
                content = f"spec-write: append {target}\n"
            elif name == "Agent":
                ident, content = t.use(name, {"prompt": f"write {SPECS[0]}"}), f"spec-write: append {SPECS[0]}\n"
            else:
                ident, content = t.use(name, {"file_path": target}), "ok"
            fate = rng.random()
            if fate < 0.1:
                continue                          # interrupted: no result
            if fate < 0.3:
                late.append((ident, content, rng.random() < 0.3))
                continue
            t.result(ident, content, is_error=rng.random() < 0.2)
            if late and rng.random() < 0.5:
                t.result(*late.pop(0))
        for pending in late:
            t.result(*pending)
        path = t.save(tmp_path, f"r{case}.jsonl", spaced=bool(case % 2))
        for cwd in ("", PROJECT):
            assert spec_path.last_spec_write(path, cwd) == _old_last_spec_write(path, cwd), (case, cwd)


def test_spec_path_reads_the_transcript_through_command_span(tmp_path, monkeypatch):
    """The one reader: what command_span's span gives is what spec_path decides on."""
    t = T()
    t.write(SPECS[0])
    path = t.save(tmp_path)
    seen = []
    real = command_span.transcript_span

    def spy(transcript_path):
        seen.append(transcript_path)
        return real(transcript_path)

    monkeypatch.setattr(command_span, "transcript_span", spy)
    assert spec_path.last_spec_write(path) == SPECS[0]
    assert seen == [path]
    monkeypatch.setattr(command_span, "transcript_span", lambda p: command_span.Span("", "", 0, str(tmp_path / "x")))
    assert spec_path.last_spec_write(path) is None
    assert "open(" not in Path(spec_path.__file__).read_text(encoding="utf-8")


# --- where command_span's rule now decides: shapes the CLI does not write ----------------
def test_a_subagent_record_in_the_main_file_is_not_the_sessions_call(tmp_path):
    """command_span's rule: an isSidechain record is a subagent's own, not the session's call
    (the CLI keeps a subagent's records in subagents/agent-<id>.jsonl; the old parser read
    them as the session's)."""
    t = T()
    t.write(SPECS[0])
    ident = t.use("Write", {"file_path": SPECS[1], "content": "x"})
    t.records[-1]["isSidechain"] = True
    t.result(ident, isSidechain=True)
    path = t.save(tmp_path)
    assert _old_last_spec_write(path) == SPECS[1]
    assert spec_path.last_spec_write(path) == SPECS[0]


def test_command_spans_result_rules_for_shapes_the_cli_does_not_write(tmp_path):
    # one id on two different calls: each call comes back by the first result after it
    t = T()
    t.records.append({"type": "assistant", "cwd": PROJECT, "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "dup", "name": "Write", "input": {"file_path": SPECS[0]}}]}})
    t.result("dup")
    t.records.append({"type": "assistant", "cwd": PROJECT, "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "dup", "name": "Write", "input": {"file_path": SPECS[1]}}]}})
    path = t.save(tmp_path)
    assert _old_last_spec_write(path) == SPECS[1]
    assert spec_path.last_spec_write(path) == SPECS[0]
    # an untyped text block is no text
    t = T()
    t.spec_write(SPECS[0])
    t.call("Bash", {"command": "python3 spec-write.py append"}, [{"text": f"spec-write: append {SPECS[1]}\n"}])
    path = t.save(tmp_path, "t2.jsonl")
    assert _old_last_spec_write(path) == SPECS[1]
    assert spec_path.last_spec_write(path) == SPECS[0]
