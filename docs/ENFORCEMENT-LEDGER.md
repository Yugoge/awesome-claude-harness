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

**Three columns are derived.** `event_class`, `matcher` and `hook` are recomputed from
`settings.json` at `@4c33f2f5` by `scripts/check-enforcement-evidence.py --claims`, which
compares the derived triple set against the published rows and fails on **either** symmetric
difference. That check runs inside the already required `baseline` CI job via
`scripts/verify-claims.sh`.

**The other seven columns are authored in this document.** They are `row_id`,
`mode/precondition`, `behavior`, `exercise_status`, `proof_layer`, `citation` and
`verifying_test`. They are not derived from anything; they receive the following validation and
no more:

- all seven are checked **non-blank** — a blank cell is a failure, not a statement that a value
  is absent;
- `behavior`, `exercise_status` and `proof_layer` are additionally validated against the closed
  sets declared in `DECLARED_SCHEMA`;
- `citation` is validated for the presence of an `@<sha8>` revision pin.

**On falsifiability.** 68 of the 70 rows carry `proof_layer: source-level`, which as section 1.3
defines it means those rows rest on **reading the code rather than running it**; the remaining 2
carry `component-tested` and none carry `host-observed` or `host-shaped`. The gate validates
proof-layer membership and a non-blank `verifying_test`, and it does **not** execute the
verifying test or establish one-command falsifiability for any row. No row's falsifier has been
run by any check in this repository.

---

## 1. Vocabulary (the closed sets)

The three label axes below — and the accepted `status:` value of each residual-risk entry of
`docs/THREAT-MODEL.md` — are **declared exactly once**, in `DECLARED_SCHEMA` in
`scripts/check-enforcement-evidence.py`. The block that follows is asserted byte-equal to that
declaration on every run, so this document cannot drift from the code that enforces it.

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

All **seven** lifecycle event classes are represented. `settings.json @4c33f2f5` wires 7 event
classes / 41 matchers / **70 hook commands**, and there are exactly 70 rows below.

