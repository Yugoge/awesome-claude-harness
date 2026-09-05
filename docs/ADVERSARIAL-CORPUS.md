# Adversarial Bypass Corpus — claude-code-guardrails

> **`hooks/tests/fixtures/adversarial_corpus.json` is the sole authoritative source.**
> This markdown is a static, human-readable index only. It is not generated from the JSON and
> nothing reads it. If the two ever disagree, **the JSON is correct and this file is stale**.
> Everything that gates CI — the black-box suite, the coverage gate, the drift probe — reads the
> JSON and never this document.

---

## 1. What this corpus is

A public, machine-readable set of inputs that probe the boundary of this harness's git-command
guards, together with the outcome each one is *expected* to produce and the evidence layer that
expectation rests on. It exists because a security claim a hostile reader cannot falsify is not
a security claim.

Two companion documents: `docs/THREAT-MODEL.md` §4 RISK-3 explains the boundary in prose, and
`docs/ENFORCEMENT-LEDGER.md` records what each wired hook is claimed to do and on what evidence.
Every corpus entry's `table_row` resolves to a real row in that ledger, and the linkage is
checked mechanically, so the three cannot drift apart.

## 2. Safety and honesty properties

These are not decoration; each is enforced by an assertion, not by good intentions.

- **No payload is ever executed.** Each is handed to a guard as *inspection input* on stdin, in
  the Claude Code PreToolUse shape, and the guard's own verdict is read back.
- **Every case carries a side-effect oracle.** The repository HEAD sha is captured before and
  after each invocation and asserted byte-identical. A case that somehow did mutate state fails
  loudly rather than passing quietly.
- **The detection witnesses use the harmless `status` subcommand.** This is a *disclosed
  substitution*: both `_command_token_index()` and the regex anchor classes are
  subcommand-independent, so `status` measures exactly the same detection boundary as a
  destructive verb would. No destructive command was constructed to build this corpus.
- **`expected_verdict` is a hypothesis, not an axiom.** The suite asserts observed against
  published. If they disagree, the rule is to correct the *published* value — see §5.

## 3. Per-entry schema

| field | meaning |
|---|---|
| `case_id` | Stable unique identifier. Uniqueness is asserted. |
| `case_class` | `deny`, `gate_deny`, or `boundary_control`. (`known_residual` was retired 2026-09-03 — see §6; no case carries it now.) |
| `table_row` | The `docs/ENFORCEMENT-LEDGER.md` row this case is evidence for. Referential integrity is asserted. |
| `lifecycle_event` | The Claude Code lifecycle event the guard is wired to. |
| `guard_chain` | Which guard(s) the case actually drives. |
| `build_config` | Claude Code build, OS, runtime and harness commit the expectation was recorded against. |
| `setup` | Preconditions (actor variables unset, no grant present, …). |
| `payload` | The command string handed to the guard as inspection input. |
| `expected_host_semantic` | What the host is expected to do, in words. |
| `side_effect_oracle` | The safe, observable check that nothing was mutated. |
| `expected_verdict` | `deny`, `allow`, or `not_detected`. |
| `matrix_cell` | The residual-matrix equivalence class this case witnesses. |
| `gate_architecture` | `A`, `B`, or `n/a` — see §4. |
| `witness_id` | `W1`–`W11` for mandated cell witnesses, `null` otherwise. The `ADV-K-*` reserved-word cases added 2026-09-03 are all `null`: they witness a family the published cell matrix never enumerated. |

## 4. Why `gate_architecture` is a field and not a footnote

Detection and prevention are different questions, and conflating them is how this repository's
threat model previously published a claim that was wrong in both directions at once.

- **Architecture A** — the classifier branch requires `CLASSIFIER_STATUS` to be `ok` *and* a
  match to be found, while the regex fallback is guarded on the status *not* being `ok`. Because
  a successful-but-**empty** parse also sets `ok`, an input the classifier tokenizes without
  finding git in **suppresses its own backstop**. Census at `4c33f2f5`: exactly **one** gate.
- **Architecture B** — the regex branch runs unconditionally and is OR-ed with the classifier
  result, so a bare token still matches. Census at `4c33f2f5`: **two** branches. Unaffected.
- **Architecture C** — classifier-only path-qualified augmentation branches with no regex
  fallback, because they never had one: each *adds* path-qualified coverage beside a separate
  bare-form regex gate. Census at `4c33f2f5`: **eight** branches. Unaffected, and the
  numerically dominant shape. It is counted here so the census cannot be read as cherry-picked
  toward the finding — an adversarial review of an earlier draft of this document flagged
  exactly that, correctly.

