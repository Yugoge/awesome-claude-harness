"""The /codex step's transcript path, docs/codex/<task>/<role>.txt (each name [A-Za-z0-9._-]+, not "." or ".."):
written by scripts/steps/codex-run.py, read by the gitignore preflight as its task's provenance. Stdlib only."""
import os
import re

SAFE_NAME = re.compile(r"[A-Za-z0-9._-]+")


def safe_name(value) -> bool:
    return isinstance(value, str) and SAFE_NAME.fullmatch(value) is not None and value not in (os.curdir, os.pardir)


def transcript_rel(task, role):  # the project-relative path, or None for an unsafe name
    return f"docs/codex/{task}/{role}.txt" if safe_name(task) and safe_name(role) else None


def transcript_task(path):  # the task whose transcript_rel is exactly path, else None
    parts = path.split("/") if isinstance(path, str) else []
    ok = len(parts) == 4 and parts[3].endswith(".txt") and transcript_rel(parts[2], parts[3][:-4]) == path
    return parts[2] if ok else None
