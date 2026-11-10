"""The Codex review loop of the owner's ruling D31, played by the /close and /commit drivers with a stub Codex.

A driver variant that runs QA's `--codex` path (drivers/close.py `codex-flip-items`, `codex-endless`;
drivers/commit.py `codex-style-reject`) plays QA from here. Nothing about the loop is kept in this module as
an outcome: each rule QA follows is read, at run time, from the sentence of the command text of the tree
under test that states it (QA's prompt block: commands/close.md Step 2, paragraph "CODEX REVIEW" and its
verdict branches and transcript bullets; commands/commit.md Step 6, the paragraph that begins "When
codex_required is true"). A sentence that is absent or worded otherwise, and a text whose rules contradict
what the scripted run needs, raise RuleError (a cmdtext.TextNotFound), so a reverted or reworded loop makes
the replay fail loudly (the driver's run() reads the rules before anything else runs).

What is scripted is the stub's side and QA's judgement, which are not rules of the text:
* `Script`: the findings the stub Codex reports, round by round, with the severity and realistic trigger
  each carries, the repair line that fixes it, QA's classification of it and the one-line reason, and what
  the scenario intends the text to do with it (`intent`, checked against what the text's rules make of it);
* `StubCodex`: answers the prompt QA sends, never a fixed list: a prompt that lists earlier items is a
  re-review and is answered per item (fixed when the diff the prompt carries holds the item's repair line);
  a prompt that lists none is a complete pass and is answered with every open item. Every call is recorded
  with its whole prompt and answer.

Observable facts the replay keeps (facts.json, read by tests/replay/test_codex_loop.py): "codex rules" (what
was read, and the sentence each value came from), "codex round" (one per Codex call: round number, what it
asked for, the prompt, the answer, QA's disposition of each finding), "codex loop" (QA rounds, producer
dispatches, the close report's text) and, for /commit, "codex commit".
"""
from __future__ import annotations

import json
import os
import re
import shlex
from dataclasses import dataclass, field

from .. import agents, cmdtext
from ..pipeline import utc_now


class RuleError(cmdtext.TextNotFound):
    """A rule of the loop the command text does not state, or states so that the scripted run cannot be played."""


# ---------------------------------------------------------------- reading the text

def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _words(listing: str) -> list[str]:
    """The words of 'blocker, high and medium'."""
    return re.findall(r"[a-z_]+", re.sub(r"\band\b|\bor\b", " ", listing.lower()))


def prompt_block(command_text: str, heading: str) -> str:
    """QA's prompt of a command: the one fenced block of `heading` that holds the obligation."""
    return cmdtext.block(command_text, heading, anchor="<obligation")


def bullets_after(block: str, head: str) -> tuple[str, list[str]]:
    """(the head line, the bullets) of the one paragraph of `block` that starts with `head`."""
    lines = block.split("\n")
    at = [i for i, line in enumerate(lines) if line.startswith(head)]
    if len(at) != 1:
        raise RuleError(f"QA's prompt holds {len(at)} paragraphs starting {head!r}, not one")
    out: list[str] = []
    for line in lines[at[0] + 1:]:
        if line.startswith("- "):
            out.append(line[2:].strip())
        elif line.startswith("  ") and out:
            out[-1] += " " + line.strip()
        else:
            break
    return flat(lines[at[0]]), out


def pick(items: list[str], start: str, what: str) -> str:
    hit = [flat(i) for i in items if i.startswith(start)]
    if len(hit) != 1:
        raise RuleError(f"{what}: {len(hit)} items start {start!r}, not one")
    return hit[0]


def grab(sentence: str, pattern: str, what: str) -> re.Match:
    """The match of `pattern` in the sentence, or the RuleError that names the clause the text lacks."""
    m = re.search(pattern, sentence)
    if not m:
        raise RuleError(f"{what}: the clause /{pattern}/ is absent from: {sentence[:300]}")
    return m


def _fill(template: str, n: int) -> str:
    return template.replace("<n>", str(n))


# ---------------------------------------------------------------- /close: rules

