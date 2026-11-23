# Harness temp state inventory

> Last updated: 2026-11-21

Every file or directory the harness itself keeps under `/tmp`, `/var/tmp` or `$TMPDIR`,
with the `path:line` that creates or reads it. `hooks/lib/harness_temp_state.py` is the one
definition of this list: `LOCATIONS` holds one entry per row below (the **Location** column),
`classify(path)` answers which entry a path is, `is_harness_state(path)` whether it is control
state, and `temp_roots()` / `is_in_temp_root(path)` what counts as a temp root. The write gate's
overwrite rule (`hooks/lib/write_gate/overwrite_scope.py`) and the tool policy's `_protected`
(`hooks/pretool-tool-policy.py`, the entries marked `hooks_only`) read it;
`hooks/tests/test_harness_temp_state.py` pins every row.

## Roots

- **State dir**: `hooks/lib/harness_state_dir.py:44` -- `CLAUDE_STATE_DIR` when absolute, else
  `state/` under the state root on disk, `<home>/.local/state/claude-harness/<harness home's
  name>-<crc32 of its real path>` (`:32`, beside the refusal record's `refusals/` and the
  harness's `logs/` and `restart-state/`). Most rows live here. Until 2026-11-21 the default was
  `/tmp`. No hook, import or session start moves what an earlier version left there: carrying the
  control rows (all but git-blessed-grants, daemon-restart-grant, scratch-owner, dispatch-temp-state,
  doc-sync-notices), the score log and the restart state over is the explicit install step
  `scripts/install/carry_state.py`, which only the configured harness may run; `/tmp` stays a name root.
- **Temp roots**: `/tmp`, `/var/tmp`, and each absolute `TMPDIR`, `CLAUDE_TMPDIR`
  (`hooks/pretool-bash-safety.sh:17`), `CLAUDE_CODE_TMPDIR` (`settings.json` env, with `TMPDIR`
  `/var/tmp/claude-scratch`). The module realpaths each, so `/tmp` and an alias such as
  `/private/tmp` are one root.
  Fail closed: an unset, empty or relative value, or one resolving to `/`, is never a temp root.
- **Name roots** (where the names below are matched): the state dir, `/tmp`, `/var/tmp`, and
  the values of `TMPDIR`, `CLAUDE_TMPDIR`, `CLAUDE_CODE_TMPDIR`, `TMP`, `TEMP`
  (`tempfile.gettempdir()` honours the last two, `hooks/doc_sync/notice.py:241`),
  `CLAUDE_USERINTENT_SENTINEL_DIR` (`hooks/pretool-wrapper-userintent.py:82`),
  `CLAUDE_DAEMON_RESTART_SENTINEL_DIR` (`hooks/lib/bash_safety_rules.py` environment()) and
  `CLAUDE_DOC_SYNC_STATE_ROOT` (`hooks/doc_sync/notice.py:238`). A relative value is joined to
  the cwd (the `cwd=` argument, else the process cwd), as a hook using it would, and `/` is kept:
  `TMPDIR=/` makes `/claude-git-blessed/<tok>.grant` state without making `/` temp.
- **Whole-directory overrides**: `CLAUDE_GIT_BLESSED_GRANT_DIR`, `CLAUDE_CAPABILITY_STATE_DIR`,
  `$XDG_RUNTIME_DIR/claude-capability`, `CLAUDE_GRAPHIFY_CACHE_ROOT` (relative values joined to
  the cwd likewise).

## Control state (a hook trusts it)

| Location | Path (below a name root) | Created / read at |
|---|---|---|
| sentinel-grants | `claude-grants/<task_id>.json` | `hooks/lib/allowlist.py:46`, `:262` (`write_sentinel_grant`), `:305` (`release`, from `hooks/lib/hook_launch.py` `release_refused`), `hooks/userprompt-consent-allowlist.sh:53`, `hooks/stop-cleanup-allowlist.sh:25` |
| do-consent-flag | `claude-orchestrator-consent-<sid>.flag` (matched as `claude-*-consent-*.flag`) | `hooks/prompt-workflow.py:1210`, `hooks/lib/allowlist.py:99` |
| tool-streak | `claude-tool-streak-<sid>.json` | `hooks/lib/allowlist.py:107` |
| tool-ran | `claude-tool-ran-<sid>.log`; no agent writes, moves or removes it (`hooks/pretool-tool-policy.py` `_protected`, `hooks_only`) | `hooks/lib/allowlist.py:167`, `hooks/posttool-orchestrator-ran.py` |
| do-reservation | `claude-do-resv-<ts>` | `hooks/prompt-workflow.py:1189` |
| do-task-sidecar | `claude-do-task-<sid>.json` | `hooks/prompt-workflow.py:1229` |
| userintent-flag | `claude-<cmd>-userintent-<sid>.flag` | `hooks/prompt-workflow.py:1244`, `hooks/pretool-wrapper-userintent.py:123`, `scripts/write-commit-grant.py:397`, `hooks/pretool-bash-safety.sh:28` |
| helper-auth | `claude-<cmd>-helper-auth-<sid>.json` | `hooks/pretool-wrapper-userintent.py:134`, `scripts/break-overnight-lock.py:51` |
| git-grant | `claude-{commit,push}-grant-<sid>-<nonce>.json` | `scripts/write-commit-grant.py:519`, `hooks/push.sh:377`, `hooks/pretool-git-privilege-guard.py:430`, `:1721` |
| commit-dispatch-attest | `claude-commit-dispatch-<sid>-<nonce>.json` | `hooks/lib/commit_pipeline.py:173`, `hooks/pretool-commit-dispatch-attest.py:4` |
| commit-manifest | `claude-commit-manifest-<sid>-plan.json` (written by `scripts/steps/commit-plan.py`); `claude-commit-manifest-<sid>.json` (written by hand by a session holding the old /commit Step 5 text, still read) | `hooks/lib/commit_pipeline.py:169`, `:174`, `:179` (`write_planned_manifest`), `scripts/write-commit-grant.py` (`verify_pipeline_dispatch`) |
| bulk-commit-sentinel | `claude-bulk-commit-sentinel-<sid>-<nonce>.json` | `scripts/write-bulk-commit-sentinel.py:99`, `hooks/lib/commit_pipeline.py:120` |
| commit-event-pointer | `claude-commit-event-<key>.json` | `hooks/lib/commit_journal.py:413` |
| agentic-commit | `agentic-commit/` (`commit-events/`, `push/`, `push-analyst/`, `merge-analyst/`, `locks/`) | `hooks/lib/commit_journal.py:113`, `scripts/write-push-gate-token.py:82`, `scripts/execute-push.py:52`, `hooks/lib/merge_grant.py:40`, `hooks/push.sh:109`, `:215`, `agents/changelog-analyst.md:180` |
| git-residual-override | `claude-git-residual-override/` | `hooks/pretool-git-privilege-guard.py:1868`, `scripts/write-git-residual-override.py:42` |
| runcode-watchdog-pid | `.runcode-watchdog-<sid>.pid` | `hooks/pretool-runcode-watchdog.py:73`, `hooks/posttool-runcode-watchdog.py:79` |
| usage-snapshot-cache | `claude-usage-snapshot-cache.json`, `.usage-cache-*` | `hooks/userprompt-usage-snapshot.py:70`, `:80`, `:94` |
| worktree-guard-cache | `worktree-guard-cache` | `hooks/pretool-worktree-guard.sh:26` |
| git-fswatch-lock | `git-fswatch-<user>-<repo>.lock` | `hooks/git-fswatch.sh:36` |
| tmpfs-pressure-counter | `claude-pressure-warn-<sid>` (the short volumes last told, the time of the last reaction) | `hooks/userprompt-tmpfs-pressure.sh:46` |
| checkpoint-push-stamp | `.checkpoint-push-<hash>.ts` | `hooks/lib/checkpoint-core.sh:368` |
| checkpoint-overtime | `.checkpoint-overtime-<hash>` (the snapshot pause mark); no agent writes, moves or removes it (`_protected`, `hooks_only`) | `hooks/lib/bash_safety_rules.py:4999` |
| codex-unavailable | `codex-unavailable.json`; no agent writes, moves or removes it (`_protected`, `hooks_only`) | `hooks/lib/codex_transcript.py:22`, `hooks/subagentstop-codex-enforce.py:118` |
| report-provenance | `report-provenance/<key>.json`, `<key>.head`; no agent writes, moves or removes it (`_protected`, `hooks_only`) | `hooks/lib/report_provenance.py:110`, `:113` |
| lane-ledger | `lane-ledger/<sid>/<agent id>.json` (and `.lock`): a dev lane's file baselines and its report as the dispatch found it. Removed on the lane's stop that stands (`end`, a witness rule of `hooks/subagentstop-producer-gate.py`); a refused stop keeps it; a lane that never reaches such a stop leaves it; no agent writes, moves or removes it (`_protected`, `hooks_only`) | `hooks/lib/lane_ledger.py:140` (`record`, from `hooks/pretool-lane-ledger.py`), `:277` (`at_stop`) |
| returns-hold | `returns-hold/<sid>.json` (and an empty `.lock`): a batch of held background returns, written only while the hold is switched on (`CLAUDE_RETURNS_HOLD=on`; off unless switched on). Removed by its writer at the batch's hand-over (at most 30 min plus the next prompt after its first hold); the `.lock` stays; no agent writes, moves or removes it (`_protected`, `hooks_only`) | `hooks/lib/returns_hold.py` `_save` and `decide` (from `hooks/userprompt-launch.py`), `deadline` (from `hooks/userprompt-returns-deadline.sh`) |
| auto-targets | `auto-targets/<sid>.json`: the task list of the session's last `/close --auto` or `/commit --auto`, fixed when the owner's command arrived. Lives until the session's next such command replaces it; a file older than 7 days goes at the next write; no agent writes, moves or removes it (`_protected`, `hooks_only`) | `scripts/dev-lifecycle.py` `freeze_auto_targets` (from `hooks/userprompt-auto-targets.py`), `read_frozen` (from `hooks/stop-command-gate.py` `_targets`) |
| stop-disposition | `stop-disposition/<digest>.json`: the Stop gate's gap lines for one (project, task, stage) and the facts they were computed from (a file's stat, a repository's state, and for the refusal record only a digest of the refused ids of each session asked of it: the record grows with every block, so its bytes are no fact; the saved conversations behind the dispatch records of a task are no path facts either: the key holds the digest of each answer and the stat of the conversations behind it, so a conversation that grew without changing an answer discards nothing and the record is kept with its stats renewed); reused only while every fact holds. Replaced by the next computation; a record older than 7 days goes at the next write; no agent writes, moves or removes it (`_protected`, `hooks_only`) | `hooks/lib/fact_cache.py` `save`, `load` (from `hooks/stop-command-gate.py` `disposition`) |
| transcript-index | `transcript-index/<digest>.json`: what the Stop gate's scan made of one saved conversation (the id runs it holds; its dispatch calls, the ids a hook refused and the typed commands; for the session's own conversation, kind `span-<digest of the set of commands asked for>` (one entry per set, the time lock's reader asks for another set than the span reader): the typed harness commands, the dispatch and SendMessage calls with their results' fields, results and times, the ids a hook refused, read by `hooks/lib/command_span.py` `active_span`, `Span.dispatches` and `active_command(keep=...)`, the coordinator's reader), the offset and line count it had read to, and a digest of the first and of the last 64 KB before that offset; the next scan reads from the offset only while the file is no shorter and both digests hold, else whole. Replaced after each conversation read, so a cut-off stop keeps what it finished; a record older than 7 days goes at the next write; no agent writes, moves or removes it (`_protected`, `hooks_only`) | `hooks/lib/transcript_index.py` `extend` (from `hooks/lib/obligation.py` `transcript_scan(keep=...)`, opened by `hooks/stop-command-gate.py` `_one_scan`; and from `hooks/lib/command_span.py` `_kept_span`, inside that scan or for `hooks/stop-workflow-coordinator.py` `_record`) |
| capability-state | `claude-capability-<euid>/` | `hooks/lib/capability_state.py:206` |
| git-blessed-grants | `claude-git-blessed/<tok>.grant` (under `${TMPDIR:-/tmp}`) | none since the minter, which nothing called, and the keystone's exemption were removed (S31); still classified |
| daemon-restart-grant | `claude-allow-daemon-restart-<target>.flag` (under `CLAUDE_TMPDIR`) | `hooks/pretool-bash-safety.sh:25`, `:544` |
| scratch-owner | `<sid>/.owner` (and `.owner.<pid>.tmp`) in the session scratch root; no agent writes, moves or removes it, nor a directory holding it, in its own session's directory or another's (`_protected`, `hooks_only`): its `created_at` dates the session's start (`hooks/lib/policy_registry.py` `_began_before`) | `hooks/session-scratch-init.sh:83`, `:84` (the writer), `hooks/lib/scratch_owner.py:35` (`owner_record`, the one reader) |
| dispatch-temp-state | `<sid>/.dispatch-tmp` (and `.dispatch-tmp.<pid>`) in the session scratch root; no agent writes, moves or removes it (`hooks/pretool-tool-policy.py` `_protected`) | `hooks/lib/dispatch_temp.py:31` (`_write`, `_read`), the env-file line of `hooks/session-scratch-init.sh`, `scripts/install/tmp-cleanup-install.sh` `retired` |
| doc-sync-notices | `<sid>/doc-sync-notices-<audience>.json` in the session scratch root (`locations.session_scratch_root`) | `hooks/doc_sync/notice.py:39`, `:232`, `:266`, `:294` |

## Harness-managed scratch

| Location | Path | Created / read at |
|---|---|---|
| claude-scratch | `/var/tmp/claude-scratch/<sid>/` (session scratch), `<sid>/<role>/` in it (a role's drafts, `<session root>/<role>/`; before policy_version 10 `/tmp/claude-scratch/<role>/`, which the tmpfiles rule ages out; there, and in the old `/tmp/agentic-commit/locks/`, a flow begun before only overwrites an existing single-link file whose path holds no link, under the role's deny prefixes, until 24 hours after the policy file reached the install; the changelog-analyst of a session whose `.owner` dates from before that arrival also creates a new `commit-msg-*.txt` there and takes its `${REPO_HASH}.lock`: `hooks/lib/policy_registry.py` `in_flight`), `<sid>/<role>/<agent id>/` in it (a subagent's own scratch) | `policies/tool-policy.v1.json:170`, `hooks/session-scratch-init.sh:27`, `hooks/subagentstart-scratch.py`, `hooks/sessionend-scratch-sweep.sh:27`, `scripts/install/tmpfiles-claude-scratch.conf:42` |
| codex-outputs | `/var/tmp/codex-outputs/` | `scripts/steps/codex-run.py:40`, `policies/tool-policy.v1.json:39` |
| graphify-cache | `/var/tmp/claude-graphify/` | `scripts/graphify_lib.py:138` |
| runtime-guard-err | `runtime-guard-XXXXXX` in `CLAUDE_TMPDIR` | none since 73fe2909d (the bash-safety shell stopped creating it); still classified for what an older install left |
| grepguard-probe | `grepguard-probe-*` (mkdtemp) | `hooks/pretool-grep-backtrack-guard.py:542` |
| checkpoint-result | `checkpoint-result.<pid>.<ns>` (mktemp fallback) | `hooks/lib/checkpoint-core.sh:677` |
| hero-fixture | `claude-hero-fixture-*` (mkdtemp) | `scripts/capture-hero-run.py:294` |
| tmp-cleanup-candidates | `/var/tmp/tmp-cleanup-cands-*` | `scripts/install/tmp-cleanup-install.sh:267`, `:291` |

## Not inventoried

- `<CLI temp root>/claude-<uid>/` is Claude Code's own task directory; the harness only sweeps
  its `*.output` files, of this user and this installation's CLI temp root only
  (`scripts/install/tmp-cleanup-install.sh:86`, `:368`).
- `contract-bookmark-*.json`, `artifact-status-*.json` and `claude-commit-plan-*`: no current
  code writes them, and the sweep no longer lists them.
- Anonymous `mktemp` / `tempfile` names (`tmp.XXXXXX`) carry no harness name to match.
- State outside the temp roots: restart state (`hooks/lib/subagent_restart.py:205`, the state
  root's `restart-state/`), the logs (the state root's `logs/`), the attribution journal (`hooks/lib/attribution_journal.py:92`), overnight state
  (`scripts/create-overnight-state.sh:688`, under the project's `.claude/`).

## Limitations

- **Case.** Control-state locations match case-insensitively, the root prefix as well as the
  names, so on a case-insensitive filesystem (macOS APFS by default) `/TMP/Claude-Grants/x` is
  still state. On a case-sensitive filesystem this errs toward "state". Scratch locations and
  `temp_roots()` stay case-sensitive, so folding never widens what counts as temp.
- **Hard links.** A hard link to a state file is a second name for the same inode that
  realpath cannot see, so `classify()` judges it by its own name only. Detecting it would need
  an inode comparison against the live state files, which this pure path classifier does not do.
- **Per-call redirects.** The classifier reads the hook process's environment. An agent can set
  `TMPDIR` or `CLAUDE_GIT_BLESSED_GRANT_DIR` (or another override above) for its own command, e.g.
  `CLAUDE_GIT_BLESSED_GRANT_DIR=/x git ...`, and the program it runs then reads and writes state
  in a directory no hook-side classifier knows about. Catching that means parsing the command's
  environment assignments, which is the caller's job.
- **Input.** A `str`, `bytes` (decoded with `os.fsdecode`) or `os.PathLike` path is accepted;
  any other type raises `TypeError` rather than reading as "not state".
