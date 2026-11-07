"""A block is its hook, its step and the first line of its refusal (P1b acceptance 4).

hookrun keeps a hook's output tail; for a long refusal that tail is the echoed
command, which differs between the base kit and the working tree. The replay
keeps the refusal's head too, records its normalised first line ("first"), and a
kept-only driver passes a block whose hook, step and first line its base run
recorded. A blocks.json from before "first" still reads, by its whole text.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from tests.replay import hookrun, replay, sandbox
from tests.replay.drivers.dev import KeptOnly
from tests.replay.drivers.overnight import NormKeptOnly
from tests.replay.pipeline import Deviations

FIRST = "BLOCKED: test-policy — UNRESOLVED dynamic_command_head:"
REFUSE = r'''
import json, sys
cmd = json.load(sys.stdin)["tool_input"]["command"]
sys.stderr.write("BLOCKED: test-policy — UNRESOLVED dynamic_command_head:" + cmd.split(";")[0] + "\n")
sys.stderr.write("Command: " + cmd + "\n")
sys.stderr.write("REASON: every boundary must be provably inert.\n")
sys.exit(2)
'''
DENY = r'''
import json, sys
cmd = json.load(sys.stdin)["tool_input"]["command"]
reason = "BLOCKED: json-policy refuses " + cmd.split(";")[0] + "\nCommand: " + cmd
print(json.dumps({"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason": reason}}))
'''
STEP = "/commit Step 5 Bash plan 0"
DEVS = Deviations([("/commit Step 5 Bash plan *",
                    replay.Deviation("hooks/refuse.py", "every boundary must be provably inert", "test"))])
KEPT_ONLY = {"dev.KeptOnly": lambda kept, rp: KeptOnly(DEVS, kept),
             "overnight.NormKeptOnly": lambda kept, rp: NormKeptOnly(DEVS, kept, rp)}


def long_command(head: str, filler: str) -> str:
    return f"{head}; " + " && ".join(f"echo {filler}-{i}" for i in range(800))


@pytest.fixture
def kit(tmp_path) -> Path:
    hooks = tmp_path / "kit" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "refuse.py").write_text(REFUSE, encoding="utf-8")
    (hooks / "deny.py").write_text(DENY, encoding="utf-8")
    return tmp_path / "kit"


def settings(kit: Path, hook: str = "refuse.py") -> dict:
    return {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": f"{sys.executable} {kit}/hooks/{hook}"}]}]}}


def make_replay(tmp_path: Path, name: str, kit: Path) -> replay.Replay:
    root = tmp_path / name
    home = root / "home"
    lay = sandbox.Layout("scratch", str(root), str(home), str(home / ".claude"), str(home / "toyproj"),
                         str(home / "toyproj-origin.git"), str(root / "state"), str(root / "out"),
                         str(root / "trace"), str(root / "markers"))
    for d in (lay.harness, lay.project, lay.state):
        os.makedirs(d, exist_ok=True)
    spath = root / "settings.json"
    spath.write_text(json.dumps(settings(kit)), encoding="utf-8")
    return replay.Replay(lay, str(spath), pipeline="kept-test", settings_label="shipped")


def plan_call(rp: replay.Replay, command: str, devs) -> replay.Call:
    s = rp.session(start=None)
    return s.main.tool("Bash", {"command": command}, perform=lambda: {"stdout": "", "stderr": ""},
                       label=STEP, deviation=devs.at(STEP))


def base_run(tmp_path: Path, kit: Path, command: str) -> str:
    """The base kit's run: every declared deviation passes. Returns its blocks.json."""
    rp = make_replay(tmp_path, "base", kit)
    call = plan_call(rp, command, DEVS)
    assert not call.blocked and rp.blocks[0]["passed_by_deviation"]
    rp.finish(0.0)
    return os.path.join(rp.layout.out, "blocks.json")


