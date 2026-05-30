---
description: Create spec files for any dev workflow (/dev, /dev-overnight, or standalone reference). Pass --codex to enable adversarial codex consultation on each spec-subagent / QA dispatch; default is self-review only.
argument-hint: "[--codex] [<requirement>]"
disable-model-invocation: true
---

# /spec: General-Purpose Spec Manager

You manage spec files. `$ARGUMENTS` may be empty or hold the user's first requirement — either way, act immediately.

---

## Spec Creation Mode

**Philosophy**: Act immediately on whatever the user provides. Ask a clarification ONLY when the input is genuinely impossible to turn into a Section 5 skeleton. After writing the first spec, stay in a multi-turn loop and append any follow-up requirements to the SAME file. Exit on natural-conclusion strong signals only.

### Step 1: Parse $ARGUMENTS

**Parse `--codex`**: If `$ARGUMENTS` contains the literal token `--codex` (in any position), strip it from the requirement text and set `codex_required = true`. Otherwise set `codex_required = false` (default). When `codex_required = true`, every spec-subagent / QA dispatch prompt below MUST include the literal line `codex_required: true` so the subagent's opt-in codex consultation block (`agents/<role>.md` § Codex adversarial consultation) activates. When `codex_required = false`, do NOT include that line — subagents skip codex consultation and emit `codex_consult: { invoked: false, status: "not_requested" }` in their output.

After stripping `--codex`, branch on the remaining requirement text:

- **Non-empty non-flag text**: treat as the first requirement. Skip to Step 3.
- **Empty**: ask once, briefly and naturally — one sentence, first-person, match the user's energy and language (en or zh). Do not use a fixed phrase; vary wording. Then wait for the response and use it as the first requirement.

Do NOT ask multiple framing questions. No "deep-dive", no "acceptance criteria" interview, no preview-and-confirm gate.

### Step 2: Clarify if truly unclear (max 3 rounds)

Adapted from `/dev` BA clarification pattern (dev.md Step 4 loop, max 3 rounds, default is to proceed).

**Trigger this step ONLY when** Section 5 cannot be sketched at all — no topic, no feature, no issue identifiable, no actionable phrase. Examples of genuinely unclear input: "help", "fix it", "something's wrong", bare emoji.

**If not triggered**: skip to Step 3.

**If triggered**:
1. Ask ONE targeted question at a time. Wait for user response.
2. Re-evaluate: can Section 5 now be sketched? If yes, proceed to Step 3.
3. Repeat max 3 rounds. After the 3rd answer, proceed regardless — write the spec with whatever Section 5 content you can extract plus an `_Assumption_` note.

### Step 3: Write first spec + dispatch background Explore

1. Read the template at `~/.claude/templates/overnight-spec.md`. If missing, report error and stop.

2. Generate the output path:
   ```
   ${CLAUDE_PROJECT_DIR:-$(pwd)}/docs/dev/specs/spec-<YYYYMMDD-HHMMSS>.md
   ```
   Specs always land in the parent project directory, never inside an overnight worktree. Create `docs/dev/specs/` if it does not exist. Store the resulting path as `spec_path` for reuse in Step 4. A fresh `/spec` invocation in a new session creates a new timestamped file; within-session follow-ups append to the same file.

3. Populate the template:
   - `<issue_description>` → short summary of the user's requirement
   - `<ISO-8601>` → current timestamp
   - Section 5 → user's requirement verbatim
   - All other sections → `_Not yet populated._`

4. Write the spec.

5. **Background exploration (non-blocking)**: when the user mentions specific files, components, features, or technical terms, immediately dispatch an Explore agent in the background:
   ```
   Agent(
     subagent_type="Explore",
     run_in_background=true,
     description="Spec background exploration",
     prompt="Find and summarize <what the user mentioned>. Report: file paths, current behavior, relevant code snippets. Thoroughness: medium."
   )
   ```
   Findings integrate when they arrive (see Step 4). Discrepancies may surface as a single targeted question but do NOT gate the loop.

6. Acknowledge that the spec was written. Include the full `<spec_path>` so the user knows where it landed. Convey that more requirements can be added whenever they are ready. Keep it brief and natural — first-person, match the user's language and energy, no fixed template.

**Do NOT** run split / checkpoints / QA yet. Finalize happens exactly once in Step 6.

### Step 4: Multi-turn accumulation loop

Copied from `ask.md` Step 6 (multi-turn dialogue loop architecture). One `/spec` invocation spans multiple user messages; each message lands in the SAME `spec_path`.

