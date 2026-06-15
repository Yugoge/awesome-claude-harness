# Nested Repo Sentinel

> **Purpose**: This file marks a symlink boundary. The directory you are in is **not** tracked by `/root/.git` -- it is tracked by a separate git repo at the symlink target.

## Topology

- **You are in**: `/root/.claude/` (symlink)
- **Real path**: `/dev/shm/dev-workspace/dot-claude/` (tmpfs, RAM-backed)
- **Git repo**: `/dev/shm/dev-workspace/dot-claude/.git`
- **Remote**: `git@github.com:Yugoge/awesome-claude-harness.git`
- **Passive mirror** (read-only): `/root/.claude.bak/` (rsync every 5 min via `/root/sync-backup.sh`)

## The trap this file prevents

Running `git log -- .claude/commands/spec.md` from `/root` returns **empty output, exit 0**. This is NOT "no history" -- it is "wrong repo". `/root/.git` records `.claude` as a mode-120000 symlink blob, so its content is never under `/root` tracking. Always query the nested repo:

```bash
cd /root/.claude && git status
cd /root/.claude && git log -- commands/spec.md
cd /root/.claude && git show <sha> -- commands/spec.md
git -C /dev/shm/dev-workspace/dot-claude log --oneline
```

`cd /root/.claude` works because the shell follows symlinks; you land in the real tmpfs directory and standard git commands operate on the nested repo.

## Do not commit into the wrong place

- Edits to files under `.claude/` must be committed inside `/dev/shm/dev-workspace/dot-claude` (or via `cd /root/.claude && git commit`).
- Do **not** `git push` from `/root` for `.claude/*` changes -- that targets the parent repo, which only tracks the symlink blob.
- Do **not** edit files in `/root/.claude.bak/` -- it is a passive rsync mirror; changes will be overwritten within 5 minutes.

## Cross-references

- Parent project memory: `/root/CLAUDE.md` (see "Nested Git Repo" section)
- Full architecture: [`ARCHITECTURE.md`](ARCHITECTURE.md) §11 (ramdisk + nested-repo rationale)
- Sync script: `/root/sync-backup.sh`
