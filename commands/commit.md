---
description: Commit session changes via changelog-analyst subagent
disable-model-invocation: true
---

# /commit

Agentic commit command. Validates the close-gate (unless `--bulk`; `--force` is deprecated and no longer bypasses it), then dispatches
the `changelog-analyst` subagent to classify files, stage them, and create real
branch commits. Normal task mode admits every task-owned path only after partitioning
it across an explicit supported-repository set; the control checkout and `~/.claude`
are supported without a project-root override.

## Usage

```
/commit [<task-id>] [--force] [--bulk] [--dry-run] [--codex] [--auto]
```

| Flag | Meaning |
|------|---------|
| `<task-id>` | Optional when the session context identifies the active cycle: if omitted (and `BULK=false`, `AUTO=false`), the orchestrator infers the task-id from the current session's conversation context (see Step 2; ambiguity never guesses, it asks); an explicit task-id is always allowed and authoritative. Unused in `--bulk` mode; rejected as an explicit token by `--auto` (which never enters Step 2). Task-id from the completed `/dev` cycle (e.g. `20260516-212024`). |
| `--force` | **Deprecated (lane L7, AC11): no-op alias of the normal path.** No gate is bypassed — Step 3's close-gate and Step 6's pre-commit QA gate both still run exactly as a bare invocation would. Human-only (enforced by `disable-model-invocation: true`). The only remaining effect is a best-effort audit-log append (Step 4), kept for backward-compatible invocation. |
| `--bulk` | Smart batch mode — group by task-id then subsystem, commit coherently, flag orphan files separately. Human-only (enforced by `disable-model-invocation: true`). Skips the close gate (Step 3); retains the pre-commit QA gate (Step 6). |
| `--dry-run` | Print what would be staged/committed (and the QA verdict); do not execute the real commit. |
| `--codex` | In the pre-commit QA gate (Step 6), QA additionally runs an adversarial Codex round on the planned per-file changes (each PLAN_GROUPS path vs HEAD), not the staged index. Without it, QA does a single-round self-review. |
| `--auto` | Discover every `commit_pending` PARENT task-id and walk each one, sequentially, through the SAME non-bulk Steps 3-8 gate a bare `/commit <task-id>` would run — never concurrently, never skipping the close gate. Structurally distinct from `--bulk` (see `--auto mode` below). Human-only (enforced by `disable-model-invocation: true`). |

## Step-by-step workflow

### Step 1: Parse arguments

Parse `$ARGUMENTS`:
- Strip `--force` if present → set `FORCE=true`; else `FORCE=false`
- Strip `--bulk` if present → set `BULK=true`; else `BULK=false`
- Strip `--dry-run` if present → set `DRYRUN=true`; else `DRYRUN=false`
- Strip `--codex` if present → set `QA_CODEX=true`; else `QA_CODEX=false`
- Strip `--auto` if present → set `AUTO=true`; else `AUTO=false` (default — every `--auto`-specific rule below is inert)
- Remaining token (if any) is `TASK_ID`

**`--auto` flag-combination check (Must-Have #8, task 20260808-035658-lanel)**: when
`AUTO=true` and `TASK_ID` is non-empty, or `FORCE=true`, or `BULK=true`, take no
action and print
`AWAITING_INPUT: need=a legal flag combination (--auto takes no task-id, --force, or --bulk); why=--auto discovers its own parents and never skips the close gate; addressee=human`
then resume at this step in place when the corrected invocation arrives. `--auto` and `--dry-run`/`--codex` MAY combine
(each `--auto` walk below still honors `DRYRUN`/`QA_CODEX` exactly as the
non-`--auto` path does). This mirrors `scripts/dev-lifecycle.py`'s
`validate_auto_flag_combination(True, TASK_ID, FORCE, BULK)` pure predicate.
When `AUTO=true` and the combination is legal, skip Step 2's single-task
resolution — control passes to the `--auto mode` section below, which binds
`TASK_ID` itself once per discovered parent and drives Steps 3-8.

### Step 2: Resolve task-id (unless --bulk or --auto)

If `BULK=false` AND `AUTO=false` (a legal `--auto` invocation skips Step 2 entirely —
see the Step 1 rejection block; `--auto` binds `TASK_ID` itself per discovered parent):
- If `TASK_ID` was supplied, use it directly. An explicit task-id is always allowed and
  authoritative.
- If `TASK_ID` is empty: the orchestrator invoking `/commit` infers the task-id from the
  current session's conversation context — the parent task-id of the active `/dev` cycle,
  `/do` cycle, or the `/close` that just ran in this session (the same bare-invocation
  resolution `/close` uses; see `commands/close.md` § Task-id resolution). Inference comes
  from conversation context ONLY: there is NO filesystem scan and NO default-to-newest.
  Do NOT scan close-reports by mtime — mtime-scan picks up unrelated reports from other sessions and causes close-gate failures on unrelated tasks.
  - **Uniqueness precondition**: inference succeeds ONLY when the conversation identifies
    exactly ONE unambiguous candidate task-id; with two or more candidate cycles, or any
    doubt which cycle is meant, do NOT guess — take the no-context branch below. The
    close-gate hard checks (close-report existence, `CLOSE: YES` final line,
    filename/task-id match) backstop an inference landing on a task with NO passing
    close-report, but NOT one landing on a different validly-closed task — which is why
    ambiguity never guesses.
  - If the orchestrator cannot identify an active cycle's task-id from conversation
    context (e.g. a fresh session with no cycle context), or the uniqueness precondition
    fails, print:
    `AWAITING_INPUT: need=an explicit task-id (/commit <task-id>), or --bulk for batch mode; why=no unambiguous active cycle task-id in this session; addressee=human`
    and resume at this step in place once it arrives.

If `BULK=true`: `TASK_ID` may remain empty; changelog-analyst operates in bulk mode.

### Artifact-to-role routing and the awaiting-input line

Every finding from Step 3 through Step 5 is routed to the role that produced
the implicated artifact, repaired there, and re-checked. No code, table or
engine output is consulted: the orchestrator builds the entry itself, at the
call site, from the finding it just observed. `commands/close.md` uses the
same mapping, entry shape and awaiting-input line.

Eight-row mapping, first match wins, in this row order. Finding codes
(`commit#6`, `LATE_REPAIR_STATE_C`, ...) are display labels only; nothing is
looked up by code. A finding with no artifact path binds `path=$TASK_ID` and
lands on row 8. `CANONICAL_DEV_REPORT` is `ARTIFACT_CHAIN.canonical_dev_report`
and is set only when `ARTIFACT_CHAIN.mode` is `fanout`; when `ARTIFACT_CHAIN`
is not in hand but the cycle is known to be a fan-out (`FANOUT_MODE=true`), a
basename equal to `dev-report-${TASK_ID}.json` exactly counts as the canonical
aggregate (lane files `dev-report-${TASK_ID}-<suffix>.json` do not). The
canonical row precedes `dev-report*` so an aggregate finding is never mis-routed
to dev.

```bash
artifact_role() {   # $1 = artifact path (empty/unknown allowed); always prints a role
  local p base; p="$1"; base="${p##*/}"
  if [ -n "$p" ] && { [ "$p" = "${CANONICAL_DEV_REPORT:-}" ] \
      || { [ -z "${CANONICAL_DEV_REPORT:-}" ] && [ "${FANOUT_MODE:-false}" = true ] \
           && [ "$base" = "dev-report-${TASK_ID:-}.json" ]; }; }; then
    echo orchestrator; return   # row 1: canonical aggregate -> orchestrator reruns aggregate-dev-report.py
  fi
  case "$base" in
    dev-report*)                                    echo dev ;;                 # row 2
    *qa-report*)                                    echo qa ;;                  # row 3
    ticket*|ba-spec*|context*|acceptance-criteria*) echo ba ;;                  # row 4
    test-writer-report*|*manifest*)                 echo test-writer ;;         # row 5
    close-report*)                                  echo qa ;;                  # row 6
    changelog-status*)                              echo changelog-analyst ;;   # row 7
    *)                                              echo orchestrator ;;        # row 8 default, fail-closed
  esac
}
```

Required-action entry shape, built locally by the orchestrator whenever a
check fails: `{path, detail, source_check, producer_role}`. `path` is the
implicated artifact, `detail` says what is wrong, `producer_role` is
`artifact_role(path)`, and `source_check` is the single originating check
already in hand at that call site (the artifact-chain resolver,
`resolve-commit-repos.py`, `late-repair-controller.py resolve-effective-report`,
the close-report resolver, or the QA verdict line); any rerun data (command,
arguments) lives inside `source_check`. No other key exists. Because the
entry is built from the live finding, it is never empty on a failed check and
the loop below always starts.

Awaiting-input line, printed when only a human (or the orchestrator, for an
orchestrator-class input) can supply what the loop needs:

`AWAITING_INPUT: need=<what input>; why=<reason>; addressee=<human|orchestrator>`

This is a pending state, not an exit: nothing lands as complete while it
holds, no commit and no verdict line is written, and when the input arrives
the loop resumes at the same step in place. Cause set: a human-only operation
(`/allow`, deletion, freeing `/tmp`, a missing session environment variable),
a hook rejection (pause and report per the Subagent Hook Discipline; the
rejected operation is never retried, wrapped or bypassed), or a usage input
the human must supply (an explicit task-id, a legal flag combination). Any
other cause is routed through the loop, not waited on.

### Required-action dispatch-and-recheck loop

Applies at every call site below (Step 3 checks 1/2/4, Step 5's
late-repair, artifact-chain and repository-plan sites, Step 6 verdict
routing, Step 7 failure routing). Per failed check:

1. Build the entry (shape above) from the finding just observed.
2. Dispatch `producer_role` (Agent, `run_in_background: false`), scoped to the
   entry's `path` and `detail` and to the root cause of why the check keeps
   failing, not "rerun it again". `producer_role` = `orchestrator` means the
   orchestrator repairs or reruns it itself (row 1 reruns
   `aggregate-dev-report.py`; row 8 diagnoses and repairs). A missing lane
   artifact is a missing artifact whose row gives its role.
3. Rerun ONLY the entry's `source_check` (e.g. `resolve-dev-artifact-chain.py`,
   `resolve-commit-repos.py`, `late-repair-controller.py
   resolve-effective-report`, the close-report resolver) — never the whole
   `/commit` flow from scratch.
