# P14: bash-safety slimmed down to one shared parser

**Base:** master 1ace5ee4. **Status:** plan only; no code changed. The reviewer reviews it and starts the lanes.

**Owner direction (2026-11-11):**
- no Claude Code sandbox;
- one shared parser;
- delete what is dead;
- use GitHub where it fits;
- no history comments;
- no hardcode explosion.

**Evidence.** Every fact below was measured on 1ace5ee4, in a throwaway HOME with an empty `GIT_CONFIG_GLOBAL`. The full per-rule inventories, with line ranges, examples, pins and the experiments behind each class, are in `P14-inventory/`:

| File | Covers |
|---|---|
| `bash-safety.md` | `hooks/pretool-bash-safety.sh` (BS-01 to BS-45) |
| `git-guard.md` | `pretool-git-privilege-guard.py` (GP), `lib/git_command_classifier.py` (GC), `lib/git_clean_guard.py` (GCL) |
| `tool-policy.md` | `pretool-tool-policy.py` (TP), the Bash path of `pretool-overnight-hook-guard.py` (OG), `lib/bash_write_targets.py` (WT) |
| `parsers.md` | every Bash reader, the `$'…'` experiment, the corpus, the parser API |
| `suites-edges.md` | the suite baseline and the gate edge cases |

The corpus extractor is `tools/p14/extract_corpus.py`, and the replay decision dump is `tools/p14/dump_replay_decisions.py`.

## 0. Corrections to the brief

**Readers that parse no Bash tool command.** `hooks/stop-command-gate.py`, `hooks/userprompt-usage-snapshot.py` and `hooks/userprompt-consent-allowlist.sh` do not read a Bash tool command:
- they `shlex.split` slash-command arguments, an env override, or the `/allow` argument;
- the one exception is `stop-command-gate.close_stalled`, which checks Bash commands by substring.

They stay out of the parser work. Their edge cases are in section 7.

**Readers the brief did not list.** Four private Bash readers also exist and join the plan:
- `hooks/lib/runtime_guard/shell_lex.py` (237 lines, used by `runtime_guard/_core.py`);
- `hooks/lib/allowlist.py:_bash_subcommands` (grant matching);
- `hooks/lib/grepguard_context_strip.py` (231);
- `hooks/pretool-block-branch-pr-worktree.py`, which uses `bash_context_strip`.

**Where the #14 over-blocks come from.**
- **`git -c x=y commit -m "fix(session-recovery)"`.** This is not refused by the git guard. It is bash-safety's hard-ban rule BS-19 (`pretool-bash-safety.sh:1644-1681`). Its quote masker gives up when the text contains `-\w*[ce]\w*` (`:1671`), so `git -c` unmasks the message, and `(` counts as a command start.
- **`mv file ~`.** This comes from the runtime guard (`runtime_guard/_core.py:_step0_mutation_anchor_hits`, `:1319`, through `pathmatch.py:269`). It protects every ancestor of `~/.config/claude/protected-runtime.json` up to a stop root, and `$HOME` is not a stop root. A destination directory is read as the mutated entry.
- **The issue itself is not in the tree.** No copy of issue #14 or of comment 6905496433 exists in the tree or in its history. This plan works from the brief's list.

## 1. Inventory of the refusal rules in the Bash path

Classes:
- **KEEP**: stays, re-expressed on the shared parser.
- **MERGE**: a duplicate of a rule in another hook or in `settings.json` deny, which stays.
- **GITHUB**: replaced by a GitHub ruleset.
- **DEAD**: unreachable, superseded, or protects nothing (evidence in the inventory row).

### 1.1 Counts

| File | Rules | KEEP | MERGE | GITHUB | DEAD |
|---|---|---|---|---|---|
| `pretool-bash-safety.sh` | 45 | 33 | 10 | 1 | 1 |
| `pretool-git-privilege-guard.py` | 30 | 21 | 3 | 1 | 5 |
| `lib/git_command_classifier.py` | 11 | 11 | 0 | 0 | 0 |
| `lib/git_clean_guard.py` | 8 | 8 | 0 | 0 | 0 |
| `pretool-tool-policy.py` (Bash path) | 18 | 17 | 0 | 0 | 1 |
| `pretool-overnight-hook-guard.py` (Bash path) | 25 | 19 | 5 | 0 | 1 |
| `pretool-block-branch-pr-worktree.py` | 8 | 1 | 0 | 0 | 0 (7 DELETE, owner decision) |
| **Total** | **145** | **110** | **18** | **2** | **8**, plus **7 DELETE** |

The 109 KEEP rules collapse further:
- bash-safety pairs fold into one rule each: BS-20+21, BS-29+35, BS-36+37, BS-38+39;
- BS-13 dies with BS-09;
- GP-22 exists only because two readers disagree, so it disappears with one parser.

Each KEEP rule becomes one predicate over the parse.

