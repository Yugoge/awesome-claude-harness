---
description: Commit session changes via changelog-analyst subagent
disable-model-invocation: true
---

# /commit

Agentic commit command. Step 3's one disposition call says whether the task's cycle is
complete and closed; an incomplete or unclosed task is completed first (its gaps go back to
the dispatches that owe them, its close runs as `/close` Steps 1-2). Then the
`changelog-analyst` subagent classifies files, stages them, and creates real branch commits.
`--bulk` skips Step 3. Normal task mode admits every task-owned path only after partitioning
it across an explicit supported-repository set; the control checkout and `<HARNESS_ROOT>`
are supported without a project-root override.

## Usage

```
/commit [<task-id>] [--force] [--bulk] [--dry-run] [--codex] [--auto]
```

| Flag | Meaning |
|------|---------|
| `<task-id>` | Optional when the session context identifies the active cycle: if omitted (and `BULK=false`, `AUTO=false`), the orchestrator infers the task-id from the current session's conversation context (see Step 2; ambiguity never guesses, it asks); an explicit task-id is always allowed and authoritative. Unused in `--bulk` mode; rejected as an explicit token by `--auto` (which never enters Step 2). Task-id from the completed `/dev` cycle (e.g. `20260516-212024`). |
| `--force` | **No-op alias of the normal path.** No gate is bypassed — Step 3 and Step 6's pre-commit QA gate both still run exactly as a bare invocation would. Human-only (enforced by `disable-model-invocation: true`). Its one effect is Step 4's best-effort audit-log append, kept for backward-compatible invocation. |
| `--bulk` | Smart batch mode — group by task-id then subsystem, commit coherently, flag orphan files separately. Human-only (enforced by `disable-model-invocation: true`). Skips Step 3; retains the pre-commit QA gate (Step 6). |
| `--dry-run` | A preview: Step 3 completes the cycle as a real run does; Steps 5-6 plan and review; print what would be staged/committed (and the QA verdict); do not execute the real commit. |
| `--codex` | In the pre-commit QA gate (Step 6), QA additionally runs an adversarial Codex round on the planned per-file changes (each PLAN_GROUPS path vs HEAD), not the staged index. Without it, QA does a single-round self-review. |
| `--auto` | Discover every `commit_pending` PARENT task-id and walk each one, sequentially, through the SAME non-bulk Steps 3-8 a bare `/commit <task-id>` would run — never concurrently, never skipping Step 3. Structurally distinct from `--bulk` (see `--auto mode` below). Human-only (enforced by `disable-model-invocation: true`). |

## Step-by-step workflow

### Step 1: Parse arguments

Parse `$ARGUMENTS`:
- Strip `--force` if present → set `FORCE=true`; else `FORCE=false`
- Strip `--bulk` if present → set `BULK=true`; else `BULK=false`
- Strip `--dry-run` if present → set `DRYRUN=true`; else `DRYRUN=false`
- Strip `--codex` if present → set `QA_CODEX=true`; else `QA_CODEX=false`
- Strip `--auto` if present → set `AUTO=true`; else `AUTO=false` (default — every `--auto`-specific rule below is inert)
- Remaining token (if any) is `TASK_ID`

**`--auto` flag combination**: `--auto` takes no task-id, `--force` or `--bulk`
(`scripts/dev-lifecycle.py`'s `validate_auto_flag_combination(True, TASK_ID, FORCE, BULK)`).
When `AUTO=true` and any of the three is set, take no action and ask one AskUserQuestion:
header `Flags`, question `--auto takes no task-id, --force or --bulk: which /commit should
run?`, options:
- `--auto`: every `commit_pending` parent, each through Steps 3-8;
- `<task-id> only`: the task-id typed, else the first parent `dev-lifecycle.py list-actionable
  --next-action commit` lists (the `--auto` discovery below), alone through Steps 3-8;
- `--bulk` (only when `--bulk` was typed): the batch sweep, Steps 5-8, with no Step 3.

Continue in this turn with the mode the answer names (`--force`, a no-op, is dropped;
`--dry-run` and `--codex` stay as typed: `--auto` MAY combine with them, and each walk below
honors `DRYRUN`/`QA_CODEX` exactly as the non-`--auto` path does). A legal `--auto` skips
Step 2: the `--auto mode` section below binds `TASK_ID` itself once per discovered parent and
drives Steps 3-8.

### Step 2: Resolve task-id (unless --bulk or --auto)

If `BULK=false` AND `AUTO=false`:
- If `TASK_ID` was supplied, use it directly. An explicit task-id is always allowed and
  authoritative.
- If `TASK_ID` is empty: infer it from the current session's conversation context — the
  parent task-id of the active `/dev` cycle, `/do` cycle, or the `/close` that just ran in
  this session (the same bare-invocation resolution `/close` uses; see `commands/close.md` §
  Task-id resolution). There is NO filesystem scan and NO default-to-newest; do NOT scan
  close-reports by mtime (it picks up unrelated reports from other sessions).
  - **Uniqueness precondition**: inference succeeds ONLY when the conversation identifies
    exactly ONE unambiguous candidate task-id. Step 3 completes and closes whatever task
    it is given, so with two or more candidate cycles, or any doubt which cycle is meant, do
    NOT guess.
  - No unambiguous candidate: ask one AskUserQuestion — header `Task`, question `Which task
    should /commit land?`, options: up to three parents that
    `python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/dev-lifecycle.py" list-actionable --next-action commit --project-dir "<PROJECT_ROOT>"`
    lists (the first word of each line), then those `--next-action close` lists (Step 3
    closes them first), each labelled with its task-id, plus `/commit --auto` (every
    `commit_pending` parent). Bind `TASK_ID` to the answer, or run `--auto` mode, and go on.
    When neither list names a parent, print `No task to commit: dev-lifecycle.py lists no
    commit_pending or close_pending parent.` and end.

If `BULK=true`: `TASK_ID` may remain empty; changelog-analyst operates in bulk mode.

### Routes: each gap or finding goes back to the dispatch that owes its artifact

Every gap the disposition call prints and every finding a later step names (the late-repair
state C and the repository plan in Step 5, a `COMMIT: REJECT` in Step 6, a changelog-analyst
failure in Step 7) has an artifact path. Its owner is the declaring-dispatch reader's answer
on that path, one Bash call, run as written with the path for `<path>`:

```bash
python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/lib/obligation.py" declaring-dispatch --task-id "$TASK_ID" --project-dir "<PROJECT_ROOT>" --path "<path>"
```

It reads this task's dispatch records in every session the project's transcript store holds
(`hooks/lib/obligation.py` `declaring_dispatch`), so a `/dev` or `/close` of an earlier
session is found. Act on its JSON answer:

- `source` `dispatch` (its obligation declares the path), `lane` (an artifact of the whole
  fan-out, as its canonical aggregate, which the lane-completeness hook writes when a lane's
  dev writes its report; the main agent runs no aggregator) or `writer` (a product file: the
  dispatch whose own tool calls wrote it): dispatch it again, a fresh synchronous Agent call
  (`run_in_background: false`) with the same `subagent_type`, `task_id`, `lane` and
  obligation and a fresh `dispatched_at` (G1 refuses a re-dispatch whose obligation
  differs), its prompt naming the gap or finding.
- `source` `todo_step` (no dispatch has declared the path yet): with a `template`, a fresh
  synchronous dispatch of that step's role under the same task id, from the template of the
  answer's `step` in `commands/<command>.md` with the template's obligation; with none, the
  step is the main agent's own (as `/dev` Step 11): run it yourself under the same task id.
- A `/do` task's do-report, and a file the answer names no owner for (`null`) in a `/do`
  task (its main agent wrote it): dispatch dev under the same task id with the obligation
  `<obligation v="1">{"task_id": "<TASK_ID>", "role": "dev", "pipeline": "do", "profile": "singular", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this call>", "artifacts": [{"kind": "json", "path": "docs/dev/dev-report-<TASK_ID>.json", "schema": "dev-report.v2", "identity": {"task_id": "<TASK_ID>"}}]}</obligation>`
  to complete the `/do` work, never `/do`'s own steps; its dev-report, which G2 verifies at
  dev's stop, concludes a `/do` task whose do-report is not `completed` (Step 3's call takes
  it), and the `/commit` orchestrator writes no report.
- `null` in a commit-QA round, and a commit-QA finding that cites no artifact: the path
  becomes that round's own report, `docs/dev/commit-qa-report-<TASK_ID>.md`, whose QA
  dispatch runs again (Step 6) and names a path, routed as above.
- `null` for any other path: no dispatch or request exists to re-run. Ask one
  AskUserQuestion (header `Request`) what the cycle should deliver, naming the task and
  the artifact; the options are the requests the task's own artifacts state (its ticket or
  user-requirement file) and up to two parents `dev-lifecycle.py list-actionable
  --next-action commit` lists (`Commit <task-id> instead`); then dispatch dev under the
  same task id for the answer.
