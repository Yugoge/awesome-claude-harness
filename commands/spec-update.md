---
description: Update an existing spec, continue unfinished development, or write a temp session note.
argument-hint: "[--update --spec <path> | --continue | --temp] [--spec <path>] [what the next session should focus on]"
disable-model-invocation: true
---

# /spec-update — Continuation Spec Update

Turn unfinished work into a continuation spec that a fresh Claude Code or Codex
session can continue with `/dev`. Use a compact temp note only when explicitly
requested for non-development session continuity.

Inspired by Matt Pocock's `mattpocock/skills` handoff skill; adapted here for
our `spec → dev → close → commit → push` workflow.

## Mode selection

`--update`, `--continue`, and `--temp` are mutually exclusive select-one
flags. Dispatch order:

1. If both `--update` and `--temp` are passed, stop with a mutual-exclusivity
   error — do not guess which was intended.
2. **Update mode (`--update`)** — pure enrichment of an existing spec's
   Section 5, with no dev-cycle semantics. Requires an explicit `--spec
   <path>` naming an existing spec file; if `--spec` is missing or the path
   does not exist, stop with an error. There is no auto-resolution fallback.
   See `## Update mode` below.
3. **Temp-note mode (`--temp`)** — use only when the user explicitly asks for a
   session/bootstrap note, or when `/commit`/`/push` need a non-repo recovery
   note after branch-moving actions. The output is a temp markdown file.
4. **Continuation-spec mode (default)** — use when there is unfinished
   development work after `/dev`, `/redev`, or a failed `/close`, or when the
   user says to continue/improve the plan. The output is a spec under
   `docs/dev/specs/`. `--continue` is an explicit alias for this default
   (no-flag) behavior.

## Continuation-spec mode

Resolve the target spec:

1. If `--spec <path>` is provided, update that spec.
2. Else if the active `/dev` artifact chain is available, inspect the validated
   singular context or every fan-out `lanes[].context`; use `spec_path` /
   `spec_file` / `user_spec_path` only when all populated values agree. A
   fan-out cycle does not need, and this command must not create, a parent
   context merely to resolve the spec.
3. Else create a new spec from `~/.claude/templates/overnight-spec.md` at
   `${CLAUDE_PROJECT_DIR:-$(pwd)}/docs/dev/specs/spec-<YYYYMMDD-HHMMSS>.md`
   through the one writer (below): `spec-write.py create --spec <path>` with the
   populated template on stdin.

Every write of a spec runs through `~/.claude/scripts/spec-write.py`, the one
writer of `docs/dev/specs/*.md` (`/spec` writes through it too); never Write or
Edit a spec file. `create --spec <path>` takes the whole new file on stdin;
`append --spec <path> --section <N>` (or `<N>.<M>` for a `### N.M` subsection)
adds the text on stdin at the end of that section, or in place of its lone
`_Not yet populated._` line. Name the spec by its absolute path. A run's
appends go in ONE Bash call, one `append` per section chained with `&&` (the
orchestrator gate refuses a sixth Bash call in a row, so a call per section
loses the last one); a refusal stops the chain there, the sections before it
stay written, and only the refused append and those after it run again:

```bash
python3 ~/.claude/scripts/spec-write.py append --spec /abs/path/docs/dev/specs/spec-<ts>.md --section 2 <<'SPEC_BLOCK' &&
### Cycle <N>
<content>
SPEC_BLOCK
python3 ~/.claude/scripts/spec-write.py append --spec /abs/path/docs/dev/specs/spec-<ts>.md --section 3 <<'SPEC_BLOCK'
### Cycle <N>
<content>
SPEC_BLOCK
```