@dataclass
class CloseRules:
    """The rules commands/close.md Step 2's CODEX REVIEW gives QA, each with the sentence it came from."""
    severities: tuple
    classes: tuple
    prelude: tuple               # the headers every Codex prompt starts with
    scope: str
    out_of_scope: str
    gives: bool                  # QA also gives Codex the input paths, its assessment and the inspector findings
    verdict_lines: tuple         # the lines Codex ends with
    complete_round: int          # the round that is one complete pass
    flip: frozenset              # severities whose findings (with a trigger) can be flip items
    flip_class: str              # the classification a flip item has
    review_rounds: tuple         # the rounds that are re-reviews
    review_gives: tuple          # what a re-review is given
    repairs_input: str           # the prompt input that names the files the repairs touched
    new_in_review: frozenset     # severities of the new defects a re-review reports
    listed_severities: frozenset
    listed_classes: frozenset
    transcript_classes: frozenset
    cap: int                     # after this round nothing below blocker reopens the cycle
    yes_line: str                # the landed form of branch 1
    findings_form: str           # the round-open form
    disclosures_form: str
    followup_heading: str
    tags: tuple                  # [QA] [Codex]
    sentences: dict = field(default_factory=dict)

    def to_fact(self) -> dict:
        d = {k: (sorted(v) if isinstance(v, (set, frozenset)) else v) for k, v in self.__dict__.items()}
        return d

    @classmethod
    def from_text(cls, close_md: str) -> "CloseRules":
        block = prompt_block(close_md, "Step 2")
        head, items = bullets_after(block, "CODEX REVIEW (only with")
        S: dict = {"CODEX REVIEW": head}
        # Prelude, and what QA gives with it
        s = S["prelude"] = pick(items, "Prelude:", "CODEX REVIEW")
        headers = tuple(re.findall(r"\b(USER REQUIREMENT|OUT OF SCOPE|SCOPE)\b", s)[:3])
        if headers != ("USER REQUIREMENT", "SCOPE", "OUT OF SCOPE"):
            raise RuleError(f"the Prelude does not name USER REQUIREMENT, SCOPE and OUT OF SCOPE in order: {s[:300]}")
        m = grab(s, r"SCOPE is (.*?); OUT OF SCOPE is (.*?)\. Also give Codex", "Prelude")
        scope, oos = m.group(1), m.group(2)
        gives = "Also give Codex the input artifact paths, your assessment with its rationale and the inspector findings" in s
        verdicts = tuple(re.findall(r"`(CODEX: [A-Z]+)`", grab(s, r"Codex ends with one line, (.*?)\.$", "Prelude").group(1)))
        if verdicts != ("CODEX: YES", "CODEX: NO"):
            raise RuleError(f"Codex does not end with `CODEX: YES` or `CODEX: NO`: {s[:300]}")
        # Round 1: one complete pass; the count of rounds
        s = S["round 1"] = pick(items, "Round 1 is one complete pass", "CODEX REVIEW")
        grab(s, r"everything in scope at once, style of this diff included, one full list", "Round 1")
        grab(s, r"this one is round n when n-1 are recorded", "Round 1")
        complete = int(grab(s, r"^Round (\d+) is one complete pass", "Round 1").group(1))
        # Flip items
        s = S["flip items"] = pick(items, "Flip items are", "CODEX REVIEW")
        m = grab(s, r"^Flip items are the ([a-z, ]+) findings with a realistic trigger that you classify (\w+)\. "
                    r"Only they send work back \(branch (\d+)\)", "Flip items")
        flip, flip_class, branch = frozenset(_words(m.group(1))), m.group(2), m.group(3)
        # Re-reviews
        s = S["re-reviews"] = pick(items, "Rounds ", "CODEX REVIEW")
        m = grab(s, r"^Rounds (\d+) and (\d+) are re-reviews: give Codex the earlier round's flip items from the close "
                    r"report \(not the items already on the follow-up list\) and the diff the repairs made since "
                    r"\(the files `([^`]+)` names\)\.", "Re-reviews")
        reviews, repairs_input = (int(m.group(1)), int(m.group(2))), m.group(3)
        m = grab(s, r"It reports each of them as fixed or not fixed, and only new ([a-z]+) or ([a-z]+) defects the fix "
                    r"itself introduced; a flip item reported not fixed stays one\. Never ask for a new complete pass\.",
                 "Re-reviews")
        new_in_review = frozenset(m.groups())
        # Classification and where the rest goes
        s = S["classification"] = pick(items, "Classify every finding", "CODEX REVIEW")
        m = grab(s, r"^Classify every finding ([a-z_, ]+) with a one-line reason; you may reject one\. ([A-Za-z_, ]+) "
                    r"findings go to the close report's follow-up list, never to a finding or another round; "
                    r"a (\w+) stays in the transcript with its reason\.$", "Classification")
        classes = tuple(_words(m.group(1)))
        listed = _words(m.group(2))
        transcript = frozenset({m.group(3)})
        # The cap
        s = S["cap"] = pick(items, "After round ", "CODEX REVIEW")
        cap_m = grab(s, r"^After round (\d+) nothing below blocker reopens the cycle: what is still open and below "
                        r"blocker goes to the follow-up list and the close lands\. A blocker still open is a finding "
                        r"\(branch (\d+)\)", "The round cap")
        cap = int(cap_m.group(1))
        # An unparseable verdict line
        s = S["parse failure"] = pick(items, "No parseable", "CODEX REVIEW")
        grab(s, r"ask Codex once more for that line; if that fails too, your own verdict stands with a note", "Parse failure")
        # The verdict branches and the transcript bullets of the same block
        if block.count("VERDICT BRANCHES.") != 1:
            raise RuleError("QA's prompt has no single VERDICT BRANCHES paragraph")
        verdicts_text = block[block.index("VERDICT BRANCHES."):]
        branches = {int(b.group(1)): flat(b.group(2)) for b in re.finditer(r"^(\d+)\. (.*)$", verdicts_text, re.M)}
        s = S["branch 1"] = branches.get(1, "")
        yes_line = grab(s, r"no flip item open \(Codex answered YES, or only below-blocker items are on the follow-up "
                           r"list\) -> `(CLOSE: YES)`", "Verdict branch 1").group(1)
        s = S["branch 3"] = branches.get(3, "")
        grab(s, r"at least one flip item is open after your classification -> one finding per flip item\. "
                r"A `CODEX: NO` with no flip item opens none\.", "Verdict branch 3")
        if int(grab(s, r"After round (\d+) a flip item below blocker is listed, not a finding", "Verdict branch 3").group(1)) != cap:
            raise RuleError(f"branch 3 and the CODEX REVIEW paragraph name different last rounds: {s}")
        if branch != "3" or cap_m.group(2) != "3":
            raise RuleError("the flip item and cap sentences no longer send a finding to branch 3")
        _, transcript_items = bullets_after(block, "TRANSCRIPT.")
        s = S["transcript"] = pick(transcript_items, "per round,", "TRANSCRIPT")
        tags = tuple(re.findall(r"`(\[[A-Za-z]+\])`", s))
        sev = tuple(_words(grab(s, r"with its severity \(([a-z, ]+)\)", "TRANSCRIPT").group(1)))
        s = S["follow-up list"] = pick(transcript_items, "`## Follow-up list`", "TRANSCRIPT")
        heading = grab(s, r"^`(## Follow-up list)` \(whenever an item is listed\): one line per item with its severity "
                          r"and classification", "TRANSCRIPT").group(1)
        if block.count("RETURN VALUE.") != 1:
            raise RuleError("QA's prompt has no single RETURN VALUE paragraph")
        ret = flat(block[block.index("RETURN VALUE."):])
        S["return value"] = ret[:400]
        findings_form = grab(ret, r"`(CLOSE_FINDINGS: <n> items)`", "RETURN VALUE").group(1)
        disclosures = grab(ret, r"`(CLOSE: YES - with disclosures: <n> items)`", "RETURN VALUE").group(1)
        rules = cls(severities=sev, classes=classes, prelude=headers, scope=scope, out_of_scope=oos, gives=gives,
                    verdict_lines=verdicts, complete_round=complete, flip=flip, flip_class=flip_class,
                    review_rounds=reviews,
                    review_gives=("the earlier round's flip items", "the diff the repairs made since"),
                    repairs_input=repairs_input, new_in_review=new_in_review,
                    listed_severities=frozenset(w for w in listed if w in sev),
                    listed_classes=frozenset(w for w in listed if w in classes), transcript_classes=transcript,
                    cap=cap, yes_line=yes_line, findings_form=findings_form, disclosures_form=disclosures,
                    followup_heading=heading, tags=tags, sentences=S)
        rules.check()
        return rules

    def check(self) -> None:
        """The rules agree with each other (a half-edited text fails here, not in a replay's middle)."""
        if self.review_rounds != tuple(range(self.complete_round + 1, self.cap + 1)):
            raise RuleError(f"the re-review rounds {self.review_rounds} are not the rounds after round "
                            f"{self.complete_round} up to the cap {self.cap}")
        if not self.flip < set(self.severities) or "blocker" not in self.flip or self.new_in_review != {"blocker", "high"}:
            raise RuleError(f"flip severities {sorted(self.flip)} / re-review severities {sorted(self.new_in_review)} "
                            f"do not fit the ladder {self.severities}")
        if self.flip_class not in self.classes or not (self.listed_classes | self.transcript_classes) <= set(self.classes):
            raise RuleError(f"classification words do not fit {self.classes}")
        if self.tags != ("[QA]", "[Codex]"):
            raise RuleError(f"the transcript tags are {self.tags}")

    # -- what QA does at a point, from the rules
    def kind(self, n: int) -> str:
        """What round n asks Codex for: the one complete pass, or a re-review."""
        return "complete_pass" if n == self.complete_round else "re_review"

    def disposition(self, severity: str, classification: str, trigger: bool, n: int) -> str:
        """Where a finding of round n goes: `flip` (a finding of the round, branch 3), `listed` (the close
        report's follow-up list) or `transcript` (stays in the transcript)."""
        if severity not in self.severities or classification not in self.classes:
            raise RuleError(f"{severity!r}/{classification!r} is outside the vocabulary {self.severities} {self.classes}")
        if classification in self.transcript_classes:
            return "transcript"
        if severity in self.flip and trigger and classification == self.flip_class:
            return "listed" if n >= self.cap and severity != "blocker" else "flip"
        if severity in self.listed_severities or classification in self.listed_classes:
            return "listed"
        raise RuleError(f"no sentence places a {severity} finding classified {classification}")

    def verdict(self, flips: int, repairs: int) -> str:
        if flips:
            return _fill(self.findings_form, flips)
        return _fill(self.disclosures_form, repairs) if repairs else self.yes_line


