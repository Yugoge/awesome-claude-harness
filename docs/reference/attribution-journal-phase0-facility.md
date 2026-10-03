# Write-time attribution journal — Phase 0 facility notes

Scope: the capture + persistence + verification facility itself --
`hooks/lib/attribution_journal.py`, `hooks/pretool-attribution-pre.py`,
`hooks/posttool-attribution-post.py`, `scripts/seal-attribution-journal.py`,
`scripts/verify-attribution-chain.py`, and `hooks/tests/test_attribution_journal.py`.
NOT the Phase D ownership-verdict / aggregate-view consumer layer
(`scripts/lib/attribution_adjudicator.py`, `scripts/lib/attribution_aggregate_view.py`
and their CLI wrappers) -- that layer is a separate, not-yet-applied lane; see
`docs/reference/attribution-journal-cutover-flip-plan-20261003.md`.

## 1. Automatic periodic sealing to persistent storage

The journal and the git object database holding its content blobs live under
`state/attribution-journal/` inside the harness checkout, which in this
deployment is itself tmpfs (`/dev/shm`) -- everything there is lost on reboot
unless sealed to disk-backed storage first.

**Trigger.** `autoseal_hook_trigger()` in `hooks/lib/attribution_journal.py`
runs after every `record_post()` call inside `hooks/posttool-attribution-post.py`
-- i.e. after every `Write`/`Edit`/`MultiEdit`/`NotebookEdit`/`Bash` tool call
across every session, which is already registered in `settings.json` and
required no new hook registration. There is deliberately no cron/heartbeat:
the seal cadence is tied to the same event stream that produces the evidence
being sealed, so it cannot go stale relative to tool-call activity the way an
independent timer could.

**Periodicity + idempotency.** `autoseal_if_due()` in
`scripts/seal-attribution-journal.py` seals only when at least `interval`
seconds (default 600, `$ATTRIBUTION_SEAL_INTERVAL_SECONDS`) have passed since
the last recorded attempt -- success or error -- in the destination's own
`seal-log.jsonl`. A persistently failing destination therefore keeps retrying
every interval rather than going silent forever. `seal()` itself was already
idempotent (content-addressed blobs, size-compared journal copies); calling it
twice in a row (e.g. two due checks racing, by design lock-free like the rest
of this facility) is harmless -- the second call's `blobs_added` /
`journals_copied` are 0. Pinned by
`test_autoseal_skips_when_not_due_then_seals_when_due` and
`test_autoseal_forced_repeat_is_idempotent_and_logs_both_attempts`.

**Verifiable evidence.** Every attempt -- automatic or manual (`main()`'s
default path now also logs) -- appends one entry to `<dest>/seal-log.jsonl`:
`{ts, trigger, status, result}` on success (`result` is `seal()`'s own
dict: `events`, `journals_copied`, `blobs_added`, `blobs_missing_in_source`,
...), or `{ts, trigger, status: "error", error}` on failure. Check it with:

```
python3 scripts/seal-attribution-journal.py --show-last
```

or tail `seal-log.jsonl` directly. Pinned end-to-end (real subprocess, hook
entrypoint, stdout contract preserved) by
`test_posttool_hook_autoseals_end_to_end_via_real_subprocess`.

**Persistence tier of the resolved destination.** `default_dest()` resolves,
in order: `$ATTRIBUTION_SEAL_DEST` (explicit override) > `$CLAUDE_CONFIG_DIR/attribution-seals`
> `~/.claude/attribution-seals` (fallback when `CLAUDE_CONFIG_DIR` is unset).
Measured in this deployment via `/proc/mounts`:

| Resolution | Path | Backing mount | fstype | Tier |
|---|---|---|---|---|
| `$CLAUDE_CONFIG_DIR` set (the normal case here) | `/var/lib/claude-accounts/<acct>/claude/attribution-seals` | `/` on `/dev/sda1` | ext4 | **disk-backed, persistent** |
| Fallback (`CLAUDE_CONFIG_DIR` unset) | `~/.claude/attribution-seals` | in this environment `~/.claude` is itself a symlink onto this tmpfs checkout | tmpfs | volatile |

