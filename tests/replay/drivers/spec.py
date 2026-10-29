"""/spec (Spec Creation Mode) and /spec-update on the spec it wrote, played compliantly from
commands/spec.md, commands/spec-update.md and agents/spec.md of the tree under test.

/spec, one session, five main-agent turns (each ends with Stop):
  1. `/spec <requirement>`: the checklist the hook hands over (checked against
     scripts/todo/spec.py), Step 1 (no --codex), Step 2 (not triggered: Section 5 can be
     sketched), Step 3: the template Read, the path the text's path line gives, the template
     populated as Step 3 item 3 lists, the first write as the tree's text says (through the
     writer block Step 3 quotes, or, where the text has no writer, the `docs/dev/specs/`
     directory created and the file written with Write), the background Explore dispatch
     from the text's own Agent(...) block (the requirement names toy.add), the acknowledgement.
  2. the Explore agent's completion notification (a task notification; no prompt hook):
     its findings integrated into Section 1 as the "Exploration findings arrive" branch says.
  3. a follow-up requirement: the capture precondition (nothing to capture), then the
     "Another requirement" branch: a `### 5.2: <title>` block appended to Section 5.
  4. a design-only turn (inline HOW-text): the Design & Evidence Capture Routine: its Bash
     blocks (the resolver's de-prefixed id, the bound folders), the design file written
     verbatim, the Section 9.1 reference line appended; no Section 5 append.
  5. "thanks": the strong signal; Step 6 Finalize: the Section 9 reference guard, the
     MONOLITH_LINES line, the spec subagent dispatched from the text's template (its
     obligation instantiated where the template has one), the split QA from its template
     and its loop (the re-split template on a fail), the `.split-complete` marker, the
     finalize guard block and the lint block; Step 7: the /spec-update --temp note
     (mktemp, Read, Write, as that command's text says) and the result display; Stop.

Every spec write follows the tree's own text: where it names scripts/spec-write.py, every
write runs that script (the command assembled from the text's block and inline calls);
where it does not, the main agent writes the file itself (Write, then Edit per append).

The spec subagent (agents/spec.md of the tree) reads the monolith, creates views/, decides
its agents (Phase 0, rule 2: a backend change to one function -> dev + qa), discovers no
meta-rules (Phase 0.5), decomposes the monolith into content blocks and routes each by its
content (Phase 1: Section 9's whole block to every view and the orchestrator view, M7), writes
each view and the orchestrator view (Step 4's sections, the machine-generated tables
included), the manifest (Step 5: a Python stanza under fcntl.LOCK_EX), runs Step 6's
verbatim self-check per view (the orchestrator view's machine-generated lines fail it; it
re-extracts that view without them, as Step 6's "On failure" says, re-checks, and leaves them
out of every later write of that view), runs
Step 7's coverage block, then Phase 2 per agent: the text's check-in block and, where the
text has one, its checkpoints block (else the Python stanza the base text describes), the
Quick sanity test's status block, and returns the Output-format JSON (codex not requested).
The split QA reads the monolith and the views and runs check 3's verifier lines.

Driver arguments (cli.py --arg K=V):
  variant=plain          the run above; split QA passes on round 1
  variant=omission       the spec subagent omits qa's Role Mandate (R3.4: qa's candidate
                         role lines conflict, Section 7 gives the duty to "QA (on fail) or
                         PM-Retro"); it records the omission only where its text tells it to
                         (the base's R3.4 record in views/mandate-omissions.json); a block at
                         its stop it cannot clear without fabricating a mandate, so it stops
                         again with the split as it stands
  variant=bad-split      round 1 of the spec subagent dumps qa's content blocks into dev.md
                         too (the coverage-fallback ANTI-PATTERN), a split that only
                         `spec-verify.py --strict` rejects (pairwise overlap); a block at the
                         subagent's stop returns the split to it and it re-extracts (round 2)
  variant=split-qa-fail  split QA round 1 fails (check 5: the 5.2 follow-up, a criterion qa
                         verifies, is only in dev.md); the spec subagent is re-dispatched from
                         the re-split template with the issues verbatim, adds that block to
                         qa.md and refreshes its checkpoints; QA round 2 passes
  variant=update         plain /spec, then in a later session /spec-update --spec <path>
                         (continuation mode: a `### Cycle 2` block per Section 2-4, 6-8, the
                         continuation marker first) and /spec-update --update --spec <path>
                         (a `### 5.3` block and the Section 8 note); pipeline "spec-update"
  req=large              (default) a requirement with Acceptance, Verification and Constraints
                         lists, and Explore findings with the current code: views large enough
                         that a split routing Section 9 into every view passes the --strict
                         overlap threshold
  req=small              a shorter requirement (6 acceptance lines, 3 constraints) and three
                         findings lines: every compliant two-view split shares Section 9's lines
                         and fails --strict's 30% pairwise overlap

Values the main agent knows and binds: the project directory it runs in (the CLI's Bash does
not export CLAUDE_PROJECT_DIR, E5; the text's blocks read it, so the main agent binds it as
it binds spec_path), the time (Step 3's <YYYYMMDD-HHMMSS>, dispatched_at).

Modelled approximations: the background Explore dispatch runs to completion inside its
Agent call (the framework has no asynchronous agent); its notification is a transcript user
record with no prompt hook.

Respellings: none (/spec's and /spec-update's harness-script calls already name ~/.claude).

Deviations: DEVIATIONS below, one entry per block the base tree's (2acc29b) replay meets,
each with a comment quoting the hook's text; nothing else passes a block.
"""
from __future__ import annotations

import json
import os
import re
import shlex

from .. import cmdtext
from ..pipeline import DROP_NEXT, Deviations, Orchestrator, utc_now
from ..replay import Deviation

PIPELINE = "spec"

REQUIREMENT_LARGE = (
    "add input validation to toy.add: raise TypeError naming the offending argument when an argument "
    "is not a number.\n\n"
    "Acceptance:\n"
    "- toy.add(1, 2) still returns 3\n"
    "- toy.add(1.5, 2) still returns 3.5\n"
    "- toy.add(-1, 1) still returns 0\n"
    "- toy.add(10**20, 1) still returns 100000000000000000001\n"
    "- toy.add('1', 2) raises TypeError whose message names argument a\n"
    "- toy.add(1, '2') raises TypeError whose message names argument b\n"
    "- toy.add(None, 2) raises TypeError whose message names argument a\n"
    "- toy.add(2, None) raises TypeError whose message names argument b\n"
    "- toy.add([1], 2) raises TypeError whose message names argument a\n"
    "- toy.add(1, {}) raises TypeError whose message names argument b\n"
    "- toy.add(True, 1) still returns 2\n"
    "- toy.add(0, 0) still returns 0\n"
    "- toy.add(1, 2.5) still returns 3.5\n"
    "- when both arguments are wrong the message names argument a\n"
    "- the message reads: add(): argument a must be a number (b for the second argument)\n"
    "- tests/test_add.py keeps passing\n"
    "- toy.sub(5, 3) still returns 2\n\n"
    "Verification:\n"
    "- python3 -m pytest -q tests/test_add.py\n"
    "- python3 -c 'import toy; print(toy.add(1, 2))' prints 3\n"
    "- one new test per acceptance line under tests/\n"
    "- git diff --stat names only toy/__init__.py and files under tests/\n"
    "- python3 -m pytest -q runs every test under tests/ green\n"
    "- grep -n TypeError toy/__init__.py shows exactly one raise\n\n"
    "Constraints:\n"
    "- change only toy/__init__.py and add tests under tests/\n"
    "- keep the signature add(a, b) and add no dependency\n"
    "- leave toy/util.py untouched\n"
    "- check with isinstance against (int, float); bool stays accepted as an int\n"
    "- raise before the addition runs\n"
    "- build the message with an f-string naming the argument\n"
    "- no logging and no print in toy/__init__.py\n"
    "- keep the module importable on python 3.10\n"
    "- do not rename or move toy/__init__.py\n"
    "- keep add a plain function (no decorator, no class)\n"
    "- keep the return statement return a + b")
REQUIREMENT_SMALL = (
    "add input validation to toy.add: raise TypeError naming the offending argument when an argument "
    "is not a number.\n\n"
    "Acceptance:\n"
    "- toy.add(1, 2) still returns 3\n"
    "- toy.add(1.5, 2) still returns 3.5\n"
    "- toy.add('1', 2) raises TypeError whose message names argument a\n"
    "- toy.add(1, '2') raises TypeError whose message names argument b\n"
    "- toy.add(None, 2) raises TypeError whose message names argument a\n"
    "- tests/test_add.py keeps passing\n\n"
    "Constraints:\n"
    "- change only toy/__init__.py\n"
    "- keep the signature add(a, b) and add no dependency\n"
    "- leave toy/util.py untouched")
