# Cluster A: producer input and producer identity (A3, A4)

Repository: /home/user/awesome-claude-harness at HEAD 09ab15b (read-only). All file:line
citations refer to that tree. Re-verification ran only in a scratch copy:
`scratchpad/landscape-work/A-producer-input-identity/` (`git archive HEAD` copy in `harness/`,
toy product repo in `product/`, driver `drive.py`, HOME, CLAUDE_STATE_DIR and
ATTRIBUTION_STATE_DIR all redirected into that directory, PYTHONDONTWRITEBYTECODE=1).

Prior evidence that was re-checked and is cited: `harness-cleanup/problems.md` X34,
`harness-cleanup/runtime-verification.md` rows 23/26/41 and findings at lines 56-58, 179,
206, 268, 311, 315, 403; `adv_result.json` (fabricated files_created admitted by
resolve-commit-repos; close/do reports forged by the main agent); `ca_result.json` inv[0]
F3 (dev.md:522-527 to changelog-analyst whitelist to "stage every candidate").

## 0. One-paragraph summary

**A3.** The first input the commit pipeline trusts is `dev.files_created` / `dev.files_modified`.
The producer (agents/dev.md) is told to compute them from git, so the lists describe the state
of the shared working tree, not what this agent wrote. They therefore pick up peer-session
files, hook byproducts (doc-sync CLAUDE.md/INDEX.md/README.md, the harness's own
`.claude/dev-registry/agent-index.json(.lock)`) and scratch files. Every downstream consumer then
treats the lists as authorship. resolve-commit-repos exempts `files_created` from its ownership
gate, and changelog-analyst stages every whitelisted candidate. A measured alternative already
runs on every tool call: the write-time attribution journal records each write with the
CLI-supplied `agent_id`. Its journal-derived view is also already called at the producer-stop
gate, but it is mis-wired (no agent ids are passed), so it attributes nothing. Its Bash
measurement also covers only the harness repo, so a Bash-created file in a product repo is
invisible to it. /do uses the opposite rule ("from memory, never git"), and nothing checks it.

**A4.** Every role-based hook resolves the role from `payload.subagent_type`, which the CLI
does not send in tool-event payloads. When that is absent, it falls back to an agent-index
entry written when the subagent *chooses* to Read a sentinel path. The CLI-supplied
`payload.agent_type` and the CLI-written `agentType` in `agent-<id>.meta.json` are ignored
everywhere except two side reads. An unregistered subagent is "role None", which every caller
allows (LOW-10). A subagent that Reads another role's sentinel becomes that role, and the
sentinel file does not even have to exist. The G1 dispatch gate triggers on
`tool_input.subagent_type` alone and never binds `obligation.role` to it. The main agent has no
write policy at all, and no hook protects any producer artifact under `docs/dev/` or
`.claude/dev-registry/`.

## 1. Verification results (scratch sandbox, this run)

| id | scenario | result | meaning |
|---|---|---|---|
| T1a | pretool-tool-policy, Edit `src/app.py` with `{agent_id, agent_type:"qa"}` | rc=0 | QA edits source when only the CLI field is present |
| T1b | same with `{agent_id, subagent_type:"qa"}` | rc=2 (denied_write_path_prefixes) | policy works only if the non-CLI field is supplied |
| T1c | pretool-subagent-code-block, same as T1a | rc=0 "unregistered subagent role; allowing write" | shim is advisory-only |
| T2a | pretool-cp-checkin: agent `a-qa2` (agent_type qa) Reads `.claude/dev-registry/dev-X/dev.json`, which **does not exist** | agent-index: `{"a-qa2":{"agent_type":"dev",...}}`; `resolve_agent_type({agent_id:a-qa2, agent_type:"qa"})` returns `dev` | role is chosen by the reader; no existence or agent_type cross-check |
| T2c | then Reads `qa.json` | resolves `qa` again | last Read wins |
| T3a | G1 in **block** mode, `subagent_type:"general-purpose"`, prompt "write docs/dev/dev-report-…json", no obligation | rc=0 | a producer dispatched under a non-producer type skips G1 |
| T3b | G1 block, `subagent_type:"qa"` with an obligation whose `role:"dev"` | rc=0 | obligation.role is never bound to subagent_type |
| T3c | G1 block, `subagent_type:"dev"`, no obligation (control) | rc=2 | G1 works only on the declared type |
| T4a-d | main agent: Write dev-report; Bash heredoc into qa-report; Write agent-index (cp-state guard); Bash write agent-index | rc=0 x4 | no guard for orchestrator writes to producer artifacts or identity state |
| P1 | `policy_registry.is_allowed` (pure) | dev may Write `close-report-*`, `qa-report-*`, `agent-index.json`; qa may Write `close-report-*`; qa/ba/analyst may not Write `dev-report-*` | dev role `allowed_write_path_prefixes:["*"]` lets dev write every other producer's artifact |
| T5 | attribution journal in a product repo: Bash `python3 gen.py` creates `generated.txt`; Write creates `src/new.py` | only `src/new.py` journaled (`agent_id:a-dev1`, `pre_sha:absent`, `post_sha:"unreadable"` because the copied harness is not a git repo) | Bash-created product files are invisible; the blob store needs a harness `.git` |
| T6 | dev.md:525-527 derivation after one legitimate Write and one legitimate Bash-generated file | `files_created` = agent-index.json, agent-index.json.lock, CLAUDE.md, generated.txt, scratch.txt, src/INDEX.md, src/README.md, src/new.py | 2 of 8 entries are the dev's work; posttool-doc-sync added CLAUDE.md, src/INDEX.md, src/README.md |
| P2 | `attribution_aggregate_view.build_view` as called in production (hooks/subagentstop-artifact-contract-enforce.py:434, no lanes) | files_created=[], disagreements=[] | the existing journal check is inert |
| P3 | same view with `lanes=[{agent_ids:[a-dev1]}]`, `session_ids=[sess-A]`, shard = the T6 report | 7 `declared_not_journaled` (agent-index x2, CLAUDE.md, scratch.txt, src/INDEX.md, src/README.md, generated.txt); `src/new.py` accepted | the producer-side check works today for Write/Edit. `generated.txt` is a false positive until the journal measures the product repo (fix F-A3-1) |

