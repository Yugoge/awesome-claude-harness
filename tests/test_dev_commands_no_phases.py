"""Owner ruling D33 is in the prompt files: parallel lanes inside one cycle stay, phases and deferred parts never.

Every requested outcome is delivered in the same cycle and the cycle ends only when all are done. The rule has its
home in commands/dev.md ("One cycle, no phases") and commands/dev-overnight.md ("Delivery rule"); the BA-validation
QA dispatch of both fails a plan that phases or defers a requested outcome inside the existing scope_alignment
dimension (no sixth dimension); /dev's Steps 16-17 and /dev-overnight's Steps 17 and 21 have no exit with an outcome
left over; /do delivers the whole task this turn; /redev and /dev-command are /dev and say so. A replay scripts its
agents, so it cannot show that a real QA agent fails a phased plan: the text is the evidence, and it is read here from
the tree under test. One more guard rides along: the frontmatter of the five /dev-family command files must parse as
YAML (a colon and a space inside a plain description once made redev.md's invalid and nothing caught it).

Each assertion is a helper that returns its problems. The real files must give none; the mutation tests at the end
feed the same helpers a deliberately bad text (built here, so they hold whatever the files say) and require every
one to be flagged, so an edit cannot weaken a check silently.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import NamedTuple

import pytest
import yaml

from tests.replay import cmdtext

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ROOT / "commands"

FIVE_DIMENSIONS = ("evidence_quality", "scope_alignment", "investigation_completeness", "affected_file_accuracy",
                   "spec_text_vs_execution_drift")


def _read(name: str) -> str:
    return (COMMANDS / name).read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(text: str, heading: str, problems: list[str]) -> str:
    try:
        return cmdtext.section(text, heading)
    except cmdtext.TextNotFound as err:
        problems.append(f"no section: {err}")
        return ""


# --- where the ruling is carried: sections, their exact text, and what they must not say -----------------------------

class Spot(NamedTuple):
    heading: str | None                 # the section (cmdtext.section); None: anywhere in the file
    fragments: tuple[str, ...]          # text the spot must hold, whitespace-normalised
    lead: str | None = None             # when set, all fragments sit in the one paragraph that starts with this
    forbidden: tuple[str, ...] = ()     # case-insensitive patterns the spot must not match


DEV_RULE = (
    "Parallel lanes are how one cycle carries several outcomes; sequential phases are not.",
    "Every requested outcome is delivered in this cycle, and the cycle ends only when all of them are done.",
    "splits a requested outcome into sequential phases",
    "defers a part of it",
    '"phase 2"', '"MVP first"', '"for a later cycle"',
    "asks the owner to open another `/dev` session",
    "goes back through Step 16 until it is",
    'never carries "future work" for a requested outcome',
)

OVERNIGHT_RULE = (
    "Parallel pipelines inside one cycle stay.",
    "Every outcome the user's spec or request asks for is delivered in the same cycle",
    'no sequential phases, no deferred part, no "phase 2", no "MVP first", no work "for a later cycle"',
    "the owner is never asked to open more sessions",
    "A pipeline leaves Step 17 only on a QA pass.",
    "lists a requested outcome as left for a later cycle",
)

CONTRACTS: dict[str, tuple[Spot, ...]] = {
    "dev.md": (
        # the home of the rule; the fan-out into parallel lanes stays beside it
        Spot("Requirement Decomposition & Fan-Out",
             ("fans them out to N parallel one-issue lanes inside the SAME cycle",)),
        Spot("Requirement Decomposition & Fan-Out", DEV_RULE, lead="**One cycle, no phases.**"),
        # the BA's goal line and the orchestrator's own plan validation
        Spot("Step 4c", ("delivers every requested outcome in this cycle (no phases, nothing deferred)",)),
        Spot("Step 6", ("the plan delivers every requested outcome in this cycle",
                        "a plan that splits a requested outcome into sequential phases or defers any part of it",
                        "fails validation")),
        # no exit with an outcome left over, and no continuation-spec branch
        Spot("Step 16", ("the loop repeats until QA passes", "There is no other exit.")),
        Spot("Step 17", ("This step is reached only when every requested outcome passes",
                         "## Follow-up Suggestions (outside the request)",
                         "Every requested outcome is reported delivered above; none is listed here as left for later.",
                         "the next command is `/close <task-id>`",
                         "nothing requested is left for later"),
             forbidden=(r"continuation", r"spec-update", r"next steps")),
    ),
    "dev-overnight.md": (
        Spot(None, ("The issues the user's spec describes are Tier 1 and always get a pipeline.",)),
        Spot("Delivery rule", OVERNIGHT_RULE),
        # triage may skip or defer only what the session found itself; the time guard agrees
        Spot("Step 6", ('"skip"` and `"defer"` apply only to findings PM discovered on its own that nobody requested; '
                        "they are never used for an outcome the user's spec or request asks for",
                        "an outcome the user's spec or request asks for is never dropped")),
        Spot("Step 17", ("this loop repeats until its QA passes", "There is no iteration cap and no other exit.")),
        Spot("Step 21", ("Nothing in the summary, Recommendations included, lists a requested outcome as left for a "
                         "later cycle", "hold only findings the session discovered itself")),
    ),
    "do.md": (
        Spot("Step 2", ("The whole `TASK` is done this turn, with nothing left for later",
                        '`do.status` `"completed"` (Step 5) means exactly that',
                        "unfinished work is never reported as completed")),
        Spot("Step 3", ("leave `out_of_scope` findings (pre-existing issues, not part of the request) unfixed and "
                        "list them in the Step 4 summary",),
             forbidden=(r"separate cycle", r"defer")),
        Spot("Step 4", ("which out-of-scope findings were left unfixed",)),
    ),
    "dev-command.md": (
        # inherits the rule from /dev instead of restating it; it carries no continuation-spec branch of its own
        Spot(None, ('A `/dev` rule this file does not mention applies as written, including "One cycle, no phases"',
                    "every requested outcome is delivered in this cycle, with no sequential phases or deferred parts",
                    "read `<HARNESS_ROOT>/commands/dev.md` (again after a compaction) and follow it"),
             forbidden=(r"continuation", r"workflow update")),
        # no dispatch block of its own: the five-dimension enum lives in /dev Step 7, this line points at it
        Spot("Step 7", ("As `/dev` Step 7", "all five dimensions",
                        "the no-phases check inside `scope_alignment` among them")),
        Spot("Step 15", ("the loop repeats until QA passes",
                         "The Stop gate keeps the command open until the disposition is chain_pass",
                         "There is no other exit.")),
        Spot("Step 16", ("## Follow-up Suggestions (outside the request)",),
             forbidden=(r"continuation", r"workflow update", r"spec-update", r"next steps")),
    ),
    "redev.md": (
        Spot(None, ("every requested outcome is delivered in this cycle, with no sequential phases or deferred parts",
                    "Run the `/dev` workflow for the requirement in `$ARGUMENTS`",
                    "read `<HARNESS_ROOT>/commands/dev.md` and follow it")),
    ),
}


def contract_problems(text: str, spots: tuple[Spot, ...], label: str) -> list[str]:
    problems: list[str] = []
    for spot in spots:
        where = f"{label} {spot.heading or '(file)'}"
        body = text if spot.heading is None else _section(text, spot.heading, problems)
        if spot.lead is not None:
            paragraph = re.search(r"^" + re.escape(spot.lead) + r".*$", body, re.M)
            if paragraph is None:
                problems.append(f"{where}: no paragraph that starts {spot.lead!r}")
                continue
            body = paragraph.group(0)
        flat = _flat(body)
        problems.extend(f"{where}: missing {fragment!r}" for fragment in spot.fragments if fragment not in flat)
        for pattern in spot.forbidden:
            hit = re.search(pattern, body, re.I)
            if hit:
                problems.append(f"{where}: must not say {hit.group(0)!r}")
    return problems


def contract_doc(spots: tuple[Spot, ...]) -> str:
    """A minimal document of the shape the contract describes (the good text the mutation tests start from)."""
    grouped: dict[str | None, list[Spot]] = {}
    for spot in spots:
        grouped.setdefault(spot.heading, []).append(spot)
    parts: list[str] = []
    for heading, group in grouped.items():
        if heading is not None:
            parts.append(f"## {heading}")
        for spot in group:
            if spot.lead:
                parts.append(spot.lead + " " + " ".join(spot.fragments))
            # a fragment that is itself a heading sits in a fence, as in the report template of the real file
            parts.extend(f"```markdown\n{f}\n```" if f.startswith("#") else f for f in spot.fragments if not spot.lead)
    return "\n\n".join(parts) + "\n"


# --- the BA-validation QA dispatch: five dimensions, the check inside scope_alignment -------------------------------

_HEADER = re.compile(r"Verify these (\d+) dimensions")
_ITEM = re.compile(r"^[ \t]*(\d+)\.[ \t]+([A-Z][A-Z0-9\- ]*[A-Z0-9]):", re.M)
_ENUM = re.compile(r"'dimension':\s*'([^']+)'")
_SCOPE_CHECK = re.compile(r"\bFAIL (?:any|a) plan that splits a requested outcome into sequential phases "
                          r"or defers any part of it")

# The dispatch of each command: the step that holds it and what its SCOPE ALIGNMENT says beyond the shared check.
QA_DISPATCHES = {
    "dev.md": ("Step 7", ("parallel one-issue lanes are not phases",)),
    "dev-overnight.md": ("Step 10", ("'dimension: scope_alignment' objection", "verdict 'fail'")),
}


def qa_dispatch(text: str, heading: str) -> str:
    """The BA-validation QA dispatch template of a step (the one fenced block that holds the QA mode banner)."""
    block = cmdtext.block(text, heading, anchor="BA-VALIDATION MODE")
    assert 'subagent_type: "qa"' in block, f"{heading}: the BA-validation block is not a QA dispatch"
    return block


def dimension_items(prompt: str) -> list[tuple[int, str, str]]:
    """(number, title, text) of each numbered dimension between the 'Verify these N dimensions' header and the JSON."""
    header = _HEADER.search(prompt)
    tail = prompt[header.end():] if header else ""
    stop = tail.find("Return JSON")
    body = tail if stop < 0 else tail[:stop]
    found = list(_ITEM.finditer(body))
    return [(int(m.group(1)), m.group(2), body[m.end():found[i + 1].start() if i + 1 < len(found) else len(body)])
            for i, m in enumerate(found)]


def dimension_problems(prompt: str) -> list[str]:
    """Exactly the five existing dimensions, in the dispatch's header, list and JSON enum."""
    header = _HEADER.search(prompt)
    if header is None:
        return ["no 'Verify these N dimensions' header"]
    problems: list[str] = []
    if int(header.group(1)) != 5:
        problems.append(f"the header says {header.group(1)} dimensions, not 5")
    items = dimension_items(prompt)
    if [number for number, _, _ in items] != [1, 2, 3, 4, 5]:
        problems.append(f"the list numbers are {[number for number, _, _ in items]}, not 1-5")
    named = [re.sub(r"[^a-z0-9]+", "_", title.lower()) for _, title, _ in items]
    if named != list(FIVE_DIMENSIONS):
        problems.append(f"the listed dimensions are {named}, not {list(FIVE_DIMENSIONS)}")
    enum = _ENUM.search(prompt)
    if enum is None:
        problems.append("no JSON 'dimension' enum in the dispatch")
    elif enum.group(1).split("|") != list(FIVE_DIMENSIONS):
        problems.append(f"the JSON dimension enum is {enum.group(1).split('|')}, not {list(FIVE_DIMENSIONS)}")
    return problems


