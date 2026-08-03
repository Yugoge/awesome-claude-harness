# Threat Model — awesome-claude-harness

> **Scope**: This threat model covers the AI-agent permission boundary enforced by the
> hook chain in `hooks/`. The adversary model is an autonomous AI agent (Claude Code,
> running as an orchestrator or subagent) that may attempt — through misunderstanding,
> prompt injection, or hallucination — to execute destructive shell operations, bypass
> authorization grants, or exfiltrate data **along a write or mutate path**. Physical
> access, hardware compromise, social engineering of the human operator, and
> **read-only** exfiltration are explicitly out of scope (see "Threat Boundaries"
> below). Protections are defense-in-depth; no single layer is assumed to be
> impenetrable.
>
> **What is proven, and what is only claimed**: this document states residual risk;
> `docs/ENFORCEMENT-LEDGER.md` states, per wired hook, which behavior is *enforced*,
> *detected*, *advisory* or *unsupported*, and which evidence layer earned that label.
> As of this revision **no row in that ledger carries `enforced`**, because no real
> Claude Code dispatcher has been driven in this environment. Treat every claim below
> as bounded by that fact.

---

## 1. Overview

The harness controls every tool call an AI agent makes through a chain of PreToolUse,
PostToolUse, and Stop hooks wired in `settings.json`. The primary attack surface is
the `Bash` tool: an agent that can run arbitrary shell commands can commit destructive
changes, mutate the shared git repository state, or exfiltrate secrets by writing them
out — all without human review. **Only write/mutate-path exfiltration is in scope**;
read-only exfiltration through the conversation context is a stated non-goal (§5.1),
and the Overview and §5 agree on that boundary deliberately. Five independently-designed
mechanisms address distinct classes of abuse. They are documented here so expert
reviewers can audit the architecture without reading all ~8,000 lines of hook code.

### 1.1 Protected Assets

What this harness is trying to keep intact, in rough order of how badly losing it hurts:

| asset | why it is worth protecting | primary mechanism |
|---|---|---|
| **Published git history on `master`/`main`** | Force-push, `reset --hard` and direct ref writes destroy work belonging to other sessions and to the human. Unrecoverable in the general case. | `hooks/pretool-bash-safety.sh:1695-1697 @4c33f2f5`; `hooks/git-keystone/reference-transaction` (overnight actors only) |
| **The uncommitted working tree** | A concurrent session's in-progress edits are not in any commit and have no backup. | `hooks/pretool-bash-safety.sh:757-1038 @4c33f2f5` (bulk-sentinel guard) |
| **Authorization grants** (`/tmp/claude-grants/*.json`) | A grant is the only artifact standing between an agent and a privileged operation. | `hooks/lib/allowlist.py:435-520 @4c33f2f5` (structural matching) |
| **The hook chain itself** | Every other protection is downstream of the hooks staying wired and unedited. | `settings.json:1 @4c33f2f5` wiring plus the hook-refactor consent file |
| **Secrets on disk** (`.env`, keys, tokens) | Disclosure is irreversible. Only the write/mutate path is defended. | Secret scan in `.github/workflows/baseline.yml:110 @4c33f2f5` |
| **The human's ability to audit what happened** | Silent failure is worse than loud failure; an unauditable harness cannot be trusted. | Schema-enforced agent contracts, `hooks/lib/contract_runtime.py:215 @4c33f2f5` |

### 1.2 Attacker Capabilities

The adversary is **the agent itself**, acting against the human's intent through
misunderstanding, prompt injection, or hallucination. Concretely, it is assumed able to:

- **Emit any tool call**, including arbitrary `Bash` command strings, in any quoting,
  escaping or encoding the shell accepts.
- **Read this repository**, including every hook, every regex, and this document —
  so no protection here may depend on the attacker not knowing how it works.
- **Compose and obfuscate**: chain commands, wrap them (`env`, `sudo`, `nice`, …),
  prefix redirections, use ANSI-C escapes, and path-qualify executables (`/usr/bin/git`).
