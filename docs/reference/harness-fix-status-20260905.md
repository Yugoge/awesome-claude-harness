# Harness fix status — R1..R20 of `spec-20260904-harness-fixes.md`

**Date**: 2026-09-05
**Subject**: the twenty harness defects catalogued as R1 through R20 in
`docs/dev/specs/spec-20260904-harness-fixes.md`, and which of them actually landed.
**Provenance**: measurements taken first-hand by four parallel audits on 2026-09-05.
Figures marked **[re-verified]** were additionally re-measured while writing this
document; everything else is carried faithfully from those audits.
**A `[re-verified]` mark must carry the instant it was measured.** A mark without an instant
is not checkable, and this document has already carried one that had not been earned. The
rule is honoured here in two forms, and there is no third: a mark that **names an instant**
was measured at that instant; a **bare** `**[re-verified]**` means *re-measured during the
correction round below, 2026-09-05T12:36Z–12:41Z, and reproducing exactly*. Every one of the
twenty marks in this document is one or the other — none is undated.

**Correction round — measured 2026-09-05T12:36Z–12:41Z.** All **twenty** `[re-verified]`
sites in this document were re-measured first-hand in that window, root
`/dev/shm/dev-workspace/dot-claude` (restart-state at `/root/.claude/restart-state/`), each
with its own positive control. **Seventeen reproduced exactly.** Three did not, and each is
corrected **in place and labelled as a correction**, not silently swapped:

- **§3.3's restart-state table** published figures that were **never re-measured** despite
  wearing the tag. Retracted and replaced there; see *Retraction* in §3.3.
- **§1's topology figures** were exactly true when written and were falsified ten minutes
  later by a concurrent commit. They were the one class of volatile figure this document
  left unstamped. Now re-measured and stamped.
- **§2.3's collision table** annotated three of five rows for a property all five carry.
  Corrected to 5 of 5.

