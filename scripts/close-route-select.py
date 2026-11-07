#!/usr/bin/env python3
"""Thin production entrypoint /close's Step 0 shells out to.

Without ``--late-repair`` this is a pass-through: it resolves the artifact
chain exactly as before and NEVER touches ``late-repair-controller.py`` --
bare ``/close`` has zero R4 side effects (AC-11). With ``--late-repair`` it
delegates the eligibility check and run-record creation entirely to
``late-repair-controller.py init`` (the single source of truth for
eligibility -- this script never recomputes it). When init declines, the
payload is the pass-through's, built from the chain result init decided on
and carrying init's refusal under ``late_repair``: /close goes on with it on
the ordinary route, so the chain is resolved once per run.

The pass-through payload is ``{"outcome": "not_selected", "artifact_chain":
<resolver result>}`` with ``artifact_chain`` byte-identical to the resolver's
own result and the resolver's own exit status: this script adds no verdict of
its own to the one chain call.

Exit codes:
  0  not_selected (no --late-repair, or init declined) with a passing chain
     (status "pass" or "pass_with_exceptions" -- ticket 20260911-011232), or
     initialized / already_initialized
  1  refuse (usage error, e.g. --late-repair + --force)
  2  not_selected with a failing chain
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


def _not_selected(resolver: ModuleType, result: dict) -> tuple[int, dict]:
    payload = {"outcome": "not_selected", "artifact_chain": result}
    return resolver.exit_status(result), payload


def run(task_id: str, project_dir: str, late_repair: bool, force: bool) -> tuple[int, dict]:
    if late_repair and force:
        payload = {"outcome": "refuse", "reason": "--late-repair combined with --force is not permitted"}
        return 1, payload

    if not late_repair:
        resolver = _resolver_module()
        return _not_selected(resolver, resolver.resolve_chain(project_dir, task_id))

    controller = _controller_module()
    rc, payload, chain = controller.init_run(Path(project_dir).resolve(), task_id)
    if payload.get("outcome") == "refuse":
        # init declined: its chain result is this run's one chain call, used
        # verbatim on the ordinary route rather than resolved again.
        exit_code, ordinary = _not_selected(_resolver_module(), chain)
        ordinary["late_repair"] = payload
        return exit_code, ordinary
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