- A dispatch of one of a late repair's stages (a role `record-stage` takes): the run record
  holds each stage's report by hash, so when the dispatch returns, record the report it wrote
  as `/close --late-repair` records each stage (`<role>` its role, `<path>` the path):
  `python3 ~/.claude/scripts/late-repair-controller.py record-stage --task-id "$TASK_ID" --project-dir "$TASK_PROJECT_ROOT" --stage <role> --report-path <path> --repair-run-id "$(jq -r .repair_run_id "$TASK_PROJECT_ROOT/docs/dev/late-repair-run-$TASK_ID.json")"`

There is no default role. Once the dispatch returns, run again the one check that named the
path; a gap or finding it names again is routed the same way, with no round cap.

### Step 3: Resolve the disposition; complete the cycle when incomplete (skip if BULK=true)

`--force` never skips this step, and `--dry-run` completes the cycle here exactly as a real
run does: only the commit itself is previewed. One Bash call binds the close-report's path
(data: check 3 and Step 5 read it), prints its mtime in epoch seconds (nothing when there is
no file), and prints the task's disposition at the close stage, the dev stage plus a
close-report whose last non-empty line classifies `yes`:

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
  Steps 1-2 for this task id, as `/close` runs them (the three inspectors, then close QA
  rounds until one lands `CLOSE: YES*`; close QA writes the close-report).
- A non-zero exit with no `DISPOSITION` line is an instrument failure (its reason on
  stderr), never a disposition: run the call once more; if it fails again, print one line
  `OPERATION_STALLED: <the error>`, record it as the session's next harness-repair item, and
  go no further: no grant, no dispatch, no commit.

The same output carries a `/dev` task's chain data fields (`mode`, `lanes`, `report_paths`,
`canonical_dev_report`, `artifact_paths`, `commit_whitelist_artifacts`, `qa_inputs`) on its
`CHAIN=` line: each run binds `ARTIFACT_CHAIN` to that JSON verbatim (empty for a `/do`
task, whose run prints none), and `close.md` Steps 1-2, Step 5 and Step 7 read the latest
run's. No second chain call is made.

**Check 3 — close-report age (advisory, never aborts)**: if the `chain_pass` run's mtime is
older than 86400 seconds (24 h), print `Close-gate: WARNING — close-report for task
${TASK_ID} is older than 24h (mtime: <mtime>). Proceeding — staleness is advisory. Re-run
/close if the tree has drifted since this approval.` and continue. Age alone never blocks a
commit: the Step 6 pre-commit QA gate reviews every planned file's actual change vs HEAD on
every invocation.

### Step 4: Deprecated --force usage audit (only when FORCE=true)

AC11: `--force` bypasses nothing — this step is a
pure audit log, kept for backward-compatible invocation. If `FORCE=true`: create `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/logs/` and append a line with ISO timestamp, task-id, and mode=force to `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/logs/commit-overrides.log`. Best-effort; proceed even if log append fails.

Print: `WARNING: --force is deprecated and is now a no-op alias of the normal path — no gate is bypassed. Audit entry written to ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/logs/commit-overrides.log.`

### Step 5: Write commit grant(s) after resolving the repository plan

Before dispatching changelog-analyst, write the appropriate authorization token:
- **BULK=true**: the multi-use bulk-commit capability is now minted by the TRUSTED `userprompt-bulk-commit-capability.py` hook the moment the human submits `/commit --bulk` (an LLM cannot self-invoke a `disable-model-invocation: true` slash command, so the prompt itself is the trust root). The orchestrator MUST NOT emit a Bash command to write the sentinel — that fragile exact-string path is retired.
  - The hook minted `claude-bulk-commit-sentinel-<sid>-<nonce>.json` in the state dir (origin `userpromptsubmit-hook`). Proceed to the **Step 6 pre-commit QA gate** (then Step 7) — `--bulk` is NOT exempt from the QA gate, and (lane L7, AC11) neither is `--force` anymore; nothing bypasses it. The privilege guard decides on the sentinel at each auto-bulk commit; this step reads nothing.
  - NO FALLBACK: the canonical writer is no longer Bash-executable (Layer 1.F deny-only, stage-2). The hook is the SOLE minter. Do NOT attempt to write the sentinel via Bash.
