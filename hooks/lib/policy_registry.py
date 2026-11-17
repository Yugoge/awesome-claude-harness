#!/usr/bin/env python3
"""Tool-policy registry loader and authorization decisions.

Reads the harness ``policies/tool-policy.v1.json`` (resolved via the shared
hooks/lib/claude_home resolver — see WS1) and provides a single
is_allowed(role, tool_name, target_path) entrypoint shared by:
  - pretool-tool-policy.py (canonical enforcement)
  - pretool-subagent-code-block.py (backstop shim)

Fallback contract (baseline behavior; the policy PATH is resolved portably via
claude_home but the absent-policy DECISION is preserved, not tightened):
  - On policy load failure (file missing, parse error), the `dev` role gets
    fail-safe ALLOW (preserves the historical ALLOWED_TYPES = {'dev'} behavior),
    every other role gets fail-CLOSED DENY.
  - On any unexpected exception, return (True, "fail-safe-exception") for the
    dev role, (False, "fail-closed-exception") for others.

Path prefix matching (T1.2 fix for B.11):
  - Targets are normalized via os.path.realpath (collapses symlinks
    such as /root/.claude -> <CLAUDE_PROJECT_DIR>/).
  - Universal allow: prefix '*' always matches.
  - Glob: prefix containing '*' uses fnmatch.fnmatchcase, with a
    trailing '*' auto-appended so '*/docs/dev/foo-' matches any suffix
    after the prefix anchor (e.g. inside any worktree).
  - Absolute anchor (starts with '/'): interpreted as project-root
    anchored, not as a raw substring. For example '/.claude/hooks/'
    becomes '<CLAUDE_PROJECT_DIR>/.claude/hooks/' (plus its realpath
    form) and matches only that path or descendants. This closes the old
    substring-collision bug where an anchor could match merely because
    the same text appeared somewhere inside an unrelated target path.
  - Relative prefix (doesn't start with '/' and contains no '*'):
    falls back to legacy substring containment. New policies should
    always anchor with '/' or '*'; relative prefixes remain only for
    backward compatibility.

Write carve-outs (``write_carveout_prefixes``, policy_version 9):
  - A row may name project-root anchored directories ('/reports/') that its
    role writes although a deny prefix holds them. A target is inside one only
    when its normalised absolute path AND its realpath both lie under the
    directory (under the project's logical path or its realpath, never the
    directory's own realpath), and an existing file there has one hard link.
  - Such a target passes the allow list and the deny prefixes the carve-out
    sits under ('/tests/' for '/tests/reports/'); every other deny prefix
    still applies (_write_denial). A malformed entry carves nothing.
  - ``carveouts=False`` (is_allowed, _check_write_path, _write_denial) judges a
    target as if the row had none: hooks/pretool-tool-policy.py passes it for a
    Bash target that the same command first makes as a link, copy or move
    destination (itself or a directory above it), whose realpath the check
    cannot see before the command runs.
"""

from __future__ import annotations

import fnmatch
import json
import os
import stat
import sys
from typing import Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_home  # noqa: E402  (shared WS1 harness-home resolver)

# Relative path of the tool policy under the resolved harness home. The absolute
# path is resolved at load time via claude_home so a fresh non-root clone (whose
# home is NOT /root/.claude) still finds its own policy.
POLICY_RELPATH = "policies/tool-policy.v1.json"
WRITE_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}
# On policy load failure (missing/unparseable policy) the dev role gets a
# fail-safe ALLOW (historical baseline behavior); every other role fails CLOSED.
# The policy PATH is resolved portably via claude_home (the de-hardcode), but the
# absent-policy DECISION is preserved exactly as baseline — not tightened.
ALLOWED_TYPES_FALLBACK: set[str] = {"dev"}

_CACHE: Optional[dict] = None
_CACHE_LOADED = False


