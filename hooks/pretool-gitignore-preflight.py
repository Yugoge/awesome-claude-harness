#!/usr/bin/env python3
# pretool-gitignore-preflight.py — PreToolUse hook (matcher: Agent)
#
# Purpose: Block Agent dispatches when any declared deliverable in the dev-report
# is matched by .gitignore, preventing a cycle from passing QA but silently
# failing to ship via git (spec-20260520-221059.md Layer A R1, arch-6).
#
# No-op conditions (exits 0):
#   1. The Agent prompt does not contain a docs/dev/dev-report-*.json path reference.
#   2. The referenced dev-report path does not exist on disk (pre-dev dispatch).
#   3. dev.files_modified and dev.files_created are both absent, null, or empty.
#   4. A top-level gitignore_waiver field is present, non-null, and non-empty.
#   5. The dev-report reference occurs inside a declared audit-input list
#      (the `--changed-files` channel) — it is a READ input, not a deliverable
#      manifest. See REVISION TRAIL / discriminator E1 below.
#   6. Every otherwise-blocking path is a commands/close.md-mandated deliverable
#      bound to the referencing report's task-id. See discriminator E2 below.
#   7. The dev-report reference occurs inside a /close Step 2 lane-matrix
#      declaration AND its task-id belongs to the cycle whose close-report the
#      SAME dispatch declares as its deliverable. See discriminator E3 below.
#   8. The reference IS the canonical parent dev-report of the cycle whose
#      close-report the SAME dispatch declares as its deliverable, AND every
#      path it would otherwise block was already recorded by an on-disk lane
#      shard of that same cycle. See discriminator E4 below.
#   9. The dispatch carries a live, unexpired /commit Step 5 commit-grant file
#      for the exact same task-id as the harvested report. See discriminator
#      E5 below.
#
# Blocking condition (exits 2):
#   Any path in dev.files_modified or dev.files_created is matched by .gitignore
#   (git check-ignore --no-index --quiet exits 0 for that path) AND no valid
#   gitignore_waiver is present at the top level of the dev-report JSON.
#
# gitignore_waiver bypass:
#   Add "gitignore_waiver": "<reason>" at the top level of the dev-report JSON.
#   The value must be non-null and non-empty string. Null or empty string is NOT
#   accepted as a waiver.
#
# Input JSON shape (stdin):
#   {"tool_name": "Agent", "tool_input": {"prompt": "... Dev report file: docs/dev/dev-report-<task-id>.json ..."}}
#   Prompt is extracted via data.get("tool_input") or data.get("toolInput") then .get("prompt", "").
#   data.get("prompt") at top level is NEVER used — that key is absent in production payloads.
#
# ---------------------------------------------------------------------------
# REVISION TRAIL
# ---------------------------------------------------------------------------
# 2026-09-05 — spec-20260904-harness-fixes.md R1 (deliberate NARROW exemption).
#
#   Defect: this gate never inspected the dispatch's own deliverable. It matched
#   ANY docs/dev/dev-report-*.json string in the prompt and harvested that
#   report's recorded files_modified/files_created as if they were deliverables
#   of the dispatch being gated. For /close Step 1 (commands/close.md:341-356)
#   the inspector dispatch carries `--changed-files <cycle-diff-file-list>` —
#   an audit INPUT list — and that list itself contains lane dev-report paths.
#   The gate opened a lane report it was only ever asked to READ and refused the
#   dispatch over paths the auditor would never write. Verbatim refusal for the
#   live fan-out cycle 20260809-013317 (5 paths, exit 2), none of which was the
#   dispatch's actual deliverable (docs/dev/style-inspector-report-<TID>.json):
#     BLOCKED: gitignored deliverables detected:
#       docs/dev/acceptance-criteria-20260809-013317-inject.json,
#       docs/dev/dev-report-20260809-013317-inject.json,
#       docs/dev/pre-edit-snapshots-...-inject-iter2/hooks__prompt-workflow.py,
#       docs/dev/pre-edit-snapshots-...-inject-iter2/tests__test_prompt_...py,
#       docs/codex/20260809-013317-inject/dev-iter2.txt
#   Consequence: the close of ANY fan-out cycle died at Step 1 with no bypass.
#
#   DISCRIMINATOR (the single idea both exemptions encode): a deliverable is a
#   path the dispatch WRITES; an audit input is a path it READS. Neither
#   exemption can be satisfied by a caller choosing a suggestive FILENAME —
#   each is bound to something the caller does not control:
#     E1 (declared audit input) is POSITIONAL. It keys on the dispatching
#        command's own `--changed-files` declaration channel. A subagent cannot
#        retroactively alter how it was dispatched, so it cannot place its own
#        deliverable inside that span.
#     E2 (contract-mandated deliverable) is an ENUMERATED SHAPE cross-bound to
#        the harvest source. The basename must be one of exactly four shapes
#        mandated by commands/close.md, under docs/dev/, AND its embedded
#        task-id must equal (or be the fan-out parent of) the task-id of the
#        dev-report that recorded it. An arbitrary name, or a mandated name
#        carrying an unrelated task-id, is still refused.
#
#   NOT changed: the protective semantics. A dispatch whose deliverable is a
#   genuine work product aimed at an ignored path is still blocked, byte-identical
#   message and exit 2. Regression coverage:
#   hooks/tests/test_gitignore_preflight_close_contract.py.
#
# 2026-09-05 (SECOND, SEPARATE NARROW STEP) — same spec R1, second dispatch shape.
#
#   This is a distinct deliberate step, not a widening of the step above. The
#   step above admitted /close **Step 1** (inspector dispatches). It keyed on
#   E1's POSITIONAL `--changed-files` channel. /close **Step 2**
#   (commands/close.md:370-408) has no such channel: it hands the QA gatekeeper
#   the cycle's full lane matrix — for each lane its ticket / context /
#   dev-report / qa-report, plus the parent canonical dev-report — as JSON and
#   as a keyed listing, all of it READ material. Its sole deliverable is
#   `docs/dev/close-report-<P>.md` (commands/close.md:518). Because E1 does not
#   fire, the gate opened those cited lane reports and refused. Verbatim refusal
#   for the live fan-out cycle 20260809-013317 (exit 2; 208 occurrences of 16
#   DISTINCT paths, since each lane report is cited by several projections of
#   the same resolver object), none of which is this dispatch's deliverable:
#     BLOCKED: gitignored deliverables detected:
#       tests/generated/20260809-013317-init/test_AC_{1,2,3,4,5,7,8,9,10}_*.py,
#       tests/generated/20260809-013317-init/{_init_harness,conftest}.py,
#       docs/dev/acceptance-criteria-20260809-013317-inject.json,
#       docs/dev/dev-report-20260809-013317-inject.json,
#       docs/dev/pre-edit-snapshots-...-inject-iter2/hooks__prompt-workflow.py,
#       docs/dev/pre-edit-snapshots-...-inject-iter2/tests__test_prompt_...py,
#       docs/codex/20260809-013317-inject/dev-iter2.txt
#   Consequence: close of a fan-out cycle cleared Step 1 and then died at Step 2.
#
#   DISCRIMINATOR E3 (lane matrix cited as reading material) — a THREE-WAY
#   CONJUNCTION, strictly narrower than E1 alone. All three must hold:
#     (1) DELIVERABLE ANCHOR. The prompt declares, outside every lane-matrix
#         span, exactly ONE `docs/dev/close-report-<P>.md`. That basename is a
#         member of E2's already-closed CONTRACT_DELIVERABLE_PREFIXES set, in
#         the mandated directory. Zero or two-or-more distinct <P> disables E3
#         (ambiguity fails CLOSED).
#     (2) STRUCTURAL SPAN. The citation sits inside a lane-matrix span: the
#         JSON value of one of the resolver's own schema keys, located by
#         real JSON decoding (json.JSONDecoder().raw_decode) — not by prose
#         proximity — or inside the token run of one of two verbatim
#         commands/close.md declaration labels. A decode failure yields no span
#         and therefore fails CLOSED.
#     (3) TASK-ID FAMILY BINDING. The cited report's own task-id must be <P>
#         or a `<P>-<lane>` id, i.e. the resolver's fan-out naming contract
#         (resolve-dev-artifact-chain.py:233 builds lanes as
#         `dev-report-{parent}-{worker}.json`). A lane matrix carrying a
#         foreign task-id is NOT exempt.
#
#   WHY E3 CANNOT BE FORGED BY THE DISPATCHED SUBAGENT: E3 never ADMITS a path.
#   It only declines to treat a cited report as a deliverable MANIFEST. The set
#   of paths that can be admitted as deliverables is still exactly E2's four
#   mandated basenames. So a subagent cannot get a work product of its own
#   choosing through by making a prompt look like a lane matrix — there is no
#   value of the lane matrix that admits `docs/dev/anything-i-like.json`.
#   Forging the suppression itself requires the forger to also name the
#   /close deliverable for the very task-id family it wants suppressed, which a
#   subagent cannot do for someone else's cycle and gains nothing by doing for
#   its own (its own report is still harvested wherever it is cited outside a
#   span — see the anti-laundering rule below).
#
#   ANTI-LAUNDERING (the prior step's rule, deliberately preserved verbatim in
#   behaviour): E3, like E1, is PER-OCCURRENCE, not per-report. If the same
#   report path appears BOTH inside a lane-matrix span AND outside one (e.g. as
#   a `Dev report file:` deliverable manifest), the outside occurrence is still
#   harvested and the dispatch is still refused. Making E3 set-based instead
#   would have been a real fail-open: a /dev QA dispatch that merely mentions a
#   prior `docs/dev/close-report-<P>.md` in passing would have silently
#   disabled the gate for its own deliverable manifest.
#
#   NOT changed: everything else. E1 and E2 keep their exact predicates; the
#   BLOCKED message and exit codes are byte-identical; a dispatch whose
#   deliverable is a genuine work product aimed at an ignored path is refused
#   as before. Regression coverage for BOTH steps lives in
#   hooks/tests/test_gitignore_preflight_close_contract.py.
#
# 2026-09-06 (THIRD, SEPARATE NARROW STEP) — same spec R1, third dispatch shape.
#
#   A third deliberate step, not a widening of either step above. Step one
#   admitted /close Step 1 via E1's POSITIONAL `--changed-files` channel; step
#   two admitted /close Step 2's LANE MATRIX via E3's structural spans. Both
#   left one Step-2 input artifact uncovered: the cycle's CANONICAL PARENT
#   dev-report, which commands/close.md:393-395 mandates be handed to the QA
#   gatekeeper ("plus canonical_dev_report and completion"). When the
#   orchestrator renders that mandate as its own input-artifact line rather
#   than inside a resolver JSON value or a CHAIN_LABELS token run, no E3 span
#   covers it, so the gate opened the canonical report and refused over the
#   ignored paths recorded inside it.
#
#   MEASURED (2026-09-06, live fan-out cycle 20260809-013317, exit 2, 16
#   occurrences of 16 DISTINCT paths). The refusal's path set is exactly the
#   canonical report's own recorded files_modified + files_created filtered to
#   gitignored non-E2 paths (|A| = 16, A == blocked, set difference empty both
#   ways) — that equality is what identifies the canonical citation as the
#   trigger. Confirmed independent of lane naming: two renderings, one
#   enumerating every lane path through E3's projections and one naming lanes
#   only by the resolver's naming pattern with NO lane path present, produced
#   BYTE-IDENTICAL refusals:
#     BLOCKED: gitignored deliverables detected:
#       tests/generated/20260809-013317-init/test_AC_{1,2,3,4,5,7,8,9,10}_*.py,
#       tests/generated/20260809-013317-init/{_init_harness,conftest}.py,
#       docs/dev/acceptance-criteria-20260809-013317-inject.json,
#       docs/dev/dev-report-20260809-013317-inject.json,
#       docs/dev/pre-edit-snapshots-...-inject-iter2/hooks__prompt-workflow.py,
#       docs/dev/pre-edit-snapshots-...-inject-iter2/tests__test_prompt_...py,
#       docs/codex/20260809-013317-inject/dev-iter2.txt
#   Consequence: close of a fan-out cycle cleared Steps 1 and 2's lane matrix
#   and then died on the one remaining mandated Step 2 input.
#
#   DISCRIMINATOR E4 (canonical parent report cited as reading material) — a
#   THREE-WAY CONJUNCTION. Unlike E1 and E3 it is deliberately NOT anchored on
#   prompt position: the mandate at close.md:393-395 prescribes no label, so a
#   prose/label anchor would be exactly the caller-chosen text this step must
#   avoid. All three conjuncts must hold:
#     (1) DELIVERABLE ANCHOR. Reuses E3's anchor unchanged: the prompt declares,
#         outside every lane-matrix span, exactly ONE
#         `docs/dev/close-report-<P>.md`. Zero or two-or-more distinct <P>
#         disables E4 (ambiguity fails CLOSED).
#     (2) CANONICAL IDENTITY. The cited path must be exactly
#         `docs/dev/dev-report-<P>.json` — the resolver's canonical_dev_report
#         name for <P> (resolve-dev-artifact-chain.py). Not a lane id, not a
#         foreign id, not a caller-chosen filename.
#     (3) LANE-SHARD PROVENANCE. Every path the report would otherwise block
#         must ALSO be recorded by an on-disk shard `dev-report-<P>-<lane>.json`
#         — the resolver's fan-out naming contract. This conjunct is read off
#         the filesystem, never off the prompt. A missing, unreadable or
#         malformed shard contributes nothing, so provenance can only shrink:
#         it fails CLOSED. All-or-nothing per report, matching the resolver's
#         own `file_unions_exact` check — a canonical that introduces even one
#         ignored path its shards never recorded is refused in full.
#
#   WHY E4 CANNOT BE FORGED BY THE DISPATCHED SUBAGENT:
#     * Conjunct (2) means a dispatch has exactly ONE suppressible path, and
#       does not get to pick it: the filename is fully determined by <P>, and
#       <P> is fully determined by the close-report the dispatch declares it
#       WRITES. There is no value of any prompt field that makes E4 suppress
#       `docs/dev/anything-i-like.json`.
#     * Conjunct (3) bounds what suppression can admit to paths a lane shard of
#       the SAME cycle already recorded. A subagent's own chosen work product,
#       written into the canonical report, has no shard provenance and is
#       refused with the message and exit code unchanged. Prompt text cannot
#       manufacture this conjunct at all.
#     * A canonical report belonging to an unrelated task fails (2): its name is
#       not `dev-report-<P>.json` for this dispatch's <P>, so it is harvested
#       exactly as before.
#   Honest residual: (3) is corroboration by an independent on-disk artifact
#   under the resolver's naming contract, not a cryptographic proof of
#   authorship. Its strength is that it is not prompt-controlled and that it
#   caps the admissible set at the shard union; it is strictly more than E3
#   requires, which needs only prompt text.
#
#   ANTI-LAUNDERING — preserved, by a different mechanism, and the difference
#   is deliberate. E1 and E3 suppress by prompt POSITION, so they MUST be
#   per-occurrence: a report cited both inside a span and as a deliverable
#   manifest is still harvested at the outside occurrence, or a span would
#   launder a manifest. E4 suppresses by on-disk PROVENANCE, so position is
#   irrelevant and E4 is REPORT-scoped: no span exists to be laundered, and the
#   only paths a canonical citation can ever carry are ones a lane shard of the
#   same cycle already recorded. Stated exactly, because it is a real
#   consequence rather than a claim of equivalence: the canonical parent report
#   IS exempt even in the /dev deliverable-manifest position, once conjuncts
#   (1)-(3) hold (pinned by test_e4_is_report_scoped_not_occurrence_scoped).
#   What that cannot do is launder a caller-chosen work product: without shard
#   provenance the refusal is unchanged in every position — measured, not
#   assumed (test_unauthorised_work_product_still_refused_with_close_report_in
#   _scope, test_e4_canonical_without_shard_provenance_still_refused), and a
#   citation of any OTHER report in the same prompt keeps its own verdict
#   (test_e4_does_not_launder_other_citations).
#
#   NOT changed: everything else. E1, E2 and E3 keep their exact predicates;
#   the BLOCKED message and exit codes are byte-identical; the per-citation
#   listing behaviour is untouched. Regression coverage for ALL THREE steps
#   lives in hooks/tests/test_gitignore_preflight_close_contract.py.
#
# 2026-09-07 (FOURTH STEP — a NARROWING of E2, not an admission of anything).
#
#   The first step's trail above claims E2 admits "exactly four shapes mandated
#   by commands/close.md". An independent review measured that claim FALSE in
#   two ways, and both were reproduced here before anything was changed
#   (2026-09-07, against the predicate as it then stood, src task-id
#   `20260809-013317-init`):
#     (a) EXTENSION DISCARDED. `tid = base[len(prefix):].rsplit('.', 1)[0]`
#         threw the extension away, so the task-id — and therefore the
#         exemption — was identical for every extension and for none:
#           docs/dev/close-report-20260809-013317-init.md    -> True (mandated)
#           docs/dev/close-report-20260809-013317-init.py    -> True (NOT)
#           docs/dev/close-report-20260809-013317-init.sh    -> True (NOT)
#           docs/dev/close-report-20260809-013317-init       -> True (NOT)
#           docs/dev/style-inspector-report-...-init.py      -> True (NOT)
#         The extension is the one part of a mandated name a caller is free to
#         choose, so discarding it handed the caller the whole shape.
#     (b) DASH-PREFIX COLLISION. `src_task_id.startswith(tid + '-')` admitted
#         EVERY dash-delimited ancestor, not the parent:
#           docs/dev/close-report-20260809.md                -> True (NOT: that
#           names a DIFFERENT task's close-report, whose last line /commit reads
#           as the closure verdict)
#   Neither property was pinned by any test, and the corpus could not backstop
#   it: E2 fires for ZERO of the 313 real docs/dev/dev-report-*.json (3255
#   recorded path entries, measured 2026-09-07). An unexercised exemption is
#   exactly where a trail can drift ahead of its code unnoticed.
#
#   E2 AS IT NOW STANDS — the claim above, made true:
#     * MANDATED SHAPE INCLUDES THE EXTENSION. CONTRACT_DELIVERABLE_PREFIXES is
#       now prefix -> mandated extension. close.md mandates the three inspector
#       reports as `.json` (:348-350, :364-366, :427-429) and the close-report
#       as `.md` (:78, :518, :540, :543). A basename must be exactly
#       `<prefix><task-id><mandated-ext>`. Rule, stated so it cannot be read two
#       ways: a name that differs only in extension is a DIFFERENT FILE and the
#       contract does not mandate it, so it is refused. This closes the one
#       degree of freedom (a) left to the caller.
#     * PARENT, NOT ANCESTRY. `startswith(tid + '-')` was an approximation of
#       "belongs to this task"; it is replaced by parent_task_id(), which
#       returns exactly ONE task-id. It cannot be lexical — worker labels here
#       really do contain dashes (21 of 131 measured lane ids), and 6 ids have
#       two on-disk dash-prefix ancestors — so the parent is settled on evidence
#       (longest ancestor with a canonical dev-report on disk), with the
#       immediate lexical parent as the sole fallback when the cycle left no
#       canonical at all. Evidence is read off the filesystem, never off the
#       prompt.
#   Measured after the change, same inputs: (a) `.py`/`.sh`/no-extension and
#   `style-inspector-report-*.md` all -> False; (b) `close-report-20260809.md`
#   -> False, while `close-report-20260809-013317.md` (the real parent) stays
#   True. The whole 313-report corpus keeps a byte-identical verdict and stderr.
#
#   NOT changed: E1, E3 and E4 keep their exact predicates. is_contract_
#   deliverable() gained an optional repo_root (defaulting to get_repo_root(),
#   so existing 2-argument callers are unaffected); no other exemption calls it.
#   The BLOCKED message and exit codes are byte-identical. This step can only
#   REFUSE more than before — it admits nothing new. Regression coverage for all
#   FOUR steps lives in hooks/tests/test_gitignore_preflight_close_contract.py.
#
# 2026-09-17 (FIFTH STEP — a NEW dispatch shape, not covered by E1/E3/E4's
# /close-Step-2 design; disposition by controller, under the user's standing
# "if it doesn't work, fix it" authorization, after a real Step 6 block).
#
#   E1-E4 were all built around /close Step 1/Step 2 dispatch shapes (an
#   auditor's `--changed-files` list, a QA gatekeeper's lane matrix, its
#   canonical-parent citation). None of them anticipated /commit Step 7's own
#   changelog-analyst dispatch, which legitimately reads a task's canonical
#   (or lane) dev-report to build its OWN staging classification — a READ, not
#   a declared deliverable, but one that declares no close-report to anchor E3
#   or E4 on at all. MEASURED (2026-09-17, live re-close of 20260808-035658,
#   exit 2, 8 distinct paths, twice): a changelog-analyst DRYRUN=true dispatch
#   whose prompt named docs/dev/dev-report-20260808-035658.json purely as
#   "read this yourself" instruction text, carrying no lane-matrix span, no
#   close-report deliverable, was refused exactly as a forged deliverable
#   would be — even after E1-E4 were restored from a prior, unrelated,
#   erroneous revert of this whole file. Verbatim:
#     BLOCKED: gitignored deliverables detected:
#       tests/generated/20260808-035658-laner1salvage/test_AC{1,2,3,4}_*.py,
#       docs/dev/salvage-manifest-20260808-035658-laner1salvage.json,
#       docs/dev/salvage-conflict-assessment-20260808-035658-laner1salvage.md,
#       docs/dev/salvage-preservation-proposal-20260808-035658-laner1salvage.md,
#       docs/dev/dev-report-20260808-035658-laner1salvage.json
#
#   DISCRIMINATOR E5 (commit-phase classification read, backstopped by a live
#   commit grant) — deliberately anchored on a DIFFERENT unforgeable artifact
#   than E1/E3/E4, because this dispatch shape has no close-report deliverable
#   to anchor a lane-matrix or canonical-parent conjunct on. ALL of the
#   following must hold, fail CLOSED on any:
#     (1) Every path this report would otherwise block was found via THIS
#         report's OWN dev.files_modified/files_created parse — structurally
#         guaranteed by this file's existing control flow: report_blocked is
#         built ONLY from the currently-opened report's own declared arrays,
#         nothing else in this hook ever independently harvests a gitignored
#         path from prompt prose. E5 therefore cannot enlarge what E1-E4
#         already harvest; it only re-examines the same per-report set.
#     (2) The prompt cites a /tmp/claude-commit-grant-*.json path.
#     (3) That path exists on disk right now, parses as JSON, and its own
#         task_id field equals this report's src_task_id exactly.
#     (4) Its expires_at (ISO-8601) has not passed as of now.
#   A commit-grant file can only be minted by /commit's own Step 5
#   (scripts/write-commit-grant.py), which itself requires a prior CLOSE: YES
#   verdict for that exact task-id (commands/commit.md Step 3's close-gate) —
#   so E5 cannot be satisfied by prompt text alone; it requires an independent,
#   time-bounded, task-id-bound artifact the dispatched subagent did not write
#   and cannot forge from inside its own prompt.
#
#   WHY E5 CANNOT BE FORGED BY THE DISPATCHED SUBAGENT: conjunct (3) reads the
#   grant's task_id off disk, not off the prompt — a prompt cannot claim a
#   grant for a task-id it does not hold one for. Conjunct (4) bounds the
#   window to the grant's own 30-minute TTL, so a stale or already-consumed
#   grant does not exempt. And per (1), E5 never widens the admissible path
#   set beyond what the report itself already declares — it cannot be used to
#   smuggle an unrelated deliverable through, only to re-permit a genuine
#   commit-phase read of a report /commit's own gate already vouched for.
#
#   NOT changed: E1, E2, E3 and E4 keep their exact predicates and ordering;
#   the BLOCKED message and exit codes are byte-identical when E5 does not
#   apply. This step can only REFUSE-then-ADMIT a dispatch shape E1-E4 never
#   admitted at all — it does not widen any existing exemption's own criteria.
# ---------------------------------------------------------------------------

