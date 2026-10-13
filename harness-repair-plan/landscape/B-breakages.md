# B-breakages: hard breakages that stop legitimate runs (B1-B4)

Repository: /home/user/awesome-claude-harness @ 09ab15b (read-only). All line numbers refer to that tree.
Execution sandbox (scratch copy via `git archive HEAD`, toy product repo, HOME and CLAUDE_STATE_DIR redirected,
PYTHONDONTWRITEBYTECODE=1): `scratchpad/landscape-work/B-breakages/` (`home/.claude` = harness copy, `prod` = product repo).
Prior evidence re-used and re-checked: `harness-cleanup/runtime-verification.md` (RV), `adv_overnight_result.json` (ADV-ON),
`harness-cleanup/problems.md` (X-ids).

Binding frame: every fix below acts on a PRODUCER (a hook, a launcher, the UserPromptSubmit hook, or a producer's own
prompt), never adds checks to /close or /commit, and adds no new mutable state files. Prose path repairs inside
close.md/commit.md only re-qualify an invocation that cannot run at all; they add no checks. Under rollout S10/S11 those
blocks are replaced by a single disposition call.

---

## Verification log (executed this session)

| # | What | Result |
|---|---|---|
| T1a | `stop-completion-gate.py` Stop in a product repo with a bridged `dev-<ts>` registry | rc=2 `COMPLETION_GATE_BLOCKED -- GATE_ERROR|FileNotFoundError ... owner: harness operator` |
| T1b | same, `stop_hook_active=true` | rc=2 again; round 2 adds the ARBITRATION directive (only exit is a self-written arbitration file) |
| T1c | gate patched to load the resolver from the harness (`_HOOKS_DIR.parent/scripts`), NO artifacts at all | rc=0. Resolver says `fail` with 2 errors, so the narrow signature does not match |
| T1d | patched gate, completion file present, dev/qa reports missing | rc=0 |
| T3a | `stop-overnight-timelock.py` directly, end_time +3h | rc=2 and a readable `TIME-LOCK ACTIVE ... Continue working on the current cycle.` |
| T3b | same through `stop-workflow-coordinator.py` | rc=2, **stderr 0 bytes**, stdout is only `{failed_phase:timelock, stderr_sha256:..., stdout_sha256:...}` |
| T3c | streak file `{Edit:1}` + a blocked Stop, then the next turn's Edit | streak unchanged; next Edit rc=2 `BLOCKED: Edit used consecutively beyond limit (2/1)` |
| T3d | fresh install (no `~/.claude/logs`), plain Stop in a product repo | coordinator rc=2 `failed_phase:auto_commit`, stderr 0 bytes (`checkpoint-core.sh: line 519: .../logs/checkpoint.log: No such file or directory`) |
| T3e | logs/ exists, but the machine has no git identity (`GIT_CONFIG_GLOBAL=/dev/null`) | **every** Stop rc=2 `failed_phase:auto_commit` (checkpoint.log: `commit-tree failed ... unable to auto-detect email address`), reason hidden |
| T3f | same with a git identity set | coordinator `pass`, all 4 phases rc=0 |
| T2-tz | timelock, end_time = now+1h (written `...Z` as the launcher does) | TZ=UTC: lock active 0h59m. **TZ=Asia/Shanghai: treated as expired, `CLOSEOUT GATE ... missing=final_summary, retro_status, artifact_checkpoint_status`**. TZ=America/Los_Angeles: `7h 59m` remaining |
| T2-wt | timelock with CLAUDE_PROJECT_DIR = a worktree under the main root | rc=0, lock silently off |
| T2-cancel | state `status=cancelled` | rc=0, released |
| T2-ct | `pretool-subagent-enforce.py`, launcher-shaped contract (`required_calls: []`), in-progress `Step 2`, Agent(pm, PLAN) | rc=2 `Case C (incomplete contract) ... no required_calls entry for step '2'` |
| T2-ct2 | malformed contract `{nope` | rc=0, enforcement silently off |
| T4a | do gate, report ABSENT, 3 Stops | rc=2, rc=2, then rc=0 `FORCED ALLOW`. **No report is written** |
| T4b | do gate, report `completed` with empty summary, 3 Stops | rc=2, rc=2, rc=0. Report stays `completed` with an empty summary |
| T4c | do gate, forged counter `{"blocks":9}`, first Stop | rc=0 at once (finalised to `blocked` with zero attempts) |
| P1 | close.md:338 / :345 run verbatim from the product root | rc=2 `can't open file .../prod/scripts/aggregate-dev-report.py` / `close-route-select.py` |
| P2 | close.md:246 `scripts/write-qa-mode.sh` | rc=127 |
| P3 | `~/.claude/scripts/write-qa-mode.sh` with CLAUDE_PROJECT_DIR unset (the real Bash-tool environment) | exit 1 `CLAUDE_PROJECT_DIR: CLAUDE_PROJECT_DIR not set` (write-qa-mode.sh:35) |
| P4 | commit.md:313 late-repair | rc=1, `state=[]` (State C can never be detected) |
| P5 | changelog-analyst.md:651 session-index guard | python `can't open file '/.claude/scripts/session-index.py'`; **guard did NOT fire** (eval of an empty string returns rc 0); GIT_INDEX_FILE unset, so the shared index is used |
| P6 | dev.md:1386, tickets.md:35, ba.md:780 | rc=2 each |
| P7 | `~/.claude/scripts/close-scoring-decide.py` from the product cwd (close.md:815 form) | rc=0 `{"events":["close_success_qa_pass"]}`. **Not broken** (corrects RV:88) |
| ENV | `echo $CLAUDE_PROJECT_DIR` inside this Claude Code Bash tool | **UNSET** (CLAUDE_CODE_SESSION_ID is set). This matches the harness's own note at dev-overnight.md:210-211 |

