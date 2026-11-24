"""P5 review M: the owner mistypes the /close or /push argument; nobody is asked, and the owner types it again.

Each replay types the command with an argument that names nothing: /close of a ticket path of another
id, which does not exist (drivers/do.py `then=close mistype=1`), and /push of a remote the toy does not
have (drivers/push.py `after=none token=owner2 remote=upstrem`). Nobody is asked (2026-11-19):

* /close's Task-id resolution ends on its NO_TARGET: line naming the task, its Stop passes (the Stop gate's
  no_target_end), and the owner types `/close <the /do task>`; that run's Stop passes, or, while this tree lacks
  P3's disposition or P4's close rating, is held by their instrument failures alone; the gate run on the replay's
  own transcript, with stand-ins of their signatures, decides on the /do task and passes once that task's
  disposition passes;
* /push's Step 5 refusal of the unknown remote is reported with the action it names (push to origin), nothing
  is pushed, and its Stop passes (the typed name is no remote of the repository and Step 5 refused it);
* no AskUserQuestion is made but the close rating, and no other block or hook error is met.
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys

import pytest

from tests.replay import suite
from tests.replay.drivers.close import CL
from tests.replay.drivers.push import PushSteps

PUSH_STEPS = PushSteps(open(os.path.join(suite.REPO, "commands", "push.md"), encoding="utf-8").read())

CLOSE = suite.Scenario("/close mistyped", "do", (("then", "close"), ("mistype", "1")), ("do", "close"), 110)
PUSH = suite.Scenario("/push mistyped", "push", (("after", "none"), ("token", "owner2"), ("remote", "upstrem")),
                      ("push",), 90)
CASES = [pytest.param(scn, s, id=f"{scn.pipeline}-{s}", marks=pytest.mark.replay(suite.replay_key(scn, s), scn.cost))
         for scn in (CLOSE, PUSH) for s in suite.SETTINGS]
GATE = os.path.join(suite.REPO, "hooks", "stop-command-gate.py")
# The phases the /close Stop calls into that this tree may lack, and the gap their absence leaves.
WAITS = {"P3": (lambda: "\ndef disposition(" in _text("scripts/resolve-dev-artifact-chain.py"),
                re.compile(r"gate instrument failure: NameError: name 'disposition' is not defined")),
         "P4": (lambda: os.path.isfile(os.path.join(suite.REPO, "hooks", "lib", "close_rating.py")),
                re.compile(r"gate instrument failure: ModuleNotFoundError: No module named 'lib\.close_rating'"))}
# The gate on one transcript, P3's disposition and P4's close rating replaced by stand-ins of their
# signatures: the disposition's lines name the task it is asked about, or none, by what the file
# stand-in-disposition in the project says ("gap" or "pass"). It reads that file as the real disposition reads its
# facts, so the gate's kept result notices a changed fact (a rewritten file), not a swapped function.
STAND_INS = r"""
import importlib.util, json, sys, types
spec = importlib.util.spec_from_file_location("gate_on_the_replay", sys.argv[1])
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
rating = types.ModuleType("lib.close_rating")
rating.rating_required = lambda span, task_id: False
rating.rating_asked = lambda transcript_path, task_id: True
sys.modules["lib.close_rating"] = rating
def lines(root, task, stage):
    with open(sys.argv[5] + "/stand-in-disposition") as fh:
        return [f"{stage} {task}: the stand-in disposition"] if fh.read() == "gap" else []
