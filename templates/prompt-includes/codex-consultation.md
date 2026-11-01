# Codex adversarial consultation

Read this file when your dispatch prompt carries the line `codex_required: true`. Without that line (the
default) you skip codex: your output carries `codex_consult: { invoked: false, status: "not_requested",
findings: [], feedback_summary: null, feedback_incorporated: null }` and nothing below applies.

**Who sets the line.** Codex is off by default; the owner turns it on with `--codex`. The orchestrator then
adds `codex_required: true` to the dispatches whose template carries that line in `/dev`, `/redev`,
`/dev-command`, `/dev-overnight`, `/spec`, `/close` and `/clean`, and `/commit --codex` passes it to its
pre-commit QA (`codex_required: <QA_CODEX>`). `/do --codex` dispatches no subagent: the main agent runs the
codex audit itself (commands/do.md Step 3). Under `--codex` the UserPromptSubmit hook arms the cycle's
`codex-enforce.json`, and `hooks/subagentstop-codex-enforce.py` blocks the stop (exit 2,
`CODEX_ENFORCE_BLOCKED`) of a subagent whose dispatch, or the template it was made from, carries the line
until its `Skill(codex)` call is in the cycle's codex ledger; without `--codex` that hook exits 0.

This per-dispatch consultation is distinct from the multi-round QA-codex debate inside `/close` (governed by
`commands/close.md`'s own `--codex` flag). It catches over-engineering, under-engineering, missed edge cases
and scope drift before the orchestrator and downstream agents inherit the mistake.

**Procedure**

1. Draft your output (your role's report, verdict or artifact, after every step your agent file requires
   before it; tag it as a draft, not yet ready).
2. Invoke `Skill(skill="codex")` with:
   - If `User requirement document:` was present in your dispatch, read it now and prepend `Verbatim user
     requirement: <exact contents of the document>` to the Skill(codex) prompt before the draft summary, so
     codex can detect scope drift or degradation against the original user text.
   - A brief summary of your draft (1-3 paragraphs: what it concludes or changes, plus the artifact paths).
   - The explicit instruction, scoped to your role's own output rules (your agent file's quality gates,
     severity calibration and constraints): "Challenge adversarially whether this draft <role> output is
     complete, correct and in scope. Look for over/under-engineering, missed edge cases, regression risk,
     scope drift, findings without the evidence the role requires, severity or verdict errors, and anything
     the role's rules forbid. **For every issue you flag, you MUST provide `PROPOSED_FIX: <concrete
     correction>`. A complaint without a PROPOSED_FIX is an observation, not a blocker.** Reply with
     CODEX_FEEDBACK: <list of issues, each with PROPOSED_FIX or marked OBSERVATION_ONLY>."
3. Parse codex's feedback.
4. Incorporate codex feedback proportionally:
   - Findings with a `PROPOSED_FIX`: apply the fix or explain specifically why you disagree — both positions
     are valid, but silence is not.
   - Findings marked `OBSERVATION_ONLY` (no PROPOSED_FIX): log them in `codex_consult.findings[]` with
     `classification: "observation_only"` and `disposition: "logged"` (a dev or QA report also lists them
     in `codex_observation_only[]`; BA does not put them in `out_of_scope_observations`, which holds
     path-external code observations with file and line). Do NOT let a bare complaint without a concrete fix
     block delivery or start a re-work loop.
5. Issue your final output only after step 4.

**Graceful fallback (codex unavailable)**

If `Skill(codex)` returns a quota error ("usage limit", "try again at..."), no response within reasonable
time, or output you cannot parse, record `codex_consult: { invoked: true, status: "failed_quota" |
"failed_timeout" | "failed_parse", findings: [], feedback_summary: "<verbatim error or summary>",
feedback_incorporated: "self-review substituted" }` and run a self-review of 5 or more adversarial questions
you generate yourself on the points of step 2's instruction. The self-review stands in for codex and the
cycle continues; never wait on codex.

**Output documentation**

Every output of yours carries a `codex_consult` field (top level of your report; BA: in the context JSON)
with this shape:

```json
{
  "codex_consult": {
    "invoked": true | false,
    "status": "ok" | "failed_quota" | "failed_timeout" | "failed_parse" | "not_requested",
    "feedback_summary": "<overall summary or error message, or null when not_requested>",
    "findings": [
      {
        "issue": "<what codex flagged>",
        "proposed_fix": "<codex's PROPOSED_FIX text, or null if OBSERVATION_ONLY>",
        "classification": "blocker | major | observation_only",
        "disposition": "applied | rejected | logged",
        "rationale": "<why applied or rejected>"
      }
    ],
    "feedback_incorporated": "<what changed in the draft, or 'self-review substituted' on failure, or null when not_requested>"
  }
}
```

The orchestrator, QA and the `/close` debate read it to know whether codex challenged the output, whether
self-review was substituted, or whether codex was not requested at all.
