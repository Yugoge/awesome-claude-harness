# Completeness critique of AUDIT.md

Completeness critique of harness-repair-plan/overblock/AUDIT.md

Scope: I read the code read-only at a21dcbf9, the report's baseline. Probes ran only on copies in the scratchpad, and I deleted those copies afterwards. The repo was not modified. Lines below are at a21dcbf9 unless marked HEAD. HEAD is 87731833 (claude/eager-allen-gf06hy).

## A. Not covered, with a repro

**A1. UserPromptSubmit: `--spec` in prose blocks the whole prompt (CONFIRMED, exit 2).**
The report never mentions UserPromptSubmit.
- Code: `hooks/prompt-workflow.py:359` uses the regex `(?:--|[–—])spec\s+(\S+)`. That text goes to `decide_spec_path` at `:1497-1512`, which calls `SystemExit(2)` at `:1511`. The callers are `:1556` (/dev, /redev, /dev-command) and `:1680` (/dev-overnight).
- Repro on a scratch copy, both rc=2 with "Spec: <proj>/section (unresolved)" or ".../parsing (unresolved)":
  - prompt `/dev align the docs with the API—spec section first` (em-dash)
  - prompt `/dev add tests for --spec parsing`
- Must still block: `/dev x --spec missing.md`.

**A2. Unbypassable bash-safety block when the protected-runtime file is schema-incomplete (CONFIRMED). The report lists it in §7 as "no false positive" and gives it no lane.**
- Code: `hooks/lib/runtime_guard/config.py:50-71` returns None when `schema_version` is not 1 or any REQUIRED_KEYS list is missing. `hooks/lib/runtime_guard/_core.py:4600` then takes `_step1_indeterminate`.
- `scripts/bootstrap:394-396` exits as soon as the file exists and never repairs it, so a file that drifts on upgrade stays broken.
- Repro: `CLAUDE_PROTECTED_RUNTIME_FILE=<scratch>/pr.json` containing `{"schema_version":1}`.
  - Bash `node --version` and `npm test` give rc=2 with "BLOCK STEP1: indeterminate policy ... unbypassable (it runs before /do and /allow)".
  - `ls` passes.

**A3. A /spec span left unfinished blocks almost every Agent dispatch.**
- Code:
  - `hooks/pretool-spec-block-foreground-agent.py:32-40` and `:65-77`, exit at `:107`. It has no /do or /allow exemption.
  - Combined with `hooks/pretool-block-background-tasks.py:91-101`, whose only background exception is Explore.
  - The span outlives plain prompts: `hooks/stop-command-gate.py:12` says "a plain prompt continues it".
- Input: type `/spec`, leave step 1 in_progress, then a plain prompt, then `Agent{subagent_type:'general-purpose', run_in_background:false, prompt:'summarize README.md'}`. Expect exit 2. The background form is refused as well.
- WF-ABANDONED-SPAN/L39 only covers workflow-gate. The Stop-side effect of an abandoned /dev or /test span is not evaluated either.

**A4. /do turn: every Agent dispatch is blocked, including read-only ones.**
- Code: `hooks/pretool-do-block-subagents.py:117`.
- The stated reason is a dev-report filename collision, which only writing roles can cause. §7 records this hook as "only under /do" with no false positive.
- Input: in a /do turn, `Agent{subagent_type:'Explore', run_in_background:false, prompt:'list files under docs/'}`.

**A5. L46/F05 rationale is wrong for roles without Edit.**
- L46 says "Edit is always available, so low priority". In `policies/tool-policy.v1.json` these roles have Write but no Edit/MultiEdit: architect (`:223`), product-owner (`:256`), changelog-analyst (`:638`), push-analyst (`:666`), merge-analyst (`:694`), graphify (`:743`), and user.
- For them `hooks/lib/write_gate/overwrite.py:135-144` makes a second Write to their own artifact a dead end. `hooks/posttool-allowlist-consume.py:337-340` already notes "the role has no Edit".
- Input: architect subagent Writes `docs/dev/arch-probe.md`, Writes it again, then Edits it.

**A6. Stop/SubagentStop and the /close, /commit, /merge, /push, /dev-overnight spans were not probed.** These are the gates CLAUDE.md names for command completion.
- **R7 text-question gate:** `hooks/stop-command-gate.py:782-788` and `hooks/lib/requirement_round.py:362-365`. Any /spec or /dev-family span blocks a turn whose last line ends in "?", even a recorded question.
  - Input: a Stop payload in a /spec span with `last_assistant_message` = "Spec written.\nOpen questions recorded in section 4: Should retries be capped?"
- **Command predicates:** p_close, p_commit, p_merge and p_push (HEAD `hooks/stop-command-gate.py:440/521/611/671`) were never exercised.
  - Input: `/push` with the remote unreachable, or the owner declining in AskUserQuestion, then end the turn.