# ---------------------------------------------------------------- /commit: rules

@dataclass
class CommitRules:
    """What commands/commit.md Step 6's QA prompt says of a Codex REJECT."""
    classes: tuple
    reject_severities: frozenset
    never_decide: frozenset
    guards: tuple                # the files that keep the secret and residue guarantees
    ask_again: bool
    sentences: dict = field(default_factory=dict)

    def to_fact(self) -> dict:
        return {k: (sorted(v) if isinstance(v, (set, frozenset)) else v) for k, v in self.__dict__.items()}

    @classmethod
    def from_text(cls, commit_md: str) -> "CommitRules":
        block = prompt_block(commit_md, "Step 6")
        text = flat(block)
        m = grab(text, r"When codex_required is true,.*?(A Codex REJECT is a finding, not a verdict\.)(.*?)"
                       r"(?= Write a transcript to)", "QA's Codex paragraph")
        para = flat(m.group(1) + m.group(2))
        S = {"paragraph": para}
        if text.count("A Codex REJECT is a finding, not a verdict.") != 1:
            raise RuleError("the sentence 'A Codex REJECT is a finding, not a verdict.' is not in QA's prompt once")
        m = grab(para, r"Classify every Codex finding as ([a-z_, ]+) with a one-line reason\.", "Classification")
        classes = tuple(_words(m.group(1)))
        m = grab(para, r"Only a ([a-z]+) or ([a-z]+) finding \([^)]*\) makes you reject; ([a-z, ]+) findings go in the "
                       r"report and never decide the verdict\.", "Which findings make QA reject")
        reject, never = frozenset({m.group(1), m.group(2)}), frozenset(_words(m.group(3)))
        grab(para, r"QA's own review decides it\.", "Who decides")
        g = grab(para, r"The secret and residue guarantees stay with the pre-commit guard \(([^)]+)\) and the privacy "
                       r"engine \(([^)]+)\), which do not depend on Codex\.", "The guards")
        ask = grab(para, r"If Codex gives no usable verdict line, ask it once more for that line; if that fails too, or "
                         r"on a quota or timeout failure, your own verdict stands, with a note of the failure in the "
                         r"report\.", "A missing verdict line")
        rules = cls(classes=classes, reject_severities=reject, never_decide=never, guards=(g.group(1), g.group(2)),
                    ask_again=bool(ask), sentences=S)
        if "blocker" not in reject or "high" not in reject or reject & never:
            raise RuleError(f"reject severities {sorted(reject)} / never-deciding {sorted(never)} do not fit")
        return rules

    def rejects(self, severity: str) -> bool:
        """Whether a Codex finding of this severity makes QA reject (the one sentence)."""
        if severity in self.reject_severities:
            return True
        if severity in self.never_decide:
            return False
        raise RuleError(f"no sentence says what a {severity} finding does to the verdict")