4. The check now succeeds: proceed. It still fails: apply the R15 progress
   test below.

**R15 progress measure (single definition for every loop in this file; same
semantics as `hooks/lib/progress_measure.py`).** Each round must change world
state: the implicated artifact's bytes changed, or the set of unresolved
findings strictly shrank to a set not seen in an earlier round. A round with
neither (including a revisit of an earlier unresolved set) is no progress, and
escalates to orchestrator arbitration: the orchestrator reruns the
`source_check` itself, decides, and either repairs it itself or re-dispatches
the producer with its own finding. There is no attempt counter, no
unbounded same-state retry, and no pass granted because retries ran out.
A repair that completed is appended as a disclosure record (path, problem,
role, fix evidence) for the commit message's `Disclosures: <n>` line; a
disclosure is never a substitute for the repair. When the next step needs an
input only a human can give, print the awaiting-input line and resume in
place on arrival. Environment-class system faults follow the harness
environment rule (R14), not this loop.

### Step 3: Close-gate validation (skip if BULK=true; `--force` is deprecated and never skips this step — AC11)

If `BULK=false`:

Resolve the close-report path via the helper script (which probes
subproject docs/dev/ first, then falls back to the resolved control-root
`docs/dev/` — `${CONTROL_ROOT}/docs/dev/`, where `CONTROL_ROOT` resolves to
the harness/project root, not an author-absolute literal — see
`scripts/resolve-close-report.sh`). The script exits 1 when no candidate
file exists; `CLOSE_REPORT` still holds the fallback path for the error
message in check 1 below.

```
CLOSE_REPORT="$(bash ~/.claude/scripts/resolve-close-report.sh "$TASK_ID")" || true
```

Run these checks in order (checks 1, 2, 4 each build a required-action entry
from the failure and route it through the dispatch-and-recheck loop above;
check 3 remains advisory and only warns). In every case `source_check` is this
close-report resolution plus the check itself, and `producer_role` is
`artifact_role "$CLOSE_REPORT"`; when the only fix is a human-only operation
(for example re-running `/close`), print the awaiting-input line naming it and
resume at this check on arrival.

1. **File exists**: `CLOSE_REPORT` must exist. On failure, build the entry
   `{path: "$TASK_ID", detail: "no close-report for task ${TASK_ID} at ${CLOSE_REPORT}", source_check: <the resolve-close-report.sh call plus this existence test>, producer_role: <artifact_role of that path>}`
   (failure label `commit#6`), dispatch `producer_role`, rerun that check, and
   apply the R15 test until the file exists.
2. **Last non-empty line starts with CLOSE: YES**: extract the last non-empty line from the file and verify it begins with `CLOSE: YES`. Accepted variants:
   - `CLOSE: YES`
   - `CLOSE: YES - with disclosures: <n> items`
   - `CLOSE: YES — FORCED`
   - `CLOSE: YES - degraded codex consultation: codex_status=<...>`
   - `CLOSE: YES — codex disabled by user`
   - `CLOSE: YES (FORCED)`
   On failure, build the entry
   `{path: "$CLOSE_REPORT", detail: "close-report does not end with CLOSE: YES (found: <last-line>)", source_check: <re-read of the close-report's last non-empty line>, producer_role: <artifact_role of that path>}`
   (failure label `commit#7`), dispatch `producer_role`, rerun that read, and
   apply the R15 test.
   **Dry-run carve-out**: check 2 — and check 2 alone — does
   not abort (and never reaches the dispatch above) when `DRYRUN=true`, where `DRYRUN` is exactly the value parsed from the
   user's `--dry-run` argument in Step 1 and nothing else. Print
   `Close-gate: check 2 relaxed for --dry-run (found: <last-line>). Preview only — no commit will be created.`
   and continue with check 3. When `DRYRUN=false`, check 2 dispatches exactly as written
   above. Checks 1 and 4 and the `CLOSE_REPORT` binding are never relaxed under
   either value (check 3 is advisory for ALL invocations — see check 3; that is independent of `DRYRUN`). Read the trigger from Step 1 only: the Step 6 planning phase raises
   `DRYRUN` internally on every invocation, so a trigger keyed on "a dry-run is
   executing" would admit a plain `/commit` with a failing close-report through to a
   real commit in Step 7.
3. **Mtime staleness (advisory — never aborts)**: if close-report mtime is older than 86400 seconds (24 h), print `Close-gate: WARNING — close-report for task ${TASK_ID} is older than 24h (mtime: <mtime>). Proceeding — staleness is advisory. Re-run /close if the tree has drifted since this approval.` and continue with check 4. Age alone never blocks a commit: wall-clock age is only a proxy for tree drift, and the Step 6 pre-commit QA gate reviews every planned file's actual change vs HEAD on every invocation. Known widening, disclosed: Step 6 does NOT re-validate changes against the closed cycle's acceptance criteria, so an aged `CLOSE: YES` vouches indefinitely for a tree that may have drifted in-scope — accepted trade-off (age must not block); acceptance-consistency checking inside Step 6 is a separate cycle, not a reason to re-harden this check.
4. **Task-id in filename matches argument**: the task-id derived from the filename must equal `TASK_ID`. On failure, build the entry
   `{path: "$CLOSE_REPORT", detail: "filename task-id mismatch (file has <file-task-id>, argument is ${TASK_ID})", source_check: <re-derivation of the task-id from the filename>, producer_role: <artifact_role of that path>}`
   (failure label `commit#8`), dispatch `producer_role`, rerun that
   derivation, and apply the R15 test.

