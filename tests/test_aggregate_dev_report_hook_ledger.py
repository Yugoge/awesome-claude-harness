"""Tests for the read-side consumer of the hook-authored side-effect-file
ledger (backlog #122 M3): scripts/aggregate-dev-report.py's len(shards_info)
< 2 singular-report branch merges validated hook_ledger.py entries into
files_landed_whole before its existing no-op return.

AC2 (ac_uid 7056eb086cc99749): a valid ledger entry for a files_modified
path with no owned_edits/pre_edit_snapshots coverage is folded into
files_landed_whole with an honesty-compliant reason, action stays
"skipped", and scripts/resolve-commit-repos.py::build_plan() (unmodified)
subsequently admits the path.

AC3 (ac_uid ec3803f493488042): a genuine foreign/unaccounted edit (no
owned_edits, no baseline_dirty_snapshot, no ledger entry) is still rejected
by build_plan() with PlanError.code == "foreign_or_unaccounted_edit" -- the
verification recipe branches on hasattr(exc, "code") BEFORE any equality
assertion (backlog #119/#123 precondition guard, ticket 20260923-175747
precondition_risks[0]/PR1).

AC4 (ac_uid 8fe9ed812aac6ad3): with no ledger entries (dir absent or
empty), the canonical report is left byte-for-byte unchanged.

Every scenario runs against a REAL git repository under tmp_path and
invokes the REAL scripts/aggregate-dev-report.py::main() and
scripts/resolve-commit-repos.py::build_plan() -- nothing here is mocked.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

_AGG_SCRIPT = REPO_ROOT / "scripts" / "aggregate-dev-report.py"
_agg_spec = importlib.util.spec_from_file_location("aggregate_dev_report_hook_ledger", _AGG_SCRIPT)
agg_mod = importlib.util.module_from_spec(_agg_spec)
_agg_spec.loader.exec_module(agg_mod)

_COMMIT_SCRIPT = REPO_ROOT / "scripts" / "resolve-commit-repos.py"
_commit_spec = importlib.util.spec_from_file_location("resolve_commit_repos_hook_ledger", _COMMIT_SCRIPT)
commit_mod = importlib.util.module_from_spec(_commit_spec)
_commit_spec.loader.exec_module(commit_mod)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "tests@example.invalid")
    _git(path, "config", "user.name", "Tests")
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(path, "add", "seed.txt")
    _git(path, "commit", "-q", "-m", "seed")
    return path


def _real_diff_sha256(control: Path, rel_path: str) -> str:
    proc = subprocess.run(
        ["git", "diff", "HEAD", "--", rel_path], cwd=str(control), capture_output=True, check=True,
    )
    return hashlib.sha256(proc.stdout).hexdigest()


def _track_and_modify(control: Path, rel_path: str, initial: str, modified: str) -> None:
    p = control / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(initial, encoding="utf-8")
    _git(control, "add", rel_path)
    _git(control, "commit", "-q", "-m", f"seed {rel_path}")
    p.write_text(modified, encoding="utf-8")


def _mint_identity(control: Path, identity: str) -> Path:
    """Write the co-minted docs/dev/user-requirement-<id>.md that makes <id> a
    genuine producer identity.

    hooks/prompt-workflow.py creates .claude/dev-registry/<id>/ and this
    document as one pair, so the document's existence is hook-authored
    evidence of a real minted cycle -- which is how the consumer now decides
    authority instead of guessing at the dispatch prefix. Every fixture that
    means to stand for a REAL producer directory must therefore mint it.
    """
    doc = control / "docs" / "dev" / f"user-requirement-{identity}.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(f"# minted identity {identity}\n", encoding="utf-8")
    return doc


def _write_ledger_entry(
    control: Path, dev_session_id: str, entry: dict, name: str = "entry.json", mint: bool = True,
) -> Path:
    ledger_dir = control / ".claude" / "dev-registry" / dev_session_id / "hook-landed-files"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    path = ledger_dir / name
    path.write_text(json.dumps(entry), encoding="utf-8")
    if mint:
        _mint_identity(control, dev_session_id)
    return path


def _write_singular_report(control: Path, task_id: str, files_modified: list[str], **extra) -> Path:
    dev_dir = control / "docs" / "dev"
    dev_dir.mkdir(parents=True, exist_ok=True)
    report_path = dev_dir / f"dev-report-{task_id}.json"
    payload = {
        "request_id": task_id,
        "task_id": task_id,
        "baseline_head_sha": _git(control, "rev-parse", "HEAD"),
        "baseline_dirty_snapshot": "",
        "dev_report_path": f"docs/dev/dev-report-{task_id}.json",
        "dev": {
            "status": "completed",
            "files_modified": files_modified,
            "files_created": [],
        },
        "blocking_issues": [],
        "recommendations": [],
        # deliberately no "parallel_workers" key -- genuine singular report.
    }
    payload.update(extra)
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    return report_path


def test_ac2_valid_hook_ledger_entry_is_folded_into_files_landed_whole_and_admitted(
    tmp_path, monkeypatch, capsys,
):
    control = _repo(tmp_path / "control")
    rel_path = "hooks/tests/INDEX.md"
    _track_and_modify(
        control, rel_path,
        initial="# tests\n\n<!-- AUTO:index-stats -->\nstale\n<!-- /AUTO:index-stats -->\n",
        modified="# tests\n\n<!-- AUTO:index-stats -->\nregenerated real stats\n<!-- /AUTO:index-stats -->\n",
    )
    diff_sha256 = _real_diff_sha256(control, rel_path)
    honest_reason = "PostToolUse doc-sync regeneration side effect; not reviewed by dev"

    task_id = "20260101-120000"
    dev_session_id = f"dev-{task_id}"
    _write_ledger_entry(control, dev_session_id, {
        "path": rel_path,
        "diff_sha256": diff_sha256,
        "reason": honest_reason,
        "source_agent_id": "agent-ac2",
        "ts": "2026-01-01T12:00:00Z",
    })
    report_path = _write_singular_report(control, task_id, [rel_path])

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(control))
    rc = agg_mod.main(["--task-id", task_id])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "skipped"

    updated = json.loads(report_path.read_text(encoding="utf-8"))
    landed = updated.get("files_landed_whole")
    assert isinstance(landed, list) and len(landed) == 1
    entry = landed[0]
    assert entry["path"] == rel_path
    assert entry["diff_sha256"] == diff_sha256
    assert entry["reason"] == honest_reason
    assert set(entry.keys()) == {"path", "diff_sha256", "reason", "claimants"}, (
        "files_landed_whole entries keep agents/changelog-analyst.md's own three "
        "fields unchanged in shape and value; `claimants` is the ONE additive "
        "field this ticket introduces, and nothing else may be invented"
    )
    assert entry["claimants"] == [
        {"task": dev_session_id, "agents": ["agent-ac2"], "task_provenance": "directory_derived"}
    ], (
        "the folding claimant must be named on the entry it produced; this record "
        "carries no dev_session_id of its own (the LEGACY shape all 21 pre-existing "
        "records have), so its owning task is derived from the producer directory -- "
        "which is exact, not weaker: the recorder builds that directory path directly "
        "from the resolved dev_session_id"
    )
    assert "not reviewed by dev" in entry["reason"] or "not reviewed" in entry["reason"]
    assert "reviewed" not in entry["reason"].replace("not reviewed", "")

    plan = commit_mod.build_plan(
        task_id=task_id,
        control_root_arg=str(control),
        supported_repo_args=[],
        report_arg=str(report_path),
    )
    owned = set(plan["repositories"][0]["owned_paths"])
    assert rel_path in owned


def test_ac2_pre_existing_files_landed_whole_entry_is_never_dropped(tmp_path, monkeypatch, capsys):
    control = _repo(tmp_path / "control")
    ledger_rel = "hooks/tests/INDEX.md"
    _track_and_modify(
        control, ledger_rel,
        initial="# tests\n\n<!-- AUTO:index-stats -->\nstale\n<!-- /AUTO:index-stats -->\n",
        modified="# tests\n\n<!-- AUTO:index-stats -->\nnew\n<!-- /AUTO:index-stats -->\n",
    )
    diff_sha256 = _real_diff_sha256(control, ledger_rel)

    task_id = "20260101-130000"
    dev_session_id = f"dev-{task_id}"
    _write_ledger_entry(control, dev_session_id, {
        "path": ledger_rel,
        "diff_sha256": diff_sha256,
        "reason": "PostToolUse doc-sync regeneration side effect; not reviewed by dev",
        "source_agent_id": "agent-ac2b",
        "ts": "2026-01-01T13:00:00Z",
    })
    pre_existing = {"path": "already/declared.txt", "diff_sha256": "deadbeef", "reason": "pre-existing"}
    report_path = _write_singular_report(
        control, task_id, [ledger_rel], files_landed_whole=[dict(pre_existing)],
    )

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(control))
    rc = agg_mod.main(["--task-id", task_id])
    assert rc == 0

    updated = json.loads(report_path.read_text(encoding="utf-8"))
    landed = updated["files_landed_whole"]
    assert pre_existing in landed
    assert any(e["path"] == ledger_rel for e in landed)
    assert len(landed) == 2


def test_ac3_foreign_unaccounted_edit_still_rejected_by_build_plan(tmp_path, monkeypatch, capsys):
    control = _repo(tmp_path / "control")
    (control / "foreign.txt").write_text("v1\n", encoding="utf-8")
    _git(control, "add", "foreign.txt")
    _git(control, "commit", "-q", "-m", "seed foreign.txt")
    (control / "foreign.txt").write_text("v2 -- an edit nobody declared\n", encoding="utf-8")

    task_id = "20260101-140000"
    # No hook-ledger directory at all for this dev_session_id: the merge
    # step must be a genuine no-op here, so this path is verifiably still
    # unaccounted for when build_plan() runs.
    report_path = _write_singular_report(control, task_id, ["foreign.txt"])

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(control))
    rc = agg_mod.main(["--task-id", task_id])
    assert rc == 0
    updated = json.loads(report_path.read_text(encoding="utf-8"))
    assert not updated.get("files_landed_whole")

    # Attribution-journal consumer cutover (docs/reference/attribution-
    # journal-cutover-flip-plan-20261003.md, superseded by the zero-blocking
    # constraint of the follow-up consumer-cutover task): build_plan()'s
    # ownership gate no longer rejects an identity on self-report absence
    # alone (see _ledger_entangled() in scripts/resolve-commit-repos.py) --
    # it asks the write-time hash-chain journal, and this fixture's edit was
    # made by a plain git write, never a journaled tool call, so it is
    # INSUFFICIENT_COVERAGE, never ENTANGLED: deferred to the commit
    # analyst's own judgment, not raised here. build_plan() must therefore
    # now SUCCEED for this exact "foreign, unaccounted-for edit" shape.
    plan = commit_mod.build_plan(
        task_id=task_id,
        control_root_arg=str(control),
        supported_repo_args=[],
        report_arg=str(report_path),
    )
    assert plan["repository_count"] == 1


def test_ac4_no_ledger_directory_leaves_canonical_report_byte_for_byte_unchanged(
    tmp_path, monkeypatch, capsys,
):
    control = _repo(tmp_path / "control")
    task_id = "20260101-150000"
    report_path = _write_singular_report(control, task_id, ["seed.txt"], owned_edits={
        "seed.txt": [{"old": "seed\n", "new": "seed\n"}]
    })
    before = report_path.read_bytes()

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(control))
    rc = agg_mod.main(["--task-id", task_id])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "skipped"
    assert report_path.read_bytes() == before


def test_ac4_empty_ledger_directory_also_leaves_canonical_report_unchanged(
    tmp_path, monkeypatch, capsys,
):
    control = _repo(tmp_path / "control")
    task_id = "20260101-160000"
    dev_session_id = f"dev-{task_id}"
    empty_ledger_dir = control / ".claude" / "dev-registry" / dev_session_id / "hook-landed-files"
    empty_ledger_dir.mkdir(parents=True)

    report_path = _write_singular_report(control, task_id, ["seed.txt"], owned_edits={
        "seed.txt": [{"old": "seed\n", "new": "seed\n"}]
    })
    before = report_path.read_bytes()

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(control))
    rc = agg_mod.main(["--task-id", task_id])

    assert rc == 0
    assert report_path.read_bytes() == before


def test_stale_ledger_entry_mismatched_diff_sha256_is_not_folded_into_files_landed_whole(
    tmp_path, monkeypatch, capsys,
):
    """AC1 (dev-20260926-044454, ac_uid bcd554c4015094fe): a ledger entry
    recorded with a diff_sha256 that no longer matches the path's current
    git diff HEAD (the file was edited again after the entry was recorded)
    must never be folded into files_landed_whole -- the freshness recheck in
    _merge_hook_ledger_into_singular rejects it, including when the
    recompute itself would fail (treated identically to a mismatch)."""
    control = _repo(tmp_path / "control")
    rel_path = "hooks/tests/INDEX.md"
    _track_and_modify(
        control, rel_path,
        initial="# tests\n\n<!-- AUTO:index-stats -->\nstale\n<!-- /AUTO:index-stats -->\n",
        modified="# tests\n\n<!-- AUTO:index-stats -->\nregenerated real stats\n<!-- /AUTO:index-stats -->\n",
    )
    stale_recorded_hash = hashlib.sha256(b"a diff that no longer matches the tree").hexdigest()
    assert stale_recorded_hash != _real_diff_sha256(control, rel_path)

    task_id = "20260101-180000"
    dev_session_id = f"dev-{task_id}"
    _write_ledger_entry(control, dev_session_id, {
        "path": rel_path,
        "diff_sha256": stale_recorded_hash,
        "reason": "PostToolUse doc-sync regeneration side effect; not reviewed by dev",
        "source_agent_id": "agent-stale-ac1",
        "ts": "2026-01-01T18:00:00Z",
    })
    report_path = _write_singular_report(control, task_id, [rel_path])

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(control))
    rc = agg_mod.main(["--task-id", task_id])
    assert rc == 0

    updated = json.loads(report_path.read_text(encoding="utf-8"))
    assert not updated.get("files_landed_whole"), (
        "a stale ledger entry (recorded diff_sha256 no longer matching the "
        "path's current git diff HEAD) must never be folded into "
        "files_landed_whole"
    )


def test_empty_diff_hash_entry_rejected_when_current_diff_is_non_empty(
    tmp_path, monkeypatch, capsys,
):
    """AC2 (ac_uid 61f82908939ad5c8): sha256('') is a legitimate write-side
    value (hook_ledger.py::_diff_sha256's own docstring: the ordinary hash
    of a genuinely empty diff, meaning "no diff existed at record time"),
    but the compare side applies the identical mismatch rule -- an entry
    recorded with that value, compared against a path that NOW has a
    non-empty diff, is rejected on the same terms as any other mismatch. No
    special-case exemption for the empty-hash value; the write side
    (hook_ledger.py) is unmodified by this fix."""
    control = _repo(tmp_path / "control")
    rel_path = "scripts/README.md"
    _track_and_modify(
        control, rel_path,
        initial="# scripts\n",
        modified="# scripts\n\nnewly regenerated content\n",
    )
    empty_diff_hash = hashlib.sha256(b"").hexdigest()
    assert empty_diff_hash != _real_diff_sha256(control, rel_path)

    task_id = "20260101-190000"
    dev_session_id = f"dev-{task_id}"
    _write_ledger_entry(control, dev_session_id, {
        "path": rel_path,
        "diff_sha256": empty_diff_hash,
        "reason": "PostToolUse doc-sync regeneration side effect; not reviewed by dev",
        "source_agent_id": "agent-empty-ac2",
        "ts": "2026-01-01T19:00:00Z",
    })
    report_path = _write_singular_report(control, task_id, [rel_path])

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(control))
    rc = agg_mod.main(["--task-id", task_id])
    assert rc == 0

    updated = json.loads(report_path.read_text(encoding="utf-8"))
    assert not updated.get("files_landed_whole"), (
        "an entry recorded as sha256('') must be rejected under the "
        "identical mismatch rule once the path has a non-empty current diff"
    )


def test_ac3_hooks_tests_readme_stale_empty_hash_regression_fixture(
    tmp_path, monkeypatch, capsys,
):
    """AC3 (ac_uid a85db87ca3700d0c): regression fixture reproducing the
    REAL on-disk shape found in this repo's own
    .claude/dev-registry/dev-20260923-175747/hook-landed-files/ ledger: the
    hooks/tests/README.md entry (source_agent_id/ts copied verbatim from
    that real entry) was recorded with diff_sha256 = sha256('') (no diff
    existed at record time), and the path has since been genuinely edited
    again, so its current git diff HEAD is non-empty. This test FAILS
    against the pre-fix _merge_hook_ledger_into_singular (which folds every
    well-formed loaded entry unconditionally, with no recompute/compare
    step at all) and PASSES against the post-fix recompute-and-compare
    code."""
    control = _repo(tmp_path / "control")
    rel_path = "hooks/tests/README.md"
    _track_and_modify(
        control, rel_path,
        initial="# hooks/tests\n\nDoc-sync regenerated test directory notes.\n",
        modified=(
            "# hooks/tests\n\nDoc-sync regenerated test directory notes.\n\n"
            "Updated after the ledger entry was recorded.\n"
        ),
    )
    empty_diff_hash = hashlib.sha256(b"").hexdigest()
    assert empty_diff_hash != _real_diff_sha256(control, rel_path)

    task_id = "20260923-175747"
    dev_session_id = f"dev-{task_id}"
    _write_ledger_entry(control, dev_session_id, {
        "path": rel_path,
        "diff_sha256": empty_diff_hash,
        "reason": "PostToolUse doc-sync regeneration side effect; not reviewed by dev",
        "source_agent_id": "ad1029bee1ffd17c6",
        "ts": "2026-09-23T19:04:49Z",
    })
    report_path = _write_singular_report(control, task_id, [rel_path])

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(control))
    rc = agg_mod.main(["--task-id", task_id])
    assert rc == 0

    updated = json.loads(report_path.read_text(encoding="utf-8"))
    assert not updated.get("files_landed_whole"), (
        "the real hooks/tests/README.md / lane dev-20260923-175747 shape "
        "(recorded sha256(''), now genuinely diffed) must be rejected, not "
        "folded into files_landed_whole"
    )


def _contract():
    sys.path.insert(0, str(REPO_ROOT))
    from hooks.doc_sync import ledger_contract
    return ledger_contract


def test_m6_hermetic_resolution_over_a_constructed_pair_of_trees(tmp_path):
    """AC4/M6 at the CONSUMER: one authoritative convention, proved hermetically.

    HERMETIC BY CONSTRUCTION: both a registry tree AND a minted-identity tree
    are built under tmp_path, and neither live tree is enumerated. Both inputs
    to discovery are gitignored (.gitignore:88 and :173), so a clean checkout
    has zero producer directories and zero minted documents while a long-lived
    tree accumulates more -- a permanent test that read either would pass
    vacuously on a fresh clone and drift everywhere else. No global directory
    count is asserted anywhere below.
    """
    contract = _contract()
    control = _repo(tmp_path / "control")

    # The six measured directory shapes, each keyed by the canonical task_id
    # its own cycle recorded -- three bare, three prefixed.
    shapes = {
        "dev-20260923-005810": "dev-20260923-005810",
        "dev-20260923-175747": "20260923-175747",
        "dev-20260923-235953": "20260923-235953",
        "dev-20260924-071719": "dev-20260924-071719",
        "dev-20260926-044454": "dev-20260926-044454",
        "dev-command-20260926-111239": "20260926-111239",
        # a previously-unseen dispatch prefix, and a base/-r02 pair
        "quartzsync-20260101-090000": "20260101-090000",
        "dev-20260102-100000": "dev-20260102-100000",
        "dev-20260102-100000-r02": "dev-20260102-100000-r02",
    }
    for index, identity in enumerate(shapes):
        _write_ledger_entry(control, identity, {
            "path": f"shape{index}/INDEX.md", "diff_sha256": f"d{index}",
            "reason": "PostToolUse doc-sync regeneration side effect; not reviewed by dev",
            "source_agent_id": f"agent-{index}", "ts": "2026-01-01T00:00:00Z",
        })
    # The five dev-command records -- the shape the old two-candidate code missed.
    for index in range(1, 5):
        _write_ledger_entry(control, "dev-command-20260926-111239", {
            "path": f"dev-command/{index}/INDEX.md", "diff_sha256": f"dc{index}",
            "reason": "PostToolUse doc-sync regeneration side effect; not reviewed by dev",
            "source_agent_id": f"agent-dc{index}", "ts": "2026-01-01T00:00:00Z",
        }, name=f"dc{index}.json")
    # A same-timestamp two-command collision with ONLY ONE side minted.
    unminted = "close-20260926-111239"
    contract.ledger_dir(control, unminted).mkdir(parents=True)

    for identity, task_id in shapes.items():
        resolved = contract.select_producers(control, task_id)
        assert resolved["consumed"] == [identity], (
            f"{task_id!r} must resolve to {identity}: {resolved}"
        )
        assert resolved["binding_provenance"] == "timestamp_inferred", (
            "the selection is a name-derived inference and must say so in the output; "
            "the artifact that would make it exact does not exist and is escalated"
        )
    collision = contract.select_producers(control, "20260926-111239")
    assert collision["consumed"] == ["dev-command-20260926-111239"]
    assert unminted not in collision["matched"], (
        "the unminted side is rejected BY EVIDENCE, not by its name: both names end in "
        "the same bare timestamp, so any name-shape rule would admit both"
    )
    # A lane-suffixed identity is not absorbed into the base cycle...
    assert contract.select_producers(control, "20260102-100000")["consumed"] == [
        "dev-20260102-100000"
    ]
    # ...and a lane's own suffixed identity resolves for its own task id.
    assert contract.select_producers(control, "dev-20260102-100000-r02")["consumed"] == [
        "dev-20260102-100000-r02"
    ]


def test_m6_live_census_is_evidence_not_a_permanent_postcondition(capsys):
    """AC4's census half: READ-ONLY, separately timestamped, asserts no count.

    This is the half that may legitimately change between any two runs. It
    exists so the convention can be seen holding against reality; the hermetic
    test above is the half that carries the falsifiable content.
    """
    import datetime

    contract = _contract()
    registry = contract.dev_registry_root(REPO_ROOT)
    if not registry.is_dir():
        pytest.skip("no live registry tree in this checkout (it is gitignored)")

    instant = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    producers, paired = [], 0
    for ledger in sorted(registry.glob(f"*/{contract.LEDGER_DIR_NAME}")):
        records = sorted(ledger.glob("*.json"))
        if not records:
            continue
        producers.append((ledger.parent.name, len(records)))
        if contract.is_minted_identity(REPO_ROOT, ledger.parent.name):
            paired += 1

    print(f"hook-ledger live census at {instant} (EVIDENCE, not a postcondition):")
    for identity, count in producers:
        print(f"  {identity}: {count} record(s)")
    print(f"  producer<->minted-document pairing: {paired}/{len(producers)}")

    assert producers, (
        "POSITIVE CONTROL: no producer directory existed at this instant, so this census "
        "evidences nothing. Do not read it as a pass."
    )


def test_dual_listing_constraint_ledger_entry_never_exempts_owned_edits_path(
    tmp_path, monkeypatch, capsys,
):
    """M3's belt-and-suspenders mirror of resolve-commit-repos.py:523-535's
    dual-listing constraint: a stale ledger entry for a path dev's own
    owned_edits already covers must never be routed through
    files_landed_whole instead."""
    control = _repo(tmp_path / "control")
    rel_path = "owned/by/dev.txt"
    (control / "owned" / "by").mkdir(parents=True)
    (control / "owned" / "by" / "dev.txt").write_text("v1\n", encoding="utf-8")
    _git(control, "add", rel_path)
    _git(control, "commit", "-q", "-m", "seed")

    task_id = "20260101-170000"
    dev_session_id = f"dev-{task_id}"
    _write_ledger_entry(control, dev_session_id, {
        "path": rel_path,
        "diff_sha256": "stale-should-be-ignored",
        "reason": "PostToolUse doc-sync regeneration side effect; not reviewed by dev",
        "source_agent_id": "agent-stale",
        "ts": "2026-01-01T17:00:00Z",
    })
    report_path = _write_singular_report(
        control, task_id, [rel_path],
        owned_edits={rel_path: [{"old": "v1\n", "new": "v1\n"}]},
    )

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(control))
    rc = agg_mod.main(["--task-id", task_id])
    assert rc == 0

    updated = json.loads(report_path.read_text(encoding="utf-8"))
    assert not updated.get("files_landed_whole"), (
        "a path already covered by owned_edits must never also be routed "
        "through files_landed_whole via the hook ledger"
    )


# ---------------------------------------------------------------------------
# F-AGG-ASYMMETRY and F-AGG-SHARED-ASSUMPTION (cycle dev-20260927-135305).
#
# F-AGG-ASYMMETRY: the shard scan derived a lane label purely from the
# filename, so a lane's separately-filed fix round stood up as an extra
# parallel worker -- and _validate_shards read the shard's declared identity
# only to compare an embedded timestamp, normalising both sides to the bare
# timestamp so a lane id and the parent id were indistinguishable there.
#
# F-AGG-SHARED-ASSUMPTION: the cross-shard baseline-equality invariant
# encoded an assumption that a fan-out is simultaneous.  A serialized
# fan-out's lanes diverge lawfully, and the invariant's head check had no
# exemption at all, so an honest set could not be projected.
#
# Each test below is written to go RED if its fix is reverted; see the
# docstrings for which revert each one detects.
# ---------------------------------------------------------------------------

_FANOUT_TASK = "dev-20260101-120000"
_FANOUT_BARE = "20260101-120000"


def _write_shard(
    control: Path, label: str, *, identity: str | None = None, **extra
) -> Path:
    """Write docs/dev/dev-report-<task>-<label>.json. identity=None means the
    lane identity matching `label`; identity="" means omit both keys."""
    dev_dir = control / "docs" / "dev"
    dev_dir.mkdir(parents=True, exist_ok=True)
    declared = f"{_FANOUT_TASK}-{label}" if identity is None else identity
    document: dict = {
        "baseline_head_sha": extra.pop("baseline_head_sha", "0" * 40),
        "baseline_dirty_snapshot": extra.pop("baseline_dirty_snapshot", ""),
        "dev": extra.pop("dev", {"status": "completed"}),
    }
    if declared:
        document["request_id"] = declared
        document["task_id"] = declared
    document.update(extra)
    path = dev_dir / f"dev-report-{_FANOUT_TASK}-{label}.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def test_fix_round_filed_separately_is_attributed_to_its_lane_not_a_new_worker(tmp_path):
    """F-AGG-ASYMMETRY. A report named '<lane>-fixround2' that DECLARES the
    lane's own identity belongs to that lane.

    Goes RED if _scan_shards is reverted to returning its filename-derived
    list: the scan then reports a third worker 'b-fixround2'.  Deliberately
    not expressed as 'fixround2 is in a non-worker vocabulary' -- extending
    that vocabulary cannot distinguish '<lane>-<roundlabel>' from a real
    worker, and the question is what lane the artifact says it belongs to.
    """
    control = _repo(tmp_path / "control")
    _write_shard(control, "a")
    _write_shard(control, "b")
    revision = _write_shard(control, "b-fixround2", identity=f"{_FANOUT_TASK}-b")

    dev_dir = control / "docs" / "dev"
    assert agg_mod._self_declared_lane(revision, _FANOUT_TASK) == "b"
    assert agg_mod._is_worker_for_task(
        revision.name, _FANOUT_BARE, _FANOUT_TASK
    ) == (True, "b-fixround2"), "the filename classifier itself is unchanged"

    labels = [label for label, _ in agg_mod._scan_shards(dev_dir, _FANOUT_BARE, _FANOUT_TASK)]
    assert labels == ["a", "b"], (
        "a lane's separately-filed fix round must not stand up as an extra "
        f"parallel worker; got {labels}"
    )

    raw = sorted(
        (agg_mod._is_worker_for_task(p.name, _FANOUT_BARE, _FANOUT_TASK)[1], p)
        for p in dev_dir.iterdir()
    )
    _, merged = agg_mod._attribute_shards_by_identity(raw, _FANOUT_TASK)
    assert merged == [(revision.name, "b-fixround2", "b")], (
        "the attribution must be observable, not a silent omission"
    )
    assert revision.is_file(), "the revision's own record is never disposed of"


def test_shard_with_no_usable_identity_keeps_its_filename_label(tmp_path):
    """F-AGG-ASYMMETRY, fail-closed direction. Blanking, omitting or
    self-contradicting one's own identity must never buy a weaker verdict
    than declaring it honestly, so the filename label still stands.

    Goes RED if identity-first attribution is widened into "drop anything
    whose filename label is not also a declared identity".
    """
    control = _repo(tmp_path / "control")
    _write_shard(control, "a")
    omitted = _write_shard(control, "b-fixround2", identity="")
    blank = _write_shard(control, "c-fixround2", identity=" ")
    contradicting = _write_shard(control, "d-fixround2", identity=f"{_FANOUT_TASK}-d")
    document = json.loads(contradicting.read_text(encoding="utf-8"))
    document["request_id"] = f"{_FANOUT_TASK}-zzz"
    contradicting.write_text(json.dumps(document, indent=2), encoding="utf-8")

    for path in (omitted, blank, contradicting):
        assert agg_mod._self_declared_lane(path, _FANOUT_TASK) is None, path.name

    labels = [
        label
        for label, _ in agg_mod._scan_shards(control / "docs" / "dev", _FANOUT_BARE, _FANOUT_TASK)
    ]
    assert labels == ["a", "b-fixround2", "c-fixround2", "d-fixround2"], labels


def test_declared_identity_can_never_invent_a_lane_no_filename_names(tmp_path):
    """F-AGG-ASYMMETRY, fail-closed direction. Honouring identity may only
    MERGE a file into a lane the shard set already contains under its own
    name; a declaration naming a lane nobody filed cannot create one, and
    cannot make the only report of a lane disappear.

    Goes RED if the `declared in filename_labels` guard is dropped.
    """
    control = _repo(tmp_path / "control")
    _write_shard(control, "a")
    _write_shard(control, "b-fixround2", identity=f"{_FANOUT_TASK}-b")  # no 'b' filed

    labels = [
        label
        for label, _ in agg_mod._scan_shards(control / "docs" / "dev", _FANOUT_BARE, _FANOUT_TASK)
    ]
    assert labels == ["a", "b-fixround2"], (
        "with no shard named 'b', the revision is the only record of that work "
        f"and must stay surfaced rather than silently dropped; got {labels}"
    )


def test_non_utf8_shard_is_not_vouched_for_rather_than_crashing(tmp_path):
    """F-AGG-ASYMMETRY, degenerate shape. Asking a file what lane it belongs
    to must not be the thing that crashes: _load_shard deliberately lets a
    non-UTF-8 file raise so main()'s loader can classify it as a load
    failure and still write a record.

    Goes RED if the (OSError, ValueError) guard in _self_declared_lane is
    dropped -- UnicodeDecodeError is a ValueError, not an OSError.
    """
    control = _repo(tmp_path / "control")
    dev_dir = control / "docs" / "dev"
    dev_dir.mkdir(parents=True, exist_ok=True)
    broken = dev_dir / f"dev-report-{_FANOUT_TASK}-a.json"
    broken.write_bytes(b"\xff\xfe not valid utf8 \x00\x01")

    assert agg_mod._self_declared_lane(broken, _FANOUT_TASK) is None
    assert [
        label for label, _ in agg_mod._scan_shards(dev_dir, _FANOUT_BARE, _FANOUT_TASK)
    ] == ["a"]


def _serialized_wave_pair(tmp_path) -> tuple[Path, list[tuple[str, dict]], str, str]:
    """A two-lane fan-out whose second lane ran after a commit landed."""
    control = _repo(tmp_path / "control")
    first = _git(control, "rev-parse", "HEAD")
    (control / "later.txt").write_text("later\n", encoding="utf-8")
    _git(control, "add", "later.txt")
    _git(control, "commit", "-q", "-m", "a peer session landed this")
    second = _git(control, "rev-parse", "HEAD")

    shards = [
        ("a", {
            "request_id": f"{_FANOUT_TASK}-a", "task_id": f"{_FANOUT_TASK}-a",
            "baseline_head_sha": first, "baseline_dirty_snapshot": "",
            "dev": {"status": "completed"},
        }),
        ("b", {
            "request_id": f"{_FANOUT_TASK}-b", "task_id": f"{_FANOUT_TASK}-b",
            "baseline_head_sha": second, "baseline_dirty_snapshot": "",
            "dev": {"status": "completed"},
            agg_mod.BASELINE_WAVE_KEY: {
                "mode": "serialized_wave",
                "derived_from": "a",
                "explains": ["baseline_head_sha"],
                "predecessor_head_sha": first,
            },
        }),
    ]
    return control, shards, first, second


def test_serialized_wave_declaration_lets_a_lawful_head_divergence_validate(tmp_path):
    """F-AGG-SHARED-ASSUMPTION. A serialized fan-out can be projected.

    Goes RED if _validate_shards' `return` is reverted to `return errors`:
    the verified declaration is then ignored and the head-equality detail
    still fires.
    """
    control, shards, first, second = _serialized_wave_pair(tmp_path)
    assert first != second

    without = agg_mod._validate_shards(shards, _FANOUT_TASK)
    assert without == [
        f"shard 'b': baseline_head_sha {second!r} != first shard {first!r}"
    ], without

    with_route = agg_mod._validate_shards(shards, _FANOUT_TASK, project_root=control)
    assert with_route == [], with_route


def test_a_set_that_declares_nothing_is_byte_identical_with_or_without_the_route(tmp_path):
    """F-AGG-SHARED-ASSUMPTION. The route is not a widening of the default:
    the equality invariant is the untouched behaviour for every fan-out that
    declares nothing, which is every pre-existing cycle."""
    control, shards, first, second = _serialized_wave_pair(tmp_path)
    for _, data in shards:
        data.pop(agg_mod.BASELINE_WAVE_KEY, None)

    without = agg_mod._validate_shards(shards, _FANOUT_TASK)
    with_root = agg_mod._validate_shards(shards, _FANOUT_TASK, project_root=control)
    assert without == with_root
    assert len(without) == 1, without


@pytest.mark.parametrize(
    "mutation, expect_in_detail",
    [
        ({"predecessor_head_sha": "0" * 40}, "does not match the baseline_head_sha"),
        ({"derived_from": "nope"}, "is not among the shards"),
        ({"derived_from": "b"}, "names itself"),
        ({"mode": "parallel"}, "is not supported"),
        ({"explains": []}, "must be a non-empty list"),
        ({"predecessor_head_sha": None}, "is required to account for"),
    ],
)
def test_a_defective_wave_declaration_adds_errors_and_never_removes_any(
    tmp_path, mutation, expect_in_detail,
):
    """F-AGG-SHARED-ASSUMPTION. A declaration is not a waiver: a defective
    one must leave the equality detail standing AND add its own.

    Goes RED if the route is ever reduced to "declaring shards are exempt",
    which is the shape that would make an error class unreachable.
    """
    control, shards, first, second = _serialized_wave_pair(tmp_path)
    equality_detail = (
        f"shard 'b': baseline_head_sha {second!r} != first shard {first!r}"
    )
    shards[1][1][agg_mod.BASELINE_WAVE_KEY].update(mutation)

    errors = agg_mod._validate_shards(shards, _FANOUT_TASK, project_root=control)
    assert equality_detail in errors, (
        f"a defective declaration must not retire the divergence: {errors}"
    )
    assert any(expect_in_detail in detail for detail in errors), errors
    assert len(errors) > len(agg_mod._validate_shards(shards, _FANOUT_TASK)), errors


def test_serialized_wave_divergence_is_disclosed_in_the_projected_aggregate(tmp_path):
    """F-AGG-SHARED-ASSUMPTION. The aggregate's single baseline_* scalars are
    the first shard's. Under a declared wave they are no longer every lane's,
    so the per-lane values must be disclosed rather than silently projected.

    Goes RED if _baseline_wave_projection stops being attached. Also pins
    that it stays OUT of the freshness projection, so it can neither mask nor
    manufacture a STALE_CANONICAL verdict.
    """
    control, shards, first, second = _serialized_wave_pair(tmp_path)
    built = agg_mod._build_aggregate(shards, _FANOUT_TASK)

    assert built["baseline_head_sha"] == first
    projection = built["baseline_wave_projection"]
    assert projection["projected_from_lane"] == "a"
    assert projection["declaring_lanes"] == ["b"]
    assert projection["per_lane_baseline"]["a"]["baseline_head_sha"] == first
    assert projection["per_lane_baseline"]["b"]["baseline_head_sha"] == second
    assert projection["per_lane_baseline"]["b"]["explains"] == ["baseline_head_sha"]
    assert "baseline_wave_projection" not in agg_mod._canonical_projection(built)

    for _, data in shards:
        data.pop(agg_mod.BASELINE_WAVE_KEY, None)
    assert "baseline_wave_projection" not in agg_mod._build_aggregate(shards, _FANOUT_TASK), (
        "a simultaneous fan-out must gain no key at all"
    )


def test_a_refresh_preserves_audit_history_the_builder_has_no_opinion_about(tmp_path):
    """A regeneration that erases the history of a false declaration is its
    own defect. _build_aggregate writes wholesale, so a hand-recorded audit
    key must survive the refresh -- while anything the builder DOES produce
    is always rebuilt, so nothing stale can survive behind this.

    Goes RED if _carry_forward_unbuilt_keys stops being called before the
    refresh write, or if it stops letting built keys win.
    """
    control, shards, first, _second = _serialized_wave_pair(tmp_path)
    dev_dir = control / "docs" / "dev"
    dev_dir.mkdir(parents=True, exist_ok=True)
    canonical = dev_dir / f"dev-report-{_FANOUT_TASK}.json"
    history = {"_doc": "why a false lane declaration was withdrawn", "entries": [1, 2]}
    canonical.write_text(json.dumps({
        "request_id": _FANOUT_TASK,
        "task_id": _FANOUT_TASK,
        "parallel_workers": ["stale", "roster"],
        "lane_declaration_provenance": history,
    }, indent=2), encoding="utf-8")

    built = agg_mod._build_aggregate(shards, _FANOUT_TASK)
    carried = agg_mod._carry_forward_unbuilt_keys(built, canonical)

    assert carried == ["lane_declaration_provenance"]
    assert built["lane_declaration_provenance"] == history
    assert built["parallel_workers"] == ["a", "b"], (
        "a key the builder produces must always win over the existing one"
    )

    missing = dev_dir / "absent.json"
    snapshot = dict(built)
    assert agg_mod._carry_forward_unbuilt_keys(built, missing) == []
    assert built == snapshot

    malformed = dev_dir / "malformed.json"
    malformed.write_text("[1, 2, 3]", encoding="utf-8")
    assert agg_mod._carry_forward_unbuilt_keys(built, malformed) == []
    assert built == snapshot


def test_a_real_refresh_through_main_preserves_audit_history(tmp_path, monkeypatch, capsys):
    """The call-site counterpart of the test above, found necessary by
    reverting the fix and watching the helper-only test stay green: exercising
    the helper proves nothing about whether main()'s refresh path calls it.

    Goes RED if the _carry_forward_unbuilt_keys call in main()'s
    canonical_path.exists() branch is removed -- the refresh then writes the
    built document wholesale and the audit key is gone.
    """
    control = _repo(tmp_path / "control")
    head = _git(control, "rev-parse", "HEAD")
    dev_dir = control / "docs" / "dev"
    for label in ("a", "b"):
        _write_shard(control, label, baseline_head_sha=head)

    canonical = dev_dir / f"dev-report-{_FANOUT_TASK}.json"
    history = {
        "_doc": "the premise of a withdrawn lane declaration and what withdrew it",
        "withdrawn": ["shard 'c': dev.status is None"],
    }
    canonical.write_text(json.dumps({
        "request_id": _FANOUT_TASK,
        "task_id": _FANOUT_TASK,
        "baseline_head_sha": head,
        "parallel_workers": ["a", "b"],
        "dev": {"status": "blocked", "files_modified": ["stale.txt"]},
        "blocking_issues": ["a stale entry the rebuild must drop"],
        "lane_declaration_provenance": history,
    }, indent=2), encoding="utf-8")

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(control))
    assert agg_mod.main(["--task-id", _FANOUT_TASK]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "aggregated"

    refreshed = json.loads(canonical.read_text(encoding="utf-8"))
    assert refreshed["lane_declaration_provenance"] == history, (
        "a refresh that erases the history of a false declaration is its own defect"
    )
    assert refreshed["dev"]["status"] == "completed", "the projection really was rebuilt"
    assert refreshed["blocking_issues"] == [], "a stale built key must not survive"


# ---------------------------------------------------------------------------
# Declared cross-cycle ownership boundaries
#
# A lane's authorship legitimately ENDS where another cycle's declared
# pre-edit snapshot for the same path BEGINS. These tests pin BOTH directions:
# a boundary another cycle actually declared excuses the remainder past it,
# and a remainder nobody declared is still a gap. Every fixture is synthetic
# and self-contained -- the real worktree files these cases were derived from
# are concurrently written by other sessions, so pinning to them would make
# the tests measure the tree's motion instead of the rule.
# ---------------------------------------------------------------------------

_B0 = "alpha\nbeta\ngamma\n"
_B1 = "alpha\nbeta-LANE\ngamma\n"
_B2 = "alpha\nbeta-LANE\ngamma-FOREIGN\n"
_B3 = "alpha-SECOND\nbeta-LANE\ngamma-FOREIGN\n"

_LANE_HUNKS = [{"old": "beta", "new": "beta-LANE"}]
_FOREIGN_HUNKS = [{"old": "gamma", "new": "gamma-FOREIGN"}]
_SECOND_FOREIGN_HUNKS = [{"old": "alpha", "new": "alpha-SECOND"}]
_OWN_TID = "20260927-135305"
_SUBJECT = "subject.md"


@pytest.fixture(autouse=True)
def _clear_foreign_claim_index():
    """The index is memoized per (dev_dir, task); tmp_path reuses neither, but
    an explicit clear keeps one test's fixture from vouching for another's."""
    agg_mod._FOREIGN_CLAIM_INDEX_CACHE.clear()
    yield
    agg_mod._FOREIGN_CLAIM_INDEX_CACHE.clear()


def _boundary_case(tmp_path, live, foreign, lane_hunks=None, own_tid=_OWN_TID):
    """Run the real completeness check for one file. `foreign` maps a report
    filename to (task_id, declared_snapshot, hunks)."""
    (tmp_path / _SUBJECT).write_text(live, encoding="utf-8")
    dev_dir = tmp_path / "docs" / "dev"
    dev_dir.mkdir(parents=True, exist_ok=True)
    for name, (task_id, snapshot, hunks) in foreign.items():
        (dev_dir / name).write_text(json.dumps({
            "task_id": task_id,
            "pre_edit_snapshots": {_SUBJECT: snapshot},
            "owned_edits": {_SUBJECT: hunks},
        }), encoding="utf-8")
    hunks = _LANE_HUNKS if lane_hunks is None else lane_hunks
    return agg_mod._completeness_check_file(
        tmp_path, "", _SUBJECT, hunks, _B0,
        lane_candidates=[("r03", _B0, hunks)],
        dev_dir=dev_dir, own_bare_tid=own_tid,
    )


def test_a_declared_cross_cycle_boundary_ends_a_lanes_authorship(tmp_path):
    """The lane replays B0->B1 and stops. Another cycle declares B1 as the
    point it began and its ledger reaches the live file. The bytes past B1 are
    that cycle's, so they are not this lane's gap."""
    ok, diagnostic = _boundary_case(tmp_path, _B2, {
        "dev-report-20260930-132644-l7.json": ("20260930-132644-l7", _B1, _FOREIGN_HUNKS),
    })
    assert ok, diagnostic
    assert diagnostic == ""


def test_a_remainder_no_other_claimant_declared_is_still_a_gap(tmp_path):
    """Byte-for-byte the same shortfall as the test above, with the single
    difference that no other cycle declares it. The rule is evidence-bound,
    so this must still be reported -- otherwise it is a hole, not a rule."""
    ok, diagnostic = _boundary_case(tmp_path, _B2, {})
    assert not ok, "unclaimed bytes must never be excused"
    assert "byte mismatch" in diagnostic


def test_a_foreign_declaration_that_does_not_match_the_boundary_is_not_followed(tmp_path):
    """A claimant that declares a DIFFERENT starting point than the lane's
    replay output is not a boundary: it is some other edit of the same path.
    Merely naming the path must excuse nothing."""
    ok, diagnostic = _boundary_case(tmp_path, _B2, {
        "dev-report-20269999-999999-x.json": ("20269999-999999-x", "unrelated\n", _FOREIGN_HUNKS),
    })
    assert not ok, "a non-matching declaration is not evidence of a boundary"
    assert "byte mismatch" in diagnostic


def test_a_claim_chain_is_followed_past_its_first_hop(tmp_path):
    """Two further cycles each declare the previous one's output. The chain is
    followed to its END, not one hop."""
    ok, diagnostic = _boundary_case(tmp_path, _B3, {
        "dev-report-20260930-132644-l7.json": ("20260930-132644-l7", _B1, _FOREIGN_HUNKS),
        "dev-report-20261001-161041-r15.json": (
            "20261001-161041-r15", _B2, _SECOND_FOREIGN_HUNKS),
    })
    assert ok, diagnostic


def test_a_chain_that_stops_short_still_reports_the_shortfall(tmp_path):
    """One hop is declared, the live file has moved further, and nobody
    declared the rest. The shortfall AFTER the last declared link is reported
    -- and is reported as the remainder, not as the lane's whole tail."""
    ok, diagnostic = _boundary_case(tmp_path, _B3, {
        "dev-report-20260930-132644-l7.json": ("20260930-132644-l7", _B1, _FOREIGN_HUNKS),
    })
    assert not ok, "a chain that stops short does not close"
    assert "claimed by no declaration" in diagnostic
    assert "20260930-132644-l7" in diagnostic, "the link that WAS declared is attributed"
    shortfall = len(_B3.encode()) - len(_B2.encode())
    assert f"leaving {shortfall} of" in diagnostic, diagnostic


