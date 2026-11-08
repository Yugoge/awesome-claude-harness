You finish what streams A, B and C left out of phases P2, P4, P5, P6, P9 and P10 of the owner's harness repair plan in
this repository (Yugoge/awesome-claude-harness). Plan files: `git fetch origin claude/vibrant-hopper-bazrn8`, then
harness-repair-plan/FAST-TRACK.md, DECISIONS.md, P12-SLIM.md and prompts/short/<phase>.md.

1. Now: collect every item PRs #10, #12, #13, #14, #15 and #16 say is not done: "Out of scope, found", "Not in this
   head", deferred rows or acceptance tests, review findings still open. Classify each:
   (a) required, and code or tests: a row or acceptance test of its phase, or a review finding of medium severity or
       higher;
   (b) prose in a file a P12 lane owns (P12-SLIM.md's lane table): that lane applies it;
   (c) truly out of scope.
   The CLAUDE.md lines listed on #16 are the reviewer's, in train 2; leave them out. Post the list as a comment headed
   "Follow-ups after train 2" on the second merge train's PR (on #14 until that PR exists), with the (b) items grouped
   by lane. Update the comment if a later final head changes the list.
2. When "P12 base <sha>" appears on the second train's PR, start from that sha and do every (a) item, each with its
   test or acceptance run as its phase prompt states it. Open one PR titled "Train 2 follow-ups".

DO NOT:
- write code before "P12 base <sha>" appears;
- edit a file a P12 lane owns, unless an (a) item needs it; then say so on that lane's PR;
- drop or weaken an acceptance test, or ask the owner anything.

Push as soon as each item's tests pass. If something blocks you, say so in a PR comment.
