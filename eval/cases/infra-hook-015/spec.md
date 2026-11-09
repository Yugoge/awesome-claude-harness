# Infra-Hook Eval Case infra-hook-015: settings.json — rebind hook matcher

## Trigger
Not a hook execution event. This case exercises a settings.json edit
that changes a hook entry's `matcher` field from one tool name to
another.

## Behavior Required
- Locate `~/.claude/settings.json` and find the `hooks` object.
- Identify the hook entry whose `command` references a target script
  path (for example `pretool-edit-confirm.py`).
- Update its `matcher` field from the old value to the new value
  (e.g., `Edit` -> `Edit|MultiEdit`) without touching any sibling key.
- Preserve the file's original ordering and 2-space indentation.
- Do NOT introduce duplicate hook entries.

## Exit Code Contract
- exit 0: matcher rebound successfully.
- exit 2: target hook entry not found OR malformed JSON OR write failed.

## Acceptance
- AC-1: after the edit, `jq` extraction of the targeted hook's
  `matcher` returns the new value.
- AC-2: count of total hook entries before vs. after the edit is
  unchanged.
- AC-3: settings file passes `jq '.' > /dev/null` JSON validity check
  post-edit.