- **Retry indefinitely** and observe each rejection, adapting the next attempt.
- **Run concurrently** with other sessions against the same working tree.

The adversary is assumed **not** able to: edit hook files without tripping the consent
gate, write outside the filesystem the harness sees, or compromise the Python/git
binaries themselves (§5.1).

### 1.3 Trusted Components

Everything below is inside the trust boundary. A defect in any of them voids the
guarantees of this document, and the harness has **no** compensating control for them.

| trusted component | what is trusted about it | controlled by this project? |
|---|---|---|
| **The Claude Code dispatcher / runtime** | That it invokes the wired hooks at all, routes each tool call to the right matcher, and **honors a non-zero hook exit code by aborting the call**. | **No.** This is the single largest uncontrolled dependency: every "blocked" claim in this repository is downstream of a host behavior this project neither implements nor tests against. Nothing here can detect a host that silently ignores exit 2. |
| `python3`, `bash`, `git`, `jsonschema` | That the interpreters and binaries behave as documented and are not compromised. | No — versions are not pinned (§5.1). |
| `settings.json` wiring | That the hook set on disk is the hook set that runs. | Partly — `scripts/verify-claims.sh` asserts the public template wires every hook, but the live file is untracked and per-install. |
| The human operator | That instructions to disable a guard are genuinely the human's (§5.1). | No. |
| The filesystem | That a hook file read at dispatch time is the file this repository committed. | No hardware root of trust. |

Because the dispatcher is **uncontrolled**, this project can never label a mechanism
`enforced` on its own evidence alone — see `docs/ENFORCEMENT-LEDGER.md` §1.1.

---

## 2. Threat Scenarios

### 2.1 TOCTOU Race on `git push` Authorization

| Attribute | Detail |
|---|---|
| **Threat scenario** | An agent validates a push grant and then, between the validation check and the `git push` syscall, a concurrent session or prompt injection replaces the grant file with one authorizing a force push to `master`. Time-of-check / time-of-use race gives the attacker a window to swap the grant. |
| **Incident motivation** | Real incident class documented in roadmap `docs/dev/roadmap-world-class-readiness-20260704.md` B3.4; mitigated in 2026 when the push path was refactored to collapse validate + consume + exec into a single process image. |
| **Primary defense** | `scripts/execute-push.py:229-322` — Steps 9-13 in `main()`: (1) HEAD-drift check at step 9 (line 229), (2) grant unlinked (`os.unlink`) at step 10, (3) Chain-B sentinel written atomically via `mkstemp` + `os.replace` at step 11, (4) `os.execv(push_sh_path, push_argv)` at step 13 (line 302-322) replaces the process image rather than spawning a subprocess. After the grant is consumed (`os.unlink`) it is never re-read; `execv` avoids spawning a second process that would revalidate a mutable grant. |
| **Secondary backstop** | `hooks/git-keystone/reference-transaction` — a git native hook wired via `core.hooksPath`. For overnight actors (`CLAUDE_OVERNIGHT_ACTOR=1`), it runs inside git's own ref-transaction path (covers PATH git, `/usr/bin/git`, Python subprocess) and aborts any `refs/heads/master` or main-worktree `HEAD` update that lacks a valid blessed token. |
| **Verifying test** | `hooks/tests/test_bulk_commit_sentinel.py::test_valid_sentinel_returns_true`, `::test_expired_sentinel_returns_false` (sentinel lifecycle); `execute-push.py` step-13 path is covered by the integration path in `test_bulk_commit_sentinel.py`. |

### 2.2 Structured-Grant Bypass via Substring Injection

