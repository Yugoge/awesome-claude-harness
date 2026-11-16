# P14 sharing: logic implemented more than once (beyond reading Bash)

Locations are on the checked-out tree of `claude/p14-bash-safety-plan`. "Measured" line counts are sums of the cited ranges. "Est." marks an estimate.

## Summary

1. Fourteen clusters outside Bash parsing exist in two to forty-one copies. Together they hold about 1,500 duplicated lines. About 850 of them are measured.
2. Several copies disagree in ways that change decisions. Naive timestamps on grants are read three ways. Hook output is combined four ways, and one way does not treat a JSON `deny` as a refusal. Session ids are read in two orders. `registered_hooks` is counted two ways.
3. On every Bash call, bash-safety loads the whole overnight guard (2,535 lines) to call three of its symbols. That costs 70 to 100 ms warm, measured.
4. Eleven future lanes, `P14-S1` to `P14-S11`, are proposed. Most wait for a P14 lane or an open PR on the same file. The best ratios are in the doc counters, the atomic writer, git subprocess calls, and output combining.
5. Five small items fit inside existing P14 lanes without widening them: P14-5, P14-6, P14-10, P14-11 and P14-12 (section 4). Everything else is future work.

## 1. Ranked clusters

"Saved" means duplicated lines minus the estimated module size and the lines left at call sites. Risk: 1 is low, 2 is medium, 3 is high. Ratio is saved divided by risk.

| Rank | Cluster | Copies | Dup lines | Saved | Risk | Ratio | Lane |
|---|---|---|---|---|---|---|---|
| 1 | G. Harness-switch header | 41 Py + 15 sh | 369 (measured, Py) | ~205 (est.) | 1 | 205 | S11 (last) |
| 2 | K. Doc counters and generators | 3 + 2 | ~85 (est.) | ~60 (est.) | 1 | 60 | S10 |
| 3 | I. Git subprocess helpers | ~20 | 83 measured (hooks, push scripts) + ~80 est. (other scripts) | ~100 (est.) | 2 | 50 | S4 |
| 4 | H. Atomic file write | 10 | 136 (measured, 8 copies) | ~85 (est.) | 2 | 42 | S8 |
| 5 | C. Hook output combining | 4 | 238 (measured) | ~113 (est.) | 3 | 38 | S1 |
| 6 | J. Protected-path sets | 7 | 248 (measured) | ~100 (est.) | 3 | 33 | S9 |
| 7 | N. Transcript lazy reader (tool-policy `_Record`) | 2 | 142 + ~60 | ~80 (est.) | 2 | 40 | (folded into S5) |
| 8 | B. Grant expiry parsing | 6 | 75 (measured) | ~46 | 2 | 23 | S2 |
| 9 | E. Subagent detection | 3 (+65 inline `agent_id` tests) | 43 (measured) | ~41 | 2 | 20 | S6 |
| 10 | D. Session paths and session id | ~45 sites | ~87 (62 measured) | ~30 (est.) | 2 | 15 | S5 |
| 11 | A. Push-gate token and repo hash | 10 | 77 (measured) | ~20 | 2 | 10 | S3 |
| 12 | F. Harness-home resolvers | 7 | ~15 | ~12 | 2 | 6 | (folded into S5) |
| 13 | M. Keystone config predicate loaded from the overnight guard | 1 cross-file load | 0 | 0 lines; 70-100 ms per Bash call | 2 | n/a (speed) | S7 |
| 14 | L. Stdin payload read, fail-open `__main__` wrappers, locks | 56 / 12 / 18 | ~200 (est.) | low | 2 | low | none |

Cluster N is ranked near A to F by ratio but is folded into S5, since both touch the same session-record readers. Cluster L is not worth a lane. Each copy encodes its own hook's fail direction, which is a decision, not shared logic.

## 2. Clusters in detail

### A. Push-gate token and repository hash

The token readers:
- `hooks/push.sh:203-240`: finds candidates at depth 1 and 2, newest first, and tests ancestry against HEAD. It runs one `python3 -c` per candidate.
- `hooks/stop-command-gate.py:759-766`: gets the path from the writer's own `token_path`, then tests ancestry against the commit under test.
- `scripts/execute-push.py:83-95`: rebuilds the path by hand and checks that `commit_sha` is a string.
- `hooks/pretool-tool-policy.py:1389-1400`: holds the tree layout (`agentic-commit/push`, `push-analyst/<hash>/<sid>/<req>.json`) for protection.

The writer is `scripts/write-push-gate-token.py:79-83` (`token_path`).

