You are the integration lane of phase P12 of the owner's harness repair plan in this repository
(Yugoge/awesome-claude-harness): the "Integration" row of P12-SLIM.md's lane table. Per FAST-TRACK.md ("Accounts"),
this lane runs on a Max or Ultra account, not the main account.

Plan files: run `git fetch origin claude/vibrant-hopper-bazrn8`, then read, under harness-repair-plan/:
- P12-SLIM.md: its rules for every lane bind you, and its "Done when" is your bar;
- FAST-TRACK.md, DECISIONS.md and prompts/_common.md;
- the two audits under audit/2026-11-08/.

Start checks (on a failure stop, and say why in your session output; never ask the owner):
- The lane PRs titled `P12-L1: ...` to `P12-L6: ...` are all merged into the same base branch. That branch is the P12
  train branch. It starts at P12's base: the sha in the newest comment `P12 base <sha>` on the second merge train's
  PR (#14 until that PR exists).
- L7 is not yet started. It begins after you merge (P12-SLIM.md).

Work on the P12 train branch, in this order:
1. Cross-lane requests: do each change a lane PR's comment asks the integration lane for, because it needs a file
   another lane owns (P12-SLIM.md rule 1). Otherwise answer on that lane's PR why not.
2. Follow-ups: apply the items for your files in the comment "Follow-ups after train 2" on the second train's PR.
3. Registrations: make settings.json register exactly the hook files L4 and L5 left.
   - No registration points at a missing file.
   - A hook a lane replaced is unregistered, and its file stays as an exit-0 `# STUB:` file for one phase (D15).
   - Merged gates use wide matchers and dispatch on tool_name inside (hooks-audit.md §7.3).
   - The tracked settings.json stays the clean public form, with no machine value (D11, D12), and the settings render
     check (`scripts/install/render-settings check --staged`) passes.
4. Ledger: docs/ENFORCEMENT-LEDGER.md has one row per registered hook and per rule. Each row states its real mode
   (block, advisory or off) and its switch. Rows of removed hooks go, or are marked as stubs.
   `check-enforcement-evidence.py --ledger` and `--claims` pass, and so does L6's check that a prompt calls a hook
   "blocks" only when the ledger says it blocks.
5. CLAUDE.md, slimmed by P12-SLIM.md's prompt principles (rule 4):
   - a rule a hook enforces gets one line pointing to it, with its strength as the ledger states it;
   - one home per rule;
   - no history, no task ids, no dead references;
   - at most three emphasis words.

   Keep the date block, every production lesson, and the meaning of P9's Hook Discipline rewrite (D20, D23, D25). Your
   PR carries rule 2's table: each removed CLAUDE.md rule, with where its lesson now lives.
6. INDEX.md and the README stats: re-measure the counts on the train head (hooks, commands, agents, prompt lines).
   `scripts/verify-claims.sh` passes.
7. Step-heading sync: the step strings in scripts/todo/*.py match the Step headings of the commands L1 and L2 slimmed.
   check-todo-md-sync is silent (or its CI test is green, if L4 moved it into tests).
8. L6's CI step: switch it on now that L1 to L5 have landed, if L6 left it off, and its lint checks pass on the train head.
9. Merge `origin/master` into the train branch with a merge commit, keeping both sides' behaviour (FAST-TRACK.md). Then
   run CI once: 3.10, 3.11 and 3.12, P1c's replay suite, and the artifact check at zero violations.
10. Check P12-SLIM.md's "Done when", each against P12's base:
    - prompts (commands/, agents/, CLAUDE.md) at least 40% shorter;
    - about 20 hook files or fewer;
    - every lesson mapped to a home (the lane tables plus yours);
    - the replay suite, the artifact check and CI green.

    L7's bars belong to L7.

Pull request: one PR from the P12 train branch into master, titled `P12: slim the prompts and consolidate the hooks`. Its
body has:
- `Owner steps: none.` as the first line;
- a summary, and release notes on what changes in the owner's sessions;
- the links to the six lane PRs;
- each "Done when" measure, before and after;
- the cross-lane requests done;
- the rules added and retired;
- one line per decision;
- "Out of scope, found".

When CI is green and "Done when" holds, mark the PR ready and stop. The reviewer merges it, on the owner's word
(FAST-TRACK.md bar 8). P13-2 and the train 2 follow-ups run beside P12 from the same base and merge after it, so
leave them out of your branch.

DO NOT:
- edit a lane's files, except for a cross-lane request on its PR, a follow-up item, or the Step-heading sync;
- change what a hook decides: behaviour stays the same unless an audit finding says it is wrong (P12-SLIM.md rule 3),
  and the registrations follow what L4 and L5 decided;
- delete a hook file in the same change that unregisters it;
- merge any PR, push to master, or rewrite published history;
- start L7 or P13, or touch harness-repair-plan/;
- add a personal value (run check-public-core.sh before every push), or ask the owner anything.

Push at most once every 30 minutes (P12-SLIM.md rule 7), and always before you stop. If something blocks you, say so
in a comment on the P12 PR.
