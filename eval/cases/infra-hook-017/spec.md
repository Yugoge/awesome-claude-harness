# Infra-Hook Eval Case infra-hook-017: standalone script — cleanup-stale-checkpoints.sh

## Trigger
Standalone bash script invoked manually or via a systemd timer. Not a
Claude Code hook — this case exercises housekeeping infrastructure.

## Behavior Required
- Accepts two parameters: `RETENTION_DAYS` (positional 1, required)
  and `CHECKPOINT_REPO_PATH` (positional 2, default `/root`).
- Validates inputs: `RETENTION_DAYS` must be a positive integer; the
  repo path must contain a `.git` directory.
- Lists checkpoint refs via `git for-each-ref refs/checkpoints/`
  inside the target repo.
- For each ref older than `RETENTION_DAYS` days (by committer date),
  invokes `git update-ref -d <refname>` to remove it.
- Prints a summary to stdout: `removed: N, kept: M`.

## Exit Code Contract
- exit 0: cleanup completed (zero or more refs removed).
- exit 2: input validation failed OR target is not a git repo OR a
  `git` invocation returned non-zero.

## Acceptance
- AC-1: invoking with `RETENTION_DAYS=0` removes all checkpoint refs.
- AC-2: invoking with non-numeric retention yields exit 2 with stderr
  citing the validation error.
- AC-3: stdout summary line matches the regex `^removed: \d+, kept: \d+$`.
