#!/usr/bin/env python3
"""The ONE authoritative declaration of the hook-landed-files ledger layout (M6).

Before this module, the producer (hooks/doc_sync/hook_ledger.py) and the
consumer (scripts/aggregate-dev-report.py) each restated the layout in their
own prose docstring and shared no definition, so the two sides could drift
without anything noticing -- and they had: the consumer enumerated two
dispatch-prefix name shapes and therefore could not see a directory minted
under a third.

Four contracts live here and are obtained from here by BOTH sides:

  (a) the producer DIRECTORY naming contract          -- ledger_dir()
  (b) the RECORD FILENAME contract, legacy and tuple  -- legacy_record_name(),
                                                         record_name()
  (c) the minted-identity AUTHORITY test              -- is_minted_identity()
  (d) the task_id -> minted-identity SELECTION        -- select_producers()

plus the exclusion-class taxonomy the consumer classifies against, which is
split by UNIT: four RECORD-level classes (a record excluded after it was
loaded) and one DISCOVERY-level class (a directory excluded before any record
was loaded). The two units are never summed.

This module imports nothing outside the standard library and touches no
global state, so the producer can import it inside the PostToolUse hook chain
without widening that chain's failure surface.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

# -- (a) producer directory naming -------------------------------------------

DEV_REGISTRY_RELATIVE = (".claude", "dev-registry")
LEDGER_DIR_NAME = "hook-landed-files"


def dev_registry_root(project_dir) -> Path:
    return Path(project_dir).joinpath(*DEV_REGISTRY_RELATIVE)


def ledger_dir(project_dir, dev_session_id: str) -> Path:
    """The producer directory of one minted cycle identity.

    The directory name IS the resolved dev_session_id -- which
    hooks/prompt-workflow.py::_reserve_dev_registry computes as its own local
    `task_id` and _init_dev_registry then binds to the name `dev_session_id`.
    They are the same minted string by construction.
    """
    return dev_registry_root(project_dir) / dev_session_id / LEDGER_DIR_NAME


# -- (b) record filename ------------------------------------------------------

RECORD_SUFFIX = ".json"
RECORD_FORMAT_VERSION = 1
RECORD_FORMAT_VERSION_FIELD = "ledger_format_version"
RECORD_TASK_FIELD = "dev_session_id"
RECORD_AGENT_FIELD = "source_agent_id"


def legacy_record_name(rel_path: str) -> str:
    """The pre-claimant filename: sha256 of the relative path alone.

    Every record written before the claimant dimension existed carries this
    name. The loader must keep accepting it unchanged: rejecting it would
    discard live evidence, which is a defect, not compliance.
    """
    return hashlib.sha256(rel_path.encode("utf-8")).hexdigest() + RECORD_SUFFIX


def record_name(rel_path: str, dev_session_id: str, source_agent_id: str) -> str:
    """The (path, task, agent) filename -- exact, versioned, drift-proof.

    The key is sha256 over a canonical JSON array with FIXED element order,
    FIXED separators and explicit UTF-8, so the producer and the consumer
    cannot encode the same triple two ways. Two distinct claimant TASKS
    recording the same path therefore land in two distinct files and neither
    overwrites the other, while the SAME (task, agent) re-recording the same
    path still cleanly replaces its own record -- keeping the record count
    bounded by distinct (path, task, agent) triples.
    """
    canonical = json.dumps(
        [rel_path, dev_session_id, source_agent_id], ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest() + RECORD_SUFFIX


# -- claimant identity --------------------------------------------------------

TASK_PROVENANCE_DECLARED = "declared"
TASK_PROVENANCE_DIRECTORY_DERIVED = "directory_derived"


def claimant_of(record: dict, producer_identity: str) -> dict:
    """{task, agent, task_provenance} for one loaded record.

    The claimant unit is the TASK (spec-20260914-052140 Section 5.3 says
    `任务`), not the agent: three agent ids inside one producer directory are
    three agents of ONE task and therefore ONE claimant. `agent` is retained
    as a sub-discriminator within that task so a within-task re-record stays
    distinguishable.

    task_provenance is a LABEL, not a confidence score. A legacy record's
    owning task is the name of the directory the recorder wrote it into, and
    the recorder builds that path directly from the resolved dev_session_id,
    so a directory-derived task is as TRUE as a declared one -- it is merely
    less self-evident. No caller may branch on this field to change an
    outcome.
    """
    declared = record.get(RECORD_TASK_FIELD)
    if isinstance(declared, str) and declared:
        task, provenance = declared, TASK_PROVENANCE_DECLARED
    else:
        task, provenance = producer_identity, TASK_PROVENANCE_DIRECTORY_DERIVED
    agent = record.get(RECORD_AGENT_FIELD)
    if not isinstance(agent, str) or not agent:
        agent = None
    return {"task": task, "agent": agent, "task_provenance": provenance}


def group_claimants(claimants: list) -> list:
    """Sorted, de-duplicated [{task, agents, task_provenance}], ONE entry per task.

    Grouping is PRESENTATIONAL. It never merges two records, never drops an
    agent id, and never collapses two differing digests -- a record excluded
    for any reason is classified and retained separately, never folded away
    here.
    """
    by_task: dict = {}
    for claimant in claimants:
        task = claimant["task"]
        bucket = by_task.setdefault(
            task, {"task": task, "agents": set(), "task_provenance": claimant["task_provenance"]}
        )
        if claimant.get("agent"):
            bucket["agents"].add(claimant["agent"])
    return [
        {"task": t["task"], "agents": sorted(t["agents"]), "task_provenance": t["task_provenance"]}
        for t in sorted(by_task.values(), key=lambda item: item["task"])
    ]


# -- (c) minted-identity authority --------------------------------------------

MINTED_DOCUMENT_RELATIVE = ("docs", "dev")
MINTED_DOCUMENT_PREFIX = "user-requirement-"
MINTED_DOCUMENT_SUFFIX = ".md"


def minted_document_path(project_dir, identity: str) -> Path:
    return Path(project_dir).joinpath(*MINTED_DOCUMENT_RELATIVE) / (
        MINTED_DOCUMENT_PREFIX + identity + MINTED_DOCUMENT_SUFFIX
    )


def is_minted_identity(project_dir, identity: str) -> bool:
    """Whether `identity` is a genuine harness-minted cycle identity.

    The evidence is hook-authored, not name-derived: _reserve_dev_registry
    creates .claude/dev-registry/<id>/ and _init_dev_registry writes
    docs/dev/user-requirement-<id>.md as one co-minted pair. A directory that
    some other command created for its own bookkeeping (a /close directory,
    say) has no such document, which is how a two-command collision sharing
    one embedded timestamp is settled BY EVIDENCE rather than by guessing at
    the prefix.
    """
    try:
        return minted_document_path(project_dir, identity).is_file()
    except OSError:
        return False


# -- (d) task_id -> minted-identity selection ---------------------------------

BINDING_PROVENANCE_FIELD = "binding_provenance"
BINDING_PROVENANCE_TIMESTAMP_INFERRED = "timestamp_inferred"

_TIMESTAMP_RE = re.compile(r"(\d{8}-\d{6})")


def identity_parts(identity: str):
    """(embedded timestamp, suffix-after-it), or None when there is no timestamp.

    The dispatch PREFIX is deliberately NOT part of the key. Prefixes are
    minted at dispatch time, so enumerating them is the very hardcoded-prefix
    defect this replaces; any previously-unseen prefix resolves without a code
    change.

    The SUFFIX is part of the key, in BOTH directions: a lane-suffixed
    identity must not be absorbed into a different cycle's resolution, and a
    lane's own suffixed identity must still resolve for its own suffixed task
    id. Blanket suffix exclusion would hide a lane's records from itself,
    which is the same defect facing the other way.
    """
    match = _TIMESTAMP_RE.search(identity)
    if match is None:
        return None
    return match.group(1), identity[match.end():]


def _record_count(directory: Path) -> int:
    try:
        return sum(1 for child in directory.iterdir() if child.is_file() and child.suffix == RECORD_SUFFIX)
    except OSError:
        return 0


def select_producers(project_dir, task_id: str) -> dict:
    """Resolve a requested task id to the producer directories it may consume.

    Returns
      task_id             the request, echoed
      binding_provenance  always "timestamp_inferred" -- see below
      matched             every record-bearing MINTED identity that matches
      consumed            matched, unless ambiguous, in which case EMPTY
      ambiguous           True when more than one record-bearing match exists
      unauthorised        record-bearing directories the AUTHORITY gate
                          rejected, each with its own record count

    binding_provenance is honest, not decorative. The AUTHORITY question --
    "is <X> a genuine producer identity?" -- is answered by hook-authored
    evidence. The SELECTION question -- "which minted identity answers the
    --task-id this script was invoked with?" -- still matches on the embedded
    timestamp, because NO artifact binds an agent-authored task_id to a minted
    identity: the canonical dev-report carries no session, registry or
    producer key, and the two places that edge could be recorded (the
    aggregator's caller, or a new dev-report field) are outside this lane's
    declared file set. That gap is ESCALATED as a blocked prerequisite; until
    it is closed the inference is LABELLED in the output rather than presented
    as exact.

    `unauthorised` exists so the authority gate can never drop a
    record-bearing directory silently. Its scope is exactly the directories
    this resolution EVALUATED -- those sharing the request's timestamp and
    suffix -- because a gate can only be said to have dropped what it looked
    at. A directory with zero records is neither consumed nor reported: there
    is nothing to lose.
    """
    result = {
        "task_id": task_id,
        BINDING_PROVENANCE_FIELD: BINDING_PROVENANCE_TIMESTAMP_INFERRED,
        "matched": [],
        "consumed": [],
        "ambiguous": False,
        "unauthorised": [],
    }
    want = identity_parts(task_id)
    if want is None:
        return result
    root = dev_registry_root(project_dir)
    try:
        children = sorted(root.iterdir())
    except OSError:
        return result
    for child in children:
        if not child.is_dir() or identity_parts(child.name) != want:
            continue
        directory = child / LEDGER_DIR_NAME
        if not directory.is_dir():
            continue
        records = _record_count(directory)
        if records == 0:
            continue
        if is_minted_identity(project_dir, child.name):
            result["matched"].append(child.name)
        else:
            result["unauthorised"].append({
                "directory": str(directory),
                "identity": child.name,
                "records_not_loaded": records,
                "absent_document": str(minted_document_path(project_dir, child.name)),
                "class": CLASS_PRODUCER_IDENTITY_UNAUTHORISED,
            })
    if len(result["matched"]) > 1:
        result["ambiguous"] = True
    else:
        result["consumed"] = list(result["matched"])
    return result


# -- exclusion-class taxonomy, split by UNIT ----------------------------------

# RECORD-level: a record excluded AFTER it was loaded. Exhaustive.
CLASS_DUAL_LISTING_ADMISSION = "dual_listing_admission"
CLASS_FRESHNESS_MISMATCH = "freshness_mismatch"
CLASS_RECOMPUTE_FAILURE = "recompute_failure"
CLASS_PATH_DEDUPE_SECOND_CLAIMANT = "path_dedupe_second_claimant"

RECORD_LEVEL_CLASSES = (
    CLASS_DUAL_LISTING_ADMISSION,
    CLASS_FRESHNESS_MISMATCH,
    CLASS_RECOMPUTE_FAILURE,
    CLASS_PATH_DEDUPE_SECOND_CLAIMANT,
)
# Deliberate admission behaviour, mirroring resolve-commit-repos.py's own
# independent dual-listing gate. COUNTED under its own label, never warned:
# it is the majority class on live data, and warning on correct behaviour
# would drown the classes that are genuine loss.
RECORD_LEVEL_COUNT_ONLY_CLASSES = (CLASS_DUAL_LISTING_ADMISSION,)
RECORD_LEVEL_LOSS_CLASSES = (
    CLASS_FRESHNESS_MISMATCH,
    CLASS_RECOMPUTE_FAILURE,
    CLASS_PATH_DEDUPE_SECOND_CLAIMANT,
)

# DISCOVERY-level: a DIRECTORY excluded BEFORE any record was loaded.
# Deliberately NOT a fifth record-level class -- it counts a different unit,
# and folding it into the record-level census would corrupt that census.
CLASS_PRODUCER_IDENTITY_UNAUTHORISED = "producer_identity_unauthorised"
DISCOVERY_LEVEL_CLASSES = (CLASS_PRODUCER_IDENTITY_UNAUTHORISED,)

SUMMARY_BLOCK_RECORD_LEVEL = "record_level"
SUMMARY_BLOCK_DISCOVERY_LEVEL = "discovery_level"

# The additive, non-blocking canonical-dev-report array that gives an excluded
# claimant a DURABLE home. Exclusion from landing must never be loss of
# identity. Absent -- not empty -- when nothing was excluded by a loss class.
EXCLUSIONS_FIELD = "hook_ledger_exclusions"
EXCLUSION_ENTRY_FIELDS = (
    "registry_file",
    "path",
    "claimant",
    "declared_diff_sha256",
    "recomputed_diff_sha256",
    "class",
    BINDING_PROVENANCE_FIELD,
)
