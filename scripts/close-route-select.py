#!/usr/bin/env python3
"""Thin production entrypoint /close's Step 0 shells out to.

Without ``--late-repair`` this is a pass-through: it resolves the artifact
chain exactly as before and NEVER touches ``late-repair-controller.py`` --
bare ``/close`` has zero R4 side effects (AC-11). With ``--late-repair`` it
delegates the eligibility check and run-record creation entirely to
``late-repair-controller.py init`` (the single source of truth for
eligibility -- this script never recomputes it).

Exit codes:
  0  not_selected (no --late-repair) with a passing chain (status "pass" or
     "pass_with_exceptions" -- ticket 20260911-011232), or initialized
  1  refuse (usage error, e.g. --late-repair + --force)
  2  not_selected with a failing chain, or late-repair refuse (ineligible)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from sibling_loader import load_sibling_module  # noqa: E402


def _controller_module() -> ModuleType:
    return load_sibling_module("late-repair-controller.py", __file__)


def _resolver_module() -> ModuleType:
    return load_sibling_module("resolve-dev-artifact-chain.py", __file__)


def run(task_id: str, project_dir: str, late_repair: bool, force: bool) -> tuple[int, dict]:
    if late_repair and force:
        payload = {"outcome": "refuse", "reason": "--late-repair combined with --force is not permitted"}
        return 1, payload

    if not late_repair:
        resolver = _resolver_module()
        result = resolver.resolve_chain(project_dir, task_id)
        payload = {"outcome": "not_selected", "artifact_chain": result}
        return (0 if result["status"] in ("pass", "pass_with_exceptions") else 2), payload

    controller = _controller_module()
    ns = argparse.Namespace(task_id=task_id, project_dir=project_dir, force=False)
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rc = controller.cmd_init(ns)
    try:
        payload = json.loads(buffer.getvalue().strip().splitlines()[-1])
    except (ValueError, IndexError):
        payload = {"outcome": "error", "reason": "controller produced no parseable output"}
    return (0 if rc == 0 else 2), payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--late-repair", action="store_true")
    parser.add_argument("--force", action="store_true")
    ns = parser.parse_args(argv)
    exit_code, payload = run(ns.task_id, ns.project_dir, ns.late_repair, ns.force)
    print(json.dumps(payload, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