The repo hash `sha256(realpath(root))[:16]` is spelled at:
- `scripts/write-push-gate-token.py:80`;
- `hooks/lib/merge_grant.py:65`, `:94`;
- `scripts/execute-push.py:190`;
- `hooks/push.sh:105`, `:205`;
- `scripts/steps/push-snapshot.py:69` and `scripts/steps/merge-snapshot.py:71`, with no `realpath`.

How the copies differ:
- push.sh puts `${_REPO_ROOT}` and `${_BRANCH_RAW}` inside Python source in single quotes (`:205`, `:207`). A path or branch name that holds `'` breaks the read.
- push.sh takes the branch from `rev-parse --abbrev-ref HEAD`, which gives `HEAD` when detached. The gate takes the branch it is given.
- The two step scripts hash the path as given. On a symlinked checkout they give a different hash from the writer.
- The plan already lists this cluster (P14 section 7, item 11): "they differ on symlinks, branch and ancestry base".
- The writer is the right copy for the path. The gate is the right copy for the ancestry base, because it tests a named commit.

Module: `hooks/lib/push_token.py`:
- `repo_hash(root) -> str`;
- `token_path(root, branch, sid)`;
- `candidates(root, branch) -> list[Path]`, newest first;
- `names_ancestor(root, branch, commit) -> Path | None`;
- a CLI `names-ancestor <root> <branch> <commit>` for push.sh.

The writer and `merge_grant` import `repo_hash` from it.

Saved: 77 duplicated lines, minus about 45 for the module and 12 left at call sites, gives about 20. The gain is correctness, not size. Risk 2: the push decision. push.sh is the `/push` script, not a hook, so no live session keeps an old copy of it.

### B. Grant expiry parsing

The copies:
- `hooks/lib/allowlist.py:214-231`;
- `hooks/pretool-git-privilege-guard.py:1159-1166` (`_end_time_passed`);
- `hooks/pretool-overnight-hook-guard.py:70-80` (`_expires_passed`);
- `hooks/lib/merge_grant.py:114-119`;
- `hooks/pretool-bash-safety.sh:606-618` (the daemon-grant consumer);
- `scripts/execute-push.py:319-337`;
- `scripts/paseo-daemon-ledger.py` `parse_aware` and `scripts/break-overnight-lock.py:67`, which use different formats.

How they differ on a timestamp with no time zone ("naive"):
- The privilege guard, the overnight guard and allowlist compare it with local time.
- bash-safety reads it as UTC.
- merge_grant and execute-push refuse it.
- With TZ=UTC all of these agree. On a machine with another TZ, a naive grant lives hours longer or shorter.
- allowlist also accepts epoch numbers, which its own writer produces (`allowlist.py:181-187`).
- Every other writer stamps aware UTC (`write-commit-grant.py:486`, `write-git-residual-override.py:102`, `write-bulk-commit-sentinel.py:90`).

The right rule is merge_grant's: refuse a naive time, and fail closed on a parse error. Keep allowlist's epoch form.

Module: `hooks/lib/grant_time.py` with `expired(value, now=None) -> bool`. It accepts aware ISO-8601 or epoch numbers; anything else counts as expired.

Saved: 75 duplicated lines, minus about 20 for the module and 9 at call sites, gives about 46. Risk 2: a decision changes only for a naive timestamp. None of the harness writers produces one.

### C. Hook output combining

The copies:
- `hooks/lib/hook_launch.py:106-115, 134-210` (`combine`, used by the `*-launch.py` dispatchers);
- `hooks/lib/write_gate/__init__.py:105-210` (`combine`, used by `pretool-write-gate.py`);
- `hooks/lib/gate_runner.py:194-238` (`report`, used by `pretool-dispatch-gate.py`, `subagentstop-producer-gate.py` and `posttool-dispatch-record.py`);
- `hooks/lib/hook_launch_fallback.py:72-97` (`minimal`).

How they differ:
- **A JSON `permissionDecision: deny` (or `decision: block`) on exit 0.** hook_launch, write_gate and the fallback treat it as a refusal. gate_runner does not: only exit 2 refuses there (`gate_runner.py:215-222`).
- **Several JSON answers.** gate_runner merges only objects whose single key is `hookSpecificOutput` with an `additionalContext`. Any other mix is written out as concatenated stdouts (`:224-229`), and the CLI cannot parse two JSON objects in a row.
- **`continue: false`, `systemMessage`, `suppressOutput`, plain-text context events.** Only hook_launch handles them. write_gate is PreToolUse only and drops them.
- **Rule failure.** write_gate has per-rule `fail: closed`. The others treat an error as non-blocking.

The right copy is hook_launch's `combine`, plus write_gate's per-rule fail-closed tally. gate_runner's behaviour on a stdout deny is a defect. Whether any of its rules prints such JSON must be checked before unifying.

