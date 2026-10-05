#!/usr/bin/env python3
"""Obligation-block grammar v1 parser/validator and own-dispatch resolver.

Rollout step S2 of the converged zero-failure design
(docs/reference/close-commit-zero-failure-mechanism-20260928.md, "the design"):

- grammar v1 (design §1.2, :78-156): extract exactly one ``<obligation v="1">``
  block from a dispatch prompt and validate it fail-closed, every rejection
  carrying a machine-readable named reason;
- own-dispatch-obligation resolution (design §1.3-G2 ladder rungs L0/L1,
  :188-221): read the verbatim dispatch prompt back out of the harness-owned
  transcript store, session-scoped, cross-checked against the parent
  transcript via the subagent's ``meta.json`` toolUseId;
- pure clock/freshness helpers (design §1.2 freshness rules and §1.3-G1
  check 2) parameterized on a caller-supplied ``now``.

Binding contract notes (ticket-20260929-104216-b):

- Typed outcomes over exceptions at the API boundary. The two honest
  negatives -- "the prompt carries no block" (``NoBlock`` /
  ``NoObligationInPrompt``) and "no correlation exists" (``Unresolvable``) --
  are DISTINCT types; conflating them is a defect.
- No wall-clock or environment reads inside validation logic. Filesystem
  access happens only in the resolver functions, strictly read-only.
- Schema-id registry MEMBERSHIP is checked only against a caller-supplied
  ``known_schema_ids`` set (``None`` skips the membership check). The library
  never reads ``schemas/registry.json`` and never imports
  ``contract_runtime`` (sibling-lane file disjointness).
- Ladder POLICY (advisory vs block, the L2 correlation heuristic, the L3
  allow) belongs to the gate cycle. This library only returns evidence.

Transcript-store primitives are REUSED from ``subagent_restart`` (the
production reader this design cites at :51-54), never duplicated.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:  # imported as hooks.lib.obligation (tests) or lib.obligation (hooks)
    from .subagent_restart import (
        AGENT_RE,
        SESSION_RE,
        RestartError,
        _read_parent_calls,
        account_project_roots,
        project_slug,
    )
except ImportError:  # hooks/lib placed directly on sys.path
    from subagent_restart import (  # type: ignore[no-redef]
        AGENT_RE,
        SESSION_RE,
        RestartError,
        _read_parent_calls,
        account_project_roots,
        project_slug,
    )


# --------------------------------------------------------------------------
# Grammar constants -- enums, markers and field names copied VERBATIM from
# design §1.2 (:83-113); versioned, immutable per release.
# --------------------------------------------------------------------------

OBLIGATION_VERSION = "1"
OBLIGATION_OPEN_TOKEN = "<obligation"
OBLIGATION_CLOSE_TAG = "</obligation>"

ROLES = frozenset({
    "ba", "dev", "qa", "graphify", "spec", "test-writer", "changelog-analyst",
    # 20261001-161041-r11: the three /close-dispatched inspectors (G1+G2
    # producer-role enforcement extension; additive-only, mirrors the
    # existing five-role pattern).
    "style-inspector", "cleanliness-inspector", "prompt-inspector",
})  # design :90
PIPELINES = frozenset({
    "dev", "redev", "dev-command", "dev-overnight", "do", "close", "commit",
})  # design :91
PROFILES = frozenset({
    "singular", "fanout-lane", "ba_validation", "final_verification",
    "overnight", "do-close", "commit-qa", "commit-landing", "commit-bulk",
    "ad_hoc",
})  # design :92-93
RESPONSE_BLOCK_FORMATS = frozenset({"json"})  # design :104
CONSISTENCY_VERDICT_CLASS = "verdict_class"  # design :108

TOP_LEVEL_FIELDS = frozenset({
    "task_id", "lane", "lane_set", "role", "pipeline", "profile",
    "dispatched_at", "artifacts", "consistency", "expected_absent",
})
REQUIRED_TOP_LEVEL_FIELDS = frozenset({
    "task_id", "role", "pipeline", "profile", "dispatched_at", "artifacts",
})
IDENTITY_KEYS = frozenset({"task_id", "request_id"})  # design :98

# Exact per-kind field sets (design :95-107): (required, optional).
# waived_by_response is OPTIONAL -- the sentinel waiver exists only for the
# close-QA bundle (design §1.4.5); requiring it would reject the design's own
# dev-report markdown obligations.
ARTIFACT_FIELDS_BY_KIND: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "json": (("kind", "path", "schema", "identity"), ("required_values",)),
    "markdown": (
        ("kind", "path", "identity_anchor"),
        ("terminal_line_regex", "waived_by_response"),
    ),
    "response_block": (("kind", "begin", "end", "format", "schema"), ()),
    "response_line": (("kind", "terminal_line_regex"), ()),
}
ARTIFACT_KINDS = frozenset(ARTIFACT_FIELDS_BY_KIND)

# task_id shape: the _TASK_ID_ANCHOR_RE precedent
# (hooks/subagentstop-artifact-contract-enforce.py:114) further pinned to the
# \d{8}-\d{6} prefix convention (ticket M3).
# L1 (dev-command-20261002-170011): also accepts the dev-command lane form
# ``dev-command-<yyyymmdd-hhmmss>[-lN]``. The pattern string is identical to
# schemas/obligation.v1.json properties.task_id.pattern (parity-tested).
TASK_ID_RE = re.compile(
    r"^(?:\d{8}-\d{6}[A-Za-z0-9._-]*|dev-command-\d{8}-\d{6}(?:-l\d+)?)$"
)

# Closed terminal vocabulary (design D1/R2): schema id -> dotted path -> legal
# terminal values. Equal to each registered schema's enum (drift-tested);
# templates and gates import this constant, they never declare their own.
TERMINAL_VOCABULARY: dict[str, dict[str, frozenset[str]]] = {
    "dev-report.v2": {"dev.status": frozenset({"completed", "blocked", "needs_review"})},
    "dev-report.v1": {
        "status": frozenset({"completed", "blocked", "partial", "needs_review"}),
    },
    "qa-report.v2": {"qa.status": frozenset({"pass", "warning", "fail"})},
    "qa-report.v1": {"verdict": frozenset({"pass", "warning", "fail"})},
    "do-report.v1": {"do.status": frozenset({"pending", "completed", "blocked"})},
}

# task_id null legality (design :85-86 + ticket M3): unconditional for
# ad_hoc / commit-bulk; conditional for commit-qa (the /commit --bulk context
# is transcript-derived, G1 check 3 -- invisible to a pure parser, so the
# validator ACCEPTS and returns an undischarged-condition flag for the gate
# cycle to discharge).
NULL_TASK_ID_PROFILES = frozenset({"ad_hoc", "commit-bulk"})
CONDITIONAL_NULL_TASK_ID_PROFILE = "commit-qa"
UNDISCHARGED_TASK_ID_NULL = "task_id_null_requires_bulk_context"

# Dispatch-clock bound (design §1.3-G1 check 2: |dispatched_at - now| <= 300s).
DISPATCH_CLOCK_BOUND_SECONDS = 300
# File-kind freshness slack (design §1.2 freshness: mtime >= dispatched_at - 2s
# covers filesystem timestamp granularity only; response kinds carry none --
# inherently produced by this run).
FILE_FRESHNESS_SLACK_SECONDS = 2
FRESHNESS_SLACK_SECONDS_BY_KIND: dict[str, int | None] = {
    "json": FILE_FRESHNESS_SLACK_SECONDS,
    "markdown": FILE_FRESHNESS_SLACK_SECONDS,
    "response_block": None,
    "response_line": None,
}

# Resolver cross-check statuses.
CROSS_CHECK_OK = "ok"
CROSS_CHECK_SKIPPED_PARENT_UNREADABLE = "skipped_parent_unreadable"
CROSS_CHECK_SKIPPED_NO_META = "skipped_no_meta"

_OPEN_TAG_RE = re.compile(r"<obligation\b([^>]*)>")
_VERSION_ONLY_ATTRS_RE = re.compile(r'\s*v="([^"]*)"\s*')

# Dev-family classification marker (ticket 20260930-132644-l4 item 3): a
# dispatch prompt that references a dev-registry directory. The captured
# token is cross-checked against the filesystem by the caller -- a textual
# match alone is never sufficient (a prompt can quote the path without this
# session having actually minted that directory).
_DEV_REGISTRY_TOKEN_RE = re.compile(r"\.claude/dev-registry/([A-Za-z0-9_-]+)/")


# --------------------------------------------------------------------------
# Typed outcomes (grammar layer)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class NoBlock:
    """The prompt carries no obligation block (design M5 zero-block case)."""

    outcome: str = "no_block"


@dataclass(frozen=True)
class Rejection:
    """Fail-closed rejection with a machine-readable named reason."""

    reason: str
    field: str = ""
    detail: str = ""
    outcome: str = "rejected"


@dataclass(frozen=True)
class ExtractedBlock:
    """Raw body text of the single well-versioned obligation block."""

    body: str


@dataclass(frozen=True)
class Validated:
    """Document accepted; ``undischarged`` lists conditions a later gate
    cycle must discharge (e.g. ``task_id_null_requires_bulk_context``)."""

    undischarged: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedObligation:
    """Extraction + parse + validation all succeeded."""

    obligation: Mapping[str, Any]
    undischarged: tuple[str, ...] = ()


# --------------------------------------------------------------------------
# Typed outcomes (resolver layer, design §1.3-G2)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Resolved:
    """A well-formed obligation was resolved from this agent's own dispatch
    prompt at ladder rung L0 (payload-supplied path) or L1 (session-scoped
    store construction)."""

    obligation: Mapping[str, Any]
    rung: str
    prompt: str
    transcript_path: str
    cross_check: str
    undischarged: tuple[str, ...] = ()
    outcome: str = "resolved"


@dataclass(frozen=True)
class NoObligationInPrompt:
    """The dispatch prompt was resolved but carries no obligation block --
    the honest result for every pre-rollout dispatch. DISTINCT from
    ``Unresolvable`` (no correlation) by binding contract."""

    prompt: str
    rung: str
    transcript_path: str
    cross_check: str
    outcome: str = "no_obligation_in_prompt"


@dataclass(frozen=True)
class Unresolvable:
    """No correlation exists (missing transcript, unreadable store, meta
    mismatch, role mismatch, invalid embedded obligation) -- fail-closed,
    never a guess, never a fallback to an unrelated transcript."""

    reason: str
    detail: str = ""
    outcome: str = "unresolvable"


# --------------------------------------------------------------------------
# Grammar: extraction (design §1.2 M5 exactly-one rule, M2 versioning)
# --------------------------------------------------------------------------

def extract_obligation_block(prompt: str) -> ExtractedBlock | NoBlock | Rejection:
    """Extract the single ``<obligation v="1">`` block body from a prompt.

    Design M5: exactly one block per producer dispatch. Zero openers is the
    typed ``NoBlock`` result; more than one opener is ``multiple_blocks``.
    Design M2: the version attribute must be exactly ``v="1"``; anything else
    (missing, other version, malformed tag) is ``unsupported_version``.
    """
    if not isinstance(prompt, str):
        return Rejection(reason="bad_prompt")
    opener_count = prompt.count(OBLIGATION_OPEN_TOKEN)
    if opener_count == 0:
        return NoBlock()
    if opener_count > 1:
        return Rejection(reason="multiple_blocks")
    match = _OPEN_TAG_RE.search(prompt)
    if match is None:
        return Rejection(reason="unsupported_version", detail="malformed opening tag")
    attrs = _VERSION_ONLY_ATTRS_RE.fullmatch(match.group(1))
    if attrs is None or attrs.group(1) != OBLIGATION_VERSION:
        return Rejection(reason="unsupported_version", detail=match.group(1).strip())
    close_index = prompt.find(OBLIGATION_CLOSE_TAG, match.end())
    if close_index < 0:
        return Rejection(reason="unterminated_block")
    return ExtractedBlock(body=prompt[match.end():close_index])


# --------------------------------------------------------------------------
# Grammar: fail-closed field validation (design §1.2 field semantics)
# --------------------------------------------------------------------------

def _legal_repo_relative_path(value: Any) -> bool:
    """Repo-relative and traversal-free (ticket M3): non-empty string with no
    leading ``/`` and no ``..`` segment."""
    if not isinstance(value, str) or not value:
        return False
    if value.startswith("/"):
        return False
    return ".." not in value.split("/")


def _validate_required_values(
    required_values: Any, schema_id: Any, label: str
) -> Rejection | None:
    """Validate a json entry's ``required_values`` against the closed
    terminal vocabulary (named reasons: bad_required_values,
    unknown_terminal_path, unknown_terminal_value)."""
    if not isinstance(required_values, Mapping) or not required_values:
        return Rejection(reason="bad_required_values", field=label)
    for dotted, allowed in required_values.items():
        field = f"{label}.{dotted}"
        if (
            not isinstance(dotted, str)
            or not dotted
            or not isinstance(allowed, list)
            or not allowed
            or any(not isinstance(v, str) or not v for v in allowed)
            or len(set(allowed)) != len(allowed)
        ):
            return Rejection(reason="bad_required_values", field=field)
        vocabulary = TERMINAL_VOCABULARY.get(schema_id) if isinstance(schema_id, str) else None
        if vocabulary is None or dotted not in vocabulary:
            return Rejection(reason="unknown_terminal_path", field=field)
        for value in allowed:
            if value not in vocabulary[dotted]:
                return Rejection(
                    reason="unknown_terminal_value", field=field, detail=value
                )
    return None


def evaluate_required_values(
    record: Any, required_values: Mapping[str, Iterable[str]]
) -> list[dict]:
    """Pure terminal-state evaluator: return the violations of
    ``required_values`` against a parsed artifact ``record`` (empty list =
    satisfied). Dotted paths hop through dicts only (a list on the path is
    not walkable). No filesystem, clock or environment access.

    Violation shapes: ``{"reason": "terminal_value_unmet", "path", "actual",
    "allowed"}`` and ``{"reason": "missing_terminal_path", "path",
    "allowed"}``.
    """
    violations: list[dict] = []
    for dotted, allowed in required_values.items():
        allowed_list = list(allowed)
        node: Any = record
        found = True
        for part in dotted.split("."):
            if isinstance(node, Mapping) and part in node:
                node = node[part]
            else:
                found = False
                break
        if not found:
            violations.append({
                "reason": "missing_terminal_path", "path": dotted, "allowed": allowed_list,
            })
        elif not isinstance(node, str) or node not in allowed_list:
            violations.append({
                "reason": "terminal_value_unmet", "path": dotted,
                "actual": node, "allowed": allowed_list,
            })
    return violations


def _validate_artifact_entry(
    entry: Any,
    label: str,
    known_schema_ids: Iterable[str] | None,
) -> Rejection | None:
    """Validate one artifacts[] entry against its kind's exact §1.2 field set."""
    if not isinstance(entry, Mapping):
        return Rejection(reason="bad_artifact_entry", field=label)
    if "kind" not in entry:
        return Rejection(reason="missing_field", field=f"{label}.kind")
    kind = entry["kind"]
    if not isinstance(kind, str) or kind not in ARTIFACT_FIELDS_BY_KIND:
        return Rejection(reason="unknown_kind", field=f"{label}.kind", detail=repr(kind))
    required, optional = ARTIFACT_FIELDS_BY_KIND[kind]
    for key in entry:
        if key not in required and key not in optional:
            return Rejection(reason="unknown_field", field=f"{label}.{key}")
    for key in required:
        if key not in entry:
            return Rejection(reason="missing_field", field=f"{label}.{key}")
    if "path" in entry and not _legal_repo_relative_path(entry["path"]):
        return Rejection(reason="illegal_path", field=f"{label}.path")
    if "schema" in entry:
        schema = entry["schema"]
        if not isinstance(schema, str) or not schema:
            return Rejection(reason="bad_schema_id", field=f"{label}.schema")
        if known_schema_ids is not None and schema not in known_schema_ids:
            return Rejection(
                reason="unregistered_schema", field=f"{label}.schema", detail=schema
            )
    if kind == "json":
        identity = entry["identity"]
        if not isinstance(identity, Mapping):
            return Rejection(reason="bad_identity", field=f"{label}.identity")
        if not identity:
            return Rejection(reason="empty_identity", field=f"{label}.identity")
        for key, value in identity.items():
            if key not in IDENTITY_KEYS:
                return Rejection(
                    reason="unknown_identity_key", field=f"{label}.identity.{key}"
                )
            if not isinstance(value, str) or not value:
                return Rejection(
                    reason="bad_identity_value", field=f"{label}.identity.{key}"
                )
        if "required_values" in entry:
            rejection = _validate_required_values(
                entry["required_values"], entry["schema"], f"{label}.required_values"
            )
            if rejection is not None:
                return rejection
    if kind == "markdown":
        anchor = entry["identity_anchor"]
        if not isinstance(anchor, str) or not anchor:
            return Rejection(reason="bad_identity_anchor", field=f"{label}.identity_anchor")
    for regex_key in ("terminal_line_regex", "waived_by_response"):
        if regex_key in entry:
            pattern = entry[regex_key]
            if not isinstance(pattern, str) or not pattern:
                return Rejection(reason="bad_regex", field=f"{label}.{regex_key}")
            try:
                re.compile(pattern)
            except re.error:
                return Rejection(reason="bad_regex", field=f"{label}.{regex_key}")
    if kind == "response_block":
        for key in ("begin", "end"):
            value = entry[key]
            if not isinstance(value, str) or not value:
                return Rejection(reason="bad_sentinel", field=f"{label}.{key}")
        if entry["begin"] == entry["end"]:
            return Rejection(reason="sentinel_collision", field=f"{label}.end")
        fmt = entry["format"]
        if not isinstance(fmt, str) or fmt not in RESPONSE_BLOCK_FORMATS:
            return Rejection(
                reason="unknown_enum_value", field=f"{label}.format", detail=repr(fmt)
            )
    return None


