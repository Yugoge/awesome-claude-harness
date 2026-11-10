---
description: Commit session changes via changelog-analyst subagent
disable-model-invocation: true
---

# /commit

Commits a task's session changes through the `changelog-analyst` subagent. Step 3's one disposition
call says whether the task's cycle is complete and closed; an incomplete or unclosed task is
completed first (its gaps go back to the dispatches that owe them, its close runs as `/close`
Steps 1-2). `--bulk` skips Step 3. Normal mode admits every task-owned path only after partitioning
it across an explicit supported-repository set; the control checkout and `<HARNESS_ROOT>` are
supported without a project-root override.

## Usage

```
/commit [<task-id>] [--force] [--bulk] [--dry-run] [--codex] [--auto]
```

| Flag | Meaning |
|------|---------|
| `<task-id>` | Optional when the session identifies the active cycle (Step 2: ambiguity is asked, never guessed). An explicit task-id that names a task is authoritative (Step 2 checks it). Unused with `--bulk`; not allowed with `--auto`. |
| `--force` | No-op alias of the normal path: Step 3 and Step 6 both still run. Its one effect is Step 4's audit-log append. |
| `--bulk` | Batch mode: group by task-id then subsystem, commit coherently, flag orphan files separately. Skips Step 3; keeps the Step 6 QA gate. |
| `--dry-run` | Step 3 completes the cycle as a real run does; Steps 5-6 plan and review; print the plan and the QA verdict; commit nothing. |
| `--codex` | Step 6's QA adds a Codex round on the planned per-file changes (each `PLAN_GROUPS` path vs HEAD). Without it QA reviews once itself. |
| `--auto` | Walk every `commit_pending` parent task-id, one at a time, through Steps 3-8 (`--auto` mode below). Not `--bulk`. |

`/commit` is human-only: `disable-model-invocation: true` plus the `Skill(commit:*)` deny in
`settings.json`.

## Step-by-step workflow

### Step 1: Parse arguments

Parse `$ARGUMENTS`: strip each of `--force`, `--bulk`, `--dry-run`, `--codex` and `--auto` into
`FORCE`, `BULK`, `DRYRUN`, `QA_CODEX` and `AUTO` (true when present, else false). The remaining
token, if any, is `TASK_ID`.

**`--auto` flag combination**: `--auto` takes no task-id, `--force` or `--bulk`
(`validate_auto_flag_combination` in `scripts/dev-lifecycle.py`). When `AUTO=true` and any of the
three is set, take no action and ask one AskUserQuestion: header `Flags`, question `--auto takes
no task-id, --force or --bulk: which /commit should run?`, options:
- `--auto`: every `commit_pending` parent, each through Steps 3-8;
- `<task-id> only`: the task-id typed, else the first parent Step 2's `list-actionable` call
  lists, alone through Steps 3-8;
- `--bulk` (only when `--bulk` was typed): the batch sweep, Steps 5-8, with no Step 3.

Continue in this turn with the mode the answer names (`--force`, a no-op, is dropped; `--dry-run`
and `--codex` stay as typed). A legal `--auto` skips Step 2: the `--auto` mode section binds
`TASK_ID` once per discovered parent.

### Step 2: Resolve task-id (unless --bulk or --auto)

If `BULK=false` and `AUTO=false`:
- A supplied `TASK_ID` is authoritative when it names a task: a file under `docs/dev/` carries
  it in its name (the task's own report or ticket, or a lane's of that parent), or, typed as a
  path, that file exists. Check it before Step 3 (that look verifies the typed id; it picks no
  task, so it is not the scan the next bullet forbids). One that names no task (a mistyped id) is
  not authoritative, and no conversation candidate replaces it unasked: ask the `Which task`
  question below, as `close.md`'s Task-id resolution asks it for a path that does not exist, and
  bind the answer. The `/commit` Stop reads the same rule (`_targets` in the command Stop gate,
  `stop-command-gate.py`): a typed id that names no task gives way to the task this `/commit`'s
  dispatches name, and with none dispatched the Stop holds, naming the typed id.
- Otherwise (no `TASK_ID` supplied) infer it from the conversation: the parent task-id of the
  active `/dev` or `/do` cycle, or of the `/close` that just ran in this session. There is no
  filesystem scan and no default-to-newest (a report mtime scan picks up other sessions'
  reports). Inference succeeds
  only when the conversation names exactly one candidate: Step 3 completes and closes whatever
  task it is given, so with two or more candidates, or any doubt, do not guess.
- No unambiguous candidate: ask one AskUserQuestion, header `Task`, question `Which task should
  /commit land?`, options: up to three parents that
  `python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/dev-lifecycle.py" list-actionable --next-action commit --project-dir "<PROJECT_ROOT>"`
  lists (the first word of each line), then those `--next-action close` lists (Step 3 closes them
  first), each labelled with its task-id, plus `/commit --auto`. Bind `TASK_ID` to the answer, or
  run `--auto` mode. When neither list names a parent, print `No task to commit: dev-lifecycle.py
  lists no commit_pending or close_pending parent.` and end.

If `BULK=true`, `TASK_ID` may stay empty.

### Routes: each gap or finding goes back to the dispatch that owes its artifact

Every gap Step 3's disposition call prints and every finding a later step names (Step 5's
late-repair state `invalid` or an empty plan, a `COMMIT: REJECT` in Step 6, a changelog-analyst
failure in Step 7) has an artifact path. Its owner is the declaring-dispatch reader's answer on
that path, one Bash call, run as written with the path for `<path>`:

```bash
python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/lib/obligation.py" declaring-dispatch --task-id "$TASK_ID" --project-dir "<PROJECT_ROOT>" --path "<path>"
```

