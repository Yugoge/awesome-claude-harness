---
description: Read-only Unfuddle-style lifecycle table of every ticket/spec/lane.
argument-hint: "[--format table|json]"
---

# /tickets

Read-only lifecycle table. Runs `scripts/dev-lifecycle.py scan` and renders
the result. Never writes to `docs/dev/`, `.git` (HEAD/refs/index/worktree), or
any `/tmp` commit-grant or bulk-commit-sentinel file — its ONLY permitted
mutation anywhere on disk is the disposable SQLite cache at
`.claude/cache/dev-lifecycle.sqlite3` (rebuilt wholesale on every run, never
merged with the prior run's rows).

Root-cause reference: `docs/dev/ticket-20260808-035658-lanel.md` (5.2 — the
user's requirement for an always-available table showing what state every
ticket and every spec has reached in the development lifecycle, like
Unfuddle; verbatim original preserved in that ticket file).

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
   PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
   source ~/.claude/venv/bin/activate 2>/dev/null || true
   python3 scripts/dev-lifecycle.py scan --format "$FORMAT" --project-dir "$PROJECT_ROOT"
   ```
3. Print the command's stdout verbatim to the user. Do not re-interpret,
   summarize, or filter the rows — this command's entire job is to surface the
   scanner's own read-only derivation.

## State reference (Required State Reducer, `scripts/dev-lifecycle.py`)

| State | Meaning | `next_action` |
|---|---|---|
| `analyzed` | ticket+context exist, BA-QA loop not yet run (or predates it) | `develop` |
| `ba_approved` | ba-qa-report verdict pass | `develop` |
| `ba_rejected` | ba-qa-report verdict fail | `resume_ba` |
| `developing` | dev-report exists, dev.status != completed | `wait` |
| `qa_pending` | dev completed, no qa-report yet | `resume_qa` |
| `qa_failed` | canonical qa.status != pass | `resume_dev` |
| `close_pending` | close-eligible (do-report, singular resolver pass, or fan-out roster-complete); no close-report yet | `close` |
| `close_failed` | close-report's strict last-line verdict is `no`/`unknown` | `resume_close` |
| `commit_pending` | close-report verdict `yes`; not every task-owned repo proven committed | `commit` |
| `committed` | every task-owned repo has a HEAD-reachable `Task-id:` trailer and zero dirty owned content | `none` |
| `blocked` | malformed artifact, resolver failure on a roster-incomplete/singular chain, duplicate ticket/ba-spec naming, or `PARTIAL_COMMIT` | `inspect` |
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
  pure filesystem read + SQLite cache rebuild + stdout render.