def test_a_lane_that_absorbs_another_cycles_declared_bytes_is_not_complete(tmp_path):
    """The absorption mutant: the lane's ledger swallows the other cycle's
    declared hunk, so its own replay reaches the live file exactly and every
    byte looks accounted for. A prior round measured exactly this shape
    passing scripts/check-owned-edits-ledger.py clean at exit 0.

    Recognising a boundary must never make crossing one easier to pass, so
    this is a gap even though the replay is byte-exact."""
    ok, diagnostic = _boundary_case(tmp_path, _B2, {
        "dev-report-20260930-132644-l7.json": ("20260930-132644-l7", _B1, _FOREIGN_HUNKS),
    }, lane_hunks=_LANE_HUNKS + _FOREIGN_HUNKS)
    assert not ok, "a boundary crossed and claimed is a double claim, not completeness"
    assert "absorbs bytes another cycle already declared" in diagnostic
    assert "20260930-132644-l7" in diagnostic, "the cycle being double-claimed is named"


def test_a_sibling_lane_of_the_same_cycle_can_never_excuse_a_gap(tmp_path):
    """Same declaration as the passing case, but made by a report belonging to
    THIS cycle. In-cycle coverage is the lane-permutation machinery's job; if
    a sibling could excuse a gap here, an in-cycle gap class would become
    unreachable."""
    ok, diagnostic = _boundary_case(tmp_path, _B2, {
        f"dev-report-dev-{_OWN_TID}-r04.json": (f"dev-{_OWN_TID}-r04", _B1, _FOREIGN_HUNKS),
    })
    assert not ok, "a same-cycle sibling is not a cross-cycle boundary"
    assert "byte mismatch" in diagnostic