Module: `hooks/lib/hook_output.py` with `combine(event, results, fail_closed=frozenset()) -> (code, stdout, stderr)`. It must stay stdlib only. The fallback keeps `minimal` as its last resort and calls `hook_output.combine` when that imports.

Saved: 238 duplicated lines, minus about 110 for the module and 15 for adapters, gives about 113. Risk 3: every hook decision passes through a combiner. Live sessions keep the old launcher list but load the module fresh, so a defect reaches running sessions at once.

Frozen: `hooks/lib/hook_launch.py` (parallel-launcher PR).

### D. Session paths and session id

**Parent transcript from a subagent transcript** (`<sid>/subagents/agent-x.jsonl` to `<sid>.jsonl`):
- `hooks/pretool-tool-policy.py:527-537`;
- `hooks/pretool-claude-config-guard.py:219-221`, which uses `with_suffix` and so differs when a session id holds a dot;
- `hooks/pretool-overnight-hook-guard.py:2418-2419`.

**Subagent files from the parent transcript:**
- `hooks/lib/declared_paths.py:228-233` (`_agent_files`, with an id check);
- `hooks/lib/commit_pipeline.py:610-622` (no id check);
- `hooks/lib/subagent_restart.py:583`, `:823` (`with_suffix("")`);
- `hooks/lib/obligation.py:841-858` (from the slug and every account root).

**Config dir** (`CLAUDE_CONFIG_DIR or ~/.claude`): `subagent_restart.config_dir` (`:196-198`) and 10 inline copies:
- `hooks/pretool-workflow-gate.py:67`;
- `hooks/pretool-harness-switch-guard.py:71`;
- `hooks/userprompt-doc-sync-check.py:33`;
- `hooks/prompt-workflow.py:228`, `:696`;
- `hooks/pretool-tool-policy.py:1492`;
- `hooks/lib/score_log.py:85`;
- `scripts/execute-push.py:130`;
- `scripts/capability-handshake.py:91`;
- `scripts/seal-attribution-journal.py:69`.

**Project dir:** 65 reads in 45 files, in three orders:
- env, else cwd;
- env, else payload `cwd`, else cwd;
- payload `cwd` first (`pretool-tool-policy.py:1491`, `declared_paths.py:632`).

The form `.get("CLAUDE_PROJECT_DIR", os.getcwd())` treats a set but empty variable as the project. The form with `or` falls back.

**Session id:** three helpers that are the same (`pretool-git-privilege-guard.py:375-385`, `pretool-block-branch-pr-worktree.py:833-837`, `pretool-wrapper-userintent.py:93-97`) and about 30 inline reads. They differ in two ways:
- **Env order.** `write-push-gate-token.py:75` prefers `CLAUDE_CODE_SESSION_ID`. `write-commit-grant.py:350`, `execute-push.py:275` and `write-bulk-commit-sentinel.py:70` prefer `CLAUDE_SESSION_ID`.
- **Fallback value.** `default` in `pretool-read-size-guard.py:70`, `posttool-allowlist-consume.py:200`, `posttool-runcode-watchdog.py:78` and `write_gate/overwrite.py:120`; `unknown` in `write-push-gate-token.py:76`; empty elsewhere.

When both variables are set to different values, a writer and a reader key different files. With `default`, all sessions without an id share one key.

The right rules:
- Session id: the payload's id, then one env order used by every writer, then empty. No `default`.
- Base directory for a relative path: payload `cwd` first.
- Project root: env first.

Module: `hooks/lib/session_paths.py`:
- `config_dir()` and `account_project_roots()` (moved from subagent_restart);
- `session_transcript(payload)`;
- `agent_files(transcript, agent_id)`;
- `session_id(payload=None)`;
- `project_dir(payload=None)`;
- `base_dir(payload)`.

Saved: about 87 duplicated lines (62 measured), giving about 30 (est.). The gain is agreement between writers and readers. Risk 2: grant and sentinel keys move only when the two variables differ.

Frozen: the overnight guard sites.

### E. Subagent detection

The canonical copy is `hooks/lib/subagent.py:66-84` (`is_subagent_context`). The others:
- `hooks/pretool-workflow-gate.py:234-270` (`codex_payload_is_subagent_context`, with its own `session_meta` scan, which repeats `subagent.py:41-63`);
- `hooks/pretool-cp-state-write-guard.py:126-131` (`agent_id` or a top-level `subagent_type`);
- 65 inline `.get("agent_id")` tests in 33 files.

How they differ:
- The workflow gate also counts `parent_thread_id` and `parent_session_id`, but not `CLAUDE_COMPAT_RUNTIME`.
- The workflow gate tests truthiness. `subagent._truthy` rejects `"0"` and `"false"`.
- The cp-state guard counts a top-level `subagent_type`, which `subagent.py:1-8` and `agent_resolver.py:17` say is no role.

