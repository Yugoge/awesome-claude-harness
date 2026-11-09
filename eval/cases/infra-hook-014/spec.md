# Infra-Hook Eval Case infra-hook-014: settings.json — add new permission entry

## Trigger
Not a hook execution event. This case exercises a settings.json edit
that adds a new bash-pattern permission to the `allow` array.

## Behavior Required
- Locate the project settings file at `~/.claude/settings.json`.
- Read the current JSON object and find the
  `permissions.allow` array.
- Insert a new permission string of the form
  `Bash(scripts/<verb>-<noun>.sh:*)` in lexicographic order with the
  surrounding entries.
- Preserve all other top-level keys, indentation (2 spaces), and the
  trailing newline.
- Do NOT add the same entry twice; the operation is idempotent.

## Exit Code Contract
- exit 0: edit applied (or already present and idempotency triggered).
- exit 2: settings file missing OR malformed JSON OR write failed.

## Acceptance
- AC-1: after the edit, `jq '.permissions.allow | length'` increases
  by exactly 1 (or stays equal if already present).
- AC-2: re-running the edit a second time leaves the file byte-identical
  to the first-run result.
- AC-3: malformed input file (missing closing brace) yields exit 2 and
  the original file is untouched.
