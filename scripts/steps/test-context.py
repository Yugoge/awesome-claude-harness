#!/usr/bin/env python3
"""Steps 7, 10 and 11 of /test: the validation context, the execution context, the safety checkpoint.

    test-context.py validation --request-id ID [--timestamp T] [--project-root DIR]
    test-context.py execution  --request-id ID --validation-status S --validators-checked N
                               [--timestamp T] [--project-root DIR]
    test-context.py checkpoint --request-id ID [--project-root DIR]

The project root defaults to the current directory; T defaults to now (ISO-8601, UTC). Facts go to
stdout as key=value lines; the exit status is 0 for every state below (2 for wrong arguments).

validation  Prints the validation context as one JSON line, in the Input Format of
            agents/test-validator.md (its validation_criteria arrays are empty there, so they are empty
            here), the validators taken from tests/reports/validator-registry-<ID>.json; the command
            hands that JSON to the validator in its dispatch, so no file is written.
            Prints status=ok|missing_registry, validators, context=<JSON>.
execution   Writes tests/reports/execution-context-<ID>.json in the template of commands/test.md Step 10
            (agents/test-executor.md names that step as the home of its input): the same validators,
            parameters (fail_fast false, verbose true, report_path
            tests/reports/execution-report-<ID>.json) and validation_report (the status and
            validators_checked the command read from the validator's report and passes in, all_valid when
            the status is pass). Prints status=ok|missing_registry, context=<path>, validators,
            validation_status.
checkpoint  Runs hooks/checkpoint.sh "Before /test execution" (a snapshot on refs/checkpoints/<branch>,
            never on HEAD) and records the commit of that ref as context.checkpoint_commit in the
            execution context. Prints checkpoint_exit, checkpoint_ref, checkpoint_commit (none when
            the ref does not exist), rollback_file, rollback_tree (destructive), context=ok|missing.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parents[2]
# The block documents these four arrays as empty: the validator's own Validation Guidelines hold the checks.
VALIDATION_CRITERIA = {"syntax": [], "dependencies": [], "quality": [], "edge_cases": []}


def emit(**facts: object) -> None:
    for key, value in facts.items():
        print(f"{key}={str(value).replace(chr(10), ' ')}")


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path: Path, document: object) -> None:
    """Replace the file whole: a temp file in the same folder, then a rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def registry_validators(root: Path, request_id: str) -> list | None:
    registry = read_json(root / "tests" / "reports" / f"validator-registry-{request_id}.json")
    if not isinstance(registry, dict) or not isinstance(registry.get("validators"), list):
        return None
    keys = ("type", "path", "edge_case", "priority")
    return [{key: item.get(key) for key in keys} for item in registry["validators"] if isinstance(item, dict)]


def base_context(root: Path, request_id: str, timestamp: str, validators: list) -> dict:
    return {
        "request_id": request_id,
        "timestamp": timestamp,
        "context": {
            "project_root": str(root),
            "test_directory": str(root / "tests"),
            "venv_path": str(HARNESS_ROOT / "venv"),
            "validators": validators,
        },
    }


def cmd_validation(root: Path, request_id: str, timestamp: str) -> None:
    validators = registry_validators(root, request_id)
    if validators is None:
        emit(status="missing_registry")
        return
    document = base_context(root, request_id, timestamp, validators)
    document["validation_criteria"] = VALIDATION_CRITERIA
    emit(status="ok", validators=len(validators), context=json.dumps(document, ensure_ascii=False))


def cmd_execution(root: Path, request_id: str, timestamp: str, status: str, checked: int) -> None:
    validators = registry_validators(root, request_id)
    if validators is None:
        emit(status="missing_registry")
        return
    document = base_context(root, request_id, timestamp, validators)
    document["parameters"] = {"fail_fast": False, "verbose": True,
                              "report_path": f"tests/reports/execution-report-{request_id}.json"}
    document["validation_report"] = {"status": status, "validators_checked": checked, "all_valid": status == "pass"}
    target = root / "tests" / "reports" / f"execution-context-{request_id}.json"
    write_json(target, document)
    emit(status="ok", context=target.relative_to(root).as_posix(), validators=len(validators),
         validation_status=status)


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=root, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def checkpoint_ref(root: Path) -> str:
    """The ref hooks/lib/checkpoint-core.sh writes: the branch with / as -, else detached-<short sha>."""
    branch = git(root, "branch", "--show-current")
    if branch:
        return "refs/checkpoints/" + branch.replace("/", "-")
    return "refs/checkpoints/detached-" + (git(root, "rev-parse", "--short", "HEAD") or "empty")


def cmd_checkpoint(root: Path, request_id: str) -> None:
    proc = subprocess.run(["bash", str(HARNESS_ROOT / "hooks" / "checkpoint.sh"), "Before /test execution"],
                          cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, errors="replace")
    sys.stderr.write(proc.stdout)
    ref = checkpoint_ref(root)
    commit = git(root, "rev-parse", "--verify", "--quiet", ref) or "none"
    target = root / "tests" / "reports" / f"execution-context-{request_id}.json"
    document = read_json(target)
    recorded = isinstance(document, dict) and isinstance(document.get("context"), dict)
    if recorded:
        document["context"]["checkpoint_commit"] = commit
        write_json(target, document)
    emit(checkpoint_exit=proc.returncode, checkpoint_ref=ref, checkpoint_commit=commit,
         rollback_file=f"git checkout {ref} -- <path>", rollback_tree=f"git reset --hard {ref}",
         context="ok" if recorded else "missing")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("step", choices=("validation", "execution", "checkpoint"))
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--timestamp")
    parser.add_argument("--validation-status", help="execution: validator.status of the validation report")
    parser.add_argument("--validators-checked", type=int, help="execution: validator.validators_checked of it")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.project_root).resolve()
    timestamp = args.timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if args.step == "validation":
        cmd_validation(root, args.request_id, timestamp)
    elif args.step == "execution":
        if not args.validation_status or args.validators_checked is None:
            parser.error("execution needs --validation-status and --validators-checked")
        cmd_execution(root, args.request_id, timestamp, args.validation_status, args.validators_checked)
    else:
        cmd_checkpoint(root, args.request_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