# ---------------------------------------------------------------- the scripted stub

@dataclass(frozen=True)
class Item:
    """One finding the stub Codex reports. `appears`: the first Codex call (1-based) that reports it. `repair`:
    the line a producer's repair adds that fixes it (None: no repair fixes it). `judge`: QA's classification and
    one-line reason. `intent`: call number -> what the scenario means the text to do with it (`flip` or `listed`);
    a text whose rules do otherwise raise, they contradict the scripted run."""
    id: str
    title: str
    severity: str
    trigger: str | None
    consequence: str
    fix: str
    judge: tuple
    path: str = "toy/__init__.py"
    appears: int = 1
    repair: str | None = None
    intent: tuple = ()


@dataclass(frozen=True)
class Script:
    name: str
    items: tuple
    new_in_review: bool = False     # the stub reports the items that appear at a call even in a re-review
    verdict_line: str = "CODEX: NO"   # the line the stub ends with while an item is open
    ok_line: str = "CODEX: YES"       # ... and when none is

    def item(self, ident: str) -> Item:
        return next(i for i in self.items if i.id == ident)

    def intended(self, item: Item, n: int):
        return dict(item.intent).get(n)


def repair_edit(current: str, item: Item) -> tuple[str, str]:
    """The producer's repair of `item` in a file: (old, new) whole texts. A repair that fixes the item adds its
    repair line; one that does not adds an unrelated attempt line (the stub reports the item not fixed)."""
    line = item.repair or f"    # attempt on {item.id}"
    return current, current.replace("def add(a, b):\n", f"def add(a, b):\n{line}\n", 1)


class StubCodex:
    """A Codex that answers the prompt it gets (no process, no network)."""

    def __init__(self, script: Script, fact=None):
        self.script, self.calls, self._fact = script, [], fact

    def ask(self, prompt: str) -> str:
        n = len(self.calls) + 1
        earlier = re.findall(r"^EARLIER ITEM (\S+) ", prompt, re.M)
        fixed = lambda it: bool(it.repair) and it.repair in prompt  # noqa: E731 (the diff the prompt carries holds the repair)
        lines: list[str] = []
        if earlier:      # a re-review: each earlier item, then (a script that has them) the items new at this call
            for ident in earlier:
                lines.append(f"ITEM {ident}: {'fixed' if fixed(self.script.item(ident)) else 'not fixed'}")
            shown = [i for i in self.script.items if i.appears == n] if self.script.new_in_review else []
            still_open = bool(shown) or any(l.endswith("not fixed") for l in lines)
        else:            # a complete pass: every open item the script has by now
            shown = [i for i in self.script.items if i.appears <= n and not fixed(i)]
            still_open = bool(shown)
        for it in shown:
            lines += [f"FINDING {it.id}: {it.title}"] + ([f"trigger: {it.trigger}"] if it.trigger else []) + [
                f"consequence: {it.consequence}", f"PROPOSED_FIX: {it.fix}", f"severity: {it.severity}"]
        lines.append(self.script.verdict_line if still_open else self.script.ok_line)
        answer = "\n".join(lines)
        self.calls.append({"n": n, "prompt": prompt, "answer": answer, "earlier": earlier,
                           "reported": [i.id for i in shown]})
        return answer


def parse_answer(answer: str, verdict_lines: tuple) -> dict:
    """QA's reading of a Codex answer: findings (severity last of each), statuses of earlier items, the verdict line."""
    findings, statuses, cur = [], {}, None
    verdict = None
    for line in answer.split("\n"):
        m = re.match(r"^FINDING (\S+): (.*)$", line)
        if m:
            cur = {"id": m.group(1), "title": m.group(2), "trigger": "", "severity": ""}
            findings.append(cur)
            continue
        m = re.match(r"^ITEM (\S+): (fixed|not fixed)$", line)
        if m:
            statuses[m.group(1)] = m.group(2)
            cur = None
            continue
        if line in verdict_lines:
            verdict = line
            cur = None
            continue
        m = re.match(r"^(trigger|severity|consequence|PROPOSED_FIX): (.*)$", line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2)
    for f in findings:
        if not f["severity"]:
            raise agents.PlayError(f"Codex finding {f['id']} carries no severity")
    return {"findings": findings, "statuses": statuses, "verdict": verdict}


def prelude_lines(rules: CloseRules, requirement: str) -> list[str]:
    return [f"{rules.prelude[0]}: {requirement}", f"{rules.prelude[1]}: {rules.scope}",
            f"{rules.prelude[2]}: {rules.out_of_scope}"]


# ---------------------------------------------------------------- the report QA writes and reads

def count_rounds(report: str) -> int:
    """The Codex consultations a close report records (one 'Round <n> (' heading each)."""
    return len(set(re.findall(r"^Round (\d+) \(", report, re.M)))


def earlier_flips(report: str) -> list[dict]:
    """The flip items of the report's last recorded round: id and severity, from its [Codex] lines."""
    parts = re.split(r"^(?=Round \d+ \()", report, flags=re.M)
    last = next((p for p in reversed(parts) if re.match(r"Round \d+ \(", p)), "")
    return [{"id": m.group(1), "severity": m.group(2), "title": m.group(3)} for m in re.finditer(
        r"^\[Codex\] (\S+) \| severity: (\w+) \| classification: \w+ \| flip item \| (.*?) \| reason:", last, re.M)]


def report_findings(report: str) -> list[tuple]:
    """(path, detail) of the `## Findings` lines of the report's last section."""
    section = report.rsplit("## Close attempt", 1)[-1] if "## Close attempt" in report else report
    m = re.search(r"^## Findings\n((?:- .*\n?)+)", section, re.M)
    return [tuple(line[2:].split(": ", 1)) for line in (m.group(1).strip().split("\n") if m else [])]