SUMMARY = "toy.add input validation"
MENTIONED = "toy.add (toy/__init__.py) and its test tests/test_add.py"
FINDINGS_SMALL = ("toy/__init__.py:1 defines add(a, b) as `return a + b`, with no argument check.\n"
                  "tests/test_add.py:3 covers only add(2, 3) == 5.\n"
                  "toy/util.py:1 defines sub(a,b); nothing imports it.")
FINDINGS_LARGE = ("toy/__init__.py:1 defines add(a, b) with no argument check:\n\n"
                  "```python\ndef add(a, b):\n    return a + b\n```\n\n"
                  "tests/test_add.py:3 covers only add(2, 3) == 5.\n"
                  "toy/util.py:1 defines sub(a,b); nothing imports it.\n"
                  "toy/__init__.py has no __all__ and no docstring.\n"
                  "The repository has no setup.py or pyproject.toml; tests import toy from the repository root.\n"
                  "Nothing else in the repository calls toy.add.\n"
                  "tests/ holds one file, test_add.py, with one test function.")
FOLLOW_UP = "Also keep toy.sub unchanged for its callers."
FOLLOW_UP_TITLE = "keep toy.sub unchanged"
DESIGN = ("Design: put the type check at the top of toy.add, before the addition: loop over the pairs "
          "(\"a\", a) and (\"b\", b) and raise TypeError(f\"add(): argument {name} must be a number\") "
          "for the first one that is not an int or float.")
DESIGN_SLUG, DESIGN_LINE = "type-check-placement", "where the type check goes and how its message names the argument"
CLOSING = "thanks, that's all"
SPLIT_QA_ISSUE = {"check": "FUNCTIONAL COMPLETENESS", "view": "qa.md",
                  "issue": "the follow-up requirement (keep toy.sub unchanged) is a criterion qa verifies; "
                           "it is only in dev.md",
                  "fix": "add that block of Section 5 to qa.md verbatim"}
CONTINUATION_FOCUS = "no /dev cycle has run yet; the next session implements the type check"
UPDATE_TITLE, UPDATE_TEXT = "bool arguments", "bool arguments keep being accepted, as int subclasses."

# Blocks the base tree's replay meets, each passed by a deviation at the step it occurs on: the
# refused call is applied as if allowed, so every later step runs and is traced.
DEVIATIONS = Deviations([
    # DEVIATION: "BLOCKED: removal-policy — UNRESOLVED census_obligation_undischarged:substitution@223,substitution@343"
    # pretool-bash-safety.sh refuses agents/spec.md Phase 2's check-in block as the text spells it
    # (the backticked `cp-state-path:` in its own `#` comment lines reads to the hook as a substitution).
    ("spec Bash check-in *", Deviation(
        "hooks/pretool-bash-safety.sh", "UNRESOLVED census_obligation_undischarged:substitution",
        "Phase 2's check-in block as agents/spec.md spells it")),
    # DEVIATION: "BLOCKED: removal-policy — UNRESOLVED census_fatal:unbalanced:single_quote"
    # pretool-bash-safety.sh refuses the capture routine's folder block as the base text spells it
    # (the apostrophe of "splitter's" in its `#` comment).
    ("Capture Bash mkdir", Deviation(
        "hooks/pretool-bash-safety.sh", "UNRESOLVED census_fatal:unbalanced:single_quote",
        "the capture routine's folder block as the text spells it")),
    # DEVIATION: "[Write Guard] BLOCKED: File already exists: /var/tmp/claude-scratch/update-<rand>.md"
    # /spec-update --temp (which /spec Step 7 runs) creates the note with mktemp, reads it, then writes it.
    ("Step 7 Write update note", Deviation(
        "hooks/pretool-write-guard.sh", "[Write Guard] BLOCKED: File already exists",
        "the temp note mktemp created, written as /spec-update --temp says")),
    # DEVIATION: "[Orchestrator Gate] BLOCKED: Edit used consecutively beyond limit (2/1)."
    # /spec-update as the base text spells it has the main agent append to the spec itself, one Edit
    # per section of the continuation (and the --update Section 8 note after its 5.N Edit).
    ("/spec-update*", Deviation(
        "hooks/pretool-orchestrator-gate.py", "Edit used consecutively beyond limit",
        "/spec-update's own appends as the base text spells them")),
])

_SECTION_RE = re.compile(r"^## Section (\d+):")
_SENTINEL_FALLBACK = r"^\s*-\s*\((inline|unpersisted design|unpersisted)\)\s"


def _sub_bash(sub, command: str, description: str, label: str):
    """A subagent's Bash call, with the deviations the driver declares for its step label."""
    return sub.bash(command, description, label=label, deviation=DEVIATIONS.at(label))


def _read(rp, path: str) -> str:
    """A file the actor already Read (or wrote), read again by the driver on its behalf."""
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------- spec text helpers

def section_range(lines: list, heading_rx: str, level: int):
    """(start, end) line indexes of the heading's section: up to the next heading of the same or a
    higher level, or the file's end."""
    rx = re.compile(heading_rx)
    start = next((i for i, l in enumerate(lines) if rx.match(l)), None)
    if start is None:
        return None
    for i in range(start + 1, len(lines)):
        m = re.match(r"^(#{1,6}) ", lines[i])
        if m and len(m.group(1)) <= level:
            return start, i
    return start, len(lines)


def appended(text: str, section: str, block: str, replace_placeholder: bool) -> str:
    """The spec text with `block` placed where the main agent's Edit puts an append to Section
    <section> (`N` or `N.M`): in place of the section's placeholder line when it says so, else at
    the section's end above its closing `---`."""
    lines = text.split("\n")
    rx = rf"^### {re.escape(section)}\b" if "." in section else rf"^## Section {re.escape(section)}\b"
    start, end = section_range(lines, rx, 3 if "." in section else 2)
    blines = block.rstrip("\n").split("\n")
    if replace_placeholder:
        k = next(i for i in range(start, end) if lines[i].strip() == "_Not yet populated._")
        return "\n".join(lines[:k] + blines + lines[k + 1:])
    k = end
    while k > start + 1 and (not lines[k - 1].strip() or lines[k - 1].strip() == "---"):
        k -= 1
    return "\n".join(lines[:k] + [""] + blines + lines[k:])


def edit_pair(old: str, new: str) -> tuple[str, str]:
    """The smallest unique whole-line span of `old` whose replacement gives `new`."""
    from ..agents import edit_span
    return edit_span(old, new)


# ---------------------------------------------------------------- the writer, as each text spells it

class SpecText:
    """How the tree's text has the main agent write a spec: through the writer the text names (its
    command from the text's block and inline calls), or with Write and Edit."""

    def __init__(self, o: Orchestrator):
        self.o = o
        self.create_block = None
        for b in cmdtext.blocks(o.text, "Step 3", "bash"):
            if "spec-write.py create" in b.text:
                self.create_block = b.text
        self.writer = self.create_block is not None

    def heredoc(self) -> tuple[str, str, str]:
        """(prefix before `spec-write.py`, heredoc opener, delimiter) of the text's create block."""
        first = self.create_block.split("\n")[0]
        m = re.match(r"^(.*?)spec-write\.py create --spec \S+\s*(<<'?(\w+)'?)\s*$", first)
        if not m:
            raise cmdtext.TextNotFound("Step 3's writer block has no `spec-write.py create --spec ... <<'X'` line")
        return m.group(1), m.group(2), m.group(3)

    def call(self, inline: str, body: str) -> str:
        """A writer command: the text's inline call (`spec-write.py append --spec <spec_path> ...`),
        placeholders bound, behind the create block's interpreter, with `body` as its heredoc."""
        prefix, opener, delim = self.heredoc()
        return f"{prefix}{self.o.bind(inline)} {opener}\n{body.rstrip(chr(10))}\n{delim}"

    def inline(self, heading: str, anchor: str, section_arg: str) -> str:
        """The inline writer call of the item holding `anchor` whose --section is `section_arg`."""
        for c in cmdtext.inline_codes(self.o.text, heading, anchor):
            if c.startswith("spec-write.py append") and c.rstrip().endswith(f"--section {section_arg}"):
                return c
        raise cmdtext.TextNotFound(f"{heading!r} item {anchor!r}: no `spec-write.py append ... --section {section_arg}`")


# ---------------------------------------------------------------- the spec subagent

