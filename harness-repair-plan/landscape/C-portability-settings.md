# C-portability-settings — complete inventory (problems C1, C2)

Repository: /home/user/awesome-claude-harness @ HEAD 09ab15b (working tree clean). Read-only analysis; every execution was done in a `git archive HEAD` copy under `scratchpad/landscape-work/C-portability-settings/repo` with PYTHONDONTWRITEBYTECODE=1.
Generator + raw data (re-runnable): `scratchpad/landscape-work/C-portability-settings/{classify.py,extra.py,gen_md.py,core_rows2.json,venv_rows.json,home_rows.json,hook_table.tsv,perm_lines.txt,settings_diff.txt,ws2_residuals.json}`.

Architecture constraint honoured: every fix below is at the PRODUCER of the artifact (the settings renderer, bootstrap, the code that emits the value). Nothing here adds a check to /close or /commit.

## 0. Method and classification legend

* Core pattern (git grep -I -E over all 893 tracked files): `/root(/|\b)`, `/dev/shm`, `/var/lib/claude-accounts`, `/opt/paseo`, `/usr/bin/node`, `/usr/local/bin/paseo`, account names `<ACCT_1>|<ACCT_2>|<ACCT_3>`, `<ACCT_2b>`, `/home/<user>/`, `/Users/<User>`, `dev-shm-dev-workspace` slug, `/var/tmp/claude-*`, `/usr/bin/claude`, author product names `happy-web-dev|happy-daemon|dev|jade|qijie|happy.engineering|happy-session-recovery|happy-restart|.happy-*`, `Asia/Shanghai`. Result: 959 lines in 171 files.
* venv pattern: `.claude/venv`, `CLAUDE_HOME}/venv` and Path forms (110 lines outside settings.json).
* HOME-derived harness/config path pattern in executable code (`$HOME/.claude`, `${HOME}/.claude`, `~/.claude`, `Path.home()/".claude"`, `expanduser("~/.claude")`), hooks/ scripts/ tools/ only, tests excluded: 142 lines (after removing lines already counted above).
* Timezones: no maintainer timezone is hard-coded in executable code (defaults are UTC: scripts/paseo-daemon-ledger.py:2955, scripts/paseo-daemon-timers.py:391). All `America/*`, `Asia/*`, `Europe/*` hits are explicit test parametrisations or fixtures (tests/test_paseo_daemon_ledger.py, tests/test_prompt_workflow_liveness_tz.py, tests/fixtures/paseo_cron_vendor_vectors.json); one test copies TZif data from /usr/share/zoneinfo (tests/test_paseo_daemon_ledger.py:3234 -> needs tzdata). Classified TEST-DATA, not a portability break.
* Emails: author email `<EMAIL_1>` only at hooks/tests/test_git_residual_override.py:134,195,204 (fixture data; C3 overlap). Author GitHub handle in README.md:98,692, LICENSE:3, CHANGELOG.md:59-60, NESTED-REPO.md:10 (legitimate project identity, docs).

| class | meaning |
|---|---|
| FUNCTIONAL-BLOCKER | breaks the harness for any other user/machine: blocks prompts, tool calls or stops |
| FUNCTIONAL | wrong behaviour off the author machine (wrong path/account/attribution used) |
| FUNCTIONAL-DEGRADED | silently weaker off-author (permission prompt instead of allow, feature silently off) |
| AUTHOR-DEFAULT | overridable default that names the author environment; harmless or inert for others, but author identity ships in code |
| HARNESS-HOME-ASSUMED / STATE-UNDER-HOME-CLAUDE | code assumes the harness lives at ~/.claude (or that runtime state lives there); correct only for the clone-to-~/.claude layout |
| TEST-BREAK / TEST-MACHINE | test fails (BREAK) or depends on /dev/shm, /usr/bin/node, /opt/paseo etc. (MACHINE) off the author machine |
| TEST-DATA / DATA | literal used as input data/fixture; portable |
| DOCS / DOCS-FALSE-CLAIM | comment, docstring, prose, incident record; FALSE-CLAIM = doc asserts portability that is not true |
| PORTABLE-OK | generic or detector literal, not a portability problem (listed for completeness) |
| DEAD | inside a disabled legacy installer body |

### 0.1 Totals

| area | class | lines |
|---|---|---|
| ci | DOCS | 1 |
| ci | PORTABLE-OK | 1 |
| code | DOCS | 173 |
| code | PORTABLE-OK | 21 |
| code | AUTHOR-DEFAULT | 18 |
| code | FUNCTIONAL | 10 |
| data | DATA | 2 |
| docs | DOCS | 187 |
| docs | DOCS-FALSE-CLAIM | 3 |
| prompt | DOCS | 17 |
| prompt | DOCS-AUTHOR | 1 |
| settings | FUNCTIONAL-BLOCKER | 83 |
| settings | FUNCTIONAL-DEGRADED | 46 |
| settings | DOCS | 2 |
| template | DOCS | 2 |
| template | FUNCTIONAL-DEGRADED | 2 |
| test | TEST-DATA | 312 |
| test | TEST-BREAK | 34 |
| test | DOCS | 30 |
| test | TEST-MACHINE | 14 |
| venv (all areas) | AUTHOR-DEFAULT | 72 (prompts 59, code 13) |
| HOME-derived (code) | AUTHOR-DEFAULT | 2 |
| HOME-derived (code) | DEAD | 30 |
| HOME-derived (code) | DOCS | 45 |
| HOME-derived (code) | HARNESS-HOME-ASSUMED | 26 |
| HOME-derived (code) | PORTABLE-OK | 7 |
| HOME-derived (code) | STATE-UNDER-HOME-CLAUDE | 32 |

Headline: the ONLY blocker-class portability defect is the tracked settings.json (83/83 hook commands). Everything else in executable code is either already resolver-based, an author default, or a ~/.claude layout assumption. The second blocker is not a literal at all: the out-of-repo `~/.config/claude/protected-runtime.json` has no producer (C2.c).

---
## C1 — hard-coded machine/user values

### C1.a settings.json: 83/83 hook commands hard-code /root/.claude (FUNCTIONAL-BLOCKER)

Mechanism (verified in scratch): `python3 /nonexistent/x.py` exits 2, `bash /nonexistent/x.sh` exits 127. Claude Code treats exit 2 as BLOCK for PreToolUse / UserPromptSubmit / Stop / SubagentStop. On any home other than /root/.claude (or as a non-root user, /root is mode 700) the 62 python3 hooks therefore block every prompt (5 UserPromptSubmit), every tool call (29 PreToolUse, 6 of them matcher ""/"*" = all tools), every main-agent Stop (4) and every subagent stop (5); the 21 bash hooks (incl. the main safety hook pretool-bash-safety.sh) silently go inert (exit 127 is non-blocking). Prior runtime evidence: harness-cleanup/runtime-verification.md:9,20,74-76,269 (SB/logs/alt-unrendered.jsonl: PreToolUse Bash 18/20 hooks exit 2, Stop 4/4 exit 2).

| settings.json line | event | matcher | hook | interpreter | effect when the path does not exist |
|---|---|---|---|---|---|
| settings.json:313 | SessionStart | `(none)` | session-info.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:317 | SessionStart | `(none)` | session-git-init.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:321 | SessionStart | `(none)` | session-scratch-init.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:326 | SessionStart | `(none)` | check-todo-md-sync.py | python3 (missing file -> exit 2) | non-blocking error |
| settings.json:330 | SessionStart | `(none)` | session-promote-hook.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:335 | SessionStart | `(none)` | canary-verify.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:340 | SessionStart | `(none)` | session-tmpfs-banner.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:345 | SessionStart | `(none)` | session-gitignore-propagate.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:356 | UserPromptSubmit | `(none)` | prompt-workflow.py | python3 (missing file -> exit 2) | BLOCKS and erases every user prompt |
| settings.json:360 | UserPromptSubmit | `(none)` | userprompt-doc-sync-check.py | python3 (missing file -> exit 2) | BLOCKS and erases every user prompt |
| settings.json:364 | UserPromptSubmit | `(none)` | userprompt-restart-authorize.py | python3 (missing file -> exit 2) | BLOCKS and erases every user prompt |
| settings.json:372 | UserPromptSubmit | `(none)` | userprompt-consent-allowlist.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:380 | UserPromptSubmit | `(none)` | userprompt-tmpfs-pressure.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:389 | UserPromptSubmit | `(none)` | userprompt-bulk-commit-capability.py | python3 (missing file -> exit 2) | BLOCKS and erases every user prompt |
| settings.json:397 | UserPromptSubmit | `(none)` | userprompt-usage-snapshot.py | python3 (missing file -> exit 2) | BLOCKS and erases every user prompt |
| settings.json:408 | PreToolUse | `(none)` | pretool-orchestrator-gate.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:416 | PreToolUse | `(none)` | pretool-block-background-tasks.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:424 | PreToolUse | `(none)` | pretool-do-block-subagents.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:432 | PreToolUse | `(none)` | pretool-read-size-guard.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:440 | PreToolUse | `(none)` | pretool-workflow-gate.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:448 | PreToolUse | `(none)` | pretool-subagent-enforce.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:457 | PreToolUse | `Bash` | pretool-bash-safety.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:461 | PreToolUse | `Bash` | pretool-bash-views-guard.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:465 | PreToolUse | `Bash` | pretool-wrapper-userintent.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:469 | PreToolUse | `Bash` | pretool-grep-backtrack-guard.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:478 | PreToolUse | `Read` | pretool-cp-checkin.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:487 | PreToolUse | `Write\|Edit\|MultiEdit\|Bash` | pretool-overnight-hook-guard.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:496 | PreToolUse | `Write\|Edit\|MultiEdit` | pretool-quality-gate.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:505 | PreToolUse | `*` | pretool-tool-policy.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:514 | PreToolUse | `Write\|Edit\|MultiEdit\|NotebookEdit\|Bash` | pretool-cp-state-write-guard.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:523 | PreToolUse | `Write\|Edit\|MultiEdit\|NotebookEdit\|Bash` | pretool-attribution-pre.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:533 | PreToolUse | `Write\|Edit\|NotebookEdit\|MultiEdit` | pretool-subagent-code-block.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:542 | PreToolUse | `TodoWrite` | pretool-todo-validate.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:551 | PreToolUse | `EnterWorktree` | pretool-block-enterworktree.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:560 | PreToolUse | `Bash` | pretool-block-branch-pr-worktree.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:568 | PreToolUse | `(none)` | pretool-worktree-guard.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:577 | PreToolUse | `Write` | pretool-write-guard.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:587 | PreToolUse | `Agent` | pretool-layer-escalation-check.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:591 | PreToolUse | `Agent` | pretool-bisect-gate.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:595 | PreToolUse | `Agent` | pretool-spec-block-foreground-agent.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:599 | PreToolUse | `Agent` | pretool-orchestrator-prompt-purity.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:603 | PreToolUse | `Agent` | pretool-aggregate-check.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:607 | PreToolUse | `Agent` | pretool-gitignore-preflight.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:611 | PreToolUse | `Agent` | pretool-obligation-gate.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:615 | PreToolUse | `Agent` | pretool-commit-dispatch-attest.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:624 | PreToolUse | `mcp__playwright__browser_run_code\|mcp__paseo__browser_run_code` | pretool-runcode-watchdog.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:633 | PreToolUse | `Edit\|Write\|MultiEdit\|Bash` | pretool-claude-config-guard.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:643 | PreToolUse | `Bash` | pretool-bulk-commit-detector.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:653 | PreToolUse | `Bash` | pretool-git-privilege-guard.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:662 | PreToolUse | `Bash` | pretool-push-analyst-grant-guard.py | python3 (missing file -> exit 2) | BLOCKS the matched tool call |
| settings.json:673 | PostToolUse | `*` | posttool-allowlist-consume.py | python3 (missing file -> exit 2) | stderr error fed back to model after every matched call |
| settings.json:682 | PostToolUse | `TodoWrite` | posttool-todo-tracker.py | python3 (missing file -> exit 2) | stderr error fed back to model after every matched call |
| settings.json:686 | PostToolUse | `TodoWrite` | posttool-todo-count.py | python3 (missing file -> exit 2) | stderr error fed back to model after every matched call |
| settings.json:690 | PostToolUse | `TodoWrite` | posttool-todo-sequence.py | python3 (missing file -> exit 2) | stderr error fed back to model after every matched call |
| settings.json:694 | PostToolUse | `TodoWrite` | posttool-overnight-loop.py | python3 (missing file -> exit 2) | stderr error fed back to model after every matched call |
| settings.json:703 | PostToolUse | `Write\|Edit\|MultiEdit\|NotebookEdit\|Bash` | posttool-attribution-post.py | python3 (missing file -> exit 2) | stderr error fed back to model after every matched call |
| settings.json:713 | PostToolUse | `Write\|Edit\|NotebookEdit\|MultiEdit` | posttool-git-checkpoint.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:717 | PostToolUse | `Write\|Edit\|NotebookEdit\|MultiEdit` | posttool-doc-sync.py | python3 (missing file -> exit 2) | stderr error fed back to model after every matched call |
| settings.json:721 | PostToolUse | `Write\|Edit\|NotebookEdit\|MultiEdit` | posttool-command-frontmatter-validate.py | python3 (missing file -> exit 2) | stderr error fed back to model after every matched call |
| settings.json:725 | PostToolUse | `Write\|Edit\|NotebookEdit\|MultiEdit` | posttool-lane-completeness-watch.py | python3 (missing file -> exit 2) | stderr error fed back to model after every matched call |
| settings.json:734 | PostToolUse | `Write` | posttool-push-gate-token-verify.py | python3 (missing file -> exit 2) | stderr error fed back to model after every matched call |
| settings.json:743 | PostToolUse | `Bash\(git commit.*\)` | posttool-git-warn.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:752 | PostToolUse | `Agent` | posttool-overnight-file-check.py | python3 (missing file -> exit 2) | stderr error fed back to model after every matched call |
| settings.json:756 | PostToolUse | `Agent` | posttool-subagent-track.py | python3 (missing file -> exit 2) | stderr error fed back to model after every matched call |
| settings.json:760 | PostToolUse | `Agent` | posttool-overnight-trace.py | python3 (missing file -> exit 2) | stderr error fed back to model after every matched call |
| settings.json:769 | PostToolUse | `SendMessage` | posttool-restart-sendmessage.py | python3 (missing file -> exit 2) | stderr error fed back to model after every matched call |
| settings.json:778 | PostToolUse | `mcp__playwright__browser_run_code\|mcp__paseo__browser_run_code` | posttool-runcode-watchdog.py | python3 (missing file -> exit 2) | stderr error fed back to model after every matched call |
| settings.json:787 | PostToolUse | `Skill` | posttool-codex-skill-ledger.py | python3 (missing file -> exit 2) | stderr error fed back to model after every matched call |
| settings.json:798 | PostToolUseFailure | `Bash` | posttool-allowlist-consume.py | python3 (missing file -> exit 2) | stderr error fed back |
| settings.json:809 | Notification | `idle_prompt` | notification-idle-overnight.py | python3 (missing file -> exit 2) | non-blocking error |
| settings.json:819 | Stop | `(none)` | stop-workflow-coordinator.py | python3 (missing file -> exit 2) | BLOCKS the main agent from stopping (loop) |
| settings.json:827 | Stop | `(none)` | stop-do-report-gate.py | python3 (missing file -> exit 2) | BLOCKS the main agent from stopping (loop) |
| settings.json:835 | Stop | `(none)` | stop-obligation-gate.py | python3 (missing file -> exit 2) | BLOCKS the main agent from stopping (loop) |
| settings.json:843 | Stop | `(none)` | stop-completion-gate.py | python3 (missing file -> exit 2) | BLOCKS the main agent from stopping (loop) |
| settings.json:853 | SessionEnd | `(none)` | sessionend-scratch-sweep.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:865 | SubagentStop | `*` | subagent-stop-diff-check.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:869 | SubagentStop | `*` | pretool-layer-match-gate.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:873 | SubagentStop | `*` | subagent-stop-guard-integrity.sh | bash (missing file -> exit 127) | non-blocking error; the hook is silently inert |
| settings.json:877 | SubagentStop | `*` | subagentstop-restart-track.py | python3 (missing file -> exit 2) | BLOCKS every subagent from stopping |
| settings.json:886 | SubagentStop | `*` | subagentstop-codex-enforce.py | python3 (missing file -> exit 2) | BLOCKS every subagent from stopping |
| settings.json:895 | SubagentStop | `*` | subagentstop-e2e-enforce.py | python3 (missing file -> exit 2) | BLOCKS every subagent from stopping |
| settings.json:904 | SubagentStop | `*` | subagentstop-artifact-contract-enforce.py | python3 (missing file -> exit 2) | BLOCKS every subagent from stopping |
| settings.json:913 | SubagentStop | `*` | subagentstop-cp-enforce.py | python3 (missing file -> exit 2) | BLOCKS every subagent from stopping |

