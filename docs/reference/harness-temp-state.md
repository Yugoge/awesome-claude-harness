# Harness temp state inventory

> Last updated: 2026-11-17

Every file or directory the harness itself keeps under `/tmp`, `/var/tmp` or `$TMPDIR`,
with the `path:line` that creates or reads it. `hooks/lib/harness_temp_state.py` is the one
definition of this list: `LOCATIONS` holds one entry per row below (the **Location** column),
`classify(path)` answers which entry a path is, `is_harness_state(path)` whether it is control
state, `temp_roots()` / `is_in_temp_root(path)` what counts as a temp root, and
`crosses_mount(path)` whether a mount point under the temp root carries the path elsewhere. The removal
policy of `hooks/pretool-bash-safety.sh` (`hooks/lib/bash_execution_boundary.py`, `rm_temp_targets_proven`)
uses it to allow a plain `rm` of temp-root paths that are not control state (only as the command string's
one command, on a path with no symlink and no mount point on it or, for a recursive removal or a directory,
below it; a symlink or mount a separate background call makes after the hook ran is a residual race);
`hooks/tests/test_harness_temp_state.py` pins every row.

## Roots

- **State dir**: `hooks/lib/harness_state_dir.py:29` -- `CLAUDE_STATE_DIR` when absolute, else
  `/tmp` (`:26`). Most rows live here.
- **Temp roots**: `/tmp`, `/var/tmp`, and each absolute `TMPDIR`, `CLAUDE_TMPDIR`
  (`hooks/pretool-bash-safety.sh:17`), `CLAUDE_CODE_TMPDIR` (`settings.json` env, with `TMPDIR`
  `/var/tmp/claude-scratch`). The module realpaths each, so `/tmp` and an alias such as
  `/private/tmp` are one root.
  Fail closed: an unset, empty or relative value, or one resolving to `/`, is never a temp root.
- **Name roots** (where the names below are matched): the state dir, `/tmp`, `/var/tmp`, and
  the values of `TMPDIR`, `CLAUDE_TMPDIR`, `CLAUDE_CODE_TMPDIR`, `TMP`, `TEMP`
  (`tempfile.gettempdir()` honours the last two, `hooks/doc_sync/notice.py:241`),
  `CLAUDE_USERINTENT_SENTINEL_DIR` (`hooks/pretool-wrapper-userintent.py:82`),
  `CLAUDE_DAEMON_RESTART_GRANT_DIR` (`hooks/pretool-bash-safety.sh:25`) and
  `CLAUDE_DOC_SYNC_STATE_ROOT` (`hooks/doc_sync/notice.py:238`). A relative value is joined to
  the cwd (the `cwd=` argument, else the process cwd), as a hook using it would, and `/` is kept:
  `TMPDIR=/` makes `/claude-git-blessed/<tok>.grant` state without making `/` temp.
- **Whole-directory overrides**: `CLAUDE_GIT_BLESSED_GRANT_DIR`, `CLAUDE_CAPABILITY_STATE_DIR`,
  `$XDG_RUNTIME_DIR/claude-capability`, `CLAUDE_GRAPHIFY_CACHE_ROOT` (relative values joined to
  the cwd likewise).

## Control state (a hook trusts it)

