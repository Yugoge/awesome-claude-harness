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
   - All other sections → `_Not yet populated._` (Section 9's two subsections each
     keep their `<!-- consumers: [all] -->` line + `_Not yet populated._` placeholder
     until their own first entry — see the Design & Evidence Capture Routine below)

4. Write the spec.

   **Design & Evidence Capture (early capture)** (un-numbered — part of writing the first
   spec, not a separate Step): Run the **Design & Evidence Capture Routine** (defined below,
   after Step 4) for the FIRST turn's material immediately after the spec is written, BEFORE
   acknowledging in sub-step 6. The routine's sub-step 1 self-no-ops if the first turn
   carries no design/evidence, so this invocation is safe to run unconditionally. Early
   capture (not finalize) is mandatory: finalize is too late and material would be lost (M2).
   This is the SOLE first-turn capture point; every LATER turn is captured exactly once by
   the Step 4 capture precondition (no double-capture).

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

After Step 3, wait for the next user message. For EVERY user turn, FIRST run the
capture precondition, THEN branch:

**Capture precondition (runs first, every turn — M2)**: BEFORE evaluating any branch
below, **run the Design & Evidence Capture Routine for THIS turn's material**.
The routine's sub-step 1 self-no-ops when the turn carries no design/evidence, so it is safe to
invoke unconditionally at the top of every turn. This single pre-branch invocation is what
guarantees M2's "capture on every follow-up turn" structurally — no branch outcome below
(another-requirement, strong-signal/finalize, mid-loop-vague, or a design/evidence-only
turn) can proceed or finalize without first capturing any material present in the same
turn. Do NOT also call the routine inside an individual branch — that would double-capture the
same turn's material.

After the capture precondition has run, branch on the turn's requirement/closure shape:

- **Strong natural-conclusion signal** (Step 5 list) → the capture precondition has already
  persisted any design/evidence carried by this closing turn (so a turn like "here is the
  runbook screenshot, thanks" is captured before finalize, never dropped). Now proceed to
  Step 6 (Finalize).
- **Another requirement** → append to `spec_path` under Section 5 as a new sub-section:
  ```
  ### 5.N: <brief title extracted from the message>
  <verbatim requirement text>
  ```
  `N` increments from 2 (the first requirement populates Section 5; subsequent requirements become 5.2, 5.3, …). The capture precondition already ran the Design & Evidence Capture Routine for this turn's design/evidence; do NOT run it again here. Then loop back to wait.
- **Design/evidence-only follow-up** (the turn supplies design/HOW-content or evidence but
  carries no new requirement text and is not a conclusion signal) → the capture precondition
  has already persisted that material via the Design & Evidence Capture Routine. Because this
  turn carries NO new requirement text, do NOT append a `### 5.N` block and do NOT touch
  Section 5 at all — the design/evidence is already persisted to Section 9 + companion files,
  so there is nothing left to record. Simply loop back to wait. This turn shape is now fully
  captured — it can never fall through uncaptured.
- **Exploration findings arrive** → integrate into Section 1 (Before) silently. If a finding contradicts the user's description, surface one targeted question — for example, "I looked at X and found Y — does that match?" — then loop back. Never gate the loop on exploration.
- **Mid-loop vague input** → apply Step 2 logic (max 3 rounds) to that single message before appending, then loop back. (The capture precondition already handled any design/evidence in the triggering turn.) Each clarification RESPONSE collected by Step 2 is itself a fresh Step 4 user turn: run the capture precondition (the Design & Evidence Capture Routine) on it FIRST, before re-evaluating Step 2 / appending — do NOT process a clarification answer in a bypass path that skips capture, or design/evidence supplied in a clarification reply would be dropped.

Maintain `turn_count` internally (not user-visible), increment after each user response. No hard turn cap — termination is signal-driven.

### Design & Evidence Capture Routine

(This is a named sub-routine, NOT a numbered Step — the integer Step 1→7 sequence runs
contiguous and un-lettered. It is invoked from Step 3's **Design & Evidence Capture (early
capture)** paragraph and from the Step 4 capture precondition.)