Non-hook literals in settings.json (permissions + env):

| location | class | what is wrong | text |
|---|---|---|---|
| settings.json:24 | FUNCTIONAL-DEGRADED | env GRAPHIFY_BIN points at the author venv; graphify integration silently off elsewhere | `"GRAPHIFY_BIN": "/root/.claude/venv/bin/graphify",` |
| settings.json:25 | DOCS | comment value | `"_comment_graphify": "Graphify (graphifyy v0.8.25) integration drives the REAL CLI (graphify update/query/affected). Gate: CLAUDE_GRAPHIFY_ENABLED=auto\|1 enables, 0 disables. Override env vars (leave unset for defaults): GRAPHIFY_BIN=<path` |
| settings.json:28 | FUNCTIONAL-DEGRADED | TMPDIR pin is machine policy (belongs in machine overlay) | `"CLAUDE_CODE_TMPDIR": "/var/tmp/claude-scratch",` |
| settings.json:29 | FUNCTIONAL-DEGRADED | TMPDIR pin is machine policy (belongs in machine overlay) | `"TMPDIR": "/var/tmp/claude-scratch",` |
| settings.json:30 | DOCS | comment value | `"_comment_tmpdir": "Pinned to /var/tmp/claude-scratch because it is disk-backed (ext4); the prior /dev/shm/claude-tmp pin was tmpfs (RAM+swap) despite claiming otherwise."` |
| settings.json:35 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/canary-verify.sh:*)",` |
| settings.json:36 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/check-overnight-reports.sh:*)",` |
| settings.json:37 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/detect-orphan-agents.sh:*)",` |
| settings.json:38 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/detect-orphan-commands.sh:*)",` |
| settings.json:39 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/detect-orphan-scripts.sh:*)",` |
| settings.json:40 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/install-git-keystone.sh:*)",` |
| settings.json:41 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/lifecycle-baseline-import.sh:*)",` |
| settings.json:42 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/mint-git-blessed-token.sh:*)",` |
| settings.json:43 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/orchestrator.sh clean-execute:*)",` |
| settings.json:44 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/orchestrator.sh clean-inspect:*)",` |
| settings.json:45 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/orchestrator.sh clean-merge-reports:*)",` |
| settings.json:46 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/orchestrator.sh record-checkpoint:*)",` |
| settings.json:47 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/orchestrator.sh rule-inspect:*)",` |
| settings.json:48 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/overnight-git-env.sh:*)",` |
| settings.json:49 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/overnight-git-selftest.sh:*)",` |
| settings.json:50 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/scan-project.sh:*)",` |
| settings.json:51 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/score-inject.sh:*)",` |
| settings.json:52 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/score-update.sh:*)",` |
| settings.json:53 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(/root/.claude/scripts/write-qa-mode.sh:*)",` |
| settings.json:103 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(python3 /root/.claude/scripts/blast-radius-tool.py:*)",` |
| settings.json:104 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(python3 /root/.claude/scripts/spec-check.py:*)",` |
| settings.json:105 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(python3 /root/.claude/scripts/spec-verify/spec-verify-views.py:*)",` |
| settings.json:125 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(source /root/.claude/venv/bin/activate && pytest tests/generated:*)",` |
| settings.json:126 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(source /root/.claude/venv/bin/activate && python /root/.claude/hooks/lib/close-verdict.py:*)",` |
| settings.json:127 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(source /root/.claude/venv/bin/activate && python3 -m pytest tests/test_graphify_scripts.py:*)",` |
| settings.json:128 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(source /root/.claude/venv/bin/activate && python3 -m pytest tests/test_graphify_workflow_contract.py:*)",` |
| settings.json:129 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(source /root/.claude/venv/bin/activate && python3 /root/.claude/scripts/graphify-enrich.py:*)",` |
| settings.json:130 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(source /root/.claude/venv/bin/activate && python3 /root/.claude/scripts/graphify-maintain.py:*)",` |
| settings.json:131 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(source /root/.claude/venv/bin/activate && python3 /root/.claude/scripts/graphify-query.py:*)",` |
| settings.json:132 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(source /root/.claude/venv/bin/activate && python3 /root/.claude/scripts/spec-verify/spec-verify.py:*)",` |
| settings.json:133 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(source /root/.claude/venv/bin/activate && python3 /root/.claude/scripts/todo/clean.py:*)",` |
| settings.json:134 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(source /root/.claude/venv/bin/activate && python3 /root/.claude/scripts/todo/close.py:*)",` |
| settings.json:135 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(source /root/.claude/venv/bin/activate && python3 /root/.claude/scripts/todo/file-analyze.py:*)",` |
| settings.json:136 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(source /root/.claude/venv/bin/activate && python3 /root/.claude/scripts/todo/quick-prototype.py:*)",` |
| settings.json:137 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(source /root/.claude/venv/bin/activate && python3 /root/.claude/scripts/todo/reflect-search.py:*)",` |
| settings.json:138 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(source /root/.claude/venv/bin/activate && python3 /root/.claude/scripts/todo/test.py:*)",` |
| settings.json:139 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(source /root/.claude/venv/bin/activate && python3 /root/.claude/tests/scripts/validate-*.py:*)",` |
| settings.json:185 | FUNCTIONAL-DEGRADED | author-machine binary allow rule; meaningless off-author (overlay) | `"Bash(/root/bin/session-link-sync.sh:*)",` |
| settings.json:186 | FUNCTIONAL-DEGRADED | author-machine binary allow rule; meaningless off-author (overlay) | `"Bash(/root/bin/paseo-timeline-healer.mjs:*)",` |
| settings.json:187 | FUNCTIONAL-DEGRADED | author-machine binary allow rule; meaningless off-author (overlay) | `"Bash(node --disable-warning=DEP0040 /root/bin/paseo-timeline-healer.mjs:*)",` |
| settings.json:188 | FUNCTIONAL-DEGRADED | author-machine binary allow rule; meaningless off-author (overlay) | `"Bash(/usr/local/bin/paseo-self-update --help:*)",` |
| settings.json:189 | FUNCTIONAL-DEGRADED | author-machine binary allow rule; meaningless off-author (overlay) | `"Bash(/usr/local/bin/paseo-self-update --reset-state:*)",` |
| settings.json:191 | FUNCTIONAL-DEGRADED | absolute /root/.claude permission literal; never matches another home -> permission prompt instead of allow | `"Bash(python3 /root/.claude/scripts/session-resources.py:*)",` |
| settings.template.json:24 | DOCS | comment value | `"_comment_graphify": "Graphify (graphifyy v0.8.25) integration drives the REAL CLI (graphify update/query/affected). Gate: CLAUDE_GRAPHIFY_ENABLED=auto\|1 enables, 0 disables. Override env vars (leave unset for defaults): GRAPHIFY_BIN=<path` |
| settings.template.json:27 | FUNCTIONAL-DEGRADED | template pins TMPDIR to /dev/shm/claude-tmp (absent on macOS; never created because session-scratch-init.sh is not in the template); contradicts live /var/tmp/claude-scratch | `"CLAUDE_CODE_TMPDIR": "/dev/shm/claude-tmp",` |
| settings.template.json:28 | FUNCTIONAL-DEGRADED | template pins TMPDIR to /dev/shm/claude-tmp (absent on macOS; never created because session-scratch-init.sh is not in the template); contradicts live /var/tmp/claude-scratch | `"TMPDIR": "/dev/shm/claude-tmp",` |
| settings.template.json:29 | DOCS | comment value | `"_comment_tmpdir": "Harness stdout-capture and agent scratch are pinned to a disk-backed filesystem. The 4G /tmp tmpfs was exhausted three times in one cycle by agent scratch trees, each time killing every Bash call before execution (the ca` |

Repo self-check agrees: `tests/ws2_zero_literal_gate.py <copy>` (run in scratch) exits 3 with 148 "genuine load-bearing" residuals, 137 of them in settings.json (the gate assumes a RENDERED clone; the tracked file is not one) + scripts/paseo-daemon-timers.py:144,678, scripts/paseo-daemon-ledger.py:3010, commands/dev-overnight.md:1085 and 6 detector literals in scripts/check-public-core.sh.

### C1.b Shipped executable code: author literals and author defaults