import datetime
import glob
import json
import os
import re
import subprocess
import sys

DEV_REPORT_PATTERN = re.compile(r'docs/dev/dev-report-[A-Za-z0-9._-]+\.json')

# E1: the declaration channel through which /close hands an auditor its READ
# list (commands/close.md:348-356). Positional, not name-based.
AUDIT_INPUT_FLAG = '--changed-files'

# E2: the closed set of deliverable basenames mandated by commands/close.md,
# each mapped to the extension that command mandates for it — the inspector
# reports as JSON (:348-350, :354-356, :364-366, :427-429), the close-report as
# Markdown (:78, :518, :528, :540, :543). The extension is part of the mandated
# shape, not decoration: `close-report-<TID>.py` is a different file and the
# contract does not mandate it. Caller-chosen names and caller-chosen extensions
# are NOT members of this set.
CONTRACT_DELIVERABLE_PREFIXES = {
    'style-inspector-report-': '.json',
    'cleanliness-inspector-report-': '.json',
    'prompt-inspector-report-': '.json',
    'close-report-': '.md',
}
CONTRACT_DELIVERABLE_DIR = 'docs/dev'

_TOKEN_RE = re.compile(r'\S+')
_PATH_CHARS_RE = re.compile(r'^[A-Za-z0-9._/@+-]+$')
_EXT_RE = re.compile(r'\.[A-Za-z0-9]+$')

