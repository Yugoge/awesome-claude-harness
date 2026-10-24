# Corrections after the owner's rulings of 2026-10-23

## 0. How to apply

- **Owner source.** The owner's message of 2026-10-23T11:59:26Z is record 1921 of the reviewer session transcript (`cur:1921`). It answers the reviewer's P2-P11 summary (`cur:1895`) line by line.
- **Supporting ids.** T0-T5, PC*, ON*, RD*, QP*, SG*, HC*, SF*, CC*, DT* and X* are rows of audit/register.md. Lnn are rows of audit/ledger.md.
- **Where DECISIONS.md and PLAN-v2.md live.** In harness-repair-plan/ on refs/remotes/origin/claude/vibrant-hopper-bazrn8. The p23 copies are byte-identical.
- **Which prompts.** Edit the p23 copies in scratchpad/p23/docs/harness-repair-plan/prompts/. P2 and P3 are the refreshed versions, not yet pushed.
- **Line numbers.** P4, P5 and P6 in p23 carry a "Carry-overs from P1" block, so after P4:385, P5:451 and P6:429 their lines run +7, +19 and +8 against the plan branch. The numbers below are the p23 ones. P9, P10 and P11 are identical in both copies.
- **Row format.** location; anchor (the verbatim opening of the text to change); action; new text.
- **Tags.** [OWNER]: the new text rests on a quoted owner statement. [INFERRED]: the owner's words do not contain it. The phase proves it with the named sandbox experiment (D18) and never asks the owner.
- **Order.** Apply §1, then §2, then §3. Where the owner's wording adds no meaning, it is elided with "…".

## 1. DECISIONS.md

1.1 After line 5 ("…read the decision below instead."), insert:

```
## Owner rulings of 2026-10-23 (latest; they override every decision below, PLAN-v1, PLAN-v2 and every prompt)

Source: the owner's message of 2026-10-23T11:59:26Z answering the reviewer's P2-P11 summary line by line (reviewer
session transcript, record 1921, answering record 1895). Quoted verbatim; "…" marks elided words; English in brackets.

- **D20 Overnight is unattended (supersedes D4b and PLAN-v2 S2).** Answering "…先把那条流水线停放，其他流水线继续跑。结束时间一到再
  一次性问你（D4b）": "不允许，谁说的？overnight就应该是无人值守" [Not allowed. Who said that? Overnight must be unattended.]
  A /dev-overnight session never asks the owner and never waits for him, inside the time-lock window or after
  end_time. Nothing is parked. Every decision a pipeline meets is made inside the session and recorded (decision,
  options, evidence or experiment, chosen option) in the re-dispatch prompt, the cycle log and the overnight summary's
  section "Decisions made without the owner". The family runs to a QA pass and lands through D6. Earlier owner words
  agree: "今晚继续跑，我授权你做任何事情+开启任何新的周期，总之就是不能停" (2026-10-22); "daemon的意义就是无人值守"
  (docs/reference/paseo-daemon-teachings-20260910.md:77 at f8c18c2).
  [INFERRED, no owner words: how a genuine decision is made. Rule: an experiment when one can be run (D18), otherwise
  the question's own `default`. Precedent: the pre-plan Clause A, "do NOT ask the user anything; make decisions
  yourself" (f8c18c2 commands/dev-overnight.md:115). A spec-declared user gate (Clause B) inside /dev-overnight is
  handled the same way and listed first in the summary.]
- **D21 No filename-to-role table, no agent manual (supersedes PLAN-v2's "One owner table, ROLE_BY_ARTIFACT", TC-19,
  TC-20, TC-34 and the owner/fix fields of gaps).** Answering "每个缺口都写明：缺了哪个文件、什么问题、该由哪个角色补、怎么修":
  "？？又开始hardcode了？自己检查我最开始的需求是什么。又开始给agent一个无法对齐无法彻底完全100%执行的说明书？" [Hardcoding again? Check
  what my original requirement was. Again a manual the agent can never align with or execute 100%?] The original
  requirement (2026-10-09; quoted in prompts/P9.md:153-156, prompts/P10.md:102-107): "如何帮助我彻底理清仓库并且彻底清理没用的东西，
  以及彻底保证整个harness彻底完整系统性干净实现目的不多不少地运行" and "我只关心：对外公开可用度+自洽度（不多不少刚刚好每一个harness artifact
  都有生产者和消费者）+整洁清洁度。不要走偏". No table maps file names to roles, in code or in prose. A gap reports facts
  only: the artifact path, the failing check's code and message, the lane. Hooks enforce correctness at the producer
  (G2 returns an artifact to its own producer at that producer's stop), at dispatch (G1) and at the end (the Stop
  gate). An instruction document the agent must follow is not the enforcement.
  [INFERRED; prove by sandbox replay before use: where a role is needed (the D7 re-dispatch, the D8 deny), read it
  from the dispatch record that declared the artifact: the obligation's `role` and `artifacts[].path`
  (hooks/lib/obligation.py find_unresolved_dispatch_obligations :915-1036, resolve_own_obligation :800). For an
  artifact no dispatch has declared yet, read it from the command's canonical todo step (scripts/todo/<command>.py).]
- **D22 /redev is /dev (supersedes the /redev part of D7, TC-17, and the /redev clauses of TC-4, TC-25 and TC-34).**
  "/redev <任务号>根本就不继续跑用的，redev单纯就是省context的时候的dev。和dev一样！谁说的！…" [/redev <task id> is not for continuing
  at all; /redev is simply /dev when saving context. Same as /dev! Who said that!] /redev mints a fresh task id on
  every invocation, exactly as /dev, and every gate treats it exactly as /dev. An interrupted session is resumed with
  /restart ("恢复一个session被截断应该用restart command而不是写字", paseo-daemon-teachings-20260910.md:295).
- **D23 Asking with the question component is the pause (corrects the "nothing pauses" reading of D3 in S1, P3 and
  P5).** Answering "P5：所有受控命令共用一个 Stop 门，agent 没法自己放行？": "但是我是不是说过agent可以给我使用提问的组件询问问题作为暂停方式？"
  [But didn't I say the agent may ask me with the question component as the way to pause?] O19 ("交回一个'需要你决定'的
  问题块 / 这样就可以暂停") stands, and O22 ("提问一定要有solid问题而不是当作逃生窗口") qualifies it. Outside /dev-overnight, an
  agent that needs the owner pauses by asking with AskUserQuestion inside the turn. The question names a real,
  specific decision. Neither asking nor answering releases a gate. No document says "nothing pauses" or "no pause
  form". The owner has not said whether an answer may end the command early, so no such exit is added.
- **D24 Producer and consumer per artifact are the first requirement.** "…最关心的artifact生产者消费者问题，有一点提及吗？没有，…这都是
  在干啥？" [The artifact producer/consumer problem I care about most: is it mentioned at all? No… what is all this
  doing?] Read with O4/O6 (2026-10-09, above) and O10/O12 ("核心架构：每个产物只有一个生产者，正确性在生产者那一端由 hook 保证，消费者只信
  一个结论"). Every harness artifact has exactly one producer and at least one consumer, and its consumers trust one
  conclusion. Every phase PR carries a table: artifact / producers before → after / deciding consumers before → after
  / proof (a grep for writers and readers, plus a sandbox write trace). An artifact that is written and never read is
  deleted at its producer. An artifact that is read and never written loses its reading branch.
```

1.2 **Lines 40-45 (D4b).** Anchor: `- **D4b Overnight is unattended.** Inside the time-lock window`. Replace the whole bullet with: `- **D4b SUPERSEDED by D20 (owner, 2026-10-23).** Parking and the after-window question are withdrawn. The text that stood here (2026-10-13) carried no owner quote (HANDOVER.md:70-71; COVERAGE.md:29).` [OWNER]

1.3 **Lines 46-48 (D7).** Replace the whole bullet with: `- **D7 /close and /commit complete an incomplete dev.** The owner (O19): "dev永远都会完成，所以如果遇到close和commit自己派发相关的dev使用过的subagent补全。只要用户想dev一定dev完成，用户想close一定close完成". When /close or /commit finds an unfinished cycle, it dispatches again the subagents that cycle used (same subagent_type, task_id, lane and obligation; a fresh dispatched_at) until the cycle completes. /redev plays no part (D22), and there is no include and no role table (D21).` [OWNER: O19, prompts/P4.md:100-102; RD6 superseded]

1.4 **Line 35 (end of D3).** After "It is never an escape hatch.", append: ` Asking is the pause (D23). Inside /dev-overnight nobody is asked (D20).` [OWNER]

1.5 **Line 39 (end of D4).** Append: ` /redev is gated exactly as /dev (D22). PLAN-v2 S1's further exits (a typed harness command, CLAUDE_COMMAND_GATE=off) are planner proposals with no owner quote.`

1.6 **Line 49 (D8).** Append: ` Which producer owns an artifact is read from the dispatch record that declared it, never from a table (D21).` [INFERRED mechanism]

1.7 **Line 16.** After "/close and /commit only shrink.", append: ` D24 measures this per artifact.`

