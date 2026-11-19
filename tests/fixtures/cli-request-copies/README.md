# cli-request-copies

`transcript-2.1.322.jsonl` is a **real excerpt**, not hand-written: six records of a main-session
transcript Claude Code CLI **2.1.322** wrote in a live session, kept in their order, redacted as below.
They show the record kind `api-request-blob`, which `scripts/cli-fixture-record.sh` did not keep
before it named the kind in `wanted()` (so `tests/fixtures/cli/` holds none):

1. three `assistant` records of one turn: two thinking blocks, then a foreground `Agent` call;
2. the `user` record with that call's `tool_result` (the agent had returned);
3. two `api-request-blob` records, written right after it: `{"type", "sessionId", "hash", "message":
   {"role", "content"}}`, the messages of the CLI's next model request that it had not written before.
   The first repeats the three assistant records as the one message sent, the `tool_use` block
   (same id, same input) included; the second is a system message.

Records between them that hold no message were left out: `last-prompt`, `session-owner`, `atis-latch`,
`tools-used`, the call's two hook `attachment` records, and the `api-request` record that follows the
copies.

What the sessions of 2026-11-16 to 2026-11-18 show (every one of the 19 main transcripts and 541 subagent
transcripts of the period holds such records): a run of `api-request-blob` records always precedes an
`api-request` record; it follows a `user` record (a tool result or a prompt) or an attachment. A copy
has no `uuid`, `timestamp`, `parentUuid` or `isSidechain`; in a subagent's own transcript it carries
`agentId`. Its `message.content` holds `tool_use` and `tool_result` blocks with their ids, so a reader
that takes the content of any record counts a call again, after its result. A turn's last message is
copied only at the next request, after the next prompt. `tests/cli_shapes.py with_request_copies` writes
copies into a synthesized transcript in this arrangement.

## Redactions

The recorder's own transcript rule (`clean()` in `scripts/cli-fixture-record.sh`), with no home or
working directory of the recording known: every string is `<redacted>` unless its key is a structural one
or it is a uuid, timestamp or API id (each becomes its placeholder); then its account rule
(`bash scripts/cli-fixture-record.sh --redact transcript-2.1.322.jsonl`, which leaves the file unchanged).
Every id therefore reads `<ID>`, the call's and its result's alike.