Note: T2b and T4e also returned rc=2, but only because the sandbox product repo sits under
`/tmp`, which tool-policy denies to every role (the "arbitrary /tmp" rule). P1 re-ran those
cases as pure policy decisions on a non-/tmp path.

---

## A3. Dirty first producer input: files_created / files_modified / owned_edits

### A3.0 Root cause
The producer is told to describe the **tree** (git diff and untracked list minus a point-in-time
baseline) instead of **its own writes**. The harness already records its own writes per agent
(the attribution journal), but nothing binds the claim to that record at the producer's stop.
The zero-failure design does not cover this either: §2 lines 424-426 mark "ownership/landing
class-c" and "grant/lock/journal class-d" as **X, out of this workstream, owned by adjacent
workstreams**. §1.6 lines 407-409 also make the git-derived inputs (`baseline_dirty_snapshot`,
`owned_edits`, `pre_edit_snapshots`) schema-REQUIRED in dev-report v2. Ruling 1 (§0 lines 13-16)
still classifies file-content/ownership failures at close/commit as defects that must be
guaranteed during /dev.

### A3.1 Producer-side locations (where the lists are made)

| file:line | what is wrong |
|---|---|
| agents/dev.md:520 | non-null lists required. Fine, but `commit.sh closure detection` is cited as the consumer and that script never commits (B2) |
| agents/dev.md:522 | "MUST be derived from git commands… NOT from work-tree inspection of expected state": mandates tree-state derivation, not authorship |
| agents/dev.md:524 | `files_modified` = `git diff --name-only <baseline_head_sha>`: includes peer-session and hook (doc-sync) edits to tracked files |
| agents/dev.md:525-527 | `files_created` = untracked files (`git ls-files --others --exclude-standard`) plus staged-added files, minus baseline_dirty_paths: every untracked file created by anyone after the baseline instant (T6) |
| agents/dev.md:529-531 | adoption-cell rules: a third derivation (`git status --porcelain`) plus a self-authored provenance contract object, adding complexity on top of the dirty base |
| agents/dev.md:533 | the two lists are explicitly non-disjoint. Consumers union them |
| agents/dev.md:535 | unborn-repo fallback to `git status --porcelain`, the same flaw |
| agents/dev.md:537 | `observed_preexisting` free-form claim |
| agents/dev.md:539-543 | `baseline_head_sha` and `baseline_dirty_snapshot` are copied verbatim from the orchestrator. The doc itself admits it "is not a session boundary… files written by a peer session after the capture instant will not appear in it" |
| agents/dev.md:545-592 | owned_edits and pre_edit_snapshots: the LLM must reproduce exact old/new strings for every edit (self-reported ownership). changelog-analyst.md:771 says the journal "replaces the owned-edits ledger", yet dev.md still marks it MANDATORY and resolve-commit-repos.py:610 still uses it as the files_modified ownership gate (D3) |
| agents/dev.md:594-683 | report template. `dev.files_*` and `tasks_completed[].files_*` are two more self-reported copies (QA scans the per-task copy, qa.md:574) |
| commands/dev.md:851-857 | the orchestrator captures the baseline by prose-only Bash. The enforcing hook exists but is **unregistered** (hooks/pretool-baseline-snapshot-preflight.py:1-40; absent from settings.json and settings.template.json) |
| commands/dev.md:884-885 | the baseline is passed in the dispatch prompt (orchestrator-authored input) |
| commands/dev.md:903-905, :933-940, :945-962 | the fan-out aggregate = UNION of per-worker lists, so every lane's dirt carries into the canonical |
| scripts/aggregate-dev-report.py:1601 | `"files_created": _union_list(shards, ["dev","files_created"])` (mechanical union of dirty shards) |
| scripts/aggregate-dev-report.py:1648 | merges self-reported owned_edits into the canonical |
| scripts/aggregate-dev-report.py:457-514 | chain-wave predecessor provenance trusts the predecessor's own `dev.files_created` as evidence |
| commands/dev-command.md:604, commands/dev-overnight.md:1286, commands/redev.md (re-attach) | the same agents/dev.md producer, no own rule. Overnight runs in a worktree with the same derivation |
| commands/do.md:50, :72-73 | /do producer (the main agent itself) fills `do.files_*` |
| commands/do.md:80 | "MUST be filled… from its own knowledge… NOT derived from git diff": the opposite rule to dev.md:522 (D3), and nothing verifies it |
| commands/do.md:82 | new files must also be duplicated into files_modified or /close will not inspect them |
| hooks/prompt-workflow.py:1364-1396 | the do skeleton writes `files_modified:[]`, `files_created:[]`. Docstring :1371-1372: "git-diff derivation is forbidden by commands/do.md" |
| hooks/stop-do-report-gate.py:27, :108-111 | checks only that `files_*` are arrays. Adversarial run: `files_modified:[]` with 3 files changed passed (adv_result.json) |
| hooks/stop-do-report-gate.py:264-268 | the block message instructs "fill… from your OWN knowledge… do NOT derive from git diff" |
| schemas/dev-report.v2.json:10-18 | REQUIRES `baseline_dirty_snapshot`, `owned_edits`, `pre_edit_snapshots` (entrenches the self-reported and git-derived inputs) |
| schemas/dev-report.v2.json:64-108 | `files_modified`/`files_created` are `array of string` with no authorship semantics |
| schemas/dev-report.v1.json:13, :50; schemas/do-report.v1.json:47, :60 | same, shape only |
| schemas/owned-edits-ledger.v1.json:42-44, :56, :86-104 | ledger contract that is not in registry.json and never loaded (manifest: DELETE) |
| scripts/dev-fix.py:1229-1241 | a **second writer** of `files_modified`/`files_created` (F05 rewrite from "authoritative" event fields). No live caller (manifest: DELETE) |
| hooks/posttool-doc-sync.py (registered PostToolUse Write/Edit) | writes CLAUDE.md, INDEX.md, README.md into the **product** repo, which become untracked and land in files_created (T6; adv_result origin contains them) |
| hooks/pretool-cp-checkin.py:154-192 | writes `.claude/dev-registry/agent-index.json` (+ `.lock`) into the product repo. Untracked, lands in files_created (T6) |
| hooks/session-gitignore-propagate.sh:3-8, :15-19 | propagates ignore rules only for repos carrying the harness marker and an existing .gitignore. It covers `.claude/dev-registry/dev-*/` but not `agent-index.json`, so product repos are unprotected |
| hooks/subagentstop-artifact-contract-enforce.py:426-440, :494 | writes `docs/dev/journal-view-<task>.json` into the product repo at every dev stop. Nothing reads it (manifest: DELETE) |
| hooks/lib/attribution_journal.py:253-276 (`record_pre`), :259-267 | Bash writes are **measured only in `harness_root()`**. In a product repo only parser-named targets are captured, so `python gen.py`, codegen and lockfiles are invisible (T5) |
| hooks/lib/attribution_journal.py:81-87, :106-108, :111-128, :184-216 | the blob store is the harness `.git`. A non-git install (published tarball/copy) yields `post_sha:"unreadable"` (T5). Path, pre_sha and agent_id survive, which is all the A3 check needs |
| hooks/lib/attribution_journal.py:329-339 | events carry `agent_id` (CLI-supplied, good). `task_id` comes from `$CLAUDE_TASK_ID`, which is never set (acknowledged at changelog-analyst.md:781-786). No `agent_type` is recorded |
| hooks/subagentstop-artifact-contract-enforce.py:434 | `build_view(events, {"task_id": task_id}, root=project_dir)` with **no lanes/agent_ids**, so every event is foreign and the view is empty (P2) |
| hooks/subagentstop-artifact-contract-enforce.py:443-495 (`_wire_ledger_judgment`) | reads `dev.files_modified + dev.files_created` (:466-469) but asks only "is the path ENTANGLED". It never asks "did this agent write it" |
| scripts/lib/attribution_aggregate_view.py:73-80, :96-150 | the journal-derived files lists and the `declared_not_journaled` / `journaled_not_declared` disagreements already exist (the correct producer check), with no wired caller that passes agent ids |
| scripts/lib/attribution_adjudicator.py:745-791 | docstring: "no `agent_id -> task_id` map… exists for any real task today", so every live consumer judges structure only |
| scripts/lib/dispatch_metadata.py:1-27 | the intended agent_id-to-task map is never wired. Not needed: G2 already knows agent_id and its obligation from the transcript (design §1.1(b)) |

