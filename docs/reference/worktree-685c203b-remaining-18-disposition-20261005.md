# Worktree `overnight-20260809-685c203b`: disposition of the remaining 18 items

**Source**: a qualitative, item-by-item analysis of the 18 items still outstanding in worktree `overnight-20260809-685c203b` (session `685c203b-2819-47f4-b612-f60f285a1602`) — the 5 test files from this same worktree already landed, byte-identical, in commit `16963b604`; these 18 are everything else. Verdicts: **3 land / 11 discard / 4 need human sign-off**.

## Prominent note 1: all 16 modified items are uncommitted bytes — the worktree itself IS their only recovery coordinate

**None of the 16 `M` (modified) items below have ever been committed.** Their content exists only as uncommitted changes in the worktree's working tree. There is no commit sha, no checkpoint ref, no reflog entry that can recover any of them independently of the worktree. Per the standing discard-with-recovery-coordinate rule, for these items **the worktree path itself is the recovery coordinate** — there is no other one.

**This worktree must not be deleted or otherwise discarded until every item below that isn't already landed has either been landed or deliberately preserved some other way.** The 11 "discard" verdicts below are a judgment that the *content* isn't worth landing, not a statement that the worktree can now be removed — the 4 "needs sign-off" and any future-reconsidered items still depend on it existing.

## Prominent note 2: the `1af2a2dcb` checkpoint is fragile as a recovery coordinate — verified, not assumed

Independently re-verified this round (this is about a *different* worktree's checkpoint — `overnight-20260810-019fe5c1`, `1af2a2dcbb4a119f01f956e32617dfec9bc0e5a9` — recorded here because the operator asked for it in writing alongside this disposition):

- `git branch -a --contains 1af2a2dcb` → empty. **Not reachable from any local or remote branch.**
- `git for-each-ref --contains 1af2a2dcb` → exactly one ref: `refs/checkpoints/worktree-overnight-20260810-019fe5c1`. No other ref holds it.
- `git reflog --all` → zero hits for this sha.

A single checkpoint ref with zero reflog backing is a thin margin: deleting or force-updating that one ref, with no reflog entry anywhere to fall back on, would make this content unrecoverable. Recorded in writing for that reason.

## The 18 items

### Land (3) — paseo/playwright tool-parity fix, hunk-cut

These three are the fix for the paseo/playwright tool-parity gap that two independent test files hit in earlier rounds tonight (commit `16963b604`'s diagnosis). Landed as surgical hunks, not whole-file — master has since added its own improvements to these files (a `sys.path.insert` + `harness_state_dir` import, and migrating the pid-file path off `/tmp` into that managed state directory, in the two watchdog scripts) that a whole-file landing would have destroyed. Zero line-level overlap between the worktree's hunks and master's additions was independently confirmed this round via `git apply --check` (clean on `settings.template.json`; the two `.py` files failed `git apply` only on *context*-line drift caused by master's unrelated nearby insertions, not on any actual overlapping edit — confirmed by direct inspection of both versions).

| Path | What was kept from the worktree | Recovery coordinate |
|---|---|---|
| `hooks/posttool-runcode-watchdog.py` | `Matcher:` docstring line extended to paseo; `RUN_CODE_TOOLS` frozenset constant added; guard changed from equality to set-membership | Landed in this commit; worktree path (uncommitted bytes) is the only prior coordinate |
| `hooks/pretool-runcode-watchdog.py` | Same family of changes | Same |
| `settings.template.json` | One `"mcp__paseo__*"` allow entry added; two matcher patterns extended from playwright-only to playwright+paseo | Same |

Verified before/after with `hooks/tests/test_runcode_watchdog_aliases.py`: 4 passed / 3 failed before → 6 passed / 1 failed after. Both paseo-specific failures flipped to passing. The one remaining failure (`test_template_and_live_settings_preserve_full_alias_parity`) is the pre-existing, already-documented `settings.json`-vs-rendered-`settings.template.json` drift on unrelated keys (env vars, hook lists) — unrelated to this fix, unchanged by it.

### Needs human sign-off (4) — not touched this round

| Path | Why it needs sign-off |
|---|---|
| `settings.json` | The worktree version downgrades 11 `deny` entries to `ask`, including `Edit(.claude/hooks/**)` (editing the security hooks themselves) and `Edit(.claude/settings.json)` (editing the permission table itself) — a self-escalation path. Must not be landed without explicit human review. |
| `policies/tool-policy.v1.json` | Flagged for sign-off by the same analysis; not independently re-examined this round. |
| `hooks/lib/bash_write_targets.py` | Ties to the variable-resolution capability gap documented separately (`docs/reference/bash-write-targets-capability-gap-20261005.md`) — filling it makes a security hook start spawning a subprocess fed by model-produced input, a design-level change needing sign-off, not something to land on green tests alone. |
| `scripts/write-qa-mode.sh` | Flagged for sign-off by the same analysis; not independently re-examined this round. |

Recovery coordinate for all four: the worktree path (uncommitted bytes; no commit coordinate exists for any of them).

### Discard (11)

Judged discard by this round's qualitative analysis. Individual reasons were not broken out item-by-item in the instruction for this round, and this desk has not independently re-verified the discard rationale for each — only the 3 "land" items' zero-overlap claim and the two checkpoint-fragility facts above were independently re-checked this round. Recovery coordinate for every row: the worktree path (uncommitted bytes; no commit coordinate exists for any of them).

| Path |
|---|
| `commands/restart.md` |
| `hooks/lib/subagent_restart.py` |
| `hooks/posttool-restart-sendmessage.py` |
| `hooks/pretool-bash-safety.sh` |
| `hooks/tests/test_bash_safety_context_rules.py` |
| `hooks/userprompt-restart-authorize.py` |
| `scripts/restart-subagents.py` |
| `tests/generated/manifest.json` |
| `tests/test_restart_command.py` |
| `.boundary-probe-rw` (untracked) |
| `.claude/overnight-contract-685c203b-2819-47f4-b612-f60f285a1602-cycle1.json` (untracked) |

## A separate master-side capability gap, found in the same analysis (unrelated to these 18 items)

Master currently has **no removal policy at all** — neither the worktree's own implementation (which failed its own cycle's terminal QA, from lane `LANE-POL`, and is correctly judged discard above) nor the `fail-closed` implementation landed on `origin/master` at `cf564cd7e`, nor that implementation's 22 removal-specific tests. Master's structural classification of removal-type commands is currently blank, not merely loose or strict in one direction. Cross-referenced in `docs/reference/harness-issues-backlog.md`; out of scope for this round's disposition, which covers only the 18 items above.
