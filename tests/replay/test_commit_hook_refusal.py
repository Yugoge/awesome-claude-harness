"""P4 acceptance 5, its hook-rejection case: a hook refuses a /commit step; it is reported, nobody is asked.

drivers/commit.py variant `waits` (the owner's world: settings_filter_world). The tree's own refusal on Phase 8's
commit: pretool-bash-safety.sh's commit guard, `unregistered-settings-filter` (the project keeps settings.json
under the claude-settings filter, this clone never registered it, the owner has a local edit). The replay is
strict: the one block is that refusal, no deviation passes anything, no hook errors. `/commit` with no task ends on
its NO_TARGET: line (Step 2), the owner types `/commit <task>`, and the hook's refusal ends that run on Step 7's
REFUSED: line, with the hook's output and the remedy it names; `/commit --auto --force` ends on Step 1's
NO_TARGET: line. No AskUserQuestion is made and every Stop passes (the Stop gate's no_target_end and
hook_refused_landing).
"""
from __future__ import annotations

import os

import pytest

from tests.replay import suite

WAITS = suite.Scenario("/commit waits (hook refusal)", "commit", (("variant", "waits"),), ("dev", "commit"), 240)
KEY = suite.replay_key(WAITS, "armed")
STEP = "agent:changelog-analyst Bash stage and commit 0"
REFUSAL = "BLOCKED: unregistered-settings-filter"


@pytest.mark.replay(KEY, WAITS.cost)
def test_a5_hook_refusal_under_commit_is_reported_and_nobody_asked(replays):
    r = replays.get(KEY)
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    # The one block: the tree's refusal of Phase 8's commit, never passed by a deviation.
    assert [(b["hook"], b["step"], b["first"].split(" —")[0], b["passed_by_deviation"]) for b in r.blocks] == [
        ("hooks/pretool-bash-safety.sh", STEP, REFUSAL, False)], r.explain()
    assert not r.summary.get("blocks_passed") and not r.summary.get("deviations"), r.explain()
    assert not r.hook_errors, r.explain()

    asked = [ev for ev in r.hook_events() if ev.get("event") == "PreToolUse" and ev.get("tool") == "AskUserQuestion"
             and ev.get("label", "").startswith("/commit ")]
    assert asked == [], asked

    lines = [f["value"] for f in r.facts if f.get("key") == "commit no target"]
    assert [bool(v["typed"]) for v in lines] == [False, True], r.explain()
    task = lines[0]["candidates"][0]
    assert lines[0]["line"].startswith(f"NO_TARGET: /commit {task}"), lines
    assert lines[1]["line"].startswith("NO_TARGET: --auto takes no task-id, --force or --bulk"), lines
    assert r.fact("commit no target stop") == {"still_blocked": False}, r.explain()

    refused = r.fact("commit refused")
    assert refused["line"].startswith("REFUSED: pretool-bash-safety.sh refused `git commit` in ") and \
        refused["line"].endswith(f" for task {task}"), refused
    assert " commit -F " in refused["line"], refused  # the exact command refused
    assert REFUSAL in refused["output"] and "Run scripts/bootstrap in " in refused["output"], refused
    assert "&& scripts/bootstrap`" in refused["remedy"], refused
    assert r.fact("commit stop") == {"outcome": "refused", "still_blocked": False}, r.explain()
    done = r.fact("commit")
    assert done["commit_status"] == "refused" and not done["landed"], done  # never retried

    # No AWAITING_INPUT text anywhere in the run's transcripts.
    for dp, _, fs in os.walk(os.path.join(r.run_dir, "transcripts")):
        for f in fs:
            with open(os.path.join(dp, f), encoding="utf-8", errors="replace") as fh:
                assert "AWAITING_INPUT" not in fh.read(), os.path.join(dp, f)