| location | class | what is wrong |
|---|---|---|
| .claude/tmp-test-writer-gen-l7.py:16 | FUNCTIONAL | stray one-off script; ROOT hard-wired to the author tmpfs checkout (E1 delete) |
| hooks/lib/checkpoint-core.sh:668 | FUNCTIONAL | every checkpoint commit written into ANY user's repo carries the author's tool attribution "via [Happy](https://happy.engineering)" |
| hooks/lib/checkpoint-core.sh:671 | FUNCTIONAL | every checkpoint commit adds "Co-Authored-By: Happy <yesreply@happy.engineering>" |
| hooks/lib/checkpoint-core.sh:782 | FUNCTIONAL | same attribution in second checkpoint path |
| hooks/lib/checkpoint-core.sh:785 | FUNCTIONAL | same Co-Authored-By trailer in second checkpoint path |
| hooks/lib/subagent_restart.py:820 | AUTHOR-DEFAULT | ACCOUNTS_ROOT default /var/lib/claude-accounts (author multi-account layout); env CLAUDE_RESTART_ACCOUNTS_ROOT overrides; absent dir = feature silently inert |
| hooks/pretool-bash-safety.sh:317 | AUTHOR-DEFAULT | CLAUDE_DEV_CONTAINERS default = author container happy-web-dev (whitelisted for docker ops) |
| hooks/pretool-bash-safety.sh:327 | AUTHOR-DEFAULT | grant helper default /root/bin/claude-allow-restart: off-author the daemon-restart gate is un-grantable |
| hooks/pretool-bash-safety.sh:333 | AUTHOR-DEFAULT | CLAUDE_PROTECTED_DAEMON_PREFIX default = author unit prefix happy-daemon |
| hooks/pretool-bash-safety.sh:334 | AUTHOR-DEFAULT | CLAUDE_PROTECTED_DAEMON_TARGETS default = author instances dev\|jade\|qijie |
| hooks/pretool-bash-safety.sh:1776 | AUTHOR-DEFAULT | non-configurable ban on author script name happy-session-recovery (false positive for any command containing it) |
| hooks/pretool-bash-safety.sh:1777 | AUTHOR-DEFAULT | (message of :1776) |
| hooks/pretool-bash-safety.sh:1783 | AUTHOR-DEFAULT | non-configurable ban on author script name happy-restart |
| hooks/pretool-bash-safety.sh:1784 | AUTHOR-DEFAULT | (message of :1783) |
| hooks/session-tmpfs-banner.sh:21 | AUTHOR-DEFAULT | df /tmp /dev/shm banner: Linux-only; maintainer tmpfs concern; harmless elsewhere (errors suppressed) |
| hooks/userprompt-tmpfs-pressure.sh:74 | AUTHOR-DEFAULT | df on /dev/shm every prompt: Linux-only maintainer tmpfs monitoring |
| hooks/userprompt-tmpfs-pressure.sh:75 | AUTHOR-DEFAULT | mounts=(/tmp /dev/shm) fixed list |
| hooks/userprompt-tmpfs-pressure.sh:140 | AUTHOR-DEFAULT | df /tmp /dev/shm |
| scripts/install/tmpfiles-claude-scratch.conf:60 | AUTHOR-DEFAULT | systemd-tmpfiles rule for /var/tmp/claude-scratch owned root:root (assumes root user) |
| scripts/install/tmpfiles-claude-scratch.conf:61 | AUTHOR-DEFAULT | systemd-tmpfiles rule still creates the retired /dev/shm/claude-tmp root (root:root); machine-specific installer payload |
| scripts/paseo-daemon-ledger.py:133 | FUNCTIONAL | DEFAULT_ACCOUNTS = author account names; used as --accounts default (:2798) so a stranger's ledger is initialised with the author's 3 accounts |
| scripts/paseo-daemon-ledger.py:1626 | AUTHOR-DEFAULT | wake node interpreter default /usr/bin/node (config-overridable via wake_vendor_node_path :2007); nvm/Homebrew/node-in-/usr/local break |
| scripts/paseo-daemon-ledger.py:3010 | FUNCTIONAL | --registry-dir default /root/.paseo/schedules: non-root user gets EACCES/wrong registry |
| scripts/paseo-daemon-timers.py:144 | FUNCTIONAL | timer registration target cwd "/root/.claude" baked into the daemon-watchdog entry |
| scripts/paseo-daemon-timers.py:146 | FUNCTIONAL | timer model pinned to the author account "claude-sonnet-4-6@<ACCT_3>" |
| scripts/paseo-daemon-timers.py:678 | FUNCTIONAL | --registry-dir default /root/.paseo/schedules |
| scripts/prune-orphaned-workflow-bookmarks.sh:89 | AUTHOR-DEFAULT | ACCOUNTS_DIR default /var/lib/claude-accounts |
| scripts/prune-orphaned-workflow-bookmarks.sh:90 | AUTHOR-DEFAULT | PROJECT_DIRNAME default = encoded author checkout path -dev-shm-dev-workspace-dot-claude; should be derived from the resolved home realpath |

| hooks/pretool-bash-safety.sh:8 | HARNESS-HOME-ASSUMED | CLAUDE_HOME defaults to $HOME/.claude instead of self-resolution (also listed in C1.c) |
| hooks/pretool-bash-safety.sh:1825 | AUTHOR-DEFAULT | non-configurable rule: docker stop\|restart\|rm\|kill of anything matching "happy" (author product); false positive for any container name containing it |
| hooks/pretool-bash-safety.sh:1827 | AUTHOR-DEFAULT | (message of :1825) |
| hooks/pretool-bash-safety.sh:1860 | AUTHOR-DEFAULT | killall/pkill of anything matching happy\|claude\|docker blocked (author product name in a shipped rule) |
| hooks/pretool-bash-safety.sh:1861 | AUTHOR-DEFAULT | (message of :1860) |
| scripts/install/tmp-cleanup-install.sh:2 | AUTHOR-DEFAULT | whole file is the author machine cron payload (/usr/local/sbin/tmp-cleanup.sh for a 4G /tmp tmpfs); author product patterns at :66,69,150-152,187,188,215 |

Portable / detector literals in code (no action; listed so the list is complete):

| location | why it is fine |
|---|---|
| .github/workflows/baseline.yml:184 | CI residue detector |
| hooks/lib/attribution_journal.py:155 | generic /dev/ device-sink filter |
| hooks/lib/runtime_guard/_core.py:3390 | false positive / detector literal |
| hooks/lib/runtime_guard/config.py:117 | generic POSIX system-roots constant |
| hooks/pretool-bash-safety.sh:1013 | generic policy pattern (scripts under /tmp\|/var/tmp\|/dev/shm); not a machine assumption |
| hooks/pretool-bash-safety.sh:1016 | message of :1013 |
| hooks/pretool-overnight-hook-guard.py:2097 | conditional bwrap ro-bind of /dev/shm only if it exists |
| hooks/pretool-overnight-hook-guard.py:2098 | see :2097 |
| hooks/pretool-overnight-hook-guard.py:2100 | false positive / detector literal |
| hooks/session-scratch-init.sh:23 | TMPDIR fallback /var/tmp/claude-scratch (exists on Linux+macOS; dir is created here) |
| hooks/sessionend-scratch-sweep.sh:23 | TMPDIR fallback /var/tmp/claude-scratch |
| scripts/check-public-core.sh:54 | detector pattern (literal is the thing searched for) |
| scripts/check-public-core.sh:108 | detector pattern |
| scripts/check-public-core.sh:249 | detector pattern |
| scripts/check-public-core.sh:368 | detector marker list |
| scripts/check-public-core.sh:369 | detector marker list |
| scripts/check-public-core.sh:544 | false positive / detector literal |
| scripts/check-public-core.sh:545 | detector marker list |
| scripts/check-public-core.sh:546 | false positive / detector literal |
| scripts/detect-hardcoded-paths.sh:9 | detector pattern |
| scripts/detect-hardcoded-paths.sh:22 | detector pattern |
| scripts/graphify_lib.py:137 | cache root default /var/tmp/claude-graphify, env-overridable |

Comments / docstrings / doctests / usage text in code that mention author paths (DOCS; cosmetic, cleanup optional) — grouped by file:

* .github/workflows/baseline.yml: 73
* examples/guard-demo/run-demo.sh: 10, 49, 75, 153
* hooks/git-hooks/pre-commit: 19
* hooks/lib/attribution_journal.py: 154
* hooks/lib/bash_write_targets.py: 34, 35, 37, 38, 40, 41, 43, 44, 52, 53, 61, 62, 176
* hooks/lib/claude_home.py: 6, 34, 115, 172, 176
* hooks/lib/claude_home.sh: 101
* hooks/lib/closeout.py: 48
* hooks/lib/contract_runtime.py: 84, 85
* hooks/lib/interruption_signals.py: 13
* hooks/lib/policy_registry.py: 20, 50, 68, 151, 166, 189, 229
* hooks/lib/runtime_guard/_core.py: 1416, 1481, 1518, 1583, 2727
* hooks/lib/runtime_guard/config.py: 40, 83, 84, 85, 113, 127, 128, 129, 130, 138
* hooks/lib/runtime_guard/find_cmds.py: 143, 144, 151, 168
* hooks/lib/runtime_guard/pathmatch.py: 208
* hooks/lib/schema_registry.py: 8
* hooks/lib/specialist_yield.py: 66
* hooks/lib/subagent_restart.py: 831
* hooks/merge.sh: 45, 339
* hooks/notification-idle-overnight.py: 17, 48, 56
* hooks/posttool-overnight-trace.py: 69
* hooks/pretool-bash-safety.sh: 79, 84, 88, 89, 96, 99, 107, 111, 112, 127, 318, 319, 320, 321, 332, 341, 428, 496, 504, 539, 549, 557, 558, 853, 975, 977, 1010, 1037, 1401, 1765
* hooks/pretool-cp-checkin.py: 50, 57, 95, 204, 476
* hooks/pretool-git-privilege-guard.py: 1401
* hooks/pretool-overnight-hook-guard.py: 47, 59, 67, 2058, 2060, 2061, 2062, 2082, 2084
* hooks/prompt-workflow.py: 67, 87
* hooks/push.sh: 29
* hooks/sentinel-lint.sh: 41
* hooks/session-promote-hook.sh: 10, 77, 86
* hooks/session-tmpfs-banner.sh: 5, 6, 17
* hooks/stop-spec-coverage-enforce.py: 42
* hooks/stop.sh: 18
* hooks/userprompt-tmpfs-pressure.sh: 5
* hooks/userprompt-usage-snapshot.py: 14, 15
* push.sh: 6
* scripts/apply-permissions.sh: 8
* scripts/break-overnight-lock.py: 26
* scripts/check-file-references.sh: 27
* scripts/check-overnight-reports.sh: 6
* scripts/check-public-core.sh: 92, 93, 97, 111, 177, 208, 213, 538, 629
* scripts/close-report-append.py: 122, 124, 129
* scripts/close-scoring-decide.py: 128, 137, 230, 231, 233
* scripts/create-overnight-state.sh: 45
* scripts/execute-push.py: 37
* scripts/graphify-maintain.py: 6, 28, 68
* scripts/graphify-query.py: 25
* scripts/install/render-settings: 27
* scripts/install/tmpfiles-claude-scratch.conf: 14, 19, 21, 44, 45
* scripts/install/tmpfiles-var-tmp-override.conf: 16
* scripts/paseo-daemon-ledger.py: 1608
* scripts/paseo-daemon-timers.py: 87
* scripts/prune-orphaned-workflow-bookmarks.sh: 23, 24, 51, 55, 56
* scripts/resolve-close-report.sh: 20
* scripts/seal-attribution-journal.py: 5, 11
* scripts/spec-verify/spec_verify_parsers.py: 3
* scripts/step7-spec-update.py: 96
* scripts/write-commit-grant.py: 6

### C1.c Harness-home and venv location assumed to be ~/.claude

These are correct only for the "clone into ~/.claude" layout. They break for (1) the README contributor path `git clone ... claude-harness` (README.md:94-101, "never over ~/.claude"), (2) the installer isolated root `<prefix>/harness` (scripts/install/install:11-16), (3) CLAUDE_CONFIG_DIR users. The structural resolver hooks/lib/claude_home.{sh,py} already exists (48 files use it); these sites bypass it.

HOME-derived paths in executable code:

