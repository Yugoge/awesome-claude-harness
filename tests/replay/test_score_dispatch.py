"""P13-3 C-A3 and D32's acceptance: what each agent sees at dispatch, and what a low record costs, in replayed /dev and /close cycles.

The real hooks run under the shipped settings in a sandbox; the score log starts with the rows `score=<role>:<rank>,...` seeds
(tests/replay/scorelog.py), long before the replay, so every hook reads them as the record at the command's opener. The stand-in CLI
(tests/replay/replay.py) fires SubagentStart at each dispatch and puts the hook's text in the agent's context, as the CLI does, and
its agent follows a text that asks for a Codex debate.

Replays (each is /dev variant plain, or qa-fail, unless it says /close):

* LOW and HIGH: dev, ba and qa at the six ranks between them (LOW: Apprentice, Disgraced, Journeyman; HIGH: Skilled Craftsman, Senior
  Craftsman, Master). Every dispatch carries its role's rank and that rank's reminder; no gate refuses anything an empty log would not
  (a compliant run's 0 blocks); a low dev and a low BA get a second independent QA round, which the Stop gate holds.
* QA_FAIL_LOW and QA_FAIL_HIGH: the same over a first QA that fails: a low dev's two rounds run after its re-dispatch.
* LOW_QA: a low QA, --codex not given: every QA round of the cycle holds a Codex debate and its ledger entry.
* RESTORED: the score brought back above the threshold: one QA round each.
* CLOSE_LOW: a /close after the cycle gets no start text at all, and no block (/close and /commit stay out of scoring).
"""
from __future__ import annotations

import json
import re

import pytest

from hooks.lib import score_log
from tests.replay import suite
from tests.replay.test_score_replay import OBLIGATION, clean_run, dispatches

LOW_FIXTURE, HIGH_FIXTURE = "dev:apprentice,ba:disgraced,qa:journeyman", "dev:skilled,ba:senior,qa:master"
RANK_OF = {"apprentice": "Apprentice", "disgraced": "Disgraced", "journeyman": "Journeyman", "skilled": "Skilled Craftsman",
           "senior": "Senior Craftsman", "master": "Master", "restored": "Journeyman"}
SCENARIOS = {
    "low": suite.Scenario("score at dispatch: dev, ba, qa at low ranks", "dev", (("variant", "plain"), ("score", LOW_FIXTURE)), ("dev",), 110),
    "high": suite.Scenario("score at dispatch: dev, ba, qa at high ranks", "dev", (("variant", "plain"), ("score", HIGH_FIXTURE)), ("dev",), 90),
    "qa-fail-low": suite.Scenario("score at dispatch: a QA fail, low ranks", "dev", (("variant", "qa-fail"), ("score", LOW_FIXTURE)), ("dev",), 130),
    "qa-fail-high": suite.Scenario("score at dispatch: a QA fail, high ranks", "dev", (("variant", "qa-fail"), ("score", HIGH_FIXTURE)), ("dev",), 110),
    "low-qa": suite.Scenario("score at dispatch: a low QA, no --codex", "dev", (("variant", "plain"), ("score", "dev:master,ba:senior,qa:disgraced")), ("dev",), 100),
    "restored": suite.Scenario("score at dispatch: the score restored", "dev", (("variant", "plain"), ("score", "dev:restored,ba:restored,qa:restored")), ("dev",), 90),
    "extra-skip": suite.Scenario("score at dispatch: a low dev's cycle ends before its extra round", "dev",
                                 (("variant", "plain"), ("score", "dev:disgraced"), ("extra", "skip")), ("dev",), 110),
    "close-low": suite.Scenario("score at dispatch: /close after a low-record cycle", "close", (("variant", "plain"), ("score", LOW_FIXTURE)), ("dev", "close"), 160),
}
KEYS = {name: suite.replay_key(scn, "shipped") for name, scn in SCENARIOS.items()}


def replay(name: str):
    return pytest.mark.replay(KEYS[name], SCENARIOS[name].cost)


def fixture_of(name: str) -> dict:
    """role -> rank name the scenario's score argument seeds."""
    return {role: RANK_OF[rank] for role, _, rank in (item.partition(":") for item in dict(SCENARIOS[name].args)["score"].split(","))}


