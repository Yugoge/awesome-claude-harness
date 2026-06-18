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
    such as /root/.claude -> /dev/shm/dev-workspace/dot-claude/).
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
"""

from __future__ import annotations

import fnmatch
import json
import os
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
    is_allowed() maps to a fail-CLOSED DENY for every role.
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
    /root/.claude -> /dev/shm/dev-workspace/dot-claude/ symlink at runtime.
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


def _check_write_path(role_pol: dict, target: Optional[str]) -> Tuple[bool, str]:
    denied_w = role_pol.get("denied_write_path_prefixes", [])
    if _path_in_prefixes(target, denied_w):
        return (False, f"write target {target} matches denied_write_path_prefixes")
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
    role: str, tool_name: str, target_path: Optional[str]
) -> Tuple[bool, str]:
    """Return (allowed: bool, reason: str). See module docstring."""
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
            return _check_write_path(role_pol, target_path)
        return _check_read_path(role_pol, target_path)
    except Exception as e:  # pragma: no cover
        sys.stderr.write(f"policy_registry: unexpected ({e})\n")
        return _fail_open_or_closed(role, "exception")