1.8 **Lines 105-106 (D16).**
- Replace "and the owner gives an explicit go-ahead at execution time. Every clone must re-clone afterwards." with: `The owner's go-ahead is on record (2026-10-13): "删除，告诉我怎么做", then "删除 git 历史里的邮箱和账号名：好"; for the refs "可以删，但是低priority" (quoted in prompts/P11.md:76-80). If the reviewer's own safety rules require a confirmation at execution time, it asks once with AskUserQuestion and names the concrete effects. No home is re-cloned or rewritten in place: a pre-push guard keeps old history off the remote (P11).`
- Tag: [INFERRED: D18's quoted words name no exception, and no owner quote asks for a re-clone (X4, X5, X8)]

1.9 **Lines 124-125 (D18).** Anchor: `The single exception is the irreversible step of P11`. Replace through "because it cannot be undone." with: `The quoted words name no exception. P11's irreversible publish runs on the go-ahead already on record (D16).` [INFERRED]

1.10 **After line 116.** Add: `- Every phase PR carries the D24 artifact table, measured, before review.`

1.11 **Append at the end of the file:**

```
## Planner text without an owner quote (status 2026-10-23)
- PLAN-v2 S1's exits beyond interrupt and /stop (a typed harness command, CLAUDE_COMMAND_GATE=off): planner proposal
  (COVERAGE.md:132, :284; HANDOVER.md:70-71).
- S2: superseded by D20. S9: planner default (landscape/G-stop-gates.md:283), kept as D2 applied by analogy.
- TC-5's producer-question file format and its overnight role: planner and decision-critic design (PLAN-v2.md:1169);
  the idea is backed by O19/D23, the parking role is withdrawn (D20).
- D1's default-off auto-push: no owner quote for the default. The owner's backup answer of 2026-10-19, "默认我都会打开，
  关闭的情况是特例", was resolved by the planner alone (HANDOVER.md:87-89). Unchanged here; no phase presents a privacy
  measurement as an answer to it.
- Codex default: the records conflict (commit 2e0303a, opt-in, 2026-05-04; paseo-daemon-teachings:245
  "每一个command都要加codex"). Unchanged here.
```

## 2. PLAN-v2.md

**Section 0 and principles**

2.1 **:24.** Replace `| Id | Clarification (binding) |` with `| Id | Planner clarification (ranks below quoted owner words and DECISIONS.md D20-D24) |`.

2.2 **:26 (S1).**
- Replace "The only way an agent involves the owner is the native AskUserQuestion tool, answered inside the turn, so no Stop happens." with: `An agent that needs the owner pauses by asking with the native AskUserQuestion inside the turn (D23); no Stop happens and no gate is released.`
- Replace "Exits are human only: interrupting the session, the human-only /stop command, a harness command the human types, and CLAUDE_COMMAND_GATE=off set by the human." with: `Exits are human only: interrupting the session and /stop (D4). Planner proposals with no owner quote: a harness command the human types; CLAUDE_COMMAND_GATE=off.`

2.3 **:27 (S2).** Replace the row with: `| S2 (D4b) | SUPERSEDED by D20 (owner, 2026-10-23: "不允许，谁说的？overnight就应该是无人值守"). Nothing is parked and nobody is asked, inside the window or after end_time; decisions are made in the session and recorded in the summary's "Decisions made without the owner". |`

2.4 **:34 (S9).** Append: ` (Planner default, landscape/G-stop-gates.md:283; D2 applied by analogy; no owner quote.)`

2.5 **:45.** Replace the bullet with:

`- [D3, D23] Producer questions. Outside /dev-overnight, a BA or dev producer that needs the owner pauses by asking. It asks directly with AskUserQuestion if the canary shows a foreground subagent can call it. Otherwise it writes docs/dev/producer-question-<task>-<role>.json, which the orchestrator relays with one AskUserQuestion inside the turn before re-dispatching the role. Inside /dev-overnight nobody asks (D20): the producer takes the option its evidence supports and records it as an assumption in its report. The disposition reports an unanswered question file as a fact gap (artifact, problem=unanswered), with no owner or fix field (D21).`

2.6 **:49.** Replace with:

`- [D20] Q3 is resolved by D20. Inside and after the window, nobody is asked and nothing is parked; decisions are recorded in "Decisions made without the owner". The AskUserQuestion deny (TC-45) covers the whole /dev-overnight session until the next human-typed prompt [INFERRED scope].`

2.7 **:82.** Replace "for /do, /dev, /redev, /dev-command," with "for /do, /dev, /redev (gated exactly as /dev, D22), /dev-command,".

2.8 **:85.** Replace with:

`- [D7] One disposition function for every stage (resolve-dev-artifact-chain.py --disposition --stage dev|close|commit, TC-22), reporting facts only. /close and /commit complete an incomplete cycle under the same task id by dispatching again the dispatch that declared each gap's artifact (D21) (P3, P4). There is no continuation include.`

2.9 **:86.** Replace with:

`- [D8] Only the producer named by an artifact's declaring dispatch record writes that artifact. The deny is derived from the session's dispatch records, not from a table (D21; P5-a proves the mechanism by sandbox experiment, TC-20).`

2.10 **:93.** Replace "/close, /commit, continue-cycle.md and the Stop gate consume it and never re-validate, re-derive or add a check. When the disposition is incomplete, they dispatch the producer that owns each gap under the same task id. One owner table, ROLE_BY_ARTIFACT in hooks/lib/obligation.py, names those producers and drives the D8 deny." with:

`/close, /commit and the Stop gate consume it and never re-validate, re-derive or add a check. When the disposition is incomplete, they dispatch again, under the same task id, the dispatch that declared each missing or invalid artifact. No table maps file names to roles (D21).`

2.11 **After :93.** Insert a new principle:

`- **One producer per artifact; consumers trust one conclusion (D24).** Each phase states, for every artifact it touches, its producers and its deciding consumers before and after, measured by grep and a sandbox write trace. An artifact without a reader, or without a writer, is deleted.`

2.12 **:95.** Replace "There is no retry bound, stop_hook_active release, counter, pause line or self-release token. The only way an agent involves the owner is AskUserQuestion, answered inside the turn, so no Stop occurs." with:

`There is no retry bound, stop_hook_active release, counter, text pause line or self-release token. An agent pauses by asking the owner with AskUserQuestion inside the turn (D23); no Stop occurs and no gate is released.`

2.13 **:96.** Replace the bullet with:

`- **Waiting happens inside the turn (D23).** A gated command that needs the owner's decision asks with AskUserQuestion and waits for the answer inside the turn. It never loops on blocked Stops on purpose, except inside the overnight window, where the time-lock blocks every Stop by design. There nobody is asked (D20), the PM step plans further work, and /stop is the human control.`

2.14 **:97 and :109.** After "(S1).**" and at the start of :109, insert: `[/stop is D4; the other two exits are planner proposals with no owner quote.]`

2.15 **:117.** Delete the row "Tell the reviewer when no /dev cycle is in flight, before an arming merge" (D19; arming lands on running sessions).

2.16 **:122.** Delete the row "Run doctor on each home before stub deletion" (D19; see 2.60).

2.17 **:134-135.**
- In :134, replace "S2 parking" with "unattended overnight (D20)".
- In :135, replace "owner-tagged gaps; one continuation include" with "facts-only gaps".

**P2 section (:340-399)**

2.18 **:340.** Replace the heading with `## P2 Run in any repo; overnight starts and ends; unattended overnight (D20); D6 landing route; arm G1-G3`.

2.19 **:348.** Replace with:

`- AskUserQuestion is denied to every caller of the /dev-overnight session (main agent and subagents), from its /dev-overnight record until the next human-typed prompt in that session [INFERRED scope from D20]. The message tells the agent to decide (by experiment, else the question's default), record the decision, and continue. Nothing is parked, and nothing is asked after end_time.`

2.20 **:368.** In the Change column, replace "Message to the main agent: park the pipeline … Other sessions, and the same session after end_time or after a human /stop record, are allowed." with:

`Main-agent message: "Overnight is unattended; nobody answers. Decide (experiment, else the default), record it in the cycle log and the summary's 'Decisions made without the owner', and continue." Subagent message: "Nobody answers overnight. Take the option your evidence supports, record it as an assumption in your report, and write your report." Other sessions are allowed, and so is the same session after a human-typed prompt (stop_contract.is_human_prompt).`

2.21 **:370.**
- Replace "The launcher seeds required_calls for steps 2-4." with: `No seed file: pretool-subagent-enforce derives the allowed steps 2-4 from _STEPS and cycle_index(state) [INFERRED; replay cycles 1 and 2].`
- Replace "Dev entries use schema_name "dev-report.v2", QA entries "qa-report.v2", and no max_retries." with: `For a dispatch that carries an obligation, posttool-overnight-file-check reads the schema from that dispatch's obligation (obligation.extract_obligation_block on tool_input.prompt). Its contract entry carries step, role, pipeline and path only (one declaration, D24; fixes E1). No max_retries.`
- Replace "The loop reset renders the next seed," with: `The PM TRIAGE handler is the contract's only writer; _candidate_contract_paths reads only <working root>/docs/dev/overnight/<sid>/cycle-<N>/cycle-contract.json;`

2.22 **:372.**
- Replace "- The final summary gains a "Parked questions" section (S2). - After end_time and before the session ends, the orchestrator asks each parked question with AskUserQuestion and finishes those families." with: `- The final summary gains "Decisions made without the owner" (D20).`
- Then add: `- Remove every parking clause P1 merged (commands/dev-overnight.md :12, :115-124, :451-452, :1049, :1071, :1073, :1331, :1444, :1476-1480, :1509, :1549-1563, :1684, :1691, :1708, :1741, :1834). Hard Rule 5 becomes "a producer question inside /dev-overnight is decided without the owner and recorded; nothing parks".`

2.23 **:380.** Replace with:

`- AskUserQuestion deny (TC-45): the overnight session's main agent or subagent, inside the window and after end_time with no human-typed prompt since /dev-overnight -> denied with the decide message; the same session after a human-typed prompt -> allowed; another session -> allowed.`

2.24 **:385.** Replace "and has a "Parked questions" section" with: `and has a "Decisions made without the owner" section; grep -ni park commands/dev-overnight.md -> 0; no instruction to call AskUserQuestion in dev-overnight.md`.

2.25 **:387.** Replace "a pipeline whose BA asks a genuine question inside the window is parked, the other pipeline completes, and after end_time the parked question reaches one AskUserQuestion;" with:

`a pipeline whose BA meets a genuine decision is decided without the owner and recorded, both families reach a QA pass, and the transcript holds 0 AskUserQuestion tool_use records; a forged ESCALATION_ACK line releases nothing;`

2.26 **:398-399.** Replace both lines with:

`Arming lands on running sessions without blocking a compliant in-flight cycle (P2 prompt acceptance 15). Rollback is the reviewer's revert (D19); the prose, overnight and arming commits revert separately.`

2.27 **P2 goals.** Add a goal:

`- Arm CLAUDE_OBLIGATION_STOPGATE only once G2's failing-stop path is a plain exit 2 that names the failing artifacts to their producer (C5): no escalations/, escalation-admissions/, progress/ or deferred-checks/ file and no ESCALATION_ACK admission (D4, design ruling 3).`

**P3 section (:402-450)**

2.28 **:402.** Replace the heading with `## P3 One disposition function for every stage, reporting facts only`.

2.29 **:408.** Replace with: `- Gaps carry facts only: the artifact path, the failing check's code and message, and the lane (D21).`

2.30 **:409.** Replace with: `- Arbitration is retired. ESCALATION_ACK releases nothing. The disposition does not read escalation records: the artifact a record names is already a gap through the chain's own check (design ruling 3).`

2.31 **:410.** Replace with: `- No continuation include and no /redev binding (D21, D22).`

2.32 **:417.** Replace with: `**Decisions applied.** D2; D3; D4; D7; D8; D10; D21; D22; D23; D24`.

2.33 **:421.** Replace the ROLE_BY_ARTIFACT row with:

`| hooks/lib/obligation.py | find_unresolved_dispatch_obligations :915-1036 | [INFERRED] Expose one reader, "declaring dispatch for an artifact path" (task_id, lane, role, the full obligation), for P4 and P5. Prove by replay that it names the owing dispatch for every gap kind of acceptance 2-6. |`

2.34 **:422.** Replace every "gives owner X ("…")" clause, and the "owner orchestrator" clauses of the question and do branches, with: `each gap is one line GAP artifact=<path> problem=<code>: <message> lane=<lane|->; no owner or fix field (D21)`.

2.35 **:425.** Delete the continue-cycle.md row.

2.36 **:426.** Replace with:

`| hooks/prompt-workflow.py | replay check in _ordinary_dev_start | S8 replay window only (60 s). /redev, /dev and /dev-command mint identically (D22); redev.md is unchanged. |`

2.37 **:438.** Replace "/redev <existing task> -> DEV_SESSION_ID equals that task. Bare /redev -> a fresh id." with: `/redev with any argument -> a fresh id, minted exactly as /dev.`

**P4 section (:452-509)**

2.38 **:468.** Remove S2 and add D20; D21; D22; D23; D24.

2.39 **:472.**
- Replace "and asks with AskUserQuestion (retry now / I will fix the harness and type /stop), asking again while nothing changes" with: `and records the stalled operation as the session's next harness-repair item; it offers the owner no "fix the harness" or "/stop" option`.
- Replace "incomplete goes to continue-cycle.md, then Step 1. - Close-QA findings use the same include, then a fresh close-QA round." with: `incomplete: dispatch again each gap's declaring dispatch (D7, D21), then Step 1. - Close-QA findings: dispatch the subagent the attribution journal records as the file's writer, dev when none is recorded [INFERRED], then a fresh close-QA round.`

2.40 **:474.**
- Replace "incomplete -> continue-cycle.md, then commit." with "incomplete -> dispatch again each gap's declaring dispatch, then commit."
- Replace "report the failure and offer retry or /stop" with "report the stalled operation and ask the specific decision, if one exists".
- Replace "artifact_role (now ROLE_BY_ARTIFACT)" with "artifact_role, with no successor table (D21)".

2.41 **:480.** Replace "Print each incomplete family's gaps on stderr and exit 2 as PostToolUse feedback; … Parked families appear in the list each cycle." with:

`The loop resets and exits 0. It prints gaps only if an overnight replay with and without the print shows the orchestrator needs them, and then by calling the P5 session-end predicate's own function. No switch, no cap, no block. The session-end predicate (P5) is the single anchor.`

2.42 **P4 goals.** Add a goal:

`- D24 table for every artifact /close and /commit read or write (L17, L18, L22, L23, L28, L31, L32, L40, L41, L42, L53), before and after, measured.`

**P5 section (:510-605)**

2.43 **:524.** Append: ` [INFERRED; decide by experiment: whether the do-report still carries hand-written files_* or /commit reads Span.write_set() directly.]`

2.44 **:532.** Remove S2, label S9 "planner", and add D20-D24.

2.45 **:536.** Replace the first sentence and "The main agent keeps the orchestrator rows: do-report-, completion-, user-requirement-, overnight-summary-." with:

`- Deny Write, Edit, NotebookEdit and Bash write targets to every caller except the agent whose dispatch obligation declared that path in this session (any declared path; undeclared paths keep today's policy rows) [INFERRED; arm-* sandboxes: 0 compliant writes denied, 0 V7a writes allowed].`

Also mark the escalation-record deny as temporary and route the removal of those stores to P3.

2.46 **:539.**
- Step 4: delete "; park any pipeline that needs an owner decision".
- Predicates: delete "or the explicit /redev task".
- Delete "parked families are gaps whose fix is "ask the parked question with AskUserQuestion now"".
- Replace "Gap lines" with: `one line per unmet fact, exactly as the disposition reports it (artifact path and failing check); no owner or fix field (D21).`

2.47 **:570.** Replace ""/redev <task>" of a chain_pass task with no dispatch -> rc 0." with: `/redev and /dev openers give the same rc on the same transcripts.`

2.48 **:572.** Delete ", a parked family".

2.49 **:602.** Replace "; parked questions are asked then." with "; it asks nothing (D20)."

2.50 **:603.** Replace "a gated command that needs an owner decision stays blocked until the human types /stop (S1)" with:

`the agent decides and records the assumption (D20 wording) so the span can reach its predicate [INFERRED; measure a headless session under repeated Stop blocks in the sandbox before arming]`

**P6 section (:608-643)**

2.51 **:626.** Replace "After hooks/capability-canary.py confirms 2.1.295 sends agent_type, the role order is … Stop writing agent-index files when agent_type is present." with:

`The role order is payload.agent_type, then meta.json agentType, then the registries only when both are absent (no live capture, D19). Every agent-index reader takes its cycle from the agent's own obligation, and pretool-cp-checkin stops writing agent-index.json when agent_type is present (D24).`

2.52 **:629.** Replace with:

`A4.d: the role binding sits at the tool call that produces the artifact (the changelog-analyst's git commit; the push-analyst's and merge-analyst's grant Write). Nothing is added where a grant is spent.`

2.53 **:635.** Replace "(P5-a's derived deny, now keyed on agent_type)" with "(P5-a's deny, now keyed on agent_type)".

**P9 section (:752-800)**

2.54 **:758.** Replace "D3 and S1 (in-turn AskUserQuestion, no pause exit); D4's gate and its human exits; D5's one-turn consent; D7's continuation; S2's overnight parking and carry-forward." with:

`D3/D23 (in-turn AskUserQuestion is the pause; a question never releases a gate); D4's gate and its human exits; D5's one-turn consent; D7 (/close and /commit dispatch the cycle's subagents until it completes); D20 (overnight asks nobody); D22 (/redev is /dev).`

2.55 **:766.** Remove S2 and add D20-D24.

2.56 **:770.** Append: ` A bad explicit --spec is blocked at UserPromptSubmit by prompt-workflow; no spec rule enters the disposition (C2).`

2.57 **:776.** Replace "that genuine owner decisions are parked inside the window and asked after it," with: `that nothing waits for the owner, inside or after the window, and every decision is recorded in "Decisions made without the owner" (D20),`.

2.58 **:782.**
- Replace ""/do <task-id>" and "/redev <task-id>", overnight parking (S2)," with "/redev = /dev (D22), unattended overnight (D20),".
- Replace "and the /do bypass as UD5 settles it (default: the /do commit bypass is kept; a remote push goes only through /push, D1)" with: `and that /do never lands a commit or a push: /close, /commit and /push do (owner: "你不知道do也要close才能commit？"; "永远不允许force和git commit，commit永远走commit command")`.

**P10 section (:801-843)**

2.59 **:812, :814, :822, :824, :833, :843.** Replace every "doctor on each home / each of the owner's homes" clause with:

`the stubs stay tracked exit-0 files; render-settings check reports any rendered settings entry naming a stub; the migration stops carrying stubs (P10 prompt R-e) (D19).`

2.60 **:836.**
- Add /dev-overnight, /merge and /push to the command list.
- Append: `; every artifact a /commit route stages is committed with the exclude in place.`

2.61 **P10 goals.** Add a goal:

`- Artifact-level D17 (D24): every artifact the harness writes has a reader and every artifact it reads has a writer, proven by an experiment-9 trace over all ten pipeline commands; ledger DEAD rows first.`

**P11 section (:845-887)**

2.62 **:845.** Replace the heading with `## P11 History rewrite, remote ref deletion, GitHub purge, pre-push guard (S7, D16, D1; last)`.

2.63 **:847-848.** Replace "An agent may prepare the commands and the local input files; the human runs every step." with:

`The phase prepares one scratch script; the reviewer runs it on the go-ahead on record (D16, owner 2026-10-13) (D19).`

2.64 **:853.** Replace with: `- The rewrite counts the secret-bearing keys in the .claude.json blob without printing any value (A6); a rotation line goes to the hand-off only if the count is non-zero.`

2.65 **:854.** Replace with:

`- After the owner's /pull, every home works on the rewritten history, and no push from any home can send a listed literal: a git pre-push hook installed by the landing runs scripts/check-public-core.sh --private-literals over every object the push would send (blobs, author, committer, message). It folds in the checkpoint push's own literal pass. [INFERRED; prove with acceptance 14 extended to /push of a new branch and a plain git push, on a pulled and an unpulled home.]`

2.66 **:863.** Delete "No session is running on any home."

2.67 **:865.** Replace with: `3. **Count, do not print** (A6).`

2.68 **:871.** Delete step 9.

2.69 **:885.** Replace with: `- A home keeps its pre-rewrite objects locally (recoverable); the pre-push guard keeps them off the remote.`

2.70 **:886.** Replace with: `Rollback: the offline pre-rewrite mirror can be force-pushed back; homes keep their local objects.`

**Section 7 ledger, section 9 TCs, sections 10-11**

2.71 **:916 (Q3).** Replace the decision cell with: `RESOLVED by D20 (owner, 2026-10-23): nobody is asked and nothing is parked, inside or after the window; decisions are recorded in the summary.`

2.72 **:920 (Q7).** Replace "the orchestrator then completes the do-report it owns (D8 allows the do-report row) with files_* equal to that dev-report's files" with:

`either the dev dispatched under the /do task id declares and writes the do-report completion in its own obligation, or the disposition takes the G2-verified dev-report as the /do task's conclusion; the /close orchestrator writes nothing (D8). Decide by experiment.`

2.73 **:933 (UD1).** Replace the default with:

`Replay with CP_ENFORCE_MODE=block. With 0 false blocks, arm at the producer's SubagentStop. Otherwise fix the producers, or retire the contract and list cp-state as unreferenced. Never ship "advisory" prose for a contract agents are told to follow (owner: "永远不要通过ai的自觉性").`

2.74 **:935 (UD5).** Replace the default with: `/do consent never covers git commit, git merge to a protected branch, or git push; landing goes through /close, /commit and /push (owner: "你不知道do也要close才能commit？"; "commit永远走commit command").`

2.75 **:949 (U-F2a).** Replace with: `Decide by experiment whether anything in the owner's flow acts on the ratchet; if nothing does, keep only --measure in CI.`

2.76 **:1033 (TC-4).** Delete "/redev of a chain_pass task passes (TC-25);".

2.77 **:1034 (TC-5).**
- Replace "the disposition reports it as a gap, owner orchestrator, fix "relay with AskUserQuestion, then re-dispatch <role>"" with "the disposition reports it as a fact gap (problem=unanswered)".
- Delete ", and is needed anyway for overnight parking, where AskUserQuestion is denied (TC-45)".
- Append: ` If the canary shows a foreground subagent can call AskUserQuestion, the subagent asks directly outside /dev-overnight (D23) and the file becomes unreferenced (D17).`

2.78 **:1044 (TC-15).**
- Replace "replaced by S2 parking" with "replaced by D20 (decide and record)".
- Replace "the P2 parked-pipeline replay" with "the P2 unattended-decision replay".
- Replace "S2: a genuine overnight decision parks instead of skipping." with "D20: a genuine overnight decision is made and recorded instead of skipped."

2.79 **:1046 (TC-17).** Replace the row's content with: `WITHDRAWN (D22). /redev with any argument mints a fresh id exactly as /dev. Test: replay /redev x and /dev x -> two fresh ids of the same form.`

2.80 **:1047 (TC-18).**
- Replace "Mirrors TC-17." with: `Planner mechanism, no owner quote. Keep only if a P5 replay of Esc plus a plain prompt inside a /do span shows a deadlock that no existing path clears.`

2.81 **:1048 (TC-19).** Replace with: `WITHDRAWN (D21). No owner table. The two prose tables (close.md:162-181, commit.md:99-116) are deleted in P4 with no successor.`

2.82 **:1049 (TC-20).** Replace "Derived from ROLE_BY_ARTIFACT … differs from the row's owner, and retired rows to all callers." with:

`[INFERRED] Derived from the session's dispatch records: a path declared by an obligation may be written only by the agent whose Agent tool_use carried that obligation; any other caller, the main agent included, is denied. Undeclared paths keep the existing tool-policy rows.`

Replace the last cell with "A per-role prefix list in tool-policy.v1.json, if the experiment fails."

2.83 **:1054 (TC-25).**
- Delete "A "/redev <task>" of a chain_pass task passes with no dispatch."
- Replace "for --auto, the gate runs `dev-lifecycle.py list-actionable --next-action close` (or `commit`) itself and every actionable task whose registry entry predates the span opener is a gap" with: `for --auto, the gate and /close --auto call one shared target function with one cut-off, with the cache bypassed`.

2.84 **:1063 (TC-34).** Replace with: `WITHDRAWN (D21, D22). /close and /commit dispatch again the declaring dispatch of each gap; the dev loops re-dispatch the lane's dev or QA with the same obligation. No include.`

2.85 **:1064 (TC-35).** Replace "P2's rendered overnight contract names dev-report.v2 and qa-report.v2 and omits max_retries, which no hook reads." with:

`For obligation-bearing dispatches, the overnight collection check reads the schema from the dispatch obligation, and the contract declares none for them (one declaration, D24; E1). No max_retries.`

2.86 **:1074 (TC-45).** Replace "(S2)", the window-only scope and the park and question-file messages with D20, the session-until-human-prompt scope [INFERRED] and the decide messages of 2.20.

2.87 **:1110.** Replace "the history rewrite, the force-push, the remote ref deletion and the installed-hook removal are human-run (P0, P11)" with "the history rewrite, the force-push and the remote ref deletion run once, by the reviewer, on the go-ahead on record (D16)".

2.88 **:1142.** Replace the target cell with: `0 questions; every decision recorded in "Decisions made without the owner" (D20)`.

2.89 **:1169.** Delete "The artifact also stays when the canary shows subagents can ask, because overnight parking needs it (TC-45)."

## 3. Prompts

**3.0 All remaining prompts (P2, P3, P4, P5, P6 and P9; P10:100; P11:70).**

Replace "S# are the owner clarifications in PLAN-v2.md section 0; they rank right below DECISIONS.md and above every plan." (in P10 and P11, the equivalent sentence) with:

`S# are planner clarifications in PLAN-v2.md section 0. They rank below quoted owner words and DECISIONS.md D20-D24 (owner, 2026-10-23). S2 is superseded by D20; S1's extra exits and S9 carry no owner quote.`

Every prompt also gains, in its owner-decisions list, one bullet that names D20-D24 and their quotes as they apply to the phase.

### 3.1 P2

- **:1, :4-5.** In the title, replace "S2 parking" with "unattended overnight". In the PR example, replace "parking, " with "unattended overnight, ".
- **:7-8.** Replace "(one disposition function for every stage, owner-tagged gaps, one continuation include; another session)" with "(one disposition function for every stage that reports facts only; another session)".
- **:45-49.** Replace "P3 changes the replay window (…) and the /redev binding inside `_ordinary_dev_start` (:1831-1921). Distinct functions; … keep both sides." with:

  `P3 changes the replay window only (`_DEV_REPORT_TERMINAL_STATUSES`, `_dev_report_reached_terminal`, :1783-1799). `_ordinary_dev_start` keeps minting /redev exactly as /dev (:1929-1931); keep no hunk that binds /redev to an existing task (D22).`
- **:56-58.** Replace "P3 only redev.md, the new templates/prompt-includes/continue-cycle.md and a few lines of agents/qa.md" with "P3 only a few lines of agents/qa.md". There is no redev.md and no include (D21, D22).
- **:64.** Delete "; P3 :640 (the /redev row)".
- **:99-103 (Goal 4).** Replace with:

  `4. **Unattended overnight (D20).** From launch to the end of the session nobody is asked and nothing waits for the owner, inside the window or after end_time. Every decision a pipeline meets is made without him and recorded (decision, options, evidence or experiment, chosen option) in the producer's artifact or re-dispatch prompt and in the summary section "Decisions made without the owner". The family runs to a QA pass and lands through D6. AskUserQuestion is denied to every caller of that session until the next human-typed prompt [INFERRED scope]. [INFERRED: genuine decisions follow an experiment when possible (D18), else the question's default (pre-plan Clause A).]`
- **:116-117.** As 3.0.
- **:131-136 (D4b / S2 bullet).** Replace with:

  `- **D20 (owner, 2026-10-23).** "不允许，谁说的？overnight就应该是无人值守". No parking, no after-window question. Also T0 (2026-10-22): "今晚继续跑…总之就是不能停". O22 still applies to every question outside overnight.`
- **:137-141 (D4 / S1 bullet).** Replace "Exits are human only: interrupting, `/stop`, a harness command the human types (outside the overnight window), and CLAUDE_COMMAND_GATE=off (P5). … The time-lock is the model for every gate (O19: "就和overnight一样")." with:

  `Exits: interrupt and /stop (D4); P2 relies on no other exit. Inside an overnight session nobody is asked (D20). In attended gated commands an in-turn AskUserQuestion is the pause (D23): a solid question, never an exit (O22).`
- **:145.** Replace "Word parking, gaps and deny messages" with "Word gaps, decisions and deny messages".
- **:146-147 (D3).** Replace "or, for a subagent, through P1's producer-question artifact. Asking never releases a Stop." with: `which is the pause (D23); a subagent without the tool uses P1's producer-question file. Inside /dev-overnight nobody is asked (D20). Asking never releases a Stop.`
- **:207 (TC-15).** Replace with: `- TC-15 (P2 part): the unattended-decision replay (acceptance 14).`
- **:253 (row 1).** Replace "state the convention once in each command file that consumes them" with: `add no per-file convention line; the hook prints self-describing lines (for example HARNESS_ROOT=<abs>) (D21, prompt bloat O2).`
- **:256 (row 4) with :421.**
  - Add: `The lane-completeness hook is the canonical aggregate's only producer. Delete the orchestrator aggregation step in dev.md (:885 and the "MUST write" block :898-923) and its dev-command.md equivalent instead of respelling them, and delete the aggregate-pending.json writer (:126-129, :188-208; no reader, L27). G3 stays the collection barrier. Replay: a 2-lane /dev and the 2-pipeline overnight have the canonical before QA, with 0 orchestrator aggregation calls.` [D24, D8]
  - Drop dev.md :885 and :923 from the :421 respelling list.
- **:257 (row 5).** Drop the lane-completeness advisory log clause; that log has no reader (L54) and goes with P4's sibling logs. Drop it from acceptance 5 too.
- **:261 (row 9).** Add: `Delete hooks/lib/closeout.py's harness-report.json writer (:518-537); nothing reads it (D24).`
- **:262 (row 10).** Replace "S2, TC-45" with "D20, TC-45".
- **:263 (row 11) and :359-363, :380.**
  - Replace "The reset renders the next cycle's seed contract." with: `The reset writes no contract.`
  - Replace the Launch seed bullet with: `- **No seed file.** Before TRIAGE, pretool-subagent-enforce derives the allowed steps 2-4 for the current cycle from _STEPS and cycle_index(state) [INFERRED; replay cycles 1 and 2 with no seed file: steps 2-4 pass, a wrong role at step 2 blocks].`
  - Delete :380.
  - Add: `Reduce contract_runtime._candidate_contract_paths (:79-98) to <working root>/docs/dev/overnight/<sid>/cycle-<N>/cycle-contract.json; the prose drops the .claude/overnight-contract-* mirror and the cycle-current.json symlink.`
- **:267 (row 15).**
  - Replace "Pass `--task-id` to every write-qa-mode.sh call (without it the e2e hook never finds the QA report; armed test)." with: `write-qa-mode.sh (row 4) exits non-zero and names the flag when --task-id is missing (HC2). Record in the PR that the durable fix is for the e2e hook to read the QA report path from the QA dispatch's obligation.`
  - Add: `Remove every parking clause P1 merged (dev-overnight.md :12, :115-124, :451-452, :1049, :1071, :1073, :1331, :1444, :1476-1480, :1509, :1549-1563, :1684, :1691, :1708, :1741, :1834). Hard Rule 5 becomes "inside /dev-overnight a producer question is decided without the owner and recorded; nothing parks".`
- **:310-312.** Replace "already compare in UTC: leave them and list them under "Out of scope, found", with the rest." with: `switch the guard's `_end_time_passed` (:379) to lib/overnight's parser (you edit this file in row 10). List pretool-git-privilege-guard.py and notification-idle-overnight.py for the next phase that edits them.`
- **:320.** Replace "P5's import-free launcher copies this rule." with: `P5's launcher imports lib/overnight.window_open by path (stdlib only) unless a replay shows the import failing where a copy would not.`
- **:324-330 ("Who").** Replace with:

  `- **Who.** Every caller of the /dev-overnight session, its main agent and its subagents, from the session's /dev-overnight record until the next human-typed prompt in that session's main transcript (stop_contract.is_human_prompt; no new state) [INFERRED scope from D20]. A /stop or the owner's first command in the morning lifts it. Nobody else is denied: another session in the same repository is allowed. `is_overnight_active` must not decide it. For a subagent payload, read the parent session's main transcript.`
- **:349-353 ("Messages").** Replace with:

  `- **Messages.** Exit 2. To the main agent: "Overnight is unattended; nobody answers. Decide (experiment, else the question's default), record the decision in the cycle log and in the summary's 'Decisions made without the owner', and continue." To a subagent: "Nobody answers overnight. Take the option your evidence supports, record it as an assumption in your report, and write your report." Neither message offers a way to stop.`
- **:364-372 (Producer).** Replace "Dev entries use `schema_name` "dev-report.v2", QA entries "qa-report.v2", the BA-QA step "ba-qa-report.v1" (P1 registered it)." with:

  `For steps 8, 10, 11g, 12, 15 and 17 (dispatches that carry an obligation) the rendered entry carries step, role, pipeline and path only; make schema_name optional for them in schemas/cycle-contract.v1.json. posttool-overnight-file-check validates their artifacts against the schema named by that dispatch's own obligation (obligation.extract_obligation_block on tool_input.prompt; the hook already reads it, _agent_dispatch_dims :230-243). Schema names stay only for dispatches with no obligation (PM PLAN/TRIAGE/RETRO, specialists). One declaration per artifact (D24, E1).`
- **:373-374.** Delete ", and BA or dev after a parked question is answered".
- **:395-398.** Replace the "Parked questions" bullet with:

  `- The final summary (Step 21 template) gains "Decisions made without the owner": per pipeline, the task id, the decision, the options, the evidence or experiment and the chosen option, written as each decision is made. P1's parking prose is removed (row 15).`
- **:399-402.** Replace with:

  `- After end_time nobody is asked. The session ends once closeout_gaps is empty (retro reports and summary). If every pipeline is done before end_time, the time-lock still blocks until end_time; the PM step plans further work, and /stop is the human control.`
- **:430-434 and :449-452.** Replace "so respell every harness path in both files; a respelled line that P4 later deletes costs nothing" with: `respell only the lines P4 keeps (producer dispatch and the one disposition call; PLAN-v2:365)`.
  - Delete the commit.md late-repair bullet (:449-452). Leave commit.md Step 5's probe and until-loop, and close.md Step 0's re-validation, as they are, and list them for P4 (design ruling 1, C2).
  - Exempt their lines from acceptances 2 and 4.
- **:454-457.** Replace "state once per agent file what the harness root is" with: `add no per-agent line; agents take Read paths from the dispatch's FIRST ACTION line, as today`.
- **:465.** Replace "(D4b)" with "(D20)".
- **:490-491.** Replace "(the human's /restart or /redev)" with "(the human's /restart)".
- **:592.** Replace "P3's work: the disposition function, owner-tagged gaps, continue-cycle.md, redev.md, freshness, the lane echo," with "P3's work: the disposition function (facts only), freshness, the lane echo,".
- **:615.** Replace with: `- Do not deny AskUserQuestion to any session other than the /dev-overnight session itself (D23 keeps the in-turn pause everywhere else).`
- **:623.** Replace "do not add a pause grammar" with: `do not add a text pause line (AWAITING_INPUT); in-turn AskUserQuestion outside /dev-overnight stays allowed (D23)`.
- **:710-717 (acceptance 7).**
  - Replace "the park message" with "the decide message", and "the question-artifact message" with "the subagent decide message".
  - Replace "the same session after end_time, or after a human /stop record: exit 0" with: `the same session after end_time with no human-typed prompt: exit 2; after a human-typed prompt (a /stop or any command): exit 0`.
- **:732-737 (acceptance 11).** Replace "step 12 names dev-report.v2, step 15 qa-report.v2," with "obligation-bearing entries carry no schema_name;" and replace "The loop reset renders cycle 2's seed." with "Cycle 2 needs no seed file."
  - Add: `Rerun E1 for the dev and the QA pair: a template-shaped v2 report passes G2 and file-check; a report invalid against its obligation's schema is stopped by G2 at its producer's stop.`
- **:739 (acceptance 12).** Replace "has a "Parked questions" section" with: `has a "Decisions made without the owner" section; grep -ni park commands/dev-overnight.md prints nothing; dev-overnight.md has no instruction to call AskUserQuestion`.
- **:753-756 (acceptance 14).** Replace the parking scenario with:

  `- unattended decision: in a 2-pipeline cycle one BA meets a genuine decision inside the window; it is decided without the owner and recorded in that pipeline's artifact and the summary; both families reach a QA pass; the session ends after end_time once retro and summary exist; the transcript holds 0 AskUserQuestion tool_use records; an attempted call is denied with the decide message; a forged ESCALATION_ACK line releases nothing and no file appears under escalations/, escalation-admissions/, progress/ or deferred-checks/.`
- **Goal 7 / row 17.** Add: `Arm CLAUDE_OBLIGATION_STOPGATE only after G2's failing-stop path (subagentstop-artifact-contract-enforce.py:745-830) is a plain exit 2 naming the failing artifacts to their producer, with no record, admission, progress or deferred-check file and no ESCALATION_ACK admission (:791-802). Either take that hunk before the arming commit, or move arming after P3's change.` [D4, design ruling 3, C5]
- **New acceptance.** `The PR carries the D24 table for overnight state, cycle contract, retro report, summary, canonical aggregate, advisory logs, harness-report.json, continuation sentinel, aggregate-pending and terminal receipts.`

### 3.2 P3

- **:1, :4-5.** Title: `# Phase P3: one disposition function for every stage, reporting facts only`. PR example: `P3: one disposition, facts-only gaps, strict pass`.
- **:7.** Replace "S2 parking" with "unattended overnight".
- **:42-44.** Replace "and the /redev binding inside `_ordinary_dev_start` (:1831-1921). Distinct functions; neither is heavy. The two sets of hunks meet near :1900-1930 …; keep both sides." with: `only. `_ordinary_dev_start` keeps minting /redev exactly as /dev (D22).`
- **:55-57.** Replace "You edit only commands/redev.md, the new templates/prompt-includes/continue-cycle.md, and a few lines of agents/qa.md" with "You edit only a few lines of agents/qa.md". Replace "P2 applies its substitution to your two command files" with "nothing for P2 to respell".
- **:63.** Delete the README line (no /redev row change).
- **:89-95 (Goal 1).** Replace "/close, /commit, the continuation include, the overnight loop (P4) and the Stop gate (P5) consume this one result" with "/close, /commit and the Stop gate (P5) consume this one result".
- **:96-98 (Goal 2).** Replace with: `2. **Facts-only gaps (D21).** Each gap names the artifact, the failing check's code and message, and the lane. No owner field, no fix text, no filename-to-role table in code or prose.`
- **:99-102 (Goal 3).** Replace with: `3. **Agent-writable releases retired.** The arbitration file and the arbitration and awaiting_input phases go; declare_awaiting_input is deleted; ESCALATION_ACK releases nothing. The disposition does not read escalation records: the artifact a record names is already a gap through the chain's own check (design ruling 3).`
- **:103-106 (Goal 4).** Replace with: `4. **No continuation include, no /redev binding (D21, D22).** /redev stays /dev minus re-emitting the spec (commands/redev.md unchanged). P4 and P5 consume the disposition and the declaring-dispatch reader (row 1).`
- **:113-124 (release notes).**
  - Replace "the cycle's own orchestrator, /redev <task-id>, or (after P4) /close and /commit complete it" with "the cycle's own orchestrator or (after P4) /close and /commit complete it".
  - Delete the bullet "`/redev <task-id>` continues an existing cycle under its own task id;".
- **:150-156 (D3 / S1).** Replace "O19's earlier … is superseded by O22 and S1: nothing pauses, nothing is released by a question. A producer's question is P1's producer-question artifact; the include relays it with one AskUserQuestion and re-dispatches the same role." with:

  `An agent pauses by asking the owner with the native AskUserQuestion inside the turn (O19, reaffirmed 2026-10-23, D23). The question is a solid, specific decision, never an escape window (O22). The turn waits; no Stop occurs and no gate is released. Inside /dev-overnight nobody asks (D20). Do not write "nothing pauses" anywhere.`
- **:157-163 (D7).** Replace "You build the stages and the include; P4 wires /close and /commit to them." with: `You build the stages and the declaring-dispatch reader; P4 wires /close and /commit to them.`
- **:164-165 (D8).** Replace "The include writes no producer artifact, and ROLE_BY_ARTIFACT is the single owner table the D8 deny (P5-a) derives from." with: `Nothing you add writes a producer artifact. The owning producer of an artifact is its declaring dispatch (D21).`
- **:166-171 (D4 / S1).** Replace "the include loops with no round cap. When a round changes nothing, the orchestrator asks the owner with AskUserQuestion inside the turn (…), never stops and never loops on blocked Stops." with:

  `a producer whose artifact does not validate is re-dispatched with the unchanged finding, with no cap. Only a producer's own solid question is asked (D23); a stall is not a question.`
- **:172-175 (D4b / S2).** Replace with: `- **D20.** Inside /dev-overnight nobody is asked and nothing is parked. A decision is made in the session and recorded (P2 owns the prose).`
- **:176-177 (D4c).** Replace "the human's /restart or `/redev <task-id>` resumes it" with "/restart resumes it".
- **:179.** Replace "bare /redev keeps its behaviour," with "/redev keeps its behaviour,".
- **:194-195 (S9).** Replace "**S9.** /do's only terminal is completed." with: `**S9 (planner default; D2 applied by analogy, no owner quote).** /do's only terminal is completed.` Replace "to an orchestrator gap" with "to a fact gap (do.status:<value>)".
- **:213-214, :217.** Delete TC-17, TC-19 and TC-34.
- **:242-246 (commit order).** Replace step (1) with "the declaring-dispatch reader with its test". Replace step (5) with "the replay window".
- **:253 (row 1).** Replace with:

  `| 1 | hooks/lib/obligation.py (P1) | find_unresolved_dispatch_obligations :915-1036 | [INFERRED] Expose one importable reader returning, for an artifact path, the dispatch that declared it (task_id, lane, role, the full obligation block). No table. Prove by replay that it names the owing dispatch for every gap of acceptance 2-6; for a never-dispatched artifact, return the command's canonical todo step. |`
- **:259 (row 7).** Delete. Also delete G2's reader-less `deferred-checks/<agent>.json` write (subagentstop-artifact-contract-enforce.py:688-694) and the journal-view sidecar write (:451-465), with reachability proofs (D17, D24).
- **:260 (row 8).** Delete.
- **:261 (row 9).** Delete.
- **:262 (row 10).** Keep.
- **:271-291 ("ROLE_BY_ARTIFACT").** Delete the subsection.
- **:296-297 (Output).** Replace the GAP format with `GAP artifact=<repo-relative path> problem=<code>: <message> lane=<lane or ->`. Also expose, per gap, the declaring dispatch from row 1 as data, not as an owner field.
- **:315-319 ("owners and fixes").** Delete the bullet. Replace it with: `a missing completion report is not a gap: completion-<ts>.md leaves the required chain (it restates chain_pass and is orchestrator-written; D8, D24).`
- **:320-325 (ordering).**
  - Replace with: `[INFERRED; decide by sandbox experiment] Staleness ("QA judged the current dev-report", "BA-QA judged the current ticket/context") is read from dispatch order in the transcript, not file mtimes, and enforced as G1 preconditions of the QA and dev dispatches plus row 14's G2 freshness. The disposition keeps only the design's G4 set (existing checks, strict pass, shard roster).`
  - The producer-question clause becomes: `an unanswered producer-question file is a fact gap (problem=unanswered)`.
- **:326-332 (escalation records).** Replace with: `G2 escalation records are not read; docs/dev/arbitration-*.json is ignored.`
- **:333-336 (do branch).** Replace "gives a gap owned by the orchestrator" with "gives the fact gap problem=do.status:<value>".
- **:346-347, :352 (close and commit stage).** Delete "owned by qa, fix "close.md Steps 1-2 …"" and "owned by changelog-analyst, fix "…"". Keep the facts.
- **:354-391 ("The continuation include").** Delete the section.
- **:413, :425, :426.** Delete the technical choices for ROLE_BY_ARTIFACT, the /redev token forms and the include wording.
- **:515.** Replace "the "Parked questions" summary section" with "the 'Decisions made without the owner' summary section".
- **Acceptance 2-6 (:595-630).** Replace every "owner=<role>" expectation with the artifact path and problem code.
  - :610-611 becomes: "a valid producer-question-<task>-ba.json newer than the ticket -> problem=unanswered".
  - Drop the escalation-gap bullets of acceptance 4.
- **Acceptance 8 (:643-644).** Replace with: `The declaring-dispatch reader returns the owing dispatch for every gap of acceptances 2-6 in the sandbox transcripts.`
- **Acceptance 9 (:645-651).** Delete bullets 1-2. Keep bullet 3, the 60 s window. Add: `a /redev UserPromptSubmit mints a fresh id exactly as /dev`.
- **Acceptance 10 (:652-663).** Delete.
- **Acceptance 13-14 (:687-695).** Drop continue-cycle.md and redev.md from both.
- **:721-746 (rules).** Remove ROLE_BY_ARTIFACT, the include and the escalation-gap rule from "added". Add the retired owner/fix mapping.
- **New acceptance (D24).** `The PR carries the D24 table for the disposition (L28: list each caller in P3's files and move scripts/dev-lifecycle.py:377, close-route-select.py and G2's _wire_qa_chain to the importable function), escalation stores (L25), journal-view (L26), completion (L23), ba-qa-report (L14: drop BA's write permission at policies/tool-policy.v1.json:129), the canonical aggregate (L18) and terminal vocabulary (L21: remaining consumers import obligation.TERMINAL_VOCABULARY).`
- **Experiment before the include question is closed (D18).** `In the sandbox, a foreground subagent with AskUserQuestion allowed asks one question. Record whether it works (it decides QP5's fate for P5/P9).`

### 3.3 P4

- **:10-11.** Replace "S2 parking" with "unattended overnight". Replace "owner-tagged gaps, one continuation include" with "facts-only gaps".
- **:35-41.** Delete the `continue-cycle.md` cat-file check and the `grep -c ROLE_BY_ARTIFACT` check. Add: `git show origin/master:hooks/lib/obligation.py` contains P3's declaring-dispatch reader.
- **:50-57 (interfaces).** Replace the GAP form with `GAP artifact=… problem=… lane=…`. Delete the continue-cycle.md, ROLE_BY_ARTIFACT and `/redev <task-id>` items. Add: `the declaring-dispatch reader (P3 row 1)`.
- **:70-74 (Goals 1-2).** Replace "Incomplete goes to continue-cycle.md under the same task id with the same producers, then Step 1. Close-QA findings go through the same include" with:

  `Incomplete: for each gap, dispatch again the dispatch the reader returns (same subagent_type, task_id, lane and obligation, a fresh dispatched_at; G1 blocks a re-dispatch whose obligation differs), then Step 1 (D7, D21). Close-QA findings go to the subagent the attribution journal records as the file's writer, dev when none [INFERRED].`

  Make the same change in Goal 2.
- **:76-79 (Goal 3).** Replace "Asking never ends the command; if the answer does not unblock the work, ask again." with: `Asking is the pause (D23): the turn waits for the owner's answer; no gate is released.`
- **:120-123 (D3 / S1).** Replace "No question releases anything." with: `The question is the pause (D23); asking or answering releases no gate.`
- **:127-128 (D4b / S2).** Replace with: `- **D20.** Overnight is unattended: the loop asks nothing and nothing is parked.`
- **:173-174 (Q7).** Replace "then the orchestrator completes the do-report it owns" with: `and the /close orchestrator writes no report (D8): either the dispatched dev declares the do-report completion in its own obligation and G2 verifies it, or the disposition takes the G2-verified dev-report as the /do task's conclusion. Decide by sandbox experiment (D18).`
- **:210 (row 2).** Replace "Keep Step 2's `SESSION_ID="dev-${TASK_ID}"` binding (:579-583)" with: `Bind the registry name from the disposition's own output (obligation.registry_dir_for, canonical_task_id), not a "dev-" prefix; add a /close of a /dev-command task to the sandbox cases (L01).`
- **:213 (row 5).**
  - Replace "dispatch the owner ROLE_BY_ARTIFACT gives" with "dispatch again the declaring dispatch".
  - Delete artifact_role with no successor.
  - Compute the repository plan once as data. Name the manifest and grant rebuild (L37, L38) as P6's producer fix instead of /commit finding loops. Keep Step 6's REJECT.
- **:226-232 (Step 0).** Replace "asks with AskUserQuestion (for example "retry now" / "stop here; I will type /stop"), asking again while nothing changes" with: `retries once, then records the stalled operation as the session's next harness-repair item; it does not offer "/stop" or "I will fix the harness"`. Replace "follows continue-cycle.md with stage dev" with "dispatches again each gap's declaring dispatch".
- **:233-237.** Delete the option "or read them from one default-mode run after chain_pass as data only (D10; say which)".
- **:238-242.** Replace with: `Close-QA findings: dispatch the subagent the attribution journal records as each named file's writer (dev when none), re-run --disposition --stage dev, then a fresh close-QA round. No include.`
- **:259-261.** Replace "and --bulk" and "or `/commit --bulk` in a session started later" with "or `/commit --auto`" (ON6: "不允许/commit --bulk").
- **:329-344 (overnight loop).**
  - Replace the per-family print with: `The reset never blocks and prints nothing per family unless an overnight replay with and without the print shows the orchestrator needs it; then it calls the P5 session-end predicate's function.`
  - Delete :338-339.
  - At :344, the gap text handed to P5 says "complete the family", never "ask".
- **:454-455.** Add: `The owner-answered in-turn AskUserQuestion is not a pause grammar (D23).`
- **:519.** Replace the grep with: `grep -c continue-cycle.md commands/close.md commands/commit.md commands/redev.md` prints 0; a /redev prompt is minted exactly like /dev.
- **:528.** Replace "`GAP … owner=qa`; the include re-dispatches qa" with: `the qa-report gap; the declaring QA dispatch is re-dispatched`.
- **:533-534.** Follow Q7 as above.
- **:568 (acceptance 11).** Replace "a parked family … is listed with the park line" with: `a family with a question file inside the window is decided without the owner, re-dispatched, and reaches chain_pass in the window with no AskUserQuestion`.
- **New goal and acceptance (D24).** `Per artifact /close and /commit read or write (L17, L18, L22, L23, L28, L31, L32, L40, L41, L42, L53): writers and deciding readers before and after, measured; each reduced to one producer and one deciding consumer, or the later phase named. L40: add a commit-QA consistency entry that G2 checks, or keep one channel.`

### 3.4 P5

- **:12.** Replace "parking," with "unattended overnight,".
- **:48, :53-54, :64.** Delete the continue-cycle.md and ROLE_BY_ARTIFACT start checks. Check for the disposition function and P3's declaring-dispatch reader.
- **:87-90 (Goal 1).** Add: "/redev is gated exactly as /dev (D22)".
- **:94-96.** Replace "No bound, no token, no pause line, no counter." with: `No bound, no token, no text pause line, no counter. The pause is an in-turn AskUserQuestion (D23), which is not a Stop.`
- **:111, :124.** Replace the `/do <task-id>` sentence with: `[planner mechanism TC-18, no owner quote] Kept only if a replay of Esc plus a plain prompt inside a /do span shows a deadlock that no existing path clears.`
- **:139-146 (D4 / S1).** Replace "(he rejected the question pause as the gates' early exit: a question must be a solid question, never an escape window)" with "(a question must be a solid question, never an escape window)". Replace "no `AWAITING_INPUT` pause, no question that releases a Stop" with "no AWAITING_INPUT text pause, no question that releases a Stop".
- **:147-151 (D3).** Replace with:

  `- **D3 / D23 (O19, O22; reaffirmed 2026-10-23).** "但是我是不是说过agent可以给我使用提问的组件询问问题作为暂停方式？" The agent pauses by asking the owner with AskUserQuestion inside the turn: a solid, specific decision, never an escape window. Answering is not a Stop and keeps /do consent, so the gate needs no release for it. A text line releases nothing. Release notes: "When the agent needs your decision, it pauses and asks you with the question dialog."`
- **:157-159 (D4b / S2).** Replace with:

  `- **D20 (owner, 2026-10-23: "不允许，谁说的？overnight就应该是无人值守").** Inside the window the time-lock blocks every Stop; only /stop and off release it. The /dev-overnight session never asks the owner and never waits for him, inside the window or after end_time. It decides itself (experiment, else the question's default; [INFERRED], ON9) and records the decision. There is no parked state.`
- **:160-161 (D8).** Replace "the deny is derived from ROLE_BY_ARTIFACT (TC-19, TC-20)" with "the deny is derived from the session's dispatch records (D21, TC-20 revised)".
- **:165-167 (D7).** Replace "the gaps name owners, and P4's close.md and commit.md complete the cycle through the include" with: `the gate consumes only the --stage close/commit disposition and names no owners; /close and /commit dispatch the cycle's subagents (D7)`.
- **:227.** Delete TC-19.
- **:255 (row 1).** Replace the ROLE_BY_ARTIFACT derivation and the hand-listed orchestrator rows with:

  `[INFERRED] A subagent may write the paths its own obligation declares (obligation.resolve_own_obligation :800). Any other caller, the main agent included, that writes a path declared by any obligation of the session is denied. Undeclared paths keep the policy rows. Decide by experiment in the arm-* sandboxes against the table variant: count compliant writes denied and V7a writes allowed; take the variant with 0/0 and less code.`

  Replace the last sentence ("The fan-out canonical aggregate is written by scripts/aggregate-dev-report.py, a Bash-run script, not an inferred write target.") with: `Orchestrator writes mandated by dev.md (:540-542 spec_path patch, :1176-1199 refined/iter context, :1026-1036 spec edits) are arming blockers next to close.md:793; measure whether the Bash write extractor sees python-heredoc and jq writes (D18).`
- **:256 (row 2).** Label the escalation-record deny "temporary, retired with the stores (P3/P6)". Count it among the rules to retire.
- **:265 (row 10).** Replace the inline GATED/CONTROL copies and their drift test with: `one tracked JSON file read by stop_contract, the coordinator fallback and the launcher (stdlib)`.
- **:288.** Delete "; park any pipeline that needs an owner decision".
- **:305-315 (dev predicate).** Make one predicate for /dev and /redev. Delete "for `/redev <task-id>`, the task P3's binding names" and "A `/redev <task>` of a task that is already chain_pass passes with no dispatch (TC-4)."
- **:320-324 (dev-overnight predicate).** Replace "A parked family shows as P3's question gap (…), which after end_time means: ask the parked question now." with: `An unanswered producer-question file inside the span is the gap "question <path> unanswered"; the orchestrator clears it itself (the question's default or an experiment, recorded) and re-dispatches the role.`
- **:325-332 (--auto targets).** Replace with: `the gate and /close --auto call one shared target function with one cut-off, with the cache bypassed; acceptance 8 shows they agree.`
- **:333-347 (/merge, /push).** Replace the copied remote-choice and tier rules with git-written facts: a reflog entry on refs/remotes/<remote>/<branch> after the opener whose new value is HEAD (or HEAD equals the upstream tip), and a DEFAULT_BRANCH reflog merge entry after the opener whose merged parent is SOURCE_TIP. [INFERRED; check with acceptance 6]
- **:353-357.** Replace "One line per gap, `<artifact>: <problem> / owner: <role> / fix: <action>`, built from P3's gap fields" with: `COMMAND_GATE /<command>: not complete, then one line per unmet fact exactly as the disposition reports it. Where a missing dispatch must be named, take it from the canonical todo step (scripts/todo/<command>.py).`
- **:399.** Replace "how the derived deny matches a path against ROLE_BY_ARTIFACT rows" with "how the deny reads declared paths from the session's dispatch records".
- **:492-495 (out of scope).** Add dev.md and dev-command.md mandated orchestrator writes as arming blockers.
- **:519.** Replace "(P2's overnight deny is the only one, S2)" with "(P2's /dev-overnight deny is the only one, D20)".
- **:584-586 (acceptance 5).** Apply the TC-18 condition above.
- **:596.** Replace the /redev case with: `the S1-S3 transcripts give the same rc at every Stop whether the opener is /redev or /dev`.
- **:625-628 (acceptance 12).** Replace "a parked family -> rc 2" with: `a question file after end_time -> rc 2 until that family is chain_pass`. Add: `arm-overnight shows 0 AskUserQuestion calls and 0 parked families`.
- **:639.** Drop the question-artifact D8 case if the canary removes the file.
- **:733-735 (residuals).** Replace with: `An overnight session runs past end_time until every family passes; it asks nothing. On a surface without AskUserQuestion the agent decides and records the assumption [INFERRED; measured in the sandbox before arming].`
- **New goal (D24).** `For every fact the gate reads (TodoWrite list, typed span opener, minted task id, /do sidecar, disposition, do-report, close and commit stages, merge and push results, overnight state), name its one producer and one deciding consumer, and retire the other deciders in files P5 edits: prompt-workflow.py:1781 _DEV_REPORT_TERMINAL_STATUSES (import obligation.TERMINAL_VOCABULARY), the todo-file writers (L08), the separate do.status deciders (L30), and merge.md Step 3's validate-and-unlink (L44, after a reachability run). Acceptance: git grep shows one writer and one deciding consumer per artifact. The release notes lead with this.`

### 3.5 P6

- **:10.** Replace "(one disposition, owner-tagged gaps, one continuation include)" with "(one disposition, facts-only gaps)".
- **:41-46.** Replace the table-derived-deny prerequisite with: `P5 ships a deny that stops any caller from writing a producer artifact another agent owes; P5's D8 acceptance cases pass on origin/master. You change only the role input.`
- **:68-69.** Replace "ROLE_BY_ARTIFACT in hooks/lib/obligation.py" with "the declaring-dispatch reader".
- **:147-148, :230-233, :306-307.** Replace each "a continuation by /close or /commit, or /redev" (or "a D7 continuation or /redev") with: `a QA loop in the same session, or a /close or /commit completion dispatch (O19)`. Add:

  `/redev is /dev with less context: it mints a fresh task id, so its dev is a first round and inherits nothing (D22).`

  New acceptance: `/redev then a dev dispatch -> new task id; the written set is that dev's own; no predecessor search runs.`
- **:151-152 (D3 / S1).** Replace with:

  `- **D3 / D23.** Outside /dev-overnight, a genuine, specific owner decision (O22) is asked with AskUserQuestion inside the turn: by the subagent if the canary shows it can call the tool, otherwise by the orchestrator relaying the dev's question file and re-dispatching dev. Inside /dev-overnight nobody is asked (D20). A3.a and F3.a run on the dev report, so neither path bypasses them.`
- **:193 (TC-20).** Replace with "TC-20: the D8 deny keeps P5's mechanism; you change only the role it reads."
- **:207-211 (correction 1).** Decide option one now. Every index reader takes its cycle from the agent's own obligation (resolve_own_obligation, then canonical_task_id/registry_dir_for). pretool-cp-checkin stops writing agent-index.json when agent_type is present. Index entries written before the pull are read only for payloads with no obligation (D15). If the +100 cap blocks this, raise the cap by the measured amount.
- **:244.** Delete "and ROLE_BY_ARTIFACT".
- **:260-263 (correction 11).** Keep only the second option: correct each newly applied row to the paths its agents/*.md documents, proved by replaying every documented write. No exempted-role list.
- **:288 (row 8) and :362-364.** Replace "Do not add a check where the grant is read or spent … consumer-side check, which the owner ruled out (O10, O12)." with: `The role binding sits at the tool call that produces the artifact: the commit itself (the changelog-analyst's git commit) and the push or merge grant file (the analyst's Write).`
- **:308-309 and :610.** Replace the gate-fault rule with:

  `Rule (b) runs on the union of readable transcripts. stderr and the finding name the unreadable one. A declared path only that predecessor wrote is accepted once the dev names it in its own Bash. G2 never exits 2 for a fault the producer cannot repair.`

  :610 becomes: `predecessor transcript unreadable -> stderr names it; a report listing that predecessor's files without naming them -> exit 2 with the instruction to name them; after naming -> exit 0`.
- **:342-343, :484-485.** P6 removes the FIRST ACTION sentinel lines it makes inert (commands/*.md dispatch templates, agents/*.md), with their prompt-wording tests in the same commit. The DO NOT list allows exactly those deletions.
- **:453-457 (out of scope).** In the A3.a promotion commit, delete the changelog-analyst's git provenance filter (agents/changelog-analyst.md:438-470) and the stale "git-derived and therefore assert the cycle AUTHORED" sentence (:253-256). Deletion only (PC9, D24).
- **:492-493.** Replace with: `A block from a hook this prompt does not change goes under "Out of scope, found" with the hook, its file:line and the artifact's two declarations. The driver stays compliant with agents/*.md and the command text and is never adapted to the hook.`
- **New acceptance (D24).** The PR names, for "which files this dev wrote", the one producer (the transcript write set) and lists the other two (the attribution journal, dev's owned_edits) with the phase that retires each, decided by experiment.

### 3.6 P9

- **:11.** Replace "S2 parking" with "unattended overnight" and "owner-tagged" with "facts-only".
- **:52.** Delete the continue-cycle.md check.
- **:75-76.** Replace "`/do <task-id>`, the derived D8 deny" with "the D8 deny as P5 merged it".
- **:82-83.** Delete "templates/prompt-includes/continue-cycle.md (the Step 16/17 loops point at it, row 7), ROLE_BY_ARTIFACT, `/redev <task-id>`".
- **:86.** Replace "the overnight parking and its "Parked questions" summary section" with "the unattended-overnight prose and its 'Decisions made without the owner' summary section".
- **:109.** Replace "beside P3's continue-cycle.md" with "under templates/prompt-includes/".
- **:111-112 (Goal 2).** Replace "D3 and S1 (in-turn AskUserQuestion, no text pause, no exit); … D5's one-turn consent and `/do <task-id>`; D7's continuation; S2's overnight parking and carry-forward." with: `D3/D23 (in-turn AskUserQuestion is the pause; a question never releases a gate); D4's gate and its human exits; D5's one-turn consent; D7 (/close and /commit dispatch the cycle's subagents until it completes); D20 (overnight asks nobody); D22 (/redev is /dev).`
- **:140-141.** As 3.0.
- **:165-166 (D3 / S1).** Append: ` The question is the pause (D23).`
- **:170-171 (D7, D8).** Replace with: `- **D7, D8.** /close and /commit complete an unfinished cycle by dispatching the cycle's subagents again; only the producer writes its artifact. The Step 16/17 loops re-dispatch the lane's dev with the QA report path, same task_id, lane and obligation, fresh dispatched_at.`
- **:172-174 (S2).** Replace with: `- **D20.** "不允许，谁说的？overnight就应该是无人值守". dev-overnight.md says nothing waits for the owner, inside or after the window, and drops its "skipped" and "parked" counters.`
- **:176 (D15).** Replace "the /do commit bypass (its push half per E2)" with "(the /do landing bypass is closed per E2's revised rule)".
- **:241-253 (E2).** New decision rule: the privilege guard ignores /do consent for git commit, git merge to a protected branch and git push. Regression tests:
  - commit under /do -> exit 2 naming /close then /commit;
  - push under /do -> exit 2 naming /push;
  - a valid /commit or /push grant -> unchanged.

  [OWNER: "你不知道do也要close才能commit？" (P4.md:174); "永远不允许force和git commit，commit永远走commit command" (teachings:139); D15 yields to these]
- **:271-276 (E4), :401 (row 9), :443.** New decision rule: replay compliant /spec-driven dispatches with CP_ENFORCE_MODE=block. With 0 false blocks, arm at the producer's SubagentStop. Otherwise fix scripts/spec-check.py and pretool-cp-checkin.py until 0, then arm. If arming still fails, drop the Checkpoint Marking Contract from the agents and list cp-state under "Now unreferenced". Remove "no arming of cp-enforce (E4)" from Out of scope. [OWNER: "如果发现了问题就通过harness解决，永远不要通过ai的自觉性！" teachings:124]
- **:376, :393 (row 1).** Replace "if anything downstream then proceeds with no spec, the disposition gets the clause" with: `prompt-workflow prints "Spec: <abs> (unresolved)" and blocks the prompt at UserPromptSubmit; no spec rule enters the disposition (design ruling 1, C2)`. Acceptance 3 adds: `bad --spec -> blocked at UserPromptSubmit, no registry created`.

  Also in row 1: BA records spec_path from its dispatch line "Spec file:" (dev.md:472), and the orchestrator patch step (dev.md:540-584) and the jq context builds (:1177-1199) are deleted (L10, D8).
- **:397 (row 5).** Replay first whether P6 made the registry sentinels inert; if so, delete the sentinel loops and CP_AGENTS consumers. Otherwise compute the roster from the stems of agents/*.md in one hooks/lib function (no 23-name literal); test that obligation.ROLES is a subset.
- **:399 (row 7) and acceptance 8 (:491-492).**
  - Replace "The Step 16/17 QA-fail loops point at continue-cycle.md (P3)" with: `Each QA-fail loop is one sentence: "QA fail: re-dispatch this lane's dev with the QA report path, the same task_id, lane and obligation template, and a fresh dispatched_at; the Stop gate keeps the command open until the disposition is chain_pass."`
  - For include families: a sandbox experiment decides whether a hook can deliver the include text (SubagentStart additionalContext or PreToolUse(Agent) updatedInput); if so, agents carry no pointer. List each family's enforcing hook, or "none", in the PR.
  - Acceptance 8: each loop is at most 3 lines and contains no "park", "ROLE_BY_ARTIFACT" or include pointer.
- **:400 (row 8).** Replace "genuine owner decisions park inside the window and are asked after them (S2)" with the D20 wording.
  - Delete the qa-input merge and both "QA input" list lines (dev.md:1196, :1395; dev-command.md:793, :919; L56).
  - The whole fallback block (dev.md:196-218, dev-command.md:142-150) becomes "re-run the command" (L02, L03, L05).
  - Contract entries at dev-overnight.md:837-838 take their schema from the obligation (L46/E1, if P2 did not).
  - dev-overnight.md reports suggested permissions instead of writing them (:1518-1519, L55).
  - Acceptance 10's grep adds `blocked` and `\bpark(ed|s|ing)?\b|Parked questions`.
- **:404 (row 12).** Replace "(S2, P2's deny)" with "(D20, P2's deny, whole /dev-overnight session)". The deny message reads "overnight is unattended: decide (Clause A / experiment), record the assumption, continue".
- **:407 (row 14).**
  - Replace the S2, "/do <task-id>" and "/redev <task-id>" documentation items with "/redev = /dev (D22)" and "unattended overnight (D20)".
  - Document `/do <task-id>` only if P5 merged it and a replay shows it, marked as planner design.
  - D-D1e: replay each of the 13 hooks; one whose matcher matches no tool is "never runs" and listed under "Now unreferenced" for P10.
- **:408 (row 16).** Replace the added CLAUDE.md line with:

  `"/do, /dev, /redev, /dev-command, /close, /commit, /merge and /push cannot end until code confirms their todo list and artifacts. When one needs the owner, it pauses by asking with AskUserQuestion inside the turn: a real, specific decision, never an escape; the gate stays armed. /dev-overnight never asks."`

  In :60, change only "this session" to "this turn"; drop "`/do <task-id>` re-grants consent…".
- **:527 (acceptance 16).** Replace the CLAUDE_COMMAND_GATE grep with: the gate line contains "AskUserQuestion" and "pause".
- **New acceptance (D24).** One-writer/one-reader proof for L01 (all consumers call canonical_task_id/registry_dir_for), L24 (QA writes its own spec sections; delete the orchestrator step dev.md:1026-1048), L51 (one grant channel and one reader in hooks/lib/allowlist.py), L44 (keep the code validator after a reachability replay), L42 (a script or hook produces the token). List L26, L27, L48, L25 deferred-checks, L36 and the L18 superseded-dir branch under "Now unreferenced" with reachability proofs. Remove the false "no code table" claims (close.md:278, commit.md:83-84) if P4 left them.

### 3.7 P10

- **:11-12, :37-38.** Replace "P3 (one disposition, one continuation include)" with "P3 (one disposition, facts-only gaps)". Re-check the merge-title checks against the rewritten P3.
- **:84-96 (Goal).** Add a goal and its own commit:

  `Every artifact the harness writes has a reader and every artifact it reads has a writer (D24). Run experiment 9 for all ten pipeline commands (/spec /dev /redev /dev-command /dev-overnight /do /close /commit /merge /push) in the toy repo and sandbox home, list every path written, seed with ledger DEAD rows, and apply the D17 search per path. A write with no reader is deleted at its producer; a read with no writer has its branch deleted; a path with two writers goes in the PR as a hand-off. The PR carries one table: artifact / producers / consumers / verdict / proof. No hand-kept table enters code.`
- **:100.** As 3.0.
- **:119-121 (D3 / S1) and :305 (row 12).** Replace with:

  `Interactive sessions: BA records "verdict: retire" and its evidence in its context artifact; the orchestrator asks the owner in-turn with AskUserQuestion (D23); removal_authorized is set only from that answer (hooks/subagent-stop-guard-integrity.sh:23). /dev-overnight: no question, no park; BA gives patch or redesign and records the assumption (D20) [INFERRED], and the retire proposal becomes a backlog entry for the harness /spec session.`

  Delete the "two or more false-positive or deadlock entries" threshold.
- **:134-136 and R-a..R-i (:313-401), experiments 3-4, acceptance 3, 5, 6, 7, :765.** Decide by experiment between (a) keeping the six stubs tracked as repo-versioned exit-0 files and (b) stand-ins. C1 excludes (b) ("zero new mutable state files", design:26-27), and :765 calls stand-ins untracked local state.
  - Keep R-e, experiments 1-2 and row 1 (render-settings check reports rendered entries naming a stub).
  - Delete R-a..R-d and R-f..R-i, experiments 3-4, acceptances 3, 5, 6 and 7, and the stand-in part of the P11 hand-off.
- **:178-181 (experiment 8) and correction 1.** New rule: G2 (blocking) rejects a v1-shaped report at dev's SubagentStop and names dev-report.v2. The rewritten report must pass G2 and posttool-overnight-file-check.py when that hook reads a pre-P2 cycle contract. Delete the v1 projection only if both hold. Nothing depends on gap owner tagging.
- **:182-186, :301 (row 8), :403-409, acceptance 11 (:661-667).** Replace the per-producer pattern list with three rules:
  - (1) runtime files go under harness-owned .claude/ subdirectories, with one info/exclude line per directory;
  - (2) no docs/dev artifact that /commit stages is ever excluded;
  - (3) a leftover with no consumer is deleted at its producer.

  New acceptance: in the toy repo with the exclude in place, /dev, /close and /commit commit every staged artifact with no "paths are ignored" message. Run experiment 9 for /dev-overnight, /merge and /push too.
- **:299 (row 6).** Replace scripts/build-pipelines-from-triage.py with "the failed_attempts filter in it (and agents/pm.md:338 if proven dead)". The file is live (dev-overnight.md:912).
- **:304 (row 11).** Add to KEEP every docs/reference file that quotes the owner verbatim: recoverable-discard-register-20261005.md, qa-status-gate-gap-orchestrator-side-20261005.md, close-commit-failure-inventory-20260927.md, commit-dryrun-close-gate-ruling.md. If one must go, first copy its dated quotes into the design doc's section 0. Acceptance 18 checks that every CJK quote of a deleted file is still in the tree.
- **:307 (row 14).** Replace "untracked files are left for the human (rm stays denied)" with: `producers stop writing untracked byproducts; nothing is left for the human (D19)`. Add an experiment: prompt_bytes before and after /clean's cleaner on the sandbox home.
- **:308 (row 15) and :411-427 (ratchet).** Decide by experiment: replay a harness /dev → /commit → /push adding 2,000 lines and record whether anything in that flow acts on the ratchet. If nothing does, drop policies/size-budget.v1.json and keep only --measure in CI.
- **:455-462.** Derive the protected set at run time from what the rendered settings.json registers (hook files, the hooks/lib modules they import, the P5-a engines). If the derivation misses a case, deny every non-forced git rm in the harness home.
- **:572-573.** Replace "they may only lose citation lines of records you delete" with: `those three files may only lose lines: citations of deleted records, and any line whose subject this PR deletes or proves dead`. This includes the routing row "changelog-status*) echo changelog-analyst", which matches no file.
- **:800 (tail).** Append: `The owner's rulings of 2026-10-23 (DECISIONS.md D20-D24) outrank every other decision and S#.`
- **New gap rows.** Delete or prove: G2's journal-view writer (L26), aggregate-pending (L27), workflow-history (L06), the close-force flag readers (L36: subagentstop-e2e-enforce.py:387, subagentstop-artifact-contract-enforce.py:365-373, :1215), the superseded-<task>/ branch (L18), the dead terminal-vocabulary branches (L21), the bulk-commit chain once P4 removes --bulk's entry (L39), the qa-input reader if P9 left it (L56), leftover G2 escalation stores (L25), and advisory writers P5 left (L54).

### 3.8 P11

- **:25-30 (deliverable 3), :86-88 (D18 bullet), :551-553, hand-off item 6 (:797-803).**
  - Replace "The publish is irreversible, so it keeps the one owner go-ahead that D16 and D18 reserve for it; the reviewer obtains that go-ahead and runs your script." with: `The go-ahead is on record: "删除，告诉我怎么做", then "删除 git 历史里的邮箱和账号名：好", and "可以删，但是低priority" (2026-10-13, :76-80). The reviewer runs your script once A8's preflight passes.`
  - In :86-88, delete "The single exception D18 names … obtains it."
  - Item 6: quote X4 and X5. If the reviewer's own rules require a confirmation, it is one AskUserQuestion naming the concrete effects, not a free-text message.

  [INFERRED: D18's words name no exception]
- **:59-64 (goal bullet 4), B3, B6, B7 (:382-463).** Replace with:

  `- After the owner's /pull, every home works on the rewritten history, and no push from any home can send a listed literal. The landing installs a git pre-push hook beside the pre-commit hook (scripts/install/land:238). It runs scripts/check-public-core.sh --private-literals with the home's own list over every object the push would send (rev-list --objects <pushed tips> --not <remote refs>: blobs, author, committer, message). On a hit it refuses the push and names the object. The checkpoint push's own literal pass (hooks/lib/checkpoint-core.sh:316-334) folds into it. Homes keep pre-rewrite objects as local, recoverable data (X17).`

  Delete B3, B6 and B7. [INFERRED; prove by extending acceptance 14 to /push of a new branch and a plain git push, on a pulled and an unpulled home]
- **:65-66, :192-201 (fact 9, goal 5).** Replace "Acceptance 14 measures it; the landing adds no check (producer-side)." with: `The pre-push guard closes both holes at the producers.` P7b's seeding (the one producer of the home's list) also takes A2's extra sources: non-noreply identities and e-mails outside the allowlist in the home's own history. Acceptance 14 expects "refused at the push, object named".
- **:127-135 (fact 1), hand-off item 9 (:807-811).** Replace the manual `git merge --no-ff` instruction with: `Measure on a throwaway PR which GitHub merge method produces commits whose author and committer carry no account address. Make it the only allowed method through the repository-settings API. If none qualifies, disable the methods that reintroduce the address. Record it in the PR.` [INFERRED]
- **:263, :353-361 (B1).** Delete the old-root constant. If a notice is still wanted, derive "upstream rewritten" from git (the branch and its upstream share no root) within P7b's 50 ms bound.
- **:366-369, :374-401 (B2, B3), :523-524, :528-529.** Delete all branch moves from the landing. If the 5b experiment shows replayed copies must not remain, put the fork-point rule into hooks/pull.sh, and have fswatch's safe_pull call pull.sh. On a stopped rebase, the pull producer restores the pre-pull state itself (abort plus its own stash pop) and leaves a notice (D20/T0: an unattended run never waits). Decide by acceptance 8 run as an experiment.
- **:417-419, :559-560 (B4 fallback).** Delete. No tracked old→new map.
- **:421-431 (B5).** Delete. If acceptance 14 shows the opt-in checkpoint push must not carry the old chain, write_checkpoint starts a new chain on HEAD when the previous snapshot shares no root with HEAD (one producer, no worker, no slices).
- **:434-443 (B6).** Delete; leave home-local backup refs and stash entries untouched.
- **:450-463 (B7).** Delete; no reflog edits and no prune.
- **:469-471 (B8).** Delete the real-list count; logs/landing.log has no reader (render-settings:1208).
- **:532-536.** Replace with: `P11 takes no product decision on the backup default (D1, disputed). With the pre-push guard, privacy holds whichever way the default is set.`
- **:740-748 (net code cap).** Replace "target <= +200 (…)" with "target <= 0: the pre-push guard plus tests, minus the folded checkpoint pass (PLAN-v2 :1158)".
- **Acceptance 3-13 (:641-701).** Keep 1, 2 and 15. Replace the rest with:
  - (i) a /push of a new branch carrying a stand-in literal in a blob or identity is refused, naming the object;
  - (ii) the same for the opt-in checkpoint push;
  - (iii) scenarios 3, 4, 5, 5b and 6 reduced to "after the pull and any later push, the sandbox origin holds 0 objects with a stand-in literal".
- **:843 (tail).** Append the same sentence as P10:800.
