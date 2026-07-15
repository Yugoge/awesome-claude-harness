# Threat Model — awesome-claude-harness

> **Scope**: This threat model covers the AI-agent permission boundary enforced by the
> hook chain in `hooks/`. The adversary model is an autonomous AI agent (Claude Code,
> running as an orchestrator or subagent) that may attempt — through misunderstanding,
> prompt injection, or hallucination — to execute destructive shell operations, bypass
> authorization grants, or exfiltrate data. Physical access, hardware compromise, and
> social engineering of the human operator are explicitly out of scope (see
> "Threat Boundaries" below). Protections are defense-in-depth; no single layer is
> assumed to be impenetrable.

---

## 1. Overview

The harness controls every tool call an AI agent makes through a chain of PreToolUse,
PostToolUse, and Stop hooks wired in `settings.json`. The primary attack surface is
the `Bash` tool: an agent that can run arbitrary shell commands can commit destructive
changes, exfiltrate secrets, or mutate the shared git repository state without human
review. Five independently-designed mechanisms address distinct classes of abuse. They
are documented here so expert reviewers can audit the architecture without reading all
~8,000 lines of hook code.

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

### RISK-1: `hooks/lib/runtime_guard.py` is a 5,839-line SPOF

- **Description**: `runtime_guard.py` is a single monolithic module (5,839 lines as of HEAD `06e0b0dd`) imported fail-closed by `pretool-bash-safety.sh` via the embedded Python interpreter. It is the single largest file in the codebase and serves as the central routing hub for Bash safety decisions. A bug anywhere in the module can affect the entire Bash guard.
- **Current risk**: If `runtime_guard.py` raises an unhandled exception, `pretool-bash-safety.sh` falls back to a protected-verb-family deny list at lines 96-103 (covers push, reset --hard, known destructive forms). That fallback is fail-closed for the covered verbs but may lose fine-grained/project-specific coverage for commands outside it. The module's size also makes it difficult to audit and to test comprehensively.
- **Planned mitigation**: Decompose into a package (`hooks/lib/runtime_guard/`) with domain-scoped sub-modules. Tracked as GAP-1 in `docs/dev/roadmap-world-class-readiness-20260704.md` B4 (P2 backlog, medium effort). Not yet in scope for the current work batch.
- **Acceptance test reference**: No dedicated RISK-1 unit test exists yet. Coverage comes indirectly through `hooks/tests/test_bash_safety_context.py` and `test_bash_safety_context_rules.py`.

### RISK-2: Two Hand-Synced Git Regex Engines with No Cross-Consistency Test

- **Description**: The harness maintains two independent regex engines for detecting dangerous git commands: (1) `GIT_COMMAND_RE` in `hooks/pretool-git-privilege-guard.py:105` (Python `re` pattern), and (2) `GIT_CMD_RE` in `hooks/pretool-bash-safety.sh:1367` (POSIX ERE for `grep -E`). Both are hand-authored with no shared source. Their current definitions are:
  - Python: `GIT_COMMAND_RE = r'(?:^|[\s;&|()`])git' + GIT_GLOBAL_OPTION_RE + r'\s+'`
  - POSIX ERE: `GIT_CMD_RE='(^|[[:space:];&|()`])git'`
- **Risk**: Any future edit to one regex without updating the other creates an asymmetric bypass: commands blocked by one guard but not the other can be routed through the unpatched engine. This is the class of drift that RISK-3 already exemplifies — both regexes currently lack the `/` character in the anchor class, meaning `/usr/bin/git push` matches neither.
- **Planned mitigation**: Add a cross-consistency test that runs a canonical command corpus against both engines and asserts identical outcomes. Long term: consolidate into `hooks/lib/git_command_classifier.py` (sub-task F of the current work batch). Tracked as RISK-2 in `docs/dev/roadmap-world-class-readiness-20260704.md` B3.4.
- **Acceptance test reference**: No cross-consistency test exists yet. The sub-task F tests (`tests/generated/20260704-134650/test_AC_F1_a1b2c3d4e5f60015.py`, `test_AC_F2_a1b2c3d4e5f60016.py`) will provide partial coverage once sub-task F is implemented.

### RISK-3: Path-Qualified Git (`/usr/bin/git push`) Bypasses Both Regex Engines in Interactive Sessions

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