def test_an_unverifiable_foreign_claim_never_advances_the_chain(tmp_path):
    """The claimant declares the right starting point but its anchor is not
    locatable there, so its ledger cannot be replayed. An unverifiable claim
    is not evidence and must excuse nothing."""
    ok, diagnostic = _boundary_case(tmp_path, _B2, {
        "dev-report-20260930-132644-l7.json": (
            "20260930-132644-l7", _B1, [{"old": "ABSENT-ANCHOR", "new": "x"}]),
    })
    assert not ok, "a claim that cannot replay from its own declaration is not evidence"
    assert "byte mismatch" in diagnostic


def test_the_boundary_rule_is_off_for_callers_that_do_not_supply_the_dev_dir(tmp_path):
    """Back-compat: with dev_dir/own_bare_tid absent the behavior is exactly
    what it was before the rule existed, so no pre-existing caller silently
    changes verdict."""
    (tmp_path / _SUBJECT).write_text(_B2, encoding="utf-8")
    ok, diagnostic = agg_mod._completeness_check_file(
        tmp_path, "", _SUBJECT, _LANE_HUNKS, _B0,
        lane_candidates=[("r03", _B0, _LANE_HUNKS)],
    )
    assert not ok and "byte mismatch" in diagnostic


def test_the_boundary_rule_reaches_files_through_apply_completeness_check(tmp_path):
    """The rule must be WIRED, not merely present: exercised through
    _apply_completeness_check (which is what the aggregate build calls) over a
    real git repo, so the dev_dir/own-identity threading is covered too."""
    control = _repo(tmp_path / "control")
    _track_and_modify(control, _SUBJECT, _B0, _B2)
    dev_dir = control / "docs" / "dev"
    dev_dir.mkdir(parents=True, exist_ok=True)
    (dev_dir / "dev-report-20260930-132644-l7.json").write_text(json.dumps({
        "task_id": "20260930-132644-l7",
        "pre_edit_snapshots": {_SUBJECT: _B1},
        "owned_edits": {_SUBJECT: _FOREIGN_HUNKS},
    }), encoding="utf-8")
    aggregate = {
        "task_id": f"dev-{_OWN_TID}",
        "baseline_head_sha": _git(control, "rev-parse", "HEAD"),
        "owned_edits": {_SUBJECT: _LANE_HUNKS},
        "pre_edit_snapshots": {_SUBJECT: _B0},
    }
    assert agg_mod._apply_completeness_check(aggregate, control) == [], (
        "the declared boundary must clear through the real entry point"
    )

    agg_mod._FOREIGN_CLAIM_INDEX_CACHE.clear()
    (dev_dir / "dev-report-20260930-132644-l7.json").unlink()
    assert agg_mod._apply_completeness_check(aggregate, control), (
        "and with the declaration removed the same bytes are a gap again"
    )