| Location | Path (below a name root) | Created / read at |
|---|---|---|
| sentinel-grants | `claude-grants/<task_id>.json` | `hooks/lib/allowlist.py:64`, `hooks/userprompt-consent-allowlist.sh:69`, `hooks/posttool-allowlist-consume.py:22`, `hooks/stop-cleanup-allowlist.sh:25` |
| do-consent-flag | `claude-orchestrator-consent-<sid>.flag` (matched as `claude-*-consent-*.flag`) | `hooks/prompt-workflow.py:1210`, `hooks/lib/allowlist.py:99` |
| tool-streak | `claude-tool-streak-<sid>.json` | `hooks/lib/allowlist.py:107` |
| do-reservation | `claude-do-resv-<ts>` | `hooks/prompt-workflow.py:1189` |
| do-task-sidecar | `claude-do-task-<sid>.json` | `hooks/prompt-workflow.py:1229` |
| userintent-flag | `claude-<cmd>-userintent-<sid>.flag` | `hooks/prompt-workflow.py:1244`, `hooks/pretool-wrapper-userintent.py:123`, `scripts/write-commit-grant.py:397`, `hooks/pretool-bash-safety.sh:28` |
| helper-auth | `claude-<cmd>-helper-auth-<sid>.json` | `hooks/pretool-wrapper-userintent.py:134`, `scripts/break-overnight-lock.py:51` |
| git-grant | `claude-{commit,push}-grant-<sid>-<nonce>.json` | `scripts/write-commit-grant.py:519`, `hooks/push.sh:377`, `hooks/pretool-git-privilege-guard.py:430`, `:1721` |
| commit-dispatch-attest | `claude-commit-dispatch-<sid>-<nonce>.json` | `hooks/lib/commit_pipeline.py:173`, `hooks/pretool-commit-dispatch-attest.py:4` |
| commit-manifest | `claude-commit-manifest-<sid>.json` | `hooks/lib/commit_pipeline.py:169` |
| bulk-commit-sentinel | `claude-bulk-commit-sentinel-<sid>-<nonce>.json` | `scripts/write-bulk-commit-sentinel.py:99`, `hooks/lib/commit_pipeline.py:120` |
| commit-event-pointer | `claude-commit-event-<key>.json` | `hooks/lib/commit_journal.py:413` |
| agentic-commit | `agentic-commit/` (`commit-events/`, `push/`, `push-analyst/`, `merge-analyst/`, `locks/`) | `hooks/lib/commit_journal.py:113`, `scripts/write-push-gate-token.py:82`, `scripts/execute-push.py:52`, `hooks/lib/merge_grant.py:40`, `hooks/push.sh:109`, `:215`, `agents/changelog-analyst.md:172` |
| git-residual-override | `claude-git-residual-override/` | `hooks/pretool-git-privilege-guard.py:1868`, `scripts/write-git-residual-override.py:42` |
| runcode-watchdog-pid | `.runcode-watchdog-<sid>.pid` | `hooks/pretool-runcode-watchdog.py:73`, `hooks/posttool-runcode-watchdog.py:79` |
| usage-snapshot-cache | `claude-usage-snapshot-cache.json`, `.usage-cache-*` | `hooks/userprompt-usage-snapshot.py:70`, `:80`, `:94` |
| worktree-guard-cache | `worktree-guard-cache` | `hooks/pretool-worktree-guard.sh:26` |
| git-fswatch-lock | `git-fswatch-<user>-<repo>.lock` | `hooks/git-fswatch.sh:36` |
| tmpfs-pressure-counter | `claude-pressure-warn-<sid>` (and `.lock`) | `hooks/userprompt-tmpfs-pressure.sh:66` |
| checkpoint-push-stamp | `.checkpoint-push-<hash>.ts` | `hooks/lib/checkpoint-core.sh:362` |
| capability-state | `claude-capability-<euid>/` | `hooks/lib/capability_state.py:206` |
| git-blessed-grants | `claude-git-blessed/<tok>.grant` (under `${TMPDIR:-/tmp}`) | `hooks/git-keystone/reference-transaction:54`, `scripts/mint-git-blessed-token.sh:39` |
| daemon-restart-grant | `claude-allow-daemon-restart-<target>.flag` (under `CLAUDE_TMPDIR`) | `hooks/pretool-bash-safety.sh:25`, `:544` |
| scratch-owner | `<sid>/.owner` (and `.owner.<pid>.tmp`) in the session scratch root | `hooks/session-scratch-init.sh:27`, `:73`, `hooks/lib/scratch_owner.py:17` |
| doc-sync-notices | `<sid>/doc-sync-notices-<audience>.json` under `tempfile.gettempdir()` | `hooks/doc_sync/notice.py:39`, `:241`, `:266`, `:294` |

