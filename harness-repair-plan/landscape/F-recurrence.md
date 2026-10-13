# F-recurrence — why the harness regrows (F1, F2, F3, F4)

Repository: `/home/user/awesome-claude-harness` at HEAD `09ab15b` (last commit 2026-10-08), 893 tracked files.
Method: read-only. Everything executed ran in a scratch copy under
`scratchpad/landscape-work/F-recurrence/` (`harness/` = copy of hooks/scripts/schemas/policies/settings.json,
`harness-f1a/` = the same copy with the F1.a prototype applied, `prod/` and `gitsem/` = throwaway git repos,
fake `HOME`, `CLAUDE_STATE_DIR`, `TMPDIR`, `PYTHONDONTWRITEBYTECODE=1`, `env -i`). GitHub run history was read
with `gh run list` (read-only). Prior evidence re-verified: problems.md X01, X03, X04, X07, X09, X10, X11, X12, X14,
X15, X16, X19, X69, X72, X75, X78, X85; wf2 themes RC5, C2, C4, C6, L1, L2, L4, L5, L7, L8, L9, L10, L14, SR-09,
hook-architecture P11. Corrections to that evidence are in §7.

Problem ids:
- **F1** agents can add but not remove (removal policy; junk gets committed).
- **F2** nothing pushes back (red CI, no size budget).
- **F3** live sessions edit the harness they run under; concurrent sessions/accounts write one tree.
- **F4** the 'record, don't fix' rule, plus every incident adds a rule or hook; rules never retire.

## 0. Summary

| id | what keeps it recurring | where (headline) | minimal fix (producer-side or feedback only) |
|---|---|---|---|
| F1 | The removal policy denies every `git rm` and `rm` for subagents even under `/do`, but lets the main agent under `/do` remove anything with no snapshot. The ruling "discard but recoverable" has no mechanical path. So junk is committed or `mv`-ed out of sight | `hooks/lib/bash_execution_boundary.py:3826-3862`, `hooks/pretool-bash-safety.sh:864-878` / `:1901-2019` / `:2751-2766` | F1.a: `git rm` without `-f` becomes PROVEN_SAFE_REMOVAL. Git itself refuses to delete anything that differs from HEAD (prototype: 17 test assertions + 6 matrix rows flip, nothing else). F1.b: rm of untracked, non-ignored, in-repo literal paths is allowed after the existing `write_checkpoint` snapshot, and the `/do` grant exits snapshot every removal. F1.c: the producer prompts use the new path (bulk analyst adds a third "discard" class, cleaner and /clean switch from archive to git rm) |
| F2 | CI runs only on human pushes (5 runs since 2026-07-16, all red, including 09ab15b). It aborts at collection and checks no size. The one growth signal never blocks. The close pipeline ignores existing debt by design | `.github/workflows/baseline.yml:10-19`, `:123-124`, `:163-187`; `hooks/subagent-stop-diff-check.sh:29-60` | F2.a: one ratchet script plus a repo-versioned budget file (6 numbers), run in CI before `Run tests` and by the existing G2 producer-stop gate for producers in a repo that carries the budget file. The budget is read from the upstream ref, so a producer cannot raise its own limit. F2.b: weekly `schedule` and `workflow_dispatch` triggers |
| F3 | Repo = live `~/.claude` (tmpfs), shared by 3 accounts. 85 of 188 commits since 07-17 touch hooks/settings. Hook edits go live with no behavioural check; the canary only runs at the NEXT SessionStart. Daemons stash, rebase and push the live tree. The bulk sweep plus `files_created` = all untracked bundle peers' half-done work, which led to 20 files / 6,292 lines of attribution machinery | `NESTED-REPO.md:7-11`; `scripts/canary-verify.sh`; `hooks/git-fswatch.sh:174-260,335-400`; `hooks/pull.sh:28,120`; `agents/changelog-analyst.md:215-218` | Under the status-quo decision, no move. F3.a: the G2 producer-stop gate runs py_compile, bash -n, the existing canary and a registered-path check when a producer changed harness hook/settings files. F3.b: fswatch and `/pull` skip pull/rebase/push on the harness home (user decision; D1 overlap). F3.c: A3 plus an optional live-peer exclusion in bulk mode |
| F4 | The user ruling "record, don't fix" has a scope condition that ended (a harness fix running in a worktree). The meta-rule "fix via harness, never AI discipline" turns every incident into a hook. BA can only `patch` or `redesign`, never `retire`. Guards are append-only. The template check is superset-only. Nothing carries an expiry | `docs/reference/harness-issues-backlog.md:3,27`; `docs/reference/paseo-daemon-teachings-20260910.md:115-125,278-288`; `agents/ba.md:20,44`; `agents/dev.md:794-798`; `scripts/verify-claims.sh:341-342` | F4.a: a `Review-by:` convention on hooks and CLAUDE.md rules, warned by the ratchet. F4.b: a `retire` verdict in BA, which also sets `removal_authorized`. F4.c: end the record-only rule's scope, name its consumer and cap the backlog by the docs budget. F4.d: symmetric template sync so retirements reach the published template |