def validate_obligation(
    doc: Any,
    known_schema_ids: Iterable[str] | None = None,
) -> Validated | Rejection:
    """Fail-closed validation of a parsed obligation document (design §1.2).

    Every rejection is wholesale (never a partial accept) and carries a named
    reason. ``known_schema_ids`` is the caller-supplied registry membership
    set; ``None`` skips membership (the library never reads
    ``schemas/registry.json`` itself). The single accepted-with-conditions
    case is ``task_id: null`` under profile ``commit-qa``, which returns the
    ``task_id_null_requires_bulk_context`` undischarged flag.

    NOTE (design :96-98, AC1): the top-level ``task_id`` and a json
    artifact's ``identity.task_id`` may differ by a lane suffix BY DESIGN;
    no equality is imposed between them.
    """
    if not isinstance(doc, Mapping):
        return Rejection(reason="bad_document")
    for key in doc:
        if key not in TOP_LEVEL_FIELDS:
            return Rejection(reason="unknown_field", field=str(key))
    for key in sorted(REQUIRED_TOP_LEVEL_FIELDS):
        if key not in doc:
            return Rejection(reason="missing_field", field=key)
    for key, allowed in (("role", ROLES), ("pipeline", PIPELINES), ("profile", PROFILES)):
        value = doc[key]
        if not isinstance(value, str) or value not in allowed:
            return Rejection(reason="unknown_enum_value", field=key, detail=repr(value))
    undischarged: list[str] = []
    task_id = doc["task_id"]
    profile = doc["profile"]
    if task_id is None:
        if profile in NULL_TASK_ID_PROFILES:
            pass
        elif profile == CONDITIONAL_NULL_TASK_ID_PROFILE:
            undischarged.append(UNDISCHARGED_TASK_ID_NULL)
        else:
            return Rejection(reason="task_id_null_illegal", field="task_id", detail=profile)
    elif not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
        return Rejection(reason="bad_task_id", field="task_id")
    lane = doc.get("lane")
    if lane is not None and (not isinstance(lane, str) or not lane):
        return Rejection(reason="bad_lane", field="lane")
    lane_set = doc.get("lane_set")
    if lane_set is not None:
        if not isinstance(lane_set, list):
            return Rejection(reason="bad_lane_set", field="lane_set")
        if not lane_set:
            return Rejection(reason="lane_set_empty", field="lane_set")
        if any(not isinstance(member, str) or not member for member in lane_set):
            return Rejection(reason="lane_set_member_not_string", field="lane_set")
        if len(set(lane_set)) != len(lane_set):
            return Rejection(reason="lane_set_duplicate", field="lane_set")
        if lane is None:
            return Rejection(reason="lane_missing_with_lane_set", field="lane")
        if lane not in lane_set:
            return Rejection(reason="lane_not_in_lane_set", field="lane")
    if parse_iso8601(doc["dispatched_at"]) is None:
        return Rejection(reason="bad_timestamp", field="dispatched_at")
    artifacts = doc["artifacts"]
    if not isinstance(artifacts, list):
        return Rejection(reason="bad_artifacts", field="artifacts")
    if not artifacts:
        return Rejection(reason="artifacts_empty", field="artifacts")
    for index, entry in enumerate(artifacts):
        rejection = _validate_artifact_entry(entry, f"artifacts[{index}]", known_schema_ids)
        if rejection is not None:
            return rejection
    if "consistency" in doc and doc["consistency"] != CONSISTENCY_VERDICT_CLASS:
        return Rejection(reason="unknown_consistency", field="consistency")
    if "expected_absent" in doc:
        expected_absent = doc["expected_absent"]
        if not isinstance(expected_absent, list):
            return Rejection(reason="bad_expected_absent", field="expected_absent")
        for index, path_value in enumerate(expected_absent):
            if not _legal_repo_relative_path(path_value):
                return Rejection(reason="illegal_path", field=f"expected_absent[{index}]")
    return Validated(undischarged=tuple(undischarged))


