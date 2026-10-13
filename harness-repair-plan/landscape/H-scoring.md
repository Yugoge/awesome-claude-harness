# H — Agent scoring system: end-to-end study and the D9 native-question rating design

Repo: /home/user/awesome-claude-harness @ 09ab15b (on the user's machine this tree IS ~/.claude). CLI 2.1.295.
Method: static read of every producer/consumer, plus runs of the scripts and the orchestrator gate in a
scratch copy: $SCRATCH/sgsc-work/H-scoring/
(HOME, TMPDIR, CLAUDE_PROJECT_DIR, CLAUDE_STATE_DIR all pointed into that directory; PYTHONDONTWRITEBYTECODE=1).
Nothing in the repo or /root/.claude was modified. The user's live score store could not be inspected: the
container's /root/.claude was not readable to this lane, and the user's own machine is out of reach.
AskUserQuestion behaviour was read statically from the 2.1.295 binary (/opt/claude-code/bin/claude, string
search only, CLI not run) and the SDK types (/opt/node22/lib/node_modules/@anthropic-ai/claude-code/sdk-tools.d.ts, v2.1.42).

## 1. Verdict in one paragraph

The scoring system ("Mascot scoring", spec-20260518-225715 §5.1, the spec itself is untracked) has one store
(an append-only JSONL), one writer script, one reader script, one decision helper, and about 25 KB of
prompt prose that tells the orchestrator when to call them. The scripts work in isolation. End to end the
system does not work reliably and nothing measures whether it helps:
- the documented /close Step 3 sequence hits the orchestrator gate's 5-consecutive-Bash cap, so the user's
  rating is recorded for ba but blocked for dev and qa (simulated, §3.4);
- the rating is asked in the Happy-client `<options>` XML format, which the stock Claude Code TUI shows as
  literal text, and nothing captures the reply except the orchestrator reading the next user turn;
- the four-field "INJECTION_PROOF" echo that is supposed to prove agents act on their rank has no consumer
  (schemas allow extra properties; no hook reads the fields) and once polluted context.json (backlog #90);
- both shell tests are outside CI, and one has been broken since the M3 precondition landed;
- automatic events are either zero-delta noise (qa_first_pass, qa_second_pass) or, under D2/D7, constant
  (close_success_* fires on every cycle because close always completes) or unreachable (close_fail_*).
The only signal that carries information is the user's rating.

## 2. Component map (producers, consumers, file:line)

### 2.1 Store
| Item | Where | Notes |
|---|---|---|
| Score log | `${HOME}/.claude/logs/lifecycle.jsonl` (scripts/score-update.sh:40, scripts/score-inject.sh:15, scripts/lifecycle-baseline-import.sh:15) | On the user's machine ~/.claude is this repo, so the runtime log sits inside the harness source tree. It is ignored by .gitignore:46 (`logs/*`) and :180 (`logs/`), and has never been committed (`git log --all -- logs/lifecycle.jsonl` is empty). |
| Lock | `${LIFECYCLE_FILE}.lock`, created by the writer (score-update.sh:207-214, `flock -w 10` exclusive) and also by the reader (score-inject.sh:63-68, `flock -s`) | The lock lives in the same ignored directory. |
| Legacy store | `~/.claude/agent-scores.json(.lock)`, ignored at .gitignore:100-101 | Read only by the finished one-time migration scripts/lifecycle-baseline-import.sh:16,77-127. score-update.sh:104-105 and score-inject.sh:29-30 accept and ignore `--scores-file`. |
| False "tracked" claims | .gitignore:47 ("PERMITTED DELIVERY PATH: logs/lifecycle.jsonl is the R9 in-repo lifecycle log", with no `!` negation); hooks/doc_sync/regen_readme.py:52 and hooks/doc_sync/tree.py:28 ("lifecycle.jsonl is tracked in git") | All three are stale. A deleted generated test, test_AC9_ac9_lifecycle_jsonl_tracked_in_git.py, shows the log was once meant to be tracked in the public repo. |
| Row shape | score-update.sh:399-409: {ts (seconds), agent, event, prev_score, new_score, delta, unclamped_score, actor:"orchestrator", reason} | `reason` is the caller's `--note`, which in practice is the task id (close.md:830-832, 887-889; dev.md:1097-1101). `actor` is always "orchestrator", even for user ratings (score-update.sh:407). |
| Scope | One global file for all projects | A rating in project A changes the rank that agents see in project B. |

### 2.2 Producer: scripts/score-update.sh (the only writer)
- Modes: `--event`, `--delta`, `--undo` (score-update.sh:121-155). `manual_reversal` is internal only (:113-119, :286-292).
- EVENT_DELTAS (:241-256):

| event | dev | ba | qa | issued by | where |
|---|---|---|---|---|---|
| close_success_qa_pass | +2 | +1 | +1 | orchestrator, /close Step 3 | close.md:827-835 |
| close_success_qa_fail_fixed | +2 | +1 | +1 | same; identical deltas, so close.md:807-811's qa_ever_rejected computation changes only the label | close.md:837 |
| close_fail_qa_pass | -10 | -5 | -12 | orchestrator direct, CLOSE: NO only; unreachable per close.md:801 | close.md:839-841 |
| close_fail_qa_fail | -10 | -5 | 0 | same | same |
| qa_first_pass | 0 | 0 | 0 | orchestrator, /dev Step 14 | dev.md:1097 |
| qa_second_pass | 0 | 0 | 0 | same | dev.md:1098 |
| qa_reject_dev | -12 | 0 | 0 | same, by primary_cause | dev.md:1100 |
| qa_reject_ba | -5 | -8 | 0 | same | dev.md:1101 |
| user_rating_5 | +1 | 0 | 0 | orchestrator after the user's reply to /close | close.md:886-889 |
| user_rating_4 | -5 | -3 | -3 | same | same |
| user_rating_3 | -15 | -8 | -8 | same | same |
| user_rating_2 | -25 | -12 | -12 | same | same |
| user_rating_1 | -40 | -20 | -20 | same | same |

- No lower bound, upper clamp 100 (:392-395). Maximum dev gain per cycle is +3 (close +2, rating 5 +1); one qa_reject_dev costs 4 perfect cycles.
- CANONICAL_AGENTS (:258-265) has 21 names. Only dev, ba and qa have deltas; any other agent gets 0-delta rows (verified: `architect user_rating_1` appends delta 0). test-writer is rejected.
- M3 precondition (:166-204): close_success_* needs `--note` = close-report stem, and the report's last line must classify as yes and not FORCED; decided by close-scoring-decide.py. **user_rating_* has no precondition**: any note, a nonexistent task id or no note at all is accepted, and the same task can be rated twice (verified, §3.2).
- Venv coupling: the Python is stdlib-only, yet every path sources `~/.claude/venv/bin/activate` (:193, :198, :199, :220). Without a venv it exits 1 (verified).
- CAS `--expected-prev-score` (:335-348) has no caller. `--undo` matches (agent, ts) at one-second resolution, so a burst is ambiguous: exit 4 with 5 rows in one second (verified).

### 2.3 Decision helper: scripts/close-scoring-decide.py
- Called by close.md:812-816 (orchestrator) and score-update.sh:193 (M3). Output `{"events":[...],"skip_reason":...}` (:19-28, :163-203).
- Its own header (:7-9) says "Tests MUST invoke this helper directly", but no test anywhere invokes it (grep over tests/ and hooks/tests/ finds none; the generated tests that did were deleted, and tests/generated/INDEX.md:172,195,198,220 still lists them).
- Five author-path residue allowlist entries exist only for this file (policies/public-core-residue-allowlist.v1.json:1566-1594).

### 2.4 Consumer: scripts/score-inject.sh (the only reader)
- Called by commands/dev.md only: BA (:424-426, placeholder :464), Dev (:844-846, :876), QA (:1006-1008, :1027). /redev, /dev-command, /dev-overnight, /do, the /close QA and the /commit QA never inject (grep of commands/), although they dispatch the same agents.
- Output: `[Rank: <5 buckets or Disgraced>] [Range: <lo-hi>] Recent events: <last 3 non-baseline events>`, a "punishment" tail, and an INJECTION_PROOF block that demands four JSON fields, including a sha256[:8] the agent must recompute (score-inject.sh:94-109, 135-196).
- Exact score hidden on purpose (:193), but dev.md:1358-1367 tells the orchestrator to print "Old → New" exact scores in the completion report.
- The tail phrase exists in three copies with two wordings: heredoc :50 ("NOTE: ...") and python :115-119 / :187-191. The python copies concatenate sentences with no space, which renders as "...scoring system.5 stars means..." (verified output).
- Recent events show `reason` (= the task id) for negative events only (:172-181), so the agent sees `qa_reject_dev(-12): "20261013-000001"`: a task id, not a reason it can act on. Zero-delta qa_first_pass rows take slots in the 3-event window.
- Missing file or unknown agent: neutral "Skilled Craftsman 41-60" fallback (:40-60, :111-120, :160-163). New installs and new users therefore always see the neutral bucket.
- Store present but no venv: exit 1 with empty stdout (verified). dev.md gives no rule for a failed inject; the agents' fail-safe nulls the four fields (agents/dev.md:510).

### 2.5 Agent-side echo contract (the intended behaviour change)
- agents/ba.md:796-810 (puts the fields into the shared context.json), agents/dev.md:501-515 (dev-report), agents/qa.md:1378-1392 (qa-report). Three hand copies with three variants (landscape/D-duplicates-contradictions.md:277).
- The intent is stated at agents/dev.md:512: "The free-text action proves act, not just read". `score_injection_action` must name "one concrete behavioral adjustment".
- **Nothing measures it.** schemas/dev-report.v2.json:7, qa-report.v2.json:7 and context.v1.json:7 all set additionalProperties:true and none requires the fields. No hook or script reads them; grep finds only score-inject.sh, the tests, and tests/test_ac_deviation_record_chain.py:388,1123, which uses `rank_acknowledged` as an arbitrary extra key. The only verifier, tests/score-inject-contract/runtime-verify.sh, must be run by hand (landscape/C-privacy-tests.md:529). Nothing analyses lifecycle.jsonl against QA outcomes.
- Cost incident: backlog #90 (docs/reference/harness-issues-backlog.md:132). The four fields polluted docs/dev/context-20260919-180650.json and the dev subagent stripped them by hand. ba.md:798 tells BA to write them into context.json, and #90 calls that location a domain violation: the two disagree.
- Stale example: agents/dev.md:197-202 cites "close_success_qa_pass ba +8"; the live value is +1. agents/qa.md:1590 `_primary_cause_doc` describes primary_cause as score attribution.

### 2.6 The /close rating today
- Step 3 order (close.md:791-797): verdict echo, then close_* scoring (:799-845), Session Summary (:847-868), and finally the `<options>` block at the very end of the text message (:870-884): 5 stars ... 1 star, plus "Skip rating".
- Capture (close.md:886-890): "the task-id MUST be retained in the orchestrator's context across the user's response. Parse the selected option text ... runs three score-update.sh calls". **No hook captures the answer**: there is no rating or stars handling in hooks/prompt-workflow.py or any UserPromptSubmit hook (grep). The stock TUI renders `<options>` as literal XML, so the user has to type the option text back. Only the Happy mobile client drew it as buttons; Happy is otherwise retired (tests/generated/20260704-*/test_AC_E2 strip the Happy co-author).
- History: commit a3191dbe (2026-05-20) asked the rating with `AskUserQuestion`. Commit 117e6afd (2026-05-24, "auto-bulk ... update close/commit/push/dev commands") replaced it with `<options>` (`git show 117e6afd -- commands/close.md`, diff lines 132-143). D9 reverts that choice.
- Conditions that contradict each other:
  - close.md:849/:872/:892 skip the summary and rating when `--force` is passed, and :843 says "--force bypasses scoring just as it bypasses QA debate". But close.md:3, :77-94 and :762 make --force a no-op ("FORCE=true carries no further effect beyond the audit-log line", :92). So a no-op flag silently suppresses the rating.
  - close.md:872 lists the YES forms that get a rating and omits "CLOSE: YES - with disclosures"; :849 says "non-forced YES forms".
  - scripts/todo/close.py:27-30,44-51 still builds a separate 2-step `_STEPS_FORCED` list, which close.md:37-39 says no longer exists.
- --auto: per-parent walks run the rating block inside each walk's own Step 3 (close.md:994-998). The D6 overnight end chain would therefore emit one rating prompt per parent with nobody present.
- The rating is never part of the /close todo list (scripts/todo/close.py:21-25 has 3 steps). stop-completion-gate exempts /close and /commit sessions entirely (hooks/stop-completion-gate.py:62-63). Nothing forces the rating to be asked.
- Attribution: every rating goes to ba, dev and qa. A /do-path close (close.md:810) or an overnight cycle penalises BA even when no BA ran, and the same three roles in /dev-command and overnight never saw a score header.
- Re-close: close-report sections are appended on re-close (close.md:775). Each successful re-close re-issues close_success_* and re-asks the rating. score-update has no task-level dedup.

### 2.7 hooks/pretool-orchestrator-prompt-purity.py `<options>` handling
- OPTIONS_XML_PATTERNS (:139-142), header/label (:143-147), block redaction OPTIONS_XML_BLOCK_RE (:168-171, applied :192-194), overnight-only scan (:277-284), remedy (:287-302).
- It only scans `Agent` dispatch prompts (:329-337), and the hook is warn-only (:340-348, always exit 0), although dev-overnight.md:142 says it "rejects". The /close rating block is main-agent text, which no hook can see (dev-overnight.md:142 admits "main-agent text emission is unhookable"). So the category never covered the one place that emits `<options>`.
- The design doc cites this redaction as the precedent for redacting `<obligation>` blocks (docs/reference/close-commit-zero-failure-mechanism-20260928.md:154).

### 2.8 Tests and CI
| Test | Runs in CI? | Result in scratch | Note |
|---|---|---|---|
| tests/score-inject-contract/test-inject-branches.sh | No. CI runs pytest (.github/workflows/baseline.yml:124) and only `bash -n` over shell (:137-145) | 3/3 pass with a venv; without one the populated branch fails ("missing required token: INJECTION_PROOF:"), and the malformed branch passes for the wrong reason (exit 1 from the missing venv, not from the JSONL) | Usage says `--score-inject <path>` (:5) but the code uses `$1` as the path (:16). |
| tests/score-lifecycle-contract/test-lifecycle-cas.sh | No | **Aborts at test (a), rc=5**: it calls close_success_qa_pass with `--note cas-test-a` and no close-report (:74-75), which the later M3 precondition rejects | Matches landscape/C-privacy-tests.md:531. |
| tests/score-inject-contract/runtime-verify.sh | No (manual tool) | n/a | Needs a captured QA report. |
| close-scoring-decide.py | no test at all | decision matrix verified by hand (§3.3) | |
| tests/TESTING.md:124-126 | | | Documents the three shell tests as current. |

### 2.9 Other score surfaces
- "Mascot" naming: commands/dev.md:424, :844, :1006, :1091, :1358; commands/close.md:799.
- agents/style-inspector.md:339 exempts five Chinese rank labels (见习学徒 ... 宗师级) "surfaced to humans via the AskUserQuestion mascot-greeting flow". That flow does not exist anywhere in the repo, and the live labels are English (score-inject.sh:77-83). The exemption is dangling.
- settings.json:51-52 allow `/root/.claude/scripts/score-*.sh` (redundant with `Bash(bash:*)` at :56). settings.template.json:173-175 and :178-180 have relative and {{CLAUDE_HOME}} variants.
- Not part of agent scoring (task metrics, out of scope): BA clarity score (agents/ba.md:96-106), PM RICE (agents/pm.md:795-802), skills/ui-beauty-score.

## 3. What the scripts actually do (scratch runs)

3.1 Fresh store: `score-inject.sh --agent dev` prints the neutral header, 1,185 bytes / 161 words, about 300 tokens (scratch file inject-fresh.txt).

3.2 Lifecycle run (all rc=0 unless noted):
```
dev qa_reject_dev                      50->38
dev close_success_qa_fail_fixed (no report)   rc=5 "close-report missing"
decide --qa-ever-rejected true          {"events":["close_success_qa_fail_fixed"],"skip_reason":null}
dev/ba/qa close_success_qa_fail_fixed   38->40, 50->51, 50->51
ba/dev/qa user_rating_4                 51->48, 40->35, 51->48
inject dev -> [Rank: Journeyman] [Range: 21-40] Recent events: qa_reject_dev(-12): "20261013-000001", close_success_qa_fail_fixed(+2), user_rating_4(-5): "20261013-000001"
dev user_rating_4 again, same task      35->30   (no dedup)
dev user_rating_5 --note does-not-exist 30->31   (no task check)
dev user_rating_1 (no --note)           31->-9   (no note required)
architect user_rating_1                 50->50 delta 0 (noise row)
dev user_rating_1 x2                    -> -89 "[Rank: Disgraced] [Range: <0]"
dev --undo <ts>                         rc=4 "ambiguous — 5 entries match" (second-resolution ts)
30 parallel writers (qa user_rating_4)  30 rows, prev/new chain consistent, final -40 as expected
no venv: inject rc=1 (empty), update rc=1
```

3.3 close-scoring-decide.py over last lines: `CLOSE: YES`, `... with disclosures: 2 items` and `... codex disabled by user` map to close_success_qa_pass; `CLOSE: YES (FORCED)` gives [] "FORCED"; `CLOSE_FINDINGS: 3 items` gives [] 'no'; `**CLOSE: YES**` gives [] 'unknown'; `CLOSE: NO` gives [] 'no'. This matches close.md:818-823.

3.4 Orchestrator gate replay (hooks/pretool-orchestrator-gate.py copied to scratch, state in scratch). Sequence: Agent (QA debate), Bash decide, 3×Bash close_success, Skill (spec-update), AskUserQuestion, 3×Bash user_rating. Result: the 2nd and 3rd rating calls are **BLOCKED rc=2 "Bash used consecutively beyond limit (6/5)"**. Cause: BASH_MAX_CONSECUTIVE=5 (:64), and the streak is cleared only by an Agent dispatch (:11-21, :222-239). Neither a Skill, an AskUserQuestion nor a new user turn clears it, and the only other reset writer, hooks/stop-cleanup-allowlist.sh:40, is not registered. Unless the user has granted /do, the user's rating lands for ba only.

## 4. Assessment

- **Works end to end?** No (3.4). Even with /do consent it depends on the orchestrator remembering the task id across a turn and parsing typed text. Nothing enforces that the rating is asked (2.6). Automatic events are partly noise (2 zero-delta calls per first-pass cycle) and partly unreachable.
- **Producer/consumer completeness.** The writer has six caller sites, all orchestrator prose (dev.md:1097-1101; close.md:827-841, 886-889), and the rating rows have no code-level producer. The reader has three caller sites, all in dev.md. The agents' echo output has no consumer. The dev.md:1104 `score_updates` array and the dev.md:1358-1367 table have no consumer. qa_ever_rejected (close.md:807-811) has no effect on the score.
- **Prompt-token cost per singular /dev + /close cycle (bytes/4 estimate).** Injected header about 1.2-1.3 KB × 3 dispatches, about 900-1,000 tokens. Echo contract about 1.6 KB in every BA/dev/QA dispatch of every pipeline, including the /close and /commit QA where it never applies: about 400 tokens each, about 1,200 for one cycle. Orchestrator prose: dev.md scoring 3,832 B and close.md scoring 4,490 B + rating 2,139 B, about 2,600 tokens, paid twice while prompt-workflow re-sends command bodies (PLAN Metrics: /close 119,653 B, /dev 108,226 B duplicated). Tool calls: 3 inject + 2-3 update in /dev, plus 7 Bash in /close, plus one extra sha256 tool call per scored dispatch. Total: roughly 5-6k tokens and about 12 extra tool calls per cycle; fan-out multiplies the dispatch share by N lanes.
- **Concurrency.** Sound: one exclusive flock for writers and a shared one for readers (verified with 30 parallel writers). The weak points are `--undo` at one-second resolution and full-file reads O(n) per call (negligible).
- **Portability and privacy.**
  - The store is runtime state inside the harness tree on the user's machine (gitignored, never committed), hard-wired to `${HOME}/.claude` and ignoring CLAUDE_CONFIG_DIR (landscape/C-portability-settings.md:405-409).
  - venv (:70/:193-220), flock and sha256sum are required; macOS ships no flock.
  - The log is global across projects, so project A's rating changes project B's prompts.
  - The log holds task ids only, low sensitivity. If free-text feedback is ever stored, it must stay out of any tracked path.
- **Value vs cost.**
  - Value: zero measured. Subagents are stateless LLMs; the only lever is prompt pressure ("punishment far exceeding any other event, and is irreversible", score-inject.sh:50/:118/:190), and threat framing is a known risk for over-claiming and gaming.
  - Incentives point the wrong way under D2, where QA fail is a process step. dev loses 12 points per QA iteration. QA loses 12 only when it passes and close later fails, and never loses points for rejecting. Scores drift into "Disgraced" and saturate: at one rejection per cycle dev nets -9/cycle, which reaches the Disgraced bucket in about 10 cycles. The rank then carries no information.
  - Cost: the token and tool load above, broken tests, a dangling style exemption, backlog #90 pollution, and five residue-allowlist entries.
  - Under D7 (close always completes), close_success_* is a constant +4 per cycle and close_fail_* cannot fire. The one informative signal left is the user's rating.

## 5. D9 design: native-question rating

### 5.1 The question (fits AskUserQuestion's limits: 1-4 questions, 2-4 options, header at most 12 characters)
Issued by the main agent in the same assistant message that carries the verdict echo and Session Summary, as the last action of /close:
```json
{
  "questions": [{
    "question": "How well did cycle <task-id> meet what you asked for?",
    "header": "Rating",
    "multiSelect": false,
    "options": [
      {"label": "5 - Fully met",   "description": "Everything you asked for, nothing missing."},
      {"label": "4 - Minor gaps",  "description": "Small gaps or friction; usable as delivered."},
      {"label": "3 - Major gaps",  "description": "Usable only after notable follow-up work."},
      {"label": "1-2 - Not met",   "description": "Missed the request. Recorded as the lowest rating."}
    ]
  }],
  "metadata": {"source": "close-rating:<task-id>"}
}
```
- The native dialog always adds a free-text box and a Skip control. The 2.1.295 binary says "AskUserQuestion always includes a Skip button and a free-text input box ... do not include `None` or `Other`", and also that it has no pre-selected default. So the old "Skip rating" option is dropped.
- Five star levels do not fit four options. Recommended: bucket 1-2. Alternatives are in §9 Q3; one is a `kind:"number"` 1-5 slider that exists in the 2.1.295 schema behind a feature gate (`_we()`/`k_o()`, unverified, not relied on).
- `metadata.source` is a schema field that is "Not displayed to user" (sdk-tools.d.ts ~:1545-1551; also present in the 2.1.295 input schema). It is the machine routing key, so nobody has to parse prose.

### 5.2 Answer flow to the single score producer
1. The CLI writes the tool result. 2.1.295 output schema: `{questions, answers: {question text -> label}, response?: free text, annotations?, afkTimeoutMs?}`. The transcript text is "Your questions have been answered: ...", "The user answered: ...", "The user did not answer the questions." or the AFK form. A user rejection writes "User declined to answer questions".
2. A **PostToolUse hook, matcher `AskUserQuestion`** (new `hooks/posttool-close-rating.py`; the source tag and label map live in a small `hooks/lib/close_rating.py`) does the following:
   - exit 0 unless the main agent (no agent_id) asked and `tool_input.metadata.source` matches `^close-rating:[A-Za-z0-9][A-Za-z0-9_-]{2,80}$`;
   - no rating row when `afkTimeoutMs` is set, the call was rejected, `answers` is missing, or the answer is not an exact label (free text and Skip land here);
   - otherwise call the producer once. The hook is not a tool call, so the orchestrator's Bash-streak cap (§3.4) cannot block it.
3. **Producer** (one writer, under the existing flock):
   - S-A (keep everything): score-update.sh `--event user_rating_N --note <task-id>` for ba, dev, qa, plus a dedup that rejects a second user_rating_* for the same (agent, task-id) with no append.
   - S-B (recommended): the hook library appends one row `{ts, task_id, rating, tool_use_id}` and dedups by task_id (first answer wins).
4. The orchestrator no longer parses answers or runs rating commands. close.md:886-890 is deleted, which keeps D8 intact: the orchestrator writes no producer artifact.
5. Guard against a model pre-filling `answers` in the tool input (the input schema has an `answers` field "collected by the permission component"). Measure in the armed sandbox whether the CLI overwrites model-supplied answers. If it does not, the same hook file registered as PreToolUse/AskUserQuestion denies a close-rating call that already carries `answers` or `annotations`. Per D10, add this guard only if the measurement shows it is needed.

### 5.3 Interaction with the /close stop gate (D4)
- Recommended: the rating is **Step 4 of the /close todo list** ("Step 4: Ask the user to rate this cycle"), added by scripts/todo/close.py only for interactive single closes (not `--auto`).
- Its completion artifact is **"asked", not "answered"**: a CLI-written transcript record. That means an assistant `AskUserQuestion` tool_use whose `input.metadata.source == "close-rating:<task-id>"`, a matching tool_result (any content, including is_error, AFK, Skip or decline), and both after the latest landed `CLOSE: YES*` section.
- The predicate is a pure function of `transcript_path`, the harness-owned append-only channel of design §1.1(b), so it adds zero mutable files (C1). It lives in hooks/lib/close_rating.py and the D4 Stop gate imports it.
- Why not "answered":
  - rating is optional for the human;
  - making the gate wait for an answer would turn an opinion into a blocking human-in-the-loop step (design C5) and could hold the session open with no exit;
  - Skip, Esc, AFK and permission deny must all be legitimate outcomes.
- The step can always be satisfied by one tool call in the same turn, so it needs no retry bound and no release token, consistent with D4.
- The rating question is **not** the D3 "needs your decision" pause. It is the final step of a complete cycle and leaves nothing incomplete. It must come after the close-report and temp update so that a stop while the dialog is open never strands Step 3.
- A score row is never a gate input. Consumers do not re-check producer output; the producer (hook) is the correctness point.

### 5.4 Unattended sessions (nobody answers)
- **Overnight end chain (D6: `/close --auto` → `/commit --auto` → `/merge` → `/push`):**
  - `--auto` never asks: close.py omits Step 4, and close.md:994-998 is rewritten to "no rating in --auto";
  - the overnight summary lists the unrated parents;
  - no rating is ever synthesised;
  - optional deferred rating: §9 Q5.
- **Paseo-managed sessions:** the controller drives `/close` with a bare command (commands/paseo-daemon.md:59-63) and must never answer a rating, because an agent-authored rating is fabricated. Recommended: rely on the CLI's native AFK auto-resolve. The 2.1.295 binary has an `askUserQuestionTimeout` setting (`function Udt(){return TP("askUserQuestionTimeout")[0]}`) and `afkTimeoutMs` in the result. The managed-session settings enable it, AFK counts as "asked, no rating", and the harness adds zero code. Verify the setting name and semantics in the armed sandbox. Fallback, if a flag is preferred: §9 Q6.
- **Headless or auto mode:**
  - auto mode may route AskUserQuestion through the auto-mode classifier (`CLAUDE_CODE_AUTO_MODE_CLASSIFY_ASK_USER_QUESTION` / setting `classifyAskUserQuestion`; binary function `Ofn`). It falls back to the dialog when the classifier is unavailable or the transcript is too long;
  - headless paths (`shouldAvoidPermissionPrompts`) avoid prompts;
  - whatever the outcome (deny, error, AFK), the tool_result exists and the gate passes. Only an exact label answer writes a row;
  - acceptance test: a close-rating question in auto mode must reach the human dialog. If the classifier can resolve it, ship `classifyAskUserQuestion: false` in the template.
- **Overnight orchestrator questions in general:** AskUserQuestion is hookable, unlike `<options>` text. If the overnight lane wants it, Clause A/C autonomy (dev-overnight.md:117) becomes enforceable with a PreToolUse deny on AskUserQuestion while `overnight-state-*.json` is live. That is out of D9 scope and listed for the overnight lane.

### 5.5 Scope options (product decision; see §9 Q1)
- **S-A (minimal):** swap the question and add the hook producer, the dedup and the Step 4 gate. Fix the venv coupling, test-lifecycle-cas and the stale --force conditions. Keep injection and automatic events. About +120 code lines; prose shrinks a little.
- **S-B (recommended):** S-A plus delete prompt injection (score-inject.sh, the three DEV/BA/QA_SCORE_HEADER blocks, the three agent echo contracts, runtime-verify.sh) and every automatic event (close_*, qa_*: close-scoring-decide.py, M3, dev.md Step 14 scoring, the dev.md "Mascot Score Changes" table). The rating log becomes the whole system: human feedback for self-review, with nothing fed back into prompts. About -1,000 code lines (score-update.sh 431 + score-inject.sh 204 + close-scoring-decide.py 252 + lifecycle-baseline-import.sh 146 + shell tests about 470), about -25 KB of prompt prose, and about 5-6k tokens and about 12 tool calls saved per cycle. Adds about 80 lines for the hook and library plus pytest.
- **S-C (maximum removal):** delete scoring entirely, including the rating question. No Step 4, no hook. Removes the most, but the user just asked to keep the rating, so it is offered for completeness only.

## 6. Findings (ids H-S1..)
See the StructuredOutput findings list for severity. They all derive from §2-§4 above.

## 7. Change list (S-B; S-A keeps the rows marked *)
| File | Locations | Change |
|---|---|---|
| commands/close.md* | :797, :867, :870-892 | Replace the `<options>` block and post-option contract with Step 4: one AskUserQuestion of the §5.1 shape, `metadata.source=close-rating:<task-id>`. Ask after any landed `CLOSE: YES*` (all suffix forms, --force irrelevant). The orchestrator records nothing. |
| commands/close.md* | :843, :849, :872, :892 | Delete the --force/FORCED skip conditions (--force is a no-op, :92). |
| commands/close.md* | :994-998 | --auto never asks a rating; the batch summary lists the unrated parents. |
| commands/close.md | :799-845 | Delete close_* scoring (helper, M3 narrative, qa_ever_rejected). |
| scripts/todo/close.py* | :21-30, :44-51 | Add Step 4 (`user_question: close-rating`) unless `--auto`; delete the stale `_STEPS_FORCED`. |
| hooks/posttool-close-rating.py* (new), hooks/lib/close_rating.py* (new) | | PostToolUse AskUserQuestion producer (§5.2); shared `rating_asked(transcript, task_id)` predicate for the D4 Stop gate; optional PreToolUse pre-fill guard, only if the measurement requires it. |
| settings.template.json*, settings.json* | hooks.PostToolUse | Register the matcher `AskUserQuestion` (template first; settings.json is rendered per P6). |
| scripts/score-update.sh | whole file | S-A: rating dedup, drop the venv sourcing (stdlib only), drop --undo/--delta (orchestrator no longer writes). S-B: delete; the hook library is the single writer. |
| scripts/score-inject.sh, scripts/close-scoring-decide.py, scripts/lifecycle-baseline-import.sh | whole files | Delete (S-B). |
| commands/dev.md | :424-426, :464, :844-846, :876, :1006-1008, :1027 (placeholder), :1091-1104, :1358-1367 | Delete injection, Step 14 scoring and the score table. |
| agents/ba.md, agents/dev.md, agents/qa.md | ba :796-810; dev :501-515, :197-202; qa :1378-1392, :1590 | Delete the echo contracts. Fix the stale blast-radius example. Reword `_primary_cause_doc` (primary_cause routes the fix, not points). |
| agents/style-inspector.md | :339 | Delete the dangling mascot exemption. |
| hooks/pretool-orchestrator-prompt-purity.py | :20, :133-147, :163-171, :192-194, :277-284, :287-302 | Delete the OPTIONS_XML category and redaction (no `<options>` producer remains). |
| commands/dev-overnight.md | :117, :142 | Replace "`<options>` XML" wording with "no questions to the user (AskUserQuestion) in autonomous mode"; drop the false "rejects" claim. |
| tests/score-inject-contract/*, tests/score-lifecycle-contract/* | all | Delete; replaced by hooks/tests/test_close_rating.py (pytest, in CI). |
| tests/TESTING.md, tests/generated/INDEX.md, tests/INDEX.md, scripts/README.md, scripts/INDEX.md, INDEX.md | TESTING :124-126; generated INDEX :172, :195, :198, :220; others regenerate | Remove the stale rows. |
| .gitignore; hooks/doc_sync/regen_readme.py; hooks/doc_sync/tree.py | .gitignore:47; regen :50-53; tree :26-29 | Remove the false "tracked in git" comments. Keep the ignore and skip of lifecycle.jsonl while the log exists; drop the agent-scores entries from the doc_sync skip lists. |
| settings.json, settings.template.json | :51-52; template :173-175, :178-180 | Delete the score-script allow entries. |
| policies/public-core-residue-allowlist.v1.json | :1566-1594 | Drop the five entries with the file. |

## 8. Acceptance tests (armed sandbox + pytest)
1. Interactive /close reaches CLOSE: YES. The transcript shows exactly one AskUserQuestion with header "Rating", 4 options, multiSelect false and metadata.source `close-rating:<task-id>`, and no `<options>` text in any assistant message.
2. Answer "4 - Minor gaps": exactly one rating record for the task (S-B), or 3 rows user_rating_4 (S-A). The orchestrator made no score Bash calls.
3. Skip, free text "great", Esc/decline, AFK auto-resolve (afkTimeoutMs set) and permission deny each write zero rows. The D4 Stop gate allows the stop in every case.
4. The orchestrator ends the turn after Step 3 without asking: the D4 Stop gate blocks and names Step 4. After one AskUserQuestion it allows.
5. `/close --auto` over 2 parents: no AskUserQuestion in the transcript, the batch summary lists 2 unrated parents, and the gate allows.
6. Re-close of an already-rated task: no second record (dedup at the producer).
7. AskUserQuestion with a source not matching close-rating (or from a subagent): the hook is a no-op.
8. Model-prefilled `answers` in tool_input: the CLI behaviour is measured. If answers pass through un-asked, the PreToolUse guard denies, and the test asserts the deny.
9. Auto mode: a close-rating question reaches the human dialog (the classifier does not resolve it), or the template ships `classifyAskUserQuestion:false` and the test asserts that.
10. (S-B) grep finds no score-inject, INJECTION_PROOF, rank_acknowledged, `<options>` or close-scoring-decide across commands/, agents/, hooks/, scripts/ and settings; the CI pytest suite includes test_close_rating.py.
11. Hook under concurrency: 20 parallel hook invocations for 20 distinct tasks give 20 records with no interleaving (flock).
12. No venv present: the hook still records (stdlib only).

## 9. Open questions for the user
1. Keep agent scoring at all? Rec **S-B**: keep only the user rating as a recorded human signal; delete prompt injection and automatic events (D2/D7 make them constant or noise, and nothing measures any effect).
2. What should the rating influence? Rec: nothing automatic. It is a log for the user's own review, optionally summarised in /retro. If the user wants feedback into agents, it should go through prompt or rule fixes a human writes, not rank injection.
3. Five stars with four options? Rec: 5 / 4 / 3 / "1-2". Alternatives: a two-step question ("2 or lower" opens a 2-option follow-up), or a 1-5 number slider if the live CLI exposes `kind:"number"` (flag-gated in 2.1.295).
4. Per-role attribution (ba/dev/qa) or per-cycle? Rec: per cycle {task_id, rating}, since /do and overnight cycles have no BA and roles are not separable from one rating.
5. Overnight parents closed by `--auto`: rec no rating. The alternative is one deferred AskUserQuestion after `/push` at the end of the D6 chain (up to 4 parents per call).
6. Paseo-managed sessions: rec the native AFK timeout (`askUserQuestionTimeout`) in managed-session settings. The alternative is an explicit flag that omits Step 4.
7. Free text typed in the native "Other" box: rec not scored and not stored (privacy, fewer rules). The alternative is to store it as an unscored comment in the local log.
8. Re-close of a rated task: rec first rating wins, with no re-ask needed. The alternative is that the latest rating replaces the first.
9. Should the rating be part of the /close stop gate? Rec yes, as "asked", not "answered" (§5.3).
10. Existing local store (~/.claude/logs/lifecycle.jsonl, ~/.claude/agent-scores.json): keep as history, archive, or delete (a human step)? Rec: keep lifecycle.jsonl read-only as history; delete agent-scores.json.
