# /merge: two documented steps are unexecutable from agent context

Measured 2026-10-07 against `hooks/pretool-bash-safety.sh` (the rules below are present in
HEAD `5db000d3`, not introduced by any in-flight edit) while executing the full `/merge`
orchestration layer for the first time, in a disposable clone.

**Citation form — this record cites grep anchors and never line numbers.** Every file named
below carried uncommitted edits when these measurements were taken, so a working-copy line
number resolves against neither the committed file nor any later state, and drifts again on
every subsequent edit. A first draft of this record did cite five numbers; all five were
already wrong. Locate each claim below by searching for the quoted anchor string. An editor
who adds a line number back into this record is reintroducing a known defect.

Both defects are in `commands/merge.md`'s orchestrator steps, not in `hooks/merge.sh`. The
wrapper itself works; see "What is not affected".

## Defect 1 — Step 3 consumes the grant with `rm`, and `rm` is unconditionally forbidden

`commands/merge.md` Step 3 mandates:

```bash
rm -f "/tmp/agentic-commit/merge-analyst/${REPO_HASH}/${SESSION_ID}/${REQUEST_ID}.json"
```

`hooks/pretool-bash-safety.sh` blocks every filesystem `rm`. Find the rule by searching for the
string it emits, `rm is forbidden`, situated under the comment that begins
`Block: filesystem rm (but NOT docker rm`. The rule's condition carves
out exactly one case, `docker rm`; there is no `/merge` term anywhere in the hook
(`CLAUDE_MERGE_COMMAND_ACTIVE` occurs 0 times in the file).

Executed, by piping synthetic PreToolUse payloads into the hook:

| command | result |
|---|---|
| `rm -f /tmp/x.json` | rc=2 `BLOCKED: rm is forbidden — delete files manually or ask the user` |
| same, with `CLAUDE_MERGE_COMMAND_ACTIVE=1` in the hook's env | rc=2, identical |
| the exact Step 3 command above | rc=2, identical |
| the exact Step 3 command, with `CLAUDE_MERGE_COMMAND_ACTIVE=1` | rc=2, identical |
| positive control: `echo hello` | rc=0 |
| positive control: `git worktree remove /tmp/foo` | rc=0 |

The positive controls matter: the hook is not blanket-denying, the rule is specific to `rm`.

**The ban is unconditional with respect to `/merge`.** It is not an agent-only limitation that a
human typing `/merge` escapes: PreToolUse governs the model's Bash tool regardless of who typed
the slash command, and the model is what executes Step 3.

One general escape exists and is deliberately NOT used: the `/allow` sentinel-grant path — the
block whose comment reads
`Reads /tmp/claude-grants/<task_id>.json via hooks/lib/allowlist.py` — is evaluated earlier in
the file than the `rm` rule, so a human-authorized `/allow` grant could reach it.
Touching the authorization layer to make a documented step run is forbidden; the grant is left
unconsumed and the gap recorded instead.

**Consequence while unfixed:** a merge-analyst grant is never consumed by the orchestrator, so
it stays replayable on disk until its TTL lapses. The privilege guard's own `_unlink_grant` does
not cover this, because the guard never fires for the wrapper (the wrapper's `git merge` runs in
a subprocess PreToolUse does not inspect — verified by execution: `merge.sh` invoked with a
remote-tracking ref, a tag, and a bare hash all returned exit 0 with the guard never
intercepting).

## Defect 2 — the 60-second grant TTL cannot survive a subagent hand-back

`agents/merge-analyst.md` Phase 8 sets `expires_at` to mint time + 60s. Step 2 requires the grant
to be produced by a dispatched subagent. Dispatch round-trip plus hand-back exceeds 60s.

Measured across three consecutive attempts on one analysis.

**Rule for the table below: `minted` means `expires_at − 60s`, uniformly, and no other timestamp
may be substituted.** Each value is derived from that grant file's own `expires_at` field, which is
the authoritative value and the one that makes every row's window exactly the 60s stated above.
Two other timestamps exist per grant and must not be used: the grant file's mtime, which for these
three grants runs up to about 25 seconds later than `expires_at − 60s`, and merge-analyst's own
audit-log entry, which is earlier still. An editor who substitutes either one into any row makes a
fixed 60-second TTL read as a variable one.

