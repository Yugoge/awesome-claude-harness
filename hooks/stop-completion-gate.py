#!/usr/bin/env python3
"""Stop hook: a /dev-family orchestrator session may not end while its
completion obligation is open (ticket 20261001-161041-r08; reworked by
dev-command-20261002-170011-l13, design D9 / rulings R9 and R15).

``docs/dev/completion-<task_id>.md`` is written by main-session prose
(``commands/dev.md`` Step 17), never by a dispatched subagent, so no
``<obligation>`` block covers it. This gate is the session-terminal backstop.

Open findings (the gate's set C; trigger = C non-empty):
  * ``MISSING_ARTIFACT|<completion path>`` -- resolve_chain() reports status
    "fail" with exactly one error, MISSING_ARTIFACT at the completion path
    (every other chain check already passed; detail is never compared).
  * ``GATE_ERROR|<ExceptionClass>`` -- any exception after the session is bound
    to a task (resolver import/call, escalation scan).
  * ``ESCALATION|<record_id>`` -- one per unresolved producer escalation record
    at ``.claude/dev-registry/<cycle_id>/escalations/<record_id>.json``. Fields
    are read from inside the JSON (record_id, nonce, ...), never from filenames;
    an unparseable record or one lacking record_id/nonce is malformed and stays
    unresolved. An unresolved record is open even when the completion file exists.

Rules:
  1. The only release is C empty (trigger false): state is cleared, exit 0.
  2. While C is non-empty every Stop exits 2 (or is the awaiting-input stop
     below). There is no counted fail-open; blocking is bounded by PROGRESS
     (hooks/lib/progress_measure.py, the C4 revisit rule), not by a count.
  3. Progress keeps blocking with the ordinary message. A round with no progress
     moves to phase ``arbitration``: exit 2 plus an ARBITRATION directive naming
     the current finding_key.
  4. Exit from arbitration: the orchestrator writes
     ``docs/dev/arbitration-<cycle_id>.json`` (the verdict carrier; never a
     fingerprint input). ``{"verdict": "awaiting_input", "finding_key", "need",
     "why", "for": "user"|"operator"}`` is validated and audited by
     ``declare_awaiting_input`` and requires post-round phase arbitration.
     ``{"verdict": "resolved", "resolves": [nonce, ...], "evidence": [existing
     project-relative paths]}`` resolves escalation records (audited
     ``escalation_resolved``; resolved nonces persist via the audit JSONL). The
     gate never edits records and never writes the completion file.
  5. Awaiting-input stop (phase awaiting_input, or state not writable on the
     primary and fallback paths) is NOT an allow: the cycle stays incomplete.
     Default form: stdout ``{"continue": false, "stopReason": "AWAITING_INPUT
     need=... why=... for=..."}`` and exit 0. If env
     CLAUDE_COMPLETION_GATE_AWAITING_FORM is anything but "continue_false" the
     same text goes to stderr with exit 2. Each awaiting round is recorded
     (round and awaiting.emissions advance).

Durable state: ``<project>/.claude/dev-registry/<cycle_id>/completion-gate-state.json``
(fallback ``~/.claude/logs/completion-gate-<cycle_id>.json``); audit JSONL
``completion-gate-audit.jsonl`` beside it. ``<cycle_id>`` is the bridged
registry directory name. Nothing is written under /tmp.

Bridge: Stop-payload session_id -> registry directories (``dev-<task_id>``)
whose artifact-contract-enforce.json / e2e-enforce.json carry that
claude_session_id. Every matching directory is evaluated; any trigger blocks.
Registry root unreadable -> awaiting-input stop. No session id / no match is out
of scope (exit 0, advisory log record).

MODE (env CLAUDE_COMPLETION_GATE_MODE): default and any unknown value = block;
"advisory" logs ``would_block`` and exits 0; "off" exits 0. advisory/off are
human operator switches set by harness configuration, not workflow outcomes.

Exemption (all modes, checked before the bridge): a session whose first user
message is /close or /commit passes untouched (those pipelines own their
completion contracts).

Failure policy: an exception before the session is bound (payload / session-id
parsing) exits 0 because the gate cannot know the session is /dev-family. After
binding no exception releases the session.

Exit codes: 0 = trigger false / out of scope / operator switch / awaiting-input
stop (continue=false form); 2 = block, arbitration, or awaiting-input fallback.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ADVISORY_LOG = Path.home() / ".claude" / "logs" / "completion-terminal-gate-advisory.jsonl"
_HOOKS_DIR = Path(__file__).resolve().parent
_EXEMPT_COMMANDS = {"close", "commit"}
_SENTINEL_FILENAMES = ("artifact-contract-enforce.json", "e2e-enforce.json")
_AWAITING_FORM_ENV = "CLAUDE_COMPLETION_GATE_AWAITING_FORM"
_STATE_NAME = "completion-gate-state.json"
_AUDIT_NAME = "completion-gate-audit.jsonl"

# Identifier-safety pattern reused from stop-do-report-gate.py / obligation.py:
# an unsafe/path-shaped session or task id degrades silently to "no
# enforcement" rather than escaping the dev-registry or counter-file paths.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _log_event(record: dict) -> None:
    """Best-effort append to the advisory log. Never affects exit."""
    try:
        ADVISORY_LOG.parent.mkdir(parents=True, exist_ok=True)
        record["ts"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(ADVISORY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _extract_command_name(user_input: str) -> str:
    """Lazy-load hooks/prompt-workflow.py's extract_command_name().

    Hyphenated filename -- not a plain importable module name -- mirrors the
    identical technique at hooks/stop-obligation-gate.py:68-91. Any failure
    degrades to "" (treated as "not /close or /commit"; the exemption simply
    does not apply -- the safe direction).
    """
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "stop_completion_gate_prompt_workflow", _HOOKS_DIR / "prompt-workflow.py"
        )
        if spec is None or spec.loader is None:
            return ""
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.extract_command_name(user_input)
    except Exception:
        return ""


def _import_obligation_lib():
    """Lazy import of hooks/lib/obligation.py, reused only for
    read_first_record_prompt() (the /close|/commit exemption)."""
    if str(_HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(_HOOKS_DIR))
    from lib import obligation  # type: ignore

    return obligation


def _import_progress_measure():
    """Shared progress-measure helper (hooks/lib/progress_measure.py)."""
    if str(_HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(_HOOKS_DIR))
    from lib import progress_measure  # type: ignore

    return progress_measure


def _first_user_message(transcript_path: str) -> str | None:
    """Return the transcript's first user-turn message text, or None."""
    if not transcript_path:
        return None
    try:
        obligation = _import_obligation_lib()
        return obligation.read_first_record_prompt(transcript_path)
    except Exception:
        return None