After Step 3, wait for the next user message and branch:

- **Strong natural-conclusion signal** (Step 5 list) → proceed to Step 6 (Finalize).
- **Another requirement** → append to `spec_path` under Section 5 as a new sub-section:
  ```
  ### 5.N: <brief title extracted from the message>
  <verbatim requirement text>
  ```
  `N` increments from 2 (the first requirement populates Section 5; subsequent requirements become 5.2, 5.3, …). Then loop back to wait.
- **Exploration findings arrive** → integrate into Section 1 (Before) silently. If a finding contradicts the user's description, surface one targeted question — for example, "I looked at X and found Y — does that match?" — then loop back. Never gate the loop on exploration.
- **Mid-loop vague input** → apply Step 2 logic (max 3 rounds) to that single message before appending, then loop back.

Maintain `turn_count` internally (not user-visible), increment after each user response. No hard turn cap — termination is signal-driven.

### Step 5: Natural-conclusion detection

Copied verbatim from `ask.md` Step 8 (lines 495-510).

**Strong signals** (trigger finalize):
- Gratitude: "thanks", "thank you", "appreciate it"
- Satisfaction: "perfect", "got it", "i understand now", "that's helpful"
- Confirmation: "makes sense", "clear now", "all good"
- Topic closure: "that answers my question"
- Equivalents in other languages meaning thanks / understood / perfect / clear / let's go

**Weak signals** (continue loop, do NOT finalize):
- User asks a clarifying question
- User says "interesting" (might want more)
- User provides partial understanding

Only proceed to Step 6 when a STRONG signal fires.

### Step 6: Finalize (exactly once)

1. **Count monolith lines**: `MONOLITH_LINES=$(wc -l < <spec_path>)`

2. **Invoke spec subagent for agent selection + view creation + checkpoints**:
   ```
   Use Agent tool with:
   - description: "Spec agent: split + checkpoints for <spec-id>"
   - prompt: "
     You are the spec subagent. Read and follow the instructions in /dev/shm/dev-workspace/dot-claude/agents/spec.md EXACTLY.
     Spec id: <spec-id>
     Monolith: <spec_path>
     Monolith lines: <MONOLITH_LINES>
     Output folder: docs/dev/specs/<spec-id>/
     Project dir: <$CLAUDE_PROJECT_DIR>
     <If codex_required = true, include the literal next line; otherwise omit it>
     codex_required: true
     Execute Phase 0 (read spec, decide relevant agents).
     Then Phase 1 (intelligent extraction if monolith > 200 lines).
     Then Phase 2 (checkpoint generation).
     Return a JSON summary."
   ```

3. **QA validation of split quality**:
   ```
   Use Agent tool with:
   - subagent_type: "qa"
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
     3. COVERAGE: If `/root/.claude/scripts/spec-verify/spec-verify.py` exists, run `source ~/.claude/venv/bin/activate && python3 /root/.claude/scripts/spec-verify/spec-verify.py --monolith <spec_path> --views-dir docs/dev/specs/<spec-id>/views/`. If the script is absent, skip and note "spec-verify.py not found — manual coverage check required".
        Report the result.
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

     Return JSON: {verdict: pass|fail, issues: [...], summary: '...'}
     "
   ```

   **Split-QA auto-iteration loop** (mirrors `/dev` Step 7; max 3 rounds, no user prompt between rounds):

   **Iteration guard**: Maximum 3 split-QA rounds to prevent infinite loops.

   **Current split-QA round**: Track internally as `SPLIT_QA_ROUND` (starts at 1).

   **If QA verdict == `pass`** (at any round): exit loop, proceed to sub-step 4 (mark split complete).

   **If QA verdict == `fail` and `SPLIT_QA_ROUND` < 3**:

   Announce: `Split-QA round <N>/3: QA found <count> issue(s). Re-invoking spec subagent with feedback.`

   Re-invoke the spec subagent with the same Agent pattern as sub-step 2, appending the QA `issues` array verbatim under the label `qa_feedback_from_previous_round` in the prompt:

   ```
   Use Agent tool with:
   - description: "Spec agent re-split (round <N>) addressing QA feedback for <spec-id>"
   - prompt: "
     You are the spec subagent. Read and follow the instructions in /dev/shm/dev-workspace/dot-claude/agents/spec.md EXACTLY.
     Spec id: <spec-id>
     Monolith: <spec_path>
     Monolith lines: <MONOLITH_LINES>
     Output folder: docs/dev/specs/<spec-id>/
     Project dir: <$CLAUDE_PROJECT_DIR>
     <If codex_required = true, include the literal next line; otherwise omit it>
     codex_required: true

     Your previous split was REJECTED by QA. Address each issue below with concrete
     corrections to the views and/or checkpoints. Do not argue -- investigate and fix.

     qa_feedback_from_previous_round:
     <JSON array of issues from the previous QA verdict>

     For each issue:
     - Identify which view(s) or checkpoint(s) the issue targets
     - Apply the specific correction QA requested
     - If the original extraction was wrong, RE-EXTRACT it verbatim from the monolith
     - If the agent selection was wrong, ADJUST the selected set

     Re-run Phase 0 (re-decide agents if selection was flagged),
     Phase 1 (re-extract affected views), Phase 2 (refresh checkpoints).
     Return a JSON summary."
   ```

   Increment `SPLIT_QA_ROUND` and re-run the QA validation (sub-step 3) against the refreshed split.

   **If QA verdict == `fail` and `SPLIT_QA_ROUND` == 3** (all rounds exhausted — auto-proceed, do NOT prompt the user):

   1. Print to stdout (non-blocking): `Spec split QA: 3 rounds exhausted. Proceeding with best-effort split. Unresolved issues: <list of QA issues>.`
   2. Write the round-3 `issues` array verbatim to `docs/dev/specs/<spec-id>/split-qa-unresolved.json`.
   3. Continue to sub-step 4 (mark split complete); the caveat line is appended there.
   4. Include the caveat in the Step 7 displayed output so reviewers are notified.

   **Rule**: Every spec subagent invocation MUST be followed by QA validation. The loop exits only on `pass` or on round-3 exhaustion.

