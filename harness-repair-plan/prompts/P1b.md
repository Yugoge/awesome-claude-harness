Owner steps: none.

# Phase P1b: one producer, one consumer per artifact

You are implementing phase P1b of the harness repair plan in this repository (the GitHub repository this session
cloned). Phase id for the PR title: `P1b` (for example `P1b: one producer and one deciding consumer per artifact`).

**Wave 2b: you run alone.** Wave 1 (P0 with its follow-up P0b, then P7) and P1 are merged: master
d625284db59399568c50424ea3162175d982ae04 is the base this prompt was written against, and every file:line below
refers to it unless it says otherwise. Two phases must be merged before you start: P8 (private tree, one privacy
engine, hermetic green CI; its branch head was 0d26692201986f86533f45851bfe5b38af95a057 with green CI) and P7b
(zero-touch landing of P7 on a live home; re-implemented by the reviewing session, not in the repository when this
prompt was written). P1c follows you: it turns the owner's rule of 2026-10-24 into a CI replay suite and reuses the
trace runner and the ten compliant pipeline drivers you ship. P2 (run in any repo, overnight start and end, arm G1-G3)
and P3 (one disposition function, facts-only gaps) start only after P1c is merged. Do not wait for anything except
the two merges above; run independent experiments in parallel; never stop to ask.

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
- `git log --merges --format='%H %s%n%b' d625284..origin/master` must show the merges of pull requests titled `P8: …`
  and `P7b: …`.
