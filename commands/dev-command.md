---
description: /dev for developing a slash command, a subagent or another .claude file; the /dev workflow with the differences in this file (its own 16 steps, a singular cycle)
disable-model-invocation: true
summary: "The /dev workflow for building a slash command, a subagent or another harness file, with the differences such a file needs."
group: Develop
---

`/dev-command` is `/dev` for developing a command or agent file: a project slash command (`.claude/commands/`), a subagent (`.claude/agents/`) and what such a file calls (scripts, hooks, configuration, todo scripts). After the first TodoWrite of the hook's checklist, read `<HARNESS_ROOT>/commands/dev.md` (again after a compaction) and follow it, with the differences below and nothing else. A `/dev` rule this file does not mention applies as written, including "One cycle, no phases" (Requirement Decomposition & Fan-Out): every requested outcome is delivered in this cycle, with no sequential phases or deferred parts. Several requirements fan out as that section says; the templates below are the singular ones, and `/dev`'s Step 11 (the aggregate dev-report of a fan-out) runs between Steps 10 and 11 here.

`<timestamp>` and `<TASK_ID>` below are the hook's `Task id: …`, the bare id every artifact and the completion report carry. `DEV_SESSION_ID` (`dev-command-<timestamp>`) names the registry directory and the requirement document only; it is never an artifact id.

This file keeps its own 16 steps (`scripts/todo/dev-command.py`). A step number inside `/dev`'s text is `/dev`'s: read it through this map. Each obligation fence below also repeats `/dev`'s own two `codex_required` lines (they are not an addition): the codex gate reads them from this file's template.

| Step here | `/dev` Step | Differs |
|---|---|---|
| 1 Parse Development Requirement | 1 | the start-function fallback |
| 2 Graphify pre-BA hydrator | 2 | no |
| 3 Specialist Consultation | 3 | no |
| 4 Delegate to BA Subagent | 4 | obligation; no score header |
| 5 BA Clarification Loop | 5 | obligation |
| 6 Validate BA Output | 6 | no |
| 7 QA Validates BA Conclusions | 7 | obligation |
| 8 BA-QA Iteration Loop | 8 | obligation |
| 9 Graphify enrichment | 9 | where the graph line goes |
| 10 Delegate to Dev Subagent | 10 | what it writes; no test-writer, header or baseline |
| 11 Validate Dev Implementation | 12 | no |
| 12 Delegate to QA Subagent | 13 | obligation; no score header |
| 13 Process QA Results | 14 | no score updates |
| 14 Update Settings.json Permissions | 15 | no |
| 15 Iteration Loop | 16 | this file's numbers |
| 16 Generate Completion Report | 17 | one lane; its identity |

### Step 1: Parse Development Requirement

As `/dev` Step 1. The start-function fallback, run when the hook's lines are not in your context, types this command:

```bash
python3 ~/.claude/hooks/prompt-workflow.py start <<'CMDEOF'
<the command exactly as typed: /dev-command, then $ARGUMENTS>
CMDEOF
```

### Step 2: Graphify pre-BA Bash hydrator (mirrors commands/dev.md)

As `/dev` Step 2.

### Step 3: Specialist Consultation (always evaluate, never silently skip)

As `/dev` Step 3.

### Step 4: Delegate to BA Subagent

As `/dev` Step 4, with this command's differences: no test-writer, so BA owes no acceptance-criteria JSON; the singular dispatch (leave out the lane-adapter line); no `BA_SCORE_HEADER` (Steps 1-4 then use at most four Bash calls before this dispatch). In place of `/dev`'s worked example the obligation is:

```
  Obligation block: embed `<obligation v="1">{...}</obligation>` here with role="ba", pipeline="dev-command", profile="singular", task_id/dispatched_at bound to this dispatch (see /dev Step 4), artifacts=[{"kind":"json","path":"docs/dev/context-<timestamp>.json","schema":"context.v1","identity":{"task_id":"<timestamp>","request_id":"<timestamp>"}},{"kind":"markdown","path":"docs/dev/ticket-<timestamp>.md","identity_anchor":"<timestamp>"}].

  <If codex_required = true, include the literal next line; otherwise omit it>
  codex_required: true
```

### Step 5: BA Clarification Loop

As `/dev` Step 5; the BA dispatched again carries Step 4's obligation with a fresh `dispatched_at`.

### Step 6: Validate BA Output

As `/dev` Step 6.

### Step 7: QA Validates BA Conclusions

As `/dev` Step 7: one QA in BA-validation mode, all five dimensions (a dispatch that lists four is stale), the no-phases check inside `scope_alignment` among them. The obligation is:

```
  Obligation block: embed `<obligation v="1">{...}</obligation>` here with role="qa", pipeline="dev-command", profile="ba_validation", task_id/dispatched_at bound to this dispatch (see /dev Step 4), artifacts=[{"kind":"json","path":"docs/dev/ba-qa-report-<timestamp>.json","schema":"ba-qa-report.v1","identity":{"task_id":"<timestamp>"}}].

  <If codex_required = true, include the literal next line; otherwise omit it>
  codex_required: true
```

