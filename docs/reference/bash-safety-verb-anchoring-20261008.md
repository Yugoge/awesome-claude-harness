# Unanchored write-verb alternations over-block reads — `pretool-bash-safety.sh`

Date: 2026-10-08
Hook: `hooks/pretool-bash-safety.sh`
Layers repaired: `commit-dispatch-attestation-write` (Layer 1.E3),
`commit-grant-raw-write` (Layer 1.E4)
Regression pin: `hooks/tests/test_commit_artifact_rw_boundary.py`

## Collision class

**Ordinary-English-word collision with an unanchored write-verb blacklist.**

Both layers gate their protected namespace with two OR'd branches. Branch 2 —
retained for write verbs that take their destination as an *argument*, where
there is no redirection operator to bind — carried a 16-token verb
alternation whose tokens were **bare, unanchored substrings**:

```
(tee|cp|mv|ln|touch|sed\s+-i|python|install|\bdd\s|truncate|shred|rsync|awk|perl|node|ruby)
```

Because the tokens were substrings, any ordinary English word *containing* a
verb as an internal or trailing fragment satisfied "a write verb is present"
all by itself. A purely **read-only** command that merely named the protected
namespace was therefore refused — the same auditability failure that branch 1's
target-binding repair had already fixed for the `2>/dev/null` case, arriving
through a different door.

The one token that already carried an anchor was the disk-image verb, written
`\bdd\s` — a word boundary before it and whitespace after. That token was the
in-file precedent for the correct shape; the other 15 lacked it.

## Measured examples

Method: drive the real hook as a subprocess with a `Bash` tool_input payload,
`CLAUDE_STATE_DIR` redirected to a sandbox, and compare **refusal labels**
(never bare exit codes, so a refusal from an unrelated layer cannot be
miscredited). The hook is a PreToolUse gate that inspects a command string and
never executes it, so every probe is inert text and no artifact is created.

Positive control for every permit below: the identical probe against a
throwaway copy of the hook with branch 2's anchors mechanically removed. That
copy **refuses** each probe, so the permits are load-bearing rather than a
method that can never return a hit.

Five collisions, each refused on **both** layers before the repair and
permitted on both after:

| word | token it fed | mechanism |
|---|---|---|
| `untouched` | `touch` | internal fragment (un-**touch**-ed) |
| `nodes` | `node` | leading fragment (**node**-s) |
| `awkward` | `awk` | leading fragment (**awk**-ward) |
| `reinstall` | `install` | internal fragment (re-**install**) |
| `committee` | `tee` | internal fragment (commit-**tee**) |

### Correction to a claim that was in circulation

`between` was asserted to contain `tee`. **It does not.** It is `be-tween`,
whose substring is `twee`. Measured directly: `printf 'between' | grep -oE
'tee|touch|node|awk|install'` returns nothing, and the unanchored mutant
**permits** `grep -c between <namespace>` on both layers while refusing the
other five words. `committee` is the real `tee` collision. The test file
records `between` as a measured non-collision
(`test_measured_non_collision_stays_a_non_collision`) so it is not
re-introduced later as evidence of something it never demonstrated.

### Short tokens are the dangerous ones

`tee`, `cp`, `mv`, `ln`, `dd` are 2–3 characters. They are the tokens most
likely to appear inside an unrelated word, and the `committee` case is the
proof that this is not theoretical.

## Root cause

The verb list was **never anchored**. It was authored as a convenience
alternation — "does the command mention a write verb?" — and `grep -E` answers
that question with substring semantics. Nothing in the predicate expressed the
intended meaning, which is "is a write verb *invoked* here?", i.e. the verb
occupies a command-head position rather than sitting inside a longer token.

Scope note, measured: as of `HEAD 74acb8f9f` both layers exist **only in the
working tree** — `git show HEAD:hooks/pretool-bash-safety.sh | grep -c
'commit-dispatch-attestation-write\|commit-grant-raw-write'` returns `0`. The
defect is pre-existing relative to the layers themselves (the list was never
anchored at any point in their authorship), not pre-existing in committed
history.