`seal()` / `autoseal_if_due()` call `mount_class()` on the destination and
refuse (raise, then record an `"error"` evidence entry rather than crash the
hook) a volatile destination unless `--allow-volatile` / `allow_volatile=True`
is explicit. In the normal case (`CLAUDE_CONFIG_DIR` set, as it is here) the
default resolves to the persistent tier automatically; an operator who unsets
`CLAUDE_CONFIG_DIR` in an environment without it would get a volatile
fallback and should set `$ATTRIBUTION_SEAL_DEST` explicitly.

## 2. Directory indices

The facility's files are listed in their owning directory's `INDEX.md`
(`hooks/INDEX.md`, `hooks/lib/INDEX.md`, `scripts/INDEX.md`,
`hooks/tests/INDEX.md`) via the repo's normal doc-sync regeneration, which
only lists git-tracked paths -- the files had to be staged (`git add`, no
commit) before a regen pass would include them, since they were created
outside a `Write`/`Edit` tool call (so doc-sync's own PostToolUse hook never
fired for them) and were therefore both untracked and un-indexed until this
pass.

## 3. Known boundary: writes by another hook, after this call, miss the window

**Symptom.** A file written to disk by a *different* PostToolUse hook as a
side effect of this tool call -- the concrete recurring case is
`hooks/doc_sync/main.py` regenerating `INDEX.md`/`README.md` for the parent
directory of whatever file was just edited -- is captured by neither this
call's single-target pre/post hash (Write/Edit/MultiEdit/NotebookEdit measure
only the declared `file_path`) nor a Bash dirty-worktree scan (it isn't a Bash
call at all). The write is simply outside this invocation's measurement
window.

**Ruling: NOT closable without changing existing capture semantics or
touching a facility-external hook/registration, so it is documented as a
known boundary rather than closed.** Both routes that *would* close it fail
one of this task's own constraints:

- Extend Write/Edit/MultiEdit/NotebookEdit to also do a Bash-style
  worktree-wide dirty scan (so an incidental sibling write is picked up too).
  This changes what these tools capture today (single declared target only)
  -- a capture-semantics change, which this ruling is required to avoid.
- Reorder `posttool-attribution-post.py` to run *after*
  `posttool-doc-sync.py` in `settings.json` (today it runs *before* --
  verified directly against the live hook registration) so doc-sync's write
  lands inside the window. This still requires the capture-semantics change
  above (doc-sync's write is to a *different* path than the edited target),
  AND it changes the relative execution order of hooks that are not part of
  this facility (`posttool-git-checkpoint.sh`, `posttool-doc-sync.py`,
  `posttool-command-frontmatter-validate.py`,
  `posttool-lane-completeness-watch.py`) -- out of scope for a facility-only
  change.

**This is not a silent gap: it has one detection signature, and the
facility already surfaces it.** The hash-chain fold in
`scripts/verify-attribution-chain.py` has no special case for it and needs
none -- an uncaptured write between two captured ones is, by the fold's own
model, indistinguishable from any other out-of-band write, and surfaces
exactly the same way: an ordinary **BREAK**, with the dangling "before"/"after"
event pair naming the two bracketing sessions. The detection criterion an
operator should use when triaging a BREAK on a path they did not expect to be
suspicious:

- the broken path's basename is `INDEX.md` or `README.md`, and
- the path lies under one of doc-sync's watched trees (`.claude/commands`,
  `.claude/agents`, `.claude/hooks`, `.claude/skills`, `.claude/scripts` when
  nested under `.claude/`, or -- as in this repo, which *is* a `.claude`-style
  root -- any directory at all, since doc-sync's extension-based fallback
  (`WATCHED_EXTS` in `hooks/doc_sync/main.py`) fires regardless of directory
  for `.py`/`.md`/`.json`/... siblings).

Such a break is explained by this boundary, not by an unattributed write, and
should be cross-checked against doc-sync's own side-effect record
(`hook_ledger` / the PostToolUse notice `hooks/doc_sync/notice.py` emits)
rather than treated as an anomaly. This ruling, and the exact BREAK shape it
produces, is pinned with the REAL doc-sync producer (not a synthetic
stand-in) by
`test_doc_sync_regen_outside_capture_window_surfaces_as_break` in
`hooks/tests/test_attribution_journal.py`.
