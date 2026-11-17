#!/usr/bin/env python3
"""Who last wrote each gate-read QA report: the provenance the e2e stop gate checks (CD-6).

hooks/subagentstop-e2e-enforce.py judges the ``e2e_enforcement.status`` of the qa-report.v2
a QA's dispatch declares. A report the orchestrator (the main agent) wrote is not the QA's
evidence. No reading of a command line can list every route that writes a file, so the
writer is measured, not parsed:

* ``observe`` runs on every tool call's PreToolUse (hooks/pretool-tool-policy.py, the
  caller known from the payload's ``agent_id``, the call from its ``tool_use_id``). It
  looks at every ``<project>/docs/dev/qa-report-*.json`` and at every path a QA dispatch
  of the session declares as its qa-report.v2 (a started subagent's obligation, the
  dispatch this call makes, every path declared before: the ledger's watch list), with no
  limit on their number. A file whose content (sha256) differs from what the ledger last
  recorded for it gets a record naming the caller as its writer. The main agent cannot
  act between its own calls, and a synchronous dispatch is one of its calls, so a report
  the main agent changed is first seen at its own next PreToolUse, at the latest the
  dispatch of the QA that will be judged on it: the writer recorded is "main". One
  exception: while a QA the main agent launched in the background (an ``async_launched``
  Agent result with no task notification yet) declares the path, a change the main
  agent's call sees first is that QA's (its own write, /do), unless the main agent's
  previous call names the path as a write target.
* ``verdict`` is the gate's question: does the report's current content come from the
  main agent? It finds the latest record of that content and trusts a subagent's record
  only when the CLI's own transcript of that subagent holds the observing call
  (``tool_use_id``) at about the time recorded (a background QA's record, the main
  agent's call and that QA's launch). A record without that witness (a hand-made
  ``observe()`` call with an invented agent id or call) counts as the main agent's.

The ledger is one JSON file per (session, project) under the harness state dir
(lib/harness_state_dir.py), ``report-provenance/<key>.json``; nothing is written into the
project. Its records form a hash chain (each record's ``h`` covers its fields and the
previous record's ``h``; the document's ``head`` is the last one). The gate fails
closed: a ledger that cannot be read, locked or written (its directory replaced by a
file, made unwritable, held locked; the file unparsable; the chain broken by an edit
or a deleted record) refuses the QA whose declared report exists. tool-policy refuses
an agent's write, delete or rename of the ledger directory as a protected path.

Limit, stated plainly: an agent that runs arbitrary code with the user's permissions can
rewrite any local state, this ledger included (recompute the chain, borrow a real call
id within its time window). The ledger makes the cheap, one-call forms detectable and
refused (moving or replacing the directory, editing a record, an out-of-band
``observe()`` with an invented agent id); it is not a cryptographic proof.
"""
from __future__ import annotations

import fcntl
import glob
import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

REPORT_GLOB = os.path.join("docs", "dev", "qa-report-*.json")
MAIN = "main"
VERSION = 2
NOTE = ("Hook-written provenance of gate-read QA reports (hooks/lib/report_provenance.py). "
        "An agent able to run arbitrary code with the user's permissions can tamper with any "
        "local state; this chain makes the cheap forms detectable, it is no cryptographic proof.")
_LOCK_WAIT = 2.0
_BEFORE = 120.0     # a record may precede its call's transcript timestamp by this much (clock skew)
_AFTER = 1800.0     # and follow it by this much (the call waiting on a permission prompt)
_QA_SCHEMA = "qa-report.v2"


class LedgerError(Exception):
    """The ledger cannot be trusted: the gate refuses (fail closed)."""


def _root(project_dir) -> str | None:
    try:
        return os.path.realpath(str(project_dir)) if project_dir else None
    except (OSError, ValueError):
        return None


def ledger_path(session_id: str, project_dir) -> str | None:
    root = _root(project_dir)
    if not root or not isinstance(session_id, str) or not session_id:
        return None
    from lib.harness_state_dir import harness_state_dir

    key = hashlib.sha256(f"{session_id}\0{root}".encode("utf-8", "surrogateescape")).hexdigest()[:32]
    return os.path.join(ledger_dir(harness_state_dir()), f"{key}.json")