def test_hookrun_keeps_the_refusals_head_beside_its_tail(kit):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONDONTWRITEBYTECODE": "1"}
    command = long_command("ARTIFACT_CHAIN=$(resolve)", "tree")
    rec = hookrun.run_event(settings(kit), "PreToolUse", {"tool_name": "Bash", "tool_input": {"command": command}},
                            env, str(kit))
    r = rec["hooks"][0]
    assert r["verdict"] == "block" and r["how"] == "exit2" and r["hook"] == "hooks/refuse.py"
    # the tail is kept as before: the model is given the same text
    assert len(r["stderr"]) == hookrun.TAIL and r["stderr"].endswith("provably inert.\n")
    assert not hookrun.refusal(r).startswith("BLOCKED")
    # the head is kept too, from the uncut output
    assert hookrun.refusal_first(r) == FIRST + "ARTIFACT_CHAIN=$(resolve)"
    assert len(r["refusal_head"]) == hookrun.HEAD and r["refusal_head"].startswith(FIRST)

    # a first line longer than HEAD is kept whole
    head = "X=" + "y" * (2 * hookrun.HEAD)
    rec = hookrun.run_event(settings(kit), "PreToolUse",
                            {"tool_name": "Bash", "tool_input": {"command": long_command(head, "tree")}}, env, str(kit))
    assert hookrun.refusal_first(rec["hooks"][0]) == FIRST + head

    # a JSON decision: the head is the reason's, parsed from the whole stdout
    rec = hookrun.run_event(settings(kit, "deny.py"), "PreToolUse",
                            {"tool_name": "Bash", "tool_input": {"command": command}}, env, str(kit))
    r = rec["hooks"][0]
    assert r["verdict"] == "block" and r["how"] == "json-deny" and len(r["stdout"]) == hookrun.TAIL
    assert hookrun.refusal_first(r) == "BLOCKED: json-policy refuses ARTIFACT_CHAIN=$(resolve)"

    # an allowed run keeps no head
    rec = hookrun.run_event({"hooks": {"PreToolUse": [{"hooks": [{"command": "true"}]}]}}, "PreToolUse",
                            {"tool_name": "Bash"}, env, str(kit))
    assert rec["hooks"][0]["verdict"] == "ok" and "refusal_head" not in rec["hooks"][0]


@pytest.mark.parametrize("kind", sorted(KEPT_ONLY))
def test_a_long_refusal_with_another_tail_is_kept_by_its_first_line(tmp_path, kit, kind):
    path = base_run(tmp_path, kit, long_command("ARTIFACT_CHAIN=$(resolve)", "base"))
    with open(path) as fh:
        base = json.load(fh)["blocks"][0]
    assert base["first"] == FIRST + "ARTIFACT_CHAIN=$(resolve)"
    kept = replay.kept_list(path)
    assert kept == [["hooks/refuse.py", STEP, base["first"]]]

    rp = make_replay(tmp_path, "tree", kit)
    call = plan_call(rp, long_command("ARTIFACT_CHAIN=$(resolve)", "tree"), KEPT_ONLY[kind](kept, rp))
    b = rp.blocks[0]
    assert b["text"] != base["text"] and b["first"] == base["first"]   # the tails differ, the first lines match
    assert not call.blocked and b["passed_by_deviation"] and rp.deviations[0]["step"] == STEP

    # by the whole recorded text (the identity before "first") the same block would be new
    rp2 = make_replay(tmp_path, "tree-by-text", kit)
    call = plan_call(rp2, long_command("ARTIFACT_CHAIN=$(resolve)", "tree"),
                     KEPT_ONLY[kind]([["hooks/refuse.py", STEP, base["text"]]], rp2))
    assert call.blocked and not rp2.blocks[0]["passed_by_deviation"]


@pytest.mark.parametrize("kind", sorted(KEPT_ONLY))
def test_another_first_line_is_a_new_block(tmp_path, kit, kind):
    kept = replay.kept_list(base_run(tmp_path, kit, long_command("ARTIFACT_CHAIN=$(resolve)", "base")))
    rp = make_replay(tmp_path, "tree", kit)
    call = plan_call(rp, long_command("REPOSITORY_PLAN=$(plan)", "base"), KEPT_ONLY[kind](kept, rp))
    b = rp.blocks[0]
    assert b["first"] == FIRST + "REPOSITORY_PLAN=$(plan)"
    assert call.blocked and not b["passed_by_deviation"] and rp.deviations == []


def test_an_old_blocks_json_still_loads(tmp_path, kit, capsys):
    """Written before "first" (and before "step_norm"): its whole text stands in, and kept_list says so."""
    path = base_run(tmp_path, kit, "ARTIFACT_CHAIN=$(resolve); echo short")
    with open(path) as fh:
        data = json.load(fh)
    for b in data["blocks"]:
        del b["first"], b["step_norm"]
    old = tmp_path / "old-blocks.json"
    old.write_text(json.dumps(data), encoding="utf-8")

    said: list = []
    kept = replay.kept_list(str(old), warn=said.append)
    assert kept == [["hooks/refuse.py", STEP, data["blocks"][0]["text"]]]
    assert len(said) == 1 and "predate" in said[0]
    replay.kept_list(json.loads(old.read_text()))           # the loaded content reads the same way
    assert "predate" in capsys.readouterr().err             # by default, on stderr
    assert replay.kept_list(path, warn=said.append) and len(said) == 1   # a current one says nothing

    # a short refusal's whole text is the same on both runs: the old list still keeps it
    rp = make_replay(tmp_path, "tree", kit)
    call = plan_call(rp, "ARTIFACT_CHAIN=$(resolve); echo short", KeptOnly(DEVS, kept))
    assert not call.blocked and rp.blocks[0]["passed_by_deviation"]