def starts(r) -> list[dict]:
    """Each SubagentStart event: the agent's type, its step label and the text its hook handed it ("" for none)."""
    out = []
    for ev in r.hook_events():
        if ev["event"] == "SubagentStart":
            (run,) = [h for h in ev["hooks"] if h["hook"] == "hooks/subagentstart-score-inject.py"]
            assert (run["rc"], run["verdict"], run["stderr"]) == (0, "ok", ""), run
            text = json.loads(run["stdout"])["hookSpecificOutput"]["additionalContext"] if run["stdout"].strip() else ""
            out.append({"type": ev["agent_type"], "label": ev["label"], "text": text, "label_n": len(out)})
    return out


def rounds(r, role: str, profile: str) -> list[dict]:
    """The main agent's dispatches of the role whose obligation carries the profile, in order, each with its prompt and its obligation."""
    out = []
    for d in dispatches(r):
        for rec in _records(d["main"]):
            for block in (rec.get("message") or {}).get("content") or () if isinstance((rec.get("message") or {}).get("content"), list) else ():
                if block.get("type") == "tool_use" and block.get("id") == d["tool_use_id"]:
                    prompt = block["input"].get("prompt") or ""
                    found = OBLIGATION.search(prompt)
                    ob = json.loads(found.group(1)) if found else {}
                    if ob.get("role") == role and ob.get("profile") == profile:
                        out.append({**d, "prompt": prompt, "obligation": ob})
    return out


