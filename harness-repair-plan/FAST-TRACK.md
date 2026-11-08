# Fast track: everything left, in five days (D27)

The owner's ruling D27 (2026-11-01, DECISIONS.md): "5天必须完成". The owner provides three high-quota accounts. Everything left after P1b runs on them in three parallel streams. Each bar the planner added was judged on its use: the useful ones stay, the waste goes.

## Streams

| Stream (account) | Phases, in order within the stream | Start from |
|---|---|---|
| A | P1c core, then P5 | the head of `claude/quirky-keller-cr679p` (PR #8) for P1c; `origin/master` for P5 |
| B | P2, then P4, then P10 | `origin/master` |
| C | P3, then P6, then P9; then P11 once every other phase is merged | `origin/master` |

**Merge order across the streams:** P1b → P1c → P2 → P3 → P4 → P5 → P6 → P9 → P10 → P12 → P13 → P11.
- P12 is `P12-SLIM.md`. P13 (D28) is `research/scoring-and-asking/phase-prompt.md`: P13-1 and P13-2 in parallel, then P13-3. Its four owner choices (`design.md` §7) are the owner's to make before P13 starts; until the owner answers, nothing is decided for them.
- D28 withdraws P9's scoring retirement: before #16 merges, it restores the scoring code block by block, as `design.md` §6.1 lists.
- Build in parallel now. Each phase is one PR, titled `<phase>: ...`.
- Before a PR merges, merge `origin/master` into it with a merge commit. Resolve conflicts by keeping both sides' behaviour.
- A stream starts its next phase on a new branch from `origin/master` as soon as its current PR is open. It does not wait for the merge.

**Branches.** Build a stream's first phase on the branch your session was assigned. For each later phase, create `repair/<phase>` (for example `repair/P5`) from `origin/master`; the owner allows these branches and pushes to them. Never push to master, to another stream's branch or to the planning branch.

The short prompts are `prompts/short/<phase>.md`. Where the rules below and a prompt differ, the rules win.

## Kept: these protect the result

1. **The artifact check stays at zero violations, with no exception list.** It is D24's enforcement, and P1b already brings it to green. Every PR keeps it green.
2. **P1c's replay suite runs in CI on every PR from its merge on.** It is D25's measurement: CI runs it, not the session. Before P1c merges, a PR needs CI green on 3.10, 3.11 and 3.12 and the artifact check green.
3. **Every acceptance test of the prompt is run, once, at the end, on the final head.** The PR shows each test's command and pass or fail; the raw output goes in a PR comment only on a failure. After a fix, re-run only the tests it touches.
4. **Decide by experiment (D18):** run the one experiment that decides the choice, and record the option taken with its key numbers.
5. **Live landing.** Where the prompt has a live-landing or real-home test, it is run: the owner's own home must take the change with no step (D19).
6. **One self-check round over your own diff,** fixing defects of medium severity or higher. List the lower ones under "Out of scope, found".
7. **Privacy scan before every push;** no personal data.
8. **The reviewer reviews each PR once,** for medium severity or higher, and merges only on the owner's word. P11's irreversible step keeps its one AskUserQuestion confirmation.
9. **The PR body** has:
   - the first line "Owner steps: none.";
   - a summary;
   - release notes of a few lines on what changes in the owner's sessions;
   - the acceptance results;
   - one line per decision;
   - "Out of scope, found".

## Cut: waste

- The hand-written D24 table. The artifact check's CI output, which names the artifacts whose writers or readers changed, takes its place.
- Regenerating the inventory: the check derives it on every run.
- Multi-option experiment matrices, and raw experiment data in the PR.
- Coverage tables and any other proof that a prompt was followed line by line.
- "Verify until a round finds nothing" loops, and second self-check rounds.
- Re-running the full replay by hand inside the session: CI runs it.
- Re-checking file:line citations: the short prompts name files, and the session finds the place in the code.
- The PR "hand-off to later phases" sections, fault tables and per-artifact proof write-ups.
- The 63-sub-phase split (SPLIT-PLAN.md). Three streams on three accounts spread the usage instead (D26's aim).
- The cap of two or three parallel lanes. Use up to five lanes per session.

## Rules for every stream

- Ignore a prompt's start checks that wait for earlier phases: build now; merge in the order above.
- Push after every commit. If a session hits a usage limit, the owner continues it in a new session from the pushed branch; it never starts over.
- Ask the owner nothing (D18, D19).
- The owner's rulings D18-D26 stay as written:
  - one producer and at least one deciding consumer per artifact;
  - never fail;
  - unattended overnight;
  - a question only pauses;
  - /redev is /dev;
  - no filename-to-role table;
  - the owner runs nothing.
- The producer-side architecture holds: no new checks at /close or /commit, and no new state files.
- The rejected ideas stay rejected.

## Scopes

- **P1c core (stream A).** D25 as the owner's ruling words it, measured by a replay suite in CI on P1b's runner and drivers:
  1. A compliant run of each of the ten pipelines meets 0 gate blocks and 0 hook errors.
  2. Each fault D25 names is returned to its own producer and repaired at the next round with no human action. The faults: missing artifact, malformed artifact, stale-version report, git index.lock held, interrupted session, resume after a usage limit, one lane leaving an old report.
  3. There is no dead end: every blocking site is enumerated at test time and has an agent action that clears it, apart from /stop.
  4. Regression replays cover P1's fan-out, E1, N1 and V1-1/NV-1.

  Fix at the producer side what the suite finds. P1c rows beyond these four go to "Out of scope, found".
- **Every other phase:** every row and every acceptance test of its short prompt, under the rules above.

## Schedule

| Day | Work |
|---|---|
| 1 | P1b merges; streams A, B and C start |
| 2-4 | Each stream builds its phases; PRs merge in order as they are ready |
| 5 | Stream C runs P11 once every other phase is merged, after the owner confirms |

At the end of day 2 the reviewer tells the owner whether five days hold and which stream is behind.