| attempt | grant nonce | minted | expired | orchestrator reached it | outcome |
|---|---|---|---|---|---|
| 1 | `844eaa30` | 15:46:20Z | 15:47:20Z | 15:47:31Z | expired by 11s |
| 2 | `c2b7655f` | 16:00:56Z | 16:01:56Z | after expiry | expired |
| 3 | `d363670c` | 16:04:28Z | 16:05:28Z | 16:04:56Z | **+31.4s margin, consumed** |

Attempt 3 succeeded only by collapsing Steps 3, 4 and 5 into a single immediate tool call with no
intervening reasoning, and still had barely half the window left.

`commands/merge.md` Step 3's documented remedy — "If expired: re-dispatch merge-analyst (return
to Step 2 with a fresh REQUEST_ID)" — **provably loops**: every re-dispatch is itself a subagent
round-trip, so it reproduces the condition it is supposed to recover from. The remedy is only
escapable by luck in the orchestrator's own latency.

## What is NOT affected

- **The merge itself.** Step 5's documented form `bash ~/.claude/hooks/merge.sh "<ref>"` is
  permitted (rc=0 when probed). The production merge does not hit either defect; it is gated only
  by the in_place clean-tree precondition.
- **`hooks/merge.sh`'s own internal `rm -f "$sf"`** — the overnight-state cleanup loop, which
  iterates `overnight-state-*.json` after the branch-deletion step — runs
  inside the wrapper's subprocess, which PreToolUse never inspects.
- **`/push`.** Its documented wrapper invocation, `bash ~/.claude/hooks/push.sh`, is invoked as
  documented and probes rc=0.
- **`/commit` — this entry is a withdrawal, narrowed, not a re-spelled path.** An earlier form of
  it paired the push probe with a commit one, asserting rc=0 for a commit wrapper it placed under
  `hooks/`. No commit wrapper exists there; the real one is `scripts/commit.sh`. That probe
  therefore named a nonexistent file, and a safety hook declining to object to a nonexistent path
  proves nothing about `/commit`. The rc=0 assertion for the commit half is **WITHDRAWN**, and is
  deliberately NOT re-asserted against the real path — no one measured that, and re-spelling the
  path would assert a result nobody took. `/commit` is unaffected by both defects regardless, but
  structurally rather than by probe: `commands/commit.md` names no wrapper at all, and `/commit`
  reaches none — it dispatches the changelog-analyst subagent — so there is no wrapper invocation
  for the text-matching rule to match.

End-to-end proof that everything except the two defective steps works, from the clone exercise:
tier resolution → Step 1 snapshot (source peeled via `^{commit}`; `refs/heads/upstream/master`
does not resolve, so the peel is load-bearing) → merge-analyst dispatch, Phases 1-5 →
grant binding validation, all 11 fields PASS with a live TTL → Step 4 tip revalidation → Step 5.
Result: merge commit `eef0b32532620f3094d4a1eee028ac698053289d`, parents
`5db000d3eee65f11b70bf07a53fefcf0c564cf85` and `fa0aea69ccedee7a9fdc71f3b0bfece0fc86c983`,
0 behind / 146 ahead, clean tree, lifecycle cleanup correctly announced-and-skipped for a
non-branch source. The self-merge path was exercised separately by dispatching merge-analyst with
identical tips: Phase 1 fired and returned `verdict: blocked`.

## Fix direction — NOT implemented here

**Consumption must not be a `rm` in prose.** The commit pipeline already solved this problem:
`hooks/posttool-allowlist-consume.py` consumes its sentinel from a PostToolUse hook on any
terminal result, so no one ever types a delete command. `/merge` should consume its grant the same
way — hook-driven on the wrapper's terminal result — or by renaming the grant out of the glob
pattern `_find_merge_grant` matches, rather than by requiring a globally-forbidden command.

