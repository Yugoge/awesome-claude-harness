"""Runtime-level regression coverage for agents/changelog-analyst.md's
`files_landed_whole` TOCTOU-safe stage-then-verify sequence (currently at
lines ~879-928: stage first inside the held fd-9 flock, then verify the
INDEX -- never the working tree -- via
`git diff --cached --no-ext-diff --no-textconv HEAD -- <path> | sha256sum`;
on mismatch, `git restore --staged` + re-check `git diff --cached
--name-only`, excluding the path with a `WARNING: excluding ...` message;
on rollback failure, ABORT the entire commit transaction naming the path).

Lane L7 of spec-20260930-092323 (ticket-20260930-132644-l7), AC14 / R8:
"verify (not reimplement) that changelog-analyst's existing stage-then-
verify sequence for `files_landed_whole` has adequate test coverage for its
two failure paths and add tests if coverage is missing." The investigation
(this ticket's Evidence section) found the sequence itself already correct
-- the gap is test coverage, not logic.

STRENGTH OF THIS EVIDENCE: the component under test is PROSE executed by a
model (agents/changelog-analyst.md is a markdown behavioral spec, not an
importable Python module), so there is no production function to import
and call directly. This file instead defines `stage_then_verify_files_landed_whole`,
a small harness that performs the EXACT documented git command sequence
(`git add`, `git diff --cached --no-ext-diff --no-textconv HEAD -- <path> |
sha256sum`, `git restore --staged`, re-check `git diff --cached
--name-only`) against a REAL throwaway git fixture repo via real
subprocess calls. This proves the documented command sequence itself
behaves as described under both failure modes -- it does not prove a model
executing the prose will always invoke these exact commands, which no
test outside a live model transcript can prove. This is the DISTINCT,
complementary half of the evidence `tests/test_changelog_analyst_declaration_categories.py::
test_landed_whole_digest_is_verified_after_staging_not_before` does not
provide (that test pins the prose text itself; this test pins the git
plumbing the prose describes). Per this ticket's "AC14 test-file placement"
Technical Hint, this is intentionally a NEW file, not an extension of that
prose-level test -- the two files test different things and mixing them
would blur both files' own evidence-strength contracts.

Only the rollback step in the rollback-FAILURE test is ever overridden (via
dependency injection, `restore_fn`) -- staging and digest-mismatch
detection always run as real git subprocess calls in every test below. A
real `git restore --staged` failure is impractical to induce reliably in a
throwaway fixture repo without external tooling (e.g. deliberately
corrupting .git/index permissions, which behaves inconsistently when the
test runner itself is root); injecting the failure at the one call site
that can legitimately fail is the standard technique for exercising an
otherwise-unreachable error branch without weakening coverage of the real
git-level mismatch-detection path, which is the actual TOCTOU-safety
invariant (codex bulk-commit-qa-20260926 finding #4) this test guards.
"""

import hashlib
import subprocess
from pathlib import Path

import pytest


def _run(args, cwd):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=False)


def _diff_sha256(repo, path, staged=False):
    """Mirrors hooks/doc_sync/hook_ledger.py::_diff_sha256's exact flags, as
    agents/changelog-analyst.md:891-894 specifies: declaration and
    verification must never drift into different diff formats."""
    cmd = ["git", "diff"]
    if staged:
        cmd.append("--cached")
    cmd += ["--no-ext-diff", "--no-textconv", "HEAD", "--", path]
    proc = _run(cmd, repo)
    return hashlib.sha256(proc.stdout.encode("utf-8")).hexdigest()


