"""Acceptance tests for scripts/lib/candidate_tree.py.

Every test builds its own throwaway git repository. None of them reads this
repository's history, this cycle's files or this cycle's dev-reports: a test that
asserts against live working-tree state passes or fails for reasons that have
nothing to do with the mechanism, and stops being a test the moment the cycle
lands.

The synthetic repo is shaped around one honest failure. `bin/consumer.sh` is
COMMITTED and refuses to run -- nonzero exit, its own distinctive message on
stderr -- when `bin/helper.env` is missing; `bin/helper.env` is UNCOMMITTED. So
"the helper is in the declared set" and "the helper is not in the declared set"
are distinguishable by RUNNING the committed consumer inside the candidate tree,
rather than by inspecting the tree and trusting that the inspection matches what
execution would do.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "scripts" / "lib" / "candidate_tree.py"

_spec = importlib.util.spec_from_file_location("candidate_tree", MODULE)
candidate_tree = importlib.util.module_from_spec(_spec)
# Registered BEFORE exec: @dataclass resolves annotations through
# sys.modules[cls.__module__], which is None for a not-yet-registered module.
sys.modules[_spec.name] = candidate_tree
_spec.loader.exec_module(candidate_tree)


CONSUMER = """#!/usr/bin/env bash
# Committed consumer: hard-requires a sibling helper and refuses without it.
set -euo pipefail
HELPER="$(dirname "$0")/helper.env"
if [[ ! -f "$HELPER" ]]; then
    echo "consumer: required helper missing at $HELPER; refusing to run" >&2
    exit 3
fi
# shellcheck disable=SC1090
. "$HELPER"
echo "consumer ok: ${HELPER_TOKEN}"
"""

REFUSAL = "refusing to run"
HELPER = "bin/helper.env"
CONSUMER_PATH = "bin/consumer.sh"
TOKEN = "helper-was-overlaid"


def _git(repo, *args, check=True):
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), proc.stderr))
    return proc.stdout


def _write(path: Path, text: str, *, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(0o755)


@pytest.fixture
def synthetic(tmp_path):
    """A repo with a committed consumer and an uncommitted helper it needs."""
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "--quiet")
    _git(src, "config", "user.email", "synthetic@test.local")
    _git(src, "config", "user.name", "synthetic")
    _write(src / CONSUMER_PATH, CONSUMER, executable=True)
    _write(src / "committed.txt", "baseline content\n")
    _git(src, "add", "--all")
    _git(src, "commit", "--quiet", "--message", "baseline")

    # Working-tree-only, exactly like a dev cycle's uncommitted change set.
    _write(src / HELPER, 'HELPER_TOKEN="%s"\n' % TOKEN)
    _write(src / "bin/tool.sh", "#!/bin/sh\nexit 0\n", executable=True)
    _write(src / "bin/ambient.txt", "untracked and undeclared\n")
    (src / "committed.txt").write_text("locally edited\n", encoding="utf-8")
    return src


def _build(src, dest, declared, ref="HEAD"):
    return candidate_tree.build_candidate_tree(src, dest, ref, declared)


def _run_consumer(tree: Path):
    return subprocess.run(
        [str(tree / CONSUMER_PATH)], capture_output=True, text=True, cwd=str(tree))


def test_declared_helper_is_present_and_consumer_runs(synthetic, tmp_path):
    """POSITIVE: helper declared -> present in the tree, consumer succeeds."""
    tree = _build(synthetic, tmp_path / "cand", [HELPER])
    assert (tree.root / HELPER).is_file()
    proc = _run_consumer(tree.root)
    assert proc.returncode == 0, proc.stderr
    assert TOKEN in proc.stdout


def test_undeclared_helper_is_absent_and_consumer_refuses(synthetic, tmp_path):
    """NEGATIVE (load-bearing): drop the helper -> the consumer's own refusal.

    This is what proves the positive test is not vacuous. If a genuinely missing
    required file still produced a green run, the mechanism would be reporting on
    a tree nobody ships.
    """
    tree = _build(synthetic, tmp_path / "cand", [])
    assert not (tree.root / HELPER).exists()
    proc = _run_consumer(tree.root)
    assert proc.returncode != 0
    assert REFUSAL in proc.stderr


def test_missing_declared_member_raises_instead_of_skipping(synthetic, tmp_path):
    """CLOSURE: a declared member absent from disk is a loud error, never a skip."""
    dest = tmp_path / "cand"
    with pytest.raises(candidate_tree.MissingDeclaredMembers) as excinfo:
        _build(synthetic, dest, [HELPER, "bin/never-written.env"])
    assert "bin/never-written.env" in str(excinfo.value)
    assert excinfo.value.missing == ("bin/never-written.env",)
    # Nothing materialised: a failed build leaves no tree to mistake for a good one.
    assert not dest.exists() or not any(dest.iterdir())


def test_untracked_undeclared_file_does_not_leak(synthetic, tmp_path):
    """NO AMBIENT LEAK: an untracked, undeclared file never reaches the tree."""
    tree = _build(synthetic, tmp_path / "cand", [HELPER])
    assert not (tree.root / "bin/ambient.txt").exists()
    assert tree.tracked_mode("bin/ambient.txt") is None


def test_baseline_content_comes_from_the_ref_not_the_checkout(synthetic, tmp_path):
    """An undeclared local edit is not adopted: the baseline is the ref's tree."""
    tree = _build(synthetic, tmp_path / "cand", [HELPER])
    assert (tree.root / "committed.txt").read_text() == "baseline content\n"


