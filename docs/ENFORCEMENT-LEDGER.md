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
the checked-out `settings.json` (the row set was last reconciled against `@2a806c79`) by
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

**On falsifiability.** 76 of the 78 registered-hook rows carry `proof_layer: source-level`, which
as section 1.3 defines it means those rows rest on **reading the code rather than running it**;
the remaining 2 carry `component-tested` and none carry `host-observed` or `host-shaped`. The gate validates
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
failure, not a statement that a value is absent.**

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
verbatim. Under that definition `settings.json @4c33f2f5` dispatches **16** PreToolUse hook
commands for `tool=Bash` — 10 from matchers naming `Bash` explicitly and 6 from
universal/empty matchers. A sibling lane reports "all 11 Bash PreToolUse hooks" under a
narrower definition. Neither count is adopted silently; the definition is stated so the two can
be reconciled rather than argued.

---

## 3. Registered-hook rows

All **nine** lifecycle event classes are represented. The tracked `settings.json` wires 9 event
classes / 50 matchers / **78 hook commands**, and there are exactly 78 rows below: 64 recorded
`@4c33f2f5`; H-071 records the later `PostToolUseFailure` registration and H-072 a later
`PostToolUse` one; H-073 – H-086 record the hooks the tracked `settings.json @ef6e9037` wires that
the ledger did not list before; H-087 records the close-rating `PostToolUse` registration (P4)
and H-088 the one `Stop` entry P5 wires. Ids H-060 – H-063 are retired and not reused: those
four scripts were never direct `Stop` entries in `settings.json` — they were the phases of
`stop-workflow-coordinator.py` — so they are recorded in section 4 as S-004 – S-007 (S-004
retired in P5).
Id H-081 is retired as well: `stop-completion-gate.py` lost its `Stop` entry in P1 and is an
exit-0 stub that stays tracked. Ids H-052 and H-053 are retired too: `posttool-todo-count.py` and
`posttool-todo-sequence.py` left the `PostToolUse` `TodoWrite` group in P5 and are exit-0 stubs;
`pretool-todo-validate.py` (H-037) decides their rules before the call runs. Ids H-082 – H-084 are
retired in P5: the `Stop` group is one entry, `stop-launch.py` (H-088), which runs
`stop-workflow-coordinator.py`, whose completion phase is `stop-command-gate.py` (section 4,
S-008). `stop-do-report-gate.py` and `stop-obligation-gate.py` left the group and are exit-0 stubs
(the gate decides a `/do` task's report), and the coordinator is no longer a direct `Stop` entry.

**The authoring rule `behavior` follows** — applied by hand, and checked only for closed-set
membership, not recomputed from the event class: events that can deny a pending action
— `PreToolUse`, `UserPromptSubmit`, `Stop`, `SubagentStop` — are `advisory`, because they are
deny-*capable* but their prevention has not been observed on a host. Events that fire after the
fact or carry no veto — `PostToolUse`, `PostToolUseFailure`, `SessionStart`, `SessionEnd`,
`Notification` — are `detected`.

| row_id | event_class | matcher | hook | mode/precondition | behavior | exercise_status | proof_layer | citation | verifying_test |
|---|---|---|---|---|---|---|---|---|---|
| H-001 | SessionStart | (universal) | canary-verify.sh | none | detected | unexercised | source-level | scripts/canary-verify.sh:1 @4c33f2f5 | none yet |
| H-002 | SessionStart | (universal) | check-todo-md-sync.py | none | detected | unexercised | source-level | hooks/check-todo-md-sync.py:1 @4c33f2f5 | none yet |
| H-003 | SessionStart | (universal) | session-git-init.sh | none | detected | unexercised | source-level | hooks/session-git-init.sh:1 @4c33f2f5 | none yet |
| H-004 | SessionStart | (universal) | session-gitignore-propagate.sh | none | detected | unexercised | source-level | hooks/session-gitignore-propagate.sh:1 @4c33f2f5 | none yet |
| H-005 | SessionStart | (universal) | session-info.sh | none | detected | unexercised | source-level | hooks/session-info.sh:1 @4c33f2f5 | none yet |
| H-006 | SessionStart | (universal) | session-promote-hook.sh | none | detected | unexercised | source-level | hooks/session-promote-hook.sh:1 @4c33f2f5 | none yet |
| H-007 | SessionStart | (universal) | session-tmpfs-banner.sh | none | detected | unexercised | source-level | hooks/session-tmpfs-banner.sh:1 @4c33f2f5 | none yet |
| H-008 | UserPromptSubmit | (universal) | prompt-workflow.py | none | advisory | unexercised | source-level | hooks/prompt-workflow.py:1 @4c33f2f5 | none yet |
| H-009 | UserPromptSubmit | (universal) | userprompt-bulk-commit-capability.py | none | advisory | unexercised | source-level | hooks/userprompt-bulk-commit-capability.py:1 @4c33f2f5 | none yet |
| H-010 | UserPromptSubmit | (universal) | userprompt-consent-allowlist.sh | none | advisory | unexercised | source-level | hooks/userprompt-consent-allowlist.sh:1 @4c33f2f5 | none yet |
| H-011 | UserPromptSubmit | (universal) | userprompt-doc-sync-check.py | none | advisory | unexercised | source-level | hooks/userprompt-doc-sync-check.py:1 @4c33f2f5 | none yet |
| H-012 | UserPromptSubmit | (universal) | userprompt-restart-authorize.py | none | advisory | unexercised | source-level | hooks/userprompt-restart-authorize.py:1 @4c33f2f5 | none yet |
| H-013 | UserPromptSubmit | (universal) | userprompt-tmpfs-pressure.sh | none | advisory | unexercised | source-level | hooks/userprompt-tmpfs-pressure.sh:1 @4c33f2f5 | none yet |
| H-014 | PreToolUse | (universal) | pretool-block-background-tasks.py | none | advisory | unexercised | source-level | hooks/pretool-block-background-tasks.py:1 @4c33f2f5 | none yet |
| H-015 | PreToolUse | (universal) | pretool-orchestrator-gate.py | none | advisory | unexercised | source-level | hooks/pretool-orchestrator-gate.py:1 @4c33f2f5 | none yet |
| H-016 | PreToolUse | (universal) | pretool-read-size-guard.py | none | advisory | unexercised | source-level | hooks/pretool-read-size-guard.py:1 @4c33f2f5 | none yet |
| H-017 | PreToolUse | (universal) | pretool-subagent-enforce.py | none | advisory | unexercised | source-level | hooks/pretool-subagent-enforce.py:1 @4c33f2f5 | none yet |
| H-018 | PreToolUse | (universal) | pretool-workflow-gate.py | none | advisory | unexercised | source-level | hooks/pretool-workflow-gate.py:1 @4c33f2f5 | none yet |
| H-019 | PreToolUse | (universal) | pretool-worktree-guard.sh | none | advisory | unexercised | source-level | hooks/pretool-worktree-guard.sh:1 @4c33f2f5 | none yet |
| H-020 | PreToolUse | * | pretool-tool-policy.py | every caller, the main agent included: a write, delete or rename of a protected file (the harness home's settings.machine.json, private-literals.txt, scripts/check-public-core.sh, scripts/install/render-settings, hooks/git-hooks/pre-commit, .git/config, .git/hooks/, .gitattributes; a session transcript or its subagent meta; a /do task sidecar) exits 2, as does a ScheduleWakeup prompt typing a harness command outside CONTROL; a Write, Edit, MultiEdit or NotebookEdit target or Bash write target that another dispatch of the session declares (its obligation's artifacts, the producer question it may write, its template's declarations) exits 2, naming the path, the declaring role and "only <role> writes this artifact (D8)"; a Write, Edit, MultiEdit or NotebookEdit target or Bash write target under `<state dir>/agentic-commit/<name>/` (the push- and merge-analyst grants, `<name>` a role the policy lists) exits 2 for any caller but `<name>` (grant binding, D8); a subagent whose role resolves to a role the policy lists also takes that role's rows of policies/tool-policy.v1.json and exits 2 on a denied tool or path; a deny-logic import failure exits 2; an unresolved role, a role the policy does not list (Explore, Plan, general-purpose, a plugin's) and any other internal error exit 0 | advisory | unexercised | source-level | hooks/pretool-tool-policy.py:1 @eba87f69 | hooks/tests/test_tool_policy_derived_permission.py, hooks/tests/test_tool_policy_protected_paths.py |
| H-021 | PreToolUse | Agent | pretool-aggregate-check.py | G3, armed by the shipped settings.json (CLAUDE_OBLIGATION_BARRIER=block): a qa dispatch (Agent or Task) exits 2 in every mode while every lane of a fan-out in its scope (the task its own obligation names) has reported and the canonical aggregate dev-report is missing, and exits 0 under the session's /do consent or, from the main agent, an /allow grant for Agent; the lane-roster and parallel_workers checks, the canonical-validity check, the obligation barrier (a prior dispatch's declared artifact of the same task family missing or invalid at a later dispatch that does not declare it again) and the gitignore rule exit 2 under =block; under =advisory or with the key unset the barrier prints each finding it would block on stderr (OBLIGATION BARRIER ADVISORY) and the canonical-validity check a warning, and the dispatch proceeds; =off also skips the barrier; writes nothing; internal errors exit 0 | advisory | unexercised | source-level | hooks/pretool-aggregate-check.py:1 @98e41855 | tests/test_aggregate_dev_report.py |
| H-022 | PreToolUse | Agent | pretool-bisect-gate.sh | none | advisory | unexercised | source-level | hooks/pretool-bisect-gate.sh:1 @4c33f2f5 | none yet |
| H-023 | PreToolUse | Agent | pretool-gitignore-preflight.py | none | advisory | unexercised | source-level | hooks/pretool-gitignore-preflight.py:1 @4c33f2f5 | none yet |
| H-024 | PreToolUse | Agent | pretool-layer-escalation-check.sh | none | advisory | unexercised | source-level | hooks/pretool-layer-escalation-check.sh:1 @4c33f2f5 | none yet |
| H-025 | PreToolUse | Agent | pretool-orchestrator-prompt-purity.py | none | advisory | unexercised | source-level | hooks/pretool-orchestrator-prompt-purity.py:1 @4c33f2f5 | none yet |
| H-026 | PreToolUse | Agent | pretool-spec-block-foreground-agent.py | none | advisory | unexercised | source-level | hooks/pretool-spec-block-foreground-agent.py:1 @4c33f2f5 | none yet |
| H-027 | PreToolUse | Bash | pretool-bash-safety.sh | no mode or precondition. Since P5 its hard ban reads a listed name merely after `(`, `;`, `\|`, `!` or `&` inside quoted data as text unless a word outside quotes can run text, its commit guard keeps single-quoted text beside a trailing `# comment` or a `$'..'` word as data, and a local keystone `git config` write from the harness home naming another repository by a literal absolute `-C`, `--git-dir` or `GIT_DIR` passes; a called alias whose value `--config-env` takes from the environment, a double-quoted `bash -c` or `eval` string inside a double-quoted `$(...)`, and commit or config text nested past the scanner's depth bound exit 2 (commit-hook-bypass, fail closed) | advisory | exercised | component-tested | hooks/pretool-bash-safety.sh:1657 @4c33f2f5 | hooks/tests/test_blackbox_integration.py |
| H-028 | PreToolUse | Bash | pretool-bash-views-guard.py | none | advisory | unexercised | source-level | hooks/pretool-bash-views-guard.py:1 @4c33f2f5 | none yet |
| H-029 | PreToolUse | Bash | pretool-block-branch-pr-worktree.py | none | advisory | unexercised | source-level | hooks/pretool-block-branch-pr-worktree.py:1 @4c33f2f5 | none yet |
| H-030 | PreToolUse | Bash | pretool-bulk-commit-detector.py | none | advisory | unexercised | source-level | hooks/pretool-bulk-commit-detector.py:1 @4c33f2f5 | none yet |
| H-031 | PreToolUse | Bash | pretool-git-privilege-guard.py | no mode or precondition. Since P5 a commit under a live `/commit` grant whose task_id is non-null exits 2 unless its whole message (the `-m`/`--message` values as git joins them, or the whole `-F`/`--file` regular file) carries the line `Task-id: <task_id>`; a message it cannot read exits 2; the bulk-commit route takes no such line | advisory | exercised | component-tested | hooks/pretool-git-privilege-guard.py:145 @4c33f2f5 | hooks/tests/test_blackbox_integration.py |
| H-032 | PreToolUse | Bash | pretool-grep-backtrack-guard.py | none | advisory | unexercised | source-level | hooks/pretool-grep-backtrack-guard.py:1 @4c33f2f5 | none yet |
| H-033 | PreToolUse | Bash | pretool-wrapper-userintent.py | none | advisory | unexercised | source-level | hooks/pretool-wrapper-userintent.py:1 @4c33f2f5 | none yet |
| H-034 | PreToolUse | Edit\|Write\|MultiEdit\|Bash | pretool-claude-config-guard.py | none | advisory | unexercised | source-level | hooks/pretool-claude-config-guard.py:1 @4c33f2f5 | none yet |
| H-035 | PreToolUse | EnterWorktree | pretool-block-enterworktree.sh | none | advisory | unexercised | source-level | hooks/pretool-block-enterworktree.sh:1 @4c33f2f5 | none yet |
| H-036 | PreToolUse | Read | pretool-cp-checkin.py | none | advisory | unexercised | source-level | hooks/pretool-cp-checkin.py:1 @4c33f2f5 | none yet |
| H-037 | PreToolUse | TodoWrite | pretool-todo-validate.py | none | advisory | unexercised | source-level | hooks/pretool-todo-validate.py:1 @4c33f2f5 | none yet |
| H-038 | PreToolUse | Write | pretool-write-guard.sh | none | advisory | unexercised | source-level | hooks/pretool-write-guard.sh:1 @4c33f2f5 | none yet |
| H-039 | PreToolUse | Write\|Edit\|MultiEdit | pretool-quality-gate.py | none | advisory | unexercised | source-level | hooks/pretool-quality-gate.py:1 @4c33f2f5 | none yet |
| H-040 | PreToolUse | Write\|Edit\|MultiEdit\|Bash\|AskUserQuestion | pretool-overnight-hook-guard.py | none | advisory | unexercised | source-level | hooks/pretool-overnight-hook-guard.py:1 @4c33f2f5 | none yet |
| H-041 | PreToolUse | Write\|Edit\|MultiEdit\|NotebookEdit\|Bash | pretool-cp-state-write-guard.py | none | advisory | unexercised | source-level | hooks/pretool-cp-state-write-guard.py:1 @4c33f2f5 | none yet |
| H-042 | PreToolUse | Write\|Edit\|NotebookEdit\|MultiEdit | pretool-subagent-code-block.py | none | advisory | unexercised | source-level | hooks/pretool-subagent-code-block.py:1 @4c33f2f5 | none yet |
| H-043 | PreToolUse | mcp__playwright__browser_run_code | pretool-runcode-watchdog.py | none | advisory | unexercised | source-level | hooks/pretool-runcode-watchdog.py:1 @4c33f2f5 | none yet |
| H-044 | PostToolUse | * | posttool-allowlist-consume.py | none | detected | unexercised | source-level | hooks/posttool-allowlist-consume.py:1 @4c33f2f5 | none yet |
| H-045 | PostToolUse | Agent | posttool-overnight-file-check.py | none | detected | unexercised | source-level | hooks/posttool-overnight-file-check.py:1 @4c33f2f5 | none yet |
| H-046 | PostToolUse | Agent | posttool-overnight-trace.py | none | detected | unexercised | source-level | hooks/posttool-overnight-trace.py:1 @4c33f2f5 | none yet |
| H-047 | PostToolUse | Agent | posttool-subagent-track.py | none | detected | unexercised | source-level | hooks/posttool-subagent-track.py:1 @4c33f2f5 | none yet |
| H-048 | PostToolUse | Bash\(git commit.*\) | posttool-git-warn.sh | none | detected | unexercised | source-level | hooks/posttool-git-warn.sh:1 @4c33f2f5 | none yet |
| H-049 | PostToolUse | SendMessage | posttool-restart-sendmessage.py | none | detected | unexercised | source-level | hooks/posttool-restart-sendmessage.py:1 @4c33f2f5 | none yet |
| H-050 | PostToolUse | Skill | posttool-codex-skill-ledger.py | none | detected | unexercised | source-level | hooks/posttool-codex-skill-ledger.py:1 @4c33f2f5 | none yet |
| H-051 | PostToolUse | TodoWrite | posttool-overnight-loop.py | acts only on a TodoWrite whose todos are all completed, for a session that owns an overnight state record (lib/overnight.py locate): while the time-lock window is open (window_open) it prints the continuation instructions (reset the todos, resume from Step 2), and once the window has closed a session-complete line; writes no state and never exits 2, so the todo reset is never blocked | detected | unexercised | source-level | hooks/posttool-overnight-loop.py:1 @63060b3b | hooks/tests/test_posttool_overnight_loop_terminal_gate.py |
| H-054 | PostToolUse | TodoWrite | posttool-todo-tracker.py | none | detected | unexercised | source-level | hooks/posttool-todo-tracker.py:1 @4c33f2f5 | none yet |
| H-055 | PostToolUse | Write\|Edit\|NotebookEdit\|MultiEdit | posttool-command-frontmatter-validate.py | none | detected | unexercised | source-level | hooks/posttool-command-frontmatter-validate.py:1 @4c33f2f5 | none yet |
| H-056 | PostToolUse | Write\|Edit\|NotebookEdit\|MultiEdit | posttool-doc-sync.py | none | detected | unexercised | source-level | hooks/posttool-doc-sync.py:1 @4c33f2f5 | none yet |
| H-057 | PostToolUse | Write\|Edit\|NotebookEdit\|MultiEdit | posttool-git-checkpoint.sh | acts only when the repository's pending files reach GIT_CHECKPOINT_THRESHOLD (default 10): writes a `refs/checkpoints/<branch>` snapshot through `hooks/lib/checkpoint-core.sh`; a snapshot the library refuses (nothing written) is reported as one JSON `systemMessage`, auto-commit.sh's refusal notice (S-006), as the hook's whole stdout; exits 0 on every path | detected | unexercised | source-level | hooks/posttool-git-checkpoint.sh:1 @10000fbd | hooks/tests/test_posttool_checkpoint_refusal.py |
| H-058 | PostToolUse | mcp__playwright__browser_run_code | posttool-runcode-watchdog.py | none | detected | unexercised | source-level | hooks/posttool-runcode-watchdog.py:1 @4c33f2f5 | none yet |
| H-059 | Notification | idle_prompt | notification-idle-overnight.py | exit-0 stub kept at its registered path: reads nothing, writes nothing (its idle log had no reader) and exits 0 on every path | detected | unexercised | source-level | hooks/notification-idle-overnight.py:1 @4c33f2f5 | none yet |
| H-064 | SubagentStop | * | pretool-layer-match-gate.sh | none | advisory | unexercised | source-level | hooks/pretool-layer-match-gate.sh:1 @4c33f2f5 | none yet |
| H-065 | SubagentStop | * | subagent-stop-diff-check.sh | none | advisory | unexercised | source-level | hooks/subagent-stop-diff-check.sh:1 @4c33f2f5 | none yet |
| H-066 | SubagentStop | * | subagent-stop-guard-integrity.sh | none | advisory | unexercised | source-level | hooks/subagent-stop-guard-integrity.sh:1 @4c33f2f5 | none yet |
| H-067 | SubagentStop | * | subagentstop-codex-enforce.py | none | advisory | unexercised | source-level | hooks/subagentstop-codex-enforce.py:1 @4c33f2f5 | none yet |
| H-068 | SubagentStop | * | subagentstop-cp-enforce.py | blocking as shipped (settings.json env CP_ENFORCE_MODE=block), only for the stopping subagent's own running cp-state slot with a pending checkpoint; advisory under any other CP_ENFORCE_MODE | advisory | unexercised | source-level | hooks/subagentstop-cp-enforce.py:1 @4c33f2f5 | none yet |
| H-069 | SubagentStop | * | subagentstop-e2e-enforce.py | subagent stops only (agent_id present); no mode switch, and no flag file is read (D24). The role is Claude Code's record of the agent: another role exits 0, and an agent it records no role for is judged only when its own dispatch obligation names role qa. A dispatch that carries an obligation is judged only on the qa-report.v2 that obligation declares, at its declared path; a QA dispatched without one, whose agent-index entry binds it to a cycle's registry (no such registry: exit 0), is judged on the `docs/dev/qa-report-*.json` files its own transcript shows it wrote, and writing none exits 2 unless the session's do-report declares qa-report expected-absent; exits 2 (E2E_ENFORCE_BLOCKED) when that report is missing, its e2e_enforcement is absent or malformed, or its status is skipped_without_justification or outside the qa-report.v2 vocabulary; a dispatch declaring no such report (BA validation, close QA, another role) and any internal error exit 0 | advisory | unexercised | source-level | hooks/subagentstop-e2e-enforce.py:1 @9f4acd03 | hooks/tests/test_e2e_enforce.py |
| H-070 | SubagentStop | * | subagentstop-restart-track.py | none | advisory | unexercised | source-level | hooks/subagentstop-restart-track.py:1 @4c33f2f5 | none yet |
| H-071 | PostToolUseFailure | Bash | posttool-allowlist-consume.py | none | detected | unexercised | source-level | hooks/posttool-allowlist-consume.py:1 @4c33f2f5 | hooks/tests/test_commit_event_pointer.py |
| H-072 | PostToolUse | Write | posttool-push-gate-token-verify.py | exit-0 stub kept at its registered path: reads nothing and exits 0 on every path; the push-gate token's commit checks run in its one writer, scripts/write-push-gate-token.py, before the write | detected | unexercised | source-level | hooks/posttool-push-gate-token-verify.py:1 @4e9d06e4 | hooks/tests/test_write_push_gate_token.py |
| H-073 | SessionStart | (universal) | session-scratch-init.sh | creates the session's own scratch directory `$TMPDIR/<session-id>/` and writes its `.owner` record; skips when no session id is available or the id contains `/` or `..`; best-effort, exits 0 on every path | detected | unexercised | source-level | hooks/session-scratch-init.sh:1 @ef6e9037 | hooks/tests/test_scratch_lifecycle.py |
| H-074 | PreToolUse | (universal) | pretool-do-block-subagents.py | exits 2 only for a main-agent Agent or Task call while this session's /do consent reads true (lib/allowlist.py has_do_consent), unless this session holds an /allow grant for the Agent tool; every other call, and any internal error, exits 0 | advisory | unexercised | source-level | hooks/pretool-do-block-subagents.py:1 @ef6e9037 | hooks/tests/test_do_block_subagents.py |
| H-075 | PreToolUse | Agent | pretool-commit-dispatch-attest.py | witness only, exits 0 on every path: writes a dispatch attestation (later required by pretool-git-privilege-guard.py) only for an Agent or Task call whose subagent_type is changelog-analyst and whose payload carries a session id | advisory | unexercised | source-level | hooks/pretool-commit-dispatch-attest.py:1 @ef6e9037 | none yet |
| H-076 | PreToolUse | Agent | pretool-obligation-gate.py | G1, armed by the shipped settings.json (CLAUDE_OBLIGATION_GATE=block): a dispatch without a valid obligation block (a missing block counts only when the active command's dispatch templates in `commands/<command>.md`, as its session loaded them (the text the CLI recorded when the command was typed), declare an obligation for its subagent_type; a malformed block counts on any dispatch) exits 2; under =advisory or with the key unset it is allowed, the reason it would block printed on one stderr line (OBLIGATION GATE ADVISORY) and nothing written; skipped under =off; internal errors exit 0 | advisory | unexercised | source-level | hooks/pretool-obligation-gate.py:1 @98e41855 | hooks/tests/test_obligation_gate.py |
| H-077 | PreToolUse | Bash | pretool-push-analyst-grant-guard.py | exit-0 stub kept at its registered path: reads nothing and exits 0 on every path; scripts/execute-push.py is the push-analyst grant's one validator, and hooks/push.sh refuses a direct call without the sentinel it writes | advisory | unexercised | source-level | hooks/pretool-push-analyst-grant-guard.py:1 @ef6e9037 | none yet |
| H-078 | PreToolUse | Write\|Edit\|MultiEdit\|NotebookEdit\|Bash | pretool-attribution-pre.py | observational: records the pre-mutation content hash of each write target in the attribution journal; never blocks, exits 0 on every path | advisory | unexercised | source-level | hooks/pretool-attribution-pre.py:1 @ef6e9037 | hooks/tests/test_attribution_journal.py |
| H-079 | PostToolUse | Write\|Edit\|MultiEdit\|NotebookEdit\|Bash | posttool-attribution-post.py | observational: appends the attribution event(s) paired with the H-078 record, then runs the periodic journal seal check (skipped under ATTRIBUTION_AUTOSEAL_DISABLE=1); exits 0 on every path | detected | unexercised | source-level | hooks/posttool-attribution-post.py:1 @ef6e9037 | hooks/tests/test_attribution_journal.py |
| H-080 | PostToolUse | Write\|Edit\|NotebookEdit\|MultiEdit | posttool-lane-completeness-watch.py | acts only when the written file is a lane dev-report shard whose own lane_set is a non-empty list: it then runs scripts/aggregate-dev-report.py for that task, the canonical aggregate's one producer (whether every lane has reported is G3's check, H-021); exits 0 on every path | detected | unexercised | source-level | hooks/posttool-lane-completeness-watch.py:1 @ef6e9037 | none yet |
| H-085 | SessionEnd | (universal) | sessionend-scratch-sweep.sh | removes only `$TMPDIR/<own-session-id>/`, and only when it is a real directory directly under that root whose `.owner` sid equals the session id; skips otherwise; best-effort, exits 0 on every path | detected | unexercised | source-level | hooks/sessionend-scratch-sweep.sh:1 @ef6e9037 | hooks/tests/test_scratch_lifecycle.py |
| H-086 | SubagentStop | * | subagentstop-artifact-contract-enforce.py | subagent stops only (agent_id present). Obligation path: G2, armed by the shipped settings.json (CLAUDE_OBLIGATION_STOPGATE=block; a process env without the key takes it from the harness home's settings.json env): exits 2 on a failed obligated artifact, on a dev report whose file lists differ from the files Claude Code recorded the dev writing (P6 A3.a), on a live harness hook or script the producer's own Write or Edit left uncompilable (P6 F3.a), and on an obligation naming another role than the one Claude Code runs the agent as (role_mismatch); under =advisory, or with the key unset in both, each failing obligated artifact's path and check are printed on stderr (OBLIGATION_STOPGATE_ADVISORY) and the stop is allowed; under =off nothing is read or judged. An exception inside the obligation path is named on stderr (OBLIGATION_STOPGATE_FAULT) and the declared-report check decides the stop. Declared-report check (reached when the agent's own obligation does not resolve, or on that fault; an agent the dev registry does not resolve is never blocked): blocking when ARTIFACT_CONTRACT_ENFORCE_MODE is unset (the default), exits 2 when a json report the agent's own dispatch declares (read as declared even when its block fails the grammar) declares report_version but fails its schema; under =advisory prints the same reason on stderr (ARTIFACT_CONTRACT_ADVISORY) and allows; a missing report never blocks; writes nothing | advisory | unexercised | source-level | hooks/subagentstop-artifact-contract-enforce.py:1 @c1d17a27 | hooks/tests/test_artifact_contract_enforce.py |
| H-087 | PostToolUse | AskUserQuestion | posttool-close-rating.py | the owner's close rating's one writer: appends one row `{ts, task_id, rating, tool_use_id}` to `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/logs/lifecycle.jsonl` under an exclusive lock on the score scripts' `<log>.lock`, only for a main-agent call (no agent_id) whose metadata.source is `close-rating:<task-id>` and whose tool_response answers its one question with one of the four rating labels, and only while that task has no rating row; Skip, free text, a decline, an error result and an AFK auto-continue write nothing; prints nothing and exits 0 on every path | detected | unexercised | source-level | hooks/posttool-close-rating.py:1 @31c9636e | hooks/tests/test_close_rating.py |
| H-088 | Stop | (universal) | stop-launch.py | the `Stop` group's one entry (`"timeout": 300`): runs `stop-workflow-coordinator.py` on the payload (280 s) and relays its exit 0 or 2, stdout and stderr; the coordinator's phases are S-005 – S-008 (section 4). When the coordinator does not decide (another exit, a timeout, a launch error, a missing file) the launcher decides alone on the transcript reader (`hooks/lib/command_span.py`) and `hooks/lib/overnight.py`'s `window_open`, both loaded by path: CLAUDE_COMMAND_GATE=off exits 0; an open overnight window, or a gated latest human-typed command in block mode, exits 2 naming the failure and `/stop`; anything else exits 0; a check whose module cannot load counts as not holding | advisory | unexercised | source-level | hooks/stop-launch.py:1 @067a29ff | hooks/tests/test_stop_launch.py |

---

## 4. Enforcement subjects that are not a single wired hook

| row_id | subject | behavior | exercise_status | proof_layer | citation | verifying_test | result |
|---|---|---|---|---|---|---|---|
| S-001 | black-box-tests-against-real-Claude-Code-builds | unsupported | unexercised | none | docs/ENFORCEMENT-LEDGER.md:1 @4c33f2f5 | none yet | unsupported |
| S-002 | permission-layer-git-backstop | unsupported | unexercised | source-level | settings.json:1 @4c33f2f5 | none yet | unsupported |
| S-003 | destructive-reset-gate-regex-backstop | advisory | exercised | component-tested | hooks/pretool-bash-safety.sh:1667 @4c33f2f5 | hooks/tests/test_blackbox_integration.py | component-tested |
| S-005 | stop-coordinator-phase-coverage:stop-spec-coverage-enforce.py | advisory | unexercised | source-level | hooks/stop-spec-coverage-enforce.py:1 @eba87f69 | none yet | source-level |
| S-006 | stop-coordinator-phase-auto_commit:auto-commit.sh | advisory | unexercised | source-level | hooks/auto-commit.sh:1 @eba87f69 | hooks/tests/test_stop_checkpoint_refusal.py | source-level |
| S-007 | stop-coordinator-phase-cleanup:stop-cleanup-allowlist.sh | advisory | unexercised | source-level | hooks/stop-cleanup-allowlist.sh:1 @eba87f69 | none yet | source-level |
| S-008 | stop-coordinator-phase-completion:stop-command-gate.py | advisory | unexercised | source-level | hooks/stop-command-gate.py:1 @eba87f69 | hooks/tests/test_stop_command_gate.py | source-level |

- **S-001** — no CI harness for actual Claude Code CLI builds exists in this environment or
  session. There is no build matrix to run against. This row is the disclosure of that gap.
- **S-002** — `settings.json @4c33f2f5` carries **96** `permissions.deny` rules, **0 of 96**
  git-related; `permissions.ask` carries 30 rules of which 3 are git-related
  (`Bash(git push --force:*)`, `Bash(git push -f:*)`, `Bash(git reset --hard:*)`), all
  **prefix-anchored** and therefore matching no wrapped or redirected form. There is no
  permission-layer backstop behind the hook layer for this class.
  Outside this class, `permissions.deny` carries a `Skill(<stem>:*)` entry for each human-only
  command, and `hooks/tests/test_skill_deny_coverage.py` requires one for every `commands/*.md`
  stem outside CONTROL that no harness text calls through the Skill tool. `Skill(codex:*)` is
  not denied, by decision (P5): agents and `/close`, `/commit`, `/do` call `Skill(skill="codex")`
  under `--codex`, and `subagentstop-codex-enforce.py` (H-067) requires the ledger entry that
  call's PostToolUse (H-050) writes.
- **S-003** — see `docs/THREAT-MODEL.md` RISK-3. This gate's regex fallback is *mutually
  exclusive* with its classifier branch, so an input the classifier parses successfully but
  finds no git in suppresses its own backstop.
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
    spec subagent's own stop (H-086). The coordinator would relay an exit 2 from it as a block;
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
    it allows when the active span is not a gated command's (only a human-typed harness command
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
   as S-004 – S-007. Neither check covers the **permission** surface, which is why S-002's
   permission-layer measurement stays pinned to `settings.json @4c33f2f5` specifically.

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