### A3.2 Consumers of the dirty lists (every location)

| file:line | what it does with the lists, and why dirt passes through |
|---|---|
| agents/changelog-analyst.md:247-252 | staging whitelist items 1-2 = `dev.files_modified`, `dev.files_created` ("git-derived and therefore assert the cycle AUTHORED the path", :253-256: false premise) |
| agents/changelog-analyst.md:330-341 | staged-count guard = len(lists)+30, so dirty lists raise their own ceiling |
| agents/changelog-analyst.md:344 | /do path: `do.files_*` become the whitelist (memory-derived, unverified) |
| agents/changelog-analyst.md:350 | "Stage-all fallback is forbidden": the whitelist is the only boundary, and it is dirty |
| agents/changelog-analyst.md:411-426 | extracts the arrays. Authorship enrichment "MUST be derived from files_modified + files_created only" |
| agents/changelog-analyst.md:431-470 | provenance filter: `provenance_anomaly` is **never** excluded from staging (:463). Informational only |
| agents/changelog-analyst.md:771-830 | attribution: the journal is consulted only for already-whitelisted paths, keyed by **session**, not agent. The backup path falls back to the dev lists. "Never warn-and-skip, never EXCLUDE, never escalate" (:819-820) |
| agents/changelog-analyst.md:902, :916-917 | "a NEW file created by this cycle (in `dev.files_created`)… Every whitelisted candidate reaching this step is staged" |
| agents/changelog-analyst.md:1827 | `task_cycle_files` = union of the lists (pre-commit recovery) |
| agents/qa.md:470-495 | provenance check against git, so it validates the *dirty* derivation |
| agents/qa.md:496-514 | **reverse under-report check: FAILs dev for not listing any `git diff` path**, which forces dev to include peer and doc-sync edits (the consumer pushes the producer toward dirt) |
| agents/qa.md:516-528 | files_created provenance against `git ls-files --others`: confirms the file exists untracked, not who wrote it |
| agents/qa.md:574 | the hard-coded-path scan targets `tasks_completed[].files_*` (a third self-reported copy) |
| commands/close.md:539-542 | inspector cycle-diff list = `dev.files_modified` only, so files that dev *created* are never inspected (the cleanliness inspector never sees scratch files) |
| commands/close.md:414 | do path: `do.files_modified` non-null check only |
| commands/commit.md:254-256 | resolve-commit-repos resolves every `files_modified[]`/`files_created[]` path into the plan |
| scripts/resolve-commit-repos.py:505-528 (docstring), :561-569 | the plan's owned paths = both lists |
| scripts/resolve-commit-repos.py:593-602 | **"files_created-only identities are exempt"** from the ownership gate, so scratch and doc-sync files enter the commit plan (adv_result: "plan admits junk files scratch.txt+tmp_notes.md from fabricated files_created") |
| scripts/resolve-commit-repos.py:610-694 | the files_modified ownership gate is backed by self-reported owned_edits / baseline / files_landed_whole |
| scripts/resolve-dev-artifact-chain.py:263-272 | shape check only |
| scripts/resolve-dev-artifact-chain.py:1220-1238, :1241-1271 | `declared_paths_exist`: existence only ("the weakest defensible predicate"). Junk exists, so it passes (runtime-verification line 315: `declared_paths_exist=true`) |
| scripts/resolve-dev-artifact-chain.py:1369-1383, :1505-1545 | chain-wave attribution corroborated by predecessors' own `files_created` |
| scripts/resolve-dev-artifact-chain.py:2028-2036 | `file_unions_exact`: canonical == union of shards (dirt-preserving) |
| scripts/stage-owned-hunks.py:180-186 | do-report claim binding (path in `do.files_*` plus a digest) |
| scripts/stage-owned-hunks.py:1134-1149 | adoption admission requires exactly one files_modified claim |
| scripts/lib/candidate_tree.py:69-83 | documents files_* as "GIT-DERIVED… authorship-shaped": the false premise restated |
| scripts/check-late-repair-provenance.py:10, :96, :200-217 | late-repair route reads the lists and owned_edits (route DECIDE in manifest) |
| scripts/laneb-integration-gate.py:774, :790, :1003, :1221 | dead consumer (no live caller; manifest DELETE) |
| scripts/lib/attribution_aggregate_view.py:76-80 | shard-declared set (compared, never adjudicating) |
| hooks/pretool-gitignore-preflight.py:11, :30, :172, :342, :585-588, :771-787 | blocks the orchestrator's next Agent dispatch when a dev list holds a gitignored path, which is a downstream reaction to producer dirt (repair lands on the wrong actor) |
| hooks/subagentstop-artifact-contract-enforce.py:466-469 | reads the lists for the ENTANGLED-only check |
| hooks/lib/contract_runtime.py:274-276 | v1 projection of the lists |
| hooks/posttool-overnight-trace.py:261 | trace projection |
| scripts/aggregate-dev-report.py:504-514 | predecessor `dev.files_created` used as attribution evidence |
| scripts/dev-lifecycle.py:505-508 | comment acknowledging the files_modified/owned_edits gap |