| Attribute | Detail |
|---|---|
| **Threat scenario** | An agent receives a grant for `git push origin master` and chains a second destructive command: `git push origin master; git push --force origin master`. A substring-matching allowlist would pass the compound command if the authorized string appears anywhere in it. |
| **Incident motivation** | CLAUDE.md §"Sentinel-grant mechanism" documents the R2 redesign that replaced free-text substring grants with structural matching. The old model was a direct bypass surface. |
| **Primary defense** | `hooks/lib/allowlist.py:435-520` — `match_sentinel_grant_for_bash_command()`. The function first splits the command into sub-commands on `&&`, `||`, `;`, and `|` (line 430-432). A compound command with `len(subcommands) != 1` returns `None` unconditionally (line 468-469). For single sub-commands it compares the **first whitespace-separated token** (after env-var skip) against `entry["op"]` by exact string equality, not substring search. The function's own docstring (line 454) states: "The function NEVER substring-matches the entry['op'] against the raw command line — that was the legacy bash-safety bypass closed by R2." |
| **Verifying test** | `hooks/tests/test_allowlist_consolidation.py::test_compound_command_match` (compound guard); `::test_exact_or_substr_exact_match`, `::test_exact_or_substr_substring_match` (structural vs substring distinction). |

### 2.3 Fail-Closed Tokenizer with ANSI-C Escape Normalization (Bulk-Sentinel Guard)

| Attribute | Detail |
|---|---|
| **Threat scenario** | An agent submits a `find` command against the bulk-commit sentinel path using ANSI-C escape sequences — e.g. `find /tmp/claude-bulk-commit-sentinel-* -de$'\x6c'ete` — to encode a destructive write-action flag and bypass a string-literal check. Alternatively, an unterminated-quote injection or process-substitution `$(cmd)` in a path argument could escape a naive regex. |
| **Incident motivation** | Documented in roadmap B3.4 as "fail-closed shlex tokenizer w/ ANSI-C decode — each guard traces to a dated real catastrophe." The 2026-04-19 incident (`hooks/pretool-bash-safety.sh:1301`) motivated the stash/checkout guards; the subagent history-mutation block cites the 2026-04-23 incident at line 1438. |
| **Primary defense** | `hooks/pretool-bash-safety.sh:757-1038`. The guard activates when the Bash command mentions a protected bulk-sentinel path or script (entry gate at line 757-759). Inside the gate, two independent passes run: (1) `tokenize_or_deny(text)` (line 806-813) uses Python `shlex` with `posix=True` and `punctuation_chars=True`; any `ValueError` (unterminated quote) returns `None` which triggers `sys.exit(0)` — fail-closed DENY (line 905-907). (2) `has_active_cmdsub_or_procsub(text)` (line 827-896) implements a 4-state quote machine (UNQUOTED=0, SINGLE=1, DOUBLE=2, ANSI_C=3). ANSI-C blocks (`$'...'`) enter state 3 where backslash sequences are consumed as 2-char skips but the body is treated as literal. Write-action flag normalization at line 992-1038 strips `$` bytes and decodes hex/octal escapes to catch `find -de$'\x6c'ete` variants. |
| **Verifying test** | `hooks/tests/test_bash_safety_context.py::test_sh_c_rm_is_blocked`, `::test_bash_c_kill_signal_is_blocked`, `::test_tee_consumer_heredoc_stripped`; `test_bash_safety_context_rules.py` covers the full rule set. |

### 2.4 QA-of-BA Gate (Analysis Reviewed Before Code Is Written)

| Attribute | Detail |
|---|---|
| **Threat scenario** | A business analyst subagent produces an implementation plan with unverified claims ("the root cause is X" without any file read confirming X). The dev subagent executes the plan, modifying files based on a hallucinated diagnosis. The error is discovered only after shipping. |
| **Incident motivation** | "Sharpest conceptual novelty" per roadmap B3.4. Motivated by patterns where agents skip investigation and jump to conclusions; surfaced as the most impactful structural safeguard in the 4-agent readiness audit 2026-07-04. |
| **Primary defense** | `commands/dev.md:533-644` — Step 7 of the `/dev` pipeline. Before any dev subagent is dispatched, a QA subagent runs in `ba_validation` mode and evaluates the BA's analysis on 5 dimensions: evidence quality, scope alignment, investigation completeness, affected-file accuracy, and spec-text-vs-execution drift. Objection schema is closed-enum (`agents/qa.md`). A `verdict: "fail"` triggers BA re-invocation (up to 3 iterations). After 3 iterations, the pipeline proceeds with unresolved objections documented — it is not an absolute stop. This makes independent-agent analysis review structural, not advisory. |
| **Verifying test** | The QA-of-BA contract is enforced by the pipeline itself; there is no separate unit test for the gate. The acceptance criterion is operational: if `verdict == "fail"` the orchestrator blocks dev dispatch (evidenced by the iteration logic at `commands/dev.md:629-650`). |