**Dry-run close-gate relaxation (scope)**: only check 2 is conditional on the Step 1 `DRYRUN` value. Checks 1, 3 and 4, the `CLOSE_REPORT` binding, Step 6's QA gate, and every permission, hook and admission gate apply unchanged, and `--force` is not loosened in any form. A dry-run leaves HEAD, worktree bytes and index bytes identical, but it does mutate-then-restore the index (`agents/changelog-analyst.md` saves and restores index bytes; `scripts/stage-owned-hunks.py` uses a throwaway `GIT_INDEX_FILE`) — never assume a dry-run does not touch the index. Disclosed widening: Step 5 mints a real single-use commit grant per plan entry before any dry-run runs, unconditioned on `DRYRUN`; it is bounded by four backstops that MUST stay intact (every unstage pause, the `--dry-run` preview end, and the plan-computed-OK-but-nothing-pending report each revoke it; it is single-use and bound to repo + branch + `expected_head`; changelog-analyst's DRYRUN guard forbids consuming it; `pretool-git-privilege-guard.py` blocks agent commits independently). Do not narrow the minting here — that would alter a second gate. Rationale record: `docs/reference/commit-dryrun-close-gate-ruling.md`.

### Step 4: Deprecated --force usage audit (only when FORCE=true)

AC11: `--force` bypasses nothing — this step is a
pure audit log, kept for backward-compatible invocation. If `FORCE=true`: create `~/.claude/logs/` and append a line with ISO timestamp, task-id, and mode=force to `~/.claude/logs/commit-overrides.log`. Best-effort; proceed even if log append fails.

Print: `WARNING: --force is deprecated and is now a no-op alias of the normal path — no gate is bypassed. Audit entry written to ~/.claude/logs/commit-overrides.log.`

### Step 5: Write commit grant(s) after resolving the repository plan

Before dispatching changelog-analyst, write the appropriate authorization token:
- **BULK=true**: the multi-use bulk-commit capability is now minted by the TRUSTED `userprompt-bulk-commit-capability.py` hook the moment the human submits `/commit --bulk` (an LLM cannot self-invoke a `disable-model-invocation: true` slash command, so the prompt itself is the trust root). The orchestrator MUST NOT emit a Bash command to write the sentinel — that fragile exact-string path is retired.
  - PRIMARY: assume the hook already minted `/tmp/claude-bulk-commit-sentinel-<sid>-<nonce>.json` (origin `userpromptsubmit-hook`). Proceed to the **Step 6 pre-commit QA gate** (then Step 7) — `--bulk` is NOT exempt from the QA gate, and (lane L7, AC11) neither is `--force` anymore; nothing bypasses it. An optional read-only check is a single bare `ls /tmp/claude-bulk-commit-sentinel-*.json`.
  - NO FALLBACK: the canonical writer is no longer Bash-executable (Layer 1.F deny-only, stage-2). The hook is the SOLE minter. If the capability is absent, the `userprompt-bulk-commit-capability.py` hook is not yet active in this session — print `AWAITING_INPUT: need=a session restart so settings.json reloads the hook, then a re-run of /commit --bulk; why=the bulk-commit capability was not minted in this session; addressee=human`. Do NOT attempt to write the sentinel via Bash.
