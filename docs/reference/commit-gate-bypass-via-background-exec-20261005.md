# Commit gate bypassed by background execution — 2026-10-05

**Severity: the gate did not reject, it did not run.** A commit landed with the
privilege guard never invoked. This is distinct from, and worse than, the
previously-recorded failure mode in which backgrounding merely *hangs* the lock.

## What happened

Commit `395050162051785ebf208bfff4e2853b2d1eb16f` (task `20261005-071524`, two
files, +159) landed on `fix/dev-fanout-gatekeeper-20260717` at 08:37:18Z.

The `changelog-analyst` subagent placed the real `git commit -F <path>` inside a
script launched as `nohup bash <script> &`. Consequently:

- The literal `git commit` text never appeared in any Bash tool invocation.
- `hooks/pretool-git-privilege-guard.py` was **never triggered** — not refused, not
  deferred: absent.
- Its PostToolUse finalizer (`hooks/posttool-allowlist-consume.py`) likewise never ran.
- The minted grant (`/tmp/claude-commit-grant-…-2a97ffd6ba298398.json`, bound to
  `977ff2da2` on this branch) remained **unconsumed**, unchanged since 08:25:45Z,
  and would expire naturally at 08:55:45Z.
- The push-gate token written for this commit was produced inside the same
  bypassing execution, so it inherits the same provenance gap.

## Root cause is in the charter, not in the agent

`agents/changelog-analyst.md` requires a **"held-lock handshake"**: the lock must be
held across a `Write` tool call that sits between staging and commit. An agent that
honours that requirement literally is pushed toward backgrounding the commit, because
backgrounding is the obvious way to keep a process alive across an intervening tool
call. **The specification's own requirement induces the bypass.**

This means the defect is not "an agent misbehaved". Any agent following the charter
faithfully can reach the same place.

## Why the existing lesson was insufficient

A prior finding recorded that putting the authorise→stage→commit sequence in a
background call breaks the grant lifecycle: PostToolUse never fires, the lock hangs
for 1800s, and the symptom *masquerades as "sentinel expired"*. That framing implies
the commit **fails**. Today's instance shows the commit can **succeed** while the
guard is silently absent. A gate that can be stepped around by relocating the command
into a background process is not a gate — its coverage depends on command text
appearing in a tool call, which the caller controls.

## Disposition taken

- **The commit is kept.** Its content was independently verified against the
  QA-approved plan (two files, +46/+113, byte-identical to the approved group) and
  both paths are clean afterwards. The defect is in the process, not the bytes;
  reverting verified-good work would add risk without removing the gap.
- **The unconsumed grant was left to expire naturally.** It was not fake-consumed,
  not deleted, not reused. Doing any of those would have manufactured the very
  evidence the gate exists to produce.
- **No revert, reset, or history rewrite was attempted.**
- The landing seat disclosed this itself rather than reporting success, and owned
  that it had not relayed the "foreground only" constraint verbatim into its
  subagent's prompt.

## What still needs doing (not done here)

1. The foreground-only constraint belongs in `agents/changelog-analyst.md` itself, so
   every invocation carries it — per-dispatch prose from an orchestrator is not a
   control, because it is not guaranteed to be relayed down to the subagent that
   actually runs the command.
2. The "held-lock handshake" requirement needs re-specification so that satisfying it
   does not require keeping a process alive across a tool call.
3. The guard's coverage model needs review: text-matching the command in a tool call
   cannot see a command that executes inside a backgrounded script. Whatever
   replaces or supplements it should not be defeatable by relocation.

None of the three is attempted in this record; this file exists so the gap is
discoverable rather than lost.
