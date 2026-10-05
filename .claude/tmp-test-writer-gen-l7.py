#!/usr/bin/env python3
"""One-shot generator for tests/generated/20260930-132644-l7/* skeletons + manifest.

Run once by the test-writer subagent for task_id 20260930-132644-l7. Source
ACs are embedded as markdown prose in docs/dev/ticket-20260930-132644-l7.md
(## Acceptance Criteria, AC1..AC17) rather than a BA-emitted JSON file, so
this script performs the Step-10 JSON-shape derivation (per agents/ba.md
"ac_uid = sha256(type+given+when+then+JSON.stringify(check))[:16]") inline,
then follows agents/test-writer.md's CREATE/UPDATE logic and skeleton/
manifest templates verbatim.
"""
import hashlib
import json
import os

ROOT = "/dev/shm/dev-workspace/dot-claude"
TASK_ID = "20260930-132644-l7"
AC_SOURCE = f"docs/dev/ticket-{TASK_ID}.md"
OUT_DIR = os.path.join(ROOT, "tests", "generated", TASK_ID)

ACS = [
    dict(
        id="AC1",
        type="data",
        given='`scripts/aggregate-dev-report.py --task-id "$TASK_ID"` fails',
        when="`/close` runs Step 0 (non-late-repair path)",
        then=(
            "close.md packages a finding and calls the repair orchestrator instead of "
            "executing `|| exit 1`; on `continue=true` execution proceeds to route-select; "
            "on stall, `OPERATION_STALLED` full text is printed and this is the only "
            "legitimate stop"
        ),
        check={
            "file": "commands/close.md",
            "assertions": [
                "Step 0's handling of the aggregate-dev-report.py failure path no longer contains a bare `|| exit 1`",
                "on failure, a finding is packaged and dispatched to the repair orchestrator",
                "on continue=true execution proceeds to route-select",
                "on stall, the full literal text OPERATION_STALLED is printed and this is the only legitimate stop for this site",
            ],
        },
        summary="Step 0 aggregation failure no longer aborts close.md",
    ),
    dict(
        id="AC2",
        type="data",
        given="`close-route-select.py` returns non-zero and `LATE_REPAIR=false`",
        when="Step 0 evaluates `ROUTE_SELECT_RC`",
        then=(
            "the `|| exit 2` at `close.md:235` is replaced by a repair-orchestrator "
            "dispatch with the same continue/stall branching as AC1"
        ),
        check={
            "file": "commands/close.md",
            "assertions": [
                "the || exit 2 previously at close.md:235 (non-late-repair ROUTE_SELECT_RC evaluation) is removed",
                "in its place, a repair-orchestrator dispatch exists with the same continue/stall branching as AC1",
            ],
        },
        summary="Non-late-repair route/resolver failure no longer aborts close.md",
    ),
    dict(
        id="AC3",
        type="data",
        given="the schema-gate python block reports `SCHEMA-GATE FAIL` for any report path",
        when="close.md evaluates the gate's result",
        then=(
            'the "Block before inspector dispatch / QA debate... This is the only '
            'blocking outcome" prose (`close.md:338`) is replaced with '
            "repair-orchestrator dispatch; inspector dispatch proceeds on continue=true"
        ),
        check={
            "file": "commands/close.md",
            "assertions": [
                "the prose stating inspector/QA-debate blocking is 'the only blocking outcome' (pre-lane close.md:338 schema-gate failure) is removed",
                "schema-gate FAIL for any report path dispatches to the repair orchestrator",
                "inspector dispatch proceeds when continue=true",
            ],
        },
        summary="Artifact schema gate failure no longer aborts close.md",
    ),
    dict(
        id="AC4",
        type="data",
        given="`resolve-spec-artifacts.py` fails during the optional cp-state handoff resolution",
        when="close.md evaluates its exit code",
        then=(
            'the `exit 1` at `close.md:366` is replaced by repair-orchestrator dispatch; '
            'on continue, `SPEC_ID=""` / `CP_DIR=""` fallback (already present in the '
            'surrounding `else` logic) is used, exactly like today\'s "else bind '
            'SPEC_ID=\\"\\"" branch'
        ),
        check={
            "file": "commands/close.md",
            "assertions": [
                "the exit 1 at pre-lane close.md:366 (resolve-spec-artifacts.py failure during optional cp-state handoff) is removed",
                "replaced by a repair-orchestrator dispatch",
                'on continue, SPEC_ID="" / CP_DIR="" fallback (the existing else-branch logic) is used',
            ],
        },
        summary="cp-state parse failure no longer aborts close.md",
    ),
    dict(
        id="AC5",
        type="data",
        given="`$DO_REPORT`'s `do.status` is `pending` or `blocked`",
        when="close.md runs the do-report lite preflight",
        then=(
            "a repair-orchestrator finding is dispatched (new wiring, per Edge Case 3) "
            "rather than the check remaining unenforced prose"
        ),
        check={
            "file": "commands/close.md",
            "assertions": [
                "do-report lite preflight for do.status in {pending, blocked} dispatches a repair-orchestrator finding",
                "this check is actually enforced, not left as unenforced prose",
            ],
        },
        summary="do-report lite preflight status failure is newly, properly enforced",
    ),
    dict(
        id="AC6",
        type="data",
        given=(
            "any of: missing close-report (check 1), non-YES last line (check 2), "
            "filename task-id mismatch (check 4), State-C (`:203-212`), chain-recheck "
            "failure (`:222`), or repo-plan-construction failure (`:228-230`)"
        ),
        when="`/commit` evaluates these in Step 3 / Step 5",
        then=(
            "each is a repair-orchestrator dispatch; check 1's finding attempts an "
            "auto-embedded `/close` re-run per turn-1 L7 microstep 4 before falling to "
            "`land_with_disclosure`; repo-plan failure attempts the do/dev-report "
            "`files_created`+owned minimal-plan fallback (turn-1 L7 microstep 5) before "
            "falling to STALL; the literal string `Run /close first.` no longer appears "
            "anywhere in commit.md"
        ),
        check={
            "file": "commands/commit.md",
            "assertions": [
                "none of close-gate checks 1/2/4, State-C (pre-lane :203-212), chain-recheck failure (pre-lane :222), or repo-plan-construction failure (pre-lane :228-230) abort via bare exit",
                "each site is a repair-orchestrator dispatch",
                "check 1's finding attempts an auto-embedded /close re-run before falling to land_with_disclosure",
                "repo-plan failure attempts the do/dev-report files_created+owned minimal-plan fallback before falling to STALL",
                "the literal string 'Run /close first.' does not appear anywhere in commit.md",
            ],
        },
        summary="commit.md's three close-gate checks (1/2/4) and three Step-5 sites no longer abort",
    ),
    dict(
        id="AC7",
        type="data",
        given="the diff produced by this lane",
        when="compared against R2's do-not-delete list plus this ticket's Scope section item 6",
        then=(
            "grant/privilege guard logic, changelog-analyst's flock/CAS/staging mechanics "
            "(other than the Step-7 dispatch-prompt obligation addition), stage-owned-hunks "
            "ownership logic, the three inspector dispatches + QA dispatch + "
            "close-report-writing + spec-update calls, all 5 named hooks, and the "
            "late-repair route's non-State-C internals are byte-identical to their "
            "pre-lane content; AND the Mascot-scoring subsystem (lines 633-677) is "
            "byte-identical to its pre-lane content EXCEPT for exactly the one-paragraph "
            "Post-AC8 reachability note specified in AC16, inserted at the exact anchor "
            "given there; no other byte of the Mascot-scoring section changes, and "
            "scripts/close-scoring-decide.py / scripts/score-update.sh themselves remain "
            "completely untouched (zero bytes). close.md:700 and :723 are byte-identical "
            "with NO exception."
        ),
        check={
            "file": "commands/close.md",
            "assertions": [
                "grant/privilege guard logic is byte-identical to pre-lane content",
                "changelog-analyst's flock/CAS/staging mechanics (excluding the Step-7 dispatch-prompt obligation addition) are byte-identical to pre-lane content",
                "stage-owned-hunks ownership logic is byte-identical to pre-lane content",
                "the three inspector dispatches + QA dispatch + close-report-writing + spec-update calls are byte-identical to pre-lane content",
                "all 5 named hooks are byte-identical to pre-lane content",
                "the late-repair route's non-State-C internals are byte-identical to pre-lane content",
                "the Mascot-scoring subsystem (pre-lane lines 633-677) is byte-identical to pre-lane content except for exactly the AC16 reachability-note paragraph",
                "scripts/close-scoring-decide.py and scripts/score-update.sh are diffed as zero-byte-changed against pre-lane content",
                "close.md:700 and close.md:723 are byte-identical with no exception",
            ],
        },
        summary="Preserved subsystems are provably untouched",
    ),
    dict(
        id="AC8",
        type="data",
        given=(
            "any combination of inspector findings and QA verdict (including a "
            "substantive `CLOSE: NO` QA position reached via ANY of branches "
            "3/4/5/7-fail-over(a)/7-fail-over(b)/8/9-sub(a)/9-sub(b)/10-fall-through "
            "-- close.md:567/569/571/580(x2)/582/586/587/595)"
        ),
        when="Step 2 evaluates its verdict and Step 3 writes the close-report",
        then=(
            "(a) each of those 9 branch/sub-branch sites is rewritten to package "
            "{code, path, detail} and dispatch to the repair orchestrator per Edge Case "
            "8's required design, acting on {continue, disclosures} exactly like every "
            "other site in this ticket; (b) on continue=true the finding becomes a "
            "## Disclosures entry (AC9 format) and Step 2's own Return-value output is "
            "forced to a YES-family line; (c) on continue=false Step 2 prints "
            "OPERATION_STALLED and halts before ever reaching the Return-value contract; "
            "(d) the Return-value legal-forms list no longer lists `CLOSE: NO - <reason>` "
            "as a legal Step-2 output line; (e) under normal (non-STALL) operation the "
            "file's last non-empty line is therefore ALWAYS exactly `CLOSE: YES` or "
            "`CLOSE: YES - with disclosures: <n> items` -- never `CLOSE: NO`"
        ),
        check={
            "file": "commands/close.md",
            "assertions": [
                "each of the 9 branch/sub-branch sites (pre-lane close.md:567/569/571/580x2/582/586/587/595) packages {code,path,detail} and dispatches to the repair orchestrator",
                "on continue=true the finding becomes a ## Disclosures entry and Step 2's Return-value is forced to a YES-family line",
                "on continue=false Step 2 prints OPERATION_STALLED and halts before the Return-value contract",
                "the Return-value legal-forms list no longer lists 'CLOSE: NO - <reason>'",
                "under normal (non-STALL) operation the file's last non-empty line is always exactly 'CLOSE: YES' or 'CLOSE: YES - with disclosures: <n> items', never 'CLOSE: NO'",
            ],
        },
        summary="close-report final line is unconditionally YES-family",
    ),
    dict(
        id="AC9",
        type="data",
        given="one or more findings resolved to `land_with_disclosure`",
        when="the close-report is written",
        then=(
            "it contains a `## Disclosures` heading with one line per item in the exact "
            "format `[code] path: problem | 归因: role(lane) | 修复: action` (field "
            "labels Chinese by design, not translated), and the final line's `<n>` count "
            "matches the number of disclosure lines"
        ),
        check={
            "file": "docs/dev/close-report-*.md",
            "assertions": [
                "the close-report contains a '## Disclosures' heading when one or more findings resolved to land_with_disclosure",
                "each disclosure is one line in the exact format '[code] path: problem | 归因: role(lane) | 修复: action'",
                "the field labels 归因/修复 are left in Chinese, not translated",
                "the final line's <n> count matches the number of disclosure lines",
            ],
        },
        summary="close-report carries a ## Disclosures section in the mandated format",
    ),
    dict(
        id="AC10",
        type="data",
        given="the close-report consumed by `/commit` contains a non-empty `## Disclosures` section",
        when="changelog-analyst constructs the commit message body",
        then=(
            "it appends a `Disclosures: <n>` line followed by up to 10 items in the "
            "same three-element format, and \"see close-report\" beyond 10, with no "
            "separate file created (commit does not duplicate the list into a new file)"
        ),
        check={
            "file": "agents/changelog-analyst.md",
            "assertions": [
                "when the consumed close-report has a non-empty ## Disclosures section, the commit message body appends a 'Disclosures: <n>' line",
                "up to 10 items are listed in the same three-element format",
                "beyond 10 items, the message says 'see close-report' instead of listing them",
                "no separate file is created to duplicate the disclosure list",
            ],
        },
        summary="commit message carries Disclosures: N + itemized list",
    ),
    dict(
        id="AC11",
        type="data",
        given="a human invokes `/close <id> --force` or `/commit --force`",
        when="the flag is parsed",
        then=(
            "execution proceeds through the identical Step 0-3 (close) / Step 3,5,6 "
            "(commit) path as a bare invocation -- no QA/inspector/close-gate/"
            "pre-commit-QA-gate skip occurs; the flag's own description/argument-hint "
            "text is updated to state it is deprecated; the forced 2-step todo list and "
            "hardcoded `CLOSE: YES — FORCED` close-report generation are removed from "
            "close.md"
        ),
        check={
            "file": "commands/close.md",
            "assertions": [
                "/close <id> --force and /commit --force execute through the identical Step 0-3 (close) / Step 3,5,6 (commit) path as a bare invocation",
                "no QA/inspector/close-gate/pre-commit-QA-gate skip occurs under --force",
                "the --force flag's description/argument-hint text states it is deprecated (in both close.md and commands/commit.md)",
                "the forced 2-step todo list is removed from close.md",
                "the hardcoded 'CLOSE: YES — FORCED' close-report generation is removed from close.md",
            ],
        },
        summary="--force is a no-op alias in both files",
    ),
    dict(
        id="AC12",
        type="data",
        given="the new schema file",
        when="validated as JSON Schema draft-07 (matching sibling schemas' `$schema`)",
        then=(
            "it declares `commit_status` as an enum of exactly `committed | "
            "partially_committed | nothing_to_commit | nothing_to_commit_precommitted "
            "| push_gate_reconciled | failed | dryrun`, and `repository_results[]` "
            "items with `order`, `repo_root`, `status` (enum `committed | "
            "nothing_to_commit | failed | not_attempted`), `expected_head`, optional "
            "`commit_sha`, `push_gate_written`, optional `reconciled_commit_sha`/"
            "`reconciliation_basis`/`push_gate_reconciliation_declined`/`failure_code`/"
            "`failure_reason`; `schemas/registry.json` gains the key "
            '`"changelog-status.v1": "changelog-status.v1.json"` alongside (not '
            "replacing) the 3 existing dirty entries"
        ),
        check={
            "file": "schemas/changelog-status.v1.json",
            "assertions": [
                "the file is valid JSON Schema draft-07 (same $schema as sibling schemas)",
                "commit_status is an enum of exactly: committed, partially_committed, nothing_to_commit, nothing_to_commit_precommitted, push_gate_reconciled, failed, dryrun",
                "repository_results[] items declare order, repo_root, status (enum committed|nothing_to_commit|failed|not_attempted), expected_head, optional commit_sha, push_gate_written, optional reconciled_commit_sha/reconciliation_basis/push_gate_reconciliation_declined/failure_code/failure_reason",
                "schemas/registry.json gains the key \"changelog-status.v1\": \"changelog-status.v1.json\" alongside (not replacing) the 3 existing dirty entries",
            ],
        },
        summary="schemas/changelog-status.v1.json exists and is registered",
    ),
    dict(
        id="AC13",
        type="data",
        given="`commit.md` Step 7's Agent-tool prompt for `subagent_type: changelog-analyst`",
        when='the prompt text is parsed for `<obligation v="1">...</obligation>`',
        then=(
            "the enclosed JSON validates against `schemas/obligation.v1.json`, with "
            '`role: "changelog-analyst"`, `pipeline: "commit"`, `profile: '
            '"commit-landing"` (task_id = "$TASK_ID", a string) for BULK=false or '
            '`profile: "commit-bulk"` (task_id = null) for BULK=true, and exactly one '
            '`artifacts[]` entry with `kind: "response_block"`, `begin: "--- '
            'CHANGELOG-ANALYST-STATUS-BEGIN ---"`, `end: "--- '
            'CHANGELOG-ANALYST-STATUS-END ---"`, `format: "json"`, `schema: '
            '"changelog-status.v1"`'
        ),
        check={
            "file": "commands/commit.md",
            "assertions": [
                'commit.md Step 7\'s Agent-tool prompt for subagent_type: changelog-analyst contains a well-formed <obligation v="1">...</obligation> block',
                "the enclosed JSON validates against schemas/obligation.v1.json",
                "role is 'changelog-analyst', pipeline is 'commit'",
                'profile is "commit-landing" with task_id="$TASK_ID" (string) when BULK=false, or "commit-bulk" with task_id=null when BULK=true',
                "exactly one artifacts[] entry: kind=response_block, begin='--- CHANGELOG-ANALYST-STATUS-BEGIN ---', end='--- CHANGELOG-ANALYST-STATUS-END ---', format=json, schema='changelog-status.v1'",
            ],
        },
        summary="changelog-analyst dispatch carries a valid obligation block",
    ),
    dict(
        id="AC14",
        type="hook",
        given=(
            "a throwaway git fixture repo replicating `changelog-analyst.md:908-926`'s "
            "documented command sequence (`git add`, `git diff --cached --no-ext-diff "
            "--no-textconv HEAD -- <path> | sha256sum`, `git restore --staged`, "
            "re-check `git diff --cached --name-only`)"
        ),
        when=(
            "(a) the staged digest mismatches the declared `diff_sha256` and (b) the "
            "subsequent rollback itself fails"
        ),
        then=(
            "a NEW test (in a NEW file -- see Technical Hints 'AC14 test-file "
            "placement') asserts, against ACTUAL git-fixture command execution (not "
            "markdown-prose string matching): (a) the file is excluded from the commit "
            "set and a `WARNING: excluding ...` message shape is produced, and (b) the "
            "whole transaction aborts naming the path. The existing test "
            "tests/test_changelog_analyst_declaration_categories.py::"
            "test_landed_whole_digest_is_verified_after_staging_not_before does NOT "
            "satisfy this AC (prose-level only, no git repo/subprocess/simulated "
            "mismatch) and must not be cited as already sufficient"
        ),
        check={
            "script": "<new test file per Technical Hints 'AC14 test-file placement' -- Dev creates it>",
            "args": [],
            "assertions": [
                "a throwaway git fixture repo replicates the documented command sequence: git add; git diff --cached --no-ext-diff --no-textconv HEAD -- <path> | sha256sum; git restore --staged; re-check git diff --cached --name-only",
                "when the staged digest mismatches the declared diff_sha256, the file is excluded from the commit set and a 'WARNING: excluding ...' message shape is produced",
                "when the subsequent rollback itself fails, the whole transaction aborts naming the path",
                "assertions run against actual git-fixture command execution, not markdown-prose string matching",
                "tests/test_changelog_analyst_declaration_categories.py::test_landed_whole_digest_is_verified_after_staging_not_before does NOT satisfy this AC and must not be cited as sufficient",
            ],
        },
        summary="TOCTOU stage-then-verify has test coverage for both failure paths",
    ),
    dict(
        id="AC15",
        type="hook",
        given="the rewritten `commands/close.md` and `commands/commit.md`",
        when=(
            "grepped per turn-1 §4.4, using the exact three-category disposition rule "
            "for the `CLOSE: NO` check (Category 1 terminal-outcome WRITE site; "
            "Category 2 allowed exception; Category 3 prose/non-terminal reference)"
        ),
        then=(
            "all checks pass; the actual stdout of the grep-and-classify script (not a "
            "hand-summary) is pasted into dev-report per turn-1 §0.1 rule 9; the "
            "classification logic is fully deterministic and anchored structurally, "
            "never by a bare line number alone; Category 1 = "
            "{567,569,571,580,582,586,587,595} (8 lines / 9 branches, all converted); "
            "Category 2 = {213,214} (inside the Late-repair-route section, untouched); "
            "Category 3 = the remaining 17 contested lines plus 622 (left untouched); "
            "the literal substring `CLOSE: NO - <one-sentence reason` does not appear "
            "anywhere in close.md post-rewrite; no bare `|| exit`, `exit 1`, `exit 2` "
            "outside a documented whitelisted STALL-explanation comment; no `Run /close "
            "first.` anywhere in commit.md; `\"repair-orchestrate\"` appears >= 3 times "
            "in EACH file"
        ),
        check={
            "script": "<grep-and-classify script per AC15's three-category disposition rule -- Dev creates it>",
            "args": ["commands/close.md", "commands/commit.md"],
            "assertions": [
                "grep -n 'CLOSE: NO' commands/close.md commands/commit.md collects every hit",
                "Category 1 (bold-assignment **CLOSE: NO** test, or branch-10 fall-through carve-out) = exactly {567,569,571,580,582,586,587,595} pre-rewrite, and NONE of these survive unconverted post-rewrite",
                "Category 2 (historical-compat tag, or late-repair allowlist narrowed by b1+b2) = exactly {213,214} pre-rewrite, left untouched",
                "Category 3 (everything else: prose/non-terminal reference) is left untouched, never a FAIL",
                "the literal substring 'CLOSE: NO - <one-sentence reason' does not appear anywhere in close.md post-rewrite",
                "no bare || exit / exit 1 / exit 2 outside a documented whitelisted STALL-explanation comment",
                "no 'Run /close first.' anywhere in commit.md",
                "'repair-orchestrate' appears >= 3 times in EACH file",
                "the actual stdout of the grep-and-classify script (not a hand-summary) is captured for the dev-report",
            ],
        },
        summary="turn-1 §4.4 mechanical zero-exit assertions pass with a concrete CLOSE: NO disposition rule",
    ),
    dict(
        id="AC16",
        type="data",
        given="the rewritten `commands/close.md`",
        when=(
            "the Mascot-scoring section (`**Mascot scoring — close outcome...**` "
            "heading through the end of its numbered Procedure; pre-lane lines "
            "633-677) is diffed against its pre-lane content"
        ),
        then=(
            "the ONLY difference is one new paragraph inserted immediately after the "
            "section's heading line and its following blank line (directly before the "
            '"Scoring runs ONLY AFTER the close-report file is written..." sentence), '
            "containing verbatim the 'Post-AC8 reachability note (lane L7)' text using "
            "plain backticks (not bold) for every `CLOSE: NO` occurrence; every other "
            "byte of the section (event names, deltas, the helper invocation command, "
            "the decision-matrix bullets themselves, steps 1-6) is unchanged; "
            "`scripts/close-scoring-decide.py` and `scripts/score-update.sh` are diffed "
            "as zero-byte-changed against their pre-lane content"
        ),
        check={
            "file": "commands/close.md",
            "assertions": [
                "the Mascot-scoring section (heading through end of numbered Procedure, pre-lane lines 633-677) differs from pre-lane content ONLY by one new paragraph",
                "the new paragraph is inserted immediately after the section heading line and its following blank line, before the 'Scoring runs ONLY AFTER...' sentence",
                "the new paragraph is the verbatim 'Post-AC8 reachability note (lane L7)' text, using plain backticks (not bold) for every CLOSE: NO occurrence",
                "every other byte of the section (event names, deltas, helper invocation command, decision-matrix bullets, steps 1-6) is unchanged",
                "scripts/close-scoring-decide.py and scripts/score-update.sh are diffed as zero-byte-changed against pre-lane content",
            ],
        },
        summary="Mascot-scoring section carries exactly one documented reachability annotation",
    ),
    dict(
        id="AC17",
        type="data",
        given="the rewritten `commands/close.md`'s `--auto` mode section (pre-lane lines 805-821)",
        when="the `ordinary_reject` bullet (pre-lane lines 816-819) is read post-rewrite",
        then=(
            'the clause "a substantive `CLOSE: NO` verdict from Step 2" is replaced '
            'with "an `OPERATION_STALLED` outcome recorded for this parent" (or an '
            "equivalent paraphrase preserving this exact meaning), the bullet gains one "
            "new sentence citing `scripts/dev-lifecycle.py::classify_walk_outcome()`'s "
            "catch-all design (`hook_deny`/`success`/`partial_abort` matched explicitly, "
            "everything else -- including an `OPERATION_STALLED` tool-result -- falls "
            "through to `ordinary_reject`) as the reason a STALL is correctly treated as "
            "parent-specific record-and-continue rather than batch-wide `hook_deny`-style "
            "abort, and no other byte of lines 805-821 (including the `hook_deny` and "
            "`success` bullets, and the `classify_walk_outcome()` cross-reference "
            "sentence) changes; `scripts/dev-lifecycle.py` itself is diffed as "
            "zero-byte-changed against its pre-lane content"
        ),
        check={
            "file": "commands/close.md",
            "assertions": [
                "in the --auto mode section (pre-lane lines 805-821), the ordinary_reject bullet's clause 'a substantive CLOSE: NO verdict from Step 2' is replaced with 'an OPERATION_STALLED outcome recorded for this parent' (or an equivalent paraphrase preserving this meaning)",
                "the bullet gains one new sentence citing scripts/dev-lifecycle.py::classify_walk_outcome()'s catch-all design (hook_deny/success/partial_abort matched explicitly, everything else including an OPERATION_STALLED tool-result falls through to ordinary_reject) as the reason a STALL is parent-specific record-and-continue rather than batch-wide hook_deny-style abort",
                "no other byte of lines 805-821 changes (including the hook_deny and success bullets, and the classify_walk_outcome() cross-reference sentence)",
                "scripts/dev-lifecycle.py itself is diffed as zero-byte-changed against pre-lane content",
            ],
        },
        summary="--auto mode's ordinary_reject illustrative example cites OPERATION_STALLED, not CLOSE: NO",
    ),
]

