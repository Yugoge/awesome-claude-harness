Owner steps: none.

# Phase P1c: never fail: the pipeline replay suite
## Dependencies and start checks
- After P1b, before P2 and P3. Master d625284db59399568c50424ea3162175d982ae04 holds P0, P0b, P7, P1; P8 (hermetic conftest.py, green CI)
  and P7b (the landing R-N1 and R-V1 exercise) merged before P1b. Effort XL: per D26 the reviewer hands P1c out only as sub-phases; push
  after each commit. Wait for nothing else; work in parallel; never stop to ask.
- Start checks: `git fetch origin master`; `git merge-base --is-ancestor d625284 origin/master` succeeds; `git log --merges --first-parent
  --format='%h %s%n%b' d625284..origin/master` lists the merges of the PRs titled `P1b: …`, `P8: …`, `P7b: …` (P8 2acc29b `Merge pull
  request #6: P8, …`; P7b 301d696 `Merge pull request #7: P7b, …`; P1b `Merge pull request #<n>: P1b, …`, or `Merge pull request #<n> from
  <owner>/<branch>` with body line 1 `P1b: …`); `git show origin/master:conftest.py | grep -c CLAUDE_STATE_DIR` prints at least 1. On a
  failure stop; tell the reviewer in your session output (never the owner) that P1c starts only after P1b, P8 and P7b merge.
- `git log --oneline d625284..origin/master`; re-find every site (named at d625284 by file, function or text) and re-measure every "today"
  claim on your base, named in the PR; a defect P1b or P8 closed needs only its replay. New code: Python 3.10.
- Consumed as merged (use the merged name, say so; never a second one). P1b, as P1b merged it: the trace runner (T1-order replay: which
  actor wrote, read, probed, deleted which path); its ten compliant drivers (its acceptance 4), extended here; its D24 table format and
  check; its E1; its "Out of scope, found"; its "Hand-off to P1c" (kept base blocks with hook text and `DEVIATION:` step; base-text-only
  deviations; the dead ends of its acceptances 14, 21, each still shown fixed at its producer); its "Live landing" `# STUB:` scripts (left
  until P10); its one reader of CLI transcripts and agent meta (its row 18), called by every decider you add there (X8, R8, R10, R16, R17).
  Also P1's obligation.py and command_span.py, P8's conftest.py, baseline.yml, P7b's landing, the kit `harness-repair-plan/tools/`. The
  pilot's record (prompts/P1c.md, "What the pilot measured") is A4's "before" and X10's input. Shipped: G1-G4 advisory; armed: G1-G3 block.
## Goal
1. A replay suite in CI (tests/replay/) on P1b's runner, network-free and hermetic (HOME, CLAUDE_CONFIG_DIR, CLAUDE_STATE_DIR in tmp_path),
   proving D25 on every merge: (1) all ten pipelines run compliantly with 0 gate blocks and 0 hook errors and reach their terminal; (2)
   every injected fault's block names the artifact and failing check and goes back to its own producer (D21), and the next round passes with
   zero human action except HX; (3) no dead end: apart from the owner's /stop no state exists in which an agent cannot satisfy a gate (X6);
   (4) one regression replay per defect met: P1's fan-out wedge, E1, N1, V1-1/NV-1.
2. Each dead end, and each refusal not returned to its producer, is fixed at the producer side (R7-R20), never by a check at /close or
   /commit, a new state file, an owner question or parking. 3. From P1c on each phase merges only with the suite green and adds the fault
   replay for the process class it changes (R6). 4. Live landing: nothing new blocks a running session or in-flight cycle (A11).
