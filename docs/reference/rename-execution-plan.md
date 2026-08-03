# Rename execution plan — `awesome-claude-harness` → `claude-code-guardrails`

> Authoritative in-tree record of the rename: what was flipped, what was deliberately left,
> why, and what remains the **user's** to execute outside this working tree.
> Baseline for every count and citation below: `4c33f2f5`.

---

## Callout — the single remaining user-visible inconsistency

After this change a reader sees the **new** name in the README title and the **old** name in
the install command. That is honest — the clone line names the repository's *actual current*
URL — but it is the one place the split is visible to a user, so it must be flipped the moment
the GitHub repository is renamed.

**The line to flip, identified by its exact text (not by a line number — a sibling lane
restructures the README's first screen):**

```
git clone https://github.com/Yugoge/awesome-claude-harness.git claude-harness
```

*(This command previously cloned over `~/.claude`; a sibling lane has since rewritten the
install section to clone into a directory of the reader's choice instead. The **URL** — the
only part this plan gates — is unchanged, so the gate below is unaffected.)*

**This line is security-relevant.** The clone is immediately followed by `cd claude-harness`
and `scripts/bootstrap`, so the reader executes code from whatever repository that URL
resolves to. If the GitHub rename happens and the rename redirect later decays (see the
redirect-decay caveat below), this command would fetch and then run a bootstrap script from a
repository someone else controls. Flip it **promptly** after the external rename; do not leave
the pair "renamed on GitHub / old URL in-tree" standing.

---

## What this document is not

It authorizes nothing. No step below was executed against GitHub, any remote, or any
registry. Renaming the repository, publishing, announcing and tagging are the **user's**
decisions and the **user's** to execute; this lane performed none of them and planned none of
them as automated steps.

---

## Reserved CLI name — `claude-guard`

`claude-guard` is **reserved in writing only**. No executable, entrypoint, binary, wrapper or
`claude-guard doctor` stub exists in this tree, and none was created.

| Field | Value |
|---|---|
| Reserved CLI name | `claude-guard` |
| Status | **name reserved, not built** |
| Owner of the real CLI | **Lane C (installer)**, which defines canonical on-disk identity |
| Blocking dependency | Lane C itself depends on **Lane A** (host-capability gate) |

Rationale for building nothing: a `doctor --strict` that does not genuinely verify the host
would itself be the silent-no-op defect the capability-gate work exists to eliminate. A stub
shipped ahead of Lane A would be worse than no CLI at all.

---

## The three-tier occurrence set

An incomplete rename is only a defect where the residue is **identity surface** — what a
stranger evaluating the project actually reads. Residue in internal identifiers is not a
positioning failure, and renaming some of it is actively unsafe *right now*.

### Tier 1 — in-tree identity surface, flip now

| Location | What changed | Status |
|---|---|---|
| `README.md` H1 | name + framing | **DONE** |
| `README.md` lead sentence | leading noun phrase + routed clause cut | **DONE** |
| `ARCHITECTURE.md` H1 | framing | **DONE** |
| `.github/CONTRIBUTING.md` | name | **DONE** |
| `LICENSE` | project name in the parenthetical **only** | **DONE** |
| `NOTICE` | name | **DONE** |
| `tools/demo/sample-trace.json` | `session_title` | **DONE** |
| `tools/demo/manifest.schema.md` | doc example string | **DONE** |
| `.github/assets/demo-trace.json` | `session_title` | **DONE** |
| `.github/assets/hook-trace.json` | `session_title` (` · hook kernel` suffix preserved) | **DONE** |
| `.github/assets/pipeline-hero.svg` | chrome title | **DONE** — regenerated, never hand-edited |
| `.github/assets/hook-hero.svg` | chrome title | **DONE** — regenerated, never hand-edited |
| `INDEX.md` — `ARCHITECTURE.md` framing mirror | derived heading | **DONE** — regenerated |
| `INDEX.md` — `THREAT-MODEL.md` name mirror | derived heading | **BLOCKED** — see Tier 1-B |
| `docs/THREAT-MODEL.md` H1 | name | **BLOCKED** — see Tier 1-B |

The `LICENSE` edit changed **only** the project name inside the parenthetical. The copyright
holder, the year and the entire licence body are byte-identical.

### Tier 1-B — Tier 1 work blocked in this pass, still owed

These are **not** deferred on their merits. They are Tier 1 and should land as soon as the
blocking condition clears. They are listed here so the residual old-name count reconciles to
zero unaccounted matches.

| Location | Blocker | Clears when |
|---|---|---|
| `INDEX.md` — the `THREAT-MODEL.md` tree entry | Auto-generated (`<!-- AUTO:index-stats -->`); a derived mirror of the `docs/THREAT-MODEL.md` H1. Regenerating it does **not** clear the name — the mirror faithfully reproduces whatever that H1 says, so it cannot resolve before the H1 flips. | `docs/THREAT-MODEL.md` flips, then INDEX is regenerated |
| `docs/THREAT-MODEL.md:1` | **File-ownership boundary** — a concurrently running sibling lane owns this file in this wave. Editing it here risks clobbering that lane. | The sibling lane lands |

The four generated-artifact rows that stood here after the first pass — both trace JSONs and
both hero SVGs — **have since been cleared**. Each trace `session_title` was flipped and each
SVG was **regenerated** from its trace, never hand-edited; the regenerated assets were verified
byte-identical against fresh generator output, both strict provenance audits exit `0`, and each
chrome title holds its character length (31 → 31, 45 → 45). The derived `ARCHITECTURE.md`
framing mirror in `INDEX.md` was cleared by the same regeneration, and `INDEX.md` was proven to
be generator output by a run-1-vs-run-2 idempotence check.

**Do not hand-edit any row above.** Two of them are generated art and one is an auto-generated
index; hand-editing them defeats the provenance audit that exists to catch exactly that.

### Tier 2 — gated on the user's external GitHub rename (do **not** flip yet)

Every line below is a live `https://github.com/Yugoge/awesome-claude-harness…` URL.

| Location | Line | Reason |
|---|---|---|
| `README.md` | `git clone https://github.com/Yugoge/awesome-claude-harness.git claude-harness` | install command — see the opening callout |
| `README.md` | `Released under the **MIT License** … Source: [`Yugoge/awesome-claude-harness`](https://github.com/Yugoge/awesome-claude-harness).` | source link (**this single line carries the old name twice**) |
| `CHANGELOG.md` | `[Unreleased]: https://github.com/Yugoge/awesome-claude-harness/compare/v1.0.0...HEAD` | compare link |
| `CHANGELOG.md` | `[1.0.0]: https://github.com/Yugoge/awesome-claude-harness/releases/tag/v1.0.0` | release link |
| `NESTED-REPO.md` | `- **Remote**: `git@github.com:Yugoge/awesome-claude-harness.git`` | remote |
| `docs/reference/git-fswatch.md` | `Report issues: https://github.com/Yugoge/awesome-claude-harness/issues` | issues URL |

**The Tier 2 gate, and why the asymmetry is decisive.** Flipping these in-tree **before** the
external rename points every one of them at a **404** — the new URL does not exist yet.
Flipping them **after** the rename is safe even if delayed, because GitHub serves a redirect
from a repository's previous name. Early = broken; late = works. So the correct order is:
rename on GitHub first, flip these second.

**Redirect-decay caveat.** GitHub's rename redirect from the old name is **not permanent**: it
stops working if anyone later creates a new repository at the old name. A stale in-tree URL is
therefore not merely untidy — combined with the clone-then-`scripts/bootstrap` sequence in the
callout above, it is a supply-chain exposure. Flip Tier 2 **promptly** after the external rename rather than
leaving it indefinitely.

*(Both the redirect behaviour and its decay are inferred from GitHub's documented rename
semantics and were not externally verified from this tree. The plan is safe either way: not
flipping is correct under both branches, which is why the gate only ever needs to hold in the
"do nothing now" direction.)*

### Tier 3 — internal identifiers, not renamed; migration recipe recorded

None of these is identity surface — no adopter ever sees them — so renaming them delivers zero
user-facing value, and canonical on-disk identity is **Lane C's** to define when it ships the
installer. The risk notes are why, *when* they are renamed, it must be done with **dual-accept**
rather than a find-and-replace.

| Occurrence | Lines | Why not now / risk when it happens |
|---|---:|---|
| `.claude/.awesome-claude-harness` (filename + content) | 1 | Internal repo-identity sentinel. Consumed by an **existence test** at `hooks/session-gitignore-propagate.sh:22` whose failure mode is `exit 0` — indistinguishable from success. Any checkout landing the hook edit without the file rename silently disables the hook. |
| `hooks/session-gitignore-propagate.sh:21,22` | 2 | Consumer of the above; moves with it. |
| `PUBLIC-CORE.md:122` | 1 | Accurately documents the sentinel's real filename; stays correct precisely *because* the sentinel is unchanged. |
| `hooks/lib/subagent_restart.py:31` | 1 | `MESSAGE_MARKER = "[awesome-claude-harness/restart-v1]"` — a **versioned cross-session wire-protocol string** matched against transcripts. Renaming it breaks `/restart` recovery for in-flight and historical sessions. |
| `tests/generated/**` (8 files) | 14 | Frozen historical acceptance-criteria skeletons from cycles `20260704-*`, excluded from the default test run. Rewriting a past cycle's recorded text falsifies history. |

**Migration recipe (dual-accept) — so this residue is not permanent by neglect.** When the
sentinel is renamed, alongside Lane C:

1. Rename the marker file and land the hook edit in the **same** commit.
2. For one full release the hook must accept **both** filenames — `[[ -f "$OLD" || -f "$NEW" ]]` —
   so there is no window in which the hook silently goes no-op.
3. Bump the wire marker to `restart-v2` and parse **both** `restart-v1` and `restart-v2`
   markers for one release, so in-flight and historical sessions still recover.
4. Only after that release may the old forms be dropped.

Rename the marker **without** step 2 and the failure is invisible: the hook exits 0 and looks
like success.

---

### Tier 2-B — occurrences created after this plan was first written

These did not exist when the original 37-line partition was measured. They were introduced by a
sibling lane's new document and are **not** this lane's to edit (`docs/reference/` is outside
its file-ownership boundary). They are recorded here so the residue still reconciles to zero
unaccounted matches.

| Location | Line | Reason retained |
|---|---|---|
| `docs/reference/launch-plan.md` | `BI-C` evidence row quoting the README clone command | Quoted **evidence text**, bound to the baseline ref `4c33f2f5`. Rewriting it would falsify a recorded observation. |
| `docs/reference/launch-plan.md` | `C-PASS` gate row quoting the same command as a corroborating indicator | Same — quoted evidence, bound to the same ref. |

Both flip naturally whenever the launch-plan's own evidence is re-taken against a later ref;
neither is identity surface.

---

## Occurrence reconciliation

Counts are in **matching lines**. Exactly one line in the tree carries the old name **twice**
(the `README.md` source link, whose label and href each contain it), so the occurrence count
runs one higher than the line count.

| Tier | Lines | Occurrences | Disposition |
|---|---:|---:|---|
| Tier 1 — cleared | 10 | 10 | done (6 in the first pass, 4 in the second) |
| Tier 1-B — still owed, blocked | 2 | 2 | listed above with blocker + clearing condition |
| Tier 2 — retained, gated on the external rename | 6 | **7** | listed above |
| Tier 2-B — retained, sibling-authored evidence | 2 | 2 | listed above |
| Tier 3 — retained, gated on Lane C | 19 | 19 | listed above |
| **Residual after this pass (measured)** | **29** | **30** | fully enumerated |
| **Tree total** | **39** | **40** | the original 37 + the 2 Tier 2-B lines added since |

10 + 2 + 6 + 2 + 19 = 39 lines, no remainder. **Every** remaining old-name line in the tree
appears in exactly one table above. This document is excluded from the residue count: it cannot
record the sentinel's filename, the dual-accept recipe or the Tier 2 URLs without quoting the
old name.

> **On the "25" figure.** The original target of 25 residual lines was derived from a 37-line
> tree that no longer exists: two further old-name lines have since been added by a sibling
> lane (Tier 2-B). Re-derived against the current 39-line tree the equivalent target is **27**,
> and the measured 29 is exactly 2 above it — the Tier 1-B pair, which is boundary-blocked
> rather than unexplained. No residual line is unaccounted for under either figure.

---

## What remains the user's to execute (outside this working tree)

| # | Step | Owner | Notes |
|---|---|---|---|
| 1 | Rename the GitHub repository to `claude-code-guardrails` | **User** | Not performed and not automated here. The configured remote still names the old repository. |
| 2 | Flip the six Tier 2 URLs | Follow-up, **after** step 1 | Early = 404. Do it promptly (redirect decay). |
| 3 | Land the two remaining Tier 1-B rows | Follow-up | The generator-dependent rows are done. What remains is the `docs/THREAT-MODEL.md` H1, which the sibling lane owning that file must land, followed by one INDEX regeneration to refresh its derived mirror. |
| 4 | Rename the sentinel + wire marker | **Lane C** | Use the dual-accept recipe above. |
| 5 | Build the `claude-guard` CLI | **Lane C** | Gated on Lane A. |
| 6 | Publish / announce / submit anywhere | **User** | Explicitly out of scope; gated on the P1 work landing. |

---

## Verification recipe

| Check | Command | Expected |
|---|---|---|
| Residual old-name lines, excluding this plan | `git grep -n -I -F 'awesome-claude-harness' -- . ':(exclude)docs/reference/rename-execution-plan.md' \| wc -l` | `29` while Tier 1-B is outstanding; `27` once Tier 1-B lands (the original `25` predates the 2 Tier 2-B lines) |
| Per-file residual | `grep -c -F 'awesome-claude-harness' <path> \|\| true` | bare integer on stdout; **exit 1 means zero matches and is success**, exit 2 means the path is unreadable |
| A Tier 2 line survives byte-exact | `grep -c -F -- "$EXACT_TEXT" <path>` | `1`. The `--` separator is **required**: the `NESTED-REPO.md` line begins with `- ` and is otherwise parsed as an option bundle, exiting 2. |
| Hero provenance | `node tools/demo/audit.mjs <trace.json> <hero.svg> --strict` | exit `0` for both pairs |
| Hero artifacts are generator output, not hand edits | regenerate each trace into a scratch path with `tools/demo/gen-svg.mjs` and `cmp` against the committed asset | byte-identical |
| `INDEX.md` is generator output | snapshot it **outside** the scanned tree, re-run the index generator from the repository root, and diff with the `*Last updated:` line filtered from **both** sides | empty diff |
| No outward action occurred | `git remote -v`; `git tag --list`; `git for-each-ref refs/remotes/origin` | remote still names the **old** repository; no tags; the remote-ref set unchanged |

The `INDEX.md` check must be **idempotence**, never byte-identity: the index generator stamps
wall-clock time, so a byte-identical check fails on every run regardless of correctness. If the
git tracked set changes between the snapshot and the re-run — several lanes share this tree —
the check is **indeterminate and should be re-run**, not recorded as a failure.

---

## Rollback

The prose and identity changes are in-place single-line text replacements plus this one new
file. No schema changed, no identifier was renamed, and nothing left the working tree. Three
artifacts, however, **are generated** — both hero SVGs and the root `INDEX.md`. Roll those back
by reverting their *canonical sources* and re-running the generators, never by reverting the
generated bytes alone.

1. Revert the changed prose lines (or the commit) — the old name and framing return verbatim.
2. Revert `meta.session_title` in both trace JSONs, then re-run
   `node tools/demo/gen-svg.mjs <trace> <svg>` for each pair. A trace and its SVG must move
   together, or the strict provenance audit hard-fails on the mismatch.
3. Regenerate the root `INDEX.md` from the then-current tree rather than restoring an older
   copy — it is a whole-file generated artifact, and a stale copy would silently drop sibling
   lanes' entries that have since been integrated.
4. Delete this document.
5. Nothing external needs undoing: the GitHub repository was never renamed, no tag was created
   and nothing was published, so there is no external state to reconcile.

Rollback is strictly local and carries no *external* coordination cost, but it is **not** a
pure text revert: steps 2 and 3 must re-run the generators.

---

## Note — where the non-guardrail half lands in the new framing

Roughly half the shipped surface is release orchestration rather than guardrail enforcement,
and the chosen framing covers both halves deliberately: in **safety & release harness**,
*safety* is the hook kernel and git protection chain, and *release* is the evidence-gated
`/spec → /dev → /close → /commit → /push` pipeline that stops unverified changes from shipping.
Only the repository **name** leans safety-first, and deliberately so — it is optimized for
searchability and for the strongest, best-evidenced subsystem. Nothing is orphaned by the
reframe, and no capability was deleted or hidden by it.