4. **Mark split as complete**: Write `"split-complete: $(date -Iseconds)"` to `docs/dev/specs/<spec-id>/.split-complete`.

   If the loop exited via round-3 exhaustion (sub-step 3), also append `"warning: unresolved split-QA issues (<N>); see split-qa-unresolved.json"` so reviewers see the warning inline with the marker.

5. **guard — Finalize-time consumer-path assertion (MANDATORY, blocks on failure)**: After the split marker is written, run the SAME resolver that every `/dev*` consumer uses against the just-written monolith, and assert it resolves to a PRESENT-AND-VALID de-prefixed split at the EXACT path `/dev` will read. This catches a producer that accidentally wrote a prefixed split dir, a manifest whose `monolith_path` does not point back at this monolith, or a missing/stale marker — at creation time, not at `/dev` time:

   ```bash
   RESOLVED_JSON=$(/root/.claude/scripts/resolve-spec-artifacts.py \
       --spec-path "$spec_path" --project-dir "$CLAUDE_PROJECT_DIR") || {
     echo "FINALIZE BLOCKED: resolver reports the split is present-but-invalid / mismatched for $spec_path." >&2
     echo "The split /dev would consume does not validate. Fix the split before finalizing." >&2
     exit 1; }
   VIEWS_AVAILABLE=$(jq -r .views_available <<<"$RESOLVED_JSON")
   ARTIFACT_ID=$(jq -r .artifact_id <<<"$RESOLVED_JSON")
   # CONSUME the resolver's own de-prefixed id (candidates[0]) — do NOT re-derive it
   # inline from the path. candidates[0] is the resolver's first candidate, which is
   # always the de-prefixed stem (exactly one leading "spec-" stripped). Re-deriving
   # the id by hand via path/suffix/prefix parameter-expansion is the precise
   # prose-drift M4/M9 forbid (and the M9 lint now flags it).
   EXPECT_ID=$(jq -r '.candidates[0]' <<<"$RESOLVED_JSON")
   if [ "$VIEWS_AVAILABLE" != "true" ] || [ "$ARTIFACT_ID" != "$EXPECT_ID" ]; then
     echo "FINALIZE BLOCKED: resolver did not return views_available=true at the de-prefixed id '$EXPECT_ID'" >&2
     echo "(got views_available=$VIEWS_AVAILABLE artifact_id=$ARTIFACT_ID). The producer must write the split DE-prefixed so /dev can consume it." >&2
     exit 1
   fi
   echo "Finalize guard OK: /dev will resolve $spec_path -> artifact_id=$ARTIFACT_ID, views_available=true." >&2
   ```

