# P1b, continued: the rules for the session that finishes it

Read this file first, then `prompts/P1b.md` in this directory in full. P1b.md is the phase specification; its rules hold except where this file overrides them.

## Budget and stopping rules (they take precedence over any wording in P1b.md that asks for open-ended checking)

- Build the rest of P1b as specified, run each acceptance test, and record its command and output in the PR.
- Do not run "verify again until a round finds nothing" loops. Run at most two self-check rounds over your own diff. A self-check round may only fix defects of medium severity or higher; list lower ones in the PR under "Out of scope, found".
- The inventory you generate in step 1 is evidence for this PR. Generate it once on your base and correct it only where an acceptance test or a deletion depends on a cell; do not re-sweep it.
- An independent review of your PR is done afterwards by the reviewer session; do not imitate it with your own multi-agent review.
- If you hit a usage limit, resume the same work after the reset; do not start over. Push your branch after each commit, so the work survives a usage limit and progress is visible in the repository.

## You continue P1b; you do not start it

Another session built the first part of P1b and hit its usage limit. Its work is on branch `claude/p1b-producer-consumer-artifact-wupfqs`, head 3507c9b (pushed 2026-10-28 04:10 UTC). It has two commits on top of master 2acc29b:

- 277a50d "P1b: hook state lives under harness_state_dir() on both sides; the guard reads the -F file the commit names" (37 files, +332/-115);
- 3507c9b "P1b: dead outputs and dead reading branches go" (108 files, +511/-4481).

That session reported both commits tested. It planned five more commits, then the acceptance tests and the PR.

These rules override P1b.md's branch rules (its "Branch and pull request" section and the shared "Planning documents" paragraph):

1. Fetch that branch. If it has commits after 3507c9b, they are the same phase's work: use the newest head.
2. Base your work on that head, not on `origin/master`. Point your assigned branch at it; this is a fast-forward of master, not a rewrite. The check "`git log --oneline origin/master..HEAD` must print nothing" does not apply: the commits it prints are this phase's work. Never reset them away, rebase, amend or force-push them.
3. Push only to your own assigned branch, or to `repair/P1b` if you have none or were assigned the planning branch. Do not push to `claude/p1b-producer-consumer-artifact-wupfqs`. Open the one P1b pull request from your branch.
4. Read the two commits' messages and diffs and match them to P1b.md. Work out which rows, experiments (E1-E14) and corrections they cover and which remain. Do not redo what they did. Verify them only by one run of the tests their messages name; if that run fails, fix the cause in a new commit.
5. The earlier session's baseline map measurement was running in the background and is probably lost. If its result is not in the branch, regenerate it once on master 2acc29b, the base of the first commit, as P1b.md's step 1 says.
6. In the PR, under "Notes for reviewers", say that an earlier session made 277a50d and 3507c9b, and list what you took from them as done.