### A3.3 Producer-side fix (minimal, hook-enforced, zero new state files)
- **F-A3-1 (prerequisite, S).** In hooks/lib/attribution_journal.py:253-276 and :317-359, measure
  Bash writes in the git toplevel of `payload.cwd` (fallback `CLAUDE_PROJECT_DIR`) instead of
  only `harness_root()`. Stamp `payload.agent_type` on each event (one line next to :334-335).
  Hash into the measured repo's own object db, or tolerate `unreadable`: the A3 check needs
  only path, `pre_sha==absent` and agent_id. This extends an existing hook-authored channel
  (allowed under C1) and adds no file.
- **F-A3-2 (core, M). Producer-stop gate G2.** In hooks/subagentstop-artifact-contract-enforce.py
  `_wire_ledger_judgment` (:443-495), call the existing
  `attribution_aggregate_view.build_view` with
  `lanes=[{lane: ob.lane or "singular", agent_ids:[payload.agent_id]}]`,
  `session_ids=[payload.session_id]` and `shards={lane: report}`. Every `declared_not_journaled`
  (claimed but not written by this agent) and every `journaled_not_declared` (written but not
  claimed) becomes a blocking finding, returned to the **dev producer** with the exact expected
  list. A fixed namespace filter covers the harness's own outputs (`docs/dev/**`,
  `.claude/dev-registry/**`, `.claude/scratch/**`). Stop writing the sidecar (:426-440, :494);
  the view is consumed in process. This runs under the existing `CLAUDE_OBLIGATION_STOPGATE`
  switch: advisory first, then block (A1).
- **F-A3-3 (S).** Replace agents/dev.md:520-535 with one rule: "list exactly the files you
  wrote (Write/Edit/Bash). The stop gate verifies against the write journal and returns the
  exact list on mismatch." Drop the baseline_dirty_paths subtraction. owned_edits
  (:545-592) is unchanged in this step (D3 follow-up, hold).
