---
description: Close the current dev cycle (agent infers task-id from conversation). QA evaluates Workflow Integrity bullets and returns CLOSE YES/with-disclosures. Pass --codex to enable multi-round QA-codex debate; default is QA-only single-round assessment. --force is DEPRECATED -- a no-op alias of the normal path (audit-logged, skips nothing). Pass --auto to discover and sequentially close every close_pending parent (see `--auto mode` below).
argument-hint: "[--codex | --force (deprecated, no-op) [--reason \"<text>\"] | --auto] [<task-id>|<path>]"
disable-model-invocation: true
---

# /close

True wrapper. Three TodoSteps (user-visible work):
1. Dispatch three inspectors (parallel for single-dev cycles; sequential for parallel-dev cycles).
2. Delegate close debate to QA subagent.
3. Generate close-report + next step (echo QA verdict + write report + name the next step).

Argument parsing (`--codex` / `--force`) and task-id resolution still happen
in this command body, but are no longer TodoSteps — they are command-internal
plumbing, not user-visible work.

The orchestration of rounds, the calls to codex, the evaluation of agreement, and the writing of the transcript all live INSIDE QAs invocation. /close itself does not call codex, does not manage rounds, and does not decide the verdict.

## Invocation

```
/close                                                         # agent infers task-id from current /dev cycle (typical use)
/close --force                                                 # DEPRECATED no-op alias of a bare /close (audit-logged only — see Forced-override path below)
/close <task-id>                                               # /do work: reads do-report-<task-id>.json, runs normal QA path
```

Power users may also pass an explicit task-id or path: `/close <task-id>` or `/close docs/dev/ticket-<ts>.md` (legacy: `/close docs/dev/ba-spec-<ts>.md`). The orchestrator parses these forms but the typical invocation is bare `/close` and lets the agent resolve the task-id from conversation context. No filesystem scan, no default-to-newest.

`/do`-developed work writes a lightweight do-report (`docs/dev/do-report-<task-id>.json`, see `commands/do.md`); `/close <task-id>` reads it and runs the normal QA path — no `--force` needed. `--force` remains a fallback for work with no do-report (hand-edits). Follow with `/commit <task-id>`.

<!-- Cross-reference: BA spec <harness-home>/docs/dev/ba-spec-20260426-redev8.md § AC-CLOSE-FORCE-1..6 govern --force / --reason behavior. -->


## Workflow

**`--force` has no separate todo-list or sentinel-file path (AC11).** No sentinel is written; QA always runs, so the SubagentStop enforcement hooks (`hooks/subagentstop-e2e-enforce.py`, `hooks/subagentstop-artifact-contract-enforce.py`) always apply, exactly like a bare invocation.

Load preloaded todo list: activate venv and run `~/.claude/scripts/todo/close.py` (now unconditional — `--force` no longer bypasses this).

### Argument parsing: `--codex` flag (applies to non-force paths)

Parse `--codex` from `$ARGUMENTS` BEFORE evaluating the forced-override path or task-id resolution:

- If `$ARGUMENTS` contains the literal token `--codex` (in any position), strip it and set `codex_required = true`.
- Otherwise set `codex_required = false` (default).

`codex_required` controls whether QA's internal multi-round debate (Step 2) consults codex via `Skill(codex)`:

- **`codex_required = true`**: dispatch prompt for QA includes the full multi-round QA-codex debate protocol as documented in Step 2 below. Verdict branches 1 / 2 / 3 / 6 / 7 apply.
- **`codex_required = false`** (default): dispatch prompt for QA SKIPS all `Skill(codex)` invocations and runs QA-only single-round assessment of the 4 Workflow Integrity bullets + step 1b cleanliness preconditions. Verdict branch 9 (codex disabled) applies; branches 3 / 6 / 7 are N/A.

`--force` is deprecated (see "Forced-override path" below) and no longer short-circuits anything, so it has no effect on `--codex`: when both are present, `codex_required` is still determined solely by `--codex`. The two flags are not mutually exclusive parse-wise (orchestrator strips both independently).

### Argument parsing: `--auto` flag (Must-Have #8, task 20260808-035658-lanel)

Parse `--auto` from `$ARGUMENTS` BEFORE evaluating the forced-override path or task-id resolution:

- If `$ARGUMENTS` contains the literal token `--auto`, strip it and set `auto = true`.
- Otherwise set `auto = false` (default — every rule below is inert).

**Invalid combination (before any action)**: when `auto = true`, `/close` MUST NOT proceed to Task-id resolution, Step 0, or any Agent dispatch — it waits (awaiting-input cause (iii): `close_awaiting_input` naming the offending token) and resumes in place once the human corrects the arguments — if `$ARGUMENTS` (after stripping `--auto` itself) still contains ANY of: an explicit task-id or path token, `--force`, or a `--reason` value. `--auto` and `--codex` MAY combine (each `--auto` walk below still honors `codex_required` exactly as the non-`--auto` path does). This mirrors `scripts/dev-lifecycle.py`'s `validate_auto_flag_combination()` pure predicate (`--force`/explicit-task-id/`--bulk` all reject; `--bulk` does not exist for `/close` so only the first two apply here) — the mechanical check:

```bash
python3 -c "
import os, sys; sys.path.insert(0, os.path.expanduser('~/.claude/scripts'))
import importlib.util
spec = importlib.util.spec_from_file_location('dlc', os.path.expanduser('~/.claude/scripts/dev-lifecycle.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
err = m.validate_auto_flag_combination(True, '<explicit-task-id-or-empty>', <force_bool>, False)
print(err or 'OK')
"
```

When `auto = true` and the combination is legal, skip Task-id resolution and Steps 0-3 entirely at THIS level — control passes to the `--auto mode` section below, which drives Steps 0-3 once per discovered parent.

### Forced-override path: `--force` flag (DEPRECATED — no-op alias of the normal path)

**`--force` skips nothing (AC11).** It is pure argument-stripping plus a
best-effort audit-log append; execution falls straight into the same Step 0-3 every other
invocation uses — no QA/inspector/close-gate skip occurs. **The model itself
still cannot trigger this flag** — `disable-model-invocation: true`
(frontmatter line 3) prevents `SlashCommand`-based self-invocation regardless
of arguments; only a human invoking via the slash UI can pass `--force`.

Procedure when `--force` is present (no separate todo list — this flows into
the normal Task-id resolution / Step 0 / Step 1 / Step 2 / Step 3 sequence
below, same as a bare invocation):

1. **Strip `--force` from `$ARGUMENTS`**. If `--reason "<text>"` follows, capture `<text>` (everything between the matched quotes) as `$REASON`. If absent, set `$REASON="no reason provided"`. Set `FORCE=true` (otherwise `FORCE=false`, the default).
2. **Append a best-effort audit log entry** to `~/.claude/logs/close-overrides.log`: a line with ISO timestamp, task-id (once resolved), mode=force (deprecated-no-op), and the reason string. Create `~/.claude/logs/` if needed. If the append fails, proceed anyway — the audit log is best-effort and never blocks closure.
3. **Continue to Task-id resolution below exactly as a bare `/close` would** — the SAME artifact preflight, the SAME Step 1 inspector dispatch, the SAME Step 2 QA debate (with `codex_required` still controlled solely by `--codex`, per the note above), and the SAME Step 3 close-report write. `FORCE=true` carries no further effect beyond the audit-log line in step 2 above.

`--force` is kept only so existing `/close --force` invocations do not error. The debate and all gates always run; every finding raised by a gate is handled by the routing helpers and routing loop (below): it is routed to the dispatch that owes its artifact, fixed, and re-judged.

### Task-id resolution

Resolve the **task-id** for the report filename. The task-id is the SAME identifier used by the source `/dev` cycle (for example, a timestamp-style task id) — NOT a fresh `date +%Y%m%d-%H%M%S` at /close invocation time. Using a fresh timestamp would break /commit's PRIMARY-path lookup, which requires `close-report-<task-id>.md` and `dev-report-<task-id>.json` under the SAME `<task-id>`.

Resolve the spec to evaluate (in priority order):
- If `$ARGUMENTS` is an explicit path (ends in `.md`/`.json` or contains `/`): use that path. Verify it exists; if not, that is awaiting-input cause (iii) naming the missing path. Derive the task-id by stripping the `ticket-` prefix (or legacy `ba-spec-` prefix) and `.md`/`.json` suffix from the basename (e.g. `docs/dev/ticket-X.md` → task-id `X`; `docs/dev/ba-spec-X.md` → task-id `X`). If the basename starts with `do-report-`, also strip that prefix and set `DO_REPORT=$ARGUMENTS` (e.g. `docs/dev/do-report-X.json` → task-id `X`, `DO_REPORT` set, proceeds to do-report lite preflight).
- Elif `$ARGUMENTS` matches a timestamp pattern (e.g. `20260424-103044`):
  - **Non-force path**: bind `TASK_ID=$ARGUMENTS` without first requiring a
    parent ticket or parent QA-report. Immediately run Step 0's chain call.
    This ordering is mandatory: those parent artifacts are optional for a
    valid fan-out cycle, so a singular-shaped existence check before the chain
    call would reject N > 1.
  - **do-report path**: when no canonical
    `docs/dev/dev-report-${ARGUMENTS}.json` exists but
    `docs/dev/do-report-${ARGUMENTS}.json` exists with top-level
    `source == "do"`, set `DO_REPORT` to it and use the lite preflight. A
    canonical dev-report takes precedence and is resolved as a dev chain; do not
    use a do-report to bypass a failing dev chain.
  - **Forced-override path**: use `$ARGUMENTS` directly as the task-id with NO file existence verification — neither ticket/ba-spec nor qa-report checks apply. The task-id is the argument itself; the close-report becomes the sole audit artifact for this task. This allows `/close <ts> --force` to work even when no ticket, spec, qa-report, or do-report file exists (e.g., hand-edits with no do-report — `/do` work that wrote a do-report uses the do-report path above instead).
  The task-id IS `$ARGUMENTS` directly (timestamp form is a valid task-id; this preserves backwards compatibility for `/close <ts>` invocations and works for both ticket- and ba-spec- artifact name conventions).
- Else (no argument): the orchestrator invoking /close MUST already know this
  conversation's parent task-id from the active `/dev` or `/do` cycle. For
  `/dev`, bind that parent task-id and immediately run Step 0's chain call;
  do not select a parent ticket/QA-report from context
  first. The resolver's `mode` identifies singular versus fan-out and its lane
  matrix supplies the paths. For `/do`, infer `TASK_ID` and `DO_REPORT` from the do-report path in
  context. There is NO filesystem scan and NO default-to-newest. If the
  orchestrator cannot identify the active parent task-id or do-report, that is
  awaiting-input cause (iii): `close_awaiting_input "an explicit path/timestamp, or run /close within a conversation that just completed /dev" "No spec identified" human`.

If no task-id can be derived (no argument, no /dev context, no parseable filename), /close waits (awaiting-input cause (iii), with the same `No spec identified` reason) and resumes in place when the human supplies one. /close MUST NOT default to `date +%Y%m%d-%H%M%S` for the close-report filename — that would silently break the task-id chain.

Bind the resolved value as `TASK_ID` (e.g. `"$ARGUMENTS"` when timestamp form, or derived from path basename).

### Late-repair route (R4 — spec-20260907-115508-lawful-commit-channel.md)

Parse `--late-repair` from `$ARGUMENTS` BEFORE Step 0's resolver-failure handling (Step 0's `close_route_finding` calls below). This is a deliberately-invoked, never-automatic route: without this flag, none of this section's code runs and `/close` behaves exactly as before.

- If `$ARGUMENTS` contains the literal token `--late-repair`, strip it and set `LATE_REPAIR=true`. Otherwise `LATE_REPAIR=false` (default — every rule below is inert).
- **`--late-repair` combined with `--force` is a usage error**, held before any eligibility check, run-record creation, or dispatch: `--force` is never widened by R4. It is awaiting-input cause (iii): `close_awaiting_input "drop --force or --late-repair" "--late-repair combined with --force is not permitted" human`; nothing lands, and the attempt resumes in place with the corrected arguments.
- When `LATE_REPAIR=true`, Step 0's `python3 ~/.claude/scripts/close-route-select.py` invocation (below) additionally passes `--late-repair`. `close-route-select.py` calls `scripts/late-repair-controller.py init` exactly once, which independently re-derives `late_repair_eligible` from the resolver's own output (the single source of truth — this section never recomputes it) and:
  - **Declines immediately** (zero run records, zero dispatch) when the chain is not late-repair eligible (`gap_classification` in `{qa_only, complete}`, or `beyond_qa` with `late_repair_eligible == false` because a `non_gap_errors` entry co-occurs with a real `stage_gaps` entry). The selector then prints the ordinary route's payload (`outcome: not_selected`, `artifact_chain` the chain result init decided on, and the ordinary exit status) with init's refusal under `late_repair`, reason `not a beyond-QA gap; use R1's route`. This is NOT a verdict: record the reason in the transcript and continue on the ordinary route with that same call's `ARTIFACT_CHAIN` and `ROUTE_SELECT_RC`, used verbatim (Step 0 sets `LATE_REPAIR=false`); the selector is not invoked again.
  - **Creates a controller-owned run record** (`docs/dev/late-repair-run-<task-id>.json`) the moment it observes a genuinely eligible chain — binding `repair_run_id`, the live eligibility snapshot, pre-route file hashes, `original_cycle_at`, and `repair_started_at` — before any BA/Dev/QA dispatch.
