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
#   9. The dispatch is /commit's changelog-analyst landing of the report's own
#      task: its obligation (profile commit-landing) names that task as its
#      task_id. See discriminator E5 below.
#
# Blocking condition (exits 2):
#   Any path in dev.files_modified or dev.files_created is matched by .gitignore
#   (git check-ignore --no-index --quiet exits 0 for that path) AND no valid
#   gitignore_waiver is present at the top level of the dev-report JSON.
#
# One rule, two callers: gitignored_deliverables() is also G3's rule on a dev
# report a dispatch names (hooks/pretool-aggregate-check.py applies it under
# CLAUDE_OBLIGATION_BARRIER). While G3 is advisory in the tracked settings.json
# this hook keeps blocking on it, the copy P1b's E4 keeps until P2's arming
# commit retires it.
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
#         span, exactly ONE `docs/dev/close-report-<P>.md`, close QA's report
#         in the mandated directory. Zero or two-or-more distinct <P> disables
#         E3 (ambiguity fails CLOSED).
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
#   DISCRIMINATOR E5 (commit-phase classification read). As first written it
#   admitted the dispatch when the prompt cited a live commit grant for the
#   report's task. That made this hook a second decider of the grant, which the
#   privilege guard already decides at the commit (P1b row 11), and it missed
#   dispatches it was written for: with CLAUDE_STATE_DIR set it looked for the
#   grant in the state directory while the grant's writer used /tmp, and an
#   effective report's name gives the task `<task>.effective`, which no grant
#   names. It now reads the
#   dispatch's own obligation instead (2026-10-28, P1b rows 6 and 11; P3 row
#   13's exemption of this profile, delivered early). BOTH must hold, fail
#   CLOSED on either:
#     (1) Every path this report would otherwise block was found via THIS
#         report's OWN dev.files_modified/files_created parse (unchanged:
#         report_blocked is built only from the currently-opened report's
#         declared arrays), so E5 never enlarges what E1-E4 harvest.
#     (2) The dispatch's obligation, parsed through obligation.py as G1 parses
#         it, has profile commit-landing and names the report's task as its
#         task_id. The report's task is the one its name gives, except for a
#         verified late repair's effective report, whose task is the one
#         scripts/late-repair-controller.py resolve_effective_report_state
#         returns that path for in state `verified`, as the changelog-analyst
#         accepts it.
#   A report of any other task named in the same prompt keeps its verdict.
#
# 2026-10-28 — P1b E3: E2 READS THE DECLARATION, NOT A LIST OF NAMES.
#
#   E2's closed set of four basenames (each with its mandated extension) was a
#   table from file names to one command's deliverables, beside the obligations
#   that already declare them: close.md's inspector and close-QA dispatches
#   declare exactly those paths for the cycle's task. E2 now asks
#   obligation.declaring_dispatch whether a dispatch of the report's task, or
#   of its one parent (parent_task_id, unchanged), declares the path, or the
#   canonical todo step of a command the task ran declares it: such a path is a
#   harness artifact, not a work product. A product file a dispatch merely
#   wrote (the reader's `writer` answer) is no declaration and stays refused,
#   as does every name no declaration covers: a foreign extension, a foreign or
#   ancestor task-id, a caller-chosen name. Only a gitignored path asks.
#
# ---------------------------------------------------------------------------

import glob
import importlib.util
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import obligation, schema_registry  # noqa: E402

DEV_REPORT_PATTERN = re.compile(r'docs/dev/dev-report-[A-Za-z0-9._-]+\.json')

# E1: the declaration channel through which /close hands an auditor its READ
# list (commands/close.md:348-356). Positional, not name-based.
AUDIT_INPUT_FLAG = '--changed-files'

# The directory the cycle's reports live in.
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
    `worker-q7x`, `worker-k3m-ab`, `fill-tests`), and 6 ids have two
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


def is_contract_deliverable(path, src_task_id, repo_root=None, project_dir=None):
    """E2: True only for a harness artifact the cycle declares: a path that a
    dispatch of src_task_id, or of the one parent task-id it is a lane of
    (close artifacts are written under the parent TASK_ID), declares, or that
    the canonical todo step of a command that task ran declares
    (obligation.declaring_dispatch, read from the project's dispatch records).
    A file a dispatch merely wrote is a work product, and a name no
    declaration covers (an unrelated task-id, a foreign extension, an ancestor
    that is not the parent) is not exempt.
    """
    project = project_dir or os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd()
    for task in (src_task_id, parent_task_id(src_task_id, repo_root or get_repo_root())):
        if not task:
            continue
        try:
            owner = obligation.declaring_dispatch(task, path, project)
        except Exception:
            owner = None
        if owner and owner.get('source') != 'writer':
            return True
    return False


