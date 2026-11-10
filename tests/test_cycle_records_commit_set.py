#!/usr/bin/env python3
"""The cycle files /commit ships with a cycle, so a product repo is clean after /commit and /push
(P10 R8 rules 2 and 3, A25; #27 comment 6737075938 item 3).

Before this change, after /commit these stayed untracked in the product repo, neither staged,
excluded nor deleted: docs/dev/ba-qa-report-<t>.json, test-writer-report-<t>.json,
user-requirement-dev-<t>.md, tests/generated/<t>/manifest.json and commit-qa-report-<t>.md. Each has a
reader after its producer, so none is deleted, and a docs/dev artifact /commit stages is never
excluded: each is committed with the cycle.
  * The chain resolver's commit_whitelist_artifacts (the analyst's Phase 2 item 4) adds the
    cycle's records found on disk, for the parent and each lane; artifact_paths (the completion
    index) is unchanged, and an absent record is no gap.
  * The commit QA's report is written after the planning dry run, so it is outside the chain:
    commands/commit.md Step 6 admits it into QA_APPROVED_FILES and the analyst's item 5 and do path
    name it.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.test_resolve_dev_artifact_chain import (
    RESOLVER, TASK_ID, WORKERS, _make_fanout, _make_singular, _relative, _write)

REPO = Path(__file__).resolve().parent.parent
STAMP = TASK_ID.removeprefix("dev-")


def _records(root: Path, units: list[str], parent: str) -> list[str]:
    dev = root / "docs" / "dev"
    paths = [dev / f"user-requirement-{parent}.md"]
    for unit in units:
        paths += [dev / f"ba-qa-report-{unit}.json", dev / f"test-writer-report-{unit}.json",
                  root / "tests" / "generated" / unit / "manifest.json"]
    for p in paths:
        _write(p, {"task_id": p.name} if p.suffix == ".json" else "# requirement\n")
    return [_relative(root, p) for p in paths]


def test_singular_whitelist_names_the_cycle_records_on_disk(tmp_path: Path) -> None:
    _make_singular(tmp_path)
    before = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    records = _records(tmp_path, [TASK_ID], TASK_ID)
    after = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert before["status"] == after["status"] == "pass"
    assert before["commit_whitelist_artifacts"] == before["artifact_paths"]
    assert after["artifact_paths"] == before["artifact_paths"]
    assert after["commit_whitelist_artifacts"] == before["artifact_paths"] + records


def test_requirement_named_by_the_registry_name_of_a_bare_task_id(tmp_path: Path) -> None:
    """/dev's hook writes user-requirement-dev-<ts>.md (dev-command-<ts> for /dev-command) while the
    artifacts are named with the bare <ts> (obligation.canonical_task_id)."""
    import tests.test_resolve_dev_artifact_chain as base
    saved = base.TASK_ID
    try:
        base.TASK_ID = STAMP
        _make_singular(tmp_path)
    finally:
        base.TASK_ID = saved
    req = tmp_path / "docs" / "dev" / f"user-requirement-dev-command-{STAMP}.md"
    _write(req, "# requirement\n")
    result = RESOLVER.resolve_chain(tmp_path, STAMP)
    assert result["status"] == "pass"
    assert _relative(tmp_path, req) in result["commit_whitelist_artifacts"]
    assert _relative(tmp_path, req) not in result["artifact_paths"]


def test_fanout_whitelist_names_each_lane_records(tmp_path: Path) -> None:
    _make_fanout(tmp_path)
    before = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    lanes = [f"{TASK_ID}-{w}" for w in WORKERS]
    records = _records(tmp_path, [TASK_ID, *lanes], TASK_ID)
    after = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert after["status"] == "pass" and after["mode"] == "fanout"
    assert after["artifact_paths"] == before["artifact_paths"]
    assert after["commit_whitelist_artifacts"] == before["artifact_paths"] + records


def test_an_absent_record_is_neither_listed_nor_a_gap(tmp_path: Path) -> None:
    _make_singular(tmp_path)
    req = tmp_path / "docs" / "dev" / f"user-requirement-{TASK_ID}.md"
    _write(req, "# requirement\n")
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "pass" and not result["errors"]
    extra = result["commit_whitelist_artifacts"][len(result["artifact_paths"]):]
    assert extra == [_relative(tmp_path, req)]


def test_the_disposition_chain_line_carries_the_records(tmp_path: Path) -> None:
    """/commit Step 3's CHAIN= line is the analyst's ARTIFACT_CHAIN: the records reach it."""
    _make_singular(tmp_path)
    records = _records(tmp_path, [TASK_ID], TASK_ID)
    chain = RESOLVER.disposition(tmp_path, TASK_ID, "dev")["chain"]
    assert set(records) <= set(chain["commit_whitelist_artifacts"])


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_commit_qa_report_is_in_the_ceiling_and_the_commit_set() -> None:
    commit = _flat((REPO / "commands" / "commit.md").read_text(encoding="utf-8"))
    approve = commit[commit.index("- `COMMIT: APPROVE`:"):commit.index("### Step 7")]
    assert ("Record `QA_APPROVED_FILES` = `PLAN_FILES` (the exact reviewed set, per repo), plus, when "
            "`BULK=false`, this round's `docs/dev/commit-qa-report-<TASK_ID>.md`") in approve
    rule1 = commit[commit.index("1. Transient / non-authored byproducts"):commit.index("2. Secrets / sensitive content")]
    assert "its `tests/generated/<task>/manifest.json`) are deliverables of the cycle, not byproducts" in rule1
    analyst = _flat((REPO / "agents" / "changelog-analyst.md").read_text(encoding="utf-8"))
    phase2 = analyst[analyst.index("### Phase 2: File classification"):analyst.index("### Phase 3:")]
    item4 = phase2[phase2.index("4. Every exact path in"):phase2.index("5. Post-chain artifacts")]
    for record in ("user-requirement document", "BA-QA report", "test-writer report",
                   "`tests/generated/<id>/manifest.json`"):
        assert record in item4, record
    item5 = phase2[phase2.index("5. Post-chain artifacts"):phase2.index("**Sourcing the item-3")]
    assert "`commit-qa-report-<TASK_ID>.md`" in item5
    do_path = phase2[phase2.index("**BULK=false and no dev-report:**"):phase2.index("**Tree self-containment")]
    assert "`commit-qa-report-`" in do_path
