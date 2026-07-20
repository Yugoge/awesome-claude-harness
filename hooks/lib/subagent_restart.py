#!/usr/bin/env python3
"""Durable discovery and authorization for quota-interrupted subagent resumes.

Claude Code persists each subagent transcript under the parent session.  This
module treats that persisted transcript as the recovery source of truth: a
restart is allowed only for an agent id that can be bound back to an Agent tool
call in the authenticated parent transcript and that call is missing a terminal
result, was interrupted, or returned a quota/usage-limit result.

The module deliberately does not invoke Claude tools.  ``SendMessage`` remains
model-owned; hooks call the helpers here to authorize the exact recovery
message and to maintain a small, session-keyed recovery journal.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1
GRANT_ISSUER = "UserPromptSubmit:/restart"
MESSAGE_MARKER = "[awesome-claude-harness/restart-v1]"
SESSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
AGENT_RE = re.compile(r"^[A-Za-z0-9._-]{3,160}$")
AGENT_ID_TEXT_RE = re.compile(r"agentId:\s*([A-Za-z0-9._-]+)")
INTERRUPT_RE = re.compile(
    r"request interrupted|interrupted by user|aborterror|aborted|cancelled",
    re.IGNORECASE,
)
QUOTA_RE = re.compile(
    r"you(?:'|’)?ve hit your session limit|session usage limit|"
    r"usage limit (?:has been )?(?:reached|exceeded)|"
    r"(?:anthropic|claude)[^\n]{0,80}rate[-_ ]limit|"
    r"(?:error|code)[\"' :=_-]{0,12}rate_limit|"
    r"resets?\s+(?:at|in)\s+\d",
    re.IGNORECASE,
)
TASK_NOTIFICATION_RE = re.compile(
    r"<task-notification>.*?<task-id>([^<]+)</task-id>.*?"
    r"<status>completed</status>(.*?)</task-notification>",
    re.IGNORECASE | re.DOTALL,
)
COMMAND_NAME_RE = re.compile(r"<command-name>\s*/([^<\s]+)\s*</command-name>", re.IGNORECASE)


class RestartError(RuntimeError):
    """Expected fail-closed recovery error."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _utcnow()).isoformat()


def _safe_session_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not SESSION_RE.fullmatch(session_id):
        raise RestartError("invalid session_id")
    return session_id


def _safe_agent_id(agent_id: str) -> str:
    if not isinstance(agent_id, str) or not AGENT_RE.fullmatch(agent_id):
        raise RestartError("invalid agent_id")
    return agent_id


def grant_dir() -> Path:
    return Path(os.environ.get("CLAUDE_RESTART_GRANT_DIR", "/tmp"))