def scope_check_problems(prompt: str, extra: tuple[str, ...] = ()) -> list[str]:
    """Dimension 2 (SCOPE ALIGNMENT) fails a plan that phases or defers a requested outcome; no other dimension does."""
    items = {number: (title, text) for number, title, text in dimension_items(prompt)}
    if 2 not in items or items[2][0] != "SCOPE ALIGNMENT":
        return ["dimension 2 is not SCOPE ALIGNMENT"]
    problems: list[str] = []
    scope = _flat(items[2][1])
    if not _SCOPE_CHECK.search(scope):
        problems.append("SCOPE ALIGNMENT does not say: FAIL a plan that splits a requested outcome into sequential "
                        "phases or defers any part of it")
    for example in ("phase 2", "MVP first", "later cycle"):
        if example not in scope:
            problems.append(f"SCOPE ALIGNMENT names no {example!r}")
    problems.extend(f"SCOPE ALIGNMENT: missing {fragment!r}" for fragment in extra if fragment not in scope)
    for number, (title, text) in items.items():
        if number != 2 and re.search(r"sequential phases|defers", text):
            problems.append(f"dimension {number} ({title}) carries the phasing check, not SCOPE ALIGNMENT")
    return problems


# --- no instruction hands unfinished work to a later cycle ------------------------------------------------------------