def test_overlaid_members_are_tracked_at_the_expected_mode(synthetic, tmp_path):
    """MODE/TRACKEDNESS: asked of the CANDIDATE TREE'S OWN index."""
    tree = _build(synthetic, tmp_path / "cand", [HELPER, "bin/tool.sh"])
    assert tree.tracked_mode(HELPER) == candidate_tree.MODE_REGULAR
    assert tree.tracked_mode("bin/tool.sh") == candidate_tree.MODE_EXECUTABLE
    assert os.access(tree.root / "bin/tool.sh", os.X_OK)
    assert not os.access(tree.root / HELPER, os.X_OK)
    manifest = tree.manifest()
    assert {e["path"] for e in manifest["overlay"]} == {HELPER, "bin/tool.sh"}
    assert manifest["baseline_commit"] == _git(synthetic, "rev-parse", "HEAD").strip()


def test_declared_member_is_tracked_even_when_baseline_ignores_it(tmp_path):
    """Membership is closed: a baseline .gitignore gets no vote on a member."""
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "--quiet")
    _git(src, "config", "user.email", "synthetic@test.local")
    _git(src, "config", "user.name", "synthetic")
    _write(src / ".gitignore", "generated/\n")
    _git(src, "add", "--all")
    _git(src, "commit", "--quiet", "--message", "baseline")
    _write(src / "generated/output.txt", "declared but ignored\n")

    tree = _build(src, tmp_path / "cand", ["generated/output.txt"])
    assert (tree.root / "generated/output.txt").is_file()
    assert tree.tracked_mode("generated/output.txt") == candidate_tree.MODE_REGULAR


def test_symlink_member_is_overlaid_as_a_symlink(synthetic, tmp_path):
    """A declared symlink stays a symlink: copying through it would record the
    wrong mode and silently turn a link into a duplicate of its target."""
    os.symlink("helper.env", synthetic / "bin/alias.env")
    tree = _build(synthetic, tmp_path / "cand", [HELPER, "bin/alias.env"])
    assert (tree.root / "bin/alias.env").is_symlink()
    assert os.readlink(tree.root / "bin/alias.env") == "helper.env"
    assert tree.tracked_mode("bin/alias.env") == candidate_tree.MODE_SYMLINK


def test_build_refuses_a_non_empty_destination(synthetic, tmp_path):
    dest = tmp_path / "cand"
    dest.mkdir()
    (dest / "occupied.txt").write_text("pre-existing\n", encoding="utf-8")
    with pytest.raises(candidate_tree.CandidateTreeError, match="not empty"):
        _build(synthetic, dest, [HELPER])


@pytest.mark.parametrize("member", ["/abs/path", "../escape", "a/../../escape", ".git/config", ""])
def test_unusable_member_paths_are_rejected(synthetic, tmp_path, member):
    with pytest.raises(candidate_tree.DeclaredPathError):
        _build(synthetic, tmp_path / "cand", [member])


