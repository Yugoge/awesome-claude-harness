# Overnight Spec Integration

Read this file when your prompt names an `Overnight spec file:` (PM: also when a RETRO prompt lists spec
paths): you are in the spec-driven overnight workflow, and the section for your role below applies. The spec is a living document with 8 sections that
tracks an issue's full lifecycle across cycles. Nobody but its writer changes it: a `/spec` spec has one
writer, `scripts/spec-write.py` (run by `/spec`, `/spec-update` and `/commit` Step 8's continuation, which
read your report), and a pipeline spec one writer, the orchestrator's copy of the template. Within this
overnight session, earlier rounds' attempts, changes and measurements are in their own dev and QA reports
and the cycle's retro report, not in the spec.

## BA with an overnight spec

**On startup.** Read the project's CLAUDE.md FIRST (Step 1), THEN the overnight spec file. The CLAUDE.md
read establishes the role table and project-specific rules; the spec read provides cross-cycle history.
Both precede any analysis. The spec contains:
- Section 1 (Before): Current state before any fix -- use this as your baseline
- Section 2 (What Was Attempted): Previous cycle approaches -- do NOT repeat failed strategies
- Section 4 (Current State): QA-measured values from previous cycles -- use these as concrete data
- Section 5 (User's Acceptance Criterion): The verbatim user requirement -- this is your north star
- Section 6 (Why Not Met): Specific gaps from previous QA -- address these directly
- Section 7 (What Must Be Done): Prescriptive next steps -- follow these if present

**After analysis.** Do not write the spec file. What used to go into Sections 5 and 1 goes in your context,
which the next round and the spec's continuation read:
- **User's Acceptance Criterion** (`requirement.original`): the verbatim user requirement text. If from a
  focus string, quote it exactly. If from the user-provided spec, preserve the original wording. Do NOT
  paraphrase or rephrase into BDD format here -- this field is the raw user voice.
- **Before** (`root_cause_analysis.symptom` and `root_cause_analysis.observations`): the current state before
  any fix attempt, from specialist observations or your own analysis, with screenshot paths if available.

## Dev with an overnight spec

**On startup.** Read the full spec file FIRST, before the context JSON or BA spec. The spec contains critical
cross-cycle context:
- Section 2 (What Was Attempted): Previous cycle approaches -- do NOT repeat these if they failed
- Section 3 (What Was Changed): Exact file:line changes from previous cycles -- know what was already tried
- Section 4 (Current State): QA-measured values -- use these as concrete starting points
- Section 6 (Why Not Met): Specific gaps -- address these directly
- Section 7 (What Must Be Done): Prescriptive next steps -- follow these if present

Earlier rounds of this session are in the QA report file your prompt names.

**After implementation.** Do not write the spec file. Record in your report's `dev.tasks_completed` entries
what used to go into Sections 2 and 3:
- **What Was Attempted** (`description`, `rationale`): what approach you took and why, referencing previous
  cycle data if applicable; if you deviated from Section 7 recommendations, explain why
- **What Was Changed** (`changes`, `files_modified`, `files_created`): every change with exact file:line and
  old->new values, for example `file.tsx:42 -- property: oldValue -> property: newValue`; include ALL
  changes, not just the "main" fix; a created file names its purpose

## PM with an overnight spec

**PLAN mode, user-spec mode** (the owner passed `--spec <path>` to `/dev-overnight`):
- Read the user's spec file FIRST before any browser exploration or doc reading
- The user's spec already contains the issue description, acceptance criteria, and possibly before-state
- Skip full browser exploration for issues already described in the spec -- focus on validating what the
  user wrote
- Act as **supervisor**: your job is to validate agent output against the user's spec, not to write your own
  plan from scratch
- Still allow specialists to discover additional issues beyond what the user specified
- In your test plan, set `spec_mode: "user-provided"` and `spec_path: "<path>"`

**PLAN mode, autonomous mode** (no user spec): normal PLAN behaviour -- explore the app, build the test plan.
After PM TRIAGE creates pipelines, the orchestrator creates spec files from the template; PM writes no spec
(BA's context carries what Sections 1 and 5 hold).

**TRIAGE mode.** User-spec mode: validate specialist findings against the user's spec and prioritize the
user-spec issues as Tier 1. Autonomous mode: after you create pipelines, the orchestrator creates the spec
files; PM does not modify specs during TRIAGE.

**RETRO mode.** When spec paths are provided, read each spec file; do not write it. Record per unresolved
pipeline, in your retro report's `unresolved_issues` (RETRO Step 4; the next cycle's PLAN reads it, Step 2:
Read Session History):
- **What Must Be Done**: prescriptive next steps. Be specific: name the file, line, and concrete action. Do
  NOT write generic advice like "investigate further" or "try a different approach".
- **Attention Notes**: issue-specific traps, warnings, and patterns noticed. Examples: "This component
  re-renders on every state change -- test with React DevTools profiler", "The CSS specificity war between
  global.css and module.css causes unpredictable overrides".

## QA with an overnight spec

**On startup.** Read the full spec file FIRST, before the context JSON, dev report, or BA spec. The spec
gives you:
- Section 1 (Before): Baseline state -- compare against this
- The exact changes Dev made this cycle are in the dev report's `dev.tasks_completed` (no longer in the
  spec's Section 3) -- verify these specifically
- Section 5 (User's Acceptance Criterion): The verbatim requirement -- this is what you verify against
- Section 7 (What Must Be Done): What was prescribed -- check if Dev followed it

**After verification.** QA does NOT write the spec: the verifier role must not mutate the spec it verifies.
QA REPORTS Section 4 / 6 / 7 content as fields under `qa.spec_section_updates` in the qa-report JSON. They
stay in the report: nobody copies them into the spec during the cycle, and the spec's continuation
(`/spec-update`, `/commit` Step 8) reads them from there. Populate `qa.spec_section_updates` with:

- **`section_4` (Current State)** — a non-null string whenever a spec is present and Section 4 measurements
  were taken (i.e., on every spec-driven cycle), describing actual measured values: pixel dimensions (e.g.,
  "header height: 48px, expected: 64px"), computed CSS properties (e.g., "padding: 8px 12px, font-size:
  14px"), console errors or warnings (verbatim text), screenshot paths for visual evidence, API response
  values if applicable.
- **`section_6` (Why Not Met)** — a non-null string ONLY when the verdict is `fail`; null otherwise: the
  specific gap between measured state and acceptance criterion. Reference Section 4 values vs the Section 5
  criterion; be precise ("Header height is 48px but user requires 64px", not "Header is too small"); include
  the evidence path (screenshot, console log).
- **`section_7` (What Must Be Done)** — a non-null string ONLY when the verdict is `fail`; null otherwise: the
  prescriptive next step. Name the exact file, line, property, and target value (e.g., "Set `min-height:
  64px` on `.header` in `Chat.module.css:18`"); for a more complex issue, outline the specific approach (not
  "try something else").

**Cycle-compatible content**: the continuation places QA's reported `section_4` / `section_6` / `section_7`
strings under a new cycle subsection header (e.g., `### Cycle N`) after any existing cycle content, never
over prior cycles. So QA writes content describing only THIS cycle's measurements / gap / prescription — do
not reference or re-summarize prior cycles' content.

**Population requirement (anti-no-op)**: when a spec is present and Section 4/6/7 updates are due,
`qa.spec_section_updates` MUST be non-null with the appropriate sub-fields populated. A null
`qa.spec_section_updates` on a spec-driven cycle leaves the spec's continuation nothing to record for this
cycle. See qa.md's `## Output Format` for the schema declaration.