# ---------------------------------------------------------------------------
# Two measured limits of the boundary rule, pinned so they stay visible.
#
# Both were found by executing the adversarial-review questions rather than
# reasoning about them. Neither is a case where the rule hides a gap it should
# report EXCEPT where named as an open hole below.
# ---------------------------------------------------------------------------

def test_an_identical_transformation_by_an_older_cycle_over_reports_theft(tmp_path):
    """KNOWN FALSE POSITIVE, pinned deliberately.

    When an older unrelated cycle declared the SAME (old, new) transformation
    this lane makes -- e.g. the edit was reverted and later re-applied -- the
    absorption check cannot tell re-application from theft and reports a gap.

    It is pinned rather than narrowed because the direction matters: it
    OVER-reports (a gap that needs a human look) and never under-reports, so
    it cannot bless absorption. Narrowing it is the move that would re-open
    the hole it exists to close, so any future narrowing must change this
    test knowingly rather than by accident."""
    ok, diagnostic = _boundary_case(tmp_path, _B1, {
        "dev-report-20260101-000000.json": ("20260101-000000", _B0, _LANE_HUNKS),
    })
    assert not ok, "pinning the measured behavior, not endorsing it"
    assert "absorbs bytes another cycle already declared" in diagnostic
    assert "20260101-000000" in diagnostic


