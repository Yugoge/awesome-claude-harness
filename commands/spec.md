---
description: Create spec files for any dev workflow (/dev, /dev-overnight, or standalone reference). Pass --codex to enable adversarial codex consultation on each spec-subagent / QA dispatch; default is self-review only.
argument-hint: "[--codex] [<requirement>]"
disable-model-invocation: true
---

# /spec: General-Purpose Spec Manager

You manage spec files. `$ARGUMENTS` may be empty or hold the user's first requirement; either way, act immediately.

---

## Spec Creation Mode

Act on whatever the user provides; ask only when the input cannot become a Section 5 skeleton at all. After the first spec, stay in a multi-turn loop that appends each follow-up requirement to the SAME file, and finalize only on a natural-conclusion signal.

### Step 1: Parse $ARGUMENTS

If `$ARGUMENTS` contains the literal token `--codex` (any position), strip it from the requirement text and set `codex_required = true`; otherwise `codex_required = false`. When true, every spec-subagent and QA dispatch prompt below carries the literal line `codex_required: true`, which activates the opt-in codex consultation block (`templates/prompt-includes/codex-consultation.md`, which `agents/<role>.md` points to). When false, omit that line: the subagents skip consultation and emit `codex_consult: { invoked: false, status: "not_requested" }`.

Then branch on the remaining text:

- **Non-empty non-flag text**: it is the first requirement. Go to Step 3.
- **Empty**: ask once with ONE AskUserQuestion in the user's language (en or zh): what should this spec be about, with 2-4 likely areas as options (the owner can type their own); use the answer as the first requirement.

No preview-and-confirm gate. The owner's intent, scope, edge cases and acceptance are asked in the requirement round (Step 3a), never in plain text.

### Step 2: Clarify if truly unclear (max 3 rounds)

Only when Section 5 cannot be sketched at all: no topic, feature or issue, no actionable phrase ("help", "fix it", "something's wrong", a bare emoji). Otherwise go to Step 3.

1. Ask ONE specific question about what Section 5 should say, with AskUserQuestion inside the turn.
2. If Section 5 can now be sketched, go to Step 3; otherwise ask again.
3. After the 3rd answer, proceed anyway: write whatever Section 5 content you can extract plus an `_Assumption_` note.

### Step 3: Write first spec + dispatch background Explore

1. Read the template at `<HARNESS_ROOT>/templates/overnight-spec.md` at runtime (never hardcode it). If it is missing, report the error and stop.

2. The spec path, always in the parent project directory and never inside an overnight worktree:
   ```
   ${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}/docs/dev/specs/spec-<YYYYMMDD-HHMMSS>.md
   ```
   Keep it as `spec_path`. A fresh `/spec` in a new session makes a new timestamped file; follow-ups within the session append to this one.

