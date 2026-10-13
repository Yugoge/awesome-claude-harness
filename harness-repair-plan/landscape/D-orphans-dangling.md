# D-orphans-dangling: producer/consumer mismatches (D1, D2)

Repository: /home/user/awesome-claude-harness @ 09ab15b (read-only). All file:line citations refer to that tree.
Scratch copy (byte-identical to all 893 tracked files, verified with `cmp`):
`scratchpad/landscape-work/D-orphans-dangling/repo`. Working files, scripts and raw outputs:
`scratchpad/landscape-work/D-orphans-dangling/v2/` (`reach3.py`/`reach3.json` reachability, `brokenrefs.json`,
`docsdev_rows.json`, `indexreadme.txt`, `lsremote.txt`, sandboxes `toy/` and `cp/`).
Prior evidence re-used and re-checked: `harness-cleanup/problems.md` (X-ids), `harness-cleanup/file-manifest.csv`
(manifest dispositions). Where this file disagrees with them, it says so.

Binding frame: every fix acts on the PRODUCER of the artifact: the hook, script or prompt that writes it, or the
settings entry that registers it. Nothing adds a check to /close or /commit, and nothing adds a mutable state file.
Under the no-retirement decision, each item is marked FEATURE-TIED (keep, fix the producer) or PURE DEAD (no feature
depends on it, so deleting it retires nothing).


## Totals at a glance

| Item | Count | Pure dead | Feature-tied (keep, fix producer) |
|---|---|---|---|
| D1.a hook scripts in neither settings file | 27 top-level + 2 git-hook templates | 19 files / 2,522 lines | 11 files / 2,392 lines (7 live via a command/installer, 4 orphan fswatch) |
| D1.b scripts/libs with no live caller | 44 (+1 false positive: core.json) | 40 files / 19,469 lines + companion tests | 4 files / 375 lines |
| D1.c generated INDEX/README (+CLAUDE.md) | 85 files / 4,593 lines; 3 generators; 17+ exclusion sites | 16 junk generated files (incl. commands/INDEX.md, README.md that register as commands) | doc-sync generator (make update-only) |
| D1.d auto-push to origin outside /push | 4 producers (P1 live, P2 opt-in daemon, P3 installed copies, P4 unreachable) | P3, P4 in repo | P1 checkpoint, P2 fswatch. **255 refs already on the public origin; one tree lists .claude.json** |
| D1.e outputs reaching no consumer | 13 no-effect registered hooks; 14 unread logs (7 = advisory-gate sinks) | — | owned by A1 / hook-architecture |
| D1.f agents never dispatched | 1 (git-edge-case-analyst) | — | 1 (decision U5) |
| D2.a Skill() denies naming nothing | 17 per file (34 lines) | 16 per file | code-review deny blocks the built-in (U2) |
| D2.b allow rules: missing / dead / never-matching | 2x2 missing; 7+6 dead-target lines; 13+14 repo-relative lines | missing + dead-target | 3 feature-tied targets kept |
| D2.c broken references in prompts | 12 functional; 10 provenance-only; 4 code-side; ~90 placeholders (not defects) | — | — |
| D2.d /spec to /dev hand-off | 3 consumer rules, 0 working auto paths (V3/V4) | — | fix at prompt-workflow.py (single producer) |
| D2.e docs/dev dependents | 260 files (R 1,015 / S 737 / N 177 / X 40 refs); 34 non-test files with S/N; 6 tests read the checkout's docs/dev | — | — |
| D2.f consumers whose producer is never invoked | 5 (keystone token, spec views, GIT_AUTO_PUSH, two env gates; + todo resolution root) | — | — |

---

## Verification log (executed this session, scratch only, PYTHONDONTWRITEBYTECODE=1, HOME redirected)