# E3 (1): the /close Step 2 gatekeeper's sole mandated deliverable
# (commands/close.md:518). <P> is the task-id of the cycle being closed.
CLOSE_REPORT_RE = re.compile(r'docs/dev/close-report-([A-Za-z0-9._-]+)\.md')

# E3 (2a): resolver schema keys whose JSON value carries read-material paths.
# Every dev-report string the resolver emits is reachable under one of these
# (scripts/resolve-dev-artifact-chain.py:233, 496, 502-505, 636, 646).
CHAIN_JSON_KEYS = (
    'canonical_dev_report',
    'dev_report',
    'report_paths',
    'artifact_paths',
    'commit_whitelist_artifacts',
)

# E3 (2b): the three commands/close.md:392-396 declaration labels that project
# read material with no adjacent schema key of their own — measured, not
# guessed: with only CHAIN_JSON_KEYS in place these were the exact remaining
# harvest sites on the live 20260809-013317 Step 2 prompt. `Lane matrix:`,
# `QA inputs:` and `Artifact-chain result:` are deliberately absent: their
# contents are already reached through CHAIN_JSON_KEYS. A label alone never
# exempts anything — E3's other two conjuncts still apply.
CHAIN_LABELS = ('Report paths:', 'Fan-out inputs:', 'Singular inputs:')

