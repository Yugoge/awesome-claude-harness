"""P13-2 B2, B3, B4: the score log after a replayed /dev cycle and after a /close that follows it, and the rating.

The real hooks run under the shipped settings in a sandbox that has its own config directory; the score
observer (hooks/posttool-close-rating.py, matcher AskUserQuestion|Agent) sweeps the active command span after
each main-agent dispatch and appends score events to the sandbox's logs/lifecycle.jsonl. The stand-in CLI
(tests/replay/agents.py, roles.py, drivers/dev.py) plays the subagents: their own transcripts hold the Write and
Edit calls the observer reads, and the lane QA's failure is a qa.failures[] entry in the shape agents/qa.md spells
(severity, location, issue, recommendation, primary_cause).

Eight replays carry every assertion, each run with the driver argument `resweep=1` (tests/replay/scorelog.py:
the observer hook run once more on the final transcript, the log kept as out/score-log.jsonl):

* QA_FAIL_CLOSE: /dev (variant qa-fail: the lane's first QA fails, its dev is dispatched again, the next QA
  passes), then a clean /close in the same session, rated "4 - Minor gaps": the log gains qa_fail (dev) and
  qa_catch (qa), no rerun_gap, nothing for close-qa, and one rating row on the task id the events carry (B2, B3's
  clean close, B4's answer 4 and its dialog).
* QA_FAIL_DEV: the same /dev cycle alone. Its final span is the /dev span, so its re-sweep derives qa_fail and
  qa_catch again; QA_FAIL_CLOSE's final span is the /close span, which holds neither (B2's "replaying again adds
  0 rows" for these two rows rests on this replay).
* QA_FAIL_OTHER_FILE: the same cycle, the failure naming a file the re-dispatched dev does not edit
  (`fail_at`): qa_fail, and no qa_catch.
* FIRST_PASS: /dev variant plain: qa_first_pass for dev and ba, nothing negative, and ba_option_chosen for ba: a /dev without a
  spec runs the BA panel, and the replayed owner answers its round with each question's first option (D32), so every
  such replay logs that event beside its others.
* PANEL_DISAGREE, PANEL_REFUTED: /dev variants panel-disagree (two BAs name different root causes, panel QA turns it into one
  decision point, the owner's answer picks BA A) and panel-refuted (panel QA refuted BA C's root cause: its option never
  reaches the owner, and the log gains ba_root_cause_refuted for ba).
* CLOSE_FINDINGS: a /dev cycle whose lane QA passes first, then a /close (variant append) whose first round opens
  a finding on the file the dev wrote, the dev writes it again and a later round lands (B3).
* RATING_ANSWERS: a clean /close of a first-pass cycle whose rating question is asked seven times for the one
  task (`again`): Skip and decline (the CLI runs no hook), a typed reply, the AFK timeout and an app-side dismissal
  (unconfirmed; the hook runs, no rating row), then "4 - Minor gaps" (the row), then "5 - Fully met" (writes nothing) (B4).

In each, the sweep of the final transcript a second time leaves the log byte for byte as it was, and runs
without error beside the compliant run's 0 gate blocks and 0 hook errors.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re

import pytest

from hooks.lib import score_log
from tests.replay import suite
from tests.replay.drivers import _round

OBSERVER = "hooks/posttool-close-rating.py"
ZULU = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
LANE_REPORT = re.compile(r"docs/dev/qa-report-[\w.-]+\.json")  # the lane QA's report (the BA-validation QA's is ba-qa-report-...)
OBLIGATION = re.compile(r'<obligation\s+v="1"\s*>\s*(\{.*?\})\s*</obligation>', re.S)
RATING_LABEL = "/close Step 4 AskUserQuestion"  # the first question's step label; the n-th asked again adds " again n"

QA_FAIL_CLOSE = suite.Scenario("score: /dev qa-fail, then /close", "close",
                               (("variant", "plain"), ("cycle_variant", "qa-fail"), ("rating", "4"), ("resweep", "1")),
                               ("dev", "close"), 150)
OTHER_FILE = "toy/util.py"
QA_FAIL_DEV = suite.Scenario("score: /dev qa-fail", "dev", (("variant", "qa-fail"), ("resweep", "1")), ("dev",), 110)
QA_FAIL_OTHER_FILE = suite.Scenario("score: /dev qa-fail naming another file", "dev",
                                    (("variant", "qa-fail"), ("fail_at", OTHER_FILE), ("resweep", "1")),
                                    ("dev",), 110)
FIRST_PASS = suite.Scenario("score: /dev first pass", "dev", (("variant", "plain"), ("resweep", "1")), ("dev",), 90)
CLOSE_FINDINGS = suite.Scenario("score: /close finding after lane QA passed", "close",
                                (("variant", "append"), ("resweep", "1")), ("dev", "close"), 180)
PANEL_DISAGREE = suite.Scenario("score: /dev panel disagree", "dev", (("variant", "panel-disagree"), ("resweep", "1")), ("dev",), 110)
PANEL_REFUTED = suite.Scenario("score: /dev panel refuted", "dev", (("variant", "panel-refuted"), ("resweep", "1")), ("dev",), 110)
ANSWERS = ["skip", "decline", "free", "afk", "dismissed", "4", "5"]  # one task's rating dialog, asked once for each
RATING_ANSWERS = suite.Scenario("score: /close rating answers", "close",
                                (("variant", "plain"), ("rating", ANSWERS[0]), ("again", ",".join(ANSWERS[1:])),
                                 ("resweep", "1")), ("dev", "close"), 150)
SCENARIOS = {"qa-fail-close": QA_FAIL_CLOSE, "qa-fail-dev": QA_FAIL_DEV, "qa-fail-other-file": QA_FAIL_OTHER_FILE,
             "first-pass": FIRST_PASS, "close-findings": CLOSE_FINDINGS, "rating-answers": RATING_ANSWERS,
             "panel-disagree": PANEL_DISAGREE, "panel-refuted": PANEL_REFUTED}
# What a sweep of each replay's final transcript yields on an empty log: its final span is the /dev span of a
# /dev-only run (every row the cycle logged: "all", or listed where the rows are the point: qa_fail and qa_catch, with the
# cycle's ba_option_chosen),
# the /close span typed in a later session (the close-time events), or, for a /close typed in the /dev's session, a
# span that holds no lane QA (none: that re-sweep proves nothing about the /dev rows, the /dev-only runs do).
REBUILT = {"qa-fail-close": [], "qa-fail-dev": [("qa_fail", "dev"), ("qa_catch", "qa"), ("ba_option_chosen", "ba")], "qa-fail-other-file": "all",
           "first-pass": "all", "panel-disagree": "all", "panel-refuted": "all", "rating-answers": [],
           "close-findings": [("escaped", "dev"), ("escaped", "qa"), ("close_catch", "close-qa")]}
KEYS = {name: suite.replay_key(scn, "shipped") for name, scn in SCENARIOS.items()}
BLOCKED = {"panel-refuted": ("Step 4a Agent(qa) panel QA offering a refuted option",)}  # the steps a replay is refused at (the others: none)


def replay(name: str):
    """A test reading the replay `name` (shared with every test that names it: one replay per session)."""
    return pytest.mark.replay(KEYS[name], SCENARIOS[name].cost)


# ---------------------------------------------------------------- what the replay left

def _jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def log_bytes(r) -> bytes:
    with open(os.path.join(r.run_dir, "score-log.jsonl"), "rb") as fh:
        return fh.read()


def events(r) -> list[dict]:
    """The log's event rows in order (legacy rows of score-update.sh carry no kind and are not events)."""
    rows = [json.loads(line) for line in log_bytes(r).decode("utf-8").splitlines() if line.strip()]
    return [row for row in rows if row.get("kind") == "event"]


