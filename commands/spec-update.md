---
description: Update an existing spec, continue unfinished development, or write a temp session note.
argument-hint: "[--update --spec <path> | --continue | --temp] [--spec <path>] [what the next session should focus on]"
disable-model-invocation: true
---

# /spec-update — Continuation Spec Update

Turn unfinished work into a continuation spec that a fresh Claude Code or Codex
session continues with `/dev`. A compact temp note is written only on request,
for session continuity outside development. Adapted from the handoff skill of
`mattpocock/skills`.

## Mode selection

`--update`, `--continue` and `--temp` select one mode; `--update` together with
`--temp` stops with a mutual-exclusivity error, never a guess.

- `--update`: enrich an existing spec's Section 5 (Update mode).
- `--temp`: a session or bootstrap note in a temp file, only when asked for
  (Temp-note mode).
- Default (`--continue` is its alias): unfinished development after `/dev`,
  `/redev` or a failed `/close`, or a request to continue or improve the plan;
  the output is a spec under `docs/dev/specs/` (Continuation-spec mode).

## Continuation-spec mode

Resolve the target spec, first match wins:

1. `--spec <path>`.
2. The active `/dev` artifact chain: the validated singular context, or every
   fan-out `lanes[].context`; use `spec_path` / `spec_file` / `user_spec_path`
   only when all populated values agree. A fan-out cycle does not need, and
   this command must not create, a parent context merely to resolve the spec.
3. A new spec from `<HARNESS_ROOT>/templates/overnight-spec.md`, created at
   `${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}/docs/dev/specs/spec-<YYYYMMDD-HHMMSS>.md`
   by `spec-write.py create --spec <path>` with the populated template on stdin.

`<HARNESS_ROOT>/scripts/spec-write.py` is the one writer of
`docs/dev/specs/*.md`; never Write or Edit a spec file. `create --spec <path>`
takes the whole new file on stdin; `append --spec <path> --section <N>` (or
`<N>.<M>` for a `### N.M` subsection) adds the stdin text at the end of that
section, or in place of its lone `_Not yet populated._` line. Name the spec by
absolute path. A run's appends go in ONE Bash call, one `append` per section
chained with `&&`: the orchestrator gate refuses a sixth Bash call in a row, so
a call per section loses the last. A refusal stops the chain there; the
sections before it stay written, so run again only the refused append and those
after it.

```bash
python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/spec-write.py" append --spec /abs/path/docs/dev/specs/spec-<ts>.md --section 2 <<'SPEC_BLOCK' &&
### Cycle <N>
<content>
SPEC_BLOCK
python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/spec-write.py" append --spec /abs/path/docs/dev/specs/spec-<ts>.md --section 3 <<'SPEC_BLOCK'
### Cycle <N>
<content>
SPEC_BLOCK
```

Gather the sources from the active task-id when available. For `/dev` work take the
`ARTIFACT_CHAIN` the invoking command (`/dev`, `/dev-command`, `/close`,
`/commit`) already holds from its one chain call, verbatim; a `/spec-update`
typed on its own runs
`python3 "<HARNESS_ROOT>/scripts/resolve-dev-artifact-chain.py" --task-id <id> --project-dir <root>`.
Keep that JSON even when `status == "fail"`: a failed continuation needs
`errors[]` and the lane matrix. Read the existing paths named by
`artifact_paths`, `report_paths`, `qa_inputs`, and `lanes[]`, plus
`docs/dev/close-report-<task-id>.md` when present: in singular mode the parent
chain, in fan-out mode every lane ticket/context/dev/QA plus the parent
canonical/completion. Never assume a singular parent context/QA and never
fabricate missing parent artifacts. Without a resolver result (legacy or
non-`/dev` work), look up the same-task parent context, dev-report, QA, close
and completion artifacts. Always include the user's latest message or explicit
focus string.

