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
import json
import os
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1
GRANT_ISSUER = "UserPromptSubmit:/restart"
MESSAGE_MARKER = "[awesome-claude-harness/restart-v1]"
# Delimiters for the operator's own words. They exist so a resumed agent can
# tell the harness's fixed instruction from its operator's guidance; the
# guidance between them is never escaped or rewritten, so these markers are
# presentation, not a sanitiser.
GUIDANCE_OPEN = "[awesome-claude-harness/restart-v1:operator-guidance]"
GUIDANCE_CLOSE = "[awesome-claude-harness/restart-v1:end-operator-guidance]"
GUIDANCE_NOTE = (
    "The lines between this marker and the closing marker are your operator's "
    "own words for this resume, carried verbatim. They refine the instruction "
    "above; they never replace it."
)
SESSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
AGENT_RE = re.compile(r"^[A-Za-z0-9._-]{3,160}$")
AGENT_ID_TEXT_RE = re.compile(r"agentId:\s*([A-Za-z0-9._-]+)")

# Interruption/quota detection lives in interruption_signals: this module used to
# carry one enumerated phrase list, which silently recovered NOTHING for every
# banner its author had not personally seen ("weekly limit", "529 Overloaded",
# "stalled mid-stream", "did NOT finish" all measured as misses on 2026-09-30).
# The scope word in "You've hit your <SCOPE> limit" is an open set, so that list
# was unwinnable by construction. See that module's docstring for the corpus
# measurement and the three evidence tiers.
try:  # package import (hooks.lib.subagent_restart)
    from . import interruption_signals as signals
except ImportError:  # direct sys.path import (lib/ on path)
    import interruption_signals as signals  # type: ignore[no-redef]


def _is_quota_text(value: Any) -> bool:
    return signals.is_quota_text(_textify(value) if not isinstance(value, str) else value)


def _is_interrupt_text(value: Any) -> bool:
    return signals.is_interrupt_text(_textify(value) if not isinstance(value, str) else value)
NOTIFICATION_OPEN = "<task-notification>"
NOTIFICATION_CLOSE = "</task-notification>"
# Applied to ONE already-delimited notification body (see
# _iter_notification_blocks), never to a whole JSONL line: a line can carry
# several notifications, and a line-wide DOTALL non-greedy scan let a failed
# block's <task-id> bridge across </task-notification> to a LATER block's
# <status>completed</status>, attributing that status and summary to the wrong
# agent and swallowing the real completed block.
#
# All three protocol statuses are recognised. A hard session-limit kill of an
# agent resumed by SendMessage is reported as status=failed with the quota
# banner inside <summary>, and matching only `completed` made that kill
# invisible: the agent's interruption_line never advanced, so prepare_state
# could not re-derive a dispatched candidate back to pending and a second
# /restart was refused. The same blindness recurred with status=stopped ("didn't
# finish before the previous session ended"): when the HOST Claude process exits
# mid-run (account rotation, teardown), the child is structurally incapable of
# still running, yet the unparsed notification left the candidate wedged at
# dispatched and the authorization hook refused the redispatch (2026-09-28,
# agent a8ab56bdd1870882d).
TASK_NOTIFICATION_RE = re.compile(
    r"<task-id>([^<]+)</task-id>.*?<status>(completed|failed|stopped)</status>(.*)",
    re.IGNORECASE | re.DOTALL,
)
# The fixed resume message instructs every resumed agent to end with an explicit
# RECOVERY_STATUS sentinel. That sentinel outranks ALL text-tier quota matching
# when grading the response: an agent reporting ON a quota outage legitimately
# quotes limit banners, and grading such a report by text inverts its meaning
# (docs/reference/restart-detector-quota-text-match-false-positive-20260915.md §2).
RECOVERY_STATUS_RE = re.compile(r"RECOVERY_STATUS:\s*(completed|quota_interrupted)\b")


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


def guidance_path(session_id: str) -> Path:
    """Session-bound sibling of the capability holding the operator's guidance.

    The /restart authorizer persists the operator's argument text here as raw
    UTF-8. The convention lives beside the other capability paths so no caller
    re-derives it.
    """
    sid = _safe_session_id(session_id)
    return grant_dir() / f"claude-restart-args-{sid}.txt"