## Owner rulings (the words are in DECISIONS.md and audit/2026-10-23/register.md; none is quoted here)
- D25 never fail (the suite and merge rule are its recorded measure, not owner words). CC4/D7: /close or /commit completes an unfinished
  cycle with dev's subagents. CC8: an agent repairs its own mistake. D2/DT2: QA fail is a step; dev's one terminal is completed. DT3: no
  failure outcome. DT4: no honest terminal (P9 rewrites Hook Discipline #5). HC2: fix in the harness, not by an agent obeying prose.
  2026-09-28 ruling (design doc in docs/reference/): detection at the producer's stop (G2), dispatch (G1), collection (G3); no re-check at
  consumers. C1 no new mutable state file; C2 no new check at /close or /commit; C3 strict failure-surface decrease; C4 the fault suite; C5
  a blocking gate returns the artifact to its own producer, subagents PAUSE-and-report hook rejections, no new human step on the success
  path, legitimate output keeps a route to completion.
- D18 open choices by experiment, nobody asked. D19 no owner machine step. D20 /dev-overnight never asks, parks or waits (after end_time
  too); experiment, else the preset default, recorded in "Decisions made without the owner" (P2). T0 overnight must not stop. D21 no
  filename-to-role table, no agent manual; a gap reports file, check, lane; the fixer comes from the declaring dispatch's obligation, else
  the canonical todo step (P1b's E3 reader). D22 /redev is /dev, fresh task id. D23 outside overnight an in-turn AskUserQuestion is the
  pause; neither asking nor answering releases a gate; exits: interrupt, /stop. D24 one producer, at least one deciding consumer
  (written-never-read deleted, read-never-written loses its read); D24 table in the PR. D15 nothing retired; a registered hook is never
  deleted in the change that unregisters it. D17 unreachable code goes with its proof; live tests are fixed, never skipped. D4c/SG6 no
  interrupt or API-error parsing; /restart resumes. D8 only the producer writes its artifact. Producer-side: fixes land on a producer (G2,
  G1, G3, a launcher, the writer, a prompt, CI); /close, /commit and the changelog-analyst gain no check (R14, R18 only change a producer
  operation or drop a refused step; X3 only deletes; routing loops only re-dispatch).
## Decided by experiment (D18; nobody is asked)
In the kit or the fixture (X3's env probe, X4's sub-measure in your session), never your container's `~/.claude` or HOME; rule fixed first;
setup, counts or exit codes, option, why and revert recorded in the PR (comments if long); result followed.
- X1 runner source. Import P1b's runner and ten drivers as merged, whatever its E1 chose; extend the drivers with the missing (1) scenarios;
  add faults, assertions, fixture (R1-R5); never a second set. A missing piece goes into P1b's module: hooks run as settings.json registers
  them; agent Read/Write/Edit and CLI transcript appends are synthetic events with their actor; optional `strace -f --seccomp-bpf`. Rule: no
  verdict of (1)-(4) depends on strace; it feeds only the D24 table, X2's audit and the coverage sets where the runner misses a file.
- X2 fixture outside the namespace. Per scenario on P8's conftest.py, under tmp_path: HOME `home`, CLAUDE_CONFIG_DIR `home/.claude` (the
  harness home: a clone of HEAD with a bare origin, landed as a live home: overlay settings.machine.json with CLAUDE_HOME the clone, TMPDIR
  and CLAUDE_CODE_TMPDIR `tmp`; `scripts/bootstrap --steps 3,4,5`, `scripts/install/land --state` prints `landed`), CLAUDE_STATE_DIR
  `state`, TMPDIR `tmp`, GIT_CONFIG_GLOBAL `gitconfig` (GIT_CONFIG_NOSYSTEM=1); `toyproj` cloned from a local bare origin; a venv at
  `~/.claude/venv` importing jsonschema and yaml (checked first); `GIT_ALLOW_PROTOCOL=file`; proxies at a guard counting each connection (a
  hook error). Experiment: compliant /dev 2-lane in the kit's namespace and in the fixture. Rule: the fixture if the per-event tables agree
  (hook, exit code, block text; ids, timestamps, paths normalized) and its traced run writes nothing outside tmp_path (devices aside);
  before merge a hook state file outside is routed through `harness_state_dir()` by its writer (unit test, A12 row), another write fixed in
  the fixture if a setting it controls moves it, else at its writer (honour TMPDIR); a table difference is a fixture defect.
- X3 G2 armed. Base sets `CLAUDE_OBLIGATION_STOPGATE` `block` (P1b E4): replays only, held to the rule; no settings change. Else, with R7,
  R8: every (1) scenario and A11's replay with it `block`; measure whether an env change reaches a running session. Rule: 0 G2 blocks on
  compliant scenarios and in-flight cycles -> set it in settings.json env (clean form, `render-settings check --staged` green) in the last
  commit (R9) (the PR tells P2: arm only G1, G3) and delete there each copy kept only because armed G2 alone stops its faults (listed; C2);
  if one goes, G2 reads its switch at run time as P1b's E4 describes unless already so or env changes reach live sessions. A false block is
  fixed at its producer side and re-run; no branch ships F1, F1q or F2 unreturned; the PR names each pre-merge-stop fault and the deleted
  copy that stopped it.
- X4 prose conflicts. Drivers follow prose literally (fenced blocks, templates, the canonical TodoWrite list, FIRST ACTION reads, stated
  defaults); a block so met is a process defect. (a) A written rule backs the refusal (CLAUDE.md, DECISIONS.md, the 2026-09-28 doc, a
  security hook's stated policy): keep the hook, change the prose to a form it accepts by design, never a wrapper, eval, hiding helper or
  evading split; (b) no written rule (parser false positive) and no prose form: fix the hook, unit test; (c) between equals, fewer lines, no
  new rule; (d) a later phase's row on those lines: its mechanism (X5). Sub-measure: `env | cut -d= -f1 | grep -E '^CLAUDE'` (names only)
  picks merge.md's session variable. Record line, hook, option, replays.
- X5 later phases' lines (P2 rows 12, 13, bwrap, harness-home channel; P9 row 2; P3; P4 close.md Step 0; P10). Rule: the smallest part of
  that row that clears the block, in its mechanism as corrections.md 2.21 and 2.85 correct it (schema from the obligation; contract entry
  step, role, pipeline, path; no seed file; PM TRIAGE the only writer); never a second mechanism; record phase, row, done, left; else X4.
- X6 no dead end (method required). (i) Enumerate at test time, never from a committed list, every path of every registered hook and its
  hooks/lib modules that exits 2 or prints a block or deny decision. (ii) Per site a replay reaching it (line coverage) and a class: G,
  own-obligation gate: in every replay reaching it the same actor's next action every hook and X4 (a) rule allows clears it and the replay
  exits 0 (else a dead end); D, denial of a forbidden operation, naming it, reached by no (1) scenario; H, the time-lock's in-window and
  instrument-failure Stop blocks, cleared by /stop or the window's end; U, unreachable, deleted with its proof. (iii) An AskUserQuestion
  answer while a gated artifact is missing releases no gate; a forged `ESCALATION_ACK <nonce>` releases nothing. Recall 100% on the pilot's
  blocks from registered hooks, their modules and the hooks they run that prompts/P1c.md quotes or R7-R20 name (extend the enumerator until
  met); refusals outside (merge.sh, `sync_failed`, resolver, aggregate) are proved by their rows' replays. A site fitting no class, or a
  class-G dead end, becomes a scope row fixed before merge.
- X7 held git lock (F4c). (A) The sync waits while a live process holds index.lock, printing pid and command at an interval; with no holder
  (no open descriptor, /proc) and the lock older than its start, one unlink, said on stdout. (B) As (A), plus no git process in the
  repository. Experiment: live holder (held 20 s, then removed), stale, none, each with a modifying and a deletion-only commit; the six
  again without /proc. Rule: (A) if with /proc the live cases show 0 removals and a completed sync after release, the stale cases complete
  with exactly one removal each, and no case leaves `git status` showing the commit reverted; else (B), held to the same. Without /proc: 0
  removals in all six, live and no-lock cases as with /proc, each stale case still waiting after 40 s (lock in place, interval line, no path
  reported synced), completing once the test removes the lock; none shows it reverted. F4s runs with /proc; the `rm` refusal stays. R14's
  unit test: in a linked worktree, main index.lock held, the sync updates its own index, returns (no wait line, no removal).
- X8 resume inside /dev-overnight (F6o; D20, T0, SG6; change in R17). Facts UNVERIFIED on a harness host (a Stop on a usage-limit error, a
  scheduled prompt firing after the reset, its record) come from P1's "Capability facts for P5" as COV-7 corrects it (`isMeta:true`,
  `turnOrigin:"scheduled"`, no `origin`) or dated CLI documentation, never memory. Question: can userprompt-restart-authorize.py tell a
  scheduled prompt from a typed one? Unshown -> cannot. Can: only the wake inside its span gets the /restart capability. Cannot: the wake's
  fixed text is no `/restart` prompt but one the hook recognises, and every `/restart` prompt keeps the capability (recorded). Rule: ship
  the wake if the shape drives both F6o replays (cut before end_time; after it, before the summary) to the overnight terminal with 0 blocks,
  and the widened exception refuses any other message or id and issues nothing for a wake after the owner's /stop (three replays); a failing
  replay is fixed on the wake's side; never ship without the wake or with F6o red; the Stop and firing facts decide nothing (typed /restart
  stays). The PR records UNVERIFIED facts and a shown inability to fire as CLI limits for P5, and an unwoken cut (or one in a pre-merge
  session) as still waiting for /restart, never as D20 met.
