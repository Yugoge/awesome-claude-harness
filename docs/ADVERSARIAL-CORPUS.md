# Adversarial Bypass Corpus — awesome-claude-harness

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
| `case_class` | `deny`, `known_residual`, `gate_deny`, or `boundary_control`. |
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
| `witness_id` | `W1`–`W11` for mandated cell witnesses, `null` otherwise. |

## 4. Why `gate_architecture` is a field and not a footnote

Detection and prevention are different questions, and conflating them is how this repository's
threat model previously published a claim that was wrong in both directions at once.

- **Architecture A** — the classifier branch requires `CLASSIFIER_STATUS` to be `ok` *and* a
  match to be found, while the regex fallback is guarded on the status *not* being `ok`. Because
  a successful-but-**empty** parse also sets `ok`, an input the classifier tokenizes without
  finding git in **suppresses its own backstop**. Census at `4c33f2f5`: exactly **one** gate.
- **Architecture B** — the regex branch runs unconditionally and is OR-ed with the classifier
  result, so a bare token still matches. Census at `4c33f2f5`: **two** branches. Unaffected.

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

## 6. Precision about what the residual entries mean

The `known_residual` entries are **detection-layer measurements** — tokenizer misses and regex
non-matches — plus a source-level reading of gate control flow. They are **not** demonstrated
executable bypasses, and no push, reset or ref mutation was performed to produce any of them.
A sibling lane independently reached the same boundary from the host-shaped layer (synthetic
PreToolUse payload, exit code read) and its result is cited by reference rather than re-run.

This residual is a **deliberately accepted** design boundary — the classifier's own docstring
says so at `hooks/lib/git_command_classifier.py:17 @4c33f2f5`. Publishing it does not widen it.
Closing it is a separate, security-reviewed decision and is deliberately out of scope here.

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