None of the fixes touches /close or /commit consumption (out of scope by the user's architecture). Each fix is
one of three things: (i) the producer of a removal (the analyzer verdict, the snapshot guard, the producer prompts),
(ii) the existing G2 producer-stop gate gaining two checks it derives from the repo (no grammar change, no new
state file), or (iii) CI as the feedback loop.

## 1. Architecture framing (why these four are one loop)

Producer side: agents produce files (dev, test-writer, changelog-analyst in bulk), and nothing lets them un-produce
recoverably (F1). The ratchet that would make growth cost something does not exist, and CI does not run (F2).
Producers edit the very hooks that gate them, in a tree other sessions write too (F3). Every failure that results
becomes a new record or hook rather than a removal (F4). The loop measured since 2026-07-17: 349 files added and 2
deleted, +224,499 / -7,964 lines. The repo grew 120,457 → 327,900 lines; hooks/ alone holds 138,945 lines.

Under the binding architecture, correctness is established at the producer by hooks (G1-G5), and consumers only read
one disposition. The F fixes stay inside that frame:
- F1 gives every producer one recoverable removal primitive. It also gives the commit producer in bulk mode a
  "discard" outcome, so junk is neither committed nor left dirty.
- F2/F3 add two producer obligations to G2: "your diff keeps the repo within budget" and "your hook edit still
  runs". They are derived from repo files, so no obligation-grammar change and no new mutable state are needed.
- F4 changes rule producers (BA spec, hook headers, CLAUDE.md) so that retirement is an expressible output.

## 2. F1 — agents can add but not remove

### 2.1 Root cause
1. `hooks/lib/bash_execution_boundary.py` classifies every non-`--cached` `git rm` and every `rm`/`unlink` as
   FORBIDDEN_REMOVAL, whatever the target's state. Git's own guarantee is ignored: `git rm` without `-f` removes
   only tracked paths identical to HEAD, so it is recoverable by construction.
2. In `hooks/pretool-bash-safety.sh` the removal policy (:1901-2019) sits AFTER the main-agent `/do` exit (:864-878)
   and BEFORE the subagent `/do` exit (:2751-2766). Result: with `/do`, the main agent removes anything with no
   snapshot (`rm -rf .` exits 0). Subagents, who do the work under the Orchestrator-Only rule, can never remove, even
   under `/do`. This is the reverse of the 2026-10-04 ruling "你可以丢弃，但是要可恢复" ("you may discard, but it
   must be recoverable"). The only pre-removal snapshot facility (`_preclean_snapshot_guard`, :757-841) is wired
   for `git clean` only.
3. The only "removal" that passes is `mv` out of the repo (PROVEN_INERT). That is the least recoverable option:
   tmpfs, no record.
4. The pipelines then force a decision with no third option. The clean-tree requirements (`/merge` in_place;
   CLAUDE.md:49) and the bulk analyst's commit-or-skip classification lead to the 2026-10-05 "tree-to-zero"
   campaign: 55 commits, +68,324 / -1,198, 108 files added, 0 deleted, and 20 of the 55 subjects say "land".

### 2.2 Runtime verification (sandbox, full `pretool-bash-safety.sh`, product repo with tracked `stage`, untracked `untracked.txt`)

| command | main agent | subagent | main + /do | subagent + /do |
|---|---|---|---|---|
| `git rm stage` | rc=2 removal-policy FORBIDDEN_REMOVAL git_rm_worktree | rc=2 | rc=0 | **rc=2** |
| `git rm -- stage` | rc=2 | rc=2 | — | — |
| `git rm -n stage` (dry run) | **rc=2** | rc=2 | — | — |
| `rm untracked.txt` | rc=2 | rc=2 | rc=0, **no snapshot written** (`git for-each-ref` shows only refs/heads/master) | rc=2 |
| `rm -rf .` | — | — | **rc=0** | rc=2 |
| `mv untracked.txt /tmp/trash/` | **rc=0** | **rc=0** | — | — |
| `git stash push -u -- untracked.txt` | rc=2 (stash rule) | rc=2 | — | — |
| `git add -- stage` | rc=0 | rc=0 | — | — |

The other 8 registered Bash PreToolUse hooks (git-privilege-guard, bulk-commit-detector, claude-config-guard,
overnight-hook-guard, cp-state-write-guard, bash-views-guard, wrapper-userintent, block-branch-pr-worktree) all exit
0 on `git rm stage` from a subagent. `bash_write_targets.extract_bash_write_paths('git rm src/x.py')` returns `[]`,
so tool-policy never sees removal operands. **The removal policy is the single point.**

Git semantics (git 2.43.0, `gitsem/`): `git rm mod.txt` → "has local modifications", rc=1. `git rm staged.txt` → "has
changes staged in the index", rc=1. `git rm untracked.txt` → "did not match any files", rc=128. `git rm -r d` removed
the tracked `d/t.txt` and left `d/untracked.txt`. `git restore --staged --worktree` restores both removed files.

F1.a prototype (`harness-f1a/`, 25-line change to `_git_rm`): `git rm stage`, `git rm -- stage`, `git rm -r dir`,
`git rm -n stage`, `git -C /tmp/x rm -- a b` and `bash -c "git rm stage"` → PROVEN_SAFE_REMOVAL
`git_rm_head_recoverable`. `git rm -f stage`, `git rm -rf dir` and `git rm --force x` stay FORBIDDEN_REMOVAL.
`git rm stage; rm other` stays FORBIDDEN (rm). `git rm "$X"` stays UNRESOLVED. Test impact:
`pytest hooks/tests/test_bash_safety_context_rules.py hooks/tests/test_bash_execution_boundary.py` goes from 412 passed
(original) to 395 passed / 17 failed. All 17 are assertions that a non-forced `git rm` must BLOCK (listed in 2.3 row 27).
`hooks/tests/fixtures/pol_iteration5_qa_matrix.v1.json` has 6 rows (POL-I5-QA-0256, -0316, -0318, -0320, -0321,
-0322) whose `expected_hook_exit_code` would flip from 2 to 0. The full pol replay (~13 min) was not run.

### 2.3 Complete location inventory (F1)

| # | file:line | what is wrong |
|---|---|---|
| 1 | hooks/lib/bash_execution_boundary.py:3826-3862 (`_git_rm`) | Any `git rm` without `--cached` → FORBIDDEN_REMOVAL (:3862), including `-n/--dry-run` and the non-forced form that git guarantees is HEAD-recoverable. The parser already reads `-f/--force/-n` (GIT_RM at :1447-1450); only the verdict mapping lacks them |
| 2 | hooks/lib/bash_execution_boundary.py:2741-2744 | `rm`/`unlink`/`shred`/`srm` → FORBIDDEN_REMOVAL with no operands surfaced, so no caller can decide "snapshot then allow" |
| 3 | hooks/lib/bash_execution_boundary.py:3425 | `find -delete` forbidden (correct; listed for completeness, no change) |
| 4 | hooks/lib/bash_execution_boundary.py:3860, :3904 | The only PROVEN_SAFE_REMOVAL classes are `git rm --cached` and docker resource rm; there is no recoverable-filesystem class |
| 5 | hooks/lib/bash_execution_boundary.py (mv → PROVEN_INERT, reason `no_execution_boundary_requires_removal_authorization`) | `mv <file> /tmp/...` is allowed, so the one "discard" that passes is the unrecoverable-in-practice one (tmpfs, no record, no recovery coordinate) |
| 6 | hooks/pretool-bash-safety.sh:864-878 | Main-agent `/do` exit runs before the removal policy: under `/do` every removal passes. `_preclean_snapshot_guard` there (:875) snapshots only for `git clean`, so `rm -rf` of untracked or ignored work is unrecoverable |
| 7 | hooks/pretool-bash-safety.sh:1901-2019 | Removal policy: denies FORBIDDEN_REMOVAL / UNRESOLVED for subagents always and for the main agent without `/do`. The REASON text (:1970) offers no recoverable alternative |
| 8 | hooks/pretool-bash-safety.sh:2751-2766 | Subagent `/do` exit ("Grant exit 4 of 4") sits after the removal policy, so `/do` never releases removal for the role that does the work |
| 9 | hooks/pretool-bash-safety.sh:757-841 (`_preclean_snapshot_guard`) | The existing snapshot-before-discard primitive (write_checkpoint + recovery coordinate) is wired only to `git clean` (git_clean_guard.py rc 10). It is the obvious reuse point for rm |
| 10 | hooks/pretool-bash-safety.sh:1889-1899 | rm/mv of workflow state files denied (correct; keep) |
| 11 | hooks/pretool-bash-safety.sh:2682-2745 | Destructive `git clean` denied except under grants with snapshot (keep; shows the snapshot-or-deny pattern is accepted house style) |
| 12 | hooks/pretool-bash-safety.sh:432-441 | Legacy `/allow` pattern grants are firewalled for subagents; only the structured sentinel (:880-935) can release a subagent removal: one human round-trip per command |
| 13 | hooks/lib/checkpoint-core.sh:534 | Snapshot temp index uses `git add -A`, so ignored files are never captured; a snapshot-then-rm path must refuse ignored targets |
| 14 | hooks/lib/checkpoint-core.sh:322-345, :698-708, :795-804 | Every successful `write_checkpoint` calls `_checkpoint_rate_limited_push`, so a pre-removal snapshot would be pushed to origin (public repo) behind only a PII gate. Needs a no-push knob or D1's removal of the auto-push |
| 15 | hooks/posttool-git-checkpoint.sh:10, :53-60; settings.json PostToolUse matcher `Write\|Edit\|NotebookEdit\|MultiEdit` | Auto checkpoints fire only once 10 or more files are dirty and never after Bash, so there is no reliable recovery coordinate for a single junk file. The snapshot must be taken at removal time |
| 16 | hooks/auto-commit.sh:1-12; settings.template.json:772 | The Stop-time checkpoint is registered only in the template, not in live settings.json |
| 17 | agents/changelog-analyst.md:919-922 | Prescribes `git -C "${GIT_ROOT}" rm -- "<path>"` for deleted tracked files. The removal policy blocks exactly that command (contradiction; F1.a resolves it with no prompt edit) |
| 18 | agents/changelog-analyst.md:215-243 | Bulk mode has two classes only: commit or skip. Junk is either committed (e227a70 `stage` "probe-byproduct updates") or left dirty; there is no "discard" outcome |
| 19 | agents/changelog-analyst.md:39, :924-925 | Single-file `git add --` / `git rm --` staging is mandated; the `git rm --` half is blocked (see 17) |
| 20 | agents/cleaner.md:72-73 | "archive → Bash (mv)" and "delete → Bash (rm)": rm is blocked for every subagent; only the archive (move-and-keep) action works |
| 21 | agents/cleaner.md:161, :168 | "Never delete without explicit approved:true": the only approval is human (clean.md), on top of the hook deny |
| 22 | commands/clean.md:2 ("archive everything"), :70 (`docs/archive/YYYY-MM/`), :94-95 ("archive docs rather than delete") | The cleanup standard keeps every file tracked under a new path. Under the recoverable ruling, git history is the archive |
| 23 | commands/clean.md:4 (`disable-model-invocation: true`); settings.json:258 (`Skill(clean:*)` deny) | The one removal workflow is human-only; it can never run as part of a pipeline |
| 24 | policies/tool-policy.v1.json:347-385 (role `cleaner`) | Cleaner write targets exclude `/src/`, `/lib/`, `/tests/` and all harness dirs. Rm operands are not write targets, so this mostly blocks the cleaner's move/fix actions on exactly the code it should prune |
| 25 | agents/ba.md:38-51 (item 5 at :44) | "Rolling back >50 lines of code that the user previously approved" forces `needs_clarification` (human) for any removal of an approved mechanism, including git-recoverable ones |
| 26 | agents/dev.md:522-527 | `files_created` = every untracked path minus baseline (A3): stray scratch is declared as produced and staged |
| 27 | hooks/tests/test_bash_safety_context_rules.py:185, :206, :209, :293-321 (17 assertions); hooks/tests/fixtures/pol_iteration5_qa_matrix.v1.json rows 0256/0316/0318/0320/0321/0322 | Tests pin "non-forced git rm must BLOCK", so they freeze F1 in place; F1.a must flip them in the same change |
| 28 | CLAUDE.md:49 ("/push requires clean tree") vs commands/push.md:36 ("dirty worktree non-blocking"); commands/merge.md:61, :221 (in_place merge requires `git status --porcelain` empty) | Clean-tree demands plus no discard path leave "land it" as the only route to zero (D4 overlap for the CLAUDE.md/push contradiction) |
| 29 | scripts/check-file-references.sh:331, :347 | Any reference from commands/agents/scripts, including the generated INDEX/README listings, marks a file "cannot delete or archive"; the removal detector protects dead code (X04; generator owned by E2) |
| 30 | docs/reference/recoverable-discard-register-20261005.md:3-6, :13-18 | The ruling exists only as prose; 119 lines of paperwork were needed to discard 2 empty scratch files |
| 31 | .gitignore (194 lines; +70 / -11 since 07-17); hooks/session-gitignore-propagate.sh:7-12 | Junk is hidden with ignore rules instead of removed (E2 owns the .gitignore burden) |
| 32 | hooks/sessionend-scratch-sweep.sh:1-18 | Evidence that a trusted hook-channel deletion already exists (session-owned scratch outside the repo); in-repo junk has no equivalent |
| 33 | schemas/dev-report.v1.json, schemas/dev-report.v2.json, schemas/do-report.v1.json | No `files_deleted`; deletions only appear implicitly in `files_modified` via `git diff --name-only`. That is sufficient for staging, so no schema change is proposed (noted so nobody adds one) |
| 34 | hooks/pretool-git-privilege-guard.py:16-31, :179, :1532-1555 | Agent commits exist only as `auto-bulk:` (with a human-minted bulk sentinel) or a `/commit` grant, so junk sits in the tree until a human bulk sweep lands it (F1 × F3) |
| 35 | Git evidence | Since 2026-07-17: 349 A / 2 D (the 2 D are db52813, attribution machinery replaced by newer attribution machinery), +224,499 / -7,964. Monthly A/D: Jul 175/542, Aug 79/0, Sep 113/0, Oct 1-8 139/2. Junk landed: e227a70 (`stage`, still tracked), `.r05_part1-3.json`, `.claude/tmp-test-writer-gen-l7.py`; 2026-10-05 landings 859ebda (+2,213 "misleading-named scratch/report-shard artifacts as real content"), b108c16 (22 files, 121 failing / 19 erroring tests, from a worktree its own message calls "Permanently unclosable", while its recovery coordinate `refs/checkpoints/worktree-overnight-20260810-019fe5c1` already existed, so discarding would have been recoverable), 16963b6 (15 failing), 87ae3e4 (+6,047), c32d814 (+3,986) |

Locations: 35 rows (52 distinct file:line anchors).

### 2.4 Fix (F1)

**F1.a — `git rm` without `-f` is a recoverable removal (effort S).**
`hooks/lib/bash_execution_boundary.py` `_git_rm` (:3826-3862): track `-f/--force` and `-n/--dry-run` (short clusters
and long forms, which the existing GIT_RM spec already parses). Map them:
`--cached` → unchanged; `-n` or not forced → `PROVEN_SAFE_REMOVAL "git_rm_head_recoverable"`; forced →
`FORBIDDEN_REMOVAL "git_rm_worktree"` (unchanged). Update the 17 assertions and 6 matrix rows in the same commit. Add
golden cases for `-f`, `-rf`, `--force`, `-fr`, `--force=…` (stays denied), `--pathspec-from-file` (safe), and
wrapped forms (`command`, `env -i`, `bash -c`, `eval`). This needs no hook-ordering change, no new state, and one
file of logic. It directly enables changelog-analyst.md:919-922 and the cleaner.

**F1.b — untracked junk: snapshot then remove; `/do` grant exits snapshot every removal (effort M).**
1. Analyzer (:2741-2744): for `rm`/`unlink` whose every argument is literal and whose command is a single simple
   command (no `cd`, subshell or substitution), add `removal_operands` to the verdict JSON (optional field, same
   schema id). `shred`/`srm` stay plain FORBIDDEN (they destroy content before unlinking).
2. `hooks/pretool-bash-safety.sh`: generalize `_preclean_snapshot_guard` (:757-841) into a removal snapshot guard
   with two callers. (a) The removal-policy DENY branch (:1964-1970), for FORBIDDEN_REMOVAL with operands: resolve
   the hook-cwd toplevel and require every operand to sit inside it and outside `.git`; require
   `git check-ignore -q` to be false for each; for directories require
   `git ls-files -o -i --exclude-standard -- <dir>` to be empty; then `write_checkpoint "" "pre-removal snapshot:
   $COMMAND"`, print `recover: git show refs/checkpoints/<branch>:<path>` and allow. Any failure denies as today.
   (b) Grant exits 1 (:874-876) and 4 (:2756-2764): run the same snapshot for any removal (not only `git clean`)
   before `exit 0`, so `/do` removals become recoverable for every non-ignored target.
3. `hooks/lib/checkpoint-core.sh:322`: honor `CHECKPOINT_NO_PUSH=1` (one early `return 0`) and set it for
   pre-removal snapshots, so discarded junk is never pushed to the public origin. Alternatively depend on D1
   removing the auto-push.
Refs/checkpoints already exist (CLAUDE.md:47-49), so nothing new is created. Ignored files remain unrecoverable, so
they stay denied outside `/do` (see U-F1c for inside `/do`).

**F1.c — producers use the path (effort S, prompt-only).**
- agents/changelog-analyst.md:215-243: add class 3 "discard (recoverable)". A tracked byproduct → `git rm -- <path>`
  (F1.a). An untracked byproduct → `rm -- <path>` (F1.b snapshot). Never for a tracked file with content changes.
  Print `DISCARDED <path> — recover: <coordinate>` in place of the commit-or-skip choice for junk.
- agents/cleaner.md:72-73: archive becomes `git rm` for tracked files; delete stays rm (now snapshotted).
- commands/clean.md:2, :70, :94-95: the standard becomes "delete with git rm; git history and refs/checkpoints are
  the archive". /clean itself is kept (no retirement); only its standard changes.
- docs/reference/recoverable-discard-register-20261005.md: superseded by the printed recovery coordinate plus the
  commit message. The register can be removed by the E4 change once F1.b lands.

Depends on: A3 (stop declaring stray files as produced), D1 (checkpoint auto-push) if the no-push knob is not taken,
E1 (the one-off cleanup of existing junk is a human-merged PR because the live guards still apply until F1 lands).

Risks: F1.a makes recoverable deletion cheap, so an agent can delete a tracked file other work needs. It stays
recoverable from HEAD, and the staged deletion appears in the next diff for QA. F1.b deletes a live peer's untracked
scratch, but the snapshot keeps it. If the snapshot write fails, the existing fail-closed deny applies. Under F3
(live harness), `git rm` of a registered hook breaks every session immediately. F3.a's registered-path check at
producer Stop catches it, and F1.a does not change that the file is restorable from HEAD.

## 3. F2 — nothing pushes back

### 3.1 Root cause
1. CI is the only place a check could run on every change, but it triggers only on push/PR. Push is human-only
   (settings.json:277 `Skill(push:*)` deny; pretool-git-privilege-guard.py:28-31). The repo was pushed 5 times in 84
   days: `gh run list` shows 2026-07-26 (x2), 2026-09-05 (x2), 2026-10-08 (09ab15b), all `failure`. The last green
   run was 2026-07-16T18:24:15Z (3345d34).
2. When it runs it aborts at collection (`tests/test_tool_policy_inference_note.py:39-40`, C4), and every later step
   is skipped, including the only invariant checks.
3. There is no size, line, prompt-byte or hook-count budget anywhere (git grep over .github, scripts, tests: only
   latency/timeout budgets). The single in-pipeline growth signal (`subagent-stop-diff-check.sh`) counts insertions
   only, warns, never blocks and accepts a self-written justification.
4. The close pipeline deliberately ignores pre-existing debt (user ruling 1: close/commit only detect a failed
   cycle). Pushback therefore has to come from the producer or from CI, never from /close (consumer; out of scope).

### 3.2 Complete location inventory (F2)

| # | file:line | what is wrong |
|---|---|---|
| 1 | .github/workflows/baseline.yml:10-19 | Triggers `push` (master/main), `pull_request`, `workflow_call`; no `schedule`/`workflow_dispatch`, so CI cadence = human push cadence (5 runs since 07-16) |
| 2 | .github/workflows/baseline.yml:123-124 | `pytest hooks/tests tests -q --ignore=tests/generated` aborts at collection (C4), so 0 tests run and every later step is skipped |
| 3 | .github/workflows/baseline.yml:163-187 | The only "invariant" step is a zero-hit grep for 3 literal strings; no budget of any kind |
| 4 | .github/workflows/baseline.yml:189-207 | Public-core and verify-claims sit behind the red test step (never executed since run #47) |
| 5 | .github/workflows/baseline.yml:215-244 | The adversarial corpus and evidence gate are also behind it |
| 6 | .github/workflows/release.yml:19-31, :39-40 | Tag-only, reuses baseline; 0 runs ever |
| 7 | scripts/verify-claims.sh:84-189, :271-331 | Recomputes hook and helper counts and fails if README/ARCHITECTURE disagree, so docs must follow growth; it never caps it |
| 8 | scripts/generate-hero-status.py:2-13 | Called the "CI ratchet", but it byte-compares README status rows, not size |
| 9 | hooks/subagent-stop-diff-check.sh:20-33, :35-44, :46-60 | Growth warning: threshold 30 inserted lines over HEAD~5 plus the worktree, insertions not net, escape via self-declared `justification_for_overage`, `exit 0` always |
| 10 | scripts/gen-test-baseline.py; tests/baselines/default-run-failures.json (64 node ids); conftest.py:9-13 | A failure ratchet ("fails only on node-ids absent from the baseline") exists but is not wired into CI; C4.f plans to delete it (private markers in ids). No conflict: F2.a does not use it |
| 11 | commands/close.md:652-656, :674, :677-688; agents/cleanliness-inspector.md:60-66; agents/prompt-inspector.md:67-73 | Pre-existing debt is "entirely ignored" by design (ruling 1). Recorded so no fix strengthens this consumer |
| 12 | hooks/subagentstop-artifact-contract-enforce.py:775-830, :1120-1123 | G2 checks artifacts only; no producer obligation about tests or size. The obligation branch is advisory by default (`CLAUDE_OBLIGATION_STOPGATE`, A1) |
| 13 | settings.json:277; hooks/pretool-git-privilege-guard.py:28-31 | Push is human-only, which is why CI almost never runs |
| 14 | hooks/git-fswatch.sh:335-400 | The only automatic push path bypasses /push (D1). It is not a feedback channel; listed because it would change CI cadence if re-enabled |
| 15 | docs/ENFORCEMENT-LEDGER.md (91 table rows; behavior column 48 advisory / 25 detected / 2 unexercised, 0 enforced) | The published pushback claims are not enforcement |
| 16 | Measured size at HEAD (no budget exists) | 893 tracked files; 327,900 lines; hooks/ 138,945 lines; prompt bytes (CLAUDE.md + commands/*.md + agents/*.md) 1,575,620; docs/reference 1,756,745 B (64 files); 131 files over 600 lines; registered hook entries: settings.template.json 73, settings.json 83 |
| 17 | C4 cross-ref: 1edf3e6 (auto-bulk) broke 53 tests; 26795c3 added the collection breaker | No producer ran the suite before landing |

Locations: 17 rows (31 distinct file:line anchors).

### 3.3 Fix (F2)

**F2.a — size ratchet (effort M, one script plus one repo-versioned budget file).**
- `scripts/size-ratchet.py` (new, ~120 lines, stdlib only):
  - `--measure [--ref <rev>]` prints 6 metrics: `tracked_files`, `tracked_lines` (excluding tests/generated),
    `hooks_lines`, `registered_hooks` (template and live counted separately), `prompt_bytes`
    (CLAUDE.md + commands/*.md + agents/*.md), `docs_reference_bytes`.
  - `--check [--budget-ref <rev>]` reads `policies/size-budget.v1.json` from the budget ref (default `@{upstream}`,
    falling back to `HEAD`), never from the working tree. A producer that raises its own budget in its diff therefore
    still fails its own check. It exits 1 on any metric above budget and prints the top growers
    (`git diff --numstat <budget-ref>`).
  - The script also carries F4.a's `Review-by:` scan.
- `policies/size-budget.v1.json` (new, repo-versioned, so immutable per release in the C1 sense). Initial values are
  measured right after the E1 deletion PR, not today's. Values only go down. A raise is a human commit and is visible
  in review.
- `.github/workflows/baseline.yml`: a new step after "Install Python dependencies" and **before** "Run tests" (so a
  red suite cannot skip it): `python3 scripts/size-ratchet.py --check --budget-ref <github.event.before | PR base>`.
- `hooks/subagentstop-artifact-contract-enforce.py`, obligation-resolved branch (:796-1123), for roles dev and
  test-writer: when `<project>/policies/size-budget.v1.json` exists, run `size-ratchet.py --check`. Failure goes down
  the same decision path as an artifact failure (advisory/block per `CLAUDE_OBLIGATION_STOPGATE`), and the artifact
  returns to its producer, who offsets with deletions (now possible, F1) or reports `growth_requires_budget_raise`.
  Product repos without the file are unaffected, which suits the published general-purpose product.

**F2.b — CI cadence (effort S).** `.github/workflows/baseline.yml:10-19`: add `schedule` (weekly, e.g.
`cron: '17 3 * * 1'`) and `workflow_dispatch`, so origin's state is checked even in weeks without a push.

Depends on: C4 (CI must collect before any CI step means anything), A1 (G2 block mode), E1 (baseline taken after the
cleanup).
Not proposed: changing close inspectors (consumer), PR-only flows (the user pushes master directly).
Risks: legitimate feature work is blocked until something is removed or a human raises the budget. Mitigation: the
first budget includes the post-E1 headroom (~55k lines of pure junk removed; E1 measures it). `@{upstream}` can be
stale or absent, in which case the fallback is HEAD (still producer-proof inside one cycle). A weekly scheduled run
spends Actions minutes and sends red e-mails until C4 lands.

## 4. F3 — live sessions edit the harness they run under; concurrent writers share one tree

### 4.1 Root cause
`~/.claude` is a symlink to a git checkout on tmpfs that IS the harness repo (NESTED-REPO.md:7-11). Three accounts'
sessions write it concurrently (backlog :11-17). An agent edit to a hook is live for every session the moment it is
written. The only behavioural check (`scripts/canary-verify.sh`) runs at the next SessionStart, after the damage. The
repo's own history shows the failure modes: a relative-import refactor passed compile, import and 725/755 tests, yet
the live hook fail-closed (docs/reference/monolith-split-plan.md:46-52). Settings registered hook files absent from
HEAD (02fe8fe → eead276). settings.json was landed whole, "entangled with several concurrent sessions' uncommitted
work" (02fe8fe; 20 commits marked "归属未定" (attribution undetermined), 34 with `Attribution-basis` trailers, 19
`chore(orphan)`). Daemon paths stash, rebase and push the live tree (`git-fswatch.sh`, `pull.sh`). The bulk sweep plus
`files_created` = all untracked bundle peers' half-done work, which grew 20 files / 6,292 lines of attribution
machinery (list in 4.2 row 17).

User decision: status quo (live sessions keep modifying the harness). So the separation (repo ≠ config dir) is NOT
proposed here (E2/C2 own it). The fixes below only make a live edit validated at its producer and keep daemons from
rewriting the live tree.

### 4.2 Complete location inventory (F3)

| # | file:line | what is wrong |
|---|---|---|
| 1 | NESTED-REPO.md:7-11 | `/root/.claude` → `/dev/shm/dev-workspace/dot-claude` (tmpfs) is the git repo; mirror rsync every 5 min; source = runtime |
| 2 | docs/reference/harness-issues-backlog.md:11-17 | Three accounts (<ACCT_2>, <ACCT_1>, <ACCT_3>) share the tree; the backlog itself was moved out of one account's memory for that reason |
| 3 | Git: 85 of 188 non-merge commits since 2026-07-17 touch hooks/ or settings*.json | Harness changes are made by sessions running under that harness |
| 4 | 02fe8fe (settings.json +85/-24 "landed whole", 20 change regions "归属未定") | Concurrent edits to one live config cannot be attributed |
| 5 | eead276 | settings.json registered 4 hook files absent from HEAD ("dangling"); nothing at the editing producer checked registered paths |
| 6 | docs/reference/monolith-split-plan.md:46-52 | Compile, import and unit tests passed while the live hook fail-closed; only a run-the-hook-as-registered check catches this |
| 7 | scripts/canary-verify.sh:1-10, :17-29, :36-39, :245; settings.json:335 (SessionStart) | The behavioural canary exists and takes `--hooks-dir`, but runs only at SessionStart, after the edit is live. It silently skips when the venv is absent (:36-39) |
| 8 | hooks/pretool-claude-config-guard.py:5-10, :24-29, :48-66, :70-93 | Substring match on `.claude/hooks/` and `.claude/commands/`. Verified: an Edit of `/dev/shm/dev-workspace/dot-claude/hooks/x.py` → rc=0 (realpath spelling bypasses), and `/root/.claude/settings.json` → rc=0 (not covered). Unlock is a hand-made `.hook-refactor-allow` sentinel |
| 9 | settings.json:236-239 (deny `Edit(.claude/CLAUDE.md)`, `Edit(.claude/hooks/**)`, `Edit(.claude/scripts/**)`, `Edit(.claude/settings.json)`); :159-160 (allow `Edit(.claude/agents/**)`, `Edit(.claude/commands/**)`) | Path patterns are relative, so (plausibly, per CLI rule semantics) they match only when the session's project is the parent of `.claude`, not when it runs inside the harness repo. Under status quo this protection is incidental, not a design |
| 10 | hooks/pretool-overnight-hook-guard.py:1-17, :52-60 (2,363 lines) | A layer 1 global block on `.claude/hooks/` during overnight, plus a contract-driven "self-repair grant" (T2.4). Guard complexity substitutes for an editing-time check |
| 11 | hooks/git-fswatch.sh:24-25, :174-260 (`safe_pull`: `git stash push` :200, `git pull --rebase` :210, every 300 s), :286-333 (`safe_commit` checkpoint), :335-400 (`safe_push` `git push origin <branch>` :357), :410-445 (`sync_changes`); hooks/git-fswatch@.service:11, :26 | A daemon stashes, rebases and pushes the live tree while sessions run. A pull can delete or replace a registered hook mid-session (X69); the push bypasses /push (D1/X75) |
| 12 | hooks/pull.sh:28, :48, :120, :126-147; commands/pull.md:28, :120 | `/pull` stashes and `pull --rebase`s the live tree; on conflict it leaves a rebase in progress (X78) |
| 13 | CLAUDE.md:92-96 (Hook Discipline #2 "NOT circumvent via … hook-file edits") | Forbids hook edits as circumvention while 85/188 commits edit hooks. There is no rule (prompt or hook) that a harness-editing cycle must prove the live chain still runs before it stops (git grep for live-hook/self-modify wording: none) |
| 14 | agents/changelog-analyst.md:215-218; commands/commit.md:24 | `--bulk` scans the FULL working tree of both repos and skips the close gate, so peers' half-done files land under one session's commit |
| 15 | agents/dev.md:522-527 (A3) | `files_created` = all untracked, so a producer claims a peer's new files |
| 16 | hooks/pretool-attribution-pre.py, hooks/posttool-attribution-post.py (registered on `Write\|Edit\|MultiEdit\|NotebookEdit\|Bash`) | Every tool call pays for concurrency attribution |
| 17 | Concurrency machinery (20 files, 6,292 lines): scripts/lib/attribution_adjudicator.py (834), hooks/tests/test_commit_journal.py (660), hooks/lib/commit_journal.py (627), hooks/tests/test_attribution_adjudicator.py (587), hooks/tests/test_attribution_journal.py (540), docs/reference/overnight-cycle-20260809-013317-shared-file-attribution-20260914.md (536), docs/reference/paseo-daemon-shared-file-attribution-20260913.md (484), hooks/lib/attribution_journal.py (437), scripts/verify-attribution-chain.py (267), schemas/owned-edits-ledger.v1.json (251), scripts/lib/attribution_aggregate_view.py (242), scripts/seal-attribution-journal.py (229), docs/reference/dev-command-20261003-020648-takeover-record.md (174), docs/reference/attribution-journal-phase0-facility.md (140), docs/reference/attribution-journal-cutover-flip-plan-20261003.md (128), docs/reference/attribution-journal-consumer-cutover-20261004.md (73), hooks/posttool-attribution-post.py (36), hooks/pretool-attribution-pre.py (27), scripts/attribution-aggregate-view.py (10), scripts/adjudicate-attribution-staging.py (10) | Exists only because several sessions write one tree. Kept under the hold; F2.a's ratchet stops it from growing further, and the journal becomes the one source for A3 (D3) |
| 18 | hooks/posttool-git-checkpoint.sh:10, :53-60, :61 (`. "$HOME/.claude/hooks/lib/checkpoint-core.sh"`) | No per-edit recovery coordinate for a single hook edit (10-file threshold); hard-wired `$HOME/.claude` (C1). Tracked hooks are still restorable from HEAD |
| 19 | hooks/session-promote-hook.sh:1-17; hooks/session-tmpfs-banner.sh; hooks/userprompt-tmpfs-pressure.sh | Tmpfs/promotion machinery exists because source lives in RAM (held; E2) |
| 20 | hooks/lib/subagent_restart.py (ACCOUNTS_ROOT cross-account discovery; C1/X110) | Cross-account coupling inside hook code |

Locations: 20 rows (44 distinct file:line anchors).

### 4.3 Fix (F3)

**F3.a — a harness edit is validated at its producer (effort M).**
`hooks/subagentstop-artifact-contract-enforce.py`, same branch as F2.a. Trigger: the producer's changed set
(`git diff --name-only <baseline_head_sha>` plus its own new files) contains `hooks/**`, `settings.json`,
`settings.template.json` or a `scripts/**` file that a settings hook command names, AND the project carries a
`settings.template.json` (the harness repo, or any fork of it). Run, from the project tree:
1. `python3 -m py_compile` on changed `.py`; `bash -n` on changed `.sh`.
2. `scripts/canary-verify.sh --hooks-dir <project>/hooks`.
3. Every hook script path named in `settings.json` and `settings.template.json` resolves to a tracked file or a
   file in the producer's own changed set (the eead276 check, moved to the producer).
Any failure blocks that producer's Stop with the failing command's output (returns to producer). No new state
file. This uses the existing canary at the right moment.

**F3.b — daemons do not rewrite the live harness tree (effort S; user decision; D1 overlap).**
`hooks/git-fswatch.sh` `safe_pull` (:174) and `safe_push` (:335): `return 0` when `realpath "$WATCH_PATH"`
equals the resolved harness home (`hooks/lib/claude_home.sh`). Checkpointing (:286) is unchanged.
`hooks/pull.sh`: refuse when the target is the harness home, printing the manual command for the human. Product
repos keep both features (no retirement).

**F3.c — concurrent-writer bundling (effort S if A3 only; M with the bulk exclusion; optional).**
Primary: A3 (dev `files_created` = producer-own paths from the existing attribution journal). Optional bulk-mode
rule in agents/changelog-analyst.md:215-243: skip, with the existing WARNING line, any path whose attribution-journal
last writer is another session with a transcript modified in the last 30 minutes. This reads the existing journal
and writes nothing.

**F3.d — CLAUDE.md wording matches the status quo (effort S; CLAUDE.md is user-owned; D4 overlap).**
CLAUDE.md:95: "hook-file edits are allowed only inside a /dev cycle on the harness (validated at Stop by the producer
gate); never to escape a block in the current turn."

Depends on: A1 (G2 block mode), A3, C1 (canary and checkpoint paths), D1 (fswatch push).
Not proposed (held by user decisions): moving the source out of `~/.claude`, single-writer locks, retiring the
attribution machinery, strengthening the config guard (it would block the status quo).
Risks: F3.a adds a few seconds to harness-touching producer stops (the canary runs 4 hooks). A canary that is itself
broken blocks every harness producer; the escape is the existing advisory switch. F3.b changes behaviour for anyone
who relied on auto-pull of `~/.claude`.

## 5. F4 — 'record, don't fix'; every incident adds a rule or hook; rules never retire

### 5.1 Root cause
1. The record-only rule (backlog :27, :3) is a user ruling scoped to "当前有 harness 修复在 worktree 跑" ("a harness fix is currently running in a worktree"). That
   scope ended (the worktree cycles were abandoned 2026-09-02/03, per b108c16), but the rule has no end condition and
   no consumer. Its intended consumer, the dedicated harness /spec session (teachings :288), is not wired. Ruling (c),
   "待办必须落地为磁盘上的 spec 文件" (the backlog must become spec files on disk, teachings :119), is not what exists:
   the backlog is a 697,229 B prose list.
2. The user's meta-rule "通过harness解决，永远不要通过ai的自觉性" (solve it through the harness, never through AI
   self-discipline), with its acceptance test "如果修复方案的成立依赖于某个 agent 读了某段文字并照做，那它就没修" ("if
   a fix only works because an agent read some text and complied, it isn't fixed", teachings :124-125, :438), is
   applied additively: each incident yields a new hook or rule, never a removal. 43 fix commits since 07-17: 42 net
   growth (+66,376 / -1,719), 22 of them adding a new file.
3. No producer can express retirement. BA's altitude verdict is `patch | redesign` (ba.md:20). Removal of approved
   code needs human clarification (ba.md:44). Guards are append-only (dev.md:794-798). The template sync is
   superset-only (verify-claims.sh:341-342), so a hook removed from live settings never leaves the published template
   (73 entries ever, 73 now).
4. Nothing expires. 0 `Review-by`/sunset clauses repo-wide. 37 of 112 top-level hooks cite a date, task id or
   incident in their header. 127 top-level hooks were added over the lifetime and 17 deleted, the last deletion being
   eb4fb45 (2026-06-16). hooks/lib has had 0 deletions ever. settings.json shows 101 distinct event:script
   registrations over its history vs 83 now.

### 5.2 Complete location inventory (F4)

| # | file:line | what is wrong |
|---|---|---|
| 1 | docs/reference/harness-issues-backlog.md:3 (frontmatter description) | Scope "当前有 harness 修复在 worktree 跑，新问题只记录不并行修" ("a harness fix is currently running in a worktree; new problems are only recorded, not fixed in parallel") is a temporary condition with no end |
| 2 | docs/reference/harness-issues-backlog.md:27 | The rule: fixes are serialized, new problems are recorded "等下一次 /spec 统一处理" ("to be handled together by the next /spec"), no consumer, no expiry. 697,229 B / 262 lines; the longest line is 22,351 chars |
| 3 | docs/reference/harness-issues-backlog.md:11-21 | Moved verbatim from one account's private memory; the archive-of-record shape, not a work queue |
| 4 | docs/reference/paseo-daemon-teachings-20260910.md:115-119 | Three-layer ruling: (b) harness problems only go to the backlog; (c) the backlog must be spec files on disk. Implementation honours (b), not (c) |
| 5 | docs/reference/paseo-daemon-teachings-20260910.md:124-125, :438 | The meta-rule and its acceptance test turn every fix into a hook (additive by construction; no removal clause) |
| 6 | docs/reference/paseo-daemon-teachings-20260910.md:278-282, :288 | "dev session 只开发" ("a dev session only develops"); harness findings route to a dedicated spec session. That consumer is not wired anywhere (no command/agent/hook reads the backlog except BA) |
| 7 | agents/ba.md:18, :917 | Mandatory full read of the 697 KB backlog per fix-class requirement (E4.b owns the change to a targeted grep) |
| 8 | agents/ba.md:19-20 | Altitude verdict `patch \| redesign` only; mechanism failure leads to "name the mechanism to replace", never "retire it" |
| 9 | agents/ba.md:38-51 (:44) | Removal of more than 50 approved lines needs human clarification, so retirement always costs a human round-trip |
| 10 | agents/ba.md:1090-1098, :1199; agents/dev.md:794-798 | `pre_existing_guards[].removal_authorized: false` by default; dev must STOP before removing a guard; no producer is told when to set `true` |
| 11 | hooks/subagent-stop-guard-integrity.sh:4-6, :23, :52-60 (always `exit 0`) | "Enforced by a SubagentStop hook" (dev.md:798) is a warning only; the rule's force is prompt text |
| 12 | CLAUDE.md:22-45 (Production Lessons numbered 11-16, incident-shaped, no review date), :38 ("Add `Skill(name:*)` … deny for every human-only command") | Rules accrete per incident; :38 requires a new deny per command (17 already dead, D2) |
| 13 | CLAUDE.md:92-98 (Hook Discipline #4/#5), :43 (Lesson 16 "Scope & terminal branch") | Over-compliance is fixed by adding qualifiers (L14: de25fe0); 809 MUST/NEVER/DO NOT/NON-NEGOTIABLE/FORBIDDEN/MANDATORY tokens across CLAUDE.md + commands + agents |
| 14 | Hook headers citing a date, task id or incident (37 of 112): hooks/auto-commit.sh, merge.sh, posttool-allowlist-consume.py, posttool-lane-completeness-watch.py, posttool-overnight-loop.py, posttool-push-gate-token-verify.py, pretool-aggregate-check.py, pretool-baseline-snapshot-preflight.py, pretool-bash-safety.sh, pretool-bisect-gate.sh, pretool-block-branch-pr-worktree.py, pretool-bulk-commit-detector.py, pretool-claude-config-guard.py, pretool-cp-checkin.py, pretool-cp-state-write-guard.py, pretool-do-block-subagents.py, pretool-git-privilege-guard.py, pretool-gitignore-preflight.py, pretool-grep-backtrack-guard.py, pretool-obligation-gate.py, pretool-push-analyst-grant-guard.py, pretool-subagent-code-block.py, pretool-wrapper-userintent.py, pretool-write-guard.sh, session-info.sh, session-scratch-init.sh, session-tmpfs-banner.sh, sessionend-scratch-sweep.sh, stop-cleanup-allowlist.sh, stop-completion-gate.py, stop-do-report-gate.py, stop-obligation-gate.py, stop-spec-coverage-enforce.py, stop-workflow-coordinator.py, subagentstop-artifact-contract-enforce.py, subagentstop-e2e-enforce.py, userprompt-tmpfs-pressure.sh | Each hook is justified by an incident whose evidence is often in gitignored docs/dev; none carries a review date, so none can be judged obsolete |
| 15 | hooks/pretool-do-block-subagents.py:15, :135; hooks/pretool-baseline-snapshot-preflight.py:52 | Hooks born from backlog entries; the entry stays after the hook lands |
| 16 | scripts/verify-claims.sh:336-396 (:341-342 "template is a superset; only MISSING hooks fail", :387) | Retirements in settings.json never propagate to the published template (73 ever / 73 now) |
| 17 | docs/ENFORCEMENT-LEDGER.md:3-5 ("every wired hook gets a row"); scripts/verify-claims.sh:84-189 | Every hook adds a ledger row and README/ARCHITECTURE count edits, so removal is a 5-6-file change (friction, not a block) |
| 18 | b108c16, 16963b6; docs/reference/overnight-worktree-20260810-test-gaps-20261005.md, docs/reference/overnight-worktree-test-gaps-20261005.md:40 | "Record, don't fix" applied to code: known-failing tests landed "documented" (C4.f owns the tests) |
| 19 | docs/reference/commit-gate-bypass-via-background-exec-20261005.md:60-73 | "None of the three is attempted in this record"; fix #1 (foreground-only rule in agents/changelog-analyst.md) is still absent (grep for foreground/nohup/background in that file: no hit) |
| 20 | docs/reference/controller-error-taxonomy-20260924.md:5, :22 | A record kept although it states "0 次是机器拦住控制器的错误" ("in 0 cases did a machine stop the controller's error"); records accrete regardless of fix value |
| 21 | docs/reference/ (64 files, 1,756,745 B; 37 dated) | The incident-record habit (E4 owns the deletions) |
| 22 | Git: fix commits since 07-17 = 43, net-growth 42, +66,376 / -1,719, 22 add a new file; top-level hooks 127 added / 17 deleted, last deletion eb4fb45 2026-06-16; hooks/lib 0 deletions; settings.json 101 distinct event:script registrations ever vs 83 now; settings.template.json 73 / 73; Review-by markers anywhere: 0 | The quantitative signature of "rules never retire" |

Locations: 22 rows (78 distinct file:line anchors, including the 37 hook headers).

### 5.3 Fix (F4)

**F4.a — rule expiry by convention (effort S; no register file).**
- Convention: each top-level hook file header and each CLAUDE.md NON-NEGOTIABLE section or Production Lesson carries
  one line `Review-by: YYYY-MM-DD` (at most 180 days ahead). Initial dates are staggered across 26 weeks by sorted
  file name, in one commit.
- `scripts/size-ratchet.py` (F2.a) prints expired markers as warnings (never a failure, so no mass red CI). It fails
  only when a top-level hook file or CLAUDE.md lesson added since the budget ref lacks the line.
- The consumer of the expired list is the harness /spec session the user already prescribed (teachings :288):
  renew (new date plus a one-line reason in the commit) or retire (F4.b plus F1.a `git rm` plus deregistration).

**F4.b — retirement is a producer output (effort S, prompt-only).**
- agents/ba.md:20: verdict `patch | redesign | retire`. For a hook or rule with 2 or more backlog entries about false
  positives or deadlocks (76 of 158 entries are of that kind per wf2 L7), evaluate `retire` first. A `retire` spec
  lists the files to `git rm`, the settings/template registrations to remove, and sets `removal_authorized: true` on
  the affected `pre_existing_guards` (ba.md:1199, dev.md:796).
- One-in-one-out is mechanical through F2.a's `registered_hooks` metric. A fix that adds a hook must retire one, or
  a human raises the budget.
- agents/ba.md:44: carve out git-recoverable deletions under a `retire` verdict from the >50-line clarification rule
  (user decision U-F1d).

**F4.c — the record-only rule gets an end, a consumer and a cap (effort S; user decision U-F4a).**
- docs/reference/harness-issues-backlog.md:3, :27: state that the record-only rule binds sessions running /dev
  (teachings 1.22, unchanged), and that the dedicated harness /spec session consumes entries. An entry is deleted
  when its spec lands (`git rm`/edit; history keeps it, F1). The worktree-scoped wording is dropped.
- The cap is mechanical: F2.a's `docs_reference_bytes` budget. A new entry needs an old one condensed or closed.
- agents/ba.md:18: targeted grep instead of a full read (E4.b, same change).

**F4.d — retirements reach the published template (effort S).**
scripts/verify-claims.sh:341-342, :387: fail on template-only hooks unless listed in an explicit `PUBLIC_ONLY`
array in the script, so a hook retired from settings.json is retired from settings.template.json in the same change.
Coordinate with C2, which owns which file is the truth.

Depends on: F1.a (removal possible), F2.a (ratchet carries the scan and caps), E4 (backlog/records disposition), C2.
Risks: expiry dates become rubber-stamped. Mitigation: renewals need a reason line, and the weekly CI warning stays
visible. A `retire` verdict removes a protection that still mattered. Mitigation: F1.a recoverability, the producer
gate's canary (F3.a), and QA on the spec.

## 6. Cross-cluster dependencies and order

1. C4 (CI collects) → F2.b is meaningful; F2.a's CI step runs before tests regardless.
2. A1 (gate switches to block) → F2.a/F3.a producer checks block instead of advise.
3. A3 (producer-own files) → F1.c/F3.c (bulk and dev stop claiming stray or peer files).
4. D1 (checkpoint auto-push; fswatch push) → F1.b (or take the `CHECKPOINT_NO_PUSH` knob), F3.b.
5. E1 (one-off deletion PR) → F2.a baseline values; E4 → F4.c.
6. Order: F1.a → E1 → F2.a (+F4.a scan) → F1.b → F1.c / F4.b / F4.c / F4.d → F3.a → F3.b / F3.c / F3.d → F2.b.

## 7. Corrections to prior evidence

- X01/X07: the removal policy is not simply "before the /do bypass". It runs AFTER the main-agent /do exit
  (pretool-bash-safety.sh:864-878) and BEFORE the subagent /do exit (:2751-2766). So main+/do removes
  **unrecoverably with no snapshot** (`rm -rf .` → rc 0), and subagent+/do cannot remove at all.
- New: `git rm -n` (dry run) is also FORBIDDEN_REMOVAL; `mv` out of the repo passes the full hook (rc 0).
- New: agents/changelog-analyst.md:919-922 prescribes the blocked `git rm --` command; agents/cleaner.md:73
  prescribes the blocked `rm`.
- X10/L10 "40 files / 18,934 lines of attribution machinery": the name filter also caught release, hero-provenance
  and paseo-ledger files. The concurrency-specific subset is 20 files / 6,292 lines (§4.2 row 17).
- L1 "129 top-level hooks added": 127 with a strict top-level path filter (the `hooks/*.py` pathspec also matches
  hooks/tests/…; e.g. 407888c 2026-07-05 deleted a test, not a hook). The last top-level hook deletion is eb4fb45
  (2026-06-16), confirmed.
- L1 "107 distinct hook entries ever": 101 distinct event:script pairs by this count (method difference); 83 now
  confirmed; template 73/73 confirmed.
- X13 "91 files exceed 600 lines": 131 across all tracked files at HEAD (prior scope narrower).
- CI history re-read: 5 runs since 07-16, all failure, the latest on 09ab15b (2026-10-08); release workflow 0 runs.

## 8. User decisions (minimal set)

| id | question | recommendation |
|---|---|---|
| U-F1a | Treat `git rm` without `-f` as an allowed, recoverable removal for all agents (direct reading of the 2026-10-04 ruling)? | yes |
| U-F1b | Allow agents to rm untracked, non-ignored, in-repo files after an automatic snapshot to refs/checkpoints (not pushed)? | yes |
| U-F1c | Inside `/do`, keep allowing removals that cannot be snapshotted (ignored files, outside the repo, `-f`), or deny them too? | keep allowing under explicit `/do` consent; snapshot whatever can be snapshotted |
| U-F1d | Exempt git-recoverable deletions under a BA `retire` verdict from the ">50 approved lines needs confirmation" rule (ba.md:44)? | yes |
| U-F2a | Approve the 6 ratchet metrics, budget = measured after the E1 cleanup, raises only by human commit | yes |
| U-F2b | Add a weekly scheduled CI run (Actions minutes, red e-mails until C4 lands)? | yes, after C4 |
| U-F3a | fswatch and `/pull` skip pull/rebase/push on the harness home (product repos unchanged)? | yes |
| U-F3b | Bulk commit skips paths last written by a still-live peer session? | optional; A3 first |
| U-F3c | Reword CLAUDE.md Hook Discipline #2 to match the status quo (user-owned file)? | user's call |
| U-F4a | Record-only rule: keep it for /dev sessions, drop the worktree scope, name the harness /spec session as consumer, cap by the docs budget? | yes |
| U-F4b | `Review-by:` convention (180 days, staggered; expiry warns, never fails)? | yes |

## 9. Deliberately not proposed

- Any change to /close or /commit consumption, including close inspectors routing pre-existing debt (consumer
  strengthening; user ruling 1).
- Retiring /clean, overnight, attribution, fswatch or any feature (hold decision). Only their regrowth and their
  live-tree side effects are addressed.
- Moving the harness source out of `~/.claude`, single-writer locks, or new state files (status-quo decision; C1).
- A rules register, weekly routines, auto-merge lanes or a new subsystem; the only new artifacts are one script and
  one repo-versioned budget file.
