#!/usr/bin/env python3
"""claude_home.py — shared "harness home" resolver (python consumable).

Generalizes the in-repo gold-standard fail-closed self-resolution pattern
(pretool-bash-safety.sh:8,83-106) into a single canonical resolver every
security-relevant hook can import instead of hardcoding ``/root`` or inventing
its own resolution.

Resolution contract
-------------------
* PRIMARY: walk upward from the running file's OWN location to the first
  ancestor that matches the STRUCTURAL sentinel SET — ``settings.json`` +
  ``hooks/`` + ``policies/`` + ``scripts/`` present together in the SAME
  directory. It is NEVER keyed on a directory basename of ``.claude`` (the
  author's RAM-disk root is literally named ``dot-claude``).
* Env hints (``CLAUDE_HOME`` then ``HOME``/.claude) are honored ONLY when their
  ``realpath`` equals the script-walk root (so the user-facing symlinked form
  ``~/.claude`` is accepted, but a fragile/empty/wrong ``$HOME`` never overrides
  the structural walk).

Public API (stable interface contract — WS7 and downstream consumers depend on
these names and semantics):

    resolve()                  -> Path | None   (the harness home, or None)
    resolve_required(relpath)  -> Path          (FAIL CLOSED: prints a block
                                                 reason to stderr and
                                                 ``sys.exit(2)`` if the home is
                                                 unresolved OR the file is
                                                 absent — never exit 0/1)
    resolve_optional(relpath)  -> Path | None   (absent sentinel = None, so the
                                                 caller can degrade gracefully)
    project_dir()              -> Path          (CLAUDE_PROJECT_DIR, else the
                                                 resolved home, else cwd —
                                                 never the literal /root)

The split mirrors the shell helper ``require_security_file`` / ``resolve_optional_file``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# The four-member structural sentinel set. ``settings.json`` is a file; the rest
# are directories. All must be present together for a dir to be the harness home.
_SENTINEL_FILE = "settings.json"
_SENTINEL_DIRS = ("hooks", "policies", "scripts")


def _is_sentinel(d: Path) -> bool:
    """True iff ``d`` contains the full structural sentinel set."""
    try:
        return (
            (d / _SENTINEL_FILE).is_file()
            and all((d / sub).is_dir() for sub in _SENTINEL_DIRS)
        )
    except OSError:
        return False


def _walk_up(start: Path) -> Optional[Path]:
    """Return the first sentinel-matching ancestor of (and including) ``start``."""
    try:
        d = start.resolve()
    except OSError:
        return None
    while True:
        if _is_sentinel(d):
            return d
        if d.parent == d:  # filesystem root reached
            return None
        d = d.parent


def _env_hint_candidates() -> list[Path]:
    """CLAUDE_HOME then HOME/.claude, as candidate env hints (validated later)."""
    out: list[Path] = []
    ch = os.environ.get("CLAUDE_HOME")
    if ch:
        out.append(Path(ch))
    home = os.environ.get("HOME")
    if home:
        out.append(Path(home) / ".claude")
    return out


def resolve() -> Optional[Path]:
    """Resolve the harness home (structural walk PRIMARY; env hint validated).

    Returns the resolved :class:`Path` or ``None`` when no structural sentinel
    set can be located. The env hint is honored only when its realpath equals
    the script-walk root (preserving the user-facing symlinked form), otherwise
    it is IGNORED.
    """
    walk_root = _walk_up(Path(__file__).resolve().parent)
    if walk_root is not None:
        try:
            walk_real = walk_root.resolve()
        except OSError:
            walk_real = walk_root
        for hint in _env_hint_candidates():
            if not _is_sentinel(hint):
                continue
            try:
                hint_real = hint.resolve()
            except OSError:
                continue
            if hint_real == walk_real:
                return hint  # honor the (possibly symlinked) user-facing form
        return walk_root

    # No script-walk root (resolver copied out of tree): accept an env hint only
    # if it is itself a structural sentinel. Never fabricate a /root default.
    for hint in _env_hint_candidates():
        if _is_sentinel(hint):
            return hint
    return None


def _block(reason: str) -> None:
    """Emit a fail-closed block reason to stderr and exit 2 (never 0/1)."""
    sys.stderr.write(reason if reason.endswith("\n") else reason + "\n")
    sys.exit(2)


def resolve_required(relpath: str) -> Path:
    """FAIL CLOSED resolution of a REQUIRED security helper/policy.

    Returns the absolute :class:`Path` to ``<home>/<relpath>`` iff the harness
    home resolves AND the file exists. Otherwise writes a block reason to stderr
    and calls ``sys.exit(2)`` — a missing REQUIRED security file must BLOCK with
    the blocking exit status, never silently continue and never a dirty exit 1.
    """
    if not relpath:
        _block("BLOCKED: claude_home FAIL-CLOSED — resolve_required needs a relative path")
    home = resolve()
    if home is None:
        _block(
            "BLOCKED: claude_home FAIL-CLOSED — cannot resolve the harness home "
            "(no structural sentinel set: settings.json + hooks/ + policies/ + "
            f"scripts/) from this hook's location; required security file '{relpath}' "
            "is unreachable. Repair the harness install (run scripts/bootstrap)."
        )
    abs_path = home / relpath
    if not abs_path.exists():
        _block(
            f"BLOCKED: claude_home FAIL-CLOSED — required security file '{relpath}' "
            f"is absent under the resolved harness home '{home}'. Denied "
            "conservatively; repair the harness install."
        )
    return abs_path


def resolve_optional(relpath: str) -> Optional[Path]:
    """Graceful resolution of an OPTIONAL capability file.

    Returns the absolute :class:`Path` if present, else ``None`` (the absent
    sentinel) so the caller can degrade. Never raises and never exits.
    """
    if not relpath:
        return None
    home = resolve()
    if home is None:
        return None
    abs_path = home / relpath
    return abs_path if abs_path.exists() else None


def project_dir() -> Path:
    """Resolve the logical project dir (state), never the author literal /root.

    Order: ``CLAUDE_PROJECT_DIR`` env (authoritative) -> the resolved harness
    home -> the current working directory. This replaces the legacy
    ``os.environ.get("CLAUDE_PROJECT_DIR", "/root")`` author-home default.
    """
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    home = resolve()
    if home is not None:
        return home
    return Path.cwd()


def _main(argv: list[str]) -> int:
    """Tiny CLI so non-python callers/tests can shell out."""
    cmd = argv[1] if len(argv) > 1 else "resolve"
    if cmd == "resolve":
        home = resolve()
        if home is None:
            return 1
        print(home)
        return 0
    if cmd == "require":
        rel = argv[2] if len(argv) > 2 else ""
        print(resolve_required(rel))  # exits 2 internally on absence
        return 0
    if cmd == "optional":
        rel = argv[2] if len(argv) > 2 else ""
        res = resolve_optional(rel)
        if res is None:
            return 1
        print(res)
        return 0
    sys.stderr.write(f"claude_home.py: unknown subcommand '{cmd}' (resolve|require|optional)\n")
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