Gather source artifacts from the active task-id when available. For `/dev`
work, take the `ARTIFACT_CHAIN` the invoking command already holds from its
one chain call (`/dev`'s and `/dev-command`'s end, `/close` Step 0, `/commit`
Step 5), verbatim; only a `/spec-update` typed on its own runs
`python3 ~/.claude/scripts/resolve-dev-artifact-chain.py --task-id <id> --project-dir <root>`.
Retain that JSON even when `status == "fail"`: a failed continuation is
precisely where `errors[]` and the existing lane matrix are useful. Use the
existing paths named by `artifact_paths`, `report_paths`, `qa_inputs`, and
`lanes[]`, plus `docs/dev/close-report-<task-id>.md` when present. In singular
mode this is the existing parent chain; in fan-out mode it is every lane
ticket/context/dev/QA plus the parent canonical/completion. Never replace this with a singular
parent context/QA assumption or fabricate missing parent artifacts.

For legacy or non-`/dev` work where no resolver result is available, retain the
existing same-task parent context/dev-report/QA/close/completion lookup. Always
include the user's latest message or explicit focus string.

The dispatches of a cycle never write the spec; their section text stays in
their own reports, and this mode is what carries it into the spec. Read it
there: what was attempted and changed from the dev reports' `dev.tasks_completed`
(`description`, `rationale`, `changes`, files); the measured state, and on a fail
the gap and the next step, from the QA reports' `qa.spec_section_updates`
(`section_4`, `section_6`, `section_7`); the before-state from BA's context
(`root_cause_analysis`); and for an overnight pipeline the retro report's
`unresolved_issues`.

When updating an existing spec, append through `spec-write.py append`; never
overwrite prior cycles. Determine
the next cycle number as `max(existing "### Cycle N" headings across Sections
1-7) + 1`; if none exist, use Cycle 1.

Before appending the first new `### Cycle N` heading for this run, check whether
the spec file already contains `<!-- spec-continuation-of: <resolved-task-id> -->`
(substituting the actual task-id value — never a literal `${TASK_ID}` or
`<task-id>` placeholder). If that exact line is absent, write it as the very
first line of the new cycle block, before any section headings. If it is already
present, do not write a second copy (put it on the first line of the first
`append` block of the run). This marker is written exactly once per
(task-id, spec file) pair and must appear only in this continuation-spec mode,
never in temp-note mode.

Populate the per-cycle sections (Sections 2-8) as follows, one `append` per
section in the run's one Bash call, each block starting with its `### Cycle N`
heading:

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
fresh unless regenerated. Updating the spec changes its content, so
`scripts/resolve-spec-artifacts.py` reports its split stale (non-zero exit) to
`/dev`, `/dev-command` and `/dev-overnight` until `/spec` splits it again.

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

## Update mode (`--update`)

Use `--update` to append enrichment content to an existing spec's Section 5
without implying an unfinished `/dev` cycle. This mode never creates a new
`### Cycle N` heading and never touches Sections 1-4 or 6-9.

Resolution: `--update` requires an explicit `--spec <path>` naming an existing
spec file. If `--spec` is missing or the path does not exist, stop with an
error — do not fall back to the active `/dev` artifact chain and do not
invoke `scripts/resolve-dev-artifact-chain.py`. Update mode has no task-id or
dev-cycle reconciliation concept.

Append the enrichment content within Section 5 only, as a new `### 5.N`
subsection, through the one writer (`spec-write.py append --spec <path>
--section 5`, see Continuation-spec mode). If the target spec's Section 5
already uses numbered `### 5.N` headings, use `max(N) + 1`; otherwise follow
whatever convention that specific target spec already uses.

If the target spec already has `docs/dev/specs/<spec-id>/views/` or
`.claude/specs/<spec-id>/cp-state-*.json`, record in Section 8 that those
split views/checkpoints predate this update and must not be treated as fresh
unless regenerated — the same rule Continuation-spec mode applies for its own
appends, written the same way (`spec-write.py append --section 8`).

Do not write the continuation marker comment that Continuation-spec mode
writes at the start of a new cycle block; Update mode has no cycle block.

## Universal rules

- Do not duplicate existing artifacts. Reference specs, tickets, PRDs, plans,
  ADRs, issues, reports, commits, and diffs by path/URL/SHA.
- Keep it compact: no raw diffs, full logs, copied reports, secrets, or
  transcript dumps.
- The next action for unfinished dev work is a spec-backed `/dev --spec
  <path>`, not `/close` or `/commit`.
