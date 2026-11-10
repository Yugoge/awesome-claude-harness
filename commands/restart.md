---
description: Resume every quota-interrupted subagent in the current Claude Code parent session from its original transcript and agent ID; when none is recoverable, continue the invoking session's own main agent.
disable-model-invocation: true
summary: "Resume every subagent a usage limit interrupted, by its original agent id; with none to resume, continue the main agent."
group: Control
---

# /restart — Recover All Quota-Interrupted Work

Human-only recovery after a session or usage limit interrupted this session. It resumes
every recoverable interrupted subagent of the current parent transcript as one wave (there is no
agent selector); when the transcript holds none, it is a continuation directive to this session's
own main agent ([Zero-candidate continuation](#zero-candidate-continuation)). The rule behind it is
CLAUDE.md lesson 16. Inside `/dev-overnight` the session's own wake (`commands/dev-overnight.md`
Step 0) runs the same procedure with no human; with 0 candidates it finalizes and the session
carries on with its checklist step in progress.

Usage: `/restart` or `/restart <guidance text>`. The guidance is the operator's words after the
command, verbatim, with no length limit. With candidates it rides inside each `resume_message`
that prepare returns; with none, step 7 reads it. The mechanics sit in hooks:
`hooks/userprompt-restart-authorize.py` issues the capability and persists the guidance,
`hooks/posttool-restart-sendmessage.py` journals each send and
`hooks/subagentstop-restart-track.py` records response evidence, all on
`hooks/lib/subagent_restart.py` and pinned by `tests/test_restart_command.py`.
`docs/ENFORCEMENT-LEDGER.md` rates the issuer and the recorder advisory and the journal detected,
so the steps below are the rule.

## Mandatory procedure

1. **Preflight.** `SendMessage` must be present. If it is absent, output
   `RESTART_BLOCKED_TOOL_UNAVAILABLE` and tell the user to restart Claude Code with this harness
   loaded, resume this parent session with `claude --resume <session-id>`, and invoke `/restart`
   again. Do not fall back to `Agent`.
2. **Prepare the recovery set.**

   ```text
   python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/restart-subagents.py" prepare
   ```

   The helper fails closed with `RESTART_BLOCKED_SESSION_ID_UNAVAILABLE` when the environment holds
   no session id. Its output is the candidate set of THIS parent session's own transcript (after
   `claude --resume` it carries the interrupted history forward); other sessions and accounts are
   not scanned by default, and children that finished (a terminal `end_turn` report) are already
   excluded, so do not re-judge the list. Only when the operator asks for the account-rotation case
   (another account's recent session in this project, scanned only when `CLAUDE_RESTART_ACCOUNTS_ROOT`
   names the accounts root), append `--cross-account` to the prepare command; a foreign-origin
   candidate can be resumed only from a state prepared with it. A `candidate_count` of `0` has
   nothing to resume and sends no message: skip steps 3-4 and follow
   [Zero-candidate continuation](#zero-candidate-continuation). Step 5 is not skipped on either
   path; the zero-candidate path reaches it from its step 6.
3. **Resume every pending candidate.** In one parallel tool-call batch where supported, call
   `SendMessage` exactly once for every candidate whose status is `pending`. A `dispatched`
   candidate is already running: wait for it and never enqueue a duplicate message. Use its exact
   `agent_id` as `to` and the exact `resume_message` emitted by the prepare command as `message`.
   Do not edit, summarize, prefix, suffix, translate, or otherwise rewrite that message.
4. **Wait for response evidence.** After all sends return, run the helper with a tool timeout of
   at least 600000 ms:

   ```text
   python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/restart-subagents.py" status --wait-seconds 540
   ```

   If `complete` is false, report `RESTART_INCOMPLETE` with every `incomplete_agent_ids` entry.
   Never claim recovery succeeded merely because messages were dispatched. A later `/restart`
   retries those same ids: a candidate stays `dispatched` only until fresh interruption evidence
   (a second session-limit notification, `status=failed` included) appears in the parent
   transcript. A resume that verifiably fails, with the evidence quoted in the report, is still not
   replaced here: its lane returns to its command's ordinary pipeline, which re-dispatches it and
   never ends it.
5. **Finalize only after all responses.** When `complete` is true, run:

   ```text
   python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/restart-subagents.py" finalize
   ```

   Report the recovered agent ids and point to their existing transcript paths. Then go on with the
   command whose subagents were cut, from the checklist step that was in progress: each resumed
   agent's original `Agent` call is that step's dispatch, so complete the step once its artifacts
   are checked; never dispatch a replacement.

## Zero-candidate continuation

`candidate_count` from step 2 is the only discriminator. Greater than `0` runs steps 3-5 and the
guidance rides along with each resume. Exactly `0` runs steps 6-8 in place of steps 3-4, and step 6
makes the step 5 finalize call. A zero count with `candidates: []` is a complete, valid result,
never an error to retry.

6. **Consume the capability.** Run the step 5 finalize command. With zero candidates `complete` is
   already true, so it succeeds; the guidance is already recorded in the session state.
7. **Branch on the guidance text.** Read the top-level `operator_guidance` field of step 2's JSON,
   present even at zero candidates and still there after step 6; do not look for the guidance file,
   whose name is derived from the capability step 6 consumes.
   - **No guidance** (a bare invocation): report that no recoverable interrupted child exists, and
     stop. Start no work and dispatch nothing.
   - **Guidance present**: continue to step 8.
8. **Continue this session's own main agent.** With no interrupted child, the main agent is what
   continues, and the invocation is a directive addressed to it. All of these bind:
   - **Resume, do not restart.** Pick the interrupted work up where it stopped: re-read the live
     state of the files, artifacts and bookmarks this session already produced and continue from
     them. Never re-run a finished phase to re-derive a result that exists, and never treat the
     original request as a fresh task.
   - **Never replay an irreversible operation.** First inspect the last tool call, its result and
     the workspace side effects. A commit, push, deletion, message send or external call that
     already landed is done: verify it and move past it.
   - **Guidance is authoritative for the next phase, not a scope licence.** It outranks this
     session's earlier plan for how to proceed and may redirect, constrain or re-prioritise the
     interrupted work. It may NOT add a separate issue, enlarge the original change, or lift any
     bullet of this step or any prohibition below; guidance that would is reported back to the
     operator, not executed.
   - **Rebuild what is missing.** When the surviving state lacks what the next phase needs, name
     what is missing and produce it again by the step that makes it, then continue. Never claim a
     phase complete when no evidence of it exists.

## Prohibitions

- **DO NOT self-invoke.** The command is human-only in both forms, the zero-candidate continuation
  included (frontmatter `disable-model-invocation: true` and the `Skill(restart:*)` deny in
  `settings.json`; CLAUDE.md lesson 15). An agent that wants continuation asks the operator; it
  never issues the directive to itself.
- **DO NOT call `Agent` or `Task`** to replace an interrupted subagent or to stand in for the main
  agent in step 8, and do not copy a transcript into a fresh prompt and call that a restart.
- **DO NOT omit any candidate**, even if its last transcript entry looks nearly complete.
- **DO NOT overwrite the active `/dev`, `/redev`, `/spec` or `/dev-overnight` TodoWrite/workflow
  bookmark, nor complete its steps before step 5.** `/restart` is an orthogonal control operation
  with no todo script: `hooks/pretool-workflow-gate.py` exempts only the exact, unchained helper
  lines of steps 2, 4 and 5, so run them as written, even when the session's own bookmark was never
  acknowledged.
- **DO NOT treat the `SubagentStop` fallback as proven native Codex parity.** On a Codex runtime
  without `SendMessage` plus authoritative child lifecycle events, report
  `RESTART_BLOCKED_UNSUPPORTED_RUNTIME`; never fabricate completion evidence.