class SpecAgent:
    """One /spec finalize's spec subagent, as agents/spec.md of the tree says (state kept across its
    re-dispatches and its stop rounds)."""

    def __init__(self, run: "SpecRun"):
        self.run, self.rp = run, run.rp
        self.text = run.o.tree.agent_text("spec")
        self.selected = ["dev", "qa"]
        self.omit = "qa" if run.variant == "omission" else None
        self.round = 0           # dispatches
        self.stop_round = 0      # stop rounds of the current dispatch
        self.extra: dict = {}    # view -> extra block keys (a re-split's corrections)
        self.generated = True    # Step 4's machine-generated orchestrator sections, until Step 6 rejects them

    # ------------------------------------------------------------ text
    def block(self, heading: str, anchor: str | None = None, index: int | None = None) -> str:
        return cmdtext.block(self.text, heading, anchor=anchor, index=index, lang="bash")

    def omission_reason(self) -> str | None:
        """The closed-enum reason the text gives for an omission whose candidate blocks conflict,
        where the text has the subagent record its omission at all."""
        sec = cmdtext.section(self.text, "Step 3: Assemble and write view files")
        if "mandate-omissions.json" not in sec or "Do not record the omission yourself" in sec:
            return None
        for code, desc in re.findall(r'^\s*-\s*`"([a-z_]+)"`\s*—\s*(.*)$', sec, re.M):
            if "conflict" in desc:
                return code
        raise cmdtext.TextNotFound("agents/spec.md R3.4 lists no reason for conflicting candidate blocks")

    # ------------------------------------------------------------ Phase 1: content blocks and routing
    def content_blocks(self, mono: str) -> list:
        """Step 1's content blocks: (first line no., lines, kind, section) for code fences, tables,
        list groups, headings and paragraphs (comment lines included), in monolith order."""
        lines, out, i, section = mono.split("\n"), [], 0, "preamble"
        while i < len(lines):
            line = lines[i]
            m = _SECTION_RE.match(line)
            if m:
                section = m.group(1)
            if not line.strip() or line.strip() == "---":
                i += 1
                continue
            j = i + 1
            if line.startswith("```"):
                while j < len(lines) and not lines[j].startswith("```"):
                    j += 1
                j, kind = j + 1, "fence"
            elif line.startswith("|"):
                while j < len(lines) and lines[j].startswith("|"):
                    j += 1
                kind = "table"
            elif re.match(r"^\s*(?:[-*+]|\d+\.)\s", line):
                while j < len(lines) and lines[j].strip() and (re.match(r"^\s*(?:[-*+]|\d+\.)\s", lines[j])
                                                             or lines[j].startswith((" ", "\t"))):
                    j += 1
                kind = "list"
            elif line.startswith("#"):
                kind = "heading"
            else:
                while (j < len(lines) and lines[j].strip() and lines[j].strip() != "---"
                       and not lines[j].startswith(("#", "```", "|"))
                       and not re.match(r"^\s*(?:[-*+]|\d+\.)\s", lines[j])):
                    j += 1
                kind = "paragraph"
            out.append((i + 1, lines[i:j], kind, section))
            i = j
        return out

    def section_owner(self, blocks: list, section: str) -> set:
        """The selected agent(s) the section's own role comment names; a section naming none goes
        by its subject: the acceptance criterion to qa, any other to dev (implementation context)."""
        for _n, lines, _k, sec in blocks:
            text = "\n".join(lines)
            if sec != section or "WHO WRITES" not in text:
                continue
            who = re.search(r"WHO WRITES:\s*(.*?)-->", text).group(1)
            named = {a for a in self.selected if re.search(rf"\b{re.escape(a)}\b", who, re.I)}
            if named:
                return named
        heading = next(("\n".join(b[1]) for b in blocks if b[3] == section and b[2] == "heading"), "")
        return {"qa"} if "Acceptance" in heading else {"dev"}

    def assignment(self, mono: str) -> dict:
        """agent -> [block] in monolith order (Phase 1 Step 2, this scenario's judgment): Section 9's
        whole block to every view and the orchestrator view (M7); the preamble to the orchestrator
        view; a section's heading, role comments, cycle headings and placeholders to the agent(s) its
        role comment names; the requirement sentence to dev and qa; an `Acceptance:` list to qa; a
        `Constraints:` list, a `### 5.N` follow-up and Section 1's findings (file paths, current
        behaviour) to dev."""
        blocks = self.content_blocks(mono)
        out = {a: [] for a in self.selected + ["orchestrator"]}
        owners, run = {}, None
        for blk in blocks:
            _n, lines, kind, sec = blk
            text = "\n".join(lines)
            if sec == "preamble":
                agents = {"orchestrator"}
            elif sec == "9":
                agents = set(self.selected) | {"orchestrator"}
            else:
                owner = owners.setdefault(sec, self.section_owner(blocks, sec))
                scaffold = (kind == "heading" and re.match(r"^(## Section|### Cycle)", text)) \
                    or text.startswith("<!--") or text.strip() == "_Not yet populated._"
                if scaffold:
                    agents, run = owner, None
                elif sec == "1":
                    agents = {"dev"}
                elif sec == "5":
                    if text.startswith(("Acceptance:", "Verification:")):
                        run = "qa"                            # acceptance criteria, verification procedures
                    elif text.startswith("Constraints:") or (kind == "heading" and text.startswith("### 5.")):
                        run = "dev"                           # implementation constraints
                    agents = {run} if run else {"dev", "qa"}
                else:
                    agents = owner
            for a in agents & set(out):
                out[a].append(blk)
        for view, needles in self.extra.items():   # a re-split's corrections (QA feedback)
            agent = view[:-3]
            for blk in blocks:
                if any(x in "\n".join(blk[1]) for x in needles) and blk not in out[agent]:
                    out[agent] = sorted(out[agent] + [blk], key=lambda b: b[0])
        return out

    # ------------------------------------------------------------ Phase 1: views
    def mandate(self, agent: str, mono: str) -> str | None:
        """The legacy-form Role Mandate: a verbatim monolith line defining the agent's duty."""
        if agent == self.omit:
            return None
        rx = {"dev": r"<!-- WHO WRITES: Dev \(after each implementation attempt\) -->",
              "qa": r"<!-- WHO WRITES: QA \(after each verification\) -->",
              "orchestrator": r"<!-- WHO WRITES: /spec orchestrator[^\n]*-->"}[agent]
        m = re.search(rx, mono)
        return m.group(0) if m else None

    def header(self, agent: str, mono_rel: str, spec_id: str, extraction: bool = True) -> list:
        tpl = cmdtext.blocks(self.text, "Step 3: Assemble and write view files")[0].text
        out = []
        for l in tpl.rstrip("\n").split("\n"):
            if l.startswith("**Extraction**") and not extraction:
                continue
            out.append(l.replace("<agent>", agent).replace("<monolith-relative-path>", mono_rel)
                       .replace("<ISO-8601>", utc_now()).replace("<spec-id>", spec_id))
        return out + [""]

    def consumer_view(self, agent: str, blocks: list, mono: str, mono_rel: str, spec_id: str) -> str:
        out = self.header(agent, mono_rel, spec_id)
        quote = self.mandate(agent, mono)
        if quote:
            out += ["## Role Mandate", "", "> " + quote, ""]
        for _n, lines, _k, _s in blocks:
            out += lines + [""]
        return "\n".join(out).rstrip("\n") + "\n"

    def orchestrator_view(self, blocks: list, views: dict, mono: str, mono_rel: str, spec_id: str,
                          generated: bool) -> str:
        """Step 4's sections in order; a section with no verbatim monolith content omitted; the
        machine-generated ones (relevance table, views list) only when `generated`."""
        out = self.header("orchestrator", mono_rel, spec_id, extraction=False)
        quote = self.mandate("orchestrator", mono)
        if quote:
            out += ["## Role Mandate (from spec)", "", "> " + quote, "", "---", ""]
        pre = [b for b in blocks if b[3] == "preamble"]
        if pre:
            out += ["## Pipeline Workflow", ""]
            for b in pre:
                out += b[1] + [""]
            out += ["---", ""]
        s9 = [b for b in blocks if b[3] == "9"]
        if s9:
            out += ["## Design & Evidence References", ""]
            for b in s9:
                out += b[1] + [""]
            out += ["---", ""]
        if generated:
            sec = cmdtext.section(self.text, "Step 4: Create orchestrator view")
            table = [l for l in sec.split("\n") if l.startswith("|")]
            rows = []
            for l in table[2:]:  # the template's header and separator rows, then one row per agent
                agent = l.split("|")[1].strip()
                rel = "yes" if agent in self.selected else "no"
                why = ("the requirement changes and verifies one library function" if rel == "yes"
                       else "not needed for a one-function library change")
                rows.append(f"| {agent} | {rel} | {why} |")
            out += ["## Agent Relevance Analysis", "", table[0], table[1]] + rows + [""]
            out += ["## Views Created", ""] + [f"- {n}: {t.count(chr(10))} lines" for n, t in views.items()] + [""]
        lines = mono.split("\n")
        previews = []
        for i, l in enumerate(lines):
            if _SECTION_RE.match(l):
                nxt = [x for x in lines[i + 1:] if x.strip()][:2]
                previews += [l] + nxt + [""]
        if previews:
            out += ["## Monolith Sections", ""] + previews
        return "\n".join(out).rstrip("\n") + "\n"

    def views(self, mono: str, mono_rel: str, spec_id: str, generated: bool = True, dump: bool = False) -> dict:
        assign = self.assignment(mono)
        if dump:  # the coverage-fallback ANTI-PATTERN: qa's blocks dumped into dev's view as well
            assign["dev"] = sorted(assign["dev"] + [b for b in assign["qa"] if b not in assign["dev"]],
                                   key=lambda b: b[0])
        out = {f"{a}.md": self.consumer_view(a, assign[a], mono, mono_rel, spec_id) for a in self.selected}
        out["orchestrator.md"] = self.orchestrator_view(assign["orchestrator"], out, mono, mono_rel, spec_id,
                                                        generated)
        return out

    # ------------------------------------------------------------ the subagent's calls
    def body(self, sub, brief) -> None:
        run, rp = self.run, self.rp
        self.round += 1
        self.stop_round = 0
        project = run.project
        mono_path = brief["Monolith"]
        mono_rel = os.path.relpath(mono_path, project)
        spec_id = brief["Spec id"]
        out_dir = brief["Output folder"].rstrip("/")
        views_dir = f"{project}/{out_dir}/views"
        self.ctx = dict(mono_path=mono_path, mono_rel=mono_rel, spec_id=spec_id, views_dir=views_dir)
        # First actions: Read the monolith, create the views directory.
        sub.read(mono_path, label="spec Read monolith")
        mono = _read(rp, mono_path)
        _sub_bash(sub, f"mkdir -p {shlex.quote(views_dir)}", "Create the views directory", label="spec Bash mkdir views")
        excluded = [a for a in re.findall(r"`([a-z-]+)`", cmdtext.section(self.text, "Step 2: Decide which agents get views")
                                          .split("Priority order")[0]) if a not in self.selected]
        sub.s.say("Agent selection:\n  Included: dev (implements the check in toy/__init__.py), "
                  "qa (verifies the acceptance list)\n  Excluded: " + ", ".join(excluded)
                  + " (a backend change to one function: rule 2)", sub.aid)
        meta = "## Meta-Rules" in mono
        musts = len(re.findall(r"\b(?:MUST|SHOULD)(?: NOT)?\b", mono))
        sub.s.say(f"Meta-Rule discovery:\n  Recognized: {'[]' if not meta else 'see ## Meta-Rules'}\n"
                  f"  Advisory (MUST/SHOULD inline): {musts}\n  Un-parseable: []", sub.aid)
        self.write_views(sub, mono, dump=run.variant == "bad-split" and self.round == 1)
        if self.omit and self.omission_reason():
            # R3.4 as the base text says: append the omission record to views/mandate-omissions.json.
            rec = {"omissions": [{"view": f"{self.omit}.md", "agent": self.omit, "reason": self.omission_reason()}]}
            sub.write(f"{views_dir}/mandate-omissions.json", json.dumps(rec, indent=2) + "\n",
                      label="spec Write mandate-omissions.json")
        self.manifest(sub, mono)
        self.self_check(sub, mono)
        self.coverage(sub)
        self.phase2(sub, mono)

    def write_views(self, sub, mono: str, dump: bool = False) -> None:
        c = self.ctx
        self.current = self.views(mono, c["mono_rel"], c["spec_id"], generated=self.generated, dump=dump)
        for name, text in self.current.items():
            path = f"{c['views_dir']}/{name}"
            if os.path.exists(path):
                sub.read(path, label=f"spec Read view {name}")
                old = _read(self.rp, path)
                if old != text:
                    a, b = edit_pair(old, text)
                    sub.edit(path, a, b, label=f"spec Edit view {name}")
            else:
                sub.write(path, text, label=f"spec Write view {name}")

    def manifest(self, sub, mono: str) -> None:
        """Step 5: manifest.json written under fcntl.LOCK_EX by a Python stanza (venv activated)."""
        c = self.ctx
        sections = sorted({m.group(1) for m in re.finditer(r"^## Section (\d+)", mono, re.M)}, key=int)
        data = {"schema_version": 1, "spec_id": c["spec_id"], "monolith_path": c["mono_rel"],
                "agent_relevance": {a: (a in self.selected) for a in ["ba", "dev", "qa", "ui-specialist", "architect",
                                                                     "product-owner", "user", "pm"]},
                "views": {a: f"views/{a}.md" for a in self.selected},
                "sections_present": {f"S{s}": True for s in sections}}
        stanza = (
            "import fcntl, hashlib, json, os, sys, time\n"
            "views, mono, extra = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])\n"
            "raw = open(mono, 'rb').read()\n"
            "doc = dict(extra, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), lines=raw.count(b'\\n'),\n"
            "           created_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))\n"
            "path = os.path.join(views, 'manifest.json')\n"
            "with open(path, 'a+') as fh:\n"
            "    fcntl.flock(fh, fcntl.LOCK_EX)\n"
            "    fh.seek(0)\n"
            "    fh.truncate()\n"
            "    fh.write(json.dumps(doc, indent=2) + '\\n')\n"
            "print(path)\n")
        cmd = (f"source ~/.claude/venv/bin/activate && python3 - {shlex.quote(c['views_dir'])} "
               f"{shlex.quote(c['mono_path'])} {shlex.quote(json.dumps(data))} <<'PY'\n{stanza}PY")
        _sub_bash(sub, cmd, "Write manifest.json under an exclusive lock", label="spec Bash manifest")

    def verbatim_cmd(self, view: str) -> str:
        """Step 6's Python verbatim check of one view (header skipped, whitelisted lines skipped,
        blockquotes unquoted; exit 1 listing the failing lines)."""
        c = self.ctx
        stanza = (
            "import re, sys\n"
            "mono = open(sys.argv[1]).read()\n"
            "lines = open(sys.argv[2]).read().split('\\n')\n"
            "start = next((i for i, l in enumerate(lines) if l.strip() == '---' and i >= 3), -1) + 1\n"
            "white = [r'^<!--\\s*AUTO-GENERATED', r'^#\\s+\\S.*view of', r'^\\*\\*Monolith\\*\\*:', "
            "r'^\\*\\*Extraction\\*\\*:', r'^---\\s*$', r'^#{2,4}\\s']\n"
            "bad = []\n"
            "for n, l in enumerate(lines[start:], start + 1):\n"
            "    s = l.rstrip()\n"
            "    if not s or any(re.match(w, s) for w in white):\n"
            "        continue\n"
            "    q = s[2:] if s.startswith('> ') else s\n"
            "    if q not in mono:\n"
            "        bad.append((n, s[:100]))\n"
            "for n, s in bad:\n"
            "    print(f'line {n}: not verbatim: {s}')\n"
            "sys.exit(1 if bad else 0)\n")
        return (f"source ~/.claude/venv/bin/activate && python3 - {shlex.quote(c['mono_path'])} "
                f"{shlex.quote(c['views_dir'] + '/' + view)} <<'PY'\n{stanza}PY")

    def self_check(self, sub, mono: str) -> None:
        """Step 6: the verbatim check per view; a failing view is re-extracted (its non-verbatim
        lines left out) and checked again."""
        c = self.ctx
        for name in list(self.current):
            call = _sub_bash(sub, self.verbatim_cmd(name), f"Verbatim check of {name}", label=f"spec Bash verbatim {name}")
            if call.ok:
                continue
            sub.s.say(f"WARNING: verbatim check failed for {name} — retrying extraction", sub.aid)
            self.generated = False
            fixed = self.views(mono, c["mono_rel"], c["spec_id"], generated=False,
                               dump=self.run.variant == "bad-split" and self.round == 1)[name]
            path = f"{c['views_dir']}/{name}"
            sub.read(path, label=f"spec Read view {name} (re-extract)")
            a, b = edit_pair(_read(self.rp, path), fixed)
            sub.edit(path, a, b, label=f"spec Edit view {name} (re-extract)")
            self.current[name] = fixed
            _sub_bash(sub, self.verbatim_cmd(name), f"Verbatim check of {name}", label=f"spec Bash verbatim {name} again")

    def coverage(self, sub) -> None:
        """Step 7's coverage block, as the text spells it."""
        c = self.ctx
        cmd = self.block("Step 7: Coverage verification", index=0)
        cmd = cmd.replace("<spec-id>", c["spec_id"])
        cmd = f"MONOLITH_PATH={shlex.quote(c['mono_path'])}\n" + cmd
        _sub_bash(sub, cmd, "Coverage verification", label="spec Bash coverage")

    def phase2(self, sub, mono: str) -> None:
        c = self.ctx
        checkin = self.block("Writing cp-state files", anchor="check-in")
        try:
            checkpoints = self.block("Writing cp-state files", anchor="spec-check.py checkpoints")
        except cmdtext.TextNotFound:
            checkpoints = None
        status = self.block("Quick sanity test", anchor="status")
        ts = c["spec_id"]
        for agent in self.selected:
            aid = f"{agent}-{c['spec_id']}"
            binds = {"<spec-id>": c["spec_id"], "<agent>": agent, "<agent-id>": aid, "<ts>": ts}
            if self.round == 1:  # a re-split refreshes the checklist of the slot it registered
                _sub_bash(sub, cmdtext.fill(checkin, binds), f"Register {agent}'s cp-state",
                         label=f"spec Bash check-in {agent}")
            actions = self.actions(agent)
            if checkpoints:
                binds.update({"<first checkpoint action>": actions[0], "<second checkpoint action>": actions[1]})
                _sub_bash(sub, cmdtext.fill(checkpoints, binds), f"Set {agent}'s checkpoints",
                         label=f"spec Bash checkpoints {agent}")
            else:
                _sub_bash(sub, self.stanza_checkpoints(agent, aid, actions), f"Set {agent}'s checkpoints",
                         label=f"spec Bash checkpoints stanza {agent}")
        for agent in self.selected:
            _sub_bash(sub, cmdtext.fill(status, {"<spec-id>": c["spec_id"], "<agent>": agent}),
                     f"Sanity check {agent}'s cp-state", label=f"spec Bash status {agent}")

    def actions(self, agent: str) -> list:
        """Two Gawande-style checkpoints anchored on Section 5's verbatim phrases."""
        if agent == "dev":
            return ["Implement in toy/__init__.py: raise TypeError naming the offending argument",
                    "Report that the change keeps the signature add(a, b) and adds no dependency"]
        return ["Measure toy.add(1, 2) still returns 3 and toy.add(None, 2) raises TypeError naming argument a",
                "Record that tests/test_add.py keeps passing"]

    def stanza_checkpoints(self, agent: str, aid: str, actions: list) -> str:
        """The base text's Python stanza: enumerate the agent's slots, primary first, keep the one
        whose agent_id matches and is_running, set its checkpoints under fcntl.LOCK_EX."""
        c = self.ctx
        stanza = (
            "import fcntl, glob, json, os, sys\n"
            "d, agent, aid, actions = sys.argv[1], sys.argv[2], sys.argv[3], json.loads(sys.argv[4])\n"
            "slots = [os.path.join(d, f'cp-state-{agent}.json')] + sorted(glob.glob(os.path.join(d, f'cp-state-{agent}-*.json')))\n"
            "for p in slots:\n"
            "    if not os.path.isfile(p):\n"
            "        continue\n"
            "    with open(p) as fh:\n"
            "        data = json.load(fh)\n"
            "    if data.get('agent_id') != aid or not data.get('is_running'):\n"
            "        continue\n"
            "    data['checkpoints'] = [{'id': f'cp-{i:02d}', 'action': a, 'state': 'pending', 'waived_reason': None,\n"
            "                            'updated_at': None} for i, a in enumerate(actions, 1)]\n"
            "    with open(p + '.lock', 'w') as lock:\n"
            "        fcntl.flock(lock, fcntl.LOCK_EX)\n"
            "        with open(p, 'w') as fh:\n"
            "            json.dump(data, fh, indent=2)\n"
            "    print(p)\n"
            "    sys.exit(0)\n"
            "sys.exit('no running cp-state slot for ' + aid)\n")
        d = f"{self.run.project}/.claude/specs/{c['spec_id']}"
        return (f"source ~/.claude/venv/bin/activate && python3 - {shlex.quote(d)} {agent} {aid} "
                f"{shlex.quote(json.dumps(actions))} <<'PY'\n{stanza}PY")

    def final(self, sub=None) -> str:
        c = self.ctx
        counts = {n[:-3]: t.count("\n") for n, t in self.current.items()}
        out = {"spec_id": c["spec_id"],
               "phase0": {"agents_selected": list(self.selected),
                          "agents_excluded": ["ba", "pm", "architect", "product-owner", "user", "ui-specialist"],
                          "reasoning": "a backend change to one library function: dev implements, qa verifies"},
               "phase1": {"ran": True, "intelligent_extraction": True,
                          "views_created": list(self.selected) + ["orchestrator"], "line_counts": counts,
                          "verbatim_verification_passed": len(self.current), "verbatim_verification_failed": 0,
                          "coverage_percentage": 100.0},
               "phase2": {"agents_processed": list(self.selected),
                          "cp_state_files": {a: f".claude/specs/{c['spec_id']}/cp-state-{a}.json" for a in self.selected},
                          "checkpoint_counts": {a: 2 for a in self.selected}},
               "codex_consult": {"invoked": False, "status": "not_requested", "feedback_summary": None,
                                 "feedback_incorporated": None}}
        if self.omit:
            out["phase1"]["mandate_omitted"] = {f"{self.omit}.md": "candidate role lines conflict (R3.4)"}
        return json.dumps(out, indent=2)

    def on_stop_block(self, sub, ev):
        """A block at the subagent's stop: the split goes back to it. A split it can fix (the bad
        split's dumped blocks) is re-extracted as its text says and checked again; one it cannot fix
        without fabricating (an omitted Role Mandate) is reported as it stands."""
        self.stop_round += 1
        text = "\n".join(h.get("stderr", "") + h.get("stdout", "") for h in ev.blocks)
        mono = _read(self.rp, self.ctx["mono_path"])
        if self.run.variant == "bad-split" and self.stop_round == 1:
            sub.s.say("The split was returned: pairwise overlap above the threshold. Restarting Phase 1 "
                      "without the fallback dump.", sub.aid)
            self.write_views(sub, mono)
            self.self_check(sub, mono)
            _sub_bash(sub, self.block("Coverage fallback (deterministic, no LLM judgment)", anchor="--strict")
                     .replace("<spec-id>", self.ctx["spec_id"]).replace('"$MONOLITH_PATH"', shlex.quote(self.ctx["mono_path"])),
                     "Strict verification", label="spec Bash strict verify")
            return self.final()
        if self.stop_round == 1:
            sub.s.say("The split was returned:\n" + text[-1500:] + "\nNothing in it can change without "
                      "fabricating content the monolith does not hold (R3.4 / verbatim-only rule).", sub.aid)
            return self.final()
        return None