### 2.5 Schema-Enforced Agent Contracts with exit(2) on Mismatch

| Attribute | Detail |
|---|---|
| **Threat scenario** | An overnight agent submits a report with a missing `evidence_summary` block or the wrong `role` label. Downstream hooks that depend on the report's schema silently process garbage, producing false PASS verdicts that mask incomplete work. |
| **Incident motivation** | Roadmap B3.4: "Schema-enforced agent contracts — real Draft7 validator... exit(2) on mismatch." GAP-6 notes the caveat that this is currently overnight-only (cycle-contract.json is only written by the overnight pipeline). |
| **Primary defense** | `hooks/lib/contract_runtime.py` (589 lines) — `validate(record, schema_name)` at line 215 loads the schema from `hooks/lib/schema_registry.py` and runs `jsonschema.Draft7Validator` (system-wide 4.25.1). The `required_when_ui` pre-pass (line 225) enforces additional keys when `ui_pipeline=True`. Two enforcement sites: (1) `hooks/pretool-subagent-enforce.py:293-299` calls `sys.exit(2)` on role/pipeline mismatch at tool-dispatch time; (2) `hooks/posttool-overnight-file-check.py:142-145, 362-377` exits 2 when a required artifact is missing or schema-invalid at tool-completion time. Schemas live in `schemas/*.v1.json` (8 schemas as of HEAD: context, cycle-contract, dev-report, qa-report, graphify-focused-subgraph, graphify-prequery, graphify-run, test-plan). |
| **Verifying test** | `hooks/tests/test_runtime_guard.py` covers the guard dispatch path. Schema round-trip coverage is in `tests/test_aggregate_dev_report.py` and `tests/test_graphify_workflow_contract.py`. |

---

## 3. Defense in Depth

The five mechanisms above are independent layers that interact without shared failure modes:

1. The **TOCTOU-free push** (§2.1) eliminates the time window between grant validation and execution. Even if an attacker could replace the grant file, it would already be unlinked before `execv` runs.

2. The **structured grant model** (§2.2) ensures a valid single-operation grant cannot be extended into a compound command. The compound-command guard runs before structural matching, so no grant schema change can re-introduce substring bypass.

3. The **fail-closed tokenizer** (§2.3) handles inputs that would confuse regex-based guards within the bulk-sentinel protected-path scope. If the tokenizer cannot parse the input, it denies. If the 4-state machine detects active command substitution, it denies. ANSI-C escape normalization catches encoded write-action flags before any pattern match.

4. The **QA-of-BA gate** (§2.4) is an independent-agent review structural control, not a technical control. It catches planning errors before they become code changes, with up to 3 BA-QA iterations; unresolved objections after 3 iterations are documented and the pipeline proceeds. It is orthogonal to the Bash guards.

5. The **schema-enforced contracts** (§2.5) prevent overnight agents from silently submitting incomplete reports. Because the schema check fires as a PreToolUse/PostToolUse hook, the rejection happens before state advances.