def project(r) -> str:
    """The project directory as the replay's processes saw it (ids.json)."""
    with open(os.path.join(r.run_dir, "ids.json")) as fh:
        return json.load(fh)["layout"]["project"]


def dispatches(r) -> list[dict]:
    """Every main-agent dispatch of the replay in order, with what its subagent's own transcript says it did:
    `role` (subagent_type), `tool_use_id`, `agent_id`, `result_at` (the time its result was recorded, as a
    score row's ts), `identity` (the scored identity its prompt's obligation names, None when it carries none), `wrote` (project-relative files of its Write and Edit calls) and `reports`
    ({path: parsed content} of each qa-report it wrote)."""
    out, by_use, root = [], {}, project(r)
    mains = sorted(glob.glob(os.path.join(r.run_dir, "transcripts", "*", "*.jsonl")), key=lambda p: _jsonl(p)[0]["timestamp"])
    for main in mains:
        for rec in _jsonl(main):
            content = (rec.get("message") or {}).get("content")
            for block in content if isinstance(content, list) else ():
                if block.get("type") == "tool_use" and block.get("name") == "Agent":
                    found = OBLIGATION.search(block["input"].get("prompt") or "")
                    ob = json.loads(found.group(1)) if found else {}
                    out.append({"role": block["input"]["subagent_type"], "tool_use_id": block["id"], "main": main,
                                "identity": score_log.identity(ob.get("role"), ob.get("pipeline")) if ob else None})
                elif block.get("type") == "tool_result" and isinstance(rec.get("toolUseResult"), dict):
                    by_use[block["tool_use_id"]] = rec["toolUseResult"].get("agentId"), rec["timestamp"]
    for d in out:
        d["agent_id"], d["result_at"] = by_use[d["tool_use_id"]]
        sub = os.path.join(d["main"][:-len(".jsonl")], "subagents", f"agent-{d['agent_id']}.jsonl")
        d["wrote"], d["reports"] = [], {}
        for rec in _jsonl(sub):
            content = (rec.get("message") or {}).get("content")
            for block in content if isinstance(content, list) else ():
                if block.get("type") == "tool_use" and block.get("name") in ("Write", "Edit"):
                    rel = os.path.relpath(block["input"]["file_path"], root)
                    d["wrote"].append(rel)
                    if block["name"] == "Write" and LANE_REPORT.fullmatch(rel):
                        d["reports"][rel] = json.loads(block["input"]["content"])
    return out


