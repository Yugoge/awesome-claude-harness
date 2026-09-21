#!/usr/bin/env python3
"""Read-only resolver for singular and fan-out /dev artifact chains.

The resolver never creates, refreshes, or rewrites artifacts.  It validates the
chain rooted at ``docs/dev/dev-report-<task-id>.json`` and emits one stable JSON
document suitable for /dev completion, /close, Close QA, and /commit.

Exit codes:
    0  the complete artifact chain is valid (status == "pass" or
       "pass_with_exceptions" -- see disclosed_exceptions[] in the JSON output;
       a blocked dev-report that carries a legitimate AC-deviation record is
       disclosed this way, in singular and fan-out chains alike (a fan-out
       lane, and the canonical that merges the lane records, each need the
       record to validate) -- never as a plain "pass")
    2  invalid arguments, or a missing/stale/mismatched/ambiguous chain, or a
       deviation record whose shape is not compliant
       (INVALID_AC_DEVIATION_RECORD)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any


SCHEMA_VERSION = 2
IDENTITY_RE = re.compile(
    r"^(?:[-*+]\s*)?(?:task[- ]id|request[- ]id)\s*:\s*(\S+)\s*$",
    re.IGNORECASE,
)
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
WORKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")

# A check that has no analogue on the code path taken.  Distinct from both
# booleans: `False` would claim the check ran and failed, `True` would claim it
# ran and passed.  Consumers must treat this as "unevaluated here", never as a
# pass.
NOT_APPLICABLE = "not_applicable"
SINGULAR_RELATIONAL_REASON = (
    "relational comparison requiring two or more independent shard artifacts; "
    "a singular chain has no second artifact to compare against, so this check "
    "has no singular analogue"
)

# R4 (spec-20260907-115508-lawful-commit-channel.md) gap classification.  A
# stage gap means an entire BA/Dev-stage artifact is absent or empty; every
# other non-qa-report error is a "non-gap" integrity problem that must NOT be
# treated as late-repair eligible even when a real stage gap is also present
# (codex finding #7 / QA round-2 objection 7).
STAGE_GAP_CODES = frozenset({"MISSING_ARTIFACT", "EMPTY_ARTIFACT"})

# Disclosed-exception vocabulary (ticket 20260911-011232).  Additive over the
# already-computed validate_dev()/validate_qa() errors -- those two functions
# are NOT edited in place (Contract D novelty requirement).  Only these three
# codes are ever eligible for reclassification into disclosed_exceptions[].
RECLASSIFIABLE_CODES = frozenset(
    {"INVALID_QA_STATUS", "INVALID_DEV_STATUS", "UNRESOLVED_BLOCKERS"}
)

# primary_cause enum reused VERBATIM from agents/qa.md:1575 -- do not invent a
# divergent enum.  Only "environment" ever excuses a blocking finding here.
QA_ENVIRONMENT_PRIMARY_CAUSE = "environment"

QA_DISCLOSED_EXCEPTION_CLASSIFICATIONS = frozenset(
    {"shared_working_tree_concurrency", "infrastructure_unavailability", "other_environmental"}
)
DEV_STATUS_RATIONALE_CLASSIFICATIONS = frozenset(
    {"pending_commit_handoff", "pending_external_authorization", "other_disclosed_handoff"}
)
DISCLOSED_EXCEPTION_ATTESTATION = (
    "This is a disclosed, evidenced, non-defect exception -- not a defect in "
    "this lane's deliverable."
)

# AC-deviation record (harness backlog #92): THE ONE PLACE that defines the
# machine shape of a legitimately recorded acceptance-criteria deviation.  A
# dev-report that is `blocked` because one AC's literal check fails while the
# user need is satisfied carries, at its top level, the flag (literally true)
# and the record object below; `_ac_deviation_violations` is the single
# validator of this shape and every consumer reads its one result.  Rules:
#   * flag: absent or literally false -> the record is never read; literally
#     true -> the record is validated; any other value is rejected explicitly.
#   * record: an object holding
#       - AC_DEVIATION_IDS_KEY: a non-empty array of unique AC ids, at most
#         AC_DEVIATION_MAX_IDS, each matching AC_DEVIATION_ID_RE via fullmatch;
#       - AC_DEVIATION_VERBATIM_KEY: an object whose AC_DEVIATION_VERBATIM_
#         REQUIRED_KEYS are non-blank strings (the verbatim user need and where
#         it is cited);
#       - AC_DEVIATION_EVIDENCE_KEY: a non-empty object whose every value is a
#         non-blank string, a non-empty array or a non-empty object.
#     Unknown extra keys are tolerated; clause (d) of the close command's
#     verdict branch is deliberately NOT part of the shape (QA decides it).
#   * blocking_issues: a non-empty array whose every entry begins with a
#     recorded id followed by a colon.  This is a coverage / self-consistency
#     check between two fields dev writes itself, NOT a security boundary: QA's
#     independent corroboration of every disclosed entry is the real guard.
AC_DEVIATION_FLAG_KEY = "ac_deviation_with_user_need_satisfied"
AC_DEVIATION_RECORD_KEY = AC_DEVIATION_FLAG_KEY + "_block"
AC_DEVIATION_IDS_KEY = "clause_a_deviated_ac_ids"
AC_DEVIATION_VERBATIM_KEY = "clause_b_user_need_verbatim"
AC_DEVIATION_EVIDENCE_KEY = "clause_c_evidence"
AC_DEVIATION_REQUIRED_RECORD_KEYS = (
    AC_DEVIATION_IDS_KEY,
    AC_DEVIATION_VERBATIM_KEY,
    AC_DEVIATION_EVIDENCE_KEY,
)
AC_DEVIATION_VERBATIM_TEXT_KEY = "text"
AC_DEVIATION_VERBATIM_SOURCE_KEY = "source"
AC_DEVIATION_VERBATIM_REQUIRED_KEYS = (
    AC_DEVIATION_VERBATIM_TEXT_KEY,
    AC_DEVIATION_VERBATIM_SOURCE_KEY,
)
# Applied with fullmatch (never match plus `$`, which accepts a trailing
# newline).  Bounds the dev-authored text that can reach the QA prompt.
AC_DEVIATION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
AC_DEVIATION_MAX_IDS = 32
AC_DEVIATION_REJECTION_CODE = "INVALID_AC_DEVIATION_RECORD"
AC_DEVIATION_DISCLOSURE_KIND = "ac_deviation"
AC_DEVIATION_CLASSIFICATIONS = frozenset({AC_DEVIATION_FLAG_KEY})
# Fan-out merge (harness backlog #92 residual): the canonical of a fan-out chain
# carries ONE record merged from the lanes' records.  These two names are the
# only additions to the shape above: the additive per-lane map inside the
# verbatim object, and the separator qualifying each evidence key with its lane.
AC_DEVIATION_VERBATIM_LANES_KEY = "lanes"
AC_DEVIATION_EVIDENCE_KEY_SEPARATOR = ":"


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _load_aggregate_module() -> ModuleType:
    path = Path(__file__).with_name("aggregate-dev-report.py")
    module = ModuleType("_dev_aggregate")
    module.__file__ = str(path)
    source = path.read_bytes()
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


class ChainValidator:
    def __init__(self, project_root: Path, task_id: str) -> None:
        self.root = project_root
        self.dev_dir = project_root / "docs" / "dev"
        self.task_id = task_id
        self.errors: list[dict[str, str]] = []
        # Every JSON object successfully parsed by read_json(), keyed by its
        # path relative to `root`.  Threaded into _reclassify_disclosed_exceptions
        # (M1) so the reclassification pass never re-reads the filesystem --
        # it only re-examines what validate_dev()/validate_qa() already loaded.
        self.loaded_reports: dict[str, dict[str, Any]] = {}

    def error(self, code: str, path: str, detail: str) -> None:
        self.errors.append({"code": code, "path": path, "detail": detail})

    def read_json(self, path: Path, *, required: bool = True) -> dict[str, Any] | None:
        relative = _rel(path, self.root)
        if not path.is_file():
            if required:
                self.error("MISSING_ARTIFACT", relative, "required JSON artifact is absent")
            return None
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.error("UNREADABLE_ARTIFACT", relative, str(exc))
            return None
        if not raw.strip():
            self.error("EMPTY_ARTIFACT", relative, "JSON artifact is empty")
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.error(
                "MALFORMED_JSON",
                relative,
                f"line {exc.lineno}, column {exc.colno}: {exc.msg}",
            )
            return None
        if not isinstance(value, dict):
            self.error("INVALID_JSON_TYPE", relative, "top-level value must be an object")
            return None
        self.loaded_reports[relative] = value
        return value

    def read_text(self, path: Path, *, required: bool = True) -> str | None:
        relative = _rel(path, self.root)
        if not path.is_file():
            if required:
                self.error("MISSING_ARTIFACT", relative, "required Markdown artifact is absent")
            return None
        try:
            value = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.error("UNREADABLE_ARTIFACT", relative, str(exc))
            return None
        if not value.strip():
            self.error("EMPTY_ARTIFACT", relative, "Markdown artifact is empty")
            return None
        return value

    def validate_json_identity(
        self, value: dict[str, Any], expected: str, path: Path
    ) -> None:
        relative = _rel(path, self.root)
        for key in ("request_id", "task_id"):
            actual = value.get(key)
            if actual != expected:
                self.error(
                    "IDENTITY_MISMATCH",
                    relative,
                    f"{key} is {actual!r}; expected {expected!r}",
                )

    def validate_markdown_identity(self, text: str, expected: str, path: Path) -> None:
        values: list[str] = []
        for line in text.splitlines():
            cleaned = line.strip().replace("**", "").replace("`", "")
            match = IDENTITY_RE.fullmatch(cleaned)
            if match:
                values.append(match.group(1))
        relative = _rel(path, self.root)
        if not values:
            self.error(
                "MISSING_IDENTITY",
                relative,
                "no TASK-ID, Task ID, or Request ID metadata was found",
            )
            return
        for actual in values:
            if actual != expected:
                self.error(
                    "IDENTITY_MISMATCH",
                    relative,
                    f"metadata identity is {actual!r}; expected {expected!r}",
                )

    def validate_dev(self, value: dict[str, Any], expected: str, path: Path) -> None:
        self.validate_json_identity(value, expected, path)
        relative = _rel(path, self.root)
        dev = value.get("dev")
        if not isinstance(dev, dict):
            self.error("INVALID_DEV_STATUS", relative, "dev must be an object")
            return
        if dev.get("status") != "completed":
            self.error(
                "INVALID_DEV_STATUS",
                relative,
                f"dev.status is {dev.get('status')!r}; expected 'completed'",
            )
        for key in ("files_modified", "files_created"):
            paths = dev.get(key)
            if not isinstance(paths, list) or any(
                not isinstance(item, str) or not item or "\x00" in item for item in paths
            ):
                self.error(
                    "INVALID_FILE_LIST",
                    relative,
                    f"dev.{key} must be an array of non-empty path strings",
                )
        blockers = value.get("blocking_issues", [])
        if not isinstance(blockers, list):
            self.error(
                "INVALID_BLOCKING_ISSUES",
                relative,
                "blocking_issues must be an array when present",
            )
        elif blockers:
            self.error(
                "UNRESOLVED_BLOCKERS",
                relative,
                "blocking_issues is not empty",
            )

    def validate_qa(self, value: dict[str, Any], expected: str, path: Path) -> None:
        self.validate_json_identity(value, expected, path)
        relative = _rel(path, self.root)
        qa = value.get("qa")
        # Binary by design (`commands/dev.md`:1354, :1361). A 20260806 relaxation
        # widened this to accept `warning`; /close QA judged it improper and it
        # was reverted -- see the close report for task 20260806-115859.
        if not isinstance(qa, dict) or qa.get("status") != "pass":
            actual = qa.get("status") if isinstance(qa, dict) else None
            self.error(
                "INVALID_QA_STATUS",
                relative,
                f"qa.status is {actual!r}; expected 'pass'",
            )

    def validate_completion(
        self, text: str, expected: str, path: Path, references: list[str]
    ) -> None:
        self.validate_markdown_identity(text, expected, path)
        relative = _rel(path, self.root)
        for reference in references:
            reference_pattern = re.compile(
                rf"(?<![A-Za-z0-9._/-]){re.escape(reference)}(?![A-Za-z0-9._/-])"
            )
            if reference_pattern.search(text) is None:
                self.error(
                    "MISSING_COMPLETION_REFERENCE",
                    relative,
                    f"completion does not reference {reference}",
                )


def _compute_gap_fields(
    errors: list[dict[str, str]],
    qa_report_path: str,
    ac_deviation_paths: frozenset[str] | set[str] = frozenset(),
) -> tuple[list[str], list[str], bool, str]:
    """Classify a singular chain's errors into stage gaps vs. integrity errors.

    THE SOLE PLACE stage_gaps/non_gap_errors/late_repair_eligible/
    gap_classification are computed (R4/AC-6).  Every consumer -- the
    late-repair controller, /close's own gate -- MUST read these fields from
    this resolver's output rather than recomputing them; there is exactly one
    source of truth.

    stage_gaps: the distinct non-qa-report paths whose only problem is that an
    entire BA/Dev/completion-stage artifact is absent or empty
    (MISSING_ARTIFACT / EMPTY_ARTIFACT).  non_gap_errors: every other
    non-qa-report error path -- a genuine integrity problem (malformed JSON,
    identity mismatch, invalid dev status, etc).  late_repair_eligible is true
    only when there is at least one stage gap AND zero non-gap errors: a chain
    with both a real gap and an unrelated integrity error is NOT late-repair
    eligible, even though the coarser gap_classification still reports
    'beyond_qa' for it (codex finding #7 / QA round-2 objection 7).

    ac_deviation_paths: dev-report paths whose blocked status was released as
    an AC-deviation disclosure (their INVALID_DEV_STATUS/UNRESOLVED_BLOCKERS
    errors no longer appear in `errors`).  Such a path is still a genuine
    integrity problem, exactly as its un-released errors were, so when a real
    stage gap is present it joins non_gap_errors and the chain is not
    late-repair eligible; with no stage gap nothing is added and a clean
    deviation pass keeps gap_classification "complete".
    """
    stage_gaps: set[str] = set()
    non_gap_errors: set[str] = set()
    qa_has_error = False
    for entry in errors:
        path = entry.get("path", "")
        if path == qa_report_path:
            qa_has_error = True
            continue
        if entry.get("code") in STAGE_GAP_CODES:
            stage_gaps.add(path)
        else:
            non_gap_errors.add(path)
    if stage_gaps:
        non_gap_errors |= set(ac_deviation_paths)
    late_repair_eligible = bool(stage_gaps) and not non_gap_errors
    if stage_gaps or non_gap_errors:
        gap_classification = "beyond_qa"
    elif qa_has_error:
        gap_classification = "qa_only"
    else:
        gap_classification = "complete"
    return sorted(stage_gaps), sorted(non_gap_errors), late_repair_eligible, gap_classification


def _qa_findings(qa: dict[str, Any]) -> list[Any] | None:
    """Return every entry in qa.all_findings/qa.failures, concatenated.

    Both keys are read (not either/or) -- a report populating only one of the
    two must still be checked in full. A truly absent key contributes zero
    findings (the majority-case shape almost every fixture relies on). A
    *present* key whose value is not a list -- a dict, an explicit JSON
    null, or any other non-list shape -- is malformed and must fail closed:
    this returns None rather than silently treating it as empty, so a
    critical finding hidden inside a wrongly-shaped container can never be
    mistaken for "no findings".
    """
    findings: list[Any] = []
    for key in ("all_findings", "failures"):
        if key not in qa:
            continue
        entries = qa.get(key)
        if not isinstance(entries, list):
            return None
        findings.extend(entries)
    return findings


def _qa_environmental_eligible(value: dict[str, Any] | None) -> bool:
    """M2: is a qa-report's INVALID_QA_STATUS error a disclosed exception?

    ALL of the following must hold, or the finding stays a hard error:
    (a) qa.disclosed_exception is present with an accepted classification,
        non-empty string evidence[], and the exact-literal attestation;
    (b) top-level iteration_needed is literally False;
    (c) every blocking finding (blocks_release is True, or severity is
        "critical") in qa.all_findings/qa.failures carries
        primary_cause == "environment" -- the enum reused verbatim from
        agents/qa.md.  A single disqualifying finding makes the whole report
        ineligible.
    """
    if not isinstance(value, dict):
        return False
    qa = value.get("qa")
    if not isinstance(qa, dict):
        return False
    disclosed = qa.get("disclosed_exception")
    if not isinstance(disclosed, dict):
        return False
    if disclosed.get("classification") not in QA_DISCLOSED_EXCEPTION_CLASSIFICATIONS:
        return False
    evidence = disclosed.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return False
    if any(not isinstance(item, str) or not item for item in evidence):
        return False
    if disclosed.get("attestation") != DISCLOSED_EXCEPTION_ATTESTATION:
        return False
    if value.get("iteration_needed") is not False:
        return False
    qa_findings = _qa_findings(qa)
    if qa_findings is None:
        # A present-but-malformed all_findings/failures container cannot be
        # vouched for as environmental -- fail closed instead of silently
        # treating it as zero findings.
        return False
    for finding in qa_findings:
        if not isinstance(finding, dict):
            # An unreadable finding shape cannot be vouched for as environmental.
            return False
        blocks = finding.get("blocks_release") is True or finding.get("severity") == "critical"
        if blocks and finding.get("primary_cause") != QA_ENVIRONMENT_PRIMARY_CAUSE:
            return False
    return True


def _dev_handoff_eligible(
    dev_value: dict[str, Any] | None, qa_value: dict[str, Any] | None
) -> bool:
    """M3: is a dev-report's needs_review status a disclosed handoff?

    ALL of the following must hold, or the finding stays a hard error:
    (a) dev.status is literally "needs_review" (never "blocked": this function
        keeps that value hard-fail unconditionally, whatever its
        status_rationale says.  The one narrow exception to AC-6 is the
        separate, explicit AC-6 NARROWING documented on
        `_ac_deviation_release_eligible`, which never routes through here)
        with a complete dev.status_rationale (accepted classification,
        non-empty blocked_by and forbidden_action strings);
    (b) the SAME lane's own qa-report independently shows qa.status == "pass".
        If that lane's own QA did not pass, the needs_review claim is
        untrustworthy and the error stays hard.
    """
    if not isinstance(dev_value, dict):
        return False
    dev = dev_value.get("dev")
    if not isinstance(dev, dict):
        return False
    if dev.get("status") != "needs_review":
        return False
    rationale = dev.get("status_rationale")
    if not isinstance(rationale, dict):
        return False
    if rationale.get("classification") not in DEV_STATUS_RATIONALE_CLASSIFICATIONS:
        return False
    blocked_by = rationale.get("blocked_by")
    forbidden_action = rationale.get("forbidden_action")
    if not isinstance(blocked_by, str) or not blocked_by:
        return False
    if not isinstance(forbidden_action, str) or not forbidden_action:
        return False
    if not isinstance(qa_value, dict):
        return False
    qa = qa_value.get("qa")
    return isinstance(qa, dict) and qa.get("status") == "pass"


def _ac_deviation_violations(dev_value: Any) -> list[str] | None:
    """THE single validator of the AC-deviation record (harness backlog #92).

    `dev_value` is the parsed top-level dev-report.  Returns None when the
    record does not apply (anything but a `blocked` report, or the flag absent
    or literally false: the record is then never read, so today's behavior is
    byte-identical), [] when the flag is literally true and the record is
    valid, and otherwise a non-empty list of violations.  Identity checks
    (`is True` / `is False`), never truthiness, so type confusion (the string
    "true", 1, null, a list) is rejected explicitly instead of opening the
    door.  The wording names locations and expectations only and never echoes
    dev-authored text, so the rejection detail stays bounded and inert.  The
    shape itself is defined by the AC_DEVIATION_* constants above; both the
    rejection and the eligibility below consume this one result.
    """
    if not isinstance(dev_value, dict):
        return None
    dev = dev_value.get("dev")
    if not isinstance(dev, dict) or dev.get("status") != "blocked":
        return None
    if AC_DEVIATION_FLAG_KEY not in dev_value:
        return None
    flag = dev_value[AC_DEVIATION_FLAG_KEY]
    if flag is False:
        return None
    if flag is not True:
        return [f"{AC_DEVIATION_FLAG_KEY} must be literally true or false when present"]

    violations: list[str] = []
    valid_ids: list[str] = []
    record = dev_value.get(AC_DEVIATION_RECORD_KEY)
    if not isinstance(record, dict):
        if AC_DEVIATION_RECORD_KEY in dev:
            violations.append(
                f"{AC_DEVIATION_RECORD_KEY} must be a top-level key of the dev-report; "
                "a copy nested under dev is never read"
            )
        elif AC_DEVIATION_RECORD_KEY not in dev_value:
            violations.append(f"top-level {AC_DEVIATION_RECORD_KEY} is absent")
        else:
            violations.append(f"top-level {AC_DEVIATION_RECORD_KEY} must be a JSON object")
    else:
        ids_value = record.get(AC_DEVIATION_IDS_KEY)
        if AC_DEVIATION_IDS_KEY not in record:
            violations.append(f"{AC_DEVIATION_IDS_KEY} is absent from the record")
        elif not isinstance(ids_value, list):
            violations.append(f"{AC_DEVIATION_IDS_KEY} must be an array of AC ids")
        elif not ids_value:
            violations.append(f"{AC_DEVIATION_IDS_KEY} must not be empty")
        else:
            if len(ids_value) > AC_DEVIATION_MAX_IDS:
                violations.append(
                    f"{AC_DEVIATION_IDS_KEY} holds more than {AC_DEVIATION_MAX_IDS} ids"
                )
            checked = ids_value[:AC_DEVIATION_MAX_IDS]
            valid_ids = [
                item
                for item in checked
                if isinstance(item, str) and AC_DEVIATION_ID_RE.fullmatch(item)
            ]
            malformed = [
                index
                for index, item in enumerate(checked)
                if not (isinstance(item, str) and AC_DEVIATION_ID_RE.fullmatch(item))
            ]
            if malformed:
                violations.append(
                    f"{AC_DEVIATION_IDS_KEY} elements at positions {malformed[:8]} are not "
                    f"strings matching the AC id pattern {AC_DEVIATION_ID_RE.pattern}"
                )
            if len(set(valid_ids)) != len(valid_ids):
                violations.append(f"{AC_DEVIATION_IDS_KEY} must hold unique ids")

        verbatim = record.get(AC_DEVIATION_VERBATIM_KEY)
        if AC_DEVIATION_VERBATIM_KEY not in record:
            violations.append(f"{AC_DEVIATION_VERBATIM_KEY} is absent from the record")
        elif not isinstance(verbatim, dict):
            violations.append(
                f"{AC_DEVIATION_VERBATIM_KEY} must be an object with the non-blank string "
                f"keys {list(AC_DEVIATION_VERBATIM_REQUIRED_KEYS)}"
            )
        else:
            for key in AC_DEVIATION_VERBATIM_REQUIRED_KEYS:
                value = verbatim.get(key)
                if not isinstance(value, str) or not value.strip():
                    violations.append(
                        f"{AC_DEVIATION_VERBATIM_KEY}.{key} must be a non-blank string"
                    )

        evidence = record.get(AC_DEVIATION_EVIDENCE_KEY)
        if AC_DEVIATION_EVIDENCE_KEY not in record:
            violations.append(f"{AC_DEVIATION_EVIDENCE_KEY} is absent from the record")
        elif not isinstance(evidence, dict):
            violations.append(f"{AC_DEVIATION_EVIDENCE_KEY} must be an object")
        elif not evidence:
            violations.append(f"{AC_DEVIATION_EVIDENCE_KEY} must not be empty")
        else:
            weak = [
                index
                for index, value in enumerate(evidence.values())
                if not (
                    (isinstance(value, str) and value.strip())
                    or (isinstance(value, (list, dict)) and value)
                )
            ]
            if weak:
                violations.append(
                    f"{AC_DEVIATION_EVIDENCE_KEY} values at positions {weak[:8]} are not a "
                    "non-blank string, a non-empty array or a non-empty object"
                )

    blockers = dev_value.get("blocking_issues")
    if not isinstance(blockers, list) or not blockers:
        violations.append("blocking_issues must be a non-empty array")
    elif valid_ids:
        unattributed = [
            index
            for index, item in enumerate(blockers)
            if not (
                isinstance(item, str)
                and any(item.startswith(f"{ac_id}:") for ac_id in valid_ids)
            )
        ]
        if unattributed:
            violations.append(
                f"blocking_issues entries at positions {unattributed[:8]} do not begin with "
                "a recorded AC id followed by a colon"
            )
    return violations


def _ac_deviation_rejection_detail(violations: list[str]) -> str:
    """Bounded rejection detail: the violations plus the required key set,
    rendered from the AC_DEVIATION_* constants (never re-typed)."""
    required = (
        f"required shape: top-level {AC_DEVIATION_FLAG_KEY} literally true and a top-level "
        f"{AC_DEVIATION_RECORD_KEY} object holding "
        f"{AC_DEVIATION_IDS_KEY} (non-empty array of unique ids, at most "
        f"{AC_DEVIATION_MAX_IDS}, each matching {AC_DEVIATION_ID_RE.pattern}), "
        f"{AC_DEVIATION_VERBATIM_KEY} (object with non-blank string keys "
        f"{', '.join(AC_DEVIATION_VERBATIM_REQUIRED_KEYS)}) and "
        f"{AC_DEVIATION_EVIDENCE_KEY} (non-empty object whose values are non-blank strings, "
        "non-empty arrays or non-empty objects); every blocking_issues entry must begin "
        "with a recorded AC id followed by a colon"
    )
    return ("; ".join(violations) + " | " + required)[:4000]


def _ac_deviation_record(dev_value: Any) -> dict[str, Any]:
    """The (already validated) deviation record of a dev-report, or {}."""
    record = dev_value.get(AC_DEVIATION_RECORD_KEY) if isinstance(dev_value, dict) else None
    return record if isinstance(record, dict) else {}


def _ac_deviation_merge(shards: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """Merge the legitimate per-lane records of a fan-out chain into the ONE
    record the canonical carries.

    Only lanes whose dev-report the single validator accepts (`[]`) contribute,
    in the order given (the aggregator's label order).  Ids: ordered,
    de-duplicated union.  Evidence: every key qualified `<lane label><separator>
    <key>`, so lanes never collide and no value is lost.  Verbatim: the first
    contributing lane's required pair (the shape holds a single pair) plus an
    additive per-lane map holding every contributing lane's pair.  Returns `{}`
    when no lane carries a record, so a chain without a deviation gains no key
    and every existing canonical stays byte-identical and fresh.
    """
    contributing = [
        (label, data) for label, data in shards if _ac_deviation_violations(data) == []
    ]
    if not contributing:
        return {}
    ids: list[str] = []
    evidence: dict[str, Any] = {}
    lanes: dict[str, dict[str, Any]] = {}
    for label, data in contributing:
        record = _ac_deviation_record(data)
        for ac_id in record[AC_DEVIATION_IDS_KEY]:
            if ac_id not in ids:
                ids.append(ac_id)
        for key, value in record[AC_DEVIATION_EVIDENCE_KEY].items():
            evidence[f"{label}{AC_DEVIATION_EVIDENCE_KEY_SEPARATOR}{key}"] = value
        verbatim = record[AC_DEVIATION_VERBATIM_KEY]
        lanes[label] = {key: verbatim[key] for key in AC_DEVIATION_VERBATIM_REQUIRED_KEYS}
    first = next(iter(lanes.values()))
    return {
        AC_DEVIATION_FLAG_KEY: True,
        AC_DEVIATION_RECORD_KEY: {
            AC_DEVIATION_IDS_KEY: ids,
            AC_DEVIATION_VERBATIM_KEY: {**first, AC_DEVIATION_VERBATIM_LANES_KEY: lanes},
            AC_DEVIATION_EVIDENCE_KEY: evidence,
        },
    }


def _ac_deviation_projection(document: Any) -> dict[str, Any]:
    """Extra keys the canonical freshness comparison must include for one
    document: the flag and the record, but only when the single validator says
    the record applies to it (a blocked report whose flag is present and not
    literally false).  Anything else contributes `{}`, so the comparison of a
    document without a record is unchanged."""
    if _ac_deviation_violations(document) is None:
        return {}
    return {
        key: document.get(key) for key in (AC_DEVIATION_FLAG_KEY, AC_DEVIATION_RECORD_KEY)
    }


def ac_deviation_provider() -> SimpleNamespace:
    """The ONE way other scripts obtain the record's shape (never re-typed).

    Three callables built only from the validator and constants above:
    `violations(dev_report)` (exactly `_ac_deviation_violations`),
    `merge(shards)` and `projection(document)`.  The aggregator and the
    lifecycle receive this object; neither holds a copy of the shape.
    """
    return SimpleNamespace(
        violations=_ac_deviation_violations,
        merge=_ac_deviation_merge,
        projection=_ac_deviation_projection,
    )


def _ac_deviation_release_eligible(
    path: str,
    mode: str,
    ac_deviation_paths: frozenset[str] | set[str],
    qa_value: dict[str, Any] | None,
) -> bool:
    """AC-6 NARROWING: may a blocked dev-report's errors become an ac_deviation
    disclosure instead of hard errors?

    AC-6 keeps `dev.status == "blocked"` a hard failure everywhere; this is the
    ONE explicit, narrow exception, hosted next to (never inside)
    `_dev_handoff_eligible`, whose behavior is unchanged.  ALL of these hold,
    or the errors stay hard with today's codes:
    (a) dev.status is literally "blocked" (established by the single validator);
    (b) the top-level flag is literally true;
    (c) the record validates against the AC_DEVIATION_* shape;
    (d) every blocker is attributable to a recorded AC id (blocking_issues
        non-empty, each entry beginning with a recorded id and a colon);
        (a)-(d) are exactly the paths in `ac_deviation_paths`, produced by one
        `_ac_deviation_violations` call per chain;
    (e) singular or fan-out mode; in a fan-out chain the path is a lane's own
        dev-report (the canonical is released by the parent predicate hosted
        below, which reuses this one for every record-bearing lane);
    (f) the SAME lane's own qa-report independently shows qa.status == "pass".

    This decides shape and reachability only.  It never judges whether the
    recorded deviation is real, whether the user need is satisfied, or clause
    (d) of the close command's verdict branch: those stay with QA, which must
    corroborate every disclosed entry.  Release is not a pass -- the chain
    status becomes pass_with_exceptions, never pass.
    """
    if mode not in ("singular", "fanout") or path not in ac_deviation_paths:
        return False
    if not isinstance(qa_value, dict):
        return False
    qa = qa_value.get("qa")
    return isinstance(qa, dict) and qa.get("status") == "pass"


def _parent_ac_deviation_eligible(
    parent_path: str,
    mode: str,
    ac_deviation_paths: frozenset[str] | set[str],
    lane_qa_by_path: dict[str, dict[str, Any] | None],
) -> bool:
    """May the PARENT/canonical dev-report of a fan-out chain be released as an
    ac_deviation disclosure?  Hosted next to `_parent_handoff_eligible`.

    ALL of these hold: the parent path validated on its own (it is in
    `ac_deviation_paths`, which the resolver fills only when the merged record
    passes the single validator); at least one record-bearing lane exists
    (`lane_qa_by_path` maps each record-bearing lane's dev-report path to its
    own qa-report; an empty map is ineligible, like an empty contributing set
    in `_parent_handoff_eligible`); and EVERY one of those lanes satisfies the
    per-lane predicate `_ac_deviation_release_eligible` (its own qa-report
    passes).  One record-bearing lane that is not releasable keeps the
    parent's errors hard.
    """
    if parent_path not in ac_deviation_paths or not lane_qa_by_path:
        return False
    return all(
        _ac_deviation_release_eligible(lane_path, mode, ac_deviation_paths, qa_value)
        for lane_path, qa_value in lane_qa_by_path.items()
    )


def _parent_handoff_eligible(
    dev_value: dict[str, Any] | None,
    contributing_qa_values: list[dict[str, Any] | None],
) -> bool:
    """M3 cross-check for the PARENT/canonical dev-report path (fan-out only).

    Ticket 20260911-011232 iteration 2.  `_dev_handoff_eligible` above locates
    "the same lane's own qa-report" via `_sibling_qa_report_path`, which is
    correct for an ordinary lane (that file exists) but wrong for the
    parent/canonical: a parent-level `qa-report-<bare-task-id>.json`
    structurally does not, and should not, exist in fan-out mode -- only
    lane-level QA reports do (commands/close.md documents parent
    ticket/context/QA as optional, never required).  Constructing that
    filename for the parent path only ever finds nothing, so the parent's own
    needs_review reclassification was permanently unreachable even when every
    contributing lane's own QA independently passed.

    The fix: cross-check against the ACTUAL synthesis source instead.  EVERY
    lane whose own dev-report shows dev.status == "needs_review" (i.e. every
    lane that actually contributed to the parent's synthesized
    dev.status_rationale, mirroring aggregate-dev-report.py's
    `_synthesize_status_rationale`) must have that SAME lane's own qa-report
    independently showing qa.status == "pass".  A single contributing lane
    whose own QA is missing, unreadable, or not a genuine pass keeps the
    parent's error hard -- exactly as `_dev_handoff_eligible` keeps a single
    ordinary lane hard when ITS OWN qa is not a pass.  An empty contributing
    set is also ineligible: a parent needs_review claim with zero lane-level
    evidence behind it is not trustworthy.
    """
    if not isinstance(dev_value, dict):
        return False
    dev = dev_value.get("dev")
    if not isinstance(dev, dict):
        return False
    if dev.get("status") != "needs_review":
        return False
    rationale = dev.get("status_rationale")
    if not isinstance(rationale, dict):
        return False
    if rationale.get("classification") not in DEV_STATUS_RATIONALE_CLASSIFICATIONS:
        return False
    blocked_by = rationale.get("blocked_by")
    forbidden_action = rationale.get("forbidden_action")
    if not isinstance(blocked_by, str) or not blocked_by:
        return False
    if not isinstance(forbidden_action, str) or not forbidden_action:
        return False
    if not contributing_qa_values:
        return False
    for qa_value in contributing_qa_values:
        if not isinstance(qa_value, dict):
            return False
        qa = qa_value.get("qa")
        if not isinstance(qa, dict) or qa.get("status") != "pass":
            return False
    return True


def _sibling_qa_report_path(dev_report_path: str, lane_task_id: str | None) -> str | None:
    """Return the qa-report path for the SAME lane as a dev-report path.

    Both paths are constructed from the same lane/parent identity by
    `_lane_paths`/`_parent_paths` (``dev-report-<id>.json`` and
    ``qa-report-<id>.json`` side by side in docs/dev/) -- rebuilt here from the
    dev-report's own directory rather than re-deriving `dev_dir` independently,
    so it stays correct under any project-root/dev-dir binding.
    """
    if not lane_task_id:
        return None
    directory, _, name = dev_report_path.rpartition("/")
    if not name.startswith("dev-report-") or not name.endswith(".json"):
        return None
    qa_name = f"qa-report-{lane_task_id}.json"
    return f"{directory}/{qa_name}" if directory else qa_name


def _evidence_ref_count(kind: str, value: dict[str, Any] | None) -> int:
    """Diagnostic count of the disclosure's own supporting evidence refs."""
    if not isinstance(value, dict):
        return 0
    if kind == "qa_environmental":
        qa = value.get("qa")
        disclosed = qa.get("disclosed_exception") if isinstance(qa, dict) else None
        evidence = disclosed.get("evidence") if isinstance(disclosed, dict) else None
        return len(evidence) if isinstance(evidence, list) else 0
    if kind == "dev_handoff":
        blocking = value.get("blocking_issues")
        return len(blocking) if isinstance(blocking, list) else 0
    if kind == AC_DEVIATION_DISCLOSURE_KIND:
        evidence = _ac_deviation_record(value).get(AC_DEVIATION_EVIDENCE_KEY)
        return len(evidence) if isinstance(evidence, dict) else 0
    return 0


def _reclassify_disclosed_exceptions(
    errors: list[dict[str, str]],
    loaded_reports: dict[str, dict[str, Any]],
    lane_task_id_by_path: dict[str, str],
    *,
    mode: str,
    parent_dev_report_path: str,
    lane_dev_report_paths: list[str],
    ac_deviation_paths: frozenset[str] | set[str] = frozenset(),
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """M1: additive post-pass moving eligible errors into disclosed_exceptions[].

    Strictly additive over already-computed `errors` -- validate_dev()/
    validate_qa() are never edited in place (Contract D).  A path's
    RECLASSIFIABLE_CODES errors are moved as a group only when every one of
    them is jointly eligible (M2 for a lone INVALID_QA_STATUS; M3 for
    INVALID_DEV_STATUS/UNRESOLVED_BLOCKERS together) -- a single disqualifying
    finding anywhere at that path keeps ALL of that path's errors hard (M2's
    "single mislabeled defect anywhere disqualifies the whole lane").  Every
    other error code (MISSING_ARTIFACT, IDENTITY_MISMATCH, STALE_*, ...) is
    passed through untouched; the original binary checks are unreachable from
    this function.

    `mode`/`parent_dev_report_path`/`lane_dev_report_paths` (ticket
    20260911-011232 iteration 2) exist ONLY to distinguish the
    PARENT/canonical dev-report path from an ordinary lane path in fan-out
    mode -- resolve_chain() always passes mode="singular" with an empty
    lane_dev_report_paths for a singular chain, so `_dev_handoff_eligible`'s
    existing same-lane-own-qa-report lookup below is completely unchanged for
    singular chains and for every ordinary fan-out lane path; only the
    parent path takes the new `_parent_handoff_eligible` cross-check.

    Harness backlog #92 adds a third, mutually exclusive kind in the same
    lane/singular branch: an "ac_deviation" disclosure for a blocked
    dev-report whose legitimate AC-deviation record was validated once by
    `_ac_deviation_violations` (its path is in `ac_deviation_paths`) and whose
    same-lane qa-report passes -- the explicit AC-6 NARROWING documented on
    `_ac_deviation_release_eligible`.  Singular chains and fan-out lanes; the
    fan-out parent/canonical path takes `_parent_ac_deviation_eligible`
    instead (after `_parent_handoff_eligible`).  This function still never
    emits a hard error itself.
    """
    grouped: dict[str, list[dict[str, str]]] = {}
    for entry in errors:
        if entry.get("code") in RECLASSIFIABLE_CODES:
            grouped.setdefault(entry.get("path", ""), []).append(entry)

    eligible: dict[str, tuple[str, str]] = {}
    for path, entries in grouped.items():
        codes_here = {entry["code"] for entry in entries}
        if codes_here == {"INVALID_QA_STATUS"}:
            qa_value = loaded_reports.get(path)
            if _qa_environmental_eligible(qa_value):
                classification = qa_value["qa"]["disclosed_exception"]["classification"]
                eligible[path] = ("qa_environmental", classification)
        elif codes_here and codes_here <= {"INVALID_DEV_STATUS", "UNRESOLVED_BLOCKERS"}:
            dev_value = loaded_reports.get(path)
            if mode == "fanout" and path == parent_dev_report_path:
                # No parent-level qa-report exists to be a "sibling" of --
                # cross-check every actually-contributing lane's own qa
                # instead (see _parent_handoff_eligible docstring).
                contributing_qa_values: list[dict[str, Any] | None] = []
                for lane_dev_path in lane_dev_report_paths:
                    lane_dev_value = loaded_reports.get(lane_dev_path)
                    lane_dev = (
                        lane_dev_value.get("dev")
                        if isinstance(lane_dev_value, dict)
                        else None
                    )
                    if not (
                        isinstance(lane_dev, dict)
                        and lane_dev.get("status") == "needs_review"
                    ):
                        continue
                    lane_qa_path = _sibling_qa_report_path(
                        lane_dev_path, lane_task_id_by_path.get(lane_dev_path)
                    )
                    contributing_qa_values.append(
                        loaded_reports.get(lane_qa_path) if lane_qa_path else None
                    )
                if _parent_handoff_eligible(dev_value, contributing_qa_values):
                    classification = dev_value["dev"]["status_rationale"]["classification"]
                    eligible[path] = ("dev_handoff", classification)
                elif _parent_ac_deviation_eligible(
                    path,
                    mode,
                    ac_deviation_paths,
                    {
                        lane_dev_path: loaded_reports.get(
                            _sibling_qa_report_path(
                                lane_dev_path, lane_task_id_by_path.get(lane_dev_path)
                            )
                            or ""
                        )
                        for lane_dev_path in lane_dev_report_paths
                        if lane_dev_path in ac_deviation_paths
                    },
                ):
                    eligible[path] = (
                        AC_DEVIATION_DISCLOSURE_KIND,
                        min(AC_DEVIATION_CLASSIFICATIONS),
                    )
            else:
                lane_task_id = lane_task_id_by_path.get(path)
                qa_path = _sibling_qa_report_path(path, lane_task_id)
                qa_value = loaded_reports.get(qa_path) if qa_path else None
                if _dev_handoff_eligible(dev_value, qa_value):
                    classification = dev_value["dev"]["status_rationale"]["classification"]
                    eligible[path] = ("dev_handoff", classification)
                elif _ac_deviation_release_eligible(path, mode, ac_deviation_paths, qa_value):
                    eligible[path] = (
                        AC_DEVIATION_DISCLOSURE_KIND,
                        min(AC_DEVIATION_CLASSIFICATIONS),
                    )

    remaining: list[dict[str, str]] = []
    disclosed: list[dict[str, Any]] = []
    for entry in errors:
        code = entry.get("code")
        path = entry.get("path", "")
        if code in RECLASSIFIABLE_CODES and path in eligible:
            kind, classification = eligible[path]
            disclosure = {
                "code": code,
                "path": path,
                "lane_task_id": lane_task_id_by_path.get(path),
                "kind": kind,
                "classification": classification,
                "evidence_ref_count": _evidence_ref_count(kind, loaded_reports.get(path)),
            }
            if kind == AC_DEVIATION_DISCLOSURE_KIND:
                recorded = _ac_deviation_record(loaded_reports.get(path)).get(AC_DEVIATION_IDS_KEY)
                disclosure["deviated_ac_ids"] = list(recorded) if isinstance(recorded, list) else []
            disclosed.append(disclosure)
        else:
            remaining.append(entry)
    return remaining, disclosed


def _dev_report_has_sibling_shards(dev_dir: Path, task_id: str) -> bool:
    """Whether any dev-report-<task_id>-<label>.json sibling exists.

    Consulted only when the canonical dev-report itself cannot be read at
    all.  A genuinely singular chain missing its dev-report has no such
    sibling; any sibling means the shape may actually be a fan-out canonical
    that also happens to be missing/broken, which gap classification does not
    cover this cycle (singular-mode only) -- fail closed to NOT_APPLICABLE
    rather than guess.
    """
    try:
        return any(dev_dir.glob(f"dev-report-{task_id}-*.json"))
    except OSError:
        return False


def _safe_task_id(task_id: str) -> bool:
    return bool(task_id not in {".", ".."} and TASK_ID_RE.fullmatch(task_id))


def _lane_paths(dev_dir: Path, task_id: str, worker: str) -> dict[str, Path]:
    lane_id = f"{task_id}-{worker}"
    return {
        "ticket": dev_dir / f"ticket-{lane_id}.md",
        "context": dev_dir / f"context-{lane_id}.json",
        "dev_report": dev_dir / f"dev-report-{lane_id}.json",
        "qa_report": dev_dir / f"qa-report-{lane_id}.json",
    }


def _is_non_worker_label(label: str, aggregate: ModuleType | None) -> bool:
    """Whether the aggregate classifier treats a filename label as non-lane.

    draft/final/fix/continuation/wip and iterN/retryN/attemptN name a revision of
    one artifact, not a parallel lane.  Shared so every filename-derived label in
    this module is classified by the one predicate; an asymmetry here would let
    the same filename be a lane on one code path and not on another.  Without the
    aggregate module no label can be excluded, which is the fail-closed answer.
    """
    if aggregate is None:
        return False
    lowered = label.lower()
    return bool(
        lowered in aggregate.NON_WORKER_LABELS
        or aggregate.NON_WORKER_LABEL_RE.match(lowered)
    )


def _lane_shard_label(filename: str, task_id: str, aggregate: ModuleType) -> str | None:
    """Return the worker label when filename is a dev-report shard OF task_id.

    Shards are named ``dev-report-<task-id>-<worker>.json`` — the same naming
    ``_lane_paths`` constructs.  Labels the aggregate classifier treats as
    non-worker (draft/final/iterN/...) are not lanes.
    """
    prefix = f"dev-report-{task_id}-"
    suffix = ".json"
    if not filename.startswith(prefix) or not filename.endswith(suffix):
        return None
    label = filename[len(prefix) : -len(suffix)]
    if not WORKER_RE.fullmatch(label):
        return None
    if _is_non_worker_label(label, aggregate):
        return None
    return label


def _self_declared_identity(path: Path) -> str | None:
    """Return the task identity an artifact declares about ITSELF, or ``None``.

    ``None`` means "no usable self-declaration" and deliberately conflates every
    degenerate shape — unreadable, non-UTF-8, empty, malformed JSON, a non-object
    top level, an absent/blank/non-string identity key, or two keys that
    contradict each other.  They collapse to one answer so that damaging or
    omitting one's own identity can never buy a weaker verdict than declaring it
    honestly; the caller treats ``None`` as "not vouched for".

    Silent and read-only by design: the artifacts that belong to the chain are
    read and reported on by the validator's own readers, so raising here would
    duplicate their errors under a second code.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    declared: set[str] = set()
    if path.suffix == ".json":
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, RecursionError):
            return None
        if not isinstance(value, dict):
            return None
        for key in ("request_id", "task_id"):
            actual = value.get(key)
            if not isinstance(actual, str) or not actual.strip():
                return None
            declared.add(actual.strip())
    else:
        for line in raw.splitlines():
            cleaned = line.strip().replace("**", "").replace("`", "")
            match = IDENTITY_RE.fullmatch(cleaned)
            if match is not None:
                declared.add(match.group(1))
    if len(declared) != 1:
        return None
    return declared.pop()


def _self_declared_worker(path: Path, task_id: str) -> str | None:
    """Return the worker an artifact's own identity names, or ``None``.

    A lane identity is exactly ``<task-id>-<worker>``.  An identity naming some
    other task, or the parent task-id with no worker, is outside this task's lane
    namespace and cannot vouch for the file, so it too yields ``None``.
    """
    identity = _self_declared_identity(path)
    if identity is None:
        return None
    prefix = f"{task_id}-"
    if not identity.startswith(prefix):
        return None
    worker = identity[len(prefix) :]
    if not WORKER_RE.fullmatch(worker):
        return None
    return worker


def _parent_paths(dev_dir: Path, task_id: str) -> dict[str, Path]:
    return {
        "ticket": dev_dir / f"ticket-{task_id}.md",
        "context": dev_dir / f"context-{task_id}.json",
        "dev_report": dev_dir / f"dev-report-{task_id}.json",
        "qa_report": dev_dir / f"qa-report-{task_id}.json",
        "completion": dev_dir / f"completion-{task_id}.md",
    }


def _optional_parent_result(
    validator: ChainValidator,
    paths: dict[str, Path],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for kind in ("ticket", "context", "qa_report"):
        path = paths[kind]
        result[kind] = {
            "path": _rel(path, validator.root),
            "present": path.is_file(),
        }
        if not path.is_file():
            continue
        if kind == "ticket":
            text = validator.read_text(path)
            if text is not None:
                validator.validate_markdown_identity(text, validator.task_id, path)
        else:
            value = validator.read_json(path)
            if value is not None:
                if kind == "qa_report":
                    validator.validate_qa(value, validator.task_id, path)
                else:
                    validator.validate_json_identity(value, validator.task_id, path)
    return result


def _find_undeclared_lane_artifacts(
    validator: ChainValidator, workers: list[str], aggregate: ModuleType | None
) -> None:
    """Report artifacts belonging to a lane the canonical never declared.

    Which lane an artifact belongs to is settled by the artifact's own declared
    identity, not by its filename.  A filename suffix is only a label a writer
    chose: a round-two or round-one report of a declared lane carries a
    distinguishing suffix while still declaring — and being — that lane's
    artifact, and attributing it to a lane named after the whole suffix invents a
    worker that never ran.  The identity fields are the authoritative statement of
    what a file is, so they decide.

    The filename remains the fallback, never an escape.  When a file declares no
    usable identity (see ``_self_declared_identity``) it is not vouched for, and
    its filename suffix is attributed to it exactly as before — so an artifact
    cannot evade the check by dropping, blanking, or corrupting its own identity.
    The non-worker label filter applies to that fallback only: it is a heuristic
    about filenames, needed only where no authoritative evidence exists, and
    applying it to a self-declared worker would let a lane exempt itself by
    naming its files after a revision label.
    """
    declared = set(workers)
    families = (
        ("ticket-", ".md"),
        ("context-", ".json"),
        ("qa-report-", ".json"),
    )
    for prefix, suffix in families:
        start = f"{prefix}{validator.task_id}-"
        for path in sorted(validator.dev_dir.glob(f"{start}*{suffix}")):
            worker = _self_declared_worker(path, validator.task_id)
            source = "declared identity"
            if worker is None:
                worker = path.name[len(start) : -len(suffix)]
                source = "filename, no usable declared identity"
                if _is_non_worker_label(worker, aggregate):
                    continue
            if worker not in declared:
                validator.error(
                    "UNDECLARED_LANE_ARTIFACT",
                    _rel(path, validator.root),
                    f"worker {worker!r} (from {source}) is not in canonical "
                    "parallel_workers",
                )


def _declared_union(canonical: dict[str, Any]) -> list[str]:
    """Return the canonical dev-report's declared file union, order-preserving.

    Tolerates a malformed canonical: a non-dict ``dev``, a non-list file list,
    or a non-string entry contributes nothing rather than raising.  ``validate_dev``
    already reports those shapes under their own error codes.
    """
    dev = canonical.get("dev")
    if not isinstance(dev, dict):
        return []
    union: list[str] = []
    for key in ("files_modified", "files_created"):
        entries = dev.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str) and entry and entry not in union:
                union.append(entry)
    return union


def _check_declared_paths_exist(
    validator: ChainValidator, canonical: dict[str, Any], result: dict[str, Any]
) -> None:
    """Every path the canonical declares must exist on disk.

    Reached by both the singular and the fan-out branch: a report claiming files
    it did not produce must not be admitted, whichever way it was assembled.
    Existence is deliberately the weakest defensible predicate -- a directory or
    a symlink, including a broken one, counts as present, because the claim under
    test is "the report named a path that is not there", not "it named a regular
    file".  Read-only: the resolver never creates the paths it looks for.

    One error per absent path, so the report enumerates every miss rather than
    aggregating them into a single opaque failure.
    """
    missing: list[str] = []
    for declared in _declared_union(canonical):
        target = validator.root / declared
        try:
            present = target.exists() or target.is_symlink()
        except OSError:
            present = False
        if not present:
            missing.append(declared)
    result["checks"]["declared_paths_exist"] = not missing
    for declared in missing:
        validator.error(
            "ABSENT_DECLARED_PATH",
            result["canonical_dev_report"],
            f"dev-report declares {declared!r}, which does not exist on disk",
        )


def _workers_declaration_state(canonical: dict[str, Any]) -> str:
    """Classify how the canonical declares ``parallel_workers``.

    ``absent`` and ``empty`` are different facts about an aggregate and must not
    be conflated: a canonical that LOST the key is structurally indistinguishable
    from a genuine singular chain, and would otherwise degrade silently into the
    unchecked branch.
    """
    if "parallel_workers" not in canonical:
        return "absent"
    value = canonical.get("parallel_workers")
    if isinstance(value, list) and not value:
        return "empty"
    return "declared"


def _base_result(task_id: str, canonical: str, completion: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "fail",
        "mode": "unknown",
        "task_id": task_id,
        "canonical_dev_report": canonical,
        "completion": completion,
        "parallel_workers": [],
        "parallel_workers_declaration": "unknown",
        "lanes": [],
        "optional_parent_artifacts": {},
        "report_paths": [],
        "artifact_paths": [],
        "commit_whitelist_artifacts": [],
        "qa_inputs": [],
        "checks": {
            "canonical_fresh": False,
            "file_unions_exact": False,
            "declared_paths_exist": False,
        },
        "checks_not_applicable": {},
        "errors": [],
        # R4 additive fields (spec-20260907-115508-lawful-commit-channel.md).
        # NOT_APPLICABLE by default; overwritten only where determinable (see
        # _compute_gap_fields call sites in resolve_chain()).
        "stage_gaps": NOT_APPLICABLE,
        "non_gap_errors": NOT_APPLICABLE,
        "late_repair_eligible": NOT_APPLICABLE,
        "gap_classification": NOT_APPLICABLE,
        # Disclosed-exception vocabulary (ticket 20260911-011232).  Populated
        # by _reclassify_disclosed_exceptions(); [] means no eligible
        # reclassification occurred (either no reclassifiable error existed,
        # or none was eligible) -- never absorbed into a bare "pass".
        "disclosed_exceptions": [],
    }


def resolve_chain(project_root: Path | str, task_id: str) -> dict[str, Any]:
    """Resolve and validate one artifact chain without mutating the filesystem."""
    root = Path(project_root).resolve()
    task_id = task_id.strip()
    dev_dir = root / "docs" / "dev"
    parents = _parent_paths(dev_dir, task_id)
    result = _base_result(
        task_id,
        _rel(parents["dev_report"], root),
        _rel(parents["completion"], root),
    )
    validator = ChainValidator(root, task_id)
    # M1: maps every dev-report/qa-report path this resolution touches to the
    # lane (or parent) task-id that owns it -- the canonical/parent pair is
    # seeded here unconditionally; fan-out lane pairs are added as each lane
    # is discovered below.  Read by _reclassify_disclosed_exceptions() to
    # populate disclosed_exceptions[].lane_task_id and to locate a dev-report's
    # sibling qa-report for the M3 same-lane cross-check.
    lane_task_id_by_path: dict[str, str] = {
        _rel(parents["dev_report"], root): task_id,
        _rel(parents["qa_report"], root): task_id,
    }

    if not _safe_task_id(task_id):
        validator.error(
            "INVALID_TASK_ID",
            "",
            "task-id must be a safe, non-empty filename component",
        )
        result["errors"] = validator.errors
        return result
    if not dev_dir.is_dir():
        validator.error(
            "MISSING_DEV_DIRECTORY",
            _rel(dev_dir, root),
            "docs/dev directory is absent",
        )
        result["errors"] = validator.errors
        return result

    canonical = validator.read_json(parents["dev_report"])
    completion = validator.read_text(parents["completion"])
    if canonical is None:
        result["errors"] = validator.errors
        # The dev-report itself could not be read (absent, empty, malformed,
        # or non-object) -- exactly the R1.4 "missing more than QA" shape that
        # can include a wholly-absent dev-report (R4/AC-13).  A sibling shard
        # makes the shape ambiguous (possibly a broken fan-out canonical,
        # out of scope this cycle); classify only when unambiguous.
        if not _dev_report_has_sibling_shards(dev_dir, task_id):
            # No sibling shard evidence of a fan-out canonical: classify as
            # the singular shape gap classification requires (R4/AC-13's
            # wholly-absent-dev-report case can only be reached this way).
            result["mode"] = "singular"
            qa_report_path = _rel(parents["qa_report"], root)
            (
                result["stage_gaps"],
                result["non_gap_errors"],
                result["late_repair_eligible"],
                result["gap_classification"],
            ) = _compute_gap_fields(validator.errors, qa_report_path)
        return result

    validator.validate_dev(canonical, task_id, parents["dev_report"])
    # Reached before the branch split, so both modes are held to it.
    _check_declared_paths_exist(validator, canonical, result)
    workers_declaration = _workers_declaration_state(canonical)
    result["parallel_workers_declaration"] = workers_declaration
    workers_value = canonical.get("parallel_workers", [])
    workers: list[str] = []
    if not isinstance(workers_value, list) or any(
        not isinstance(worker, str) or not WORKER_RE.fullmatch(worker)
        for worker in workers_value
    ):
        validator.error(
            "INVALID_WORKER_SET",
            result["canonical_dev_report"],
            "parallel_workers must be an array of valid worker labels",
        )
    else:
        workers = list(workers_value)
        if len(set(workers)) != len(workers):
            validator.error(
                "AMBIGUOUS_WORKER_SET",
                result["canonical_dev_report"],
                "parallel_workers contains duplicates",
            )

    try:
        aggregate = _load_aggregate_module()
        bare_task_id = aggregate._bare_task_id(task_id)
        # Shards belong to the FULL task-id.  When the bare timestamp is a
        # truncation of it (prefixed/suffixed ids), classifying against that key
        # collects this task's own canonical and unrelated sibling tasks, so the
        # filename must name this task-id plus a worker suffix instead.
        scan_key_is_truncated = bare_task_id != task_id
        own_canonical = parents["dev_report"].name
        scanned = []
        try:
            children = sorted(dev_dir.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            validator.error(
                "UNREADABLE_DEV_DIRECTORY", _rel(dev_dir, root), str(exc)
            )
            children = []
        for child in children:
            if not child.is_file() or child.name == own_canonical:
                continue
            if scan_key_is_truncated:
                label = _lane_shard_label(child.name, task_id, aggregate)
                is_worker = label is not None
            else:
                is_worker, label = aggregate._is_worker_for_task(
                    child.name, bare_task_id, task_id
                )
            if is_worker and label is not None:
                scanned.append((label, child))
        scanned.sort(key=lambda item: item[0])
    except Exception as exc:
        validator.error(
            "AGGREGATE_IMPLEMENTATION_ERROR",
            "scripts/aggregate-dev-report.py",
            str(exc),
        )
        scanned = []
        aggregate = None

    if workers:
        result["mode"] = "fanout"
        if len(workers) < 2:
            validator.error(
                "AMBIGUOUS_WORKER_SET",
                result["canonical_dev_report"],
                "fan-out requires at least two workers",
            )
        scanned_labels = [worker for worker, _ in scanned]
        if scanned_labels != workers:
            validator.error(
                "LANE_SET_MISMATCH",
                result["canonical_dev_report"],
                f"parallel_workers {workers!r} do not exactly match shards {scanned_labels!r}",
            )
        _find_undeclared_lane_artifacts(validator, workers, aggregate)

        loaded_shards: list[tuple[str, dict[str, Any]]] = []
        completion_refs = [result["canonical_dev_report"]]
        artifact_paths = [result["canonical_dev_report"], result["completion"]]
        result["report_paths"] = [result["canonical_dev_report"]]
        for worker in workers:
            lane_id = f"{task_id}-{worker}"
            paths = _lane_paths(dev_dir, task_id, worker)
            lane = {
                "worker": worker,
                "task_id": lane_id,
                **{key: _rel(path, root) for key, path in paths.items()},
            }
            result["lanes"].append(lane)
            lane_task_id_by_path[lane["dev_report"]] = lane_id
            lane_task_id_by_path[lane["qa_report"]] = lane_id
            result["report_paths"].extend((lane["dev_report"], lane["qa_report"]))
            lane_refs = [lane[key] for key in ("ticket", "context", "dev_report", "qa_report")]
            completion_refs.extend(lane_refs)
            artifact_paths.extend(lane_refs)

            ticket = validator.read_text(paths["ticket"])
            if ticket is not None:
                validator.validate_markdown_identity(ticket, lane_id, paths["ticket"])
            context = validator.read_json(paths["context"])
            if context is not None:
                validator.validate_json_identity(context, lane_id, paths["context"])
            dev = validator.read_json(paths["dev_report"])
            if dev is not None:
                validator.validate_dev(dev, lane_id, paths["dev_report"])
                loaded_shards.append((worker, dev))
            qa = validator.read_json(paths["qa_report"])
            if qa is not None:
                validator.validate_qa(qa, lane_id, paths["qa_report"])

        if completion is not None:
            validator.validate_completion(
                completion, task_id, parents["completion"], completion_refs
            )
        optional = _optional_parent_result(validator, parents)
        result["optional_parent_artifacts"] = optional
        artifact_paths.extend(
            value["path"] for value in optional.values() if value["present"]
        )
        if optional["qa_report"]["present"]:
            result["report_paths"].append(optional["qa_report"]["path"])
        result["artifact_paths"] = artifact_paths
        result["commit_whitelist_artifacts"] = artifact_paths
        result["qa_inputs"] = [
            {"task_id": lane["task_id"], "qa_report": lane["qa_report"]}
            for lane in result["lanes"]
        ]

        if aggregate is not None and len(loaded_shards) == len(workers):
            # The provider hands the aggregator the ONE shape definition above:
            # a blocked lane whose record validates is a legitimate shard, and
            # the expected canonical / freshness projection carry the record.
            deviation = ac_deviation_provider()
            shard_errors = aggregate._validate_shards(
                loaded_shards, task_id, deviation=deviation
            )
            for detail in shard_errors:
                validator.error(
                    "INVALID_SHARD_SET", result["canonical_dev_report"], detail
                )
            if not shard_errors:
                expected = aggregate._build_aggregate(
                    loaded_shards, task_id, deviation=deviation
                )
                canonical_dev = canonical.get("dev")
                if not isinstance(canonical_dev, dict):
                    canonical_dev = {}
                result["checks"]["file_unions_exact"] = (
                    canonical_dev.get("files_modified")
                    == expected.get("dev", {}).get("files_modified")
                    and canonical_dev.get("files_created")
                    == expected.get("dev", {}).get("files_created")
                )
                result["checks"]["canonical_fresh"] = (
                    aggregate._canonical_projection(canonical, deviation=deviation)
                    == aggregate._canonical_projection(expected, deviation=deviation)
                )
                if not result["checks"]["file_unions_exact"]:
                    validator.error(
                        "STALE_FILE_UNION",
                        result["canonical_dev_report"],
                        "canonical file unions do not match current lane reports",
                    )
                if not result["checks"]["canonical_fresh"]:
                    validator.error(
                        "STALE_CANONICAL",
                        result["canonical_dev_report"],
                        "canonical aggregate projection does not match current lane reports",
                    )
    else:
        result["mode"] = "singular"
        # Both are comparisons of the canonical against a rebuild from two or
        # more shards.  A singular chain has no shards, so neither has a
        # singular analogue -- report that, rather than a value that would read
        # as a check having been performed.  Assigned per key so the
        # branch-independent checks computed above survive.
        for check in ("canonical_fresh", "file_unions_exact"):
            result["checks"][check] = NOT_APPLICABLE
            result["checks_not_applicable"][check] = SINGULAR_RELATIONAL_REASON
        if scanned:
            validator.error(
                "AMBIGUOUS_SINGULAR_CHAIN",
                result["canonical_dev_report"],
                f"singular canonical coexists with worker shards {[label for label, _ in scanned]!r}",
            )
        if workers_declaration == "absent" and scanned:
            # Additive to AMBIGUOUS_SINGULAR_CHAIN above, which still fires
            # unchanged.  That error says "a singular chain has shards"; this one
            # says "this is an aggregate that lost its parallel_workers key",
            # which is a different diagnosis with a different remedy.
            validator.error(
                "LOST_WORKER_DECLARATION",
                result["canonical_dev_report"],
                "parallel_workers key is absent, not empty, while worker shards "
                f"{[label for label, _ in scanned]!r} survive on disk; an aggregate "
                "that lost the key is indistinguishable from a singular chain",
            )
        completion_refs = [
            _rel(parents[key], root)
            for key in ("ticket", "context", "dev_report", "qa_report")
        ]
        ticket = validator.read_text(parents["ticket"])
        if ticket is not None:
            validator.validate_markdown_identity(ticket, task_id, parents["ticket"])
        context = validator.read_json(parents["context"])
        if context is not None:
            validator.validate_json_identity(context, task_id, parents["context"])
        qa = validator.read_json(parents["qa_report"])
        if qa is not None:
            validator.validate_qa(qa, task_id, parents["qa_report"])
        if completion is not None:
            validator.validate_completion(
                completion, task_id, parents["completion"], completion_refs
            )
        result["report_paths"] = [
            result["canonical_dev_report"],
            _rel(parents["qa_report"], root),
        ]
        result["artifact_paths"] = completion_refs + [result["completion"]]
        result["commit_whitelist_artifacts"] = list(result["artifact_paths"])
        result["qa_inputs"] = [
            {"task_id": task_id, "qa_report": _rel(parents["qa_report"], root)}
        ]

    result["parallel_workers"] = workers
    # Harness backlog #92: the AC-deviation record is validated ONCE per
    # dev-report, by the single validator.  A non-empty violation list becomes
    # the additive rejection error (in addition to the dev errors that stay
    # hard); a valid record only makes the dev-report path a candidate for the
    # reclassification pass below.  Singular chains validate the canonical
    # itself.  Fan-out chains validate every lane, and the canonical (the merge
    # of the lane records) only when at least one lane carries a valid record,
    # so a record forged on the canonical alone is never even read.
    ac_deviation_paths: set[str] = set()
    if result["mode"] == "singular":
        deviation_violations = _ac_deviation_violations(canonical)
        if deviation_violations:
            validator.error(
                AC_DEVIATION_REJECTION_CODE,
                result["canonical_dev_report"],
                _ac_deviation_rejection_detail(deviation_violations),
            )
        elif deviation_violations is not None:
            ac_deviation_paths.add(result["canonical_dev_report"])
    elif result["mode"] == "fanout":
        for lane in result["lanes"]:
            lane_violations = _ac_deviation_violations(
                validator.loaded_reports.get(lane["dev_report"])
            )
            if lane_violations:
                validator.error(
                    AC_DEVIATION_REJECTION_CODE,
                    lane["dev_report"],
                    _ac_deviation_rejection_detail(lane_violations),
                )
            elif lane_violations is not None:
                ac_deviation_paths.add(lane["dev_report"])
        if ac_deviation_paths:
            deviation_violations = _ac_deviation_violations(canonical)
            if deviation_violations:
                validator.error(
                    AC_DEVIATION_REJECTION_CODE,
                    result["canonical_dev_report"],
                    _ac_deviation_rejection_detail(deviation_violations),
                )
            elif deviation_violations is not None:
                ac_deviation_paths.add(result["canonical_dev_report"])
    # M1: additive reclassification pass over the already-computed errors --
    # validate_dev()/validate_qa() above are never revisited.  Final status:
    # "pass" when both lists are empty, "pass_with_exceptions" when errors is
    # empty but disclosed_exceptions is not, "fail" whenever errors is
    # non-empty (regardless of disclosed_exceptions).
    remaining_errors, disclosed_exceptions = _reclassify_disclosed_exceptions(
        validator.errors,
        validator.loaded_reports,
        lane_task_id_by_path,
        mode=result["mode"],
        parent_dev_report_path=result["canonical_dev_report"],
        lane_dev_report_paths=[lane["dev_report"] for lane in result["lanes"]],
        ac_deviation_paths=ac_deviation_paths,
    )
    result["errors"] = remaining_errors
    result["disclosed_exceptions"] = disclosed_exceptions
    if remaining_errors:
        result["status"] = "fail"
    elif disclosed_exceptions:
        result["status"] = "pass_with_exceptions"
    else:
        result["status"] = "pass"
    if result["mode"] == "singular":
        qa_report_path = _rel(parents["qa_report"], root)
        released_deviation_paths = {
            entry["path"]
            for entry in disclosed_exceptions
            if entry.get("kind") == AC_DEVIATION_DISCLOSURE_KIND
        }
        (
            result["stage_gaps"],
            result["non_gap_errors"],
            result["late_repair_eligible"],
            result["gap_classification"],
        ) = _compute_gap_fields(remaining_errors, qa_report_path, released_deviation_paths)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = StableArgumentParser(prog="resolve-dev-artifact-chain.py")
    parser.add_argument("--task-id", required=True)
    parser.add_argument(
        "--project-dir",
        default=str(Path(__file__).resolve().parent.parent),
    )
    try:
        args = parser.parse_args(argv)
    except ValueError as exc:
        result = _base_result("", "", "")
        result["errors"] = [
            {"code": "CLI_ARGUMENT_ERROR", "path": "", "detail": str(exc)}
        ]
        print(
            json.dumps(
                result, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
        )
        return 2
    result = resolve_chain(args.project_dir, args.task_id)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0 if result["status"] in ("pass", "pass_with_exceptions") else 2


if __name__ == "__main__":
    sys.exit(main())