- Their products must be there: `git cat-file -e origin/master:scripts/install/land` succeeds (P7b's landing fast
  path; if P7b merged it under another name, find it from P7b's PR body and say so); `git cat-file -e
  origin/master:scripts/dev-fix.py` and `git cat-file -e origin/master:scripts/spec-update-contract.py` fail (P8's dead
  code deletions); the latest baseline CI run on origin/master is green (P8).
- If a check fails, stop and tell the reviewer in your session output (never the owner) that P1b starts only after P8
  and P7b are merged. Do not start from an older base.
- Then `git log --oneline d625284..origin/master` tells you what else merged. Find every location below again on
  your base and say in the PR which base you measured against.

**Interfaces you consume.** Read each on your base (read-only) and use it as merged; do not build a second one.
- P1: `hooks/lib/obligation.py` (`parse_obligation`, `TASK_ID_RE`, `canonical_task_id`, `registry_dir_for`,
  `resolve_own_obligation`, `TERMINAL_VOCABULARY`; it reads dispatch records through
  `hooks/lib/subagent_restart.py` `_read_parent_calls`), `hooks/lib/command_span.py` (at d625284 it ships `active_span`
  and the Span's command, args and start line; the accessors `calls()` and `last_todos()` that prompts/P1.md describes
  were deferred to their first consumer, which is you if E7 needs them), `hooks/lib/stop_contract.py`, the
  producer-question artifact, the `# STUB:` marker, the D5 clearers at UserPromptSubmit.
- P8: the hermetic test fixture in conftest.py, green CI collecting every test file, the one privacy engine
  (`scripts/check-public-core.sh`), and its D17 deletions.
- P7b: the landing (`scripts/install/land`, `render-settings land`), the overlay `settings.machine.json`, the marker or
  record the landing keeps in the git directory (`claude-settings.applied` in the reviewing session's copy; an
  earlier planning note calls it a `claude-settings.checked` marker in the git common dir: use what merged),
  `logs/landing.log`, the seeded private-literal list and the installed pre-commit hook.
- The planning kit `harness-repair-plan/tools/` and the d625284 map `harness-repair-plan/inventory/` (read-only
  planning evidence; see Step 1).

**What you hand to P1c.** The trace runner and the drivers that replay all ten pipeline commands compliantly
(acceptance 4), in the repository under tests/, so P1c can add fault injection, the dead-end check and the replays of
fixed process errors without rebuilding them.

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
   (G1) and at collection (G3). Every re-check and re-derivation elsewhere goes: in /close and /commit, in scripts
   consumers run, in other hooks, in prose steps. G1 and G3 stay; P2 still arms G1-G3.
4. **No filename-to-role table (D21).** Where a role or an owner is needed, it is read from the dispatch record that
   declared the artifact (its obligation's `role` and `artifacts[].path`), or, for an artifact no dispatch has declared
   yet, from the command's canonical todo step (`scripts/todo/<command>.py`). Hand-written role rosters, artifact-name
   lists and terminal vocabularies that repeat a declaration go.
5. **A CI check that proves it every time.** A test derives the write/read relations at test time (from code, and from
   a sandbox runtime trace where E1 shows static derivation is not reliable enough), asserts the invariants of goals
   1-4 directly, never compares against a committed TSV or any hand-written list, and has zero exceptions and no
   allowlist when P1b ends.
6. **Live landing.** Merged into a live home whose sessions keep running, nothing blocks a compliant session or an
   in-flight cycle (acceptance 17).

Put these release notes in the PR (adjust them to what you actually did):
- /close and /commit no longer re-run the aggregator, the schema gates, their own accepted-line lists or the routing
  tables; when a cycle is incomplete they name the missing artifact and the dispatch that declared it.
- The task id is derived in one place; every hook and script that needs a registry name or an artifact name calls it.
- One path rule for hook state: /do consent, the push grant, the chain-B sentinel and the push-gate token are written
  and read in the same directory, also when CLAUDE_STATE_DIR is set.
- /allow writes one grant file.
- Files nothing reads are no longer written (each named in the PR, for example journal-view, aggregate-pending,
  workflow-history, the overnight continuation sentinel, harness-report.json, the escalation records).
- The producer-side gates G1-G3 stay advisory until P2 arms them; the PR lists, from experiment E4, which faults the
  deleted consumer-side checks used to stop in shipped settings and which gate stops them once armed.

## Owner decisions that govern this phase

D# are in DECISIONS.md. S# are planner clarifications in PLAN-v2.md section 0. They rank below quoted owner words and
DECISIONS.md D20-D24 (owner, 2026-10-23). S2 is superseded by D20; S1's extra exits and S9 carry no owner quote. The
2026-10-23 rulings below are quoted verbatim from audit/2026-10-23/corrections.md section 1.1 (source: the owner's
message of 2026-10-23T11:59:26Z, answering the reviewer's P2-P11 summary line by line).

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
  land only via /commit's changelog-analyst. The producer's stop, G1 and G3 are the allowed positions: they are not
  consumer-side checks and they stay.
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
- **The owner's rule of 2026-10-24** (relayed in this workflow's task; P1c's): "永远不能失败！每一次开发一定不会在流程上
  出现任何错误！出现了错误也可以立刻被修复！" ("It must never fail. No development run may hit any process error, and an
  error that does occur must be repairable at once.") The owner ranks it with "one producer, one consumer". P1c owns
  its CI suite; you must not make any compliant replay worse (acceptance 4, 5) and you hand P1c the runner.

**Decided technical choices.** None of PLAN-v2 section 9's rows is assigned to P1b. Where your work delivers a corrected
row early (TC-35 as corrected: one schema declaration for obligation-bearing overnight reports, E13; TC-20 as
corrected: write permission derived from dispatch records, E3), say so in the PR so the later phase does not redo it.

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
removed, or made schema-invalid, changes its exit code or its decision output; a deciding read is a re-check when the
artifact's own producer side (its producer stop, G1 or G3) already checks the property it decides on. Fallback, if the
differential runs exceed E2's time budget: run them only for readers outside the allowed positions, and treat every
remaining static branch to an exit or block on a read of the artifact as deciding.

**E2. How the runtime trace runs in CI.** Planning cost on d625284: one full replay of six pipelines 637.6 s untraced,
1034.9 s traced with `strace -f --seccomp-bpf` (x1.62; per hook run 99 ms to 161 ms); a second replay of seven
pipelines 451.4 s untraced, 632.6 s traced (x1.40); plain ptrace strace without `--seccomp-bpf` x3.1 on the first 76
events; analysis 17.6 s to about 50 s of CPU; raw strace 57 MB (3.6 MB gzipped) per replay. The kit isolates with
`unshare --mount` as root; CI runs as a non-root user with passwordless sudo on ubuntu-latest. Candidates:
(a) `strace -f --seccomp-bpf` inside `sudo unshare --mount` with the kit's layout; (b) the same without a namespace,
with HOME, CLAUDE_CONFIG_DIR and CLAUDE_STATE_DIR pointed at a scratch directory (the hermetic fixture's convention);
(c) Python audit hooks (`sys.addaudithook`) plus a shell wrapper, if strace is unavailable. Experiment: in a CI job on
your branch, run `strace -V` and a two-pipeline traced replay under (a) and (b); record wall time, the relations each
yields, and every path either variant writes outside its scratch root. Decision rule: take (a) if strace has
`--seccomp-bpf` there and the full traced replay of all ten pipelines fits 25 minutes wall per CI job (shard by
pipeline with a matrix if one job does not); take (b) only if (a) cannot run and (b) writes nothing outside its
scratch root; take (c) only if strace cannot run at all, and only if on the same replay it recovers at least 99% of
(a)'s relations measured locally. Fallback: if no variant fits the budget, the trace job runs on every PR in a
separate workflow job that the PR must pass (still per PR, never nightly-only).

**E3. The declaring dispatch replaces every filename-to-role table.** The D21 mechanism is INFERRED in corrections.md.
Tables at d625284 (inventory rows A59, A118, A119 and the hand-written-table column): commands/close.md:162-181 and
commands/commit.md:99-116 (filename to role; their changelog-status* row matches no file); scripts/late-repair-
controller.py:82-88 (stage to basenames); hooks/subagentstop-artifact-contract-enforce.py:119-122 (role to report
prefix); hooks/posttool-overnight-trace.py:256-269 (per-role required fields); scripts/spec-verify/
spec_verify_gated.py:244-249 (view file to role); hooks/pretool-gitignore-preflight.py:398-403 (deliverable prefixes);
policies/tool-policy.v1.json from :14 (24 roles, 261 write prefixes; 94 prefix families name files nothing writes or
reads, 41 of which match no other artifact in the map). Experiment: write one reader in hooks/lib/obligation.py,
"declaring dispatch for an artifact path" (task_id, lane, role, the whole obligation), built on `_read_parent_calls`
(hooks/lib/subagent_restart.py, already used by obligation.py :755 and :958); for an artifact no dispatch has declared
yet, it returns the canonical todo step from `scripts/todo/<command>.py`. At d625284 scripts/todo/ has no commit.py,
merge.py or push.py, the /merge and /push dispatches carry no obligation, and obligation.ROLES and PIPELINES
(obligation.py:74-83) name neither command nor the push-, merge- and pull-analysts: those analysts' artifacts get no
answer from either source and take the fallback below (which then extends both sets). In the sandbox, for every artifact
kind of every replayed pipeline, remove the artifact (and separately make it schema-invalid) after its producer ran, and
ask the reader for the owing dispatch; compare with the producer the replay actually dispatched. Then replay the D8
write permission derived from the session's dispatch records ("a subagent may write the paths its own obligation
declares; any other caller writing a declared path is denied; undeclared paths keep the policy rows") against the table,
in the same replays. Decision rule: if the reader names the producing dispatch (or the canonical todo step) for 100% of
cases, every table above is deleted and its callers read the reader; if the derived write permission denies 0 compliant
writes and allows 0 writes of a path another agent's obligation declares, the per-role write prefixes that name declared
artifacts go (prefixes for undeclared paths stay until P5). Fallback: an artifact kind for which the reader names
nothing is declared in its producer's dispatch template (its obligation gains the path), never in a table; then re-run.

**E4. Deleting consumer-side checks while G1-G3 are still advisory.** P2 arms G1-G3; you delete the consumer-side
re-checks now (owner ruling 1 makes every class-b/c check at /close and /commit a defect). Planning fault pilot on
d625284 (shipped settings, where G1-G4 are advisory in code): a missing or malformed dev report is blocked by no hook;
only the dev.md Step 12 prose and the Step 17 resolver run by prose catch it; armed G2 names the exact path and the
failing check, sends it back to the producer, and the next round passes with zero human action. Experiment: on your
base and on your branch, replay three faults per artifact family whose consumer-side check you delete (artifact
missing at its producer's stop, artifact schema-invalid, a stale earlier-version artifact beside the new one), in
shipped settings and in sandbox-armed settings (P1's "Sandbox and arming": CLAUDE_OBLIGATION_GATE, _STOPGATE and
_BARRIER = block, G4 untouched). Decision rule: armed, every fault must be stopped at an allowed position, naming the
artifact and the failing check, returned to its own producer, and pass on the next round; any fault that escapes armed
on your branch means the deleted check carried a rule the allowed position lacks: move that rule into the gate at the
allowed position (G2 for the artifact's own properties, G1 for dispatch preconditions, G3 for prior stages), then
delete the consumer copy. Shipped, list every fault that a deleted check used to stop and that now only an advisory
record notes, with the gate that stops it once P2 arms; this list goes in the PR and into P2's hand-off. Fallback:
for a family no replay can reach, move the deleted check's rule into the allowed-position gate unconditionally, cover
it with a unit test on a recorded payload, and list it; never keep a consumer-side copy.

**E5. One producer for the canonical fan-out aggregate.** Producers at d625284: scripts/aggregate-dev-report.py run by
the orchestrator at /dev Step 11 (commands/dev.md:885, the "MUST write" block :898-923), at /close Step 0
(close.md:334-343) and at /commit row 1 (commit.md:105), and by hooks/posttool-lane-completeness-watch.py:216-220
itself. /close and /commit re-running a producer goes regardless (ruling 1). Candidates for the one producer: (a) the
lane-completeness hook when the last lane report lands; (b) the orchestrator's Step 11. Experiment: replay a 2-lane
and a 3-lane /dev and the 2-pipeline overnight cycle (once E13 lets it run) with only (a), then with only (b). Decision
rule: take (a) if the canonical exists and validates before every QA dispatch in every replay with 0 orchestrator
aggregation calls (it is a hook, D8 and HC2); otherwise (b), and the hook's aggregator call goes. Either way G3
(pretool-aggregate-check.py) stays the collection check and the other producer goes.

**E6. One producer for "which files this dev wrote" and for the baseline.** Producers at d625284: the write-time
attribution journal (hooks/pretool-attribution-pre.py and posttool-attribution-post.py through
hooks/lib/attribution_journal.py) and the dev's self-reported `owned_edits` / `pre_edit_snapshots` (agents/dev.md:555-
592), unioned by the aggregator; the baseline head and dirty snapshot are captured by orchestrator Bash before dispatch
(commands/dev.md:826-835) and copied verbatim by dev (agents/dev.md:539-543). Experiment: over every replayed dev
(singular, 2-lane, a dev that edits a file another hook regenerates), compare the journal's file set, the self-report,
and the transcript's Write/Edit set of that dev. Decision rule: keep the producer that is hook-written and equals the
transcript set in every replay (HC2: never the agent's self-report); the other producer and every consumer rule that
compares the two go (the G2 wire `_wire_ledger_judgment`, the aggregator union, attribution_adjudicator's comparison,
verify-attribution-chain at /commit Step 5 if it only re-checks). For the baseline: the value lives in one record (the
dispatch prompt's obligation, checked at G1) and no agent copies it; take this if G1 validates it in every replay,
else keep the orchestrator's capture as the producer and delete the agent copy and the aggregate's equality check.
Fallback: if no producer equals the transcript set, keep the journal and record each difference in the PR for P6
(role and identity from the CLI).

**E7. Mutable switch and copy files replaced by records.** At d625284: `qa.json`'s `qa_mode` is flipped by the
orchestrator through scripts/write-qa-mode.sh between dispatches (commands/dev.md:606-611, :975-980) and read by G2
(subagentstop-artifact-contract-enforce.py:1218-1221); the workflow bookmark `.claude/workflow-<sid>.json` has 5-7
writers that mutate `subagent_calls`,
`last_todos`, `todo_acknowledged`; the canonical todo file is written by three hooks, a script and the CLI. The
records already exist: each QA dispatch's obligation names the artifact it owes (ba-qa-report or qa-report), and the
transcript holds every TodoWrite and Agent call (command_span reads them). Experiment: switch each reader to the
record (G2 classifies BA-validation from the obligation's declared artifact; the todo and bookmark readers take
command_span's `calls()` and `last_todos()`, which you add) and replay every pipeline. Decision rule: a field whose readers give
identical decisions on every replay event (0 differences) loses its file write; the file goes when no field is left.
Fallback: a field with a difference keeps exactly one writer (the UserPromptSubmit hook for bookmark fields), and the
other writers go.

**E8. One producer for the /do report.** At d625284 prompt-workflow.py:1363-1397 writes a pending skeleton and the /do
main agent rewrites it (commands/do.md:46-60); the planning trace found that do.md's Step 5 template drops the
skeleton's `expected_absent` field, so a template Write makes the e2e gate block the close QA. Candidates: (a) the main
agent writes the whole report (no skeleton); (b) the hook writes it and the agent edits only its result fields.
Experiment: replay /do then /close of the do-report with each. Decision rule: take the candidate with 0 blocks in the
compliant replay and a single writer in the trace; prefer (a) on a tie (fewer state files). Every reader then decides
`do.status` through one function on obligation.TERMINAL_VOCABULARY (stop-do-report-gate.py, /close preflight,
resolve-commit-repos.py, dev-lifecycle.py, the e2e gate). Fallback: if neither passes, the main agent writes the whole
report and the e2e gate reads `expected_absent` from the /do dispatch record instead of from the report.

**E9. doc-sync's writes into product directories.** At d625284 hooks/posttool-doc-sync.py creates INDEX.md and
README.md in every product directory an agent writes to; nothing reads them by name (they are opened only by
directory listings), they stay untracked after a compliant /commit (planning trace: 57 files of the cycle left,
docs/dev and toy/ index files among them), /dev-command's spec auto-detect picks docs/dev/specs/INDEX.md, and they are
why doc-sync keeps the hook-landed-files ledger that the aggregator merges into a singular dev report at /close
(aggregate-dev-report.py `_merge_hook_ledger_into_singular` :1321-1505, called at :3738-3740). Experiment: make doc-sync
update-only (it updates an existing marked file, creates none, skips docs/dev/) and replay every pipeline. Decision
rule: if no consumer's decision changes and no INDEX.md or README.md appears in the product repository, delete the
creation paths, the hook-landed-files ledger (hooks/doc_sync/hook_ledger.py, ledger_contract.py) and the aggregator's
merge; if a consumer decision changes, give that consumer its input from its own producer and keep creation off.
Fallback: if a consumer can only work from a generated index, it lists the directory itself; doc-sync still creates
nothing in a product directory (P9 row 2 then has nothing left to do for doc-sync creation).

**E10. Context without in-place patches.** At d625284 the BA context (docs/dev/context-<ts>[-<lane>].json) is written
by BA and patched in place by the orchestrator (`spec_path`, commands/dev.md:540-584; `attempts[].target_layer`,
:1163-1166) and by scripts/graphify-enrich.py (:413-491, also when it reports skipped); the graphify outputs
graph-summary.json, focused-subgraph.json and graph-report.md have no reader. Experiment: BA records `spec_path` from
its dispatch line ("Spec file:", dev.md:472) and the layer attempt from its own analysis; graphify writes only its own
output, which BA's and QA's dispatches name as input (or no file at all); replay /dev with graphify unavailable and
with a stub graphify binary that returns a fixed graph. Decision rule: if G2 validates every context and QA's graphify
gates (agents/qa.md:104-112) give the same verdicts in both replays, the orchestrator patches and the in-place patch go,
and each graphify output either gains its reader or is no longer written. Fallback: keep graphify-enrich as a
producer of its own file only; never of the context.

**E11. One channel and one validator per verdict or grant.** At d625284: commit QA writes a file and a response line
for one verdict, and /commit cross-checks them (commit.md:579-583); the changelog-analyst status block is validated by
G2 and re-parsed by /commit (commit.md:851-853) and step7-spec-update.py; the merge-analyst grant is validated and
unlinked both by /merge Step 3 prose (merge.md:127-166) and by the privilege guard (`_enforce_merge_grant`, reachable
only when CLAUDE_MERGE_COMMAND_ACTIVE=1 is in the hook's environment, UNVERIFIED); the push-analyst grant is validated
by execute-push.py and again by pretool-push-analyst-grant-guard.py. Experiment: replay /commit, /merge and /push with
each candidate single channel or single validator, and run the guard's merge path once with the variable set as
merge.sh sets it. Decision rule: keep the channel or validator that sits at the producer side (G2 at the producer's
stop for a verdict; the code validator for a grant) and is reached in the compliant replay; delete the other, and the
consumer reads the kept one verbatim. Fallback: if the guard's merge path is unreachable, the grant's validation moves
to the merge-analyst's own Write (a PostToolUse check on the producer's tool call), and the prose validation goes.

**E12. Which outputs the owner reads.** Written-never-read logs and reports at d625284 include the seven advisory
JSONL logs, the guard and override audit logs, checkpoint logs, analyst audit logs, the overnight idle and self-repair
logs and P7b's logs/landing.log; the overnight log and summary, the close report and the completion report are
read by people. Decision rule fixed now: a file counts as read by the owner only if a command's own output tells him
its path (the command text prints or links it, as dev-overnight.md's final summary does); the CI check derives this
from the command files at test time. Experiment: list each written-never-read file and grep the commands for the
output that names it. Every file no command output names is deleted at its producer (for the advisory logs: the gate
writes nothing in advisory mode until P2 arms it); every file a command names stays, with the owner as its consumer.
Fallback: a file a command mentions without printing or linking it to the owner counts as not read and is deleted;
the PR lists each such file with its hunk, so the reviewer can restore one by reverting that hunk.

**E13. One producer for the overnight state and the cycle contract.** At d625284 the overnight state
`.claude/overnight-state-<sid>.json` has four writers (create-overnight-state.sh, posttool-overnight-loop.py:101-153,
update-overnight-state.sh:271, break-overnight-lock.py:96); the cycle contract has three copies written by the
orchestrator (dev-overnight.md:821-852), a seed from the launcher (create-overnight-state.sh:1026-1056, `required_calls:
[]`) whose presence switches pretool-subagent-enforce.py into enforce mode and refuses the Step 2 PM dispatch (a dead
end in the planning replay), and in-place mutation by hooks/lib/contract_runtime.py:1208-1250; its `schema_name`
entries name dev-report.v1 and qa-report.v1 (dev-overnight.md:836-840) while the same dispatches' obligations name v2
(E1 of the ledger, re-run on d625284 and P8). Experiment (corrections.md 2.21, INFERRED): no seed file
(pretool-subagent-enforce derives the allowed steps 2-4 from `_STEPS` and the cycle index); the contract has one path
(`<working root>/docs/dev/overnight/<sid>/cycle-<N>/cycle-contract.json`), one writer (the orchestrator at Step 4) and
no in-place mutation (dispatch status is read from the transcript); obligation-bearing entries carry no schema name
and posttool-overnight-file-check validates against the dispatch's own obligation; the state is written once by the
launcher and its cycle index and completion are read from the cycle directories; replay cycles 1 and 2 of a
2-pipeline overnight session. Decision rule: the variant ships if both cycles run with 0 blocks from the contract and
state hooks, a wrong role at step 2 is still refused, and a v2 report passes collection while a schema-invalid one is
stopped by G2 at its producer's stop. Fallback: keep the launcher as the state's only writer and the PM TRIAGE handler
as the contract's only writer, with one path; never three copies or a seed.

**E14. One producer for the spec monolith's sections.** At d625284 docs/dev/specs/spec-<ts>.md is written by the /spec
orchestrator, by dev (Sections 2 and 3, commands/dev.md:865), by the orchestrator applying QA's `spec_section_updates`
(dev.md:1026-1048) and by /commit Step 8's continuation agent (commit.md:915-943); /dev picks "the newest spec" by mtime
(dev.md:125-138). Candidates: (a) each section has one producer that writes it (dev its Sections 2/3, QA its own
updates, the spec agent the rest) and no orchestrator writes; (b) the spec agent is the monolith's only writer and the
others hand their changes in their own reports. Experiment: replay /spec then /dev (singular and 2-lane, QA pass and
QA fail) with each. Decision rule: take the variant with one writer per byte range in the trace and 0 blocks; prefer
(b) on a tie (one writer per file). Either way the spec path is decided once, by prompt-workflow at UserPromptSubmit
(the explicit `--spec`, else the session's last Write or Edit to docs/dev/specs/*.md, INDEX.md and README.md excluded;
PLAN-v2 P9 row 1), and the mtime rules go. Fallback: if neither variant gives one writer per byte range, take (b): the
spec agent writes the monolith and dev and QA put their section text in their own reports.

### Corrections to PLAN-v2 (and to the prompts written before P1b existed; record each in the PR with what you did)

1. P1b is new. It runs after P7b and P8 and before P1c; P2 and P3 start after P1c. PLAN-v2 section 6 (waves) and
   section 5 (phases at a glance) gain the rows "P1b, wave 2b, after P7b and P8, net code cap <= -1200" and "P1c, wave
   2c, after P1b".
2. D24 is applied here to every artifact, so per-artifact work that PLAN-v2 and the corrected prompts gave to later
   phases moves into P1b where your scope rows touch it: from P2, the canonical aggregate's single producer (corrected
   P2 row 4), closeout's harness-report writer (row 9), the cycle contract's single writer, single path, no seed and
   obligation-sourced schema (row 11, TC-35), the aggregate-pending and continuation-sentinel writers; from P3, the
   declaring-dispatch reader (corrected row 1), the escalation stores and the arbitration path (Goal 3), the
   journal-view writer, the completion report leaving the required chain, consumers importing
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
   fixed /tmp path in pretool-git-privilege-guard.py (/do consent :274, push grant :2093; probes X11a and X11b2 on
   d625284), execute-push.py writes the chain-B sentinel under /tmp (:35) for push.sh to read under the state dir
   (:106), and the push-gate token is written under /tmp by prose (commit.md:666) and read under the state dir
   (push.sh:212). With CLAUDE_STATE_DIR set each is a read of a file never written there.
5. pretool-git-privilege-guard.py:1254-1260 opens the `git commit -F "$MSGFILE"` argument with its quotes attached
   (planning trace-a), so its bulk-commit subject check never reads the message the changelog-analyst wrote. It is a
   read of a path never written (A69); fix the argument parsing (one line) and test it.
6. G4: stop-obligation-gate.py's whole effect is advisory re-validation; when you delete it, the registered file
   becomes an exit-0 stub (D15, TC-37) for P5 to replace. P5's "arm and delete the advisory branch" shrinks to what you
   leave.
7. P2 keeps arming G1-G3. E4's shipped-mode list is P2's input.

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
prompts, and the CLI's own writes (transcripts and todos are modelled). The fault pilot (prompts/P1c.md, "What the
pilot measured") ran /restart, a quota resume and armed G2's hand-off once each, without the write trace, so the map
holds no relation from them. The 33 map rows whose evidence is "code"
(inventory/README.md) are the first artifacts the regenerated trace must reach.

## Scope (re-verify every location on your base)

Locations are at d625284 with the inventory row (A..) that holds the evidence. "Moves" means the rule leaves a
consumer and lands in the gate at an allowed position (G2 or the producer's own stop, G1, G3); a rule that is already
there is deleted at the consumer, not moved. Where a row names an E-block, the experiment decides and the row states
both outcomes. Every deletion of code no live entry point reaches carries its reachability proof (D17).

| # | Group (map rows) | One producer kept | Deciding consumer kept | Moves to producer stop / G1 / G3 | Deleted |
|---|---|---|---|---|---|
| 0 | Step 1: the inventory on your base | — | — | — | Regenerate the map on your base before changing anything: run your trace runner over every pipeline and step in "What the planning trace replayed" (the "partly" and "no" items included) in shipped and in sandbox-armed settings, and run the static half (E1). Include what P7b and P8 added: P7b's overlay `settings.machine.json`, `logs/landing.log`, the marker or record it keeps in the git directory (`claude-settings.applied` in the reviewer's copy, or a `claude-settings.checked` marker in the git common dir), the seeded private-literal list and the installed pre-commit hook (A105-A107 hold the reviewer's-copy reading, UNVERIFIED); P8's deletions (dead callers of the resolver, spec-update-contract.py, check-todo-accounting.py) and its moved grant pointer. The d625284 map is a starting point; acceptance is measured on your base's map. Put the regenerated map (before) and the after-map, both produced by your CI check's own derivation, in the PR, never in the repository. |
| 1 | G01 cycle identity and registry (A01-A08) | Task id: hooks/prompt-workflow.py's mint at UserPromptSubmit (:1462-1480; /do :1320-1360; /redev minted as /dev, D22). User requirement: prompt-workflow.py's O_EXCL writer (:1573-1574); scripts/overnight-init.sh:411 writes through the same function or hands the text to it (technical choice, replayed). Registry sentinels: prompt-workflow.py `_init_dev_registry` (:1546-1553), also for overnight registries. Enforcement flags: the UserPromptSubmit hook through scripts/write-enforce-flag.sh. | obligation.py `canonical_task_id`, `registry_dir_for` and `TASK_ID_RE` (one rule; every other place calls them); G2 and the e2e gate read the sentinel's task anchor through that rule; the `qa_mode` reading follows E7. | none (the mint is the producer) | The orchestrator fallback mint and fallback blocks (commands/dev.md:196-218, dev-command.md:142-160: they become "re-run the command"), /do's fallback mint (do.md:58); the regex copies (subagentstop-artifact-contract-enforce.py:220-232, pretool-aggregate-check.py:96-107, posttool-lane-completeness-watch.py:113-119, scripts/dev-lifecycle.py:37, close.md:553-561 and :582 `SESSION_ID="dev-${TASK_ID}"`, dev.md:128, dev-command.md:884); the test-writer's self-created sentinel (dev.md:799); write-qa-mode.sh's `--init-if-missing` creation and, per E7, its `qa_mode` mutation (the script goes if nothing is left); /close's QA re-arming of the flags (close.md:244-274); the overnight-init.sh second flag caller (:304-305) once the launcher arms overnight registries through the same path; the role lists of the registry (prompt-workflow.py:1514-1526, dev.md:202-208, dev-command.md:146-151) per row 18; dispatch-metadata / start-sha writers (A07) if the regenerated map confirms no reader. |
| 2 | G02 workflow bookmark, todo list, replay stores (A09-A13) | Bookmark: prompt-workflow.py writes it once at command start. Todo list: the CLI's TodoWrite (a record in the transcript); no harness writer. Replay store: prompt-workflow.py (self-consumed at the next start, a use). | command_span (`calls()`, `last_todos()`, added per E7) for every reader of todos and dispatch counts (pretool-todo-validate.py, pretool-block-background-tasks.py, pretool-spec-block-foreground-agent.py, pretool-workflow-gate.py, pretool-subagent-enforce.py, stop-spec-coverage-enforce.py), per E7. | none | Per E7, the bookmark mutations in posttool-subagent-track.py:247-260, posttool-todo-sequence.py:146/:171, posttool-todo-tracker.py:97/:120, pretool-workflow-gate.py:908/:998/:1116, posttool-todo-count.py:50, contract_runtime.py:1208-1250, and the harness writes of `~/.claude/todos/<sid>-agent-<sid>.json` (prompt-workflow.py:1896/:1975, posttool-todo-tracker.py:93/:110, pretool-workflow-gate.py:901, break-overnight-lock.py:113); workflow-history (prompt-workflow.py:1802-1828 and its call :1893; probe X2: written at the second /dev of a session, read only by its own collision check); the replay decision's private terminal set (prompt-workflow.py:1783) in favour of obligation.TERMINAL_VOCABULARY. |
| 3 | G03 dispatch record and producer-gate outputs (A14-A18) | Obligation block: the orchestrator's dispatch from the command templates (a record in the transcript). | G1 at dispatch, G2 at the producer's stop, G3 at the next dispatch, all through obligation.py; nothing else validates an obligation or its artifacts. | the e2e gate's QA-report rule moves onto the QA dispatch's own obligation: it reads the path that obligation declares, not "the most recent qa-report" (subagentstop-e2e-enforce.py:115; fault pilot: the newest-file correlation masks a missing lane report and wedges every lane on a stale one) | G4's re-validation: stop-obligation-gate.py:103-145 (the file becomes an exit-0 stub, D15), obligation.py's re-validation inside find_unresolved_dispatch_obligations (:1001-1020; keep only what the declaring-dispatch reader of E3 uses), posttool-overnight-loop.py:142-222 terminal lanes; G2's escalation stores and admission (subagentstop-artifact-contract-enforce.py:614-635, :637-656, :659-713, :747-829, deferred-checks :691) so G2's failing stop is a plain exit 2 naming the failing artifacts to their producer (corrections 2.27), and the arbitration comment (:292-297); the advisory log writes per E12 (pretool-obligation-gate.py:91, stop-obligation-gate.py:56, posttool-overnight-loop.py:28, subagentstop-artifact-contract-enforce.py:124, pretool-aggregate-check.py:388, subagentstop-cp-enforce.py:36, stop-do-report-gate.py:58, posttool-lane-completeness-watch.py:68); the second role list (pretool-obligation-gate.py:80-86 against obligation.ROLES :74-80) per row 18. |
| 4 | G04 BA and context family (A19-A30, A122) | Context: BA (agents/ba.md:145). Ticket, acceptance criteria: BA. BA-QA report: QA in BA-validation mode. Graphify pre-query: scripts/graphify-query.py; graph cache: one of graphify-maintain.py and graphify-enrich.py (technical choice with a stub binary). | G2 at each producer's stop and G3 at the next dispatch; the orchestrator's verdict branch on the BA-QA report (dev.md:691-699) stays as the route (a use, not a check). | dev.md's post-BA "sanity checks" (:352-389, :527-538) and the test-writer gate's field checks (:789-791) are schema-checkable: what G2's context.v1 already checks is deleted, anything it lacks moves into the schema (E4 shows which). | Per E10, the orchestrator patches of the context (dev.md:540-584, :1163-1166) and graphify-enrich.py's in-place patch (:413-491), and every graphify output with no reader (graph-summary.json, focused-subgraph.json, graph-report.md, the registry copy of graphify-run.json); the refined-context and context-iter jq builds (dev.md:1177-1199, dev-command.md:778-793) and the qa-input reading branch with its naming-list mentions (dev.md:1196, :1392-1396; dev-command.md:793, :916-920): the QA-fail loop re-dispatches the lane's dev with the QA report path (D2); BA's write permission on ba-qa-report (policies/tool-policy.v1.json:127); the resolver's re-check of the ticket and context at /close and /commit (row 7); scripts/create-worktree.sh's copies of docs/dev artifacts into the overnight worktree, unless E13's replay shows the worktree cycle needs them (then the copy is the worktree's own producer and the main tree's file is not read there). |
| 5 | G05 test-writer artifacts (A31-A33, A121) | test-writer. | G2 and G3. | none | The orchestrator's existence check that "aborts the cycle" (dev.md:818, a duplicate of G2); the global index upsert (tests/generated/manifest.json) if the regenerated map confirms no reader (planning: none but snapshot scanners). |
| 6 | G06 dev-report family and ownership facts (A34-A43) | Lane or singular dev report: dev. Canonical aggregate: per E5. Ownership facts and baseline: per E6. Late repair: scripts/late-repair-controller.py writes only its own files. Terminal vocabulary: the schema, with obligation.TERMINAL_VOCABULARY as its one code mirror (drift-tested since P1). | G2 at dev's stop (the obligation path; the legacy correlation path only for a dispatch without an obligation) and G3 (pretool-aggregate-check.py) before QA; QA uses the report (a use). Consumers that need the cycle's state call the one chain function (row 7). | posttool-overnight-file-check.py validates against the dispatch's obligation, not a contract schema name (E13; one declaration, fixes E1); the lane roster check moves from posttool-lane-completeness-watch.py into G3. | late-repair-controller.py's writes into dev, BA and QA reports (:94) and its stage-to-basenames table (:82-88, E3); per E9, the aggregator's merge into the singular report (aggregate-dev-report.py:1321-1505, called at :3738-3740); the aggregator's re-run at /close Step 0 and /commit row 1 (ruling 1); its `superseded-<task>/` reading branch (aggregate-dev-report.py:962-1036, read and never written); the lane-watch's roster decision; prompt-workflow.py:1786-1799, posttool-overnight-loop.py:32/:156-200 and dev-lifecycle.py:201-252 private terminal sets and re-derivations (they import the one vocabulary or call the chain function); per E6, the losing ownership producer and every rule that compares the two; journal-view (subagentstop-artifact-contract-enforce.py:451-465); aggregate-pending (posttool-lane-completeness-watch.py:126-129, :188-208, :309); the role-to-prefix and per-role field tables (subagentstop-artifact-contract-enforce.py:119-122, posttool-overnight-trace.py:256-269) per E3. |
| 7 | G07 QA report, completion report, chain disposition (A44-A46) | QA report: QA. Chain conclusion: scripts/resolve-dev-artifact-chain.py, the one function every consumer calls (P3 later turns it into `--disposition`). | G2 at QA's stop and G3; the e2e gate reads its own dispatch's obligation (row 3). /dev's end, /close and /commit each call the one chain function once and use its output verbatim (ruling 1 allows class a there); calling the same pure function is trusting one conclusion, re-implementing any part of it is re-deriving. | G2's qa wire (subagentstop-artifact-contract-enforce.py `_wire_qa_chain` :523-564) checks other producers' artifacts at QA's stop, which is the wrong producer: what it checks moves to G3 at the next dispatch, or is deleted where G3 already checks it. | /close's schema gate (close.md:434-491), /close Step 0's re-validation layer (scripts/close-route-select.py's own verdict, close.md:344-398) and /commit Step 5's second resolver run (commit.md:334); dev-lifecycle.py's own stage derivation and its SQLite cache (:858-937, written and never read); late-repair-controller.py:218 and aggregate-dev-report.py:597 resolver runs; the completion report leaves the resolver's required chain (it restates the chain result and is orchestrator-written, D8) and, per E12, is no longer written if no command output names it; the orchestrator's writes of QA content into the spec, the settings, the context and the score log (dev.md:1026-1048, :1081-1110, :1180-1182, :1062-1075; QA writes its own spec sections per E14, permissions are reported, not written); the resolver's chain and family lists (resolve-dev-artifact-chain.py:1030-1035, :1137-1143, :1196-1200) and dev-lifecycle.py:667-672 where E3's reader names the same files. |
| 8 | G08 spec, checkpoints, split views (A47-A50) | Spec monolith per E14; spec path: prompt-workflow.py at UserPromptSubmit. Checkpoint state: scripts/spec-check.py (the CLI agents run). Split views: the spec subagent. | subagentstop-cp-enforce.py at the producer's stop (cp-state); resolve-spec-artifacts.py at /spec finalize (the producer side) and as /dev's entry precondition (G1 position). | none | The three spec mtime rules (dev.md:125-138 and its staleness guard, dev-command.md:87-95, create-overnight-state.sh:500-517); pretool-cp-checkin.py's cp-state payload writes (:309-313, :423-430) and the spec agent's direct cp-state write instruction (agents/spec.md), leaving spec-check.py as the one writer; /close's split-view re-check (close.md:504-519); the `.spec-binding.json` and design-turn writes if the regenerated map confirms no reader outside /spec. |
| 9 | G09 /do (A51-A55) | Consent flag and task sidecar: prompt-workflow.py at UserPromptSubmit. Reservation markers: prompt-workflow.py:1348. /do report per E8. | One `has_do_consent(payload)` in hooks/lib/allowlist.py (state-dir path, content `true`, the subagent check), called by every consent reader (eleven hooks with thirteen read sites at d625284; PLAN-v2's "12 consent readers" counts differently; shell hooks through one entry point; measure the added latency). `do.status` through one function on obligation.TERMINAL_VOCABULARY. | none | The readers' own consent semantics (pretool-aggregate-check.py:647, pretool-bash-safety.sh:907, :2748, :2790, pretool-block-background-tasks.py:153, pretool-block-branch-pr-worktree.py:589, pretool-block-enterworktree.sh:60, pretool-do-block-subagents.py:74, pretool-orchestrator-gate.py:77, pretool-read-size-guard.py:27, pretool-subagent-enforce.py:52, pretool-write-guard.sh:60, pretool-git-privilege-guard.py:274 and its fixed /tmp path, probe X11a); do.md:58's fallback marker writer; the per-reader terminal sets of the do-report (stop-do-report-gate.py:23-24, close.md:414/:416/:491, resolve-commit-repos.py:423-463's route by file name, dev-lifecycle.py's do track). |
| 10 | G10 /close (A56-A61) | Inspector reports: the three inspectors. Close report: close QA (close-report-append.py only as close QA's own tool). | G2 at each producer's stop. Every reader of the close verdict uses one classifier (hooks/lib/close-verdict.py) on the report's last line, verbatim. | none | The orchestrator's re-validation of the inspector reports (close.md:567); pretool-gitignore-preflight.py's deliverable allowlist (:398-403) per E3; the routing tables (close.md:162-181, commit.md:99-116) and the "no code table" claims (close.md:288, commit.md:83-84): an incomplete cycle is reported as the artifact, its failing check and the dispatch E3's reader returns; /commit Step 3's own accepted-line list (commit.md:204-233, its "— FORCED" form included) and close.md's prose list (:782-787); score-update.sh's precondition re-read of the close report (close.md:845) and close-scoring-decide.py's own verdict reading (they call the classifier; P9 retires scoring); the close-force flag's reading branches (subagentstop-e2e-enforce.py:387-388, subagentstop-artifact-contract-enforce.py:365-373, :1215) and scripts/cleanup-close-force-sentinel.sh (read, never written). |
| 11 | G11 /commit chain (A62-A70) | Manifest: the orchestrator (an orchestrator artifact). Commit grant: scripts/write-commit-grant.py. Attestation: pretool-commit-dispatch-attest.py. Commit-QA verdict and changelog status: per E11. Push-gate token: the changelog-analyst's Write. Commit message: the changelog-analyst. | The grant mint's pipeline check (hooks/lib/commit_pipeline.py `verify_pipeline_dispatch`) for the manifest; the privilege guard for the grant and the attestation (spending a single-use grant deletes it: consumption); push.sh for the token. | posttool-push-gate-token-verify.py stays as the producer-side check on the analyst's own Write (it runs at the producer). | The changelog-analyst's manifest check (agents/changelog-analyst.md:206); the guard's `.use`/`.lck` rewrites of the grant and its rewrite of the attestation (spend by deletion instead; technical choice, replayed); per E11, the losing channel of each verdict and /commit's cross-check (commit.md:579-583), re-parse (:851-853) and the changelog-status* table row; step7-spec-update.py's re-checks of the close report, the changelog status and the token (it reads them verbatim or not at all); push.md's token re-check (:140-160); write-commit-grant.py's own user-intent age rule (:460-468) per row 14; the path mismatch of the token (row 12's path rule); the guard's quoted `-F` read (Correction 5). |
| 12 | G12 /push and /merge grants (A71-A75, A123) | Each grant: its analyst. Chain-B sentinel: scripts/execute-push.py. Push grant: hooks/push.sh. | One validator per grant per E11 (execute-push.py for the push-analyst grant; the code validator or the producer-side check for the merge grant). | per E11's fallback, the merge grant's validation moves to the merge-analyst's own Write | The second validator of each grant (pretool-push-analyst-grant-guard.py's repeated field checks, or merge.md:127-166's prose validation and unlink); the fixed /tmp paths: execute-push.py:35 and pretool-git-privilege-guard.py:2093 read and write under `harness_state_dir()` like push.sh:106, :212, :369 (probe X11b2), and the token's writer prose uses the same rule; the analysts' audit logs per E12; the pull-analyst grant if the regenerated map confirms no consumer. |
| 13 | G13 overnight (A76-A87) | State and cycle contract per E13. PM and specialist artifacts: their subagents. Plans: the scripts the orchestrator runs (once E13 lets them run). Overnight log and summary: the orchestrator (read by the owner, E12). Git shims: scripts/overnight-git-env.sh. | pretool-subagent-enforce.py at dispatch (G1) and posttool-overnight-file-check.py at collection (G3) for the contract; G2 at each PM or specialist stop for their reports (their obligations name them). | The prose validations "Validate test plan / triage report / retro report" (dev-overnight.md:533, :802, :1638) move into the PM and specialist obligations, checked by G2 at their producers' stops. | Per E13, the extra state writers, the seed, the mirror `.claude/overnight-contract-<sid>-cycle<N>.json`, the `cycle-current.json` symlink, contract_runtime's in-place mutation and its candidate paths beyond the working root (`_candidate_contract_paths` :79-98; it probes `~/docs/dev/overnight/...` and cycle-0 contracts on every Agent call outside overnight), and the v1 schema names (dev-overnight.md:836-840); posttool-subagent-track.py's second reading of the contract bookmark (:397) and the artifact-status sidecar writer (posttool-overnight-file-check.py:316-330) if its reader is gone; the continuation sentinel (stop-overnight-timelock.py:163-190); closeout's harness-report.json writer (hooks/lib/closeout.py:510-537); the idle and self-repair logs per E12 (notification-idle-overnight.py:144; pretool-overnight-hook-guard.py:317, whose write is part of that guard's fail-closed self-repair grant, so E12's replay of the guard decides it); the overnight delivery marker stays: prompt-workflow.py:1039-1040 writes it and :1180-1182 reads it back to decide whether to re-send the continuation spec (a cache, so it has a consumer); scripts/check-overnight-reports.py's re-check where G2 now checks the same report. |
| 14 | G14 grants, consent, intent (A88-A94) | /allow: hooks/userprompt-consent-allowlist.sh writes the structured sentinel only (probe X1: it writes both channels today). User-intent flags: prompt-workflow.py. Restart grants: userprompt-restart-authorize.py. | hooks/lib/allowlist.py's reader for every /allow consumer; pretool-wrapper-userintent.py for the commit, push and merge intent flags; one reader function in subagent_restart.py for the restart state. | none | The legacy flag `claude-bash-allowlist-<sid>.json` (its write at userprompt-consent-allowlist.sh:653-663, described in its header :21-24, and the reading branches: hooks/lib/allowlist.py:147, :216, :290, which `read_grant` and its siblings use, and their callers pretool-bash-safety.sh:499 and :923-957, pretool-git-privilege-guard.py:293-298, pretool-block-branch-pr-worktree.py:614, pretool-block-enterworktree.sh:72, pretool-do-block-subagents.py:118, pretool-aggregate-check.py:658, pretool-orchestrator-gate.py:250, pretool-read-size-guard.py:73, pretool-subagent-enforce.py:326, pretool-write-guard.sh:137, posttool-allowlist-consume.py:774-788, stop-cleanup-allowlist.sh); write-commit-grant.py's second user-intent decision (:460-468); the daemon-restart `-all` fallback (pretool-bash-safety.sh:613-620: no repository file writes `claude-allow-daemon-restart-all.flag`, and the documented external grant-helper protocol names per-target flags only, PUBLIC-CORE.md:109-112; the per-target flags, which the operator's helper writes, stay); the residual-override logs per E12. |
| 15 | G15 logs, scores, capability, daemon state (A95-A103) | Score log: scripts/score-update.sh until P9 retires scoring. Each log or state file: its one writer function. | none needed for logs read by nobody (E12); the capability gate for the handshake records; the coordinator for session resources. | none | scripts/lifecycle-baseline-import.sh's second write of the score log and its read of `agent-scores.json` (read, never written); the score-update precondition (row 10); every log no command output names (E12: checkpoint logs, guard and override audit logs, fswatch logs) at its writer; second writers of the fswatch state, capability records and watchdog pid files if the regenerated map confirms them (planning evidence is static only). |
| 16 | G16 settings and landing (A104-A107) | Project settings: the CLI (the platform); harness writers report suggested permissions instead of writing. Harness settings: scripts/install/render-settings (P7b's `land` calls the same function). Private-literal list and pre-commit hook: init's step, which the landing calls. | the CLI's permission engine; render-settings check (doctor, CI). | none | The orchestrator's jq edit of project settings from the QA report (dev.md:1081-1110, D8) and scripts/apply-permissions.sh's write (dev-overnight.md:1518-1519): both report suggested permissions; P7b's `logs/landing.log` write (read by no code, render-settings :1193 in the reviewer's P7b copy; E12: unless a command output names it), keeping the notice line; any second code path that writes the overlay or the hooks outside the shared functions. |
| 17 | G17 doc-sync and session by-products (A108-A116) | doc-sync per E9 (update-only). Session scratch marker: session-scratch-init.sh. | none needed (nothing reads INDEX.md or README.md by name) | none | Per E9, doc-sync's creation of INDEX.md and README.md in product directories and docs/dev, and with it the hook-landed-files ledger and the aggregator's merge (row 6); doc-sync notices (`/var/tmp/claude-scratch/<sid>/doc-sync-notices-agent-<hex>.json`, deleted unread at SessionEnd); the spec-update temp notes (`update-<rand>.md`, written and never read; spec-update.md's mktemp-then-Write sequence is also refused by pretool-write-guard.sh); the `.claude/doc-sync.json` reading branch unless a command or doc creates that file. |
| 18 | G18 probes nothing writes, tables, rosters (A117-A120, A124) | Roster: computed from the stems of agents/*.md in one hooks/lib function (no literal list); obligation.ROLES stays the producer subset, tested as a subset. | the one roster function; E3's reader for anything that maps an artifact to a role. | none | The reading branches of files nothing writes: `.claude/.hook-refactor-allow` (pretool-claude-config-guard.py:77), `~/.config/claude/protected-runtime.json` (runtime_guard/config.py:63), the generic `claude-*-grant-*.json` probe (pretool-git-privilege-guard.py:374), `<proj>/.claude/CLAUDE.md` (session-info.sh:26, session_start.sh:28), `.claude/agent-bookmark-*.json` (posttool-overnight-trace.py:394), `.claude/.awesome-claude-harness` (session-gitignore-propagate.sh:22) unless a command or init creates it; the hand-written rosters (CP_AGENTS pretool-cp-checkin.py:62-84, ALLOWED_AGENTS spec-check.py:91-110, agent_types prompt-workflow.py:1514-1526, PRODUCER_ROLES pretool-obligation-gate.py:80-86, the roles in posttool-overnight-file-check.py:53-56, posttool-overnight-trace.py:50, subagentstop-codex-enforce.py:31, contract_runtime.py:1185, late-repair-controller.py:51, score-update.sh:258-262) and command lists (obligation.py:81-83, pretool-obligation-gate.py:88-90, prompt-workflow.py:1925, :1929) that repeat a declaration; the tool-policy write prefixes that name files nothing writes or reads (A118: 94 families at d625284, 41 matching no other artifact) and, per E3, those that name declared artifacts; /clean's orchestrator.sh outputs read only by their writer if the regenerated map confirms it. |
| 19 | The CI check and the trace runner (new, under tests/) | — | — | — | Not a deletion: a pytest module (for example tests/test_artifact_graph.py) and the runner and drivers it uses (for example tests/replay/), added to the baseline workflow as its own step or job (E2). It derives the relations at test time (E1), asserts every invariant of goals 1-4 over every artifact it finds, prints each violation as facts (artifact, writers, deciding readers, position, file:line or trace event), and has no exception list. It opens no TSV and no file under harness-repair-plan/, and its source holds no list of artifact names or roles: it reads settings.json for hook positions, the obligation records and the canonical todo steps for declarations, agents/*.md for the roster, the command files for owner-facing outputs (E12). The runner and the ten compliant drivers are written so P1c can add faults to them. |
| 20 | tests | every test that pins code or prose you delete or change | — | — | A test that exercises only deleted code goes with it, named in the PR (D17); a pin a decided change makes false changes in the same commit to the decided behaviour (TC-54); no skip, xfail or collect_ignore. New tests: the declaring-dispatch reader, has_do_consent, the roster function, the path rule under CLAUDE_STATE_DIR, the guard's `-F` parsing, and the CI check's own mutation tests (acceptance 3). |

## Background (in the extracted planning documents, `harness-repair-plan/`, and in the repository)

- `audit/2026-10-23/`: `register.md` (the owner's words with sources; rows PC1-PC11, T0-T5, ON1-ON9, RD1-RD7,
  QP1-QP9, SG1-SG7, HC1-HC7, SF1-SF5, CC1-CC11, DT1-DT5, X1-X19), `ledger.md` (56 rows with the problem labels MP, MC, RD, DEAD, PROSE, TABLE, STATE, MISMATCH and the
  experiment E1), `corrections.md` (section 1.1 holds D20-D24 verbatim; section 3 the corrected P2-P11 prompt text this
  phase takes items from), `report-zh.md` (the owner-facing summary).
- `inventory/README.md` and `inventory/artifact-map-d625284.tsv`: the d625284 map (planning evidence only, Step 1),
  with how each disagreement was settled and what the planning traces did not replay.
- `prompts/P1.md`: "Sandbox and arming" (how to arm G1-G3 in a sandbox copy only), the scenario-driver rules (T1
  order: the Agent tool_use is in the transcript before PreToolUse runs; queue-operation records; slash-command
  records; dispatch, subagent transcript, SubagentStop, tool_result), and acceptance 18 (live landing), which
  acceptance 17 here follows.
- `PLAN-v2.md` sections 3 (principles), 5 and 6 (phases, waves), 13 (carry-overs); `DECISIONS.md` (D2, D8, D15, D17,
  D18, D19; D20-D24 once corrections.md 1.1 is applied).
- `tools/` (the kit) and `README.md` ("Sandbox").
- In the repository: docs/reference/close-commit-zero-failure-mechanism-20260928.md (section 0 rulings and C1-C5;
  section 1.1 state channels; section 1.2 the obligation grammar; section 1.3 the gates).

## Out of scope

- P1c's suite: fault injection as a CI test, the no-dead-end check, the replays of fixed process errors (P1's parallel
  wedge, E1, the settings write that hung /pull, a repair refused under a held git lock with no notice), and the merge
  condition for later phases. You ship the runner and the compliant drivers; P1c builds on them.
- Arming G1-G3 (P2) and the time-lock, window and landing route of /dev-overnight (P2), beyond the state and contract
  producers of row 13.
- The disposition function's interface, facts-only gap lines and freshness (P3), beyond the declaring-dispatch reader
  and the single chain function of row 7.
- /close and /commit completing an incomplete cycle by re-dispatching (D7, P4), the native rating (P4).
- The unified Stop gate and its launcher, the D8 deny for paths no obligation declares, /do <task-id> (P5).
- Role and identity from the CLI, the commit grant's binding (P6).
- The prose pass, CLAUDE.md, scoring retirement beyond row 15's second score-log writer, the git option table (P9).
  CLAUDE.md's Hook Discipline #5 ("honest terminal branch") conflicts with the owner's "诚实终态永远不允许" and is P9's
  rewrite under D20 and D23; do not touch CLAUDE.md.
- Stub removal and file-level dead code beyond the deletions your rows name (P10); history and remote refs (P11).

## Acceptance tests (run each, paste the command and its output in the PR)

Setup: the kit is in the extracted planning documents: `T="$SCRATCH/plan/harness-repair-plan/tools"`,
`export SB=$SCRATCH/sb-p1b`, `PYTHONDONTWRITEBYTECODE=1 "$T/sb-setup.sh" "$PWD"` from the repository root (re-run after
every code change); a second kit `SB=$SCRATCH/sb-base` from a scratch clone at your base (`git clone`, then a detached
checkout of origin/master; not a worktree) for every "on the base" comparison. Every hook run goes through `"$T/ns.sh"`
(or your E2 runner); never against your container's `~/.claude`. Arm only a copy, as P1 "Sandbox and arming" shows.

1. **Base.** The "Before you start" checks, with their output.
2. **CI.** The baseline workflow's steps on Python 3.12 on your base and on your branch, plus the new check's step or
   job (E2): green on your branch, with its wall time.
3. **The check fails when it should** (committed mutation tests that build a scratch copy of the tree and run the
   check on it): a second writer of an existing artifact; a reader of a path nothing writes; a write of a file nothing
   reads; a consumer outside the allowed positions that re-validates an artifact (for example a resolver run added to a
   /close step); a hand-written filename-to-role mapping or role list in a hook; a consumer reading a state file under
   /tmp that its writer puts under CLAUDE_STATE_DIR. Each run exits non-zero and names the artifact, the components
   and the file:line or trace event. On your base (before your changes) the check fails, and its output is the
   "before" side of the D24 table.
4. **Ten compliant pipelines.** Your runner replays /spec, /dev (singular and 2-lane, with a QA-fail loop, a BA
   producer question, a BA-QA fail), /redev, /dev-command, /dev-overnight (two cycles of a 2-pipeline session, E13),
   /do, /close (after /dev, after /do, after /dev-command, with a routing round and a close-QA append round), /commit
   (after /close; and --auto), /merge and /push, in shipped settings and in sandbox-armed settings. Expected: 0 blocks
   from any hook and 0 hook errors (exit other than 0 or 2) in every compliant run. Print one table: pipeline, settings,
   hook events, hook runs, blocks, hook errors, wall time untraced and traced. Any block is either a driver that does
   not follow the command text (fix the driver and say so) or a defect you fix; never a hook change to suit a driver.
5. **Faults (E4).** For every artifact family whose consumer-side check you deleted: missing, schema-invalid and stale
   artifact, in shipped and armed settings, on your base and your branch. Armed on your branch: every fault stopped at
   its allowed position, the message naming the artifact and the failing check, returned to its own producer, passing
   on the next round with no human action. Shipped: the escape list for P2.
6. **D24 table** in the PR body: artifact / producers before → after / deciding consumers before → after / proof (the
   writer and reader grep on your branch plus the trace events of acceptance 4), one row per artifact of your
   regenerated map, every row "after" = one producer, at least one consumer, one deciding rule.
7. **Declaring dispatch (E3).** The reader returns the producing dispatch (or the canonical todo step) for every gap of
   every replayed pipeline; `grep -nE 'close_artifact_role|artifact_role\(' commands/close.md commands/commit.md`
   prints nothing, and neither file claims "no code table"; the tables named in E3 are gone or reduced as E3 decided.
8. **Identity.** `git grep -nE 'session_ts|TASK_ID_REF_PATTERNS|SESSION_ID="dev-\$\{TASK_ID\}"' -- hooks scripts commands ':!hooks/tests'`
   prints nothing; every task-id-to-name derivation in hooks/ and scripts/ is a call into obligation.py (list them).
9. **Path rule.** With CLAUDE_STATE_DIR set in the sandbox: a /do UserPromptSubmit then a main-agent `git commit`
   PreToolUse through the privilege guard and the other consent readers: each honours /do (the guard probes the state
   dir; on the base it probes /tmp, probe X11a); with CLAUDE_PUSH_COMMAND_ACTIVE=1 the guard reads the push grant from
   the state dir (on the base its message names /tmp, probe X11b2); execute-push.py and push.sh agree on the chain-B
   sentinel and the push-gate token. `git grep -nE '"/tmp/claude-|/tmp/agentic-commit' -- hooks scripts ':!hooks/tests'`
   lists only defaults inside the state-dir helper.
10. **Dead artifacts gone.** For each written-never-read artifact your rows delete: no writer left (`git grep` of its
    name over hooks scripts commands agents prints only its removal's test, if any) and the acceptance-4 replays create
    no such file. For each read-never-written path: no reading branch left. Name each in the PR with its reachability
    proof.
11. **C1.** The path patterns of state and artifact files in your branch's acceptance-4 trace are a subset of the base's
    (no new mutable state file); list the files your branch no longer writes.
12. **C2.** `git diff --numstat origin/master -- commands/close.md commands/commit.md agents/changelog-analyst.md`:
    deletions exceed additions, and every added line is a call of an existing function or the reader's output, not a
    check; show the added lines.
13. **C3.** Deciding checks outside the allowed positions: count on the base (from the check's "before" output) and 0
    on your branch; producers per artifact: the base's distribution and 1 everywhere on your branch; rules retired >=
    rules added.
14. **C4.** The planning fault scenarios replayed armed on your branch (a missing, a malformed, a stale report; a held
    `index.lock` during /commit; a session cut and /restart; a fan-out lane with a stale report): your changes add no
    block a compliant producer cannot clear and no dead end; list every dead end that exists on the base too, for P1c.
15. **C5.** For every blocking hook left at an allowed position, one replay shows its block message names the artifact
    path and the failing check and lands on the producing subagent's stop, or on the orchestrator's dispatch of that
    producer.
16. **E-blocks.** Each experiment's setup, raw output and option taken, E1-E14.
17. **Live landing** (owner, 2026-10-18: he cannot stop his sessions; D15). Copy origin/master's settings.json to
    `$SB/settings.base.json` and replay, in the sandbox built from your branch, with `--settings
    /mnt/sb/settings.base.json`: a compliant /dev Stop, an in-flight /dev cycle built from the base's command text
    (routing tables, the base's obligation templates, the base's dispatch prompts), a /close and a /commit of it, and a
    plain UserPromptSubmit. Expected: no hook exits 2 except a block your rows make correct (name each), every hook file
    the base's settings register still exists (emptied ones are exit-0 stubs with the `# STUB:` line), and the cycle can
    still reach a commit. Repeat with your branch's settings.json.
18. **Personal values.** `scripts/check-public-core.sh` passes on your branch, and `git diff origin/master` adds no
    e-mail address, account name, private project name or personal home path.
19. **Full suite.** `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider` -> 0 failed at every commit of
    the PR (TC-54); CI green.
20. **Net code.** `git diff --numstat origin/master -- hooks scripts schemas ':!hooks/tests'`: net lines (added minus
    deleted) <= -1200. Report tests/ (the check, the runner, the drivers) and commands/ plus agents/ separately.

## Rules added / retired (expected)

Added (at most 3, each replacing several):
- the CI check of D24 and the allowed positions (a test, not a runtime rule);
- one declaring-dispatch reader (replaces every filename-to-role table and, per E3, the per-role write prefixes that
  name declared artifacts);
- one path rule for hook state (`harness_state_dir()` on both sides of every state file).

Retired (at least 40): every regex or prefix copy of the task id; the orchestrator and /do fallback mints and blocks;
the registry role lists and the hand-written rosters; the `qa_mode` switch and the bookmark and todo-file mutations
(E7); workflow-history; G4's re-validation and the overnight loop's terminal lanes; G2's escalation records, admission
and arbitration; the advisory logs (E12); the e2e gate's newest-file correlation; the orchestrator's context patches and
graphify's in-place patch (E10); the refined-context and context-iter builds and the qa-input read; BA's ba-qa-report
permission; dev.md's post-BA and test-writer re-checks; late repair's writes into other producers' reports and its stage
table; the aggregator's re-runs at /close and /commit, its superseded read and its singular merge; the lane watch's
roster decision; the private terminal sets; journal-view; aggregate-pending; /close's schema gate and Step 0 verdict
layer; /commit Step 3's accepted-line list, Step 5's second resolver run, the commit-QA cross-check and the status
re-parse; dev-lifecycle's own derivation and cache; G2's qa wire chain run; the completion report as a required link;
the orchestrator's writes of QA content; the spec mtime rules; cp-checkin's and the spec agent's cp-state writes;
/close's split-view re-check; the consent readers' own semantics (eleven hooks); the per-reader do.status sets; the
routing tables and their "no code table" claims; the close verdict's private lists; the close-force readers; the
manifest re-check by the analyst; the grant's use-marker rewrites; the second validator of each grant; the fixed /tmp
state paths; the legacy /allow flag and its readers; the second user-intent decision; the daemon-restart-all reader; the
second score-log writer; the contract's seed, mirror, symlink, in-place mutation, home-root candidates and v1 schema
names; the state's extra writers; the continuation sentinel; harness-report.json; doc-sync's creation in product
directories with the hook-landed-files ledger (E9); doc-sync notices; the spec-update temp note; landing.log (E12).
Report what you actually did, each with its file:line on your base.

## Net code cap

Net lines in hooks/, scripts/ and schemas/ (tests excluded) must be <= -1200. Planning estimate on d625284 from the
map's deletions: about 2,300 lines removed (measured blocks: G2's escalation and journal-view code about 230,
find_unresolved_dispatch_obligations' re-validation and evaluate_required_values about 155, stop-obligation-gate.py
about 150 as a stub, the overnight loop's terminal lanes about 50, the aggregator's superseded read and singular merge
about 270, the hook-landed-files ledger about 640 if E9 deletes it, dev-lifecycle's cache and private rules about 50,
the second score-log writer 146, write-qa-mode.sh 92 if E7 removes the switch, the workflow-history and continuation
writers about 55, the advisory writers about 60, the legacy /allow channel about 90, the regex copies, rosters and
tables about 120, the close-route-select verdict layer and close-force readers about 110) against about 250 added (the
reader, has_do_consent, the roster function, the path rule, the obligation-sourced schema check). The cap leaves room
for E9 and E7 going the other way. tests/ (the check, the runner, the ten drivers) is outside the cap; report its size,
and keep the drivers to what the ten pipelines need. commands/ and agents/ are outside the cap; report their byte change
(they should shrink). Effort: XL (about 7 days). No owner time.

## Technical choices you make (D10, D18: list each in the PR as choice / experiment or test / result / why / revert)

E1-E14 and their options; the static half's parser and its determinism (fixed ordering); the runner's isolation and
sharding (E2); the differential runs' mutation set; how the check reads hook positions from settings.json and
owner-facing outputs from the command files; the declaring-dispatch reader's signature and its canonical-todo
fallback; has_do_consent's signature and the shell entry point, with the measured latency per Bash call; the roster
function's home; how overnight-init.sh reaches the one requirement and registry writer; how a single-use grant is spent
without a rewrite; which graph-cache writer stays; the stub text of every emptied hook; anything else you decide.
Follow the producer-side design doc, take the option with less code and fewer rules, and back each with a test or a
replay.

## Rollback

Commit order: (1) the path rule and the guard's `-F` parsing (small, behaviour-correcting); (2) dead outputs and dead
reading branches (rows 2, 3, 6, 13, 14, 17, 18: deletions only); (3) one producer per artifact (rows 1, 2, 4, 6, 8, 9,
11, 13, 16, with E5-E10, E13, E14); (4) one deciding consumer and the consumer-side deletions (rows 3, 6, 7, 10, 11,
12; E4, E11); (5) the declaring-dispatch reader and the table deletions (E3, rows 10, 18); (6) the CI check, the runner
and the drivers (row 19), which turn green only on top of (1)-(5). Each commit keeps the suite green and reverts on
its own; say in the PR what each revert restores. The reviewer reverts; the owner runs nothing.

## Branch and pull request

- Dependencies: start only after the pull requests titled `P8: …` and `P7b: …` are merged (see "Before you start");
  P1c follows you, and P2 and P3 start after P1c.
- Start your branch from the latest `origin/master`. If this session was assigned the planning-docs branch
  `claude/vibrant-hopper-bazrn8` or no branch, create `repair/P1b` from `origin/master` and use it. Push only to your
  branch. One branch, one pull request to `master`.
- PR body: the shared format below. Its first line reads "Owner steps: none." Under "Notes for reviewers" add these
  headings: **D24 table** (acceptance 6, every artifact of your regenerated map); **Inventory** (the regenerated map
  before and after, from the check's own derivation, and what differs from inventory/artifact-map-d625284.tsv);
  **Decided by experiment** (E1-E14: setup, raw result, option taken); **Corrections to PLAN-v2** (the list above,
  with what you did for each); **Faults** (acceptance 5, with the shipped-mode escape list for P2); **Hand-off to
  P1c** (the runner, the drivers, how to add a fault, the dead ends that exist on your base); **Live landing**
  (acceptance 17); **Release notes** (the list under "Goal"); **Out of scope, found**.
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
- Do not arm G1-G3 or any other switch in a tracked file (P2); arm only sandbox copies.
- Do not ask the owner anything, write a REQUEST for him, or give him a step on his machine (D18, D19).
- Do not commit or read from a test the d625284 map, any TSV, or a hand-written list of artifacts or relations; the
  check derives everything at test time and has no exception list or allowlist.
- Do not delete a registered hook file; empty it to an exit-0 stub with a `# STUB:` line (D15).
- Do not edit CLAUDE.md (P9 rewrites Hook Discipline #5 under D20 and D23).
- Do not change a hook to suit a replay driver; fix the driver to follow the command text.
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
