Owner steps: none.

# Phase P1b: one producer, one consumer per artifact

You are implementing phase P1b of the harness repair plan in this repository (the GitHub repository this session
cloned). Phase id for the PR title: `P1b` (for example `P1b: one producer and one deciding consumer per artifact`).

**Wave 2b: you run alone.** Wave 1 (P0 with its follow-up P0b, then P7) and P1 are merged: master
d625284db59399568c50424ea3162175d982ae04 is the base this prompt was written against, and every file:line below
refers to it unless it says otherwise. Two phases must be merged before you start: P8 (private tree, one privacy
engine, hermetic green CI; merged at 2acc29b from head 755860c; its head was 0d26692201986f86533f45851bfe5b38af95a057,
with green CI, when this prompt was planned) and P7b (zero-touch landing of P7 on a live home; re-implemented by the
reviewing session; merged at 301d696 from head 1071ad3). P1c follows you: it turns D25 (never fail) into a CI replay
suite and reuses the trace runner and the ten compliant pipeline drivers you ship. P2 (run in any repo, overnight start
and end, arm G1 and G3) and P3 (one disposition function, facts-only gaps) start only after P1c is merged. Do not wait
for anything except the two merges above; run independent experiments in parallel; never stop to ask.

**No owner step and no owner question (D19, D18).** Asked to run steps on his machine, the owner answered
(2026-10-18): "我自己在机器上做的是什么意思？我不做，没空，我不能停止claude" ("What does 'do it on your own machine'
mean? I won't do it, I have no time, I cannot stop Claude."). On 2026-10-19 he ended all arbitration: "我不会管以上你如何
决定，我只想告诉你你必须研究后再做决定，你的研究是有实验的研究而不是空口无凭，只要是有实验的无论实验结果我都接受 ... 不要让我裁决任何事情了"
("I don't care how you decide; you must research before deciding, with experiments, not empty words; I accept any
experiment-backed result ... don't make me arbitrate anything any more"). Every open choice in this phase is a
"Decided by experiment" block below, with its decision rule fixed before you run it. Nobody is asked. Your merge
reaches his live harness when he types /pull, while his sessions keep running with the hook list they loaded (D15),
so it must land on them safely (acceptance 17). The rollback is the reviewer's revert. The PR body's first line reads
"Owner steps: none."

**Before you start.**
- `git fetch origin master`, then `git merge-base --is-ancestor d625284db59399568c50424ea3162175d982ae04 origin/master`
  must succeed.
- `git log --merges --first-parent --format='%h %s' d625284..origin/master` must list the merges of the pull requests
  titled `P8: …` and `P7b: …`. git log prints the merge commit's subject, not the pull request's title; theirs are
  `Merge pull request #6: P8, private tree, one privacy engine, green hermetic CI` (2acc29b) and
  `Merge pull request #7: P7b, a live home lands P7 by itself` (301d696).
- Their products must be there: `git cat-file -e origin/master:scripts/install/land` succeeds (P7b's landing fast
  path; if P7b merged it under another name, find it from P7b's PR body and say so); `git cat-file -e
  origin/master:scripts/dev-fix.py` and `git cat-file -e origin/master:scripts/spec-update-contract.py` fail (P8's dead
  code deletions); the latest completed baseline CI run on master is green (P8): `gh run list --workflow baseline.yml
  --branch master --status completed --limit 1 --json conclusion,headSha,event` prints conclusion `success` (`headSha`
  names the commit it ran on). A run still queued or in progress (master moved a moment ago; a run's legs take 47-73
  minutes) is not a result: `--status completed` leaves it out, so neither wait for it nor read it as a failure. Without
  gh (not installed or not signed in), make the same query through the GitHub REST API, a GET of
  `/repos/<owner>/<repo>/actions/workflows/baseline.yml/runs?branch=master&status=completed&per_page=1` (its first run's
  `conclusion` and `head_sha`), or through any GitHub tool the session has; if nothing reaches GitHub, stop and tell the
  reviewer, as the next item says, that the CI check could not be read (E2's runs and the PR need GitHub too).
- If a check fails, stop and tell the reviewer in your session output (never the owner) that P1b starts only after P8
  and P7b are merged. Do not start from an older base.
- Then `git log --oneline d625284..origin/master` tells you what else merged. Find every location below again on
  your base and say in the PR which base you measured against.

**Interfaces you consume.** Read each on your base (read-only) and use it as merged; do not build a second one.
- P1: `hooks/lib/obligation.py` (`parse_obligation`, `TASK_ID_RE`, `canonical_task_id`, `registry_dir_for`,
  `resolve_own_obligation`, `TERMINAL_VOCABULARY`; it reads dispatch records through `hooks/lib/subagent_restart.py`
  `_read_parent_calls`), `hooks/lib/command_span.py` (at d625284 it ships `active_span` and the Span's command, args and
  start line; the accessors `calls()` and `last_todos()` that prompts/P1.md describes were deferred to their first
  consumer, which is you if E7 needs them), `hooks/lib/stop_contract.py`, the producer-question artifact, the `# STUB:`
  marker, the D5 clearers at UserPromptSubmit.
- P8: the hermetic test fixture in conftest.py, green CI collecting every test file, the one privacy engine
  (`scripts/check-public-core.sh`), and its D17 deletions.
- P7b (PR #7, merged at 301d696 from head 1071ad3; its file:line here are on master 2acc29b, where P8 is merged too):
  the landing (`scripts/install/land`, run at Stop by hooks/auto-commit.sh:23; `render-settings land` :1532,
  `cmd_land` :1493); its writes of P7's overlay `settings.machine.json` and, through init step 3's render, of P7's
  record `<git dir>/claude-settings.applied` (render-settings :65, written by `save_record` :285-289; land reads it
  at :31, :36, :44); its own `<git common dir>/claude-settings.checked` marker (land :195-201, kept as P7b's recorded
  departure NF-1) and `<git common dir>/claude-landing.lock` (land :206): the record, the marker and the lock are
  three files, map each; `logs/landing.log` (two writers: land :50, :226, :245 and render-settings `cmd_land` :1503;
  `LANDING_LOG` :1208; row 16 leaves land the one); the new readers of settings.json's env through
  hooks/lib/claude_home.py `settings_env` (:189; hooks/pretool-bash-safety.sh:8-14,
  hooks/lib/checkpoint-core.sh:344-349, hooks/lib/subagent_restart.py:824-830); the seeded private-literal list and the
  installed pre-commit hook.
- The planning kit `harness-repair-plan/tools/` and the d625284 map `harness-repair-plan/inventory/` (read-only
  planning evidence; see Step 1).

**What you hand to P1c.** The trace runner and the drivers that replay all ten pipeline commands compliantly
(acceptance 4), in the repository under tests/, so P1c can add fault injection, the dead-end check and the replays of
fixed process errors without rebuilding them. The drivers carry acceptance 4's marked deviations past the base's blocks;
P1c removes each in the commit that fixes its block (its rows 18-19); a deviation that fires only on the base's text
(acceptance 4) goes with no fix.

## Goal

1. **One producer per artifact (D24).** Every harness artifact (a file, a record or a fact one component writes and
   another reads) has exactly one producer. A consumer that rewrites or renames what it reads becomes a producer and
   stops doing it. One fact lives in one place.
2. **At least one consumer, and consumers trust one conclusion (D24).** An artifact written and never read is deleted
   at its producer. An artifact read and never written loses its reading branch. Several consumers may use an
   artifact, but only one rule decides on it: either they all call the one function that decides, or exactly one of
   them decides.
3. **Checks only at the allowed positions (owner rulings of 2026-09-27/28).** Artifact existence and correctness are
   established at the producer when it finishes (G2 and the producer's own stop) and by the orchestrator at dispatch
   (G1) and at collection (G3). Two more deciding reads are allowed, and neither carries a rule of its own: the single
   call of row 7's one chain function at /dev's end, /close and /commit (ruling 1, class a), its output used verbatim,
   and the command's Stop gate (D4; the end position D21 names; P5's unified gate), which decides the command's
   completion only from that function's conclusion, from git and from the stopping main agent's own artifacts (its own
   stop), and re-validates no subagent's artifact. Every other re-check and re-derivation goes: in /close and /commit,
   in scripts consumers run, in other hooks (G4's Stop re-validation among them, row 3), in prose steps. G1 and G3
   stay. You arm G2 and P2 arms G1 and G3 (E4); a consumer-side check whose faults only a still-advisory G1 or G3 would
   stop is not yet a re-check and goes in P2's arming commit.
4. **No filename-to-role table (D21).** Where a role or an owner is needed, it is read from the dispatch record that
   declared the artifact (its obligation's `role` and `artifacts[].path`), or, for an artifact no dispatch has declared
   yet, from the command's canonical todo step (`scripts/todo/<command>.py`). Hand-written role rosters, artifact-name
   lists and terminal vocabularies that repeat a declaration go.
5. **A CI check that proves it every time.** A test derives the write/read relations at test time (from code, and from
   a sandbox runtime trace where E1 shows static derivation is not reliable enough), asserts the invariants of goals
   1-4 directly, never compares against a committed TSV or any hand-written list, and has zero exceptions and no
   allowlist when P1b ends. Row 19 states, as rules in its code, what an artifact, a reader, one rule, a position, a
   re-check and a list that repeats a declaration are. It covers code and the command and agent text the drivers
   extract; a check written only as natural-language prose cannot be derived, so the rows delete it or move its rule
   into the gate (HC2, E4), and the PR lists each as deleted or moved, not as detected.
6. **Live landing.** Merged into a live home whose sessions keep running, nothing new blocks a compliant session or
   an in-flight cycle (acceptance 17).

Put these release notes in the PR (adjust them to what you actually did):
- /close and /commit no longer run the aggregator as a step of their own, nor the schema gates, their own accepted-line
  lists or the routing tables; when a cycle is incomplete they dispatch again each gap's declaring dispatch, read
  through E3's reader (same subagent_type, task_id, lane and obligation template, a fresh dispatched_at), or, for an
  artifact no dispatch declared, make a fresh dispatch of the role of the canonical todo step the reader returns (or run
  that step themselves when it is the main agent's own, as /dev Step 11 under E5 (b); never /do's Step 5, since an
  unfinished /do task keeps the base's route of dispatching dev again), until the cycle completes (D7, CC4), also when
  the /dev ran in an earlier session; under E5 (a) a missing or stale canonical aggregate goes back to the hook, which a
  lane's dev dispatch run again sets off by writing its report; the gap carries facts only (D21).
- The task id is derived in one place; every hook and script that needs a registry name or an artifact name calls it.
- One path rule for hook state: /do consent, the /do task sidecar, the push grant, the push-analyst grant, the chain-B
  sentinel and the push-gate token are written and read in the same directory, also when CLAUDE_STATE_DIR is set.
- /allow writes one grant file.
- Files nothing reads are no longer written (each named in the PR, for example journal-view, aggregate-pending,
  workflow-history, the overnight continuation sentinel, harness-report.json, the escalation records).
- G2 blocks at the producer's stop from this PR's arming commit (E4); G1 and G3 stay advisory until P2 arms them, and
  each consumer-side check whose faults only they would stop stays until then (the PR lists each with its gate). Every
  fault a deleted check used to stop is still stopped and returned to its own producer when that producer stops after
  the merge reaches the harness home, also in a session started before it; the PR names each stop. A fault a producer
  left at a stop before then, where the base's G2 blocked nothing, is stopped only where a check its run still reaches
  decides on that artifact: the run then runs the current hook and script files (D15), without the checks this PR
  deletes, and G2 decides only at a producer's stop. So a split only `spec-verify.py --strict` rejects passes when the
  spec subagent's last stop came before the merge and the /spec orchestrator's Stop after it (row 8); the PR names
  each such fault.

## Owner decisions that govern this phase

D# are in DECISIONS.md. S# are planner clarifications in PLAN-v2.md section 0. They rank below quoted owner words and
DECISIONS.md D20-D25 (owner, 2026-10-23 and 2026-10-24). S2 is superseded by D20; S1's extra exits and S9 carry no owner
quote. The 2026-10-23 rulings below are quoted verbatim from audit/2026-10-23/corrections.md section 1.1 (source: the
owner's message of 2026-10-23T11:59:26Z, answering the reviewer's P2-P11 summary line by line).

- **D24 Producer and consumer per artifact are the first requirement.** "…最关心的artifact生产者消费者问题，有一点提及吗？
  没有，…这都是在干啥？" [The artifact producer/consumer problem I care about most: is it mentioned at all? No… what is
  all this doing?] Read with O4/O6 (2026-10-09): "我只关心：对外公开可用度+自洽度（不多不少刚刚好每一个harness artifact都有
  生产者和消费者）+整洁清洁度。不要走偏" [I only care about public usability + self-consistency (no more, no less: every
  harness artifact has its producer and its consumer) + cleanliness. Don't drift.] and O10/O12: "核心架构：每个产物只有
  一个生产者，正确性在生产者那一端由 hook 保证，消费者只信一个结论" [core architecture: each artifact has one producer,
  correctness is enforced at the producer by hooks, consumers trust one conclusion]. Every harness artifact has exactly
  one producer and at least one consumer, and its consumers trust one conclusion. Every phase PR carries a table:
  artifact / producers before → after / deciding consumers before → after / proof (a grep for writers and readers,
  plus a sandbox write trace). An artifact that is written and never read is deleted at its producer. An artifact that
  is read and never written loses its reading branch. This phase is that requirement, applied to every artifact.
- **D21 No filename-to-role table, no agent manual.** "？？又开始hardcode了？自己检查我最开始的需求是什么。又开始给agent一个无法
  对齐无法彻底完全100%执行的说明书？" [Hardcoding again? Check what my original requirement was. Again a manual the agent
  can never align with or execute 100%?] No table maps file names to roles, in code or in prose. A gap reports facts
  only: the artifact path, the failing check's code and message, the lane. Hooks enforce correctness at the producer
  (G2 returns an artifact to its own producer at that producer's stop), at dispatch (G1) and at the end (the Stop
  gate). An instruction document the agent must follow is not the enforcement. Where a role is needed, it is read from
  the dispatch record that declared the artifact (corrections.md marks that mechanism INFERRED: you prove it, E3).
- **D20 Overnight is unattended.** "不允许，谁说的？overnight就应该是无人值守" [Not allowed. Who said that? Overnight must be
  unattended.] Nothing you add parks a pipeline, waits for the owner or asks him, inside or after the window.
- **D22 /redev is /dev.** "/redev <任务号>根本就不继续跑用的，redev单纯就是省context的时候的dev。和dev一样！谁说的！…" [/redev
  <task id> is not for continuing at all; /redev is simply /dev when saving context. Same as /dev!] /redev mints a fresh
  task id exactly as /dev; no artifact you touch binds /redev to an earlier task.
- **D23 Asking with the question component is the pause.** "但是我是不是说过agent可以给我使用提问的组件询问问题作为暂停方式？"
  [Didn't I say the agent may ask me with the question component as the way to pause?] Outside /dev-overnight an agent
  that needs the owner asks with AskUserQuestion inside the turn; neither asking nor answering releases a gate. The
  producer-question artifact stays the BA/dev route to that question (P1); you do not change it.
- **Owner rulings of 2026-09-27/28** (docs/reference/close-commit-zero-failure-mechanism-20260928.md:13-23):
  "1. 2026-09-27 — /close and /commit may only detect 'the development cycle itself failed' (class a). Every
  artifact-missing/schema (b), file-content/hash/ownership (c), environment/grant/lock (d), input/precondition (e)
  failure at close/commit is a defect; the guarantee must be established during /dev, /do, /redev, /dev-command,
  /dev-overnight. 2. 2026-09-28 am — artifact-missing detection belongs on the PRODUCER of each artifact (at the moment
  it finishes) and on the ORCHESTRATOR (at dispatch and collection points). 3. 2026-09-28 pm — the enforcement
  primitive is hooks; new mutable state files are themselves new failure surface; cross-event state via new files:
  zero. 4. … the mechanism must not depend on spec presence and must cover every entry variation; no new bugs are
  acceptable." The hard criteria (same file :26-35; summarised here, the file has the full text) are acceptance
  criteria of this phase: **C1** zero new mutable state files; **C2** zero new class-(b)/(c) checks at /close or
  /commit; **C3** strictly fewer failure surfaces; **C4** the change survives an adversarial rehearsal; **C5** a
  blocking gate returns the artifact to its own producer, hook rejections are pause-and-report for subagents, no new
  human-in-the-loop step on the default success path, legitimate output always keeps a route to completion, commits
  land only via /commit's changelog-analyst. The producer's stop, G1 and G3 are the allowed positions, plus goal 3's
  two completion reads: they are not consumer-side checks and they stay.
- **HC2** (an owner message to the paseo-daemon controller, quoted in audit/2026-10-23/register.md):
  "如果发现了问题就通过harness解决，永远不要通过ai的自觉性！" ("when you find a problem, solve it through the harness, never
  through the AI's self-discipline"). A prose step that checks an artifact is not enforcement: it is either a duplicate
  of a hook at an allowed position (delete it) or the only check (move it into that hook).
- **D8** The orchestrator never writes a producer's artifact. Every orchestrator write of a subagent's artifact you find
  goes, and the producer writes it.
- **D15** Live sessions keep the hook list they loaded and run the current hook files. A registered hook file you empty
  stays an exit-0 stub with a `# STUB:` line until P10; never delete a registered hook file in the change that
  unregisters it.
- **D17** Dead code and its tests are deleted, not quarantined, each with its reachability proof.
- **D18, D19** No owner question, no owner machine step (above).
- **D2** One dev terminal, completed; QA fail and BA questions are process steps. Nothing you delete may turn into a
  "skipped", "blocked" or "accept with known issues" path.
- **D25 Never fail** (owner, 2026-10-24):
  "还有一件我关心的！就是永远不能失败！每一次开发一定不会在流程上出现任何错误！出现了错误也可以立刻被修复！"
  [One more thing I care about! It must never fail! No development run may ever hit an error in the process! And if an
  error does occur it can be repaired immediately!] Source: his message to the reviewing session, recorded verbatim in
  DECISIONS.md D25; the register has no row for it. His words name no suite. The CI replay suite is the measure
  DECISIONS.md D25 records ("Measured by a replay suite in CI that every later phase keeps green"): the reviewing
  session proposed it and the owner forwarded the proposal with his words; it is not his words. P1c owns that suite;
  you must not make any compliant replay worse (acceptance 4, 5) and you hand P1c the runner.

**Decided technical choices.** None of PLAN-v2 section 9's rows is assigned to P1b. Where your work delivers a corrected
row early (TC-35 as corrected: one schema declaration for obligation-bearing overnight reports, E13; TC-43: the PM
TRIAGE handler as the cycle contract's only writer, E13; TC-20 as corrected: write permission derived from dispatch
records, E3), say so in the PR so the later phase does not redo it.

### Decided by experiment (D18; nobody is asked)

Each experiment runs in the sandbox kit (`harness-repair-plan/tools/`: `sb-setup.sh`, `ns.sh`, `runhook.py`,
`baseline.py`, `reset.sh`), never against your container's real `~/.claude` or HOME. Fix the decision rule before you
run it, and put the experiment, its raw counts or exit codes and the option taken into the PR's technical-choices
table. "Your branch" means a kit built from your working tree (`sb-setup.sh "$PWD"`, re-run after every change);
"base" means a second kit built from a scratch clone at your base. The numbers quoted as "planning" were measured on
d625284 by the planning workflow (inventory/README.md); re-measure them on your base.

**E1. Can the CI check derive relations from code alone?** Planning pilot on d625284 and P8's head (a throwaway
extractor of literal paths in Python, shell and markdown, scored against the 56 ledger rows): recall producers 89/119
(74.8%), consumers 102/186 (54.8%), deciding consumers 60/156 (38.5%), the same on P8; estimated precision about 82%
for writers and readers (68-91%); the "deciding" label right 16/20 times. Misses by class (150): path named only in
prose 37; path arriving as data at run time 27 (obligation record 15, cycle contract 2, argv or hook payload 10); path
assembled at run time 38 (dicts, parameters, listings, regex or glob matches, the caller's stdout redirect, modules
loaded by path, heredoc interpolation); row not a file 32; ledger claims the code does not support 16; plus 33 reads
found but not labelled deciding. The extractor is not deterministic (hash-ordered sets): the pilot saw two runs differ
in 2 of about 8,960 file operations; a verifier's two reruns of the same extractor on d625284 differed in 108 of 8,962
records.
Experiment: build the static half of the check on your base (Python AST and shell parsing of hooks/, scripts/,
commands/, agents/, with the obligation templates read as records) and the runtime half (E2), and run both on the
compliant replays of acceptance 4. Measure, on the artifacts the runtime trace sees: static recall of producers,
readers and deciding consumers against the runtime relations, static precision on a hand-checked random sample of 60
static-only edges, and whether two static runs give byte-identical output. Decision rule: static derivation alone is
used only if recall is at least 95% for producers and for deciding consumers, sampled precision at least 95%, and two
runs are identical. Otherwise (the pilot predicts this) the check takes the union: relations from the runtime trace of
the compliant replays, plus static relations at literal code sites (file:line) for paths no replay exercises, with
producers checked against the obligation records that declare them (D21); a relation either source finds counts.
"Deciding" is measured, not guessed: a reader is deciding when re-running its recorded invocation with the artifact
removed, or made schema-invalid (for an artifact with no schema, its bytes replaced at the same size by content its
reader cannot parse), changes its exit code or its decision output; a deciding read outside goal 3's positions is a
re-check when the artifact's own producer side (its producer stop, G1 or G3) already checks the property it decides on
(row 19, rule 6). Fallback, if the differential runs exceed E2's time budget: run them only for readers outside the
allowed positions, and treat every remaining static branch to an exit or block on a read of the artifact as deciding.

**E2. How the runtime trace runs in CI.** Planning cost on d625284: one full replay of six pipelines 637.6 s untraced,
1034.9 s traced with `strace -f --seccomp-bpf` (x1.62; per hook run 99 ms to 161 ms); a second replay of seven
pipelines 451.4 s untraced, 632.6 s traced (x1.40); plain ptrace strace without `--seccomp-bpf` x3.1 on the first 76
events; analysis 17.6 s to about 50 s of CPU; raw strace 57 MB (3.6 MB gzipped) per replay. The kit isolates with
`unshare --mount` as root; CI runs as a non-root user with passwordless sudo on ubuntu-latest. Candidates:
(a) `strace -f --seccomp-bpf` inside `sudo unshare --mount` with the kit's layout; (b) the same without a namespace,
with HOME, CLAUDE_CONFIG_DIR and CLAUDE_STATE_DIR pointed at a scratch directory (the hermetic fixture's convention);
(c) Python audit hooks (`sys.addaudithook`) plus a shell wrapper, if strace is unavailable. Experiment: in a CI job on
your branch, install strace (`sudo apt-get update && sudo apt-get install -y strace`; ubuntu-latest's ubuntu-24.04 image
lists none), run `strace -V` and a two-pipeline traced replay under (a) and (b); record wall time, the relations each
yields, and every path either variant writes outside its scratch root. A push to your branch alone starts no baseline
run (baseline.yml's push trigger names master and main only): run the probe in your pull request's runs (open it early
as a draft; it is still your one pull request) or through the workflow_dispatch trigger P8 gave baseline.yml
(`gh workflow run baseline.yml --ref <your branch>`). The probe (its job and anything only that job runs) is added in
one commit and deleted in a later one; the job records and never fails the run (for example `continue-on-error: true`).
Both commits stay in the branch (no force-push or rebase), keep the suite green and revert on their own; they sit
outside the Rollback order, and the PR's Rollback names them. Put the run URL and the measurements in the PR, not the
raw trace. Decision rule: take (a) if strace has `--seccomp-bpf` there and the full traced replay of all ten pipelines
fits 25 minutes wall per CI job, setup and E1's differential runs included (shard by pipeline with a matrix if one job
does not: at most one traced job per pipeline; record the number and wall time of the differential runs); take (b) only
if (a) cannot run and (b) writes nothing outside its scratch root; take (c) only if strace cannot run at all once
installed as above (row 19's job installs it the same way), and only if on the same replay it recovers at least 99%
of (a)'s relations measured locally. Fallback: if no variant fits the budget after E1's fallback has cut the
differential runs, the trace job runs on every PR in a separate workflow job that must be green on the PR head before
the reviewer merges (still per PR, never nightly-only; the PR changes no repository setting). The check's traced replay
runs with the tree's own settings.json (the shipped settings: the commit that arms a gate is traced armed), and the
budget counts that one replay; row 19 rule 6's measurement with the gates armed is part of the differential runs. The
sandbox-armed replays of row 0 and acceptances 4 and 5 use the same runner and derivation outside the CI job.

**E3. The declaring dispatch replaces every filename-to-role table.** The D21 mechanism is INFERRED in corrections.md.
Tables at d625284 (inventory rows A59, A118, A119 and the hand-written-table violations): commands/close.md:162-181 and
commands/commit.md:99-116 (filename to role; their changelog-status* row matches no file) with their prose copies
(close.md:276, :718, :731; commit.md:88-97, :350-351, :575, :680-681, :852) and the references to their rows
(close.md:293-298, :594, and :414's pointer to the orchestrator row, whose /do route row 10 keeps; commit.md:154-156,
:340), which go with them, while Step 8's selection, which E14 keeps, loses `artifact_role` (commit.md:910): its
unlinked-spec route to ba, a deciding read of BA's context at /commit, goes or moves under goal 3 and E4 like any other
consumer-side check (ruling 1; prompts/P4.md:697 expects stage 4 to print and dispatch nothing), and while it stays it
takes the context's producer from the reader, not from a table or a role name in the text;
scripts/late-repair-controller.py:82-88 (stage to basenames); hooks/subagentstop-artifact-contract-enforce.py:119-122
(role to report prefix); hooks/posttool-overnight-trace.py:256-269 (per-role required fields);
scripts/spec-verify/spec_verify_gated.py:244-249 (view file to role); hooks/pretool-gitignore-preflight.py:398-403
(deliverable prefixes); scripts/generate-repair-map.py:276-295 (artifact-name words to the producer_role of
schemas/repair-map.v1.json, whose one reader is scripts/close-commit-repair-orchestrate.py; only tests run either
script, so the table goes with both scripts, the map and its entry in schemas/registry.json (:16), D17, in this phase,
not in P10 row 6, which lists all three, since row 19 rule 7 flags the table on your branch);
policies/tool-policy.v1.json from :14 (24 roles, 261 write prefixes; 94 prefix families name files nothing writes or
reads, 41 of which match no other artifact in the map). Experiment: write one reader in hooks/lib/obligation.py,
"declaring dispatch for an artifact path" (task_id, lane, role, the whole obligation), built on `_read_parent_calls`
(hooks/lib/subagent_restart.py, already used by obligation.py :755 and :958) over every dispatch record of the task, not
only the current session's: a /close or /commit often runs in a later session than its /dev, so the reader keys the
records by the task_id each dispatch's obligation carries, never by session, and reads every session transcript the CLI
keeps for the project (obligation.py `candidate_transcript_paths` :694-712 already finds that store through
subagent_restart.py's `account_project_roots` and `project_slug`, :830-855); how it narrows that scan is a technical
choice, replayed, and E6's one function reaches the writer's dispatch through the same records (a journal event names
its session and agent, attribution_journal.py:330-338). For an artifact no dispatch has declared yet, it returns the
canonical todo step from `scripts/todo/<command>.py` with what that step's entry names: its `subagent_call`, or none
when the step is the main agent's own (at d625284 /dev Step 11, which writes the canonical aggregate,
scripts/todo/dev.py:29, while Step 10's entry names dev, :28); the main agent of the /close or /commit that asked runs
such a step itself (row 10), with two exceptions row 10 states: if E5 keeps (a), a gap on the canonical aggregate goes
back to its producer, the hook; and a /do task's do-report keeps the base's route and never goes to /do's Step 5
(scripts/todo/do.py:14), which only records the /do work of the main agent's own Steps 1-4; no step gets a role its
entry does not name. A finding that names no artifact (both tables bind `path=$TASK_ID` and send it to the orchestrator,
close.md:184-185, :718; commit.md:90-91) loses that default with the tables: it names the artifact its check was
reading, or, for a close-QA or commit-QA finding that cites none, that round's own report, which the round's dispatch
declares, so the reader answers it like any other path and that QA dispatch runs again to name what the finding
concerns. A close-QA or commit-QA finding whose only path is a product file for which E6's kept producer records no
dispatch of the task as the writer, outside row 10's /do case (a file the cycle should have changed and did not, for
example), goes the same way, as no record gives that file a producer: the gap is on that round's own report, with the
file and the finding as its detail, and the re-run names a path whose producer the reader or that record gives (no
default role). At d625284 scripts/todo/ has no commit.py, merge.py or push.py, the /merge and /push dispatches carry no
obligation, and obligation.ROLES and PIPELINES (obligation.py:74-83) name neither command nor the push- and
merge-analysts (the pull-analyst writes no file): those analysts' artifacts get no answer from either source and take
the fallback below (their dispatch templates gain an obligation whose role validates against the roster function and
whose pipeline validates against the command files, row 18). In the sandbox, for every artifact kind of every replayed
pipeline, remove the artifact (and separately make it schema-invalid) after its producer ran, and ask the reader for the
owing dispatch, once from the replay's own session and once from a later session; compare with the producer the replay
actually dispatched or, for a main agent's step, ran.
Then replay the D8 write permission derived from the session's dispatch records ("a subagent may write the paths its own
obligation declares; any other caller writing a declared path is denied; undeclared paths keep the policy rows") against
the table, in the same replays. Decision rule: if the reader names the producing dispatch (or the canonical todo step)
for 100% of cases, every table above is deleted and its callers read the reader; if the derived write permission denies
0 compliant writes and allows 0 writes of a path another agent's obligation declares, the per-role write prefixes that
name declared artifacts go. An allow prefix that names the file of an artifact the CI check derives (a prefix ending in
neither '/' nor '*') maps a file name to a role whether or not a dispatch declares that artifact: the check fails on it,
with no exception for policies/tool-policy.v1.json, and the prefix goes (when that role's dispatch is the artifact's
producer, its obligation declares the path first, as in the fallback). A deny prefix grants no write and stays, so no
deny is lost. Directory and wildcard prefixes (dev's `*`, general-purpose's `*/docs/dev/*`) name no file and stay: the
derived permission overrides them on every declared path; the check asserts, with no exception, that the effective write
permission lets only the declaring dispatch's role write each declared path. Fallback: an artifact kind for which the
reader names nothing is declared in its producer's dispatch template (its obligation gains the path), never in a table;
then re-run.
The derived permission ships in hooks/pretool-tool-policy.py, enforcing and with no switch (the hook has none, so this
arms nothing), in the commit that deletes the prefixes it replaces. It runs before the role policy on Write, Edit,
MultiEdit, NotebookEdit and Bash write targets, for every caller, the main agent included; only if acceptance 17's
in-flight cycle on the base's command text (whose orchestrator still patches BA's context, row 4) shows a main-agent
deny the base kit does not show is the main agent's half left to P5 row 1, and the PR says so. Acceptance (replayed on
your branch; the base's replay of the same writes records what its policy rows allow): every write of a declared
artifact by its declaring agent is allowed, and every write of a declared path by any other caller it covers is
denied, including one that a surviving prefix (dev's `*`, general-purpose's `*/docs/dev/*`) allows; the deny names the
path and the declaring obligation's role and offers no workaround. A count above 0 in the decision rule is fixed where
it arises and the replays re-run, never by keeping a prefix: a compliant write it denies is a path its producer's
obligation must declare (the fallback) or a write by a caller that does not produce the artifact, which goes (D8,
D24); a write it allows is a Bash write whose target the hook does not extract, which the extraction gains, or which
the PR names for P5 row 1's extractor measurement where the base does not extract it either. When it covers every
caller, you deliver P5 row 1 (TC-20).
A dispatch made from the base's templates before your merge meets the merged hook (D15) with what the base declared: at
d625284 BA's obligation declares the context, ticket and acceptance criteria (commands/dev.md:509, :721), while BA
writes its producer question (agents/ba.md:116, the D23 route) under a file allow prefix this rule deletes
(policies/tool-policy.v1.json:133), and some dispatches carry no obligation (graphify's, commands/dev.md:763-775). So
the derived permission reads the dispatch's record whole: a subagent may also write the paths that the template it was
dispatched from declares in the current command files (the templates for its obligation's role, pipeline and profile;
for a dispatch that carries none, those for its subagent_type in the command whose span holds its dispatch record), each
placeholder bound to that dispatch's own ids (technical choice). Those paths are that dispatch's declarations for this
rule: any other caller writing one is denied, and the role's deny prefixes still apply to them, so no deny is lost. A
fresh dispatch gains nothing by it (its obligation is its template's), and the templates are the declarations the CI
check already reads (row 19), read at run time, never a table or a kept prefix, so the check keeps zero exceptions.
Acceptance 17 replays it; a deny there is fixed in this rule or in a template, never by keeping a prefix.

**E4. Deleting consumer-side checks while G1-G3 are still advisory.** P2 arms G1 and G3; you arm G2 under the rule below
and delete the consumer-side re-checks (owner ruling 1 makes every class-b/c check at /close and /commit a defect).
Planning fault pilot on d625284 (shipped settings, where G1-G4 are advisory in code): a missing or malformed dev report
is blocked by no hook; only the dev.md Step 12 prose and the Step 17 resolver run by prose catch it; armed G2 names the
exact path and the failing check, sends it back to the producer, and the next round passes with zero human action.
Experiment: on your base and on your branch, replay three faults per artifact family whose consumer-side check you
delete (artifact missing at its producer's stop, artifact schema-invalid, a stale earlier-version artifact beside the
new one), in shipped settings and in sandbox-armed settings (P1's "Sandbox and arming": CLAUDE_OBLIGATION_GATE,
_STOPGATE and _BARRIER = block, G4 untouched). Decision rule: armed, every fault must be stopped at an allowed position,
naming the artifact and the failing check, returned to its own producer, and pass on the next round (a stale file at a
path no dispatch of the cycle declares is read by no consumer: no block, no new check, and the cycle reaches its
terminal; that is a pass, not an escape); any fault that escapes armed on your branch means the deleted check carried a
rule the allowed position lacks: move that rule into the gate at the allowed position (G2 for the artifact's own
properties, G1 for dispatch preconditions, G3 for prior stages), then delete the consumer copy under the shipped rule.
Shipped, no fault a deleted check used to stop may pass at any commit (an advisory record stops nothing): a
consumer-side copy goes only in a commit whose own settings.json leaves its faults stopped at an allowed position, and
the PR names that stop. For faults only armed G2 stops, that commit is Rollback's (7), the last you plan: it adds
`"CLAUDE_OBLIGATION_STOPGATE": "block"` to settings.json env (the tracked clean form;
`scripts/install/render-settings check --staged` stays green) together with those deletions, once acceptance 4 (armed)
and acceptance 17 (with your branch's settings.json) show 0 G2 blocks on compliant stops, a block the base shows too
included; a compliant stop G2 blocks is a false block: fix its producer side and re-run (P1c X3's rule). A commit after
it (a review fix, a merge of origin/master) keeps the switch, deletes a copy only under this rule, and is followed by
acceptances 4 (armed), 5 and 17 re-run on the PR's new head. Record whether a settings env change reaches a running
session (P2's "Arming timing" step (1)); if it does not, or you cannot measure it, G2 takes its switch, when its process
env lacks the key, from the harness home's settings.json env at run time, as hooks/lib/claude_home.py `settings_env`
(:189 on master 2acc29b) reads P7b's keys, and also when that env has CLAUDE_HOME, which every session started since
P7b's landing has (init and the landing's migrate put it in the overlay, scripts/bootstrap:288 and render-settings :1172
on master 2acc29b) and for which `settings_env` returns nothing (claude_home.py:193-195 on master 2acc29b): take that
read through P7b's function, not a second reader (for example an option whose default leaves its other callers as they
are; technical choice; acceptance 17's fault replays with the base's settings.json, with and without CLAUDE_HOME, prove
it), so a session started before your merge meets armed G2 once the copies are gone. A copy whose faults only G1 or G3
would stop stays and keeps returning them to their producer (row 10's loop at /close and /commit); the PR lists it with
its gate, and P2's arming commit deletes it. While a copy's gate is advisory in the tracked settings.json, the copy is
its faults' only stop, not a re-check (E1: the producer side does not yet check them); the CI check reads the switches
there (row 19), so the commit that arms the gate must delete the copy. Fallback: for a family no replay can reach, move
the deleted check's rule into the allowed-position gate unconditionally, cover it with a unit test on a recorded
payload, and list it; its copy follows the shipped rule.

**E5. One producer for the canonical fan-out aggregate.** Producers at d625284: scripts/aggregate-dev-report.py run by
the orchestrator at /dev Step 11 (commands/dev.md:885, the "MUST write" block :898-923), at /close Step 0
(close.md:334-343) and at /commit row 1 (commit.md:105), and by hooks/posttool-lane-completeness-watch.py:216-220
itself. /close's and /commit's own aggregator re-runs go regardless (ruling 1). Candidates for the one producer: (a) the
lane-completeness hook when the last lane report lands; (b) the orchestrator's Step 11. Both reach the aggregator by a
path inside the product repository: the hook joins CLAUDE_PROJECT_DIR or the cwd (:90-91) with scripts/ (:216) and
returns silently when the file is absent (:217-218); Step 11 runs `source venv/bin/activate && python3
scripts/aggregate-dev-report.py` (dev.md:885, :923). The kit's toyproj has neither scripts/ nor venv/ (`sb-setup.sh`
`make_toy`), so on your base neither candidate writes the canonical there and G3's missing-canonical check blocks every
fan-out's QA dispatch (pretool-aggregate-check.py:298-319): a product-repository defect, not a driver's. A replay of the
base's text (acceptance 4) runs Step 11's call in the harness's copy as row 7 says, so the base kit writes the canonical
too. Before the experiment give both candidates the harness's copy, so that neither loses on a path: (a) the hook
resolves the script from its own file (`Path(__file__).resolve().parent.parent / "scripts"`, the form of
hooks/prompt-workflow.py:557; corrected P2 row 4's path part, delivered early: say so in the PR); (b) Step 11 runs
`python3 ~/.claude/scripts/aggregate-dev-report.py` with no venv, as the hook runs it (:219-220), in the base's own
harness-home spelling (commit.md:353; bash-safety passes the `~/.claude/...` form, prompts/P1c.md row 15), which P2's
TC-44 substitution respells later. The aggregator takes its root from CLAUDE_PROJECT_DIR, else from its own location
(aggregate-dev-report.py:173-182), and the CLI's Bash does not export that variable (prompts/P2.md Goal 1): give it a
`--project-dir` option with the resolver's meaning (an empty value is the cwd; resolve-dev-artifact-chain.py:2263-2266,
:1775) and pass it from both candidates. Experiment: replay a 2-lane and a 3-lane /dev and the 2-pipeline overnight
cycle (through E13 and acceptance 4's marked deviations), and acceptance 7's /commit whose canonical aggregate was
removed after a landed /close, with only (a), then with only (b). Decision rule: take (a) if the canonical exists and
validates before every QA dispatch in every replay with 0 orchestrator aggregation calls (it is a hook, D8 and HC2) and
that /commit lands with no human action; otherwise (b), and the hook's aggregator call goes. Either way G3
(pretool-aggregate-check.py) stays the collection check, the other producer goes with its path change, the one kept
keeps its resolution, and a canonical missing or stale at /close or /commit goes back to it through row 10's loop: under
(a) the loop dispatches again the declaring dispatch of one lane dev report, whose report write runs the hook; under (b)
the main agent of that /close or /commit runs /dev Step 11. Fallback: if (b) also leaves a QA dispatch without a valid
canonical in some replay, take the candidate that leaves fewer ((a) on a tie), fix each remaining miss on that
producer's side (the replay shows which root or lane report it missed) and re-run until every replay passes; never keep
both producers.

**E6. One producer for "which files this dev wrote" and for the baseline.** Producers at d625284: the write-time
attribution journal (hooks/pretool-attribution-pre.py and posttool-attribution-post.py through
hooks/lib/attribution_journal.py) and the dev's self-reported `owned_edits` / `pre_edit_snapshots` (agents/dev.md:555-
592), unioned by the aggregator; the baseline head and dirty snapshot are captured by orchestrator Bash before dispatch
(commands/dev.md:826-835) and copied verbatim by dev (agents/dev.md:539-543). Experiment: over every replayed dev
(singular, 2-lane, a dev that edits a file another hook regenerates, a dev that creates a file through Bash), compare
each candidate with the writes of that dev's own tool calls in the replay's write trace (E2): (a) the journal's file
set; (b) the self-report; (c) the record the CLI writes in that dev's transcript (not the agent: a record like those E7
reads): its Write, Edit, MultiEdit and NotebookEdit targets with an ok tool_result, plus the paths its own Bash commands
name (TC-46's set), computed by the replay kit, since P5 row 8's `Span.write_set()` does not exist yet. Decision rule:
take (c) if it equals the trace in every replay; else (a) if it does; never (b) (HC2: never the agent's self-report).
Keep G2's `_wire_ledger_judgment` with the attribution_adjudicator functions it calls (its ENTANGLED check stays,
P6 row 5) and dev's declared `files_created` / `files_modified` (P6's A3.a checks them against TC-46's set at dev's
stop). Delete verify-attribution-chain at /commit Step 5 if it only re-checks (ruling 1), and the aggregator union once
the map shows no reader of it. Row 10's route for a product file reads the kept producer's record through one function:
for (a), the journal's own reader (hooks/lib/attribution_journal.py `read_all_journals` :391); for (c), TC-46's one
write-set reader, which you then add to hooks/lib/command_span.py for any transcript path, delivered early (P5 row 8 and
P6's A3.a reuse it and write no second one; say so in the PR). The PR lists each losing candidate with its remaining
readers on your base and the phase that retires it (P6's D24 acceptance). For the baseline: the value lives in one
record (the dispatch prompt's obligation, checked at G1) and no agent copies it; take this if G1 validates it in every
replay, else keep the orchestrator's capture as the producer and delete the agent copy and the aggregate's equality
check. Fallback: if neither (a) nor (c) equals the trace, take (c) (TC-46) and record each difference in the PR for P6
(A3.a's Bash-naming rule; role and identity from the CLI).

**E7. Mutable switch and copy files replaced by records.** At d625284: `qa.json`'s `qa_mode` is flipped by the
orchestrator through scripts/write-qa-mode.sh between dispatches (commands/dev.md:609, :978;
commands/dev-command.md:437, :627; commands/dev-overnight.md:1097, :1381, :1503, :1648) and read by G2
(subagentstop-artifact-contract-enforce.py:1218-1221, its path for a dispatch without an obligation) and by the e2e
gate (subagentstop-e2e-enforce.py:395-401, its registry path, which a QA found in the agent index takes with or
without an obligation); the workflow bookmark `.claude/workflow-<sid>.json` has 5-7 writers that mutate
`subagent_calls`, `last_todos`, `todo_acknowledged`; the canonical todo file is written by three hooks, a script and the
CLI. The records already exist: each QA dispatch's obligation names the artifact it owes (ba-qa-report or qa-report),
and the transcript holds every TodoWrite and Agent call (command_span reads them). Experiment: switch each reader to the
record (G2 and the e2e gate classify BA-validation from the obligation's declared artifact; the todo and bookmark
readers take command_span's `calls()` and `last_todos()`, which you add) and replay every pipeline. Decision rule: a
field whose readers give identical decisions on every replay event (0 differences) loses its file write; the file goes
when no field is left.
When `qa_mode` loses its write, one commit switches its readers to the record and deletes every flip listed above, and
once nothing is left for write-qa-mode.sh (row 1) the script becomes an exit-0 stub (acceptance 17); the overnight
sandbox's RW bind of qa.json, which exists only for this write (pretool-overnight-hook-guard.py:1986-2048, :2121-2123),
goes with the flip, and the script's allow rule (settings.json:52) stays with the stub. /close's call
(commands/close.md:246-248) goes under row 1 regardless. While a flip stays (in this experiment's replays, and under the
fallback), /dev's and /dev-command's four flips (dev.md:609, :978; dev-command.md:437, :627) name the product root in
their own environment as a prefix of the call,
`CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}" bash ~/.claude/scripts/write-qa-mode.sh`,
so both commands reach their terminal on your branch's own text (acceptance 4): the CLI's Bash does not export the
variable (E5), so in toyproj write-qa-mode.sh:35 exits 1 and the `|| { …; exit 1; }` after each call aborts the command.
That is the overnight calls' remedy (dev-overnight.md:1086-1097) with P2's root form (prompts/P2.md:519); it changes
neither the script nor P8's tests/test_write_qa_mode.py, which pins the script's refusal, and the script's own fallback
stays P2 row 4's (prompts/P2.md:322).
Fallback: a field with a difference keeps exactly one writer (the UserPromptSubmit hook for bookmark fields), and the
other writers go; the check counts writers per file path (row 19 rule 1), so a field kept in a file another component
also writes (`qa_mode` in qa.json, which `_init_dev_registry` creates, prompt-workflow.py:1546-1553; row 1) is written
through that file's one writer (row 1's pattern: the same function, or the value handed to it; technical choice,
replayed), never as a second writer of the file.

**E8. One producer for the /do report.** At d625284 prompt-workflow.py:1363-1397 writes a pending skeleton, the /do main
agent rewrites it (commands/do.md:46-60), and the /do Stop gate, once it gives up after MAX_BLOCKS, rewrites a
still-`pending` status to `blocked` (stop-do-report-gate.py:149-166, called at :217; A54), a third writer, which row 9
deletes with `pending`; the planning trace found that do.md's Step 5 template drops the skeleton's `expected_absent`
field, so a template Write makes the e2e gate block the close QA. Candidates: (a) the main agent writes the whole report
(no skeleton); (b) the hook writes it and the agent edits only its result fields. Experiment: replay /do then /close of
the do-report with each. Decision rule: take the candidate with no block in the compliant replay beyond acceptance 4's
kept base blocks and a single writer in the trace; prefer (a) on a tie (fewer state files). resolve-commit-repos.py
routes the do-report by file name (:423-424) and the e2e gate reads only its `expected_absent`
(subagentstop-e2e-enforce.py:166-205): neither decides `do.status`, and neither gains that decision. Every reader that
does (stop-do-report-gate.py, /close preflight, dev-lifecycle.py) then decides it through one function on
obligation.TERMINAL_VOCABULARY. At d625284 that entry is the schema's whole enum, {pending, completed, blocked}
(obligation.py:138), so such a function would pass the skeleton's `pending`: remove `pending` at the declaration, never
with a second set in code (row 6). With (a) or the fallback nothing writes it, so it leaves schemas/do-report.v1.json
and the constant follows; with (b) the skeleton leaves `do.status` unset until the agent writes it. The function returns
the status it finds in that vocabulary, or none: the /do Stop passes on any returned status (as
stop-do-report-gate.py:59 does today; `blocked` leaves the enum with P5 row 21), and only `completed` lets /close,
/commit and dev-lifecycle.py treat the work as done (close.md:414, dev-lifecycle.py:188); no reader keeps a set of its
own. Correction 8 records what this leaves P5. Fallback: if neither passes, the main agent writes the whole report, and
the close QA's dispatch on the do-report path declares profile `do-close` and `expected_absent` in its own obligation
(obligation.py:86, :94, :493-499); the e2e gate reads them there (rows 3 and 7), not from the report; /do itself
dispatches nothing (pretool-do-block-subagents.py).

**E9. doc-sync's writes into product directories.** At d625284 hooks/posttool-doc-sync.py creates INDEX.md and
README.md in every product directory an agent writes to. In the ten pipelines no hook or script but doc-sync's own reads
them by name (the others open them only by directory listings); agents do: the cleanliness-inspector that /close
dispatches reads each folder's README.md for its allowed file types and naming rules, which its findings follow
(agents/cleanliness-inspector.md:74, :82); under /dev-overnight the PM reads the project root's README.md for the app
URL when CLAUDE.md names none and plans from documents when no file it checks names one (agents/pm.md:232-236, :290);
the specialists that /dev, /dev-command and /dev-overnight dispatch (dev.md:267-270, dev-command.md:202-205,
dev-overnight.md:573) read it beside CLAUDE.md for the app URL or the product description (agents/architect.md:203,
ui-specialist.md:174, product-owner.md:204, user.md:171, :215); doc-sync creates that file when the root has none and
an agent writes a root-level file it watches (hooks/doc_sync/main.py:49-57, :171; regen_readme.py:194-215). /clean,
outside the ten pipelines, writes both files itself (its rule-inspector through scripts/generate-folder-index.sh and
scripts/generate-folder-readme.sh, agents/rule-inspector.md:85-98; its cleaner through the same index script,
agents/cleaner.md:77, :91), and its clean-inspect step exits 1 when agents/, scripts/, docs/, hooks/ or commands/ lacks
either file while the rule-inspector's context is absent (scripts/orchestrator.sh:204-224). The files doc-sync creates
stay untracked after a compliant /commit (planning trace: 57 files of the cycle left, docs/dev and toy/ index files
among them), /dev-command's spec auto-detect picks docs/dev/specs/INDEX.md, and they are why doc-sync keeps the
hook-landed-files ledger that the aggregator merges into a singular dev report at /close (aggregate-dev-report.py
`_merge_hook_ledger_into_singular` :1321-1505, called at :3738-3740). Experiment: make doc-sync update-only (it updates
an existing marked file, creates none, skips docs/dev/) and replay every pipeline. The kit's toyproj has an unmarked
root README.md in every replay (tools/sb-setup.sh:39, tools/reset.sh:11), which doc-sync never rewrites
(hooks/doc_sync/regen_readme.py:196-202), so replay /dev-overnight's two cycles also from a toyproj whose README.md a
fixture commit removes and in which one pipeline's first-cycle dev writes a root-level file doc-sync watches: the base
kit's doc-sync then creates the file the second cycle's PM and specialists read. Decision rule: if no consumer's
decision changes and no INDEX.md or README.md appears in the product repository, delete the creation paths, the
hook-landed-files ledger (hooks/doc_sync/hook_ledger.py, ledger_contract.py) and the aggregator's merge; if a consumer
decision changes, give that consumer its input from its own producer and keep creation off. Fallback: if a consumer can
only work from a generated index, it lists the directory itself; doc-sync still creates nothing in a product directory
(P9 row 2 then has nothing left to do for doc-sync creation).

**E10. Context without in-place patches.** At d625284 the BA context (docs/dev/context-<ts>[-<lane>].json) is written
by BA and patched in place by the orchestrator (`spec_path`, commands/dev.md:540-584; `attempts[].target_layer`,
:1163-1166) and by scripts/graphify-enrich.py (`_build_graph_context_patch` :413-443, called at :612, and
`_patch_context` :623-643, called at :491, :505 and :615, also when it reports skipped); the graphify outputs
graph-summary.json, focused-subgraph.json and graph-report.md have no code reader (their prose readers: the
orchestrator's status note, dev.md:780; dev's consult of the focused subgraph, whose path the in-place patch puts in
the context, agents/dev.md:127 and graphify-enrich.py:439; QA's presence fields, agents/qa.md:120-121). Experiment:
BA records `spec_path` from its dispatch line ("Spec file:", dev.md:472) and the layer attempt from its own analysis;
graphify writes only its own output, which BA's, dev's and QA's dispatches name as input (or no file at all); replay
/dev with graphify unavailable and with a stub graphify binary that returns a fixed graph. Decision rule: if G2
validates every context and QA's graphify gates (agents/qa.md:104-112) give the same verdicts in both replays, the
orchestrator patches and the in-place patch go, and each graphify output either keeps a reader or is no longer
written. Fallback: keep graphify-enrich as a producer of its own file only; never of the context.

**E11. One channel and one validator per verdict or grant.** At d625284: commit QA writes a file and a response line
for one verdict, and /commit cross-checks them (commit.md:579-583); the changelog-analyst status block is validated by
G2 and re-parsed by /commit (commit.md:673-681, :851-854) and step7-spec-update.py; the merge-analyst grant is validated
and unlinked both by /merge Step 3 prose (merge.md:127-166) and by the privilege guard (`_enforce_merge_grant`,
reachable only when CLAUDE_MERGE_COMMAND_ACTIVE=1 is in the hook's environment, UNVERIFIED); the push-analyst grant is
validated by execute-push.py and again by pretool-push-analyst-grant-guard.py. Experiment: replay /commit, /merge and
/push with each candidate single channel or single validator, and run the guard's merge path once with the variable set
as merge.sh sets it. Decision rule: keep the channel or validator that sits at the producer side (G2 at the producer's
stop for a verdict; the code validator for a grant) and is reached in the compliant replay; delete the other, and the
consumer reads the kept one verbatim. Fallback: if the guard's merge path is unreachable, the grant's validation moves
to the merge-analyst's own Write (a PostToolUse check on the producer's tool call), and the prose validation goes.

**E12. Which outputs the owner reads.** Written-never-read logs and reports at d625284 include the seven advisory
JSONL logs, the guard and override audit logs, checkpoint logs, analyst audit logs, the overnight idle and self-repair
logs and P7b's logs/landing.log; the overnight log and summary, the close report and the completion report are
read by people. Decision rule fixed now: a file counts as read by the owner only if an owner-facing output names its
path: a command's own output (the command text, or a script it runs, prints or links it, as dev-overnight.md's final
summary does) or a message that reaches the owner's session (a hook's systemMessage, relayed ones included). At d625284
auto-commit.sh:51's refused-snapshot notice names logs/checkpoint.log, and the Stop coordinator relays it
(stop-workflow-coordinator.py:185, :380); on master 2acc29b auto-commit.sh:23-24 relays the landing's one notice line
the same way, and it names logs/landing.log (scripts/install/land :230, :239, :247, :249). A hook's plain stdout or
stderr and context only the agent sees do not count. The CI check derives both at test time, from the command files and
from the hooks and the scripts they run (the path literals that reach a systemMessage or a command's output), never from
a list. Experiment: list each written-never-read file and search those sources for the output that names it. Every file
no owner-facing output names is deleted at its producer (for the advisory logs: a gate writes nothing in advisory mode,
and no fault relies on such a record, because E4 keeps a stop for each fault); every file one names stays, with the
owner as its consumer. Fallback: a file a command or hook mentions without showing its path to the owner counts as not
read and is deleted; the PR lists each such file with its hunk, so the reviewer can restore one by reverting that hunk.

**E13. One producer for the overnight state and the cycle contract.** At d625284 the overnight state
`.claude/overnight-state-<sid>.json` has four writers (create-overnight-state.sh, posttool-overnight-loop.py:101-153,
update-overnight-state.sh:271, which nothing runs (D17 reachability proof), break-overnight-lock.py:96);
the cycle contract has three copies written by the orchestrator (dev-overnight.md:821-852), a seed
from the launcher (create-overnight-state.sh:1026-1056, `required_calls: []`) whose presence switches
pretool-subagent-enforce.py into enforce mode and refuses the Step 2 PM dispatch (a dead end in the planning
replay), and in-place mutation by hooks/lib/contract_runtime.py:1208-1250; its `schema_name` entries name
dev-report.v1 and qa-report.v1 (dev-overnight.md:836-840) while the same dispatches' obligations name v2
(E1 of the ledger, re-run on d625284 and P8). Experiment (corrections.md 2.21, INFERRED): no seed file
(pretool-subagent-enforce derives the allowed steps 2-4 from `_STEPS` and the cycle index); the contract has one path
(`<working root>/docs/dev/overnight/<sid>/cycle-<N>/cycle-contract.json`), one writer (a PM TRIAGE handler in
hooks/posttool-subagent-track.py rendering steps 8/10/11g/12/15/20 per pipeline, with the labels imported from
scripts/todo/dev-overnight.py `_STEPS`: TC-43 and P2 row 13, delivered early, so say so in the PR; the orchestrator
writes none) and no in-place mutation (dispatch status is read from the transcript); obligation-bearing entries carry no
schema name and posttool-overnight-file-check validates against the dispatch's own obligation; the state is written only
through the launcher's write path: the launcher at launch, and the owner's /stop, whose write (break-overnight-lock.py
`_backdate` :77-102: end_time, current_phase=completed and the token-gated isolation fields) is the base's only /stop
release, stays until P2 rows 8, 9 and 14 replace it, and goes through the same path (row 1's pattern: the same function,
or the fields handed to it; technical choice, replayed); the cycle index and completion are read from the cycle
directories (every reader of the cycle number calls `cycle_index(state)` in hooks/lib/overnight.py, P2 row 7's function,
which you add, delivered early (neither d625284 nor master 2acc29b has it); it reads the cycle directories once
posttool-overnight-loop.py's cycle_count write, :120, goes; say so in the PR for P2); replay cycles 1 and 2 of a
2-pipeline overnight session and a human /stop inside cycle 1's window (trace-a and trace-b lack /stop). Decision rule:
the variant ships if both cycles run with 0 blocks from the contract and state hooks (other hooks' kept base blocks
passed by acceptance 4's deviations), a wrong role at step 2 is still refused, a v2 report passes collection while a
schema-invalid one is stopped by G2 at its producer's stop, and the /stop releases the time-lock and closes the session
as the same /stop does on your base (the same state fields and time-lock exit; lib/overnight `_state_file_is_live` false
afterwards; the closeout block the base's /stop then meets, landscape B2.b, is P2 row 9's). Fallback: a part that fails
the replay is fixed at its own producer; the launcher stays the state's only writer and the PM TRIAGE handler the
contract's only writer, with one path; never three copies, a seed or an orchestrator-written contract (TC-43's revert).

**E14. One producer for the spec monolith.** At d625284 docs/dev/specs/spec-<ts>.md is written by the /spec
orchestrator (commands/spec.md Step 3 and its Step 4 appends, :108), by dev (Sections 2 and 3, commands/dev.md:865,
dev-command.md:597), by the orchestrator applying QA's `spec_section_updates` (dev.md:1026-1048), by QA under
/dev-command (dev-command.md:654), by BA, dev and QA under /dev-overnight when a pipeline's `spec_path` is the user's
spec (dev-overnight.md:871, :1041, :1303, :1406-1407), by /commit Step 8's continuation agent (commit.md:915-943) and
by /spec-update's continuation and `--update` modes (spec-update.md:37-48, :154-178); /dev picks "the newest spec" by
mtime (dev.md:125-138). The check counts writers per file path (row 19 rule 1), never per byte range, so a split by
section leaves several producers of one file. The one writer is /spec's write of the monolith (the spec subagent only
reads it, agents/spec.md:669), made the one code path every write of the file runs (for example a script that /spec's
own writes call too; technical choice, replayed). Every other writer above, and any other your regenerated map finds,
stops writing the file itself, and the PR names what replaced each: a dispatch's section text stays in its own report
(dev's report, QA's `spec_section_updates`, BA's context), which the continuation reads (commit.md:934-936,
spec-update.md:50-64), and a report field that then has no reader is deleted at its producer (goal 2); a writer that is
a feature of its own writes through the one writer instead, since no feature goes (D15): /spec-update's two modes and
/commit Step 8's post-commit continuation keep updating the spec that way, and Step 8's selection, which picks the spec
the continuation updates (commit.md:856-912, scripts/step7-spec-update.py), stays. The spec path is decided once, by
prompt-workflow at UserPromptSubmit (the explicit `--spec`, else the session's last Write or Edit to
docs/dev/specs/*.md, INDEX.md and README.md excluded, a call of the one writer naming such a file counting as such a
write; PLAN-v2 P9 row 1), and the mtime rules go. The same BA, dev and QA lines write every overnight pipeline's
`spec_path`, also the per-pipeline spec of autonomous mode (docs/dev/overnight/<sid>/spec-pipeline-<index>.md, which the
orchestrator copies from the template and fills, dev-overnight.md:858-866, :873-874), and that file follows the same
rule: the orchestrator's copy is its one writer, and the dispatches' section text stays in their reports. Experiment:
replay /spec, then on that spec /dev (singular and 2-lane, QA pass and QA fail), /dev-command, one /dev-overnight cycle
in user-spec mode and one in autonomous mode, /close and /commit (Step 8 included) after the /dev, and /spec-update's
two modes on that spec. Decision rule: this ships if the trace and the static half show one writer of the monolith and
of each per-pipeline spec, each /commit and /spec-update replay leaves its update in the spec (a `### Cycle N` block or
a `### 5.N` entry), and no block beyond acceptance 4's kept base blocks. Fallback: a reader that blocks on, or decides
on, text the monolith no longer receives takes it from the report of the dispatch that declared it (E3); any other block
is a driver that leaves the command text (fix the driver) or a defect you fix at its producer (acceptance 4); re-run
until the decision rule holds, never with a second writer of the file and never by dropping an update (D15).

### Corrections to PLAN-v2 (and to the prompts written before P1b existed; record each in the PR with what you did)

1. P1b is new. It runs after P7b and P8 and before P1c; P2 and P3 start after P1c. PLAN-v2 already carries this:
   section 5 (phases at a glance) has the rows for P1b (wave 2b, after P1, P8 and P7b, net code cap <= -1200) and P1c
   (wave 2c, after P1b, net code cap <= +150) at PLAN-v2.md:133-134, the caps again at :1199, :1311 and :1329, and
   section 6 (waves) describes waves 2b and 2c (:172, :174).
2. D24 is applied here to every artifact, so per-artifact work that PLAN-v2 and the corrected prompts gave to later
   phases moves into P1b where your scope rows touch it: from P2, the canonical aggregate's single producer (corrected
   P2 row 4), closeout's harness-report writer (row 9), the cycle contract's single writer, single path, no seed and
   obligation-sourced schema (rows 11-13 and 15, TC-35), the aggregate-pending and continuation-sentinel writers;
   from P3, the declaring-dispatch reader (corrected row 1), the escalation stores and the arbitration path (Goal 3),
   the journal-view writer, the completion report leaving the required chain, consumers importing
   obligation.TERMINAL_VOCABULARY, BA's write permission on ba-qa-report; from P4, the D24 table for every artifact
   /close and /commit read or write (L17, L18, L22, L23, L28, L31, L32, L40, L41, L42, L53), the class-b/c re-checks and
   both routing tables, the close-force flag readers; from P5, the G4 terminal re-validation, the todo-file writers,
   the separate do.status deciders, merge.md's validate-and-unlink, and the write permission derived from dispatch
   records (E3); from P9, the spec_path producer (row 1), doc-sync update-only (row 2, if E9 deletes creation), one
   /do consent reader (row 4), the roster from agents/*.md stems (row 5), and the one-writer proofs for L01, L24, L42,
   L44, L51; from P10, the artifact-level goal (corrections 2.61): the CI check replaces it, and P10 keeps file-level
   D17. Each of those phases' net code caps must be re-measured against the master P1b leaves.
3. The audit ledger's counts are superseded by the d625284 map (inventory/README.md): the ledger re-check removes 18
   writer or reader claims and adds 19; the ledger's MC label on L04 (agent index) is withdrawn, because all its
   consumers take agent_resolver's one conclusion.
4. Path rule (found while mapping, not in PLAN-v2): hook state is written under `harness_state_dir()` but read at a
   fixed /tmp path in pretool-git-privilege-guard.py (/do consent :274; push grant `_find_grant` :328, called at :2135,
   whose block message :2093 names the same pattern; probes X11a and X11b2 on d625284), and /do reads its task sidecar
   at /tmp (commands/do.md:57) while prompt-workflow.py:1419 writes it under the state dir (do.md:58's fallback
   reservation, under /tmp while the hook's mint scans the state dir at prompt-workflow.py:1337, goes in rows 1 and 9).
   execute-push.py's `_SENTINEL_BASE` (:35) is both the chain-B sentinel's write root and the push-analyst grant's read
   root (:117): hooks/push.sh:106 reads the sentinel and pretool-push-analyst-grant-guard.py:73 the grant under the
   state dir, while the push-analyst writes the grant under /tmp (agents/push-analyst.md:155). The push-gate token is
   written under /tmp by the changelog-analyst's prose (agents/changelog-analyst.md:1221, :1247; dispatch text
   commit.md:666) and by the cleaner's under /clean (agents/cleaner.md:109-111), and read under the state dir
   (hooks/push.sh:212, posttool-push-gate-token-verify.py:44). With CLAUDE_STATE_DIR set each is a read of a file never
   written there. A writer moves with its prose and its write permission: execute-push.py:35 moves only together with
   agents/push-analyst.md:155, its path rules (:3, :33, :35, :200; commands/push.md:189, :214) and the analyst's write
   permission (policies/tool-policy.v1.json:800, enforced by pretool-tool-policy.py, or what E3 derives from the
   dispatch record).
5. pretool-git-privilege-guard.py:1254-1260 opens the `-F` operand as raw command text: planning trace-a saw it open
   `"/tmp/commit-msg-..."` with its quotes attached (ENOENT; A69). Stripping the quotes is not enough. In the bulk
   loop's `if ! git -C "${GIT_ROOT}" commit -F "${MSGFILE}"; then` (agents/changelog-analyst.md:1449, the form bulk
   mode must use, :1085-1087) the `;` stays on the operand, and a PreToolUse hook sees the command unexpanded, so for
   the `-F "${MSGFILE}"` form the analyst's prose gives (:1118, :1333, :1449, :1895) the guard opens the literal
   `${MSGFILE}` (docs/reference/harness-issues-backlog.md:54 measured `excerpt: ''`). Either way its bulk-commit
   subject check never reads the message the changelog-analyst wrote. It is a read of a path never written (A69). Take
   the operand from the shell-tokenised commit invocation, then make the analyst and the guard name one path: either
   the guard resolves the variable from an assignment in the same command, or the analyst's commit lines carry the
   literal path of its own Write (swap `"${MSGFILE}"` for the `"<msgfile>"` form CP-2 already gives at
   changelog-analyst.md:81-82, line for line, within acceptance 12). Choose by experiment; no new state file (C1). Test
   each form the analyst's prose gives: CP-2's quoted literal path (:81-82), the bulk loop's `if ! …; then` form
   (:1449) and `-F "${MSGFILE}"` (:1118).
6. G4: stop-obligation-gate.py's whole effect is advisory re-validation; when you delete it, the registered file
   becomes an exit-0 stub (D15, TC-37) for P5 to replace. P5's "arm and delete the advisory branch" shrinks to what you
   leave.
7. P1b arms G2 (E4); P2 arms G1 and G3, and its arming commit deletes the consumer-side copies E4 keeps for them (the
   PR lists each with its gate).
8. E8 removes `pending` from the do-report's `do.status` enum, and under (a) or its fallback no do-report exists before
   the /do agent writes one. P5 row 15 (`/do <task-id>`, TC-18, only if P5's Goal 6 keeps it) and its acceptance 5
   therefore find the unfinished task from a hook-written record with no completed do-report (the hook's
   `[/do] task-id minted: <id>` line at prompt-workflow.py:1425, the sidecar it writes at :1419, or under (b) the
   skeleton; name the one that still names the first task after /do, Esc, a plain prompt and a second /do in your
   replay), not from a pending do-report; P5 row 21's enum (S9) has no `pending`, and its skeleton message (:1434-1437)
   exists only under (b). Row 9 deletes stop-do-report-gate.py's `blocked` rewrite of the agent's report (P5's retired
   list, P5.md:841), which rewrites only `pending`; the gate's MAX_BLOCKS forced allow and its block stay P5's.
9. The /spec coverage phase: PLAN-v2.md:1158 keeps it unchanged and P5 keeps it and its block (P5.md:265, :607,
   :753), but it re-validates at the /spec orchestrator's Stop the views the spec subagent wrote, which goal 3 forbids.
   Row 8 moves its rule to G2 at the spec subagent's stop and leaves stop-spec-coverage-enforce.py an exit-0 stub in
   Rollback's (7), so P5's coverage phase blocks nothing.

### What the planning trace replayed (trace coverage)

The audit ledger read all ten pipeline commands. The runtime traces behind the d625284 map did not replay all of them,
and a CI check that derives relations from a runtime trace misses every artifact of a step no replay runs. Each
"partly" or "no" below is step-1 work for you (Scope row 0): the trace runner you ship must replay it.

| pipeline | planning replay | status |
|---|---|---|
| /spec | trace-b | replayed once |
| /dev | trace-a (2-lane fan-out); fault pilot (1 and 2 lanes) | partly: no QA-fail or BA-QA-fail loop (refined-context, context-iter, qa-input), no producer question or BA novelty check, graphify only "unavailable", no --codex, test-writer only on one lane |
| /redev | trace-a | replayed (singular cycle) |
| /dev-command | trace-b | partly: dev's write of a command file refused (scenario switched to scripts/lint.sh); `--spec` passed explicitly because auto-detect picked docs/dev/specs/INDEX.md |
| /dev-overnight | trace-b | partly: the launch only; the first cycle is a dead end on d625284 (E13); a what-if with marked deviations, in which every overnight python script was refused |
| /do | trace-a | replayed, then /close of the do-report |
| /close | trace-a (after /dev and after /do), trace-b (after /dev-command) | partly: no routing loop, no close-QA append round, no --auto, Step 0's block refused by bash-safety and re-issued as plain commands |
| /commit | trace-a, trace-b | partly: no --auto, no Phase 2 adoption, no late repair, `rm -f "$MSGFILE"` refused |
| /merge | trace-b | partly: the topic branch was a fixture; Step 3's `rm -f <grant>` refused; merge.sh refused on the dirty tree the pipeline left |
| /push | trace-b | replayed |

Not exercised by trace-a or trace-b: /restart and quota resume, /allow, /stop, armed gates (G2's escalation and hand-off
paths), CLAUDE_STATE_DIR set, hooks of one event running in parallel (the replays ran them in sequence), permission
prompts, and the CLI's own writes (transcripts, todos and settings are modelled). The fault pilot (prompts/P1c.md,
"What the pilot measured") ran /restart, a quota resume and armed G2's hand-off once each, without the write trace, so
the map holds no relation from them. The 33 map rows whose evidence is "code" (inventory/README.md) are the first
artifacts the regenerated trace must reach.

## Scope (re-verify every location on your base)

Locations are at d625284 with the inventory row (A..) that holds the evidence. "Moves" means the rule leaves a
consumer and lands in the gate at an allowed position (G2 or the producer's own stop, G1, G3); a rule that is already
there is deleted at the consumer, not moved. Where a row names an E-block, the experiment decides and the row states
both outcomes. Every deletion of code no live entry point reaches carries its reachability proof (D17).

| # | Group (map rows) | One producer kept | Deciding consumer kept | Moves to producer stop / G1 / G3 | Deleted |
|---|---|---|---|---|---|
| 0 | Step 1: the inventory on your base | — | — | — | Regenerate the map on your base before changing anything: run your trace runner over every pipeline and step in "What the planning trace replayed" (the "partly" and "no" items included) in shipped and in sandbox-armed settings, and run the static half (E1). Include what P7b and P8 added: P7b's landing writes of P7's overlay `settings.machine.json` and of P7's record `<git dir>/claude-settings.applied`, `logs/landing.log`, P7b's own `claude-settings.checked` marker and `claude-landing.lock` in the git common dir (the record, the marker and the lock are three files: map each), its new readers of settings.json's env, the seeded private-literal list and the installed pre-commit hook (A88 and A105-A107 hold P7b as merged, re-read at its head 1071ad3); P8's deletions (dead callers of the resolver, spec-update-contract.py, check-todo-accounting.py) and its moved grant pointer. The d625284 map is a starting point; acceptance is measured on your base's map. Put the regenerated map (before) and the after-map, both produced by your CI check's own derivation, in PR comments of at most 60,000 UTF-8 bytes each, linked from the PR body, never in the repository. |
| 1 | G01 cycle identity and registry (A01-A08, A125) | Task id: hooks/prompt-workflow.py's mint at UserPromptSubmit (:1462-1480; /do :1320-1360; /redev minted as /dev, D22). User requirement: prompt-workflow.py's O_EXCL writer (:1573-1574); scripts/overnight-init.sh:411 (written at :447) writes through the same function or hands the text to it (technical choice, replayed). Registry sentinels: prompt-workflow.py `_init_dev_registry` (:1546-1553), also for overnight registries. Enforcement flags: the UserPromptSubmit hook through scripts/write-enforce-flag.sh. Codex skill ledger (A125): hooks/posttool-codex-skill-ledger.py at the PostToolUse of a Skill call of codex (:93-116). | obligation.py `canonical_task_id`, `registry_dir_for` and `TASK_ID_RE` (one rule; every other place calls them); G2 and the e2e gate read the sentinel's task anchor through that rule; the `qa_mode` reading follows E7. QA's Phase 6 comparison (agents/qa.md:1150-1169) uses the blast-radius maps (A06; a use, as row 6 counts QA's reading), so graphify-enrich.py's nil-map skip (:477-491, less its context patch at :491, which row 4 deletes per E10) is their only deciding read; it, graphify-query.py's test of the requirement file (:284-288, A02) and /dev's graphify sentinel test (dev.md:759, A03) stay as uses or their rules move into the gate, as row 19 rule 6 and E4 measure. The codex skill ledger's one deciding read is subagentstop-codex-enforce.py's existence test of the stopping BA, dev or QA subagent's own entry (:86-99, exit 2) while A05's codex flag is enabled (:75-84); its role list (:31) goes with row 18's rosters. | none (the mint is the producer) | The orchestrator fallback mint and fallback blocks (commands/dev.md:196-218, dev-command.md:141-163): when the hook output is no longer in the orchestrator's context (as after a compaction), the orchestrator uses the `task_id` the hook wrote at this command's start into the session-keyed bookmark (sid from CLAUDE_CODE_SESSION_ID, as do.md:56 resolves it; prompt-workflow.py:1880-1897, or the record E7 moves that field to), never a registry picked by name or age and never the owner typing the command again; if the hook recorded no id for this command (it failed), the orchestrator calls the hook's own start function for its session and command text, which writes the id, the registry, the requirement and the flags, so the hook's code stays their one producer (technical choice, replayed; no command text mints an id or writes a registry, requirement or flag itself); /do's fallback mint (do.md:58); the regex copies (subagentstop-artifact-contract-enforce.py:223-235 (the session_ts dimension of `_find_correlated_reports`, with the glob only it reads, :219-220, and its docstring mentions, :45 and :209-212, reworded; the candidates map :221 and the task-id dimension :237-247 stay for the path row 6 keeps), pretool-aggregate-check.py:96-107, posttool-lane-completeness-watch.py:113-119, scripts/dev-lifecycle.py:37, close.md:553-561 and :582 `SESSION_ID="dev-${TASK_ID}"`, dev.md:128, dev-command.md:890); the test-writer's self-created sentinel (dev.md:799); the graphify sentinel's read where nothing wrote it (prompt-workflow.py:1531-1547 writes it only when a graphify binary resolves; /dev-command's dispatch, dev-command.md:569-571, has no sentinel test, and graphify's FIRST ACTION reads it, agents/graphify.md:22): that read loses its branch, or the sentinel is written wherever graphify is dispatched (technical choice, replayed); write-qa-mode.sh's `--init-if-missing` creation and, per E7, its `qa_mode` mutation (for the base's calls in a running session the option stays accepted and creates nothing, and where the sentinel it would have created is missing, as on a /do or /dev-command task, whose `dev-<ts>` that call binds (close.md:582) neither task's mint creates, the call exits 0 with nothing written, never with the refusal of write-qa-mode.sh:73-74, which the base's arming rule repeats into its `no_progress` stop (close.md:263-267); the script becomes an exit-0 stub if nothing is left; acceptance 17); /close's QA re-arming of the flags (close.md:244-274; on a /do task, which starts no registry, the only writer of the flags and of the `qa.json` close QA's FIRST ACTION line reads, a line that stays: acceptance 4); the overnight-init.sh second flag caller (:303-322) once the launcher arms overnight registries through the same path; the launcher's and the initializer's checks of the registry, the flags and the requirement, each a second rule on what the one producer wrote (scripts/create-overnight-state.sh:881-1019, its flag-to-roles map :910-912 included; overnight-init.sh:284-293, :334-364 and :451-452 in every mode, and its --verify-only assertions :136 and :163-165, which the actor's run at every cycle makes, dev-overnight.md:261, :325, and prompt-workflow.py's own runs make at the launch (:1966-1972, exit 2) and before each continuation block, with a --repair-only run between two of them (:1179, :1690-1729); the actor's run stays for the values the actor binds from it, dev-overnight.md:329-338, and the hook's runs, which use only the verdict, go with these checks (prompt-workflow.py `verify_overnight_state` :1633-1665; `_repair_overnight_registry` :1668-1744, with its WARNING that an invalid registry needs a human, D20; the --repair-only mode only it runs, overnight-init.sh:36-46, :166-188)); the role lists of the registry (prompt-workflow.py:1514-1526, dev.md:202-208, dev-command.md:146-151) and of the flags (write-enforce-flag.sh:54-61) per row 18; the dispatch-metadata writer (A07; no command, agent or hook runs it) if the regenerated map confirms no reader, and QA's read of start-sha (agents/qa.md:1161), which nothing writes. |
| 2 | G02 workflow bookmark, todo list, replay stores (A09-A13) | Bookmark: prompt-workflow.py writes it once at command start. Todo list: the CLI's TodoWrite (a record in the transcript); no harness writer. Replay store: prompt-workflow.py (self-consumed at the next start, a use). | command_span (`calls()`, `last_todos()`, added per E7) for every reader of todos and dispatch counts (pretool-todo-validate.py, pretool-block-background-tasks.py, pretool-spec-block-foreground-agent.py, pretool-workflow-gate.py, posttool-todo-sequence.py (its step-sequence check against the bookmark's last_todos, read at :219-228, exit 2 at :164), posttool-todo-count.py (its count check of the TodoWrite against the canonical list for the bookmark's command and arguments, read at :85-88, exit 2 at :60), posttool-todo-tracker.py (its count gate on its own todo-file and todo_acknowledged writes, :104-120, on the command and arguments read at :79-83; the gate goes when E7 deletes both writes), prompt-workflow.py's progress notice at each prompt that names no command (its text follows the bookmark's lock_reason, todo_acknowledged and last_todos, `read_bookmark_state` :1205-1227, called at :1259), its workflow-conflict warning at a new command's start (:1308-1316, called at :1874, :1935), pretool-subagent-enforce.py, stop-spec-coverage-enforce.py, posttool-subagent-track.py's step pairing for the subagent-call record (:414-437, :480-525, on the bookmark's command, arguments and last_todos read at :429-436 and its subagent_calls read at :186; the pairing goes when E7 deletes the writes it places, :247-260 and contract_runtime.py:1208-1250)), per E7. | none | Per E7, the bookmark mutations in posttool-subagent-track.py:247-260, posttool-todo-sequence.py:146/:171, posttool-todo-tracker.py:97/:120, pretool-workflow-gate.py:908/:998/:1116, posttool-todo-count.py:50, contract_runtime.py:1208-1250, and the harness writes of `~/.claude/todos/<sid>-agent-<sid>.json` (prompt-workflow.py:1896/:1975, posttool-todo-tracker.py:93/:110, pretool-workflow-gate.py:901, break-overnight-lock.py:113); workflow-history (prompt-workflow.py:1802-1828 and its call :1893; probe X2: written at the second /dev of a session, read only by its own collision check); the replay decision's private terminal set (prompt-workflow.py:1783) in favour of obligation.TERMINAL_VOCABULARY. |
| 3 | G03 dispatch record and producer-gate outputs (A14-A18) | Obligation block: the orchestrator's dispatch from the command templates (a record in the transcript). | G1 at dispatch, G2 at the producer's stop, G3 at the next dispatch, all through obligation.py; nothing else validates an obligation or its artifacts. | the e2e gate's QA-report rule moves onto the QA dispatch's own obligation: it reads the path that obligation declares, not "the most recent qa-report" (subagentstop-e2e-enforce.py:115; fault pilot: the newest-file correlation masks a missing lane report and wedges every lane on a stale one) | G4's re-validation: stop-obligation-gate.py:103-145 (the file becomes an exit-0 stub, D15), obligation.py's re-validation inside find_unresolved_dispatch_obligations (:1007-1035; keep only what the declaring-dispatch reader of E3 uses), posttool-overnight-loop.py:142-222 terminal lanes; G2's escalation stores and admission (subagentstop-artifact-contract-enforce.py:614-635, :637-656, :659-713, :747-829, deferred-checks :691) so G2's failing stop is a plain exit 2 naming the failing artifacts to their producer (corrections 2.27), and the arbitration comment (:292-297); the advisory log writes per E12 (pretool-obligation-gate.py:91, stop-obligation-gate.py:56, posttool-overnight-loop.py:28, subagentstop-artifact-contract-enforce.py:124, pretool-aggregate-check.py:388, subagentstop-cp-enforce.py:36, stop-do-report-gate.py:58, posttool-lane-completeness-watch.py:68); the second role list (pretool-obligation-gate.py:80-86 against obligation.ROLES :74-80) per row 18. |
| 4 | G04 BA and context family (A19-A30, A122) | Context: BA (agents/ba.md:145). Ticket, acceptance criteria: BA. BA-QA report: QA in BA-validation mode. Graphify pre-query: scripts/graphify-query.py; graph cache: one of graphify-maintain.py and graphify-enrich.py (technical choice with a stub binary). Graphify run record: graphify-enrich.py (:648) for the registry copy, the /dev-overnight orchestrator for the cycle copy (dev-overnight.md:1266). | G2 at each producer's stop and G3 at the next dispatch; the orchestrator's verdict branch on the BA-QA report (dev.md:691-699, dev-command.md:507-515, dev-overnight.md:1165-1176) stays as the route (a use, not a check), and so does its status branch on the graphify pre-query (dev.md:249, dev-command.md:194, dev-overnight.md:970), the one rule on that file's status: BA's structural-context step and QA's graphify gates (agents/ba.md:666, agents/qa.md:104-112) apply when their dispatch names the file, with no status test of their own. /dev-overnight Step 11g's fingerprint skip (dev-overnight.md:1246) stays as a use: it compares the hash of the context Dev will consume with the fingerprint in graphify's run record, a cache key, not a check of either file. The warn-only hooks on the newest context by mtime (pretool-layer-match-gate.sh:14, subagent-stop-guard-integrity.sh:19, pretool-layer-escalation-check.sh:12, pretool-bisect-gate.sh:12) stay as uses, since no feature goes (D15): each exits 0 on every input and writes only stderr (subagent-stop-guard-integrity.sh also writes its own lock file, :13-14, A114, which no other code opens: a run that finds it held exits 0), which reaches neither the agent nor the owner (landscape D1.e; E12), so E1 measures no decision, and their newest-file pick, unlike the e2e gate's (row 3), blocks nothing. | dev.md's post-BA "sanity checks" (:352-389, :527-538) and the test-writer gate's field checks (:789-791) are schema-checkable: what G2's context.v1 already checks is deleted, anything it lacks moves into the schema (E4 shows which). | Per E10, the orchestrator patches of the context (dev.md:540-584, :1163-1166) and graphify-enrich.py's in-place patch (`_build_graph_context_patch` :413-443, called at :612, and `_patch_context` :623-643, called at :491, :505 and :615), and every graphify output the regenerated map shows with no reader (at d625284 each has a prose one: graph-summary.json the orchestrator's status note, dev.md:780; focused-subgraph.json dev's consult, agents/dev.md:127; both it and graph-report.md QA's presence fields, agents/qa.md:120-121; the registry copy of graphify-run.json the fingerprint skip of /dev-overnight Step 11g, dev-overnight.md:1246, while under /dev and /dev-command nothing reads it); the orchestrator's fingerprint update of that registry copy (dev-overnight.md:1266), since graphify-enrich.py, its one producer, records the fingerprint itself instead (goal 1): at d625284 only that update writes it, and the run record the script writes on every path (`_write_outputs`, :645-648) has none of the four fields Step 11g's skip requires (dev-overnight.md:1246), so the script gains them from its dispatch and the context file it is given; the refined-context and context-iter builds (the jq of dev.md:1177-1199 and dev-command.md:777-795, and /dev-overnight's scripts/refine-context.sh, run at dev-overnight.md:1492-1497; Step 11g, :1246, then fingerprints the context Dev is dispatched with) and the qa-input reading branch with its naming-list mentions (dev.md:1196, :1392-1396; dev-command.md:793, :916-920): the QA-fail loop re-dispatches the lane's dev with the QA report path (D2); BA's write permission on ba-qa-report (policies/tool-policy.v1.json:127); the resolver's re-check of the ticket and context at /close and /commit (row 7); scripts/create-worktree.sh's copies of docs/dev artifacts into the overnight worktree, unless E13's replay shows the worktree cycle needs them (then the copy is the worktree's own producer and the main tree's file is not read there); the observations ledger BA writes and only BA opens (docs/dev/observations-ledger.md, agents/ba.md:474-511), per E12. |
| 5 | G05 test-writer artifacts (A31-A33, A121) | test-writer. | G2 and G3. QA Phase 5 reads the per-task manifest's active_tests[] to run those tests (agents/qa.md:1125-1127): a use, whose findings judge dev's work (A121). | QA Phase 5's checks of the test-writer's files (agents/qa.md:1128-1129), deciders of A32 and A33 whose findings the QA-fail loop returns to dev (dev.md:1175), not to their producer: a missing per-task manifest after the test-writer ran is G2's check at its stop and is deleted, as is the missing tasks[] entry in the global index, which only repeats that fact (goal 1); a listed test file missing on disk, and a test-writer dispatch skipped while test_writer_expected is true, move to the allowed position per E4 (G2; G1 or G3 at the dev dispatch). | The orchestrator's existence check that "aborts the cycle" (dev.md:818, a duplicate of G2 for the report and the per-task manifest; no obligation declares the global index, dev.md:803, so its index part goes with the index or moves per E4); the global index upsert (tests/generated/manifest.json) if the regenerated map confirms no reader besides the two this row removes (planning: the existence check, dev.md:818, and QA Phase 5's tasks[] entry rule, agents/qa.md:1129, which dev.md:1011 names as QA's sentinel; otherwise snapshot scanners only). |
| 6 | G06 dev-report family and ownership facts (A34-A43) | Lane or singular dev report: dev. Canonical aggregate: per E5. Ownership facts and baseline: per E6. Late repair: scripts/late-repair-controller.py writes only its own files. Terminal vocabulary: the schema; obligation.TERMINAL_VOCABULARY keeps only which field of which schema is terminal and reads that field's enum from the schema at import (row 18; the drift test goes). | G2 at dev's stop (the obligation path; the legacy correlation path only for a dispatch without an obligation) and G3 (pretool-aggregate-check.py) before QA; QA uses the report (a use). Consumers that need the cycle's state call the one chain function (row 7). The warn-only hooks' reads of dev reports (pretool-layer-match-gate.sh:15, the newest; subagent-stop-diff-check.sh:36-43, any changed in the last 10 minutes) stay as uses for row 4's reason. | posttool-overnight-file-check.py validates against the dispatch's obligation, not a contract schema name (E13; one declaration, fixes the ledger's E1, the v1/v2 contract conflict); the lane roster check moves from posttool-lane-completeness-watch.py into G3, and so does the gitignore preflight's rule on a dev report an Agent dispatch names (a path in its dev.files_modified or dev.files_created that `git check-ignore` matches, with no `gitignore_waiver`, blocks that dispatch: hooks/pretool-gitignore-preflight.py:717-820, exit 2 at :818; A34, A35, and A43's effective report, which /commit's Step 6 and Step 7 changelog-analyst dispatches name as the repository plan's report after a verified late repair, commit.md:324-325, :355, :483, :602, resolve-commit-repos.py:724, and whose task the preflight reads from its name as `<task>.effective`, since source_task_id strips only `dev-report-` and `.json`, pretool-gitignore-preflight.py:599-602, so its `has_live_commit_grant` exemption, which compares that id with the grant's task_id at :692, never admits those dispatches), a second rule on the report at the dispatch, where row 3 leaves a prior stage's artifacts to G3 alone: G3 applies it, with row 11's admission of /commit's changelog-analyst dispatches in place of the preflight's `has_live_commit_grant` exemption (a verdict that turns on the dispatch, so not G2's), and the preflight keeps the rule with that admission while G3 is advisory, as E4 keeps a copy whose faults only G3 would stop, until P2's arming commit deletes it (acceptance 9 replays the admission on it); for A43's effective report the report's task that the admission compares with the obligation's `task_id` is the task for which resolve_effective_report_state returns that path in state `verified`, as the changelog-analyst accepts the report (agents/changelog-analyst.md:185-188), never the one its name gives (`<task>.effective`), with which the admission would never apply and row 10's loop would return the block to finalize, the report's producer, whose rewrite under the same name from the task's dev report (late-repair-controller.py:337, :372-383) is blocked again on every round, so the admission admits a verified late repair's dispatches as it admits a dev report's (E4's fallback where no replay reaches finalize's writing branch); verify-disclosure's rule on finalize's effective report (A43: the file exists, parses and carries the block finalize embedded) moves into finalize's own run, the report's producer, which checks the file it wrote (scripts/late-repair-controller.py:383-391) before it records its outcome and the path (:393-397) and otherwise refuses, naming that path. | late-repair-controller.py's writes into the singular dev and QA reports and BA's ticket and context (record-stage's `_embed_disclosure` call, :312: its JSON branch :92-98, its markdown branch :100-106) and its stage-to-basenames table (:82-88, E3); verify-disclosure's reads of the blocks record-stage wrote into those files (late-repair-controller.py:440-451, run at every /close --late-repair and, through resolve_effective_report_state :496, at the /commit after it), which would refuse every such run with no exit once nothing writes the blocks: verify-disclosure names in each refusal the artifact's path, not the label it names now (:437-454), so close.md:144 returns the fault through row 10's loop to that artifact's producer; verify-disclosure's checks of finalize's effective report (its existence, block and hash on that target, late-repair-controller.py:427-432, :438-454) and the existence tests that resolve_effective_report_state and two of its callers add (:518-520; resolve-commit-repos.py:461; resolve-dev-report.py:48), run at /close --late-repair (close.md:143) and at /commit through that function (late-repair-controller.py:496; Step 5, commit.md:313-322; resolve-commit-repos.py:434, :460; resolve-dev-report.py:45; changelog-analyst.md:185-186), class-(b) and class-(c) checks at /close and /commit that no gate covers, since finalize is a script G2 never sees (goal 3; ruling 1; row 19 rule 6's third case; acceptance 13), whose rule this row moves into finalize, with the hash finalize records of the file (late-repair-controller.py:396), which only they read (:431): verify-disclosure and that function then take the effective report only from the outcome and path finalize recorded, and every caller takes the function's state and path verbatim (goal 2); finalize's refusal, and a gap at /commit on a file removed or broken after finalize ran (its first use, the plan of commit.md:353-360, names the path), go through row 10's loop to finalize, which E3's reader returns for that path as a main-agent step of the route (close.md:142), declared in /close's canonical todo list under `--late-repair` as scripts/todo/close.py declares the forced steps under `--force` (:27-30, :44-51), and which the /close or /commit that asked runs under the run record's repair_run_id, as row 10 runs /dev Step 11; finalize writes the file afresh on every run and has no refusal of a second run, so that route has no dead end (acceptance 5, with E4's fallback where no replay reaches the branch that writes the file, late-repair-controller.py:372-397); in Rollback's (7) (E4), verify-disclosure's comparisons of each stage's report with the path and hash its run record holds (existence late-repair-controller.py:438-439, hash :452-454, against :315-320) and record-stage's existence check of that report (:295-296), re-checks of what G2 decides at the report's producer's stop (goal 3, row 19 rule 6; ruling 1's classes b and c), with the stage targets (:422-426) and the hash record-stage takes of the report (:313, stored :317), so verify-disclosure admits a run that recorded no effective report only when its record holds finalize's drift-free outcome (the test of resolve_effective_report_state, :512-516, one function both call; goal 2) instead of refusing it for want of a target (:434-435), and with record-stage's refusal of a stage already recorded in the run (:285-286; close.md:141's "duplicate"), which only kept that hash from being replaced: on the base, once verify-disclosure refuses a stage's report, its producer's new one is never recorded, so verify-disclosure refuses on every round of close.md:144's re-record and of /commit Step 5's loop (commit.md:316-322), a dead end (acceptance 14); on your branch a stage report missing or schema-invalid at its producer's stop goes back to that producer through G2 at that stop (E4), and one removed or broken later through the next one chain-function call (row 7; /commit Step 5's, commit.md:334) and row 10's loop to the dispatch E3's reader returns for it (acceptance 7); per E9, the aggregator's merge into the singular report (aggregate-dev-report.py:1321-1505, called at :3738-3740); the aggregator's re-run at /close Step 0 and /commit row 1 (ruling 1); its `superseded-<task>/` reading branch (aggregate-dev-report.py:962-1036, read and never written); the lane-watch's roster decision; prompt-workflow.py:1786-1799, posttool-overnight-loop.py:32/:156-200, dev-lifecycle.py:201-252 and aggregate-dev-report.py:2099 (`_TERMINAL_DEV_STATUSES`, used at :2161) private terminal sets and re-derivations (they import the one vocabulary or call the chain function); per E6, verify-attribution-chain at /commit Step 5 if it only re-checks and the aggregator union once no reader of it is left (each losing candidate stays for its readers, listed with the phase that retires it); journal-view (subagentstop-artifact-contract-enforce.py:451-465); aggregate-pending (posttool-lane-completeness-watch.py:126-129, :188-208, :309); the role-to-prefix and per-role field tables (subagentstop-artifact-contract-enforce.py:119-122, posttool-overnight-trace.py:256-269) per E3. |
| 7 | G07 QA report, completion report, chain disposition (A44-A46) | QA report: QA. Chain conclusion: scripts/resolve-dev-artifact-chain.py, the one function every consumer calls (P3 later turns it into `--disposition`). | G2 at QA's stop and G3; the e2e gate reads its own dispatch's obligation (row 3) and decides only `e2e_enforcement.status` (qa-report.v2.json:5: the schema checks shape, the gate the status policy); its missing-report block (subagentstop-e2e-enforce.py:318-326) goes in the commit that arms G2 (E4), since G2 then decides existence at the same stop. /dev's end, /close and /commit each call the one chain function once and use its output verbatim (ruling 1 allows class a there; /close's call is Step 0's: scripts/close-route-select.py:53, or with `--late-repair` late-repair-controller.py init's (:218-219), which stays as that route's only call (close-route-select.py:74 runs init instead of :53, close.md:137; principle 6); /commit's call is Step 5's, commit.md:334, which stays, and row 10's routing loop re-runs it after each dispatch it makes for the call's gaps); calling the same pure function is trusting one conclusion, re-implementing any part of it is re-deriving. Continuation-spec mode, wherever one of these commands runs it after its call, takes that call's output verbatim instead of running the function again as spec-update.md:50-53 tells it to (A46 lists that caller): /commit Step 8's continuation agent, which E14 keeps, takes Step 5's output from its dispatch (commit.md:930), as Step 7's changelog-analyst does (commit.md:594, :603), and /dev's and /dev-command's workflow update (dev.md:1359-1363, dev-command.md:897-900) and /close's fresh continuation spec (close.md:924-930) use the `ARTIFACT_CHAIN` their main agent already holds from that call, so each command still calls it once; a /spec-update typed on its own is none of goal 3's commands, and row 19 rules 5 and 6 measure its run like any other read. Each call kept runs the harness's copy, spelled `python3 ~/.claude/scripts/resolve-dev-artifact-chain.py` as in E5 (b), since a product repository has no scripts/ (dev.md:1322, dev-command.md:889 and commit.md:334 call `python3 scripts/resolve-dev-artifact-chain.py`); its `--project-dir` argument stays (an empty value is the cwd, resolve-dev-artifact-chain.py:1775). So does every other harness script that close.md or commit.md runs by a repository-relative path, or behind a repository-relative venv activation, on a step your replays reach (acceptances 4 and 7, and the --auto and /commit late-repair replays "What the planning trace replayed" asks for), in the same `~/.claude/scripts/` spelling; at d625284 these are /close's call, which runs inside `python3 scripts/close-route-select.py` (close.md:345), /commit Step 5's `source venv/bin/activate && python3 scripts/late-repair-controller.py` (commit.md:313, :320; a product repository has no venv/ either, so it runs with no venv, as in E5 (b): late-repair-controller.py:34-48 imports only the standard library and scripts/lib/sibling_loader.py, found from its own file), /commit's grant writer, `source venv/bin/activate && python3 ~/.claude/scripts/write-commit-grant.py` (Step 5's mint, commit.md:459, and the same writer's revokes and retry mint in Steps 6 and 7, :486, :570, :821: the same missing venv/, and write-commit-grant.py:91-100 imports only the standard library; left as it is, the `source` fails, no grant is minted, and commit.md:434-440 makes the failed mint a finding the orchestrator re-mints through the routing loop before any analyst is dispatched, a failure no DEVIATION passes), the --auto discovery's `python3 scripts/dev-lifecycle.py list-actionable` (close.md:950, commit.md:965) and /close --auto's flag check, whose python loads `scripts/dev-lifecycle.py` (close.md:66-68), close QA's append helper (row 10), `python3 "$PROJECT_ROOT/scripts/close-report-append.py"` (close.md:776), and, if a replay runs /close --late-repair, its controller calls (close.md:141-143). So does an agent file's call of a harness script by a path a product repository does not have where its failure ends one of those replays short of its terminal (a failure, not a block, so no DEVIATION passes it): the changelog-analyst's dev-report resolution, `${CLAUDE_PROJECT_DIR}/.claude/scripts/resolve-dev-report.py` (changelog-analyst.md:399: the CLI's Bash leaves the variable unset (E5) and a product repository has no .claude/scripts/, so the output is empty, which reads as no dev report, and Phase 2 aborts with `scope_violation` before staging, :342-349, on every /commit of a /dev, /redev or /dev-command task), its Phase 1 load of `scripts/late-repair-controller.py` (changelog-analyst.md:185, which the /commit late-repair replay reaches; a failed load is `repository_plan_invalid`, :186-190), and QA's Phase 5 guard, `python3 scripts/qa-manifest-guard.py` (qa.md:1137-1138, on every lane with `test_writer_expected`, :1123: python exits 2 on the missing file, the guard's own `vacuous_rejected` code, which :1140 turns into `qa.status` fail on every round). So does the Phase 2 adoption call, `"${CLAUDE_PROJECT_DIR}/.claude/scripts/stage-owned-hunks.py"` (changelog-analyst.md:729), whose exit 127 ends no replay, since any non-zero exit falls through to the ordinary staging decision (:757-760), but leaves the Phase 2 adoption replay row 0 runs ("What the planning trace replayed") with the adoption route never run; respelled, it adds no stop. Each script already does what E5 gives the aggregator: it takes the project root as an argument where it needs one (`--project-dir`; the append helper an absolute `--report-path`; resolve-dev-report.py `--git-root` and `--control-root`; stage-owned-hunks.py `--git-root`; write-commit-grant.py `--repo-root`) and finds the harness files it loads from its own file (close-route-select.py:34-43, late-repair-controller.py:47-48, dev-lifecycle.py:49-50, close-report-append.py:214-217, resolve-dev-report.py:19-20, stage-owned-hunks.py:4625, write-commit-grant.py:105; qa-manifest-guard.py loads none), so no option is added and only the path changes. A respelled call names its interpreter and a path that resolves where it stands: `python3 ~/.claude/scripts/<name>` (`bash` for a .sh script), the path an unquoted shell word, since bash expands `~` only at the start of one; so a call that names the script by its path alone gains `python3` (changelog-analyst.md:399, close.md:141-143: resolve-dev-report.py and late-repair-controller.py are mode 100644 at d625284, so their path alone exits 126, permission denied, and resolve-dev-report.py:5 gives the `python3` form), a call behind `source venv/bin/activate &&` loses that prefix and runs with no venv, as in E5 (b), since a product repository has no venv/ (commit.md:313, :320, :459, :486, :570, :821, and dev.md:885 where a replay runs the base's text), a quoted path loses its quotes (close.md:776), and inside Python, which expands no `~` (close.md:66-68's string literals, inside the shell's double quotes; the analyst's load, changelog-analyst.md:185), the path is `os.path.expanduser('~/.claude/scripts/<name>')`, with `import os` added where the code has none (close.md:66-67 imports only sys and importlib.util). Wherever a replay runs the base's text (acceptance 4: every replay in the base kit, and acceptance 17's in-flight cycle with its /close and /commit and its in-flight closes, built from the base's command and agent text, in either kit), the same drivers run each of these lines as respelled here where that text still has the old form (a path, not a rule; your branch's own text already carries it), and, spelled the same way, each other harness-script call of that text whose failure in a product repository would end that replay short of its terminal (at d625284 /dev Step 11's aggregator, dev.md:885, E5, the `qa_mode` flips of /dev and /dev-command, dev.md:609, :978 and dev-command.md:437, :627, E7, and the lines rows 1 and 6 delete: /close's QA arming, close.md:246-249, and Step 0's aggregator re-run, :338), with CLAUDE_PROJECT_DIR set to the product root in that call's environment where the script finds the product root only through that variable (the CLI's Bash does not export it, E5; without it aggregate-dev-report.py:173-182 takes the harness home from its own location, and write-qa-mode.sh:35 and write-enforce-flag.sh:42 exit); like a deviation, this lives in the driver only and the CI check reads none of it, so both kits reach the same steps and acceptances 4 and 17 compare their blocks; list each in the PR. Not respelled in your branch's text: the lines rows 1 and 6 delete (close.md:246-249, :338); the changelog-analyst's session-index calls (:651, :665, :669), since the guard at :651-654 (`eval "$(…)"`, then `exit 1` if that fails) does not fire on a missing script (eval of an empty string returns 0; landscape/B-breakages.md:42, P5), so the analyst goes on to stage and commit on the shared index in both kits, and switching the private index on is P1c's X5 and P2's TC-44 (P2.md:756); and every other agent-file call whose failure the replay passes (for example the blast-radius tool calls, ba.md:789 and qa.md:1155, which leave no map, so QA's Phase 6 has nothing to compare), left to P2's TC-44. Change only those lines and list them in the PR for P2's TC-44 substitution. | G2's qa wire (subagentstop-artifact-contract-enforce.py `_wire_qa_chain` :523-564) checks other producers' artifacts at QA's stop, which is the wrong producer: what it checks moves to G3 at the next dispatch, or is deleted where G3 already checks it. | /close's schema gate (close.md:434-491) and /close Step 0's re-validation layer (scripts/close-route-select.py's own verdict, close.md:344-398); dev-lifecycle.py's own stage derivation and its SQLite cache (:858-937, written and never read); not deleted: aggregate-dev-report.py's use of the resolver, which runs no chain (:597 is the docstring of its loader :596-622) and calls two of the resolver's own functions, `_adjudicate_serialized_wave` (:665-675) and `ac_deviation_provider` (`_load_deviation_provider` :1832-1857, called at :3837), whose results it uses verbatim (trusting one conclusion); these are library calls inside the canonical aggregate's producer (E5), not chain calls: row 19 rule 5's one call per task counts only calls of the chain function, so they are no second call, and they are not respelled, since the aggregator loads the resolver from its own file (:615, :1848); the completion report leaves the resolver's required chain (it restates the chain result and is orchestrator-written, D8) and is still written: /commit Step 8's continuation agent, which E14 keeps, gathers it (commit.md:934-936; A45), so it is none of the written-never-read files E12 decides; the orchestrator's writes of QA content into the spec, the context and the score log (dev.md:1026-1048, :1180-1182, :1062-1075; QA's spec section text stays in its own report per E14); the settings write (dev.md:1081-1110) follows row 16; the resolver's chain and family lists (resolve-dev-artifact-chain.py:1030-1035, :1137-1143, :1196-1200) and dev-lifecycle.py:667-672 where E3's reader names the same files; the resolver's fan-out optional-parent read (`_optional_parent_result` resolve-dev-artifact-chain.py:1146-1170, its call and its report-path and whitelist entries :1980-1986, the `optional_parent_artifacts` key :1301, which no non-test code reads) and dev.md's sentence stating it (:1340-1342): every fan-out dispatch writes lane-suffixed paths (dev.md:99), none declares the unsuffixed parent ticket, context or qa-report, and dev.md:1342-1343 forbids inventing them, so nothing writes what it reads (D24; fault pilot F3b in prompts/P1c.md: a stale unsuffixed qa-report fails the Step 17 resolver, a dead end); singular cycles and the "Never create, copy, or invent" sentence unchanged. |
| 8 | G08 spec, checkpoints, split views (A47-A50) | Spec monolith per E14; spec path: prompt-workflow.py at UserPromptSubmit. Checkpoint state: scripts/spec-check.py (the CLI agents run). Split views and manifest: the spec subagent; views/mandate-omissions.json, which the subagent appends (agents/spec.md:334-338), has a second writer, scripts/spec-verify/spec_verify_mandate.py `_record_omission` (:324-335), which records an omitted Role Mandate while it checks the views, and D24 leaves one of the two (which one is a technical choice, replayed in both kits on a /spec run with the kit's templates/overnight-spec.md given front matter declaring `guide_version: 1`, which no /spec step writes (the template starts with its title, :1) and without which spec-verify writes nothing (spec_verify_mandate.py:412-413), where the spec subagent omits one selected agent's Role Mandate, once as its text says (on the base it appends its R3.4 record, agents/spec.md:334-338, which `_record_omission` then skips, spec_verify_mandate.py:328-329) and once with that record left out (which `_record_omission` then writes, :330-335): row 19's check derives both writers of the file from the base kit's traces of the two runs, and the choice ships when it derives one from your branch kit's (rule 1, no exception)). The `.split-complete` marker: the /spec orchestrator, which writes it after the split QA loop's last verdict and appends its round-3 warning (commands/spec.md:420-422), a verdict the subagent, dispatched before it, never sees; commands/spec.md:181-182, :503 and :510-511, which call the marker spec-subagent-owned, drop that claim. | For cp-state, one rule (goal 2) on whether a checkpoint state is running: subagentstop-cp-enforce.py at the producer's stop tests `is_running` alone (:68), while hooks/lib/agent_resolver.py's role resolution also needs a fresh check-in (:228) and reads cp-state before the agent index (`_scan_cp_state_files` :211-232, called at :237) for the one hook that blocks on the role it returns (pretool-tool-policy.py:348, exit 2 at :311-335; pretool-subagent-code-block.py:69 only warns, :34-56; pretool-overnight-hook-guard.py:202 is reached only behind a contract self_repair block that no writer sets, :339-343); both call one function, or one of them loses its read (technical choice, replayed); resolve-spec-artifacts.py at /spec finalize (the producer side) and as the entry precondition of /dev, /dev-command and /dev-overnight (G1 position: dev.md:157-172, dev-command.md:101-112, and the /dev-overnight launcher and every initializer run, scripts/create-overnight-state.sh:678-700, scripts/overnight-init.sh:377-394), each taking its one conclusion. | stop-spec-coverage-enforce.py's rule (`spec-verify.py --strict` on the views against the monolith, stop-spec-coverage-enforce.py:188-198, run at :272, exit 2 at :213) moves into the obligation of the spec subagent's dispatches (commands/spec.md:297, :377; row 18 admits /spec as their pipeline), checked by G2 at that subagent's stop (E4: the views' own properties, agents/spec.md:564-568, which its Step 7 checks only in prose, :494, :551). The hook is the Stop coordinator's coverage phase (stop-workflow-coordinator.py:68-69; settings.json registers the coordinator only under Stop, :796-801), so it never runs at the subagent's stop and its block lands on the /spec orchestrator, which wrote no view; after the move a split that fails the rule goes back to the spec subagent, and Step 7's note that the hook blocks the subagent's exit (agents/spec.md:488-489) names G2. The base's templates of the spec subagent's dispatch carry no obligation (commands/spec.md:299-313, :380-406), and a /spec in flight at your merge still dispatches from them while its Stop runs the hook's exit-0 stub (D15): G2 checks the views of such a dispatch by the rule the current /spec template's obligation declares for them, that template found as E3's derived write permission finds the template of a dispatch that carries none (technical choice, replayed in acceptance 5), so the hook's rule still stops the spec subagent in a running session (E4). | The three spec mtime rules (dev.md:125-138 and its staleness guard, dev-command.md:87-95, create-overnight-state.sh:500-517); pretool-cp-checkin.py's cp-state payload writes (:309-313, :423-430) and the spec agent's direct cp-state write instruction (agents/spec.md), leaving spec-check.py as the one writer; /close's split-view re-check (close.md:504-519); the `.spec-binding.json`, design-turn and evidence-copy writes (commands/spec.md:177-178, :193-198, :222-226) if the regenerated map confirms no reader outside /spec; the split QA's existence test on the design turns and evidence copies (check 6, :356-357), which re-checks the Finalize guard's test (:278-293) and sends its fail verdict to the spec subagent, which writes neither; views/allocation-decisions.json (agents/spec.md:538), which nothing reads, per E12's rule; in Rollback's (7) (E4), re-checks of what G2 then decides at the spec subagent's stop (goal 3; row 19 rules 5 and 6), until then those faults' only stops: the split QA's coverage test (check 3, commands/spec.md:335) and stop-spec-coverage-enforce.py with its bookmark read (:73-82, row 2) and its transcript tail scan (:112-157, row 18), the hook becoming an exit-0 stub, as D15 keeps a hook file, so the coordinator's coverage phase blocks nothing. |
| 9 | G09 /do (A51-A55) | Consent flag and task sidecar: prompt-workflow.py at UserPromptSubmit. Reservation markers: prompt-workflow.py:1348. /do report per E8. | One `has_do_consent(payload)` in hooks/lib/allowlist.py (state-dir path, content `true`, the subagent check), called by every consent reader (eleven hooks with thirteen read sites at d625284; PLAN-v2's "12 consent readers" counts differently; shell hooks through one entry point; measure the added latency). `do.status` through E8's one function on obligation.TERMINAL_VOCABULARY, with `pending` removed at the schema. | none | The readers' own consent semantics (pretool-aggregate-check.py:647, pretool-bash-safety.sh:907, :2748, :2790, pretool-block-background-tasks.py:153, pretool-block-branch-pr-worktree.py:589, pretool-block-enterworktree.sh:60, pretool-do-block-subagents.py:74, pretool-orchestrator-gate.py:77, pretool-read-size-guard.py:27, pretool-subagent-enforce.py:52, pretool-write-guard.sh:60, pretool-git-privilege-guard.py:274 and its fixed /tmp path, probe X11a); do.md:58's fallback marker writer; do.md:57's fixed /tmp sidecar path (prompt-workflow.py:1419 writes the sidecar under the state dir; Correction 4); the per-reader terminal sets of the do-report (stop-do-report-gate.py:59's `TERMINAL_STATUSES` (used at :101 and :104, restated in the docstring :23-26), close.md:414/:416/:491, dev-lifecycle.py's do track, :188); the /do Stop gate's `blocked` rewrite of the do-report (stop-do-report-gate.py `_rewrite_pending_to_blocked` :149-166, its call at :217 and the log field and message clause that report it, :221 and :225-226: a hook writing the agent's report, D8, and another producer of it, D24; it rewrites only `pending`, which E8 removes; Correction 8). |
| 10 | G10 /close (A56-A61) | Inspector reports: the three inspectors. Close report: close QA (close-report-append.py only as close QA's own tool). | G2 at each producer's stop; close QA's rule that only inspector findings proven new in this diff become its findings (close.md:677-699; A56) stays as a use, not a check, and the routing loop routes each such finding as this row routes one on a product file, not by close.md:680's dev-report claim or its orchestrator fallback. Every reader of the close verdict uses one classifier (hooks/lib/close-verdict.py) on the report's last line, verbatim. | none | The orchestrator's re-validation of the inspector reports (close.md:567) and close QA's finding on a missing or unreadable one (close.md:668; G2 verifies each inspector's report at its stop); pretool-gitignore-preflight.py's deliverable allowlist (:398-403) per E3; the routing tables (close.md:162-181, commit.md:99-116) with their prose copies and row references (E3) and the "no code table" claims (close.md:278, :288, commit.md:83-84): both routing loops (close.md:282-321, commit.md:144-178) take each finding's producer from E3's reader instead, and their entry keeps path, detail and source_check and loses producer_role (D21); at /commit Step 5's chain call the entries are the paths in the call's `errors[]`, one each, as /close Step 0 routes them (close.md:385-388), not the one entry on the selected report (commit.md:336); the loop dispatches again the dispatch the reader returns for the path (same subagent_type, task_id, lane and obligation template, a fresh dispatched_at), or, when the reader returns a canonical todo step, makes a fresh dispatch of that step's role under the same task id with the template's obligation, or, when the step names no role (the main agent's own, as /dev Step 11, which writes the canonical aggregate, is if E5 keeps (b)), runs that step itself under the same task id, and the loop goes on as after a dispatch: the cycle's own step completing the cycle on a gap (CC4), not a /close or /commit re-run of its own, which E5 and row 6 delete; if E5 keeps (a), a gap on the canonical aggregate (the call's `canonical_dev_report`) goes back to the hook through the write it runs on: the loop dispatches again the dispatch the reader returns for one lane dev report the call's `lanes[]` lists (which lane is a technical choice, replayed), whose report write runs the hook, and the main agent runs no aggregator; the main agent never runs /do's Step 5 (scripts/todo/do.py:14), which records the /do work of the main agent's own Steps 1-4: a gap on a /do task's do-report keeps the route close.md:414 gives it (dev dispatched again under the same task id to complete the /do work), which that sentence, its pointer to the orchestrator row gone (E3), states as the /do lite preflight's own step (that preflight runs only for a /do-origin task, close.md:412), not as a role the do-report's path maps to (acceptance 7); no /close or /commit orchestrator writes the do-report (D8, D2), and P4's Q7 decides how that completion is declared; the reader finds the dispatch also when the /dev ran in an earlier session (E3); a finding on a file no obligation declares (a product file a close-QA or commit-QA round names) goes to the dispatch that E6's kept producer records as the file's writer, and, where that record names no dispatch because a /do task's main agent wrote the file (/do dispatches nothing, E8), takes the route a gap on that task's do-report takes (dev dispatched again under the same task id, stated as the routing loop's own step for a /do-origin task, not as a role the file's path maps to); a finding that names no artifact, and one whose only path is a product file for which that record names no dispatch for any other reason (no dispatch of the task wrote it), go as E3 says (that round's own report; no default role); R15, arbitration and the waits stay for P4; /commit Step 3's own accepted-line list (commit.md:204-233, its "— FORCED" form included) and close.md's prose list (:782-787); score-update.sh's precondition re-read of the close report (close.md:845) and close-scoring-decide.py's own verdict reading (they call the classifier; P9 retires scoring); the close-force flag's reading branches (subagentstop-e2e-enforce.py:387-388, subagentstop-artifact-contract-enforce.py:365-373, :1215) and scripts/cleanup-close-force-sentinel.sh (read, never written); the human-operator transcript's parser, which nothing calls (scripts/dev-lifecycle.py `human_operator_transcript_path` :761-763, `parse_human_operator_transcript` :766-790 and the constants only it uses, :753-758; D17 reachability proof), and its name in close.md:1006 and commit.md:1019, which keep the transcript only as AC-L21's human record (A60: the --auto discovery, dev-lifecycle.py list-actionable, never opens it). |
| 11 | G11 /commit chain (A62-A70) | Manifest: the orchestrator (an orchestrator artifact). Commit grant: scripts/write-commit-grant.py. Attestation: pretool-commit-dispatch-attest.py. Commit-QA verdict and changelog status: per E11. Push-gate token: one writer that both of the base's writers call after their own commit (A68), the changelog-analyst under /commit (its Write, agents/changelog-analyst.md:1221, :1247, dispatch text commit.md:666; CP-3, agents/changelog-analyst.md:96-103, makes every token write of that file a Write) and the cleaner under /clean (an inline Python step through Bash, agents/cleaner.md:109-111, dispatched at commands/clean.md:512-518). That both become calls of one writer is forced: hooks/push.sh passes only a token whose commit is an ancestor of HEAD (:212-242), so without the cleaner's write a /clean commit that no /commit token precedes has no route to /push, which no ruling retires, and two writes are two producers. The writer is a script both run with the repository root, the branch and the commit, which resolves the path itself (row 12; for example scripts/write-push-gate-token.py beside write-commit-grant.py; technical choice, replayed in acceptance 9). Planning probe: the call with its repository-root argument only (`python3 ~/.claude/scripts/write-push-gate-token.py --repo-root "$(git rev-parse --show-toplevel)"`; the branch and commit arguments were not probed, and acceptance 9 replays the full call), run as the cleaner and as the changelog-analyst through all 20 PreToolUse hooks settings.json registers for Bash, exits 0 with no deny at d625284 and at master 2acc29b; it carries neither the token's content nor its path, CP-3's reason for the Write tool. Commit message: the changelog-analyst. | The grant mint's pipeline check (hooks/lib/commit_pipeline.py `verify_pipeline_dispatch`) for the manifest; the privilege guard for the grant, the attestation and the bulk-commit sentinel (spending a single-use grant deletes it: consumption; the sentinel's one rule is the guard's kind, origin and expiry test, pretool-git-privilege-guard.py `_has_bulk_commit_sentinel` :1338-1384, called at :1537; the Stop coordinator's cleanup phase, stop-workflow-coordinator.py:72 (settings.json:801 registers the coordinator, not stop-cleanup-allowlist.sh), reaps the sentinels whose expires_at has passed by its own parse, stop-cleanup-allowlist.sh:50-65, A65, and sweeps the grant pointers and locks the stopping session owns or that are at least 1800 seconds old, :286-314, A63: each reap takes the reading of that file's one decider in place of its own rule, or goes (the guard's for a sentinel, the PostToolUse finalizer's, hooks/posttool-allowlist-consume.py, for a grant pointer; the lock reap goes with the `.lck`, column Deleted), as row 14's sentinel reap takes allowlist.py's reader's verdict; technical choice, tested); push.sh for the token. | posttool-push-gate-token-verify.py's rule (the token's commit_sha is live HEAD at its repo_root and a commit object, :123-136) moves into the token's one writer with the analyst's pre-write HEAD and DO NOT rule 7 checks (agents/changelog-analyst.md:1225-1228), so it runs before the write (the producer side) and covers the cleaner's commits too (the hook's Write matcher never saw the cleaner's Bash write, A68); the hook, left with no Write of the token to match, becomes an exit-0 stub (D15), and its rename of a written token to `.rejected` (:84-96, called at :137; A68's third writer) goes with it. | The changelog-analyst's manifest check (agents/changelog-analyst.md:206); the gitignore preflight's own rule on the grant (its discriminator E5, A63: `has_live_commit_grant`, hooks/pretool-gitignore-preflight.py:669-698, called at :810, admits a dispatch whose prompt names a report listing a gitignored path when the prompt also names a live grant for that report's task, :692-697), a second decider of the grant, together with its read of the grant (under harness_state_dir(), :655-656, while the grant's writer uses /tmp): the guard stays the grant's one decider (goal 2), since its verdict needs a commit's target and a dispatched subagent's id (pretool-git-privilege-guard.py `_evaluate_commit` :1532, `_grant_provenance_refusal` :1480-1486), which the orchestrator's Agent dispatch does not carry; the dispatch the preflight's E5 admitted, /commit's changelog-analyst dispatch at Steps 6 and 7 (commit.md:483, :591), is admitted from its own obligation instead (profile `commit-landing` and the report's task id as its `task_id`, read through obligation.py as G1 reads it; P3 row 13's exemption for that profile, bound to the report's task as the preflight's E5 was, delivered early: say so in the PR; replayed in acceptance 9); the guard's `.use`/`.lck` rewrites of the grant and its rewrite of the attestation (spend by deletion instead; technical choice, replayed; whatever replaces the attestation's claim, hooks/lib/commit_pipeline.py `claim_attestation` :679-739, called at pretool-git-privilege-guard.py:1519, leaves the one subagent its dispatch started, and no other, able to commit every repository that dispatch's plan names, with the guard as its one decider, no second writer of it, no state file added and no check at /commit: that dispatch commits each `REPOSITORY_PLAN.repositories[]` entry in order with one grant per entry, commands/commit.md:434, :654, the guard admits the second through the claim the first made, hooks/lib/commit_pipeline.py:614-616, and an attestation deleted at the first commit refuses the second, a hook rejection that /commit turns into an AWAITING_INPUT line for a human, commit.md:846-849; replayed in your branch's kit, whose harness home is a checkout of your branch: a /commit after /close of a cycle whose dev wrote a path in the kit's toyproj and one in its harness home, so that Step 5's plan names both, commit.md:250-259, lands both commits with no block from the privilege guard, and another subagent's `git commit` on the second repository between them is refused; the base kit's harness home is a detached checkout, which that plan refuses, scripts/resolve-commit-repos.py:705-708), and with them each read of a `.use` record or a `.lck` grant, which nothing then writes (goal 2), among them write-commit-grant.py's revoke of `.lck` grants, with its revoke of the pointers that name one (:342-347, :296-330), and the PostToolUse finalizer's restore and lock reap (hooks/posttool-allowlist-consume.py :669-684, :410-457; a failed commit's next attempt takes a fresh grant from /commit's retry routes, commit.md:817-828, :843-844); the guard still writes its per-event pointer in the spending step (pretool-git-privilege-guard.py `_lock_grant_for_posttool` :709-802), recording in place of the grant's two paths the fields the journal entry takes from the grant (hooks/lib/commit_journal.py `append_commit_event` :395), never in a form a reader of grants takes for one (the guard's globs, pretool-git-privilege-guard.py:406, :1406, and the revoke's, write-commit-grant.py:346, also match the pointer's name), so that finalizer stays the one writer of the commit-event journal (A70; posttool-allowlist-consume.py `_finalize_deferred_commit_grant` :537, pointer read :590-627, append :659-665), on which the changelog-analyst's push-gate reconciliation decides before its token write (agents/changelog-analyst.md:1640-1652), measured after each acceptance-4 /commit replay: that reconciliation's query (:1644-1646) on each commit the replay landed exits 0 in your branch's kit wherever it does in the base kit; per E11, the losing channel of each verdict and /commit's cross-check (commit.md:579-583), re-parse (:673-681, :851-854) and the changelog-status* table row; /commit Step 5's optional `ls` of the bulk-commit sentinel (commit.md:248) and its AWAITING_INPUT route when the sentinel is absent (:249; A65), a second rule on the sentinel and a check at /commit (goals 2 and 3): the guard's verdict at the commit stays the only one, as Step 5's primary path already assumes (:248); step7-spec-update.py's re-checks of the close report, the changelog status and the token (it reads them verbatim or not at all); push.md's token re-check (:140-149); the token's own write steps, the changelog-analyst's Writes (each one CP-3 binds, agents/changelog-analyst.md:96-103) and the cleaner's inline step (agents/cleaner.md:111), which become calls of the one writer; the path mismatch of the token (row 12's path rule); the guard's quoted `-F` read (Correction 5). |
| 12 | G12 /push and /merge grants (A71-A75) | Each grant: its analyst. Chain-B sentinel: scripts/execute-push.py. Push grant: hooks/push.sh. | One validator per grant per E11 (execute-push.py for the push-analyst grant; the code validator or the producer-side check for the merge grant). | per E11's fallback, the merge grant's validation moves to the merge-analyst's own Write | The second validator of each grant (pretool-push-analyst-grant-guard.py's repeated field checks, or merge.md:127-166's prose validation and unlink); the fixed /tmp paths: execute-push.py:35, together with the push-analyst's grant path, its path rules and its write permission (Correction 4), and pretool-git-privilege-guard.py:328 (its block message :2093 with it) read and write under `harness_state_dir()` like hooks/push.sh:106, :212, :369 (probe X11b2), and the token's one writer (row 11) and its callers' prose (agents/changelog-analyst.md:1221, :1247; dispatch text commit.md:666; agents/cleaner.md:111) use the same rule; so does every other fixed state path acceptance 9's greps list on your base, writer and reader together, single-quoted readers and command and agent prose included (at d625284: the merge-analyst grant glob, guard :1968, with its writer's prose and write permission, agents/merge-analyst.md:164 and policies/tool-policy.v1.json:827, and merge.md:139 and :165, for the sides E11 keeps; the residual override, scripts/write-git-residual-override.py:39, with its reader, guard :2237; the /stop helper-auth read, scripts/break-overnight-lock.py:35, whose writer pretool-wrapper-userintent.py:74 already uses the state dir; the hero demo's grant install, scripts/capture-hero-run.py:52, whose non-disclosure scans, capture-hero-run.py:377 and verify-hero-provenance.py:242, and tools/demo/normalize-capture.py:42 match the `/claude-grants/` component instead of a /tmp literal; scripts/close-report-append.py:232 and its help text :731 if E12 keeps the markers, otherwise they go with their writer); comments and docstrings that name a moved path are reworded; the analysts' audit logs per E12. |
| 13 | G13 overnight (A76-A87) | State and cycle contract per E13. PM and specialist artifacts: their subagents. Plans: the scripts the orchestrator runs (replayed through acceptance 4's marked deviations where the base refuses them). Overnight log and summary: the orchestrator (read by the owner, E12). Git shims: scripts/overnight-git-env.sh. | pretool-subagent-enforce.py at dispatch (G1) and posttool-overnight-file-check.py at collection (G3) for the contract; G2 at each PM or specialist stop for their reports (their obligations name them). For the state, one conclusion (goal 2): one function in hooks/lib/overnight.py, the module that calls itself the single source of liveness (:3) and whose `is_overnight_active` (:95-109) pretool-block-branch-pr-worktree.py:662 and pretool-block-enterworktree.sh:41-42 already call, reads a record and returns its verdicts, each computed once, by the base's rule for it (the window: overnight.py `_state_file_is_live` :46-60; isolation held: pretool-overnight-hook-guard.py `_is_session_live` :392-407; released: `isolation_released_at` set, as the keystone tests it), with the fields its callers act on (for example protected_branch and worktree_path); every other deciding reader calls it in place of its own reading of the record and decides its own action from that return value alone (a use): stop-overnight-timelock.py (`load_state` :61-69, `parse_end_time` :72-87), prompt-workflow.py (`_is_active_state` :103-136), posttool-overnight-loop.py (`_check_end_time` :80-98), posttool-overnight-file-check.py (`_is_live` :97-106), pretool-orchestrator-prompt-purity.py (`_overnight_active` :218-233), pretool-overnight-hook-guard.py (its `is_overnight_active` :645-651, `_is_session_live` and `_get_protected_branches` :483-514), and the git keystone and the overnight git shim, which run it in place of their two copies of one shell scan (reference-transaction:161-182, git-policy-shim:246-267); /stop's read (break-overnight-lock.py:118) belongs to its write, which E13 routes through the launcher's write path. P2 row 7's one locator and UTC parser then change that function alone (delivered early: say so in the PR for P2; how the shell callers run it is a technical choice, replayed in E13's replay and in the launch's keystone selftest, create-overnight-state.sh:644). For the git shims, the one rule is scripts/overnight-git-env.sh's own check of what it installed (`_oge_provisioned` :52-55), made after its own repair (:57-70) in each of its runs, the launch's and each one the actor sources before a git op; it refuses to arm on a mismatch (:77-82), and the launcher (create-overnight-state.sh:609-613) and the actor's `&&` in worktree or fresh-clone mode (commands/dev-overnight.md:289) act on its exit status alone (A85). | The prose validations "Validate test plan / triage report / retro report" (dev-overnight.md:533, :802, :1638) and the specialist reports' "Sanity checks on each report" (:684-688) move into the PM and specialist obligations, checked by G2 at their producers' stops; Step 6's route on whether the triage report exists and is valid (:878-880) and the legacy fallback it leads to (:890-905) go, since the only way to the fallback is :802's failure (:809-811), which G2 now returns to the PM; the last sanity check, no overlap with the state's `addressed_issues` (:689), goes: under E13 only the launch sets that field, empty (create-overnight-state.sh:783), so it decides nothing. | Per E13, the extra state writers (/stop's fields stay, written through the launcher's write path), the seed, the orchestrator's contract write (dev-overnight.md:817-852, "Cycle Contract Manifest"; P2 row 15's deletion, delivered early), the mirror `.claude/overnight-contract-<sid>-cycle<N>.json`, the `cycle-current.json` symlink, contract_runtime's in-place mutation and its candidate paths beyond the working root (`_candidate_contract_paths` :79-98; it probes `~/docs/dev/overnight/...` and cycle-0 contracts on every Agent call outside overnight), and the v1 schema names (dev-overnight.md:836-840); posttool-subagent-track.py's second reading of the contract bookmark (:397) and its own existence and schema test of the matched entry's file (`_validate_artifact_for_entry` :341-355, called at :402; A19, A34), a second rule beside posttool-overnight-file-check.py's at the same PostToolUse; the artifact-status sidecar writer (posttool-overnight-file-check.py:316-330) if its reader (posttool-subagent-track.py:358-368, called at :403; A79) is gone; the continuation sentinel (stop-overnight-timelock.py:163-190); closeout's harness-report.json writer (hooks/lib/closeout.py:510-537); the idle and self-repair logs per E12 (notification-idle-overnight.py:144; pretool-overnight-hook-guard.py:317, whose write is part of that guard's fail-closed self-repair grant, reached only behind a cycle contract's enabled self_repair block, which no harness file writes (:80-90, :332-354; A48, A86), so E12's replay of the guard decides it); the QA verification plans the orchestrator writes at Step 14 and nothing reads (`qa-verification-plans.json`, dev-overnight.md:1357-1364) and the deadlock report no owner-facing output names (`docs/dev/overnight-deadlock-<ts>.md`, asked for at dev-overnight.md:117 and in the prompt-purity guard's remedy, pretool-orchestrator-prompt-purity.py:288-289), per E12; the overnight delivery marker stays: prompt-workflow.py:1039-1040 writes it and :1180-1182 reads it back to decide whether to re-send the continuation spec (a cache, so it has a consumer); scripts/check-overnight-reports.py's re-check where G2 now checks the same report; closeout's pending-required-calls block (hooks/lib/closeout.py `has_pending_required_calls` and its helpers, :404-470, which stop-overnight-timelock.py calls and blocks on, :100-129, :248-250; A19, A28, A34, A44, A80): before the end time the time-lock's own block gives the same exit (:257-258) and after it the result is unused (:249), so it stops nothing and only changes the message (landscape B2.e), while at a Stop it re-validates the subagents' reports (goal 3) by a second rule beside posttool-overnight-file-check.py's (goal 2), whose exit 2 (:366-367) and G2 at each producer's stop keep stopping their faults (say so in the PR for P2, row 9; E13's closeout block, B2.b, is the one after the end time, stop-overnight-timelock.py:251-254); the launcher's own executable test of the policy shim (create-overnight-state.sh:622-625), whose path is the helper's `$SHIM_DIR/git` (overnight-git-env.sh:116), a file the helper's check found executable before it exited 0 (:50, :54): a shim the helper cannot repair still stops the launch, through the helper's exit status (create-overnight-state.sh:609-613; A85); scripts/overnight-status.sh's default state directory (docs/dev/overnight, :6, :11), where nothing writes the state (the launcher writes `.claude`, create-overnight-state.sh:93, :704; A76): the script reads the state through the state's one function (this row's deciding consumer) and prints its window verdict, exiting non-zero once the window has closed, which is what the TIME CHECK that routes on it says it does (dev-overnight.md:1568; at d625284 it computes no time and exits 0); its other runs (dev-overnight.md:14, agents/pm.md:746) only show the state. |
| 14 | G14 grants, consent, intent (A88-A94) | /allow: hooks/userprompt-consent-allowlist.sh writes the structured sentinel only (probe X1: it writes both channels today), through one writer that scripts/capture-hero-run.py `install_grant` (:174-192) calls too: it writes the README demo's reserved-task sentinel in the same form, and CI runs it (baseline.yml:188, scripts/verify-claims.sh:227, verify-hero-provenance.py:109; A88), so two writes would be two producers; the writer resolves the path (row 12) and keeps the capture's exclusive create (for example a function beside the reader in hooks/lib/allowlist.py; technical choice, replayed: CI's hero rerun runs the capture's call), and the demo stays. User-intent flags: prompt-workflow.py. Restart grants: userprompt-restart-authorize.py. Tool streak counter (`claude-tool-streak-<sid>.json`, A90): one writer function, which hooks/pretool-orchestrator-gate.py's streak update and Agent reset (`update_streak` :125-159, :233-238) and hooks/prompt-workflow.py's turn reset at each UserPromptSubmit (`_clear_turn_state` :1999-2016, today a second code path that unlinks the file) call (technical choice, replayed: row 19's check shows one writer of the file, and the streak still starts again at each prompt and at each Agent dispatch, so acceptances 4 and 17 show no new block at the gate). | hooks/lib/allowlist.py's reader for every /allow consumer, the Stop coordinator's cleanup phase among them: its sentinel reap (stop-cleanup-allowlist.sh:39-45, hooks/lib/allowlist.py `reap_expired_sentinel_grants` :712-747) takes that reader's verdict on each sentinel in place of its own parse and test of expires_at (:717-740), which keeps some sentinels the reader rejects (`load_sentinel_grant_for_task` :405-431; for example one whose expires_at is missing) and raises on JSON that is not an object (:728); scripts/capture-hero-run.py, the demo's writer, checks the reserved sentinel it writes before the write (it refuses when one exists, :108-113) and after it (:236-237, :341-346, :354-355; exit 2 at :430-431), its own check at the producer, and compares the other sentinels' bytes and mtimes before and after the demo (:67-84, :292, :357-364), a check of the demo's isolation that interprets no grant (A88); each user-intent flag's one reader, which alone decides on it: pretool-wrapper-userintent.py for the stop flag (its `_GUARDED_WRAPPERS`, :66-71, holds only /stop's wrapper; it consumes the flag, :182) and write-commit-grant.py's mint check for the commit flag (`_sentinel_live` :443-473, called at :499; one of the mint's two preconditions, commit.md:419); one reader function in subagent_restart.py for the restart state. | none | The legacy flag `claude-bash-allowlist-<sid>.json` (its write at userprompt-consent-allowlist.sh:653-663, described in its header :21-24, and the reading branches: hooks/lib/allowlist.py:147, :216, :290, which `read_grant` and its siblings use, and their callers pretool-bash-safety.sh `check_and_consume_allowlist` :482-570 (the flag :498-499) with its call :1001-1008 and the variable that gates that call (`SENTINEL_EXISTS_FOR_TASK`, set at :924 and :976; the rest of the structured-sentinel check :924-984 stays), pretool-git-privilege-guard.py:295-298 (the structured-sentinel check :293-294 stays), pretool-block-branch-pr-worktree.py:614, pretool-block-enterworktree.sh:72, pretool-do-block-subagents.py:118, pretool-aggregate-check.py:658, pretool-orchestrator-gate.py:250, pretool-read-size-guard.py:73, pretool-subagent-enforce.py:326, pretool-write-guard.sh:137, posttool-allowlist-consume.py:785-788 and its unlinks of the flag after a sentinel consume (:847-861; the sentinel consumes :774, :803-843 and :869-919 stay), stop-cleanup-allowlist.sh:26-29 (the Stop coordinator's cleanup phase, stop-workflow-coordinator.py:72)); the push and merge intent flags, which prompt-workflow.py writes (:1925-1926) and no code reads (A89), at their producer (goal 2), with the text that claims a guard for them (the comments hooks/push.sh:25, hooks/merge.sh:40 and hooks/stop.sh:12; the module docstring's "mirrors the commit/push/merge sentinel-grant model", hooks/pretool-wrapper-userintent.py:10; commands/stop.md:8's "sentinel guard mirrors `/commit /push /merge`"; the wrapper's step 1 at commands/merge.md:200, "User-intent sentinel check"); the daemon-restart `-all` fallback (pretool-bash-safety.sh:613-620: no repository file writes `claude-allow-daemon-restart-all.flag`, and the documented external grant-helper protocol names per-target flags only, PUBLIC-CORE.md:109-112; the per-target flags, which the operator's helper writes, stay); the residual-override audit log (`audit.jsonl`, pretool-git-privilege-guard.py:2375, read by no code) per E12; its refusal journal (`refusals.jsonl`, :2269) stays, since the guard reads it back to decide whether an override may clear a refusal (`_digest_was_refused` :2281-2303, called at :2430; A93). |
| 15 | G15 logs, scores, capability, daemon state (A95-A103) | Score log: scripts/score-update.sh until P9 retires scoring. Each log or state file: its one writer function. Terminal receipt (`.claude/session-resources/<id>/terminal.json`, A103; finalize reads it, session_resources.py:1784, through the Stop coordinator's :328 and scripts/session-resources.py:86): publish_terminal_receipt, which needs the two trust keys. Its one call on a registered path, the time-lock's (stop-overnight-timelock.py:224, through publish_overnight_receipt; publish_workflow_receipt has no caller), runs as a coordinator phase, and no phase gets either key (stop-workflow-coordinator.py:108-111, :147-155), so it raises before the write (session_resources.py:335-336): writer and reader do not meet, and as row 12 does for the /stop helper-auth token (A92) they are made to meet. The coordinator, which holds the keys, either makes that call itself on the time-lock's terminal decision, handed in the structured line it reads from that phase (stop-workflow-coordinator.py:115-131), and the time-lock's own call goes, or hands both keys to that phase alone: the one with less code that passes acceptance 21 (technical choice); a replay that still fails is fixed at the receipt's producer and re-run. | none needed for logs read by nobody (E12); for the score log, until P9 retires scoring, one function that reads its lines (an unreadable file, or a malformed line before the last, refused), which scripts/score-update.sh (:295-319, exit 2) and scripts/score-inject.sh (:128-154, exit 1) call in place of their own parse, each keeping its exit code and its use of the lines (A95; technical choice, replayed; tests/score-inject-contract/test-inject-branches.sh's malformed ledger still gets exit 1 from score-inject.sh, and exit 2 when given to score-update.sh); for the handshake records, the handshake verdict that scripts/doctor --strict (through scripts/capability-doctor-strict.py:146, :158) and scripts/install/preflight act on (the capability gate, hooks/pretool-capability-gate.py, is not registered at d625284, nor is hooks/capability-canary.py, which alone appends the receipts the handshake waits for, so at d625284 every event fails missing_event_record before any transcript read (scripts/capability-handshake.py:207-219) and that verdict is never PASS: A100, A120); hooks/lib/session_resources.py's one conclusion for session resources (the Stop coordinator at stop-workflow-coordinator.py:264 and :328, pretool-tool-policy.py:173 and scripts/session-resources.py call it). | none | scripts/lifecycle-baseline-import.sh whole (its only work is the second write of the score log and its read of `agent-scores.json`, read, never written; no command, hook, agent or skill runs it: D17 reachability proof), with its allow rule (settings.json:40) and the one test case that runs it (tests/score-lifecycle-contract/test-lifecycle-cas.sh case (d), :147-185, and the lines naming the script, :3-4, :11, :23, :30; case (e) writes its baseline line by hand, runs only score-inject.sh and stays; row 20); every log no owner-facing output names (E12: guard and override audit logs, fswatch logs, and each checkpoint log no such output names: auto-commit.sh:51's notice names logs/checkpoint.log, and /checkpoint's own output, hooks/checkpoint.sh:54 and :81, names it and logs/checkpoint-push.log) at its writer; second writers of the fswatch state, capability records and watchdog pid files if the regenerated map confirms them (planning evidence for the fswatch state's writers is static only, A99; the planning map read the capability records' and the watchdog pid files' writers in code: scripts/capability-handshake.py writes the probe file and the handshake record and removes the probe file and the receipts (:55-64, :344, :388), which hooks/capability-canary.py appends (A100), and hooks/pretool-runcode-watchdog.py removes a previous call's pid files (:43-45) before it starts scripts/runcode-watchdog.py, which writes them (A102)); the two reads of hooks/fswatch-manager.sh that meet no writer, its status command's `git-fswatch-state-${USER}.txt` (fswatch-manager.sh:17, :161-163) and its logs command's `logs/git-fswatch.log` (fswatch-manager.sh:171-175), where the watcher writes `git-fswatch-state-${USER}-${REPO_NAME}.txt` (hooks/git-fswatch.sh:31, :91, :544) and `logs/git-fswatch-${REPO_NAME}.log` (git-fswatch.sh:27): each read is made to meet the watcher's name or is deleted with its branch (technical choice, replayed: whichever has less code and passes row 19's check on a replay that runs the watcher on a sandbox repository and then the manager's status and logs, the logs command under `timeout 5` since it ends in `tail -f` (fswatch-manager.sh:181-185), so it exits 124 once it reaches a log and 1 where it finds none (:173-176); Principle 6 keeps each manager command); a watcher file whose read goes is deleted at its writer (goal 2), and a watcher log the manager reads is not among E12's fswatch logs; hooks/start-fswatch-all.sh:60's removal of `git-fswatch-${USER}.lock`, a name nothing writes (the watcher clears its own stale lock, git-fswatch.sh:101-109). |
| 16 | G16 settings and landing (A104-A107) | Project settings: the CLI (the platform); the harness's one writer of `.claude/settings.json` is scripts/apply-permissions.sh (a merge that only adds entries, :25-32), which /dev, /dev-command and /dev-overnight all call with QA's validated permissions (how the list is passed is a technical choice); scripts/create-worktree.sh:108-138, which writes the overnight `Edit(<worktree>/**)` entry into `.claude/settings.local.json`, stays that file's one harness writer. Acceptance, in acceptance 4's traces (the replays run no permission prompts): apply-permissions.sh is the only harness writer of `.claude/settings.json`, and after /dev, /dev-command and /dev-overnight, each started in the kit's toyproj, which has no such file (tools/sb-setup.sh `make_toy`, tools/reset.sh:11), with at least one entry QA validated, the file holds each entry QA validated: a missing file is an empty object to the merge, so it creates the file when it has an entry to add (at d625284 apply-permissions.sh exits 1 there, :22), as scripts/install/installer.py:958-969 creates a missing target. Harness settings: scripts/install/render-settings (P7b's `land` calls the same function); scripts/bootstrap:272-280 writes the overlay with code of its own (O_EXCL :277), a second code path: it goes (column "Deleted"), and bootstrap seeds the overlay through render-settings. The config home's settings.json, which is not the harness home's where the coexistence installer runs (scripts/install/installer.py:8-13, :197-203): the CLI (the platform); the installer's additive merge of its hook groups (written at :1164, :1168; undone at uninstall, :1628-1651) stays that file's one harness writer, not a second code path under column "Deleted". Private-literal list and pre-commit hook: init's step, which the landing calls. Landing log (its file:line here are on master 2acc29b): scripts/install/land, which opens it for its own lines (`log()` :50, the init steps' output :245) and for render-settings' stderr (land :226); render-settings `cmd_land`, which only land runs (render-settings :1494), stops opening it (:1502-1504, master 2acc29b) and writes its lines to that stderr. Decided by planning experiment on master 2acc29b: with that change tests/test_landing.py passes 90 of 90 unchanged, and 126 of the 129 logs its landings write are identical to the base's (timestamps, revision ids and temporary paths aside); the other 3 come from the one test that runs `render-settings land` itself, outside land. render-settings cannot be the one writer instead: land logs steps no Python process runs (:208, :221, :52) and render-settings' own start-up errors (land :226). Replayed on your base: the same comparison, and the CI check derives land as the log's one writer (acceptance 13). | the CLI's permission engine (the platform); in the harness, one conclusion per file, as row 15's session resources have: render-settings' `load_overlay` and `load_record` for the overlay and the record, which check (doctor, CI), check --staged, render, clean and smudge already call (A105), and one load for every settings.json and settings.local.json a harness decider reads (the harness home's, the config home's, the project's two): the file's JSON object, with the shapes its readers rely on, or absent, or unusable with the reason, which render and check read settings.json through too, instead of their own `parse` of it (render-settings :736-737, :932). Map rows A104 and A105 list other harness deciders of these files, each with a rule of its own; each reads its file through that load and takes the load's verdict on a missing or unusable file (the mutations row 19 rule 4 measures, E1) instead of a test of its own (goal 2), and keeps what it does with what the file holds, so no feature goes: the /allow deny preflight (hooks/userprompt-consent-allowlist.sh:436-624; its match of a selector against the deny entries decides whether its hook writes a grant, row 14, and the CLI's verdict on the call stays final, :397-402), hooks/pretool-bash-safety.sh:355-368 (its commit block), scripts/bootstrap:332-353 (env.TMPDIR), the capability binding (hooks/lib/capability_state.py `settings_records` :231-249, `binding_matches` :328; its byte comparison stays its handshake record's freshness, row 15), scripts/check-file-references.sh and scripts/detect-orphan-scripts.sh (their verdict on whether another file is referenced), scripts/install/installer.py `plan_settings` (:951-995; its merge) and apply-permissions.sh's read of the file it merges into (:22, :25-31); the orchestrator's syntax check (commands/dev.md:1146, dev-command.md:743) goes with its jq edit (column "Deleted"). The claude_home probes (hooks/lib/claude_home.sh:38-42, claude_home.py:52-60) read no content, only whether settings.json exists (a walk with a name test reads by name, row 19 rule 3), and decide on it by route only: they pick the harness home every caller of claude_home.sh and claude_home.py resolves (claude_home.sh:73-110, claude_home.py:89-119), so E1's removal of the file changes their output (map A105), and their exit-2 blocks (`require_security_file` claude_home.sh:117-135, `resolve_required` claude_home.py:128-153) have no caller outside tests/. They take the load's verdict on a missing file in place of their own test, as the deciders above do, and keep their route; a file the load finds unusable still marks the home, as it does on the base. Where the load lives (render-settings, installer.py's `read_settings_document` :943-945 or hooks/lib, the others calling it) and how the shell deciders call it is a technical choice, replayed: it ships when the check derives one deciding rule per settings file on your branch (row 19 rule 4, no exception), every refusal these deciders give on the base for an unusable settings file is still given, with the load's reason (shown in both kits: by E1's differential where an acceptance-4 replay reaches the decider's read, else by running the decider directly with each settings file it reads made unparseable in turn, at the same size where the kit has the file: the /allow hook on an /allow that names a command, and pretool-bash-safety.sh's commit block on a `git commit` in the kit's harness home with the settings filter unregistered, both through runhook.py with its hook list from an intact copy; scripts/bootstrap, which runs render; scripts/doctor with and without --strict, for check and the capability binding; installer.py's plan command; and apply-permissions.sh, whose replays start without the file it merges into (column "One producer kept")), and acceptance 4 meets no new block; of the options that pass, the one with less code; a replay that fails is fixed at the decider or in the load it names, and re-run. | none | The orchestrator's jq edits of project settings from the QA report (dev.md:1081-1110, dev-command.md:678-707; D24, one writer): both steps call scripts/apply-permissions.sh instead, as dev-overnight.md:1518-1519 already does; no step only reports permissions (D19, D20, principle 6); P7b's `logs/landing.log` (its file:line here are on master 2acc29b) stays, with land its one writer (read by no code, render-settings :1208 on master 2acc29b; two writers on the base: scripts/install/land :50, :226, :245 and render-settings `cmd_land` :1503): the landing's notice names it (land :230, :239, :247, :249), so the owner is its consumer (E12), and `cmd_land`'s own open of it goes with `LANDING_LOG` (render-settings :1502-1504, :1208); any second code path that writes the overlay or init's git hooks outside the shared functions (for the overlay, scripts/bootstrap:272-280). |
| 17 | G17 doc-sync and session by-products (A108-A116) | doc-sync per E9 (update-only); under /clean, scripts/generate-folder-index.sh (the rule-inspector's Step 4, agents/rule-inspector.md:85-91, and the cleaner's generate_index action, agents/cleaner.md:77, :91) and scripts/generate-folder-readme.sh (the rule-inspector's Step 5, :93-98) write the same files: they and doc-sync write each file through one function or hand their text to it (technical choice, replayed: acceptance 9's /clean replay and the acceptance-4 pipelines); hooks/userprompt-doc-sync-check.py, which re-runs doc-sync at a prompt for a watched `.claude/` directory whose file list lost a name (:142-200), also unlinks INDEX.md from one whose list is left empty (:164-176): that removal goes through the same function (A108). Session scratch marker: session-scratch-init.sh. | the cleanliness-inspector, which /close dispatches, uses each folder's README.md rules for its naming and placement findings (agents/cleanliness-inspector.md:74, :82): a use, whose decision E9's replay of /close measures; /dev-overnight's PM reads the project root's README.md for the app URL and the test credentials when CLAUDE.md gives none (agents/pm.md:232-236, :290): a use, whose decisions (the URL it explores, or `app_not_running` and a plan from documents; the test credentials it puts in the plan, or `credentials_available: false`, :291-292) E9's replay of /dev-overnight measures; the specialists that /dev, /dev-command and /dev-overnight dispatch (dev.md:267-270, dev-command.md:202-205, dev-overnight.md:573) read that file beside CLAUDE.md for the app URL or the product description (agents/architect.md:203, ui-specialist.md:174, product-owner.md:204, user.md:171, :215); no other consumer in the ten pipelines reads INDEX.md or README.md by name. For the session scratch marker (`/var/tmp/claude-scratch/<sid>/.owner`, A111): one function reads it and decides, by the SessionEnd sweep's rule (the file exists and its `sid` field is the session's id), whether the session directory belongs to the session; the sweep (sessionend-scratch-sweep.sh:75-92, which deletes the directory only then) and doc-sync's notice (hooks/doc_sync/notice.py `state_path_for` :363-365, which keeps its dedupe state only then; today it tests only that the file exists) call it in place of their own tests and act on its return value alone, each a use (technical choice, replayed: the acceptance-4 pipelines). | /clean's clean-inspect test that agents/, scripts/, docs/, hooks/ and commands/ each hold both files (scripts/orchestrator.sh:204-213; its exit 1 at :215-224 only while the rule-inspector's context is also absent): if E1's measure finds it deciding, its rule moves to the rule-inspector's own stop; if not, it stays as a reader. | Per E9, doc-sync's creation of INDEX.md and README.md in product directories and docs/dev, and with it the hook-landed-files ledger and the aggregator's merge (row 6); /clean's writes of any INDEX.md the regenerated map shows with no reader, unless an owner-facing output names it (E12; commands/clean.md:73 names docs/INDEX.md); doc-sync's notice dedupe state stays: hooks/doc_sync/notice.py:511 writes `/var/tmp/claude-scratch/<sid>/doc-sync-notices-<audience>.json` (`main` or `agent-<hex>`) and :469-470 reads it back to decide whether that audience already saw the notice (a cache, so it has a consumer); the spec-update temp notes (`update-<rand>.md`, read by no code) per E12: /spec's Step 7 output prints the path of the note it writes (spec.md:473), so that note stays with the owner as its consumer; the notes /dev, /dev-command and /close write (dev.md:1365-1370, dev-command.md:902-905, close.md:896-902) go unless an owner-facing output names them (at d625284 none names their path); the `/spec-update --temp` mode itself stays (Principle 6); its mktemp-then-Write sequence (spec-update.md:115), which pretool-write-guard.sh refuses, is P1c row 18's, fixed on the side X4 picks; the `.claude/doc-sync.json` reading branch unless a command or doc creates that file; /clean's reads of `docs/clean/context-with-reports-<id>.json`, which no step creates (A116: Step 11's merge, commands/clean.md:333; Step 15's record-checkpoint, :482, which rewrites it in place, scripts/orchestrator.sh:381-389; Step 16's merge, clean.md:506-509): they read the files /clean writes (its Step 3 context, clean.md:121, and the inspector reports) or go, and record-checkpoint rewrites no file it reads (goal 1); /clean's reads of `docs/clean/combined-report-<id>.json` (Step 13's approvals, clean.md:404, Step 14's completeness gate, :454, and the cleaner's dispatch at Step 16, :521), which no step creates: Step 11 says clean-merge-reports writes it (:333-336), but the script writes `/tmp/combined-report-<epoch>.json` and returns that path (scripts/orchestrator.sh:287, :318, :326; A124): the merge writes the file /clean reads, or /clean reads the file the merge writes (A116), and the orchestrator's amendment of the merged JSON at Step 11 and its prompt_report rule (clean.md:338) go, since the merge already requires, carries and counts the prompt report (scripts/orchestrator.sh:281-284, :295, :300; goals 1 and 3) (technical choices for both files, replayed: acceptance 9's /clean replay reaches the cleaner's commit). |
| 18 | G18 probes nothing writes, tables, rosters (A117-A120, A124) | Roster: computed from the stems of the agents/*.md files that carry front matter (INDEX.md and README.md carry none), in one hooks/lib function (no literal list). obligation.ROLES and PIPELINES (obligation.py:74-83) go, and so do the role and pipeline enums of schemas/obligation.v1.json: parse_obligation validates role against the roster function and pipeline against the command files (commands/*.md with front matter). Whether a dispatch must carry a block (G1, pretool-obligation-gate.py:88-97, :143) and G2's expected_role (subagentstop-artifact-contract-enforce.py:873) are read from the active command's declaration (its dispatch template or canonical todo step for that role), never from a role list; the roster is not that set (graphify is dispatched without a block, commands/dev.md:763-775). obligation.PROFILES is read at import from the schema's profile enum, TERMINAL_VOCABULARY as row 6 says; no literal copy stays, and an unreadable schema is a fault of the gate that reads it, never an import error. | the one roster function; E3's reader for anything that maps an artifact to a role. For the CLI's transcripts and agent meta (A120), one reader in hooks/lib, which every harness decider on them that stays calls in place of its own parse, keeping what it does with what the reader returns; at d625284 these deciders include the gates and the restart path (subagent_restart.py `_read_parent_calls` :459, obligation.py `read_first_record_prompt` :654-691), G1 and the Stop coordinator (command_span.py `active_span` :43-57 and stop_contract.py `active_command` :84-99, both on `span_opener` :74-81), G3 (pretool-aggregate-check.py `_scan_transcript_for_prior_obligations` :409) and stop-spec-coverage-enforce.py (its tail scan, :112-157, until row 8 stubs the hook in Rollback's (7)). Which reader it is (command_span.py, with row 2's `calls()` and `last_todos()`, reads through it or is it) is a technical choice, replayed; it ships when the check derives one deciding rule on these files on your branch (row 19 rule 4, no exception) and each decider whose read no acceptance-4 replay reaches, run directly in both kits with each of these files it reads made unparseable in turn at the same size, on inputs where that changes its base decision (E1's differential), gives on your branch the decision the base gives, intact and mutated, and, with the file mutated but the one reader handed the intact copy, the intact decision (so no read of its own decides): at d625284 the restart path's `discover_candidates` and `authorize_send_message` (hooks/lib/subagent_restart.py:681, :1103), on acceptance 14's session-cut transcripts and agent meta (discovery maps an Agent call to its child only through that meta or an agent id in the call's result, :685, :690-691, so a cut call with neither is dropped at :764-765, before its child is read; if the replays write none, the run writes beside each child transcript the meta the CLI writes, `agent-<id>.meta.json` with its call's `toolUseId`, as the base's tests/test_restart_command.py:63-77 does), the cut child's transcript also with an end_turn record added; scripts/capability-handshake.py `cross_check_event` (:103-174, called only for a receipt a live host wrote, :207-221), on a recorded transcript with a receipt and probe made for it; and G2's and e2e's agent-meta read (hooks/lib/obligation.py `_read_meta_tool_use_id` :719-727) if the replays write no agent meta (the kit's model writes none, tools/baseline.py:48-51), on an acceptance-4 subagent transcript given the agent meta the CLI writes beside it. | none | The reading branch of `.claude/agent-bookmark-*.json` (posttool-overnight-trace.py:394; nothing writes it) and the uncalled `_find_grant_any` (pretool-git-privilege-guard.py:365-386, the generic `claude-*-grant-*-*.json` glob at :372; D17 reachability proof). Not deleted, because something writes each file (row 19 rule 1 covers each): `~/.config/claude/protected-runtime.json` (read at runtime_guard/config.py:63; init writes it, scripts/bootstrap:362-386, README.md:99), `.claude/.awesome-claude-harness` (read at session-gitignore-propagate.sh:22; tracked; P10 row 8 removes its gate), `.claude/.hook-refactor-allow` (read at pretool-claude-config-guard.py:77; the human's sentinel, which the guard's own text says the user creates by hand, :27, and its block messages :122-123 and :137-138 name that step; the config guard's policy, and P1c row 18 settles /dev-command's route under X4), `<proj>/.claude/CLAUDE.md` (read at session-info.sh:26; the user's project file, which the CLI loads). Deleted as well: the hand-written rosters (CP_AGENTS pretool-cp-checkin.py:62-84, ALLOWED_AGENTS spec-check.py:91-110, agent_types prompt-workflow.py:1514-1526, PRODUCER_ROLES pretool-obligation-gate.py:80-86, the roles in posttool-overnight-file-check.py:53-56, posttool-overnight-trace.py:50, subagentstop-codex-enforce.py:31, contract_runtime.py:1185, late-repair-controller.py:51, score-update.sh:258-265, QUESTION_ARTIFACT_ROLES subagentstop-artifact-contract-enforce.py:716: which dispatches may carry a producer question is read from their obligation templates, and the BA/dev route is unchanged, D23) and command lists (obligation.py:81-83, pretool-obligation-gate.py:88-90) that repeat a declaration; prompt-workflow.py:1925 (after row 14, commit and stop: the two flags with a deciding reader) and :1929 (dev, dev-command and redev: the commands that reach row 1's task-id mint at :1462-1480; /do reaches that mint at :1320-1360 by its own branch, :1927-1928) repeat none, since no declaration names either set, and stay (row 19 rule 7 flags neither); the tool-policy write prefixes that name files nothing writes or reads (A118: 94 families at d625284, 41 matching no other artifact) and, per E3, those that name declared artifacts or the file of any other artifact the CI check derives; /clean's orchestrator.sh outputs read only by their writer if the regenerated map confirms it. |
| 19 | The CI check and the trace runner (new, under tests/) | — | — | — | Not a deletion: a pytest module (for example tests/test_artifact_graph.py) and the runner and drivers it uses (for example tests/replay/), added to the baseline workflow as its own job with its setup steps (E2; the baseline job already runs 47-73 minutes per Python leg on master 2acc29b); the baseline job's pytest step (baseline.yml:112 there: hooks/tests and tests on python 3.10-3.12, pytest.ini's testpaths) leaves the check and its mutation tests (acceptance 3) to that job, which runs them all (an `--ignore` beside tests/generated's, not a skip). It derives the relations at test time (E1), asserts every invariant of goals 1-4 over every artifact it finds, prints each violation as facts (artifact, writers, deciding readers, position, file:line or trace event), and has no exception list. It opens no TSV and no file under harness-repair-plan/, and its source holds no list of artifact names, roles or hook names: it reads settings.json for hook positions (each from the hook's event and matcher) and their switches (E4), the call sites of row 7's one chain function, the obligation records, the command files' obligation templates and the canonical todo steps for declarations, agents/*.md for the roster, schemas/ for vocabularies, the command files, and the hooks with the scripts they run, for owner-facing outputs (E12). Its derivation rules, in its code and never as lists of names: (1) a file artifact is a regular file's path pattern, with the replay's own session ids, timestamps, lanes and task ids replaced by `<sid>`, `<ts>`, `<lane>` and `<task>`, taken by value from the replay (in every minted id that holds a timestamp only the timestamp is replaced and the rest of the id kept, never the whole id by `<task>`); a lock file or a same-run temporary folds into the file it serves; a file one process creates and removes within one run is its private scratch; a file tracked at replay start, a file of the user's project that the CLI itself loads (the platform, as in row 16) and a file the reading code's own text says the user creates by hand are inputs unless a trace event or a literal code site writes them; the static half parses every file under hooks/ and scripts/, with or without an extension (scripts/bootstrap included). (2) An artifact that is not a file (a response block or line, a script's stdout a later step uses, a vocabulary, the task-id rule) is found from what declares it: a response block or line by its obligation's begin and end markers, schema and terminal_line_regex, a vocabulary by its schema enum, the task-id rule by the ids the replays minted, a script's stdout by the script's invocation in the trace; its producer is the declaring obligation's role, the schema, the minting hook or the script; its readers are every code or extracted command-block site outside the producer side (the declaring obligation, the producer's own agent file) that holds the declared marker, schema id or enum set, or a regex or template matching a minted id, every caller of the function that parses it, and every step whose tool_result carries it in the replay transcripts; whether a reader decides is measured as in E1. (3) A reader reads content, and how it reads, never its name, leaves it out: a scan with a name test reads by name; a process that in one run reads every non-ignored file of a directory it listed (auto-commit.sh's `git add -A`) is not a reader of them; a hook whose reads in one run are exactly the triggering tool call's target paths reads a path only where E1's differential (content made schema-invalid, or unparseable by its reader where it has no schema, at the same size) changes its exit code or decision. (4) Two deciders decide the same property when both decisions change on the same mutation of the artifact (E1's differential); they are one rule only when each verdict is the same function's return value, used with no further test on the content (goal 2, row 7). (5) A deciding read's position comes from where it runs: a hook at an event of the artifact's own producer (its stop or its own tool call) is the producer side; a PreToolUse or PostToolUse hook on Agent is the orchestrator's dispatch or collection (G1, G3); a Stop hook deciding on what the stopping main agent did not write is goal 3's completion read (for this rule it wrote what its session writes outside every subagent's run, through its own tool calls, the session's hooks or the scripts these run, and the transcript its Stop payload names, but not a dispatched role's response block in it, rule 2) and may use only the one chain function's output and git; another decision there is measured as in rule 6: one whose mutation the producer side rejects only armed is that fault's only stop while its gate is advisory (E4) and passes, so the commit that arms the gate must delete it, and any other fails the check; elsewhere a call of that function, its output used verbatim, is goal 3's single call only where it is the one call per task in that command run at /dev's end (an overnight cycle's end included), /close or /commit (/close's is Step 0's, with `--late-repair` late-repair-controller.py init's, :218-219; /commit's is Step 5's, commit.md:334); row 10's routing loop running that same call again after the dispatch it made for the call's gap has stopped (or the main agent's own step it ran for it has ended) is still that one call, and in /close --auto and /commit --auto dev-lifecycle.py's discovery and the walked task's own step share it: the step uses the discovery's result verbatim, or the discovery selects the task without calling it, as /commit --auto's does at d625284 for the tasks it walks (dev-lifecycle.py:600-608, stage 3); technical choice, replayed; and a /close --late-repair whose init declines continues on the ordinary route with that call's result, used verbatim, instead of calling again (close.md:138 re-invokes the selector without the flag at d625284); technical choice, tested in tests/test_late_repair_route.py. (6) Re-checks (E1) are measured twice, with the gates as the tree's settings.json switches them and with them armed: a deciding read outside goal 3's positions whose decision changes on a mutation the producer side rejects with the tree's switches is a re-check and fails the check; one whose mutation the producer side rejects only armed is that fault's only stop while its gate is advisory (E4) and passes, so the commit that arms the gate must delete it; one whose mutation no gate rejects even armed is printed as a rule to move into the gate (E4) or as a use of the artifact, never exempted by name. (7) A list that repeats a declaration (D21, goal 4) is a literal in hooks/, scripts/ or an extracted command block (tests excluded), outside the declarations (agents/*.md, the command files' obligation templates, scripts/todo/<command>.py, schemas/), that maps a declared path to a role, names two or more roster entries, or copies a schema enum; a tool-policy allow prefix that names the file of an artifact the check derives is one too (E3). (8) Every replay it derives from sets CLAUDE_STATE_DIR to a directory other than /tmp. (9) The drivers take the Bash blocks and dispatch templates they run from commands/*.md and agents/*.md of the tree under test, at test time. (10) The static half's output is sorted, and a test asserts that two runs give byte-identical output. The runner and the ten compliant drivers are written so P1c can add faults to them. |
| 20 | tests | every test that pins code or prose you delete or change | — | — | A test that exercises only deleted code goes with it, named in the PR (D17); a pin a decided change makes false changes in the same commit to the decided behaviour (TC-54); P8's privacy gate pins lines too: policies/public-core-residue-allowlist.v1.json keys each allowed home-path literal by path, line fingerprint and ordinal, and scripts/check-public-core.sh (a baseline step, acceptance 18) fails on an entry whose file or line is gone and on a new literal no entry covers (:368, :398, :402 on master 2acc29b), so the commit that deletes or changes a pinned line (comments and docstrings in files your rows edit, for example five in hooks/pretool-cp-checkin.py and five in scripts/close-scoring-decide.py) drops its entry or re-pins it with the class the gate derives, and the runner and drivers take the kit's HOME (`/root` inside ns.sh) from the environment, or each such literal they hold gets an entry of class test_fixture with its rationale; no skip, xfail or collect_ignore. New tests: the declaring-dispatch reader, has_do_consent, the roster function, the path rule under CLAUDE_STATE_DIR, the guard's `-F` parsing, and the CI check's own mutation tests (acceptance 3). |

## Background (in the extracted planning documents, `harness-repair-plan/`, and in the repository)

- `audit/2026-10-23/`: `register.md` (the owner's words with sources; rows PC1-PC11, T0-T5, ON1-ON9, RD1-RD7, QP1-QP9,
  SG1-SG7, HC1-HC7, SF1-SF5, CC1-CC11, DT1-DT5, X1-X19), `ledger.md` (56 rows with the problem labels MP, MC, RD, DEAD,
  PROSE, TABLE, STATE, MISMATCH and the experiment E1), `corrections.md` (section 1.1 holds D20-D24 verbatim; section 3
  the corrected P2-P11 prompt text this phase takes items from), `report-zh.md` (the owner-facing summary).
- `inventory/README.md` and `inventory/artifact-map-d625284.tsv`: the d625284 map (planning evidence only, Step 1),
  with how each disagreement was settled and what the planning traces did not replay.
- `prompts/P1.md`: "Sandbox and arming" (how to arm G1-G3 in a sandbox copy only), the scenario-driver rules (T1
  order: the Agent tool_use is in the transcript before PreToolUse runs; queue-operation records; slash-command
  records; dispatch, subagent transcript, SubagentStop, tool_result), and acceptance 18 (live landing), which
  acceptance 17 here follows.
- `PLAN-v2.md` sections 3 (principles), 5 and 6 (phases, waves), 13 (carry-overs); `DECISIONS.md` (D2, D8, D15, D17,
  D18, D19, D20-D25).
- `tools/` (the kit) and `README.md` ("Sandbox").
- In the repository: docs/reference/close-commit-zero-failure-mechanism-20260928.md (section 0 rulings and C1-C5;
  section 1.1 state channels; section 1.2 the obligation grammar; section 1.3 the gates).

## Out of scope

- P1c's suite: fault injection as a CI test, the no-dead-end check, the replays of fixed process errors (P1's parallel
  wedge, the ledger's E1 (the v1/v2 contract conflict), the settings write that hung /pull, a repair refused under a
  held git lock with no notice), and the merge condition for later phases. You ship the runner and the compliant
  drivers; P1c builds on them.
- Arming G1 and G3 (P2; you arm G2 under E4) and the time-lock, window and landing route of /dev-overnight (P2),
  beyond row 13's state and contract producers, the state's one function that every deciding reader, the time-lock
  included, calls (its rules the base's; P2 row 7 changes them there) and overnight-status.sh's window verdict, and
  the terminal receipt's call (row 15).
- The disposition function's interface, facts-only gap lines and freshness (P3), beyond the declaring-dispatch reader
  and the single chain function of row 7.
- /close's and /commit's Step 0 as one disposition call, the retirement of the R15 measure and of arbitration, the
  waits as in-turn questions, and the native rating (P4); the re-dispatch of each gap's declaring dispatch keeps
  working through E3's reader from this phase on (row 10, D7).
- The unified Stop gate and its launcher, the protected-path denies of P5 rows 2 and 3 (row 1 only for what E3 leaves
  to it), /do <task-id> (P5).
- Role and identity from the CLI, the commit grant's binding (P6).
- The prose pass, CLAUDE.md, scoring retirement beyond row 15's second score-log writer, the git option table (P9).
  CLAUDE.md's Hook Discipline #5 ("honest terminal branch") conflicts with the owner's "诚实终态永远不允许" and is P9's
  rewrite under D20 and D23; do not touch CLAUDE.md.
- Stub removal and file-level dead code beyond the deletions your rows and E3 name (P10); history and remote refs (P11).

## Acceptance tests (run each, paste the command and its output in the PR)

Setup: the kit is in the extracted planning documents: `T="$SCRATCH/plan/harness-repair-plan/tools"`,
`export SB=$SCRATCH/sb-p1b`, `PYTHONDONTWRITEBYTECODE=1 "$T/sb-setup.sh" "$PWD"` from the repository root (re-run after
every code change); for every "on the base" comparison a second kit `SB=$SCRATCH/sb-base` from a scratch clone at your
base (`git clone "$PWD" "$SCRATCH/base"`, then a detached checkout there of the commit `git rev-parse origin/master`
prints in your checkout: in the clone, origin/master names your checkout's local master, not your base; not a worktree).
Every hook run goes through `"$T/ns.sh"` (or your E2 runner); never against your container's `~/.claude`. Arm only a
copy, as P1 "Sandbox and arming" shows.

1. **Base.** The "Before you start" checks, with their output.
2. **CI.** The baseline workflow's steps on Python 3.12 on your base and on your branch, plus the new check's job (E2,
   row 19): green on your branch, with its wall time, meaning both (a) and (b). (a) The pull_request run on your PR's
   head is green in every job, on GitHub's runners (a non-root user, full history). (b) Locally, every `run:` step of
   .github/workflows/baseline.yml, and the check's job, exits 0 (`python3` from a 3.12 venv in place of setup-python;
   your container's own python3.12 may refuse pip as externally managed); run the same steps on your base and show
   both. Where your container runs as root, one step is skipped there: "Clean-install smoke" (:83-109 at 2acc29b)
   exits 1 under uid 0 by design (:94-97 at 2acc29b), and an unprivileged user cannot reach PyPI through your session's
   proxy, whose certificate only root can read; its verdict is (a)'s. Run (b) with full history: if
   `git rev-parse --is-shallow-repository` prints `true`, first `git fetch --unshallow origin`, because "Verify headline
   claims" runs verify-claims.sh's provenance audit in --strict, which fails on a commit source the clone lacks
   (62957b3, cited by .github/assets/demo-trace.json at 2acc29b; hence the workflow's fetch-depth 0, :45-49 at 2acc29b).
   If that fetch fails, that step's verdict is (a)'s too; say so.
3. **The check fails when it should** (committed mutation tests that build a scratch copy of the tree and run the
   check on it): a second writer of an existing artifact; a reader of a path nothing writes; a write of a file nothing
   reads; a consumer outside the allowed positions that re-validates an artifact (for example a second resolver run
   added to a /close step, or a Stop hook re-validating a subagent's artifact); a hand-written filename-to-role mapping
   or role list in a hook; a consumer reading a state file under /tmp that its writer puts under CLAUDE_STATE_DIR; a
   second parser of a declared response block in a hook (for example the changelog-analyst's status block); a second
   task-id-to-name derivation in a script; a copy of a schema's terminal vocabulary in a hook; a script that runs the
   chain resolver and decides on its stdout fields instead of using its output verbatim. Each run exits non-zero and
   names the artifact, the components and the file:line or trace event. A mutation test reruns only what its mutation
   can change: the static half, and a traced replay of only the pipelines whose steps reach the mutated site (the
   unmutated run's trace stands for the others); E2's budget counts these runs. On your base (before your changes) the
   check fails, and its output is the "before" side of the D24 table.
4. **Ten compliant pipelines.** Your runner replays /spec, /dev (singular and 2-lane, with a QA-fail loop, a BA
   producer question, a BA-QA fail), /redev, /dev-command, /dev-overnight (two cycles of a 2-pipeline session, E13),
   /do, /close (after /dev, after /do, after /dev-command, with a routing round and a close-QA append round), /commit
   (after /close; and --auto), /merge and /push, in shipped settings and in sandbox-armed settings, in your branch's
   kit and, with the same drivers, in the base kit. A driver records every block it meets (hook, step and refusal text,
   run ids and timestamps aside) and passes a block only by a `DEVIATION:` step: the smallest step that produces the
   refused step's effect (for a refused tool call, the call applied as if allowed), marked in the driver source with a
   comment quoting the hook text, so every later step runs and is traced. A compliant replay of the base's text (each
   one in the base kit, and acceptance 17's in-flight replays in either kit) runs row 7's respellings and passes each
   block the base kit's replay of that text meets, so it reaches its terminal and the base kit records every block with
   its hook, step and refusal text. On your branch's own text a deviation passes only a kept base block: one the base
   kit records at the same hook and step with the same refusal text, on a line none of your rows or experiments changes.
   A base block on a line one of your rows or experiments changes (for example E8, E13, rows 3, 6 and 8) is removed
   there, not kept; its deviation fires only on the base's text, a no-op on your branch. A deviation lives in the driver
   only, and the CI check (row 19) reads none and keeps no exception. Expected on your branch: 0 hook errors (exit other
   than 0 or 2) in every compliant run, and no new block (any block that is not a kept base block). Print one table:
   pipeline, settings, hook events, hook runs, blocks (kept base / new), deviations, hook errors, wall time untraced and
   traced. A new block is either a driver that does not follow the command text (fix the driver and say so) or a defect
   you fix; never a hook change to suit a driver. List each kept base block, with its hook text and its DEVIATION, under
   "Hand-off to P1c" (P1c's rows 18-19 remove them), and apart from them each deviation that fires only on the base's
   text (P1c's base no longer shows its block, so it goes with no fix). In /close after /do, close QA's tool calls
   resolve the role `qa` (hooks/lib/agent_resolver.py `resolve_agent_type` :245-255 on their recorded payloads) on your
   branch as in the base kit's same replay, so the tool policy's qa row still limits its writes: on a /do task row 1
   deletes the only writer of the `qa.json` its FIRST ACTION line reads, and that line's registration
   (pretool-cp-checkin.py `_handle_dev_sentinel` :490-503) takes the path alone, so the line stays until P6 takes the
   role from the CLI (P6.md:413-416); the check reads that path as the pattern row 1's mint writes,
   `.claude/dev-registry/dev-<ts>/qa.json`, since row 19 rule 1 replaces only a minted id's timestamp.
   The runner, like the kit's `tool()` (tools/baseline.py:92-110), runs a call's PreToolUse before it performs the call,
   and records a call that fails as an error tool_result and goes on, where the kit's `do_read` (:117-122) raises: in
   /close after /do the inspectors' FIRST ACTION Reads (close.md:553-561) fail in both kits, close QA's on your branch.
5. **Faults (E4).** For every artifact family whose consumer-side check you deleted: missing, schema-invalid and stale
   artifact, in shipped and armed settings, on your base and your branch. Armed on your branch: every fault stopped at
   its allowed position, the message naming the artifact and the failing check, returned to its own producer, passing
   on the next round with no human action; a stale file at a path no dispatch of the cycle declares blocks nothing.
   Shipped, with your branch's settings.json: every fault a deleted check used to stop is still stopped, at an allowed
   position or by a copy E4 keeps, and returned to its own producer; name the stop of each, and list each kept copy
   with its gate for P2. For the spec views (row 8) the faults include a split that only `spec-verify.py --strict`
   rejects (two views whose overlap is above its threshold, which the base blocks only at the /spec orchestrator's
   Stop): armed on your branch G2 blocks the spec subagent's stop on it, and the orchestrator's Stop blocks nothing.
   G2 does so too with your branch's settings.json when the spec dispatch comes from the base's /spec text, which
   declares no obligation (a /spec in flight at your merge, D15; row 8; replayed in acceptance 17's in-flight form),
   and never on a compliant split of that text.
6. **D24 table** in PR comments of at most 60,000 UTF-8 bytes each, linked from the PR body (the body gives acceptance
   13's before and after counts and names, by artifact only, each artifact whose producers or deciding consumers
   change): artifact / producers before → after / deciding consumers before → after / proof (the writer and reader
   grep on your branch plus the trace events of acceptance 4), one row per artifact of your regenerated map, every row
   "after" = one producer, at least one consumer, one deciding rule. Coverage floor, compared once by hand for the PR
   and never in a test: every row of inventory/artifact-map-d625284.tsv whose writer or reader site still exists on your
   base (the code at the cited d625284 file:line, found again with line numbers ignored) is in the check's "before" map,
   or the PR names the row 19 rule or the code change that leaves it out.
7. **Declaring dispatch (E3).** The reader returns the producing dispatch (or the canonical todo step) for every gap of
   every replayed pipeline;
   `grep -niE 'artifact_role|mapping rows?|-row mapping|first match wins|no code,? table|maps to (dev|qa|ba)\b|\*. ?(->|→)' commands/close.md commands/commit.md`
   prints nothing (at d625284 it finds both tables, their callers, their prose copies and the "no code table" claims),
   neither file claims "no code table" or maps a file name to a role in any other words, and the tables named in E3
   and their prose copies are gone or reduced as E3 decided. Replayed on your branch in shipped and sandbox-armed
   settings, each with no human action, the first, third and fourth with the /close or /commit typed in a later
   session than the /dev's: a /close after a /dev cycle whose lane QA report was removed after /dev reached its
   terminal (the reader names that QA dispatch, /close dispatches it again, the report is written, /close lands
   `CLOSE: YES`); a /close after a cycle whose lane QA was never dispatched (the reader returns the canonical todo step;
   /close dispatches that role under the same task id); a /close whose close-QA round names a product file a lane's dev
   wrote (that dev's dispatch runs again and a fresh close-QA round lands `CLOSE: YES`); a /commit after a landed /close
   whose lane dev report was then removed (Step 5's one chain-function call, commit.md:334, names that report; the
   declaring dev dispatch runs again, the same call is re-run and the commit lands); a /close whose close-QA round
   raises a finding that cites no artifact (the reader returns that round's QA dispatch, which runs again and names it,
   and /close lands `CLOSE: YES`); a /close whose close-QA round names only a product file no dispatch of the task wrote
   (the loop's first dispatch is that round's QA dispatch, which the reader returns for the round's report, not a dev
   dispatch; it runs again and names a dev report of the cycle, whose declaring dev dispatch runs again, and a fresh
   close-QA round lands `CLOSE: YES`); a /close of a /do task whose do-report is not `completed` (dev is dispatched
   again under the same task id, as close.md:414 does, no orchestrator writes the do-report, and the replay meets no
   block or dead end the base kit does not show); and a /commit after a landed /close of a 2-lane cycle whose canonical
   aggregate was then removed (Step 5's call names it and row 10's loop reaches the producer E5 kept: under (a) one
   lane's dev dispatch runs again and its report write runs the hook, under (b) the reader returns /dev Step 11 and
   /commit's main agent runs it; the same call is re-run and the commit lands). Replayed the same way, a
   `/close --late-repair` of a singular /dev cycle whose ticket and context were removed after /dev reached its
   terminal, and a /commit of it: Step 0's selector prints init's outcome `initialized` (close.md:137-139), /close
   dispatches BA, dev and QA again under the same task id (close.md:141), no ticket, context, dev or QA report of
   the task carries a `retrospective_disclosure` block, finalize prints `finalized_pending_verification` with no
   drift, verify-disclosure prints `admitted` at its first call (row 6), /close lands `CLOSE: YES`, /commit Step 5's
   resolve-effective-report (commit.md:313-322) prints state `none` with no routing round, and the commit lands. Then,
   replayed to the same `CLOSE: YES`, a /commit after the task's QA report was removed, its driver stopping each Step 5
   loop after three rounds (a round: one routed finding and the re-run of its check): resolve-effective-report prints
   `none` again (row 6: no stage report is compared), Step 5's chain call (commit.md:334) names the QA report, the
   dispatch E3's reader returns for it runs again, the same call is re-run and the commit lands within those rounds;
   the base kit's same replay prints `invalid` at its first call (commit.md:313-315) and on each of the three rounds of
   commit.md:316-322, lands no commit, and its driver stops it (verify-disclosure refuses stage `qa`, and no stage is
   recorded twice, late-repair-controller.py:285-286): list it with acceptance 14's base dead ends under
   "Hand-off to P1c".
8. **Identity.** `git grep -niE 'session_ts|TASK_ID_REF_PATTERNS|DEV_SESSION_ID#|SESSION_ID="dev-\$\{TASK_ID\}"' -- hooks scripts commands ':!hooks/tests'`
   prints only subagentstop-e2e-enforce.py's qa-report resolution for a QA dispatch without an obligation, which P1c
   row 10 replaces (list those lines under "Hand-off to P1c"); every other task-id-to-name derivation in hooks/ and
   scripts/ is a call into obligation.py (list them).
9. **Path rule.** With CLAUDE_STATE_DIR set in the sandbox: a /do UserPromptSubmit then a main-agent `git commit`
   PreToolUse through the privilege guard and the other consent readers: each honours /do (the guard probes the state
   dir; on the base it probes /tmp, probe X11a); with CLAUDE_PUSH_COMMAND_ACTIVE=1 the guard reads the push grant from
   the state dir (on the base its message names /tmp, probe X11b2); push.sh finds the chain-B sentinel execute-push.py
   wrote and the push-gate token row 11's one writer wrote, after a /commit and, in a /clean then /push replay on a
   branch no earlier token covers, after the cleaner's commit (the privilege guard refuses that agent commit on the base
   too, `BLOCKED: agent git commit`: acceptance 4's marked deviation passes it, listed under "Hand-off to P1c"), so
   /push passes its token gate; in a /push replay, pretool-push-analyst-grant-guard.py and execute-push.py both find the
   grant the push-analyst wrote; the sidecar path in commands/do.md is the one prompt-workflow.py writes. In your
   branch's kit on your branch's text and on the base's (acceptance 17's in-flight form), and in the base kit on the
   base's text, each with CLAUDE_STATE_DIR set and unset: /commit's Step 6 and Step 7 changelog-analyst dispatches,
   built from that text's template, through the registered Agent PreToolUse hooks, each naming on a line of its own (as
   `commit_step7_prompt` in hooks/tests/test_gitignore_preflight_close_contract.py does for the preflight's E5) the dev
   report of its task, a singular cycle's, in the harness home (the gitignore preflight finds the report and runs
   `git check-ignore` from its own install location, pretool-gitignore-preflight.py:700-703) with no `gitignore_waiver`
   and a `files_created` path the harness's .gitignore matches (for example under tests/generated/), with and without a
   line naming a live grant for that task where the kit's write-commit-grant.py writes it: in your branch's kit the
   preflight exits 0 on every one, and `git grep -n claude-commit-grant -- hooks/pretool-gitignore-preflight.py` prints
   nothing on your branch (row 11: the guard is the grant's one decider); in the base kit it exits 0 only with the grant
   line and the variable unset, and 2 on the rest (`BLOCKED: gitignored deliverables detected`; with the variable set,
   the preflight's E5 looks in the state dir for a grant written under /tmp). The two greps
   `git grep -nE '(^|[^/[:alnum:]_.])/tmp/(claude-|agentic-commit|overnight-)' -- hooks scripts commands agents ':!hooks/tests' ':!scripts/install/tests'`
   and `git grep -nE "[\"']/tmp/?[\"']" -- hooks scripts ':!hooks/tests' ':!scripts/install/tests'` list only the
   state-dir helper's default (hooks/lib/harness_state_dir.py, harness_state_dir.sh) and the import fallbacks that copy
   it, comments and prose that only describe a path, and uses that are not hook state (scratch roots, the installer's
   cleanup rules, path checks); the PR gives each remaining line's category. Every hook state file's writer and reader,
   in code and in command and agent prose, resolve it under `harness_state_dir()`. At d625284 the two print 133 and 23
   lines, among them pretool-git-privilege-guard.py:274, :328 and :2093, pretool-bash-safety.sh:1722,
   scripts/execute-push.py:35, scripts/break-overnight-lock.py:35 (the /stop helper-auth read; its writer
   pretool-wrapper-userintent.py:74 uses the state dir), commands/do.md:57-58, commands/commit.md:666,
   agents/changelog-analyst.md:1221 and :1247, and agents/push-analyst.md:155. Three file families neither prints at
   d625284 are not hook state and keep their directories; the PR names each with that category: the per-target
   daemon-restart flags row 14 keeps, which the operator's helper outside the repository writes in the directory
   PUBLIC-CORE.md:94 documents for it (CLAUDE_DAEMON_RESTART_GRANT_DIR, default $TMPDIR) and pretool-bash-safety.sh
   reads through the same variable, else CLAUDE_TMPDIR, TMPDIR or /tmp (:9, :17), so moving that reader would part it
   from its writer; the git keystone grants, whose minter (scripts/mint-git-blessed-token.sh:39, :50) exports their
   directory with the token to the hook that reads them (hooks/git-keystone/reference-transaction:51), so both sides
   share it with or without CLAUDE_STATE_DIR; and, if row 18 leaves them, /clean's orchestrator.sh outputs, that
   script's scratch under a fixed /tmp (scripts/orchestrator.sh:25-27, :243-244, :287, :352, :381, :429).
10. **Dead artifacts gone.** For each written-never-read artifact your rows delete: no writer left (`git grep` of its
    name over hooks scripts commands agents prints only its removal's test, if any) and the acceptance-4 replays create
    no such file. For each read-never-written path: no reading branch left. Name each in the PR with its reachability
    proof.
11. **C1.** The path patterns of state and artifact files in your branch's acceptance-4 trace are, on the steps both
    trees reach, a subset of the base's (no new mutable state file); list in the PR each pattern from a step only your
    branch reaches (one the base kit does not reach, even past its blocks) with its writer on the base as file:line (a
    code site, the site that assembles the path at run time, the obligation template that declares it, or the command
    text its orchestrator follows; a pattern with none fails C1); list the files your branch no longer writes.
12. **C2.** `git diff --numstat origin/master -- commands/close.md commands/commit.md agents/changelog-analyst.md`:
    deletions exceed additions, and no added line is a check (a test, scan, filter, comparison, validation or
    re-derivation of an artifact); show each added line with its kind: a call of an existing function or of row 11's
    token writer, the reader's or the chain call's output used verbatim, a step of row 10's loop (a dispatch, or the
    main agent's own step), or a reworded path or commit line (row 12, Correction 5).
13. **C3.** Deciding checks outside the allowed positions: count on the base (from the check's "before" output) and 0
    on your branch apart from the copies E4 keeps until P2 arms their gate (each named with its gate); producers per
    artifact: the base's distribution and 1 everywhere on your branch; rules retired >= rules added.
14. **C4.** The planning fault scenarios replayed armed on your branch (a missing, a malformed, a stale report; a held
    `index.lock` during /commit; a session cut and /restart; a fan-out lane with a stale report), plus a /dev and a
    /dev-command whose hook output is no longer in the orchestrator's context (as after a compaction) and the same two
    after a hook that recorded no id for them, one of them in a session whose bookmark still holds an earlier /dev's id
    (the new cycle gets its own id from the hook's start function, never that one; row 1), each going on under one task
    id with no new user prompt and no human action, except the one /restart the human types after the session cut
    (human-only by design): your changes add no block a compliant producer cannot clear and no dead end; list every dead
    end that exists on the base too, for P1c, among them the late-repair one row 6 ends (once verify-disclosure refuses
    a stage's report, its producer's new one is never recorded, late-repair-controller.py:285-286; acceptance 7).
15. **C5.** For every blocking hook left at an allowed position, one replay shows its block message names the artifact
    path and the failing check and lands on the producing subagent's stop, or on the orchestrator's dispatch of that
    producer.
16. **E-blocks.** Each experiment's setup, raw counts or exit codes and option taken, E1-E14 (no trace files).
17. **Live landing** (owner, 2026-10-18: he cannot stop his sessions; D15). Copy origin/master's settings.json to
    `$SB/settings.base.json` and replay, in the sandbox built from your branch, with `--settings
    /mnt/sb/settings.base.json`: a compliant /dev Stop, an in-flight /dev cycle built from the base's command text
    (routing tables, the base's obligation templates, the base's dispatch prompts; its BA asks one producer question,
    and each subagent writes, as the base's agent text says, every file that only an allow prefix E3 deletes allowed it
    to write, BA's producer question among them), a /close and a /commit of it, the in-flight closes (a /do task and a
    /dev-command task, each run and closed from the base's command text: the base's /close binds both to `dev-<ts>`,
    close.md:582, a registry neither task's mint creates, so its QA arming finds no sentinel there), and a plain
    UserPromptSubmit. Expected: on every replayed event, no hook exits 2 or prints a block or deny decision that the
    same replay in the base kit does not show at the same hook, step and refusal text (acceptance 4; D15; D25). The
    in-flight cycle, its /close and its /commit, and the in-flight closes follow the base's command and agent text, so
    in your branch's kit too they are a replay of the base's text (acceptance 4): the drivers run row 7's respellings
    and pass each block the base kit's same replay meets. A new block is a driver that leaves the base's command text
    (fix the driver and say so) or a row you change until it no longer blocks; each block the base shows too is listed
    with its deviation as acceptance 4 says. Every hook file the base's settings register still exists (emptied ones are
    exit-0 stubs with the `# STUB:` line), and the cycle can still reach a commit and each in-flight close its terminal.
    So every harness script the base's command or agent text calls on a step this cycle, its /close, its /commit or an
    in-flight close reaches still answers that call as in the base kit's same replay (exiting 0 wherever that replay
    does), whatever your rows do to it: an option they delete (row 1's `--init-if-missing`, close.md:248) stays accepted
    and creates nothing, and where the sentinel it would have created is missing (the in-flight closes) the call exits 0
    with nothing written, never with the refusal of write-qa-mode.sh:73-74, which the base's arming rule repeats into
    its `no_progress` stop (close.md:263-267); a script they would delete (row 1's write-qa-mode.sh, if E7 removes the
    `qa_mode` switch) stays at its path and mode (the overnight calls run it by path, dev-overnight.md:1097), with any
    allow rule that names it, as an exit-0 stub with the `# STUB:` line until P10, as D15 keeps a hook file; its tests
    shrink to one case that runs the stub on each call the base's text makes; list each under "Live landing". Deleting
    it once its call sites are gone would not do: the cycle runs the base's text it took up before your merge, which no
    edit of your command files reaches, and no time is known after which no session runs it (the owner cannot stop his
    sessions); bash on a missing script exits 127, which that text turns into an abort (dev.md:609-610, :978-979;
    dev-command.md:437-438, :627-628) or, at /close, into the `no_progress` stop (close.md:263-267). Repeat with your
    branch's settings.json, and repeat both with a copy of the settings file whose env gains `"CLAUDE_HOME":
    "/root/.claude"` (the kit's harness home): a session started since P7b's landing has that key from the overlay, one
    started before has not (E4). Where E4 gives G2 its run-time switch read, also replay, with the base's settings.json
    with and without that key, the in-flight cycle's dev stopping with its report missing (a fault, outside the
    compliant expectation above): G2 blocks that stop, naming the report path and the failing check, and the dev's next
    round, with the report written, passes, since the harness home's settings.json is your branch's, which Rollback's
    (7) arms; a G2 left advisory there fails this item (in a running session it would leave unstopped the faults of the
    copies (7) deletes, E4).
18. **Personal values.** `scripts/check-public-core.sh` passes on your branch, and `git diff origin/master` adds no
    e-mail address, account name, private project name or personal home path.
19. **Full suite.** In acceptance 2's 3.12 venv (`python3 -m pip install --require-hashes -r requirements/py312.txt`
    in it; your container's default `python3` may be another version, with no lockfile and no pytest),
    `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider` -> 0 failed at every commit of the PR (TC-54);
    CI green.
20. **Net code.** `git diff --numstat origin/master -- hooks scripts schemas ':!hooks/tests' ':!scripts/install/tests'`:
    net lines (added minus deleted) <= -1200. Report tests/ (the check, the runner, the drivers) and commands/ plus
    agents/ separately.
21. **Terminal receipt (row 15).** In each kit, with both trust keys in the replay's environment (as runhook.py's
    `--env` sets it): `LANEB_SESSION_RESOURCE_TRUST_KEY`, 64 lowercase hex digits not all zero, and
    `LANEB_SESSION_RESOURCE_TRUST_ROOT`, an absolute directory outside the project made with mode 0700, as
    hooks/tests/test_laneb_stop_coordinator.py:38-45 does. Bind a resource session to an overnight session with
    `python3 ~/.claude/scripts/session-resources.py --project-dir /root/toyproj provision --binding-json '<binding>'`
    (the kit's toyproj, also the Stop payload's `cwd`; both keys in this call's environment too) and give that session
    its overnight state, as that test file's time-lock test does
    (`test_timelock_uses_exact_state_and_publishes_without_finalizing`, :244-269, :154-179 on master 2acc29b; the
    `dev-overnight` binding of :48-65), the binding's generation the one the receipt carries (the cycle plus one,
    session_resources.py:1478, :1488). Replay the session's Stop through the registered hooks with end_time in the
    future, then twice with it past and the closeout fields present. Expected on your branch: in the future, the
    time-lock's block, as in the base kit, with no terminal.json and the scratch intact; at the first past Stop, the
    coordinator exits 0 with `finalizer_called` true and status `pass`, the scratch is gone, terminal.json was written
    once, by row 15's one call, and read by finalize, and no phase but the time-lock received a key (no other phase's
    execve lists either key in its environment in a `strace -f -v -s 64` trace of this replay, strace installed as in
    E2; `-v` prints an execve's environment, not only its count of variables); at the second, the coordinator exits 0
    again, terminal.json is not written again, and finalize reads finalized.json (session_resources.py:2102-2108),
    which the first wrote (:2265), and returns `idempotent` true. The base kit's same replay blocks at both past Stops
    (at d625284 `resource_finalizer_contract_error`, exit 2, with no terminal.json: no agent action writes it, and
    /stop's helper writes only the state and the todo file, scripts/break-overnight-lock.py:127-129): list it with
    acceptance 14's base dead ends under "Hand-off to P1c". The check's traced replay (row 19) includes this replay's
    provision call and Stops (not the trust root, state and summary file the replay writes itself: fixtures, not harness
    writes), so the receipt's writer and readers come from its trace (E1), not from the static half's call at
    stop-overnight-timelock.py:224, and so does finalized.json's reader, the second past Stop's finalize, a read in a
    later run as with row 13's delivery marker: E1 adds no static reader (provision's, session_resources.py:1109) for
    a path a replay exercises.

## Rules added / retired (expected)

Added (at most 3, each replacing several):
- the CI check of D24 and the allowed positions (a test, not a runtime rule);
- one declaring-dispatch reader (replaces every filename-to-role table and, per E3, the per-role write prefixes that
  name declared artifacts);
- one path rule for hook state (`harness_state_dir()` on both sides of every state file).

Retired (at least 40): every item in the Deleted and Moves columns of Scope rows 1-18 that you deleted or moved, one
line each with its file:line on your base.

## Net code cap

Net lines in hooks/, scripts/ and schemas/ (tests excluded) must be <= -1200. Planning estimate on d625284 from the
map's deletions: about 2,300 lines removed (measured blocks: G2's escalation and journal-view code about 230,
find_unresolved_dispatch_obligations' re-validation and evaluate_required_values about 155, stop-obligation-gate.py
about 150 as a stub, the overnight loop's terminal lanes about 50, the aggregator's superseded read and singular merge
about 270, the hook-landed-files ledger about 640 if E9 deletes it, dev-lifecycle's cache and private rules about 50,
lifecycle-baseline-import.sh 146, write-qa-mode.sh about 90 as a stub if E7 removes the switch, the workflow-history and
continuation writers about 55, the advisory writers about 60, the legacy /allow channel about 90, the regex copies,
rosters and tables about 120, the close-route-select verdict layer and close-force readers about 110) against about 250
added (the reader, has_do_consent, the roster function, the path rule, the obligation-sourced schema check). The cap
leaves room for E9 and E7 going the other way. tests/ (the check, the runner, the ten drivers) is outside the cap;
report its size, and keep the drivers to what the ten pipelines need. commands/ and agents/ are outside the cap; report
their byte change (they should shrink). Effort: XL (about 7 days). No owner time.

## Technical choices you make (D10, D18: list each in the PR as choice / experiment or test / result / why / revert)

E1-E14 and their options; the static half's parser and its determinism (fixed ordering); the runner's isolation and
sharding (E2); the differential runs' mutation set; how the check reads hook positions from settings.json and
owner-facing outputs from the command files and the hooks' systemMessages; the declaring-dispatch reader's signature and
its canonical-todo fallback; has_do_consent's signature and the shell entry point, with the measured latency per Bash
call; the roster function's home; how overnight-init.sh reaches the one requirement and registry writer; how a
single-use grant is spent without a rewrite; which graph-cache writer stays; the stub text of every emptied hook or
script; anything else you decide. Follow the producer-side design doc, take the option with less code and fewer rules,
and back each with a test or a replay.

## Rollback

Commit order: (1) the path rule and the guard's `-F` parsing (small, behaviour-correcting); (2) dead outputs and dead
reading branches (rows 1-8, 10, 12-15, 17, 18: deletions only); (3) one producer per artifact (rows 1, 2, 4, 6,
8, 9, 11, 13, 14, 15, 16, 17, with E5-E10, E13, E14); (4) one deciding consumer and the consumer-side deletions whose
faults that commit's settings still stop (rows 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18; E4, E11); (5)
the declaring-dispatch reader and the table deletions (E3, rows 10, 18); (6) the CI check, the runner and the drivers
(row 19), which turn green only on top of (1)-(5); (7) last: `"CLAUDE_OBLIGATION_STOPGATE": "block"` in settings.json
env together with the deletions of the copies whose faults only armed G2 stops (E4), so they revert as one unit. A
commit after (7) (a review fix, a merge of origin/master) keeps the switch and E4's rule, and acceptances 4 (armed), 5
and 17 are re-run on the PR's head after it. Each commit keeps the suite green; (7) and (6) each revert on their own,
and a revert of any of (1)-(5) also reverts the later commits, last first, since the check fails on what that revert
restores; say in the PR what each revert restores. The reviewer reverts; the owner runs nothing.

## Branch and pull request

- Dependencies: start only after the pull requests titled `P8: …` and `P7b: …` are merged (see "Before you start");
  P1c follows you, and P2 and P3 start after P1c.
- Start your branch from the latest `origin/master`. If this session was assigned the planning-docs branch
  `claude/vibrant-hopper-bazrn8` or no branch, create `repair/P1b` from `origin/master` and use it. Push only to your
  branch. One branch, one pull request to `master`.
- Where the shared text below (from "## Context (read once)" on) differs, this bullet and the next govern. CI: the
  "CI" section dates from a red master; P8, merged before you start, made baseline CI green ("Before you start" checks
  that its latest run on origin/master is green). That section's allowance for pre-existing failures and the
  "Pull request" section's "keep CI no worse than master" therefore mean green: the baseline steps green on your
  branch, as acceptance 2 measures them, and CI green on every run of the PR, from E2's early draft on if you open one
  (acceptance 19).
  Planning documents: if you cannot fetch or read them, stop and tell the reviewer in your session output, never the
  owner (D18, D19).
- Commits: subject `P1b: <what changed>`, or `P1b (<item ids>): <what changed>` for a commit that answers review
  items; a body that says why and what you ran; last, exactly the attribution trailer lines your session's own
  attribution instructions give for commits (today `Co-Authored-By` and `Claude-Session`), unchanged, none added or
  dropped. They are not what the shared "Do not put model identifiers in commits or the PR" forbids (the reviewer's
  reading on P1's PR #5, COV-2, in the planning documents' reviews/P1-PR5-review-followup.md); everywhere else that
  rule holds.
- PR body: the shared format below. Its first line reads "Owner steps: none." Under "Notes for reviewers" add these
  headings: **D24 table** (acceptance 6: the counts and the changed artifacts by name, and links to the comments that
  hold every artifact of your regenerated map); **Inventory** (from the check's own derivation, before and after: the
  artifact count and each violation count of inventory/README.md's "Counts" table that the derivation yields; by name,
  the artifacts added to or missing from inventory/artifact-map-d625284.tsv or whose writers or deciding readers
  differ, line numbers ignored; links to the PR comments that hold both full maps); **Decided by experiment** (E1-E14:
  setup, raw counts or exit codes, option taken); **Corrections to PLAN-v2** (the list above, with what you did for
  each); **Faults** (acceptance 5: the stop of each fault a deleted check used to stop, and the copies E4 keeps for P2
  with their gates); **Hand-off to P1c** (the runner, the drivers, how to add a fault, the dead ends that exist on your
  base, each kept base block of acceptances 4, 9 and 17 with its hook text and its `DEVIATION:` step, apart from them
  each deviation that fires only on the base's text (acceptance 4), and the e2e gate's lines acceptance 8 leaves for P1c
  row 10); **Live landing** (acceptance 17); **Release notes** (the list under "Goal").
- The PR body and each PR comment stay under GitHub's limit of 65,536 characters: measure each in UTF-8 bytes (`wc -c`
  of the file you post; never fewer than its characters) before you post it, and keep it at or under 60,000. Every
  heading, those above and the shared format's, stays in the body with its summary (the counts and names the D24 table
  and Inventory headings ask for, one line per experiment with the option taken, one pass line per acceptance test).
  What does not fit in the body goes in PR comments, split as needed, never in the repository: both full maps, every
  artifact's D24 row with its proof, E1-E14's setups and raw counts or exit codes, and every other pasted output (each
  acceptance command and its output), with trace events quoted and no trace file. Once the PR is open, post those
  comments, then edit the body so each heading links its comments; a CI run's uploaded artifact may hold an extra copy,
  never the only one.
- After opening the PR, subscribe to its activity and drive it until it is merged: answer and fix every review comment,
  keep CI green, and merge `origin/master` into your branch (a merge commit) whenever master moves. Never merge or
  approve the PR yourself; the reviewer merges.

## DO NOT (this phase)

- Do not park a pipeline, add a parked state or a "parked questions" section, or let anything wait for the owner or ask
  him, inside or after the overnight window (D20).
- Do not add a table, list or map from file names to roles, in code or in prose, and do not add a role roster, an
  artifact-name list or a terminal vocabulary that repeats a declaration (D21). Read the dispatch record, the canonical
  todo step, the schema or agents/*.md.
- Do not write a continuation manual, an include the agent must follow to resume, or any instruction document that
  stands in for a hook (D21, HC2).
- Do not bind /redev to an earlier task or give it continuation semantics (D22).
- Do not add a mutable state file, a counter, a flag file or any release an agent can write (C1, ruling 3).
- Do not add a check, scan, filter or re-validation to /close, /commit, the changelog-analyst or any consumer (C2,
  ruling 1); a rule a consumer carried either already exists at an allowed position or moves there.
- Do not arm G1, G3 or any switch other than `CLAUDE_OBLIGATION_STOPGATE` in a tracked file (P2); set that one only in
  Rollback's commit (7), the last you plan, under E4's rule (a later commit keeps it), and arm everything else only in
  sandbox copies.
- Do not ask the owner anything, write a REQUEST for him, or give him a step on his machine (D18, D19).
- Do not commit or read from a test the d625284 map, any TSV, or a hand-written list of artifacts or relations; the
  check derives everything at test time and has no exception list or allowlist.
- Do not delete a registered hook file, or a harness script the base's command or agent text calls (acceptance 17);
  empty it to an exit-0 stub with a `# STUB:` line (D15).
- Do not edit CLAUDE.md (P9 rewrites Hook Discipline #5 under D20 and D23).
- Do not change a hook to suit a replay driver; fix the driver to follow the command text (the exceptions, both in
  driver code only: acceptance 4's marked `DEVIATION:` step past a block, which on your branch's own text must be a kept
  base block, and row 7's respellings wherever a replay runs the base's text).
- Do not run hooks, init, a render, doctor or the landing against your container's real `~/.claude`, HOME or global
  git config; only inside the sandbox namespace or a scratch HOME. Do not start a nested `claude`.
- Do not commit scenario captures or sandbox output; the drivers and the runner you commit are test code under tests/.
- Do not push from a test to a real remote; every origin is a local bare repository.

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