def load_guidance(session_id: str) -> str | None:
    """Operator guidance persisted for this session, or None when there is none.

    Returns None — never raises — for every way the file can fail to yield
    guidance (absent, unreadable, invalid UTF-8, empty), because guidance is
    purely additive: a session without it must keep the unmodified recovery
    behaviour rather than lose the recovery entirely. Bytes are read raw and
    decoded explicitly instead of through a text-mode read, whose
    universal-newline translation would silently rewrite CRLF the operator
    typed.
    """
    try:
        path = guidance_path(session_id)
    except RestartError:
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        return None
    return text or None


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
        "schema_version": SCHEMA_VERSION,
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


def _iter_notification_blocks(line: str) -> Iterator[str]:
    """Yield each complete task-notification body found on one JSONL line.

    Blocks are sliced by literal tag scanning instead of one line-wide DOTALL
    regex so no field can ever be read across a block boundary, and so a line
    holding an unterminated notification cannot make the matcher backtrack over
    the whole (multi-hundred-KB) line.
    """
    pos = 0
    while True:
        start = line.find(NOTIFICATION_OPEN, pos)
        if start < 0:
            return
        body_start = start + len(NOTIFICATION_OPEN)
        end = line.find(NOTIFICATION_CLOSE, body_start)
        if end < 0:
            return
        nested = line.find(NOTIFICATION_OPEN, body_start)
        if 0 <= nested < end:
            # The outer opener was never closed before a new one began; parse the
            # inner block on its own rather than merging two agents' fields.
            pos = nested
            continue
        yield line[body_start:end]
        pos = end + len(NOTIFICATION_CLOSE)


