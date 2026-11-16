# lib

<!-- AUTO:index-stats -->
*Last updated: 2026-11-10T08:16:38Z*
**Total entries**: 64
**Convention**: kebab

## Tree
```
lib/
├── runtime_guard/
│   ├── `_core.py` - This module contains ZERO project identifiers. Every project-specific name
│   ├── `anchor.py` - The cleanly-extractable leaf subset of the HEAD-AGNOSTIC P0 anchor scan
│   ├── `config.py` - Depends on shell_lex (`_strip_quotes`, `_has_redirect_to`) + pathmatch
│   ├── `constants.py` - Dependency LEAF: defines only literal frozenset/dict constants, imports nothing,
│   ├── `context.py` - `_core.evaluate` computes a small set of per-EVALUATION inputs ONCE — the
│   ├── `find_cmds.py` - Depends on shell_lex (`_strip_quotes`) + pathmatch (`_glob_to_segment_regex`,
│   ├── `git_cmds.py` - Depends on shell_lex (`_strip_quotes`) + pathmatch (`_expand_leading_home`) +
│   ├── `pathmatch.py` - Depends only on shell_lex (`_strip_quotes`) + stdlib; references nothing from
│   └── `shell_lex.py` - Dependency LEAF: imports only the stdlib, references nothing from _core
├── write_gate/
│   └── `overwrite.py` - The Python form of hooks/pretool-write-guard.sh, decision for decision and message for
├── `agent_cycle.py` - producer (posttool-codex-skill-ledger.py) and the hooks that read a cycle's
├── `agent_resolver.py` - Refactored from pretool-subagent-code-block.py::_find_agent_type so that
├── `allowlist.py` - The /allow grant file's one writer (write_sentinel_grant) and its readers,
├── `attribution_journal.py` - Capture side (used by pretool-attribution-pre.py / posttool-attribution-post.py):
├── `auto_push.sh` - auto_push.sh -- harness_auto_push, the one reader of the per-repository push switch.
├── `bash_active_syntax_census.py` - WHY THIS MODULE EXISTS (spec-20260808-035658 LANE-POL, Must-2 "completeness
├── `bash_context_strip.py` - This is deliberately NOT a full shell parser.  It only computes a conservative
├── `bash_execution_boundary.py` - THE ALGEBRA (spec-20260808-035658 LANE-POL, Must-1).  Every execution-bearing
├── `bash_write_targets.py` - Provides two public functions used by tool-policy and overnight-hook-guard:
├── `capability_state.py` - verdict, and the INDEPENDENT (non-hook-dispatched) preactivation consumer
├── `checkpoint-core.sh` - checkpoint-core.sh - Shared library for automated snapshot commits
├── `claude_home.py` - Generalizes the in-repo gold-standard fail-closed self-resolution pattern
├── `claude_home.sh` - claude_home.sh — shared "harness home" resolver (shell consumable).
├── `close-verdict.py` - The one rule every reader of a close verdict applies: classify the close
├── `close_rating.py` - The owner's close rating: handle() writes its row and returns the owner summary; the predicates P5's Stop gate imports.
├── `closeout.py` - CLI:
├── `command_span.py` - rule of which transcript record is a prompt the human typed
├── `commit_journal.py` - WHY THIS EXISTS
├── `commit_pipeline.py` - ONE home for the two questions the commit-authorization chain could not
├── `contract_runtime.py` - This module is the single shared engine consumed by every contract-aware
├── `declared_paths.py` - hooks/pretool-tool-policy.py decides who may write a path a dispatch of the
├── `dev_loop_checks.py` - Five hooks held these checks (pretool-layer-escalation-check.sh, pretool-bisect-gate.sh,
├── `dev_report_shard_patterns.py` - Single source for the per-worker / canonical dev-report filename regexes and
├── `dispatch_template.py` - A dispatch made from a base template before a merge carries no obligation block
├── `do_report.py` - `docs/dev/do-report-<task_id>.json` has one producer, the /do main agent. Every
├── `gate_runner.py` - Claude Code starts every hook registered on an event at once, so two hooks that
├── `git_clean_guard.py` - Classifies ONE Bash command for the fail-closed pre-clean guard woven into the
├── `git_command_classifier.py` - Provides iter_git_invocations() — a token-aware parser that detects git
├── `grepguard_context_strip.py` - PURPOSE (narrow, guard-specific)
├── `harness_state_dir.py` - Hook runtime state (consent flags, grants, sentinels, bookmarks, stamps) lives
├── `harness_state_dir.sh` - harness_state_dir.sh -- shell twin of hooks/lib/harness_state_dir.py.
├── `interruption_signals.py` - Decides whether a subagent was cut off — and whether a usage limit did it — from
├── `merge_grant.py` - The merge-analyst writes its grant with the Write tool at
├── `obligation.py` - Rollout step S2 of the converged zero-failure design
├── `overnight.py` - The state record `<main root>/.claude/overnight-state-<sid>.json` has one producer,
├── `pol_degraded_removal_reference.ere` - ere file
├── `policy_registry.py` - Reads the harness ``policies/tool-policy.v1.json`` (resolved via the shared
├── `roster.py` - A role exists because ``agents/<role>.md`` exists and opens with YAML front
├── `rule_runner.py` - A merged gate (hooks/pretool-write-gate.py) holds several rules that were
├── `runtime_guard.py` - This file exists for backwards-compatibility with callers that invoke
├── `schema_registry.py` - Reads schemas/registry.json once and lazily loads referenced schema files
├── `score_events.py` - Score events from facts: sweep() appends the active span's events to the score log; observe() is the dispatch hook's entry.
├── `score_log.py` - and views are computed on read, never stored. Rows: event {kind, ts, project, task_id, role, even...
├── `score_view.py` - What a score shows at a dispatch and what a low one costs (D29, D32): the readers of the score log that hooks call. They read the log and the
├── `scratch_owner.py` - hooks/session-scratch-init.sh writes <root>/<sid>/.owner = {"sid": ..., ...}. One rule reads
├── `session_resources.py` - Every destructive operation is bound to an immutable resource session and a
├── `spec_path.py` - One rule, two callers: prompt-workflow.py decides a /dev, /dev-command, /redev or
├── `specialist_yield.py` - Public API:
├── `stop-commands.json` - JSON config: GATED_COMMANDS, CONTROL_COMMANDS, ASK_COMMANDS
├── `stop_contract.py` - is a prompt the human typed (TC-4)
├── `subagent.py` - is_subagent_context() and supporting helpers, for the hooks that import it
├── `subagent_restart.py` - Claude Code persists each subagent transcript under the parent session.  This
└── `todo_canonical.py` - Shared canonical todo validation utilities
```
<!-- /AUTO:index-stats -->

---
*Auto-generated by doc-sync hook.*