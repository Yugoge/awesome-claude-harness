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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:  # imported as hooks.lib.obligation (tests) or lib.obligation (hooks)
    from . import roster
    from .subagent_restart import (
        AGENT_RE,
        SESSION_RE,
        RestartError,
        _read_parent_calls,
        account_project_roots,
        project_slug,
    )
except ImportError:  # hooks/lib placed directly on sys.path
    import roster  # type: ignore[no-redef]
    from subagent_restart import (  # type: ignore[no-redef]
        AGENT_RE,
        SESSION_RE,
        RestartError,
        _read_parent_calls,
        account_project_roots,
        project_slug,
    )


# --------------------------------------------------------------------------
# Grammar constants -- markers and field names from design §1.2 (:83-113).
# Every value set is read from the file that declares it, never copied here:
# a role is an agent file (roster.roles()), a pipeline a command file with
# front matter, a profile and an artifact kind the schema's enums.
# --------------------------------------------------------------------------

OBLIGATION_VERSION = "1"
OBLIGATION_OPEN_TOKEN = "<obligation"
OBLIGATION_CLOSE_TAG = "</obligation>"

_HARNESS_DIR = Path(__file__).resolve().parent.parent.parent
_SCHEMAS_DIR = _HARNESS_DIR / "schemas"
_COMMANDS_DIR = _HARNESS_DIR / "commands"


def _schema(schema_id: str) -> Any:
    return json.loads((_SCHEMAS_DIR / f"{schema_id}.json").read_text(encoding="utf-8"))


def _schema_enum(schema_id: str, dotted: str) -> frozenset[str]:
    """The enum ``schemas/<schema_id>.json`` declares at ``dotted`` (walked
    through ``properties``), read at import so no copy here can drift from the
    schema. An unreadable schema or a missing path yields the empty set:
    nothing is legal, so the gate that reads the value refuses it, and
    importing this module never fails over a schema file."""
    try:
        node = _schema(schema_id)
        for part in dotted.split("."):
            node = node["properties"][part]
        return frozenset(value for value in node["enum"] if isinstance(value, str))
    except (OSError, ValueError, KeyError, TypeError):
        return frozenset()


