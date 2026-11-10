"""P4 acceptance 5, its hook-rejection case: a hook refuses a /commit step and the main agent asks one question.

drivers/commit.py variant `waits` (the owner's world: settings_filter_world). The tree's own refusal on Phase 8's
commit: pretool-bash-safety.sh's commit guard, `unregistered-settings-filter` (the project keeps settings.json
under the claude-settings filter, this clone never registered it, the owner has a local edit). It runs before any
/do or /allow bypass, so the remedy it names is the command the owner runs. The replay is strict: the one block is
that refusal, no deviation passes anything, no hook errors. The main agent asks one Authorize question in the turn
(commands/commit.md Step 7 "A hook rejection") naming the hook, the operation and the exact refused command, with
the hook's output; the orchestrator gate allows it; the owner's answer runs the named remedy and Steps 5-7 land
the commit. The Task question before it and the Flags question of the later `/commit --auto --force` are the
same run's other A5 cases.
"""
from __future__ import annotations

import os

import pytest

from tests.replay import suite

WAITS = suite.Scenario("/commit waits (hook refusal)", "commit", (("variant", "waits"),), ("dev", "commit"), 240)
KEY = suite.replay_key(WAITS, "armed")
STEP = "agent:changelog-analyst Bash stage and commit 0"
REFUSAL = "BLOCKED: unregistered-settings-filter"


def _questions(r) -> list:
    return [f["value"] for f in r.facts if f.get("key") == "commit question"]


@pytest.mark.replay(KEY, WAITS.cost)
def test_a5_hook_refusal_under_commit_is_one_authorize_question(replays):
    r = replays.get(KEY)
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    # The one block: the tree's refusal of Phase 8's commit, never passed by a deviation.
    assert [(b["hook"], b["step"], b["first"].split(" —")[0], b["passed_by_deviation"]) for b in r.blocks] == [
        ("hooks/pretool-bash-safety.sh", STEP, REFUSAL, False)], r.explain()
    assert not r.summary.get("blocks_passed") and not r.summary.get("deviations"), r.explain()
    assert not r.hook_errors, r.explain()

    asked = _questions(r)
    assert [q["header"] for q in asked] == ["Task", "Authorize", "Flags"], r.explain()
    assert not any(q["blocked"] for q in asked), r.explain()
    auth = asked[1]
    task = asked[0]["answer"]
    head = auth["question"].split("\n")[0]
    assert head.startswith("pretool-bash-safety.sh refused `git commit` in ") and head.endswith(
        f" for task {task}: authorize it?"), head
    assert " commit -F " in head, head  # the exact command refused
    assert REFUSAL in auth["question"] and "Run scripts/bootstrap in " in auth["question"], auth["question"]
    assert auth["options"] == ["Authorize it", "Do not authorize"] and auth["answer"] == "Authorize it", auth
    # The authorizing option names the exact command the owner runs: the remedy the refusal names.
    owner = r.fact("owner authorizes")
    assert owner["hook"] == "pretool-bash-safety.sh" and "&& scripts/bootstrap`" in owner["authorize"], owner
    assert any(k.endswith(".clean") for k in r.fact("owner remedy")["keys"]), r.explain()

    # The orchestrator gate ran on each question and allowed it.
    gate = [[h["verdict"] for h in ev["hooks"] if h["hook"] == "hooks/pretool-orchestrator-gate.py"]
            for ev in r.hook_events() if ev.get("event") == "PreToolUse" and ev.get("tool") == "AskUserQuestion"]
    assert gate == [["ok"]] * 3, gate

    # After the owner's answer, Steps 5-7 again: the commit lands with its trailer and push-gate token.
    done = r.fact("commit")
    assert done["commit_status"] == "committed" and len(done["landed"]) == 1, done
    assert done["task_id_trailer"] and done["push_gate_tokens"], done

    # No AWAITING_INPUT text anywhere in the run's transcripts.
    for dp, _, fs in os.walk(os.path.join(r.run_dir, "transcripts")):
        for f in fs:
            with open(os.path.join(dp, f), encoding="utf-8", errors="replace") as fh:
                assert "AWAITING_INPUT" not in fh.read(), os.path.join(dp, f)
