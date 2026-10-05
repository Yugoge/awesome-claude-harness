# Close/commit zero-failure mechanism — converged design (2026-09-28/29)

Status: adversarially debated design, pre-implementation. Repository under design:
/dev/shm/dev-workspace/dot-claude (working tree of 2026-09-28, uncommitted modifications
included — every file:line citation below refers to that tree and was verified there by the
design driver). Companion inventory: docs/reference/close-commit-failure-inventory-20260927.md
(199 close + 275 commit = 474 counted failure modes). Debate: iterated adversarial review with
the external Codex reasoning model (gpt-5.6-sol, xhigh) — §5.

## 0. Binding rulings and hard acceptance criteria

User rulings (in order):
1. 2026-09-27 — /close and /commit may only detect "the development cycle itself failed"
   (class a). Every artifact-missing/schema (b), file-content/hash/ownership (c),
   environment/grant/lock (d), input/precondition (e) failure at close/commit is a defect; the
   guarantee must be established during /dev, /do, /redev, /dev-command, /dev-overnight.
2. 2026-09-28 am — artifact-missing detection belongs on the PRODUCER of each artifact (at the
   moment it finishes) and on the ORCHESTRATOR (at dispatch and collection points).
3. 2026-09-28 pm — the enforcement primitive is hooks; new mutable state files are themselves
   new failure surface; cross-event state via new files: zero.
4. 2026-09-28 — cycles frequently start WITHOUT a spec (bare /dev on free text is the common
   case); the mechanism must not depend on spec presence and must cover every entry variation;
   no new bugs are acceptable.

Hard acceptance criteria (all five hold in this design; proofs in §3):
C1 zero new mutable state files (repo-versioned schemas/hooks and the harness-owned transcript
   are not mutable state; existing hook-authored files may be extended, not multiplied);
C2 zero new class-(b)/(c) checks at /close or /commit;
C3 strict global failure-surface decrease vs the 474-mode inventory;
C4 the design survives an adversarial pre-mortem run with the inventory's own methodology
   BEFORE implementation (§3 register, debated in rounds R4-R7);
C5 house rules: a blocking gate returns the artifact to its own producer; hook rejections are
   PAUSE-and-report for subagents; no new human-in-the-loop steps on the default success path;
   legitimate output always retains a route to completion ("free landing"); commits land only
   via /commit's changelog-analyst.

## 1. The mechanism

### 1.1 State channels (C1: zero new mutable files)

(a) **The dispatch prompt payload** — visible to PreToolUse Agent-matcher hooks
    (payload: session_id, transcript_path, tool_input.subagent_type, tool_input.prompt; the
    transcript_path channel is production-read at hooks/pretool-workflow-gate.py:224).
(b) **The harness-owned transcript store** (append-only, harness-keyed):
    - parent transcript `<root>/<slug>/<session_id>.jsonl` records every Agent dispatch as an
      assistant tool_use block with the full input.prompt (empirically verified: 22 dispatches
      with prompts in a live parent transcript);
    - per-subagent transcript `<root>/<slug>/<session_id>/subagents/agent-<agent_id>.jsonl`,
      whose FIRST record is the verbatim dispatch prompt, plus `agent-<agent_id>.meta.json`
      carrying `toolUseId` (empirically verified on live files);
    - production precedent for all of it: hooks/lib/subagent_restart.py `_read_parent_calls`
      (:295-358), `_metadata_by_tool_use` (:361-385), agent-transcript path construction
      (:498-500), multi-account roots (:537-559), split-store limitation measured and
      documented (:574-635, esp. :587-594);
    - "transcript_path is AUTHORITATIVE" precedent: hooks/prompt-workflow.py:801-833;
    - SubagentStop payload carries agent_id (verified live via
      ~/.claude/logs/artifact-contract-advisory.jsonl records and
      subagentstop-artifact-contract-enforce.py:217); `last_assistant_message` and
      `agent_transcript_path` are accepted defensively by production code when the host
      supplies them (subagent_restart.py:883-886, :902-904) — their availability is a
      measured rollout input (step S0), not an assumption.
(c) **Existing hook-authored files, extended not multiplied**: dev-registry sentinels +
    agent-index (hooks/pretool-cp-checkin.py:46-48; hooks/lib/agent_resolver.py:173-197,
    fail-open LOW-10 contract :17-21); the /do report skeleton (prompt-workflow.py:1360-1392,
    O_EXCL); the user-requirement doc (prompt-workflow.py:1567-1569, O_EXCL); the advisory
    JSONL logs; the overnight cycle-contract (schemas/cycle-contract.v1.json:67-119);
    the dev-start replay store (.claude/dev-start-replays/).
(d) **Repo-versioned schema files** — immutable per release.
(e) **The fan-out roster is disk-persisted inside existing artifacts**: v2 lane dev-reports
    carry a schema-REQUIRED `lane_set` field echoed from the dispatch obligation, so the
    intended roster lives in the shards themselves — no transcript or canonical is a single
    point of roster truth.