def _is_exempt_session(transcript_path: str) -> bool:
    """M7/AC5: /close and /commit sessions always pass through, checked
    BEFORE any dev-registry bridge lookup, in every mode."""
    message = _first_user_message(transcript_path)
    if not message:
        return False
    return _extract_command_name(message) in _EXEMPT_COMMANDS


def _bridge_session_to_cycles(project_dir: Path, session_id: str) -> list[tuple[str, str]]:
    """session_id -> [(cycle_id, task_id)] via the dev-registry
    claude_session_id sidecar. cycle_id is the registry directory name. An
    unreadable registry root raises OSError (the caller turns it into an
    awaiting-input stop); every matching directory is returned."""
    registry_root = project_dir / ".claude" / "dev-registry"
    if not registry_root.is_dir():
        return []

    matches: dict[str, str] = {}
    entries = sorted(registry_root.iterdir())
    for entry in entries:
        try:
            if not entry.is_dir() or not entry.name.startswith("dev-"):
                continue
        except OSError:
            continue
        task_id = entry.name[len("dev-"):]
        if not task_id or not _SAFE_ID_RE.match(task_id):
            continue
        for fname in _SENTINEL_FILENAMES:
            sentinel = entry / fname
            try:
                if not sentinel.is_file():
                    continue
                data = json.loads(sentinel.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict) and data.get("claude_session_id") == session_id:
                matches[entry.name] = task_id
                break

    if len(matches) > 1:
        _log_event({
            "event": "ambiguous_bridge",
            "session_id": session_id,
            "candidates": sorted(matches),
        })
    return sorted(matches.items())