The overnight `reference-transaction` keystone (§2.1 secondary backstop) acts as a final layer for the overnight actor scope. It is the only mechanism that intercepts commands that bypass all Python hooks (e.g. a raw `os.execv(['git', 'push'])` call from inside an exec'd process).

---

## 4. Known Residual Risks

> **Citation contract for this section**: every file reference is written `path:line @<sha8>`,
> and every numeric claim is pinned to the revision it was measured at. A citation without a
> revision is not evidence — it is a snapshot that decays silently. This section proves that on
> itself: the RISK-2 entry's original citations (`:105`, `:1367`) were exactly correct when
> written and were both wrong thirteen days later. `scripts/check-enforcement-evidence.py
> --claims` fails CI if any citation here loses its pin.

### RISK-1: The Bash-Guard Core Is Still the Largest File in the Tree

status: PARTIALLY MITIGATED

- **Description**: the Bash guard's decision logic was a single monolithic module. It is now a
  package, but the mass moved rather than shrank, and the core is still the largest file in the
  repository, so the single-point-of-failure and auditability concerns are **reduced, not
  removed**.
- **What actually changed** (each figure pinned to its own revision):
  - `407888c4` turned `hooks/lib/runtime_guard.py:1 @407888c4` into a 17-line delegating shim
    and moved the logic to `hooks/lib/runtime_guard/_core.py:1 @407888c4`, which was itself
    **5,839 lines @407888c4** — the same figure the original entry attributed to
    `runtime_guard.py` at `06e0b0dd`, where it was also accurate. The claim went stale by
    *relocation*, not by being wrong when written.
  - Decomposition then ran as six phases — `455f5be6` (shell_lex), `9752a8c0` (constants),
    `72a2525f` (pathmatch), `96cc84a9` (config), `8aeaa718` (find_cmds + git_cmds) and
    `432c8d70`, *"complete monolith decomposition"* — hardened at `915aa830`.
  - Current size: `hooks/lib/runtime_guard/_core.py:1 @4c33f2f5` is **4,717** lines, with 8
    sibling modules alongside it.
- **Residual**: a defect anywhere in the core still affects the whole Bash guard. If it raises,
  `hooks/pretool-bash-safety.sh:96 @4c33f2f5` falls back to a protected-verb-family deny list
  that is fail-closed for the verbs it covers and blind to everything else.
- **Verifying test**: no dedicated RISK-1 test. Indirect coverage via
  `hooks/tests/test_bash_safety_context.py:1 @4c33f2f5`.

### RISK-2: Two Hand-Synced Git Regex Engines

status: MITIGATED

- **Description**: the harness maintains two independently hand-authored regex engines for
  detecting git commands — `GIT_COMMAND_RE` at `hooks/pretool-git-privilege-guard.py:145
  @4c33f2f5` (Python `re`) and `GIT_CMD_RE` at `hooks/pretool-bash-safety.sh:1654 @4c33f2f5`
  (POSIX ERE for `grep -E`). Editing one without the other creates an asymmetric bypass. Both
  engines still exist as separate hand-authored patterns. Their current definitions are:
  - Python: `GIT_COMMAND_RE = r'(?:^|[\s;&|()`])git' + GIT_GLOBAL_OPTION_RE + r'\s+'`
  - POSIX ERE: `GIT_CMD_RE='(^|[[:space:];&|()`])git'`
- **Risk**: any future edit to one regex without updating the other creates an asymmetric
  bypass — commands blocked by one guard but not the other can be routed through the unpatched
  engine. Both anchor classes still lack the `/` character, which is one dimension of RISK-3.
- **What actually mitigated it — and what did not.** Consolidation into a single engine **did
  not occur**, and the earlier plan to perform one has been withdrawn from this entry rather
  than left standing as an aspiration. What closed the drift risk is the originally-planned
  cross-consistency test: `hooks/tests/test_git_cmd_cross_consistency.py:1 @4c33f2f5` (added
  `407888c4`) runs a shared corpus against both engines *and* against
  `hooks/lib/git_command_classifier.py:1 @4c33f2f5`, asserting agreement, with accepted
  divergences marked `xfail`. Drift between the two engines now fails a test instead of opening
  a silent hole.
- **Note on the classifier's role**: `hooks/lib/git_command_classifier.py:1 @4c33f2f5` is a
  *supplementary augmentation layer* consulted by both guard sites for path-qualified forms. It
  is not a replacement for either regex, and describing it as one would be the same overclaim
  this section exists to remove.
- **Standing guard**: `scripts/check-enforcement-evidence.py --claims` asserts both symbols
  still exist on every CI run, so a future consolidation invalidates this prose loudly instead
  of outdating it quietly.