## The anchoring decision, and why it does not weaken interception

Each token is anchored **individually**:

```
\bVERB([^A-Za-z_]|$)
```

- **Leading `\b`** — a word boundary, so the character before the verb must be
  a non-word character.
- **Trailing `([^A-Za-z_]|$)`** — the next character must not be a letter or
  underscore, or the verb must end the line.

The flat per-token shape is deliberate: it keeps a one-to-one correspondence
with the original 16 tokens, in the original order, so the list stays
auditable and the regression test can still enumerate it verb by verb.

### The trap: naive both-sides anchoring silently opens a write route

Anchoring immediately after the bare verb name would stop matching the forms
real invocations actually take. That is **worse than the over-block**: an
over-block is loud and merely annoying, whereas a verb that slips past branch 2
writes into the protected namespace with no redirection operator at all — which
means branch 1 is structurally blind to it. The anchoring therefore still
matches, each one measured and pinned in
`test_anchoring_did_not_narrow_the_reach`:

- **Version-suffixed interpreters.** The trailing class admits digits and dots,
  so `python3`, `python3.12`, `perl5.36`, `ruby3.2`, `node20` all still match.
- **Leading directory paths.** `/` is a non-word character, so `\b` is
  satisfied by `/usr/bin/touch`, `/usr/local/bin/python3`, `./bin/node`,
  `../vendor/perl`.
- **Every command-head position.** First word of the line, and the first word
  after a pipe, a semicolon (spaced or not), `&&`, `||`, a subshell `(`, or a
  command substitution `$(`.
- **Real binary aliases the old substring form covered by accident.** These are
  kept explicitly, as optional groups, so the repair does not quietly drop
  coverage that existed before it: `cp(io)?`, `i?python`, `[gmn]?awk`,
  `node(js)?`. `gawk` matters in particular — it is the default `awk` on most
  Linux distributions, and `awk` is an interpreter, so losing it would reopen
  precisely the no-redirection hole branch 2 exists to close.

And it now **stops** matching a verb that is merely an internal or trailing
fragment of a longer word, which is the defect.

Nothing was removed. All 16 tokens remain in both layers, in their original
order, with all five interpreters (`python`, `awk`, `perl`, `node`, `ruby`)
intact in each. Branch 1 — the redirection branch — was not touched.

### Residual, accepted

A verb blacklist remains a **blacklist**: it raises the cost of hand-authoring
these artifacts from Bash, it is not an absolute barrier, and must not be
described as one. A verb not in the list still writes through. The structural
barrier stays where it already was — `hooks/pretool-git-privilege-guard.py`
refuses any grant without a pipeline `minted_by.origin`, any caller with an
empty `agent_id`, and any caller that is not the dispatched subagent holding
the matching dispatch attestation.

Also accepted: a bare standalone verb that *is* an English word (`node`,
`install`, `tee`, and `gawk` as a verb) still matches when it stands alone,
because it is simultaneously the real binary name. Anchoring cannot separate
those two readings; only the fragment case is fixed.

## Same class, still present in sibling branches (NOT repaired here)

Out of scope for this lane — a different refusal branch is a different lane —
but recorded so it is findable. Measured with a passing positive control (a
real `touch` write into each namespace is refused, so the method can hit):

| hook line | label | unanchored alternation |
|---|---|---|
| 965 | `daemon-restart-sentinel-write` | `(>\|>>\|tee\|cp\|mv\|ln\|touch\|cat\s)` |
| 987 | `commit-userintent-sentinel-write` | `(>\|>>\|tee\|cp\|mv\|ln\|touch\|cat\s)` |
| 1676 | docker daemon-config write | `(>\|>>\|tee\|cp\|mv\|sed\|awk)\s.*` |