- **F-A3-4 (S).** Delete the git-derived provenance and under-report re-derivation in
  agents/qa.md:470-528. Once the producer is journal-verified, those checks FAIL every correct
  report whenever a hook or peer touched a tracked file. This removes a duplicated consumer
  re-check (rollout S12 spirit); it is not a consumer strengthening.
- **F-A3-5 (S). /do.** In hooks/stop-do-report-gate.py (:95-120), compare `do.files_*` with
  journal events where `session_id==payload.session_id`, no agent_id, and
  `ts >= the task_id timestamp` (the task_id is the hook-minted YYYYMMDD-HHMMSS, so no new field
  is needed). Block with the expected list. Align commands/do.md:80 and the gate message
  :264-268 with the dev rule (resolves D3). Depends on B4: today the gate force-allows after 2
  blocks.
- Consumers stay unchanged. The resolve-commit-repos `files_created` exemption, the
  changelog-analyst whitelist and the aggregate union become correct because their input is
  correct. close.md:539 inspecting only files_modified is a consumer issue for the A2/S10
  cutover; no consumer change is proposed here.
- **Risk.** Journal coverage holes (MCP filesystem tools, browser downloads, writes outside any
  repo) would false-block. Mitigate with advisory first, and treat out-of-coverage
  "written-not-claimed" as advisory. Measuring a large product repo costs one `git status` and
  one `hash-object` per Bash call; the same cost is already paid for the harness root. agent_id
  reuse across sessions (agent_resolver.py:23-29) is handled by the session pin.

---

## A4. Producer identity is self-declared

