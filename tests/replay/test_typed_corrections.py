"""P5 review M: the owner mistypes the /close or /push argument and corrects it in the same turn.

Each replay types the command with an argument that names nothing: /close of a ticket path of another
id, which does not exist (drivers/do.py `then=close mistype=1`), and /push of a remote the toy does not
have (drivers/push.py `after=none token=owner2 remote=upstrem`: two sessions' push-gate tokens name
HEAD, so one is left after push.sh consumes the other). The main agent asks in the turn (close.md's
Task-id resolution, awaiting-input cause (iii); push.md's Refusals rule over push.sh's "remote
'upstrem' not found"), the owner picks the corrected value (the /do task's id; origin), and the work is
done on it. With the tree's settings ("shipped") and armed:

* the /push Stop passes, a token still naming HEAD, and /push reaches its terminal (origin's branch is
  HEAD), with no block;
* the /close Stop passes, or, while this tree lacks P3's disposition or P4's close rating, is held by
  their instrument failures alone (waiting on P3/P4); the gate run on the replay's own transcript, with
  stand-ins of their signatures, decides on the /do task and never on the typed id, and passes once
  that task's disposition passes;
* each replay asks once and meets no other block and no hook error.
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
# signatures: the disposition's lines name the task it is asked about (argv[4]: "gap") or none ("pass").
STAND_INS = r"""
import importlib.util, json, sys, types
spec = importlib.util.spec_from_file_location("gate_on_the_replay", sys.argv[1])
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
rating = types.ModuleType("lib.close_rating")
rating.rating_required = lambda span, task_id: False
rating.rating_asked = lambda transcript_path, task_id: True
sys.modules["lib.close_rating"] = rating
lines = lambda root, task, stage: [f"{stage} {task}: the stand-in disposition"] if sys.argv[4] == "gap" else []
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
           "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("CLAUDE_COMPAT_RUNTIME", None)
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
        assert typed == ["/push typed"] and asked == ["/push Step 5 AskUserQuestion"], (typed, asked)
        assert [f["value"] for f in r.facts if f.get("key") == "push refusal"] == [
            {"step": "Step 5", "action": "push to origin", "answer": "push to origin"}], r.explain()
        pushes = [f["value"] for f in r.facts if f.get("key") == "push"]
        assert [p["rc"] for p in pushes] == [1, 0] and "remote 'upstrem' not found" in pushes[0]["output"], pushes
        assert pushes[-1]["pushed"] and pushes[-1]["origin_equals_head"], pushes[-1]
        assert any("/agentic-commit/push/" in p for left in pushes[-1]["left"].values() for p in left), pushes[-1]
        assert list(stops) == ["/push Stop"] and not r.blocks, r.explain()
        assert r.reached(), r.explain()
        return
    tid = (r.terminal("do") or {}).get("task")
    made = r.fact("close typed") or {}
    assert tid and made.get("answer") == tid and made.get("typed", "").startswith("docs/dev/ticket-"), (tid, made)
    typo = re.search(r"ticket-(.+)\.md$", made["typed"]).group(1)
    assert typo != tid and asked == ["/close Task-id resolution AskUserQuestion"], (typo, asked)
    assert set(stops) == {"/do Stop", "/close Stop"} and not _blocked(stops["/do Stop"]), r.explain()
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
    assert held["command"] == "close" and held["args"] == made["typed"], held
    assert held["decision"] == [2, f"COMMAND_GATE /close: not complete\n- close {tid}: the stand-in disposition\n"
                                   "Finish the gaps above. Ask with AskUserQuestion only for a real decision the "
                                   "user must make.\n"], held
    assert typo not in held["decision"][1]
    assert _on_the_transcript(r, str(tmp_path), "pass")["decision"] == [0, ""]