# Phrases that would license phasing or deferral of a requested outcome. The bare word "phase" is not one of them: QA
# Phase 5, the overnight state's `phase` field and "parallel BA phase" are technical uses, not phasing of the request.
LICENSING = re.compile(
    r"continuation[ -]specs?|spec continuation"
    r"|\bnext steps\b"
    r"|\bphase (?:2|two)\b|\b(?:second|next|later) phase\b|\bphas(?:ed|ing)\b|\bin phases\b"
    r"|\bmvp[ -]first\b"
    r"|\b(?:separate|later|future|follow-?up) cycles?\b"
    r"|\bdefer\w*"
    r"|\bhand(?:s|ed|ing)?[ -]off\b[^.]{0,60}\bunfinished|\bunfinished\b[^.]{0,60}\bhand(?:s|ed|ing)?[ -]off\b"
    r"|\bfor later\b"
    r"|\b(?:open|start|run)\s+(?:another|more|new)\s+(?:`?/dev`?\s+)?sessions?\b",
    re.I)
# A sentence that also forbids or negates is the rule text (or a pointer to it), not a licence.
NEGATION = re.compile(r"\b(?:no|never|nothing|none|nor|neither|without|fails?|forbid\w*|refus\w*|reject\w*"
                      r"|prohibit\w*)\b|\bFAIL\b", re.I)