def ledger_dir(state_dir: str) -> str:
    """The ledger directory under ``state_dir`` (tool-policy protects it)."""
    return os.path.join(state_dir, "report-provenance")


def _sha(path: str) -> str | None:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 16), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _stat(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_mtime_ns, st.st_size, st.st_ino, st.st_ctime_ns]


def _norm(rel) -> str | None:
    if not isinstance(rel, str) or not rel or os.path.isabs(rel) or "\x00" in rel:
        return None
    rel = os.path.normpath(rel)
    return None if rel == os.pardir or rel.startswith(os.pardir + os.sep) else rel


# -- the hash chain ----------------------------------------------------------------
def _digest(record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "h"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _check_chain(doc) -> list:
    """The records of a ledger document, or LedgerError when it is not one the hook wrote."""
    if not isinstance(doc, dict) or doc.get("v") != VERSION:
        raise LedgerError("the ledger is not a version-2 provenance ledger")
    records = doc.get("records")
    if not isinstance(records, list):
        raise LedgerError("the ledger holds no record list")
    prev = ""
    for number, record in enumerate(records, 1):
        if not isinstance(record, dict) or record.get("seq") != number or record.get("prev") != prev:
            raise LedgerError(f"record {number} breaks the chain (a record edited, deleted or reordered)")
        if record.get("h") != _digest(record):
            raise LedgerError(f"record {number} does not match its hash (a record edited)")
        prev = record["h"]
    if doc.get("head", "") != prev:
        raise LedgerError("the ledger's head does not match its last record (records deleted)")
    return records


def _read(path: str) -> dict | None:
    """The ledger document at ``path``; None when there is none; LedgerError when unreadable."""
    if not os.path.lexists(path):
        return None
    if os.path.islink(path) or not os.path.isfile(path):
        raise LedgerError("the ledger is not a regular file")
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, ValueError) as exc:
        raise LedgerError(f"the ledger cannot be read ({exc.__class__.__name__})") from exc
    _check_chain(doc)
    return doc


def _latest(records: list) -> dict:
    """{path: its latest record}."""
    out = {}
    for record in records:
        out[record.get("path")] = record
    return out


# -- what the session's QA dispatches declare ---------------------------------------
def declared_in_prompt(prompt) -> list:
    """The qa-report.v2 paths an obligation block in ``prompt`` declares (repo-relative)."""
    if not isinstance(prompt, str) or "<obligation" not in prompt or _QA_SCHEMA not in prompt:
        return []
    try:
        from lib import obligation

        parsed = obligation.parse_obligation(prompt)
        if not isinstance(parsed, obligation.ParsedObligation):
            return []
        out = []
        for artifact in parsed.obligation.get("artifacts") or []:
            if isinstance(artifact, dict) and artifact.get("schema") == _QA_SCHEMA:
                rel = _norm(artifact.get("path"))
                if rel:
                    out.append(rel)
        return out
    except Exception:
        return []


def _subagents(session_transcript) -> Path | None:
    if not session_transcript:
        return None
    path = Path(str(session_transcript))
    return path.with_suffix("") / "subagents"


def started_declarations(session_transcript) -> dict:
    """{agent_id: [declared qa-report.v2 paths]} of every subagent the CLI started in the session."""
    folder = _subagents(session_transcript)
    out = {}
    try:
        names = sorted(n for n in os.listdir(folder) if n.startswith("agent-") and n.endswith(".jsonl"))
    except (OSError, TypeError):
        return out
    from lib import obligation

    for name in names:
        try:
            prompt = obligation.read_first_record_prompt(folder / name)
        except Exception:
            continue
        paths = declared_in_prompt(prompt)
        if paths:
            out[name[len("agent-"):-len(".jsonl")]] = paths
    return out


