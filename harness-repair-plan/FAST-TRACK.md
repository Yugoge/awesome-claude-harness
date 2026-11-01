# Fast track: everything left, in five days (D27)

The owner's ruling D27 (2026-11-01, DECISIONS.md): "5天必须完成". Everything left after P1b is finished within five days.

That is possible only by cutting the bars the planner added, and by running the work in parallel on several accounts. The owner's rulings stay; only planner-added process is cut.

**Workstreams.** One session per workstream, each on its own account, all started at once:

| Workstream | Phases (short prompts) | Base | Merge order |
|---|---|---|---|
| P1b | PR #8, being finished under prompts/P1b-continue.md | its branch | 1 |
| WS1 | P1c, core only (below) | PR #8's head; merge `origin/master` once P1b merges | 2 |
| WS2 | P2 | `origin/master` | 3 |
| WS3 | P3 and P4 | `origin/master` | 4 |
| WS4 | P5 and P6 | `origin/master` | 5 |
| WS5 | P9 and P10 | `origin/master` | 6 |
| WS6 | P11 | `origin/master` once WS1-WS5 are merged | last (day 5) |

The short prompts are `prompts/short/<phase>.md`. A workstream does its phases' rows and acceptance tests under the rules below; where the rules and a prompt differ, the rules win.

## Rules for every workstream (they override the prompts, SPLIT-PLAN.md and D26's one-day cap for these five days)

1. **Start now.** Ignore the prompt's start checks that wait for earlier phases. Start from the base above, and merge `origin/master` into your branch (a merge commit) every time it moves. Resolve conflicts by keeping both sides' behaviour. Your PR is merged in the order above, after the ones before it.
2. **One PR per workstream**, titled with its phases, for example `P3+P4: ...`. Its body has:
   - the first line "Owner steps: none.";
   - a summary;
   - each acceptance test's command and its result (raw output in PR comments when long);
   - one line per decision you took;
   - "Out of scope, found".
3. **Cut paperwork.** Drop the D24 table, coverage tables, inventory regeneration and the PR "hand-off" sections. The artifact check's own CI output stands in for the D24 table.
4. **Cut experiments to one run.** Settle each "decided by experiment" item by the cheapest single experiment that decides it. Record it in one line. No matrices.
5. **Zero targets become ratchets.** Where a check must reach zero violations or zero exceptions, record the count at your head and make CI fail only if the count rises. Lower it where your rows touch the code.
6. **Speed over cost.** Use up to five parallel lanes in a session. Run the acceptance tests once, at the end, on the final head; re-run only what a fix touches. Run one self-check round, fixing high-severity defects only.
7. **Push after every commit.** If you hit a usage limit, the owner moves the work to a new session on another account. That session continues from your pushed branch and never starts over.
8. **Merge gate.** Until WS1 merges, a PR merges with CI green on 3.10, 3.11 and 3.12 and the artifact check not above its ratchet. After WS1 merges, P1c's replay suite must be green too. The reviewer reviews each PR once, for high-severity defects only, and merges on the owner's word.
9. **Ask the owner nothing** (D18, D19). P11's irreversible step keeps its one AskUserQuestion confirmation.

**What stays, unchanged**, because these are the owner's own rulings:
- D18 to D25: producer and consumer per artifact; never fail; unattended overnight; a question only pauses; /redev is /dev; no filename-to-role table; the owner runs nothing;
- the producer-side architecture: no new checks at /close or /commit, no new state files;
- privacy;
- the rejected ideas stay rejected.

## Workstream scopes

- **WS1, P1c core: D25 exactly as the owner's ruling words it.** A replay suite in CI on P1b's runner and drivers:
  - (1) a compliant run of each of the ten pipelines meets 0 gate blocks and 0 hook errors;
  - (2) each fault D25 names (missing artifact, malformed artifact, stale-version report, git index.lock held, interrupted session, resume after a usage limit, one lane leaving an old report) is returned to its own producer and repaired at the next round with no human action;
  - (3) no dead end: every blocking site is enumerated at test time, and each has an agent action that clears it, apart from /stop;
  - (4) regression replays for P1's fan-out, E1, N1 and V1-1/NV-1.

  Fix at the producer side what the suite finds. A fix in a file another workstream rewrites goes to that workstream as a PR comment. P1c rows beyond these four items are cut.
- **WS2, P2:** every row of `prompts/short/P2.md`.
- **WS3, P3 then P4:** every row of both prompts, P3's in commits before P4's.
- **WS4, P5 then P6:** every row of both prompts. P5's arming commit is the last commit of the P5 part.
- **WS5, P9 then P10:** every row of both prompts. P10's deletions come after P9's prose pass.
- **WS6, P11:** every row. Its history rewrite runs only after the owner confirms it with one AskUserQuestion that names the concrete effects.

## Schedule

| Day | Work |
|---|---|
| 1 | P1b merges; WS1-WS5 start in parallel |
| 2-4 | WS1-WS5 build; their PRs merge in the order above as each is ready, each merging master first |
| 5 | WS6, P11, after the owner's confirmation |

The reviewer reports at the end of day 2 whether the five days hold, and names which workstream is behind.