def followup_items(report: str, heading: str = "## Follow-up list") -> dict:
    """id -> (severity, classification) of every line under a follow-up heading, in all the report's sections."""
    out: dict = {}
    for m in re.finditer(r"^%s\n((?:- .*\n?)+)" % re.escape(heading), report, re.M):
        for line in m.group(1).strip().split("\n"):
            mm = re.match(r"^- (\S+) \| severity: (\w+) \| classification: (\w+)", line)
            if mm:
                out[mm.group(1)] = (mm.group(2), mm.group(3))
    return out


# ---------------------------------------------------------------- /close

class CloseCodex:
    """QA's Codex review inside /close, played for a CloseRun (drivers/close.py)."""

    def __init__(self, run, rules: CloseRules, script: Script, fact):
        self.run, self.rules, self.script, self.fact = run, rules, script, fact
        self.stub = StubCodex(script)
        self.judged: list = []

    # -- the orchestrator's side of Step 2: a round-open return is routed, Step 0 runs again, a fresh round
    def step2(self) -> str:
        run, o = self.run, self.run.o
        last = run.close_round("")
        k = 0
        while last.startswith("CLOSE_FINDINGS") and k < 3:
            k += 1
            o.s.say(last)
            run.read(run.report_rel(), run.label(f"Step 2 Read close-report round {run.round}"))
            text = agents.peek(run.rp, "main", os.path.join(o.project, run.report_rel()))
            n = len(run.routed)
            for path, detail in report_findings(text):
                item = self.script.item(detail.split(":", 1)[0].strip())
                old, new = repair_edit(run.current(path), item)
                run.route_path(path, detail, f"Step 2 round {k}", edits=[(path, old, new)], close_finding=True)
            run.repairs.extend(run.routed[n:])
            if not run.step0(f"Step 2 round {k} Step 0"):
                return ""
            last = run.close_round("")
        return last

    # -- QA's side
    def requirement(self, sub) -> str:
        """The user's verbatim requirement (the file the Prelude names), Read."""
        run = self.run
        rel = f"docs/dev/user-requirement-{run.session_id}.md"
        path = os.path.join(run.o.project, rel)
        if not os.path.isfile(path):
            raise agents.PlayError(f"the Prelude's requirement file {rel} does not exist")
        sub.read(path, label=f"{sub.role} Read {rel}")
        return flat(agents.peek(run.rp, sub.role, path))[:240]

    def act(self, append: bool) -> "agents.Act":
        run, rules, script, o = self.run, self.rules, self.script, self.run.o
        tid, project = run.tid, o.project
        act = agents.Act(summary="close debate", produced=[run.report_rel()] if append else [])

        def work(sub, brief, player):
            inputs = ([run.do_report] if run.do_report else list(run.chain.get("report_paths") or [])) + run.inspector_reports
            for rel in inputs:
                p = os.path.join(project, rel)
                if os.path.isfile(p):
                    sub.read(p, label=f"{sub.role} Read {rel}")
            report_path = os.path.join(project, run.report_rel())
            report = ""
            if os.path.isfile(report_path):
                sub.read(report_path, label=f"{sub.role} Read close-report")
                report = agents.peek(run.rp, sub.role, report_path)
            n = count_rounds(report) + 1                 # "this one is round n when n-1 are recorded"
            kind = rules.kind(n)
            asked = self.codex_prompt(sub, brief, n, kind, report, inputs)
            prompt, earlier_ids, diff_files = asked
            answer = self.stub.ask(prompt)
            read = parse_answer(answer, rules.verdict_lines)
            if read["verdict"] is None:
                raise agents.PlayError("the stub's answer carries no verdict line")
            body, flips, listed, rest = self.judge(n, kind, read, report)
            verdict = rules.verdict(len(flips), len(run.repairs))
            lines = self.section_lines(sub, brief, inputs, n, kind, read, body, flips, listed, verdict)
            text = "\n".join(lines)
            self.fact("codex round", {
                "n": n, "kind": kind, "asked_items": earlier_ids, "diff_files": diff_files, "prompt": prompt,
                "answer": answer, "reported": [f["id"] for f in read["findings"]], "statuses": read["statuses"],
                "verdict_line": read["verdict"], "flips": [f["id"] for f in flips],
                "listed": [f["id"] for f in listed], "close_verdict": verdict})
            if not append:
                act.notes = text.rsplit("\n\n" + verdict, 1)[0]
                act.terminal.update({run.report_rel(): verdict, "response_line": verdict})
                return None
            # Overwrite policy: the section to a temp file, then the append helper the text names.
            section = os.path.join("/tmp/claude-scratch/qa", f"close-section-{tid}-r{run.round}.md")
            sub.write(section, text + "\n", label=f"{sub.role} Write section")
            code = run.append_call().replace('"<absolute-temp-section-path>"', shlex.quote(section)).replace(
                "<absolute-temp-section-path>", section)
            c = sub.bash(o.respell(o.bind(code), f"{sub.role} Bash append helper"), "Append this attempt's section",
                         label=f"{sub.role} Bash append helper")
            out = (c.response.get("stdout") or "") if c.ok else (c.error or "")
            line = out.strip().splitlines()[-1] if out.strip() else ""
            try:
                got = json.loads(line).get("verdict_line") if c.ok else None
            except ValueError:
                got = None
            act.terminal["response_line"] = got or (line if line.startswith("CLOSE_REPORT_APPEND_") else verdict)
            return None
        act.work = work
        return act

    def codex_prompt(self, sub, brief, n: int, kind: str, report: str, inputs: list) -> tuple:
        """The prompt of Codex call n, as the text says it is built: the prelude first, then, for the one complete
        pass, everything in scope; for a re-review, the earlier round's flip items from the close report and the diff
        the repairs made since (the files the Completed repairs input names)."""
        run, rules, project = self.run, self.rules, self.run.o.project
        lines = prelude_lines(rules, self.requirement(sub))
        if rules.gives:
            lines += ["Input artifacts: " + ", ".join(inputs), "QA assessment: YES - the acceptance criteria are met "
                      "and the workflow integrity bullets pass", "Inspector findings: none introduced by this diff"]
        earlier_ids: list = []
        if kind == "complete_pass":
            files = run.files
            diff = self.git_diff(sub, files, "the cycle diff")
            lines += ["Review everything in scope at once, style of this diff included, and return one full list. "
                      "Each finding: trigger, consequence, PROPOSED_FIX, and its severity last "
                      f"({', '.join(rules.severities)}). End with one line: " + " or ".join(f"`{v}`" for v in rules.verdict_lines),
                      f"Diff of {', '.join(files)}:", diff]
        else:
            m = re.search(r"^\s*-\s*Completed repairs:\s*(.*)$", brief.prompt, re.M)
            repairs = json.loads(m.group(1)) if m and m.group(1).strip().startswith("[") else []
            files = sorted({r.split(": ", 1)[0] for r in repairs})
            if not files:
                raise agents.PlayError("a re-review needs the files the Completed repairs input names; it lists none")
            flips = earlier_flips(report)
            if not flips:
                raise agents.PlayError("the close report records no flip item of the earlier round to re-review")
            earlier_ids = [f["id"] for f in flips]
            diff = self.git_diff(sub, files, "the repairs")
            lines += ["Re-review: for each earlier item below say whether it is fixed or not fixed, and report only new "
                      + " or ".join(sorted(rules.new_in_review)) + " defects the fix itself introduced. This is not a "
                      "new complete pass. End with one line: " + " or ".join(f"`{v}`" for v in rules.verdict_lines)]
            lines += [f"EARLIER ITEM {f['id']} ({f['severity']}): {f['title']}" for f in flips]
            lines += [f"Diff the repairs made since ({', '.join(files)}):", diff]
        return "\n".join(lines), earlier_ids, files

    def git_diff(self, sub, files: list, what: str) -> str:
        c = sub.bash("git diff -- " + " ".join(shlex.quote(f) for f in files), f"Inspect {what}",
                     label=f"{sub.role} Bash git diff")
        return ((c.response.get("stdout") or "") if c.ok else "").rstrip("\n")

    def judge(self, n: int, kind: str, read: dict, report: str) -> tuple:
        """QA's classification of what Codex answered (the judgement the script gives) and the disposition the
        text's sentences make of it. Returns (lines, flip items, listed items, transcript-only items)."""
        rules, script = self.rules, self.script
        lines, flips, listed, rest = [], [], [], []
        earlier = {f["id"]: f for f in earlier_flips(report)}
        for ident, status in read["statuses"].items():
            if ident not in earlier:
                raise agents.PlayError(f"Codex reported on {ident}, which is no earlier flip item")
            if status == "fixed":
                lines.append(f"[Codex] {ident} | reported fixed")
                continue
            item = script.item(ident)
            disp = rules.disposition(earlier[ident]["severity"], item.judge[0], True, n)   # a flip item reported not fixed stays one
            self.check_intent(item, n, disp)
            lines.append(f"[Codex] {ident} | severity: {earlier[ident]['severity']} | classification: {item.judge[0]} | "
                         f"{self.words(disp)} | {item.title} | reason: reported not fixed" + (
                             f"; round {n} is the last, so it is listed" if disp == "listed" else ""))
            (flips if disp == "flip" else listed).append(dict(id=ident, severity=earlier[ident]["severity"], item=item))
        for f in read["findings"]:
            item = script.item(f["id"])
            cls, why = item.judge
            if kind == "re_review" and f["severity"] not in rules.new_in_review:
                raise agents.PlayError(f"the stub reported a new {f['severity']} item in a re-review; the text asks for "
                                       f"{sorted(rules.new_in_review)} only")
            disp = rules.disposition(f["severity"], cls, bool(f["trigger"]), n)
            self.check_intent(item, n, disp)
            lines.append(f"[Codex] {f['id']} | severity: {f['severity']} | classification: {cls} | {self.words(disp)} | "
                         f"{f['title']} | reason: {why}")
            (flips if disp == "flip" else listed if disp == "listed" else rest).append(dict(f, item=item))
        return lines, flips, listed, rest

    @staticmethod
    def words(disp: str) -> str:
        return {"flip": "flip item", "listed": "follow-up list", "transcript": "transcript only"}[disp]

    def check_intent(self, item: Item, n: int, disp: str) -> None:
        want = self.script.intended(item, n)
        if want and want != disp:
            raise RuleError(f"the scripted run intends {item.id} (severity {item.severity}) to be a {want} item at "
                            f"round {n}; the text's rules make it {disp}")

    def section_lines(self, sub, brief, inputs, n, kind, read, body, flips, listed, verdict) -> list:
        run, rules = self.run, self.rules
        mode = "do" if run.do_report else run.chain.get("mode", "singular")
        head = [f"## Close attempt (round {n}) {utc_now()}", "", f"Task-id: {run.tid}", f"Artifact-chain mode: {mode}",
                "Input files: " + ", ".join(inputs), f"Rounds run: {n} (judging round {run.round} of this close)",
                "Workflow Integrity Dimension:",
                "1. Downstream consumability: PASS — Step 0's chain_pass covers the chain /commit consumes",
                "2. task-id chain consistency: PASS — Step 0's chain_pass covers every identity",
                "3. Pre-existing-defect rule: PASS — nothing pre-existing raised",
                "4. Self-deployability: PASS — (i) PASS citing chain_pass, (ii) PASS (local bare origin), (iii) PASS, (iv) N/A",
                "codex_status: ok", "",
                f"Round {n} ({'complete pass' if kind == 'complete_pass' else 're-review'}):",
                f"{rules.tags[0]} position: YES — the acceptance criteria are met; Codex's findings are judged below",
                f"{rules.tags[1]} {read['verdict']}"] + body
        if flips:
            head += ["", "## Findings"] + [f"- {f['item'].path}: {f['id']}: {f['item'].title} (severity {f['severity']})"
                                           for f in flips]
        if listed:
            head += ["", rules.followup_heading] + [
                f"- {f['id']} | severity: {f['severity']} | classification: {f['item'].judge[0]} | {f['item'].title}"
                for f in listed]
        if run.repairs and not flips:
            head += ["", "## Disclosures"] + [f"{r['path']}: {r['problem']} | 归因: {r['role']} | 修复: dispatched again, "
                                               f"re-judged clean in round {run.round}" for r in run.repairs]
        return head + ["", verdict]

    # -- after the run
    def finish(self) -> None:
        run = self.run
        with run.rp.acting("driver"):
            try:
                with open(os.path.join(run.o.project, run.report_rel()), encoding="utf-8") as fh:
                    report = fh.read()
            except OSError:
                report = ""
        dev = [r for r in run.routed if r.get("role") == "dev"]
        self.fact("codex loop", {
            "script": self.script.name, "qa_rounds": run.round, "codex_calls": len(self.stub.calls),
            "calls": [{k: c[k] for k in ("n", "prompt", "answer", "earlier", "reported")} for c in self.stub.calls],
            "producer_dispatches": len(dev), "verdicts": [v for _, v in run.verdicts], "report": report,
            "scripted_items": [i.id for i in self.script.items],
            "never_reported": [i.id for i in self.script.items
                               if not any(i.id in c["reported"] or i.id in c["earlier"] for c in self.stub.calls)]})