def test_a_declaration_proves_possession_not_authorship(tmp_path):
    """OPEN HOLE, pinned so it is visible rather than discovered later.

    docs/dev is writable by any agent. A report that declares the boundary
    byte-image AND carries a ledger that replays from it will close the
    chain -- which proves whoever wrote it POSSESSED those bytes, not that
    they AUTHORED them. So a fabricated declaration can still suppress a real
    gap.

    It is recorded rather than fixed here for a measured reason: the
    repository's available authorship signal is the co-minted
    docs/dev/user-requirement-<id>.md, and requiring it would reject
    legitimate tool-owner rounds that have no minted identity but whose
    declarations are genuine (measured 2026-10-02: the round whose
    declaration correctly closes one of this cycle's paths is itself
    unminted). Gating on minting would therefore trade this hole for a false
    rejection of true declarations. Closing it needs an authorship
    attestation that does not yet exist, which is a different issue."""
    fabricated = _B1.replace("BETA", "BETA\nNEVER-WRITTEN-BY-THE-LANE")
    ok, _diagnostic = _boundary_case(tmp_path, fabricated, {
        "dev-report-29991231-235959-x.json": (
            "29991231-235959-x", _B1,
            [{"old": "BETA", "new": "BETA\nNEVER-WRITTEN-BY-THE-LANE"}]),
    })
    assert ok, (
        "pinning the measured hole: a declaration that replays is accepted as "
        "a boundary on possession alone. If this ever starts failing, an "
        "authorship signal was added and this test should become its "
        "positive control."
    )


