"""Shared fixture builders for the R4 late-repair test suite.

Not collected by pytest (leading underscore).  Builds four representative
singular/fan-out artifact chains used by BOTH the AC-15 golden-baseline
regression test and the AC-6/AC-7/AC-8/AC-9/AC-13/AC-14 late-repair tests, so
every consumer classifies the exact same fixture shapes the same way.

Every builder writes real files under ``root/docs/dev`` and returns the paths
it created.  Content -- not the tmp_path location -- determines the
resolver's output, so re-running a builder against a fresh tmp_path
reproduces byte-identical resolver output every time (required for the AC-15
golden comparison).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

TASK_ID = "20260101-000000"
FANOUT_WORKERS = ["lane-a", "lane-b"]


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, dict):
        value = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.write_text(value, encoding="utf-8")


def _dev_dir(root: Path) -> Path:
    path = root / "docs" / "dev"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _dev_document(identity: str, *, status: str = "completed", modified=None, created=None) -> dict:
    return {
        "request_id": identity,
        "task_id": identity,
        "baseline_head_sha": "0" * 40,
        "baseline_dirty_snapshot": "",
        "dev": {
            "status": status,
            "tasks_completed": [f"completed {identity}"],
            "scripts_created": [],
            "permissions_to_add": [],
            "files_modified": modified or [],
            "files_created": created or [],
            "observed_preexisting": [],
        },
        "blocking_issues": [],
        "recommendations": [],
    }


def _qa_document(identity: str, status: str = "pass") -> dict:
    return {"request_id": identity, "task_id": identity, "qa": {"status": status}}


def _ticket(identity: str) -> str:
    return f"# Ticket\n\n**TASK-ID**: `{identity}`\n"


def _completion(identity: str, references: list[str]) -> str:
    lines = [f"# Completion\n\n**Request ID**: `{identity}`\n"]
    lines.extend(f"- `{reference}`\n" for reference in references)
    return "".join(lines)


def _parent_paths(root: Path, task_id: str = TASK_ID) -> dict[str, Path]:
    dev_dir = _dev_dir(root)
    declare_stage_dispatches(root, task_id)
    return {
        "ticket": dev_dir / f"ticket-{task_id}.md",
        "context": dev_dir / f"context-{task_id}.json",
        "dev_report": dev_dir / f"dev-report-{task_id}.json",
        "qa_report": dev_dir / f"qa-report-{task_id}.json",
        "completion": dev_dir / f"completion-{task_id}.md",
    }


def declare_stage_dispatches(root: Path, task_id: str) -> None:
    """The BA, dev and QA dispatch records of the task, in a session transcript
    of the store the test's CLAUDE_CONFIG_DIR names: record-stage takes a
    stage report's role from the dispatch that declared it."""
    store = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / str(Path(root).resolve()).replace("/", "-")
    store.mkdir(parents=True, exist_ok=True)

    def dispatch(role: str, artifacts: list) -> dict:
        block = {"task_id": task_id, "lane": None, "lane_set": None, "role": role, "pipeline": "dev",
                 "profile": "singular", "dispatched_at": "2026-01-01T00:00:00Z", "artifacts": artifacts}
        prompt = f'<obligation v="1">\n{json.dumps(block)}\n</obligation>'
        return {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": f"toolu_{role}_{task_id}", "name": "Agent",
             "input": {"subagent_type": role, "prompt": prompt}}]}}

    def json_artifact(name: str, schema: str) -> dict:
        return {"kind": "json", "path": f"docs/dev/{name}", "schema": schema, "identity": {"task_id": task_id}}

    records = [
        {"type": "user", "message": {"role": "user", "content": f"/close --late-repair {task_id}"}},
        dispatch("ba", [json_artifact(f"context-{task_id}.json", "context.v1"),
                        {"kind": "markdown", "path": f"docs/dev/ticket-{task_id}.md", "identity_anchor": task_id}]),
        dispatch("dev", [json_artifact(f"dev-report-{task_id}.json", "dev-report.v2")]),
        dispatch("qa", [json_artifact(f"qa-report-{task_id}.json", "qa-report.v2")]),
    ]
    (store / f"late-repair-{task_id}.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def build_complete(root: Path, task_id: str = TASK_ID) -> dict[str, Path]:
    """Fully valid singular chain -- resolver status: pass, gap_classification: complete."""
    paths = _parent_paths(root, task_id)
    _write(paths["ticket"], _ticket(task_id))
    _write(paths["context"], {"request_id": task_id, "task_id": task_id})
    _write(paths["dev_report"], _dev_document(task_id))
    _write(paths["qa_report"], _qa_document(task_id))
    references = [_relative(root, paths[key]) for key in ("ticket", "context", "dev_report", "qa_report")]
    _write(paths["completion"], _completion(task_id, references))
    return paths


def build_qa_only(root: Path, task_id: str = TASK_ID) -> dict[str, Path]:
    """Chain missing only the QA report -- gap_classification: qa_only."""
    paths = _parent_paths(root, task_id)
    _write(paths["ticket"], _ticket(task_id))
    _write(paths["context"], {"request_id": task_id, "task_id": task_id})
    _write(paths["dev_report"], _dev_document(task_id))
    # qa_report intentionally absent.
    references = [_relative(root, paths[key]) for key in ("ticket", "context", "dev_report", "qa_report")]
    _write(paths["completion"], _completion(task_id, references))
    return paths


def build_beyond_qa_clean(root: Path, task_id: str = TASK_ID) -> dict[str, Path]:
    """Ticket + context + qa-report all missing, no other integrity errors.

    late_repair_eligible: true, gap_classification: beyond_qa, stage_gaps
    holds ticket+context paths, non_gap_errors is empty.
    """
    paths = _parent_paths(root, task_id)
    # ticket, context, qa_report intentionally absent.
    _write(paths["dev_report"], _dev_document(task_id))
    references = [_relative(root, paths[key]) for key in ("ticket", "context", "dev_report", "qa_report")]
    _write(paths["completion"], _completion(task_id, references))
    return paths


def build_mixed_integrity(root: Path, task_id: str = TASK_ID) -> dict[str, Path]:
    """Ticket missing (stage gap) PLUS an unrelated non_gap_error on the dev-report.

    late_repair_eligible MUST be false despite stage_gaps being non-empty
    (codex finding #7): a real stage gap co-occurring with an unrelated
    integrity error is not late-repair eligible.
    """
    paths = _parent_paths(root, task_id)
    # ticket intentionally absent -> MISSING_ARTIFACT (stage gap).
    _write(paths["context"], {"request_id": task_id, "task_id": task_id})
    # dev.status != "completed" -> INVALID_DEV_STATUS (non_gap_error), an
    # integrity problem unrelated to any missing stage artifact.
    _write(paths["dev_report"], _dev_document(task_id, status="blocked"))
    _write(paths["qa_report"], _qa_document(task_id))
    references = [_relative(root, paths[key]) for key in ("ticket", "context", "dev_report", "qa_report")]
    _write(paths["completion"], _completion(task_id, references))
    return paths


def build_fanout(root: Path, task_id: str = TASK_ID, workers: list[str] | None = None) -> dict[str, Path]:
    """Fully valid fan-out chain -- resolver mode: fanout, gap fields: NOT_APPLICABLE."""
    workers = workers or list(FANOUT_WORKERS)
    parents = _parent_paths(root, task_id)
    references = [_relative(root, parents["dev_report"])]
    loaded = []
    for index, worker in enumerate(workers):
        identity = f"{task_id}-{worker}"
        dev_dir = _dev_dir(root)
        lane_paths = {
            "ticket": dev_dir / f"ticket-{identity}.md",
            "context": dev_dir / f"context-{identity}.json",
            "dev_report": dev_dir / f"dev-report-{identity}.json",
            "qa_report": dev_dir / f"qa-report-{identity}.json",
        }
        dev = _dev_document(identity)
        _write(lane_paths["ticket"], _ticket(identity))
        _write(lane_paths["context"], {"request_id": identity, "task_id": identity})
        _write(lane_paths["dev_report"], dev)
        _write(lane_paths["qa_report"], _qa_document(identity))
        loaded.append((worker, dev))
        references.extend(_relative(root, lane_paths[key]) for key in ("ticket", "context", "dev_report", "qa_report"))

    import importlib.util

    resolver_path = Path(__file__).resolve().parent.parent / "scripts" / "resolve-dev-artifact-chain.py"
    spec = importlib.util.spec_from_file_location("_dev_chain_resolver_for_fanout_fixture", resolver_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    aggregate = module._load_aggregate_module()._build_aggregate(loaded, task_id)
    aggregate["parallel_workers"] = list(workers)
    _write(parents["dev_report"], aggregate)
    _write(parents["completion"], _completion(task_id, references))
    return parents