`subagent.py` is the right copy, with the two Codex keys added. The 65 inline tests are deliberate, as `subagent.py:5-6` says. Changing them is an owner decision and not part of this lane.

Saved: 43 duplicated lines, minus 2, gives about 41. Risk 2: payloads that carry only a Codex alias.

### F. Harness-home resolvers

The resolvers:
- `hooks/lib/claude_home.py:138-166` (structural walk; an env hint is used only when it equals the walk);
- `hooks/lib/harness_switch.py:23-24` (three `dirname`s; deliberately import free);
- `hooks/lib/capability_state.py:189-196` (`CLAUDE_HOME` taken unchecked);
- `hooks/pretool-overnight-hook-guard.py:1632`, `:2252` (`CLAUDE_HOME` unchecked, else `abspath`, so symlinks are not resolved);
- `hooks/pretool-claude-config-guard.py:213`, `:284` (`CLAUDE_HOME` or `~/.claude`);
- `scripts/steps/pull-run.py:92` and `scripts/steps/commit-plan.py:112`.

`claude_home.resolve` is the right copy. `harness_switch` stays as it is by design.

Saved: about 12. Risk 2: the overnight guard's harness-script exemption reads this home. These sites fold into S5.

### G. Harness-switch header

Forty-one Python hooks repeat the same 9-line preamble (for example `hooks/pretool-read-size-guard.py:9-17`). Fifteen shell files repeat a 1-line source.

How they differ:
- `pretool-harness-switch-guard.py:28-30` has no `ImportError` guard, so with no `lib/` it ends with exit 1, a non-blocking error.
- The shell twin (`harness_switch.sh:11-12`) strips the literal suffix `/hooks/lib`. The Python one goes up three levels whatever the names are.

The header must stay import-free and come first, so it cannot become one shared import. It can shrink from 9 lines to 4, using one-line `try`/`except`/`finally` suites.

Saved: about 205 (est.). Risk 1. It touches 41 files, including files in every P14 lane and every frozen file, so it must run last.

### H. Atomic file write

The copies:
- `hooks/prompt-workflow.py:156-182` (`O_EXCL` temp file, fsync, fsync of the directory);
- `hooks/lib/subagent_restart.py:347-366` (`mkstemp`, fsync, mode 0600);
- `scripts/aggregate-dev-report.py:1038-1058` (fsync);
- `scripts/spec-check.py:192-228` (`O_EXCL` with retry, keeps the file mode, fsync);
- `scripts/paseo-daemon-ledger.py:173-176` (fixed temp name `<name>.tmp`, no fsync);
- `scripts/lib/session_index.py:115-119` (temp `.tmp-<pid>`, no fsync);
- `hooks/lib/allowlist.py:188-196` (mode 0600, no fsync);
- `scripts/write-push-gate-token.py:130-142` (`mkstemp`, no fsync);
- `scripts/paseo-daemon-timers.py:246` and `scripts/install/installer.py:1027`.

The ledger's fixed temp name lets two writers interleave. `spec-check._atomic_write_text` is the most complete copy.

Module: `hooks/lib/atomic_io.py` with `write_bytes(path, data, mode=None, fsync=True)` and `write_json(path, value, **dumps)`.

Saved: 136 duplicated lines, minus about 35 for the module and 16 at call sites, gives about 85 (est.). Risk 2: file modes, and fsync latency in hot hooks (prompt-workflow already pays it). Keep `installer.py` out, because it runs before the harness is installed.

### I. Git subprocess helpers

The copies in hooks:
- `hooks/stop-command-gate.py:89-93` (timeout 20; sets `GIT_NO_REPLACE_OBJECTS=1` and `GIT_GRAFT_FILE=/dev/null`, `:86`; does not catch timeouts);
- `hooks/pretool-overnight-hook-guard.py:2059-2069` (timeout 10; removes `CLAUDE_OVERNIGHT_ACTOR`);
- `hooks/lib/overnight.py:181-187` (timeout 5; empty output counts as `None`);
- `hooks/lib/dev_loop_checks.py:137-142` (returns stdout even when git fails);
- `hooks/pretool-git-privilege-guard.py:551-570`, `:801-809` (timeout 5, runs in cwd);
- `hooks/lib/merge_grant.py:71-77` (timeout 10);
- `hooks/prompt-workflow.py:1715-1717` (timeout 5, uncaught).

The copies in scripts:
- `scripts/write-push-gate-token.py:64-71`;
- `scripts/execute-push.py:74-80` (timeout 20, uncaught);
- about ten more (`readme_facts.py:91`, `generate-hero-status.py:155`, `size-ratchet.py:28`, `steps/*.py`, `resolve-commit-repos.py:57`, `stage-owned-hunks.py:110`, ...).

