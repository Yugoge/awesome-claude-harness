# Specialist Findings Intake Protocol

Read this file when your dispatch hands you specialist findings (ui-specialist, architect, product-owner or
user reports), before you use any of them; the section for your role below applies.

## BA: specialist findings as Contract A evidence

BA receives specialist findings through the orchestrator's specialist routing (`/dev` Step 3, Specialist
Consultation; `/dev-overnight`'s triaged pipelines). This protocol applies before a finding is used as
Contract A evidence.

**Mandatory fields per specialist type**

| Specialist | Required for Contract A use | Notes |
|---|---|---|
| ui-specialist | `location.selector`, `measured`, `expected`, `downstream_agent: "ba"` | All three canonical channels (automated_findings, contextual_findings, aesthetic_findings) inherit these from finding_base via allOf |
| architect | `location.file`, `location.line`, `measured`, `expected`, `downstream_agent: "ba"` | `location.url` is optional; `measured` distills `runtime_evidence` into a scalar |
| product-owner | `observed_behavior`, `expected_behavior`, `downstream_agent: "ba"` | `location.file` acceptable as string (not browser-only) |
| user | `location.url`, `observed_behavior`, `expected_behavior`, `downstream_agent: "ba"` | `location.file` MUST be null — user agent is browser-only. `location.url` is required so the finding is reproducible. |

**tier_3_tainted classification.** A finding is classified `tier_3_tainted` when it is a natural-language-only
claim that lacks any required evidence field: for ui-specialist/architect this means `measured` OR
`expected` is absent; for product-owner/user this means `observed_behavior` OR `expected_behavior` is absent.
Missing any one of the pair is sufficient to taint — a finding with `measured` but no `expected` cannot be
verified. Tainted findings:
- Cannot be used as primary Contract A evidence without independent BA measurement
- MUST be flagged in BA's context JSON under `root_cause_analysis.observations[]` with a note indicating the
  taint
- May still inform BA's investigation direction, but BA must independently verify before citing

**Measurement fallback.** When a specialist finding lacks `measured` or `expected` (or their prose equivalents
for architect/product-owner/user), BA MUST measure independently before using that finding as Contract A
evidence:
1. Read the relevant source file or query the runtime directly
2. Record the independently-measured value as BA's own `measured` data point
3. Note in the spec that the specialist finding lacked the field and BA measured independently

This fallback does NOT exempt the specialist from the requirement — BA reports the gap to the orchestrator
as an observation.

**downstream_agent routing.** Every specialist finding with `downstream_agent: "ba"` is routed to BA for
root-cause analysis and spec generation. BA is the exclusive first-stage consumer. BA does NOT forward raw
specialist findings to dev — BA translates them into a BA spec with root-cause analysis,
development_approach, and acceptance criteria.

**Fast-fail.** BA MUST reject findings used as primary evidence if they lack the required fields for their
specialist type (see the table above). Rejection means:
- The finding is NOT cited in the BA spec as a Contract A measurement
- The finding is logged in `out_of_scope_observations` or as a tainted observation with the missing fields
  noted
- BA proceeds with independent measurement (see the measurement fallback above), and reports the gap to the
  orchestrator when it cannot measure the value itself

Findings used only as investigation leads (not primary evidence) are exempt from the fast-fail rule, but
must still be flagged as tainted if they lack required fields.

## PM: specialist findings in PLAN and TRIAGE

This protocol applies when PM receives specialist findings in **TRIAGE mode** (routing findings to BA
pipelines or `out_of_scope_observations`) or in **PLAN mode** (seeding priority tiers). Important mode
distinction: BA routing, pipeline creation, and deferral language apply **only in TRIAGE mode**. In PLAN
mode, specialist findings inform priority ordering only — PM does not route findings to BA or create
pipelines.

**Mandatory fields per specialist type**

| Specialist | Required for triage/test-plan use | Notes |
|---|---|---|
| ui-specialist | `location.selector`, `measured`, `expected`, `downstream_agent: "ba"` | `location.selector` is required (non-null) for targeted browser test; `location.url` is preferred companion — both schema keys must be present (nullable allowed) |
| architect | `location.file`, `location.line`, `measured`, `expected`, `downstream_agent: "ba"` | `location.url` optional; `location.line` needed for precise test scenario linkage to source |
| product-owner | `observed_behavior`, `expected_behavior`, `downstream_agent: "ba"` | `location.url` strongly preferred for reproducibility in PLAN browser exploration |
| user | `location.url`, `observed_behavior`, `expected_behavior`, `downstream_agent: "ba"` | `location.file` MUST be null (browser-only); `location.url` is required so PM can reproduce the scenario during PLAN mode |