- **BULK=false**: before writing any grant, resolve the task's report and build
  `REPOSITORY_PLAN` once, as data, in one Bash call. `scripts/resolve-commit-repos.py`
  takes the resolved control checkout and the de-duplicated supported repository, the
  real harness checkout: command-owned admissions, never values read from the report,
  `CLAUDE_PROJECT_DIR` or a user-supplied root override. It reads the canonical dev/do
  report, resolves every `files_modified[]` / `files_created[]` path, assigns each path to
  its actual Git root (the deepest supported repository, never an unadmitted nested
  checkout), and emits an ordered JSON plan whose per-repository entries bind
  `repo_root`, `branch`, `expected_head`, task-owned repo-relative paths, and whether the
  control repo owns cycle artifacts. The report is this task's dev-report, else its
  do-report, in the exact `docs/dev` directory that supplied `CLOSE_REPORT` (the
  control-root `docs/dev` only when there is none); never scan reports by mtime.

  ```bash
  CONTROL_ROOT="$(git rev-parse --show-toplevel)"
  NESTED_REPO="$(git -C "$(realpath "${CLAUDE_HOME:-$HOME/.claude}")" rev-parse --show-toplevel)"
  TASK_DOCS_ROOT="${CLOSE_REPORT:+$(dirname "$CLOSE_REPORT")}"
  TASK_DOCS_ROOT="${TASK_DOCS_ROOT:-$CONTROL_ROOT/docs/dev}"
  TASK_PROJECT_ROOT="$(dirname "$(dirname "$(realpath "$TASK_DOCS_ROOT")")")"
  # The late-repair state and path the controller prints, used verbatim: "verified"
  # names the effective report finalize recorded (TASK_REPORT below); "none" keeps the
  # dev or do report; "invalid" (State C) names the artifact of a finding.
  LATE_REPAIR_JSON="$(python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/late-repair-controller.py" \
      resolve-effective-report --task-id "$TASK_ID" --project-dir "$TASK_PROJECT_ROOT")"
  LATE_REPAIR_STATE="$(jq -r .state <<<"$LATE_REPAIR_JSON")"
  if [ "$LATE_REPAIR_STATE" = "verified" ]; then
      TASK_REPORT="$(jq -r .path <<<"$LATE_REPAIR_JSON")"
  elif [ -f "$TASK_DOCS_ROOT/dev-report-$TASK_ID.json" ] || [ ! -f "$TASK_DOCS_ROOT/do-report-$TASK_ID.json" ]; then
      TASK_REPORT="$TASK_DOCS_ROOT/dev-report-$TASK_ID.json"
  else
      TASK_REPORT="$TASK_DOCS_ROOT/do-report-$TASK_ID.json"
  fi
  REPOSITORY_PLAN="$(python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/resolve-commit-repos.py" \
      --task-id "$TASK_ID" --control-root "$CONTROL_ROOT" \
      --report "$TASK_REPORT" --supported-repo "$NESTED_REPO")"
  printf 'LATE_REPAIR=%s\n' "$LATE_REPAIR_JSON"
  ```

  Two outcomes are findings (Routes), each followed by this block run again:
  - The late-repair state `invalid` (State C): a finding on the `path` the controller
    printed.
  - An empty plan (the helper's non-zero exit, its reason on stderr: a malformed report,
    an unattached branch, an absent HEAD, an unsupported owner, an identity mismatch): a
    finding on `TASK_REPORT`, the plan's one source. It is never an empty plan or "nothing
    to commit"; no grant is issued and nothing is staged while it holds.

  **Attribution-log slice (ground-truth attribution, additive to the plan above),
  with the dispatch snapshot's inputs.** Once `REPOSITORY_PLAN` resolves, the next
  Bash call (the block below) builds `ATTRIBUTION_LOG` — a slice of
  the write-time attribution journal (`hooks/lib/attribution_journal.py`) scoped to
  exactly this plan's owned paths. This is the fact-based attribution source
  `agents/changelog-analyst.md`'s staging decision reads instead of (or as a
  cross-check alongside) the dev-report's self-reported ledger fields. An exit code of 2
  (no journaled events for any requested path — e.g. the path pre-dates the journal's
  rollout) is an ordinary, expected outcome, not a finding, and nothing in this call
  decides: its output is what the manifest below records. The same call prints
  the manifest's other inputs: the state dir, the session id and each plan
  entry's `git status --porcelain=v1`. (The orchestrator gate allows five Bash
  calls in a row; with `--auto`'s discovery, Step 3 and the plan this is the
  fourth, a one-repository plan's grant writer the fifth.)

  ```bash
  ATTRIBUTION_FILES=()
  while IFS= read -r abs_path; do
      [ -n "$abs_path" ] && ATTRIBUTION_FILES+=(--file "$abs_path")
  done < <(jq -r '.repositories[] | .repo_root as $root | (.owned_paths[]? // empty) | $root + "/" + .' <<<"$REPOSITORY_PLAN")
  ATTRIBUTION_LOG="$(python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/verify-attribution-chain.py" --json "${ATTRIBUTION_FILES[@]}" 2>/dev/null)"
  ATTRIBUTION_LOG="${ATTRIBUTION_LOG:-{\"results\":[],\"no_events\":[],\"discarded_lines\":[]}}"
  . ~/.claude/hooks/lib/harness_state_dir.sh
  harness_state_dir
  echo "${CLAUDE_CODE_SESSION_ID:-$CLAUDE_SESSION_ID}"
  while IFS= read -r PLAN_ROOT; do
      echo "--- $PLAN_ROOT"
      git -C "$PLAN_ROOT" status --porcelain=v1
  done < <(jq -r '.repositories[].repo_root' <<<"$REPOSITORY_PLAN")
  ```

  `ATTRIBUTION_LOG.results[]` carries, per owned path, its folded write-event
  chain verdict (`CONTINUOUS_TAIL_MATCH` / `CONTINUOUS_TAIL_MISMATCH` / `BREAK`)
  and the `session_id`/`agent_id`/`task_id` of every witnessing event —
  `agents/changelog-analyst.md` groups commits from this. `no_events[]` lists
  owned paths the journal has zero coverage for (pre-journal backlog or a write
  that bypassed the hooks surface): for those, changelog-analyst's backup
  investigative path applies, never a block.

  **Write the dispatch-snapshot manifest FIRST — before minting any grant** (non-bulk
  mode only; ordering is load-bearing since 2026-10-06, see below). From the
  snapshot call above (each admitted plan entry's own `git status --porcelain=v1`,
  the state dir and the session id it printed), write
  `manifest_path = <state-dir>/claude-commit-manifest-{sid}.json` — where `<state-dir>`
  is `CLAUDE_STATE_DIR` when set to an absolute path and `/tmp` otherwise, resolved by
  `hooks/lib/harness_state_dir`, which is the SAME resolver the manifest's readers use;
  do not hardcode `/tmp` — containing `session_id`,
  `task_id`, `dispatched_at`, the complete `REPOSITORY_PLAN` (including its report
  digest), the exact `ARTIFACT_CHAIN` JSON (when non-empty), and
  `files_at_dispatch` keyed by canonical repository root. Best-effort status
  capture is permitted; the plan and the chain are written exactly as bound. Bulk mode
  retains its existing control+nested behavior.

  **Why the manifest now comes first (mint precondition).** `write-commit-grant.py` will
  REFUSE to mint without it. A live `/commit` user-intent sentinel is no longer
  sufficient on its own: a bare `/commit` first line delivered to a seat lights that
  sentinel without running any of this pipeline, and that is exactly how 14 commits
  landed with changelog-analyst never dispatched and Phase 2/3/4/5/10 — including the
  fd-9 lock and the MANDATORY pre-stage validation, both of which fail silently — never
  executed. The minter now also requires, via
  `hooks/lib/commit_pipeline.verify_pipeline_dispatch()`: a live manifest for this
  session and task, whose `repository_plan` admits the exact `--repo-root` being minted
  for at that repo's live branch and HEAD, whose `report_sha256` matches the actual bytes
  of the cycle report it cites, plus an existing close-report for the task (existence
  only; Step 3 wrote or found it). A
  mint refusal names the one missing piece; rebuild that artifact and re-mint rather than
  working around the refusal. Closes disclosure items 1 and 2 of commit `1fdbd3767`,
  which landed labelled `Not fully closed`.

  Write **one single-use commit grant per `REPOSITORY_PLAN.repositories[]` entry**,
  always passing that entry's `repo_root` to `write-commit-grant.py`. Verify that
  the writer's captured repo/branch/HEAD equals the plan entry; any mismatch revokes
  all grants for this task/session, then the plan is rebuilt (the block above), the
  grants re-minted and re-verified. The script resolves the session ID from
  `CLAUDE_CODE_SESSION_ID` (primary) or `CLAUDE_SESSION_ID` (fallback). If neither is
  set it exits 2 and no grant can exist: print one line `OPERATION_STALLED:
  write-commit-grant.py has no session id (CLAUDE_CODE_SESSION_ID and CLAUDE_SESSION_ID
  unset)`, record it as the session's next harness-repair item, and dispatch nothing.
  Each grant is still a single-repository capability; a report cannot mint admission
  for a new repository.

**Repo/branch/HEAD binding (2026-07-15 parity fix)**: `repo_root`, `branch`, and
`expected_head` are captured by both the repository planner and the grant-writer,
then re-checked by the privilege guard against live Git state when each commit runs.
A grant issued for one repo/branch/commit is rejected if any of the three changes.
Never omit `--repo-root`: every grant corresponds to exactly one plan entry.