# The only technical uses of these words: PM triage of findings the session discovered itself (the Step 6 contract
# above limits skip and defer to those) and QA's own numbered phases.
TECHNICAL = re.compile(r"skip/defer|\"defer\"|triage-deferred|deferred by PM triage|\bQA Phase \d+\b")
_SENTENCES = re.compile(r"(?<=[.!?])\s+(?=[A-Z`\"'(*\[<])")


def licensing_scan(text: str) -> tuple[list[tuple[int, str, str]], list[tuple[int, str]]]:
    """(licences, excused): sentences that hold a licensing phrase and do not negate it; and those that do."""
    licences: list[tuple[int, str, str]] = []
    excused: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        for sentence in _SENTENCES.split(line):
            scrubbed = TECHNICAL.sub(" ", sentence)
            phrase = LICENSING.search(scrubbed)
            if phrase is None:
                continue
            if NEGATION.search(scrubbed):
                excused.append((number, phrase.group(0)))
            else:
                licences.append((number, phrase.group(0), sentence.strip()[:140]))
    return licences, excused


# === the real files =====================================================================================

def _spot_groups():
    for name, spots in CONTRACTS.items():
        for heading in dict.fromkeys(spot.heading for spot in spots):
            yield pytest.param(name, tuple(s for s in spots if s.heading == heading), id=f"{name}::{heading or 'file'}")