| location | class | what is wrong |
|---|---|---|
| scripts/install/render-settings:197 | AUTHOR-DEFAULT | renderer defaults the install home to $CLAUDE_HOME or $HOME/.claude instead of its own location (see C2) — `or str(Path(os.environ.get("HOME", str(Path.home()))) / ".claude"))` |
| scripts/install/render-settings:207 | AUTHOR-DEFAULT | renderer defaults the install home to $CLAUDE_HOME or $HOME/.claude instead of its own location (see C2) — `or str(Path(os.environ.get("HOME", str(Path.home()))) / ".claude"))` |
| hooks/auto-commit.sh:34 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `. "$HOME/.claude/hooks/lib/checkpoint-core.sh"` |
| hooks/checkpoint.sh:51 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `. "$HOME/.claude/hooks/lib/checkpoint-core.sh"` |
| hooks/fswatch-manager.sh:14 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `SCRIPT_PATH="$HOME/.claude/hooks/git-fswatch.sh"` |
| hooks/fswatch-manager.sh:261 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `local service_file="$HOME/.claude/systemd/git-fswatch@.service"` |
| hooks/git-fswatch.sh:274 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `if [ -f "$HOME/.claude/hooks/lib/checkpoint-core.sh" ]; then` |
| hooks/git-fswatch.sh:275 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `. "$HOME/.claude/hooks/lib/checkpoint-core.sh"` |
| hooks/git-hooks/pre-commit:20 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `if [ -f "$HOME/.claude/hooks/sentinel-lint.sh" ]; then` |
| hooks/git-hooks/pre-commit:24 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `if ! "$HOME/.claude/hooks/sentinel-lint.sh"; then` |
| hooks/git-hooks/pre-commit:32 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `if [ -f "$HOME/.claude/hooks/pre-commit-check.sh" ]; then` |
| hooks/git-hooks/pre-commit:33 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `"$HOME/.claude/hooks/pre-commit-check.sh"` |
| hooks/posttool-git-checkpoint.sh:61 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `. "$HOME/.claude/hooks/lib/checkpoint-core.sh"` |
| hooks/pretool-bash-safety.sh:8 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `CLAUDE_HOME="${CLAUDE_HOME:-${HOME}/.claude}"` |
| hooks/pretool-runcode-watchdog.py:29 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `WATCHDOG_SCRIPT = str(Path.home() / ".claude" / "scripts" / "runcode-watchdog.py")` |
| hooks/start-fswatch-all.sh:62 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `nohup bash ~/.claude/hooks/git-fswatch.sh "$repo" \` |
| hooks/subagentstop-artifact-contract-enforce.py:363 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `real = os.path.realpath(os.path.expanduser("~/.claude"))` |
| scripts/canary-verify.sh:18 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `HOOKS_DIR_DEFAULT="${HOME}/.claude/hooks"` |
| scripts/canary-verify.sh:35 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"` |
| scripts/check-file-references.sh:190 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `"$HOME/.claude/settings.json"` |
| scripts/detect-dead-functions.sh:9 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `COMMANDS_DIR="${2:-${CLAUDE_COMMANDS_DIR:-${HOME}/.claude/commands}}"` |
| scripts/detect-dead-functions.sh:11 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `AGENTS_DIR="${3:-${CLAUDE_AGENTS_DIR:-${HOME}/.claude/agents}}"` |
| scripts/detect-orphan-agents.sh:16 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `GLOBAL_CLAUDE_DIR="$HOME/.claude"` |
| scripts/detect-orphan-commands.sh:16 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `GLOBAL_CLAUDE_DIR="$HOME/.claude"` |
| scripts/detect-orphan-scripts.sh:16 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `GLOBAL_CLAUDE_DIR="$HOME/.claude"` |
| scripts/dev-lifecycle.py:112 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `Path.home() / ".claude" / "hooks" / "lib" / "close-verdict.py",` |
| scripts/execute-push.py:38 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `_PUSH_SH_TILDE = "~/.claude/hooks/push.sh"` |
| scripts/seal-attribution-journal.py:70 | HARNESS-HOME-ASSUMED | harness asset located via $HOME/.claude instead of the script's own location / resolver; breaks when the harness is not at ~/.claude — `base = os.path.realpath(str(Path.home() / ".claude"))` |
| hooks/audit-slashcommand.sh:8 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `LOGS_DIR="$HOME/.claude/logs"` |
| hooks/fswatch-manager.sh:171 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `local log_file="$HOME/.claude/logs/git-fswatch.log"` |
| hooks/git-fswatch.sh:27 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `LOG_FILE="${HOME}/.claude/logs/git-fswatch-${REPO_NAME}.log"` |
| hooks/git-hooks/post-commit-auto-push:23 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `LOG_PATH="${CLAUDE_BACKUP_LOG:-${HOME}/.claude/logs/post-commit-auto-push.log}"` |
| hooks/lib/checkpoint-core.sh:64 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `CHECKPOINT_LOG_DIR="${CHECKPOINT_LOG_DIR:-$HOME/.claude/logs}"` |
| hooks/lib/subagent_restart.py:150 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `return Path.home() / ".claude" / "restart-state"` |
| hooks/lib/subagent_restart.py:846 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `home_projects = Path.home() / ".claude" / "projects"` |
| hooks/pretool-bash-safety.sh:433 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `CONSENT_LOG="$HOME/.claude/logs/bash-consent.log"` |
| hooks/pretool-bash-safety.sh:545 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `DAEMON_RESTART_AUDIT_LOG="${CLAUDE_DAEMON_RESTART_AUDIT_LOG:-$HOME/.claude/logs/claude-daemon-restart-grants.log}"` |
| hooks/pretool-block-background-tasks.py:95 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `Path.home() / ".claude" / "todos" / f"{session_id}-agent-{session_id}.json"` |
| hooks/pretool-spec-block-foreground-agent.py:33 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `return Path.home() / ".claude" / "todos" / f"{session_id}-agent-{session_id}.json"` |
| hooks/push.sh:439 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `mkdir -p ~/.claude/logs` |
| hooks/push.sh:443 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `>> ~/.claude/logs/git-privilege-grants.log` |
| hooks/sessionstart-artifact-census.py:55 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `return Path(override) if override else Path.home() / ".claude" / "restart-state"` |
| hooks/start-fswatch-all.sh:51 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `log_file="$HOME/.claude/logs/fswatch-$repo_name.log"` |
| hooks/start-fswatch-all.sh:52 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `pid_file="$HOME/.claude/logs/fswatch-$repo_name.pid"` |
| hooks/start-fswatch-all.sh:55 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `mkdir -p "$HOME/.claude/logs"` |
| hooks/stop-cleanup-allowlist.sh:23 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `CONSENT_LOG="$HOME/.claude/logs/bash-consent.log"` |
| hooks/stop-completion-gate.py:83 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `ADVISORY_LOG = Path.home() / ".claude" / "logs" / "completion-terminal-gate-advisory.jsonl"` |
| hooks/stop-completion-gate.py:412 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `fallback = Path.home() / ".claude" / "logs" / f"completion-gate-{cycle_id}.json"` |
| hooks/stop-completion-gate.py:567 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `str(Path.home() / ".claude" / "logs" / f"completion-gate-registry-{session_id}.json"),` |
| hooks/stop-do-report-gate.py:58 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `ADVISORY_LOG = Path.home() / ".claude" / "logs" / "do-report-gate-advisory.jsonl"` |
| hooks/stop-obligation-gate.py:56 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `ADVISORY_LOG = Path.home() / ".claude" / "logs" / "obligation-terminal-gate-advisory.jsonl"` |
| hooks/subagentstop-cp-enforce.py:34 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `logdir = os.path.expanduser("~/.claude/logs")` |
| hooks/userprompt-consent-allowlist.sh:666 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `CONSENT_LOG="$HOME/.claude/logs/bash-consent.log"` |
| scripts/break-overnight-lock.py:31 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `TODOS_DIR = Path.home() / ".claude" / "todos"` |
| scripts/capability-handshake.py:91 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `root = Path.home() / ".claude" / "projects"` |
| scripts/lifecycle-baseline-import.sh:15 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `LIFECYCLE_FILE_DEFAULT="${HOME}/.claude/logs/lifecycle.jsonl"` |
| scripts/lifecycle-baseline-import.sh:16 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `SCORES_FILE_DEFAULT="${HOME}/.claude/agent-scores.json"` |
| scripts/prune-orphaned-workflow-bookmarks.sh:182 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `LOG_DIR="$HOME/.claude/logs"` |
| scripts/score-inject.sh:15 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `LIFECYCLE_FILE_DEFAULT="${HOME}/.claude/logs/lifecycle.jsonl"` |
| scripts/score-update.sh:40 | STATE-UNDER-HOME-CLAUDE | runtime/config-dir data hard-wired to $HOME/.claude (ignores CLAUDE_CONFIG_DIR; separate harness state root absent, see E2) — `LIFECYCLE_FILE_DEFAULT="${HOME}/.claude/logs/lifecycle.jsonl"` |

Other HOME-derived lines (no functional effect): hooks/install-auto-sync.sh:97,101,105,119,150,160,217,223,224,228,257,262,263,268,273 [DEAD]; hooks/install-git-hooks.sh:56 [DEAD]; hooks/install-protection-all.sh:84,123,138,139 [DEAD]; hooks/install.sh:76,80,106,110,112,180,181,184 [DEAD]; hooks/protection-status.sh:37,84 [DEAD]; hooks/auto-commit.sh:53 [DOCS]; hooks/check-todo-md-sync.py:5,6 [DOCS]; hooks/checkpoint.sh:54,80 [DOCS]; hooks/git-fswatch.sh:305,329 [DOCS]; hooks/git-hooks/pre-commit:38 [DOCS]; hooks/hook-todo-injection.py:11,68 [DOCS]; hooks/lib/checkpoint-core.sh:665,779 [DOCS]; hooks/lib/todo_canonical.py:50 [DOCS]; hooks/merge.sh:47 [DOCS]; hooks/posttool-git-checkpoint.sh:78 [DOCS]; hooks/posttool-todo-sequence.py:181 [DOCS]; hooks/pretool-block-enterworktree.sh:87 [DOCS]; hooks/pretool-git-privilege-guard.py:89,396,847 [DOCS]; hooks/pretool-spec-block-foreground-agent.py:17 [DOCS]; hooks/pretool-todo-validate.py:212 [DOCS]; hooks/prompt-workflow.py:815,816,2015 [DOCS]; hooks/push.sh:63 [DOCS]; hooks/start-fswatch-all.sh:90,91,93 [DOCS]; hooks/stop-completion-gate.py:48 [DOCS]; hooks/stop.sh:21 [DOCS]; hooks/subagentstop-artifact-contract-enforce.py:61,361 [DOCS]; hooks/userprompt-doc-sync-check.py:11 [DOCS]; scripts/bootstrap:190 [DOCS]; scripts/dev-lifecycle.py:117 [DOCS]; scripts/execute-push.py:10 [DOCS]; scripts/install/install:15 [DOCS]; scripts/install/render-settings:28 [DOCS]; scripts/install/tests/installer-acceptance.py:346,805 [DOCS]; scripts/orchestrator.sh:222 [DOCS]; scripts/verify-claims.sh:7,339 [DOCS]; scripts/write-commit-grant.py:276 [DOCS]; hooks/lib/claude_home.py:18 [PORTABLE-OK]; hooks/lib/claude_home.sh:87,102 [PORTABLE-OK]; hooks/merge.sh:49 [PORTABLE-OK]; hooks/stop.sh:23 [PORTABLE-OK]; hooks/userprompt-consent-allowlist.sh:403 [PORTABLE-OK]; scripts/install/installer.py:10 [PORTABLE-OK]

venv path assumptions (harness venv assumed at ~/.claude/venv):

