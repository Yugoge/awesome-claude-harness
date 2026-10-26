Owner steps: none.

# Phase P1c: never fail: the pipeline replay suite

You are implementing phase P1c of the harness repair plan in this repository (the GitHub repository this session
cloned). Phase id for the PR title: `P1c` (for example `P1c: never fail, the pipeline replay suite`).

**Wave 2c: right after P1b (wave 2b), before P2 and P3.** P1b (one producer and at least one consumer per artifact, D24)
ships the artifact ledger check and its runtime trace runner. You build the owner's "never fail" requirement on that
runner as a CI replay suite, and you fix at the producer side every process defect the suite finds today. P2 (run in any
repo, overnight start and end, arming) and P3 (one disposition function) start only after you merge. From then on they,
and every later phase, merge only with your suite green and add the fault replay for the process they change ("Merge
rule from P1c on" below). P0, P0b, P7 and P1 are merged as master d625284db59399568c50424ea3162175d982ae04, the revision
every file:line below refers to unless it names another. P8 (private tree, one privacy engine, green hermetic CI) and
P7b (zero-touch landing of P7 on live homes) merge before P1b. You need both: P8's hermetic conftest.py and green CI are
the floor the suite runs on, and P7b's landing is what the N1 and V1-1/NV-1 regression replays exercise.

Do not wait for anything except the merges above; run independent experiments and scenario runs in parallel; never
stop to ask.

**No owner step and no owner question (D18, D19).** The owner runs nothing on his machine and cannot stop his
sessions (2026-10-18: "我不做，没空，我不能停止claude"). He accepts any experiment-backed decision and arbitrates
nothing (2026-10-19: "只要是有实验的无论实验结果我都接受 ... 不要让我裁决任何事情了"). Every open choice below is a
"Decided by experiment" block whose rule is fixed before you run it. Your merge reaches his live harness while its
sessions keep running with the hook list they loaded (D15), so every hook change must land safely on them (acceptance
11). The rollback is the reviewer's revert, never an owner action.

**Before you start.**
- `git fetch origin master`, then `git merge-base --is-ancestor d625284db59399568c50424ea3162175d982ae04 origin/master`
  must succeed.
- `git log --merges --first-parent --format='%h %s%n%b' d625284..origin/master` must list the merges of the pull
  requests titled `P1b: …`, `P8: …` and `P7b: …`. git log prints the merge commit's message, not the pull request's
  title. P8's and P7b's subjects are `Merge pull request #6: P8, private tree, one privacy engine, green hermetic CI`
  (2acc29b) and `Merge pull request #7: P7b, a live home lands P7 by itself` (301d696). P1b's merge is one more, in
  either form master's merges take: the subject `Merge pull request #<n>: P1b, …`, or the subject
  `Merge pull request #<n> from <owner>/<branch>` with the body's first line `P1b: …` (the pull request's title; so
  d625284 records P1's merge). 2acc29b has no such merge, so this check fails until P1b is merged.
  P8's product: `git show origin/master:conftest.py | grep -c CLAUDE_STATE_DIR` prints at least 1 (its hermetic root).
- If a check fails, stop and tell the reviewer in your session output (do not ask the owner) that P1c starts only after
  P1b, P8 and P7b are merged. Do not start from an older base.
- Then `git log --oneline d625284..origin/master` tells you what else merged. Every location below is given at d625284
  with its function name, heading or quoted text: find each site again on your base and say in the PR which base you
  measured against. P8 deleted unreachable files (D17) and P1b changed producers, so re-measure every "today" claim on
  your base before you fix it. A defect P1b or P8 already closed needs only its replay.

**Interfaces you consume.** Read each on your base and in its merged PR (read-only) and use it as merged; do not build
a second one. If a name or form differs from this description, use what is merged and say so in the PR.
- P1b: its trace runner (the committed module that replays a pipeline in T1 order and records which actor wrote, read,
  probed or deleted which path), its ten compliant pipeline drivers (P1b acceptance 4; you extend them, never a second
  set), its D24 table format, its experiment that chose runtime tracing or static derivation (X1 below), its "Out of
  scope, found" items that name a process defect, and its "Hand-off to P1c" list: each base block its compliant drivers
  still meet, with the hook text and the driver's `DEVIATION:` step that passes it. Rows 18 and 19 remove each block,
  and the commit that removes it drops its DEVIATION (X4). The same list names the dead ends P1b met on its base (its
  acceptance 14): each one your base still shows is fixed at its producer with the replay that meets it (Goal 2).
- P1: hooks/lib/obligation.py (parse_obligation, resolve_own_obligation, find_unresolved_dispatch_obligations,
  canonical_task_id, registry_dir_for); hooks/lib/stop_contract.py and hooks/lib/command_span.py (is_human_prompt,
  active_command, active_span); the producer-question artifact; the Stop coordinator's relay; P1's PR section
  "Capability facts for P5" (the transcript record shapes it captured; X8 needs them).
- P8: the root conftest.py hermetic root (HOME, CLAUDE_CONFIG_DIR, CLAUDE_STATE_DIR, CLAUDE_PYTHON_BIN and
  CLAUDE_PROTECTED_RUNTIME_FILE set at import; CLAUDE_PROJECT_DIR, CLAUDE_HOME and the other runner pointers removed);
  .github/workflows/baseline.yml (pull_request, push, workflow_call from release.yml, the weekly schedule,
  workflow_dispatch; python 3.10-3.12; hash-locked requirements); its D17 deletions.
- P7b: the landing behind hooks/auto-commit.sh (its R2 repair of a conflicted stash pop, its busy-repository wait and
  notice, its lock) and the pull-path scenario scripts its PR describes (not in the repository: rebuild what you need
  under your scratch).
- The planning kit, `harness-repair-plan/tools/` (baseline.py with Session, ev and tool in T1 order; runhook.py;
  sb-setup.sh; ns.sh; reset.sh; proto/txbuild.py): the reference you port from where P1b's runner lacks a piece.

**What the pilot measured (the evidence of today's behaviour).** On 2026-10-24 the reviewing workflow replayed, in
sandboxes built from d625284 with the planning kit, all ten pipelines compliantly (/dev-overnight only up to its first
dispatch, plus a what-if) and seven injected faults through full /dev cycles. Its drivers and logs are not in the
repository or the planning branch, so this section is the record; build the scenarios P1b's drivers lack from it and
from P1's "Scenario drivers". "Shipped" means today's settings (G1, G2, G3 and G4 advisory by default in code); "armed"
means P1's sandbox arming (G1-G3 block, G4 advisory), P2's target.
- **Compliant /dev, 2 lanes, 17 steps, T1:** 0 blocks and 0 hook errors in both modes (shipped: 243 hook events, 1965
  hook runs; armed: 241 and 1945). A full fault replay took 150-252 s wall untraced (control: 203 s). Across all 29 fault
  runs there was no hook error.
- **Trace A** (one session: /dev 2-lane, /close, /commit, /do, /close of the do-report, /redev): 0 blocks, 0 hook
  errors; 700 hook events, 5782 hook runs of 73 hooks, 106 Bash commands, 26 dispatches; 637.6 s untraced, 1034.9 s
  under `strace -f --seccomp-bpf` (x1.62; plain ptrace about x3.1). The compliant driver had to step around five
  conflicts between the prose and the hooks (row 18).
- **Trace B** (/spec, /dev-command, /close, /commit, /merge, /push, /dev-overnight start): 9 refusals on the compliant
  replay and 13 on an overnight what-if, 0 hook errors; 451.4 s untraced, 632.6 s traced (x1.40); the overnight what-if
  159.5 s untraced. /dev-overnight's first cycle is a dead end (row 19). /dev-command cannot write the command file it
  exists to develop (row 18).
- **Faults:**

| Fault | Today (shipped) | Verdict today | Armed |
|---|---|---|---|
| F1 a dev lane's report missing at its stop | no block. G2 only logs `obligation_verify_fail`; the gap is caught only if the orchestrator follows dev.md's Step 12 prose; without it the Step 17 resolver fails on the canonical aggregate, not on dev(l1) | not returned to its producer | G2 names the exact path ("obligation-named artifact absent"), the same dev repairs, round 2 passes |
| F1q a QA lane's report missing after the sibling wrote its own | the e2e gate passes the lane on the sibling's file (newest filename containing the session timestamp, subagentstop-e2e-enforce.py:120-137) | not returned | G2 blocks with the path |
| F2 a schema-invalid dev report (F2j: truncated JSON) | no block at the stop. The aggregate script fails and writes a canonical report with dev.status "blocked", which dev-report.v2 forbids | not returned | G2 lists every schema error, round 2 passes |
| F2g the producer does not repair | (armed) G2's no-progress hand-off admits the stop on an `ESCALATION_ACK <nonce>` line with the report still invalid, into records nothing reads (ledger L25); the stale "blocked" canonical survives to Step 17, where /dev gives no route; one aggregate re-run that no prose asks for clears it | not returned; route by judgment only | — |
| F3a E1: overnight contract names dev-report.v1 (dev-overnight.md:837), the dispatch obligation v2 (:1288) | posttool-overnight-file-check.py blocks at PostToolUse, after the producer stopped; its text "Re-run the subagent or escalate" sends a template-following dev into the same block; only an undocumented dual-shape report passes both | not returned (lands on the orchestrator) | same, plus G2 forces v2 at the stop |
| F3b a stale v1 qa-report beside the lane reports | the e2e gate picks the unsuffixed stale file and blocks every lane QA; the Step 17 resolver fails on it; `rm` is refused, a QA may not edit another producer's file, the orchestrator may not write it, dev.md:1342 forbids inventing it | dead end | same |
| F4 index.lock held through a /dev cycle | checkpoints build their tree in a private temp index: nothing blocks, nothing is lost | fine | — |
| F4c index.lock held during /commit | the commit lands; the shared-index sync exits 3 (`SESSION-INDEX REFUSED reason=sync_failed`); nothing notices; `git status` then shows the commit as reverted; `rm .git/index.lock` is refused by bash-safety | silent; a stale lock is a human-only dead end | same |
| F5 session cut after a dev's Edit, human /restart | restart.md's own command (`$HOME/.claude/venv/bin/python …`, :70) is refused by bash-safety (dynamic command head); spelled `~/.claude/...` it passes and recovery works; then pretool-todo-validate's Gate 4 refuses to complete the dev step without a new dev Agent call, which restart.md and CLAUDE.md Lesson 16 forbid | dead end in a single-lane cycle | same |
| F6 usage limit mid-subagent | the same refusal; otherwise resumes after the human's /restart; no autonomous path, so an unattended overnight session waits for the owner (against D20) | dead end overnight | same |
| F7 one fan-out lane leaves an old-format report (P1's wedge) | fixed in d625284 when the dispatch carries any obligation block: the sibling passes, the stale lane is blocked at its own stop; with no obligation block at all (F7b) the legacy check is session-wide and blocks the compliant sibling in every round | F7b: dead end for that lane | not run |

Also measured: recovery steps the orchestrator runs count against the orchestrator gate's 5-Bash streak, which only an
Agent dispatch or a new prompt clears (hooks/pretool-orchestrator-gate.py docstring :6-7, :13-21; the prompt's reset
is hooks/prompt-workflow.py `_clear_turn_state` :1999-2016, at every UserPromptSubmit, typed or not).

## Goal

1. **A replay suite in CI** (tests/replay/), built on P1b's trace runner, network-free and hermetic (HOME,
   CLAUDE_CONFIG_DIR and CLAUDE_STATE_DIR in tmp_path), that proves D25's four requirements on every merge:
   - (1) all ten pipelines (/spec /dev /redev /dev-command /dev-overnight /do /close /commit /merge /push) run
     compliantly with 0 gate blocks and 0 hook errors and reach their terminal;
   - (2) fault injection (missing artifact, malformed artifact, old-version report, held git index.lock, interrupted
     session, usage limit and resume, a fan-out lane leaving an old report): every block names the artifact and the
     failing check, goes back to that artifact's own producer (read from the dispatch record that declared it, D21),
     and the next round passes with zero human action, except the one /restart the human types in F5, F5f and F6
     and the /close or /commit the human types in each F8 fault: a session the owner interrupted (his exit, D23),
     or one a usage limit cut outside /dev-overnight, resumes with his /restart (D22, human-only by design), his
     /close or /commit completes a cycle it meets unfinished (CC4), and after either nothing needs a human; inside
     /dev-overnight a usage-limit cut (F6o) resumes with no human action at all (D20, X8);
   - (3) no dead end: apart from the owner's /stop there is no state in which an agent cannot satisfy a gate (proved
     by X6);
   - (4) one regression replay per process defect already met: P1's fan-out wedge, E1, N1, V1-1/NV-1.
2. **Every fault and every compliant-replay refusal that is a dead end, or that does not return the artifact to its own
   producer, is fixed at the producer side** (rows 7-20): never by a check at /close or /commit, never by a new state
   file, never by an owner question, never by parking; who fixes is read from the declaring dispatch record (D21);
   overnight decides by experiment or the preset default (D20); outside overnight, asking with AskUserQuestion inside
   the turn is the only pause (D23).
3. **From P1c on, every phase merges only with the suite green and adds the fault replay for the class of process it
   changes.** A CI check derives that class from the suite's own traces (row 6), not from a table.
4. **Live landing.** Merged into a live home whose sessions keep running, nothing new blocks a compliant session or an
   in-flight cycle (acceptance 11).

Put these release notes in the PR (adjust to what the experiments decided):
- a producer whose declared artifact is missing or invalid is stopped at its own stop and told the path and every
  failing check (G2 blocks; before, it only logged); a stop is never admitted on an `ESCALATION_ACK` line;
- the e2e gate judges the stopping QA's own declared report, never a sibling's or a stale one;
- the aggregate script no longer writes a "blocked" canonical report;
- the overnight cycle contract no longer declares a second schema for obligation-bearing dispatches (E1);
- /commit's shared-index sync waits for a live git lock and handles a stale one itself (X7);
- /restart's commands run as written, and a resumed agent completes its todo step;
- the X8 outcome for a usage limit inside /dev-overnight;
- each prose step a hook refused is fixed (list them);
- the replay suite runs in CI and every later phase merges only with it green.

## Owner decisions that govern this phase

D# are in the planning documents' DECISIONS.md (D20-D25; audit/2026-10-23/corrections.md section 1.1 quotes D20-D24
too). S# are planner clarifications in PLAN-v2.md section 0; they rank below quoted owner words and D20-D25. Register
rows are audit/2026-10-23/register.md; a `plan:F:N` source below is the register's citation, line N of
harness-repair-plan/F at planning commit 3ce5882 (read it with `git show 3ce5882:harness-repair-plan/F`), not of the
extracted planning documents.