SKELETON_TEMPLATE = '''# Auto-generated by agents/test-writer.md from {ac_source}
# AC ID: {id}  ac_uid: {ac_uid}  type: {type}
# Dev is free to REPLACE the body of test_{id_norm}() with a real
# implementation that asserts the GIVEN/WHEN/THEN behaviour. The metadata
# above (AC_UID, AC_TYPE, docstring) MUST be preserved verbatim so QA can
# trace each test back to its source AC entry.

import pytest

AC_UID = "{ac_uid}"
AC_TYPE = "{type}"


def test_{id_norm}():
    """
    GIVEN: {given}
    WHEN:  {when}
    THEN:  {then}
    """
    # TODO(dev): replace the line below with the real test body. While the
    # TEST_INCOMPLETE sentinel is present the test will hard-fail, marking
    # the AC as unimplemented for QA Phase 5.
    pytest.fail(f"TEST_INCOMPLETE: {{AC_UID}} — {summary}")
'''


def normalize_id(ac_id: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in ac_id)


def compute_ac_uid(ac_type: str, given: str, when: str, then: str, check: dict) -> str:
    check_json = json.dumps(check, separators=(",", ":"), ensure_ascii=False)
    payload = f"{ac_type}{given}{when}{then}{check_json}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    active_tests = []
    tests_created = []

    for ac in ACS:
        ac_id = ac["id"]
        id_norm = normalize_id(ac_id)
        ac_uid = compute_ac_uid(ac["type"], ac["given"], ac["when"], ac["then"], ac["check"])
        filename = f"test_{id_norm}_{ac_uid}.py"
        rel_path = f"tests/generated/{TASK_ID}/{filename}"
        abs_path = os.path.join(OUT_DIR, filename)

        content = SKELETON_TEMPLATE.format(
            ac_source=AC_SOURCE,
            id=ac_id,
            ac_uid=ac_uid,
            type=ac["type"],
            id_norm=id_norm,
            given=ac["given"],
            when=ac["when"],
            then=ac["then"],
            summary=ac["summary"],
        )
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)

        tests_created.append(rel_path)
        active_tests.append(
            {
                "task_id": TASK_ID,
                "ac_id": ac_id,
                "ac_uid": ac_uid,
                "type": ac["type"],
                "file": rel_path,
                "status": "active",
                "hook_check": ac["check"],
            }
        )

    manifest = {
        "schema_version": "1.1",
        "task_id": TASK_ID,
        "generated_at": "2026-10-01T00:00:00Z",
        "active_tests": active_tests,
        "archived_tests": [],
    }
    manifest_path = os.path.join(OUT_DIR, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(json.dumps({"tests_created": tests_created, "manifest_path": f"tests/generated/{TASK_ID}/manifest.json"}, indent=2))


if __name__ == "__main__":
    main()
