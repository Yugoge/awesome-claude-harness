# Inventory: Bash refusal rules in pretool-tool-policy.py, pretool-overnight-hook-guard.py, lib/bash_write_targets.py

Repo: <repo> @ 1ace5ee (clean tree; nothing in it was modified).
Experiments ran under `$S=$SCRATCH`:
`HOME=$S/home-tp`, `GIT_CONFIG_GLOBAL=$S/home-tp/gitconfig` (empty), `CLAUDE_STATE_DIR=$S/state`.
`$HOME/.claude` is a **linked git worktree** of a throwaway clone (`$S/clone`), so the hooks resolve the harness
home to it (lib/claude_home.resolve walks up from the hook file). Overnight experiments use a throwaway repo
`$S/ovproj` (main root) with linked worktree `$S/ovproj/.claude/worktrees/w1` and a hand-written live
`overnight-state-x.json` (isolation_kind `worktree`, protected_branch `master`). No bubblewrap on this host,
so the overnight guard takes its fail-closed path. Runner: `$S/scripts/run.sh`; matrix: `$S/scripts/matrix.py`;
line counts: `$S/scripts/lines.py`, `$S/scripts/lines_strict.py`.

Registration: both hooks run as rules of `hooks/pretool-write-gate.py` (`hooks/lib/write_gate/__init__.py:73-79`:
`overnight-boundary` fail-open, `tool-policy` fail-closed). `pretool-bash-safety.sh` is registered separately
(settings.json PreToolUse matcher `Bash`).