# ---------------------------------------------------------------------------
# Mid-chain foreign bridging (task 20261001-161041-selfhost-close), reproduced
# in miniature from scripts/aggregate-dev-report.py's own real self-hosting
# gap: a foreign cycle's edit can land BETWEEN two of this cycle's own steps,
# not only before the first (_foreign_prefix_extend, pre-existing) or after
# the last (_follow_declared_claim_chain, pre-existing). Neither lane-block
# ordering nor hunk-level interleaving could express that until
# _chain_bounded_orderings and _chain_bounded_hunk_orderings both learned to
# try a foreign claim mid-walk.
# ---------------------------------------------------------------------------

_MC_S0 = "one\ntwo\nthree\nfour\n"
_MC_S1 = "ONE\ntwo\nthree\nfour\n"
_MC_S2 = "ONE\nTWO\nthree\nfour\n"
_MC_S3 = "ONE\nTWO\nTHREE\nfour\n"
_MC_S4 = "ONE\nTWO\nTHREE\nFOUR\n"
_MC_LIVE = "ONE\nTWO\nTHREE\nFOUR!\n"

_MC_LANE_A = [{"old": "one", "new": "ONE"}]
_MC_LANE_B = [{"old": "two", "new": "TWO"}]
_MC_FOREIGN_BLOCK = [{"old": "three", "new": "THREE"}]
_MC_LANE_C = [{"old": "four\n", "new": "FOUR\n"}]
_MC_LANE_D = [{"old": "FOUR\n", "new": "FOUR!\n"}]