- **BULK=false**: before writing any grant, build `REPOSITORY_PLAN` with
  `scripts/resolve-commit-repos.py`. Pass the resolved control checkout and the
  de-duplicated supported repository: the real `~/.claude` checkout.
  These are command-owned admissions, not values read from the dev-report. The
  helper reads the canonical dev/do report, resolves every `files_modified[]` /
  `files_created[]` path, assigns each path to its actual Git root (which must be
  the deepest supported repository rather than an unadmitted nested checkout),
  and fails closed if any owned path is outside that set. It emits an ordered JSON
  plan whose per-repository entries bind `repo_root`, `branch`, `expected_head`,
  task-owned repo-relative paths, and whether the control repo owns cycle artifacts.
  A malformed report, unattached branch, absent HEAD, unsupported owner, or identity
  mismatch is a finding: no grant is issued and nothing is staged while it holds.
  The finding is routed through the dispatch-and-recheck loop (the plan derives
  from the dev-report, so `producer_role` is `artifact_role` of that report) and
  rechecked with `resolve-commit-repos.py` until the plan validates; a cause only
  a human can remove prints the awaiting-input line.

  For a normal `/dev` report, resolve its complete artifact chain before
  repository planning. This is the same read-only authority used by `/dev`
  completion and `/close`; do not reconstruct a singular whitelist from
  filename patterns. The single executable invocation appears below only after
  `TASK_DOCS_ROOT`, `TASK_PROJECT_ROOT`, and `TASK_REPORT` are bound.

  The fixed entrypoint is
  `scripts/resolve-dev-artifact-chain.py --task-id <id> --project-dir <root>`.
  Require exit 0 and `status in {"pass", "pass_with_exceptions"}` and retain
  the complete JSON. A non-passing resolver result or `status == "fail"` holds
  grants, dry-run staging, and dispatch until the finding is routed (entry built from
  the resolver's output, producer role dispatched, resolver rerun) and the
  resolver passes. `pass_with_exceptions` (ticket 20260911-011232)
  is not a new trust decision at this gate: Step 3 above already required a
  passing `CLOSE: YES` verdict, and `/close`'s own QA debate already
  independently corroborated every `disclosed_exceptions[]` entry before
  granting it -- this check consumes a chain a prior gate already vouched
  for, it does not itself widen admission. A source=`do` report has no
  `/dev` chain, so set `ARTIFACT_CHAIN=""` and retain the existing do-report
  whitelist path.

  Resolve roots from the active environment, de-duplicate them through the helper,
  and capture stdout without `eval`. Preserve the existing subproject resolution:
  use the exact `docs/dev` directory that supplied `CLOSE_REPORT`, prefer this
  task's dev-report there, then its do-report, and fall back to the control-root
  `docs/dev` only when no close-report directory is available. Pass the selected
  canonical report explicitly; never scan reports by mtime.

  ```bash
  CONTROL_ROOT="$(git rev-parse --show-toplevel)"
  NESTED_REPO="$(git -C "$(realpath ~/.claude)" rev-parse --show-toplevel)"
  TASK_DOCS_ROOT="${CLOSE_REPORT:+$(dirname "$CLOSE_REPORT")}"
  TASK_DOCS_ROOT="${TASK_DOCS_ROOT:-$CONTROL_ROOT/docs/dev}"
  TASK_PROJECT_ROOT="$(dirname "$(dirname "$(realpath "$TASK_DOCS_ROOT")")")"
  # R4 tri-state guard (Architect (f) v2, QA round-2 objection 3): prefer a
  # corroborated dev-report-<task-id>.effective.json ONLY when
  # late-repair-controller.py's verify-disclosure independently admits it
  # for this task-id (State B). No late-repair state at all (State A) keeps
  # TASK_REPORT selection below byte-identical to pre-R4 behavior. A
  # present-but-uncorroborated state (State C) is a finding routed through the
  # dispatch-and-recheck loop: route_finding builds the entry
  # {path, detail, source_check, producer_role}, dispatches artifact_role(path),
  # and the SAME resolve-effective-report check is rerun until the state is no
  # longer "invalid". Control then falls through to the chain below (never the
  # "verified" branch unless the controller itself says verified), so
  # TASK_REPORT is never pointed at an unverified effective-report.
  LATE_REPAIR_JSON="$(source venv/bin/activate && python3 scripts/late-repair-controller.py \
      resolve-effective-report --task-id "$TASK_ID" --project-dir "$TASK_PROJECT_ROOT")"
  LATE_REPAIR_STATE="$(jq -r .state <<<"$LATE_REPAIR_JSON")"
  while [ "$LATE_REPAIR_STATE" = "invalid" ]; do
      route_finding "$TASK_DOCS_ROOT/dev-report-$TASK_ID.effective.json" \
          "a late-repair effective report exists for $TASK_ID but is not independently corroborated (State C)" \
          "late-repair-controller.py resolve-effective-report --task-id $TASK_ID --project-dir $TASK_PROJECT_ROOT"
      LATE_REPAIR_JSON="$(source venv/bin/activate && python3 scripts/late-repair-controller.py \
          resolve-effective-report --task-id "$TASK_ID" --project-dir "$TASK_PROJECT_ROOT")"
      LATE_REPAIR_STATE="$(jq -r .state <<<"$LATE_REPAIR_JSON")"
  done
  if [ "$LATE_REPAIR_STATE" = "verified" ]; then
      TASK_REPORT="$(jq -r .path <<<"$LATE_REPAIR_JSON")"
  elif [ -f "$TASK_DOCS_ROOT/dev-report-$TASK_ID.json" ]; then
      TASK_REPORT="$TASK_DOCS_ROOT/dev-report-$TASK_ID.json"
  else
      TASK_REPORT="$TASK_DOCS_ROOT/do-report-$TASK_ID.json"
  fi
  if [ "$LATE_REPAIR_STATE" = "verified" ] || [ -f "$TASK_DOCS_ROOT/dev-report-$TASK_ID.json" ]; then
      # A failed chain check is a finding on the dev-report chain: route it and
      # rerun the SAME resolver until it passes; ARTIFACT_CHAIN is never blanked.
      until ARTIFACT_CHAIN="$(python3 scripts/resolve-dev-artifact-chain.py \
          --task-id "$TASK_ID" --project-dir "$TASK_PROJECT_ROOT")"; do
          route_finding "$TASK_REPORT" \
              "resolve-dev-artifact-chain.py (chain-recheck) failed during commit-time repository planning" \
              "resolve-dev-artifact-chain.py --task-id $TASK_ID --project-dir $TASK_PROJECT_ROOT"
      done
      # Row 1 applies only to a fan-out chain's canonical aggregate.
      FANOUT_MODE=false; CANONICAL_DEV_REPORT=""
      if [ "$(jq -r .mode <<<"$ARTIFACT_CHAIN")" = "fanout" ]; then
          FANOUT_MODE=true; CANONICAL_DEV_REPORT="$(jq -r .canonical_dev_report <<<"$ARTIFACT_CHAIN")"
      fi
  else
      ARTIFACT_CHAIN=""
  fi
  # A failed plan computation is never an empty plan and never "nothing to
  # commit": the plan derives from the dev-report, so route the finding
  # (artifact_role of the report; a dev-report maps to dev, or to the
  # orchestrator for a fan-out canonical aggregate) and rerun the SAME
  # computation until it succeeds (exit status 0).
  until REPOSITORY_PLAN="$(python3 ~/.claude/scripts/resolve-commit-repos.py \
      --task-id "$TASK_ID" --control-root "$CONTROL_ROOT" \
      --report "$TASK_REPORT" \
      --supported-repo "$NESTED_REPO")"; do
      route_finding "$TASK_REPORT" \
          "resolve-commit-repos.py could not construct a repository plan" \
          "resolve-commit-repos.py --task-id $TASK_ID --control-root $CONTROL_ROOT --report $TASK_REPORT --supported-repo $NESTED_REPO"
  done
  ```

  **Attribution-log slice (ground-truth attribution, additive to the plan above).**
  Immediately after `REPOSITORY_PLAN` resolves, build `ATTRIBUTION_LOG` — a slice of
  the write-time attribution journal (`hooks/lib/attribution_journal.py`) scoped to
  exactly this plan's owned paths. This is the fact-based attribution source
  `agents/changelog-analyst.md`'s staging decision reads instead of (or as a
  cross-check alongside) the dev-report's self-reported ledger fields. No retry
  loop here — unlike `REPOSITORY_PLAN`, an exit code of 2 (no journaled events for
  any requested path — e.g. the path pre-dates the journal's rollout) is an
  ordinary, expected outcome, not a finding to route:

  ```bash
  ATTRIBUTION_FILES=()
  while IFS= read -r abs_path; do
      [ -n "$abs_path" ] && ATTRIBUTION_FILES+=(--file "$abs_path")
  done < <(jq -r '.repositories[] | .repo_root as $root | (.owned_paths[]? // empty) | $root + "/" + .' <<<"$REPOSITORY_PLAN")
  ATTRIBUTION_LOG="$(python3 ~/.claude/scripts/verify-attribution-chain.py --json "${ATTRIBUTION_FILES[@]}" 2>/dev/null)"
  ATTRIBUTION_LOG="${ATTRIBUTION_LOG:-{\"results\":[],\"no_events\":[],\"discarded_lines\":[]}}"
  ```

  `ATTRIBUTION_LOG.results[]` carries, per owned path, its folded write-event
  chain verdict (`CONTINUOUS_TAIL_MATCH` / `CONTINUOUS_TAIL_MISMATCH` / `BREAK`)
  and the `session_id`/`agent_id`/`task_id` of every witnessing event —
  `agents/changelog-analyst.md` groups commits from this. `no_events[]` lists
  owned paths the journal has zero coverage for (pre-journal backlog or a write
  that bypassed the hooks surface): for those, changelog-analyst's backup
  investigative path applies, never a block.

  `route_finding <path> <detail> <source_check>` is the loop above made
  concrete: build the entry with `producer_role="$(artifact_role "$path")"`,
  dispatch that role (the orchestrator itself when the role is
  `orchestrator`), then return so the caller reruns exactly its
  `source_check`; it applies the R15 progress test between rounds and escalates
  to orchestrator arbitration on no progress. It has no failure return: it
  either returns after a dispatch or prints the awaiting-input line and holds.

  Do not use `CLAUDE_PROJECT_DIR`, a
  user-supplied root override, or a report field to populate this list.

  Write **one single-use commit grant per `REPOSITORY_PLAN.repositories[]` entry**,
  always passing that entry's `repo_root` to `write-commit-grant.py`. Verify that
  the writer's captured repo/branch/HEAD equals the plan entry; any mismatch revokes
  all grants for this task/session and is a finding on the plan/grant artifact:
  rebuild the plan (resolve-commit-repos.py, above), re-mint, and re-verify, routed
  through the dispatch-and-recheck loop; a mismatch cause only a human can fix
  prints the awaiting-input line. The script resolves the session ID
  from `CLAUDE_CODE_SESSION_ID` (primary) or `CLAUDE_SESSION_ID` (fallback). If
  neither is set, print
  `AWAITING_INPUT: need=CLAUDE_CODE_SESSION_ID (or CLAUDE_SESSION_ID) set, i.e. invoke /commit from within a Claude Code session; why=cannot write the commit grant without a session id; addressee=human`
  and hold at this step in place. Do NOT dispatch changelog-analyst meanwhile. Each grant is
  still a single-repository capability; a report cannot mint admission for a new
  repository.

**Repo/branch/HEAD binding (2026-07-15 parity fix)**: `repo_root`, `branch`, and
`expected_head` are captured by both the repository planner and the grant-writer,
then re-checked by the privilege guard against live Git state when each commit runs.
A grant issued for one repo/branch/commit is rejected if any of the three changes.
Never omit `--repo-root`: every grant corresponds to exactly one plan entry.

**Grant timestamp format (NON-NEGOTIABLE)**: The `expires_at` and `created_at` fields MUST be ISO-8601 strings produced from timezone-aware UTC datetimes (e.g. `(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()` yields `"2026-05-19T16:18:56.123456+00:00"`). Epoch integers and epoch floats (e.g. `int(time.time()) + 600`, `time.time() + 600`) are NOT accepted by the privilege guard. The guard at `~/.claude/hooks/pretool-git-privilege-guard.py:377-384` parses these fields via `datetime.fromisoformat(end_str.replace('Z', '+00:00'))`; on `ValueError`/`TypeError`/`AttributeError` the helper `_end_time_passed` returns `True` (i.e. "already expired"), which silently rejects the grant and blocks the commit. The expiration window is 30 minutes from `created_at` — bake the offset into `expires_at` at write time. Activate the venv and invoke the grant-writer script (resolves `CLAUDE_SESSION_ID` from the environment, generates a fresh nonce, writes timezone-aware ISO-8601 `created_at` and `expires_at` on a 30-minute window, and emits the resulting grant path on stdout):

For each entry, invoke the existing writer with the concrete admitted root:

```bash
source venv/bin/activate && python3 ~/.claude/scripts/write-commit-grant.py \
    --task-id "$TASK_ID" --repo-root "$PLANNED_REPO_ROOT"
```

Do not flatten the plan into one grant and do not infer repositories from current
dirty status. Unused per-repository grants expire normally or are revoked at every
unstage pause and at the `--dry-run` preview end.

Both `created_at` and `expires_at` MUST match the regex `^20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(\+\d{2}:\d{2}|Z)$`. Do NOT substitute `time.time()`, `int(time.time())`, or `datetime.utcnow()` (the last returns a naive datetime whose `.isoformat()` omits the TZ offset and falls into the naive-comparison branch at line 382).

Also write the dispatch-snapshot manifest (non-bulk mode only): capture
`git status --porcelain=v1` independently for every admitted plan entry, then write
`manifest_path = /tmp/claude-commit-manifest-{sid}.json` containing `session_id`,
`task_id`, `dispatched_at`, the complete `REPOSITORY_PLAN` (including its report
digest), the exact `ARTIFACT_CHAIN` JSON (when non-empty), and
`files_at_dispatch` keyed by canonical repository root. Best-effort status
capture is permitted, but losing or changing `REPOSITORY_PLAN` or
`ARTIFACT_CHAIN` is not: a lost or changed plan or chain is a finding on that
artifact, routed through the dispatch-and-recheck loop (the plan derives from the
dev-report; the chain is rebuilt by the orchestrator rerunning
`resolve-dev-artifact-chain.py`), then rebuilt before the manifest is written. Bulk mode retains its existing
control+nested behavior.

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
- If the dry-run reports `nothing_to_commit` / empty plan: first compare it to the plan. If the plan computed OK, its owned paths exist, and those paths are not already landed, the disagreement between the owned-edit declaration and the live bytes is a finding routed to dev (not a silent no-op) and the planning phase is rerun after the fix. Only when the plan computed OK and the paths are already landed (or the plan lists no owned path), print `Nothing to commit (plan computed OK; dry-run found no pending change) — QA gate skipped.` It is never printed after a failed plan computation; then **when `BULK=false`, revoke the Step 5 commit grant** (it will never be consumed — same Grant-hygiene rationale as the Step 6 decision phase) via `source venv/bin/activate && python3 ~/.claude/scripts/write-commit-grant.py --task-id "$TASK_ID" --revoke-only` (skip in `BULK=true` — no per-task grant, empty TASK_ID); then proceed to Step 7 (which also no-ops). Do NOT dispatch QA on an empty plan.

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
  "dispatched_at": "<ISO-8601 timestamp of this dispatch>",
  "artifacts": [
    {"kind": "markdown", "path": "docs/dev/commit-qa-report-<TASK_ID or \"bulk\">.md",
     "identity_anchor": "<TASK_ID or \"bulk\">",
     "terminal_line_regex": "^COMMIT: (APPROVE|REJECT)"},
    {"kind": "response_line", "terminal_line_regex": "^COMMIT: (APPROVE|REJECT)"}
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

Write a transcript to docs/dev/commit-qa-report-<TASK_ID or "bulk">.md (verdict +
per-file findings + codex_status when run).

Return, as the LAST line, EXACTLY one of:
  COMMIT: APPROVE
  COMMIT: REJECT - <one sentence naming the offending file(s) and why>
```

**Step 6 — Decision phase.**

**Grant hygiene (`BULK=false`, at every unstage pause — REJECT routing, bad verifier report, unparseable verdict — and at the `--dry-run` preview end):** in addition to unstaging, when `BULK=false` REVOKE the Step 5 commit grant so a gate under repair never leaves live commit authorization lingering (30-min TTL; never hold a live grant across a producer repair — re-mint by re-entering Step 5 after the fix, because bytes and plan changed):
```bash
source venv/bin/activate && python3 ~/.claude/scripts/write-commit-grant.py --task-id "$TASK_ID" --revoke-only
```
**Skip this revoke entirely when `BULK=true`**: bulk wrote NO per-task commit grant (Step 5 minted the multi-use bulk-commit sentinel, which self-expires on its own 30-min TTL) and `TASK_ID` is empty, so calling the writer with an empty `--task-id` would error (exit 2). (Only the `COMMIT: APPROVE` + real-commit path keeps the grant — it is consumed by Step 7.)

- `COMMIT: REJECT`: this is a verdict on the product, not a broken artifact. Print the verdict + offending files; **unstage the dry-run-staged set so the tree is left clean** — per repo, unstage ONLY currently-staged paths, computed rename-aware. Run `git -C <repo> diff --cached --name-status -z -M` and build the unstage set from its entries: a plain (non-rename) staged path → include it if it is in `PLAN_FILES`; a staged `R`/`C` entry → include BOTH its old and new paths if EITHER endpoint is in `PLAN_FILES` (the analyst may list only the new path, yet `--name-only` / a single-endpoint unstage leaves the other endpoint — e.g. `D old` — staged). Unstage that set via `git -C <repo> restore --staged -- <those>` (unborn repo: `git -C <repo> rm --cached -- <those>`). Do NOT pass planned files that are not currently staged — in multi-group bulk Phase 4 already unstaged the earlier groups, and `restore --staged` / `rm --cached` on an unstaged/untracked pathspec errors out and leaves the last group staged. Then revoke the grant (Grant hygiene above). Do NOT proceed to Step 7; do NOT commit (`--force` does not override this gate — it is a no-op alias of the normal path). Route the REJECT through the verdict loop:
    1. **Findings to the producer.** Send the offending files and reason (from the verdict line and `commit-qa-report`) to the role that produced the flagged material, by what each finding points at: code/doc files and the dev-report → dev; ticket/context/acceptance-criteria defects → ba (`artifact_role`); anything else → orchestrator. QA never edits the subject, and "fix until APPROVE" as a formality is not a path.
    2. **Fresh independent re-verification.** After the producer's fix, rebuild the plan (Step 5), rerun the planning dry-run, and dispatch a NEW QA subagent (a fresh dispatch; the prior verdict, the findings and any ruling are NOT in its prompt) that re-judges the actual changes against HEAD. The loop ends only on that fresh verdict being `COMMIT: APPROVE` (with the file cross-check below unchanged); a further `COMMIT: REJECT` repeats this routing.
    3. **Dispute.** If the producer contends a finding is wrong, the orchestrator reruns the check itself (re-reads the diff and contents of the cited path) and arbitrates. Producer right → the `commit-qa-report` is a bad artifact: dispatch a FRESH QA subagent (same fresh-dispatch rule) to re-judge from the actual changes; the old report is never edited or re-emitted by the verifier that wrote it. Verifier right → the producer continues. No third role judges, and QA's prompt never contains the orchestrator's ruling, the producer's dispute or any prior verdict.
    4. **R15 bound (definition above).** A round whose flagged files have identical bytes and whose finding set is unchanged is no progress: it escalates to orchestrator arbitration, never a further identical dispatch and never an acceptance after a number of rounds.
- `COMMIT: APPROVE`:
  - **File cross-check (fail-closed; hardens this gate against trusting the returned string alone)**: before honoring this verdict, read `docs/dev/commit-qa-report-<TASK_ID or "bulk">.md`'s last non-empty line and compare it to the Agent tool's returned last line:
    - File does not exist → sub-case `missing_file`: the verifier's own report is a bad artifact, not a REJECT of the product. Run the SAME unstage-and-revoke cleanup as the `COMMIT: REJECT` branch above, print a message naming the `missing_file` sub-case, do NOT proceed to Step 7, do NOT commit, and dispatch a fresh QA subagent (new dispatch; the prior verdict is not in its prompt) to produce a valid report from the actual changes, rerunning this cross-check on its output (R15 bound as above).
    - File exists but its last non-empty line does not match `^COMMIT: APPROVE` → sub-case `line_mismatch`: same cleanup, print a message naming the `line_mismatch` sub-case (quoting the file's actual last line), do NOT proceed to Step 7, do NOT commit, and dispatch a fresh QA subagent exactly as for `missing_file`.
    - File exists and its last non-empty line matches `^COMMIT: APPROVE` → the two channels agree; continue below unchanged.
  - Record `QA_APPROVED_FILES` = `PLAN_FILES` (the exact reviewed set, per repo). This is passed to Step 7 as the commit **ceiling** (TOCTOU guard — Step 7 must not commit anything outside it).
  - If the user passed `--dry-run` (`DRYRUN=true`): print the plan + `QA: APPROVE`, unstage the dry-run-staged set (clean tree, as in the REJECT branch), revoke the grant, and end the invocation with the preview delivered — the requested end state; no real commit.
  - Otherwise proceed to Step 7 for the real commit.
- Unparseable / missing `COMMIT:` final line: the verifier's report is a bad artifact (fail-closed: it is not an APPROVE); unstage (as above), revoke the grant, print the raw QA output, and dispatch a fresh QA subagent (prior verdict not in its prompt) to produce a valid verdict, rerunning the cross-check on it.

### Step 7: Dispatch changelog-analyst

Use the Agent tool with `subagent_type: changelog-analyst`. Pass a structured prompt:

(substitute `<CONTROL_ROOT>` with the resolved control root and
`<REPOSITORY_PLAN>` / `<ARTIFACT_CHAIN>` with the exact Step 5 JSON values.
`NESTED_REPO` remains present only for bulk-mode backward compatibility; normal
mode's repository authority is the plan, while its `/dev` cycle-artifact
authority is the resolver result):

```
CONTROL_ROOT=<CONTROL_ROOT>
NESTED_REPO=<NESTED_REPO>
REPOSITORY_PLAN=<exact Step 5 JSON; empty only in bulk mode>
ARTIFACT_CHAIN=<exact resolver JSON; empty only for bulk or source=do>
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
  "dispatched_at": "<ISO-8601 timestamp of this dispatch>",
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
- In normal `/dev` mode, require `ARTIFACT_CHAIN.status in {"pass",
  "pass_with_exceptions"}`, `ARTIFACT_CHAIN.task_id == TASK_ID`, and its
  canonical report to equal the plan's report. The base cycle-artifact
  whitelist is exactly `ARTIFACT_CHAIN.commit_whitelist_artifacts`; this
  admits validated lane artifacts in fan-out mode and never invents optional
  parent artifacts.
- **TOCTOU guard (pre-commit QA gate)**: when `QA_APPROVED_FILES` is non-empty (the Step 6 gate ran and approved this exact set), it is the commit CEILING. Re-classify normally, then intersect the classified set with `QA_APPROVED_FILES`: stage/commit ONLY files in both. If your fresh classification yields any file NOT in `QA_APPROVED_FILES` (working tree changed since QA review), do NOT commit the unreviewed file; if the divergence is material (a QA-approved file vanished, or a new non-approved candidate appeared that you would otherwise commit), ABORT with `failure_code: scope_violation` rather than commit an unreviewed set. `QA_APPROVED_FILES` is empty only when Step 6's own planned file set was empty (nothing to commit); this guard does not apply in that case.
- Stage only files in the classified set; never use `git add -A` or `git add .`
- Commit message must NOT match: `\bsync\b.*\buncommitted\b` or `chore\(claude\)\s*:\s*sync`
- Handle every admitted repository independently and return a `repository_results` entry for each one
- Write push-gate token after each successful commit
- Push-gate token path MUST be: `/tmp/agentic-commit/push/<sha256(os.path.realpath(GIT_ROOT))[:16]>/<PUSH_GATE_SID_DIGEST>/<BRANCH with / replaced by __>.json` — session-scoped, where `PUSH_GATE_SID` is the Phase 10 three-part chain (`CLAUDE_CODE_SESSION_ID` → `CLAUDE_SESSION_ID` → `"unknown"`) and `PUSH_GATE_SID_DIGEST` is `sha256(PUSH_GATE_SID)[:16]`; only the path segment is digested (it comes from the environment and must not carry `/` or `..`), while the token's `session_id` field keeps the raw `PUSH_GATE_SID`; per-session paths stop two sessions on one branch from contending for a single token slot
- Push-gate validates commit_sha only; expires_at is no longer written or checked
- **BULK mode commit message prefix (REQUIRED when BULK=true)**: every commit message MUST begin with `auto-bulk: end-of-cycle commit for <current-branch>` where `<current-branch>` is the actual current git branch of the repo being committed (run `git rev-parse --abbrev-ref HEAD`). This prefix matches `BLESSED_BRIDGE_RE`; the privilege guard requires a valid bulk-commit sentinel (written in Step 5) to allow the commit. Do NOT use this prefix when BULK=false.
```

Wait for changelog-analyst to complete. Echo its final status to the user.

#### Changelog-analyst result handling and retry protocol

Parse changelog-analyst's structured status output (see `agents/changelog-analyst.md`
§Structured Final Status Output). The machine-readable JSON block contains
`commit_status`, `repository_results[]`, and, when applicable, `failure_code`,
`failure_reason`, and `auto_bulk_commits[]`. In normal mode a result whose
repository roots/order do not exactly equal `REPOSITORY_PLAN` is not accepted as a
landing: it is a finding on the changelog status artifact (`changelog-status*` →
changelog-analyst), routed through the dispatch-and-recheck loop and re-read.

**Handle each commit_status value:**

#### status = `committed`
Require every planned repository to have a terminal `repository_results` entry
(`committed` with commit SHA and push-gate written, or `nothing_to_commit`) and no
failed/remaining entry. Continue to Step 8 normally.

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
rejected operation, paused and reported per the Subagent Hook Discipline, never bypassed;
print `AWAITING_INPUT: need=a human git push, or a re-run of the originating session; why=HEAD has no push-gate token and could not be attributed to this session; addressee=human`
(see `agents/changelog-analyst.md` §Push-gate reconciliation, "The accepted residual").
The landed commit itself stands; only the push gate waits.

Continue to Step 8 (skip spec-update if no real commit occurred — Step 8 skip conditions apply).

#### status = `push_gate_reconciled`

No new commit was created. A prior commit ATTRIBUTED to this task was already at HEAD without
a push-gate token, and changelog-analyst has now written the missing token for that existing
commit. Say "attributed to", not "this task's own": attribution is by journal entry, and
`hooks/lib/commit_journal.py::_parent_linkage_verified` records a narrow race in which the
attributed commit was made by a peer that committed from the same recorded parent.

Seven routes reach that state, and nothing here can tell which one applied: the Phase 10
step-6 Write itself failed or was refused; the invocation was interrupted between the commit
and the token Write; the commit was already pushed — `/push` deletes the token on success,
and with no upstream configured the already-published check (condition 7) cannot establish
publication and permits reconciliation anyway; a peer replaced HEAD with a SAME-PARENT commit
inside the post-lock window — the journal accepted the peer's HEAD (linkage validates: same
first parent) while the original invocation's pre-write HEAD-stability check returned
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

Require the `repository_results` entry to report `push_gate_written: true`, a
`reconciled_commit_sha` equal to the current HEAD, and a `reconciliation_basis` whose
`attribution` is `commit_event_journal`. Verify the sha equality yourself before treating the
gate as open — a reconciled token whose sha does not match live HEAD is not authorizing, and
`/push` would reject it anyway. A result claiming reconciliation on any other attribution
basis (a `Task-id:` trailer, a file-set overlap, a subject pattern) is REJECTED: those read
content the committing actor chose and are not attribution.

Print: `INFO: no new commit; wrote the missing push-gate token for existing commit <reconciled_commit_sha>. /push is now unblocked.`

Continue to Step 8. Note that Step 8's skip condition is worded around "no real commit
occurred": a reconciliation creates no commit, so Step 8 SKIPS the spec-update dispatch. Keep
that skip — it is correct because this invocation has no cycle result of its own to fold into
a spec, and dispatching here would append a block describing work this invocation never did.

Do NOT read the skip as evidence that the spec is already current. On the route where the
originating cycle kept running and itself observed "no push-gate token written" — the failed
or refused Phase 10 Write — its own Step 8 skipped the spec-update on that ABSENT TOKEN
(`scripts/step7-spec-update.py` gates on the token file existing, whatever the reason it is
missing), so the update was never performed. On the interruption route the cycle never reached
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

Retry with a fresh grant (each further round must pass the R15 progress test):
1. Revoke stale grants, rebuild `REPOSITORY_PLAN`, and write a fresh bound grant
   for every newly planned repository. Never refresh only the control-root grant:
   ```bash
   source venv/bin/activate && python3 ~/.claude/scripts/write-commit-grant.py \
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
   - If retry `commit_status = failed` or unknown: print `ERROR: changelog-analyst retry failed (failure_code: <code>, reason: <reason>).` and route the cause as for a non-retryable code below; do NOT proceed to Step 8 until a landing is confirmed.

**Non-retryable** (`git_error`, `staging_error`, `hook_blocked`, `scope_violation`,
`repository_plan_invalid`, or any other code; also every failure after one or more
repository commits landed):

Print: `ERROR: changelog-analyst failed with failure_code: <failure_code>. Reason: <failure_reason>.`
Do NOT proceed to Step 8 until a landing is confirmed. Route the cause through the
dispatch-and-recheck loop: build the entry with `path` = the changelog status artifact
or the implicated file named in `failure_reason`, `source_check` = this changelog-analyst
result, and `producer_role` = `artifact_role(path)`; dispatch it (the cause is rerun,
not the same dispatch repeated), then re-run Step 5 through Step 7 for the repositories
not yet landed, under the R15 progress test. `scope_violation` means the tree changed
after QA reviewed it: rebuild the plan and dispatch a fresh QA over the actual set. A
`hook_blocked` failure, or any hook rejection, pauses and reports per the Subagent Hook
Discipline with
`AWAITING_INPUT: need=authorization or a ruling for the rejected operation; why=<hook output verbatim>; addressee=human`
and the rejected operation is never retried, wrapped or bypassed.

#### status unknown / unparseable
The status artifact is bad (`changelog-status*` → changelog-analyst). Print the raw
changelog-analyst output and re-dispatch changelog-analyst to emit a valid structured
status for the same plan, re-reading it under the R15 progress test.

### Step 8: Spec-update dispatch (post-commit, deterministic fail-closed)

**This step is dispatched by `/commit` from its own orchestrator context — NOT from within changelog-analyst.** changelog-analyst has already returned before this step executes.

Skip this step entirely if ANY of the following are true:
- `BULK=true`
- `DRYRUN=true`
- `TASK_ID` is empty
- changelog-analyst did not report a successful real commit (no push-gate token written, or changelog-analyst reported an error)

**Observable Step 8 trace (AC-05 Phase B contract — task 20260524-205206 iter-2)**: when env var `COMMIT_STEP7_TRACE=1` is set, Step 8 MUST emit a deterministic single-line marker to **stderr** at every decision point. The markers are:

- `STEP7_SKIPPED: bulk=true` — at the BULK=true skip branch
- `STEP7_SKIPPED: dryrun=true` — at the DRYRUN=true skip branch
- `STEP7_SKIPPED: task_id_empty` — at the empty-TASK_ID skip branch
- `STEP7_SKIPPED: changelog_no_real_commit` — at the no-push-gate / changelog-error skip branch
- `STEP7_SPEC_UPDATE_DISPATCHED: task-id=<TASK_ID> stage=<1|2> spec_path=<SPEC_PATH>` — emitted IMMEDIATELY BEFORE the Agent dispatch in stages (1) and (2)
- `STEP7_NO_SPEC: task-id=<TASK_ID>` — at stage (3) empty-set outcome
- `STEP7_UNLINKED_SPEC: task-id=<TASK_ID> count=<N> paths=<paths>` — at stage (3) one-or-more-element outcome (routed to ba, selection rerun)

This trace is OFF by default (no env var). When ON, the markers are emitted to stderr only; they MUST NOT affect stdout, exit codes, or dispatch behavior. The trace is consumed by the AC-05 Phase B test harness (tests/generated/20260524-205206/test_AC_05_e5f7a9b1c4d6e8fb.py) which exercises the Step 8 SELECTION + TRACE algorithm via `scripts/step7-spec-update.py` — the executable reference embodiment of the SELECTION portion of this Step 8 specification (stages 1-4 + STEP7_* markers). The script does NOT perform the Agent dispatch described in the "Dispatch payload" subsection below — that step is the orchestrator's responsibility, performed as a Claude Code Agent call after the selection marker emits. The orchestrator MAY either follow the prose directly OR invoke the harness to compute the selection; in both cases the orchestrator must perform the real Agent dispatch when a stage 1 or stage 2 path is selected.

When `BULK=false` AND `DRYRUN=false` AND `TASK_ID` is set AND changelog-analyst reported success:

Set `DEV_DOCS_ROOT` using the same CONTROL_ROOT logic as Step 7: `DEV_DOCS_ROOT=${CONTROL_ROOT}/docs/dev` (where `CONTROL_ROOT` is the resolved control root from the Step 7 dispatch — `$HOME`, not an author-absolute literal). Use absolute paths throughout Step 8.

**Step 8 algorithm (verbatim contract — total-ordered, deterministic, fail-closed):**

The algorithm is total-ordered and mandatory. Implementers MUST NOT introduce wording that admits implementer discretion; every nondeterminism alias is forbidden by AC5-V3. Prior-cycle artifacts MUST NOT be matched: the glob and content predicates are anchored to the CURRENT cycle's `${TASK_ID}`; no cross-cycle drag-in. This operationalizes the user binding directive that prohibits loading any non-current-cycle content (verbatim Chinese phrasing preserved at `docs/dev/ticket-20260519-211515.md`, Standard 6 exemption scope).

(1) context.spec_path first.
    If `${DEV_DOCS_ROOT}/context-${TASK_ID}.json` field `spec_path` is non-null AND the file at that path exists as a regular file, dispatch `/dev` with that `spec_path` (when `COMMIT_STEP7_TRACE=1`, emit `STEP7_SPEC_UPDATE_DISPATCHED: task-id=${TASK_ID} stage=1 spec_path=<SPEC_PATH>` to stderr immediately before the dispatch). STOP.

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
    If exactly one such line matches AND the captured path exists on disk, dispatch `/dev` with that path, emit a WARNING `linked via close-report, not context.spec_path` (when `COMMIT_STEP7_TRACE=1`, also emit `STEP7_SPEC_UPDATE_DISPATCHED: task-id=${TASK_ID} stage=2 spec_path=<SPEC_PATH>` to stderr immediately before the dispatch). STOP.

(3) Mtime window + machine-readable marker predicate (final stage).
    Else glob `docs/dev/specs/spec-YYYYMMDD-HHMMSS.md` (basename pattern enforced) with mtime in [close-report mtime - 24h, close-report mtime + 1h]. For each candidate, run `grep -lF "<!-- spec-continuation-of: ${TASK_ID} -->" candidate.md` — this is the ONLY content predicate allowed; no other grep, no free-form content scan. Collect the set of candidates that pass both the basename pattern, mtime window, and machine-readable marker grep.

(4) Outcome (fail-closed).
    - If set is empty: print `No spec associated with task-id ${TASK_ID}` and exit 0 (silent, unchanged from prior behavior). When `COMMIT_STEP7_TRACE=1`, also emit `STEP7_NO_SPEC: task-id=${TASK_ID}` to stderr.
    - If set has exactly one element: print `spec produced this cycle but not linked in context: <path>` (the finding stays visible; no spec update is dispatched for an unlinked spec). When `COMMIT_STEP7_TRACE=1`, also emit `STEP7_UNLINKED_SPEC: task-id=${TASK_ID} count=1 paths=<path>` to stderr. Route the finding to ba (`artifact_role` of `context-${TASK_ID}.json`: the context lacks `spec_path` linkage), then rerun this selection under the R15 progress test.
    - If set has multiple elements: print `multiple specs produced this cycle without context linkage: <paths>; explicit context.spec_path required` (no spec update is dispatched). When `COMMIT_STEP7_TRACE=1`, also emit `STEP7_UNLINKED_SPEC: task-id=${TASK_ID} count=<N> paths=<paths>` to stderr. Route the finding to ba exactly as above, then rerun this selection.

**Dispatch payload (when stage 1 or 2 selects a path)**

Dispatch an inline Agent (do NOT invoke `/spec-update` as a slash-command) with the following prompt, substituting `TASK_ID`, `SPEC_PATH`, and `DEV_DOCS_ROOT`:

```
You are executing the spec-continuation logic for task-id=<TASK_ID>.

Target spec file: <SPEC_PATH> (absolute path — this file exists; update it in place).

DO NOT:
- Invoke /spec-update as a slash command
- Create a new spec file; only update the existing one at <SPEC_PATH>
- Overwrite or delete prior "### Cycle N" sections
- Modify any git state, commit grants, push tokens, or command files
- Write any artifacts outside <SPEC_PATH>
- Read or modify files outside <DEV_DOCS_ROOT>/, <SPEC_PATH>, and ~/.claude/commands/spec-update.md (allowed: read spec-update.md for instructions)

Follow the ## Continuation-spec mode instructions from ~/.claude/commands/spec-update.md exactly:

- The active task-id is <TASK_ID>.
- The target spec to update is <SPEC_PATH>. Update this spec; do not create a new one.
- Gather source artifacts from <DEV_DOCS_ROOT>/:
    context-<TASK_ID>.json, dev-report-<TASK_ID>*.json, qa-report-<TASK_ID>*.json,
    close-report-<TASK_ID>.md, completion-<TASK_ID>.md
- Determine the next cycle number: max(existing "### Cycle N" headings) + 1; if none exist, use Cycle 1.
- Append the new cycle block to the spec. Never overwrite prior cycles.
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
human-only `--bulk` escape hatch: `--bulk` skips the close gate (Step 3)
entirely; `--auto` never skips it — every discovered parent walks THROUGH
Step 3's close-gate validation, never around it.

1. **Discover** the candidate parent snapshot (frozen once, at the start of
   the batch):

   ```bash
   PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
   source ~/.claude/venv/bin/activate 2>/dev/null || true
   mapfile -t COMMIT_PENDING_PARENTS < <(python3 scripts/dev-lifecycle.py list-actionable --next-action commit --project-dir "$PROJECT_ROOT")
   ```

   `list-actionable` returns a deterministically sorted list of
   `kind == "ticket"` parent task-ids only.

2. **Walk each parent sequentially** — no two parents run concurrently, and
   parent N+1's walk does not begin until parent N's walk has been
   classified. For each `TASK_ID` in `COMMIT_PENDING_PARENTS`, in order, bind
   `FORCE=false`, `BULK=false`, `DRYRUN` as passed to the batch (default
   `false`), `QA_CODEX` as passed to the batch, and run **Step 3** through
   **Step 8** exactly as written for that `TASK_ID` — same close-gate
   validation, same repository-plan resolution, same pre-commit QA gate, same
   changelog-analyst dispatch, same Step 8 spec-update dispatch. Nothing in
   Steps 3-8 is aware `--auto` is driving it.

3. **Classify the walk's outcome** (mirrors
   `scripts/dev-lifecycle.py`'s `classify_walk_outcome()`):
   - **`hook_deny`** — a `PreToolUse`/`PostToolUse`/`Stop` hook literally
     blocked a tool call during the walk (e.g. `pretool-git-privilege-guard.py`
     denying an unauthorized commit attempt). Pause and report per the
     Subagent Hook Discipline as an awaiting-input cause (hook rejection
     pause, addressee human): print the awaiting-input line with the hook's
     output, record this parent as awaiting input, and continue with the
     remaining parents (parents are independent). The rejected operation is
     never retried or bypassed.
   - **`partial_abort`** (a class name only; it does not abort anything) — this parent's OWN walk reported
     `commit_status = partially_committed` (a partial multi-repository
     commit within that one parent). Continue the remaining repositories of
     that parent in order under fresh grants (Step 7 `partially_committed`
     handling); it is not a batch-level class and no later parent is
     skipped because of it.
   - **`ordinary_reject`** — a close-gate failure, `COMMIT: REJECT` from
     Step 6, or a changelog-analyst failure inside this parent's walk. It is
     routed within that parent's walk per the dispatch-and-recheck loop, the
     Step 6 verdict routing and the Step 7 failure routing; the walk ends a
     parent only by landing (or the `--dry-run` preview end state), never by
     recording the rejection and moving on.
   - **`success`** — `commit_status ∈ {committed, nothing_to_commit,
     push_gate_reconciled, nothing_to_commit_precommitted}`. **Record and
     continue** to the next parent.

4. **Batch summary**: the walk ends only when every parent has landed or is
   awaiting input. Print one line per parent: `task-id: <landed outcome>` or
   `task-id: awaiting_input` (a parent paused by `hook_deny` or another
   awaiting-input cause).

Human-operator verification of this mode (QA cannot literally invoke
`/commit --auto` — `disable-model-invocation: true` plus `settings.json`'s
global `Skill(commit:*)` deny) is documented in
`docs/dev/ticket-20260808-035658-lanel.md` AC-L21: a separate
human-operator-executed transcript at
`docs/dev/human-operator-transcript-<task-id>.md`, using the
`PARENT_START: <task_id>` / `PARENT_END: <task_id> outcome=<...>` schema
`scripts/dev-lifecycle.py`'s `parse_human_operator_transcript()` parses.

## Close-gate verification reference

The close-gate is the only guard this command owns. All git operations (staging, committing,
nested-repo handling, push-gate write) are delegated entirely to `changelog-analyst`.

## Privilege guard compatibility note

`pretool-git-privilege-guard.py` is REGISTERED in `settings.json` (PreToolUse, Bash matcher).

Authorization flow for changelog-analyst commits:

1. `/commit` writes `/tmp/claude-commit-grant-<SID>-<nonce>.json` before dispatching changelog-analyst (Step 5).
2. `_evaluate_commit(command, data)` collects EVERY unexpired grant candidate (the any-SID glob covers the subagent SID-propagation fallback) and SELECTS the one whose `repo_root`/`branch`/`expected_head` match the commit's target repo — recency alone never decides.
3. The selected grant passes the authoritative binding re-check (`_enforce_commit_grant_binding`: redirect vectors, then repo/branch/HEAD). A Bash call containing MORE THAN ONE `git commit` invocation is hard-BLOCKED before any of that: every invocation in one call would be validated against the same pre-execution HEAD under one lock, so a second commit would ride the first one's authorization (audit round 3, F5). One grant authorizes exactly one commit; issue each as its own call. The grant is then LOCKED for deferred consumption — renamed to `.lck`, with a pointer keyed on this tool event's `tool_use_id` and recording that raw id. The pointer is published ATOMICALLY (content written to a temp name, then `link(2)` into the final name), so a reader never sees a torn pointer (audit F7).
4. Grant validates: expires_at (30 min window); no message-hash validation. Consumption is deferred to the finalizer (`posttool-allowlist-consume.py`, registered under PostToolUse AND PostToolUseFailure), which classifies the terminal result from the payload shape — not from an exit code: success unlinks the `.lck` (single-use) and journals the commit event; any other TERMINAL result restores the grant for retry. A NONTERMINAL background-launch receipt (the command is still running) finalizes nothing at all — no unlink, no restore, no journal entry (audit F2/F3). An event with no usable `tool_use_id` leaves the grant in place un-deferred, and single-use there is NOT enforced by the `expected_head` binding: "a landed commit moves HEAD past the grant" was disproven — `git reset --soft <expected_head>` restores the matching tuple and a deterministic `--amend` reproduces the same sha, so HEAD need never move (audit round 3, F4). The guard instead writes its own validation-time use record (`<grant>.json.use`) holding an APPEND-ONLY witness of the target repo — HEAD sha plus HEAD reflog entry COUNT — and honors a later authorization only while that witness is unchanged and under `_MAX_GRANT_USE_ATTEMPTS`. The count rises on commit, reset and amend alike, so neither a soft reset nor a same-sha amend can replay a grant; an unreadable witness fails closed.

**DO NOT extend `BLESSED_BRIDGE_RE` with conventional commit patterns** (e.g. `^feat\(`, `^fix\(`).
This would allow any agent that learns the commit format to bypass the guard — destroying the
security model. The grant-file mechanism provides the correct narrow authorization.

auto-bulk bridge commits (matching BLESSED_BRIDGE_RE) require a **bulk-commit sentinel**
written by `/commit --bulk` Step 5 (`scripts/write-bulk-commit-sentinel.py`, 30 min TTL,
multi-use). Without it the guard blocks the commit even if the message prefix is correct. With
it, the commit is still DEFERRED (blocked, retry next cycle) while a `/commit` grant that could
actually authorize a commit HERE is live — the deferral applies the same repo/branch/HEAD
binding and spent test the commit validation applies, so a foreign-repo or already-spent
leftover no longer defers auto-bulk for its whole TTL (audit round 3, F6).
changelog-analyst non-bulk commits use the single-use grant-file path.
The BLESSED_BRIDGE_RE check runs first in `_evaluate_commit`, followed by the sentinel check.

## Related

- `/close <task-id>` — must run before `/commit` (produces the close-report gate token)
- `/push` — must run after `/commit` (reads the push-gate token written by changelog-analyst)
- `agents/changelog-analyst.md` — the subagent that does all git work