**The authoring rule `behavior` follows** — applied by hand, and checked only for closed-set
membership, not recomputed from the event class: events that can deny a pending action
— `PreToolUse`, `UserPromptSubmit`, `Stop`, `SubagentStop` — are `advisory`, because they are
deny-*capable* but their prevention has not been observed on a host. Events that fire after the
fact or carry no veto — `PostToolUse`, `SessionStart`, `Notification` — are `detected`.

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
| H-020 | PreToolUse | * | pretool-tool-policy.py | none | advisory | unexercised | source-level | hooks/pretool-tool-policy.py:1 @4c33f2f5 | none yet |
| H-021 | PreToolUse | Agent | pretool-aggregate-check.py | none | advisory | unexercised | source-level | hooks/pretool-aggregate-check.py:1 @4c33f2f5 | none yet |
| H-022 | PreToolUse | Agent | pretool-bisect-gate.sh | none | advisory | unexercised | source-level | hooks/pretool-bisect-gate.sh:1 @4c33f2f5 | none yet |
| H-023 | PreToolUse | Agent | pretool-gitignore-preflight.py | none | advisory | unexercised | source-level | hooks/pretool-gitignore-preflight.py:1 @4c33f2f5 | none yet |
| H-024 | PreToolUse | Agent | pretool-layer-escalation-check.sh | none | advisory | unexercised | source-level | hooks/pretool-layer-escalation-check.sh:1 @4c33f2f5 | none yet |
| H-025 | PreToolUse | Agent | pretool-orchestrator-prompt-purity.py | none | advisory | unexercised | source-level | hooks/pretool-orchestrator-prompt-purity.py:1 @4c33f2f5 | none yet |
| H-026 | PreToolUse | Agent | pretool-spec-block-foreground-agent.py | none | advisory | unexercised | source-level | hooks/pretool-spec-block-foreground-agent.py:1 @4c33f2f5 | none yet |
| H-027 | PreToolUse | Bash | pretool-bash-safety.sh | none | advisory | exercised | component-tested | hooks/pretool-bash-safety.sh:1657 @4c33f2f5 | hooks/tests/test_blackbox_integration.py |
| H-028 | PreToolUse | Bash | pretool-bash-views-guard.py | none | advisory | unexercised | source-level | hooks/pretool-bash-views-guard.py:1 @4c33f2f5 | none yet |
| H-029 | PreToolUse | Bash | pretool-block-branch-pr-worktree.py | none | advisory | unexercised | source-level | hooks/pretool-block-branch-pr-worktree.py:1 @4c33f2f5 | none yet |
| H-030 | PreToolUse | Bash | pretool-bulk-commit-detector.py | none | advisory | unexercised | source-level | hooks/pretool-bulk-commit-detector.py:1 @4c33f2f5 | none yet |
| H-031 | PreToolUse | Bash | pretool-git-privilege-guard.py | none | advisory | exercised | component-tested | hooks/pretool-git-privilege-guard.py:145 @4c33f2f5 | hooks/tests/test_blackbox_integration.py |
| H-032 | PreToolUse | Bash | pretool-grep-backtrack-guard.py | none | advisory | unexercised | source-level | hooks/pretool-grep-backtrack-guard.py:1 @4c33f2f5 | none yet |
| H-033 | PreToolUse | Bash | pretool-wrapper-userintent.py | none | advisory | unexercised | source-level | hooks/pretool-wrapper-userintent.py:1 @4c33f2f5 | none yet |
| H-034 | PreToolUse | Edit\|Write\|MultiEdit\|Bash | pretool-claude-config-guard.py | none | advisory | unexercised | source-level | hooks/pretool-claude-config-guard.py:1 @4c33f2f5 | none yet |
| H-035 | PreToolUse | EnterWorktree | pretool-block-enterworktree.sh | none | advisory | unexercised | source-level | hooks/pretool-block-enterworktree.sh:1 @4c33f2f5 | none yet |
| H-036 | PreToolUse | Read | pretool-cp-checkin.py | none | advisory | unexercised | source-level | hooks/pretool-cp-checkin.py:1 @4c33f2f5 | none yet |
| H-037 | PreToolUse | TodoWrite | pretool-todo-validate.py | none | advisory | unexercised | source-level | hooks/pretool-todo-validate.py:1 @4c33f2f5 | none yet |
| H-038 | PreToolUse | Write | pretool-write-guard.sh | none | advisory | unexercised | source-level | hooks/pretool-write-guard.sh:1 @4c33f2f5 | none yet |
| H-039 | PreToolUse | Write\|Edit\|MultiEdit | pretool-quality-gate.py | none | advisory | unexercised | source-level | hooks/pretool-quality-gate.py:1 @4c33f2f5 | none yet |
| H-040 | PreToolUse | Write\|Edit\|MultiEdit\|Bash | pretool-overnight-hook-guard.py | none | advisory | unexercised | source-level | hooks/pretool-overnight-hook-guard.py:1 @4c33f2f5 | none yet |
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
| H-051 | PostToolUse | TodoWrite | posttool-overnight-loop.py | none | detected | unexercised | source-level | hooks/posttool-overnight-loop.py:1 @4c33f2f5 | none yet |
| H-052 | PostToolUse | TodoWrite | posttool-todo-count.py | none | detected | unexercised | source-level | hooks/posttool-todo-count.py:1 @4c33f2f5 | none yet |
| H-053 | PostToolUse | TodoWrite | posttool-todo-sequence.py | none | detected | unexercised | source-level | hooks/posttool-todo-sequence.py:1 @4c33f2f5 | none yet |
| H-054 | PostToolUse | TodoWrite | posttool-todo-tracker.py | none | detected | unexercised | source-level | hooks/posttool-todo-tracker.py:1 @4c33f2f5 | none yet |
| H-055 | PostToolUse | Write\|Edit\|NotebookEdit\|MultiEdit | posttool-command-frontmatter-validate.py | none | detected | unexercised | source-level | hooks/posttool-command-frontmatter-validate.py:1 @4c33f2f5 | none yet |
| H-056 | PostToolUse | Write\|Edit\|NotebookEdit\|MultiEdit | posttool-doc-sync.py | none | detected | unexercised | source-level | hooks/posttool-doc-sync.py:1 @4c33f2f5 | none yet |
| H-057 | PostToolUse | Write\|Edit\|NotebookEdit\|MultiEdit | posttool-git-checkpoint.sh | none | detected | unexercised | source-level | hooks/posttool-git-checkpoint.sh:1 @4c33f2f5 | none yet |
| H-058 | PostToolUse | mcp__playwright__browser_run_code | posttool-runcode-watchdog.py | none | detected | unexercised | source-level | hooks/posttool-runcode-watchdog.py:1 @4c33f2f5 | none yet |
| H-059 | Notification | idle_prompt | notification-idle-overnight.py | none | detected | unexercised | source-level | hooks/notification-idle-overnight.py:1 @4c33f2f5 | none yet |
| H-060 | Stop | (universal) | auto-commit.sh | none | advisory | unexercised | source-level | hooks/auto-commit.sh:1 @4c33f2f5 | none yet |
| H-061 | Stop | (universal) | stop-cleanup-allowlist.sh | none | advisory | unexercised | source-level | hooks/stop-cleanup-allowlist.sh:1 @4c33f2f5 | none yet |
| H-062 | Stop | (universal) | stop-overnight-timelock.py | none | advisory | unexercised | source-level | hooks/stop-overnight-timelock.py:1 @4c33f2f5 | none yet |
| H-063 | Stop | (universal) | stop-spec-coverage-enforce.py | none | advisory | unexercised | source-level | hooks/stop-spec-coverage-enforce.py:1 @4c33f2f5 | none yet |
| H-064 | SubagentStop | * | pretool-layer-match-gate.sh | none | advisory | unexercised | source-level | hooks/pretool-layer-match-gate.sh:1 @4c33f2f5 | none yet |
| H-065 | SubagentStop | * | subagent-stop-diff-check.sh | none | advisory | unexercised | source-level | hooks/subagent-stop-diff-check.sh:1 @4c33f2f5 | none yet |
| H-066 | SubagentStop | * | subagent-stop-guard-integrity.sh | none | advisory | unexercised | source-level | hooks/subagent-stop-guard-integrity.sh:1 @4c33f2f5 | none yet |
| H-067 | SubagentStop | * | subagentstop-codex-enforce.py | none | advisory | unexercised | source-level | hooks/subagentstop-codex-enforce.py:1 @4c33f2f5 | none yet |
| H-068 | SubagentStop | * | subagentstop-cp-enforce.py | advisory when CP_ENFORCE_MODE is unset (the default); blocking only under CP_ENFORCE_MODE=block | advisory | unexercised | source-level | hooks/subagentstop-cp-enforce.py:1 @4c33f2f5 | none yet |
| H-069 | SubagentStop | * | subagentstop-e2e-enforce.py | none | advisory | unexercised | source-level | hooks/subagentstop-e2e-enforce.py:1 @4c33f2f5 | none yet |
| H-070 | SubagentStop | * | subagentstop-restart-track.py | none | advisory | unexercised | source-level | hooks/subagentstop-restart-track.py:1 @4c33f2f5 | none yet |

