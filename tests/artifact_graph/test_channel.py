"""The CLI's hook-output channel as an artifact (P15-L2, plan section 2(e)): `channel:cli-hook-output`,
produced by the CLI alone, declared by the recorded fixture's shapes; its readers derived from the code
that parses its records; its synthesizers held to the fixture's shapes; one parser."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from tests.artifact_graph import check as C
from tests.artifact_graph import pyscan

SHAPES = {
    "attachment/hook_success": {
        "attachment.type": ["string"], "attachment.hookName": ["string"], "attachment.toolUseID": ["string"],
        "attachment.hookEvent": ["string"], "attachment.content": ["string"], "attachment.stdout": ["string"],
        "attachment.stderr": ["string"], "attachment.exitCode": ["number"], "attachment.command": ["string"],
        "attachment.durationMs": ["number"], "type": ["string"], "uuid": ["string"]},
    "attachment/hook_additional_context": {
        "attachment.type": ["string"], "attachment.content": ["array"], "attachment.content[]": ["string"],
        "attachment.hookName": ["string"], "attachment.toolUseID": ["string"], "attachment.hookEvent": ["string"],
        "type": ["string"]},
    "system/stop_hook_summary": {"type": ["string"], "subtype": ["string"], "hookCount": ["number"]},
}

PARSER = '''
    def parse(attachment):
        kind = attachment.get("type")
        if kind == "hook_success":
            return attachment.get("content") or attachment.get("stdout")
        if kind == "hook_additional_context":
            return attachment.get("content")
        return None


    class Span:
        def minted(self):
            return parse(self.attachment)

        def _private(self):
            return self.minted()
'''

READER = '''
    from lib.parse import Span


    def gate(span):
        return span.minted()


    def unrelated(span):
        return span.other()
'''

SYNTH_OK = '''
    def record(tx, text):
        return {"type": "hook_success", "hookName": "UserPromptSubmit", "toolUseID": "t", "hookEvent": "UserPromptSubmit",
                "content": text, "stdout": text, "stderr": "", "exitCode": 0, "command": "c", "durationMs": 1}
'''

SYNTH_MUTATED = '''
    def record(tx, text):
        return {"type": "hook_success", "hookName": "UserPromptSubmit", "toolUseID": "t", "hookEvent": "UserPromptSubmit",
                "content": text, "stdout": text, "stderr": "", "exitCode": "0", "durationMs": 1}
'''


def _tree(tmp_path: Path, files: dict, shapes=SHAPES) -> Path:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))
    if shapes is not None:
        fx = tmp_path / "tests/fixtures/cli"
        (fx / "9.9.9").mkdir(parents=True, exist_ok=True)
        (fx / "CURRENT").write_text("9.9.9\n")
        (fx / "9.9.9/shapes.json").write_text(json.dumps(shapes))
    return tmp_path


def _channel(tree: Path):
    ctx = C._Ctx(C.Map(str(tree)), [], [], [], [], C._tree_files(str(tree)), "scripts/chain.py", [], str(tree))
    ctx._channel()
    return ctx.m.artifacts.get(C.CHANNEL), ctx.m.extra, ctx.m.pending


def _rules(vs) -> list:
    return sorted(v.rule for v in vs)


def test_the_channel_is_produced_by_the_cli_and_declared_by_the_fixture(tmp_path):
    """The artifact exists, kind channel, one producer (cli) whose evidence is the fixture's shapes."""
    a, extra, pending = _channel(_tree(tmp_path, {"hooks/lib/parse.py": PARSER, "hooks/gate.py": READER,
                                                  "hooks/tests/test_gate.py": SYNTH_OK}))
    assert (a.kind, a.producers()) == ("channel", ["cli"])
    assert [w.evidence for w in a.writers] == ["tests/fixtures/cli/9.9.9/shapes.json"]
    assert (extra, pending) == ([], [])