On lines 965 and 987, `grep -c untouched <namespace>` and
`grep -c committee <namespace>` are both **refused** — 4 over-blocked pure
reads. `nodes`, `awkward` and `reinstall` are permitted there, correctly: those
alternations carry no `node`, `awk` or `install` token. The line-1676 branch
requires whitespace after the verb, which incidentally blocks the `untouched`
collision but leaves its leading side unanchored.

Line numbers are "as of this edit" and drift; the labels are stable.

## Counts, before and after

Measured on label-**emitting** lines specifically — `echo`/`printf` of
`BLOCKED: <lowercase-label>` — not substring occurrences anywhere in the file.
A previous measurement of this same quantity was wrong because it counted
comment and explanatory text.

| metric | before | after |
|---|---|---|
| label-emitting lines (lowercase stable label) | 30 | 30 |
| distinct stable labels | 23 | 23 |
| all `BLOCKED:`-emitting lines | 44 | 44 |

The 44 − 30 = 14 difference is 14 refusal *messages* that carry no lowercase
stable label (e.g. `BLOCKED: Destructive disk operation detected` at line 1694)
— they are emissions, not comments. **Zero** comment or prose lines in the file
contain the string `BLOCKED:`. No count decreased.

## Regression coverage added

`hooks/tests/test_commit_artifact_rw_boundary.py`:

- `test_prose_word_collisions_are_permitted` — the five collisions × both
  layers, each with the de-anchored-mutant positive control.
- `test_measured_non_collision_stays_a_non_collision` — pins `between`.
- `test_anchoring_did_not_narrow_the_reach` — 22 shapes × both layers:
  version-suffixed interpreters, aliases, leading directory paths, and every
  command-head position.

**Disclosed test change:** `_normalize_verb` / `_layer_verbs` previously split
branch 2's alternation on a flat `alt.split("|")` and stripped only `\b` and
`\s`. That parser **encoded the flat, unanchored token shape as the expected
structure** and shredded anchored tokens into fragments (`$)`,
`tee([^A-Za-z_]`), failing 4 tests. It was upgraded — a depth- and
bracket-expression-aware `_split_alternation`, plus normalization that strips
the trailing boundary class and optional alias groups — so it again derives the
bare 16 verbs. The polarity assertions it feeds are unchanged; no assertion
was weakened to accommodate the repair.

### Suite status — a method, not a frozen count

Two populations live in this statement and must not be read as one; quoting
one as the other, or comparing across them, is how a misleading comparison
gets built. Name the population you collected.

- **The two files this lane touched** — `test_commit_artifact_rw_boundary.py`
  and `test_fail_closed_drift.py`. The figures below describe only these.
- **The whole `hooks/tests/` directory collection** — more than an order of
  magnitude larger, and the repo's default `testpaths` run adds `tests/` again
  on top of that.

Method, re-runnable: collect and then run each file individually under the
repo's own pytest configuration, reading the collected and passed totals off
that run. The claim pinned here is the *shape* — every collected test passes,
in both files, nothing skipped — so re-derive the numbers rather than trust
them.

Point-in-time observation, 2026-10-08, single host: 162 collected / 162 passed
in `test_commit_artifact_rw_boundary.py`, 31 collected / 31 passed in
`test_fail_closed_drift.py`; whole-directory collection 3781 (the directory
holds 72 `test_*.py` files), default run 6389. Observations, not standing
facts.

The `86 passed / 4 failed` this line used to carry is **history, not a
re-runnable figure** — the old `_normalize_verb` parser meeting anchored
tokens, a state the disclosed test change above removed. And the line is
itself a repaired instance of the defect above: it read `115 passed` while the
file collected 162. Its adjacent `31` re-measured correctly — one drifted
figure does not convict its neighbours.

## Rule

Any verb added to any write-verb alternation in this hook must be anchored
`\bVERB([^A-Za-z_]|$)` at the time it is added. An unanchored token is an
over-block waiting to be discovered by whichever English word happens to
contain it.
