---
description: Read-only Unfuddle-style lifecycle table of every ticket/spec/lane.
argument-hint: "[--format table|json]"
---

# /tickets

Read-only lifecycle table. Runs `scripts/dev-lifecycle.py scan` and renders
the result. Never writes to `docs/dev/`, `.git` (HEAD/refs/index/worktree), or
any commit-grant or bulk-commit-sentinel file: the scan writes nothing at all.

It answers the owner's requirement for an always-available table showing what
state every ticket and every spec has reached in the development lifecycle,
like Unfuddle.

## Invocation

```
/tickets                # table view (default)
/tickets --format json  # machine-readable
```

## Workflow

1. Parse `--format` from `$ARGUMENTS` (`table` default, `json` optional). Any
   other token in `$ARGUMENTS` is ignored (this command takes no task-id).
2. Run:
   ```bash
   PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
   source "${CLAUDE_HOME:-$HOME/.claude}/venv/bin/activate" 2>/dev/null || true
   python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/dev-lifecycle.py" scan --format "$FORMAT" --project-dir "$PROJECT_ROOT"
   ```
3. Print the command's stdout verbatim to the user. Do not re-interpret,
   summarize, or filter the rows — this command's entire job is to surface the
   scanner's own read-only derivation.

## State reference (`scripts/dev-lifecycle.py`)

| State | Meaning | `next_action` |
|---|---|---|
| `analyzed` | a ticket or ba-spec with no dev-report, ba-qa-report or do-report yet | `develop` |
| `ba_approved` | no dev-report; ba-qa-report verdict pass | `develop` |
| `ba_rejected` | no dev-report; ba-qa-report verdict fail | `resume_ba` |
| `close_pending` | no close-report yet, and either a dev-report (its one chain call, `scripts/resolve-dev-artifact-chain.py`, passing or not, since `/close` routes an incomplete chain's gaps to their producers; its result carried whole as `artifact_chain`) or a do-report whose terminal status is `completed` | `close` |
| `close_failed` | close-report's last-line verdict (`hooks/lib/close-verdict.py`) is `no`/`unknown` | `resume_close` |
| `commit_pending` | close-report verdict `yes`; not every task-owned repo proven committed | `commit` |
| `committed` | every task-owned repo has a HEAD-reachable `Task-id:` trailer and zero dirty owned content | `none` |
| `blocked` | a chain instrument failure (a failing aggregator, reported as a scan exception), a malformed or unreadable ba-qa-report, do-report or close-report (a do-report not `completed` included), a repository-plan error, `PARTIAL_COMMIT`, or a scan exception | `inspect` |
| `analysis_pending` | a spec row with no linked ticket | *(none)* |

Row taxonomy: `kind ∈ {spec, ticket, lane}`. Lane rows (fan-out children) are
always visible but never independently actionable — only `kind == "ticket"`
parent rows ever carry a `close`/`commit` `next_action`.

## Constraints

- Read-only across the full disk surface (see the guarantee above). If a scan
  cannot determine a task-id's state without crashing, it reports
  `state=blocked, next_action=inspect` for that row and continues scanning
  every other task-id — one malformed artifact never aborts the whole table.
- `/tickets` never invokes `/close`, `/commit`, or any agent subagent. It is a
  read of `docs/dev/` and of git (`log`, `status`), one chain call per open
  dev task, and a stdout render; nothing is cached.