Explicitly rejected under ruling 3: obligations.json ledgers, lane sentinels, chain receipts,
terminal-receipt files (the architect's ledger design and the external round-1 receipt design)
— replaced by obligations-in-prompt + pure recomputation.

### 1.2 Obligation-block grammar v1 (versioned)

Exactly one block per producer dispatch:

```
<obligation v="1">
{
  "task_id": "20260928-153000",            // null legal only for ad_hoc / commit-bulk /
                                           // commit-qa-in-bulk-context
  "lane": "b" | null,
  "lane_set": ["a","b","c"] | null,        // fan-out only: FULL intended roster, identical in
                                           // every lane dispatch; lane must be a member
  "role": "ba"|"dev"|"qa"|"graphify"|"spec"|"test-writer"|"changelog-analyst",
  "pipeline": "dev"|"redev"|"dev-command"|"dev-overnight"|"do"|"close"|"commit",
  "profile": "singular"|"fanout-lane"|"ba_validation"|"final_verification"|"overnight"
           |"do-close"|"commit-qa"|"commit-landing"|"commit-bulk"|"ad_hoc",
  "dispatched_at": "2026-09-28T15:30:05Z", // bounded by the dispatch gate's own clock
  "artifacts": [
    {"kind":"json", "path":"docs/dev/dev-report-20260928-153000-b.json",
     "schema":"dev-report.v2",
     "identity":{"task_id":"20260928-153000-b","request_id":"20260928-153000-b"}},
    {"kind":"markdown", "path":"docs/dev/close-report-20260928-153000.md",
     "identity_anchor":"20260928-153000",
     "terminal_line_regex":"<verdict-class rule, §1.4.5>",
     "waived_by_response":"^CLOSE_REPORT_APPEND_(ERROR|CRITICAL): "},
    {"kind":"response_block","begin":"--- CHANGELOG-ANALYST-STATUS-BEGIN ---",
     "end":"--- CHANGELOG-ANALYST-STATUS-END ---","format":"json",
     "schema":"changelog-status.v1"},
    {"kind":"response_line","terminal_line_regex":"^COMMIT: (APPROVE|REJECT)"}
  ],
  "consistency": "verdict_class",          // optional, close-QA bundle: file and response
                                           // verdict classes must agree
  "expected_absent": ["docs/dev/qa-report-20260928-153000.json"]
}
</obligation>
```

Field semantics:
- **Artifact kinds**: `json` — Draft7 against the OBLIGATION's schema id via the existing
  engine (hooks/lib/contract_runtime.py validate_report_artifact machinery :515-558; authority
  from the obligation, never from the artifact's self-declared report_version, so the measured
  665-report unversioned legacy corpus is never retro-rejected — the version-gated skip
  semantics :440-458, :547-551 are preserved for all non-obligated reads). `markdown` —
  exists, non-empty, contains identity_anchor, last non-empty line satisfies the terminal
  rule. `response_block` — sentinel-delimited block in the SubagentStop payload's
  last_assistant_message (or the agent's own transcript tail), parsed per `format`, validated
  against a repo-versioned schema (changelog-status.v1 encodes the full existing contract:
  commit_status enum, repository_results[] with per-repo terminal fields and
  status-conditional requirements — agents/changelog-analyst.md:1872-1935, consumed at
  commands/commit.md:419-432). `response_line` — last non-empty line of the response matches
  the rule (the actual commit-QA contract, commands/commit.md:349-355).
- **Freshness (per kind)**: json — file mtime ≥ dispatched_at − 2s AND the report's
  schema-required internal `timestamp` ≥ dispatched_at; markdown — mtime ≥ dispatched_at − 2s;
  response kinds — none (inherently produced by this run). The 2s covers filesystem timestamp
  granularity only: dispatch gate and producers share one host clock. The dispatch gate bounds
  |dispatched_at − gate-now| ≤ 300s, so a producer can never be handed an artificially old
  timestamp. Deliberate forgery of the internal timestamp is the pre-existing report-content
  trust boundary (pre-mortem M39), not a new surface.
- **Retry rule**: a retry dispatch re-declares the SAME canonical artifact paths as the
  original lane. Iteration reports (`dev-report-iter<N>-*`, an optional archival convention
  with explicitly no promotion barrier, commands/dev.md:1221-1230) never appear in
  obligations; freshness then forces the retry to REWRITE the canonical lane report, and the
  terminal STALE_CANONICAL / STALE_FILE_UNION recompute (resolve-dev-artifact-chain.py
  :1543-1563) forces re-aggregation.
- **lane_set echo**: fan-out producers copy lane_set verbatim into their v2 report
  (schema-required when lane != null); the producer-stop gate verifies the echo.
- **expected_absent**: paths that must NOT exist at the producer's stop (the /do profile's
  declaration that no qa-report/dev-report/ticket/context/completion will ever exist).

**Coexistence with the prompt-purity gate** (the required argument): the gate is warn-only by
policy — it never blocks (hooks/pretool-orchestrator-prompt-purity.py:23 "Always exit 0",
:340-349 `_route_hit` returns 0 unconditionally), so coexistence cannot fail hard even with
zero changes; the obligation block declares WHAT (paths, schema ids, identity), never HOW (no
tool names, no shell syntax — JSON in an XML wrapper matches none of the gate's four blacklist
categories except incidental token collisions); and the implementation adds
`<obligation ...>...</obligation>` to the gate's pre-scan redaction list exactly as it already
redacts `<options>` blocks (OPTIONS_XML_BLOCK_RE, :168-171) and dev-registry heredocs
(:158-162), removing even the cosmetic warning.

### 1.3 Hook-by-hook validation flows

#### G1 — Dispatch gate: `hooks/pretool-obligation-gate.py` (NEW code file), PreToolUse, Agent matcher

Payload used: tool_name, tool_input.subagent_type, tool_input.prompt, session_id,
transcript_path. Checks (stateless plus read-only transcript reads):
1. Trigger: subagent_type ∈ producer set — UNCONDITIONALLY (commit-QA dispatch prompts carry
   no registry FIRST-ACTION marker, commands/commit.md:300-355, so marker-sniffing is not a
   sound trigger). Non-producer types pass untouched.
2. Exactly one well-formed obligation: grammar-valid; schema ids registered
   (schemas/registry.json); repo-relative traversal-free paths; task_id shape;
   |dispatched_at − now| ≤ 300s.
3. Profile-context matrix (transcript-derived from the session's own command records):
   changelog-analyst → commit-landing/commit-bulk only, never ad_hoc (it is "dispatched
   exclusively by /commit", agents/changelog-analyst.md:2-10); qa in a /commit context →
   commit-qa (task_id required unless the context shows --bulk, which dispatches QA with no
   TASK_ID, commands/commit.md:22-24, :51-75); qa in a /close context → final_verification or
   do-close. **ad_hoc (or any empty-artifacts obligation) for qa/changelog-analyst is
   fail-closed under unknown context**: legal only when the context positively resolves to a
   non-close/commit command; unreadable transcript ⇒ reject, orchestrator re-dispatches with
   an explicit profile (bounded, no producer harmed).
4. Fan-out consistency (per task_id): every previously dispatched obligation in this
   transcript for this task_id declares the IDENTICAL lane_set; lane ∈ lane_set; a
   re-dispatched lane (retry) must re-declare the same artifact paths. Transcript unreadable ⇒
   this sub-check skipped with an advisory record (the roster stays safe via the disk-side
   lane_set echo, §1.4.2); checks 1-3's payload-only parts still enforced.
Failure = exit 2 to the ORCHESTRATOR (it repairs its own dispatch — C5-compatible: no producer
context is ever lost at dispatch time). Kill switch: OBLIGATION_GATE_MODE=advisory|block|off;
armed per-pipeline during rollout. Fail-open wrapper on unexpected exceptions (pattern:
subagentstop-artifact-contract-enforce.py:321-328).

#### G2 — Producer-stop gate: generalized `hooks/subagentstop-artifact-contract-enforce.py`, SubagentStop

Payload used: agent_id (:217), session_id, and when supplied last_assistant_message /
agent_transcript_path. Obligation resolution ladder (deterministic; every degrade writes an
advisory record to the existing ~/.claude/logs/artifact-contract-advisory.jsonl):
- L0: payload agent_transcript_path (production-precedent field, subagent_restart.py:902-904)
  → first record's prompt → obligation block.
- L1: session-scoped path `<root>/<slug>/<payload.session_id>/subagents/agent-<agent_id>.jsonl`
  across account roots (subagent_restart.py:537-559). Session scoping kills the observed
  cross-session agent-id reuse (agent_resolver.py:23-29); multiple roots holding the path are
  split views of the SAME child (measured, subagent_restart.py:587-594) — accept any copy
  whose first record is a user message containing a well-formed obligation whose role matches;
  cross-check meta.json toolUseId. For close/commit-internal producers this resolves inside
  the LIVE session's own actively-written store (L1′), so reaching L3 for them requires
  harness self-corruption while running — the irreducible in-harness floor, pre-existing.
- L2 (degraded, logged): today's enforce-flag + correlation heuristic — never worse than the
  status quo.
- L3: advisory record ("obligation_unresolvable") and allow — a hook infra failure must never
  trap a producer (C5); the pipeline-terminal recompute (G4/G5) is the backstop.
Validation: per-kind checks + freshness + lane_set echo + expected_absent + the close-QA
bundle rules (verdict-class response validation via the close-verdict classifier — yes/no or
append-sentinel, never `unknown`; cross-channel verdict-class consistency; sentinel waiver of
the file obligation — §1.4.5). Failure = exit 2: the producer repairs its OWN artifact with
full context intact; missing is blocking (the obligation names the exact path — a certainty,
not a correlation guess). Honest terminals (blocked / needs_review with schema-valid
rationale) PASS this gate; their chain-level meaning is G4's disposition. Profile-driven
exemptions replace today's sentinel-sniffing (ba_validation :251-254, force-close :248-249,
and the --codex residue close #146 via an obligation-profile-aware
subagentstop-codex-enforce.py). Kill switch: ARTIFACT_CONTRACT_ENFORCE_MODE (existing, :282).
This gate SUBSUMES and retires the timestamp-substring correlation heuristics of both stop
hooks (artifact-contract :147-209 — whose own docstring admits per-lane attribution is
"structurally unavailable" :160-166 — and subagentstop-e2e-enforce's missing-report guess-block
:228-234); the e2e content check (:238-280) remains, reading the obligation-named report.

#### G3 — Collection gates (PreToolUse barriers), generalized existing hooks

- `hooks/pretool-aggregate-check.py`: from existence-only (:347-381) to
  exists+parses+schema+identity for the canonical aggregate, PLUS roster equality — canonical
  parallel_workers == the union of shard-recorded lane_sets == the current dispatch's
  obligation lane_set. obligation.task_id is the scope anchor: with an obligation present the
  hook NEVER falls back to its global scan (:455-472), eliminating the unrelated-orphan-shard
  blocks (close #139, commit #261).
- `hooks/pretool-gitignore-preflight.py`: obligation-profile-scoped exemption (equivalent to
  its live commit-grant E5 exemption) for {commit-qa, commit-landing, do-close,
  final_verification}, eliminating commit #260 and close #122/#140 as close/commit surface
  while keeping the guard for dev-side producers.
- Overnight: the cycle-contract dispatch gate (hooks/pretool-subagent-enforce.py:290-311) and
  collection gate (hooks/posttool-overnight-file-check.py:342-369) remain; G2 fires FIRST
  (repair lands on the live producer, fixing the PostToolUse-only repair-by-orchestrator
  violation); scripts/overnight-init.sh additionally arms the artifact-contract flag
  (today arms only e2e/codex, :303-305).

#### G4 — Terminal recompute with dispositions (Stop hook; the disposition is also what /close//commit consume)

`scripts/resolve-dev-artifact-chain.py` extended as a pure function of two read-only inputs —
the on-disk artifact set and (dev-side only) the session transcript's obligation records.
Existing check set retained: nested dev/qa validation (:250-300), identity (:214-248), worker
set (:1394-1414, :1455-1469), lane paths (:1476-1522), read-only aggregate rebuild + staleness
(:1524-1563), singular ambiguity (:1565-1592). Additions:
- roster derivation from shard-recorded lane_sets (identical across shards; divergence names
  both rosters); a lane in the roster with no shard, or a shard outside it ⇒ `incomplete`;
- spec binding: when a consumed context declares a non-null spec_path with
  spec_path_source=explicit, it must resolve (the pure logic of
  scripts/resolve-spec-artifacts.py); auto-detected specs are null-degrading enrichment
  (§1.5.1) and never render a cycle incomplete;
- **disposition** output: `chain_pass` (status pass / pass_with_exceptions, the existing
  :1349 contract) | `honest_blocked` (canonical dev-report or do-report exists, parses,
  identity-valid, status blocked or needs_review+rationale; downstream artifacts NOT required)
  | `forced` (close-report last non-empty line is the legal `CLOSE: YES (FORCED)` form,
  commands/close.md's enumerated verdict list) | `incomplete` (everything else, with
  evidence[]).

**Consumption contract**: /close and /commit each make ONE disposition call.
`chain_pass` → proceed. `honest_blocked` → CLOSE: NO, class-a, quoting the producer's own
rationale. `incomplete` → CLOSE: NO, class-a — the load-bearing semantic argument: ruling 1
defines class-a as "the development cycle itself failed"; a cycle whose orchestrator died
before completion, or that exhausted its bounded Stop attempts, IS a failed cycle; /close
reports that single fact with the disposition's evidence attached and names the resume route
(/redev, or /restart for quota-interrupted children). No per-artifact class-b error ever
surfaces as a close failure — the b-facts live inside the disposition's evidence payload for
the repair route. `forced` → the hand-edit path (§1.4.4). **Instrument-failure rule**: the
disposition invocation's OWN runtime failures (entrypoint missing, module import — the
resolver imports the aggregator module, :138-144, :1416-1453; unreadable artifact/dir IO;
unhandled exception; timeout) are retryable OPERATION STATES: retry once, then report
`OPERATION_STALLED: <instrument> <error>` and stop WITHOUT a verdict — never CLOSE: NO
(pure/idempotent recompute makes retry always safe). Consumption is single-invocation with
flat output — no secondary parser (deletes the jq dependency, close #35).

Terminal anchors per pipeline (gate rule: block only `incomplete`; bounded; then honest
class-a):

| Pipeline | Anchor | Notes |
|---|---|---|
| /dev, /redev | existing prose postcondition (commands/dev.md:1336-1362) + NEW Stop-hook recompute `hooks/stop-devcycle-recompute.py` | selector: EVERY task_id appearing in an obligation block in this session's transcript (cheap substring prefilter precedent subagent_restart.py:408-411); per-task bounded blocking, the bound counted from the transcript's own recorded hook-block events — stateless; beyond the bound: advisory + honest `incomplete` |
| /dev-command | the SAME Stop-hook recompute — today it has NO tail at all (commands/dev-command.md:911-925) | command-agnostic coverage is what makes spec-absent and multi-cycle sessions safe |
| /dev-overnight | loop-reset gate in hooks/posttool-overnight-loop.py — today it resets the cycle on all-todos-complete with NO artifact condition (:138-163) | recompute (per-pipeline dispositions + scripts/check-overnight-reports.py summary :136-149) runs BEFORE `_update_state_cycle`; on failure print repair instructions INSTEAD of the reset, bounded by max_retries; the EXPIRY path keeps precedence (:157-160 `_mark_session_complete` first) — the gate conditions CYCLE RESET only, never session termination; the pre-existing timelock closeout surface (hooks/stop-overnight-timelock.py:132-154) is untouched |
| /do | hooks/stop-do-report-gate.py flips to block mode; the force-allow escape (:54) is replaced by hook-side finalization of its OWN skeleton to do.status="blocked" + explanatory summary (extending the prompt-workflow.py:1360-1392 hook-authored file) — an honest class-a terminal instead of a guarantee hole; unwritable-docs/dev last resort stays force-allow + advisory |
| /close, /commit | disposition consumption only (above) | task-scoped /commit only; /commit --bulk is task-less by design and exempt (its producers still carry response obligations; its admission authority remains the human-minted bulk sentinel) |

#### G5 — close/commit-internal producers (all become obligated)

- close-QA (dispatched at commands/close.md:441+): markdown close-report obligation
  (identity anchor + verdict-class terminal line) AND a response_line obligation — the two
  final-line contracts are DISTINCT channels ("Two distinct final-line contracts",
  close.md:625-640) — with: verdict-class validation via hooks/lib/close-verdict.py (yes/no or
  append-sentinel family `^CLOSE_REPORT_APPEND_(ERROR|CRITICAL): `; `unknown` such as
  "CLOSE: MAYBE" blocks); cross-channel verdict-class consistency (file NO + response YES
  blocks the producer; the file remains downstream authority, close.md:625-631, and /commit's
  file-based admission commit.md:92-101 can no longer disagree with the /close echo); sentinel
  waiver — an append-sentinel response waives the file obligation, because a failed append
  leaves the report untouched by design (scripts/close-report-append.py:570-616; the CRITICAL
  form :81-102) and the sentinel is the legal honest terminal (close.md:610-617); the
  append-failure family (#169-184) remains its own workstream's surface.
- commit-QA (commands/commit.md:300): response_line `^COMMIT: (APPROVE|REJECT)`.
- changelog-analyst (commands/commit.md:372+): response_block against changelog-status.v1 —
  a structurally unusable payload is returned to the analyst at ITS stop, not to /commit
  (dissolving the "unparseable ⇒ manual intervention" branch, commit #102).
- /close Step 2's registry-arming block (close.md:429-436, `|| exit 1` — close modes
  #129-138) is DELETED at cutover; obligation presence replaces flag-file arming. The
  FIRST-ACTION sentinel read survives only as the fail-open agent-index channel for
  tool-policy role resolution (LOW-10).

### 1.4 Cross-cutting design elements

1. **Roster invariant chain (fan-out; close needs NO transcript)**: (i) chain_pass requires
   every lane's passing QA report; (ii) lane-QA dispatches are blocked unless the canonical
   aggregate already exists once ≥2 shards are on disk (EXISTING behavior,
   pretool-aggregate-check.py:347-381); (iii) the generalized G3 additionally requires
   canonical parallel_workers == the dispatch obligation's lane_set (carried redundantly in
   every dispatch — one obligation suffices, no cross-session transcript needed);
   (iv) every v2 shard records lane_set, so the disposition call derives the roster from the
   shards themselves — a dev session that died mid-fan-out leaves shards naming the missing
   lane; (v) a dev session that died before ANY canonical existed cannot have produced the
   lane-QA reports. Residual: an orchestrator that never DECLARES a requirement's lane at all
   is requirement-decomposition fidelity — LLM judgment above any mechanical roster, judged by
   the close QA debate (class-a by definition).
2. **Honest terminals**: producer schemas keep blocked/needs_review legal (dev-report v2
   carries the v1 status_rationale conditional, schemas/dev-report.v1.json:91-97 pattern);
   G4's honest_blocked requires no downstream artifacts; class-a judgment stays at close.
3. **External kill / crash windows**: SubagentStop does NOT fire on external hard termination
   (measured: docs/reference/harness-issues-backlog.md line 59 — the interruption lands before
   any terminal report or SubagentStop); killed producers leave incomplete chains caught by
   G4/G5; /restart resumes the SAME agent_id (its transcript still holds the obligation).
4. **`forced` (hand-edit) path**: /close --force is the sanctioned no-artifact route
   (close.md:24-30); disposition `forced` derives from the close-report's terminal line.
   Forgery honesty: a `CLOSE: YES (FORCED)` line is mechanically forgeable by any docs/dev
   editor (the Write-only write-guard does not cover Edit — hooks/pretool-write-guard.sh's
   matcher and its own message :148-155; qa/dev tool-policy include Edit), exactly as a false
   plain `CLOSE: YES` always was; FORCED adds bypass-of-chain, so containment is the HUMAN
   GATE: every landing route for `forced` is human-invoked (/commit is model-denied —
   commands/commit.md frontmatter + settings.json deny Skill(commit:*)), and /commit MUST echo
   `disposition: forced (mechanically unverifiable — confirm you ran /close --force for this
   task)` verbatim before any landing step, with commit-QA still running. TODAY's landing
   route for forced cycles = human /commit --bulk (the sentinel-gated bulk path); a per-task
   forced-admission profile (planner + analyst accepting disposition forced + close-report as
   whitelist authority under human commit-QA) is a NAMED DEPENDENCY on the free-landing
   workstream (spec-20260914-052140 §5.3 — the concurrent-edit clean-landing design-intent
   charter), specified here as an interface, not claimed.
5. **Instrument failures are operation states** (§1.3 G4) — adopted from the external round-1
   review's operation-state vs verdict vocabulary, together with its overnight loop-reset
   anchor and rollout dependency ordering; its receipt-file architecture was rejected under
   ruling 3 and replaced by pure recomputation.

### 1.5 Per-pipeline wiring and entry variations

1. **Bare /dev <free text> — the common case, spec-absent by intent**: task_id + verbatim
   user-requirement doc are hook-minted at UserPromptSubmit (O_EXCL, exists-by-construction,
   prompt-workflow.py:1567-1569); obligations derive from task_id alone; NOTHING in the
   mechanism reads a spec. Current dev.md silently AUTO-ADOPTS the newest historical spec
   (commands/dev.md:123-129) — under this design, auto-detected specs become null-degrading
   enrichment: entry-time resolution failure or later non-resolution degrades the binding to
   null with an advisory, never `incomplete`; the context patch records `spec_path_source:
   "explicit"|"auto"|"none"` (additive field; schemas/context.v1.json is
   additionalProperties:true); explicit `--spec` keeps its loud entry-time fail
   (dev.md:137-144) and hard-binds in the recompute.
2. **/dev fan-out**: lane_set in every dispatch + shard echo + G3 roster equality + G4
   derivation (§1.4.1). Retries re-declare canonical paths.
3. **/redev**: fresh task_id per invocation (commands/redev.md:12-15). Current-behavior bug
   fixed at source: the Dev-start replay key is sha256(session + raw input) (:1808-1811) with
   a pre-lock short-circuit (:1814-1823), so an IDENTICAL bare /redev replays the prior
   task_id — replaced by a 60-second replay window keyed on the replay record's own creation
   time (duplicate hook deliveries are sub-second; a later identical invocation starts fresh).
   Obligation checks are per-task_id, so two cycles in one transcript never cross-contaminate.
4. **/dev-command**: same producers; gains its FIRST terminal gate via the command-agnostic
   Stop recompute (today: none, dev-command.md:911-925).
5. **/dev-overnight**: obligations ride the same dispatch prompts; cycle-contract
   required_calls[] remains the overnight roster (schemas/cycle-contract.v1.json:67-119);
   loop-reset recompute closes the cycle boundary; artifact-contract flag armed at init.
   Landing story: the per-cycle scripts/commit.sh is a deliberately NON-committing stub
   (exits 0 clean / 3 dirty, refusing to self-authorize — scripts/commit.sh:23-35, :47-51;
   dev-overnight.md:1561 logs and continues); work is preserved per-fix in refs/checkpoints/*
   and lands later through the already-human-only /commit (--bulk) → changelog-analyst. C5's
   commits-only-via-changelog-analyst holds by construction; no new human step is introduced —
   the human /commit was already the only landing path; the mechanism's contribution is that
   the eventual /commit consumes obligation-clean, disposition-checked state.
6. **/do**: consent-time skeleton extended with `pipeline_profile: "do"` +
   `expected_absent` (fixing close #141 — today subagentstop-e2e-enforce.py:228-234 blocks
   every /do close hunting a qa-report that legitimately never exists); stop gate in block
   mode with hook-side blocked-finalization; /close <task-id> runs the do-close profile;
   /commit consumes the do-report (source=="do" route).
7. **--codex variants**: subagentstop-codex-enforce.py becomes obligation-profile-aware
   (close #146 residue dissolves).
8. **Force paths**: §1.4.4. /commit --dry-run unchanged (by-design stop, #92). /commit --bulk
   task-less and exempt from the per-task disposition; its QA/analyst dispatches still carry
   response obligations (task_id null legal in bulk context).
9. **Cross-session /close**: disk-only disposition (§1.4.1); close re-derives
   SESSION_ID="dev-${TASK_ID}" exactly as today (close.md:430).
10. **Nonstandard order / concurrent cycles**: dispositions are pure functions of disk —
   order-free; obligation checks are per-dispatch and per-task; the Stop selector handles
   multi-cycle sessions; task-id collisions are prevented by the existing O_EXCL reservation
   minting (prompt-workflow.py:1340-1357).

### 1.6 Schema v2 cutover

- NEW repo-versioned schemas: dev-report.v2.json, qa-report.v2.json — matching the REAL nested
  producer shapes (dev.* — agents/dev.md:590-674 template has nested dev.status and NO
  report_version field; qa.* — agents/qa.md:1393 mandates nested qa.status with top-level
  status forbidden). The v1 schemas are flat (dev-report.v1.json:8-16 requires top-level
  status; qa-report.v1.json:8-14 requires top-level verdict) and match NO current producer.
  v2 additionally REQUIRES: baseline_head_sha, baseline_dirty_snapshot, owned_edits /
  pre_edit_snapshots key presence (moving commit #71/#72 and close #20/#22 to the producer),
  timestamp, and lane_set when lane-scoped. Producers do not flatten: every consumer reads
  nested (resolve-dev-artifact-chain.py:253-262, :290-300; the aggregate writer; the
  commit side).
- NEW schemas/changelog-status.v1.json (the analyst's response contract).
- do-report.v1 gains additive optional fields only (pipeline_profile, expected_absent) — it
  already matches its producer (hook-written skeleton). context.v1 gains additive
  spec_path_source.
- Producer templates emit report_version: 2; enforcement authority comes from the obligation's
  schema id, so the unversioned legacy corpus (674 reports → 9 pass / 0 fail / 665 skip
  measured baseline, artifact-contract hook header :12-25) is never retro-rejected.

## 2. Elimination accounting (by inventory mode number)

Categories: P removed at producer gate; O removed at orchestrator gate; R removed by recompute
relocation (including whole close-side sub-mechanisms deleted outright); S neutralized to a
retryable non-verdict OPERATION_STALLED state; X out of this workstream (owned by adjacent
workstreams — ownership/landing class-c, grant/lock/journal class-d, close-verdict-protocol
internals, typed-plan transport, argument grammar class-e, session-hygiene hooks — or
already-advisory today); A legal class-a retained by ruling 1; G genuinely residual.

### /close (199)

- P (44): 14,16,17,19,20,22 · 39,40,41,42,43,44,45,46,47,49,50,51,52,53,54,55,57,58,76 ·
  101,102,103,105,106 · 107,108,109 · 141,142,143,144,145,146 · 163 · 168,173,174 · 195
- O (8): 13,15,21,23,24,26,27 · 139
- R (72): 11,12,25,28,29,30,32,33 · 35,37,38,61,62,63,64,67,68,69,70,71,72,73,74,75,77 ·
  78-100 (23, the late-repair family withering to deletion) · 110,111 · 112-120 (9) ·
  129-138 (10) · 154,155,157
- S (5): 34,36,48,65,66 (disposition-instrument runtime → OPERATION_STALLED, never a verdict)
- A (12): 18,56,59,60,104,153,156,159,160,161,162,166 (plus partial-a members of 75,88,144,165)
- X (58): 1-7 · 8,9,10 · 31 · 121-128 · 140 · 147-152 · 158,164,165,167 ·
  169,170,171,172,175,176,177,178,179,180,181,182,183,184,185 · 186,187,188 · 189-194 ·
  196-199
- G (0). Sum 44+8+72+5+12+58 = 199.

### /commit (275)

- P (55): 26,28,29,30,31,32,34,35,52 · 57,58,59,61,62,64,65,70,71,72 ·
  125,128,129,130,131,132,133,139,154 · 185,186,187,189,190,191,192,193,194,195,196,197,198,
  199,200,201,203,205 · 211,212,213,214,215,222,223 · 268,269
- O (2): 56, 261
- R (37): 8 · 11-22 (12, late-repair) · 23,24,25,38,39,40,41,42,45,46,47,48,49,50,51 · 60 ·
  103,104 (Step-8 spec-link demoted to advisory — a check REMOVAL) · 120,121,122,123,124,126,137
- S (4): 27,43,44,76 (instrument runtime → OPERATION_STALLED; #77 stays R via the fixed
  absolute entrypoint)
- A (4): 7,33,36,37 (plus half of 88)
- G (3): 6 (close-born close-report absence — recast as the one legal "close has not yet
  succeeded" sequencing verdict, the commit-side analogue of class-a) · 55,136 (forced-path
  residual until the named forced-admission dependency lands; eliminated for
  obligation-carrying cycles)
- X (170): 1,2,3,4,5,9,10 · 53,54,63,66,67,68,69,73,74,75,76→S? — see note — 77→R ·
  78-83 · 84-93 · 94,95,96,97,98,99,100,101,102,105,106,107 · 108-119 (plan transport /
  live-drift / detached-unborn; the #108/110/111/113/114/115 R-claim of round R4 was REVERTED
  in round R5: the plan travels through model-mediated prompt interpolation,
  commit.md:372-395, so the analyst's Phase-1 input validation is a legitimate typed-handoff
  guard; plan_sha256 in the analyst obligation is the named future interface) ·
  127,134,135,138,140,141,142,143,144,145,146 · 147-150 · 151,152,153,155,156,157,158,159,
  160,161 · 162-179 · 180-184 · 188,202,204,206,207,208,209,210 · 216-221,224 · 225-236 ·
  237-258 · 259,260,262,263,264,265,266,267,270 · 271-275
  (Note: #76 is counted in S, #77 in R; the X list above excludes them.)
- Sum 55+2+37+4+4+3+170 = 275.

### Headline (criteria C2/C3)

- Eliminated from the close/commit failure surface: close 124 (44P+8O+72R) + commit 94
  (55P+2O+37R) = **218**.
- Neutralized to bounded non-verdict stalls (S): **9** — honestly not counted as eliminated.
- Remaining verdict-capable at close/commit: 474 − 218 − 9 = **247**: X 228 (adjacent
  workstreams or already-advisory — the X set contains advisory b-modes close #149/#187 and
  commit #97, which block nothing today and are untouched), A 16, G 3.
- New class-(b)/(c) checks added at /close or /commit: **0** — every added gate lives at
  PreToolUse, SubagentStop, dev-side Stop, or the overnight loop-reset; the close/commit-side
  changes are strictly REMOVALS plus one disposition read whose infra failures are
  operation-states, not verdicts.

## 3. Design pre-mortem register (criterion C4)

Methodology: the inventory's own (per component, enumerate distinct failure/abuse modes;
classify; behavior; why acceptable or how designed out). Debated adversarially in rounds
R4-R7; corrections from those rounds are inline. Components: G1 dispatch gate, G2
producer-stop gate, G3 collection gates, G4 terminal Stop gate, G5 overnight loop-reset, G6
do-gate finalization, G7 grammar/lib, G8 schemas, G9 purity redaction, G10 rollout.

G1: M1 (d) gate crash traps all dispatches → fail-open wrapper + kill switch; degrade covered
by G2/G4. M2 (e) false-reject → orchestrator repairs. M3 (b) false-accept → G2+G4 nets.
M4 (d) mint-to-dispatch latency >300s → false-reject, re-mint. M5 (e) two blocks in one prompt
→ exactly-one rejects; quoting convention. M6 (d) transcript unreadable for consistency read →
advisory skip; roster safe via disk-side lane_set echo (corrected in R4). M7 (e) lane/lane_set
shape mismatch → shape-reject. M36 (c) coordinated forgery: every lane re-run with a falsified
smaller roster during a sustained outage → content-trust boundary (the mechanism eliminates
honest omission, not coordinated lying); same boundary as today, owned by QA class-a judgment
and the class-c content workstream. M37 (d) profile-context read fails → role minimum still
enforced; ad_hoc for qa/analyst FAIL-CLOSED under unknown context (corrected in R5).

G2: M8 (d) full ladder degrade to L3 → advisory + G4 backstop; internal producers bounded by
L1′ (live-store) — floor = harness self-corruption while running, pre-existing. M9 (b)
transcript format drift → observable degrade; format pinned by tests (precedent
tests/test_restart_command.py). M10 (d) SubagentStop never fires on external kill (measured)
→ G4/G5 catch; /restart resumes the same agent. M11 (e) obligation names a pre-existing file
→ loud freshness false-block at first use (template bug caught in rollout). M12 (d) fs
timestamp granularity → 2s allowance; false-block direction. M13 (b) schema-valid junk →
semantic layer unchanged (QA); floor strictly higher. M14 (e) producer edits a peer's
artifact → forbidden by gate text (:313-316); peer's own stop revalidates; residual =
c-ownership interface. M15 (d) repeated stops on resume → idempotent. M39 (c) forged internal
timestamp + touch → content-trust boundary (R4). M42 (e) cross-channel consistency
false-block when QA revises its verdict between file and response → self-repairing re-align
(R6). M43 (d) close-verdict classifier unavailable to the gate → degrade to enumerated-forms
regex + advisory; never traps (R6).

G3: M16 (b) legacy canonical without lane_set-era shards → roster clause applies only where
obligations/echoes exist; legacy keeps today's behavior. M17 (d) mid-write read → AGG writes
atomic (temp + os.replace). M18 (c) gitignore exemption too broad → four profiles only.

G4: M19 (d) Stop gate blocks forever → transcript-counted bounded attempts; beyond →
advisory + honest incomplete. M20 (e) wrong task → exhaustive selector, no heuristic.
M21 (d) block-event format drift → bound degrades to zero (advisory immediately);
observable. M22 (d) death without Stop → incomplete → class-a with resume route. M23 (b)
recompute bug misclassifies → same class as a resolver bug today; shared code + extended
test corpus (tests/test_resolve_dev_artifact_chain.py); false-block direction with named
evidence. M44 (d) instrument-failure retry loop → bounded by construction: one retry, then
OPERATION_STALLED (R6).

G5: M24 (d) recompute fails every retry → bounded by max_retries then failed-cycle record;
EXPIRY path keeps precedence (posttool-overnight-loop.py:157-160 ordering pinned) — the gate
conditions CYCLE RESET only; the pre-existing timelock closeout surface
(stop-overnight-timelock.py:132-154) is untouched (corrected in R4). M25 (e) todos never
all-complete → session runs to end_time; landing deferred to human /commit as today
(corrected in R4).

G6: M26 (d) skeleton finalization write fails → last-resort force-allow + advisory →
incomplete → class-a. M27 (c) finalization races the agent's late write → only after
MAX_BLOCKS; atomic; either writer leaves a terminal status.

G7: M28 (e) grammar drift across five templates → single lib parser + gate rejection +
per-template emission tests. M29 (b) obligation version bump → versioned, tolerant. M35 (d)
replay window (corrected in R4/R5-era analysis): too short → duplicate init (O_EXCL-unique,
never corrupting); too long → same-minute identical re-invocation replays (user-visible,
repairable) — both bounded and observable. M41 (e) the 2s freshness allowance admits a retry
dispatched within 2s of the prior report write — physically pathological, risk-accepted (R5).

G8: M30 (b) v2 stricter than real output → producer-stop blocks with context; rollback =
obligation reverts to v1 id. M31 (b) changelog-status drift from the agent doc →
single-source + pinning test. M38 (b) lane_set echo divergence across shards → identical-echo
requirement; divergence = incomplete naming both rosters; repair = re-dispatch minority lanes.

G9: M32 (cosmetic) purity warning → warn-only hook + redaction addition.

G10: M33 (b/d) pipeline armed before its templates → per-pipeline advisory arming. M34 (b)
deleting close/commit checks before dispositions live → forbidden by rollout order
(deletions last, each behind a green gate). M40 (b) Step-8 spec-link advisory demotion hides
a missing linkage → visibility preserved (advisory text + the spec-update dispatch still
runs); repair path unaffected; accepted trade under ruling 1.

**Arithmetic proof (C2/C3, and the quantitative half of C1)**:
- C1: files created by the mechanism at runtime: none (obligations live in prompts and
  transcripts; roster lives in existing report files; advisory records append to existing
  logs; the do-skeleton and replay stores are existing hook-authored channels). New
  repo-versioned files: schemas + hook code only.
- C2: new class-(b)/(c) checks at /close or /commit: 0 (§2 headline; every mechanism mode
  M1-M44 lives outside the two commands; the S states are non-verdict stalls).
- C3: 474 → 247 remaining + 9 S + 44 mechanism modes = 300 < 474 — a strict decrease even
  counting every stall and every mechanism mode as full surface (both over-counts: 29 of the
  44 are self-repairing or advisory-degrading, 8 are honest class-a terminals, 3 are
  pre-existing trust-boundary restatements).

## 4. Rollout (each step independently leaves all five pipelines green)

| Step | Content | Files changed (M) / created (C) | close/commit checks that become deletable |
|---|---|---|---|
| S0 | Measure the SubagentStop payload via the existing observational canary (register it for SubagentStop; it records session_id/transcript_path/cwd and tier-3 fields — hooks/capability-canary.py, hooks/lib/capability_state.py:129-130) | M settings.json | none (canary never blocks) |
| S1 | Schemas: dev-report.v2, qa-report.v2, changelog-status.v1; registry entries; additive do-report.v1 + context.v1 fields | C schemas/*.json, M schemas/registry.json | none (nothing consumes yet) |
| S2 | Obligation grammar lib + tests | C hooks/lib/obligation.py, C tests | none |
| S3 | Dispatch gate hook, advisory mode | C hooks/pretool-obligation-gate.py, M settings.json | none |
| S4 | Producer-stop generalization behind env flag (ladder L0-L3, kinds, freshness, bundle rules) | M hooks/subagentstop-artifact-contract-enforce.py | none yet |
| S5 | Templates: obligations into dev.md (+redev), dev-command.md, dev-overnight.md, close.md (close-QA bundle), commit.md (commit-QA + analyst); purity-hook redaction line; do-skeleton profile fields; overnight-init arms artifact-contract; per-pipeline gate arming advisory→block as each template lands | M commands/*.md, M hooks/pretool-orchestrator-prompt-purity.py, M hooks/prompt-workflow.py, M scripts/overnight-init.sh | close #141/#146 paths stop firing |
| S6 | Producer v2 cutover: agents/dev.md + agents/qa.md emit report_version 2 + lane_set echo + timestamps; obligations point at v2 | M agents/dev.md, M agents/qa.md | none yet |
| S7 | Collection gates generalized (aggregate-check: schema+identity+roster+obligation anchor; gitignore profile exemption) | M hooks/pretool-aggregate-check.py, M hooks/pretool-gitignore-preflight.py | commit #260/#261, close #139 stop firing |
| S8 | Resolver dispositions (+ shard-roster derivation, spec clause, forced/honest_blocked, flat single-call output) + tests; replay-window fix; codex-enforce profile-awareness | M scripts/resolve-dev-artifact-chain.py, M hooks/prompt-workflow.py, M hooks/subagentstop-codex-enforce.py, M tests | none yet |
| S9 | Terminal anchors: Stop recompute hook (advisory→block), loop-reset recompute (non-expired branch only), do-gate block mode + finalization | C hooks/stop-devcycle-recompute.py, M settings.json, M hooks/posttool-overnight-loop.py, M hooks/stop-do-report-gate.py | close #195 becomes producer-guaranteed |
| S10 | /close consumption cutover: Step 0 → one disposition call with the instrument-failure operation-state branch; Step 2 registry-arming deleted; RSA advisory; Workflow-Integrity bullets cite the disposition | M commands/close.md | close #11-33 (aggregation invocation deleted; #34/36/48/65/66 → stalls), #34-77 region (resolver duplicate), #107-111 (schema gate), #112-120 (RSA), #129-138 (registry writes), #154/#155/#157 vacuous triggers |
| S11 | /commit consumption cutover: Step 5 resolver/late-repair duplicates → disposition; Step 8 spec-link advisory; forced-echo requirement | M commands/commit.md | commit #11-22 (late-repair), #23-52 duplicates (→ #27/43/44/76 stalls), #103/#104 |
| S12 | Deletions/retirements behind green gates: correlation heuristics in both stop hooks; e2e missing-report guess-block; enforce-flag writers at close; late-repair route retirement (flag-gated until the forced-admission dependency lands) | M hooks/subagentstop-e2e-enforce.py, M hooks/subagentstop-artifact-contract-enforce.py, M scripts (late-repair), M commands/close.md | close #78-100 family (route deleted) |

Order rationale (adopted from the external round-1 review): schemas and obligations before
gates; gates before terminal anchors; anchors before consumption cutover; deletions last —
otherwise /commit would temporarily trust evidence some pipelines do not yet produce.

## 5. Debate log and convergence evidence

Consultation channel: the /codex command's own conventions (commands/codex.md — isolation
wrapper resolved from CODEX_ISO_BIN, default model gpt-5.6-sol, reasoning_effort xhigh,
outputs under /var/tmp/codex-outputs/, USER REQUIREMENT / SCOPE / OUT OF SCOPE prelude on
every prompt, strictly read-only review, detached execution for long investigations with
liveness judged by output-file growth and the terminal token-usage footer). Every finding was
classified per the /codex calling protocol (in_scope_real_bug / in_scope_minor /
out_of_scope / nitpick) and verified against the working tree before acceptance. The full
per-finding ledger (claims, classifications, verification evidence, resolutions) accompanies
this document's source debate at /var/tmp/zerofail-defect-ledger.md; the summary follows.

Background round 0 (prior to this debate): the external universal-finalizer/terminal-receipt
design — /var/tmp/codex-outputs/codex-output-1398509-1790527455.txt (final answer lines
5228-5622; 170,271 tokens). Subsumed except three adopted elements (loop-reset anchor,
operation-state vocabulary, rollout order); its receipt files were rejected under ruling 3.

| Round (theme) | Raw output | Verdict | Accepted | Design delta |
|---|---|---|---|---|
| R1 state-channel soundness | /var/tmp/codex-outputs/zerofail-r1-1790562855.txt | DEFECTS_FOUND(9) | 9 real | v0.4→v0.5: resolution ladder; unconditional producer trigger; markdown/response kinds; dispatched_at freshness; disposition model seeded (honest_blocked); obligation-anchored collection gates; close Step-2 deletion |
| R2 fan-out + orchestrator artifacts + anchors | /var/tmp/codex-outputs/zerofail-r2-1790579837.txt | DEFECTS_FOUND(9) | 8 real + 1 minor | v0.5→v0.6: lane_set; retry same-paths rule; dispositions become the ONLY close-side consumption with the class-a incomplete argument; spec clause; gate-clock bound; response_line; changelog-status schema; overnight landing story |
| R3 entry variations | /var/tmp/codex-outputs/zerofail-r3-1790580932.txt | DEFECTS_FOUND(8) | 6 real + 2 minor | v0.6→v0.7: explicit/auto spec split; replay fix; Stop selector; roster invariant chain; 2s freshness; forced disposition; bulk exemption |
| R4 pre-mortem | /var/tmp/codex-outputs/zerofail-r4-1790581814.txt | DEFECTS_FOUND(10) | 10 (8 design/register + 2 arithmetic) | v0.7→v0.8: disk-persisted lane_set echo; disposition subsumes aggregation; forced forgery layers; forced-landing dependency honesty; profile-context matrix; replay window; internal-timestamp freshness; accounting reclassifications; loop-reset expiry precedence |
| R5 free attack | first run /var/tmp/codex-outputs/zerofail-r5-1790598151.txt DIED on the channel's own usage limit (verbatim limit errors in the tail; 104,653 tokens; no verdict); protocol retry ONCE → round of record /var/tmp/codex-outputs/zerofail-r5retry-1790641317.txt | DEFECTS_FOUND(7) | 7 (5 design + 2 accounting) | v0.8→v0.9: bulk-context nullability; dual close-QA obligations; ad_hoc fail-closed; plan-transport X reversion; #55/#136→G; forced containment withdrawal → human gate; per-kind freshness |
| (disclosure) | an intermediate retry /var/tmp/codex-outputs/zerofail-r5-retry-1790603022.txt completed with DEFECTS_FOUND(3); two of its findings duplicate R5-F2/F3; its unique finding was accepted late in R6 as R5R1-F1 | — | — | — |
| R6 free attack | /var/tmp/codex-outputs/zerofail-r6-1790642531.txt | DEFECTS_FOUND(3) | 3 real + 1 carry-over (R5R1-F1) | v0.9→v0.10: verdict-class classifier reuse; cross-channel consistency; sentinel waiver (+CRITICAL form); instrument-failure operation states + S bucket |
| R7 free attack | /var/tmp/codex-outputs/zerofail-r7-1790663400.txt and zerofail-r7-retry-1790664095.txt | CHANNEL_EXHAUSTED — both runs died on the external channel's own usage limit (verbatim limit errors, 2,471 bytes each, no verdict; stated retry date 2026-10-05); round not counted, no verdict fabricated | — | — |

Convergence rule: minimum 4 rounds; converged when two consecutive rounds yield zero new
accepted in-scope real defects; hard cap 8.

### Convergence status at close of debate (2026-09-29)

- Rounds completed with verdicts: R1(9) R2(9) R3(8) R4(10) R5(7, plus a disclosed intermediate
  retry with 1 unique finding processed late) R6(3+1 carry-over) = 6 rounds, 47 accepted
  findings, minimum-4 satisfied, 8-round cap not reached.
- Zero accepted findings remain unresolved: every one has a resolution incorporated in the
  v0.10 design stack (v0.6+v0.7+v0.8+v0.9+v0.10), the pre-mortem register (M1-M44), and the
  amended accounting (218 eliminated / 9 S / 247 remaining).
- Convergence criterion (two consecutive rounds with zero new accepted in-scope real defects):
  NOT met — the last completed round (R6) accepted 3 new defects, and the consultation channel
  died before any subsequent round could complete. The design is therefore delivered as
  debate-hardened through six rounds but NOT adversarially converged; rounds R7+ should resume
  against the v0.10 stack when the channel restores (on its stated schedule, 2026-10-05).
