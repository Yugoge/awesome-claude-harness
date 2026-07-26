"""Regressions for scripts/stage-owned-hunks.py provenance modes.

These modes are DORMANT: no command, agent definition, or hook invokes them by
default. The tests pin the helper's behaviour for explicit, hand-supplied
invocations only.
"""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "scripts" / "stage-owned-hunks.py"
TASK_ID = "dev-20260720-150632"


def git(repo, *args, input_bytes=None, check=True):
    result = subprocess.run(
        ["git", "-C", str(repo), *args], input=input_bytes,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if check and result.returncode:
        raise AssertionError(result.stderr.decode())
    return result


def _nonmutating_state(root: Path, paths: set[str]) -> dict:
    index_path = Path(git(root, "rev-parse", "--git-path", "index").stdout.decode().strip())
    if not index_path.is_absolute():
        index_path = root / index_path
    return {
        "head": git(root, "rev-parse", "HEAD").stdout,
        "index": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        "cached": git(root, "diff", "--cached", "--binary").stdout,
        "worktree": {
            path: (
                hashlib.sha256((root / path).read_bytes()).hexdigest(),
                (root / path).stat().st_mode & 0o777,
            )
            for path in paths if (root / path).is_file()
        },
    }


@pytest.fixture
def composed_case(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    target = repo / "state.txt"
    target.write_text("slot\n")
    git(repo, "add", "state.txt")
    git(repo, "commit", "-qm", "head")
    head = git(repo, "rev-parse", "HEAD").stdout.decode().strip()

    git(repo, "switch", "-qc", "checkpoint-fixture")
    target.write_text("foreign-before\nslot\n")
    git(repo, "commit", "-qam", "base")
    base = git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    target.write_text("foreign-before\nowned\n")
    git(repo, "commit", "-qam", "checkpoint owned")
    end = git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    git(repo, "switch", "-q", "--detach", head)
    target.write_text("foreign-before\nlater\nforeign-after\n")

    evidence = repo / "do-report.json"
    evidence.write_text(json.dumps({
        "source": "do",
        "do": {"files_modified": ["state.txt"], "files_created": []},
    }))
    checkpoint = {
        "task_id": f"{TASK_ID}-a",
        "path": "state.txt",
        "base_commit": base,
        "owned_end_commit": end,
        "base_blob": git(repo, "rev-parse", f"{base}:state.txt").stdout.decode().strip(),
        "owned_end_blob": git(repo, "rev-parse", f"{end}:state.txt").stdout.decode().strip(),
        "binding_artifacts": [{
            "path": "do-report.json",
            "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        }],
        "scope_rationale": "Checkpoint changes the owned slot while foreign lines stay unstaged.",
    }
    plan = {
        "task_id": TASK_ID,
        "path": "state.txt",
        "segments": [
            {
                "kind": "checkpoint",
                "source_worker": "a",
                "source_task_id": f"{TASK_ID}-a",
                "checkpoint_provenance": checkpoint,
            },
            {
                "kind": "live",
                "source_worker": "b",
                "source_task_id": f"{TASK_ID}-b",
                "owned_edits": [{"old": "owned", "new": "later"}],
                "pre_edit_snapshot": "foreign-before\nowned\nforeign-after\n",
            },
        ],
    }
    plan_path = repo / "plan.json"
    plan_path.write_text(json.dumps(plan))
    return repo, plan_path


def run_plan(repo, plan_path, *extra):
    return subprocess.run(
        [sys.executable, str(HELPER), "--git-root", str(repo), "--file", "state.txt",
         "--provenance-plan", str(plan_path), "--task-id", TASK_ID, *extra],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def test_composes_checkpoint_and_later_live_provenance_without_foreign_hunks(composed_case):
    repo, plan_path = composed_case
    result = run_plan(repo, plan_path, "--plan-only")
    assert result.returncode == 0, result.stderr.decode()
    plan = json.loads(result.stdout)
    assert plan["segment_count"] == 2
    assert "+later" in plan["patch"] and "-slot" in plan["patch"]
    assert "foreign-before" not in plan["patch"]
    assert "foreign-after" not in plan["patch"]
    assert git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0


def test_approved_digest_mismatch_aborts_and_restores_index(composed_case):
    repo, plan_path = composed_case
    result = run_plan(repo, plan_path, "--approved-sha256", "0" * 64)
    assert result.returncode == 10
    assert b"approved patch digest mismatch" in result.stderr
    assert git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0


def test_current_mode_drift_and_real_overlap_fail_closed(composed_case):
    repo, plan_path = composed_case
    target = repo / "state.txt"
    target.chmod(0o755)
    mode = run_plan(repo, plan_path, "--plan-only")
    assert mode.returncode == 10
    assert b"current worktree mode" in mode.stderr
    target.chmod(0o644)
    target.write_text("foreign-before\npeer-overlap\nforeign-after\n")
    overlap = run_plan(repo, plan_path, "--plan-only")
    assert overlap.returncode == 10
    assert b"no provenance hunk" in overlap.stderr


def _write_untracked_modified_report(
    repo: Path, task_id: str, rel: str, before_sha: str, final_sha: str
) -> Path:
    report = repo / "docs" / "dev" / f"dev-report-{task_id}.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "task_id": task_id,
        "request_id": task_id,
        "baseline_head_sha": git(repo, "rev-parse", "HEAD").stdout.decode().strip(),
        "dev": {"files_modified": [rel], "files_created": []},
        "pre_edit_provenance": {
            "source": "dispatch current_file_hashes",
            "verified_before_edit": True,
            "files": {rel: before_sha},
            "statuses": {rel: "??"},
        },
        "final_source_hashes": {rel: final_sha},
        "untracked_modified_provenance": {
            rel: {
                "path": rel,
                "admission": "authenticated_preexisting_untracked_whole_file",
                "pre_edit": {"git_status": "??", "sha256": before_sha},
                "final": {"git_status": "??", "sha256": final_sha},
                "evidence_source": "dispatch hash plus pre-edit porcelain observation",
            },
        },
    }), encoding="utf-8")
    return report


def _run_untracked_modified(
    repo: Path, report: Path, task_id: str, rel: str, *extra: str
) -> subprocess.CompletedProcess:
    report_sha = hashlib.sha256(report.read_bytes()).hexdigest()
    return subprocess.run(
        [
            sys.executable, str(HELPER),
            "--git-root", str(repo),
            "--file", rel,
            "--untracked-modified-report", str(report),
            "--report-sha256", report_sha,
            "--task-id", task_id,
            *extra,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_authenticated_preexisting_untracked_modification_plans_and_stages_exact_patch(
    tmp_path: Path,
) -> None:
    """Cover normal downstream admission, not only repository partitioning."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "seed.txt").write_text("seed\n")
    git(repo, "add", "seed.txt")
    git(repo, "commit", "-qm", "head")

    task_id = "untracked-admission"
    rel = "tests/existing_draft.py"
    target = repo / rel
    target.parent.mkdir()
    target.write_text("def draft():\n    return False\n", encoding="utf-8")
    before_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    target.write_text("def draft():\n    return True\n", encoding="utf-8")
    final_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    report = _write_untracked_modified_report(
        repo, task_id, rel, before_sha, final_sha
    )

    before = _nonmutating_state(repo, {rel})
    planned = _run_untracked_modified(repo, report, task_id, rel, "--plan-only")
    assert planned.returncode == 0, planned.stderr.decode()
    plan = json.loads(planned.stdout)
    assert plan["admission"] == "authenticated_preexisting_untracked_whole_file"
    assert plan["pre_edit_sha256"] == before_sha
    assert plan["final_sha256"] == final_sha
    assert "+    return True" in plan["patch"]
    assert _nonmutating_state(repo, {rel}) == before

    staged = _run_untracked_modified(
        repo, report, task_id, rel,
        "--approved-sha256", plan["patch_sha256"],
    )
    assert staged.returncode == 0, staged.stderr.decode()
    assert git(repo, "diff", "--cached", "--name-only").stdout == (rel + "\n").encode()
    assert git(repo, "show", f":{rel}").stdout == target.read_bytes()


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("drop_contract", b"path contract missing"),
        ("claim_created", b"no files_created claim"),
        ("wrong_pre_hash", b"lacks verified canonical provenance"),
        ("wrong_final_status", b"status binding must be exactly ??"),
        ("unchanged_hash", b"no authenticated cycle modification"),
        ("current_drift", b"differ from attested final hash"),
    ],
)
def test_untracked_modified_admission_rejects_unbound_or_drifted_paths(
    tmp_path: Path, mutation: str, expected: bytes
) -> None:
    repo = tmp_path / mutation
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "seed.txt").write_text("seed\n")
    git(repo, "add", "seed.txt")
    git(repo, "commit", "-qm", "head")
    task_id = "untracked-negative"
    rel = "candidate.txt"
    target = repo / rel
    target.write_text("before\n")
    before_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    target.write_text("after\n")
    final_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    report = _write_untracked_modified_report(repo, task_id, rel, before_sha, final_sha)
    payload = json.loads(report.read_text())
    contract = payload["untracked_modified_provenance"][rel]
    if mutation == "drop_contract":
        payload.pop("untracked_modified_provenance")
    elif mutation == "claim_created":
        payload["dev"]["files_created"] = [rel]
    elif mutation == "wrong_pre_hash":
        contract["pre_edit"]["sha256"] = "0" * 64
    elif mutation == "wrong_final_status":
        contract["final"]["git_status"] = " M"
    elif mutation == "unchanged_hash":
        contract["final"]["sha256"] = before_sha
        payload["final_source_hashes"][rel] = before_sha
    elif mutation == "current_drift":
        target.write_text("peer drift\n")
    report.write_text(json.dumps(payload))

    result = _run_untracked_modified(repo, report, task_id, rel, "--plan-only")
    assert result.returncode == 10
    assert expected in result.stderr
    assert git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0