## Harness-managed scratch

| Location | Path | Created / read at |
|---|---|---|
| claude-scratch | `/tmp/claude-scratch/<role>/` (role scratch, e.g. `qa/`), `/var/tmp/claude-scratch/<sid>/` (session scratch) | `policies/tool-policy.v1.json:167`, `hooks/session-scratch-init.sh:27`, `hooks/sessionend-scratch-sweep.sh:27`, `scripts/install/tmpfiles-claude-scratch.conf:50` |
| codex-outputs | `/var/tmp/codex-outputs/` | `scripts/steps/codex-run.py:40`, `policies/tool-policy.v1.json:39` |
| graphify-cache | `/var/tmp/claude-graphify/` | `scripts/graphify_lib.py:138` |
| orchestrator-output | `/tmp/{dev-output,qa-output,iteration-context,cleanliness-output,style-output,cleaner-output,rule-output}-<epoch>.json` | `scripts/orchestrator.sh:25`, `:26`, `:27`, `:248`, `:249`, `:360`, `:426` |
| runtime-guard-err | `runtime-guard-XXXXXX` in `CLAUDE_TMPDIR` | `hooks/pretool-bash-safety.sh:285` |
| grepguard-probe | `grepguard-probe-*` (mkdtemp) | `hooks/pretool-grep-backtrack-guard.py:1108` |
| checkpoint-result | `checkpoint-result.<pid>.<ns>` (mktemp fallback) | `hooks/lib/checkpoint-core.sh:645` |
| hero-fixture | `claude-hero-fixture-*` (mkdtemp) | `scripts/capture-hero-run.py:294` |
| tmp-cleanup-candidates | `/var/tmp/tmp-cleanup-cands-*` | `scripts/install/tmp-cleanup-install.sh:92` |

## Not inventoried

- `/tmp/claude-0/` is Claude Code's own task directory; the harness only sweeps it
  (`scripts/install/tmp-cleanup-install.sh:58`).
- Names the sweep still lists but no current code writes: `contract-bookmark-*.json`,
  `artifact-status-*.json` (`tmp-cleanup-install.sh:147`), `claude-commit-plan-*` (`:59`).
- Anonymous `mktemp` / `tempfile` names (`tmp.XXXXXX`) carry no harness name to match.
- State outside the temp roots: restart state (`hooks/lib/subagent_restart.py:201`, under
  `~/.claude`), the attribution journal (`hooks/lib/attribution_journal.py:92`), overnight state
  (`scripts/create-overnight-state.sh:688`, under the project's `.claude/`).

## Mount points

realpath cannot see a bind mount: as root, `mount --bind ~/.claude /tmp/b3` leaves `/tmp/b3`
resolving to itself (same `st_dev` too, when both are on one filesystem), while `rm -rf /tmp/b3`
or a write to `/tmp/b3/settings.json` reaches the mounted directory. `crosses_mount(path, *,
below=False, cwd=None, mountinfo=None)` reads `/proc/self/mountinfo` (`mount_points()`, field 5
with its `\040`-style octal escapes undone, each realpath'd) and is True when a mount point lies
between the path's temp root and the path, the path itself included, or with `below=True`
anywhere under it (for a recursive removal). Mounts at or above the temp root, such as a tmpfs
`/tmp` or the root filesystem, are ignored. It is a disqualifier only and fails closed: True
when the path is in no temp root, when mountinfo cannot be read or parsed, or on any error.
A caller allowing a temp write or removal requires `is_in_temp_root(p) and not crosses_mount(p)`.

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
- **Races.** Every check reads the filesystem when the hook runs. A symlink or a mount created
  afterwards, by a separate call that is still running (a backgrounded `sleep 1; mount --bind
  ...`), is not seen; the path's later meaning is outside any pre-tool check.
- **Input.** A `str`, `bytes` (decoded with `os.fsdecode`) or `os.PathLike` path is accepted;
  any other type raises `TypeError` rather than reading as "not state".
