"""Progress measure for blocking gates (R15): block while progress is made,
escalate when it is not, and never release.

Pure stdlib. No gate-specific inputs, no I/O outside the paths a caller hands
in. Consumers: hooks/stop-completion-gate.py and the L2 SubagentStop
producer gate. The helper has NO allow outcome: it cannot release anything;
only a caller whose own trigger became false may release, and it does so by
calling ``clear_state``.

Interface (names are the contract; only underscore-private helpers may be
added):

* ``finding_id(code, path, project_dir=None) -> str``
    ``"<code>|<project-relative posix path>"``. Absolute paths under
    ``project_dir`` are relativised. Detail text, line numbers and
    timestamps are never inputs.
* ``finding_key(open_findings, scope) -> str``
    sha256 hex[:16] of ``"\\n".join(sorted(set(open_findings))) + "|" + scope``.
* ``world_fingerprint(project_dir, artifact_paths) -> str``
    sha256 over sorted ``(relpath, sha256(bytes) | "ABSENT")`` for exactly the
    explicit paths given (no glob, no directory walk).
* ``record_round(state_path, loop_key, world_fingerprint, open_findings=None,
  *, fallback_path=None, now=None) -> Round``
    ``Round`` is a dict ``{outcome, phase, round, no_progress_rounds, reason,
    state_path}``. ``outcome`` is one of ``first | progress | no_progress |
    unwritable``; ``phase`` is one of ``block | arbitration | awaiting_input``.
    Corrupt, unreadable or foreign-``loop_key`` prior state counts as "no prior
    round". The decision is persisted atomically. Never raises.
* ``declare_awaiting_input(state_path, loop_key, verdict, current_finding_key,
  *, audit_path=None, now=None) -> (ok, reason)``
    Validation and audit gate for an orchestrator-written awaiting_input
    verdict; on ok sets ``phase=awaiting_input``.
* ``clear_state(state_path)``; ``read_state(state_path) -> dict | None``.
* ``_write_atomic(path, text)`` is the single write seam (tmp file in the same
  directory + ``os.replace`` + fsync); tests monkeypatch it to simulate failure.

Progress rule (C4). Per ``loop_key`` the state keeps ``prev_set`` (the previous
round's finding ids P), ``seen_sets`` (every earlier finding set), ``seen_fps``
(set-key -> fingerprints already seen with that set), ``world_fp``, ``round``,
``phase``, ``no_progress_rounds``, ``awaiting`` and ``audit``. For the current
set C and fingerprint F, the round is ``progress`` iff (a) C is a PROPER subset
of P and C was never seen in an earlier round, or (b) C == P and F was never
seen with that set. Anything else is ``no_progress`` (including every revisited
set, even when bytes changed in between). ``round`` is never reset except by
``clear_state``; ``seen_*`` only grow.

Phases: ``first``/``progress`` -> ``block``; ``no_progress`` -> ``arbitration``
(``no_progress_rounds += 1``). From ``awaiting_input`` a ``no_progress`` round
stays ``awaiting_input`` and records ``awaiting.emissions += 1`` and
``awaiting.last_emitted_at``; ``progress`` returns to ``block``. A write that
fails on the primary and the fallback path yields outcome ``unwritable`` /
phase ``awaiting_input``.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import posixpath
import tempfile

OUTCOMES = ("first", "progress", "no_progress", "unwritable")
PHASES = ("block", "arbitration", "awaiting_input")
_AWAITING_FOR = ("user", "operator")


def _now_str(now) -> str:
    if now is None:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()
    if isinstance(now, datetime.datetime):
        return now.isoformat()
    return str(now)


def _norm_rel(path, project_dir) -> str:
    p = str(path).replace("\\", "/")
    if project_dir is not None and os.path.isabs(p):
        try:
            rel = os.path.relpath(p, os.path.abspath(str(project_dir)))
            if not rel.startswith(".."):
                p = rel
        except ValueError:
            pass
    return posixpath.normpath(p)


def finding_id(code: str, path: str, project_dir: str | None = None) -> str:
    return f"{code}|{_norm_rel(path, project_dir)}"


def finding_key(open_findings, scope: str) -> str:
    body = "\n".join(sorted({str(f) for f in open_findings})) + "|" + str(scope)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def world_fingerprint(project_dir: str, artifact_paths) -> str:
    entries: dict[str, str] = {}
    for p in artifact_paths:
        rel = _norm_rel(p, project_dir)
        absolute = rel if os.path.isabs(rel) else os.path.join(str(project_dir), rel)
        try:
            if os.path.isfile(absolute):
                with open(absolute, "rb") as fh:
                    digest = hashlib.sha256(fh.read()).hexdigest()
            else:
                digest = "ABSENT"
        except OSError:
            digest = "ABSENT"
        entries[rel] = digest
    body = "\n".join(f"{r}\t{d}" for r, d in sorted(entries.items()))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _write_atomic(path, text: str) -> None:
    path = str(path)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".pm-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_state(state_path) -> dict | None:
    """Return the normalised state dict, or None when absent/unreadable/corrupt."""
    try:
        with open(str(state_path), encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or not isinstance(data.get("loop_key"), str):
            return None
        if data.get("phase") not in PHASES or not isinstance(data.get("round"), int):
            return None
        prev = data.get("prev_set")
        seen = data.get("seen_sets")
        fps = data.get("seen_fps")
        if not isinstance(prev, list) or not isinstance(seen, list) or not isinstance(fps, dict):
            return None
        data.setdefault("no_progress_rounds", 0)
        data.setdefault("world_fp", "")
        if not isinstance(data.get("awaiting"), dict):
            data["awaiting"] = {}
        data["awaiting"].setdefault("emissions", 0)
        data["awaiting"].setdefault("last_emitted_at", None)
        if not isinstance(data.get("audit"), list):
            data["audit"] = []
        return data
    except Exception:
        return None


def clear_state(state_path) -> None:
    try:
        os.unlink(str(state_path))
    except OSError:
        pass


def _set_key(items) -> str:
    return "\n".join(sorted(items))


def _load_prior(state_path, fallback_path, loop_key):
    best = None
    for p in (state_path, fallback_path):
        if p is None:
            continue
        st = read_state(p)
        if st is not None and st["loop_key"] == loop_key:
            if best is None or st["round"] > best["round"]:
                best = st
    return best


def record_round(state_path, loop_key, world_fingerprint, open_findings=None, *,
                 fallback_path=None, now=None) -> dict:
    stamp = _now_str(now)
    current = sorted({str(f) for f in (open_findings or [])})
    ckey = _set_key(current)
    prior = _load_prior(state_path, fallback_path, loop_key)

    if prior is None:
        outcome = "first"
        reason = "no prior round"
        state = {
            "loop_key": loop_key, "prev_set": current, "seen_sets": [current],
            "seen_fps": {ckey: [world_fingerprint]}, "world_fp": world_fingerprint,
            "round": 1, "phase": "block", "no_progress_rounds": 0,
            "awaiting": {"emissions": 0, "last_emitted_at": None}, "audit": [],
        }
    else:
        state = prior
        prev = set(state["prev_set"])
        cset = set(current)
        seen_keys = {_set_key(s) for s in state["seen_sets"] if isinstance(s, list)}
        fps_seen = list(state["seen_fps"].get(ckey, []))
        if cset < prev and ckey not in seen_keys:
            outcome, reason = "progress", "strictly smaller never-seen finding set"
        elif cset == prev and world_fingerprint not in fps_seen:
            outcome, reason = "progress", "pinned fingerprint changed to a never-seen value"
        else:
            outcome = "no_progress"
            reason = "finding set/fingerprint revisited or not smaller"
        prior_phase = state["phase"]
        if ckey not in seen_keys:
            state["seen_sets"].append(current)
        if world_fingerprint not in fps_seen:
            fps_seen.append(world_fingerprint)
        state["seen_fps"][ckey] = fps_seen
        state["prev_set"] = current
        state["world_fp"] = world_fingerprint
        state["round"] += 1
        if outcome == "progress":
            if prior_phase == "awaiting_input":
                spent = state["awaiting"].setdefault("spent", [])
                sha = state["awaiting"].get("sha")
                if sha and sha not in spent:
                    spent.append(sha)
            state["phase"] = "block"
        else:
            state["no_progress_rounds"] += 1
            if prior_phase == "awaiting_input":
                state["phase"] = "awaiting_input"
                state["awaiting"]["emissions"] = int(state["awaiting"].get("emissions", 0)) + 1
                state["awaiting"]["last_emitted_at"] = stamp
            else:
                state["phase"] = "arbitration"
    state["last_outcome"] = outcome
    state["last_round_at"] = stamp

    text = json.dumps(state, ensure_ascii=False, sort_keys=True)
    written = None
    errors = []
    for target in (state_path, fallback_path):
        if target is None:
            continue
        try:
            _write_atomic(target, text)
            written = str(target)
            break
        except Exception as exc:  # never raises, never allows
            errors.append(f"{target}: {exc!r}")
    if written is None:
        return {
            "outcome": "unwritable", "phase": "awaiting_input",
            "round": state["round"], "no_progress_rounds": state["no_progress_rounds"],
            "reason": "state not writable: " + "; ".join(errors), "state_path": str(state_path),
        }
    return {
        "outcome": outcome, "phase": state["phase"], "round": state["round"],
        "no_progress_rounds": state["no_progress_rounds"], "reason": reason,
        "state_path": written,
    }


def _append_jsonl(path, record) -> None:
    if path is None:
        return
    try:
        os.makedirs(os.path.dirname(str(path)) or ".", exist_ok=True)
        with open(str(path), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def declare_awaiting_input(state_path, loop_key, verdict, current_finding_key, *,
                           audit_path=None, now=None):
    stamp = _now_str(now)
    try:
        sha = hashlib.sha256(
            json.dumps(verdict, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    except Exception:
        sha = "unhashable"
    v = verdict if isinstance(verdict, dict) else {}
    state = read_state(state_path)
    if state is not None and state["loop_key"] != loop_key:
        state = None

    def audit(kind: str, reason: str) -> None:
        record = {
            "ts": stamp, "kind": kind, "finding_key": v.get("finding_key"),
            "need": v.get("need"), "why": v.get("why"), "for": v.get("for"),
            "verdict_sha256": sha, "reason": reason,
        }
        if state is not None:
            for old in state["audit"]:
                if old.get("verdict_sha256") == sha and old.get("reason") == reason:
                    return
            state["audit"].append(record)
        _append_jsonl(audit_path, record)

    def reject(reason: str):
        audit("verdict_rejected", reason)
        if state is not None:
            try:
                _write_atomic(state_path, json.dumps(state, ensure_ascii=False, sort_keys=True))
            except Exception:
                pass
        return False, reason

    if state is None:
        return reject("no_state_for_loop")
    if not isinstance(verdict, dict):
        return reject("verdict_not_object")
    if verdict.get("verdict") != "awaiting_input":
        return reject("not_an_awaiting_input_verdict")
    if v.get("finding_key") != current_finding_key:
        return reject("finding_key_mismatch")
    if state["phase"] not in ("arbitration", "awaiting_input"):
        return reject("phase_not_arbitration")
    if not _nonempty(v.get("need")) or not _nonempty(v.get("why")):
        return reject("need_or_why_missing")
    if v["need"].strip() == v["why"].strip():
        return reject("need_equals_why")
    if v.get("for") not in _AWAITING_FOR:
        return reject("for_not_user_or_operator")
    awaiting = state["awaiting"]
    if state["phase"] != "awaiting_input" and sha in awaiting.get("spent", []):
        return reject("verdict_already_spent")

    audit("awaiting_input_declared", "accepted")
    if state["phase"] != "awaiting_input":
        awaiting["emissions"] = int(awaiting.get("emissions", 0)) + 1
        awaiting["last_emitted_at"] = stamp
        awaiting["declared_at"] = stamp
    awaiting.update({"need": v["need"], "why": v["why"], "for": v["for"], "sha": sha})
    state["phase"] = "awaiting_input"
    try:
        _write_atomic(state_path, json.dumps(state, ensure_ascii=False, sort_keys=True))
    except Exception as exc:
        return False, f"state_unwritable: {exc!r}"
    return True, "accepted"
