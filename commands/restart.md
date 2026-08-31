---
description: Resume every quota-interrupted subagent in the current Claude Code parent session from its original transcript and agent ID.
disable-model-invocation: true
---

# /restart — Recover All Quota-Interrupted Subagents

Human-only emergency recovery; invoke only after a session or usage limit has
interrupted subagents.

## Usage

```text
/restart
/restart confirm-unrecoverable <audit-id>
```

The bare command handles every recoverable interrupted subagent as one wave;
there is deliberately no agent selector. The second form is valid only after
the bare command emitted the exact matching audit request. It confirms one
content-addressed proposal and never resumes or replaces a child.

## Mandatory procedure

1. **Preflight the native tool.** `SendMessage` must be present. If it is absent,
   output `RESTART_BLOCKED_TOOL_UNAVAILABLE` and instruct the user to restart
   Claude Code with this harness loaded, resume this same parent session using
   `claude --resume <session-id>`, and invoke `/restart` again. Do not fall back
   to `Agent`.
2. **Prepare the recovery set.** The helper resolves the current session from
   `$CLAUDE_CODE_SESSION_ID`, then `$CLAUDE_SESSION_ID`, and fails closed with
   `RESTART_BLOCKED_SESSION_ID_UNAVAILABLE` when neither exists:

   ```text
   $HOME/.claude/venv/bin/python $HOME/.claude/scripts/restart-subagents.py prepare
   ```

   The output is the complete transcript-derived candidate set. A zero count is
   a successful no-op; continue to the finalize command in step 5 to consume the
   grant, then report that no recoverable interrupted child exists.
3. **Resume every pending candidate.** In one parallel tool-call batch where
   supported, call `SendMessage` exactly once for every candidate whose status is
   `pending`. A `dispatched` candidate is already running: wait for it and never
   enqueue a duplicate message. Use its exact `agent_id` as `to` and the exact
   `resume_message` emitted by the prepare command as `message`. Do not edit,
   summarize, prefix, suffix, translate, or otherwise rewrite that message.
   PostToolUse records the native structured result. `success:false`, an error,
   or an unknown result remains `pending` with an audited attempt and is safe to
   retry; only a truthful success becomes `dispatched`.
4. **Wait for response evidence.** Successful sends are journaled automatically;
   `SubagentStop` records response evidence. After all sends return, invoke the
   helper with a tool timeout of at least 600000 ms:

   ```text
   $HOME/.claude/venv/bin/python $HOME/.claude/scripts/restart-subagents.py status --wait-seconds 540
   ```

   If `complete` is false, report `RESTART_INCOMPLETE` with every
   `incomplete_agent_ids` entry. Never claim recovery succeeded merely because
   messages were dispatched. A later `/restart` safely retries those same IDs.
   If durable evidence proves one pending exact tuple cannot be resumed, use
   `propose-unrecoverable` with its exact tuple, a 20-2000 character reason, and
   at least one hash-matching structured evidence reference. Print the returned
   `RESTART_AUDIT_CONFIRMATION_REQUIRED` record and exact confirmation prompt,
   then pause. **Do not mark it or submit the prompt yourself.**
5. **Finalize only after all responses.** When `complete` is true, invoke:

   ```text
   $HOME/.claude/venv/bin/python $HOME/.claude/scripts/restart-subagents.py finalize
   ```

   Report `recovered_agent_ids` and `unrecoverable_agent_ids` separately and
   point to their evidence/transcript paths. Unrecoverable means only that the
   restart wave was human-audited as permanently unresumable; it never claims
   the original development task, QA, close, or commit succeeded.

## Human audit confirmation mode

For an exact human `/restart confirm-unrecoverable <audit-id>` turn, do not run
prepare or send messages. The UserPromptSubmit hook mints a one-use capability;
invoke only:

```text
$HOME/.claude/venv/bin/python $HOME/.claude/scripts/restart-subagents.py mark-unrecoverable --audit-id <audit-id>
```

Report the exact durable audit result. A missing, expired, changed, ambiguous,
or model-originated capability is `RESTART_AUDIT_CONFIRMATION_BLOCKED`; do not
retry, weaken, or synthesize audit fields.

## Non-negotiable prohibitions

- **DO NOT call `Agent` or `Task`** to replace an interrupted subagent.
- **DO NOT omit any candidate**, even if its last transcript entry looks nearly complete.
- **DO NOT infer `unrecoverable`** from a failed send, stale/missing path,
  elapsed time, retry count, or final-looking prose.
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