The difference that matters: only stop-command-gate ignores replace refs and grafts. Every reader that tests ancestry for a decision is open to a planted `refs/replace/*`:
- `push.sh:235`;
- `execute-push.py:93`;
- the privilege guard's HEAD checks;
- `merge_grant`'s tips.

The right copy is stop-command-gate's environment, plus explicit error handling.

Module: `hooks/lib/git_run.py` with `git(cwd, *args, timeout=10, facts=True) -> str | None` (`facts` sets the two variables) and `ok(cwd, *args) -> bool`.

Saved: about 100 (est.; 83 measured in hooks and push scripts). Risk 2: decisions change only when a repository holds replace refs or grafts. Pin that with a test.

### J. Protected-path sets

The sets:
- `hooks/pretool-tool-policy.py:1364-1438`: `_HOME_PROTECTED` at `:1371-1373`; `_below`; `_push_input`; `_protected` covers home files, transcripts and agent meta, the score log, `/do` sidecars, push tokens and push-analyst grants.
- `hooks/pretool-harness-switch-guard.py:36-38, 66-77`: the home's and config dir's `settings*.json`, `.harness-switch/`, and the `.hook-refactor-allow` sentinel.
- `hooks/pretool-claude-config-guard.py:51-100`: `.claude/hooks/` and `.claude/commands/` by substring, the same sentinel at `:79-81`, and home spellings at `:103-157`.
- `hooks/pretool-cp-state-write-guard.py:32-79`: cp-state globs and shape.
- `hooks/pretool-overnight-hook-guard.py:93-125`: state-dir prefixes and `overnight-state-`.
- `hooks/pretool-overnight-hook-guard.py:2270-2284`: `config` and `config.worktree` of any git dir, by asking git.
- `hooks/pretool-bash-safety.sh:26-37`: user-intent, dispatch-attest, commit-grant and daemon-grant name regexes over raw text.

Path containment is written three times:
- tool-policy `_below` (`:1376-1385`, the written or the real form);
- overnight `_path_under_prefix` (`:83-91`, real forms only);
- merge_grant `is_grant_path` (`:43-49`, `abspath` only).

How the sets differ:
- tool-policy protects `.git/config` and `.git/hooks` of the home only. The overnight guard protects any checkout's git config, but only overnight. The plan's linked-worktree gap (P14 1.7) comes from this split.
- bash-safety protects `claude-commit-grant-*`, `claude-commit-userintent-*` and `claude-commit-dispatch-*` from Bash writes. tool-policy's `_protected` does not list them, so a Write-tool write of them is caught only by later checks (the grant's `minted_by` provenance).
- The daemon grant lives under `CLAUDE_TMPDIR` (`pretool-bash-safety.sh:25`). `harness_state_dir.py:12-15` says a per-session directory makes a writer and a reader disagree.

Module: `hooks/lib/protected_paths.py`:
- `roots(payload) -> (home, config, state)`;
- `below(path, root) -> str | None`, the one containment rule;
- `kind(path, removed=False) -> str | None`, which only names what the file is.

Each guard keeps its own rule on who may write which kind. This module moves the existing sets; it adds none.

Saved: 248 duplicated lines, minus about 120 for the module and 30 at call sites, gives about 100 (est.). Risk 3: every write decision.

Frozen: the overnight guard and the harness-switch guard.

### K. Doc counters and generators

The hook registration count is computed three ways:
- `scripts/readme_facts.py:507-531` (launchers expanded);
- `scripts/check-enforcement-evidence.py:315-345` (launchers expanded; its own `expand_launchers` loader, like `readme_facts.py:517-522`);
- `scripts/size-ratchet.py:53-58` (raw command entries, so a launcher counts as one).

So `registered_hooks` in the size budget and the hook count in the README measure different things under similar names.

INDEX.md is generated twice:
- `hooks/doc_sync/regen_index.py` (git-tracked files);
- `scripts/generate-folder-index.sh:25-46` (every file `find` sees, `__pycache__` included).

Both write through `hooks/doc_sync/folder_doc.py`, but with different lists of files. `scripts/check-readme-freshness.sh:63-66` counts a third way (`find`, minus `venv` and `__pycache__`).

`readme_facts` and `generate-hero-status.py` already share one fact source. `verify-claims.sh` retired its own counts (`:18-20`).

Module: none is new.
- `hooks/lib/launch_settings.py` gains `expand_file(root, settings)`.
- `readme_facts.hook_registrations(root, expand=True)` becomes the one counter.
- `generate-folder-index.sh` calls `doc_sync.regen_index`.