# ---------------------------------------------------------------- /commit

class CommitCodex:
    """QA's Codex round inside /commit's pre-commit review, played for a CommitRun (drivers/commit.py)."""

    def __init__(self, run, rules: CommitRules, script: Script, fact):
        self.run, self.rules, self.script, self.fact = run, rules, script, fact
        self.stub = StubCodex(script)

    def act(self, groups: list) -> "agents.Act":
        run, rules, script = self.run, self.rules, self.script
        act = agents.Act(summary="pre-commit QA", final_line="")

        def work(sub, brief, player):
            material, own = [], []
            for g in groups:
                for p in g["files"]:
                    d = sub.bash(f"git -C {shlex.quote(g['repo'])} diff --text HEAD -- {shlex.quote(p)}", f"DIFF of {p}",
                                 label=f"{sub.role} Bash diff {p}")
                    full = os.path.join(g["repo"], p)
                    if os.path.isfile(full):
                        sub.read(full, label=f"{sub.role} Read {p}")
                    material.append(f"--- {p}\n" + ((d.response.get("stdout") or "") if d.ok else ""))
                    own.append(f"- {p}: authored change of this task; no secret, byproduct or scope contamination")
            prompt = "\n".join(["Review the files about to be committed (the HEAD diffs and new-file contents, not the "
                                "staged set). Each finding: trigger, consequence, PROPOSED_FIX, severity last. End with "
                                "one line: `CODEX: APPROVE` or `CODEX: REJECT`.",
                                "QA's draft verdict: COMMIT: APPROVE"] + material)
            answer = self.stub.ask(prompt)
            read = parse_answer(answer, ("CODEX: APPROVE", "CODEX: REJECT"))
            if read["verdict"] is None:
                raise agents.PlayError("the stub's answer carries no verdict line")
            lines, deciding = [], []
            for f in read["findings"]:
                item = script.item(f["id"])
                cls, why = item.judge
                if cls not in rules.classes:
                    raise RuleError(f"the scripted classification {cls!r} is not one of {rules.classes}")
                if rules.rejects(f["severity"]):
                    deciding.append(f)
                lines.append(f"[Codex] {f['id']} | severity: {f['severity']} | classification: {cls} | reason: {why}")
                want = dict(item.intent).get(1)
                if want and want != ("reject" if rules.rejects(f["severity"]) else "no_reject"):
                    raise RuleError(f"the scripted run intends {item.id} (severity {item.severity}) to {want}; "
                                    f"the text's sentence makes it {'reject' if rules.rejects(f['severity']) else 'no_reject'}")
            verdict = ("COMMIT: REJECT - " + ", ".join(sorted({script.item(f['id']).path for f in deciding}))
                       + " has a defect Codex found") if deciding else "COMMIT: APPROVE"
            act.notes = (f"Round {run.rounds}, {utc_now()}. Per-file findings:\n" + "\n".join(own)
                         + f"\n\nCodex verdict line: {read['verdict']}\n" + "\n".join(lines)
                         + "\ncodex_status: ok")
            act.terminal.update({"*commit-qa-report-*": verdict, "response_line": verdict})
            act.final_line = verdict
            self.fact("codex round", {"n": 1, "kind": "pre_commit_review", "prompt": prompt, "answer": answer,
                                      "reported": [f["id"] for f in read["findings"]], "verdict_line": read["verdict"],
                                      "close_verdict": verdict,
                                      "deciding": [f["id"] for f in deciding]})
            return None
        act.work = work
        return act

    def finish(self) -> None:
        run = self.run
        path = os.path.join(run.o.project, f"docs/dev/commit-qa-report-{run.tid}.md")
        with run.rp.acting("driver"):
            try:
                with open(path, encoding="utf-8") as fh:
                    report = fh.read()
            except OSError:
                report = ""
        self.fact("codex commit", {"script": self.script.name, "qa_rounds": run.rounds, "codex_calls": len(self.stub.calls),
                                   "report": report, "guards_exist": self.guards_exist()})

    def guards_exist(self) -> dict:
        root = self.run.rp.layout.harness
        return {g: os.path.isfile(os.path.join(root, g)) for g in self.rules.guards}