def _artifact_fields_by_kind() -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    """Exact per-kind field sets (design :95-107), as schemas/obligation.v1.json
    declares them: each kind of its ``kind`` enum, with ``kind`` and the fields
    the kind's then-clause requires, and as optional the other fields it names
    (markdown's terminal_line_regex and waived_by_response: the sentinel
    waiver exists only for the close-QA bundle, design §1.4.5). Read at import
    like PROFILES; an unreadable schema declares no kind, so every block is
    refused by the gate that reads it."""
    try:
        items = _schema("obligation.v1")["properties"]["artifacts"]["items"]
        fields = {kind: (("kind",), ()) for kind in items["properties"]["kind"]["enum"]}
        for rule in items.get("allOf", []):
            kind = rule.get("if", {}).get("properties", {}).get("kind", {}).get("const")
            if kind in fields:
                required = tuple(rule["then"].get("required", []))
                named = rule["then"].get("properties", {})
                fields[kind] = (("kind",) + required, tuple(k for k in named if k not in required))
        return fields
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def _null_task_id_profiles() -> frozenset[str]:
    """The profiles schemas/obligation.v1.json exempts from its string task_id
    rule (the allOf entry whose then-clause makes task_id a string), read at
    import like PROFILES; an unreadable schema exempts none."""
    try:
        for rule in _schema("obligation.v1")["allOf"]:
            if rule.get("then", {}).get("properties", {}).get("task_id", {}).get("type") == "string":
                return frozenset(rule["if"]["properties"]["profile"]["not"]["enum"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return frozenset()


PROFILES = _schema_enum("obligation.v1", "profile")  # design :92-93
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

ARTIFACT_FIELDS_BY_KIND = _artifact_fields_by_kind()  # (required, optional) per kind
ARTIFACT_KINDS = frozenset(ARTIFACT_FIELDS_BY_KIND)

# task_id shape: an identifier-safe id (no path separator), pinned to the
# \d{8}-\d{6} prefix convention (ticket M3); G2's legacy report correlation
# anchors on this same shape.
# Also accepts the ids /dev and /dev-command mint (hooks/prompt-workflow.py
# _reserve_dev_registry) and their lane form (commands/dev.md fan-out):
# ``dev[-command]-<yyyymmdd-hhmmss>[-lN]``. The pattern string is identical to
# schemas/obligation.v1.json properties.task_id.pattern (parity-tested).
TASK_ID_RE = re.compile(
    r"^(?:\d{8}-\d{6}[A-Za-z0-9._-]*|dev-(?:command-)?\d{8}-\d{6}(?:-l\d+)?)$"
)
_MINTED_PREFIX_RE = re.compile(r"^dev-(?:command-)?(?=\d{8}-\d{6})")
_LANE_SUFFIX_RE = re.compile(r"-l\d+$")

# Closed terminal vocabulary (design D1/R2): schema id -> dotted path -> legal
# terminal values. Only which field of which schema is terminal is stated
# here; the values are that field's enum, read from the schema itself.
# Readers decide through terminal_status() and never declare a set of their own.
TERMINAL_VOCABULARY: dict[str, dict[str, frozenset[str]]] = {
    schema_id: {dotted: _schema_enum(schema_id, dotted)}
    for schema_id, dotted in (
        ("dev-report.v2", "dev.status"),
        ("dev-report.v1", "status"),
        ("ba-qa-report.v1", "verdict"),
        ("qa-report.v2", "qa.status"),
        ("qa-report.v1", "verdict"),
        ("do-report.v1", "do.status"),
    )
}


def terminal_status(schema_id: str, record: Any) -> str | None:
    """The value ``record`` carries at ``schema_id``'s terminal field when that
    value is in the field's vocabulary, else None (absent, malformed or not
    terminal). The one decision on a report's terminal status: a reader that
    needs more than "terminal" compares the value returned (only
    ``completed`` lets /close and dev-lifecycle.py take /do work as done)."""
    for dotted, legal in TERMINAL_VOCABULARY.get(schema_id, {}).items():
        value = record
        for part in dotted.split("."):
            value = value.get(part) if isinstance(value, Mapping) else None
        if isinstance(value, str) and value in legal:
            return value
    return None


# task_id null legality (design :85-86 + ticket M3): legal under the profiles
# the schema exempts, unconditionally except for commit-qa (the /commit --bulk
# context is transcript-derived, G1 check 3 -- invisible to a pure parser, so
# the validator ACCEPTS and returns an undischarged-condition flag for the
# gate cycle to discharge).
CONDITIONAL_NULL_TASK_ID_PROFILE = "commit-qa"
NULL_TASK_ID_PROFILES = _null_task_id_profiles() - {CONDITIONAL_NULL_TASK_ID_PROFILE}
UNDISCHARGED_TASK_ID_NULL = "task_id_null_requires_bulk_context"

# Dispatch-clock bound (design §1.3-G1 check 2: |dispatched_at - now| <= 300s).
DISPATCH_CLOCK_BOUND_SECONDS = 300
# File-kind freshness slack (design §1.2 freshness: mtime >= dispatched_at - 2s
# covers filesystem timestamp granularity only; response kinds carry none --
# inherently produced by this run). A file kind is one whose fields require a
# path, as the schema declares each kind's fields.
FILE_FRESHNESS_SLACK_SECONDS = 2
FRESHNESS_SLACK_SECONDS_BY_KIND: dict[str, int | None] = {
    kind: FILE_FRESHNESS_SLACK_SECONDS if "path" in required else None
    for kind, (required, _optional) in ARTIFACT_FIELDS_BY_KIND.items()
}

# Resolver cross-check statuses.
CROSS_CHECK_OK = "ok"
CROSS_CHECK_SKIPPED_PARENT_UNREADABLE = "skipped_parent_unreadable"
CROSS_CHECK_SKIPPED_NO_META = "skipped_no_meta"

_OPEN_TAG_RE = re.compile(r"<obligation\b([^>]*)>")
_VERSION_ONLY_ATTRS_RE = re.compile(r'\s*v="([^"]*)"\s*')


# --------------------------------------------------------------------------
# Typed outcomes (grammar layer)
# --------------------------------------------------------------------------

class _Outcome:
    """What ``@dataclass(frozen=True)`` gave the outcomes below, written out
    so that loading this module does not import dataclasses (and the inspect
    it loads), a cost every hook that loads it paid at each call. Fields are
    set once in ``__init__``; equality, hash and repr go over ``_fields``."""

    _fields: tuple[str, ...] = ()

    def _set(self, **fields: Any) -> None:
        self.__dict__.update(fields)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(f"cannot assign to field {name!r}")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"cannot delete field {name!r}")

    def __eq__(self, other: Any) -> Any:
        if self is other:
            return True
        if other.__class__ is self.__class__:
            return all(getattr(self, name) == getattr(other, name) for name in self._fields)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(tuple(getattr(self, name) for name in self._fields))

    def __repr__(self) -> str:
        fields = ", ".join(f"{name}={getattr(self, name)!r}" for name in self._fields)
        return f"{self.__class__.__qualname__}({fields})"


class NoBlock(_Outcome):
    """The prompt carries no obligation block (design M5 zero-block case)."""

    _fields = ("outcome",)

    def __init__(self, outcome: str = "no_block") -> None:
        self._set(outcome=outcome)


class Rejection(_Outcome):
    """Fail-closed rejection with a machine-readable named reason."""

    _fields = ("reason", "field", "detail", "outcome")

    def __init__(self, reason: str, field: str = "", detail: str = "", outcome: str = "rejected") -> None:
        self._set(reason=reason, field=field, detail=detail, outcome=outcome)


class ExtractedBlock(_Outcome):
    """Raw body text of the single well-versioned obligation block."""

    _fields = ("body",)

    def __init__(self, body: str) -> None:
        self._set(body=body)


class Validated(_Outcome):
    """Document accepted; ``undischarged`` lists conditions a later gate
    cycle must discharge (e.g. ``task_id_null_requires_bulk_context``)."""

    _fields = ("undischarged",)

    def __init__(self, undischarged: tuple[str, ...] = ()) -> None:
        self._set(undischarged=undischarged)


class ParsedObligation(_Outcome):
    """Extraction + parse + validation all succeeded."""

    _fields = ("obligation", "undischarged")

    def __init__(self, obligation: Mapping[str, Any], undischarged: tuple[str, ...] = ()) -> None:
        self._set(obligation=obligation, undischarged=undischarged)


# --------------------------------------------------------------------------
# Typed outcomes (resolver layer, design §1.3-G2)
# --------------------------------------------------------------------------

class Resolved(_Outcome):
    """A well-formed obligation was resolved from this agent's own dispatch
    prompt at ladder rung L0 (payload-supplied path) or L1 (session-scoped
    store construction)."""

    _fields = ("obligation", "rung", "prompt", "transcript_path", "cross_check", "undischarged", "outcome")

    def __init__(self, obligation: Mapping[str, Any], rung: str, prompt: str, transcript_path: str,
                 cross_check: str, undischarged: tuple[str, ...] = (), outcome: str = "resolved") -> None:
        self._set(obligation=obligation, rung=rung, prompt=prompt, transcript_path=transcript_path,
                  cross_check=cross_check, undischarged=undischarged, outcome=outcome)


class NoObligationInPrompt(_Outcome):
    """The dispatch prompt was resolved but carries no obligation block --
    the honest result for every pre-rollout dispatch. DISTINCT from
    ``Unresolvable`` (no correlation) by binding contract."""

    _fields = ("prompt", "rung", "transcript_path", "cross_check", "outcome")

    def __init__(self, prompt: str, rung: str, transcript_path: str, cross_check: str,
                 outcome: str = "no_obligation_in_prompt") -> None:
        self._set(prompt=prompt, rung=rung, transcript_path=transcript_path, cross_check=cross_check,
                  outcome=outcome)


class Unresolvable(_Outcome):
    """No correlation exists (missing transcript, unreadable store, meta
    mismatch, role mismatch, invalid embedded obligation) -- fail-closed,
    never a guess, never a fallback to an unrelated transcript. ``prompt`` is
    the dispatch prompt when it was read and correlated but its obligation
    failed (invalid_obligation, role_mismatch); empty otherwise."""

    _fields = ("reason", "detail", "outcome", "prompt")

    def __init__(self, reason: str, detail: str = "", outcome: str = "unresolvable", prompt: str = "") -> None:
        self._set(reason=reason, detail=detail, outcome=outcome, prompt=prompt)


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
    for path_key in ("path", "monolith"):
        if path_key in entry and not _legal_repo_relative_path(entry[path_key]):
            return Rejection(reason="illegal_path", field=f"{label}.{path_key}")
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
    # Roles and pipelines are read when a block is validated, from the files
    # that declare them: the roster, and the command files by the same
    # front-matter rule. An unreadable directory makes none legal, so the
    # gate refuses the block.
    for key, allowed in (
        ("role", roster.roles()),
        ("pipeline", roster.roles(_COMMANDS_DIR)),
        ("profile", PROFILES),
    ):
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
# Task-id families (pure): the minted ``dev-`` / ``dev-command-`` prefix names
# the registry directory; artifacts are named with the id without it.
# --------------------------------------------------------------------------

def canonical_task_id(task_id: Any) -> str | None:
    """The id artifacts are named with: a leading ``dev-command-`` or ``dev-``
    stripped (``<ts>``, ``<ts>-l<N>``, ``<ts>-<N>``); None for a non-string."""
    if not isinstance(task_id, str) or not task_id:
        return None
    return _MINTED_PREFIX_RE.sub("", task_id, count=1)


def task_family(task_id: Any) -> str | None:
    """Collection-barrier family: the canonical id without a fan-out lane
    suffix, so lanes ``-l1``/``-l2`` of one cycle share a family while
    overnight pipelines ``<ts>-1``/``<ts>-2`` stay apart."""
    canonical = canonical_task_id(task_id)
    return _LANE_SUFFIX_RE.sub("", canonical) if canonical else None


def registry_dir_for(project_dir: str | Path, task_id: Any) -> Path | None:
    """The cycle's ``.claude/dev-registry/<name>/`` as the UserPromptSubmit
    hook names it (``dev-<ts>`` or ``dev-command-<ts>``; a lane suffix is not
    part of the name). An id minted with a prefix keeps it; a bare ``<ts>``
    id resolves to whichever of the two directories exists (``dev-`` first)
    and defaults to ``dev-<ts>``. None when the id carries no timestamp."""
    if not isinstance(task_id, str):
        return None
    stamp = re.search(r"\d{8}-\d{6}", task_id)
    if stamp is None:
        return None
    root = Path(project_dir) / ".claude" / "dev-registry"
    if task_id.startswith("dev-command-"):
        return root / f"dev-command-{stamp.group()}"
    candidates = [root / f"dev-{stamp.group()}"]
    if not task_id.startswith("dev-"):
        candidates.append(root / f"dev-command-{stamp.group()}")
    return next((c for c in candidates if c.is_dir()), candidates[0])


# --------------------------------------------------------------------------
# Resolver: own-dispatch-obligation resolution (design §1.3-G2, rungs L0/L1)
# --------------------------------------------------------------------------

def read_first_record_prompt(transcript_path: str | Path) -> str | None:
    """Return the dispatch prompt from a subagent transcript's first MESSAGE
    record when it is a user message (design §1.3-G2: "first record is a user
    message"). Records that carry no message (queue-operation, attachment and
    the like) are skipped; the first user/assistant record decides.

    Handles both persisted ``message.content`` shapes: plain string (observed
    live on this store) and content-block list (the shape the parent-side
    reader ``_read_parent_calls`` handles at subagent_restart.py:340-346).
    Read-only; returns None when unreadable, not type=user, or textless.
    """
    record = None
    try:
        with Path(transcript_path).open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    candidate = json.loads(line)
                except ValueError:
                    return None
                if isinstance(candidate, dict) and candidate.get("type") in ("user", "assistant"):
                    record = candidate
                    break
    except OSError:
        return None
    if record is None or record.get("type") != "user":
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
        return Unresolvable(reason="invalid_obligation", detail=parsed.reason, prompt=prompt)
    if expected_role is not None and parsed.obligation.get("role") != expected_role:
        return Unresolvable(
            reason="role_mismatch", detail=repr(parsed.obligation.get("role")), prompt=prompt
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
# Dispatch records: what a session's own dispatches declared
# --------------------------------------------------------------------------

def dispatch_obligations(
    transcript_path: str | Path,
    known_schema_ids: Iterable[str] | None = None,
) -> list[dict]:
    """The obligation blocks a top-level session transcript's own Agent/Task
    dispatch records carry, in record order: one ``{"tool_use_id", "line",
    "subagent_type", "obligation", "prompt"}`` per dispatch whose prompt parses as a
    well-formed obligation (:func:`parse_obligation`).

    The record walk a reader of "the dispatch that declared this artifact"
    builds on (it keys the records by each obligation's own task_id). It
    reuses ``subagent_restart._read_parent_calls``, the scanner the resolver
    layer above reads parent transcripts with, and judges nothing: no
    artifact on disk is read (each is decided at its producer's stop, G2, and
    at the next dispatch, G3). Read-only; never raises: an unreadable
    transcript, or a dispatch whose prompt carries no well-formed block,
    contributes nothing.
    """
    try:
        calls, _results, _notifications = _read_parent_calls(Path(transcript_path))
    except Exception:
        return []
    found: list[dict] = []
    for call in sorted(calls.values(), key=lambda c: c.get("line", 0)):
        tool_input = call.get("input")
        prompt = tool_input.get("prompt") if isinstance(tool_input, Mapping) else None
        if not isinstance(prompt, str) or not prompt:
            continue
        parsed = parse_obligation(prompt, known_schema_ids=known_schema_ids)
        if isinstance(parsed, ParsedObligation):
            found.append({
                "tool_use_id": call.get("tool_use_id"),
                "line": call.get("line"),
                "subagent_type": tool_input.get("subagent_type"),
                "obligation": parsed.obligation,
                "prompt": prompt,
            })
    return found


# --------------------------------------------------------------------------
# Declaring dispatch (P1b E3): who owes an artifact of a task. The one reader
# every route and every role question about an artifact takes its answer
# from, in place of a table from file names to roles (D21).
# --------------------------------------------------------------------------

# A placeholder of a command file's template path: <task_id>, {pipeline.x}.
_TEMPLATE_PLACEHOLDER_RE = re.compile(r"<[^<>/\n]+>|\{[^{}/\s]+\}")
# A worked example: the block's JSON written out in the template.
_TEMPLATE_BLOCK_RE = re.compile(r'<obligation v="1">\s*(\{.*?\})\s*</obligation>', re.S)
# The sentence form: "embed `<obligation v="1">{...}</obligation>` here with role="qa", ..., artifacts=[...]".
_TEMPLATE_SENTENCE_RE = re.compile(r'<obligation v="1">\{\.\.\.\}</obligation>`[^\n]*?\bwith\b([^\n]*)')
_TEMPLATE_FIELD_RE = re.compile(r'\b(role|pipeline|profile)="([^"]*)"')
_STEP_LABEL_RE = re.compile(r"\bStep (\d+[A-Za-z]?)\b")
_STEP_HEADING_RE = re.compile(r"^#{1,6}[^\n]*?\bStep (\d+[A-Za-z]?)\b", re.M)


def _lib_module(name: str):
    """A sibling module of hooks/lib, imported when first needed so the
    grammar and resolver layers above load nothing more."""
    import importlib
    try:
        return importlib.import_module(f".{name}", __package__) if __package__ else importlib.import_module(name)
    except ImportError:
        return importlib.import_module(name)


def _session_transcripts(project_dir: str | Path, roots: Iterable[str | Path] | None) -> list[Path]:
    """Every top-level session transcript the CLI keeps for the project, in
    every account root (the store candidate_transcript_paths walks)."""
    slug = project_slug(project_dir)
    found: list[Path] = []
    for root in (list(roots) if roots is not None else account_project_roots()):
        try:
            found.extend(sorted((Path(root) / slug).glob("*.jsonl")))
        except OSError:
            continue
    return found


def _span_openers(transcript: Path, commands: frozenset) -> list[tuple[int, str, str]]:
    """(line, command, arguments) of each human-typed harness command."""
    stop_contract = _lib_module("stop_contract")
    openers = []
    try:
        with transcript.open(encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, 1):
                if '"user"' not in line:
                    continue
                try:
                    found = stop_contract.span_opener(json.loads(line), commands)
                except ValueError:
                    continue
                if found:
                    openers.append((number, found[0], found[1]))
    except OSError:
        return []
    return openers


def _task_records(task_id: str, project_dir: str | Path,
                  roots: Iterable[str | Path] | None) -> list[dict]:
    """Every dispatch record of the task in every session of the project:
    dispatch_obligations' records whose obligation's task_id is of the task's
    family (lanes -l1, -l2 and the minted dev- prefix included), each with its
    session transcript and the harness command whose span holds it. The scan
    reads only the transcripts whose bytes name the family."""
    family = task_family(task_id)
    if not family:
        return []
    commands = _lib_module("stop_contract").harness_commands()
    # A dispatch of the task is appended to its transcript after the task id
    # was minted, so a transcript last written a day or more before the id's
    # timestamp (local or UTC) holds none of them.
    stamp = re.search(r"\d{8}-\d{6}", family)
    try:
        cutoff = datetime.strptime(stamp.group(), "%Y%m%d-%H%M%S").timestamp() - 86400 if stamp else None
    except ValueError:
        cutoff = None
    seen: set[tuple[str, str]] = set()
    records: list[dict] = []
    for transcript in _session_transcripts(project_dir, roots):
        try:
            if cutoff is not None and transcript.stat().st_mtime < cutoff:
                continue
            if family.encode() not in transcript.read_bytes():
                continue
        except OSError:
            continue
        openers = _span_openers(transcript, commands)
        for record in dispatch_obligations(transcript):
            if task_family(record["obligation"].get("task_id")) != family:
                continue
            key = (transcript.stem, str(record["tool_use_id"]))
            if key in seen:  # the same session's copy in another account root
                continue
            seen.add(key)
            span = None
            for line, command, args in openers:
                if line < (record.get("line") or 0):
                    span = (command, args)
            records.append(dict(record, transcript=transcript, span=span))
    return records


def _latest(records: list[dict]) -> dict | None:
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return max(records, default=None, key=lambda r: (
        parse_iso8601(r["obligation"].get("dispatched_at")) or epoch, r.get("line") or 0))


def _dispatch_answer(source: str, record: dict) -> dict:
    ob = record["obligation"]
    return {"source": source, "task_id": ob.get("task_id"), "lane": ob.get("lane"),
            "role": ob.get("role"), "subagent_type": record.get("subagent_type"),
            "obligation": ob, "prompt": record.get("prompt"),
            "session_id": record["transcript"].stem, "tool_use_id": record.get("tool_use_id")}


def _bind_template_path(pattern: Any, path: str, family: str) -> dict[str, str] | None:
    """The placeholder values under which ``pattern`` names ``path``, when one
    of them names the task (its family); else None."""
    if not isinstance(pattern, str):
        return None
    parts, names, pos = [], [], 0
    for match in _TEMPLATE_PLACEHOLDER_RE.finditer(pattern):
        parts.append(re.escape(pattern[pos:match.start()]) + "([^/]+?)")
        names.append(match.group())
        pos = match.end()
    if not names:
        return None
    matched = re.fullmatch("".join(parts) + re.escape(pattern[pos:]), path)
    if matched is None:
        return None
    values: dict[str, str] = {}
    for name, value in zip(names, matched.groups()):
        if values.setdefault(name, value) != value:
            return None
    if not any(task_family(value) == family for value in values.values()):
        return None
    return values


def _bound(value: Any, values: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return _TEMPLATE_PLACEHOLDER_RE.sub(lambda m: values.get(m.group(), m.group()), value)
    if isinstance(value, list):
        return [_bound(v, values) for v in value]
    if isinstance(value, Mapping):
        return {k: _bound(v, values) for k, v in value.items()}
    return value


def _bracketed(text: str, start: int) -> str | None:
    """The JSON array or object opening at ``start``, by bracket depth outside
    strings; None when it never closes."""
    depth, quoted, escaped = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _template_json(body: str) -> Any:
    """A worked example's JSON; a value the template leaves to the
    orchestrator as a bare <...> (outside every string) reads as null."""
    try:
        return json.loads(body)
    except ValueError:
        pass
    out, quoted, escaped, index = [], False, False, 0
    while index < len(body):
        char = body[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "<":
            end = body.find(">", index)
            if end > index:
                out.append("null")
                index = end + 1
                continue
        out.append(char)
        index += 1
    try:
        return json.loads("".join(out))
    except ValueError:
        return None


def command_templates(command: str, commands_dir: str | Path | None = None) -> list[dict]:
    """The obligation templates commands/<command>.md writes, in text order:
    each worked example and each "embed ... here with role=..., artifacts=[...]"
    sentence, as ``{"role", "pipeline", "profile", "artifacts", "step"}``,
    ``step`` being the label of the "Step N" heading the template sits under."""
    try:
        text = (Path(commands_dir) if commands_dir else _COMMANDS_DIR).joinpath(f"{command}.md").read_text(encoding="utf-8")
    except OSError:
        return []
    headings = [(m.start(), m.group(1)) for m in _STEP_HEADING_RE.finditer(text)]
    found: list[tuple[int, dict]] = []
    for match in _TEMPLATE_BLOCK_RE.finditer(text):
        doc = _template_json(match.group(1))
        if isinstance(doc, dict):
            found.append((match.start(), doc))
    for match in _TEMPLATE_SENTENCE_RE.finditer(text):
        tail = match.group(1)
        at = tail.find("artifacts=[")
        body = _bracketed(tail, at + len("artifacts=")) if at >= 0 else None
        try:
            artifacts = json.loads(body) if body else None
        except ValueError:
            continue
        doc = {k: v for k, v in reversed(_TEMPLATE_FIELD_RE.findall(tail[:at]))}
        found.append((match.start(), dict(doc, artifacts=artifacts)))
    templates = []
    for offset, doc in sorted(found, key=lambda pair: pair[0]):
        if not isinstance(doc.get("artifacts"), list):
            continue
        step = None
        for at, label in headings:
            if at < offset:
                step = label
        templates.append({"role": doc.get("role"), "pipeline": doc.get("pipeline"),
                          "profile": doc.get("profile"), "artifacts": doc["artifacts"], "step": step})
    return templates


def _step_label(step: Mapping) -> str | None:
    match = _STEP_LABEL_RE.match(str(step.get("content") or ""))
    return match.group(1) if match else None


def _canonical_step(family: str, path: str, spans: list[tuple[str, str]],
                    template_sources: list[str]) -> dict | None:
    """The canonical todo step of a command the task ran that owes ``path``:
    a step that declares it itself (the main agent's own, as /close's
    late-repair Step 0 declares finalize's effective report), else the step
    whose dispatch template declares it (the step under whose heading the
    template sits, else the step whose subagent_call names the template's
    role). Each step is returned with what its entry names."""
    todo_canonical = _lib_module("todo_canonical")
    for command, args in spans:
        steps = todo_canonical.run_todo_script(command, args) or []
        for step in steps:
            for artifact in step.get("artifacts") or []:
                if isinstance(artifact, Mapping) and _bind_template_path(artifact.get("path"), path, family):
                    return {"source": "todo_step", "command": command, "arguments": args,
                            "step": step.get("content"), "subagent_call": step.get("subagent_call"),
                            "template": None}
        for source in [command] + [s for s in template_sources if s != command]:
            for template in command_templates(source):
                for artifact in template["artifacts"]:
                    values = _bind_template_path(artifact.get("path") if isinstance(artifact, Mapping) else None,
                                                 path, family)
                    if values is None:
                        continue
                    owner = next((s for s in steps if _step_label(s) == template["step"]), None)
                    call = owner.get("subagent_call") if owner else None
                    if owner is None or (call and call.get("subagent_type") != template["role"]):
                        owner = next((s for s in steps if (s.get("subagent_call") or {}).get("subagent_type")
                                      == template["role"]), owner)
                    if owner is None:
                        continue
                    return {"source": "todo_step", "command": command, "arguments": args,
                            "step": owner.get("content"), "subagent_call": owner.get("subagent_call"),
                            "template": dict(_bound({k: template[k] for k in ("role", "pipeline", "profile")},
                                                    values),
                                             artifacts=_bound(template["artifacts"], values))}
    return None


def _lane_dispatch(family: str, path: str, records: list[dict], spans: list[tuple[str, str]],
                   template_sources: list[str]) -> dict | None:
    """A path a template declares for the cycle itself (its placeholder bound
    to the task's own id, not a lane's), in a cycle whose dispatches of that
    template's role ran per lane: what the lanes produce together, as the
    fan-out's canonical aggregate, which the lane-completeness hook writes
    whenever a lane's dev writes its report. Its owner is the latest of those
    lane dispatches; None otherwise."""
    for source in dict.fromkeys([command for command, _args in spans] + template_sources):
        for template in command_templates(source):
            for artifact in template["artifacts"]:
                values = _bind_template_path(artifact.get("path") if isinstance(artifact, Mapping) else None,
                                             path, family)
                if values is None or family not in {canonical_task_id(v) for v in values.values()}:
                    continue
                lanes = [r for r in records
                         if r["obligation"].get("role") == template["role"] and r["obligation"].get("lane")]
                if lanes:
                    return _dispatch_answer("lane", _latest(lanes))
    return None


def _writer(records: list[dict], path: str, project_dir: str | Path) -> dict | None:
    """The latest dispatch of the task whose own tool calls wrote ``path``
    (TC-46's write set, command_span.write_set: E6's producer of "which files
    this agent wrote"): a Write or Edit of it counts first; only when none did
    does the latest whose own Bash commands name it (a verifier's read names
    the file too, so a mention never outranks a write)."""
    command_span = _lib_module("command_span")
    subagent_restart = _lib_module("subagent_restart")
    written, named, metadata = [], [], {}
    for record in records:
        transcript = record["transcript"]
        if transcript not in metadata:
            metadata[transcript] = subagent_restart._metadata_by_tool_use(transcript)
        meta = metadata[transcript].get(record.get("tool_use_id"))
        found = command_span.write_set(meta["agent_transcript_path"], project_dir) if meta else None
        if found is not None and path in found.written:
            written.append(record)
        elif found is not None and path in found.named:
            named.append(record)
    owner = _latest(written) or _latest(named)
    return _dispatch_answer("writer", owner) if owner else None


def declaring_dispatch(
    task_id: str,
    path: str | Path,
    project_dir: str | Path,
    roots: Iterable[str | Path] | None = None,
) -> dict | None:
    """Who owes ``path`` for the task ``task_id``, read from the task's
    dispatch records in every session the project's transcript store holds
    (a /close or /commit often runs in a later session than its /dev):

    - ``{"source": "dispatch", ...}``: the latest dispatch whose obligation
      declares the path (task_id, lane, role, subagent_type, the whole
      obligation, its prompt, session and tool_use id);
    - ``{"source": "lane", ...}``: a path a template declares for the cycle
      itself, whose dispatches of that role ran per lane (the fan-out's
      canonical aggregate): the latest of those lane dispatches, whose write of
      its own report runs the hook that writes the aggregate;
    - ``{"source": "todo_step", "command", "arguments", "step",
      "subagent_call", "template"}``: no dispatch has declared it yet; the
      canonical step of scripts/todo/<command>.py, for a command the task
      ran, that owes it, with the entry's own subagent_call (None for the
      main agent's own step) and the template that declares the path, bound
      to its values (None when the step declares the path itself);
    - ``{"source": "writer", ...}``: a file no declaration names (a product
      file): the dispatch whose own tool calls wrote it;
    - None: nothing names an owner.

    Read-only; judges nothing on disk."""
    root = Path(project_dir)
    rel = Path(path)
    if rel.is_absolute():
        try:
            rel = rel.resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            return None
    wanted = rel.as_posix()
    family = task_family(task_id)
    records = _task_records(task_id, project_dir, roots)
    declaring = [r for r in records
                 if any(isinstance(a, Mapping) and isinstance(a.get("path"), str)
                        and Path(a["path"]).as_posix() == wanted
                        for a in r["obligation"].get("artifacts") or [])]
    found = _latest(declaring)
    if found is not None:
        return _dispatch_answer("dispatch", found)
    spans = list(dict.fromkeys(r["span"] for r in records if r["span"]))
    pipelines = list(dict.fromkeys(str(r["obligation"].get("pipeline")) for r in records))
    lane = _lane_dispatch(family, wanted, records, spans, pipelines) if family else None
    if lane is not None:
        return lane
    step = _canonical_step(family, wanted, spans, pipelines) if family else None
    if step is not None:
        return step
    return _writer(records, wanted, project_dir)


def _main(argv: list[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="obligation.py")
    sub = parser.add_subparsers(dest="command", required=True)
    owing = sub.add_parser("declaring-dispatch", help="who owes an artifact path of a task (JSON, or null)")
    owing.add_argument("--task-id", required=True)
    owing.add_argument("--path", required=True)
    owing.add_argument("--project-dir", default="")
    ns = parser.parse_args(argv)
    answer = declaring_dispatch(ns.task_id, ns.path, ns.project_dir or Path.cwd())
    print(json.dumps(answer, sort_keys=True))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
