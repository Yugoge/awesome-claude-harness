#!/usr/bin/env python3
"""PreToolUse guard — refuse wholesale replacement of an existing file.

REGISTRATION: matcher ``Bash`` ONLY. This hook registers against no other tool.
``Edit``, ``MultiEdit``, ``NotebookEdit`` and ``Write`` are deliberately and
permanently outside its surface: incremental modification is the legitimate
path, and a guard that fires on ordinary developer work gets switched off — at
which point nothing is protected at all.

WHAT IT DELIVERS, stated without inflation
------------------------------------------
For each Bash tool call, if the command names a REPLACING verb whose target
resolves to an EXISTING REGULAR FILE, that call is refused unless a matching
single-use grant names that exact file — and either outcome is recorded.

That is a syntactic filter over one tool's visible input. It does not cover
multi-step compositions, indirection, or anything that happens inside a
process. The complete uncovered set is enumerated, and DEMONSTRATED by
execution, in ``hooks/tests/fixtures/overwrite_corpus.json`` and documented in
``docs/reference/overwrite-prohibition.md``.

AFFIRMATIVE DENIAL
------------------
The guard denies only when it establishes BOTH (a) a replacing verb and (b) a
target resolving to an existing regular file. Every other state ALLOWS. A
target the guard cannot affirmatively resolve is allowed and declared
uncovered, because denying it would deny CREATION — which must never happen.

FAILURE BEHAVIOUR
-----------------
Bootstrap failure (this guard's own imports) FAILS OPEN, loudly, with an audit
row. A guard that cannot load cannot tell ``2>&1`` from a real replacement, and
failing closed would deny nearly every Bash call in the session — including the
diagnostics needed to repair the guard. The repair path is never sealed: the
edit tools are never gated, appending is never denied, and creating a file that
does not yet exist is never denied.

ATTRIBUTION
-----------
Every refusal AND every grant-permitted replacement appends a structured audit
row. If the append fails, the operation is DENIED on both paths: a replacement
that cannot be attributed must not proceed, because unattributability is
precisely the defect this guard exists to fix.

Exit codes: 0 = allowed (or not our surface), 2 = blocked.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

#: Named in the fail-open warning so an operator can find the broken file.
GUARD_RELPATH = "hooks/pretool-overwrite-guard.py"
AUDIT_RELPATH = "logs/overwrite-guard.jsonl"

_HOOKS_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Bootstrap. Deliberately FAIL OPEN (see module docstring). Note the shared
# lexer is ALSO imported by pretool-tool-policy.py inside a fail-CLOSED
# bootstrap, so making that module unimportable denies every Bash call in the
# session rather than silently disabling this guard. That defence covers IMPORT
# failure only — a lexer that imports cleanly and returns incomplete targets
# degrades this guard silently, and is a declared uncovered route.
# ---------------------------------------------------------------------------
_BOOTSTRAP_ERROR = ""
try:
    if str(_HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(_HOOKS_DIR))
    from lib.allowlist import (  # noqa: E402
        consume_sentinel_grant_on_terminal_result,
        load_sentinel_grant_for_task,
        match_sentinel_grant_for_write,
    )
    from lib.bash_write_targets import (  # noqa: E402
        REPLACING_MODES,
        extract_bash_write_targets_with_modes,
    )
except Exception as exc:  # pragma: no cover - exercised via injected failure
    _BOOTSTRAP_ERROR = f"{type(exc).__name__}: {exc}"

try:  # WS1 shared harness-home resolver; fail-soft, the sink has a fallback.
    from lib import claude_home as _claude_home  # noqa: E402
except Exception:  # pragma: no cover - fail-soft when the resolver is absent
    _claude_home = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Attribution sink
# ---------------------------------------------------------------------------

def audit_log_path() -> Path:
    """Resolve the audit sink via the shared harness-home resolver.

    Order: resolved harness home -> CLAUDE_PROJECT_DIR/.claude -> this hook's
    own parent directory. Never an author literal.
    """
    if _claude_home is not None:
        home = _claude_home.resolve()
        if home is not None:
            return home / AUDIT_RELPATH
        return _claude_home.project_dir() / ".claude" / AUDIT_RELPATH
    return _HOOKS_DIR.parent / AUDIT_RELPATH


def persist_audit_row(row: dict) -> bool:
    """Append one JSONL row with flush + fsync. True iff fully persisted.

    Wrapped in a blanket except so a resolver or filesystem failure degrades to
    a soft False rather than crashing this PreToolUse guard and bypassing its
    block path. A False return DENIES the operation on both the refusal and the
    grant path.
    """
    try:
        path = audit_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return True
    except Exception:
        return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identifiers(payload: dict) -> tuple[str, str]:
    """(session_id, task_id) as carried by the PreToolUse payload."""
    sid = payload.get("session_id") or ""
    task_id = payload.get("task_id") or os.environ.get("CLAUDE_TASK_ID", "") or sid
    return (sid if isinstance(sid, str) else ""), (task_id if isinstance(task_id, str) else "")


# ---------------------------------------------------------------------------
# Target identity
# ---------------------------------------------------------------------------

#: A token carrying any of these is not affirmatively resolvable from command
#: text. Allowed, and the syntax is declared uncovered.
_DYNAMIC_MARKERS = ("$", "`", "*", "?", "[")

#: Process-descriptor aliases name an entry in ANOTHER process's descriptor
#: table, so they carry no stable path identity the guard can judge. This is
#: NOT a list of blessed paths: it never denies anything, and ordinary device
#: targets such as /dev/null are decided by FILE TYPE below, not by name.
_FD_NAMESPACES = ("/dev/fd/", "/proc/self/fd/", "/dev/stdout", "/dev/stderr", "/dev/stdin")


def _payload_cwd(payload: dict) -> str:
    """Effective cwd = payload['cwd'] -> $PWD -> os.getcwd()."""
    value = payload.get("cwd") if isinstance(payload, dict) else None
    if isinstance(value, str) and value:
        return value
    return os.environ.get("PWD", "") or os.getcwd()


def _is_fd_alias(abs_path: str) -> bool:
    if abs_path in _FD_NAMESPACES:
        return True
    if abs_path.startswith("/dev/fd/") or abs_path.startswith("/proc/"):
        parts = abs_path.split("/")
        return "fd" in parts[:4] or abs_path.startswith("/dev/fd/")
    return False


def resolve_identity(token: str, cwd: str) -> str | None:
    """Absolute realpath of `token`, or None when not affirmatively resolvable."""
    if not token:
        return None
    if any(marker in token for marker in _DYNAMIC_MARKERS):
        return None
    candidate = token if os.path.isabs(token) else os.path.join(cwd, token)
    if _is_fd_alias(os.path.normpath(candidate)):
        return None
    try:
        return os.path.realpath(candidate)
    except Exception:
        return None


def _judge(resolved: str, target, cwd: str, depth: int) -> str | None:
    """Return the offending resolved path, or None when the write is allowed."""
    try:
        st = os.stat(resolved)
    except Exception:
        # Does not exist, or existence cannot be established -> CREATION.
        # Creation is never denied, however the path is spelled.
        return None
    if stat.S_ISDIR(st.st_mode):
        # Move-into-a-directory is ordinary, non-destructive work. Re-resolve to
        # <dir>/<basename(source)> and re-apply the table to THAT path; only the
        # resolved collision is refused.
        if depth or not target.source:
            return None
        source = resolve_identity(target.source, cwd)
        if source is None:
            return None
        landed = os.path.realpath(os.path.join(resolved, os.path.basename(source)))
        return _judge(landed, target, cwd, depth + 1)
    if not stat.S_ISREG(st.st_mode):
        # Device, FIFO, socket. Decided by TYPE, not by path string, so
        # `> /dev/null` keeps working without an allowlist of blessed names.
        return None
    return resolved


def offending_targets(command: str, cwd: str) -> list[dict]:
    """Every replacing write in `command` whose target is an existing regular file."""
    offenders: list[dict] = []
    for target in extract_bash_write_targets_with_modes(command):
        if target.mode not in REPLACING_MODES:
            continue  # appending / in-place editing are never gated
        resolved = resolve_identity(target.path, cwd)
        if resolved is None:
            continue
        hit = _judge(resolved, target, cwd, 0)
        if hit is None:
            continue
        offenders.append({
            "resolved_target": hit,
            "mechanism": target.mechanism,
            "write_mode": target.mode,
            "as_written": target.path,
        })
    seen: set[str] = set()
    unique: list[dict] = []
    for off in offenders:  # S1: report every offending target, not just the first
        if off["resolved_target"] in seen:
            continue
        seen.add(off["resolved_target"])
        unique.append(off)
    return unique


# ---------------------------------------------------------------------------
# The authorized escape: the EXISTING single-use sentinel grant, op == "Write"
# ---------------------------------------------------------------------------

def _entry_authorizes(entry: dict, resolved: str) -> bool:
    """True iff this grant entry names THIS file by an explicit absolute target.

    A bare {"op":"Write"} entry is an intentional wildcard for the Write TOOL
    and is preserved there unchanged — but it does NOT authorize shell
    replacement. A relative or absent target does not either: the sentinel
    records no grant-time cwd, so the two sides could not be compared honestly,
    and a grant that silently authorizes nothing is worse than one refused loudly.
    """
    target = entry.get("target") if isinstance(entry, dict) else None
    if not isinstance(target, str) or not target or not os.path.isabs(target):
        return False
    try:
        return os.path.realpath(target) == resolved
    except Exception:
        return False


def grant_for(resolved: str, session_id: str, task_id: str) -> dict | None:
    """Matched grant identity for `resolved`, or None.

    The decision stays with lib/allowlist.py::match_sentinel_grant_for_write —
    no new op name, no new issuance channel, and no modification to the shared
    matcher. Both sides are realpath-normalized before comparison.
    """
    keys: list[str] = []
    for key in (task_id, session_id):
        if key and key not in keys:
            keys.append(key)
    for key in keys:
        entry = match_sentinel_grant_for_write(key, session_id, resolved)
        if entry is not None and _entry_authorizes(entry, resolved):
            return {"task_key": key, "grant_target": entry.get("target")}
        # The grant may spell the SAME identity through a symlink. Re-offer its
        # own literal target to the matcher, but only after confirming that
        # literal realpaths to this exact identity.
        grant = load_sentinel_grant_for_task(key)
        if not isinstance(grant, dict):
            continue
        for candidate in grant.get("allowed_operations") or []:
            if not isinstance(candidate, dict) or candidate.get("op") != "Write":
                continue
            literal = candidate.get("target")
            if not isinstance(literal, str) or not literal or not os.path.isabs(literal):
                continue
            try:
                if os.path.realpath(literal) != resolved:
                    continue
            except Exception:
                continue
            confirmed = match_sentinel_grant_for_write(key, session_id, literal)
            if confirmed is not None and _entry_authorizes(confirmed, resolved):
                return {"task_key": key, "grant_target": confirmed.get("target")}
    return None


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def _deny_message(offenders: list[dict], sink: str) -> str:
    lines = [
        "BLOCKED: wholesale replacement of an existing file "
        f"({GUARD_RELPATH})",
    ]
    for off in offenders:
        lines.append(
            f"  {off['mechanism']} [{off['write_mode']}] -> {off['resolved_target']}"
        )
    lines += [
        "",
        "Incremental modification is never gated. Use one of:",
        "  Edit / MultiEdit      modify the file in place (always allowed)",
        "  >>  or  tee -a        append (always allowed)",
        "  sed -i / patch        in-place edit (always allowed)",
        "  a path that does not exist yet    creation is never denied",
        "  /allow Write <absolute-path>      single-use, audited, human-issued",
        "",
        f"Recorded as decision=refused in {sink}",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entrypoints
# ---------------------------------------------------------------------------

def _fail_open(payload: dict, command: str) -> int:
    """Bootstrap failed: warn loudly, record, and ALLOW."""
    session_id, task_id = _identifiers(payload)
    persist_audit_row({
        "timestamp": _now(),
        "decision": "bootstrap_failed_fail_open",
        "resolved_target": None,
        "mechanism": "bootstrap",
        "grant_identity": None,
        "session_id": session_id,
        "task_id": task_id,
        "guard": GUARD_RELPATH,
        "error": _BOOTSTRAP_ERROR,
        "command_head": command[:200],
    })
    sys.stderr.write(
        f"WARNING: {GUARD_RELPATH} could not load and is FAILING OPEN — "
        "replacement protection is OFF for this call.\n"
        f"  cause: {_BOOTSTRAP_ERROR}\n"
        "  Repair it: the edit tools, appending and new-file creation are never "
        "gated by this guard, so the repair path is open.\n"
    )
    return 0


def _explain(command: str, cwd: str) -> int:
    """C1 self-test entrypoint: show the verdict for a command without acting."""
    if _BOOTSTRAP_ERROR:
        print(f"bootstrap failed: {_BOOTSTRAP_ERROR} (guard would FAIL OPEN)")
        return 0
    for target in extract_bash_write_targets_with_modes(command):
        resolved = resolve_identity(target.path, cwd)
        gated = target.mode in REPLACING_MODES
        hit = _judge(resolved, target, cwd, 0) if (gated and resolved) else None
        verdict = "DENY (unless granted)" if hit else "allow"
        print(f"{target.mechanism:18} {target.mode:18} {target.path} -> "
              f"{resolved or 'unresolvable'} : {verdict}")
    if not extract_bash_write_targets_with_modes(command):
        print("no write target named in this command : allow (declared uncovered)")
    return 0


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--explain":
        return _explain(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else os.getcwd())

    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    if payload.get("tool_name") != "Bash":
        return 0  # matcher Bash only; every edit-tool surface is untouched
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command.strip():
        return 0

    if _BOOTSTRAP_ERROR:
        return _fail_open(payload, command)

    cwd = _payload_cwd(payload)
    try:
        offenders = offending_targets(command, cwd)
    except Exception as exc:
        # An internal fault is a bootstrap-class failure: warn, record, allow.
        sys.stderr.write(
            f"WARNING: {GUARD_RELPATH} failed while classifying and is FAILING "
            f"OPEN: {type(exc).__name__}: {exc}\n"
        )
        session_id, task_id = _identifiers(payload)
        persist_audit_row({
            "timestamp": _now(), "decision": "bootstrap_failed_fail_open",
            "resolved_target": None, "mechanism": "classify",
            "grant_identity": None, "session_id": session_id, "task_id": task_id,
            "guard": GUARD_RELPATH, "error": f"{type(exc).__name__}: {exc}",
            "command_head": command[:200],
        })
        return 0

    if not offenders:
        return 0

    session_id, task_id = _identifiers(payload)
    grants: list[dict] = []
    ungranted: list[dict] = []
    for off in offenders:
        identity = grant_for(off["resolved_target"], session_id, task_id)
        if identity is None:
            ungranted.append(off)
        else:
            off["grant_identity"] = identity
            grants.append(off)

    decision = "refused" if ungranted else "permitted_by_grant"
    consumed = _consume_grants(grants) if decision == "permitted_by_grant" else []
    if decision == "permitted_by_grant" and not consumed:
        decision = "refused_grant_not_consumed"
    sink = str(audit_log_path())
    audit_ok = persist_audit_row({
        "timestamp": _now(),
        "decision": decision,
        "resolved_target": [off["resolved_target"] for off in offenders],
        "mechanism": [off["mechanism"] for off in offenders],
        "write_mode": [off["write_mode"] for off in offenders],
        "grant_identity": [off.get("grant_identity") for off in offenders],
        "grant_consumed": consumed,
        "session_id": session_id,
        "task_id": task_id,
        "guard": GUARD_RELPATH,
        "cwd": cwd,
        "command_head": command[:200],
    })
    if not audit_ok:
        sys.stderr.write(
            f"BLOCKED: {GUARD_RELPATH} could not record this replacement to "
            f"{sink}, so it cannot be attributed afterwards and is DENIED.\n"
            "  An unattributable replacement is the defect this guard exists to "
            "prevent; both the refusal and the granted paths deny on audit failure.\n"
        )
        return 2

    if decision == "permitted_by_grant":
        sys.stderr.write(
            f"[overwrite-guard] permitted_by_grant: "
            f"{', '.join(off['resolved_target'] for off in grants)} — grant CONSUMED "
            f"({', '.join(consumed)}), recorded in {sink}\n"
        )
        return 0

    if decision == "refused_grant_not_consumed":
        sys.stderr.write(
            f"BLOCKED: {GUARD_RELPATH} matched a grant it could not consume, so the "
            "replacement could not be made single-use and is DENIED.\n"
            "  Either another call consumed the same grant first, or the grant file "
            "could not be removed. Re-issue the grant to retry.\n"
        )
        return 2

    sys.stderr.write(_deny_message(ungranted, sink))
    return 2


if __name__ == "__main__":
    sys.exit(main())
