# commands

<!-- AUTO:index-stats -->
*Last updated: 2026-10-05T03:51:03Z*
**Total entries**: 21
**Convention**: kebab

## Tree
```
commands/
├── `allow.md` - Single-use break-glass for a declared grant-aware safety hook; it never overrides a settings DENY. Forms — /allow <command...> (literal, upgraded to regex only when it contains true regex metacharacters), /allow --tool <literal> (always literal, regex off), or /allow re:<anchored-regex> (explicit regex, must be anchored). Bare /allow with no argument is the owner-authorized match-all selector, still single-use and TTL-bounded; every explicit selector is refuse-by-default when no narrow command is derivable. A literal selector matches as a POSITIONAL PREFIX of the argument tokens, not a substring. When the head token is git, repo-retargeting global options (-C, --git-dir, --work-tree, --namespace) are skipped so a short selector reaches the canonical `git -C <dir> <verb>` shape; -c / --config-env / --exec-path are never skipped and fail closed. Trailing tokens become an audit-log comment. Sentinel TTL 300s, consumed on any terminal result.
├── `checkpoint.md` - Checkpoint Command
├── `clean.md` - Aggressive project cleanup - normalize docs structure, archive everything, delete one-time scripts/tests. Pass --codex to enable adversarial codex consultation on cleanliness-inspector and style-inspector; default is self-review only.
├── `close.md` - Close the current dev cycle (agent infers task-id from conversation). QA evaluates Workflow Integrity bullets and returns CLOSE YES/with-disclosures. Pass --codex to enable multi-round QA-codex debate; default is QA-only single-round assessment. --force is DEPRECATED -- a no-op alias of the normal path (audit-logged, skips nothing). Pass --auto to discover and sequentially close every close_pending parent (see `--auto mode` below).
├── `codex.md` - Delegate a task to OpenAI Codex CLI (gpt-5.6-sol, xhigh reasoning) for a second opinion or parallel coding
├── `commit.md` - Commit session changes via changelog-analyst subagent
├── `dev-command.md` - Enhanced development workflow with BA subagent delegation, command development best practices, Three-Party Architecture, and comprehensive automation patterns
├── `dev-overnight.md` - Autonomous overnight development loop - continuously explores codebase, finds issues, fixes them, and repeats until end-time
├── `dev.md` - Orchestrated development workflow with BA subagent delegation, parallel agent execution, and iterative QA verification. Pass --codex to enable adversarial codex consultation on each subagent's draft; default is self-review only.
├── `do.md` - Allow main agent to bypass orchestrator-gate restrictions for this turn (subagent-only operations become directly allowed). Auto-clears at stop.
├── `merge.md` - Merge a branch into the default branch, on either a linked (registered_worktree) worktree or an in_place one (the main checkout -- see commands/dev-overnight.md's isolation_kind vocabulary). On a linked worktree, the agent infers the branch from active overnight state, auto-removes the worktree, deletes the merged branch, and removes the overnight-state file. In_place, the agent merges the current (or explicit) branch directly in the main root, requires a clean tree first, and keeps the branch afterward. Bare /merge typical; explicit /merge <branch> overrides.
├── `paseo-daemon.md` - paseo multi-session monitoring and three-account dynamic scheduling control plane — bootstrap of a persistent disk-backed state machine (blueprint F1–F15, amended 22-entry runtime baseline). Human-only.
├── `pull.md` - Pull Command
├── `push.md` - Push Command
├── `redev.md` - dev workflow harness re-attach — for conversations where the /dev workflow context has already appeared; may be invoked with no new requirement text to purely re-attach the harness (canonical TodoList, gates, dev-registry, artifact conventions) to that context. Pass --codex to enable adversarial codex consultation on each subagent's draft; default is self-review only.
├── `restart.md` - Resume every quota-interrupted subagent in the current Claude Code parent session from its original transcript and agent ID; when none is recoverable, continue the invoking session's own main agent.
├── `spec-update.md` - Update an existing spec, continue unfinished development, or write a temp session note.
├── `spec.md` - Create spec files for any dev workflow (/dev, /dev-overnight, or standalone reference). Pass --codex to enable adversarial codex consultation on each spec-subagent / QA dispatch; default is self-review only.
├── `stop.md` - Cancel active overnight time-lock + workflow-enforce so the session can terminate normally. User-invoked only — agents cannot self-stop.
├── `test.md` - Test validation workflow with edge case detection, systematic validation, and quality enforcement
└── `tickets.md` - Read-only Unfuddle-style lifecycle table of every ticket/spec/lane.
```
<!-- /AUTO:index-stats -->

---
*Auto-generated by doc-sync hook.*