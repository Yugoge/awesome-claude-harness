# Overnight reference (maintainer-facing)

Reference material relocated out of `commands/dev-overnight.md`, which is injected
verbatim into the orchestrator prompt on every continuation cycle. Both blocks below
were audited line by line and issue no instruction the orchestrator acts on: the schema
is a field catalogue the orchestrator reads named fields from and never writes, and the
comparison is an orientation table. Slices are verbatim relocations of their former
inline form, except three lines newly authored here to describe the new in-place default
(`worktree_path`, `worktree_branch`, and the `| Worktree |` comparison row).

---

## State file schema

**Schema**:
```json
{
  "session_id": "string (from $CLAUDE_SESSION_ID or UUID)",
  "end_time": "ISO-8601 datetime",
  "start_time": "ISO-8601 datetime",
  "focus": "string (discovery hint from user, or empty)",
  "spec_mode": "autonomous|user-provided",
  "user_spec_path": "string (path to user-provided spec, or null)",
  "cycle_count": 0,
  "issues_found": 0,
  "issues_fixed": 0,
  "issues_skipped": 0,
  "current_phase": "initializing|exploring|pipeline_creation|analyzing|implementing|verifying|iterating|logging|retrospective|completed",
  "current_issues": [
    {
      "index": 0,
      "description": "issue description",
      "location": "file:line",
      "severity": "critical|major|minor|cosmetic",
      "category": "category string",
      "agents_flagged": ["product-owner", "architect"],
      "phase": "pending|ba_complete|dev_complete|qa_failed|done",
      "iteration": 0,
      "status": "active|fixed|skipped",
      "timestamp_suffix": "YYYYMMDD-HHMMSS-0",
      "spec_path": "docs/dev/overnight/<session_id>/spec-pipeline-<index>.md"
    }
  ],
  "failed_attempts": {"issue_desc": 2},
  "addressed_issues": ["issue_desc_1", "issue_desc_2"],
  "cycle_log": [
    {
      "cycle": 1,
      "pipeline_index": 0,
      "issue": "description",
      "location": "file:line",
      "severity": "critical|major|minor|cosmetic",
      "status": "fixed|skipped",
      "iterations": 1,
      "timestamp": "ISO-8601"
    }
  ],
  "consecutive_clean_sweeps": 0,
  "worktree_path": "absolute path to the session working root; never null. Equals main_root under in_place; /abs/main/.claude/worktrees/overnight-... under registered_worktree; the clone path under fresh_clone_checkout",
  "worktree_branch": "the session working branch; never the protected branch. Under in_place this is the branch the checkout was already on; otherwise worktree-overnight-YYYYMMDD-<session_id_short>",
  "pm_triage_reports": [],
  "pm_retro_reports": [],
  "unresolved_issues": [
    {
      "description": "issue description",
      "severity": "critical|major|minor|cosmetic",
      "cycles_unresolved": 0,
      "last_attempt_reason": "why it failed or was deferred",
      "recommended_approach": "what to try next"
    }
  ]
}
```

---

## Comparison: /dev vs /dev-overnight

| Aspect | /dev | /dev-overnight |
|--------|------|----------------|
| Input | User provides requirement | Agent discovers issues via 4 specialist subagents |
| BA phase | Full BA + clarification loop (max 3 rounds) | BA with clarification skipped (round=3) |
| BA validation | Step 8 | Step 9 |
| Dev validation | Step 12 | Step 13 |
| QA processing | Step 14 decision tree | Step 16 autonomous decision |
| Iteration loop | Step 10 (max 5, asks user after 5) | Step 17 (max 5 per pipeline, auto-skip after 5) |
| Settings update | Step 9 | Step 18 (aggregated from all pipelines) |
| Loop | Single pass | Continuous until end-time |
| Termination | After QA passes | After end-time expires |
| User interaction | Required (clarification, approval) | None (fully autonomous) |
| Scope per cycle | One complete feature/fix | User-pathway-filtered findings (parallel pipelines, gated by PM Step 4 — Tier 1 + multi-agent-consensus in autonomous mode; user-need-relevant in user-provided mode); specialists' free exploration is preserved per Section 5.7 anti-pattern #5 |
| Subagent usage | BA + dev + QA | product-owner + architect + user + ui-specialist + BA + dev + QA |
| Stop hook | Workflow enforcement only | Workflow + time-lock |
| Worktree | Not used | Not used by default (`in_place`); created on first run and reused across cycles only under `--worktree` |
| Total steps | 13 | 21 |

---