def parse_obligation(
    prompt: str,
    known_schema_ids: Iterable[str] | None = None,
) -> ParsedObligation | NoBlock | Rejection:
    """Extract + strict-parse + validate in one call (design §1.2).

    The block body must be strict JSON (``json.loads``): the §1.2 example's
    ``//`` annotations are documentation, NOT grammar -- comment-bearing or
    trailing-garbage bodies are ``malformed_json`` (a comment-TOLERANT parser
    would be a lenient-parsing defect under the fail-closed principle).
    """
    extracted = extract_obligation_block(prompt)
    if not isinstance(extracted, ExtractedBlock):
        return extracted
    try:
        doc = json.loads(extracted.body)
    except ValueError:
        return Rejection(reason="malformed_json")
    validated = validate_obligation(doc, known_schema_ids=known_schema_ids)
    if isinstance(validated, Rejection):
        return validated
    return ParsedObligation(obligation=doc, undischarged=validated.undischarged)


def serialize_obligation(doc: Mapping[str, Any]) -> str:
    """Render a document as the exact block a dispatch prompt embeds
    (design §1.2). ``parse_obligation(serialize_obligation(x))`` is lossless
    for JSON-representable documents (AC1)."""
    body = json.dumps(doc, indent=2, ensure_ascii=False)
    return f'<obligation v="{OBLIGATION_VERSION}">\n{body}\n</obligation>'