def load_policy() -> Optional[dict]:
    """Read tool-policy.v1.json. Returns dict or None on error.

    The policy path is resolved via the shared claude_home resolver
    (resolve_optional) so the loader never depends on the author's literal
    /root home. A missing home or missing/unparseable file returns None, which
    is_allowed() maps to a fail-safe ALLOW for the dev role and a fail-CLOSED
    DENY for every other role (baseline behavior).
    """
    global _CACHE, _CACHE_LOADED
    if _CACHE_LOADED:
        return _CACHE
    _CACHE_LOADED = True
    policy_path = claude_home.resolve_optional(POLICY_RELPATH)
    if policy_path is None:
        sys.stderr.write(
            f"policy_registry: policy '{POLICY_RELPATH}' not found under the "
            "resolved harness home (or home unresolved)\n"
        )
        _CACHE = None
        return _CACHE
    try:
        with open(policy_path) as f:
            _CACHE = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        sys.stderr.write(f"policy_registry: load failed ({e})\n")
        _CACHE = None
    return _CACHE


def _reset_cache_for_tests() -> None:
    global _CACHE, _CACHE_LOADED
    _CACHE = None
    _CACHE_LOADED = False


def get_role_policy(role: str) -> dict:
    """Return the role's policy dict, or a deny-all fallback."""
    policy = load_policy()
    if not policy:
        return {"allowed_tools": [], "default_action": "deny"}
    roles = policy.get("roles", {})
    return roles.get(
        role,
        {"allowed_tools": [], "default_action": "deny", "_unknown_role": True},
    )


def _entry_matches(entry: str, tool_name: str) -> bool:
    if entry.endswith("*"):
        return tool_name.startswith(entry[:-1])
    return entry == tool_name


def _tool_in_list(tool_name: str, items: list) -> bool:
    """Match tool against a list, supporting `*` wildcard suffix."""
    for entry in items or []:
        if isinstance(entry, str) and _entry_matches(entry, tool_name):
            return True
    return False


def _normalize_target(target: str) -> str:
    """Resolve target to canonical absolute path, collapsing symlinks.

    On any failure (target missing, permission denied), fall back to
    os.path.abspath so policy decisions never crash on non-existent paths
    (e.g. Write to a file that does not exist yet).
    """
    try:
        return os.path.realpath(target)
    except OSError:
        try:
            return os.path.abspath(target)
        except Exception:  # pragma: no cover
            return target


def _glob_match(prefix: str, target_canonical: str) -> bool:
    """fnmatch glob match; conditionally auto-extend trailing '*'.

    Auto-append '*' ONLY when the pattern ends with a prefix marker
    (a trailing '-' for artifact prefixes like '*/docs/dev/qa-report-',
    or a trailing '/' for directory prefixes like '*/docs/dev/overnight/').
    Patterns that end with anything else (e.g., a literal filename like
    '*/cp-state-ba.json') are matched EXACTLY as written, with no
    auto-suffix. This closes the codex-flagged leak where
    '*/cp-state-ba.json' would otherwise match
    '/root/.../cp-state-ba.json.bak' or '/root/.../cp-state-ba.json/evil'.

    Patterns already ending in '*' are passed through untouched.
    """
    if prefix.endswith("*") or prefix.endswith("-") or prefix.endswith("/"):
        pattern = prefix if prefix.endswith("*") else prefix + "*"
    else:
        pattern = prefix
    return fnmatch.fnmatchcase(target_canonical, pattern)


def _project_dir() -> str:
    """Return the logical Claude project dir used for root-anchored policy.

    WS1: resolves via claude_home.project_dir() (CLAUDE_PROJECT_DIR -> resolved
    harness home -> cwd) so the author literal /root is never the default.
    """
    return os.path.abspath(str(claude_home.project_dir()))


def _path_is_prefix(prefix_path: str, target_path: str) -> bool:
    """Boundary-aware filesystem prefix check, never substring containment."""
    try:
        prefix_norm = os.path.normpath(prefix_path)
        target_norm = os.path.normpath(target_path)
    except (TypeError, ValueError):
        return False
    return (
        target_norm == prefix_norm
        or target_norm.startswith(prefix_norm.rstrip(os.sep) + os.sep)
    )