# ---------------------------------------------------------------- /spec

class SpecRun:
    def __init__(self, rp, variant: str, size: str = "large", session=None):
        self.rp, self.variant = rp, variant
        self.project = rp.layout.project
        self.requirement = REQUIREMENT_SMALL if size == "small" else REQUIREMENT_LARGE
        self.findings = FINDINGS_SMALL if size == "small" else FINDINGS_LARGE
        self.o = Orchestrator(rp, "spec", session=session, deviations=DEVIATIONS,
                              rules=self._rules(), line_rules=self._line_rules())
        self.s = self.o.s
        self.st = SpecText(self.o)
        self.ts = ""
        self.path = ""
        self.spec_id = ""
        self.turn = 0
        self.agent = SpecAgent(self)
        self.qa_round = 0
        self.issues: list = []

    # ------------------------------------------------------------ binding rules
    def _rules(self):
        return [
            (r"^spec_path$", lambda m: self.path),
            (r"^absolute path$", lambda m: self.path),
            (r"^spec-id$", lambda m: self.spec_id),
            (r"^de-prefixed-id$", lambda m: self.spec_id),
            (r"^YYYYMMDD-HHMMSS$", lambda m: self.ts),
            (r"^MONOLITH_LINES$", lambda m: self.o.values.get("MONOLITH_LINES", "")),
            (r"^\$CLAUDE_PROJECT_DIR$", lambda m: self.project),
            (r"^ISO-8601", lambda m: utc_now()),
            (r"^what the user mentioned$", MENTIONED),
            (r"^JSON array of issues", lambda m: json.dumps(self.issues)),
            (r"^N$", lambda m: str(self.qa_round)),
            (r"^populated from Explore findings", "populated from Explore findings"),
        ]

    def _line_rules(self):
        return [(r"^\s*<If codex_required = true, include the literal next line", lambda l: DROP_NEXT)]

    # ------------------------------------------------------------ helpers
    def to(self, n: int) -> None:
        while not self.o.at_step(n):
            self.o.advance()

    def spec_text(self) -> str:
        return _read(self.rp, self.path)

    def write_append(self, section: str, block: str, label: str, inline: tuple | None,
                     replace_placeholder: bool = False):
        """Append `block` to a section as the tree's text says: its writer call, or the main agent's
        own Edit of the file (which it wrote, so the CLI holds its content)."""
        if self.st.writer:
            heading, anchor = inline
            cmd = self.st.call(self.st.inline(heading, anchor, section), block)
            return self.o.run(cmd, f"Append to Section {section} through the spec writer", label)
        old = self.spec_text()
        new = appended(old, section, block, replace_placeholder)
        a, b = edit_pair(old, new)
        return self.s.edit(self.path, a, b, label=label, deviation=self.o.devs.at(label))

    def end_turn(self, text: str, label: str) -> None:
        self.s.stop(text, label=label, deviation=self.o.devs.at(label))

    # ------------------------------------------------------------ turn 1: /spec <requirement>
    def turn1(self) -> None:
        o, s = self.o, self.s
        self.turn = 1
        o.slash(self.requirement)
        o.todo_start()
        # Step 1: no --codex token; non-empty requirement -> Step 3. Step 2: not triggered.
        self.to(3)
        self.step3()
        o.advance()  # Step 3 done, Step 4 in progress
        self.end_turn(f"Spec written to {self.path}. Tell me more requirements whenever you are ready.",
                      "Stop turn 1")

    def step3(self) -> None:
        o, s, rp = self.o, self.s, self.rp
        sec = o.section("Step 3")
        tpl_rel = re.search(r"Read the template at `([^`]+)`", sec).group(1)
        tpl = tpl_rel.replace("~", rp.layout.home, 1)
        s.read(tpl, label="Step 3 Read template", deviation=o.devs.at("Step 3 Read template"))
        text = _read(rp, tpl)
        self.ts = utc_now().replace("-", "").replace(":", "").replace("T", "-").rstrip("Z")
        rp.task(self.ts)
        path_line = next(b.text for b in cmdtext.blocks(o.text, "Step 3") if "docs/dev/specs/spec-" in b.text).strip()
        path_line = re.sub(r"\$\{CLAUDE_PROJECT_DIR:-\$\(pwd\)\}", self.project, path_line)
        self.path = o.bind(path_line)
        # Step 3 item 3: the placeholders it names, Section 5 the requirement verbatim.
        pop = sec[sec.index("Populate the template"):sec.index("Write the spec")]
        for ph in re.findall(r"`(<[^`>]+>)`\s*→", pop):
            val = {"<issue_description>": SUMMARY, "<ISO-8601>": utc_now()}.get(ph)
            if val is None:
                raise cmdtext.TextNotFound(f"Step 3 item 3 names {ph}, which the driver cannot fill")
            text = text.replace(ph, val)
        if "Section 5 → user's requirement verbatim" in pop:
            text = appended(text, "5", self.requirement, replace_placeholder=True)
        self.populated = text
        if self.st.writer:
            o.run_text(self.st.create_block, "Step 3 Bash spec-write create", "Write the first spec",
                       extra_rules=[(r"^the populated template$", text)])
        else:
            if "Create `docs/dev/specs/` if it does not exist" in sec:
                o.run(f"mkdir -p {shlex.quote(os.path.dirname(self.path))}", "Create docs/dev/specs/",
                      "Step 3 Bash mkdir specs")
            s.write(self.path, text, label="Step 3 Write spec", deviation=o.devs.at("Step 3 Write spec"))
        # The early capture: the first turn carries no design or evidence (sub-step 1 no-op).
        self.explore()
        s.say(f"Spec written: {self.path}. Add more requirements whenever you are ready.")

    def explore(self) -> None:
        """Step 3 item 5: the background Explore dispatch, from the text's own Agent(...) block."""
        o = self.o
        blk = next(b.text for b in cmdtext.blocks(o.text, "Step 3") if "subagent_type=" in b.text)
        fields = dict(re.findall(r'(\w+)="((?:[^"\\]|\\.)*)"', blk))
        flags = {k: v == "true" for k, v in re.findall(r"(\w+)=(true|false)\b", blk)}
        prompt = o.bind(fields["prompt"])
        project = self.project

        def body(sub):
            for rel in ("toy/__init__.py", "tests/test_add.py"):
                sub.read(f"{project}/{rel}", label=f"Explore Read {rel}")
            sub.tool("Grep", {"pattern": r"\badd\b", "path": project, "output_mode": "files_with_matches"},
                     label="Explore Grep add")
            sub.read(f"{project}/toy/util.py", label="Explore Read toy/util.py")

        label = "Step 3 Agent(Explore) background"
        self.s.dispatch(fields["subagent_type"], prompt, description=fields.get("description", ""), body=body,
                        result=self.findings, label=label, deviation=o.devs.at(label),
                        extra_input={"run_in_background": flags.get("run_in_background", False)})

    # ------------------------------------------------------------ turn 2: the Explore notification
    def turn_notification(self) -> None:
        s = self.s
        s.append({"type": "user", "message": {"role": "user", "content": (
            "<task-notification>\n<status>completed</status>\n<summary>Agent \"Spec background exploration\" "
            f"completed</summary>\n<result>{self.findings}</result>\n</task-notification>")}})
        # "Exploration findings arrive -> integrate into Section 1 (Before) silently."
        self.write_append("1", self.findings, "Turn 2 Section 1 findings",
                          ("Step 4", "Exploration findings arrive"), replace_placeholder=True)
        self.end_turn("Folded the exploration findings into Section 1.", "Stop turn 2")

    # ------------------------------------------------------------ turn 3: another requirement
    def turn_requirement(self) -> None:
        o = self.o
        self.turn += 1
        self.s.prompt(FOLLOW_UP, label="prompt follow-up requirement", deviation=o.devs.at("prompt follow-up requirement"))
        # Capture precondition: nothing to capture. Branch: another requirement -> ### 5.N.
        tpl = next(b.text for b in cmdtext.blocks(o.section("Step 4"), None) if "### 5.N" in b.text)
        n = 2 + len(re.findall(r"^### 5\.\d+", self.spec_text(), re.M))
        block = o.bind(tpl.replace("### 5.N:", f"### 5.{n}:"),
                       [(r"^brief title extracted", FOLLOW_UP_TITLE), (r"^verbatim requirement text$", FOLLOW_UP)])
        self.write_append("5", block, "Turn 3 Section 5 append", ("Step 4", "Another requirement"))
        self.end_turn(f"Added it to the spec as 5.{n}.", "Stop turn 3")

    # ------------------------------------------------------------ turn 4: design only
    def turn_design(self) -> None:
        o, s = self.o, self.s
        self.turn += 1
        s.prompt(DESIGN, label="prompt design", deviation=o.devs.at("prompt design"))
        routine = "Design & Evidence Capture Routine"
        o.values.update(spec_path=self.path, CLAUDE_PROJECT_DIR=self.project)
        for name, b, _para in o.step_blocks(routine):
            o.run_text(b.text, f"Capture Bash {name}", f"Capture routine: {name}",
                       capture=("SPEC_DIR_ID", "BOUND_ROOT"))
        self.spec_id = o.values.get("SPEC_DIR_ID") or ""
        if not self.spec_id:
            raise cmdtext.TextNotFound("the capture routine's resolver block gave no SPEC_DIR_ID")
        bound = o.values.get("BOUND_ROOT") or f"{self.project}/docs/dev/specs/{self.spec_id}"
        # sub-step 3/4: design/turn-<N>-<slug>.md, the user's HOW-text verbatim.
        name = f"turn-{self.turn}-{DESIGN_SLUG}.md"
        s.write(f"{bound}/design/{name}", DESIGN + "\n", label="Capture Write design turn",
                deviation=o.devs.at("Capture Write design turn"))
        ref_tpl = next(b.text for b in cmdtext.blocks(o.section(routine), None) if "/design/turn-<N>-<slug>.md" in b.text)
        ref = o.bind(ref_tpl.strip().replace("turn-<N>-<slug>.md", name),
                     [(r"^one-line description$", DESIGN_LINE)])
        self.write_append("9.1", ref, "Capture Section 9.1 reference", (routine, "ADDITIVE mirror"),
                          replace_placeholder=True)
        self.end_turn("Saved the design and referenced it in Section 9.", "Stop turn 4")

    # ------------------------------------------------------------ turn 5: the strong signal, finalize
    def turn_finalize(self) -> None:
        o, s = self.o, self.s
        self.turn += 1
        s.prompt(CLOSING, label="prompt conclusion", deviation=o.devs.at("prompt conclusion"))
        self.to(6)
        self.finalize()
        o.advance()  # Step 6 done, Step 7 in progress
        self.step7()
        o.advance()  # Step 7 done
        s.stop(self.display, label="Stop", deviation=o.devs.at("Stop"))

    def finalize(self) -> None:
        o, s = self.o, self.s
        sec = o.section("Step 6")
        # 0. Section-9 dangling-reference guard: the sentinel lines skipped, every real reference checked.
        sentinel = re.search(r"sentinel\s+pattern `([^`]+)`", sec)
        rx = re.compile(sentinel.group(1) if sentinel else _SENTINEL_FALLBACK)
        lines = self.spec_text().split("\n")
        start, end = section_range(lines, r"^## Section 9\b", 2)
        refs = []
        for l in lines[start:end]:
            if rx.search(l):
                continue
            refs += re.findall(r"`(docs/dev/specs/[^`]+/(?:design|evidence)/[^`]+)`", l)
        if refs:
            o.run("ls -l " + " ".join(shlex.quote(f"{self.project}/{r}") for r in refs),
                  "Section 9 guard: every referenced design/evidence file exists", "Step 6 Bash Section 9 guard")
        # 1. MONOLITH_LINES.
        count = next(c for c in cmdtext.inline_codes(o.text, "Step 6", "Count monolith lines") if "MONOLITH_LINES=" in c)
        o.run_text(count, "Step 6 Bash MONOLITH_LINES", "Count monolith lines", capture=("MONOLITH_LINES",))
        # 2-3. The spec subagent and the split QA loop.
        self.dispatch_spec(0, "Step 6 Agent(spec)")
        verdict = self.split_qa()
        while verdict == "fail" and self.qa_round < 3:
            s.say(f"Split-QA round {self.qa_round}/3: QA found {len(self.issues)} issue(s). "
                  "Re-invoking spec subagent with feedback.")
            # The correction each issue asks for: the block it names (in parentheses) added to its view.
            for issue in self.issues:
                named = re.search(r"\(([^)]+)\)", issue["issue"])
                self.agent.extra.setdefault(issue["view"], []).append(named.group(1))
            self.dispatch_spec(2, f"Step 6 Agent(spec) re-split round {self.qa_round}")
            verdict = self.split_qa()
        # 4. The marker, written by this command after the split QA's last verdict.
        marker_item = next(it for it in re.split(r"\n(?=\d+\.\s)", sec) if ".split-complete" in it and "Mark split" in it)
        content = re.search(r'Write `"([^`]+)"` to `([^`]+)`', marker_item)
        marker_path = f"{self.project}/{o.bind(content.group(2))}"
        o.run(f'printf \'%s\\n\' "{content.group(1)}" > {shlex.quote(marker_path)}', "Mark the split complete",
              "Step 6 Bash split-complete")
        # 5. Finalize guard; 6. centralization lint.
        o.values.update(spec_path=self.path, CLAUDE_PROJECT_DIR=self.project)
        o.run_text(o.block("Step 6", anchor="FINALIZE BLOCKED"), "Step 6 Bash finalize guard", "Finalize guard",
                   capture=("VIEWS_AVAILABLE", "ARTIFACT_ID"))
        o.run_text(o.block("Step 6", anchor="lint-spec-id-centralization"), "Step 6 Bash centralization lint",
                   "Centralization lint (advisory)")

    def spec_template(self, index: int) -> dict:
        return o_template(self.o, "Step 6", index)

    def dispatch_spec(self, index: int, label: str):
        o = self.o
        fields = self.spec_template(index)
        prompt = o.render(fields, self.spec_id)
        atype = fields.get("subagent_type") or _subagent_of(o, prompt)
        brief = dict(re.findall(r"^\s*(Spec id|Monolith|Monolith lines|Output folder|Project dir):\s*(\S+)\s*$",
                                prompt, re.M))
        agent = self.agent
        return self.s.dispatch(atype, prompt, description=o.bind(fields.get("description", "") or atype),
                               body=lambda sub: agent.body(sub, brief), result=agent.final, label=label,
                               deviation=o.devs.at(label), on_stop_block=agent.on_stop_block)

    def split_qa(self) -> str:
        o = self.o
        self.qa_round += 1
        fields = o_template(o, "Step 6", 1)
        prompt = o.render(fields, self.spec_id)
        fail = self.variant == "split-qa-fail" and self.qa_round == 1
        views = f"{self.project}/docs/dev/specs/{self.spec_id}/views"
        codes = re.findall(r"`([^`\n]+)`", prompt[prompt.index("3. COVERAGE"):prompt.index("4. CONTENT")])
        find = next(c for c in codes if c.startswith("VERIFIER="))
        verify = next(c for c in codes if '"$VERIFIER"' in c)
        project, path = self.project, self.path

        def body(sub):
            sub.read(path, label="qa split Read monolith")
            for name in sorted(os.listdir(views)):
                if name.endswith(".md"):
                    sub.read(f"{views}/{name}", label=f"qa split Read view {name}")
            cmd = (f"{find}\nif [ -n \"$VERIFIER\" ] && [ -f \"$VERIFIER\" ]; then\n  {verify}\nelse\n"
                   "  echo \"spec-verify.py not found — manual coverage check required\"\nfi")
            _sub_bash(sub, cmd, "Split QA check 3: coverage", label="qa split Bash coverage")

        if fail:
            self.issues = [SPLIT_QA_ISSUE]
            result = json.dumps({"verdict": "fail", "issues": self.issues,
                                 "summary": "one Section 1 line qa needs is only in dev.md"})
        else:
            result = json.dumps({"verdict": "pass", "issues": [], "summary": "views cover the monolith; "
                                 "each view holds what its agent needs"})
        label = f"Step 6 Agent(qa) split QA round {self.qa_round}"
        self.s.dispatch(fields.get("subagent_type") or "qa", prompt, description=o.bind(fields.get("description", "")),
                        body=body, result=result, label=label, deviation=o.devs.at(label))
        return "fail" if fail else "pass"

    def step7(self) -> None:
        """/spec-update --temp as that command's text says, then the display block."""
        o, s, rp = self.o, self.s, self.rp
        su = Orchestrator(rp, "spec-update", session=s, deviations=o.devs)
        mk = su.inline("Temp-note mode", "mktemp", startswith="mktemp")
        c = o.run(mk, "Create the temp update note", "Step 7 Bash mktemp update note")
        note_path = c.response.get("stdout", "").strip() if c.ok else ""
        disp = o.bind(cmdtext.blocks(o.section("Step 7"), None)[0].text,
                      [(r"^absolute path$", self.path), (r"^temp update path", note_path or "(none)")])
        disp = "\n".join(l for l in disp.split("\n")
                         if not (l.startswith("<If split-QA exhausted") or l.startswith("⚠ Split-QA")))
        self.display = disp.replace(" N requirements", " 2 requirements")
        if not note_path:
            return
        m = re.search(r"update-([A-Za-z0-9]+)\.md$", note_path)
        if m:
            rp.rand(m.group(1))
        s.read(note_path, label="Step 7 Read update note", deviation=o.devs.at("Step 7 Read update note"))
        note = su.block("Temp-note mode", anchor="# Update")
        note = su.bind(note, [(r"^short focus$", "implement the spec with /dev"), (r"^ISO-8601$", utc_now()),
                              (r'id or "unknown"', self.spec_id), (r"^spec\|dev\|close", "spec"),
                              (r"exact next command", "/dev (in this session) or /dev --spec " + self.path),
                              (r"^path or URL$", self.path),
                              (r".", f"see {self.path} and docs/dev/specs/{self.spec_id}/views/")])
        s.write(note_path, note, label="Step 7 Write update note", deviation=o.devs.at("Step 7 Write update note"))

    # ------------------------------------------------------------ the whole /spec
    def run(self) -> "SpecRun":
        self.turn1()
        self.turn_notification()
        self.turn_requirement()
        self.turn_design()
        self.turn_finalize()
        return self


