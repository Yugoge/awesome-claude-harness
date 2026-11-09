---
description: Read-only Unfuddle-style lifecycle table of every ticket/spec/lane.
argument-hint: "[--format table|json]"
---

# /tickets

Prints the lifecycle table that `scripts/dev-lifecycle.py scan` derives from `docs/dev/` and git. Read-only: the scan writes nothing (not `docs/dev/`, not git refs, index or worktree, not grant or sentinel files), and `/tickets` never invokes `/close`, `/commit` or a subagent.

## Workflow

1. `--format` in `$ARGUMENTS` is `table` (default) or `json`. Any other token is ignored: there is no task-id.
2. Run this one call, with `<FORMAT>` the format from step 1:
   ```bash
   python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/dev-lifecycle.py" scan --format <FORMAT> --project-dir "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
   ```
3. Print its stdout verbatim. Do not summarize, filter or re-interpret the rows.

## State reference (`scripts/dev-lifecycle.py`)

| State | Meaning | `next_action` |
|---|---|---|
| `analyzed` | a ticket or ba-spec with no dev-report, ba-qa-report or do-report yet | `develop` |
| `ba_approved` | no dev-report; ba-qa-report verdict pass | `develop` |
| `ba_rejected` | no dev-report; ba-qa-report verdict fail | `resume_ba` |
| `close_pending` | no close-report, and a dev-report (its chain result, passing or not, is carried whole as `artifact_chain`) or a well-formed do-report of any status (`/close` routes one that is not `completed` to dev) | `close` |
| `close_failed` | the close-report's last-line verdict (`hooks/lib/close-verdict.py`) is `no` or `unknown` | `resume_close` |
| `commit_pending` | close-report verdict `yes`; no task-owned repo has a HEAD-reachable `Task-id:` trailer yet | `commit` |
| `committed` | every task-owned repo has a HEAD-reachable `Task-id:` trailer and no dirty owned content | `none` |
| `blocked` | a malformed or unreadable ba-qa-report, do-report or close-report, a repository-plan error, `PARTIAL_COMMIT` (mixed commit evidence), or a scan exception (a failing chain aggregator included) | `inspect` |
| `analysis_pending` | a spec row with no linked ticket | empty |

`kind` is `spec`, `ticket` or `lane`. Lane rows (fan-out children) are always listed but never actionable: only `ticket` rows carry a `close` or `commit` `next_action`. A task the scan cannot read is `blocked` on its own row; the other rows are still listed.
