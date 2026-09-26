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


def _write_ledger_entry(control: Path, dev_session_id: str, entry: dict, name: str = "entry.json") -> Path:
    ledger_dir = control / ".claude" / "dev-registry" / dev_session_id / "hook-landed-files"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    path = ledger_dir / name
    path.write_text(json.dumps(entry), encoding="utf-8")
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
    assert set(entry.keys()) == {"path", "diff_sha256", "reason"}, (
        "files_landed_whole entries must match agents/changelog-analyst.md's "
        "own schema exactly -- no invented extra keys"
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

    with pytest.raises(commit_mod.PlanError) as excinfo:
        commit_mod.build_plan(
            task_id=task_id,
            control_root_arg=str(control),
            supported_repo_args=[],
            report_arg=str(report_path),
        )
    exc = excinfo.value
    if not hasattr(exc, "code"):
        pytest.fail(
            "PRECONDITION FAILURE (NOT an AC3 regression in this ticket's own change): "
            "PlanError instances raised by build_plan() lack a `.code` attribute in this "
            "working tree. The entire `.code` mechanism on scripts/resolve-commit-repos.py "
            "lives only in backlog #119's orphaned, unlanded, uncommitted diff on that file "
            "(see ticket 20260923-175747 precondition_risks[0]/PR1 and backlog #123's "
            "documented silent-corruption failure mode for that same file). Halting and "
            "reporting per the ticket's mandatory precondition guard instead of treating "
            "this as a defect in the hook-ledger mechanism under test."
        )
    assert exc.code == "foreign_or_unaccounted_edit", (
        "control-flow assertion on .code value only, never on message wording "
        "(backlog #118 convention)"
    )


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