# Keys admitted inside a label's token run, i.e. the resolver's lane-row schema
# plus the two parent fields close.md names alongside it. An unknown key ends
# the run, so unrelated prose cannot extend a span.
LANE_ROW_KEYS = frozenset((
    'task_id', 'worker', 'ticket', 'context', 'dev_report', 'qa_report',
    'canonical_dev_report', 'completion',
))

_SEP_RE = re.compile(r'[\s:]*')
_WS_RE = re.compile(r'\s*')


def _is_path_token(token):
    """True if token looks like a file path argument rather than prose or a flag."""
    if token.startswith('-'):
        return False
    if not _PATH_CHARS_RE.match(token):
        return False
    return '/' in token or bool(_EXT_RE.search(token))


def declared_audit_input_spans(prompt):
    """Return [(start, end)] char spans covering each declared audit-input list.

    A span begins after an AUDIT_INPUT_FLAG occurrence and extends over the
    maximal run of following path-shaped, non-flag whitespace-separated tokens.
    It terminates at the first flag or prose token, so a deliverable declaration
    that follows the list ("Write your report to <path>") is NOT inside a span.
    Ambiguity terminates the span early, which fails CLOSED (paths outside a
    span keep the original checking).
    """
    spans = []
    for flag in re.finditer(re.escape(AUDIT_INPUT_FLAG), prompt):
        start = flag.end()
        end = start
        for token in _TOKEN_RE.finditer(prompt, start):
            if not _is_path_token(token.group(0)):
                break
            end = token.end()
        if end > start:
            spans.append((start, end))
    return spans