- Precompute the extra selector array Step 0 appends verbatim: `LATE_REPAIR_SELECTOR_ARGS=(); [ "$LATE_REPAIR" = "true" ] && LATE_REPAIR_SELECTOR_ARGS+=(--late-repair)`. Step 0's own invocation of `close-route-select.py` (below) appends `"${LATE_REPAIR_SELECTOR_ARGS[@]}"` — this keeps the literal flag spelling confined to this section rather than duplicated into Step 0's own text.
- On a genuinely eligible chain, dispatch BA, then Dev, then QA against the CURRENT state of the work (a measured no-change Dev result is acceptable; being skipped is not). After each stage genuinely completes, run `python3 ~/.claude/scripts/late-repair-controller.py record-stage --task-id "$TASK_ID" --project-dir "$PROJECT_ROOT" --stage <ba|dev|qa> --report-path <path> --repair-run-id <id>` — this independently recomputes the artifact's hash from its on-disk bytes and records it in the run record; it writes nothing into the artifact. Stage order (ba → dev → qa) is enforced; an out-of-order or duplicate call is refused.
- After all three stages are recorded, the canonical todo list's Step 0 (`scripts/todo/close.py` under `--late-repair`, the main agent's own step) runs `python3 ~/.claude/scripts/late-repair-controller.py finalize --task-id "$TASK_ID" --project-dir "$PROJECT_ROOT" --repair-run-id <id>`. This runs an explicit drift-detection phase (comparing each declared file's recorded provenance against current live bytes) and, if drift is found, routes each drifted file through the correct provenance mechanism, writing a non-destructive `docs/dev/dev-report-<task-id>.effective.json` refresh afresh on every run (never overwriting the original dev-report) when reconcilable, or an honest refusal when not; it checks the file it wrote (it exists, parses and carries the block it embedded) before it records its outcome and the path, and otherwise refuses, naming that path. `finalize`'s `finalized_pending_verification` outcome is PROVISIONAL — it does NOT by itself make the chain commit-eligible.
- Only a separate, subsequent `python3 ~/.claude/scripts/late-repair-controller.py verify-disclosure --task-id "$TASK_ID" --project-dir "$PROJECT_ROOT"` returning `outcome: admitted` makes the chain eligible to proceed toward `/commit`. It compares each recorded stage report with the path and hash the run record holds: no matching run record, a missing stage report or a hash mismatch is refused (not admitted), and each refusal names the artifact's `path`. `/commit` (see `commands/commit.md`) runs this same verify-disclosure through `resolve-effective-report` and takes the effective report only from the outcome and path finalize recorded. R4 does not grandfather work completed before R4 existed: a chain's only lawful path via this route requires a run record created while the resolver actually reported the eligible shape, never a label added afterward.
- When `verify-disclosure` returns `admitted`, proceed to Step 1 exactly as the normal path does. When it or `finalize` refuses (or `finalize` reports unreconcilable drift), that is a finding on the artifact the refusal's `path` names: `close_route_finding` with that path, routed to that path's producer (a step of the main agent's own, as finalize's Step 0, runs again under the run record's `repair_run_id`), and `verify-disclosure` (the verifier, unchanged) re-judges. A late-repair attempt stays on the late-repair route until admitted and never reports a negative verdict; it does not get a second, silent try via the ordinary route.

### Routing helpers (R1 / R4 / R12 / R13 / R15 — the only non-landing state is a defined wait)

**State machine.** A close attempt is always in exactly one of three states:
**routing** (a finding is being fixed by the dispatch that owes its artifact),
**awaiting-input** (the defined wait below), or **landed** (a `CLOSE: YES*`
verdict is the last line of the close-report). Nothing in this file ends an
attempt any other way. Every finding follows ONE loop: finding -> the dispatch
that owes its artifact -> that dispatch runs again and fixes -> the verifier
re-judges independently. The verifier never edits the artifact it judges. A
negative judgment is a finding, never an exit.

Define these functions once (bash; `jq` and `python3` already assumed available
by the rest of this file).

```bash
# Required-action entry: {path, detail, source_check}. path is the artifact the
# finding concerns; source_check names the ONE check that produced the finding.
# One key per object literal: pretool-bash-safety.sh refuses a function whose
# body holds a comma inside braces.
close_required_action() {
  local path="${1:-}" detail="${2:-}" source_check="${3:-}"
  jq -nc --arg path "$path" --arg detail "$detail" --arg sc "$source_check" \
    '{path:$path} + {detail:$detail} + {source_check:$sc}'
}

# Record a finding: append its entry to REQUIRED_ACTIONS_JSON for the routing loop.
close_route_finding() {
  local entry
  entry="$(close_required_action "$@")"
  REQUIRED_ACTIONS_JSON="$(jq -c --argjson e "$entry" '(. // []) + [$e]' <<<"${REQUIRED_ACTIONS_JSON:-[]}")"
}

# R15 progress measure. Arguments: before-hash after-hash before-unresolved
# after-unresolved (the sets are newline-separated finding ids). Call it directly,
# not inside $( ): it keeps its history in CLOSE_PROGRESS_SEEN and sets
# CLOSE_PROGRESS_RESULT (also printed) to progress or no_progress. A round is
# progress iff the producer artifact bytes changed, or the unresolved set became
# strictly smaller; a (bytes, set) state seen in any earlier round never counts
# as progress again (the revisit rule).
close_progress() {
  local bh="${1:-}" ah="${2:-}" bset="${3:-}" aset="${4:-}" bkey akey nb na
  bset="$(printf '%s\n' "$bset" | sed '/^$/d' | sort -u)"
  aset="$(printf '%s\n' "$aset" | sed '/^$/d' | sort -u)"
  bkey="$bh|$(paste -sd, - <<<"$bset")"
  akey="$ah|$(paste -sd, - <<<"$aset")"
  case $'\n'"${CLOSE_PROGRESS_SEEN:-}"$'\n' in *$'\n'"$bkey"$'\n'*) ;; *) CLOSE_PROGRESS_SEEN="${CLOSE_PROGRESS_SEEN:+$CLOSE_PROGRESS_SEEN$'\n'}$bkey" ;; esac
  CLOSE_PROGRESS_RESULT=no_progress
  case $'\n'"${CLOSE_PROGRESS_SEEN:-}"$'\n' in
    *$'\n'"$akey"$'\n'*) ;;
    *)
      CLOSE_PROGRESS_SEEN="$CLOSE_PROGRESS_SEEN"$'\n'"$akey"
      nb=$(printf '%s\n' "$bset" | sed '/^$/d' | wc -l)
      na=$(printf '%s\n' "$aset" | sed '/^$/d' | wc -l)
      if [ "$bh" != "$ah" ]; then
        CLOSE_PROGRESS_RESULT=progress
      elif [ "$na" -lt "$nb" ] && [ -z "$(comm -13 <(printf '%s\n' "$bset") <(printf '%s\n' "$aset"))" ]; then
        CLOSE_PROGRESS_RESULT=progress
      fi
      ;;
  esac
  echo "$CLOSE_PROGRESS_RESULT"
}

# The one defined wait. Prints exactly one structured line and nothing else: no
# CLOSE: line of any kind and no close-report section.
close_awaiting_input() {
  local need why who
  need="$(printf '%s' "${1:-}" | tr '\n' ' ')"
  why="$(printf '%s' "${2:-}" | tr '\n' ' ')"
  who="${3:-human}"
  case "$who" in human|orchestrator) ;; *) who=human ;; esac
  printf 'AWAITING_INPUT: need=%s; why=%s; addressee=%s\n' "$need" "$why" "$who"
}

```

**`source_check` values** (the one check that produced the finding): the route-select / resolver run, the artifact schema gate, an inspector report validation, or a QA bullet. The command builds each entry itself with `close_required_action`.

**Awaiting-input (R1-b / R6) — closed cause set.** The ONLY causes that wait are: (i) a human-only authorized operation (deletion, `/allow`, freeing `/tmp`, a rule-conflict ruling, or a hook rejection, which pauses per Subagent Hook Discipline and is never retried or worked around); (ii) an environment fault (R14) that needs a human action; (iii) pre-cycle argument or usage input the human must correct or supply (an invalid flag combination, `--auto` with a task-id / `--force` / `--reason`, `--late-repair` with `--force`, no resolvable task-id). Any other cause is routed (the loop below), never waited on. While waiting, NOTHING lands as complete: no `CLOSE:` line of any kind, no `CLOSE_FINDINGS:` line, and no close-report section is written; the wait is signalled by the single `AWAITING_INPUT:` line, and a consumer tells a wait from a landed verdict by the absence of any `CLOSE:` line. When the awaited input arrives, the loop resumes at the same step in place.

### Routing loop (finding -> owing dispatch -> fix -> same check re-run)

Applies identically at EVERY site that records a finding with
`close_route_finding` (Step 0, the do-report lite preflight, the cp-state
handoff, the artifact schema gate, Step 1's missing-report check, and every Step 2
verdict branch below), whenever `REQUIRED_ACTIONS_JSON` is a non-empty array.
There is no repair engine and no repetition bound: the loop is bounded only by
the R15 progress measure.

For each `{path, detail, source_check}` entry:

1. **Owing dispatch** = the JSON answer (or `null`) of the declaring-dispatch
   reader on the entry's path, run as its own Bash call:

   ```bash
   python3 ~/.claude/hooks/lib/obligation.py declaring-dispatch --task-id "$TASK_ID" --project-dir "$PROJECT_ROOT" --path "<path>"
   ```

   It reads this task's dispatch records in every session the project's
   transcript store holds (a `/dev` of an earlier session included):
   - `source` `dispatch` (its obligation declares `path`), `lane` (an
     artifact of the whole fan-out, as its canonical aggregate, which the
     lane-completeness hook writes when a lane's dev writes its report; the
     main agent runs no aggregator) or `writer` (a product file: the dispatch
     whose own tool calls wrote it): dispatch it again, the same
     `subagent_type`, `task_id`, `lane` and obligation with a fresh
     `dispatched_at`.
   - `source` `todo_step` (no dispatch has declared `path` yet): with a
     `template`, make a fresh dispatch of its role under the same task id from
     that template of the answer's `step` in `commands/<command>.md`; with
     none, the step is the main agent's own (as finalize's Step 0 under
     `--late-repair`): run it yourself under the same task id.
   - For a `/do`-origin task (`DO_REPORT` set), the do-report and a file the
     answer names no owner for (`null`: the /do main agent wrote it) take the
     do-report lite preflight's own step: dispatch dev again under the same
     task id to complete the /do work.
   - `null` otherwise, and a close-QA finding that cites no artifact: the
     entry's path becomes that round's own report,
     `docs/dev/close-report-$TASK_ID.md`, with the finding's path and detail as
     its detail; that round's QA dispatch runs again and names an artifact.
   A wholly missing lane is rebuilt in ba -> dev -> qa order.
2. **Dispatch** — one real `Agent` tool call, `run_in_background: false`
   (CLAUDE.md Orchestrator-Only Rule), carrying the FIRST ACTION line and the
   `<obligation v="1">` block of the dispatch it repeats, scoped to the entry's
   `path` / `detail` (a step of the main agent's own runs in its place).
3. **Re-check** — re-run ONLY the entry's `source_check` (never the whole
   `/close` flow from scratch), as an independent verifier. A verifier never
   edits the artifact it judges; it reports a finding and the producer fixes it.
4. **Measure progress** with `close_progress` when the re-check still fails
   (before/after hash of the producer artifact's bytes; before/after set of
   unresolved finding ids), as `/commit`'s loop does. Re-check
   passes -> the finding is closed: it is recorded as a completed repair (see
   `## Disclosures` below), never as an open gap. A round that changed neither
   the producer artifact's bytes nor shrank the unresolved set, or that
   revisits a state already seen, is `no_progress`.
5. **No progress -> orchestrator arbitration (R5 / R13).** The orchestrator
   personally re-runs the single `source_check` and decides who is right.
   Producer right -> the verifier's report is itself a bad artifact: its
   report path is an entry like any other, and the verifier's own dispatch, which
   the reader returns for it, runs again to fix its report. Verifier right -> the producer continues, and its next round
   must change world state. There is no third role, no retry in place, no
   fall-back to a disclosure, and no fail-open.

A fault whose cause is environmental (R14: no space, read-only filesystem,
permission on a state directory) that persists across rounds is a defined wait:
`close_awaiting_input` with that cause. Everything else keeps routing.

### Step 0: Resolve the artifact chain
(non-force, normal `/dev` path)

For both explicit `/close <task-id-or-path>` and bare `/close`, fan-out
recognition MUST happen before any parent ticket/context/QA assumption. Resolve
the project root that owns the selected `docs/dev/` directory, then the chain.
`/close` runs no aggregator: a fan-out's canonical aggregate has one producer,
the lane-completeness hook (`commands/dev.md` Step 11), and a resolver finding
on it goes back to that producer like any other finding:

```bash
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
ROUTE_SELECT_ARGS=(--task-id "$TASK_ID" --project-dir "$PROJECT_ROOT" "${LATE_REPAIR_SELECTOR_ARGS[@]}")
ROUTE_SELECT_RESULT="$(python3 ~/.claude/scripts/close-route-select.py "${ROUTE_SELECT_ARGS[@]}")"; ROUTE_SELECT_RC=$?
[ "$(jq -r '.outcome' <<<"$ROUTE_SELECT_RESULT")" = "not_selected" ] && LATE_REPAIR=false   # init declined: the ordinary route goes on with the chain of this call
ARTIFACT_CHAIN="$(jq -c '.artifact_chain // {}' <<<"$ROUTE_SELECT_RESULT")"
REQUIRED_ACTIONS_JSON='[]'   # the Resolver-error routing rule below, recorded in this same call
if [ "$LATE_REPAIR" != "true" ] && [ "$ROUTE_SELECT_RC" -ne 0 ]; then
  while IFS= read -r ERR; do
    close_route_finding "$(jq -r --arg report "docs/dev/dev-report-$TASK_ID.json" '.path // .artifact // $report' <<<"$ERR")" \
      "resolver reported $(jq -r '.code // "an error"' <<<"$ERR") (rc=$ROUTE_SELECT_RC)" "close-route-select.py"
  done < <(jq -c '.errors[]?' <<<"$ARTIFACT_CHAIN")
  [ "$REQUIRED_ACTIONS_JSON" != "[]" ] || close_route_finding "docs/dev/dev-report-$TASK_ID.json" "close-route-select.py returned non-zero (rc=$ROUTE_SELECT_RC) with no parseable errors[] and LATE_REPAIR=false" "close-route-select.py"
fi
```

**Resolver-error routing rule.** Applies only when `LATE_REPAIR != true` and
`ROUTE_SELECT_RC != 0`. `ARTIFACT_CHAIN.errors[]` (`jq -c '.errors[]?'`) is the
resolver's own error list; this is the implementation this rule reads, not a
separate mechanism. Each element of that array becomes one `close_route_finding`
call: path = that element's `.path // .artifact`, or, when the element names
neither, the chain's dev report `docs/dev/dev-report-$TASK_ID.json`; detail = "resolver reported `<.code, default "an
error">` (rc=$ROUTE_SELECT_RC)"; `source_check` = `close-route-select.py` --
the same `{path, detail, source_check}` shape `close_route_finding` takes
everywhere else in this document. When `errors[]` is empty or unparseable,
there is exactly one such finding instead, on that same dev report, with detail
"close-route-select.py returned non-zero (rc=$ROUTE_SELECT_RC) with no
parseable errors[] and LATE_REPAIR=false", same `source_check`. The block's
last lines make these calls in the chain call's own Bash call: a routing round
the main agent works itself dispatches nothing, and the orchestrator gate
refuses a sixth Bash call in a row before Step 1's dispatch.

Whatever `close_route_finding` recorded in this block is then worked by the routing loop (below) before Step 1; the same `source_check` is re-run after each fix.

The fixed production entrypoint Step 0 shells out to is
`scripts/close-route-select.py` — never `scripts/resolve-dev-artifact-chain.py`
directly, and this script alone decides (based on `LATE_REPAIR_SELECTOR_ARGS`
computed in the Late-repair route section above) whether to reach the
late-repair controller at all — this is what makes the flagged and unflagged
paths exercise the SAME entrypoint, not two divergent implementations. With
`LATE_REPAIR_SELECTOR_ARGS` empty (the default), `close-route-select.py` is a
byte-for-byte pass-through: `ARTIFACT_CHAIN` is the identical resolver JSON
the bare invocation always produced, and the script never touches the
late-repair controller. This order is mandatory for explicit and bare close alike: bind the parent
task-id, then invoke the read-only resolver. Do not put a singular parent
ticket/QA existence gate before it.

`pass_with_exceptions` (ticket 20260911-011232)
means every hard error is resolved but one or more disclosed, evidenced,
non-defect conditions remain — retain `disclosed_exceptions[]` from the result
verbatim; it MUST be surfaced into the Step 2 QA dispatch prompt below (never
silently absorbed into an undifferentiated pass) and QA MUST independently
corroborate each entry before granting `CLOSE: YES` (see Step 2's appended
verdict branch 10). Retain the entire JSON for every later close step. In
particular, `mode`, `lanes`, `report_paths`, `artifact_paths`,
`commit_whitelist_artifacts`, `qa_inputs`, and `disclosed_exceptions` MUST come
from this one result, not a fresh glob, filename guess, or hand-rolled
singular check.

- `mode == "singular"` preserves the existing N == 1 chain.
- `mode == "fanout"` requires each lane ticket/context/dev-report/passing
  QA-report plus the parent canonical aggregate and parent completion. Parent
  ticket/context/QA are optional, not missing prerequisites.
- `/close` MUST NOT copy lane data into, or fabricate, a parent
  ticket/context/QA-report, canonical aggregate or completion. A missing
  completion remains a resolver failure that the originating `/dev` cycle must
  fix.

### do-report lite preflight (non-force, /do path)

If `DO_REPORT` was set during task-id resolution, skip the normal-path artifact preflight entirely and run this lite check instead:

- Read `$DO_REPORT`. Verify top-level `task_id == TASK_ID`, `source == "do"`, `do.files_modified` is a non-null array, and `DO_STATUS == "completed"`, where `DO_STATUS` is the one decision on `do.status` (`lib/obligation.terminal_status`: the terminal status the report carries, or empty):

  ```bash
  DO_STATUS="$(python3 -c 'import json, os, sys; sys.path.insert(0, os.path.expanduser("~/.claude/hooks")); from lib.obligation import terminal_status; print(terminal_status("do-report.v1", json.load(open(sys.argv[1]))) or "")' "$DO_REPORT")"
  ```

  Any other `DO_STATUS`, or any other failed check here, is a finding on `$DO_REPORT`: `close_route_finding "$DO_REPORT" "do-report status is '<observed>', not 'completed'" "do-report lite preflight"`. The /do work it describes is unfinished, so this preflight's own step works the finding: dispatch dev again under the same task id to complete the /do work (no /close orchestrator writes the do-report), re-read the do-report as the same `source_check`, and the preflight passes only once the status is `completed`.
- No ticket, context, dev-report, qa-report, or completion existence checks apply.
- Set `SPEC_ID=""` (no cp-state for /do work). Skip the cp-state resolver entirely.
- Set `ARTIFACT_CHAIN=""`; a do-report is not a `/dev` artifact chain. Proceed
  directly to inspector dispatch without shard inference.

### Normal-path artifact preflight (non-force)

Resolve the optional cp-state handoff for the QA close gate. `/close` runs no
spec-split resolver: a split is checked at its producer's stop (G2, the spec
subagent's) and taken at `/dev*`'s entry, never re-checked here.

- If `.claude/specs/<TASK_ID>/cp-state-qa.json` exists, bind `SPEC_ID="$TASK_ID"`,
  `CP_DIR=".claude/specs/$TASK_ID"`.
- Else bind `SPEC_ID=""` and skip the QA cp-state `SECOND ACTION`.

When `SPEC_ID` is non-empty, `/close` MUST hand the QA subagent
`$CP_DIR/cp-state-qa.json`; this is what makes the close gate participate in the
same check-in/checklist chain as `/dev`.

### Artifact schema gate (interactive schema validation — closes the §13 asymmetry)

The structural preflight (Step 0's chain call above) is a hand-rolled shape check. It does NOT run the JSON-Schema validators (`schemas/dev-report.v1.json` / `schemas/qa-report.v1.json`) that the `/dev-overnight` contract path applies via `hooks/lib/contract_runtime.py`. Historically that made interactive `/dev` artifacts categorically exempt from schema validation (ARCHITECTURE.md §13). This gate removes that exemption using the SAME `contract_runtime` engine (Draft7Validator) — it does NOT touch the overnight contract machinery.

Run the gate over the exact normal-path `ARTIFACT_CHAIN.report_paths[]`; this is
the canonical dev + QA pair for singular mode and the canonical aggregate plus
every lane dev/QA report (and a validated optional parent QA if present) for
fan-out mode. Do not synthesize a parent QA input. Paths are relative to the
resolver's `--project-dir`; the harness code + schemas live under `~/.claude`. Populate
`REPORT_PATHS` directly from the retained JSON, preserving order:

```bash
mapfile -t REPORT_PATHS < <(python3 -c \
  'import json,sys; print(*json.loads(sys.argv[1])["report_paths"], sep="\n")' \
  "$ARTIFACT_CHAIN")
source ~/.claude/venv/bin/activate 2>/dev/null || true
SCHEMA_GATE_OUT="$(python3 -c '
import sys, os
sys.path.insert(0, os.path.expanduser("~/.claude/hooks"))
from lib import contract_runtime as cr
rc = 0
for p in sys.argv[1:]:
    r = cr.validate_report_artifact(p)
    if r["status"] == "fail":
        rc = 2
        print("SCHEMA-GATE FAIL:", p, "->", r["schema"])
        for e in r["errors"]:
            print("   -", e)
    else:
        print("SCHEMA-GATE " + r["status"].upper() + ":", p, "(" + (r.get("reason") or r.get("schema") or "") + ")")
sys.exit(rc)
' "${REPORT_PATHS[@]}")"
SCHEMA_GATE_RC=$?
printf '%s\n' "$SCHEMA_GATE_OUT"
```

Blocking semantics:
- **Non-zero (`SCHEMA-GATE FAIL`)**: a report DECLARED a schema version (`report_version`) but VIOLATED its schema. Each `SCHEMA-GATE FAIL:` line names the offending report path; each is a finding on that path, routed by the Routing loop to the dispatch that owes the report, which fixes the named field(s):

  ```bash
  if [ "$SCHEMA_GATE_RC" -ne 0 ]; then
    while IFS= read -r FAILED_REPORT; do
      close_route_finding "$FAILED_REPORT" "artifact schema gate reported SCHEMA-GATE FAIL for this report" "artifact schema gate (contract_runtime.validate_report_artifact)"
    done < <(sed -n 's/^SCHEMA-GATE FAIL: \([^ ]*\) ->.*/\1/p' <<<"$SCHEMA_GATE_OUT")
  fi
  ```

  Inspector dispatch (Step 1) proceeds once the routing loop has re-run the gate and it passes.
- **Exit 0 (`SCHEMA-GATE PASS` / `SKIP`)**: proceed.
  `validate_report_artifact()` is version-gated and no-ops (never fail-closed)
  for an artifact kind with no registered schema, unparseable JSON
  already rejected by the structural resolver, or an unversioned legacy record.
  Every required dev/QA report in a fan-out chain is nevertheless presented to
  this gate through `report_paths`; an optional parent report is omitted only
  when the resolver says it is absent and optional.

`/close --force` is deprecated and no longer short-circuits before this gate (see "Forced-override path" above) — this gate always runs on the normal path.

### Step 1: Agent dispatch — three inspectors (orchestrator authority — `commands/close.md` itself, NOT QA)

**TodoWrite ordering reminder (task 20260519-211515 R3 / AC3)**: TodoWrite mark-as-in_progress for step N must precede any Agent() call dispatched within step N.
The orchestrator MUST emit a TodoWrite call updating the Step-N todo item to `in_progress` BEFORE invoking any Agent() in Step N. REQUIRED ordering: TodoWrite first, then Agent(). Always update the in_progress marker BEFORE dispatch. Before dispatch of any inspector (or any subagent in any Step), the matching Todo item MUST already be in_progress; otherwise do not dispatch.

**Authority note**: inspector subagents (`style-inspector`, `cleanliness-inspector`, `prompt-inspector`) are orchestrator-only auditors. ONLY this `/close` command may dispatch them. Subagents (including QA in Step 2) have NO authority to dispatch inspectors. This Step 1 is the orchestrator-layer dispatch site.

**Compute the cycle-diff file list** before dispatch:

- **Closed-task path** (`ARTIFACT_CHAIN.status in {"pass", "pass_with_exceptions"}`): read the
  `dev.files_modified` array from the canonical report named by
  `ARTIFACT_CHAIN.canonical_dev_report`; use that aggregate union verbatim as
  `<cycle-diff-file-list>`. Do not rebuild the union from lane files.
- **do-report path** (`DO_REPORT` is set, i.e. `do-report-<TASK_ID>.json` exists): read `do.files_modified` array verbatim as `<cycle-diff-file-list>`. Do NOT fall through to the Irregular path.
- **Irregular path** (no dev-report-<TASK_ID>.json and no do-report — e.g., hand-edits): run `git diff --name-only` against the relevant repo's cycle commit range to compute the file list. For nested-`.claude` edits the relevant repo is the nested git repo at `~/.claude` (working-tree root); for parent-repo edits use the parent-repo working-tree root (`$HOME`, resolved — not an author-absolute literal).
- If both paths yield an empty list, record `<cycle-diff-file-list>=` (empty) and proceed with dispatch — inspectors will return findings=[] and Step 5 will treat all cleanliness branches as non-blocking.

**Parallel detection check** — before dispatch, use only the retained resolver
result: a parallel cycle is detected exactly when
`ARTIFACT_CHAIN.mode == "fanout"`. Do not re-scan filenames or reinterpret
`parallel_workers`; that would create a second, divergent fan-out authority.

**Registry name** — `<SESSION_ID>` in the inspectors' FIRST ACTION lines below is the registry directory of `$TASK_ID`, printed by `python3 ~/.claude/hooks/prompt-workflow.py registry-dir "$TASK_ID"` (the value Step 2 binds as `$SESSION_ID`).

**If a parallel cycle is detected** — dispatch inspectors SEQUENTIALLY (one Agent call at a time, wait for each to return before the next). **Obligation wiring (20261001-161041-r11, G1/G2 producer-role coverage):** each Agent call's prompt MUST begin with that inspector's own `FIRST ACTION` dev-registry sentinel-read line, followed by a well-formed `<obligation v="1">` block (docs/reference/close-commit-zero-failure-mechanism-20260928.md §1.2 — instantiated per-dispatch from the already-bound `<TASK_ID>`, never hand-invented) naming that inspector's own report path/schema/identity:

- Agent call 1: `subagent_type: style-inspector`, prompt begins with the literal line `FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<SESSION_ID>/style-inspector.json to register with the enforcement system. Do this BEFORE any other tool call.` followed by `<obligation v="1">{"task_id": "<TASK_ID>", "lane": null, "lane_set": null, "role": "style-inspector", "pipeline": "close", "profile": "singular", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this call, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>", "artifacts": [{"kind": "json", "path": "docs/dev/style-inspector-report-<TASK_ID>.json", "schema": "style-inspector-report.v1", "identity": {"request_id": "<TASK_ID>"}}]}</obligation>`, then includes `--changed-files <cycle-diff-file-list>`, instructs the inspector to write its report to `docs/dev/style-inspector-report-<TASK_ID>.json`, and (if `codex_required = true`) includes the literal line `codex_required: true`. Wait for completion.
- Agent call 2: `subagent_type: cleanliness-inspector`, prompt begins with the literal line `FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<SESSION_ID>/cleanliness-inspector.json to register with the enforcement system. Do this BEFORE any other tool call.` followed by `<obligation v="1">{"task_id": "<TASK_ID>", "lane": null, "lane_set": null, "role": "cleanliness-inspector", "pipeline": "close", "profile": "singular", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this call, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>", "artifacts": [{"kind": "json", "path": "docs/dev/cleanliness-inspector-report-<TASK_ID>.json", "schema": "cleanliness-inspector-report.v1", "identity": {"request_id": "<TASK_ID>"}}]}</obligation>`, then includes `--changed-files <cycle-diff-file-list>`, instructs the inspector to write its report to `docs/dev/cleanliness-inspector-report-<TASK_ID>.json`, and (if `codex_required = true`) includes the literal line `codex_required: true`. Wait for completion.
- Agent call 3: `subagent_type: prompt-inspector`, prompt begins with the literal line `FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<SESSION_ID>/prompt-inspector.json to register with the enforcement system. Do this BEFORE any other tool call.` followed by `<obligation v="1">{"task_id": "<TASK_ID>", "lane": null, "lane_set": null, "role": "prompt-inspector", "pipeline": "close", "profile": "singular", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this call, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>", "artifacts": [{"kind": "json", "path": "docs/dev/prompt-inspector-report-<TASK_ID>.json", "schema": "prompt-inspector-report.v1", "identity": {"request_id": "<TASK_ID>"}}]}</obligation>`, then includes `--changed-files <cycle-diff-file-list>`, instructs the inspector to write its report to `docs/dev/prompt-inspector-report-<TASK_ID>.json`, and (if `codex_required = true`) includes the literal line `codex_required: true`. Wait for completion.

**If no parallel cycle is detected** — dispatch all three inspectors in parallel (original behavior): emit ONE message containing THREE Agent tool calls (concurrent, not sequential). **Obligation wiring (20261001-161041-r11)** — identical FIRST ACTION + `<obligation v="1">` prefix as the sequential branch above, per inspector:

- Agent tool call 1: `subagent_type: style-inspector`, prompt begins with the literal line `FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<SESSION_ID>/style-inspector.json to register with the enforcement system. Do this BEFORE any other tool call.` followed by `<obligation v="1">{"task_id": "<TASK_ID>", "lane": null, "lane_set": null, "role": "style-inspector", "pipeline": "close", "profile": "singular", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this call, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>", "artifacts": [{"kind": "json", "path": "docs/dev/style-inspector-report-<TASK_ID>.json", "schema": "style-inspector-report.v1", "identity": {"request_id": "<TASK_ID>"}}]}</obligation>`, then includes `--changed-files <cycle-diff-file-list>`, instructs the inspector to write its report to `docs/dev/style-inspector-report-<TASK_ID>.json`, and (if `codex_required = true`) includes the literal line `codex_required: true`.
- Agent tool call 2: `subagent_type: cleanliness-inspector`, prompt begins with the literal line `FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<SESSION_ID>/cleanliness-inspector.json to register with the enforcement system. Do this BEFORE any other tool call.` followed by `<obligation v="1">{"task_id": "<TASK_ID>", "lane": null, "lane_set": null, "role": "cleanliness-inspector", "pipeline": "close", "profile": "singular", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this call, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>", "artifacts": [{"kind": "json", "path": "docs/dev/cleanliness-inspector-report-<TASK_ID>.json", "schema": "cleanliness-inspector-report.v1", "identity": {"request_id": "<TASK_ID>"}}]}</obligation>`, then includes `--changed-files <cycle-diff-file-list>`, instructs the inspector to write its report to `docs/dev/cleanliness-inspector-report-<TASK_ID>.json`, and (if `codex_required = true`) includes the literal line `codex_required: true`.
- Agent tool call 3: `subagent_type: prompt-inspector`, prompt begins with the literal line `FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<SESSION_ID>/prompt-inspector.json to register with the enforcement system. Do this BEFORE any other tool call.` followed by `<obligation v="1">{"task_id": "<TASK_ID>", "lane": null, "lane_set": null, "role": "prompt-inspector", "pipeline": "close", "profile": "singular", "dispatched_at": "<ISO-8601 UTC ending in Z, captured immediately before this call, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>", "artifacts": [{"kind": "json", "path": "docs/dev/prompt-inspector-report-<TASK_ID>.json", "schema": "prompt-inspector-report.v1", "identity": {"request_id": "<TASK_ID>"}}]}</obligation>`, then includes `--changed-files <cycle-diff-file-list>`, instructs the inspector to write its report to `docs/dev/prompt-inspector-report-<TASK_ID>.json`, and (if `codex_required = true`) includes the literal line `codex_required: true`.

**Wait** for all three Agent tool calls to return. Each inspector writes its findings JSON to its assigned report path; the orchestrator does not re-interpret or re-aggregate those findings here — Step 2's QA dispatch passes the three concrete report paths as inputs and QA applies the AC-2.6 verdict-plumbing logic against them.

**Transient-failure retry (both dispatch branches).** Inspector dispatch over the API can hit transient infrastructure errors — `529 Overloaded`, `Server is temporarily limiting requests` / rate-limited, or a subagent that returns with 0 tokens and no report written. These are NOT inspection results. When an inspector returns such a transient error, RE-DISPATCH that ONE inspector (same prompt — not the others) up to 3 times with escalating backoff (~5s, ~15s, ~30s) before giving up. If the 3 retries still fail transiently, that inspector's report is simply still missing and is handled by the missing/invalid-report check immediately below — performed by the orchestrator, before Step 2 ever dispatches QA — never silently treated as advisory. A substantive (non-transient) inspector result — including one that reports findings or returns a clean verdict — is NEVER retried. Sequential branch: retry the current inspector before moving to the next. Parallel branch: after the initial batch returns, re-dispatch only the inspector(s) that failed transiently.

**Missing/invalid-report re-dispatch (orchestrator-owned, before Step 2 — 20261001-161041-r11 / AC5).** After the dispatch above (including the Transient-failure retry) completes for all three inspectors, the orchestrator — never QA, which has no inspector-dispatch authority per the Authority note at the top of this Step — checks each inspector's own report path for existence and schema-validity, reusing `hooks/lib/contract_runtime.validate_artifact_for_obligation()`'s existing fail/pass semantics under that inspector's own obligation-named path + registered schema id (`style-inspector-report.v1`, `cleanliness-inspector-report.v1`, `prompt-inspector-report.v1` respectively — `fail` on a missing or schema-invalid report, `pass` on a present, shape-matching one). For any inspector whose report fails that check, the orchestrator records an unresolved finding on that inspector's own report path (`close_route_finding "<inspector report path>" "report missing or schema-invalid" "inspector report validation"`; the Routing loop's declaring-dispatch reader answers with that inspector's own dispatch) and re-dispatches that SAME inspector (same prompt template, same `<obligation v="1">` block, a fresh `dispatched_at`) before Step 2 ever dispatches QA, then re-runs the same validation. A re-dispatch whose report bytes and unresolved set are unchanged is `no_progress`: the orchestrator arbitrates by diagnosing why the inspector keeps producing no valid report, and a persistent environment-class cause (R14) is the defined wait (`close_awaiting_input`). QA is not dispatched while an inspector report is still unresolved — never a silent advisory downgrade. This re-dispatch is entirely a Step 1 / orchestrator action; it does not loosen QA's documented lack of inspector-dispatch authority (preserved verbatim below and at this Step's Authority note), and it does not require flipping either `CLAUDE_OBLIGATION_GATE` or `CLAUDE_OBLIGATION_STOPGATE` out of their advisory-first defaults.

The three concrete inspector report paths produced by Step 1 — for verbatim cross-reference by Step 2's QA dispatch prompt — are:

- `docs/dev/style-inspector-report-<TASK_ID>.json`
- `docs/dev/cleanliness-inspector-report-<TASK_ID>.json`
- `docs/dev/prompt-inspector-report-<TASK_ID>.json`

These exact path strings (with `<TASK_ID>` substituted) MUST appear verbatim inside the Step 2 QA dispatch prompt body so the cross-reference between Step 1 output and Step 2 input is mechanical, not narrative.

### Step 2: Delegate close debate to QA subagent

**Bind this dispatch's own QA sentinel session** (M7 — close.md's OWN deterministic session binding, computed entirely from the already-bound `$TASK_ID` by the one task-id rule, `obligation.registry_dir_for`: the source cycle's `dev-<timestamp>` or `dev-command-<timestamp>` registry when it exists). This makes the QA-report correlation the SubagentStop hook performs (`hooks/subagentstop-e2e-enforce.py`) resolvable via its task_id-anchored branch even when this `/close` runs in a different session than the originating `/dev` cycle:

```bash
SESSION_ID="$(python3 ~/.claude/hooks/prompt-workflow.py registry-dir "$TASK_ID")"
```

Use the Agent tool with `subagent_type: qa` ONCE per independent judging round (a re-judge after producers fixed findings is a NEW round, dispatched fresh; QA never fixes what it judges). The entire debate of a round happens inside that single subagent call. Pass this prompt (substitute paths and $TS):

```
FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<SESSION_ID>/qa.json to register with the enforcement system. Do this BEFORE any other tool call.
SECOND ACTION (only if SPEC_ID is non-empty): read $CLAUDE_PROJECT_DIR/$CP_DIR/cp-state-qa.json to load your mandatory checklist before the debate. Mark each completed checkpoint with ~/.claude/scripts/spec-check.py mark --spec-id <SPEC_ID> --agent qa --agent-id $CLAUDE_AGENT_ID --cp-id <cp-NN>. Waive only with ~/.claude/scripts/spec-check.py waive --spec-id <SPEC_ID> --agent qa --agent-id $CLAUDE_AGENT_ID --cp-id <cp-NN> (auto-text records actor + ISO timestamp). You MUST leave zero pending checkpoints before Stop (a discipline expectation tracked via spec-check.py — no hook blocks exit on pending checkpoints today). If `$CLAUDE_AGENT_ID` is unavailable, use the `agent_id` value written into the cp-state file by the read.

<obligation v="1">
{"task_id":"<TASK_ID>","role":"qa","pipeline":"close","profile":"final_verification","dispatched_at":"<ISO-8601 UTC ending in Z, captured immediately before this call, for example the output of date -u +%Y-%m-%dT%H:%M:%SZ>","artifacts":[{"kind":"markdown","path":"docs/dev/close-report-<TASK_ID>.md","identity_anchor":"<TASK_ID>","terminal_line_regex":"^(CLOSE: YES([ \\-—(].*)?|CLOSE_FINDINGS: [0-9]+ items?)$","waived_by_response":"^CLOSE_REPORT_APPEND_(ERROR|CRITICAL): "},{"kind":"response_line","terminal_line_regex":"^(CLOSE: YES([ \\-—(].*)?|CLOSE_FINDINGS: [0-9]+ items?|CLOSE_REPORT_APPEND_(ERROR|CRITICAL): .*)$"}],"consistency":"verdict_class"}
</obligation>

You are the QA gatekeeper evaluating whether a completed development can be closed. The orchestrator passes a `codex_required: <true|false>` flag in this dispatch:

- **`codex_required: true`** (user passed `--codex` to /close): you run a MULTI-ROUND INTERNAL DEBATE with OpenAI Codex (via the Skill tool) yourself. Follow the full Debate protocol below (Round 1 + 1b + 1b' + Round 2/3 + verdict branches 1/2/3/4/5/6/7 with branch 9 N/A).
- **`codex_required: false`** (default — no `--codex` flag): SKIP all `Skill(codex)` invocations. Run a SINGLE-ROUND QA-ONLY ASSESSMENT covering the 4 Workflow Integrity Dimension bullets + 1b cleanliness-of-THIS-diff inspector preconditions. Apply verdict branch 9 (codex disabled by user) — see verdict rules below. Branches 3/6/7 are N/A in this mode.

In both modes, the caller does NOT orchestrate rounds; you own the loop.

Input artifacts (read them first):
- Artifact-chain result: <the complete retained ARTIFACT_CHAIN JSON, or "none" for /do>
- Mode: <ARTIFACT_CHAIN.mode, or "do">
- Lane matrix: <ARTIFACT_CHAIN.lanes JSON array; [] for singular or /do>
- Report paths: <ARTIFACT_CHAIN.report_paths JSON array; [] for /do>
- QA inputs: <ARTIFACT_CHAIN.qa_inputs JSON array; [] for /do>
- Disclosed exceptions: <ARTIFACT_CHAIN.disclosed_exceptions JSON array VERBATIM;
  [] when status=="pass". Non-empty only when status=="pass_with_exceptions"
  (ticket 20260911-011232) — each entry names a hard error the resolver moved
  out of errors[] because it matched a structured, evidenced, non-defect
  disclosure. You MUST independently corroborate every entry before granting
  CLOSE: YES on a pass_with_exceptions chain (see verdict branch 10 below);
  never treat this array as pre-cleared just because it reached you.>
- Singular inputs: <parent ticket/context/dev-report/QA-report/completion paths
  from artifact_paths when mode=singular; otherwise omit>
- Fan-out inputs: <for each lanes[] row, its task_id/ticket/context/dev_report/
  qa_report, plus canonical_dev_report and completion; never invent a parent
  ticket/context/QA-report>
- do-report: <do-report-<ts>.json for /do work, otherwise omit>

Treat the `lanes[]` array as a lane matrix for one parent close decision, not as
a bundled implementation-verification prompt. In fan-out mode read every row and
every `qa_inputs[]` entry; one missing/failing/inconsistent lane blocks closure.
The resolver's passed matrix is authoritative for membership and paths.

Debate protocol (all runs INSIDE you):

Round 1:
  1a. Form your initial assessment (YES/NO) on whether the dev can close. Consider:
      - Are all acceptance criteria measurably met (evidence, not code review)?
      - Is the root cause addressed and the fix correct & complete?
      - Regression risks? Scope drift? Missed edge cases?

      WORKFLOW INTEGRITY DIMENSION (mandatory — evaluate ALL four bullets explicitly; report a per-bullet PASS / FAIL / N/A-with-reason in the transcript; every FAIL is a finding that opens a round-open return regardless of AC coverage — see "Findings and return forms" below):
        1. **Downstream consumability** — Can the artifacts under evaluation be consumed by downstream commands (`/commit`, `/push`, `/merge`) without manual patching of timestamps, names, or artifact contracts? Require the supplied resolver result to have `status in {"pass", "pass_with_exceptions"}` and verify that normal `/commit` can admit the exact `commit_whitelist_artifacts`. In singular mode this is the existing parent chain. In fan-out mode the lane artifacts in that exact whitelist are consumable without copying/renaming them or fabricating parent ticket/context/QA artifacts. If a human would have to patch an artifact or manufacture a pseudo-parent artifact, this bullet is FAIL. **For /do path** (DO_REPORT is set): N/A-with-reason — changelog-analyst accepts the do-report as its staging-whitelist source; evaluate consumability against do-report + planned close-report only.
        2. **task-id chain consistency** — Use the supplied resolver matrix rather than imposing one universal filename shape. `mode == "singular"` requires the existing parent ticket → context → dev-report → QA-report → completion chain under one task-id. `mode == "fanout"` requires every `lanes[]` row's ticket/context/dev-report/QA-report to use that row's lane task-id, plus the parent canonical dev-report and completion under the parent task-id; parent ticket/context/QA are optional and absence is PASS. Any required identity mismatch, undeclared/missing lane, stale canonical, or completion index gap would contradict `status in {"pass", "pass_with_exceptions"}` and is FAIL. **For /do path** (DO_REPORT is set): N/A-with-reason — chain is `do-report → close-report` under the same `<task-id>`; the `/dev` artifact chain is intentionally absent.
        3. **Pre-existing-defect rule** (rewritten per spec-20260503-091826 Section 5.4 rule 1+2 — out-of-scope-by-default UNLESS user-need-impact OR security OR cleanliness-of-THIS-diff) — If a Round-1 critique surfaces a "pre-existing architectural defect" or similar, the debate resolves as follows:
             (a) if THIS cycle's BA spec CLAIMS to address the defect AND the claim maps to user-need / path-dependent shared infrastructure / security / cleanliness-of-THIS-diff → the defect IS in scope and must be evaluated on its merits. If the BA-spec claim does NOT map to one of those four axes (i.e., BA over-expanded into path-external scope), the claim is itself out-of-scope and falls through to (d) — pre-existing-out-of-scope, NOT NO; the AC-deviation / out_of_scope_observations path applies instead.
             (b) if the pre-existing defect actively blocks user-need success in THIS cycle's spec (i.e., the user-stated requirement cannot be satisfied without addressing the defect) → it IS in scope; bullet evaluates on its merits and FAILS only if the defect remains;
             (c) if the pre-existing defect is a security hole (Section 5.4 rule 2: security holes are exceptions — must be fixed even when outside the user-need path) → it IS in scope and must be fixed; bullet FAILS unless addressed;
             (d) otherwise — the pre-existing defect is OUT of scope by default. Bullet PASSES. Recording in `out_of_scope_observations` is the correct disposition; the "pre-existing / out-of-scope" walkback is the default behavior, not a forbidden one. The user's binding directive: if something does not impede user experience, security, or the cleanliness of the repository as a whole, it is not necessarily a reason for NO — pre-existing defects that do not impact user needs / security / cleanliness-of-THIS-diff are NOT NO triggers.
        4. **Self-deployability** — Can the changes be committed and shipped via the project's own commit/push toolchain (`/commit`, `/push`, `/merge`) without out-of-band patching? Evaluate as the AND of these sub-items:
             (i) **/commit consumability** (PASS/FAIL) — `/commit` accepts the resolver's exact `commit_whitelist_artifacts` plus the close/inspector outputs without orchestrator-side jq/Edit patches. For fan-out this explicitly includes each validated lane artifact and does not require optional parent ticket/context/QA artifacts. FAIL if any manual artifact patch or pseudo-parent artifact was required.
             (ii) **Push permission** (PASS/FAIL) — the orchestrator's git identity has write access to the target remote(s). FAIL if push was blocked by remote permissions or required a human to push from a different identity.
             (iii) **No commit-channel bypass** (PASS/FAIL) — no manual `git commit` outside agent context, no `CLAUDE_PROJECT_DIR` override to bypass repo-rooted hook gates, no `auto-bulk:` pattern abuse to smuggle changes past `pretool-git-privilege-guard.py`. FAIL if any of these bypass channels was used.
             (iv) **User-only physical filesystem actions** (N/A-with-reason — NEVER FAIL) — any sub-item that would require the user to perform a physical filesystem action the orchestrator structurally cannot perform itself is evaluated as N/A-with-reason, NOT FAIL. The canonical example is the user touching `.hook-refactor-allow` to authorize a hook-tree edit: human-in-the-loop is intentional anti-fabrication protection per Trap 11; orchestrator-creatable sentinels would defeat the protection's threat model. The N/A reason MUST cite Trap 11 verbatim. This clause covers ONLY user-only physical filesystem actions; it does NOT cover the bypasses listed in sub-item (iii), which remain FAIL.
           Bullet 4 is PASS when (i), (ii), and (iii) are each PASS (or N/A-with-reason where structurally inapplicable per (iv)). Any FAIL in (i)–(iii) is Bullet 4 FAIL.

  1b. **Cleanliness-of-THIS-diff preconditions — inspector reports as input** (per spec-20260503-091826 Section 5.4 rule 3 + Section 5.2: integrate clean tools such as style-inspector into the close steps). Inspector reports are ALREADY GENERATED by the orchestrator (`/close` Step 4) BEFORE this dispatch. Read them at the following exact paths:
      - `docs/dev/style-inspector-report-<TASK_ID>.json`
      - `docs/dev/cleanliness-inspector-report-<TASK_ID>.json`
      - `docs/dev/prompt-inspector-report-<TASK_ID>.json`
      **DO NOT attempt to dispatch inspector subagents — you do not have that authority; the orchestrator already did Step 4.** Inspector dispatch is `/close`-orchestrator-only by design (`agents/style-inspector.md` etc. are auditors invoked at the orchestrator layer). Treat the JSON contents of the three report files above as input to the AC-2.6 verdict-plumbing rules below. Inspector findings DO NOT directly decide the verdict — `close.md`'s finding-routing rules at AC-2.6 govern when an inspector finding becomes a routed finding. If any of the three report files is still missing or unreadable when you read it here, that is not something for you to resolve: Step 1's own missing/invalid-report re-dispatch (see "Missing/invalid-report re-dispatch" above) already performed one bounded re-dispatch of that specific inspector — by the orchestrator, before QA's debate in this Step 2 dispatch began. You still have NO authority to invoke the inspector yourself (this Step's Authority note, close.md:420, preserved verbatim). Report the still-missing/unreadable report as an unresolved finding (path = that report's path) so the orchestrator routes it to the dispatch that owes it and a fresh round re-judges — instead of treating it as empty/advisory input to the AC-2.6 finding-routing rules.

  1b'. Invoke the Skill tool with skill=codex. Pass codex a prompt that includes:
      - The same input artifact paths
      - Your Round-1 position and rationale
      - Inspector findings from 1b above (so codex can weigh them)
      - Instruction (user-need + THIS-diff cleanliness scoped, per spec-20260503-091826 Section 5.4 rule 3 + 4): "Challenge whether this close grants YES on something that ACTUALLY satisfies the user-stated need (not just the BA AC's mechanical wording). Flag any cleanliness/style violations introduced by THIS diff (not pre-existing). Out-of-path observations and pre-existing technical debt are NOT grounds for a finding under this scoping. Reply with exactly one line `CODEX: YES` or `CODEX: NO` followed by 3-8 sentences of rationale. **If CODEX: NO, you MUST also list 2–5 specific actionable items that would flip your verdict to YES — without this list, a NO verdict is incomplete and QA will treat it as an observation, not a blocker.**"
  1c. Parse codexs response. If parsing ambiguous, treat as NO.

  **Inspector-finding → routed-finding plumbing** (AC-2.6 — encodes Section 5.4 rule 3: cleanliness scope = only violations newly introduced in this diff become findings; pre-existing historical dirt is entirely ignored):

  - **(a) Diff-scoped invocation**: close passes `--changed-files <cycle-diff-changed-files>` (e.g., derived from `git diff --name-only $BASE..HEAD` or token-equivalent cycle-diff source — changed-line metadata for line-level inspectors / file list for file-level inspectors) to all three inspectors at Round-1.
  - **(b) NEW-violation → routed finding** (only **provably-new** findings; pre-existing/ambiguous/untagged default to **ignore**): an inspector finding becomes a routed finding ONLY when it is explicitly proven NEW (introduced by THIS cycle's diff). It is a finding on that file, routed by the Routing loop (the dispatch whose own tool calls wrote the file; none -> that round's own report), that dispatch fixes it, the inspectors are re-run on the new diff (verifiers, independent), and a fresh QA round re-judges; the round that found it returns `CLOSE_FINDINGS: <n> items`. Findings that are pre-existing, untagged, ambiguous, or from non-diff-aware inspector runs default to **ignore** (cannot become a routed finding):
    - **Line-level inspectors** (e.g., `style-inspector` emitting `file:line`): a finding is provably NEW when **(i) its line falls within the cycle diff's changed-line range / diff-hunk overlap for that file AND (ii) the finding is also absent from the pre-diff baseline of the same file** (the violation did not exist on the corresponding pre-diff line content). Overlap alone is **necessary but NOT sufficient** — a pre-existing violation preserved on a modified line is still pre-existing. Soft fallback when pre-diff baseline comparison is impractical: dev/inspector documents the proxy used (e.g., "overlap-only used because <reason>") and close treats overlap-only findings as **advisory** unless the proxy explicitly stipulates newness.
    - **File-level inspectors** (`cleanliness-inspector`, `prompt-inspector` — granularity = `file`, not `file:line`): the inspector's output MUST distinguish NEW vs pre-existing. Two acceptable mechanisms (dev's discretion; **may be implemented individually OR combined**):
      - **(i) Inspector-side filtering**: the inspector itself emits findings only for NEW violations (e.g., comparing its analysis against a pre-diff baseline of the same file, or analyzing diff hunks directly). Findings emitted under mechanism (i) in `--changed-files` mode count as NEW **only when the inspector's documentation explicitly declares the filtering contract** (per AC-12.1 documentation requirement); absent that explicit contract, untagged file-level findings fall under the default-safe ignore rule below.
      - **(ii) Inspector-side tagging**: the inspector emits findings for the listed files but tags each with an explicit `introduced_in_diff: bool` field (or token-equivalent positive marker like `is_new: true|false`). close honors that tag.
    - **Default-safe rule for ambiguity** (covers tag absence, null, unknown, missing field, untagged output): close.md verdict logic requires an **explicit positive marker** (`introduced_in_diff: true` or token-equivalent positive value) to route a file-level finding. Findings where the marker is `false`, absent, null, unknown, or where the inspector emitted output without a marker at all, MUST default to **ignore** — they CANNOT become routed findings. `absent/unknown -> ignore` is the encoded default. Section 5.4 rule 3 requires explicit proof of newness, not absence of evidence.
    - **Default-safe rule for non-diff-aware mode** (covers no `--changed-files` arg / default full-repo run): file-level inspector findings produced in default/full-repo/non-diff-aware mode are **advisory** (never routed) unless they carry an explicit positive new-in-this-diff marker per the rule above. close.md's full-repo inspector runs (e.g., for orientation or audit) MUST NOT escalate file-level findings into routed findings absent that marker.
    - close.md verdict logic honors whichever mechanism the inspector chose (or the combination thereof): if (i) with explicit-contract documentation, close treats every finding emitted in `--changed-files` mode as NEW; if (ii), close reads the explicit positive marker and applies the default-safe rule above.
  - **(c) Pre-existing → never routed**: inspector findings whose `file:line` is **not in this diff**, OR whose file-level marker is `introduced_in_diff: false` / absent / null / untagged, OR which originate from a non-diff-aware full-repo run, MUST NOT become routed findings. `pre-existing finding ignored`. `pre-existing technical debt` and historical dirt are out-of-scope for cleanliness verdict per Section 5.4 rule 3.

  **Worked example** (the three required paths α/β/γ are walked through; a NEW finding is routed and counted in the round-open return `CLOSE_FINDINGS: <n> items`):

  - Suppose `style-inspector --changed-files` returns a finding at `path/to/component.tsx:42` (line-level), and `cleanliness-inspector --changed-files` returns a file-level finding at `path/to/util.ts` with `introduced_in_diff: true`.
  - Close evaluates each finding against the cycle diff (changed-line metadata / diff hunk ranges for line-level inspectors; honors the file-level inspector's NEW vs pre-existing marker for file-level inspectors).
  - **diff-NEW finding (line-level)**: line 42 is within the diff's changed-line range AND was absent from the pre-diff baseline of `component.tsx` → routed finding "new style violation introduced at component.tsx:42" to the dev lane that claims `component.tsx`.
  - **diff-NEW finding (file-level)**: `cleanliness-inspector` returned `introduced_in_diff: true` for `util.ts` under explicit-contract mechanism (i) or tagging mechanism (ii) → routed finding "new cleanliness violation in util.ts" to the dev lane that claims `util.ts`.
  - **(α) pre-existing finding in a changed file → ignore**: `style-inspector` returns a finding at `path/to/component.tsx:7` where line 7 IS within the diff's changed-line range BUT the pre-diff baseline of `component.tsx` already contained the same violation on the corresponding pre-diff line — overlap is necessary but not sufficient, and the pre-diff baseline shows the violation pre-existed. Outcome: ignore, not a finding. Continue evaluating other findings.
  - **(β) untagged / ambiguous finding → ignore**: `cleanliness-inspector` emits a file-level finding for `path/to/legacy.ts` with NO `introduced_in_diff` field, NO token-equivalent positive marker, and the inspector documentation does not declare an explicit-contract filtering claim — under the Default-safe rule for ambiguity, `absent/unknown -> ignore`; this `untagged finding ignored`. Outcome: not a routed finding. Continue evaluating other findings.
  - **(γ) non-diff-aware mode finding → advisory / non-blocking**: `prompt-inspector` was invoked in default full-repo mode (no `--changed-files` argument) for an orientation pass; it returns a file-level finding for `path/to/agent.md`. Under the Default-safe rule for non-diff-aware mode, this is `advisory` (never routed). Outcome: record the observation, do not route it; downstream cycles may address it through the `out_of_scope_observations` ledger if desired.

Round 2 (skip if Round 1 ended with both QA=YES and CODEX=YES):
  2a. Re-assess your position after reading codexs Round-1 challenge. If you still say YES, strengthen justification; if codex surfaced a real issue, update to NO.
  2b. Invoke Skill(codex) again with your updated position + codexs prior challenge + artifact paths. Ask codex to either confirm or press further, replying again with `CODEX: YES` / `CODEX: NO` + rationale.

Round 3 (skip if earlier unanimous YES):
  3a. Final reassessment.
  3b. Final Skill(codex) call with full history.

Verdict rule (UNANIMOUS CONSENT, with infrastructure-failure escape valve):

Track a single field about the codex consultation across all rounds:
  `codex_status`: `ok` | `failed_quota` | `failed_timeout` | `failed_parse`

- `ok` — at least one round received a parseable `CODEX: YES` or `CODEX: NO`.
- `failed_quota` — every round attempted hit a usage-limit / quota error.
- `failed_timeout` — every round attempted hung past the round's deadline.
- `failed_parse` — every round attempted returned content that could not be parsed into `CODEX: YES` / `CODEX: NO`. Unlike `failed_quota` / `failed_timeout`, the round produced output -- it just did not match the required format. QA MUST preserve the verbatim raw output and perform a manual dissent scan before branch 7 can grant CLOSE: YES (FINDING-4).

**Findings and return forms**: branches 3, 4, 5, 7's two fail-overs, 8, 9's two sub-branches, and 10's fall-through below never end in a negative verdict. Each one is a **finding**: QA records it in the close-report with the artifact path it concerns (that round's own report, `docs/dev/close-report-<TASK_ID>.md`, when it names none) and counts it. A round that opened at least one finding ends with the round-open return `CLOSE_FINDINGS: <n> items` (`<n>` = number of open findings): it is NON-LANDING (it grants nothing, lands nothing, and `/commit` reads it as not landed). The orchestrator then routes each finding through the Routing loop above — the dispatch that owes its path runs again and fixes, and QA is re-dispatched as a fresh independent judging round that re-judges from the artifacts (QA is a verifier; it NEVER edits the artifact it judges and never fixes a finding itself). No sentence in this command grants YES on a disclosure while a finding is unresolved: `CLOSE: YES*` is returned only by a round that opened no finding. The two legal returns are therefore exactly: landed (one of the five `CLOSE: YES` forms) or round-open (`CLOSE_FINDINGS: <n> items`). Findings routed by the branches: codex dissent items and QA dissent items go to the dispatch that owes the cited artifact (an unsatisfiable AC cites the acceptance criteria); a Workflow Integrity FAIL goes to the dispatch that owes the failing artifact (bullets 1, 2, 4i: the artifact itself; bullet 3: the dev lane's artifact; bullet 4iii bypass: the files the bypass wrote, else that round's own report). A completed repair is attached to the close-report as one `## Disclosures` line (below) — a record of the fix, never a substitute for it.

Verdict branches:

1. **Unanimous YES (normal happy path)**: QA position = YES AND codex position = YES (codex_status = ok) AND all four Workflow Integrity Dimension bullets PASS (or N/A-with-reason; never FAIL) → **CLOSE: YES**.

2. **AC-deviation-PASS branch** (per spec-20260503-091826 Section 5.4 rule 4: dev deviating from BA spec AC but empirically satisfying user requirement = PASS, provided dev report explicitly records the AC deviation reason). When QA's verdict is YES on user-need verification (i.e., `verified_against_complaint = true` AND `passed_user_requirement = true` per agents/qa.md report contract) but dev's diff deviated from one or more BA AC literal-wording → **CLOSE: YES** is allowed iff ALL of the following hold (necessary AND sufficient — codex-refined; citation alone is necessary but NOT sufficient):
    - **(a)** Dev report explicitly identifies the deviated AC by ID (e.g., `AC-3.1`, `AC-12.1`) — `ac_deviation_with_user_need_satisfied: true` is present in the dev report and the deviated AC IDs are listed.
    - **(b)** Dev report cites the verbatim user-need text from the BA spec that the implementation actually satisfies (the deviation is from AC mechanics, not from user need; the verbatim user-need text is reproduced).
    - **(c)** Dev report provides evidence (test result / measurement / observation) that the implemented behavior satisfies that need. Hand-wave reasoning is rejected.
    - **(d)** **QA SHALL reject this branch if the deviated AC directly encodes user-need / security / THIS-diff-cleanliness — for those, AC-deviation is plain AC-FAIL, NOT AC-deviation-PASS.** This prevents the branch becoming a downgrade vector. If the deviated AC's text encodes the user-need test itself, or a security check, or a cleanliness-of-THIS-diff check, deviation collapses back to AC-FAIL and the result follows branch 5 (QA dissent → routed finding, round-open return).
    - When (a)–(c) hold and (d) does not trigger, the verdict is **CLOSE: YES** and the close-report records the deviation rationale verbatim.

3. **Substantive Codex dissent**: codex_status = ok AND any round ended with `CODEX: NO` AND the disagreement was not resolved by a later round → codex's dissent is a finding set: codex MUST have listed 2-5 actionable flip items, and each item is a finding against the artifact it cites (that round's own report when it cites none), routed per "Findings and return forms". The round returns `CLOSE_FINDINGS: <n> items`; the producers fix; a fresh round re-judges. A codex NO without a flip list is an observation, not a finding. Trigger condition is unchanged.

