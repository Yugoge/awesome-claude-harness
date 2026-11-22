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
Step 0) runs the same procedure with no human; with 0 candidates nothing is run and the session
carries on with its checklist step in progress.

Usage: `/restart`, `/restart <guidance text>`, or either with `--cross-account` as the first
word after the command (step 2). The guidance is the operator's words after the
command, verbatim, with no length limit. With candidates it rides inside each `resume_message`
that prepare returns; with none, step 7 reads it. The mechanics sit in hooks:
`hooks/userprompt-restart-authorize.py` issues the capability, persists the guidance and
prepares the recovery set (step 2),
`hooks/posttool-restart-sendmessage.py` journals each send and
`hooks/subagentstop-restart-track.py` records response evidence and finalizes (step 4), all on
`hooks/lib/subagent_restart.py` and pinned by `tests/test_restart_command.py`.
`docs/ENFORCEMENT-LEDGER.md` rates the issuer and the recorder advisory and the journal detected,
so the steps below are the rule.

## Mandatory procedure

1. **Preflight.** `SendMessage` must be present. If it is absent, output
   `RESTART_BLOCKED_TOOL_UNAVAILABLE` and tell the user to restart Claude Code with this harness
   loaded, resume this parent session with `claude --resume <session-id>`, and invoke `/restart`
   again. Do not fall back to `Agent`.
2. **Read the recovery set.** On a typed `/restart`, `hooks/userprompt-restart-authorize.py`
   has already prepared it: right after issuing the capability it ran the prepare command below
   and handed its stdout, verbatim, to this turn's context between the line
   `[/restart] RECOVERY SET PREPARED (the output of restart-subagents.py prepare, verbatim):` and
   the line `[/restart] END OF RECOVERY SET`. That JSON is step 2's result: read it and go on
   with step 3; do not run prepare again. Run the prepare command yourself only when that block is
   absent or cut short (no END line): the context holds the line `[/restart] RECOVERY SET NOT PREPARED:` instead (preparing
   ran past the hook's time budget, or the helper failed, the reason named on that line), or
   neither line (the hook did not run to its end: an install without it, or its time limit), or no
   `/restart` was typed (the overnight wake, `commands/dev-overnight.md` Step 0). A payload with no
   session id never gets this far: the capability cannot be issued, so the hook refuses the prompt.

   ```text
   python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/restart-subagents.py" prepare
   ```

   The helper fails closed with `RESTART_BLOCKED_SESSION_ID_UNAVAILABLE` when the environment holds
   no session id. It reads the `/restart` grant as data only: with none valid (no `/restart` in this
   session, or an expired one) it still lists the candidates, adds `restart_grant` to its output and
   says so on stderr. The grant is no permission: each send of step 3 is a dispatch to an own
   subagent, judged by the dispatch gate (CLAUDE.md lesson 16). Its output is the candidate set of THIS parent session's own transcript (after
   `claude --resume` it carries the interrupted history forward); other sessions and accounts are
   not scanned by default, and children that finished (a terminal `end_turn` report) are already
   excluded, so do not re-judge the list. It lists every own subagent (the CLI's result or its
   `agent-<id>.meta.json` names the dispatch that started it) that did not finish, whatever cut it:
   a usage or session limit, the end of the CLI process, the owner's interrupt of a foreground
   dispatch (a result that names no child), a TaskStop; never one whose task a later dispatch of
   this session carried again (the same prompt, or the same `<obligation>` lane). The account-rotation case (another account's
   session in this project, scanned only when `CLAUDE_RESTART_ACCOUNTS_ROOT` names the accounts
   root) is prepared with `--cross-account`: typed as the first word after the command
   (`/restart --cross-account [guidance]`), the hook passes it to prepare itself, and the block's
   `cross_account` is `true` (the guidance is still the whole argument, verbatim); asked for in
   words instead, run the prepare command with `--cross-account` appended, whose output then
   replaces the block. A foreign-origin candidate can be resumed only from a state prepared with
   it. The cross-account sweep reads every other session of this project, newest first, up to
   `CLAUDE_RESTART_SIBLING_MAX_BYTES` (default 256 MiB); copies of this session under other
   accounts are always read and their children are ordinary candidates.
   The interrupted children of a session last written more than
   `CLAUDE_RESTART_SIBLING_WINDOW_SECONDS` ago (default a day) are listed apart in
   `older_candidates`, each with its `session_last_written`, and a line of `warnings` says so.
   Resume an older candidate (in step 3, as any other) only when the operator's guidance asks for
   it, by naming it or by asking for everything; otherwise report them in one line (how many, the
   newest `session_last_written`) and leave them: an older candidate nobody resumed holds back no
   finalize. A `siblings_not_read` count means the byte bound was reached: report it in one line
   with its `newest` age; the state file names each transcript left unread. A `candidate_count`
   of `0` with no older candidate to resume has nothing to resume and sends no message: skip
   steps 3-5 and follow [Zero-candidate continuation](#zero-candidate-continuation).
3. **Resume every pending candidate.** In one parallel tool-call batch where supported, call
   `SendMessage` exactly once for every candidate whose status is `pending` (and every older
   candidate step 2 says to resume). A `dispatched`
   candidate is already running: wait for it and never enqueue a duplicate message. Use its exact
   `agent_id` as `to` and the exact `resume_message` step 2's set holds as `message`.
   Do not edit, summarize, prefix, suffix, translate, or otherwise rewrite that message. Where a
   dispatch of the candidate's role at this point must carry an `<obligation>` block (its lane's
   span requires one), append the lane's original block after the message: the send is that
   dispatch, the dispatch gate refuses it without the block, and the resumed run's stop is judged
   by the block the send carries.