6. **Centralization lint (advisory — surfaces inline spec-id re-derivation regressions)**: run `scripts/lint-spec-id-centralization.py` over the `/dev*`/`/spec` command files that consume the resolver. This is NON-BLOCKING here (a WARNING only) — finalize must not hard-fail on an unrelated command-file edit. The authoritative hard gate for this lint belongs at the `.claude`-repo commit boundary (a pre-commit check on staged `commands/*.md` / `scripts/*.sh`), the only place command-file edits actually land; this advisory is a safety-net that makes a regression visible at every finalize.

   ```bash
   /root/.claude/scripts/lint-spec-id-centralization.py --paths \
       /root/.claude/commands/dev.md /root/.claude/commands/dev-command.md \
       /root/.claude/commands/dev-overnight.md /root/.claude/commands/close.md \
       /root/.claude/commands/spec.md \
     || echo "WARNING: centralization lint flagged inline spec-id derivation in a consumer command file — a /dev*/spec command re-derives the spec-id in prose instead of calling resolve-spec-artifacts.py. Fix before the next commit that touches those files." >&2
   ```

### Step 7: Display result + workflow update

Before the final stdout response, create a compact temp update using
`/spec-update --temp`. Default to `mktemp -t update-XXXXXX.md`; do not write this
update into the repo unless the user explicitly asks. The update focuses on
the next `/dev` session and references the spec path, split marker, views
folder, checkpoints, and unresolved split-QA file by path instead of duplicating
their contents. Do NOT use continuation-spec mode here because `/spec` already
produced the spec.

```
Spec created: <absolute path>
Split marker: docs/dev/specs/<spec-id>/.split-complete
Output folder: docs/dev/specs/<spec-id>/
Checkpoints:  .claude/specs/<spec-id>/cp-state-*.json
Update:      <temp update path for the next /dev session>

Sections populated:
- Section 5 (User's Acceptance Criterion): populated (N requirements accumulated)
- Section 1 (Before): <populated from Explore findings, or empty>

<If split-QA exhausted 3 rounds, include:>
⚠ Split-QA: 3 rounds exhausted with unresolved issues — see docs/dev/specs/<spec-id>/split-qa-unresolved.json

Usage:
  /dev                                   ← auto-detects this spec
  /dev --spec <path>                     ← explicit path
  /dev-command                           ← auto-detects this spec
  /dev-command --spec <path>             ← explicit path
  /dev-overnight <end-time>              ← auto-detects this spec
  /dev-overnight <end-time> --spec <path> ← explicit path
```

---

## Important Rules

- **Read the template at runtime** from `~/.claude/templates/overnight-spec.md`. Never hardcode template content.
- **Preserve template structure exactly** — only replace designated placeholders and `_Not yet populated._` markers.
- **Do not modify any existing files** except the spec file being created.
- **Create the output directory** (`docs/dev/specs/`) if it does not exist.
- **Use absolute paths** in all output messages.
- **Spec Creation Mode is the only mode.** It acts immediately on whatever the user provides, accumulates multiple requirements into one file per session, and finalizes only on a natural-conclusion strong signal.
- **Section 5 verbatim — DO NOT invent nested sub-section structure.** Section 5 holds the user's requirement text verbatim. The only structure the /spec orchestrator may ADD beneath Section 5 is the `### 5.N: <title>` accumulation header defined in Step 4 (one per follow-up turn); any other bullets, headings, or sub-headings must come verbatim from the user, not be invented. DO NOT decompose the user's natural-language paragraph into invented `#### A.`, `#### B.`, `#### C.` (or any `5.X.A`, `5.X.B`-style) sub-headings, machine-voice checklist bullets, or parallel "should/should-not" AC ladders below a `§5.N` block. This prohibition governs both Step 3 (first-write of Section 5) and Step 4 (multi-turn append of `### 5.N`). If the user's paragraph contains multiple ideas, leave them as one paragraph; downstream agents (BA, dev, QA) will decompose during their own phases — not the /spec orchestrator.
- **Output folder is created by the spec subagent** during Phase 0. The subagent decides which agents get views based on spec content. Legacy specs lacking an output folder remain valid — `/dev*` falls back gracefully.
- **Todo script**: `/root/.claude/scripts/todo/spec.py` (symlinked to `/dev/shm/dev-workspace/dot-claude/scripts/todo/spec.py` — same inode) exposes the 7-step Spec Creation Mode todo list with `blocking_count = 3` (Steps 1-3 must complete before Claude can stop; Steps 4-7 are session-duration).
- **Workflow update**: Step 7 emits a temp update for the next phase using
  `/spec-update --temp`. It must be compact, reference existing artifacts by path,
  and suggest the exact next command (`/dev` auto-detect or `/dev --spec
  <path>`).