It reads this task's dispatch records in every session the project's transcript store holds
(`hooks/lib/obligation.py` `declaring_dispatch`), so a `/dev` or `/close` of an earlier session is
found. Act on its JSON answer:

- `source` `dispatch` (its obligation declares the path), `lane` (an artifact of the whole
  fan-out, as its canonical aggregate, which the lane-completeness hook writes when a lane's dev
  writes its report; the main agent runs no aggregator) or `writer` (a product file: the dispatch
  whose own tool calls wrote it): dispatch it again, a fresh synchronous Agent call
  (`run_in_background: false`) with the same `subagent_type`, `task_id`, `lane` and obligation and
  a fresh `dispatched_at` (G1 refuses a re-dispatch whose obligation differs), its prompt naming
  the gap or finding.
- `source` `todo_step` (no dispatch has declared the path yet): with a `template`, a fresh
  synchronous dispatch of that step's role under the same task id, from the template of the
  answer's `step` in `commands/<command>.md` with the template's obligation; with none, the step
  is the main agent's own (as `/dev` Step 11): run it yourself under the same task id.
- A `/do` task's do-report, and a file the answer names no owner for (`null`) in a `/do`
  task (its main agent wrote it): dispatch dev under the same task id with the obligation
  `<obligation v="1">{"task_id": "<TASK_ID>", "role": "dev", "pipeline": "do", "profile": "singular", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this call>", "artifacts": [{"kind": "json", "path": "docs/dev/dev-report-<TASK_ID>.json", "schema": "dev-report.v2", "identity": {"task_id": "<TASK_ID>"}}]}</obligation>`
  to complete the `/do` work, never `/do`'s own steps; its dev-report, which G2 verifies at dev's
  stop, concludes a `/do` task whose do-report is not `completed` (Step 3's call takes it), and
  the `/commit` orchestrator writes no report. That dev-report lists, beside the files dev wrote,
  each file the do-report lists (dev names each in one of its Bash commands so G2 counts it);
  nobody rewrites the do-report, whose producer's `/do` has ended.
- `null` in a commit-QA round, and a commit-QA finding that cites no artifact: the path becomes
  that round's own report, `docs/dev/commit-qa-report-<TASK_ID>.md`, whose QA dispatch runs again
  (Step 6) and names a path, routed as above.
- `null` for any other path: no dispatch or request exists to re-run. Ask one AskUserQuestion
  (header `Request`) what the cycle should deliver, naming the task and the artifact; the options
  are the requests the task's own artifacts state (its ticket or user-requirement file) and up to
  two parents `dev-lifecycle.py list-actionable --next-action commit` lists (`Commit <task-id>
  instead`); then dispatch dev under the same task id for the answer.

There is no default role. Once the dispatch returns, run again the one check that named the path;
a gap or finding it names again is routed the same way, with no round cap.

A task with a late-repair run record (`docs/dev/late-repair-run-<TASK_ID>.json`) records a BA, dev
or QA stage that was dispatched again when it returns, as `/close` Step 0 records one:
`python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/late-repair-controller.py" record-stage --task-id "$TASK_ID" --project-dir "<PROJECT_ROOT>" --stage <ba|dev|qa> --report-path <path> --repair-run-id <the run record's repair_run_id>`.
A recorded dev report clears finalize's outcome: Step 5's late-repair state is then `invalid` and
`/close` Step 0's finalize runs again, so the plan never comes from an effective report older than
the dev report.

### Step 3: Resolve the disposition; complete the cycle when incomplete (skip if BULK=true)

`--force` never skips this step, and `--dry-run` completes the cycle here exactly as a real run
does: only the commit itself is previewed. One Bash call binds the close-report's path (used
inside the call only), prints its mtime in epoch seconds (nothing when there is no file), and
prints the task's disposition at the close stage, the dev stage plus a close-report whose last
non-empty line classifies `yes`:

```bash
CLOSE_REPORT="$(bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/resolve-close-report.sh" "$TASK_ID")" || true
stat -c %Y "$CLOSE_REPORT" 2>/dev/null || stat -f %m "$CLOSE_REPORT" 2>/dev/null || true
python3 "${CLAUDE_HOME:-$HOME/.claude}"/scripts/resolve-dev-artifact-chain.py --disposition --stage close --task-id "$TASK_ID" --project-dir "<PROJECT_ROOT>"
```

Its output is data, read verbatim:

- `DISPOSITION=chain_pass`: go on to check 3, then Step 4.
- `DISPOSITION=incomplete`: complete the cycle, then run this call again, until it prints
  `chain_pass`. Each `GAP artifact=<path> problem=<code>: <message> lane=<lane>` line on an
  artifact other than the close-report is a dev-stage gap: route it (Routes). The gap on the
  close-report is the close stage's: once no dev-stage gap is left, run `commands/close.md`
  Steps 1-2 for this task id, as `/close` runs them (the three inspectors, then close QA rounds
  until one lands `CLOSE: YES*`; close QA writes the close-report).
- A non-zero exit with no `DISPOSITION` line is an instrument failure (its reason on stderr),
  never a disposition: run the call once more; if it fails again, print one line
  `OPERATION_STALLED: <the error>`, record it as the session's next harness-repair item, and go no
  further: no grant, no dispatch, no commit.

The same output carries a `/dev` task's chain data fields (`mode`, `lanes`, `report_paths`,
`canonical_dev_report`, `artifact_paths`, `commit_whitelist_artifacts`, `qa_inputs`) on its
`CHAIN=` line: each run binds `ARTIFACT_CHAIN` to that JSON verbatim (empty for a `/do` task,
whose run prints none), and `close.md` Steps 1-2, Step 5 and Step 7 read the latest run's.
No second chain call is made.