- **Verifying test**: `hooks/tests/test_git_cmd_cross_consistency.py:1 @4c33f2f5`.

### RISK-3: Wrapper-Flag and Leading-Redirection Prefixes Defeat Git-Command Detection

status: PARTIALLY MITIGATED

**This entry previously described the wrong boundary in both directions — too broad and too
narrow at the same time — and both corrections are published here rather than quietly amended.**

- **Too broad.** The entry's own title named path-qualified `/usr/bin/git push` carrying a force
  flag as passing through both guards. That is **false** at `4c33f2f5`: the force/delete push
  gate at `hooks/pretool-bash-safety.sh:1695 @4c33f2f5` fires on the `GIT_CMD_RE` push branch
  **OR** on the classifier's `_PQ_PUSH_FORCE` flag, and the classifier detects the
  path-qualified form. A sibling lane's host-shaped probe (synthetic PreToolUse payload on
  stdin, exit code read) observed **exit 2** for exactly that command. The plain path-qualified
  force-push form is blocked.
- **Too narrow.** The real residual is not about path qualification at all. It is
  **`wrapper-with-flag`** and **`leading-redirection`** prefixes — and for one gate shape a
  *bare* form with no path qualification is enough.

#### The residual class, by dimension

The classifier's own module docstring accepts these residuals under the heading *"Known scope
boundaries (arch-F7)"* at `hooks/lib/git_command_classifier.py:17 @4c33f2f5`, adding *"The
speed-bump design accepts this."* Measured this cycle across 12 wrapper tokens x 4 flag shapes,
7 redirection operators, x {bare, path-qualified}: **136 forms probed, 110 classifier misses,
55 forms missing both detection mechanisms**.

| prefix form | qualification | `iter_git_invocations()` | anchor class | forms |
|---|---|---|---|---|
| none | bare | detected | MATCH | 1 |
| none | path-qualified | detected (`path_qualified:true`) | no-match | 1 |
| wrapper-no-flag (12 tokens) | bare | detected | MATCH | 12 |
| wrapper-no-flag (12 tokens) | path-qualified | detected (`path_qualified:true`) | no-match | 12 |
| **wrapper-with-flag** | bare | `[]` | MATCH | 48 |
| **wrapper-with-flag** | **path-qualified** | `[]` | no-match | **48 — both miss** |
| **leading-redirection** (7 ops) | bare | `[]` | MATCH | 7 |
| **leading-redirection** (7 ops) | **path-qualified** | `[]` | no-match | **7 — both miss** |

**Mechanism**: `_command_token_index()` at `hooks/lib/git_command_classifier.py:113 @4c33f2f5`
skips env-assignments and the 12 `_WRAPPERS` tokens at
`hooks/lib/git_command_classifier.py:105 @4c33f2f5` (`sudo`, `doas`, `env`, `xargs`, `time`,
`nohup`, `setsid`, `stdbuf`, `ionice`, `command`, `builtin`, `nice`) — but a wrapper *flag* such
as `-i` is neither an assignment nor a wrapper, so it is returned as the command token and the
git token is never reached. Separately, both anchor classes omit `/`, so they miss every
path-qualified token. Only the `env` family and redirections are named in any docstring in this
repository; the **privilege** family (`sudo`, `doas`) and the **scheduling** family (`nice`,
`ionice`, `time`, `nohup`, `setsid`) appear in none.

#### Third dimension: gate architecture

An anchor MATCH does **not** mean the gate fires. Two gate shapes exist in
`hooks/pretool-bash-safety.sh:1 @4c33f2f5`:

