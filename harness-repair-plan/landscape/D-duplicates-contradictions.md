# D-duplicates-contradictions: multiple truths (D3) and contradictions (D4)

Repository: /home/user/awesome-claude-harness @ 09ab15b (read-only). All line numbers refer to that tree.
Execution sandbox: `scratchpad/landscape-work/D-duplicates-contradictions/` (`h/` = `git archive HEAD` copy of
hooks/scripts/policies/schemas/settings.json, `proj/` = toy git repo; HOME, CLAUDE_STATE_DIR, TMPDIR and
CLAUDE_PROJECT_DIR redirected into the sandbox; PYTHONDONTWRITEBYTECODE=1; no live `/tmp/claude-*` file was written).
Prior evidence reused and re-checked: `harness-cleanup/problems.md` (X-ids: X13, X22, X29, X30, X31, X39, X47, X50, X51),
`wf2_result.json` themes "Prompt-layer diet" P3/P6/P7/P13, "Hook architecture" P6/P7/P8, "separating-source-from-runtime"
SR-02/SR-04/SR-08, "purpose-spec" C1-C4/C7/P10; sibling inventories `landscape/B-breakages.md` (B3.e, B4) and
`landscape/A-producer-input-identity.md` (A4 role source, owned_edits D3 note).

Binding frame. Every fix below either (1) collapses N implementations of one decision into the ONE producer-side library
that already exists for it (hooks/lib/*), so every gate computes the same answer, or (2) corrects prose so it states what
the producer hooks actually do. No fix adds a check to /close or /commit, no fix adds a mutable state file, and no feature
is retired (dead files are only named and handed to E1). Prompt de-duplication uses one source fragment per shared block,
rendered into the agent/command files (repo-versioned source, not runtime state).

---

## Verification log (executed this session, sandbox only)

| # | What | Result |
|---|---|---|
| T1 | `pretool-orchestrator-gate.py`, consent flag `true` written ONLY under `CLAUDE_STATE_DIR`, two `Edit` calls | rc=0, rc=0 (gate honours /do at the resolver path) |
| T2 | `pretool-git-privilege-guard.py`, same session and flag, main agent `git commit -m wip` | **rc=2 `BLOCKED: agent git commit`**. The guard reads the flag at the literal `/tmp` (`:274`), so /do is invisible to it |
| T3 | `pretool-block-branch-pr-worktree.py`, same flag, main agent `git checkout -b feat` | rc=0 (honours /do at the resolver path). T1-T3 = one flag, two answers |
| T4 | Bash, Bash, Bash, Read, Grep, Bash, Bash, Bash through the orchestrator gate | 8th call rc=2 `Bash used consecutively beyond limit (6/5)`: interleaved Read/Grep do not reset the "consecutive" count |
| T5 | `EnterPlanMode` through the gate, then again with the /do flag present | both rc=2; the block text says "run /do to unlock" |
| T6 | the two `strip_non_executable_contexts` (bash_context_strip vs grepguard_context_strip) on 7 inputs | **6 of 7 outputs differ** (one strips quoted text and keeps `#` comments, the other strips comments and keeps quoted text) |
| T7 | git subcommand location: classifier `_git_subcommand`, runtime_guard `_git_subcommand_index`, allowlist `_strip_git_global_opts` | `--exec-path status` -> classifier None, runtime_guard None (both swallow `status`); `--attr-source HEAD status` -> classifier/runtime_guard return `HEAD`; `--config-env x=y commit` -> classifier `commit`, runtime_guard `x=y` |
| T8 | subagent `echo "tip; git commit -m x"` through privilege-guard, bash-safety, branch firewall | **privilege-guard rc=2 `BLOCKED: agent git commit`**; bash-safety rc=0; branch firewall rc=0. The guard feeds RAW text to the shared quote-blind `_segments` (`classify_git_command(command)` at `:2398`, `GIT_COMMIT_INVOCATION_RE` at `:204-206`); bash-safety feeds context-stripped text |
| T9 | main agent `git branch -d old`, `git branch -m a b`, `git branch -D old` | privilege-guard **rc=2** (`direct git ref mutation`), branch firewall rc=0. CLAUDE.md:86 says these forms "remain allowed" |
| T10 | `allowlist._bash_subcommands("git commit -m 'a && b'")` | `["git commit -m 'a", "b'"]` (quote-blind split inside the "single source of truth" grant matcher) |

Corrections to prior evidence:
- wf2 P13 / problems X50: "the real sentinel path is `<task_id>-<nonce>.json` (allowlist.py:20)" is wrong. The writer
  writes `<state_dir>/claude-grants/<TASK_ID>.json` (`hooks/userprompt-consent-allowlist.sh:711-714`); the reader accepts
  both shapes (`hooks/lib/allowlist.py:364-378`). The stale statement is the allowlist.py:20 docstring, not CLAUDE.md:102.
- wf2 P6 C2: stop-cleanup-allowlist.sh is not "registered in settings.json's Stop list". Live settings runs it as phase 4 of
  `stop-workflow-coordinator.py` (`:40`, `:68`); only the template registers it directly (`settings.template.json:776`).
- wf2 P6 C11 (dev-command single-lane): partly fixed; `commands/dev-command.md:54` now defers to dev.md's fan-out. The residue
  is the single-lane diagram at `:20-40` (D4.f).
- X31 "9 lexers, 5 git locators" is an undercount: 16 tokenizer/stripper sites in 15 files, 7 git global-option tables,
  4 git-invocation iterators (D3.a, D3.b).
- wf2 P3 "charter: at least 2 wording variants (13 vs 8)": 23 copies, 18 distinct texts, 2 semantic families (9 "STOP and
  return the named status" vs 14 "carry a baseline_check entry").

---

## D3. Multiple truths for one thing

### D3.a Shell lexers / tokenizers / context strippers (16 sites, 15 files)

What is wrong: every Bash-reading hook re-tokenizes the command with its own rules, so the same command is "a git commit"
to one gate and "an echo" to another (T6, T8, T10).

| # | Location | Implementation | Notes |
|---|---|---|---|
| 1 | hooks/lib/bash_execution_boundary.py:621 `lex()` (+ :589 `_read_heredoc_delim`) | full bash lexer, 4,127-line module | most complete; imported only by pretool-bash-safety.sh and bash_active_syntax_census.py |
| 2 | hooks/lib/bash_context_strip.py:44 `strip_non_executable_contexts`, :140 `_split_top_level`, :179 `_tokenize_segment`, :406 `_process_heredocs` (regex :27) | quote/heredoc/interp stripper | used by bash-safety, git_command_classifier callers, branch firewall |
| 3 | hooks/lib/grepguard_context_strip.py:42 `_scan_heredoc_openers`, :178 `_process_heredocs`, :210 `strip_non_executable_contexts` | SAME public name as #2, different semantics (T6: 6/7 differ) | used only by pretool-grep-backtrack-guard.py |
| 4 | hooks/lib/git_clean_guard.py:213 `_lex`, :418 `_split_segments` | its own word lexer with `dynamic` flags | used only by bash-safety |
| 5 | hooks/lib/git_command_classifier.py:62 `_segments` | quote-blind separator split; docstring :589-593 says callers must pre-strip | imported by bash-safety (:2477-2478), branch firewall (:101-104), git-privilege-guard (:166-171), push-analyst-grant-guard |
| 6 | hooks/lib/bash_write_targets.py:136 `command_without_heredoc_bodies`, :306 `_strip_quoted_regions`, :431 `_strip_comment_regions`, :818 `_segment_end`, :826 `_segment_tokens` | write-target lexer | 7 importers (tool-policy, cp-state-write-guard, overnight-hook-guard, overwrite-guard, wrapper-userintent, attribution_journal, overnight-init.sh) |
| 7 | hooks/lib/agent_temp_targets.py:35 `_tokens` (shlex), :45 `_segments` | shlex punctuation lexer | no non-test importer (dead; E1) |
| 8 | hooks/lib/runtime_guard/shell_lex.py:23 `_split_pipeline`, :117 `_strip_compound_delims`, :234 `_safe_shlex`; runtime_guard/_core.py:2437 `_segments` | runtime_guard's own lexer | 7 runtime_guard modules |
| 9 | hooks/lib/allowlist.py:435 `_bash_subcommands` | `str.replace` split on `|| && ; |` (T10) | the grant matcher, docstring calls the module "single source of truth" (:3) |
| 10 | hooks/pretool-grep-backtrack-guard.py:206 `_tokenize_segments` (shlex :223) | own lexer | |
| 11 | hooks/pretool-block-branch-pr-worktree.py:525 `_classify_segment` | whitespace tokens over #5 segments | |
| 12 | hooks/pretool-bash-safety.sh:129 `strip_shell_prelude_for_compose`; :1439 `tokenize_or_deny` (embedded python shlex :1440) | two more inside the 2,850-line hook | |
| 13 | hooks/userprompt-consent-allowlist.sh:269 | `shlex.split(body, posix=False)` | /allow argument parsing (grant producer) |
| 14 | hooks/pretool-orchestrator-prompt-purity.py:105, :115, :158 | heredoc/redirect regexes | |
| 15 | hooks/pretool-wrapper-userintent.py:40-42 | fallback stub `command_without_heredoc_bodies = lambda c: c` when #6 fails to import | silently changes semantics |
| 16 | scripts/check-public-core.sh:160 `sh_heredocs` | heredoc scanner | |

Acknowledged drift inside the code: pretool-bash-safety.sh:1069-1077 (an earlier "Mirrors Layer 1.E2 exactly" claim was false).

Canonical choice: bash_context_strip.strip_non_executable_contexts as the ONE normaliser and git_command_classifier._segments as
the ONE segmenter over normalised text (they are already the most widely imported pair and are what bash-safety uses).
bash_execution_boundary.lex stays as bash-safety's deep analyser; unifying #4/#6/#8 onto it is optional follow-up (L, hold).

Minimal fix:
1. `classify_git_command()` / `iter_git_invocations()` normalise their own input (call strip_non_executable_contexts inside),
   so no caller can feed raw text (fixes T8 at git-privilege-guard.py:2398 and every future caller).
2. Delete grepguard_context_strip.py's private copy: grep-backtrack-guard imports #2 (add its comment-stripping as a flag of #2).
3. Replace allowlist._bash_subcommands with `_segments(strip_non_executable_contexts(cmd))`.
4. Remove the fallback stub #15 (import failure must fail closed, like tool-policy's bootstrap).
5. #7 is dead code: hand to E1.

### D3.b Git command locators and git global-option tables (7 tables, 4 iterators)

| # | Location | Members / behaviour |
|---|---|---|
| 1 | hooks/lib/git_command_classifier.py:361-364 `_GIT_GLOBAL_VALUE` | `-C -c --git-dir --work-tree --namespace --exec-path --super-prefix --config-env`; `_git_subcommand` :367-379 treats every other `-x` as a flag |
| 2 | hooks/lib/bash_execution_boundary.py:1438-1444 `GIT_GLOBAL` | value opts add `--attr-source`; flags add `--html-path --man-path --info-path --version --help -v -h --no-lazy-fetch` |
| 3 | hooks/lib/git_clean_guard.py:134-138 `_REDIRECT_FLAGS` + `_NEUTRAL_GLOBALS_WITH_ARG`, special cases :546 (fused `-C<dir>`), :553-556 (`-c`/`--config-env`) | splits the same set by "redirect" meaning |
| 4 | hooks/lib/runtime_guard/git_cmds.py:42-45 `_GIT_GLOBAL_OPTS_WITH_ARG` | lacks `--config-env` (T7: `--config-env x=y commit` -> subcommand `x=y`) |
| 5 | hooks/pretool-overnight-hook-guard.py:1235-1237 `_GIT_GLOBAL_OPTS_WITH_OPERAND` | 5 members; `-c` handled separately |
| 6 | hooks/pretool-git-privilege-guard.py:181-188 `GIT_GLOBAL_OPTION_RE` (regex) used by :189, :204-206, :211-213 | accepts fused `-C\S+`; the SAME file also imports #1 at :170 (two truths in one file) |
| 7 | hooks/lib/allowlist.py:463-471 `_GRANT_SKIPPABLE_*` (comment :442-462) | deliberate authorization subset (correct to differ); but its comment asserts git has NO fused `-C<dir>` form, contradicting #3 and #6 |

Iterators over git invocations: git_command_classifier.py:577 `iter_git_invocations`; pretool-overnight-hook-guard.py:1125
`_iter_git_invocations` (own cd-tracking parser); git_clean_guard.py:529 `_git_invocation`; runtime_guard/git_cmds.py:57
`_git_subcommand_index`. Plus regex-only detection: pretool-bash-safety.sh:1328, :2075-2076, :2099, :2129, :2167, :2781,
:2821, :2829-2832 (13 `grep -qE 'git\s+...'` lines on raw `$COMMAND`), and git-privilege-guard's own segment loops
:946, :1655.

Git root locators (same decision, many copies): 44 `rev-parse --show-toplevel` sites in 31 files and 11
`--git-common-dir` sites in 7 files (Appendix A/B); named helpers pretool-gitignore-preflight.py:701 `get_repo_root`,
prompt-workflow.py:48 `_try_git_toplevel`, scripts/close-report-append.py:214 and scripts/close-scoring-decide.py:61
`_resolve_repo_root` (two copies), scripts/resolve-commit-repos.py:70 `_repo_root`, hooks/lib/overnight.py:83.

Canonical choice: git_command_classifier (#1 table, `iter_git_invocations`) for "which git verb runs"; allowlist #7 stays a
policy subset, asserted `⊆ #1` at import.

Minimal fix: one table in git_command_classifier corrected to real git grammar (union of #1/#2: add `--attr-source`; treat
`--exec-path`, `--super-prefix`, `--config-env` as `=`-attached only), imported by #3, #4, #5 and used to build #6's regex;
fix allowlist's comment. Iterator merge (#5's cd-tracking into the classifier) is optional follow-up.

### D3.c Grant / consent / sentinel namespaces and the state-dir resolver (split brain)

What is wrong: one logical fact (for example "the user typed /do this turn") is written once and re-derived by 16 readers
with 3 semantics and 2 locations (T1-T3).

/do consent flag `claude-orchestrator-consent-<sid>.flag` (writer hooks/prompt-workflow.py:1410; clearers
hooks/stop-cleanup-allowlist.sh:35, hooks/stop-do-report-gate.py:128):

| Reader | Location | Semantics |
|---|---|---|
| hooks/pretool-git-privilege-guard.py:274 | **literal `/tmp`** | content == "true" (T2: ignores CLAUDE_STATE_DIR) |
| hooks/pretool-bash-safety.sh:871-873 | resolver | content == "true", sid fallback "default" |
| hooks/pretool-bash-safety.sh:2713, :2755 | resolver | **existence only** |
| hooks/pretool-block-background-tasks.py:153 | resolver | **existence only** |
| hooks/pretool-aggregate-check.py:684-686 | resolver | content == "true", sid from env, fallback "default" |
| hooks/pretool-block-branch-pr-worktree.py:589 | resolver | content == "true" |
| hooks/pretool-block-enterworktree.sh:59-61 | resolver | content == "true", fallback "default" |
| hooks/pretool-do-block-subagents.py:92 | resolver | content == "true" |
| hooks/pretool-orchestrator-gate.py:77 | resolver | content == "true", fallback "default" (:68-73) |
| hooks/pretool-read-size-guard.py:27 | resolver | content == "true" |
| hooks/pretool-subagent-enforce.py:52 | resolver | content == "true" |
| hooks/pretool-write-guard.sh:59-61 | resolver | content == "true", fallback "default" |
| scripts/install/tmp-cleanup-install.sh:163 | literal | cleanup |

Other namespaces and their path truth (writer -> readers):
- legacy `/allow` grant `claude-bash-allowlist-<sid>.json` AND structured sentinel `claude-grants/<task_id>.json`: two
  channels for one /allow (allowlist.py:17-23; writer userprompt-consent-allowlist.sh:70-72, :654, :711-714; readers
  allowlist.py:139-147, :216, :290, posttool-allowlist-consume.py:848-857, bash-safety.sh:451, enterworktree.sh:66,
  write-guard.sh:131). Sentinel task key = `CLAUDE_TASK_ID` or sid (userprompt-consent-allowlist.sh:711;
  pretool-block-branch-pr-worktree.py:603; pretool-git-privilege-guard.py:294); CLAUDE_TASK_ID is never set (A sibling).
- commit grant: writer scripts/write-commit-grant.py `--output-dir` default **`/tmp`** (:264-267) while the same script reads
  the user-intent sentinel through the resolver (:433-440, :460); readers pretool-git-privilege-guard.py:328, :372, :406,
  :636, :1406-1407 (literal `/tmp`); consumer posttool-allowlist-consume.py:55-56, :428-467; reaper
  stop-cleanup-allowlist.sh:294, :312; scripts/dev-fix.py:1725.
- bulk-commit sentinel: writer scripts/write-bulk-commit-sentinel.py:45-48 (default `/tmp`); readers
  pretool-git-privilege-guard.py:1358-1360, pretool-bash-safety.sh:1390, :1686, pretool-write-guard.sh:25-26; reaper
  stop-cleanup-allowlist.sh:62 (all literal `/tmp`).
- push grant `claude-push-grant-<sid>-*`: pretool-git-privilege-guard.py:2093 (literal), hooks/push.sh:369.
- merge-analyst / push-analyst tokens `/tmp/agentic-commit/...`: pretool-git-privilege-guard.py:1954, :1968;
  scripts/execute-push.py:35; hooks/lib/commit_journal.py:64, :109; posttool-push-gate-token-verify.py:45;
  pretool-push-analyst-grant-guard.py:26, :73; hooks/push.sh:106, :212.
- residual override dir: pretool-git-privilege-guard.py:2237 and scripts/write-git-residual-override.py:39 (literal).
- user-intent sentinels: commit_pipeline.py:20 / prompt-workflow.py:1448 / write-commit-grant.py:460 (resolver) vs
  pretool-wrapper-userintent.py:12, :115 (generic `claude-<name>-userintent-`), scripts/break-overnight-lock.py:35, :47-52
  (`CLAUDE_USERINTENT_SENTINEL_DIR` default `/tmp`, a separate env knob).
- daemon-restart grants: pretool-bash-safety.sh:18, :545, :577-578.
- restart grant: hooks/lib/subagent_restart.py:155 (under `~/.claude/restart-state`, not the resolver).
- git blessed token: hooks/git-keystone/reference-transaction:51 and scripts/mint-git-blessed-token.sh:39 keyed on
  **`TMPDIR`** (which harness_state_dir.py:13-16 explicitly rejects because writer and reader would disagree).
- forced-close flag: subagentstop-artifact-contract-enforce.py:266 `LEGACY_FLAG_DIR = "/tmp"`, :343; subagentstop-e2e-enforce.py:387.
- do task sidecar / reservation / gate counter: prompt-workflow.py:1325-1350, :1421-1427; stop-do-report-gate.py:150-169, :210
  (resolver) vs commands/do.md:57-59 (tells the agent to read/write literal `/tmp/...`).

State/root resolvers (one decision, nine answers):
- hooks/lib/harness_state_dir.py:29-37 and its shell twin hooks/lib/harness_state_dir.sh:9-20 (canonical; default `/tmp`).
- fallback stubs that drop CLAUDE_STATE_DIR on import failure: hooks/prompt-workflow.py:41-45, hooks/stop-overnight-timelock.py:37-40.
- hooks/lib/capability_state.py:195-208 (`CLAUDE_CAPABILITY_STATE_DIR`, then **XDG_RUNTIME_DIR**, then resolver).
- hooks/lib/subagent_restart.py:146-150 and a verbatim copy hooks/sessionstart-artifact-census.py:53-55 (`~/.claude/restart-state`).
- hooks/lib/attribution_journal.py:89-91 (`<harness>/state/attribution-journal`).
- hooks/doc_sync/notice.py:340-344 (`tempfile.gettempdir()`, i.e. TMPDIR-keyed).
- scripts/graphify_lib.py:137 (`/var/tmp/claude-graphify`).
- hooks/lib/commit_pipeline.py:144-154 (delegates to the resolver; correct, and its docstring records the historical writer/reader
  disagreement).

Canonical choice: hooks/lib/harness_state_dir.py for every grant/consent/sentinel namespace; hooks/lib/allowlist.py (already the
"grant-read" library) gains `has_do_consent(payload)`.

Minimal fix: (1) add `has_do_consent(payload)` to allowlist.py (agent_id via lib.subagent, resolver path, content=="true") and
replace the 13 readers; (2) replace every literal `/tmp` grant path in git-privilege-guard (14 lines), bash-safety (:1390,
:1686), write-guard.sh:25, stop-cleanup-allowlist.sh:62, and the `/tmp` defaults of write-bulk-commit-sentinel.py,
write-commit-grant.py, write-git-residual-override.py, break-overnight-lock.py, execute-push.py with the resolver; (3) delete the
two fallback stubs; (4) git-keystone + mint-git-blessed-token use the resolver instead of TMPDIR. No namespace is added or
removed (grant-sprawl reduction is X30/F-cluster work).

### D3.d "Am I a subagent?" readers (agent_id) (≈40 sites)

Canonical module hooks/lib/subagent.py:1-3 calls itself the "single source of truth" (`is_subagent_context`, :63-80: agent_id
OR subagent_id/agent_path/parent_agent_id OR env aliases OR transcript meta), but only 3 hooks use it:
pretool-do-block-subagents.py:71/:152, pretool-orchestrator-gate.py:40/:202, pretool-subagent-enforce.py:38/:322/:326.
A fourth private variant: pretool-workflow-gate.py:209 `codex_payload_is_subagent_context`. Everyone else re-derives it:

- python truthiness `data.get('agent_id')`: doc_sync/hook_ledger.py:220, doc_sync/notice.py:333, posttool-codex-skill-ledger.py:71,
  posttool-todo-count.py:73, posttool-todo-sequence.py:240, posttool-todo-tracker.py:69, pretool-aggregate-check.py:682, :693,
  pretool-block-branch-pr-worktree.py:583, :609, :639, pretool-git-privilege-guard.py:268, :296, :1480,
  pretool-grep-backtrack-guard.py:1191, pretool-orchestrator-prompt-purity.py:362, pretool-overnight-hook-guard.py:170, :983,
  pretool-read-size-guard.py:37, :70, pretool-spec-block-foreground-agent.py:81, pretool-subagent-code-block.py:67,
  pretool-todo-validate.py:286, pretool-tool-policy.py:167, :218, stop-workflow-coordinator.py:200,
  subagentstop-artifact-contract-enforce.py:780, subagentstop-codex-enforce.py:53, subagentstop-e2e-enforce.py:341,
  userprompt-restart-authorize.py:131, lib/attribution_journal.py:334-335.
- alias variant `agent_id or agentId`: pretool-block-background-tasks.py:139.
- agent_id OR top-level subagent_type (exempts nothing correctly, see A4): pretool-cp-state-write-guard.py:126-131.
- four byte-identical shell one-liners `print('1' if d.get('agent_id') else '0')`: pretool-bash-safety.sh:121,
  pretool-write-guard.sh:52, pretool-block-enterworktree.sh:52, userprompt-consent-allowlist.sh:38.

Effect: in a payload with an alias field but no agent_id (the case lib/subagent.py exists for), the orchestrator gate exempts
the caller while bash-safety, write-guard and git-privilege-guard treat it as the main agent. CLAUDE.md:61 and :62 describe
two different predicates ("agent_id present", "agent_id truthy").

Canonical choice: lib/subagent.is_subagent_context (identity); role comes from A4's fix (payload.agent_type), not from here.
Minimal fix: replace every direct read above with the import; give subagent.py a `__main__` that prints 1/0 so the 4 shell hooks
call it instead of carrying the one-liner. Depends on A4 for role, not for this predicate.

### D3.e Harness-home and project-dir resolvers

Harness home (where the harness code lives), 6 schemes:
- hooks/lib/claude_home.py:171 + `resolve()` (structural sentinel walk; env CLAUDE_HOME honoured only if realpath equals the walk)
  and its shell twin hooks/lib/claude_home.sh:87, :102.
- hooks/lib/capability_state.py:185-191 `harness_home()` (trusts CLAUDE_HOME unconditionally, else `__file__` parents): gives a
  different answer from claude_home whenever CLAUDE_HOME points elsewhere.
- hooks/lib/attribution_journal.py:81-85 `harness_root()` (`ATTRIBUTION_HARNESS_ROOT`, else `__file__` parents).
- pretool-bash-safety.sh:8, :83-106 self-resolution (the "gold standard" claude_home.py:4-6 says it generalises).
- scripts/close-scoring-decide.py:61, scripts/close-report-append.py:214 `_resolve_repo_root` (copies).
- ad-hoc `~/.claude` literals: 36 `Path.home()/".claude"` sites, 61 `$HOME/.claude` sites, 2 `expanduser("~/.claude")` sites
  (Appendix F; their portability is C1's, their multiplicity is D3's).

Project dir (where the product repo is), 17 functions, 4 fallback orders:
- env -> harness home -> cwd: hooks/lib/claude_home.py:171-185 `project_dir()`; callers closeout.py:47, policy_registry.py:162,
  specialist_yield.py:65, pretool-tool-policy.py:120, posttool-overnight-trace.py:67. When CLAUDE_PROJECT_DIR is unset (the
  Bash-tool environment, see B1.g) this resolves to the HARNESS, not the product.
- env -> cwd: contract_runtime.py:1097, posttool-lane-completeness-watch.py:90, pretool-claude-config-guard.py:70,
  pretool-obligation-gate.py:81, sessionstart-artifact-census.py:49, scripts/graphify_lib.py:129,
  scripts/restart-subagents.py:46, scripts/spec-check.py:247, pretool-overnight-hook-guard.py:133.
- env -> payload.cwd -> getcwd -> git toplevel -> harness home: prompt-workflow.py:62.
- env -> git toplevel(cwd) -> cwd: scripts/close-scoring-decide.py:82.
- plus session_resources.py:152 `_project_root`.

Canonical choice: claude_home (home) and one `claude_home.project_dir(payload=None)` with ONE order: env -> payload.cwd ->
git toplevel(cwd) -> cwd, never the harness home. Minimal fix: change claude_home.project_dir's order, route the 16 other
functions to it, delete capability_state.harness_home / attribution_journal.harness_root in favour of claude_home.resolve.
Depends on B1 (completion-gate root) and C1 (literal paths).

### D3.f Agent roster lists (who is an agent)

- hooks/pretool-cp-checkin.py:62-82 `CP_AGENTS` (canonical in practice; scripts/overnight-init.sh:208-240 AST-parses it).
- scripts/spec-check.py:91-110 `ALLOWED_AGENTS` (hand copy).
- hooks/prompt-workflow.py:1516-1528 `agent_types` (hand copy, 18 names).
- commands/dev.md:202-204 fallback loop (17 names, no graphify); commands/dev-command.md:146-148 fallback loop (16 names, no
  test-writer, no graphify): following the fallback breaks the graphify/test-writer FIRST ACTION reads.
- hooks/lib/obligation.py:74-80 `ROLES` vs hooks/pretool-obligation-gate.py:70-76 `PRODUCER_ROLES` (A sibling).
- hooks/subagentstop-codex-enforce.py:31 `ENFORCED_AGENT_TYPES`; policies/tool-policy.v1.json `roles` (24 incl. general-purpose).

Canonical choice: CP_AGENTS (move it to hooks/lib, e.g. obligation.py or a constant in agent_resolver.py, since overnight-init
already reads it). Minimal fix: spec-check and prompt-workflow import it; the two prose fallback loops are replaced by "re-run
the command" (the hook is the only producer of the registry).

### D3.g Hand-copied prompt blocks (≈2,500 duplicated lines, 12.7% of 19,647 non-blank prompt lines)

Measured this session: lines of ≥25 chars that occur in ≥2 of the 45 prompt files = 2,497 (12.7%).
commands/dev-command.md is a drifted fork of commands/dev.md: 486 of its 628 substantive lines are verbatim dev.md lines (77%).

Block families (file:start-end, line count, content hash; every family has drifted, see variant counts):
- **charter: 23 copies, 146 lines, 18 distinct variants**: agents/architect.md:8-13 (6L, v=cce3ddcb); agents/ba.md:8-21 (14L, v=86e1def7); agents/changelog-analyst.md:6-11 (6L, v=a30c4034); agents/cleaner.md:6-11 (6L, v=403c279d); agents/cleanliness-inspector.md:6-11 (6L, v=1cb6e67a); agents/dev.md:6-11 (6L, v=1625f0d6); agents/git-edge-case-analyst.md:6-11 (6L, v=6f65cb33); agents/graphify.md:6-11 (6L, v=878ac6a8); agents/merge-analyst.md:6-11 (6L, v=922a2f4c); agents/pm.md:11-16 (6L, v=1d20cba5); agents/product-owner.md:8-13 (6L, v=6f65cb33); agents/prompt-inspector.md:6-11 (6L, v=1cb6e67a); agents/pull-analyst.md:6-11 (6L, v=2024e9d1); agents/push-analyst.md:6-11 (6L, v=6340431c); agents/qa.md:8-13 (6L, v=086dc62f); agents/rule-inspector.md:6-11 (6L, v=b766380f); agents/spec.md:6-11 (6L, v=552d71e2); agents/style-inspector.md:6-11 (6L, v=1cb6e67a); agents/test-executor.md:6-11 (6L, v=2d70e352); agents/test-validator.md:6-11 (6L, v=2d70e352); agents/test-writer.md:6-11 (6L, v=2d70e352); agents/ui-specialist.md:6-11 (6L, v=35dd28df); agents/user.md:8-13 (6L, v=8820019f); 
- **antigiveup: 6 copies, 174 lines, 1 distinct variants**: agents/architect.md:14-42 (29L, v=7fd05dac); agents/pm.md:74-102 (29L, v=7fd05dac); agents/product-owner.md:14-42 (29L, v=7fd05dac); agents/qa.md:28-56 (29L, v=7fd05dac); agents/ui-specialist.md:23-51 (29L, v=7fd05dac); agents/user.md:14-42 (29L, v=7fd05dac); 
- **checkpoint: 17 copies, 413 lines, 17 distinct variants**: agents/architect.md:398-417 (20L, v=daad7340); agents/ba.md:1335-1374 (40L, v=f9a12d93); agents/cleaner.md:172-195 (24L, v=b45e174c); agents/cleanliness-inspector.md:365-389 (25L, v=ba6ef3b9); agents/dev.md:1054-1085 (32L, v=d51fdabc); agents/git-edge-case-analyst.md:253-276 (24L, v=ca0df871); agents/pm.md:1052-1071 (20L, v=b27929df); agents/product-owner.md:414-433 (20L, v=83e3bbe2); agents/prompt-inspector.md:230-254 (25L, v=691c643d); agents/qa.md:1931-1962 (32L, v=af2b5e91); agents/rule-inspector.md:186-209 (24L, v=c9ba15fb); agents/spec.md:802-824 (23L, v=d7bd789e); agents/style-inspector.md:660-684 (25L, v=a385cc86); agents/test-executor.md:401-424 (24L, v=403d0bcf); agents/test-validator.md:327-350 (24L, v=270c7974); agents/ui-specialist.md:281-291 (11L, v=3ac034ec); agents/user.md:520-539 (20L, v=8670a5e6); 
- **codex: 12 copies, 707 lines, 12 distinct variants**: agents/architect.md:418-474 (57L, v=968c840d); agents/ba.md:1375-1443 (69L, v=87f63752); agents/cleanliness-inspector.md:390-445 (56L, v=d0771508); agents/dev.md:944-1003 (60L, v=daa71ae1); agents/pm.md:1072-1133 (62L, v=9de4ea33); agents/product-owner.md:434-490 (57L, v=3df0d21f); agents/prompt-inspector.md:255-310 (56L, v=1fe1f4d4); agents/qa.md:1317-1377 (61L, v=0572e9c6); agents/spec.md:741-801 (61L, v=063dc98d); agents/style-inspector.md:685-740 (56L, v=aff70fb2); agents/ui-specialist.md:292-346 (55L, v=137ea108); agents/user.md:540-596 (57L, v=a244312b); 
- **overnight_spec: 4 copies, 144 lines, 4 distinct variants**: agents/ba.md:1480-1507 (28L, v=d06cd613); agents/dev.md:1019-1053 (35L, v=6d1cbb6d); agents/pm.md:1016-1051 (36L, v=b177a296); agents/qa.md:1886-1930 (45L, v=684b029d); 
- **specialist_intake: 2 copies, 104 lines, 2 distinct variants**: agents/ba.md:1205-1251 (47L, v=fffd85ae); agents/pm.md:1134-1190 (57L, v=1ff739fe); 
- **score_echo: 3 copies, 45 lines, 3 distinct variants**: agents/ba.md:796-810 (15L, v=6346ad0c); agents/dev.md:501-515 (15L, v=bcdfd64c); agents/qa.md:1378-1392 (15L, v=2a66446c); 
- **json_storage: 3 copies, 44 lines, 2 distinct variants**: commands/dev-command.md:963-981 (19L, v=ea968ce0); commands/dev-overnight.md:1868-1873 (6L, v=0178d68e); commands/dev.md:1460-1478 (19L, v=ea968ce0); 
- **integration_clean: 2 copies, 22 lines, 1 distinct variants**: commands/dev-command.md:982-992 (11L, v=2a1b42c7); commands/dev.md:1479-1489 (11L, v=2a1b42c7); 
- **agent_dev_use_cases: 2 copies, 224 lines, 2 distinct variants**: commands/dev-command.md:1018-1112 (95L, v=0e4328f6); commands/dev.md:1513-1641 (129L, v=126d44b9); 
- **example_e2e: 2 copies, 92 lines, 2 distinct variants**: commands/dev-command.md:1113-1162 (50L, v=10e2d368); commands/dev.md:1642-1683 (42L, v=c54ed10f); 
- **success_metrics: 2 copies, 29 lines, 2 distinct variants**: commands/dev-command.md:1163-1176 (14L, v=a0faf5e4); commands/dev.md:1684-1698 (15L, v=eb068b14);

Orchestrator-side copies (hand ranges, headings are mis-nested so the generic scan over-reads them):
- "Four Contracts Awareness (Orchestrator Role)" incl. "Layer vocabulary (shared with BA)": commands/dev.md:326-421 (96L),
  commands/dev-command.md:257-320 (64L), commands/dev-overnight.md:386-459 (74L); the BA-side master is agents/ba.md:221-419.
- cp-state lifecycle SOP "(canonical path)" x3 with three different invocation forms: agents/ba.md:1341-1374 (venv-activated
  `${CLAUDE_HOME:-$HOME/.claude}`), agents/dev.md:1060-1084 (`python3 ~/.claude/...`), agents/qa.md:1937-1961 (`$CLAUDE_HOME`);
  plus agents/spec.md:595-663 "Writing cp-state files".
- "Per-Subagent Single-Task Rule (MANDATORY)": commands/dev.md:65-76, commands/dev-command.md:57-66 (restating CLAUDE.md:33).
- dispatch envelope `FIRST ACTION` / `SECOND ACTION` lines: 66 occurrences (dev.md 18, dev-overnight.md 21, dev-command.md 14,
  close.md 12, graphify.md 1; Appendix G). SECOND ACTION path has three spellings: `$CP_DIR/cp-state-<agent>.json`
  (dev-command.md:186), `$CP_STATE_DIR/...` (dev.md:235), `.claude/specs/<SPEC_ID>/cp-state-<agent>.json` (dev.md:307, :437).
- obligation block template `<obligation v="1">`: 34 occurrences (close.md 11, dev.md 7, dev-overnight.md 7, dev-command.md 6,
  commit.md 2, changelog-analyst.md 1; Appendix H), each a hand instantiation of schemas/obligation.v1.json.
- score-inject: the INJECTION_PROOF contract is emitted twice inside scripts/score-inject.sh (:51-57 heredoc and :103-109
  python) and restated in agents/ba.md:796-810, agents/dev.md:501-515, agents/qa.md:1378-1392; the three score header insertion
  blocks commands/dev.md:426, :464, :846, :876, :1008, :1027.
- `--codex` flag parsing / `codex_required: true` propagation: clean.md (5), close.md (7), dev-overnight.md (5), spec.md (4),
  dev.md (3), dev-command.md (2), redev.md (1).

Canonical choice: one fragment per family under a single source directory, rendered into the agent/command files by one
script with a `--check` mode (precedent: scripts/install/render-settings). For commands, Claude Code's native `@file` include
is an alternative.

Minimal fix (no wording change in the first pass, so E3's diet then edits one place):
1. Extract charter (2 variants: producer/reviewer), codex (1 generic text; the source-command list removed), checkpoint
   contract + cp-state SOP (1 text, role substituted), Anti-Give-Up, Overnight Spec Integration, Specialist Intake, score echo.
2. dev-command.md: replace the 486 copied lines with "same as /dev Step N" pointers or render both from shared fragments.
3. FIRST ACTION lines: delete after A4 lands (role comes from payload.agent_type, so the sentinel Read that exists only to
   self-declare identity is no longer needed); until then render from one fragment. SECOND ACTION (load the cp-state
   checklist) stays, rendered from one fragment with one path spelling.
4. score-inject.sh: one emitter function, used by both branches.

### D3.h Duplicated hook helpers

- run_todo_script x4: hooks/lib/todo_canonical.py:45 (canonical; used by pretool-todo-validate.py:32, posttool-subagent-track.py:40)
  vs copies hooks/posttool-todo-count.py:21, hooks/posttool-todo-tracker.py:23, hooks/prompt-workflow.py:330.
- the same 5 todo rules twice: hooks/pretool-todo-validate.py:45-113 (immutability, one completion, skip, single in_progress,
  ordering) and hooks/posttool-todo-sequence.py:27-107 (Rules 1-5).
- protected-path regex list twice with drift (`\S*` vs `.*`): hooks/pretool-claude-config-guard.py:48-56 (+ `_CMD_PATTERNS`
  :57-) vs hooks/pretool-overnight-hook-guard.py:753-761.
- /spec interview detection twice: hooks/pretool-block-background-tasks.py:79-118 ("identical to spec-block's", :86) vs
  hooks/pretool-spec-block-foreground-agent.py:49-54.
- byte-identical hooks: hooks/posttool-git-warn.sh == hooks/post-commit-warn.sh (cmp), and posttool-git-warn.sh is registered
  with matcher `Bash\(git commit.*\)` (settings.json and settings.template.json PostToolUse), which never equals a tool name.
- mutual delegation: hooks/pretool-tool-policy.py:350-356 exits 0 on an unresolved role "defer to the backstop shim"; the shim
  hooks/pretool-subagent-code-block.py:2-9 says "Canonical enforcement: pretool-tool-policy.py ... this shim only emits a
  warning". Each names the other as the enforcer (A4 owns the role fix).
- CLOSE FORCED verdict spelled twice: commands/close.md:787 `CLOSE: YES (FORCED)` vs agents/changelog-analyst.md:1309
  `CLOSE: YES — FORCED (bulk mode ...)`; scripts/close-scoring-decide.py:187-191 matches case-insensitively to cover both.
- close_route_finding (commands/close.md:194) vs undefined `route_finding` (commands/commit.md:307, :317, :336, :357) (B/D2 own
  the break; here it is one routine with two names).

Minimal fix: delete the three run_todo_script copies (import lib); move the 5 rule functions into lib/todo_canonical and import
from both hooks; one protected-path list in hooks/lib (policy_registry.py already holds protected prefixes); one
`spec_interview_active()` in lib; the twin warn hook and its dead matcher go to E1/D1.

### D3.i Documentation and configuration truths (counts, registrations, installers)

- Hook registrations: settings.json 83 entries vs settings.template.json 73 vs README.md:564-573 table (SessionStart 7,
  UPS 6, PreToolUse 30, PostToolUse 15, Stop 4, SubagentStop 7; no SessionEnd) vs ARCHITECTURE.md:162-167. Live-only:
  pretool-obligation-gate.py (G1), subagentstop-artifact-contract-enforce.py (G2), stop-obligation-gate.py,
  stop-completion-gate.py, stop-do-report-gate.py (G4), stop-workflow-coordinator.py, pretool-do-block-subagents.py,
  pretool-commit-dispatch-attest.py, pretool-push-analyst-grant-guard.py, posttool-push-gate-token-verify.py,
  posttool-lane-completeness-watch.py, session-scratch-init.sh, sessionend-scratch-sweep.sh, userprompt-usage-snapshot.py.
  Template-only Stop: auto-commit.sh, stop-cleanup-allowlist.sh, stop-overnight-timelock.py, stop-spec-coverage-enforce.py.
  Consequence for the architecture: **a user who installs the published product from the template gets none of the producer
  gates G1/G2/G4**. (Drift itself is C2's; listed here because it is the largest "two truths" in the repo.)
- Counts: commands 21 on disk vs "20 slash commands" (README.md:326, ARCHITECTURE.md:118; /tickets missing from README's list);
  ARCHITECTURE.md:121 "scripts/ (95 helpers)" vs 156 .py/.sh/.mjs files under scripts/; ARCHITECTURE.md:119 says agents carry `tools`
  frontmatter, 0 of 23 do.
- Installers: README.md:66-84 (`scripts/install/install`), README.md:94-100 (`scripts/bootstrap`, "never over ~/.claude"),
  README.md:598 ("each developer clones it to their own ~/.claude"), hooks/install.sh, hooks/install-protection-all.sh,
  hooks/install-git-hooks.sh, hooks/install-auto-sync.sh (C2 owns).
- Ownership ledger vs journal: agents/dev.md:545-592 owned_edits MANDATORY vs agents/changelog-analyst.md:771 "the journal
  replaces the owned-edits ledger" vs scripts/resolve-commit-repos.py:610 still gating on owned_edits (A sibling, A3).
- files_created truth: agents/dev.md:522-527 (from git status) vs commands/do.md:80 ("NOT derived from git diff") (A3).

Fix: C2 renders settings from the template (+ overlay) and README/ARCHITECTURE tables are generated from settings (or deleted);
counts are dropped from prose. Nothing here adds state.

---

## D4. Contradictions between prose, CLAUDE.md and actual hook/script behaviour

Notation: "prose side" -> "code side". Each row is verified at 09ab15b (T-numbers = executed above).

### D4.a CLAUDE.md (always loaded) is wrong or contradicts other prose

| # | Prose side | Code / other side | What is wrong |
|---|---|---|---|
| a1 | CLAUDE.md:57 "Bash capped at 5 consecutive same-name calls" (also ARCHITECTURE.md:134, README.md:187 partly correct) | hooks/pretool-orchestrator-gate.py:13-21, :128-149, :233-241 | the count is Bash calls since the last Agent dispatch; Read/Grep between do not reset it (T4) |
| a2 | CLAUDE.md:58 "once TOTAL per tool name per turn" | gate :156-159 counts until hooks/stop-cleanup-allowlist.sh:40 deletes the file, which runs only after a successful Stop (coordinator :262-277) | "per turn" is false after any blocked/interrupted Stop (B3.c) |
| a3 | CLAUDE.md:59-60 "Permanently blocked ... even with /do"; CLAUDE.md:60 "/do this session" | gate :162-169 message "run /do to unlock" (T5); gate :243-253 lets `/allow` rescue perm-blocked tools; stop-cleanup-allowlist.sh:32-39 clears consent every Stop | the block message contradicts the rule; /allow exception undocumented; /do is per turn, not per session (B3.d user decision) |
| a4 | CLAUDE.md:61 "For files >600 lines, delegate and ask for a summary — never request raw contents" | hooks/pretool-read-size-guard.py:53-56, :81-82 allow offset+limit chunks ≤600; its block text :87-89 says "retry with offset+limit" | hook and CLAUDE.md give opposite instructions |
| a5 | CLAUDE.md:61 "Subagents (`agent_id` present)"; :62 "(`agent_id` truthy)" | gate uses lib/subagent.py:63-80 (aliases, env, transcript) | two predicates in one paragraph, a third in code (D3.d) |
| a6 | CLAUDE.md:61 "Streak state at /tmp/claude-tool-streak-<sid>.json" (also ARCHITECTURE.md:138, :155) | gate :84-85 `harness_state_dir()` | path is CLAUDE_STATE_DIR-relative |
| a7 | CLAUDE.md:62 "MUST pass run_in_background: false on every dispatch" | hooks/pretool-block-background-tasks.py:52-118 exempts background Explore during /spec; commands/spec.md:74 instructs `run_in_background=true` | CLAUDE.md contradicts spec.md (the hook sides with spec.md) |
| a8 | CLAUDE.md:49 "/push requires clean tree" (also docs/reference/checkpoint-mechanism.md:177-180 "exits non-zero") | commands/push.md:36 "dirty worktree state as non-blocking"; hooks/push.sh:18-19, :302-311 "(not blocking)" | three docs, two answers |
| a9 | CLAUDE.md:86 "List / delete / rename / info forms of `git branch` ... remain allowed" | hooks/pretool-git-privilege-guard.py:34-35 + T9 (rc=2 for `-d`, `-m`, `-D`) | delete/rename are blocked for every agent caller |
| a10 | CLAUDE.md:102 sentinel at `/tmp/claude-grants/<task_id>.json` | writer userprompt-consent-allowlist.sh:712-714 `$(harness_state_dir)/claude-grants/${TASK_ID}.json` | directory is resolver-relative (name is right; see correction above) |
| a11 | CLAUDE.md:102 last sentence (and ARCHITECTURE.md:166) "stop-cleanup-allowlist.sh ... is not currently registered ... does not reap" | stop-workflow-coordinator.py:40, :68 runs it as phase "cleanup"; settings.template.json:776 registers it; allowlist.py:33-34 "called by stop-cleanup hook" | false; it runs (but only after the earlier phases pass) |
| a12 | CLAUDE.md:117 "delegate to `@deep-search` (`/deep-search`, `/research-deep`, `/search-tree`, `/reflect-search`, `/site-navigate`)" | no such agent/command/skill; settings.json:262, :282, :283, :285, :287 deny `Skill(<each>:*)` | routes work to things that are both absent and denied (D2 owns the dangling part) |
| a13 | CLAUDE.md:125 "Enforcement: pretool-orchestrator-prompt-purity.py" | hooks/pretool-orchestrator-prompt-purity.py:21-23, :39-40, :340-348 "Always exit 0 (warn-only)" | not enforcement |
| a14 | CLAUDE.md:29-30 lesson 12 "LIVE browser rendering on BOTH desktop and mobile ... NEVER sufficient" | hooks/subagentstop-e2e-enforce.py:21-25 accepts `legitimately_skipped`, `blocked_app_unavailable`, `ran`; no viewport check | the only producer gate accepts non-render outcomes |

### D4.b README.md / ARCHITECTURE.md (published docs)

| # | Prose side | Code side | What is wrong |
|---|---|---|---|
| b1 | README.md:567 "UserPromptSubmit ... prompt-purity enforcement"; README.md:583 "Enforced by pretool-orchestrator-prompt-purity.py"; ARCHITECTURE.md:144 "enforced at two points" | purity hook is PreToolUse(Agent), warn-only (:21-23) | wrong event and not enforced |
| b2 | ARCHITECTURE.md:183 and §6.1 flowchart :191 list pretool-bulk-commit-detector.py as an enforcement entry point ("catches 'sync' sweeps") | hooks/pretool-bulk-commit-detector.py:57 warn-only; README.md:243 "warn-only — it exits 0 and never blocks" | the two docs disagree; README is right |
| b3 | ARCHITECTURE.md:301 "pretool-subagent-code-block.py ... ensure the dev subagent is effectively the only writer" | hook warn-only since 2026-05-14 (:2-9); tool-policy exits 0 on unresolved role (:350-356) | nothing enforces it for unresolved roles (A4) |
| b4 | README.md:250 tool-policy "FAIL CLOSED (non-dev roles)" | pretool-tool-policy.py:348-356 exit 0 when the role is unresolved; :365-368 exit 0 on any exception | fail-open in the common case (A4) |
| b5 | ARCHITECTURE.md:152 matchers may be "a Bash-command regex (`Bash\(git commit.*\)`)" | Claude Code matches tool names; the one such registration (posttool-git-warn.sh) never fires | false platform claim |
| b6 | ARCHITECTURE.md:154 "matcher blocks run in settings.json order ... A PreToolUse chain stops at the first hook that exits 2"; §6.1 flowchart H1->H4; pretool-orchestrator-gate.py:261-271 "This gate runs FIRST, before write-guard" | Claude Code runs all matching hooks of an event in parallel (hooks reference, code.claude.com/docs/en/hooks; not executed here) | ordering premise is false; the coordinator exists for Stop precisely because of this |
| b7 | ARCHITECTURE.md:166 Stop list = timelock, coverage, auto-commit | live settings Stop = coordinator, do-report gate, obligation gate, completion gate | matches neither config (D3.i) |
| b8 | ARCHITECTURE.md:167 SubagentStop list | omits subagentstop-artifact-contract-enforce.py (G2), registered live | |
| b9 | README.md:598 "clones it to their own ~/.claude ... hooks and grants ... use $HOME-relative paths" | settings.json: 122 `/root/.claude` literals; README.md:94-95 "never over ~/.claude" | contradicts itself and the config (C1/C2) |
| b10 | README.md:326, ARCHITECTURE.md:118 "20 slash commands"; ARCHITECTURE.md:119 `tools` frontmatter; :121 "95 helpers" | 21 commands; 0 tools frontmatter; 156 .py/.sh/.mjs files under scripts/ | stale counts (D3.i) |

### D4.c Command prose vs hooks / scripts / platform

| # | Prose side | Code side | What is wrong |
|---|---|---|---|
| c1 | commands/dev.md:1747 "the hook exits with code 2 (Claude Code's blocking convention)"; :1701 "Enforcement hook" | prompt-purity :21-23, :340-348 always 0 | false |
| c2 | commands/clean.md:223 "launch a style-inspector agent ... with `run_in_background: true`" | pretool-block-background-tasks.py:7-8 (Agent blocked unless explicitly false), CLAUDE.md:62 | every /clean Step 8 dispatch is blocked |
| c3 | commands/dev.md, dev-command.md, dev-overnight.md dispatch templates (e.g. dev.md:304, :441, :635, :743; dev-command.md:329; dev-overnight.md:487) never include `run_in_background: false` | same hook; close.md:299, commit.md:151, paseo-daemon.md:43/:54 do include it | following the /dev templates literally yields exit 2 |
| c4 | commands/dev.md:235 (and the 17 agent copies in D4.d d1) "subagentstop-cp-enforce.py ... blocks (exit 2) on any pending checkpoint ... hook-enforced block" | hooks/subagentstop-cp-enforce.py:4-8, :43 ADVISORY unless `CP_ENFORCE_MODE=block`; that variable is set nowhere (settings.json, template, scripts) | the gate never blocks (UD1) |
| c5 | commands/dev-command.md:127 "The hook pretool-subagent-code-block.py blocks non-dev subagents from writing code files" | hook warn-only (:2-9) | false |
| c6 | commands/redev.md:10 "subagent enforce (Gate 4) ... canonical-todo validation, layer-escalation gate" | hooks/pretool-layer-escalation-check.sh:6, :45 "Non-blocking: always exit 0"; dev.md:1181-1200 is prose only | the "gate" is a warning |
| c7 | commands/redev.md:9 "canonical 14-step ... TodoList (hook will pre-init it)"; redev.md:19, agents/graphify.md:3, :16, agents/INDEX.md:17, agents/README.md:19 "between Step 7 and Step 8" | scripts/todo/dev.py:16-36 (17 steps, graphify Step 9); commands/dev.md:775-777 (Step 9 + a note that keeps the drift) | step model differs in 6 places |
| c8 | scripts/todo/dev.py:20 "Step 3: Consult specialists (optional)" | commands/dev.md:261-284 "always evaluate ... Skipping all 4 by default — INVALID" | the pre-initialised checklist (the hook-injected truth) contradicts the command |
| c9 | commands/do.md:53 "in advisory mode (default)" | hooks/stop-do-report-gate.py:12, :193 default "block" | inverted default (B4) |
| c10 | commands/do.md:57-59 read `/tmp/claude-do-task-$SID.json`, reserve `/tmp/claude-do-resv-$TS` | prompt-workflow.py:1325-1350, :1421-1427 write under harness_state_dir | wrong path under CLAUDE_STATE_DIR (D3.c) |
| c11 | commands/close.md:156-158 "Define these functions once" (shell state across steps; also REQUIRED_ACTIONS_JSON/CLOSE_PROGRESS_SEEN) | Claude Code's Bash tool keeps no shell state between calls; commands/dev-overnight.md:263 BINDING-EVAPORATION RULE says exactly that | two commands, two models of the shell |
| c12 | commands/dev.md:1106-1178 Step 15: orchestrator edits `.claude/settings.json` to add `Bash(...)` allow rules; "Commands created → Already allowed via SlashCommand" | policies/tool-policy.v1.json:4-12 `_shared_protected_path_prefixes` lists `/.claude/settings.json`; there is no SlashCommand permission | self-granting permissions contradicts the protected-path declaration |
| c13 | commands/dev.md 6 bash blocks before the first dispatch (:127, :157, :198, :224, :243, :253); commands/close.md 6 (:64, :161, :334, :446, :474, :506) | orchestrator gate blocks the 6th Bash since the last Agent (:64, :180-186; T4) | a literal run of the command can hit its own gate |
| c14 | commands/dev-overnight.md:1775, :1784, :1796 `/commit -m "<summary>"`, ":1800 per redev6 P-MSG, `-m` is REQUIRED" | commands/commit.md:16-38: no `-m` flag; "Remaining token (if any) is TASK_ID" | the advertised call turns `-m` into a task-id |
| c15 | commands/dev-overnight.md:1801 "For `--force` overrides on /commit (e.g. spec-only commits without ceremony artifacts)" | commands/commit.md:8, :21, :180, :239, :480 "--force is deprecated and bypasses nothing" | |
| c16 | commands/allow.md:6 "body is not injected because of `disable-model-invocation: true`" | CLAUDE.md:37-38 (dmi only stops model self-invocation); a human `/allow` still injects the body | wrong mechanism statement |
| c17 | commands/clean.md:39-43 "orchestrates three specialized subagents" | clean.md dispatches five types (rule-inspector, prompt-inspector added; counts: cleaner 14, style 9, cleanliness 5, prompt 3, rule 3 mentions) | |
| c18 | commands/dev-command.md:20-40 core diagram: one BA -> one dev -> one QA, no specialists/graphify/aggregate | dev-command.md:54 defers to dev.md fan-out; CLAUDE.md:33 | residual of prior C11 |
| c19 | docs/reference/checkpoint-mechanism.md:179-180 "Use /checkpoint ... or `git commit` (real semantic commit) before pushing" | git-privilege-guard.py:22-27 blocks agent `git commit` | instructs a blocked action |
| c20 | commands/clean.md:45 "All agents communicate via JSON in docs/clean/"; :176, :210-211, :327, :509, :534 output paths | policies/tool-policy.v1.json roles cleaner / cleanliness-inspector / style-inspector / prompt-inspector / rule-inspector: write only `*/docs/dev/<role>-*` (default deny :3); runtime proof wf2 RC1 (cleanup-execution write exit 2) | every /clean producer output path is denied to its producer |

### D4.d Agent prose vs hooks / schemas / policy

| # | Prose side | Code side | What is wrong |
|---|---|---|---|
| d1 | "subagentstop-cp-enforce.py ... BLOCKS your exit (exit 2)": agents/architect.md:410, ba.md:1361, dev.md:1080, pm.md:1064, product-owner.md:426, qa.md:1957, user.md:532, ui-specialist.md:283; "Pending checkpoints cause subagentstop-cp-enforce.py to block exit with code 2": cleaner.md:189-190, cleanliness-inspector.md:382-383, git-edge-case-analyst.md:270-271, prompt-inspector.md:247-248, rule-inspector.md:203-204, spec.md:819-820, style-inspector.md:677-678, test-executor.md:418-419, test-validator.md:344-345 | hooks/subagentstop-cp-enforce.py:4-8, :43 advisory; CP_ENFORCE_MODE unset | 17 agents + dev.md:235 = 18 false enforcement claims (UD1) |
| d2 | charter "STOP and return the matching named status — `baseline_contradiction`, `coupled_issues_merge_requested` ..." (agents/dev.md:9, qa.md:11 `verdict:`, ba.md, cleaner, graphify, spec, test-executor, test-validator, test-writer); commands/dev.md:95, :103 "a BA/Dev subagent returns `status: coupled_issues_merge_requested`" | schemas/dev-report.v2.json `dev.status` enum [completed, blocked, needs_review]; schemas/qa-report.v2.json `qa.status` [pass, fail, warning]; no hook or schema knows `multi_issue_fanout_requested` / `coupled_issues_merge_requested` / `baseline_contradiction` (only changelog-status.v1.json:149-162 has baseline_check) | the routing statuses cannot be expressed in the artifacts the producer-stop gate validates (G2 would reject or ignore them) |
| d3 | charter family split: 9 agents "Mismatch is a success output ... STOP and return status" vs 14 agents "Report contradictions ... MUST carry a baseline_check entry" | only changelog-status.v1.json validates baseline_check | two contracts for one rule; 13 of 14 "MUST carry" agents have no schema field |
| d4 | agents/dev.md:10 "This charter outranks the 'absolute truth / do not question' clauses of the Authority Chain below" | agents/dev.md:12 `### Authority Chain` (same file, next section) | self-contradiction left in place instead of edited |
| d5 | score-echo "placeholder values are REJECTED"; "Without all four fields your output is considered non-compliant" (agents/ba.md:803, dev.md:508, qa.md:1385; scripts/score-inject.sh:55-56, :107-108) | no consumer anywhere (only tests read `rank_acknowledged`) | claims enforcement that does not exist (D1 owns the orphan) |
| d6 | agents/qa.md:1319, ba.md, dev.md codex gating: "sets codex_required when the user invokes /dev, /dev-command, /dev-overnight, /redev, or /close with --codex"; pm.md: /dev-overnight only; spec.md: /spec only | commands with --codex: clean, close, commit (QA runs codex in Step 6, commit.md:26), dev, dev-command, dev-overnight, do, redev, spec | QA's own prompt omits /commit, the command that dispatches QA with codex |
| d7 | agents/dev.md:497 `"status": "success"` | dev-report.v2.json enum [completed, blocked, needs_review]; dev.md:614 uses the enum | |
| d8 | architect/product-owner/user/ui-specialist descriptions "for overnight exploration" (agents/architect.md:3, product-owner.md:3, user.md:3, ui-specialist.md:3) | commands/dev.md:261-284 dispatches them in every /dev Step 3 | |
| d9 | agents/cleaner.md:62 "Verify git checkpoint exists: `git log -1 --grep="checkpoint: Before"`" | commands/clean.md:477-488 writes the checkpoint to `refs/checkpoints/<branch>`, never HEAD | the check can never pass |
| d10 | agents/cleaner.md:73 delete via `rm`; :101-107 create a `cleanup: Execute approved cleanup actions` commit; :109-111 then write the push-gate token for its own commit | bash_execution_boundary FORBIDDEN_REMOVAL (pretool-bash-safety.sh:1901-2019 removal policy); pretool-git-privilege-guard.py:22-27 (agent commit blocked); tool-policy cleaner write prefixes | the delete and commit steps are blocked for the cleaner; the commit also contradicts design §0 C5 (only /commit's changelog-analyst lands commits) |
| d11 | agents/style-inspector.md:600 `docs/clean/style-report-{REQUEST_ID}.json`, :37 `docs/clean/style-progress-*`; agents/prompt-inspector.md:187 `docs/clean/prompt-report-*` | tool-policy role prefixes (`*/docs/dev/<role>-*` only) | same as c20, agent side |
| d12 | agents/dev.md:843 "If passing the quality gate (pretool-quality-gate.py ...) requires modifying unrelated code, STOP" | pretool-quality-gate.py:338-360 never blocks | implies a gate that cannot fail |

### D4.e Hook docstrings vs their own code

| # | Docstring | Code | |
|---|---|---|---|
| e1 | hooks/pretool-quality-gate.py:5 "Blocks file writes", :19 "Exit codes: 0 allow, 2 block" | :338-360 `_grandfather_or_block` "always returns 0 (warn-only)" | |
| e2 | hooks/pretool-bulk-commit-detector.py:24 "2: Block tool use" | :57 "exit 0 (warn-only per user policy)" | |
| e3 | hooks/posttool-command-frontmatter-validate.py:11 "1 = block with error message" | :80 `sys.exit(1)` in PostToolUse = non-blocking notice; the tool already ran | |
| e4 | hooks/stop-do-report-gate.py:31-33 "it never writes the report itself" | :172-189 `_rewrite_pending_to_blocked` writes it | (B4) |
| e5 | hooks/lib/allowlist.py:20 sentinel at `<task_id>-<nonce>.json` | writer `${TASK_ID}.json` (userprompt-consent-allowlist.sh:714); posttool-allowlist-consume.py:24 says `<task_id>.json` | two docstrings disagree |
| e6 | hooks/lib/allowlist.py:3 "Single source of truth for grant-read" | 13 hooks read the consent flag themselves; git-privilege-guard reads grants by literal globs | D3.c |
| e7 | hooks/lib/subagent.py:3 "Single source of truth for is_subagent_context()" | ≈40 direct readers | D3.d |
| e8 | hooks/pretool-tool-policy.py:350-355 "defer to the backstop shim" | the shim (pretool-subagent-code-block.py:2-9) defers back to tool-policy | circular |
| e9 | hooks/pretool-orchestrator-gate.py:166 "run /do to unlock" for permanently blocked tools | :255-259 perm-block is checked before consent (T5) | |
| e10 | hooks/posttool-codex-skill-ledger.py:12-15 "PostToolUse fires on all Skill completions regardless of whether the codex invocation succeeded" | hooks/posttool-allowlist-consume.py:15-20: a failing tool fires PostToolUseFailure, not PostToolUse; the ledger hook is registered on PostToolUse only (settings.json:787) | two hooks state opposite platform semantics (PLAUSIBLE: a Skill load rarely fails) |
| e11 | hooks/lib/allowlist.py:455-461 "`-C` has NO bare-attached form in real git" | hooks/lib/git_clean_guard.py:546 and pretool-git-privilege-guard.py:182 treat `-C<dir>` as valid | D3.b |

### D4.f Internal contradictions inside one command file

| # | Location A | Location B | |
|---|---|---|---|
| f1 | commands/close.md:77-84, :762, :1013 "--force skips nothing (AC11) ... no-op alias" | commands/close.md:843 "--force bypasses scoring just as it bypasses QA debate", :868, :892 "The --force short-circuit at Step 2 line 54 means no QA debate occurred", :787 `CLOSE: YES (FORCED)` still a landed form | the FORCED verdict has no producer any more |
| f2 | commands/commit.md:856 "### Step 8: Spec-update dispatch" | commands/commit.md:866-874 `STEP7_*` markers; scripts/step7-spec-update.py:23-62 | step renumbered, markers not |
| f3 | commands/dev.md:777 note: "between Step 7 and Step 8" labels "intentionally NOT renumbered" | commands/dev.md:775 "### Step 9" | a note that preserves a contradiction |
| f5 | commands/dev-overnight.md:1796-1801 (`/commit -m`, `--force` override) | commands/commit.md:16-38 | (= c14/c15) |

### D4.g Contradictory rulings (user decisions; not resolvable from code)

| # | Side A | Side B |
|---|---|---|
| g1 honest terminal | CLAUDE.md:98 (Hook Discipline #5 "honest terminal branch"); design §0 C5 "free landing"; stop-do-report-gate.py:23-26 ("blocked" is the honest terminal) | docs/reference/paseo-daemon-teachings-20260910.md:103 "诚实终态永远不允许" (the doc itself flags the tension at :104) |
| g2 codex default | 12 agent codex blocks "OPT-IN (2026-05-04 user directive)" (e.g. agents/qa.md:1319) | teachings:245 "每一个command都要加codex" |
| g3 agent authority | 19 of 21 commands `disable-model-invocation: true` + 36 Skill denies (settings.json:256-291) | teachings:80, :132-137 "commit和restart你都可以做", "你就是我"; narrowed at :139 |
| g4 /do scope | CLAUDE.md:60 "this session"; ARCHITECTURE.md:139 | stop-cleanup-allowlist.sh:32-39 single turn (B3.d) |
| g5 /do may commit | README.md:247 "/do (main agent only)" for privilege-guard; git-privilege-guard.py:2501-2503 | design §0 C5 "commits land only via /commit's changelog-analyst"; teachings:139 "永远不允许force和git commit，commit永远走commit command" |
| g6 branch delete/rename | CLAUDE.md:86 allowed | git-privilege-guard.py:34-35 forbidden (T9) |
| g7 /push dirty tree | CLAUDE.md:49, checkpoint-mechanism.md:177-180 blocks | push.md:36, push.sh:18-19 does not |
| g8 large Reads | CLAUDE.md:61 never raw, delegate | read-size-guard.py:53-56, :87-89 chunked raw Reads allowed |
| g9 cp-enforce | 18 prompt claims "BLOCKS" | hook advisory by default (arming is A1-style) |

---

## Minimal plan (ordered, smallest first)

1. **D4 prose-only corrections that follow code** (S, no behaviour change): a1, a4-a7, a10-a13, b1-b10, c1, c5-c11, c15-c19, d4,
   d6-d9, d12, e1-e5, e8, e9, e11, f1-f3. Default rule: prose follows code. Where a row is a user decision (g1-g9), only the
   chosen side is kept.
2. **D3.c consent/state-dir** (S-M): `allowlist.has_do_consent()` + resolver in git-privilege-guard and the literal `/tmp`
   writers. Fixes T2 directly.
3. **D3.a/b parser normalisation** (M): classifier normalises its own input; one git global-option table; grepguard uses
   bash_context_strip; allowlist uses the classifier segmenter. Fixes T6-T8, T10.
4. **D3.d subagent predicate** (S-M): replace direct agent_id reads with lib.subagent; shell hooks call its CLI.
5. **D3.f/D3.h helpers** (S): run_todo_script, todo rules, protected-path list, spec-interview check, roster constant.
6. **D3.e resolvers** (M): one project_dir order; claude_home for home. Coordinate with B1/C1.
7. **D3.g prompt fragments** (M-L): render shared blocks from one source; dev-command de-fork; then E3 shortens them once.
   FIRST/SECOND ACTION removal waits for A4.
8. **D3.i** is executed by C2 (render settings from template) and docs generated from settings.

Dependencies: D3.d needs nothing; D3.g step 3 needs A4; D3.e needs B1 (completion-gate root) and C1; D3.i needs C2; D4 a2/a3
follow B3.c/B3.d; c9/e4 follow B4; d1/c4 wait for UD1 (A1 owns arming switches).

## User decisions (one line each)

- UD1 cp-enforce: arm `CP_ENFORCE_MODE=block` (makes 18 claims true, matches the producer-stop architecture) or rewrite the claims
  to "advisory". Recommendation: rewrite now via the shared fragment; arming joins A1's switch decision.
- UD2 /do scope: single turn (code) or session (CLAUDE.md). Recommendation: single turn (code).
- UD3 honest terminal: keep CLAUDE.md #5 + design C5 (recommended; B4's fix relies on it) or adopt teachings:103.
- UD4 codex default: opt-in (prompts) or every command (teachings:245).
- UD5 /do commit/push bypass in git-privilege-guard: keep (README) or remove to honour design C5 (recommended: remove for
  commit/push only).
- UD6 branch delete/rename by agents: allowed (CLAUDE.md:86) or blocked (code).
- UD7 /push on a dirty tree: allowed (code) or blocked (CLAUDE.md).
- UD8 large Reads: chunked Reads allowed (code) or delegate-only (CLAUDE.md).

---

## Appendices (generated with git grep at 09ab15b, non-test hooks/ and scripts/ unless stated)

### Appendix A rev-parse --show-toplevel sites (non-test hooks/scripts)
hooks/git-keystone/reference-transaction:239, hooks/lib/negative_evidence.py:697, hooks/lib/overnight.py:83, hooks/merge.sh:171, hooks/pretool-git-privilege-guard.py:1089, hooks/pretool-git-privilege-guard.py:1171, hooks/pretool-git-privilege-guard.py:1765, hooks/pretool-git-privilege-guard.py:1932, hooks/pretool-git-privilege-guard.py:1938, hooks/pretool-push-analyst-grant-guard.py:153, hooks/pretool-worktree-guard.sh:28, hooks/prompt-workflow.py:49, hooks/prompt-workflow.py:52, hooks/prompt-workflow.py:66, hooks/prompt-workflow.py:672, hooks/push.sh:102, hooks/push.sh:201, hooks/session-gitignore-propagate.sh:19, hooks/subagentstop-artifact-contract-enforce.py:365, scripts/apply-permissions.sh:16, scripts/check-enforcement-evidence.py:1313, scripts/check-public-core.sh:26, scripts/check-security-hook-drift.sh:85, scripts/checkpoint-prune.sh:95, scripts/close-scoring-decide.py:68, scripts/close-scoring-decide.py:100, scripts/commit.sh:38, scripts/create-overnight-state.sh:58, scripts/create-overnight-state.sh:236, scripts/create-worktree.sh:29, scripts/create-worktree.sh:31, scripts/create-worktree.sh:53, scripts/dev-fix.py:546, scripts/install-git-keystone.sh:33, scripts/overnight-git-selftest.sh:199, scripts/overnight-git/git-policy-shim:311, scripts/prune-orphaned-workflow-bookmarks.sh:84, scripts/refine-context.sh:10, scripts/resolve-close-report.sh:27, scripts/resolve-commit-repos.py:72, scripts/verify-claims-extended.sh:51, scripts/verify-claims.sh:24, scripts/write-commit-grant.py:14, scripts/write-commit-grant.py:515, 

### Appendix B rev-parse --git-common-dir sites
hooks/git-keystone/reference-transaction:76, hooks/git-keystone/reference-transaction:78, hooks/lib/negative_evidence.py:698, hooks/pretool-overnight-hook-guard.py:1942, hooks/pretool-overnight-hook-guard.py:1964, hooks/pretool-overnight-hook-guard.py:1967, scripts/create-overnight-state.sh:249, scripts/create-overnight-state.sh:530, scripts/install-git-keystone.sh:35, scripts/overnight-git-selftest.sh:200, scripts/overnight-git/git-policy-shim:303, 

### Appendix F1 Path.home()/.claude sites
hooks/doc_sync/main.py:66, hooks/doc_sync/patch.py:17, hooks/lib/subagent_restart.py:150, hooks/lib/subagent_restart.py:846, hooks/lib/todo_canonical.py:22, hooks/posttool-overnight-loop.py:28, hooks/posttool-todo-count.py:24, hooks/posttool-todo-tracker.py:26, hooks/posttool-todo-tracker.py:58, hooks/pretool-block-background-tasks.py:95, hooks/pretool-runcode-watchdog.py:29, hooks/pretool-spec-block-foreground-agent.py:33, hooks/pretool-workflow-gate.py:91, hooks/pretool-workflow-gate.py:102, hooks/prompt-workflow.py:177, hooks/prompt-workflow.py:266, hooks/prompt-workflow.py:274, hooks/prompt-workflow.py:333, hooks/prompt-workflow.py:555, hooks/prompt-workflow.py:687, hooks/prompt-workflow.py:832, hooks/prompt-workflow.py:1542, hooks/prompt-workflow.py:1652, hooks/prompt-workflow.py:1696, hooks/sessionstart-artifact-census.py:55, hooks/stop-completion-gate.py:83, hooks/stop-completion-gate.py:412, hooks/stop-completion-gate.py:567, hooks/stop-do-report-gate.py:58, hooks/stop-obligation-gate.py:56, hooks/userprompt-doc-sync-check.py:22, hooks/userprompt-doc-sync-check.py:161, scripts/break-overnight-lock.py:31, scripts/capability-handshake.py:91, scripts/dev-lifecycle.py:112, scripts/seal-attribution-journal.py:70, 

### Appendix F2 $HOME/.claude sites (code)
hooks/audit-slashcommand.sh:8, hooks/auto-commit.sh:34, hooks/checkpoint.sh:51, hooks/fswatch-manager.sh:14, hooks/fswatch-manager.sh:171, hooks/fswatch-manager.sh:261, hooks/git-fswatch.sh:27, hooks/git-fswatch.sh:274, hooks/git-fswatch.sh:275, hooks/git-hooks/post-commit-auto-push:23, hooks/git-hooks/pre-commit:20, hooks/git-hooks/pre-commit:24, hooks/git-hooks/pre-commit:32, hooks/git-hooks/pre-commit:33, hooks/git-hooks/pre-commit:38, hooks/install-auto-sync.sh:97, hooks/install-auto-sync.sh:101, hooks/install-git-hooks.sh:56, hooks/lib/checkpoint-core.sh:64, hooks/lib/claude_home.sh:87, hooks/lib/claude_home.sh:102, hooks/merge.sh:47, hooks/merge.sh:49, hooks/posttool-git-checkpoint.sh:61, hooks/pretool-bash-safety.sh:8, hooks/pretool-bash-safety.sh:433, hooks/pretool-bash-safety.sh:545, hooks/prompt-workflow.py:815, hooks/prompt-workflow.py:816, hooks/prompt-workflow.py:2015, hooks/start-fswatch-all.sh:51, hooks/start-fswatch-all.sh:52, hooks/start-fswatch-all.sh:55, hooks/stop-cleanup-allowlist.sh:23, hooks/stop.sh:21, hooks/stop.sh:23, hooks/userprompt-consent-allowlist.sh:403, hooks/userprompt-consent-allowlist.sh:666, scripts/bootstrap:190, scripts/canary-verify.sh:18, scripts/canary-verify.sh:35, scripts/check-file-references.sh:190, scripts/create-overnight-state.sh:874, scripts/detect-dead-functions.sh:9, scripts/detect-dead-functions.sh:11, scripts/detect-orphan-agents.sh:16, scripts/detect-orphan-commands.sh:16, scripts/detect-orphan-scripts.sh:16, scripts/install/install:15, scripts/install/installer.py:10, scripts/install/render-settings:28, scripts/lifecycle-baseline-import.sh:15, scripts/lifecycle-baseline-import.sh:16, scripts/overnight-init.sh:222, scripts/prune-orphaned-workflow-bookmarks.sh:182, scripts/score-inject.sh:15, scripts/score-update.sh:40, scripts/verify-claims.sh:7, scripts/verify-claims.sh:339, scripts/write-qa-mode.sh:55, 

### Appendix F3 expanduser(~/.claude) sites
hooks/subagentstop-artifact-contract-enforce.py:363, hooks/subagentstop-cp-enforce.py:34, 

### Appendix G FIRST/SECOND ACTION envelope lines
agents/graphify.md:20, commands/close.md:300, commands/close.md:523, commands/close.md:551, commands/close.md:553, commands/close.md:554, commands/close.md:555, commands/close.md:557, commands/close.md:559, commands/close.md:560, commands/close.md:561, commands/close.md:602, commands/close.md:603, commands/dev-command.md:127, commands/dev-command.md:165, commands/dev-command.md:176, commands/dev-command.md:180, commands/dev-command.md:182, commands/dev-command.md:183, commands/dev-command.md:186, commands/dev-command.md:239, commands/dev-command.md:329, commands/dev-command.md:391, commands/dev-command.md:457, commands/dev-command.md:553, commands/dev-command.md:604, commands/dev-command.md:662, commands/dev-overnight.md:26, commands/dev-overnight.md:27, commands/dev-overnight.md:32, commands/dev-overnight.md:250, commands/dev-overnight.md:337, commands/dev-overnight.md:339, commands/dev-overnight.md:341, commands/dev-overnight.md:350, commands/dev-overnight.md:353, commands/dev-overnight.md:487, commands/dev-overnight.md:643, commands/dev-overnight.md:644, commands/dev-overnight.md:743, commands/dev-overnight.md:974, commands/dev-overnight.md:1092, commands/dev-overnight.md:1194, commands/dev-overnight.md:1248, commands/dev-overnight.md:1255, commands/dev-overnight.md:1286, commands/dev-overnight.md:1387, commands/dev-overnight.md:1596, commands/dev.md:220, commands/dev.md:235, commands/dev.md:304, commands/dev.md:307, commands/dev.md:434, commands/dev.md:437, commands/dev.md:503, commands/dev.md:506, commands/dev.md:628, commands/dev.md:631, commands/dev.md:736, commands/dev.md:739, commands/dev.md:790, commands/dev.md:821, commands/dev.md:865, commands/dev.md:868, commands/dev.md:1016, commands/dev.md:1019, 

### Appendix H obligation template lines
agents/changelog-analyst.md:1983, commands/close.md:301, commands/close.md:551, commands/close.md:553, commands/close.md:554, commands/close.md:555, commands/close.md:557, commands/close.md:559, commands/close.md:560, commands/close.md:561, commands/close.md:567, commands/close.md:605, commands/commit.md:501, commands/commit.md:611, commands/dev-command.md:333, commands/dev-command.md:394, commands/dev-command.md:460, commands/dev-command.md:556, commands/dev-command.md:607, commands/dev-command.md:665, commands/dev-overnight.md:978, commands/dev-overnight.md:1095, commands/dev-overnight.md:1197, commands/dev-overnight.md:1289, commands/dev-overnight.md:1390, commands/dev-overnight.md:1504, commands/dev-overnight.md:1506, commands/dev.md:442, commands/dev.md:510, commands/dev.md:635, commands/dev.md:743, commands/dev.md:825, commands/dev.md:874, commands/dev.md:1023, 

### Appendix T: sandbox commands used

- Sandbox: `git archive HEAD hooks scripts policies schemas settings.json | tar -x -C h/`; toy repo `proj/` (`git init`, one empty commit).
- Env for every run: `PYTHONDONTWRITEBYTECODE=1 HOME=<sandbox>/home CLAUDE_STATE_DIR=<sandbox>/state TMPDIR=<sandbox>/tmp CLAUDE_PROJECT_DIR=<sandbox>/proj`.
- T1-T3: consent flag `true` at `<sandbox>/state/claude-orchestrator-consent-<sid>.flag`; payloads piped to the three hooks.
- T4-T5: eight-call sequence and EnterPlanMode through `hooks/pretool-orchestrator-gate.py`.
- T6-T7, T10: python `-I` imports of `hooks/lib/{bash_context_strip,grepguard_context_strip,git_command_classifier,allowlist}` and `hooks/lib/runtime_guard/git_cmds` from the sandbox copy.
- T8-T9: payloads with `agent_id` (T8) / without (T9) piped to `pretool-git-privilege-guard.py`, `pretool-bash-safety.sh`, `pretool-block-branch-pr-worktree.py`.
- Helper scripts kept in the sandbox: `blocks.py` (prompt-block ranges and hashes), `flags.py` (script flags named in prose vs script source: no flag mismatch found; the missing-script hits are D2's).
