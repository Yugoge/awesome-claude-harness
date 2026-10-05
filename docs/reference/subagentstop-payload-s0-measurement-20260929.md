# SubagentStop payload availability — S0 measurement (2026-09-29)

Rollout step S0 of `docs/reference/close-commit-zero-failure-mechanism-20260928.md`
(§4, row S0) defers five SubagentStop payload fields to measurement: `agent_id`,
`session_id`, `transcript_path`, `agent_transcript_path`, `last_assistant_message`.
The rollout table's method (registering the observational canary for SubagentStop)
modifies `settings.json`, which is forbidden for the S2 lane that produced this note;
the canary also records nothing without an active probe file
(`hooks/capability-canary.py:40-46` returns early when no probe exists, and grep
confirms it is not registered for any event in `settings.json` today). This note
therefore measures via the **existing passive live channels** and reports a field as
`indeterminate` **with the structural code-cited reason** wherever those channels
cannot decide. Nothing below is assumed: every `present_observed` verdict rests on
records that could not exist without the field having arrived in a live payload.

## Channels measured (re-read at implementation time, 2026-09-29)

| Channel | Fresh counts (2026-09-29) | Structural bias |
|---|---|---|
| `~/.claude/logs/artifact-contract-advisory.jsonl` | 11 records; 11/11 truthy `agent_id`; record key set = {agent_id, agent_type, dev_session_id, failures, kind, mode, prefix, project_dir, ts} | Presence-biased: the writing hook exits before logging when payload `agent_id` is absent (`hooks/subagentstop-artifact-contract-enforce.py:217-219`), so the log can never witness an absent field |
| `~/.claude/restart-state/*.json` | 742 candidates; statuses: response_observed=68, dispatched=156, pending=518, quota_interrupted=0; 742/742 non-empty `agent_transcript_path` | `status=response_observed` is reachable only through `observe_subagent_stop`, which hard-requires a live payload `session_id` AND `agent_id` (`hooks/lib/subagent_restart.py:893-898`) plus an existing state file for that session (`:899-900`); `subagentstop-restart-track.py` is a registered SubagentStop consumer in `settings.json`, so these state flips are genuine SubagentStop deliveries |

Counts drift run-to-run: the store is actively written by live sessions (the BA
baseline three hours earlier saw 744/71; this implementation-time re-read saw
742/68). Both readings support the same verdicts.

## Per-field verdicts

### `agent_id` — **present_observed**
- Channel 1: 11/11 advisory records carry truthy `agent_id` (channel is
  presence-biased per the table above — it proves presence occurs live, not a rate).
- Channel 2 (independent): 68/742 restart-state candidates reached
  `response_observed`, a status that structurally requires a payload `agent_id`
  matching `AGENT_RE` (`hooks/lib/subagent_restart.py:893-898`).

### `session_id` — **present_observed**
- Channel: the same 68 `response_observed` candidates require a payload
  `session_id` matching `SESSION_RE` and resolving to an existing state file
  (`hooks/lib/subagent_restart.py:893-899`).
- Refinement over the pre-implementation baseline: the advisory JSONL contributes
  **nothing** for this field — 0/11 records carry a `session_id` key at all (they
  carry `dev_session_id`, a dev-registry identifier written by the hook itself, not
  the harness payload field). restart-state is the only passive channel for this
  field, and it decides it positively.

### `transcript_path` — **indeterminate**
- Structural reason: **no registered SubagentStop consumer records this field**, so
  no passive on-disk evidence can exist either way. The advisory key set (measured
  above) does not include it; restart-state candidates do not persist it.
- The known `transcript_path` production read (`hooks/pretool-workflow-gate.py:224`)
  is a **PreToolUse** payload read, not SubagentStop — it proves nothing about the
  SubagentStop payload.
- Completion route: canary SubagentStop registration (rollout §4 S0,
  `hooks/capability-canary.py` + `hooks/lib/capability_state.py:129-130`,
  `M settings.json`) in a later gate cycle.

### `agent_transcript_path` — **indeterminate**
- Measured: 742/742 candidates carry a non-empty `agent_transcript_path` — but the
  value is **discovery-written** at candidate-build time
  (`hooks/lib/subagent_restart.py:516-518`, constructed from the parent transcript
  path) and only **conditionally overwritten** from the payload at `:920-922` (only
  when the payload supplies a non-empty string). On-disk state cannot distinguish
  the writer, so universal presence proves nothing about payload delivery.
- Completion route: same canary registration as above.

### `last_assistant_message` — **indeterminate**
- Measured: 0/742 candidates are `quota_interrupted` — the only status whose
  derivation requires non-empty message content (the `RECOVERY_STATUS` sentinel or
  quota-text match at `hooks/lib/subagent_restart.py:913-917`). `response_observed`
  is reachable with an **empty** message because a non-string payload field defaults
  to `""` (`:901-903`). No candidate on this machine proves non-empty content ever
  arrived in the payload.
- Completion route: same canary registration as above.

## Cross-reference (not re-measured here)

SubagentStop does not fire on an external hard kill: the 2026-09-03 evidence chain
in `docs/reference/harness-issues-backlog.md` (line 59, the `/restart` deadlock
entry) shows two subagents killed simultaneously by an external event with the
interruption recorded "早于任何终态报告与 `SubagentStop`" (before any terminal
report and before SubagentStop). Any consumer of these payload fields must assume
the event itself can be absent entirely.

## Design consequence

The L0 ladder inputs (`agent_transcript_path`, `last_assistant_message`) are
**OPTIONAL**: with both file-path fields indeterminate, the G2 resolution ladder
degrades from L0 (payload-supplied path) to L1 (session-scoped store construction
from the two `present_observed` fields `session_id` + `agent_id`) — exactly as
design §1.3-G2 already mandates. `hooks/lib/obligation.py` implements L0 as an
optional caller-supplied input and L1 as the guaranteed-input rung; nothing in the
library depends on the indeterminate fields being present.
