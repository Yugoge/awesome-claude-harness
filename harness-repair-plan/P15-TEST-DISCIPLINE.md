# P15: tests that catch real failures

**Base.** master 1ace5ee4 (train #49: #44 + #19 + #45). Every number and file:line below was measured on that commit
unless a line says otherwise.

**Why (owner, 2026-11-11).** "Claude Code writes shallow tests that do not understand the codebase and treat the
symptom." The problem is where the tests sit, not how many there are. P15 moves tests to the place a failure starts:
- recorded CLI shapes instead of hand-built records;
- consumers run instead of sentences grepped;
- a red-then-green proof for every fix;
- mutation checks on changed hook lines;
- one owner for the CLI's hook-output channel.

**Prompts.** `prompts/P15-*.md`, one per lane, each self-contained.

## 1. Baseline (measured)

The scripts and raw outputs are in the planning session's scratchpad. Each lane that needs a number re-runs the command
on its own base; the prototypes quoted in the lane prompts are enough to rebuild them.

### 1.1 Tests that only assert that text is present in a prompt or Markdown file

| Metric | Value | How |
|---|---|---|
| Tracked test files | 322 (hooks/tests 170, tests 120, artifact_graph 8, differential 3, lint 2, replay 19) | `git ls-files \| grep -E 'test_.*\.py$'` |
| Test functions (AST) / collected | 5678 / 15253 (14929 with CI's ignores) | AST walk; `HOME=$(mktemp -d) python -m pytest --collect-only -q -p no:cacheprovider` |
| Files that read a prompt or Markdown file | **109** (owner's 110 confirmed within 1) | classifier A (below) |
| Functions that read a prompt | 615 | classifier A |
| ... of which never execute code | 148 | classifier A |
| ... of which assert only text presence (lexical rule) | **84 functions in 31 files**; 2 files are prose-only throughout | classifier A |
| ... flagged by the data-flow lint prototype (the rule lane L6 ships) | **45 functions in 19 files**; 14 of 45 spot-checked, all true positives | classifier B |

The two classifiers:
- **Classifier A** is lexical. A test counts when every assert is `in`, `not in`, `re.*`, `startswith`, `endswith`,
  `count`, `find` or `index` on text read from `commands/`, `agents/`, `skills/`, `templates/`, `docs/`, a root `*.md`
  or CLAUDE.md, and nothing calls subprocess, importlib, runpy or a hooks/scripts/tools import.
- **Classifier B** is the lint prototype. It follows doc text through assignments, loops, `with`, helpers and
  fixtures, and treats a `tests.<pkg>` checker call as code. Its exemption rule is in section 2(c).

Files with the most flagged tests (B): `tests/test_close_command_text.py` 10,
`tests/test_dev_artifact_chain_consumer_contracts.py` 7, `tests/test_no_phases_agent_prompts.py` 7,
`tests/test_no_phases_spec_template.py` 5, then 14 files with 1 each.

Sampled prose-only tests stand in for behaviour that code implements:
- `hooks/tests/test_close_verdict_round_open.py:102` lifts `<obligation>` regexes out of `commands/close.md`; the
  hooks obligation reader should be run instead.
- `tests/test_step8_spec_update_markers.py:77` should run `scripts/step7-spec-update.py`.
- `tests/test_steps_pull_run.py:483` greps the source of `scripts/steps/pull-run.py`.
- `hooks/tests/test_spec_path.py:222` greps prose where the spec-selection hook should be run.

Others guard a sentence on purpose: the no-phases charter (D33), clause numbering that `agents/qa` cites, the lesson-15
deny coverage.

### 1.2 Hook tests that build CLI records by hand

| Class | Files / functions |
|---|---|
| Hook tests that execute code | 253 / 4608 |
| Build CLI transcript or hook records inline | **101 / 1278** (81 files in hooks/tests) |
| Use a shared hand-built builder | 3 / 24 (`hooks/tests/_fixtures_obligation_terminal.py:29,36,178`, `tests/_late_repair_fixtures.py`, `tests/replay/replay.py` `Session`/`Actor`) |
| Read **recorded** CLI records | **0**: the repository tracks no `.jsonl` or recorded transcript |

- The replay harness writes plain hook stdout in the pre-2.1.322 form: `hook_additional_context` with a string
  `content`. See `tests/replay/replay.py:553`, `:771` and `tests/replay/test_live_arming.py:127`.
- The installed CLI (2.1.325) writes `hook_success` for that stdout. No replay therefore exercises
  `hooks/lib/command_span.py:620`, the path #43 fixed.
- Only 2 tests build a `hook_success` record: `hooks/tests/test_command_span.py:568` and
  `hooks/tests/test_stop_command_gate.py:542`. Both use a `command` value the real CLI never writes.

### 1.3 Fix PRs since P12 with red-then-green evidence

**Since P12.** P12 merged as #33 at 3a968cf (2026-11-09T22:23Z). 14 PRs have merged since, 6 of them fix PRs. The
method: `git log --merges --first-parent master`, then each PR's body.

| PR | Evidence |
|---|---|
| #24 | claimed ("N new tests fail on the base"), no run |
| #27 | none (per-item tests, no failing run) |
| #43 | claimed (two tests "fail on master"), one commit, no red run |
| #47 | CI-only fix, red run 42880348955 cited, no test change |
| #48 | red run exists (42915142598 attempt 1), not linked |
| #49 (f0e4d9ca, 6bf06147) | f0e4d9ca: CI failure named by test id. 6bf06147: claimed only |

**Strict red-then-green evidence: 0 of 6.** Two have a red CI run, linked or not (#48, #49 for f0e4d9ca); two only
claim one (#24, #43).

The experiment for (a) found that the tests were usually good: replayed on their parents, 6 recent fix commits went red
then green (036d1ed, 447a63c, a3346c9, 3c68ca4, 041eafa, c9a29f4). The evidence was missing, not the test. Two did not:
- 6bf06147 changed no test; its guard already existed.
- f0e4d9ca's red was timing.

### 1.4 Flaky tests, from CI history

Baseline workflow, 589 runs. Method: rerun pairs plus log scan; the other ~131 failures in 60 days were not log-scanned,
so this is a lower bound.

| Flake | Seen | Status at 1ace5ee4 |
|---|---|---|
| Hero capture, `scripts/capture-hero-run.py:328-343`, via "Verify headline claims" | 2 (42924754530, 41295898191) | **open**: L10 |
| `hooks/tests/test_overnight_trace_yield.py::test_any_other_dispatch_is_only_traced[...]`: xdist "Different tests were collected" (non-deterministic parametrize ids) | 2 (42493753536, 42466716374) | **open**: L11 |
| SubagentStop freshness 2 s slack, extra BA-QA round (`test_score_dispatch`, `test_no_dead_end`) | 1 (42956128911) | fixed, f0e4d9ca |
| Launch-differential clock, `test_live_landing.py::test_again_with_your_settings[...]` | 1 (42915142598) | fixed, #48 |
| Replay shard 60-minute timeout | ≥3 | fixed, #47 |

### 1.5 CI time today

Median of 9 green runs after #47, by job:
- baseline 3.10 / 3.11 / 3.12: 54.8 / 49.0 / 55.3 min;
- replay shards 1 to 6: 33.3 / 57.9 / 57.9 / 39.6 / 41.8 / 36.0 min;
- artifact shards: 10 to 24 min;
- the existing mutation step: about 5 min;
- lint: 30 to 45 s.

Whole run: about 67 min median, range 58 to 98. **The critical path is replay shards 2 and 3 (57.9 min).**

### 1.6 Corrections to the brief

- #19, #43, #44 and #45 are PRs; the repository has no GitHub issues.
- The keystone PR, the parallel-launcher PR and the settings-switch PR are not open at the time of writing. Open PRs:
  - #29 (38 files, including 9 under `tests/replay/drivers/`);
  - #50 (`tests/replay/launch_cost.py` only);
  - #41 (one research doc).

  The fences in section 5 still hold for all four file sets: a lane does not touch them until the reviewer says the
  owning PR has merged or does not exist.
- `minted_id` takes the first match at `hooks/lib/command_span.py:533` (the property starts at `:530`). The artifact
  graph's own task-id minter search also takes the first match (`tests/artifact_graph/check.py:1504-1514`).

## 2. Decisions, each made by experiment (D18)

The prototypes ran in a copy of the repository with a throwaway HOME.

| | Decision | Experiment and result | CI time | Lines |
|---|---|---|---|---|
| **(a)** red-then-green | **Adopt** as a parallel job; blocking after the CI lane (L13) lands | see (a) | +1 to 6 min, parallel, off the critical path | ~150 |
| **(b)** mutation | **New** diff-scoped AST mutation step; do not extend `tests/artifact_graph/test_mutations.py` | see (b) | +5 to 10 min, parallel | ~130 |
| **(c)** prose lint | **Check 7** in `tests/lint`, with the consumer rule as the exemption | see (c) | +5 to 18 s in the existing lint step | ~300 |
| **(d)** recorded fixtures | **Recorder + fixtures + shape diff**; keep `scripts/canary-verify.sh` and add one version line to it | see (d) | <1 s | ~150 |
| **(e)** channel artifact | **`channel:cli-hook-output`** in the artifact graph, producer `cli`, plus the minted_id fix | see (e) | 0 at runtime | ~180 |
| **(f)** cross-PR integration | **Scheduled, non-blocking pair check** of changed tests; the merge train stays the gate | see (f) | off the PR path, 2 to 3 min per pair | ~40 |

### (a) Red-then-green job

**Mechanism.** Check out the merge base and lay the head's changed `test_*.py` and `conftest.py` over it. Run only those
files there (red), then on the head (green). Test helpers and fixtures stay the base's.

**Experiment.** Replayed on 8 real commits:
- 6 went red then green;
- 6bf06147 had no changed test, but its existing guard went red then green (2/23 to 0, 0.2 s);
- f0e4d9ca could not show a deterministic red, because the failure was timing.

A `git archive` tree gave false failures for tests that read history, so the job needs a real checkout.

**What it requires, and of which PRs.**
- **Exempt by path:** test-only and docs-only PRs.
- **Every other PR** (anything under `hooks/`, `scripts/`, `tools/`, test helpers or `settings.json`) needs at least
  one test id that fails or errors on red and passes on green.
- **A guard that already exists** is named with a trailer, `Red-test: <nodeid>`; the job runs that id red and green.
- **No red possible:** the PR body says `Red-test: none: <reason>`, and the job prints that reason at the top of its
  summary for the reviewer.

**Risk.** A collection error on red counts as red. The job reports it apart from an assertion failure, so the reviewer
can tell them apart.

### (b) Mutation on changed hook code

Extending the existing step does not fit:
- the existing step mutates the artifact checker's input by adding files nothing runs;
- a mutated existing hook is run by the replays, which would cost about 23 shard-minutes and about 50 s of CPU per
  mutant.

**The new step.**
- It mutates only the changed lines (`-U0` hunks) of `hooks/**/*.py` and `scripts/**/*.py`, spliced in place.
- It runs the PR's changed tests, plus the tests that name the file's stem.

**Results.**

| File | Mutants | Killed | Survivors |
|---|---|---|---|
| `hooks/subagentstart-record.py` | 6 | 3 | 3, all equivalent `sys.path` index mutants |
| `hooks/lib/score_view.py` | 33 | 32 | 1, at `:28` |
| `hooks/lib/command_span.py` | 16 | 13 | 3, at `:624` (the `stdout` fallback is untested) |
| `hooks/lib/allowlist.py` | 82 | 78 | 4, at `:326-329` (separators inside a shell comment are untested) |

The command_span and allowlist survivors are real test gaps. Time per file was 13 to 914 s.

**Bounds.** At most 40 mutants per PR, a per-mutant timeout of 4x the baseline run, `-x`. Equivalent mutants are
filtered by operator (no list): mutations of `sys.path` index arguments are not generated.

**Policy.** P15 lands it report-only, and L5 kills the known survivors. After 10 PRs, the CI lane (L13) makes it
blocking for survivors on changed lines, if fewer than 1 survivor in 10 turned out equivalent; otherwise it fixes the
generator first. That is decided by measurement, not by the owner.

### (c) Prose-only lint

**Rule.** A test is flagged when all of these hold:
- every assertion, its own or in a local helper, is text presence on doc text;
- the doc text comes from a literal naming `*.md`, `commands/`, `agents/`, `skills/`, `templates/` or CLAUDE.md;
- the test exercises no code. Code means an import outside stdlib, pytest and `tests.<pkg>` pure-text helpers, or a
  subprocess, importlib or runpy call.

Assertions on parsed structure (JSON, YAML front matter, a table parsed into rows) are not text presence.

**Exemption without a list.** A test whose assertions are all text presence passes only if, in the same test:
- it runs a consumer of that text;
- the consumer's source names the asserted file (by basename or directory);
- the lint resolves the call or subprocess target to a file and checks this.

If the consumer cannot be resolved, the lint fails closed. A sentence that no code consumes is not a contract; its test
is deleted, or replaced by one that runs the component that enforces the rule (for D33, the QA check that fails a
phased plan).

The rejected alternative, declaring the `.md` file an artifact with a derived reader, is coarser (whole file) and would
tie the lint to the replay job.

**Prototype.** 45 flagged in 19 files. 4 text-only tests are exempt because they exercise code: 2 resolve their
consumer and 2 do not yet (`hooks/tests/test_doc_sync_index_notices.py:724,744`, which L9 fixes). Run time: 18 s
unoptimized, under 5 s with caching.

### (d) Recorded CLI fixtures and the upgrade canary

**Experiment.** CLI 2.1.325 ran headless in a throwaway HOME with five trivial hooks. Shapes recorded:
- plain stdout becomes `attachment.hook_success`: `{hookName, toolUseID, hookEvent, content, stdout, stderr, exitCode,
  command, durationMs}`;
- JSON additionalContext becomes `attachment.hook_additional_context`: `{content: [str], hookName, toolUseID,
  hookEvent}`, with no `command`;
- Stop adds `system/stop_hook_summary`;
- **SubagentStop's `hook_success` goes to the subagent's transcript, not the parent's**;
- new stdin fields: Stop and SubagentStop carry `effort`, `background_tasks`, `session_crons` and
  `last_assistant_message`; SubagentStop also carries `agent_transcript_path`.

**Shape-diff rule.**
- A record's key is `type`, plus `attachment.type` or `subtype`.
- Its shape is each dotted key path, 3 levels deep with `[]` for list items, mapped to its set of JSON types.
- Values are never compared.
- Verified: identical shapes exit 0. A copy with `command` dropped and `exitCode` made a string exits 1 and names both
  changes.

**Layout.**
- `tests/fixtures/cli/<version>/` holds `transcript.jsonl`, `subagent.jsonl`, `stdin/<Event>.json` and `shapes.json`.
- `tests/fixtures/cli/CURRENT` names the version in use.
- The recorder replaces home, cwd, uuids and timestamps with placeholders and keeps no prompt or system-prompt text.

**`scripts/canary-verify.sh`.**
- It never runs the CLI (it feeds synthetic stdin to four PreToolUse guards, `:61-209`), so it is kept as it is.
- It gains one line: when `claude --version` differs from `CURRENT`, it prints an advisory to re-record (about 0.2 s).
- Recording itself needs the CLI and model access, so it runs locally on upgrade (about $0.03 a run, about 30 s).
- **Owner decision O1** is whether CI also re-records on a schedule.

**Gate.** A CLI version bump whose shapes differ fails CI until the new fixture, and every reader and synthesizer that
the diff touches, are committed together.

**Note on access.** In the planning container the CLI reached the model with no API key and nothing in HOME: the
container supplies auth. A machine without it fails after SessionStart and UserPromptSubmit have run. Those two events
still record.

### (e) The CLI's hook-output channel as an artifact

**Entry.** Artifact `channel:cli-hook-output`, kind `channel` (new; `tests/artifact_graph/check.py:206`, built in
`non_file()` at `:1421-1482`). Its one producer is `cli` (already a role, `check.py:111`); the declaration is
`tests/fixtures/cli/CURRENT/shapes.json`.

**Production readers**, all through `_opener_context` (`hooks/lib/command_span.py:555-572`), then `_prompt_hook_text`
(`:611-632`):
- `Span.minted_id` (`:530`), read by `hooks/stop-command-gate.py:387,403`, `hooks/lib/requirement_round.py:327` and
  `scripts/resolve-dev-artifact-chain.py:1574,1796`;
- `Span.opener_heads` (`:535`) and `Span.opener_remotes` (`:542`), read by `hooks/stop-command-gate.py:694,697`.

No other code under hooks/, scripts/ or tools/ reads `hook_success`, `hook_additional_context` or `stop_hook_summary`.

**Test synthesizers**, which become declared synthesizers of the channel:
- `tests/replay/replay.py:553,771`;
- `tests/replay/test_live_arming.py:127`;
- `hooks/tests/test_command_span.py:528,563`;
- `hooks/tests/test_stop_command_gate.py:91,548,1214,1395`;
- `hooks/tests/test_requirement_round.py:51`;
- `tests/test_do_partly_failed_close_route.py:139`;
- `tests/test_disposition.py:244`.

**Enforced.**
1. Only `cli` produces the channel. A synthesizer passes only if its records' shapes equal the fixture's; today
   `replay.py:553` fails this.
2. Every key a reader reads exists in the fixture for that record kind.
3. The channel has one parser, `_prompt_hook_text`.

**minted_id fix (folded in).** A scratch test with a foreign `hook_success` first and `userprompt-launch.py` second made
`minted_id()` return the foreign id. The rule:
- a `hook_success` record counts only when its `command` names the harness's own minting launcher (`userprompt-launch.py`
  or `prompt-workflow.py`);
- a `hook_additional_context` record (no identity) counts;
- two different ids among the counted records give `None` (fail closed).

About 20 lines; the scratch test passes. One existing test, `test_the_openers_context_is_read_in_the_cli_2_1_322_record_forms`,
then fails, because its helper writes `"command": "command hook"`, a shape the CLI never writes. Lane L2 moves it onto
the recorded fixture. The same first-match search in `check.py:1504-1514` gets the same rule.

### (f) Integration between open PRs

**Experiment** on the #44/#45 conflict:
- `git merge-tree` of the two heads has textual conflicts in 4 files.
- With conflicts resolved mechanically, the union of both PRs' changed tests (9 files, 566 tests, 144 s) **catches the
  semantic conflict**: `test_every_registered_hook_asks_the_switch_first` fails. It adds one spurious failure from the
  mechanical resolution.
- The full suite on that tree took 1894 s and gave 21 failures and 14 errors from local noise.

**Decision.** A scheduled (daily) and on-label workflow runs the changed-test union for each pair of open, green,
non-draft PRs. It posts the result to the PR as a check, not a comment, and never blocks. The merge train stays the
gate. A full-suite pre-merge train check is not added: 31 min for a noisy signal that the train gives anyway.

## 3. Items folded in

- **minted_id**: in (e), lane L2.
- **Replay gaps**:
  - the fan-out replay (`FanoutCycle.run`, `tests/replay/drivers/dev.py:1292-1339`) overrides `DevCycle.run` and drops
    the D32 extra rounds the single-lane run plays at Step 7 (`:1082`) and Step 14 (`:1106`);
  - `tests/replay/drivers/overnight.py` has no low-record logic.

  Running the fan-out with a low dev score blocks the Stop: "lane ... owes one more independent final_verification QA
  dispatch" (`hooks/lib/score_view.py:57-65`). Both fixes are inside `tests/replay/drivers/`, so lanes L14 and L15 start
  after #29 merges.
- **Hero-capture flake**:
  - root cause: samples are stamped `round(monotonic - t0, 4)` (`scripts/capture-hero-run.py:224`), but the marker is
    printed `"[%8.3f]"` (`:264`) and parsed back (`:269`), up to ±0.5 ms off;
  - a present sample under 1 ms before the real marker can sort after it, failing `:338` and `:342`;
  - deterministic reproduction: failure rate 50% / 30% / 15% / 7.5% for gaps of 0.1 / 0.5 / 1 / 2 ms, 0% with raw times;
  - fix: compare raw floats, and format only for display. No tolerance: a sample is stamped before its observation and
    the marker after the read, so a present sample later than the marker is a real failure.

  Lane L10.
- **xdist collection flake**: lane L11.

## 4. Net size

**Tests.**
- Deleted or rewritten: the 45 flagged functions. About 25 become behavioural tests that run the consumer; about 20 are
  deleted where a behavioural test already covers the behaviour, or the sentence has no consumer (each listed in the PR
  with where the lesson now lives).
- The hand-built CLI records in the 9 synthesizer sites in (e) are rebuilt from fixtures: no change in count.
- Added:
  - L1: about 6 (shape diff, loader, version advisory);
  - L2: about 8 (channel, minted_id, the `:624` survivor);
  - L4, L5, L12: about 6 each for the job scripts;
  - L6: about 10 lint unit tests;
  - L5: about 6 for the allowlist and score_view survivors;
  - L10, L11: 2 each;
  - L14, L15: 3 replay scenarios.
- **Expected net: about +15 test functions out of 5678 (+0.3%); collected tests about +20 out of 15253.** The 45
  prose-only tests drop to 0, and the 0 recorded-fixture hook tests rise to every hook test that reads the hook-output
  channel.

**Production code.** About +200 lines (`hooks/lib/command_span.py` +20, `tests/artifact_graph` +160, scripts +20). CI
scripts: about +450 lines (red-green 150, mutate 130, pair 40, recorder 60, shape diff 50).

**CI time.**
- PR path:
  - red-green +1 to 6 min, parallel;
  - mutation +5 to 10 min, parallel;
  - lint +5 s;
  - shape diff <1 s;
  - the 3 new replays add about 260 s + 260 s + 600 s of shard time. L13 places them on the shortest shards (1/6 at
    33 min, 6/6 at 36 min), so the critical path (57.9 min) does not grow.
- Hero and xdist flakes fixed: the about 2 reruns per 100 runs they cause go away.
- **Expected median run: unchanged at about 67 min**, plus up to 10 min of parallel CPU per PR.
- Pair check: off the PR path.

## 5. Lanes

**Rules for every lane.** One lane is one issue, one branch and one PR titled `P15-L<n>: ...`. Every fix lane
includes its own red-then-green evidence: the failing run on its base, then the passing run. That holds before L4
exists. The fences:

| Fence | Files | Until |
|---|---|---|
| #29 | `tests/replay/drivers/` | #29 merges |
| keystone PR | `hooks/lib/bash_write_targets.py`, `hooks/pretool-overnight-hook-guard.py` | the reviewer says it has merged or does not exist |
| parallel-launcher PR | `hooks/lib/hook_launch.py` (and #50's `tests/replay/launch_cost.py`) | same |
| settings-switch PR | `hooks/pretool-harness-switch-guard.py` | same |

`.github/workflows/baseline.yml` is owned by L13 alone. Lanes L4, L5 and L12 ship scripts and their tests, and L13
wires them in. L12 owns its own new workflow file.

| Lane | Issue | Owns (file scope) | Acceptance | Order |
|---|---|---|---|---|
| L1 | Recorded CLI fixtures and the upgrade canary (d) | new `scripts/cli-fixture-record.sh`; new `tests/fixtures/cli/**`; new `tests/cli_shapes.py`; new `tests/test_cli_fixture_shapes.py`; the root `conftest.py` loader fixture; one advisory line in `scripts/canary-verify.sh` | the fixture is recorded from the installed CLI (version in `CURRENT`); the shape diff exits 1 on a mutated copy and names each change; the advisory prints on a version mismatch and is silent on a match; no prompt text in the fixtures (`scripts/check-public-core.sh` green) | wave A |
| L2 | The hook-output channel as an artifact; minted_id (e) | `hooks/lib/command_span.py`; `tests/artifact_graph/check.py`, `pyscan.py` and their tests; `hooks/tests/test_command_span.py` | foreign-first scratch case fails on base, passes on head; two ids give `None`; the channel artifact exists with producer `cli`; a synthesizer whose shape differs is a violation; the `:624` stdout-fallback mutant is killed; the `check.py:1504` first-match search uses the same rule | wave B, after L1 |
| L3 | Synthesizers built from the recorded fixtures | `tests/replay/replay.py` (`:553`, `:771` only), `tests/replay/test_live_arming.py`, `hooks/tests/test_stop_command_gate.py`, `hooks/tests/test_requirement_round.py`, `hooks/tests/_fixtures_obligation_terminal.py`, `tests/test_do_partly_failed_close_route.py`, `tests/test_disposition.py`, `tests/_late_repair_fixtures.py` | every synthesized hook record's shape equals the fixture's (L2's check at zero for these sites); a replay plays the `hook_success` form and the /do span closes; the suite is green | wave B, after L1; beside L2 |
| L4 | Red-then-green job script (a) | new `scripts/ci/red-green.py`; its tests; `docs/` page for the `Red-test:` trailer | on 036d1ed's parent and head it reports the 2 red-then-green tests; on 6bf06147 with `Red-test: <id>` it reports red then green; a docs-only diff is exempt; `none: <reason>` is printed | wave A |
| L5 | Diff-scoped mutation script (b), and the known survivors | new `scripts/ci/diff-mutate.py`; its tests; tests that kill the `hooks/lib/allowlist.py:326-329` and `hooks/lib/score_view.py:28` survivors (in `hooks/tests/test_allow_grant_quoted_separators.py`, `hooks/tests/test_score_view.py`) | the bounds hold (≤40 mutants, timeout, `-x`); no `sys.path` index mutants; after the new tests, 0 survivors on those two files | wave A |
| L6 | Prose-only lint, check 7 (c) | `tests/lint/` (new check, its unit tests, the tree test) | fixture tests: one flagged, one exempt by a resolved consumer, one unresolved that fails closed, one structural assert not flagged; the tree test at zero once L7 to L9 land (until then it lists the open hits) | wave A; merges after L7, L8, L9 |
| L7 | Rewrite prose-only tests: /close, /commit and the dev artifact chain | `tests/test_close_command_text.py`, `tests/test_dev_artifact_chain_consumer_contracts.py`, `tests/test_commit_multi_repo_plan.py`, `tests/test_cleaner_discard.py`, `tests/test_cycle_records_commit_set.py`, `tests/test_late_repair_route.py`, `hooks/tests/test_close_stalled_stop.py`, `hooks/tests/test_close_rating_no_tool.py` | each flagged test runs its consumer, or is deleted with where its lesson lives; L6's lint reports 0 for these files | wave A |
| L8 | Rewrite prose-only tests: the no-phases charter (D33) | `tests/test_no_phases_agent_prompts.py`, `tests/test_no_phases_spec_command.py`, `tests/test_no_phases_spec_template.py`, `tests/test_dev_commands_no_phases.py` | the charter is shown by running the component that enforces it (the QA check or step script that fails a phased plan); 0 lint hits | wave A |
| L9 | Rewrite prose-only tests: the remaining files | `tests/test_paseo_daemon_ledger.py`, `tests/test_paseo_daemon_timers.py`, `tests/test_spec_update_command_contracts.py`, `tests/test_dev_question_relay_route.py`, `tests/test_ba_blast_radius_map_registry.py`, `hooks/tests/test_overnight_gitenv_failclosed.py`, `hooks/tests/test_doc_sync_index_notices.py` (`:724`, `:744` consumer resolution) | 0 lint hits; the two unresolved exempt tests resolve their consumer | wave A |
| L10 | Hero-capture flake (#19), root-caused | `scripts/capture-hero-run.py`; a new deterministic test | the reproduction fails on base for a 0.5 ms gap and passes on head; no tolerance added; "Verify headline claims" green | wave A |
| L11 | xdist collection flake | `hooks/tests/test_overnight_trace_yield.py` | two collections with different hash seeds give identical ids; the test's behaviour unchanged | wave A |
| L12 | Pair check between open PRs (f) | new `scripts/ci/pair-check.sh`; new `.github/workflows/pair-check.yml`; its test | on #44 and #45's heads it reports the switch-first failure; scheduled and on label; never a required check | wave A |
| L13 | CI wiring | `.github/workflows/baseline.yml` | red-green job and mutation step run on PRs; red-green blocking; mutation report-only; the 3 new replays on shards 1/6 and 6/6; median run time not above the baseline + 2 min | wave C, after L4, L5 |
| L14 | Replay: fan-out low-record extra rounds | `tests/replay/drivers/dev.py` (`FanoutCycle.run`); `tests/replay/test_score_dispatch.py` | low dev: two `final_verification` QA dispatches per lane, the second free of the first's paths and verdict; Stop not blocked; `extra=skip` gives one refusal naming the lane | wave D, after #29 |
| L15 | Replay: low-record /dev-overnight cycle | `tests/replay/drivers/overnight.py`; a new replay test | per pipeline, the same counts (`commands/dev-overnight.md:580,753`); close-out passes (`hooks/stop-command-gate.py:428`); with a low QA score, each QA SubagentStart text demands the Codex debate | wave D, after #29 and L14 |

**Waves.**
- A: L1, L4, L5, L6, L7, L8, L9, L10, L11, L12, in parallel.
- B: L2 and L3, after L1.
- C: L13, after L4 and L5.
- D: L14, then L15, after #29.

L6 merges after L7, L8 and L9. **Done when:**
- the lint, the channel check and the shape diff are at zero;
- L13's jobs are green on master;
- the two open flakes have not failed in 20 runs.

## 6. Owner decisions

**O1. Re-recording the CLI fixtures in CI.**
- Background: recording needs the CLI and model access (about $0.03 and 30 s a run). CI has no key today.
- Options:
  1. locally only, on upgrade, prompted by the canary advisory;
  2. plus a weekly scheduled job with an API-key secret the owner adds;
  3. plus a run on every PR.
- **Recommendation: option 1 now.** The advisory and the shape-diff gate catch a changed shape the first time any
  session runs a new CLI. Option 2 only adds detection on days nobody upgrades, and it needs a secret and spend.

No other decision needs the owner. Each of (a) to (f) is decided by the experiments in section 2, per D18.