- **D25 Never fail** (owner, 2026-10-24): "还有一件我关心的！就是永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！"
  ("One more thing I care about! It must never fail! No development run may ever hit an error in the process! And if
  an error does occur it can be repaired immediately!") Source: his message to the reviewing session, recorded
  verbatim in DECISIONS.md D25; the register has no row for it. His words name no suite. The CI replay suite that
  reuses P1b's runtime trace, parts (1)-(4) of the Goal, and the rule that every later phase merges only with it green
  and adds the fault replay for the process it changes are the measure DECISIONS.md D25 records ("Measured by a replay
  suite in CI that every later phase keeps green"): the reviewing session proposed them and the owner forwarded the
  proposal with his words; they are not his words.
- **The earlier words it restates** (register rows, with their sources; "teachings" is
  docs/reference/paseo-daemon-teachings-20260910.md at d625284, which P8 deleted: read it with
  `git show d625284:docs/reference/paseo-daemon-teachings-20260910.md`):
  - **CC4** (D7, O19; plan:prompts/P4.md:100-102, plan:prompts/P3.md:154-155; <=2026-10-13, date inferred):
    "dev永远都会完成，所以如果遇到close和commit自己派发相关的dev使用过的subagent补全。只要用户想dev一定dev完成，用户想close一定close完成"
    ("dev always completes; if close or commit meets an unfinished cycle, it dispatches the subagents that dev used to
    complete it; whatever the user starts, dev or close, is completed").
  - **CC8** (teachings:108, <=2026-09-10, batch 6): "永远不允许force，永远一致的规则就是agent哪里犯错了自己就补哪里" ("never
    force; the one rule is that an agent fixes its own mistake where it made it"). Requirement (2)'s "back to its own
    producer" is this rule.
  - **DT2** (O17/O18; plan:prompts/P3.md:144-146):
    "QA判定为 fail的话dev就永远不能complete report，这算什么诚实？这只是过程而已。dev走完只会有一个结果：彻底开发完成，不存在任何gap"
    ("a QA fail is only a step in the process; dev ends with one result: fully developed, no gap").
  - **DT3** (O17; plan:prompts/P9.md:161, plan:COVERAGE.md:26): "不要给我说失败" ("don't talk to me about failure").
  - **DT4** (teachings:103, batch 2): "诚实终态永远不允许" ("an honest terminal state is never allowed"). It conflicts with
    CLAUDE.md:98 at d625284 (Hook Discipline #5, "Ordinary /dev recovery has an honest terminal branch"). P9 rewrites #5
    under D20 and D23 (hand-off under "Branch and pull request"); you do not edit CLAUDE.md.
  - **HC2** (teachings:124, batch 6): "如果发现了问题就通过harness解决，永远不要通过ai的自觉性！" ("when you find a problem, solve
    it through the harness, never through the AI's self-discipline"). A recovery that works only because an agent
    reads a prose step and complies (dev.md Step 12's sanity check in F1) is not a fix.
- **The 2026-09-28 ruling** (docs/reference/close-commit-zero-failure-mechanism-20260928.md, rulings :13-23, hard
  criteria :26-35). Ruling 2: "artifact-missing detection belongs on the PRODUCER of each artifact (at the moment it
  finishes) and on the ORCHESTRATOR (at dispatch and collection points)". Those positions (the producer's stop, G1 at
  dispatch, G3 at collection) are allowed, not consumer-side checks to delete. What goes is re-checking and re-deriving
  at /close, /commit and other consumers, and several deciding consumers. C1 zero new mutable state files; C2 zero new
  class-(b)/(c) checks at /close or /commit; C3 strict failure-surface decrease; C4 an adversarial rehearsal (your
  fault suite is it); C5 "a blocking gate returns the artifact to its own producer; hook rejections are
  PAUSE-and-report for subagents; no new human-in-the-loop steps on the default success path; legitimate output always
  retains a route to completion". Requirement (3) is C5's last clause made testable.
- **D18, D19** No owner question, no owner machine step (above).
- **D20** /dev-overnight is unattended: it never asks, never parks, never asks after the window. A decision is made by
  experiment when one can be run, otherwise by the question's preset default (DECISIONS.md marks that rule INFERRED, no
  owner words), and recorded in the summary's "Decisions made without the owner". For you: no fix may wait for the
  owner inside /dev-overnight, and F6's overnight case must resume with zero human action if the CLI allows it at all
  (X8). The AskUserQuestion deny and the summary section are P2's.
- **D21** No filename-to-role table, in code, prose or test data, and no agent manual. A gap reports facts only (file,
  failing check, lane). Who fixes is read from the obligation of the dispatch record that declared the artifact
  (`role` and `artifacts[].path`; obligation.py resolve_own_obligation and find_unresolved_dispatch_obligations; for
  an artifact no dispatch declared, the command's canonical todo step in scripts/todo/<command>.py; DECISIONS.md marks
  that mechanism INFERRED, and P1b's E3 reader implements it). The suite derives every expected producer this way.
- **D22** /redev is /dev that saves context: a fresh task id every time, gated exactly as /dev, not a continuation. The
  suite replays it as such and asserts the fresh id.
- **D23** Outside overnight, asking with AskUserQuestion inside the turn is the pause; the question is specific;
  neither asking nor answering releases a gate. The suite's clarify scenario asks; requirement (3) checks that an
  answer releases nothing.
- **D24** Every artifact has exactly one producer and at least one consumer, and its consumers trust one conclusion.
  Your PR carries the table artifact / producers before -> after / deciding consumers before -> after / proof (a
  writer and reader grep plus a sandbox write trace) for every artifact you touch. Written-never-read is deleted at its
  producer (the G2 escalation stores, row 7); read-never-written loses its reading branch (row 12).
- **D15** Published product: no feature is retired; live sessions keep running with the hook list they loaded; a
  registered hook is never deleted in the change that unregisters it. **D17** Unreachable code is deleted with its
  reachability proof; a failing test of live code is fixed, never skipped or quarantined.
- **D4c / SG6** (plan:prompts/P5.md:152-156): "放行，但是不要hardcode，并且我记得claude原生支持stop不检测手动被动中止，只检测agent主动终止
  之后用restart自动接" ("let it stop, but hardcode nothing; Claude Code runs no Stop on a manual interruption, only when the
  agent ends its turn; /restart then picks it up"). No code parses an API-error or interrupt record. D22's source line
  (teachings:295): "恢复一个session被截断应该用restart command而不是写字" ("resume a cut session with the restart command, not
  with text"). T0 (2026-10-22): "今晚继续跑，我授权你做任何事情+开启任何新的周期，总之就是不能停" ("keep running tonight ... it must
  not stop").
- **D2** dev has one terminal, completed; QA fail and BA needs_clarification are process steps, not terminals.
  **D8** only the producer writes its artifact: the orchestrator never repairs a producer's file, and a QA never edits
  another producer's file.
- **Producer-side.** Every fix lands on a producer: the producer's own stop (G2), the dispatch (G1) or collection (G3)
  point, a launcher, the script that writes the artifact, a producer prompt, or CI. Nothing is added to /close, /commit
  or the changelog-analyst as a check (C2); the two places rows 14 and 18 touch there change how a producer operation
  runs or remove a step a hook refuses, a change to any part of the routing loops P1b's PR left only makes them
  dispatch a gap's producer again ("Delivered by P1b"), and the PR shows that each hunk adds no check.

**OPEN owner decisions.** None. Ask the owner nothing, at any point. A product question this prompt does not answer is
decided by an experiment you run, recorded in the technical-choices table.

### Decided by experiment (D18; nobody is asked)

Each experiment runs in the sandbox kit or in the suite's own hermetic fixture; X3's settings-env probe and X4's
sub-measure ask about a live CLI session and run in your own session. None runs against your container's real
`~/.claude` or HOME. Fix the rule before you run; put the setup, the raw counts or exit codes and the option taken into
the PR's technical-choices table; follow the result. ("E1" in this prompt is the v1/v2 contract conflict of the
ledger's section 3, so the experiments here are X1-X10.)

**X1. Runner source.** Read P1b's merged PR ("Decided by experiment", its D24 check and "Hand-off to P1c"). P1b ships
the runner and the ten compliant drivers whatever its E1 decided: import both, extend the drivers with the scenarios of
(1) they lack, and add the fault injection, the assertions and the fixture (rows 1-5); never a second runner or driver
set. A piece the runner lacks goes into P1b's module, ported from the planning kit (baseline.py's Session, ev and tool;
runhook.py) and the pilot design: hook commands run exactly as settings.json registers them; every agent-side
Read/Write/Edit and every CLI-side transcript append is logged as a synthetic event with its actor; an optional strace
layer (`strace -f --seccomp-bpf` over openat, open, creat, rename/renameat/renameat2, unlink/unlinkat, mkdir/mkdirat,
rmdir, link, symlink and truncate, the stat/access family recorded as probes, execve/clone/chdir to credit each child to
the script that started it). Rule: no verdict of (1)-(4) depends on strace. The strace layer feeds only the D24 table,
the hermetic write audit (X2) and the fault-coverage step's path set where the runner's own records do not show a file
("Merge rule from P1c on"; X10's traced run), so the suite runs where strace is absent. Record each piece you added to
P1b's runner and each scenario you added to its drivers.

**X2. Hermetic fixture outside the namespace.** The kit runs hooks inside ns.sh with HOME=/root. A CI runner may not
offer unprivileged mount namespaces, and the requirement is HOME, CLAUDE_CONFIG_DIR and CLAUDE_STATE_DIR in tmp_path.
Build per scenario, on top of P8's root conftest.py: `tmp_path/home` (HOME); `tmp_path/home/.claude` (CLAUDE_CONFIG_DIR;
the harness home, a landed git clone built as below, no worktree); `tmp_path/state` (CLAUDE_STATE_DIR);
`tmp_path/tmp` (TMPDIR); `tmp_path/gitconfig` (GIT_CONFIG_GLOBAL, with GIT_CONFIG_NOSYSTEM=1); the toy product repository
`tmp_path/toyproj` cloned from a local bare origin (so `refs/remotes/origin/HEAD` exists); a venv reachable as
`~/.claude/venv` whose interpreter imports jsonschema and yaml, checked first (trace B found a copied venv whose
activate script pointed at its creation path and silently ran a system Python without them); `GIT_ALLOW_PROTOCOL=file`;
http_proxy, https_proxy, HTTP_PROXY, HTTPS_PROXY and ALL_PROXY pointed at a local port where the fixture's guard counts
each connection and closes it, so any network attempt fails fast, is counted (acceptance 7) and counts as a hook error
even if the hook swallows it. The harness home is a clone of your checkout's HEAD whose origin is a bare clone
of the checkout under tmp_path, landed as a live home is: write its overlay settings.machine.json first (env CLAUDE_HOME
that clone, TMPDIR and CLAUDE_CODE_TMPDIR `tmp_path/tmp`), run init steps 3-5 the way the landing runs them
(`scripts/bootstrap --steps 3,4,5` in the fixture's environment; the venv above takes step 1's place), and check that
`scripts/install/land --state` prints `landed`. So the Stop chain's landing and checkpoint run git there as on a live
home (acceptance 11's harness-home Stop, R-V1); a replay that needs another home state or revision builds that home
from the same bare origin, the way tests/test_landing.py builds its homes. Experiment: replay the compliant /dev 2-lane
scenario once in the kit's namespace and once in the fixture. Rule: take the fixture if both give the same table (per
hook event: hook, exit code, block text with ids, timestamps and paths normalized) and the fixture run, traced, writes
no file outside tmp_path (device files aside). P1b's path rule put every hook state file's writer and reader under
`harness_state_dir()` (at d625284 the fixed `/tmp` paths of ledger L29, L42 and L43 among them), so no write outside
tmp_path is tolerated: a state file written there is a path-rule defect, and its writer routes it through
`harness_state_dir()` before merge, with a unit test and a row in acceptance 12's D24 table; any other write there
is fixed in the fixture when a setting the fixture controls moves it (TMPDIR, a documented override), otherwise
at its writer (made to honour TMPDIR). A difference between the two tables is a fixture defect, fixed in the fixture.

**X3. G2 armed (by P1b's E4, or here).** If your base's settings.json already sets `CLAUDE_OBLIGATION_STOPGATE` to
`block` (P1b's E4 sets it in P1b's last commit, after its own false-block replay), run the replays below only and say
so in the PR: they must meet the rule below (0 G2 blocks on compliant stops; a false block is fixed at its producer
side and re-run), and you change no settings (row 9 and Rollback step 7 then add nothing). At d625284, F1, F1q and F2
do not return to their producer under the shipped settings; arming G2 alone fixes all three (pilot: f1-armed,
f1q2-armed and f2-armed each blocked once at the producer's stop and passed round 2). P2 arms G1 and G3 in its last
commit. Experiment: with rows 7 and 8 applied, run every (1) scenario and the live-landing replay of acceptance 11 with
`CLAUDE_OBLIGATION_STOPGATE=block`; also measure, as P2's prompt describes under "Arming timing" step (1), whether a
settings env change reaches a running session. Rule: if every compliant scenario has 0 G2 blocks and the live-landing
replay has no G2 block on a compliant in-flight cycle, add `"CLAUDE_OBLIGATION_STOPGATE": "block"` to settings.json env
(the tracked clean form; `scripts/install/render-settings check --staged` stays green) in your last commit, and the PR
tells P2 to arm only G1 and G3. A compliant scenario that G2 blocks is a false block: fix its producer side (the
template, the agent prose, or G2) and re-run. No branch of this rule ships the suite with F1, F1q or F2 unreturned.
Either env result is safe: a running session keeps advisory until it ends or picks up block at its next producer stop,
which acceptance 11 covers. G1 and G3 stay advisory (P2); G4 stays advisory (P5 replaces it).

**X4. Literal-prose conflicts: which side changes.** The compliant drivers follow the command and agent prose
literally: every fenced command block as written with its placeholders filled, every template as written, the
canonical TodoWrite list, `run_in_background: false`, the FIRST ACTION reads, and the stated default wherever the prose
offers a choice. A block met that way is a process defect. For each (row 18 lists those the pilot met):
- (a) if the refusal enforces a rule written in CLAUDE.md, DECISIONS.md, the 2026-09-28 design doc or a security
  hook's stated policy (the removal policy, git privilege, config protection, the overnight boundary), keep the hook and
  change the prose to a form the hook accepts by its own design (a path form it resolves, a step dropped because a
  script already does it). Never a wrapper, an eval, a helper script that hides the operation, or a split that evades
  the rule's intent;
- (b) if the hook refuses an action no written rule forbids (a parser false positive) and no prose form expresses the
  step, fix the hook, with a unit test;
- (c) between equal options, fewer lines and no new rule;
- (d) if a later phase's prompt already has a row on the same lines, use that row's mechanism (X5).
Sub-measure for merge.md:87, which binds SESSION_ID from CLAUDE_SESSION_ID only: in your own session run
`env | cut -d= -f1 | grep -E '^CLAUDE'` (names only, never values) and use the variable the CLI's Bash environment
carries (trace B saw only CLAUDE_CODE_SESSION_ID, as dev-overnight.md:207-208 says). Record each conflict: prose line,
hook, option taken, replay before and after.

**X5. Work a later phase owns.** Some refusals sit on lines a later phase rewrites: the overnight start, the cycle
contract and the cycle index (P2 rows 12 and 13), P2's bwrap decision, the prose paths (P2's harness-home channel,
TC-44), doc-sync writing into docs/dev/ (P9 row 2), the resolver (P3), close.md Step 0 (P4), product-repo hygiene (P10).
The suite must be green at your merge, so you fix them, with the later phase's mechanism. Read that row in the planning
documents as corrected by audit/2026-10-23/corrections.md; for the cycle contract that is 2.21 and 2.85: "For a dispatch
that carries an obligation, posttool-overnight-file-check reads the schema from that dispatch's obligation … Its
contract entry carries step, role, pipeline and path only (one declaration, D24; fixes E1)", "No seed file:
pretool-subagent-enforce derives the allowed steps 2-4 from _STEPS and cycle_index(state)", "The PM TRIAGE handler is
the contract's only writer". Rule: implement the smallest part of that row that clears the block, in the row's own
mechanism, never a second mechanism the later phase would have to remove. List each under the PR heading "Delivered for
later phases" (phase, row, what is done, what remains). Where no later row exists, X4 decides.

**X6. No dead end: how it is proven.** Requirement (3): apart from the owner's /stop, no state exists in which an agent
cannot satisfy a gate. Method:
- (i) Enumerate every block site from the code at test time, never from a committed list: every code path of every
  hook settings.json registers, and of the hooks/lib modules they import, that exits 2 or prints a block or deny
  decision (Python: from the AST, the exits and the decision dicts; shell: `exit 2` and the deny printers).
- (ii) The corpus holds, per site, one hook-level replay that reaches it, proved by line coverage (Python: a trace
  function or coverage in the hook subprocess; shell: `bash -x` with PS4 carrying BASH_SOURCE and LINENO), and the
  site's class with its next action:
  - G, a gate on the actor's own obligation: in every replay that reaches the site, compliant or fault, the same actor's
    next action that every registered hook and every rule X4 (a) names allow in that state clears it, and that replay
    exits 0; a state whose only clearing action such a rule forbids is a dead end (at d625284, Gate 4 after a recovery
    resume: Lesson 16 forbids the replacement Agent call);
  - D, a denial of a forbidden operation: the denial names the operation, and no (1) scenario reaches the site (each
    completes with 0 blocks), so no pipeline needs the operation;
  - H, human control: the /dev-overnight time-lock's Stop block inside the window and the timelock instrument-failure
    block (P1), cleared by the owner's /stop or the window's end; the agent keeps working meanwhile, and a broken
    time-lock cannot merge because the compliant overnight scenario would fail;
  - U, unreachable from every registered entry: deleted under D17 with its reachability proof.
- (iii) Two more replays: the orchestrator asks AskUserQuestion while a gated artifact is missing, and the answer
  releases no gate (D23); a producer ends with a forged `ESCALATION_ACK <nonce>` line, and it releases nothing
  (corrections 2.25).
Rule fixed: the method is required. Recall counts the blocks the pilot observed that came from a registered hook, from a
hooks/lib module it imports or from a hook it runs as a subprocess (the Stop coordinator's phases, the time-lock among
them): each such block text quoted in this prompt and each such refusal rows 7-20 name. If on your base the enumerator
misses one of their sites, extend its reach (those subprocess hooks, helper functions that exit 2 or print a deny,
non-literal exit codes) until recall is 100%. The observed refusals outside that code (such as hooks/merge.sh, which
settings.json does not register, scripts/session-index.py's `sync_failed`, the resolver and the aggregate script) are
proved by their rows' replays in (1) and (2). A site that fits no class is a dead end and becomes, like each dead-end
state of class G, a scope row fixed at its producer before merge. The test prints the site count per hook and per class.
A crude count at d625284 found 295 block-like lines in 40 of the 80 registered hook files (pretool-bash-safety.sh 53,
pretool-git-privilege-guard.py 47, pretool-overnight-hook-guard.py 42); expect fewer distinct sites. Such counts depend
on the pattern: a verifier's re-counts with other line patterns gave 136 to 442 lines in 31 to 44 files, so only the
enumerator's own site list counts.

**X7. A git lock held under a repair (F4c).** `session-index.py sync-shared` exits 3 when index.lock is held
(scripts/lib/session_index.py :255-256 raise `sync_failed` when `update-index --add --cacheinfo` (:252-253) cannot take
the lock; the deletion branch's `update-index --force-remove` (:248-249) ignores its exit code and :257 lists the path
as synced, so a commit whose only changes are deletions exits 0 with a false "synced" report; :231-235 is `diff-tree`,
which takes no lock); nothing retries or tells the agent, and `rm .git/index.lock` is refused by bash-safety. Options:
- (A) the sync itself (the producer of the shared-index update) waits while a live process holds the lock, printing
  the holder (pid and command where the platform shows them) at a fixed interval; when no process holds the lock (no
  open file descriptor on it, read from /proc) and the lock is older than the sync's own start, it removes the lock
  with one unlink, says so on stdout, and continues;
- (B) as (A), but a lock with no open descriptor is removed only when, in addition, no git process has this repository
  as its working directory (also read from /proc).
Experiment, in the fixture: a live holder (a background process that creates index.lock exclusively, keeps it open for
20 s and then removes it, as git does with its own locks), a stale lock (the file with no holder), and no lock, each run
once with a commit that modifies a path and once with a commit whose only change is a deleted path; then the same six
with /proc unavailable to the helper (removal never happens there). Rule: take (A) if, with /proc, the live cases show
0 removals and a completed sync after release, the stale cases complete with exactly one removal each, and no case
leaves `git status` showing the commit as reverted; otherwise (B), held to the same conditions before merge. Without
/proc the option taken must, before merge, show 0 removals in all six, the live and no-lock cases completing as they do
with /proc and each stale case still waiting after 40 s (the lock in place, its interval line printed, no path reported
synced), then completing once the test removes the lock; no case may then leave `git status` showing the commit as
reverted. F4s, like the rest of the replay, runs with /proc. No option asks the owner or the orchestrator, inside or
outside /dev-overnight (D3, D25 (2)). Row 14's unit test (acceptance 10) also runs the sync in a linked worktree, as
/dev-overnight's `--worktree` launch makes, while a live process holds the main repository's index.lock: the sync
updates the worktree's own index and returns with that lock still held, no wait line printed and nothing removed. The
bash-safety refusal of `rm` stays.

**X8. Autonomous resume after a usage limit inside /dev-overnight (F6o; D20, T0, SG6).** Today only the human's /restart
resumes (human-only: `disable-model-invocation: true` and the `Skill(restart:*)` deny), so an unattended session waits
for the owner. The facts you need are UNVERIFIED on a harness host: whether a usage-limit error ends the turn with no
Stop (SG6 says a manual interruption runs none); whether a prompt scheduled with CronCreate or ScheduleWakeup fires into
a session whose last turn ended in a usage-limit error once the limit resets; and that prompt's transcript record. Take
them from P1's "Capability facts for P5" as corrected in the planning documents' reviews/P1-PR5-review-followup.md
("Capability capture, corrected (COV-7)": the fired CronCreate prompt carries `isMeta:true`, `turnOrigin:"scheduled"`
and no `origin`, CLI 2.1.303, off a harness host; the PR body's table predates it) or from the CLI documentation read
in this session (quote it with the date read); do not substitute memory. The change:
- /dev-overnight's canonical todo list gains a first step "schedule the wake": one recurring scheduled prompt with a
  fixed text, valid until end_time. pretool-todo-validate accepts that step's completion only after a CronCreate or
  ScheduleWakeup call in the span (HC2: a gated step, not prose alone). When the prompt fires, prompt-workflow
  recognises it by the non-human origin that stop_contract.is_human_prompt already excludes (`origin` or `turnOrigin`
  kind other than "human", stop_contract.py:45-49), if the scheduled prompt's record carries one (UNVERIFIED above),
  inside an open /dev-overnight span only, and starts the recovery restart.md runs (restart-subagents.py prepare, the
  fixed recovery SendMessage to the transcript-discovered pending agent ids, status, finalize). The SendMessage
  exception of hooks/pretool-block-background-tasks.py (:157-161) widens from "typed /restart" to "typed /restart, or
  the overnight session's own wake inside its span", with the same fixed message and the same id rule. A wake that fires
  while nothing is interrupted finds 0 candidates and the loop simply continues; the schedule is deleted when the
  session ends. The widened exception is row 17's own decision under D20 and SG6, not an X4 case: every other message
  and id stays refused, and the lines that name the typed /restart as the only exception go to P9 ("Hand-offs for the
  sync list").
Rule: ship the wake if the documented or captured record shape drives the replay to a completed overnight cycle with 0
blocks, and the widened exception refuses any other message or id (two replays); a replay that fails is fixed on the
wake's side and run again, so no branch of this rule ships without the wake or with F6o red. The other two facts above
(the Stop, the firing) decide nothing: the typed /restart stays beside the wake, so a wake the CLI never fires leaves
the session as it is today. F6o's driver models the firing on the captured record shape, listed with the other modeled
CLI behaviour ("Out of scope"). While those facts stay UNVERIFIED, the PR records them as UNVERIFIED for P5; if the
documentation or a capture shows that a scheduled prompt cannot fire there, the PR quotes it under "Decided by
experiment" (X8) as a CLI limit for P5, never as D20 met. No branch of this rule asks the owner or adds a wait for him
(D20); only a cut the CLI never wakes still waits for his /restart, as today. Never parse an API-error record (D4c).

**X9. N1 on a landed home.** The record is P7b's merged PR #7: commits 8ab874b and 98d153a, scripts/install/land's
"Review N1" block, the tests in tests/test_landing.py whose docstrings begin "Review N1"
(`test_a_cli_write_of_its_own_key_does_not_stop_the_pulls_after_a_stop` runs both pulls), and, in the planning
documents, reviews/P7b-PR-record.md (the N1 row; under "Out of scope, found", "Review N1's remaining window" and
"Fact 1"). N1: on a landed home the CLI writes a key the clean form leaves out (`model`); settings.json's size changes
and git trusts the stat without the filter, so `git diff --quiet` says clean and /pull does not stash,
`git pull --rebase` refuses (`cannot pull with rebase: You have unstaged changes`), hooks/pull.sh exits 1 and
`safe_pull` returns 0 without pulling, at every later Stop too. P7b fixed it from the next Stop on (the landed fast
path re-records the stat). The record leaves two parts open: a pull after the write and before that Stop still meets
the refusal once (the window), and `safe_pull` decides its fetch, stash push and pull by `tee`'s exit status, so it
logs their failures as success (Fact 1). Before, on 1d10ae0 (the first parent of 8ab874b; the record shows the same
on d625284 after P7's manual init), in a scratch clone with HOME and GIT_CONFIG_GLOBAL in scratch and a local bare
origin one commit ahead: a landed home, a CLI `model` write, one Stop -> hooks/pull.sh exits 1, `safe_pull` returns 0,
HEAD behind. After, on your base: (i) the same -> both pulls reach the upstream commit, the CLI's `model` kept,
nothing stashed; (ii) the same write, then each pull before any Stop. Rule: if (i) and (ii) hold, N1 needs only its
replay. If (ii) refuses, on a landed harness home hooks/pull.sh's `HAS_CHANGES` and fswatch's `has_changes` (the
producers of the stash decision) first run the landing's existing re-record, made callable from them if it is not (no
second implementation, no new state), and the replay must then pass (row 20). Either way `safe_pull` decides each step
by that git command's own exit status, and a failing fetch, stash push or pull returns non-zero (row 20).

**X10. CI run time and the split.** Inputs: the pilot timings under "What the pilot measured" (4 cores shared with other
sessions, so noisy; strace x1.4-1.6) and the CI wall time P1b's PR records for its traced job (P1b E2, acceptance 2).
Estimate for this suite, untraced and sequential: (1) 16 scenarios about 2,100 s per settings mode; (2) 21 faults about
4,000 s per mode, roughly half that if each fault starts from the compliant run's saved state at its injection step;
(3) about 60-120 s (hook-level replays); (4) about 400 s beyond what (2) shares. Both modes: about 3.5 h, or about 2.4 h
with saved-state starts. UNVERIFIED on a CI runner. Experiments:
- (a) run the hooks of one event in parallel, as the CLI does, against sequential: if the verdict tables of the 16
  compliant scenarios are identical, run them in parallel;
- (b) saved-state starts: if F1, F2, F3b and F7 give the same verdicts as full replays, use them for every fault;
- (c) measure every scenario on the CI runner (ubuntu-latest; record `nproc`) in your pull request's runs: a push to
  your branch alone starts no baseline run (baseline.yml's push trigger names master and main only), so open it early
  as a draft; it is still your one pull request.
Rule: if the whole suite in both modes, untraced, sharded over at most 20 matrix jobs, finishes within 20 minutes wall
including setup, every pull_request push runs all of it. Otherwise split: every push runs (1) and (4) in both modes, (2)
in the PR's own settings mode, and (3); the full set ((2) in the armed copy too, and the traced run that feeds the D24
table) runs on the PR head before merge (started by every pull_request event of a PR to master: opened, synchronize,
reopened and `ready_for_review`; a newer push cancels the PR's older run) and on baseline.yml's weekly schedule on
master. Either way the full set must be green on the PR head before the reviewer merges (each head gets that run from
its own pull_request event, with nobody starting it; the PR changes no repository setting), and no scenario is dropped
from both sets. P1b's D24 check (its own step or job, P1b's E2) keeps the schedule P1b's E2 chose (per PR, never
nightly-only) and is outside this split; the traced run above is this suite's own (X1).

## Scope (re-verify every location on current origin/master)

Locations are at d625284. Every file below may have been changed by P1b, P8 or P7b: find each site again on your base
before you edit it. New code runs on Python 3.10, the CI floor.

**Delivered by P1b.** P1b merged before you, and its rows target several sites below: row 7 (its row 3), row 10's
obligation-bearing case (its row 3), row 12's fan-out optional-parent read (its row 7), row 13's schema source and the
contract's v1 names (its rows 6 and 13, E13), row 19's launcher seed and cycle-id disagreement (its E13: no seed, and
every reader of the cycle number calls P2's `cycle_index(state)`), and in row 18 the do.md template (its
E8), close.md :337 and :507 (its rows 6 and 8), commit.md :334 (its row 7), merge.md:165 (its row 12, E11), push.md
Step 1's token scan (its row 11), the resolver calls at dev.md:1322 and dev-command.md:889 (its row 7 respells them
to the harness's copy) and, for /dev-command, the spec auto-detect (its E9 and E14) and the Step 16 completion
template (its row 7 takes the completion report out of the resolver's required chain); outside the table, the routing
loops of /close and /commit, which dispatch again each gap's declaring dispatch through its E3 reader (its row 10; the
F8 faults replay them). For each, read P1b's merged PR, verify on your base what it delivered, add the replay, and
change code or prose only for what P1b's PR left. What P1b's PR did is neither your deletion nor your retired rule
("Rules added / retired", "Net code cap").

| # | File | Location (d625284) | Change |
|---|---|---|---|
| 1 | tests/replay/ (P1b's runner and drivers, extended where P1b merged them): conftest.py, the runner glue, the scenarios P1b's drivers lack | — | The fixture of X2 on top of P8's root conftest.py; P1b's runner and drivers per X1. P1b's drivers, extended to the 16 scenarios, build every pipeline the way the CLI records it (P1's "Scenario drivers"): two queue-operation records at transcript start; a typed slash command as UserPromptSubmit, the `<command-name>` user record and the isMeta body; each dispatch as the Agent tool_use carrying its obligation with a UTC dispatched_at before PreToolUse, the subagent transcript and `.meta.json`, the subagent's own tool calls, SubagentStop with agent_transcript_path, last_assistant_message and stop_hook_active, then the tool_result and PostToolUse; a re-dispatch with the same obligation template and a fresh dispatched_at. Chained scenarios (/close, /commit, /merge, /push) start from the saved state of their predecessor. Settings modes: `shipped` (the checkout's settings.json) and `armed` (the same plus CLAUDE_OBLIGATION_GATE, CLAUDE_OBLIGATION_STOPGATE and CLAUDE_OBLIGATION_BARRIER = block: P1's sandbox arming as P1b's runner uses it, P2's target; CLAUDE_OBLIGATION_TERMINAL never). Drivers model a compliant agent per X4. Extend the drivers P1b committed; do not build a second set. |
| 2 | tests/replay/test_pipelines.py (new) | — | Requirement (1), "The suite" below: 16 scenarios over the ten pipelines, both settings modes. |
| 3 | tests/replay/test_faults.py (new) | — | Requirement (2): the 21 faults of "The suite", both settings modes. |
| 4 | tests/replay/test_no_dead_end.py (new) | — | Requirement (3) per X6: the site enumerator, the per-site replays and classes, the AskUserQuestion-answer and forged-ESCALATION_ACK replays. |
| 5 | tests/replay/test_regressions.py (new) | — | Requirement (4): R-P1, R-E1, R-N1 and R-V1 of "The suite", each with its "before" reproduction recorded in the PR. |
| 6 | .github/workflows/baseline.yml (P8's) or one new workflow it calls; tests/TESTING.md | the jobs; one short section | The suite as CI jobs, triggered and sharded per X10, reachable from release.yml's workflow_call so a tag cannot publish around it; its full set must be green on the PR head before the reviewer merges (X10; the PR changes no repository setting, and baseline.yml's comment (:181-182 at d625284, :203-204 on master 2acc29b) that calls the `baseline` job "already-required" so it "gates merges" loses both claims). The `baseline` job's own pytest step (baseline.yml:107 at d625284, :112 on master 2acc29b; hooks/tests and tests on python 3.10-3.12) leaves tests/replay/ to the suite's jobs, which run all of it (not a skip). The fault-coverage step ("Merge rule from P1c on"), its code under tests/replay/ with the rest of the suite: a CI-only script under scripts/ lies on no replay's path, so the step would fail on your own diff (acceptance 8). The network guard of X2 in every job. TESTING.md gets one short section: how to run the suite locally and the merge rule, nothing more (D21: no manual). |
| 7 | hooks/subagentstop-artifact-contract-enforce.py (G2) | `ACK_PREFIX` :304 and the ack helpers :319-329; `_load_progress_helper` :351; `_mint_record` :614 (escalations/ :631); `_latest_unadmitted` :637 (escalation-admissions :639, written at :797-798); `_write_side_records` :659 (deferred-checks :691); `_clear_progress` :704; `_gate_decide` :747 (the no-progress hand-off :778-829) | F2g; corrections 2.27 and 2.30; C5; D24. P1b's row 3 delivers this: verify it on your base, add F2g's replay, and change code only for what P1b's PR left. A failing obligation stop is a plain exit 2 that names each failing artifact and check to the stopping producer, in every round. Delete what your base still has of the no-progress hand-off, the `ESCALATION_ACK` admission and its four record stores (escalations/, escalation-admissions/, progress/, deferred-checks/; ledger L25: written, read only by this hook). Before deleting a store, show by grep and the suite's trace that nothing else reads it; a store another reader uses stays and goes into the D24 table. Records left on live homes are ignored (acceptance 11). `GATE_FAULT` (a crashed gate decision, :1158-1163) never admits the stop, and X6 classes its site like any other: G where the stopping producer's repair clears it, U (deleted under D17) where nothing on your base reaches it. Its tests change with it (row 21). |
| 8 | same | the legacy correlation path :1218-1230 (`_find_correlated_reports`, `_dispatch_task_id`, `_own_reports`) | F7b. When the dispatch prompt carries no obligation block, judge only the reports the stopping agent wrote itself, read from its own transcript's Write and Edit tool uses (agent_transcript_path), never a sibling's or an earlier attempt's. A report it did not write is not its to fix (C5, CC8); it stays for its own producer's stop. |
| 9 | settings.json | env | X3, only if your base's settings.json does not already set it (P1b's E4 sets it): `"CLAUDE_OBLIGATION_STOPGATE": "block"`, in the last commit together with the fault replays whose return depends on it (Rollback, step 7). Nothing else in settings.json. |
| 10 | hooks/subagentstop-e2e-enforce.py | report resolution :120-137 (`session_ts_filename_match`, then the "last 5" scan) | F1q, F3b, the overnight what-if ("no qa-report-*.json … under session <sid>"). P1b's row 3 moves the obligation-bearing case: verify it on your base, add its replays, and change code only for what P1b's PR left; the case without an obligation is yours. For an obligation-bearing QA dispatch, judge exactly the qa-report path its obligation declares (resolve_own_obligation), whatever the session id format; without an obligation, only a report the stopping QA wrote itself (as row 8). The newest-filename and "last 5" correlation goes. The message names the exact path and the missing field. P1b's row 7 split the deciders on the qa-report by property (G2: existence and shape; this gate: the e2e status policy); keep that split and add no second decider. |
| 11 | scripts/aggregate-dev-report.py | `_write_blocked_aggregate` :2023-2082 and its callers (:2223 in `_reaggregate_with_shrunk_from_or_block`, :3780, :3830, :3848); `canonical_status = "blocked"` :1591; the shard validation that accepts `needs_review` (a third vocabulary, ledger L21) | F2, F2g. On a shard failure the script writes no canonical report, removes the canonical it wrote earlier for that task (its own output), and exits non-zero naming each failing shard's path and every error. A schema-invalid canonical can then never exist; the existing aggregate check at the next QA dispatch sees the canonical absent and the canonical's one producer, as P1b's E5 chose, writes it once the lane is repaired. The shard check accepts only dev-report.v2's own status set. |
| 12 | scripts/resolve-dev-artifact-chain.py; commands/dev.md :1338-1344 (and dev-command.md's copy, if it has one) | the fan-out optional-parent branch ("any present optional parent artifact must validate") | F3b; D24 (read-never-written loses its reading branch). P1b's row 7 delivers this: verify it on your base, add F3b's replay, and change code or prose only for what P1b's PR left. In a fan-out cycle no dispatch declares the unsuffixed parent ticket, context or qa-report, and dev.md forbids inventing them, so the resolver no longer reads them; the prose sentence follows. Singular cycles are unchanged. P3 turns the resolver into the disposition and keeps this. |
| 13 | hooks/posttool-overnight-file-check.py; commands/dev-overnight.md | the block text :333-367 ("Re-run the subagent or escalate"); contract entries :835-838 (`schema_name: "dev-report.v1"` :837, `"qa-report.v1"` :838); the append-only rule :852 | F3a and its QA half (:838 against the obligation's v2 at :1390); corrections 2.21 and 2.85, which P1b's rows 6 and 13 (E13) deliver (the schema read from the obligation, the v1 names gone): verify them on your base, add the F3a and F3q replays, and change code only for what P1b's PR left (X5 decides how). For a dispatch that carries an obligation, the check reads the schema from that dispatch's obligation; the contract entry for such a dispatch carries step, role, pipeline and path only. One declaration, so this check can no longer disagree with G2. The message names the artifact and the failing check and offers no "escalate". |
| 14 | scripts/lib/session_index.py; scripts/session-index.py; agents/changelog-analyst.md :660-675 | `sync_failed` raised at :255-256 (`update-index --add --cacheinfo` :252-253); `update-index --force-remove` :248-249, its exit code unchecked (:257 lists the path as synced); the analyst's sync step | F4c, X7's option. X7's wait covers both update-index calls, and no path is reported synced unless update-index wrote it (the deletion branch returns its failure as the `--cacheinfo` branch does). The analyst's prose does not change, and the row adds no check (C2). |
| 15 | commands/restart.md | :70, :118, :131 (`$HOME/.claude/venv/bin/python $HOME/.claude/scripts/restart-subagents.py …`) | F5, F6. Spell each command in the form bash-safety resolves by design (the bashprobe showed `~/.claude/...` passing), per X4 (a). The hook keeps refusing a dynamic command head. |
| 16 | hooks/pretool-todo-validate.py; hooks/posttool-subagent-track.py | Gate 4 `check_subagent_completion_guard` :251-270 | F5 (and F5f). A subagent step is also satisfied by an Agent tool_use of that role in the span whose agent was resumed by the recovery path and whose resume finalized (the recovery's own journal record, which CLAUDE.md says is journaled through SubagentStop). Read it from the transcript and that record; no replacement call is demanded, which restart.md and Lesson 16 forbid. The message names the step, the role and, where the obligation declares one, the artifact. |
| 17 | per X8 | — | F6o, X8's wake: scripts/todo/dev-overnight.py (the wake step), hooks/pretool-todo-validate.py (its completion rule), hooks/prompt-workflow.py (recognising the wake), hooks/pretool-block-background-tasks.py (the widened exception), commands/dev-overnight.md (one line). |
| 18 | the literal-prose conflicts (X4) | see the list under the table | Each fixed on the side X4 picks, with the replay that met it. |
| 19 | the /dev-overnight compliant cycle (X5) | see the list under the table | The smallest part of the owning row that lets the compliant overnight scenario run from launch to a Stop after end_time with 0 blocks. |
| 20 | hooks/pull.sh; hooks/git-fswatch.sh `has_changes`, `safe_pull`; scripts/install/land's "Review N1" block (only if it must be made callable) | pull.sh `HAS_CHANGES` :17-21; fswatch `has_changes` :160, `safe_pull` :174 (fetch :180, stash push :200, `pull --rebase` :210) | X9. N1's window (only if X9 (ii) refuses): on a landed harness home the landing's existing settings.json re-record runs before the stash decision; no second implementation, no new state. Fact 1: each `safe_pull` step is decided by its git command's own exit status, not `tee`'s. |
| 21 | tests that pin what rows 7-20 change; docs lines a CI check names | hooks/tests and tests (grep each changed file's name) | TC-54: a pin a decided change makes false changes in the same commit to assert the new behaviour (the ESCALATION_ACK tests, the aggregate's blocked-canonical tests, the e2e correlation tests, Gate 4's tests). A test that exercises only deleted code goes with it, named in the PR (D17). If scripts/verify-claims.sh or `scripts/check-enforcement-evidence.py --ledger/--claims` names a line your change makes false, fix that line and nothing more (P9 does the prose pass). |

**Rows 18 and 19, P1b's kept base blocks.** P1b's PR lists under "Hand-off to P1c" each block its compliant drivers
met on its base and passed with a `DEVIATION:` step in the driver source (its acceptances 4 and 17). Each is a row 18
item (X4 picks the side) or, where it stops the /dev-overnight cycle, a row 19 item, whether or not the lists below
name it. Re-verify it on your base and remove it with the replay that met it; the same commit drops its `DEVIATION:`
step, so that replay follows the command text literally and meets no block. A listed block your base no longer shows
needs only its replay, and its DEVIATION goes too. No driver keeps a DEVIATION at your merge, and no check exception,
skip or expected block takes its place (acceptance 3).

**Row 18, the literal-prose conflicts the pilot met** (re-verify each on your base; P1b or P8 may have fixed some):
- commands/dev.md :757-759 tells the orchestrator not to dispatch graphify when its sentinel is absent, but
  pretool-todo-validate's Gate 4 will not complete Step 9 without a graphify call (canonical step from
  scripts/todo/dev.py).
- The orchestrator gate's 5-Bash streak (cleared only by an Agent dispatch or a new prompt) blocks dev.md Steps 14-17
  (:1022 on), which need six Bash calls for a 2-lane cycle, and any prescribed recovery step (F2g's aggregate re-run).
- commands/spec-update.md:115 says mktemp, then Read, then Write; pretool-write-guard.sh refuses a Write over an existing
  file.
- agents/changelog-analyst.md :93, :1123, :1456, :1898 prescribe `rm -f "${MSGFILE}"`, which bash-safety's removal
  policy refuses.
- commands/do.md Step 5 (:46) gives a do-report template that drops the skeleton's `expected_absent` field
  (hooks/prompt-workflow.py:1386); a Write of that template makes subagentstop-e2e-enforce block the close-QA of the
  do-report with a condition that QA cannot satisfy.
- commands/close.md :337 (`if ! AGGREGATE_RESULT="$(…)"`) and :507 (`if RESOLVED_JSON=$(…)`) are refused by bash-safety
  (dynamic command head); QA then gets no SECOND ACTION.
- commands/merge.md:87 binds SESSION_ID from CLAUDE_SESSION_ID only (X4's sub-measure); merge.md:165's `rm -f <grant>`
  is refused; hooks/merge.sh :181-183 refuses an in-place merge because of untracked files the compliant pipeline itself
  left (docs/dev, .claude registries, doc-sync's INDEX.md and README.md, lock files).
- commands/push.md Step 1 (:140-149) has the agent scan `/tmp/agentic-commit/push/<repo-hash>/` for the token; the
  agent's `find` (the form :82-84 gives for push.sh's own read) is refused by bash-safety; push.sh validates the
  token itself.
- /dev-command: auto-detect (dev-command.md:89, newest docs/dev/specs/*.md) picks the docs/dev/specs/INDEX.md that
  posttool-doc-sync.py writes (X5: P9 row 2's exclusion of docs/dev/ from doc-sync); its Step 16 completion template
  (:802-882) fails resolve-dev-artifact-chain with IDENTITY_MISMATCH (identity `dev-<ts>`, expected `<ts>`) and
  MISSING_COMPLETION_REFERENCE (no reference to docs/dev/ticket-<ts>.md); and pretool-claude-config-guard.py (docstring
  :1-40; a Write or Edit at :143-149, a Bash command by the patterns :60-66) refuses the dev's write of the product's
  `.claude/commands/<name>.md` unless a hand-made sentinel `.claude/.hook-refactor-allow` exists, a human step on the
  path /dev-command exists for. Under X4 (b), the narrowest fix lets only a dev subagent whose dispatch obligation lies
  in a human-typed /dev-command span (command_span) write only `<project>/.claude/commands/*.md`, never hooks, settings
  or the harness home; prove with a replay that every other refusal of that guard is unchanged.
- Repo-relative script paths a product repo does not have (X5, P2's channel): dev.md:1322 and dev-command.md:889
  (`python3 scripts/resolve-dev-artifact-chain.py`), commit.md :313 (`source venv/bin/activate && python3
  scripts/late-repair-controller.py`) and :334, close.md Step 0 (:337, `scripts/aggregate-dev-report.py`),
  changelog-analyst.md:669 (`${CLAUDE_PROJECT_DIR}/.claude/scripts/session-index.py`).

**Row 19, what blocks the compliant /dev-overnight cycle today** (trace B; re-verify):
- scripts/create-overnight-state.sh :1026-1056 writes `cycle-1/cycle-contract.json` with `required_calls: []` (:1051);
  its presence switches hooks/pretool-subagent-enforce.py (load_contract :329; passthrough only without a contract,
  :330-332) into enforcement, so the Step 2 PM dispatch is refused (Case C), while the prose publishes the real contract
  only at Step 4 and forbids editing it in place. Then the Stop is refused by the time-lock. P1b's E13 removes the
  seed in either outcome (corrections.md 2.21): verify it on your base and replay it.
- dev-overnight.md's Step 1 block (:196 on) is refused by pretool-bash-safety.sh (`census_fatal:unbalanced:single_quote`,
  set off by apostrophes in its own comments) and by pretool-overnight-hook-guard.py (`OVERNIGHT MAIN-ROOT BLOCK`, :1708).
- In place: `OVERNIGHT SUBPROCESS GIT BLOCK` (:1637) on every harness python3 or bash script the overnight actor runs
  (build-pipelines-from-triage.py, graphify-query and graphify-enrich, aggregate- and apply-permissions,
  scripts/commit.sh).
- `OVERNIGHT WRITE-BOUNDARY FAIL-CLOSED` (pretool-overnight-hook-guard.py:2265) where bubblewrap is absent: P2's bwrap
  decision. CI may install bubblewrap in the job's setup step (network there is allowed; the tests stay network-free).
  Your container runs the suite too (acceptance 3, 4 and 17): install bubblewrap there if it allows that, otherwise
  give the replay a stand-in, as P2's prompt allows ("the way P8 does for its bwrap argv tests"); say which, for both.
- E1 (row 13); the e2e QA stop under the overnight session id (row 10).
- stop-overnight-timelock.py's `CLOSEOUT GATE` (:125) and the cycle-id disagreement (the file check says cycle 0, the
  contract and closeout say 1): P2 row 12's one cycle index, which P1b's E13 delivers early (every reader of the cycle
  number calls `cycle_index(state)`): verify it on your base and replay it.
- Launch prerequisites the fixture meets as a real home does: a clone (origin/HEAD set) and the default launch mode,
  never in place on a protected branch (the launcher refuses that by design).
The compliant overnight scenario carries no producer question; P2 adds the D20 decide-and-record replay as its fault
replay.

### The suite

**Definitions** (one place, used by every test):
- *Gate block*: any hook exit 2, or a block or deny decision on stdout, from any registered hook.
- *Hook error*: an exit other than 0 and 2, a Python traceback on stderr, a hook timeout, `GATE_ERROR` or `GATE_FAULT`
  text, or a network attempt caught by X2's guard.
- *Expected producer* of an artifact: the agent whose Agent tool_use carried the obligation that declares that path
  (role, lane and agent id via the `.meta.json` toolUseId); for an artifact no dispatch declares, the actor that the
  command's canonical todo step (scripts/todo/<command>.py) names. Derived from the replay's own transcript, never
  from a table (D21). At d625284 scripts/todo/ has no commit.py, merge.py or push.py and the /merge and /push dispatches
  carry no obligation; P1b's E3 fallback declares those analysts' artifacts in their dispatch templates. An artifact
  your base still leaves with neither source is a scope row: declare it at its producer's dispatch, never in a table.
- *Next round*: for a SubagentStop block, the same agent's next stop (stop_hook_active true); for a block at dispatch
  (G1) or collection (G3), the re-dispatch of the declaring dispatch (same subagent_type, task_id, lane and obligation
  template, a fresh dispatched_at); for a Bash denial, the next compliant command; for a gap /close or /commit routes
  (the F8 faults), the dispatch its routing loop sends for that gap.
- *Human event*: a UserPromptSubmit whose transcript record stop_contract.is_human_prompt accepts, an AskUserQuestion
  answer, or a file action or command whose actor (X1 logs each event with its actor) is none of these: an agent, a
  hook or a process either starts, the CLI's own writes (its transcript records and `.meta.json`), and the fault's
  injection as its bullet in (2) names it (a live lock holder's release included). X8's wake is not one: its record
  carries `isMeta` and `turnOrigin` "scheduled", which is_human_prompt rejects (hooks/lib/stop_contract.py:43-49).
- *Terminal*: /spec, the spec written and the Stop rc 0; /dev, /redev, /dev-command, the completion step's resolver
  status pass and the Stop rc 0; /dev-overnight, the Stop after end_time rc 0 with the summary written; /do, the
  do-report complete and the Stop rc 0; /close, the Stop rc 0 and, as the last non-empty line of the close report
  (docs/dev/close-report-<task-id>.md), exactly `CLOSE: YES - with disclosures: <n> items` when the cycle's routing
  loop completed a repair (`<n>` = the lines of the report's `## Disclosures` section), otherwise exactly
  `CLOSE: YES — codex disabled by user` (close.md :754, :772; no scenario passes --codex); /commit, the commit on HEAD
  with the cycle's files, none of them still listed by `git status --porcelain`, and the push-gate token present;
  /merge, the topic commit reachable from master; /push, the bare origin's branch equal to HEAD.

**(1) Compliant pipelines: 16 scenarios, each in both settings modes.** /spec; /dev singular; /dev 2-lane fan-out; /dev
qafail (QA fail, dev iterates, QA passes); /dev clarify (BA writes its producer-question artifact, the orchestrator asks
one AskUserQuestion inside the turn, BA is re-dispatched with the answer; D23); /dev devquestion (the same for dev);
/redev (a fresh task id of /dev's form, the same gates; D22); /dev-command (a product command file); /dev-overnight
(launched with an end_time of launch time plus twice the cycle's longest wall time in X10 (c) and in your container, so
the QA pass precedes it on any runner; one cycle with one pipeline to a QA pass, the loop's work continued with no early
Stop, the driver idle until end_time, then the Stop after it); /do; /close after /dev; /close after /do (CC6); /close
with a `CLOSE_REPORT_APPEND_ERROR` round (its cause a defective section text: the close QA's section file ends in a
line that is no legal `CLOSE:` form, so scripts/close-report-append.py:563-566 refuses it at its `append` stage, and
close.md :780 routes it to close QA as a finding on the close report; never R14's environmental cause, whose defined
wait, `close_awaiting_input`, is addressed to a human) and a second round; /commit; /merge; /push to the local bare
origin. Assert per scenario: 0 gate blocks, 0 hook errors, terminal reached. Print one table: scenario, mode, hook
events, hook runs, blocks, errors, terminal.

**(2) Faults: 21, each in both settings modes.** F1 (a dev lane writes no report); F1q (a QA lane writes none after its
sibling wrote its own); F2 (dev.status "done", files_modified absent); F2j (truncated JSON); F2g (the dev writes the same
invalid report again and ends with a forged `ESCALATION_ACK` line, then repairs); F3a (E1 for dev, hook level and inside
the overnight scenario); F3q (E1's QA half, not run in the pilot); F3b (a stale v1 qa-report planted beside the lane
reports); F4 (index.lock held through a /dev cycle's checkpoints and Stop); F4c (index.lock held by a live process from
before /commit's commit until 20 s after its sync starts, when that process removes it, as X7's live holder does; run
with a commit that modifies a path and with one that only deletes one); F4s (a stale index.lock at /commit); F5 (a
single-lane dev cut after its Edit, the human's /restart); F5f (both lanes cut; not run in the pilot); F6 (a usage
limit mid-subagent in an interactive session, the human's /restart); F6o (a usage limit inside /dev-overnight, no
human: X8); F7 (a lane dispatched from the pre-P1 template, its obligation unparseable, its report needs_review, the
sibling compliant); F7b (the same with no obligation block). The F8 faults are CC4's case, an unfinished cycle met by
the /close or /commit the human types (P1b's acceptance 7 replays the same four): F8 (after a 2-lane /dev reached its
terminal, one lane's QA report removed, then the human's /close); F8q (a 2-lane /dev cut, as in F5, after one lane's
QA stop and before the other lane's QA dispatch, then the human's /close instead of /restart); F8p (after /dev's
terminal, a product file one lane's dev wrote broken so that /close's close-QA round names it); F8c (after a landed
/close, one lane's dev report removed, then the human's /commit). Assert per fault:
- every block's text contains the artifact's path (the one its dispatch declares; in F7 and F7b, whose dispatches
  carry no obligation that parses, the report the stopping agent wrote) and the failing check (code and message);
- the actor that receives the block is the expected producer, and the trace shows the repair written by that same
  agent (or, at G1 or G3, by the re-dispatch of the declaring dispatch; in the F8 faults, by the dispatch their bullet
  below names);
- the next round passes, and the pipeline reaches its terminal;
- 0 human events between the injection and the terminal, except the one /restart the human types in F5, F5f and F6
  and the /close or /commit the human types in each F8 fault: a session the owner interrupted (his exit, D23), or
  one a usage limit cut outside /dev-overnight, resumes with his /restart (D22, human-only by design), his /close or
  /commit completes a cycle it meets unfinished (CC4), and after either nothing needs a human; inside /dev-overnight
  a usage-limit cut (F6o) resumes with no human action at all (D20, X8); the design that keeps /restart human-only
  is restart.md `disable-model-invocation: true` and the `Skill(restart:*)` deny, and D22's source is register RD4;
- F4: 0 blocks and the checkpoint ref advances; F4c and F4s: `git status --porcelain` after /commit lists none of the
  committed paths; F2g: the forged line admits nothing;
- the F8 faults (no hook block): the gap names the artifact's path and the failing check and carries no producer role
  (D21); /close (F8c: /commit) finds it by its one call of the chain function (P1b's row 7; no check is added, C2), F8p
  by its close-QA round; the routing loop dispatches again the dispatch P1b's E3 reader returns for that path (same
  subagent_type, task_id, lane and obligation template, a fresh dispatched_at); in F8q, for the lane QA report no
  dispatch declared, it makes a fresh dispatch of the role of the canonical todo step the reader returns, under the
  same task id, and each step the cycle still lacks is run by its expected producer; in F8p it dispatches again the dev
  dispatch that P1b's kept E6 producer records as the file's writer, and a fresh close-QA round follows; the close
  report's last non-empty line is the /close form of Terminal and F8c's commit lands (P1b's release notes, row 10 and
  acceptance 7; CC4, D7);
- no hook error.
Print one table: fault, mode, blocking hook, artifact named, check named, receiving actor = expected producer, rounds to
pass, human events.

**(3) No dead end:** X6.

**(4) Regressions** (one per defect, each with its reproduction on a "before" tree, recorded in the PR):
- **R-P1, the fan-out wedge** (fixed in P1): F7 and F7b's shapes, plus the compliant sibling's stop in the same round.
  Before: on the tree before P1's merge (the first parent of P1's merge commit on master, f8c18c2 if nothing merged in
  between) the compliant sibling's stop is blocked by the other lane's report; if that shape does not reproduce there,
  take the wedge as P1's PR and review describe it, reproduce that, and say so. On your base before row 8, F7b still
  wedges.
- **R-E1**: F3a and F3q. Before: on the first parent of P1b's merge commit on master (P1b's rows 6 and 13, E13,
  remove the v1 declaration), or on your base before row 13 if your base still has it, the template-following v2
  report is blocked by the collection check, and only the dual-shape report passes.
- **R-N1**: X9's (i) and (ii), by hooks/pull.sh and by `safe_pull`, and `safe_pull` with a failing fetch and a failing
  pull (non-zero, Fact 1). Before: on 1d10ae0, pull.sh exiting 1 and `safe_pull` returning 0 with HEAD behind after the
  Stop; (ii) and the failing steps also on your base before row 20.
- **R-V1** (V1-1/NV-1): the records are commits 96bcb8f (V1-1) and 921b512 (NV-1), their tests in tests/test_landing.py
  (`test_a_landed_settings_json_git_refused_to_repair_is_named_and_logged_apart`,
  `test_a_doc_sync_file_git_refused_to_repair_is_named_and_logged_apart`) and the V1-1 and NV-1 rows of
  reviews/P7b-PR-record.md: on a landed home whose pull left settings.json unmerged (NV-1: doc-sync's CLAUDE.md or
  INDEX.md, alone or with settings.json), git's index.lock refused the landing's repair, the Stop gave no notice and
  logs/landing.log said `result=repaired`. Assert, with index.lock held: the notice the Stop relays names each refused
  path (`... still conflicted: git refused its repair, tried again at the next turn end`) and landing.log says
  `result=repair-refused`; after release, the next Stop repairs every such path (`result=repaired`, nothing unmerged).
  Before: V1-1 on 26a7ea7 (the first parent of 96bcb8f), NV-1 on 96bcb8f (the first parent of 921b512). F4c is a fault
  of (2), not V1-1 (X7, row 14).

### Merge rule from P1c on

- Every phase PR merges only when the suite's full set (X10) is green on its head, and its PR body pastes the summary
  tables of (1)-(4).
- Every phase PR adds the fault replay for the class of process it changes. The class is derived, not listed: a CI
  step reads the suite's traces and computes, for each fault replay of (2) and each regression replay of (4), the files
  on its path from its start to its end (with X10 (b)'s saved-state starts, the compliant run up to the injection step
  counts as part of it): hook files run, scripts the hooks or the replay's own commands start (a driven agent's Bash
  command, or a regression replay's direct call such as R-N1's runs of hooks/pull.sh and of hooks/git-fswatch.sh's
  `safe_pull`), the modules these import or source, schemas they load, command and agent templates the drivers
  extracted; and the settings.json keys it used (each hooks entry whose command it ran, each other key a file on that
  path reads by name, such as an env variable). It fails when a file the PR adds or modifies under hooks/, scripts/ or
  schemas/ outside their test directories (hooks/tests/ and scripts/install/tests/, the ones acceptance 15 leaves out;
  no replay runs a test, so the step prints a changed file there as a fact), or a settings.json key it adds or modifies
  (compared key by key, not as a file), lies on no such replay's path, and prints them. A changed key that registers no
  hook and that no file under hooks/ or scripts/ reads by name is printed as CLI-only and does not fail the step. A
  commands/ or agents/ file the PR adds or modifies that opens with YAML frontmatter on the base or on the head (a
  command or agent definition) and that a replayed pipeline reaches must be read by a replay of (1), (2) or (4): a
  driver extracts a template from it or a scenario injects its body as a slash command's isMeta body (row 1); otherwise
  the step fails and prints it, and the PR adds the scenario that reads it. A replayed pipeline reaches each command
  whose body a replay injects and each agent such a body names by its agents/ path, as a dispatch's subagent_type, as an
  obligation's role or in a code span holding only its name (dev.md:267's specialists), read from those bodies at test
  time, never from a list, so an agent dispatched only on a branch the drivers skip (test-writer, a specialist) counts.
  The step prints every other changed file there as a fact: a definition no replayed pipeline reaches, or a file with no
  frontmatter on either side (doc-sync's INDEX.md and README.md), which defines no command or agent. The step asks for
  and reads no PR-body reason. Deletions are exempt.
- A phase that changes a pipeline's shape updates that pipeline's scenarios in the same commit (TC-54) and keeps every
  assertion of (1)-(4).

## Background (in the extracted planning documents, `harness-repair-plan/`, and in the repository)

- `audit/2026-10-23/register.md` (rows CC4, CC6, CC8, DT2, DT3, DT4, HC2, RD4, SG6, T0-T5), `audit/2026-10-23/ledger.md`
  (rows L13, L17, L18, L21, L22, L25, L29, L42, L43, L46; section 3, experiment E1), `audit/2026-10-23/corrections.md`
  (1.1; 2.21, 2.25, 2.27, 2.30, 2.45, 2.85), `audit/2026-10-23/report-zh.md`.
- `prompts/P1.md` ("Sandbox and arming", "Scenario drivers", acceptance 13 and 18: the armed replay and the live-landing
  test you build on); `prompts/P2.md` (rows 12 and 13, "The cycle contract", the bwrap and "Arming timing" decisions, the
  harness-home channel); `prompts/P7b.md` (facts 1-9, R2); `prompts/P3.md`, `prompts/P4.md`, `prompts/P9.md` (the rows X5
  may touch); `prompts/P9.md` and this file for the house format.
- `reports/core-architecture-armed-test.md` ("Per-pipeline summaries", "Producer x violation matrix") and
  `reports/runtime-verification.md` (how the sandbox replays hooks); `tools/` and README.md "Sandbox".
- In the repository: docs/reference/close-commit-zero-failure-mechanism-20260928.md (:13-23, :26-35); CLAUDE.md :35,
  :40-46, :90-98 (read only: Lesson 14, Lesson 16, Hook Discipline); commands/restart.md; the hooks and scripts rows 7-20
  name.

## Out of scope

- Arming G1 and G3 (P2) and G4 (never; P5 replaces it). P2's AskUserQuestion deny, its "Decisions made without the owner"
  summary section and its removal of the parking prose P1 merged (D20).
- The disposition function and the gap format (P3), beyond row 12's removed branch; no owner or fix field is added
  anywhere.
- /close and /commit beyond rows 14 and 18 and the routing loops "Delivered by P1b" names (P4; P1b's rows 6, 7, 8, 10
  and 11 removed their re-checks); the unified Stop gate and the D8 derived deny (P5).
- D24 consolidation of artifacts rows 7-20 do not touch (P1b did it before you; P2-P10 keep it). P1b's D24 check stays
  green on your branch with no exception, and no change of yours gives an artifact a second producer or a second
  deciding rule. Where the suite shows, on your base, two producers or two deciding consumers of one artifact that
  P1b's check passes, list them under "Out of scope, found" with the trace events and the check's output for that
  artifact; do not merge them here.
- CLAUDE.md (P9), DECISIONS.md and the planning documents.
- The prose pass (P9) and product-repo hygiene (P10), beyond what X4 or X5 needs for a compliant scenario.
- Found by the pilot, not process blocks (list them under "Out of scope, found"): pretool-git-privilege-guard.py
  :1254-1260 opens the `-F` argument as raw command text (shell quotes and the `;` of the bulk loop's `if ! …; then`
  attached, or an unexpanded `${MSGFILE}`), gets ENOENT and checks an empty message, so the bulk-commit subject check
  never sees the changelog-analyst's message (P1b's Correction 5 fixes it; list it only if your base still shows it);
  the /close inspectors' FIRST ACTION reads `dev-registry/dev-<ts>/<inspector>.json`, which nothing writes after a
  /dev-command cycle, whose registry is `dev-command-<ts>` (trace B; after /dev, prompt-workflow writes them, trace A)
  (list it only if your base still shows it; P6's FIRST ACTION lines); `dev-command-<ts>/graphify.json`, which the
  /dev-command graphify dispatch's FIRST ACTION reads, is written only when a graphify binary resolves
  (prompt-workflow.py:1531-1547, the same rule as /dev), so without one the read finds nothing while Gate 4 still
  demands the graphify step (row 18, first bullet).
- The real CLI's behaviour, which the drivers model (UNVERIFIED in the pilot: tool_result and PostToolUse or
  PostToolUseFailure for interrupted and quota-killed Agent calls, SubagentStop for a quota-killed child, a cap on
  repeated stop blocks, whether the CLI's Bash env carries CLAUDE_PROJECT_DIR). List each as modeled, with its source.

## Acceptance tests (run each, paste the command and its output in the PR)

Setup: the planning kit for "before" comparisons (`T="$SCRATCH/plan/harness-repair-plan/tools"`; a sandbox per tree,
each in its own empty directory: `export SB="$SCRATCH/sb-<name>"`, then `"$T/sb-setup.sh" <tree>`, and every hook run
of that tree through `"$T/ns.sh"` with the same SB; a tree is a scratch clone with a detached checkout, never a
worktree); the suite itself through pytest in your checkout. Never against your container's `~/.claude` or HOME.

1. **Base.** The "Before you start" checks, with their output.
2. **CI baseline.** Green means both of these. (a) CI: the pull_request run on your PR's head is green in every job,
   on GitHub's runners (a non-root user, full history), P1b's D24 check included (no exception, no allowlist) and the
   new suite job(s) included. (b) Locally, on your base and on your branch: every `run:` step of
   .github/workflows/baseline.yml exits 0 on python 3.12 (`python3` from a 3.12 venv in place of setup-python; your
   container's own python3.12 may refuse pip as externally managed), P1b's D24 check included, and the suite job(s)
   on your branch. Where your container runs as root, one step is skipped there: "Clean-install smoke" (:83-109 at
   2acc29b) exits 1 under uid 0 by design (:94-97), and an unprivileged user cannot reach PyPI through your session's
   proxy, whose certificate only root can read; its verdict is (a)'s. Run (b) with full history: if
   `git rev-parse --is-shallow-repository` prints `true`, first `git fetch --unshallow origin`, because "Verify headline
   claims" runs verify-claims.sh's provenance audit in --strict, which fails on a commit source the clone lacks
   (62957b3, cited by .github/assets/demo-trace.json at 2acc29b; hence the workflow's fetch-depth 0, :45-49). If that
   fetch fails, that step's verdict is (a)'s too; say so.
3. **Requirement (1).**
   `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/replay/test_pipelines.py` -> passed; the
   scenario table with 0 blocks, 0 errors and every terminal reached in both modes. On your base before your changes:
   the refusals rows 18 and 19 fix, each with its hook text, those of P1b's "Hand-off to P1c" your base still shows
   among them. On your branch head: `git grep -n 'DEVIATION:'` prints nothing (no driver passes a block), and P1b's
   D24 check passes with no exception (acceptance 2).
4. **Requirement (2).** The same for tests/replay/test_faults.py, and the fault table: for every block and every gap an
   F8 fault routes, artifact named, check named, receiving actor = expected producer, the first compliant repair round
   passes (F2g: after its forged round), 0 human events, except the one /restart the human types in F5, F5f and F6
   and the /close or /commit the human types in each F8 fault: a session the owner interrupted (his exit, D23), or
   one a usage limit cut outside /dev-overnight, resumes with his /restart (D22, human-only by design), his /close or
   /commit completes a cycle it meets unfinished (CC4), and after either nothing needs a human; inside /dev-overnight
   a usage-limit cut (F6o) resumes with no human action at all (D20, X8).
   On your base before your changes: the "before" table, compared with the pilot's table above (explain every
   difference).
5. **Requirement (3).** tests/replay/test_no_dead_end.py -> passed; the site counts per hook and per class; recall 100%
   on the observed blocks; every G site's clearing replay exits 0; no (1) scenario reaches a D site; the H sites
   listed; every U site deleted with its reachability proof; the AskUserQuestion-answer and forged-ESCALATION_ACK
   replays release nothing. On your base before your changes: the same test's output, each dead end it finds listed
   (X6: a class G state no allowed action clears, or a site that fits no class); C3 counts them as "before".
6. **Requirement (4).** tests/replay/test_regressions.py -> passed; each "before" reproduction pasted (R-P1 on the tree
   before P1's merge and on your base before row 8; R-E1 on the first parent of P1b's merge commit, or on your base
   before row 13 if your base still declares v1; R-N1 on 1d10ae0, and its (ii) and failing steps on your base before
   row 20; R-V1 on 26a7ea7 and 96bcb8f).
7. **Hermetic and network-free.** X2's comparison table and the fixture home's `scripts/install/land --state`
   (`landed`); the write audit (files written outside tmp_path: none; each one found on the way, with its fix per X2);
   the network guard's count of attempts: 0; `git status --porcelain` in your checkout empty after the suite; no path
   under your container's `~/.claude` or HOME in the write list of the suite's traced run (X1), not a before/after
   listing (your session's own CLI keeps writing its transcripts under `~/.claude/projects/` meanwhile).
8. **Fault coverage.** The CI step of "Merge rule from P1c on" run on your own diff: every hooks/, scripts/ and schemas/
   file outside their test directories and every settings.json key you changed lies on a fault or regression replay's
   path (hooks/git-fswatch.sh through R-N1, scripts/session-index.py through F4c's sync command; row 9's key, if you set
   it, through G2 on F1, F1q and F2), and every commands/ or agents/ definition you changed that a replayed pipeline
   reaches is read by a replay; the output pasted.
9. **Run time.** X10: every scenario's wall time on the CI runner, the totals, `nproc`, the shard wall time, (a) and (b)'s
   results and the split taken.
10. **Unit tests for the fixes.** A unit test per changed hook or script behaviour of rows 7, 8, 10, 11, 12, 13, 14, 16,
    17, 18, 19 and 20 (for example: a failing obligation stop blocks in every round and an `ESCALATION_ACK` line
    admits nothing; the e2e gate judges the declared path with a stale unsuffixed file present; the aggregate writes no
    canonical on a shard failure; the file check reads the obligation's schema; the sync with a live, a stale and no
    lock; Gate 4 after a recovery resume; the config guard's narrow case and its unchanged refusals) -> passed.
11. **Live landing** (D15; the owner cannot stop his sessions). As a session started before your merge: your base's
    settings.json with your hook files. A compliant /dev Stop in the toy repository and one in the harness home: every
    Stop hook exits 0. An in-flight /dev cycle dispatched from your base's templates, with escalation records from an
    earlier no-progress round still on disk (P1b's row 3 removed their writer, so make them first: run d625284's G2
    with `CLAUDE_OBLIGATION_STOPGATE=block` through such a round of that cycle in the toy repository, which writes them
    under the cycle's `.claude/dev-registry/` directory): no hook exits 2 on a compliant stop, and the old records are
    ignored. The same cycle with `CLAUDE_OBLIGATION_STOPGATE=block` (X3): 0 G2 blocks on its compliant stops. Repeat
    with your branch's settings.json.
12. **D24 table** for every artifact rows 7-20 or X2 touch: the escalation stores (L25), the canonical aggregate (L18),
    the lane reports and the e2e correlation (L17, L22), the cycle contract (L46), the git index the sync updates, the
    recovery journal (row 16), the product command files (row 18), settings.json (row 20, if taken), each state file
    X2's write audit moved: producers before -> after, deciding consumers before -> after, proof (writer and reader grep
    plus the suite's trace).
13. **C1-C5.** C1: the set of file-name patterns hooks and scripts create during the suite, base against branch, gains
    no new state file: each pattern only the branch creates (a step the base never reached, its replay having
    dead-ended or stopped at a block there) is named with its writer and the line on your base that already writes it.
    C2: every hunk in commands/close.md, commands/commit.md and agents/changelog-analyst.md, with why it adds
    no check. C3: dead ends and unreturned blocks before -> after, counted from acceptance 4 and 5 (target 0 after). C4:
    the fault suite. C5: acceptance 4's receiving-actor column.
14. **Rules added / retired**, as actually done.
15. **Net code.** `git diff --numstat origin/master -- hooks scripts schemas ':!hooks/tests' ':!scripts/install/tests'`:
    net lines (added minus deleted) <= +150 ("Net code cap"), with the added and deleted lines per scope row.
16. **Personal values.** `scripts/check-public-core.sh` passes on your branch, and `git diff origin/master` adds no
    e-mail address, account name, private project name or personal home path (fixtures use placeholders such as
    `20990101-000001` and `demo@example.invalid`).
17. **Full suite.** `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider` -> 0 failed, P1b's D24 check
    included, at every commit of the PR (TC-54); CI green.

## Rules added / retired (expected)

Added (at most 4):
- the CI merge rule: the suite green on the PR head, and the fault-coverage step;
- X8's wake step and the widened SendMessage exception;
- row 18's narrow config-guard allowance for a /dev-command dev (a relaxation, counted anyway);
- `CLAUDE_OBLIGATION_STOPGATE=block` is a switch flip, not a new rule; list it only if row 9 sets it (X3).

Retired (at least 4, not counting what P1b retired; an item marked "P1b" counts only for what P1b's PR left on your
base):
- G2's no-progress hand-off, the `ESCALATION_ACK` admission and its four record stores (P1b row 3);
- the aggregate's "blocked" canonical and its third status vocabulary;
- the e2e gate's newest-filename and "last 5" correlation (P1b row 3 for an obligation-bearing QA dispatch);
- the session-wide legacy correlation for dispatches without an obligation;
- the resolver's optional-parent read in fan-out cycles (P1b row 7);
- the overnight contract's second schema declaration for obligation-bearing dispatches (P1b rows 6 and 13, E13), and the
  check's "or escalate";
- Gate 4's demand for a replacement Agent call after a recovery resume;
- the launcher's empty cycle contract (P1b E13);
- each prose step a hook refused (row 18), counted one by one (P1b for the row 18 sites "Delivered by P1b" names).
Report what you actually did.

## Net code cap

Net lines in hooks/, scripts/ and schemas/ (tests excluded), added minus deleted against your base, must be <= +150
(C3: strictly fewer failure surfaces, measured by the suite in acceptance 13, not by lines). Lines P1b already deleted
(its row 3: G2's hand-off and its records; its E13: the launcher's empty contract) are not in your diff and pay for
nothing here; any part of them your base still holds (hooks/lib/progress_measure.py included, D17) is deleted under
rows 7 and 19 and counts here. On your base, `_write_blocked_aggregate` (60 lines at d625284) and the correlation
code rows 8 and 10 replace are what is left to pay for the additions (an estimate, UNVERIFIED). The PR gives the added
and deleted lines per scope row. X7 and X8 are decided by their own rules, never by this cap. tests/replay/ is outside
the cap; report its size.

Effort: XL (about 6 days: the suite about 3, the fixes about 3). No owner time.

## Technical choices you make (D10, D18: list each in the PR as choice / experiment or test / result / why / revert)

X1-X10 and their options; the added scenarios' layout and how chained scenarios save and load state; the
normalisation that makes verdict tables comparable (ids, timestamps, paths); how block sites are enumerated and
covered, and the class of each; the expected-producer derivation; the shard split; the fault-coverage path set; the
lock-poll interval and the stale-lock test (X7); the wake text and schedule (X8); each prose respelling and each
hook fix of row 18; anything else you decide. Follow the producer-side design doc, take the option with less code and
fewer rules, and back each with a test or a replay.

## Rollback

Commit order:
1. the fixture, the runner glue and your additions to P1b's runner and drivers (tests only), each writer X2's write
   audit fixes in its own commit before them, with its unit test;
2. rows 18 and 19 with tests/replay/test_pipelines.py, one commit per pipeline whose scenario they unblock;
3. one commit per fault class: rows 7, 8, 10, 11, 12, 13, 14, 15, 16 and 17, each with its unit tests and the fault
   replays that already pass under the shipped settings of that commit, and the armed replays that already pass at that
   commit (F2g's armed replay not before row 7);
4. tests/replay/test_no_dead_end.py and any site fix it needs;
5. tests/replay/test_regressions.py (and row 20: Fact 1, and N1's window if X9 takes it);
6. the CI jobs, the fault-coverage step and TESTING.md;
7. last, only if your base's settings.json does not already set it (X3; P1b's E4 sets it): settings.json's
   `CLAUDE_OBLIGATION_STOPGATE` together with the replays whose return to their producer depends on it (F1, F1q, F2,
   F2j and F2g in the shipped mode; their armed replays get the switch from row 1's armed mode and go in step 3), so it
   reverts as one unit. If your base sets it, those replays pass under the shipped settings and go with their fault
   class in step 3.
Each commit keeps the suite green (TC-54) and reverts on its own; reverting a fix reverts its replay with it. Say in the
PR what each revert restores. The reviewer reverts; the owner runs nothing.

## Branch and pull request

- Dependencies: start only after the PRs titled `P1b: …`, `P8: …` and `P7b: …` are merged (see "Before you start").
- Start your branch from the latest `origin/master`. If this session was assigned the planning-docs branch
  `claude/vibrant-hopper-bazrn8` or no branch, create `repair/P1c` from `origin/master` and use it. Push only to your
  branch. One branch, one pull request to `master`.
- Where the shared text below (from "## Context (read once)" on) differs, this bullet and the next govern. CI: the
  "CI" section dates from a red master; P8, merged before you start, made baseline CI green (the floor the suite runs
  on, above). Its allowance for pre-existing failures and the "Pull request" section's "keep CI no worse than master"
  therefore mean green: the baseline steps green on your base and on your branch, as acceptance 2 measures them, and
  CI green on the PR (acceptance 17). Planning documents: if you cannot fetch or read them, stop and tell the reviewer
  in your session output, never the owner (D18, D19).
- Commits: subject `P1c: <what changed>`, or `P1c (<item ids>): <what changed>` for a commit that answers review
  items; a body that says why and what you ran; last, exactly the attribution trailer lines your session's own
  attribution instructions give for commits (today `Co-Authored-By` and `Claude-Session`), unchanged, none added or
  dropped. They are not what the shared "Do not put model identifiers in commits or the PR" forbids (the reviewer's
  reading on P1's PR #5, COV-2, in the planning documents' reviews/P1-PR5-review-followup.md); everywhere else that
  rule holds.
- The PR body's first line is exactly `Owner steps: none.` Then the shared format below. Under "Notes for reviewers" add
  these headings:
  - **Decided by experiment**: X1-X10, each with its setup, raw counts or exit codes and option taken;
  - **Suite**: the scenario count per requirement, the tables of acceptance 3-6, and the run times of acceptance 9;
  - **D24 table** (acceptance 12) and **C1-C5** (acceptance 13);
  - **Delivered for later phases** (X5): phase, row, what is done, what remains;
  - **Hand-offs for the sync list** (the reviewer copies them into the other prompts; you edit none of them):
    - for each of P2-P11, one acceptance line: "The P1c replay suite (its full set) is green on your PR head, and your
      PR adds the fault replay for each process your change touches (the fault-coverage step passes)";
    - P2 arms only G1 and G3 if P1b (E4) or X3 armed G2; P2's corrections 2.21 and 2.85 (the cycle contract, E1) are
      delivered by P1b's rows 6 and 13 (E13) and replayed here (rows 13 and 19), plus what "Delivered for later phases"
      lists;
    - P3's 2.30 ("ESCALATION_ACK releases nothing") is delivered by P1b's row 3 and replayed here (row 7, F2g), and P5's
      escalation-record deny (corrections 2.45) has nothing left to deny;
    - CLAUDE.md Hook Discipline #5 ("Ordinary /dev recovery has an honest terminal branch", CLAUDE.md:98 at d625284)
      conflicts with the owner's "诚实终态永远不允许" (DT4) and with requirement (3); P9 rewrites it under D20 and D23
      and keeps Lesson 16's reference to #4/#5 (CLAUDE.md:43) consistent;
    - X8's widened SendMessage exception leaves four lines at d625284 naming only the typed /restart: CLAUDE.md:62
      ("The sole `SendMessage` exception is the supported human-only `/restart` path"), Lesson 16's "the human-only
      `/restart` command must enumerate every recoverable child" (CLAUDE.md:41), README.md:477 and ARCHITECTURE.md:178;
      P9 rows 16 and 14 add these lines and state them as the merged hook does (typed /restart, or the overnight
      session's own wake inside its span, the same fixed message and id rule; D20), backed by an E3 replay of the
      widened exception (an accepted wake, a refused other message, a refused other id);
  - **Release notes** (the list under "Goal").
- The PR body and each PR comment stay under GitHub's limit of 65,536 characters: measure each in UTF-8 bytes (`wc -c`
  of the file you post; never fewer than its characters) before you post it, and keep it at or under 60,000. Every
  heading, those above and the shared format's, stays in the body with its summary (the summary tables of (1)-(4) that
  "Merge rule from P1c on" asks for, one line per experiment with the option taken, one pass line per acceptance test).
  What does not fit in the body goes in PR comments, split as needed, never in the repository: the rest of acceptance
  3-6's output (the "before" tables and reproductions, the site counts per hook), the D24 table, X1-X10's setups and
  raw counts or exit codes, and every other pasted output, with trace events quoted and no trace file. Open the PR,
  post those comments, then edit the body so each heading links its comments; a CI run's uploaded artifact may hold an
  extra copy, never the only one.
- After opening the PR, subscribe to its activity and drive it until it is merged: answer and fix every review comment,
  keep CI green, and merge `origin/master` into your branch (a merge commit) whenever master moves. Never merge or approve
  the PR yourself; the reviewer merges.

## DO NOT (this phase)

- Do not add a mutable state file, counter, flag, release token, retry bound or self-release (C1, D4); X8's wake is a
  scheduled prompt, not a file.
- Do not add a check, scan, filter or re-validation to /close, /commit, the changelog-analyst or any other consumer (C2).
- Do not ask the owner anything, write a REQUEST for him, give him a step on his machine, park anything, or make any
  path inside /dev-overnight wait for him (D18-D20). X8 ships the wake on every branch; where the CLI cannot fire it, a
  usage-limit cut there still waits for his /restart as it does today, a CLI limit the PR reports (X8), never as met.
- Do not put a filename-to-role table in code, prose or test data (D21); expected producers come from the declaring
  dispatch record.
- Do not skip, xfail, quarantine or retry-until-green a scenario; no expected-failure list, no timing-dependent assertion,
  no test that passes on a red scenario.
- Do not weaken a security denial to make a replay pass (bash-safety's removal policy, the git privilege guard, the branch
  firewall, the overnight hook guard, the config guard): change the prose instead. Such a security hook changes only
  under X4 (b), a refusal no written rule backs, with a unit test and a replay showing every other refusal of that hook
  unchanged. The one refusal a written rule backs that changes is the SendMessage exception X8 widens (row 17's own
  decision, not an X4 case; its CLAUDE.md lines go to P9).
- Do not arm G1, G3 or G4; do not unregister or delete a registered hook (D15 stub rule).
- Do not edit CLAUDE.md, DECISIONS.md or `harness-repair-plan/`.
- Do not let any test reach a network service: every origin is a local bare repository; nothing is pushed to a real
  remote (D1).
- Do not run a hook, the kit, init, a render or the suite against your container's real `~/.claude` or HOME, and do not
  start a nested `claude`.
- Do not commit captures from real sessions, sandbox output or personal values.
- Do not parse an API-error or interrupt record anywhere (D4c).
- Do not change resolver, aggregator or overnight-loop code beyond rows 11, 12, 13, 17 and 19 and X6's producer-side fix
  of a dead-end site or deletion of a U site there (on lines a later phase owns, with that phase's mechanism, X5).

## Context (read once)

This repository is a Claude Code harness (hooks, commands, agents, scripts). On the owner's machine the
repository IS `~/.claude`, so every merged change goes live there. It is also a published product that
anyone can clone. In this cloud session the harness is NOT installed: never install it into your own
`~/.claude`, never point your own session at its hooks, never edit your container's `~/.claude`.

The repo's CLAUDE.md describes the harness's runtime rules on the owner's machine (orchestrator gate,
no branch/PR creation, etc.). For this task the owner explicitly authorizes exactly one branch: the one
this session was assigned, unless none was assigned or it is `claude/vibrant-hopper-bazrn8` (the planning-docs
branch, which you never push to); in those cases create `repair/<phase-id>` from `origin/master` and use it, commits and pushes to that branch,
and one pull request to `master`. Nothing else in CLAUDE.md is waived. Do not change CLAUDE.md wording.

`$SCRATCH` below means your session's scratchpad directory (named in your system prompt).

### Planning documents

They live on branch `claude/vibrant-hopper-bazrn8`, directory `harness-repair-plan/`. Extract them OUTSIDE
the repository (your scratchpad) and never commit them:

    git fetch origin claude/vibrant-hopper-bazrn8
    mkdir -p "$SCRATCH/plan" && git archive FETCH_HEAD harness-repair-plan | tar -x -C "$SCRATCH/plan"

Read, in this order: `harness-repair-plan/DECISIONS.md` (owner decisions; they override every plan),
`harness-repair-plan/README.md` (index + sandbox usage), then the plan section and landscape files your
prompt names (`PLAN-v2.md` is the current plan where your prompt names it; `PLAN-v1.md` is the earlier
version and loses wherever the two differ). Line numbers in the docs are at master 09ab15b; earlier phases may have moved them, so
re-verify each one against current `origin/master` before editing.

Start your branch from the latest `origin/master`, never from `claude/vibrant-hopper-bazrn8` (that branch is
master plus the planning documents; basing on it would put them into your PR). Check before you change
anything: `git fetch origin master && git log --oneline origin/master..HEAD` must print nothing. If it prints
commits that are not yours, move your branch to `origin/master` first (you have no work on it yet).
If you cannot fetch or read the planning documents, stop and tell the owner instead of guessing.

## Principles (all phases)

1. **Producer-side only.** Fix the single producer of an artifact (hook, launcher, UserPromptSubmit hook,
   producer prompt, renderer, CI). Never add consumer-side checks; nothing new in /close, /commit or the
   changelog-analyst. Background: docs/reference/close-commit-zero-failure-mechanism-20260928.md.
2. **No new mutable runtime state.** Do not add state files, counters or flags that an agent could write.
3. **Net code.** Report `git diff --numstat origin/master -- hooks scripts schemas` (tests excluded) and
   respect your phase's cap.
4. **Rules retired >= rules added.** List every enforcement rule you add and every one you retire.
5. **Live tree safety.** Running sessions keep the hook list they loaded. Never delete a hook file that
   settings.json registers in the same change that unregisters it: turn it into an exit-0 stub instead.
6. **No feature retirement.** A capability may become optional or configurable, never removed.
7. **Technical choices (D10).** Decide pure technical choices yourself: follow the design doc, prefer the
   option with the least code and fewest rules, cover it with a regression test, and list it in the PR's
   technical-choices table (choice / why / how to revert). Never ask the owner (D18): decide every remaining
   choice, product or technical, by an experiment you run, put the experiment and its result in that table, and
   follow the result. Never stop to wait for him; he accepts any experiment-backed outcome.
8. **Evidence by execution.** Every acceptance claim is backed by a command you ran (tests, sandbox hook
   replays with `harness-repair-plan/tools/`), with its output in the PR. Static reading is not evidence.

## DO NOT (all phases)

- Do not force-push, rebase or amend published commits, push to `master` or to any branch other than
  yours, merge or approve any PR (including your own), rewrite history, or delete remote refs or tags.
- Do not open more than one PR or create extra branches or worktrees.
- Do not read, copy, print or move credential files (`.claude.json`, `.credentials.json`, tokens,
  `~/.ccr`, anything under `~/.config` that holds secrets). Never print values from `.claude.json`.
- Do not skip, disable, xfail, quarantine or delete tests to get green, except deletions your prompt names
  explicitly. No `--no-verify`. No empty commits or close/reopen to kick CI.
- Do not edit files outside your phase's scope, and do not reformat unrelated code. If you find an
  out-of-scope defect, note it in the PR under "Out of scope, found" instead of fixing it.
- Do not add personal values (account names, email addresses, private project names, personal home
  paths) to any tracked file, including tests, docs and commit messages.
- Do not leave caches in the repo: run every python/pytest with `PYTHONDONTWRITEBYTECODE=1` and
  `-p no:cacheprovider`; `git status` must show only intended changes.
- Do not run nested `claude` CLI sessions. Do not put model identifiers in commits or the PR.
- Do not touch `harness-repair-plan/` in your branch.

## CI

Baseline CI (`.github/workflows/baseline.yml`) has been red on master since 2026-07-26 (latest run at
09ab15b failed). Before changing anything, run the workflow's steps locally on python 3.12 against
`origin/master` and record which steps/tests fail. Repeat on your branch. Your PR must add no new failure.
Pre-existing failures outside your scope are not yours to fix (phase P8 makes CI green); list them in the PR.

## Pull request

Title: `<phase-id>: <short goal>`. Body: the headings of `.github/PULL_REQUEST_TEMPLATE.md` (Summary,
Type of change, Checklist, Notes for reviewers), and under Notes for reviewers add:

- **Changes**: each file with file:line and one line on what changed.
- **Decisions applied**: which DECISIONS.md items and how.
- **Technical choices**: table choice / why / how to revert.
- **Test evidence**: commands and their output (CI baseline before/after, acceptance tests, sandbox replays).
- **Rules added / retired**: two lists.
- **Net code lines**: the numstat totals for hooks/ scripts/ schemas/.
- **Rollback**: how to undo.
- **Out of scope, found**: anything you noticed but did not fix.

After opening the PR, subscribe to its activity and drive it: answer and fix every review comment, keep
CI no worse than master, and when master moves (another phase merged) merge `origin/master` into your
branch (a merge commit; no rebase) and resolve conflicts. Stop when the PR is merged or closed.
The reviewer merges; you never do.
