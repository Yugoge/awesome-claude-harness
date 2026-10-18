# Phase P7b: zero-touch landing of P7 on a live home (no human step, sessions keep running)

You are implementing phase P7b of the harness repair plan in this repository (the GitHub repository this session
cloned). Phase id for the PR title: `P7b` (for example `P7b: a live home lands P7 by itself`). P7b is a new, small
phase that PLAN-v2.md does not contain, so this prompt is its authoritative scope. It finishes P7 (portable,
sanitized product: one tracked clean settings.json, the claude-settings clean/smudge filter, the untracked
settings.machine.json overlay, init, doctor, migration, optional paseo, the private-literal rule; merged as master
f8c18c276e92e07c14487e9908490aa4bdefbc3a, pull request #4) on a home that was running pre-P7 code when it receives
that master.

**Wave 2a: start now; you may run alongside P1 and P8 (other sessions), but try to merge first.** The owner's live
home can receive P7 through any pull at any time, and PLAN-v2.md section 13's row "P8 ... render-settings migrate"
(migrate must never seed GIT_AUTO_PUSH=1, doctor flags it) moved into this phase. P7b needs neither P1 nor P8, and
neither needs P7b. Files the three phases share (locations at f8c18c2; keep your edits to the lines named here):
- scripts/install/render-settings, scripts/doctor, tests/test_settings_filter.py: yours (the earlier P8 prompt
  carried that row as its row 11 with the acceptance test "Migration keeps push off"; the refreshed P8 prompt marks
  row 11 "(moved)" and does not edit these files).
- scripts/bootstrap: you make its init steps 2-5 (:227-457) runnable without a terminal and without the venv step
  (:150-225) and the doctor step (:478-503). Keep the body of step 5 (:392-457) intact: P8's optional row 12 may add a
  pre-merge-commit and a commit-msg install to it, and your landing must then install those too, through the same
  code.
- hooks/lib/checkpoint-core.sh: you `_checkpoint_rate_limited_push` (:319-320) and, only if you choose it under R7,
  the trailer line (:428). P1 edits the read-tree redirects (:518, :525) and P8 edits :95 and
  `_checkpoint_push_gate_pii_signature` (:247-315, its closing brace at :314; use at :301; its call :403). Your hunk
  starts five lines after that brace (a blank line and the three-line comment :316-318 lie between), so the diff
  contexts overlap: expect a textual conflict there if P8 merges first, and keep both sides.
- hooks/auto-commit.sh: yours (the recommended trigger site, R1). Neither P1 nor P8 edits it. P1's acceptance relies
  on its output contract (exit 0; the refused-snapshot notice at :50-51), which must not change. P1's row 23 keeps
  the coordinator's relay of a passing phase's last-line `systemMessage` (its text: the relay "stays for refused
  snapshots only", meaning P1 adds no failure notice); your landing notice (R9) uses the same relay, so if P1 merged
  first, check that the relay still passes any such line and say so in the PR.
- hooks/pretool-bash-safety.sh: you only the pre-landing env helper and its call sites (R7: near :377-387 and
  :1816); P8 redacts comment and message lines at :1961, :2083-2084 and :2168.
- hooks/lib/subagent_restart.py: you only :826 (R7); P8 edits :111 and :775-776.
- README.md: yours in the install section (:74-130), the overlay bullet of the settings section (:166-167) and the
  private-literal paragraph (:258-268); P1 rewrites the paragraph just above yours (:253-256: a broken filter
  install "blocks the Stop"; expect a textual conflict if P1 merges first, keep both sides), the count lines
  (:423, :821) and the per-event table's Stop row (:869); P8 deletes the count lines and may change :325-327.
- PUBLIC-CORE.md: yours :46-48 and :69-71; P8 rewrites sections 3 and 5 (:80-123, :174-196).
- Not yours, do not edit: hooks/stop-workflow-coordinator.py and hooks/prompt-workflow.py (P1 rows 23 and 25),
  settings.json (P1 unregisters a Stop entry and adds a timeout), scripts/check-public-core.sh and
  .github/workflows/baseline.yml (P8), conftest.py (P8 adds an autouse hermetic fixture; every test you add must
  pass with it as well as without it).

Whichever PR merges later merges `origin/master` into its branch (a merge commit, no rebase), re-verifies the shared
lines and re-runs its acceptance tests.

**Before you start.** `git fetch origin master`, then both must succeed:
`git merge-base --is-ancestor f8c18c276e92e07c14487e9908490aa4bdefbc3a origin/master` and
`git cat-file -e origin/master:settings.machine.example.json`. If either fails, stop and tell the owner that P7b
starts only after P7 is merged. Your acceptance tests check out the pre-P7 revisions
fe7700c86976dbe299fd8d4a5ca99dcd7a050cf6 (master before P7, after P0 and P0b) and
09ab15bc (master before P0), and read files from the pre-P0 hook commits e34918cf, 84c85f23 and 86d70265: if your
clone is shallow,
run `git fetch --unshallow origin` (read-only) first. Note in the PR whether P1 or P8 had merged when you measured.

## Goal

P7 assumes that the owner runs a one-time migration by hand on each home, with every Claude Code session closed
(pull request #4's REQUEST): fetch, migrate with the incoming render-settings, register the filter, pull,
`scripts/bootstrap`, fill `private-literals.txt`, `scripts/doctor --strict`, restart the sessions. P0's REQUEST
(remove the installed auto-push post-commit hooks, restart a running fswatch daemon) and the earlier P8 prompt's
REQUEST steps 1 (copy the engine's marker literals into the list) and 4 (check the overlay for GIT_AUTO_PUSH) are
further steps on his machine. The owner will not do any of it and cannot stop his
sessions (his words below). Three Claude accounts run sessions on the home, often unattended.

After this phase, a home that ran pre-P7 code and receives master through any pull path ends up, at the next turn
end of any of its running sessions, in the state the manual steps would have produced, with no human step, no
restart and no session stopped:
- settings.json is valid and in machine form, and the index entry is clean (no conflict, no staged change the pull
  path left behind);
- the overlay holds the home's previous personal settings (the previous revision's tracked values beyond the clean
  form, its built-in code defaults, and the live entries the CLI wrote) and never GIT_AUTO_PUSH=1;
- the filter is registered, the applied-record exists, the fail-closed pre-commit hook is installed;
- `private-literals.txt` is seeded from values the machine already knows, and no value is ever printed;
- no legacy auto-push post-commit hook stays active in the harness home, and a git-fswatch daemon running stale code
  on it is restarted with the current code;
- sessions that started before the landing stop pushing checkpoints when the rendered settings say so, and see the
  overlay's personal guard settings, without a restart;
- nothing ever blocks a Stop, and the sessions see one plain line saying what happened.

## Owner decisions that govern this phase

D# are in DECISIONS.md; S# are the owner clarifications in PLAN-v2.md section 0 (they rank right below DECISIONS.md).

- **The owner's statement (2026-10-18, answering the manual steps he was given after P7 merged):**
  "我自己在机器上做的是什么意思？我不做，没空，我不能停止claude。" ("What does 'do it on your own machine' mean?
  I won't do it, I have no time, I cannot stop Claude.") It outranks every plan text that makes these human steps:
  PLAN-v2.md section 4 (the P0 row "Remove the installed post-commit push hooks ...", the P7 row "Run init on each of
  the owner's homes and the one-time owner migration command (R5); confirm doctor --strict", and "Write the overlay
  and the private-literal list (only init, run by the human, writes them ...)"), pull request #4's REQUEST ("Run
  them with no Claude Code session open"), PUBLIC-CORE.md:47 ("written only by init ... never by hooks or agents")
  and :70 ("only the human fills it"), README.md:167 ("written by init only when absent, never by hooks or
  agents") and :259 ("only you fill it"), and the earlier P8 prompt's REQUEST steps 1 and 4. This phase replaces
  those steps with one producer: the landing. The reviewer updates PLAN-v2.md section 4 on the planning branch (the
  refreshed prompts/P8.md already has no REQUEST); you change only the repository files this prompt names.
- **Earlier owner words pointing the same way:** the harness should repair itself and not cost him time ("这就是我一直
  希望它自治地自己修复自己"); the way the harness is modified stays as it is (sessions keep running on the live tree);
  his machine keeps full local support while the remote is sanitized ("我本地不要删除支持，找一个本地有支持但是远端去敏感的
  方法"); steps for him must be the lazy version ("懒人版"). Here the lazy version is: none.
- **D1** One switch, GIT_AUTO_PUSH, pushes only when it is exactly `1`. The landing never seeds `1`; sessions that
  started with a stale `1` stop pushing once the rendered settings say otherwise; legacy installed hooks that push
  unless the value is `0` are disabled. Local checkpoints stay. /push stays the normal route.
- **D11 / S3** settings.json stays tracked in clean form; the filter and the overlay keep machine values out of the
  index; a machine without the registered filter must not commit personal values (P7's fail-closed checks stay).
- **D12 / S6** Personal values are never tracked or printed. The private-literal list stays local and untracked.
  Messages, logs, tests, the PR and commit messages carry key names, counts and hashes only.
- **D13 / S5** paseo stays optional: the migration detects whether the previous settings had it on (P7's
  `module_enabled`); a fresh clone is never switched on.
- **D14 / S4** Permissions are not changed: personal-path allows go into the overlay exactly as P7's migration puts
  them there.
- **D15** No feature retirement; live sessions keep running on this tree. No registered hook file is deleted or
  unregistered. The fswatch daemon is restarted, never stopped for good.
- **D4 / S1** Stop gates exist only on the eight commands. The landing is never a Stop gate: it exits 0, and a failed
  or skipped landing is a notice, never a block (PLAN-v2.md section 13's row P5 records that an auto_commit failure
  blocks the Stop today; P1's row 23 delivers that row, so it holds until P1 merges).
- **D3** The landing asks no questions. You ask the owner only the one input below, and only if it is still OPEN.
- **D16 / S7** No history rewrite, no remote ref deletion (both P11). D17's dead-code deletions are P8's: this phase
  deletes no code and no test.
- **D10** Pure technical choices are yours (listed below); each goes into the PR's technical-choices table.
- **Producer-side, no new mutable state.** The landing is the producer of the machine state P7 defined (overlay,
  filter registration, record, private-literal list, pre-commit hook). "Landed" is read from those artifacts
  themselves; add no flag, marker or counter file. A lock file used only by `flock` and an append-only log that no
  code reads are allowed. Nothing is added to /close, /commit, /push, /pull, /merge or the changelog-analyst.

**Owner input (ask once with AskUserQuestion at the start, only if the next line still says OPEN).**
OPEN. Other repositories: may the landing also disable the legacy auto-push post-commit hooks (R6) and restart stale
git-fswatch daemons (R8) in the owner's other repositories, which are the places P0's REQUEST searched (every `.git`
under the home directory down to depth 5)? Options: "harness home only" (default if unanswered) or "also the other
repositories". Put each option's consequence in the question: with "harness home only", the legacy hooks in his other
repositories keep pushing on every commit made where GIT_AUTO_PUSH is not exactly `0` (a plain shell, a daemon, a
session that started before P0), so D1 is not met there, and nothing else in the plan removes them, because he runs
no steps; with "also the other repositories", the same reversible rename and restart happen there, reported as
counts only. With "also", the same signatures, the same reversible method and the same counts-only reporting apply,
and the LFS hooks of a repository that uses Git LFS are restored with a command that writes only that repository's
hooks (`git lfs update --force`, never a global config write). Start on everything else while you wait for the answer.

No OPEN decision of PLAN-v2.md's decision ledger applies to P7b.

## Scope (re-verify every location on current origin/master)

Locations are at master f8c18c2 unless another revision is named. Name functions and anchors in your PR as well:
P1 and P8 may move lines.

### What happens today (re-run these facts in a scratch clone and put the output in the PR)

These were verified in scratch clones of f8c18c2 and fe7700c8 with HOME pointed at a scratch directory.

1. **Pull paths.** Every path that can bring P7 to a live home is executed by the home's old code:
   - the git-fswatch daemon, which no hook starts (it is started by hand: hooks/fswatch-manager.sh `start_watcher`
     :63-81, hooks/start-fswatch-all.sh :62, or the systemd unit hooks/git-fswatch@.service :11): `sync_changes`
     (:411), run after each debounced change, calls `safe_pull` after a successful checkpoint (:423) when the last
     pull is older than 300 s (:428-440); `safe_pull` (:174-263) stashes (:200), runs
     `git pull --rebase origin <branch>` (:210) and pops (:216). Each of those three git calls is piped into `tee`
     without pipefail, so its failure is logged as success and `safe_pull` returns 0 (verified: a conflicted pop
     prints git's `CONFLICT (content): Merge conflict in settings.json`, then "Stashed changes restored"); and when
     `<home>/logs/` is missing, `tee` itself fails and the pull reports a fetch failure. A running daemon keeps the
     functions it loaded at start, checkpoint-core's included; one started before P0 pushes the branch and every
     checkpoint whatever GIT_AUTO_PUSH says (09ab15bc: `safe_push` and `_checkpoint_rate_limited_push` have no
     switch);
   - /pull, human-only (commands/pull.md:3), runs hooks/pull.sh: stash (:28), `git pull --rebase` (:120), pop
     (:160); a failed pop exits 1 and keeps the stash;
   - /merge origin/master in place: hooks/merge.sh refuses uncommitted changes (:183), then `git merge` (:231).
     Master's 09ab15bc ("Merge remote-tracking branch 'origin/master'") came from the owner's home this way or by a
     plain `git pull`;
   - a plain `git pull` in a terminal. Agents are refused `git pull` (hooks/pretool-git-privilege-guard.py
     `_looks_like_git_forbidden_plumbing`, :2180) unless granted. No hook pulls (session-git-init.sh does not).
2. **The stash pop conflicts on settings.json.** Pre-P7 tracked settings.json holds CLI-owned keys (model,
   alwaysThinkingEnabled, effortLevel, tui, theme, autoCompactEnabled; render-settings `CLI_OWNED` :58-59) that P7's
   clean form removed. A home at fe7700c8 whose live settings.json has a changed `model` value and one added allow
   entry, after the fswatch sequence (stash, pull --rebase, pop): `UU settings.json`, conflict markers around the
   removed model line, settings.json no longer JSON, the stash kept, and every other stashed path left STAGED in the
   index. A live delta that touches no removed line merges cleanly: the working file is the clean form plus that
   delta, and the stash is dropped. From a clean working tree every pull path gives the clean form. With
   settings.json modified, a merge pull (`git pull --no-rebase`) refuses ("Your local changes to the following files
   would be overwritten by merge") and /merge refuses (merge.sh :183); both leave HEAD and the file as they were.
3. **What the new code then does.** The filter is not registered (.gitattributes:1 declares it; git ignores an
   undefined driver), and there is no overlay and no record. Every personal value P7 moved into the overlay is
   inactive (pull request #4's list: CLI keys, personal allows, the paseo module, the protected-daemon guard, the
   dev-container whitelist, the restart sibling scan, the checkpoint trailer, the product hard bans). While
   settings.json differs from HEAD, hooks/pretool-bash-safety.sh denies every agent `git commit` in the harness home
   (unregistered-settings-filter, :355-360, message :368), and `write_checkpoint` refuses every harness-home
   snapshot whose settings.json fails `render-settings check --staged` (`cmd_check_staged` :943-969: a CLI-owned key,
   a non-canonical file or no JSON at all; hooks/lib/checkpoint-core.sh step 2c, :589-606, rc 3; one notice per
   Stop, hooks/auto-commit.sh:50-51). Verified on an S2 home: with only an added allow entry the snapshot is
   written; once the CLI writes `model` back (the clean form removed it), every snapshot is refused; S3's
   conflict-marker file is always refused.
   While settings.json holds conflict markers, a session that starts reads an invalid file, which Claude Code skips:
   that session runs without the harness's hooks and permissions until it ends.
4. **P7's manual commands do not cover it.** On the conflicted home, `scripts/bootstrap --yes --migrate-from
   ORIG_HEAD --no-doctor` writes an overlay from ORIG_HEAD's tracked file (the live delta in the stash is ignored),
   registers the filter, then fails: "settings.json is not a valid JSON object; fix it, or re-run with --force"
   (render-settings `cmd_render`, :739), rc 1.
5. **Migration re-enables push.** `render-settings migrate` copies every env value that differs from the clean form
   (`cmd_migrate` :1095-1169: `extra = diff(prev, reference)` :1137, `diff` :540-582). From a home at 09ab15bc
   (GIT_AUTO_PUSH "1") the new overlay holds GIT_AUTO_PUSH "1" (PLAN-v2.md section 13, row "P8 ... render-settings
   migrate").
6. **Running sessions keep their environment.** The checkpoint push reads only the process env (checkpoint-core.sh
   :320). The bash-safety knobs (:377-387 and the hard-ban list :1816), hooks/lib/subagent_restart.py (:826) and the
   checkpoint trailer (checkpoint-core.sh :428) read env keys that only the rendered overlay provides. A session that
   started before the landing keeps a stale GIT_AUTO_PUSH (for example "1" from a pre-P0 settings.json) and none of
   the overlay keys until it ends. A session started from the rendered overlay has CLAUDE_HOME in its env (P7
   seeds it into every overlay); one started earlier does not.
7. **Installed legacy post-commit hooks.** Copies of hooks/git-hooks/post-commit-auto-push from before P0 (commits
   e34918cf, 84c85f23, 86d70265) and the combined "Git LFS + Auto-Push" hook of the pre-P0
   hooks/install-protection-all.sh test `${GIT_AUTO_PUSH:-1}` and push unless the value is exactly `0`: in any
   shell, any daemon and any pre-P0 session. In a repository they live at `<git common dir>/hooks/post-commit`, at
   `<git common dir>/keystone-hooks/preserved/post-commit` (scripts/install-git-keystone.sh :41; its dispatcher
   exits 0 when the preserved file is not executable, :78-79), or in the directory core.hooksPath names. The current
   template (post-commit-auto-push :15-18, exact `1`) is an opt-in hook and stays.
8. **Which hook runs in every session.** All 83 hook registrations of fe7700c8's settings.json (82 distinct files,
   absolute `/root/.claude/...`; the same holds for 09ab15bc's) exist at f8c18c2, so a session started before the
   pull runs the new hook files. The Stop coordinator, registered both there and in the clean form
   (settings.json:801, no `timeout` key in either, so Claude Code's default hook timeout bounds the whole
   coordinator; P1 adds 300), runs hooks/auto-commit.sh as its auto_commit phase (hooks/stop-workflow-coordinator.py
   `_default_phases` :55-63, :61, timeout 120 s) at every main-session turn end (not for a subagent's Stop,
   :199-205), unless the timelock or coverage phase blocks first. The coordinator shows the phase's `systemMessage`
   as its own only when the phase exits 0 and the JSON is the last line of its stdout (`_run_phase` :165-168, :175;
   `main` :334-336); whether Claude Code displays it is still to be confirmed on a live host (PLAN-v2.md section
   13, second row P5).
9. **A home that already pulled P7 alone.** P7 merged before P7b. A home that pulled it and was left in S3 or S4
   (R2) receives nothing more by any pull path, so P7b's code cannot reach it. Verified in a scratch clone at
   f8c18c2 in S3 with a later commit on origin: the old `safe_pull` prints "settings.json: needs merge" at the stash,
   "Pulling is not possible because you have unmerged files" at the pull and keeps the stash at the pop, yet logs
   success and returns 0; the old hooks/pull.sh exits 1 at its stash (:28-31); a plain `git pull` refuses. A home
   that pulled P7 alone into S1 or S2 receives P7b with its next pull (P7b does not edit settings.json).

### Requirements (R1-R11)

**R1 One trigger, cheap when landed, never a block.** Put the landing behind one call in a hook file that both a
pre-P7 settings.json and the clean form register and that every session runs at least once per turn.
hooks/auto-commit.sh is the recommended site (before its git-repository check at :21, independent of the session's
cwd: the harness home is the one that holds the script). Constraints:
- never change auto-commit.sh's exit status or its existing output (`|| true` style; it runs under `set -e`, :13);
  until P1 lands, a non-zero auto_commit phase blocks the Stop;
- fast path on a landed home: file checks and at most the one or two git calls the "landed" test needs; measured
  overhead under 50 ms per Stop (acceptance 11);
- "landed" = the overlay exists, the applied-record exists, `filter.claude-settings.clean` is set, and every hook
  bootstrap step 5 installs (today the pre-commit) is byte-identical to its source under hooks/git-hooks/. Installed
  hooks are copies (step 5 compares and copies, :447-454), so a later change under hooks/git-hooks/ (P8's optional
  row 12 adds a pre-merge-commit and a commit-msg step) reaches a landed home only this way: when only that
  comparison differs, re-run step 5 alone (no migration, no seeding, no other step). Skip the comparison where step 5
  cannot install (R4), so such a home gets no notice at every Stop. From the owner conversation (2026-10-18: he runs
  no init after a pull). If the record exists but the overlay does not (a human removed it), do nothing: doctor
  reports it;
- act only on an upgraded home: one whose HEAD reflog (or ORIG_HEAD, when the reflog is missing) holds a commit
  whose `.gitattributes` does not declare `filter=claude-settings`. A clone that never had a pre-P7 revision checked
  out is left to init (D13: module choice is the user's), and nothing is written there;
- one landing at a time across sessions and accounts (`flock`, or an equivalent that adds no state); a session that
  finds the lock taken skips and lands nothing;
- bounded: target under 15 s (the phase's 120 s and Claude Code's default timeout for the coordinator, fact 8, hold
  the checkpoint too); each step idempotent, so a landing killed half-way completes at the next trigger;
- do not register a new hook (a session started before the pull never loads it) and do not edit the coordinator or
  prompt-workflow.py.

**R2 Recover the settings state the pull path left.** Before migrating, classify and repair, touching nothing else:
- clean form (S1) or clean form plus a merged live delta (S2): nothing to repair;
- conflicted stash pop (S3: settings.json unmerged, no rebase or merge in progress): restore settings.json from HEAD
  once the overlay exists and the filter is registered (so the checkout writes the machine form), and return to
  unstaged every path the conflicted pop staged (index blob equal to that path's content in the pull path's stash),
  so the index ends equal to HEAD for those paths with their working-tree content unchanged. Keep the stash entry
  (D10: dropping it is not needed). Other unmerged paths (a hook file the owner had edited, for example) are left
  exactly as they are and counted in the notice; the landing still lands the settings;
- integration stopped mid-rebase or mid-merge (S4: a rebase-merge or rebase-apply directory, or MERGE_HEAD, in the
  harness home): change nothing in git, land nothing, and show the notice (R9) naming the stopped operation and the
  number of conflicted paths. Never abort, continue, reset or clean anything.
Find the pull path's stash by content, not by message: the newest stash entry whose first parent is the pre-pull
revision (R3) and whose settings.json differs from it (messages differ by path: "fswatch auto-stash", "Auto-stash
before pull", git's "autostash").

**R3 One migration, never GIT_AUTO_PUSH=1.** The overlay keeps exactly one producer, render-settings' migration;
extend `cmd_migrate` (or give it one more input) instead of writing a second migration. Inputs:
- the pre-pull revision `rev`: the newest HEAD reflog entry whose tree does not declare the filter (ORIG_HEAD as
  the fallback; covered by a test where ORIG_HEAD was overwritten by a later git operation);
- the previous personal settings: the live file at pull time when the pull path's stash holds it (S3); otherwise
  `rev:settings.json` plus the working file's entries that the clean form at HEAD does not explain (S1, S2: the
  CLI's writes, whether they came before or after the pull);
- the previous code defaults: `code_defaults(home, rev)` (:1050-1060, table :1029-1047), as today;
- `env.CLAUDE_HOME`, as today (:1143).
`render-settings migrate` never writes GIT_AUTO_PUSH "1" into a new overlay: it leaves the key out and names it (key
only, never a value) in its output as not migrated because automatic push is opt-in (D1). The settings check that
doctor runs (`render-settings check`, `cmd_check` :925-940; doctor :142-146) prints one line naming the key when the
overlay's env sets GIT_AUTO_PUSH to "1", saying automatic pushes are on (D10 whether it fails the check, given that D1
lets a human opt in on purpose; prefer adding the line inside the existing settings step, so it is a changed rule,
not a new one). This is PLAN-v2.md section 13's row "P8 ... render-settings migrate", moved here from the earlier P8
prompt's row 11; its owner step ("check the overlay") is gone. `cmd_migrate` already reads a previous-settings file
instead of the revision's blob (`--settings-file`, :1110-1118); a file you extract from the stash holds personal
values: mode 0600, outside the repository, removed afterwards.

**R4 The rest of init, without a human.** After the migration: register the filter (the three local keys
`scripts/bootstrap` step 3 writes, :292-301), render (`cmd_render` :722-777, which writes the record), create only
when absent `<home>/logs/`, the TMPDIR root and the protected-runtime file (step 4, :328-390), and install the
fail-closed pre-commit hook where step 5 installs it (:392-457, displaced hook kept as pre-commit.local). Reuse
bootstrap's own steps through a non-interactive mode that skips the venv (step 1), the resolver check that needs the
venv (step 6's python half) and doctor (step 7); no second copy of any step. No network, no pip, no prompt. When step
5 cannot install (core.hooksPath from global or system config), finish the other steps and name it in the notice.
The `git config` writes run inside the hook process: hooks/pretool-bash-safety.sh denies them to agent Bash calls
(config-keystone-write, :298, :367), which is why an agent cannot do this step and the landing must.

**R5 Seed the private-literal list.** Write `<home>/private-literals.txt` (mode 0600) only when it is absent or
empty; never rewrite or reorder a list that has lines. Sources, read after the migration:
- the new overlay's env values of the personal keys P7 moved there (the twelve former code defaults:
  CLAUDE_DEV_CONTAINERS, CLAUDE_DAEMON_RESTART_GRANT_HELPER, CLAUDE_PROTECTED_DAEMON_PREFIX and _TARGETS,
  CLAUDE_HARD_BANNED_SCRIPTS when it is not the shipped default (its plain-word alternatives only, not ERE syntax),
  CLAUDE_PROTECTED_PROCESS_FAMILY, CLAUDE_RESTART_ACCOUNTS_ROOT, WORKFLOW_PRUNE_ACCOUNTS_DIR and _PROJECT_DIRNAME,
  the e-mail part of CLAUDE_CHECKPOINT_EXTRA_TRAILER, PASEO_DAEMON_ACCOUNTS split into names, the account suffix of
  PASEO_DAEMON_MODEL) and GRAPHIFY_BIN; never CLAUDE_HOME;
- the overlay's permission entries that name an absolute path outside the harness home (the personal tool paths);
- the harness home's git `user.email` (local, else global); not `user.name`;
- the literal marker values `rev`'s scripts/check-public-core.sh holds: HARD_MARKERS, PARAM_MARKERS and WS_MARKER
  (at fe7700c8 and 09ab15bc :366-370, :543-547 and :54; f8c18c2 still holds the first two at :398-402 and :563-567
  and dropped WS_MARKER), read from the git blob with a generic parser. P8 removes these lists from the tracked
  engine and relies on this seeding for the owner's local coverage (the earlier P8 prompt's REQUEST step 1 asked
  him to copy them); this makes that step automatic.
Filters (D10 for the exact form, each covered by a test): split list values on their separators; trim; drop values
shorter than 4 characters; drop values equal to a default the tracked code or the clean settings.json ships; never
seed the bare owner name of the origin remote URL (it appears legitimately in the project's public URL; P8 uses the
same rule, and HARD_MARKERS already carries the remote's SSH form); de-duplicate. Print and log only counts per
source. In the PR, list for each class of the owner step this replaces (account names, e-mail addresses, private
project names, personal paths) the sources that cover it, with counts; a class that no source covers goes under
"Out of scope, found" (from the owner conversation: the private-literal step of the manual steps his 2026-10-18
statement refused named these classes; the refreshed P8 prompt expects this seed to cover each class).

**R6 Disable legacy auto-push hooks in the harness home.** In the three locations of fact 7, a post-commit file whose
content contains `GIT_AUTO_PUSH:-1` is made inert reversibly (renamed aside with its content kept, D10 for the name);
the keystone dispatcher then exits 0. The current opt-in template stays. A disabled combined "Git LFS + Auto-Push"
hook also carried the repository's LFS post-commit step (P0's REQUEST step 3): where git-lfs is installed, restore
the LFS hooks with `git lfs update --force` in that repository (it writes only that repository's hooks; never a
global config write). If the owner input says "also the other repositories", apply the same to each repository P0's
REQUEST would list. Report counts only.

**R7 Sessions that started before the landing.** In a Claude Code hook or tool process whose environment lacks
CLAUDE_HOME (it started before its settings carried the overlay), read GIT_AUTO_PUSH and the overlay-provided keys
from the harness home's current settings.json env at use time instead of the process env:
- the checkpoint push (`_checkpoint_rate_limited_push` :319-320): such a process pushes only when the rendered
  settings say exactly `1`;
- the bash-safety knobs (:377-387, :1816) and subagent_restart's CLAUDE_RESTART_ACCOUNTS_ROOT (:826): a key the
  process env lacks comes from the rendered settings. hooks/pretool-bash-safety.sh assigns its own CLAUDE_HOME at :8
  (script-relative), so test the process environment before that line.
A process outside Claude Code (a fswatch daemon, a plain shell, a cron job) keeps today's env-only rule, so a human
who exports GIT_AUTO_PUSH=1 for fswatch is unaffected. Identify a Claude Code process by a variable Claude Code sets
for hook and tool processes; check which one in the official hooks documentation and name it in the PR (the sandbox
replayer sets CLAUDECODE=1 and CLAUDE_PROJECT_DIR). An unreadable or invalid settings.json (S3 before the landing)
means no checkpoint push from such a process (D1: off unless an explicit `1`; its stale env is what this rule
replaces); for the other keys it falls back to the process env. The other readers
(scripts/prune-orphaned-workflow-bookmarks.sh :87-88, scripts/paseo-daemon-ledger.py :2799,
scripts/paseo-daemon-timers.py :146, the trailer :428) may use the same helper if that is a one-line change; list
what you left under "Out of scope, found". hooks/prompt-workflow.py's GRAPHIFY_BIN reader (:1533) is P1's file: leave
it. GIT_AUTO_PUSH's other readers need no change here: hooks/session-git-init.sh:135 runs only at session start,
hooks/git-fswatch.sh:336 runs outside Claude Code; the opt-in post-commit template
(hooks/git-hooks/post-commit-auto-push:16) runs in the committing process and its copies live in other repositories,
so name it under "Out of scope, found".

**R8 A stale fswatch daemon on the harness home.** A git-fswatch process whose watched path resolves to the harness
home and which started before the current hooks/git-fswatch.sh or hooks/lib/checkpoint-core.sh was written is
restarted with the current code: a systemd instance (git-fswatch@<instance>.service, read from the process's
cgroup) through `systemctl restart`, any other through stop and a detached start of the current script (as
fswatch-manager.sh does). The new process gets the stopped process's own environment (read from
/proc/<pid>/environ), never the triggering session's, so a session's GIT_AUTO_PUSH can never reach the daemon. Never
stop a daemon in the middle of its own git work (a git child process of it running, a git lock held, or a rebase or
merge in progress in its repository): skip it, say so in the notice and try again at the next trigger; killing it
between its stash, pull and pop would leave the stash or a stopped rebase behind. Other repositories' daemons only
with the owner input "also". A restart that fails is a notice, never a retry loop.

**R9 One plain line, one log.** The session sees at most one line per Stop from the landing, through the auto_commit
phase's systemMessage (combine it with auto-commit's own refused-snapshot notice when both occur): what was done or
why the landing waits (S4, lock taken, a failed step), with key names and counts only. The coordinator parses only
the last stdout line of a phase that exits 0 (fact 8), and the landing runs before auto-commit.sh's own output, so
the notice must come out as the script's last line on each of its exit-0 paths (:23, :29, :51, :57). Every landing
appends what it did to one log under `<home>/logs/` (counts, key names, revision ids; never a value). Exit 0 always.

**R10 Docs.** README.md: in the install section (:74-130) one short paragraph "Upgrading a home that predates the
overlay": the home lands by itself at the next turn end of any session, nothing to stop or type, what it writes, the
S4 case, and that `scripts/bootstrap --migrate-from` and `render-settings migrate` remain for homes without sessions;
the private-literal paragraph (:258-268, "only you fill it" at :259) says the landing seeds it once; the overlay
bullet (:166-167, "never by hooks or agents") names the landing as its one other writer. PUBLIC-CORE.md :46-48 and
:69-71, settings.machine.example.json:92, scripts/bootstrap's comment :228 and render-settings' docstring
:27 say who writes the overlay and the list now: init, or the landing once on an upgraded home. CLAUDE.md is not
edited. The PR body has no REQUEST for the owner: its first line says "Owner steps: none".

**R11 Tests.** CI-collected pytest cases (under tests/, next to tests/test_settings_filter.py, or a new module) for:
the migrate exclusion and the check line (R3); the state classification and the stash match (R2) on temporary git
repositories; rev detection with ORIG_HEAD overwritten; the seeding sources, filters and the no-print property (R5);
the legacy-hook signature (R6); the push and env rule for pre-landing, post-landing and non-Claude processes, and
with an invalid settings.json (R7).
Stand-in values only (for example acct-test-123, demo@example.invalid, /opt/demo/bin/tool). Each passes with HOME
and CLAUDE_CONFIG_DIR pointed at tmp_path and without.

### Technical choices you make (list each in the PR: choice / why / how to revert)

The trigger site; where the landing code lives (a render-settings subcommand or one script under scripts/install/);
how bootstrap's steps are reused without a terminal; rev detection; the reconstruction of the previous settings in S1
and S2; the stash match; how the staged paths are returned to unstaged; the lock; the notice wording and channel; the
log path; each seeding filter; the rename used for legacy hooks; the Claude-process variable and the helper's form
(bash and python); whether the GIT_AUTO_PUSH line fails the check; the daemon restart mechanism. Follow the
producer-side design doc, take the option with less code and fewer rules, and back each with a test.

## Background (in the extracted planning documents, `harness-repair-plan/`, and on GitHub)

- Pull request #4 (read it with the GitHub tools, read-only): the REQUEST section (the manual steps this phase
  automates, both orders), "What the migration writes", "Intended differences", and acceptance 2's semantic-diff
  method, which you reuse.
- `PLAN-v2.md`: section P7 (rows R2, R4, R5 and the risks), section P0 (the installed-push-hooks row), section 4
  (human-only actions, replaced here), section 13 (rows "P8 ... render-settings migrate", moved here; "P5 ...
  auto_commit phase is a Stop gate", why the landing never fails auto-commit.sh; "P5-a ... deny agent edits of
  .git/config, .git/hooks/, .gitattributes", which the landing is not subject to because it runs in a hook, not as an
  agent tool call).
- `prompts/P0.md` (row 1h and its REQUEST text), `prompts/P7.md` (R5 and the R2 fail-closed rule), `prompts/P8.md`
  (its P7b paragraph at the top, row 11 "(moved)", row 10's note that the marker values reach the owner's list
  through this seeding; `git log -p` of that file on the planning branch shows the earlier row 11, its acceptance
  test and REQUEST steps 1 and 4, which this phase replaces), `prompts/P1.md` (row 23: the coordinator relay).
- `landscape/00-INDEX.md`: D1.d (:842, the automatic push producers), F3.b (:1354, daemon paths rewrite the live
  tree), C1.b (:428), C2.b (:481) and C2.c (:492).
- `reports/runtime-verification.md` (how the sandbox replays hooks) and `tools/` (the kit).
- `docs/reference/close-commit-zero-failure-mechanism-20260928.md` in the repository (producer-side design).

## Out of scope

- Resolving a pull that stopped mid-rebase or mid-merge (S4). It holds the owner's own commits, so the landing only
  reports it.
- Making fswatch, /pull or /merge safe on the live tree in general (landscape F3.b): no edits to git-fswatch.sh's
  sync and pull logic, hooks/pull.sh, hooks/merge.sh or commands/pull.md (name fact 1's masked exit statuses under
  "Out of scope, found"). No automatic pull of the harness home.
- A session that started while settings.json held conflict markers stays without hooks until it ends (Claude Code
  reads hooks at session start); the landing shortens that window, nothing can reload such a session.
- A home that pulled P7 alone and was left in S3 or S4 (fact 9): P7b's code never reaches it, and you add nothing to
  pull it there. Put this case in "Pull paths and states" with its evidence; the reviewer takes it up with the owner.
- A per-account session whose HOME is not the harness home's parent: the clean form's hook paths resolve there only
  once CLAUDE_HOME is in its settings (P7's documented limit).
- `doctor --strict`'s fresh capability handshake (it needs a live host).
- P8's privacy engine, the marker lists in scripts/check-public-core.sh (read from git blobs here, never edited), CI;
  P1's coordinator, Stop plumbing and prompt-workflow.py; the remote refs and history (P11); an off-site backup of
  the home.
- Other repositories, unless the owner input says "also".

## DO NOT (this phase)

- Do not run the landing, `render-settings migrate|render|check`, `scripts/bootstrap`, `scripts/doctor`, a filter
  registration or any hook against your container's real `~/.claude` or real HOME: only inside `tools/ns.sh` /
  `tools/ns-alt.sh`, or in scratch clones with HOME, CLAUDE_CONFIG_DIR and GIT_CONFIG_GLOBAL pointed at scratch.
- Do not print, log, test with, commit or quote any value the migration or the seeding reads. Your sandbox runs the
  real pre-P7 code, which holds the owner's real defaults: assert on counts and sha256 only, and use a synthetic
  previous revision with stand-ins wherever a test prints literals (acceptance 10).
- Do not edit hooks/stop-workflow-coordinator.py, hooks/prompt-workflow.py, settings.json, scripts/check-public-core.sh,
  .github/workflows/baseline.yml, conftest.py, hooks/git-fswatch.sh's sync and pull functions, hooks/pull.sh,
  hooks/merge.sh or commands/pull.md. Register no new hook.
- Do not let the landing exit non-zero, block a Stop, call AskUserQuestion, fetch, pull, push, create a venv or reach
  the network.
- Do not abort, continue or reset a rebase or merge; do not drop, pop or apply a stash entry; no `git reset --hard`,
  `git clean`, `git checkout -- .`. Touch only settings.json's index entry and the paths a conflicted stash pop staged.
- Do not write an overlay that exists, rewrite a non-empty private-literal list, seed GIT_AUTO_PUSH "1", or change
  GIT_AUTO_PUSH's tracked value.
- Do not delete an installed hook; make it inert reversibly. Do not touch another repository without the owner input
  "also".
- Do not push to anything but your branch on origin. The bare repositories your tests push to live inside the sandbox
  or your scratch directory, never on the network.

## Acceptance tests (run each in the sandbox, paste the output in the PR)

Setup: `export SB=$SCRATCH/sb-p7b`, build the kit from your branch (`PYTHONDONTWRITEBYTECODE=1
harness-repair-plan/tools/sb-setup.sh "$PWD"`; re-run after every code change), and write your scenario scripts to
`$SB/payloads/` (never into the repository). For each "on f8c18c2's code" comparison, build a second kit
(`SB=$SCRATCH/sb-master`) from a scratch clone of the repository checked out at f8c18c2 (a clone, not a worktree).
Every scenario runs inside `harness-repair-plan/tools/ns.sh` (or ns-alt.sh) and starts from a pre-P7 live home built
the same way, by one script of yours, `live-home.sh <rev> <live-edit>`:
1. `NEW` = the kit's snapshot of your branch: on a fresh kit `git -C /root/.claude tag sb-new HEAD`, and every later
   run reuses `sb-new` (earlier scenarios move HEAD and add commits); a bare `/root/harness-origin.git` whose master
   is `$NEW`; origin of /root/.claude pointed at it and fetched;
2. save `<rev>`'s settings.json, hooks/git-fswatch.sh and hooks/pull.sh to `/mnt/sb/payloads/old-*` (the old session's
   hook list and the old pull code);
3. first delete what an earlier scenario left in the harness's git directory (sandbox scaffolding, not landing
   behaviour; tools/reset.sh does not do it): `refs/stash`, `.git/rebase-merge`, `.git/rebase-apply`, `MERGE_HEAD`,
   `.git/keystone-hooks`, a local `core.hooksPath` and every file in `.git/hooks/` except the samples; then
   `git -C /root/.claude checkout -q -f -B master <rev>`, upstream origin/master; remove any filter section, overlay,
   private-literals.txt and record; create `logs/` (a live home has it; without it the old `safe_pull`'s `tee`
   fails, fact 1);
4. the live edit, written the way the CLI writes (JSON, indent 2, non-ASCII characters kept: in Python
   `json.dumps(obj, indent=2, ensure_ascii=False)` plus a final newline; the default `ensure_ascii` rewrites every
   non-ASCII character of the old file, and then even `cli-merge` conflicts): `model` changed and one stand-in allow
   added (`cli-conflict`), or only the stand-in allow (`cli-merge`), or nothing (`none`); save the resulting file as
   `/mnt/sb/payloads/live-settings.json` (what `assert-landed.sh`'s live-model, live-allow and semantic-diff lines
   compare with; with `none` it equals `<rev>`'s file);
5. a pre-P0 hook installed: `git show 86d70265:hooks/git-hooks/post-commit-auto-push > .git/hooks/post-commit`, mode
   0755.
The sandbox home has no git identity: every commit a scenario makes in the harness home (acceptance 8, 9 and 10) runs
with GIT_AUTHOR_NAME, GIT_AUTHOR_EMAIL, GIT_COMMITTER_NAME and GIT_COMMITTER_EMAIL set to `sandbox` /
`sandbox@example.invalid` in that command's environment (without them the commit fails with "Author identity
unknown" and acceptance 8 turns into S3); write no identity into the home's git config except where acceptance 10
says so (R5 reads `user.email`).
Pull paths (each run with cwd /root/.claude; hooks/pull.sh works on its cwd): fswatch =
`bash -c 'source <(sed "\$d" /mnt/sb/payloads/old-git-fswatch.sh) /root/.claude; trap - SIGINT SIGTERM EXIT;
safe_pull; echo "safe_pull rc=$?"'`; /pull = `bash
/mnt/sb/payloads/old-pull.sh`; merge = `git pull --no-rebase --no-edit origin master`. A pre-landing session's Stop =
`python3 /mnt/sb/tools/runhook.py --settings /mnt/sb/payloads/old-settings.json --event Stop --payload
/mnt/sb/payloads/stop.json --no-snap` (stop.json: session id, an existing empty transcript, cwd /root/.claude,
stop_hook_active false); a post-pull session's Stop = the same with `--settings /root/.claude/settings.json`. Your
`assert-landed.sh` prints exactly these lines (each must read as shown):

```
stop verdict: ok
settings.json: json=yes markers=0 machine-form=yes
index: unmerged=0 settings.json-staged=no other-staged=0
filter: clean=set smudge=set required=true   record: present mode=600
overlay: present mode=600 git-auto-push-1=no live-model=kept live-allow=kept
semantic diff vs the live file: only the intended differences
pre-commit: installed
private-literals: present mode=600 lines>=1 seeded-values-in-output=0
legacy post-commit hooks active: 0
```

1. **fswatch, conflicting live edit (S3), pre-landing session lands it.** `live-home.sh fe7700c8 cli-conflict`; the
   fswatch pull prints git's `CONFLICT (content): Merge conflict in settings.json` (its own log line still says
   "Stashed changes restored" and `safe_pull rc=0`, fact 1) and `git status --porcelain` shows `UU settings.json`
   (fact 2); then the old-session Stop; `assert-landed.sh` as above, plus `stash entries: 1 (kept)`. The same pull
   and Stop on f8c18c2's code (before your change) leaves `UU settings.json` (show it).
2. **/pull, mergeable live edit (S2), post-pull session lands it.** `live-home.sh fe7700c8 cli-merge`, /pull, the
   post-pull session's Stop; `assert-landed.sh`, plus `stash entries: 0`.
3. **Merge pull with a clean tree (S1).** `live-home.sh fe7700c8 none`, the merge pull, the old-session Stop;
   `assert-landed.sh`; the semantic diff equals pull request #4's intended differences and nothing else.
4. **Pre-P0 home: push stays off.** `live-home.sh 09ab15bc none`, the fswatch pull, the old-session Stop (old
   settings from 09ab15bc, GIT_AUTO_PUSH "1"); `assert-landed.sh` (the semantic diff also lists GIT_AUTO_PUSH "0"
   against the live "1", intended under D1); the landing output names GIT_AUTO_PUSH as not migrated (no value).
   Separately, in a scratch clone: `python3 scripts/install/render-settings migrate --from 09ab15bc` on your branch
   writes no GIT_AUTO_PUSH; on f8c18c2 it writes "1" (show both).
5. **The check line.** In a landed home, add `"GIT_AUTO_PUSH": "1"` to the overlay's env by hand, `render-settings
   render`, `render-settings check`: one line naming GIT_AUTO_PUSH and that automatic pushes are on, exit code as you
   chose; without the key, no such line.
6. **A pre-landing session stops pushing.** After scenario 4, make a plain change in the kit's toy product repository
   and replay the old-session Stop with cwd /root/toyproj and `--env CHECKPOINT_PUSH_MIN_INTERVAL=0` (its env carries
   GIT_AUTO_PUSH "1" and no CLAUDE_HOME; the toy repository keeps the checkpoint push gate's content check out of the
   way): after 6 s `git -C /root/toyproj ls-remote origin 'refs/checkpoints/*' | wc -l` prints 0; on f8c18c2's code
   it prints 1 (show it). Positive control: the overlay's env set to GIT_AUTO_PUSH "1" and rendered, the same Stop:
   the ref appears within 20 s. Non-Claude control: in a scratch repository with a bare origin, a plain shell
   without the Claude Code variables, `GIT_AUTO_PUSH=1`, sourcing your hooks/lib/checkpoint-core.sh and calling
   `write_checkpoint`: pushed, as today.
7. **A pre-landing session sees the overlay's guard settings.** In a landed home set the overlay's
   CLAUDE_HARD_BANNED_SCRIPTS to a stand-in (`demo-recovery`) and render; replay a PreToolUse Bash payload
   `bash demo-recovery.sh` with the old settings (no CLAUDE_HOME): `BLOCK(exit2)` naming the hard-ban rule; the same
   replay on f8c18c2's code: `ok` (show it). A pytest case covers CLAUDE_RESTART_ACCOUNTS_ROOT for subagent_restart.
8. **A stopped rebase (S4) is left alone.** `live-home.sh fe7700c8 none`, then commit a `model` change to
   settings.json on the home (a local commit not on origin); the fswatch pull stops mid-rebase (`.git/rebase-merge`,
   `UU settings.json`, while its log says "Pull successful"); the old-session Stop: `stop verdict: ok`, one notice
   naming the stopped rebase and the conflicted-path count, and HEAD, the rebase-merge directory, the index, the
   stash list and `git diff` sha256 are identical before and after; no overlay.
9. **Legacy hooks.** Scenario 3 again, with a keystone layout added before the pull
   (`.git/keystone-hooks/preserved/post-commit` = the 86d70265 copy, the dispatcher scripts/install-git-keystone.sh
   writes, core.hooksPath set to the keystone directory). After the landing: no post-commit at those paths contains
   `GIT_AUTO_PUSH:-1` and is executable; a commit in the home from a plain shell with GIT_AUTO_PUSH unset leaves
   `git ls-remote /root/harness-origin.git 'refs/backups/*' | wc -l` at 0 after 6 s (on f8c18c2's code: 1). The
   current template installed on purpose in a scratch repository stays.
10. **Seeding, with stand-ins.** Build a synthetic previous revision inside the sandbox only: a commit on top of
    fe7700c8 whose DEFAULT_ACCOUNTS, PARAM_MARKERS, HARD_MARKERS and WS_MARKER values and whose overlay-bound
    defaults are stand-ins (acct-test-123, acct-test-456, /opt/demo/bin/tool, demo-daemon, ...; one stand-in account
    is `demo-owner`, because an account name can equal the remote's owner name), a git `user.email` of
    demo@example.invalid and an origin URL whose owner part is `demo-owner`. That commit conflicts with P7's edits of
    the same default lines, so every pull path would stop mid-merge (S4): move the home with
    `git checkout -q -B master origin/master` instead (its HEAD reflog then holds the synthetic commit as `rev`), set
    the origin URL after that move, then the old-session Stop lands it. `private-literals.txt` then holds exactly the
    expected stand-ins (print them; they are stand-ins), not `demo-owner`, nothing shorter than 4 characters, no
    shipped default. A commit in the home that adds a file containing acct-test-123 is refused by the
    pre-commit hook; an unrelated public change commits. In scenarios 1-4 (real values), print only the counts and
    `seeded-values-in-output=0`, computed by grepping every landing output, notice and log for each seeded line.
11. **Idempotent and cheap.** A second Stop on a landed home: sha256 of the overlay, settings.json, the record, the
    list and `git config --local --list` unchanged. Cost: the median of 10 timed runs of the auto_commit phase alone
    (`bash /root/.claude/hooks/auto-commit.sh`, stop.json on stdin, cwd /root/.claude) on a landed clean home is
    within 50 ms of the same measurement on f8c18c2's kit, whose home is the scenario 3 home after P7's manual
    `scripts/bootstrap --yes --migrate-from ORIG_HEAD --no-doctor`. Stale installed hook (R1): on the same landed
    home, commit a stand-in comment line to hooks/git-hooks/pre-commit (a sandbox commit, identity as above) and
    replay the old-session Stop: the installed pre-commit is byte-identical to the new source, `assert-landed.sh`
    passes, the sha256 values listed above are unchanged, and the log names a step-5-only run; a third Stop changes
    nothing. The cost measurement includes the hook comparison. If P8's row 12 has merged, the same holds for each
    hook step 5 installs.
12. **Concurrent sessions.** Two Stops started together on an unlanded home (scenario 3 before its Stop): both
    `stop verdict: ok`; one overlay; `assert-landed.sh` passes; the log shows exactly one landing, and the other Stop
    either skipped on the lock or found the home landed (say which; both are correct).
13. **A fresh clone is not touched.** Inside ns-alt.sh, a fresh `git clone` of your branch at a scratch path (its
    reflog holds only the clone entry), without init: its clean settings.json replayed for a Stop with
    `--env CLAUDE_HOME=<that clone>` writes no overlay, list or record, adds no git config and shows no notice.
14. **Non-root layout.** Scenario 3 in ns-alt.sh (harness at /home/alice/.claude; `live-home.sh` and
    `assert-landed.sh` take the harness path from `RV_CLAUDE`), with the post-pull session's Stop
    (`--settings /home/alice/.claude/settings.json`): the pre-P7 settings name `/root/.claude/...` hook paths, which
    do not exist in that layout (python3 on a missing file exits 2). `assert-landed.sh` passes.
15. **Stale fswatch daemon.** Put a stub `fswatch` on PATH (a script that sleeps). After `live-home.sh fe7700c8 none`
    and before the pull, start /root/.claude/hooks/git-fswatch.sh (still the old file) on /root/.claude, detached,
    with `FSWATCH_DEBOUNCE=7` and without GIT_AUTO_PUSH in its environment (for example
    `env -u GIT_AUTO_PUSH FSWATCH_DEBOUNCE=7 setsid bash ... &`); then the merge pull and the old-session Stop given
    `--env GIT_AUTO_PUSH=1`: the old pid is gone; a new process runs the current script on /root/.claude; its
    /proc/<pid>/environ has `FSWATCH_DEBOUNCE=7` and no GIT_AUTO_PUSH; the log names the restart.
16. **Never a block.** Every Stop replay above prints `stop verdict: ok`. With the landing forced to fail (an overlay
    path that cannot be written; the sandbox runs as root, which ignores file modes, so use for example a directory
    or a dangling symlink at that path), the Stop is still `ok` and the notice names the failed step.
17. **Unit tests.** `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/test_settings_filter.py
    <your new modules>` passes, and passes again with HOME and CLAUDE_CONFIG_DIR pointed at a temporary directory.
18. **CI baseline and net code.** The workflow steps run locally on origin/master and on your branch: no new failure.
    `git diff --numstat origin/master -- hooks scripts schemas` totals reported in the two groups of "Net code cap".
19. **Privacy.** A personal-value and secret-pattern scan of your diff, commit messages and PR text: zero hits (counts
    only). `git diff origin/master -- commands/commit.md commands/close.md agents/changelog-analyst.md` is empty.

## Rules added / retired (expected)

Added: none expected. The landing is a producer step, not an enforcement rule; the GIT_AUTO_PUSH line inside the
existing settings check changes a rule. If you make it a separate check, retire one rule for it or fold it in
(principle 4). Changed, counted as neither: migrate no longer seeding GIT_AUTO_PUSH "1" (a defect fix under D1); the
checkpoint push and the overlay keys read from the rendered settings in pre-landing sessions (defect fixes under D1
and D15). Retired: none in code. The human steps of PLAN-v2.md section 4 (P0 and P7 rows), pull request #4's REQUEST
and the earlier P8 prompt's REQUEST steps 1 and 4 become the landing; they are not enforcement rules. Report what you
actually did.

## Net code cap

PLAN-v2.md has no row for P7b. The two groups follow P7's row (scripts/bootstrap and scripts/install/ reported
apart):
- hooks/, schemas/ and scripts/ outside scripts/bootstrap and scripts/install/: <= +60 net lines (the trigger, the
  push switch, the pre-landing env helper and its call sites). This departs from PLAN-v2.md section 3 ("Only P2, P6
  and P7's init/install code may be positive"; P7's own row: <= 0 outside bootstrap and install), so keep it as low
  as the requirements allow and justify each line;
- scripts/bootstrap and scripts/install/: report the number; target <= +250 (the landing, the migrate change, the
  seeding, the legacy-hook and daemon steps).
Tests excluded. Justify every added block in the PR.

Effort: M (about 1.5 days). Owner time: none.

## Branch and pull request

Dependencies: start only after P0 (PR #2), P0b (PR #3) and P7 (PR #4) are merged (the two checks under "Before you
start"); P1 and P8 need not be merged. Run `git log --oneline f8c18c2..origin/master` before you start and again
before you ask for review, and say in the PR which phases had merged.

Start from `origin/master`. If you were given the planning branch `claude/vibrant-hopper-bazrn8` or no branch, create
`repair/P7b` from `origin/master` and use it; never push anywhere else. One PR to master, titled `P7b: <short goal>`.
Body as in "Pull request" below, starting with the line "Owner steps: none.", and under Notes for reviewers also:
"Pull paths and states" (each pull path x S1-S4: what the home looked like before and after, with the evidence) and
"What the landing writes" (keys and counts only). Subscribe to your PR and drive it until it is merged; never merge
it yourself.

## Context (read once)

This repository is a Claude Code harness (hooks, commands, agents, scripts). On the owner's machine the
repository IS `~/.claude`, so every merged change goes live there. It is also a published product that
anyone can clone. In this cloud session the harness is NOT installed: never install it into your own
`~/.claude`, never point your own session at its hooks, never edit your container's `~/.claude`.

The repo's CLAUDE.md describes the harness's runtime rules on the owner's machine (orchestrator gate,
no branch/PR creation, etc.). For this task the owner explicitly authorizes exactly one branch: the one
this session was assigned, unless none was assigned or it is `claude/vibrant-hopper-bazrn8` (the planning-docs
branch, which you never push to); in those cases create `repair/<phase-id>` from `origin/master` and use it, commits and pushes to that branch,
and one pull request to `master`. Nothing else in CLAUDE.md is waived. Do not change CLAUDE.md wording.

`$SCRATCH` below means your session's scratchpad directory (named in your system prompt).

### Planning documents

They live on branch `claude/vibrant-hopper-bazrn8`, directory `harness-repair-plan/`. Extract them OUTSIDE
the repository (your scratchpad) and never commit them:

    git fetch origin claude/vibrant-hopper-bazrn8
    mkdir -p "$SCRATCH/plan" && git archive FETCH_HEAD harness-repair-plan | tar -x -C "$SCRATCH/plan"

Read, in this order: `harness-repair-plan/DECISIONS.md` (owner decisions; they override every plan),
`harness-repair-plan/README.md` (index + sandbox usage), then the plan section and landscape files your
prompt names (`PLAN-v2.md` is the current plan where your prompt names it; `PLAN-v1.md` is the earlier
version and loses wherever the two differ). Line numbers in the docs are at master 09ab15b; earlier phases may have moved them, so
re-verify each one against current `origin/master` before editing.

Start your branch from the latest `origin/master`, never from `claude/vibrant-hopper-bazrn8` (that branch is
master plus the planning documents; basing on it would put them into your PR). Check before you change
anything: `git fetch origin master && git log --oneline origin/master..HEAD` must print nothing. If it prints
commits that are not yours, move your branch to `origin/master` first (you have no work on it yet).
If you cannot fetch or read the planning documents, stop and tell the owner instead of guessing.

## Principles (all phases)

1. **Producer-side only.** Fix the single producer of an artifact (hook, launcher, UserPromptSubmit hook,
   producer prompt, renderer, CI). Never add consumer-side checks; nothing new in /close, /commit or the
   changelog-analyst. Background: docs/reference/close-commit-zero-failure-mechanism-20260928.md.
2. **No new mutable runtime state.** Do not add state files, counters or flags that an agent could write.
3. **Net code.** Report `git diff --numstat origin/master -- hooks scripts schemas` (tests excluded) and
   respect your phase's cap.
4. **Rules retired >= rules added.** List every enforcement rule you add and every one you retire.
5. **Live tree safety.** Running sessions keep the hook list they loaded. Never delete a hook file that
   settings.json registers in the same change that unregisters it: turn it into an exit-0 stub instead.
6. **No feature retirement.** A capability may become optional or configurable, never removed.
7. **Technical choices (D10).** Decide pure technical choices yourself: follow the design doc, prefer the
   option with the least code and fewest rules, cover it with a regression test, and list it in the PR's
   technical-choices table (choice / why / how to revert). Ask the owner (AskUserQuestion) only for a real
   product decision that DECISIONS.md does not answer; never as a way to stop.
8. **Evidence by execution.** Every acceptance claim is backed by a command you ran (tests, sandbox hook
   replays with `harness-repair-plan/tools/`), with its output in the PR. Static reading is not evidence.

## DO NOT (all phases)

- Do not force-push, rebase or amend published commits, push to `master` or to any branch other than
  yours, merge or approve any PR (including your own), rewrite history, or delete remote refs or tags.
- Do not open more than one PR or create extra branches or worktrees.
- Do not read, copy, print or move credential files (`.claude.json`, `.credentials.json`, tokens,
  `~/.ccr`, anything under `~/.config` that holds secrets). Never print values from `.claude.json`.
- Do not skip, disable, xfail, quarantine or delete tests to get green, except deletions your prompt names
  explicitly. No `--no-verify`. No empty commits or close/reopen to kick CI.
- Do not edit files outside your phase's scope, and do not reformat unrelated code. If you find an
  out-of-scope defect, note it in the PR under "Out of scope, found" instead of fixing it.
- Do not add personal values (account names, email addresses, private project names, personal home
  paths) to any tracked file, including tests, docs and commit messages.
- Do not leave caches in the repo: run every python/pytest with `PYTHONDONTWRITEBYTECODE=1` and
  `-p no:cacheprovider`; `git status` must show only intended changes.
- Do not run nested `claude` CLI sessions. Do not put model identifiers in commits or the PR.
- Do not touch `harness-repair-plan/` in your branch.

## CI

Baseline CI (`.github/workflows/baseline.yml`) has been red on master since 2026-07-26 (latest run at
09ab15b failed). Before changing anything, run the workflow's steps locally on python 3.12 against
`origin/master` and record which steps/tests fail. Repeat on your branch. Your PR must add no new failure.
Pre-existing failures outside your scope are not yours to fix (phase P8 makes CI green); list them in the PR.

## Pull request

Title: `<phase-id>: <short goal>`. Body: the headings of `.github/PULL_REQUEST_TEMPLATE.md` (Summary,
Type of change, Checklist, Notes for reviewers), and under Notes for reviewers add:

- **Changes**: each file with file:line and one line on what changed.
- **Decisions applied**: which DECISIONS.md items and how.
- **Technical choices**: table choice / why / how to revert.
- **Test evidence**: commands and their output (CI baseline before/after, acceptance tests, sandbox replays).
- **Rules added / retired**: two lists.
- **Net code lines**: the numstat totals for hooks/ scripts/ schemas/.
- **Rollback**: how to undo.
- **Out of scope, found**: anything you noticed but did not fix.

After opening the PR, subscribe to its activity and drive it: answer and fix every review comment, keep
CI no worse than master, and when master moves (another phase merged) merge `origin/master` into your
branch (a merge commit; no rebase) and resolve conflicts. Stop when the PR is merged or closed.
The reviewer merges; you never do.