# --------------------------------------------------------------------------
# Pure clock / freshness helpers (design §1.2 freshness, §1.3-G1 check 2)
# --------------------------------------------------------------------------

def parse_iso8601(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp (``Z`` suffix normalized); None on failure.
    Pure -- never reads the wall clock."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def dispatch_clock_within_bound(
    dispatched_at: Any,
    now: Any,
    bound_seconds: int = DISPATCH_CLOCK_BOUND_SECONDS,
) -> bool | None:
    """G1 check 2 predicate: ``|dispatched_at - now| <= bound_seconds``.

    ``now`` is caller-supplied (never read here). Returns None when either
    timestamp is unparseable or the aware/naive mix is uncomparable --
    fail-closed disposition is the caller's."""
    dispatched = parse_iso8601(dispatched_at)
    current = parse_iso8601(now)
    if dispatched is None or current is None:
        return None
    try:
        delta = abs((current - dispatched).total_seconds())
    except TypeError:
        return None
    return delta <= bound_seconds


def artifact_freshness_satisfied(
    kind: str,
    artifact_mtime: Any,
    dispatched_at: Any,
) -> bool | None:
    """Per-kind freshness predicate (design §1.2): file kinds require
    ``mtime >= dispatched_at - 2s``; response kinds carry no freshness rule
    (inherently produced by this run) and return True.

    ``artifact_mtime`` may be a datetime or an epoch number (UTC). Returns
    None on unknown kind or unparseable inputs."""
    if kind not in ARTIFACT_KINDS:
        return None
    slack = FRESHNESS_SLACK_SECONDS_BY_KIND[kind]
    if slack is None:
        return True
    if isinstance(artifact_mtime, (int, float)) and not isinstance(artifact_mtime, bool):
        mtime = datetime.fromtimestamp(artifact_mtime, tz=timezone.utc)
    else:
        mtime = parse_iso8601(artifact_mtime)
    dispatched = parse_iso8601(dispatched_at)
    if mtime is None or dispatched is None:
        return None
    try:
        return mtime.timestamp() >= dispatched.timestamp() - slack
    except (OSError, OverflowError, ValueError):
        return None