- **Architecture A — classifier-primary with a *mutually exclusive* regex fallback.** The
  classifier branch at `hooks/pretool-bash-safety.sh:1657 @4c33f2f5` requires
  `CLASSIFIER_STATUS` to be `ok` **and** a match to be found. Its regex fallback at
  `hooks/pretool-bash-safety.sh:1667 @4c33f2f5` is guarded on `CLASSIFIER_STATUS` **not** being
  `ok`. But `CLASSIFIER_STATUS` is set to `ok` for a *successful-but-empty* parse — an empty
  list trivially passes the schema validator, whose per-item loop runs zero times
  (`hooks/pretool-bash-safety.sh:906 @4c33f2f5`, `hooks/pretool-bash-safety.sh:930 @4c33f2f5`).
  **So an input the classifier tokenizes without finding git suppresses its own backstop.**
  Every wrapper-with-flag and leading-redirection form produces exactly that parse. Census at
  `4c33f2f5`: **exactly one** gate has this shape — the destructive-reset gate at
  `hooks/pretool-bash-safety.sh:1657 @4c33f2f5`.
- **Architecture B — unconditional regex OR classifier.** The `GIT_CMD_RE` branch runs
  unconditionally and is OR-ed with the classifier result, so the anchor still fires for bare
  forms. Census at `4c33f2f5`: **2** such branches —
  `hooks/pretool-bash-safety.sh:1695 @4c33f2f5` (force/delete push) and
  `hooks/pretool-bash-safety.sh:1732 @4c33f2f5` (`update-ref`, branch deletion,
  `symbolic-ref`). **These two are unaffected by the suppression above.**

**Consequence**: for the single architecture-A gate a **bare** wrapper-with-flag form defeats
the gate despite the anchor matching. Path qualification is not required. A sibling lane's
host-shaped re-probe found 9 of 15 tested destructive-reset forms exit 0 across the Bash
PreToolUse chain, **including an environment-unset form with no path qualification** — that is
this mechanism, observed from outside.

#### Cell witnesses

Every witness below is probed individually on every CI run by
`scripts/check-enforcement-evidence.py --claims`, and each is a corpus entry in
`hooks/tests/fixtures/adversarial_corpus.json:1 @4c33f2f5`.

| id | form | cell | classifier | anchor |
|---|---|---|---|---|
| W1 | `git status` | none/bare | detected | MATCH |
| W2 | `/usr/bin/git status` | none/path-qualified | detected | no-match |
| W3 | `env /usr/bin/git status` | wrapper-no-flag/path-qualified | detected | no-match |
| W4 | `env -i git status` | wrapper-with-flag/bare | miss | MATCH |
| W5 | `env -u FOO git status` | wrapper-with-flag/bare | miss | MATCH |
| W6 | `2>/dev/null git status` | leading-redirection/bare | miss | MATCH |
| W7 | `env -i /usr/bin/git status` | wrapper-with-flag/path-qualified | miss | no-match |
| W8 | `env -u FOO /usr/bin/git status` | wrapper-with-flag/path-qualified | miss | no-match |
| W9 | `2>/dev/null /usr/bin/git status` | leading-redirection/path-qualified | miss | no-match |
| W10 | `sudo -n /usr/bin/git status` | wrapper-with-flag/path-qualified | miss | no-match |
| W11 | `nice -n 5 /usr/bin/git status` | wrapper-with-flag/path-qualified | miss | no-match |

`env -u FOO` (W5, W8) is the least-disputable witness: unsetting an unset variable perturbs
nothing — 57 environment variables remain intact, versus 0 under `env -i` — so it cannot be
dismissed as a self-defeating payload.

#### No permission-layer backstop

Parsed from `settings.json:1 @4c33f2f5`: `permissions.deny` carries 96 rules, of which **0 of
96** are git-related. `permissions.ask` carries 30 rules, 3 of them git-related (force-push,
short-form force-push, and hard-reset prefixes) — and all three are **prefix-anchored**, so they
match no wrapped or redirected form. Publishing the hook-layer residual while omitting the
absence of a permission-layer backstop would describe half the boundary.

#### Precision, held deliberately

These are **detection-layer measurements** — tokenizer and regex misses — plus a source-level
reading of gate control flow. They are **not** 55 demonstrated executable bypasses. Every probe
in this repository used the harmless `status` subcommand, which is valid because both
`_command_token_index()` and the anchor classes are subcommand-independent. **No push, reset or
ref mutation was ever executed** to produce any figure in this section.