The consequence is visible directly in the corpus: `ADV-W05-envu-bare-archA` and
`ADV-W05-envu-bare-archB` carry the **same payload** and **opposite expected verdicts**. Nothing
about the payload decides the outcome — the gate's shape does.

## 5. Falsification clause

`expected_verdict` records what this analysis *predicts*, measured at the detection layer and by
reading gate control flow. If the black-box suite observes a residual form actually being
blocked by some mechanism this analysis did not enumerate, the published row is corrected to
match the observed behavior — **not** the other way round. A lane whose product is
"verified, not asserted" does not get to make its own analysis unfalsifiable.

At the revision this corpus was authored, all 20 cases were run and **every observed outcome
matched its published expectation**, so no correction was required.

**The clause was exercised for real on 2026-09-03**, and this is what it looks like when it
fires. `_command_token_index()` was taught the shell constructs it had never skipped — the
reserved words, leading redirections, and a wrapper's own option flags — and eight cases
published as `not_detected` were then observed as `deny`. Per the clause, the published rows
were corrected to match observation: `ADV-W04-envi-bare-archA`, `ADV-W05-envu-bare-archA`,
`ADV-W06-redir-bare-archA`, and `ADV-W07`–`ADV-W11` moved from `known_residual` /
`not_detected` to `deny` / `deny`, and `known_residual` now has no members. Nineteen
`ADV-K-*` cases were added for the reserved-word family. The corpus is **39 cases**.

## 6. Precision about what the residual entries mean

The `known_residual` entries were **detection-layer measurements** — tokenizer misses and regex
non-matches — plus a source-level reading of gate control flow. They were **not** demonstrated
executable bypasses, and no push, reset or ref mutation was performed to produce any of them.
A sibling lane independently reached the same boundary from the host-shaped layer (synthetic
PreToolUse payload, exit code read) and its result is cited by reference rather than re-run.

**Retired 2026-09-03.** The residual was published as a *deliberately accepted* design boundary,
on the strength of the classifier's own docstring saying so. That framing turned out to under-
state the exposure in two ways, and both are the reason the class no longer exists:

1. **The accepted boundary was wider than the matrix said.** The matrix was built on a
   wrapper × path-qualification grid, so nobody probed a *shell reserved word*. `if ! git … `,
   `then git …`, `do git …`, `while ! git …` and thirteen more forms enumerated to NOTHING —
   and `if ! git commit …` is this repository's own documented error-handling idiom, present
   twice in the committed text of `agents/changelog-analyst.md`. The residual was not an exotic
   corner; it was the house style.
2. **"Detection-layer only" understated the blast radius.** `pretool-git-privilege-guard.py`
   built its invocation list once and returned immediately when that list was empty, *before*
   dispatching any check. A miss in the enumerator was therefore not a miss in one gate — it
   skipped the commit policy, the reset-hard check, the direct-ref-mutation check, the push
   check, the merge check and the forbidden-plumbing check together.

Both are closed. The enumerator now skips every construct the shell permits before a command
word, and an empty invocation list is no longer silently equivalent to "no git here": a
command that is git-shaped but statically unresolvable (`g\it push`, `$GIT push`,
`$(which git) push`) is refused rather than dropped through the early return. Measured against
71,598 unique real commands from the harness transcripts, that fail-closed branch fires on 2
(0.003%) and no command the guard previously refused is now permitted.

## 7. Prior art — reused, not duplicated

`hooks/tests/test_git_cmd_cross_consistency.py` already implements a 20-plus-entry
git-command-detection corpus that cross-checks `GIT_CMD_RE`, `GIT_COMMAND_RE` and
`iter_git_invocations()` for agreement, with accepted divergences marked `xfail`. That module is
**referenced, not copied**: a second parallel git corpus would recreate exactly the
two-hand-synced-copies drift risk that RISK-2 of `docs/THREAT-MODEL.md` teaches this repository
to avoid. This corpus covers what that one does not — the wrapper-flag and leading-redirection
equivalence classes, and the gate-architecture dimension.

## 8. Running it

```
python3 -m pytest hooks/tests/test_blackbox_integration.py -q
python3 scripts/check-enforcement-evidence.py --coverage
```

The first drives every case at the subprocess boundary and writes the run manifest; the second
gates that manifest for one-to-one corpus coverage, field population, and evidence-of-execution
provenance. In CI both run inside the required `baseline` job, and the manifest is uploaded with
`if: always()` so a red run still publishes what it exercised.

**This suite earns `proof_layer: component-tested` and nothing stronger.** A subprocess
invocation of a hook script is not a real Claude Code event dispatch: it proves the script's own
behavior, not that the dispatcher routed to it, nor that the host honors the exit code.
Requirement R3 — black-box integration tests against real supported Claude Code builds — remains
**incomplete, not satisfiable in this environment**.