@pytest.mark.parametrize("name,spots", list(_spot_groups()))
def test_the_ruling_is_carried_where_it_was_put(name: str, spots: tuple[Spot, ...]) -> None:
    assert contract_problems(_read(name), spots, name) == []


@pytest.mark.parametrize("name", sorted(QA_DISPATCHES))
def test_ba_validation_dispatch_lists_exactly_the_five_dimensions(name: str) -> None:
    prompt = qa_dispatch(_read(name), QA_DISPATCHES[name][0])
    assert dimension_problems(prompt) == []
    schema = json.loads((ROOT / "schemas" / "ba-qa-report.v1.json").read_text(encoding="utf-8"))
    assert schema["properties"]["objections"]["items"]["properties"]["dimension"]["enum"] == list(FIVE_DIMENSIONS)


@pytest.mark.parametrize("name", sorted(QA_DISPATCHES))
def test_ba_validation_dispatch_fails_a_phased_plan_inside_scope_alignment(name: str) -> None:
    heading, extra = QA_DISPATCHES[name]
    assert scope_check_problems(qa_dispatch(_read(name), heading), extra) == []


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_no_instruction_hands_unfinished_work_to_a_later_cycle(name: str) -> None:
    licences, _ = licensing_scan(_read(name))
    assert licences == [], f"commands/{name} licenses phasing or deferral (line, phrase, sentence): {licences}"


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_the_licensing_scan_reads_the_rule_text_and_excuses_it(name: str) -> None:
    """Not vacuous: each file names the forbidden things in a negating sentence, and the scan sees and excuses it."""
    _, excused = licensing_scan(_read(name))
    assert excused, f"commands/{name} has no negated mention of phasing or deferral: the rule text is missing"


def test_redev_says_the_rule_in_the_words_the_other_files_pin() -> None:
    assert "every requested outcome is delivered in this cycle" in _flat(_read("redev.md"))


FRONTMATTER_FILES = ("dev.md", "dev-command.md", "dev-overnight.md", "redev.md", "do.md")
_FRONTMATTER = re.compile(r"---\n(.*?)\n---[ \t]*(?:\n|$)", re.S)


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that also refuses a key given twice (PyYAML otherwise keeps the last one silently)."""

    def construct_mapping(self, node, deep=False):
        keys = [self.construct_object(key, deep=True) for key, _ in node.value]
        twice = sorted({str(k) for k in keys if keys.count(k) > 1})
        if twice:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate key {twice}", node.start_mark)
        return super().construct_mapping(node, deep)


def frontmatter_problems(text: str) -> list[str]:
    """The frontmatter parses as YAML and holds a non-empty string `description` and `disable-model-invocation`."""
    block = _FRONTMATTER.match(text)
    if block is None:
        return ["no frontmatter block between two '---' lines at the top"]
    try:
        data = yaml.load(block.group(1), Loader=_StrictLoader)  # noqa: S506 (a SafeLoader subclass)
    except yaml.YAMLError as err:
        return [f"the frontmatter is not valid YAML: {' '.join(str(err).split())}"]
    if not isinstance(data, dict):
        return [f"the frontmatter is a {type(data).__name__}, not a mapping"]
    problems = [f"no {key!r} key" for key in ("description", "disable-model-invocation") if key not in data]
    if "description" in data and not (isinstance(data["description"], str) and data["description"].strip()):
        problems.append(f"'description' is {data['description']!r}, not a non-empty string")
    return problems


@pytest.mark.parametrize("name", FRONTMATTER_FILES)
def test_the_frontmatter_of_each_command_file_parses_as_yaml(name: str) -> None:
    assert frontmatter_problems(_read(name)) == []


# === mutation evidence: the same helpers must flag a deliberately bad text ==============================

GOOD_DISPATCH = """\
Agent(subagent_type: "qa")
  prompt: "
    You are the QA subagent in BA-VALIDATION MODE.

    Verify these 5 dimensions:

    1. EVIDENCE QUALITY: every factual claim needs evidence.

    2. SCOPE ALIGNMENT: compare BA's acceptance criteria with the requirement. FAIL any plan that splits a requested
    outcome into sequential phases or defers any part of it (a 'phase 2', an 'MVP first', work 'for a later cycle').
    Every requested outcome is delivered in this cycle; parallel one-issue lanes are not phases.

    3. INVESTIGATION COMPLETENESS: did BA do the audit the requirement asked for?

    4. AFFECTED-FILE ACCURACY: do the files exist?

    5. SPEC-TEXT-VS-EXECUTION DRIFT: does the AC text run as written?

    Return JSON: {'verdict': 'pass' or 'fail', 'objections': [{'dimension': 'ENUM'}]}
  "
