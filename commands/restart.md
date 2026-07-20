---
description: Resume every quota-interrupted subagent in the current Claude Code parent session from its original transcript and agent ID.
disable-model-invocation: true
---

# /restart — Recover All Quota-Interrupted Subagents

Human-only emergency recovery for the case where a Claude Code session or usage
limit interrupts multiple subagents. This command resumes the original subagent
instances from their persisted transcripts. It never replaces them with fresh
agents and never selects only a convenient subset.

## Usage

```text
/restart
```

Only the exact bare command is valid. There is deliberately no agent selector:
every recoverable interrupted subagent in the current parent session is handled.

## Mandatory procedure

1. **Preflight the native tool.** `SendMessage` must be present. If it is absent,
   output `RESTART_BLOCKED_TOOL_UNAVAILABLE` and instruct the user to restart
   Claude Code with this harness loaded, resume this same parent session using
   `claude --resume <session-id>`, and invoke `/restart` again. Do not fall back
   to `Agent`.
2. **Prepare the recovery set.** Resolve `SID` from
   `$CLAUDE_CODE_SESSION_ID` with `$CLAUDE_SESSION_ID` as fallback in the same
   Bash call. An empty SID is a fail-closed error:

   ```bash
   SID="${CLAUDE_CODE_SESSION_ID:-${CLAUDE_SESSION_ID:-}}"; test -n "$SID" || { echo 'RESTART_BLOCKED_SESSION_ID_UNAVAILABLE' >&2; exit 2; }
   python3 "$HOME/.claude/scripts/restart-subagents.py" prepare --session-id "$SID"
   ```

   The output is the complete transcript-derived candidate set. A zero count is
   a successful no-op; report that no recoverable interrupted child exists.
3. **Resume every incomplete candidate.** In one parallel tool-call batch where
   supported, call `SendMessage` exactly once for every candidate whose status is
   not `response_observed`. Use its exact `agent_id` as `to` and the exact
   `resume_message` emitted by the prepare command as `message`. Do not edit,
   summarize, prefix, suffix, translate, or otherwise rewrite that message.
4. **Wait for response evidence.** Successful sends are journaled automatically;
   `SubagentStop` records response evidence. After all sends return, run with a
   Bash timeout of at least 600000 ms:

   ```bash
   SID="${CLAUDE_CODE_SESSION_ID:-${CLAUDE_SESSION_ID:-}}"; test -n "$SID" || exit 2
   python3 "$HOME/.claude/scripts/restart-subagents.py" status --session-id "$SID" --wait-seconds 540
   ```

   If `complete` is false, report `RESTART_INCOMPLETE` with every
   `incomplete_agent_ids` entry. Never claim recovery succeeded merely because
   messages were dispatched. A later `/restart` safely retries those same IDs.
5. **Finalize only after all responses.** When `complete` is true, run:

   ```bash
   SID="${CLAUDE_CODE_SESSION_ID:-${CLAUDE_SESSION_ID:-}}"; test -n "$SID" || exit 2
   python3 "$HOME/.claude/scripts/restart-subagents.py" finalize --session-id "$SID"
   ```

   Report the recovered agent IDs and point to their existing transcript paths.

## Non-negotiable prohibitions

- **DO NOT call `Agent` or `Task`** to replace an interrupted subagent.
- **DO NOT omit any candidate**, even if its last transcript entry looks nearly complete.
- **DO NOT copy a transcript into a fresh prompt** and call that a restart.
- **DO NOT repeat irreversible operations.** The fixed recovery message requires
  each resumed agent to inspect its last tool result and workspace side effects first.
- **DO NOT overwrite or complete the active `/dev`, `/redev`, `/spec`, or
  `/dev-overnight` TodoWrite/workflow bookmark.** `/restart` is an orthogonal
  control operation and intentionally has no todo script.
- **DO NOT treat `SubagentStop` fallback as proven native Codex parity.** This is
  a Claude Code native command. On a Codex runtime without equivalent
  `SendMessage` plus authoritative child lifecycle events, report
  `RESTART_BLOCKED_UNSUPPORTED_RUNTIME`; never fabricate completion evidence.

## Why this preserves content

The parent transcript binds each original Agent tool call to its persisted
`agent_id` and `agent-<id>.jsonl`. The authenticated `/restart` grant allows
`SendMessage` only to those discovered IDs and only with the fixed recovery
message. Claude Code therefore resumes the existing context, including prior
tool calls and results, instead of reconstructing an incomplete summary.