def o_template(o: Orchestrator, heading: str, index: int) -> dict:
    return o.template(heading, index=index)


def _subagent_of(o: Orchestrator, prompt: str) -> str:
    """A template that names no subagent_type: the agent its prompt says it is ("You are the <x>
    subagent"), when agents/<x>.md exists in the tree."""
    m = re.search(r"You are the (\S+) subagent", prompt)
    if m and o.tree.agent_text(m.group(1)):
        return m.group(1)
    raise cmdtext.TextNotFound("the dispatch template names no subagent_type and no agent")


# ---------------------------------------------------------------- /spec-update on that spec

class SpecUpdate:
    """/spec-update's continuation mode and its --update mode on the spec /spec wrote, typed in a
    later session, as commands/spec-update.md of the tree says."""

    def __init__(self, rp, spec: SpecRun):
        self.rp, self.spec = rp, spec
        self.path, self.spec_id, self.project = spec.path, spec.spec_id, spec.project

    def orchestrator(self, session) -> Orchestrator:
        return Orchestrator(self.rp, "spec-update", session=session, deviations=DEVIATIONS)

    def writer_block(self, o: Orchestrator):
        """The text's writer example (`spec-write.py append ... <<'X'`), or None where the text has
        the main agent write the spec itself."""
        for b in cmdtext.blocks(o.text, "Continuation-spec mode", "bash"):
            if "spec-write.py append" in b.text:
                return b.text
        return None

    def writer_appends(self, o: Orchestrator):
        """The text's writer example split into its appends, (opener, terminator) each; None where the
        text has the main agent write the spec itself."""
        ex = self.writer_block(o)
        if not ex:
            return None
        lines = ex.rstrip("\n").split("\n")
        at = [i for i, l in enumerate(lines) if "spec-write.py append" in l]
        return [(lines[i], lines[(at[k + 1] if k + 1 < len(at) else len(lines)) - 1]) for k, i in enumerate(at)]

    def chained(self, o: Orchestrator) -> bool:
        """Whether the text puts a run's appends in one Bash call (its example chains them with &&)."""
        units = self.writer_appends(o)
        return bool(units) and len(units) > 1 and units[0][0].rstrip().endswith("&&")

    def one_call(self, o: Orchestrator, items: list, label: str):
        """A run's appends [(section, block)] in one Bash call, chained as the text's example chains
        them: every append but the last takes the example's chained opener, the last its closing one."""
        units, out = self.writer_appends(o), []
        for n, (section, block) in enumerate(items):
            opener, term = units[0] if n < len(items) - 1 else units[-1]
            opener = re.sub(r"--spec \S+", "--spec " + shlex.quote(self.path), opener)
            opener = re.sub(r"--section \S+", f"--section {section}", opener)
            out.append(f"{opener}\n{block.rstrip(chr(10))}\n{term}")
        return o.run("\n".join(out), "Append to Sections " + ", ".join(s for s, _ in items), label)

    def append(self, o: Orchestrator, section: str, block: str, label: str, replace_placeholder=False):
        units = self.writer_appends(o)
        if units:
            opener, term = units[-1]
            first = re.sub(r"--spec \S+", "--spec " + shlex.quote(self.path), opener)
            first = re.sub(r"--section \S+", f"--section {section}", first)
            return o.run(f"{first}\n{block.rstrip(chr(10))}\n{term}", f"Append to Section {section}", label)
        old = _read(self.rp, self.path)
        new = appended(old, section, block, replace_placeholder)
        a, b = edit_pair(old, new)
        return o.s.edit(self.path, a, b, label=label, deviation=o.devs.at(label))

    def todo(self, o: Orchestrator, prefix: str) -> None:
        try:
            o.todo_start(label=f"{prefix} TodoWrite canonical list")
        except cmdtext.TextNotFound:
            o.todos = None

    def predates(self, o: Orchestrator, prefix: str) -> bool:
        """Whether the spec has a split or cp-state files (the Section 8 note's condition)."""
        hits = 0
        for pattern, base in ((f"{self.spec_id}/views/*", f"{self.project}/docs/dev/specs"),
                              ("cp-state-*.json", f"{self.project}/.claude/specs/{self.spec_id}")):
            g = o.s.tool("Glob", {"pattern": pattern, "path": base}, label=f"{prefix} Glob {pattern}",
                         deviation=o.devs.at(f"{prefix} Glob {pattern}"))
            hits += len(g.response.get("filenames", [])) if g.ok else 0
        return hits > 0

    def continuation(self, session) -> None:
        o = self.orchestrator(session)
        prefix = "/spec-update"
        o.slash(f"--spec {self.path} {CONTINUATION_FOCUS}", label=prefix)
        self.todo(o, prefix)
        o.s.read(self.path, label=f"{prefix} Read spec", deviation=o.devs.at(f"{prefix} Read spec"))
        text = _read(self.rp, self.path)
        lines = text.split("\n")
        start, end = section_range(lines, r"^## Section 1\b", 2)[0], section_range(lines, r"^## Section 7\b", 2)[1]
        cycle = 1 + max([int(n) for n in re.findall(r"^### Cycle (\d+)", "\n".join(lines[start:end]), re.M)] or [0])
        marker_rx = re.search(r"`(<!-- spec-continuation-of: <resolved-task-id> -->)`", o.text)
        marker = marker_rx.group(1).replace("<resolved-task-id>", self.spec_id) if marker_rx else None
        split = self.predates(o, prefix)
        content = {
            "2": "- Nothing attempted yet: /spec wrote the spec; no /dev cycle has run.",
            "3": "- No files changed.",
            "4": "- toy.add still returns a + b for any arguments (no check); tests/test_add.py passes.",
            "6": "- toy.add('1', 2) returns '12' where the spec asks for a TypeError naming argument a.",
            "7": f"- Run /dev --spec {self.path} to add the type check at the top of toy.add.",
            "8": ("- The split views under docs/dev/specs/{id}/views/ and .claude/specs/{id}/cp-state-*.json "
                  "predate this continuation update; do not treat them as fresh until /spec splits the spec "
                  "again.".format(id=self.spec_id) if split else "- No split views or checkpoints exist yet."),
        }
        items = []
        for sec in ("2", "3", "4", "6", "7", "8"):
            block = f"### Cycle {cycle}\n{content[sec]}"
            if not items and marker and marker not in text:
                block = marker + "\n" + block
            items.append((sec, block))
        if self.chained(o):
            self.one_call(o, items, f"{prefix} Cycle {cycle} appends")
        else:
            for sec, block in items:
                self.append(o, sec, block, f"{prefix} Section {sec} Cycle {cycle}")
        done = f"Continuation spec: {self.path}\nNext: /dev --spec {self.path}"
        if o.todos:
            while o.current() is not None:
                o.advance()
        o.s.stop(done, label=f"{prefix} Stop", deviation=o.devs.at(f"{prefix} Stop"))

    def update(self, session) -> None:
        o = self.orchestrator(session)
        prefix = "/spec-update --update"
        o.slash(f"--update --spec {self.path} {UPDATE_TEXT}", label=prefix)
        self.todo(o, prefix)
        o.s.read(self.path, label=f"{prefix} Read spec", deviation=o.devs.at(f"{prefix} Read spec"))
        text = _read(self.rp, self.path)
        n = 1 + max([int(x) for x in re.findall(r"^### 5\.(\d+)", text, re.M)] or [1])
        five = f"### 5.{n}: {UPDATE_TITLE}\n{UPDATE_TEXT}"
        note = (f"- 5.{n} was added after the split: the views under docs/dev/specs/{self.spec_id}/views/ "
                f"and .claude/specs/{self.spec_id}/cp-state-*.json predate it; regenerate before "
                "treating them as fresh.")
        if self.chained(o):
            # The run's appends go in one call: whether the note is due is known before it.
            items = [("5", five)] + ([("8", note)] if self.predates(o, prefix) else [])
            self.one_call(o, items, f"{prefix} appends 5.{n}")
        else:
            self.append(o, "5", five, f"{prefix} Section 5 append 5.{n}")
            if self.predates(o, prefix):
                self.append(o, "8", note, f"{prefix} Section 8 note")
        if o.todos:
            while o.current() is not None:
                o.advance()
        o.s.stop(f"Spec updated: {self.path} (5.{n}).", label=f"{prefix} Stop", deviation=o.devs.at(f"{prefix} Stop"))


# ---------------------------------------------------------------- entry

VARIANTS = ("plain", "omission", "bad-split", "split-qa-fail", "update")


def run(rp) -> None:
    variant = rp.args.get("variant", "plain")
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    size = rp.args.get("req", "large")
    if size not in ("large", "small"):
        raise ValueError(f"unknown req {size!r}")
    rp.pipeline = {"plain": "spec", "update": "spec-update"}.get(variant, f"spec/{variant}") + (
        "/small" if size == "small" else "")
    spec = SpecRun(rp, "plain" if variant == "update" else variant, size=size).run()
    if variant == "update":
        su = SpecUpdate(rp, spec)
        later = rp.later_session(spec.s)
        su.continuation(later)
        su.update(rp.later_session(later))