def lane_qa(r) -> list[dict]:
    """The lane's final-verification QA rounds: the dispatches that wrote or edited the lane's qa-report."""
    return [d for d in dispatches(r) if d["role"] == "qa" and any(LANE_REPORT.fullmatch(p) for p in d["wrote"])]


def project_key(r) -> str:
    """S1: the first 12 hex digits of the sha256 of the real path of the project's git common directory (what
    hooks/lib/score_log.py project_key hashes; the toy project is a plain checkout, so that directory is its .git)."""
    return hashlib.sha256(os.path.realpath(os.path.join(project(r), ".git")).encode()).hexdigest()[:12]


def task_of(r) -> str:
    return r.terminal("dev")["task"]


def clean_run(r, blocks: tuple = ()) -> None:
    """The compliant run's terms: 0 gate blocks (`blocks`: the steps, as label prefixes, the replay is expected to be refused at),
    0 hook errors, every command at its terminal; and the score observer ran once on each main-agent dispatch's return,
    exit 0, nothing printed."""
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    steps = [b["step"] for b in r.blocks]
    assert len(steps) == len(blocks) and all(s.startswith(b) for s, b in zip(steps, blocks)), "a compliant run met a gate block:\n" + r.explain()
    assert not r.hook_errors, "a compliant run met a hook error:\n" + r.explain()
    assert r.reached(), "a pipeline did not reach its terminal:\n" + r.explain()
    returns = [ev for ev in r.hook_events() if ev["event"] == "PostToolUse" and ev.get("tool") == "Agent"]
    ran = [h for ev in returns for h in ev["hooks"] if h["hook"] == OBSERVER]
    assert returns and len(ran) == len(returns) == len(dispatches(r)), (len(returns), len(ran), len(dispatches(r)))
    assert all((h["rc"], h["verdict"], h["stdout"], h["stderr"]) == (0, "ok", "", "") for h in ran), ran


def event_rows(r, shape: list[tuple], refs: dict | None = None) -> list[dict]:
    """The log holds exactly the events `shape` lists ((event, role), in any order), each a well-formed row:
    kind event, this project's key, this cycle's canonical task id, the rule's points, one line of why text
    without the task id, as ref the lane QA's report path (`refs` names another for an event: the artifact a
    close finding cites; the BA panel's two events cite theirs: the owner's answer file, panel QA's round file),
    a UTC time and a key no other row has."""
    rows, task = events(r), task_of(r)
    refs = {"ba_option_chosen": f"docs/dev/requirement-answers-{task}-r1.json", "ba_root_cause_refuted": f"docs/dev/ba-panel-{task}-r1.json", **(refs or {})}
    assert sorted((e["event"], e["role"]) for e in rows) == sorted(shape), rows
    assert len({e["key"] for e in rows}) == len(rows), rows
    for e in rows:
        assert e["kind"] == "event" and e["project"] == project_key(r) and e["task_id"] == task_of(r), e
        assert e["points"] == score_log.points_for(e["event"], e["role"]), e
        assert e["why"].strip() and "\n" not in e["why"] and task_of(r) not in e["why"], e
        assert e["ref"] == refs.get(e["event"], f"docs/dev/qa-report-{task_of(r)}.json") and ZULU.match(e["ts"]), e
    return rows


