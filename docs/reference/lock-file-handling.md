# Git Lock File Handling

## Overview

The push.sh and pull.sh scripts automatically detect and handle git lock file conflicts.

## What Is a Git Lock File?

Git uses .git/index.lock to prevent multiple processes from modifying the repository
simultaneously. This file is created when a git operation starts and deleted when it completes.

## Problem Scenarios

A lock file may be left behind when:
- A git process was forcefully interrupted (Ctrl+C)
- The system crashed or restarted
- A process hung or became unresponsive

## Error Message Example

```
fatal: Unable to create '/path/to/repo/.git/index.lock': File exists.
Another git process seems to be running in this repository
```

## Auto-Detection

### Push script (hooks/push.sh)

Detects lock files automatically at Step 7 (before creating a commit):

1. **Detect lock file** -- if .git/index.lock exists, display a warning
2. **Check for active processes** -- inspect running processes; if another git process is active, exit with a prompt to wait
3. **Handle stale lock** -- if no active process is found, prompt: Remove the lock file and continue? (y/n); on confirmation, delete and continue

### Pull script (hooks/pull.sh)

Same logic as push, at Step 4 (before executing the pull).
**Special handling**: if a stash was already created, it is restored before exiting on failure.

## User Experience

### Scenario 1: Stale lock file (most common)

```
  Warning: Git lock file detected

A lock file exists at: .git/index.lock
No active git processes detected.
The lock file appears to be stale (from a crashed process).

Remove the lock file and continue? (y/n)
```

**User action**: type `y` to continue; the script cleans up and proceeds automatically.

### Scenario 2: Active git process

```
  Warning: Git lock file detected

Active git processes found:
user  12345  0.1  0.2  git fetch origin

Please wait for other git operations to complete.
```

**User action**: wait for the other process to finish, then re-run the script.

## Manual Cleanup (if needed)

If auto-cleanup fails, manually delete the lock file:

```bash
rm .git/index.lock
```

**Note**: only do this when you are certain no other git process is running.

## Safety

Safe guards in place:
- Always checks for active processes before deleting
- Requires user confirmation before deletion
- Provides clear error messages and recommendations

Will NOT auto-delete when:
- An active git process is detected
- The user declines the confirmation

## Tests

```bash
bash ~/.claude/tests/test-lock-detection.sh
```

Test coverage:
1. Lock file detection
2. Git process detection
3. Lock file deletion
4. Git operation recovery

## Technical Implementation

### Detection code

```bash
LOCK_FILE=".git/index.lock"
if [ -f "$LOCK_FILE" ]; then
  GIT_PROCESSES=$(ps aux | grep -i '[g]it' | grep -v grep || true)

  if [ -n "$GIT_PROCESSES" ]; then
    echo "Please wait for other git operations to complete."
    exit 1
  else
    read -r RESPONSE
    if [ "$RESPONSE" = "y" ]; then
      rm -f "$LOCK_FILE"
    fi
  fi
fi
```

### Integration points
- **push.sh**: Line 129-172 (Step 7)
- **pull.sh**: Line 55-117 (Step 4)

## Improvement History

**Version 1.1** (2025-10-28)

- Added automatic lock file detection
- Smart distinction between active processes and stale files
- User confirmation mechanism
- Protect stash contents in the pull script

**Version 1.0** (initial)
- Basic push/pull functionality
- No lock file conflict handling

## FAQ

**Q: Why do lock files appear?**
A: Usually because a git operation was interrupted (Ctrl+C) or the system crashed.

**Q: Is it safe to delete the lock file?**
A: Only when no other git process is running. The script checks automatically.

**Q: What if I choose "n" to decline deletion?**
A: The script exits. Handle it manually or re-run the script.

**Q: Will data be lost?**
A: No. The lock file is only a locking mechanism; deleting it does not affect code content.

## Related Files

- hooks/push.sh -- push script (with lock detection)
- hooks/pull.sh -- pull script (with lock detection)
- tests/test-lock-detection.sh -- lock file detection tests
- docs/git-tracking-solution-plan.md -- full implementation plan

## Contributing

If you find a bug or have a suggestion, please open an issue in the project.