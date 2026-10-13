# Cluster E-junk-runtime-prompts: complete inventory (E1, E2, E3, E4)

Repository: /home/user/awesome-claude-harness @ 09ab15b (893 tracked files; read-only). Every file:line refers to that tree.
Work dir (scripts, sandbox, raw outputs): `scratchpad/landscape-work/E-junk-runtime-prompts/`
(`classify.py` + `classified.json` = per-file E1 classes; `stamps2.py` + `stamps2.json` = stamp locations;
`sizes.py` + `sizes.json` = prompt sizes; `e4_table.py` = dated-doc verdicts; `sbx/` = sandbox runs; `pure_junk_refs.tsv` = reference check).
Prior evidence re-used and re-checked: `harness-cleanup/file-manifest.csv` (333 DELETE rows), `harness-cleanup/problems.md`
(X03, X06, X12, X14, X35, X38, X41, X46, X47, X61, X62, X65, X66), `wf2_result.json` themes "separating-source-from-runtime" and
"Prompt-layer diet", and the sibling inventory `landscape/D-orphans-dangling.md` (D1 reachability, which this file cross-references
instead of repeating).

Binding frame. One producer per artifact, and correctness is enforced at the producer by hooks. Every fix below changes the producer:
the hook or script that writes the file, the prompt that is the producer of prompt text, or the settings entry that registers it.
Nothing below adds a check to /close or /commit, and nothing adds a mutable state file. User decisions applied: the repo is a
published, general-purpose product; no feature is retired for now; live sessions keep editing the harness (status quo).

---

## 0. Summary

| Problem | What is wrong (measured) | Minimal producer-side fix |
|---|---|---|
| E1 deletable set | The manifest's 333 DELETE rows are not one set. 202 files / 55,270 lines are pure junk and safe to delete now. 50 are generated INDEX/README stubs tied to the per-folder convention. 44 are feature-tied and blocked by the hold. 23 are product surface (KEEP under the published-product decision; the manifest assumed a personal tool). 14 need a decision. Plus 5 missed junk files (2,681 lines) and 4 harmful generated files the manifest only marked MOVE_OUT | One deletion change for the 202 + 5, prepared in a hook-free container and merged by the human (agents cannot delete on the live harness, F1). It also removes CI's collection breaker (`tests/test_tool_policy_inference_note.py`, C4) |
| E2 runtime writes | One Write in a product repo creates `CLAUDE.md`, `src/INDEX.md` and `src/README.md` there (sandbox). One Write in the harness rewrites `CLAUDE.md:4` (date), `scripts/INDEX.md` and `scripts/README.md`. 8 slash-command prompts in a fresh product repo leave **75 untracked files** in it (`.claude/dev-registry/*` 57, `workflow-<sid>.json` 8, `dev-start-replays` 3, `workflow-locks` 3, `docs/dev/*` 4) plus 8 todo files in `~/.claude/todos` (= harness source). Nothing makes product repos ignore any of it, and A3's `files_created` = "all untracked files" then reads it as work | (a) doc-sync update-only: never create INDEX/README/CLAUDE.md, never patch dates, never write into the harness home from another project. (b) Re-scope the existing SessionStart hook `session-gitignore-propagate.sh` to write the harness runtime patterns into the session repo's `.git/info/exclude` (any repo; no tracked file touched; no new state file). (c) Two one-line producer fixes for home-side writes (seal default dest; `PYTHONDONTWRITEBYTECODE`). (d) Drop 11 dead or duplicate `.gitignore` rules and anchor 5 that swallow source |
| E3 prompt bloat | Prompt layer: 77 files, 1,629,603 B (~407k tokens; commands+agents+CLAUDE.md = 1,575,620 B, ~394k). `prompt-workflow.py:1278-1280` re-sends the whole command body on top of Claude Code's own expansion for 8 commands (sandbox stdout: /close 119,653 B, /dev 108,226 B, /dev-command 55,380 B, /spec 36,162 B, /clean 29,969 B, /test 18,487 B, /do 6,670 B, /redev 5,910 B). Stamps: 169 prompt lines in 31 files (91 task-id, 21 dated notes, 60 dated-doc filename refs, 2 commit SHAs); 608 code lines in 110 files. Six hand-copied blocks: 59 copies, 1,658 lines | (a) Delete the 3 re-injection lines. (b) Remove prompt stamps; stop new ones at the write (PreToolUse check in the existing guard that already sees commands/ and agents/ edits). (c) Move the six copied blocks into 6 include files read only when their condition holds, delete dev.md's 239 tutorial lines and its false "exit 2" claim |
| E4 dated docs + backlog | 37 dated docs in docs/reference (plus 14 undated incident/plan records): 1 binding, 3 still carry rationale a live hook defers to, 2 are evidence for open fixes (A2, A4), 8 are open defects, 2 private, 5 product/ops decisions, 30 pure history (509 KB). Backlog: 697,229 B / 262 lines (max line 22,351 chars) / 158 entries, a mandatory read for every fix-class BA (`agents/ba.md:18`) and a "record, don't fix" sink (line 27) | Delete the 30 history docs in the E1 change and trim the provenance comments that point at them; inline the 3 rationale docs (<=15 lines each) into the code that cites them; leave each open-defect doc to the cluster that fixes it. Replace the BA "read the whole backlog" instruction with a targeted grep; the backlog's fate and the record-only rule are a user decision (F4) |

---

## Verification log (executed this session; scratch only; `PYTHONDONTWRITEBYTECODE=1`; HOME redirected into the sandbox)