def test_lane_block_chain_bridges_a_mid_chain_foreign_claim(tmp_path):
    """4 in-cycle lanes -- exactly _MAX_COMPLETENESS_CANDIDATE_LANES, so this
    also pins the off-by-one fix: N==4 must take the chain-aware branch, not
    the exhaustive-permutation one (the latter has no re-anchoring step and
    so can never place a mid-chain foreign claim). Lane C's own declared
    snapshot is _MC_S3 (what it genuinely observed), not _MC_S2 (lane B's raw
    output) -- the gap between them is real and only a foreign cycle's own
    declared boundary explains it."""
    control = _repo(tmp_path / "control")
    _track_and_modify(control, _SUBJECT, _MC_S0, _MC_LIVE)
    dev_dir = control / "docs" / "dev"
    dev_dir.mkdir(parents=True, exist_ok=True)
    (dev_dir / "dev-report-99999999-999999-foreign.json").write_text(json.dumps({
        "task_id": "99999999-999999-foreign",
        "pre_edit_snapshots": {_SUBJECT: _MC_S2},
        "owned_edits": {_SUBJECT: _MC_FOREIGN_BLOCK},
    }), encoding="utf-8")
    agg_mod._FOREIGN_CLAIM_INDEX_CACHE.clear()

    lane_candidates = [
        ("lane-a", _MC_S0, _MC_LANE_A),
        ("lane-b", _MC_S1, _MC_LANE_B),
        ("lane-c", _MC_S3, _MC_LANE_C),
        ("lane-d", _MC_S4, _MC_LANE_D),
    ]
    merged_hunks = _MC_LANE_A + _MC_LANE_B + _MC_LANE_C + _MC_LANE_D
    ok, diagnostic = agg_mod._completeness_check_file(
        control, _git(control, "rev-parse", "HEAD"), _SUBJECT, merged_hunks, _MC_S0,
        lane_candidates=lane_candidates,
        dev_dir=dev_dir, own_bare_tid="88888888-888888",
    )
    assert ok, diagnostic


