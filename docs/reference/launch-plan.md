# Launch Plan — ROI-ranked channels, gated on recorded evidence

**Status**: planning artifact. **Every gate below is BLOCKED today.**
**Authored**: 2026-08-02 · Lane H of `docs/dev/specs/spec-20260719-163852.md` §5 "P3 — H"
**Authoritative copy source**: `docs/dev/specs/20260719-163852/design/turn-1-codex-capstone-review.md:324-368` (named authoritative by that spec's §9.1)

---

## 0. What this document is, and what it is not

### 0.1 Non-authorization clause (operational prohibition)

**This document authorizes no posting, submission, upload, or outreach; execution is a human decision taken outside this pipeline.**
Nobody may treat the existence of this plan, or a green gate row inside it, as permission to
publish anything. Recording a channel *eligible* records eligibility and authorizes nothing.

**This clause is a prohibition, not an evidence claim.** No artifact in this repository can prove
that no outward action occurred — a clean working tree, an unchanged diff and a complete gate
table are all equally consistent with someone having posted. Absence of evidence is reported as
absence of evidence, and this document never claims otherwise.

### 0.2 No mechanical enforcement is claimed

Nothing here is wired into CI. Nothing here makes launching technically impossible. The gate
contract is a **record-keeping discipline**: it defines what must be *recorded as verified*
before a human chooses to execute a channel. A tree-inspecting script cannot decide whether a
sibling lane is "done" — completion is a multi-criterion, live-host evidence question, and any
file-inspection proxy would report green on work that had not happened. That is why the gates are
evidence records rather than computed verdicts.

### 0.3 What this lane authored, and what it did not

Lane H authors only: the **shot list**, the **content contract**, the **reuse destinations**, and
the **gates**. **Media production is outside this lane** — the 90-second master, the GIFs, and any
hero clip are produced elsewhere, and channel ③'s refusal footage cannot exist before Lane A
lands. Pitch and limitations *wording* belong to §5 G, the README hero to §5 F, and the
name/framing to §5 E; this plan references them as gate inputs and does not author them.

Artifacts named here that do not exist yet — a strict preflight, a minimal install profile, the
demo assets, a compatibility ledger — are named as **future prerequisites**, never as existing
paths.

---

## 1. Channel overview (ROI order)

| № | Channel | Purpose | Required gate row set (exact) |
|---|---|---|---|
| ① | **Show HN** | Highest-ROI single spike; technically hostile, evidence-rewarding audience | A-PASS, B-PASS, D-PASS, E-PASS, F-PASS, G-PASS, RULES-PASS(Hacker News) |
| ② | **r/ClaudeAI** | Practitioner audience already running the tool being guarded | A-PASS, B-PASS, C-PASS, E-PASS, F-PASS, G-PASS, RULES-PASS(r/ClaudeAI) |
| ③ | **90s demo video** | Reusable proof asset consumed by README, ① and ② | A-PASS, B-PASS, E-PASS, F-PASS, RULES-PASS(selected video host) |
| ④ | **X thread** | Broad reach, low depth; carries the same security framing as ① | A-PASS, B-PASS, D-PASS, E-PASS, F-PASS, G-PASS, RULES-PASS(X) |
| ⑤ | **awesome-* lists** | Durable discovery; unlikely to create the initial spike | A-PASS, B-PASS, E-PASS, G-PASS, RULES-PASS(awesome-* target set) |

The row sets above are an **exact contract**, not a minimum. A channel's gate table must contain
each mapped gate ID **exactly once and nothing else**. In particular ① carries **no C-PASS row**
(it does not consume the installer) and ③ carries **no D-PASS row** (it is held by its own
A/B/E/F rows).

---

## 2. The named launch candidate

Every PASS is evidence **against a named launch candidate**: a specific release or commit, plus
the specific host where host-bound evidence applies.

- All `PASS` gates within one channel must reference the **same** launch-candidate ref. Baseline
  refs and lane-completion refs may explain a `BLOCKED` status, but can never satisfy a `PASS` —
  otherwise a channel could be assembled from mutually incompatible revisions.
- **Current launch candidate: UNFILLED.** No candidate has been named. This is the single reason
  every gate row below is BLOCKED, and it is checkable by reading this document.

---

## 3. Gate definitions

No gate's PASS condition is the presence or absence of a keyword in a file. A keyword gate is
satisfiable by word substitution, by deleting old text, or by any arbitrary asset, and would
report green on work that had not been done.

| Gate | Owner | PASS criterion |
|---|---|---|
| **A-PASS** | §5 A | Recorded evidence that **every** Lane-A Must acceptance criterion passes for the named launch candidate, **plus** a fresh capability handshake bound to the **execution host**, the **Claude Code build**, the **settings hash**, and the **harness version**. Channel ③ additionally requires captured evidence of a real unsupported-host protection refusal. |
| **B-PASS** | §5 B | Recorded evidence for **all** Lane-B Must criteria against the exact launch candidate: residue-blocking CI, dependency pinning, Actions pinning, unprivileged clean install, signed artifacts, checksums, SBOM, and released-artifact verification. |
| **C-PASS** | §5 C | A **tested isolated minimal-profile install that preserves an already-occupied user configuration**. An installer merely being promoted, documented or shipped is insufficient. |
| **D-PASS** | §5 D | The threat model matches current behavioural evidence and the enforcement ledger. For RISK-3 specifically, see §7: the gate closes only when a regression test proves the residual class closed. Accurately-disclosed unrelated residual risks do **not** fail this gate. |
| **E-PASS** | §5 E | The canonical public name / CLI / framing is consistently present. |
| **F-PASS** | §5 F | A reproducible demo satisfying its action → block → reason → remedy → single-use-grant sequence and the provenance rules in `docs/demo-capture.md`. Any arbitrary asset is insufficient. |
| **G-PASS** | §5 G | The approved pitch, audience and limitations contract exist. **E and G are separate gates; do not merge them.** |
| **RULES-PASS** | Executor (human, at execution time) | Per external target, a recorded row carrying the five fields of §13. Missing, ambiguous or conflicting rules **block that target**. |

### 3.1 Diagnostics are not gates

Single observations — that a personal config became untracked, that a version badge changed, that
a strict flag now exists in a usage block, that an installer is promoted somewhere — are
**diagnostics, not the gate**. They are useful signals about the public state of the tree. They
are not evidence that a lane's deliverable passes for a named candidate, and none of them may be
recorded as a PASS.

### 3.2 Execution-blocking rule

**No channel may execute unless A-PASS and B-PASS are current PASSes for the same named launch
candidate and satisfy their freshness requirements.** `BLOCKED`, `FAIL`, `UNKNOWN`, missing or
stale evidence blocks execution. A-PASS and B-PASS are the universal minimum named by the
requirement itself; they are not the whole test — **a channel may be recorded eligible only when
every one of its required gate rows is PASS**, and any non-PASS required gate holds the channel
BLOCKED.

---

## 4. Gate table schema and status vocabulary

Every channel carries **exactly one** gate table with **exactly six columns**:

> **condition · owner lane · verification method · required evidence artifact · freshness
> requirement · status today**

### 4.1 Conformance versus blocked

A missing, duplicated, aliased, merged, unknown or extra gate row is a **conformance FAIL**, and
marking the channel `BLOCKED` does **not** cure it. `BLOCKED` is a valid channel state only when
the complete required row set is present **and** at least one of those gates is non-PASS. This is
what stops an omission being laundered as a blocked gate.

### 4.2 `schema_present` and `evidence_complete`

- **`schema_present`** — every one of the six columns carries a non-empty value after trimming,
  and every required nested field exists.
- **`evidence_complete`** — **derived, never self-asserted.** True only when every required field
  of that row is present, non-sentinel, and satisfies its own field rule. A `PASS` row requires
  `evidence_complete = true`. Today it is false for every row in this document.

### 4.3 Sentinels: a closed set, and only in the evidence columns

Permitted incomplete-evidence tokens are exactly **`UNFILLED`**, **`UNVERIFIED`**,
**`UNDETERMINED`**, and only on rows whose status is `BLOCKED`. Blank cells and every other
placeholder spelling (`TBD`, `N/A`, `-`, `--`, `?`, `—`, `none`, `pending`) fail schema
validation. **No row may be marked `PASS` while any required field holds a sentinel.**

**Definitional columns may never hold a sentinel.** The six columns are two different kinds of
thing, and collapsing them would let a table of pure placeholders satisfy the schema:

| Column | Kind | Sentinel permitted? |
|---|---|---|
| condition | definitional | **No** — the condition is knowable now and must be stated now |
| owner lane | definitional | **No** |
| verification method | definitional | **No** — how it will be checked is knowable now |
| freshness requirement | definitional | **No** — the freshness rule is a policy decision, made now |
| required evidence artifact | evidence | **Yes** — the artifact does not exist yet |
| status today | status | `BLOCKED`, with the sentinel permitted only as a qualifier |

A row whose *condition*, *owner lane*, *verification method* or *freshness requirement* cell
carries a sentinel is a conformance FAIL, not a blocked gate.

### 4.4 Row classes — exactly two, no third

| Class | Gates | Supporting evidence form on top of the primary blocking reason |
|---|---|---|
| **tree-derived** | A, B, C, D, E, F, G-PASS | A **content anchor** re-located at authoring time and recorded as a **corroborating indicator of the current public state** — explicitly *not* proof the gate is unmet, and never a claim that the cited text proves a sibling lane's deliverable does not exist anywhere |
| **non-tree** | all `RULES-PASS` rows | The row's **five record fields visibly carrying sentinels** — that is the falsifiable evidence. The capability-denial citation is context only |

No row outside these two classes may appear in any gate table.

### 4.5 Anchor selector policy and supersession

Every content anchor points into a file owned by a lane running **concurrently** with this one,
and each anchor's condition is owned by the very lane whose completion that gate tests. **An
anchor disappearing is therefore the expected signal of that lane progressing — not a defect and
not an error.**

**The quoted anchor text is the authoritative selector. The line number is a baseline convenience
and is NOT authoritative**; it is re-derived by locating the text.

1. **Anchor absent is never a PASS.** Absence of the old text proves nothing about the gate.
2. Anchor resolves → record it normally as a corroborating indicator.
3. Anchor does not resolve → evaluate the gate's **positive** criterion against the same named
   launch candidate. If qualifying recorded evidence exists, the gate **PASSes through the
   ordinary evidence route**. A genuinely satisfied gate is never frozen by a vanished anchor.
4. Otherwise record `BLOCKED — baseline indicator absent or superseded`. Attribute it to a named
   lane (`superseded by lane X at <ref>`) **only** where that lane's tracked completion artifact
   associates the change with this indicator; otherwise record `BLOCKED — anchor unresolved after
   concurrent edit`. Disappearance alone does not prove who caused it.
5. This branch **replaces**, not supplements, anchor-presence validation: a citation is valid when
   *either* it resolves *or* a complete unresolved/superseded record exists.
6. All `PASS` gates within a channel reference the **same** launch-candidate ref.
7. **Nobody may edit a sibling-owned file to restore a vanished anchor.**

---

## 5. Baseline indicator register (evaluation log, 2026-08-02)

Each indicator records: *file · anchor text · expected polarity · baseline line (non-authoritative)
· evaluated ref · what the anchor identifies*. All eight were re-located at authoring time against
`4c33f2f5`; each of the anchored files was unmodified in the working tree at read time.

| ID | Gate | File | Anchor text (authoritative selector) | Polarity | Baseline line (non-authoritative) | Evaluated ref | What it identifies | Resolved? |
|---|---|---|---|---|---|---|---|---|
| BI-A | A-PASS | `scripts/doctor` | `# Usage: scripts/doctor [--venv <venv-dir>]` | **absent-predicate**: the token `--strict` is absent file-wide; the usage block is the contextual anchor only | `:7-8` | `4c33f2f5` | The strict preflight Lane A must add is not present | yes (0 occurrences of the token) |
| BI-B1 | B-PASS | `PUBLIC-CORE.md` | the `settings.json` row classifying it `private-lab` | present | `:130` | `4c33f2f5` | The boundary manifest's own record that a tracked personal config is classified private | yes |
| BI-B2 | B-PASS | `README.md` | `badge/version-1.0.0-blue` | present | `:11` | `4c33f2f5` | A released-version badge sitting above that record | yes |
| BI-C | C-PASS | `README.md` | `git clone https://github.com/Yugoge/awesome-claude-harness.git ~/.claude` **and** `The only "installation" is` | present | `:35`, `:527` | `4c33f2f5` | Clone-over-`~/.claude` promoted as the only install | yes |
| BI-D | D-PASS | `docs/THREAT-MODEL.md` | `RISK-3 gap UNMITIGATED in interactive sessions` — **quoted as the published wording, not asserted as this document's status** (see §7) | present | `:112-117` | `4c33f2f5` | The published RISK-3 status line that §7 corrects | yes |
| BI-E | E-PASS | `README.md` | `A Self-Governing Agent Operating System for Claude Code` | present | `:1` | `4c33f2f5` | The title framing §5 E replaces | yes |
| BI-F | F-PASS | `README.md` | `not a screen recording` (hero image alt text and the caption below it) | present | `:4`, `:6` | `4c33f2f5` | The stylized hero §5 F replaces | yes |
| BI-G | G-PASS | `README.md` | `badge/subagents-`, `badge/lifecycle%20events-`, `badge/skills-` | present | `:12-18` | `4c33f2f5` | The inventory badge block leading the page | yes |

**Read every one of these as an indicator of the current public state, never as proof.** That a
clone instruction is published does not prove no tested minimal profile exists anywhere; that the
old hero is still in place does not prove no qualifying demo exists. The **primary** blocking
reason for every gate row is the empty evidence record, which is directly checkable inside this
document.

---

## 6. Limitations block

### 6.1 Support snapshot — as of 2026-08-01

- **`ubuntu-latest` is supported and tested.** It is the declared, tested platform
  (`.github/workflows/baseline.yml:18-20`).
- **macOS and Windows are outside the supported matrix** (same source).
- **GNU userland is required** (`README.md:411`): the GNU forms of `realpath`, `flock`, `stat`,
  `sha256sum`, `date`, `grep`, `sed`, `awk` and `find` are assumed, and BSD/macOS flag variants
  are expected to produce hook failures.

**This is a dated snapshot, not a standing claim.** Every support statement in this document
carries the date above. No undated, permanent support claim appears anywhere in this plan, and
none may be introduced.

### 6.2 Re-derivation is mandatory before any channel executes

The limitations block published in any channel must be **re-derived at execution time** from the
then-current compatibility ledger and from fresh Lane-A evidence, and must record the **release**
and the **date** of that derivation. The snapshot in §6.1 is a baseline for planning and must not
be copied into a post.

### 6.3 What the limitations block must say about the security claim

Whatever channel it appears in, the limitations block must carry the §7 finding in the direction
§7 states it. A launch that leads with a threat model must not publish a status its own
measurements contradict.

---

## 7. D-PASS and the RISK-3 finding

### 7.1 Provenance of this section

Re-derived at authoring time from the **latest valid revision** of the sibling RISK-3 artifacts,
resolved by **lane + artifact role** rather than by any frozen timestamp:

| Role | Resolved artifact | Immutable ref (sha256) | Parse / claim check |
|---|---|---|---|
| Lane D ticket | `docs/dev/ticket-dev-20260719-193823-d.md` | `5ed0b2610eb827d44a3a08b28589864bda07d3e050ed584e15045f7149b69f3f` | readable; carries the detection-layer corpus and the normalized status |
| Lane G QA report | `docs/dev/ba-qa-report-dev-20260719-193823-g.json` | `952e3c04a7c56a109c8268f6573fa1969ea9eabb8be6386b89098c30daab8b54` | parses as JSON; carries the gate-layer result |

If a resolved artifact is ever absent, ambiguous, unparsable, or does not contain the claim being
cited, the evidence is recorded `BLOCKED`. **There is no silent fallback to an older or more
favourable revision** — a silent downgrade is the frozen-stale-evidence failure this rule exists
to prevent.

### 7.2 The published status is wrong in both directions

The published section states, at its "Current status" line, that the RISK-3 gap is *"UNMITIGATED
in interactive sessions"*, under a title that scopes RISK-3 to path-qualified `git push`. Measured
results contradict that in **both** directions, and stating only one of them would replace one
inaccuracy with another:

- **Too NARROW.** The measured residual is not confined to path-qualified forms. It spans the
  wrapper-with-flag and leading-redirection prefix families across the classifier's wrapper token
  set, it **includes bare (non-path-qualified) forms**, and it covers the **destructive-reset**
  family rather than push. **Path qualification is not a necessary condition for the residual.**
- **Too BROAD.** The tested **direct path-qualified force-push payload returned exit 2**. The
  exact shape the published title names is, on the evidence available, not the open hole.

**Accurate normalized status: `PARTIALLY MITIGATED`.** The published `UNMITIGATED` wording is
quoted above as the text being corrected, not adopted; a flat "mitigated" is equally wrong; and a
"the residual got smaller" framing is wrong too, because the residual is *broader* than the
published scope in family and in qualification while being *narrower* in the one shape the title
names.

### 7.3 The mechanism (read at primary source by this lane)

Read directly in `hooks/pretool-bash-safety.sh` at `4c33f2f5` while authoring this plan, rather
than inherited from a sibling's characterization:

- The destructive-reset gate's **primary branch** (`:1657`) requires the command classifier's
  status to be `ok` **and** the classifier to have found a reset invocation.
- Its **regex fallback** (`:1666-1668`) is guarded by the classifier status **not** being `ok`.
- The classifier status is set to `ok` whenever the classifier returns a schema-valid list — at
  `:906` explicitly for a **conclusive empty classification**, and at `:930` for a validated
  parse — **including an empty list**.

So an input the classifier tokenizes *successfully but without finding the git token* fails the
primary branch (nothing was found) **and simultaneously suppresses its own fallback** (the status
is `ok`). A successful-but-empty parse disables its own backstop.

By contrast the force/delete push gate (`:1695-1697`) evaluates its regex branch
**unconditionally**, OR-ed with the classifier result, so it has no equivalent self-suppression.
**That asymmetry between the two gates is the whole finding.**

This lane **did not re-run the sibling probes.** Reproducing them touches destructive git verbs,
which is outside this lane's scope; the mechanism above is cited from source reading, and the
measurements below are cited by attribution.

### 7.4 Measured breadth, with its evidence layer attached

| Layer | Measurement | Source lane |
|---|---|---|
| **Detection layer** (tokenizer and regex misses) | 136 forms probed · 110 classifier misses · 55 forms missing **both** mechanisms | Lane D |
| **Gate layer** (synthetic PreToolUse payload, exit code read) | 15 destructive-reset and force-push forms driven at the hook chain: 6 direct forms blocked, **9 returned exit 0** | Lane G |

**These are not demonstrated executable bypasses. No push, reset or ref mutation was executed by
any lane.** A public document asserting "55 bypasses" would overstate the project's own breakage.

Three quantifier limits bind any published restatement of the above:

1. Do **not** claim that every wrapper or redirection form is a live bypass. The corpus measures
   detection state.
2. Do **not** generalize the bare-form result beyond the gate family actually measured.
3. Do **not** convert the single tested force-push payload into a class-wide claim that the whole
   titled class is blocked.

### 7.5 The headline's push claim is unsubstantiated, not disproved

Reset-family evidence **cannot** establish a push bypass. The honest statement is that the public
threat-model account conflicts with measured results, and that **no evidence recorded against a
named launch candidate establishes the broad "stops … pushing unreviewed code" claim**. That is
unsubstantiated — it is not disproved, and this document does not claim it is.

### 7.6 The permission layer, stated to its measured scope

`settings.json` carries **no git-related deny rule (0 of 96)**, and its **3 git-related `ask`
rules are prefix-anchored** and therefore do not cover the tested wrapper-prefixed reset shape.
This does **not** generalize to "no second enforcement layer exists" for every git operation, and
must not be published that way.

### 7.7 Hook count: open, not frozen

The number of Bash `PreToolUse` hooks is **contested and is deliberately not frozen here**: one
sibling round reports **11** (distinct hook scripts), another reports **16** (PreToolUse hook
commands dispatched for Bash, from matchers naming Bash plus universal matchers), and a third
count reports **17** (Bash-firing hook command entries). The three use different definitions of
"Bash hook". No figure is adopted. Any channel that publishes a count must state which definition
it uses and record the discrepancy as open.

### 7.8 No reproduction recipe

This document does **not** perform, and instructs nobody to perform, a destructive git
reconfirmation. It contains **no shell-executable example combining a git invocation with a
destructive mutation or force operation.** The prose description above and the citation of the
published section by title are the disclosure, and they are required — the prohibition removes the
reproduction recipe, never the finding.

### 7.9 Consequence for the channels

**Channels ① and ④ carry the D-PASS row and stay BLOCKED until D-PASS closes.** They are the two
that lead with, or assert, the security framing this finding governs. **Channel ③ is not gated on
D** — it carries no D-PASS row and is held by its own A/B/E/F rows.

---

## ① Show HN

### Consumes / authors

- **Consumes**: §5 F raw blocked-action demo · §5 D threat model · §5 A capability handshake ·
  §5 G pitch and limitations framing · §5 E name.
- **Authors here**: the headline (verbatim, below), the submission sequencing, the limitations
  placement, and the gate list.

### Copy

**Headline — verbatim-required**, reproduced from `design/turn-1-codex-capstone-review.md:332`:

> Show HN: Claude Guard – fail-closed hooks that stop coding agents from killing services or pushing unreviewed code

**Angle — recorded recommendation** attributed to the same source (`:334`), subject to §5 E's
naming decision and §5 G's wording, reproduced as that source line reads:

**Angle:** “Prompt instructions are not enforcement.” Lead with the raw blocked-action demo, the threat model and the capability handshake. State limitations prominently. HN will reward mechanics and punish inflated claims.

### Content requirements

1. **The post leads with three things, in this order**: (a) the **raw blocked-action demo**,
   (b) the **threat model**, (c) the **capability handshake**.
2. **The limitations block sits immediately after that opening block** — before any technical
   detail, before any outbound link, and before any call to action. A trailing section or an
   appendix does not satisfy this; placement at the end defeats the requirement to state
   limitations prominently.
3. The limitations block is re-derived per §6.2 and carries the §7 finding in both directions.
4. Body copy is **DRAFT — awaiting §5 G pitch wording** until G lands, so it cannot silently
   contradict G.

### Hostile-commenter register

| What a hostile commenter will say | The honest answer |
|---|---|
| "Your own threat model says the push gap is unmitigated." | Correct that the published wording is wrong — and wrong in both directions. See §7; D-PASS holds this channel until a regression test closes the residual class. |
| "You ship a 1.0.0 badge over a config the repo itself classifies as personal." | Both are true today (BI-B1, BI-B2). B-PASS holds this channel until the release hygiene work lands. |
| "It only runs on one OS." | Stated in §6.1 as a dated snapshot, and re-derived before posting. |

### Gate table

| condition | owner lane | verification method | required evidence artifact | freshness requirement | status today |
|---|---|---|---|---|---|
| **A-PASS** — every Lane-A Must acceptance criterion passes for the named launch candidate, plus a fresh capability handshake bound to execution host + Claude Code build + settings hash + harness version | A (§5 A) | Executor reads the Lane-A acceptance evidence set for the named candidate and re-runs the handshake on the intended execution host; a flag or preflight merely existing is a diagnostic | Lane-A acceptance evidence set + handshake record (host, Claude Code build, settings hash, harness version) bound to the candidate ref — **UNFILLED** | Handshake re-run on the execution host within 24h of posting, against the same candidate ref | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-A: `scripts/doctor` · `# Usage: scripts/doctor [--venv <venv-dir>]` · absent-predicate (`--strict` absent file-wide) · baseline `:7-8` (non-authoritative) · evaluated `4c33f2f5` · the strict preflight Lane A must add is not present |
| **B-PASS** — all Lane-B Must criteria pass against the exact launch candidate: residue-blocking CI, dependency pinning, Actions pinning, unprivileged clean install, signed artifacts, checksums, SBOM, released-artifact verification | B (§5 B) | Executor reads the Lane-B evidence set for the exact candidate and verifies the released artifact from the published checksums | Lane-B evidence set + signed artifacts + checksums + SBOM + released-artifact verification log for the candidate ref — **UNFILLED** | Bound to the exact released candidate; re-verified if the candidate is re-cut | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicators (corroborating, not proof) BI-B1: `PUBLIC-CORE.md` · the `settings.json` row classifying it `private-lab` · present · baseline `:130` (non-authoritative) · evaluated `4c33f2f5`; BI-B2: `README.md` · `badge/version-1.0.0-blue` · present · baseline `:11` (non-authoritative) · evaluated `4c33f2f5` |
| **D-PASS** — the threat model matches current behavioural evidence and the enforcement ledger; for RISK-3, a regression test proves the residual class of §7 closed | D (§5 D) | Executor reads the corrected threat-model section against the enforcement ledger and the regression test result for the candidate | Corrected threat-model section + passing regression test covering the §7 residual class, bound to the candidate ref — **UNFILLED** | Regression test run against the candidate ref; re-run if hook or classifier code changes | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-D: `docs/THREAT-MODEL.md` · `RISK-3 gap UNMITIGATED in interactive sessions` (quoted published wording, corrected in §7) · present · baseline `:112-117` (non-authoritative) · evaluated `4c33f2f5` |
| **E-PASS** — the canonical public name / CLI / framing is consistently present | E (§5 E) | Executor confirms the landed naming decision is applied consistently across the candidate's public surface | Lane-E completion evidence for the candidate ref — **UNFILLED** | Bound to the candidate ref | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-E: `README.md` · `A Self-Governing Agent Operating System for Claude Code` · present · baseline `:1` (non-authoritative) · evaluated `4c33f2f5` |
| **F-PASS** — a reproducible demo satisfying action → block → reason → remedy → single-use-grant, under the `docs/demo-capture.md` provenance rules | F (§5 F) | Executor reproduces the demo from its trace artifact and checks each visible line against a real run | Reproducible demo asset + its trace artifact + provenance check result for the candidate ref — **UNFILLED** | Re-captured against the candidate ref; a demo from an earlier build does not carry forward | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-F: `README.md` · `not a screen recording` (hero alt text and caption) · present · baseline `:4`, `:6` (non-authoritative) · evaluated `4c33f2f5` |
| **G-PASS** — the approved pitch, audience and limitations contract exist | G (§5 G) | Executor confirms the approved pitch/audience/limitations contract is landed and that the post's copy derives from it | Lane-G pitch + audience + limitations contract for the candidate ref — **UNFILLED** | Bound to the candidate ref; re-approved if the pitch changes | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-G: `README.md` · `badge/subagents-`, `badge/lifecycle%20events-`, `badge/skills-` · present · baseline `:12-18` (non-authoritative) · evaluated `4c33f2f5` |
| **RULES-PASS(Hacker News)** — Hacker News's own current rules permit this submission as specified | Executor (human, at execution time) | Executor opens the target's first-party rules page at execution time and records the five fields below. **No repository file may be cited as evidence about a platform's rules.** | Recorded platform-rules row:<br>• **exact target**: Hacker News — Show HN submission (target fixed by the requirement); record UNVERIFIED in-cycle<br>• **first-party rules / CONTRIBUTING URL**: UNFILLED<br>• **access date**: UNFILLED<br>• **relevant constraints found**: UNVERIFIED<br>• **PASS decision**: UNFILLED | Re-read on the day of execution; no rules snapshot is embedded here because rules change | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate; all five record fields carry sentinels, which is this row's falsifiable evidence. Context only: `policies/tool-policy.v1.json:111-120` + `hooks/lib/policy_registry.py:264` establish **only** why the research was not performed in-cycle and **nothing** about any platform's rules |

---

## ② r/ClaudeAI

### Consumes / authors

- **Consumes**: §5 C minimal core profile and non-clobbering coexistence · §5 F three failure
  demos · §5 G limitations framing · §5 E name.
- **Authors here**: the three-failure narrative order, the reader-facing minimal-profile offer,
  and the gate list.

### Copy

**Headline — recorded recommendation** attributed to `design/turn-1-codex-capstone-review.md:340`,
subject to §5 E's naming decision and §5 G's wording (not mandated as final copy):

> I made Claude Code refuse dangerous shell and git actions—even when the agent tries to proceed

### Content requirements

1. **All three named failures are shown, in this order**: **protected-service kill** →
   **unauthorized push** → **QA rejection**.
2. **The post must actually offer the reader** (a) a **minimal-profile artifact or link**, and
   (b) **isolated try-it instructions that preserve the reader's existing configuration**. This is
   a promise made to the reader, not only a gate: a post that describes the profile without
   offering it does not satisfy the requirement.
3. The limitations block is re-derived per §6.2.
4. Body copy is **DRAFT — awaiting §5 G pitch wording**.

### Hostile-commenter register

| What a hostile commenter will say | The honest answer |
|---|---|
| "Your install tells me to clone over my `~/.claude`." | True today (BI-C). C-PASS holds this channel until a tested isolated minimal-profile install that preserves an occupied config exists. |
| "The QA-rejection demo is just your own tooling agreeing with itself." | The demo must satisfy the `docs/demo-capture.md` provenance rules: every visible line traces to a real run. |

### Gate table

| condition | owner lane | verification method | required evidence artifact | freshness requirement | status today |
|---|---|---|---|---|---|
| **A-PASS** — every Lane-A Must acceptance criterion passes for the named launch candidate, plus a fresh capability handshake bound to execution host + Claude Code build + settings hash + harness version | A (§5 A) | Executor reads the Lane-A acceptance evidence set for the named candidate and re-runs the handshake on the intended execution host | Lane-A acceptance evidence set + handshake record bound to the candidate ref — **UNFILLED** | Handshake re-run on the execution host within 24h of posting, same candidate ref | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-A: `scripts/doctor` · `# Usage: scripts/doctor [--venv <venv-dir>]` · absent-predicate (`--strict` absent file-wide) · baseline `:7-8` (non-authoritative) · evaluated `4c33f2f5` |
| **B-PASS** — all Lane-B Must criteria pass against the exact launch candidate: residue-blocking CI, dependency pinning, Actions pinning, unprivileged clean install, signed artifacts, checksums, SBOM, released-artifact verification | B (§5 B) | Executor reads the Lane-B evidence set and verifies the released artifact from the published checksums | Lane-B evidence set + signed artifacts + checksums + SBOM + released-artifact verification log — **UNFILLED** | Bound to the exact released candidate | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicators (corroborating, not proof) BI-B1: `PUBLIC-CORE.md` · the `settings.json` row classifying it `private-lab` · present · baseline `:130` (non-authoritative) · evaluated `4c33f2f5`; BI-B2: `README.md` · `badge/version-1.0.0-blue` · present · baseline `:11` (non-authoritative) · evaluated `4c33f2f5` |
| **C-PASS** — a **tested isolated minimal-profile install that preserves an already-occupied user configuration**; an installer merely being promoted is insufficient | C (§5 C) | Executor runs the minimal-profile install into an environment that already holds a populated user configuration, and verifies the pre-existing configuration survives byte-for-byte | Install transcript + before/after state of the occupied user configuration + uninstall result, bound to the candidate ref — **UNFILLED** | Re-run against the candidate ref on a clean machine | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-C: `README.md` · `git clone https://github.com/Yugoge/awesome-claude-harness.git ~/.claude` and `The only "installation" is` · present · baseline `:35`, `:527` (non-authoritative) · evaluated `4c33f2f5` |
| **E-PASS** — the canonical public name / CLI / framing is consistently present | E (§5 E) | Executor confirms the landed naming decision is applied consistently across the candidate's public surface | Lane-E completion evidence for the candidate ref — **UNFILLED** | Bound to the candidate ref | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-E: `README.md` · `A Self-Governing Agent Operating System for Claude Code` · present · baseline `:1` (non-authoritative) · evaluated `4c33f2f5` |
| **F-PASS** — a reproducible demo satisfying action → block → reason → remedy → single-use-grant, under the `docs/demo-capture.md` provenance rules | F (§5 F) | Executor reproduces each of the three failure demos from their trace artifacts | Three reproducible demo assets + trace artifacts + provenance check results for the candidate ref — **UNFILLED** | Re-captured against the candidate ref | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-F: `README.md` · `not a screen recording` (hero alt text and caption) · present · baseline `:4`, `:6` (non-authoritative) · evaluated `4c33f2f5` |
| **G-PASS** — the approved pitch, audience and limitations contract exist | G (§5 G) | Executor confirms the approved pitch/audience/limitations contract is landed and that the post's copy derives from it | Lane-G pitch + audience + limitations contract for the candidate ref — **UNFILLED** | Bound to the candidate ref | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-G: `README.md` · `badge/subagents-`, `badge/lifecycle%20events-`, `badge/skills-` · present · baseline `:12-18` (non-authoritative) · evaluated `4c33f2f5` |
| **RULES-PASS(r/ClaudeAI)** — the subreddit's own current rules permit a self-promotional technical post as specified | Executor (human, at execution time) | Executor opens the subreddit's first-party rules page at execution time and records the five fields below. **No repository file may be cited as evidence about a platform's rules.** | Recorded platform-rules row:<br>• **exact target**: r/ClaudeAI — self-promotional technical post (target fixed by the requirement); record UNVERIFIED in-cycle<br>• **first-party rules / CONTRIBUTING URL**: UNFILLED<br>• **access date**: UNFILLED<br>• **relevant constraints found**: UNVERIFIED<br>• **PASS decision**: UNFILLED | Re-read on the day of execution | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate; all five record fields carry sentinels, which is this row's falsifiable evidence. Context only: `policies/tool-policy.v1.json:111-120` + `hooks/lib/policy_registry.py:264` establish **only** why the research was not performed in-cycle and **nothing** about any platform's rules |

---

## ③ 90s demo video

### Consumes / authors

- **Consumes**: §5 A unsupported-host refusal behaviour (**hard, blocking** — captured evidence
  required) · §5 F blocked-action demo · §5 E name.
- **Authors here**: the shot list, the content contract, the reuse destinations, and the gate
  table. **Media production is outside this lane.**

### Copy

**Title — recorded recommendation** attributed to `design/turn-1-codex-capstone-review.md:348`,
subject to §5 E's naming decision and §5 G's wording:

> Claude Code tries to kill a service and push a commit. The guardrails say no.

### Content requirements

1. **Format: 90 seconds.**
2. **Reuse destinations — all three**: the **README**, the **HN** submission (①), and the
   **Reddit** post (②). One master asset, three destinations.
3. **Shot list** (this lane authors the list; the footage is produced elsewhere):
   1. A protected-service kill attempt, blocked pre-execution, with the rule and reason visible.
   2. An unauthorized push attempt, blocked pre-execution, with the safe remedy visible.
   3. A narrowly-scoped grant permitting exactly one operation, then the repeat failing because
      the grant was consumed.
   4. **Footage from a real unsupported host, visibly showing the harness refusing to claim
      protection.** This shot is part of the video itself, not merely a prerequisite captured
      elsewhere. It is a **required** shot.
4. **Authenticity**: every visible line must trace to a real run artifact, per the contract in
   `docs/demo-capture.md:9-33`. The video is composed from a real run; no line may be invented,
   and no shot may be staged.
5. **The video cannot be produced before §5 A lands** — the refusal behaviour it must film does
   not exist yet.

### Media lineage — a coordination decision, not an assertion

The **90-second master** specified here and the **raw, reproducible 10–15 second terminal
recording** specified for the README hero (`spec-20260719-163852.md:132-134`) are **two distinct
artifacts**. Whether the hero clip is an excerpt of the master, the source the master is built
from, or an independent capture is a **coordination decision to be made with §5 F**. This plan
records the decision as open and does not assert an answer.

### Hostile-commenter register

| What a hostile commenter will say | The honest answer |
|---|---|
| "This is a staged screen recording." | The authenticity contract forbids that; every visible line traces to a real run artifact. |
| "You only show it working." | The required refusal shot shows the harness declining to claim protection on an unsupported host. |

### Gate table

| condition | owner lane | verification method | required evidence artifact | freshness requirement | status today |
|---|---|---|---|---|---|
| **A-PASS (hard, blocking)** — every Lane-A Must acceptance criterion passes for the named launch candidate, plus a fresh capability handshake bound to execution host + Claude Code build + settings hash + harness version, **plus captured evidence of a real unsupported-host protection refusal** | A (§5 A) | Executor reads the Lane-A acceptance evidence set, re-runs the handshake on the intended execution host, and confirms the captured refusal footage was taken on a genuinely unsupported host | Lane-A acceptance evidence set + handshake record + **captured unsupported-host protection refusal footage and its provenance record**, bound to the candidate ref — **UNFILLED** | Handshake and refusal capture taken against the candidate ref; earlier captures do not carry forward | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-A: `scripts/doctor` · `# Usage: scripts/doctor [--venv <venv-dir>]` · absent-predicate (`--strict` absent file-wide) · baseline `:7-8` (non-authoritative) · evaluated `4c33f2f5` · the refusal behaviour this channel must film does not exist yet |
| **B-PASS** — all Lane-B Must criteria pass against the exact launch candidate: residue-blocking CI, dependency pinning, Actions pinning, unprivileged clean install, signed artifacts, checksums, SBOM, released-artifact verification | B (§5 B) | Executor reads the Lane-B evidence set and verifies the released artifact from the published checksums | Lane-B evidence set + signed artifacts + checksums + SBOM + released-artifact verification log — **UNFILLED** | Bound to the exact released candidate | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicators (corroborating, not proof) BI-B1: `PUBLIC-CORE.md` · the `settings.json` row classifying it `private-lab` · present · baseline `:130` (non-authoritative) · evaluated `4c33f2f5`; BI-B2: `README.md` · `badge/version-1.0.0-blue` · present · baseline `:11` (non-authoritative) · evaluated `4c33f2f5` |
| **E-PASS** — the canonical public name / CLI / framing is consistently present | E (§5 E) | Executor confirms the landed naming decision is applied consistently in the video's on-screen text and title | Lane-E completion evidence for the candidate ref — **UNFILLED** | Bound to the candidate ref; re-shoot if the name changes after capture | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-E: `README.md` · `A Self-Governing Agent Operating System for Claude Code` · present · baseline `:1` (non-authoritative) · evaluated `4c33f2f5` |
| **F-PASS** — a reproducible demo satisfying action → block → reason → remedy → single-use-grant, under the `docs/demo-capture.md` provenance rules | F (§5 F) | Executor reproduces the filmed sequence from its trace artifact and checks each visible line against a real run | Reproducible demo asset + trace artifact + provenance check result for the candidate ref — **UNFILLED** | Re-captured against the candidate ref | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-F: `README.md` · `not a screen recording` (hero alt text and caption) · present · baseline `:4`, `:6` (non-authoritative) · evaluated `4c33f2f5` |
| **RULES-PASS(selected video host)** — the chosen host's own current rules permit this upload as specified | Executor (human, at execution time) | Executor chooses the host, then opens that host's first-party policy page at execution time and records the five fields below. **No repository file may be cited as evidence about a platform's rules.** | Recorded platform-rules row:<br>• **exact target**: UNDETERMINED — the video host has not been chosen; this lane must not name one<br>• **first-party rules / CONTRIBUTING URL**: UNFILLED<br>• **access date**: UNFILLED<br>• **relevant constraints found**: UNVERIFIED<br>• **PASS decision**: UNFILLED | Re-read on the day of execution | **BLOCKED — UNDETERMINED** — primary reason: no evidence has been recorded against a named launch candidate, and the target itself is not chosen in-cycle; all five record fields carry sentinels, which is this row's falsifiable evidence. **This placeholder row is replaced by a real per-target row once the host is chosen, before executing ③.** Context only: `policies/tool-policy.v1.json:111-120` + `hooks/lib/policy_registry.py:264` establish **only** why the research was not performed in-cycle and **nothing** about any platform's rules |

---

## ④ X thread

### Consumes / authors

- **Consumes**: the **③ GIFs (one per failure class)** — a *content* dependency, not a gate ·
  §5 G limitations post wording · §5 D adversarial-review gate content.
- **Authors here**: the opener (verbatim, below), the thread structure, the GIF-to-failure-class
  mapping, and the gate list.

### Copy

**Opening post — verbatim-required**, reproduced from
`design/turn-1-codex-capstone-review.md:356`:

> Your CLAUDE.md is not a security boundary. I built executable guardrails that intercept Claude Code before dangerous shell and git operations run.

**Thread constraint — recorded recommendation** attributed to the same source (`:358`), subject to
§5 G's wording, reproduced as that source line reads:

Follow with one GIF per failure class, one architecture image, the adversarial review gate and an explicit limitations post. Do not start with inventory counts.

### Content requirements

1. **Three distinct GIFs, one mapped to each named failure class** — a different asset per class,
   not one asset reused:

   | Failure class | Asset |
   |---|---|
   | protected-service kill | **GIF-1** (distinct) |
   | unauthorized push | **GIF-2** (distinct) |
   | QA rejection | **GIF-3** (distinct) |

2. **A dedicated limitations post** inside the thread — its own post, not a clause appended to
   another post. It is re-derived per §6.2 and carries the §7 finding in both directions.
3. Body copy is **DRAFT — awaiting §5 G pitch wording**.

### Hostile-commenter register

| What a hostile commenter will say | The honest answer |
|---|---|
| "'Not a security boundary' — but your own threat model says a gap is open." | §7 states the finding in both directions; D-PASS holds this channel until the residual class is closed by a regression test. |
| "One GIF proves nothing." | Three distinct GIFs, one per failure class, each traceable to a real run. |

### Gate table

| condition | owner lane | verification method | required evidence artifact | freshness requirement | status today |
|---|---|---|---|---|---|
| **A-PASS** — every Lane-A Must acceptance criterion passes for the named launch candidate, plus a fresh capability handshake bound to execution host + Claude Code build + settings hash + harness version | A (§5 A) | Executor reads the Lane-A acceptance evidence set for the named candidate and re-runs the handshake on the intended execution host | Lane-A acceptance evidence set + handshake record bound to the candidate ref — **UNFILLED** | Handshake re-run on the execution host within 24h of posting, same candidate ref | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-A: `scripts/doctor` · `# Usage: scripts/doctor [--venv <venv-dir>]` · absent-predicate (`--strict` absent file-wide) · baseline `:7-8` (non-authoritative) · evaluated `4c33f2f5` |
| **B-PASS** — all Lane-B Must criteria pass against the exact launch candidate: residue-blocking CI, dependency pinning, Actions pinning, unprivileged clean install, signed artifacts, checksums, SBOM, released-artifact verification | B (§5 B) | Executor reads the Lane-B evidence set and verifies the released artifact from the published checksums | Lane-B evidence set + signed artifacts + checksums + SBOM + released-artifact verification log — **UNFILLED** | Bound to the exact released candidate | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicators (corroborating, not proof) BI-B1: `PUBLIC-CORE.md` · the `settings.json` row classifying it `private-lab` · present · baseline `:130` (non-authoritative) · evaluated `4c33f2f5`; BI-B2: `README.md` · `badge/version-1.0.0-blue` · present · baseline `:11` (non-authoritative) · evaluated `4c33f2f5` |
| **D-PASS** — the threat model matches current behavioural evidence and the enforcement ledger; for RISK-3, a regression test proves the residual class of §7 closed | D (§5 D) | Executor reads the corrected threat-model section against the enforcement ledger and the regression test result for the candidate | Corrected threat-model section + passing regression test covering the §7 residual class — **UNFILLED** | Regression test run against the candidate ref; re-run if hook or classifier code changes | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-D: `docs/THREAT-MODEL.md` · `RISK-3 gap UNMITIGATED in interactive sessions` (quoted published wording, corrected in §7) · present · baseline `:112-117` (non-authoritative) · evaluated `4c33f2f5` |
| **E-PASS** — the canonical public name / CLI / framing is consistently present | E (§5 E) | Executor confirms the landed naming decision is applied consistently across the thread's copy and assets | Lane-E completion evidence for the candidate ref — **UNFILLED** | Bound to the candidate ref | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-E: `README.md` · `A Self-Governing Agent Operating System for Claude Code` · present · baseline `:1` (non-authoritative) · evaluated `4c33f2f5` |
| **F-PASS** — a reproducible demo satisfying action → block → reason → remedy → single-use-grant, under the `docs/demo-capture.md` provenance rules | F (§5 F) | Executor reproduces each GIF's underlying sequence from its trace artifact | Three reproducible demo assets + trace artifacts + provenance check results for the candidate ref — **UNFILLED** | Re-captured against the candidate ref | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-F: `README.md` · `not a screen recording` (hero alt text and caption) · present · baseline `:4`, `:6` (non-authoritative) · evaluated `4c33f2f5` |
| **G-PASS** — the approved pitch, audience and limitations contract exist | G (§5 G) | Executor confirms the approved pitch/audience/limitations contract is landed and that the dedicated limitations post derives from it | Lane-G pitch + audience + limitations contract for the candidate ref — **UNFILLED** | Bound to the candidate ref | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-G: `README.md` · `badge/subagents-`, `badge/lifecycle%20events-`, `badge/skills-` · present · baseline `:12-18` (non-authoritative) · evaluated `4c33f2f5` |
| **RULES-PASS(X)** — X's own current policy permits the thread as specified | Executor (human, at execution time) | Executor opens X's first-party policy page at execution time and records the five fields below. **No repository file may be cited as evidence about a platform's rules.** | Recorded platform-rules row:<br>• **exact target**: X — thread as specified (target fixed by the requirement); record UNVERIFIED in-cycle<br>• **first-party rules / CONTRIBUTING URL**: UNFILLED<br>• **access date**: UNFILLED<br>• **relevant constraints found**: UNVERIFIED<br>• **PASS decision**: UNFILLED | Re-read on the day of execution | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate; all five record fields carry sentinels, which is this row's falsifiable evidence. Context only: `policies/tool-policy.v1.json:111-120` + `hooks/lib/policy_registry.py:264` establish **only** why the research was not performed in-cycle and **nothing** about any platform's rules |

---

## ⑤ awesome-* lists

### Consumes / authors

- **Consumes**: §5 E name · §5 G pitch.
- **Authors here**: the category placement, the negative assertion, the target-list enumeration
  instruction, and the gate table.

### Copy

**Category placement — verbatim-required**, reproduced from
`design/turn-1-codex-capstone-review.md:362`:

Submit it under **Safety / Guardrails**, not “Claude configurations.”

**Listing copy — recorded recommendation** attributed to the same source (`:366`), subject to
§5 E's naming decision and §5 G's wording:

> Fail-closed Claude Code hook kernel with git privilege grants, protected-service guards and evidence-gated release workflows.

### Content requirements

1. **Positive placement**: every submission goes under **Safety / Guardrails**.
2. **Negative assertion**: the project is **not submitted under "Claude configurations"**. If a
   target list has no Safety / Guardrails-equivalent category, that is a blocking condition for
   that target, resolved by its own RULES-PASS row — not by falling back to a configurations
   category.
3. **This lane must not invent a target list.** The set of appropriate `awesome-*` lists is
   UNDETERMINED in-cycle (§14, OA-4).

### Hostile-commenter register

| What a hostile commenter will say | The honest answer |
|---|---|
| "This is a config collection, not a guardrail kernel." | The placement decision is exactly this argument; the listing copy leads with interception and evidence gating, not inventory. |

### Gate table

| condition | owner lane | verification method | required evidence artifact | freshness requirement | status today |
|---|---|---|---|---|---|
| **A-PASS** — every Lane-A Must acceptance criterion passes for the named launch candidate, plus a fresh capability handshake bound to execution host + Claude Code build + settings hash + harness version | A (§5 A) | Executor reads the Lane-A acceptance evidence set for the named candidate and re-runs the handshake on the intended execution host | Lane-A acceptance evidence set + handshake record bound to the candidate ref — **UNFILLED** | Handshake re-run on the execution host within 24h of submission, same candidate ref | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-A: `scripts/doctor` · `# Usage: scripts/doctor [--venv <venv-dir>]` · absent-predicate (`--strict` absent file-wide) · baseline `:7-8` (non-authoritative) · evaluated `4c33f2f5` |
| **B-PASS** — all Lane-B Must criteria pass against the exact launch candidate: residue-blocking CI, dependency pinning, Actions pinning, unprivileged clean install, signed artifacts, checksums, SBOM, released-artifact verification | B (§5 B) | Executor reads the Lane-B evidence set and verifies the released artifact from the published checksums | Lane-B evidence set + signed artifacts + checksums + SBOM + released-artifact verification log — **UNFILLED** | Bound to the exact released candidate | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicators (corroborating, not proof) BI-B1: `PUBLIC-CORE.md` · the `settings.json` row classifying it `private-lab` · present · baseline `:130` (non-authoritative) · evaluated `4c33f2f5`; BI-B2: `README.md` · `badge/version-1.0.0-blue` · present · baseline `:11` (non-authoritative) · evaluated `4c33f2f5` |
| **E-PASS** — the canonical public name / CLI / framing is consistently present | E (§5 E) | Executor confirms the landed naming decision is the name used in every listing entry | Lane-E completion evidence for the candidate ref — **UNFILLED** | Bound to the candidate ref; a listing submitted under a superseded name must be corrected | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-E: `README.md` · `A Self-Governing Agent Operating System for Claude Code` · present · baseline `:1` (non-authoritative) · evaluated `4c33f2f5` |
| **G-PASS** — the approved pitch, audience and limitations contract exist | G (§5 G) | Executor confirms the listing copy derives from the approved pitch rather than from inventory framing | Lane-G pitch + audience + limitations contract for the candidate ref — **UNFILLED** | Bound to the candidate ref | **BLOCKED** — primary reason: no evidence has been recorded against a named launch candidate. Indicator (corroborating, not proof) BI-G: `README.md` · `badge/subagents-`, `badge/lifecycle%20events-`, `badge/skills-` · present · baseline `:12-18` (non-authoritative) · evaluated `4c33f2f5` |
| **RULES-PASS(awesome-* target set)** — each target list's own CONTRIBUTING policy permits this submission under a Safety / Guardrails-equivalent category | Executor (human, at execution time) | Executor determines the target set, then opens each target's CONTRIBUTING policy at execution time and records the five fields below **per target**. **No repository file may be cited as evidence about a platform's rules.** | Recorded platform-rules row:<br>• **exact target**: UNDETERMINED — the `awesome-*` target set is not known; this lane must not invent one<br>• **first-party rules / CONTRIBUTING URL**: UNFILLED<br>• **access date**: UNFILLED<br>• **relevant constraints found**: UNVERIFIED<br>• **PASS decision**: UNFILLED | Re-read on the day of execution, per target | **BLOCKED — UNDETERMINED** — primary reason: no evidence has been recorded against a named launch candidate, and the target set itself is not determined in-cycle; all five record fields carry sentinels, which is this row's falsifiable evidence. **This placeholder row is replaced by one real per-target row per list, before executing ⑤.** Context only: `policies/tool-policy.v1.json:111-120` + `hooks/lib/policy_registry.py:264` establish **only** why the research was not performed in-cycle and **nothing** about any platform's rules |

---

## 13. Platform-rule row template and executor instructions

### 13.1 Row template — copy this for every new target

Each `RULES-PASS` row carries these **five fields**, nested as a labelled sub-list inside that
row's *required evidence artifact* cell. They are not extra table columns and not a separate
ledger. Each label appears **exactly once per row**, with a non-empty value.

```
• exact target:                          <platform + the specific submission form>
• first-party rules / CONTRIBUTING URL:  <URL read at execution time>
• access date:                           <YYYY-MM-DD the URL was read>
• relevant constraints found:            <the constraints that bear on this submission>
• PASS decision:                         <PASS or BLOCKED, with the reason>
```

The third field label is also written "first-party rules or CONTRIBUTING URL"; the two spellings
denote the same field.

### 13.2 Executor instructions

- **Before executing ⑤**: add **one row per `awesome-*` target**, replacing the placeholder row.
- **Before executing ③**: add **one row for the selected video host**, replacing the placeholder
  row.
- **Missing, ambiguous, or conflicting rules block that target.** A target whose rules cannot be
  read, or whose rules conflict, is BLOCKED — it is not waved through.
- **Both of those target sets are `UNDETERMINED` in-cycle.** This plan does not enumerate an
  `awesome-*` target list and does not name a video host, because neither is knowable at authoring
  time and a guessed list would rot.

### 13.3 Labelling requirement

**Every statement in this document about any platform's rules is `tier_3_unverified` and was not
verified in-cycle.** No repository file may be cited as evidence *about* a platform's rules. The
capability-denial citation (`policies/tool-policy.v1.json:111-120`, where the authoring role's
allowed-tool list contains no web-research capability, and `hooks/lib/policy_registry.py:264`,
which generates the corresponding deny string) establishes **only** why the research was not
performed here, and **nothing** about Hacker News, r/ClaudeAI, X, any `awesome-*` list, or any
video host.

---

## 14. Open assumptions — external dependencies

| # | Open assumption (external) | Status in-cycle | Who resolves it, and when |
|---|---|---|---|
| OA-1 | Hacker News Show HN submission rules permit this submission as specified | **UNVERIFIED** | Executor, at execution time, via RULES-PASS(Hacker News) |
| OA-2 | r/ClaudeAI rules permit a self-promotional technical post as specified | **UNVERIFIED** | Executor, via RULES-PASS(r/ClaudeAI) |
| OA-3 | X policy permits the thread as specified | **UNVERIFIED** | Executor, via RULES-PASS(X) |
| OA-4 | **Which** `awesome-*` lists are appropriate targets, and each one's CONTRIBUTING policy | **UNDETERMINED** — the target *set itself* is unknown | Executor, before ⑤; one row added **per** target |
| OA-5 | **Which** video host is used, and its policy | **UNDETERMINED** — an unmade decision | Executor, before ③; one row added once chosen |
| OA-6 | Platform rules are unchanged between this document's authoring date and the execution date | **CANNOT BE ASSUMED** | Executor re-reads at execution time; this is why no snapshot is embedded |

---

## 15. Authoring constraints this document was written under

- **No launch step was executed while authoring this plan.** No post, submission, upload, pull
  request, issue or outreach of any kind. Per §0.1, that statement is a report of what was done,
  not a claim that any artifact proves it.
- **No sibling-owned file was edited.** The files named in §5 are read-only inputs to this plan.
  Where an anchor has been changed or removed by the lane that owns it, §4.5 rule 7 forbids
  editing that file to restore the anchor.
- **Sibling deliverables are referenced by spec section** (`spec-20260719-163852.md` §5 A–G),
  never by a guessed ticket path or guessed wording.
- **Nothing was created under `scripts/`**, and nothing here is wired into CI.
- The three verbatim-required strings (① headline, ④ opener, ⑤ category label) were **copied from
  the source file lines**, not retyped; the source uses an en dash, an em dash, curly quotation
  marks and a typographic ellipsis, and an ASCII transliteration would be a defect.
