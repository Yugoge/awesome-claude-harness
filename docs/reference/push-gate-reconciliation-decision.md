# Push-gate reconciliation — decision to keep

> Last updated: 2026-09-05. **Status: decided and closed.** The keep / harden /
> remove question is settled in favour of KEEP. Later cycles must not re-open it.

**Mechanism under decision**: `agents/changelog-analyst.md` §Push-gate reconciliation
**Consumer contract**: `commands/commit.md` (`status = push_gate_reconciled`)
**Attribution record**: `hooks/lib/commit_journal.py`
**Journal writer**: `hooks/posttool-allowlist-consume.py`
**Gate enforcement**: `hooks/push.sh`

This record explains the mechanism before it states the verdict, because the verdict
is only meaningful to a reader who knows what is being kept. Sections 1-4 are
verified against the sources above; section 5 records a decision, not a proof.

---

## 1. What the push-gate is

`/commit` writes a **push-gate token** after a real commit. `/push` refuses to run
without one.

- **Write**: on each successful commit, `changelog-analyst` writes a token to
  `/tmp/agentic-commit/push/<sha256(realpath(GIT_ROOT))[:16]>/<sha256(PUSH_GATE_SID)[:16]>/<branch>.json`
  (`commands/commit.md:319-320`). The path is keyed by repository, by session and by
  branch, so two sessions on one branch do not contend for a single slot.
- **Validate**: `hooks/push.sh:250-283` reads the token and compares its `commit_sha`
  field against live `HEAD`. A missing token, an unreadable token, or a
  `sha_mismatch` all refuse the push.
- **Consume**: `hooks/push.sh:472` (`rm -f "$_TOKEN_PATH"`) deletes the token on the
  post-push success path. The token is single-use.

The property this buys is narrow and worth stating without inflation: **it evidences
that the commit now at HEAD was produced through the sanctioned commit path.** It is
not an authorization boundary. `hooks/push.sh` authorizes on `commit_sha == HEAD`
alone and no hook guards `/tmp/agentic-commit/**`, so an actor who can emit arbitrary
Bash can write a token directly (`agents/changelog-analyst.md:1439-1447`). The gate
is an integrity check against *loss and mistake*, not against an adversary.

## 2. What reconciliation is

Reconciliation is the recovery path that **retroactively writes a missing token for a
commit already at HEAD**, creating no new commit.

It exists because the ordinary failure is otherwise terminal. If Phase 10 reaches its
end without writing a token, the commit lands tokenless and *no subsequent invocation
can ever tokenize it*: the tree is now clean, so no future run commits, and the
sibling `nothing_to_commit_precommitted` recovery is gated on the HEAD subject
matching `/^auto-bulk:/`, which a conventional-commit subject can never satisfy.
`/push` stays blocked forever and re-running `/commit` returns `nothing_to_commit`
indefinitely (`agents/changelog-analyst.md:1240-1250`).

**Seven routes reach that state, and nothing at reconciliation time can tell which
one applied.** `agents/changelog-analyst.md` §Push-gate reconciliation, "Which cases
actually survive" (lines 1252-1332) is the canonical enumeration; it is reproduced
here rather than paraphrased, and **no single route may be restated as THE cause**:

1. **The Phase 10 token Write failed or was refused** — tool error, guard rejection,
   disk.
2. **The invocation was interrupted between the commit and the token Write** — quota
   exhaustion and subagent termination are both live events in this harness.
3. **The commit was already pushed.** `/push` deletes the token on success, leaving
   exactly the empty-slot-plus-attributable-HEAD state this path fires on. Condition
   7 normally absorbs this, but only when an upstream is configured; with no upstream
   `merge-base --is-ancestor HEAD @{u}` errors and publication is treated as unknown,
   so reconciliation proceeds and writes a token nothing needs. Harmless to the gate,
   but it *is* this path firing.
4. **A peer replaced HEAD with a same-parent commit inside the post-lock window.** The
   journal hook, reading live HEAD in that window, records the *peer's* sha against
   this session's `parent_head`; the entry passes the parent-linkage bind because the
   peer's commit genuinely has that first parent, while Phase 10's pre-write
   HEAD-stability check returns `push_gate_race` and writes nothing. **On this route
   the commit reconciled is the peer's, not this session's.** See §4.