**Grant timestamp format (NON-NEGOTIABLE)**: The `expires_at` and `created_at` fields MUST be ISO-8601 strings produced from timezone-aware UTC datetimes (e.g. `(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()` yields `"2026-05-19T16:18:56.123456+00:00"`). Epoch integers and epoch floats (e.g. `int(time.time()) + 600`, `time.time() + 600`) are NOT accepted by the privilege guard. The guard at `<HARNESS_ROOT>/hooks/pretool-git-privilege-guard.py:377-384` parses these fields via `datetime.fromisoformat(end_str.replace('Z', '+00:00'))`; on `ValueError`/`TypeError`/`AttributeError` the helper `_end_time_passed` returns `True` (i.e. "already expired"), which silently rejects the grant and blocks the commit. The expiration window is 30 minutes from `created_at` — bake the offset into `expires_at` at write time. Invoke the grant-writer script (standard library only, so no venv: the orchestrator's working directory is the product repository; it resolves `CLAUDE_SESSION_ID` from the environment, generates a fresh nonce, writes timezone-aware ISO-8601 `created_at` and `expires_at` on a 30-minute window, and emits the resulting grant path on stdout):

For each entry, invoke the existing writer with the concrete admitted root:

```bash
python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/write-commit-grant.py" \
    --task-id "$TASK_ID" --repo-root "$PLANNED_REPO_ROOT"
```

Do not flatten the plan into one grant and do not infer repositories from current
dirty status. Unused per-repository grants expire normally or are revoked at every
unstage pause and at the `--dry-run` preview end.

**Dry-run and the grants**: a dry-run leaves HEAD, worktree bytes and index bytes
identical, but it does mutate-then-restore the index (`agents/changelog-analyst.md` saves
and restores index bytes; `scripts/stage-owned-hunks.py` uses a throwaway
`GIT_INDEX_FILE`). This step mints a real single-use grant per plan entry before any
dry-run runs, unconditioned on `DRYRUN`; four backstops bound it and MUST stay intact:
every unstage pause, the `--dry-run` preview end and the plan-computed-OK-but-nothing-
pending report each revoke it; it is single-use and bound to repo + branch +
`expected_head`; changelog-analyst's DRYRUN guard forbids consuming it;
`pretool-git-privilege-guard.py` blocks agent commits independently. Rationale record:
`docs/reference/commit-dryrun-close-gate-ruling.md`.

Both `created_at` and `expires_at` MUST match the regex `^20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(\+\d{2}:\d{2}|Z)$`. Do NOT substitute `time.time()`, `int(time.time())`, or `datetime.utcnow()` (the last returns a naive datetime whose `.isoformat()` omits the TZ offset and falls into the naive-comparison branch at line 382).

**Transaction boundary:** Git provides no cross-repository atomic commit. Normal mode
therefore uses an explicit ordered, non-atomic transaction: all repositories are
planned and QA-reviewed before the first commit, each repository then receives its
own lock/grant/CAS/commit/token transaction, and any later failure is surfaced as
`partially_committed` with per-repository results. Never claim cross-repository atomicity,
silently roll back an already-created commit, or hide a partially completed transaction.

### Step 6: Pre-commit QA review gate

A QA agent reviews **what is actually about to be committed** (each planned file's change vs HEAD) and may BLOCK the commit. This is an independent second reviewer on top of `changelog-analyst`'s own staging judgment — it exists because `--bulk` skips `/close`'s gate entirely, and even a normal commit's *actual file changes* deserve a fresh adversarial check for junk / secrets / scope contamination. The gate reviews the file changes themselves, NOT the dev-report.

**AC11: `--force` never skips this step.** This gate always runs, for BOTH `BULK=false` and `BULK=true`:

**Step 6 — Planning phase (internal dry-run; plan-only).**
Dispatch `changelog-analyst` (Agent, `subagent_type: changelog-analyst`) with the **same prompt as Step 7 but `DRYRUN=true`** (force dry-run regardless of the user's `--dry-run`). Under `DRYRUN=true` changelog-analyst classifies, stages the candidate set into the index, and STOPS before commit — it does NOT commit, write push-gate tokens, run any recovery commit, or consume the Step 5 grant (guaranteed by the DRYRUN guard in `agents/changelog-analyst.md` — the `nothing_to_commit_precommitted` recovery path is disabled under DRYRUN). Capture from its output:
- `PLAN_GROUPS` — the per-proposed-commit groups, each `{repo, commit_message, files[]}` (one entry per intended commit; bulk yields several). **Preserve group boundaries — do NOT flatten across groups** (QA needs them to detect cross-task mixing).
- `PLAN_FILES` — the union of all group files, per repo.
- If the dry-run reports `nothing_to_commit` / empty plan: first compare it to the plan. If the plan computed OK, its owned paths exist, and those paths are not already landed, the disagreement between the owned-edit declaration and the live bytes is a finding on the dev report (Routes), not a silent no-op, and the planning phase is rerun after the fix. Only when the plan computed OK and the paths are already landed (or the plan lists no owned path), print `Nothing to commit (plan computed OK; dry-run found no pending change) — QA gate skipped.` It is never printed after a failed plan computation; then **when `BULK=false`, revoke the Step 5 commit grant** (it will never be consumed — same Grant-hygiene rationale as the Step 6 decision phase) via `python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/write-commit-grant.py" --task-id "$TASK_ID" --revoke-only` (skip in `BULK=true` — no per-task grant, empty TASK_ID); then proceed to Step 7 (which also no-ops). Do NOT dispatch QA on an empty plan.

QA reviews each planned file's change **directly against HEAD** (staging-independent), NOT via `git diff --cached`. Rationale: in multi-group `--bulk`, changelog-analyst stages per subsystem group and Phase 4 unstages cross-group files each iteration, so after the dry-run only the LAST group remains staged — a `--cached` review would silently skip every earlier group while ALL groups still enter `QA_APPROVED_FILES` and get committed. Reviewing each `PLAN_GROUPS` file vs HEAD (or reading new files) covers ALL groups regardless of staging state.

**Step 6 — Review phase (vs HEAD, staging-independent).**
Dispatch ONE QA subagent (Agent, `subagent_type: qa`). The dispatch prompt MUST include `codex_required: <QA_CODEX>` and `PLAN_GROUPS`, and instruct QA as follows:

```
You are the pre-commit QA gate. Review ONLY what is about to be committed — the files
in PLAN_GROUPS — by reading each file's ACTUAL change, NOT the dev-report.

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

For EVERY path in EVERY group, review its actual change DIRECTLY (do NOT rely on the
staging state — in multi-group bulk only the LAST group is left staged, so `git diff
--cached` would silently skip earlier groups). For each path, gather BOTH sources and
review every one that is non-empty:
  - DIFF: `git -C <repo> diff --text HEAD -- <path>` — `--text` forces a content patch even
    when `.gitattributes` marks the path `-diff`. If git instead reports "Binary files …
    differ", the path is a real binary blob: do NOT text-review it — judge it under
    rejection rule 1/4 below (intended asset vs accidental/junk binary).
  - CONTENTS: if `<path>` currently EXISTS on disk, ALSO read its contents directly.
  Both sources can be non-empty at once and you MUST review both — e.g. a path deleted at
  HEAD yet recreated on disk (status `D` + `??`: the diff shows only the old deletion, the
  file holds the new content), or a rename/copy's new side an earlier bulk group left
  unstaged (untracked → empty diff, but the file exists).
  - for a rename/copy, treat the OLD and NEW paths as TWO separate entries under this rule.
Feed the SAME per-path material to the Codex sub-round below (NOT the staged set).
Judge by intelligent review — NEVER a hardcoded junk list. REJECT the commit if any of:
  1. Transient / non-authored byproducts (runtime/session state, caches, registries,
     scratch/temp outputs, generated indexes, build products) — by what the file IS,
     regardless of which folder it sits in.
  2. Secrets / sensitive content (credentials, keys, tokens, .env material).
  3. Scope contamination — files unrelated to TASK_ID (BULK=false); or, WITHIN ONE
     proposed group, files belonging to two different task-ids / unrelated subsystems
     (BULK=true) — use the group boundaries above.
  4. Obvious correctness/quality defects in the diff (syntax-broken code, committed
     debug leftovers, accidental large/binary blobs).

codex_required = <QA_CODEX>:
  - true  → after your own review run ONE adversarial Codex round via Skill(codex) on the
            SAME per-file PLAN_GROUPS material you reviewed above (the HEAD diffs / new-file
            contents — NOT the staged set, which in multi-group bulk holds only the last group)
            + your draft verdict (reply `CODEX: APPROVE` / `CODEX: REJECT` +
            rationale). A substantive codex REJECT flips you to REJECT. Codex-status
            handling MIRRORS /close: quota/timeout MAY degrade to your own verdict with a
            recorded note; a PARSE FAILURE is NOT auto-degrade — record the verbatim raw
            codex output, manually scan it for dissent signals (`NO`, `bug`, `secret`,
            `junk`, `must not`, `wrong`, `should not`…), and REJECT (fail-closed) if ANY
            dissent signal or ambiguity is present.
  - false → single-round self-review; do NOT invoke codex.

Write a transcript to docs/dev/commit-qa-report-<TASK_ID or "bulk">.md (per-file
findings + codex_status when run) whose LAST line is EXACTLY one of:
  COMMIT: APPROVE
  COMMIT: REJECT - <one sentence naming the offending file(s) and why>
That line is your verdict; nothing else carries it.
```

**Step 6 — Decision phase.** The verdict is the last non-empty line of
`docs/dev/commit-qa-report-<TASK_ID or "bulk">.md`, read verbatim: the producer-stop gate
(G2) checked that file and that line at the QA subagent's own stop.

**Grant hygiene (`BULK=false`, at every unstage pause — REJECT routing — and at the `--dry-run` preview end):** in addition to unstaging, when `BULK=false` REVOKE the Step 5 commit grant so a gate under repair never leaves live commit authorization lingering (30-min TTL; never hold a live grant across a producer repair — re-mint by re-entering Step 5 after the fix, because bytes and plan changed):
```bash
python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/write-commit-grant.py" --task-id "$TASK_ID" --revoke-only
```
**Skip this revoke entirely when `BULK=true`**: bulk wrote NO per-task commit grant (Step 5 minted the multi-use bulk-commit sentinel, which self-expires on its own 30-min TTL) and `TASK_ID` is empty, so calling the writer with an empty `--task-id` would error (exit 2). (Only the `COMMIT: APPROVE` + real-commit path keeps the grant — it is consumed by Step 7.)

- `COMMIT: REJECT`: this is a verdict on the product, not a broken artifact. Print the verdict + offending files; **unstage the dry-run-staged set so the tree is left clean** — per repo, unstage ONLY currently-staged paths, computed rename-aware. Run `git -C <repo> diff --cached --name-status -z -M` and build the unstage set from its entries: a plain (non-rename) staged path → include it if it is in `PLAN_FILES`; a staged `R`/`C` entry → include BOTH its old and new paths if EITHER endpoint is in `PLAN_FILES` (the analyst may list only the new path, yet `--name-only` / a single-endpoint unstage leaves the other endpoint — e.g. `D old` — staged). Unstage that set via `git -C <repo> restore --staged -- <those>` (unborn repo: `git -C <repo> rm --cached -- <those>`). Do NOT pass planned files that are not currently staged — in multi-group bulk Phase 4 already unstaged the earlier groups, and `restore --staged` / `rm --cached` on an unstaged/untracked pathspec errors out and leaves the last group staged. Then revoke the grant (Grant hygiene above). Do NOT proceed to Step 7; do NOT commit (`--force` does not override this gate — it is a no-op alias of the normal path). Then:
    1. **Findings to their owners (Routes).** Each offending file and its reason (from the `commit-qa-report` and its verdict line) goes to the dispatch that declared the file or, for a product file, the dispatch whose own tool calls wrote it; a finding that names no file, or only a file no dispatch of the task wrote, goes to that round's own report, whose QA dispatch runs again to name a path. QA never edits the subject.
    2. **A fresh round.** After the owners' fixes, rebuild the plan (Step 5), rerun the planning dry-run, and dispatch a NEW QA subagent (a fresh dispatch; no prior verdict or finding in its prompt) that re-judges the actual changes against HEAD. A further `COMMIT: REJECT` repeats this routing; the loop ends on `COMMIT: APPROVE`, with no round cap.
- `COMMIT: APPROVE`:
  - Record `QA_APPROVED_FILES` = `PLAN_FILES` (the exact reviewed set, per repo). This is passed to Step 7 as the commit **ceiling** (TOCTOU guard — Step 7 must not commit anything outside it).
  - If the user passed `--dry-run` (`DRYRUN=true`): print the plan + `QA: APPROVE`, unstage the dry-run-staged set (clean tree, as in the REJECT branch), revoke the grant, and end the invocation with the preview delivered — the requested end state; no real commit.
  - Otherwise proceed to Step 7 for the real commit.

### Step 7: Dispatch changelog-analyst

Use the Agent tool with `subagent_type: changelog-analyst`. Pass a structured prompt:

(substitute `<CONTROL_ROOT>` with the resolved control root, `<REPOSITORY_PLAN>` with
the exact Step 5 JSON and `<ARTIFACT_CHAIN>` with the exact Step 3 JSON.
`NESTED_REPO` remains present only for bulk-mode backward compatibility; normal
mode's repository authority is the plan, while its `/dev` cycle-artifact
whitelist is the chain's `commit_whitelist_artifacts`):

```
CONTROL_ROOT=<CONTROL_ROOT>
NESTED_REPO=<NESTED_REPO>
REPOSITORY_PLAN=<exact Step 5 JSON; empty only in bulk mode>
ARTIFACT_CHAIN=<the chain data fields of Step 3's disposition call; empty only for bulk or source=do>
ATTRIBUTION_LOG=<exact Step 5 verify-attribution-chain.py --json output scoped to REPOSITORY_PLAN's owned paths; empty object ({"results":[],"no_events":[],"discarded_lines":[]}) in bulk mode>
TASK_ID=<resolved task-id or empty for bulk>
BULK=<true|false>
DRYRUN=<true|false>
FORCE=<true|false>
QA_APPROVED_FILES=<the Step 6 decision-phase QA-approved file set, per repo — Step 6 now runs unconditionally (lane L7, AC11), so this is non-empty whenever the planned file set was non-empty>

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
      "schema": "changelog-status.v1"
    }
  ]
}
</obligation>

You are the changelog-analyst subagent. Execute the commit workflow as specified
in your agent definition (agents/changelog-analyst.md). Use the variables above
to guide your behavior.

Disclosures (lane L7, AC10): when `BULK=false` and the close-report consumed
for `TASK_ID` (at `$CLOSE_REPORT`, or its late-repair effective-report
equivalent) contains a non-empty `## Disclosures` section, append to the
commit message body a `Disclosures: <n>` line followed by up to 10 items in
the same three-element format (`[code] path: problem | 归因: role(lane) |
修复: action`); beyond 10 items, write "see close-report" instead of listing
the rest. Do NOT create a separate file to duplicate the list.

**Standard-6 exemption (English-only) for this format string**: the `归因`/`修复`
field labels are not a violation to translate here — they are a verbatim
pass-through of `commands/close.md`'s own `## Disclosures` line format (that
command's own text: "field labels stay in Chinese"), which this line quotes so
`/commit` reproduces exactly what `/close` wrote rather than re-labeling it.
Translating only this copy would make the two commands describe two different
formats for the same artifact. If the convention is ever translated, do it in
`commands/close.md` first and update this quoted copy to match.

Constraints:
- CONTROL_ROOT is the fallback root for dev-report resolution; changelog-analyst MUST apply the subproject path-walk (dirname-of-changed-files → commonpath → walk up to docs/dev/) and check the subproject docs/dev/ first before falling back to ${CONTROL_ROOT}/docs/dev/
- GIT_ROOT must be computed per repo via `git rev-parse --show-toplevel`; never conflate with CONTROL_ROOT
- In normal mode, process exactly `REPOSITORY_PLAN.repositories[]` in `order`. Verify the plan schema/task/report digest and each live repo/branch/HEAD before staging; never add a repo from the report or dirty status. Bulk mode alone retains the legacy CONTROL_ROOT + NESTED_REPO sweep.
- In normal `/dev` mode, the base cycle-artifact whitelist is exactly
  `ARTIFACT_CHAIN.commit_whitelist_artifacts`, data of the disposition that admitted the
  task; this admits validated lane artifacts in fan-out mode and never invents optional
  parent artifacts.
- **TOCTOU guard (pre-commit QA gate)**: when `QA_APPROVED_FILES` is non-empty (the Step 6 gate ran and approved this exact set), it is the commit CEILING. Re-classify normally, then intersect the classified set with `QA_APPROVED_FILES`: stage/commit ONLY files in both. If your fresh classification yields any file NOT in `QA_APPROVED_FILES` (working tree changed since QA review), do NOT commit the unreviewed file; if the divergence is material (a QA-approved file vanished, or a new non-approved candidate appeared that you would otherwise commit), ABORT with `failure_code: scope_violation` rather than commit an unreviewed set. `QA_APPROVED_FILES` is empty only when Step 6's own planned file set was empty (nothing to commit); this guard does not apply in that case.
- Stage only files in the classified set; never use `git add -A` or `git add .`
- Commit message must NOT match: `\bsync\b.*\buncommitted\b` or `chore\(claude\)\s*:\s*sync`
- Handle every admitted repository independently and return a `repository_results` entry for each one
- Write the push-gate token after each successful commit by running `python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/write-push-gate-token.py" --repo-root "<GIT_ROOT>" --branch "<BRANCH>" --commit "<COMMIT_SHA>"`, the token's one writer: it resolves the token's path under the hook state directory and checks the commit is live HEAD before it writes
- Push-gate validates commit_sha only; expires_at is no longer written or checked
- **BULK mode commit message prefix (REQUIRED when BULK=true)**: every commit message MUST begin with `auto-bulk: end-of-cycle commit for <current-branch>` where `<current-branch>` is the actual current git branch of the repo being committed (run `git rev-parse --abbrev-ref HEAD`). This prefix matches `BLESSED_BRIDGE_RE`; the privilege guard requires a valid bulk-commit sentinel (written in Step 5) to allow the commit. Do NOT use this prefix when BULK=false.
```

Wait for changelog-analyst to complete. Echo its final status to the user.

#### Changelog-analyst result handling and retry protocol

Read changelog-analyst's structured status block verbatim (see `agents/changelog-analyst.md`
§Structured Final Status Output): the producer-stop gate (G2) validated it against
`changelog-status.v1` at the analyst's own stop. It carries `commit_status`,
`repository_results[]`, and, when applicable, `failure_code`, `failure_reason`, and
`auto_bulk_commits[]`. In normal mode a result whose repository roots/order do not
exactly equal `REPOSITORY_PLAN` is not accepted as a landing (the schema does not
hold the plan): it names no file, so the changelog-analyst dispatch whose status block
it is runs again (Routes) and its status is read again.

**Handle each commit_status value:**

#### status = `committed`
Every planned repository reached `committed` or `nothing_to_commit` (the status says so).
Continue to Step 8 normally.

#### status = `partially_committed`

At least one repository commit already landed and a later repository failed. Print
the complete ordered `repository_results`, the first failure, and `remaining_repos`.
Do NOT claim rollback or cross-repository atomicity, and do NOT run Step 8 yet.
Revoke all still-unused grants for this task/session, then continue with the
remaining repositories in order: rebuild the plan for only the still-dirty owned
material, re-mint fresh grants, rerun the planning dry-run and QA, and
re-dispatch. The plan may cover only the still-dirty owned material;
repositories already clean must return `nothing_to_commit`, not receive a synthetic
recovery commit merely because another planned repository remains dirty.

#### status = `nothing_to_commit`
Print: `WARNING: changelog-analyst found nothing to commit after exclusions (plan computed OK). Verify the task cycle produced staged changes.`

If the result carries `push_gate_reconciliation_declined`, ALSO print:
`WARNING: HEAD <sha> has no push-gate token and could not be attributed to this session (<reason>); /push stays blocked for this session.`
Do not retry and do not attempt to tokenize HEAD by any other route — the refusal is a
rejected operation, never bypassed. Report the stalled operation in one line,
`OPERATION_STALLED: push-gate token for HEAD <sha>: <reason>; /push stays blocked for this
HEAD until a human pushes it or its originating session re-runs /commit` (see
`agents/changelog-analyst.md` §Push-gate reconciliation, "The accepted residual"); no
decision of the owner's changes it inside this command, so nothing is asked. The landed
commit itself stands; only the push gate waits.

Continue to Step 8 (skip spec-update if no real commit occurred — Step 8 skip conditions apply).

#### status = `push_gate_reconciled`

No new commit was created. A prior commit ATTRIBUTED to this task was already at HEAD without
a push-gate token, and changelog-analyst has now written the missing token for that existing
commit. Say "attributed to", not "this task's own": attribution is by journal entry, and
`hooks/lib/commit_journal.py::_parent_linkage_verified` records a narrow race in which the
attributed commit was made by a peer that committed from the same recorded parent.

Seven routes reach that state, and nothing here can tell which one applied: the Phase 10
step-6 token write itself failed or was refused; the invocation was interrupted between the
commit and the token write; the commit was already pushed — `/push` deletes the token on success,
and with no upstream configured the already-published check (condition 7) cannot establish
publication and permits reconciliation anyway; a peer replaced HEAD with a SAME-PARENT commit
inside the post-lock window — the journal accepted the peer's HEAD (linkage validates: same
first parent) while the token writer's pre-write HEAD-stability check returned
`push_gate_race` and wrote no token, so on this route the reconciled commit is the PEER's,
not this session's; HEAD left this session's own journaled commit before that same pre-write
check — again `push_gate_race`, no token — and was LATER RESTORED to it, which re-enables the
match because freshness is compared against live HEAD at query time and no entry is ever
marked superseded (so a HEAD move defeats reconciliation only while it lasts, never
permanently); or the token namespace drifted in either segment of the token path — tokens are
keyed by branch AND by one session alias, while journal matching ignores the recorded branch
entirely and accepts MEMBERSHIP in a set of up to four session ids, so renaming/switching
branch at the same unpublished HEAD, or a later run resolving a different alias of the same
set, leaves the old token in the old slot and reconciliation mints into the empty new one.
`agents/changelog-analyst.md` §Push-gate
reconciliation, "Which cases actually survive", is the canonical enumeration — do not restate
any one route as THE cause, and do NOT re-add same-session fan-out contention: rule 7 compares
against the writer's own session id and cannot fire within one session (see "Why rule 7 cannot
be one of these cases").

See that section for the full trigger conditions; it only permits this outcome when the token
slot was EMPTY (DO NOT rule 7 is never relaxed) and when a commit-event journal entry —
appended by the PostToolUse hook layer, not by the committing agent — attributes that HEAD
commit to this task AND this session. That entry is appended once the committing shell call
has exited and the commit lock is released, NOT at the moment the commit returned, so a peer's
commit can land in that window and be recorded under this session's ids. RULE: attribution
therefore also requires VERIFIED PARENT LINKAGE — the entry's recorded parent must be the
actual first parent of its recorded resulting sha, in the bound repository — and fails closed
whenever that cannot be read. Do not remove that condition.

The token is written by `scripts/write-push-gate-token.py`, which writes it only for a
commit that is live HEAD, and `/push` decides on it; this handler re-checks neither.

Print: `INFO: no new commit; wrote the missing push-gate token for existing commit <reconciled_commit_sha>. /push is now unblocked.`

Continue to Step 8. Note that Step 8's skip condition is worded around "no real commit
occurred": a reconciliation creates no commit, so Step 8 SKIPS the spec-update dispatch. Keep
that skip — it is correct because this invocation has no cycle result of its own to fold into
a spec, and dispatching here would append a block describing work this invocation never did.

Do NOT read the skip as evidence that the spec is already current. On the route where the
originating cycle kept running and itself observed "no push-gate token written" — the failed
or refused Phase 10 token write — its own Step 8 skipped the spec-update because the cycle's
status was not `committed` (`scripts/step7-spec-update.py` skips on that status, whatever the
reason), so the update was never performed. On the interruption route the cycle never reached
Step 8 at all, with the same result. On BOTH routes where the pre-write HEAD-stability check
fired — the same-parent race and the HEAD round trip — the cycle returned `failed` with
`push_gate_race`, which is not in the retryable set; that code is routed by the
non-retryable handling below (rerun the cause; a hook rejection pauses and reports),
and Step 8 runs after the landing — previously the handler ended there before Step 8 ran.
**On those four routes the originating cycle's spec update was not performed by that
cycle and remains owed.** This reconciliation does not perform it (see the skip above);
the owed update is a finding for the spec-update path, not an accepted outcome: carry it
into a separate explicit cycle and do not treat the spec as current.

The four are not equally recoverable, and the difference decides what a follow-up cycle should
describe. On three of them the owed update describes exactly the commit that was reconciled,
because that commit is this session's own. On the same-parent race ALONE the gap is
compounded: the update that never ran described THIS session's commit, which a peer had
already replaced, while the commit later reconciled is the PEER's, whose spec state belongs
to a cycle this session never saw. Reconciliation performs the update on none of them.

The remaining three routes — already-pushed, branch drift and session drift — are weaker
exceptions than they look, and they are why the skip must stay unconditional rather than
conditioned on the spec's state: on all three, the originating cycle DID write its token
(into the then-current branch's slot on branch drift, under the then-resolved alias on
session drift) and DID reach Step 8. But reaching Step 8 does not
guarantee the spec was updated: Step 8's own dispatch-failure contract permits the update
dispatch to FAIL — print a WARNING and continue — so even an already-pushed or
namespace-drifted commit can have missed its spec update. What these routes guarantee is only
that the cycle reached its spec-update step; whether the update landed is unknowable from
here. So an empty slot is equally consistent with a completed cycle and with one whose update never landed.
Neither this handler nor changelog-analyst can tell them apart, so neither may assume either.

#### status = `nothing_to_commit_precommitted`
Record `auto_bulk_commits[]` from the structured output in the Step 8 summary.
Print: `INFO: Changes were already committed in an auto-bulk commit. auto_bulk_commits: <auto_bulk_commits[]>`
Continue to Step 8.

#### status = `failed` — retryable grant codes

Check `failure_code`:

**Retryable** (`grant_missing`, `grant_expired`, `grant_consumed`) only when
`repository_results` proves that zero repository commits landed:

Retry with a fresh grant:
1. Revoke stale grants, rebuild `REPOSITORY_PLAN`, and write a fresh bound grant
   for every newly planned repository. Never refresh only the control-root grant:
   ```bash
   python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/write-commit-grant.py" \
       --task-id "$TASK_ID" --repo-root "$PLANNED_REPO_ROOT" \
       --revoke-existing-for-task "$TASK_ID"
   ```
   Revoke once, then issue the remaining repository grants without repeating the
   revoke flag. This keeps all repo-bound capabilities available for one retry.
2. Re-run the internal dry-run and QA because rebuilding the plan changes the CAS
   snapshot, then re-dispatch changelog-analyst with that freshly approved plan.
3. Parse the retry result using the same status table as the initial result:
   - If `commit_status = committed` or `commit_status = nothing_to_commit_precommitted`: continue to Step 8 (handle as specified above for each status).
   - If `commit_status = nothing_to_commit`: warn user and continue to Step 8.
   - If retry `commit_status = failed`: print `ERROR: changelog-analyst retry failed (failure_code: <code>, reason: <reason>).` and route the cause as for a non-retryable code below; do NOT proceed to Step 8 until a landing is confirmed.

**Non-retryable** (`git_error`, `staging_error`, `hook_blocked`, `scope_violation`,
`repository_plan_invalid`, or any other code; also every failure after one or more
repository commits landed):

Print: `ERROR: changelog-analyst failed with failure_code: <failure_code>. Reason: <failure_reason>.`
Do NOT proceed to Step 8 until a landing is confirmed. The file `failure_reason` names goes
to its owner (Routes); a reason that names no file goes back to the changelog-analyst
dispatch whose status block reported it. Then re-run Step 5 through Step 7 for the
repositories not yet landed, with no round cap. `scope_violation` means the tree changed
after QA reviewed it: rebuild the plan and dispatch a fresh QA over the actual set.

**A hook rejection** (`hook_blocked`, or any hook refusing a tool call during `/commit`) is
the owner's decision (CLAUDE.md Subagent Hook Discipline #1-#3): the rejected operation is
never retried without the owner's grant, and never wrapped or bypassed. Ask one
AskUserQuestion — header `Authorize`,
question `<hook> refused <the operation> for task <TASK_ID>: authorize it?` with the hook's
output verbatim, options `Authorize it` (description: the exact command the owner runs to
authorize it, for example `/allow <op> <args>`; `/commit` runs the operation again once the
grant exists) and `Do not authorize` (description: `/commit` goes on without that operation
where every acceptance criterion still holds without it, Hook Discipline #4).

### Step 8: Spec-update dispatch (post-commit, advisory)

**This step is dispatched by `/commit` from its own orchestrator context — NOT from within changelog-analyst.** changelog-analyst has already returned before this step executes.

Skip this step entirely if ANY of the following are true:
- `BULK=true`
- `DRYRUN=true`
- `TASK_ID` is empty
- changelog-analyst did not report a successful real commit (no push-gate token written, or changelog-analyst reported an error)

**Observable Step 8 trace (AC-05 Phase B contract — task 20260524-205206 iter-2)**: when env var `COMMIT_STEP8_TRACE=1` is set, Step 8 MUST emit a deterministic single-line marker to **stderr** at every decision point. The markers are:

- `STEP8_SKIPPED: bulk=true` — at the BULK=true skip branch
- `STEP8_SKIPPED: dryrun=true` — at the DRYRUN=true skip branch
- `STEP8_SKIPPED: task_id_empty` — at the empty-TASK_ID skip branch
- `STEP8_SKIPPED: changelog_no_real_commit` — at the no-push-gate / changelog-error skip branch
- `STEP8_SPEC_UPDATE_DISPATCHED: task-id=<TASK_ID> stage=<1|2> spec_path=<SPEC_PATH>` — emitted IMMEDIATELY BEFORE the Agent dispatch in stages (1) and (2)
- `STEP8_NO_SPEC: task-id=<TASK_ID>` — at stage (4)'s empty-set outcome
- `STEP8_UNLINKED_SPEC: task-id=<TASK_ID> count=<N> paths=<paths>` — at stage (4)'s one-or-more-element outcome (printed; nothing is dispatched)

This trace is OFF by default (no env var). When ON, the markers are emitted to stderr only; they MUST NOT affect stdout, exit codes, or dispatch behavior. `scripts/step7-spec-update.py` is the executable reference embodiment of the SELECTION portion of this Step 8 specification (stages 1-4 + STEP8_* markers). The script does NOT perform the Agent dispatch described in the "Dispatch payload" subsection below — that step is the orchestrator's responsibility, performed as a Claude Code Agent call after the selection marker emits. The orchestrator MAY either follow the prose directly OR invoke the harness to compute the selection; in both cases the orchestrator must perform the real Agent dispatch when a stage 1 or stage 2 path is selected.

When `BULK=false` AND `DRYRUN=false` AND `TASK_ID` is set AND changelog-analyst reported success:

Set `DEV_DOCS_ROOT` using the same CONTROL_ROOT logic as Step 7: `DEV_DOCS_ROOT=${CONTROL_ROOT}/docs/dev` (where `CONTROL_ROOT` is the resolved control root from the Step 7 dispatch — `$HOME`, not an author-absolute literal). Use absolute paths throughout Step 8.

**Step 8 algorithm (verbatim contract — total-ordered, deterministic):**

The algorithm is total-ordered and mandatory. Implementers MUST NOT introduce wording that admits implementer discretion; every nondeterminism alias is forbidden by AC5-V3. Prior-cycle artifacts MUST NOT be matched: the glob and content predicates are anchored to the CURRENT cycle's `${TASK_ID}`; no cross-cycle drag-in. This operationalizes the user binding directive that prohibits loading any non-current-cycle content (verbatim Chinese phrasing preserved at `docs/dev/ticket-20260519-211515.md`, Standard 6 exemption scope).

(1) context.spec_path first.
    If `${DEV_DOCS_ROOT}/context-${TASK_ID}.json` field `spec_path` is non-null AND the file at that path exists as a regular file, dispatch `/dev` with that `spec_path` (when `COMMIT_STEP8_TRACE=1`, emit `STEP8_SPEC_UPDATE_DISPATCHED: task-id=${TASK_ID} stage=1 spec_path=<SPEC_PATH>` to stderr immediately before the dispatch). STOP.

(2) Continuation spec line (parenthetical-qualifier + markdown-bullet + backtick tolerant).
    Else parse `${DEV_DOCS_ROOT}/close-report-${TASK_ID}.md` fence-aware: read each line outside a fenced code block (skip ranges between ``` and ```). Apply the regex

        ^[-*+]?\s*Continuation spec(\s*\([^)]*\))?\s*:\s*`?(docs/dev/specs/spec-[^\s`]+\.md)`?\s*$

    against each non-fenced line, where:
      - Leading `^[-*+]?\s*` accepts an optional markdown list marker (`- `, `* `, `+ `).
      - Optional `(\s*\([^)]*\))?` accepts parenthetical qualifiers such as `(from prior NO)`, `(this cycle)`, `(rebuilt)`.
      - Inline backticks `` ` `` around the path are accepted (markdown code-span).
    A conforming close-report line looks like:

        - Continuation spec (from prior NO): `docs/dev/specs/spec-20260520-044700.md`

    Note the leading dash AND the backticks AND the parenthetical qualifier — ALL THREE must be tolerated.
    If exactly one such line matches AND the captured path exists on disk, dispatch `/dev` with that path, emit a WARNING `linked via close-report, not context.spec_path` (when `COMMIT_STEP8_TRACE=1`, also emit `STEP8_SPEC_UPDATE_DISPATCHED: task-id=${TASK_ID} stage=2 spec_path=<SPEC_PATH>` to stderr immediately before the dispatch). STOP.

(3) Mtime window + machine-readable marker predicate (final stage).
    Else glob `docs/dev/specs/spec-YYYYMMDD-HHMMSS.md` (basename pattern enforced) with mtime in [close-report mtime - 24h, close-report mtime + 1h]. For each candidate, run `grep -lF "<!-- spec-continuation-of: ${TASK_ID} -->" candidate.md` — this is the ONLY content predicate allowed; no other grep, no free-form content scan. Collect the set of candidates that pass both the basename pattern, mtime window, and machine-readable marker grep.

(4) Outcome (advisory: it prints and dispatches nothing).
    - If set is empty: print `No spec associated with task-id ${TASK_ID}` and exit 0. When `COMMIT_STEP8_TRACE=1`, also emit `STEP8_NO_SPEC: task-id=${TASK_ID}` to stderr.
    - If set has exactly one element: print `spec produced this cycle but not linked in context: <path>`. When `COMMIT_STEP8_TRACE=1`, also emit `STEP8_UNLINKED_SPEC: task-id=${TASK_ID} count=1 paths=<path>` to stderr.
    - If set has multiple elements: print `multiple specs produced this cycle without context linkage: <paths>; explicit context.spec_path required`. When `COMMIT_STEP8_TRACE=1`, also emit `STEP8_UNLINKED_SPEC: task-id=${TASK_ID} count=<N> paths=<paths>` to stderr.

**Dispatch payload (when stage 1 or 2 selects a path)**

Dispatch an inline Agent (do NOT invoke `/spec-update` as a slash-command) with the following prompt, substituting `TASK_ID`, `SPEC_PATH`, and `DEV_DOCS_ROOT`:

```
You are executing the spec-continuation logic for task-id=<TASK_ID>.

Target spec file: <SPEC_PATH> (absolute path — this file exists; update it in place through its one writer, <HARNESS_ROOT>/scripts/spec-write.py, as spec-update.md's Continuation-spec mode describes).

DO NOT:
- Invoke /spec-update as a slash command
- Create a new spec file; only update the existing one at <SPEC_PATH>
- Write <SPEC_PATH> any other way than through <HARNESS_ROOT>/scripts/spec-write.py
- Overwrite or delete prior "### Cycle N" sections
- Modify any git state, commit grants, push tokens, or command files
- Write any artifacts outside <SPEC_PATH>
- Read or modify files outside <DEV_DOCS_ROOT>/, <SPEC_PATH>, and <HARNESS_ROOT>/commands/spec-update.md (allowed: read spec-update.md for instructions)

Follow the ## Continuation-spec mode instructions from <HARNESS_ROOT>/commands/spec-update.md exactly:

- The active task-id is <TASK_ID>.
- The target spec to update is <SPEC_PATH>. Update this spec; do not create a new one.
- Gather source artifacts from <DEV_DOCS_ROOT>/:
    context-<TASK_ID>.json, dev-report-<TASK_ID>*.json, qa-report-<TASK_ID>*.json,
    close-report-<TASK_ID>.md, completion-<TASK_ID>.md
- Determine the next cycle number: max(existing "### Cycle N" headings) + 1; if none exist, use Cycle 1.
- Append the new cycle block to the spec through spec-write.py, as spec-update.md's Continuation-spec mode says. Never overwrite prior cycles.
- Take each section's text from the report that holds it (dev reports' dev.tasks_completed, QA reports' qa.spec_section_updates, the context), as spec-update.md lists.
- Populate sections 2-8 per the spec-update continuation-spec instructions.
- Output the spec path when done.
```

If the Agent dispatch fails for any reason (error, timeout, or exception), retry the identical dispatch (same prompt, same `TASK_ID`/`SPEC_PATH`/`DEV_DOCS_ROOT` substitutions) exactly once. If the retry also fails for any reason, print `WARNING: spec-update dispatch failed for task-id=${TASK_ID} — spec not updated` and continue. The commit is already recorded; neither the initial failure nor an exhausted retry rolls back or affects the commit — Step 8 (including its one retry) runs entirely after the commit has already landed and must never block or delay it.

**Reversal-rationale guidance for changelog-analyst (R9 cross-reference)**: the binding rule that any forward-fix commit which intentionally reverses prior behavior MUST include `Reverses <SHA>: <one-line rationale for why prior reasoning no longer holds>` in the commit-message body lives in `agents/changelog-analyst.md` Phase 6 (the SOLE binding landing). `/commit` orchestrator does NOT enforce the rule directly; changelog-analyst owns commit-message construction and is the contract holder.

## `--auto` mode: batch-discover and sequentially commit (Must-Have #7, task 20260808-035658-lanel)

`--auto` discovers every `commit_pending` PARENT task-id and walks each one,
ONE AT A TIME, through the exact same unmodified **Step 3 → Step 8** body (the
`### Step 3` through `### Step 8` headings above, up to this section) an
explicit `/commit <task-id>` would run — `--auto` performs Step 1-2's job itself
(binding `FORCE=false`, `BULK=false`, and the current parent's `TASK_ID`)
before entering that shared body. It is structurally distinct from the
human-only `--bulk` escape hatch: `--bulk` skips Step 3 entirely; `--auto`
never skips it.

1. **Discover** the candidate parent snapshot (frozen once, at the start of
   the batch):

   ```bash
   PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
   source "${CLAUDE_HOME:-$HOME/.claude}/venv/bin/activate" 2>/dev/null || true
   mapfile -t COMMIT_PENDING_PARENTS < <(python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/dev-lifecycle.py" list-actionable --next-action commit --project-dir "$PROJECT_ROOT")
   ```

   `list-actionable` returns a deterministically sorted list of
   `kind == "ticket"` parents, one per line, the task-id first (Step 3's call is
   each parent's one disposition call).

2. **Walk each parent sequentially** — no two parents run concurrently, and
   parent N+1's walk does not begin until parent N's walk has landed. For each
   `TASK_ID` in `COMMIT_PENDING_PARENTS`, in order, bind `FORCE=false`,
   `BULK=false`, `DRYRUN` as passed to the batch (default `false`), `QA_CODEX`
   as passed to the batch, and run **Step 3** through **Step 8** exactly as
   written for that `TASK_ID`. Nothing in Steps 3-8 is aware `--auto` is
   driving it.

3. **Each parent completes**: its walk ends only by landing (`commit_status ∈
   {committed, nothing_to_commit, push_gate_reconciled,
   nothing_to_commit_precommitted}`) or, under `--dry-run`, the preview end. A
   gap, a `COMMIT: REJECT` or a changelog-analyst failure is routed inside the
   walk as Steps 3-7 say; a `partially_committed` parent continues its
   remaining repositories in order under fresh grants (Step 7). A hook
   rejection, or another decision only the owner can make, inside a parent's
   walk is one AskUserQuestion naming that parent and the decision (for a hook,
   Step 7's hook-rejection question); after the answer the walk goes on.

4. **Batch summary**: once every parent has landed, print one line per parent:
   `task-id: <landed outcome>`.

Human-operator verification of this mode (QA cannot literally invoke
`/commit --auto` — `disable-model-invocation: true` plus `settings.json`'s
global `Skill(commit:*)` deny) is documented in
`docs/dev/ticket-20260808-035658-lanel.md` AC-L21: a separate
human-operator-executed transcript at
`docs/dev/human-operator-transcript-<task-id>.md`, using the
`PARENT_START: <task_id>` / `PARENT_END: <task_id> outcome=<...>` schema.

## Close-gate verification reference

Step 3's disposition is the only gate this command owns. All git operations (staging, committing,
nested-repo handling, push-gate write) are delegated entirely to `changelog-analyst`.

## Privilege guard compatibility note

`pretool-git-privilege-guard.py` is REGISTERED in `settings.json` (PreToolUse, Bash matcher).

Authorization flow for changelog-analyst commits:

1. `/commit` writes the dispatch-snapshot manifest, and `write-commit-grant.py` refuses to mint without it plus a live user-intent sentinel (Step 5, `hooks/lib/commit_pipeline.verify_pipeline_dispatch`). Every minted grant records `minted_by` (origin `commit-pipeline` + the evidence checked) and `expected_consumer`.
2. `/commit` writes `<state-dir>/claude-commit-grant-<SID>-<nonce>.json` before dispatching changelog-analyst (Step 5).
3. Dispatching changelog-analyst fires `hooks/pretool-commit-dispatch-attest.py` (PreToolUse:Agent), which writes `<state-dir>/claude-commit-dispatch-<SID>-<nonce>.json`. That hook is the only intended writer, and an attestation it wrote exists only because a dispatch really happened. Bash writes into that namespace are intercepted verb by verb by `pretool-bash-safety.sh` Layer 1.E3, which raises the cost of forging one; being a verb blacklist it is not an absolute barrier, so the attestation is never trusted on existence alone — step 4's identity requirement is what it is weighed by.
4. `_grant_provenance_refusal(grant, path, data)` then refuses any grant that is not a pipeline product (`minted_by.origin`), any caller that is not a dispatched subagent (empty `agent_id` — the main agent), and any caller that is not the subagent this dispatch produced (the attestation's `prompt_sha256` must equal the digest of the prompt that dispatched the caller, read from the caller's own transcript; another subagent was dispatched with another prompt and is refused). Nothing is written to decide this, so the same subagent commits every repository of its plan under the same attestation. A grant is a NAMED ticket, not a bearer ticket: holding it is not sufficient. A provenance refusal skips that candidate and is reported only if no candidate authorizes the commit, so one stale or legacy grant cannot shadow a legitimate one. Closes disclosure items 1 and 2 of `1fdbd3767`.
5. `_evaluate_commit(command, data)` collects EVERY unexpired grant candidate (the any-SID glob covers the subagent SID-propagation fallback) and SELECTS the one whose `repo_root`/`branch`/`expected_head` match the commit's target repo — recency alone never decides.
6. The selected grant passes the authoritative binding re-check (`_enforce_commit_grant_binding`: redirect vectors, then repo/branch/HEAD). A Bash call containing MORE THAN ONE `git commit` invocation is hard-BLOCKED before any of that: every invocation in one call would be validated against the same pre-execution HEAD under one lock, so a second commit would ride the first one's authorization (audit round 3, F5). One grant authorizes exactly one commit; issue each as its own call. The grant is then SPENT by deleting it (only one event's unlink can succeed, so two events racing for one grant cannot both spend it), and the guard writes a pointer keyed on this tool event's `tool_use_id`, recording that raw id and the grant's journal fields (`hooks/lib/commit_journal.py` `write_event_pointer`; the name `claude-commit-event-*` is outside every grant reader's glob). The pointer is published ATOMICALLY (content written to a temp name, then `link(2)` into the final name), so a reader never sees a torn pointer (audit F7).
7. Grant validates: expires_at (30 min window); no message-hash validation. The finalizer (`posttool-allowlist-consume.py`, registered under PostToolUse AND PostToolUseFailure) classifies the terminal result from the payload shape — not from an exit code: success journals the commit event from the pointer; every TERMINAL result removes the pointer. A NONTERMINAL background-launch receipt (the command is still running) finalizes nothing (audit F2/F3); its pointer ages out through the finalizer's stale reading, which the Stop cleanup also takes. A failed commit does not get its grant back: its next attempt takes a fresh grant from Step 7's retry routes. An event with no usable `tool_use_id` is authorized and left unjournaled.

**DO NOT extend `BLESSED_BRIDGE_RE` with conventional commit patterns** (e.g. `^feat\(`, `^fix\(`).
This would allow any agent that learns the commit format to bypass the guard — destroying the
security model. The grant-file mechanism provides the correct narrow authorization.

auto-bulk bridge commits (matching BLESSED_BRIDGE_RE) require a **bulk-commit sentinel**
written by `/commit --bulk` Step 5 (`scripts/write-bulk-commit-sentinel.py`, 30 min TTL,
multi-use). Without it the guard blocks the commit even if the message prefix is correct. With
it, the commit is still DEFERRED (blocked, retry next cycle) while a `/commit` grant that could
actually authorize a commit HERE is live — the deferral applies the same repo/branch/HEAD
binding the commit validation applies, so a foreign-repo grant no longer defers auto-bulk
for its whole TTL (audit round 3, F6); a spent grant no longer exists.
changelog-analyst non-bulk commits use the single-use grant-file path.
The BLESSED_BRIDGE_RE check runs first in `_evaluate_commit`, followed by the sentinel check.

## Related

- `/close <task-id>` — may run first; `/commit` completes an unclosed task itself (Step 3 runs `/close` Steps 1-2 for it)
- `/push` — must run after `/commit` (reads the push-gate token written by changelog-analyst)
- `agents/changelog-analyst.md` — the subagent that does all git work
