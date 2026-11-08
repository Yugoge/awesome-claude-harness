# P12: slim the prompts and consolidate the hooks, with every lesson kept

**Inputs** (read both first):
- `audit/2026-11-08/prompt-audit.md`: about 47% of the 25,436 prompt lines can go, plus 11 principles.
- `audit/2026-11-08/hooks-audit.md`: 80 hook files map to about 18, and it lists 15 lessons at risk.

**When.** P12 starts from the second merge train's head, the commit where P1b to P10 are all merged, which the reviewer names. It never starts from an older base, because P1b to P10 rewrite the same files.

**Order against P11.** P11 rewrites history, so it runs last, after P12 merges. No branch may be open while it runs.

## Rules for every lane

1. **Own only your files** (list below). If a change needs a file another lane owns, say so in a PR comment; the integration lane does it.
2. **Keep every lesson.** Your PR carries a table: each removed prose rule or hook → where its lesson now lives (a hook, a shared file or a test). Removing anything with no new home is a defect.
3. **Behaviour stays the same** unless an audit finding says it is wrong. P1c's replay suite, the artifact check (at zero) and CI on 3.10, 3.11 and 3.12 must be green.
4. **Prompt principles:**
   - a rule a hook enforces gets at most a one-line pointer;
   - describe a hook's real strength, as `docs/ENFORCEMENT-LEDGER.md` states it;
   - one home per rule;
   - variant commands state only their difference from /dev;
   - mechanical steps go in tested scripts, at most two Bash calls a step, no pseudo-shell;
   - no history, no task ids, no dead references;
   - no restating what a capable model does anyway;
   - at most three emphasis words per file.
5. **Hook principles:**
   - one gate decides each fact;
   - a hook whose output cannot reach the model is fixed or merged;
   - no state file has two writers;
   - hooks on the same event do not race;
   - nothing blocks the action that clears it.
6. One PR per lane, titled `P12-L<n>: ...`. Push at most once every 30 minutes. Ask the owner nothing.

## Lanes (disjoint files)

| Lane | Owns | Work |
|---|---|---|
| L1 | `commands/dev.md`, `dev-command.md`, `dev-overnight.md`, `redev.md`, `do.md` and their `scripts/todo/*.py` | Slim them. `dev-command.md` keeps only its difference from `dev.md`. `/redev` is documented as re-entering the harness in the same conversation without repeating the prompt, to save context. |
| L2 | every other file in `commands/`, plus new scripts under `scripts/steps/` | Slim them, and move the mechanical sequences into tested scripts. This covers `close.md`'s cross-call shell variables and `commit.md`'s undefined `route_finding`. |
| L3 | `agents/*.md`, plus new shared files under `agents/shared/` | Move the duplicated blocks into shared files read on demand: Codex consultation (12 copies), the cp-state contract (17 copies), give-up discipline (6 copies). Then slim each agent. |
| L4 | hooks: the 7 write guards, the dead and half-dead hooks, hooks whose output never reaches the model, the unreferenced files | Merge, fix or remove each, as `hooks-audit.md` maps it. |
| L5 | hooks: the 16 artifact checks (G1 to G4, lane watch, e2e, codex, cp, overnight file check), the bookmark and other multi-writer state, the same-event races | Consolidate into one gate per fact, as `hooks-audit.md` maps it. |
| L6 | new tests under `tests/lint/` and one CI step in `.github/workflows/baseline.yml` | Make the principles checked by CI, not by discipline. CI fails when:<br>- a prompt calls a hook "blocks" while `docs/ENFORCEMENT-LEDGER.md` says it warns or is off;<br>- a prompt names a file that does not exist;<br>- a block of 10 or more lines is repeated in two prompts;<br>- a file has more than 3 emphasis words;<br>- a registered hook can only exit 0 with stderr, so its output never reaches the model;<br>- a state file has two writers (the artifact check already derives writers).<br>Each check gets a test that fails on today's tree, and passes once L1 to L5 land. |
| Integration (the reviewer) | `settings.json`, `CLAUDE.md`, `docs/ENFORCEMENT-LEDGER.md`, `INDEX.md` and README stats, `check-todo-md-sync` inputs | After L1 to L6 land on the P12 train branch: registrations, the ledger, CLAUDE.md slimmed by the same principles, and the Step-heading sync. Then one CI run, and merge. |

**Done when:** prompts are at least 40% shorter; hook files number about 20 or fewer; every lesson maps to a home; and the replay suite, the artifact check and CI are green.
