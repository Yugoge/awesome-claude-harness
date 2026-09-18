# Auto-Commit / Checkpoint Mechanism

> Full reference for the `refs/checkpoints/*` snapshot system. Slim summary lives in `~/.claude/CLAUDE.md`.
> Last updated: 2026-04-16

---

## Overview

As of 2026-04-16, all automated snapshots (PostToolUse threshold, Stop
hooks, fswatch daemon, manual `/checkpoint`) are written to
`refs/checkpoints/<sanitized-branch>` via
`~/.claude/hooks/lib/checkpoint-core.sh`. Branch HEADs are **never**
advanced by automated snapshots. `git blame` on any line therefore points
to a real semantic commit.

---

## Key consequences for verifying subagent work

- `git diff` AND `git log HEAD` both show no evidence of the snapshot —
  the commit lives on a side-ref, not on HEAD.
- To see recent automated snapshots on the current branch:
    ```
    git log refs/checkpoints/<branch>
    ```
  (replace `/` in branch name with `-`; detached HEAD maps to
  `refs/checkpoints/detached-<short-sha>`.)
- To list all checkpoint refs:
    ```
    git for-each-ref refs/checkpoints/
    ```
- To confirm files are actually saved (not lost), inspect the latest
  checkpoint tree — NOT `git diff`:
    ```
    git show refs/checkpoints/<branch> --stat
    ```

---

## Recovery commands

```
# View full history of snapshots on current branch:
git log refs/checkpoints/master

# Restore a single file from the latest checkpoint:
git checkout refs/checkpoints/master -- path/to/file

# Read a file's content at a specific checkpoint:
git show refs/checkpoints/master:path/to/file

# Restore an entire tree snapshot into the working copy:
git checkout refs/checkpoints/master -- .
```

---

## Cross-machine recovery

Add to `.git/config` on any clone; **NOT** applied automatically, this is
document-only:

```
[remote "origin"]
    fetch = +refs/heads/*:refs/remotes/origin/*
    fetch = +refs/checkpoints/*:refs/remotes/origin/checkpoints/*
```

After adding the refspec, `git fetch` mirrors checkpoints into
`refs/remotes/origin/checkpoints/<branch>` on the cloning machine.

---

## Log file locations

- `~/.claude/logs/checkpoint.log` — CAS retries, build failures,
  empty-repo bootstraps.
- `~/.claude/logs/checkpoint-push.log` — background push failures. Push
  is rate-limited to once per 30 seconds per repo and never uses `-f`
  (CAS guarantees the ref chain is always fast-forward).

---

## PII/credential safety (2026-09-18)

Two independent, purely-additive safety layers guard against a checkpoint
snapshot republishing sensitive content (root cause: a `.claude.json` blob
captured on 2026-07-13, 13 days before the corresponding `.gitignore` rule
existed, stayed reachable forever on `refs/checkpoints/master` because
`commit-tree` always parents each new checkpoint on the prior checkpoint
tip — see `git log --grep=checkpoint` for the history).

### 1. Hard-exclude at snapshot-build time (independent of `.gitignore`)

`write_checkpoint()` removes known PII file classes from the temp index
right after `git add -A`, **before** `write-tree` — regardless of what the
CURRENT `.gitignore` says. This is a defense-in-depth backstop, not a
replacement for `.gitignore`: `add -A` still carries no `-f`, so ordinary
ignore rules are respected exactly as before.

Matching is path-component-exact (never substring), mirroring this
project's own established discipline (`.gitignore:118-119`):

- `CHECKPOINT_PII_BASENAME_PREFIXES` (default `.claude.json`) — matched as
  a basename **prefix**, so `.claude.json`, `.claude.json.bak`, etc. are
  all excluded.
- `CHECKPOINT_PII_PATH_COMPONENTS` (default `backups sessions`) — matched
  as an exact **interior directory segment** at any depth, so
  `configs/backups/x.txt` and `a/b/sessions/c.txt` are excluded, but a
  plain top-level file literally named `backups` is not.

A hard-excluded path never enters the snapshot tree, so `git ls-tree -r`
on the resulting checkpoint commit will not list it, no matter what
`.gitignore` currently says.

### 2. Fail-closed PII/credential push gate

`_checkpoint_rate_limited_push()`'s detached background worker
(`_checkpoint_push_worker()`) now runs a **second** gate,
`_checkpoint_push_gate_pii_signature()`, before the pre-existing
oversized-blob size gate. It scans the same local-minus-remote object set
the size gate already computes (`rev-list --objects <local> --not
<remote>`) for conventional PII/credential shapes:

- email-shaped strings, RFC-4122 UUID-shaped strings
- `sk-`/`AKIA`-prefixed token shapes (copied verbatim from this repo's own
  CI secret scan, `.github/workflows/baseline.yml:130`)
- GitHub token prefixes (`ghp_`/`gho_`/`ghu_`/`ghs_`/`ghr_`)
- JWT-shaped three-segment base64url strings

The pattern is overridable via `CHECKPOINT_PII_SIGNATURE_PATTERN`.

**This gate is fail-CLOSED**, in explicit contrast to the sibling
oversized-blob gate (which is intentionally fail-open — a bandwidth
optimization, not a security control). Any inability to complete the scan
— no `timeout` binary, a remote-lookup failure/timeout, a `rev-list`
failure, a `cat-file` failure — also **blocks** the push rather than
allowing it.

On a match, the upload never happens and a distinct `[ALERT]` line is
appended to `~/.claude/logs/checkpoint-push.log` naming the blocking
object, e.g.:

```
[2026-09-18 09:26:56] [ALERT] BLOCK push refs/checkpoints/master: local-minus-remote object set contains PII/credential-shaped content: <oid> (<path>) (repo=<path>)
```

Once a PII-shaped blob enters local checkpoint history this way, it stays
in the local-minus-remote set (and keeps blocking every subsequent push
attempt on that branch) until a human intervenes — this is intentional:
the mechanism is forward-only and additive, and deleting/rewriting a
`refs/checkpoints/*` ref is a human-operated action, never automatic.

Regression coverage: `hooks/tests/test_checkpoint_pii_gate.sh`.

---

## Migration note (pre-existing HEAD pollution)

Commits with messages `Auto-commit: …` and `checkpoint: Auto-save at …`
that already exist on `master` are **not** rewritten automatically. If
you want a clean history you can excise them retroactively with
`git filter-repo`. Example (destructive — coordinate before running):

```
git filter-repo --commit-callback '
    if commit.message.startswith(b"Auto-commit:") or commit.message.startswith(b"checkpoint:"):
        commit.skip()
'
```

---

## `/push` behaviour change

`/push` no longer auto-commits. If the working tree is dirty, `/push`
exits non-zero with a "commit first" message. Use `/checkpoint`
(snapshot-only, no HEAD move) or `git commit` (real semantic commit)
before pushing.