`bash_write_targets.py` holds no rules but 9 extraction capabilities (WT-01 to WT-09). Eight move into the shared parser. The ninth, the FROZEN extractor at `:803`, is superseded by the write-mode extractor's coverage. Its `mode`/`mechanism` labels have no production reader.

GP-09 (refuse every agent push without a `/push` grant) was proposed as GITHUB and is kept local here. GitHub judges the credential, not who typed the command. On the owner's machine the agent pushes with the owner's key, so GitHub cannot tell an agent push from the owner's.

### 1.2 MERGE (18)

| Rule | What it refuses | Survivor |
|---|---|---|
| BS-09, BS-10 | Daemon prefix restart (inert unless `CLAUDE_PROTECTED_DAEMON_PREFIX` is set; nothing in the repo writes its grant flag) | `runtime_guard` `protected_services` + P0 anchor scan |
| BS-12 | HTTP `localhost:<port>/stop` | `runtime_guard` P5 `protected_endpoint_paths` (tested there) |
| BS-34 | `npm i -g` | `runtime_guard` global-install (refuses 10 of 11 forms first; P14-3 closes the `bash -c` gap) |
| BS-18 | `session_dirs.txt` | `settings.json` `permissions.deny` (already present) |
| BS-22 | `systemctl … docker` | BS-30 (already refuses it; BS-22 misses `reload`) |
| BS-40 | `git reset --hard` | GP-05 |
| BS-42 | `update-ref`, `branch -D/-f/-m`, `symbolic-ref` | GP-06 (the same predicate, byte for byte) |
| BS-44 | Subagent `revert`/`cherry-pick`/`rebase` | GP-04 (refuses it for every agent; the in-file "NOT covered there" comment is stale) |
| BS-45 | `git revert <hash>` | GP-04 (broader) |
| GP-04 (part), GP-05, GP-06 | The other side of the four pairs above | They stay in GP; bash-safety's copies go |
| OG-01, OG-02 | `.claude/hooks/`, `.claude/commands/` writes | `pretool-claude-config-guard.py` (same regex list, always on, the same verdicts measured) |
| OG-19, OG-20, OG-21 | Branch force, update-ref/symbolic-ref, push of the protected branch | GP (rc=2 measured on each) |

The GP-04/05/06 row is counted once, as the pair. The MERGE total is 10 in bash-safety, 3 in GP and 5 in OG.

### 1.3 GITHUB (2)

| Rule | What it refuses | Replaced by |
|---|---|---|
| BS-41 | `git push --force/-f/--force-with-lease/--delete/-d/--mirror/+ref/:ref` | Section 3, rulesets R1 and R2. It is also a GP-08 duplicate. |
| GP-08 | Force or delete pushes | Section 3, rulesets R1, R2 and R3. Owner decision Q1. |

### 1.4 DEAD (8)

| Rule | Evidence |
|---|---|
| BS-11 `bash /tmp/*.sh` | It stops only one spelling: `sh -x /tmp/x.sh`, `/tmp/x.sh` and `bash ./x.sh` all pass. It refuses the Claude Code scratchpad. Its daemon purpose is inert. |
| GP-07 | It refuses the literal `CLAUDE_PUSH_COMMAND_ACTIVE=`. An inline assignment never reaches the hook's environment, and GP-09 refuses the same command anyway. |
| GP-10 to GP-13 | The push-grant checks run only when `CLAUDE_PUSH_COMMAND_ACTIVE=1` is set in the hook's own environment. `hooks/push.sh:397` sets it only inside push.sh, and push.sh's `git push` is seen by no hook (`push.sh:436`). Only tests that set it artificially reach these checks: `test_do_consent_landing.py:267-311` and the replay case `pushgrant`. |
| TP-15 | The Bash tool-list row check. None of the 23 policy roles excludes Bash, and `echo hi` passes for all 23. |
| OG-06 `_enforce_bash_worktree` | Unreachable from `main()`: OG-05 runs first, with the same test and the same exemptions. Only tests call it directly. |

### 1.4b DELETE by owner decision (7)