4. **Read the outcome; run nothing.** The hooks wait and finalize: `hooks/subagentstop-restart-track.py`
   records each response and, when the last one is in, finalizes the recovery (the capability is
   consumed); at the parent's next prompt (a resumed child's notification included)
   `hooks/userprompt-restart-authorize.py` prints one line, once per change:
   `[/restart] RECOVERY FINALIZED by the harness: ...` or
   `[/restart] RESTART_INCOMPLETE: no response yet from <agent id> (<status>), ...`.
   On the incomplete line report `RESTART_INCOMPLETE` with every id it names. Never claim
   recovery succeeded merely because messages were dispatched. A later `/restart`
   retries those same ids: a candidate stays `dispatched` only until fresh interruption evidence
   (a second session-limit notification, `status=failed` included) appears in the parent
   transcript. A resume that verifiably fails, with the evidence quoted in the report, is still not
   replaced here: its lane returns to its command's ordinary pipeline, which re-dispatches it and
   never ends it.
5. **After the finalized line.** Report the recovered agent ids and point to their existing
   transcript paths. Then go on with the
   command whose subagents were cut, from the checklist step that was in progress: each resumed
   agent's original `Agent` call is that step's dispatch, so complete the step once its artifacts
   are checked; never dispatch a replacement.

## Zero-candidate continuation

`candidate_count` from step 2 is the only discriminator (older candidates the guidance asks
for count with it). Greater than `0` runs steps 3-5 and the
guidance rides along with each resume. Exactly `0` runs steps 6-8 in place of steps 3-5. A zero
count with `candidates: []` is a complete, valid result, never an error to retry.

6. **Nothing to run.** A complete set needs no finalize call: the prompt hook finalizes it (the
   capability is consumed) at the session's next prompt; the guidance is already recorded in the
   session state.
7. **Branch on the guidance text.** Read the top-level `operator_guidance` field of step 2's JSON,
   present even at zero candidates; do not look for the guidance file, whose name is derived from
   the capability the hook consumes.
   - **No guidance** (a bare invocation): report in one line that no recoverable interrupted
     child exists, then carry on with the active gated command from its checklist step in
     progress, by step 8's rules: the rule of step 5 and of the overnight wake. The turn ends only
     when no gated command's checklist is open. Never end it with an offer to continue ("say if
     you want me to continue") or a question; nothing is asked, and
     `/stop` is the exit.
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
  included (frontmatter `disable-model-invocation: true` and the `Skill(restart)` entry of
  the deny list, `policies/cli-deny.v1.json`; CLAUDE.md lesson 15). An agent that wants continuation asks the operator; it
  never issues the directive to itself.
- **DO NOT call `Agent` or `Task`** to replace an interrupted subagent or to stand in for the main
  agent in step 8, and do not copy a transcript into a fresh prompt and call that a restart.
- **DO NOT omit any candidate** of `candidates`, even if its last transcript entry looks nearly
  complete. `older_candidates` follow step 2's rule instead.
- **DO NOT overwrite the active `/dev`, `/redev`, `/spec` or `/dev-overnight` TodoWrite/workflow
  bookmark, nor complete its steps before step 5.** `/restart` is an orthogonal control operation
  with no todo script: `hooks/pretool-workflow-gate.py` exempts only the exact, unchained helper
  line of step 2 (and the helper's `status` and `finalize` lines, which a session holding the older
  text of this file may still run; they answer as before), so run it as written, even when the
  session's own bookmark was never acknowledged.
- **DO NOT treat the `SubagentStop` fallback as proven native Codex parity.** On a Codex runtime
  without `SendMessage` plus authoritative child lifecycle events, report
  `RESTART_BLOCKED_UNSUPPORTED_RUNTIME`; never fabricate completion evidence.