- **SubagentStop compile check:** `hooks/subagentstop-artifact-contract-enforce.py:397-425` blocks a dev that writes a deliberately invalid fixture under the harness home's hooks/ or scripts/.
  - Input: dev writes `hooks/tests/fixtures/bad_syntax.py` containing `def f(:`.
  - No such file exists today (0 non-compiling files), so this is low severity.
- **Overnight-only gates:** none were run inside an open overnight window, and the report contains the string "dev-overnight" zero times.
  - `hooks/pretool-subagent-enforce.py:278-298` keys on an overnight state record existing (`hooks/lib/contract_runtime.py:101-109`), not on the window being live.
  - Input: in a session that already ran /dev-overnight and whose window has ended, type `/dev x`, mark a step in_progress, dispatch `Agent{subagent_type:'ba'}`, and check for "CONTRACT BLOCK".
  - Not yet probed: `hooks/posttool-overnight-file-check.py` (a PostToolUse exit 2 via `hooks/posttool-dispatch-record.py:41`) and the AskUserQuestion deny at `hooks/pretool-overnight-hook-guard.py:2451`.

**A7. Obligation clock bound not checked.**
- `hooks/lib/obligation.py:216` sets `DISPATCH_CLOCK_BOUND_SECONDS=300`, enforced by `hooks/pretool-obligation-gate.py`.
- Input: re-send a /dev BA dispatch verbatim after an AskUserQuestion pause longer than 5 minutes.
- Cost is one retry. §7 lists only R17/R5.

## B. Tools with no probe at all

- **NotebookEdit:** only dev has it (`policies/tool-policy.v1.json`). The main agent gets one per turn.
  - Input: qa calls NotebookEdit on `tests/reports/demo.ipynb`; or the main agent calls NotebookEdit twice in one turn.
- **Read size guard on .ipynb:** `hooks/pretool-read-size-guard.py:25-27` exempts only images and PDF.
  - Input: the main agent Reads a 700-line `.ipynb` without `limit`.
- **Grep/Glob tools against Read() deny:** settings.json `:238-245` (at HEAD, `:236-248` per the report). The perm-* findings test Read and Bash grep but not the Grep or Glob tool.
  - Input: `Grep{pattern:'TODO', path:'src/auth/password_reset.py'}`.
- **Agent teams:** settings.json `:23` sets `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, but no hook handles TeamCreate or teammates. Teammate SendMessage falls into `hooks/pretool-block-background-tasks.py:152`. CD-8/T2 only covers a session's own finished subagent.
  - Input: `TeamCreate{team_name:'probe'}`, then `SendMessage{to:'<teammate>', message:'status'}`.
- **MultiEdit, mcp__playwright__* (main agent, one per turn per name), PostToolUseFailure:** not mentioned. Code reading found no deny paths beyond those already covered.

## C. Findings that need more evidence

1. **perm-* findings #117-131:** these rest on CLI-internal permission behaviour: the cd guard triggered by a Read() rule, `Skill(x:*)` prefix matching, and `Bash(*session_dirs.txt*)` mid-pattern matching. The report does not pin a CLI version or name a recording; task-migration.md does use CLI 2.1.326. Name the version and the recording logs, or re-record.
2. **L46/F05 severity** "偶 (occasional), low priority": should be raised for the roles in A5.
3. **§7 "no false positive" entries that are actually blocks:** `:291` protected-runtime-guard (A2) and pretool-do-block-subagents (A4). Both should become findings with lanes.
4. **L39 "Stop gate still requires checklist":** asserted, not evaluated for abandoned spans. Combined with A3, an abandoned /spec, /dev or /test leaves only Read/Grep/Glob (after L39) until the human types another harness command or /stop.
5. **Baseline drift:** the report header pins a21dcbf9, but the clone's HEAD is 87731833. Between them, stop-command-gate.py, pretool-block-background-tasks.py (CD-8/CD-10) and userprompt-restart-authorize.py changed. Line references for CD-8/CD-10 should be re-pinned to HEAD before lanes start.

## Checked and fine

- These hooks have no deny path: runcode-watchdog, attribution-pre, quality-gate, cp-checkin, worktree-guard.
- These files are not wired into any launcher: capability-gate, subagent-code-block, push-analyst-grant-guard, stop-completion/obligation/overnight-timelock/do-report, posttool-todo-count/sequence/push-gate-token-verify.
- The `stop-spec-coverage-enforce.py` phase is an exit-0 stub.
- G6 phantom targets reproduce on the baseline (`sed -n ... user-info.py` gives `y`).
- G1 line numbers and CLAUDE.md `:48-50` and `:83-84` match.
- The G2 claim that no hook gives a subagent its agent_id holds: SubagentStart emits only the score reminder.