This routine is invoked UNCONDITIONALLY in Step 3's early-capture paragraph for the first turn,
and unconditionally as the Step 4 **capture precondition** that fires BEFORE branching on EVERY
follow-up turn — including the design/evidence-only turn shape and the finalizing turn that
also carries material (M2). It performs work only if that turn carries design/evidence;
sub-step 1 self-no-ops otherwise. It is invoked at exactly ONE point per turn (Step 3's
early-capture paragraph for the first turn, the Step 4 capture precondition for every later
turn), so each turn's material is captured exactly once — no double-capture. It NEVER touches
Section 5 — design and evidence land in Section 9 + companion files only (M8). User-provided
design and evidence are first-class material and MUST NOT be silently dropped (M3-M5, M12).

1. **Detect material in this turn.** Classify what the user supplied this turn into:
   - **Design/HOW-content**: architecture, directory layout, deployment topology,
     systemd units, runbook, rollout/landing order — whether pasted inline as text OR
     supplied as a readable file path the user describes as design/HOW/runbook/systemd/
     rollout/layout (M14).
   - **Evidence**: files and photos/screenshots offered as proof/screenshot/log/photo.
   - **Ambiguous path input** (a file path the user neither clearly frames as design nor
     as evidence) → default to **evidence/** with visible Section-9 wording noting the
     ambiguous classification (M14).
   - If neither is present this turn, do nothing and return control to the caller.
     When invoked from the Step 4 capture precondition (or Step 3's early-capture paragraph),
     this is a no-op that hands control straight back so the SAME turn's branch evaluation
     (append / finalize / clarify) still runs — it does NOT skip to waiting for the next turn.

2. **Resolve the de-prefixed id and bind the per-id folder (first material only).** Obtain
   the per-id folder id by consuming the resolver's `candidates[0]` (the de-prefixed stem,
   exactly one leading `spec-` stripped). Do NOT re-derive the id inline by hand from the
   path — the centralization lint (Step 6 sub-step 6) flags inline derivation:

   ```bash
   RESOLVED_JSON=$(/root/.claude/scripts/resolve-spec-artifacts.py \
       --spec-path "$spec_path" --project-dir "$CLAUDE_PROJECT_DIR")
   SPEC_DIR_ID=$(jq -r '.candidates[0]' <<<"$RESOLVED_JSON")   # de-prefixed id
   BOUND_ROOT="$CLAUDE_PROJECT_DIR/docs/dev/specs/$SPEC_DIR_ID"
   ```

   On the FIRST arriving design/evidence material, create the bound artifact root and its
   two subfolders, and write the binding marker (M2):

   ```bash
   mkdir -p "$BOUND_ROOT/design" "$BOUND_ROOT/evidence"
   # .spec-binding.json ties this early folder to THIS spec-id so the splitter's later
   # views/ creation does not merge into a stale/foreign folder. It is NOT one of the
   # reserved artifact names (views/ / manifest.json / .split-complete), so the resolver
   # still classifies the folder ABSENT (legacy-monolith fallback intact) — verified.
   printf '{"spec_id":"%s","monolith_path":"%s","bound_at":"%s"}\n' \
       "$SPEC_DIR_ID" "$spec_path" "$(date -Iseconds)" > "$BOUND_ROOT/.spec-binding.json"
   ```

   Do NOT create `views/`, `manifest.json`, or `.split-complete` here — those remain
   spec-subagent-owned at finalize (M9).

3. **Safe target naming (M13).** Compute deterministic, safe target names. Reject any name
   containing `..`, an absolute path, or control characters — never write outside
   `$BOUND_ROOT/design/` or `$BOUND_ROOT/evidence/`, and never overwrite a prior artifact:
   - Design: `design/turn-<N>-<slug>.md` where `<N>` is the current turn number and
     `<slug>` is a sanitized short title.
   - Evidence: the sanitized basename of the source; on a name collision, append a short
     content hash (e.g. `photo.png` → `photo-<8hex>.png`) so no prior artifact is
     overwritten.

4. **Persist design (M3 — additive, never relocating) — two branches like evidence.**
   - **Design pasted inline as HOW-text** → write the user's HOW-content VERBATIM to
     `$BOUND_ROOT/design/turn-<N>-<slug>.md`.
   - **Design supplied as a readable file path** (runbook/systemd/layout document the user
     framed as design — M14) → read/copy the SOURCE bytes VERBATIM into
     `$BOUND_ROOT/design/turn-<N>-<slug>.md`. Do NOT summarize or transcode; persist the
     file content as-is.
   - **Design path that fails to read** (missing / unreadable / outside accessible paths)
     → do NOT drop it silently (fail-visible, same contract as evidence M12): append an
     "unpersisted design" limitation line under Section 9.1 carrying the original path +
     the error, and tell the user immediately:
     ```
     - (unpersisted design) <original-path> — read/copy failed: <error>; not archived
     ```

   The persisted design file is an ADDITIVE mirror: if the design text arrived as part of
   the user's requirement it STAYS verbatim in Section 5; the companion design doc + the
   Section-9 reference are ADDED, never used to strip, rewrite, summarize, or relocate any
   Section-5 text. On a successful persist, append a short project-root-relative reference
   line under Section 9.1 (replacing the `_Not yet populated._` placeholder on the FIRST
   design entry; leaving Section 9.2's placeholder untouched until its own first entry — M1):

   ```
   - `docs/dev/specs/<de-prefixed-id>/design/turn-<N>-<slug>.md` — <one-line description>
   ```

   Keep the `<!-- consumers: [all] -->` line as the first line of Section 9.1 so every
   reference line under it routes to all selected views + orchestrator (S1).

5. **Persist evidence (M4 / M5 — two branches).**
   - **File/photo WITH a usable readable path** → copy it into
     `$BOUND_ROOT/evidence/<safe-name>` and append a reference line under Section 9.2:
     ```
     - `docs/dev/specs/<de-prefixed-id>/evidence/<safe-name>` — <one-line description>
     ```
   - **Photo arriving ONLY as inline/pathless content** → in THIS harness, a pasted image
     currently arrives as a base64 content block with no filesystem path the orchestrator
     can `Read` (current-harness observation, not an eternal absolute — if a future client
     exposes a usable path for the pasted image, take the by-path copy branch above
     instead). Because nothing can be copied from a non-existent path, record a VISIBLE
     evidence reference under Section 9.2 noting the item was provided inline and could not
     be archived to a path, and tell the user durable archival needs a file path. The
     material is NEVER silently dropped (M5):
     ```
     - (inline) <one-line description> — provided inline (no filesystem path in this harness); durable archival needs a file path
     ```

6. **Fail-visible evidence-copy errors (M12).** If a file-by-path copy fails (path missing,
   unreadable, or outside accessible paths), do NOT drop it silently. Either the copy
   succeeds and the copied path is referenced (sub-step 5), OR append an "unpersisted
   evidence" limitation line under Section 9.2 carrying the original path + the error, and
   tell the user immediately:

   ```
   - (unpersisted) <original-path> — copy failed: <error>; not archived
   ```

7. Each Section-9 reference line is a SHORT verbatim monolith line (it enters the coverage
   denominator and MUST appear verbatim in ≥1 view — see Step 6 and the splitter). The
   companion design body and evidence binaries live OUTSIDE the monolith and are NOT in the
   coverage denominator. Then return control to the caller: when invoked from the Step 4
   capture precondition, continue branch evaluation for the SAME turn (append `### 5.N` /
   finalize / clarify / loop back for a design/evidence-only turn); do NOT skip ahead to
   waiting for the next user turn.

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

0. **Section-9 dangling-reference guard (PRE-split, M11)**: Before counting lines or
   invoking the splitter, parse every `docs/dev/specs/<de-prefixed-id>/design/...` and
   `docs/dev/specs/<de-prefixed-id>/evidence/...` reference path listed under Section 9
   and assert each exists on disk under the bound per-id folder. `(inline)`,
   `(unpersisted)`, and `(unpersisted design)` limitation lines are intentionally NOT real
   paths — BEFORE any path-regex extraction, skip any Section-9 line matching the sentinel
   pattern `^\s*-\s*\((inline|unpersisted design|unpersisted)\)\s` (the markdown bullet
   `- (` plus one of the three sentinel tokens followed by whitespace, exactly as emitted in
   the Design & Evidence Capture Routine's sub-steps 4/5/6 — note the trailing `\s`, NOT a word boundary `\b`, since a `)`
   immediately followed by a space is not a word boundary and `\b` would fail to match these
   lines). These are already visible records, not dangling file references, so they must
   never be passed to the path extractor. If any real reference path is
   missing, finalize HALTS with a visible error naming the dangling path, OR the
   orchestrator converts that reference into a visible `(unpersisted)` limitation line
   carrying the original path — the dangling reference is NEVER silently accepted. This
   keeps the deferred manifest-tracking change (a Won't-Have) safe.

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
     6. SECTION 9 (DESIGN & EVIDENCE REFERENCES): If the monolith has a Section 9 at all,
        verify that EVERY non-blank, non-`---` line of Section 9 — the
        `## Section 9: Design & Evidence References` heading, every explanatory
        `<!-- WHO/WHAT ... -->` comment, the `### 9.1` / `### 9.2` subsection headings,
        each `<!-- consumers: [all] -->` annotation line, every design/evidence reference
        line, AND the `_Not yet populated._` placeholders — appears verbatim in
        orchestrator.md and in the selected relevant views (each of those lines counts
        toward coverage because `spec-verify.py`'s `is_skippable` skips only blank/`---`);
        that companion design body files and evidence binaries are NOT inlined into any
        view; and that each referenced design/ or evidence/ artifact path exists under
        docs/dev/specs/<spec-id>/. Flag any Section-9 line — heading, comment, subheading,
        annotation, or reference — that was dropped from the views (a coverage break the
        routing alone would miss).

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
- **Do not modify any existing files** except the spec file being created — with ONE
  scoped carve-out for design/evidence capture (M9): at design/evidence capture time
  (the Design & Evidence Capture Routine) `/spec` MAY create/write ONLY
  `docs/dev/specs/<de-prefixed-id>/.spec-binding.json`,
  `docs/dev/specs/<de-prefixed-id>/design/*`, and
  `docs/dev/specs/<de-prefixed-id>/evidence/*`. It MUST NOT write `views/`,
  `manifest.json`, or `.split-complete` — those remain spec-subagent-owned, created at
  finalize. No other existing file may be modified.
- **Create the output directory** (`docs/dev/specs/`) if it does not exist.
- **Use absolute paths** in all output messages.
- **Spec Creation Mode is the only mode.** It acts immediately on whatever the user provides, accumulates multiple requirements into one file per session, and finalizes only on a natural-conclusion strong signal.
- **Section 5 verbatim — DO NOT invent nested sub-section structure.** Section 5 holds the user's requirement text verbatim. The only structure the /spec orchestrator may ADD beneath Section 5 is the `### 5.N: <title>` accumulation header defined in Step 4 (one per follow-up turn); any other bullets, headings, or sub-headings must come verbatim from the user, not be invented. DO NOT decompose the user's natural-language paragraph into invented `#### A.`, `#### B.`, `#### C.` (or any `5.X.A`, `5.X.B`-style) sub-headings, machine-voice checklist bullets, or parallel "should/should-not" AC ladders below a `§5.N` block. This prohibition governs both Step 3 (first-write of Section 5) and Step 4 (multi-turn append of `### 5.N`). If the user's paragraph contains multiple ideas, leave them as one paragraph; downstream agents (BA, dev, QA) will decompose during their own phases — not the /spec orchestrator.
  - **Scope of this rule (M6 — agent-INVENTED decomposition only).** The prohibition above bans the ORCHESTRATOR from INVENTING or decomposing architecture/structure inside Section 5 — that decomposition is downstream's job. It does NOT, and must NEVER, justify discarding design the USER actually provided. User-provided design (architecture, directory layout, deployment topology, systemd, runbook, rollout/landing order) is first-class material: it MUST be persisted BYTE-FOR-BYTE to the companion design doc under `docs/dev/specs/<de-prefixed-id>/design/` and REFERENCED from Section 9 (per the Design & Evidence Capture Routine / M3) — never dropped, never used to summarize or relocate Section-5 text. "Design is downstream's job" applies ONLY to agent-invented decomposition; it is not grounds to drop user-supplied design.
- **Output folder is created by the spec subagent** during Phase 0 (the `views/` /
  `manifest.json` / `.split-complete` finalize artifacts). The subagent decides which
  agents get views based on spec content. EXCEPTION (M9): the `design/`, `evidence/`,
  and `.spec-binding.json` early-capture artifacts may be created by `/spec` itself at
  design/evidence capture time (the Design & Evidence Capture Routine). Legacy specs lacking an output folder remain
  valid — `/dev*` falls back gracefully.
- **Todo script**: `/root/.claude/scripts/todo/spec.py` (symlinked to `/dev/shm/dev-workspace/dot-claude/scripts/todo/spec.py` — same inode) exposes the 7-step Spec Creation Mode todo list with `blocking_count = 3` (Steps 1-3 must complete before Claude can stop; Steps 4-7 are session-duration).
- **Workflow update**: Step 7 emits a temp update for the next phase using
  `/spec-update --temp`. It must be compact, reference existing artifacts by path,
  and suggest the exact next command (`/dev` auto-detect or `/dev --spec
  <path>`).