def test_the_readers_are_derived_from_the_parser_and_its_callers(tmp_path):
    """Readers: the parser, the functions of its module that reach it, and each production function
    elsewhere that calls a public one of them; not a function that calls none, and not a test."""
    a, _extra, _pending = _channel(_tree(tmp_path, {
        "hooks/lib/parse.py": PARSER, "hooks/gate.py": READER,
        "hooks/tests/test_gate.py": "def test_it(span):\n    return span.minted()\n"}))
    assert sorted((r.who, r.via) for r in a.readers) == [
        ("hooks/gate.py", "gate"), ("hooks/lib/parse.py", "Span._private"), ("hooks/lib/parse.py", "Span.minted"),
        ("hooks/lib/parse.py", "parse")]


def test_a_synthesizer_whose_shape_differs_from_the_fixture_is_a_violation(tmp_path):
    """C1: a test's hand-built record passes only with the fixture's shape; one with `command` dropped and
    `exitCode` a string is reported, naming both (reported-only until P15-L3 lands: REPORTED_ONLY)."""
    a, extra, pending = _channel(_tree(tmp_path, {"hooks/lib/parse.py": PARSER,
                                                  "hooks/tests/test_gate.py": SYNTH_MUTATED}))
    assert [s.evidence for s in a.synthesizers] == ["hooks/tests/test_gate.py:3"]
    vs = extra + pending
    assert _rules(vs) == ["C1-synth"]
    assert "missing command" in vs[0].message and "exitCode is string, the CLI's is number" in vs[0].message
    assert ("C1-synth" in C.REPORTED_ONLY) == (vs[0] in pending)


def test_production_code_that_builds_a_record_is_a_second_producer(tmp_path):
    """C1: only the CLI produces the channel; production code building a record, even one shaped like
    the CLI's, is a violation that fails the check."""
    _a, extra, _pending = _channel(_tree(tmp_path, {"hooks/lib/parse.py": PARSER, "scripts/fake.py": SYNTH_OK}))
    assert _rules(extra) == ["C1-producer"]


def test_a_key_the_parser_reads_that_the_fixture_lacks_is_a_violation(tmp_path):
    """C2: every key a parser reads exists in the fixture for the record kinds it compares."""
    parser = PARSER.replace('attachment.get("stdout")', 'attachment.get("output")')
    _a, extra, _pending = _channel(_tree(tmp_path, {"hooks/lib/parse.py": parser}))
    assert _rules(extra) == ["C2-key"] and "'output'" in extra[0].message


def test_a_second_parser_is_a_violation(tmp_path):
    """C3: the channel has one parser; a second production function comparing a record's kind is reported."""
    second = 'def other(a):\n    return a.get("content") if a.get("type") == "hook_success" else None\n'
    _a, extra, _pending = _channel(_tree(tmp_path, {"hooks/lib/parse.py": PARSER, "hooks/second.py": second}))
    assert _rules(extra) == ["C3-one-parser"]
    assert "hooks/lib/parse.py#parse" in extra[0].message and "hooks/second.py#other" in extra[0].message


def test_a_missing_fixture_fails_closed(tmp_path):
    """No CURRENT (or no shapes.json for it): the producer's declaration is unreadable, a violation."""
    _a, extra, _pending = _channel(_tree(tmp_path, {"hooks/lib/parse.py": PARSER}, shapes=None))
    assert _rules(extra) == ["C1-producer"] and "unreadable" in extra[0].message


def test_pyscan_reads_the_keys_next_to_a_kind_comparison_only():
    """transcript_key: the literal keys a function reads when it compares a value with a hook-record kind;
    a function that reads keys but compares none is no parser."""
    src = textwrap.dedent('''
        def parse(a):
            if a.get("type") == "hook_additional_context":
                return a["content"]

        def other(a):
            return a.get("content")
    ''')
    recs = [r for r in pyscan.channel_records("hooks/x.py", src) if r["kind"] == "transcript_key"]
    assert sorted((r["function"], r["key"]) for r in recs) == [("parse", "content"), ("parse", "type")]
    assert recs[0]["record_kinds"] == ["hook_additional_context"]
