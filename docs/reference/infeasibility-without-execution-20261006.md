# An infeasibility judgment that was never executed is a hypothesis, not a finding

**2026-10-06.** `docs/reference/master-origin-reconciliation-gap-20261005.md` recorded five routes to reconcile a diverged branch with its remote, all five independently measured, and called the result a closed loop. It wasn't. A sixth, more direct route — just running `/push` and observing what happens — was never executed. Its outcome was reasoned out instead: the branch was seven commits behind, therefore a push would be rejected as non-fast-forward, therefore that route was BLOCKED too, same as the other five.

When `/push` was actually run the next day, it never got that far. It stopped one layer earlier — the push-gate token check inside the wrapper script itself, which refused before any network call reached the remote, for a reason that had nothing to do with the fast-forward question at all. The reasoned-out blocker remains, to this moment, untested.

## What actually happened, as evidence

- Five routes (an agent-issued merge, the `/merge` command, checking whether an existing local branch already reaches the remote tip, creating a new branch, and `/pull`) were run and their outcomes observed directly — real measurements, not predictions.
- The sixth route (`/push`) was not run. Its outcome was derived from one fact (behind-count = 7) via one inference (behind implies non-fast-forward implies blocked), and entered the record with the same confidence as the five that were actually tested.
- Run for real the next day: `push-analyst`'s own review flagged the non-fast-forward concern as a `warn`-severity risk — not blocking — and then `push.sh`'s push-gate check rejected the attempt (exit 3) for an unrelated reason (no valid push-gate token exists for this branch) before `git` ever contacted the remote. The reasoned conclusion and the measured outcome turned out to be about two entirely different layers.

## The criterion

**An action judged "infeasible," if it was never actually executed even once, is not a conclusion — it is a hypothesis wearing a conclusion's confidence.** The check is a single question, asked before any infeasibility verdict goes into a record: did this route actually get run, or was its failure only worked out? The first is evidence. The second, however carefully reasoned, is not — and it can be wrong in ways the reasoning itself gives no hint of, because the real blocker may sit at a completely different layer than the one being reasoned about.

## Cross-reference

See `docs/reference/master-origin-reconciliation-gap-20261005.md`'s 2026-10-06 correction for the specific case this criterion was extracted from, and `docs/reference/harness-issues-backlog.md` entry `#153` for the operational log entry.

## Follow-up (2026-10-06, same day): the same reasoning was right once and wrong twice

The non-fast-forward prediction in the companion record above has since been confirmed by an actual rejection from the remote — the reasoning that produced it turned out to be correct. That does not vindicate the method it came from. The same night, the same style of reasoning — deriving a blocker from adjacent facts instead of running the thing — produced two confident, wrong conclusions: a push attempt judged doomed by a fast-forward problem that, when actually run, turned out to be stopped by a missing authorization token instead; and a merge command judged unable to reach a remote branch, when what it actually does is never look for one in the first place, resolving to something else entirely. All three predictions felt equally solid at the time they were written down. Only one of three was right, and there was no way to tell which from the reasoning alone — only from running it.