def declared_reports(session_id, project_dir, session_transcript) -> set:
    """Every path a QA dispatch of the session declares or declared (started subagents and the
    ledger's watch list). Read-only; never raises."""
    found = set()
    for paths in started_declarations(session_transcript).values():
        found.update(paths)
    try:
        ledger = ledger_path(session_id, project_dir)
        doc = _read(ledger) if ledger else None
        if doc:
            found.update(r for r in doc.get("watch") or [] if _norm(r))
    except Exception:
        pass
    return found


# -- the session transcript: background QAs, the main agent's previous call -----------
def _iso(value) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _session_reading(session_transcript, call=None) -> dict:
    """One pass over the session transcript: the Agent calls launched in the background
    (``async_launched``) and not yet notified, their declared paths, and the main agent's
    tool calls (id -> (name, input, timestamp))."""
    out = {"running": {}, "launched": set(), "calls": {}, "order": []}
    try:
        from lib import subagent_restart as restart
    except Exception:
        restart = None
    try:
        handle = open(str(session_transcript), encoding="utf-8", errors="replace")
    except (OSError, TypeError, ValueError):
        return out
    dispatch_prompts, notified = {}, set()
    with handle:
        for line in handle:
            if restart is not None and "task-notification" in line:
                for body in restart._iter_notification_blocks(line):
                    found = restart.TASK_NOTIFICATION_RE.search(body)
                    if found:
                        notified.add(found.group(1).strip())
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict) or record.get("isSidechain"):
                continue
            message = record.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            for block in content if isinstance(content, list) else ():
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and isinstance(block.get("id"), str):
                    tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
                    out["calls"][block["id"]] = (block.get("name"), tool_input, _iso(record.get("timestamp")))
                    out["order"].append(block["id"])
                    if block.get("name") in ("Agent", "Task"):
                        dispatch_prompts[block["id"]] = tool_input.get("prompt")
                elif block.get("type") == "tool_result" and block.get("tool_use_id") in dispatch_prompts:
                    own = record.get("toolUseResult")
                    if isinstance(own, dict) and own.get("status") == "async_launched" \
                            and isinstance(own.get("agentId"), str):
                        agent = own["agentId"]
                        out["launched"].add(agent)
                        out["running"][agent] = declared_in_prompt(dispatch_prompts[block["tool_use_id"]])
    for agent in notified:
        out["running"].pop(agent, None)
    return out


def _previous_main_call_writes(reading: dict, call, root: str, rel: str) -> bool:
    """The main agent's call before ``call`` names ``rel`` as a write target (a file tool's
    path, a Bash write target lib/bash_write_targets.py reads)."""
    order = [c for c in reading["order"] if c != call]
    if not order:
        return False
    name, tool_input, _ts = reading["calls"][order[-1]]
    want = os.path.normpath(os.path.join(root, rel))
    targets = []
    if name in ("Write", "Edit", "MultiEdit"):
        targets = [tool_input.get("file_path")]
    elif name == "NotebookEdit":
        targets = [tool_input.get("notebook_path")]
    elif name == "Bash" and isinstance(tool_input.get("command"), str):
        try:
            from lib import bash_write_targets as bwt

            targets = [str(t) for t in bwt.extract_bash_write_paths(tool_input["command"])]
        except Exception:
            targets = []
    for target in targets:
        if isinstance(target, str) and target and \
                os.path.normpath(os.path.join(root, os.path.expanduser(target))) == want:
            return True
    return False