def asks(r) -> list[dict]:
    """Every AskUserQuestion the main agent made, in order: `input`, `tool_use_id`, and what came back: `is_error`
    (the tool_result) and `denial` (the user row's toolDenialKind)."""
    out, by_id = [], {}
    for main in sorted(glob.glob(os.path.join(r.run_dir, "transcripts", "*", "*.jsonl")), key=lambda p: _jsonl(p)[0]["timestamp"]):
        for rec in _jsonl(main):
            content = (rec.get("message") or {}).get("content")
            for block in content if isinstance(content, list) else ():
                if block.get("type") == "tool_use" and block.get("name") == "AskUserQuestion":
                    by_id[block["id"]] = {"input": block["input"], "tool_use_id": block["id"], "is_error": None, "denial": None}
                    out.append(by_id[block["id"]])
                elif block.get("type") == "tool_result" and block.get("tool_use_id") in by_id:
                    by_id[block["tool_use_id"]].update(is_error=bool(block.get("is_error")), denial=rec.get("toolDenialKind"))
    return out


def questions(r) -> list[dict]:
    """The rating questions among them (metadata.source close-rating:<task id>)."""
    return [q for q in asks(r) if str(q["input"].get("metadata", {}).get("source", "")).startswith("close-rating:")]


def rating_steps(r) -> list[dict]:
    """What the driver recorded after each rating question (facts.json "close Step 4"), in order: the answer it
    played, whether any PostToolUse hook ran, and the rating rows the score log held right after."""
    return [f["value"] for f in r.facts if f["key"] == "close Step 4"]


def after_call(r, label: str) -> list[dict]:
    """The hook events a tool call fired once it ended (PostToolUse, or PostToolUseFailure), by its step label."""
    return [ev for ev in r.hook_events() if ev["event"] in ("PostToolUse", "PostToolUseFailure") and ev.get("label") == label]


def owner_summary(r, label: str) -> str:
    """The summary the observer hook printed for the call labelled `label`: its one run, exit 0, nothing on stderr,
    one line of standard output holding one JSON object whose only member is systemMessage."""
    (event,) = after_call(r, label)
    (run,) = [h for h in event["hooks"] if h["hook"] == OBSERVER]
    assert (run["rc"], run["verdict"], run["stderr"]) == (0, "ok", ""), run
    assert run["stdout"].endswith("\n") and "\n" not in run["stdout"][:-1], run["stdout"]
    out = json.loads(run["stdout"])
    assert list(out) == ["systemMessage"] and isinstance(out["systemMessage"], str), out
    return out["systemMessage"]


def rating_rows(r) -> list[dict]:
    return [json.loads(line) for line in log_bytes(r).decode("utf-8").splitlines() if '"kind": "rating"' in line]


# ---------------------------------------------------------------- B2: a QA fail, its fix, then /close

@pytest.mark.parametrize("name", [pytest.param(n, id=n, marks=replay(n)) for n in ("qa-fail-close", "qa-fail-dev")])
def test_a_qa_fail_and_its_fix_log_qa_fail_for_dev_and_qa_catch_for_qa_and_no_rerun_gap(replays, name):
    r = replays.get(KEYS[name])  # /dev alone, or /dev and then a clean /close
    clean_run(r)
    rows = event_rows(r, [("qa_fail", "dev"), ("qa_catch", "qa"), ("ba_option_chosen", "ba")])  # and the owner's pick of a BA's option (D32)
    fail, catch = (next(e for e in rows if e["event"] == name) for name in ("qa_fail", "qa_catch"))
    assert fail["points"] < 0 < catch["points"] and fail["ts"] <= catch["ts"]
    # what the driver played: the first QA round's failure, blamed on the dev, naming the file the dev's re-dispatch writes
    first, second = lane_qa(r)[:2]
    (report,) = first["reports"].values()
    (failure,) = report["qa"]["failures"]
    assert report["qa"]["status"] == "fail" and failure["primary_cause"] == "dev_implementation", report
    assert fail["why"] == failure["issue"], (fail, failure)
    named = failure["location"].rpartition(":")[0]
    _, dev_again = [d for d in dispatches(r) if d["role"] == "dev"]  # the cycle's dev and its re-dispatch
    assert named in dev_again["wrote"], (named, dev_again["wrote"])
    # each row stands for its own dispatch: the failing round, and the round that passed after the fix
    assert first["tool_use_id"] in fail["key"] and second["tool_use_id"] in catch["key"]
    # the QA-driven re-dispatch is not a gap
    assert not [e for e in events(r) if e["event"] == "rerun_gap"]