**tier_3_tainted classification.** A finding is `tier_3_tainted` when it lacks ANY of the required evidence
fields for its specialist type (see the table above). Missing either side of an evidence pair is sufficient
to taint — a finding with `measured` but no `expected` cannot be verified. Tainted findings:
- Cannot form the sole basis for a test scenario or pipeline creation
- MUST be flagged by naming the missing fields:
  - **In TRIAGE mode** — in `observation_notes` (for `issues[]` entries) or in
    `out_of_scope_observations[].observation` / `pm_notes[]` (for `out_of_scope_observation` findings, which
    have no `observation_notes` field)
  - **In PLAN mode** — in the `evidence` field of the affected priority tier entry (e.g. `"evidence":
    "TAINTED — missing measured/expected: treat as tentative"`)
- May still inform priority ordering; the gap MUST be noted in whichever field is appropriate for the current
  mode (see the bullet above)
- In TRIAGE mode only: during Step 4 assessment (before finalization), MAY still contribute to `pipe_category`
  determination when other evidence supports it — tainted findings may NOT reopen or override a finalized
  Step 4 classification; PM records the gap in `pm_notes[]` (TRIAGE-only schema field) and recommends BA
  independent measurement before dev dispatch

**PM does not perform BA's measurement fallback.** PM marks the gap in the mode-appropriate field and defers
to BA; BA performs independent measurement per the BA section above.

**Triage confidence mapping**

| Evidence completeness | Triage impact |
|---|---|
| All required fields present | Eligible for test scenario (PLAN) or pipeline creation after Step 3 and Step 4 pass (TRIAGE) |
| ANY required evidence field absent (tainted) | In PLAN: note taint in tier `evidence` field, treat as tentative; in TRIAGE: apply the fast-fail cases below |

**Routing (TRIAGE mode only).** Findings with `downstream_agent: "ba"` route to BA pipelines **only after
passing Step 4 (User-Need Path Relevance Filter)**:
- `pipe_category: "user_need"`, `"security"`, or `"dependency"` → eligible for BA pipeline creation
- `pipe_category: "out_of_scope_observation"` → routed to `out_of_scope_observations[]`; no BA pipeline
  regardless of `downstream_agent` value

PM does NOT convert specialist findings to implementation tasks directly. For tainted on-path findings,
record the evidence gap in `pm_notes[]` with `description: "Evidence gap: [missing fields]. BA measurement
recommended before dev dispatch."` and `source_agent`.

**Fast-fail.** PM MUST NOT generate a test scenario or pipeline with a concrete pass/fail criterion based
solely on a tainted finding. Apply the following by case:
- **In PLAN mode**: do not create a pipeline or set `pipeline_recommendation`. Note the taint in the
  `evidence` field of the affected priority tier entry.
- **In TRIAGE mode — pipeline-eligible UI finding (`pipe_category: user_need`, `security`, or `dependency`;
  AND Step 3 applies)**: PM MUST NOT defer. Create the pipeline with `pipeline_recommendation: "fix"` and the
  evidence gap noted in `observation_notes`; BA/QA enforce the live-evidence gate downstream.
- **In TRIAGE mode — pipeline-eligible non-UI finding (`pipe_category: user_need`, `security`, or
  `dependency`; AND Step 3 does NOT apply)**: note the gap in `observation_notes` and use
  `pipeline_recommendation: "defer"` with the gap description.
- **In TRIAGE mode — `out_of_scope_observation` finding**: do NOT set `pipeline_recommendation` (Step 4: no
  pipeline_recommendation for out-of-scope). Record the taint gap in `out_of_scope_observations[].observation`
  or `pm_notes[]`.

**This rule does NOT override Step 3 (Live-Evidence Mandate).** On-path UI findings that produce a UI surface
must go through the live-evidence gate regardless of evidence completeness.

**This rule does NOT override Step 4 (User-Need Path Relevance Filter).** Step 4 applies before this rule;
`out_of_scope_observation` findings do not become pipelines regardless of evidence completeness.