**The TTL must not be shorter than the flow that must traverse it.** Commit grants run 300s; the
`/allow` sentinel runs 300s. A flow that mandates a subagent dispatch between issuance and
consumption cannot be given 60s. Either lengthen it, or re-base expiry on the consumption attempt
rather than on issuance.

## Known-unfixed, recorded rather than silently carried

- **`commands/merge.md` tier 3 can only ever produce a blocked self-merge.** On the main checkout,
  tier 3 resolves the source to the current branch; when HEAD is on the default branch — the normal
  case — source and target are the same commit. The refusal is correct, but it rejects a source the
  resolver itself chose, not a user error. Whether tier 3 should decline to resolve instead is a
  design question, deliberately left to its own cycle.
- **`hooks/pretool-git-privilege-guard.py` resolves a grant's source tip as
  `refs/heads/<branch_arg>`** — in the function `_validate_merge_grant_source_tip`, at the
  expression building `'refs/heads/%s' % branch_arg` — a third copy of the assumption removed
  from the wrapper and the command doc. It cannot resolve for a remote-tracking ref, a tag, or a
  bare hash. It is latent, not live: the guard never intercepts the wrapper (proven by execution
  above). Left unfixed here because that file held another session's uncommitted work.
- **The `daemon-restart-wrapper` rule in `hooks/pretool-bash-safety.sh` — search for the string
  it emits, `bash invocation of disposable wrapper script is FORBIDDEN` — matches on command
  text, not on what executes.** `bash /dev/shm/.../hooks/merge.sh` is blocked while the equivalent
  `bash ~/.claude/hooks/merge.sh` and a path held in a shell variable are both permitted — so for a
  checkout that lives on tmpfs, whether the rule fires depends on how the path is spelled. Recorded
  as a known weakness; not used as a route.
- **`commands/commit.md` Step 5 documents one of the three exit states
  `scripts/verify-attribution-chain.py --json` actually returns, so a caller that follows it can
  silently discard a `BREAK`.** The script's exit is three-state: 2 when there are no results at
  all, 1 when any path's verdict is not `CONTINUOUS_TAIL_MATCH`, 0 when every path matches. Step 5
  documents only the rc=2 case, describing exit 2 as "no journaled events for any requested path,
  an expected outcome". Measured on this cycle's six owned paths: `commands/INDEX.md` and
  `commands/README.md` both `BREAK`, the other four `CONTINUOUS_TAIL_MATCH`, whole-run exit 1.
  **Correction: an earlier version of this bullet also claimed the script emits a separate JSON
  document for each `--file`, concatenated, and cited a `JSONDecodeError` (`Extra data`, char
  8538) as proof. That claim was WRONG** — source and execution both show one merged document,
  the shape Step 5 declares. The script holds exactly one `print(json.dumps(` of the `{"results",
  "no_events", "discarded_lines"}` object, and it sits outside the per-file loop; run in the
  single repeated-`--file` form Step 5 builds, over those same six paths, it exits 1, writes 8538
  bytes, and parses as ONE document with `results` of length 6 and `no_events` empty. 8538 is that
  document's full length and also the exact offset the quoted error reports, and an `Extra data`
  error at offset N means a parser consumed a complete document ending at N and then found further
  input — so the extra data was appended by this cycle's own caller, not emitted by the script.
  How it got there was not isolated, and no mechanism is asserted here. Both remedies that claim
  implied go with it: emitting the merged document is already what the script does, and splitting
  the invocation per path is what produces the error. Fix direction for what remains, not
  implemented here: document all three exit states in `commands/commit.md`, or make the script
  two-state to match the doc — and add a check that fails when the two disagree, since the only
  reason this gap survived is that nothing compares them.

## Measurement method

Both defects were established by execution, not by reading: the `rm` rule by piping synthetic
PreToolUse payloads into the hook and recording exit codes, with positive controls to show the
hook was not denying everything; the TTL by three timed attempts whose mint and expiry timestamps
are above. Do not re-derive either from the hook's source alone. Cite any of it in the form the
citation rule at the top of this record requires; that rule, not this paragraph, states the
prohibition and fixes its reach.