def _in_any_span(pos, spans):
    return any(start <= pos < end for start, end in spans)


def _json_value_span(prompt, idx):
    """Span of the JSON value at/after idx, decoded for real. None if it is not one.

    Uses the JSON decoder rather than bracket counting or prose proximity, so a
    key followed by anything that is not a well-formed JSON literal yields no
    span at all — which fails CLOSED (the paths keep the original checking).
    """
    start = _SEP_RE.match(prompt, idx).end()
    try:
        _, end = json.JSONDecoder().raw_decode(prompt, start)
    except ValueError:
        return None
    return (start, end) if end > start else None


def _label_run_span(prompt, idx):
    """Span over the run of path / `<lane-key>=<value>` tokens following a label.

    Terminates at the first token that is neither, so a declaration that follows
    the block (prose, a new bullet, a deliverable line) is NOT absorbed.
    """
    start = _WS_RE.match(prompt, idx).end()
    end = start
    for token in _TOKEN_RE.finditer(prompt, start):
        text = token.group(0)
        if '=' in text:
            key, _, value = text.partition('=')
            admitted = key in LANE_ROW_KEYS and bool(value)
        else:
            admitted = _is_path_token(text)
        if not admitted:
            break
        end = token.end()
    return (start, end) if end > start else None


def lane_matrix_spans(prompt):
    """E3 (2): [(start, end)] spans covering /close Step 2 lane-matrix read material."""
    spans = []
    for key in CHAIN_JSON_KEYS:
        for hit in re.finditer(re.escape('"%s"' % key), prompt):
            span = _json_value_span(prompt, hit.end())
            if span:
                spans.append(span)
    for label in CHAIN_LABELS:
        for hit in re.finditer(re.escape(label), prompt):
            span = _json_value_span(prompt, hit.end()) or \
                _label_run_span(prompt, hit.end())
            if span:
                spans.append(span)
    return spans