gate._SCRIPTS["scripts/resolve-dev-artifact-chain.py"] = types.SimpleNamespace(disposition_lines=lines)
payload = {"session_id": sys.argv[2], "transcript_path": sys.argv[3], "cwd": sys.argv[5], "hook_event_name": "Stop"}
span = gate.command_span.active_span(sys.argv[3])
print(json.dumps({"command": span.command, "args": span.args, "decision": gate.decide(payload)}))
"""


def _text(rel: str) -> str:
    with open(os.path.join(suite.REPO, rel)) as fh:
        return fh.read()


def _blocked(ev: dict) -> str:
    return "\n".join((h.get("stderr") or "") for h in ev["hooks"] if h["verdict"] == "block")


def _gaps(text: str) -> list[str]:
    return [line[2:] for line in text.splitlines() if line.startswith("- ")]


def _on_the_transcript(r, root: str, disposition: str) -> dict:
    """The gate's decision on the replay's /close session transcript with P3's and P4's stand-ins, in a
    process of its own, the project an empty directory (the typed path is absent there, as in the toy)."""
    paths = glob.glob(os.path.join(r.run_dir, "transcripts", "*", "*.jsonl"))
    assert len(paths) == 1, paths
    sid = os.path.basename(paths[0])[:-len(".jsonl")]
    env = {**os.environ, "CLAUDE_PROJECT_DIR": root, "CLAUDE_CODE_ENABLE_TODO_TOOLS": "1",
           "CLAUDE_CODE_ENABLE_TASKS": "false",
           "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("CLAUDE_COMPAT_RUNTIME", None)
    with open(os.path.join(root, "stand-in-disposition"), "w") as fh:
        fh.write(disposition)
    done = subprocess.run([sys.executable, "-c", STAND_INS, GATE, sid, paths[0], disposition, root], cwd=root,
                          capture_output=True, text=True, env=env, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.parametrize("scn,settings", CASES)
def test_a_mistyped_argument_corrected_in_the_turn_is_checked_on_the_corrected_value(replays, tmp_path, scn, settings):
    r = replays.get(suite.replay_key(scn, settings))
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert not r.hook_errors, "a hook error:\n" + r.explain()
    events = r.hook_events()
    typed = [ev["label"] for ev in events if ev["event"] == "UserPromptSubmit"]
    asked = [ev["label"] for ev in events if ev["event"] == "PreToolUse" and ev.get("tool") == "AskUserQuestion"]
    stops = {ev["label"]: ev for ev in events if ev["event"] == "Stop"}
    if scn is PUSH:
        assert typed == ["/push typed"] and asked == [], (typed, asked)
        assert [f["value"] for f in r.facts if f.get("key") == "push refusal"] == [
            {"step": PUSH_STEPS.push, "action": "push to origin", "answer": None}], r.explain()
        pushes = [f["value"] for f in r.facts if f.get("key") == "push"]
        assert [p["rc"] for p in pushes] == [1] and "remote 'upstrem' not found" in pushes[0]["output"], pushes
        assert not pushes[-1]["pushed"], pushes[-1]
        assert list(stops) == ["/push Stop"] and not r.blocks, r.explain()
        return
    tid = (r.terminal("do") or {}).get("task")
    made = r.fact("close typed") or {}
    assert tid and made.get("retyped") == tid and made.get("typed", "").startswith("docs/dev/ticket-"), (tid, made)
    assert made["line"].startswith("NO_TARGET: ") and made["still_blocked"] is False, made
    typo = re.search(r"ticket-(.+)\.md$", made["typed"]).group(1)
    # with P4's close rating in the tree, close.md's Step 4 asks the rating; nothing else is asked
    rating = [f"/close Step {CL.rating} AskUserQuestion"] if WAITS["P4"][0]() else []
    assert typo != tid and asked == rating, (typo, asked)
    assert [t for t in typed if t.startswith("/close ")] == ["/close typed", "/close typed again"], typed
    assert set(stops) == {"/do Stop", "/close Stop (no task)", "/close Stop"} and not _blocked(stops["/do Stop"]), \
        r.explain()
    assert not _blocked(stops["/close Stop (no task)"]), r.explain()
    refused = {(b["step"], b["hook"]) for b in r.blocks} - {("/close Stop", "hooks/stop-launch.py")}
    assert not refused, r.explain()
    waiting = sorted(phase for phase, (present, _rx) in WAITS.items() if not present())
    held = _blocked(stops["/close Stop"])
    if waiting:  # P3's disposition or P4's close rating not in this tree: their instrument failures alone
        gaps = _gaps(held)
        assert held.startswith("COMMAND_GATE /close: not complete\n") and gaps, held
        assert all(any(WAITS[phase][1].fullmatch(gap) for phase in waiting) for gap in gaps), held
    else:
        assert not held and r.reached(), r.explain()
    held = _on_the_transcript(r, str(tmp_path), "gap")
    assert held["command"] == "close" and held["args"] == tid, held
    assert held["decision"] == [2, f"COMMAND_GATE /close: not complete\n- close {tid}: the stand-in disposition\n"
                                   "Finish the gaps above. What a rule refuses is reported as refused, with the "
                                   "hook's output; nobody is asked about it.\n"], held
    assert typo not in held["decision"][1]
    assert _on_the_transcript(r, str(tmp_path), "pass")["decision"] == [0, ""]