# -- observe (PreToolUse) ----------------------------------------------------------
def observe(session_id: str, project_dir, actor: str, call=None, session_transcript=None,
            declared=()) -> None:
    """Record ``actor`` ("main" or a subagent's agent_id), observing in the call ``call``
    (the payload's tool_use_id), as the writer of every watched report of ``project_dir``
    whose content changed since the ledger last recorded it. ``declared``: the paths the
    calling dispatch itself declares. Never raises; records nothing it cannot."""
    try:
        root = _root(project_dir)
        ledger = ledger_path(session_id, project_dir)
        if not root or not ledger or not actor:
            return
        started = started_declarations(session_transcript)
        watch_new = {r for r in (_norm(d) for d in declared or ()) if r}
        for paths in started.values():
            watch_new.update(paths)
        reports = {os.path.relpath(p, root) for p in glob.glob(os.path.join(glob.escape(root), REPORT_GLOB))}
        if not reports and not watch_new and not os.path.exists(ledger):
            return
        os.makedirs(os.path.dirname(ledger), mode=0o700, exist_ok=True)
        with open(ledger + ".lock", "a") as lock:
            deadline = time.monotonic() + _LOCK_WAIT
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        return
                    time.sleep(0.02)
            try:
                doc = _read(ledger) or {"v": VERSION, "note": NOTE, "head": "", "records": [], "watch": []}
            except LedgerError:
                return  # never repaired here: the gate refuses on it
            records = doc["records"]
            watch = set(r for r in doc.get("watch") or [] if _norm(r)) | watch_new
            latest = _latest(records)
            reading = None
            changed = sorted(watch - set(doc.get("watch") or [])) != []
            for rel in sorted(reports | watch | {p for p in latest if isinstance(p, str)}):
                path = os.path.join(root, rel)
                entry = latest.get(rel)
                stat = _stat(path)
                if stat is None:
                    if entry and entry.get("sha") is not None:
                        _append(doc, rel, None, None, actor, actor, call)
                        changed = True
                    continue
                if entry and entry.get("stat") == stat:
                    continue
                sha = _sha(path)
                if sha is None or (entry and entry.get("sha") == sha):
                    continue  # same content: the writer stays (a touch changes no writer)
                writer = actor
                if actor == MAIN:
                    if reading is None:
                        reading = _session_reading(session_transcript, call)
                    declarers = [a for a, paths in reading["running"].items() if rel in paths]
                    if declarers and not _previous_main_call_writes(reading, call, root, rel):
                        writer = declarers[-1]
                _append(doc, rel, sha, stat, writer, actor, call)
                changed = True
            doc["watch"] = sorted(watch)
            if changed:
                tmp = f"{ledger}.{os.getpid()}.tmp"
                with open(tmp, "w", encoding="utf-8") as handle:
                    json.dump(doc, handle)
                os.replace(tmp, ledger)
    except Exception:
        return


def _append(doc: dict, rel: str, sha, stat, writer: str, observer: str, call) -> None:
    records = doc["records"]
    record = {"seq": len(records) + 1, "path": rel, "sha": sha, "stat": stat, "actor": writer,
              "by": observer, "call": call if isinstance(call, str) else None, "at": time.time(),
              "prev": doc.get("head", "")}
    record["h"] = _digest(record)
    records.append(record)
    doc["head"] = record["h"]


# -- the gate's reading (SubagentStop) ------------------------------------------------
def _health(ledger: str) -> dict | None:
    """The ledger document (None when there is none yet); LedgerError when the ledger, its
    directory or its lock cannot serve a recording."""
    folder = os.path.dirname(ledger)
    if os.path.lexists(folder):
        if os.path.islink(folder) or not os.path.isdir(folder):
            raise LedgerError(f"the ledger directory {folder} is not a directory")
        if not os.access(folder, os.W_OK | os.X_OK):
            raise LedgerError(f"the ledger directory {folder} is not writable")
    else:
        # None recorded yet; the first existing ancestor must let an observation create it.
        parent = os.path.dirname(folder)
        while not os.path.lexists(parent) and os.path.dirname(parent) != parent:
            parent = os.path.dirname(parent)
        if not os.path.isdir(parent) or not os.access(parent, os.W_OK | os.X_OK):
            raise LedgerError(f"{parent} cannot hold the ledger directory")
        return None
    lock_path = ledger + ".lock"
    if os.path.lexists(lock_path):
        try:
            with open(lock_path, "a") as lock:
                deadline = time.monotonic() + _LOCK_WAIT
                while True:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise LedgerError("the ledger is held locked, so no observation could record")
                        time.sleep(0.02)
                return _read(ledger)
        except OSError as exc:
            raise LedgerError(f"the ledger lock cannot be opened ({exc.__class__.__name__})") from exc
    return _read(ledger)