def close_cycle_task_id(prompt, lane_spans):
    """E3 (1): the single task-id whose close-report this dispatch declares it writes.

    Declarations inside a lane-matrix span do not count (a cited close-report is
    read material, not this dispatch's deliverable). Zero or several distinct
    task-ids means the dispatch is not an unambiguous /close gatekeeper: return
    None and leave every citation subject to the original checking.
    """
    task_ids = {
        hit.group(1) for hit in CLOSE_REPORT_RE.finditer(prompt)
        if not _in_any_span(hit.start(), lane_spans)
    }
    return task_ids.pop() if len(task_ids) == 1 else None


def is_lane_of_cycle(task_id, cycle_task_id):
    """E3 (3): the resolver's fan-out naming contract, parent or `<parent>-<lane>`."""
    return task_id == cycle_task_id or task_id.startswith(cycle_task_id + '-')


def canonical_report_rel(cycle_task_id):
    """E4 (2): the ONE dev-report path E4 can ever suppress for this dispatch.

    The resolver's canonical_dev_report name for the cycle. Fully determined by
    the close-report the dispatch declares it writes, so it is never a
    caller-chosen filename.
    """
    return '%s/dev-report-%s.json' % (CONTRACT_DELIVERABLE_DIR, cycle_task_id)


def shard_recorded_paths(cycle_task_id, repo_root):
    """E4 (3): union of the file lists recorded by this cycle's on-disk lane shards.

    Shard names follow the resolver's fan-out contract
    (resolve-dev-artifact-chain.py:233, `dev-report-<parent>-<worker>.json`).
    An absent, unreadable or malformed shard contributes nothing, so the
    provenance set can only shrink — which fails CLOSED.
    """
    recorded = set()
    pattern = os.path.join(repo_root, CONTRACT_DELIVERABLE_DIR,
                           'dev-report-%s-*.json' % cycle_task_id)
    for shard in glob.glob(pattern):
        try:
            with open(shard) as f:
                body = json.load(f)
        except Exception:
            continue
        dev = body.get('dev') if isinstance(body, dict) else None
        if not isinstance(dev, dict):
            continue
        for key in ('files_modified', 'files_created'):
            value = dev.get(key)
            if isinstance(value, list):
                recorded.update(p for p in value if isinstance(p, str) and p)
    return recorded


