"""Where the /codex step writes a task's consultation transcript: docs/codex/<task>/<role>.txt in the project,
each name matching [A-Za-z0-9._-]+ and neither "." nor "..". scripts/steps/codex-run.py writes there; the gitignore
preflight reads a path of this shape as the provenance of its task, not a work product. Standard library only."""
import os
import re

SAFE_NAME = re.compile(r"[A-Za-z0-9._-]+")


def safe_name(value) -> bool:
    return isinstance(value, str) and SAFE_NAME.fullmatch(value) is not None and value not in (os.curdir, os.pardir)


def transcript_rel(task, role):
    """The project-relative transcript path for task and role, or None when either name is unsafe."""
    return f"docs/codex/{task}/{role}.txt" if safe_name(task) and safe_name(role) else None


def transcript_task(path):
    """The task whose transcript path is (transcript_rel gives exactly it), else None."""
    parts = path.split("/") if isinstance(path, str) else []
    if len(parts) == 4 and parts[3].endswith(".txt") and transcript_rel(parts[2], parts[3][:-4]) == path:
        return parts[2]
    return None