Saved: about 60 (est.). Risk 1, but the owner must decide what `registered_hooks` means. If it changes, `policies/size-budget.v1.json` changes in the same lane.

### M. Keystone config predicate

`hooks/pretool-bash-safety.sh:325-327` runs `exec_module` on all of `pretool-overnight-hook-guard.py` on every Bash call. It uses only `_git_invocation_injects_keystone_config` (`:1108`), `_config_key_redirects_keystone` and `_GIT_HOOK_SUPPRESS_RE`.

Measured with a throwaway HOME: 71 to 103 ms per load warm, 426 ms cold. It brings 210 modules into the process.

Module: `hooks/lib/keystone_config.py`, the existing key test moved out of the guard unchanged. Both the guard and `bash_safety_rules.py` import it.

Saved: 0 lines and about 0.1 s per Bash call. Risk 2: the 850 commit-bypass cases.

Frozen: the overnight guard (keystone PR).

### N. Transcript readers

These readers are already partly shared through `hooks/lib/command_span.py` (`_Lines`, `_records`, `_piece`, `active_span`). The private copies left:
- `hooks/pretool-tool-policy.py:550-691` (`_Record`: reads pieces forward and backward, `find_call`, `command_before`);
- `hooks/pretool-workflow-gate.py:646-657` (`_transcript_events`, whole file, fails on any bad line);
- `hooks/pretool-workflow-gate.py:249-270` and `hooks/lib/subagent.py:41-63` (the same `session_meta` scan, cluster E);
- `scripts/execute-push.py:137-170` (a raw scan of every subagent transcript).

`_Record` exists for speed on 100 MB transcripts. Moving it into `command_span` as its lazy reader keeps that speed.

Saved: about 80 (est.). Risk 2: the derived permission is on tool-policy's hot write path. Pin it with `test_span_lazy_reader.py` and `test_tool_policy_derived_permission.py`.

### L. Not worth sharing

- **Stdin payload reads (56 hooks).** On a bad payload, a hook exits 0, returns `{}`, or refuses. That is each hook's fail direction, and it should stay visible where it is decided.
- **Fail-open `__main__` wrappers (12 hooks).** Same reason.
- **flock users (18 files).** They lock different files with different timeouts. Sharing would save little.

## 3. Proposed future lanes

Each lane is one issue. Every lane has the same baseline acceptance:
- every hook decision is unchanged, except the changes the lane names, each pinned by a new test;
- the named tests and the replay decision diff (`harness-repair-plan/tools/p14/dump_replay_decisions.py`) are taken against a baseline recorded before the change;
- the artifact check stays at 0;
- no new special-case list.