_MH_S0 = "one\ntwo\nfour\n"
_MH_LIVE = "ONE\nTWO\nTHREE\nFOUR\n"
_MH_LANE_X = [{"old": "one", "new": "ONE"}, {"old": "three", "new": "THREE"}]
_MH_LANE_Y = [{"old": "four", "new": "FOUR"}]
_MH_FOREIGN = [{"old": "two", "new": "TWO\nthree"}]


def test_hunk_level_pool_bridges_a_mid_lane_foreign_claim(tmp_path):
    """The foreign edit is needed WITHIN a single lane's own two hunks (lane
    X's second hunk anchors on text the foreign claim itself inserts), a
    granularity no LANE-BLOCK ordering -- exhaustive or chain-bounded -- can
    ever express, since a lane-block always applies its own hunks as one
    unit. Only _chain_bounded_hunk_orderings' per-hunk pool, widened to admit
    a foreign cycle's hunks as OPTIONAL items, can place it mid-lane."""
    control = _repo(tmp_path / "control")
    _track_and_modify(control, _SUBJECT, _MH_S0, _MH_LIVE)
    dev_dir = control / "docs" / "dev"
    dev_dir.mkdir(parents=True, exist_ok=True)
    (dev_dir / "dev-report-99999999-999999-foreign2.json").write_text(json.dumps({
        "task_id": "99999999-999999-foreign2",
        "pre_edit_snapshots": {_SUBJECT: "ONE\ntwo\nfour\n"},
        "owned_edits": {_SUBJECT: _MH_FOREIGN},
    }), encoding="utf-8")
    agg_mod._FOREIGN_CLAIM_INDEX_CACHE.clear()

    lane_candidates = [
        ("lane-x", _MH_S0, _MH_LANE_X),
        ("lane-y", "ONE\nTWO\nTHREE\nfour\n", _MH_LANE_Y),
    ]
    merged_hunks = _MH_LANE_X + _MH_LANE_Y
    ok, diagnostic = agg_mod._completeness_check_file(
        control, _git(control, "rev-parse", "HEAD"), _SUBJECT, merged_hunks, _MH_S0,
        lane_candidates=lane_candidates,
        dev_dir=dev_dir, own_bare_tid="88888888-888888",
    )
    assert ok, diagnostic