### Step 8: BA-QA Iteration Loop (if QA rejects BA)

As `/dev` Step 8; the BA dispatched again carries Step 4's obligation with a fresh `dispatched_at`.

### Step 9: Graphify enrichment (mirrors commands/dev.md)

As `/dev` Step 9; its `Graph context file:` line, when graphify's run record says `ok` or `degraded`, goes into this file's Step 10 (dev) and Step 12 (QA) dispatches.

### Step 10: Delegate to Dev Subagent

As `/dev` Step 10's dev dispatch, without its test-writer gate and dispatch, its `DEV_SCORE_HEADER` line, its `baseline_head_sha` and `baseline_dirty_snapshot` capture and lines, and its `Generated tests` line. Dev writes the file the requirement names (a project command under `<project>/.claude/commands/`, an agent under `.claude/agents/`, ...) and creates a script only for an operation that repeats (about five runs or more), a multi-step workflow, an integration or a performance-critical path; a one-time operation is the agent's own work. `hooks/pretool-claude-config-guard.py` lets this command's dev write the project command file (its dispatch carries its obligation block); any other write under `.claude/hooks/` or `.claude/commands/` needs the owner's `.claude/.hook-refactor-allow`. The obligation is:

```
  Obligation block: embed `<obligation v="1">{...}</obligation>` here with role="dev", pipeline="dev-command", profile="singular", task_id/dispatched_at bound to this dispatch (see /dev Step 4), artifacts=[{"kind":"json","path":"docs/dev/dev-report-<timestamp>.json","schema":"dev-report.v2","identity":{"task_id":"<timestamp>"}}].

  <If codex_required = true, include the literal next line; otherwise omit it>
  codex_required: true
```

### Step 11: Validate Dev Implementation

As `/dev` Step 12; when dev completed, go to Step 12.

### Step 12: Delegate to QA Subagent

As `/dev` Step 13, without its `QA_SCORE_HEADER` line and its `Per-task active test manifest` line. The obligation is:

```
  Obligation block: embed `<obligation v="1">{...}</obligation>` here with role="qa", pipeline="dev-command", profile="final_verification", task_id/dispatched_at bound to this dispatch (see /dev Step 4), artifacts=[{"kind":"json","path":"docs/dev/qa-report-<timestamp>.json","schema":"qa-report.v2","identity":{"task_id":"<timestamp>","request_id":"<timestamp>"}}].

  <If codex_required = true, include the literal next line; otherwise omit it>
  codex_required: true
```

### Step 13: Process QA Results

As `/dev` Step 14 without its score-update events: `qa.status == "pass"` goes to Step 14; `warning` or `fail` goes to Step 15.

### Step 14: Update Settings.json Permissions

As `/dev` Step 15; the line is:

```bash
python3 "<HARNESS_ROOT>/scripts/aggregate-permissions.py" docs/dev/qa-report-<timestamp>.json | bash "<HARNESS_ROOT>/scripts/apply-permissions.sh" /dev/stdin .claude/settings.json
```

### Step 15: Iteration Loop (QA warning or fail)

As `/dev` Step 16, in this file's numbers: re-dispatch this lane's dev with the QA report path, the same task_id, lane and obligation template, and a fresh `dispatched_at`; Steps 11-13 run again, and the loop repeats until QA passes (then Step 14). Dispatch line: `QA report file: docs/dev/qa-report-<timestamp>.json`.

The Stop gate keeps the command open until the disposition is chain_pass, which needs the QA report's `qa.status` to be `pass` (`INVALID_QA_STATUS` until then). There is no other exit.

### Step 16: Generate Completion Report

As `/dev` Step 17 for one lane (`mode == "singular"`). The report's identity is the hook's `Task id: …` as given, the bare `<timestamp>`: never `dev-<timestamp>`, never the registry name `dev-command-<timestamp>`. The chain resolver reads that identity and the four references below, and a prefixed id or a missing reference fails it.

```markdown
# Development Completion Report — <timestamp>

**Request ID**: <timestamp>
**Completed**: <ISO-8601>
**Iterations**: <N>

## Summary

{As /dev Step 17's Summary; its quality line names the standards of a command or agent file: no hardcoded values, the venv sourced, integer step numbering, meaningful names, root cause referenced.}

## Files Generated

- Ticket: `docs/dev/ticket-<timestamp>.md`
- Context: `docs/dev/context-<timestamp>.json`
- Dev Report: `docs/dev/dev-report-<timestamp>.json`
- QA Report: `docs/dev/qa-report-<timestamp>.json`

## Follow-up Suggestions (outside the request)

{As /dev Step 17's.}
```

**Save report to**: `docs/dev/completion-<timestamp>.md`

Then `/dev` Step 17's postcondition (the shared resolver) with `--task-id "<TASK_ID>"`, and its Next command.