def _absolute_anchor_candidates(prefix: str) -> list[str]:
    """Expand a policy anchor like '/.claude/hooks/' into real path prefixes.

    The policy file uses leading-slash anchors as project-root-relative
    anchors, e.g. '/src/' means '<project>/src/'. Include both logical and
    realpath forms so /root/.claude symlinked into tmpfs remains protected.
    """
    project = _project_dir()
    rel = prefix.lstrip("/")
    logical = os.path.abspath(os.path.join(project, rel))
    candidates = [logical]
    try:
        real = os.path.realpath(logical)
        if real != logical:
            candidates.append(real)
    except OSError:
        pass
    return candidates


def _absolute_anchor_match(prefix: str, target_canonical: str) -> bool:
    """True iff target is under the project-root anchored prefix."""
    return any(
        _path_is_prefix(candidate, target_canonical)
        for candidate in _absolute_anchor_candidates(prefix)
    )


def _prefix_matches(prefix: str, target_canonical: str) -> bool:
    """Boundary-aware prefix match — see module docstring for full rules."""
    if prefix == "*":
        return True
    if "*" in prefix:
        return _glob_match(prefix, target_canonical)
    if prefix.startswith("/"):
        return _absolute_anchor_match(prefix, target_canonical)
    # Relative prefix — interpret as project-root anchored legacy path.
    return _absolute_anchor_match("/" + prefix, target_canonical)


def _candidate_targets(target: str) -> list:
    """Return both the original absolute target and its realpath form.

    Logical path prefixes like '/.claude/specs/' are written against the
    user-facing path, but realpath collapses the
    /root/.claude -> <CLAUDE_PROJECT_DIR>/ symlink at runtime.
    Matching against BOTH forms keeps logical anchors working AND still
    catches escapes that go through the canonical form.
    """
    if not target:
        return []
    abs_t = os.path.abspath(target)
    canonical = _normalize_target(target)
    if abs_t != canonical:
        return [abs_t, canonical]
    return [abs_t]


def _prefix_matches_any_candidate(prefix: str, candidates: list) -> bool:
    for cand in candidates:
        if _prefix_matches(prefix, cand):
            return True
    return False


def _path_in_prefixes(target: Optional[str], prefixes: list) -> bool:
    if not target or not prefixes:
        return False
    candidates = _candidate_targets(target)
    for p in prefixes:
        if isinstance(p, str) and _prefix_matches_any_candidate(p, candidates):
            return True
    return False


def _check_tool_lists(role_pol: dict, tool_name: str) -> Optional[Tuple[bool, str]]:
    if _tool_in_list(tool_name, role_pol.get("denied_tools", [])):
        return (False, f"tool {tool_name} explicitly denied")
    allowed = role_pol.get("allowed_tools", [])
    if allowed and not _tool_in_list(tool_name, allowed):
        return (False, f"tool {tool_name} not in allowed_tools")
    return None


def _carveout_entries(role_pol: dict) -> list:
    """The role's well-formed ``write_carveout_prefixes``: project-root anchors
    of a directory ('/' first and last, no '*', no '.' or '..' segment).
    A malformed entry carves nothing."""
    out = []
    for entry in role_pol.get("write_carveout_prefixes", []) or []:
        if not isinstance(entry, str) or len(entry) < 3 or "*" in entry:
            continue
        if not (entry.startswith("/") and entry.endswith("/")):
            continue
        parts = entry.strip("/").split("/")
        if any(part in ("", ".", "..") for part in parts):
            continue
        out.append(entry)
    return out


def _carveout_roots(entry: str) -> list:
    """A carve-out's directory under the project: its logical path and the same
    relative path under the project's realpath, NEVER the carve-out directory's
    own realpath, so a carve-out that is itself a symlink (tests/reports ->
    tests) carves nothing beyond its own logical tree."""
    project = _project_dir()
    rel = entry.strip("/")
    roots = [os.path.normpath(os.path.join(project, rel))]
    real_root = os.path.normpath(os.path.join(os.path.realpath(project), rel))
    if real_root not in roots:
        roots.append(real_root)
    return roots