| # | What | Result |
|---|---|---|
| V1 | Every hook command in settings.json / settings.template.json vs `hooks/*.{py,sh}` on disk | 112 top-level hook scripts. settings.json has 83 registrations (82 distinct scripts, one of them scripts/canary-verify.sh); the template has 73 (72). 27 hook scripts are in NEITHER file. The template's 4 Stop phases (timelock, coverage, auto-commit, cleanup) are absent from settings.json, but settings.json runs them through stop-workflow-coordinator.py:63-68, so they are live |
| V2 | Token-indexed reachability (`v2/reach3.py`): roots = both settings files, the coordinator phases, installer entry points, prompts, CI and dynamic todo loads; edges = Python imports and non-docstring strings, non-comment shell lines | 354 executables, 289 reached, 65 not reached (`v2/reach3.out`). One false positive: scripts/install/profiles/core.json, which installer.py loads by name. The earlier regex pass (`reach2.py`) timed out at 900 s and was replaced |
| V3 | posttool-doc-sync.py run in a fresh product repo after a Write of `docs/dev/specs/my-feature-spec.md` (`v2/toy`) | rc=0. It **created** `CLAUDE.md` (repo root), `docs/dev/specs/README.md` and `docs/dev/specs/INDEX.md`. INDEX.md got the newest mtime |
| V4 | /dev-command auto-detect rule (`ls -t docs/dev/specs/*.md \| head -1`, dev-command.md:89) run on V3's tree | Selects **`docs/dev/specs/INDEX.md`** as the spec |
| V5 | Stop-phase `hooks/auto-commit.sh` in a product repo with a local bare `origin` and an untracked `app.py` (`v2/cp`) | rc=0. `refs/checkpoints/master` was created locally **and pushed to origin**. The pushed tree contains the never-committed `app.py`. No env var was set. With no `logs/` dir it first fails (the known B-cluster T3d) |
| V6 | `git ls-remote origin` on the published repo github.com/Yugoge/awesome-claude-harness (read-only) | 260 refs: **252 `refs/backups/claude/*`** (written by post-commit-auto-push) and **3 `refs/checkpoints/*`** (written by checkpoint-core) |
| V7 | Tree listing (`--filter=blob:none`, no blobs downloaded, probe repo deleted afterwards) of the public `refs/checkpoints/master` @ 1fb1fc7 (2026-07-17) | 550 paths. Two are not on master: `.claude/.hook-refactor-allow` and **`.claude.json`** (Claude Code's account/config file). Its content was not downloaded or read. checkpoint-core.sh:546 records this capture ("root cause: .claude.json was captured in b432fc54"). The exclusion added later (:87, 9d9e660, 2026-09-18) only covers future snapshots. The public ref is still there |
| V8 | Skill() rules vs commands/*.md and skills/*/SKILL.md | 17 of 36 deny rules in each file name nothing. All 19 human-only commands (disable-model-invocation) are denied, so the lesson-15 contract holds for every command that exists |
| V9 | Path references in commands/agents/skills/templates/CLAUDE.md and in hooks/scripts code (`v2/brokenrefs.json`), filtered by hand | Real dangling references are listed in D2.c. About 90 lines are illustrative placeholders (`scripts/xxx.sh`, `foo.md`, `validate-timeout.sh`), are not defects, and are listed in Appendix C |
| V10 | docs/dev references across all tracked files (`v2/docsdev_rows.json`) | 260 tracked files mention `docs/dev`. Most are runtime output paths that the pipeline writes into each project. 34 prompt/code/config/stray files cite specific static or stamped files in the author's gitignored docs/dev. 6 test files read the checkout's own docs/dev, so they fail on any clone |

Corrections to prior evidence:
- problems.md X51 counts "17 dead Skill() denies". That is confirmed, but there are 17 **per file** (34 lines in total), and one of them,
  `Skill(code-review:*)`, is not dead: it blocks the Claude Code **built-in** /code-review skill (settings.json:260).
- CLAUDE.md:102 says `hooks/stop-cleanup-allowlist.sh` "is not currently registered … so it does not reap". That is false:
  settings.json:819 → stop-workflow-coordinator.py:68 runs it on every Stop. See D4.
- reach3 flags scripts/install/profiles/core.json as unreached (the manifest has it as DECIDE). It is live: installer.py loads it by
  profile name (scripts/install/install:43,52,73). It is excluded from all counts.
- New since prior evidence: the public origin carries 255 auto-pushed refs, including a snapshot whose tree lists `.claude.json` (V6/V7).
  Doc-sync also makes /dev-command pick `docs/dev/specs/INDEX.md` as the spec (V3/V4).

---

## D1 — artifacts with a producer and no consumer

### D1.a Hook scripts registered in neither settings file (27 top-level .py/.sh, plus the fswatch systemd unit and 2 git-hook templates)

Live through another route (not orphans; listed so nobody deletes them on a "not registered" basis):

| File | Lines | How it is reached | Class |
|---|---|---|---|
| hooks/checkpoint.sh | 80 | /checkpoint backend: commands/checkpoint.md:13,39,42; commands/clean.md:482; commands/test.md:297 | FEATURE-TIED (live) |
| hooks/merge.sh | 358 | /merge backend: commands/merge.md:45,65,106,182 | FEATURE-TIED (live) |
| hooks/pull.sh | 207 | /pull backend: commands/pull.md:28,120 | FEATURE-TIED (live) |
| hooks/push.sh | 474 | /push backend: commands/push.md:9-17; scripts/execute-push.py:2 (os.execv) | FEATURE-TIED (live) |
| hooks/stop.sh | 30 | /stop backend: commands/stop.md:37; scripts/break-overnight-lock.py:8 | FEATURE-TIED (live) |
| hooks/capability-canary.py | 79 | scripts/capability-handshake.py:417 (scripts/doctor --strict); hooks/lib/capability_state.py:175 | FEATURE-TIED (public-core install profile) |
| hooks/pretool-capability-gate.py | 162 | Registered by the core install profile: scripts/install/profiles/core.json:21-23,51 | FEATURE-TIED (public-core install profile) |

Orphan feature (a documented feature with no installer in the repo, so it runs only if the user starts it by hand):

| File | Lines | Producer / consumer evidence | Class |
|---|---|---|---|
| hooks/git-fswatch.sh | 568 | Started only by hooks/git-fswatch@.service:11 (systemd, no installer in repo), hooks/start-fswatch-all.sh:62, hooks/fswatch-manager.sh:14. Pushes to origin (D1.d) | FEATURE-TIED (fswatch auto-sync; docs/reference/git-fswatch.md, fswatch-quickref.md) |
| hooks/fswatch-manager.sh | 309 | No caller. Manual tool. :261 cites `systemd/git-fswatch@.service`, which does not exist (the unit is hooks/git-fswatch@.service) | FEATURE-TIED (fswatch) |
| hooks/start-fswatch-all.sh | 94 | Named only by dead install-protection-all.sh:123,138 and protection-status.sh:84 | FEATURE-TIED (fswatch) |
| hooks/git-fswatch@.service | 31 | No installer. `Documentation=file://%h/.claude/docs/git-fswatch.md` (:3) is missing; the doc is docs/reference/git-fswatch.md | FEATURE-TIED (fswatch) |

PURE DEAD (no runtime path; no feature depends on them):

| File | Lines | Why dead (verified) | Companion tests / docs that go with it |
|---|---|---|---|
| hooks/audit-slashcommand.sh | 45 | Never registered; single commit e34918c | INDEX/README rows only |
| hooks/post_tool_use.sh | 59 | Never registered; echo-only hints | INDEX/README rows only |
| hooks/pre_slashcommand_validate.sh | 44 | Self-described "Documentation-only … performs no validation and exits 0" (:3-4) | INDEX/README rows only |
| hooks/pre_tool_use_safety.sh | 54 | Reads `$1` (:22); hooks receive JSON on stdin; superseded by pretool-bash-safety.sh | INDEX/README rows only |
| hooks/session_start.sh | 47 | Legacy duplicate of registered session-info.sh | INDEX/README rows only |
| hooks/hook-todo-injection.py | 236 | Unregistered since dec89cc; superseded by prompt-workflow.py:330-335 | hooks/README-TODO-INJECTION.md (whole file documents it) |
| hooks/install.sh | 191 | LEGACY banner :3, `exit 0` at :15, before the body | hooks/QUICKSTART.md (its own banner :3-8 says obsolete) |
| hooks/install-auto-sync.sh | 274 | LEGACY :3, `exit 0` :12. Its body also cites missing examples/settings-with-checkpoint.json (:101), hooks/git-watcher.sh (:217,:223), docs/auto-sync-analysis.md (:262,:273) | — |
| hooks/install-git-hooks.sh | 98 | LEGACY :3, `exit 0` :12. It was the only installer of hooks/git-hooks/pre-commit | tests/integration-test.sh:73,340 |
| hooks/install-protection-all.sh | 140 | LEGACY :3, `exit 0` :11. It was the only installer of post-commit-auto-push (:18,:57) | — |
| hooks/protection-status.sh | 86 | Reports a retired design (greps for a 'smart-checkpoint' hook and auto-push layers); its own :83 says the installer is disabled | — |
| hooks/post-commit-warn.sh | 29 | Byte-identical to registered posttool-git-warn.sh (`cmp` = identical) | tests/integration-test.sh:109 |
| hooks/pretool-baseline-snapshot-preflight.py | 102 | Header :9 and :49: "NOT registered" | hooks/tests/test_baseline_snapshot_preflight.py |
| hooks/pretool-overwrite-guard.py | 582 | Never registered since eed4787 (2026-08-07); its log logs/overwrite-guard.jsonl (:62) has no reader | hooks/tests/test_overwrite_guard.py, hooks/tests/fixtures/overwrite_corpus.json, tests/test_bash_write_targets_verb_narrowing.py (mixed); docs/reference/overwrite-prohibition.md |
| hooks/sessionstart-artifact-census.py | 298 | Never registered (f8d7b60, auto-bulk) | hooks/tests/test_sessionstart_artifact_census.py |
| hooks/git-hooks/post-commit-auto-push | 31 | Its only installers (install-auto-sync.sh:150,160; install-protection-all.sh:18) exit before reaching the cp. **Installed copies still run on the author's machine: 252 refs on the public origin (V6)** | hooks/git-hooks/INDEX.md, README.md |
| hooks/git-hooks/pre-commit | 40 | Only installer install-git-hooks.sh exits at :12. :19 embeds /root/.claude | — |
| hooks/pre-commit-check.sh | 74 | Reached only from hooks/git-hooks/pre-commit:32-33 (no live installer) | — |
| hooks/sentinel-lint.sh | 92 | Reached only from hooks/git-hooks/pre-commit:20-27 (no live installer) | policies/public-core-residue-allowlist.v1.json:873 |

Totals: pure dead 19 files / 2,522 lines. Feature-tied 11 files / 2,392 lines (7 live through another route,
4 orphan fswatch).

### D1.b Scripts and libraries with no live caller

Source: `v2/reach3.out`, re-checked against the manifest. One false positive is removed (core.json). Two more files the manifest
marks DELETE are in B2 scope and are not repeated here: scripts/commit.sh ("never commits"; reached from agents/ba.md:1329 and
dev-overnight.md:124) and scripts/update-overnight-state.sh (dev-overnight.md:275 mentions it, but no step runs it).

FEATURE-TIED (keep; the defect is that nothing calls them):

| File | Lines | Evidence | Pairs with |
|---|---|---|---|
| scripts/checkpoint-prune.sh | 236 | The only thing that trims `refs/checkpoints/*`. Nothing schedules it. Allowed at settings.json:115 / template:144 (repo-relative form, D2.b) | checkpoint feature: refs grow without bound locally and on origin |
| scripts/install-checkpoint-refspec.sh | 63 | Adds the `+refs/checkpoints/*` fetch refspec that docs/reference/checkpoint-mechanism.md:65-71 describes. Nothing calls it. settings.json:119 / template:145 | The only would-be consumer of the remote checkpoint refs (D1.d). Pure dead if remote push is removed |
| scripts/mint-git-blessed-token.sh | 50 | Sole producer of the keystone exemption token read by hooks/git-keystone/reference-transaction:44-63. Header :7-8 claims /commit, /push and /merge call it, but nothing does. settings.json:42 / template:129 | Overnight keystone. The exemption is reachable only by hand (consumer with no producer, D2.f) |
| hooks/lib/runtime_guard/__init__.py | 26 | Production execs hooks/lib/runtime_guard.py → `_core.py` (pretool-bash-safety.sh:289-292). The package `__init__` is imported only by 9 test files | Tests only (manifest: SIMPLIFY) |

PURE DEAD (no runtime path; no product feature; mostly abandoned-cycle landings):

| File | Lines | Why dead (verified) | Companion tests / data |
|---|---|---|---|
| scripts/laneb-integration-gate.py | 9,076 | Abandoned LANE-B cycle (b108c16). Hard-codes SESSION_ID (:41) and gitignored docs/dev paths (:45, :3452-3456, :5986) | hooks/tests/test_laneb_integration_gate.py |
| scripts/session-resources.py | 103 | Its only caller is laneb-integration-gate.py (:1680, :1802, :2652). Allowed at settings.json:191-192. The broker it provisions is never configured (X63) | (shares the laneb test) |
| hooks/lib/agent_temp_targets.py | 203 | No importer; landed in b108c16 | hooks/tests/test_laneb_agent_temp_targets.py, test_laneb_pretool_composition.py |
| hooks/lib/checkpoint_resources.py | 325 | No importer; landed in b108c16 | hooks/tests/test_laneb_checkpoint_resources.py; tests/test_spec_update_command_contracts.py:61 (mixed) |
| hooks/lib/negative_evidence.py | 1,639 | Only importer is the dead CLI below. Schema 'negative-evidence.v1' is not in schemas/registry.json | tests/test_negative_evidence.py |
| scripts/negative-evidence.py | 149 | No caller | (same test) |
| scripts/dev-fix.py | 3,249 | No `/dev --fix` exists in any command; landed in b108c16 | tests/test_dev_fix.py |
| scripts/check-todo-accounting.py | 390 | No caller; :16-30 freeze byte counts, so it breaks on any edit | tests/test_dev_todo_accounting.py |
| scripts/close-commit-repair-orchestrate.py | 366 | No caller; it is the only consumer of schemas/repair-map.v1.json | tests/test_repair_orchestrate.py, tests/test_repair_map_call_site_coverage.py |
| scripts/generate-repair-map.py | 395 | Its only consumer is dead (above). It also produces schemas/repair-map.v1.json, which nothing reads | tests/test_generate_repair_map.py; schemas/repair-map.v1.json (+ registry.json:16 row) |
| scripts/gen-test-baseline.py | 106 | No CI step runs 'check' | tests/baselines/default-run-failures.json |
| scripts/spec-update-contract.py | 1,288 | "Planner for /spec-update", but commands/spec-update.md never invokes it (abandoned cycle) | tests/test_spec_update_command_contracts.py, tests/test_mat_doc10_writer_order_contract.py |
| scripts/adjudicate-attribution-staging.py | 10 | CLI wrapper; tests only. The live path imports the lib directly (aggregate-dev-report.py) | hooks/tests/test_attribution_adjudicator.py (mixed) |
| scripts/attribution-aggregate-view.py | 10 | CLI; tests only | (same, mixed) |
| scripts/lib/attribution_aggregate_view.py | 242 | Its only caller is the dead CLI. Writes docs/dev/journal-view-<task>.json, which nothing reads | (same, mixed) |
| scripts/lib/dispatch_metadata.py | 173 | Its only caller is the dead CLI below | — |
| scripts/capture-dispatch-metadata.py | 13 | No caller (a78d248) | — |
| scripts/analyze-folder-history.sh | 38 | Self-described placeholder that prints fixed JSON (:15-37). Allowed at settings.json:114 / template:141 | — |
| scripts/check-security-hook-drift.sh | 178 | "Operator runs this manually; no CI integration this cycle" (:14-15); no caller | — |
| scripts/cleanup-close-force-sentinel.sh | 13 | rm-workaround; no caller | — |
| scripts/lifecycle-baseline-import.sh | 146 | One-time migration, finished. Allowed at settings.json:41 / template:175,180 | tests/score-lifecycle-contract/test-lifecycle-cas.sh, tests/TESTING.md:126 (mixed) |
| scripts/verify-claims-extended.sh | 580 | Not in CI or any command | — |
| scripts/prune-orphaned-workflow-bookmarks.sh | 213 | One-off incident tool (docs/reference/workflow-bookmark-orphans-20261005.md), machine defaults (/var/lib/claude-accounts :89) | — |
| scripts/repair-venv.sh | 190 | One-off (ticket-20260529); `scripts/bootstrap --force` already recreates the venv | docs/reference/venv-repair.md |
| scripts/regen-index-dirs.py | 103 | Guard-bypass wrapper (:5-7) for the removed /doc-sync command | hooks/tests/test_regen_index_dirs_script.py |
| hooks/lib/runtime_guard/__main__.py | 3 | No `python -m` caller anywhere | — |
| push.sh (repo root) | 71 | No in-repo caller; release-membership.v1.json:46,59 calls it a "private-lab maintainer pre-push wrapper" | ARCHITECTURE.md:228 (C3 overlap) |
| scripts/todo/code-review.py | 11 | No /code-review command exists. prompt-workflow.py:330-335 runs scripts/todo/<cmd>.py for ANY typed `/<cmd>` (extract_command_name :168-173), so typing the **built-in** /code-review injects this stale 6-step checklist (manifest reproduced this). **Actively harmful** | — |
| scripts/todo/deep-search.py, doc-gen.py, explain-code.py, optimize.py, playwright-helper.py, refactor.py, research-deep.py, security-check.py, site-navigate.py | 9-11 each (97) | No such command (83460ea, 2026-03-24) | — |
| scripts/todo/file-analyze.py, quick-prototype.py, reflect-search.py | 31 / 30 / 30 | No such command. Still allowed at settings.json:135-137 / template:122-124 | — |

Totals: pure dead 40 files / 19,469 lines, plus their companion tests. Feature-tied 4 files / 375 lines.

### D1.c Generated INDEX.md / README.md (and CLAUDE.md) with no consumer

Producers (generators):

| Producer | Registration / caller | What it writes |
|---|---|---|
| hooks/posttool-doc-sync.py → hooks/doc_sync/main.py | PostToolUse Write/Edit/NotebookEdit: settings.json:717, template:675 | After every Write/Edit of a file with a watched extension (main.py:25-29: .py .sh .md .json …) **in any repo**, `should_sync` (:49-57) is true even outside WATCHED_DIRS. It then regenerates README.md and INDEX.md in the parent dir (main.py:113-120) and the matching ~/.claude dir (:122-136). regen_index.py:223-236 and regen_readme.py:196-216 **create the file when absent**. patch_claude_md (patch.py:129-162) → claude.py ensure_claude_md (:18-30) **creates CLAUDE.md** in any project without one (V3) |
| hooks/userprompt-doc-sync-check.py | UserPromptSubmit: settings.json:360, template:352 | Runs every user turn; on deletions it regenerates or removes INDEX.md (:160-199) and injects additionalContext (:105-117) |
| scripts/generate-folder-index.sh, scripts/generate-folder-readme.sh, scripts/check-readme-freshness.sh | /clean via agents/rule-inspector.md:24,85-98; agents/cleaner.md:77,91; commands/clean.md:73,130,142 | A second, independent generator of the same files (D3) |
| scripts/regen-index-dirs.py | none (D1.b pure dead) | A third generator (bypass wrapper) |

Not excluded: `docs/dev/` (main.py:35-41 excludes `.claude/specs/` but not `docs/dev/specs/`), CLI-loaded directories
(`.claude/commands` and `.claude/agents` are in WATCHED_DIRS :18-24), and product repos generally.

Artifacts: 85 tracked INDEX.md/README.md files (4,593 lines). 61 carry an `<!-- AUTO:index-stats|readme-stats -->` region
and are regenerated on edit; 24 have no marker (older generators). Full list in Appendix A. 359 of 778 commits touch them.

Consumers: none read them as input. Instead, the following sites must **exclude** them (a cost the producer imposes on others):
hooks/check-todo-md-sync.py:43; hooks/posttool-command-frontmatter-validate.py:35; hooks/userprompt-doc-sync-check.py:39;
scripts/check-readme-freshness.sh:35; scripts/cleanup-tests-folder.sh:154; scripts/create-overnight-state.sh:501-503;
scripts/detect-orphan-agents.sh:149,195; scripts/detect-orphan-commands.sh:162,216; scripts/detect-orphan-scripts.sh:150,284-285;
scripts/spec-verify/spec-verify.py:196; scripts/spec-verify/spec_verify_gated.py:40; scripts/spec-verify/spec_verify_mandate.py:42;
scripts/verify-claims-extended.sh:103,116; scripts/verify-claims.sh:273; hooks/lib/attribution_journal.py:49;
scripts/aggregate-dev-report.py:3729; commands/dev.md:1040 (AC clarifier); .gitignore:191-194.
Two whole modules exist only to account for doc-sync's own side-effect files inside dev reports: hooks/doc_sync/hook_ledger.py (308 lines)
and hooks/doc_sync/ledger_contract.py (332 lines), merged by scripts/aggregate-dev-report.py:1190,1410 (hook_ledger.py:3-12 says so).
This couples doc-sync to A3, the dirty files_created input.

Where the output does reach a consumer, it is the wrong one:
1. **commands/INDEX.md and commands/README.md** (no frontmatter) sit in the directory Claude Code loads as slash commands, so every
   install sees `/INDEX` and `/README` commands. The harness's own capability gate counted them as routes ("10 as unmanifested_route
   (INDEX, README, …)", scripts/install/profiles/core.json:147). agents/INDEX.md and agents/README.md sit in the agent-definition
   directory without frontmatter.
2. **docs/dev/specs/INDEX.md/README.md** in product repos break the /spec→/dev hand-off (V4; D2.d).
3. **Product-repo CLAUDE.md** is created, and its AUTO blocks are patched in on each sync. Claude Code loads it into every session
   context (E3), and it appears as an unrequested file in the user's repo (E2).
4. commands/test.md:41,494 copies the harness's own tests/README.md and the generated tests/INDEX.md (163 lines listing harness tests)
   into product repos as "templates".

Classification: the doc-sync generator is FEATURE-TIED (keep; fix the producer). These generated files are PURE JUNK:
tests/generated/README.md, tests/generated/INDEX.md, tests/generated/20260704-134650/{INDEX,README}.md,
tests/generated/20260704-225139/{INDEX,README}.md, .claude/INDEX.md, .claude/README.md,
.claude/quarantined-phantom-dev-cycles/dev-20260915-020044/{INDEX,README}.md, hooks/git-hooks/{INDEX,README}.md (directory of dead
hooks), skills/.archive/frontend-design/{INDEX,README}.md, and commands/INDEX.md and commands/README.md (harmful: they register as commands).
The remaining folder READMEs render on GitHub for visitors to the published repo (a weak human consumer). The root README.md is the product
landing page (only its AUTO region is generated). The 746-line root INDEX.md and the other INDEX.md files have no reader.

### D1.d Automatic pushes to `origin` outside /push

| # | Producer (file:line) | Trigger and environment | What is pushed | Env gate | Consumer | Live? |
|---|---|---|---|---|---|---|
| P1 | hooks/lib/checkpoint-core.sh:322-390 `_checkpoint_rate_limited_push` → :400-413 worker `git push origin <sha>:refs/checkpoints/<branch>` (:409). Called after every successful checkpoint at :708 and :804 | (a) **every Stop with a dirty tree**: settings.json:819 → stop-workflow-coordinator.py:67 → auto-commit.sh:27,36 (template registers auto-commit.sh directly at :772); (b) PostToolUse Write/Edit once ≥ `GIT_CHECKPOINT_THRESHOLD` (settings.json:15 = 10) files are pending: settings.json:713 / template:671 → posttool-git-checkpoint.sh:11,63; (c) /checkpoint → checkpoint.sh:53; (d) the fswatch daemon → git-fswatch.sh:314. Runs in whatever repo the session is in (**product repos and the harness repo**), with the user's git credentials, in a detached background subshell (:388-390) | A snapshot of the whole working tree, **including untracked, never-committed files** (V5), to `refs/checkpoints/<branch>` | **None.** The only skip is "no origin remote" (:333). Rate limit `CHECKPOINT_PUSH_MIN_INTERVAL` 30 s (:67). The push has existed since 2026-04-16 (3f88c2f). The size gate (:179-235) came on 2026-06-16 (a46d6d5); the PII gate (:250-311) and the hard-exclude (:541-556) only on 2026-09-18 (9d9e660) | **None in the pipeline.** Only a manual fetch refspec (docs/reference/checkpoint-mechanism.md:65-71) set up by install-checkpoint-refspec.sh, which nothing calls | **YES.** Reproduced in V5. The public origin holds 3 such refs (V6); one tree lists `.claude.json` (V7) |
| P2 | hooks/git-fswatch.sh:335-385 `safe_push` → :357 `git push origin "$branch"`, called at :442. Also `git pull --rebase` at :210 | Only while the fswatch daemon runs (systemd unit hooks/git-fswatch@.service:11, or start-fswatch-all.sh:62; no installer in repo) | **refs/heads/<branch>**: real branch HEADs | None (FSWATCH_* only tune timing, :24-26) | origin branch | Only if the user started fswatch |
| P3 | hooks/git-hooks/post-commit-auto-push:21-28 `nohup git push "$REMOTE" "$SHA:refs/backups/claude/<branch>/<sha12>" &` | After every commit, in repos where a copy was installed into .git/hooks/post-commit (installers dead, D1.a) | One backup ref per commit | `GIT_AUTO_PUSH` (:15-16; settings.json:14 sets it to "1") | None | **Copies are installed on the author's machine:** 252 `refs/backups/claude/*` on the public origin (V6) |
| P4 | hooks/install-protection-all.sh:57 `nohup git push origin "$BRANCH"` | Unreachable (exit 0 at :11) | — | GIT_AUTO_PUSH (:53) | — | No |

`GIT_AUTO_PUSH: "1"` (settings.json:14, template:14) looks like the master switch, but checkpoint-core.sh never reads it. Only P3 and P4
(dead installers) do. A user who sets it to "0" still pushes checkpoints. CLAUDE.md:47-49 ("Automated snapshots go to
`refs/checkpoints/<branch>`; HEADs never advance") and checkpoint-mechanism.md never say that the snapshots are pushed (D4).
None of P1-P3 goes through /push, push-analyst, the push grant, the push guard, or a secret scan. The hook process runs `git` directly,
so pretool-git-privilege-guard.py never sees it. P1 and P2 are FEATURE-TIED (checkpoint, fswatch). P3 is PURE DEAD in the repo,
but installed copies are still live on the author's machine.

### D1.e Outputs that reach no consumer: registered hooks whose output is dropped, and logs nobody reads

Registered hooks that exit 0 and write only to stderr. Claude Code does not pass exit-0 stderr to the model, so these produce nothing
any consumer receives (verified by exit-code census; manifest DELETE):
posttool-git-warn.sh (settings.json:743; its matcher `Bash\(git commit.*\)` is matched against tool_name "Bash", so it never fires);
pretool-bisect-gate.sh (:591); pretool-bulk-commit-detector.py (:643); pretool-layer-escalation-check.sh (:587);
pretool-layer-match-gate.sh (:869); pretool-orchestrator-prompt-purity.py (:599; docstring :21-23 "warn-only — never blocks", yet
CLAUDE.md:125 cites it as Enforcement, D4); pretool-quality-gate.py (:496; `_grandfather_or_block` "always returns 0" :347);
pretool-subagent-code-block.py (:533); session-info.sh (:313; all output `>&2` :8-12); session-tmpfs-banner.sh (:340);
session-git-init.sh (:317; gated on CLAUDE_SESSION_GIT_INIT, which nothing sets, :15); subagent-stop-diff-check.sh (:865);
subagent-stop-guard-integrity.sh (:873).
Classification: these are FEATURE-TIED in name (warnings) but have no effect. They belong to the hook-architecture and D4 clusters;
the fix there is either to emit through a consumer (additionalContext / exit 2) or to unregister.

Log files with a writer and no reader (grep across all prompts, hooks and scripts finds only the writer):
logs/obligation-gate-advisory.jsonl (pretool-obligation-gate.py:77), logs/obligation-barrier-advisory.jsonl
(pretool-aggregate-check.py:385), logs/obligation-terminal-gate-advisory.jsonl (stop-obligation-gate.py:56;
posttool-overnight-loop.py:28), logs/artifact-contract-advisory.jsonl (subagentstop-artifact-contract-enforce.py:61,120),
logs/completion-terminal-gate-advisory.jsonl (stop-completion-gate.py:83), logs/do-report-gate-advisory.jsonl
(stop-do-report-gate.py:58; commands/do.md:53 only describes it), logs/lane-completeness-watch-advisory.jsonl
(posttool-lane-completeness-watch.py:68), logs/cp-enforce-advisory.jsonl (subagentstop-cp-enforce.py:7,36),
logs/overnight-self-repair.jsonl (pretool-overnight-hook-guard.py:60), logs/overnight-idle.jsonl
(notification-idle-overnight.py:16,49), logs/refusals.jsonl (pretool-git-privilege-guard.py:2269,2288),
completion-gate-audit.jsonl (stop-completion-gate.py:49,89), logs/checkpoint-push.log (checkpoint-core.sh:66),
docs/dev/journal-view-<task>.json (scripts/lib/attribution_aggregate_view.py, dead).
**The first seven are the sinks of the advisory-mode producer gates: A1's four switches (G1 dispatch, G2 producer-stop, G3 barrier, G4 terminal), plus the /do-report gate (B4) and the lane watch.** Advisory mode means the producer writes to a file that
nobody reads. Flipping A1's switches to block makes these sinks unnecessary, so the fix belongs to A1 and nothing is added here.

### D1.f Agent definitions no pipeline dispatches

agents/git-edge-case-analyst.md has zero dispatch sites. agents/cleanliness-inspector.md:173 claims it is "invoked by /test
orchestrator at runtime", but commands/test.md never names it. It appears only in the registry-arming role lists at
commands/dev.md:203 and dev-command.md:147. The spec subagent can still emit a view for it (agents/spec.md:55, :266, :448), and that
view has no consumer. FEATURE-TIED (no retirement); this needs a user decision: wire it into /test, or stop agents/spec.md offering it.

---

## D2 — consumers with no producer

### D2.a Skill() deny rules that name nothing (17 per file, 34 lines)

None of these names exists as commands/<name>.md, skills/<name>/SKILL.md or skills/.archive/<name>:

| Name | settings.json | settings.template.json | Note |
|---|---|---|---|
| code-review | :260 | :244 | **Collides with the Claude Code built-in /code-review skill.** This deny blocks the native skill. Not dead. User decision |
| deep-search | :262 | :246 | CLAUDE.md:117 still points to it (D2.c) |
| doc-gen | :267 | :251 | |
| doc-sync | :268 | :252 | Command removed. scripts/regen-index-dirs.py is its leftover bypass wrapper |
| explain-code | :269 | :253 | |
| file-analyze | :270 | :254 | scripts/todo/file-analyze.py is still allowed (D2.b) |
| fswatch | :271 | :255 | |
| optimize | :273 | :257 | |
| playwright-helper | :275 | :259 | |
| quick-commit | :278 | :262 | |
| quick-prototype | :279 | :263 | |
| refactor | :281 | :265 | |
| reflect-search | :282 | :267 | CLAUDE.md:117 |
| research-deep | :283 | :268 | CLAUDE.md:117 |
| search-tree | :285 | :269 | CLAUDE.md:117 |
| security-check | :286 | :270 | |
| site-navigate | :287 | :271 | CLAUDE.md:117 |

There are no Skill() allow or ask rules. The other 19 denies (allow … test) match existing human-only commands. The lesson-15 contract
holds for all of them; commands/codex.md and commands/tickets.md are model-invocable (no disable-model-invocation) and correctly not denied.

### D2.b Permission allow rules for missing, dead, or never-matching scripts

Missing target (file never existed at HEAD):
- settings.json:122 and template:168: `Bash(scripts/validate-dev-registry-enforcement.sh:*)`
- settings.json:140 and template:164: `Bash(source venv/bin/activate && python scripts/add-status-field.py:*)`

Target exists but is PURE DEAD (D1.b). The rule goes when the file goes:
settings.json:41 / template:175,180 (lifecycle-baseline-import.sh); settings.json:114 / template:141 (analyze-folder-history.sh);
settings.json:135-137 / template:122-124 (todo/file-analyze.py, quick-prototype.py, reflect-search.py);
settings.json:191-192 (session-resources.py).
Target is FEATURE-TIED but has no caller (keep the rule): settings.json:42 / template:129 (mint-git-blessed-token.sh);
settings.json:115 / template:144 (checkpoint-prune.sh); settings.json:119 / template:145 (install-checkpoint-refspec.sh).

Repo-relative form that matches only when the cwd is the harness checkout. Prompts invoke these scripts as `~/.claude/scripts/<x>`,
so the rule never matches the documented call:
settings.json:106,114-122,140,192,193 and template:140-145,164,168,173-177,188. Examples: generate-folder-index.sh (allowed as
`scripts/generate-folder-index.sh`, settings.json:117; invoked as `~/.claude/scripts/generate-folder-index.sh`, agents/rule-inspector.md:90),
discover-folders.sh (:116), generate-folder-readme.sh (:118), score-inject.sh (template:174). This overlaps D3 and C1.

### D2.c Broken file references in commands / agents / skills / CLAUDE.md

Functional (an agent is told to read or run the missing thing, or a rule depends on it):

| Location | Missing target | Status | Effect |
|---|---|---|---|
| CLAUDE.md:117 | `@deep-search` agent and commands `/deep-search`, `/research-deep`, `/search-tree`, `/reflect-search`, `/site-navigate` | None exist (agents/ holds 23 definitions, commands/ 21; none has these names) | The global rule loaded into every session routes multi-source research to nothing. The same names are Skill-denied (D2.a) |
| agents/ui-specialist.md:16; commands/dev-overnight.md:1892 | `~/.claude/docs/templates/design-handoff.example.json` | Never tracked; `docs/*` gitignored (.gitignore:67) | DESIGN_MODE output schema has no producer in the published repo |
| agents/ui-specialist.md:269 | `~/.claude/skills/ui-shared/enhancement-templates.md` | Never existed (no history) | Enhancement categories have no source |
| skills/ui-axe-injector/SKILL.md:95 | `~/.claude/scripts/axe-bump.sh` "(future)" | Never built | The skill's monthly bump procedure has no producer |
| commands/dev-command.md:69 | `~/.claude/docs/dev/command-development-patterns.md` ("Read that document before authoring or editing slash commands, subagents, or todo scripts") | gitignored docs/dev | Mandatory pre-read missing on every install |
| commands/dev-overnight.md:122 | `docs/dev/state-file-write-policy.md` ("for the full per-field write matrix") | gitignored | Missing |
| agents/ba.md:649; agents/qa.md:106 | Chinese reference-trigger word list in `docs/dev/ticket-20260527-132200.md` | gitignored. The list exists nowhere in the repo (grep for the words and for `candidate_anchors_resolved` finds only ba.md and qa.md) | BA's clarification-blocking procedure and QA Fail Gate G2 depend on a list nobody can read. The user writes in Chinese |
| commands/paseo-daemon.md:10-12, :257 | "adjudicated blueprint" `docs/dev/specs/20260826-132923/design/turn-3-solutions-adopted.md`, `docs/dev/specs/spec-20260826-132923.md`, `docs/dev/specs/spec-20260910-164747.md` | gitignored (X67) | A kept command cites binding design that no clone has |
| agents/qa.md:1197; commands/commit.md:900 | "frozen" `docs/dev/specs/spec-20260520-044700.md` | gitignored | Author-repo-only rule shipped to all users |
| commands/dev.md:1040 | `docs/dev/INDEX.md`, `docs/dev/specs/INDEX.md` (the "manually-managed INDEX files" clarifier) | gitignored, harness-local | Applies only inside the author's checkout |
| agents/cleanliness-inspector.md:173 | "git-edge-case-analyst (invoked by /test orchestrator at runtime)" | /test never invokes it | False claim (D1.f) |
| commands/test.md:41, :494 | `~/.claude/tests/` README.md + INDEX.md as product templates | Exists, but INDEX.md is the doc-sync inventory of the harness's own tests | Wrong content copied into product repos (D1.c) |

Provenance-only (a comment or prose cites a missing or private file; no reader acts on it). These are E3 stamps:
commands/close.md:32 (`/root/docs/dev/ba-spec-20260426-redev8.md`), :1002; commands/commit.md:884, :1015;
commands/dev.md:1749 (`/root/docs/dev/redev-prompt-purity-20260426-self-test.md`); commands/tickets.md:15;
agents/ba.md:1004; agents/style-inspector.md:341; skills/ui-shared/anti-pattern-catalog.yml:3; skills/ui-shared/rule-map.json:17.

Code-side references to removed or missing files:
scripts/aggregate-dev-report.py:2364 cites `scripts/check-owned-edits-ledger.py:127-165` as the algorithm's source (deleted in db52813);
hooks/git-fswatch@.service:3 (`%h/.claude/docs/git-fswatch.md`); hooks/fswatch-manager.sh:261 (`systemd/git-fswatch@.service`);
hooks/install-auto-sync.sh:101, :217, :223, :262, :273 (dead file).

All other path references in CLAUDE.md resolve: docs/reference/checkpoint-mechanism.md, hooks/pretool-orchestrator-gate.py,
pretool-read-size-guard.py, pretool-block-background-tasks.py, pretool-bash-safety.sh, pretool-block-branch-pr-worktree.py,
pretool-block-enterworktree.sh, hooks/lib/allowlist.py, posttool-allowlist-consume.py, stop-cleanup-allowlist.sh and
pretool-orchestrator-prompt-purity.py all exist. The defects at :102 and :125 are false claims about behaviour (D4), not broken paths.

### D2.d The /spec → /dev spec hand-off has no working path

Producer: /spec writes `docs/dev/specs/<id>.md` and promises "`/dev ← auto-detects this spec`", likewise for /dev-command and
/dev-overnight (commands/spec.md:483-489, :519). Consumers and their rules:

| Consumer | Rule | Why it never receives /spec's output |
|---|---|---|
| /dev (commands/dev.md:125-151) | Take the newest `docs/dev/specs/*.md`, but only if its mtime is **strictly newer than this /dev session's own `DEV_SESSION_ID`** timestamp | prompt-workflow.py mints DEV_SESSION_ID when /dev is submitted (local `datetime.now()`, :1461-1471; injected at :1905). /spec always finishes before /dev starts, so its spec is always older, and the result is always "auto-detect skipped: newest spec predates this session" (dev.md:148). Even when a spec is touched mid-session, `ls -t … \| head -1` returns doc-sync's INDEX.md/README.md first, because they are written after the spec (V3) |
| /dev-command (commands/dev-command.md:89-95) | Newest `docs/dev/specs/*.md`, no staleness guard, no INDEX exclusion | **Picks `docs/dev/specs/INDEX.md`** (V4). Without doc-sync it silently inherits any stale spec of any age |
| /dev-overnight (scripts/create-overnight-state.sh:500-517) | Newest `*.md` excluding INDEX/README, then a focus-match check | Inherits any older spec that passes the focus match; otherwise degrades to autonomous |
| /redev | Follows dev.md | Same as /dev |

So the only working route is an explicit `--spec <path>`, which /spec-update prints (spec-update.md:109-110) and /spec does not
reliably print. There are three different rules for one hand-off (D3). The doc-sync producer (D1.c) corrupts two of them. The
.spec-binding.json that /spec writes (spec.md:173-178) carries no session id, so no consumer can tie a spec to the session that wrote it.

### D2.e Tracked files that depend on the gitignored docs/dev

`.gitignore:173` ignores `docs/dev/` (and `docs/*` at :67). 260 tracked files mention it. Classes (Appendix B has every file):
- R: runtime output paths (`docs/dev/dev-report-<task>.json`, `docs/dev/specs/*.md`, …) that the pipeline itself writes into each
  project. They have a producer, so they are **not dangling**. 1,015 references.
- S: stamped task-id/date files from the author's past cycles (`docs/dev/ticket-20260808-035658-lanel.md`, …). 737 references.
- N: named static documents (`observations-ledger.md`, `command-development-patterns.md`, …). 177 references.
- X: illustrative examples. 40 references.

Dangling in prompt/code/config/stray files (every S/N line):
- Prompts (functional ones are in D2.c): agents/ba.md:468,495 (observations-ledger.md is a **per-repo runtime file BA itself
  creates**, so this has a producer and is not dangling), :649, :655, :1004; agents/qa.md:106, :1197, :1201;
  agents/style-inspector.md:341; commands/close.md:32, :1002; commands/commit.md:884, :900, :1015; commands/dev-command.md:69;
  commands/dev-overnight.md:122; commands/dev.md:1040, :1749; commands/paseo-daemon.md:11, :12, :257; commands/tickets.md:15;
  skills/ui-shared/anti-pattern-catalog.yml:3; skills/ui-shared/rule-map.json:17.
- Code (all provenance comments except where noted): hooks/lib/subagent_restart.py:739; hooks/pretool-aggregate-check.py:56, :379;
  hooks/pretool-bash-safety.sh:429, :529, :530, :536, :848; hooks/pretool-block-branch-pr-worktree.py:5;
  hooks/pretool-git-privilege-guard.py:399, :1563 (`peer-review-grant-parity.md` cited as the CRITICAL rationale);
  hooks/pretool-gitignore-preflight.py:60, :61, :104, :105, :182, :183, :265-268, :274, :324, :331-334 (example paths inside its
  docstring/tests-by-example); hooks/pretool-push-analyst-grant-guard.py:20, :375;
  hooks/subagentstop-artifact-contract-enforce.py:72; scripts/aggregate-dev-report.py:2644; scripts/check-overnight-reports.sh:6;
  scripts/commit.sh:16; scripts/dev-fix.py:952 (`docs/dev/.fix-locks`, a runtime path in a dead file); scripts/dev-lifecycle.py:5, :20, :21;
  scripts/install/profiles/core.json:146 (states outright that the handoff record is gitignored); scripts/laneb-integration-gate.py:45,
  :3452, :3454, :3456, :5986 (**reads** them; dead file); scripts/lib/soundness_gate.py:5; scripts/qa-manifest-guard.py:4;
  scripts/repair-venv.sh:4; scripts/spec-verify/spec_verify_parsers.py:3 ("Authoritative grammar: /root/docs/dev/specs/MONOLITH-WRITING-GUIDE.md
  R6.6": the spec-verify grammar's source of truth is unpublished); scripts/stage-owned-hunks.py:1384, :1429, :2828.
- Config: policies/tool-policy.v1.json:250 (`*/docs/dev/test-plan`, a runtime glob, fine); schemas/owned-edits-ledger.v1.json:49, :95.
- Stray tracked junk (E1): .claude/quarantined-phantom-dev-cycles/dev-20260915-020044/QUARANTINE-NOTE.md:12,
  original-path-manifest.json:135-136; .claude/scratch_write_report.py:132, :203, :207, :223; .claude/tmp-test-writer-gen-l7.py:5;
  .github/assets/pipeline-hero-sources.json:5, :10, :15, :20, :25, :30 (the README hero image's provenance points at gitignored
  files); .r05_part1.json:12, :18; .r05_part2.json:12, :18; .r05_part3.json:12, :18, :329; .scratch_subagentstop_ancestor.txt:71.

Tests that **read** the checkout's own docs/dev, so they fail on any fresh clone (C4 overlap):
hooks/tests/test_artifact_contract_enforce.py:2043; hooks/tests/test_contract_runtime_version_dispatch.py:234-235;
hooks/tests/test_dual_runtime_lifecycle_e2e.py:1204, :1207-1209; hooks/tests/test_obligation.py:36;
hooks/tests/test_tool_policy_contracts.py:19; tests/test_changelog_analyst_required_to_ship_sourcing.py:57.
The other 120 test files only build docs/dev trees inside temp fixtures. Their stamped names are E3 noise, not dependencies.

### D2.f Consumers whose only producer is never invoked

- hooks/git-keystone/reference-transaction:44-63 honours a blessed token (`CLAUDE_GIT_BLESSED_TOKEN` + grant dir) whose only producer,
  scripts/mint-git-blessed-token.sh, nothing calls (D1.b). Its header :7-8 claims /commit, /push and /merge call it (D4).
- Spec views for git-edge-case-analyst (agents/spec.md:266) are consumed by no dispatch (D1.f).
- `GIT_AUTO_PUSH` (settings.json:14) has no live consumer; checkpoint-core ignores it (D1.d).
- `CLAUDE_SESSION_GIT_INIT` (session-git-init.sh:15) and `CP_ENFORCE_MODE` (subagentstop-cp-enforce.py) are read by hooks, and no
  config produces them. A1 covers the gate switches.
- prompt-workflow.py:331-335 resolves the todo script from `PROJECT_DIR/scripts/todo/<cmd>.py` **before** the harness copy, so a product
  repo that ships its own `scripts/todo/clean.py` gets its code run on prompt submit. The consumer resolves from the wrong root
  (D3, security).

---

## Fix plan (producer-side, minimal, ordered by risk)

Each step is self-contained, adds no check at /close or /commit, and adds no mutable state file.

**Step 1: stop auto-publishing to origin (D1.d).** Effort S. Do this first: it is a privacy exposure on a public repo.
- hooks/lib/checkpoint-core.sh:322: make the first line of `_checkpoint_rate_limited_push` return 0 unless `GIT_AUTO_PUSH` is "1".
  This reuses the existing env var as the single opt-in, and its default when unset is off.
- hooks/git-fswatch.sh:442: put the same guard in front of `safe_push`.
- settings.template.json:14 (and settings.json:14 until C2 makes it rendered): set `"GIT_AUTO_PUSH": "0"`.
- Result: checkpoints stay local recovery refs, which is what CLAUDE.md:47-49 describes, and /push stays the only route to a remote.
  The mechanism is one switch read by the producer itself.
- Human-only follow-up (REQUEST; an agent may not delete remote refs): delete the 252 `refs/backups/claude/*` and 3 `refs/checkpoints/*`
  on github.com/Yugoge/awesome-claude-harness (list: `v2/lsremote.txt`).
- Assess the `.claude.json` that appears in the tree of `refs/checkpoints/master`@1fb1fc7 (public since 2026-07-17). Deleting the ref may
  not purge cached objects on the host.
- Remove installed `post-commit-auto-push` copies from `.git/hooks/post-commit` in the author's repos.

**Step 2: one producer for the /dev spec input (D2.d).** Effort M.
- hooks/prompt-workflow.py becomes the single resolver, run when the command starts.
  - In `_ordinary_dev_start` (:1840-1920), and for /dev-overnight before `create_overnight_state` (:1953-1955, which already forwards
    `--spec` at :561): when no `--spec` is given, read the session transcript (`transcript_path`, an existing channel; precedent
    prompt-workflow.py:801-833).
  - Take the last Write/Edit tool_use whose `file_path` matches `docs/dev/specs/*.md` and is not INDEX.md or README.md.
  - Emit `Spec: <abs path>` or `Spec: none` in the replay-stored start output (:1901-1920).
- Delete the three orchestrator-side detection rules, keeping the explicit `--spec` branches:
  - commands/dev.md:125-151
  - commands/dev-command.md:89-95
  - the auto-detect branch of scripts/create-overnight-state.sh:500-517
- dev.md, dev-command.md and dev-overnight.md consume the injected `Spec:` line.
- commands/spec.md:483-489 and :519 always print `/dev --spec <abs path>` as the cross-session route.
- Result: same-session /spec→/dev works, stale specs are never inherited, and INDEX.md is never selected. There is one producer and
  no new file.

**Step 3: make doc-sync update-only (D1.c).** Effort S.
- hooks/doc_sync/regen_index.py:223 and regen_readme.py:196: when the target file is absent, return a skip status and never create it.
- hooks/doc_sync/claude.py:18-30: `ensure_claude_md` never creates a file.
- hooks/doc_sync/main.py:35-41: add `docs/dev/` to EXCLUDED_PATTERNS.
- Delete the junk generated files listed in D1.c, including commands/INDEX.md, commands/README.md, agents/INDEX.md and
  agents/README.md. Once doc-sync is update-only they are never recreated.
- Result: nothing appears in product repos, in docs/dev/specs, or in the slash-command menu. The feature keeps working for the
  directories that keep a marker.
- The 17 exclusion sites listed in D1.c become harmless and are left alone (no consumer-side edits).

**Step 4: delete pure-dead producers in one change (D1.a, D1.b, plus their D2.a and D2.b rules).** Effort M.
- Files:
  - The 19 pure-dead hook files (D1.a).
  - The 40 pure-dead scripts/libs (D1.b).
  - Their companion tests. For mixed tests, edit only the dead cases: tests/test_spec_update_command_contracts.py,
    tests/test_bash_write_targets_verb_narrowing.py, hooks/tests/test_attribution_adjudicator.py, tests/integration-test.sh,
    tests/score-lifecycle-contract/test-lifecycle-cas.sh.
  - schemas/repair-map.v1.json and its schemas/registry.json:16 row.
  - tests/baselines/default-run-failures.json.
  - hooks/README-TODO-INJECTION.md and hooks/QUICKSTART.md.
- In the same change, remove from settings.template.json, and settings.json until C2:
  - the 17 dead Skill() denies (D2.a), except code-review pending decision U2;
  - the 2 missing-script allows (D2.b);
  - the dead-target allows (D2.b: 7 lines in settings.json, 6 in the template).
- No feature is retired: every feature-tied file listed in D1.a and D1.b stays.
- Risk: hidden dynamic callers (X83). Mitigations:
  - reach3 covers imports, string literals and the todo dynamic load.
  - The installed git pre-commit tests for the scripts with `-f` before calling them (hooks/git-hooks/pre-commit:20,32), so it
    degrades to a warning.

**Step 5: repair dangling prompt references (D2.c).** Effort S. Each item is a deletion or an inline; none adds a check.
- agents/ba.md:649 and agents/qa.md:106: inline the trigger-word list. The prompt is the rule's producer.
- agents/ui-specialist.md:269 and skills/ui-axe-injector/SKILL.md:95: delete the sentences that name never-built files.
- commands/dev-overnight.md:122, agents/qa.md:1197, commands/commit.md:900, commands/dev.md:1040: delete the harness-local or private
  clauses.
- agents/cleanliness-inspector.md:173: delete the false /test claim.
- commands/test.md:41 and :494: drop INDEX.md from the "template" copy list.
- scripts/aggregate-dev-report.py:2364, hooks/git-fswatch@.service:3, hooks/fswatch-manager.sh:261: correct the paths.
- CLAUDE.md:117, commands/dev-command.md:69, commands/paseo-daemon.md:10-12,:257, agents/ui-specialist.md:16 and
  commands/dev-overnight.md:1892 need a decision (U4, U6, U7).
- Provenance stamps in code comments are left to E3.

**Not done here, by design:**
- D1.e advisory sinks: fixed by A1 (flip to block; the sinks then go).
- D1.e no-effect registered hooks: hook-architecture and D4.
- B2 files: scripts/commit.sh, scripts/update-overnight-state.sh.
- The mint script's header claim (D4).

## User decisions

- **U1:** checkpoint push. Choose between off-by-default opt-in (recommended; one env var) and removing the push code entirely.
  Separately, authorize the human-only deletion of the 255 auto-pushed refs on the public origin. Also review the exposure of the
  `.claude.json` listed in the tree of `refs/checkpoints/master`@1fb1fc7 (its content was not inspected).
- **U2:** `Skill(code-review:*)` deny (settings.json:260, template:244). It blocks the built-in /code-review skill. Keep it if the model
  must not self-invoke the built-in; otherwise remove it with the other 16.
- **U3:** confirm these are abandoned-cycle code (PURE DEAD), not held features:
  - LANE-B: laneb-integration-gate, session-resources, agent_temp_targets, checkpoint_resources
  - negative-evidence (lib + CLI)
  - dev-fix
  - repair-map (orchestrate + generate)
  - the attribution CLIs and their libs
  - spec-update-contract
- **U4:** CLAUDE.md:117. Delete the deep-search routing line or replace it with native tools. CLAUDE.md is user-owned.
- **U5:** git-edge-case-analyst. Wire it into /test, or stop agents/spec.md offering it a view.
- **U6:** commands/paseo-daemon.md's binding blueprint and dev-command.md's tutorial. Either publish them under docs/reference or remove
  the references. paseo may be private (C3).
- **U7:** docs/templates/design-handoff.example.json. Ship it as a tracked template, if the author has it, or drop the two references.

## Cross-references

- A1: the advisory JSONL sinks (D1.e) are the outputs of the advisory gates.
- A3: doc-sync side-effect files and hook_ledger feed files_created.
- B2: commit.sh and update-overnight-state.sh. The keystone exemption has no producer (D2.f).
- C1: `/root/.claude` literals inside allow rules.
- C2: every settings edit lands in the template; settings.json drift.
- C3: `.claude.json` in a public ref; push.sh; private paths in docs/dev citations.
- C4: 6 tests read the checkout's docs/dev; companion tests of dead code.
- D3: three spec auto-detect rules; two INDEX generators; repo-relative vs absolute allow forms; the todo-script resolution root.
- D4: CLAUDE.md:102 (cleanup hook *is* run), CLAUDE.md:125 (purity hook is warn-only), mint-git-blessed-token.sh:7-8, and the
  checkpoint docs saying nothing about the push.
- E1: junk generated files and stray tracked files.
- E2: doc-sync writes into product repos.
- E3: task-id/date stamps citing docs/dev.
- F1: the removal policy needed for Step 4.

## Appendix A: all 85 tracked INDEX.md / README.md files

GEN = carries an AUTO region that doc-sync regenerates on edit; HAND = no marker. Class: JUNK = pure junk (E1); CLI-DIR = sits in a
directory Claude Code loads (commands/ registers it as a slash command); LANDING = product landing page; FOLDER-DOC = renders on GitHub
for repo visitors (weak human consumer; no machine consumer); INDEX = no reader at all.

| File | Lines | Marker | Class |
|---|---|---|---|
| hooks/README.md | 113 | GEN | FOLDER-DOC |
| policies/README.md | 12 | GEN | FOLDER-DOC |
| schemas/README.md | 12 | GEN | FOLDER-DOC |
| scripts/install/README.md | 12 | GEN | FOLDER-DOC |
| skills/ui-anti-pattern-catalog/README.md | 12 | GEN | FOLDER-DOC |
| skills/ui-apca-contrast/README.md | 12 | GEN | FOLDER-DOC |
| skills/ui-contextual-heuristics/README.md | 12 | GEN | FOLDER-DOC |
| skills/ui-shared/README.md | 12 | GEN | FOLDER-DOC |
| skills/ui-state-matrix/README.md | 12 | GEN | FOLDER-DOC |
| skills/ui-token-conformance/README.md | 12 | GEN | FOLDER-DOC |
| templates/README.md | 12 | GEN | FOLDER-DOC |
| tests/score-inject-contract/README.md | 12 | GEN | FOLDER-DOC |
| tests/score-lifecycle-contract/README.md | 12 | GEN | FOLDER-DOC |
| examples/guard-demo/README.md | 124 | GEN | FOLDER-DOC |
| .claude/README.md | 13 | GEN | JUNK |
| hooks/git-hooks/README.md | 13 | GEN | JUNK |
| tests/generated/20260704-134650/INDEX.md | 14 | GEN | JUNK |
| tests/generated/20260704-225139/INDEX.md | 14 | GEN | JUNK |
| scripts/README.md | 143 | GEN | FOLDER-DOC |
| scripts/install/profiles/INDEX.md | 15 | GEN | INDEX (no reader) |
| scripts/install/tests/INDEX.md | 15 | GEN | INDEX (no reader) |
| skills/ui-axe-injector/README.md | 15 | GEN | FOLDER-DOC |
| tests/fixtures/INDEX.md | 15 | GEN | INDEX (no reader) |
| tests/generated/README.md | 15 | GEN | JUNK |
| examples/guard-demo/INDEX.md | 16 | GEN | INDEX (no reader) |
| hooks/tests/fixtures/INDEX.md | 16 | GEN | INDEX (no reader) |
| tests/INDEX.md | 163 | GEN | INDEX (no reader) |
| .claude/quarantined-phantom-dev-cycles/dev-20260915-020044/README.md | 17 | GEN | JUNK |
| .claude/INDEX.md | 19 | GEN | JUNK |
| .claude/quarantined-phantom-dev-cycles/dev-20260915-020044/INDEX.md | 19 | GEN | JUNK |
| scripts/lib/README.md | 19 | GEN | FOLDER-DOC |
| scripts/INDEX.md | 190 | GEN | INDEX (no reader) |
| hooks/doc_sync/README.md | 20 | GEN | FOLDER-DOC |
| scripts/lib/INDEX.md | 21 | GEN | INDEX (no reader) |
| skills/README.md | 22 | GEN | FOLDER-DOC |
| tests/scripts/README.md | 22 | GEN | FOLDER-DOC |
| tools/demo/INDEX.md | 22 | GEN | INDEX (no reader) |
| hooks/lib/runtime_guard/INDEX.md | 24 | GEN | INDEX (no reader) |
| hooks/doc_sync/INDEX.md | 27 | GEN | INDEX (no reader) |
| scripts/install/INDEX.md | 27 | GEN | INDEX (no reader) |
| hooks/INDEX.md | 281 | GEN | INDEX (no reader) |
| commands/INDEX.md | 35 | GEN | CLI-DIR (harmful) |
| skills/INDEX.md | 35 | GEN | INDEX (no reader) |
| commands/README.md | 37 | GEN | CLI-DIR (harmful) |
| scripts/todo/README.md | 38 | GEN | FOLDER-DOC |
| agents/README.md | 39 | GEN | CLI-DIR (agents/, no frontmatter) |
| hooks/lib/README.md | 49 | GEN | FOLDER-DOC |
| hooks/lib/INDEX.md | 59 | GEN | INDEX (no reader) |
| README.md | 692 | GEN | LANDING (AUTO region only) |
| docs/reference/INDEX.md | 74 | GEN | INDEX (no reader) |
| INDEX.md | 746 | GEN | INDEX (no reader) |
| hooks/lib/runtime_guard/README.md | 9 | GEN | FOLDER-DOC |
| hooks/tests/fixtures/README.md | 9 | GEN | FOLDER-DOC |
| scripts/install/profiles/README.md | 9 | GEN | FOLDER-DOC |
| scripts/install/tests/README.md | 9 | GEN | FOLDER-DOC |
| tests/fixtures/README.md | 9 | GEN | FOLDER-DOC |
| tests/generated/20260704-134650/README.md | 9 | GEN | JUNK |
| tests/generated/20260704-225139/README.md | 9 | GEN | JUNK |
| tools/demo/README.md | 9 | GEN | FOLDER-DOC |
| hooks/tests/README.md | 98 | GEN | FOLDER-DOC |
| hooks/tests/INDEX.md | 99 | GEN | INDEX (no reader) |
| scripts/modern-git-slot/README.md | 125 | HAND | FOLDER-DOC |
| skills/ui-anti-pattern-catalog/INDEX.md | 13 | HAND | INDEX (no reader) |
| skills/ui-apca-contrast/INDEX.md | 13 | HAND | INDEX (no reader) |
| skills/ui-beauty-score/INDEX.md | 13 | HAND | INDEX (no reader) |
| skills/ui-contextual-heuristics/INDEX.md | 13 | HAND | INDEX (no reader) |
| skills/ui-state-matrix/INDEX.md | 13 | HAND | INDEX (no reader) |
| skills/ui-token-conformance/INDEX.md | 13 | HAND | INDEX (no reader) |
| tests/score-lifecycle-contract/INDEX.md | 13 | HAND | INDEX (no reader) |
| hooks/git-hooks/INDEX.md | 14 | HAND | JUNK |
| skills/ui-axe-injector/INDEX.md | 14 | HAND | INDEX (no reader) |
| templates/INDEX.md | 14 | HAND | INDEX (no reader) |
| tests/score-inject-contract/INDEX.md | 14 | HAND | INDEX (no reader) |
| policies/INDEX.md | 15 | HAND | INDEX (no reader) |
| skills/ui-shared/INDEX.md | 16 | HAND | INDEX (no reader) |
| skills/.archive/frontend-design/INDEX.md | 21 | HAND | JUNK |
| tests/scripts/INDEX.md | 23 | HAND | INDEX (no reader) |
| schemas/INDEX.md | 25 | HAND | INDEX (no reader) |
| tests/generated/INDEX.md | 324 | HAND | JUNK |
| scripts/todo/INDEX.md | 34 | HAND | INDEX (no reader) |
| agents/INDEX.md | 35 | HAND | CLI-DIR (agents/, no frontmatter) |
| skills/ui-beauty-score/README.md | 43 | HAND | FOLDER-DOC |
| tests/README.md | 43 | HAND | FOLDER-DOC |
| docs/reference/README.md | 45 | HAND | FOLDER-DOC |
| skills/.archive/frontend-design/README.md | 46 | HAND | JUNK |

## Appendix B: docs/dev references, every tracked file

R = runtime output path (has a producer); S = stamped evidence file from a past cycle; N = named static doc; X = example.
Prompt/code/config/stray S/N lines are listed in full in D2.e. Below: the totals, the test and doc files (S/N line numbers), and the
prompt/code/config files whose references are all runtime or example paths.

| category | files | R refs | S refs | N refs | X refs |
|---|---|---|---|---|---|
| prompt | 26 | 419 | 20 | 6 | 11 |
| code | 58 | 156 | 45 | 5 | 9 |
| config | 6 | 120 | 2 | 1 | 0 |
| stray | 11 | 10 | 22 | 0 | 0 |
| test | 126 | 140 | 542 | 153 | 20 |
| doc | 33 | 170 | 106 | 12 | 0 |

#### test files referencing docs/dev (S/N line numbers listed; R/X counted)

- hooks/tests/INDEX.md: S/N@-; R=1; X=0
- hooks/tests/README.md: S/N@-; R=1; X=0
- hooks/tests/_fixtures_obligation_terminal.py: S/N@56; R=0; X=0
- hooks/tests/test_ac10_verify.sh: S/N@10,43; R=0; X=0
- hooks/tests/test_ac3_verify.sh: S/N@38; R=0; X=0
- hooks/tests/test_ac5_verify.sh: S/N@57,58,66; R=2; X=0
- hooks/tests/test_ac9_verify.sh: S/N@25; R=0; X=0
- hooks/tests/test_agent_resolver.py: S/N@-; R=0; X=1
- hooks/tests/test_artifact_contract_enforce.py: S/N@661,686,714,769,824,825,871,911,948,1044,1084,1126; R=10; X=0
- hooks/tests/test_baseline_snapshot_preflight.py: S/N@34,36,37,38,88,103,104,105; R=0; X=0
- hooks/tests/test_bash_safety_git_clean.py: S/N@20; R=1; X=0
- hooks/tests/test_bash_write_targets_policy.py: S/N@-; R=0; X=2
- hooks/tests/test_bulk_commit_sentinel.py: S/N@519; R=0; X=0
- hooks/tests/test_checkpoint_pii_gate.sh: S/N@4; R=0; X=0
- hooks/tests/test_contract_runtime_version_dispatch.py: S/N@116,125,143; R=0; X=0
- hooks/tests/test_do_block_subagents.py: S/N@-; R=1; X=0
- hooks/tests/test_do_taskid_mint.py: S/N@-; R=2; X=0
- hooks/tests/test_doc_sync_hook_ledger.py: S/N@5; R=1; X=0
- hooks/tests/test_e2e_enforce.py: S/N@-; R=6; X=0
- hooks/tests/test_final_sweep.sh: S/N@121,122,126,160,164,168; R=2; X=0
- hooks/tests/test_git_prefix_enumeration.py: S/N@344; R=0; X=0
- hooks/tests/test_gitignore_preflight_close_contract.py: S/N@91,133,142,145,148,184,195,198,210,213,226,230,250,254,258,267,277,352,362,372,374,403,407,412,417,422,424,428,433,435,438,443,445,448,453,455,458,463,465,469 ...+49; R=29; X=0
- hooks/tests/test_laneb_integration_gate.py: S/N@29,42,43,44,749,862,928,1526,1618,1655,1801,1804,3098,3943,3946; R=3; X=0
- hooks/tests/test_obligation.py: S/N@40,54,58,71,118; R=0; X=0
- hooks/tests/test_posttool_overnight_loop_terminal_gate.py: S/N@69,71,208,292; R=0; X=0
- hooks/tests/test_push_sentinel_abort.sh: S/N@12; R=0; X=0
- hooks/tests/test_report_projection_contract.py: S/N@765; R=1; X=0
- hooks/tests/test_sessionstart_artifact_census.py: S/N@-; R=1; X=0
- hooks/tests/test_stop_do_report_gate.py: S/N@-; R=1; X=0
- hooks/tests/test_stop_obligation_gate.py: S/N@90,93,105,110,134,153,211; R=0; X=0
- hooks/tests/test_tool_policy_contracts.py: S/N@19; R=0; X=0
- tests/INDEX.md: S/N@25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,56,57,58,59,60,61,62,63,64,65,66 ...+11; R=0; X=0
- tests/_dev_lifecycle_fixtures.py: S/N@-; R=4; X=0
- tests/_late_repair_fixtures.py: S/N@-; R=1; X=0
- tests/fixtures/late_repair_golden/complete.json: S/N@3,4,5,6,7,9,20,21,22,23,24,26,35,40,41; R=0; X=0
- tests/fixtures/late_repair_golden/fanout.json: S/N@3,4,5,6,7,8,9,10,11,12,14,22,23,24,25,26,27,28,29,30,31,33,37,38,39,41,45,46,47,49,56,60,64,75,79,84,85,86,87,88; R=0; X=0
- tests/fixtures/late_repair_golden/mixed_integrity.json: S/N@3,4,5,6,7,9,20,21,22,23,24,26,31,36,46,51,52; R=0; X=0
- tests/fixtures/late_repair_golden/qa_only.json: S/N@3,4,5,6,7,9,20,21,22,23,24,26,31,41,46,47; R=0; X=0
- tests/fixtures/late_repair_golden/spec-20260907-115508-lawful-commit-channel.pre-r4.md: S/N@193,204,207; R=3; X=0
- tests/fixtures/paseo-usage-envelope-20260828.json: S/N@2; R=0; X=0
- tests/fresh-clone-bootstrap-smoke.sh: S/N@-; R=5; X=0
- tests/generated/20260704-134650/test_AC_A_a1b2c3d4e5f60001.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_B1_a1b2c3d4e5f60002.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_B2_a1b2c3d4e5f60003.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_B3_a1b2c3d4e5f60004.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_B4_a1b2c3d4e5f60005.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_B5_a1b2c3d4e5f60006.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_C1_a1b2c3d4e5f60007.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_C1b_a1b2c3d4e5f60007b.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_C2_a1b2c3d4e5f60008.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_C3_a1b2c3d4e5f60009.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_D_a1b2c3d4e5f60010.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_E1_a1b2c3d4e5f60011.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_E2_a1b2c3d4e5f60012.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_E3_a1b2c3d4e5f60013.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_E4_a1b2c3d4e5f60014.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_E5_a1b2c3d4e5f6001e.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_E6a_a1b2c3d4e5f6e6a0.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_E6b_a1b2c3d4e5f6e6b0.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_E6c_a1b2c3d4e5f6e6c0.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_F1_a1b2c3d4e5f60015.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_F2_a1b2c3d4e5f60016.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_F3_a1b2c3d4e5f60017.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_F4_a1b2c3d4e5f6001f.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_F5_a1b2c3d4e5f60020b.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_F6_a1b2c3d4e5f60020c.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_G1_a1b2c3d4e5f60018.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_G2_a1b2c3d4e5f60019.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_G3_a1b2c3d4e5f60020.py: S/N@1; R=0; X=0
- tests/generated/20260704-134650/test_AC_G4_a1b2c3d4e5f60021.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_E1_a1b2c3d4e5f60011.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_E2_a1b2c3d4e5f60012.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_E3_a1b2c3d4e5f60013.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_E4_a1b2c3d4e5f60014.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_E5_a1b2c3d4e5f6001e.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_E6a_a1b2c3d4e5f6e6a0.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_E6b_a1b2c3d4e5f6e6b0.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_E6c_a1b2c3d4e5f6e6c0.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_E7_e7a1b2c3d4e5f601.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_F10_f10a1b2c3d4e5f60.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_F11_f11a1b2c3d4e5f60.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_F1_a1b2c3d4e5f60015.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_F2_a1b2c3d4e5f60016.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_F3_a1b2c3d4e5f60017.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_F4_a1b2c3d4e5f6001f.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_F5_a1b2c3d4e5f60020b.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_F6_a1b2c3d4e5f60020c.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_F7_f7a1b2c3d4e5f601.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_F7b_f7ba1b2c3d4e5f60.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_F8_f8a1b2c3d4e5f601.py: S/N@1; R=0; X=0
- tests/generated/20260704-225139/test_AC_F9_f9a1b2c3d4e5f601.py: S/N@1; R=0; X=0
- tests/generated/INDEX.md: S/N@12,13,14,15,16,17,18,19,20,21,22,23,24,27,28,29,30,31,32,35,36,37,38,39,40,41,44,45,46,47,48,49,50,53,54,55,56,57,60,61 ...+183; R=0; X=0
- tests/score-inject-contract/runtime-verify.sh: S/N@13; R=0; X=0
- tests/score-inject-contract/test-inject-branches.sh: S/N@8; R=0; X=0
- tests/scripts/validate-venv-usage.py: S/N@-; R=1; X=0
- tests/scripts/validate-workflow-json-cleanup.py: S/N@-; R=2; X=0
- tests/test_ac_deviation_fanout_consumer.py: S/N@-; R=9; X=2
- tests/test_ac_deviation_record_chain.py: S/N@1144; R=7; X=0
- tests/test_aggregate_dev_report.py: S/N@494,2261,2380,2417,2457,2555,2597,2630,2674; R=2; X=0
- tests/test_aggregate_dev_report_hook_ledger.py: S/N@-; R=5; X=0
- tests/test_aggregate_dev_report_superseded_rounds.py: S/N@6,763; R=6; X=0
- tests/test_changelog_analyst_required_to_ship_sourcing.py: S/N@-; R=1; X=0
- tests/test_close_report_append.py: S/N@6,19,234; R=0; X=0
- tests/test_commit_multi_repo_plan.py: S/N@505,823,1157,1230,1264; R=2; X=0
- tests/test_completeness_channel_invariant.py: S/N@-; R=1; X=0
- tests/test_completeness_span_accounting.py: S/N@-; R=1; X=0
- tests/test_dev_fix.py: S/N@22,125,138,260,261,284,316,486,489,497,498,500,509,609,819,835,852,855,856,857,858,860,870,874,945,955,981,983,985,1021,1082,1094,1131,1267,1279,1358,1629,1637,1642; R=7; X=0
- tests/test_dev_lifecycle.py: S/N@-; R=1; X=0
- tests/test_generate_repair_map.py: S/N@4; R=0; X=0
- tests/test_late_repair_route.py: S/N@5; R=2; X=0
- tests/test_mat_doc10_writer_order_contract.py: S/N@23; R=2; X=0
- tests/test_parent_cycle_claimant_reader.py: S/N@-; R=4; X=0
- tests/test_paseo_daemon_ledger.py: S/N@5; R=0; X=3
- tests/test_paseo_usage_read.py: S/N@4; R=0; X=0
- tests/test_prompt_workflow_injection_cadence.py: S/N@28; R=0; X=0
- tests/test_refusal_record_consumers.py: S/N@4,313; R=0; X=0
- tests/test_repair_orchestrate.py: S/N@5,66,75,178,182; R=0; X=0
- tests/test_resolve_dev_artifact_chain.py: S/N@262,1160; R=1; X=0
- tests/test_resolve_spec_artifacts.py: S/N@-; R=1; X=0
- tests/test_spec_check_closed_slot.py: S/N@82,129; R=0; X=0
- tests/test_spec_update_command_contracts.py: S/N@341,1058,1100,1143,1183; R=1; X=12
- tests/test_stage_owned_hunks_boundary.py: S/N@4,32,62,77,515,521,653,782,811,894,946,1011,1074,1144; R=4; X=0
- tests/test_subagentstop_e2e_enforce.py: S/N@-; R=3; X=0
- tests/test_tool_policy_inference_note.py: S/N@361,395,396,424; R=2; X=0
- tests/verify-stop-spec-session-isolation.sh: S/N@17,18,20,25,28,82,84,156,216,240,242; R=0; X=0
- tests/ws2_zero_literal_gate.py: S/N@127; R=0; X=0

#### doc files referencing docs/dev (S/N line numbers listed; R/X counted)

- INDEX.md: S/N@447,553,676; R=6; X=0
- docs/THREAT-MODEL.md: S/N@92,398; R=0; X=0
- docs/reference/MORNING-20260907.md: S/N@523; R=6; X=0
- docs/reference/abandoned-cycles-20260905.md: S/N@18,20,32,33,305,396,408,409,410; R=8; X=0
- docs/reference/attribution-journal-consumer-cutover-20261004.md: S/N@-; R=1; X=0
- docs/reference/attribution-journal-cutover-flip-plan-20261003.md: S/N@-; R=5; X=0
- docs/reference/claim-verification-methodology-20260925.md: S/N@-; R=1; X=0
- docs/reference/close-commit-failure-inventory-20260927.md: S/N@-; R=1; X=0
- docs/reference/close-commit-zero-failure-mechanism-20260928.md: S/N@96,99,110; R=2; X=0
- docs/reference/controller-error-taxonomy-20260924.md: S/N@-; R=2; X=0
- docs/reference/dev-command-20261003-020648-takeover-record.md: S/N@4,5,19,66,67; R=3; X=0
- docs/reference/do-report-ledger-has-no-refresh-path-20261008.md: S/N@-; R=1; X=0
- docs/reference/harness-defects-20260906-controller.md: S/N@224,234; R=8; X=0
- docs/reference/harness-fix-status-20260905.md: S/N@5,677; R=5; X=0
- docs/reference/harness-issues-backlog.md: S/N@70,78,87,97,103,105,118,120,124,125,131,132,135,141,163,167,169,173,177,181,183,238,250,256; R=73; X=0
- docs/reference/lane-pol-catchup-plan-20260808-035658-lanepolcatchup.md: S/N@255; R=0; X=0
- docs/reference/launch-plan.md: S/N@4,5,267,268; R=0; X=0
- docs/reference/mat-doc10-writer-order.v2.json: S/N@37,118,121,139,148,149,157,205,210,215,237,239; R=3; X=0
- docs/reference/overnight-cycle-20260809-013317-shared-file-attribution-20260914.md: S/N@65,185,218,317,321,347,515; R=17; X=0
- docs/reference/overnight-reference.md: S/N@-; R=1; X=0
- docs/reference/overnight-worktree-20260810-test-gaps-20261005.md: S/N@7,38; R=4; X=0
- docs/reference/paseo-daemon-concurrent-staging-triple-repro-20260904-181435-20260914.md: S/N@49,56,178; R=0; X=0
- docs/reference/paseo-daemon-shared-file-attribution-20260913.md: S/N@44,61,105,180,217,219,281,284,285,299,409,410,471,473,474,475; R=7; X=0
- docs/reference/paseo-daemon-teachings-20260910.md: S/N@-; R=4; X=0
- docs/reference/quarantine-record-dev-20260915-020044.md: S/N@11,57,67,82; R=1; X=0
- docs/reference/recoverable-discard-register-20261005.md: S/N@-; R=3; X=0
- docs/reference/restart-detector-quota-text-match-false-positive-20260915.md: S/N@383,450; R=0; X=0
- docs/reference/roadmap-decomposition-productization.md: S/N@-; R=1; X=0
- docs/reference/tmpfs-persistent-backups-20261005.md: S/N@-; R=4; X=0
- hooks/INDEX.md: S/N@-; R=1; X=0
- scripts/INDEX.md: S/N@44,150; R=1; X=0
- scripts/README.md: S/N@94; R=1; X=0
- skills/ui-beauty-score/README.md: S/N@44; R=0; X=0

#### prompt/code/config files with only runtime-pattern (R) or example (X) references (not dangling)

- agents/changelog-analyst.md: R=16 X=0
- agents/cleanliness-inspector.md: R=2 X=0
- agents/dev.md: R=7 X=0
- agents/pm.md: R=1 X=0
- agents/spec.md: R=10 X=0
- agents/test-writer.md: R=2 X=0
- agents/ui-specialist.md: R=1 X=0
- agents/user.md: R=2 X=0
- commands/clean.md: R=1 X=0
- commands/do.md: R=1 X=0
- commands/spec-update.md: R=5 X=0
- commands/spec.md: R=22 X=0
- templates/overnight-spec.md: R=1 X=0
- templates/spec-template.md: R=1 X=0
- hooks/doc_sync/ledger_contract.py: R=1 X=0
- hooks/lib/contract_runtime.py: R=1 X=0
- hooks/lib/policy_registry.py: R=3 X=0
- hooks/posttool-lane-completeness-watch.py: R=2 X=0
- hooks/posttool-overnight-trace.py: R=1 X=0
- hooks/pretool-bash-views-guard.py: R=4 X=0
- hooks/pretool-bisect-gate.sh: R=1 X=0
- hooks/pretool-cp-checkin.py: R=2 X=0
- hooks/pretool-cp-state-write-guard.py: R=1 X=0
- hooks/pretool-do-block-subagents.py: R=2 X=0
- hooks/pretool-layer-escalation-check.sh: R=1 X=0
- hooks/pretool-layer-match-gate.sh: R=2 X=0
- hooks/pretool-obligation-gate.py: R=1 X=0
- hooks/pretool-orchestrator-prompt-purity.py: R=1 X=0
- hooks/prompt-workflow.py: R=3 X=0
- hooks/stop-completion-gate.py: R=6 X=0
- hooks/stop-do-report-gate.py: R=4 X=0
- hooks/stop-spec-coverage-enforce.py: R=4 X=0
- hooks/subagent-stop-diff-check.sh: R=1 X=0
- hooks/subagent-stop-guard-integrity.sh: R=1 X=0
- hooks/subagentstop-e2e-enforce.py: R=5 X=0
- scripts/build-pipelines-from-triage.py: R=2 X=0
- scripts/check-late-repair-provenance.py: R=1 X=0
- scripts/close-report-append.py: R=7 X=0
- scripts/close-scoring-decide.py: R=4 X=0
- scripts/create-overnight-state.sh: R=4 X=0
- scripts/lib/attribution_aggregate_view.py: R=1 X=0
- scripts/lib/candidate_tree.py: R=1 X=0
- scripts/lint-spec-id-centralization.py: R=2 X=0
- scripts/overnight-init.sh: R=1 X=0
- scripts/overnight-status.sh: R=2 X=0
- scripts/resolve-close-report.sh: R=8 X=0
- scripts/resolve-dev-artifact-chain.py: R=3 X=0
- scripts/resolve-spec-artifacts.py: R=4 X=0
- scripts/score-update.sh: R=2 X=0
- scripts/spec-update-contract.py: R=3 X=0
- scripts/step7-spec-update.py: R=2 X=0
- tools/demo/sample-trace.json: R=0 X=7
- schemas/cleanliness-inspector-report.v1.json: R=1 X=0
- schemas/prompt-inspector-report.v1.json: R=1 X=0
- schemas/style-inspector-report.v1.json: R=1 X=0
- schemas/test-writer-report.v1.json: R=1 X=0

## Appendix C: scanner hits that are NOT defects (illustrative placeholders, dotted module names, regex-escaped or wrapped paths)

Each was checked by hand. Placeholders (xxx, foo, example, validate-timeout, measure-api-latency, analyze, mycommand) are teaching
examples inside dev/qa/style-inspector/dev-command prompts. `hooks/lib/x.y` forms are Python dotted references to existing modules.
Trailing-hyphen forms are line-wrapped citations of files that exist. Regex-escaped forms (restart-subagents.py, spec-check.py,
write-bulk-commit-sentinel.py) name tracked scripts.

- agents/changelog-analyst.md:392 `agents/foo.md`
- agents/cleanliness-inspector.md:243 `commands/agents/scripts`
- agents/dev.md:401 `commands/xxx.md`
- agents/dev.md:407 `scripts/xxx.sh`
- agents/dev.md:411 `scripts/script-name.sh`
- agents/dev.md:414 `scripts/xxx.py`
- agents/dev.md:417 `scripts/xxx.py`
- agents/dev.md:419 `scripts/xxx.py`
- agents/dev.md:422 `hooks/xxx.sh`
- agents/dev.md:425 `hooks/xxx.sh`
- agents/dev.md:428 `scripts/todo/xxx.py`
- agents/dev.md:431 `scripts/todo/xxx.py`
- agents/dev.md:441 `scripts/new-script.sh`
- agents/dev.md:449 `scripts/validate-timeout.sh`
- agents/dev.md:456 `scripts/validate-timeout.sh`
- agents/dev.md:462 `scripts/validate-timeout.sh`
- agents/dev.md:623 `scripts/validate-timeout.sh`
- agents/dev.md:637 `scripts/validate-timeout.sh`
- agents/dev.md:668 `scripts/validate-timeout.sh`
- agents/dev.md:673 `scripts/measure-api-latency.sh`
- agents/dev.md:940 `scripts/measure-api-latency.sh`
- agents/dev.md:940 `scripts/validate-api-timeout.sh`
- agents/prompt-inspector.md:136 `commands/example.md`
- agents/prompt-inspector.md:163 `commands/example.md`
- agents/prompt-inspector.md:209 `commands/example.md`
- agents/qa.md:363 `scripts/validate-api-timeout.sh`
- agents/qa.md:460 `scripts/validate-api-timeout.sh`
- agents/qa.md:613 `scripts/deploy.sh`
- agents/qa.md:1222 `scripts/script-name.sh`
- agents/qa.md:1233 `scripts/todo/xxx.py`
- agents/qa.md:1243 `hooks/xxx.sh`
- agents/qa.md:1274 `scripts/delete-data.sh`
- agents/qa.md:1281 `scripts/validate-timeout.sh`
- agents/qa.md:1837 `scripts/validate-api-timeout.sh`
- agents/style-inspector.md:190 `scripts/delete-temp-files.sh`
- agents/style-inspector.md:236 `scripts/example.py`
- agents/style-inspector.md:248 `scripts/analyze.py`
- agents/style-inspector.md:255 `scripts/run-tests.sh`
- agents/style-inspector.md:288 `commands/deploy.md`
- agents/style-inspector.md:310 `scripts/enhance-deployment.sh`
- agents/style-inspector.md:373 `scripts/validate-timeout.sh`
- agents/style-inspector.md:374 `scripts/validate-endpoints.sh`
- agents/style-inspector.md:375 `scripts/validate-headers.sh`
- agents/style-inspector.md:378 `scripts/validate-api.sh`
- agents/style-inspector.md:387 `scripts/check-doc-references.sh`
- agents/style-inspector.md:539 `scripts/process.sh`
- agents/style-inspector.md:554 `scripts/X.py`
- agents/style-inspector.md:557 `scripts/foo.py`
- agents/style-inspector.md:558 `scripts/foo.sh`
- agents/style-inspector.md:567 `commands/generate.md`
- agents/style-inspector.md:568 `scripts/old_script.py`
- agents/style-inspector.md:584 `agents/foo.md`
- agents/style-inspector.md:642 `commands/agents`
- commands/clean.md:2 `scripts/tests`
- commands/close.md:567 `hooks/lib/contract_runtime.validate_artifact_for_obligation`
- commands/commit.md:406 `hooks/lib/harness_state_dir`
- commands/commit.md:425 `hooks/lib/commit_pipeline.verify_pipeline_dispatch`
- commands/commit.md:1032 `hooks/lib/commit_pipeline.verify_pipeline_dispatch`
- commands/dev-command.md:725 `scripts/new-script.sh`
- commands/dev-command.md:735 `scripts/new-script.sh`
- commands/dev-command.md:759 `scripts/validate-timeout.sh`
- commands/dev-command.md:760 `scripts/measure-api-latency.sh`
- commands/dev-command.md:1075 `scripts/validate-file-header.sh`
- commands/dev-command.md:1084 `scripts/validate-headers.sh`
- commands/dev-command.md:1135 `commands/analyze.md`
- commands/dev-command.md:1136 `agents/code-analyzer.md`
- commands/dev-command.md:1137 `scripts/todo/analyze.py`
- commands/dev-command.md:1154 `commands/analyze.md`
- commands/dev-command.md:1155 `scripts/todo/analyze.py`
- commands/dev.md:1127 `scripts/new-script.sh`
- commands/dev.md:1137 `scripts/new-script.sh`
- commands/dev.md:1161 `scripts/validate-timeout.sh`
- commands/dev.md:1162 `scripts/measure-api-latency.sh`
- commands/dev.md:1570 `scripts/validate-file-header.sh`
- commands/dev.md:1579 `scripts/validate-headers.sh`
- commands/dev.md:1616 `scripts/todo/mycommand.py`
- commands/dev.md:1664 `scripts/measure-api-latency.sh`
- commands/dev.md:1665 `scripts/validate-api-timeout.sh`
- hooks/doc_sync/main.py:36 `commands/scripts/`
- hooks/lib/claude_home.sh:20 `scripts/x.py`
- hooks/lib/claude_home.sh:21 `scripts/y.py`
- hooks/lib/policy_registry.py:5 `hooks/lib/claude_home`
- hooks/lib/subagent_restart.py:770 `docs/reference/restart-detector-quota-text-match-false-positive-`
- hooks/posttool-command-frontmatter-validate.py:29 `commands/something.md`
- hooks/pretool-aggregate-check.py:378 `docs/reference/close-commit-zero-failure-`
- hooks/pretool-baseline-snapshot-preflight.py:42 `hooks/pretool-gitignore-`
- hooks/pretool-bash-safety.sh:1533 `scripts/write-bulk-commit-sentinel`
- hooks/pretool-bash-safety.sh:1757 `scripts/write-bulk-`
- hooks/pretool-bash-views-guard.py:39 `scripts/spec-check`
- hooks/pretool-bulk-commit-detector.py:114 `hooks/foo.sh`
- hooks/pretool-capability-gate.py:10 `hooks/lib/capability_state.evaluate_activation`
- hooks/pretool-claude-config-guard.py:28 `hooks/commands`
- hooks/pretool-git-privilege-guard.py:135 `hooks/lib/commit_pipeline.verify_pipeline_dispatch`
- hooks/pretool-gitignore-preflight.py:16 `commands/close.md-mandated`
- hooks/pretool-gitignore-preflight.py:628 `commands/close.md-mandated`
- hooks/pretool-overnight-hook-guard.py:6 `hooks/state`
- hooks/pretool-overnight-hook-guard.py:855 `hooks/state`
- hooks/pretool-tool-policy.py:5 `hooks/lib/claude_home`
- hooks/pretool-workflow-gate.py:56 `scripts/restart-subagents`
- hooks/stop-cleanup-allowlist.sh:46 `hooks/lib/allowlist.reap_expired_sentinel_grants`
- hooks/subagentstop-artifact-contract-enforce.py:166 `scripts/close-report-`
- hooks/subagentstop-artifact-contract-enforce.py:427 `scripts/lib/attribution_`
- hooks/subagentstop-artifact-contract-enforce.py:445 `docs/reference/attribution-`
- scripts/aggregate-dev-report.py:2314 `hooks/tests/test_artifact_`
- scripts/aggregate-dev-report.py:3291 `docs/reference/attribution-journal-`
- scripts/capture-dispatch-metadata.py:4 `scripts/attribution-aggregate-`
- scripts/check-enforcement-evidence.py:1324 `hooks/tests/.enforcement-run-manifest.json`
- scripts/check-file-references.sh:26 `scripts/test-migration.sh`
- scripts/check-file-references.sh:334 `commands/agents/scripts`
- scripts/check-file-references.sh:347 `commands/agents/scripts/code`
- scripts/check-file-references.sh:392 `commands/agents/scripts`
- scripts/detect-orphan-scripts.sh:114 `scripts/X.py`
- scripts/detect-orphan-scripts.sh:134 `scripts/X.py`
- scripts/detect-orphan-scripts.sh:134 `scripts/X.sh`
- scripts/detect-orphan-scripts.sh:135 `scripts/check_page_height.py`
- scripts/detect-orphan-scripts.sh:152 `commands/agents/scripts`
- scripts/detect-orphan-scripts.sh:261 `commands/agents/scripts`
- scripts/detect-orphan-scripts.sh:309 `commands/agents/scripts`
- scripts/generate-repair-map.py:49 `docs/reference/close-commit-failure-`
- scripts/generate-repair-map.py:135 `docs/reference/close-commit-zero-failure-`
- scripts/lib/attribution_adjudicator.py:748 `docs/reference/attribution-journal-cutover-flip-plan-`
- scripts/lib/dispatch_metadata.py:14 `scripts/adjudicate-attribution-`
- scripts/overnight-git-selftest.sh:151 `hooks/reference-transaction`
- scripts/overnight-git-selftest.sh:152 `hooks/reference-transaction`
- scripts/overnight-git-selftest.sh:453 `hooks/reference-transaction`
- scripts/overnight-git-selftest.sh:454 `hooks/reference-transaction`
- scripts/qa-manifest-guard.py:47 `scripts/bar.py`
- scripts/resolve-commit-repos.py:474 `docs/reference/attribution-journal-cutover-`
- scripts/resolve-commit-repos.py:601 `agents/dev.md/schemas/owned-edits-ledger.v1.json`
- scripts/write-commit-grant.py:62 `hooks/lib/commit_pipeline.verify_pipeline_dispatch`
- scripts/write-commit-grant.py:448 `hooks/pretool-bash-`

## Appendix D: raw reachability output (v2/reach3.out; columns: file, lines, references by source kind, allow-rule mentions)

```
code 354 live 289 dead 65
DEAD	hooks/audit-slashcommand.sh	45	doc=3[INDEX.md:266,hooks/INDEX.md:163,hooks/README.md:12]	allow=
DEAD	hooks/fswatch-manager.sh	309	doc=28[INDEX.md:271,docs/reference/fswatch-quickref.md:9,docs/reference/fswatch-quickref.md:12]	allow=
DEAD	hooks/git-fswatch.sh	568	code=9[hooks/fswatch-manager.sh:14,hooks/fswatch-manager.sh:74,hooks/fswatch-manager.sh:103]; doc=11[INDEX.md:272,docs/reference/fswatch-quickref.md:36,docs/reference/fswatch-quickref.md:98]	allow=
DEAD	hooks/git-fswatch@.service	31	code=1[hooks/fswatch-manager.sh:261]; doc=4[INDEX.md:273,docs/reference/git-fswatch.md:115,hooks/INDEX.md:170]	allow=
DEAD	hooks/git-hooks/post-commit-auto-push	31	code=3[hooks/install-auto-sync.sh:150,hooks/install-auto-sync.sh:160,hooks/install-protection-all.sh:18]; doc=4[INDEX.md:142,hooks/INDEX.md:27,hooks/git-hooks/INDEX.md:10]	allow=
DEAD	hooks/hook-todo-injection.py	236	doc=8[INDEX.md:274,hooks/INDEX.md:171,hooks/README-TODO-INJECTION.md:5]	allow=
DEAD	hooks/install-auto-sync.sh	274	doc=3[INDEX.md:275,hooks/INDEX.md:172,hooks/README.md:20]	allow=
DEAD	hooks/install-git-hooks.sh	98	doc=3[INDEX.md:276,hooks/INDEX.md:173,hooks/README.md:21]; test=2[tests/integration-test.sh:73,tests/integration-test.sh:340]	allow=
DEAD	hooks/install-protection-all.sh	140	code=1[hooks/protection-status.sh:83]; doc=3[INDEX.md:277,hooks/INDEX.md:174,hooks/README.md:22]	allow=
DEAD	hooks/install.sh	191	doc=3[INDEX.md:278,hooks/INDEX.md:175,hooks/README.md:23]	allow=
DEAD	hooks/lib/agent_temp_targets.py	203	doc=4[INDEX.md:149,hooks/INDEX.md:44,hooks/lib/INDEX.md:23]; test=3[hooks/tests/test_laneb_agent_temp_targets.py:15,hooks/tests/test_laneb_pretool_composition.py:19,hooks/tests/test_laneb_pretool_composition.py:64]	allow=
DEAD	hooks/lib/checkpoint_resources.py	325	doc=4[INDEX.md:156,hooks/INDEX.md:51,hooks/lib/INDEX.md:30]; test=2[hooks/tests/test_laneb_checkpoint_resources.py:19,tests/test_spec_update_command_contracts.py:61]	allow=
DEAD	hooks/lib/negative_evidence.py	1639	code=1[scripts/negative-evidence.py:14]; doc=4[INDEX.md:170,hooks/INDEX.md:65,hooks/lib/INDEX.md:44]; test=1[tests/test_negative_evidence.py:18]	allow=
DEAD	hooks/lib/runtime_guard/__init__.py	26	test=28[hooks/tests/test_fail_closed_drift.py:60,hooks/tests/test_fail_closed_drift.py:66,hooks/tests/test_runtime_guard.py:140]	allow=
DEAD	hooks/lib/runtime_guard/__main__.py	3	doc=3[hooks/INDEX.md:33,hooks/lib/INDEX.md:12,hooks/lib/runtime_guard/INDEX.md:11]	allow=
DEAD	hooks/post-commit-warn.sh	29	doc=6[INDEX.md:281,INDEX.md:289,hooks/INDEX.md:178]; test=1[tests/integration-test.sh:109]	allow=
DEAD	hooks/post_tool_use.sh	59	doc=3[INDEX.md:282,hooks/INDEX.md:179,hooks/README.md:27]	allow=
DEAD	hooks/pre_slashcommand_validate.sh	44	doc=3[INDEX.md:302,hooks/INDEX.md:199,hooks/README.md:44]	allow=
DEAD	hooks/pre_tool_use_safety.sh	54	doc=3[INDEX.md:303,hooks/INDEX.md:200,hooks/README.md:45]	allow=
DEAD	hooks/pretool-baseline-snapshot-preflight.py	102	doc=7[INDEX.md:306,docs/reference/close-commit-failure-inventory-20260927.md:287,docs/reference/close-commit-failure-inventory-20260927.md:634]; test=1[hooks/tests/test_baseline_snapshot_preflight.py:25]	allow=
DEAD	hooks/pretool-overwrite-guard.py	582	doc=7[INDEX.md:328,docs/reference/overwrite-prohibition.md:3,docs/reference/overwrite-prohibition.md:155]; test=7[hooks/tests/fixtures/overwrite_corpus.json:4,hooks/tests/fixtures/overwrite_corpus.json:391,hooks/tests/fixtures/overwrite_corpus.json:444]	allow=
DEAD	hooks/protection-status.sh	86	code=2[hooks/install-protection-all.sh:139,hooks/start-fswatch-all.sh:90]; doc=3[INDEX.md:344,hooks/INDEX.md:241,hooks/README.md:79]	allow=
DEAD	hooks/session_start.sh	47	doc=3[INDEX.md:356,hooks/INDEX.md:253,hooks/README.md:88]	allow=
DEAD	hooks/sessionstart-artifact-census.py	298	doc=2[INDEX.md:358,hooks/INDEX.md:255]; test=1[hooks/tests/test_sessionstart_artifact_census.py:17]	allow=
DEAD	hooks/start-fswatch-all.sh	94	code=3[hooks/install-protection-all.sh:123,hooks/install-protection-all.sh:138,hooks/protection-status.sh:84]; doc=3[INDEX.md:359,hooks/INDEX.md:256,hooks/README.md:89]	allow=
DEAD	push.sh	71	doc=9[ARCHITECTURE.md:228,INDEX.md:346,INDEX.md:734]; policy=2[release-membership.v1.json:46,release-membership.v1.json:59]	allow=
DEAD	scripts/adjudicate-attribution-staging.py	10	code=1[scripts/lib/dispatch_metadata.py:125]; doc=5[INDEX.md:472,docs/reference/attribution-journal-cutover-flip-plan-20261003.md:10,docs/reference/attribution-journal-cutover-flip-plan-20261003.md:56]; test=2[hooks/tests/test_attribution_adjudicator.py:447,hooks/tests/test_attribution_adjudicator.py:472]	allow=
DEAD	scripts/analyze-folder-history.sh	38	doc=3[INDEX.md:475,scripts/INDEX.md:72,scripts/README.md:15]; settings=1[settings.json:114]; template=1[settings.template.json:141]	allow=settings.json:114,settings.template.json:141
DEAD	scripts/attribution-aggregate-view.py	10	code=1[scripts/lib/dispatch_metadata.py:125]; doc=5[INDEX.md:478,docs/reference/attribution-journal-cutover-flip-plan-20261003.md:11,docs/reference/attribution-journal-cutover-flip-plan-20261003.md:64]; test=1[hooks/tests/test_attribution_adjudicator.py:584]	allow=
DEAD	scripts/capture-dispatch-metadata.py	13	doc=3[INDEX.md:487,scripts/INDEX.md:84,scripts/README.md:27]	allow=
DEAD	scripts/check-security-hook-drift.sh	178	doc=3[INDEX.md:496,scripts/INDEX.md:93,scripts/README.md:36]	allow=
DEAD	scripts/check-todo-accounting.py	390	doc=3[INDEX.md:497,scripts/INDEX.md:94,scripts/README.md:37]; test=1[tests/test_dev_todo_accounting.py:12]	allow=
DEAD	scripts/checkpoint-prune.sh	236	doc=5[INDEX.md:498,docs/reference/workflow-bookmark-orphans-20261005.md:21,docs/reference/workflow-bookmark-orphans-20261005.md:23]; settings=1[settings.json:115]; template=1[settings.template.json:144]	allow=settings.json:115,settings.template.json:144
DEAD	scripts/cleanup-close-force-sentinel.sh	13	doc=5[INDEX.md:499,docs/reference/close-commit-failure-inventory-20260927.md:48,docs/reference/workflow-bookmark-orphans-20261005.md:21]	allow=
DEAD	scripts/close-commit-repair-orchestrate.py	366	doc=3[INDEX.md:500,scripts/INDEX.md:97,scripts/README.md:41]; test=2[tests/test_repair_map_call_site_coverage.py:54,tests/test_repair_orchestrate.py:21]	allow=
DEAD	scripts/dev-fix.py	3249	doc=3[INDEX.md:515,scripts/INDEX.md:112,scripts/README.md:56]; test=2[tests/test_dev_fix.py:20,tests/test_dev_fix.py:1548]	allow=
DEAD	scripts/gen-test-baseline.py	106	doc=4[INDEX.md:520,docs/reference/attribution-journal-cutover-flip-plan-20261003.md:100,scripts/INDEX.md:117]; test=1[tests/baselines/default-run-failures.json:69]	allow=
DEAD	scripts/generate-repair-map.py	395	doc=3[INDEX.md:524,scripts/INDEX.md:121,scripts/README.md:65]; policy=1[schemas/repair-map.v1.json:4]; test=1[tests/test_generate_repair_map.py:20]	allow=
DEAD	scripts/install-checkpoint-refspec.sh	63	doc=3[INDEX.md:529,scripts/INDEX.md:126,scripts/README.md:70]; settings=1[settings.json:119]; template=1[settings.template.json:145]	allow=settings.json:119,settings.template.json:145
DEAD	scripts/install/profiles/core.json	162	doc=3[scripts/INDEX.md:13,scripts/install/INDEX.md:12,scripts/install/profiles/INDEX.md:11]; test=2[scripts/install/tests/installer-acceptance.py:47,scripts/install/tests/installer-acceptance.py:78]	allow=
DEAD	scripts/laneb-integration-gate.py	9076	doc=3[INDEX.md:532,scripts/INDEX.md:129,scripts/README.md:73]; test=14[hooks/tests/test_laneb_integration_gate.py:27,hooks/tests/test_laneb_integration_gate.py:788,hooks/tests/test_laneb_integration_gate.py:810]	allow=
DEAD	scripts/lib/attribution_aggregate_view.py	242	code=1[scripts/attribution-aggregate-view.py:7]; doc=10[INDEX.md:430,INDEX.md:478,docs/reference/attribution-journal-consumer-cutover-20261004.md:46]; test=1[hooks/tests/test_attribution_adjudicator.py:33]	allow=
DEAD	scripts/lib/dispatch_metadata.py	173	code=1[scripts/capture-dispatch-metadata.py:10]; doc=3[INDEX.md:432,docs/reference/attribution-journal-consumer-cutover-20261004.md:12,scripts/INDEX.md:29]	allow=
DEAD	scripts/lifecycle-baseline-import.sh	146	doc=4[INDEX.md:534,docs/reference/harness-issues-backlog.md:121,scripts/INDEX.md:131]; settings=1[settings.json:41]; template=2[settings.template.json:175,settings.template.json:180]; test=2[tests/TESTING.md:126,tests/score-lifecycle-contract/test-lifecycle-cas.sh:3]	allow=settings.json:41,settings.template.json:175,settings.template.json:180
DEAD	scripts/mint-git-blessed-token.sh	50	doc=3[INDEX.md:538,scripts/INDEX.md:135,scripts/README.md:79]; settings=1[settings.json:42]; template=1[settings.template.json:129]	allow=settings.json:42,settings.template.json:129
DEAD	scripts/negative-evidence.py	149	doc=3[INDEX.md:539,scripts/INDEX.md:136,scripts/README.md:80]; test=3[tests/test_negative_evidence.py:95,tests/test_negative_evidence.py:472,tests/test_negative_evidence.py:523]	allow=
DEAD	scripts/prune-orphaned-workflow-bookmarks.sh	213	doc=4[INDEX.md:552,docs/reference/workflow-bookmark-orphans-20261005.md:23,scripts/INDEX.md:149]	allow=
DEAD	scripts/regen-index-dirs.py	103	doc=5[INDEX.md:556,docs/reference/harness-issues-backlog.md:127,docs/reference/harness-issues-backlog.md:157]; test=3[hooks/tests/test_regen_index_dirs_script.py:24,hooks/tests/test_regen_index_dirs_script.py:47,hooks/tests/test_regen_index_dirs_script.py:61]	allow=
DEAD	scripts/repair-venv.sh	190	doc=6[INDEX.md:557,docs/reference/venv-repair.md:3,docs/reference/venv-repair.md:9]	allow=
DEAD	scripts/session-resources.py	103	code=3[scripts/laneb-integration-gate.py:1680,scripts/laneb-integration-gate.py:1802,scripts/laneb-integration-gate.py:2652]; doc=4[INDEX.md:570,docs/reference/harness-issues-backlog.md:122,scripts/INDEX.md:167]; settings=2[settings.json:191,settings.json:192]; test=2[hooks/tests/test_laneb_integration_gate.py:649,hooks/tests/test_laneb_integration_gate.py:1161]	allow=settings.json:191,settings.json:192
DEAD	scripts/spec-update-contract.py	1288	doc=7[INDEX.md:572,docs/reference/mat-doc10-writer-order.v2.json:24,docs/reference/mat-doc10-writer-order.v2.json:31]; test=3[tests/test_mat_doc10_writer_order_contract.py:34,tests/test_spec_update_command_contracts.py:20,tests/test_spec_update_command_contracts.py:1204]	allow=
DEAD	scripts/todo/code-review.py	11	doc=4[INDEX.md:452,scripts/INDEX.md:49,scripts/todo/INDEX.md:12]	allow=
DEAD	scripts/todo/deep-search.py	11	doc=4[INDEX.md:453,scripts/INDEX.md:50,scripts/todo/INDEX.md:13]	allow=
DEAD	scripts/todo/doc-gen.py	10	doc=4[INDEX.md:458,scripts/INDEX.md:55,scripts/todo/INDEX.md:18]	allow=
DEAD	scripts/todo/explain-code.py	11	doc=4[INDEX.md:459,scripts/INDEX.md:56,scripts/todo/INDEX.md:19]	allow=
DEAD	scripts/todo/file-analyze.py	31	doc=4[INDEX.md:460,scripts/INDEX.md:57,scripts/todo/INDEX.md:20]; settings=1[settings.json:135]; template=1[settings.template.json:123]	allow=settings.json:135,settings.template.json:123
DEAD	scripts/todo/optimize.py	11	doc=4[INDEX.md:461,scripts/INDEX.md:58,scripts/todo/INDEX.md:21]	allow=
DEAD	scripts/todo/playwright-helper.py	9	doc=4[INDEX.md:462,scripts/INDEX.md:59,scripts/todo/INDEX.md:22]	allow=
DEAD	scripts/todo/quick-prototype.py	30	doc=4[INDEX.md:463,scripts/INDEX.md:60,scripts/todo/INDEX.md:23]; settings=1[settings.json:136]; template=1[settings.template.json:122]	allow=settings.json:136,settings.template.json:122
DEAD	scripts/todo/refactor.py	10	doc=4[INDEX.md:465,scripts/INDEX.md:62,scripts/todo/INDEX.md:25]	allow=
DEAD	scripts/todo/reflect-search.py	30	doc=4[INDEX.md:466,scripts/INDEX.md:63,scripts/todo/INDEX.md:26]; settings=1[settings.json:137]; template=1[settings.template.json:124]	allow=settings.json:137,settings.template.json:124
DEAD	scripts/todo/research-deep.py	11	doc=4[INDEX.md:467,scripts/INDEX.md:64,scripts/todo/INDEX.md:27]	allow=
DEAD	scripts/todo/security-check.py	11	doc=4[INDEX.md:468,scripts/INDEX.md:65,scripts/todo/INDEX.md:28]	allow=
DEAD	scripts/todo/site-navigate.py	11	doc=4[INDEX.md:469,scripts/INDEX.md:66,scripts/todo/INDEX.md:29]	allow=
DEAD	scripts/verify-claims-extended.sh	580	doc=3[INDEX.md:579,scripts/INDEX.md:176,scripts/README.md:120]	allow=
```