3. Populate the template, keeping its structure exactly:
   - `<issue_description>` → short summary of the user's requirement
   - `<ISO-8601>` → current timestamp
   - Section 5 → user's requirement verbatim
   - every other section → `_Not yet populated._` (Section 9's two subsections keep their `<!-- consumers: [all] -->` line above the placeholder until their first entry)

4. Write the spec through its one writer, `<HARNESS_ROOT>/scripts/spec-write.py`, naming it by its absolute path (the `UserPromptSubmit` hook of the `/dev`, `/dev-command` or `/dev-overnight` that implements this spec takes this session's last spec write as that run's spec, from the line the writer prints). It creates `docs/dev/specs/` if needed and refuses an existing file:

   ```bash
   python3 "<HARNESS_ROOT>/scripts/spec-write.py" create --spec <spec_path> <<'SPEC_TEXT'
   <the populated template>
   SPEC_TEXT
   ```

   Every later write of this spec runs through the same script: `spec-write.py append --spec <spec_path> --section <N>` (or `<N>.<M>` for a `### N.M` subsection) adds the stdin text at the end of that section, or in place of its lone `_Not yet populated._` line. Never Write or Edit a spec file.

   Then run the **Design & Evidence Capture Routine** (below Step 4) on the first turn's material, before the acknowledgement; it does nothing when the turn carries none. This is the only first-turn capture point, and it must not wait for finalize, which is too late: the material would be lost.

5. When the user names specific files, components, features or technical terms, dispatch an Explore agent in the background:
   ```
   Agent(
     subagent_type="Explore",
     run_in_background=true,
     description="Spec background exploration",
     prompt="Find and summarize <what the user mentioned>. Report: file paths, current behavior, relevant code snippets. Thoroughness: medium."
   )
   ```
   Findings integrate when they arrive (Step 4); a discrepancy may surface as one targeted question but never gates the loop. While this interview's checklist has an open step, `hooks/pretool-spec-block-foreground-agent.py` exits 2 on a foreground Agent call other than the `spec`, `qa` and `ba` subagents; the ledger lists it as advisory (H-026), since no host run has observed it prevent a call.

6. Acknowledge that the spec was written, with the full `<spec_path>`, and that more requirements can be added whenever the user is ready. Brief, natural, first-person, in the user's language.

Do not split, checkpoint or QA yet: finalize happens exactly once, in Step 6.

### Step 3a: The requirement round (D28, D29, D32)

Right after Section 5's first write, the owner is asked about the requirement. The task id of every dispatch here is the spec id, `<spec-id>`: the timestamp in `spec-<spec-id>.md`. Until round 1 is asked, the dispatch gate refuses every dispatch but round 1's own producers (`ASK_FIRST`), Finalize included.

1. **Three BAs, in parallel and independent**: one response with three foreground Agent calls, angles A (root cause first, traced to the code), B (the smallest change that meets the requirement) and C (the owner's intent, the product view); none is given another's report:
   ```
   Use Agent tool with:
   - subagent_type: "ba"
   - run_in_background: false
   - description: "BA panel <angle> for spec <spec-id>"
   - prompt: "
     You are the BA subagent. Follow <HARNESS_ROOT>/agents/ba.md instructions precisely.
     Mode: panel
     Angle: <angle>
     Spec: <spec_path>
     <If codex_required = true, include the literal next line; otherwise omit it>
     codex_required: true
     Obligation block (instantiate per dispatch: dispatched_at is the UTC time captured just before this Agent call):
     <obligation v="1">
     {"task_id": "<spec-id>", "lane": null, "lane_set": null, "role": "ba", "pipeline": "spec", "profile": "singular", "dispatched_at": "<ISO-8601 UTC ending in Z>", "artifacts": [{"kind": "markdown", "path": "docs/dev/ba-panel-<spec-id>-<angle>.md", "identity_anchor": "<spec-id>", "terminal_line_regex": "^BA PANEL [ABC]: DONE$"}]}
     </obligation>
     Write your panel report only. Do not read another panel BA's report."
   ```

2. **Panel QA writes round 1** (`agents/qa.md` "Panel QA mode"): it checks each BA's evidence, marks every root cause verified, unsupported or refuted, lists the agreements and turns each disagreement into a decision point, recommended first:
   ```
   Use Agent tool with:
   - subagent_type: "qa"
   - run_in_background: false
   - description: "Panel QA: verify the three BA reports and write round 1 for spec <spec-id>"
   - prompt: "
     You are the QA subagent in PANEL QA MODE. Follow <HARNESS_ROOT>/agents/qa.md "Panel QA mode" precisely.
     Panel reports: docs/dev/ba-panel-<spec-id>-A.md, docs/dev/ba-panel-<spec-id>-B.md, docs/dev/ba-panel-<spec-id>-C.md
     Spec: <spec_path>
     <If codex_required = true, include the literal next line; otherwise omit it>
     codex_required: true
     Obligation block (instantiate per dispatch: dispatched_at is the UTC time captured just before this Agent call):
     <obligation v="1">
     {"task_id": "<spec-id>", "lane": null, "lane_set": null, "role": "qa", "pipeline": "spec", "profile": "ba_validation", "dispatched_at": "<ISO-8601 UTC ending in Z>", "artifacts": [{"kind": "json", "path": "docs/dev/ba-panel-<spec-id>-r1.json", "schema": "requirement-round.v1", "identity": {"task_id": "<spec-id>"}}]}
     </obligation>"
   ```

3. **Ask it**: ONE AskUserQuestion whose `questions` are the round file's questions verbatim with `id`, `dimension`, `assume`, `spec_ref` and each option's `ba` removed, and whose `metadata.source` is `requirement-round:<spec-id>:r<n>`. Never paraphrase it; Skip or no answer is fine (the round counts as asked). The PostToolUse AskUserQuestion hook writes the answers to `docs/dev/requirement-answers-<spec-id>-r<n>.json`.

4. **Copy the answers into Section 5**, byte for byte, through the writer (it adds `### 5.N: Requirement round r<n>`; nothing is retyped):
   ```bash
   python3 "<HARNESS_ROOT>/scripts/spec-write.py" append --spec <spec_path> --section 5 --answers docs/dev/requirement-answers-<spec-id>-r<n>.json
   ```
   With no answer file (the owner skipped), append nothing.

5. **The next round**: dispatch the chosen BA again (the BA whose option the owner chose; when they agreed or none was chosen, the one whose root cause panel QA verified, A, then B, then C), with sub-step 1's template plus the line `Answers: <every docs/dev/requirement-answers-<spec-id>-r<n>.json so far>`. It updates its panel report with the answers or, while a point still needs the owner, writes `docs/dev/requirement-round-<spec-id>-r<n+1>.json` instead; ask that round (3), copy it (4) and repeat. Rounds have no cap; a follow-up requirement in Step 4 that leaves a point open gets the same step.

### Step 4: Multi-turn accumulation loop

One `/spec` invocation spans many user messages; each lands in the SAME `spec_path`. After Step 3, wait for the next message. For EVERY user turn, first run the **capture precondition**: the Design & Evidence Capture Routine on this turn's material. It does nothing when the turn carries no design or evidence, so run it unconditionally, once per turn, at the top: no branch below may proceed or finalize before it, and no branch calls it again.

Then branch on the turn:

- **Strong natural-conclusion signal** (Step 5) → Step 6. The precondition has already persisted any design or evidence the closing turn carried ("here is the runbook screenshot, thanks" is captured, never dropped).
- **Another requirement** → append it to `spec_path` as a new Section 5 sub-section (`spec-write.py append --spec <spec_path> --section 5` with this block on stdin), numbering from 2 (the first requirement populates Section 5 itself: 5.2, 5.3, …); then wait:
  ```
  ### 5.N: <brief title extracted from the message>
  <verbatim requirement text>
  ```
- **Design/evidence only** (no new requirement text, not a conclusion) → the precondition already persisted it to Section 9 and the companion files. Append no `### 5.N` block, leave Section 5 alone, and wait.
- **Exploration findings arrive** → integrate into Section 1 silently (`spec-write.py append --spec <spec_path> --section 1`). If a finding contradicts the user's description, ask one targeted question with AskUserQuestion inside the turn ("I looked at X and found Y; does that match?"), then loop back. Never gate the loop on exploration.
- **Mid-loop vague input** → apply Step 2 (max 3 rounds) to that message before appending, then loop back. A clarification answer is itself a user turn: run the capture precondition on it first, so design or evidence in a reply is not dropped.

Keep `turn_count` internally (not shown to the user), incremented per user response. There is no turn cap: only the Step 5 signal ends the loop.

### Design & Evidence Capture Routine

A named sub-routine, not a numbered Step: Step 3 runs it for the first turn and Step 4's capture precondition for every later one, once per turn. It never touches Section 5; design and evidence land in Section 9 and companion files only, and user-provided material is never silently dropped.

1. **Classify what this turn supplied.**
   - Design/HOW-content (architecture, directory layout, deployment topology, systemd units, runbook, rollout or landing order), pasted inline or given as a readable file path the user describes as design.
   - Evidence: files and photos offered as proof, screenshot or log.
   - A file path the user frames as neither: treat it as evidence and say so in its Section 9 line.
   - Nothing: return at once. The caller's branch for the same turn still runs; do not skip ahead to the next turn.

2. **Persist it**, one call per item. The first call creates `docs/dev/specs/<de-prefixed-id>/design/` and `evidence/`; the script takes the id from `resolve-spec-artifacts.py`, so never derive it by hand (the centralization lint flags that). A design pasted inline goes on stdin verbatim; `--from <path>` copies a design file's bytes as they are, with no summary and no transcoding, and `evidence --spec <spec_path> --from <path>` copies an evidence file:

   ```bash
   python3 "<HARNESS_ROOT>/scripts/steps/spec-capture.py" design --spec <spec_path> --turn <N> --slug "<short title>" <<'DESIGN_TEXT'
   <the user's HOW-text, verbatim>
   DESIGN_TEXT
   ```

   It prints `spec_dir_id=`, `bound_root=` and either `status=persisted` with `artifact=<project-relative path>`, or `status=failed` with `error=<why>`. It picks safe, collision-proof file names itself (it never overwrites an earlier artifact).

3. **Reference it in Section 9** through the writer: `spec-write.py append --spec <spec_path> --section 9.1` for a design, `--section 9.2` for evidence, with one short line (it replaces that subsection's `_Not yet populated._` placeholder on the first entry, and the other subsection's placeholder stays until its own first entry):

   ```
   - `<artifact>` — <one-line description>
   ```

   The persisted design is an additive mirror: design text that arrived inside the requirement also stays verbatim in Section 5. Leave the `<!-- consumers: [all] -->` line as the first line of each subsection, so the reference lines route to every selected view and the orchestrator.

4. **When nothing could be archived, say so in Section 9** and tell the user at once. A `status=failed` result gets the `(unpersisted design)` line (9.1) for a design or the `(unpersisted)` line (9.2) for evidence, carrying the original path and the error. A photo that arrives only as inline content gets the `(inline)` line (9.2): this harness hands a pasted image over as a base64 block with no path to copy from (use `--from` if a client ever exposes one), so durable archival needs a file path:

   ```
   - (unpersisted design) <original-path> — read/copy failed: <error>; not archived
   - (unpersisted) <original-path> — copy failed: <error>; not archived
   - (inline) <one-line description> — provided inline (no filesystem path in this harness); durable archival needs a file path
   ```

Each Section 9 line is a short verbatim monolith line that must appear in at least one view (it counts toward coverage); the design bodies and evidence binaries live outside the monolith and do not. Then return to the caller.

### Step 5: Natural-conclusion detection

**Strong signals** (go to Step 6): gratitude ("thanks", "thank you", "appreciate it"); satisfaction ("perfect", "got it", "i understand now", "that's helpful"); confirmation ("makes sense", "clear now", "all good"); topic closure ("that answers my question"); equivalents in other languages meaning thanks / understood / perfect / clear / let's go.

**Weak signals** (keep looping, do not finalize): a clarifying question, "interesting" (may want more), partial understanding.

Proceed to Step 6 only on a strong signal.

### Step 6: Finalize (exactly once)

1. **Pre-split checks**, one call:

   ```bash
   python3 "<HARNESS_ROOT>/scripts/steps/spec-finalize.py" prepare --spec <spec_path>
   ```

   It prints `spec_id=` (the de-prefixed id: use it as `<spec-id>` below), `monolith_lines=`, `references=`, a `dangling=<path>` line for each design or evidence path Section 9 lists with no file behind it, and `status=ok|dangling`. On `dangling` either halt finalize with a visible error naming each path, or append an `(unpersisted)` limitation line carrying the original path (the capture routine's failure form) and run `prepare` again. A dangling reference is never accepted silently.

2. **Spec subagent** (agent selection, view creation, checkpoints):
   ```
   Use Agent tool with:
   - subagent_type: "spec"
   - run_in_background: false
   - description: "Spec agent: split + checkpoints for <spec-id>"
   - prompt: "
     You are the spec subagent. Read and follow the instructions in <HARNESS_ROOT>/agents/spec.md EXACTLY.
     Spec id: <spec-id>
     Monolith: <spec_path>
     Monolith lines: <monolith_lines>
     Output folder: docs/dev/specs/<spec-id>/
     Project dir: <PROJECT_ROOT>
     <If codex_required = true, include the literal next line; otherwise omit it>
     codex_required: true
     Obligation block (instantiate per dispatch: dispatched_at is the UTC time captured just before this Agent call):
     <obligation v="1">
     {"task_id": "<spec-id>", "lane": null, "lane_set": null, "role": "spec", "pipeline": "spec", "profile": "singular", "dispatched_at": "<ISO-8601 UTC ending in Z>", "artifacts": [{"kind": "spec_views", "path": "docs/dev/specs/<spec-id>/views", "monolith": "docs/dev/specs/spec-<spec-id>.md"}]}
     </obligation>
     Panel reports: docs/dev/ba-panel-<spec-id>-A.md, -B.md, -C.md; round files: docs/dev/ba-panel-<spec-id>-r1.json and docs/dev/requirement-round-<spec-id>-r<n>.json; answers: Section 5's Requirement round blocks.
     Do the agent selection, the content extraction and the checkpoint generation, in that order; each owner decision of the rounds reaches the views that act on it.
     Return a JSON summary."
   ```

3. **QA validation of split quality** (after every spec subagent invocation):
   ```
   Use Agent tool with:
   - subagent_type: "qa"
   - run_in_background: false
   - description: "Validate spec split quality for <spec-id>"
   - prompt: "
     Validate the spec split at docs/dev/specs/<spec-id>/views/.
     Monolith: <spec_path>
     <If codex_required = true, include the literal next line; otherwise omit it>
     codex_required: true

     Check these criteria:
     1. ROLE MANDATE: If the spec defines role responsibilities (look for 'role split',
        'pipeline', agent-specific duties), verify each view's Role Mandate section
        accurately reflects the spec's definition. Flag any view where the agent's
        mandate is missing or contradicts the spec.
     2. AGENT SELECTION: Are the selected agents consistent with the spec's defined
        pipeline? Flag any agent that was included but isn't in the spec's pipeline,
        or any pipeline agent that was excluded.
     3. COVERAGE: coverage, pairwise overlap and per-view uniqueness (`spec-verify.py --strict`)
        were checked at the spec subagent's own stop, which returned a failing split to it;
        do not run the verifier again.
     4. CONTENT RELEVANCE: Spot-check 3 random content blocks in each view.
        Is the content relevant to that agent's role?
     5. FUNCTIONAL COMPLETENESS: For each agent view, verify it contains enough
        information for that agent to do its job WITHOUT reading the monolith.
        - ui-specialist: Has design briefs, visual language rules, motion specs?
        - ba: Has requirements, acceptance criteria, constraints?
        - dev: Has implementation constraints, file paths, deployment steps?
        - qa: Has acceptance criteria, verification procedures, test patterns?
        Flag any view that is missing critical content that would force the agent
        to fall back to the monolith (defeating the purpose of the split).
     6. SECTION 9 (DESIGN & EVIDENCE REFERENCES): If the monolith has a Section 9 at all,
        verify that EVERY non-blank, non-`---` line of it (the `## Section 9: Design & Evidence
        References` heading, the `<!-- WHO/WHAT ... -->` comments, the `### 9.1` / `### 9.2`
        headings, each `<!-- consumers: [all] -->` line, every reference line, AND the
        `_Not yet populated._` placeholders) appears verbatim in orchestrator.md and in the
        selected relevant views (`spec-verify.py`'s `is_skippable` skips only blank/`---`
        lines), and that companion design bodies and evidence binaries are NOT inlined into
        any view. Flag any Section 9 line that was dropped from the views: a coverage break
        the routing alone would miss.
     7. NO PHASING OR DEFERRAL: Fail the split if the spec or any view splits a requested
        outcome into sequential phases, deferred parts, a 'phase 2', an 'MVP first' or work for
        a later cycle: every requested outcome is delivered in one cycle. Parallel lanes inside
        one cycle are fine. Quote each offending line in `issues`.

     Return JSON: {verdict: pass|fail, issues: [...], summary: '...'}
     "
   ```

   **Split-QA loop** (no user prompt between rounds; the loop exits only on `pass`). Track `SPLIT_QA_ROUND` (starts at 1). On `fail`, announce `Split-QA round <N>: QA found <count> issue(s). Re-invoking spec subagent with feedback.`, then re-dispatch sub-step 2's template with the description "Spec agent re-split (round <N>) addressing QA feedback for <spec-id>", adding this text to its prompt after the obligation block, and run the QA again on the refreshed split:

   ```
   Your previous split was REJECTED by QA. Address each issue below with concrete
   corrections to the views and/or checkpoints. Do not argue -- investigate and fix.

   qa_feedback_from_previous_round:
   <JSON array of issues from the previous QA verdict>

   For each issue:
   - Identify which view(s) or checkpoint(s) the issue targets
   - Apply the specific correction QA requested
   - If the original extraction was wrong, RE-EXTRACT it verbatim from the monolith
   - If the agent selection was wrong, ADJUST the selected set

   Re-decide the agent selection if it was flagged, re-extract the affected views, and refresh the checkpoints.
   ```

4. **Mark the split complete**, after the split QA's last verdict:

   ```bash
   python3 "<HARNESS_ROOT>/scripts/steps/spec-finalize.py" complete --spec <spec_path>
   ```

   It writes `docs/dev/specs/<spec-id>/.split-complete`, then runs the spec-id centralization lint (`scripts/lint-spec-id-centralization.py`) over the `/dev*`, `/close` and `/spec` command files. `lint=flagged` only warns that a command re-derives the spec-id in prose instead of calling `resolve-spec-artifacts.py`; it never fails finalize. The split's own predicates (its manifest of this monolith, the monolith hash it records, the views the manifest references) were checked at the spec subagent's own stop by `hooks/subagentstop-artifact-contract-enforce.py` (ledger H-086), which returned a failing split to it; every `/dev*` consumer resolves the split, with this marker, through the same resolver.

### Step 7: Display result + workflow update

Before the final stdout response, create a compact temp update with `/spec-update --temp` (its `update.md` in a `mktemp -d` directory); do not write it into the repo unless the user explicitly asks. It is the hand-off to the `/dev` run that implements this spec: it references the spec path, split marker, views folder and checkpoints by path instead of duplicating their contents, lists every requested outcome as work for that one cycle (never as phases or deferred parts), and names the exact command to start it (`/dev` in this session, or `/dev --spec <absolute path>` in another). Do not use continuation-spec mode: `/spec` already produced the spec.

```
Spec created: <absolute path>
Split marker: docs/dev/specs/<spec-id>/.split-complete
Output folder: docs/dev/specs/<spec-id>/
Checkpoints:  .claude/specs/<spec-id>/cp-state-*.json
Update:      <temp update path for the /dev run that implements this spec>

Sections populated:
- Section 5 (User's Acceptance Criterion): populated (N requirements accumulated)
- Section 1 (Before): <populated from Explore findings, or empty>

Usage:
  /dev                                        ← in this session: uses this spec (the session's last spec write)
  /dev --spec <absolute path>                 ← in any session
  /dev-command                                ← in this session: uses this spec
  /dev-command --spec <absolute path>         ← in any session
  /dev-overnight <end-time>                   ← in this session: uses this spec
  /dev-overnight <end-time> --spec <absolute path> ← in any session
```

---

## Important Rules

- **Write only the spec, through the writer.** The one existing file `/spec` modifies is the spec being created, and only through `<HARNESS_ROOT>/scripts/spec-write.py`. The exceptions: the capture routine creates files under `docs/dev/specs/<de-prefixed-id>/design/` and `evidence/`, and Step 6 writes `.split-complete`. The spec subagent creates the output folder (`views/`, `manifest.json`) at finalize and decides which agents get views; a legacy spec with no output folder stays valid, since `/dev*` falls back to the monolith.
- **Use absolute paths** in all output messages.
- **Section 5 is verbatim: invent no sub-structure.** The only structure `/spec` may add under Section 5 is Step 4's `### 5.N: <title>` header, one per follow-up turn. Never decompose the user's paragraph into invented `#### A.` / `#### B.` or `5.X.A`-style headings, checklist bullets or parallel should/should-not ladders; downstream agents (BA, dev, QA) decompose it themselves when they plan the work. This bans agent-invented decomposition only, never the design the user provided: architecture, directory layout, deployment topology, systemd, runbook and rollout order are persisted byte for byte by the capture routine and referenced from Section 9, never dropped, summarized or relocated.
