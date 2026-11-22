"""Which paths a dev report declares that are gaps: the one predicate a lane's stop
(hooks/subagentstop-artifact-contract-enforce.py) and the orchestrator's stop
(scripts/resolve-dev-artifact-chain.py, ABSENT_DECLARED_PATH) both apply."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_SHA = re.compile(r"[0-9a-f]{7,64}")


def declared(report: dict) -> list:
    """dev.files_modified + dev.files_created, order kept, each once; a malformed shape
    contributes nothing (the schema check reports it)."""
    dev = report.get("dev") if isinstance(report, dict) else None
    lists = [dev.get(k) for k in ("files_modified", "files_created")] if isinstance(dev, dict) else []
    return list(dict.fromkeys(p for v in lists if isinstance(v, list) for p in v if isinstance(p, str) and p))


def _present(path: Path) -> bool:  # a directory or a symlink, a broken one included, is there
    try:
        return path.exists() or path.is_symlink()
    except OSError:
        return False


def absent(root, report: dict) -> list:
    """The declared paths that are gaps: not on disk, and not known to the repository at
    root as deleted since the report's baseline_head_sha (else HEAD), whether in the working
    tree, in the index or by a commit since (git diff <baseline> against the working tree).
    One git call for all; a path outside root, or a repository git cannot read, knows
    nothing, so the path stays a gap."""
    root = Path(root).resolve()
    # normpath, not resolve: a declared symlink, a broken one included, is itself the path
    missing = {d: Path(os.path.normpath(root / os.path.expanduser(d))) for d in declared(report)}
    missing = {d: p for d, p in missing.items() if not _present(p)}
    inside = {p.relative_to(root).as_posix() for p in missing.values() if p.is_relative_to(root) and p != root}
    base = report.get("baseline_head_sha") if isinstance(report, dict) else None
    deleted = set()
    for rev in dict.fromkeys([base if isinstance(base, str) and _SHA.fullmatch(base) else "HEAD", "HEAD"]):
        if not inside:
            break
        try:
            proc = subprocess.run(["git", "--no-optional-locks", "--literal-pathspecs", "-C", str(root), "diff",
                                   "--relative", "--no-renames", "--name-only", "-z", "--diff-filter=D", rev, "--",
                                   *sorted(inside)], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            break
        if proc.returncode == 0:  # an unresolvable baseline falls back to HEAD
            deleted = {Path(os.path.normpath(root / n)) for n in proc.stdout.split("\0") if n}
            break
    return [d for d, p in missing.items() if p not in deleted]