5. **HEAD left this session's own journaled commit and was later restored to it.**
   Freshness is compared against live HEAD at query time and no entry is ever marked
   superseded, so the round trip re-enables the match. Needs no history destruction
   and no shared parent — a peer abandoning its commit, a `reset`/`checkout` back, or
   a `rebase --abort` all do it. The reconciled commit here is this session's own.
6. **Branch-segment namespace drift.** Tokens are branch-keyed while journal matching
   deliberately ignores the entry's recorded branch. Renaming, or switching branch at
   the same unpublished HEAD, leaves the old token in the old slot and presents an
   empty new one.
7. **Session-segment namespace drift.** The token path carries one alias
   (`PUSH_GATE_SID`, preferring `CLAUDE_CODE_SESSION_ID`) while the journal records up
   to four identifying ids and accepts *membership* in that set. The commit grant's
   own `sid` resolves by the opposite precedence
   (`scripts/write-commit-grant.py` prefers `CLAUDE_SESSION_ID`), so the two disagree
   by construction under ordinary orchestrator/subagent divergence. A later run
   resolving a different member of the set finds an empty slot and fills it.

Routes 6 and 7 are documented rather than fixed, deliberately: narrowing the matcher
to one canonical id would refuse the legitimate id divergence the candidate set
exists to admit, and re-ordering the chain would only change which pair drifts.

**Rule 7 of the DO-NOT list is not among these cases.** It rejects a token only when
its recorded `session_id` differs from `PUSH_GATE_SID`, so it cannot fire within one
session, and two lanes of one fan-out share `PUSH_GATE_SID` by construction. Do not
re-add same-session contention to the list (`agents/changelog-analyst.md:1334-1345`).

## 3. The safeguards that make it acceptable

Reconciliation runs only when **all seven** trigger conditions hold
(`agents/changelog-analyst.md:1351-1473`). Three are load-bearing against
mis-attribution:

- **The token slot must be EMPTY** (condition 4). If any token is present the path
  does not run — whether it belongs to this session (nothing to reconcile) or to a
  peer (rule 7 forbids touching it). Rule 7 is never relaxed. Note that condition 4's
  result is *advisory* by write time: no lock is held across the gap, so the
  **pre-write re-read is the authoritative check**, and a token appearing in the
  window is never overwritten (`:1481-1488`).
- **Attribution comes from the commit-event journal, written by the hook layer, not
  by the committing agent** (condition 5). `hooks/posttool-allowlist-consume.py:656-662`
  appends one entry for a `git commit` authorized by a single-use grant that reached a
  success terminal result. The matcher reads fields that live *outside* the commit
  object, so no property of a commit — subject, `Task-id:` trailer, file set — can
  satisfy it. The superseded design inferred attribution from trailer and file set;
  both are chosen by whoever made the commit, and both misfire without any adversary
  at all, because fan-out lanes carry prefix-related task ids and overlapping file
  sets by construction. The query fails closed: exit 0 is the only result that
  permits reconciliation.
- **Parent linkage must verify.** The entry's recorded `parent_head` must be the
  actual first parent of its recorded `resulting_head`, resolved in the bound
  repository and compared as exact shas. The read is from the raw commit object with
  replacement suppressed (`git --no-replace-objects cat-file commit <sha>`), which is
  what makes it immune to *both* `refs/replace/*` and `.git/info/grafts` — each
  defeats only one half of that command, both are reachable from inside the
  repository, and either can move the answer in either direction. It must not be
  simplified to `rev-parse <sha>^1`. It fails closed on anything unreadable, on a
  non-sha parent, and on a root commit.

The remaining four: `BULK=false` and `DRYRUN=false` (1); empty candidate set (2);
`HEAD` verifiable, not unborn or detached (3); every owned path clean in
`git status` (6); and `HEAD` not already published (7).

The path creates no commit, does not stage, does not take the fd-9 commit lock, and
consumes no commit grant. When condition 5 alone fails it **refuses loudly** —
`push_gate_reconciliation_declined: no_journal_entry` plus a warning naming HEAD as
un-pushable — rather than guessing.