| location | class | what is wrong |
|---|---|---|
| hooks/README-TODO-INJECTION.md:120 | code AUTHOR-DEFAULT | harness venv assumed under ~/.claude |
| hooks/pretool-bash-safety.sh:13 | code AUTHOR-DEFAULT | PYTHON_BIN from ${CLAUDE_HOME:-$HOME/.claude}/venv, silently falls back to system python3 |
| hooks/pretool-workflow-gate.py:54 | code AUTHOR-DEFAULT | regex requires the interpreter path to contain /.claude/venv/ (misses a harness installed elsewhere) |
| hooks/prompt-workflow.py:1542 | code AUTHOR-DEFAULT | graphify binary looked up at Path.home()/.claude/venv, not the resolved harness home |
| scripts/canary-verify.sh:36 | code AUTHOR-DEFAULT | CLAUDE_HOME defaults to $HOME/.claude (:35) -> venv probe wrong elsewhere; canary silently skipped |
| scripts/create-overnight-state.sh:874 | code AUTHOR-DEFAULT | ${CLAUDE_HOME:-$HOME/.claude}/venv: correct only if CLAUDE_HOME exported or harness at ~/.claude |
| scripts/lifecycle-baseline-import.sh:59 | code AUTHOR-DEFAULT | source ~/.claude/venv/bin/activate (harness venv assumed at ~/.claude) |
| scripts/overnight-init.sh:222 | code AUTHOR-DEFAULT | ${CLAUDE_HOME:-$HOME/.claude}/venv |
| scripts/score-inject.sh:70 | code AUTHOR-DEFAULT | source ~/.claude/venv/bin/activate |
| scripts/score-update.sh:193 | code AUTHOR-DEFAULT | source ~/.claude/venv/bin/activate |
| scripts/score-update.sh:198 | code AUTHOR-DEFAULT | source ~/.claude/venv/bin/activate |
| scripts/score-update.sh:199 | code AUTHOR-DEFAULT | source ~/.claude/venv/bin/activate |
| scripts/score-update.sh:220 | code AUTHOR-DEFAULT | source ~/.claude/venv/bin/activate |
| agents/architect.md:406 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/ba.md:1343 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/dev.md:419 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/dev.md:431 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/graphify.md:48 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/pm.md:1060 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/product-owner.md:422 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/qa.md:1074 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/qa.md:1125 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/qa.md:1137 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/qa.md:1138 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/qa.md:1145 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/qa.md:1233 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/spec.md:470 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/spec.md:494 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/spec.md:551 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/spec.md:610 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/spec.md:617 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/spec.md:666 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/spec.md:732 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/test-executor.md:47 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/test-executor.md:91 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/test-executor.md:249 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/test-executor.md:288 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/test-executor.md:354 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/test-executor.md:356 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/test-executor.md:360 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/test-executor.md:361 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/test-executor.md:368 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/test-executor.md:379 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/test-validator.md:46 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/test-validator.md:73 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| agents/user.md:528 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/close.md:336 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/close.md:450 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/close.md:776 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/close.md:815 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/close.md:949 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/commit.md:964 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/dev-command.md:746 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/dev-command.md:1155 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/dev-overnight.md:955 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/dev-overnight.md:1259 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/dev-overnight.md:1540 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/dev.md:244 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/dev.md:256 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/dev.md:794 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/dev.md:1148 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/pull.md:110 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/restart.md:70 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/restart.md:116 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/restart.md:129 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/spec.md:335 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/test.md:36 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/test.md:206 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/test.md:265 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/test.md:338 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/test.md:394 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |
| commands/tickets.md:34 | prompt AUTHOR-DEFAULT | prompt tells agents to use ~/.claude/venv (wrong when harness is not at ~/.claude; CLAUDE_HOME not exported) |

Other venv lines: ARCHITECTURE.md:50 [DOCS]; INDEX.md:114 [DOCS]; README.md:471,480,510,513 [DOCS]; docs/reference/INDEX.md:67 [DOCS]; docs/reference/graphify-integration.md:3,115,141,144,147,150 [DOCS]; docs/reference/venv-repair.md:1,4,11,12,15 [DOCS]; hooks/prompt-workflow.py:1536 [DOCS]; requirements.txt:2 [DOCS]; scripts/score-update.sh:191 [DOCS]; scripts/write-qa-mode.sh:55 [PORTABLE-OK]; hooks/tests/test_runtime_guard.py:3424 [TEST-DATA]; tests/generated/20260704-134650/test_AC_E3_a1b2c3d4e5f60013.py:16 [TEST-DATA]; tests/instructions/execution-guide.md:73,332 [TEST-DATA]; tests/reports/edge-case-analysis.json:48 [TEST-DATA]; tests/score-lifecycle-contract/test-lifecycle-cas.sh:86,151,195 [TEST-DATA]; tests/scripts/validate-venv-usage.py:108 [TEST-DATA]; tests/test_bash_write_targets_verb_narrowing.py:62 [TEST-DATA]; tests/test_restart_command.py:716,749,760,783,813 [TEST-DATA]; tests/test_stage_owned_hunks_boundary.py:77 [TEST-DATA]

### C1.d Tests hard-wired to the author machine

| location | class | what is wrong |
|---|---|---|
| hooks/tests/pol_replay_harness.py:122 | TEST-MACHINE | scans author dir /dev/shm/claude-scratch |
| hooks/tests/test_allowlist_consolidation.py:1304 | TEST-MACHINE | HOME default /root for consent log |
| hooks/tests/test_attribution_journal.py:255 | TEST-MACHINE | needs RAM-backed /dev/shm (skips otherwise) |
| hooks/tests/test_attribution_journal.py:462 | TEST-MACHINE | needs RAM-backed /dev/shm (skips otherwise) |
| hooks/tests/test_dual_runtime_lifecycle_e2e.py:23 | TEST-BREAK | falls back to /root/.claude as SOURCE_ROOT |
| hooks/tests/test_dual_runtime_lifecycle_e2e.py:24 | TEST-BREAK | requires /root/.codex/hooks/codex_native_harness.py |
| hooks/tests/test_dual_runtime_lifecycle_e2e.py:30 | TEST-BREAK | reads the live /root/.claude/settings.json |
| hooks/tests/test_dual_runtime_lifecycle_e2e.py:31 | TEST-BREAK | reads /root/.codex/hooks.json |
| hooks/tests/test_dual_runtime_lifecycle_e2e.py:357 | TEST-BREAK | symlinks fixture dirs to /root/.claude |
| hooks/tests/test_dual_runtime_lifecycle_e2e.py:974 | TEST-BREAK | reads /root/.codex/hooks.json |
| hooks/tests/test_git_residual_override.py:48 | TEST-MACHINE | scratch default /dev/shm/gitguard-route (no /dev/shm on macOS) |
| hooks/tests/test_overnight_gitenv_failclosed.py:48 | TEST-MACHINE | lab default under /dev/shm |
| tests/generated/20260704-225139/test_AC_E1_a1b2c3d4e5f60011.py:15 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_E2_a1b2c3d4e5f60012.py:11 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_E2_a1b2c3d4e5f60012.py:18 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_E2_a1b2c3d4e5f60012.py:25 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_E2_a1b2c3d4e5f60012.py:26 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_E3_a1b2c3d4e5f60013.py:15 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_E4_a1b2c3d4e5f60014.py:13 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_E5_a1b2c3d4e5f6001e.py:15 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_E6a_a1b2c3d4e5f6e6a0.py:14 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_E6b_a1b2c3d4e5f6e6b0.py:15 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_E6c_a1b2c3d4e5f6e6c0.py:15 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_E7_e7a1b2c3d4e5f601.py:15 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_F10_f10a1b2c3d4e5f60.py:14 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_F11_f11a1b2c3d4e5f60.py:14 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_F1_a1b2c3d4e5f60015.py:14 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_F2_a1b2c3d4e5f60016.py:14 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_F3_a1b2c3d4e5f60017.py:14 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_F4_a1b2c3d4e5f6001f.py:14 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_F5_a1b2c3d4e5f60020b.py:14 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_F6_a1b2c3d4e5f60020c.py:14 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_F7_f7a1b2c3d4e5f601.py:14 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_F7b_f7ba1b2c3d4e5f60.py:14 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_F8_f8a1b2c3d4e5f601.py:14 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/generated/20260704-225139/test_AC_F9_f9a1b2c3d4e5f601.py:14 | TEST-BREAK | generated AC test pins the author tmpfs checkout path (E1 delete candidate) |
| tests/test_paseo_daemon_ledger.py:3022 | TEST-MACHINE | NODE=/usr/bin/node |
| tests/test_paseo_daemon_ledger.py:3023 | TEST-MACHINE | vendor scheduler under /opt/paseo (author install) |
| tests/test_paseo_daemon_ledger.py:3793 | TEST-MACHINE | vendor parser under /opt/paseo |
| tests/test_paseo_daemon_ledger.py:4278 | TEST-BREAK | asserts the author default /root/.paseo/schedules (pins the bug) |
| tests/test_prompt_workflow_injection_cadence.py:348 | TEST-MACHINE | tempfile dir='/dev/shm' (absent on macOS) |
| tests/test_prompt_workflow_injection_cadence.py:963 | TEST-MACHINE | tempfile dir='/dev/shm' |
| tests/test_prompt_workflow_injection_cadence.py:993 | TEST-MACHINE | tempfile dir='/dev/shm' |
| tests/test_prompt_workflow_injection_cadence.py:1016 | TEST-MACHINE | tempfile dir='/dev/shm' |
| tests/test_prompt_workflow_injection_cadence.py:1035 | TEST-MACHINE | tempfile dir='/dev/shm' |
| tests/test_specialist_yield.py:18 | TEST-BREAK | HOOKS_DIR = /root/.claude/hooks |
| tests/test_specialist_yield.py:25 | TEST-BREAK | PROD_POLICY_PATH under /root/.claude |
| tests/verify-stop-spec-session-isolation.sh:9 | TEST-BREAK | HOOK=/root/.claude/hooks/stop-spec-coverage-enforce.py |

Tests that read the TRACKED repo settings.json and therefore pin the author live config (they break or must change when settings.json becomes generated):

* hooks/tests/test_runcode_watchdog_aliases.py:74-79 — asserts live == template rendered with the literal "/root/.claude" (currently FAILS; the invariant is right, the literal is not)
* hooks/tests/test_stop_obligation_gate.py:66 — asserts live Stop has stop-obligation-gate.py (a live-only registration; template lacks it)
* hooks/tests/test_obligation_gate.py:289 — reads REPO/settings.json registration
* hooks/tests/test_capability_gate.py:232 — live_settings = REPO/settings.json (render-mutation test)
* tests/test_paseo_usage_read.py:148-158 — asserts live settings.json ALLOWS `node scripts/paseo-usage-read.mjs` and that the template must NOT contain it: a test that enforces the drift
* tests/test_restart_command.py:718 — reads live settings.json + template
* tests/generated/20260704-134650/test_AC_B1_a1b2c3d4e5f60002.py:23-32 — reads live settings.json
* hooks/tests/test_dual_runtime_lifecycle_e2e.py:30 — reads /root/.claude/settings.json

TEST-DATA / test comments containing author paths or names (portable input data; no action for C1, names are C3) — grouped by file:

* hooks/tests/fixtures/pol_iteration5_qa_matrix.v1.json: 7295, 7299
* hooks/tests/test_attribution_journal.py: 256, 257, 264, 265, 267, 463, 465
* hooks/tests/test_bulk_commit_sentinel.py: 755
* hooks/tests/test_dual_runtime_lifecycle_e2e.py: 121
* hooks/tests/test_git_prefix_enumeration.py: 348, 354
* hooks/tests/test_git_residual_override.py: 134, 195, 204
* hooks/tests/test_overnight_gitenv_failclosed.py: 20, 282, 283, 287, 288, 467, 469, 471, 475, 478, 479
* hooks/tests/test_overnight_qa_sentinel_bind.py: 25, 50
* hooks/tests/test_residual_false_positives.py: 125
* hooks/tests/test_runcode_watchdog_aliases.py: 78
* hooks/tests/test_runtime_guard.py: 70, 73, 76, 156, 175, 176, 177, 199, 200, 201, 209, 315, 316, 317, 337, 403, 404, 405, 410, 418, 419, 537, 540, 541, 542, 555, 642, 677, 856, 1024, 1025, 1029, 1040, 1041, 1042, 1043, 1088, 1091, 1172, 1229, 1235, 1236, 1241, 1254, 1359, 1508, 1543, 1959, 2080, 2547, 3038, 3054, 3156, 3191, 3352, 3353, 3387, 3388, 3391, 3392, 3462, 3514, 3535, 3567, 3628, 3629, 3672, 3673, 3679, 3690, 3691, 3697, 3703, 3704, 3705, 3706, 3784, 3786, 3787, 3797, 3798, 3885, 3887, 3888, 3897, 3898, 3908, 3957, 4005, 4030, 4031
* hooks/tests/test_scratch_lifecycle.py: 19
* hooks/tests/test_unit_anchor.py: 85, 86, 90, 91, 95, 96, 97, 103, 107, 108
* hooks/tests/test_unit_find_cmds.py: 30, 34, 39, 43, 58, 59, 60, 79, 83, 84, 99
* hooks/tests/test_unit_pathmatch.py: 47, 48
* hooks/tests/test_userprompt_usage_snapshot.py: 32, 42, 43, 97, 98, 99, 128
* tests/__init__.py: 1
* tests/baselines/default-run-failures.json: 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 30, 31, 32, 34, 35, 39, 40, 73
* tests/fixtures/canary-tool-policy.v1.json: 3
* tests/fixtures/late_repair_golden/spec-20260907-115508-lawful-commit-channel.pre-r4.md: 27, 39, 124, 128, 129, 191, 297, 298
* tests/fixtures/paseo-usage-envelope-20260828.json: 2, 11, 37, 38, 56, 57
* tests/fixtures/paseo_cron_vendor_vectors.json: 2, 5
* tests/fresh-clone-bootstrap-smoke.sh: 48, 50, 72, 84, 147, 296, 322, 384
* tests/generated/20260704-134650/manifest.json: 225
* tests/generated/20260704-134650/test_AC_E2_a1b2c3d4e5f60012.py: 18
* tests/generated/20260704-225139/manifest.json: 35
* tests/generated/20260704-225139/test_AC_E4_a1b2c3d4e5f60014.py: 18
* tests/reports/edge-case-analysis.json: 3
* tests/test_aggregate_dev_report.py: 495
* tests/test_codex_workflow_gate.py: 223, 308, 480, 575, 660, 698, 725, 750
* tests/test_dev_todo_codex_native_parse.py: 10
* tests/test_interruption_signals.py: 4
* tests/test_late_repair_route.py: 1204
* tests/test_paseo_daemon_ledger.py: 83, 102, 472, 475, 570, 573, 596, 597, 599, 605, 606, 615, 623, 624, 625, 651, 652, 653, 668, 670, 672, 673, 674, 675, 676, 683, 688, 690, 696, 705, 818, 984, 993, 995, 998, 999, 1001, 1008, 1009, 1012, 1020, 1021, 1149, 1150, 1152, 1157, 2274
* tests/test_paseo_daemon_timers.py: 62
* tests/test_paseo_usage_read.py: 24, 94, 97, 105, 106, 107, 108, 110, 124, 126, 131
* tests/test_prompt_workflow_liveness_tz.py: 204, 205, 232
* tests/test_public_core_residue_gate.py: 4, 8, 33, 185, 186, 187, 219, 269, 302, 347, 348, 349, 472, 491, 506
* tests/test_restart_command.py: 839, 845, 854, 1042, 1044
* tests/test_spec_update_command_contracts.py: 986, 990, 1001
* tests/test_specialist_yield.py: 6
* tests/test_tool_policy_inference_note.py: 107, 378
* tests/verify-stop-spec-session-isolation.sh: 82, 84, 156, 216, 240, 242
* tests/ws2_zero_literal_gate.py: 14, 15, 53, 54, 55, 57, 60, 71, 125, 127, 128, 129, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 142, 144, 157, 158, 161, 173, 174, 207, 208, 211

