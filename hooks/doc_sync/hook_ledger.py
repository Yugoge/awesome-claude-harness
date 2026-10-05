#!/usr/bin/env python3
"""Write-side ledger for hook-authored side-effect files (backlog #122, M1/M2).

hooks/doc_sync/main.py calls record_landed_files() right after
process_parent_dirs() regenerates a directory's README.md/INDEX.md as a
PostToolUse side effect of a dev agent's own Write/Edit/NotebookEdit call.
Those regenerated files never go through Edit/Write themselves, so they can
never enter a dev-report's own owned_edits ledger (agents/dev.md's
contract) -- this module gives them a separate, honestly-labeled
declaration path that scripts/aggregate-dev-report.py merges into the
existing files_landed_whole exemption channel (backlog #121) for
single-lane (N==1) dev cycles.

The layout this module writes is declared ONCE, in ledger_contract.py, and
the consumer obtains it from there too -- neither side restates it.

Fail-open throughout, mirroring hooks/posttool-codex-skill-ledger.py: never
raise, never block the PostToolUse hook chain. A dev-registry resolution
failure, a git subprocess failure, or a write failure all result in no
record for that path.

What CHANGED (ticket dev-20260927-135305-r02, M1/M7): the record key gained
the claimant dimension it never had, and failing open stopped meaning
failing INVISIBLY. record_landed_files() returns a bounded list of
structured failure descriptors -- it still never raises -- and main.py folds
them into the single capped PostToolUse output object notice.py already
prints. A LEGITIMATE no-op stays silent: doc_sync fires on every Write/Edit/
NotebookEdit in the whole harness, so "this agent is not a dev agent" is the
majority outcome, and reporting it would manufacture exactly the
false-positive surface that has to stay clear.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .ledger_contract import (
    RECORD_AGENT_FIELD,
    RECORD_FORMAT_VERSION,
    RECORD_FORMAT_VERSION_FIELD,
    RECORD_TASK_FIELD,
    ledger_dir,
    record_name,
)
from .regions import RegenStatus

HONEST_REASON = "PostToolUse doc-sync regeneration side effect; not reviewed by dev"

# The SIX failure classes of M7. Each is a no-op that means something went
# wrong, as opposed to the FOUR legitimate no-ops (no results; no agent_id;
# an agent that POSITIVELY RESOLVES to a non-dev role; no WRITTEN record),
# which produce no descriptor at all.
FAILURE_AGENT_UNRESOLVABLE = "agent_unresolvable"
FAILURE_DEV_SESSION_ID_MISSING = "dev_session_id_missing"
FAILURE_RECORD_PATH_UNUSABLE = "record_path_unusable"
FAILURE_DIFF_SHA256_FAILED = "diff_sha256_failed"
FAILURE_LEDGER_WRITE_FAILED = "ledger_write_failed"
FAILURE_RECORDER_INTERNAL = "recorder_internal_failure"

FAILURE_CLASSES = (
    FAILURE_AGENT_UNRESOLVABLE,
    FAILURE_DEV_SESSION_ID_MISSING,
    FAILURE_RECORD_PATH_UNUSABLE,
    FAILURE_DIFF_SHA256_FAILED,
    FAILURE_LEDGER_WRITE_FAILED,
    FAILURE_RECORDER_INTERNAL,
)

# Bounded by construction: a hook that fires on every edit in the harness
# must never grow an unbounded log. The LAST slot is reserved for the
# overflow marker below, so the bound can never hide its own effect.
MAX_FAILURE_DESCRIPTORS = 8
# Not a seventh failure class -- a CHANNEL marker saying how many failures the
# cap suppressed. A bound that drops silently would report that something was
# lost without reporting how much, which is the same silent-loss shape, in
# miniature, that this change exists to remove.
FAILURE_DESCRIPTORS_SUPPRESSED = "failure_descriptors_suppressed"


def _now_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _failure(descriptors: list, failure_class: str, reason: str, path: str | None = None) -> None:
    """Append one bounded descriptor, and COUNT anything the bound suppresses.

    The cap is real (this runs on every edit in the harness), but it never
    drops silently: once the reserved last slot is reached, further failures
    increment a suppressed-count marker instead of vanishing, so an operator
    always learns both that something was lost and how much.
    """
    limit = MAX_FAILURE_DESCRIPTORS - 1
    if len(descriptors) < limit:
        descriptors.append({"class": failure_class, "reason": reason, "path": path})
        return
    if len(descriptors) == limit:
        descriptors.append({
            "class": FAILURE_DESCRIPTORS_SUPPRESSED,
            "reason": f"1 further recorder failure was not shown (channel cap "
                      f"{MAX_FAILURE_DESCRIPTORS}); the ledger directory holds the rest",
            "path": None,
            "suppressed": 1,
        })
        return
    overflow = descriptors[-1]
    overflow["suppressed"] += 1
    overflow["reason"] = (
        f"{overflow['suppressed']} further recorder failures were not shown (channel cap "
        f"{MAX_FAILURE_DESCRIPTORS}); the ledger directory holds the rest"
    )


def _diff_sha256(rel_path: str, project_dir: Path) -> str | None:
    """sha256 of `git diff --no-ext-diff --no-textconv HEAD -- <rel_path>`, or None on any failure.

    This is the REFERENCE producer for the files_landed_whole diff_sha256
    format (agents/changelog-analyst.md's staging clause verifies with the
    identical flags, against `--cached`, after staging). The two `--no-*`
    flags change nothing for ordinary paths; they pin down paths carrying a
    textconv/ext-diff attribute, whose rendered diffs could alias two
    different byte-states to one digest.
    """
    try:
        proc = subprocess.run(
            ["git", "diff", "--no-ext-diff", "--no-textconv", "HEAD", "--", rel_path],
            cwd=str(project_dir),
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return hashlib.sha256(proc.stdout).hexdigest()


def _write_entry(ledger_path: Path, name: str, entry: dict) -> bool:
    """Atomically write one entry; True on success, False on any OS failure.

    The status is RETURNED rather than swallowed. Before M7 an unwritable
    ledger directory was indistinguishable from a hook that had nothing to
    do, so the one failure an operator most needs to see was the one that
    looked most like success.

    The record is content-addressed by the (path, task, agent) triple
    (ledger_contract.record_name), not by the path alone. Two distinct
    claimant TASKS regenerating the same path therefore keep two records --
    the identity the old path-only key destroyed -- while the SAME (task,
    agent) re-regenerating that path still overwrites its own entry cleanly,
    so the record count stays bounded by distinct triples and a torn write to
    one record can never corrupt another.
    """
    try:
        ledger_path.mkdir(parents=True, exist_ok=True)
        descriptor, tmp_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=ledger_path)
    except OSError:
        return False
    target = ledger_path / name
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(entry, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp_path, target)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        return False
    return True


def record_landed_files(results: list, payload: dict, project_dir: Path) -> list:
    """Write a ledger entry for every real (WRITTEN) regeneration in `results`.

    `results` is the list process_parent_dirs() populates (README/INDEX
    RegenRecords for the edited file's parent, and its matching global
    directory). `payload` is the PostToolUse stdin JSON; only `agent_id` is
    read from it here.

    Returns a BOUNDED list of structured failure descriptors, possibly empty.
    NEVER raises into its caller: that caller runs inside the PostToolUse
    chain for every Write/Edit/NotebookEdit in the harness, so an exception
    escaping here would break every agent's ability to edit files -- including
    the agent used to fix it.

    The FOUR legitimate no-ops return an empty list: no `results`; no
    `agent_id`; an agent that POSITIVELY RESOLVES to a non-`dev` role; no
    record with status WRITTEN. The third is deliberately NOT collapsed with
    "a non-empty agent_id that resolves to nothing": the first is the ordinary
    harness-wide case, the second means the registry could not answer a
    question it should have been able to answer.

    Fail-open: any resolution, computation, or write failure still writes no
    ledger entry for that record, and never writes one at all for a
    non-`dev`-role agent or one with no `dev_session_id` (doc_sync fires on
    every PostToolUse Write/Edit/NotebookEdit across the whole harness, not
    just dev cycles).

    hooks/lib/agent_resolver.py is imported lazily, inside this function's
    own try block, rather than at module scope: it is a sibling of doc_sync/'s
    own parent directory (hooks/), not of doc_sync/ itself, so some
    deployment/test shapes copy the doc_sync/ package tree without its
    hooks/lib/ sibling (e.g. hooks/tests/test_doc_sync_index_notices.py's
    own synthetic-HOME fixture) -- a module-level import there would raise
    ModuleNotFoundError at doc_sync.main import time and crash the entire
    PostToolUse hook chain, which is exactly the failure mode this ledger
    must never cause.
    """
    failures: list = []
    try:
        if not results:
            return failures
        agent_id = payload.get("agent_id") if isinstance(payload, dict) else None
        if not agent_id or not isinstance(agent_id, str):
            return failures
        written = [r for r in results if getattr(r, "status", None) is RegenStatus.WRITTEN]
        if not written:
            # LEGITIMATE class 4, evaluated BEFORE the agent is resolved rather
            # than after. Nothing was regenerated, so there was never a ledger
            # entry to write and no resolution failure can have cost anything.
            # Order matters here and is deliberate: an agent that is not in
            # agent-index.json is the ORDINARY case across the harness (an
            # agent is indexed only when it reads a dev-registry sentinel as
            # its FIRST ACTION, which is a /dev-family convention -- see
            # hooks/subagentstop-e2e-enforce.py's own fail-open rationale), so
            # resolving first would report a failure on every skipped
            # regeneration by every non-/dev subagent in the harness. That is
            # the false-positive surface M7 exists to keep clear, and it would
            # bury the six real failures under noise.
            return failures
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from lib.agent_resolver import resolve_dev_registry_entry
        entry_meta = resolve_dev_registry_entry(agent_id, str(project_dir))
        if entry_meta is None:
            _failure(
                failures, FAILURE_AGENT_UNRESOLVABLE,
                f"agent_id {agent_id!r} resolved to no dev-registry entry at all, so a "
                "regeneration it authored cannot be attributed to any task",
            )
            return failures
        if entry_meta.get("agent_type") != "dev":
            # LEGITIMATE, and by far the most common outcome: doc_sync fires
            # for every agent in the harness and only a dev cycle has a ledger
            # to write into. Silent on purpose.
            return failures
        dev_session_id = entry_meta.get(RECORD_TASK_FIELD)
        if not dev_session_id or not isinstance(dev_session_id, str):
            _failure(
                failures, FAILURE_DEV_SESSION_ID_MISSING,
                f"agent_id {agent_id!r} resolved to a dev agent carrying no "
                f"{RECORD_TASK_FIELD}, so there is no producer directory to write into",
            )
            return failures
        ledger_path = ledger_dir(project_dir, dev_session_id)
        ts = _now_iso_z()
        for record in written:
            path = getattr(record, "path", None)
            if path is None:
                _failure(
                    failures, FAILURE_RECORD_PATH_UNUSABLE,
                    "a WRITTEN regeneration record carries no path, so the file it "
                    "rewrote cannot be declared",
                )
                continue
            try:
                rel_path = Path(path).relative_to(project_dir).as_posix()
            except ValueError:
                _failure(
                    failures, FAILURE_RECORD_PATH_UNUSABLE,
                    "a WRITTEN regeneration lies outside the project directory, so it has "
                    "no relative path to declare", str(path),
                )
                continue
            diff_sha256 = _diff_sha256(rel_path, Path(project_dir))
            if diff_sha256 is None:
                _failure(
                    failures, FAILURE_DIFF_SHA256_FAILED,
                    "git diff could not be computed, so this regeneration has no "
                    "verifiable digest and was not declared", rel_path,
                )
                continue
            entry = {
                "path": rel_path,
                "diff_sha256": diff_sha256,
                "reason": HONEST_REASON,
                RECORD_AGENT_FIELD: agent_id,
                RECORD_TASK_FIELD: dev_session_id,
                RECORD_FORMAT_VERSION_FIELD: RECORD_FORMAT_VERSION,
                "ts": ts,
            }
            if not _write_entry(ledger_path, record_name(rel_path, dev_session_id, agent_id), entry):
                _failure(
                    failures, FAILURE_LEDGER_WRITE_FAILED,
                    f"the ledger entry could not be written under {ledger_path}", rel_path,
                )
    except Exception as error:  # noqa: BLE001 -- failing open is the contract
        _failure(
            failures, FAILURE_RECORDER_INTERNAL,
            f"the recorder caught {type(error).__name__} and stopped early",
        )
    return failures
