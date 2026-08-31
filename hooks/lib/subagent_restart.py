#!/usr/bin/env python3
"""Durable discovery and authorization for quota-interrupted subagent resumes.

Claude Code persists each subagent transcript under the parent session.  This
module treats that persisted transcript as the recovery source of truth: a
restart is allowed only for an agent id that can be bound back to an Agent tool
call in the bound parent transcript and that call is missing a terminal
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
import tempfile
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


GRANT_SCHEMA_VERSION = 1
STATE_SCHEMA_VERSION = 2
AUDIT_SCHEMA_VERSION = 1
# Backward-compatible public alias: state artifacts, not grants, use this value.
SCHEMA_VERSION = STATE_SCHEMA_VERSION
GRANT_ISSUER = "UserPromptSubmit:/restart"
AUDIT_ISSUER = "UserPromptSubmit:/restart-confirm-unrecoverable"
MESSAGE_MARKER = "[awesome-claude-harness/restart-v1]"
SESSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
AGENT_RE = re.compile(r"^[A-Za-z0-9._-]{3,160}$")
TOOL_ID_RE = re.compile(r"^[A-Za-z0-9._-]{3,200}$")
AUDIT_ID_RE = re.compile(r"^[0-9a-f]{64}$")
JSON_ARRAY_INDEX_RE = re.compile(r"^(?:0|[1-9][0-9]*)$")
AGENT_ID_TEXT_RE = re.compile(r"agentId:\s*([A-Za-z0-9._-]{3,160})")
MODEL_WORD = r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}"
MODEL_LABEL = rf"{MODEL_WORD}(?: {MODEL_WORD}){{0,3}}"
DEADLINE = r"[A-Za-z0-9 ,:()./+_-]{1,96}"
NONMODEL_QUOTA_ATOM = (
    r"(?:You've hit your (?:session|weekly) limit|"
    r"(?:session usage limit|usage limit)(?: has been)? (?:reached|exceeded))"
)
MODEL_QUOTA_ATOM = rf"You've reached your {MODEL_LABEL} limit"
QUOTA_ATOM = rf"(?:{NONMODEL_QUOTA_ATOM}|{MODEL_QUOTA_ATOM})"
RESET_SUFFIX = rf"(?:(?: · resets |; resets | — resets ){DEADLINE})"
API_PREFIX = "Agent terminated early due to an API error: "
PARTIAL_MARKER = (
    "Everything below is PARTIAL output recovered from the agent before it was cut off. "
    "The agent did NOT finish its task — treat these results as incomplete."
)
MODEL_LIMIT_NOTICE_RE = re.compile(
    rf"You've reached your (?P<label>{MODEL_LABEL}) limit\. Run /usage-credits to "
    r"continue or switch models with /model\."
)
LEGACY_QUOTA_RE = re.compile(
    rf"(?:{re.escape(API_PREFIX)})?{QUOTA_ATOM}(?:{RESET_SUFFIX})?"
    rf"(?:\. The response above may be incomplete\.)?"
    rf"(?:\nagentId: (?P<agent>{AGENT_RE.pattern[1:-1]})"
    r"(?: \(use SendMessage to continue this agent\))?)?",
    re.IGNORECASE | re.ASCII,
)
NONQUOTA_TRANSPORT_RE = re.compile(
    rf"{re.escape(API_PREFIX)}(?:API Error: (?:Response stalled mid-stream|"
    r"Stream idle timeout - no chunks received|Connection closed mid-response)"
    r"(?:\. The response above may be incomplete\.)?|AbortError(?:[^\r\n]*)?)",
    re.IGNORECASE | re.ASCII,
)
WRAPPED_HEADER_RE = re.compile(
    rf"{re.escape(API_PREFIX)}(?:You've hit your (?:session|weekly) limit"
    rf"{RESET_SUFFIX}|API Error: Connection closed mid-response\. "
    r"The response above may be incomplete\.)",
    re.IGNORECASE | re.ASCII,
)
SEND_TRAILER_RE = re.compile(
    rf"agentId: (?P<agent>{AGENT_RE.pattern[1:-1]}) \(use SendMessage with to: "
    rf"'(?P<target>{AGENT_RE.pattern[1:-1]})', summary: '<5-10 word recap>' to continue this agent\)"
    r"\n<usage>subagent_tokens: [0-9]{1,20}\ntool_uses: [0-9]{1,20}"
    r"\nduration_ms: [0-9]{1,20}</usage>"
)
BACKGROUND_ACK_RE = re.compile(
    rf"Async agent launched successfully\.\nagentId: (?P<agent>{AGENT_RE.pattern[1:-1]})"
)
TERMINAL_STATUSES = {"response_observed", "unrecoverable"}
VALID_V1_STATUSES = {"pending", "dispatched", "quota_interrupted", "response_observed"}
VALID_V2_STATUSES = VALID_V1_STATUSES | {"unrecoverable"}


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
    override = os.environ.get("CLAUDE_RESTART_GRANT_DIR")
    if override:
        return Path(override)
    return state_dir() / "grants"


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


def audit_capability_path(session_id: str, audit_id: str) -> Path:
    sid = _safe_session_id(session_id)
    if not isinstance(audit_id, str) or not AUDIT_ID_RE.fullmatch(audit_id):
        raise RestartError("invalid audit_id")
    return grant_dir() / f"claude-restart-audit-{sid}-{audit_id}.json"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


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
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_suffix(path.suffix + ".lock")
        handle = lock_path.open("a+", encoding="utf-8")
    except OSError as exc:
        raise RestartError(f"cannot open restart state lock: {exc}") from exc
    with handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            raise RestartError(f"cannot lock restart state: {exc}") from exc


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
    *,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """Issue the intended session-bound recovery capability."""
    sid = _safe_session_id(session_id)
    transcript = Path(transcript_path).expanduser().resolve()
    if transcript.name != f"{sid}.jsonl" or not transcript.is_file():
        raise RestartError("transcript_path is not the current parent session transcript")
    try:
        ttl = ttl_seconds or int(os.environ.get("CLAUDE_RESTART_GRANT_TTL_SECONDS", "7200"))
    except (TypeError, ValueError) as exc:
        raise RestartError("restart grant TTL is not an integer") from exc
    if ttl < 60 or ttl > 86400:
        raise RestartError("restart grant TTL must be between 60 and 86400 seconds")
    now = _utcnow()
    grant = {
        "schema_version": GRANT_SCHEMA_VERSION,
        "issued_by": GRANT_ISSUER,
        "session_id": sid,
        "transcript_path": str(transcript),
        "issued_at": _iso(now),
        "expires_at": _iso(now + timedelta(seconds=ttl)),
    }
    _atomic_write_json(grant_path(sid), grant)
    return grant


def load_valid_grant(session_id: str) -> dict[str, Any]:
    sid = _safe_session_id(session_id)
    grant = _load_json(grant_path(sid))
    if not grant:
        raise RestartError("no valid /restart capability for this session")
    if grant.get("schema_version") != GRANT_SCHEMA_VERSION:
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


def _normalize_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("’", "'").strip()


def _simple_result_text(block: dict[str, Any]) -> str | None:
    content = block.get("content")
    if isinstance(content, str):
        return _normalize_text(content)
    if (
        isinstance(content, list)
        and len(content) == 1
        and isinstance(content[0], dict)
        and set(content[0]) == {"type", "text"}
        and content[0].get("type") == "text"
        and isinstance(content[0].get("text"), str)
    ):
        return _normalize_text(content[0]["text"])
    return None


def _task_notification_carriers(record: dict[str, Any]) -> list[str]:
    carriers: list[str] = []
    if record.get("type") == "queue-operation":
        if record.get("operation") in {"enqueue", "remove"}:
            if isinstance(record.get("content"), str):
                carriers.append(record["content"])
    attachment = record.get("attachment")
    if (
        isinstance(attachment, dict)
        and attachment.get("type") == "queued_command"
        and attachment.get("commandMode") == "task-notification"
        and isinstance(attachment.get("prompt"), str)
    ):
        carriers.append(attachment["prompt"])
    message = record.get("message")
    if isinstance(message, dict) and message.get("role") == "user" and isinstance(message.get("content"), str):
        carriers.append(message["content"])
    return carriers


def _parse_notification(carrier: str, line_no: int) -> dict[str, Any] | None:
    text = _normalize_text(carrier)
    match = re.fullmatch(r"<task-notification>(.*)</task-notification>", text, re.DOTALL)
    if not match:
        return None
    body = match.group(1)
    fields: dict[str, str] = {}
    position = 0
    for field in re.finditer(
        r"<(task-id|tool-use-id|status|summary|result)>(.*?)</\1>", body, re.DOTALL
    ):
        if body[position:field.start()].strip() or field.group(1) in fields:
            return None
        fields[field.group(1)] = field.group(2)
        position = field.end()
    if body[position:].strip() or set(fields).difference(
        {"task-id", "tool-use-id", "status", "summary", "result"}
    ):
        return None
    task_id = fields.get("task-id", "").strip()
    status = fields.get("status", "").strip().lower()
    tool_use_id = fields.get("tool-use-id", "").strip()
    if not AGENT_RE.fullmatch(task_id) or status not in {"completed", "stopped", "failed", "killed"}:
        return None
    if tool_use_id and not TOOL_ID_RE.fullmatch(tool_use_id):
        return None
    return {
        "line": line_no,
        "agent_id": task_id,
        "tool_use_id": tool_use_id,
        "status": status,
        "summary": fields.get("summary", ""),
        "result": fields.get("result", ""),
    }


def _read_parent_calls(
    transcript: Path,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    list[dict[str, Any]],
]:
    calls: dict[str, dict[str, Any]] = {}
    results: dict[str, list[dict[str, Any]]] = {}
    notifications: list[dict[str, Any]] = []
    try:
        lines = transcript.open("r", encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RestartError(f"cannot read parent transcript: {exc}") from exc
    with lines:
        for line_no, line in enumerate(lines, 1):
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            for carrier in _task_notification_carriers(record):
                notification = _parse_notification(carrier, line_no)
                if notification:
                    notifications.append(notification)
            message = record.get("message") if isinstance(record, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str):
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
                        outer = record.get("toolUseResult")
                        result["_outer_tool_use_result"] = outer if isinstance(outer, dict) else None
                        results.setdefault(tool_id, []).append(result)

    return calls, results, notifications


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
        previous = result.get(tool_id)
        if previous and previous.get("agent_id") != agent_id:
            previous["identity_conflict"] = True
            continue
        result[tool_id] = {
            "agent_id": agent_id,
            "agent_type": meta.get("agentType") if isinstance(meta.get("agentType"), str) else "",
            "description": meta.get("description") if isinstance(meta.get("description"), str) else "",
            "agent_transcript_path": str(subagent_dir / f"agent-{agent_id}.jsonl"),
        }
    return result


def _result_identity(block: dict[str, Any], meta: dict[str, Any]) -> tuple[str, bool]:
    identities: set[str] = set()
    meta_id = meta.get("agent_id")
    if isinstance(meta_id, str) and AGENT_RE.fullmatch(meta_id):
        identities.add(meta_id)
    outer = block.get("_outer_tool_use_result")
    if isinstance(outer, dict):
        outer_id = outer.get("agentId")
        if isinstance(outer_id, str) and AGENT_RE.fullmatch(outer_id):
            identities.add(outer_id)
    simple = _simple_result_text(block)
    if simple:
        ack = BACKGROUND_ACK_RE.fullmatch(simple)
        quota = LEGACY_QUOTA_RE.fullmatch(simple)
        if ack:
            identities.add(ack.group("agent"))
        if quota and quota.group("agent"):
            identities.add(quota.group("agent"))
        trailer = re.search(r"(?:^|\n)agentId: ([A-Za-z0-9._-]{3,160})(?: \([^\n]*\))?$", simple)
        if trailer:
            identities.add(trailer.group(1))
    content = block.get("content")
    if isinstance(content, list) and len(content) == 3 and isinstance(content[2], dict):
        tail = content[2].get("text")
        if isinstance(tail, str):
            match = SEND_TRAILER_RE.fullmatch(_normalize_text(tail))
            if match:
                identities.update((match.group("agent"), match.group("target")))
    return (next(iter(identities)) if len(identities) == 1 else "", len(identities) > 1 or bool(meta.get("identity_conflict")))


def _partial_recovery_identity(
    block: dict[str, Any], meta: dict[str, Any]
) -> tuple[str, str] | None:
    if "is_error" in block:
        return None
    content = block.get("content")
    if not isinstance(content, list) or len(content) != 3:
        return None
    if any(
        not isinstance(part, dict)
        or set(part) != {"type", "text"}
        or part.get("type") != "text"
        or not isinstance(part.get("text"), str)
        for part in content
    ):
        return None
    first = _normalize_text(content[0]["text"])
    suffix = "\n\n" + PARTIAL_MARKER
    if not first.endswith(suffix) or not WRAPPED_HEADER_RE.fullmatch(first[:-len(suffix)]):
        return None
    trailer = SEND_TRAILER_RE.fullmatch(_normalize_text(content[2]["text"]))
    if not trailer:
        return None
    outer = block.get("_outer_tool_use_result")
    if not isinstance(outer, dict) or outer.get("status") != "completed":
        return None
    ids = {trailer.group("agent"), trailer.group("target"), outer.get("agentId")}
    meta_id = meta.get("agent_id")
    if isinstance(meta_id, str):
        ids.add(meta_id)
    if len(ids) != 1 or meta.get("identity_conflict"):
        return "", "agent_identity_mismatch"
    if outer.get("content") != content[:2]:
        return None
    return trailer.group("agent"), "partial_recovery_transport"


def _structured_rate_limit(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("type") == "rate_limit_error" or value.get("code") == "rate_limit":
            return True
        return any(_structured_rate_limit(item) for item in value.values() if isinstance(item, (dict, list)))
    if isinstance(value, list):
        return any(_structured_rate_limit(item) for item in value)
    return False


def _classify_result(
    block: dict[str, Any], meta: dict[str, Any], *, background: bool
) -> dict[str, Any]:
    line = block.get("_parent_line")
    identity, conflict = _result_identity(block, meta)
    if block.get("toolDenialKind") == "user-rejected" or (isinstance(block.get("_outer_tool_use_result"), dict) and block["_outer_tool_use_result"].get("toolDenialKind") == "user-rejected"):
        return {"state": "terminal", "reason_code": "user_rejected", "line": line, "agent_id": identity}
    simple = _simple_result_text(block)
    ack = BACKGROUND_ACK_RE.fullmatch(simple or "")
    if background and ack:
        return {"state": "active", "reason_code": "background_active", "line": line, "agent_id": ack.group("agent")}
    if block.get("is_error") is False:
        return {"state": "terminal", "reason_code": "foreground_result_success", "line": line, "agent_id": identity}
    partial = _partial_recovery_identity(block, meta)
    if partial:
        partial_id, reason = partial
        return {"state": "terminal" if not partial_id else "interrupted", "reason_code": reason, "line": line, "agent_id": partial_id or identity}
    if conflict:
        return {"state": "terminal", "reason_code": "agent_identity_mismatch", "line": line, "agent_id": ""}
    if block.get("is_error") is True:
        if _structured_rate_limit(block.get("content")) or LEGACY_QUOTA_RE.fullmatch(simple or ""):
            reason = "quota_or_usage_limit"
            state = "interrupted"
        elif NONQUOTA_TRANSPORT_RE.fullmatch(simple or ""):
            reason = "transport_interrupted"
            state = "interrupted"
        else:
            reason = "foreground_result_error"
            state = "terminal"
        return {"state": state, "reason_code": reason, "line": line, "agent_id": identity}
    if simple is not None and LEGACY_QUOTA_RE.fullmatch(simple):
        return {"state": "interrupted", "reason_code": "quota_or_usage_limit", "line": line, "agent_id": identity}
    if simple is None and block.get("content") is None and identity:
        return {"state": "interrupted", "reason_code": "ambiguous_legacy_conservative_resume", "line": line, "agent_id": identity}
    return {"state": "terminal", "reason_code": "legacy_foreground_result_success", "line": line, "agent_id": identity}


def _recoverable_notification_summary(summary: str) -> str | None:
    match = re.fullmatch(r'Agent "[^"<>\r\n]{1,240}" failed: (.*)', _normalize_text(summary), re.DOTALL)
    if not match:
        return None
    remainder = match.group(1)
    if remainder.startswith(API_PREFIX) and MODEL_LIMIT_NOTICE_RE.fullmatch(remainder[len(API_PREFIX):]):
        return "model_limit"
    nonmodel = re.compile(
        rf"{re.escape(API_PREFIX)}{NONMODEL_QUOTA_ATOM}(?:{RESET_SUFFIX})?"
        r"(?:\. The response above may be incomplete\.)?",
        re.IGNORECASE | re.ASCII,
    )
    if nonmodel.fullmatch(remainder) or NONQUOTA_TRANSPORT_RE.fullmatch(remainder):
        return "transport"
    return None


def _classify_notification(notification: dict[str, Any]) -> tuple[str, str]:
    status = notification["status"]
    summary = _normalize_text(str(notification.get("summary", "")))
    if re.fullmatch(r'Agent "[^"<>\r\n]{1,240}" (?:was stopped by user|came to rest \(stopped by user\))', summary):
        return "terminal", "notification_killed_user_stopped"
    if status == "completed":
        if LEGACY_QUOTA_RE.fullmatch(_normalize_text(str(notification.get("result", "")))):
            return "interrupted", "quota_or_usage_limit"
        return "terminal", "notification_completed"
    if status == "stopped":
        return "terminal", "notification_stopped"
    recoverable = _recoverable_notification_summary(summary)
    if status == "failed":
        if recoverable == "model_limit":
            return "interrupted", "notification_failed_model_limit"
        if recoverable:
            return "interrupted", "notification_failed_transport"
        return "terminal", "notification_failed_terminal"
    if recoverable:
        return "interrupted", "notification_killed_transport"
    return "terminal", "notification_killed_unrecognized"


def discover_candidates(transcript_path: str | Path) -> list[dict[str, Any]]:
    """Return every recoverable interrupted/quota Agent call in parent order."""
    transcript = Path(transcript_path).expanduser().resolve()
    calls, results, notifications = _read_parent_calls(transcript)
    metadata = _metadata_by_tool_use(transcript)
    candidates: list[dict[str, Any]] = []
    call_agent_ids: dict[str, str] = {}
    for tool_id, call in calls.items():
        blocks = results.get(tool_id, [])
        found = metadata.get(tool_id, {}).get("agent_id", "")
        for block in blocks:
            candidate_id, conflict = _result_identity(block, metadata.get(tool_id, {}))
            if conflict:
                found = ""
                break
            found = found or candidate_id
        if isinstance(found, str) and AGENT_RE.fullmatch(found):
            call_agent_ids[tool_id] = found
    agent_calls: dict[str, list[str]] = {}
    for tool_id, agent_id in call_agent_ids.items():
        agent_calls.setdefault(agent_id, []).append(tool_id)
    for tool_id, call in sorted(calls.items(), key=lambda item: item[1]["line"]):
        result_blocks = results.get(tool_id, [])
        meta = metadata.get(tool_id, {})
        tool_input = call.get("input") if isinstance(call.get("input"), dict) else {}
        is_background = tool_input.get("run_in_background") is True
        classification = {
            "state": "active" if is_background else "interrupted",
            "reason_code": "background_active" if is_background else "missing_parent_tool_result",
            "source": "missing_result",
            "event_line": call["line"],
        }
        agent_id = call_agent_ids.get(tool_id, "")
        events: list[tuple[int, str, dict[str, Any]]] = [
            (int(block.get("_parent_line", 0)), "result", block) for block in result_blocks
        ]
        for notification in notifications:
            if notification["line"] <= call["line"]:
                continue
            bound = notification.get("tool_use_id") == tool_id if notification.get("tool_use_id") else (
                notification.get("agent_id") == agent_id
                and len(agent_calls.get(str(agent_id), [])) == 1
            )
            if bound and notification.get("agent_id") == agent_id:
                events.append((notification["line"], "notification", notification))
        for _, event_type, event in sorted(events, key=lambda value: value[0]):
            if classification["state"] == "terminal":
                break
            if event_type == "result":
                reduced = _classify_result(event, meta, background=is_background)
                agent_id = reduced.get("agent_id") or agent_id
                state, reason, line = reduced["state"], reduced["reason_code"], reduced["line"]
            else:
                state, reason = _classify_notification(event)
                line = event["line"]
            classification = {
                "state": state, "reason_code": reason,
                "source": "parent_tool_result" if event_type == "result" else "task_notification",
                "event_line": line,
            }
        if classification["state"] != "interrupted" or not AGENT_RE.fullmatch(str(agent_id)):
            continue
        description = meta.get("description") or tool_input.get("description") or ""
        agent_type = meta.get("agent_type") or tool_input.get("subagent_type") or ""
        classification["identity"] = {
            "parent_session_id": transcript.stem,
            "tool_use_id": tool_id,
            "agent_id": agent_id,
        }
        candidates.append({
            "agent_id": agent_id,
            "agent_type": agent_type if isinstance(agent_type, str) else "",
            "description": description if isinstance(description, str) else "",
            "tool_use_id": tool_id,
            "tool_name": call.get("tool_name", "Agent"),
            "parent_line": call.get("line"),
            "interruption_line": classification["event_line"],
            "agent_transcript_path": meta.get("agent_transcript_path")
            or str(transcript.with_suffix("") / "subagents" / f"agent-{agent_id}.jsonl"),
            "evidence": [classification["reason_code"]],
            "classification": classification,
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


def _read_state_document(session_id: str, *, allow_missing: bool = False) -> dict[str, Any]:
    sid = _safe_session_id(session_id)
    path = state_path(sid)
    if not path.exists() and allow_missing:
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RestartError("restart state missing; run prepare first") from exc
    except (OSError, ValueError, UnicodeError) as exc:
        raise RestartError("restart state is malformed") from exc
    if not isinstance(state, dict) or state.get("parent_session_id") != sid:
        raise RestartError("restart state session mismatch")
    return state


def _migrate_state_document(state: dict[str, Any], session_id: str) -> tuple[dict[str, Any], bool]:
    if not state:
        return {}, False
    version = state.get("schema_version")
    if type(version) is not int or version not in {GRANT_SCHEMA_VERSION, STATE_SCHEMA_VERSION}:
        raise RestartError("restart state schema mismatch")
    candidates = state.get("candidates")
    if not isinstance(candidates, list):
        raise RestartError("restart state candidates must be a list")
    allowed = VALID_V1_STATUSES if version == GRANT_SCHEMA_VERSION else VALID_V2_STATUSES
    seen: set[tuple[str, str, str]] = set()
    for row in candidates:
        if not isinstance(row, dict):
            raise RestartError("restart state candidate is malformed")
        tool_id, agent_id = row.get("tool_use_id"), row.get("agent_id")
        if not isinstance(tool_id, str) or not TOOL_ID_RE.fullmatch(tool_id):
            raise RestartError("restart state candidate tool_use_id is invalid")
        if not isinstance(agent_id, str) or not AGENT_RE.fullmatch(agent_id):
            raise RestartError("restart state candidate agent_id is invalid")
        if not isinstance(row.get("status"), str) or row.get("status") not in allowed:
            raise RestartError("restart state candidate status is invalid")
        attempts = row.get("attempts", 0)
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
            raise RestartError("restart state candidate attempts is invalid")
        identity = (session_id, tool_id, agent_id)
        if identity in seen:
            raise RestartError("restart state contains a duplicate exact tuple")
        seen.add(identity)
    if version == STATE_SCHEMA_VERSION:
        return state, False
    migrated = json.loads(json.dumps(state))
    migrated["schema_version"] = STATE_SCHEMA_VERSION
    return migrated, True


def migrate_state(session_id: str) -> dict[str, Any]:
    sid = _safe_session_id(session_id)
    with _state_lock(sid):
        state, changed = _migrate_state_document(_read_state_document(sid), sid)
        if changed:
            _atomic_write_json(state_path(sid), state)
    return state


def _load_state(session_id: str) -> dict[str, Any]:
    sid = _safe_session_id(session_id)
    state, changed = _migrate_state_document(_read_state_document(sid), sid)
    if changed:
        raise RestartError("restart state requires prepare migration")
    return state


def _row_identity(session_id: str, row: dict[str, Any]) -> tuple[str, str, str]:
    return session_id, str(row.get("tool_use_id", "")), str(row.get("agent_id", ""))


def _resolve_row(
    state: dict[str, Any], agent_id: str, *, tool_use_id: str | None = None
) -> dict[str, Any]:
    matches = [
        row for row in state.get("candidates", [])
        if isinstance(row, dict) and row.get("agent_id") == agent_id
        and (tool_use_id is None or row.get("tool_use_id") == tool_use_id)
    ]
    if len(matches) != 1:
        raise RestartError("restart identity must resolve to exactly one state row")
    return matches[0]


def classify_send_response(response: Any) -> tuple[str, str]:
    if not isinstance(response, dict):
        return "unknown", "native_send_result_unknown"
    success, status, error = response.get("success"), response.get("status"), response.get("error")
    status_text = status.lower() if isinstance(status, str) else ""
    nonempty_error = bool(error)
    if success is False:
        return "failed", "native_send_returned_false"
    if success is True:
        if not nonempty_error and status_text not in {"failed", "error"}:
            return "sent", "native_send_succeeded"
        return "unknown", "native_send_result_unknown"
    if success is not None:
        return "unknown", "native_send_result_unknown"
    if status_text in {"sent", "success"} and not nonempty_error:
        return "sent", "legacy_native_send_succeeded"
    if status_text in {"failed", "error"} or nonempty_error:
        return "failed", "native_send_failed"
    return "unknown", "native_send_result_unknown"


def _safe_send_scalars(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    safe: dict[str, Any] = {}
    for key in ("success", "status", "message"):
        value = response.get(key)
        if isinstance(value, (bool, int, float)) or value is None:
            safe[key] = value
        elif isinstance(value, str):
            safe[key] = value[:1000]
    return safe


def _apply_send_result(row: dict[str, Any], event_id: str, response: Any) -> bool:
    log = row.setdefault("send_attempt_log", [])
    if not isinstance(log, list):
        raise RestartError("send_attempt_log is malformed")
    if any(isinstance(item, dict) and item.get("send_tool_use_id") == event_id for item in log):
        return False
    outcome, reason = classify_send_response(response)
    log.append({
        "send_tool_use_id": event_id, "outcome": outcome, "reason_code": reason,
        "observed_at": _iso(), "response_sha256": _digest(response),
        **_safe_send_scalars(response),
    })
    row["attempts"] = int(row.get("attempts", 0)) + 1
    if row.get("status") not in TERMINAL_STATUSES:
        row["status"] = "dispatched" if outcome == "sent" else "pending"
        if outcome == "sent":
            row["last_dispatched_at"] = _iso()
            row["interruption_line_at_dispatch"] = row.get("interruption_line")
    return True


def _historical_send_results(transcript: Path, session_id: str) -> list[tuple[str, str, Any]]:
    calls: dict[str, str] = {}
    output: list[tuple[str, str, Any]] = []
    try:
        lines = transcript.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return output
    with lines:
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            message = record.get("message") if isinstance(record, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("name") == "SendMessage":
                    params = block.get("input")
                    event_id = block.get("id")
                    if (
                        isinstance(params, dict)
                        and isinstance(event_id, str)
                        and TOOL_ID_RE.fullmatch(event_id)
                    ):
                        agent_id = params.get("to")
                        if (
                            isinstance(agent_id, str)
                            and AGENT_RE.fullmatch(agent_id)
                            and params.get("message") == build_resume_message(session_id, agent_id)
                        ):
                            calls[event_id] = agent_id
                elif block.get("type") == "tool_result":
                    event_id = block.get("tool_use_id")
                    if not isinstance(event_id, str) or not TOOL_ID_RE.fullmatch(event_id):
                        continue
                    agent_id = calls.get(event_id)
                    if agent_id is None:
                        continue
                    response: Any = record.get("toolUseResult")
                    if not isinstance(response, dict):
                        text = _simple_result_text(block)
                        try:
                            response = json.loads(text or "")
                        except ValueError:
                            response = None
                        if not isinstance(response, dict) or not isinstance(response.get("success"), bool):
                            response = None
                    output.append((agent_id, event_id, response))
    return output


def prepare_state(session_id: str) -> dict[str, Any]:
    sid = _safe_session_id(session_id)
    grant = load_valid_grant(sid)
    discovered = discover_candidates(grant["transcript_path"])
    with _state_lock(sid):
        old, _ = _migrate_state_document(_read_state_document(sid, allow_missing=True), sid)
        old_rows = old.get("candidates", []) if old else []
        old_by_key = {_row_identity(sid, row): row for row in old_rows if isinstance(row, dict)}
        discovered_by_key = {
            (sid, item["tool_use_id"], item["agent_id"]): item for item in discovered
        }
        items: list[dict[str, Any]] = []
        ordered_keys = list(old_by_key) + [key for key in discovered_by_key if key not in old_by_key]
        for key in ordered_keys:
            previous = old_by_key.get(key, {})
            candidate = discovered_by_key.get(key)
            if candidate is None:
                if previous.get("status") in TERMINAL_STATUSES:
                    items.append(previous)
                continue
            status = previous.get("status", "pending")
            if status == "dispatched":
                line = previous.get("interruption_line_at_dispatch")
                if not isinstance(line, int) or candidate["interruption_line"] > line:
                    status = "pending"
            elif status not in TERMINAL_STATUSES:
                status = "pending"
            item = {**previous, **candidate, "status": status}
            item["resume_message"] = build_resume_message(sid, candidate["agent_id"])
            item["attempts"] = previous.get("attempts", 0)
            items.append(item)
        state = {
            **old,
            "schema_version": STATE_SCHEMA_VERSION,
            "parent_session_id": sid,
            "transcript_path": grant["transcript_path"],
            "grant_issued_at": grant.get("issued_at"),
            "created_at": old.get("created_at") or _iso(),
            "updated_at": _iso(),
            "candidates": items,
        }
        for agent_id, event_id, response in _historical_send_results(Path(grant["transcript_path"]), sid):
            try:
                row = _resolve_row(state, agent_id)
            except RestartError:
                continue
            if row.get("status") == "dispatched" and classify_send_response(response)[0] == "failed":
                _apply_send_result(row, event_id, response)
        _atomic_write_json(state_path(sid), state)
    return status_view(state)


def status_view(state: dict[str, Any]) -> dict[str, Any]:
    candidates = state.get("candidates") if isinstance(state.get("candidates"), list) else []
    public: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        public.append({key: item.get(key) for key in (
            "agent_id", "agent_type", "description", "tool_use_id",
            "agent_transcript_path", "evidence", "interruption_line", "status",
            "attempts", "resume_message", "classification", "send_attempt_log",
            "unrecoverable_proposal", "unrecoverable_audit",
        )})
    incomplete = [item["agent_id"] for item in public if item.get("status") not in TERMINAL_STATUSES]
    recovered = [item for item in public if item.get("status") == "response_observed"]
    unrecoverable = [item for item in public if item.get("status") == "unrecoverable"]
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "parent_session_id": state.get("parent_session_id"),
        "state_path": str(state_path(str(state.get("parent_session_id")))),
        "candidate_count": len(public),
        "complete": not incomplete,
        "incomplete_agent_ids": incomplete,
        "recovered_agent_ids": [item["agent_id"] for item in recovered],
        "unrecoverable_agent_ids": [item["agent_id"] for item in unrecoverable],
        "recovered_identities": [
            {key: item.get(key) for key in ("tool_use_id", "agent_id")} for item in recovered
        ],
        "unrecoverable_identities": [
            {key: item.get(key) for key in ("tool_use_id", "agent_id")} for item in unrecoverable
        ],
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
        discovered = [item for item in discover_candidates(grant["transcript_path"]) if item["agent_id"] == agent_id]
        if len(discovered) != 1:
            raise RestartError("target is not a recoverable interrupted subagent in this parent transcript")
        state = _load_state(sid)
        item = _resolve_row(state, agent_id)
        if item.get("tool_use_id") != discovered[0].get("tool_use_id"):
            raise RestartError("target tuple differs from transcript discovery")
        if item.get("status") != "pending":
            raise RestartError("target is not pending; duplicate restart dispatch denied")
        return True, "validated /restart recovery"
    except RestartError as exc:
        return False, str(exc)


def mark_dispatched(
    session_id: str, agent_id: str, *, tool_use_id: str | None = None
) -> dict[str, Any]:
    sid = _safe_session_id(session_id)
    aid = _safe_agent_id(agent_id)
    with _state_lock(sid):
        state = _load_state(sid)
        item = _resolve_row(state, aid, tool_use_id=tool_use_id)
        if item.get("status") in TERMINAL_STATUSES:
            return status_view(state)
        if item.get("status") != "pending":
            raise RestartError("target is not pending; duplicate restart dispatch denied")
        item["status"] = "dispatched"
        item["last_dispatched_at"] = _iso()
        item["interruption_line_at_dispatch"] = item.get("interruption_line")
        state["updated_at"] = _iso()
        _atomic_write_json(state_path(sid), state)
        return status_view(state)


def record_send_result(
    session_id: str,
    agent_id: str,
    send_tool_use_id: str,
    tool_response: Any,
    *,
    tool_use_id: str | None = None,
) -> dict[str, Any]:
    sid, aid = _safe_session_id(session_id), _safe_agent_id(agent_id)
    if not isinstance(send_tool_use_id, str) or not TOOL_ID_RE.fullmatch(send_tool_use_id):
        raise RestartError("SendMessage tool-use id is invalid")
    with _state_lock(sid):
        state = _load_state(sid)
        item = _resolve_row(state, aid, tool_use_id=tool_use_id)
        if item.get("status") in TERMINAL_STATUSES:
            return status_view(state)
        if _apply_send_result(item, send_tool_use_id, tool_response):
            state["updated_at"] = _iso()
            _atomic_write_json(state_path(sid), state)
        return status_view(state)


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
        try:
            item = _resolve_row(state, agent_id)
        except RestartError:
            return None
        if item.get("status") in TERMINAL_STATUSES:
            return status_view(state)
        quota = bool(re.search(r"(?m)^RECOVERY_STATUS: quota_interrupted\s*$", last_message))
        quota = quota or bool(LEGACY_QUOTA_RE.fullmatch(_normalize_text(last_message)))
        item["status"] = "quota_interrupted" if quota else "response_observed"
        item["last_stop_at"] = _iso()
        agent_transcript = payload.get("agent_transcript_path")
        if isinstance(agent_transcript, str) and agent_transcript:
            item["agent_transcript_path"] = agent_transcript
        state["updated_at"] = _iso()
        _atomic_write_json(state_path(sid), state)
        return status_view(state)


def _decode_json_pointer_token(token: str) -> str:
    decoded: list[str] = []
    index = 0
    while index < len(token):
        char = token[index]
        if char != "~":
            decoded.append(char)
            index += 1
            continue
        if index + 1 >= len(token) or token[index + 1] not in {"0", "1"}:
            raise ValueError("invalid JSON pointer escape")
        decoded.append("~" if token[index + 1] == "0" else "/")
        index += 2
    return "".join(decoded)


def _validate_evidence_ref(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"kind", "path", "sha256", "locator"}:
        raise RestartError("evidence reference shape is invalid")
    if value.get("kind") not in {
        "parent_transcript", "child_transcript", "restart_state", "incident_report", "operator_record",
    }:
        raise RestartError("evidence reference kind is invalid")
    raw_path = value.get("path")
    if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
        raise RestartError("evidence path must be absolute")
    path = Path(raw_path).resolve()
    if str(path) != raw_path or not path.is_file() or not os.access(path, os.R_OK):
        raise RestartError("evidence path must be normalized, readable, and regular")
    expected = value.get("sha256")
    if not isinstance(expected, str) or not AUDIT_ID_RE.fullmatch(expected):
        raise RestartError("evidence sha256 is invalid")
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise RestartError("cannot read evidence reference") from exc
    if actual != expected:
        raise RestartError("evidence sha256 mismatch")
    locator = value.get("locator")
    if not isinstance(locator, str):
        raise RestartError("evidence locator is invalid")
    line_match = re.fullmatch(r"line:([1-9][0-9]*)-([1-9][0-9]*)", locator)
    if line_match:
        start, end = map(int, line_match.groups())
        try:
            count = len(path.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeError) as exc:
            raise RestartError("line evidence is not readable UTF-8") from exc
        if start > end or end > count:
            raise RestartError("evidence line locator is out of range")
    elif locator.startswith("json:"):
        try:
            target: Any = json.loads(path.read_text(encoding="utf-8"))
            pointer = locator[5:]
            if pointer and not pointer.startswith("/"):
                raise KeyError
            for raw_token in ([] if pointer == "" else pointer[1:].split("/")):
                token = _decode_json_pointer_token(raw_token)
                if isinstance(target, list):
                    if not JSON_ARRAY_INDEX_RE.fullmatch(token):
                        raise KeyError
                    target = target[int(token)]
                else:
                    target = target[token]
        except (OSError, ValueError, UnicodeError, KeyError, IndexError, TypeError):
            raise RestartError("evidence JSON pointer does not resolve")
    else:
        raise RestartError("evidence locator is invalid")
    return {key: str(value[key]) for key in ("kind", "path", "sha256", "locator")}


def _proposal_body(
    session_id: str, tool_use_id: str, agent_id: str, reason: str, evidence_refs: list[dict[str, str]]
) -> dict[str, Any]:
    return {
        "schema": AUDIT_SCHEMA_VERSION,
        "identity": {
            "parent_session_id": session_id, "tool_use_id": tool_use_id, "agent_id": agent_id,
        },
        "reason": reason,
        "evidence_refs": evidence_refs,
    }


def propose_unrecoverable(
    session_id: str,
    tool_use_id: str,
    agent_id: str,
    reason: str,
    evidence_refs: list[Any],
) -> dict[str, Any]:
    sid, aid = _safe_session_id(session_id), _safe_agent_id(agent_id)
    if not isinstance(tool_use_id, str) or not TOOL_ID_RE.fullmatch(tool_use_id):
        raise RestartError("invalid tool_use_id")
    reason = reason.strip() if isinstance(reason, str) else ""
    if (
        len(reason) < 20
        or len(reason) > 2000
        or any(unicodedata.category(char) == "Cc" for char in reason)
    ):
        raise RestartError("unrecoverable reason must be 20-2000 non-control characters")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        raise RestartError("at least one evidence reference is required")
    refs = [_validate_evidence_ref(value) for value in evidence_refs]
    body = _proposal_body(sid, tool_use_id, aid, reason, refs)
    audit_id = _digest(body)
    with _state_lock(sid):
        state = _load_state(sid)
        row = _resolve_row(state, aid, tool_use_id=tool_use_id)
        if row.get("status") in TERMINAL_STATUSES:
            raise RestartError("unrecoverable proposal requires a nonterminal row")
        current = row.get("unrecoverable_proposal")
        if isinstance(current, dict) and current.get("audit_id") == audit_id:
            proposal = current
        else:
            proposal = {**body, "audit_id": audit_id, "proposed_at": _iso()}
            row["unrecoverable_proposal"] = proposal
            state["updated_at"] = _iso()
            _atomic_write_json(state_path(sid), state)
    return {
        "status": "RESTART_AUDIT_CONFIRMATION_REQUIRED",
        "identity": body["identity"], "reason": reason, "evidence_refs": refs,
        "audit_id": audit_id,
        "confirmation_prompt": f"/restart confirm-unrecoverable {audit_id}",
    }


def _find_proposal(state: dict[str, Any], audit_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    matches = []
    for row in state.get("candidates", []):
        proposal = row.get("unrecoverable_proposal") if isinstance(row, dict) else None
        audit = row.get("unrecoverable_audit") if isinstance(row, dict) else None
        if isinstance(proposal, dict) and proposal.get("audit_id") == audit_id:
            matches.append((row, proposal))
        elif isinstance(audit, dict) and audit.get("audit_id") == audit_id:
            matches.append((row, proposal if isinstance(proposal, dict) else {}))
    if len(matches) != 1:
        raise RestartError("audit_id must resolve to exactly one proposal")
    return matches[0]


def mint_audit_capability(
    session_id: str, audit_id: str, prompt: str, *, ttl_seconds: int | None = None
) -> dict[str, Any]:
    sid = _safe_session_id(session_id)
    if not AUDIT_ID_RE.fullmatch(str(audit_id)):
        raise RestartError("invalid audit_id")
    expected_prompt = f"/restart confirm-unrecoverable {audit_id}"
    if prompt != expected_prompt:
        raise RestartError("audit confirmation prompt mismatch")
    try:
        ttl = ttl_seconds if ttl_seconds is not None else int(
            os.environ.get("CLAUDE_RESTART_AUDIT_TTL_SECONDS", "600")
        )
    except (TypeError, ValueError) as exc:
        raise RestartError("restart audit TTL is not an integer") from exc
    if ttl < 60 or ttl > 3600:
        raise RestartError("restart audit TTL must be between 60 and 3600 seconds")
    with _state_lock(sid):
        state = _load_state(sid)
        row, proposal = _find_proposal(state, audit_id)
        identity = proposal.get("identity")
        body = _proposal_body(sid, row["tool_use_id"], row["agent_id"], proposal.get("reason", ""), proposal.get("evidence_refs", []))
        if row.get("status") in TERMINAL_STATUSES or identity != body["identity"] or _digest(body) != audit_id:
            raise RestartError("audit proposal is not current and nonterminal")
    now = _utcnow()
    capability = {
        "schema_version": AUDIT_SCHEMA_VERSION, "issued_by": AUDIT_ISSUER,
        "session_id": sid, "identity": identity, "audit_id": audit_id,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "issued_at": _iso(now), "expires_at": _iso(now + timedelta(seconds=ttl)),
    }
    _atomic_write_json(audit_capability_path(sid, audit_id), capability)
    return capability


def mark_unrecoverable(session_id: str, audit_id: str) -> dict[str, Any]:
    sid = _safe_session_id(session_id)
    if not AUDIT_ID_RE.fullmatch(str(audit_id)):
        raise RestartError("invalid audit_id")
    with _state_lock(sid):
        state = _load_state(sid)
        row, proposal = _find_proposal(state, audit_id)
        existing = row.get("unrecoverable_audit")
        if row.get("status") == "unrecoverable" and isinstance(existing, dict) and existing.get("audit_id") == audit_id:
            return status_view(state)
        capability = _load_json(audit_capability_path(sid, audit_id))
        expires = _parse_time(capability.get("expires_at")) if capability else None
        body = _proposal_body(sid, row["tool_use_id"], row["agent_id"], proposal.get("reason", ""), proposal.get("evidence_refs", []))
        expected_identity = body["identity"]
        expected_prompt = f"/restart confirm-unrecoverable {audit_id}"
        if (
            not capability or capability.get("schema_version") != AUDIT_SCHEMA_VERSION
            or capability.get("issued_by") != AUDIT_ISSUER or capability.get("session_id") != sid
            or capability.get("audit_id") != audit_id or capability.get("identity") != expected_identity
            or capability.get("prompt_sha256") != hashlib.sha256(expected_prompt.encode("utf-8")).hexdigest()
            or expires is None or expires <= _utcnow() or _digest(body) != audit_id
            or row.get("status") in TERMINAL_STATUSES
        ):
            raise RestartError("valid human audit confirmation capability is required")
        for evidence in body["evidence_refs"]:
            _validate_evidence_ref(evidence)
        marked_at = _iso()
        row["status"] = "unrecoverable"
        row["unrecoverable_audit"] = {
            "audit_id": audit_id, "audited_by": "human-user-via-UserPromptSubmit",
            "reason": body["reason"], "evidence_refs": body["evidence_refs"],
            "marked_at": marked_at,
            "confirmation": {
                "channel": "UserPromptSubmit", "issuer": AUDIT_ISSUER,
                "prompt_sha256": capability["prompt_sha256"], "confirmed_at": marked_at,
            },
        }
        state["updated_at"] = marked_at
        _atomic_write_json(state_path(sid), state)
        try:
            audit_capability_path(sid, audit_id).unlink()
        except FileNotFoundError:
            pass
    return status_view(state)


def finalize(session_id: str) -> dict[str, Any]:
    sid = _safe_session_id(session_id)
    view = get_status(sid)
    if not view["complete"]:
        raise RestartError("cannot finalize while recovered agents remain incomplete")
    try:
        grant_path(sid).unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise RestartError(f"cannot consume restart grant: {exc}") from exc
    return view