def lane_sets_identical(first: Any, second: Any) -> bool:
    """G1 check 4 helper: producers copy ``lane_set`` verbatim (design
    :142-143), so roster equality is exact value equality."""
    return first == second


# --------------------------------------------------------------------------
# Resolver: own-dispatch-obligation resolution (design §1.3-G2, rungs L0/L1)
# --------------------------------------------------------------------------

def read_first_record_prompt(transcript_path: str | Path) -> str | None:
    """Return the dispatch prompt from a subagent transcript's FIRST JSONL
    record when it is a user message (design §1.3-G2: "first record is a user
    message").

    Handles both persisted ``message.content`` shapes: plain string (observed
    live on this store) and content-block list (the shape the parent-side
    reader ``_read_parent_calls`` handles at subagent_restart.py:340-346).
    Read-only; returns None when unreadable, not type=user, or textless.
    """
    try:
        with Path(transcript_path).open("r", encoding="utf-8", errors="replace") as handle:
            first_line = handle.readline()
    except OSError:
        return None
    try:
        record = json.loads(first_line)
    except ValueError:
        return None
    if not isinstance(record, dict) or record.get("type") != "user":
        return None
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content or None
    if isinstance(content, list):
        text = "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
        return text or None
    return None


def candidate_transcript_paths(
    session_id: str,
    agent_id: str,
    project_dir: str | Path,
    roots: Iterable[str | Path] | None = None,
) -> list[Path]:
    """Session-scoped candidate paths across every account root (design
    §1.3-G2 L1): ``<root>/<slug>/<session_id>/subagents/agent-<agent_id>.jsonl``.

    Reuses ``project_slug`` / ``account_project_roots``
    (subagent_restart.py:551-577). Session scoping kills the observed
    cross-session agent-id reuse (agent_resolver.py:23-29). Multi-root copies
    are split views of the SAME child (design :196-199)."""
    resolved_roots = list(roots) if roots is not None else account_project_roots()
    slug = project_slug(project_dir)
    return [
        Path(root) / slug / session_id / "subagents" / f"agent-{agent_id}.jsonl"
        for root in resolved_roots
    ]


