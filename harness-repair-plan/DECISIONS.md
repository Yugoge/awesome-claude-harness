# Owner decisions (2026-10-13)

These decisions were made by the repository owner. They override PLAN-v1.md wherever the two disagree.
PLAN-v1.md still gives the file:line scope for each phase. Where it says "honest_blocked", "untrack settings.json",
"ask for curl/wget/docker" or "per-cycle commit", read the decision below instead.

## Owner rulings of 2026-10-23 (latest; they override every decision below, PLAN-v1, PLAN-v2 and every prompt)

Source: the owner's message of 2026-10-23T11:59:26Z answering the reviewer's P2-P11 summary line by line (reviewer
session transcript, record 1921, answering record 1895). Quoted verbatim; "…" marks elided words; English in brackets.

- **D20 Overnight is unattended (supersedes D4b and PLAN-v2 S2).** Answering
  "…先把那条流水线停放，其他流水线继续跑。结束时间一到再一次性问你（D4b）": "不允许，谁说的？overnight就应该是无人值守" [Not allowed. Who said that? Overnight must be unattended.]
  A /dev-overnight session never asks the owner and never waits for him, inside the time-lock window or after
  end_time. Nothing is parked. Every decision a pipeline meets is made inside the session and recorded (decision,
  options, evidence or experiment, chosen option) in the re-dispatch prompt, the cycle log and the overnight summary's
  section "Decisions made without the owner". The family runs to a QA pass and lands through D6. Earlier owner words
  agree: "今晚继续跑，我授权你做任何事情+开启任何新的周期，总之就是不能停" (2026-10-22); "daemon的意义就是无人值守"
  (docs/reference/paseo-daemon-teachings-20260910.md:77 at f8c18c2).
  [INFERRED, no owner words: how a genuine decision is made. Rule: an experiment when one can be run (D18), otherwise
  the question's own `default`. Precedent: the pre-plan Clause A, "do NOT ask the user anything; make decisions
  yourself" (f8c18c2 commands/dev-overnight.md:115). A spec-declared user gate (Clause B) inside /dev-overnight is
  handled the same way and listed first in the summary. Prove with P2's acceptance 14 (the 'unattended decision'
  scenario of the armed replay, TC-15) before P2's arming commit, run with two stand-in genuine decisions (one an
  experiment can settle, one it cannot) and one stand-in spec-declared user gate: 0 questions asked; the first records
  its experiment and result, the second records the question's own `default`; all three appear in "Decisions made
  without the owner", the user gate first.]