The owner decided on 2026-11-16 that branches and PRs are allowed everywhere; the concern was repository size, and it no longer applies (relayed by the reviewer; see also PR #56). So the branch and PR refusals in `hooks/pretool-block-branch-pr-worktree.py` are deleted:

| Rule | What it refuses today |
|---|---|
| BB-02 | `git checkout`/`git switch` that creates a branch (`-b`, `-B`, `-c`, `-C`, `--orphan`, `--track`, `--guess`) (`_is_co_sw_create`) |
| BB-03 | `git branch <new>` and `git branch --copy` (`_branch_creates`) |
| BB-04 | `git stash branch` (`_stash_creates`) |
| BB-05 | `git fetch`/`git pull` refspecs that create a local branch (`_refspec_creates`) |
| BB-06 | `git update-ref` that creates a ref (`_update_ref_creates`) |
| BB-07 | `gh pr create` / `gh pr new`, and `gh api` POST to `.../pulls` (`_is_gh_pr_create`, `_is_gh_api_pr_create`) |
| BB-08 | `gh pr checkout` (`_is_gh_pr_checkout`) |

These stay:
- **BB-01 (KEEP):** `git worktree add`, together with its `/dev-overnight`, `/do` and `/allow` exceptions, and `hooks/pretool-block-enterworktree.sh` for the `EnterWorktree` tool;
- **the fail-closed infrastructure** (`_may_create`, `_fail_closed_exit`, `_refuse_on_load_failure`), narrowed to the worktree case;
- **the branch delete/rename guards:** BS-42 and GP-06 (`git branch -D/-d/-m/-M/-f`, `update-ref`, `symbolic-ref`). `git update-ref` stays refused there as a direct ref mutation, so deleting BB-06 opens no `update-ref` path.

P14-8 does this. Once its hook change lands, it also rewrites CLAUDE.md's "Branches, PRs and worktrees" section (as #56 retitles it), which is the only CLAUDE.md edit P14 makes.

### 1.5 Dead code that is not a rule

These go in the lane that owns the file:
- **bash-safety:**
  - `any_subcmd_matches` (`:442-451`);
  - `strip_shell_prelude_for_compose`/`COMPOSE_COMMAND` (`:110-127`), whose result is never read;
  - the `BARE_WRITER)` case arm (`:1599`);
  - `HOOKS_DIR_BULK` (`:1295`).
- **GP:** `_is_overnight_active`, `_state_file_is_live` (`:1169-1190`) and `GIT_COMMAND_RE` (`:318`, read only by a test).
- **Classifier:** `_GIT_GLOBAL_VALUE`.
- **OG-05:** the `'worktree' not in path` fallback (`:596`).
- **bash_write_targets:** the `mode`/`mechanism` labels.
- **pretool-cp-state-write-guard.py:** its `bash_write_targets` import, which is never called.

TP-13 and TP-14 are in-flight compatibility code. Their own comments say to delete them once no session predates train 2. That is owner decision Q5.

### 1.6 Over-blocks this plan fixes

These are the only decisions that may change from allow-or-deny to allow.

| # | Command | Today | Cause | Fixed in |
|---|---|---|---|---|
| O1 | `git -c x=y commit -m "fix(session-recovery)"` | BS-19 deny | Quote masker gives up on `-c` | P14-5 (BS-19 asks "is the command word X") |
| O2 | `` echo $'a\'b' "$(echo x)" `` | census `unbalanced:single_quote`, then UNRESOLVED | `census()` has no `$'` case (`:235`, `:275`, `:184`) | P14-1 |
| O3 | `mv f ~`, `mv f ~/`, `mv f $HOME`, `cp f ~` | runtime-guard STEP0 deny | A destination directory is read as the mutated entry | P14-3 (target is `<dir>/<basename(src)>`) |
| O4 | `echo hi # don't`; a comment with an apostrophe before `ls .git`; an unquoted heredoc holding `it's` | census/lex fatal, BS-32 deny | Comments and heredoc bodies scanned as code | P14-1 |
| O5 | `git -c a=b commit -m "x; git push origin"` | GP push deny | `_is_text_only` drops text status once `-c` appears (classifier `:1810-1813`) | P14-2 |
| O6 | `echo "see secret > file"` (BS-21); `ls <ns> 2>/dev/null`, `cat <ns>` (BS-14); `cat <flag> \| cat` (BS-13); `git commit -m "fix: avoid npm install -g"` (BS-34); `bash <scratchpad>/x.sh` (BS-11) | bash-safety deny | Raw-text co-occurrence | P14-5 |
| O7 | `git log > /tmp/l; cat overnight-state-x.json` (OG-03); `git worktree list` (OG-22); a harness script run through `python3` (OG-13, recorded in `tests/replay/drivers/overnight.py:302`) | overnight-guard deny | Raw text; the verb is not narrowed | P14-11 |

The cd-then-config case from #14 is not an over-block. `cd <repo> && git config core.hooksPath …` from the harness home is intended:
- it is refused by BS-05 and pinned by `test_commit_hook_bypass_deny.py::test_keystone_write_whose_target_rests_on_the_shell_state_stays_denied_in_the_harness_home` (`:604-615`);
- `git -C <repo> config …` passes.

The plan keeps it (Q2).

### 1.7 Under-blocks the parser exposes

These are owner decision Q3. Reading the command correctly makes some existing rules see what they miss today. Each item is a rule that already exists and starts working; no new rule or list is involved.
- **Write forms:**
  - `&>`, `>|`, `dd of=`, `truncate`, `ln -sf`, `rsync`, `curl -o`, `git checkout -- <path>`, `git restore <path>`, written into paths that TP and OG protect. Measured rc=0 today, while the same target with `>` is refused.
  - `X=/p; echo > $X` resolves in the frozen extractor but not in the write-mode one.
- **Git:**
  - `git -C "my dir" push --force` (the classifier reads subcommand `dir"`);
  - `python3 -c "x; git reset --hard"` (it reads `--hard"`);
  - abbreviated long options `git reset --har`, `git branch --del` (git accepts both);
  - `push -uf`, `--force-if-includes`.
- **`echo x>settings.json`.** `harness-switch-guard.writes_settings_file` does not split on `>`.
- **The harness home as a linked worktree.** In that case `_HOME_PROTECTED` (`pretool-tool-policy.py:1371`) misses `<common>/config`, `<common>/hooks/`, `<gitdir>/config`, `config.worktree` and the `.git` file. Measured rc=0 for all of them, and for the Write tool too.

**Under-blocks left outside P14.** Closing these needs a rule that does not exist today. They are listed, not fixed:
- a shell fed by a pipe or here-string: `echo "git push --force" | sh`, `sh <<< "…"`;
- `python3 -c "os.system('git push --force')"`;
- `core.logAllRefUpdates=false` and `git reflog expire`;
- tag deletion, which ruleset R3 covers on GitHub.

The parser records how each command is fed (`walk` gives pipe, heredoc, here-string or file), so a later rule can be one predicate, not a list.

## 2. The shared parser

### 2.1 What the readers are today

There are 18 parsing mechanisms inside bash-safety alone (`P14-inventory/bash-safety.md`). Across the hooks:

| Reader | Method | Known failures (measured) |
|---|---|---|
| `bash_execution_boundary.py` `lex`/`analyze` (`:623`, `:4314`) | Real lexer: exact offsets, nested commands, explicit errors, ANSI-C, heredocs, fd redirects, about 100 wrappers, `bash -c`/`eval`/git alias bodies | `&>`/`&>>` read as `&` then `>`; no `{fd}>`; a comment after a word raises; heredoc end matched with `.strip()`; no quote record per part; no tree exposed |
| `bash_active_syntax_census.py` | Independent scanner | No `$'…'`, no comments (O2, O4) |
| `bash_context_strip.py` | Text view | `a#b` strips the rest; `$'…'` mangled; single `&` does not split |
| `bash_write_targets.py` | Regexes over a quote-blanked copy | `'it'\''s' > f` gives no target; `>a\ b` gives `a\`; never looks inside `$( )` or `bash -c` |
| `git_command_classifier.py` | Quote-blind segment split + `str.split`; a second lexer for `-c` strings | `-C "my dir"`; `-m 'a b c'` split into three args |
| `git-privilege-guard` | Classifier + 4 private readers (`_iter_commit_invocations`, two regexes, `_simple_commands`, `shlex` in `_branch_writes`) | GP-22 exists only because two of them can disagree |
| `git_clean_guard._lex` | A third full lexer | none listed |
| `grep-backtrack-guard` | ANSI-C decode + `shlex` + three near-duplicate body scanners | Lets the command through when `shlex` fails |
| `harness-switch-guard` | `shlex` without punctuation | `echo x>settings.json` passes |
| `runtime_guard/shell_lex.py`, `allowlist._bash_subcommands`, `grepguard_context_strip.py` | Private lexers | none listed |
| bash-safety | 10 to 12 Python starts per call (a plain `ls` starts 10), `grep -E` on raw text, `sed` splitters | 0.44 to 0.52 s per call |

No bash parser library is installed or vendored (no bashlex, no tree-sitter). Requirements list only the test stack. GNU bash 5.2 is present and serves as a syntax oracle through `bash -n -c`, which runs nothing.

### 2.2 Design

There is one module, `hooks/lib/shell_parse.py`. It is stdlib only and never raises.

- **`parse(text) -> Script`.** A failed parse carries `ParseError(code, offset)` plus the commands parsed before it. A failed parse is a fact the caller decides on (today: deny), never a guess.
- **Tree:**
  - Script → Pipeline → SimpleCommand / Compound (subshell, group, if, while, for, case, `[[ ]]`, `(( ))`, function).
  - A SimpleCommand holds Assignments, Words and Redirects.
  - A **Word** is a list of Parts. Each Part has a kind, decoded text, its quote kind (bare, single, double, ANSI-C `$'…'`, `$"…"`, escaped), a span, and, for `$( )`, backticks and `<( )`, a nested parsed Script.
  - A **Redirect** has fd, `{fd}`, op (including `&>`, `&>>`, `>|`, `<<<`, `>&-`), target and `Heredoc(delim, quoted, strip_tabs, body, terminated)`.
- **Views:**
  - `walk`: every command with its context and its feed (argv, pipe, heredoc, here-string, file).
  - `resolve`: peels wrappers (one table, merged from the classifier's and the analyzer's) and parses `-c`, `eval`, `su -c`, `ssh` payloads.
  - `argv`, `split_options`.
  - `executable_view`: the text with non-executable parts blanked, for the rules that stay text predicates.
  - `write_targets` gives `WriteTarget(path, mode ∈ {truncate, append, create, link, copy-dest, move-dest, delete, in-place}, mechanism, fd, decidable)`. Its verb coverage is the union of the three write-target paths that exist today, from one table, with assignment projection.
  - `git_invocations` gives `GitInvocation(global_opts, C_dirs, config_pairs incl. --config-env and GIT_CONFIG_*, env, subcommand, args with long-option abbreviation resolved, alias_body, unresolved)`.
- **CLI.** `python3 hooks/lib/shell_parse.py --facts` reads one hook payload on stdin and prints one JSON fact sheet. The shell hooks need one Python start per call, not ten.

It is built from code that exists today, and nothing is written twice:
- `bash_execution_boundary.py:192-711` (`Src` offset map, Word segments, `Redir`, `_lex_*`, `lex`), `split_opts` (`:713-944`) and `ansi_decode` (`:1597`) move into it;
- the boundary analyzer keeps its policy tables and imports the lexer;
- the feed tracking is modelled on the classifier's `_shell_words`.

The census stays an independent second check, as its contract requires, with O2 and O4 fixed.

The estimated size is about 2,400 lines (range 2,100 to 2,800). The readers it replaces hold about 3,100 parse lines today, and runtime_guard, git_clean_guard and allowlist add about 700 more.

### 2.3 The experiment that shows it reads at least what the readers read

This experiment is P14-1's acceptance. Its inputs were prepared on 1ace5ee4.

**E1 Corpus.** `REPO=<repo> python3 -I harness-repair-plan/tools/p14/extract_corpus.py out.json` extracts 3,829 distinct command strings from 264 test files and fixtures:
- 1,002 strong, 2,827 weak (about 10% noise), 330 templates, 209 multi-line;
- it parses the files and never imports them;
- it was re-run on 1ace5ee4 and reproduces 3,829.

Add the generated sweeps of `pol_sweep_generators.py` (about 27k strings by the analyzer's own count).

For every string, record:
- (a) `bash -n -c` accept or reject;
- (b) each old reader's output: boundary `lex`/`analyze`, census, `strip_non_executable_contexts`, the three write-target paths, classifier `iter_git_invocations`, grep-guard `_find_searches`, `writes_settings_file`, `allowlist._bash_subcommands`, `runtime_guard.shell_lex`;
- (c) the new parser's corresponding view.

Pass: for every reader, each fact it extracts is extracted by the new view (a superset). Every difference falls in one of three groups:
- a listed fix (O1 to O7);
- a listed under-block (1.7), only once Q3 says yes;
- a string bash rejects, where the new parser's `ParseError` stands in for the old one's error.

Zero differences may be unexplained. Measured today: 3,636 strings are accepted alike by bash, the census and `lex()`. The census rejects 17 strings that bash accepts:
- 4 are `$'…'`;
- 6 are comments holding an apostrophe;
- 7 are unterminated heredocs, which looks deliberate.

**E2 Decisions.** Every hook decision on every Bash call stays the same, except O1 to O7 (and 1.7 under Q3). Measured on 1ace5ee4, with baseline files in the session scratchpad that the P14-1 lane re-creates (section 4):

| Suite | Result | Bash decisions |
|---|---|---|
| Adversarial corpus `test_blackbox_integration.py` + `check-enforcement-evidence.py --coverage` | 41 passed, PASS | 39 |
| Fail-closed companions | 45 passed | 45 |
| `test_commit_hook_bypass_deny.py` | 850 passed | about 850 |
| `test_env_configured_defaults.py` | 67 passed | about 60 |
| Artifact check `tests/test_artifact_graph.py` | 3 passed, 0 violations, 232 artifacts | 1,494 (70 traced replays) |
| Replay + fault suite | Not finished: 192 replays, about 3 to 4 h on 4 CPUs | 831 from 27 replays, 0 hook errors |

The replay suite has to be baselined in CI's six shards (`replay suite i/6`), or in local shards with pytest-xdist already on `PYTHONPATH`. Without xdist, `tests/replay/sandbox.py:213-238` runs `pip install -r requirements.txt` over the network.

## 3. GitHub branch protection

The repository `Yugoge/awesome-claude-harness` is public, so baseline CI runs on it (D30 visibility gate). Required status checks are left out, because on a direct push they amount to requiring a pull request (Q4). The settings below are owner steps (G1). Nothing in a lane applies them.

| Ruleset | Target | Rules | Bypass |
|---|---|---|---|
| R1 `default-branch` | `~DEFAULT_BRANCH` | Restrict deletions; Block force pushes | none |
| R2 `all-branches` | `~ALL` branches | Block force pushes | none |
| R3 `tags` | all tags (`refs/tags/*`) | Restrict deletions; Restrict updates | none |
| R4, optional (Q4) | `~DEFAULT_BRANCH` | Require a pull request before merging, 0 approvals | none |

Path: Settings → Rules → Rulesets → New branch ruleset. Each ruleset has Enforcement "Active".

**Why there is no bypass.** On the owner's machine an agent pushes with the owner's credential, so a repository-admin bypass would exempt the agent too.

**Phases that rewrite history.** P11 rewrites history and deletes remote refs. During that run the owner sets R1 to R3 to "Disabled", and enables them again afterwards.

**What the rulesets replace:**
- BS-41: force, delete, mirror and `+ref`/`:ref` pushes, through R1, R2 and R3. A `--mirror` push can still delete non-default branches, because R2 does not restrict deletions; agent branches are deleted after merge.
- GP-08: force and delete pushes, through R1 to R3. Tag deletion, which neither hook refuses today, is covered by R3.

**What stays local, because GitHub cannot see it:**
- GP-09: an agent push without a `/push` grant (GitHub sees the owner's key);
- every commit rule (GP-14 to GP-30, BS-04 to BS-07);
- local ref mutations (GP-06, GP-03 on the local default branch);
- reset, clean, stash and checkout/restore (BS-36 to BS-39, BS-43, GCL);
- the harness home and state-namespace rules;
- every non-git rule;
- pushes to remotes that are not GitHub;
- product users whose repositories carry no ruleset. The README's install section names R1 to R3 as a recommended step; the integration lane writes it.

**Verification for G1.** On a throwaway branch of the repository, run from a plain terminal (not an agent):
- `git push --force` of a rewritten commit is refused by GitHub;
- `git push origin :<branch>` on the default branch is refused;
- `git push origin :refs/tags/<t>` is refused.

The owner pastes the three refusals into the P14-4 PR. P14-4 removes the local copy only after that, if Q1 says so.

## 4. Bars (every lane, and the train)

1. **Decisions unchanged.** The bar covers the corpus (39), the fail-closed companions (45), `test_commit_hook_bypass_deny.py` (850), `test_env_configured_defaults.py` (67), the artifact check (0 violations, 1,494 Bash decisions per hook, as in `tools/p14/dump_replay_decisions.py`'s TSV), and the full replay and fault suite. Both are compared as the per-hook decision on each Bash call, against a baseline each lane records on `origin/master` before its change (CI shards or local shards).
   - The only allowed differences are O1 to O7 and, under Q3, the 1.7 list.
   - Each changed decision gets a test pinning its new value.
   - Tests that pin source text (in `test_blackbox_integration.py`, `test_commit_artifact_rw_boundary.py`, `test_fail_closed_drift.py`, `test_git_cmd_cross_consistency.py`, `test_bash_safety_git_clean.py::_mutant_hook`, `test_pol_generative_sweeps.py`) may be rewritten into behaviour tests over the same cases, never deleted. The PR lists each one, old assertion against new.
2. **Net lines.** `pretool-bash-safety.sh` plus any rules module it delegates to totals at most 1,354 lines (half of 2,709); the target is about 1,000. The total over the files in section 6 drops by at least as much as bash-safety does: no line moves out of bash-safety without leaving the total. Every lane reports `wc -l` before and after for the files it owns.
3. **No history comments.** No dates, issue or PR numbers, commit ids, "previously", "was added because", "FROZEN since", or revision-history blocks in any touched file. CI's existing comment checks stay green.
4. **Artifact check at 0 violations.**
5. **No new special-case list.**
   - A fix may change how an existing rule reads the command, or delete a rule.
   - It may not add a word list, an exception list or a per-command carve-out.
   - Wrapper and verb tables move into the parser's one table; they are not copied.
6. **Live tree safety.** `settings.json` registrations stay as they are: same files, same matchers. A file that is still registered is never deleted.
7. **CI green** on 3.10, 3.11 and 3.12. The replay suite is run in shards.

## 5. Lanes

Each lane is one issue. Lanes in the same wave own disjoint files. A lane never touches the files of these open PRs until they merge:

| PR | Files |
|---|---|
| keystone PR | `hooks/lib/bash_write_targets.py`, `hooks/pretool-overnight-hook-guard.py` |
| settings-switch PR | `hooks/pretool-harness-switch-guard.py` |
| parallel-launcher PR | `hooks/lib/hook_launch.py` |
| #29 | `tests/replay/drivers/` |

| Lane | Issue | Owns | Needs | Wave |
|---|---|---|---|---|
| P14-1 | The shared parser, E1 differential, census fixes, replay baseline | new `hooks/lib/shell_parse.py`; `hooks/lib/bash_execution_boundary.py` (lexer moved out); `hooks/lib/bash_active_syntax_census.py`; new tests | none | A |
| P14-2 | One git view | `hooks/lib/git_command_classifier.py`, `hooks/lib/git_clean_guard.py` | P14-1 | B |
| P14-3 | runtime_guard reads the parser | `hooks/lib/runtime_guard/*` | P14-1 | B |
| P14-6 | tool-policy reads the parser | `hooks/pretool-tool-policy.py` | P14-1 | B |
| P14-7 | grep-backtrack-guard reads the parser | `hooks/pretool-grep-backtrack-guard.py`, `hooks/lib/grepguard_context_strip.py` | P14-1 | B |
| P14-8 | Branch and PR refusals deleted (owner decision); the worktree rule reads the parser | `hooks/pretool-block-branch-pr-worktree.py`, its tests, CLAUDE.md "Branches, PRs and worktrees" section | P14-1 and #56 merged | B |
| P14-9 | `/allow` grant matching reads the parser | `hooks/lib/allowlist.py` | P14-1 | B |
| P14-4 | Privilege guard on one reader; dead push checks out | `hooks/pretool-git-privilege-guard.py` | P14-2 (+ G1 if Q1 = replace) | C |
| P14-5 | bash-safety slimmed | `hooks/pretool-bash-safety.sh`, new `hooks/lib/bash_safety_rules.py`, `hooks/lib/bash_context_strip.py` (deleted when its last user goes), `hooks/lib/pol_degraded_removal_reference.ere` | P14-2, P14-3, P14-4, P14-7, P14-8 | D |
| P14-10 | Write targets retired into the parser | `hooks/lib/bash_write_targets.py` (kept as an import shim), `hooks/pretool-cp-state-write-guard.py`, `hooks/pretool-wrapper-userintent.py`, `hooks/lib/attribution_journal.py` | the keystone PR merged; P14-1 | gated |
| P14-11 | Overnight guard's Bash path on the parser | `hooks/pretool-overnight-hook-guard.py` | the keystone PR merged; P14-10 | gated |
| P14-12 | Harness-switch guard on the parser | `hooks/pretool-harness-switch-guard.py` | the settings-switch PR merged; P14-1 | gated |
| P14-13 | Integration: replay drivers' DEVIATION entries, README ruleset step, final accounting | `tests/replay/drivers/` (DEVIATION entries only), `README.md` install section, `docs/ENFORCEMENT-LEDGER.md`, `docs/ADVERSARIAL-CORPUS.md` line citations, INDEX files | #29 merged; all lanes | last |

`hooks/pretool-claude-config-guard.py` is not in any lane. OG-01 and OG-02 merge into it as it stands, with no change to it.

Prompts are at `prompts/P14-1.md` to `prompts/P14-13.md`, each self-contained.

## 6. Lines before and after

"Before" is `wc -l` on 1ace5ee4. "After" is the estimate this plan commits the lanes to; the bars in section 4 are the hard limits.

| File | Before | After (est.) | Lane |
|---|---|---|---|
| `hooks/pretool-bash-safety.sh` + new `lib/bash_safety_rules.py` | 2,709 | 1,000 | P14-5 |
| new `hooks/lib/shell_parse.py` | 0 | 2,400 | P14-1 |
| `hooks/lib/bash_execution_boundary.py` | 4,499 | 2,600 | P14-1 |
| `hooks/lib/bash_active_syntax_census.py` | 399 | 330 | P14-1 |
| `hooks/lib/bash_context_strip.py` | 440 | 0 | P14-5 |
| `hooks/lib/bash_write_targets.py` | 1,277 | 60 (shim) | P14-10 |
| `hooks/lib/git_command_classifier.py` | 1,892 | 800 | P14-2 |
| `hooks/lib/git_clean_guard.py` | 835 | 450 | P14-2 |
| `hooks/pretool-git-privilege-guard.py` | 2,142 | 1,350 | P14-4 |
| `hooks/pretool-tool-policy.py` | 1,621 | 1,450 | P14-6 |
| `hooks/pretool-overnight-hook-guard.py` | 2,535 | 1,900 | P14-11 |
| `hooks/pretool-grep-backtrack-guard.py` | 1,253 | 850 | P14-7 |
| `hooks/pretool-harness-switch-guard.py` | 274 | 250 | P14-12 |
| `hooks/stop-command-gate.py` | 942 | 942 | none |
| `hooks/userprompt-usage-snapshot.py` | 262 | 262 | none |
| `hooks/userprompt-consent-allowlist.sh` | 691 | 691 | none |
| **Subtotal, the brief's 15 files + new** | **21,771** | **15,335** | |
| `hooks/lib/runtime_guard/shell_lex.py` (+ adapter in `_core.py`) | 237 | 60 | P14-3 |
| `hooks/lib/allowlist.py` | 638 | 560 | P14-9 |
| `hooks/lib/grepguard_context_strip.py` | 231 | 0 | P14-7 |
| `hooks/pretool-block-branch-pr-worktree.py` | 915 | 300 | P14-8 |
| **Total** | **23,792** | **about 16,200 (−7,600, −32%)** | |

About 1,500 of the removed lines are history comments:
- bash-safety: about 500 (594 lines are in history paragraphs);
- the GP revision-history docstring: 104 lines at `:54-157`;
- the boundary: about 316.

The bar for bash-safety is −1,355 lines; the estimate is −1,709.

## 7. Leftovers: the gate edge cases (not P14)

Only items 1 and 3 are on the Bash-reading path.
- **Item 1 (unbalanced quote).** The parser keeps today's verdict (deny, fail closed) and makes it an explicit `ParseError`.
- **Item 3 (grant matching).** P14-9 moves grant matching onto the parser and keeps its behaviour.

The rest are gate concerns for a separate plan. Each was reproduced on 1ace5ee4 unless marked.

| # | Case | Where | Verdict |
|---|---|---|---|
| 1 | Unbalanced quote | `bash_execution_boundary.py:4328-4333`, `pretool-bash-safety.sh:1862` | Deny is right (bash will not run it). The over-blocks of `# don't` and heredoc `it's` are O4. |
| 2 | `--auto` | `stop-command-gate.py:346-348` | Still wrong. With no opener timestamp, a task minted after the opener holds `/commit --auto`. An open quote in the args holds the Stop with no agent action. |
| 3 | Blocked grant then approved | `pretool-bash-safety.sh:807-832`, allowlist | A grant whose call is denied is not spent, and stays live for 300 s for the next call it matches. bash-safety and branch-pr honour it; GP can still deny. Not pinned. |
| 4 | Corrupt newest grant | `lib/merge_grant.py:61-68` | `newest` returns `{}` and does not fall back to an older valid grant (unlike GP's `_find_grant`). |
| 5 | `core.logAllRefUpdates=false` | `stop-command-gate.py:538-660` | Fails open: a bare `/merge` that merged nothing passes once reflogs are off. No Bash rule refuses turning them off (1.7). |
| 6 | Missing opener timestamp | `command_span.py:519-528`, `stop-command-gate.py:560-564` | `/push` and `/merge` hold the Stop until `/stop`. |
| 7 | Overnight launch aborts before its record | `stop-command-gate.py:418-428` | "no overnight state record" holds the Stop until `/stop`. |
| 8 | Skipped wake check | `stop-command-gate.py:848-853` | The Stop is allowed while wake `cron-7` is still scheduled. |
| 9 | Fallback ignores `agent_id` | `stop-launch.py:49-62` | With the coordinator missing, a Stop payload with `agent_id` exits 2; the gate itself allows it (`:883`). |
| 10 | `disposition_lines` read twice | `stop-command-gate.py:448` | Plausible, not reproduced. |
| 11 | Gate's own parse of the push-gate token | `stop-command-gate.py:759-766`, `push.sh:203-245`, `scripts/execute-push.py:90, :173-176` | Three readers of one token. They agree on pinned cases and differ on symlinks, branch and ancestry base. |

None of 2 and 4 to 11 is pinned by a test.

## 8. Owner decisions

| # | Decision | Options | Recommendation |
|---|---|---|---|
| Q1 | Force/delete pushes: does GitHub replace the local refusal? | (a) Apply R1 to R3; P14-5 deletes BS-41 and P14-4 deletes GP-08's force/delete branch after the G1 check. (b) Keep GP-08 as the one local copy and delete only BS-41. | **(a)** for this repository, as the owner's direction says. Product users get R1 to R3 as a README step. |
| Q2 | `cd <repo> && git config core.hooksPath …` from the harness home | (a) Keep the refusal (pinned; `-C` works). (b) Allow when the cd target is provably another repository. | **(a)**: it is intended, and (b) needs shell-state tracking. |
| Q3 | Under-blocks the parser exposes (1.7) | (a) Let the existing rules see them (decisions change to deny on that list only, each pinned by a test). (b) Keep today's decisions exactly. | **(a)**: these are the same rules reading correctly, with no new list. |
| Q4 | Require a pull request on the default branch (R4) | (a) Yes. (b) No. | **(b)** for now: `/push` on the owner's machine pushes the default branch directly, and R4 would refuse it. |
| Q5 | TP-13, TP-14 in-flight compatibility code | (a) Delete now. (b) Keep until the owner says no session older than train 2 is running. | **(a)** if no session started before 2026-11-08 is still running; only the owner knows. |
| Q6 | The bulk-commit sentinel can be minted from Bash: BS-17's canonical form at `pretool-bash-safety.sh:1273` exits 0 for `python3 <home>/scripts/write-bulk-commit-sentinel.py`, while `commands/commit.md:188-191` says the UserPromptSubmit hook is the only minter | (a) Close it: the canonical form allows only reads; change the pinned allow in `test_env_configured_defaults.py::test_harness_home_resolves_from_the_hook_location` to a deny. (b) Keep it, and correct commit.md. | **(a)**: it is the only allow on bash-safety's path that skips every later rule. |
| Q7 | Rules whose messages say "PERMANENTLY FORBIDDEN" are released by `/do` and `/allow` (everything after `:835`) | (a) Keep the behaviour and correct the messages. (b) Move the hard bans before the bypass. | **(a)**: CLAUDE.md says `/do` lifts every limit but the permanent one. P14-5 makes the messages say what is true. |