def _import_resolve_chain(project_dir: Path):
    """M4: in-process import of scripts/resolve-dev-artifact-chain.py's
    resolve_chain(), via the hyphenated-filename technique already used at
    hooks/stop-obligation-gate.py:68-91 for prompt-workflow.py. Never
    subprocess, never network."""
    import importlib.util

    path = project_dir / "scripts" / "resolve-dev-artifact-chain.py"
    spec = importlib.util.spec_from_file_location(
        "stop_completion_gate_resolve_dev_artifact_chain", path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _is_sole_missing_completion(result: object) -> bool:
    """M5/AC2: the exact 'all else passed, completion missing' signature.

    Field-subset check on code+path only -- ChainValidator.error() always
    appends a 3-key {code, path, detail} dict, so detail is deliberately
    never compared.
    """
    if not isinstance(result, dict):
        return False
    if result.get("status") != "fail":
        return False
    errors = result.get("errors")
    if not isinstance(errors, list) or len(errors) != 1:
        return False
    entry = errors[0]
    if not isinstance(entry, dict):
        return False
    return (
        entry.get("code") == "MISSING_ARTIFACT"
        and entry.get("path") == result.get("completion")
    )


def _format_block_message(task_id: str, completion_path: str) -> str:
    """Three-part template -- what is unmet / whose responsibility / how to
    fix -- mirrors hooks/stop-obligation-gate.py's _format_block_message."""
    return (
        f"COMPLETION_GATE_BLOCKED -- {completion_path}: completion missing | "
        "owner: orchestrator (this session) | "
        f"fix: write docs/dev/completion-{task_id}.md per commands/dev.md's "
        "Step-17 template, then stop again.\n"
    )


def _audit_lines(audit_path: Path) -> list[dict]:
    out: list[dict] = []
    try:
        for line in audit_path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    except OSError:
        pass
    return out


def _audit_once(audit_path: Path, record: dict, dedupe: tuple) -> None:
    """Append-only audit line, skipped when an existing line matches every
    (field, value) pair in ``dedupe``. Best effort; never raises."""
    try:
        for old in _audit_lines(audit_path):
            if all(old.get(k) == v for k, v in dedupe):
                return
        record["ts"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _read_verdict(project_dir: Path, cycle_id: str, audit_path: Path):
    """Return (verdict dict | None, sha256). An unparseable file is audited
    once as verdict_rejected."""
    path = project_dir / "docs" / "dev" / f"arbitration-{cycle_id}.json"
    try:
        raw = path.read_bytes()
    except OSError:
        return None, None
    sha = hashlib.sha256(raw).hexdigest()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        data = None
    if not isinstance(data, dict):
        _audit_once(audit_path, {"kind": "verdict_rejected", "reason": "unparseable",
                                 "verdict_sha256": sha},
                    (("kind", "verdict_rejected"), ("verdict_sha256", sha), ("reason", "unparseable")))
        return None, sha
    return data, sha


def _evidence_ok(project_dir: Path, evidence: object) -> bool:
    if not isinstance(evidence, list) or not evidence:
        return False
    root = project_dir.resolve()
    for item in evidence:
        if not isinstance(item, str) or not item.strip():
            return False
        try:
            target = (root / item).resolve()
            target.relative_to(root)
            if not target.exists():
                return False
        except (OSError, ValueError):
            return False
    return True


def _scan_escalations(registry_dir: Path) -> list[dict]:
    """Records at the single C1 path. Fields come from inside the JSON."""
    esc_dir = registry_dir / "escalations"
    records: list[dict] = []
    if not esc_dir.is_dir():
        return records
    for f in sorted(esc_dir.iterdir()):
        if not f.is_file() or f.suffix != ".json":
            continue
        rid = nonce = None
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                r, n = data.get("record_id"), data.get("nonce")
                if isinstance(r, str) and r.strip() and isinstance(n, str) and n.strip():
                    rid, nonce = r, n
        except Exception:
            pass
        records.append({"path": f, "record_id": rid or f.stem, "nonce": nonce})
    return records


def _resolve_escalations(project_dir: Path, audit_path: Path, verdict, sha, records) -> set[str]:
    """Resolved nonce set = earlier escalation_resolved audit lines plus the
    current valid ``resolved`` verdict (each audited once)."""
    resolved = {
        rec.get("nonce") for rec in _audit_lines(audit_path)
        if rec.get("kind") == "escalation_resolved" and isinstance(rec.get("nonce"), str)
    }
    if not isinstance(verdict, dict) or verdict.get("verdict") != "resolved":
        return resolved
    resolves = verdict.get("resolves")
    reason = "evidence_missing_or_nonexistent_or_no_nonces"
    if not isinstance(resolves, list) or not resolves or not _evidence_ok(
            project_dir, verdict.get("evidence")):
        _audit_once(audit_path, {"kind": "verdict_rejected", "verdict_sha256": sha,
                                 "reason": reason},
                    (("kind", "verdict_rejected"), ("verdict_sha256", sha), ("reason", reason)))
        return resolved
    known = {r["nonce"] for r in records if r["nonce"]}
    for nonce in resolves:
        if isinstance(nonce, str) and nonce in known:
            resolved.add(nonce)
            _audit_once(audit_path, {"kind": "escalation_resolved", "nonce": nonce,
                                     "evidence": verdict.get("evidence"),
                                     "verdict_sha256": sha},
                        (("kind", "escalation_resolved"), ("nonce", nonce)))
        else:
            why = f"unknown_nonce:{nonce}"
            _audit_once(audit_path, {"kind": "verdict_rejected", "verdict_sha256": sha,
                                     "reason": why},
                        (("kind", "verdict_rejected"), ("verdict_sha256", sha), ("reason", why)))
    return resolved


def _block_lines(findings: list[str], task_id: str, cycle_id: str, completion_path) -> str:
    lines = []
    for fid in findings:
        code, _, ident = fid.partition("|")
        if code == "MISSING_ARTIFACT":
            lines.append(_format_block_message(task_id, completion_path or ident).rstrip("\n"))
        elif code == "ESCALATION":
            lines.append(
                f"COMPLETION_GATE_BLOCKED -- {fid}: unresolved producer escalation | "
                "owner: orchestrator (this session) | fix: resolve it via "
                f"docs/dev/arbitration-{cycle_id}.json (verdict resolved, resolves:[nonce], "
                "evidence:[existing paths]), then stop again.")
        else:
            lines.append(
                f"COMPLETION_GATE_BLOCKED -- {fid}: gate could not evaluate the chain | "
                "owner: harness operator | fix: repair the gate/resolver, then stop again.")
    return "\n".join(lines) + "\n"


def _evaluate_cycle(project_dir: Path, cycle_id: str, task_id: str, session_id: str,
                    mode: str) -> dict:
    """One bridged registry directory -> {status: pass | block | awaiting, ...}."""
    try:
        pm = _import_progress_measure()
        registry_dir = project_dir / ".claude" / "dev-registry" / cycle_id
        state_path = registry_dir / _STATE_NAME
        fallback = Path.home() / ".claude" / "logs" / f"completion-gate-{cycle_id}.json"
        audit_path = registry_dir / _AUDIT_NAME

        findings: list[str] = []
        pinned: list[str] = []
        completion_path = None
        try:
            resolver = _import_resolve_chain(project_dir)
            result = resolver.resolve_chain(str(project_dir), task_id)
            if _is_sole_missing_completion(result):
                completion_path = result.get("completion", f"docs/dev/completion-{task_id}.md")
                findings.append(pm.finding_id("MISSING_ARTIFACT", completion_path, str(project_dir)))
                pinned.append(completion_path)
        except Exception as exc:
            findings.append(f"GATE_ERROR|{type(exc).__name__}")
            _log_event({"event": "gate_error", "session_id": session_id,
                        "cycle_id": cycle_id, "error": repr(exc)})

        try:
            records = _scan_escalations(registry_dir)
        except Exception as exc:
            records = []
            findings.append(f"GATE_ERROR|{type(exc).__name__}")
            _log_event({"event": "gate_error", "session_id": session_id,
                        "cycle_id": cycle_id, "error": repr(exc)})

        verdict, verdict_sha = _read_verdict(project_dir, cycle_id, audit_path)
        resolved = _resolve_escalations(project_dir, audit_path, verdict, verdict_sha, records)
        for rec in records:
            if rec["nonce"] is None or rec["nonce"] not in resolved:
                findings.append(f"ESCALATION|{rec['record_id']}")
                pinned.append(str(rec["path"]))

        if not findings:
            had_state = pm.read_state(state_path) is not None or pm.read_state(fallback) is not None
            pm.clear_state(state_path)
            pm.clear_state(fallback)
            if had_state:
                _audit_once(audit_path, {"kind": "released_trigger_false", "cycle_id": cycle_id},
                            (("kind", "__never_matches__"),))
            return {"status": "pass"}

        if mode == "advisory":
            _log_event({"event": "would_block", "mode": mode, "session_id": session_id,
                        "task_id": task_id, "cycle_id": cycle_id, "findings": findings})
            return {"status": "pass"}

        fkey = pm.finding_key(findings, cycle_id)
        fingerprint = pm.world_fingerprint(str(project_dir), pinned)
        rnd = pm.record_round(str(state_path), cycle_id, fingerprint, findings,
                              fallback_path=str(fallback))
        phase = rnd["phase"]
        awaiting: dict = {}
        if rnd["outcome"] == "unwritable":
            awaiting = {
                "need": f"restore write access to {state_path} or {fallback}",
                "why": "completion-gate state cannot be persisted so progress cannot be measured",
                "for": "operator",
            }
        else:
            if verdict is not None and verdict.get("verdict") != "resolved":
                pm.declare_awaiting_input(rnd["state_path"], cycle_id, verdict, fkey,
                                          audit_path=str(audit_path))
            state = pm.read_state(rnd["state_path"]) or {}
            phase = state.get("phase", phase)
            if phase == "awaiting_input":
                awaiting = dict(state.get("awaiting") or {})
        _log_event({"event": phase, "mode": mode, "session_id": session_id,
                    "task_id": task_id, "cycle_id": cycle_id, "round": rnd["round"],
                    "outcome": rnd["outcome"], "finding_key": fkey, "findings": findings})

        if phase == "awaiting_input":
            return {"status": "awaiting", "cycle_id": cycle_id,
                    "need": awaiting.get("need") or "orchestrator verdict",
                    "why": awaiting.get("why") or "no progress and awaiting input",
                    "for": awaiting.get("for") or "operator"}
        text = _block_lines(findings, task_id, cycle_id, completion_path)
        if phase == "arbitration":
            text += (
                f"ARBITRATION -- cycle {cycle_id}: no progress for {rnd['no_progress_rounds']} "
                f"round(s) (round {rnd['round']}), finding_key={fkey}. Orchestrator: make a "
                "pinned artifact change (write the missing artifact), or write "
                f"docs/dev/arbitration-{cycle_id}.json with verdict awaiting_input "
                f'{{"verdict": "awaiting_input", "finding_key": "{fkey}", "need": ..., '
                '"why": ..., "for": "user"|"operator"} (validated and audited), or a '
                "resolved verdict for escalation records.\n"
            )
        return {"status": "block", "text": text}
    except Exception as exc:  # the machine itself failed: never allow, never wedge
        _log_event({"event": "machine_error", "session_id": session_id,
                    "cycle_id": cycle_id, "error": repr(exc)})
        return {"status": "awaiting", "cycle_id": cycle_id,
                "need": f"repair hooks/stop-completion-gate.py or hooks/lib/progress_measure.py ({type(exc).__name__})",
                "why": "completion-gate progress machine raised an exception",
                "for": "operator"}


def _emit_awaiting(items: list[dict], session_id: str) -> int:
    parts = [f"need={i['need']} why={i['why']} for={i['for']}" for i in items]
    text = "AWAITING_INPUT " + " ; ".join(parts)
    sys.stderr.write(text + "\n")
    _log_event({"event": "awaiting_input_stop", "session_id": session_id, "text": text})
    if os.environ.get(_AWAITING_FORM_ENV, "continue_false").strip().lower() == "continue_false":
        sys.stdout.write(json.dumps({"continue": False, "stopReason": text}) + "\n")
        return 0
    return 2


def main() -> int:
    mode = (os.environ.get("CLAUDE_COMPLETION_GATE_MODE", "block") or "block").strip().lower()
    if mode == "off":
        return 0
    if mode != "advisory":
        mode = "block"  # default and unknown values resolve to block

    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    transcript_path = str(payload.get("transcript_path") or "")

    # M7/AC5: unconditional exemption, before any dev-registry bridge lookup,
    # in every mode.
    if _is_exempt_session(transcript_path):
        return 0

    session_id = str(
        payload.get("session_id")
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
        or os.environ.get("CLAUDE_SESSION_ID")
        or ""
    )
    if not session_id or not _SAFE_ID_RE.match(session_id):
        _log_event({"event": "out_of_scope", "reason": "no_or_unsafe_session_id"})
        return 0

    project_dir = Path(
        os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    )

    try:
        matches = _bridge_session_to_cycles(project_dir, session_id)
    except OSError as exc:
        # Registry root exists but cannot be listed: environmental, needs a human.
        registry_root = project_dir / ".claude" / "dev-registry"
        if mode == "advisory":
            _log_event({"event": "would_block", "mode": mode, "session_id": session_id,
                        "reason": "registry_unreadable", "error": repr(exc)})
            return 0
        try:
            pm = _import_progress_measure()
            pm.record_round(
                str(Path.home() / ".claude" / "logs" / f"completion-gate-registry-{session_id}.json"),
                f"registry-unreadable:{session_id}",
                pm.world_fingerprint(str(project_dir), [str(registry_root)]),
                [pm.finding_id("REGISTRY_UNREADABLE", str(registry_root), str(project_dir))])
        except Exception:
            pass
        return _emit_awaiting([{
            "need": f"restore read access to {registry_root}",
            "why": f"dev-registry cannot be listed ({type(exc).__name__}) so the session cannot be bound",
            "for": "operator",
        }], session_id)
    if not matches:
        _log_event({"event": "out_of_scope", "reason": "no_registry_match", "session_id": session_id})
        return 0

    results = [
        _evaluate_cycle(project_dir, cycle_id, task_id, session_id, mode)
        for cycle_id, task_id in matches
    ]
    blocks = [r for r in results if r["status"] == "block"]
    if blocks:
        sys.stderr.write("".join(r["text"] for r in blocks))
        return 2
    waiting = [r for r in results if r["status"] == "awaiting"]
    if waiting:
        return _emit_awaiting(waiting, session_id)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # pre-binding failure only: session cannot be shown to be /dev-family
        try:
            _log_event({"event": "gate_error", "error": repr(exc)})
        except Exception:
            pass
        sys.exit(0)
