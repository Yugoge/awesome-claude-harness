"""Frozen reference copy of ``build_plan`` from scripts/resolve-commit-repos.py.

This is NOT production code. It is ``build_plan`` exactly as it stood at commit
cc22f78, before it was split into helpers, kept only so
tests/differential/test_build_plan_differential.py can run the old and the new
version on the same inputs and assert identical results. The function body below
is a verbatim copy, except one comment: its citation of the since-deleted ledger
schema now names agents/dev.md's owned-edits ledger rule. Do not edit it.

``bind(module)`` returns this function with the live module's globals, so both
versions read the same helpers (and the same monkeypatches) and raise the same
``PlanError`` class.
"""

from __future__ import annotations

import types
from typing import Any


def build_plan(
    *,
    task_id: str,
    control_root_arg: str,
    supported_repo_args: list[str],
    report_arg: str | None = None,
    verify_ownership: bool = True,
    excluded_unsupported_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve a task's owned paths into an admitted repository plan.

    ``verify_ownership`` (default True) gates a cross-check, for
    ``section_name == "dev"`` reports only: every canonical identity declared
    via ``files_modified`` is first matched against three SELF-REPORTED
    exemption sources (unchanged, still computed, no longer the blocking
    authority -- see below): a canonicalized key of the report's
    ``owned_edits`` ledger, OR a canonicalized path parsed from the report's
    ``baseline_dirty_snapshot`` (a pre-existing dirty tracked file from
    another session, exempt per agents/dev.md:521/533), OR a canonicalized
    path declared in the report's ``files_landed_whole`` (this repo's
    whole-file no-authorship declaration channel,
    agents/changelog-analyst.md:783-843, backlog #121) that is itself absent
    from BOTH ``owned_edits`` AND ``pre_edit_snapshots``. Whenever
    ``files_landed_whole`` is declared, each of those two subtraction
    sources must be absent or a JSON object; any other present shape raises
    instead of silently shrinking the subtraction (codex
    bulk-commit-qa-20260926 finding #3). All are read from the
    TOP-LEVEL report payload (``payload["owned_edits"]`` /
    ``payload["baseline_dirty_snapshot"]`` / ``payload["files_landed_whole"]``
    / ``payload["pre_edit_snapshots"]``), never from ``section[...]``,
    which is never populated (see agents/dev.md, agents/changelog-analyst.md).
    ``files_created``-only paths are exempt; a path dual-listed in both
    ``files_modified`` and ``files_created`` is not.

    Identities the self-report does NOT exempt are no longer blocked on that
    basis alone (attribution-journal consumer cutover):
    ``_ledger_entangled()`` asks the write-time hash-chain
    journal (``scripts/lib/attribution_adjudicator.py``) and this raises
    ONLY for an identity the journal itself measures as structurally
    ENTANGLED. No journal evidence, or evidence that does not reach back to
    the current HEAD blob, is deferred to the commit analyst's own judgment,
    never raised here. Pass ``verify_ownership=False`` only for read-only
    historical-status reuse (scripts/dev-lifecycle.py's commit_detection())
    that predates the ledger and must not misreport already-landed tasks as
    blocked.

    ``excluded_unsupported_paths`` is an exact, per-path declared exclusion
    list -- never a policy switch, prefix, or glob -- for the case where a
    cycle's owned set legitimately spans a repository this invocation does not
    support (e.g. another account's home or the filesystem root), and the
    operator commits that foreign portion by hand. Repository admission is
    NOT widened: an exclusion takes effect
    only for a path that is BOTH unsupported-owner AND named here, and such a
    path is dropped from every repository entry's ``owned_paths`` and recorded
    in the emitted plan's ``unsupported_owner_exclusions`` array so the plan
    (and the commit message built from it) discloses the scope difference. A
    declared path whose owner IS supported, or that is absent from the
    report's owned set, raises instead of being honored -- a stale declaration
    must never silently drop committable work. An unsupported-owner path that
    is NOT declared still raises exactly as before. When nothing is excluded
    the key is omitted, so the emitted plan stays byte-identical to the
    pre-existing shape.
    """
    if not task_id.strip():
        raise PlanError("task id must be non-empty")
    control_root = _repo_root(Path(control_root_arg).expanduser().resolve())
    report_path = _resolve_report(control_root, task_id, report_arg)
    if not _contains(control_root, report_path):
        raise PlanError(f"report must resolve under the control repository: {report_path}")
    payload, section_name = _load_report(report_path, task_id, control_root)
    section = payload[section_name]

    supported: list[Path] = []
    for raw in [str(control_root), *supported_repo_args]:
        repo = _repo_root(Path(raw).expanduser().resolve())
        if repo not in supported:
            supported.append(repo)

    owned_raw: list[str] = []
    raw_fields: dict[str, set[str]] = {}
    for field in ("files_modified", "files_created"):
        values = section.get(field, [])
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise PlanError(f"{section_name}.{field} must be an array of strings")
        owned_raw.extend(values)
        for raw in values:
            raw_fields.setdefault(raw, set()).add(field)

    # Explicit per-path declared exclusions (--exclude-unsupported-owned-path).
    # Matched by canonical absolute path so a declaration shares this module's
    # single canonicalization convention. A declaration that cannot be
    # canonicalized at all (nonexistent ancestor, a glob, a typo) matches
    # nothing and therefore falls to the "not in the owned set" raise below --
    # never a silent drop, and never a prefix/glob admission.
    declared_exclusions: list[str] = list(excluded_unsupported_paths or [])
    exclusion_by_canonical: dict[Path, str] = {}
    for declared in declared_exclusions:
        try:
            canonical = _canonical_owned_path(declared, control_root)
        except PlanError:
            continue
        exclusion_by_canonical.setdefault(canonical, declared)
    matched_declarations: set[str] = set()
    unsupported_owner_exclusions: list[dict[str, str]] = []
    excluded_canonical: set[Path] = set()

    by_repo: dict[Path, list[str]] = {control_root: []}
    identity_fields: dict[tuple[Path, str], set[str]] = {}
    identity_display: dict[tuple[Path, str], str] = {}
    for raw in owned_raw:
        absolute = _canonical_owned_path(raw, control_root)
        actual_owner = _repo_root(_existing_ancestor(absolute))
        declared = exclusion_by_canonical.get(absolute)
        if actual_owner not in supported:
            if declared is None:
                raise PlanError(f"owned path is outside the supported repository set: {raw}")
            matched_declarations.add(declared)
            if absolute not in excluded_canonical:
                excluded_canonical.add(absolute)
                unsupported_owner_exclusions.append(
                    {
                        "path": raw,
                        "declared_as": declared,
                        "owner_repo_root": str(actual_owner),
                        "reason": (
                            "owner repository is outside the supported repository "
                            "set and this path was explicitly declared via "
                            "--exclude-unsupported-owned-path; it is committed "
                            "manually outside this plan"
                        ),
                    }
                )
            continue
        if declared is not None:
            raise PlanError(
                "declared unsupported-owner exclusion names an owned path whose "
                f"owner repository {actual_owner} IS supported: {raw}"
            )
        # Git, not pathname containment alone, determines ownership. This rejects
        # an unadmitted nested checkout instead of laundering it through an
        # admitted outer repository.
        owner = actual_owner
        relative = absolute.relative_to(owner).as_posix()
        if relative == "." or relative.startswith("../"):
            raise PlanError(f"owned path cannot name a repository root: {raw}")
        by_repo.setdefault(owner, [])
        if relative not in by_repo[owner]:
            by_repo[owner].append(relative)
        identity = (owner, relative)
        identity_fields.setdefault(identity, set()).update(raw_fields.get(raw, set()))
        identity_display.setdefault(identity, raw)

    unmatched_declarations = sorted(
        declared for declared in declared_exclusions if declared not in matched_declarations
    )
    if unmatched_declarations:
        raise PlanError(
            "declared unsupported-owner exclusion is not in the report's owned "
            f"path set: {', '.join(unmatched_declarations)}"
        )

    # Ownership gate (backlog #110, extended -- task 20260923-024043,
    # backlog #121): files_modified is never blindly trusted -- it must be
    # backed by this cycle's own owned_edits ledger, OR by
    # baseline_dirty_snapshot (a pre-existing dirty tracked file from
    # another session in a shared worktree, per agents/dev.md:521/533), OR
    # by files_landed_whole (this repo's own whole-file no-authorship
    # declaration channel, agents/changelog-analyst.md:783-843, subject to
    # its own dual-listing constraint below), or the plan would silently
    # admit a foreign seat's uncommitted work. files_created-only identities
    # are exempt (a brand-new file's ledger entry is legitimately absent, or
    # carries an empty `old` -- agents/dev.md's owned-edits ledger rule); a
    # dual-listed identity is not. Missing/empty owned_edits AND
    # missing/empty baseline_dirty_snapshot both fall out of the same
    # set-difference with no special branch: an absent/empty input
    # canonicalizes to an empty identity-set, so a files_modified path
    # backed by neither always yields a reject (agents/dev.md requires the
    # ledger be non-empty whenever edits were made, and requires
    # baseline_dirty_snapshot itself be a mandatory top-level field).
    if verify_ownership and section_name == "dev":
        ledger_identities = _canonicalized_ledger_identities(payload.get("owned_edits"), control_root)
        baseline_identities = _canonicalized_baseline_dirty_identities(
            payload.get("baseline_dirty_snapshot"), control_root
        )
        # files_landed_whole's own dual-listing constraint
        # (agents/changelog-analyst.md:834-837): a path is exempt via this
        # channel ONLY when it is absent from BOTH owned_edits AND
        # pre_edit_snapshots -- never baseline_dirty_snapshot, which is a
        # different field entirely (backlog #121's flagged "universal
        # skeleton key" risk: subtracting baseline_identities here instead
        # would wrongly exempt a path already claimed elsewhere).
        #
        # The two subtraction sources are validated STRICTLY first (codex
        # bulk-commit-qa-20260926 finding #3): _canonicalized_ledger_
        # identities()'s drop-malformed behavior is fail-closed only in
        # POSITIVE-proof position, where dropping a key shrinks an
        # EXEMPTION set; reused in this NEGATIVE/subtraction position the
        # same drop shrinks the EXCLUSION set and silently disables the
        # dual-listing constraint -- a malformed pre_edit_snapshots would
        # turn files_landed_whole into exactly the universal skeleton key
        # described above. Absent keys and {} are the only
        # legitimate-absence shapes (both real fixtures declare {}); any
        # other present value -- null, list, string -- refuses the whole
        # channel by raising. Scoped to reports that actually declare
        # files_landed_whole, so a report that never uses the channel
        # keeps its exact pre-existing behavior, malformed fields included.
        landed_whole_identities: set[tuple[Path, str]] = set()
        declared_landed_whole = payload.get("files_landed_whole")
        if declared_landed_whole:
            for claim_field in ("owned_edits", "pre_edit_snapshots"):
                if claim_field in payload and not isinstance(payload[claim_field], dict):
                    raise PlanError(
                        "files_landed_whole is declared but "
                        f"{claim_field} is present and not a JSON object "
                        f"({type(payload[claim_field]).__name__}); the "
                        "dual-listing constraint cannot be proven against "
                        "a malformed claim field, so every "
                        "files_landed_whole exemption is refused "
                        "(fail-closed)",
                        code=_BASELINE_DIRTY_UPSTREAM_DEFECT,
                    )
            strict_ledger_identities = _canonicalized_ledger_identities_or_raise(
                payload.get("owned_edits") or {}, control_root, field_name="owned_edits"
            )
            strict_pre_edit_snapshot_identities = _canonicalized_ledger_identities_or_raise(
                payload.get("pre_edit_snapshots") or {}, control_root, field_name="pre_edit_snapshots"
            )
            landed_whole_identities = _canonicalized_landed_whole_identities(
                declared_landed_whole, control_root
            ) - (strict_ledger_identities | strict_pre_edit_snapshot_identities)
        unbacked_by_self_report = [
            identity
            for identity, fields in identity_fields.items()
            if "files_modified" in fields
            and identity not in ledger_identities
            and identity not in baseline_identities
            and identity not in landed_whole_identities
        ]
        missing = sorted(
            identity_display[identity]
            for identity in _ledger_entangled(unbacked_by_self_report)
        )
        if missing:
            code, reason = _classify_baseline_dirty_snapshot(payload.get("baseline_dirty_snapshot"))
            if code == _BASELINE_DIRTY_UPSTREAM_DEFECT:
                if reason == "absent":
                    detail = (
                        "baseline_dirty_snapshot was not provided by the dispatch "
                        "payload (missing or not a string) -- see agents/dev.md:535's "
                        "orchestrator capture obligation (backlog #119)"
                    )
                else:
                    detail = (
                        "baseline_dirty_snapshot was provided but is not porcelain "
                        "text (git status --porcelain produced zero parseable path "
                        "lines), so it could not be used to compute an exemption "
                        "(backlog #119)"
                    )
                raise PlanError(
                    "files_modified declares path(s) that could not be verified "
                    f"because {detail}: {', '.join(missing)}",
                    code=code,
                )
            raise PlanError(
                "files_modified declares path(s) with no matching owned_edits "
                "ledger entry and absent from baseline_dirty_snapshot (foreign "
                f"or unaccounted-for edit): {', '.join(missing)}",
                code=code,
            )

    targets: list[dict[str, Any]] = []
    ordered_roots = [control_root] + sorted(
        (root for root in by_repo if root != control_root), key=lambda item: str(item)
    )
    for order, root in enumerate(ordered_roots):
        branch = _git_capture(root, "branch", "--show-current")
        head = _git_capture(root, "rev-parse", "HEAD")
        if not branch or not head:
            raise PlanError(f"repository must have an attached branch and HEAD: {root}")
        targets.append(
            {
                "order": order,
                "repo_root": str(root),
                "branch": branch,
                "expected_head": head,
                "owned_paths": sorted(by_repo.get(root, [])),
                "cycle_artifact_repo": root == control_root,
            }
        )

    report_bytes = report_path.read_bytes()
    plan: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "report_path": str(report_path),
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "control_root": str(control_root),
        "repository_count": len(targets),
        "repositories": targets,
        "transaction_semantics": "ordered_non_atomic_with_partial_failure_reporting",
    }
    # Emitted only when non-empty, so an invocation that declares no exclusion
    # keeps the pre-existing plan shape byte-for-byte.
    if unsupported_owner_exclusions:
        plan["unsupported_owner_exclusions"] = sorted(
            unsupported_owner_exclusions,
            key=lambda item: (item["owner_repo_root"], item["path"]),
        )
    return plan


def bind(module: types.ModuleType):
    """``build_plan`` as frozen at cc22f78, resolving its names in ``module``."""
    frozen = types.FunctionType(build_plan.__code__, vars(module), "build_plan_legacy")
    frozen.__kwdefaults__ = dict(build_plan.__kwdefaults__ or {})
    return frozen
