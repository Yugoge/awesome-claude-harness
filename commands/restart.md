---
description: Resume every quota-interrupted subagent in the current Claude Code parent session from its original transcript and agent ID; when none is recoverable, continue the invoking session's own main agent.
disable-model-invocation: true
---

# /restart — Recover All Quota-Interrupted Work

Human-only emergency recovery; invoke only after a session or usage limit has
interrupted this session — every recoverable interrupted subagent, or, when the
session had none, the main agent's own work.

## Usage

```text
/restart
/restart <guidance text>
```

Both forms are valid. The first token of the prompt must be the command itself,
followed by whitespace or end-of-prompt, so `/restarts` and a mid-sentence
mention mint nothing (`hooks/userprompt-restart-authorize.py::split_invocation`).
Everything after that separating whitespace is the operator's **guidance text**,
taken verbatim with **no length limit, no character filtering, and no
truncation**. It is persisted raw beside the capability as
`claude-restart-args-<session-id>.txt` and is never echoed back into session
context — the issuer prints only its byte count and path
(`::_persist_guidance`, `::guidance_path`). A bare invocation removes any
guidance an earlier `/restart` of this same session left behind, so the absence
of that file is current fact rather than stale silence.

There is deliberately no agent selector: every recoverable interrupted subagent
in the current parent transcript is handled as one recovery wave. When the
transcript yields no such subagent, the invocation is instead a continuation
directive to this session's own main agent — see
[Zero-candidate continuation](#zero-candidate-continuation).

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

   The output is the transcript-derived candidate set for THIS parent session
   only. Discovery reads the invoking session's own transcript (after
   `claude --resume` that transcript already carries the interrupted history
   forward) and NEVER scans other sessions or other account roots by default.
   A listed candidate must also be structurally interrupted: a child whose own
   transcript reached a `stop_reason: "end_turn"` terminal report finished
   naturally and is excluded, even when its report quotes quota/limit text
   (the false-positive corpus in
   `docs/reference/restart-detector-quota-text-match-false-positive-20260915.md`).
   That exclusion is conditional, not a flat guarantee: each account root holds
   only its own PARTIAL copy of a child transcript, so the verdict is resolved
   across every copy and the strongest wins — an `end_turn` record in any one
   copy excludes the child, while its absence from a partial copy proves nothing
   (`hooks/lib/subagent_restart.py::_child_transcript_copies` and
   `::_child_transcript_signals`). Reading only the copy beside the parent
   transcript listed three already-finished children of session `4758df81` as
   resumable. When NO copy is readable the verdict is unknowable and the
   candidate is deliberately kept, so a genuinely cut-off child is never
   dropped. The same check runs again at dispatch time, so a child that reached
   its terminal report after prepare is refused rather than resumed
   (`::authorize_send_message`).
   For the account-rotation case only — recovering what another account's
   recent session left behind in this same project under
   `/var/lib/claude-accounts/<name>/claude/projects/<slug>/` — the human may
   append `--cross-account` to the prepare command; each candidate then reports
   its true originating `parent_session_id` and origin transcript path, and
   only a state prepared with that flag can authorize resuming a
   foreign-origin candidate. A `candidate_count` of `0` does not enter the
   subagent path at all: skip steps 3-5 and follow
   [Zero-candidate continuation](#zero-candidate-continuation) instead.
3. **Resume every pending candidate.** In one parallel tool-call batch where
   supported, call `SendMessage` exactly once for every candidate whose status is
   `pending`. A `dispatched` candidate is already running: wait for it and never
   enqueue a duplicate message. Use its exact `agent_id` as `to` and the exact
   `resume_message` emitted by the prepare command as `message`. Do not edit,
   summarize, prefix, suffix, translate, or otherwise rewrite that message.
4. **Wait for response evidence.** Successful sends are journaled automatically;
   `SubagentStop` records response evidence. After all sends return, invoke the
   helper with a tool timeout of at least 600000 ms:

   ```text
   $HOME/.claude/venv/bin/python $HOME/.claude/scripts/restart-subagents.py status --wait-seconds 540
   ```

   If `complete` is false, report `RESTART_INCOMPLETE` with every
   `incomplete_agent_ids` entry. Never claim recovery succeeded merely because
   messages were dispatched. A later `/restart` safely retries those same IDs:
   the retry is armed by fresh interruption evidence in the parent transcript —
   including the `status=failed` session-limit notification that a second quota
   kill of a resumed agent produces — so a candidate stays `dispatched` only
   while no new interruption has been recorded against it.
5. **Finalize only after all responses.** When `complete` is true, invoke:

   ```text
   $HOME/.claude/venv/bin/python $HOME/.claude/scripts/restart-subagents.py finalize
   ```

   Report the recovered agent IDs and point to their existing transcript paths.

## Zero-candidate continuation

`candidate_count` from step 2 is the only discriminator
(`hooks/lib/subagent_restart.py::status_view`). Greater than `0` runs steps 3-5
unchanged, and the guidance text rides along with each resume. Exactly `0` runs
the steps below. There is no third case: a zero count with `candidates: []` is a
complete, valid prepare result, never an error to retry.

6. **Consume the capability.** Run the step 5 finalize command. With zero
   candidates `complete` is already true, so finalize succeeds and unlinks the
   grant (`::finalize`). Finalize consumes only the capability, never the
   guidance file, so step 7 can still read it afterwards.
7. **Branch on the guidance text.** The guidance is the byte content of
   `claude-restart-args-<session-id>.txt` beside the capability, which `prepare`
   also surfaces as a top-level `operator_guidance` field of its JSON
   (`::prepare_state` writes it, `::status_view` emits it, and it is present
   even at zero candidates); the file is the byte source of record, so read it
   directly if the field is absent.
   - **No guidance** — the plain bare invocation. Behaviour is exactly what it
     was before this section existed: report that no recoverable interrupted
     child exists, and stop. Start no work and dispatch nothing. Guidance
     absence is authoritative, because a bare invocation deletes any earlier
     text rather than leaving it to be replayed (`::_persist_guidance`).
   - **Guidance present** — continue to step 8.
8. **Continue this session's own main agent.** With no interrupted child, the
   only thing needing to continue is the main agent, and the invocation is a
   continuation directive addressed to it. All of the following bind:
   - **Resume, do not restart.** Pick the interrupted work up from where it
     stopped: re-read the live state of the files, artifacts, and bookmarks this
     session already produced and continue from them. Never re-run a finished
     phase to re-derive a result that already exists, and never treat the
     original request as a fresh task.
   - **Never replay an irreversible operation.** First inspect the last tool
     call, its result, and current workspace side effects. A commit, push,
     deletion, message send, or external call that already landed is done:
     verify it and move past it.
   - **Guidance is authoritative for the next phase, not a scope licence.** The
     operator's text outranks this session's own earlier plan for how to proceed
     from here. It may redirect, constrain, or re-prioritise the interrupted
     work. It may NOT add a separate issue, enlarge the change beyond the
     original one, or lift any prohibition below — guidance that would do so is
     reported back to the operator instead of executed.
   - **No stand-in agent.** Continuation is the main agent resuming its own
     work. It never becomes an `Agent`/`Task` dispatch carrying the session's
     transcript as a prompt.
   - **Report honestly.** If the interrupted work cannot be resumed from the
     surviving state, say so and name what is missing. Never claim a phase
     complete when no evidence of it exists.

## Non-negotiable prohibitions

- **DO NOT self-invoke.** This command is human-only in both forms, including the
  zero-candidate continuation: only the operator may start it. `Skill(restart:*)`
  is denied in `settings.json`, the frontmatter sets
  `disable-model-invocation: true`, and the capability issuer mints nothing for a
  prompt carrying an `agent_id`. An agent that wants continuation asks the
  operator; it never issues the directive to itself.
- **DO NOT call `Agent` or `Task`** to replace an interrupted subagent.
- **DO NOT omit any candidate**, even if its last transcript entry looks nearly complete.
- **DO NOT copy a transcript into a fresh prompt** and call that a restart.
- **DO NOT repeat irreversible operations.** The fixed recovery message requires
  each resumed agent to inspect its last tool result and workspace side effects first.
- **DO NOT overwrite or complete the active `/dev`, `/redev`, `/spec`, or
  `/dev-overnight` TodoWrite/workflow bookmark.** `/restart` is an orthogonal
  control operation and intentionally has no todo script. Because of this,
  `pretool-workflow-gate.py` exempts the exact `restart-subagents.py`
  invocations in steps 2, 4, and 5 from the checklist gate: even a session
  whose own bookmark was never acknowledged (e.g. an unrelated command was
  invoked and interrupted before its first `TodoWrite`) can still run
  `/restart`'s recovery steps without initializing that bookmark first.
- **DO NOT treat `SubagentStop` fallback as proven native Codex parity.** This is
  a Claude Code native command. On a Codex runtime without equivalent
  `SendMessage` plus authoritative child lifecycle events, report
  `RESTART_BLOCKED_UNSUPPORTED_RUNTIME`; never fabricate completion evidence.
