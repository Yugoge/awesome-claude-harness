# Codex consultation

Read this file when your dispatch prompt carries the line `codex_required: true`. Without that line (the
default) you skip codex: your output carries `codex_consult: { invoked: false, status: "not_requested",
findings: [], feedback_summary: null, feedback_incorporated: null }` and nothing below applies.

**Who sets the line.** Codex is off by default; the owner turns it on with `--codex`. The orchestrator adds
the line to the dispatches whose command text carries it:

- `/dev`, `/redev`, `/dev-command`, `/dev-overnight`: the dispatches whose template carries it.
- `/spec`, `/clean`: the dispatches whose template carries it.
- `/close`, `/commit`: QA's dispatch (`/commit`: `codex_required: <QA_CODEX>`). That command's own text sets out
  QA's Codex round; the protocol below governs how Codex is asked and answered there too.
- `/do`: no subagent runs; the main agent calls codex itself (commands/do.md Step 3), by the same protocol.

Enforcement, as `docs/ENFORCEMENT-LEDGER.md` states it (its codex rows): on a `/dev`-family cycle started with
`--codex`, a SubagentStop hook checks that a bound subagent called `Skill(codex)` before it stops, and the
ledger lists it as advisory, with no prevention guarantee. Nothing checks it for the other commands.

## The protocol (every Codex call in the pipeline)

1. **Prelude.** Every Codex prompt starts with three lines: `USER REQUIREMENT:` (the verbatim requirement, or
   the contents of the `User requirement document:` your dispatch names), `SCOPE:` (what this call may judge)
   and `OUT OF SCOPE:` (what it must not judge, including anything the requirement does not ask for).
2. **Running first.** Each finding names a realistic trigger (the input or path, in the stated use, that hits
   it), its consequence and a `PROPOSED_FIX`, and gives its severity last, after the description:
   - `blocker`: it does not run, or the requirement fails on its main path;
   - `high`: a real defect on a path the requirement uses;
   - `medium`: a real defect on a realistic secondary path;
   - `edge`: it needs an unusual input or state the requirement does not name;
   - `style`: cleanliness of this diff.
3. **One complete pass.** The first call reviews everything in scope at once, style of this diff included, and
   returns one full list. Only blocker, high and medium findings with a realistic trigger send work back. Fix
   this diff's `style` items in the same rework when each is small; otherwise list them. List `edge` items.
   Neither ever starts another round.
4. **A re-review only verifies.** A later call gets Codex's earlier list and the diff since. It reports, for each
   earlier item, fixed or not fixed, and only new blocker or high defects that the fix itself introduced. At
   most two re-reviews follow the first call. What is still open then and below blocker is listed, and the work
   goes on. The cap limits Codex calls, not your fixes: a blocker you classify `in_scope_real_bug` is fixed.
5. **You classify, and you may reject.** Before acting, classify every finding as `in_scope_real_bug`,
   `in_scope_minor`, `out_of_scope` or `nitpick`, with a one-line reason. Rejecting is as valid as applying;
   silence is not. Reject a finding with no realistic trigger. To apply a fix, state what the change adds and
   which failure it prevents; reject a fix larger than the risk it removes, or one that widens the scope. An
   `out_of_scope` finding is listed, never fixed. Codex never sets your verdict.

## Procedure

1. Draft your output (your role's report, verdict or artifact, after every step your agent file requires before
   it; tag it as a draft, not yet ready). The style-, cleanliness- and prompt-inspector keep the draft in
   memory: they write neither the report file nor a draft file before step 5, and give step 2's summary as text
   in the prompt, not as a file path.
2. Invoke `Skill(skill="codex")` with: the prelude; a brief summary of your draft (1-3 paragraphs: what it
   concludes or changes, plus the artifact paths); and this instruction, scoped to your role's own output rules
   (your agent file's quality gates, severity calibration and constraints): "Review this draft <role> output
   once and completely. Is it complete, correct and in scope against the requirement? Does each finding carry
   the evidence the role requires, and are severities and verdict right? Does it break anything the role's
   rules forbid? Return one list in the finding shape above, each finding ending with its severity. Reply with
   CODEX_FEEDBACK: <list>."
3. Parse the reply, classify every finding (rule 5), apply what rules 3 and 5 send back, and log every finding
   in `codex_consult.findings[]`.
4. If you changed the draft for a blocker or high finding, run one re-review (rule 4). Run the second only if
   the first reports an earlier item not fixed.
5. Issue your final output only after step 4.

**Graceful fallback (codex unavailable).** If `Skill(codex)` returns a quota error ("usage limit", "try again
at..."), no response within reasonable time, or output you cannot parse, record `codex_consult: { invoked:
true, status: "failed_quota" | "failed_timeout" | "failed_parse", findings: [], feedback_summary: "<verbatim
error or summary>", feedback_incorporated: "self-review substituted" }` and run a self-review of 5 or more
adversarial questions you generate yourself on the points of step 2's instruction. The self-review stands in
for codex and the cycle continues; never wait on codex.

## Output documentation

Every output of yours carries a `codex_consult` field (top level of your report; BA: in the context JSON):

```json
{
  "codex_consult": {
    "invoked": true | false,
    "status": "ok" | "failed_quota" | "failed_timeout" | "failed_parse" | "not_requested",
    "feedback_summary": "<overall summary or error message, or null when not_requested>",
    "findings": [
      {
        "issue": "<what codex flagged>",
        "trigger": "<the realistic trigger codex named, or null>",
        "proposed_fix": "<codex's PROPOSED_FIX text, or null>",
        "severity": "blocker | high | medium | edge | style",
        "classification": "in_scope_real_bug | in_scope_minor | out_of_scope | nitpick",
        "disposition": "applied | rejected | listed",
        "rationale": "<one line: why applied, rejected or listed>"
      }
    ],
    "feedback_incorporated": "<what changed in the draft, or 'self-review substituted' on failure, or null when not_requested>"
  }
}
```

A dev or QA report also lists the `edge`, `out_of_scope` and `nitpick` items it did not fix in
`codex_observation_only[]`. BA does not put them in `out_of_scope_observations`, which holds path-external code
observations with file and line. The orchestrator, QA and the `/close` debate read `codex_consult` to know
whether codex challenged the output, whether self-review was substituted, or whether codex was not requested.