def _in_carveout(target: Optional[str], entry: str) -> bool:
    """True iff EVERY form of ``target`` (its normalised absolute path and its
    realpath) lies under the carve-out's directory, and an existing file there
    has one hard link. A '..' that leaves the directory, a symlink anywhere on
    the path that resolves outside it, or a hard link to a file elsewhere
    fails the check."""
    if not target:
        return False
    candidates = _candidate_targets(target)
    roots = _carveout_roots(entry)
    if not all(any(_path_is_prefix(r, c) for r in roots) for c in candidates):
        return False
    try:
        st = os.stat(candidates[-1])
    except OSError:
        return True  # not there yet: a new file under the carve-out
    return not (stat.S_ISREG(st.st_mode) and st.st_nlink > 1)


def _carveout_waives(deny_prefix: str, entry: str) -> bool:
    """A carve-out waives a deny prefix it sits under ('/tests/reports/' under
    '/tests/'), never one that sits under it or beside it."""
    if not isinstance(deny_prefix, str) or "*" in deny_prefix:
        return False
    deny = "/" + deny_prefix.strip("/") + "/"
    return deny != entry and entry.startswith(deny)


def _write_denial(role_pol: dict, target: Optional[str], carveouts: bool = True) -> Optional[str]:
    """The deny-prefix reason for a write target, or None. A target inside one
    of the role's carve-outs (_in_carveout) is judged only by the deny prefixes
    that carve-out does not waive; with ``carveouts`` false no carve-out
    applies (a Bash target its own command re-stages first)."""
    denied_w = role_pol.get("denied_write_path_prefixes", []) or []
    for entry in (_carveout_entries(role_pol) if carveouts else []):
        if _in_carveout(target, entry):
            denied_w = [d for d in denied_w if not _carveout_waives(d, entry)]
            break
    if _path_in_prefixes(target, denied_w):
        return f"write target {target} matches denied_write_path_prefixes"
    return None


def _check_write_path(role_pol: dict, target: Optional[str], carveouts: bool = True) -> Tuple[bool, str]:
    denial = _write_denial(role_pol, target, carveouts)
    if denial is not None:
        return (False, denial)
    if carveouts and any(_in_carveout(target, entry) for entry in _carveout_entries(role_pol)):
        return (True, "ok")
    allowed_w = role_pol.get("allowed_write_path_prefixes", [])
    if allowed_w and "*" not in allowed_w and not _path_in_prefixes(target, allowed_w):
        return (False, f"write target {target} not in allowed_write_path_prefixes")
    return (True, "ok")


def _check_read_path(role_pol: dict, target: Optional[str]) -> Tuple[bool, str]:
    denied_r = role_pol.get("denied_path_prefixes", [])
    if _path_in_prefixes(target, denied_r):
        return (False, f"read target {target} matches denied_path_prefixes")
    return (True, "ok")


def _fail_open_or_closed(role: str, reason: str) -> Tuple[bool, str]:
    # dev gets fail-safe ALLOW on a missing/unparseable policy (ALLOWED_TYPES_
    # FALLBACK = {"dev"}); every other role fails CLOSED. Baseline behavior.
    if role in ALLOWED_TYPES_FALLBACK:
        return (True, f"fail-safe-{reason}")
    return (False, f"fail-closed-{reason}")


def is_allowed(
    role: str, tool_name: str, target_path: Optional[str], carveouts: bool = True
) -> Tuple[bool, str]:
    """Return (allowed: bool, reason: str). See module docstring. With
    ``carveouts`` false the row's write_carveout_prefixes admit nothing."""
    try:
        policy = load_policy()
        if not policy:
            return _fail_open_or_closed(role, "policy-unavailable")
        role_pol = get_role_policy(role)
        if role_pol.get("_unknown_role"):
            return (False, f"unknown role {role}")
        tool_check = _check_tool_lists(role_pol, tool_name)
        if tool_check is not None:
            return tool_check
        if tool_name in WRITE_TOOLS:
            return _check_write_path(role_pol, target_path, carveouts)
        return _check_read_path(role_pol, target_path)
    except Exception as e:  # pragma: no cover
        sys.stderr.write(f"policy_registry: unexpected ({e})\n")
        return _fail_open_or_closed(role, "exception")
