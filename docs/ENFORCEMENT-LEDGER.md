# Enforcement Ledger — claude-code-guardrails

> **What this document is for.** The harness makes "fail closed" claims. This ledger turns that
> adjective into a **state**: every wired hook gets a row, every row carries a behavior label
> drawn from a closed set, and every label carries the *proof layer* that earned it.
>
> Companion documents: `docs/THREAT-MODEL.md` (what is defended and against whom),
> `docs/ADVERSARIAL-CORPUS.md` (the payloads), `hooks/tests/fixtures/adversarial_corpus.json`
> (the machine-readable source of truth for those payloads).

## What the gate behind this ledger does and does not establish

The registered-hook table has **ten** columns. Stating which of them a check recomputes — rather
than leaving the reader to assume all of them — is the whole point of publishing it.

**Three columns are derived.** <!-- published-columns:derived:begin -->`event_class`, `matcher`
and `hook`<!-- published-columns:derived:end --> are recomputed from
the checked-out `settings.json` (the row set was last reconciled against `@4ffb9279`) by
`scripts/check-enforcement-evidence.py --claims`, which
compares the derived triple set against the published rows and fails on **either** symmetric
difference. That check runs inside the already required `baseline` CI job via
`scripts/verify-claims.sh`, which hands it the index copy of `settings.json` (the tracked form).

**The other seven columns are authored in this document.** They are
<!-- published-columns:authored:begin -->`row_id`,
`mode/precondition`, `behavior`, `exercise_status`, `proof_layer`, `citation` and
`verifying_test`<!-- published-columns:authored:end -->. They are not derived from anything;
they receive the following validation and
no more:

- all seven are checked **non-blank** — a blank cell is a failure, not a statement that a value
  is absent;
- `behavior`, `exercise_status` and `proof_layer` are additionally validated against the closed
  sets declared in `DECLARED_SCHEMA`;
- `citation` is validated for the presence of an `@<sha8>` revision pin.

**On falsifiability.** 50 of the 53 registered-hook rows carry `proof_layer: source-level`, which
as section 1.3 defines it means those rows rest on **reading the code rather than running it**;
the remaining 3 carry `component-tested` and none carry `host-observed` or `host-shaped`. The gate validates
proof-layer membership and a non-blank `verifying_test`, and it does **not** execute the
verifying test or establish one-command falsifiability for any row. No row's falsifier has been
run by any check in this repository.

---

## 1. Vocabulary (the closed sets)

The three label axes below — and the accepted `status:` value of each residual-risk entry of
`docs/THREAT-MODEL.md` — are **declared exactly once**, in `DECLARED_SCHEMA` in
`scripts/check-enforcement-evidence.py`. The block that follows is parsed on every run and
asserted **equal as JSON** to that declaration — the decoded value is compared, not the bytes,
so key order and formatting may differ — and its `begin`/`end` markers must both be present.
The document therefore cannot drift from the code that enforces it in any way that changes a
declared value.

<!-- enforcement-schema:begin -->
```json
{
  "behavior": [
    "enforced",
    "detected",
    "advisory",
    "unsupported"
  ],
  "exercise_status": [
    "exercised",
    "unexercised"
  ],
  "proof_layer": [
    "host-observed",
    "host-shaped",
    "component-tested",
    "source-level",
    "none"
  ],
  "risk_status": {
    "RISK-1": [
      "PARTIALLY MITIGATED"
    ],
    "RISK-2": [
      "MITIGATED"
    ],
    "RISK-3": [
      "PARTIALLY MITIGATED"
    ]
  }
}
```
<!-- enforcement-schema:end -->

### 1.1 `behavior` — how the mechanism acts

| label | operational definition |
|---|---|
| `enforced` | **The host actually prevented the pending action**, observed on a real Claude Code dispatcher. Requires `proof_layer: host-observed`. Nothing less earns this label. |
| `detected` | Recorded or logged **without** prevention. |
| `advisory` | Guidance emitted with **no prevention guarantee**. A deny-capable hook whose prevention has not been observed on a host belongs here, not under `enforced`. |
| `unsupported` | Outside this project's currently-tested contract. |

These are exactly the four labels the requirement names. Two things that look like behaviors are
deliberately **not** on this axis:

- **`component-tested` is a proof layer, not a behavior.** It means the hook script itself exits
  2 or emits a deny when driven directly or through a synthetic lifecycle payload. It proves the
  *script's* behavior. It does **not** prove the dispatcher routed to it, nor that the host
  honored the exit code. Filing subprocess evidence under `enforced` is precisely the
  adjective-for-state substitution this ledger exists to prevent.
- **`unexercised` is an exercise state, not a behavior.** Whether the corpus *reaches* a hook is
  orthogonal to how that hook *behaves*.

### 1.2 `exercise_status` — whether this cycle's corpus reached it

`exercised` = at least one corpus case drives this row in the black-box suite.
`unexercised` = no corpus case reaches it; the row is published anyway, because an event class
that silently has no row is indistinguishable from one that passed.

### 1.3 `proof_layer` — what evidence earned the label

| layer | meaning |
|---|---|
| `host-observed` | A real Claude Code dispatcher was driven and the action was prevented. **Zero rows in this repository currently qualify.** |
| `host-shaped` | A synthetic lifecycle payload was fed to the hook on stdin and the process exit code was read. |
| `component-tested` | The hook script was invoked at the subprocess boundary and its real exit code / stderr asserted. |
| `source-level` | The claim rests on reading the code, not on running it. |
| `none` | No evidence layer applies. |

### 1.4 `mode/precondition`

Mandatory, never blank. A conditional mechanism must be able to state its condition; a table
with no place to say "advisory by default, blocking only under this environment variable" would
publish one of a hook's two behaviors as though it were the whole truth. Where there is
genuinely no precondition the explicit sentinel `none` is required — **a blank cell is a
failure, not a statement that a value is absent.** Since P12 no registered-hook row uses the
sentinel: every cell opens with the hook's mode (`block`, `advisory` or `off`) and its switch
(section 3 says how to read them).

---

## 2. The hard consequence, stated up front

**No row in this ledger carries `enforced`, and that is the correct output of this cycle.**

No real-Claude-Code-dispatcher harness exists in this environment, so no host-observed
prevention can be demonstrated, so nothing qualifies for the one label that means "the host
stopped it." The strongest truthful label available here is a `component-tested` proof layer
behind an `advisory` behavior. An empty `enforced` column is what turns "fail closed" from an
adjective into a state with a measurable — and currently unmet — bar.

`scripts/check-enforcement-evidence.py --ledger` enforces this mechanically: a row labelled
`enforced` whose `proof_layer` is anything other than `host-observed`, or which has no linked
corpus case, exits non-zero.

**R3** (black-box integration tests against real supported Claude Code builds) status:
incomplete — not satisfiable in this environment. Adding the disclosure row below **discloses**
that gap; it does not close it. What *is* delivered — the exact current-environment
compatibility row, the component-tested rows, and an explicit `unexercised` row for every hook
the corpus does not reach — is delivered in full. What is not delivered is not relabelled.

### 2.1 Counting definition for "Bash hook"

Two counts of "the Bash PreToolUse hooks" are in circulation and they use different definitions.
**This ledger uses the settings-derived definition**: a row exists for every
`(event class, matcher, hook)` triple in `settings.json`, and the matcher string is reproduced
verbatim. Under that definition `settings.json @4ffb9279` dispatches **14** PreToolUse hook
commands for `tool=Bash` — 7 from matchers naming `Bash` explicitly and 7 from universal
matchers (`*` or none); at `@4c33f2f5` the same count was 16 (10 and 6). A sibling lane reports "all 11 Bash PreToolUse hooks" under a
narrower definition. Neither count is adopted silently; the definition is stated so the two can
be reconciled rather than argued.

---

## 3. Registered-hook rows

The tracked `settings.json` wires 9 event classes / 38 matcher groups / **53 hook commands** over
52 hook files (`posttool-allowlist-consume.py` is registered twice, on `PostToolUse` and
`PostToolUseFailure`), and the table below has exactly 53 rows. Of the ten lifecycle event classes,
`Notification` alone has no registration since P12 (its one hook was an exit-0 stub), so it has no
row; this sentence records that its absence is deliberate.

**Reading the `mode/precondition` cell.** Each cell opens with the hook's real mode, read from its
exit paths at the cited revision, then its switch:

- `block` — some input makes the hook exit 2 (or deny) on its own registration, and that refuses
  the pending action (a tool call, a prompt, a stop);
- `advisory` — no input makes it refuse the pending action: it records, informs the model or the
  user, or runs after the fact (a `SessionStart`, `PostToolUse` or `SessionEnd` hook cannot refuse
  what already happened);
- `off` — it does nothing unless its switch is set, and the shipped `settings.json` does not set it.

`switch: none` means no environment variable changes the mode; the exemptions the cell names
(a subagent context, `/do` consent, an `/allow` grant, a live `/dev-overnight` session, a sentinel
file) are conditions of the rule, not switches. A rule a merged gate runs keeps its own decision
and switch; it has a row in section 3.1, and the gate's row here says what the gate adds.