def _report(directory: Path, name: str, baseline: str, created, modified):
    _write(directory / name, json.dumps({
        "baseline_head_sha": baseline,
        "dev": {"files_created": created, "files_modified": modified},
    }))


def test_declaration_is_derived_as_a_union_and_excludes_other_baselines(tmp_path):
    """DECLARATION DERIVATION: union across agreeing reports, disagreers dropped."""
    reports = tmp_path / "reports"
    reports.mkdir()
    task, baseline, other = "T-1", "a" * 40, "b" * 40
    _report(reports, "dev-report-%s.json" % task, baseline, ["one.txt"], ["two.txt"])
    _report(reports, "dev-report-%s-lane.json" % task, baseline, [], ["three.txt", "two.txt"])
    _report(reports, "dev-report-%s-stale.json" % task, other, ["excluded.txt"], [])
    _report(reports, "dev-report-OTHER-TASK.json", baseline, ["foreign.txt"], [])

    decl = candidate_tree.derive_declaration(reports, task)
    assert decl.baseline == baseline
    assert decl.paths == ("one.txt", "three.txt", "two.txt")
    assert "excluded.txt" not in decl.paths
    assert "foreign.txt" not in decl.paths
    assert decl.excluded == (("dev-report-%s-stale.json" % task, other),)
    assert set(decl.reports) == {"dev-report-%s.json" % task, "dev-report-%s-lane.json" % task}


def test_required_to_ship_paths_join_the_declaration(synthetic, tmp_path):
    """THIRD CATEGORY: a path required-but-not-authored still reaches the tree.

    A report cannot put such a path in files_created/files_modified without
    claiming an authorship its own git derivation contradicts. Declaring it
    under files_required_to_ship must have the same effect on the candidate
    tree and none on the authorship record.
    """
    reports = tmp_path / "reports"
    reports.mkdir()
    task = "T-4"
    baseline = _git(synthetic, "rev-parse", "HEAD").strip()
    _write(reports / ("dev-report-%s.json" % task), json.dumps({
        "baseline_head_sha": baseline,
        "dev": {
            "files_created": [],
            "files_modified": [],
            "files_required_to_ship": [HELPER],
        },
    }))

    tree, decl = candidate_tree.build_from_declaration(
        synthetic, tmp_path / "cand", reports, task)
    assert decl.paths == (HELPER,)
    assert tree.tracked_mode(HELPER) == candidate_tree.MODE_REGULAR
    assert _run_consumer(tree.root).returncode == 0

    # CLOSURE IS NOT WEAKENED by the new category: a required-to-ship member
    # that is absent is still a hard error, never a silent skip.
    (synthetic / HELPER).unlink()
    with pytest.raises(candidate_tree.MissingDeclaredMembers):
        candidate_tree.build_from_declaration(
            synthetic, tmp_path / "cand2", reports, task)


def test_report_without_a_recorded_baseline_is_excluded(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    task, baseline = "T-2", "c" * 40
    _report(reports, "dev-report-%s.json" % task, baseline, ["kept.txt"], [])
    _write(reports / ("dev-report-%s-nobase.json" % task), json.dumps(
        {"dev": {"files_created": ["dropped.txt"], "files_modified": []}}))

    decl = candidate_tree.derive_declaration(reports, task)
    assert decl.paths == ("kept.txt",)
    assert decl.excluded == (("dev-report-%s-nobase.json" % task, None),)


def test_derived_declaration_drives_the_build(synthetic, tmp_path):
    """End to end: the recorded declaration, not a re-typed list, selects members."""
    reports = tmp_path / "reports"
    reports.mkdir()
    task = "T-3"
    baseline = _git(synthetic, "rev-parse", "HEAD").strip()
    _report(reports, "dev-report-%s.json" % task, baseline, [HELPER], [])

    tree, decl = candidate_tree.build_from_declaration(
        synthetic, tmp_path / "cand", reports, task)
    assert decl.baseline == baseline
    assert tree.ref == baseline
    assert tree.tracked_mode(HELPER) == candidate_tree.MODE_REGULAR
    assert _run_consumer(tree.root).returncode == 0


def test_derivation_fails_loudly_when_no_report_exists(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    with pytest.raises(candidate_tree.DeclarationError):
        candidate_tree.derive_declaration(reports, "no-such-task")