def state_dir() -> Path:
    override = os.environ.get("CLAUDE_RESTART_STATE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "restart-state"


def grant_path(session_id: str) -> Path:
    sid = _safe_session_id(session_id)
    return grant_dir() / f"claude-restart-grant-{sid}.json"


def state_path(session_id: str) -> Path:
    sid = _safe_session_id(session_id)
    return state_dir() / f"{sid}.json"


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
    except OSError as exc:
        raise RestartError(f"cannot persist restart state at {path}: {exc}") from exc


@contextlib.contextmanager
def _state_lock(session_id: str) -> Iterator[None]:
    path = state_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _parse_time(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def mint_grant(
    session_id: str,
    transcript_path: str,
    project_dir: str,
    *,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """Mint the human-authorized, session-bound recovery capability."""
    sid = _safe_session_id(session_id)
    transcript = Path(transcript_path).expanduser().resolve()
    if transcript.name != f"{sid}.jsonl" or not transcript.is_file():
        raise RestartError("transcript_path is not the current parent session transcript")
    ttl = ttl_seconds or int(os.environ.get("CLAUDE_RESTART_GRANT_TTL_SECONDS", "7200"))
    if ttl < 60 or ttl > 86400:
        raise RestartError("restart grant TTL must be between 60 and 86400 seconds")
    now = _utcnow()
    grant = {
        "schema_version": SCHEMA_VERSION,
        "issued_by": GRANT_ISSUER,
        "session_id": sid,
        "transcript_path": str(transcript),
        "project_dir": str(Path(project_dir).expanduser().resolve()),
        "nonce": secrets.token_hex(24),
        "issued_at": _iso(now),
        "expires_at": _iso(now + timedelta(seconds=ttl)),
    }
    _atomic_write_json(grant_path(sid), grant)
    return grant


def load_valid_grant(session_id: str) -> dict[str, Any]:
    sid = _safe_session_id(session_id)
    grant = _load_json(grant_path(sid))
    if not grant:
        raise RestartError("no authenticated /restart grant for this session")
    if grant.get("schema_version") != SCHEMA_VERSION:
        raise RestartError("restart grant schema mismatch")
    if grant.get("issued_by") != GRANT_ISSUER or grant.get("session_id") != sid:
        raise RestartError("restart grant identity mismatch")
    expires = _parse_time(grant.get("expires_at"))
    if expires is None or expires <= _utcnow():
        raise RestartError("restart grant expired; invoke /restart again")
    transcript = Path(str(grant.get("transcript_path", ""))).expanduser().resolve()
    if transcript.name != f"{sid}.jsonl" or not transcript.is_file():
        raise RestartError("restart grant parent transcript is unavailable")
    grant["transcript_path"] = str(transcript)
    return grant


def _textify(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_textify(item) for item in value)
    if isinstance(value, dict):
        parts: list[str] = []
        for key, item in value.items():
            if key in {"text", "content", "error", "message", "agentId", "agent_id"}:
                parts.append(_textify(item))
        return "\n".join(parts)
    return ""


def _extract_agent_id(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("agentId", "agent_id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and AGENT_RE.fullmatch(candidate):
                return candidate
        for item in value.values():
            found = _extract_agent_id(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _extract_agent_id(item)
            if found:
                return found
    elif isinstance(value, str):
        match = AGENT_ID_TEXT_RE.search(value)
        if match:
            return match.group(1)
    return ""


def _read_parent_calls(
    transcript: Path,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, list[Any]],
    dict[str, dict[str, Any]],
    int,
]:
    calls: dict[str, dict[str, Any]] = {}
    results: dict[str, list[Any]] = {}
    latest_notifications: dict[str, dict[str, Any]] = {}
    human_prompt_lines: list[tuple[int, bool]] = []
    try:
        lines = transcript.open("r", encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RestartError(f"cannot read parent transcript: {exc}") from exc
    with lines:
        for line_no, line in enumerate(lines, 1):
            # Notifications can appear as top-level queue-operation content,
            # message.content, or attachment.prompt. Scan the complete JSONL line
            # before walking message blocks so all three persisted forms count.
            for match in TASK_NOTIFICATION_RE.finditer(line):
                agent_id = match.group(1).strip()
                if AGENT_RE.fullmatch(agent_id):
                    tail = match.group(2)
                    latest_notifications[agent_id] = {
                        "line": line_no,
                        "quota_interrupted": bool(QUOTA_RE.search(tail)),
                    }
            try:
                record = json.loads(line)
            except ValueError:
                continue
            message = record.get("message") if isinstance(record, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str):
                if record.get("type") == "user" and "<task-notification>" not in content:
                    command = COMMAND_NAME_RE.search(content)
                    is_restart = content.strip() == "/restart" or bool(
                        command and command.group(1).lower() == "restart"
                    )
                    human_prompt_lines.append((line_no, is_restart))
                continue
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("name") in {"Agent", "Task"}:
                    tool_id = block.get("id")
                    if isinstance(tool_id, str) and tool_id:
                        tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
                        calls[tool_id] = {
                            "tool_use_id": tool_id,
                            "tool_name": block.get("name"),
                            "line": line_no,
                            "input": tool_input,
                        }
                elif block.get("type") == "tool_result":
                    tool_id = block.get("tool_use_id")
                    if isinstance(tool_id, str) and tool_id:
                        result = dict(block)
                        result["_parent_line"] = line_no
                        results.setdefault(tool_id, []).append(result)

    # Recovery is scoped to the current human request, not every quota event in
    # a long-lived parent transcript. During UserPromptSubmit the /restart line
    # may not be persisted yet; after submission it is the newest human prompt.
    if human_prompt_lines and human_prompt_lines[-1][1]:
        request_boundary = human_prompt_lines[-2][0] if len(human_prompt_lines) > 1 else 0
    else:
        request_boundary = human_prompt_lines[-1][0] if human_prompt_lines else 0
    return calls, results, latest_notifications, request_boundary


def _metadata_by_tool_use(transcript: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    subagent_dir = transcript.with_suffix("") / "subagents"
    try:
        files = list(subagent_dir.glob("agent-*.meta.json"))
    except OSError:
        return result
    for meta_path in files:
        meta = _load_json(meta_path)
        if not meta:
            continue
        tool_id = meta.get("toolUseId")
        if not isinstance(tool_id, str) or not tool_id:
            continue
        name = meta_path.name
        agent_id = name[len("agent-") : -len(".meta.json")]
        if not AGENT_RE.fullmatch(agent_id):
            continue
        result[tool_id] = {
            "agent_id": agent_id,
            "agent_type": meta.get("agentType") if isinstance(meta.get("agentType"), str) else "",
            "description": meta.get("description") if isinstance(meta.get("description"), str) else "",
            "agent_transcript_path": str(subagent_dir / f"agent-{agent_id}.jsonl"),
        }
    return result


def discover_candidates(transcript_path: str | Path) -> list[dict[str, Any]]:
    """Return every recoverable interrupted/quota Agent call in parent order."""
    transcript = Path(transcript_path).expanduser().resolve()
    calls, results, latest_notifications, request_boundary = _read_parent_calls(transcript)
    metadata = _metadata_by_tool_use(transcript)
    candidates: list[dict[str, Any]] = []
    for tool_id, call in sorted(calls.items(), key=lambda item: item[1]["line"]):
        if call["line"] <= request_boundary:
            continue
        result_blocks = results.get(tool_id, [])
        result_text = _textify(result_blocks)
        meta = metadata.get(tool_id, {})
        agent_id = meta.get("agent_id") or _extract_agent_id(result_blocks)
        notification = latest_notifications.get(agent_id, {}) if isinstance(agent_id, str) else {}
        notification_after_call = (
            isinstance(notification.get("line"), int)
            and notification["line"] > call["line"]
        )
        # A normal post-call notification is authoritative evidence that this
        # exact child already came to rest successfully, including after a prior
        # SendMessage resume. A notification whose result is the Claude quota
        # message is an interruption, despite its protocol status="completed".
        if notification_after_call and not notification.get("quota_interrupted"):
            continue
        evidence: list[str] = []
        if not result_blocks:
            evidence.append("missing_parent_tool_result")
        if (result_text and QUOTA_RE.search(result_text)) or (
            notification_after_call and notification.get("quota_interrupted")
        ):
            evidence.append("quota_or_usage_limit")
        if result_text and INTERRUPT_RE.search(result_text):
            evidence.append("interrupted_tool_result")
        tool_input = call.get("input") if isinstance(call.get("input"), dict) else {}
        if (
            tool_input.get("run_in_background") is True
            and isinstance(agent_id, str)
            and not notification_after_call
        ):
            evidence.append("background_without_completion_notification")
        if not evidence:
            continue
        if not isinstance(agent_id, str) or not AGENT_RE.fullmatch(agent_id):
            # A hook-rejected Agent call has no child identity and must never be
            # replaced with a fresh agent: it is not a resumable invocation.
            continue
        description = meta.get("description") or tool_input.get("description") or ""
        agent_type = meta.get("agent_type") or tool_input.get("subagent_type") or ""
        prompt = tool_input.get("prompt") if isinstance(tool_input.get("prompt"), str) else ""
        fingerprint = hashlib.sha256(
            f"{transcript}|{tool_id}|{agent_id}|{prompt}".encode("utf-8", errors="replace")
        ).hexdigest()
        candidates.append({
            "agent_id": agent_id,
            "agent_type": agent_type if isinstance(agent_type, str) else "",
            "description": description if isinstance(description, str) else "",
            "tool_use_id": tool_id,
            "tool_name": call.get("tool_name", "Agent"),
            "parent_line": call.get("line"),
            "agent_transcript_path": meta.get("agent_transcript_path")
            or str(transcript.with_suffix("") / "subagents" / f"agent-{agent_id}.jsonl"),
            "evidence": evidence,
            "fingerprint": fingerprint,
        })
    return candidates


def build_resume_message(session_id: str, agent_id: str) -> str:
    sid = _safe_session_id(session_id)
    aid = _safe_agent_id(agent_id)
    return "\n".join([
        MESSAGE_MARKER,
        f"parent_session_id={sid}",
        f"agent_id={aid}",
        "",
        "Resume this exact existing subagent from its persisted transcript after a quota or session-limit interruption.",
        "First inspect the last tool call/result and current workspace side effects. Do not replay irreversible operations.",
        "Continue only the original single assigned issue; do not broaden scope and do not spawn a replacement agent.",
        "If the original work was already complete, make no duplicate edits and re-emit the terminal report after verification.",
        "If quota blocks again, end with `RECOVERY_STATUS: quota_interrupted`; otherwise end with `RECOVERY_STATUS: completed`.",
    ])


def prepare_state(session_id: str) -> dict[str, Any]:
    sid = _safe_session_id(session_id)
    grant = load_valid_grant(sid)
    discovered = discover_candidates(grant["transcript_path"])
    with _state_lock(sid):
        old = _load_json(state_path(sid)) or {}
        old_items = {
            item.get("agent_id"): item
            for item in old.get("candidates", [])
            if isinstance(item, dict) and isinstance(item.get("agent_id"), str)
        }
        items: list[dict[str, Any]] = []
        for candidate in discovered:
            previous = old_items.get(candidate["agent_id"], {})
            status = previous.get("status")
            if status not in {"response_observed", "dispatched"}:
                status = "pending"
            item = {
                **candidate,
                "status": status,
                "attempts": previous.get("attempts", 0)
                if isinstance(previous.get("attempts", 0), int) else 0,
                "resume_message": build_resume_message(sid, candidate["agent_id"]),
            }
            for key in ("last_dispatched_at", "last_stop_at", "last_message_sha256", "stop_hook_active"):
                if key in previous:
                    item[key] = previous[key]
            items.append(item)
        state = {
            "schema_version": SCHEMA_VERSION,
            "parent_session_id": sid,
            "transcript_path": grant["transcript_path"],
            "project_dir": grant.get("project_dir", ""),
            "grant_issued_at": grant.get("issued_at"),
            "created_at": old.get("created_at") or _iso(),
            "updated_at": _iso(),
            "candidates": items,
        }
        _atomic_write_json(state_path(sid), state)
    return status_view(state)


def _load_state(session_id: str) -> dict[str, Any]:
    sid = _safe_session_id(session_id)
    state = _load_json(state_path(sid))
    if not state or state.get("schema_version") != SCHEMA_VERSION:
        raise RestartError("restart state missing; run prepare first")
    if state.get("parent_session_id") != sid:
        raise RestartError("restart state session mismatch")
    return state


def status_view(state: dict[str, Any]) -> dict[str, Any]:
    candidates = state.get("candidates") if isinstance(state.get("candidates"), list) else []
    public: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        public.append({key: item.get(key) for key in (
            "agent_id", "agent_type", "description", "tool_use_id",
            "agent_transcript_path", "evidence", "status", "attempts", "resume_message",
        )})
    incomplete = [item["agent_id"] for item in public if item.get("status") != "response_observed"]
    return {
        "schema_version": SCHEMA_VERSION,
        "parent_session_id": state.get("parent_session_id"),
        "state_path": str(state_path(str(state.get("parent_session_id")))),
        "candidate_count": len(public),
        "complete": not incomplete,
        "incomplete_agent_ids": incomplete,
        "candidates": public,
    }


def get_status(session_id: str, *, wait_seconds: int = 0, poll_seconds: float = 1.0) -> dict[str, Any]:
    sid = _safe_session_id(session_id)
    deadline = time.monotonic() + max(0, wait_seconds)
    while True:
        view = status_view(_load_state(sid))
        if view["complete"] or time.monotonic() >= deadline:
            return view
        time.sleep(max(0.05, poll_seconds))


def authorize_send_message(payload: dict[str, Any]) -> tuple[bool, str]:
    """Authorize only the exact recovery message to a discovered agent id."""
    if not isinstance(payload, dict):
        return False, "malformed hook payload"
    sid = payload.get("session_id") or payload.get("sessionId") or os.environ.get("CLAUDE_SESSION_ID")
    try:
        sid = _safe_session_id(str(sid or ""))
        grant = load_valid_grant(sid)
        params = payload.get("tool_input") if "tool_input" in payload else payload.get("params")
        if not isinstance(params, dict):
            raise RestartError("SendMessage input is missing")
        agent_id = _safe_agent_id(str(params.get("to") or ""))
        message = params.get("message")
        if message != build_resume_message(sid, agent_id):
            raise RestartError("SendMessage body is not the exact restart-v1 recovery message")
        discovered = {item["agent_id"]: item for item in discover_candidates(grant["transcript_path"])}
        if agent_id not in discovered:
            raise RestartError("target is not a recoverable interrupted subagent in this parent transcript")
        state = _load_state(sid)
        item = next(
            (entry for entry in state.get("candidates", [])
             if isinstance(entry, dict) and entry.get("agent_id") == agent_id),
            None,
        )
        if not item:
            raise RestartError("target is absent from prepared restart state")
        if item.get("status") == "response_observed":
            raise RestartError("target already produced a post-restart response")
        return True, "authenticated /restart recovery"
    except RestartError as exc:
        return False, str(exc)


def mark_dispatched(session_id: str, agent_id: str) -> dict[str, Any]:
    sid = _safe_session_id(session_id)
    aid = _safe_agent_id(agent_id)
    with _state_lock(sid):
        state = _load_state(sid)
        for item in state.get("candidates", []):
            if isinstance(item, dict) and item.get("agent_id") == aid:
                item["status"] = "dispatched"
                item["attempts"] = int(item.get("attempts", 0)) + 1
                item["last_dispatched_at"] = _iso()
                state["updated_at"] = _iso()
                _atomic_write_json(state_path(sid), state)
                return status_view(state)
    raise RestartError("agent is absent from restart state")


def observe_subagent_stop(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Record a resumed agent response; quota responses remain incomplete."""
    if not isinstance(payload, dict):
        return None
    sid = payload.get("session_id") or payload.get("sessionId")
    agent_id = payload.get("agent_id") or payload.get("agentId")
    if not isinstance(sid, str) or not SESSION_RE.fullmatch(sid):
        return None
    if not isinstance(agent_id, str) or not AGENT_RE.fullmatch(agent_id):
        return None
    if not state_path(sid).is_file():
        return None
    last_message = payload.get("last_assistant_message")
    if not isinstance(last_message, str):
        last_message = ""
    with _state_lock(sid):
        state = _load_state(sid)
        for item in state.get("candidates", []):
            if not isinstance(item, dict) or item.get("agent_id") != agent_id:
                continue
            item["status"] = "quota_interrupted" if QUOTA_RE.search(last_message) else "response_observed"
            item["last_stop_at"] = _iso()
            item["last_message_sha256"] = hashlib.sha256(last_message.encode("utf-8")).hexdigest()
            item["stop_hook_active"] = bool(payload.get("stop_hook_active"))
            agent_transcript = payload.get("agent_transcript_path")
            if isinstance(agent_transcript, str) and agent_transcript:
                item["agent_transcript_path"] = agent_transcript
            state["updated_at"] = _iso()
            _atomic_write_json(state_path(sid), state)
            return status_view(state)
    return None


def finalize(session_id: str) -> dict[str, Any]:
    sid = _safe_session_id(session_id)
    view = get_status(sid)
    if not view["complete"]:
        raise RestartError("cannot finalize while recovered agents remain incomplete")
    try:
        grant_path(sid).unlink()
    except FileNotFoundError:
        pass
    return view