### C1.e Prompts and docs

| location | class | what is wrong |
|---|---|---|
| README.md:438 | DOCS-FALSE-CLAIM | claims a fresh non-root clone works with zero load-bearing author paths; false while tracked settings.json carries 83 /root/.claude hook commands — `The harness runs on a fresh non-root clone. Clone to '$HOME/.claude' on any Linux box (non-root user, '$HOME' not under '/root'), populate the venv, and the core flows resolve to *your* home with zero author-path literals load-bearing. The ` |
| README.md:442 | DOCS-FALSE-CLAIM | claims a fresh non-root clone works with zero load-bearing author paths; false while tracked settings.json carries 83 /root/.claude hook commands — `\| **Fresh non-root clone**: core flows resolve to *your* home with zero author-path literals load-bearing \| 'tests/' WS2 smoke test — runs under a synthetic non-root '$HOME' with the author's home absent; asserts "core is runnable" and "s` |
| README.md:445 | DOCS-FALSE-CLAIM | claims a fresh non-root clone works with zero load-bearing author paths; false while tracked settings.json carries 83 /root/.claude hook commands — `\| **Zero author-path literals load-bearing** \| 'hooks/lib/claude_home.{sh,py}' structural resolver handles runtime path lookup; production hooks still retain known historical '/root/' and '/dev/shm' topology literals tied to the nested-re` |
| agents/graphify.md:94 | DOCS | example / cross-reference text (often to the author's gitignored /root/docs) — `- 'CLAUDE_GRAPHIFY_CACHE_ROOT' — override '/var/tmp/claude-graphify'` |
| agents/qa.md:579 | DOCS | example / cross-reference text (often to the author's gitignored /root/docs) — `grep -nE "(/root/\|/home/\|/tmp/\|/var/\|/etc/)" <file>` |
| agents/qa.md:614 | DOCS | example / cross-reference text (often to the author's gitignored /root/docs) — `"finding": "Hardcoded path /root/deploy/",` |
| agents/qa.md:1644 | DOCS | example / cross-reference text (often to the author's gitignored /root/docs) — `- Hardcoded file paths (e.g., '/root/', '/home/user/') that should be parameters` |
| agents/style-inspector.md:198 | DOCS | example / cross-reference text (often to the author's gitignored /root/docs) — `> **PRE-SCAN**: Run '~/.claude/scripts/detect-hardcoded-paths.sh "$PROJECT_ROOT"' first to get a baseline list of hardcoded '/root/', '/tmp/', '/home/' paths. Then read each flagged file to confirm or dismiss.` |
| commands/close.md:32 | DOCS | example / cross-reference text (often to the author's gitignored /root/docs) — `<!-- Cross-reference: BA spec /root/docs/dev/ba-spec-20260426-redev8.md § AC-CLOSE-FORCE-1..6 govern --force / --reason behavior. -->` |
| commands/dev-overnight.md:1085 | DOCS | example / cross-reference text (often to the author's gitignored /root/docs) — `# NOT substitute an absolute /root/… path (hardcoding), do NOT drop '\|\| exit 1'.` |
| commands/dev.md:1723 | DOCS | example / cross-reference text (often to the author's gitignored /root/docs) — `> "Restore '/root/.claude/agents/ui-specialist.md' to its pre-rewrite content. Acceptance: file length is exactly 657 lines AND its sha256 matches the byte stream pinned at nested-repo HEAD blob '7e5a4b3...'. The restore MUST NOT touch any ` |
| commands/dev.md:1729 | DOCS | example / cross-reference text (often to the author's gitignored /root/docs) — `> "Use the Write tool to overwrite the file with the original content. Run 'git -C "$CLAUDE_PROJECT_DIR" show HEAD:agents/ui-specialist.md > /root/.claude/agents/ui-specialist.md'. Then verify with 'wc -l'."` |
| commands/dev.md:1743 | DOCS | example / cross-reference text (often to the author's gitignored /root/docs) — `- **dev-registry sentinel-registration boilerplate** (the standard 'cat > /root/.claude/dev-registry/<sid>/<role>.json << 'REGEOF'' pattern is subagent-internal scaffolding, not orchestrator HOW-prescription, and is exempted by the hook)` |
| commands/dev.md:1749 | DOCS | example / cross-reference text (often to the author's gitignored /root/docs) — `Self-test fixtures live at '/root/docs/dev/redev-prompt-purity-20260426-self-test.md'.` |
| commands/paseo-daemon.md:20 | DOCS-AUTHOR | author account names in a shipped command prompt — `<ACCT_1>, <ACCT_2>, <ACCT_3> — each with its OWN weekly reset instant)` |
| commands/paseo-daemon.md:424 | DOCS | example / cross-reference text (often to the author's gitignored /root/docs) — `'/usr/local/bin/paseo-account-matrix-gen' (8 models × 3 accounts,` |
| commands/paseo-daemon.md:514 | DOCS | example / cross-reference text (often to the author's gitignored /root/docs) — `- DO NOT modify the paseo kernel or any external asset: '/opt/paseo/**',` |
| commands/paseo-daemon.md:516 | DOCS | example / cross-reference text (often to the author's gitignored /root/docs) — `'/usr/local/bin/paseo-account-matrix-gen', '/root/bin/*' (incl.` |
| commands/restart.md:96 | DOCS | example / cross-reference text (often to the author's gitignored /root/docs) — `'/var/lib/claude-accounts/<name>/claude/projects/<slug>/' — the human may` |
| skills/ui-shared/anti-pattern-catalog.yml:3 | DOCS | example / cross-reference text (often to the author's gitignored /root/docs) — `# Spec: /root/docs/dev/specs/spec-20260426-080555.md sections 5.4, 5.11, 5.16.` |
| skills/ui-shared/rule-map.json:17 | DOCS | example / cross-reference text (often to the author's gitignored /root/docs) — `"spec_reference": "/root/docs/dev/specs/spec-20260426-080555.md sections 5.4, 5.6, 5.11, 5.15, 5.16, 5.17",` |

Docs / data lines mentioning author paths (DOCS; NESTED-REPO.md is the documented private-lab file; dated docs/reference records are E4) — grouped by file:

* ARCHITECTURE.md: 64
* INDEX.md: 447
* NESTED-REPO.md: 3, 7, 8, 9, 11, 15, 18, 19, 20, 21, 24, 28, 29, 30, 34, 36
* PUBLIC-CORE.md: 24, 32, 68, 70, 72, 76, 77, 82, 83, 92, 93, 96, 97, 144, 145, 161
* docs/reference/MORNING-20260907.md: 47, 150, 160, 161, 173, 181, 182, 183, 184, 187, 188, 191, 192, 251, 252, 284, 407, 456
* docs/reference/abandoned-cycles-20260905.md: 18, 20, 24, 104, 143, 144, 145, 153, 166, 231, 242, 376
* docs/reference/attribution-journal-phase0-facility.md: 16, 62
* docs/reference/claim-verification-methodology-20260925.md: 17
* docs/reference/close-commit-zero-failure-mechanism-20260928.md: 4
* docs/reference/controller-error-taxonomy-20260924.md: 172
* docs/reference/core-context-refactor-plan.md: 143
* docs/reference/dev-command-20261003-020648-takeover-record.md: 19
* docs/reference/graphify-integration.md: 61, 100, 110
* docs/reference/harness-defects-20260906-controller.md: 25, 28, 29, 35, 36, 283, 339, 457, 464, 519, 520, 521, 524, 527, 528, 542, 543, 549, 551, 552, 565, 566, 586, 588, 629, 632, 633, 634, 643, 658, 663, 667, 668
* docs/reference/harness-fix-status-20260905.md: 18, 91, 123, 125, 468, 484, 614, 623, 650, 679
* docs/reference/harness-issues-backlog.md: 13, 14, 42, 43, 46, 58, 73, 76, 77, 90, 93, 120, 121, 128, 137, 150, 155, 171, 183, 191, 230, 244, 246, 248
* docs/reference/merge-pipeline-blocked-steps-20261007.md: 150
* docs/reference/monolith-split-plan.md: 44, 107, 123, 150
* docs/reference/paseo-daemon-teachings-20260910.md: 18, 214, 228, 230, 238, 240, 245, 248, 253, 276, 304, 316, 318, 324, 452, 487, 512, 517, 521, 641, 712
* docs/reference/quarantine-record-dev-20260915-020044.md: 123
* docs/reference/restart-detector-quota-text-match-false-positive-20260915.md: 14, 75, 81, 368, 381
* docs/reference/roadmap-decomposition-productization.md: 209, 217, 226, 231, 232, 233, 239, 240
* docs/reference/tmpfs-persistent-backups-20261005.md: 3
* docs/reference/workflow-bookmark-orphans-20261005.md: 11
* examples/guard-demo/README.md: 68
* policies/public-core-residue-allowlist.v1.json: 289, 884
* scripts/INDEX.md: 44
* skills/ui-beauty-score/README.md: 43, 44

---
## C2 — settings.json vs settings.template.json, renderer, bootstrap/doctor/installer, protected-runtime.json

### C2.a The tracked settings.json is the author live config, with several producers and no single source

Producers that write the harness settings today (the architecture wants exactly one):

| # | producer | where | effect |
|---|---|---|---|
| 1 | agents/humans editing settings.json directly | git log --oneline: 75 commits touch settings.json vs 10 for settings.template.json (last: 906c782 2026-10-08 vs 62ae1ec 2026-10-05) | live-only hooks/permissions never reach the template |
| 2 | Claude Code CLI write-back (/model, /config, "always allow") | settings.json:295 `"model": "fable"`, settings.json:921 `"tui": "fullscreen"` (not in template) | user/machine choices land in a tracked, published file |
| 3 | scripts/install/render-settings | invoked by scripts/bootstrap:183 (only when settings.json is absent or `--force`) and .github/workflows/baseline.yml:69-80 (CI) | the only producer that derives paths from the install home |
| 4 | scripts/install/installer.py additive merge | installer.py:344-361 (isolated-root copy, written at :1049) + merge into the user config-dir settings.json (core.json:103-131) | a second, different settings producer (2 hooks) |
| 5 | legacy installers (disabled) | hooks/install.sh:109-112, hooks/install-auto-sync.sh:96-101 (unreachable after `exit 0` at :15 / :12) | dead code (D1/E1) |

scripts/apply-permissions.sh:21 writes `<project>/.claude/settings.json` (project scope), not the harness file; not a producer of this artifact.

#### Full settings.json vs settings.template.json diff (placeholders normalised `{{CLAUDE_HOME}}` -> `/root/.claude`)

Totals: hooks 83 vs 73 commands (9 vs 8 events: SessionEnd is live-only); permissions allow 159 vs 150, deny 96 vs 85, ask 0 vs 23.

Hooks only in settings.json (14) — every one is absent from what a fresh install or CI renders:

| settings.json line | event | matcher | hook | note |
|---|---|---|---|---|
| settings.json:321 | SessionStart | `(none)` | session-scratch-init.sh | creates the TMPDIR root; without it the template TMPDIR is never created |
| settings.json:397 | UserPromptSubmit | `(none)` | userprompt-usage-snapshot.py | author multi-account usage snapshot |
| settings.json:424 | PreToolUse | `(none)` | pretool-do-block-subagents.py |  |
| settings.json:611 | PreToolUse | `Agent` | pretool-obligation-gate.py | G1 dispatch gate (producer architecture, A1) |
| settings.json:615 | PreToolUse | `Agent` | pretool-commit-dispatch-attest.py |  |
| settings.json:662 | PreToolUse | `Bash` | pretool-push-analyst-grant-guard.py |  |
| settings.json:725 | PostToolUse | `Write\|Edit\|NotebookEdit\|MultiEdit` | posttool-lane-completeness-watch.py |  |
| settings.json:734 | PostToolUse | `Write` | posttool-push-gate-token-verify.py |  |
| settings.json:819 | Stop | `(none)` | stop-workflow-coordinator.py | runs the 4 template-only Stop hooks internally (stop-workflow-coordinator.py:63-68) |
| settings.json:827 | Stop | `(none)` | stop-do-report-gate.py | B4 |
| settings.json:835 | Stop | `(none)` | stop-obligation-gate.py | G4 terminal gate (A1/A2) |
| settings.json:843 | Stop | `(none)` | stop-completion-gate.py | B1 (blocks /dev Stop outside the harness repo) — do not ship to the template until B1 is fixed |
| settings.json:853 | SessionEnd | `(none)` | sessionend-scratch-sweep.sh | whole SessionEnd event missing from template |
| settings.json:904 | SubagentStop | `*` | subagentstop-artifact-contract-enforce.py | G2 producer-stop gate (A1) |

Hooks only in settings.template.json (4): settings.template.json:764 stop-overnight-timelock.py, :768 stop-spec-coverage-enforce.py, :772 auto-commit.sh, :776 stop-cleanup-allowlist.sh (all in one Stop group at :759). Live runs all four through stop-workflow-coordinator.py:63-68, so the template is a pre-coordinator snapshot; a `bootstrap --force` render would drop the coordinator AND 13 other live hooks (incl. the producer gates G1/G2/G4) — an enforcement downgrade (runtime-verification.md:270). CLAUDE.md "stop-cleanup-allowlist.sh is not registered" is therefore also stale (D4).

Permission differences (every entry, with line numbers in both files):

| list | entry | settings.json | settings.template.json |
|---|---|---|---|
| allow | `Bash(/root/bin/paseo-timeline-healer.mjs:*)` | 186 | - |
| allow | `Bash(/root/bin/session-link-sync.sh:*)` | 185 | - |
| allow | `Bash(/usr/local/bin/paseo-self-update --help:*)` | 188 | - |
| allow | `Bash(/usr/local/bin/paseo-self-update --reset-state:*)` | 189 | - |
| allow | `Bash(curl:*)` | 66 | - |
| allow | `Bash(do)` | - | 105 |
| allow | `Bash(docker exec:*)` | 68 | - |
| allow | `Bash(docker run:*)` | 72 | - |
| allow | `Bash(done)` | - | 106 |
| allow | `Bash(else)` | - | 109 |
| allow | `Bash(fi)` | - | 110 |
| allow | `Bash(if:*)` | - | 107 |
| allow | `Bash(node --disable-warning=DEP0040 /root/bin/paseo-timeline-healer.mjs:*)` | 187 | - |
| allow | `Bash(node scripts/paseo-usage-read.mjs:*)` | 190 | - |
| allow | `Bash(python3 /root/.claude/scripts/session-resources.py:*)` | 191 | - |
| allow | `Bash(python3 scripts/lib/soundness_gate.py:*)` | 193 | - |
| allow | `Bash(python3 scripts/session-resources.py:*)` | 192 | - |
| allow | `Bash(scripts/canary-verify.sh:*)` | - | 176 |
| allow | `Bash(scripts/lifecycle-baseline-import.sh:*)` | - | 175 |
| allow | `Bash(scripts/score-inject.sh:*)` | - | 174 |
| allow | `Bash(scripts/score-update.sh:*)` | - | 173 |
| allow | `Bash(scripts/test:*)` | 121 | - |
| allow | `Bash(then)` | - | 108 |
| allow | `Bash(wget:*)` | 150 | - |
| allow | `Edit(**/Cargo.toml)` | 154 | - |
| allow | `Edit(**/go.mod)` | 155 | - |
| allow | `Edit(**/package.json)` | 156 | - |
| allow | `Edit(**/pyproject.toml)` | 157 | - |
| allow | `Edit(**/requirements.txt)` | 158 | - |
| ask | `Bash(curl:*)` | - | 290 |
| ask | `Bash(docker exec:*)` | - | 279 |
| ask | `Bash(docker rm:*)` | - | 280 |
| ask | `Bash(docker run:*)` | - | 278 |
| ask | `Bash(git push --force:*)` | - | 284 |
| ask | `Bash(git push -f:*)` | - | 285 |
| ask | `Bash(git reset --hard:*)` | - | 286 |
| ask | `Bash(kubectl apply:*)` | - | 282 |
| ask | `Bash(kubectl create:*)` | - | 283 |
| ask | `Bash(kubectl delete:*)` | - | 281 |
| ask | `Bash(npm publish:*)` | - | 287 |
| ask | `Bash(rm -rf:*)` | - | 289 |
| ask | `Bash(wget:*)` | - | 291 |
| ask | `Bash(yarn publish:*)` | - | 288 |
| ask | `Edit(**/Cargo.toml)` | - | 294 |
| ask | `Edit(**/go.mod)` | - | 295 |
| ask | `Edit(**/package.json)` | - | 292 |
| ask | `Edit(**/pyproject.toml)` | - | 293 |
| ask | `Edit(**/requirements.txt)` | - | 296 |
| ask | `Edit(.claude/CLAUDE.md)` | - | 300 |
| ask | `Edit(.claude/hooks/**)` | - | 297 |
| ask | `Edit(.claude/scripts/**)` | - | 298 |
| ask | `Edit(.claude/settings.json)` | - | 299 |
| deny | `Bash(docker rm:*)` | 199 | - |
| deny | `Bash(kubectl apply:*)` | 205 | - |
| deny | `Bash(kubectl create:*)` | 206 | - |
| deny | `Bash(kubectl delete:*)` | 207 | - |
| deny | `Bash(npm publish:*)` | 209 | - |
| deny | `Bash(rm -rf:*)` | 214 | - |
| deny | `Bash(yarn publish:*)` | 227 | - |
| deny | `Edit(.claude/CLAUDE.md)` | 236 | - |
| deny | `Edit(.claude/hooks/**)` | 237 | - |
| deny | `Edit(.claude/scripts/**)` | 238 | - |
| deny | `Edit(.claude/settings.json)` | 239 | - |

Reading of the permission diff: live moved 7 destructive entries ask->deny (rm -rf, docker rm, kubectl apply/create/delete, npm/yarn publish) and 4 Edit(.claude/...) ask->deny (stricter), but moved curl, wget, docker run, docker exec and 5 Edit(**/manifest) entries ask->ALLOW (looser), and added 9 author-machine allow entries (/root/bin/*, /usr/local/bin/paseo-self-update, paseo scripts, session-resources). The template allows bare shell keywords `Bash(do|done|if:*|then|else|fi)` (template:105-110) that live dropped. Template internal contradiction: `git push --force`, `git push -f`, `git reset --hard` are in BOTH deny (template:218-220) and ask (template:284-286).

env differences: CLAUDE_CODE_ENABLE_TODO_TOOLS=1 live only (settings.json:21); TMPDIR/CLAUDE_CODE_TMPDIR = /var/tmp/claude-scratch live (settings.json:28-29) vs /dev/shm/claude-tmp template (template:27-28) — and the template `_comment_tmpdir` (template:29) says "disk-backed" while pinning tmpfs; GRAPHIFY_BIN literal (settings.json:24) vs placeholder (template:23). Missing from BOTH: CLAUDE_OBLIGATION_GATE / _STOPGATE / _BARRIER / _TERMINAL (A1). Top level: model "fable" (settings.json:295) vs "opus" (template:303); tui (settings.json:921) live only. deniedMcpServers, cleanupPeriodDays, alwaysThinkingEnabled, effortLevel, theme, autoCompactEnabled, includeCoAuthoredBy are equal.

#### render-settings --check on the tracked file (scratch copy; same result with HOME=/root and with explicit --home /root/.claude): exit 1, 4 failures

1. `required hook wiring missing: hooks/stop-spec-coverage-enforce.py` — the check itself is stale: scripts/install/render-settings:46-51 (REQUIRED_HOOK_SUFFIXES, :49) pins a hook that live runs via the coordinator.
2. `ask entries dropped` — all 23 template ask entries.
3. `allow broadened beyond template` — 19 entries (the live-only allow rows above).
4. `hook arrays differ from template (entries/order parity violation)` — the 14/4 hook drift + group shape.

Control: rendering the template for /home/alice/.claude (`render-settings /home/alice/.claude --print`) and checking that output passes (exit 0). The renderer works; its two inputs (template vs live) disagree.

### C2.b Renderer, bootstrap, doctor and installer gaps (fresh install is bricked, tooling reports success)

| location | gap |
|---|---|
| scripts/bootstrap:166-169 | skips rendering whenever settings.json exists — and it always exists in a clone because it is tracked; the author /root/.claude hooks stay in place (C1.a) and bootstrap prints SUCCESS (:243). Prior evidence runtime-verification.md:76,269. |
| scripts/bootstrap:171-197 | '--force' re-render backs up then replaces the live chain with the stale 73-hook template (drops G1/G2/G4 + coordinator) — enforcement downgrade. |
| scripts/install/render-settings:195-197, :205-207 | default install home = $CLAUDE_HOME or $HOME/.claude, not the renderer own location (repo_root computed at :182-183 is only used for the template path). A bare run from a clone elsewhere renders the wrong home. |
| scripts/install/render-settings:226 | default --out = <template-dir>/settings.json, i.e. it overwrites the tracked file in place (fine once the file is untracked/generated). |
| scripts/install/render-settings:46-51 | REQUIRED_HOOK_SUFFIXES stale (stop-spec-coverage-enforce.py instead of stop-workflow-coordinator.py). |
| scripts/install/render-settings:109-152 | no notion of a per-machine overlay: any machine-specific allow entry is reported as "broadened", so the author cannot be in parity without editing the public template. |
| scripts/bootstrap (missing step) | does not create runtime prerequisites: <home>/logs (first Stop is blocked: hooks/lib/checkpoint-core.sh:519 redirects 2>>$CHECKPOINT_LOG_FILE before any mkdir, runtime-verification.md:272), ~/.config/claude/protected-runtime.json (C2.c), TMPDIR root (template /dev/shm/claude-tmp is never created because session-scratch-init.sh is live-only; canary-verify then false-FAILs, runtime-verification.md:278). |
| scripts/bootstrap:128-141 + requirements/ | lockfiles only for py310/py311/py312; bootstrap refuses Python 3.13 (runtime-verification.md:277) although hooks run on 3.13. |
| scripts/doctor:17-21, :78-140 | checks python3, git, jq, venv, pytest/jsonschema/pyyaml, resolver. Does NOT check: (a) every hook command path in settings.json exists under this home; (b) render-settings --check parity; (c) protected-runtime.json present + valid; (d) TMPDIR root writable; (e) node (scripts/verify-claims.sh:28 requires it). Doctor says "ready" on a bricked clone. |
| hooks/lib/claude_home.sh:40, hooks/lib/claude_home.py:48-57 | structural sentinel requires settings.json; once settings.json is generated/untracked a fresh clone has none until the first render — the sentinel must also accept settings.template.json (installer.py:344-361 writes a stub settings.json into the isolated root partly to satisfy this). |
| scripts/install/profiles/core.json:132-142, :64-75 | installer core profile registers 2 of 83 hooks (pretool-block-background-tasks.py, pretool-block-enterworktree.sh), excludes pretool-bash-safety.sh (:72), agents, commands, skills; never renders (core.json:103-131). It is a guardrails-only install, not the harness. |
| README.md:58-84 vs :94-101 | README presents the installer core profile as "Install"; the full harness is only reachable via the "contributors" clone + bootstrap path, whose bootstrap does not render (above). Neither path yields a working full harness on a non-author machine. |
| README.md:438-445 | claims "fresh non-root clone ... zero author-path literals load-bearing" — false for the tracked settings.json (DOCS-FALSE-CLAIM). |
| README.md:139, :528; ARCHITECTURE.md:20, :28, :356 | claim 71 wired entries / 8 events; live has 83/9, template 73/8 (D4). |
| PUBLIC-CORE.md:44-53 | records generate-then-untrack as half done: render side wired, "untrack side is not done and is not authorized" (user decision U1). |
| hooks/install.sh:1-15, hooks/install-auto-sync.sh:1-12, hooks/install-protection-all.sh:1-11, hooks/install-git-hooks.sh:1-12 | four legacy installers are disabled no-ops (D1/E1), still shipped and still referencing ~/.claude/settings.json and examples/settings-with-checkpoint.json (file absent). |

### C2.c ~/.config/claude/protected-runtime.json: a required out-of-repo input with no producer (FUNCTIONAL-BLOCKER for JS users)

* Location: hooks/lib/runtime_guard/config.py:41-47 (env CLAUDE_PROTECTED_RUNTIME_FILE, else $HOME/.config/claude/protected-runtime.json). Loader config.py:60-74 returns None when the file is missing/invalid or lacks any of the 10 REQUIRED_KEYS (:52-57).
* None => STEP1 fail-closed verb families (hooks/lib/runtime_guard/_core.py:1725-1803) => pretool-bash-safety.sh:291-311 exits 2 with "unbypassable (it runs before /do and /allow)" (:299).
* Measured in scratch with the file absent (HOME=empty dir): BLOCK `npm install`, `node app.js`, `npx prettier .`, `yarn test`, `kill 1234`; ALLOW `pip install`, `make`, `python3 app.py`, `pytest`, `cargo build`, `go build`, `systemctl status`, `curl`, `docker compose up -d`. With a schema_version:1 file holding the 10 REQUIRED_KEYS as empty lists: all ALLOW. Prior evidence: runtime-verification.md:35,68,273 (a bare `{"schema_version":1}` still blocks).
* Producer: none. No example/template in the repo (no tracked file outside tests carries the protected_* keys), bootstrap/installer do not create it, doctor does not check it, README does not mention it. The author container has /root/.config/claude/protected-runtime.json (not read).
* Consumers: hooks/lib/runtime_guard/config.py:60-74, find_cmds.py:195 (self-protection), hooks/tests/test_runtime_guard.py (tmp fixtures only).

### C2.d CI and tests neutralise or pin the drift

* .github/workflows/baseline.yml:56-84 overwrites the tracked settings.json with a template render BEFORE "Verify headline claims" (:197). The comment at :64-66 admits it "does NOT detect drift between the TRACKED settings.json and the template". Consequently scripts/verify-claims.sh section 5 (:336-400, template-sync) compares the template with itself in CI. Run on the tracked file in scratch: `template-sync DRIFT: settings.template.json is MISSING 14 hook(s)`, exit 1.
* scripts/verify-claims.sh:337-344 lets the template be a superset ("only MISSING hooks fail"), so the 4 stale template-only Stop hooks can never be caught.
* CI therefore tests the 73-hook template chain, never the 83-hook chain that runs (no G1/G2/G4 producer gates under CI).
* Tests pin the live file (list in C1.d); tests/test_paseo_usage_read.py:148-158 actively enforces "live has a machine-specific allow entry, template must not".

---
## 3. Fix plan (producer-side, minimal, concrete)

Target state: ONE producer for the harness settings — `scripts/install/render-settings` — rendering `settings.json` (generated, untracked) from `settings.template.json` (tracked, the only source) plus `settings.machine.json` (untracked, per user/machine), with every path derived from the renderer's own install location. Code derives paths from the structural resolver or from the CLAUDE_HOME value the renderer exports. No new pipeline state file; the overlay is user-authored config.

Step 1 — make the template the single source (C2.a; effort M; files: settings.template.json, scripts/install/render-settings)
* Port the 14 live-only hooks into settings.template.json with `{{CLAUDE_HOME}}`, in live order; replace the 4 direct Stop entries (template:759-779) with stop-workflow-coordinator.py; add the SessionEnd event. Hold stop-completion-gate.py out of the PUBLIC template until B1 is fixed (or ship it only after B1), so the public render does not export B1.
* env: TMPDIR/CLAUDE_CODE_TMPDIR -> /var/tmp/claude-scratch and fix _comment_tmpdir (template:27-29); add CLAUDE_CODE_ENABLE_TODO_TOOLS; add `"CLAUDE_HOME": "{{CLAUDE_HOME}}"` so every existing `${CLAUDE_HOME:-$HOME/.claude}` default in code/prompts becomes correct for any install location (canary-verify.sh:35, overnight-init.sh:222, create-overnight-state.sh:874, pretool-bash-safety.sh:8,13, claude_home.py env hint). (A1 adds its CLAUDE_OBLIGATION_* keys here too — template only.)
* permissions: apply decision U2; remove the deny/ask duplicates (template:284-286).
* render-settings: default install home = its own repo root (:195-197, :205-207 -> repo_root from :182-183); REQUIRED_HOOK_SUFFIXES: stop-spec-coverage-enforce.py -> stop-workflow-coordinator.py (:49); add overlay merge: if `<home>/settings.machine.json` exists, its permissions entries, env keys and top-level keys are merged on top of the template, and the parity check becomes `rendered == template (+) overlay` (allow may only broaden via the overlay); keys the template does not own (model, theme, tui, effortLevel, ...) are carried over from an existing settings.json so CLI write-back is not lost; entries present only in the existing settings.json are printed (never silently dropped) so they can be moved into the overlay.

Step 2 — generated, untracked settings.json (C2.a/C2.d; effort S; needs U1; files: .gitignore, hooks/lib/claude_home.sh, hooks/lib/claude_home.py, tests listed in C1.d, scripts/verify-claims.sh, .github/workflows/baseline.yml)
* `git rm --cached settings.json`; ignore `/settings.json` and `/settings.machine.json`. On the author machine the file stays on disk; move the author-only values into settings.machine.json (model fable, tui, the 19 live-only allow entries incl. /root/bin/* and paseo, curl/wget/docker allow if U2 keeps them ask publicly, the author env defaults from Step 4), re-render, confirm `render-settings --check` exit 0.
* Structural sentinel accepts settings.template.json OR settings.json (claude_home.sh:40, claude_home.py:48-57).
* Tests that read REPO/settings.json read a render of the template instead (hooks/tests/test_runcode_watchdog_aliases.py:74-79 keeps its live==render invariant via the renderer, not a /root literal; test_stop_obligation_gate.py:66, test_obligation_gate.py:289, test_capability_gate.py:232, tests/test_restart_command.py:718, tests/test_paseo_usage_read.py:148-158 (delete the drift-enforcing assertion), tests/generated/20260704-134650/test_AC_B1_a1b2c3d4e5f60002.py:23-32).
* scripts/verify-claims.sh section 5 (:336-400) is deleted (one source, nothing to sync); hook counts are recomputed from the rendered template. CI baseline.yml:56-84 keeps rendering — now it renders the only source, so CI tests what users run.

Step 3 — bootstrap and doctor produce/verify a working install (C2.b/C2.c; effort S; files: scripts/bootstrap, scripts/doctor, requirements/py313.txt)
* bootstrap: render when settings.json is absent (always true on a fresh clone after Step 2); when present, run `render-settings --check` and exit non-zero (not SUCCESS) on failure, re-render only with --force (keeps the non-destructive contract).
* bootstrap creates, only if absent: <home>/logs; the TMPDIR root; `~/.config/claude/protected-runtime.json` with schema_version 1 and the 10 REQUIRED_KEYS as empty lists (this is the missing producer; never overwrites an existing file, so the author file is untouched).
* doctor adds three required checks: every hook command path in settings.json exists; `render-settings --check` passes; protected-runtime.json loads with all REQUIRED_KEYS.
* add requirements/py313.txt (hash-locked) so bootstrap accepts 3.13.

Step 4 — remove author values from shipped code (C1.b/C1.c; effort M; files listed in C1.b/C1.c)
* Author defaults become empty and move to the author overlay env: pretool-bash-safety.sh:317,327,333,334 (and gate the happy-* rules :1776-1784, :1825-1827, :1860-1861 on the configured CLAUDE_PROTECTED_DAEMON_PREFIX so they stay active for the author only); hooks/lib/subagent_restart.py:820; scripts/prune-orphaned-workflow-bookmarks.sh:89 (and derive :90 from the resolved home realpath).
* paseo: scripts/paseo-daemon-ledger.py:133 (accounts from --accounts/overlay, no author default), :1626 (node via PATH lookup), :3010 and scripts/paseo-daemon-timers.py:678 (Path.home()/.paseo/schedules), timers :144 (resolved harness home), :146 (model from overlay); update tests/test_paseo_daemon_ledger.py:4278.
* hooks/lib/checkpoint-core.sh:668,671,782,785: drop the Happy attribution from checkpoint commits (or make the trailer overlay-configurable).
* scripts/install/tmpfiles-claude-scratch.conf:61: delete the retired /dev/shm/claude-tmp rule. Delete stray .claude/tmp-test-writer-gen-l7.py (E1).
* HARNESS-HOME-ASSUMED sites (C1.c table, 26 lines) resolve from their own location / CLAUDE_HOME (claude_home.sh/py already exist); STATE-UNDER-HOME-CLAUDE sites (32 lines) use ${CLAUDE_CONFIG_DIR:-$HOME/.claude} (or the E2 state root when that cluster lands). Prompts: replace `~/.claude/venv` (59 prompt lines) with `$CLAUDE_HOME/venv` (exported by Step 1) — mechanical.

Step 5 — tests and docs (C1.d/C1.e; effort S): tests in the C1.d table derive paths from __file__ / tmp_path and skip cleanly without /dev/shm, /usr/bin/node, /opt/paseo; tests/generated/20260704-225139/ (21 files) go with E1. Update README.md:58-104 (one documented full-install path), :438-445, :471, :510-517, :139, :528, ARCHITECTURE.md:20,28,356, PUBLIC-CORE.md:44-53.

Order: Step 1 -> Step 2 -> Step 3 (each leaves the author machine working: Step 1 changes only the template and the renderer; Step 2 is safe because the on-disk file is unchanged; Step 3 only adds). Step 4/5 are independent and can trail.

Risks: (1) re-rendering changes settings.json bytes -> capability state invalidated (hooks/lib/capability_state.py:330), a fresh `scripts/doctor --strict` handshake is needed; (2) a live session editing settings.json during the migration is overwritten by the render (F3 status quo: do Step 2 in one commit + immediate render); (3) shipping the producer gates in the public template exports their current defects (advisory switches A1, B1 completion-gate) — gate Step 1 on B1 for stop-completion-gate.py; (4) CLI permission accepts written into the generated file must be moved into the overlay or they are lost at the next render (renderer prints them).

## 4. User decisions needed

* U1 — untrack settings.json (generate-then-untrack). PUBLIC-CORE.md:49-53 records it as "not authorized". Recommended: yes; it removes C1.a for every user and makes the template the single source.
* U2 — public permission posture for the 23 conflicting entries: live deny (rm -rf, docker rm, kubectl apply/create/delete, npm/yarn publish, Edit(.claude/**)) vs template ask; live allow (curl, wget, docker run/exec, Edit(**/package.json|pyproject.toml|requirements.txt|go.mod|Cargo.toml)) vs template ask. Recommended: ship live deny set + template ask set; author allow entries go to the overlay.
* U3 — overlay name/location: `<harness>/settings.machine.json` (gitignored, derived from the install location; recommended) vs `~/.config/claude-harness/local.json`.
* U4 — author-specific features stay (no retirement) but all author values (3 paseo accounts, happy-* daemon/container names, /var/lib/claude-accounts, Happy commit attribution, /root/bin grant helper) move into the overlay so shipped defaults are empty. Recommended: yes.
* U5 — which path README documents as the full install (clone + bootstrap) vs the installer core profile (guardrails only). Recommended: document both explicitly; no code change.

## 5. Cross-references

* A1: CLAUDE_OBLIGATION_* switches must be added to settings.template.json (Step 1), never to the live file only, or drift recurs. A1 depends on C2 Step 1.
* B1: stop-completion-gate.py is live-only today; adding it to the public template exports B1 (Step 1 hold).
* B4/B3: stop-do-report-gate.py and stop-workflow-coordinator.py are live-only; their fixes reach users only after Step 1.
* C3: author names/email in tests and docs (TEST-DATA rows) and NESTED-REPO.md are C3; this file lists them but proposes no C3 action.
* C4: TEST-BREAK/TEST-MACHINE rows and the 8 tests reading the live settings.json; py313 lockfile.
* D1/E1: legacy installers (4), .claude/tmp-test-writer-gen-l7.py, tests/generated/20260704-225139/.
* D3: settings vs template is the D3 "two truths" instance resolved by Step 2.
* D4: README/ARCHITECTURE counts, CLAUDE.md stop-cleanup-allowlist claim.
* E2: STATE-UNDER-HOME-CLAUDE rows belong to a separate state root once E2 lands.
