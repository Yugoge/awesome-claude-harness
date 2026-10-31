# P1b, continued: the rules for the session that finishes it

Read this file first, then `prompts/P1b.md` in this directory in full. P1b.md is the phase specification; its rules hold except where this file overrides them.

## Budget and stopping rules (they take precedence over any wording in P1b.md that asks for open-ended checking)

- Build the rest of P1b as specified, run your acceptance tests, and record each command and its output in the PR.
- Do not run "verify again until a round finds nothing" loops. Run at most two self-check rounds over your own diff. A self-check round may only fix defects of medium severity or higher; list lower ones in the PR under "Out of scope, found".
- Do not regenerate the inventory or re-sweep it. Use the artifact check's own output on the branch.
- An independent review of your PR is done by the reviewer session; do not imitate it with your own multi-agent review.
- Effort (D26): what is left is about one day of work. Push after each commit, so the work survives a usage limit and progress is visible. If you hit a usage limit, resume the same work after the reset; do not start over.

## You continue P1b; you do not start it

Two earlier sessions built most of P1b and each hit its usage limit. Their work is pull request #8, head branch `claude/quirky-keller-cr679p`. The head is 8dd63fb (pushed 2026-10-30 22:20 UTC): 47 commits on master 2acc29b. The first two commits (277a50d, 3507c9b) come from the first session's branch `claude/p1b-producer-consumer-artifact-wupfqs`, which is superseded.

**Done**, by the commit subjects and the last session's report:
- rows 1-18;
- the replay framework and the pipeline drivers, including /merge, /push and /clean;
- the artifact check in its own CI job, sharded to fit E2's 1,500 s;
- violations of rules 4, 5, 6 and 8 down from 64 to 2, and rule 2 reduced;
- the latency work;
- /close and /commit reach their terminal with no new block;
- E4's kept copies for /close and /dev-overnight.

**Left.** The second session's last report (2026-10-30) is the source for this list. CI on ec21e1b passed the three baseline legs and all five artifact shards, in about 1,290 s. The final check failed only on known violations: the phase-2 blast-radius map, and /clean's report checks, which 8dd63fb has since moved.

The session also had two lanes half done and never pushed. They are lost; redo them:
- **Determinism:** the artifact check must give the same result run after run. Its run-to-run test failed. The lane touched tests/replay/trace.py, replay.py, sandbox.py and a new test_run_to_run.py.
- **The lock commit (7):** settings STOPGATE=block; delete the copies E4 kept that only a blocking G2 makes redundant; then the replays. The lane touched settings.json, G2, claude_home.py, the command texts, and their scripts and tests. Two open points belong to it:
  - scripts/orchestrator.sh's validity loop is now a leftover copy of that check, and step 7 deletes it;
  - deleting only the loop leaves the merge's `jq --slurpfile` failing on a removed report, and the artifact check would still count the script as deciding that fault. Settle both together.

The work, in order:
1. Determinism, then the last violation (the phase-2 blast-radius map). That violation touches the same check code, so it comes after determinism. The artifact check then shows zero violations.
2. The lock commit (7), as above.
3. Acceptance tests 1-21, shared with a helper session as below.
4. The PR body and the evidence comments, as P1b.md's "Branch and pull request" says.

Work out the exact state from the branch's commits, PR #8's body and comments, and one run of the artifact check. Work an earlier session left unpushed is lost; redo only what the list above needs.

## Rules that override P1b.md's branch rules

1. Base your work on the newest head of `claude/quirky-keller-cr679p`, never on `origin/master`. Its commits are this phase's work. The check "`git log --oneline origin/master..HEAD` must print nothing" does not apply. Never reset them away, rebase, amend or force-push.
2. Push to `claude/quirky-keller-cr679p`, so that PR #8 stays the one P1b pull request. The owner gives explicit permission for this branch even though your session was assigned another one.
   - Before every push, fetch that branch and merge it with a merge commit if it moved: a helper session may comment on the PR at the same time.
   - Do not open a second PR. Do not close PR #8.
3. Verify the earlier sessions' work only by one run of the tests their latest commits name. If that run fails, fix the cause in a new commit.
4. **Acceptance is shared.** After you push the lock commit, a helper session runs acceptance tests 4, 5, 14, 15, 17 and 21 on that head and posts each one as a PR comment headed `Acceptance <n> on <sha>`. You run 1-3, 6-13, 16 and 18-20, write the PR body, and link the helper's comments from it.
   - Fix every failure the helper reports, in a new commit.
   - After such a fix, re-run only the tests it affects.
5. In the PR body, under "Notes for reviewers", say that three sessions made the commits, and which ones each made.