| Lane | Issue | File scope | Acceptance (tests) | Order |
|---|---|---|---|---|
| P14-S1 | One hook-output combiner | new `hooks/lib/hook_output.py`; `hooks/lib/hook_launch.py`, `hooks/lib/hook_launch_fallback.py`, `hooks/lib/write_gate/__init__.py`, `hooks/lib/gate_runner.py` | `test_hook_launch.py`, `test_write_gate.py`, `test_write_gate_overwrite_parity.py`, `test_one_process_gates.py`, `test_hook_output_reaches_model.py`, `test_stop_launch.py`. The stdout deny and multi-JSON cases in gate_runner are pinned. If any gate_runner rule prints a deny on exit 0 today, that change is listed. | After the parallel-launcher PR. Before S11. |
| P14-S2 | One grant-expiry rule | new `hooks/lib/grant_time.py`; `hooks/lib/allowlist.py`, `hooks/lib/merge_grant.py`, `hooks/pretool-git-privilege-guard.py`, `scripts/execute-push.py` | `test_allowlist_consolidation.py`, `test_merge_grant_write_check.py`, `test_grant_binding.py`, `test_privilege_guard_fails_closed.py`, `test_bulk_commit_sentinel.py`. A naive timestamp is pinned as expired. | After P14-4 and P14-9. The overnight copy follows in S7. The bash-safety copy goes in P14-5 (section 4). |
| P14-S3 | One push-gate token reader | new `hooks/lib/push_token.py`; `hooks/push.sh`, `hooks/stop-command-gate.py`, `scripts/execute-push.py`, `scripts/write-push-gate-token.py`, `scripts/steps/push-snapshot.py`, `scripts/steps/merge-snapshot.py` | `test_write_push_gate_token.py`, `test_push_typed_remote.py`, `test_inflight_push_route.py`, `test_stop_command_gate.py`, `test_push_gate_ancestor_cross_session.sh`, `test_push_sentinel_abort.sh`. New cases: a symlinked repo root, a branch with `'`, a detached HEAD. | After S4 (it uses `git_run`). tool-policy's `_push_input` switches over in S9. |
| P14-S4 | One git subprocess helper | new `hooks/lib/git_run.py`; `hooks/stop-command-gate.py`, `hooks/lib/overnight.py`, `hooks/lib/dev_loop_checks.py`, `hooks/lib/merge_grant.py`, `hooks/prompt-workflow.py`, `scripts/write-push-gate-token.py`, `scripts/execute-push.py` | `test_stop_command_gate.py`, `test_dev_loop_checks.py`, `test_overnight_window.py`, `test_merge_grant_write_check.py`. New case: a replace ref that fakes ancestry is ignored. | Any time. The privilege guard and the overnight guard switch over after P14-4 and P14-11. |
| P14-S5 | Session paths, session id, home and transcript reader | new `hooks/lib/session_paths.py`; `hooks/lib/subagent_restart.py`, `hooks/lib/declared_paths.py`, `hooks/lib/commit_pipeline.py`, `hooks/lib/score_log.py`, `hooks/lib/capability_state.py`, `hooks/lib/command_span.py` (gains the lazy reader), `hooks/pretool-claude-config-guard.py`, `hooks/pretool-workflow-gate.py`, `hooks/userprompt-doc-sync-check.py`, `scripts/write-*.py`, `scripts/execute-push.py` | `test_declaring_dispatch.py`, `test_cli_role_own_cycle.py`, `test_g2_file_lists.py`, `test_span_lazy_reader.py`, `test_command_span.py`, `test_claude_config_guard.py`, `test_write_push_gate_token.py`, `test_env_configured_defaults.py`. New case: both session variables set and different gives one key for writer and reader. | tool-policy (`_session_transcript`, `_Record`) after P14-6. The privilege guard, branch-pr and wrapper-userintent session-id helpers after P14-4, P14-8 and P14-10. The overnight sites after P14-11. |
| P14-S6 | One subagent test | `hooks/lib/subagent.py`, `hooks/pretool-workflow-gate.py`, `hooks/pretool-cp-state-write-guard.py` | `test_write_gate.py`, `test_stop_launch.py`, `test_dual_runtime_lifecycle_e2e.py`, `test_checklist_record.py`, `test_overwrite_guard.py`. New cases: the Codex aliases, a `"0"` value, a top-level `subagent_type`. | cp-state guard after P14-10. |
| P14-S7 | Keystone key test out of the overnight guard | new `hooks/lib/keystone_config.py`; `hooks/pretool-overnight-hook-guard.py`, `hooks/lib/bash_safety_rules.py` (or `pretool-bash-safety.sh` if P14-5 has not landed) | `test_commit_hook_bypass_deny.py` (850 cases), `test_overnight_git_config_write_guard.py`, `test_overnight_worktree_config_file.py`, `test_env_configured_defaults.py`. Report the time per Bash call before and after. Also moves `_expires_passed` onto `grant_time`. | After the keystone PR, P14-5 and P14-11. |
| P14-S8 | One atomic writer | new `hooks/lib/atomic_io.py`; `hooks/prompt-workflow.py`, `hooks/lib/subagent_restart.py`, `hooks/lib/allowlist.py` (writer only), `scripts/aggregate-dev-report.py`, `scripts/spec-check.py`, `scripts/paseo-daemon-ledger.py`, `scripts/paseo-daemon-timers.py`, `scripts/lib/session_index.py`, `scripts/write-push-gate-token.py` | `test_cp_checkin.py`, `test_allowlist_consolidation.py`, `tests/test_paseo_daemon_ledger.py`, `test_write_push_gate_token.py`. File modes are pinned per writer. | After P14-9 (allowlist). |
| P14-S9 | Protected-path kinds in one module | new `hooks/lib/protected_paths.py`; `hooks/pretool-tool-policy.py`, `hooks/pretool-claude-config-guard.py`, `hooks/pretool-cp-state-write-guard.py`, `hooks/pretool-harness-switch-guard.py`, `hooks/pretool-overnight-hook-guard.py`, `hooks/lib/bash_safety_rules.py` | `test_tool_policy_protected_paths.py`, `test_claude_config_guard.py`, `test_claude_config_guard_home_spellings.py`, `test_c_layer_protected_targets.py`, `test_overnight_state_file_write_guard.py`, `test_overnight_git_config_write_guard.py`, `tests/test_harness_switch.py`. Any kind newly covered for a tool (for example the commit-grant files for Write) is an owner decision and pinned. | Last of the hook lanes: after P14-5, P14-6, P14-10, P14-11, P14-12, the keystone PR and the settings-switch PR. After S3. |
| P14-S10 | One registration counter; one INDEX generator | `scripts/readme_facts.py`, `scripts/check-enforcement-evidence.py`, `scripts/size-ratchet.py`, `hooks/lib/launch_settings.py`, `scripts/generate-folder-index.sh`, `policies/size-budget.v1.json` if needed | `tests/test_readme_facts.py`, `tests/test_size_ratchet.py`, `test_doc_sync_folder_doc.py`, `test_doc_sync_regen_readme_status.py`. Owner decision first: what `registered_hooks` counts. | Any time. Not touched by P14. |
| P14-S11 | Harness-switch header to 4 lines | the 41 Python hooks with the 9-line header, and `hooks/pretool-harness-switch-guard.py:28-30` | `tests/test_harness_switch.py`, `test_stop_launch.py`, `test_hook_launch.py`. New case: a hook copied without `lib/` still runs. | Last: after P14-13 and every S lane, because it touches every hook file. |