@replay("qa-fail-other-file")
def test_a_qa_fail_whose_fix_touches_no_named_file_gives_no_qa_catch(replays):
    r = replays.get(KEYS["qa-fail-other-file"])
    clean_run(r)
    (fail,) = [e for e in event_rows(r, [("qa_fail", "dev"), ("ba_option_chosen", "ba")]) if e["event"] == "qa_fail"]
    first = lane_qa(r)[0]
    (failure,) = next(iter(first["reports"].values()))["qa"]["failures"]
    assert failure["location"].rpartition(":")[0] == OTHER_FILE and failure["primary_cause"] == "dev_implementation", failure
    assert fail["why"] == failure["issue"]
    _, dev_again = [d for d in dispatches(r) if d["role"] == "dev"]
    # the re-dispatched dev did write files (the lane's own), none of them the one the failure names
    assert dev_again["wrote"] and OTHER_FILE not in dev_again["wrote"], dev_again["wrote"]
    assert not [e for e in events(r) if e["event"] in ("qa_catch", "rerun_gap")]


@replay("first-pass")
def test_a_first_pass_cycle_gives_qa_first_pass_for_dev_and_ba_and_nothing_negative(replays):
    r = replays.get(KEYS["first-pass"])
    clean_run(r)
    rows = event_rows(r, [("qa_first_pass", "dev"), ("qa_first_pass", "ba"), ("ba_option_chosen", "ba")])
    assert all(e["points"] > 0 for e in rows) and not [e for e in events(r) if e["points"] < 0]
    (qa,) = lane_qa(r)
    first, (chosen,) = [e for e in rows if e["event"] == "qa_first_pass"], [e for e in rows if e["event"] == "ba_option_chosen"]
    assert len(first) == 2 and all(qa["tool_use_id"] in e["key"] for e in first), (qa["tool_use_id"], rows)  # a row of the lane QA's round names it
    assert chosen["key"] == f"ba_option_chosen:{task_of(r)}", chosen  # the owner's pick stands for the task, not for a dispatch
    assert list(qa["reports"].values())[0]["qa"]["status"] == "pass"


# ---------------------------------------------------------------- D32: the BA panel's two events

def panel_ask(r) -> dict:
    """The one AskUserQuestion that asks round 1 of the cycle (metadata.source requirement-round:<task id>:r1), as the main agent made it."""
    (ask,) = [q for q in asks(r) if q["input"].get("metadata", {}).get("source") == f"requirement-round:{task_of(r)}:r1"]
    assert ask["is_error"] is False and not any("ba" in o for q in ask["input"]["questions"] for o in q["options"]), ask
    return ask


@replay("panel-disagree")
def test_the_owners_answer_picking_a_bas_option_logs_ba_option_chosen_for_ba(replays):
    r = replays.get(KEYS["panel-disagree"])
    clean_run(r)
    rows = event_rows(r, [("qa_first_pass", "dev"), ("qa_first_pass", "ba"), ("ba_option_chosen", "ba")])
    (chosen,) = [e for e in rows if e["event"] == "ba_option_chosen"]
    assert chosen["points"] == 3 and chosen["key"] == f"ba_option_chosen:{task_of(r)}" and "BA A" in chosen["why"], chosen
    # what the driver played (variant panel-disagree: B names another root cause than A): the three panel BAs in order, panel QA's
    # one round-1 file, the owner asked once and taking each question's first option, which on the scope question is BA A's solution
    panel_rel = f"docs/dev/ba-panel-{task_of(r)}-r1.json"
    bas, (panel_qa,) = [d for d in dispatches(r) if d["role"] == "ba"][:3], [d for d in dispatches(r) if d["role"] == "qa" and panel_rel in d["wrote"]]
    assert [d["wrote"] for d in bas] == [[f"docs/dev/ba-panel-{task_of(r)}-{angle}.md"] for angle in _round.ANGLES], [d["wrote"] for d in bas]
    scope = next(q for q in panel_ask(r)["input"]["questions"] if q["header"] == "Scope")
    assert scope["options"][0]["label"] == _round.SOLUTION["A"][0], scope
    order = [d["tool_use_id"] for d in dispatches(r)]
    assert order.index(bas[-1]["tool_use_id"]) < order.index(panel_qa["tool_use_id"]) < order.index(dispatches(r)[-1]["tool_use_id"])
    assert chosen["ts"] >= panel_qa["result_at"][:19] + "Z" and not [e for e in events(r) if e["event"] == "ba_root_cause_refuted"]