4. **Workflow Integrity FAIL**: any of the four bullets evaluates to FAIL (not N/A-with-reason) → each failing bullet is a finding on the artifact it concerns (bullets 1, 2, 4i: the defective artifact's own path; bullet 3: the dev lane's artifact; bullet 4iii: the files the bypass wrote, else that round's own report), regardless of QA / codex positions; the round returns `CLOSE_FINDINGS: <n> items`. Trigger condition is unchanged.

5. **QA dissent**: QA position = NO at end of final round → QA MUST name concrete items; each is a finding against the artifact it cites (that round's own report when none), routed per "Findings and return forms"; the round returns `CLOSE_FINDINGS: <n> items`. Trigger condition is unchanged.

6. **Codex infrastructure failure (BUG-CLOSE-2 escape valve)**: codex_status ∈ {`failed_quota`, `failed_timeout`} AND QA position = YES AND all four Workflow Integrity Dimension bullets PASS → **CLOSE: YES (degraded codex consultation)**. The verdict is granted on QA's substantive YES alone because codex never produced a substantive opinion to disagree with. Document the codex_status value verbatim in the close-report transcript under a new "Degraded codex consultation" section. The dissent line is replaced by an annotation: `degraded codex consultation: codex_status=<value>, codex contributed no substantive position`. This branch ONLY applies when the failure mode is unambiguous mechanical / infrastructural transport failure (the request never produced any output at all); a successful CODEX: NO still falls under branch 3. `failed_quota` and `failed_timeout` are unambiguous (the round produced no body to inspect). `failed_parse` is NOT in this branch -- see branch 7.

7. **Codex parse failure (FINDING-4 hardening for `failed_parse`)**: codex_status = `failed_parse` AND QA position = YES AND all four Workflow Integrity Dimension bullets PASS → conditional **CLOSE: YES (degraded codex consultation)**, BUT ONLY when QA also attests in the close-report:
    - **(a)** the verbatim raw codex output text from each `failed_parse` round is recorded in the "Degraded codex consultation" section;
    - **(b)** QA performed a manual scan of that verbatim output for substantive dissent signals -- including but not limited to: `CODEX: NO`, `Codex: NO`, the literal substring `NO`, the words `bug`, `defect`, `regression`, `wrong`, `incorrect`, `must not`, `should not`, `does not work`, `fails`, `broken`, or any prose explicitly objecting to the proposed close;
    - **(c)** QA explicitly states the determination: `manual parse: NO substantive dissent signal found in failed_parse output` (verbatim wording required).

    `failed_parse` differs from `failed_quota`/`failed_timeout` because the request DID complete and the codex CLI DID emit content -- the parser merely could not map it to the `CODEX: YES` / `CODEX: NO` format. Skipping the manual scan would create a downgrade vector: a substantive `NO` could ride a malformed response into a YES verdict. If the manual parse finds ANY dissent signal, treat it as substantive Codex dissent (branch 3): a finding carrying the verbatim signal as its detail, routed per "Findings and return forms". If QA omits the verbatim attestation, the close-report is defective: a finding on `docs/dev/close-report-<TASK_ID>.md`, whose declaring QA dispatch repairs the report and re-attests in the next round (branch 8's target).

8. **Other ambiguity / parse failure on QA's side / unresolved disagreement after final round**: a defective close-report is a finding on `docs/dev/close-report-<TASK_ID>.md`, detail = a one-sentence description of the ambiguity / parse-failure / unresolved disagreement; its declaring QA dispatch repairs the report and the next round re-judges (conservative default — never silently absorbed). Distinct from branch 6: the failure is on QA's reasoning side, not codex's transport.

9. **Codex disabled by user (no `--codex` flag)** — `codex_required = false` from Step 1 → QA runs **single-round QA-only assessment** of the 4 Workflow Integrity bullets + 1b cleanliness preconditions; no `Skill(codex)` invocations attempted; `codex_status` is set to the literal sentinel `disabled_by_user`. Verdict logic collapses to:
   - QA position = YES AND all four Workflow Integrity bullets PASS (or N/A-with-reason; never FAIL) AND no NEW-violation cleanliness inspector finding → **CLOSE: YES** (annotation: `codex_disabled_by_user: codex consultation skipped because --codex flag was not passed; verdict granted on QA's substantive YES + 4 bullets PASS alone`).
   - QA position = NO at end of single round → findings per branch 5 (concrete items routed to the producers of the cited artifacts); the round returns `CLOSE_FINDINGS: <n> items`.
   - Any of the four bullets FAIL → findings per branch 4; the round returns `CLOSE_FINDINGS: <n> items`.
   - AC-deviation-PASS branch 2 is fully applicable in the codex-disabled path — when QA verdict is YES on user-need verification AND dev report contains a valid `ac_deviation_with_user_need_satisfied: true` block satisfying clauses (a)–(d) of branch 2, **CLOSE: YES** is granted with the deviation rationale recorded.
   - Branches 3 / 6 / 7 / 8 are all N/A in the codex-disabled path (codex was never invoked; there is no codex dissent to weigh, no infrastructure failure to handle, no parse failure to scan).
   - The close-report MUST record `codex_status: disabled_by_user` in the "Codex consultation" section (NOT `failed_*`), and the per-round entries record `[Codex] consultation skipped: --codex flag not passed; QA-only assessment performed`. The final line MUST be `CLOSE: YES — codex disabled by user` (when the round opened no finding; or the form `CLOSE: YES - with disclosures: <n> items` once every finding the cycle routed has been fixed and re-judged clean, `<n>` = the `## Disclosures` lines) or, when the round opened findings, `CLOSE_FINDINGS: <n> items`.

10. **Disclosed-exceptions corroboration (ticket 20260911-011232 — appended, does NOT renumber branches 1-9)**: applies ONLY when `ARTIFACT_CHAIN.status == "pass_with_exceptions"` (i.e., `disclosed_exceptions[]` is non-empty). This branch runs IN ADDITION to whichever of branches 1-9 above determined the base verdict from QA/codex positions and the four Workflow Integrity bullets — it is a second, independent gate layered on top, mirroring R4's `late-repair-controller.py verify-disclosure` being a separate substantive check on top of a structural eligibility computation.
    - For EVERY entry in `disclosed_exceptions[]`, QA MUST independently re-verify and cite the entry's underlying evidence — re-running at least the commands the cited qa-report/dev-report itself cites, not merely re-reading its prose. Record each entry's `code`/`path`/`lane_task_id`/`classification` plus the corroboration performed and its result in the close-report transcript.
    - If QA corroborates every entry, and the base verdict from branches 1-9 was YES, → **CLOSE: YES** proceeds with the disclosed-exceptions corroboration recorded verbatim in the close-report (a new "Disclosed exceptions corroboration" section: one row per entry).
    - If QA CANNOT corroborate an entry (the cited evidence does not hold up, is missing, or on re-running contradicts the disclosure), that entry is a **finding** on the cited qa-report / dev-report (path = the entry's path or `lane_task_id`'s report; detail = why corroboration failed), regardless of what the base verdict from branches 1-9 was. That artifact's role fixes it, and QA re-corroborates in a fresh round by re-running the cited commands. A `pass_with_exceptions` chain therefore never silently reaches `CLOSE: YES` on the strength of the resolver's structural eligibility computation alone; QA's independent corroboration (followed by routing for any entry that fails it) is the actual truth-adjudication step, exactly as `late-repair-controller.py verify-disclosure` is for R4.
    - Out-of-scope-by-default (Pre-existing-defect rule, bullet 3) does NOT apply here — a disclosed exception is, by construction, part of THIS chain's own deliverable being evaluated, not a pre-existing defect elsewhere.

The `/close --force` flag is deprecated and no longer bypasses anything (see "Forced-override path" above) — it is a no-op alias of the normal path, so every verdict branch above runs identically whether or not `--force` was passed.

Transcript file: write the full debate to `docs/dev/close-report-<task-id>.md` (substitute `<task-id>` with the value resolved in Step 3 — e.g. the source `/dev` cycle's task-id; do NOT use a fresh `date +%Y%m%d-%H%M%S` here, that would break /commit's PRIMARY-path lookup) with this structure:
  # Close Debate Report
  Task-id, artifact-chain mode, Input files, Rounds run, Verdict. For fan-out,
  include the supplied `lanes[]` matrix and `qa_inputs[]` paths so the report
  records which independently-passed lanes were rolled into the parent decision.
  Workflow Integrity Dimension: explicit per-bullet status (1. Downstream consumability: PASS/FAIL/N/A; 2. task-id chain consistency: PASS/FAIL/N/A; 3. Pre-existing-defect rule: PASS/FAIL/N/A; 4. Self-deployability: PASS/FAIL/N/A) — with one-sentence reason for each FAIL or N/A.
  Codex consultation: explicit `codex_status` value (`ok` | `failed_quota` | `failed_timeout` | `failed_parse`). When the value is one of the failure modes, include a "Degraded codex consultation" section that records: which rounds failed, the verbatim error / timeout / parse-issue from each attempt, and the explicit acknowledgement that the verdict was granted on QA's substantive YES alone (per Verdict rule branch 6). For `failed_parse` specifically (FINDING-4), the section MUST additionally include: (i) the verbatim raw codex output text from EACH failed_parse round, (ii) QA's explicit per-round manual scan note, and (iii) the verbatim attestation `manual parse: NO substantive dissent signal found in failed_parse output`. Without all three, branch 7 is not satisfied and the result falls to branch 8 (a defective close-report: a finding on it, routed to its declaring QA dispatch).
  For each round: [QA] position + rationale; [Codex] position + rationale (or "consultation failed: <reason>" when codex_status was failed-* in that round).
  **`## Disclosures` (present whenever the routing loop completed at least one repair this cycle):** one line per completed repair, as an attached record only, in the exact format `path: problem | 归因: role(lane) | 修复: fix evidence` (field labels stay in Chinese; no code prefix). The final line's `<n>` count (in the `CLOSE: YES - with disclosures: <n> items` form below) MUST equal the number of disclosure lines in this section. Omit the section entirely when no repair was completed.
  At bottom: the LAST non-empty line of the file MUST be EXACTLY this attempt's verdict line (Return value below: a landed `CLOSE: YES*` form such as a bare line `CLOSE: YES`, or the round-open line `CLOSE_FINDINGS: <n> items`). A round-open section is appended like any other (append-only) and never lands anything. Do NOT prefix it with `Final verdict:`, `Verdict:`, or any other label — the runtime parser (`hooks/lib/close-verdict.py`) reads the last non-empty line and requires it to start literally with `CLOSE: `; any prefix breaks `/commit`'s admission check.

Overwrite policy: if `docs/dev/close-report-<task-id>.md` already exists with a `CLOSE:` line in it (a prior closure attempt for the same task-id), do NOT silently overwrite: always preserve the existing bytes and append a fresh debate as a new section dated by ISO timestamp, then require the file's LAST non-empty line to be exactly THIS new attempt's own legal `CLOSE:` verdict line (see Return value below). Perform this append via the deterministic helper — write the new dated section's full text (ending in this attempt's own legal `CLOSE:` line) to a temp file, then invoke it with ABSOLUTE paths rooted at `$PROJECT_ROOT` (resolved in Step 0 above) so the helper can never target the wrong project's `docs/dev` tree regardless of QA's own working directory:
  `source ~/.claude/venv/bin/activate 2>/dev/null || true && python3 ~/.claude/scripts/close-report-append.py --report-path "$PROJECT_ROOT/docs/dev/close-report-<task-id>.md" --section-file "<absolute-temp-section-path>" --task-id "<task-id>"`
  (activates the venv first, matching Step 0's own invocation pattern above). The helper performs an atomic, verified append and never mutates a byte of the file's existing content — see its own module docstring for the full read-append-readback-verification and atomicity design. Branch explicitly on its exit code:
  - **exit 0**: stdout is one line of JSON `{"status":"ok","report_path":...,"verdict_line":...}` — validate `status == "ok"`, then use `verdict_line` (NOT the raw JSON) as QA's own Return-value line.
  - **exit non-zero**: stdout is exactly the sentinel line below; propagate that exact line as QA's own Return-value output. Any other stdout shape (missing/malformed JSON on exit 0, or a non-sentinel line on exit non-zero) is a bug in the invocation itself — treat it as a verification failure and fail closed rather than guessing a verdict.
  Such a failure is NEVER a basis for falling back to treating the prior closure's verdict as authoritative for this new attempt: print the single non-`CLOSE:`-prefixed line `CLOSE_REPORT_APPEND_ERROR: <read|append|readback|verification>: <error detail>` as this attempt's not-landed signal, and run no Step 3 verdict echo, scoring, session summary, or workflow update for it — the pre-existing report's prior verdict is never reused as this attempt's result. The command then retries the atomic append under the R15 progress measure (progress = the section is now appended): a persistent environment-class cause (R14) is the defined wait (`close_awaiting_input`); a defective section text is a finding on `docs/dev/close-report-<task-id>.md`, whose declaring QA dispatch repairs the section text.

Return value: print to stdout, as the final line of your response, the verdict line your verdict branch names — a landed `CLOSE: YES` form, or the round-open line `CLOSE_FINDINGS: <n> items` (NON-LANDING: findings are open and routed; nothing is granted); your obligation's `terminal_line_regex` declares the legal set — or the `CLOSE_REPORT_APPEND_ERROR: <read|append|readback|verification>: <error detail>` line of the Overwrite policy above. Every reader classifies the last non-empty line through `hooks/lib/close-verdict.py`: a landed form reads `yes`, the round-open line `no`, anything else `unknown` (fail closed).
```

### Step 3: Generate close-report + workflow update

Take the final line QA returned — either a landed `CLOSE: YES*` form or the round-open `CLOSE_FINDINGS: <n> items` — and echo whichever one QA returned in the orchestrator's text message to the user. A round-open echo is followed by routing (the Routing loop, then a fresh QA round), never by this step's scoring, session summary, rating, or workflow-update branches. The close-report itself is written by QA inside Step 2; this step is the echo + ensures the report file exists at `docs/dev/close-report-<task-id>.md`.

**Two distinct final-line contracts — DO NOT confuse**:
- **Close-report FILE** (`docs/dev/close-report-<task-id>.md`): the LAST non-empty line of the FILE must be EXACTLY the verdict line Step 2's Return value names. This is the runtime-parser contract consumed by `hooks/lib/close-verdict.py` and `/commit`'s admission check. This contract is enforced INSIDE the file QA wrote in Step 2; nothing in Step 3 alters it.
- **Orchestrator's stdout text message to the user**: the orchestrator's response stream in Step 3 begins with the `CLOSE:` verdict echo, continues with the Session Summary (CLOSE:YES branch only — see below), and ends with the rating `<options>` XML block (CLOSE:YES branch only — see below). On the round-open path there is no Session Summary and no `<options>` block, so the echo is itself the last line of the orchestrator's message. The `<options>` block being the literal final stdout content on CLOSE:YES does NOT violate the close-report FILE contract — they are two different output channels.

**Mascot scoring — close outcome (spec-20260518-225715 §5.1; M4 — task 20260529-210616)**:

> Reachability rule (AC8): Step 2 can no longer produce a literal `CLOSE: NO` Return-value line, so the helper's "last-line `CLOSE: NO`" decision-matrix bullet in step 2 above and step 5's `close_fail_qa_pass`/`close_fail_qa_fail` direct-issuance bullets below apply only to a close-report whose last line was written outside Step 2 (a legacy report or an out-of-band tool). Disclosure-driven negative scoring (dev -10, ba -5, qa -12 or -10/-5/0) is NOT implemented; it is a Won't-Have pending separate user sign-off.

Scoring runs ONLY AFTER the close-report file is written (Step 2 wrote it) AND AFTER the verdict line is echoed. The decision of WHICH `close_success_*` event to issue (if any) is delegated to the executable helper `scripts/close-scoring-decide.py` — NOT inline orchestrator reasoning. Issuing a `close_success_*` event before QA finalizes its verdict is forbidden.

Procedure:

1. Determine `qa_ever_rejected` from every QA report named by
   `ARTIFACT_CHAIN.qa_inputs` (the single parent QA in singular mode; all lane
   QA reports in fan-out mode). It is true if any resolved QA history contains a
   rejection. On the do path, use false because no prior QA cycle exists. Do not
   substitute or create a parent QA-report for fan-out scoring.
2. Invoke the helper to decide which close_success_* event (if any) is permitted:

   ```
   bash -c 'source ~/.claude/venv/bin/activate && python3 ~/.claude/scripts/close-scoring-decide.py --task-id "<task-id>" --qa-ever-rejected "<true|false>"'
   ```

   The helper reads the close-report at `docs/dev/close-report-<task-id>.md`, classifies its last non-empty line via `hooks/lib/close-verdict.py`, and emits stdout JSON `{"events": [...], "skip_reason": "<string|null>"}`:
   - missing close-report → `events=[]`, `skip_reason` contains "missing"
   - last-line `CLOSE: NO` → `events=[]`, `skip_reason` non-null
   - last-line `CLOSE: YES` + qa_ever_rejected=false → `events=["close_success_qa_pass"]`, `skip_reason=null`
   - last-line `CLOSE: YES` + qa_ever_rejected=true → `events=["close_success_qa_fail_fixed"]`, `skip_reason=null`

3. The orchestrator MUST ONLY issue the events returned by the helper. If `events[]` is empty, log `skip_reason` and SKIP all `close_success_*` score updates. Tests MUST invoke `scripts/close-scoring-decide.py` directly against fixtures; tests MUST NOT reimplement the decision logic in a parallel test harness.

4. For each event name returned by the helper, issue three `score-update.sh` calls (ba, dev, qa). Example for the qa_pass branch:

   ```
   bash ~/.claude/scripts/score-update.sh --agent dev --event close_success_qa_pass --note "<task-id>"
   bash ~/.claude/scripts/score-update.sh --agent ba  --event close_success_qa_pass --note "<task-id>"
   bash ~/.claude/scripts/score-update.sh --agent qa  --event close_success_qa_pass --note "<task-id>"
   ```

   (dev +2, ba +1, qa +1 — Path A rebalance task 20260524-205206 M1; cycle-total cross-agent sum = +4.)

   For the qa_fail_fixed branch the event name is `close_success_qa_fail_fixed` (same deltas).

5. `close_fail_*` branches are NOT routed through the helper — the orchestrator issues them directly when the verdict is `CLOSE: NO`:
   - `CLOSE: NO` AND QA had passed (PM/inspector or codex caught issue post-QA) → `score-update.sh --event close_fail_qa_pass` for ba/dev/qa. (dev -10, ba -5, qa -12.)
   - `CLOSE: NO` AND QA had failed (rejection upstream) → `score-update.sh --event close_fail_qa_fail` for ba/dev/qa. (dev -10, ba -5, qa 0.)

Defense-in-depth: `scripts/score-update.sh` itself enforces the same precondition (M3 — task 20260529-210616). Any `close_success_*` call without a legal `CLOSE: YES` last-line in `docs/dev/close-report-<note>.md` exits 5 ("precondition unmet"), so even if the orchestrator skips the helper or the helper is bypassed, the lifecycle log cannot be polluted with premature success entries.

**Session Summary — CLOSE:YES branch only (mandatory before rating)**:

- If the verdict is **`CLOSE: YES`** (class `yes`) AND `--force` was NOT passed in `$ARGUMENTS`:
  - The orchestrator MUST produce a `## Session Summary` section in its text output to the user.
  - Format: chronological order, 6 buckets, each entry CONCISE (1–2 sentences max per bullet):
    - **Accomplished**: what was done this session
    - **Not accomplished**: gaps, deferred items, out-of-scope decisions
    - **User needs satisfied**: which stated user requirements were met
    - **User needs not satisfied**: which stated user requirements remain unmet
    - **Bugs encountered**: bugs surfaced during the session (if none, omit or write "none")
    - **Improvement opportunities**: technical debt, UX gaps, or follow-up items worth noting
  - **Conciseness rule**: each bullet MUST be exactly 1 sentence. Narrative paragraphs are FORBIDDEN. The entire summary MUST fit within 20 lines including the heading. Exception: if the bullet contains a verbatim user quote, reproduce it exactly as stated (no paraphrase, no truncation), then the quote itself counts as the sentence.
  - **Source binding**: read the canonical report and every lane report named by
    the retained `ARTIFACT_CHAIN.report_paths` / `qa_inputs`, plus
    `docs/dev/user-requirement-<DEV_SESSION_ID>.md` and
    `docs/dev/close-report-<task-id>.md`. In singular mode these resolve to the
    same parent dev/QA sources as before. Do NOT assume a parent QA-report exists
    in fan-out mode and do not improvise outcomes not present in the resolved
    artifacts. The user-requirement document remains primary for the user-needs
    buckets.
  - This summary appears in the orchestrator's text message to the user, AFTER the `CLOSE:` verdict echo and BEFORE the rating `<options>` block below.
- If the last line is the round-open `CLOSE_FINDINGS:` line (read-side class `no`/`unknown`, i.e. any non-YES): SKIP the session summary.

**User rating prompt — CLOSE:YES branch only (spec-20260518-225715 §5.1 line 136 verbatim: "Only fires after CLOSE:YES; CLOSE:NO does NOT prompt." (translated from spec))**:

- If the verdict is **`CLOSE: YES`** (class `yes`) AND `--force` was NOT passed in `$ARGUMENTS`:
  - Output the following `<options>` XML block at the VERY END of the orchestrator's text message to the user (after the verdict echo and session summary above). This block is in the orchestrator's text output only — NOT in the close-report file, which retains its `CLOSE:` final-line contract:

    ```
    <options>
        <option>5 stars -- Excellent</option>
        <option>4 stars -- Good</option>
        <option>3 stars -- Average</option>
        <option>2 stars -- Below average</option>
        <option>1 star -- Poor</option>
        <option>Skip rating</option>
    </options>
    ```

  - **Post-option handling contract**: the task-id MUST be retained in the orchestrator's context across the user's response. Parse the selected option text to extract the star count: "5 stars" → N=5, "4 stars" → N=4, etc. When N ∈ {1,2,3,4,5}, the orchestrator runs three `score-update.sh` calls:
    - `bash ~/.claude/scripts/score-update.sh --agent ba --event user_rating_<N> --note "<task-id>"`
    - `bash ~/.claude/scripts/score-update.sh --agent dev --event user_rating_<N> --note "<task-id>"`
    - `bash ~/.claude/scripts/score-update.sh --agent qa --event user_rating_<N> --note "<task-id>"`
  - When the user selects "Skip rating": NO score-update calls are made. (Skip does NOT produce a separate event — spec 5.1.)
- If the last line is any non-YES form (the round-open `CLOSE_FINDINGS:` line, class `no`/`unknown`): SKIP the rating entirely. Per spec 5.1 line 136 verbatim, the rating prompt fires only after CLOSE:YES, NOT after CLOSE:NO.

Then branch the workflow update:

- If the final verdict is `CLOSE: YES*`, the next action is
  `/commit <task-id> -m "<real session summary>"`.
- **(Edge Case 8 — resume guidance)** If `/close` printed an `AWAITING_INPUT:` line (a defined wait: causes (i)-(iii) in Routing helpers; no `CLOSE:` line and no close-report section were written, so nothing landed), the human's input channel is one of two routes, and the loop resumes in place from the step that was waiting once the input arrives (distinct from `/dev`'s internal 5-iteration-exhaustion guard in Step 16, which has its own documented path, unaffected by this section):
  - **Same-task-id resume** (default when the rejection doesn't require
    reopening scope): re-dispatch Dev, then QA, reusing the SAME `<task-id>`
    for every artifact filename (`docs/dev/context-<task-id>.json`,
    `docs/dev/ticket-<task-id>.md`, `docs/dev/dev-report-<task-id>.json`,
    `docs/dev/qa-report-<task-id>.json`, or their lane-suffixed equivalents)
    AND the source cycle's own `DEV_SESSION_ID` (commonly `dev-<task-id>`,
    but recover the EXACT value the original `/dev` cycle used — e.g. from
    its dev-registry directory listing — rather than assuming the prefix)
    for its existing `.claude/dev-registry/<DEV_SESSION_ID>/` registry — do
    not mint a new `DEV_SESSION_ID`. If the original `DEV_SESSION_ID` cannot
    be recovered, do not guess one; fall through to the Fresh continuation
    spec route below instead. For a fan-out cycle
    (`ARTIFACT_CHAIN.mode == "fanout"`), resume only the lane(s) named in
    the close dissent using each lane's own unchanged `lanes[].task_id` and
    its exact ticket/context/dev-report/QA-report paths from
    `ARTIFACT_CHAIN` — never fabricate a parent-level ticket/context/QA
    artifact the fan-out shape doesn't have. Once the resumed lane(s) or
    singular cycle pass QA, re-invoke `/close <task-id>` (the SAME parent
    `<task-id>`, so Step 0's chain call reads the correction) —
    the route by which `<task-id>`'s OWN close-report reaches `CLOSE: YES`.
  - **Fresh continuation spec** (fallback, when the dissent requires
    reopening a materially different scope, or when the original
    `DEV_SESSION_ID` cannot be recovered): create or update a continuation
    spec using `/spec-update` default continuation-spec mode, handing it the
    `ARTIFACT_CHAIN` Step 0 holds (it does not call the chain again). If the dev
    context has a source spec, append the close dissent and unresolved gaps
    to that spec; otherwise create a new spec. Next action:
    `/dev --spec <spec_path>`. No longer the only documented route.
  Do NOT direct a waiting close to `/commit` under either route.

## `--auto` mode: batch-discover and sequentially close (Must-Have #6, task 20260808-035658-lanel)

`--auto` discovers every `close_pending` PARENT task-id and walks each one, ONE
AT A TIME, through the exact same unmodified **Step 0 → Step 3** body (the
`### Step 0` through `### Step 3` headings above, up to this section) an
explicit `/close <task-id>` would run. It is structurally distinct from the human-only
`--bulk` escape hatch documented in `commands/commit.md` — `--auto` never
skips the close gate; it walks every discovered parent THROUGH the gate,
never around it.

1. **Discover** the candidate parent snapshot (frozen once, at the start of
   the batch — parents discovered mid-batch by a later scan are NOT added to
   the running batch):

   ```bash
   PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
   source ~/.claude/venv/bin/activate 2>/dev/null || true
   mapfile -t CLOSE_PENDING_PARENTS < <(python3 ~/.claude/scripts/dev-lifecycle.py list-actionable --next-action close --project-dir "$PROJECT_ROOT")
   ```

   `list-actionable` already returns a deterministically sorted list of
   `kind == "ticket"` parent task-ids only — lane rows and spec rows never
   appear (Must-Have #3). A `blocked` task is never included and is never
   force-closed by `--auto`. Each line is the parent's task-id, followed, for
   a `/dev` parent, by its chain result from the discovery's one chain call.

2. **Walk each parent sequentially** — no two parents run concurrently, and
   parent N+1's walk does not begin until parent N's walk has been classified
   (step 3 below). For each element `LINE` of `CLOSE_PENDING_PARENTS`, in order,
   bind `read -r TASK_ID ARTIFACT_CHAIN <<<"$LINE"` and re-enter this file at **Task-id resolution**'s
   `$ARGUMENTS` matches a timestamp pattern → non-force path branch, then run
   **Step 0** through **Step 3** exactly as written — Step 0 takes the line's
   `ARTIFACT_CHAIN` with `ROUTE_SELECT_RC=0` in place of its selector call (the
   discovery's call is this parent's one chain call; a `/do` parent's line has
   none and takes the do-report lite preflight), same Step 1 inspector dispatch, same Step 2 QA debate
   (`codex_required` from the `--codex` parsing above, shared across every
   parent in the batch), same Step 3 close-report write. Nothing in Steps 0-3
   is aware `--auto` is driving it.

3. **Classify the walk's outcome** at the orchestrator-procedure level (the
   walk is a sequence of individual tool calls this file's prose drives an
   agent through — not a single bash process an exit code terminates
   wholesale; see `scripts/dev-lifecycle.py`'s `classify_walk_outcome()` for
   the exact recognition predicate this mirrors):
   - **`hook_deny`** — a `PreToolUse`/`PostToolUse`/`Stop` hook literally
     blocked a tool call during the walk (observable shape: a
     `<Phase>:<hook-script> hook error: ... BLOCKED ...` tool result, per
     CLAUDE.md's Subagent Hook Discipline). The hook rejection is awaiting-input
     cause (i): PAUSE that parent, never retry or work around the rejected
     operation, and report which parent was mid-walk with the verbatim hook
     rejection as the awaiting-input line (`close_awaiting_input`). Parents are
     independent, so **record the outcome and continue** with the next parent
     in the frozen list.
   - **`ordinary_reject`** — any other non-success outcome for this parent
     (including a parent that is waiting on human input, recorded as waiting).
     `scripts/dev-lifecycle.py::classify_walk_outcome()` is a catch-all:
     `hook_deny`/`success`/`partial_abort` are matched explicitly and
     everything else falls through to `ordinary_reject`. It is parent-specific
     (about ONE parent's own artifacts and inputs), so **record the outcome
     and continue** to the next parent in the frozen list.
   - **`success`** — the walk reached Step 3 and wrote a `CLOSE: YES*`
     close-report. **Record and continue** to the next parent.

4. **Batch summary**: after the batch ends (list exhausted), print one line
   per attempted parent (`task-id: outcome`). Do not run the Session Summary / user
   rating block (those remain per-parent, inside each successful walk's own
   Step 3, unchanged) as a SECOND batch-level summary — the per-parent Step 3
   output already covers each `CLOSE: YES` parent individually.

Human-operator verification of this mode (QA cannot literally invoke
`/close --auto` — `disable-model-invocation: true` plus `settings.json`'s
global `Skill(close:*)` deny) is documented in `docs/dev/ticket-20260808-035658-lanel.md`
AC-L21: a separate human-operator-executed transcript at
`docs/dev/human-operator-transcript-<task-id>.md`, using the
`PARENT_START: <task_id>` / `PARENT_END: <task_id> outcome=<...>` schema.

## Constraints

- /close does NOT call Skill(codex). QA does, internally.
- /close does NOT manage rounds. QA does, internally.
- /close does NOT evaluate verdict. QA does, internally.
- QA is invoked once per independent judging round, regardless of `--force` (deprecated, never skips QA — see "Forced-override path"). A re-judge after producers fixed findings is a new round; QA never fixes what it judges. `--auto` does not change this invariant — it drives multiple SEQUENTIAL parent close decisions, each judged in its own rounds, never concurrently.
- `--auto` never bypasses Steps 0-3; it is structurally distinct from `--bulk` (documented in `commands/commit.md`), which skips the close gate entirely. `--auto` walks every discovered parent THROUGH the unmodified gate.
- **Scoped findings** (per spec-20260503-091826 Section 5.1: if something does not impede user experience, security, or the overall cleanliness of the repository, it is not necessarily a finding): a finding that would once have ended the attempt negatively is instead routed through the Routing loop above — to the dispatch that owes its artifact, fixed, and re-judged by a fresh independent round — and the only non-landing state is the defined AWAITING_INPUT wait; never a silent, undocumented pass. Recoverable transient infrastructure failures (e.g., Codex quota / timeout) follow the existing branch-6/7 graceful-degradation logic — this clause does NOT override branches 6/7. `--force` is deprecated and no longer produces an unconditional override of this logic (see "Forced-override path" above) — it is a no-op alias of the normal path.
- `disable-model-invocation: true` (frontmatter) means the model cannot self-invoke /close via SlashCommand — this applies equally to the forced path. Only a human can trigger `--force`.
