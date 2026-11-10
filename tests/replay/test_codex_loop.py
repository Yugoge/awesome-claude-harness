"""D31's acceptance replays of the Codex review loop (plan4/codex-review-loop.md, "Acceptance").

Each replay plays QA's `--codex` path against a stub Codex (tests/replay/drivers/_codex.py). The driver reads
every rule QA follows from the sentence of the command text that states it (commands/close.md Step 2's CODEX
REVIEW paragraph, its verdict branches and transcript bullets; commands/commit.md Step 6's Codex paragraph), so
what a replay shows is what the committed text makes QA do. What each test reads is the replay's own record
(facts.json: the rules read, every Codex call with its prompt and answer, the producer dispatches, the written
close or commit-QA report), never a list kept here of what the loop should have done beyond the owner's expected
outcomes below:

(1) a stub Codex answers one blocker plus five style and edge items: the producer is dispatched again once,
    round 2 only checks the blocker (a re-review of that flip item with the diff the repair made, not a new
    complete pass), and the cycle closes with the remaining items on the close report's follow-up list;
(2) a stub Codex returns a new item on every call: the cycle closes after round 3 (nothing below blocker
    reopens it; what is still open goes to the follow-up list);
(3) `/commit --codex` where the stub Codex rejects for a style reason: the commit is approved (committed) and the
    finding is classified (in_scope_real_bug, in_scope_minor, out_of_scope or nitpick) with a one-line reason,
    not treated as a veto.

Each replay has a negative check: the same replay against the BASE text of the command (commands/close.md or
commands/commit.md at d64fa96, before the loop), in a copy of the tree under test, stops with a RuleError that
names the sentence the text lacks, so a revert of the loop fails the suite. Replays (1) to (3) run with the tree's
settings ("shipped") and armed (G1-G3 block); the negative checks run shipped, and fail before any pipeline
runs.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

import pytest

from tests.replay import sandbox, suite
from tests.replay.drivers import _codex as C

BASE = "d64fa96"   # master after train 2: the command texts before the loop (D31)
INCLUDE = "templates/prompt-includes/codex-consultation.md"

FLIP = suite.Scenario("D31 (1) /close --codex, one blocker and five style and edge items", "close",
                      (("variant", "codex-flip-items"),), ("dev", "close"), 150)
ENDLESS = suite.Scenario("D31 (2) /close --codex, a new item every round", "close",
                         (("variant", "codex-endless"),), ("dev", "close"), 230)
STYLE = suite.Scenario("D31 (3) /commit --codex, a Codex REJECT for style", "commit",
                       (("variant", "codex-style-reject"),), ("dev", "close", "commit"), 260)


def _cases(scn: suite.Scenario) -> list:
    return [pytest.param(suite.replay_key(scn, s), id=s, marks=pytest.mark.replay(suite.replay_key(scn, s), scn.cost))
            for s in suite.SETTINGS]


def _compliant(r) -> None:
    """The replay ran to its terminal with 0 gate blocks and 0 hook errors (as test_pipelines.py asks)."""
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert not r.blocks, "a compliant run met a gate block:\n" + r.explain()
    assert not r.hook_errors, "a compliant run met a hook error:\n" + r.explain()
    assert r.reached(), "a pipeline did not reach its terminal:\n" + r.explain()


def _facts(r, key: str) -> list:
    return [f["value"] for f in r.facts if f["key"] == key]


def _last_line(text: str) -> str:
    return next(line for line in reversed(text.split("\n")) if line.strip())


def _findings_by_section(report: str) -> list:
    """The ids of the `## Findings` lines of each section of the close report (an `F1: ...` detail's first word)."""
    out = []
    for part in report.split("## Close attempt")[1:]:
        m = re.search(r"^## Findings\n((?:- .*\n?)+)", part, re.M)
        out.append([l[2:].split(": ", 2)[1] for l in m.group(1).strip().split("\n")] if m else [])
    return out


# ---------------------------------------------------------------- the rules, read from the committed text

def test_the_rules_the_replays_follow_are_the_rulings_in_the_committed_text():
    """The sentences the driver reads state the rulings of plan4/codex-review-loop.md (rules 2, 3, 5, 6 and 7)."""
    close = C.CloseRules.from_text(open(os.path.join(suite.REPO, "commands/close.md"), encoding="utf-8").read())
    assert close.severities == ("blocker", "high", "medium", "edge", "style")
    assert close.classes == ("in_scope_real_bug", "in_scope_minor", "out_of_scope", "nitpick")
    assert close.prelude == ("USER REQUIREMENT", "SCOPE", "OUT OF SCOPE")
    assert close.flip == {"blocker", "high", "medium"} and close.flip_class == "in_scope_real_bug"
    assert close.complete_round == 1 and close.review_rounds == (2, 3) and close.cap == 3
    assert close.new_in_review == {"blocker", "high"}
    assert close.listed_severities == {"edge", "style"} and close.listed_classes == {"in_scope_minor", "out_of_scope"}
    assert close.transcript_classes == {"nitpick"}
    commit = C.CommitRules.from_text(open(os.path.join(suite.REPO, "commands/commit.md"), encoding="utf-8").read())
    assert commit.classes == close.classes
    assert commit.reject_severities == {"blocker", "high"} and commit.never_decide == {"style", "edge", "nitpick"}
    for guard in commit.guards:   # "the secret and residue guarantees stay with ..." names files that exist
        assert os.path.isfile(os.path.join(suite.REPO, guard)), guard


def test_each_pipeline_prompt_names_the_one_shared_include_and_it_exists():
    assert os.path.isfile(os.path.join(suite.REPO, INCLUDE))
    for command in ("close", "commit", "codex"):
        text = open(os.path.join(suite.REPO, "commands", command + ".md"), encoding="utf-8").read()
        assert INCLUDE in text, f"commands/{command}.md does not name {INCLUDE}"


def test_the_scripted_runs_fit_the_text():
    """A script whose intent the text's rules contradict, or whose new items would not outlast the cap, is refused."""
    rules = C.CloseRules.from_text(open(os.path.join(suite.REPO, "commands/close.md"), encoding="utf-8").read())
    for script in (C.FLIP_ITEMS, C.ENDLESS):
        C.check_script(rules, script)
    short = C.Script("a stub that gives up before the cap", tuple(i for i in C.ENDLESS.items if i.appears <= rules.cap),
                     new_in_review=True)
    with pytest.raises(C.RuleError, match="cap"):
        C.check_script(rules, short)


def _text(name: str) -> str:
    with open(os.path.join(suite.REPO, "commands", name + ".md"), encoding="utf-8") as fh:
        return fh.read()


def _changed(text: str, old: str, new: str) -> str:
    """`text` with the one place that reads `old` (any run of whitespace, a line break included, standing for a space)
    reading `new`."""
    rx = re.compile(r"\s+".join(re.escape(w) for w in old.split(" ")))
    assert len(rx.findall(text)) == 1, f"{old!r} is not in the text once; the mutation below no longer applies"
    return rx.sub(lambda _m: new, text)


@pytest.mark.parametrize("command, old, new", [
    # the cap and the re-review rounds disagree (a text half edited)
    ("close", "After round 3 nothing below blocker reopens the cycle", "After round 5 nothing below blocker reopens the cycle"),
    # a re-review that starts from scratch
    ("close", "give Codex the earlier round's flip items from the close report", "give Codex the whole task again"),
    ("close", "Never ask for a new complete pass.", ""),
    # the old 2-5 flip item demand and the style demand
    ("close", "Flip items are the blocker, high and medium findings", "Flip items are 2-5 actionable items"),
    # a Codex NO with no flip item is a finding again: the veto
    ("close", "A `CODEX: NO` with no flip item opens none.", ""),
    ("commit", "A Codex REJECT is a finding, not a verdict.", "A substantive Codex REJECT flips you to REJECT."),
    ("commit", "Only a blocker or high finding", "Only a blocker or style finding"),
    ("commit", "style, edge and nitpick findings go in the report and never decide the verdict",
     "style findings go in the report"),
])
def test_a_reworded_or_reverted_sentence_stops_the_driver_before_it_plays(command, old, new):
    """The driver reads every rule from its sentence: a text that drops it or words it otherwise raises RuleError."""
    text = _changed(_text(command), old, new)
    rules = C.CloseRules if command == "close" else C.CommitRules
    with pytest.raises(C.RuleError):
        parsed = rules.from_text(text)
        (C.check_script if command == "close" else C.check_commit_script)(
            parsed, *(C.FLIP_ITEMS, ) if command == "close" else (C.STYLE_REJECT, ))


def test_a_text_that_contradicts_the_scripted_run_is_refused():
    """The text still states every rule, but one of them does something else with a scripted item than the
    scenario means: medium findings no longer flip (replay 2's first item), a style finding rejects (replay 3)."""
    no_medium = C.CloseRules.from_text(_changed(_text("close"), "blocker, high and medium findings with a realistic trigger",
                                                  "blocker and high findings with a realistic trigger"))
    with pytest.raises(C.RuleError, match="N1"):
        C.check_script(no_medium, C.ENDLESS)
    style_rejects = C.CommitRules.from_text(_text("commit"))
    style_rejects = C.CommitRules(**{**style_rejects.__dict__, "reject_severities": frozenset({"blocker", "high", "style"}),
                                     "never_decide": frozenset({"edge", "nitpick"})})
    with pytest.raises(C.RuleError, match="S1"):
        C.check_commit_script(style_rejects, C.STYLE_REJECT)


# ---------------------------------------------------------------- replay 1

@pytest.mark.parametrize("key", _cases(FLIP))
def test_one_blocker_and_five_items_the_producer_runs_once_and_round_2_checks_the_blocker(replays, key):
    r = replays.get(key)
    _compliant(r)
    rounds, loop = _facts(r, "codex round"), r.fact("codex loop")
    rules = r.fact("codex rules")
    assert rules["flip"] == ["blocker", "high", "medium"] and rules["cap"] == 3 and rules["review_rounds"] == [2, 3]
    ids = [i.id for i in C.FLIP_ITEMS.items]
    blocker, rest = ids[0], ids[1:]
    assert len(rest) == 5 and [i.severity for i in C.FLIP_ITEMS.items[1:]] == ["style", "style", "edge", "edge", "style"]
    # Round 1: one complete pass; Codex lists all six; only the blocker is a finding of the round
    first, second = rounds
    assert first["kind"] == "complete_pass" and first["asked_items"] == [] and first["reported"] == ids
    assert first["flips"] == [blocker] and first["listed"] == rest and first["close_verdict"] == "CLOSE_FINDINGS: 1 items"
    assert first["prompt"].startswith("USER REQUIREMENT: ")
    # The producer is dispatched again once, for the blocker alone
    assert loop["producer_dispatches"] == 1, loop["producer_dispatches"]
    routed = _facts(r, "routed")
    assert [(x["role"], x["new"]) for x in routed] == [("dev", 1)] and "round 1" in routed[0]["label"]
    # Round 2: a re-review of the blocker with the diff the repair made, not a new complete pass
    assert second["kind"] == "re_review" and second["asked_items"] == [blocker]
    assert second["prompt"].count("EARLIER ITEM") == 1 and "EARLIER ITEM " + blocker in second["prompt"]
    for item in C.FLIP_ITEMS.items[1:]:   # none of the five (not the items already on the follow-up list)
        assert item.id not in second["prompt"] and item.title not in second["prompt"], item.id
    assert C.FLIP_ITEMS.item(blocker).repair.strip() in second["prompt"]   # the diff since the repair
    assert second["diff_files"] == ["toy/__init__.py"]
    assert second["prompt"].startswith("USER REQUIREMENT: ") and "SCOPE: " in second["prompt"]
    assert second["statuses"] == {blocker: "fixed"} and second["reported"] == [] and second["flips"] == []
    assert loop["codex_calls"] == 2 and loop["qa_rounds"] == 2
    # The cycle closes, the rest listed with severity and classification
    assert loop["verdicts"] == ["CLOSE_FINDINGS: 1 items", "CLOSE: YES - with disclosures: 1 items"]
    report = loop["report"]
    assert _last_line(report) == "CLOSE: YES - with disclosures: 1 items"
    assert C.followup_items(report) == {i.id: (i.severity, i.judge[0]) for i in C.FLIP_ITEMS.items[1:]}
    assert _findings_by_section(report) == [[blocker], []]   # the five never became a finding
    assert r.terminal("close")["reached"], r.terminal("close")


# ---------------------------------------------------------------- replay 2

@pytest.mark.parametrize("key", _cases(ENDLESS))
def test_a_new_item_every_round_the_cycle_closes_after_round_3(replays, key):
    r = replays.get(key)
    _compliant(r)
    rounds, loop = _facts(r, "codex round"), r.fact("codex loop")
    assert r.fact("codex rules")["cap"] == 3
    n1, n2, n3 = [f"N{k}" for k in (1, 2, 3)]
    # Exactly three Codex calls and three QA rounds, though the stub had a new item for two more
    assert [c["kind"] for c in rounds] == ["complete_pass", "re_review", "re_review"]
    assert loop["codex_calls"] == 3 and loop["qa_rounds"] == 3, (loop["codex_calls"], loop["qa_rounds"])
    assert loop["never_reported"] == ["N4", "N5"]
    # A re-review is given the earlier round's flip items alone (round 3: N2, not N1) and the diff since
    assert [c["asked_items"] for c in rounds] == [[], [n1], [n2]]
    assert all(c["prompt"].count("EARLIER ITEM") == len(c["asked_items"]) for c in rounds)
    assert C.ENDLESS.item(n1).repair.strip() in rounds[1]["prompt"]
    # The stub reports a new item each time; before the cap it is a finding, at the cap it is listed
    assert [c["reported"] for c in rounds] == [[n1], [n2], [n3]]
    assert [c["flips"] for c in rounds] == [[n1], [n2], []]
    assert rounds[2]["statuses"] == {n2: "not fixed"} and rounds[2]["listed"] == [n2, n3]
    assert [c["close_verdict"] for c in rounds] == ["CLOSE_FINDINGS: 1 items", "CLOSE_FINDINGS: 1 items",
                                                   "CLOSE: YES - with disclosures: 2 items"]
    # The producer ran for round 1's and round 2's finding, and not for round 3's
    assert loop["producer_dispatches"] == 2
    assert [("round 1" in x["label"], "round 2" in x["label"]) for x in _facts(r, "routed")] == [(True, False), (False, True)]
    assert loop["verdicts"] == [c["close_verdict"] for c in rounds]
    report = loop["report"]
    assert _last_line(report) == "CLOSE: YES - with disclosures: 2 items"
    assert C.followup_items(report) == {n2: ("high", "in_scope_real_bug"), n3: ("high", "in_scope_real_bug")}
    assert _findings_by_section(report) == [[n1], [n2], []]
    assert r.terminal("close")["reached"], r.terminal("close")


# ---------------------------------------------------------------- replay 3

@pytest.mark.parametrize("key", _cases(STYLE))
def test_commit_codex_rejects_for_style_the_commit_is_approved_and_the_finding_classified(replays, key):
    r = replays.get(key)
    _compliant(r)
    rules, codex = r.fact("codex rules"), r.fact("codex round")
    assert rules["reject_severities"] == ["blocker", "high"] and set(rules["never_decide"]) == {"style", "edge", "nitpick"}
    # Codex rejected, for one style finding
    finding = C.STYLE_REJECT.items[0]
    assert finding.severity == "style"
    assert codex["verdict_line"] == "CODEX: REJECT" and codex["reported"] == [finding.id] and codex["deciding"] == []
    assert f"severity: {finding.severity}" in codex["answer"]
    # ... and QA approved: one round, no REJECT routed, no grant revoked, the commit landed
    assert _facts(r, "commit QA round") == [{"round": 1, "verdict": "COMMIT: APPROVE"}]
    assert r.fact("commit")["commit_status"] == "committed", r.fact("commit")
    assert not [e for e in r.hook_events() if "revoke grant" in (e.get("label") or "")]
    # The finding is in the report, classified with a one-line reason; it decided nothing
    report = r.fact("codex commit")["report"]
    classification, reason = finding.judge
    assert classification in rules["classes"]    # one of the four the text names
    line = next(l for l in report.split("\n") if l.startswith(f"[Codex] {finding.id} "))
    assert f"severity: {finding.severity}" in line and f"classification: {classification}" in line
    assert re.search(r"reason: \S.*$", line), line
    assert "codex_status: ok" in report and _last_line(report) == "COMMIT: APPROVE"
    assert r.fact("codex commit")["guards_exist"] and all(r.fact("codex commit")["guards_exist"].values())
    assert r.terminal("commit")["reached"], r.terminal("commit")


# ---------------------------------------------------------------- the negative checks: the base text of the command

@pytest.fixture(scope="module")
def base_runner(tmp_path_factory):
    """A runner whose tree under test is a copy of this tree with commands/close.md and commands/commit.md as they
    were at BASE, before the loop. The drivers are this tree's; only the command texts differ."""
    missing = suite.preconditions()
    if missing:
        pytest.fail("the replay suite cannot run here: " + "; ".join(missing), pytrace=False)
    root = tmp_path_factory.mktemp("codex-base")
    tree = os.path.join(str(root), "tree")
    shutil.copytree(suite.REPO, tree, symlinks=True, ignore=sandbox.COPY_IGNORE)
    for name in ("close", "commit"):
        shown = subprocess.run(["git", "-C", suite.REPO, "show", f"{BASE}:commands/{name}.md"], capture_output=True,
                               text=True)
        assert shown.returncode == 0, f"git show {BASE}:commands/{name}.md: {shown.stderr.strip()}"
        with open(os.path.join(tree, "commands", name + ".md"), "w", encoding="utf-8") as fh:
            fh.write(shown.stdout)
    runner = suite.Runner(os.path.join(str(root), "work"), tree=tree, workers=1)
    yield runner
    runner.guard.close()


@pytest.mark.parametrize("scn, missing", [
    pytest.param(FLIP, "CODEX REVIEW", id="replay-1-close-flip-items"),
    pytest.param(ENDLESS, "CODEX REVIEW", id="replay-2-close-endless"),
    pytest.param(STYLE, "A Codex REJECT is a finding, not a verdict", id="replay-3-commit-style-reject"),
])
def test_the_base_text_of_the_command_fails_the_replay(base_runner, scn, missing):
    """A command text without the loop (the base: 2-5 flip items and from-scratch rounds in /close, a Codex veto
    in /commit) is refused by the driver before any pipeline runs, naming the sentence it lacks."""
    r = base_runner.run(scn, "shipped")
    err = r.summary.get("driver_error", "")
    assert r.rc != 0 and err, "the replay of the base text passed:\n" + r.explain()
    assert "RuleError" in err and missing in err, err[-1200:]
    assert not r.reached() and r.fact("codex loop") is None and r.fact("codex commit") is None
    assert r.fact("close QA round") is None and r.fact("commit QA round") is None   # no pipeline ran


def test_the_replays_name_the_text_they_were_run_against():
    """Guards the negative checks' fixture: the base texts differ from this tree's, in the loop."""
    for name, marker in (("close", "CODEX REVIEW (only with"), ("commit", "A Codex REJECT is a finding, not a verdict.")):
        base = subprocess.run(["git", "-C", suite.REPO, "show", f"{BASE}:commands/{name}.md"], capture_output=True, text=True)
        assert base.returncode == 0, base.stderr
        assert marker not in base.stdout
        assert marker in open(os.path.join(suite.REPO, "commands", name + ".md"), encoding="utf-8").read()