**Check 3 — close-report age (advisory, never aborts)**: if the `chain_pass` run's mtime is older
than 86400 seconds (24 h), print `Close-gate: WARNING — close-report for task ${TASK_ID} is older
than 24h (mtime: <mtime>). Proceeding — staleness is advisory. Re-run /close if the tree has
drifted since this approval.` and continue. Age alone never blocks a commit: Step 6 reviews every
planned file's actual change vs HEAD on every invocation.

### Step 4: Deprecated --force usage audit (only when FORCE=true)

`--force` bypasses nothing; this step is a best-effort audit log. If `FORCE=true`, create
`${CLAUDE_CONFIG_DIR:-$HOME/.claude}/logs/` and append a line with ISO timestamp, task-id and
`mode=force` to `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/logs/commit-overrides.log` (proceed if the
append fails), then print: `WARNING: --force is deprecated and is now a no-op alias of the normal
path — no gate is bypassed. Audit entry written to
${CLAUDE_CONFIG_DIR:-$HOME/.claude}/logs/commit-overrides.log.`

### Step 5: Write commit grant(s) after resolving the repository plan

**BULK=true.** The human's `/commit --bulk` prompt makes
`hooks/userprompt-bulk-commit-capability.py` mint the multi-use bulk-commit sentinel (an LLM cannot
self-invoke this slash command, so the prompt is the trust root). Write nothing and never write it
with Bash: the hook is the sole minter. Go to Step 6: `--bulk` and `--force` are not exempt from
the QA gate. The privilege guard decides on the sentinel at each auto-bulk commit.

**BULK=false.** One Bash call (a fresh shell: nothing carries over in variables) resolves the task's
report and builds the repository plan, the attribution slice and the manifest inputs:

```bash
python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/steps/commit-plan.py" --task-id "$TASK_ID"
```

It prints one JSON object whose keys the script's header defines. Steps 5-7 read these:
- `repository_plan`: the plan `scripts/resolve-commit-repos.py` builds from `task_report` over the
  supported repositories, the control checkout and `nested_repo` (the real harness checkout): command-owned
  admissions, never values read from the report, `CLAUDE_PROJECT_DIR` or a user-supplied root
  override. Each owned path goes to its actual Git root (the deepest supported repository, never an
  unadmitted nested checkout) in an ordered entry binding `repo_root`, `branch`, `expected_head`,
  the owned paths and whether the control repo owns cycle artifacts.
