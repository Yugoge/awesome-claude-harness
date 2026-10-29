# lib

<!-- AUTO:index-stats -->
*Last updated: 2026-10-29T07:57:38Z*
**Total entries**: 52
**Convention**: kebab

## Tree
```
lib/
├── runtime_guard/
│   ├── `__main__.py` - Package entry-point so `python -m lib.runtime_guard` still works.
│   ├── `_core.py` - This module contains ZERO project identifiers. Every project-specific name
│   ├── `anchor.py` - The cleanly-extractable leaf subset of the HEAD-AGNOSTIC P0 anchor scan
│   ├── `config.py` - Depends on shell_lex (`_strip_quotes`, `_has_redirect_to`) + pathmatch
│   ├── `constants.py` - Dependency LEAF: defines only literal frozenset/dict constants, imports nothing,
│   ├── `context.py` - `_core.evaluate` computes a small set of per-EVALUATION inputs ONCE — the
│   ├── `find_cmds.py` - Depends on shell_lex (`_strip_quotes`) + pathmatch (`_glob_to_segment_regex`,
│   ├── `git_cmds.py` - Depends on shell_lex (`_strip_quotes`) + pathmatch (`_expand_leading_home`) +
│   ├── `pathmatch.py` - Depends only on shell_lex (`_strip_quotes`) + stdlib; references nothing from
│   └── `shell_lex.py` - Dependency LEAF: imports only the stdlib, references nothing from _core
├── `agent_resolver.py` - Refactored from pretool-subagent-code-block.py::_find_agent_type so that
├── `allowlist.py` - Single source of truth for the one /allow grant file and the one /do consent
├── `attribution_journal.py` - Capture side (used by pretool-attribution-pre.py / posttool-attribution-post.py):
├── `bash_active_syntax_census.py` - WHY THIS MODULE EXISTS (spec-20260808-035658 LANE-POL, Must-2 "completeness
├── `bash_context_strip.py` - This is deliberately NOT a full shell parser.  It only computes a conservative
├── `bash_execution_boundary.py` - THE ALGEBRA (spec-20260808-035658 LANE-POL, Must-1).  Every execution-bearing
├── `bash_write_targets.py` - Provides two public functions used by tool-policy and overnight-hook-guard:
├── `capability_state.py` - verdict, and the INDEPENDENT (non-hook-dispatched) preactivation consumer
├── `checkpoint-core.sh` - checkpoint-core.sh - Shared library for automated snapshot commits
├── `claude_home.py` - Generalizes the in-repo gold-standard fail-closed self-resolution pattern
├── `claude_home.sh` - claude_home.sh — shared "harness home" resolver (shell consumable).
├── `close-verdict.py` - The one rule every reader of a close verdict applies: classify the close
├── `closeout.py` - CLI:
├── `command_span.py` - The span is the records after the latest human-typed harness command outside
├── `commit_journal.py` - WHY THIS EXISTS
├── `commit_pipeline.py` - ONE home for the two questions the commit-authorization chain could not
├── `contract_runtime.py` - This module is the single shared engine consumed by every contract-aware
├── `dev_report_shard_patterns.py` - Single source for the per-worker / canonical dev-report filename regexes and
├── `dispatch_template.py` - A dispatch made from a base template before a merge carries no obligation block
├── `git_clean_guard.py` - Classifies ONE Bash command for the fail-closed pre-clean guard woven into the
├── `git_command_classifier.py` - Provides iter_git_invocations() — a token-aware parser that detects git
├── `grepguard_context_strip.py` - PURPOSE (narrow, guard-specific)
├── `harness_state_dir.py` - Hook runtime state (consent flags, grants, sentinels, bookmarks, stamps) lives
├── `harness_state_dir.sh` - harness_state_dir.sh -- shell twin of hooks/lib/harness_state_dir.py.
├── `interruption_signals.py` - Decides whether a subagent was cut off — and whether a usage limit did it — from
├── `merge_grant.py` - The merge-analyst writes its grant with the Write tool at
├── `obligation.py` - Rollout step S2 of the converged zero-failure design
├── `overnight.py` - The state record `<project>/.claude/overnight-state-<sid>.json` has one producer,
├── `pol_degraded_removal_reference.ere` - ere file
├── `policy_registry.py` - Reads the harness ``policies/tool-policy.v1.json`` (resolved via the shared
├── `roster.py` - A role exists because ``agents/<role>.md`` exists and opens with YAML front
├── `runtime_guard.py` - This file exists for backwards-compatibility with callers that invoke
├── `schema_registry.py` - Reads schemas/registry.json once and lazily loads referenced schema files
├── `scratch_owner.py` - hooks/session-scratch-init.sh writes <root>/<sid>/.owner = {"sid": ..., ...}. One rule reads
├── `session_resources.py` - Every destructive operation is bound to an immutable resource session and a
├── `spec_path.py` - One rule, two callers: prompt-workflow.py decides a /dev, /dev-command, /redev or
├── `specialist_yield.py` - Public API:
├── `stop_contract.py` - is a prompt the human typed (TC-4)
├── `subagent.py` - Single source of truth for is_subagent_context() and supporting helpers
├── `subagent_restart.py` - Claude Code persists each subagent transcript under the parent session.  This
└── `todo_canonical.py` - Shared canonical todo validation utilities
```
<!-- /AUTO:index-stats -->

---
*Auto-generated by doc-sync hook.*