@replay("panel-refuted")
def test_a_refuted_root_cause_logs_ba_root_cause_refuted_and_its_option_never_reaches_the_owner(replays):
    r = replays.get(KEYS["panel-refuted"])
    clean_run(r, BLOCKED["panel-refuted"])
    rows = event_rows(r, [("qa_first_pass", "dev"), ("qa_first_pass", "ba"), ("ba_option_chosen", "ba"), ("ba_root_cause_refuted", "ba")])
    (refuted,) = [e for e in rows if e["event"] == "ba_root_cause_refuted"]
    assert refuted["points"] == -4 and refuted["key"] == f"ba_root_cause_refuted:{task_of(r)}:C" and "BA C" in refuted["why"], refuted
    (chosen,) = [e for e in rows if e["event"] == "ba_option_chosen"]
    assert chosen["points"] == 3 and "BA A" in chosen["why"], chosen  # the owner still chose among the options that reached it
    # what the driver played: panel QA first offered the refuted BA's option, was refused and wrote round 1 again without it
    panel_rel = f"docs/dev/ba-panel-{task_of(r)}-r1.json"
    (panel_qa,) = [d for d in dispatches(r) if d["role"] == "qa" and panel_rel in d["wrote"]]
    assert panel_qa["wrote"].count(panel_rel) == 2, panel_qa["wrote"]
    # no question to the owner names that option (its label or its description), whatever the question
    label, description = _round.SOLUTION["C"]
    offered = [o for a in asks(r) for q in a["input"]["questions"] for o in q["options"]]
    assert offered and not [o for o in offered if label in (o["label"], o.get("description")) or description in (o["label"], o.get("description"))], offered
    assert refuted["ts"] <= chosen["ts"] and panel_ask(r)["is_error"] is False


# ---------------------------------------------------------------- B2: replaying again adds 0 rows

@pytest.mark.parametrize("name", [pytest.param(n, id=n, marks=replay(n)) for n in SCENARIOS])
def test_sweeping_the_final_transcript_again_leaves_the_log_byte_for_byte_unchanged(replays, name):
    r = replays.get(KEYS[name])
    clean_run(r, BLOCKED.get(name, ()))
    sweep = r.fact("score resweep")
    assert sweep and sweep.get("hooks") == 1, f"the observer hook was not run again: {sweep}"
    assert (sweep["rc"], sweep["stdout"], sweep["stderr"]) == (0, "", ""), sweep
    log = sweep["log"]
    assert log["bytes_before"] > 0 and log["unchanged"] and log["bytes_after"] == log["bytes_before"], log
    assert log["sha256_before"] == log["sha256_after"] == hashlib.sha256(log_bytes(r)).hexdigest(), log
    # the same sweep on an empty log yields rows (the silence above is not a hook that did nothing): rows the log
    # already holds, those REBUILT says (the /close span of a later session derives escaped and close_catch)
    rebuilt = sweep["rebuilt"]
    assert (rebuilt["hooks"], rebuilt["rc"], rebuilt["stdout"], rebuilt["stderr"]) == (1, 0, "", ""), rebuilt
    held = {e["key"]: e for e in events(r)}
    assert all(held.get(e["key"]) == e for e in rebuilt["events"]), (rebuilt["events"], held)
    want = REBUILT[name]
    if want == "all":
        assert sorted(e["key"] for e in rebuilt["events"]) == sorted(held), (rebuilt["events"], held)
    else:
        assert sorted((e["event"], e["role"]) for e in rebuilt["events"]) == sorted(want), rebuilt["events"]


# ---------------------------------------------------------------- B3: a close finding after the lane QA passed