## 4. The residual being knowingly accepted

**On the same-parent race, the reconciled commit can be a peer's rather than this
session's.** This is an accepted residual, not a defect awaiting a fix.

The precise shape (`hooks/lib/commit_journal.py::_parent_linkage_verified`): the
linkage check compares shas, so it cannot separate two commits that genuinely share a
first parent. A peer that **hard-resets to this session's grant head and re-commits**
inside the post-lock window produces a sha whose actual first parent *is* the recorded
`parent_head`. That entry validates and remains attributable, and a later
empty-candidate `/commit` tokenizes the peer's commit under this session's
attribution.

Two qualifications keep this honest in both directions:

- It requires the peer to **destroy history at exactly the raced instant AND land on
  the same parent**. The ordinary linear race — a peer committing on top of what is
  already there, which is what concurrent sessions on one branch actually do — is
  **closed** by the linkage bind.
- It is why the mechanism must be read as **"attributed to"**, never "created by".
  The journal is an attribution record; it does not prove identity. The
  same-session-only attribution test covers every surviving route as a *coverage*
  claim, not a soundness claim.

A second accepted residual: **a session the journal does not name cannot reconcile.**
That commit stays un-pushable through this path forever. The only cross-session basis
available would be "same task id", and a task id is not an identity — any actor can
mint a grant carrying any `--task-id`, and a legitimate retry after a restart produces
two live sessions sharing one. A weaker tier there would restore the original defect
in a new costume.

## 5. The verdict, and the basis on which it was taken

**KEEP the push-gate reconciliation path.** Recorded as the user's decision.

The stated basis: removing reconciliation would eliminate **only 1 of the 15 round-4
audit findings**. Findings 3 through 13 attach to the commit-authorization guard and
the deferred-grant lifecycle. Those exist at HEAD independently and survive the
removal untouched. So "remove it to shrink the audit surface" buys 1/15, and the
argument does not hold.

This is recorded as a decision, not as a technical proof. The count and the
attribution of findings to components are the user's; this document does not
re-derive them.

## 6. What the rejected option would have cost

Without reconciliation, **a commit that lands but loses its token becomes permanently
unpushable through the wrapper.** Section 2 gives the mechanics: clean tree, so no
future run commits; conventional subject, so the auto-bulk recovery gate never
matches. The only remaining recoveries are a **human `git push`** or **re-running the
originating session**.

That cost is paid on all seven routes in §2, including the two that need no
concurrency at all — a refused token Write and a quota-interrupted invocation — both
of which are ordinary events in this harness rather than exotic ones.

## 7. Why "harden" was also declined

Adding further checks to narrow the §4 residual was considered and rejected on the
same accounting as removal: **each added check is itself new code, and new enforcement
code in this repository carries an obligation to be falsifiable** — a corpus entry, a
ledger row, and a behavioural driver (the pattern set by `docs/ADVERSARIAL-CORPUS.md`,
`docs/ENFORCEMENT-LEDGER.md`, and `hooks/tests/`). Hardening therefore manufactures
its own audit surface, which is the cost the removal argument was trying to avoid.

This is distinct from — and does not overrule — the redesign the source already names
as better and deliberately out of scope: having the journal-writing hook write the
**token** itself, closing the loss window that makes this whole path necessary. That
would not close the HEAD race (the hook also runs after the lock is released and reads
live HEAD, so it would need the same parent-linkage bind), and it ripples into Phase
10's contract, bulk mode, multi-repository ordering, the `DRYRUN` planning pass and
`/push`'s token expectations. `agents/changelog-analyst.md:1524-1533` requires it to
be scoped and security-reviewed as its own cycle. **Nothing in this decision
authorizes it; nothing here forecloses it either.**

## 8. Scope of this record

This document decides **keep vs. harden vs. remove, and nothing else.** It changed no
implementation, no guard, no grant machinery, no hook and no script.

One correction to the framing this record was commissioned under, kept here so the
next reader inherits the accurate version: the §4 residual is *not* caused by the
post-lock journal-append window alone. That window is necessary but not sufficient —
the peer must additionally destroy history onto the same first parent. The linkage
bind closes the ordinary case. Stating the window as the whole cause overstates the
residual.