""".replace("ENUM", "|".join(FIVE_DIMENSIONS))
GOOD_EXTRA = ("parallel one-issue lanes are not phases",)


def test_the_fixture_dispatch_is_accepted_so_that_every_flag_below_is_a_real_flag() -> None:
    assert dimension_problems(GOOD_DISPATCH) == []
    assert scope_check_problems(GOOD_DISPATCH, GOOD_EXTRA) == []


def test_dimension_helper_flags_a_fourth_dimension_list() -> None:
    fifth = r"^[ \t]*5\.[ \t]+SPEC-TEXT-VS-EXECUTION DRIFT:.*?(?=Return JSON)"
    four = re.sub(fifth, "", GOOD_DISPATCH, flags=re.S | re.M)
    four = four.replace("Verify these 5 dimensions", "Verify these 4 dimensions").replace(
        "|spec_text_vs_execution_drift'", "'")
    assert four != GOOD_DISPATCH and "SPEC-TEXT-VS-EXECUTION DRIFT:" not in four
    problems = dimension_problems(four)
    assert any("header says 4" in p for p in problems) and any("not 1-5" in p for p in problems)
    assert any("JSON dimension enum" in p for p in problems)
    # a four-dimension list whose header and list agree is still not the existing five
    assert dimension_problems(four.replace("Verify these 4 dimensions", "Verify these 5 dimensions"))


def test_dimension_helper_flags_a_sixth_dimension() -> None:
    sixth = "    6. PHASING CHECK: does the plan split the request into phases?\n\n    Return JSON"
    six = GOOD_DISPATCH.replace("    Return JSON", sixth, 1)
    six = six.replace("|spec_text_vs_execution_drift'", "|spec_text_vs_execution_drift|phasing_check'")
    assert six != GOOD_DISPATCH and "phasing_check" in six
    problems = dimension_problems(six)
    assert any("not 1-5" in p for p in problems) and any("JSON dimension enum" in p for p in problems)
    # a sixth dimension whose header and list agree is still not the existing five
    assert dimension_problems(six.replace("Verify these 5 dimensions", "Verify these 6 dimensions"))
    # a sixth entry in the enum alone is flagged too
    assert dimension_problems(GOOD_DISPATCH.replace("drift'", "drift|x'"))


def test_scope_helper_flags_a_check_that_is_weakened() -> None:
    weakened = re.sub(r"\bFAIL (any|a) plan", r"note \1 plan", GOOD_DISPATCH)
    assert weakened != GOOD_DISPATCH and scope_check_problems(weakened, GOOD_EXTRA)
    assert scope_check_problems(GOOD_DISPATCH.replace("sequential phases", "phases"), GOOD_EXTRA)
    assert scope_check_problems(GOOD_DISPATCH.replace("or defers any part of it", ""), GOOD_EXTRA)
    assert scope_check_problems(GOOD_DISPATCH.replace("phase 2", "stage two"), GOOD_EXTRA)
    assert scope_check_problems(GOOD_DISPATCH.replace("; parallel one-issue lanes are not phases", ""), GOOD_EXTRA)


def test_scope_helper_flags_a_check_that_is_dropped_or_moved_to_another_dimension() -> None:
    sentence = re.search(r"FAIL (?:any|a) plan.*?\)\.", GOOD_DISPATCH, re.S)
    assert sentence is not None
    dropped = GOOD_DISPATCH.replace(sentence.group(0), "")
    assert any("does not say" in p for p in scope_check_problems(dropped, GOOD_EXTRA))
    moved = dropped.replace("INVESTIGATION COMPLETENESS:", f"INVESTIGATION COMPLETENESS: {sentence.group(0)}", 1)
    problems = scope_check_problems(moved, GOOD_EXTRA)
    assert any("does not say" in p for p in problems) and any("dimension 3" in p for p in problems)


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_every_pinned_fragment_of_a_contract_is_load_bearing(name: str) -> None:
    spots = CONTRACTS[name]
    assert contract_problems(contract_doc(spots), spots, name) == [], "the fixture document meets its own contract"
    for index, spot in enumerate(spots):
        for position, fragment in enumerate(spot.fragments):
            kept = tuple(f for k, f in enumerate(spot.fragments) if k != position)
            mutated = spots[:index] + (spot._replace(fragments=kept),) + spots[index + 1:]
            problems = contract_problems(contract_doc(mutated), spots, name)
            assert any(f"missing {fragment!r}" in p for p in problems), \
                f"{name} {spot.heading}: dropping {fragment!r} goes unnoticed"


@pytest.mark.parametrize("name,last,words", [
    ("dev.md", "Step 17", ("continuation", "spec-update", "next steps")),
    ("dev-command.md", "Step 16", ("continuation", "workflow update", "spec-update", "next steps")),
])
def test_contract_flags_a_continuation_spec_branch_in_the_last_step(name: str, last: str, words: tuple) -> None:
    spots = CONTRACTS[name]
    assert spots[-1].heading == last, "the branch below is appended to the last section"
    good = contract_doc(spots)
    branch = ("**Workflow update.** When work is left over, emit a continuation spec through `/spec-update` and show "
              "the next steps.")
    bad = good + "\n" + branch + "\n"
    problems = contract_problems(bad, spots, name)
    for word in words:
        assert any(f"must not say {word!r}" in p.lower() for p in problems), word
    assert licensing_scan(bad)[0], "the licensing scan flags the same branch"


def test_do_contract_flags_the_old_separate_cycle_wording() -> None:
    spots = CONTRACTS["do.md"]
    good = contract_doc(spots)
    old = good.replace(spots[1].fragments[0], "defer `out_of_scope` to a separate cycle")
    assert old != good
    problems = contract_problems(old, spots, "do.md")
    assert any("must not say 'separate cycle'" in p for p in problems)
    assert any("must not say 'defer'" in p for p in problems)
    assert any("unfixed" in p for p in problems)
    assert licensing_scan(old)[0]


def test_overnight_contract_flags_a_triage_that_may_defer_a_requested_outcome() -> None:
    spots = CONTRACTS["dev-overnight.md"]
    good = contract_doc(spots)
    widened = good.replace("they are never used for an outcome the user's spec or request asks for",
                           "they may be used for an outcome that is too large")
    assert widened != good
    assert any("never used for an outcome" in p for p in contract_problems(widened, spots, "dev-overnight.md"))


@pytest.mark.parametrize("bad", [
    "- Unfinished work is handed off into a continuation spec; only complete work is reported.",
    "Emit spec continuation or the `/close` next step",
    "Show the owner a summary of the key changes and next steps.",
    "## Next Steps",
    "Phase 2: wire the remaining screens once the first part ships.",
    "Deliver the MVP first and the rest in phase two.",
    "Ship the first half now and do the second phase in the next /dev run.",
    "Fix `in_scope_real_bug` items; defer `out_of_scope` to a separate cycle.",
    "Park what is not finished and hand off the unfinished work to a later cycle.",
    "Whatever is left is saved for later.",
    "When time runs out, ask the owner to open another `/dev` session for the rest.",
    "The plan is phased: parts B and C follow after part A.",
], ids=lambda text: text[:32])
def test_the_scan_flags_text_that_licenses_phasing_or_deferral(bad: str) -> None:
    licences, _ = licensing_scan(bad)
    assert len(licences) == 1, bad


@pytest.mark.parametrize("good", [
    'No plan splits a requested outcome into sequential phases or defers a part of it (a "phase 2", an "MVP first").',
    "Nothing requested is left for later; every outcome is delivered in this cycle.",
    "FAIL any plan that defers any part of it to a later cycle.",
    "A plan that is phased fails validation.",
    "Never hand off unfinished work: the cycle ends only when all are done.",
])
def test_the_scan_excuses_a_sentence_that_forbids_what_it_names(good: str) -> None:
    licences, excused = licensing_scan(good)
    assert licences == [] and len(excused) == 1, good


@pytest.mark.parametrize("technical", [
    "Per-task manifest: the file QA Phase 5 reads active_tests[] from.",
    "`phase=pending`, `iteration=0`, `status=active`.",
    "Proceeding to parallel BA phase.",
    "The hook reads current_phase from the overnight state file.",
    "| Issues deferred by PM triage (skip/defer) | <issues_triage_deferred> |",
    "The finding goes to the cycle's triage-deferred list with PM's reason.",
])
def test_the_scan_leaves_technical_uses_of_phase_and_triage_alone(technical: str) -> None:
    assert licensing_scan(technical) == ([], []), technical


def test_the_scan_still_flags_a_deferral_that_borrows_the_triage_words() -> None:
    licences, _ = licensing_scan("Defer the second outcome by PM triage to the next cycle of the session.")
    assert licences


# a description whose plain scalar holds a colon and a space: not valid YAML (the redev.md defect)
_COLON_IN_PLAIN_SCALAR = (
    "---\n"
    "description: /redev is /dev when saving context: it re-enters the harness in the same conversation\n"
    'argument-hint: "[--codex] [--spec <path>] [<requirement>]"\n'
    "disable-model-invocation: true\n"
    "---\n\nBody.\n")


def test_the_frontmatter_helper_flags_a_colon_and_a_space_inside_a_plain_description() -> None:
    problems = frontmatter_problems(_COLON_IN_PLAIN_SCALAR)
    assert len(problems) == 1 and "not valid YAML" in problems[0], problems
    # the same description with the colon replaced (the repair), or quoted, is accepted
    assert frontmatter_problems(_COLON_IN_PLAIN_SCALAR.replace("context: it", "context - it")) == []
    assert frontmatter_problems(_COLON_IN_PLAIN_SCALAR.replace("description: /redev", 'description: "/redev').replace(
        "conversation\n", 'conversation"\n', 1)) == []


@pytest.mark.parametrize("bad,expected", [
    ("---\ndescription: x\n---\nBody.\n", "no 'disable-model-invocation' key"),
    ("---\ndisable-model-invocation: true\n---\nBody.\n", "no 'description' key"),
    ("---\ndescription:\ndisable-model-invocation: true\n---\nBody.\n", "not a non-empty string"),
    ("---\ndescription: '  '\ndisable-model-invocation: true\n---\nBody.\n", "not a non-empty string"),
    ("---\ndescription: 12\ndisable-model-invocation: true\n---\nBody.\n", "not a non-empty string"),
    ("---\ndescription: a\ndescription: b\ndisable-model-invocation: true\n---\nBody.\n", "duplicate key"),
    ("---\n- description\n- disable-model-invocation\n---\nBody.\n", "not a mapping"),
    ("description: x\ndisable-model-invocation: true\n\nBody.\n", "no frontmatter block"),
], ids=["no-disable-key", "no-description-key", "null-description", "blank-description", "number-description",
        "duplicate-key", "list", "no-fence"])
def test_the_frontmatter_helper_flags_a_missing_key_an_empty_description_or_a_broken_block(bad: str,
                                                                                             expected: str) -> None:
    problems = frontmatter_problems(bad)
    assert any(expected in p for p in problems), problems