def _call_time(transcript, call) -> float | None:
    """The timestamp of the tool_use ``call`` in ``transcript``; None when it is not there."""
    try:
        handle = open(str(transcript), encoding="utf-8", errors="replace")
    except (OSError, TypeError, ValueError):
        return None
    with handle:
        for line in handle:
            if call not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            message = record.get("message") if isinstance(record, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            for block in content if isinstance(content, list) else ():
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id") == call:
                    return _iso(record.get("timestamp"))
    return None


def _witnessed(record: dict, session_transcript, reading_cache: dict) -> bool:
    """A subagent's record holds only when the CLI's transcript holds its observing call,
    at about the time recorded."""
    call, at, actor, by = record.get("call"), record.get("at"), record.get("actor"), record.get("by")
    if not isinstance(call, str) or not call or not isinstance(at, (int, float)):
        return False
    if by == MAIN:  # a background QA's change the main agent's call saw first
        if "r" not in reading_cache:
            reading_cache["r"] = _session_reading(session_transcript)
        reading = reading_cache["r"]
        if actor not in reading["launched"] or call not in reading["calls"]:
            return False
        stamp = reading["calls"][call][2]
    else:
        if by != actor:
            return False
        folder = _subagents(session_transcript)
        if folder is None or not isinstance(actor, str) or "/" in actor or not actor:
            return False
        stamp = _call_time(folder / f"agent-{actor}.jsonl", call)
    return stamp is not None and stamp - _BEFORE <= at <= stamp + _AFTER


def verdict(session_id: str, project_dir, rel: str, session_transcript=None) -> str | None:
    """"main" when report ``rel``'s current content comes from the main agent: the latest
    record of that content is the main agent's, or a subagent's no transcript witnesses;
    None when it does not (or no record holds it). LedgerError when the ledger cannot be
    trusted (the gate refuses)."""
    root = _root(project_dir)
    ledger = ledger_path(session_id, project_dir)
    rel = _norm(rel)
    if not root or not ledger or not rel:
        return None
    doc = _health(ledger)
    if doc is None:
        return None
    current = _sha(os.path.join(root, rel))
    if current is None:
        return None
    cache: dict = {}
    for record in reversed(doc["records"]):
        if record.get("path") != rel or record.get("sha") != current:
            continue
        if record.get("actor") == MAIN or not _witnessed(record, session_transcript, cache):
            return MAIN
        return None
    return None


def held_by_main(session_id: str, project_dir, rel: str, session_transcript=None) -> bool:
    """verdict() == "main"; an untrustworthy ledger counts as the main agent's."""
    try:
        return verdict(session_id, project_dir, rel, session_transcript) == MAIN
    except LedgerError:
        return True
    except Exception:
        return False


def own_write(transcript_path, project_dir, rel: str) -> bool:
    """The agent's own transcript shows a Write of ``rel`` with an ok result whose content is
    the report's current content: the agent authored exactly these bytes. A Bash command,
    a touch, an append of nothing or an Edit leaves the main agent's content as it was and
    is no write of the QA's own (judged by content, not by the command)."""
    try:
        root = _root(project_dir)
        want = os.path.normpath(os.path.join(root, rel))
        with open(want, encoding="utf-8", errors="replace") as handle:
            current = handle.read().rstrip()
        writes, ok = [], set()
        with open(str(transcript_path), encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                message = record.get("message") if isinstance(record, dict) else None
                content = message.get("content") if isinstance(message, dict) else None
                cwd = record.get("cwd") or root
                for block in content if isinstance(content, list) else ():
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use" and block.get("name") == "Write" \
                            and isinstance(block.get("input"), dict):
                        target = block["input"].get("file_path")
                        text = block["input"].get("content")
                        if isinstance(target, str) and isinstance(text, str) and \
                                os.path.normpath(os.path.join(cwd, os.path.expanduser(target))) == want:
                            writes.append((block.get("id"), text))
                    elif block.get("type") == "tool_result" and not block.get("is_error"):
                        ok.add(block.get("tool_use_id"))
        return any(ident in ok and text.rstrip() == current for ident, text in writes)
    except Exception:
        return False