- **D21 No filename-to-role table, no agent manual (supersedes PLAN-v2's "One owner table, ROLE_BY_ARTIFACT", TC-19,
  TC-20, TC-34 and the owner/fix fields of gaps).** Answering "每个缺口都写明：缺了哪个文件、什么问题、该由哪个角色补、怎么修":
  "？？又开始hardcode了？自己检查我最开始的需求是什么。又开始给agent一个无法对齐无法彻底完全100%执行的说明书？" [Hardcoding again? Check
  what my original requirement was. Again a manual the agent can never align with or execute 100%?] The original
  requirement (2026-10-09; quoted in prompts/P9.md bullet 'Clean, self-consistent, public (O2, O4)', prompts/P10.md
  bullet 'What the owner asked for (2026-10-09)'):
  "如何帮助我彻底理清仓库并且彻底清理没用的东西，以及彻底保证整个harness彻底完整系统性干净实现目的不多不少地运行" and
  "我只关心：对外公开可用度+自洽度（不多不少刚刚好每一个harness artifact都有生产者和消费者）+整洁清洁度。不要走偏". No table maps file names to roles, in code or in prose. A gap reports facts
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
  [But didn't I say the agent may ask me with the question component as the way to pause?] O19
  ("交回一个'需要你决定'的问题块 / 这样就可以暂停") stands, and O22 ("提问一定要有solid问题而不是当作逃生窗口") qualifies it. Outside /dev-overnight, an
  agent that needs the owner pauses by asking with AskUserQuestion inside the turn. The question names a real,
  specific decision. Neither asking nor answering releases a gate. No document says "nothing pauses" or "no pause
  form". Asked on 2026-10-24 (AskUserQuestion, "agent 用提问组件问你选择题时，你的回答能不能让这条命令提前结束？"), the owner
  chose "只是暂停": the question only pauses; after the answer the agent continues to completion; an answer never ends
  the command and never releases a gate; the exits are the owner's interrupt and /stop; an agent never offers a
  "stop here" or "end" option to give itself a way out (O22).
- **D24 Producer and consumer per artifact are the first requirement.**
  "…最关心的artifact生产者消费者问题，有一点提及吗？没有，…这都是在干啥？" [The artifact producer/consumer problem I care about most: is it mentioned at all? No… what is all this
  doing?] Read with O4/O6 (2026-10-09, above) and O10/O12
  ("核心架构：每个产物只有一个生产者，正确性在生产者那一端由 hook 保证，消费者只信一个结论"). Every harness artifact has exactly one producer and at least one consumer, and its consumers trust one
  conclusion. Every phase PR carries a table: artifact / producers before → after / deciding consumers before → after
  / proof (a grep for writers and readers, plus a sandbox write trace). An artifact that is written and never read is
  deleted at its producer. An artifact that is read and never written loses its reading branch. Phase P1b
  (prompts/P1b.md, added 2026-10-24) owns this requirement: the full inventory and a CI check that derives writers and
  readers from code or a runtime trace at test time, never from a committed list; later phases keep that check green.

## Owner ruling of 2026-10-24

- **D25 Never fail.** "还有一件我关心的！就是永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！"
  [One more thing I care about! It must never fail! No development run may ever hit an error in the process! And if an
  error does occur it can be repaired immediately!] Earlier words that agree: "dev永远都会完成…只要用户想dev一定dev完成，
  用户想close一定close完成" (O19), "不要给我说失败" (O17), "诚实终态永远不允许" (paseo-daemon-teachings-20260910.md:103),
  "永远一致的规则就是agent哪里犯错了自己就补哪里" (:108), "如果发现了问题就通过harness解决，永远不要通过ai的自觉性！" (:124).
  Measured by a replay suite in CI that every later phase keeps green: (1) a compliant run of each of the ten pipelines
  (/spec /dev /redev /dev-command /dev-overnight /do /close /commit /merge /push) meets 0 gate blocks and 0 hook errors;
  (2) every injected fault (missing artifact, malformed artifact, stale-version report, git index.lock held, interrupted
  session, resume after a usage limit, one lane leaving an old report) is returned to its own producer, named by
  artifact and failing check, and repaired at the next round with no human action; (3) no dead end: no state exists
  that no agent action can clear, apart from the owner's own /stop; (4) every process failure fixed so far is a replay
  that stays green (P1's fan-out block, E1's v1/v2 contract conflict, N1's stuck /pull, V1-1/NV-1's silent refused
  repair). Phase P1c (prompts/P1c.md) owns the suite; each later phase adds the fault replays for the flows it changes.
  master's CLAUDE.md Hook Discipline #5 ("honest terminal branch") contradicts this and "诚实终态永远不允许"; P9 rewrites
  it under D20 and D23.

## Product stance

- **D15 Published product.** The repo is a public, general-purpose harness that anyone can clone and use.
  No feature is retired. Live sessions keep running on this tree while it is edited (status quo), so a
  registered hook file is never deleted in the same change that unregisters it: it becomes an exit-0 stub
  for one phase.
- **Architecture is producer-side** (see docs/reference/close-commit-zero-failure-mechanism-20260928.md).
  Each fix lands on the single producer of an artifact: a hook, a launcher, the UserPromptSubmit hook, a
  producer prompt, the renderer, or CI. Never add consumer-side checks: nothing new in /close, /commit or
  the changelog-analyst (no scan, no cleanup class, no filter). /close and /commit only shrink. D24 measures
  this per artifact.
- **D10 Technical choices by rule.** Pure technical choices are not put to the owner. The implementer
  picks the option that (1) follows the producer-side design doc, (2) adds the least code and the fewest
  rules, (3) is covered by a regression test, and (4) is listed in the PR's technical-choices table
  (choice / why / how to revert) so the reviewer or owner can veto it.

## dev never "honestly fails"

- **D2 dev has exactly one terminal: completed, with no gap.**
  - Remove dev report states blocked / needs_review and the status_rationale escape. There is no
    honest_blocked disposition anywhere.
  - QA fail or warning, and BA needs_clarification, are process steps inside the cycle. They are not
    terminals.
  - Remove the `required_values` lines that force a QA report to say "pass" (dev.md, dev-command.md,
    dev-overnight.md). Instead, the code-computed disposition reaches chain_pass only when every lane's
    QA verdict is pass. A failing QA sends the lane back to dev and the cycle continues.
- **D3 Questions are in-turn and never an exit.** When dev, BA or any pipeline needs the owner, it asks
  with Claude Code's native AskUserQuestion tool inside the turn. Asking never releases a stop gate.
  A question must be a real, specific decision the agent cannot make from the request, the code or a
  sensible default. It is never an escape hatch. Asking is the pause (D23). Inside /dev-overnight nobody is asked
  (D20).
- **D4 Stop gates on eight commands.** /do, /dev, /dev-command, /dev-overnight, /close, /commit, /merge
  and /push cannot stop until the todo list is complete and their artifacts are verified by code.
  No retry bound, no self-release, no agent-writable release file. The only way out is human:
  interrupting the session, or a human-only /stop command. /redev is gated exactly as /dev (D22). PLAN-v2 S1's
  further exits (a typed harness command, CLAUDE_COMMAND_GATE=off) are planner proposals with no owner quote.
- **D4b SUPERSEDED by D20 (owner, 2026-10-23).** Parking and the after-window question are withdrawn. The text that
  stood here (2026-10-13) carried no owner quote (HANDOVER.md:70-71; COVERAGE.md:29).
- **D7 /close and /commit complete an incomplete dev.** The owner (O19):
  "dev永远都会完成，所以如果遇到close和commit自己派发相关的dev使用过的subagent补全。只要用户想dev一定dev完成，用户想close一定close完成". When
  /close or /commit finds an unfinished cycle, it dispatches again the subagents that cycle used (same subagent_type,
  task_id, lane and obligation; a fresh dispatched_at) until the cycle completes. /redev plays no part (D22), and there
  is no include and no role table (D21).
- **D8 The orchestrator never writes a producer's artifact.** Only the producer subagent writes its report.
  Which producer owns an artifact is read from the dispatch record that declared it, never from a table (D21).
  [INFERRED mechanism; prove by D21's sandbox replay before use.]

## Pipelines

- **D4c Interrupts and API errors need no gate code.** Claude Code does not run the Stop hook when the
  user interrupts a turn, and on an API error it runs `StopFailure` instead of `Stop` and ignores that
  hook's output (code.claude.com/docs/en/hooks, sections Stop and StopFailure). So the Stop gate contains
  no API-error or interrupt rule and parses no error records (nothing hardcoded). Such a cycle simply stays
  incomplete, and /restart resumes it.
- **D5 /do consent lasts one turn.**
- **D6 Overnight lands once, at the end.** After the whole overnight session ends:
  /close --auto, then /commit --auto, then /merge, then /push. /commit --auto follows the normal /commit
  route but batches cycles the way /close --auto does. Never /commit --bulk. Remove the per-cycle commit
  at commands/dev-overnight.md:1576-1578 and give the post-loop flow (:1794-1809) the /close step.
  - **D6a The owner types the four landing commands** in the morning, each held by its own Stop gate.
    The overnight session never runs /commit or /push itself (they stay human-only, CLAUDE.md #15); its
    final summary prints the exact commands to type, and in isolated modes where to type them.
- **D9 Close rating uses AskUserQuestion.** Replace the Happy `<options>` block in commands/close.md
  (about :867-880) with a native AskUserQuestion. A dedicated section studies the agent scoring system
  (landscape/H-scoring.md).
  - **D9a Scope: keep only the owner's rating log (plan option S-B).** A hook records the native rating.
    Score injection into agent prompts, automatic score events, the agents' score echo contracts and their
    scripts and tests are deleted (their effect on behaviour was never measured).
  - **D9b The Stop gate requires the rating question to be asked, not answered.** Skip, no answer or a
    denial never blocks the session and records nothing.

## Git, remote and privacy

- **D1 Remote push is opt-in.** One switch, GIT_AUTO_PUSH, default off ('0' or unset means off). Every
  automatic push path (checkpoint push, post-commit auto-push, installers that default it on) obeys it.
  Local checkpoints stay. /push is the only normal route to a remote. Deleting the 255 refs already on
  the public origin (252 refs/backups/claude/*, 3 refs/checkpoints/*) is low priority and happens at the
  very end, with D16's single confirmation at that time.
- **D11 settings.json stays tracked, sanitized.** The tracked settings.json is the clean, public form.
  A git clean/smudge filter (declared in .gitattributes, registered locally by init) strips machine
  values on commit and restores them on checkout. Machine values live in an untracked
  settings.machine.json overlay (gitignored), with a tracked settings.machine.example.json. Init makes a
  fresh clone the user's own. A machine where the filter is not registered must not be able to commit
  personal values (fail closed).
- **D12 Personal values are never tracked.** Account names, emails, private project names, personal paths
  and the paseo account list leave code and docs. The owner's machine keeps full support through the
  overlay. The list of private literals used by any check stays local (untracked).
- **D13 paseo is an optional module.** Init lets the user choose modules. With paseo off, nothing paseo
  runs, nothing fails because paseo is missing, and the core harness is complete. The paseo commands stay
  in the repo for users who enable it.
- **D14 Public permissions = the owner's local allow list, minus personal-path entries.** curl, wget,
  docker run, docker exec and package.json edits are allowed (they are normal operations, not "ask").
  The owner does not want to curate fine-grained entries; pick the strongest coherent posture.
- **D17 Dead code and its tests are deleted, not quarantined (P8).** Code that no live entry point reaches is
  deleted together with the tests that exercise only that code. Live entry points: hooks registered in settings.json,
  commands, agents, skills, and scripts any of those run. This applies to the abandoned-cycle code and to tests that
  belong to another tool, such as the Codex tests. It is not feature retirement (D15), because nothing reachable is
  removed. Each deletion carries its reachability proof in the PR. A failing test of live code is never deleted or
  quarantined: the code or the test is fixed. No collect_ignore or skip list is used to make CI green.
- **D16 History cleanup at the end.** Emails and account names are removed from git history in the final
  phase (git filter-repo with a mailmap, replace-text and replace-message), followed by deleting the 255
  remote refs. This is destructive and runs only after every phase PR is merged. The owner's go-ahead is on record
  (2026-10-13) as its basis: "删除，告诉我怎么做", then "删除 git 历史里的邮箱和账号名：好"; for the refs "可以删，但是低priority" (quoted
  in prompts/P11.md, the D16 and D1 bullets). The record alone does not authorize running it: right before the
  irreversible step (history rewrite, force-push, remote ref deletion), the reviewer asks the owner once with
  AskUserQuestion and names the concrete effects. That single confirmation is the D23 pause, not an escape, and it is
  the one exception D18 keeps.
  No home is re-cloned or rewritten in place: a pre-push guard keeps old history off the remote (P11).
  [INFERRED: no owner quote asks for the confirmation (D18's quoted words name no exception; it is the reviewer's rule
  for the one step that cannot be undone) or for a re-clone (X4, X5, X8). Prove the pre-push guard before use with
  P11's acceptance 14 extended to /push of a new branch and a plain git push, on a pulled and an unpulled home.]

## Execution

- One session per phase, one branch and one PR per phase, PR base `master`.
- The reviewing session reviews and merges. Phase sessions never merge their own PR.
- Phase numbering follows PLAN-v2.md: P0-P11 (P5 = the unified Stop gate, P6 = producer input and
  identity, P7 = portable product, P8 = private tree and CI, P9 = prose pass, P10 = clean tree,
  P11 = remote refs and history cleanup). Wave 1 = P0 + P7. The later waves are in PLAN-v2.md.
- The policy choices listed as OPEN in PLAN-v2.md's decision ledger are no longer asked: they are decided by
  experiment under D18 when their phase reaches them.
- Every phase PR carries the D24 artifact table, measured, before review.

## Owner delegation (2026-10-18 / 2026-10-19)

- **D18 No more owner arbitration; decide by experiment.** The owner (2026-10-19): "我不会管以上你如何决定，我只想告诉你你必须
  研究后再做决定，你的研究是有实验的研究而不是空口无凭，只要是有实验的无论实验结果我都接受 ... 不要让我裁决任何事情了". Every remaining
  choice, product or technical, is made by the reviewer or the phase session from an experiment it ran (a sandbox run,
  a test, a measurement), recorded with its result in the PR's technical-choices table. No phase asks him anything.
  The quoted words name no exception. One named exception is kept: right before P11's irreversible publish (history
  rewrite, force-push, remote ref deletion), the reviewer asks the owner once with AskUserQuestion, naming the
  concrete effects (D16, D23). The go-ahead on record (D16) is its basis; the record alone does not authorize the run.
  [INFERRED: the owner's words do not contain this confirmation. It is the reviewer's rule for the one step that
  cannot be undone; no experiment decides it.]
- **D19 No owner machine step.** The owner (2026-10-18): "我不做，没空，我不能停止claude". No phase gives him a step on his
  machine or needs his sessions stopped; merged code lands on a live home by itself (P7b). Merged code reaches his
  homes only when he types /pull (answered 2026-10-19; no automatic pull is added).
- Answers recorded 2026-10-19: P7b also handles the other repositories (legacy auto-push hooks, stale fswatch).
  TC-47 (P8): BA may write docs/dev/observations-ledger.md (agents/ba.md makes BA its producer); BA may use WebSearch
  and WebFetch; browser roles keep playwright only (the owner prefers it).

## Planner text without an owner quote (status 2026-10-23)
- PLAN-v2 S1's exits beyond interrupt and /stop (a typed harness command, CLAUDE_COMMAND_GATE=off): planner proposal
  (COVERAGE.md:132, :284; HANDOVER.md:70-71).
- S2: superseded by D20. S9: planner default (landscape/G-stop-gates.md:283), kept as D2 applied by analogy.
- TC-5's producer-question file format and its overnight role: planner and decision-critic design (PLAN-v2.md,
  'Decision 7 (producer waiver)'); the idea is backed by O19/D23, the parking role is withdrawn (D20).
- D1's default-off auto-push: no owner quote for the default. The owner's backup answer of 2026-10-19,
  "默认我都会打开，关闭的情况是特例", was resolved by the planner alone (HANDOVER.md:87-89). Unchanged here; no phase presents a privacy
  measurement as an answer to it.
- Codex default: the records conflict (commit 2e0303a, opt-in, 2026-05-04; paseo-daemon-teachings:245
  "每一个command都要加codex"). Unchanged here.