Corrections to prior evidence:
- RV:88 "close-scoring-decide.py errors in a product repo": not reproduced through the documented invocation (P7). Its code
  root is the git toplevel of its own directory, or its parent's parent (close-scoring-decide.py:60-78).
- ADV-ON step 10, "the closeout gate does not fire from the worktree cwd": this is true only when Claude Code's own project
  dir is the worktree (a session launched or resumed there). In a normal session the coordinator forwards
  CLAUDE_PROJECT_DIR = main root (stop-workflow-coordinator.py:143, :191-196), so the gate fires. This agrees with ADV-ON's
  verifier. The T2-wt mechanism is real but conditional; see B2.h.
- New since RV: T2-tz is worse than RV reported. In UTC+ zones there is no time-lock at all, and the closeout deadlock
  starts at the first Stop. T3e (no git identity blocks every Stop) is new. The /dev-command triple task-id (B1.c) is
  new. The escalation directory mismatch (B1.d) is new. The commit.md:334 infinite loop is new. The
  lane-completeness-watch no-op (B1.e) is new.

---

## B1: stop-completion-gate resolves harness code from the product repo and recognises only one failure signature (+ the product-root-relative path family)

### B1.a The resolver is loaded from the product root, so every /dev-family Stop is blocked outside the harness repo
- `hooks/stop-completion-gate.py:211-226`: `_import_resolve_chain(project_dir)` builds `project_dir / "scripts" / "resolve-dev-artifact-chain.py"` (**:218**). Product repos have no `scripts/`.
- `hooks/stop-completion-gate.py:418-428`: the import raises FileNotFoundError, which is caught and turned into finding `GATE_ERROR|FileNotFoundError`.
- `hooks/stop-completion-gate.py:398-401`: a GATE_ERROR renders "gate could not evaluate the chain | owner: harness operator". The agent cannot fix it.
- `hooks/stop-completion-gate.py:459-499`: progress machine. Rounds 2 and later add an ARBITRATION directive. The only exit is the orchestrator self-writing `docs/dev/arbitration-<cycle>.json` (:30-45, :293-311, :472-474), which is also a self-release hole (A-cluster).
- `hooks/stop-completion-gate.py:551-553`: `project_dir = CLAUDE_PROJECT_DIR or payload.cwd or getcwd()` is correct for the registry and artifacts, but it was reused for code.
- `settings.json:843`: registered as a standalone Stop hook, default mode block (:521-525), with no env override in settings.json.
- The correct in-repo pattern already exists: `hooks/prompt-workflow.py:1578` (`Path(__file__).parent.parent / 'scripts'`) and `hooks/stop-completion-gate.py:84` (`_HOOKS_DIR`). The resolver loads its aggregator relative to itself (`scripts/resolve-dev-artifact-chain.py:138-144`), so loading the resolver from the harness path works (T1c).
- Evidence: T1a, T1b; RV:28, RV:59-61; RV /dev stage critical #1.
- **Fix**: line 218 becomes `_HOOKS_DIR.parent / "scripts" / "resolve-dev-artifact-chain.py"`. One line.