@replay("close-findings")
def test_a_close_finding_after_lane_qa_passed_logs_escaped_for_dev_and_qa_and_close_catch_for_close_qa(replays):
    r = replays.get(KEYS["close-findings"])
    clean_run(r)
    cited = "toy/__init__.py"
    rows = event_rows(r, [("qa_first_pass", "dev"), ("qa_first_pass", "ba"), ("ba_option_chosen", "ba"), ("escaped", "dev"),
                          ("escaped", "qa"), ("close_catch", "close-qa")], refs={"escaped": cited, "close_catch": cited})
    first = {e["role"]: e for e in rows if e["event"] == "qa_first_pass"}
    escaped = {e["role"]: e for e in rows if e["event"] == "escaped"}
    (caught,) = [e for e in rows if e["event"] == "close_catch"]
    assert all(e["points"] < 0 for e in escaped.values()) and caught["points"] > 0
    assert escaped["dev"]["points"] < escaped["qa"]["points"], escaped  # the producer loses more than the lane QA
    # what the driver played: lane QA passed the first time, then close QA's first round opened a finding on the
    # file the dev wrote and the second round landed
    (lane,) = lane_qa(r)
    assert list(lane["reports"].values())[0]["qa"]["status"] == "pass"
    rounds = [f["value"] for f in r.facts if f["key"] == "close QA round"]
    assert [x["verdict"].split(":")[0] for x in rounds] == ["CLOSE_FINDINGS", "CLOSE"], rounds
    assert [f["path"] for f in rounds[0]["findings"]] == [cited] and not rounds[1]["findings"], rounds
    # a finding is charged once per cited file and role, however many rounds cite it: the key names the task, the
    # cited file and the role, not a round (the rows of a re-sweep, or of a second round that cites it again, are the same rows)
    assert {role: e["key"] for role, e in escaped.items()} == \
        {role: f"escaped:{task_of(r)}:{cited}:{role}" for role in ("dev", "qa")}, escaped
    assert caught["key"] == f"close_catch:{task_of(r)}:{cited}", caught
    # each row still stands for its own dispatch, through the time its result was recorded: the finding for the round
    # that opened it, the catch for the round that landed
    opened, landed = [d for d in dispatches(r) if d["identity"] == "close-qa"]
    assert all(e["ts"] == opened["result_at"][:19] + "Z" for e in escaped.values()), (opened["result_at"], escaped)
    assert caught["ts"] == landed["result_at"][:19] + "Z", (landed["result_at"], caught)
    # the cited artifact's producer is the dev whose own calls wrote it, before the finding and again after it
    order = [d["tool_use_id"] for d in dispatches(r)]
    devs = [d for d in dispatches(r) if d["role"] == "dev"]
    assert len(devs) == 2 and cited in devs[0]["wrote"] and cited in devs[1]["wrote"], [d["wrote"] for d in devs]
    assert order.index(lane["tool_use_id"]) < order.index(opened["tool_use_id"]) < order.index(devs[1]["tool_use_id"]) \
        < order.index(landed["tool_use_id"]), order
    assert first["dev"]["ts"] <= escaped["dev"]["ts"] <= caught["ts"], (first, escaped, caught)


@pytest.mark.parametrize("name", [pytest.param(n, id=n, marks=replay(n)) for n in ("qa-fail-close", "rating-answers")])
def test_a_clean_close_gives_close_qa_no_row(replays, name):
    r = replays.get(KEYS[name])
    clean_run(r)
    rounds = [f["value"] for f in r.facts if f["key"] == "close QA round"]
    assert len(rounds) == 1 and rounds[0]["verdict"].startswith("CLOSE: YES") and not rounds[0]["findings"], rounds
    assert len([d for d in dispatches(r) if d["identity"] == "close-qa"]) == 1
    assert events(r), "the cycle's own events are in the log"
    assert not [e for e in events(r) if e["role"] == "close-qa" or e["event"] in ("escaped", "close_catch")], events(r)


# ---------------------------------------------------------------- B4: the rating

@pytest.mark.parametrize("name", [pytest.param(n, id=n, marks=replay(n)) for n in ("qa-fail-close", "rating-answers")])
def test_the_rating_dialog_is_one_question(replays, name):
    r = replays.get(KEYS[name])
    clean_run(r)
    asked = questions(r)
    assert len(asked) == len(rating_steps(r)) == (1 if name == "qa-fail-close" else len(ANSWERS)), asked
    for q in asked:  # close.md Step 4: one question, header Rating, the four rating options, one answer
        (question,) = q["input"]["questions"]
        assert q["input"]["metadata"] == {"source": f"close-rating:{task_of(r)}"}, q["input"]
        assert (question["header"], question["multiSelect"]) == ("Rating", False), question
        assert [o["label"] for o in question["options"]] == ["5 - Fully met", "4 - Minor gaps", "3 - Major gaps", "1-2 - Not met"]
        assert task_of(r) in question["question"], question
    assert {q["input"]["metadata"]["source"] for q in asked} == {f"close-rating:{task_of(r)}"}
    rounds = [q for q in asks(r) if str(q["input"].get("metadata", {}).get("source", "")).startswith("requirement-round:")]
    assert len(rounds) == 1, f"the replayed /dev asks its requirement round once: {rounds}"  # P13-1: asked before the rating dialog
    assert len(asks(r)) == len(asked) + len(rounds), f"the replay asked a question besides the rating and the requirement round: {asks(r)}"