def _read_parent_calls(
    transcript: Path,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, list[Any]],
    dict[str, dict[str, Any]],
]:
    calls: dict[str, dict[str, Any]] = {}
    results: dict[str, list[Any]] = {}
    latest_notifications: dict[str, dict[str, Any]] = {}
    try:
        lines = transcript.open("r", encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RestartError(f"cannot read parent transcript: {exc}") from exc
    with lines:
        for line_no, line in enumerate(lines, 1):
            # Notifications can appear as top-level queue-operation content,
            # message.content, or attachment.prompt. Scan the complete JSONL line
            # before walking message blocks so all three persisted forms count.
            for block in _iter_notification_blocks(line):
                match = TASK_NOTIFICATION_RE.search(block)
                if not match:
                    continue
                agent_id = match.group(1).strip()
                if AGENT_RE.fullmatch(agent_id):
                    # <status> precedes <summary>, so the post-status tail covers
                    # the failure summary that carries the quota banner.
                    tail = match.group(3)
                    latest_notifications[agent_id] = {
                        "line": line_no,
                        "status": match.group(2).lower(),
                        "quota_interrupted": signals.is_quota_text(tail),
                    }
            try:
                record = json.loads(line)
            except ValueError:
                continue
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
                        results.setdefault(tool_id, []).append(result)

    return calls, results, latest_notifications


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


def _scan_child_transcript(agent_transcript_path: str | Path) -> dict[str, Any]:
    """One pass over ONE COPY of a child transcript for the verdicts it holds.

    Callers want the verdict for a CHILD, not for a copy, and must go through
    _child_transcript_signals: each account root holds only its own partial
    view, so a verdict read from a single copy can be strictly weaker than the
    truth. See _child_transcript_copies.

    Returns ``{"end_turn": bool | None, "api_error": Signal | None,
    "api_error_line": int | None}``.

    ``end_turn``
        True iff the child emitted a terminal end_turn report. ``stop_reason``
        is written by the harness, never by report prose, so an assistant record
        carrying ``stop_reason == "end_turn"`` proves the child reached a natural
        stopping point — including the completed-then-rewoken shape where a later
        resume turn was itself cut off after the report already landed.
        Synthetic quota-abort records carry ``stop_sequence`` (plus
        ``isApiErrorMessage``) and can never satisfy this test. None when the
        transcript is missing or unreadable: liveness is then unknowable and the
        caller must fall back to parent-side evidence rather than silently
        dropping the candidate.

    ``api_error``
        The strongest structural interruption signal among the child's own
        ``isApiErrorMessage`` records. This is the evidence source the detector
        previously lacked entirely: recovery read only the PARENT's prose, so a
        child killed mid-run contributed nothing unless the parent happened to
        phrase the banner in a way the old phrase list recognised. These records
        are machine-written, so they hold for wordings nobody has seen yet.

    Both verdicts come from one read because the caller needs them together and
    child transcripts are large.
    """
    path = Path(agent_transcript_path)
    verdict: dict[str, Any] = {"end_turn": None, "api_error": None, "api_error_line": None}
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return verdict
    end_turn = False
    with handle:
        for line_no, line in enumerate(handle, 1):
            # Cheap substring pre-filters; every hit is structurally verified
            # below, so prose merely quoting these tokens cannot match.
            has_end_turn = '"end_turn"' in line
            has_api_error = "isApiErrorMessage" in line
            if not has_end_turn and not has_api_error:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            if has_api_error:
                signal = signals.classify_record(record)
                if signal is not None:
                    verdict["api_error"] = signals.strongest(
                        (verdict["api_error"], signal)
                    )
                    verdict["api_error_line"] = line_no
            if not has_end_turn or record.get("isApiErrorMessage") is True:
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            if message.get("role") == "assistant" and message.get("stop_reason") == "end_turn":
                end_turn = True
    verdict["end_turn"] = end_turn
    return verdict


def _child_transcript_copies(agent_transcript_path: str | Path) -> list[Path]:
    """Every account root's copy of ONE child transcript, the given path first.

    Separate account logins each persist their own PARTIAL view of one logical
    session, so the copy reachable from the parent transcript's own directory
    can be MISSING records that another account's copy holds (measured
    2026-09-27: inside this project's slug, 28 of 28 same-stem pairs diverge in
    byte size; measured 2026-10-01: three children of session 4758df81 carry
    their terminal end_turn record only in the non-parent root). Paths that sit
    under no known root (synthetic or relocated transcripts) yield just
    themselves, which is the pre-fan-out behaviour.
    """
    path = Path(agent_transcript_path)
    anchor = path.resolve()
    roots = account_project_roots()
    resolved = [root.resolve() for root in roots]
    tail = next((anchor.relative_to(r) for r in resolved if r in anchor.parents), None)
    if tail is None:
        return [path]
    return [path] + [
        root / tail for root, base in zip(roots, resolved) if base / tail != anchor
    ]


def _child_transcript_signals(agent_transcript_path: str | Path) -> dict[str, Any]:
    """Resolve a child's structural verdicts across EVERY copy of its transcript.

    Completion evidence is POSITIVE and MONOTONE: an end_turn record in any one
    copy proves the child finished, while its absence from a partial copy proves
    nothing at all. So the strongest verdict wins -- True from one copy beats
    False from another -- and the structural api_error signal is gathered the
    same way rather than taken from whichever copy the parent happened to sit
    next to. Deriving the verdict from the parent's own directory alone listed
    three already-finished children of session 4758df81 as resumable.

    Fail-toward-recovery is unchanged: end_turn stays None when NO copy is
    readable, so a genuinely cut-off child is still never dropped.
    """
    merged: dict[str, Any] = {"end_turn": None, "api_error": None, "api_error_line": None}
    for copy in _child_transcript_copies(agent_transcript_path):
        verdict = _scan_child_transcript(copy)
        if verdict["end_turn"] is None:
            continue  # this copy is absent/unreadable; it contributes no evidence
        merged["end_turn"] = bool(merged["end_turn"]) or verdict["end_turn"]
        signal = signals.strongest((merged["api_error"], verdict["api_error"]))
        if signal is not None and signal is not merged["api_error"]:
            merged["api_error_line"] = verdict["api_error_line"]
        merged["api_error"] = signal
    return merged


def _child_reported_end_turn(agent_transcript_path: str | Path) -> bool | None:
    """Back-compat wrapper: only the end_turn verdict of the combined scan."""
    return _child_transcript_signals(agent_transcript_path)["end_turn"]


def discover_candidates(transcript_path: str | Path) -> list[dict[str, Any]]:
    """Return every recoverable interrupted/quota Agent call in parent order."""
    transcript = Path(transcript_path).expanduser().resolve()
    calls, results, latest_notifications = _read_parent_calls(transcript)
    metadata = _metadata_by_tool_use(transcript)
    candidates: list[dict[str, Any]] = []
    for tool_id, call in sorted(calls.items(), key=lambda item: item[1]["line"]):
        result_blocks = results.get(tool_id, [])
        result_text = _textify(result_blocks)
        meta = metadata.get(tool_id, {})
        agent_id = meta.get("agent_id") or _extract_agent_id(result_blocks)
        notification = latest_notifications.get(agent_id, {}) if isinstance(agent_id, str) else {}
        notification_after_call = (
            isinstance(notification.get("line"), int)
            and notification["line"] > call["line"]
        )
        # A post-call status=completed notification is authoritative evidence
        # that this exact child already came to rest successfully, including
        # after a prior SendMessage resume. Three shapes must NOT reach that
        # skip: a completed notification whose body carries the Claude quota
        # message (an interruption despite its protocol status), ANY
        # status=failed notification — a failed agent never came to rest, so
        # counting failure as settled would strand exactly the children
        # /restart recovers — and ANY status=stopped notification.
        # A failed notification without quota text adds no evidence of its own
        # either; failure is ambiguous (a transport error can strike an agent
        # whose work still landed), so such a candidate stands or falls on the
        # parent-side evidence below, as it did while failed notifications were
        # unparsed. A stopped notification is NOT ambiguous the same way: it
        # means the host process exited with no completion record, so the child
        # cannot still be running, and it counts as interruption evidence in
        # its own right (below) — subject only to the end_turn structural gate.
        settled = (
            notification.get("status") == "completed"
            and not notification.get("quota_interrupted")
        )
        if notification_after_call and settled:
            continue
        evidence: list[str] = []
        interruption_lines: list[int] = []
        tool_input = call.get("input") if isinstance(call.get("input"), dict) else {}
        is_background = tool_input.get("run_in_background") is True
        if not result_blocks and not is_background:
            evidence.append("missing_parent_tool_result")
            interruption_lines.append(call["line"])
        if (result_text and _is_quota_text(result_text)) or (
            notification_after_call and notification.get("quota_interrupted")
        ):
            evidence.append("quota_or_usage_limit")
            interruption_lines.extend(
                block["_parent_line"] for block in result_blocks
                if isinstance(block.get("_parent_line"), int) and _is_quota_text(block)
            )
            if notification_after_call and notification.get("quota_interrupted"):
                interruption_lines.append(notification["line"])
        if notification_after_call and notification.get("status") == "stopped":
            # Host-process teardown left this child with no completion record;
            # the notification line itself is the interruption point that lets
            # prepare_state re-derive a dispatched candidate back to pending.
            evidence.append("session_teardown_stop")
            interruption_lines.append(notification["line"])
        # Real Agent/Task tool_results set is_error present-only-when-true
        # (never explicit False) on genuine transport/hook errors -- see
        # docs/dev/context-20260808-035658-lanersgap.json corpus measurement.
        # interrupted_tool_result therefore requires is_error is True AND the
        # word-bounded phrase match on the SAME block; there is no
        # is_error-less fallback, and one block's error must never vouch for
        # a different block's unrelated success text.
        interrupted_blocks = [
            block for block in result_blocks
            if block.get("is_error") is True and _is_interrupt_text(block)
        ]
        if interrupted_blocks:
            evidence.append("interrupted_tool_result")
            interruption_lines.extend(
                block["_parent_line"] for block in interrupted_blocks
                if isinstance(block.get("_parent_line"), int)
            )
        # Child identity and the child's OWN structural record are resolved
        # BEFORE the evidence-sufficiency test, because that record is often the
        # only evidence in existence. A hook-rejected Agent call has no child
        # identity and must never be replaced with a fresh agent: it is not a
        # resumable invocation.
        if not isinstance(agent_id, str) or not AGENT_RE.fullmatch(agent_id):
            continue
        agent_transcript_path = meta.get("agent_transcript_path") or str(
            transcript.with_suffix("") / "subagents" / f"agent-{agent_id}.jsonl"
        )
        child = _child_transcript_signals(agent_transcript_path)
        # Structural liveness gate. The parent's Agent tool_result IS the
        # child's own report whenever the child completed, so the textual
        # evidence above cannot distinguish "was quota-interrupted" from
        # "reported on a quota event": 39 of 217 candidates in the measured
        # corpus were clean end_turn reports merely quoting limit banners
        # (docs/reference/restart-detector-quota-text-match-false-positive-
        # 20260915.md §4-5). A child that reached end_turn finished naturally
        # and must never be resumed; an unreadable child transcript (None)
        # keeps the candidate so a genuinely cut-off child is never dropped.
        if child["end_turn"] is True:
            continue
        # Structural interruption evidence, machine-written and prose-free. This
        # is what the enumerated phrase list never had: a background child killed
        # by the API leaves the parent no tool_result to read and no banner to
        # match, so the whole fan-out used to discover zero candidates. The
        # child's own isApiErrorMessage record survives that, and survives
        # banner wordings nobody has seen yet.
        child_signal = child["api_error"]
        if child_signal is not None:
            evidence.append(
                "quota_or_usage_limit_structural"
                if child_signal.kind == signals.KIND_QUOTA
                else "child_api_error_structural"
            )
            # interruption_line is a PARENT-transcript line: prepare_state
            # compares it against interruption_line_at_dispatch to re-derive a
            # dispatched candidate back to pending. The child's own line
            # numbering is a different axis, so anchor to the furthest parent
            # line this call is known to occupy instead of mixing the two.
            interruption_lines.append(max(
                [
                    block["_parent_line"] for block in result_blocks
                    if isinstance(block.get("_parent_line"), int)
                ] or [call["line"]]
            ))
        if not evidence:
            continue
        description = meta.get("description") or tool_input.get("description") or ""
        agent_type = meta.get("agent_type") or tool_input.get("subagent_type") or ""
        candidates.append({
            "parent_session_id": transcript.stem,
            "origin_transcript_path": str(transcript),
            "agent_id": agent_id,
            "agent_type": agent_type if isinstance(agent_type, str) else "",
            "description": description if isinstance(description, str) else "",
            "tool_use_id": tool_id,
            "tool_name": call.get("tool_name", "Agent"),
            "parent_line": call.get("line"),
            "interruption_line": max(interruption_lines or [call["line"]]),
            "agent_transcript_path": agent_transcript_path,
            "evidence": evidence,
        })
    return candidates


ACCOUNTS_ROOT = Path(os.environ.get("CLAUDE_RESTART_ACCOUNTS_ROOT", "/var/lib/claude-accounts"))


def project_slug(project_dir: str | Path) -> str:
    return str(Path(project_dir).resolve()).replace("/", "-")


def account_project_roots() -> list[Path]:
    """Every account's session-transcript root, plus the caller's own $HOME.

    Separate Claude account logins (used to spread API quota) each persist
    session transcripts under their own /var/lib/claude-accounts/<name>/claude
    tree rather than a tree shared across accounts, so discovery must walk
    all of them explicitly — $HOME alone only ever sees the currently active
    account.
    """
    roots: list[Path] = []
    if ACCOUNTS_ROOT.is_dir():
        try:
            children = sorted(ACCOUNTS_ROOT.iterdir())
        except OSError:
            children = []
        for child in children:
            candidate = child / "claude" / "projects"
            if candidate.is_dir():
                roots.append(candidate)
    home_projects = Path.home() / ".claude" / "projects"
    if home_projects.is_dir():
        roots.append(home_projects)
    return roots


DEFAULT_SIBLING_WINDOW_SECONDS = 86400


def sibling_window_seconds() -> int:
    try:
        return int(os.environ.get(
            "CLAUDE_RESTART_SIBLING_WINDOW_SECONDS", str(DEFAULT_SIBLING_WINDOW_SECONDS)
        ))
    except (TypeError, ValueError):
        return DEFAULT_SIBLING_WINDOW_SECONDS


def sibling_transcripts(project_dir: str | Path, exclude: str | Path) -> list[Path]:
    """Other RECENT sessions' top-level transcripts for this project, any account.

    Consulted ONLY when the operator explicitly opted into cross-account
    discovery (``prepare --cross-account``). Default discovery never leaves the
    invoking session's own transcript: a same-project sibling within the window
    is routinely a live, unrelated work lane whose still-running children look
    exactly like interrupted ones from the parent side.

    Restricted to the exact project slug so recovery never reads unrelated
    projects. Deduplicates by session id, first root wins: when two account
    roots hold the same session stem, the later copy is dropped, not merged.

    KNOWN LIMITATION — same-stem transcripts are common here, not
    astronomical: measured 2026-09-27, 52 (slug, stem) pairs exist under
    more than one ACCOUNTS_ROOT root, 51 of them with divergent byte sizes
    (28 of 28 divergent inside this project's own slug), because each
    account records its own partial view of one logical session. An
    interrupted child living only in a dropped copy is therefore
    unreachable under --cross-account: under-recovery confined to the
    opt-in path.
    This docstring used to add "never over-recovery, so the default scope is
    unaffected". That was FALSE, and measurement disproved it on 2026-10-01:
    divergent copies also split a child's own completion record, so three
    already-finished children of session 4758df81 were listed as resumable
    from the default (own-transcript) scope alone. Child-level verdicts are
    now resolved across every copy (_child_transcript_copies); only this
    session-level dedup keeps the under-recovery limitation above.

    Bounded to transcripts modified within sibling_window_seconds() of now
    (default 24h). Fanning out to every sibling account's *entire* project
    history (unbounded) surfaced hundreds of candidates spanning months of
    abandoned/superseded work on first real use — this window keeps
    cross-account recovery to what a session left behind recently, which is
    what "even after switching accounts" actually means in practice. The
    current session's own transcript is never subject to this window: it is
    read unconditionally by the caller before sibling_transcripts runs.
    """
    slug = project_slug(project_dir)
    try:
        exclude_resolved = Path(exclude).resolve()
    except OSError:
        exclude_resolved = Path(exclude)
    cutoff = time.time() - sibling_window_seconds()
    seen: dict[str, Path] = {}
    for root in account_project_roots():
        candidate_dir = root / slug
        if not candidate_dir.is_dir():
            continue
        try:
            entries = list(candidate_dir.glob("*.jsonl"))
        except OSError:
            continue
        for entry in entries:
            try:
                resolved = entry.resolve()
            except OSError:
                continue
            if resolved == exclude_resolved:
                continue
            sid = entry.stem
            if not SESSION_RE.fullmatch(sid):
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            seen.setdefault(sid, resolved)
    return list(seen.values())


def build_resume_message(
    session_id: str, agent_id: str, guidance: str | None = None,
) -> str:
    """The fixed recovery instruction, optionally followed by operator guidance.

    With no guidance the result is byte-for-byte what it has always been, so a
    bare /restart is unchanged. Guidance is APPENDED after the instruction
    between explicit markers and copied verbatim — never truncated, escaped,
    re-wrapped or normalised. The instruction therefore stays an exact prefix,
    which is precisely what authorize_send_message enforces: the real persisted
    instruction always reaches the resumed agent unaltered, and the agent can
    still tell the harness's words from its operator's.
    """
    sid = _safe_session_id(session_id)
    aid = _safe_agent_id(agent_id)
    instruction = "\n".join([
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
    if not isinstance(guidance, str) or not guidance:
        return instruction
    return "".join([
        instruction, "\n\n", GUIDANCE_OPEN, "\n", GUIDANCE_NOTE, "\n",
        guidance, "\n", GUIDANCE_CLOSE,
    ])


def prepare_state(
    session_id: str,
    project_dir: str | Path | None = None,
    *,
    cross_account: bool = False,
) -> dict[str, Any]:
    """Build the recovery candidate set for the invoking parent session.

    Default scope is the invoking session's OWN transcript only (after
    ``claude --resume`` that transcript already carries the interrupted history
    forward, so the lineage is covered by construction). The cross-account
    sibling sweep — the account-rotation case where another account's earlier
    session left interrupted children in this same project — runs only on the
    operator's explicit ``cross_account=True`` opt-in, and that opt-in is
    recorded in the state file because authorize_send_message refuses
    foreign-origin dispatches from a state that was not prepared with it.
    """
    sid = _safe_session_id(session_id)
    grant = load_valid_grant(sid)
    own_transcript = Path(grant["transcript_path"])
    # Guidance belongs to THIS operator session's /restart invocation: it is
    # read fresh here, keyed by this sid alone, and never inherited from the
    # previous state below — so it cannot leak across sessions, and a later bare
    # /restart (which removes the file) cannot replay an earlier invocation's
    # guidance as if it were current.
    guidance = load_guidance(sid)
    discovered = discover_candidates(own_transcript)
    if cross_account and project_dir is not None:
        for sibling in sibling_transcripts(project_dir, exclude=own_transcript):
            discovered.extend(discover_candidates(sibling))
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
            if status == "dispatched":
                dispatched_line = previous.get("interruption_line_at_dispatch")
                if not isinstance(dispatched_line, int) or candidate["interruption_line"] > dispatched_line:
                    status = "pending"
            elif status != "response_observed":
                status = "pending"
            item = {
                **candidate,
                "status": status,
                "attempts": previous.get("attempts", 0)
                if isinstance(previous.get("attempts", 0), int) else 0,
                "resume_message": build_resume_message(
                    candidate["parent_session_id"], candidate["agent_id"], guidance
                ),
            }
            for key in (
                "last_dispatched_at", "last_stop_at", "interruption_line_at_dispatch",
            ):
                if key in previous:
                    item[key] = previous[key]
            items.append(item)
        state = {
            "schema_version": SCHEMA_VERSION,
            "parent_session_id": sid,
            "transcript_path": grant["transcript_path"],
            "grant_issued_at": grant.get("issued_at"),
            "cross_account": bool(cross_account),
            "operator_guidance": guidance,
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
            "agent_id", "parent_session_id", "origin_transcript_path", "agent_type",
            "description", "tool_use_id",
            "agent_transcript_path", "evidence", "interruption_line", "status",
            "attempts", "resume_message",
        )})
    incomplete = [item["agent_id"] for item in public if item.get("status") != "response_observed"]
    return {
        "schema_version": SCHEMA_VERSION,
        "parent_session_id": state.get("parent_session_id"),
        "cross_account": state.get("cross_account") is True,
        # Top-level and unconditional: a caller must be able to read the
        # guidance it passed even when discovery found ZERO candidates and no
        # resume_message exists to carry it.
        "operator_guidance": state.get("operator_guidance"),
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
    """Authorize only the exact recovery message, as a prefix, to a discovered id.

    Validates against this operator session's prepared state. A candidate whose
    parent_session_id is not the operator's own session is dispatchable ONLY
    when the state itself records the explicit ``--cross-account`` opt-in from
    prepare time; a state without that marker — including every legacy state
    file predating the flag, with its possibly stale foreign entries — fails
    closed on foreign-origin targets. A candidate whose origin transcript was
    never recorded is refused outright: unprovable locality is not locality.
    """
    if not isinstance(payload, dict):
        return False, "malformed hook payload"
    sid = payload.get("session_id") or payload.get("sessionId") or os.environ.get("CLAUDE_SESSION_ID")
    try:
        sid = _safe_session_id(str(sid or ""))
        # The operator must still hold a live /restart grant; keep it for the
        # origin and epoch checks below.
        grant = load_valid_grant(sid)
        params = payload.get("tool_input") if "tool_input" in payload else payload.get("params")
        if not isinstance(params, dict):
            raise RestartError("SendMessage input is missing")
        agent_id = _safe_agent_id(str(params.get("to") or ""))
        message = params.get("message")
        state = _load_state(sid)
        item = next(
            (entry for entry in state.get("candidates", [])
             if isinstance(entry, dict) and entry.get("agent_id") == agent_id),
            None,
        )
        if not item:
            raise RestartError("target is not a recoverable interrupted subagent for this /restart session")
        # Foreign origin is decided by transcript path, not session id alone:
        # account roots hold byte-copies of the same session file (same stem,
        # different root), so a same-sid candidate discovered from another root
        # must still count as foreign. A candidate without the recorded origin
        # path (legacy state) therefore cannot be PROVEN local — session id is
        # not an identity here — so it fails closed instead of degrading to the
        # session-id comparison. Origin is never inferred from anything else.
        origin_transcript = item.get("origin_transcript_path")
        if not isinstance(origin_transcript, str) or not origin_transcript:
            raise RestartError(
                "target records no origin transcript, so its locality cannot be "
                "proven; re-run prepare to record the origin of every genuine "
                "candidate (add --cross-account if the target is foreign)"
            )
        is_foreign = (
            item.get("parent_session_id") != sid
            or origin_transcript != grant.get("transcript_path")
        )
        if is_foreign:
            if state.get("cross_account") is not True:
                raise RestartError(
                    "target originates from another parent session; only a prepare run "
                    "explicitly opted into --cross-account may authorize resuming it"
                )
            # The opt-in is epoch-bound: a state prepared with --cross-account
            # under an EARLIER grant must not keep authorizing foreign sends
            # after a later bare /restart mints a fresh grant. Same-epoch is
            # proven by the issued_at the prepare recorded.
            if state.get("grant_issued_at") != grant.get("issued_at"):
                raise RestartError(
                    "cross-account state is stale: it was prepared under an earlier "
                    "/restart grant; re-run prepare (with --cross-account) first"
                )
        # Completion is rechecked at dispatch time, not only at discovery: a
        # child that reached its terminal end_turn report after prepare (or a
        # legacy-state candidate never structurally screened) must not be
        # resumed. Only an unreadable transcript (None) stays dispatchable —
        # the same fail-toward-recovery rule discovery applies.
        if _child_reported_end_turn(str(item.get("agent_transcript_path") or "")) is True:
            raise RestartError(
                "target's child transcript already contains its terminal end_turn "
                "report; completed agents are never resumed"
            )
        # Relaxed from byte-equality to a REQUIRED EXACT PREFIX. The rule being
        # enforced is that the REAL persisted resume instruction reaches the
        # agent unaltered, so an orchestrator can never pass a freshly
        # reconstructed prompt off as a resume. Content AFTER the instruction is
        # additive and cannot change it, so operator guidance may follow; any
        # message that rewords, truncates or reorders the instruction itself
        # fails this test exactly as it did under equality.
        expected = item.get("resume_message")
        if not isinstance(expected, str) or not expected or not isinstance(message, str):
            raise RestartError("SendMessage body is not the exact restart-v1 recovery message")
        if not message.startswith(expected):
            raise RestartError(
                "SendMessage body does not begin with the exact restart-v1 recovery "
                "message; the persisted instruction must be delivered verbatim as an "
                "exact prefix (trailing operator guidance is allowed, altering the "
                "instruction is not)"
            )
        if item.get("status") != "pending":
            raise RestartError("target is not pending; duplicate restart dispatch denied")
        return True, "validated /restart recovery"
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
                item["interruption_line_at_dispatch"] = item.get("interruption_line")
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
            # The explicit sentinel the fixed resume message demands outranks the
            # quota text-match: a recovered agent reporting on an outage quotes
            # limit banners in a legitimately complete response. Take the LAST
            # sentinel so quoted earlier ones cannot mask the final verdict.
            sentinels = RECOVERY_STATUS_RE.findall(last_message)
            if sentinels:
                interrupted = sentinels[-1] == "quota_interrupted"
            else:
                interrupted = signals.is_quota_text(last_message)
            item["status"] = "quota_interrupted" if interrupted else "response_observed"
            item["last_stop_at"] = _iso()
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
    except OSError as exc:
        raise RestartError(f"cannot consume restart grant: {exc}") from exc
    return view