| # | What | Result |
|---|---|---|
| V1 | `git ls-files` count and HEAD | 893 files @ 09ab15b; the manifest was built on the same tree (no commits since 2026-10-08) |
| V2 | Reference check of every proposed pure-junk file (`pure_junk_refs.tsv`): `git grep -F` of its basename stem across all tracked files, excluding INDEX/README listings, the file itself and the other candidates | No live code/settings/prompt reference for any of them, except the companion edits listed in the E1 tables (settings allow rules, `scripts/todo/do.py:4` docstring, `tests/fresh-clone-bootstrap-smoke.sh:489`, `tests/test_late_repair_route.py:1191-1195`, `hooks/subagentstop-artifact-contract-enforce.py:426-494`, `hooks/tests/test_attribution_adjudicator.py:447,472,584`, `tests/score-lifecycle-contract/test-lifecycle-cas.sh:23`). Generic stems (`stage`, `install`, `refactor`, `optimize`, `__main__`) hit only the English word |
| V3 | `hooks/prompt-workflow.py` run in the sandbox for 10 slash commands in a fresh product repo (`sbx/proj`) | Stdout carries the full command body behind `--- /<cmd> COMMAND SPECIFICATION ---` for close, dev, clean, spec, test, do, redev, dev-command (bytes in E3.a). /commit and /push have no todo script, so no stdout. The product repo then holds 75 untracked files; `~/.claude/todos/` (sandbox harness copy) holds 8 files |
| V4 | `hooks/posttool-doc-sync.py` in the sandbox: (a) a Write of `scripts/zz_probe.py` inside the harness copy; (b) a Write of `src/foo.py` in a fresh product repo (`sbx/proj2`) | (a) rewrote `CLAUDE.md` (line 4 → `> Last updated: 2026-10-13`), `scripts/README.md`, `scripts/INDEX.md`. (b) created untracked `CLAUDE.md`, `src/INDEX.md`, `src/README.md` in the product repo |
| V5 | `git log` of CLAUDE.md | 33 of the last 40 commits that touch CLAUDE.md rewrite its `> Last updated` line (the doc-sync AUTO block at CLAUDE.md:3-5) |
| V6 | Duplicate-block measurement (heading-to-next-heading) over agents/ and commands/ | codex 12 blocks / 707 lines; checkpoint contract 17 / 413; charter 18 / 116; anti-give-up 6 / 174; overnight spec 4 / 144; specialist intake 2 / 104 (identical to wf2's figures) |
| V7 | Stamp scan (`stamps2.py`), regexes stated in E3.b | prompts 169 stamped lines in 31 files; code 608 lines in 110 files |
| V8 | Citations of every docs/reference file (`git grep -F <stem>`, excluding INDEX/README and the file itself) | See E4 table "live citations" column |

Corrections to prior evidence:
- The manifest marks 23 files DELETE on the ground that the repo is a personal tool (".github" community files, the README hero
  chain, examples/guard-demo, tools/demo samples, NOTICE, requirements/py310|311). Under the user's published-product decision they are
  product surface: KEEP (NOTICE needs a content fix, not deletion).
- The manifest marks `schemas/graphify-focused-subgraph.v1.json` and `schemas/test-plan.v1.json` DELETE because nothing validates
  them. Both describe live producer artifacts (`scripts/graphify-enrich.py:665`, PM `test-plan.json`). Under the producer-side
  architecture the fix is to validate at the producer, so they are FEATURE-TIED, not junk.
- problems.md X06 gives "/dev 108,227 B, /close 119,654 B" for the re-injection; the sandbox stdout is 108,226 B and 119,653 B
  (the command body plus the checklist preamble). Whether the CLI truncates hook stdout could not be observed here (running the
  `claude` CLI is forbidden). The repo itself documents a 10,000-character hook-output cap (`hooks/userprompt-doc-sync-check.py:25`).
  If that cap applies, the second copy arrives truncated mid-document. Either way it duplicates text the CLI already expanded.
- Stamp counts: the prior "130 task-id / 179 date stamps" used other regexes. Here: task-id = `(dev-|dev-command-|spec-|ticket-|task )?YYYYMMDD-HHMMSS[-suffix]`
  or `spec|ticket|task YYYYMMDD`; dated note = ISO date in prose, excluding JSON timestamp examples (`...T10:00:00Z`) and dates inside
  a path; dated-doc ref = a path whose name contains YYYYMMDD; SHA = a 7-12 hex token that resolves to a commit in this repo.

---

## E1 — the deletable set, split

### E1.0 Root cause

1. Nothing removes. The live harness blocks agent `rm` / `git rm` (`hooks/lib/bash_execution_boundary.py` FORBIDDEN_REMOVAL), agent
   commits other than `auto-bulk:` (`hooks/pretool-git-privilege-guard.py:179`) and agent edits of `.claude/commands|hooks|scripts`
   (`hooks/pretool-claude-config-guard.py:48-66`). End-of-cycle `auto-bulk:` commits sweep every untracked file in
   (`859ebda` "land misleading-named scratch/report-shard artifacts as real content", `b108c16` "land 22 net-new files from abandoned
   overnight worktree", `e227a70` "probe-byproduct updates" landed `stage`). That is F1; E1 is its residue.
2. Generated output is tracked: doc-sync writes INDEX/README into every directory it touches (E2.a), and test-writer's per-cycle
   output was tracked until `.gitignore:143-155` pinned two cycles.
3. Abandoned cycles land as code: LANE-B, negative-evidence, dev-fix, repair-map and spec-update-contract were landed with failing
   tests and no caller (`b108c16`, `16963b6`, `87ae3e4`, `c32d814`).

### E1.1 Classification rule used

| Class | Meaning | Action under the user's decisions |
|---|---|---|
| I (pure junk) | No runtime path reaches it, no command/agent/hook/settings/CI names it (V2), and no feature depends on it. Deleting it retires nothing | Delete now, with the companion edits listed |
| G (generated stub) | doc-sync / rule-inspector per-folder INDEX.md or README.md, no reader | Keep under the hold (the per-folder convention is a feature: `/clean` rule-inspector would recreate them). Stop new ones via E2.a. Decision U-E1b |
| F (feature-tied) | Registered hook, live command dependency, or the evidence base of an open fix | Keep; owned by the named cluster |
| P (product surface) | Serves the published product (community files, README hero chain, demos, supported-Python locks, NOTICE) | KEEP. The manifest's DELETE assumed a personal tool |
| D (decision) | Product or policy choice | Listed in E1.4 |

### E1.2 Totals (all 333 manifest DELETE rows)

| class | files | lines |
|---|---|---|
| I1 strays, scratch, runtime output | 16 | 3240 |
| I2 tests/generated fossils (2 July cycles) | 58 | 3315 |
| I3 never-run hooks, legacy installers and their docs | 21 | 2866 |
| I4 scripts/todo checklists of deleted commands | 13 | 197 |
| I5 dead scripts/libs/schemas (mostly abandoned-cycle landings) | 27 | 24604 |
| I6 dead or one-off tests and fixtures | 33 | 13558 |
| I7 dated/one-off history docs with no live reader (E4) | 30 | 7204 |
| I8 archived skill | 4 | 286 |
| D | 14 | 2603 |
| F | 44 | 6783 |
| G | 50 | 2057 |
| P | 23 | 2333 |

#### I1 strays, scratch, runtime output — 16 files / 3240 lines

| file | lines | why | companion edit / owner |
|---|---|---|---|
| .claude/INDEX.md | 19 | doc-sync stub of a runtime dir; 0 readers |  |
| .claude/README.md | 13 | doc-sync stub of a runtime dir; 0 readers |  |
| .claude/quarantined-phantom-dev-cycles/dev-20260915-020044/INDEX.md | 19 | quarantine of a phantom /dev run; history (git keeps it) | delete docs/reference/quarantine-record-dev-20260915-020044.md with it |
| .claude/quarantined-phantom-dev-cycles/dev-20260915-020044/QUARANTINE-NOTE.md | 26 | quarantine of a phantom /dev run; history (git keeps it) | delete docs/reference/quarantine-record-dev-20260915-020044.md with it |
| .claude/quarantined-phantom-dev-cycles/dev-20260915-020044/README.md | 17 | quarantine of a phantom /dev run; history (git keeps it) | delete docs/reference/quarantine-record-dev-20260915-020044.md with it |
| .claude/quarantined-phantom-dev-cycles/dev-20260915-020044/docs/dev/user-requirement-dev-20260915-020044.md | 0 | quarantine of a phantom /dev run; history (git keeps it) | delete docs/reference/quarantine-record-dev-20260915-020044.md with it |
| .claude/quarantined-phantom-dev-cycles/dev-20260915-020044/original-path-manifest.json | 141 | quarantine of a phantom /dev run; history (git keeps it) | delete docs/reference/quarantine-record-dev-20260915-020044.md with it |
| .claude/scratch_write_report.py | 226 | one-off dev-lane script (859ebda); 0 refs |  |
| .claude/tmp-test-writer-gen-l7.py | 576 | one-shot test-writer generator (docstring :2-4); 0 refs; same class as ignored tw-gen-*.py |  |
| .r05_part1.json | 168 | lane report shard landed by 859ebda; 0 refs |  |
| .r05_part2.json | 244 | lane report shard landed by 859ebda; 0 refs |  |
| .r05_part3.json | 355 | lane report shard landed by 859ebda; 0 refs |  |
| .scratch_subagentstop_ancestor.txt | 562 | 562-line stale copy of a hook saved as .txt (859ebda); only a dated doc mentions it |  |
| hooks/tests/fixtures/pol_installed_program_allow_set.json | 606 | host-enumerated PATH snapshot; no test reads it (test_pol_generative_sweeps.py:263-268 only writes it when POL_REFRESH_ALLOW_SET is set) | make the opt-in writer write to tmp_path only |
| stage | 1 | probe byproduct "ABSENT - 2" committed by e227a70; 0 refs |  |
| tests/reports/edge-case-analysis.json | 267 | 2026-01-07 runtime output at a path nothing reads (readers use docs/test/edge-case-analysis.json: scripts/analyze-git-edge-cases.sh:53); contains /root/.claude |  |

#### I2 tests/generated fossils (2 July cycles) — 58 files / 3315 lines

| file | lines | why | companion edit / owner |
|---|---|---|---|
| tests/generated/20260704-134650/INDEX.md | 14 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/README.md | 9 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/manifest.json | 419 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_A_a1b2c3d4e5f60001.py | 56 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_B1_a1b2c3d4e5f60002.py | 47 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_B2_a1b2c3d4e5f60003.py | 42 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_B3_a1b2c3d4e5f60004.py | 44 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_B4_a1b2c3d4e5f60005.py | 32 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_B5_a1b2c3d4e5f60006.py | 38 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_C1_a1b2c3d4e5f60007.py | 51 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_C1b_a1b2c3d4e5f60007b.py | 75 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_C2_a1b2c3d4e5f60008.py | 50 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_C3_a1b2c3d4e5f60009.py | 51 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_D_a1b2c3d4e5f60010.py | 54 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_E1_a1b2c3d4e5f60011.py | 23 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_E2_a1b2c3d4e5f60012.py | 23 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_E3_a1b2c3d4e5f60013.py | 23 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_E4_a1b2c3d4e5f60014.py | 23 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_E5_a1b2c3d4e5f6001e.py | 23 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_E6a_a1b2c3d4e5f6e6a0.py | 23 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_E6b_a1b2c3d4e5f6e6b0.py | 23 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_E6c_a1b2c3d4e5f6e6c0.py | 23 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_F1_a1b2c3d4e5f60015.py | 23 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_F2_a1b2c3d4e5f60016.py | 23 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_F3_a1b2c3d4e5f60017.py | 23 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_F4_a1b2c3d4e5f6001f.py | 23 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_F5_a1b2c3d4e5f60020b.py | 23 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_F6_a1b2c3d4e5f60020c.py | 23 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_G1_a1b2c3d4e5f60018.py | 41 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_G2_a1b2c3d4e5f60019.py | 34 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_G3_a1b2c3d4e5f60020.py | 44 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-134650/test_AC_G4_a1b2c3d4e5f60021.py | 45 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/INDEX.md | 14 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/README.md | 9 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/manifest.json | 366 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_E1_a1b2c3d4e5f60011.py | 78 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_E2_a1b2c3d4e5f60012.py | 27 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_E3_a1b2c3d4e5f60013.py | 38 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_E4_a1b2c3d4e5f60014.py | 32 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_E5_a1b2c3d4e5f6001e.py | 85 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_E6a_a1b2c3d4e5f6e6a0.py | 37 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_E6b_a1b2c3d4e5f6e6b0.py | 55 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_E6c_a1b2c3d4e5f6e6c0.py | 58 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_E7_e7a1b2c3d4e5f601.py | 66 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_F10_f10a1b2c3d4e5f60.py | 49 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_F11_f11a1b2c3d4e5f60.py | 43 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_F1_a1b2c3d4e5f60015.py | 52 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_F2_a1b2c3d4e5f60016.py | 52 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_F3_a1b2c3d4e5f60017.py | 39 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_F4_a1b2c3d4e5f6001f.py | 81 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_F5_a1b2c3d4e5f60020b.py | 53 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_F6_a1b2c3d4e5f60020c.py | 44 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_F7_f7a1b2c3d4e5f601.py | 50 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_F7b_f7ba1b2c3d4e5f60.py | 66 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_F8_f8a1b2c3d4e5f601.py | 54 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/20260704-225139/test_AC_F9_f9a1b2c3d4e5f601.py | 60 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/INDEX.md | 324 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |
| tests/generated/README.md | 15 | fossil per-cycle test-writer output of July cycles; CI --ignore=tests/generated; only .gitignore:152-155 negations keep it | delete .gitignore:143-155 negation block in the same change |

#### I3 never-run hooks, legacy installers and their docs — 21 files / 2866 lines

| file | lines | why | companion edit / owner |
|---|---|---|---|
| hooks/.env.example | 71 | env template of the retired auto-commit/auto-create-repo installer; nothing sources it |  |
| hooks/QUICKSTART.md | 215 | its own banner (:3-8) says obsolete; documents dead installers |  |
| hooks/README-TODO-INJECTION.md | 262 | documents unregistered hook-todo-injection.py |  |
| hooks/audit-slashcommand.sh | 45 | 2025-12 template hook, never registered |  |
| hooks/git-hooks/INDEX.md | 15 | generated stub of a dir of dead hooks |  |
| hooks/git-hooks/README.md | 14 | generated stub of a dir of dead hooks |  |
| hooks/git-hooks/post-commit-auto-push | 31 | installers exit before the cp; in-repo copy is dead | HUMAN: remove installed copies from .git/hooks/post-commit (252 refs/backups/* on origin; see D1.d) |
| hooks/hook-todo-injection.py | 236 | unregistered since dec89cc; superseded by prompt-workflow.py:330-351 | fix stale docstring scripts/todo/do.py:4 |
| hooks/install-auto-sync.sh | 274 | LEGACY, unconditional exit 0 at :12 |  |
| hooks/install-git-hooks.sh | 98 | LEGACY, exit 0 at :12 | tests/integration-test.sh goes too |
| hooks/install-protection-all.sh | 140 | LEGACY, exit 0 at :11 |  |
| hooks/install.sh | 191 | LEGACY, exit 0 at :15 | drop the scripts/canary-verify.sh comment mention |
| hooks/post-commit-warn.sh | 29 | unregistered byte-identical copy of posttool-git-warn.sh |  |
| hooks/post_tool_use.sh | 59 | 2025-12 template hook, never registered |  |
| hooks/pre_slashcommand_validate.sh | 44 | self-described no-op stub, never registered |  |
| hooks/pre_tool_use_safety.sh | 54 | reads $1 not stdin; never registered |  |
| hooks/pretool-baseline-snapshot-preflight.py | 102 | header :9,:49 "NOT registered" |  |
| hooks/pretool-overwrite-guard.py | 582 | never registered since eed4787; overlaps registered write guards | delete hooks/tests/test_overwrite_guard.py, hooks/tests/fixtures/overwrite_corpus.json, docs/reference/overwrite-prohibition.md; edit the mixed tests/test_bash_write_targets_verb_narrowing.py |
| hooks/project-settings-template.json | 59 | no caller; duplicates settings.template.json |  |
| hooks/session_start.sh | 47 | legacy duplicate of session-info.sh; never registered |  |
| hooks/sessionstart-artifact-census.py | 298 | never registered (f8d7b60) | delete hooks/tests/test_sessionstart_artifact_census.py |

#### I4 scripts/todo checklists of deleted commands — 13 files / 197 lines

| file | lines | why | companion edit / owner |
|---|---|---|---|
| scripts/todo/code-review.py | 11 | checklist for a command already deleted (24d82aa/83460ea); prompt-workflow.py:330-351 still runs it for any typed /<name>; ACTIVELY HARMFUL for the built-in /code-review | drop the matching settings allow rules (file-analyze/quick-prototype/reflect-search: settings.json:135-137, template:122-124) |
| scripts/todo/deep-search.py | 11 | checklist for a command already deleted (24d82aa/83460ea); prompt-workflow.py:330-351 still runs it for any typed /<name> | drop the matching settings allow rules (file-analyze/quick-prototype/reflect-search: settings.json:135-137, template:122-124) |
| scripts/todo/doc-gen.py | 10 | checklist for a command already deleted (24d82aa/83460ea); prompt-workflow.py:330-351 still runs it for any typed /<name> | drop the matching settings allow rules (file-analyze/quick-prototype/reflect-search: settings.json:135-137, template:122-124) |
| scripts/todo/explain-code.py | 11 | checklist for a command already deleted (24d82aa/83460ea); prompt-workflow.py:330-351 still runs it for any typed /<name> | drop the matching settings allow rules (file-analyze/quick-prototype/reflect-search: settings.json:135-137, template:122-124) |
| scripts/todo/file-analyze.py | 31 | checklist for a command already deleted (24d82aa/83460ea); prompt-workflow.py:330-351 still runs it for any typed /<name> | drop the matching settings allow rules (file-analyze/quick-prototype/reflect-search: settings.json:135-137, template:122-124) |
| scripts/todo/optimize.py | 11 | checklist for a command already deleted (24d82aa/83460ea); prompt-workflow.py:330-351 still runs it for any typed /<name> | drop the matching settings allow rules (file-analyze/quick-prototype/reflect-search: settings.json:135-137, template:122-124) |
| scripts/todo/playwright-helper.py | 9 | checklist for a command already deleted (24d82aa/83460ea); prompt-workflow.py:330-351 still runs it for any typed /<name> | drop the matching settings allow rules (file-analyze/quick-prototype/reflect-search: settings.json:135-137, template:122-124) |
| scripts/todo/quick-prototype.py | 30 | checklist for a command already deleted (24d82aa/83460ea); prompt-workflow.py:330-351 still runs it for any typed /<name> | drop the matching settings allow rules (file-analyze/quick-prototype/reflect-search: settings.json:135-137, template:122-124) |
| scripts/todo/refactor.py | 10 | checklist for a command already deleted (24d82aa/83460ea); prompt-workflow.py:330-351 still runs it for any typed /<name> | drop the matching settings allow rules (file-analyze/quick-prototype/reflect-search: settings.json:135-137, template:122-124) |
| scripts/todo/reflect-search.py | 30 | checklist for a command already deleted (24d82aa/83460ea); prompt-workflow.py:330-351 still runs it for any typed /<name> | drop the matching settings allow rules (file-analyze/quick-prototype/reflect-search: settings.json:135-137, template:122-124) |
| scripts/todo/research-deep.py | 11 | checklist for a command already deleted (24d82aa/83460ea); prompt-workflow.py:330-351 still runs it for any typed /<name> | drop the matching settings allow rules (file-analyze/quick-prototype/reflect-search: settings.json:135-137, template:122-124) |
| scripts/todo/security-check.py | 11 | checklist for a command already deleted (24d82aa/83460ea); prompt-workflow.py:330-351 still runs it for any typed /<name> | drop the matching settings allow rules (file-analyze/quick-prototype/reflect-search: settings.json:135-137, template:122-124) |
| scripts/todo/site-navigate.py | 11 | checklist for a command already deleted (24d82aa/83460ea); prompt-workflow.py:330-351 still runs it for any typed /<name> | drop the matching settings allow rules (file-analyze/quick-prototype/reflect-search: settings.json:135-137, template:122-124) |

#### I5 dead scripts/libs/schemas (mostly abandoned-cycle landings) — 27 files / 24604 lines

| file | lines | why | companion edit / owner |
|---|---|---|---|
| docs/reference/mat-doc10-writer-order.v2.json | 242 | abandoned-cycle contract; only its own test reads it |  |
| hooks/lib/agent_temp_targets.py | 203 | no importer (b108c16) |  |
| hooks/lib/checkpoint_resources.py | 325 | no importer (b108c16); 5/19 own tests fail |  |
| hooks/lib/negative_evidence.py | 1639 | only importer is the dead CLI; schema missing from registry |  |
| hooks/lib/runtime_guard/__main__.py | 3 | no python -m caller |  |
| schemas/negative-evidence.v1.json | 194 | abandoned-cycle schema, not in registry.json |  |
| schemas/owned-edits-ledger.v1.json | 251 | validator deleted in db52813; superseded by the attribution journal | reword schemas/dev-report.v2.json:46 description |
| schemas/repair-map.v1.json | 5222 | 5,222-line generated table; generator and consumer both dead | drop schemas/registry.json:16 row |
| scripts/adjudicate-attribution-staging.py | 10 | 10-line CLI wrapper; live path imports the lib | point hooks/tests/test_attribution_adjudicator.py:447,472 at the lib main() |
| scripts/analyze-folder-history.sh | 38 | placeholder printing fixed JSON | drop settings.json:114 / template:141 allow rules |
| scripts/attribution-aggregate-view.py | 10 | 10-line CLI wrapper; tests only | edit hooks/tests/test_attribution_adjudicator.py:584 |
| scripts/capture-dispatch-metadata.py | 13 | CLI for the never-wired lib; 0 refs |  |
| scripts/check-security-hook-drift.sh | 178 | manual audit, "no CI integration" (:14-15); no caller |  |
| scripts/check-todo-accounting.py | 390 | abandoned-cycle proof with frozen digests (:16-30) |  |
| scripts/cleanup-close-force-sentinel.sh | 13 | rm wrapper; no caller |  |
| scripts/close-commit-repair-orchestrate.py | 366 | no caller; only consumer of repair-map |  |
| scripts/dev-fix.py | 3249 | abandoned worktree (b108c16); no /dev --fix exists |  |
| scripts/gen-test-baseline.py | 106 | CI never runs check; baseline stale | drop conftest.py:11-12 comment |
| scripts/generate-repair-map.py | 395 | consumer dead | docs/reference/close-commit-failure-inventory-20260927.md loses its only code reader |
| scripts/laneb-integration-gate.py | 9076 | 9,076 lines for one abandoned cycle; hard-codes SESSION_ID (:41) and gitignored docs/dev paths |  |
| scripts/lib/attribution_aggregate_view.py | 242 | writes docs/dev/journal-view-<task>.json that nothing reads (E2 product-repo writer) | remove the sidecar call hooks/subagentstop-artifact-contract-enforce.py:426-440 in the same change |
| scripts/lib/dispatch_metadata.py | 173 | never wired (attribution_adjudicator.py:11) |  |
| scripts/lifecycle-baseline-import.sh | 146 | finished one-time migration | drop settings.json:41 / template:175,180 allow rules; edit tests/score-lifecycle-contract/test-lifecycle-cas.sh, tests/TESTING.md:126 |
| scripts/negative-evidence.py | 149 | abandoned-cycle CLI; no caller |  |
| scripts/session-resources.py | 103 | only provisioner for the never-configured LANE-B broker; only laneb-integration-gate calls it | drop settings.json:191-192 allow rules; Lane-B branches in hooks become dead (X63) |
| scripts/spec-update-contract.py | 1288 | abandoned cycle; commands/spec-update.md never calls it | tests/test_spec_update_command_contracts.py:61 copy line |
| scripts/verify-claims-extended.sh | 580 | never wired (not CI, not a command) |  |

#### I6 dead or one-off tests and fixtures — 33 files / 13558 lines

| file | lines | why | companion edit / owner |
|---|---|---|---|
| hooks/tests/test_ac10_verify.sh | 47 | one-off acceptance check of a closed 2026-05 task; fails in a clean clone | tests/TESTING.md mention |
| hooks/tests/test_ac1_verify.sh | 22 | one-off acceptance check of a closed 2026-05 task; fails in a clean clone | tests/TESTING.md mention |
| hooks/tests/test_ac3_verify.sh | 39 | one-off acceptance check of a closed 2026-05 task; fails in a clean clone | tests/TESTING.md mention |
| hooks/tests/test_ac5_verify.sh | 69 | one-off acceptance check of a closed 2026-05 task; fails in a clean clone | tests/TESTING.md mention |
| hooks/tests/test_ac6_verify.sh | 30 | one-off acceptance check of a closed 2026-05 task; fails in a clean clone | tests/TESTING.md mention |
| hooks/tests/test_ac9_verify.sh | 28 | one-off acceptance check of a closed 2026-05 task; fails in a clean clone | tests/TESTING.md mention |
| hooks/tests/test_baseline_snapshot_preflight.py | 110 | tests the unregistered preflight |  |
| hooks/tests/test_final_sweep.sh | 172 | re-runs the one-off AC checks; can never fail | tests/TESTING.md mention |
| hooks/tests/test_laneb_agent_temp_targets.py | 96 | tests dead lib |  |
| hooks/tests/test_laneb_checkpoint_resources.py | 292 | tests dead lib |  |
| hooks/tests/test_laneb_integration_gate.py | 4290 | module-level skip; 0 tests ever run on a clean checkout |  |
| hooks/tests/test_laneb_pretool_composition.py | 129 | tests a stand-in defined in the test; tautology at :62-65 |  |
| hooks/tests/test_regen_index_dirs_script.py | 238 | tests a one-shot migration script with no caller | delete scripts/regen-index-dirs.py too (missed DELETE, see E1.v) |
| tests/baselines/default-run-failures.json | 79 | stale known-failure ledger; nothing consumes it |  |
| tests/fixtures/dev-todo-canonical-before.v1.json | 1 | read only by dead check-todo-accounting.py |  |
| tests/fixtures/late_repair_golden/spec-20260907-115508-lawful-commit-channel.pre-r4.md | 300 | compared against ~/docs/dev (author machine) by AC12 | delete the AC12 function tests/test_late_repair_route.py:1191-1195 |
| tests/integration-test.sh | 436 | drives dead install-git-hooks.sh; never run | tests/TESTING.md mention |
| tests/scripts/validate-posttool-ac-dev-20260524-205811.py | 313 | one-cycle QA script; picked up only by the /test glob |  |
| tests/test-lock-detection.sh | 101 | tautological; exercises no harness code | tests/TESTING.md mention |
| tests/test_changelog_analyst_declaration_categories.py | 182 | pins prompt wording of a mechanism its own last test calls retired | 2 sibling tests cite it in docstrings only |
| tests/test_changelog_analyst_files_landed_whole_toctou.py | 194 | tests a Python mirror of prompt lines that no longer exist |  |
| tests/test_dev_fix.py | 1725 | tests dead scripts/dev-fix.py; 46 failing |  |
| tests/test_dev_todo_accounting.py | 175 | 19/19 setup errors; tests dead script |  |
| tests/test_generate_repair_map.py | 194 | tests dead generator |  |
| tests/test_mat_doc10_writer_order_contract.py | 222 | tests dead contract; needs gitignored docs/dev |  |
| tests/test_negative_evidence.py | 984 | tests dead lib; 59 failing |  |
| tests/test_no_artificial_lifecycle_ceremony.py | 67 | tombstone test + host-home scans (~/.codex, ~/.agents) |  |
| tests/test_repair_map_call_site_coverage.py | 303 | own docstring: AC5 is a vacuous pass |  |
| tests/test_repair_orchestrate.py | 235 | tests dead engine |  |
| tests/test_spec_update_command_contracts.py | 1207 | tests dead spec-update-contract.py (85 pass / 2 fail) |  |
| tests/test_tool_policy_inference_note.py | 813 | module-level pytest.fail (:39-40) aborts CI collection (C4) | optionally add 2-3 direct assertions for pretool-tool-policy in hooks/tests |
| tests/test_write_qa_mode.py | 76 | abandoned-worktree variant; 0/4 pass; live script covered by tests/test_subagentstop_e2e_enforce.py:105-134 |  |
| tests/ws2_zero_literal_gate.py | 389 | one-off cycle gate pinned to gitignored dev-reports; covered by check-public-core.sh | remove the call tests/fresh-clone-bootstrap-smoke.sh:489 |

#### I7 dated/one-off history docs with no live reader (E4) — 30 files / 7204 lines

| file | lines | why | companion edit / owner |
|---|---|---|---|
| docs/reference/MORNING-20260907.md | 534 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/abandoned-cycles-20260905.md | 422 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/attribution-journal-consumer-cutover-20261004.md | 73 | history; cited only as provenance: scripts/lib/attribution_adjudicator.py:5 (provenance comment) | trim the citing comments to one line or keep the rationale inline (E4.b) |
| docs/reference/attribution-journal-cutover-flip-plan-20261003.md | 128 | history; cited only as provenance: scripts/lib/dispatch_metadata.py:16, attribution_adjudicator.py:4, resolve-commit-repos.py:532 (comments) | trim the citing comments to one line or keep the rationale inline (E4.b) |
| docs/reference/bash-safety-verb-anchoring-20261008.md | 249 | history; cited only as provenance: hooks/pretool-bash-safety.sh:58,1171,1251 cite it; manifest: rationale restated inline | trim the citing comments to one line or keep the rationale inline (E4.b) |
| docs/reference/claim-verification-methodology-20260925.md | 90 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/codex-sandbox-verification.md | 205 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/commit-dryrun-close-gate-ruling.md | 25 | history; cited only as provenance: commands/commit.md:235 (normative rule lives there; doc is history per its own :3) | trim the citing comments to one line or keep the rationale inline (E4.b) |
| docs/reference/controller-error-taxonomy-20260924.md | 178 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/dev-command-20261003-020648-takeover-record.md | 174 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/harness-defects-20260906-controller.md | 671 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/harness-fix-status-20260905.md | 724 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/infeasibility-without-execution-20261006.md | 23 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/lane-pol-catchup-plan-20260808-035658-lanepolcatchup.md | 264 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/master-origin-reconciliation-gap-20261005.md | 61 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/monolith-split-plan.md | 267 | history; cited only as provenance: 20 provenance comment lines in hooks/lib/runtime_guard/ (_core.py:36..292 x8, 12 lines in 7 modules) | trim the citing comments to one line or keep the rationale inline (E4.b) |
| docs/reference/overnight-cycle-20260809-013317-shared-file-attribution-20260914.md | 536 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/overnight-worktree-20260810-test-gaps-20261005.md | 88 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/overnight-worktree-test-gaps-20261005.md | 40 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/overwrite-prohibition.md | 359 | history; cited only as provenance: docstring of unregistered hooks/pretool-overwrite-guard.py:23 | trim the citing comments to one line or keep the rationale inline (E4.b) |
| docs/reference/paseo-daemon-caller-id-rollout-20261004.md | 51 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/paseo-daemon-concurrent-staging-triple-repro-20260904-181435-20260914.md | 247 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/paseo-daemon-shared-file-attribution-20260913.md | 484 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/quarantine-record-dev-20260915-020044.md | 127 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/recoverable-discard-register-20261005.md | 119 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/restart-detector-quota-text-match-false-positive-20260915.md | 486 | history; cited only as provenance: commands/restart.md:81, hooks/lib/interruption_signals.py:65, hooks/lib/subagent_restart.py:111, tests/test_restart_command.py:979 | trim the citing comments to one line or keep the rationale inline (E4.b) |
| docs/reference/slashcommand-quick-reference.md | 232 | 23 of 31 commands it names do not exist; commands/INDEX.md lists the real ones |  |
| docs/reference/test-suite-overhaul-plan.md | 229 | history; cited only as provenance: conftest.py:3, pytest.ini:8, tests/TESTING.md:5 | trim the citing comments to one line or keep the rationale inline (E4.b) |
| docs/reference/workspace-disposition-criteria-20261005.md | 52 | dated/one-off history record; no live reader (git preserves it) |  |
| docs/reference/worktree-685c203b-remaining-18-disposition-20261005.md | 66 | dated/one-off history record; no live reader (git preserves it) |  |

#### I8 archived skill — 4 files / 286 lines

| file | lines | why | companion edit / owner |
|---|---|---|---|
| skills/.archive/frontend-design/INDEX.md | 21 | generated stub of the archived skill |  |
| skills/.archive/frontend-design/LICENSE.txt | 177 | licence of the archived skill | rewrite NOTICE (same change) |
| skills/.archive/frontend-design/README.md | 46 | generated stub of the archived skill |  |
| skills/.archive/frontend-design/SKILL.md | 42 | archived skill, not loadable (nested under .archive/) | rewrite NOTICE (same change) |

#### D  needs a user decision — 14 files / 2603 lines

| file | lines | why | companion edit / owner |
|---|---|---|---|
| docs/reference/bash-write-targets-capability-gap-20261005.md | 35 | open-defect record ("if still open, one issue line, then delete"); destination depends on the issue-list decision (E4/F4) |  |
| docs/reference/commit-gate-bypass-via-background-exec-20261005.md | 73 | open-defect record ("if still open, one issue line, then delete"); destination depends on the issue-list decision (E4/F4) |  |
| docs/reference/do-report-ledger-has-no-refresh-path-20261008.md | 112 | open-defect record ("if still open, one issue line, then delete"); destination depends on the issue-list decision (E4/F4) |  |
| docs/reference/harness-gaps-found-20261005.md | 141 | open-defect record ("if still open, one issue line, then delete"); destination depends on the issue-list decision (E4/F4) |  |
| docs/reference/launch-plan.md | 720 | marketing plan; never executed; under the published-product decision the user decides keep vs delete |  |
| docs/reference/merge-pipeline-blocked-steps-20261007.md | 185 | open-defect record ("if still open, one issue line, then delete"); destination depends on the issue-list decision (E4/F4) |  |
| docs/reference/open-findings-from-read-only-cycles-20261005.md | 65 | open-defect record ("if still open, one issue line, then delete"); destination depends on the issue-list decision (E4/F4) |  |
| docs/reference/positioning.md | 281 | market positioning; no reader; product decision |  |
| docs/reference/qa-status-gate-gap-orchestrator-side-20261005.md | 117 | open-defect record ("if still open, one issue line, then delete"); destination depends on the issue-list decision (E4/F4) |  |
| docs/reference/rename-execution-plan.md | 296 | never-executed rename to claude-code-guardrails while README.md:1/NOTICE/THREAT-MODEL already use it | decide ONE product name |
| docs/reference/roadmap-decomposition-productization.md | 304 | "Status: plan (not executed)" (:4); cited by PUBLIC-CORE.md:10 and scripts/check-public-core.sh:6 | product decision |
| docs/reference/workflow-bookmark-orphans-20261005.md | 31 | open-defect record ("if still open, one issue line, then delete"); destination depends on the issue-list decision (E4/F4) |  |
| schemas/graphify-prequery.v1.json | 97 | shape of graphify pre_query.json (scripts/graphify-query.py:260 writes it unvalidated); either validate at the producer or delete |  |
| tests/test_dev_artifact_chain_consumer_contracts.py | 146 | passes 6/6 but only pins prose in 6 prompts; deleting is the "may prose-pinning tests go?" decision (X52) |  |

#### F  feature-tied (blocked by the no-retirement hold) — 44 files / 6783 lines

| file | lines | why | companion edit / owner |
|---|---|---|---|
| .claude/.awesome-claude-harness | 1 | marker that gates hooks/session-gitignore-propagate.sh:22 (KEEP hook); goes only with the E2.d re-scope of that hook | delete in the same change as E2.d |
| agents/git-edge-case-analyst.md | 275 | agent file anyone can dispatch; 0 dispatch sites (D1.f, decision U5) | wire into /test or drop spec.md views |
| docs/reference/close-commit-failure-inventory-20260927.md | 654 | evidence base of the binding design (close-commit-zero-failure-mechanism-20260928.md:6); keep until the A2 cutover (S10-S12) lands | delete with scripts/generate-repair-map.py after A2 |
| docs/reference/subagentstop-payload-s0-measurement-20260929.md | 92 | measured SubagentStop payload fields = input to the A4 identity fix | delete after A4 lands |
| hooks/doc_sync/__init__.py | 6 | module of the registered doc-sync generator (settings.json:717) | make update-only (E2.a); hook_ledger/ledger_contract exist only to account for doc-sync side effects (A3 coupling) |
| hooks/doc_sync/claude.py | 30 | module of the registered doc-sync generator (settings.json:717) | make update-only (E2.a); hook_ledger/ledger_contract exist only to account for doc-sync side effects (A3 coupling) |
| hooks/doc_sync/config.py | 140 | module of the registered doc-sync generator (settings.json:717) | make update-only (E2.a); hook_ledger/ledger_contract exist only to account for doc-sync side effects (A3 coupling) |
| hooks/doc_sync/docker.py | 59 | module of the registered doc-sync generator (settings.json:717) | make update-only (E2.a); hook_ledger/ledger_contract exist only to account for doc-sync side effects (A3 coupling) |
| hooks/doc_sync/extract.py | 229 | module of the registered doc-sync generator (settings.json:717) | make update-only (E2.a); hook_ledger/ledger_contract exist only to account for doc-sync side effects (A3 coupling) |
| hooks/doc_sync/hook_ledger.py | 308 | module of the registered doc-sync generator (settings.json:717) | make update-only (E2.a); hook_ledger/ledger_contract exist only to account for doc-sync side effects (A3 coupling) |
| hooks/doc_sync/ledger_contract.py | 332 | module of the registered doc-sync generator (settings.json:717) | make update-only (E2.a); hook_ledger/ledger_contract exist only to account for doc-sync side effects (A3 coupling) |
| hooks/doc_sync/main.py | 196 | module of the registered doc-sync generator (settings.json:717) | make update-only (E2.a); hook_ledger/ledger_contract exist only to account for doc-sync side effects (A3 coupling) |
| hooks/doc_sync/notice.py | 513 | module of the registered doc-sync generator (settings.json:717) | make update-only (E2.a); hook_ledger/ledger_contract exist only to account for doc-sync side effects (A3 coupling) |
| hooks/doc_sync/patch.py | 169 | module of the registered doc-sync generator (settings.json:717) | make update-only (E2.a); hook_ledger/ledger_contract exist only to account for doc-sync side effects (A3 coupling) |
| hooks/doc_sync/regen_index.py | 236 | module of the registered doc-sync generator (settings.json:717) | make update-only (E2.a); hook_ledger/ledger_contract exist only to account for doc-sync side effects (A3 coupling) |
| hooks/doc_sync/regen_readme.py | 216 | module of the registered doc-sync generator (settings.json:717) | make update-only (E2.a); hook_ledger/ledger_contract exist only to account for doc-sync side effects (A3 coupling) |
| hooks/doc_sync/regions.py | 266 | module of the registered doc-sync generator (settings.json:717) | make update-only (E2.a); hook_ledger/ledger_contract exist only to account for doc-sync side effects (A3 coupling) |
| hooks/doc_sync/systemd.py | 47 | module of the registered doc-sync generator (settings.json:717) | make update-only (E2.a); hook_ledger/ledger_contract exist only to account for doc-sync side effects (A3 coupling) |
| hooks/doc_sync/tree.py | 98 | module of the registered doc-sync generator (settings.json:717) | make update-only (E2.a); hook_ledger/ledger_contract exist only to account for doc-sync side effects (A3 coupling) |
| hooks/posttool-doc-sync.py | 13 | registered hook: settings.json:717 / template:675 (doc-sync generator; E2 writer) | E2.a (make doc-sync update-only) |
| hooks/posttool-git-warn.sh | 29 | registered hook: settings.json:743 / template:688 (matcher never matches tool_name Bash) | owned by hook-architecture / A1 / D4 (no-effect or advisory registered hook) |
| hooks/posttool-lane-completeness-watch.py | 325 | registered hook: settings.json:725 (live only); advisory sink logs/lane-completeness-watch-advisory.jsonl | owned by hook-architecture / A1 / D4 (no-effect or advisory registered hook) |
| hooks/pretool-bisect-gate.sh | 51 | registered hook: settings.json:591 / template:566 (exit-0 stderr, never reaches model) | owned by hook-architecture / A1 / D4 (no-effect or advisory registered hook) |
| hooks/pretool-bulk-commit-detector.py | 188 | registered hook: settings.json:643 / template:610 (exit-0 stderr) | owned by hook-architecture / A1 / D4 (no-effect or advisory registered hook) |
| hooks/pretool-layer-escalation-check.sh | 45 | registered hook: settings.json:587 / template:562 (exit-0 stderr) | owned by hook-architecture / A1 / D4 (no-effect or advisory registered hook) |
| hooks/pretool-layer-match-gate.sh | 40 | registered hook: settings.json:869 / template:791 (exit-0 stderr) | owned by hook-architecture / A1 / D4 (no-effect or advisory registered hook) |
| hooks/pretool-orchestrator-prompt-purity.py | 367 | registered hook: settings.json:599 / template:574 (warn-only; CLAUDE.md calls it Enforcement) | owned by hook-architecture / A1 / D4 (no-effect or advisory registered hook) |
| hooks/pretool-quality-gate.py | 385 | registered hook: settings.json:496 / template:471; agents/dev.md:843 | owned by hook-architecture / A1 / D4 (no-effect or advisory registered hook) |
| hooks/pretool-subagent-code-block.py | 94 | registered hook: settings.json:533 / template:508 (exit-0 stderr) | owned by hook-architecture / A1 / D4 (no-effect or advisory registered hook) |
| hooks/pretool-worktree-guard.sh | 82 | registered hook: settings.json:568 / template:543 (all tools; self-locking, B-cluster/hook-arch) | owned by hook-architecture / A1 / D4 (no-effect or advisory registered hook) |
| hooks/session-git-init.sh | 155 | registered hook: settings.json:317 / template:314 (env-gated off: CLAUDE_SESSION_GIT_INIT unset) | owned by hook-architecture / A1 / D4 (no-effect or advisory registered hook) |
| hooks/session-info.sh | 32 | registered hook: settings.json:313 / template:310 (exit-0 stderr) | owned by hook-architecture / A1 / D4 (no-effect or advisory registered hook) |
| hooks/session-tmpfs-banner.sh | 39 | registered hook: settings.json:340 / template:332 (exit-0 stderr) | owned by hook-architecture / A1 / D4 (no-effect or advisory registered hook) |
| hooks/subagent-stop-diff-check.sh | 63 | registered hook: settings.json:865 / template:787 (exit-0 stderr) | owned by hook-architecture / A1 / D4 (no-effect or advisory registered hook) |
| hooks/subagent-stop-guard-integrity.sh | 64 | registered hook: settings.json:873 / template:795 (exit-0 stderr) | owned by hook-architecture / A1 / D4 (no-effect or advisory registered hook) |
| hooks/subagentstop-cp-enforce.py | 111 | registered hook: settings.json:913 / template:826 (advisory; sink logs/cp-enforce-advisory.jsonl) | owned by hook-architecture / A1 / D4 (no-effect or advisory registered hook) |
| hooks/userprompt-doc-sync-check.py | 226 | registered hook: settings.json:360 / template:352 (doc-sync companion; E2 writer) | E2.a (make doc-sync update-only) |
| schemas/graphify-focused-subgraph.v1.json | 58 | shape of a LIVE producer artifact (scripts/graphify-enrich.py:665 writes focused-subgraph.json unvalidated); under the producer-side architecture the fix is to validate at the producer, not delete | wire into graphify-enrich.py write (A-cluster producer validation) |
| schemas/test-plan.v1.json | 69 | shape of PM test-plan.json, a live producer artifact written unvalidated; validate at the producer, do not delete | A-cluster producer validation |
| scripts/commit.sh | 49 | called by commands/dev-overnight.md Step 19 (:1578) and agents/ba.md:1329; never commits (B2.a) | owned by B2 |
| scripts/mint-git-blessed-token.sh | 50 | sole producer of the overnight keystone exemption token (hooks/git-keystone/reference-transaction:44-63); no caller (D2.f) | owned by B2/D2.f |
| scripts/update-overnight-state.sh | 276 | overnight state mutator named by dev-overnight.md:275 and whitelisted at pretool-overnight-hook-guard.py:727,841 (B2) | owned by B2 |
| skills/ui-axe-injector/vendor/axe.min.js | 11 | Tier-1 of the live ui-axe-injector skill (SKILL.md:77); 554 KB | decide with the skill; add MPL-2.0 attribution to NOTICE |
| tests/score-inject-contract/runtime-verify.sh | 94 | manual verifier of the live score-injection contract (not junk; no automation) |  |

#### G  generated INDEX/README stubs tied to the per-folder convention (doc-sync + /clean rule-inspector) — 50 files / 2057 lines

| file | lines | why | companion edit / owner |
|---|---|---|---|
| INDEX.md | 746 | 746-line generated tree of the whole repo; no reader |  |
| docs/reference/INDEX.md | 74 | generated tree of docs/reference; rewritten on every write |  |
| docs/reference/README.md | 45 | stale rule-inspector boilerplate (.md files: 6 found vs 60) |  |
| examples/guard-demo/INDEX.md | 16 | generated stub |  |
| hooks/INDEX.md | 282 | doc-sync / per-folder-convention generated stub; no reader |  |
| hooks/doc_sync/INDEX.md | 28 | doc-sync / per-folder-convention generated stub; no reader |  |
| hooks/doc_sync/README.md | 21 | doc-sync / per-folder-convention generated stub; no reader |  |
| hooks/tests/INDEX.md | 99 | doc-sync / per-folder-convention generated stub; no reader |  |
| hooks/tests/README.md | 98 | doc-sync / per-folder-convention generated stub; no reader |  |
| hooks/tests/fixtures/INDEX.md | 16 | doc-sync / per-folder-convention generated stub; no reader |  |
| hooks/tests/fixtures/README.md | 9 | doc-sync / per-folder-convention generated stub; no reader |  |
| policies/INDEX.md | 15 | doc-sync / per-folder-convention generated stub; no reader |  |
| policies/README.md | 12 | doc-sync / per-folder-convention generated stub; no reader |  |
| schemas/INDEX.md | 25 | doc-sync / per-folder-convention generated stub; no reader |  |
| schemas/README.md | 12 | doc-sync / per-folder-convention generated stub; no reader |  |
| scripts/install/INDEX.md | 27 | doc-sync / per-folder-convention generated stub; no reader |  |
| scripts/install/README.md | 12 | doc-sync / per-folder-convention generated stub; no reader |  |
| scripts/install/profiles/INDEX.md | 15 | doc-sync / per-folder-convention generated stub; no reader |  |
| scripts/install/profiles/README.md | 9 | doc-sync / per-folder-convention generated stub; no reader |  |
| scripts/install/tests/INDEX.md | 15 | doc-sync / per-folder-convention generated stub; no reader |  |
| scripts/install/tests/README.md | 9 | doc-sync / per-folder-convention generated stub; no reader |  |
| scripts/lib/INDEX.md | 21 | doc-sync / per-folder-convention generated stub; no reader |  |
| scripts/lib/README.md | 19 | doc-sync / per-folder-convention generated stub; no reader |  |
| scripts/todo/INDEX.md | 34 | doc-sync / per-folder-convention generated stub; no reader |  |
| scripts/todo/README.md | 38 | doc-sync / per-folder-convention generated stub; no reader |  |
| skills/INDEX.md | 35 | doc-sync / per-folder-convention generated stub; no reader |  |
| skills/README.md | 22 | doc-sync / per-folder-convention generated stub; no reader |  |
| skills/ui-anti-pattern-catalog/INDEX.md | 13 | doc-sync / per-folder-convention generated stub; no reader |  |
| skills/ui-anti-pattern-catalog/README.md | 12 | doc-sync / per-folder-convention generated stub; no reader |  |
| skills/ui-apca-contrast/INDEX.md | 13 | doc-sync / per-folder-convention generated stub; no reader |  |
| skills/ui-apca-contrast/README.md | 12 | doc-sync / per-folder-convention generated stub; no reader |  |
| skills/ui-axe-injector/INDEX.md | 14 | doc-sync / per-folder-convention generated stub; no reader |  |
| skills/ui-axe-injector/README.md | 15 | doc-sync / per-folder-convention generated stub; no reader |  |
| skills/ui-beauty-score/INDEX.md | 13 | doc-sync / per-folder-convention generated stub; no reader |  |
| skills/ui-contextual-heuristics/INDEX.md | 13 | doc-sync / per-folder-convention generated stub; no reader |  |
| skills/ui-contextual-heuristics/README.md | 12 | doc-sync / per-folder-convention generated stub; no reader |  |
| skills/ui-shared/INDEX.md | 16 | doc-sync / per-folder-convention generated stub; no reader |  |
| skills/ui-shared/README.md | 12 | doc-sync / per-folder-convention generated stub; no reader |  |
| skills/ui-state-matrix/INDEX.md | 13 | doc-sync / per-folder-convention generated stub; no reader |  |
| skills/ui-state-matrix/README.md | 12 | doc-sync / per-folder-convention generated stub; no reader |  |
| skills/ui-token-conformance/INDEX.md | 13 | doc-sync / per-folder-convention generated stub; no reader |  |
| skills/ui-token-conformance/README.md | 12 | doc-sync / per-folder-convention generated stub; no reader |  |
| templates/INDEX.md | 14 | doc-sync / per-folder-convention generated stub; no reader |  |
| templates/README.md | 12 | doc-sync / per-folder-convention generated stub; no reader |  |
| tests/score-inject-contract/INDEX.md | 14 | doc-sync / per-folder-convention generated stub; no reader |  |
| tests/score-inject-contract/README.md | 12 | doc-sync / per-folder-convention generated stub; no reader |  |
| tests/score-lifecycle-contract/INDEX.md | 13 | doc-sync / per-folder-convention generated stub; no reader |  |
| tests/score-lifecycle-contract/README.md | 12 | doc-sync / per-folder-convention generated stub; no reader |  |
| tools/demo/INDEX.md | 22 | doc-sync / per-folder-convention generated stub; no reader |  |
| tools/demo/README.md | 9 | doc-sync / per-folder-convention generated stub; no reader |  |

#### P  product surface: KEEP under the published-product decision (manifest said DELETE because it assumed a personal tool) — 23 files / 2333 lines

| file | lines | why | companion edit / owner |
|---|---|---|---|
| .github/CODE_OF_CONDUCT.md | 39 | community-profile file of a published, general-purpose product | keep; CONTRIBUTING.md:3 product name follows the naming decision; PR template item "Docs/INDEX updated" (:25) follows the INDEX decision |
| .github/CONTRIBUTING.md | 39 | community-profile file of a published, general-purpose product | keep; CONTRIBUTING.md:3 product name follows the naming decision; PR template item "Docs/INDEX updated" (:25) follows the INDEX decision |
| .github/ISSUE_TEMPLATE/bug_report.md | 41 | community-profile file of a published, general-purpose product | keep; CONTRIBUTING.md:3 product name follows the naming decision; PR template item "Docs/INDEX updated" (:25) follows the INDEX decision |
| .github/ISSUE_TEMPLATE/feature_request.md | 29 | community-profile file of a published, general-purpose product | keep; CONTRIBUTING.md:3 product name follows the naming decision; PR template item "Docs/INDEX updated" (:25) follows the INDEX decision |
| .github/PULL_REQUEST_TEMPLATE.md | 27 | community-profile file of a published, general-purpose product | keep; CONTRIBUTING.md:3 product name follows the naming decision; PR template item "Docs/INDEX updated" (:25) follows the INDEX decision |
| .github/SECURITY.md | 38 | community-profile file of a published, general-purpose product | keep; CONTRIBUTING.md:3 product name follows the naming decision; PR template item "Docs/INDEX updated" (:25) follows the INDEX decision |
| .github/assets/demo-trace.json | 161 | README hero media of the published product (hero chain gated by scripts/verify-claims.sh:207-209) | keep |
| .github/assets/guard-hero.json | 193 | README hero media of the published product (hero chain gated by scripts/verify-claims.sh:207-209) | keep |
| .github/assets/guard-hero.svg | 37 | README hero media of the published product (hero chain gated by scripts/verify-claims.sh:207-209) | keep |
| .github/assets/hero-capture-evidence.json | 33 | README hero media of the published product (hero chain gated by scripts/verify-claims.sh:207-209) | keep |
| .github/assets/hero-capture.txt | 17 | README hero media of the published product (hero chain gated by scripts/verify-claims.sh:207-209) | keep |
| .github/assets/hook-hero.svg | 33 | README hero media of the published product (hero chain gated by scripts/verify-claims.sh:207-209) | keep |
| .github/assets/hook-trace.json | 181 | README hero media of the published product (hero chain gated by scripts/verify-claims.sh:207-209) | keep |
| .github/assets/pipeline-hero-sources.json | 33 | README hero media of the published product (hero chain gated by scripts/verify-claims.sh:207-209) | keep |
| .github/assets/pipeline-hero.svg | 38 | README hero media of the published product (hero chain gated by scripts/verify-claims.sh:207-209) | keep |
| NOTICE | 32 | third-party attribution of a published product; wrong content (lists only skills/.archive, omits axe-core MPL-2.0) | SIMPLIFY: rewrite to the axe-core MPL-2.0 attribution; do not delete |
| examples/guard-demo/README.md | 124 | public demo guide of the published product (README.md:103,407,619) | keep |
| examples/guard-demo/run-demo.sh | 245 | standalone block->grant->consume demo for users | keep |
| examples/guard-demo/run-hero-demo.sh | 139 | produces the README hero media (hero chain) | keep with the hero chain |
| requirements/py310.txt | 309 | supported-Python lock for the published product (baseline.yml matrix leg 3.10) | keep while the 3.10 leg is claimed |
| requirements/py311.txt | 257 | supported-Python lock for the published product (baseline.yml matrix leg 3.11) | keep while the 3.11 leg is claimed |
| tools/demo/sample-hook-trace.json | 127 | example input documented by tools/demo/manifest.schema.md:85 | keep (product example) |
| tools/demo/sample-trace.json | 161 | example input documented by tools/demo/manifest.schema.md:84 | keep (product example) |


### E1.3 Missed by the manifest's DELETE set (verified the same way as V2)

| file | lines | manifest disposition | class | why | companion |
|---|---|---|---|---|---|
| hooks/protection-status.sh | 86 | DECIDE | I | status report of the retired "three-layer protection" design (greps for a `smart-checkpoint` hook that does not exist; its installers exit 0) | drop the echo at hooks/start-fswatch-all.sh:90 |
| hooks/tests/fixtures/overwrite_corpus.json | 573 | DECIDE | I | corpus of the never-registered pretool-overwrite-guard.py | goes with the guard (E1 I3) |
| hooks/tests/test_overwrite_guard.py | 1,641 | DECIDE | I | 1,600 lines of tests for a hook that never runs | same |
| hooks/tests/test_sessionstart_artifact_census.py | 278 | DECIDE | I | tests the never-registered census hook | same |
| scripts/regen-index-dirs.py | 103 | DECIDE | I | guard-bypass wrapper for the removed /doc-sync command (:5-7); its test is already in the DELETE set | drop the comment scripts/aggregate-dev-report.py:1400 |
| commands/INDEX.md, commands/README.md, agents/INDEX.md, agents/README.md | 35+37+35+39 | MOVE_OUT | I (move) | generated, no frontmatter, inside the directories Claude Code loads as slash commands / agent definitions (`/INDEX`, `/README` per scripts/install/profiles/core.json:147 "unmanifested_route"; inferred, not observed in a live CLI) | delete; after E2.a doc-sync never recreates them; add `.claude/commands` and `.claude/agents` exclusion to the rule-inspector convention (agents/rule-inspector.md) so /clean does not ask for them again |
| scripts/repair-venv.sh + docs/reference/venv-repair.md | 190+51 | DECIDE / MERGE | D | one-off (ticket-20260529); `scripts/bootstrap --force` already recreates the venv; but it is a user-facing ops tool of a published product | decision U-E1d |
| scripts/prune-orphaned-workflow-bookmarks.sh | 213 | DECIDE | F | the only reclaimer of orphan `workflow-<sid>.json`; machine defaults (/var/lib/claude-accounts :89) | superseded by the producer-side cleanup in E2.b step 4, then delete |
| push.sh (repo root) | 71 | DECIDE | D | "private-lab maintainer pre-push wrapper" (release-membership.v1.json:46,59); no in-repo caller | C3 decision |
| hooks/git-hooks/pre-commit, hooks/pre-commit-check.sh, hooks/sentinel-lint.sh | 40+74+92 | DECIDE (Q7) | D | git pre-commit feature with no live installer; the author's installed copy has drifted | Q7 (keep a git pre-commit hook?) |
| tests/generated/manifest.json | 597 | DECIDE | F | test-writer's global index (agents/test-writer.md:88-133); 146 of 148 entries point at ignored/absent dirs | E2.b: ignore it like the rest of tests/generated (producer contract stays) |
| scripts/install-checkpoint-refspec.sh | 63 | DECIDE | F | sole consumer path for remote checkpoint refs (D1.d) | D cluster U1 |

The manifest's other 167 DECIDE rows are outside "the deletable set" and are owned by the clusters whose rulings they wait on.

### E1.4 Decisions surfaced by E1 (one line each)

- U-E1a (shared with D cluster U3): confirm the abandoned-cycle code in I5/I6 (LANE-B, negative-evidence, dev-fix, repair-map,
  spec-update-contract, attribution CLIs) is not a held feature. Recommended: yes, delete (nothing ever called it).
- U-E1b: retire the per-folder INDEX.md/README.md convention (50 G files here, 85 tracked in total, /clean rule-inspector + doc-sync)?
  Recommended under the hold: no; just stop doc-sync creating new ones (E2.a). Revisit when the hold lifts.
- U-E1c: the 4 product docs (launch-plan, positioning, rename-execution-plan, roadmap-decomposition-productization) and ONE product
  name (README.md:1 / NOTICE / CONTRIBUTING.md:3 say `claude-code-guardrails`, the repo is `awesome-claude-harness`).
- U-E1d: scripts/repair-venv.sh + venv-repair.md (ops tool vs junk).
- U-E1e: tests/test_dev_artifact_chain_consumer_contracts.py and the other prose-pinning tests (X52): may tests that only pin prompt
  wording go? Needed by E3.c.
- U-E1f: schemas/graphify-prequery.v1.json: validate graphify `pre_query.json` at its producer (scripts/graphify-query.py:260) or delete.
- Open-defect docs (8) and product docs: see E4.

### E1.5 Fix (minimal, producer-side)

1. One deletion change, built in a hook-free container (this one) as a reviewed PR, merged by the human. Agents cannot delete on the
   live harness (F1), and nothing here weakens that. Contents: the 202 I files + 5 missed I files + the 4 harmful generated files,
   with every companion edit in the tables in the same change:
   settings allow rules (settings.json:41,114,135-137,191-192; template:122-124,141,175,180), the journal-view sidecar call
   (hooks/subagentstop-artifact-contract-enforce.py:426-494), the AC12 function (tests/test_late_repair_route.py:1191-1195), the
   ws2 gate call (tests/fresh-clone-bootstrap-smoke.sh:489), test pointers (hooks/tests/test_attribution_adjudicator.py:447,472,584),
   tests/score-lifecycle-contract/test-lifecycle-cas.sh:23, schemas/registry.json:16, schemas/dev-report.v2.json:46 wording,
   scripts/todo/do.py:4 docstring, conftest.py:11-12 comment, tests/TESTING.md rows, NOTICE rewrite (axe-core MPL-2.0 only),
   and `.gitignore:143-155` (the tests/generated negation block becomes `tests/generated/` only).
2. Deleting `tests/test_tool_policy_inference_note.py` (module-level `pytest.fail` at :39-40) removes the single CI collection
   breaker (C4.b): this change is also the first step of C4.
3. G, F, P: no action under the hold. E2.a stops G from growing.
4. Do this after E2.a lands, otherwise doc-sync regenerates the deleted INDEX/README stubs on the next edit in those folders.

---

## E2 — runtime writes into the harness source tree and into product repos

### E2.0 Root cause

Three couplings, all by construction:
1. The harness source IS `~/.claude`, the Claude Code config dir (NESTED-REPO.md:7-11). Everything the CLI and the hooks write under
   `~/.claude` lands in the source checkout. The harness-home resolver walks up from the hook file to the first dir holding
   `settings.json`+`hooks/`+`policies/`+`scripts/` (hooks/lib/claude_home.py:48-60), i.e. the repo root.
2. Per-project state goes to `<project>/.claude/` and `<project>/docs/dev/` of whatever repo the session runs in
   (hooks/prompt-workflow.py:62-91 resolves PROJECT_DIR from CLAUDE_PROJECT_DIR → payload cwd → getcwd → git toplevel → harness home).
   No producer makes those paths invisible to git in that repo. The only hook meant to do it, hooks/session-gitignore-propagate.sh,
   exits unless the repo carries `.claude/.awesome-claude-harness` (:21-22), which only the harness repo has.
3. doc-sync regenerates INDEX.md/README.md in any directory of any repo whose file is edited, mirrors watched `.claude/*` edits into
   the harness home, and creates/patches CLAUDE.md (hooks/doc_sync/main.py:113-134,183).

Consequence for the producer architecture: A3's first producer input (`files_created` = all untracked files, agents/dev.md:522-527)
picks up every one of these files as "work" (V3: 75 untracked files after 8 prompts in a clean repo).

### E2.a doc-sync (harness source AND product repos)

| file:line | what it writes | where it lands | defect |
|---|---|---|---|
| hooks/posttool-doc-sync.py:10 → hooks/doc_sync/main.py:152-192 | entry; registered PostToolUse Write/Edit/NotebookEdit (settings.json:717, template:675) | — | runs after every Write/Edit of a file with a watched extension (main.py:25-29) **in any repo**; `should_sync` (:49-57) is true outside WATCHED_DIRS too |
| hooks/doc_sync/main.py:113-120 (`_regen_if_dir`) → regen_readme.py:215, regen_index.py:235 | README.md then INDEX.md of the edited file's directory | product repos and the harness | **creates** the files when absent (regen_index.py:221-235, regen_readme.py:194-215); V4b created `src/INDEX.md`, `src/README.md` in a fresh repo |
| hooks/doc_sync/main.py:122-134 (`_maybe_regen_global`) | README.md/INDEX.md of `~/.claude/{commands,agents,hooks,skills,scripts}` | **harness source**, from a session in any other project that edits its own `.claude/<watched>` | one project's edit rewrites the harness tree |
| hooks/doc_sync/main.py:183 → patch.py:129-162 → claude.py:18-30 | `CLAUDE.md` (and `.claude/CLAUDE.md`) | product repos and the harness | `ensure_claude_md` **creates** CLAUDE.md (claude.py:28-30) or **prepends** a header to an existing one (claude.py:23-26); patch.py rewrites AUTO blocks (:149-162) |
| hooks/doc_sync/patch.py:113-116,154 (`_patch_last_updated`) | `> Last updated: <today>` inside `<!-- AUTO:last-updated -->` | **harness CLAUDE.md:3-5** (user-owned global instructions) and any opted-in CLAUDE.md | daily date churn: 33 of the last 40 CLAUDE.md commits (V5); V4a rewrote it on one Write |
| hooks/doc_sync/patch.py:119-126,158-160 (`_patch_docker`, `_patch_systemd`) | docker-compose / systemctl tables | product CLAUDE.md files that carry the markers | host state written into a tracked file loaded into every session |
| hooks/doc_sync/hook_ledger.py:145-172,261,298 (paths from ledger_contract.py:46-54) | ledger entries of doc-sync's own side-effect files | `<project>/.claude/dev-registry/<id>/<ledger dir>/` | exists only so /dev attribution can account for doc-sync's writes (A3 coupling; merged by scripts/aggregate-dev-report.py:1190,1410) |
| hooks/userprompt-doc-sync-check.py:22,212-213 | `.doc-sync-cache.json` snapshot cache | **harness root** (`Path.home()/.claude`) | runtime file in source (ignored at .gitignore:55) |
| hooks/userprompt-doc-sync-check.py:146-199 | on a detected deletion: re-runs posttool-doc-sync.py with `CLAUDE_PROJECT_DIR=<root>/.claude` (:180-187) or unlinks INDEX.md (:171-176) | `<root>/.claude/*` for root ∈ {CLAUDE_DOC_SYNC_ROOTS, CLAUDE_PROJECT_DIR, $HOME} (:46-66) | with root=$HOME the child patches `~/.claude/CLAUDE.md` = harness CLAUDE.md |
| tracked outputs | 85 tracked INDEX.md/README.md (61 with an AUTO marker) — listed in D-orphans-dangling.md Appendix A | harness source | 359 of 778 commits touch them (X03) |

Fix (shared with D-orphans-dangling Step 3; effort S):
1. regen_index.py:221 and regen_readme.py:194: when the target file is absent, return a skip status; never create.
2. claude.py:18-30 and patch.py:135: never create or prepend CLAUDE.md; only rewrite AUTO blocks that already exist.
3. patch.py:154: delete the `_patch_last_updated` call (the CLAUDE.md:3-5 markers become inert text; the user's file is not edited).
4. main.py:122-134: delete `_maybe_regen_global` (no session writes into another tree).
5. main.py:35-41: add `docs/dev/` to EXCLUDED_PATTERNS.
Result: doc-sync creates nothing anywhere; existing marked files are still maintained (no feature retired).

### E2.b Per-project runtime state written into product repos (and into the harness when it self-hosts)

| file:line | what | path under the product repo | ignored there by any producer? |
|---|---|---|---|
| hooks/prompt-workflow.py:181,1899,1986-1996 | workflow bookmark (UserPromptSubmit, every slash command) | `.claude/workflow-<sid>.json` | no |
| hooks/posttool-subagent-track.py:73,260; posttool-todo-sequence.py:146,171,222; posttool-todo-tracker.py:74; pretool-todo-validate.py:151 | bookmark field updates | `.claude/workflow-<sid>.json` | no |
| hooks/prompt-workflow.py:1464-1491 (`_reserve_dev_registry`) | per-cycle registry with 19 per-agent sentinel files | `.claude/dev-registry/<task>/` | no (V3: 57 files from 3 /dev-family prompts) |
| hooks/prompt-workflow.py:1473 + _init_dev_registry | user requirement document | `docs/dev/user-requirement-<task>.md` | no |
| hooks/prompt-workflow.py:1365-1385 | /do report skeleton | `docs/dev/do-report-<task>.json` | no |
| hooks/prompt-workflow.py:1778 | workflow lock | `.claude/workflow-locks/<sid>.lock` | no |
| hooks/prompt-workflow.py:1782,1912 | start replay (stores the full stdout, incl. the re-injected command body, E3.a) | `.claude/dev-start-replays/<sid>/<digest>.json` | no |
| hooks/prompt-workflow.py:1817 | workflow history | `.claude/workflow-history/<sid>/<gen>-<id>` | no |
| hooks/prompt-workflow.py:781,1038 | overnight delivery marker | `.claude/overnight-delivery-<sid>.json` | no |
| scripts/create-overnight-state.sh (state), :450, :664, :712 | overnight state; fresh clones; registry; trace | `.claude/overnight-state-<sid>.json`, `.claude/overnight-fresh-clones/` (whole git clones), `.claude/dev-registry/<sid>/`, `docs/dev/overnight/.../trace.jsonl` | no |
| scripts/overnight-init.sh:204 | registry | `.claude/dev-registry/<sid>/` | no |
| hooks/lib/contract_runtime.py:91,1102,1245-1248 | cycle contract; locks | `.claude/overnight-contract-<sid>-cycle<n>.json`, `.claude/locks/` | no |
| hooks/posttool-overnight-trace.py:394,473-481 | agent bookmark; cycle trace | `.claude/agent-bookmark-<sid>.json`, `docs/dev/overnight/<sid>/cycle-<n>/trace.jsonl` | no |
| hooks/lib/closeout.py:68; hooks/lib/specialist_yield.py:81 | specialist yield log | `.claude/state/specialist-yield-log.jsonl` | no |
| hooks/notification-idle-overnight.py:49,64 | idle log | `.claude/logs/overnight-idle.jsonl` | no |
| hooks/pretool-overnight-hook-guard.py:60,75 | self-repair audit | `.claude/logs/overnight-self-repair.jsonl` | no |
| scripts/overnight-git-env.sh:38-39 | git shim bins | `.claude/overnight-git-bin/`, `.claude/overnight-git-policy-bin/` | no |
| scripts/create-worktree.sh:35,123 | worktrees | `.claude/worktrees/` | no |
| hooks/lib/session_resources.py:741,1058,1257,2016,2051 | LANE-B resource state and scratch (never provisioned, X63) | `.claude/session-resources/`, `.claude/scratch/` | no |
| hooks/stop-completion-gate.py:410-413 | completion-gate state + audit | `.claude/dev-registry/<cycle>/completion-gate-state.json`, `completion-gate-audit.jsonl` | no |
| hooks/posttool-codex-skill-ledger.py:93,113 | codex ledger | `.claude/dev-registry/<sid>/codex-ledger/<agent>.json` | no |
| hooks/pretool-cp-checkin.py:155,174 | agent index | `.claude/dev-registry/agent-index.json` | no |
| scripts/spec-check.py:252; hooks/pretool-cp-checkin.py:196 | cp-state | `.claude/specs/<spec>/cp-state-<agent>.json` | no |
| scripts/write-enforce-flag.sh:42; scripts/write-qa-mode.sh:35 | enforce flag; qa mode | `.claude/dev-registry/<sid>/` | no |
| scripts/graphify-enrich.py:125,456; scripts/graphify-query.py:260 | blast-radius map; graphify outputs | `.claude/dev-registry/<task>/graphify/` | no |
| scripts/graphify_lib.py:15,152 | graphify manifest (cwd-relative) | `graphify-out/manifest.json` | no |
| scripts/dev-lifecycle.py:937 | lifecycle cache | `.claude/cache/dev-lifecycle.sqlite3` | no |
| scripts/lib/attribution_aggregate_view.py via hooks/subagentstop-artifact-contract-enforce.py:426-494 | journal view nobody reads (E1 I5) | `docs/dev/journal-view-<task>.json` | no |
| scripts/paseo-daemon-ledger.py:2781 (`--root .claude/paseo-daemon`) | paseo ledger | `.claude/paseo-daemon/` | no |
| commands/codex.md:95,127,162,171 | codex outputs (`tee`) | `docs/codex/<task>/<role>.txt` | no |
| agents/test-writer.md:45-133 (prompt producer) | test skeletons, per-task and global manifest | `tests/generated/<task>/*`, `tests/generated/manifest.json` | no |
| all pipeline prompts (dev, qa, ba, close, commit, …; 260 tracked files mention docs/dev, D2.e) | pipeline artifacts by design | `docs/dev/<artifact>-<task>.*` | no |
| Playwright MCP (QA live E2E) | screenshots, MCP dir | `*.png`, `.playwright-mcp/` | no |
| hooks/lib/checkpoint-core.sh:322-413 (via auto-commit.sh Stop and posttool-git-checkpoint.sh) | snapshot refs, **pushed to origin** | `refs/checkpoints/<branch>` | owned by D-cluster D1.d (not repeated) |
| hooks/session-gitignore-propagate.sh:29-32 | appends 4 rules to the tracked `.gitignore` | `.gitignore` (only in repos with the marker = the harness) | — |
| scripts/update-gitignore.sh (agents/cleaner.md:76 action) | appends Python/Node rules | product `.gitignore` | feature-tied (/clean) |

Fix (effort S; one existing producer, no new state file):
1. Re-scope hooks/session-gitignore-propagate.sh (already registered SessionStart: settings.json:345, template:337): write to
   `$(git -C "$PROJECT_DIR" rev-parse --git-path info/exclude)` instead of the tracked `$GIT_ROOT/.gitignore`; drop the marker gate
   (:21-22); keep the idempotent append (:29-32). Rule list = the families in the table: `.claude/workflow-*.json`,
   `.claude/workflow-locks/`, `.claude/workflow-history/`, `.claude/dev-start-replays/`, `.claude/dev-registry/`,
   `.claude/specs/*/cp-state-*.json`, `.claude/overnight-*.json`, `.claude/agent-bookmark-*.json`, `.claude/state/`, `.claude/cache/`,
   `.claude/locks/`, `.claude/logs/`, `.claude/scratch/`, `.claude/session-resources/`, `.claude/overnight-fresh-clones/`,
   `.claude/overnight-git-bin/`, `.claude/overnight-git-policy-bin/`, `.claude/worktrees/`, `.claude/paseo-daemon/`, `docs/dev/`,
   `docs/codex/`, `tests/generated/`, `graphify-out/`, `.playwright-mcp/`.
   `info/exclude` is git's own untracked per-repo file: no tracked file of the user's repo changes and no harness state file is added.
   `git status --porcelain` then no longer reports runtime state, which cleans A3's untracked-file input at its source.
2. Delete `.claude/.awesome-claude-harness` (the marker; manifest row) in the same change.
3. Delete the journal-view sidecar (E1 companion edit).
4. Open defect "22/22 workflow bookmarks orphaned" (docs/reference/workflow-bookmark-orphans-20261005.md): the writer owns the
   cleanup. The registered SessionEnd hook (hooks/sessionend-scratch-sweep.sh, settings.json:853) removes
   `<project>/.claude/workflow-<sid>.json` for its own `session_id`; then scripts/prune-orphaned-workflow-bookmarks.sh can go.
Decision U-E2a: may the harness write `.git/info/exclude` in the user's product repos? (Recommended: yes; the alternative is the
status quo, where every product repo accumulates untracked harness state.)

### E2.c Home-side writes that land in the harness source (repo == ~/.claude; kept under the status-quo decision)

| file:line | what | path in the source tree | .gitignore line |
|---|---|---|---|
| hooks/prompt-workflow.py:177,1898,1976-1977; posttool-todo-tracker.py:58; pretool-block-background-tasks.py:95; pretool-spec-block-foreground-agent.py:33; pretool-workflow-gate.py:91; scripts/break-overnight-lock.py:31 | the CLI's todo file, pre-written by the hook | `todos/<sid>-agent-<sid>.json` (ignores CLAUDE_CONFIG_DIR, so on multi-account hosts it writes into the source instead of the account dir) | :16 |
| hooks/lib/checkpoint-core.sh:64-66,101,108,118,128,404; hooks/pretool-bash-safety.sh:816 | checkpoint.log, checkpoint-push.log, .checkpoint-fail-count | `logs/` | :46, :180 |
| hooks/pretool-bash-safety.sh:433; hooks/userprompt-consent-allowlist.sh:666; hooks/stop-cleanup-allowlist.sh:23 | bash-consent.log | `logs/` | :46 |
| hooks/pretool-bash-safety.sh:545 | claude-daemon-restart-grants.log | `logs/` | :46 |
| hooks/push.sh:439-443 | git-privilege-grants.log | `logs/` | :46 |
| hooks/pretool-obligation-gate.py:77; pretool-aggregate-check.py:385; stop-obligation-gate.py:56; posttool-overnight-loop.py:28; subagentstop-artifact-contract-enforce.py:120; stop-completion-gate.py:83; stop-do-report-gate.py:58; posttool-lane-completeness-watch.py:68; subagentstop-cp-enforce.py:34-36 | advisory-gate JSONL sinks nobody reads (A1's advisory branch; D1.e) | `logs/*.jsonl` | :46 |
| hooks/stop-completion-gate.py:412,567 | completion-gate fallback state | `logs/completion-gate-<cycle>.json`, `logs/completion-gate-registry-<sid>.json` | :46 |
| scripts/score-update.sh:40; scripts/score-inject.sh:15 | lifecycle.jsonl | `logs/lifecycle.jsonl` (.gitignore:47 comment calls it a "PERMITTED DELIVERY PATH", but `logs/*` ignores it) | :46 |
| hooks/git-fswatch.sh:27; hooks/fswatch-manager.sh:171; hooks/start-fswatch-all.sh:51-55 | fswatch logs/pids (opt-in daemon) | `logs/` | :46 |
| hooks/git-hooks/post-commit-auto-push:23 (installed copies) | post-commit-auto-push.log | `logs/` | :46 |
| scripts/prune-orphaned-workflow-bookmarks.sh:182-184 | workflow-bookmark-prune.log | `logs/` | :46 |
| hooks/lib/subagent_restart.py:150 | restart state | `restart-state/` | :185 |
| hooks/lib/attribution_journal.py:81-91,300 | write-time attribution journal (`realpath(hook)/../../state`) | `state/attribution-journal/` | :184 |
| scripts/seal-attribution-journal.py:64-71 (autoseal from hooks/lib/attribution_journal.py:407-427) | sealed journal copies + a bare git store + seal-log.jsonl | `attribution-seals/` when CLAUDE_CONFIG_DIR is unset (`realpath(~/.claude)`) | **none: not ignored** (a git store inside the source) |
| hooks/userprompt-doc-sync-check.py:22,212-213 | doc-sync cache | `.doc-sync-cache.json` | :55 |
| scripts/bootstrap:18,154 | settings backups; venv | `settings.json.bak-*`, `venv/` | :95, :32 |
| every python hook (no PYTHONDONTWRITEBYTECODE in settings env) | bytecode | `hooks/__pycache__/`, `hooks/lib/__pycache__/`, `hooks/doc_sync/__pycache__/`, `scripts/lib/__pycache__/`, root `__pycache__/` (present now, ignored) | :35-36 |
| hooks/tests/test_blackbox_integration.py (test run) | enforcement-run manifest | `hooks/tests/.enforcement-run-manifest.json` | :84 |
| the Claude Code CLI itself (config dir == repo) | credentials, transcripts, todos, plugins, statsig, history, shell snapshots, session-env, file-history, sessions, mcp cache, paste-cache, plans, tasks, .claude.json and its backups | root-level dirs/files | :4, :9, :16-19, :22-23, :26, :48, :52, :58, :61, :94, :106, :181-182, :186 |

Fix (effort S; status quo kept, so these stay in the tree but stop leaking):
1. scripts/seal-attribution-journal.py:69-70: default `base` to the journal's own state dir (`hooks/lib/attribution_journal.py`
   `state_dir().parent`, i.e. `<source>/state/`, already ignored by `.gitignore:184`) instead of `realpath(~/.claude)`.
2. settings.template.json env (and settings.json until C2 makes it rendered): `"PYTHONDONTWRITEBYTECODE": "1"`. One line; every hook
   stops writing bytecode into the source tree.
3. The todo-path sites (7) belong to C1 (resolve the CLI config dir from CLAUDE_CONFIG_DIR, fallback `~/.claude`); listed here only
   because they write into the source on multi-account hosts.

### E2.d .gitignore rules, each mapped to the writer it exists for

| .gitignore line(s) | rule | exists because of | verdict |
|---|---|---|---|
| 4, 9, 16-19, 22-23, 26, 48, 52, 58, 61, 94, 106, 181, 182, 186 | CLI config-dir files (`.credentials.json`, `settings.local.json`, `todos/`, `shell-snapshots/`, `debug/`, `projects/`, `plugins/`, `statsig/`, `history.jsonl`, `session-env/`, `file-history/`, `mcp-needs-auth-cache.json`, `sessions/`, `backups/.claude.json.backup.*`, `/.claude.json`, `paste-cache/`, `plans/`, `tasks/`) | repo == config dir (coupling 1) | keep under the status quo; anchor `projects/` (:19) to `/projects/` (it swallows `tests/projects/x.py`, X41) |
| 46-47, 180 | `logs/*`, `logs/` | E2.c log writers | keep one (`/logs/`); :180 duplicates :46 |
| 55 | `.doc-sync-cache.json` | userprompt-doc-sync-check.py:22 | keep |
| 84 | `hooks/tests/.enforcement-run-manifest.json` | test writes into source | keep (test producer; could write to tmp) |
| 87-89, 92-93, 102, 121-128, 133-136 | per-project families (`workflow-*.json`, `dev-registry/`, `specs/*/cp-state-*.json`, `specs/spec-*/`, `worktrees/`, `/.claude/specs/spec-*/`, `workflow-locks/`, `dev-start-replays/`, `.hook-refactor-allow`, `paseo-daemon/`, `scratch/`, `workflow-history/`, `overnight-git-bin/`, `overnight-git-policy-bin/`, `overnight-state-*.json`, `overnight-contract-*.json`, `tw-gen-*.py`, `overnight-delivery-*.json`) | coupling 2 when the harness self-hosts (and, for project `/root`, coupling 1) | covered by E2.b's info/exclude once it lands; keep until then |
| 67-78, 173 | `docs/*` + 4 negations; `docs/dev/` | pipeline artifact store when self-hosting | keep `docs/*`+negations; :173 duplicates :67 → delete |
| 95, 32-36 | `settings.json.bak-*`; `venv/`, `*.pyc`, `__pycache__/` | scripts/bootstrap; hooks' bytecode | keep (hygiene) |
| 100-101 | `/agent-scores.json`, `/agent-scores.json.lock` | a writer that no longer exists (scripts/score-update.sh:104 "write path removed") | delete |
| 64, 65, 66, 140 | `.last-cleanup`, `playwright-storage-state.json`, `.todos.json`, `/downstream` | no writer anywhere in the repo (grep: 0) | delete (:65 if Playwright storage is not used) |
| 49 | `systemd/` | fswatch-manager.sh:261 expects `~/.claude/systemd/git-fswatch@.service`; nothing writes it (the unit is hooks/git-fswatch@.service) | delete with the D2.c path fix |
| 145-160 | tests/generated negation dance (9 rules) | the 2 tracked July cycles + the tracked global manifest | collapse to `tests/generated/` after E1 deletes the 2 cycles and E2.b ignores the manifest |
| 161, 162, 165, 170 | `docs/codex/`, `.playwright-mcp/`, `*.png`, `graphify-out/` | commands/codex.md:95; Playwright MCP; screenshots; graphify_lib.py:15 | keep; anchor `*.png` (unanchored; would swallow real images) |
| 166-167 | `.claude/dev-registry/dev-*/` (appended by session-gitignore-propagate.sh:31) | the propagator itself | delete (duplicates :88) |
| 176, 178, 183, 184, 185 | `archive/`, `cache/`, `specs/`, `state/`, `restart-state/` (unanchored "global no-track policy") | attribution journal (`/state/`), restart state (`/restart-state/`), cp-state (`specs/`), dev-lifecycle cache (`.claude/cache/`), /clean archive | anchor to `/archive/`, `/cache/`, `/specs/`, `/state/`, `/restart-state/` (each unanchored rule swallows source paths: `schemas/specs/a.json`, `tests/fixtures/state/a.json`, `hooks/lib/cache/x.py`, `docs/reference/archive/x.md`, wf2 SR-06) |
| 179 | `eval/` | no writer (only regex prose) | delete |
| 192-194 | `.github/**/README.md`, `.github/**/INDEX.md`, `.github/INDEX.md` | doc-sync | delete after E2.a (doc-sync never creates) |
| 5-6, 12-13, 29, 39-40, 43-44 | secrets and hygiene | — | keep |

Burden code that exists only for coupling 2/3: hooks/pretool-gitignore-preflight.py (824 lines; blocks dispatches whose deliverables
are gitignored), scripts/update-gitignore.sh (92), scripts/prune-orphaned-workflow-bookmarks.sh (213), hooks/session-gitignore-propagate.sh
(35, re-scoped by E2.b). Under the hold only the prune script goes (after E2.b step 4).

---

## E3 — prompt bloat

### E3.0 Root cause

Every incident fix appends prompt text and nothing removes any (F4); blocks are copied by hand into every agent (a5f650a added the
charter, codex and cp-state blocks to all agents); stamps record provenance in the text the model reads; and a hook re-sends whole
command files. 58 test files pin prompt wording (X52), so any trim turns CI red. Size history (wf2): 287 KB (2026-01-01) → 1,576 KB
(HEAD) for commands+agents+CLAUDE.md. One minimal /dev→/close→/commit→/push cycle loads ~383k tokens of instructions over 14
dispatches (wf2 P2; qa.md 31.5k loaded 4 times).

### E3.a The duplicate re-injection site

`hooks/prompt-workflow.py:1278-1280` (inside `checklist_message`, :1265-1281):

```python
    spec = read_command_spec(cmd_name)
    if spec:
        lines += ['', f'--- /{cmd_name} COMMAND SPECIFICATION ---', '', spec]
```

Callers: `_ordinary_dev_start` (:1909, for dev, dev-command, redev; the output is also persisted to
`.claude/dev-start-replays/<sid>/<digest>.json` at :1912) and `handle_phase_a` → `emit_checklist_message` (:1979, every command that
has a `scripts/todo/<cmd>.py`). Claude Code already expands the slash command's body into the prompt, so this is a second copy.
Introduced in f022edd (2026-03-23, the overnight loop); the overnight continuation path (:1090-1104, `include_spec` on a fresh
context) is a different, legitimate delivery and is not touched.

Measured (V3, sandbox stdout of the hook):

| command | hook stdout bytes | command body bytes (no frontmatter) |
|---|---|---|
| /close | 119,653 | 118,845 |
| /dev | 108,226 | 105,159 |
| /dev-command | 55,380 | 52,494 |
| /spec | 36,162 | 34,950 |
| /clean | 29,969 | 27,203 |
| /test | 18,487 | 16,243 |
| /do | 6,670 | 5,191 |
| /redev | 5,910 | 2,839 (redev.md) |
| /commit, /push, others without a todo script | 0 | — |

Per minimal cycle (/dev + /close): 227,879 B ≈ 57k tokens of duplicate text in the main context (if the CLI does not truncate hook
stdout; see the correction in the verification log). No test pins this output (`git grep` for `checklist_message` / `COMMAND SPEC`
finds only the overnight header tests: tests/test_prompt_workflow_injection_cadence.py:55, tests/test_prompt_workflow_liveness_tz.py:261,478).

Fix (effort S, risk low): delete the three lines. Keep `read_command_spec` (still exercised by the overnight tests). The replay files
shrink by the same amount.

### E3.b Per-file prompt size (commands, agents, CLAUDE.md, skills' SKILL.md)

Totals: commands 23 files / 718,760 B (~179.7k tokens); agents 25 / 845,754 B (~211.4k); CLAUDE.md 11,106 B (~2.8k, loaded into
every context); skills 28 files / 53,983 B. Prompt layer total 77 files / 1,629,603 B (~407k tokens).

| file | bytes | lines | non-blank | ~tokens (bytes/4) | re-injected by prompt-workflow.py (stdout bytes, sandbox) |
|---|---|---|---|---|---|
| agents/changelog-analyst.md | 146672 | 2059 | 1768 | 36668 |  |
| commands/dev-overnight.md | 142918 | 1901 | 1409 | 35730 |  |
| agents/qa.md | 125998 | 1962 | 1535 | 31500 |  |
| commands/close.md | 119440 | 1017 | 835 | 29860 | 119653 |
| commands/dev.md | 105497 | 1750 | 1288 | 26374 | 108226 |
| agents/ba.md | 93437 | 1507 | 1140 | 23359 |  |
| commands/commit.md | 87500 | 1059 | 904 | 21875 |  |
| agents/pm.md | 64315 | 1199 | 937 | 16079 |  |
| agents/dev.md | 58201 | 1085 | 825 | 14550 |  |
| agents/spec.md | 53909 | 824 | 583 | 13477 |  |
| commands/dev-command.md | 52705 | 1176 | 854 | 13176 | 55380 |
| commands/paseo-daemon.md | 39581 | 608 | 536 | 9895 |  |
| agents/style-inspector.md | 38393 | 740 | 567 | 9598 |  |
| commands/spec.md | 35253 | 521 | 428 | 8813 | 36162 |
| agents/user.md | 34821 | 619 | 477 | 8705 |  |
| agents/ui-specialist.md | 30188 | 362 | 256 | 7547 |  |
| agents/product-owner.md | 28759 | 515 | 396 | 7190 |  |
| agents/architect.md | 28244 | 496 | 383 | 7061 |  |
| commands/clean.md | 27517 | 772 | 562 | 6879 | 29969 |
| agents/cleanliness-inspector.md | 22259 | 445 | 303 | 5565 |  |
| commands/merge.md | 16556 | 228 | 178 | 4139 |  |
| agents/prompt-inspector.md | 16445 | 310 | 237 | 4111 |  |
| commands/test.md | 16393 | 502 | 376 | 4098 | 18487 |
| agents/test-executor.md | 13937 | 424 | 337 | 3484 |  |
| commands/push.md | 13394 | 266 | 214 | 3348 |  |
| commands/restart.md | 13025 | 213 | 191 | 3256 |  |
| agents/test-writer.md | 11348 | 242 | 186 | 2837 |  |
| CLAUDE.md | 11106 | 126 | 77 | 2776 |  |
| agents/test-validator.md | 10853 | 350 | 271 | 2713 |  |
| agents/merge-analyst.md | 10091 | 223 | 163 | 2523 |  |
| commands/codex.md | 9737 | 204 | 157 | 2434 |  |
| agents/git-edge-case-analyst.md | 9059 | 276 | 212 | 2265 |  |
| agents/push-analyst.md | 8558 | 211 | 158 | 2140 |  |
| agents/rule-inspector.md | 8499 | 209 | 153 | 2125 |  |
| commands/spec-update.md | 8489 | 188 | 147 | 2122 |  |
| agents/cleaner.md | 8297 | 195 | 151 | 2074 |  |
| agents/pull-analyst.md | 6910 | 167 | 114 | 1728 |  |
| skills/ui-beauty-score/SKILL.md | 6451 | 132 | 101 | 1613 |  |
| agents/README.md | 6348 | 40 | 34 | 1587 |  |
| agents/INDEX.md | 6032 | 36 | 33 | 1508 |  |
| skills/ui-contextual-heuristics/SKILL.md | 5621 | 118 | 79 | 1405 |  |
| commands/do.md | 5388 | 85 | 57 | 1347 | 6670 |
| commands/INDEX.md | 5170 | 36 | 33 | 1292 |  |
| commands/README.md | 5101 | 38 | 32 | 1275 |  |
| skills/ui-state-matrix/SKILL.md | 5019 | 113 | 84 | 1255 |  |
| skills/ui-apca-contrast/SKILL.md | 4850 | 106 | 81 | 1212 |  |
| skills/ui-anti-pattern-catalog/SKILL.md | 4828 | 98 | 73 | 1207 |  |
| skills/ui-token-conformance/SKILL.md | 4464 | 98 | 74 | 1116 |  |
| skills/.archive/frontend-design/SKILL.md | 4275 | 43 | 30 | 1069 |  |
| agents/graphify.md | 4181 | 95 | 60 | 1045 |  |
| skills/ui-axe-injector/SKILL.md | 4071 | 104 | 80 | 1018 |  |
| commands/pull.md | 3879 | 121 | 87 | 970 |  |
| commands/tickets.md | 3402 | 70 | 57 | 850 |  |
| commands/redev.md | 3323 | 20 | 14 | 831 | 5910 |
| commands/stop.md | 1968 | 45 | 28 | 492 |  |
| commands/checkpoint.md | 1318 | 44 | 31 | 330 |  |
| commands/allow.md | 1206 | 7 | 5 | 302 |  |


### E3.c Stamp locations, every file

Regexes in the verification log. "dated-doc ref" lines cite a docs/reference file whose name carries a date; 20 of the 60 prompt
lines in that column cite the binding design doc (close-commit-zero-failure-mechanism-20260928.md), which stays (E4), so those lines
stay too. The JSON timestamp examples in agents/test-executor.md (:112-113,156,187-188,222, …) are example data, not stamps, and are
excluded.

Prompt files (31 files, 169 stamped lines: 91 task-id, 21 dated notes, 60 dated-doc refs, 2 commit SHAs; line numbers listed):

| file | task-id lines | dated-note lines | dated-doc-filename refs | commit-sha refs |
|---|---|---|---|---|
| commands/dev.md | 16: 424,481,546,555,806,809,811,844,1006,1091,1097,1098,1282,1345,1358,1399 | 0: - | 13: 441,481,510,635,743,825,874,1023,1658,1667,1673,1679,1749 | 0: - |
| commands/close.md | 19: 55,102,388,531,551,557,567,624,652,664,674,724,756,799,835,845,870,933,1015 | 0: - | 4: 32,131,551,1002 | 0: - |
| agents/ba.md | 10: 152,435,507,521,532,777,796,997,1009,1183 | 1: 1377 | 6: 546,552,649,655,1004,1403 | 0: - |
| agents/qa.md | 9: 95,100,156,265,352,1152,1378,1395,1609 | 1: 1319 | 5: 106,1197,1201,1347,1816 | 0: - |
| commands/commit.md | 5: 22,41,279,866,947 | 2: 402,448 | 4: 876,884,900,1015 | 2: 431,1035 |
| commands/dev-command.md | 1: 369 | 0: - | 11: 332,369,394,460,556,607,665,1129,1140,1148,1158 | 0: - |
| commands/dev-overnight.md | 5: 119,187,808,839,1727 | 0: - | 6: 977,1095,1197,1289,1390,1504 | 0: - |
| agents/style-inspector.md | 7: 46,110,114,337,339,341,602 | 1: 687 | 1: 341 | 0: - |
| agents/dev.md | 4: 124,170,501,518 | 1: 946 | 1: 972 | 0: - |
| agents/changelog-analyst.md | 4: 165,238,1025,1230 | 0: - | 1: 238 | 0: - |
| agents/pm.md | 2: 589,603 | 1: 1074 | 1: 1100 | 0: - |
| agents/spec.md | 1: 26 | 1: 743 | 1: 768 | 0: - |
| commands/paseo-daemon.md | 0: - | 0: - | 3: 11,12,257 | 0: - |
| agents/cleanliness-inspector.md | 1: 54 | 1: 392 | 0: - | 0: - |
| agents/merge-analyst.md | 0: - | 2: 54,198 | 0: - | 0: - |
| agents/prompt-inspector.md | 1: 61 | 1: 257 | 0: - | 0: - |
| agents/rule-inspector.md | 0: - | 2: 143,145 | 0: - | 0: - |
| agents/ui-specialist.md | 1: 247 | 1: 294 | 0: - | 0: - |
| skills/.archive/frontend-design/README.md | 0: - | 2: 37,40 | 0: - | 0: - |
| CLAUDE.md | 0: - | 1: 4 | 0: - | 0: - |
| agents/INDEX.md | 1: 30 | 0: - | 0: - | 0: - |
| agents/README.md | 1: 32 | 0: - | 0: - | 0: - |
| agents/architect.md | 0: - | 1: 420 | 0: - | 0: - |
| agents/product-owner.md | 0: - | 1: 436 | 0: - | 0: - |
| agents/test-writer.md | 1: 3 | 0: - | 0: - | 0: - |
| agents/user.md | 0: - | 1: 542 | 0: - | 0: - |
| commands/clean.md | 1: 771 | 0: - | 0: - | 0: - |
| commands/restart.md | 0: - | 0: - | 1: 81 | 0: - |
| commands/tickets.md | 0: - | 0: - | 1: 15 | 0: - |
| skills/INDEX.md | 1: 25 | 0: - | 0: - | 0: - |
| skills/ui-beauty-score/README.md | 0: - | 0: - | 1: 44 | 0: - |


Code files (hooks/, scripts/, excluding tests; 110 files, 608 stamped lines: 335 task-id, 157 dated notes, 109 dated-doc refs, 17 commit SHAs; counts per file, line numbers in stamps2.json):

| file | task-id | dated-note | dated-doc ref | sha | lines with any |
|---|---|---|---|---|---|
| hooks/pretool-bash-safety.sh | 33 | 19 | 8 | 1 | 60 |
| hooks/pretool-git-privilege-guard.py | 7 | 33 | 11 | 2 | 53 |
| scripts/aggregate-dev-report.py | 38 | 3 | 9 | 0 | 48 |
| scripts/paseo-daemon-ledger.py | 42 | 6 | 0 | 0 | 48 |
| hooks/pretool-gitignore-preflight.py | 13 | 11 | 21 | 0 | 42 |
| hooks/pretool-overnight-hook-guard.py | 6 | 13 | 0 | 0 | 19 |
| hooks/subagentstop-artifact-contract-enforce.py | 8 | 4 | 2 | 0 | 13 |
| scripts/resolve-dev-artifact-chain.py | 9 | 0 | 2 | 0 | 11 |
| hooks/lib/git_command_classifier.py | 1 | 9 | 0 | 0 | 9 |
| scripts/paseo-daemon-timers.py | 10 | 0 | 0 | 0 | 10 |
| hooks/lib/subagent_restart.py | 0 | 6 | 3 | 0 | 9 |
| scripts/score-update.sh | 9 | 0 | 0 | 0 | 9 |
| scripts/generate-repair-map.py | 1 | 0 | 7 | 0 | 8 |
| scripts/laneb-integration-gate.py | 3 | 0 | 5 | 0 | 8 |
| hooks/lib/obligation.py | 5 | 0 | 2 | 0 | 7 |
| hooks/pretool-cp-checkin.py | 4 | 2 | 1 | 0 | 7 |
| scripts/stage-owned-hunks.py | 2 | 0 | 3 | 2 | 7 |
| scripts/write-commit-grant.py | 1 | 3 | 0 | 3 | 7 |
| hooks/doc_sync/tree.py | 6 | 0 | 0 | 0 | 6 |
| hooks/lib/agent_resolver.py | 0 | 5 | 1 | 0 | 6 |
| hooks/lib/allowlist.py | 6 | 0 | 0 | 0 | 6 |
| hooks/lib/bash_write_targets.py | 5 | 1 | 0 | 0 | 5 |
| hooks/lib/contract_runtime.py | 6 | 0 | 0 | 0 | 6 |
| hooks/pretool-aggregate-check.py | 3 | 0 | 3 | 0 | 6 |
| scripts/blast-radius-tool.py | 6 | 0 | 0 | 0 | 6 |
| scripts/canary-verify.sh | 6 | 0 | 0 | 0 | 6 |
| scripts/dev-lifecycle.py | 1 | 0 | 5 | 0 | 6 |
| hooks/doc_sync/regen_readme.py | 5 | 0 | 0 | 0 | 5 |
| hooks/posttool-overnight-loop.py | 5 | 0 | 0 | 0 | 5 |
| hooks/posttool-subagent-track.py | 5 | 0 | 0 | 0 | 5 |
| hooks/pretool-claude-config-guard.py | 4 | 1 | 0 | 0 | 5 |
| hooks/pretool-do-block-subagents.py | 3 | 2 | 0 | 0 | 5 |
| hooks/pretool-obligation-gate.py | 4 | 0 | 1 | 0 | 5 |
| scripts/check-enforcement-evidence.py | 0 | 1 | 0 | 4 | 5 |
| scripts/spec-check.py | 4 | 0 | 1 | 0 | 5 |
| hooks/lib/checkpoint-core.sh | 1 | 3 | 0 | 0 | 4 |
| hooks/pretool-push-analyst-grant-guard.py | 1 | 1 | 2 | 0 | 3 |
| hooks/prompt-workflow.py | 1 | 3 | 0 | 0 | 4 |
| hooks/stop-spec-coverage-enforce.py | 2 | 0 | 2 | 0 | 4 |
| hooks/subagentstop-e2e-enforce.py | 4 | 0 | 0 | 0 | 4 |
| scripts/install/tmp-cleanup-install.sh | 0 | 4 | 0 | 0 | 4 |
| hooks/lib/commit_pipeline.py | 0 | 2 | 0 | 1 | 3 |
| hooks/lib/dev_report_shard_patterns.py | 2 | 0 | 0 | 1 | 3 |
| hooks/lib/interruption_signals.py | 0 | 2 | 1 | 0 | 3 |
| hooks/posttool-allowlist-consume.py | 3 | 0 | 0 | 0 | 3 |
| hooks/posttool-lane-completeness-watch.py | 3 | 0 | 0 | 0 | 3 |
| hooks/pretool-block-branch-pr-worktree.py | 0 | 3 | 0 | 0 | 3 |
| hooks/pretool-bulk-commit-detector.py | 3 | 0 | 0 | 0 | 3 |
| hooks/pretool-cp-state-write-guard.py | 2 | 1 | 0 | 0 | 3 |
| hooks/push.sh | 2 | 1 | 0 | 0 | 3 |
| hooks/stop-cleanup-allowlist.sh | 2 | 1 | 0 | 0 | 3 |
| hooks/userprompt-consent-allowlist.sh | 2 | 0 | 0 | 1 | 3 |
| scripts/close-commit-repair-orchestrate.py | 3 | 0 | 0 | 0 | 3 |
| scripts/lib/attribution_adjudicator.py | 0 | 0 | 3 | 0 | 3 |
| scripts/resolve-commit-repos.py | 1 | 0 | 2 | 0 | 3 |
| scripts/score-inject.sh | 3 | 0 | 0 | 0 | 3 |
| hooks/lib/git_clean_guard.py | 1 | 1 | 0 | 0 | 2 |
| hooks/merge.sh | 0 | 2 | 0 | 0 | 2 |
| hooks/pretool-grep-backtrack-guard.py | 0 | 2 | 0 | 0 | 2 |
| hooks/pretool-orchestrator-prompt-purity.py | 0 | 0 | 2 | 0 | 2 |
| hooks/pretool-write-guard.sh | 2 | 0 | 0 | 0 | 2 |
| hooks/session-git-init.sh | 0 | 1 | 1 | 0 | 2 |
| hooks/stop-completion-gate.py | 2 | 0 | 0 | 0 | 2 |
| hooks/stop-obligation-gate.py | 2 | 0 | 0 | 0 | 2 |
| scripts/check-overnight-reports.sh | 1 | 0 | 1 | 0 | 2 |
| scripts/checkpoint-prune.sh | 0 | 2 | 0 | 0 | 2 |
| scripts/close-report-append.py | 2 | 0 | 0 | 0 | 2 |
| scripts/close-scoring-decide.py | 1 | 0 | 1 | 0 | 2 |
| scripts/commit.sh | 1 | 0 | 1 | 0 | 2 |
| scripts/create-overnight-state.sh | 0 | 2 | 0 | 0 | 2 |
| scripts/derive-default-branch.sh | 1 | 1 | 0 | 0 | 2 |
| scripts/lint-spec-id-centralization.py | 2 | 0 | 0 | 0 | 2 |
| scripts/repair-venv.sh | 1 | 0 | 1 | 0 | 2 |
| scripts/verify-claims-extended.sh | 0 | 0 | 0 | 2 | 2 |
| hooks/auto-commit.sh | 0 | 1 | 0 | 0 | 1 |
| hooks/doc_sync/hook_ledger.py | 1 | 0 | 0 | 0 | 1 |
| hooks/doc_sync/ledger_contract.py | 1 | 0 | 0 | 0 | 1 |
| hooks/git-fswatch.sh | 0 | 1 | 0 | 0 | 1 |
| hooks/lib/bash_active_syntax_census.py | 1 | 0 | 0 | 0 | 1 |
| hooks/lib/bash_execution_boundary.py | 1 | 0 | 0 | 0 | 1 |
| hooks/lib/close-verdict.py | 1 | 0 | 0 | 0 | 1 |
| hooks/notification-idle-overnight.py | 0 | 0 | 1 | 0 | 1 |
| hooks/posttool-push-gate-token-verify.py | 1 | 0 | 0 | 0 | 1 |
| hooks/pretool-baseline-snapshot-preflight.py | 1 | 0 | 0 | 0 | 1 |
| hooks/pretool-subagent-code-block.py | 0 | 1 | 0 | 0 | 1 |
| hooks/pretool-wrapper-userintent.py | 1 | 0 | 0 | 0 | 1 |
| hooks/session-info.sh | 1 | 0 | 0 | 0 | 1 |
| hooks/session-scratch-init.sh | 1 | 0 | 0 | 0 | 1 |
| hooks/session-tmpfs-banner.sh | 1 | 0 | 0 | 0 | 1 |
| hooks/sessionend-scratch-sweep.sh | 1 | 0 | 0 | 0 | 1 |
| hooks/stop-do-report-gate.py | 1 | 0 | 0 | 0 | 1 |
| hooks/stop-overnight-timelock.py | 0 | 0 | 1 | 0 | 1 |
| hooks/stop-workflow-coordinator.py | 1 | 0 | 0 | 0 | 1 |
| hooks/userprompt-tmpfs-pressure.sh | 1 | 0 | 0 | 0 | 1 |
| scripts/capture-hero-run.py | 1 | 0 | 0 | 0 | 1 |
| scripts/check-late-repair-provenance.py | 0 | 0 | 1 | 0 | 1 |
| scripts/check-security-hook-drift.sh | 1 | 0 | 0 | 0 | 1 |
| scripts/close-route-select.py | 1 | 0 | 0 | 0 | 1 |
| scripts/create-worktree.sh | 1 | 0 | 0 | 0 | 1 |
| scripts/graphify-enrich.py | 1 | 0 | 0 | 0 | 1 |
| scripts/install-checkpoint-refspec.sh | 0 | 1 | 0 | 0 | 1 |
| scripts/late-repair-controller.py | 0 | 0 | 1 | 0 | 1 |
| scripts/lib/dispatch_metadata.py | 0 | 0 | 1 | 0 | 1 |
| scripts/lib/soundness_gate.py | 0 | 0 | 1 | 0 | 1 |
| scripts/lifecycle-baseline-import.sh | 1 | 0 | 0 | 0 | 1 |
| scripts/overnight-init.sh | 0 | 1 | 0 | 0 | 1 |
| scripts/qa-manifest-guard.py | 0 | 0 | 1 | 0 | 1 |
| scripts/qa-report-stale-iter-lint.py | 1 | 0 | 0 | 0 | 1 |
| scripts/resolve-spec-artifacts.py | 0 | 1 | 0 | 0 | 1 |
| scripts/step7-spec-update.py | 1 | 0 | 0 | 0 | 1 |

### E3.d The biggest removable sections (relocation or deletion; no feature retired)

| # | section | file:line | lines | what is wrong | minimal fix |
|---|---|---|---|---|---|
| 1 | Codex consultation block, 12 copies | agents/architect.md:418-474, ba.md:1375-1443, cleanliness-inspector.md:390-445, dev.md:944-1003, pm.md:1072-1133, product-owner.md:434-490, prompt-inspector.md:255-310, qa.md:1317-1377, spec.md:741-801, style-inspector.md:685-740, ui-specialist.md:292-346, user.md:540-596 | 707 | opt-in (`--codex`) text loaded on every dispatch | one include file read only when the dispatch says `codex_required: true`; each agent keeps a 1-line pointer |
| 2 | Checkpoint Marking Contract, 17 copies | agents/architect.md:398-417, ba.md:1335-1374, cleaner.md:172-195, cleanliness-inspector.md:365-389, dev.md:1054-1085, git-edge-case-analyst.md:253-276, pm.md:1052-1071, product-owner.md:414-433, prompt-inspector.md:230-254, qa.md:1931-1962, rule-inspector.md:186-209, spec.md:802-824, style-inspector.md:660-684, test-executor.md:401-424, test-validator.md:327-350, ui-specialist.md:281-291, user.md:520-539 | 413 | /spec cp-state text loaded on every dispatch, spec or not | one include read only when SPEC_ID is set |
| 3 | Requirement Baseline and Scope Authority charter, 18 copies (+5 variant headings, 23 per wf2) | agents/ba.md:8-21, changelog-analyst.md:6-11, cleaner.md:6-11, cleanliness-inspector.md:6-11, git-edge-case-analyst.md:6-11, graphify.md:6-11, merge-analyst.md:6-11, pm.md:11-16, prompt-inspector.md:6-11, pull-analyst.md:6-11, push-analyst.md:6-11, rule-inspector.md:6-11, spec.md:6-11, style-inspector.md:6-11, test-executor.md:6-11, test-validator.md:6-11, test-writer.md:6-11, ui-specialist.md:6-11 | 116 | wording drift between copies | 2 identical inline lines |
| 4 | Anti-Give-Up discipline, 6 copies | agents/architect.md:14-42, pm.md:74-102, product-owner.md:14-42, qa.md:28-56, ui-specialist.md:23-51, user.md:14-42 | 174 | identical copies | one include |
| 5 | Overnight Spec Integration, 4 copies | agents/ba.md:1480-1507, dev.md:1019-1053, pm.md:1016-1051, qa.md:1886-1930 | 144 | overnight-only text on every dispatch | one include read only in overnight mode |
| 6 | Specialist Findings Intake, 2 copies | agents/ba.md:1205-1251, pm.md:1134-1190 | 104 | duplicate | one include |
| 7 | Tutorial sections of /dev (JSON Storage Policy, Integration with /clean, Quality Standards, Agent Development Use Cases, …) | commands/dev.md:1460-1698 | 239 | tutorials, not orchestration; loaded twice per /dev today (E3.a) | delete |
| 8 | "Orchestrator Prompt Purity (MANDATORY)" | commands/dev.md:1699-1750 | 52 | claims the hook "exits with code 2" (:1747) and cites a gitignored /root/docs/dev self-test (:1749); hooks/pretool-orchestrator-prompt-purity.py:21-24 is warn-only, exit 0 (D4) | replace with the 3-line WHAT-not-HOW rule |
| 9 | Inline QA dispatch template | commands/close.md:601-789 | 189 | overlaps agents/qa.md | move into qa.md's close-debate part (later QA mode split) |
| 10 | Test-only trace contract | commands/commit.md:866-911 | 46 | stderr trace contract (`COMMIT_STEP7_TRACE`) consumed only by scripts/step7-spec-update.py | move to that script's docstring |
| 11 | Shell function library that assumes persistent shell state | commands/close.md:146-280 | 135 | the Bash tool does not keep state between calls (dev-overnight.md:245-247 says so) | later: move into a script (L) |
| 12 | Repository plan / grant procedure | commands/commit.md:244-475 | 232 | plumbing in prose | later: script (L) |
| 13 | Git transaction procedures | agents/changelog-analyst.md:1508-1802, :1803-1948 | 441 | push-gate reconciliation + precommitted recovery in prose | later: scripts (L) |
| 14 | Spec / context templates | agents/ba.md:813-1193 | 381 | templates inline | move to templates/ (M) |
| 15 | Root/state resolution | commands/dev-overnight.md:193-363 | 171 | plumbing | later: script (L) |
| 16 | Four Contracts, orchestrator copies | commands/dev.md:326-421, dev-overnight.md:398-459, dev-command.md:265-320 | ~206 | 3 copies | keep one (agents/ba.md) (M) |
| 17 | Test plan schema inline | agents/pm.md:376-517 | 142 | inline JSON | schema file (M) |
| 18 | dev-command.md as a drifted fork of dev.md | commands/dev-command.md (1,176 lines; ~497 shared with dev.md, wf2) | ~497 | fork drift | blocked: /dev-command is a held feature; dedupe later |

Rows 1-8 and 10 (1,995 lines; after keeping one copy of each include, about 1,780 lines leave the always-loaded prompts, ~7% of the 25,588 lines of commands/agents/CLAUDE.md) are the minimal set: relocations and deletions with no behaviour change.
Rows 9 and 11-18 are the larger structural diet (wf2 Phases 3-4) and are not needed for the producer architecture now.

### E3.e Context injected by hooks (not counted in the prompt files)

UserPromptSubmit stdout goes into context on every prompt: hooks/prompt-workflow.py (E3.a; phase B also prints todo progress and the
overnight continuation, :1229-1262), hooks/userprompt-doc-sync-check.py (notices, cap 10,000 chars at :25),
userprompt-restart-authorize.py, userprompt-consent-allowlist.sh, userprompt-tmpfs-pressure.sh, userprompt-bulk-commit-capability.py,
userprompt-usage-snapshot.py (additionalContext). SessionStart (8 hooks, settings.json SessionStart) and PostToolUse
`additionalContext` emitters (hooks/doc_sync/notice.py:320-324,492; hooks/userprompt-usage-snapshot.py) add more. No budget covers
hook output (X90). Only E3.a is a measured duplicate; the rest is listed for completeness.

### E3.f CLAUDE.md (user-owned; loaded into every context)

Section sizes (characters): Production Lessons 2,264; Subagent Hook Discipline 3,025 (incl. the sentinel-grant mechanism);
Orchestrator-Only Rule 1,935; No branch/PR/worktree 1,125; others < 640 each; total 11,106 B. About 43% describes hook internals
(X56), and lines :57, :102, :117, :125 contradict the hooks (D4). CLAUDE.md is the user's own instruction file: no change is proposed
here except that doc-sync stops rewriting its line 4 (E2.a step 3). Trimming it is a user decision (U-E3b).

### E3 fix (minimal, ordered)

1. E3.a: delete hooks/prompt-workflow.py:1278-1280. S, low risk. Largest single saving (~57k tokens per /dev+/close).
2. Stamps: remove the stamps in the 31 prompt files listed in E3.c (keep the 20 binding-design citations). Prevent regrowth at the
   producer: the existing PreToolUse Write|Edit hook that already inspects edits of `.claude/commands/` (hooks/pretool-claude-config-guard.py)
   gains one stateless check: refuse a `new_string`/`content` that adds a task-id or dated-note stamp to `commands/*.md`,
   `agents/*.md`, `CLAUDE.md`. No state file. Code-comment stamps (608 lines / 110 files) are left; the ones that point at docs deleted
   by E4 are trimmed in that change.
3. Extract rows 1-6 of E3.d into 6 include files in a directory Claude Code does not load (`templates/prompt-includes/`), each read only
   when its condition holds; delete rows 7-8 and move row 10. M, low-medium risk; the prose-pinning tests that assert those exact
   phrases must be updated in the same change (U-E1e, C4).
4. Rows 9, 11-18: later (wf2 Phases 3-4), not required now.

---

## E4 — dated incident records and the 697 KB backlog

### E4.0 Root cause

The "record, don't fix" rule (docs/reference/harness-issues-backlog.md:27: harness fixes run serially; newly found problems are
recorded here for the next /spec) and the habit of writing a dated doc per incident (F4). Nothing deletes a record once the fix lands
or the cycle ends, so docs/reference grew to 64 files and the backlog to 697,229 B.

### E4.a Every dated doc (37) and every undated incident/plan record (14), with a verdict

Verdicts:
- KEEP-BINDING: the user's binding architecture.
- RATIONALE: live code or a live prompt defers its "why" to this doc. Inline the rationale (<=15 lines) into that code, then delete.
- EVIDENCE-UNTIL: evidence for a still-open fix. Delete when that fix lands.
- OPEN: open defect. The named cluster owns it; delete when its fix lands. No new issue list is created.
- PRIVATE: machine- or person-specific notes; move out of the published repo.
- PRODUCT: product or ops decision (U-E1c, U-E1d).
- HISTORY: no live reader. Git keeps it. Delete in the E1 change and trim the citing comments.

| verdict | files | bytes |
|---|---|---|
| KEEP-BINDING | 1 | 51957 |
| RATIONALE | 3 | 56829 |
| EVIDENCE-UNTIL | 2 | 49221 |
| OPEN | 8 | 51763 |
| PRIVATE | 2 | 135394 |
| PRODUCT | 5 | 128716 |
| HISTORY | 30 | 508627 |

| verdict | file | lines | bytes | live citations (excluding INDEX/README) | note |
|---|---|---|---|---|---|
| KEEP-BINDING | docs/reference/close-commit-zero-failure-mechanism-20260928.md | 639 | 51957 | hooks/lib/obligation.py:5; hooks/pretool-obligation-gate.py:78 (GRAMMAR_DOC_REF); commands/dev.md x7, dev-command.md x6, dev-overnight.md x6, close.md:551; 31 refs | the user's binding architecture (§0-§1, §4); keep; its dated name is cited 31 times, so do not rename |
| RATIONALE | docs/reference/attribution-journal-phase0-facility.md | 140 | 8138 | hooks/lib/attribution_journal.py:51,57; hooks/posttool-attribution-post.py:9; scripts/seal-attribution-journal.py:14; hooks/tests/test_attribution_journal.py:508 | rulings #1/#3 of a live mechanism; merge <=15 lines into attribution_journal.py docstring, then delete |
| RATIONALE | docs/reference/core-context-refactor-plan.md | 449 | 34919 | hooks/pretool-bash-safety.sh:232 ("authoritative, detailed record"); hooks/lib/runtime_guard/context.py:10,76 ("Do not restate"); _core.py:324; hooks/tests/test_fail_closed_drift.py:38 | live security hook defers its residual-gap list here; inline the residual-gap list (<=15 lines) into pretool-bash-safety.sh, then delete |
| RATIONALE | docs/reference/push-gate-reconciliation-decision.md | 227 | 13772 | hooks/posttool-push-gate-token-verify.py:18 | the only "why" of a live hook; manifest: merge a <=10-line verdict into that hook docstring, then delete |
| EVIDENCE-UNTIL | docs/reference/close-commit-failure-inventory-20260927.md | 654 | 42974 | close-commit-zero-failure-mechanism-20260928.md:6 (design driver); dead scripts/generate-repair-map.py:37 | 474-failure evidence base of the binding design; delete when A2 cutover (S10-S12) lands |
| EVIDENCE-UNTIL | docs/reference/subagentstop-payload-s0-measurement-20260929.md | 92 | 6247 | dated docs only | measured SubagentStop payload fields (incl. agent_type in logs) = input to A4; delete when A4 lands |
| OPEN | docs/reference/bash-write-targets-capability-gap-20261005.md | 35 | 4887 | none (backlog line 258 duplicates it) | fail-open/fail-shut pair in hooks/lib/bash_write_targets.py; owner: hook-architecture |
| OPEN | docs/reference/commit-gate-bypass-via-background-exec-20261005.md | 73 | 3997 | harness-gaps-found-20261005.md:13 | security gap (commit gate bypassed by backgrounding); owner: B/hook-architecture |
| OPEN | docs/reference/do-report-ledger-has-no-refresh-path-20261008.md | 112 | 7477 | none | /do report ledger cannot refresh; owner: B4 |
| OPEN | docs/reference/harness-gaps-found-20261005.md | 141 | 7363 | none | 5 gaps (commit-gate bypass, charter -F example, bulk attribution, deleted checker, contradictory disclosure lines); owners: B/D4 |
| OPEN | docs/reference/merge-pipeline-blocked-steps-20261007.md | 185 | 12658 | do-report-ledger doc:110 | /merge Step 3 grant consumption uses forbidden rm; 60 s TTL; owner: D4/B |
| OPEN | docs/reference/open-findings-from-read-only-cycles-20261005.md | 65 | 3369 | none | spec defects + workspace verdicts; owner: D4 |
| OPEN | docs/reference/qa-status-gate-gap-orchestrator-side-20261005.md | 117 | 6591 | none | orchestrator can self-serve the QA verdict = A4 producer identity; owner: A4 |
| OPEN | docs/reference/workflow-bookmark-orphans-20261005.md | 31 | 5421 | none | 22/22 workflow bookmarks orphaned, no reclaimer; owner: E2.b step 4 (the registered SessionEnd hook removes its own session bookmark) |
| PRIVATE | docs/reference/paseo-daemon-teachings-20260910.md | 721 | 130510 | .claude/scratch_write_report.py:158 (stray) | 721 lines / 130 KB of operator lessons; 18 private-path lines; not referenced by commands/paseo-daemon.md; user decides keep (private notes) vs move out |
| PRIVATE | docs/reference/tmpfs-persistent-backups-20261005.md | 46 | 4884 | none | machine-specific backup locations (/var/backups/..., /dev/sda1); move to private notes |
| PRODUCT | docs/reference/launch-plan.md | 720 | 67921 | rename-execution-plan.md only | marketing plan; product decision |
| PRODUCT | docs/reference/positioning.md | 281 | 20712 | none | product decision |
| PRODUCT | docs/reference/rename-execution-plan.md | 296 | 18840 | none | never-executed rename; README.md:1/NOTICE already use the new name; pick ONE name |
| PRODUCT | docs/reference/roadmap-decomposition-productization.md | 304 | 18690 | PUBLIC-CORE.md:10; scripts/check-public-core.sh:6; residue allowlist | "plan (not executed)"; product decision |
| PRODUCT | docs/reference/venv-repair.md | 51 | 2553 | none | runbook of scripts/repair-venv.sh; decided together with it (U-E1d) |
| HISTORY | docs/reference/MORNING-20260907.md | 534 | 31951 | none (one dated doc mentions it) | one-day operator handoff; 16 private-path lines (C3) |
| HISTORY | docs/reference/abandoned-cycles-20260905.md | 422 | 26165 | dated docs only | cycle bookkeeping |
| HISTORY | docs/reference/attribution-journal-consumer-cutover-20261004.md | 73 | 5703 | scripts/lib/attribution_adjudicator.py:5 (provenance comment) | "APPLIED" status record |
| HISTORY | docs/reference/attribution-journal-cutover-flip-plan-20261003.md | 128 | 10769 | comments: attribution_adjudicator.py:4, resolve-commit-repos.py:532, dispatch_metadata.py:16 (dead), tests/test_changelog_analyst_declaration_categories.py:161 (dead) | superseded plan; the input contract is restated in code |
| HISTORY | docs/reference/bash-safety-verb-anchoring-20261008.md | 249 | 12264 | hooks/pretool-bash-safety.sh:58,1171,1251 ("Full record") | rationale already restated inline at pretool-bash-safety.sh:50-57; drop the pointer lines |
| HISTORY | docs/reference/claim-verification-methodology-20260925.md | 90 | 14885 | dated docs only | session working method |
| HISTORY | docs/reference/codex-sandbox-verification.md | 205 | 11867 | none | one-off verification report (dev-20260719-150041-b) |
| HISTORY | docs/reference/commit-dryrun-close-gate-ruling.md | 25 | 2382 | commands/commit.md:235 | its own :3 says the normative rule lives in commit.md |
| HISTORY | docs/reference/controller-error-taxonomy-20260924.md | 178 | 44754 | dated docs only | controller retrospective; 44.7 KB |
| HISTORY | docs/reference/dev-command-20261003-020648-takeover-record.md | 174 | 10469 | none | single-cycle record |
| HISTORY | docs/reference/harness-defects-20260906-controller.md | 671 | 32569 | dated docs only; backlog:21 | dated defect log; 15 private-path lines (C3) |
| HISTORY | docs/reference/harness-fix-status-20260905.md | 724 | 45619 | backlog:259 only | status of a finished spec |
| HISTORY | docs/reference/infeasibility-without-execution-20261006.md | 23 | 3769 | dated docs only | one-sentence principle; if wanted, one line in the agent charter |
| HISTORY | docs/reference/lane-pol-catchup-plan-20260808-035658-lanepolcatchup.md | 264 | 14104 | none | branch-specific plan; branch reconciled |
| HISTORY | docs/reference/master-origin-reconciliation-gap-20261005.md | 61 | 11698 | dated docs only | obsolete: master == origin/master after 09ab15b |
| HISTORY | docs/reference/monolith-split-plan.md | 267 | 27313 | 20 provenance comment lines in hooks/lib/runtime_guard/ (_core.py:36,85,137,177,184,224,263,292 + 12 lines in 7 modules); 2 residue-allowlist rows; 2 companion plans | executed plan; trim the comments to nothing |
| HISTORY | docs/reference/overnight-cycle-20260809-013317-shared-file-attribution-20260914.md | 536 | 32142 | none | single-cycle forensic record |
| HISTORY | docs/reference/overnight-worktree-20260810-test-gaps-20261005.md | 88 | 12360 | backlog:257 only | abandoned-worktree diagnosis (the E1 abandoned-cycle files) |
| HISTORY | docs/reference/overnight-worktree-test-gaps-20261005.md | 40 | 5214 | none | abandoned-worktree diagnosis |
| HISTORY | docs/reference/overwrite-prohibition.md | 359 | 25900 | unregistered hooks/pretool-overwrite-guard.py:23 + its tests | goes with the dead guard (E1) |
| HISTORY | docs/reference/paseo-daemon-caller-id-rollout-20261004.md | 51 | 2379 | none | rollout record |
| HISTORY | docs/reference/paseo-daemon-concurrent-staging-triple-repro-20260904-181435-20260914.md | 247 | 14671 | none | incident repro |
| HISTORY | docs/reference/paseo-daemon-shared-file-attribution-20260913.md | 484 | 29469 | dated docs only | forensic record |
| HISTORY | docs/reference/quarantine-record-dev-20260915-020044.md | 127 | 8447 | .claude/quarantined-*/QUARANTINE-NOTE.md:10 (also junk) | goes with the quarantine dir |
| HISTORY | docs/reference/recoverable-discard-register-20261005.md | 119 | 8641 | none | register of 4 trivial scratch files |
| HISTORY | docs/reference/restart-detector-quota-text-match-false-positive-20260915.md | 486 | 26748 | commands/restart.md:81; hooks/lib/interruption_signals.py:65; hooks/lib/subagent_restart.py:111; tests/test_restart_command.py:979 | the rule is restated at commands/restart.md:76-82 and subagent_restart.py:111; this is the 217-record evidence dump |
| HISTORY | docs/reference/slashcommand-quick-reference.md | 232 | 8633 | none | 23 of 31 commands it lists do not exist |
| HISTORY | docs/reference/test-suite-overhaul-plan.md | 229 | 17366 | conftest.py:3, pytest.ini:8, tests/TESTING.md:5 | executed plan |
| HISTORY | docs/reference/workspace-disposition-criteria-20261005.md | 52 | 3320 | dated docs only | campaign criteria |
| HISTORY | docs/reference/worktree-685c203b-remaining-18-disposition-20261005.md | 66 | 7056 | none | one worktree disposition |

Citing comments to trim when the HISTORY docs go (same change): hooks/lib/runtime_guard/_core.py:36,85,137,177,184,224,263,292, anchor.py:7,28, config.py:6,27, constants.py:7,
find_cmds.py:6,26, git_cmds.py:5,26, pathmatch.py:5,24, shell_lex.py:5 (monolith-split-plan; 20 lines);
conftest.py:3, pytest.ini:8, tests/TESTING.md:5 (test-suite-overhaul-plan); hooks/pretool-bash-safety.sh:58,1171,1251
(bash-safety-verb-anchoring); commands/restart.md:81, hooks/lib/interruption_signals.py:65, hooks/lib/subagent_restart.py:111,
tests/test_restart_command.py:979 (restart-detector corpus); scripts/lib/attribution_adjudicator.py:4-5, scripts/resolve-commit-repos.py:532
(attribution cutover docs); commands/commit.md:235 (commit-dryrun ruling); policies/public-core-residue-allowlist.v1.json rows for deleted
docs (C3 ledger).

Open-defect docs and their owners (no new issue list; each doc is deleted by the change that fixes it):
qa-status-gate-gap-orchestrator-side-20261005.md → A4 (producer identity: the orchestrator can self-serve the QA verdict);
do-report-ledger-has-no-refresh-path-20261008.md → B4; merge-pipeline-blocked-steps-20261007.md → B/D4;
commit-gate-bypass-via-background-exec-20261005.md and harness-gaps-found-20261005.md → B/D4; bash-write-targets-capability-gap-20261005.md
→ hook-architecture (D3 lexers); open-findings-from-read-only-cycles-20261005.md → D4; workflow-bookmark-orphans-20261005.md → E2.b step 4.

### E4.b The backlog

| fact | location |
|---|---|
| 697,229 B, 262 lines, longest line 22,351 chars (est. 175k-230k tokens, mostly CJK text; exceeds a single Read) | docs/reference/harness-issues-backlog.md |
| 158 `- **` items, 74 of them numbered `#N`; 12 commits | same |
| moved in verbatim from one account's private memory dir; frontmatter kept as "provenance" (:1-9), private paths (:13) | :1-22 |
| the record-only rule: "harness 修复串行进行；期间新发现的问题记在这里，等下一次 /spec 统一处理" (fixes run serially; new problems are only recorded here) | :27 (also :3 description) |
| mandatory read for every fix-class BA: "Read the harness issues backlog (docs/reference/harness-issues-backlog.md)" | agents/ba.md:18 (and the History-evidence field at agents/ba.md:917) |
| the same relative path does not exist in a product repo, so the instruction is harness-only but sits in a general agent | agents/ba.md:18 |
| other readers: comments only (hooks/pretool-baseline-snapshot-preflight.py:52 (dead), hooks/pretool-do-block-subagents.py:15,135) and dated docs | — |

Fix (producer-side: the BA prompt is the producer of the "history evidence" field; effort S):
1. agents/ba.md:18: replace "Read the harness issues backlog" with "search (grep) docs/reference/harness-issues-backlog.md for the
   affected mechanism's file and hook names, when that file exists; cite matches". Same evidence, a few KB instead of 697 KB, and it
   degrades cleanly in product repos.
2. The backlog's own fate and the record-only rule at :27 are F4 decisions (U-E4a): keep as an archive that agents grep (recommended
   under the hold), or triage into a short open list. No new file either way.

### E4 fix (minimal, ordered)

1. In the E1 deletion change: delete the 30 HISTORY docs (508,627 B) and trim the citing comments above; move the 2 PRIVATE docs
   (paseo-daemon-teachings-20260910.md, tmpfs-persistent-backups-20261005.md) out of the published repo (user's private notes, U-E4b).
2. Inline the 3 RATIONALE docs into the code that cites them, then delete them: core-context-refactor-plan.md → residual-gap list in the
   hooks/pretool-bash-safety.sh header (:228-236); push-gate-reconciliation-decision.md → hooks/posttool-push-gate-token-verify.py
   docstring (:18); attribution-journal-phase0-facility.md → hooks/lib/attribution_journal.py docstring (:51-57).
3. Keep close-commit-zero-failure-mechanism-20260928.md (binding; 31 citations, so no rename) and the 2 EVIDENCE-UNTIL docs until A2/A4.
4. agents/ba.md:18 → targeted grep (E4.b).

---

## User decisions (minimal set)

| id | question | recommended |
|---|---|---|
| U-E1a | Abandoned-cycle code (I5/I6) is not a held feature? (= D cluster U3) | yes, delete |
| U-E1b | Retire the per-folder INDEX/README convention (50 G stubs here, 85 tracked)? | not now (hold); E2.a stops growth |
| U-E1c | Product docs (launch-plan, positioning, rename plan, roadmap) and ONE product name | user's call |
| U-E1d | scripts/repair-venv.sh + venv-repair.md: keep as ops tool or delete | user's call |
| U-E1e | May prose-pinning tests be replaced/removed (needed by E3.c)? (= C4/X52) | yes |
| U-E1f | schemas/graphify-prequery.v1.json: validate at producer or delete | validate (consistent with producer architecture) |
| U-E2a | May the harness append its runtime patterns to `.git/info/exclude` of product repos? | yes |
| U-E3b | Trim CLAUDE.md (user-owned; ~43% hook internals, 4 contradictions)? | user's call; nothing here edits it |
| U-E4a | Backlog: archive that agents grep, or triage into a short list; keep or lift the record-only rule (F4) | archive + grep now |
| U-E4b | Move paseo-daemon-teachings and tmpfs-persistent-backups out of the published repo | yes |

## Dependencies and order

1. E2.a (doc-sync update-only) first: otherwise E1's deleted stubs come back.
2. E1 deletion change (with E4 step 1-2 and the companion edits). It also removes C4's collection breaker.
3. E2.b (info/exclude re-scope) any time; it immediately cleans A3's untracked-file input in every repo.
4. E3.a any time (3 lines).
5. E3.c after U-E1e (prose-pinning tests).

## Cross-references

- A1: the advisory JSONL sinks in E2.c are A1's advisory branch; flipping the switches removes them.
- A3: E2.b removes runtime files from `git status`, the source of `files_created`; doc-sync's hook_ledger exists only for A3 accounting.
- A4: qa-status-gate-gap doc; subagentstop-payload-s0 measurement doc (EVIDENCE-UNTIL).
- B2: scripts/commit.sh, scripts/update-overnight-state.sh, scripts/mint-git-blessed-token.sh stay (F).
- B4: do-report-ledger doc.
- C1: todo-path sites ignore CLAUDE_CONFIG_DIR (E2.c).
- C3: private paths in MORNING/harness-defects/paseo-teachings/backlog; push.sh.
- C4: tests/test_tool_policy_inference_note.py (E1 I6) is the collection breaker; prose-pinning tests (E3.c).
- D1: reachability of hooks/scripts (D-orphans-dangling.md D1.a/D1.b) agrees with E1 I3/I5; D1.c doc-sync; D1.d checkpoint push.
- D4: dev.md:1747 "exit 2" claim, CLAUDE.md contradictions.
- F1: why junk lands and why the deletion must be a human-merged PR.
- F2: size budget (E3) belongs there; E3 step 2 adds only the stamp check.
- F4: record-only rule (E4.b).

