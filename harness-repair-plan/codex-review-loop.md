# The Codex review loop: one complete pass, no loops on nits, Claude disputes (D31)

Owner's ruling D31 (DECISIONS.md). Lanes L2 and L3 of P12 apply this to the files they own; it changes prompt text only.
No new hook, gate or state file. The field's experience behind these rules: `research/industry-2026-11-09.md` §4.

## What is wrong today (train 2 head, 99b4d69 / a99f32d)

- `commands/close.md` Step 2, `--codex`: Codex answers `CODEX: YES` or `CODEX: NO`, and a NO must list 2-5 "flip"
  items (line 220). Branch 3 (line 277) routes every flip item back to its producer; a fresh QA round then asks Codex
  again from scratch, which can list 2-5 new items. Nothing limits a re-review to the earlier items, and nothing ends
  the loop. The Codex prompt also asks it to "Flag any cleanliness/style violations introduced by THIS diff".
- `templates/prompt-includes/codex-consultation.md` (`/dev --codex` and its variants): Codex is asked to challenge
  adversarially for over- and under-engineering, missed edge cases, regression risk and scope drift, each with a
  `PROPOSED_FIX`; the agent must "apply the fix or explain specifically why you disagree". Classes are only blocker,
  major and observation_only: there is no class for "real but not worth it" or "out of scope". Applying is cheapest.
- `commands/commit.md` Step 5, `--codex`: "A substantive codex REJECT flips you to REJECT": Codex has a veto, and QA
  cannot dispute it. A parse failure scans the raw output for words such as `NO`, `should not` or `wrong`, which
  ordinary prose contains.
- `commands/codex.md`'s "Calling Protocol" (Rules 1-4: declare the requirement; no nitpicks; the caller classifies,
  Codex never sets the verdict; the requirement wins) is right, but none of the three pipeline prompts carries it.

## The rules (one shared text, read by every Codex call in the pipeline)

1. **One home.** The Calling Protocol moves into one shared include that `/dev` and its variants, `/close`, `/commit`
   and `/do` all read. Every Codex prompt starts with its prelude: `USER REQUIREMENT`, `SCOPE`, `OUT OF SCOPE`.
2. **Running first.** Each finding names a realistic trigger (the input or path, in the stated use, that hits it), its
   consequence and a `PROPOSED_FIX`, and gives its severity last, after the description:
   - `blocker`: it does not run, or the requirement fails on its main path;
   - `high`: a real defect on a path the requirement uses;
   - `medium`: a real defect on a realistic secondary path;
   - `edge`: it needs an unusual input or state the requirement does not name;
   - `style`: cleanliness of this diff.
3. **One complete pass.** The first Codex call on an artifact reviews everything in scope at once, style of this diff
   included, and returns one full list. Only blocker, high and medium with a realistic trigger send work back. The
   producer fixes this diff's `style` items in the same rework when each is small; otherwise they are listed. `edge`
   items are listed. Neither ever starts another round.
4. **Re-review verifies, it does not re-audit.** A later round gives Codex its earlier list and the diff since. It
   reports, for each earlier item, fixed or not, and only new blocker or high defects that the fix itself introduced.
5. **Claude disputes.** Before acting, the agent classifies every finding as in_scope_real_bug, in_scope_minor,
   out_of_scope or nitpick, with a one-line reason. Rejecting is as valid as applying. A finding without a realistic
   trigger is rejected. To apply a fix the agent states what the change adds and which failure it prevents; it rejects
   a fix larger than the risk it removes, or one that widens the scope. An out_of_scope finding is listed, never fixed.
6. **The loop ends without a person.** `/close`'s flip items are only blocker, high and medium findings with a trigger.
   Rounds 2 and 3 are re-reviews (rule 4). What is still open after round 3 and below blocker goes to the close
   report's follow-up list, and the cycle closes; a remaining blocker is routed as today.
7. **No veto.** In `/commit`, a Codex REJECT is a finding QA classifies under rule 5, not a verdict; only blocker or
   high findings (a secret, junk, broken syntax) make QA reject. On a parse failure QA asks Codex once more for the
   verdict line; if that fails too, QA's own verdict stands with a note, as for a quota failure. The secret and residue
   guarantees stay with the pre-commit guard and the privacy engine, which do not depend on Codex.

## Acceptance

- Each of the three pipeline prompts reads the one shared include; no copy of the protocol remains elsewhere.
- A replay with a stub Codex that returns one blocker plus five style and edge items: the producer is re-dispatched
  once, the second round only checks the blocker, and the cycle closes with the rest listed.
- A replay with a stub Codex that returns a new item on every round: the cycle closes after round 3.
- A replay of `/commit --codex` where the stub Codex rejects for a style reason: the commit is approved, with the
  finding classified.