# ---------------------------------------------------------------- the three scripted runs

TRIGGER = "toy.add('a', 1) called by the requirement's main path"

# (1) one blocker plus five style and edge items
FLIP_ITEMS = Script("one blocker and five style and edge items", (
    Item("F1", "add() accepts a non-number: the requirement's TypeError never happens", "blocker", TRIGGER,
         "the requirement fails on its main path", "validate both arguments before adding",
         ("in_scope_real_bug", "the requirement's main path fails with the stated input"),
         repair="    # F1 repaired: both arguments are validated", intent=((1, "flip"),)),
    Item("F2", "the loop variable is named `x`", "style", None, "readability of this diff only", "rename it",
         ("in_scope_minor", "naming in this diff; no failure"), intent=((1, "listed"),)),
    Item("F3", "a blank line is missing before the return", "style", None, "readability only", "add the blank line",
         ("in_scope_minor", "cleanliness of this diff; small"), intent=((1, "listed"),)),
    Item("F4", "add(1e308, 1e308) returns inf", "edge", "add(1e308, 1e308), a call the requirement does not name",
         "an unusual float input", "document the limit", ("out_of_scope", "an input the requirement does not name"),
         intent=((1, "listed"),)),
    Item("F5", "add(True, 1) accepts a bool", "edge", "add(True, 1), a call the requirement does not name",
         "bool passes as int", "reject bool", ("in_scope_minor", "bool is an int in Python; harmless"),
         intent=((1, "listed"),)),
    Item("F6", "the docstring lacks an example", "style", None, "documentation of this diff", "add an example",
         ("in_scope_minor", "nice to have"), intent=((1, "listed"),)),
))