- `late_repair` (`{state, path}`, used verbatim) and `task_report` (the plan's one source): state
  `verified` makes the effective report finalize recorded the source, `none` keeps the report Step 3's
  disposition plans from, `invalid` (State C) names the artifact of a finding.
- `attribution_log`: the write-time attribution journal's slice for the plan's owned paths, the
  fact-based staging source `agents/changelog-analyst.md` reads beside the dev-report's own ledger;
  `no_events[]` lists paths the journal does not cover, for which the analyst's backup investigation
  applies, never a block.
- `control_root`, `nested_repo`, `close_report`, `session_id`, `manifest_path` and `files_at_dispatch`
  feed Step 7's prompt and the manifest below.

Two outcomes are findings (Routes), each followed by this call run again: `late_repair.state`
`invalid` (a finding on `late_repair.path`), and a `null` `repository_plan` (a malformed report,
an unattached branch, an absent HEAD, an unsupported owner, an identity mismatch: a finding on
`task_report`). It is never an empty plan or "nothing to commit"; no grant is issued and nothing is
staged while it holds.

**Write the dispatch-snapshot manifest before minting any grant.** Write `manifest_path` with the
Write tool: JSON holding `session_id`, `task_id`, `dispatched_at` (now, UTC), the complete
`repository_plan` (with its report digest), the exact `ARTIFACT_CHAIN` JSON (when non-empty) and
`files_at_dispatch`. With no session id (`session_id` empty) print `OPERATION_STALLED:
write-commit-grant.py has no session id (CLAUDE_CODE_SESSION_ID and CLAUDE_SESSION_ID unset)`,
record it as the session's next harness-repair item, and dispatch nothing. `write-commit-grant.py`
refuses to mint without the manifest: a live `/commit` user-intent sentinel alone is not enough,
because a bare `/commit` first line lights it without running this pipeline. The minter also requires, through
`hooks/lib/commit_pipeline.verify_pipeline_dispatch()`, a live manifest for this session and task
whose plan admits the exact `--repo-root` at its live branch and HEAD, whose `report_sha256`
matches the actual bytes of the cycle report it cites, and an existing close-report. A refusal
names the one missing piece: rebuild that artifact and mint again, never work around it.

Write **one single-use commit grant per `repository_plan.repositories[]` entry**, run as written
with that entry's `repo_root` for `$PLANNED_REPO_ROOT`:

```bash
python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/write-commit-grant.py" \
    --task-id "$TASK_ID" --repo-root "$PLANNED_REPO_ROOT"
```

The writer stamps timezone-aware ISO-8601 `created_at` and `expires_at` on a 30-minute window and
prints the grant path; never write a grant by hand (the privilege guard reads an epoch value as
already expired). Never omit `--repo-root`, flatten the plan into one grant or infer repositories
from dirty status: each grant is a single-repository capability, and a report cannot mint admission
for a new repository. The planner and the writer both capture `repo_root`, `branch` and
`expected_head`, and the privilege guard re-checks all three against live Git state when each
commit runs. Verify that the writer's captured values equal the plan entry; any mismatch revokes
all grants for this task/session, then the plan is rebuilt (this step), the grants re-minted and
re-verified. The writer reads `CLAUDE_CODE_SESSION_ID`, else `CLAUDE_SESSION_ID`, and exits 2 when
neither is set (print the `OPERATION_STALLED` line above).

**Dry-run and the grants**: a dry-run leaves HEAD, worktree bytes and index bytes identical, but
mutates and restores the index, and this step mints real grants before it runs. They are revoked
at every unstage pause, at the `--dry-run` preview end and when the plan computed OK with nothing
pending; each is single-use, bound to repo + branch + `expected_head`, never consumed by
changelog-analyst's `DRYRUN` guard, and the privilege guard blocks agent commits independently.
Rationale: `docs/reference/commit-dryrun-close-gate-ruling.md`.

**Transaction boundary**: Git has no cross-repository atomic commit. Normal mode is an ordered,
non-atomic transaction: all repositories are planned and QA-reviewed before the first commit, each
then gets its own lock/grant/CAS/commit/token transaction, and a later failure is surfaced as
`partially_committed` with per-repository results. Never claim cross-repository atomicity,
silently roll back a created commit, or hide a partially completed transaction.

### Step 6: Pre-commit QA review gate

A QA agent reviews what is actually about to be committed (each planned file's change vs HEAD) and
may block the commit. It is an independent second reviewer on top of changelog-analyst's staging
judgment: `--bulk` skips `/close`'s gate, and even a normal commit's file changes deserve a fresh
adversarial check for junk, secrets and scope contamination. It reads the file changes, not the
dev-report. It always runs, for `BULK=false` and `BULK=true`; `--force` does not skip it.

**Planning phase (internal dry-run, plan only).** Dispatch `changelog-analyst` (Agent,
`subagent_type: changelog-analyst`) with Step 7's prompt but `DRYRUN=true`, whatever the user's
`--dry-run`. Under `DRYRUN=true` it classifies, stages the candidate set into the index and stops
before the commit: no commit, no push-gate token, no recovery commit, no use of the Step 5 grant
(its `DRYRUN` guard, `agents/changelog-analyst.md`). Capture from its output:
- `PLAN_GROUPS`: the per-proposed-commit groups, each `{repo, commit_message, files[]}` (bulk
  yields several). Keep the group boundaries: QA needs them to detect cross-task mixing.
- `PLAN_FILES`: the union of the groups' files, per repo.
- If the dry-run reports `nothing_to_commit` / an empty plan, compare it to the plan first. If the
  plan computed OK, its owned paths exist and they are not already landed, the disagreement
  between the owned-edit declaration and the live bytes is a finding on the dev report (Routes),
  not a silent no-op; rerun the planning phase after the fix. Only when the plan computed OK and
  the paths are already landed (or it lists no owned path), print `Nothing to commit (plan
  computed OK; dry-run found no pending change) — QA gate skipped.` (never after a failed plan
  computation), revoke the Step 5 grant (Grant hygiene below), and go to Step 7, which also
  no-ops. Dispatch no QA on an empty plan.

**Review phase (vs HEAD, staging-independent).** QA reads each planned file's change directly
against HEAD, not through `git diff --cached`: in multi-group `--bulk`, changelog-analyst stages per
subsystem group and Phase 4 unstages cross-group files each iteration, so after the dry-run only
the last group stays staged, and a `--cached` review would skip every earlier group while all
groups still enter `QA_APPROVED_FILES` and get committed. Dispatch ONE QA subagent (Agent,
`subagent_type: qa`) with `codex_required: <QA_CODEX>` and `PLAN_GROUPS` in the prompt, which
instructs QA as follows:

```
You are the pre-commit QA gate. Review ONLY what is about to be committed — the files
in PLAN_GROUPS — by reading each file's actual change, not the dev-report.

codex_required: <QA_CODEX>
Proposed commit groups (preserve boundaries): <PLAN_GROUPS>
  (each = {repo, commit_message, files[]} — one intended commit)
TASK_ID: <TASK_ID or "bulk">   BULK: <true|false>

<obligation v="1">
{
  "task_id": <"$TASK_ID" when BULK=false, else null>,
  "lane": null,
  "lane_set": null,
  "role": "qa",
  "pipeline": "commit",
  "profile": "commit-qa",
  "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this dispatch, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>",
  "artifacts": [
    {"kind": "markdown", "path": "docs/dev/commit-qa-report-<TASK_ID or \"bulk\">.md",
     "identity_anchor": "<TASK_ID or \"bulk\">",
     "terminal_line_regex": "^COMMIT: (APPROVE|REJECT)"}
  ]
}
</obligation>

For EVERY path in EVERY group, review its actual change directly; the staging state is no
source (in multi-group bulk only the last group is left staged). Gather both sources and
review each that is non-empty:
  - DIFF: `git -C <repo> diff --text HEAD -- <path>`. `--text` forces a content patch even
    when `.gitattributes` marks the path `-diff`. "Binary files … differ" means a real binary
    blob: do not text-review it, judge it under rejection rule 1 or 4 (intended asset, or
    accidental/junk binary).
  - CONTENTS: if `<path>` exists on disk, read it too.
  Both can be non-empty at once, e.g. a path deleted at HEAD yet recreated on disk (`D` + `??`:
  the diff shows only the old deletion), or a rename/copy's new side an earlier bulk group left
  unstaged (untracked: empty diff, but the file exists). A rename/copy is two entries: its OLD
  and its NEW path.
Judge by intelligent review — NEVER a hardcoded junk list. REJECT the commit if any of:
  1. Transient / non-authored byproducts (runtime/session state, caches, registries,
     scratch/temp outputs, generated indexes, build products) — by what the file IS,
     regardless of which folder it sits in.
  2. Secrets / sensitive content (credentials, keys, tokens, .env material).
  3. Scope contamination — files unrelated to TASK_ID (BULK=false); or, WITHIN ONE proposed
     group, files belonging to two different task-ids / unrelated subsystems (BULK=true).
  4. Obvious correctness/quality defects in the diff (syntax-broken code, committed debug
     leftovers, accidental large/binary blobs).

When codex_required is true, after your own review run ONE Codex round via Skill(codex) on the
SAME per-file material (the HEAD diffs and new-file contents, not the staged set) and your
draft verdict. Codex calls follow templates/prompt-includes/codex-consultation.md.
A Codex REJECT is a finding, not a verdict. Classify every Codex finding as in_scope_real_bug,
in_scope_minor, out_of_scope or nitpick, with a one-line reason. Only a blocker or high
finding (a secret, junk, broken syntax) makes you reject; style, edge and nitpick findings go
in the report and never decide the verdict. QA's own review decides it. The secret and
residue guarantees stay with the pre-commit guard (hooks/git-hooks/pre-commit) and the
privacy engine (scripts/check-public-core.sh), which do not depend on Codex.
If Codex gives no usable verdict line, ask it once more for that line; if that fails too, or
on a quota or timeout failure, your own verdict stands, with a note of the failure in the
report. When codex_required is false, review once yourself and do not invoke Codex.

Write a transcript to docs/dev/commit-qa-report-<TASK_ID or "bulk">.md: per-file findings,
each Codex finding with its classification and reason, and codex_status (ok, failed_quota,
failed_timeout or failed_parse) when Codex ran. Its LAST line is EXACTLY one of:
  COMMIT: APPROVE
  COMMIT: REJECT - <one sentence naming the offending file(s) and why>
That line is your verdict; nothing else carries it.
```

**Decision phase.** The verdict is the last non-empty line of
`docs/dev/commit-qa-report-<TASK_ID or "bulk">.md`, read verbatim: the producer-stop gate (G2)
checked that file and that line at the QA subagent's own stop.

**Grant hygiene** (`BULK=false`, at every unstage pause, REJECT routing and the `--dry-run` preview
end): besides unstaging, revoke the Step 5 commit grant, so a gate under repair never leaves live
commit authorization lingering (30-minute TTL; never hold a live grant across a producer repair:
bytes and plan changed, so re-mint by re-entering Step 5):

```bash
python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/write-commit-grant.py" --task-id "$TASK_ID" --revoke-only
```

Skip the revoke when `BULK=true`: bulk wrote no per-task grant (Step 5's sentinel expires on its own
30-minute TTL) and `TASK_ID` is empty, so the writer would exit 2. Only a `COMMIT: APPROVE` on the
real-commit path keeps the grant: Step 7 consumes it.

- `COMMIT: REJECT`: a verdict on the product, not a broken artifact. Print the verdict and the
  offending files and leave the tree clean: per repo, unstage only currently-staged paths,
  computed rename-aware. Run `git -C <repo> diff --cached --name-status -z -M`; a plain staged path
  goes in the unstage set if it is in `PLAN_FILES`; a staged `R`/`C` entry adds BOTH its old and new
  paths if EITHER endpoint is in `PLAN_FILES` (the analyst may list only the new path, and a
  single-endpoint unstage leaves e.g. `D old` staged). Unstage with `git -C <repo> restore --staged
  -- <those>` (unborn repo: `git -C <repo> rm --cached -- <those>`). Pass no planned file that is not
  staged: in multi-group bulk Phase 4 already unstaged the earlier groups, and an unstaged pathspec
  errors out and leaves the last group staged. Then revoke the grant. Do not go to Step 7 and do not
  commit (`--force` does not override this). Then:
    1. **Findings to their owners (Routes).** Each offending file and its reason (from the
       `commit-qa-report` and its verdict line) goes to the dispatch that declared the file or, for
       a product file, the dispatch whose own tool calls wrote it; a finding that names no file, or
       only a file no dispatch of the task wrote, goes to that round's own report, whose QA
       dispatch runs again to name a path. QA never edits the subject.
    2. **A fresh round.** After the owners' fixes, rebuild the plan (Step 5), rerun the planning
       dry-run, and dispatch a NEW QA subagent (a fresh dispatch; no prior verdict or finding in its
       prompt) that re-judges the actual changes against HEAD. A further `COMMIT: REJECT` repeats
       this routing; the loop ends on `COMMIT: APPROVE`, with no round cap.
- `COMMIT: APPROVE`:
  - Record `QA_APPROVED_FILES` = `PLAN_FILES` (the exact reviewed set, per repo): the commit
    ceiling Step 7 must not exceed (TOCTOU guard).
  - With `--dry-run` (`DRYRUN=true`): print the plan and `QA: APPROVE`, unstage the dry-run-staged
    set (as in the REJECT branch), revoke the grant, and end the invocation with the preview
    delivered: the requested end state; no real commit.
  - Otherwise go to Step 7 for the real commit.

### Step 7: Dispatch changelog-analyst

Use the Agent tool with `subagent_type: changelog-analyst` and this structured prompt. Substitute
`<CONTROL_ROOT>`, `<NESTED_REPO>`, the plan and the attribution slice from Step 5's `control_root`,
`nested_repo`, `repository_plan` and `attribution_log`, and `<ARTIFACT_CHAIN>` from Step 3's
`CHAIN=` line (in bulk mode, `CONTROL_ROOT` is the git top level of the working directory and
`NESTED_REPO` the harness checkout). Normal mode's repository authority is the plan; its `/dev`
cycle-artifact whitelist is the chain's `commit_whitelist_artifacts`.

```
CONTROL_ROOT=<CONTROL_ROOT>
NESTED_REPO=<NESTED_REPO>
REPOSITORY_PLAN=<Step 5's repository_plan, exact; empty only in bulk mode>
ARTIFACT_CHAIN=<the chain data fields of Step 3's disposition call; empty only for bulk or source=do>
ATTRIBUTION_LOG=<Step 5's attribution_log, exact; the empty object ({"results":[],"no_events":[],"discarded_lines":[]}) in bulk mode>
TASK_ID=<resolved task-id or empty for bulk>
BULK=<true|false>
DRYRUN=<true|false>
FORCE=<true|false>
QA_APPROVED_FILES=<the Step 6 decision-phase QA-approved file set, per repo; non-empty whenever the planned file set was non-empty>

<obligation v="1">
{
  "task_id": <"$TASK_ID" when BULK=false, else null>,
  "role": "changelog-analyst",
  "pipeline": "commit",
  "profile": <"commit-landing" when BULK=false, else "commit-bulk">,
  "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this dispatch, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>",
  "artifacts": [
    {
      "kind": "response_block",
      "begin": "--- CHANGELOG-ANALYST-STATUS-BEGIN ---",
      "end": "--- CHANGELOG-ANALYST-STATUS-END ---",
      "format": "json",
      "schema": "changelog-status.v1",
      "repo_roots": <the JSON array of REPOSITORY_PLAN.repositories[].repo_root, in order, when BULK=false, else null>
    }
  ]
}
</obligation>

You are the changelog-analyst subagent. Execute the commit workflow as specified
in your agent definition (agents/changelog-analyst.md). Use the variables above
to guide your behavior.

Disclosures: when `BULK=false` and the close-report consumed for `TASK_ID` (Step 5's
`close_report`, or its late-repair effective-report equivalent) contains a non-empty
`## Disclosures` section, append to the commit message body a `Disclosures: <n>` line followed
by up to 10 items in the same three-element format (`[code] path: problem | 归因: role(lane) |
修复: action`); beyond 10 items, write "see close-report" instead of listing the rest. Do NOT
create a separate file to duplicate the list. The `归因`/`修复` labels are a verbatim pass-through
of `commands/close.md`'s own `## Disclosures` line format (its field labels stay in Chinese):
do not translate them here, and if the convention is ever translated, do it in `close.md`
first and update this quoted copy to match.

Constraints (the staging, commit-message, per-repository result and push-gate token rules are
those of the agent definition; this prompt adds only these):
- In normal `/dev` mode the base cycle-artifact whitelist is exactly
  `ARTIFACT_CHAIN.commit_whitelist_artifacts`, the data of the disposition that admitted the task:
  it admits validated lane artifacts in fan-out mode and never invents optional parent artifacts.
- `QA_APPROVED_FILES`, when non-empty, is the commit CEILING (TOCTOU guard): re-classify
  normally, intersect with it, stage and commit ONLY files in both. A fresh classification that
  yields a file outside it (the working tree changed since QA reviewed) is not committed; if the
  divergence is material (an approved file vanished, or a new non-approved candidate appeared that
  you would otherwise commit), ABORT with `failure_code: scope_violation`.
- BULK mode: every commit message begins with `auto-bulk: end-of-cycle commit for
  <current-branch>` (the actual branch of the repo being committed). The privilege guard requires
  the Step 5 bulk sentinel for that prefix. Never use it when BULK=false.
```

Wait for changelog-analyst to complete and echo its final status to the user.

#### Changelog-analyst result handling and retry protocol

Read the structured status block verbatim (`agents/changelog-analyst.md` § Structured Final Status
Output): the producer-stop gate (G2) validated it at the analyst's own stop against
`changelog-status.v1` and, in normal mode, its repository roots and order against the obligation's
`repo_roots`. It carries `commit_status`, `repository_results[]`, and when applicable
`failure_code`, `failure_reason` and `auto_bulk_commits[]`.

#### status = `committed`
Every planned repository reached `committed` or `nothing_to_commit`. Continue to Step 8.

#### status = `partially_committed`
At least one repository commit landed and a later one failed. Print the ordered
`repository_results`, the first failure and `remaining_repos`; claim no rollback or
cross-repository atomicity; do not run Step 8 yet. Revoke all still-unused grants for this
task/session, then continue with the remaining repositories in order: rebuild the plan for only the
still-dirty owned material, re-mint fresh grants, rerun the planning dry-run and QA, re-dispatch.
Repositories already clean must return `nothing_to_commit`: they get no synthetic recovery commit
because another repository remains dirty.

#### status = `nothing_to_commit`
Print: `WARNING: changelog-analyst found nothing to commit after exclusions (plan computed OK).
Verify the task cycle produced staged changes.` If the result carries
`push_gate_reconciliation_declined`, also print: `WARNING: HEAD <sha> has no push-gate token and
could not be attributed to this session (<reason>); /push stays blocked for this session.` Do not
retry and do not tokenize HEAD another way: the refusal is a rejected operation. Report it in one
line, `OPERATION_STALLED: push-gate token for HEAD <sha>: <reason>; /push stays blocked for this
HEAD until a human pushes it or its originating session re-runs /commit` (`agents/changelog-analyst.md`
§ Push-gate reconciliation, "The accepted residual"); no owner decision changes it here, so nothing
is asked. The landed commit stands; only the push gate waits. Continue to Step 8 (its skip
conditions apply when no real commit occurred).

#### status = `push_gate_reconciled`
No new commit: a prior commit attributed to this task was at HEAD without a push-gate token, and
changelog-analyst wrote the missing token for it. Say "attributed to", not "this task's own":
attribution is by journal entry, and a narrow same-parent race lets a peer's commit be the one
reconciled. `agents/changelog-analyst.md` § Push-gate reconciliation holds the trigger conditions
and the canonical list of routes that reach this state; do not restate one route as the cause.
Print: `INFO: no new commit; wrote the missing push-gate token for existing commit
<reconciled_commit_sha>. /push is now unblocked.` Continue to Step 8, which skips the spec-update
dispatch because no real commit occurred. Keep that skip unconditional, and do not read it as proof
that the spec is current: the update is still owed where the originating cycle never reached Step 8
or skipped it (the Phase 10 token write failed or was refused, the invocation was interrupted, or
`push_gate_race`); where it did reach Step 8 (already pushed, branch or session drift), Step 8's
own contract lets the dispatch fail with a WARNING, so an empty token slot cannot tell a completed
cycle from one whose update never landed. This reconciliation performs no update; the owed update
is a finding for the spec-update path, carried into a separate explicit cycle, never an accepted
outcome.

#### status = `nothing_to_commit_precommitted`
Record `auto_bulk_commits[]` in the Step 8 summary and print: `INFO: Changes were already
committed in an auto-bulk commit. auto_bulk_commits: <auto_bulk_commits[]>`. Continue to Step 8.

#### status = `failed` — retryable grant codes

Check `failure_code`.

**Retryable** (`grant_missing`, `grant_expired`, `grant_consumed`), only when `repository_results`
proves that zero repository commits landed. Retry once with fresh grants:
1. Revoke the stale grants, rebuild the plan (Step 5) and write a fresh bound grant for every
   newly planned repository, never only the control-root grant. Revoke once with the first
   grant's `--revoke-existing-for-task`, then issue the remaining grants without it:
   ```bash
   python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/write-commit-grant.py" \
       --task-id "$TASK_ID" --repo-root "$PLANNED_REPO_ROOT" \
       --revoke-existing-for-task "$TASK_ID"
   ```
2. Rerun the planning dry-run and QA (rebuilding the plan changes the CAS snapshot), then
   re-dispatch changelog-analyst with the freshly approved plan.
3. Read the retry result with this same status handling: `committed` and
   `nothing_to_commit_precommitted` continue to Step 8; `nothing_to_commit` warns and continues to
   Step 8; a second `failed` prints `ERROR: changelog-analyst retry failed (failure_code: <code>,
   reason: <reason>).` and routes the cause as a non-retryable code below, with no Step 8 until a
   landing is confirmed.

**Non-retryable** (`git_error`, `staging_error`, `hook_blocked`, `scope_violation`,
`repository_plan_invalid`, any other code, and every failure after one or more repository commits
landed): print `ERROR: changelog-analyst failed with failure_code: <failure_code>. Reason:
<failure_reason>.` No Step 8 until a landing is confirmed. The file `failure_reason` names goes to
its owner (Routes); a reason that names no file goes back to the changelog-analyst dispatch whose
status block reported it. Then rerun Step 5 through Step 7 for the repositories not yet landed,
with no round cap. `scope_violation` means the tree changed after QA reviewed it: rebuild the plan
and dispatch a fresh QA over the actual set.

**A hook rejection** (`hook_blocked`, or any hook refusing a tool call during `/commit`) is
the owner's decision (CLAUDE.md Subagent Hook Discipline #1-#3): the rejected operation is
never retried without the owner's grant, and never wrapped or bypassed. This rule does not
cover `grant_missing`, `grant_expired` and `grant_consumed`, though each reaches the analyst as
the privilege guard refusing the commit for want of a live grant: they are the commit grant's
own lifecycle (absent, past `expires_at`, or spent by an earlier attempt;
`agents/changelog-analyst.md` § failure_code values keeps them apart from `hook_blocked`), not a
hook refusing an operation. The Retryable rule above takes a fresh grant for them and asks
nothing, and after a landing the Non-retryable rule routes them. Ask one
AskUserQuestion — header `Authorize`,
question `<hook> refused <the operation> for task <TASK_ID>: authorize it?` with the hook's
output verbatim, options `Authorize it` (description: the exact command the owner runs to
authorize it, for example `/allow <op> <args>`; `/commit` runs the operation again once the
grant exists) and `Do not authorize` (description: `/commit` goes on without that operation
where every acceptance criterion still holds without it, Hook Discipline #4).

### Step 8: Spec-update dispatch (post-commit, advisory)

This step is dispatched from `/commit`'s own orchestrator context, never from within
changelog-analyst, which has already returned. It runs only when `BULK=false`, `DRYRUN=false`,
`TASK_ID` is set and changelog-analyst reported a real commit (`commit_status` `committed`);
otherwise it is skipped (a `push_gate_reconciled` result created no commit). Use absolute paths,
with `<DEV_DOCS_ROOT>` = `<CONTROL_ROOT>/docs/dev`.

You make the selection yourself, in this order, and stop at the first stage that decides. Every
predicate is anchored to the current `TASK_ID`; an artifact of another cycle is never matched.

1. **`context.spec_path`.** If `<DEV_DOCS_ROOT>/context-<TASK_ID>.json` has a non-null `spec_path`
   that is a regular file, that file is the spec to update.
2. **The close report's continuation line.** Otherwise read `<DEV_DOCS_ROOT>/close-report-<TASK_ID>.md`
   outside its fenced code blocks and match each line against
   ``^[-*+]?\s*Continuation spec(\s*\([^)]*\))?\s*:\s*`?(docs/dev/specs/spec-[^\s`]+\.md)`?\s*$``
   (an optional list marker, an optional parenthetical qualifier and backticks around the path are
   all accepted, as in ``- Continuation spec (from prior NO): `docs/dev/specs/spec-20260520-044700.md` ``).
   Exactly one matching line whose path exists is the spec to update; print `WARNING: linked via
   close-report, not context.spec_path`.
3. **Specs of this cycle.** Otherwise take the files `<DEV_DOCS_ROOT>/specs/spec-YYYYMMDD-HHMMSS.md`
   (that basename form only) modified between 24 hours before and 1 hour after the close report's
   modification time and holding the literal line `<!-- spec-continuation-of: <TASK_ID> -->`. That
   line is the only content test: no other search, no free-form scan of a spec.
4. **Outcome (advisory: print, dispatch nothing).** No file: `No spec associated with task-id
   <TASK_ID>`. One file: `spec produced this cycle but not linked in context: <path>`. Several:
   `multiple specs produced this cycle without context linkage: <paths>; explicit context.spec_path
   required`.

A spec named by stage 1 or 2 is updated by the inline Agent below, with `<SPEC_PATH>` that file (do
not invoke `/spec-update` as a slash command).

With `COMMIT_STEP8_TRACE=1` in the environment, also write one marker line on stderr at each
decision point and change nothing else (stdout, exit codes and dispatch stay as they are; the
trace is off by default): `STEP8_SKIPPED: bulk=true`, `STEP8_SKIPPED: dryrun=true`,
`STEP8_SKIPPED: task_id_empty` or `STEP8_SKIPPED: changelog_no_real_commit` at the skip that
applies; `STEP8_SPEC_UPDATE_DISPATCHED: task-id=<TASK_ID> stage=<1|2> spec_path=<SPEC_PATH>`
immediately before the Agent dispatch; `STEP8_NO_SPEC: task-id=<TASK_ID>` and `STEP8_UNLINKED_SPEC:
task-id=<TASK_ID> count=<N> paths=<paths>` at stage 4's two outcomes. `scripts/step7-spec-update.py`
is the tested reference of this selection and these markers
(`tests/test_step8_spec_update_markers.py`); it is not a call of this step, because a script that
reads the close report here would be a second decider of it.

```
You are executing the spec-continuation logic for task-id=<TASK_ID>.

Target spec file: <SPEC_PATH> (absolute path — this file exists; update it in place through its
one writer, <HARNESS_ROOT>/scripts/spec-write.py, as spec-update.md's Continuation-spec mode describes).

DO NOT:
- Invoke /spec-update as a slash command
- Create a new spec file; only update the existing one at <SPEC_PATH>
- Write <SPEC_PATH> any other way than through <HARNESS_ROOT>/scripts/spec-write.py
- Overwrite or delete prior "### Cycle N" sections
- Modify any git state, commit grants, push tokens, or command files
- Write any artifacts outside <SPEC_PATH>
- Read or modify files outside <DEV_DOCS_ROOT>/, <SPEC_PATH>, and <HARNESS_ROOT>/commands/spec-update.md (allowed: read spec-update.md for instructions)

Follow the ## Continuation-spec mode instructions from <HARNESS_ROOT>/commands/spec-update.md
exactly. The active task-id is <TASK_ID>; the target spec is <SPEC_PATH>. Gather the source
artifacts from <DEV_DOCS_ROOT>/: context-<TASK_ID>.json, dev-report-<TASK_ID>*.json,
qa-report-<TASK_ID>*.json, close-report-<TASK_ID>.md, completion-<TASK_ID>.md. Output the spec
path when done.
```

If the Agent dispatch fails for any reason (error, timeout or exception), retry the identical
dispatch exactly once. If the retry also fails, print `WARNING: spec-update dispatch failed for
task-id=${TASK_ID} — spec not updated` and continue. The commit is already recorded: neither the
failure nor the retry rolls it back or delays it.

## `--auto` mode: batch-discover and sequentially commit

`--auto` performs Step 1-2's job itself, then walks every `commit_pending` PARENT task-id, one at a
time, through the same unmodified Step 3 to Step 8 an explicit `/commit <task-id>` runs (binding
`FORCE=false`, `BULK=false` and the current parent's `TASK_ID`). It is distinct from `--bulk`:
`--bulk` skips Step 3, `--auto` never does.

1. **Discover** once, at the start; the snapshot is frozen for the batch. Run Step 2's
   `list-actionable --next-action commit` call. It lists `kind == "ticket"` parents only,
   deterministically sorted, the task-id first on each line.
2. **Walk each parent in order**, never concurrently: parent N+1 starts only after parent N has
   landed. Bind `DRYRUN` and `QA_CODEX` as passed to the batch, and run Step 3 through Step 8 exactly
   as written; nothing in them is aware `--auto` drives them.
3. **Each parent completes**: its walk ends only by landing (`commit_status` in `committed`,
   `nothing_to_commit`, `push_gate_reconciled`, `nothing_to_commit_precommitted`) or, under
   `--dry-run`, the preview end. Gaps, a `COMMIT: REJECT` and changelog-analyst failures are routed
   inside the walk (Steps 3-7); a `partially_committed` parent continues its remaining repositories
   in order under fresh grants (Step 7). A hook rejection, or another decision only the owner can
   make, is one AskUserQuestion naming that parent and the decision (Step 7's question for a hook);
   the walk goes on after the answer.
4. **Batch summary**: once every parent has landed, print one line per parent:
   `task-id: <landed outcome>`.

## Privilege guard

Every git operation (staging, committing, nested repositories, the push-gate write) is
changelog-analyst's. `hooks/pretool-git-privilege-guard.py` (PreToolUse, Bash) refuses an agent
commit that no live single-use grant authorizes, and the ledger row H-031 in
`docs/ENFORCEMENT-LEDGER.md` states what is observed of it. The grant's binding to repo, branch and
`expected_head`, its provenance (`hooks/lib/commit_pipeline.py`), the one-commit-per-call rule and
the finalizer that journals a commit are described in the hook's own header; `/commit` adds
nothing to them.

## Related

- `/close <task-id>` — may run first; `/commit` completes an unclosed task itself (Step 3 runs `/close` Steps 1-2 for it)
- `/push` — must run after `/commit` (reads the push-gate token written by changelog-analyst)
- `agents/changelog-analyst.md` — the subagent that does all git work
