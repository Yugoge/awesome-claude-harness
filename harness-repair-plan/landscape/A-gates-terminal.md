# Cluster A-gates-terminal — complete inventory (A1, A2)

Repo: /home/user/awesome-claude-harness @ 09ab15b (read-only). Binding design:
docs/reference/close-commit-zero-failure-mechanism-20260928.md (§0 rulings, §1 G1-G5,
§2 accounting, §4 rollout S0-S12). Mode numbers: docs/reference/close-commit-failure-inventory-20260927.md
("close #N" / "commit #N"). All file:line below re-verified at HEAD 09ab15b unless marked.

Scratch experiments (copy of hooks/ + schemas/ under
landscape-work/A-gates-terminal/h, driver landscape-work/A-gates-terminal/exp/run.py,
HOME and project dir sandboxed, PYTHONDONTWRITEBYTECODE=1):

| id | scenario | result |
|---|---|---|
| E1 | G3 barrier, BARRIER=block, retry re-dispatch of a dev lane whose first attempt left no dev-report (same canonical path) | exit 2 `[artifact_missing] docs/dev/dev-report-<T>.json` -> retry blocked |
| E1b | same, current dispatch already present in transcript, nothing prior | exit 2 (if the harness writes the tool_use before PreToolUse, every first dispatch is blocked; timing unverified) |
| E2a | G1, GATE=block, obligation with profile "repair" (the barrier's only retry escape) | exit 2 reason=unknown_enum_value |
| E2b | G1, GATE=block, BA obligation exactly as commands/dev.md:510 describes (json entries without identity) | exit 2 reason=missing_field |
| E2c | G1, GATE=block, qa dispatch with NO obligation while `.claude/dev-registry/dev-<ts>/` exists | exit 0 (missing block passes) |
| E2d | G1, GATE=block, dispatched_at = 2001-01-01 | exit 0 (no 300 s bound) |
| E2e | G1, GATE=block, schema "ba-qa-report.v1" (unregistered) | exit 0 (no registry membership check) |
| E3 | G4 stop-obligation-gate, TERMINAL=block, obligated artifact missing, 5 consecutive Stops incl. stop_hook_active=true | [2,2,2,2,2] — unbounded |
| E3b | G4, obligated dispatch whose prompt has no `.claude/dev-registry/<x>/` reference | exit 0 (never checked) |

Prior evidence re-used (not re-run): runtime-verification.md:310 — schema-invalid dev-report at
producer stop: rc=0 with an obligation block, rc=2 without (advisory branch defect, A1.b).

---------------------------------------------------------------------------------------------------

## 0. Rollout status at HEAD (design §4)

| Step | Design content | State at 09ab15b | Evidence |
|---|---|---|---|
| S0 | canary on SubagentStop | not verified (out of cluster) | — |
| S1 | schemas dev-report.v2, qa-report.v2, changelog-status.v1, registry, do-report/context additive | DONE except: `ba-qa-report.v1` never created/registered (used by 3 templates); context.v1 lacks `spec_path_source` (additive, additionalProperties:true) | schemas/registry.json; schemas/context.v1.json props |
| S2 | obligation grammar lib | DONE (hooks/lib/obligation.py) but helpers `dispatch_clock_within_bound` (:584), `artifact_freshness_satisfied` (:605) have ZERO production callers | grep |
| S3 | G1 dispatch gate advisory | DONE as advisory; design checks 2-4 missing (A1.c) | hooks/pretool-obligation-gate.py |
| S4 | G2 producer-stop generalization | DONE as advisory; freshness, expected_absent, lane_set echo NOT verified; advisory branch skips legacy block (A1.b) | hooks/subagentstop-artifact-contract-enforce.py:797-1147 |
| S5 | templates carry obligations | MOSTLY DONE; defects A1.d; purity-hook redaction missing; overnight-init does not arm artifact-contract (scripts/overnight-init.sh:304-305) | — |
| S6 | producers emit v2 | DONE in templates (schema dev-report.v2 / qa-report.v2 with required_values) | commands/dev.md:874, :1023 |
| S7 | collection gates generalized | PARTIAL: G3 barrier added (advisory, retry-deadlock A1.e); canonical schema+identity+roster equality NOT built; gitignore profile exemption NOT built | hooks/pretool-aggregate-check.py:373-652; hooks/pretool-gitignore-preflight.py:717-818 |
| S8 | resolver dispositions, roster derivation, spec clause, forced/honest_blocked, flat output, replay fix, codex profile-awareness | NOT BUILT (no `disposition` anywhere in scripts/resolve-dev-artifact-chain.py); replay fix built differently and broken; codex-enforce unchanged | grep `disposition` = 0 hits |
| S9 | Stop recompute (advisory->block), loop-reset recompute, do-gate block + finalization | PARTIAL substitutes: stop-obligation-gate.py (json-only obligation re-check, unbounded, advisory), posttool-overnight-loop.py conditions (a)/(b) (advisory, unbounded), stop-do-report-gate.py block + pending->blocked rewrite (counter file, force-allow); no disposition | see A2-S9 |
| S10 | /close cutover | NOT DONE (all old checks present + new consumer-side routing machinery added) | commands/close.md |
| S11 | /commit cutover | NOT DONE (same) | commands/commit.md |
| S12 | deletions | NOT DONE | hooks/subagentstop-artifact-contract-enforce.py:1149-1244; hooks/subagentstop-e2e-enforce.py:406-422 |

---------------------------------------------------------------------------------------------------

## A1 — producer gates' four switches default advisory; advisory branch exits before the schema check

### A1.a  Every location of the four switches and their defaults

| Switch | File:line | What is there | Default | What is wrong |
|---|---|---|---|---|
| CLAUDE_OBLIGATION_GATE (G1) | hooks/pretool-obligation-gate.py:16 | docstring kill-switch semantics | — | — |
| | hooks/pretool-obligation-gate.py:69 | `SWITCH_ENV = "CLAUDE_OBLIGATION_GATE"` | — | design §1.3-G1 :184 names it `OBLIGATION_GATE_MODE` (name drift doc vs code) |
| | hooks/pretool-obligation-gate.py:150-151 | `off` -> exit 0 | — | — |
| | hooks/pretool-obligation-gate.py:155 | `mode = os.environ.get(SWITCH_ENV, "advisory")` | advisory | never armed anywhere |
| | hooks/pretool-obligation-gate.py:143-146 | advisory log, block -> exit 2 | — | only branch that can block |
| CLAUDE_OBLIGATION_STOPGATE (G2) | hooks/subagentstop-artifact-contract-enforce.py:799-801 | comment: different switch from ARTIFACT_CONTRACT_ENFORCE_MODE | — | — |
| | hooks/subagentstop-artifact-contract-enforce.py:802-804 | `os.environ.get("CLAUDE_OBLIGATION_STOPGATE", "advisory")`; unknown value -> advisory | advisory | never armed |
| | hooks/subagentstop-artifact-contract-enforce.py:1062-1068 | side records (escalations/deferrals) written only in block mode | — | — |
| | hooks/subagentstop-artifact-contract-enforce.py:1081-1083 | progress cleared only in block mode | — | — |
| | hooks/subagentstop-artifact-contract-enforce.py:1096-1121 | block -> `_gate_decide` -> exit 2 / escalation admission | — | — |
| | hooks/subagentstop-artifact-contract-enforce.py:1122-1123 | `# advisory mode: never blocks` `sys.exit(0)` | — | THE DEFECT (A1.b) |
| CLAUDE_OBLIGATION_BARRIER (G3) | hooks/pretool-aggregate-check.py:383 | `OBLIGATION_BARRIER_ENV` | — | — |
| | hooks/pretool-aggregate-check.py:607-609 | `get(OBLIGATION_BARRIER_ENV, "advisory")`; off -> return | advisory | never armed |
| | hooks/pretool-aggregate-check.py:638-650 | block -> exit 2 else advisory log | — | retry deadlock if armed (A1.e) |
| CLAUDE_OBLIGATION_TERMINAL (G4) | hooks/stop-obligation-gate.py:15 | docstring "advisory (default, unset)" | — | — |
| | hooks/stop-obligation-gate.py:104-106 | default advisory; off -> 0 | advisory | never armed |
| | hooks/stop-obligation-gate.py:138-145 | advisory log / block exit 2 | — | unbounded block (E3) — must NOT be armed before A2-S9 |
| | hooks/posttool-overnight-loop.py:275 | same switch governs overnight loop-reset conditions | advisory | never armed |
| | hooks/posttool-overnight-loop.py:285-292 | block -> writes `terminal_gate_blocked_reason`, no reset, exit 0 | — | no max_retries bound (A2-S9) |

Same-family switches with OTHER defaults (context, not part of the four):
- ARTIFACT_CONTRACT_ENFORCE_MODE — hooks/subagentstop-artifact-contract-enforce.py:1208, default **block** (legacy correlation path).
- DO_REPORT_GATE_MODE — hooks/stop-do-report-gate.py:193, default **block** (docstring :12; contradicted by commands/do.md:53 "advisory (default)").
- CLAUDE_COMPLETION_GATE_MODE — hooks/stop-completion-gate.py:521, default **block**.
- CP_ENFORCE_MODE — hooks/subagentstop-cp-enforce.py:44, default advisory (spec checkpoints; not in the design, out of A1).

Settings (where arming would live):
- settings.json:3-31 `env` — 0 occurrences of any CLAUDE_OBLIGATION_* key (verified by JSON parse).
- settings.template.json:3-30 `env` — 0 occurrences.
- settings.json registers the gates: :603 aggregate-check, :611 pretool-obligation-gate, :694 posttool-overnight-loop, :827 stop-do-report-gate, :835 stop-obligation-gate, :843 stop-completion-gate, :904 subagentstop-artifact-contract-enforce.
- settings.template.json (the PUBLISHED source of truth) registers only :578 aggregate-check and :652 posttool-overnight-loop; it does NOT register pretool-obligation-gate (Agent group ends :582), subagentstop-artifact-contract-enforce (SubagentStop :781-), stop-obligation-gate / stop-do-report-gate / stop-completion-gate (Stop :759-779). A user installing from the template gets neither G1, G2 nor G4 at all, armed or not (overlaps C2).

Prompts / docs that state the advisory default as intended (must change when arming):
- commands/close.md:567 (last sentence) — "...does not require flipping either `CLAUDE_OBLIGATION_GATE` or `CLAUDE_OBLIGATION_STOPGATE` out of their advisory-first defaults." — the orchestrator-side inspector re-validation was added precisely because G1/G2 are advisory.
- docs/reference/qa-status-gate-gap-orchestrator-side-20261005.md:69, :90 — records the gap and proposes `CLAUDE_OBLIGATION_GATE=block`.
- commands/do.md:53 — says do-report gate default advisory (code default block).
- docs/reference/close-commit-zero-failure-mechanism-20260928.md:184 (`OBLIGATION_GATE_MODE`), :216 (`ARTIFACT_CONTRACT_ENFORCE_MODE (existing, :282)` — the design assumed G2 shares the existing default-block switch; implementation introduced a new advisory switch instead).

Tests that pin switch behaviour (all set/pop env explicitly; arming via settings env does not break them):
- hooks/tests/test_obligation_gate.py:55-57, :256
- hooks/tests/test_artifact_contract_enforce.py:138-143, :707-730 (advisory never blocks), :734-747, :789, :941-978, :1269-1290, :1384, :1414, :1520
- hooks/tests/test_stop_obligation_gate.py:30-32, :203
- hooks/tests/test_posttool_overnight_loop_terminal_gate.py:30-32
- tests/test_aggregate_dev_report.py:2336-2673 (barrier block/advisory/off)
- tests/test_overnight_loop_tz.py:134, :160
- Stray copy: .scratch_subagentstop_ancestor.txt:56-516 (untracked scratch duplicate of the hook; E1 cluster).

### A1.b  The exact advisory branch that skips the schema check

hooks/subagentstop-artifact-contract-enforce.py `main()`:
- :797-805 obligation mode runs first whenever STOPGATE != off.
- :810-816 `resolve_own_obligation(...)` with `expected_role` taken from the registry entry's agent_type (:794-795), not from the CLI payload's agent_type (A4 overlap).
- :817-1123 `if isinstance(resolution, obligation.Resolved)` block: verifies json/markdown/response_line/response_block kinds, consistency, downstream wires.
- :1078-1083 all checks pass -> `sys.exit(0)` (correct per design: obligation supersedes legacy).
- :1084-1095 failures -> advisory record `obligation_verify_fail`.
- :1096-1121 block mode -> exit 2 / escalation.
- **:1122-1123 advisory mode with failures -> `sys.exit(0)`**. Control never reaches the legacy path :1149-1244 whose own default (:1208 `ARTIFACT_CONTRACT_ENFORCE_MODE`, default "block") would have blocked a versioned-but-schema-invalid report (:1200-1244). Net effect: the documented path (dispatch WITH an obligation block, as every template requires) is weaker than the undocumented path (no block) — runtime-verification.md:310: rc=0 with obligation, rc=2 without.
- :1124-1136 Unresolvable / NoObligationInPrompt fall through to legacy (fine).
- :1137-1147 obligation-mode exception falls through to legacy (fine).
- Docstring :21-25 still says "A MISSING report is NOT blocked here" — false for the obligation path in block mode (missing is blocking, contract_runtime.validate_artifact_for_obligation absent file -> fail, hooks/lib/contract_runtime.py:872-874).

Fix: replace the `sys.exit(0)` at :1123 with fall-through to :1149 (advisory obligation mode must never disable the default-on legacy block); update docstring :21-25. Re-check tests :707-730, :941-978, :1269-1290 (their setups have no versioned-invalid correlated report, expected to stay rc 0).

### A1.c  G1 dispatch gate — design checks missing (what block mode would and would not catch)

hooks/pretool-obligation-gate.py:
- :70-76 `PRODUCER_ROLES` = ba, dev, qa, test-writer, changelog-analyst, style/cleanliness/prompt-inspector. `graphify` and `spec` are in the grammar's ROLES (hooks/lib/obligation.py:74-80) but not gated (their outputs are null-degrading enrichment; acceptable, see A1 coverage table).
- :86-87, :137-140 NoBlock is gated on `.claude/dev-registry/<payload session_id>/` existing. Registries are minted as `dev-<ts>` / `dev-command-<ts>` (hooks/prompt-workflow.py:1462-1481), the payload session_id is the Claude session UUID -> the directory never exists -> a producer dispatch with NO obligation passes even in block mode (E2c). Design §1.3-G1 check 1: trigger is the producer set "UNCONDITIONALLY" because marker-sniffing is unsound.
- :134 `parse_obligation(..., known_schema_ids=None)` -> registry membership of schema ids is never checked (design check 2); unregistered `ba-qa-report.v1` passes G1 (E2e) and then G2 returns `skip` (hooks/subagentstop-artifact-contract-enforce.py:845-855) = silent non-enforcement.
- no call to `obligation.dispatch_clock_within_bound` (hooks/lib/obligation.py:584-602; zero callers) -> design check 2 "|dispatched_at − now| ≤ 300 s" absent (E2d); G2 freshness (`artifact_freshness_satisfied` :605-631, zero callers) is therefore also unanchored.
- no profile-context matrix (design check 3): commit-qa task_id null legality is "undischarged" (hooks/lib/obligation.py:144-146 `UNDISCHARGED_TASK_ID_NULL`, zero callers); ad_hoc for qa/changelog-analyst not fail-closed.
- no fan-out consistency (design check 4) — `lane_sets_identical` used only by hooks/posttool-lane-completeness-watch.py:183.

### A1.d  Obligation coverage per pipeline/producer (which producers carry blocks, which lack them)

| Pipeline | Producer dispatch site | Obligation? | Defect at that site |
|---|---|---|---|
| /dev | BA — commands/dev.md:427-460 (worked example :442-458) | yes | ok (identity present) |
| /dev | BA clarification re-dispatch — commands/dev.md:510 | yes (prose) | json entries listed WITHOUT `identity` (required for kind json, hooks/lib/obligation.py:106) -> G1 block rejects (E2b) |
| /dev | QA ba_validation — commands/dev.md:625/:635 | yes | schema `ba-qa-report.v1` unregistered (no schemas/ba-qa-report.v1.json; artifact is real: commands/dev.md:694, scripts/dev-lifecycle.py:162) -> G2 skip |
| /dev | BA iteration — commands/dev.md:733/:743 | yes | same identity omission as :510 |
| /dev | graphify — commands/dev.md:787 | NO | not gated; enrichment only (no change required by the design) |
| /dev | test-writer — commands/dev.md:825 | yes | ok |
| /dev | dev — commands/dev.md:874 | yes | `required_values {"dev.status":["completed"]}` (A1.f) |
| /dev | QA final — commands/dev.md:1023 | yes | `required_values {"qa.status":["pass"]}` (A1.f) |
| /dev | Step 16 retry -> "Return to Step 10" commands/dev.md:1263 | inherits :874 | retry re-declares same canonical path (correct per §1.2 retry rule) but G3 blocks it (A1.e) |
| /dev fan-out | lane variant prose commands/dev.md:460 | yes (lane, lane_set, fanout-lane) | ok |
| /redev | commands/redev.md (reuses /dev templates) | yes | obligations claim `pipeline:"dev"`, design value is "redev"; harmless (no code branches on pipeline — grep) |
| /dev-command | BA — commands/dev-command.md:333-347 | yes | ok |
| /dev-command | BA re-dispatch — :394, :556 | yes | identity omitted (as dev.md:510) |
| /dev-command | QA ba_validation — :454/:460 | yes | `ba-qa-report.v1` unregistered |
| /dev-command | dev — :607 | yes | required_values completed only |
| /dev-command | QA — :665 | yes | required_values pass only |
| /dev-command fan-out | :54 says fan-out mirrors /dev; worked example :336-337 lane/lane_set null; no lane variant prose | partial | lane obligations not described (falls back to dev.md text) |
| /dev-overnight | BA — commands/dev-overnight.md:971-993 (worked example :978) | yes | ok |
| /dev-overnight | QA ba_validation — :1089/:1095 | yes | `ba-qa-report.v1` unregistered |
| /dev-overnight | BA — :1191/:1197 | yes | identity omitted |
| /dev-overnight | graphify — :1252 | NO | enrichment only |
| /dev-overnight | dev — :1283/:1289; iteration :1504 | yes | required_values completed only |
| /dev-overnight | QA — :1384/:1390; iteration :1506 | yes | required_values pass only |
| /dev-overnight | specialist — :633 `Agent(subagent_type: specialist.type)` | NO | specialist roles not producers (ok) |
| /do | no producer dispatch (pretool-do-block-subagents blocks Agent during /do); producer = hook-written skeleton hooks/prompt-workflow.py:1365-1399 (`_write_do_report_skeleton`) + main agent | n/a | skeleton `expected_absent` holds kind names (:1388 "qa-report", ...) not paths as design §1.2 defines; consumed only by hooks/subagentstop-e2e-enforce.py:166-209 |
| /close | style/cleanliness/prompt inspectors — commands/close.md:553-555 (sequential), :559-561 (parallel) | yes | profile "singular" (no close profile in design matrix; harmless) |
| /close | close-QA — commands/close.md:599-607 | yes (markdown + response_line + consistency, G5) | always `final_verification`; /do path should be `do-close` (design §1.5.6) |
| /commit | planning changelog-analyst DRYRUN — commands/commit.md:483 ("same prompt as Step 7") | yes (inherits :611-628) | ok |
| /commit | commit-QA — commands/commit.md:491, block :501-517 | yes (markdown + response_line) | design specified response_line only; markdown added (fine) |
| /commit | changelog-analyst — commands/commit.md:591, block :611-628 | yes (response_block changelog-status.v1) | ok |
| /spec | spec subagent — commands/spec.md:297-313, :377-395 | NO | no subagent_type (blocked by other gates, out of cluster); "spec" not a PIPELINES value (hooks/lib/obligation.py:81-83) — /spec is outside the design's five pipelines (§0 ruling 4: mechanism must not depend on spec) |
| /spec | QA split validation — commands/spec.md:316-330 | NO | qa is a producer role; passes today only because G1's NoBlock gate is dead (A1.c); after the A1.c trigger fix it must either carry an `ad_hoc` obligation or be outside the transcript-derived pipeline context (decision D-A1-2) |
| close/commit repair engine | scripts/close-commit-repair-orchestrate.py | — | zero callers (close.md:288 "There is no repair engine"); its `profile:"repair"` is consumed by hooks/pretool-aggregate-check.py:387,:616 and hooks/pretool-do-block-subagents.py:76,:118 but rejected by G1 (E2a) — dead producer/consumer pair (D1/D2) |

Other S5 template gaps:
- hooks/pretool-orchestrator-prompt-purity.py — no `<obligation>` redaction (0 hits for "obligation"); design §1.2 coexistence; cosmetic (warn-only hook).
- scripts/overnight-init.sh:304-305 arms `e2e` (+codex) only; design S5 says arm artifact-contract too. Moot once STOPGATE=block (obligation path does not need the flag) and once S12 deletes the legacy path.

### A1.e  G3 barrier retry deadlock (must be fixed before BARRIER=block)

hooks/pretool-aggregate-check.py `_run_obligation_barrier` :597-652:
- :617-627 scans the transcript for ALL prior obligations with the same task-id prefix (`_scan_transcript_for_prior_obligations` :427-488).
- :629-650 verifies every prior json/markdown artifact; any missing one -> exit 2 to the orchestrator.
- No exclusion of artifacts the CURRENT dispatch re-declares -> a retry of a producer whose first attempt died without writing its report is blocked (E1). The only escape is `profile == "repair"` (:387, :616), which G1 rejects (E2a) and which no template emits. Design §1.2 retry rule: "a retry dispatch re-declares the SAME canonical artifact paths as the original lane".
- If the harness records the tool_use before PreToolUse fires, the current dispatch itself is scanned as "prior" and every first dispatch is blocked (E1b; timing unverified). The same fix covers it.

Fix: in `_run_obligation_barrier`, compute the current obligation's artifact path set and skip prior entries whose `path` is in it; delete the REPAIR_PROFILE bypass (:387, :616) — and its twin hooks/pretool-do-block-subagents.py:76, :101-118 — because the retry rule supersedes it.

### A1.f  required_values vs the design's honest terminals (blocks arming STOPGATE=block)

- commands/dev.md:874, commands/dev-command.md:607, commands/dev-overnight.md:1289, :1504 — dev `required_values {"dev.status":["completed"]}` "blocked/needs_review is not an acceptable hand-back" (R10).
- commands/dev.md:1023, commands/dev-command.md:665, commands/dev-overnight.md:1390, :1506 — QA `required_values {"qa.status":["pass"]}`.
- agents/dev.md:41, agents/qa.md:193 — the same R10 rule in the agents.
- Design §1.3-G2: "Honest terminals (blocked / needs_review with schema-valid rationale) PASS this gate; their chain-level meaning is G4's disposition"; §1.4.2.
- Consequence once STOPGATE=block: a QA that finds a defect cannot stop with `fail` except via the escalation path (plain block -> no_progress -> escalation record -> ESCALATION_ACK nonce line -> admitted; hooks/subagentstop-artifact-contract-enforce.py:690-772) — three stops per legitimate FAIL; escalation records land in `.claude/dev-registry/<bare task_id>/escalations/` (`_cycle_id` :295-309) while registries are `dev-<ts>` and stop-completion-gate scans `dev-<task>/` (B1 overlap). Also G4 (stop-obligation-gate, find_unresolved_dispatch_obligations hooks/lib/obligation.py:1002-1020) reports every required_values violation -> an honestly blocked cycle can never end (E3).
- `TERMINAL_VOCABULARY` hooks/lib/obligation.py:129-137 already holds the full legal sets.

Fix (decision D-A1-1): widen to the terminal vocabulary — QA `{"qa.status":["pass","warning","fail"]}`, dev `{"dev.status":["completed","blocked","needs_review"]}` — in the 8 template lines + agents/dev.md:41, agents/qa.md:193; the "pass/completed" requirement moves to the G4 disposition (A2-S8/S9), where /dev Step 16 (commands/dev.md:1179-1276) already loops on QA FAIL.

### A1 fix order (producer-side only)
1. A1.b fall-through (1 line + docstring).
2. A1.e barrier retry rule.
3. A1.d template identity fixes (5 lines) + schemas/ba-qa-report.v1.json + registry entry.
4. A1.f required_values widening (decision).
5. A1.c G1: transcript-derived pipeline context replaces the dead dev-registry gate; pass known_schema_ids from schemas/registry.json; call dispatch_clock_within_bound.
6. Arm: settings.template.json + settings.json `env`: CLAUDE_OBLIGATION_GATE=block, CLAUDE_OBLIGATION_STOPGATE=block, CLAUDE_OBLIGATION_BARRIER=block; register G1/G2/G4 hooks in settings.template.json; leave CLAUDE_OBLIGATION_TERMINAL=advisory until A2-S9. Remove the advisory sentence at commands/close.md:567 and fix commands/do.md:53.

---------------------------------------------------------------------------------------------------

## A2 — terminal disposition (S8/S9) not built; /close, /commit not cut over (S10/S11); old checks not deleted (S12)

### A2.1  What exists today in place of G4 (three partial, mutually inconsistent terminal truths)

| Piece | File:line | Behaviour | Gap vs design G4 |
|---|---|---|---|
| G4 obligation re-check (Stop) | hooks/stop-obligation-gate.py:103-145 + hooks/lib/obligation.py:900-1021 | re-validates json-kind obligated artifacts (schema + required_values) of dispatches whose prompt contains `.claude/dev-registry/<token>/` with an existing dir (:960-968); markdown/response kinds skipped (:979-981) | no disposition; no resolver chain checks; selector depends on registry marker (E3b) instead of "EVERY task_id appearing in an obligation block"; no bound (E3); advisory |
| Completion gate (Stop) | hooks/stop-completion-gate.py:405-505, :211-250 | runs the resolver but blocks only the sole-missing-completion signature (:229-250); loads resolver from `project_dir/scripts` (:218) -> FileNotFoundError in product repos; durable state + arbitration file (:44-49) | B1 cluster; duplicates G4 terminal duty; exempts /close,/commit sessions (:63-65, :85) while stop-obligation-gate removed that exemption (:24-32) — contradiction |
| Overnight loop-reset anchor | hooks/posttool-overnight-loop.py:202-222 (conditions), :245-296 (main) | condition (a) unresolved obligations (same lib scan), condition (b) dev.status not in {completed, blocked} (:32, :186-199) | no disposition / check-overnight-reports summary; no max_retries bound (schemas/cycle-contract.v1.json:106 exists); advisory; B2 overlap |
| /do anchor | hooks/stop-do-report-gate.py:192-271 | block default; after MAX_BLOCKS=2 (:57) force-allow (:240-256) with pending->blocked rewrite only for status "pending" (:172-189); counter file `/tmp/claude-do-report-gate-<sid>.json` (:150-169) | malformed/truncated reports force-allowed unfinalized; counter is a new mutable state file (ruling 3); B4 cluster |
| Dev prose postconditions | commands/dev.md:1386-1391, commands/dev-command.md:941-945 | resolver must pass before completion | relative `scripts/...` path fails outside the harness repo (C1); dev-overnight has none |

### A2-S7  Collection gates — files/functions

- hooks/pretool-aggregate-check.py
  - `main()` :655-711 legacy QA-only barrier: `_extract_current_task_ids` :247-266 returns None -> global scan (`_collect_violations` :356-369 / `_find_violations` :284-300) even when the dispatch carries an obligation with task_id -> close #139 / commit #261 orphan-shard blocks survive. Change: when the prompt carries an obligation, scope = `_normalize_task_id_prefix(obligation.task_id)` (:269-282), never global.
  - existence-only canonical check (`_find_violations` :295-299: ≥2 shards and no canonical). Change: canonical must exist + parse + `contract_runtime.validate_artifact_for_obligation(canonical, "dev-report.v2")` + identity, and roster equality: canonical `parallel_workers` == union of shard `lane_set`s == current obligation `lane_set`.
  - `_run_obligation_barrier` :597-652 retry rule (A1.e).
- hooks/pretool-gitignore-preflight.py `main()` :717-818 — add obligation-profile exemption for profiles {commit-qa, commit-landing, do-close, final_verification} (parse with hooks/lib/obligation.parse_obligation), equivalent to the E5 grant exemption at :652-699 / :810. Removes commit #260, close #122/#140 from the close/commit surface.
- Deletable at /close,/commit after S7: commit #260, #261; close #139.

### A2-S8  Resolver dispositions — files/functions

- scripts/resolve-dev-artifact-chain.py
  - `_base_result` :1290-1340 — add `disposition` (chain_pass | honest_blocked | forced | incomplete) and `evidence[]`.
  - `resolve_chain` :1773-2259 — final status block :2221-2259: derive disposition: `chain_pass` iff status in {pass, pass_with_exceptions} (existing :2238-2243 contract); `honest_blocked` iff canonical dev-report parses, identity-valid, `dev.status` in {blocked, needs_review} (+ rationale) — downstream MISSING_ARTIFACT errors ignored; `forced` iff close-report last non-empty line matches `^CLOSE: YES( —|-)? ?\(?FORCED\)?` (classification only — /close --force is a deprecated no-op, commands/close.md:77-94; hooks/lib/close-verdict.py:37-49 maps FORCED to "yes" so the resolver needs its own regex); `incomplete` otherwise with evidence = errors[].
  - do-report branch (new, inside resolve_chain): no canonical dev-report and `docs/dev/do-report-<T>.json` with `source=="do"` -> completed => chain_pass, blocked => honest_blocked, pending/malformed => incomplete. Subsumes commands/close.md:410-419 (close #101-#106) and commands/commit.md:324-330 selection.
  - shard-roster derivation: read `lane_set` from every v2 shard; divergent echoes -> incomplete naming both rosters; roster lane with no shard / shard outside roster -> incomplete. Extend the existing LANE_SET_MISMATCH site (:1936).
  - spec clause: context `spec_path` with `spec_path_source=="explicit"` must resolve (reuse scripts/resolve-spec-artifacts.py pure logic); `auto` -> null-degrading advisory, never incomplete.
  - `main()` :2262-2284 — add `--disposition` flag printing one flat JSON line; exit 0 whenever a disposition was computed; non-zero only for instrument failure (operation state). Keep the default mode's exit semantics unchanged because existing consumers depend on exit 2 on fail: commands/dev.md:1386, commands/dev-command.md:941, scripts/close-route-select.py, commands/commit.md:334, hooks/stop-completion-gate.py:419-421, hooks/subagentstop-artifact-contract-enforce.py:498-533 (`_wire_qa_chain`).
- tests/test_resolve_dev_artifact_chain.py — add disposition cases (singular, fan-out roster, honest_blocked, forced legacy line, do-report, spec explicit/auto).
- hooks/prompt-workflow.py replay fix: built differently and broken — `_ordinary_dev_start` :1833-1858 replays until `_dev_report_reached_terminal(prior_task_id)` (:1787-1800), but prior_task_id is the registry id `dev-<ts>` (:1877, :1912-1917; minted :1462-1481) and the check reads `docs/dev/dev-report-dev-<ts>.json`, a name /dev never writes -> identical bare /redev replays forever. Design §1.5.3: 60-second window keyed on the replay record's own creation time -> replace the terminal check with `replay_path.stat().st_mtime` age < 60 s.
- hooks/subagentstop-codex-enforce.py :60-99 — obligation-profile awareness: resolve own obligation (hooks/lib/obligation.resolve_own_obligation) and skip when the stopping agent's obligation `pipeline` is close/commit while `codex-enforce.json` (:76-84) was armed by the dev cycle (close #146).
- Deletable after S8: none yet (enables S10/S11).

### A2-S9  Terminal anchors — files/functions

- hooks/stop-obligation-gate.py (extend instead of creating the design's hooks/stop-devcycle-recompute.py — it is already registered as G4 at settings.json:835 and owns the transcript selector): `_find_unresolved` :81-84 -> for every task_id appearing in an obligation block with pipeline in {dev, redev, dev-command, dev-overnight} in this transcript, call the resolver's disposition (import from `Path(__file__).parent.parent/"scripts"`, never project_dir); block only `incomplete`; bound counted from the transcript's own recorded Stop-hook block events (stateless; M19), beyond the bound -> advisory + allow (honest incomplete). close/commit pipeline obligations stay G2-only (a /close of a broken cycle must be able to stop and report).
- hooks/lib/obligation.py:900-1021 `find_unresolved_dispatch_obligations` — drop the dev-registry-token prefilter (:960-968) in favour of the obligation's own task_id (selector rule), or add a sibling `obligated_task_ids(transcript)`.
- hooks/stop-completion-gate.py — its resolver duty (sole-missing-completion :229-250) is subsumed: a missing completion is `incomplete`. Fold or retire (decision D-A2-3; B1 owns its bugs).
- hooks/posttool-overnight-loop.py `_terminal_gate_block_reason` :202-222 -> per-pipeline disposition (+ scripts/check-overnight-reports.py summary); `main()` :274-296 (inside main :245) -> on `incomplete` print repair instructions instead of reset, bounded by the cycle-contract `max_retries` (schemas/cycle-contract.v1.json:106); expiry precedence :264-267 unchanged (B2 overlap).
- hooks/stop-do-report-gate.py :239-256 -> finalize ANY non-compliant report (not only "pending", :182) to `do.status="blocked"` + explanatory summary; derive the bound from the transcript instead of the counter file :150-169 (B4 owns).
- settings.json:835 / settings.template.json Stop :759 — arm CLAUDE_OBLIGATION_TERMINAL=block only after the bound exists.
- Deletable after S9: close #195 becomes producer-guaranteed.

### A2-S10  /close cutover — what commands/close.md must lose (every remaining class-b/c/d/e check, mapped)

Design buckets (§2): P producer gate, O orchestrator gate, R recompute relocation / deleted, S operation-state stall, A legal class-a, X adjacent workstream (stays), G residual.

| close.md line(s) | Check / mechanism today | Inventory # (class) | Bucket | S10-S12 action |
|---|---|---|---|---|
| :4 | disable-model-invocation (+ settings deny) | #1 (e) | X | keep |
| :55-75 | `--auto` illegal combinations (dev-lifecycle validate_auto_flag_combination) | #2, #3, #4 (e) | X | keep |
| :29-30, :77-94, :115 | `--force` (now deprecated no-op; :29-30 still calls it "a fallback for work with no do-report", contradicting :77-94) | #8, #9, #10 (e/c) moot | X | keep; fix the :29-30 contradiction (D4) |
| :101 | explicit path does not exist -> awaiting-input | #6 (e) | X | keep |
| :109-114, :122 | do-report precedence / source=="do" routing into /dev chain | #106 (b) | P | replaced by disposition do-report branch (S8) |
| :117-127 | no task-id -> awaiting-input | #7 (e) | X | keep |
| :136 | `--late-repair` + `--force` usage error | #5 (e) | X | keep |
| :131-144, :140, :344 (`LATE_REPAIR_SELECTOR_ARGS`) | late-repair route (controller init/record-stage/finalize/verify-disclosure) | #78-#100 (b/c/d/e) | R | S12 route retirement — HELD (user decision: no retirement); stays flag-gated |
| :146-242 | Routing helpers (close_artifact_role, close_required_action, close_route_finding, close_progress, close_awaiting_input) | post-inventory consumer-side repair of class-b findings | — | delete every class-b call site (rows below); keep only for QA class-a findings (decision D-A2-2) |
| :244-274, :585-597 | QA-arming rule: write-qa-mode.sh / write-e2e-enforce.sh / write-enforce-flag.sh with environment-wait + arbitration | #129-#138 (d/e/b) | R | delete (design G5: obligation presence replaces flag-file arming); keep `SESSION_ID="dev-${TASK_ID}"` :582 for the FIRST ACTION fail-open agent-index channel |
| :276-280 | mapping rows / source_check list / awaiting cause set (closed i-iii) | — | — | trim source_check list; add cause (iv) per D-A2-2 |
| :282-321 | Routing loop (dispatch producer from /close, R15 progress, arbitration) | post-inventory | — | only class-a uses survive |
| :334-343 | Step 0 aggregate writer `cd "$PROJECT_ROOT" && python3 scripts/aggregate-dev-report.py` (relative; finding on failure :342) | #11 (d), #12 (e), #13-#33 | #11,12,25,28,29,30,32,33 R; #13,15,21,23,24,26,27 O; #14,16,17,19,20,22 P; #18 A; #31 X | delete invocation (aggregation is a dev-side producer duty; G3+G4 guarantee the canonical) |
| :344-349 | `python3 scripts/close-route-select.py` (cwd-relative) + `jq` extraction | #34 (d), #35 (d), #36 (d) | #34, #36 S; #35 R | replace with one absolute-path disposition call; jq dependency gone |
| :351-364 | resolver-error routing (each errors[] -> close_route_finding) | #37-#77 | #37,38,61-64,67-75,77 R; #39-47,49-55,57,58,76 P; #48,65,66 S; #56,59,60 A | delete; disposition `incomplete` evidence replaces |
| :366-408 | fixed entrypoint, status pass/pass_with_exceptions requirement, singular/fan-out rules, "aggregate writer is the sole permitted close-time repair" | #37-#77, #75 | as above | replace with disposition consumption; keep the path fields (report_paths, lanes, commit_whitelist_artifacts, qa_inputs, disclosed_exceptions) as disposition output |
| :410-419 | do-report lite preflight (task_id, source, status completed, files_modified array) + dev re-dispatch from /close | #101, #102, #103, #105 (b); #104 (a) | #101-103,105 P; #104 A | delete (disposition do-report branch + stop-do-report-gate) |
| :421-432 | normal-path artifact preflight prose | (restates #37-#77) | R | delete |
| :434-491 | Artifact schema gate (inline python validate_report_artifact over report_paths; FAIL -> producer re-dispatch :472-480) | #107, #108, #109 (b); #110, #111 (d) | #107-109 P; #110,111 R | delete (G2 with obligation schema authority) |
| :493-527 | cp-state handoff via resolve-spec-artifacts.py; failure -> close_route_finding :516 | #112-#120 (b/c/d/e) | R | demote to advisory (no finding), per design "RSA advisory" |
| :536-544 | cycle-diff file list (Irregular path git diff) | — | — | keep |
| :546-549 | parallel detection from ARTIFACT_CHAIN.mode | — | — | read from disposition output |
| :565 | inspector transient retry (≤3) | #124 (d) | X | keep |
| :567 | orchestrator re-validates each inspector report (validate_artifact_for_obligation) + re-dispatch, "does not require flipping ... advisory-first defaults" | post-inventory class-b at /close (violates C2) | P (G2 at inspector stop) | delete once STOPGATE=block |
| :599-607 | close-QA dispatch with obligation (G5) — triggers hooks #139 (aggregate-check), #140 (gitignore), #141-#146 (e2e / artifact-contract / codex), #147-#152 | #139 O; #140 X; #141-146 P; #147-152 X | | #139 by S7, #141/#146 by S5/S8, rest by G2; add `do-close` profile for /do |
| :603 | SECOND ACTION cp-state checkpoints | #149 (b, ADV) | X | keep |
| :616-634 | QA inputs = full ARTIFACT_CHAIN JSON | — | — | pass disposition + paths |
| :650 | WI bullet 1 downstream consumability | #154 (b) | R | rewrite to cite disposition chain_pass |
| :651 | WI bullet 2 task-id chain consistency | #155 (b) | R | same |
| :652-656 | WI bullet 3 pre-existing defect | #156 (a) | A | keep |
| :658 | WI bullet 4(i) /commit consumability | #157 (b) | R | same as bullet 1 |
| :659 | WI bullet 4(ii) push permission | #158 (d) | X | keep |
| :660 | WI bullet 4(iii) commit-channel bypass | #159 (a) | A | keep |
| :668 | QA must report a still-missing inspector report as a finding | post-inventory class-b | P | delete with :567 |
| :677-698 | AC-2.6 inspector NEW-violation routing | #166 (a) | A | keep |
| :724-729 | branch 2(d) AC deviation collapse | #161 (a) | A | keep |
| :731 | branch 3 codex dissent | #153 (a) | A | keep |
| :735 | branch 5 QA dissent | #160 (a) | A | keep |
| :739-744 | branch 7 failed_parse dissent / attestation missing | #162 (a), #163 (b) | #162 A; #163 P | keep #162; #163 enforced at QA stop (G2 markdown) |
| :746 | branch 8 ambiguity | #164 (d/e) | X | keep |
| :756-760 | branch 10 disclosed-exception corroboration | #165 (a/c) | X | keep |
| :773, :782-788 | terminal-line contract (last line must be legal; `unknown` fails closed); :787 still lists `CLOSE: YES (FORCED)` although --force is a no-op | #168 (b) | P | G2 terminal_line_regex already enforces; FORCED line kept for legacy (D4 note) |
| :775-780 | close-report-append helper `$PROJECT_ROOT/scripts/close-report-append.py` | #169-#184 (d/e/b), #185 (e) | #173,174 P; rest X | keep (own workstream) |
| :803-845 | Step 3 scoring (close-scoring-decide, score-update) | #186-#188 | X | keep |
| :807-811 | qa_ever_rejected from ARTIFACT_CHAIN.qa_inputs | — | — | read from disposition paths |
| :933-998 | `--auto` batch walk | #196-#198 (d/e) | X | keep |

Close-side S10 net: delete :244-274, :334-364 (replace with one disposition call + OPERATION_STALLED branch), :410-432, :434-491, :567 sentence + check, :585-597 arming, :668 clause; demote :516; rewrite :650, :651, :658; trim :146-321 to class-a call sites.

### A2-S11  /commit cutover — every remaining class-b/c/d/e check in commands/commit.md, mapped

| commit.md line(s) | Check / mechanism today | Inventory # (class) | Bucket | S11/S12 action |
|---|---|---|---|---|
| :41-51 | `--auto` combination | #1, #2, #3 (e) | X | keep |
| :53-78 | task-id inference / ambiguity -> awaiting | #4, #5 (e) | X | keep |
| :80-178 | Artifact-to-role routing + dispatch-and-recheck loop + R15 | post-inventory consumer-side repair | — | strip class-b call sites |
| :193 | resolve-close-report.sh | (#6 source) | | keep |
| :204-207 | check 1 close-report exists — routed to orchestrator row (path=$TASK_ID) | #6 (b) | G | becomes AWAITING_INPUT "run /close first" (the one legal sequencing verdict); no dispatch |
| :208-218 | check 2 last line CLOSE: YES — routed to qa (close-report row): /commit re-dispatches close-QA | #7 (a) | A | keep the check; replace the qa re-dispatch with a not-landed class-a stop naming /close (D-A2-2) |
| :211 | accepted variant `CLOSE: YES — FORCED` (not a close.md :783-787 legal form) | — | | D4 note |
| :219-228 | dry-run relaxation of check 2 | (#7) | A | keep |
| :229 | check 3 mtime >24 h advisory | #9 (d, ADV) = close #199 | X | keep |
| :230-233 | check 4 filename task-id == argument — routed | #8 (e/b) | R | delete (disposition is task-scoped) |
| :247-249 | bulk capability sentinel absent -> awaiting | #10 (d) | X | keep |
| :250-265, :353-360 | resolve-commit-repos.py plan + until-loop (route_finding) | #53-#77 | #53,54,63,66-69,73-75 X; #55 G; #56 O; #57-59,61,62,64,65,70-72 P (G2 `_wire_trial_plan` already runs build_plan at dev stop, hooks/subagentstop-artifact-contract-enforce.py:390-413, :562); #60 R; #76 S; #77 R | keep RCR call (X workstream); drop the route_finding loop for P-modes |
| :267-286, :331-339 | resolver chain re-check (`python3 scripts/resolve-dev-artifact-chain.py`, relative :334) with until-loop | #23-#52 (+ #77 relative path) | #23,24,25,38-42,45-51 R; #26,28-32,34,35,52 P; #27,43,44 S; #33,36,37 A | replace with one disposition call (absolute path), retry once -> OPERATION_STALLED |
| :295-300 | CONTROL_ROOT / NESTED_REPO / TASK_DOCS_ROOT derivation | #54, #63 (d) | X | keep |
| :301-323 (relative `source venv/bin/activate && python3 scripts/late-repair-controller.py` :313, :320) | late-repair tri-state guard State C loop | #11-#22 (b/c) | R | S12 HELD (no retirement); flag-gate |
| :324-330 | TASK_REPORT selection (effective / dev / do fallback) | #55 (b), #136 | G | take report path from disposition |
| :340-344 | FANOUT detection from ARTIFACT_CHAIN.mode | — | | from disposition |
| :363-388 | attribution-log slice (advisory) | — | | keep |
| :401-432 | manifest-first + mint precondition (commit_pipeline.verify_pipeline_dispatch: manifest, report_sha256, close-report existence) | #82, #83 (d) + post-inventory grant checks | X (grant/landing workstream) | keep |
| :434-446 | per-repo grant, captured repo/branch/HEAD mismatch, no session id | #78, #81 (d/c) | X | keep |
| :454-467 | grant timestamp format | #250, #251 (d) | X | keep |
| :486 | dry-run nothing_to_commit | #84 (e) | X | keep |
| :501-517 | commit-QA obligation (G5) | — | | keep |
| :534-543 | QA rejection rules 1-4 | #85-#88 (c / half a) | X | keep |
| :545-556 | codex sub-round | #89, #90 (c/d) | X | keep |
| :574-578 | REJECT verdict routing, unstage (`git rm --cached` unborn) | #85-#88, #93 (d) | X | keep |
| :580-583 | file cross-check missing_file / line_mismatch (+ fresh QA re-dispatch) | post-inventory class-b at /commit | P (G2 markdown + response_line at commit-QA stop) | delete once STOPGATE=block |
| :585 | --dry-run end state | #92 (e) | X | keep |
| :587 | unparseable / missing COMMIT line -> fresh QA | #91 (d) | X -> P | delete branch once G2 response_line blocks |
| :678-681 | result roots/order != plan | #94 (c) | X | keep |
| :685-688 | committed needs terminal entries per repo | #95 (c) | X | keep |
| :690-700 | partially_committed | #96 (d) | X | keep |
| :702-713 | nothing_to_commit / reconciliation declined | #97 (b, ADV), #98 (c) | X | keep |
| :715-803 | push_gate_reconciled verification | #98, #99 (c) | X | keep |
| :810-832 | retryable grant codes | #100 (d) | X | keep |
| :834-849 | non-retryable codes | #101 | X | keep |
| :851-854 | status unknown/unparseable -> re-dispatch analyst | #102 (d) | P | delete (G2 response_block changelog-status.v1 returns it to the analyst at ITS stop) |
| :906-911 | Step 8 unlinked spec(s) routed to ba under R15 after the commit | #103, #104 (b) | R | demote to advisory print, no route |
| :943 | spec-update dispatch failure | #105 (d) | X | keep |
| :981-1002 | `--auto` hook_deny / partial abort | #106, #107 (d) | X | keep |
| (new) Step 3 | forced echo `disposition: forced (mechanically unverifiable — confirm you ran /close --force for this task)` | design §1.4.4 | — | add (1 line) |

Changelog-analyst side (agents/changelog-analyst.md, consumes ARTIFACT_CHAIN): :126, :161-192 Phase-1 chain checks = commit #120-#124, #126 (R), :344 do-report path, #137 (R via resolve-dev-report.py) — read disposition output instead; :268-280 whitelist from commit_whitelist_artifacts (keep as disposition field).

### A2-S12  Deletions/retirements behind green gates

- hooks/subagentstop-artifact-contract-enforce.py :1149-1244 legacy correlation path, `_find_correlated_reports` :182-262, `REPORT_PREFIX_BY_AGENT_TYPE` :115-118, `_forced_close_flag_present` :340-348 (forced-close flag has no legitimate writer), docstring :1-91 — after STOPGATE=block soak (design: G2 subsumes the timestamp-substring heuristics).
- hooks/subagentstop-e2e-enforce.py :406-422 missing-report guess-block (`_find_latest_qa_report` correlation :95-163) and force-sentinel skip :384-393 (pattern at :387) — keep the e2e content check :212-268 reading the obligation-named report (make `_enforce_e2e_via_obligation` :271-333 primary, not the fallback :348-355).
- enforce-flag writers at close: commands/close.md:244-250 (S10). Dev-side artifact-contract flag writers hooks/prompt-workflow.py:1593-1606, commands/dev.md:192, :215, commands/dev-command.md:137, :160 lose their only consumer — but hooks/stop-completion-gate.py `_SENTINEL_FILENAMES` (:86) bridges sessions via artifact-contract-enforce.json / e2e-enforce.json, so retire only after B1 moves the bridge to e2e-enforce.json.
- Late-repair route (scripts/late-repair-controller.py, scripts/close-route-select.py, scripts/check-late-repair-provenance.py; close.md:131-144; commit.md:301-323): design retires it flag-gated "until the forced-admission dependency lands"; user decision "no feature retired (hold)" -> keep, flag-gated, not deleted.
- Dead pair (not in the design, found here): scripts/close-commit-repair-orchestrate.py (zero callers) + REPAIR_PROFILE consumers hooks/pretool-aggregate-check.py:387,:616, hooks/pretool-do-block-subagents.py:76,:118 (A1.e removes the consumers; the script itself is D1/E1 territory).

### A2 constraints / cross-cluster dependencies

- Order (design §4): S7 -> S8 -> S9 -> S10/S11 -> S12; A1 arming (G1/G2/G3) before S10/S11 deletions (M34: never delete consumer checks before the producer gate is live).
- D3 identity split: hook-minted id `dev-<ts>` (hooks/prompt-workflow.py:1469) vs artifact task_id `<ts>` (dev.md templates) breaks `_dev_report_reached_terminal`, G2 `_cycle_id` escalation dir, completion-gate stripping (B1). The disposition keys on the obligation's own task_id and is unaffected.
- B1 (completion gate), B2 (overnight loop/closeout), B4 (do gate) own the bug fixes in their hooks; S9 only adds the disposition call/bound.
- C2: settings.template.json lacks the gate registrations; arming must land in the template.

---------------------------------------------------------------------------------------------------

## User decisions surfaced (minimal set)

- D-A1-1 (A1.f): widen QA/dev `required_values` to the terminal vocabulary (design honest terminals) instead of R10's pass/completed-only. Recommended yes; otherwise STOPGATE/TERMINAL block mode traps legitimate QA FAIL and honestly blocked cycles.
- D-A1-2 (A1.c): G1 trigger = transcript-derived pipeline context (latest slash command ∈ dev/redev/dev-command/dev-overnight/close/commit) instead of the design's literal "unconditional" — keeps /spec's QA dispatch (commands/spec.md:316-330) and free-form producer dispatches working without ad_hoc blocks. Recommended.
- D-A2-2 (S10/S11): what /close and /commit print for disposition `incomplete`/`honest_blocked`. Design says "CLOSE: NO, class-a + resume route"; today's close.md forbids CLOSE: NO and routes findings back to producers. Recommended: a not-landed `AWAITING_INPUT` line with new cause (iv) "the dev cycle itself failed — resume via /redev <task> or /restart" (no producer dispatch from /close or /commit); keep the routing loop only for QA class-a findings.
- D-A2-3 (S9): fold stop-completion-gate's resolver duty into the disposition-based G4 Stop hook (one terminal truth) vs keep both hooks.
- Held by existing decision: late-repair route stays (S12 portion deferred).
