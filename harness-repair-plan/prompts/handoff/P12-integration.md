You are the integration lane of phase P12 of the owner's harness repair plan in this repository
(Yugoge/awesome-claude-harness): the "Integration" row of P12-SLIM.md's lane table. Per FAST-TRACK.md ("Accounts"),
this lane runs on a Max or Ultra account, not the main account.

Plan files: run `git fetch origin claude/vibrant-hopper-bazrn8`, then read, under harness-repair-plan/:
- P12-SLIM.md: its rules for every lane bind you, and its "Done when" is your bar;
- FAST-TRACK.md, DECISIONS.md and prompts/_common.md;
- the two audits under audit/2026-11-08/;
- the lane hand-offs prompts/handoff/P12-L1.md to P12-L7.md, so you know what each lane hands you.

Base and the train branch:
- P12's base is the sha in the newest comment `P12 base <sha>` on the second merge train's PR (#14 until that PR exists).
  If it is not posted yet, stop and say so in your session output.
- The P12 train branch is `repair/P12`, at that sha. Whichever lane starts first creates it. If it does not exist on
  origin, create it at the sha and push it; if it exists, use it as it is. You work on `repair/P12` itself.
- Open the P12 PR now, as a draft, from `repair/P12` into master, titled
  `P12: slim the prompts and consolidate the hooks`, with `Owner steps: none.` as its body's first line. CI runs on it at
  every merge into the train.

Merging the lanes (L1 to L6):
- Every lane PR, `P12-L1: ...` to `P12-L6: ...`, targets `repair/P12`. L6's #21 is retargeted from master to it once
  the base is posted. Watch the lane PRs (subscribe to their activity where your session can).
- When a lane marks its PR ready for review, merge it into `repair/P12` with a merge commit, if all of these hold:
  - its base is `repair/P12`;
  - it merges without conflict;
  - CI is green on its head;
  - its body carries the lesson table (P12-SLIM.md rule 2).
- If one of them fails, say on that PR what is missing and leave it for the lane. The lane fixes it and marks the PR
  ready again.
- Merge L6 (#21) as soon as it is ready, so the other lanes can run the lint from `repair/P12`.
- Merge nothing else into `repair/P12`. P13-2 and the train 2 follow-ups run beside P12 from the same base, and merge
  into master after it. L7 starts after your PR merges, and targets master.

When L1 to L6 have all merged, work on `repair/P12`, in this order:
1. Cross-lane requests: do each change a lane PR's comment asks the integration lane for, because it needs a file
   another lane owns (P12-SLIM.md rule 1). Otherwise answer on that lane's PR why not.
2. Follow-ups: apply the items for your files in the comment "Follow-ups after train 2" on the second train's PR.
3. Registrations: switch settings.json to the hook files L4 and L5 left, as their PRs' registration changes give them.
   - In the same change, turn each replaced file they name into an exit-0 `# STUB:` file for one phase (D15).
   - No registration points at a missing file.
   - Merged gates use wide matchers and dispatch on tool_name inside (hooks-audit.md §7.3).
   - The tracked settings.json stays the clean public form, with no machine value (D11, D12), and
     `scripts/install/render-settings check --staged` passes.
4. Ledger: docs/ENFORCEMENT-LEDGER.md has one row per registered hook and per rule. Each row states its real mode
   (block, advisory or off) and its switch, including the rows that say `none` today (#21's description). Rows of
   removed hooks go, or are marked as stubs. `scripts/check-enforcement-evidence.py --ledger` and `--claims` pass.
5. CLAUDE.md, slimmed by P12-SLIM.md's prompt principles (rule 4):
   - a rule a hook enforces gets one line pointing to it, with its strength as the ledger states it;
   - one home per rule;
   - no history, no task ids, no dead references;
   - at most three emphasis words.

   Keep the date block, every production lesson, and the meaning of P9's Hook Discipline rewrite (D20, D23, D25). Your
   PR carries rule 2's table: each removed CLAUDE.md rule, with where its lesson now lives.
6. INDEX.md and the README stats: re-measure the counts on the train head (hooks, commands, agents, prompt lines).
   `scripts/verify-claims.sh` passes.
7. Step-heading sync: the step strings in scripts/todo/*.py match the Step headings of the commands L1 and L2 slimmed,
   using the changes L1 and L2 list on their PRs. check-todo-md-sync is silent (or its CI test is green, if L4 moved it
   into tests).
8. L6's CI step: delete its `if: ${{ false }}` line now that L1 to L5 have landed. `HARNESS_LINT=1 python3 -m
   tests.lint` reports nothing, and the step is green.
9. Merge `origin/master` into `repair/P12` with a merge commit, keeping both sides' behaviour (FAST-TRACK.md). Then run CI
   once: 3.10, 3.11 and 3.12, P1c's replay suite, and the artifact check at zero violations.
10. Check P12-SLIM.md's "Done when", each against P12's base:
    - prompts (commands/, agents/, CLAUDE.md) at least 40% shorter;
    - about 20 hook files or fewer;
    - every lesson mapped to a home (the lane tables plus yours);
    - the replay suite, the artifact check and CI green.

    L7's bars belong to L7.

The P12 PR's body has:
- `Owner steps: none.` as the first line;
- a summary, and release notes on what changes in the owner's sessions;
- the links to the six lane PRs;
- each "Done when" measure, before and after;
- the cross-lane requests and registration changes done;
- the rules added and retired;
- one line per decision;
- "Out of scope, found".

When CI is green and "Done when" holds, mark the P12 PR ready for review and stop. The reviewer merges it into master,
on the owner's word (FAST-TRACK.md bar 8). L7 (prompts/handoff/P12-L7.md) starts after that merge.

DO NOT:
- merge a lane PR that is still a draft, or any PR other than the lane PRs into `repair/P12`; the P12 PR is the
  reviewer's to merge;
- edit a lane's files while its PR is open, except as its PR asks; after the merges, only for a cross-lane request, a
  follow-up item, the registration switch or the Step-heading sync;
- change what a hook decides: behaviour stays the same unless an audit finding says it is wrong (P12-SLIM.md rule 3),
  and the registrations follow what L4 and L5 decided;
- delete a hook file in the same change that unregisters it;
- push to master, or rewrite published history;
- start L7 or P13, or touch harness-repair-plan/;
- add a personal value (run `scripts/check-public-core.sh` before every push), or ask the owner anything.

Push at most once every 30 minutes (P12-SLIM.md rule 7), and always before you stop. If something blocks you, say so in
a comment on the P12 PR.