---

## 4. Enforcement subjects that are not a single wired hook

| row_id | subject | behavior | exercise_status | proof_layer | citation | verifying_test | result |
|---|---|---|---|---|---|---|---|
| S-001 | black-box-tests-against-real-Claude-Code-builds | unsupported | unexercised | none | docs/ENFORCEMENT-LEDGER.md:1 @4c33f2f5 | none yet | unsupported |
| S-002 | permission-layer-git-backstop | unsupported | unexercised | source-level | settings.json:1 @4c33f2f5 | none yet | unsupported |
| S-003 | destructive-reset-gate-regex-backstop | advisory | exercised | component-tested | hooks/pretool-bash-safety.sh:1667 @4c33f2f5 | hooks/tests/test_blackbox_integration.py | component-tested |

- **S-001** — no CI harness for actual Claude Code CLI builds exists in this environment or
  session. There is no build matrix to run against. This row is the disclosure of that gap.
- **S-002** — `settings.json @4c33f2f5` carries **96** `permissions.deny` rules, **0 of 96**
  git-related; `permissions.ask` carries 30 rules of which 3 are git-related
  (`Bash(git push --force:*)`, `Bash(git push -f:*)`, `Bash(git reset --hard:*)`), all
  **prefix-anchored** and therefore matching no wrapped or redirected form. There is no
  permission-layer backstop behind the hook layer for this class.
- **S-003** — see `docs/THREAT-MODEL.md` RISK-3. This gate's regex fallback is *mutually
  exclusive* with its classifier branch, so an input the classifier parses successfully but
  finds no git in suppresses its own backstop.

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
2. **The live settings file has already diverged from its template.** Running the settings
   renderer against `settings.json` today silently re-adds 2 `deny` entries and strips roughly
   38 `allow` entries. The hook *set* is currently identical between the two files — verified
   this cycle, 70 of 70 `(event, matcher, hook)` triples match — so the registered-hook rows
   above hold under either file. The **permission** surface does not, which is why S-002's
   permission-layer measurement is pinned to `settings.json @4c33f2f5` specifically.

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
- **`_WRAPPERS` @4c33f2f5** (`hooks/lib/git_command_classifier.py:105-108 @4c33f2f5`), 12 tokens:
  `sudo`, `doas`, `env`, `xargs`, `time`, `nohup`, `setsid`, `stdbuf`, `ionice`, `command`,
  `builtin`, `nice`.
<!-- published-tokens:wrapper:end -->
<!-- published-tokens:leading-redirection:begin -->
- **Leading-redirection operators** covered by the published matrix, 7 tokens:
  `2>/dev/null`, `>`, `>>`, `<`, `2>&1`, `&>`, `1>`.
<!-- published-tokens:leading-redirection:end -->
- **Gate-architecture census @4c33f2f5**: **1** classifier-exclusive fallback guard
  (architecture A — the only shape the empty-parse suppression affects), **2** unconditional
  `GIT_CMD_RE` branches (architecture B), and **8** classifier-only path-qualified augmentation
  branches (architecture C, which never carried a regex fallback to lose). All three are
  counted and regression-guarded. Publishing only A and B would be a cherry-picked census:
  a reader counting classifier-consuming branches in that guard finds 11, not 3.

---

## 7. Evidence claims resting on internal sources only

Every claim in this document is `tier_2_verified` against this repository's own code and
configuration — read, greped, parsed or executed in-tree this cycle. **None** rests on an
official Claude Code source, because no external documentation was fetched. Specifically
unverified against upstream: the meaning of each lifecycle event class, whether the host honors
a non-zero hook exit code, and what a "supported build" means to the vendor. Those three are the
load-bearing gaps between this ledger and a genuine enforcement guarantee, and they are named
rather than papered over.

---

*Only `event_class`, `matcher` and `hook` are derived from `settings.json`; the other seven
registered-hook columns are authored in this ledger. Verified by
`scripts/check-enforcement-evidence.py --ledger` and `--claims`, both wired into
`scripts/verify-claims.sh` and thus into the required `baseline` CI job.*
