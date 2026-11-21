#!/usr/bin/env python3
"""PostToolUse:Agent observability hook.

Records the yield of a specialist's report in an overnight cycle.
A specialist dispatch is one whose own obligation declares a
specialist-report.v1 report: the hook classifies the produced report and
records the yield via ``lib.specialist_yield``.

HARD CUTOVER: when no overnight-state-*.json or cycle-contract.json is
present (legacy /spec, single-shot /dev sessions) the hook exits 0
immediately so it never blocks.

Fail-soft: ANY exception is swallowed and reported on stderr. Exit code
is always 0 -- this hook is observability, never a gate.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Make sibling lib importable regardless of cwd.
_HOOKS_DIR = Path(__file__).resolve().parent
if str(_HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOKS_DIR))

from lib.subagent import DISPATCH_TOOLS  # noqa: E402

try:
    from lib.specialist_yield import classify_report, record_yield  # noqa: E402
except Exception:  # pragma: no cover - fail-soft if lib missing
    classify_report = None  # type: ignore[assignment]
    record_yield = None  # type: ignore[assignment]

try:
    from lib.contract_runtime import load_contract  # noqa: E402
except Exception:  # pragma: no cover
    load_contract = None  # type: ignore[assignment]

try:
    from lib import claude_home  # noqa: E402  (shared WS1 resolver)
except Exception:  # pragma: no cover - fail-soft if lib missing
    claude_home = None  # type: ignore[assignment]

try:
    from lib import overnight  # noqa: E402
except Exception:  # pragma: no cover - fail-soft if lib missing
    overnight = None  # type: ignore[assignment]

try:
    from lib.obligation import ParsedObligation, parse_obligation  # noqa: E402
except Exception:  # pragma: no cover - fail-soft if lib missing
    parse_obligation = None  # type: ignore[assignment]


# Which dispatches are specialists is what their own obligation declares
# (dev-overnight Step 3's template names this schema); no role list says so.
SPECIALIST_REPORT_SCHEMA = "specialist-report.v1"


# ---------------------------------------------------------------------------
# stdin + project-dir helpers
# ---------------------------------------------------------------------------


def _read_stdin_json() -> dict:
    try:
        if sys.stdin.isatty():
            return {}
        return json.load(sys.stdin)
    except Exception:
        return {}


def _project_dir() -> Path:
    # WS1: resolve via the shared claude_home resolver (CLAUDE_PROJECT_DIR ->
    # harness home -> cwd), never the author literal /root.
    if claude_home is not None:
        return claude_home.project_dir()
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def _try_load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# session/cycle resolution
# ---------------------------------------------------------------------------


def _scan_state_dir(claude_dir: Path, session_id: str) -> dict | None:
    for path in sorted(claude_dir.glob("overnight-state-*.json")):
        data = _try_load_json(path)
        if data is None:
            continue
        if not session_id or data.get("session_id") == session_id:
            return data
    return None


def _read_overnight_state(project_dir: Path, session_id: str) -> dict | None:
    """Return the matching overnight-state-*.json contents, or None."""
    claude_dir = project_dir / ".claude"
    if not claude_dir.is_dir():
        return None
    if session_id:
        exact_data = _try_load_json(claude_dir / f"overnight-state-{session_id}.json")
        if exact_data is not None:
            return exact_data
    return _scan_state_dir(claude_dir, session_id)


def _resolve_session_cycle(stdin_ctx: dict) -> tuple[str | None, int | None, dict | None]:
    """Return (session_id, cycle_id, state_dict) from env + state files."""
    session_id = stdin_ctx.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or ""
    state = _read_overnight_state(_project_dir(), session_id)
    if state is None:
        return (session_id or None, None, None)
    sid = session_id or state.get("session_id")
    cid = overnight.cycle_index(state) if overnight is not None else None
    return (sid, cid, state)


# ---------------------------------------------------------------------------
# Field extractors -- all defensive, all fail-safe to None/0/[]
# ---------------------------------------------------------------------------


def _agent_type(stdin_ctx: dict) -> str | None:
    tool_input = stdin_ctx.get("tool_input") or {}
    if isinstance(tool_input, dict):
        st = tool_input.get("subagent_type")
        if isinstance(st, str) and st:
            return st
    return None


def _tool_response(stdin_ctx: dict) -> dict | None:
    tr = stdin_ctx.get("tool_response")
    return tr if isinstance(tr, dict) else None


def _looks_like_artifact(token: str) -> bool:
    if "/" not in token:
        return False
    if "/docs/" not in token and "/.claude/" not in token:
        return False
    return token.endswith((".json", ".md", ".jsonl", ".py"))


def _artifact_paths_from_response(tool_response: dict | None) -> list[str]:
    if not isinstance(tool_response, dict):
        return []
    out = tool_response.get("output") or tool_response.get("text") or ""
    if not isinstance(out, str) or not out:
        return []
    seen: set[str] = set()
    unique: list[str] = []
    for token in out.split():
        stripped = token.strip().strip(",.;:'\"()[]")
        if not _looks_like_artifact(stripped):
            continue
        if stripped not in seen:
            seen.add(stripped)
            unique.append(stripped)
    return unique


# ---------------------------------------------------------------------------
# Specialist yield
# ---------------------------------------------------------------------------


def _pick_report_path(artifacts: list[str]) -> str | None:
    json_artifacts = [p for p in artifacts if isinstance(p, str) and p.endswith(".json")]
    if json_artifacts:
        return json_artifacts[0]
    if artifacts and isinstance(artifacts[0], str):
        return artifacts[0]
    return None


def _declares_specialist_report(stdin_ctx: dict) -> bool:
    ti = stdin_ctx.get("tool_input") or {}
    prompt = ti.get("prompt") if isinstance(ti, dict) else None
    if parse_obligation is None or not isinstance(prompt, str):
        return False
    parsed = parse_obligation(prompt)
    return isinstance(parsed, ParsedObligation) and any(
        isinstance(art, dict) and art.get("schema") == SPECIALIST_REPORT_SCHEMA
        for art in parsed.obligation.get("artifacts") or []
    )


def _maybe_record_yield(stdin_ctx: dict, session_id: str, cycle_id: int) -> None:
    """If this Agent was a specialist, classify+record its report."""
    agent_type = _agent_type(stdin_ctx)
    if not _declares_specialist_report(stdin_ctx):
        return
    if classify_report is None or record_yield is None:
        return
    artifacts = _artifact_paths_from_response(_tool_response(stdin_ctx))
    report_path = _pick_report_path(artifacts) if artifacts else None
    if not report_path:
        return
    try:
        classification = classify_report(report_path)
        record_yield(
            report_path, agent_type, session_id, cycle_id, classification, "active"
        )
    except Exception as exc:  # pragma: no cover - fail-soft
        sys.stderr.write(
            f"[posttool-overnight-trace] yield record failed: {exc}\n"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _resolve_contract(sid: str, cid: int) -> dict | None:
    if load_contract is None:
        return None
    try:
        return load_contract(sid, cid)
    except Exception:
        return None


def _process(stdin_ctx: dict) -> None:
    tool_name = stdin_ctx.get("tool_name") or ""
    if tool_name and tool_name not in DISPATCH_TOOLS:
        return
    sid, cid, state = _resolve_session_cycle(stdin_ctx)
    if state is None or sid is None or cid is None:
        return
    if _resolve_contract(sid, cid) is None:
        return
    _maybe_record_yield(stdin_ctx, sid, cid)


def main() -> int:
    try:
        stdin_ctx = _read_stdin_json()
        if isinstance(stdin_ctx, dict):
            _process(stdin_ctx)
    except Exception as exc:  # pragma: no cover - fail-soft observability
        sys.stderr.write(
            f"[posttool-overnight-trace] fail-soft error: {exc}\n"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
