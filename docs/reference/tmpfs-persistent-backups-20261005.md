# Persistent-disk backups of the tmpfs-only checkout (2026-10-05)

The entire checkout — working tree, `.git`, and `docs/dev/` — lives on `/dev/shm` (tmpfs, 16G, volatile). Local `master` is 141 commits ahead of `origin/master` with no history-preserving reconciliation path currently available (measured and recorded in full in `docs/reference/master-origin-reconciliation-gap-20261005.md`). Both backups below exist for the same reason that record does: the only copy of a growing amount of work sits on volatile storage, and this machine also has a large persistent disk (`/`, ext4, 601G, ~300G free) that nothing was writing to.

## A judgment process worth keeping, because it is more useful than the conclusion

The whole investigation that produced the reconciliation-gap record treated "the 141 commits only exist on tmpfs" as a problem that could only be solved by getting them onto the remote. Five push/merge/pull routes were tested, all five came back closed, and that got written down carefully. What never got asked, across any of those five tests, was whether this machine had persistent storage at all. It turned out it does — a 300G ext4 volume, sitting unused the entire time. Exhausting every route to one destination (the remote) got mistaken for exhausting every way to protect the content. The real question was "how do I make sure this doesn't get lost," and pushing to a remote is only one answer to that question, not the question itself.

## Archive 1 — full git history

| | |
|---|---|
| Path | `/var/backups/dot-claude-git-backup-20261005/dot-claude-full.bundle` |
| Size | 27,229,316 bytes (~26M) |
| Filesystem | ext4 (`/dev/sda1`, persistent) |
| Method | a full-history git bundle covering every ref namespace, not just branches |
| Coverage | all 4 ref namespaces present in the source repo — `refs/heads/` (12), `refs/remotes/` (4), `refs/checkpoints/` (3), `refs/backups/` (596) — plus `HEAD` and two worktree `HEAD` refs; 618 refs total |

**Verified, not assumed:** the bundle's own integrity check reports a complete history. A restore into a throwaway clone on the same ext4 volume reproduced an identical `master` tip to the live source, byte-for-byte. The one fragile coordinate this exercise exists to protect — the checkpoint ref that is the sole recovery path for 60 files, reachable from no branch — was checked by name in the restored clone and confirmed reachable through `refs/checkpoints/worktree-overnight-20260810-019fe5c1`, not merely "present somewhere."

**To restore:** clone from the bundle (a mirror-clone reproduces every ref; an ordinary clone gives a normal working checkout of whichever branch you need).

## Archive 2 — `docs/dev/` working files

| | |
|---|---|
| Path | `/var/backups/dot-claude-docs-dev-backup-20261005/docs-dev-20261005.tar.gz` |
| Compressed size | 741,735,451 bytes (~708M) |
| Source size | 2.4G (~3.3x compression) |
| Time taken | 1m17s |
| Filesystem | ext4 (`/dev/sda1`, persistent) |
| Method | a plain compressed tar of the directory tree, read-only against the source |

`docs/dev/` is gitignored and has never been part of git history — it is tracked here as a second, separate archive for exactly that reason; the git bundle above does not and cannot cover it. It contains, among other things, a 722-line / 164K spec (`specs/spec-20260808-035658.md`) whose role-split views were still being read as recently as 2026-09-13 — an active working asset, not leftover scratch.

**`.gitignore` was never a risk here, confirmed:** this is a plain filesystem copy, not a git operation. A plain `tar` has no concept of `.gitignore` at all — it was never consulted, so every gitignored file under `docs/dev/` is in the archive, which is the entire point of taking this backup separately from the git bundle. Confirmed the source's own mtimes are byte-for-byte unchanged after archiving (archiving only reads).

**Verified by hash, not by inspection:** six files were extracted from the finished archive into a throwaway scratch directory and compared against the live source by `sha256sum` — the spec file itself, plus all five role views (`qa.md`, `dev.md`, `pm.md`, `ba.md`, `orchestrator.md`). All six: identical hash, source vs. archive.

**To restore:** extract the tar archive into the target directory.

## Leftovers, left in place rather than routed around

Two throwaway scratch directories from this backup work are still on disk, both harmless, both pending the operator's manual removal (automated deletion hit the standing blanket `rm`-forbidden safety gate both times, and per standing instruction that gate was not routed around):
- `/var/tmp/dot-claude-restore-test-20261005/` — a mirror-clone of Archive 1, used to verify the git bundle.
- `/var/tmp/docs-dev-restore-check-20261005/` — six files extracted from Archive 2, used for the hash check above.
