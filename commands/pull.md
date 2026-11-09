---
description: "Pull Command"
disable-model-invocation: true
---

# Pull Command

Safe `git pull --rebase` with automatic stash management and conflict detection, then an advisory analysis of what arrived. `<HARNESS_ROOT>/hooks/pull.sh` does the pull; `<HARNESS_ROOT>/scripts/steps/pull-run.py` runs it and reads what changed.

## Usage

```
/pull
```

## Command Implementation

Steps 0-4 are one script call, in Step 1. Its facts are read by key below.

### Step 0: Capture pre-pull HEAD

Step 1's script reads `PRE_PULL_HEAD` and `BRANCH` before it runs the pull.

### Step 1: Execute the pull script

```bash
python3 "<HARNESS_ROOT>/scripts/steps/pull-run.py" run
```

`pull.sh`'s own output (stash, rebase, conflict list) comes first, unchanged. After the line `--- pull-run ---` come `KEY=value` lines: `PRE_PULL_HEAD`, `POST_PULL_HEAD`, `BRANCH`, `PULL_EXIT_CODE`, `REBASE_STATE` (`yes` when a rebase is stopped mid-way), `PULL_EXIT_PHASE` and `ACTION`. The call itself ends with status 0 whatever `pull.sh` did.

### Step 2: Capture post-pull HEAD

`POST_PULL_HEAD` is read whatever the exit code: `pull.sh` can move HEAD in a rebase that then stops on a conflict, and after a rebase that finished but whose stash pop failed.

### Step 3: No-op check (exit 0, HEAD unchanged)

`ACTION=no_change`: print "No HEAD change (pull was no-op or cancelled). Skipping pull-analyst." and stop.

### Step 4: Determine pull_exit_phase

`PULL_EXIT_PHASE` is decided by the script; act on `ACTION`:

| `PULL_EXIT_PHASE` | When | `ACTION` |
|---|---|---|
| `success` | exit code 0 | `analyze` (`no_change`: Step 3) |
| `stash_restoration_failed` | exit code not 0, no rebase stopped, HEAD moved: the rebase finished, the stash pop failed, the local changes remain in `stash@{0}` | `analyze` |
| `rebase_conflict` | exit code not 0 and `REBASE_STATE=yes` | `stop` |
| `rebase_conflict` | exit code not 0, no rebase, HEAD unchanged: a failure before the rebase (no upstream, detached HEAD, stash or lock failure), classified the same way | `stop` |

On `ACTION=stop`, do not dispatch pull-analyst. Show the user `pull.sh`'s error output. With `REBASE_STATE=yes`, add: "Resolve conflicts, then run: git rebase --continue" and "Or abort the rebase: git rebase --abort". Then stop.

### Step 5: Dispatch pull-analyst subagent

On `ACTION=analyze`, dispatch the `pull-analyst` subagent (`run_in_background: false`) with this context, filled from the facts:

```
PRE_PULL_HEAD=<PRE_PULL_HEAD>
POST_PULL_HEAD=<POST_PULL_HEAD>
BRANCH=<BRANCH>
PULL_EXIT_PHASE=<PULL_EXIT_PHASE>
```

Wait for it to complete.

### Step 6: Display pull-analyst report

Display the advisory report to the user. It is informational only and gates no later command.

### Post-pull Graphify update (advisory, non-blocking)

After Step 6, refresh the global knowledge graph with the pulled commits:

```bash
python3 "<HARNESS_ROOT>/scripts/steps/pull-run.py" graphify
```

It never blocks the pull or asks for confirmation: it ends with status 0, and a failure is a line on stderr. With no Graphify CLI or `CLAUDE_GRAPHIFY_ENABLED=0` it does nothing.