@replay("qa-fail-close")
def test_answering_4_minor_gaps_writes_one_rating_row_with_the_roles_and_prints_the_owner_summary(replays):
    r = replays.get(KEYS["qa-fail-close"])
    clean_run(r)
    (asked,) = questions(r)
    (answered,) = rating_steps(r)
    assert answered["answer"] == "4" and answered["ok"] and answered["hook_ran"], answered
    (row,) = rating_rows(r)
    roles = sorted({d["identity"] for d in dispatches(r) if d["identity"]})
    assert row == {"kind": "rating", "ts": row["ts"], "project": project_key(r), "task_id": task_of(r), "rating": 4,
                   "roles": roles, "tool_use_id": asked["tool_use_id"]}, row
    assert ZULU.match(row["ts"]) and "close-qa" in roles and len(roles) >= 4, row
    # the hook's standard output: one JSON object, at most 5 lines, the worst identity and why, no hook name
    summary = owner_summary(r, RATING_LABEL)
    lines = summary.splitlines()
    assert 2 <= len(lines) <= 5, summary
    (worst,) = [line for line in lines if line.startswith("Worst:")]
    (failure,) = next(iter(lane_qa(r)[0]["reports"].values()))["qa"]["failures"]
    assert worst.startswith("Worst: dev ") and failure["issue"] in worst, (worst, failure)  # the one negative event is dev's
    # every identity is listed, its name cut to 24 characters (the summary bounds a name; the longest real role has 21)
    assert any(line.startswith("Scores") and all(f"{role[:24]} " in line for role in roles if role != "main") for line in lines), summary
    assert any(line.startswith("This cycle") and "rating 4" in line for line in lines), summary
    assert not re.search(r"posttool|close-rating|PostToolUse|hooks/|\.py\b", summary), summary


@replay("rating-answers")
def test_skip_decline_a_typed_reply_the_afk_timeout_and_the_apps_skip_write_no_rating_row(replays):
    r = replays.get(KEYS["rating-answers"])
    clean_run(r)
    steps, asked = rating_steps(r), questions(r)
    assert [s["answer"] for s in steps] == ANSWERS and len(asked) == len(ANSWERS), steps
    for n, (step, q) in enumerate(zip(steps, asked)):
        label = step["label"]
        assert label == RATING_LABEL + (f" again {n + 1}" if n else ""), label
        if step["answer"] in ("skip", "decline"):
            # the owner turned the dialog down: an error result, and the CLI runs no hook at all after it
            assert (step["ok"], step["hook_ran"], q["is_error"], q["denial"]) == (False, False, True, "user-rejected"), (step, q)
            assert not after_call(r, label), after_call(r, label)
        else:
            assert (step["ok"], step["hook_ran"], q["is_error"]) == (True, True, False), (step, q)
            lines = owner_summary(r, label).splitlines()
            assert any(line.startswith("Worst:") for line in lines), lines
            cycle = [line for line in lines if line.startswith("This cycle")]
            # the summary shows the cycle's rating from the "4" answer on (the second rating, 5, is never in it)
            assert len(cycle) == 1 and ("rating 4" in cycle[0]) == (step["answer"] in ("4", "5")), (step["answer"], cycle)
            assert "rating 5" not in cycle[0] and "rating 3" not in cycle[0], cycle
        # a rating row exists once "4 - Minor gaps" has been answered, and never before
        assert [row["rating"] for row in step["rating_rows"]] == ([4] if step["answer"] in ("4", "5") else []), step
    assert [row["rating"] for row in rating_rows(r)] == [4]


@pytest.mark.parametrize("name", [pytest.param(n, id=n, marks=replay(n)) for n in ("qa-fail-close", "rating-answers")])
def test_an_event_row_with_the_same_task_id_does_not_stop_the_rating_row_and_a_second_rating_writes_nothing(replays, name):
    r = replays.get(KEYS[name])
    clean_run(r)
    lines = [json.loads(line) for line in log_bytes(r).decode("utf-8").splitlines() if line.strip()]
    posted = [(i, row) for i, row in enumerate(lines) if row.get("kind") in ("event", "rating")]
    found = [row for _, row in posted if row["kind"] == "event"]
    assert found and {row["task_id"] for _, row in posted} == {task_of(r)}, posted  # events and the rating, one task id
    (index, rating), = [(i, row) for i, row in posted if row["kind"] == "rating"]
    assert index > max(i for i, row in posted if row["kind"] == "event") and rating["rating"] == 4, posted
    asked = questions(r)
    if name == "rating-answers":  # the dialog asked again for the same task after the row: "5 - Fully met" is not written
        assert [s["answer"] for s in rating_steps(r)][-2:] == ["4", "5"] and len(asked) == len(ANSWERS)
        assert rating["tool_use_id"] == asked[-2]["tool_use_id"] != asked[-1]["tool_use_id"], (rating, asked[-2:])
        assert [row["rating"] for row in rating_steps(r)[-1]["rating_rows"]] == [4]