Pin sources searched: `hooks/tests/**`, `tests/**` (incl. `tests/replay/**`), `hooks/tests/fixtures/adversarial_corpus.json`
(the JSON is the corpus' authority; `docs/ADVERSARIAL-CORPUS.md` is its index). **The adversarial corpus has 39
cases, all on git_command_classifier / bash-safety / git-privilege-guard; none pins any rule below** (guard_chain
census). Searches: refusal message literal, function name, and command shape.

## 1. pretool-tool-policy.py (Bash-firing rules)

Order in `main()` (:1561-1588): bootstrap -> `_check_protected` -> (ScheduleWakeup, not Bash) -> declared writes ->
/clean -> grant binding -> in-flight msg -> in-flight entry -> [main agent / unresolved / unlisted role exit 0] -> role rows.
Reading paths: **F** = FROZEN `extract_bash_write_paths` (bash_write_targets.py:803) via `_extract_targets` :182-203,
applied to the command plus every shell `-c` layer (`_bash_texts`/`_layer_texts` :221-243, walker =
`lib/git_command_classifier.iter_shell_texts`); **T** = `extract_bash_touched_paths` (:1242, built on the mode
extractor :1117) plus F's targets, same layers (`_check_protected` :1477-1504).

| id | file:lines | refuses (example) | reads via | switch/env/grant | pinned by | class / reason |
|---|---|---|---|---|---|---|
| TP-01 | :149-172 | any tool call when lib imports fail (fail closed). `echo hi` with a broken lib/ | n/a (import) | none | none found (message literal absent from tests) | KEEP-LOCAL - becomes the shared parser's own fail-closed import |
| TP-02 | :1371-1373, :1403-1410, :1477-1515 | write/delete/rename of harness-home `settings.machine.json`, `private-literals.txt`, `scripts/check-public-core.sh`, `scripts/install/render-settings`, `hooks/git-hooks/pre-commit`, `.git/config`, `.git/hooks`, `.gitattributes`, every caller incl. main. `echo x > ~/.claude/.gitattributes` (rc=2) | T (+F); `os.path.expandvars` + `${V:-d}` regex :1495 | none (D11/D12); no /do | hooks/tests/test_tool_policy_protected_paths.py::test_r3_engines_and_git_files_of_the_harness_home_are_denied, ::test_a_move_into_a_directory_over_a_protected_file_is_denied, ::test_the_same_names_in_a_product_repository_stay_writable; test_tool_policy_c_layer_writes.py::test_a_layer_exits_as_its_plain_command; test_c_layer_protected_targets.py::* | KEEP-LOCAL. `settings.machine.json` part duplicates hooks/pretool-harness-switch-guard.py (rc=2 on the same Bash write, measured) - not one of the two named merge targets. **Gap: linked-worktree git dir (finding 2)**; misses `ln -sf`, `rsync`, `git checkout --`, `python -c open()` (measured rc=0) |
| TP-03 | :1414-1417 | write of a hook-owned owner-answer file (`lib/requirement_round.HOOK_OWNED`) | T | none | test_tool_policy_protected_paths.py::test_r6_hook_owned_files_are_refused_to_every_agent | KEEP-LOCAL |
| TP-04 | :1418-1419 | write of `<config>/logs/lifecycle.jsonl(.lock)` | T | none | test_tool_policy_protected_paths.py::test_r2_paths_are_denied_to_every_caller | KEEP-LOCAL |
| TP-05 | :1420-1421 | write of a session transcript `*.jsonl` / `agent-*.meta.json` under `~/.claude/projects` | T | `CLAUDE_CONFIG_DIR` | test_r2_paths_are_denied_to_every_caller, ::test_a_directory_holding_transcripts_or_metas_is_denied | KEEP-LOCAL |
| TP-06 | :1422-1423 | write of `<state>/claude-do-task-*.json` | T | `CLAUDE_STATE_DIR` | ::test_the_do_sidecar_without_a_state_dir_is_the_default_roots, test_r2 | KEEP-LOCAL |
| TP-07 | :1389-1400, :1424-1426, :1441-1474, :1496-1497 | push-gate token / push-analyst grant under `<state>/agentic-commit/`, except the grant's own producer's write. `echo x > $state/agentic-commit/push-analyst/a/b/c.json` | T | producer exemption via dispatch record | ::test_h2_the_push_stops_inputs_are_denied_to_every_caller_without_their_dispatch, ::test_h2_the_push_analyst_writes_the_grant_its_own_dispatch_binds_and_nothing_else, ::test_h2_a_subagent_of_another_type_given_the_same_prompt_is_no_producer; tests/replay/test_push_holds.py | KEEP-LOCAL (local /push gate input, not remote protection) |
| TP-08 | :1427-1437 | rm/mv of a directory holding any TP-02..07 file. `rm -rf ~/.claude/scripts` | T (removed flag) + `os.walk` | none | ::test_a_directory_holding_transcripts_or_metas_is_denied, ::test_h2_a_directory_holding_a_token_or_a_grant_is_denied, ::test_a_removal_or_move_over_no_protected_file_is_not_denied | KEEP-LOCAL |
| TP-09 | :918-1058 | another caller's write of a path a started dispatch's obligation/template declares (D8). main agent `echo x > docs/dev/qa-report-<id>.json` | F, then lib/declared_paths shapes + transcript `_Record` | none | hooks/tests/test_tool_policy_derived_permission.py (60+ tests, e.g. ::test_any_other_caller_is_denied_whatever_a_prefix_allows, ::test_the_extractor_reads_heredoc_and_jq_writes); tests/replay/test_a20.py | KEEP-LOCAL |
| TP-10 | :930-938 | any write when declared-paths readers fail to import (fail closed) | n/a | none | none found | KEEP-LOCAL |
| TP-11 | :1266-1298 | another caller's write of a path the active /clean's owner approved for cleaner / rule-inspector | F | /clean span | hooks/tests/test_clean_approved_writes.py::test_another_caller_does_not_write_the_cleaners_approved_paths, ::test_the_main_agents_refusal_names_the_producer | KEEP-LOCAL |
| TP-12 | :733-754 | non-owner write under `<state>/agentic-commit/<role>/` (unexpanded word judged by its spelled dir) | F | none | hooks/tests/test_grant_binding.py::test_only_the_analyst_writes_its_grant, ::test_every_write_tool_and_an_unexpanded_word_are_bound, ::test_removal_and_the_rest_of_the_state_dir_are_not_bound | KEEP-LOCAL (overlaps TP-07 on push-analyst dir; TP-12 is F-only so `dd of=` passes - measured rc=0) |
| TP-13 | :778-815 | any caller but the changelog-analyst writing `/tmp/commit-msg-*.txt` / `/tmp/recovery-commit-*.txt`. `echo x > /tmp/commit-msg-abc.txt` (rc=2 main) | F | "in-flight compatibility (A17)", sunset D15 | test_grant_binding.py::test_no_other_caller_writes_the_in_flight_message_file, ::test_an_in_flight_changelog_analyst_writes_its_commit_message_file (+recovery variants) | KEEP-LOCAL with sunset: comment says delete once no session predates train 2; train 2 landed 2026-11-08 (git log dfc9053), 8 days before today - cannot prove DEAD from the repo |
| TP-14 | :842-915 | any caller but the test-writer writing `.claude/dev-registry/<id>/test-writer.json` | F | same sunset | test_grant_binding.py::test_no_other_caller_writes_the_test_writer_entry, ::test_an_in_flight_test_writer_creates_its_own_cycles_registry_entry | KEEP-LOCAL with sunset (as TP-13) |
| TP-15 | :1338-1348 (idx 0, target None) | Bash itself for a role whose `allowed_tools`/`denied_tools` exclude Bash | `is_allowed(role,"Bash",None)` | policies/tool-policy.v1.json | none found for Bash | **DEAD for Bash**: 0 of 23 policy roles exclude Bash (policy scan); `echo hi` for all 23 roles -> rc=0 (measured). The is_allowed path stays for other tools |
| TP-16 | :1338-1350 (idx>0) | Bash write target outside role's allowed / inside denied write prefixes (checked as Write). ba `echo x > proj/src.py` rc=2 | F | policy rows; own/approved/message_file relaxations | hooks/tests/test_bash_write_targets_policy.py::test_projected_result_still_traverses_deny_before_allow; test_tool_policy_contracts.py; tests/test_bash_write_targets_verb_narrowing.py::test_tool_policy_still_detected_* (17 tests) | KEEP-LOCAL. F misses `dd of=`/`truncate`/`curl -o`/`>|`/`&>` (ba `dd of=proj/src.py` rc=0, measured) |
| TP-17 | :365-424 | write into a sibling dispatch's `.claude/scratch/<rs>/<role>/<id>/` | F | none | tests/test_tool_policy_note_fail_closed.py::test_note_follows_the_refusal_without_a_fault, ::test_exception_inside_the_note_keeps_exit_2 | KEEP-LOCAL |
| TP-18 | :418-430, :310-340 | write to `/tmp`, `/var/tmp` outside the role's own temp prefixes, every role incl. `*`. dev `echo x > /tmp/foo` rc=2 | F | role temp exceptions from policy | none found by message ("arbitrary /tmp and /var/tmp" absent from tests) | KEEP-LOCAL; F-only: dev `dd of=/tmp/foo`, `echo x >\| /tmp/foo`, `echo x &> /tmp/foo` all rc=0 (measured) |

Not refusals but on the Bash refusal path: `_note_bash_write_target` :447-486 (explains an inferred target),
`_note_inflight_token_route` :1528-1537 (A17 note). Not Bash: `_check_scheduled_prompt` :1540-1558 (ScheduleWakeup).

## 2. pretool-overnight-hook-guard.py (Bash path)

Order in `main()` (:2431-2511): AskUserQuestion (not Bash) -> if any live overnight state: global security
(OG-01..03, every session) -> classify actor (`_classify_actor` :915; `normal` exits 0 here, so the
"all sessions" worktree enforcement below never applies to a normal session - measured rc=0 for session `z`) ->
invalid isolation -> git rules (owner/child/worktree_context, Bash) -> write boundary (bwrap rewrite, else fail
closed) -> global worktree enforcement -> session worktree checks.
Reading paths: **F** (FROZEN extractor via `_extract_bash_write_paths` :752-763); **RX** = raw regex on the
command (heredoc bodies stripped where noted); **GI** = `_iter_git_invocations` :1012-1069 (own `str.split`
tokenizer, separators, cd tracking, wrapper skipping); **SEG** = `re.split(r'[;&|\n]+')` + `str.split`.
Commands for the git rules are first passed through `_strip_shell_comments` :1389-1436.

| id | file:lines | refuses (example) | reads via | switch/env/grant | pinned by | class / reason |
|---|---|---|---|---|---|---|
| OG-01 | :631-649, :726-730 | any session, while any overnight is live: Bash write to `.claude/hooks/`. `echo x > .claude/hooks/x.py` | RX (heredoc stripped) | self_repair grant (`_grant_skips_block` :269, contract) | none found (message, `check_bash_targets_hooks` absent from tests) | **MERGE -> hooks/pretool-claude-config-guard.py** (same regex list, always on; measured identical verdicts on 5 shapes incl. the read over-block `cp .claude/hooks/x.py /tmp/b.py` and the miss `sed -i`/`dd of=`). The overnight self_repair grant is moot: config-guard still refuses unless `.hook-refactor-allow` exists. Not bash-safety/privilege-guard |
| OG-02 | :652-673, :731-733 | same for `.claude/commands/`. `cp a .claude/commands/x.md` | RX | self_repair grant | none found | **MERGE -> pretool-claude-config-guard.py** (same) |
| OG-03 | :607-628, :734-736 | any session: modify/delete `overnight-state-*.json`. `rm .claude/overnight-state-x.json` | RX (heredoc stripped) | never grantable | hooks/tests/test_overnight_state_file_write_guard.py::test_bash_redirect_into_state_file_blocked | KEEP-LOCAL (no other hook protects it: tool-policy, config-guard rc=0 measured). Over-blocks reads: `git log > /tmp/l; cat overnight-state-x.json` rc=2 (regex `>\s*.*overnight-state-`); misses `sed -i`, `dd of=` |
| OG-04 | :467-476, :500-510, :2507-2508 | enforced actor's Bash write outside every live isolated worktree (+state dir, /tmp, harness-state dirs for main agent). `echo x > /home/elsewhere/a` | F | self_repair grant; `_is_docker_compose_safe` :747-749 skips the whole check if the text contains `docker compose build/up` | tests/test_overnight_guard_in_place_git.py::test_concurrent_isolated_session_cannot_write_into_main_root, ::test_in_place_record_never_joins_the_write_confinement_allow_list; tests/test_bash_write_targets_verb_narrowing.py::test_overnight_still_detected_real_copy_refused (direct call) | KEEP-LOCAL. F misses `dd of=/home/elsewhere/a`, `>|`, `&>` (rc=0 measured). Docker exemption is text-wide: `docker compose up -d; echo x > /home/elsewhere/a` skips OG-04 (only OG-05 then catches it); docker exemption pinned by none found |
| OG-05 | :799-823, :938-943 | owner/child Bash write outside its own worktree. (msg `WORKTREE STRING ENFORCEMENT`) | F | self_repair grant | tests/test_bash_write_targets_verb_narrowing.py (direct calls of `_check_bash_string`) | KEEP-LOCAL. Its `'worktree' not in path` fallback (:596-597) is **DEAD**: owner/child with no worktree_path is blocked earlier by OG-07 (:2456-2459) |
| OG-06 | :775-796, :826-831 | same predicate as OG-05 (msg `WORKTREE ENFORCEMENT: File is outside`) | F | same | tests/test_bash_write_targets_verb_narrowing.py (direct call of `_enforce_bash_worktree`) | **DEAD**: unreachable from main(); runs only after OG-05 with identical exemption chain and `is_outside_worktree` == `path_outside_session_worktree` for non-empty wt. Measured: the docker-exempt write above reports OG-05's message, never OG-06's |
| OG-07 | :1984-1991, :2455-2459 | any tool by owner/child whose state lacks worktree_path | n/a | none | none found | KEEP-LOCAL |
| OG-08 | :1072-1190, :1747-1754 | `-c core.hooksPath=`, `-c include.path`/`includeIf.*.path`, `GIT_CONFIG_*`, `--config-env`. `git -c core.hooksPath=/dev/null status` | RX + GI (token-aware, global-option region) | none | tests/test_overnight_guard_in_place_git.py::test_in_place_actor_still_refused_git_config_hook_suppression | KEEP-LOCAL (bash-safety commit-hook-bypass covers the same overrides only for `git commit`; bash-safety imports OG's `_config_key_redirects_keystone`/`_git_invocation_injects_keystone_config` at pretool-bash-safety.sh:327,332,367 - shared-parser candidate) |
| OG-09 | :1194-1323, :1757-1758, :1854-1855 | `git config` write of core.hooksPath/include.path/includeIf, built-from-expansion key, core section remove/rename, `--edit`. `git config core.hooksPath /dev/null` | GI (+ `_neutralize_substitutions`) | none | tests/test_overnight_guard_in_place_git.py::test_keystone_config_scan_skips_every_value_option_of_the_table; hooks/tests/test_overnight_worktree_no_bwrap.py::test_keystone_removals_stay_refused_without_bwrap, ::test_reading_the_keystone_passes | KEEP-LOCAL (partial overlap with bash-safety `config-keystone-write` :407, which only refuses writes reaching the harness home; OG refuses it in any repo for an overnight actor) |
| OG-10 | :1331-1386, :1759-1765 | any write onto `config.worktree` or a path built from `git rev-parse --git-dir`. `echo x > w1/.git/config.worktree` | SEG + own verb set `_WRITE_VERBS` (has ln, dd, truncate, rsync, python...) | none | hooks/tests/test_overnight_worktree_config_file.py::test_no_route_writes_the_per_worktree_config, ::test_reading_and_ordinary_config_work_still_passes, ::test_helpers_read_a_command_the_way_git_and_the_shell_do | KEEP-LOCAL (fourth independent write-verb list; fold into shared parser) |
| OG-11 | :1572-1593, :1766-1772 | `--git-dir`/`GIT_DIR`/`GIT_COMMON_DIR` into main's git dir. `git --git-dir=$P/.git log` | RX | none | none found | KEEP-LOCAL |
| OG-12 | :1596-1619, :1775-1782 | `--work-tree`/`GIT_WORK_TREE` into main. `git --work-tree=$P status` | RX | none | tests/test_overnight_guard_in_place_git.py::test_isolated_work_tree_override_into_main_still_blocked, ::test_in_place_work_tree_override_at_its_own_root_is_allowed | KEEP-LOCAL |
| OG-13 | :1622-1709, :1784-1793 | interpreter (python/perl/ruby/node/sh/bash/env) whose text or readable script holds a main-targeting dangerous git op. `python3 -c 'subprocess.run(["git","checkout","master"])'` | RX + file read of script operands | harness-script exemption `_harness_script` :2249 | hooks/tests/test_overnight_operand_scan_channel.py (4); tests/test_overnight_guard_in_place_git.py::test_tilde_script_switching_the_main_branch_still_blocked, ::test_tilde_script_operand_is_scanned_not_refused_as_unreadable; tests/replay/drivers/overnight.py:302-306 (recorded DEVIATION: refuses a harness script run through python3) | KEEP-LOCAL |
| OG-14 | :1858-1863 | any git op (but rev-parse) whose -C / cd / cwd is under main and outside every worktree. `git -C $P status` | GI | in_place own-root exemption `_set_governing_own_root` :1502 | tests/test_overnight_guard_in_place_git.py::test_isolated_session_still_blocked_at_main_root, ::test_isolated_session_cannot_git_into_main_root_via_dash_C, ::test_concurrent_*_cannot_git_into_main_root | KEEP-LOCAL |
| OG-15 | :1871-1883 | HEAD-moving git op after an unresolvable `cd`. `cd $X && git checkout foo` | GI | none | none found | KEEP-LOCAL |
| OG-16 | :1889-1897 | checkout/switch targeting main, a protected branch, or from outside a worktree. `git checkout master` | GI + `_mentions_protected_branch` | protected_branch from state | tests/test_overnight_guard_in_place_git.py::test_protected_branch_switch_refused_for_in_place_actor | KEEP-LOCAL |
| OG-17 | :1899-1905 | reset/restore/clean that could write main | GI | none | none found (reset under main fires OG-14 first, measured) | KEEP-LOCAL (`reset --hard` part also refused by git-privilege-guard, measured rc=2) |
| OG-18 | :1907-1914 | `stash apply/pop` against main / outside worktree | GI | none | none found (fires OG-14 first in main, measured) | KEEP-LOCAL |
| OG-19 | :1918-1925 | `git branch -f/-D/-M` of the protected branch. `git branch -f master HEAD` | GI | none | tests/test_overnight_guard_in_place_git.py::test_protected_branch_refused_for_in_place_actor / _isolated_actor (param :413) | **MERGE -> pretool-git-privilege-guard.py** (refuses every agent's branch force/delete/rename, measured rc=2; keeps protected-branch moves refused even under /do) |
| OG-20 | :1926-1931 | update-ref / symbolic-ref touching protected branch/HEAD. `git update-ref refs/heads/master HEAD` | GI | none | same param list (:415) | **MERGE -> pretool-git-privilege-guard.py** (measured rc=2 for update-ref and `symbolic-ref HEAD`) |
| OG-21 | :1945-1949 | `git push` naming the protected branch. `git push origin master` | GI | none | tests/test_overnight_guard_in_place_git.py::test_protected_branch_publication_refused_for_in_place_actor / _isolated_actor, ::test_push_of_a_non_protected_branch_is_not_blocked_by_this_rule | **MERGE -> pretool-git-privilege-guard.py** (refuses every agent push without the /push grant, measured rc=2). The code comment :1932-1944 keeps it deliberately as a second layer |
| OG-22 | :1950-1953 | every `git worktree ...`, read-only `list` included. `git worktree list` (rc=2) | GI | none | none found | KEEP-LOCAL but narrow to mutating subcommands (over-block measured). pretool-block-branch-pr-worktree.py allows `worktree add` inside a live /dev-overnight (measured rc=0), so this is the only overnight worktree refusal |
| OG-23 | :1956-1981, :2493-2500 | worktree_context actor, no governing state: any git/interpreter command | RX (`_GIT_TOKEN_RE`, `_INTERPRETER_LAUNCHER_RE`) | none | tests/test_overnight_guard_in_place_git.py::test_unregistered_worktree_context_write_to_main_still_blocked (shape) | KEEP-LOCAL |
| OG-24 | :2300-2340, :2359-2366 | raw write to main `.git` refs/objects/logs/packed-refs/HEAD. `echo x > $P/.git/refs/heads/master` | F + regex `open(...,'w')` + raw `>`/`tee` regex | none | tests/test_bash_write_targets_verb_narrowing.py::test_overnight_still_detected_main_checkout_and_git_metadata, ::test_overnight_no_phantom_grant_and_worktree_local | KEEP-LOCAL |
| OG-25 | :2209-2237, :2368-2390 | no bwrap: any command not provably worktree-local (F write under main outside wt, any non-harness interpreter). `echo x > $P/a.txt`, `python3 foo.py` | F + RX | harness-script exemption; `/restart` journal | hooks/tests/test_overnight_worktree_no_bwrap.py::test_other_interpreter_launches_still_fail_closed_without_bwrap, ::test_a_harness_script_launch_passes_without_bwrap; tests/test_overnight_guard_in_place_git.py::test_in_place_git_allowed_when_bwrap_boundary_unavailable; tests/replay/drivers/overnight.py:295-300 (DEVIATION) | KEEP-LOCAL. **F gap measured**: `dd if=/dev/zero of=$P/a.txt`, `truncate -s0 $P/a.txt`, `ln -sf /x $P/a.txt`, `curl -o $P/a.txt`, `echo x >\| $P/a.txt`, `git checkout HEAD -- $P/a.txt`, `git restore $P/a.txt` all rc=0 from the worktree while `echo x > $P/a.txt` is rc=2 |
| (OG-26) | :2343-2375 | not a refusal: bwrap available -> rewrites the command (updatedInput) and exits 0, skipping OG-04..06 | - | - | tests/test_overnight_guard_in_place_git.py::test_concurrent_isolated_session_bash_write_to_main_root_is_confined; tests/replay/test_kept_first_line.py | n/a |

Not Bash: Write/Edit git-config rule :2501-2505 (hooks/tests/test_overnight_git_config_write_guard.py), AskUserQuestion deny :2434-2437.

## 3. bash_write_targets.py capabilities

| id | lines | capability | used by | pinned by | class |
|---|---|---|---|---|---|
| WT-01 | :104-162 | heredoc body stripping `command_without_heredoc_bodies` | F, modes, OG-01..03, pretool-wrapper-userintent.py | doctests; hooks/tests/test_overwrite_guard.py::test_ac10_fourth_consumer_of_the_shared_module_is_pinned_too | KEEP -> shared parser |
| WT-02 | :403-435 | `--reason` payload strip `_strip_reason_payload` | F, modes, touched | tests/test_bash_write_targets_verb_narrowing.py | KEEP -> shared parser |
| WT-03 | :361-400, :483-532 | quote + comment masking (`_strip_quoted_regions`, `_strip_comment_regions`, case-block detection) | all extractors | verb_narrowing ::test_tool_policy_unmatched_quote_in_comment_does_not_suppress_write_detection, ::test_tool_policy_case_lead_heuristic_* | KEEP -> shared parser (a real tokenizer replaces it) |
| WT-04 | :534-745 | command-word neutralization (`\cp`, `/bin/cp`, `(cp ...)`, `command`/`nohup`/... prefixes, loop headers, quoted-expansion verbs) | all | verb_narrowing (28 tests), doctests | KEEP -> shared parser |
| WT-05 | :165-191 | `~`, `$HOME`, `${HOME}`, `$CLAUDE_PROJECT_DIR` resolution `_resolve_path` | all | doctests; hooks/tests/test_bash_write_targets_policy.py::test_approved_home_and_project_expansions_are_projected | KEEP |
| WT-06 | :194-242 | assignment projection `X=/p; ... > $X` -> `/p` (`_resolve_sink`) | **F only** (the mode extractor returns `$X`, measured) | test_bash_write_targets_policy.py::test_assignment_target_matrix, ::test_projection_failure_fails_closed | KEEP; inconsistency between paths |
| WT-07 | :249-345, :748-828 | FROZEN `extract_bash_write_paths`: `>`/`>>` (not `>|`, not `&>`), tee, cp/mv dest (cp -r too), `sed -i`, install | TP-09..18, OG-04..06, OG-24, OG-25, lib/attribution_journal.py:148-151 | hooks/tests/test_overwrite_guard.py::test_ac10_frozen_extractor_behaviour_unchanged, ::test_ac10_frozen_extractor_signature_and_return_shape; doctests | MERGE into shared parser (superseded by WT-08's coverage) |
| WT-08 | :846-1234 | mode extractor: adds `>|`, truncate, dd `of=`, curl `-o/--output`, wget `-O`, unlink; refuses cp -r / -t / install -d (undecidable) | only via WT-09 (TP-02..08) | test_overwrite_guard.py (iter2_*, ac10_quoted...), doctests | KEEP the target list; **the `mode`/`mechanism` labels are DEAD in production**: grep finds no hook reading `.mode`; `extract_bash_touched_paths` keeps only the path (:1263); the Bash overwrite rule they were built for is not wired (write_gate overwrite rule is `{"Write"}` only, lib/write_gate/__init__.py:82-84) |
| WT-09 | :1237-1269 | touched paths: WT-08 targets + rm/rmdir/unlink/mv operands (removed), `git rm`/`git mv` (not `--cached`), mv-into-dir entries | TP-02..08 only | doctests; test_tool_policy_protected_paths.py | KEEP |

### Capability matrix (measured by `$S/scripts/matrix.py`, module imported by path)

| form | command | extract_bash_write_paths (FROZEN :803) | extract_bash_write_targets_with_modes (:1117) | extract_bash_touched_paths (:1242) |
|---|---|---|---|---|
| > | `echo x > /tmp/a` | ['/tmp/a'] | [('/tmp/a', 'truncating')] | [('/tmp/a', False)] |
| >> | `echo x >> /tmp/a` | ['/tmp/a'] | [('/tmp/a', 'appending')] | [('/tmp/a', False)] |
| `>\|` | `echo x >\| /tmp/a` | [] | [('/tmp/a', 'truncating')] | [('/tmp/a', False)] |
| &> | `echo x &> /tmp/a` | [] | [] | [] |
| tee | `echo x \| tee /tmp/a` | ['/tmp/a'] | [('/tmp/a', 'truncating')] | [('/tmp/a', False)] |
| cp | `cp /tmp/s /tmp/a` | ['/tmp/a'] | [('/tmp/a', 'truncating')] | [('/tmp/a', False)] |
| cp -r | `cp -r /tmp/s /tmp/a` | ['/tmp/a'] | [] | [] |
| mv | `mv /tmp/s /tmp/a` | ['/tmp/a'] | [('/tmp/a', 'rename_into_place')] | [('/tmp/a', False), ('/tmp/s', True), ('/tmp/a', False), ('/tmp/a/s', True)] |
| dd of= | `dd if=/tmp/s of=/tmp/a` | [] | [('/tmp/a', 'truncating')] | [('/tmp/a', False)] |
| truncate | `truncate -s 0 /tmp/a` | [] | [('/tmp/a', 'truncating')] | [('/tmp/a', False)] |
| ln -sf | `ln -sf /tmp/s /tmp/a` | [] | [] | [] |
| rsync | `rsync -a /tmp/s /tmp/a` | [] | [] | [] |
| curl -o | `curl -o /tmp/a http://h/f` | [] | [('/tmp/a', 'truncating')] | [('/tmp/a', False)] |
| curl --output | `curl --output /tmp/a http://h/f` | [] | [('/tmp/a', 'truncating')] | [('/tmp/a', False)] |
| wget -O | `wget -O /tmp/a http://h/f` | [] | [('/tmp/a', 'truncating')] | [('/tmp/a', False)] |
| install | `install -m 755 /tmp/s /tmp/a` | ['/tmp/a'] | [('/tmp/a', 'truncating')] | [('/tmp/a', False)] |
| sed -i | `sed -i s/a/b/ /tmp/a` | ['/tmp/a'] | [('/tmp/a', 'in_place_edit')] | [('/tmp/a', False)] |
| perl -i | `perl -pi -e s/a/b/ /tmp/a` | [] | [] | [] |
| git checkout -- | `git checkout -- /tmp/a` | [] | [] | [] |
| git restore | `git restore /tmp/a` | [] | [] | [] |
| heredoc | `cat > /tmp/a <<EOF⏎hi⏎EOF` | ['/tmp/a'] | [('/tmp/a', 'truncating')] | [('/tmp/a', False)] |
| heredoc tee | `tee /tmp/a <<EOF⏎hi⏎EOF` | ['/tmp/a'] | [('/tmp/a', 'truncating')] | [('/tmp/a', False)] |
| python open w | `python3 -c "open('/tmp/a','w').write('x')"` | [] | [] | [] |
| touch | `touch /tmp/a` | [] | [] | [] |
| unlink | `unlink /tmp/a` | [] | [('/tmp/a', 'destroying')] | [('/tmp/a', False), ('/tmp/a', True)] |
| rm | `rm /tmp/a` | [] | [] | [('/tmp/a', True)] |
| chmod | `chmod 777 /tmp/a` | [] | [] | [] |
| bash -c | `bash -c 'echo x > /tmp/a'` | [] | [] | [] |
| eval | `eval 'echo x > /tmp/a'` | [] | [] | [] |
| var cmd | `X=/tmp/a; echo x > $X` | ['/tmp/a'] | [('$X', 'truncating')] | [('$X', False)] |
| mv to ~ | `mv /tmp/s ~` | ['$HOME'] | [('$HOME', 'rename_into_place')] | [('$HOME', False), ('/tmp/s', True), ('$HOME', False), ('$HOME/s', True)] |

Verdict on the claim: **confirmed**. The FROZEN extractor (:803) names nothing for `dd of=`, `truncate`, `ln -sf`,
`rsync`, `curl -o`, `git checkout -- <path>` (nor `>|`, `&>`, `wget -O`, `git restore`, `perl -i`, `touch`,
`python -c open(...,'w')`, `bash -c`/`eval` strings). The write-mode section knows `truncate` (`_TRUNCATE_WORD_RE`
:912) and `dd` (`_DD_WORD_RE` :913), plus curl/wget/unlink/`>|`; it still misses `ln -sf`, `rsync`, `git
checkout --`, `git restore`, `&>`, `perl -i`, `touch`, `python open()`. Only tool-policy's protected stage (TP-02..08)
reads the mode section; every other rule in both hooks reads the frozen one. tool-policy covers `bash -c` by
reading each `-c` layer (`_bash_texts`); the overnight guard does not (it catches `bash -c 'echo x > /home/..'` only
via OG-25's interpreter clause).

## 4. Findings

### F2 - `_HOME_PROTECTED` and a linked-worktree harness home (confirmed)

`_protected` (:1403-1410) matches `rel` of the target against the home **as a path**: `.git/config`, `.git/hooks`.
With `$HOME/.claude` a linked worktree, `$HOME/.claude/.git` is a file (`gitdir: $S/clone/.git/worktrees/-claude`),
`git rev-parse --git-dir` = `$S/clone/.git/worktrees/-claude`, `--git-common-dir` = `$S/clone/.git`. Measured (main agent):

| command | rc |
|---|---|
| `echo x > $HOME/.claude/.git/config` (meaningless path under a file) | 2 |
| `echo x > $S/clone/.git/config` (the real shared config, holds core.hooksPath) | **0** |
| `echo x > $S/clone/.git/hooks/pre-commit` | **0** |
| `rm -rf $S/clone/.git/hooks` | **0** |
| `echo x > $S/clone/.git/worktrees/-claude/config` / `config.worktree` | **0** |
| `echo 'gitdir: /tmp/evil' > $HOME/.claude/.git` (repoints the gitdir file) | **0** |
| Write tool `file_path=$S/clone/.git/config` | **0** |
| `echo x > $(git -C $HOME/.claude rev-parse --git-common-dir)/config` | 0 (unexpanded word skipped, :1498) |

Fix shape: resolve the home's git dirs once per call with `git -C <home> rev-parse --path-format=absolute --git-dir
--git-common-dir` (the overnight guard already does exactly this for its Write/Edit rule, `_targets_git_config`
:2270-2284 via `_git_query`), and protect `<git-common-dir>/config`, `<git-common-dir>/hooks/`,
`<git-dir>/config.worktree`, `<git-dir>/config` (per-worktree), plus the `<home>/.git` gitdir file itself; then
`_below(path, common_dir)` matches by realpath, independent of whether `.git` is a dir or a file. When the
command does not hold the literal path (substitution), the rule can additionally refuse an unexpanded word that
contains `rev-parse --git-(common-)dir` as OG-10's `_builds_git_dir_path` does. No test covers the worktree case
(test_tool_policy_protected_paths.py has no linked-worktree fixture; grep "worktree" there: none).

### F3 - `mv file ~` over-block

Not tool-policy (rc=0) and not the overnight guard. It is **pretool-bash-safety.sh's protected-runtime guard**
(:170-306) -> `hooks/lib/runtime_guard/_core.py` STEP0 config self-protection, `_step0_mutation_anchor_hits`
:1319-1381: stderr `[protected-runtime-guard] BLOCK STEP0: config self-protection: mutation of data file`.
Measured rc=2 for `mv /tmp/f ~`, `mv /tmp/f ~/`, `mv /tmp/f $HOME`, `mv /tmp/f <abs HOME>`, `cp /tmp/f ~`; rc=0 for
`mv /tmp/f ~/x.txt`. Why: STEP0 protects the data file `DATA_FILE_PATH` = `$HOME/.config/claude/protected-runtime.json`
(`lib/runtime_guard/config.py:39-45`) **and every ancestor directory** up to `_ANCESTOR_STOP_ROOTS`
(config.py:114-143). `/home/<user>` (or any HOME not literally `/root`, `/home`, ...) is not a stop root, so `$HOME`
itself is a protected *entry*. The mv/cp destination operand `~` is taken as the mutation target and matched
against that entry (`_path_matches_entries`, lib/runtime_guard/pathmatch.py:269-292), although moving a file
*into* a directory neither moves, removes nor re-modes the directory. Fix: for cp/mv/install whose last operand is
an existing directory (or ends in `/`), the target is `<dir>/<basename(src)>`, not `<dir>`. Pins: test_runtime_guard.py
::test_mv_ancestor_dir_blocks (:3333, intended) and `ev_nested("mv /root /backup") == "ALLOW"` (:3386); no test pins
`mv f ~` either way (grep).

### F4 - every importer / caller of bash_write_targets in hooks/

| file | symbol | calls it? |
|---|---|---|
| hooks/pretool-tool-policy.py:158,201 | `extract_bash_write_paths` | yes (TP-09..18 targets) |
| hooks/pretool-tool-policy.py:1479,1486 | `extract_bash_touched_paths` | yes (TP-02..08) |
| hooks/pretool-overnight-hook-guard.py:35-37 | `command_without_heredoc_bodies`, `extract_bash_write_paths` | yes (:616,640,664; :507,713,794,811,2226,2319) |
| hooks/pretool-cp-state-write-guard.py:28 | `extract_bash_write_paths` | **no - import only** (pinned to stay import-only by tests/test_bash_write_targets_verb_narrowing.py::test_noncaller_unchanged_cp_state_write_guard_imports_but_never_calls). The FROZEN banner :834-838 calls it a consumer "itself a security guard": stale |
| hooks/pretool-wrapper-userintent.py:48,115 | `command_without_heredoc_bodies` (local fallback def :50) | yes |
| hooks/lib/attribution_journal.py:148-151 | `extract_bash_write_paths` | yes (not named in the banner or the module docstring) |
| indirect: hooks/pretool-bash-safety.sh:327 | loads pretool-overnight-hook-guard.py as module `og` (uses `_config_key_redirects_keystone`, `_git_invocation_injects_keystone_config`), which imports bash_write_targets | transitively |

Tests importing it: hooks/tests/test_bash_write_targets_policy.py, test_c_layer_protected_targets.py,
test_overwrite_guard.py, tests/test_bash_write_targets_verb_narrowing.py. `extract_bash_write_targets_with_modes` has
no hook caller except `extract_bash_touched_paths` (grep).

### F5 - line breakdown (ast/tokenize, `$S/scripts/lines.py`)

"parse" = Bash-command reading code (functions listed in the script + module `*_RE` constants); "rule" = everything
else that is code (in tool-policy this includes ~350 lines of transcript/dispatch reading, `_Record`, /clean and
grant readers, which are not Bash parsing). "history" strict = dates, issue `#N`, commit shas, "previously", "was
added", "used to", "no longer", "FROZEN", "incident", "task 2026..."; broad = strict + provenance tags (VECTOR-n,
codex #n, fix-n, Mn, Pn-n, Dn, T2.x, round-n, lane x, A17, train n, in-flight).

| file | total | blank | `#` comment | docstring | parse code | rule code | history (strict) | history (broad) |
|---|---|---|---|---|---|---|---|---|
| hooks/pretool-tool-policy.py | 1621 | 178 | 153 | 307 | 104 | 879 | 8 | 65 |
| hooks/pretool-overnight-hook-guard.py | 2535 | 289 | 288 | 487 | 505 | 966 | 50 | 157 |
| hooks/lib/bash_write_targets.py | 1277 | 125 | 135 | 357 (incl. ~45 doctests) | 660 | 0 | 16 | 21 |

Tool-policy's three in-flight compatibility blocks (A17, :758-777, :820-841, :1507-1526) are ~60 comment lines
that state their own sunset condition.

## 5. Counts by class

- tool-policy (18 rows): KEEP-LOCAL 17 (2 with sunset: TP-13, TP-14), DEAD 1 (TP-15), MERGE 0.
- overnight guard Bash (25 refusal rows): KEEP-LOCAL 19, MERGE 5 (OG-01, OG-02 -> pretool-claude-config-guard.py;
  OG-19, OG-20, OG-21 -> pretool-git-privilege-guard.py), DEAD 1 (OG-06) + 1 dead branch inside OG-05.
- bash_write_targets (9 capabilities): KEEP/move to shared parser 8, MERGE 1 (WT-07 into WT-08's coverage); dead
  sub-part: WT-08 mode labels; dead import: cp-state guard.
- GITHUB: none.
