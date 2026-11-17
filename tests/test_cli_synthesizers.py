"""Every CLI record the tests and the replay synthesize has the shape the installed CLI records (P15 L3).

The replay harness and the hook tests below wrote CLI transcript records by hand, so the records they
read could drift from the CLI's (CLI 2.1.322 moved plain hook stdout to hook_success, and no test
noticed). They now build each record from the recorded fixture (tests/fixtures/cli, through
tests/cli_shapes.py synthesize), filling values only. These tests drive each synthesizer, read back
what it wrote, and hold every record to the fixture's shape of its kind: a key renamed in a
synthesizer is a key the CLI does not record, and fails here (or raises in synthesize)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from tests import cli_shapes  # noqa: E402
from tests.replay import replay  # noqa: E402


def _module(rel: str):
    spec = importlib.util.spec_from_file_location(f"_synth_{Path(rel).stem}", REPO / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _records(*paths: Path) -> list:
    return [json.loads(line) for path in paths for line in path.read_text().splitlines() if line.strip()]


def _assert_recorded_shapes(records: list) -> None:
    assert records, "the synthesizer wrote no record"
    problems = [p for rec in records for p in cli_shapes.check_record(rec)]
    assert problems == [], problems


def test_check_record_names_a_renamed_key_and_synthesize_refuses_an_unrecorded_one():
    record = cli_shapes.synthesize("attachment/hook_success", attachment__content="x")
    assert cli_shapes.check_record(record) == []
    record["attachment"]["contents"] = record["attachment"].pop("content")
    assert cli_shapes.check_record(record) == ["attachment/hook_success: key not recorded: attachment.contents"]
    with pytest.raises(KeyError):
        cli_shapes.synthesize("attachment/hook_success", attachment__contents="x")
    with pytest.raises(KeyError):
        cli_shapes.synthesize("attachment/hook_additional_context", attachment__command="command hook")


def test_every_recorded_form_a_synthesizer_uses_is_in_the_fixture():
    for kind, variants in cli_shapes.VARIANTS.items():
        for variant in variants:
            assert cli_shapes.check_record(cli_shapes.synthesize(kind, variant)) == [], (kind, variant)
    for kind in ("subagent:assistant", "subagent:user"):
        for variant in ("tool_use",) if kind.endswith("assistant") else ("tool_result",):
            assert cli_shapes.synthesize(kind, variant)["isSidechain"] is True


def _hook(stdout: str, matcher=None) -> dict:
    return {"hook": "h.py", "matcher": matcher, "rc": 0, "verdict": "ok", "how": "", "ms": 12,
            "stdout": stdout, "stderr": "", "command": "python3 h.py", "timeout": 60}


def test_the_replay_writes_hook_output_in_the_recorded_forms(tmp_path):
    """Session._context, the one writer of hook output in the replay: plain UserPromptSubmit stdout is a
    hook_success record (CLI 2.1.322 on), a JSON additionalContext a hook_additional_context record whose
    content is a list; a SubagentStart's JSON context goes to the agent's transcript."""
    session = object.__new__(replay.Session)
    session.rp = SimpleNamespace(layout=SimpleNamespace(project=str(tmp_path / "project")))
    # the typed prompt's record precedes its hooks' (a hook record always has a parent)
    session.sid, session.tdir, session.parent, session._agent_parent = "s1", str(tmp_path / "t"), "u0", {"a1": "u1"}
    session.tpath = str(tmp_path / "t" / "s1.jsonl")
    plain = "[/do] task-id minted: 20261117-010000\n"
    context = json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "ctx"}})
    assert session._context(SimpleNamespace(event="UserPromptSubmit", hooks=[_hook(plain), _hook(context)])) \
        == "[/do] task-id minted: 20261117-010000\nctx"
    start = json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": "debate"}})
    assert session._context(SimpleNamespace(event="SubagentStart", hooks=[_hook(start)]), "a1") == "debate"
    main, agent = _records(Path(session.tpath)), _records(Path(session.agent_tpath("a1")))
    _assert_recorded_shapes(main + agent)
    assert [(r["attachment"]["type"], r["attachment"]["content"]) for r in main] == [
        ("hook_success", "[/do] task-id minted: 20261117-010000"), ("hook_additional_context", ["ctx"])]
    assert main[0]["attachment"]["command"] == "command hook 1" and "command" not in main[1]["attachment"]
    assert [(r["attachment"]["type"], r["agentId"], r["isSidechain"]) for r in agent] == [
        ("hook_additional_context", "a1", True)]


def test_the_stop_gate_tests_transcript_has_the_recorded_shapes(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    module = _module("hooks/tests/test_stop_command_gate.py")
    tx = module.TX(tmp_path / "s.jsonl")
    tx.typed("hello")
    tx.command("do", "x", context="[/do] task-id minted: 20261117-010000\n", body="the body")
    tx.command("dev")
    tx.tool("Write", {"file_path": "a", "content": "x"}, ok=False, extra={"toolUseResult": {"id": "c", "recurring": True}})
    tx.tool("Write", {"file_path": "a", "content": "x"}, sidechain=True)
    tx.ask("yes")
    tx.say("done")
    tx.todos([{"content": "a"}], 1)
    tx.dispatch("20261117-010000")
    _assert_recorded_shapes(_records(tx.path))


def test_the_requirement_round_tests_transcript_has_the_recorded_shapes(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    module = _module("hooks/tests/test_requirement_round.py")
    tx = module.TX(tmp_path / "s.jsonl")
    tx.command("dev", context="DEV_SESSION_ID pre-initialized by hook: dev-1\n")
    tx.tool("Read", {"file_path": "a"}, ok=False)
    tx.tool("Read", {"file_path": "a"}, ok=None, sidechain=True)
    tx.dispatch("ba", ["docs/x.json"])
    _assert_recorded_shapes(_records(tx.path))


def test_the_obligation_terminal_fixture_records_have_the_recorded_shapes():
    module = _module("hooks/tests/_fixtures_obligation_terminal.py")
    _assert_recorded_shapes([module.user_record("/dev x"), module.agent_dispatch_record("toolu_1", "p")])


def test_the_late_repair_transcript_has_the_recorded_shapes(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    from tests import _late_repair_fixtures as late
    late.declare_stage_dispatches(tmp_path / "project", "20261117-010000")
    _assert_recorded_shapes(_records(*(tmp_path / "config").rglob("*.jsonl")))


def test_the_do_close_route_transcript_has_the_recorded_shapes(tmp_path):
    module = _module("tests/test_do_partly_failed_close_route.py")
    path = module.transcript(tmp_path / "s.jsonl", tmp_path, ["src/a.py", "src/b.py"])
    _assert_recorded_shapes(_records(Path(path)))


def test_the_disposition_tests_records_have_the_recorded_shapes():
    module = _module("tests/test_disposition.py")
    doc = module.ob("20261117-010000", "dev", "dev", "singular", [])
    _assert_recorded_shapes([module.typed("do", "x"), module.minted(), module.dispatch("toolu_1", "dev", doc)])


def test_the_live_arming_world_has_the_recorded_shapes(tmp_path):
    module = _module("tests/replay/test_live_arming.py")
    world = module.World(tmp_path)
    _assert_recorded_shapes(_records(*world.transcripts.values()))