def _records(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def opener_text(r) -> str:
    """What the typed command's UserPromptSubmit hooks printed (the first typed command of the replay)."""
    ev = next(e for e in r.hook_events() if e["event"] == "UserPromptSubmit" and e["label"].startswith("/"))
    return "\n".join(h["stdout"] for h in ev["hooks"])


# ---------------------------------------------------------------- every dispatch carries its rank's reminder (C-A3)

@pytest.mark.parametrize("name", [pytest.param(n, id=n, marks=replay(n)) for n in ("low", "high", "qa-fail-low", "qa-fail-high", "low-qa", "restored")])
def test_every_dispatch_carries_its_roles_rank_and_that_ranks_reminder_and_no_gate_refuses_more_than_an_empty_log_would(replays, name):
    r = replays.get(KEYS[name])
    clean_run(r)  # 0 gate blocks and 0 hook errors, each command at its terminal: the verdicts of an empty log's replay
    seen = starts(r)
    assert seen and all(s["text"] for s in seen), seen
    for s in seen:
        text, role = s["text"], s["type"]
        assert len(text.split("\n")) <= 3 and len(text.encode()) <= 400, text
        rank = fixture_of(name).get(role, "Skilled Craftsman")
        if role in fixture_of(name) and rank != "Skilled Craftsman":
            assert f"Your record ({role}, this project)" in text and f"[Rank: {rank}," in text, (s["label"], text)
        else:  # an agent with no rows (graphify, test-writer; a role seeded Skilled Craftsman, the rank of no rows): one line
            assert text.startswith(f"No record yet for {role} in this project: Rank Skilled Craftsman") and "\n" not in text, text
        assert score_log.REMINDERS[rank] in text and not [o for o in score_log.REMINDERS if o != rank and score_log.REMINDERS[o] in text], text
        assert not re.search(r"\d{8}-\d{6}", text) and not any(w in text.lower() for w in ("punish", "irreversible")), text


# ---------------------------------------------------------------- a low dev or BA: one more independent QA round (D32)

@pytest.mark.parametrize("name", [pytest.param(n, id=n, marks=replay(n)) for n in ("low", "qa-fail-low")])
def test_a_low_dev_and_a_low_ba_get_a_second_independent_qa_round_and_the_stop_gate_holds_it(replays, name):
    r = replays.get(KEYS[name])
    final, validation = rounds(r, "qa", "final_verification"), rounds(r, "qa", "ba_validation")
    assert len(final) == (3 if name == "qa-fail-low" else 2), [d["tool_use_id"] for d in final]  # a QA fail: one round, the dev again, then both rounds
    assert len(validation) == 3  # panel QA (round 1) and the two rounds of BA's final context
    for first, second in zip(final[-2:-1] + validation[-2:-1], final[-1:] + validation[-1:]):
        assert second["agent_id"] != first["agent_id"] and second["tool_use_id"] != first["tool_use_id"]
        assert second["obligation"]["dispatched_at"] > first["obligation"]["dispatched_at"]
        assert first["agent_id"] not in second["prompt"] and first["tool_use_id"] not in second["prompt"]  # nothing of the first round
        assert not re.search(r"(?i)\bqa report file:|\bverdict\b.*\bfirst round", second["prompt"]), second["prompt"]
    out = opener_text(r)
    assert "Low record: dev/ba: one more independent QA round after the normal one" in out and "qa:" not in out.split("Low record:")[1]


@pytest.mark.parametrize("name", [pytest.param(n, id=n, marks=replay(n)) for n in ("high", "restored", "qa-fail-high")])
def test_with_the_score_not_low_one_qa_round_runs(replays, name):
    r = replays.get(KEYS[name])
    assert len(rounds(r, "qa", "final_verification")) == (2 if name == "qa-fail-high" else 1)  # (a QA fail's re-dispatch: one round each time)
    assert len(rounds(r, "qa", "ba_validation")) == 2  # panel QA, then BA's final context
    assert "Your record (main)" in opener_text(r) and "Low record" not in opener_text(r)
    assert not any(score_log.CONSEQUENCES[role] in s["text"] for s in starts(r) for role in score_log.CONSEQUENCES), "no start text names a consequence"


# ---------------------------------------------------------------- a low QA debates Codex without --codex (D32)

@replay("low-qa")
def test_a_low_qa_holds_a_codex_debate_in_every_round_without_the_flag(replays):
    r = replays.get(KEYS["low-qa"])
    clean_run(r)  # no stop was refused: each QA stopped only after it called codex (R-022 binds it with no flag and no line)
    assert "Low record: qa: a Codex debate every round, --codex or not" in opener_text(r) and "independent QA round" not in opener_text(r)
    qa = [s for s in starts(r) if s["type"] == "qa"]
    assert len(qa) == 3 and all(score_log.CONSEQUENCES["qa"] in s["text"] for s in qa)  # panel QA, BA validation, final verification
    called = [ev for ev in r.hook_events() if ev["event"] == "PostToolUse" and ev.get("tool") == "Skill" and ev["agent_type"] == "qa"]
    assert len(called) == 3  # every QA round: one codex call, and the ledger hook ran on it
    assert all(any(h["hook"] == "hooks/posttool-codex-skill-ledger.py" and (h["rc"], h["verdict"]) == (0, "ok") for h in ev["hooks"]) for ev in called)
    assert not any(s["type"] in ("dev", "ba") and "Codex" in s["text"] for s in starts(r))  # dev and ba do not debate


# ---------------------------------------------------------------- /close and /commit stay out of scoring

@replay("close-low")
def test_a_close_span_gets_no_start_text_and_no_new_block(replays):
    r = replays.get(KEYS["close-low"])
    assert not r.error and r.rc == 0 and not r.hook_errors, r.explain()
    events = r.hook_events()
    opener = next(i for i, ev in enumerate(events) if ev["event"] == "UserPromptSubmit" and ev["label"].startswith("/close"))
    in_close = [e for e in events[opener:] if e["event"] == "SubagentStart"]
    before = [e for e in events[:opener] if e["event"] == "SubagentStart"]
    assert in_close and before
    for ev in in_close:  # the hook ran (it is registered on every start) and printed nothing
        (run,) = [h for h in ev["hooks"] if h["hook"] == "hooks/subagentstart-score-inject.py"]
        assert (run["rc"], run["verdict"], run["stdout"], run["stderr"]) == (0, "ok", "", ""), run
    assert all(any(h["stdout"].strip() for h in ev["hooks"]) for ev in before)  # while the /dev span's starts did
    assert [b for b in r.blocks if b["event"] in ("SubagentStart", "Stop", "SubagentStop")] == [], r.blocks


# ---------------------------------------------------------------- the Stop gate holds the extra round, and the next action clears it

@replay("extra-skip")
def test_a_cycle_ended_before_a_low_devs_extra_round_is_refused_once_and_one_more_qa_clears_it(replays):
    r = replays.get(KEYS["extra-skip"])
    assert not r.error and r.rc == 0 and not r.hook_errors and r.reached(), r.explain()
    (block,) = r.blocks  # the one refusal: the Stop before the extra round, by the Stop gate, naming the dispatch it wants
    assert block["step"] == "Stop before the extra round" and block["hook"] == "hooks/stop-launch.py", block
    assert "owes one more independent final_verification QA dispatch" in block["text"] and "dev's record is low (D32)" in block["text"], block
    assert len(rounds(r, "qa", "final_verification")) == 2  # the first, and the one the gap asked for; the cycle's own Stop then passed