No dispatch of a cycle writes the spec; its section text stays in its report,
and this mode carries it over. Read what was attempted and changed from the dev
reports' `dev.tasks_completed` (`description`, `rationale`, `changes`, files);
the measured state, and on a fail the gap and next step, from the QA reports'
`qa.spec_section_updates` (`section_4`, `section_6`, `section_7`); the
before-state from BA's context (`root_cause_analysis`); and for an overnight
pipeline the retro report's `unresolved_issues`.

Add each cycle with `spec-write.py append`; never overwrite a prior cycle. The
next cycle number is the highest existing `### Cycle N` heading across
Sections 1-7, plus 1 (Cycle 1 when none exist). The first `append` block of a run starts with the line
`<!-- spec-continuation-of: <resolved-task-id> -->` (the real task-id, never a
placeholder) unless the spec already holds that exact line; it is written once
per (task-id, spec) pair, in this mode only.

One `append` per section, each block starting with its `### Cycle N` heading:

- Section 2: what was attempted and why it did not finish.
- Section 3: changed files or artifact references, not raw diffs.
- Section 4: current measured state, QA result, close dissent.
- Section 5: a `### 5.N` block instead of a Cycle heading, only when a
  remaining acceptance criterion is new or materially refined. A newly created
  spec's Section 5 holds the original user-facing goal if known plus the
  remaining criteria.
- Section 6: the gap between the current state and done.
- Section 7: the concrete actions the next `/dev` run takes to deliver the
  whole outcome still open (a failed cycle's unfinished requirement, or the
  improvement the user just asked for); none of it is left for a later run.
- Section 8: traps, stale assumptions and warnings for the next agent. If the
  spec has `docs/dev/specs/<spec-id>/views/` or
  `.claude/specs/<spec-id>/cp-state-*.json`, say here that they predate this
  update and are not fresh until `/spec` splits the spec again:
  `scripts/resolve-spec-artifacts.py` reports a changed spec's split stale to
  `/dev`, `/dev-command` and `/dev-overnight`.
- Section 9 (Design & Evidence References) belongs to `/spec`; leave its lines
  as they are.

Output the spec path and next command (unfinished dev work always continues as
`/dev --spec`; the rule is held in `commands/dev.md` Step 17, Workflow update):

```text
Continuation spec: <spec_path>
Next: /dev --spec <spec_path>
```

## Temp-note mode (`--temp`)

Make a private directory with `mktemp -d -t update-XXXXXX` and Write the note
as the new file `update.md` in it (the write guard refuses a Write over an
existing file, even an empty one `mktemp` made). Keep it out of the repo unless
the user passes `--path <path>`, a file that does not exist yet.

```markdown
# Update — <short focus>

Generated: <ISO-8601>
Next focus: <what the next session should do>
Current stage: <spec|dev|close|commit|push|ad hoc>
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

Free-form text in `$ARGUMENTS` is the next-session focus: tailor the Resume
prompt, Next actions and Suggested skills around it.

## Update mode (`--update`)

Appends enrichment to an existing spec's Section 5 with no dev-cycle
semantics: no `### Cycle N` heading, no continuation marker, and no section but
5 (plus the Section 8 note below). `--spec <path>` must name an existing spec
file; a missing flag or path stops with an error. There is no auto-resolution:
do not fall back to the `/dev` artifact chain or call
`scripts/resolve-dev-artifact-chain.py`, since update mode has no task-id.

Append the content as a new `### 5.N` subsection through the writer
(`append --spec <path> --section 5`, see Continuation-spec mode): `max(N) + 1`
when Section 5 already uses numbered `### 5.N` headings, else that spec's own
convention. If the spec has split views or checkpoints (Section 8 bullet of
Continuation-spec mode), append the same note to Section 8 in the same Bash
call, saying they predate this update.

## Universal rules

Reference existing specs, tickets, PRDs, plans, ADRs, issues, reports, commits
and diffs by path, URL or SHA; keep it compact, with no raw diffs, full logs,
copied reports, secrets or transcript dumps.