def has_lane_shard_provenance(paths, cycle_task_id, repo_root):
    """E4 (3): True only if EVERY given path was already recorded by a lane shard."""
    if not paths:
        return False
    return set(paths).issubset(shard_recorded_paths(cycle_task_id, repo_root))


def source_task_id(report_rel):
    """Task-id embedded in a docs/dev/dev-report-<TID>.json filename."""
    base = os.path.basename(report_rel)
    return base[len('dev-report-'):-len('.json')]


def parent_task_id(src_task_id, repo_root):
    """The ONE task-id whose close artifacts a report for src_task_id may record.

    A lane id is `<parent>-<worker>` (resolve-dev-artifact-chain.py:229), but the
    split point is NOT lexically determined: worker labels really do contain
    dashes here (measured 2026-09-07 over docs/dev — 21 of 131 lane ids, e.g.
    `application-assistant`, `subtask-ab`, `fill-tests`), and 6 ids have two
    distinct dash-prefix ancestors that both exist on disk. So the parent is
    settled on EVIDENCE: the longest ancestor carrying a canonical dev-report.
    Only when the cycle left no canonical at all does it fall back to the
    immediate lexical parent. Either branch yields exactly ONE task-id, never the
    family of every dash-delimited prefix — which is the whole point.
    """
    segments = src_task_id.split('-')
    for cut in range(len(segments) - 1, 0, -1):
        candidate = '-'.join(segments[:cut])
        if os.path.isfile(os.path.join(repo_root, CONTRACT_DELIVERABLE_DIR,
                                       'dev-report-%s.json' % candidate)):
            return candidate
    return '-'.join(segments[:-1]) if len(segments) > 1 else None


def is_contract_deliverable(path, src_task_id, repo_root=None):
    """E2: True only for a commands/close.md-mandated path bound to src_task_id.

    Requires all three: the mandated directory, one of the four mandated
    basenames COMPLETE WITH the extension commands/close.md mandates for it, and
    a task-id that either IS src_task_id or is the one parent task-id src_task_id
    is a lane of (close artifacts are written under the parent TASK_ID). A
    mandated-looking name carrying an unrelated task-id, a foreign extension, or
    an ancestor that is not the parent, is not exempt.
    """
    if os.path.dirname(path) != CONTRACT_DELIVERABLE_DIR:
        return False
    base = os.path.basename(path)
    for prefix, ext in CONTRACT_DELIVERABLE_PREFIXES.items():
        if not (base.startswith(prefix) and base.endswith(ext)):
            continue
        tid = base[len(prefix):-len(ext)]
        if not tid:
            return False
        if tid == src_task_id:
            return True
        return tid == parent_task_id(src_task_id, repo_root or get_repo_root())
    return False


# E5: a live /commit Step 5 commit-grant reference. Minted only by
# scripts/write-commit-grant.py after a passing close-gate check for the
# exact task-id, so its presence and content are not prompt-controlled.
COMMIT_GRANT_PATTERN = re.compile(r'/tmp/claude-commit-grant-[A-Za-z0-9._-]+\.json')