**Rows of hooks that are no longer registered are removed, and their ids are retired, not
reused.** P12 merged parallel hooks into four gates (H-089 – H-092) and left the merged files as
the rules those gates run, so their decisions now have section 3.1 rows: H-017, H-021, H-023,
H-025, H-026, H-075 and H-076 (dispatch gate), H-045 – H-047 (dispatch record), H-067 – H-070 and H-086
(producer gate), and H-020, H-028, H-034, H-040 and H-041 (write gate). Ten retired rows are
exit-0 `# STUB:` files kept at their paths so a session that loaded an older hook list does not
wedge: H-038 `pretool-write-guard.sh` (its checks are rule R-005), H-042
`pretool-subagent-code-block.py` (R-003 refuses every non-dev role's code write), H-022, H-024,
H-064, H-065 and H-066 (the five dev-loop shells; R-016 and R-021 give their advice), and H-059
`notification-idle-overnight.py`, H-072 `posttool-push-gate-token-verify.py` and H-077
`pretool-push-analyst-grant-guard.py`, already stubs before P12. `posttool-git-warn.sh` keeps
H-048 with its matcher moved from `Bash\(git commit.*\)`, which matched no tool name, to `Bash`.
Ids retired earlier stay retired: H-052, H-053, H-060 – H-063, H-081 and H-082 – H-084 (the
`Stop` phases are section 4's S-005 – S-008, run by `stop-launch.py`, H-088).

**The authoring rule `behavior` follows** — applied by hand, and checked only for closed-set
membership, not recomputed from the event class: events that can deny a pending action
— `PreToolUse`, `UserPromptSubmit`, `Stop`, `SubagentStop` — are `advisory`, because they are
deny-*capable* but their prevention has not been observed on a host. Events that fire after the
fact or carry no veto — `PostToolUse`, `PostToolUseFailure`, `SessionStart`, `SessionEnd`,
`Notification` — are `detected`. The `behavior` label is a proof label; the mode is in
`mode/precondition`.

| row_id | event_class | matcher | hook | mode/precondition | behavior | exercise_status | proof_layer | citation | verifying_test |
|---|---|---|---|---|---|---|---|---|---|
| H-001 | SessionStart | (universal) | canary-verify.sh | advisory; switch: none. It never blocks (a SessionStart exit 2 only shows stderr to the user): it drives pretool-bash-safety.sh, the write gate's overwrite rule (H-089, R-005), pretool-read-size-guard.py and pretool-git-privilege-guard.py with one benign and one refused payload each, compares deployed cleanup artifacts with their repository copies, and exits 2 naming each failure; a healthy run prints nothing and exits 0 | detected | unexercised | source-level | scripts/canary-verify.sh:1 @4ffb9279 | none yet |
| H-002 | SessionStart | (universal) | check-todo-md-sync.py | advisory; switch: none. It never blocks and exits 0 on every path: prints, into the model's context, each Step-token drift between a harness `scripts/todo/<cmd>.py` and its `commands/<cmd>.md` (missing, extra, duplicated or reordered tokens); silent when they agree | detected | unexercised | source-level | hooks/check-todo-md-sync.py:1 @4ffb9279 | tests/test_todo_md_sync.py |
| H-003 | SessionStart | (universal) | session-git-init.sh | off when CLAUDE_SESSION_GIT_INIT is unset (the default); the shipped settings.json does not set it. With it truthy (1, true, yes) it creates a git repository in a project that has none, offers or (CLAUDE_AUTO_CREATE_REPO true) creates the GitHub repository, and tells the model on its stdout; it never blocks | detected | unexercised | source-level | hooks/session-git-init.sh:1 @4ffb9279 | hooks/tests/test_hook_output_reaches_model.py |
| H-004 | SessionStart | (universal) | session-gitignore-propagate.sh | advisory; switch: none. It never blocks and exits 0 on every path: appends each harness runtime directory under `.claude/` that the clone's own `info/exclude` does not list yet; writes no tracked file; a project that is not a git repository is left alone | detected | unexercised | source-level | hooks/session-gitignore-propagate.sh:1 @4ffb9279 | hooks/tests/test_session_gitignore_propagate.py |
| H-005 | SessionStart | (universal) | session-info.sh | advisory; switch: none. It never blocks: prints the session's directory, git branch and dirty count and project metadata on stdout, which a SessionStart hook adds to the model's context | detected | unexercised | source-level | hooks/session-info.sh:1 @4ffb9279 | hooks/tests/test_hook_output_reaches_model.py |
| H-006 | SessionStart | (universal) | session-promote-hook.sh | off when SESSION_PROMOTE_BIN is unset (the default); the shipped settings.json does not set it. With it naming an executable, a session whose transcript is a symlink under the harness home's `projects/` runs that helper in the background to promote it back to RAM; exits 0 on every path | detected | unexercised | source-level | hooks/session-promote-hook.sh:1 @4ffb9279 | none yet |
| H-007 | SessionStart | (universal) | session-tmpfs-banner.sh | advisory; switch: none. It never blocks and exits 0 on every path: prints one `WARN tmpfs over 75%` line on stdout (the model's context) for each of /tmp and /dev/shm whose use exceeds 75%, nothing otherwise | detected | unexercised | source-level | hooks/session-tmpfs-banner.sh:1 @4ffb9279 | hooks/tests/test_hook_output_reaches_model.py |
| H-008 | UserPromptSubmit | (universal) | prompt-workflow.py | block; switch: none (CLAUDE_COMPAT_RUNTIME=codex, set only by the Codex wrapper, makes it exit 0 at once). It exits 2, which refuses the prompt, when a /dev-overnight launch cannot write its overnight state record (OVERNIGHT LAUNCH ABORTED) and when a command's `--spec` names no readable file; otherwise, for a harness command, it prints the roots, the checklist and the first TodoWrite call into the context, mints the /dev task id and arms its registry, and starts the workflow bookmark `.claude/workflow-<sid>.json`, of which it is the one writer (lib/todo_canonical.write_bookmark); on a plain prompt it injects the open overnight window's continuation and the checklist's next call; any other error exits 0 | advisory | unexercised | source-level | hooks/prompt-workflow.py:1 @4ffb9279 | hooks/tests/test_cycle_registry.py, hooks/tests/test_workflow_bookmark_writer.py |
| H-009 | UserPromptSubmit | (universal) | userprompt-bulk-commit-capability.py | advisory; switch: none. It never blocks and exits 0 on every path: a human-typed `/commit` with a `--bulk` flag mints the bulk-commit sentinel through scripts/write-bulk-commit-sentinel.py (origin `userpromptsubmit-hook`); any other prompt is a no-op | advisory | unexercised | source-level | hooks/userprompt-bulk-commit-capability.py:1 @4ffb9279 | hooks/tests/test_userprompt_bulk_commit_capability.py |
| H-010 | UserPromptSubmit | (universal) | userprompt-consent-allowlist.sh | advisory; switch: none. It never blocks and exits 0 on every path: a human-typed `/allow [<selector>]` (no agent_id) writes the one /allow grant file `<state dir>/claude-grants/<task_id>.json` through lib/allowlist.py write_sentinel_grant (single use, TTL 300 s); no argument writes a match-all grant; an explicit selector it cannot narrow writes nothing, removes a stale grant and prints a usage error | advisory | unexercised | source-level | hooks/userprompt-consent-allowlist.sh:1 @4ffb9279 | hooks/tests/test_allowlist_consolidation.py, hooks/tests/test_allowlist_git_global_opts.py |
| H-011 | UserPromptSubmit | (universal) | userprompt-doc-sync-check.py | advisory; switch: none (CLAUDE_DOC_SYNC_ROOTS names the watched roots). It never blocks and exits 0 on every path: at most every 300 s it re-runs posttool-doc-sync.py for watched directories that lost a file and removes the INDEX.md of one left empty; resynced lines reach the model as additionalContext and its notices the user as systemMessage | advisory | unexercised | source-level | hooks/userprompt-doc-sync-check.py:1 @4ffb9279 | hooks/tests/test_doc_sync_index_notices.py |
| H-012 | UserPromptSubmit | (universal) | userprompt-restart-authorize.py | block; switch: none. A prompt that starts with `/restart`, or the /dev-overnight session's own wake prompt while its span is the active one (lib/overnight.wake_fired), mints the session-bound /restart capability (lib/subagent_restart.mint_grant) and prints it to the context; a failed mint exits 2, which refuses that prompt; a subagent payload and every other prompt exit 0; guidance it cannot keep is a stderr warning and the capability stands | advisory | unexercised | source-level | hooks/userprompt-restart-authorize.py:1 @4ffb9279 | tests/test_restart_command.py, hooks/tests/test_overnight_wake.py |
| H-013 | UserPromptSubmit | (universal) | userprompt-tmpfs-pressure.sh | advisory; switch: none. It never blocks and exits 0 on every path: while /tmp or /dev/shm is over 75% it prints df and the five largest directories of each such mount, at most 3 times per session | advisory | unexercised | source-level | hooks/userprompt-tmpfs-pressure.sh:1 @4ffb9279 | none yet |
| H-014 | PreToolUse | (universal) | pretool-block-background-tasks.py | block; switch: none. Main agent only (agent_id present: exit 0), and /do consent lifts it: an Agent or Task call whose run_in_background is not explicitly false exits 2, except an explicit background Explore dispatch while a /spec interview's checklist has an open step; a Bash call with run_in_background true exits 2; SendMessage exits 2 except the exact /restart recovery message to a transcript-discovered pending interrupted agent id under a /restart capability or the overnight wake's (lib/subagent_restart); Workflow exits 2; a malformed payload exits 0. The dispatch gate consults it on Agent (R-012) | advisory | unexercised | source-level | hooks/pretool-block-background-tasks.py:1 @4ffb9279 | tests/test_restart_command.py, hooks/tests/test_one_process_gates.py |
| H-015 | PreToolUse | (universal) | pretool-orchestrator-gate.py | block; switch: none. Main agent only (subagents exempt, lib/subagent.is_subagent_context): the 6th Bash call exits 2 until an Agent dispatch or the next prompt resets the count (other tools between Bash calls do not); a tool outside its always-allowed list exits 2 on its second call in a turn; EnterPlanMode and ExitPlanMode exit 2 even under /do; /do consent lifts every other limit; an /allow grant naming the tool passes one call; an unreadable payload or state error exits 0 | advisory | unexercised | source-level | hooks/pretool-orchestrator-gate.py:1 @4ffb9279 | hooks/tests/test_do_consent_landing.py, hooks/tests/test_prompt_workflow_turn_state.py |
| H-016 | PreToolUse | (universal) | pretool-read-size-guard.py | block; switch: none. Main agent only: a Read of a text file over 600 lines exits 2 unless its limit is at most 600; subagents, binary files (images, PDF), /do consent and an /allow grant for Read pass; an unreadable payload exits 0 | advisory | unexercised | source-level | hooks/pretool-read-size-guard.py:1 @4ffb9279 | none yet |
| H-018 | PreToolUse | (universal) | pretool-workflow-gate.py | block; switch: none (CLAUDE_COMPAT_RUNTIME=codex selects its Codex plan path). Any tool but TodoWrite, TodoRead and the exact /restart helper call exits 2 (CHECKLIST NOT STARTED) while the transcript's active span is a checklist command's and holds no ok TodoWrite yet; on that path it writes nothing and only reads the workflow bookmark; under the Codex runtime it is the one writer of its own Codex plan record and exits 2 on an invalid or step-skipping update_plan; an unreadable payload exits 0. The dispatch gate consults it on Agent (R-014) | advisory | unexercised | source-level | hooks/pretool-workflow-gate.py:1 @4ffb9279 | tests/test_codex_workflow_gate.py |
| H-019 | PreToolUse | (universal) | pretool-worktree-guard.sh | advisory; switch: none. It never blocks and exits 0 on every path: while an agent worktree is behind the main branch (checked at most once a minute) it prints PreToolUse JSON whose additionalContext tells the model and whose systemMessage tells the user | advisory | unexercised | source-level | hooks/pretool-worktree-guard.sh:1 @4ffb9279 | hooks/tests/test_worktree_guard.py |
| H-027 | PreToolUse | Bash | pretool-bash-safety.sh | block; switch: none for its hard bans and git rules; its protected-daemon restart rule acts only when CLAUDE_PROTECTED_DAEMON_PREFIX or CLAUDE_PROTECTED_DAEMON_TARGETS is set, which the shipped settings.json does not do. Since P5 its hard ban reads a listed name merely after `(`, `;`, `\|`, `!` or `&` inside quoted data as text unless a word outside quotes can run text, its commit guard keeps single-quoted text beside a trailing `# comment` or a `$'..'` word as data, and a local keystone `git config` write from the harness home naming another repository by a literal absolute `-C`, `--git-dir` or `GIT_DIR` passes; a called alias whose value `--config-env` takes from the environment, a double-quoted `bash -c` or `eval` string inside a double-quoted `$(...)`, and commit or config text nested past the scanner's depth bound exit 2 (commit-hook-bypass, fail closed) | advisory | exercised | component-tested | hooks/pretool-bash-safety.sh:2079 @4ffb9279 | hooks/tests/test_blackbox_integration.py |
| H-029 | PreToolUse | Bash | pretool-block-branch-pr-worktree.py | block; switch: none. Each branch, PR or worktree creation form its docstring lists (git checkout -b, git switch -c, git branch NAME, git worktree add, gh pr create, gh pr checkout, a pulls POST, git stash branch, a refspec into refs/heads, git update-ref refs/heads) exits 2 for every caller, subagents included, unless a /dev-overnight session is live (lib/overnight.is_overnight_active), /do consent holds or an /allow grant names the command; list, delete, rename and info forms pass; an internal error exits 0 | advisory | unexercised | source-level | hooks/pretool-block-branch-pr-worktree.py:1 @4ffb9279 | hooks/tests/test_block_branch_pr_worktree.py |
| H-030 | PreToolUse | Bash | pretool-bulk-commit-detector.py | advisory; switch: none. It never blocks and exits 0 on every path: a `git commit` whose staged set spans three or more of hooks/, commands/, scripts/, packages/, docs/ and whose subject has the b5d447e shape gets a warning to the model as additionalContext | advisory | unexercised | source-level | hooks/pretool-bulk-commit-detector.py:1 @4ffb9279 | hooks/tests/test_hook_output_reaches_model.py |
| H-031 | PreToolUse | Bash | pretool-git-privilege-guard.py | block; switch: none. For the main agent and subagents alike, a git commit outside its allowed routes (the `auto-bulk:` bridge, a live /commit grant), git merge (/merge merges inside hooks/merge.sh, which no hook sees), git push outside a live /push grant, a hard reset and direct ref mutation exit 2; /do consent releases merge, forbidden plumbing, hard reset and ref mutation except where it can move the protected branch or the branch cannot be told. Since P5 a commit under a live `/commit` grant whose task_id is non-null exits 2 unless its whole message (the `-m`/`--message` values as git joins them, or the whole `-F`/`--file` regular file) carries the line `Task-id: <task_id>`; a message it cannot read exits 2; the bulk-commit route takes no such line | advisory | exercised | component-tested | hooks/pretool-git-privilege-guard.py:309 @4ffb9279 | hooks/tests/test_blackbox_integration.py |
| H-032 | PreToolUse | Bash | pretool-grep-backtrack-guard.py | block; switch: none. A text search whose pattern has the catastrophic-backtracking shape (two or more adjacent variable-length gaps) is probed through the same embedded engine under a memory and time ceiling, and exits 2 when the probe is killed; every other command, and any internal error, exits 0 | advisory | unexercised | source-level | hooks/pretool-grep-backtrack-guard.py:1 @4ffb9279 | hooks/tests/test_grep_backtrack_guard.py |
| H-033 | PreToolUse | Bash | pretool-wrapper-userintent.py | block; switch: none. A Bash command that runs scripts/break-overnight-lock.py or hooks/stop.sh exits 2 unless the session holds a live /stop user-intent sentinel (written when the human types /stop), which it then consumes; every other command exits 0 | advisory | unexercised | source-level | hooks/pretool-wrapper-userintent.py:1 @4ffb9279 | hooks/tests/test_stop_md_userintent_wrapper.py |
| H-035 | PreToolUse | EnterWorktree | pretool-block-enterworktree.sh | block; switch: none. An EnterWorktree call exits 2 unless a /dev-overnight session is live; a subagent's always, the main agent's unless /do consent holds or an /allow EnterWorktree grant exists; an unparseable payload exits 0 | advisory | unexercised | source-level | hooks/pretool-block-enterworktree.sh:1 @4ffb9279 | hooks/tests/test_block_branch_pr_worktree.py |
| H-036 | PreToolUse | Read | pretool-cp-checkin.py | advisory; switch: none. It never blocks and exits 0 on every path: a subagent's Read of its `cp-state-<agent>.json` or dev-registry sentinel registers it through scripts/spec-check.py register | advisory | unexercised | source-level | hooks/pretool-cp-checkin.py:1 @4ffb9279 | hooks/tests/test_cp_checkin.py |
| H-037 | PreToolUse | TodoWrite | pretool-todo-validate.py | block; switch: none. The TodoWrite rules' one decider: a list that breaks one exits 2 (the canonical list on a span's first list or a change of length; at most one step completed per call; in_progress before completed; one in_progress; immutable content and activeForm; steps in order; a subagent step completed only after an ok Agent call of its type; the overnight wake step only after its recurring CronCreate) | advisory | unexercised | source-level | hooks/pretool-todo-validate.py:1 @4ffb9279 | hooks/tests/test_todo_validate_after_restart.py, hooks/tests/test_todo_validate_in_flight.py |
| H-039 | PreToolUse | Write\|Edit\|MultiEdit | pretool-quality-gate.py | advisory; switch: none. It never blocks and exits 0 on every path: a Write's content or an Edit's result over 800 file lines, 30-line functions or nesting depth 3, in a .py/.ts/.js/.tsx/.jsx file, gets a warning to the model as additionalContext unless the edit does not worsen it; a MultiEdit is not checked | advisory | unexercised | source-level | hooks/pretool-quality-gate.py:1 @4ffb9279 | hooks/tests/test_hook_output_reaches_model.py |
| H-043 | PreToolUse | mcp__playwright__browser_run_code | pretool-runcode-watchdog.py | advisory; switch: none (PLAYWRIGHT_RUNCODE_TIMEOUT sets the limit: 30 s when unset, 120 s in the shipped settings.json). It never blocks: starts a detached watchdog that ends the script over CDP once the call runs past that limit | advisory | unexercised | source-level | hooks/pretool-runcode-watchdog.py:1 @4ffb9279 | hooks/tests/test_runcode_watchdog_aliases.py |
| H-044 | PostToolUse | * | posttool-allowlist-consume.py | advisory; switch: none. It never blocks the call, which has already run: it unlinks the /allow grant a finished call matches (a Bash command, a Write target, a grant naming the tool) and a malformed or expired grant file; for a `git commit` a single-use commit grant authorized it appends the commit-event journal record, of which it is the one writer (hooks/lib/commit_journal.py), and removes the event pointer; after a Write of a faulty merge-analyst grant it removes the grant and exits 2, which returns MERGE_GRANT_INVALID to the writing agent | detected | unexercised | source-level | hooks/posttool-allowlist-consume.py:1 @4ffb9279 | hooks/tests/test_allowlist_consolidation.py |
| H-048 | PostToolUse | Bash | posttool-git-warn.sh | advisory; switch: GIT_WARN_UNTRACKED=1 turns it on (the shipped settings.json sets it; any other value leaves it silent). It never blocks and exits 0 on every path: after a successful Bash call that runs `git commit`, the untracked files (20 named at most) reach the model as additionalContext | detected | unexercised | source-level | hooks/posttool-git-warn.sh:1 @4ffb9279 | hooks/tests/test_hook_output_reaches_model.py |
| H-049 | PostToolUse | SendMessage | posttool-restart-sendmessage.py | advisory; switch: none. It never blocks and exits 0 on every path: a validated /restart SendMessage is recorded as dispatched (lib/subagent_restart.mark_dispatched) and `RESTART DISPATCH RECORDED: <agent>; incomplete=<n>` reaches the orchestrator as additionalContext | detected | unexercised | source-level | hooks/posttool-restart-sendmessage.py:1 @4ffb9279 | tests/test_restart_command.py |
| H-050 | PostToolUse | Skill | posttool-codex-skill-ledger.py | advisory; switch: none. It never blocks and exits 0 on every path: a Skill call of `codex` by an agent whose cycle registry resolves (lib/agent_cycle) writes `.claude/dev-registry/<sid>/codex-ledger/<agent_id>.json` with the call's status, the entry R-022 requires | detected | unexercised | source-level | hooks/posttool-codex-skill-ledger.py:1 @4ffb9279 | hooks/tests/test_cli_role_own_cycle.py |
| H-051 | PostToolUse | TodoWrite | posttool-overnight-loop.py | advisory; switch: none. It never blocks. Acts only on a TodoWrite whose todos are all completed, for a session that owns an overnight state record (lib/overnight.py locate): while the time-lock window is open (window_open) it gives the agent the continuation instructions (reset the todos, resume from Step 2), and once the window has closed a session-complete line, both as additionalContext; writes no state and never exits 2, so the todo reset is never blocked | detected | unexercised | source-level | hooks/posttool-overnight-loop.py:1 @4ffb9279 | hooks/tests/test_posttool_overnight_loop_terminal_gate.py |
| H-054 | PostToolUse | TodoWrite | posttool-todo-tracker.py | advisory; switch: none (CLAUDE_COMPAT_RUNTIME=codex makes it exit 0). It never blocks and exits 0 on every path: after a TodoWrite in a checklist command's span the checklist progress reaches the agent as additionalContext; writes nothing | detected | unexercised | source-level | hooks/posttool-todo-tracker.py:1 @4ffb9279 | hooks/tests/test_checklist_record.py |
| H-055 | PostToolUse | Write\|Edit\|NotebookEdit\|MultiEdit | posttool-command-frontmatter-validate.py | advisory; switch: none. It never blocks and exits 0 on every path: after a write of a `.claude/commands/*.md` file whose frontmatter lacks the opening or closing `---` or a description, the errors reach the model as additionalContext | detected | unexercised | source-level | hooks/posttool-command-frontmatter-validate.py:1 @4ffb9279 | hooks/tests/test_hook_output_reaches_model.py |
| H-056 | PostToolUse | Write\|Edit\|NotebookEdit\|MultiEdit | posttool-doc-sync.py | advisory; switch: none. It never blocks and exits 0 on every path: after a structural file changes it updates the marked sections of the INDEX.md, README.md and CLAUDE.md files that exist (it creates none) | detected | unexercised | source-level | hooks/posttool-doc-sync.py:1 @4ffb9279 | hooks/tests/test_doc_sync_hook_notices.py |
| H-057 | PostToolUse | Write\|Edit\|NotebookEdit\|MultiEdit | posttool-git-checkpoint.sh | advisory; switch: GIT_CHECKPOINT_THRESHOLD (10 when unset; the shipped settings.json sets 10). Acts only when the repository's pending files reach that threshold: writes a `refs/checkpoints/<branch>` snapshot through `hooks/lib/checkpoint-core.sh`; a snapshot the library refuses (nothing written) is reported as one JSON `systemMessage`, auto-commit.sh's refusal notice (S-006), as the hook's whole stdout; exits 0 on every path | detected | unexercised | source-level | hooks/posttool-git-checkpoint.sh:1 @4ffb9279 | hooks/tests/test_posttool_checkpoint_refusal.py |
| H-058 | PostToolUse | mcp__playwright__browser_run_code | posttool-runcode-watchdog.py | advisory; switch: none. It never blocks and exits 0 on every path: stops the watchdog H-043 started; when its timeout already fired, that reaches the model as additionalContext | detected | unexercised | source-level | hooks/posttool-runcode-watchdog.py:1 @4ffb9279 | hooks/tests/test_runcode_watchdog_aliases.py |
| H-071 | PostToolUseFailure | Bash | posttool-allowlist-consume.py | advisory; switch: none. It never blocks: the H-044 consumer on the failure event, so a Bash call that failed or was interrupted consumes the grant it matches and a failed commit's event pointer is removed | detected | unexercised | source-level | hooks/posttool-allowlist-consume.py:1 @4ffb9279 | hooks/tests/test_commit_event_pointer.py |
| H-073 | SessionStart | (universal) | session-scratch-init.sh | advisory; switch: none. Creates the session's own scratch directory `$TMPDIR/<session-id>/` and writes its `.owner` record; skips when no session id is available or the id contains `/` or `..`, saying so on its stdout (the model's context); best-effort, exits 0 on every path | detected | unexercised | source-level | hooks/session-scratch-init.sh:1 @4ffb9279 | hooks/tests/test_scratch_lifecycle.py |
| H-074 | PreToolUse | (universal) | pretool-do-block-subagents.py | block; switch: none. Exits 2 only for a main-agent Agent or Task call while this session's /do consent reads true (lib/allowlist.py has_do_consent), unless this session holds an /allow grant for the Agent tool; every other call, and any internal error, exits 0. The dispatch gate consults it on Agent (R-013) | advisory | unexercised | source-level | hooks/pretool-do-block-subagents.py:1 @4ffb9279 | hooks/tests/test_do_block_subagents.py |
| H-078 | PreToolUse | Write\|Edit\|MultiEdit\|NotebookEdit\|Bash | pretool-attribution-pre.py | advisory; switch: none. Observational: records the pre-mutation content hash of each write target in the attribution journal; never blocks, exits 0 on every path | advisory | unexercised | source-level | hooks/pretool-attribution-pre.py:1 @4ffb9279 | hooks/tests/test_attribution_journal.py |
| H-079 | PostToolUse | Write\|Edit\|MultiEdit\|NotebookEdit\|Bash | posttool-attribution-post.py | advisory; switch: ATTRIBUTION_AUTOSEAL_DISABLE=1 skips the seal check. Observational: appends the attribution event(s) paired with the H-078 record, then runs the periodic journal seal check; exits 0 on every path | detected | unexercised | source-level | hooks/posttool-attribution-post.py:1 @4ffb9279 | hooks/tests/test_attribution_journal.py |
| H-080 | PostToolUse | Write\|Edit\|NotebookEdit\|MultiEdit | posttool-lane-completeness-watch.py | advisory; switch: none. Acts only when the written file is a lane dev-report shard whose own lane_set is a non-empty list: it then runs scripts/aggregate-dev-report.py for that task, the canonical aggregate's one producer (whether every lane has reported is G3's check, R-008); exits 0 on every path | detected | unexercised | source-level | hooks/posttool-lane-completeness-watch.py:1 @4ffb9279 | hooks/tests/test_lane_completeness_watch.py |
| H-085 | SessionEnd | (universal) | sessionend-scratch-sweep.sh | advisory; switch: none. Removes `$TMPDIR/<own-session-id>/` only when it is a real directory directly under that root whose `.owner` sid equals the session id, and the session's own `.claude/workflow-<sid>.json`, `.claude/workflow-locks/<sid>.lock` and `.claude/dev-start-replays/<sid>` in the project; prints nothing; best-effort, exits 0 on every path | detected | unexercised | source-level | hooks/sessionend-scratch-sweep.sh:1 @4ffb9279 | hooks/tests/test_scratch_lifecycle.py |
| H-087 | PostToolUse | AskUserQuestion\|Agent | posttool-close-rating.py | advisory; switch: none. It records only, never blocks, exits 0 on every path, and prints neither decision, continue nor updatedToolOutput: a dispatcher that holds no logic and sends the call by tool_name, to handlers that act only on a main-agent call (no agent_id): the question tool by the prefix of its `metadata.source` to one handler per library (three routes), an Agent call to the score observer, over the score log `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/logs/lifecycle.jsonl` for the rating and the events (its rules are `hooks/lib/score_log.py`; its one writer path, append_all, reads the log once with a tolerant scan, cuts a crash-truncated tail back to the last newline, skips a row that cannot be serialised, and lets the first row per key win). A question of any other source writes and prints nothing. D9b (a gate needs the question asked, not answered): on every route Skip, an AFK auto-continue, a decline and an error result write nothing. Route `close-rating:<task-id>` (`hooks/lib/close_rating.py` handle): for a call whose one question is answered with one of the four rating labels, appends one rating row `{kind, ts, project, task_id, rating, roles, tool_use_id}` under an exclusive lock on `<log>.lock`, only while no rating row holds that canonical task id (an event row, a row without kind or another task's rating never stops it). Only on such a real label does it write the row (none when the task already holds a rating row) and then sweep the active command span for score events; Skip, free text, a typed reply, an AFK auto-continue, a decline, an error result and an unanswered annotation write no row and sweep nothing. For a main-agent call with exactly one close-rating question it then returns the owner summary, read from the log as it stands, as a systemMessage when the log can be read (three lines, control and format characters removed from their text, names cut to 24 characters, the cycle line cut to 200); the hook prints that one JSON object, the only output of any route. Routes `requirement-round:<task>:r<n>` and `producer-question:<task>:<role>` (P13-1 R4, D28; `hooks/lib/requirement_round.py` handle): write the owner's answer file `docs/dev/requirement-answers-<task>-r<n>.json` or the producer answer `docs/dev/producer-answer-<task>-<role>-<q8>.json` from the CLI's tool_input and tool_response verbatim (a typed reply and the annotations too), the first ask per file winning; only for a main-agent call whose response holds the owner's content (answers, response or annotations) and no afkTimeoutMs, whose questions equal the round file's (a paraphrase writes nothing) or whose source names an existing producer question file; these routes print nothing. Dispatch branch (an Agent call; the script also accepts a Task payload, which the registered matcher never delivers; `hooks/lib/score_events.py` observe): appends score events (qa_first_pass, qa_fail, qa_catch, escaped, close_catch, rerun_gap and, for the BA panel, ba_root_cause_refuted and ba_option_chosen) from facts of the active command span (QA report status and failures, the files a re-dispatch wrote, close-time findings, re-dispatches, the panel QA's file and the owner's answer file of the requirement round) in one batch under one lock, the first row per event key only: escaped is charged once per task, cited file and role, close_catch once per task and cited file, qa_catch ignores bookkeeping files, and a QA report whose real path lies outside the project is not read; each rule runs in its own try; the branch prints nothing, and writes nothing in a session that holds no command span. Evidence: hooks/tests/test_close_rating.py runs the hook as a subprocess on synthetic payloads for the rating route (row shape, labels, the non-answers, first rating wins, other sources and subagents, garbage input, the lock) and for a dispatch with no span, and checks the routing by tool and by source (a rating, a requirement round, a producer question, another source) and the sweep call with stand-ins; hooks/tests/test_requirement_round.py runs the same script as a subprocess for the two answer routes (the answer file written verbatim, the first ask winning, the producer answers, what writes nothing) and holds its stdout and stderr empty; tests/test_score_events.py calls observe and sweep in-process on constructed sessions (each rule, repeat runs, a crash-truncated tail, racing processes); tests/test_score_log.py covers the writer, the score and the renderers; tests/test_rating_view.py runs scripts/rating-view.py, the read side of the same log; tests/replay/test_requirement_round.py (the /spec and /dev rounds: the answer file equals the replayed tool_response) and tests/replay/test_score_replay.py (the /dev and /close cycles: the score log and the rating row follow the replayed dispatches and answers) replay cycles in a sandbox where a stand-in CLI, not a Claude Code dispatcher, selects this hook script by the shipped settings.json matcher and runs it, and the tests read each run's exit code, stdout and stderr; none of it ran under a Claude Code dispatcher | detected | unexercised | source-level | hooks/posttool-close-rating.py:1 @e3e2f98b | hooks/tests/test_close_rating.py, hooks/tests/test_requirement_round.py, tests/test_score_events.py, tests/test_score_log.py, tests/test_rating_view.py, tests/replay/test_requirement_round.py, tests/replay/test_score_replay.py |
| H-088 | Stop | (universal) | stop-launch.py | block; switch: CLAUDE_COMMAND_GATE=off, read from the process environment only, skips the completion phase and the time-lock with it; the shipped settings.json does not set it. The `Stop` group's one entry (`"timeout": 300`): runs `stop-workflow-coordinator.py` on the payload (280 s) and relays its exit 0 or 2, stdout and stderr; the coordinator's phases are S-005 – S-008 (section 4), whose completion phase, `stop-command-gate.py`, holds every gated command's stop. When the coordinator does not decide (another exit, a timeout, a launch error, a missing file) the launcher decides alone on the transcript reader (`hooks/lib/command_span.py`) and `hooks/lib/overnight.py`'s `window_open`, both loaded by path: an open overnight window, or a gated latest human-typed command in block mode, exits 2 naming the failure and `/stop`; anything else exits 0; a check whose module cannot load counts as not holding | advisory | unexercised | source-level | hooks/stop-launch.py:1 @4ffb9279 | hooks/tests/test_stop_launch.py |
| H-089 | PreToolUse | * | pretool-write-gate.py | block; switch: none at the gate (each rule keeps its own). Registered on every tool with `"timeout": 70`; it runs the rules of `hooks/lib/write_gate/__init__.py` RULES whose tools match the call's tool_name (R-001 – R-006, section 3.1), in order, each in its own try within its own budget (they sum to 60 s), and exits 2 with every refusing rule's reason, in rule order, when any rule exits 2 or denies; else it relays one JSON object (ask or defer, allow, updatedInput, additionalContext); a rule's other non-zero status is an error that does not decide the call (its stderr reaches the user); a fail-closed rule's error or overrun (tool-policy) refuses the call and a fail-open rule's lets it go on; when the gate's own code fails it runs each matching rule as its own process and combines their answers the same way | advisory | unexercised | source-level | hooks/pretool-write-gate.py:1 @4ffb9279 | hooks/tests/test_write_gate.py, hooks/tests/test_write_gate_overwrite_parity.py |
| H-090 | PreToolUse | Agent | pretool-dispatch-gate.py | block; switch: none at the gate (each rule keeps its own). It runs the eleven rules of its RULES (R-007 – R-017, section 3.1) in order, each as its own hook would run alone (hooks/lib/gate_runner.py), and exits 2 with the reasons of every refuse rule (R-007 – R-011) that exits 2, reported together once; the consulted hooks (R-012 – R-014) refuse from their own registrations, so the gate reports nothing for them; the observe and advise rules' additionalContext reaches the orchestrator as one object when nothing refused, and follows the reasons on stderr when something did; the witness (R-017) runs last, only when no rule refused and no consulted hook would; an error that escapes a rule is that rule's exit 1, and the next rule still runs. No timeout is registered | advisory | unexercised | source-level | hooks/pretool-dispatch-gate.py:1 @4ffb9279 | hooks/tests/test_one_process_gates.py |
| H-091 | PostToolUse | Agent | posttool-dispatch-record.py | advisory; switch: none at the gate. It never blocks the Agent call, which has already returned: it runs R-018 – R-021 in order, the cycle contract's writer before the two rules that read it; when R-019 exits 2 the gate exits 2 and the finding returns to the orchestrator; the observe and advise rules' additionalContext reaches the orchestrator as one object; an error that escapes a rule is that rule's exit 1. No timeout is registered | detected | unexercised | source-level | hooks/posttool-dispatch-record.py:1 @4ffb9279 | hooks/tests/test_one_process_gates.py, hooks/tests/test_dev_loop_checks.py |
| H-092 | SubagentStop | * | subagentstop-producer-gate.py | block; switch: none at the gate (each rule keeps its own). It runs R-022 – R-026 in order, each as its own hook would run alone, and exits 2 when any refuse rule (R-022 – R-025) exits 2, with every refusing rule's reasons reported together once to the stopping producer; where R-024 (G2) states a QA's declared report absent, R-023's line for that path is left out and both still refuse; R-026 runs whatever they decided; a main-agent stop (no agent_id) passes every rule; an error that escapes a rule is that rule's exit 1. No timeout is registered | advisory | unexercised | source-level | hooks/subagentstop-producer-gate.py:1 @4ffb9279 | hooks/tests/test_one_process_gates.py |
| H-093 | SubagentStart | (universal) | subagentstart-record.py | advisory; switch: none. It never blocks (a SubagentStart exit 2 is no refusal of the agent) and exits 0 on every path: prints, as `hookSpecificOutput.additionalContext` (which the CLI puts in the starting subagent's context), the agent's own record in at most 3 lines and 400 bytes: its score, rank and trend from the score log `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/logs/lifecycle.jsonl` as of the span opener's time, its newest good event and newest miss as facts (an event's why, no task id), and the rank's reminder, with the role's consequence when its record is low (the two lowest ranks: a second independent QA round for dev and ba, a Codex debate for qa; the Stop gate and R-022 hold them, so this text only says so). An agent with no rows gets one line. It prints nothing for an agent outside `agents/`, in a /close, /commit, /merge or /push span, and on any error. It reads the log and writes nothing | advisory | exercised | component-tested | hooks/subagentstart-record.py:1 @a959bcec | hooks/tests/test_score_view.py |

### 3.1 Rules a merged gate runs

Each rule below is a hook file (or, for R-016 and R-021, a function) that one of the four gates
runs in its own process, in the gate's order. **A rule keeps its own decision, exemptions, switch
and failure direction**; the gate adds only the order and the one combined answer. A rule's
`mode/precondition` cell is the rule's own, as it would decide on its own registration, read
from its code; its `gate` column names the gate row of section 3 that runs it. The rule kinds of
`hooks/lib/gate_runner.py`: `refuse` decides (exit 2 refuses); `consult` is a hook that keeps its
own registration and decides there, run only to learn its verdict; `observe` and `advise` never
refuse; `witness` runs only when nothing refused. These rows are not registrations, so
`--claims` does not compare them with `settings.json`, and `tests/lint`'s hook-strength check,
which reads the section 3 table, does not read them.

The write gate's columns are its rule table's own declarations (`hooks/lib/write_gate/__init__.py`):
`tools` is the rule's old matcher, the tool names it sees; `actors` whom its code governs (the
gate does not skip on it); `fail` what an uncaught error or an overrun of its `budget` (seconds)
means. For the gate_runner gates, `tools` is the gate's matcher, `actors` whom the rule's own
code governs, `fail` is `open` (an escaped error is the rule's exit 1, a non-blocking error) and
no per-rule budget exists.

| rule_id | gate | rule (kind) | rule file | tools | actors | fail | budget | mode/precondition | citation | verifying_test |
|---|---|---|---|---|---|---|---|---|---|---|
| R-001 | H-089 | bash-views (refuse) | hooks/pretool-bash-views-guard.py | Bash | both | open | 5 | block; switch: none. A Bash redirect into `*.lock.json`, `*/manifest.json.lock`, `docs/dev/specs/*/views/*.md`, `.claude/specs/*/cp-state-*.json` or a views `manifest.json` exits 2; exemption: a command that runs scripts/spec-check.py, the cp-state writer; a parse error exits 0 | hooks/lib/write_gate/__init__.py:60 @4ffb9279 | hooks/tests/test_bash_views_guard.py |
| R-002 | H-089 | overnight-boundary (refuse) | hooks/pretool-overnight-hook-guard.py | Write, Edit, MultiEdit, Bash, AskUserQuestion | both | open | 20 | block, only while a /dev-overnight session is live; switch: none. AskUserQuestion exits 2 for the /dev-overnight session's main agent and subagents until a human-typed prompt follows its /dev-overnight; while any overnight session is active a write to `.claude/hooks/` or an overnight state file exits 2; for the overnight owner and its children a write outside the worktree, a Write or Edit of the checkout's git config (the keystone) and a git operation aimed at the main root exit 2, and a Bash command is rerun inside a read-only bwrap boundary (updatedInput) or refused when bwrap is unavailable; a normal session on main exits 0. Exemptions: none (no /do, no /allow) | hooks/lib/write_gate/__init__.py:62 @4ffb9279 | hooks/tests/test_overnight_guard_in_place_git.py |
| R-003 | H-089 | tool-policy (refuse) | hooks/pretool-tool-policy.py | every tool | both | closed | 20 | block; switch: none. Every caller, the main agent included: a write, delete or rename of a protected file (the harness home's settings.machine.json, private-literals.txt, scripts/check-public-core.sh, scripts/install/render-settings, hooks/git-hooks/pre-commit, .git/config, .git/hooks/, .gitattributes; a session transcript or its subagent meta; a /do task sidecar) exits 2, as does a ScheduleWakeup prompt typing a harness command outside CONTROL; a Write, Edit, MultiEdit or NotebookEdit target or Bash write target that another dispatch of the session declares (its obligation's artifacts, the producer question it may write, its template's declarations) exits 2, naming the path, the declaring role and "only <role> writes this artifact (D8)"; a write under `<state dir>/agentic-commit/<name>/` exits 2 for any caller but `<name>` (grant binding, D8); a subagent whose role the policy lists takes that role's rows of policies/tool-policy.v1.json and exits 2 on a denied tool or path, which refuses every non-dev role's code write; a deny-logic import failure exits 2; an unresolved or unlisted role (Explore, Plan, general-purpose, a plugin's) and any other internal error exit 0. Exemptions: the main agent passes the role rows once the derived write permission allows it; the declaring dispatch's own write of a path it declares P13-1 R6 (D28): the owner's answer files (`docs/dev/requirement-answers-*.json`, `docs/dev/producer-answer-*.json`) and the score log `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/logs/lifecycle.jsonl` with its `.lock` are hook-owned: every caller's Write, Edit, NotebookEdit or Bash write, delete or rename of one is refused. | hooks/pretool-tool-policy.py:1 @4ffb9279 | hooks/tests/test_tool_policy_derived_permission.py, hooks/tests/test_tool_policy_protected_paths.py |
| R-004 | H-089 | cp-state (refuse) | hooks/pretool-cp-state-write-guard.py | Write, Edit, MultiEdit, NotebookEdit, Bash | subagent | open | 5 | block; switch: none. A subagent's Write, Edit, MultiEdit or NotebookEdit of a `cp-state-*.json` under `.claude/specs/`, `docs/dev/specs/` or `dot-claude/specs/` exits 2 naming scripts/spec-check.py, the one cp-state writer; a Bash call is out of its scope (exit 0); the main agent is not governed; any exception exits 0 | hooks/lib/write_gate/__init__.py:66 @4ffb9279 | hooks/tests/test_write_gate.py |
| R-005 | H-089 | overwrite (refuse) | hooks/lib/write_gate/overwrite.py | Write | both | open | 5 | block; switch: none. A Write whose target's name is `claude-bulk-commit-sentinel-*.json` exits 2 for every actor with no exemption; a Write whose target is an existing file exits 2 ("[Write Guard] BLOCKED: File already exists", Edit it in place); exemptions for the overwrite check: /do consent and an /allow grant naming the target (main agent), while a same-session grant naming another target refuses the overwrite; no target exits 0. The rule of the stub `pretool-write-guard.sh`, decision for decision | hooks/lib/write_gate/overwrite.py:1 @4ffb9279 | hooks/tests/test_write_gate_overwrite_parity.py |
| R-006 | H-089 | claude-config (refuse) | hooks/pretool-claude-config-guard.py | Edit, Write, MultiEdit, Bash | both | open | 5 | block; switch: none. An Edit, Write, MultiEdit or Bash write aimed at the project's `.claude/hooks/` or `.claude/commands/` exits 2, for the main agent and subagents; exemptions: the project's `.claude/.hook-refactor-allow` sentinel, made by hand, and /dev-command's dev writing the project command file its cycle develops; an uncaught exception exits 0 | hooks/lib/write_gate/__init__.py:74 @4ffb9279 | hooks/tests/test_claude_config_guard.py |
| R-007 | H-090 | overnight-contract (refuse) | hooks/pretool-subagent-enforce.py | Agent | both | open | none | block, only in a /dev-overnight session; switch: none. An Agent call whose role, pipeline_id or mode the cycle allows at the current checklist step (the exploration steps from scripts/todo/dev-overnight.py, then the cycle contract R-018 writes) exits 0; a mismatch exits 2 with a structured message; a contract that holds no JSON object allows only the exploration steps; no overnight state, no in-progress step, /do consent and (main agent) an /allow grant for Agent exit 0 | hooks/pretool-dispatch-gate.py:43 @4ffb9279 | hooks/tests/test_overnight_cycle_contract.py |
| R-008 | H-090 | g3-aggregate (refuse) | hooks/pretool-aggregate-check.py | Agent | both | open | none | G3; block under CLAUDE_OBLIGATION_BARRIER=block, which the shipped settings.json sets: a qa dispatch (Agent or Task) exits 2 in every mode while every lane of a fan-out in its scope (the task its own obligation names) has reported and the canonical aggregate dev-report is missing, and exits 0 under the session's /do consent or, from the main agent, an /allow grant for Agent; the lane-roster and parallel_workers checks, the canonical-validity check, the obligation barrier (a prior dispatch's declared artifact of the same task family missing or invalid at a later dispatch that does not declare it again) and the gitignore rule exit 2 under =block; under =advisory or with the key unset the barrier prints each finding it would block on stderr (OBLIGATION BARRIER ADVISORY) and the canonical-validity check a warning, and the dispatch proceeds; =off also skips the barrier; writes nothing; internal errors exit 0 | hooks/pretool-aggregate-check.py:1 @98e41855 | tests/test_aggregate_dev_report.py |
| R-009 | H-090 | gitignore-preflight (refuse) | hooks/pretool-gitignore-preflight.py | Agent | both | open | none | block; switch: none. A dispatch prompt naming a `docs/dev/dev-report-*.json` whose dev.files_modified or dev.files_created holds a path .gitignore matches exits 2, unless the report carries a non-empty gitignore_waiver or one of its discriminators applies (an audit-input reference, a /close-mandated deliverable, a /close lane-matrix or canonical-parent reference of its own cycle, a close or commit producer reading its own task's report); no report reference, a report not on disk and an unreadable payload exit 0. G3 (R-008) applies the same function under its switch | hooks/pretool-gitignore-preflight.py:1 @4ffb9279 | hooks/tests/test_gitignore_preflight_close_contract.py |
| R-010 | H-090 | g1-obligation (refuse) | hooks/pretool-obligation-gate.py | Agent | both | open | none | G1; block under CLAUDE_OBLIGATION_GATE=block, which the shipped settings.json sets: a dispatch without a valid obligation block (a missing block counts only when the active command's dispatch templates in `commands/<command>.md`, as its session loaded them (the text the CLI recorded when the command was typed), declare an obligation for its subagent_type; a malformed block counts on any dispatch) exits 2; under =advisory or with the key unset it is allowed, the reason it would block printed on one stderr line (OBLIGATION GATE ADVISORY) and nothing written; skipped under =off; internal errors exit 0 P13-1 R5 (D28): in block mode, inside a span whose loaded text or checklist asks the requirement round (`requirement_round.runs_round`), a dispatch made while a schema-valid round or producer-question file of the span's task, whose producer's latest dispatch came back ok, is not asked, or one declaring anything beyond round 1's producers before round 1 is asked, exits 2 with `ASK_FIRST: ...` (`hooks/lib/requirement_round.py` `ask_first`); a dispatch declaring that question file, or carrying no obligation, passes. | hooks/pretool-obligation-gate.py:1 @98e41855 | hooks/tests/test_obligation_gate.py |
| R-011 | H-090 | spec-window (refuse) | hooks/pretool-spec-block-foreground-agent.py | Agent | main | open | none | block; switch: none. A main-agent Agent call that is not explicitly in the background exits 2 while the transcript's active span is /spec's and its checklist has a step not completed; a subagent's call and any unexpected exception exit 0 P13-1 (D28, D32): a foreground `ba` passes too (the requirement round's BAs). | hooks/pretool-dispatch-gate.py:47 @4ffb9279 | hooks/tests/test_obligation_gate.py |
| R-012 | H-090 | background-agent (consult) | hooks/pretool-block-background-tasks.py | Agent | main | open | none | decided by its own registration, H-014 (block; switch: none); the gate runs it only to learn whether that registration refuses the call, skips the witness when it would, and reports nothing for it | hooks/pretool-dispatch-gate.py:48 @4ffb9279 | hooks/tests/test_one_process_gates.py |
| R-013 | H-090 | do-block-subagents (consult) | hooks/pretool-do-block-subagents.py | Agent | main | open | none | decided by its own registration, H-074 (block; switch: none); consulted as R-012 is | hooks/pretool-dispatch-gate.py:49 @4ffb9279 | hooks/tests/test_one_process_gates.py |
| R-014 | H-090 | checklist-started (consult) | hooks/pretool-workflow-gate.py | Agent | both | open | none | decided by its own registration, H-018 (block; switch: none); consulted as R-012 is | hooks/pretool-dispatch-gate.py:50 @4ffb9279 | hooks/tests/test_one_process_gates.py |
| R-015 | H-090 | prompt-purity (observe) | hooks/pretool-orchestrator-prompt-purity.py | Agent | main | open | none | advisory; switch: none. It never blocks and exits 0 on every path: a main-agent dispatch prompt that prescribes HOW (tool names, shell-command tokens with options, shell syntax, fenced bash blocks; `<USER_VERBATIM>` text and the dev-registry registration boilerplate removed first) gets a warning to the orchestrator as additionalContext; a subagent's dispatch is not scanned | hooks/pretool-orchestrator-prompt-purity.py:1 @4ffb9279 | hooks/tests/test_hook_output_reaches_model.py |
| R-016 | H-090 | dev-loop-before (advise, `lib.dev_loop_checks:advice`) | hooks/lib/dev_loop_checks.py | Agent | both | open | none | advisory; switch: none. It never refuses: for an Agent or Task call of subagent_type dev whose obligation declares `docs/dev/dev-report-<X>.json`, the layer-escalation advice (two or more prior attempts at one layer, the diagnosis targeting it again) and the bisect advice (a regression without git_bisect_result) reach the orchestrator as additionalContext; any other call gets none. Replaces the stubs `pretool-layer-escalation-check.sh` and `pretool-bisect-gate.sh` | hooks/pretool-dispatch-gate.py:52 @4ffb9279 | hooks/tests/test_dev_loop_checks.py |
| R-017 | H-090 | commit-dispatch-witness (witness) | hooks/pretool-commit-dispatch-attest.py | Agent | both | open | none | advisory; switch: none. Witness only, exits 0 on every path: writes a dispatch attestation `<state dir>/claude-commit-dispatch-<sid>-<nonce>.json` (later required by pretool-git-privilege-guard.py) for an Agent or Task call whose subagent_type is changelog-analyst and whose payload carries a session id, and the gate runs it only when no rule of the dispatch gate refused and no consulted hook would, so no refused dispatch is witnessed | hooks/pretool-dispatch-gate.py:53 @4ffb9279 | hooks/tests/test_one_process_gates.py, hooks/tests/test_commit_event_pointer.py |
| R-018 | H-091 | cycle-contract-writer (observe) | hooks/posttool-subagent-track.py | Agent | both | open | none | advisory; switch: none. It never blocks and exits 0 on every path: on the PM TRIAGE step's return in /dev-overnight it writes the cycle contract `docs/dev/overnight/<sid>/cycle-<N>/cycle-contract.json`, its one writer, by rename, and keeps a contract the cycle already has; it writes no workflow bookmark; its outcome reaches the orchestrator as additionalContext | hooks/posttool-dispatch-record.py:31 @4ffb9279 | hooks/tests/test_overnight_cycle_contract.py |
| R-019 | H-091 | overnight-file-check (refuse) | hooks/posttool-overnight-file-check.py | Agent | both | open | none | advisory (a PostToolUse exit 2 returns its finding after the call has run); switch: none. At the return of a dispatch the cycle contract governs, a json or markdown artifact its own obligation declares that is missing or invalid exits 2 naming each artifact, its failing check and the declaring dispatch's next round; no contract (before PM TRIAGE, outside /dev-overnight), no matching entry, no obligation, a valid producer question and all-valid artifacts exit 0 | hooks/posttool-dispatch-record.py:32 @4ffb9279 | hooks/tests/test_overnight_cycle_contract.py |
| R-020 | H-091 | overnight-trace (observe) | hooks/posttool-overnight-trace.py | Agent | both | open | none | advisory; switch: none. Observability only, exits 0 on every path: in an overnight cycle with a contract, one JSONL trace record per Agent return in `docs/dev/overnight/<sid>/cycle-<N>/trace.jsonl`, plus a specialist report's yield; exceptions are named on stderr | hooks/posttool-dispatch-record.py:33 @4ffb9279 | hooks/tests/test_overnight_trace_evidence.py, hooks/tests/test_overnight_trace_yield.py |
| R-021 | H-091 | dev-loop-after (advise, `lib.dev_loop_checks:advice`) | hooks/lib/dev_loop_checks.py | Agent | both | open | none | advisory; switch: none. It never refuses: for a returned dev dispatch whose obligation declares `docs/dev/dev-report-<X>.json`, the layer-match, guard-integrity and minimum-diff (more than 30 inserted lines without a justification) advice reaches the orchestrator as additionalContext. Replaces the stubs `pretool-layer-match-gate.sh`, `subagent-stop-guard-integrity.sh` and `subagent-stop-diff-check.sh` | hooks/posttool-dispatch-record.py:34 @4ffb9279 | hooks/tests/test_dev_loop_checks.py |
| R-022 | H-092 | codex-ledger (refuse) | hooks/subagentstop-codex-enforce.py | * | subagent | open | none | block in a cycle run with `--codex`; switch: the cycle registry's `codex-enforce.json` with enabled true (written when the command is launched with `--codex`), no environment variable. A stopping subagent whose dispatch is bound (its prompt, or the dispatch template it was made from, carries `codex_required: true`) and whose `codex-ledger/<agent_id>.json` (H-050) is absent exits 2 (CODEX_ENFORCE_BLOCKED); a dispatch whose obligation names pipeline close or commit is not bound; a QA of a /dev-family cycle whose record is low (hooks/lib/score_view.py `codex_forced`: the two lowest ranks as of the span opener, D32) is bound whether or not `--codex` armed the cycle, with no flag and no line, and is let go when it stops again after the block (`stop_hook_active`: codex may be unavailable, and no flag switches this rule off); no agent_id, no cycle, no enabled flag (unless that QA is low), an unbound dispatch and any internal error exit 0 | hooks/subagentstop-codex-enforce.py:1 @4ffb9279 | hooks/tests/test_subagentstop_codex_enforce.py |
| R-023 | H-092 | qa-e2e (refuse) | hooks/subagentstop-e2e-enforce.py | * | subagent | open | none | block; switch: none, and no flag file is read (D24). Subagent stops only (agent_id present). The role is Claude Code's record of the agent: another role exits 0, and an agent it records no role for is judged only when its own dispatch obligation names role qa. A dispatch that carries an obligation is judged only on the qa-report.v2 that obligation declares, at its declared path; a QA dispatched without one, whose agent-index entry binds it to a cycle's registry (no such registry: exit 0), is judged on the `docs/dev/qa-report-*.json` files its own transcript shows it wrote, and writing none exits 2 unless the session's do-report declares qa-report expected-absent; exits 2 (E2E_ENFORCE_BLOCKED) when that report is missing, its e2e_enforcement is absent or malformed, or its status is skipped_without_justification or outside the qa-report.v2 vocabulary (performed, ran, legitimately_skipped and blocked_app_unavailable pass); a dispatch declaring no such report (BA validation, close QA, another role) and any internal error exit 0 | hooks/subagentstop-e2e-enforce.py:1 @9f4acd03 | hooks/tests/test_e2e_enforce.py |
| R-024 | H-092 | g2-artifact-contract (refuse) | hooks/subagentstop-artifact-contract-enforce.py | * | subagent | open | none | G2; block under CLAUDE_OBLIGATION_STOPGATE=block, which the shipped settings.json sets (a process env without the key takes it from the harness home's settings.json env). Subagent stops only (agent_id present). Obligation path: exits 2 on a failed obligated artifact, on a dev report whose file lists differ from the files Claude Code recorded the dev writing (P6 A3.a), on a live harness hook or script the producer's own Write or Edit left uncompilable (P6 F3.a), and on an obligation naming another role than the one Claude Code runs the agent as (role_mismatch); that role_mismatch refusal is released at the agent's next stop (stop_hook_active) when its own transcript shows it wrote none of the files that obligation declares (no Write or Edit of one, and none that another of its calls, a Bash heredoc, tee or cp, changed since its dispatch), while an agent that wrote one stays refused, the refusal naming the file; under =advisory, or with the key unset in both, each failing obligated artifact's path and check are printed on stderr (OBLIGATION_STOPGATE_ADVISORY) and the stop is allowed; under =off nothing is read or judged. An exception inside the obligation path is named on stderr (OBLIGATION_STOPGATE_FAULT) and the declared-report check decides the stop. Declared-report check (reached when the agent's own obligation does not resolve, or on that fault; an agent the dev registry does not resolve is never blocked): blocking when ARTIFACT_CONTRACT_ENFORCE_MODE is unset (the default), exits 2 when a json report the agent's own dispatch declares (read as declared even when its block fails the grammar) declares report_version but fails its schema; under =advisory prints the same reason on stderr (ARTIFACT_CONTRACT_ADVISORY) and allows; a missing report never blocks; writes nothing P13-1 R1, R2 (D28, D29): a BA dispatch's fresh, schema-valid, not yet asked next round file stands in for its declared artifacts; a declared round file is held to `requirement_round.check_round` (task, round order, four dimensions without a spec, no answered question again, the code-token lint, assume, the BA panel's verified root causes) and BA's `context.v1` to `check_analysis` (every answered question in `requirement.contract_refs`, every unanswered one in `assumptions`). | hooks/subagentstop-artifact-contract-enforce.py:772 @4ffb9279 | hooks/tests/test_artifact_contract_enforce.py, hooks/tests/test_g2_harness_syntax.py |
| R-025 | H-092 | cp-pending (refuse) | hooks/subagentstop-cp-enforce.py | * | subagent | open | none | block under CP_ENFORCE_MODE=block, which the shipped settings.json sets: a stopping subagent whose own running cp-state slot has a pending checkpoint exits 2; another agent's slots are not judged; off when CP_ENFORCE_MODE is unset (the default) or holds any other value: it exits 0 and prints nothing; any error exits 0 | hooks/subagentstop-cp-enforce.py:4 @4ffb9279 | hooks/tests/test_cp_enforce_own_slot.py, hooks/tests/test_subagentstop_cp_enforce.py |
| R-026 | H-092 | restart-track (observe) | hooks/subagentstop-restart-track.py | * | subagent | open | none | advisory; switch: none. Observer, exits 0 on every path: records the response evidence /restart reads for a resumed agent (lib/subagent_restart.observe_subagent_stop), whatever the rules above decided; prints nothing, since at SubagentStop output that reaches the model keeps the subagent running | hooks/subagentstop-producer-gate.py:42 @4ffb9279 | tests/test_restart_command.py |

---

## 4. Enforcement subjects that are not a single wired hook

| row_id | subject | behavior | exercise_status | proof_layer | citation | verifying_test | result |
|---|---|---|---|---|---|---|---|
| S-001 | black-box-tests-against-real-Claude-Code-builds | unsupported | unexercised | none | docs/ENFORCEMENT-LEDGER.md:1 @4c33f2f5 | none yet | unsupported |
| S-002 | permission-layer-git-backstop | unsupported | unexercised | source-level | settings.json:1 @4ffb9279 | none yet | unsupported |
| S-003 | destructive-reset-gate-regex-backstop | advisory | exercised | component-tested | hooks/pretool-bash-safety.sh:2089 @4ffb9279 | hooks/tests/test_blackbox_integration.py | component-tested |
| S-005 | stop-coordinator-phase-coverage:stop-spec-coverage-enforce.py | advisory | unexercised | source-level | hooks/stop-spec-coverage-enforce.py:1 @eba87f69 | none yet | source-level |
| S-006 | stop-coordinator-phase-auto_commit:auto-commit.sh | advisory | unexercised | source-level | hooks/auto-commit.sh:1 @eba87f69 | hooks/tests/test_stop_checkpoint_refusal.py | source-level |
| S-007 | stop-coordinator-phase-cleanup:stop-cleanup-allowlist.sh | advisory | unexercised | source-level | hooks/stop-cleanup-allowlist.sh:1 @eba87f69 | none yet | source-level |
| S-008 | stop-coordinator-phase-completion:stop-command-gate.py | advisory | unexercised | source-level | hooks/stop-command-gate.py:1 @eba87f69 | hooks/tests/test_stop_command_gate.py | source-level |
| S-009 | command-script:resolve-dev-artifact-chain.py | advisory | unexercised | source-level | scripts/resolve-dev-artifact-chain.py:1 @4ffb9279 | none yet | source-level |
| S-010 | command-script:execute-push.py | advisory | unexercised | source-level | scripts/execute-push.py:1 @4ffb9279 | none yet | source-level |
| S-011 | command-script:push.sh | advisory | unexercised | source-level | hooks/push.sh:1 @4ffb9279 | none yet | source-level |
| S-012 | command-script:merge.sh | advisory | unexercised | source-level | hooks/merge.sh:1 @4ffb9279 | none yet | source-level |
| S-013 | command-script:write-commit-grant.py | advisory | unexercised | source-level | scripts/write-commit-grant.py:1 @4ffb9279 | none yet | source-level |
| S-009 | requirement-round-text-question:stop-command-gate.py | detected | exercised | component-tested | hooks/stop-command-gate.py:652 @b74f9720 | hooks/tests/test_stop_command_gate.py | component-tested |
| S-010 | requirement-round-code-token-lint:subagentstop-artifact-contract-enforce.py | detected | exercised | component-tested | hooks/lib/requirement_round.py:30 @b74f9720 | hooks/tests/test_requirement_round.py | component-tested |
| S-011 | low-score-extra-round:stop-command-gate.py | detected | exercised | component-tested | hooks/lib/score_view.py:49 @a959bcec | hooks/tests/test_score_view.py | component-tested |

- **S-001** — no CI harness for actual Claude Code CLI builds exists in this environment or
  session. There is no build matrix to run against. This row is the disclosure of that gap.
- **S-002** — `settings.json @4ffb9279` carries **80** `permissions.deny` rules, of which 3 are
  git-related (`Bash(git push --force:*)`, `Bash(git push -f:*)`, `Bash(git reset --hard:*)`),
  and `permissions.ask` is empty; at `@4c33f2f5` the same three were `ask` rules beside 96 deny
  rules, none git-related. All three are **prefix-anchored** and therefore match no wrapped or
  redirected form. There is no permission-layer backstop behind the hook layer for this class.
  Outside this class, `permissions.deny` carries a `Skill(<stem>:*)` entry for each human-only
  command, and `hooks/tests/test_skill_deny_coverage.py` requires one for every `commands/*.md`
  stem outside CONTROL that no harness text calls through the Skill tool. `Skill(codex:*)` is
  not denied, by decision (P5): agents and `/close`, `/commit`, `/do` call `Skill(skill="codex")`
  under `--codex`, and `subagentstop-codex-enforce.py` (R-022, run by the producer gate H-092)
  requires the ledger entry that call's PostToolUse (H-050) writes.
- **S-003** — see `docs/THREAT-MODEL.md` RISK-3. This gate's regex fallback is *mutually
  exclusive* with its classifier branch, so an input the classifier parses successfully but
  finds no git in suppresses its own backstop.
- **S-009** — P13-1 R7 (D28): in a `/spec`, `/dev`, `/redev` or `/dev-command` span whose loaded text or checklist
  asks the requirement round, a Stop whose last main-agent text (the Stop payload's `last_assistant_message`, else
  the span's last assistant text) ends with `?` or `？` on its last non-empty line is the gap `<command>: the turn ends
  with a question in text; ask it with AskUserQuestion, or end without it.` `/spec` is checked for this gap only and
  stays out of `GATED_COMMANDS`; a `/close` span is not checked. The gate still writes nothing; asking with
  AskUserQuestion, or ending without the question, clears it.
- **S-010** — P13-1 R1 (D18): the code-token lint in `requirement_round.check_round` refuses a round whose question,
  header or option holds a backtick, a path with an extension, `()` or `::`. **Its real strength is a lint: it
  catches code tokens only.** A technical choice written in plain words passes it; the prompts' product-level
  examples and BA's instructions are what keep such a question out, not this check.
- **S-004 – S-008** — the `Stop` phases that `hooks/stop-workflow-coordinator.py` runs itself,
  in the fixed order its `PHASE_ORDER` declares: `coverage`, `auto_commit`, `completion`,
  `cleanup`. S-004 – S-007 were previously registered-hook rows H-060 – H-063 (event class `Stop`,
  matcher `(universal)`, mode/precondition `none`), matching the direct `Stop` entries of the
  since-retired settings template; `settings.json` wires none of them, nor since P5 the
  coordinator itself, as a direct `Stop` entry, so none of them is an
  `(event_class, matcher, hook)` triple and `--claims` rejects a registered-hook row for any of
  them. **S-004 is retired and not reused:** P5 deleted the `timelock` phase;
  `stop-overnight-timelock.py` is a tracked exit-0 stub, and the overnight time-lock is the
  completion phase's (S-008). How the phases run, from the coordinator source: `stop-launch.py`
  (registered-hook row H-088) runs the coordinator, and a session that loaded an older hook list
  runs it directly; each phase is a child process that receives the `Stop` payload on stdin, with
  `LANEB_COORDINATED_STOP=1` added to its environment; no phase runs when the payload carries an
  `agent_id` or no `session_id`; `LANEB_COORDINATOR_PHASES_JSON` may replace the phase commands
  (exit 2 if malformed or reordered); resource finalisation runs only when both
  `LANEB_SESSION_RESOURCE_TRUST_KEY` and `LANEB_SESSION_RESOURCE_TRUST_ROOT` are set, and no phase
  receives either key. Only `coverage` and `completion` may block: exit 2 ends the run and the
  coordinator exits 2, relaying a coverage block as `failed_phase=coverage` and the last 4 KB of
  its stderr, and a completion block as the gate's own text, whole. An `auto_commit` or `cleanup`
  failure — another non-zero exit, a timeout (30 s; 120 s for `auto_commit`, 60 s for
  `completion`; 240 s in all, under the launcher's 280 s), a launch error or a missing script —
  is recorded in the coordinator's result JSON and allowed. `CLAUDE_COMMAND_GATE` is read from
  the process environment only, never from a settings file: `off` skips `completion`, and the
  time-lock with it; any other value, or none, runs it in block mode when the launcher started the
  coordinator (it marks the coordinator it runs with `CLAUDE_STOP_LAUNCHER=1`). A coordinator run
  directly, unmarked — a session that loaded the hook list from before P5 — runs `completion`
  advisory (`would block` on stderr, exit 0) and still blocks an open overnight window (P5's
  arming option 1, decided by `tests/replay/test_live_arming.py`). Per phase, from each
  script's own source at `@eba87f69`:
  - **S-005 `coverage`** (`stop-spec-coverage-enforce.py`): a tracked exit-0 `# STUB:` file since
    P1b that reads nothing and decides nothing; the `/spec` split's coverage is decided at the
    spec subagent's own stop (R-024). The coordinator would relay an exit 2 from it as a block;
    the stub never exits 2.
  - **S-006 `auto_commit`** (`auto-commit.sh`): writes a `refs/checkpoints/<branch>` snapshot when
    the working tree is dirty. It runs before `completion`, so a Stop the gate blocks still writes
    its snapshot. A snapshot the library refuses (the private-literal rule, the settings check or
    the settings clean filter; nothing written) is reported as the one line
    `Checkpoint snapshot refused by <rule>: nothing written, see logs/checkpoint.log` in a JSON
    `systemMessage` the coordinator shows as its own (the launcher relays its stdout), and the
    Stop is allowed; the PostToolUse checkpoint hook (H-057) reports its own refused snapshot the
    same way. That the host shows this notice to the user is documented
    (code.claude.com/docs/en/hooks, read 2026-11-01: `systemMessage`, "Warning message shown to
    the user", with no exception in the `Stop` or `PostToolUse` section), and emitted end to end
    in the sandbox; not observed on a harness host (no owner step). Its exit 1 on any other
    failed checkpoint is recorded in the coordinator's result JSON and in `logs/checkpoint.log`,
    and the Stop is allowed.
  - **S-007 `cleanup`** (`stop-cleanup-allowlist.sh`): exits 0 on every path. It runs last, and
    only on a Stop that `coverage` and `completion` allow (an `auto_commit` failure included), so a
    blocked Stop keeps its `/allow` grants; its own header comment ("Registered LAST in Stop hooks
    array so earlier hook failures do not block cleanup") describes the former direct
    registration, not this sequencing.
  - **S-008 `completion`** (`stop-command-gate.py`): the one Stop gate for every gated command
    (`hooks/lib/stop-commands.json`: `/do`, `/dev`, `/redev`, `/dev-command`, `/dev-overnight`,
    `/close`, `/commit`, `/merge`, `/push`). It allows a subagent's Stop (`agent_id`) and mode
    `off`; it holds the overnight time-lock in any span, for the stopping session's own
    `<main root>/.claude/overnight-state-<session_id>.json` (`hooks/lib/overnight.py`'s one
    locator): exit 2 while its window is open (`window_open`: end time ahead, no human-typed
    `/stop` since the session's `/dev-overnight`; no state field releases it); after `end_time`
    with `overnight.closeout_gaps` empty, or the owner's `/stop`, while the wake's `CronCreate`
    has no later `CronDelete`;
    it allows when the active span is neither a gated command's nor a `/spec` one (only a human-typed harness command
    outside CONTROL opens or replaces a span, never a Skill expansion, a scheduled prompt or a
    wakeup; a plain prompt continues it); else it exits 2 with
    `COMMAND_GATE /<command>: not complete` and one line per gap (the todo half and the
    command's predicate: the dev chain's disposition per family, `/dev-overnight`'s closeout
    after `end_time` (`overnight.closeout_gaps`: no PM retrospective report, or no non-empty
    overnight summary written since `start_time`), the hook-minted
    `/do` task's do-report with lists equal to its write set, close and commit stages, git facts
    for `/merge` and `/push`), an exception being the gap
    `gate instrument failure: <type>: <message>`. It writes no file and keeps no count; the next
    compliant step clears each gap, and the human's `/stop` opens a span that is not gated. A
    completion failure (exit outside {0, 2}, a timeout, a launch error, a missing file) is decided
    by the coordinator's stdlib fallback on the transcript reader: an open overnight window, or a
    gated latest human-typed command in block mode, exits 2 with `COMMAND_GATE instrument
    failure: <reason>. The gate is broken; the human can type /stop`; anything else is recorded
    and allowed. When resource finalisation runs, the coordinator alone publishes the overnight
    terminal receipt, from the terminal time-lock status the gate prints on an allowed Stop.
- **S-009 – S-013** — scripts a command's text runs, not hooks: each refuses only by its exit
  status, which the command then acts on, so none refuses a pending tool call by itself, and
  none has a switch.
  - **S-009** (`scripts/resolve-dev-artifact-chain.py`): read-only; exits 0 when the chain rooted
    at `docs/dev/dev-report-<task-id>.json` is complete and valid, and 2 on invalid arguments or a
    missing, stale, mismatched or ambiguous chain; its `disposition` stage exits 0 whenever it
    computed one and 1 on an instrument failure. /dev completion, /close, Close QA and /commit
    read its one JSON document.
  - **S-010** (`scripts/execute-push.py`): in one process it validates the push-analyst grant,
    consumes it, writes the chain-B sentinel and execs `hooks/push.sh`; it exits 1 on a failed
    validation, HEAD drift, a blocked verdict or a failed consume, and 2 on an infrastructure
    failure (no session id, `push.sh` missing, a failed exec or chdir).
  - **S-011** (`hooks/push.sh`): exits 1 without a fresh (60 s) chain-B sentinel whose fields
    match the push, or with a FAIL or malformed one, before any `git push`; a dirty working tree
    does not block (an informational line), since only committed commits are pushed.
  - **S-012** (`hooks/merge.sh`): runs `git merge` in its own process, which no PreToolUse hook
    sees, after /merge checked the merge-analyst's grant; it refuses a self-merge, keeps the
    clean-tree and untracked-overlap preconditions on every ref shape, and enforces the
    post-merge invariant before any cleanup (exit 1 or 2).
  - **S-013** (`scripts/write-commit-grant.py`): writes the single-use /commit grant manifest
    (task_id, sid, nonce, repo_root, branch, expected_head, created_at, expires_at) that
    `pretool-git-privilege-guard.py` (H-031) consumes; it exits 2 when it has no session id or
    cannot resolve the repository, branch or HEAD the grant binds.

---

## 5. Per-release compatibility ledger

Keyed by (release/tag, Claude Code build, OS/runtime, commit, date, CI workflow-run link,
result). The release-key column is checked against an **enumerable inventory** — `git tag -l`
unioned with `CHANGELOG.md` release headings — so a release cannot be quietly omitted. A release
whose build or evidence is unknown is recorded explicitly as `unsupported`, never dropped.

| row_id | release_key | claude_code_build | os_runtime | commit | date | workflow_run_link | result |
|---|---|---|---|---|---|---|---|
| C-001 | Unreleased | 2.1.220 | Linux 6.8.0-117-generic x86_64 / Python 3.12.3 | 4c33f2f5 | 2026-08-03 | not-run | unsupported |
| C-002 | 1.0.0 | unknown | unknown | untagged | 2026-07-05 | not-run | unsupported |

- **C-001** is the exact current environment, measured this cycle (`claude --version` →
  `2.1.220 (Claude Code)`; `uname -srm` → `Linux 6.8.0-117-generic x86_64`; `python3 --version`
  → `Python 3.12.3`; harness commit `4c33f2f5`). HEAD is **not** a release, so its release key
  is `Unreleased`. The build identifier is knowable today and omitting a knowable fact from a
  hostile-reader document would itself be a defect — but **recordable is not passing**: no
  host-observed evidence exists for this combination, so the result is `unsupported`.
- **C-002** is declared by `CHANGELOG.md` (`## [1.0.0] - 2026-07-05`). `git tag -l` returns
  **zero** tags, so no commit is resolvable for it and its build/OS are `unknown`.
- **No row may claim a pass without a linked workflow-run artifact.** A passing result with an
  empty link field exits the ledger gate non-zero.

### 5.1 Supported-build policy

The definition below is a **project-local** policy statement with **no upstream** reference: no
official Claude Code event/blocking-semantics documentation was fetched or cited while writing
it, and that missing reference is recorded here as an **open dependency** rather than implied to
exist. Any reader treating it as an upstream compatibility guarantee is being misled by this
document, and that is the failure mode this paragraph exists to prevent.

**Project-local definition.** A Claude Code build is *supported* by this harness when a CI
workflow run has executed the corpus suite against it and published the resulting manifest as an
artifact. By that definition, **this project currently supports zero builds** — including the
one it is running on. Every row in §5 is therefore `unsupported`.

### 5.2 Known host-environment limits recorded this cycle

These are recorded here because they bound what any compatibility claim above can mean.

1. **A host-capability handshake exists but is inert on this host.** A sibling lane built a full
   capability-handshake mechanism, but it could register **nothing** in the live settings or in
   the settings template, because its wired-hook count is asserted against two documentation
   files that lane does not own. Its artifacts are present and its aggregate correctly reports
   an **unprotected** state, with the strict doctor exiting non-zero. Present-but-inert is not
   the same as absent, and it is not the same as working; the ledger records the third state.
2. **The settings template has been retired; the tracked `settings.json` is the single settings
   source.** When this item was recorded at `@4c33f2f5`, the live settings file had diverged from
   a separate template: running the settings renderer against `settings.json` silently re-added
   2 `deny` entries and stripped roughly 38 `allow` entries, while the hook *set* was measured
   identical between the two files, 70 of 70 `(event, matcher, hook)` triples — a one-time
   measurement, not a standing guarantee. The standing check of that time was weaker:
   `scripts/verify-claims.sh` confirmed only that every hook script *basename* wired by
   `settings.json` also appeared in the template, without comparing lifecycle event or matcher.
   That template and that basename check (the script's former step 5) have since been retired.
   The standing wiring check is now `--claims` step 7, which compares the full
   `(event_class, matcher, hook)` triple set of the checked-out `settings.json` against section 3
   in both directions, so a hook moved to a different event or matcher fails it. Reconciling the
   rows against `settings.json @ef6e9037` added H-073 – H-086 and moved H-060 – H-063 to section 4
   as S-004 – S-007; reconciling them against `@4ffb9279` (P12's merged gates) added H-089 – H-092
   and moved the merged hooks' decisions to section 3.1. Neither check covers the **permission**
   surface, so S-002's permission-layer measurement is re-measured by hand and pinned to the
   revision it was read at.

---

## 6. Published token sets

These are claims about the code, and `--claims` re-derives them from source on every run. Any
widening or narrowing changes the size of the residual class described in `docs/THREAT-MODEL.md`
RISK-3 even when every probed form still behaves exactly as recorded, so drift must fail loudly
rather than silently outdate the published table.

Each token set below is published inside an **anchored region**, and `--claims` matches the
recorded tokens against that region only. Matching them anywhere in the document would be
vacuous: `>` opens every blockquote line and `<` opens every HTML comment, so two of the seven
redirection operators were previously satisfied by unrelated prose and could never be reported
missing.

<!-- published-tokens:wrapper:begin -->
- **`_WRAPPERS` @4c33f2f5** (`hooks/lib/git_command_classifier.py:105-108 @4c33f2f5`), 19 tokens:
  `sudo`, `doas`, `env`, `xargs`, `time`, `nohup`, `setsid`, `stdbuf`, `ionice`, `command`,
  `builtin`, `nice`, `exec`, `eval`, `timeout`, `flock`, `chrt`, `taskset`, `unbuffer`.
<!-- published-tokens:wrapper:end -->
<!-- published-tokens:leading-redirection:begin -->
- **Leading-redirection operators** covered by the published matrix, 7 tokens:
  `2>/dev/null`, `>`, `>>`, `<`, `2>&1`, `&>`, `1>`.
<!-- published-tokens:leading-redirection:end -->
- **Boundary moved 2026-09-03.** The last seven wrapper tokens above were added
  together with three new constructs in the same module — a shell-reserved-word
  prefix set, a leading-redirection matcher, and a per-wrapper value-flag table.
  Together they closed the wrapper-with-flag, leading-redirection and
  reserved-word residual cells: witnesses W4–W11 moved from `MISS` to
  `detected`. The reserved-word family (`if ! git …`, `then git …`, `do git …`)
  had never been published as a cell at all, because the matrix was built from
  the wrapper/redirection axis and no one had probed a keyword prefix.
- **Gate-architecture census @4c33f2f5**: **1** classifier-exclusive fallback guard
  (architecture A — the only shape the empty-parse suppression affects), **2** unconditional
  `GIT_CMD_RE` branches (architecture B), and **8** classifier-only path-qualified augmentation
  branches (architecture C, which never carried a regex fallback to lose). All three are
  counted and regression-guarded. Publishing only A and B would be a cherry-picked census:
  a reader counting classifier-consuming branches in that guard finds 11, not 3.
  **The reach of that regression guard, stated rather than implied**: the census is derived by
  a shell-aware structural pass that canonicalizes `[`, `[[` and `test` predicates — quoting,
  `$X` versus `${X}`, `${X:-default}`, operand order and negation are all normalized, so a
  respelled guard is still counted — and it ignores whole-line comments so a commented-out
  guard cannot hold the count up. It recognizes gates written as `if`/`elif` arms. A gate
  expressed through a construct the pass does not model — a `case` arm, or a decision reached
  inside a function it does not inline — would not be counted. That is a bounded, disclosed
  limit of this census, not a claim of exhaustiveness over all shell.

---

## 7. Evidence claims resting on internal sources only

Every claim in this document is `tier_2_verified` against this repository's own code and
configuration — read, greped, parsed or executed in-tree this cycle. Only one also rests on an
official Claude Code source: S-006's `systemMessage` notice cites code.claude.com/docs/en/hooks,
read 2026-11-01, and is not host-observed either. Specifically
unverified against upstream: the meaning of each lifecycle event class, whether the host honors
a non-zero hook exit code, and what a "supported build" means to the vendor. Those three are the
load-bearing gaps between this ledger and a genuine enforcement guarantee, and they are named
rather than papered over.

---

*Only `event_class`, `matcher` and `hook` are derived from `settings.json`; the other seven
registered-hook columns are authored in this ledger. Verified by
`scripts/check-enforcement-evidence.py --ledger` and `--claims`, both wired into
`scripts/verify-claims.sh` and thus into the required `baseline` CI job.*