# E5: the profile of /commit's changelog-analyst dispatch (Steps 6 and 7),
# which names the report of the task it lands.
COMMIT_LANDING_PROFILE = 'commit-landing'


def commit_landing_task_id(prompt):
    """E5 (2): the task a commit-landing dispatch lands, or None.

    Read from the dispatch's own obligation, parsed as G1 parses it; a block
    that does not parse is G1's finding and admits nothing here.
    """
    try:
        parsed = obligation.parse_obligation(
            prompt, known_schema_ids=frozenset(schema_registry.load_registry()))
    except Exception:
        return None
    if not isinstance(parsed, obligation.ParsedObligation):
        return None
    doc = parsed.obligation
    task_id = doc.get('task_id')
    if doc.get('profile') != COMMIT_LANDING_PROFILE or not isinstance(task_id, str):
        return None
    return task_id


def _effective_report_state(repo_root, task_id):
    """resolve_effective_report_state's (state, path) for task_id, the one
    function /commit and the changelog-analyst take an effective report from;
    ('invalid', None) when it cannot be run, which admits nothing."""
    try:
        spec = importlib.util.spec_from_file_location(
            'late_repair_controller',
            os.path.join(repo_root, 'scripts', 'late-repair-controller.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.resolve_effective_report_state(repo_root, task_id)
    except Exception:
        return 'invalid', None


def is_report_of_task(report_rel, task_id, repo_root):
    """E5 (2): True when report_rel is task_id's dev report.

    Its name gives its task, except a late repair's effective report
    (`dev-report-<task>.effective.json`), which belongs to the task
    resolve_effective_report_state returns that path for in state `verified`.
    """
    if source_task_id(report_rel) == task_id:
        return True
    state, path = _effective_report_state(repo_root, task_id)
    return (state == 'verified' and path is not None
            and os.path.realpath(path) == os.path.realpath(os.path.join(repo_root, report_rel)))


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


def gitignored_deliverables(prompt):
    """[(report_rel, [path, ...])] per dev-report citation this dispatch's
    prompt makes whose declared files git ignores, after E1-E5; [] admits it.

    One finding per occurrence, in prompt order, so a report cited twice
    outside every span is listed twice, as this hook always reported it.
    """
    if not isinstance(prompt, str):
        return []
    # Use findall to capture ALL dev-report paths in prompt (not just the first).
    # If the prompt contains prior context mentioning an older clean report
    # before the current dirty one, .search() would miss the dirty report.
    matches = list(DEV_REPORT_PATTERN.finditer(prompt))
    if not matches:
        return []

    # E1: a dev-report cited inside a declared audit-input list is something the
    # dispatch READS, not a manifest of what it WRITES. Do not harvest it.
    audit_spans = declared_audit_input_spans(prompt)

    # E3: /close Step 2 hands the QA gatekeeper the cycle's whole lane matrix as
    # READ material; its only deliverable is the parent close-report.
    lane_spans = lane_matrix_spans(prompt)
    cycle_task_id = close_cycle_task_id(prompt, lane_spans)

    repo_root = get_repo_root()
    landed_task_id = None
    findings = []

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
            if not is_gitignored(path, repo_root):
                continue
            # E2: a harness artifact the cycle declares, bound to this report's
            # task-id. Refusing these made the contract unsatisfiable.
            if is_contract_deliverable(path, src_task_id, repo_root):
                continue
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

        # E5: /commit's changelog-analyst reads the report of the task it
        # lands to classify what it stages. See REVISION TRAIL above.
        if report_blocked:
            if landed_task_id is None:
                landed_task_id = commit_landing_task_id(prompt) or ''
            if landed_task_id and is_report_of_task(report_rel, landed_task_id, repo_root):
                continue
            findings.append((report_rel, report_blocked))

    return findings


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_input = data.get('tool_input') or data.get('toolInput') or {}
    blocked = [path for _, paths in gitignored_deliverables(tool_input.get('prompt', ''))
               for path in paths]
    if blocked:
        msg = 'BLOCKED: gitignored deliverables detected: ' + ', '.join(blocked)
        print(msg, file=sys.stderr)
        sys.exit(2)

    sys.exit(0)


if __name__ == '__main__':
    main()