## 4. What fits inside P14's existing lanes

Each item below touches only files the lane already owns. Each is part of moving that file onto the shared parser or deleting what the lane deletes, so the lane does not widen.

| Lane | Item | Why it fits |
|---|---|---|
| P14-5 | The daemon-grant consumer (`pretool-bash-safety.sh:522-640`), with its private expiry parse (`:606-618`), its session-id `python3 -c` (`:538-541`) and its flock: B's bash-safety copy | P14-5 deletes BS-09 and BS-10 (MERGE into runtime_guard) and rewrites the rest into `bash_safety_rules.py`. The copy goes away with them. If BS-13 survives, its grant read uses the lane's own rules module. |
| P14-6 | `pretool-tool-policy.py:1494-1497`: the path word's own `${V:-d}` and `expandvars` expansion | Reading a write target's word is the parser's `write_targets` (with assignment projection). That replaces this expansion inside the lane's file. |
| P14-10 | `pretool-cp-state-write-guard.py:28` imports `extract_bash_write_paths` and never calls it. That costs about 10 ms per write-tool call (measured). | The lane retires `bash_write_targets` from this file. Dropping the dead import is that change. |
| P14-11 | Overnight guard: the `_CHANNEL_RE` path-word expansion (`:1463`, `:1632-1636`, `:2252-2253`) and the `_HARNESS_LAUNCH_RE` interpreter-launch scan (`:2245-2267`) | Both read words of a Bash command. The lane puts the guard's Bash path on the parser. |
| P14-12 | Harness-switch guard: `_resolve`'s `expandvars` (`:61-63`) and `_segments` (`:96-123`) | The lane puts this guard on the parser (the plan already lists `echo x>settings.json`). |

Everything else in section 3 is a future lane. That covers:
- moving a shared set or helper into `hooks/lib/`;
- every change to the privilege guard, `allowlist.py` or tool-policy beyond the rows above;
- `claude-config-guard`, which is in no P14 lane.

Moving `claude-config-guard`'s home-spelling expansion (`:103-157`) onto the parser is part of S9. That file is in no P14 lane (P14 section 5).

## 5. Frozen files

| Frozen file (open PR) | Clusters waiting on it |
|---|---|
| `hooks/pretool-overnight-hook-guard.py` (keystone PR) | B, D, F, I, J, M (S2 tail, S4 tail, S5 tail, S7, S9) |
| `hooks/pretool-harness-switch-guard.py` (settings-switch PR) | D, J, G (S5 tail, S9, S11) |
| `hooks/lib/hook_launch.py` (parallel-launcher PR) | C (S1) |
| `hooks/lib/bash_write_targets.py` (keystone PR) | none: only P14-10 touches it |
| `tests/replay/drivers/` (#29) | none: S lanes add no DEVIATION entries |

## 6. Risks common to all lanes

- **Live sessions.** A running session keeps the hook list it loaded, but it imports `hooks/lib/` modules fresh on each call. So a new shared module reaches running sessions at once, while a renamed or deleted hook file does not. Keep every hook path and every old public function name (as a thin alias) until P14-13.
- **Shell hooks.** `push.sh`, `pretool-bash-safety.sh` and `userprompt-consent-allowlist.sh` cannot import Python. They get one CLI entry per module (`python3 hooks/lib/<module>.py <verb>`), one start per call, never one per candidate.
- **Import cost in hot hooks.** Every new module is stdlib only and imports nothing heavy at module level. Measured: `harness_switch`, `subagent` and `claude_home` together load in about 10 ms. The overnight guard takes 70 to 100 ms.
- **Decision changes.** Each copy that is wrong (the naive timestamp, the gate_runner stdout deny, the replace refs, the session-id order, the cp-state `subagent_type`) changes a decision once it is unified. Each one is listed in its lane and pinned by a test. The 65 inline `agent_id` tests and the meaning of `registered_hooks` are owner decisions.
