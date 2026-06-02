---
description: Continuation spec update or temp session note (was /update then /spec-continue — renamed to avoid collision with MAP's /update portfolio mutation command)
argument-hint: "[--temp] [--spec <path>] [what the next session should focus on]"
disable-model-invocation: true
---

# /spec-update — Continuation Spec Update

Turn unfinished work into a continuation spec that a fresh Claude Code or Codex
session can continue with `/dev`. Use a compact temp note only when explicitly
requested for non-development session continuity.

**Migration note**: This command was previously `/update` at `~/.claude/commands/update.md`,
then renamed to `/spec-continue`, and is now `/spec-update`. The renames resolve name
collisions and improve clarity. Users with muscle-memory for `/update --temp` should
now use `/spec-update --temp` instead.

Inspired by Matt Pocock's `mattpocock/skills` handoff skill; renamed and adapted here for
our `spec → dev → close → commit → push` workflow.

## Mode selection

1. **Continuation-spec mode (default)** — use when there is unfinished
   development work after `/dev`, `/redev`, or a failed `/close`, or when the
   user says to continue/improve the plan. The output is a spec under
   `docs/dev/specs/`.
2. **Temp-note mode (`--temp`)** — use only when the user explicitly asks for a
   session/bootstrap note, or when `/commit`/`/push` need a non-repo recovery
   note after branch-moving actions. The output is a temp markdown file.

## Continuation-spec mode

Resolve the target spec:

1. If `--spec <path>` is provided, update that spec.
2. Else if the active `/dev` context has `spec_path` / `spec_file` /
   `user_spec_path`, update that spec.
3. Else create a new spec from `~/.claude/templates/overnight-spec.md` at
   `${CLAUDE_PROJECT_DIR:-$(pwd)}/docs/dev/specs/spec-<YYYYMMDD-HHMMSS>.md`.

Gather source artifacts from the active task-id when available:

- `docs/dev/context-<task-id>.json`
- `docs/dev/dev-report-<task-id>.json`
- `docs/dev/qa-report-<task-id>.json`
- `docs/dev/close-report-<task-id>.md`
- `docs/dev/completion-<task-id>.md`
- the user's latest message / explicit focus string

When updating an existing spec, append; never overwrite prior cycles. Determine
the next cycle number as `max(existing "### Cycle N" headings across Sections
1-7) + 1`; if none exist, use Cycle 1.

Before appending the first new `### Cycle N` heading for this run, check whether
the spec file already contains `<!-- spec-continuation-of: <resolved-task-id> -->`
(substituting the actual task-id value — never a literal `${TASK_ID}` or
`<task-id>` placeholder). If that exact line is absent, write it as the very
first line of the new cycle block, before any section headings. If it is already
present, do not write a second copy. This marker is written exactly once per
(task-id, spec file) pair and must appear only in this continuation-spec mode,
never in temp-note mode.

Populate the per-cycle sections (Sections 2-8) as follows:

- Section 2: what was attempted and why it did not finish.
- Section 3: changed files or artifact references, not raw diffs.
- Section 4: current measured state / QA result / close dissent.
- Section 5: remaining user acceptance criteria; append as `### 5.N` only when
  the remaining criterion is new or materially refined.
- Section 6: specific gap between current state and done.
- Section 7: concrete next plan for the next `/dev` run.
- Section 8: traps, stale assumptions, and warnings for the next agent.

Section 9 (Design & Evidence References) is owned by the `/spec` orchestrator at
design/evidence capture time, not by `/spec-update`. Leave any existing Section 9
reference lines intact; do not populate or rewrite Section 9 here.

For a newly created continuation spec, Section 5 must contain the original
user-facing goal if known plus the remaining acceptance criteria. For an
existing spec, do not rewrite Section 5 unless the remaining criterion is new or
materially refined.

If the spec already has `docs/dev/specs/<spec-id>/views/` or
`.claude/specs/<spec-id>/cp-state-*.json`, record in Section 8 that those split
views/checkpoints predate the continuation update and must not be treated as
fresh unless regenerated. Updating the spec makes its mtime newer than
`.split-complete`; `/dev` and `/dev-command` must then ignore stale views and
fall back to the monolith spec.

Output the spec path and next command:

```text
Continuation spec: <spec_path>
Next: /dev --spec <spec_path>
```

## Temp-note mode (`--temp`)

Create the path with `mktemp -t update-XXXXXX.md`. Read the newly created empty
file before writing to it. Do not write temp updates into the repo unless the
user explicitly passes `--path <path>`.

Required temp-note shape:

```markdown
# Update — <short focus>

Generated: <ISO-8601>
Next focus: <what the next session should do>
Current phase: <spec|dev|close|commit|push|ad hoc>
Task/spec id: <id or "unknown">

## Resume prompt
<3-8 sentences the next agent can paste/read to resume.>

## Artifact map
- Spec/ticket: <path or URL>
- Context/dev/QA/close reports: <paths>
- Commit/branch/remote: <SHA / branch / remote when relevant>

## Decisions not captured elsewhere
- <only decisions absent from the artifacts above>

## Blockers / risks
- <known blocker or "none known">

## Next actions
1. <exact next command or action>
2. <verification or fallback>

## Suggested skills
- <skill/command name> — <why>
```

If `$ARGUMENTS` contains free-form text, treat it as the next-session focus and
tailor the `Resume prompt`, `Next actions`, and `Suggested skills` around it.

## Universal rules

- Do not duplicate existing artifacts. Reference specs, tickets, PRDs, plans,
  ADRs, issues, reports, commits, and diffs by path/URL/SHA.
- Keep it compact: no raw diffs, full logs, copied reports, secrets, or
  transcript dumps.
- The next action for unfinished dev work is a spec-backed `/dev --spec
  <path>`, not `/close` or `/commit`.
