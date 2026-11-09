# Infra-Hook Eval Case infra-hook-016: settings.json — add env var entry

## Trigger
Not a hook execution event. This case exercises a settings.json edit
that adds an entry to the `env` object so subprocesses launched by
Claude Code inherit the variable.

## Behavior Required
- Locate `~/.claude/settings.json` and find the top-level `env` object.
- Insert a new `KEY: "value"` pair in alphabetic key order.
- If the `env` object does not exist, create it with the new entry
  as the sole member.
- Validate that the value is a string (no booleans, numbers, or null).
- Preserve all other top-level fields and indentation.

## Exit Code Contract
- exit 0: env entry added (or updated to the same value, idempotent).
- exit 2: file malformed OR value is not a string OR write failed.

## Acceptance
- AC-1: `jq '.env.NEW_KEY'` returns the inserted string value
  post-edit.
- AC-2: re-running the operation with the same key/value yields a
  byte-identical file.
- AC-3: passing a non-string value (e.g., a number) yields exit 2
  with stderr naming the type error.