- X9 N1 (P7b's PR #7; reviews/P7b-PR-record.md). Before, on 1d10ae0 (scratch HOME, a bare origin one commit ahead): a landed home, a CLI
  `model` write, one Stop -> pull.sh exits 1, `safe_pull` returns 0, HEAD behind. After, on base: (i) the same -> both pulls reach upstream,
  `model` kept, nothing stashed; (ii) the write, then each pull before any Stop. Rule: (i) and (ii) hold -> replay only; (ii) refuses ->
  R20's re-record. Either way `safe_pull` judges each step by its git command and returns non-zero on a failed fetch, stash push or pull.
- X10 CI time and split (pilot estimate 3.5 h, 2.4 h with saved-state starts; UNVERIFIED). (a) Hooks of one event in parallel vs sequential:
  identical verdict tables for the 16 scenarios -> parallel. (b) Saved-state starts: F1, F2, F3b, F7 equal full replays -> every fault. (c)
  Each scenario's CI time (`nproc`) in your draft PR's runs. Rule: the whole suite, both modes, untraced, over at most 20 matrix jobs within
  20 minutes wall with setup -> every pull_request push runs it all. Else each push runs (1) and (4) both modes, (2) in the PR's mode, (3);
  the full set ((2) armed, the traced D24 run) on every pull_request event to master (opened, synchronize, reopened, `ready_for_review`; a
  newer push cancels the older run) and weekly. The full set is green on the PR head before merge (own event); no scenario in neither set.
## Scope rows (re-find every site on your base)
Delivered by P1b (verify each as P1b merged it, add its replay, change only what P1b left; not your deletion or retired rule): R7, R10's
obligation case, R12, R13, R19's seed and cycle id, R18's do.md, close.md, commit.md, merge.md, push.md, resolver and script-call sites,
changelog-analyst.md's and qa.md's agent calls, /dev-command's auto-detect and template, the /close and /commit routing loops (F8).
- R1 tests/replay/ (conftest.py, glue, P1b's drivers extended): X2's fixture; the 16 scenarios built as the CLI records them (P1's "Scenario
  drivers"; each dispatch carries its obligation and a UTC dispatched_at; a re-dispatch the same obligation template); chained scenarios
  from saved state. Modes `shipped` (checkout settings.json) and `armed` (CLAUDE_OBLIGATION_GATE, _STOPGATE, _BARRIER = block; _TERMINAL
  never). R2-R5 (new): test_pipelines.py (1), test_faults.py (2), test_regressions.py (4), both modes; test_no_dead_end.py (X6).
- R6 baseline.yml (or a workflow it calls); tests/TESTING.md: suite jobs per X10, reachable from release.yml; the comment's
  "already-required" and "gates merges" go; the `baseline` pytest step leaves tests/replay/ to the suite jobs; the merge rule's coverage
  step (code in tests/replay/); X2's network guard in each; one TESTING.md section (how to run, the merge rule).
- R7 hooks/subagentstop-artifact-contract-enforce.py (G2; F2g): a failing obligation stop is a plain exit 2 naming each failing artifact and
  check to the stopping producer, every round; delete what remains of the no-progress hand-off, `ESCALATION_ACK` admission and four stores
  (escalations/, escalation-admissions/, progress/, deferred-checks/), each once grep and trace show no other reader; `GATE_FAULT` never
  admits. R8 same file (F7b): with no obligation block, judge only reports the stopping agent wrote (per its transcript), not a sibling's.
- R9 settings.json env (X3, only if absent): STOPGATE `block` in the last commit with the shipped replays depending on it (F1, F1q, F2, F2j,
  F2g), X3's deletions and run-time read, one revertible unit; later ones keep them, re-run A3, A4, A11; nothing else in settings.json.
- R10 hooks/subagentstop-e2e-enforce.py (F1q, F3b): an obligation-bearing QA is judged on exactly its declared qa-report path, any session
  id format; without one, only a report it wrote; newest-filename and "last 5" correlation go; the message names path and missing field;
  keep P1b's split (G2: existence, shape; here: e2e status).
- R11 scripts/aggregate-dev-report.py (F2, F2g): a shard failure writes no canonical, removes the task's earlier one, exits non-zero naming
  each failing shard and error (no "blocked" canonical); shards accept only dev-report.v2's statuses. R12 resolve-dev-artifact-chain.py;
  dev.md (dev-command.md's copy): fan-out cycles stop reading the undeclared unsuffixed parent ticket, context, qa-report (F3b).
- R13 posttool-overnight-file-check.py; dev-overnight.md (F3a, F3q; X5): schema from the dispatch's obligation; contract entry step, role,
  pipeline, path only; the message names artifact and check, no "escalate". R14 scripts/lib/session_index.py; scripts/session-index.py;
  changelog-analyst.md's sync step (no analyst prose; F4c): X7's option on both update-index calls; nothing reported synced unless written.
- R15 commands/restart.md (its three `$HOME/.claude/...` commands; F5, F6): the `~/.claude/...` form bash-safety resolves (X4 (a)). R16
  pretool-todo-validate.py; posttool-subagent-track.py (Gate 4; F5, F5f): a subagent step is also met by an Agent call of that role in the
  span whose agent the recovery resumed and finalized (its journal record); no replacement call; the message names step, role, artifact.
- R17 (X8; F6o): scripts/todo/dev-overnight.py's first step "schedule the wake", one recurring prompt with fixed text from launch to session
  end (after end_time too) unless /stop ends it; pretool-todo-validate.py completes it only after a recurring CronCreate of that text in the
  span; prompt-workflow.py recognises a fired wake (non-human origin, else its text) only in an open /dev-overnight span and starts
  restart.md's recovery; userprompt-restart-authorize.py (whose reader in subagent_restart.py stays the one deciding rule) widens the
  /restart capability (the SendMessage exception) to the wake inside its span, same message and id rule, never after /stop; dev-overnight.md
  gains the wake step, and its session-ending last step and stop.md's last step are a CronDelete of the wake's id;
  stop-overnight-timelock.py, after its closeout check, refuses a Stop after end_time (after /stop or any later span too) while the
  transcript's wake CronCreate has no later CronDelete, naming the id; a transcript without one meets nothing new. Drivers end the schedule
  by CronDelete and run two wake intervals past the terminal; X8's /stop replay (overnight, /stop typed in the window; in test_pipelines.py,
  outside its table) runs past stop.md's CronDelete and drives no Stop after it. Base steps keep label, content, activeForm; every hook
  comparing todo lists (Gate 4, posttool-subagent-track.py, posttool-todo-count.py, posttool-todo-tracker.py, pretool-workflow-gate.py)
  compares the whole list only at a command's first TodoWrite or a length change, else pairs by content, never index.
- R18 prose conflicts, each on X4's side with its replay; R19 the smallest part of the owning row (X5) taking the compliant overnight
  scenario from launch to a Stop after end_time with 0 blocks. Each kept base block in P1b's hand-off is R18 or R19: remove it with its
  replay and drop its `DEVIATION:` in that commit (gone on base: replay only), as each base-text-only deviation; none, nor a skip, at merge.
  - R18 (pilot; re-verify): dev.md's graphify skip vs Gate 4; the 5-Bash streak vs dev.md Steps 14-17 and recovery steps; spec-update.md's
    Write over a file vs pretool-write-guard.sh; changelog-analyst.md's `rm -f "${MSGFILE}"` vs the removal policy; do.md Step 5's template
    without `expected_absent`; close.md's AGGREGATE_RESULT and RESOLVED_JSON blocks (dynamic head); merge.md's CLAUDE_SESSION_ID binding,
    `rm -f <grant>`, merge.sh's untracked-file refusal; push.md Step 1's `find` (push.sh validates the token).
  - R18 /dev-command: auto-detect picks doc-sync's specs INDEX.md (P9 row 2); the Step 16 template fails the resolver;
    pretool-claude-config-guard.py refuses the dev's command-file write (X4 (b): only a dev whose obligation lies in a human-typed
    /dev-command span may write only `<project>/.claude/commands/*.md`; a replay shows every other refusal unchanged). Repository-relative
    script paths (X5, P2's channel) in dev.md, dev-command.md, commit.md, close.md Step 0 and changelog-analyst.md, respelled together.
  - R19 (trace B; re-verify): create-overnight-state.sh's empty cycle contract (P1b E13); dev-overnight.md's Step 1 block
    (`census_fatal:unbalanced:single_quote`; `OVERNIGHT MAIN-ROOT BLOCK`); `OVERNIGHT SUBPROCESS GIT BLOCK` in place; `OVERNIGHT
    WRITE-BOUNDARY FAIL-CLOSED` without bubblewrap (P2's bwrap: install it in CI and your container if allowed, else a stand-in as P8's
    bwrap argv tests; say which); E1 (R13); the e2e QA stop under the overnight id (R10); `CLOSEOUT GATE` (P1b row 13); the cycle-id
    disagreement (`cycle_index(state)`). The fixture launches from a clone, default mode.
- R20 hooks/pull.sh (`HAS_CHANGES`); git-fswatch.sh (`has_changes`, `safe_pull`); land's "Review N1" block only to make it callable (X9): if
  (ii) refuses, on a landed harness home the existing settings.json re-record runs before the stash decision (no second implementation, no
  new state); always, each `safe_pull` step judged by its git command, not `tee`. R21 tests pinning R7-R20 change in the same commit
  (TC-54); a test of only deleted code goes, named (D17); a line a claims check names that you made false is fixed.
## The suite
- Gate block: any hook exit 2, or a block or deny decision on stdout, from any registered hook. Hook error: an exit other than 0 and 2, a
  Python traceback on stderr, a hook timeout, `GATE_ERROR` or `GATE_FAULT` text, or a network attempt caught by X2's guard.
- Expected producer: the agent whose Agent tool_use carried the obligation declaring that path (role, lane, agent id via the `.meta.json`
  toolUseId); for an artifact no dispatch declares, the actor the command's canonical todo step (scripts/todo/<command>.py) names; from the
  replay's own transcripts, never a table. /merge and /push (no todo script or obligation at d625284) use P1b's E3 fallback declarations; an
  artifact still with neither source is a scope row, declared at its producer's dispatch.
- Next round: a SubagentStop block, the same agent's next stop (stop_hook_active true); a G1 or G3 block, the declaring dispatch's
  re-dispatch (same subagent_type, task_id, lane, obligation template, fresh dispatched_at); a Bash denial, the next compliant one; an F8
  gap, the loop's re-dispatch.
- Human event: a UserPromptSubmit whose record stop_contract.is_human_prompt accepts, an AskUserQuestion answer, or a file action or command
  whose actor (X1) is none of: an agent, a hook or a process either starts, the CLI's own writes (transcript records, `.meta.json`), the
  fault's injection as its (2) bullet names it (a live lock holder's release included). X8's wake is none (`turnOrigin` "scheduled").
- HX: the one /restart the human types in F5, F5f and F6 and the /close or /commit the human types in each F8 fault: a session the owner
  interrupted (their exit, D23), or one a usage limit cut outside /dev-overnight, resumes with their /restart (D22, human-only by design:
  `disable-model-invocation: true`, the `Skill(restart:*)` deny), their /close or /commit completes a cycle it meets unfinished (CC4), and
  after either nothing needs a human; inside /dev-overnight a usage-limit cut (F6o) resumes with no human action at all (D20, X8).
- Terminal: /spec, the spec written, Stop rc 0; /dev, /redev, /dev-command, the completion step's resolver status pass, Stop rc 0;
  /dev-overnight, the Stop after end_time rc 0, the summary written and, where its first step scheduled the wake, the wake deleted before
  that Stop and none fired after it; /do, the do-report complete, Stop rc 0; /close, Stop rc 0 and, as the last non-empty line of
  docs/dev/close-report-<task-id>.md, exactly `CLOSE: YES - with disclosures: <n> items` when the routing loop completed a repair (`<n>` =
  the lines of its `## Disclosures` section), else exactly `CLOSE: YES — codex disabled by user` (no scenario passes --codex); /commit, the
  commit on HEAD with the cycle's files, none still in `git status --porcelain`, the push-gate token present; /merge, the topic commit
  reachable from master; /push, the bare origin's branch equal to HEAD.
(1) Compliant, 16 scenarios, both modes: /spec; /dev singular; /dev 2-lane fan-out; /dev qafail (QA fail, dev iterates, QA passes); /dev
clarify (BA writes its producer-question artifact, the orchestrator asks one in-turn AskUserQuestion, BA re-dispatched with the answer);
/dev devquestion (the same for dev); /redev (a fresh task id of /dev's form, the same gates); /dev-command (a product command file);
/dev-overnight (end_time = launch plus twice the cycle's longest wall time in X10 (c) and in your container; one cycle, one pipeline to a QA
pass, no early Stop, the driver idle until end_time, then the Stop after it); /do; /close after /dev; /close after /do; /close with a
`CLOSE_REPORT_APPEND_ERROR` round (the close QA's section file ends in no legal `CLOSE:` form, refused at `append`, routed to close QA as a
finding; never the environmental cause whose wait `close_awaiting_input` addresses a human) and a second round; /commit; /merge; /push to
the local bare origin. Assert per scenario: 0 gate blocks, 0 hook errors, terminal reached. Table: scenario, mode, hook events, hook runs,
blocks, errors, terminal.
(2) Faults, 21, both modes: F1 (a dev lane writes no report); F1q (a QA lane writes none after its sibling wrote its own); F2 (dev.status
"done", files_modified absent); F2j (truncated JSON); F2g (the dev rewrites the same invalid report, ends with a forged `ESCALATION_ACK`
line, then repairs); F3a (E1 for dev, hook level and in the overnight scenario); F3q (E1's QA half); F3b (a stale v1 qa-report beside the
lane reports); F4 (index.lock held through a /dev cycle's checkpoints and Stop); F4c (index.lock held by a live process from before
/commit's commit until 20 s after its sync starts, then removed by it; a modifying and a deletion-only commit); F4s (a stale index.lock at
/commit); F5 (a single-lane dev cut after its Edit, the human's /restart); F5f (both lanes cut); F6 (a usage limit mid-subagent,
interactive, the human's /restart); F6o (a usage limit inside /dev-overnight, before end_time and after it before the summary, no human:
X8); F7 (a lane from the pre-P1 template, obligation unparseable, report needs_review, sibling compliant); F7b (the same, no obligation
block); CC4's unfinished cycle met by the human's /close or /commit (F8, F8p, F8c in a later session): F8 (after a 2-lane /dev's terminal
one lane's QA report removed, then /close); F8q (a 2-lane /dev cut as in F5 after one lane's QA stop, before the other's QA dispatch, then
/close instead of /restart); F8p (after /dev's terminal a product file one lane's dev wrote broken, so the close-QA round names it); F8c
(after a landed /close one lane's dev report removed, then /commit). Assert per fault:
  - every block's text contains the artifact's path (the one its dispatch declares; F7, F7b: the report the stopping agent wrote) and the
    failing check (code and message); no hook error;
  - the receiving actor is the expected producer, the trace shows the repair written by that same agent (G1/G3: by the declaring dispatch's
    re-dispatch; F8: by the dispatch below), the next round passes, the pipeline reaches its terminal, and 0 human events occur between
    injection and terminal except HX;
  - F4: 0 blocks, the checkpoint ref advances; F4c, F4s: `git status --porcelain` after /commit lists none of the committed paths; F2g: the
    forged line admits nothing;
  - F8 faults (no hook block): the gap names the artifact's path and failing check, no producer role; /close (F8c: /commit) finds it by its
    one chain-function call (no check added), F8p by its close-QA round; the routing loop re-dispatches the dispatch P1b's E3 reader returns
    for that path (same subagent_type, task_id, lane, obligation template, fresh dispatched_at); F8q: for the lane QA report no dispatch
    declared, a fresh dispatch of the role of the canonical todo step the reader returns, same task id, each step still lacking run by its
    expected producer; F8p: the dev dispatch P1b's E6 producer records as the file's writer re-dispatched, then a fresh close-QA round; the
    close report ends in /close's Terminal form and F8c's commit lands.
  Table: fault, mode, blocking hook, artifact named, check named, receiving actor = expected producer, rounds to pass, human events.
(3) No dead end: X6. (4) Regressions, each reproduced on a "before" tree, recorded in the PR:
- R-P1 (fan-out wedge): F7 and F7b's shapes plus the compliant sibling's stop in the same round. Before: on the first parent of P1's merge
  (f8c18c2 if nothing between) the sibling's stop is blocked by the other lane's report (if not reproducible, reproduce the wedge as P1's PR
  and review describe it, say so); on your base before R8, F7b still wedges.
- R-E1: F3a and F3q. Before: on the first parent of P1b's merge, or your base before R13 if it still declares v1: the template-following v2
  report is blocked by the collection check; only the dual-shape report passes.
- R-N1: X9's (i) and (ii), by hooks/pull.sh and by `safe_pull`, and `safe_pull` with a failing fetch and a failing pull (non-zero). Before:
  on 1d10ae0 pull.sh exits 1, `safe_pull` returns 0, HEAD behind after the Stop; (ii) and the failing steps also on your base before R20.
- R-V1 (96bcb8f, 921b512, their tests): a landed home whose pull left settings.json unmerged (NV-1: doc-sync's CLAUDE.md or INDEX.md, alone
  or with settings.json); with index.lock held, the Stop's relayed notice names each refused path (`... still conflicted: git refused its
  repair, tried again at the next turn end`) and logs/landing.log says `result=repair-refused`; after release the next Stop repairs every
  such path (`result=repaired`, nothing unmerged). Before (no notice, `result=repaired`): V1-1 on 26a7ea7, NV-1 on 96bcb8f; F4c is not V1-1.
## Merge rule from P1c on
- Every phase PR merges only when the suite's full set (X10) is green on its head, and its PR body pastes the summary tables of (1)-(4).
- Every phase PR adds the fault replay for the process class it changes, derived, not listed: a CI step reads the suite's traces and
  computes, for each fault replay of (2) and regression replay of (4), the files on its path from start to end (with saved-state starts, the
  compliant run up to the injection counts): hook files run; scripts the hooks or the replay's own commands start (a driven agent's Bash
  command; a direct call such as R-N1's pull.sh and `safe_pull`); modules they import or source; files its processes open (schema, policy,
  data file); command and agent templates the drivers extracted; and the settings.json keys it used (each hooks entry whose command it ran,
  each other key a file on the path reads by name).
- It sorts each file the PR adds or modifies outside settings.json, commands/ and agents/, read at test time from the files and the traced
  run, never a list. A file under a directory named tests is a test. Any other file a replayed process can run or read is in the runtime
  set: a file a settings.json hooks entry runs; a script (`.py`, `.sh`, or first line `#!`) a reached command or agent definition names by
  path; a module a set file imports, and a file one sources or runs by a path or module name naming it (comments and messages aside); a file
  a replay of (1), (2) or (4) runs, imports, sources or opens in any process it starts (a git command's reads of its own working tree
  aside). Comment-only: Python, the same syntax tree once docstrings are dropped; shell, the same lines once blank lines and comment lines
  after the first are dropped.
- It fails when a runtime-set file the PR adds or changes beyond comments, or a settings.json key it adds or modifies (key by key), lies on
  no such replay's path, printing them. A changed key that registers no hook and that no runtime-set file reads by name is printed as a fact
  (CLI-only), not a failure. It prints as facts each comment-only runtime-set change and, with its class, each changed file outside the set:
  test; CI-only (a .github/ file or a script a `run:` step there runs); or used by no replayed process (e.g. INDEX.md).
- A commands/ or agents/ file the PR adds or modifies that opens with YAML frontmatter on the base or the head and that a replayed pipeline
  reaches must be read by a replay of (1), (2) or (4) (a driver extracts a template from it, or a scenario injects its body as a slash
  command's isMeta body); else the step fails and prints it, and the PR adds the scenario. A replayed pipeline reaches each command whose
  body a replay injects and each agent such a body names by agents/ path, as subagent_type, as an obligation's role or in a code span
  holding only its name, read from those bodies at test time, never a list, so an agent dispatched only on a skipped branch counts. Other
  changed files there are printed as facts (an unreached definition; a file without frontmatter on either side). The step reads no PR-body
  reason. Deletions are exempt.
- A phase that changes a pipeline's shape updates that pipeline's scenarios in the same commit (TC-54) and keeps every assertion of (1)-(4).
## Acceptance tests (each command and output goes in the PR)
Setup: "before" trees are scratch clones in the kit (`"$T/sb-setup.sh" <tree>`, hooks via `"$T/ns.sh"`,
`T="$SCRATCH/plan/harness-repair-plan/tools"`); the suite runs in A2's 3.12 venv; never your `~/.claude` or HOME.
- A1 the start checks and their output.
- A2 green means both: (a) the pull_request run on your head is green in every job, P1b's D24 check (no exception, no allowlist) and the
  suite jobs included; (b) locally on base and branch every `run:` step of baseline.yml exits 0 on python 3.12, P1b's check and (on your
  branch) the suite jobs included (as root "Clean-install smoke" takes (a)'s verdict; unshallow first, else "Verify headline claims" does).
- A3 `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/replay/test_pipelines.py` -> passed; table: 0 blocks, 0
  errors, every terminal reached, both modes; for /dev-overnight, F6o and X8's /stop replay, 0 wakes fired while the modeled clock runs two
  wake intervals past the terminal (/stop replay: past its CronDelete). Base before changes: the refusals R18 and R19 fix, with hook text,
  P1b's hand-off items (both lists) among them. Head: `git grep -n 'DEVIATION:'` prints nothing; P1b's check passes, no exception.
- A4 the same for tests/replay/test_faults.py and the fault table: for every block and every gap an F8 fault routes, artifact named, check
  named, receiving actor = expected producer, the first compliant repair round passes (F2g: after its forged round), 0 human events except
  HX. Base before changes: the "before" table against the pilot's, every difference explained.
- A5 tests/replay/test_no_dead_end.py -> passed; site counts per hook and class; recall 100% on the observed blocks; every G site's clearing
  replay exits 0; no (1) scenario reaches a D site; H sites listed; every U site deleted with its reachability proof; the
  AskUserQuestion-answer and forged-ESCALATION_ACK replays release nothing. Base before: the same output, each dead end listed (a G state no
  allowed action clears, a site fitting no class), C3's "before".
- A6 tests/replay/test_regressions.py -> passed; each "before" pasted (R-P1 before P1's merge and on base before R8; R-E1 on P1b's merge's
  first parent or base before R13; R-N1 on 1d10ae0, (ii) and failing steps on base before R20; R-V1 on 26a7ea7 and 96bcb8f).
- A7 X2's comparison table; the fixture home's `scripts/install/land --state` prints `landed`; write audit: nothing outside tmp_path (each
  found, with its X2 fix); network guard count 0; your checkout's `git status --porcelain` empty after the suite; no path under your
  container's `~/.claude` or HOME in the traced run's write list.
- A8 the merge rule's step on your diff: every runtime-set file you changed beyond comments and every settings.json key you changed lies on
  a fault or regression replay's path (git-fswatch.sh via R-N1, session-index.py via F4c's sync, R9's key via G2 on F1, F1q, F2); every
  reached definition you changed is read by a replay; every other file printed with its class.
- A9 X10: each scenario's CI wall time, totals, `nproc`, shard wall time, (a) and (b)'s results, the split.
- A10 unit tests per changed behaviour of R7, R8, R10-R14, R16-R20 (e.g. `ESCALATION_ACK` admits nothing; declared path beside a stale file;
  no canonical on a shard failure; live, stale, no lock; Gate 4 after a resume; the config guard's narrow case) -> passed.
- A11 live landing (D15), as a pre-merge session (base settings.json, your hooks): compliant /dev Stops in the toy repository and the
  harness home exit 0 in every Stop hook. Two cycles on base files through the first TodoWrite and its hooks, then on yours from the next
  event: (a) /dev with records of its own earlier no-progress round on disk (d625284's G2, `CLAUDE_OBLIGATION_STOPGATE=block`): no hook
  exits 2 on a compliant stop, old records ignored; (b) /dev-overnight through its next todo reset to its Stop after end_time. Base drivers
  (P1b's): no exit 2, block or deny on any event that the same replay on base files does not show at the same hook, step (same-content todo)
  and refusal text, or hook and step where a row rewrites the message; each listed with hook text, none new. With STOPGATE=block: 0 G2
  blocks on compliant stops; if X3 deleted copies, G2 blocks each fault they stopped (with and without CLAUDE_HOME; your branch's env if X3
  saw env changes reach running sessions) at its producer, naming artifact and check, next round passing; again with your settings.json.
- A12 D24 table (producers before -> after, deciding consumers before -> after, proof: writer and reader grep plus the suite's trace) for
  every artifact R7-R20 or X2 touch (escalation stores, aggregate, lane reports and e2e correlation, cycle contract, git index, recovery
  journal, /restart capability, fan-out parents, todo list (with bookmark and todo file where written), CLI transcripts and agent meta, wake
  records, command files, settings.json, moved state files).
- A13 C1: file-name patterns hooks and scripts create in the suite, base vs branch: no new state file (a branch-only pattern named with its
  writer and the base line already writing it). C2: every hunk in close.md, commit.md, changelog-analyst.md with why it adds no check. C3:
  dead ends and unreturned blocks before -> after from A4, A5 (target 0). C4: the fault suite. C5: A4's receiving-actor column.
- A14 rules added (expected at most 4: merge rule and coverage step; the wake and widened exception; R18's config-guard allowance; STOPGATE
  if R9) and retired (at least 4 beyond P1b's, e.g. R7, R8, R10-R13, R16, R19's empty contract, each refused prose step), as done.
- A15 `git diff --numstat origin/master -- hooks scripts schemas ':!hooks/tests' ':!scripts/install/tests'`: net (added minus deleted) <=
  +150, per scope row.
- A16 `scripts/check-public-core.sh` passes; `git diff origin/master` adds no e-mail address, account name, private project name or personal
  home path (placeholders such as `20990101-000001` and a stand-in .invalid address).
- A17 in A2's venv (`python3 -m pip install --require-hashes -r requirements/py312.txt`), `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p
  no:cacheprovider` -> 0 failed, P1b's D24 check included, at every commit (TC-54); CI green.
## Net code cap and DO NOT
- Net code cap: hooks/, scripts/, schemas/ (tests excluded), added minus deleted against your base, <= +150; what your base keeps of P1b's
  deletions is deleted under R7, R19 and counts; X7, X8 never decided by the cap; tests/replay/ outside it, size reported. Each commit keeps
  the suite green; a fix and its replay revert together.
- No mutable state file, counter, flag, release token, retry bound or self-release (C1); no check, scan or filter in /close, /commit, the
  changelog-analyst or any consumer (C2); never ask the owner, write a REQUEST, give a machine step, park, or make an overnight path wait
  (D18-D20); no filename-to-role table, owner or fix field (D21); no skip, xfail, quarantine, retry-until-green, expected failure,
  timing-dependent assertion or test passing on a red scenario.
- No weakened security denial (removal, git privilege, branch firewall, overnight, config guards) except under X4 (b) with a replay of its
  other refusals, and X8's SendMessage exception. Do not arm G1, G3, G4, unregister or delete a registered hook, or edit CLAUDE.md,
  DECISIONS.md, `harness-repair-plan/`. No network in tests (D1); nothing against your `~/.claude` or HOME; no nested `claude`; no committed
  captures or personal values; no API-error or interrupt parsing (D4c).
- No resolver, aggregator or overnight-loop change beyond R11-R13, R17, R19, X3, X6. Not here: arming (P2, P5); P2's deny and summary;
  disposition and gaps (P3); /close and /commit beyond R14, R18, X3's deletions, the routing loops (P4); the Stop gate (P5); prose (P9) and
  hygiene (P10) beyond X4, X5; D24 consolidation beyond R7-R20 (no second producer or deciding rule).
## Pull request
Title `P1c: <short goal>`; CI means green (A2, A17). Body only: `Owner steps: none.` first; a summary (base, scenario counts, the summary
tables of (1)-(4), A9's times); each acceptance test's command and output (past 60,000 UTF-8 bytes in PR comments, linked, never in the
repository); the choices decided by experiment, one line each (X1-X10, X5's parts, others), details in comments; the D24 table (A12); "Out
of scope, found" (two producers or deciding consumers of one artifact P1b's check passes; each modeled CLI behaviour with its source; pilot
non-blocking findings your base still shows).
Read prompts/_common.md; this file overrides it where they differ