# (2) a new item at every call; the cap, not Codex, ends it
ENDLESS = Script("a new item at every round", (
    Item("N1", "add() raises no TypeError for a string", "medium", "toy.add('a', 1) on the requirement's secondary path",
         "no error for a bad argument", "check the argument types",
         ("in_scope_real_bug", "a stated input is not rejected"), appears=1, repair="    # N1 repaired: strings rejected",
         intent=((1, "flip"),)),
    Item("N2", "the TypeError names neither argument", "high", "toy.add('a', 1): the message the requirement asks for",
         "the error does not name the argument", "name the argument in the message",
         ("in_scope_real_bug", "the fix for N1 introduced it"), appears=2, repair=None, intent=((2, "flip"), (3, "listed"))),
    Item("N3", "the TypeError message is not stable across Python versions", "high",
         "toy.add(None, 1) on another Python version", "a flaky message", "build the message by hand",
         ("in_scope_real_bug", "the fix for N2 introduced it"), appears=3, repair=None, intent=((3, "listed"),)),
    Item("N4", "the message mentions the module path", "high", "toy.add([], 1)", "noise in the message", "drop the path",
         ("in_scope_real_bug", "the fix for N3 introduced it"), appears=4, repair=None),
    Item("N5", "the message is not translated", "high", "toy.add({}, 1)", "no translation", "translate it",
         ("in_scope_real_bug", "the fix for N4 introduced it"), appears=5, repair=None),
), new_in_review=True)

# (3) /commit --codex: the stub rejects for a style reason
STYLE_REJECT = Script("a Codex REJECT for a style reason", (
    Item("S1", "the new function name `add` is terse; prefer `add_numbers`", "style", None,
         "readability of the changed line only", "rename the function",
         ("nitpick", "a naming preference; nothing fails and no requirement names it"), intent=((1, "no_reject"),)),
), verdict_line="CODEX: REJECT", ok_line="CODEX: APPROVE")


def close_rules(rp) -> CloseRules:
    """The rules of commands/close.md of the tree under test (read first, before any pipeline runs)."""
    with rp.acting("driver"):
        with open(os.path.join(rp.layout.harness, "commands", "close.md"), encoding="utf-8") as fh:
            return CloseRules.from_text(fh.read())


def commit_rules(rp) -> CommitRules:
    with rp.acting("driver"):
        with open(os.path.join(rp.layout.harness, "commands", "commit.md"), encoding="utf-8") as fh:
            return CommitRules.from_text(fh.read())


def check_script(rules: CloseRules, script: Script) -> None:
    """The scripted run fits the text: every severity and classification it uses is in the text's vocabulary, what
    the scenario intends for each item at each round is what the text's rules make of it, and a script whose new
    items never stop outlasts the text's cap (else the cap is not what ends the run)."""
    for it in script.items:
        if it.severity not in rules.severities or it.judge[0] not in rules.classes:
            raise RuleError(f"scripted item {it.id} uses {it.severity}/{it.judge[0]}, outside the text's vocabulary")
        for n, want in it.intent:
            try:
                got = rules.disposition(it.severity, it.judge[0], bool(it.trigger), n)
            except RuleError as e:
                raise RuleError(f"scripted item {it.id} (severity {it.severity}, round {n}): {e}") from e
            if got != want:
                raise RuleError(f"the scripted run intends {it.id} (severity {it.severity}) to be a {want} item at round "
                                f"{n}; the text's rules make it {got}")
    if script.new_in_review and max(i.appears for i in script.items) <= rules.cap:
        raise RuleError(f"the scripted run has new items up to call {max(i.appears for i in script.items)}; the text's "
                        f"cap is round {rules.cap}, so the cap would not be what ends it")


def check_commit_script(rules: CommitRules, script: Script) -> None:
    """The scripted /commit run fits the text: the classification is one of the text's, and a finding the scenario
    means not to decide the verdict does not, by the text's one sentence."""
    for it in script.items:
        if it.judge[0] not in rules.classes:
            raise RuleError(f"scripted item {it.id} is classified {it.judge[0]!r}, not one of {rules.classes}")
        for _n, want in it.intent:
            got = "reject" if rules.rejects(it.severity) else "no_reject"
            if got != want:
                raise RuleError(f"the scripted run intends {it.id} (severity {it.severity}) to {want}; the text's "
                                f"sentence makes it {got}")