#### Why this is published

The residual is a *deliberately accepted* design boundary, and the harness makes public
"fail closed" claims that a reader could not otherwise bound. An undisclosed accepted residual
is exactly the overclaim this document exists to end. Closing the residual is a separate,
security-reviewed decision that the classifier's own docstring reserves; this entry publishes
and regression-guards it rather than silently changing the guard.

- **Verifying test**: `hooks/tests/test_blackbox_integration.py:1 @4c33f2f5` (component /
  subprocess boundary) and `scripts/check-enforcement-evidence.py --claims` (drift guard).

#### Superseded description (retained for provenance)

- **Description**: Both `GIT_COMMAND_RE` (Python) and `GIT_CMD_RE` (POSIX ERE) use an anchor character class `[\s;&|()\`]` / `[[:space:];&|()\`]` that does not include `/`. As a result, the command `/usr/bin/git push --force origin master` does not match either regex and passes through both guards without triggering a block. In the overnight scope, the `git-keystone/reference-transaction` backstop intercepts this at the git layer. In interactive sessions where `CLAUDE_OVERNIGHT_ACTOR` is not set, there is no backstop — the bypass is un-backstopped.
- **Incident context**: RISK-3 is the security seam referenced as "incident `b5d447e`" in `docs/dev/roadmap-world-class-readiness-20260704.md` B3.4. The commit class represents the interactive-session gap where the keystone actor-scope gate leaves a window.
- **Fix in progress**: Sub-task F of the current work batch (`task_id: 20260704-134650`) will introduce `hooks/lib/git_command_classifier.py`, a shared Python classifier that uses command-position parsing (`os.path.basename(token) == 'git'`) rather than regex anchor class extension. Both `pretool-git-privilege-guard.py` and `pretool-bash-safety.sh` will consume the classifier. The fix is tracked as `R6` in `docs/dev/ticket-20260704-134650.md` and will be acceptance-tested by the pending generated AC-F tests (`test_AC_F1_a1b2c3d4e5f60015.py`, `test_AC_F2_a1b2c3d4e5f60016.py`, `test_AC_F4_a1b2c3d4e5f6001f.py`) once sub-task F is implemented — those tests currently contain `pytest.fail(TEST_INCOMPLETE)` stubs.
- **Current status**: RISK-3 gap UNMITIGATED in interactive sessions until sub-task F is merged.

---

## 5. Threat Boundaries (Out of Scope)

The following threat classes are explicitly NOT addressed by this threat model or by the harness hook chain:

- **Social engineering of the human operator**: an attacker who convinces the human to run `touch .claude/.hook-refactor-allow` and then issue a prompt that edits hook files is outside the model. The harness assumes the human operator is trustworthy.
- **Hardware compromise or physical access**: an attacker with write access to the filesystem can modify hook files directly, bypassing all Python-level controls. The harness has no hardware root-of-trust.
- **Supply-chain attacks on Python or system packages**: if `python3`, `shlex`, `jsonschema`, or `git` itself is compromised, all guards relying on those binaries are bypassed. The harness does not pin system package versions.
- **Claude model-level jailbreaks**: prompt injection that overrides the model's adherence to its system prompt is a model safety problem, not a harness problem. The harness defends against the model's output (tool calls) but not against the model being instructed to produce a particular output.
- **Exfiltration via read-only Bash**: the harness permits many read-only Bash commands. An agent can `cat`, `curl`, or `grep` files and exfiltrate their content through the conversation context. Read-only exfiltration is out of scope; the harness focuses on write/mutate operations.
- **Secrets disclosure via `SECURITY.md` disclosure policy**: see `SECURITY.md` for the responsible disclosure process; that document governs how to report security vulnerabilities in the harness itself.

---

*Document source: generated 2026-07-04 as part of world-class-readiness batch `20260704-134650`. Cite `docs/dev/roadmap-world-class-readiness-20260704.md` B3.4 for the engineering context that motivated this document.*
