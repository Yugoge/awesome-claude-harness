"""The recorded CLI fixtures, their shape diff and the upgrade canary's advisory (P15 section 2(d)).

Tests built CLI records by hand, so CLI 2.1.322's change of the hook-output records (plain stdout
became `hook_success`, JSON additionalContext became `hook_additional_context` with a list) passed
every test while `/do` could not end. tests/fixtures/cli/<version>/ holds what the real CLI wrote,
recorded by scripts/cli-fixture-record.sh; these tests keep that recording, its shapes.json and
the CLI in use from drifting apart silently.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "cli"
SHAPES = REPO / "tests" / "cli_shapes.py"
sys.path.insert(0, str(REPO / "tests"))
import cli_shapes  # noqa: E402

sys.path.pop(0)

CURRENT = (FIXTURES / "CURRENT").read_text().strip()
VERSIONS = sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())


def _diff(old, new):
    proc = subprocess.run([sys.executable, str(SHAPES), "diff", str(old), str(new)],
                          capture_output=True, text=True, timeout=60)
    return proc.returncode, proc.stdout.splitlines()


def test_current_names_a_recorded_fixture():
    assert re.fullmatch(r"\d+\.\d+\.\d+\S*", CURRENT), CURRENT
    fixture = FIXTURES / CURRENT
    for name in ("transcript.jsonl", "subagent.jsonl", "shapes.json"):
        assert (fixture / name).is_file(), name
    for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "Stop", "SubagentStop"):
        assert (fixture / "stdin" / f"{event}.json").is_file(), event


@pytest.mark.parametrize("version", VERSIONS)
def test_shapes_json_is_the_shape_of_the_committed_fixture(version):
    fixture = FIXTURES / version
    committed = json.loads((fixture / "shapes.json").read_text())
    assert cli_shapes.diff_shapes(committed, cli_shapes.fixture_shapes(fixture)) == []
    assert _diff(fixture, fixture / "shapes.json") == (0, [])


def test_the_recording_holds_the_hook_record_forms_of_section_2d():
    shapes = json.loads((FIXTURES / CURRENT / "shapes.json").read_text())
    success = shapes["transcript:attachment/hook_success"]
    for key in ("hookName", "toolUseID", "hookEvent", "content", "stdout", "stderr", "exitCode",
                "command", "durationMs"):
        assert f"attachment.{key}" in success, key
    context = shapes["transcript:attachment/hook_additional_context"]
    assert context["attachment.content"] == ["array"] and context["attachment.content[]"] == ["string"]
    assert "attachment.command" not in context
    assert "transcript:system/stop_hook_summary" in shapes
    # SubagentStop's hook_success is written to the subagent's transcript, not the parent's.
    events = {r["attachment"]["hookEvent"] for r in cli_shapes.load_records("attachment/hook_success")}
    assert "SubagentStop" not in events
    sub = cli_shapes.load_records("subagent:attachment/hook_success")
    assert "SubagentStop" in {r["attachment"]["hookEvent"] for r in sub}
    for event in ("Stop", "SubagentStop"):
        for key in ("effort", "background_tasks", "session_crons", "last_assistant_message"):
            assert f"{key}" in shapes[f"stdin:{event}"], (event, key)
    assert "agent_transcript_path" in shapes["stdin:SubagentStop"]


def test_the_diff_is_empty_on_itself(tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(FIXTURES / CURRENT, copy)
    assert _diff(FIXTURES / CURRENT, copy) == (0, [])


def test_the_diff_names_a_dropped_command_and_a_string_exit_code(tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(FIXTURES / CURRENT, copy)
    lines = []
    for rec in (json.loads(l) for l in (copy / "transcript.jsonl").read_text().splitlines()):
        if cli_shapes.record_kind(rec) == "attachment/hook_success":
            rec["attachment"].pop("command")
            rec["attachment"]["exitCode"] = str(rec["attachment"]["exitCode"])
        lines.append(json.dumps(rec))
    (copy / "transcript.jsonl").write_text("".join(l + "\n" for l in lines))
    rc, out = _diff(FIXTURES / CURRENT, copy)
    assert rc == 1, out
    assert "transcript:attachment/hook_success: removed key attachment.command" in out, out
    assert ("transcript:attachment/hook_success: type of attachment.exitCode changed "
            "['number'] -> ['string']") in out, out
    assert len(out) == 2, out


def test_the_diff_names_added_and_removed_kinds_and_keys():
    old = {"a": {"x": ["string"]}, "gone": {"y": ["number"]}}
    new = {"a": {"x": ["string"], "z": ["array"]}, "new": {"y": ["number"]}}
    assert cli_shapes.diff_shapes(old, new) == ["removed kind gone", "added kind new", "a: added key z"]


def test_shape_is_three_levels_deep_with_list_items_marked():
    rec = {"type": "attachment", "attachment": {"type": "hook_x", "content": ["s"],
                                                "deep": {"deeper": {"deepest": 1}}}}
    shape = cli_shapes.record_shape(rec)
    assert shape["attachment.content[]"] == {"string"}
    assert shape["attachment.deep.deeper"] == {"object"}
    assert "attachment.deep.deeper.deepest" not in shape
    assert cli_shapes.record_kind(rec) == "attachment/hook_x"
    summary = cli_shapes.load_records("system/stop_hook_summary")[0]  # a recorded record, not a hand-built one
    assert cli_shapes.record_kind(summary) == "system/stop_hook_summary"


def test_the_loader_fixture_returns_fresh_recorded_records(cli_record):
    first = cli_record("attachment/hook_success")
    assert first and all(r["attachment"]["type"] == "hook_success" for r in first)
    first[0]["attachment"]["content"] = "changed"
    assert cli_record("attachment/hook_success")[0]["attachment"]["content"] != "changed"
    assert cli_record("stdin:Stop")["hook_event_name"] == "Stop"
    with pytest.raises(KeyError):
        cli_record("attachment/no_such_kind")


def _installed_cli_version():
    exe = shutil.which("claude")
    if exe is None:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (out.split() or [None])[0]


def test_an_installed_cli_other_than_current_has_its_fixture_committed():
    """A CLI upgrade fails here, where a CLI is installed, until its recording is committed.

    Where no CLI is installed (CI) the version cannot change, and shapes.json is what holds.
    """
    version = _installed_cli_version()
    if version is None or version == CURRENT:
        return
    fixture = FIXTURES / version
    assert fixture.is_dir(), (
        f"claude CLI {version} is installed, tests/fixtures/cli/CURRENT is {CURRENT}: record it with "
        f"bash scripts/cli-fixture-record.sh and commit tests/fixtures/cli/{version}")
    changes = cli_shapes.diff_shapes(cli_shapes.fixture_shapes(FIXTURES / CURRENT),
                                     cli_shapes.fixture_shapes(fixture))
    assert not changes, (f"CLI {version} records differ from {CURRENT}; point CURRENT at {version} and "
                         f"update every reader and synthesizer of them: {changes}")


def test_the_fixtures_hold_no_prompt_text_path_or_id_of_the_recording_machine():
    # The recorder's two prompts, and this checkout's path.
    no_private_text = [str(REPO), "Reply with", "single word"]
    uuid = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    for f in FIXTURES.rglob("*"):
        if not f.is_file():
            continue
        text = f.read_text()
        for needle in no_private_text:
            assert needle not in text, (f, needle)
        assert not uuid.search(text), f
        assert not re.search(r"(toolu|msg|req)_[0-9A-Za-z]{6,}|[0-9a-f]{16}", text), f
        # Every path starts at a placeholder (<HOME>, <CWD>, <TMP>), none at the machine's root.
        assert not re.search(r'"/[^"\s]', text), f


def _canary(tmp_path, cli_version):
    home = tmp_path / "home"
    home.mkdir()
    for entry in REPO.iterdir():
        if entry.name not in (".git", "venv"):
            (home / entry.name).symlink_to(entry)
    (home / "venv" / "bin").mkdir(parents=True)
    (home / "venv" / "bin" / "activate").write_text("")
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "claude").write_text(f"#!/bin/sh\necho '{cli_version} (Claude Code)'\n")
    (stub / "claude").chmod(0o755)
    root = tmp_path / "host"
    root.mkdir()
    (tmp_path / "user").mkdir()
    env = {"PATH": f"{stub}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path / "user"),
           "CLAUDE_HOME": str(home), "CLAUDE_STATE_DIR": str(tmp_path / "state"), "TMPDIR": str(tmp_path)}
    proc = subprocess.run(["bash", str(home / "scripts" / "canary-verify.sh"), "--host-root", str(root)],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout, [l for l in proc.stderr.splitlines() if "re-record" in l]


def test_the_canary_advises_a_re_record_on_a_cli_version_mismatch(tmp_path):
    rc, out, lines = _canary(tmp_path, "9.9.999")
    assert out == ""
    assert lines == [f"canary-verify[ADVISORY]: claude CLI is 9.9.999 but tests/fixtures/cli/CURRENT is {CURRENT}: "
                     "re-record with bash scripts/cli-fixture-record.sh and commit the fixture"], lines


def test_the_canary_is_silent_on_a_matching_cli_version(tmp_path):
    rc, out, lines = _canary(tmp_path, CURRENT)
    assert out == "" and lines == []
