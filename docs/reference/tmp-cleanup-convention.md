# Ad-hoc scratch directory convention

> Last updated: 2026-05-19 (dev-20260519-161035)

When a script/hook/subagent needs a transient scratch directory under `/tmp`,
name it `<purpose>-scratch-<timestamp>` (timestamp must start with a digit so
the cleanup glob `*-scratch-[0-9]*` matches).

Example: `dev-scratch-1779000000`, `qa-fixtures-scratch-20260519`.

## Cleanup

The hourly cron at `/etc/cron.d/tmp-cleanup` (`scripts/install/tmp-cleanup.cron`) invokes
`/usr/local/sbin/tmp-cleanup.sh`, which sweeps `*-scratch-[0-9]*` at the
**>3-day** age tier. Files newer than 3 days are left alone.

## No hook enforcement — convention only

There is no PreToolUse / SessionStart / UserPromptSubmit hook that validates
this naming. Code that omits the suffix keeps working; it just is not
swept automatically. See `/usr/local/sbin/tmp-cleanup.sh` for the sweep
implementation.