### A4.1 Core resolver
| file:line | what is wrong |
|---|---|
| hooks/lib/agent_resolver.py:8-12 | documented order: `payload.subagent_type`, then cp-state by agent_id, then agent-index by agent_id. **`payload.agent_type` (CLI-supplied) is never consulted** |
| hooks/lib/agent_resolver.py:245-255 | `resolve_agent_type` reads `payload.get("subagent_type")` (:249). That field is not part of a CLI tool-event payload (it belongs to the main agent's Agent `tool_input`), so the real path is always the self-declared registries (T1a/T1b) |
| hooks/lib/agent_resolver.py:17-21 | LOW-10 contract: callers MUST NOT block on None. This makes "skip registration" equal to "no role policy" |
| hooks/lib/agent_resolver.py:159-170, :173-197 | `_lookup_dev_registry_index` / `resolve_dev_registry_entry`: role **and** dev_session_id come from agent-index.json, an agent-writable file in the product repo |
| hooks/lib/agent_resolver.py:203-242 | global cp-state scan across all specs. The STALE-1 docstring (:23-50) admits a bounded window of misattribution by recycled agent ids and "a freshly manufactured dangling entry" |
| hooks/pretool-cp-checkin.py:38-48 | design: the orchestrator writes sentinels, the subagent Reads one, and this hook maps agent_id to the role **from the path the reader chose** |
| hooks/pretool-cp-checkin.py:132-151, :490-503 | `_handle_dev_sentinel`: registration is PreToolUse on Read, so the **file need not exist** (T2a). No comparison with `payload.agent_type` |
| hooks/pretool-cp-checkin.py:167-178 | `existing[agent_id] = …` overwrite: last Read wins (T2c) |
| hooks/pretool-cp-checkin.py:58-60, :317-349, :467-487 | cp-state slot takeover by any Read of the path |
| hooks/pretool-cp-checkin.py:510 | the registry location is `CLAUDE_PROJECT_DIR` or cwd (product repo). Overnight worktree versus main-root splits are documented at dev-overnight.md:236-252 |
| hooks/lib/subagent.py:63-80 | a second caller-identity module (`is_subagent_context`) with no role. 49 hooks read `agent_id` directly (manifest) (D3) |

### A4.2 Every role-reading call site (subagent_type vs agent_type)
| file:line | reads | verdict |
|---|---|---|
| hooks/pretool-tool-policy.py:348-356 | `resolve_agent_type` (subagent_type, then registries); None means exit 0 | wrong source; unregistered subagent unrestricted (T1a) |
| hooks/pretool-tool-policy.py:9-15 | main agent: no role, exit 0 | the orchestrator has **no** write policy (T4a/T4b/T4d) |
| hooks/pretool-subagent-code-block.py:59-74 (and :34-56) | `resolve_agent_type` | wrong source; also warn-only for every outcome (:1-10), so it is dead enforcement (D1) |
| hooks/pretool-overnight-hook-guard.py:197-215 | `resolve_agent_type`, then env `CLAUDE_AGENT_TYPE` | wrong source |
| hooks/pretool-overnight-hook-guard.py:977-995 | `resolve_dev_registry_entry` → dev_session_id → overnight state | self-declared cycle binding |
| hooks/subagentstop-e2e-enforce.py:347-365 | `resolve_dev_registry_entry`; a role other than qa exits 0 **before** the obligation fallback (:354 runs only when entry is None) | a QA that Read dev.json skips E2E entirely (runtime-verification:311) |
| hooks/subagentstop-e2e-enforce.py:386-401 | `/tmp/claude-close-force-<sid>.flag` and `qa.json` `qa_mode=="ba_validation"` exemptions | orchestrator-writable self-release |
| hooks/subagentstop-artifact-contract-enforce.py:794-815 | `expected_role` = agent-index role, or None (no role check) | G2 role binding is self-declared; payload agent_type ignored |
| hooks/subagentstop-artifact-contract-enforce.py:1149-1180 | legacy path keyed on the registry role; force-close flag and qa_mode exemptions | same |
| hooks/subagentstop-codex-enforce.py:58-70 | `resolve_dev_registry_entry` | wrong source; None means fail-open |
| hooks/posttool-codex-skill-ledger.py:72-86 | `resolve_dev_registry_entry` | wrong source |
| hooks/doc_sync/hook_ledger.py:239-248 | `resolve_dev_registry_entry`, role must be dev | wrong source |
| hooks/pretool-cp-state-write-guard.py:126-131 | `_is_subagent` = agent_id or **top-level** subagent_type; main agent exempt (:138) | orchestrator can write cp-state (T4c) |
| hooks/pretool-git-privilege-guard.py:1441-1504 | commit-grant consumer requires a non-empty `agent_id` plus a first-claim attestation; **agent_type never checked** | any dispatched subagent (e.g. a concurrent dev) can claim and spend a commit grant (runtime-verification:403) |
| hooks/lib/commit_pipeline.py:77-85, :595-720 | "Consumer identity: agent_id"; select/claim attestation by agent_id only | same |
| hooks/lib/obligation.py:753-775 | role check only `if expected_role is not None`; callers pass the registry role | G2 L0/L1 resolution inherits the self-declared role |
| hooks/subagentstop-cp-enforce.py:55 | `payload.get("agent_type") or payload.get("subagent_type")` | **correct source**, but used for reporting only and the hook is advisory |
| hooks/lib/subagent_restart.py:519-543, :803 | role from CLI-written `agent-<id>.meta.json` `agentType` | **correct source** (precedent; live: 87 meta files with `agentType` in this container) |
| hooks/pretool-obligation-gate.py:130-131; pretool-aggregate-check.py:132-140; pretool-subagent-enforce.py:129; posttool-subagent-track.py:452-460; posttool-overnight-file-check.py:344; posttool-overnight-trace.py:136-140; pretool-spec-block-foreground-agent.py:73-79; pretool-commit-dispatch-attest.py:88; pretool-block-background-tasks.py:116 | dispatch-time `tool_input.subagent_type` (main agent's Agent call) | legitimate for dispatch events. It is the *declared* type, which is why G1 must bind it to obligation.role (A4.4) |
| scripts/spec-update-contract.py:556; scripts/write-qa-mode.sh:82; scripts/create-overnight-state.sh:908 | `agent_type` inside a cp-state, sentinel or state **file** | not caller identity (file-content field) |

### A4.3 Identity declared in prompts (the voluntary registration protocol)
- "FIRST ACTION: Read …/dev-registry/<sid>/<role>.json" lines: commands/dev.md (10;
  e.g. :304, :434, :503, :628, :736, :790, :865, :1016), commands/dev-command.md (10; :239,
  :329, :391, :457, :553, :604, :662), commands/dev-overnight.md (18; :26-27, :337, :487,
  :643, :743, :974, :1092, :1194, :1255, :1286, :1387, :1596), commands/close.md (10;
  :553-561, :602), agents/graphify.md:22.
- commands/dev.md:220 / dev-command.md:165: "Without that Read, the enforcement hook will fail
  open": the prompts state the enforcement is voluntary.
- commands/dev.md:821: test-writer is told to Read its sentinel "**(or create if absent with
  {agent_type:'test-writer', …})**", so the identity is literally self-authored.
- commands/dev.md:184-213: registry init is "hook pre-done", with an orchestrator Bash
  fallback that writes every sentinel. commands/dev.md:1743 describes `cat > …/dev-registry/<sid>/<role>.json`
  as "subagent-internal scaffolding".
- Profile self-declaration: commands/dev.md:617, :1002; dev-command.md:446, :652;
  dev-overnight.md:1086, :1381, :1505, :1654; close.md:246. `write-qa-mode.sh` (orchestrator)
  sets `qa_mode`, which exempts QA from the E2E and artifact gates (e2e :396-401,
  artifact-contract :1177-1180).
- Design §1.3 G5 (lines 305-308): "The FIRST-ACTION sentinel read survives only as the
  fail-open agent-index channel for tool-policy role resolution (LOW-10)." The design kept the
  self-declared channel for role.

### A4.4 Dispatch-side identity (G1)
| file:line | what is wrong |
|---|---|
| hooks/pretool-obligation-gate.py:9-23, :70-76, :125-132 | trigger = `tool_input.subagent_type ∈ PRODUCER_ROLES`. A producer dispatched as `general-purpose` or another non-producer type is never checked (T3a) |
| hooks/pretool-obligation-gate.py:134-136 | a valid obligation means exit 0. `obligation.role` is never compared with `subagent_type` (T3b) |
| hooks/pretool-obligation-gate.py:137-140 | missing block is gated on `.claude/dev-registry/<sid>/` existing, so producers outside a registry session are unchecked |
| design §1.3 G1 checks 3-4 (doc lines 169-182) | profile-context matrix and fan-out roster consistency are **not implemented** (the hook only calls parse_obligation) |
| hooks/lib/obligation.py:74-80 vs pretool-obligation-gate.py:70-76 | ROLES includes `graphify`, `spec`; PRODUCER_ROLES omits them (two lists, D3) |

### A4.5 Producer artifacts the orchestrator (main agent) can write itself today
Mechanism: pretool-tool-policy exits 0 for no role (main agent). pretool-orchestrator-gate
limits Edit/Write to 1 per turn but allows Bash (5 consecutive). pretool-write-guard.sh blocks
only Write over existing files and Write to `/tmp/claude-bulk-commit-sentinel-*.json`
(:16-33, :152-161). pretool-bash-safety.sh protects only the /tmp grant, user-intent,
attestation and commit-grant namespaces (Layers 1.E-1.E4, :21-67, :1036-1165), by verb
blacklist. pretool-cp-state-write-guard exempts the main agent. Verified T4a-d; prior runs
show main-agent forgeries of dev, qa, close, do, merge and push artifacts passing 20/20 hooks
(runtime-verification:147-150; adv_result.json).

| artifact | designated producer | main-agent write blocked? |
|---|---|---|
| docs/dev/ticket-<T>.md, context-<T>.json, acceptance-criteria-<T>.json | ba | no |
| docs/dev/ba-qa-report-<T>.json | qa (ba_validation) | no |
| docs/dev/test-writer-report-<T>.json, tests/generated/<T>/ | test-writer | no |
| .claude/dev-registry/<sid>/graphify/* | graphify | no |
| docs/dev/dev-report-<T>[-<lane>].json (shards) | dev | no (T4a) |
| docs/dev/dev-report-<T>.json canonical aggregate | orchestrator via scripts/aggregate-dev-report.py | n/a (orchestrator is the producer) but it can also hand-write it |
| docs/dev/qa-report-<T>.json | qa | no (T4b) |
| docs/dev/close-report-<T>.md | close-QA (+ close-report-append.py) | no. Forged "CLOSE: YES" accepted by close-verdict (adv_result.json) |
| docs/dev/{style,cleanliness,prompt}-inspector-report-<T>.json | inspectors | no |
| docs/dev/commit-qa-report-<T>.json | commit-QA | no |
| docs/dev/do-report-<T>.json | hook skeleton + main agent | n/a (main agent is the /do producer); content unverified |
| docs/dev/user-requirement-<sid>.md | prompt-workflow hook (O_EXCL) | create-over blocked by write-guard (Write); Edit and Bash allowed |
| docs/dev/completion-<T>.md, qa-verification-plans.json, overnight cycle-contract | orchestrator | n/a (orchestrator is the producer) |
| .claude/dev-registry/<sid>/<role>.json sentinels | prompt-workflow hook (fallback: orchestrator) | no |
| .claude/dev-registry/agent-index.json | pretool-cp-checkin hook | no (T4c, T4d) |
| .claude/dev-registry/<sid>/{e2e-enforce,artifact-contract-enforce,codex-enforce}.json, qa_mode in qa.json | write-*-enforce.sh / write-qa-mode.sh (orchestrator-run) | no (flags the orchestrator can set or clear to self-release) |
| /tmp/claude-close-force-<sid>.flag | /close --force | no |
| .claude/specs/<id>/cp-state-*.json | spec-check.py | subagents blocked (Write only); main agent exempt |
| overnight-state closeout fields | none (B2) / update-overnight-state.sh | no |
| push-analyst / merge-analyst grants, push-gate token | analysts | no; no agent binding (adv_result.json) |
| /tmp commit grant, dispatch attestation, user-intent sentinels | write-commit-grant.py / pretool-commit-dispatch-attest | Bash verb blacklist only (1.E2-1.E4); consume side requires a subagent agent_id, not a role |
| attribution journal state/attribution-journal/journals/*.jsonl, transcripts, agent meta.json | hooks / CLI | no (agent-writable; this is the in-process trust floor) |

Per-role write policy is also too coarse for single-producer authority:
policies/tool-policy.v1.json:157-175 gives dev `allowed_write_path_prefixes:["*"]`, so dev can
write qa, close and inspector artifacts, agent-index and enforcement flags (P1). The qa prefixes
(:176+) admit close-report-, commit-qa-report- and ba-qa-report- for every QA instance,
whatever its obligation.

### A4.6 Producer-side fix (minimal)
- **F-A4-0 (measurement, S).** Confirm the CLI version in use sends `agent_type` in
  PreToolUse, PostToolUse and SubagentStop payloads for subagent events. Register the existing
  hooks/capability-canary.py for one record, or check live hook logs. Fallback source if the
  field is absent: CLI-written `agentType` in
  `<transcript_dir>/<session_id>/subagents/agent-<agent_id>.meta.json`
  (precedent subagent_restart.py:519-543).
- **F-A4-1 (S).** hooks/lib/agent_resolver.py:245-255: role = `payload.agent_type`, then meta
  `agentType`, then (legacy CLI only) the current registries. Add one helper that returns role
  from the payload and task/cycle from the producer's own obligation (G2 already resolves it).
  All 10 resolver call sites in A4.2 inherit the change without edits, except the
  `resolve_dev_registry_entry` users that need dev_session_id (switch those to the
  obligation's task_id).
- **F-A4-2 (S).** hooks/pretool-cp-checkin.py:490-503: when the payload carries agent_type, do
  not write agent-index (or refuse a sentinel whose role differs). The registry then stops
  being an identity source (hold: files kept). The FIRST ACTION lines become inert; removing
  them is optional prompt diet (E3).
- **F-A4-3 (S). G1.** hooks/pretool-obligation-gate.py:125-146: (a) validate any dispatch whose
  prompt contains an `<obligation` block, whatever its subagent_type; (b) reject when
  `obligation.role != tool_input.subagent_type`. Both checks are stateless.
- **F-A4-4 (S). G2 and e2e.** Pass `expected_role = payload.agent_type` in
  subagentstop-artifact-contract-enforce.py:794-815, so `role_mismatch` in obligation.py:771
  fires. Take the role in subagentstop-e2e-enforce.py:347-365 from the payload, so a spoofed or
  unregistered QA no longer bypasses.
- **F-A4-5 (S).** hooks/pretool-git-privilege-guard.py:1480 (next to the agent_id check):
  require `agent_type == "changelog-analyst"`. Apply the same binding to the push and merge
  grant consumers (cross-ref the cluster owning B/C grants).
- **F-A4-6 (M, user decision). Write authority bound to the obligated producer.** In
  pretool-tool-policy.py, apply a `main` policy when agent_id is absent: deny Write/Edit and
  Bash write-targets on producer-artifact prefixes whose designated producer is a subagent
  (ticket-, context-, acceptance-criteria-, dev-report shards, qa-report-, ba-qa-report-,
  close-report-, commit-qa-report-, *-inspector-report-, test-writer-report-). Keep
  orchestrator-owned outputs allowed (do-report, completion, cycle-contract, canonical aggregate
  via script, sentinels). In tool-policy.v1.json dev (:169-173), add denied prefixes for other
  roles' artifacts. Measured backstop: at G2/G4, the last journal writer (with the agent_type
  stamp from F-A3-1) of each obligated artifact path must be a subagent of the obligated role,
  otherwise a finding or `incomplete`.
- **F-A4-7 (dependency).** Replace the qa_mode and force-flag exemptions (e2e :386-401,
  artifact-contract :1170-1180) with the obligation profile. This is already design S12
  "profile-driven exemptions replace sentinel-sniffing", so it rides A2.

### A4.7 Where the design doc treats this as a trust boundary (for the user's decision)
- §1.2 freshness (lines 133-135): "Deliberate forgery of the internal timestamp is the
  pre-existing report-content trust boundary (pre-mortem M39), not a new surface."
- §3 G1 **M36** (lines 497-500): "coordinated forgery… content-trust boundary (the mechanism
  eliminates honest omission, not coordinated lying); same boundary as today."
- §3 G2 **M14** (lines 510-512): "producer edits a peer's artifact → forbidden by gate text…
  residual = c-ownership interface"; **M39** (line 513): "forged internal timestamp + touch →
  content-trust boundary."
- §1.4.4 (lines 331-345): `CLOSE: YES (FORCED)` is "mechanically forgeable by any docs/dev
  editor… containment is the HUMAN GATE."
- §1.3 G5 (lines 305-308): the FIRST-ACTION sentinel stays as the "fail-open agent-index
  channel for tool-policy role resolution (LOW-10)."
- §2 (lines 424-426): ownership/landing class-c and journal class-d are out of the workstream (X).

Decision points:
1. **Role identity (F-A4-0 to F-A4-5) is not a trust-boundary question.** It is a plain bug:
   the hooks ignore a CLI-supplied field the model cannot set in a hook payload, and use a
   self-declared one. Recommend: fix.
2. **Authorship of producer artifacts (F-A4-6)** moves the design's M14/M36/M39/§1.4.4
   boundary. In-process, everything on disk (artifacts, journal, transcripts, meta.json) is
   writable through Bash, so only the live hook payload is unforgeable. Options:
   (a) keep the design boundary (no F-A4-6);
   (b) recommended: preventive deny for Write/Edit (payload identity) plus heuristic Bash
       targets plus the journal backstop. This catches the observed shortcut class (the
       orchestrator writes or forges a report to get past a gate).
   (c) adversarial-grade, which needs OS-level isolation of hook state and is out of scope.
3. A3 extends the design, which marked ownership as X (§2:424-426). Confirm that the producer
   gate G2 owns file-list authorship.
4. Agent types not listed in tool-policy (general-purpose, Explore, plugin agents): keep
   "allow" (status quo) once the role is read from the payload. Recommend: yes, no behaviour
   change for built-ins.
5. Deleting the QA git-provenance and under-report checks (agents/qa.md:470-528), which are
   required to avoid false FAILs after F-A3-2.

## 5. Ordered minimal plan (cluster A)
1. F-A4-0 measure payload agent_type (S). Gate for every A4 step.
2. F-A4-1 + F-A4-4 + F-A4-3 + F-A4-5: resolver reads agent_type; G2/e2e expected_role; G1
   role binding and obligation-presence trigger; commit grant agent_type (S each, one PR). Tests to
   update: hooks/tests/test_agent_resolver.py:167-172, hooks/tests/test_obligation_gate.py:77,
   tests/test_tool_policy_inference_note.py, tests/test_bash_write_targets_verb_narrowing.py:138,
   :610, tests/fresh-clone-bootstrap-smoke.sh:157-196, examples/guard-demo/run-demo.sh:157
   (all build payloads with top-level `subagent_type`).
3. F-A3-1 journal measures the product repo and stamps agent_type (S). Tests:
   hooks/tests/test_attribution_journal.py:52 currently sets ATTRIBUTION_HARNESS_ROOT to the
   test repo, which hides the product-repo gap; add a case with cwd outside the harness.
4. F-A3-2 + F-A3-3 + F-A3-4: G2 compares claims with the agent's journaled writes; dev.md
   rule; delete the qa.md re-derivation (M). Advisory under CLAUDE_OBLIGATION_STOPGATE, then
   block (needs A1).
5. F-A3-5 /do journal check (S, after B4).
6. F-A4-2 cp-checkin stops writing agent-index (S). Optional: drop FIRST ACTION lines (E3).
7. F-A4-6 only if the user picks option 2(b) (M).