def _parse_iso8601(value):
    """Best-effort ISO-8601 datetime parse. None on any failure (fails CLOSED)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


def has_live_commit_grant(prompt, src_task_id):
    """E5 conjuncts (2)-(4): a live, unexpired /commit Step 5 grant for src_task_id.

    Reads the grant's task_id and expires_at OFF DISK, never off the prompt, so
    a dispatch cannot claim a grant for a task-id it does not hold one for, and
    cannot extend its own admission window past the grant's own TTL. Conjunct
    (1) -- that every otherwise-blocked path came from THIS report's own
    declared arrays -- is a structural property of main()'s existing control
    flow (report_blocked is built solely from the currently-opened report),
    not something this function re-checks.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    for hit in COMMIT_GRANT_PATTERN.finditer(prompt):
        grant_path = hit.group(0)
        if not os.path.isfile(grant_path):
            continue
        try:
            with open(grant_path) as f:
                grant = json.load(f)
        except Exception:
            continue
        if not isinstance(grant, dict):
            continue
        if grant.get('task_id') != src_task_id:
            continue
        expires_at = _parse_iso8601(grant.get('expires_at'))
        if expires_at is None or expires_at <= now:
            continue
        return True
    return False


def get_repo_root():
    """Derive repo root from this file's location (hooks/ is one level below root)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_gitignored(path, repo_root):
    """Return True if git considers the path gitignored (exit 0 = ignored)."""
    result = subprocess.run(
        ['git', 'check-ignore', '--no-index', '--quiet', '--', path],
        cwd=repo_root,
        capture_output=True,
    )
    # exit 0 = ignored, exit 1 = not ignored, exit 128 = error (treat as not ignored)
    return result.returncode == 0


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_input = data.get('tool_input') or data.get('toolInput') or {}
    prompt = tool_input.get('prompt', '')

    # Use findall to capture ALL dev-report paths in prompt (not just the first).
    # If the prompt contains prior context mentioning an older clean report
    # before the current dirty one, .search() would miss the dirty report.
    matches = list(DEV_REPORT_PATTERN.finditer(prompt))
    if not matches:
        sys.exit(0)

    # E1: a dev-report cited inside a declared audit-input list is something the
    # dispatch READS, not a manifest of what it WRITES. Do not harvest it.
    audit_spans = declared_audit_input_spans(prompt)

    # E3: /close Step 2 hands the QA gatekeeper the cycle's whole lane matrix as
    # READ material; its only deliverable is the parent close-report.
    lane_spans = lane_matrix_spans(prompt)
    cycle_task_id = close_cycle_task_id(prompt, lane_spans)

    repo_root = get_repo_root()
    blocked = []

    for match in matches:
        if _in_any_span(match.start(), audit_spans):
            continue

        report_rel = match.group(0)

        if (cycle_task_id is not None
                and _in_any_span(match.start(), lane_spans)
                and is_lane_of_cycle(source_task_id(report_rel), cycle_task_id)):
            continue

        report_path = os.path.join(repo_root, report_rel)

        if not os.path.isfile(report_path):
            continue

        try:
            with open(report_path) as f:
                report = json.load(f)
        except Exception:
            continue

        waiver = report.get('gitignore_waiver')
        if waiver is not None and isinstance(waiver, str) and waiver.strip():
            continue

        dev = report.get('dev') or {}
        files_modified = dev.get('files_modified') or []
        files_created = dev.get('files_created') or []
        # Guard: only process list entries that are non-empty strings.
        # A string-typed files_modified would iterate chars without this check.
        if not isinstance(files_modified, list):
            files_modified = []
        if not isinstance(files_created, list):
            files_created = []
        all_paths = files_modified + files_created

        src_task_id = source_task_id(report_rel)
        report_blocked = []

        for path in all_paths:
            if not (isinstance(path, str) and path):
                continue
            # E2: the close contract's own mandated output paths, bound to this
            # report's task-id. Refusing these made the contract unsatisfiable.
            if is_contract_deliverable(path, src_task_id, repo_root):
                continue
            if is_gitignored(path, repo_root):
                report_blocked.append(path)

        # E4: /close Step 2 must hand the QA gatekeeper this cycle's canonical
        # parent dev-report (commands/close.md:393-395) — a declared audit
        # INPUT. Decline to treat it as a deliverable manifest only when it
        # introduces no ignored path of its own: every one must already carry
        # lane-shard provenance on disk, which no prompt text can manufacture.
        if (report_blocked
                and cycle_task_id is not None
                and report_rel == canonical_report_rel(cycle_task_id)
                and has_lane_shard_provenance(
                    report_blocked, cycle_task_id, repo_root)):
            continue

        # E5: a commit-phase classification read (e.g. changelog-analyst's own
        # Step 6 dispatch), backstopped by a live /commit Step 5 grant for the
        # exact same task-id. See REVISION TRAIL 2026-09-17 above.
        if report_blocked and has_live_commit_grant(prompt, src_task_id):
            continue

        blocked.extend(report_blocked)

    if blocked:
        msg = 'BLOCKED: gitignored deliverables detected: ' + ', '.join(blocked)
        print(msg, file=sys.stderr)
        sys.exit(2)

    sys.exit(0)


if __name__ == '__main__':
    main()