### B1.b The trigger is only "sole missing completion"
- `hooks/stop-completion-gate.py:229-249` `_is_sole_missing_completion`: requires status fail AND exactly one error AND that error is MISSING_ARTIFACT on the completion path.
- `hooks/stop-completion-gate.py:419-424`: any other resolver failure adds no finding, so the Stop passes.
- Passing today: QA FAIL + completion (RV:62-64); an abandoned cycle with no dev-report (T1c); completion present but dev/qa missing (T1d); a Stop right after UPS (RV /dev stage high #5).
- **Fix** (interim rule from the G4 disposition table, until S8 lands): finding = resolver `status == "fail"` UNLESS the canonical dev-report parses, its identity is valid, and `dev.status in {"blocked","needs_review"}` (honest_blocked). The existing progress-measure, arbitration and awaiting_input machine (:459-506) is the bound, and its `{"continue": false}` awaiting stop is the honest class-a terminal. Requires B1.a and B1.c first, otherwise it turns into a permanent block for /dev-command.

### B1.c Three task-ids for one /dev-command cycle
- `hooks/prompt-workflow.py:1466-1471`: the hook mints registry dirs `dev-<ts>` (/dev) or `dev-command-<ts>` (/dev-command).
- `hooks/stop-completion-gate.py:187`: `task_id = entry.name[len("dev-"):]`, which turns `dev-command-<ts>` into `command-<ts>`.
- `commands/dev-command.md:335, :607, :618, :630, :673, :922`: artifacts are named `<timestamp>` (`dev-report-<timestamp>.json`).
- `commands/dev-command.md:941-942`: the postcondition passes `--task-id "$DEV_SESSION_ID"` (= `dev-command-<ts>`, dev-command.md:143).
- Effect: the gate and the postcondition each evaluate a task-id with no artifacts. Today the result is vacuous. Under B1.b it would be a permanent block.
- **Fix**: one derivation in the gate. Strip `dev-command-` before `dev-`, giving `<ts>`. dev-command.md:941-942 passes the same bare timestamp.

### B1.d Producer escalations are written where the terminal gate never reads them
- Writer: `hooks/subagentstop-artifact-contract-enforce.py:295-309` `_cycle_id` returns the obligation `task_id` (bare `<ts>`). `:573-574` `_cycle_dir` = `.claude/dev-registry/<cycle_id>`. Writes and reads at `:604`, `:611`, `:644` go to `.claude/dev-registry/<ts>/escalations/`.
- Reader: `hooks/stop-completion-gate.py:331-333, :410, :431` reads `.claude/dev-registry/dev-<ts>/escalations/` (cycle_id = registry dir name).
- **Fix**: the writer maps task_id to the registry dir name (`dev-<ts>`, or `dev-command-<ts>`), shared with B1.c.

### B1.e The same defect class in code: harness code or policy resolved against the product root
- `hooks/posttool-lane-completeness-watch.py:216-218` (registered at settings.json:725): the aggregator auto-invocation uses `Path(project_dir)/"scripts"/"aggregate-dev-report.py"`. In a product repo `script.exists()` is false, so it returns silently. The fan-out canonical aggregate is never auto-built at the producer side. **Fix**: `Path(__file__).resolve().parent.parent / "scripts"`.
- `hooks/lib/specialist_yield.py:70-74` (used by posttool-overnight-trace.py:34): the policy is read at `<project>/.claude/policies/specialist-degradation.v1.json`, so the shipped `policies/specialist-degradation.v1.json` is ignored everywhere except the author's `/root` layout (silent `_FALLBACK_POLICY`). **Fix**: resolve via `claude_home.resolve_optional("policies/...")`.
- `scripts/dev-fix.py:678-684`, `:2157-2160`: `root / "scripts/resolve-dev-artifact-chain.py"` and `aggregate-dev-report.py` under the product root. No live caller (grep: only README/INDEX), so this is dead code (E1). Fix it only if it is kept.
- Hazard, not a breakage: the todo-script lookups check the project first (`hooks/posttool-todo-count.py:22`, `hooks/pretool-workflow-gate.py:100`, `hooks/posttool-todo-tracker.py:24`, `hooks/prompt-workflow.py:331`, `hooks/lib/todo_canonical.py:19-27`). They work through the `~/.claude` fallback, but a product repo's `scripts/todo/<cmd>.py` would shadow the canonical checklist.
- Not broken (correction): `scripts/close-scoring-decide.py:50-78, :140` (P7); `scripts/close-report-append.py:205-217` defaults to its own parent's parent; `scripts/dev-lifecycle.py:109-117` has a `~/.claude` fallback.

### B1.f The same defect class in prose: product-root-relative harness invocations (each fails from a product root)
/close:
- `commands/close.md:335-345` Step 0: `cd "$PROJECT_ROOT" && python3 scripts/aggregate-dev-report.py` (:338) and `python3 scripts/close-route-select.py` (:345). rc=2 (P1). Step 0 cannot run.
- `commands/close.md:137`: the same Step 0 route-select call with `--late-repair`.
- `commands/close.md:142`, `:143`: "call `scripts/late-repair-controller.py finalize|verify-disclosure`", relative.
- `commands/close.md:243-251` QA-arming: `scripts/write-qa-mode.sh` (rc=127, P2), `scripts/write-e2e-enforce.sh`, `scripts/write-enforce-flag.sh`. Even when qualified with `~/.claude/`, write-qa-mode.sh:35 exits 1 because CLAUDE_PROJECT_DIR is unset in Bash (P3, see B1.g).
- `commands/close.md:776`: `python3 "$PROJECT_ROOT/scripts/close-report-append.py"`, under the product root.
- `commands/close.md:950`: `--auto` discovery `python3 scripts/dev-lifecycle.py list-actionable`, rc=2 (P6 class). /close --auto cannot discover anything.
- Contract text that teaches the relative form: `commands/close.md:367`, `:383`.

/commit:
- `commands/commit.md:313`, `:320`: `source venv/bin/activate && python3 scripts/late-repair-controller.py`. The `&&` short-circuits, so state="" and State C is never detected; the failure is silent (P4).
- `commands/commit.md:334-339`: `until ARTIFACT_CHAIN="$(python3 scripts/resolve-dev-artifact-chain.py ...)"; do route_finding ...; done`. From a product root python returns 2 forever and `route_finding` is undefined in commit.md (grep: no definition; X49). The result is an **unbounded loop** until the Bash timeout.
- `commands/commit.md:965`: `python3 scripts/dev-lifecycle.py list-actionable --next-action commit`.
- Contract text: `commands/commit.md:251`, `:274`.

/dev, /redev, /dev-command:
- `commands/dev.md:907`, `:945`: `source venv/bin/activate && python3 scripts/aggregate-dev-report.py`, rc=1.
- `commands/dev.md:1386-1387`: completion postcondition `python3 scripts/resolve-dev-artifact-chain.py ... || exit 2`, rc=2 (P6). /dev can never be "complete" by its own rule outside the harness repo.
- `commands/dev.md:214-215` (and the commented :217): fallback arming `scripts/write-e2e-enforce.sh`, `scripts/write-enforce-flag.sh` (hook-absent path only; the hook path prompt-workflow.py:1578-1610 is correct).
- `commands/dev-command.md:159-160` (+ :162): the same fallback arming.
- `commands/dev-command.md:194`: "Run `scripts/graphify-query.py`" (prose only, no qualified block; advisory).
- `commands/dev-command.md:941-942`: postcondition, rc=2.
- Contract text: `commands/dev.md:1391`, `commands/dev-command.md:945`, `commands/spec-update.md:52`, `:163`.

/dev-overnight:
- `commands/dev-overnight.md:1578`: `scripts/commit.sh` "(repo-relative path, run from the project root)", rc=127 in product repos (see also B2.a).

Other commands:
- `commands/tickets.md:35`: `python3 scripts/dev-lifecycle.py scan`, rc=2. /tickets is broken in product repos.
- `commands/paseo-daemon.md:98`, `:355`: `scripts/paseo-daemon-timers.py ensure|drain` (personal tool, C3).

Agents:
- `agents/ba.md:780`: `python3 scripts/blast-radius-tool.py`, rc=2.
- `agents/qa.md:1137`, `:1138`: `python3 scripts/qa-manifest-guard.py`.
- `agents/qa.md:1146`: `python3 scripts/qa-report-stale-iter-lint.py`.
- `agents/qa.md:1155`: `python3 scripts/blast-radius-tool.py --git-diff`.
- `agents/graphify.md:28`: "You run `scripts/graphify-enrich.py`".
- `agents/changelog-analyst.md:1855`, `:1899`, `:1905`: `scripts/precommitted-recovery.sh scan-shas|execute-commit|capture-sha`.
- `agents/changelog-analyst.md:128`, `:131`, `:185`: references to `scripts/resolve-dev-artifact-chain.py`, `scripts/verify-attribution-chain.py`, `scripts/late-repair-controller.py`.
- `agents/changelog-analyst.md:399`, `:651`, `:669`, `:729`: `${CLAUDE_PROJECT_DIR}/.claude/scripts/{resolve-dev-report.py,session-index.py,stage-owned-hunks.py}`. This expands to `/.claude/scripts/...` (CLAUDE_PROJECT_DIR is unset) or `<product>/.claude/scripts/...` (never exists). At :651 the `eval "$(...)" || {exit 1}` guard does not fire (P5), so the private index is silently off and staging falls into the shared index.

**Fix** (one pattern for every prose site): qualify as `~/.claude/scripts/<name>` and `source ~/.claude/venv/bin/activate`. That is the form already used by the majority of sites (close.md:815, dev.md:244, dev-overnight.md:955). The four changelog-analyst `${CLAUDE_PROJECT_DIR}/.claude/scripts/` sites change the same way. Code sites use `Path(__file__).resolve().parent.parent`.

### B1.g Prose depends on $CLAUDE_PROJECT_DIR, which the Bash tool does not export
- Measured UNSET in this session (ENV row). The harness records the same at `commands/dev-overnight.md:210-211`.
- 84 uses without a `:-` fallback across commands/close.md (12), codex.md (5), commit.md (1), dev-command.md (13), dev-overnight.md (17), dev.md (28), spec-update.md (1), spec.md (6), tickets.md (1), agents/changelog-analyst.md (4), graphify.md (1), qa.md (2), spec.md (1).
- Hard failures:
  - `scripts/write-qa-mode.sh:35` `${CLAUDE_PROJECT_DIR:?}` exits 1 when called from an orchestrator Bash (P3). dev-overnight.md:1077-1085 works around this with an explicit prefix; close.md:246 does not.
  - `scripts/break-overnight-lock.py:30` `CLAUDE_DIR = claude_home.project_dir()/".claude"` falls back to the harness home (hooks/lib/claude_home.py:171-184), so in a product repo the human /stop finds no overnight state (PLAUSIBLE: hooks/stop.sh:20-30 does not set the variable).
  - `commands/dev.md:209-210`: `mkdir -p "$CLAUDE_PROJECT_DIR/docs/dev"` becomes `/docs/dev` (hook-absent fallback).
  - `commands/close.md:508`, `commands/dev.md:160`, `commands/dev-command.md:104`, `commands/spec.md:163, :428`: `--project-dir ""`.
  - The FIRST ACTION registration Read lines are never substituted. `dev.md:304, :434, :503, :628, :736, :790, :821, :865, :1016`; `dev-command.md:239, :329, :391, :457, :553, :604, :662`; `dev-overnight.md:27, :487, :643, :743, :974, :1092, :1194, :1255, :1286, :1387, :1596`; `close.md:553-555, :559-561, :602-603`; `agents/graphify.md:22`. When a registration Read misses, the role is unresolved and role enforcement fails open (feeds A4).
- **Fix** (producer-side, no new file): `hooks/prompt-workflow.py` already resolves PROJECT_DIR (:62-97) and the harness home. At UserPromptSubmit it prints both as literal values (`PROJECT_ROOT=<abs>` and `HARNESS_ROOT=<abs>`) into the injected context. Prose uses `${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}`, as close.md:335 and update-overnight-state.sh:27 already do. write-qa-mode.sh:35 gets the same fallback.

---

## B2: /dev-overnight cannot run, close or land honestly

### B2.a The per-cycle commit never commits, and the prose claims it does
- `scripts/commit.sh:37-49`: a dirty tree always gives exit 3 "cannot self-authorize a real HEAD commit". This is deliberate (:22-33) and agrees with the architecture (`docs/reference/close-commit-zero-failure-mechanism-20260928.md:373-384`, §1.5.5: a non-committing stub, work preserved in refs/checkpoints/*, landing via the human /commit (--bulk)).
- `commands/dev-overnight.md:124` (Rule 8): claims Step 19 "lands a real HEAD commit ... that HEAD commit IS merge-ready and is the only artifact /merge consumes". This is false.
- `commands/dev-overnight.md:1576-1578`: Step 19 calls `scripts/commit.sh` with a repo-relative path. It exits 127 in product repos and 3 in the harness repo, and is "log and continue".
- `commands/dev-overnight.md:1721`: "under in_place it leaves the cycle commits on the working branch". No such commits exist.
- `commands/dev-overnight.md:1781`: "the cycle commits are already on <worktree_branch>". False.
- `commands/dev-overnight.md:1798`: "after the final cycle's end-of-cycle commit". False.
- Evidence: ADV-ON step 7 (rc=3, empty worktree branch; junk reached the branch only through the `bash -c "git commit"` bypass).
- **Fix** (prose): delete the Step 19 "Per-cycle commit" paragraph (:1576-1578) and the HEAD-commit sentences of Rule 8 (:124). Replace them with: "work is preserved in refs/checkpoints/<branch>; it lands after the session through the post-loop flow (B2.g)". `scripts/commit.sh` becomes unreferenced (hold; no retirement).

### B2.b The closeout fields have no producer, so an honest session (or the human /stop) can never end
- `hooks/stop-overnight-timelock.py:138-150` `_closeout_artifact_blockers`: requires
  - `final_summary_path`|`summary_path` to exist (:142)
  - `pm_retro_reports` to be non-empty (:144-146)
  - `artifact_checkpoint_status` ∈ {checkpointed, intentionally_uncommitted} (:147-149)
  - an empty `unresolved_issues`/`current_issues` (:140-141)
- `hooks/stop-overnight-timelock.py:251-254`: once end_time has passed, any blocker gives exit 2. Combined with :270-278 (stop_hook_active is honoured only when end_time is None), Stop stays blocked forever.
- Writers (grep over hooks/scripts/commands/agents): `scripts/create-overnight-state.sh:812` (`pm_retro_reports: []`), `:781`/`:813` (current_issues/unresolved_issues `[]`), `hooks/posttool-overnight-loop.py:122-126` (resets/setdefault). **Nothing** writes final_summary_path, artifact_checkpoint_status, or any pm_retro_reports entry.
- The real artifacts exist but are never linked:
  - `commands/dev-overnight.md:1638` (Step 20): the retro goes to `docs/dev/overnight/<sid>/retro-report-cycle<N>.json` in the working root.
  - `commands/dev-overnight.md:1672-1720` (Step 21): the summary goes to `docs/dev/overnight-summary-<date>.md`.
- The human /stop ends up in the same block: `hooks/stop.sh:24-30` runs `scripts/break-overnight-lock.py:77-101`, which only backdates end_time (:80-81), so the closeout gate fires (RV do/overnight critical #2).
- The vacuous part: current_issues/unresolved_issues have no per-cycle writer (Step 6 writes `docs/dev/overnight/<sid>/pipelines.json`, dev-overnight.md:902), so the backlog check never binds.
- Evidence: T2-tz (Shanghai) shows the block; RV:83-85; ADV-ON steps 12-13 (satisfiable only by forging through update-overnight-state.sh).
- **Fix** (the gate becomes its own producer by recomputing from disk; zero new files):
  1. In `_closeout_artifact_blockers`, derive `retro_status` from the existence of `<working_root>/docs/dev/overnight/<sid>/retro-report-cycle*.json`, and `final_summary` from `<working_root>/docs/dev/overnight-summary-*.md` with mtime ≥ state.start_time. Derive `artifact_checkpoint_status` from git: the working tree is clean, or `refs/checkpoints/<worktree_branch>`^{tree} equals the current snapshot. Here working_root = state.worktree_path. Delete the reads of the three state fields.
  2. Drop the `unresolved_backlog` blocker. Unresolved issues are an honest outcome and are recorded in the retro/summary (Hook Discipline #5).
  3. `break-overnight-lock.py` already validates a human /stop helper-auth token (:37-75). When the token is valid it also sets `terminal_status="cancelled_by_user"`, so /stop is an honest terminal through the existing branch at timelock.py:240-243.

### B2.c The agent can release the time-lock in one step
- `hooks/stop-overnight-timelock.py:240-243`: `terminal_status|status ∈ {cancelled_by_user, user_cancelled, cancelled}` gives exit 0.
- `scripts/update-overnight-state.sh:75-81` IMMUTABLE_FIELDS omits `status`, `terminal_status`, `end_time`, `start_time` and the closeout fields, so `--set status cancelled` is allowed (the overnight guard whitelists this script).
- Evidence: T2-cancel rc=0; RV:30, :83-85; RV do/overnight critical #4.
- **Fix**: add those keys to IMMUTABLE_FIELDS. Only the token-gated break-overnight-lock.py (B2.b.3) may set terminal_status.

### B2.d The time-lock depends on the timezone
- `hooks/stop-overnight-timelock.py:72-87` `parse_end_time`: strips tzinfo and compares naive local time (`:245`, `:257`, `:194` use `datetime.now()`).
- `scripts/create-overnight-state.sh:142-219`: always writes UTC `...Z`.
- Correct siblings: `hooks/posttool-overnight-loop.py:80-97` and `hooks/lib/overnight.py:31-42`.
- Evidence: T2-tz. In UTC+8 a 1h session is expired at launch, so there is no time-lock and the closeout deadlock starts at the first Stop. In UTC-7 a 1h session locks for about 8h.
- **Fix**: parse `Z` as `+00:00` and compare in UTC (reuse `lib/overnight._end_time_passed`).

### B2.e The cycle contract deadlocks Step 2; it has no code republisher and no shared cycle index
- `scripts/create-overnight-state.sh:1026-1056` (`required_calls: []` at :1051; contract path :711): publishes `docs/dev/overnight/<sid>/cycle-1/cycle-contract.json` with **`required_calls: []`** at launch.
- `hooks/pretool-subagent-enforce.py:329-339`: any contract present means enforce (HARD CUTOVER). `:211-237` (Case C) plus `:291-300` give exit 2 for the Step-2 PM PLAN dispatch (T2-ct).
- `commands/dev-overnight.md:808-839`: says the orchestrator writes the contract after Step 4 and that "until it exists hooks pass through". This contradicts the launcher.
- `commands/dev-overnight.md:841`: the contract is append-only and re-plans go to `cycle-contract.v2.json`, but `hooks/lib/contract_runtime.py:79-125` reads only `cycle-contract.json` (v2 is ignored).
- The overnight write boundary blocks main-tree writes by the actor and subagents (RV do/overnight critical #1), so no agent can republish. Each dispatch needs a human `/allow Agent`.
- `hooks/lib/contract_runtime.py:101-107`: a malformed contract returns None, which `pretool-subagent-enforce.py:330-332` treats as passthrough (T2-ct2 rc=0).
- Cycle index disagreement:
  - `hooks/pretool-subagent-enforce.py:86-99` and `hooks/posttool-overnight-file-check.py:109-114` use the bookmark `cycle_id||cycle_count`, default 1.
  - `hooks/stop-overnight-timelock.py:100-120` uses state `cycle_count`, which is 0 in cycle 1, so the closeout probe reads cycle-0 and finds `no_contract`.
  - `hooks/posttool-overnight-loop.py:120` increments only `cycle_count`.
  - Nothing writes cycle-N≥2 contracts.
  - `hooks/lib/closeout.py:45-55`.
- The pending-required-calls branch is dead: `stop-overnight-timelock.py:248-250` consults it only before end_time, when the lock blocks anyway (RV do/overnight medium).
- **Fix** (the contract producer becomes code):
  1. The launcher seeds `required_calls` for steps `2` (pm, PLAN), `3-<specialist>`, `4` (pm, TRIAGE).
  2. A hook-side republisher renders steps 8/10/11g/12/15/20 into the SAME `cycle-contract.json` from the output of `scripts/build-pipelines-from-triage.py`. It runs in the PostToolUse/SubagentStop hook that observes the completed PM TRIAGE dispatch (posttool-subagent-track.py). Hook writes are not subject to the actor's write boundary. On loop reset (posttool-overnight-loop.py:114-138) it renders the cycle-(N+1) seed.
  3. One cycle-index helper (`cycle_count + 1`), used by subagent-enforce, file-check, closeout and timelock.
  4. A malformed contract is a Case M block, not passthrough.
  5. Delete the "orchestrator writes the contract" prose (dev-overnight.md:806-841).

### B2.f The loop-reset recompute (G4 overnight anchor) is vacuous, advisory, and reads the wrong root
- `hooks/posttool-overnight-loop.py:268-293` (switch read at :275): `CLAUDE_OBLIGATION_TERMINAL` defaults to advisory (no settings.json env entry; arming is A1).
- `hooks/posttool-overnight-loop.py:186-197` condition (b) iterates `state.current_issues`, which has no writer (B2.b), so it always passes.
- `hooks/posttool-overnight-loop.py:156-171` `_lane_dev_status` reads `<CLAUDE_PROJECT_DIR>/docs/dev/dev-report-<suffix>.json` (main root), while worktree producers write under the worktree (dev-overnight.md:1607 "Project path: <worktree_path>").
- **Fix**: take the roster from the cycle contract's step-12 `required_calls` (B2.e) or `pipelines.json`, resolved against `state.worktree_path`. Later, swap in the S8 disposition. Switch arming lives in A1.

### B2.g The dev-overnight post-loop flow contradicts the user's contract (/close only after the whole session ends)
- `commands/dev-overnight.md:1721-1790`: the completion announcement (no /close; /commit "optional").
- `commands/dev-overnight.md:1792-1816`: the post-loop manual flow is `/commit` (optional), then `/merge`, then `/push`. No /close step.
- `commands/close.md`: no overnight handling (the only mention is :436). `/close --auto` (close.md:933-952) is the existing batch path over close_pending parents, but its discovery is broken in product repos (B1.f close.md:950).
- Evidence: ADV-ON holes #4 (overnight output reached merge/push with no /close in the code path).
- **Fix** (prose only; the producer chain is unchanged): after the session ends, in the working root, run `/close --auto`, then `/commit --bulk` (architecture §1.5.5; no longer "optional"; it is the landing path), then `/merge`, then `/push`. Update the announcement text (:1765-1790) to match. Depends on B1.f (close.md:950) and B2.a.

### B2.h Worktree vs main-root resolution
- State lookup only at `<CLAUDE_PROJECT_DIR>/.claude`, with no walk-up and no git-common-dir:
  - `hooks/stop-overnight-timelock.py:61-69, :274, :281`
  - `hooks/posttool-overnight-loop.py:62-77`
  - `hooks/posttool-overnight-file-check.py:66-79`
- Artifacts resolved against the main tree, where worktree producers cannot write: `hooks/posttool-overnight-file-check.py:117-119` (RV do/overnight high #8).
- `hooks/lib/closeout.py:45-55`: the cycle dir comes from claude_home.project_dir().
- `hooks/lib/overnight.py:63-92` `candidate_project_dirs`: `git rev-parse --show-toplevel` returns the worktree, not the main root.
- Evidence: T2-wt (rc=0, lock off). The real-world trigger is a session whose CC project dir is the worktree (see corrections).
- **Fix**: one locator in `hooks/lib/overnight.py`: main root = parent of `git rev-parse --path-format=absolute --git-common-dir`. Use it for state in all four hooks, and resolve artifacts against `state.worktree_path`.

### B2.i Launch and host prerequisites (low; doctor checks belong to C2)
- `hooks/prompt-workflow.py` launch refuses a repo whose `origin/HEAD` is unset, and refuses in_place on the protected branch (RV boot low; RV do/overnight medium #11).
- With no bwrap, non-worktree writes fail closed, including the human /stop path (`hooks/pretool-overnight-hook-guard.py:1842-1890`; README.md:459, :479). bootstrap/doctor do not check for bwrap.

---

## B3: the Stop coordinator hides block reasons; per-turn state resets only on a successful Stop

### B3.a Reason hashing
- `hooks/stop-workflow-coordinator.py:160-177` `_run_phase`: phase stdout/stderr are reduced to `stdout_sha256`/`stderr_sha256`.
- `hooks/stop-workflow-coordinator.py:262-277`: the first non-allow phase returns `{status: blocked, failed_phase}` with exit 2.
- `hooks/stop-workflow-coordinator.py:328-338` `main`: prints JSON to stdout and returns 2. stderr is empty. Claude Code feeds back only stderr on exit 2, so the agent and user get an empty reason. This covers the timelock "Continue working", closeout `missing=...`, coverage gaps, and auto_commit errors.
- Registered at `settings.json:819`. The template registers phases directly (`settings.template.json:764`, `:776`), so the defect is live-config only (C2 drift).
- Evidence: T3b (stderr 0 bytes); RV:33, :80-82.
- **Fix**: when a phase blocks or fails, write `failed_phase` plus that phase's decoded stderr (bounded, for example the last 4 KB) to sys.stderr before exit 2. Keep fixed codes only for the resource-broker branches (:253-260, :296-303), where diagnostics are trust material (that is the rationale of the comment at :157-158).

### B3.b Best-effort phases block Stop
- `hooks/stop-workflow-coordinator.py:162-166`: any rc other than 0 or 2 becomes `fail`, and `:270-277` blocks on it, including `auto_commit` (`hooks/auto-commit.sh`) and `cleanup`.
- `hooks/lib/checkpoint-core.sh:519` (and `:529`, `:537`): `2>>"$CHECKPOINT_LOG_FILE"` into a log dir that may not exist on a fresh install (T3d). Commit-tree fails without a git identity (T3e), so **every** Stop is blocked on such machines, with the reason hidden (B3.a).
- **Fix**: only `timelock` and `coverage` may block. Log auto_commit/cleanup failures and allow (phase order unchanged). Add `mkdir -p "$CHECKPOINT_LOG_DIR"` before the read-tree block (checkpoint-core.sh:519).

### B3.c The orchestrator per-turn counters reset only on a successful Stop
- Counter: `hooks/pretool-orchestrator-gate.py:84-86` (state file), `:125-159` (update), `:180-186` (limits), `:285-286`.
- The only reset: `hooks/stop-cleanup-allowlist.sh:40`. It runs as the coordinator's LAST phase (`hooks/stop-workflow-coordinator.py:40`, `:63-69`), and the coordinator returns early when any earlier phase blocks (`:270-277`). Stop does not fire on a user interrupt.
- Evidence: T3c (after a blocked Stop the next turn's first Edit is blocked `(2/1)`); RV:274; RV close low #3; RV commit medium #7.
- **Fix**: reset at the real turn boundary. `hooks/prompt-workflow.py` `main` (:2001) unlinks `<state_dir>/claude-tool-streak-<sid>.json` on every UserPromptSubmit. Drop the cleanup-phase line (stop-cleanup-allowlist.sh:40) or keep it as a no-op.

### B3.d The same defect for the /do consent flag
- Written: `hooks/prompt-workflow.py:1402-1415`.
- Cleared only by `hooks/stop-cleanup-allowlist.sh:32-39`, or by `hooks/stop-do-report-gate.py:131-147` (on compliance :226-232 or at the bound :245).
- After a blocked or interrupted /do turn the flag survives. In later turns `hooks/pretool-do-block-subagents.py:87-95, :155` blocks every Agent dispatch (so a following /dev cannot dispatch), and the orchestrator gate stays bypassed (`pretool-orchestrator-gate.py:258-259`). See also docs/reference/close-commit-failure-inventory-20260927.md:601 (#262).
- **Fix**: the same UPS hook expires a previous turn's consent flag when the new prompt is not `/do`. Scope is documented as single-turn at stop-cleanup-allowlist.sh:32-34.
- **User decision**: CLAUDE.md:60 says "/do this session" while stop-cleanup-allowlist.sh:32-34 says single-turn. Pick one; the fix follows it.

### B3.e Documentation contradictions tied to B3
- `CLAUDE.md:102` (Sentinel-grant section, last sentence) and `ARCHITECTURE.md:166` say `stop-cleanup-allowlist.sh` is not registered and never runs. It runs as coordinator phase 4 (`stop-workflow-coordinator.py:68`).

---

## B4: the /do Stop gate force-allows instead of finalising its own skeleton

- `hooks/stop-do-report-gate.py:57` `MAX_BLOCKS = 2`. `:239-256`: at the bound it **force-allows**.
- `hooks/stop-do-report-gate.py:172-189` `_rewrite_pending_to_blocked`: finalises only when `do.status == "pending"`. Results:
  - Absent report: no finalisation and no terminal artifact (T4a).
  - Unparseable report: same.
  - `completed` with an empty summary or wrong identity/source: stays a false `completed` (T4b).
- `hooks/stop-do-report-gate.py:150-169`: the counter lives at `harness_state_dir()` (/tmp) and is agent-writable. A forged counter finalises at the first Stop (T4c).
- Fail-open paths: missing/unsafe sidecar (:210-218), any exception (:274-282), schema-infra skip (:116-123).
- Documentation contradictions: the header says the gate "never writes the report itself" (:31-33) while :172-189 writes it. `commands/do.md:53` says advisory is the default; the code default is block (:12, :193).
- Architecture: §1.3 G4 table, /do row (`docs/reference/close-commit-zero-failure-mechanism-20260928.md:284`): the force-allow is to be replaced by hook-side finalisation of the gate's OWN skeleton to `do.status="blocked"` plus an explanatory summary. The last-resort force-allow plus advisory is kept only for an unwritable docs/dev.
- **Fix**: at the bound, for every non-compliant state:
  - absent, unparseable, or identity/source mismatch: re-mint the skeleton (`hooks/prompt-workflow.py:1365` `_write_do_report_skeleton`, or the same shape inline);
  - non-terminal or shape-invalid: set `do.status="blocked"` and `do.summary="do-report gate finalised: <problems>"`, keeping the agent-written fields.

  Then exit 0. This is an honest class-a terminal, consumed by /close as CLOSE: NO. Force-allow plus advisory stays only for a failed write. Optional: derive the bound from `stop_hook_active` plus transcript block events instead of the /tmp counter (removes a mutable state file). Fix the docstring and do.md:53.

---

## Dependency and order (minimal)

1. B1.a, B1.c, B1.d (completion gate path, task-id, escalation dir), then B1.b (widen the trigger).
2. B3.a, B3.b (coordinator relays reasons; best-effort phases do not block). Independent, small.
3. B3.c, B3.d (UPS-time per-turn reset). Independent, small. B3.d needs the user's decision on /do scope.
4. B4 (do gate finalisation). Independent.
5. B2.d (TZ), B2.c (immutable fields), B2.b (closeout recompute + /stop terminal). B2.b needs B2.h's locator for working_root.
6. B2.e (contract producer + cycle index), then B2.f (loop-reset roster).
7. B1.f/B1.g (path qualification + UPS literal injection), then B2.a/B2.g (overnight prose: no per-cycle commit; post-session /close --auto then /commit --bulk then /merge then /push).