def _meta_path(transcript_path: Path) -> Path:
    return transcript_path.with_name(transcript_path.stem + ".meta.json")


def _read_meta_tool_use_id(transcript_path: Path) -> str | None:
    try:
        meta = json.loads(_meta_path(transcript_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    tool_use_id = meta.get("toolUseId") if isinstance(meta, dict) else None
    if isinstance(tool_use_id, str) and tool_use_id:
        return tool_use_id
    return None


def _parent_transcript_for(transcript_path: Path) -> Path:
    """Invert the store layout: .../<session_id>/subagents/agent-X.jsonl ->
    .../<session_id>.jsonl (the layout _metadata_by_tool_use walks forward at
    subagent_restart.py:367-391)."""
    session_dir = transcript_path.parent.parent
    return session_dir.parent / f"{session_dir.name}.jsonl"


def _cross_check_against_parent(
    transcript_path: Path, prompt: str
) -> tuple[str, str]:
    """Meta toolUseId cross-check (design §1.3-G2 L1): the subagent's
    ``meta.json`` toolUseId must map to an Agent/Task tool_use block in the
    parent transcript whose ``input.prompt`` equals the first-record prompt.

    Returns ``(status, failure_reason)``. Per the design, the cross-check runs
    "when the parent transcript is readable"; an unreadable parent yields the
    explicit skipped status, never a silent pass-as-checked."""
    tool_use_id = _read_meta_tool_use_id(transcript_path)
    if tool_use_id is None:
        return "failed", "meta_not_found"
    parent = _parent_transcript_for(transcript_path)
    if not parent.is_file():
        return CROSS_CHECK_SKIPPED_PARENT_UNREADABLE, ""
    try:
        calls, _results, _notifications = _read_parent_calls(parent)
    except RestartError:
        return CROSS_CHECK_SKIPPED_PARENT_UNREADABLE, ""
    call = calls.get(tool_use_id)
    if call is None:
        return "failed", "meta_tool_use_mismatch"
    tool_input = call.get("input")
    parent_prompt = tool_input.get("prompt") if isinstance(tool_input, dict) else None
    if parent_prompt != prompt:
        return "failed", "prompt_mismatch"
    return CROSS_CHECK_OK, ""


def _finish_resolution(
    prompt: str,
    rung: str,
    transcript_path: Path,
    cross_check: str,
    expected_role: str | None,
    known_schema_ids: Iterable[str] | None,
) -> Resolved | NoObligationInPrompt | Unresolvable:
    parsed = parse_obligation(prompt, known_schema_ids=known_schema_ids)
    if isinstance(parsed, NoBlock):
        return NoObligationInPrompt(
            prompt=prompt,
            rung=rung,
            transcript_path=str(transcript_path),
            cross_check=cross_check,
        )
    if isinstance(parsed, Rejection):
        return Unresolvable(reason="invalid_obligation", detail=parsed.reason)
    if expected_role is not None and parsed.obligation.get("role") != expected_role:
        return Unresolvable(
            reason="role_mismatch", detail=repr(parsed.obligation.get("role"))
        )
    return Resolved(
        obligation=parsed.obligation,
        rung=rung,
        prompt=prompt,
        transcript_path=str(transcript_path),
        cross_check=cross_check,
        undischarged=parsed.undischarged,
    )


def resolve_own_obligation(
    session_id: str,
    agent_id: str,
    project_dir: str | Path,
    payload_agent_transcript_path: str | Path | None = None,
    expected_role: str | None = None,
    known_schema_ids: Iterable[str] | None = None,
    roots: Iterable[str | Path] | None = None,
) -> Resolved | NoObligationInPrompt | Unresolvable:
    """Resolve THIS dispatch's obligation from the transcript store (design
    §1.3-G2 ladder, rungs L0/L1 only -- L2/L3 are gate-cycle policy).

    - L0: a caller-supplied ``payload_agent_transcript_path`` (the
      production-precedent SubagentStop field, subagent_restart.py:920-922)
      is read directly; unreadable degrades to L1 per the ladder.
    - L1: session-scoped path construction across all account roots. Any
      root's copy is a split view of the SAME child (design :196-199); a copy
      is accepted only after the meta toolUseId cross-check.

    Typed outcomes, fail-closed: ``Resolved`` / ``NoObligationInPrompt`` /
    ``Unresolvable(named reason)`` with the distinct reasons
    ``session_not_found`` (no root holds the session),
    ``agent_transcript_not_found`` (session present, agent file absent),
    ``meta_not_found`` / ``meta_tool_use_mismatch`` / ``prompt_mismatch``
    (cross-check failures), ``unreadable_first_record``,
    ``invalid_obligation``, ``role_mismatch``, ``invalid_identifier``.
    """
    if not isinstance(session_id, str) or not SESSION_RE.fullmatch(session_id):
        return Unresolvable(reason="invalid_identifier", detail="session_id")
    if not isinstance(agent_id, str) or not AGENT_RE.fullmatch(agent_id):
        return Unresolvable(reason="invalid_identifier", detail="agent_id")

    if payload_agent_transcript_path:
        l0_path = Path(payload_agent_transcript_path)
        if l0_path.is_file():
            prompt = read_first_record_prompt(l0_path)
            if prompt is not None:
                if _meta_path(l0_path).is_file():
                    status, failure = _cross_check_against_parent(l0_path, prompt)
                    if status == "failed":
                        return Unresolvable(reason=failure, detail=str(l0_path))
                else:
                    status = CROSS_CHECK_SKIPPED_NO_META
                return _finish_resolution(
                    prompt, "L0", l0_path, status, expected_role, known_schema_ids
                )
        # L0 unreadable: degrade to L1 (design ladder order).

    slug = project_slug(project_dir)
    resolved_roots = list(roots) if roots is not None else account_project_roots()
    session_found = False
    last_failure: tuple[str, str] | None = None
    for root in resolved_roots:
        slug_dir = Path(root) / slug
        if (slug_dir / f"{session_id}.jsonl").is_file() or (slug_dir / session_id).is_dir():
            session_found = True
        candidate = slug_dir / session_id / "subagents" / f"agent-{agent_id}.jsonl"
        if not candidate.is_file():
            continue
        prompt = read_first_record_prompt(candidate)
        if prompt is None:
            last_failure = ("unreadable_first_record", str(candidate))
            continue
        status, failure = _cross_check_against_parent(candidate, prompt)
        if status == "failed":
            # Another root may hold a healthy copy of the SAME child.
            last_failure = (failure, str(candidate))
            continue
        return _finish_resolution(
            prompt, "L1", candidate, status, expected_role, known_schema_ids
        )
    if last_failure is not None:
        return Unresolvable(reason=last_failure[0], detail=last_failure[1])
    if session_found:
        return Unresolvable(reason="agent_transcript_not_found")
    return Unresolvable(reason="session_not_found")


# --------------------------------------------------------------------------
# Shared scan-and-check (design G4, ticket 20260930-132644-l4 item 7): the
# ONE algorithm reused verbatim by hooks/stop-obligation-gate.py (session-
# terminal check) and hooks/posttool-overnight-loop.py (cycle-reset check).
# Do not duplicate this scan in either caller.
# --------------------------------------------------------------------------

def _validate_artifact_status(path: Path, schema_id: str) -> str:
    """Lazy, fail-safe reuse of contract_runtime.validate_artifact_for_obligation.

    Lazy-imported (not at module top) so this module's grammar/resolver
    layers above stay free of a hard ``contract_runtime`` dependency (the
    binding-contract note in the module docstring: "never imports
    contract_runtime"); only this additive function -- the one this ticket
    explicitly authorizes to cross that boundary (BA component_chain,
    ticket-20260930-132644-l4.md item 4/7) -- reuses the obligation-
    authority schema gate instead of re-implementing per-artifact
    validation a second time. Any import or validation failure returns
    ``"skip"`` (never ``"fail"``) -- an infra problem here must never be
    reported as an unresolved obligation.
    """
    try:
        import sys as _sys

        lib_dir = str(Path(__file__).resolve().parent)
        if lib_dir not in _sys.path:
            _sys.path.insert(0, lib_dir)
        try:
            from . import contract_runtime as _cr  # type: ignore
        except ImportError:
            import contract_runtime as _cr  # type: ignore[no-redef]
        result = _cr.validate_artifact_for_obligation(path, schema_id)
        return result.get("status", "skip") if isinstance(result, Mapping) else "skip"
    except Exception:
        return "skip"


def find_unresolved_dispatch_obligations(
    transcript_path: str | Path,
    project_dir: str | Path,
    known_schema_ids: Iterable[str] | None = None,
) -> list[dict]:
    """Classify dev-family dispatches in a top-level session transcript and
    re-check their declared ``json``-kind artifacts' current on-disk state.

    Reused verbatim by BOTH ``hooks/stop-obligation-gate.py`` (session-
    terminal check) and ``hooks/posttool-overnight-loop.py`` (cycle-reset
    check) -- neither caller duplicates this scan.

    Dev-family classification (ticket item 3): walks THIS transcript's own
    Agent/Task ``tool_use`` dispatch records (reusing
    ``subagent_restart._read_parent_calls`` -- the same parent-transcript
    scanner the resolver layer above already depends on) for a dispatch
    prompt containing a ``.claude/dev-registry/<token>/`` reference whose
    directory actually exists under ``project_dir``. A dispatch that does
    not match is simply not this gate's concern (not dev-family, or not yet
    reflected on disk) -- never an error.

    For each dev-family-qualifying dispatch whose prompt also parses as a
    well-formed obligation (:func:`parse_obligation`), every declared
    ``json``-kind artifact is re-checked via
    :func:`_validate_artifact_status` (``contract_runtime
    .validate_artifact_for_obligation``). Non-``json`` kinds (``markdown``,
    ``response_block``, ``response_line``) carry no schema-validatable
    path+schema pair here and are skipped -- their resolution is a separate,
    already-existing SubagentStop-level concern (out of this lane's scope;
    mirrors the identical kind-split already live in
    ``hooks/subagentstop-artifact-contract-enforce.py``).

    Read-only; never raises. A malformed transcript, an unparseable
    dispatch, or a validation failure is swallowed per-item (fail-open) so
    one bad record never hides another dispatch's genuinely unresolved
    obligation. Returns one dict per unresolved artifact:
    ``{"task_id", "lane", "role", "artifact_path", "reason"}``.
    """
    results: list[dict] = []
    try:
        path = Path(transcript_path)
        if not path.is_file():
            return results
        calls, _results, _notifications = _read_parent_calls(path)
    except Exception:
        return results

    try:
        project_root = Path(project_dir)
    except TypeError:
        return results

    seen: set[tuple[Any, str]] = set()
    for call in calls.values():
        if not isinstance(call, Mapping):
            continue
        tool_input = call.get("input")
        prompt = tool_input.get("prompt") if isinstance(tool_input, Mapping) else None
        if not isinstance(prompt, str) or not prompt:
            continue
        token_match = _DEV_REGISTRY_TOKEN_RE.search(prompt)
        if token_match is None:
            continue
        token = token_match.group(1)
        try:
            if not (project_root / ".claude" / "dev-registry" / token).is_dir():
                continue
        except Exception:
            continue
        parsed = parse_obligation(prompt, known_schema_ids=known_schema_ids)
        if not isinstance(parsed, ParsedObligation):
            continue
        obligation_doc = parsed.obligation
        task_id = obligation_doc.get("task_id")
        lane = obligation_doc.get("lane")
        role = obligation_doc.get("role")
        artifacts = obligation_doc.get("artifacts")
        if not isinstance(artifacts, list):
            continue
        for artifact in artifacts:
            if not isinstance(artifact, Mapping) or artifact.get("kind") != "json":
                continue
            artifact_path = artifact.get("path")
            schema_id = artifact.get("schema")
            if not isinstance(artifact_path, str) or not artifact_path:
                continue
            if not isinstance(schema_id, str) or not schema_id:
                continue
            dedup_key = (task_id, artifact_path)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            status = _validate_artifact_status(project_root / artifact_path, schema_id)
            if status == "fail":
                results.append({
                    "task_id": task_id,
                    "lane": lane,
                    "role": role,
                    "artifact_path": artifact_path,
                    "reason": "artifact_unresolved",
                })
                continue
            required_values = artifact.get("required_values")
            if status == "skip" or not isinstance(required_values, Mapping):
                continue
            try:
                record = json.loads(
                    (project_root / artifact_path).read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                continue  # vanished/unreadable between reads: fail-open
            for violation in evaluate_required_values(record, required_values):
                results.append({
                    "task_id": task_id,
                    "lane": lane,
                    "role": role,
                    "artifact_path": artifact_path,
                    "reason": violation["reason"],
                    "path": violation["path"],
                    "actual": violation.get("actual"),
                })
    return results
