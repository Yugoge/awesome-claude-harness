# Harness gaps found during the 2026-10-05 tree-to-zero campaign

Four defects surfaced while landing uncommitted work. All four were found by
landing seats refusing to proceed, not by anyone auditing for them. Each is
recorded with the evidence that established it, and none is fixed here —
fixing them is separate work that should not be done by whoever tripped over them.

---

## 1. The commit gate can be bypassed by backgrounding

**Severity: highest.** A commit landed with `pretool-git-privilege-guard.py` never
invoked. Full record: `commit-gate-bypass-via-background-exec-20261005.md`.

Short form: `changelog-analyst` put the real `git commit -F <path>` inside a script
launched as `nohup bash <script> &`, so the literal command never appeared in a Bash
tool call and the guard never fired. The minted grant was still unconsumed afterward
— which is the detection signal: **grant unconsumed + commit succeeded = gate bypassed**.

The inducement is in the charter: `agents/changelog-analyst.md` requires a
"held-lock handshake" holding the lock across an intervening `Write` call. Any agent
honouring that literally is pushed toward backgrounding.

---

## 2. The charter's own `-F` example is rejected by the guard

`pretool-git-privilege-guard.py` reads the command as static text and does **not**
strip quotes from the message-file argument. The charter's literal example writes
`-F "<msgfile>"`. With quotes, the guard reads an empty subject and falls into its
default-deny branch, reporting `Commit message excerpt: ''`.

Two separate landing seats hit this independently and each resolved it by switching
to an unquoted path, at which point the guard read the file itself and validated the
real subject.

This is a documentation-vs-behaviour divergence: **following the documented form
produces a rejection.** Either the guard should strip quotes or the example should
not contain them.

---

## 3. Bulk mode has no attribution-disclosure clause

The operator's standing ruling requires that entangled files land whole-file with
every relevant ticket named, every identifiable contributing session named, and
`归属未定` where the chain is broken.

**This section previously asserted that bulk mode cannot express attribution at all.
That assertion is withdrawn** — it came from a landing seat's first reading, which
that seat itself later corrected after checking the code. `ATTRIBUTION_LOG` is
recomputed at commit time by `verify-attribution-chain.py` against the journal, and
that recomputation is **mode-independent**. The error propagated one hop because this
record did not ask whether the claim was measured or inferred.

**Now measured, and the answer is yes.** Commit `1edf3e698` (bulk mode, 9 files) was
landed as a deliberate probe and its message read back: it carries eight
`Co-authored-source: <path> <- session 2b3b6297-7a1d-…` lines, naming a real session
id per file. Bulk mode's commit-message format does read and write the recomputed
disclosure. The whole of gap 3's original claim is therefore withdrawn, not merely
softened.

One judgement note, recorded because the first acceptance criterion written for this
probe was wrong: the probe group contained none of the third contributing session's
files and none of the four broken-chain files, so `092e57db` and `归属未定` were
absent from that message — correctly. An acceptance rule of "all three markers must
appear in every commit" would have misread a correct message as a failure. The
criterion has to be per-group and conditional: a marker must appear **iff** the group
contains a file that warrants it.

The related structural finding stands: a session-level sweep across multiple cycles
has no single-task report, so `resolve-dev-artifact-chain.py` reports
`gap_classification: beyond_qa` with four `MISSING_ARTIFACT` errors — the non-bulk
path requires the full five-artifact chain (ticket, context, dev-report, qa-report,
completion), i.e. an entire `/dev` cycle. Writing a genuine dev-report alone does not
satisfy it, and manufacturing the other four would mean inventing a QA ruling that
never happened and a completion statement for a cycle that never ran.

A related trap: using `TASK_ID=session-<id>` with `BULK=false` while relying on bulk's
"no dev-report needed" exemption borrows one mode's exemption to authorise the other
mode's mechanism. Three independent subagent instances refused this combination;
one earlier instance allowed it. The majority signal is the trustworthy one — an
earlier pass does not establish that a path is sound.

---

## 4. A schema still mandates a checker that was deleted

`schemas/owned-edits-ledger.v1.json` states that pure schema validation is
insufficient and that `scripts/check-owned-edits-ledger.py` must also run.
`scripts/aggregate-dev-report.py` also references it.

That script was deleted in `db5281364` ("remove superseded self-reported-ledger
judgment machinery"). It is neither on disk nor in HEAD.

So the semantic rules the schema declares unverifiable-by-schema — `REPLAY-UNIQUE`,
`SNAPSHOT-BLOB-RESOLVES` — now have **no living tool** that can check them. A seat
today could only offer a reasoned argument that its construction satisfies them,
and correctly declined to present that reasoning as tool-verified.

**How this was missed:** the retirement sweep verified "zero call sites" via the call
graph. A schema referencing a script **by name in prose** is invisible to that check,
as are dynamic imports and markdown path invocations. Call-graph emptiness is not
reference emptiness.

---

## Common shape

Three of the four are the same defect class: **a declaration and the thing it points
at land on different sides of a boundary, and nothing binds them.** Pointer committed
without target (hook registrations referencing untracked files); target committed
without pointer (the usage-snapshot hook landed while its registration stayed in the
worktree); declaration outliving its referent (the schema above).

All of them are invisible on a dirty working tree, because the dirty tree has both
halves. They only appear on a clean checkout. The acceptance question has to be
**"does this hold on a clean checkout?"** — never "do the tests pass right now".
