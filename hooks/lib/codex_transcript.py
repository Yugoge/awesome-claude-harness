"""The /codex step's transcript path, docs/codex/<task>/<role>.txt (each name [A-Za-z0-9._-]+, not "." or ".."):
written by scripts/steps/codex-run.py, read by the gitignore preflight as its task's provenance. Stdlib only.

Also <state dir>/codex-unavailable.json, codex is out of quota: written by codex-run.py from a foreground call's
outcome (observe), read by subagentstop-codex-enforce.py (unavailable_until). A failed call whose output ends with
the usage-limit error sets it to the reset time stated (none readable: DEFAULT_SPAN_S, the provider's shortest
limit window; at most MAX_SPAN_S, its weekly one); a call that exits 0 removes it; any other outcome leaves it."""
import json
import os
import re
import time
from datetime import datetime, timezone

from .harness_state_dir import harness_state_dir

SAFE_NAME = re.compile(r"[A-Za-z0-9._-]+")
USAGE_LIMIT = re.compile(r"^ERROR: You[’']ve hit your usage limit\b(?:.*?try again at ([A-Z][a-z]{2}) (\d{1,2})[a-z]{0,2}, "
                         r"(\d{4}),? (\d{1,2}:\d{2} [AP]M))?", re.S | re.M)
DEFAULT_SPAN_S, MAX_SPAN_S = 5 * 3600, 7 * 86400


def unavailable_path():
    return os.path.join(harness_state_dir(), "codex-unavailable.json")


def observe(code, out_file, now=None):  # codex-run.py: a finished foreground call's exit status and its output file
    now = time.time() if now is None else now
    try:
        if code == 0:
            os.unlink(unavailable_path())
            return
        with open(out_file, "rb") as fh:
            fh.seek(max(0, os.fstat(fh.fileno()).st_size - 4096))
            lines = fh.read().decode("utf-8", "replace").strip().splitlines()
        hit = USAGE_LIMIT.search("\n".join(lines[-2:]))  # the error closes the output (the CLI may wrap it once)
        if not hit:
            return
        until = now + DEFAULT_SPAN_S
        if hit.group(1):  # the CLI prints the reset time in the machine's local time
            until = time.mktime(time.strptime(" ".join(hit.groups()), "%b %d %Y %I:%M %p"))
        stamp = datetime.fromtimestamp(min(max(until, now), now + MAX_SPAN_S), timezone.utc).isoformat(timespec="seconds")
        with open(unavailable_path(), "w", encoding="utf-8") as fh:
            json.dump({"until": stamp, "error": hit.group(0)[:300]}, fh)
    except (OSError, ValueError, OverflowError):
        pass


def unavailable_until(now=None):  # the reset time (ISO, UTC) while codex is known to be out of quota, else None
    try:
        with open(unavailable_path(), encoding="utf-8") as fh:
            until = json.load(fh)["until"]
        live = datetime.fromisoformat(until).timestamp() > (time.time() if now is None else now)
        return until if live else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def safe_name(value) -> bool:
    return isinstance(value, str) and SAFE_NAME.fullmatch(value) is not None and value not in (os.curdir, os.pardir)


def transcript_rel(task, role):  # the project-relative path, or None for an unsafe name
    return f"docs/codex/{task}/{role}.txt" if safe_name(task) and safe_name(role) else None


def transcript_task(path):  # the task whose transcript_rel is exactly path, else None
    parts = path.split("/") if isinstance(path, str) else []
    ok = len(parts) == 4 and parts[3].endswith(".txt") and transcript_rel(parts[2], parts[3][:-4]) == path
    return parts[2] if ok else None