def stage_then_verify_files_landed_whole(repo, path, declared_sha256, restore_fn=None):
    """Mirrors agents/changelog-analyst.md:908-928's documented sequence.

    Returns a dict with `outcome` in {"staged", "excluded", "abort"}.

    `restore_fn`, when given, replaces the real `git restore --staged` +
    recheck step for the SOLE purpose of injecting a rollback failure --
    it must return (exit_code: int, still_staged: bool). Staging and
    digest computation always run as real git subprocess calls.
    """
    _run(["git", "add", "--", path], repo)
    staged_sha = _diff_sha256(repo, path, staged=True)

    if staged_sha == declared_sha256:
        return {"outcome": "staged", "path": path}

    if restore_fn is not None:
        rc, still_staged = restore_fn()
    else:
        proc = _run(["git", "restore", "--staged", "--", path], repo)
        rc = proc.returncode
        recheck = _run(["git", "diff", "--cached", "--name-only", "HEAD", "--", path], repo)
        still_staged = bool(recheck.stdout.strip())

    if rc == 0 and not still_staged:
        return {
            "outcome": "excluded",
            "path": path,
            "message": (
                f"WARNING: excluding {path} -- declared files_landed_whole, but the "
                f"staged diff does not match the declared diff_sha256 (declared "
                f"{declared_sha256}, staged {staged_sha}); a peer changed the file "
                f"after the declaration and its hunks were never reviewed."
            ),
        }

    return {
        "outcome": "abort",
        "path": path,
        "message": (
            f"ABORT the entire commit transaction: rollback of {path} failed "
            f"(exit={rc}, still_staged={still_staged}) -- unreviewed bytes are "
            f"still staged and every later step would commit them."
        ),
    }


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-q"], repo)
    _run(["git", "config", "user.email", "test@example.com"], repo)
    _run(["git", "config", "user.name", "Test"], repo)
    f = repo / "tracked.txt"
    f.write_text("original content\n")
    _run(["git", "add", "tracked.txt"], repo)
    _run(["git", "commit", "-q", "-m", "init"], repo)
    return repo


def test_digest_mismatch_excludes_and_warns(git_repo):
    """AC14 (a): the staged digest mismatches the declared diff_sha256 ->
    the file is excluded from the commit set and a `WARNING: excluding
    ...` message shape is produced, against ACTUAL git-fixture command
    execution."""
    (git_repo / "tracked.txt").write_text(
        "original content\nTHIS CHANGE WAS NEVER REVIEWED BY ANY CYCLE\n"
    )
    wrong_declared_sha256 = "0" * 64

    result = stage_then_verify_files_landed_whole(git_repo, "tracked.txt", wrong_declared_sha256)

    assert result["outcome"] == "excluded"
    assert result["message"].startswith("WARNING: excluding tracked.txt")
    assert "tracked.txt" in result["message"]

    staged = _run(["git", "diff", "--cached", "--name-only"], git_repo).stdout.strip()
    assert staged == "", "rollback must leave nothing staged for the excluded path"


def test_rollback_failure_aborts_transaction(git_repo):
    """AC14 (b): the subsequent rollback itself fails -> the whole
    transaction aborts, naming the path."""
    (git_repo / "tracked.txt").write_text(
        "original content\nTHIS CHANGE WAS NEVER REVIEWED BY ANY CYCLE\n"
    )
    wrong_declared_sha256 = "0" * 64

    def failing_restore():
        # Simulate a rollback whose own recheck still shows the path
        # staged -- the one git-level failure mode a throwaway fixture
        # repo cannot reliably reproduce without external tooling.
        return (1, True)

    result = stage_then_verify_files_landed_whole(
        git_repo, "tracked.txt", wrong_declared_sha256, restore_fn=failing_restore
    )

    assert result["outcome"] == "abort"
    assert "tracked.txt" in result["message"]
    assert "ABORT" in result["message"]


def test_digest_match_keeps_file_staged(git_repo):
    """Control: when the declared digest matches the post-staging index
    diff, the file is kept staged, not excluded -- proves the harness does
    not vacuously exclude every candidate (i.e. the two tests above are
    exercising the mismatch branch specifically, not a harness that always
    excludes)."""
    (git_repo / "tracked.txt").write_text("original content\nreviewed change\n")
    # Declared digest is computed from the WORKING-TREE diff before
    # staging, exactly as hooks/doc_sync/hook_ledger.py::_diff_sha256 does
    # at report-write time; with no peer interference the post-staging
    # INDEX diff is byte-identical.
    correct_sha256 = _diff_sha256(git_repo, "tracked.txt", staged=False)

    result = stage_then_verify_files_landed_whole(git_repo, "tracked.txt", correct_sha256)

    assert result["outcome"] == "staged"
    staged = _run(["git", "diff", "--cached", "--name-only"], git_repo).stdout.strip()
    assert staged == "tracked.txt"
