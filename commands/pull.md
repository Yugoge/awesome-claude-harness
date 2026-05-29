---
description: "Pull Command"
disable-model-invocation: true
---

# Pull Command

Execute safe git pull with automatic stash management and conflict detection.

## Usage

```
/pull
```

## Command Implementation

### Step 0: Capture pre-pull HEAD

```bash
PRE_PULL_HEAD=$(git rev-parse HEAD)
BRANCH=$(git rev-parse --abbrev-ref HEAD)
```

### Step 1: Execute the pull script

```bash
bash ~/.claude/hooks/pull.sh
PULL_EXIT_CODE=$?
```

### Step 2: Capture post-pull HEAD

Always capture, regardless of exit code — pull.sh may change HEAD during a partial
rebase before a conflict (line 151 exit), or after a fully successful rebase before
stash pop fails (line 174 exit):

```bash
POST_PULL_HEAD=$(git rev-parse HEAD)
```

### Step 3: No-op check (exit 0, HEAD unchanged)

```
if PULL_EXIT_CODE == 0 AND PRE_PULL_HEAD == POST_PULL_HEAD:
    Print: "No HEAD change (pull was no-op or cancelled). Skipping pull-analyst."
    Stop.
```

### Step 4: Determine pull_exit_phase

```
if PULL_EXIT_CODE == 0:
    pull_exit_phase = "success"
    proceed to Step 5

else (PULL_EXIT_CODE != 0):
    Check for rebase state directories (worktree-aware paths):
        REBASE_MERGE=$(git rev-parse --git-path rebase-merge 2>/dev/null || echo ".git/rebase-merge")
        REBASE_APPLY=$(git rev-parse --git-path rebase-apply 2>/dev/null || echo ".git/rebase-apply")
        rebase_state_exists = test -d "${REBASE_MERGE}" OR test -d "${REBASE_APPLY}"

    if rebase_state_exists:
        pull_exit_phase = "rebase_conflict"
        # Rebase stopped mid-operation; HEAD may have changed but rebase is in progress.
        # The rebase-state-directory is the primary discriminant.
        Display pull.sh error output.
        Print guidance: "Resolve conflicts, then run: git rebase --continue"
        Print guidance: "Or abort the rebase: git rebase --abort"
        STOP — do NOT dispatch pull-analyst.

    else if NOT rebase_state_exists AND PRE_PULL_HEAD != POST_PULL_HEAD:
        pull_exit_phase = "stash_restoration_failed"
        # Rebase fully succeeded (HEAD advanced past line 154 success message);
        # then stash pop failed at pull.sh line 174.
        # No rebase state remains because rebase completed cleanly.
        proceed to Step 5

    else (NOT rebase_state_exists AND PRE_PULL_HEAD == POST_PULL_HEAD):
        pull_exit_phase = "rebase_conflict"
        # Unknown pre-rebase failure; HEAD unchanged; classify conservatively.
        Display pull.sh error output.
        STOP — do NOT dispatch pull-analyst.
```

### Step 5: Dispatch pull-analyst subagent

Dispatch the `pull-analyst` subagent with the following context (only reached for
`pull_exit_phase = "success"` or `pull_exit_phase = "stash_restoration_failed"`):

```
PRE_PULL_HEAD=<PRE_PULL_HEAD>
POST_PULL_HEAD=<POST_PULL_HEAD>
BRANCH=<BRANCH>
PULL_EXIT_PHASE=<pull_exit_phase>
```

Wait for the subagent to complete.

### Step 6: Display pull-analyst report

Display the pull-analyst advisory report to the user. The report is informational only —
it does not gate any future command.

### Post-pull Graphify update (advisory, non-blocking)

After displaying the pull-analyst report, run a non-blocking incremental Graphify cache update. This ensures the global knowledge graph reflects the newly pulled commits.

```bash
source "${CLAUDE_PROJECT_DIR}/venv/bin/activate" && python3 "$CLAUDE_PROJECT_DIR/scripts/graphify-maintain.py" update
```

This call is advisory: if GRAPHIFY_BIN is absent, CLAUDE_GRAPHIFY_ENABLED=0, or the cache is unavailable, it exits 0 immediately with a status=unavailable message. The update MUST NOT block the pull workflow or require user confirmation. Failure is silent (logged to stderr only).

## Related Commands

- `/push` - Push changes with untracked file detection
- `git status` - Check current working directory state

The implementation is in `~/.claude/hooks/pull.sh`.
