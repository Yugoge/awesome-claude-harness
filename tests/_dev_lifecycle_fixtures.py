"""Shared fixture builders for scripts/dev-lifecycle.py tests (task 20260808-035658-lanel).

NOT a test file itself (no test_ prefix, not collected by pytest). Imported by
tests/test_dev_lifecycle.py and tests/generated/20260808-035658-lanel/test_AC_L*.py
so both suites exercise the exact same builders against the exact same module
under test.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_dev_lifecycle():
    """Dynamically import scripts/dev-lifecycle.py (dash in filename -> no
    plain `import` statement is possible)."""
    path = REPO_ROOT / "scripts" / "dev-lifecycle.py"
    spec = importlib.util.spec_from_file_location("dev_lifecycle_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dlc = load_dev_lifecycle()


# --------------------------------------------------------------------------
# filesystem helpers
# --------------------------------------------------------------------------


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "docs" / "dev").mkdir(parents=True, exist_ok=True)
    return project


def dev_dir(project: Path) -> Path:
    return project / "docs" / "dev"


# --------------------------------------------------------------------------
# canonical-shape builders (mirror the real on-disk artifact contracts)
# --------------------------------------------------------------------------


def ticket_md(task_id: str) -> str:
    return f"# Ticket\nTask-id: {task_id}\n"


def context_json(task_id: str, spec_path: Optional[str] = None) -> dict:
    doc: dict[str, Any] = {"task_id": task_id, "request_id": task_id}
    if spec_path is not None:
        doc["spec_path"] = spec_path
    return doc


def dev_report(
    task_id: str,
    *,
    status: str = "completed",
    files_modified: Optional[list] = None,
    files_created: Optional[list] = None,
    parallel_workers: Optional[list] = None,
    baseline_head_sha: str = "0" * 40,
    baseline_dirty_snapshot: str = "",
) -> dict:
    doc: dict[str, Any] = {
        "task_id": task_id,
        "request_id": task_id,
        "dev": {
            "status": status,
            "files_modified": files_modified if files_modified is not None else [],
            "files_created": files_created if files_created is not None else [],
        },
        "baseline_head_sha": baseline_head_sha,
        "baseline_dirty_snapshot": baseline_dirty_snapshot,
    }
    if parallel_workers is not None:
        doc["parallel_workers"] = parallel_workers
    return doc


def qa_report(task_id: str, *, status: str = "pass") -> dict:
    return {"task_id": task_id, "request_id": task_id, "qa": {"status": status}}


def ba_qa_report(
    task_id: str,
    *,
    top_verdict: Optional[str] = None,
    qa_status: Optional[str] = None,
) -> dict:
    doc: dict[str, Any] = {"task_id": task_id, "request_id": task_id}
    if top_verdict is not None:
        doc["verdict"] = top_verdict
    if qa_status is not None:
        doc["qa"] = {"status": qa_status}
    return doc


def do_report(task_id: str, *, status: str = "completed", files_modified: Optional[list] = None) -> dict:
    return {
        "task_id": task_id,
        "request_id": task_id,
        "source": "do",
        "do": {
            "status": status,
            "files_modified": files_modified if files_modified is not None else [],
        },
    }


def close_report_text(task_id: str, verdict_line: str, extra_body: str = "") -> str:
    return f"# Close Debate Report\nTask-id: {task_id}\n\n{extra_body}\n{verdict_line}\n"


def completion_md(task_id: str) -> str:
    """Satisfies resolve-dev-artifact-chain.py's singular-mode validate_completion:
    a Task-id identity line plus a literal mention of each parent reference path."""
    return (
        f"# Completion\nTask-id: {task_id}\n\n"
        f"Ticket: docs/dev/ticket-{task_id}.md\n"
        f"Context: docs/dev/context-{task_id}.json\n"
        f"Dev report: docs/dev/dev-report-{task_id}.json\n"
        f"QA report: docs/dev/qa-report-{task_id}.json\n"
    )


def write_ticket_fixture(project: Path, task_id: str, *, spec_path: Optional[str] = None) -> None:
    dd = dev_dir(project)
    write_text(dd / f"ticket-{task_id}.md", ticket_md(task_id))
    write_json(dd / f"context-{task_id}.json", context_json(task_id, spec_path=spec_path))


# --------------------------------------------------------------------------
# git repo helpers (AC-L13 commit detection, AC-L22 reachability)
# --------------------------------------------------------------------------


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "-q"], path)
    _run_git(["config", "user.email", "test@example.com"], path)
    _run_git(["config", "user.name", "Test"], path)


def git_commit_all(path: Path, message: str) -> None:
    _run_git(["add", "-A"], path)
    _run_git(["commit", "-q", "-m", message, "--allow-empty"], path)