One supporting figure in §3.4 (raw-backslash source lines) had drifted by one and is
restated with its instant. The seventeen that reproduced are listed in *Measurement
discipline* → *Correction-round audit*.
**Why this file lives here**: `docs/dev/` is ignored at `.gitignore:142`, so the
cycle-artifact tree does not survive a clone. `docs/reference/` is the declared durable
delivery path, so the authoritative status answer is recorded here.
**Scope note**: this document covers **R1–R20** only. The spec has since grown further
items, by concurrent sessions and by this cycle, and **none of them were assessed here**:
**R21** (another session — the aggregate writer's stale-canonical fail-closed loop),
**R22** (another session — `push.sh` reporting a no-op push as success), **R28** and
**R29** (another session — aggregator baseline-snapshot equality and shard-mismatch
behaviour), and **R30–R35**, this cycle's six, found on 2026-09-05 and recorded, unfixed,
in the spec's "2026-09-05 追加" section — **and any item added to the spec after
2026-09-05T11:43Z**, which is the instant this enumeration was resolved. That cutoff is not
hypothetical: `### R23.` (a `permissions.deny` symlink-alias item, another session) is
present at spec line 104 as of **2026-09-05T12:40Z** and is **not** named above, because it
postdates this enumeration. The spec was 251 lines at 11:43Z and is 259 lines with mtime
`11:57:50Z` — 9m51s after **the revision of this document published at `11:47:59Z`**, which
is the revision that wrote this scope note. (That instant, not the file's current mtime, is
the one that dates the note: the correction round rewrote this file at 12:47Z, so its live
mtime no longer marks when the enumeration was made.) The renumbering account below is
unaffected (R23 < R29).

**Numbering note**: this cycle's six were first appended as R22–R27 and were **renumbered
to R30–R35** on 2026-09-05, because a concurrent session had independently numbered its
`push.sh` item R22, producing two `### R22.` headings in one spec. The new numbers sit
above every heading then present (the highest was R29). Every reference to these six in
this document and in `abandoned-cycles-20260905.md` uses the **new** numbers; the other
session's R22 is untouched.

---

## 1. The topology finding, which inverts the question

Three of the four audits reported this independently, and it must be stated before any
per-item status, because it changes what "did it land" means.

> **Correction — the figures first published here were unstamped, and have since been
> falsified.** This section originally read *"The feature branch is already fully merged into
> `origin/master`"*, reporting **0 ahead / 7 behind** and an ancestry test that **passes**,
> under a bold `[re-verified]` mark. Those figures were **exactly true when written** — the
> branch tip was then `71f5dfbc`, and at `71f5dfbc` the count is still `0  7` and the
> ancestry test still exits 0 — but they **carried no measurement instant**, in a document
> that states a volatility rule at §2.2 and applies it to four other classes of figure. That
> omission is the defect: it implied an unstamped figure was durable. Commit `b4b5f13b`
> (`2026-09-05T11:58:14Z`, a concurrent session, parent `71f5dfbc`) landed **10m15s after the
> revision of this document published at 11:47:59Z** — the revision that made the claim — and
> made them false. (That publication instant, not the file's live mtime, is the relevant
> clock; the correction round rewrote this file at 12:47Z.) They are re-measured and stamped
> below, and brought under §2.2's rule.

> **A branch's ahead/behind count and its ancestry verdict are volatile facts, strictly more
> volatile than the worktree blob ids of §2.2: a commit on *either* side moves them.** The
> **durable side is `origin/master`**; the **volatile side is the branch tip**. Every claim
> this document rests on is stated against `origin/master`, which has **not** moved.

**The feature branch is one commit ahead of `origin/master`, and that commit is not merged.**
`fix/dev-fanout-gatekeeper-20260717` is **one commit ahead of and seven behind**
`origin/master`, and the ancestry test **fails**. **[re-verified 2026-09-05T12:37Z]**

```
measured 2026-09-05T12:37Z, root /dev/shm/dev-workspace/dot-claude
branch tip = b4b5f13b   origin/master = fa0aea69

git merge-base --is-ancestor fix/dev-fanout-gatekeeper-20260717 origin/master   -> 1 (NOT ancestor)
git rev-list --left-right --count fix/dev-fanout-gatekeeper-20260717...origin/master
  -> 1   7          (1 ahead, 7 behind)

positive control (same test, commits known to be ancestors):
git merge-base --is-ancestor 71f5dfbc origin/master   -> 0
git merge-base --is-ancestor dce9fff9 origin/master   -> 0
```

The single commit ahead is **`b4b5f13b`** — *"docs(repo): correct README count claims and
archive push-gate KEEP decision"*, committed `2026-09-05T11:58:14Z` by a concurrent session.
Its parent is `71f5dfbc`, and at that parent the count is `0  7`.

Commit `dce9fff9` is reachable from `origin/master`, as is `71f5dfbc`.
**[re-verified 2026-09-05T12:37Z]** (These are the positive controls above: both exit 0,
which is what shows the ancestry test's exit 1 for the branch is a real negative and not a
broken tool.)

Two consequences follow, and both should be stated plainly:

1. **The unmerged feature-branch backlog is one commit, and it is a documentation fix.**
   The real distinction remains not *merged vs unmerged* but **committed vs uncommitted**.
   Every defect below that is still unfixed is still present **on `origin/master`** — which
   still means **a fresh clone receives the defective code**. `b4b5f13b` is the sole
   exception and it fixes R9's README half only; nothing else is waiting in a side branch to
   rescue anything. **The conclusion this section exists to establish is therefore unchanged
   by the correction**; only the categorical *"there is no unmerged backlog"* is withdrawn,
   and it is replaced by *"the unmerged backlog is exactly `b4b5f13b`"*.

2. **`/root/.claude` is a symlink to this checkout.** **[re-verified]**
   ```
   /root/.claude -> /dev/shm/dev-workspace/dot-claude
   ```
   The running harness therefore executes **working-tree files**, not committed ones. An
   uncommitted fix is simultaneously **live on this machine** and **absent from master**.
   This is why "it works here" and "a clone gets it" are, for this repository, entirely
   independent claims.

---

## 2. Per-item status, as measured

### 2.1 Landed and merged — exactly one, and only in part

**R9** — `verify-claims.sh` binding surface for ARCHITECTURE/README numeric claims.

The **ARCHITECTURE.md count corrections landed** as commit `71f5dfbc`
(`docs(architecture): correct three stale count claims in the §1 inventory table`), an
ancestor of `origin/master`, touching `ARCHITECTURE.md` alone with 7 insertions and 7
deletions across **seven sites**. **[re-verified]** It corrected:

- nineteen -> twenty,
- ninety-three -> ninety-four,
- the permissions triple -> one hundred sixty-five / ninety-six / zero.

Ground truth was independently re-measured and now matches.

R9's **other two halves did not land**:

- **The three README locations still read the stale count at `origin/master`.**
  **[re-verified 2026-09-05T12:37Z]** All three sites carry the false "19":
  ```
  origin/master:README.md:131:    U([Human]) --> CMD[Slash commands<br/>19 entry points]
  origin/master:README.md:326:## The command surface: 19 slash commands
  origin/master:README.md:529:├── commands/          # 19 slash-command workflows (…)
  ```

  > **Correction — "only as working-tree state" was true when written and is now false.**
  > This bullet originally said the corrected value existed *"only as working-tree state"*.
  > The same commit that falsified §1, **`b4b5f13b`** (`2026-09-05T11:58:14Z`), committed it.
  > The clause is restated in its **durable** form below — *not on `origin/master`* — which is
  > the form the argument actually needs and the form a later commit on the branch cannot
  > falsify.

  The corrected value is **not on `origin/master`**. It is committed on the branch at
  `b4b5f13b`, which is **not an ancestor of `origin/master`** (§1), and it is also in the
  worktree. Measured 2026-09-05T12:37Z: `b4b5f13b:README.md` reads **20** at lines 131, 326
  and 530 (the third site moved from 529 to 530 when the block was restructured); the
  worktree agrees. Ground truth is **20** — a direct ignore-blind listing of `commands/*.md`
  excluding `INDEX.md`/`README.md` yields 20, against a control of 22 for the same listing
  including them. R9's README half is therefore **committed but unmerged**, a state the
  four-row taxonomy in §4 does not have a row for; §4 records it in prose instead.

- **The verify-claims gate was never widened.** **[re-verified]** `scripts/verify-claims.sh`
  still binds only three families: the recomputed **wired hook entry count**, the
  **lifecycle event count** (step 2, `WIRED_PATS` / `EVENT_PATS` at
  `scripts/verify-claims.sh:127-142`), and a **hook-set set-equality** against the public
  template (step 5). It binds none of the count classes it misses. For one of them the
  gate does not even possess the vocabulary:

  | term in `scripts/verify-claims.sh` | occurrences |
  |---|---|
  | `agent` / `subagent` | **0** |
  | `slash` | 1 (only in a comment declaring it out of scope) |
  | `permission` | 1 (same comment) |
  | `hook` | 53 |
  | `wired` | 34 |

  The subagent-count class is thus not merely unchecked but **unnameable** by the gate.
  The single mention of `slash` and of `permission` is the comment at
  `scripts/verify-claims.sh:77` that explicitly excludes them from coercion.

### 2.2 Uncommitted only — three

**R1** — gitignore-preflight hook vs workflow artifact policy.

The fix **exists and works**. An A/B against the committed hook shows the **committed**
hook blocks a real `/close` Step 1 dispatch with **exit 2**, while the **working-tree**
hook **passes** it, and the protective **negative control still blocks in both** — the
guard was not weakened. But:

- The fixed blob is **not on any branch**. **[re-verified]**

  > **A worktree blob id is a volatile fact, not a durable one.** The identifiers below are
  > snapshots of a file that concurrent sessions keep editing; each is stamped with the
  > instant it was measured. The *committed* identifier is the durable half, and it is the
  > half the conclusion rests on.

  | | blob for `hooks/pretool-gitignore-preflight.py` | measured |
  |---|---|---|
  | working tree (**volatile**) | `34acce9b9905d36ba7207fdf3161869aa2338b44` | 2026-09-05T11:43Z |
  | working tree, at the original audit (**superseded**) | `e7a8f0d57c7013de760b61e45e2c6c4b15864d40` | 2026-09-05, earlier that day |
  | `HEAD` (durable) | `9088f5ed37a58aba8ef08e8a025766831549b3a8` | 2026-09-05T11:43Z |
  | `origin/master` (durable) | `9088f5ed37a58aba8ef08e8a025766831549b3a8` | 2026-09-05T11:43Z |

  The worktree blob **moved between the original audit and this re-verification**
  (`e7a8f0d5…` -> `34acce9b…`), which is exactly what a volatile identifier does; the
  `e7a8f0d5…` object still exists in the object database but is no longer the file's
  content. **The conclusion is unchanged**, because it depends only on the committed side:
  `HEAD` and `origin/master` still carry `9088f5ed…`, i.e. still the *unfixed* blob. The
  fixed content — under whichever worktree id it currently has — appears in exactly one
  ref, and it is an **automated checkpoint ref**:
  `refs/checkpoints/fix-dev-fanout-gatekeeper-20260717` (re-confirmed for `34acce9b…` at
  2026-09-05T11:43Z). Per the checkpoint mechanism, those refs never advance a branch HEAD.
- Its **regression suite is untracked**: `hooks/tests/test_gitignore_preflight_close_contract.py`
  returns `did not match any file(s) known to git`. **[re-verified]**
- The item's own acceptance clause **(c)** — fanout-cycle close running end-to-end
  through Step 1 — is **unmet**.

**R7** — `changelog-analyst` route documentation for `--untracked-modified-report`.

The route documentation is **substantive and consistent with the validator's admission
constants** (`agents/changelog-analyst.md:374,584,591`). But it has **zero occurrences at
both `HEAD` and `origin/master`**. **[re-verified]**

```
git grep -c -- '--untracked-modified-report' HEAD          -- agents/changelog-analyst.md  -> (no output: ZERO)
git grep -c -- '--untracked-modified-report' origin/master -- agents/changelog-analyst.md  -> (no output: ZERO)
grep -c  -- '--untracked-modified-report'                     agents/changelog-analyst.md  -> 3   (worktree)
```

Positive control: `git cat-file -e HEAD:agents/changelog-analyst.md` succeeds, so the file
exists at that ref and the zero is a real absence, not a missing path. The flag itself is
committed in `scripts/stage-owned-hunks.py` (5 occurrences) and
`tests/test_checkpoint_provenance.py` (1) — it is the **analyst's route documentation**,
which is the thing R7 asks for, that is absent. The item's e2e clause is **unmet**.

**R8** — `untracked_modified_adoption` constituent count disagreeing across documents.

The two documents **now agree — both say five conjuncts**. **[re-verified]**
`agents/qa.md:475` reads "only if all five"; `agents/changelog-analyst.md:365,372,576`
read "all five" / "meeting all five" / "five conjuncts". But the whole passage is
**uncommitted** — the same search at `HEAD` over both files returns nothing — and the
**required consistency lint or pinning test does not exist**.

### 2.3 Partial — two beyond R9

**R5** — bare `dev-report` and `do-report` colliding on one task-id.

- One **untracked filename rename** for a single case.
- **Zero codification** anywhere in code or contract. **[re-verified]** A search for
  `lane-internal` across `agents`, `commands`, `hooks`, `scripts`, `docs/reference` and
  `tests` returns **0 files** — **measured 2026-09-05T11:43Z, pre-publication**. See
  *Self-falsifying counts* under Measurement discipline: this document is published **into**
  `docs/reference/`, one of the scanned directories, and its own prose contains the string
  `lane-internal`. From publication onward the same search returns **1 file, and that file is
  this document**. The reported 0 is the pre-publication figure and is the one that bears on
  R5; a re-runner should expect 1 and confirm the sole hit is this file.
- The **five July collision cases are still live on disk**.
  **[re-verified 2026-09-05T12:37Z]**

  > **Correction — the annotation was 3-of-5 where the truth is 5-of-5.** An earlier
  > revision of this table marked only three of the five rows as carrying both a
  > `dev-report-<id>.json` and a `do-report-<id>.json`. **All five carry both.** The
  > artifact counts in the right-hand column were and remain correct; only the
  > parenthetical annotation was wrong. It understated the harness's own fault, and it
  > would have led a reader using the table to pick ids to inspect to record a blast
  > radius of three where the evidence supports five.

  **All five** ids carry artifacts under `docs/dev/`, and **all five exhibit the collision**:
  each carries **both** `dev-report-<id>.json` **and** `do-report-<id>.json` — **5 of 5**,
  measured 2026-09-05T12:37Z by a direct `find` walk over `docs/dev` (**ignore-blind**:
  `docs/dev/` is gitignored at `.gitignore:142`, so this shell's default matcher would not
  see it). Positive control, same idiom and root: an absent id `29990101-000000` returns
  **0**, a present id `20260905-072023` returns **5**.

  | task id | artifacts on disk | `dev-report` **and** `do-report` both present |
  |---|---|---|
  | 20260713-101753 | 8 | yes |
  | 20260713-113357 | 4 | yes |
  | 20260714-183239 | 7 | yes |
  | 20260714-232546 | 6 | yes |
  | 20260715-134718 | 32 | yes |

- **No regression test.**

**R17** — paseo `list_agents` omission and `attentionReason` ambiguity.

The **ambiguity half was measured still present**: a live listing of **128 rows** shows
the `attentionReason` field takes only **two values**, and **no field distinguishes clean
completion from quota truncation** — determining which requires reading the text of the
last activity entry. A smaller live listing taken while writing this document (6 rows,
720-hour window) independently reproduces the same schema property: `attentionReason` is
either `"finished"` or `null`, and the record carries no completion-kind discriminator.
**[re-verified, schema property only]**

The **omission half is not verifiable from here** — establishing that an active session
was absent from a `sinceHours` window requires the session-side ground truth that this
vantage point does not have.

### 2.4 Not done — the remaining fourteen

**R2, R3, R4, R6, R10, R11, R12, R13, R14, R15, R16, R18, R19, R20** — fourteen
identifiers, counted from this list. Of them, R3 and R10 are additionally **corrected**
below because the spec's own text about them is wrong, and R18 is additionally
**confirmed and deepened** below (its spec citation is accurate; the mechanism is worse
than the spec states).

---

## 3. Five findings about the spec's own text — four corrections and one confirmation

### 3.1 Two of the spec's own prior-work claims are unsupported

The spec twice tells a reader not to redo work, on the strength of a cycle that does not
support the claim.

- `spec-20260904-harness-fixes.md:21` states that cycle **`dev-20260904-161820`** was
  already fixing **R2** ("已在做,验收其结果即可,勿重复开发"). That cycle's **three
  lanes touched the `changelog-analyst` and `qa` agent definitions and never touched
  `commands/commit.md`** — which is the file R2 is about (`commit.md:65-73`, the
  `CLOSE: YES` precondition). It left **zero cycle artifacts**.

- `spec-20260904-harness-fixes.md:47` states that cycle **`dev-20260904-092550`** already
  repaired **R7** ("周期已修,验收其结果勿重复"). A history search for that identifier
  returns **zero commits** **[re-verified]**, and the only trace is **eighteen one-line
  registry stubs in an ignored directory**.

  ```
  git log --all --oneline --grep='20260904-092550'  -> 0
  git log --all --oneline --grep='dev-20260904-161820' -> 0
  positive control: git log --all --oneline --grep='20260829-104922' -> 2
  ```

  The positive control confirms the search idiom finds cycle identifiers that are really
  in the history, so both zeros are real absences.

**Consequence**: both "do not repeat this work" notes should be treated as retracted.
R2 and R7 have no landed prior work to accept.

### 3.2 R3's claimed workaround does not discharge it

`spec-20260904-harness-fixes.md:25` says the third cycle worked around the absorbing
`qa_pass` state by moving the close dimension forward into QA, "已验证可行".

The commit it points at, **`dce9fff9`, is genuinely merged** — but it **changes a
contract-runtime module and a projection test, not the lifecycle edge set**. **[re-verified]**

```
dce9fff9 chore(hooks): land corrected schema-projection unit closing gate fail-open
 hooks/lib/contract_runtime.py                  | 268 +++++-
 hooks/tests/test_report_projection_contract.py | 900 +++++++++++++++++++
 2 files changed, 1155 insertions(+), 13 deletions(-)
```

And a search for **any contractualisation of the close-forward approach returns zero**
across the agent, command, hook, script and reference trees. **[re-verified]**

All five figures below were **measured 2026-09-05T11:43Z, pre-publication**, and all five
are self-falsifying on publication — see *Self-falsifying counts* under Measurement
discipline. This document is published **into** `docs/reference/`, one of the scanned
directories, and its own prose contains every term in the table, including the control.

| searched term | files matched in `agents`, `commands`, `hooks`, `scripts`, `docs/reference` | after this file is published |
|---|---|---|
| `close_rejected` | 0 | 1 — this document |
| `close-forward` | 0 | 1 — this document |
| `close_forward` | 0 | 1 — this document |
| `qa_pass ->` / `qa_pass →` | 0 | 1 — this document |
| **positive control**: `qa_pass` | **5** | **6** — the five below plus this document |

The control's five are `agents/dev.md`, `commands/close.md`, `scripts/close-scoring-decide.py`,
`scripts/score-update.sh` and `scripts/__pycache__/close-scoring-decide.cpython-312.pyc`;
the control is affected by publication in exactly the same way as the zeros, and is
annotated the same way rather than being presented as stable. In every one of the five
rows the **sole** new hit is this document's own prose, so no row's *substance* moves:
the trees still contain no `close_rejected` edge and no contractualised close-forward
scheme. The positive control shows the trees really do discuss `qa_pass`, so the zeros are
absences of the *edge* and of the *contractualised workaround*, not of the search.
R3's acceptance requires one of "add a `qa_pass -> close_rejected -> retry_dispatched`
class of edge" **or** "fix the close-forward scheme into contract". **Neither exists.**

### 3.3 R18's line citation is accurate; the defect is real and worse than described

R18 (`spec-20260904-harness-fixes.md`, heading `### R18.` — line 100 as resolved
2026-09-05T11:43Z) cites `subagent_restart.py:435-438` and reports that a subagent
re-interrupted after resume is **permanently pinned in `dispatched`**.

**The spec's line citation is correct.** Read first-hand in the working-tree copy of
`hooks/lib/subagent_restart.py` on 2026-09-05: the `if status == "dispatched":`
conditional opens at line **435** and its block ends at line **438**. Line **439** is the
`elif status != "response_observed":` arm and belongs to a different branch. The spec's
range `435-438` is exactly the conditional and its block, quoted here with the line
numbers it was read at:

```python
435:            if status == "dispatched":
436:                dispatched_line = previous.get("interruption_line_at_dispatch")
437:                if not isinstance(dispatched_line, int) or candidate["interruption_line"] > dispatched_line:
438:                    status = "pending"
439:            elif status != "response_observed":   # <- different branch; not part of 435-438
```

**Correction to an earlier revision of this document.** A previous revision of this section
asserted that the spec's range was wrong and substituted `437-439`. That assertion was
**false** — and self-contradicting, since it printed a four-line block under a three-line
label. It is **withdrawn in full**: the spec's R18 line citation needs no correction, and
this section no longer challenges it.

**The substantive finding is unaffected and stands.** The re-arm transition is **present**
in the code — it arrived with commit `336fe96a` ("/restart subagent lifecycle recovery", an
ancestor of `origin/master`), so it predates the observation **[re-verified]** — and that is
precisely what makes the defect worse than a missing edge would be.

It is **unreachable on the resume path**, because **resume traffic does not advance
the counter the re-arm predicate compares**. Re-arming requires
`interruption_line > interruption_line_at_dispatch`; a resume does not increment
`interruption_line`, so the strict inequality never becomes true.

> ### Retraction — the figures previously published here were wrong, and the `[re-verified]`
> ### tag on them had not been earned
>
> An earlier revision of this table reported **70** candidates pinned in `dispatched`, 70 of
> them with equal counters, and a status histogram of `dispatched` **70** /
> `response_observed` **40** / `quota_interrupted` **11**, under a bold `[re-verified]` mark.
> **Every one of those five numbers is wrong**, and the mark was false.
>
> **The numbers were carried forward from the earlier source audits and were never
> re-measured**, which is precisely what this document's header says the `[re-verified]` mark
> rules out ("additionally re-measured while writing this document"). This is not a figure
> that went stale; it is a figure that was never taken. Three independent things establish
> that:
>
> 1. **The histogram was arithmetically unreachable.** Total `quota_interrupted` across
>    **all sixteen** state files is **5**. The retracted table reported **11**. A component
>    exceeding the whole quantity available cannot arise from any subset of the data, so no
>    scoping choice could have produced it.
> 2. **The state files had stopped moving before the claimed instant.** The latest mtime of
>    any state file — and of the directory itself, which forecloses any add or delete — is
>    **2026-09-05T11:37:45Z**. This document's own stamped measurement instant is
>    **11:43Z**, 5m15s later, and the revision carrying the retracted figures was published
>    at 11:47:59Z. A measurement taken at 11:43Z
>    would necessarily have returned the figures below.
> 3. **Two independent parties measured the same different values.** The close gate measured
>    88 / 88 / 0 / 0 and 88 / 35 / 5; this correction round reproduced that independently,
>    from the state files rather than from the gate's report.
>
> **The substantive conclusion of this section is unaffected, and it was re-checked rather
> than assumed.** The argument needs only the **equality invariant** — that *no* dispatched
> candidate has `interruption_line > interruption_line_at_dispatch` and none has that field
> missing — and the invariant holds on the true numbers, over a **larger** population than
> was claimed: 88 of 88 rather than 70 of 70. **The durable claim is the invariant; the
> absolute counts are volatile** and are stamped accordingly below.

Empirically, over the 16 live state files under `/root/.claude/restart-state/` — measured
**2026-09-05T12:36Z**, ignore-blind (direct `glob` over `*.json` at depth 1, no shell matcher
involved), 128 candidates in total: **[re-verified 2026-09-05T12:36Z]**

| | count |
|---|---|
| candidates pinned in `dispatched` | **88** |
| of those, `interruption_line == interruption_line_at_dispatch` (predicate **false**) | **88** |
| `interruption_line > interruption_line_at_dispatch` (would re-arm) | **0** |
| `interruption_line_at_dispatch` missing / non-int (would re-arm) | **0** |

Status histogram across all **128** candidates: `dispatched` **88**, `response_observed`
**35**, `quota_interrupted` **5**. The four rows above sum to the 88 dispatched, and
88 + 35 + 5 = 128, so the table and the histogram reconcile to the same population.

Scope, stated so the figures are re-checkable: the sixteen files are the `*.json` files at
the **top level** of `/root/.claude/restart-state/`. The ten files under its `grants/`
subdirectory are **excluded** and carry **zero** candidates between them, so their exclusion
does not move any number. Positive control: a status token that cannot exist returns **0**
over the same walk that returns **88** for `dispatched`.

**These counts are volatile** — any `/restart` activity rewrites them, and six of the sixteen
files were rewritten on the morning of 2026-09-05. What is **not** volatile is the invariant:
the re-arm predicate requires `interruption_line > interruption_line_at_dispatch` **or** that
field to be absent, and **neither holds for any dispatched candidate**. Read first-hand at
`hooks/lib/subagent_restart.py:435-438`, that disjunction is the whole of the re-arm
condition, so the predicate is **false for every one of the eighty-eight** — and the
documented procedure instructs **waiting indefinitely**. This is worse than "a missing
transition": a missing transition is visible on inspection, whereas a present-but-unreachable
one reads as correct in review.

### 3.4 Both mandated helper scripts still return misleading results

Both were **run first-hand** and both still fail as R10 describes. **[re-verified]**

**`scripts/detect-hardcoded-paths.sh`** — exits **5** with an **empty stdout (0 bytes)**
and a **bare parser error naming no file**:

```
EXIT=5
stdout bytes: 0
stderr: jq: parse error: Invalid numeric literal at line 534, column 202
```

The "line 534" is a line of the script's **own intermediate stream**, not of any file the
operator can open, so the message is unactionable. Root cause: the script builds JSON by
**shell string interpolation** and pipes it to `jq -s` —
`scripts/detect-hardcoded-paths.sh:20-27` constructs
`{"file": "$file", …, "hardcoded_path": "$path", …}` with `$path` inserted raw. Any
matched path containing a backslash yields invalid JSON. The audit root-caused this to
**raw backslashes in eleven of its own intermediate lines**; a bounded re-check confirms
the ingredient is abundantly present — **30** matched source lines under `scripts/` and
`hooks/` alone contain a raw backslash, **measured 2026-09-05T12:40Z**, ignore-blind, using
the detector's own pattern set, against a control of **765** matched lines before the
backslash filter and **0** for an impossible pattern over the same roots. *(An earlier
revision reported **29** here without an instant; this is a working-tree count and it drifts.
The figure is illustrative — the failure above reproduces regardless of its exact value.)*
The failure is fail-**open** in effect: a caller reading only stdout sees nothing and may
conclude "no hardcoded paths".

**`scripts/detect-dead-functions.sh`** — returns a **clean empty result** (`exit 0`,
`"findings": []`, `"severity": "none"`) while being **structurally unable to open the
directory under audit**:

```json
{ "detector": "dead-functions", "project_root": ".", "scan_dir": "./scripts",
  "findings": [], "summary": { "total": 0, "severity": "none" } }
```

`scripts/detect-dead-functions.sh:13-14` hardcodes `SCRIPTS_DIR="${PROJECT_ROOT}/scripts"`
under the comment "Only scan Python files in scripts/ directory", and line 24 iterates
`"$SCRIPTS_DIR"/*.py`. **`hooks/` is never opened**, and no parameter can redirect it —
the second and third positional parameters are bound to `COMMANDS_DIR` and `AGENTS_DIR`
(lines 9 and 11), not to the scan directory. The audit demonstrated the consequence with a
controlled experiment: **the identical dead function is found when placed in one directory
and missed when placed in the other.** A green result from this detector carries no
information about `hooks/`.

Neither script satisfies R10's acceptance, which requires the first to be fail-closed with
readable error text and the second to accept a directory argument or scan the whole
repository, each with a known-positive control.

### 3.5 No commit references the spec

The spec's own general acceptance requires each fix to record its correspondence to the
spec **in the commit message**. The clause is the single unnumbered paragraph that follows
the last `### R…` heading of the original catalogue and opens `每条 R 的通用验收:`; it ends
`…与本 spec 的对应关系写入提交信息。` **Cite it by that opening string, not by line
number** — the spec is being appended to by concurrent sessions and its line numbers move
under it (it was 214 lines recently; **251 lines when resolved at 2026-09-05T11:43Z**; 254
lines after the R30–R35 renumbering note was added later that day; and it will be longer
again). The clause sat at **line 116** at both of those measurements — the additions landed
below it — but that stability is incidental, not something a reader should rely on. An
earlier revision of this document cited `:105`; at 2026-09-05T11:43Z line 105 held an
unrelated line inside another session's `push.sh` item, so the citation was wrong as of
that measurement. Whether `:105` was ever correct earlier in the file's history is **not
established here** — the file is untracked and ignored, so no prior revision is available
to check against, which is itself the reason to cite by anchor text.

A history search for the spec's name returns **zero commits**. **[re-verified]**

```
git log --all --oneline --grep='spec-20260904-harness-fixes'  -> 0
positive control: git log --all --oneline --grep='spec-'      -> 84
```

The positive control shows 84 commits do name some spec, so the idiom works and the zero
is a real absence. **No fix in this catalogue satisfies the general acceptance criterion**,
including the one that landed.

---

## 4. Bottom line

Of the **twenty** catalogued items:

| outcome | count | items |
|---|---:|---|
| landed and merged, **in part only** | 1 | R9 (ARCHITECTURE half only; see the note below on its README half) |
| exist **only as uncommitted working-tree state** | 3 | R1, R7, R8 |
| **partial** | 3 | R5, R9, R17 |
| **untouched** | 14 | R2, R3, R4, R6, R10, R11, R12, R13, R14, R15, R16, R18, R19, R20 |

**A fifth state the four rows cannot express, recorded in prose.** Since this document was
first written, R9's **README half** has moved from *uncommitted working-tree only* to
**committed but unmerged**: commit `b4b5f13b` (`2026-09-05T11:58:14Z`, concurrent session)
carries it, and `b4b5f13b` is **not** an ancestor of `origin/master` (§1, measured
2026-09-05T12:37Z). It is therefore neither "merged" nor "uncommitted", and no row above
fits it. **R9's gate-widening half remains unlanded in every sense.** The three rows'
memberships are otherwise unchanged and were re-measured at 12:37Z–12:39Z: R1, R7 and R8 are
still absent from `HEAD` as well as from `origin/master`.

**How this table reconciles to twenty.** Every count above is the length of the item list
beside it: 1 + 3 + 3 + 14 = **21 row entries**. **R9 is deliberately listed in two rows** —
once under *landed and merged, in part only* (its ARCHITECTURE half, the sole merged result
in the catalogue) and once under *partial* (its two unlanded halves) — so it is counted
twice and no other item is. Subtracting that single duplicate gives 21 − 1 = **20 distinct
items**, which matches the twenty catalogued as R1–R20. Every one of R1…R20 appears in
exactly one row except R9, which appears in exactly two.

**The feature branch carries exactly one unmerged commit — a documentation fix — so there is
effectively no backlog to land, and every one of the unfixed defects is still what a fresh
clone gets.** (Measured 2026-09-05T12:37Z: 1 ahead / 7 behind, ancestry test exit 1; the one
commit ahead is `b4b5f13b`, R9's README half. `origin/master` has not moved from `fa0aea69`.
An earlier revision of this document said the branch was *fully merged* with *no unmerged
backlog*; that was true at authorship and is corrected in §1.) The three uncommitted fixes
are live on this machine only, via the `/root/.claude` symlink, and would vanish from any
other checkout. And because no commit names the spec, none of this work is discoverable from
the history by the route the spec itself mandates.

---

## Measurement discipline

Every zero reported above is paired with a positive control, because a tool reporting zero
results is not on its own evidence of absence. Search root was `/dev/shm/dev-workspace/dot-claude`
throughout, stated explicitly at each measurement.

The shell's default `grep` in this environment is **not** the system binary — it is a shell
function wrapping `ugrep --ignore-files`, which applies `.gitignore` rules. Whole-tree scans
above therefore used either `git grep` against an explicit ref (ignore rules do not apply to
tracked content at a ref) or `/bin/grep` directly. Where an ignored tree such as `docs/dev/`
had to be scanned, `/bin/grep` was used and is named as such. Re-confirmed
2026-09-05T12:40Z: `type grep` still reports a shell function, not a binary.

### Correction-round audit — measured 2026-09-05T12:36Z–12:41Z

The document carries the mark at **twenty** sites. The countable form is a bold marker that
is **not** wrapped in backticks; there are **twenty-one** of those, and the header's own
definition of the mark is one of them, leaving twenty sites. *(Two exclusions matter, both
introduced by this correction round, which necessarily discusses the mark by name: bare
occurrences of the string `re-verified` in prose are not sites, and a bold marker enclosed
in backticks is a quoted reference, not a tag. Counting either way inflates the figure.
Measured 2026-09-05T12:47Z on the repaired file: **21** unquoted bold markers and **1**
quoted one, at line 12 of the header.)* All twenty were re-measured first-hand in that window, each with its own positive
control. **Seventeen reproduced exactly; three did not and are corrected in place**, each
under an explicit correction or retraction notice rather than a silent substitution.

| § | tagged claim | outcome |
|---|---|---|
| §1 | branch 0 ahead / 7 behind, ancestry passes | **CORRECTED** — 1 ahead / 7 behind, ancestry exit 1 |
| §1 | `dce9fff9` and `71f5dfbc` reachable from `origin/master` | reproduces (exit 0 both) |
| §1 | `/root/.claude` is a symlink to this checkout | reproduces |
| §2.1 | `71f5dfbc` touches `ARCHITECTURE.md` alone, 7 ins / 7 del, seven sites | reproduces exactly |
| §2.1 | three `origin/master:README.md` sites carry "19" | reproduces exactly (the adjoining *"only as working-tree state"* clause is separately corrected) |
| §2.1 | `verify-claims.sh` term table 0 / 0 / 1 / 1 / 53 / 34 | reproduces exactly; line 77 is the exclusion comment, `WIRED_PATS` at 127 and `EVENT_PATS` at 137 |
| §2.2 | R1 blob table + checkpoint ref | reproduces exactly — worktree and checkpoint `34acce9b…`, `HEAD` and `origin/master` `9088f5ed…`, superseded `e7a8f0d5…` still a blob in the ODB |
| §2.2 | R1 regression suite untracked | reproduces (control: a genuinely tracked sibling resolves) |
| §2.2 | `--untracked-modified-report` 0 / 0 / 3, and 5 + 1 committed elsewhere | reproduces exactly |
| §2.2 | R8 "five conjuncts" agree in the worktree, absent at `HEAD` | reproduces exactly (`qa.md:475`, `changelog-analyst.md:365,372,576`) |
| §2.3 | `lane-internal` = 0 pre-publication | behaves exactly as annotated — now **1**, sole hit this document |
| §2.3 | five July collision cases live; counts 8 / 4 / 7 / 6 / 32 | counts reproduce exactly; **the per-row annotation is CORRECTED** to 5 of 5 |
| §2.3 | R17 `attentionReason` schema property | reproduces — a live 6-row / 720h listing gives exactly two values (`finished`, `null`) and no completion-kind discriminator |
| §3.1 | `dev-20260904-092550` and `dev-20260904-161820` → 0 commits, control 2 | reproduces exactly |
| §3.2 | `dce9fff9` = +268 / +900, 1155 ins / 13 del, 2 files | reproduces exactly |
| §3.2 | close-forward table 0 / 0 / 0 / 0, control 5 | behaves exactly as annotated — now 1 / 1 / 1 / 1, control **6** |
| §3.3 | `336fe96a` introduced the re-arm transition and is an ancestor of `origin/master` | reproduces (exit 0) |
| §3.3 | restart-state 70 / 70 / 0 / 0, histogram 70 / 40 / 11 | **RETRACTED** — never measured; true figures 88 / 88 / 0 / 0 and 88 / 35 / 5 across 128 |
| §3.4 | both helper scripts still fail as R10 describes | reproduces exactly — `detect-hardcoded-paths.sh` exit **5**, **0** stdout bytes, the identical `jq: parse error: Invalid numeric literal at line 534, column 202`; `detect-dead-functions.sh` exit **0** with the quoted empty JSON, and lines 9 / 11 / 13-14 / 24 are as cited |
| §3.5 | spec-name history search → 0 commits, control 84 | reproduces exactly |

Two notes a re-checker should have. First, §3.5 records that the general-acceptance clause
sat at spec **line 116**; at 2026-09-05T12:40Z the anchor text `每条 R 的通用验收:` resolves
to **line 121**. That is the drift §3.5 predicts, which is why it directs citation by anchor
text rather than line number — the anchor still resolves uniquely, and the clause is
unchanged. Second, the counts in this audit that scope over `docs/reference/` are subject to
the *Self-falsifying counts* rule below and are reported post-publication where so marked.

The measured divergence between the two matchers is recorded in the spec, as **R35**
(`docs/dev/specs/spec-20260904-harness-fixes.md`, section "2026-09-05 追加", heading
`### R35.` — "shell 默认文本匹配器是应用 ignore 规则的**包装器**"). It reports, for the
pattern `untracked_modified_provenance` at root `/dev/shm/dev-workspace/dot-claude`, **5**
matching files under the default wrapper against **20** under ignore-blind `/bin/grep`, with
a positive control of 3 / 3 on a tracked directory. **This pair is itself self-falsifying —
see below.** Its root is the repository root, which contains `docs/reference/`, so
publication adds this file to **both** sides (5 → 6 and 20 → 21), leaving the divergence R35
exists to demonstrate exactly intact. Confirmed 2026-09-05T12:40Z: the ignore-blind match set
at that root **contains this document** (membership verified by filtering the result list;
the set had grown to 32 by then, because the tree has moved since R35 was written —
**membership**, not the magnitude, is what the annotation needs). *(An earlier revision of this document
pointed here with "See Document 3, defect 6"; that pointer named a working bundle that was
never published and resolved to nothing. It is replaced by the citation above, which a
reader can follow.)*

### Self-falsifying counts

Several counts in this document scoped their search over `docs/reference/`, or over a root
that contains it, which is the directory this document is **published into**. Publication
therefore necessarily adds one hit — this file's own prose — to every such count. The
affected figures **include**:

1. the `lane-internal` count in §2.3;
2. **all five rows of the §3.2 table, the positive control included**;
3. the **R35 figure quoted above** (`untracked_modified_provenance`, 5 under the default
   wrapper against 20 ignore-blind), whose root is the repository root and which is therefore
   perturbed on **both** sides.

> **Correction — this enumeration previously omitted item 3.** An earlier revision of this
> section wrote *"The affected figures **are** the `lane-internal` count in §2.3 and all five
> rows of the §3.2 table"* — an **exhaustive** form that left out the R35 figure this same
> section quotes a dozen lines above, even though it is scoped over a root containing
> `docs/reference/` and is perturbed by the identical mechanism. A section whose subject is
> *counts that falsify themselves* is the wrong place for an incomplete set. The list is now
> introduced with **"include"** rather than "are", and item 3 is named.

Each is stamped with the instant it was measured, and each is the **pre-publication** figure.

These are annotated rather than re-run, deliberately: re-running them chases a moving
target, since each re-measurement of a count taken over a directory that contains the
report of that count perturbs what it measures. In every affected row of items 1 and 2 the
sole new hit is this document — verified at 2026-09-05T11:43Z and **re-confirmed
2026-09-05T12:39Z**, when `lane-internal` returned exactly **1** file (this one) and the
§3.2 control returned exactly **6** (the five named files plus this one) — so no row's
substantive conclusion changes. Item 3 differs only in that publication adds one to **both**
of its sides, which preserves rather than perturbs the divergence it reports.
A reader re-checking any of them should expect the annotated figure **plus one**, and
should confirm the extra hit is this file before drawing an inference from the difference.
