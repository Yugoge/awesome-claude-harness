#!/usr/bin/env python3
"""Compatibility entry point: /close Step 0's route select as origin/master's command text calls it.

COMPATIBILITY CODE (live landing, D15/D25), kept like the old permission spellings of D14:
delete this file and tests/test_close_route_select_compat.py together once no session predates
merge train 2's landing. Nothing in this tree calls it. P10 (R6, cc27c36) deleted the route
selector because this tree's /close no longer runs it, and that deletion stands for everything
else; but a session that took up origin/master's /close text before the landing keeps running

    python3 ~/.claude/scripts/close-route-select.py --task-id T --project-dir P [--late-repair]

at Step 0. Without this file that call exits 2 (can't open file), which that text routes as a
resolver finding no producer owns, and the session's /close dead-ends at Step 0.

It answers that call as the deleted selector did, from this tree's own resolver and controller:
without ``--late-repair``, ``{"outcome": "not_selected", "artifact_chain": <resolver result>}``,
the result of resolve-dev-artifact-chain.py verbatim, with the resolver's own exit status; with
``--late-repair``, late-repair-controller.py's init decides (the one eligibility check) and its
payload is printed, or, when init declines, the not_selected payload above carrying init's
refusal under ``late_repair``. No verdict of its own, and no file written but init's run record.

Exit codes: 0 a passing chain, or initialized / already_initialized; 2 any other chain status.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from sibling_loader import load_sibling_module  # noqa: E402


def run(task_id: str, project_dir: str, late_repair: bool) -> tuple[int, dict]:
    if late_repair:
        controller = load_sibling_module("late-repair-controller.py", __file__)
        rc, payload = controller.init_run(Path(project_dir).resolve(), task_id)
        if payload.get("outcome") != "refuse":
            return (0 if rc == 0 else 2), payload
    resolver = load_sibling_module("resolve-dev-artifact-chain.py", __file__)
    result = resolver.resolve_chain(project_dir, task_id)
    selected = {"outcome": "not_selected", "artifact_chain": result}
    if late_repair:
        selected["late_repair"] = payload
    return resolver.exit_status(result), selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--late-repair", action="store_true")
    ns = parser.parse_args(argv)
    exit_code, payload = run(ns.task_id, ns.project_dir, ns.late_repair)
    print(json.dumps(payload, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
