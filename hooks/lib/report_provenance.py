#!/usr/bin/env python3
"""Who last wrote each gate-read QA report: the provenance the e2e stop gate checks (CD-6).

hooks/subagentstop-e2e-enforce.py judges the ``e2e_enforcement.status`` of the qa-report.v2
a QA's dispatch declares. A report the orchestrator (the main agent) wrote is not the QA's
evidence. No reading of a command line can list every route that writes a file, so the
writer is measured, not parsed:

* ``observe_call`` is the PreToolUse hook's entry (hooks/pretool-tool-policy.py, with the CLI's
  payload: the caller from ``agent_id``, the call from ``tool_use_id``). It first writes the
  call into the ledger's call stream: a QA dispatch of the main agent as a launch record (its
  declared qa-report.v2 paths, whether it runs in the background, its prompt's sha256), a
  subagent's first call with the sha256 of the prompt its own transcript holds then (the link
  to its launch), any call that records a change, and the main agent's call after anything
  else. Then it looks at every ``<project>/docs/dev/qa-report-*.json`` and every path a QA
  dispatch of the session declares (the ledger's watch list), with no limit on their number.
  A file whose content (sha256) differs from what the ledger last recorded for it gets a
  record naming the caller as its writer. The main agent cannot act between its own calls,
  and a synchronous dispatch is one of its calls, so a report the main agent changed is first
  seen at its own next PreToolUse, at the latest the dispatch of the QA that will be judged on
  it: the writer recorded is "main". One exception: while a QA dispatch the main agent made in
  the background (a launch record) has a started subagent (a call record linked to it) that
  declares the path and that no task notification names, a change the main agent's call sees
  first is that QA's (its own write, /do), unless the main agent's previous call names the
  path as a write target.
* ``observe`` (out of band: no payload) records changes but no call: its records are no
  subagent's to the gate, whatever agent id and call it names. This holds for ``observe``
  only: ``observe_call`` and the hook entry trust the payload they are given, so code that
  calls either with a payload it makes up writes records the gate trusts. The main agent's
  literal forms of that (a Bash call running a PreToolUse/SubagentStart/SubagentStop hook
  entry by hand, or code naming this module, ``observe_call`` or its state dir) are refused at
  PreToolUse by hooks/pretool-tool-policy.py (_check_hook_replay).
* ``verdict`` is the gate's question: does the report's current content come from the main
  agent? It finds the latest record of that content and trusts a subagent's record only when
  the hook wrote its witnesses: the call record of the observing caller's same call directly
  precedes it, and the writer is a subagent linked to a launch record declaring the path (the
  main agent's call observed it only for a background launch). Anything else counts as the
  main agent's. No transcript content is evidence of a launch or a witness, since the main
  agent can append to a transcript: a transcript is read only where a forged line refuses
  more (a task notification ends a background QA's window; the main agent's previous call
  naming the report keeps the change the main agent's) or widens the watch list.

The ledger is one JSON file per (session, project) under the harness state dir
(lib/harness_state_dir.py), ``report-provenance/<key>.json``; nothing is written into the
project. Its records form a hash chain (each record's ``h`` covers its fields and the
previous record's ``h``; the document's ``head`` is the last one), and a head witness
``<key>.head`` beside it holds the length and head the hook last wrote, so a ledger older than
the history last seen (an earlier snapshot copied back, a prefix with its head reset, the
ledger or the witness deleted alone) is refused. The gate fails closed: a ledger that cannot be read, locked or written (its directory replaced by a
file, made unwritable, held locked; the file unparsable; the chain broken by an edit
or a deleted record, older than its witness) refuses the QA whose declared report exists.
The gate also refuses a report whose trusted writer is a subagent other than the QA judged. tool-policy refuses an
agent's write, delete or rename of the ledger directory when the target is one its Bash
reader reads or a file tool's path; a rename or delete by an interpreter, ``find -delete``
or a computed name is not seen there, and gains nothing: the next observation starts a new
ledger and records the report's current content as the main agent's.

Limit, stated plainly (accepted): code running with the user's permissions can always run
the hook's own code path, and no local scheme can tell the records it makes apart from the
CLI's without a secret the agent cannot read. Such code can recompute the chain, restore the
ledger and its witness together, run the hook's entry or ``observe_call`` with a payload it
makes up (under a computed name, from a file an earlier call staged, as a copy of the hook,
through a subagent), or borrow the call of a background QA while it runs. The ledger makes
the cheap forms detectable and refused (moving, deleting or replacing the directory, editing
a record, a restored snapshot or truncated prefix, a fake launch or subagent call appended to
a transcript, an out-of-band ``observe()`` under any agent id and call, the main agent's
literal run of the hook entry or the module); it is not a cryptographic proof.
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

from lib import command_span

REPORT_GLOB = os.path.join("docs", "dev", "qa-report-*.json")
MAIN = "main"
VERSION = 2
NOTE = ("Hook-written provenance of gate-read QA reports (hooks/lib/report_provenance.py). "
        "An agent able to run arbitrary code with the user's permissions can tamper with any "
        "local state; this chain makes the cheap forms detectable, it is no cryptographic proof.")
_LOCK_WAIT = 2.0
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


def witness_path(ledger: str) -> str:
    """The head witness beside ``ledger``: the length and head the hook last wrote it with."""
    return (ledger[:-len(".json")] if ledger.endswith(".json") else ledger) + ".head"


def _witness(ledger: str) -> dict | None:
    path = witness_path(ledger)
    if not os.path.lexists(path):
        return None
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            raise ValueError("not a regular file")
        with open(path, encoding="utf-8") as handle:
            found = json.load(handle)
        if not isinstance(found, dict) or not isinstance(found.get("seq"), int) or found["seq"] < 1 \
                or not isinstance(found.get("head"), str):
            raise ValueError("not a head witness")
    except (OSError, ValueError) as exc:
        raise LedgerError(f"the ledger's head witness cannot be read ({exc})") from exc
    return found


def _check_history(ledger: str, records) -> None:
    """The ledger holds the history its head witness last saw: at least that many records, the
    witnessed head among them at its place. A snapshot copied back over the ledger, a prefix with
    its head reset, a deleted ledger or witness all fail it (LedgerError)."""
    seen = _witness(ledger)
    if records is None:
        if seen is not None:
            raise LedgerError("the ledger is gone while its head witness remains (the ledger deleted or moved)")
        return
    if seen is None:
        if records:
            raise LedgerError("the ledger has records but no head witness (the witness deleted)")
        return
    if len(records) < seen["seq"] or records[seen["seq"] - 1].get("h") != seen["head"]:
        raise LedgerError("the ledger is older than the history last seen (an earlier snapshot restored or "
                          "the ledger truncated)")


def _write_witness(ledger: str, doc: dict) -> None:
    if not doc["records"]:
        return
    path = witness_path(ledger)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"seq": len(doc["records"]), "head": doc["head"]}, handle)
    os.replace(tmp, path)


def _read(path: str) -> dict | None:
    """The ledger document at ``path``; None when there is none (and no head witness); LedgerError
    when unreadable or older than its head witness."""
    if not os.path.lexists(path):
        _check_history(path, None)
        return None
    if os.path.islink(path) or not os.path.isfile(path):
        raise LedgerError("the ledger is not a regular file")
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, ValueError) as exc:
        raise LedgerError(f"the ledger cannot be read ({exc.__class__.__name__})") from exc
    _check_history(path, _check_chain(doc))
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


# -- the session transcript: task notifications, the main agent's previous call ------
# Transcript content is no evidence that a QA was launched or acted: anything there the main
# agent can append. It is read only where a forged line can refuse more, never pass more: a
# task notification ends a background QA's window; the main agent's previous call naming a
# report as its write target keeps the change the main agent's.
def _iso(value) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _session_reading(session_transcript, call=None) -> dict:
    """One pass over the session transcript: the agent ids a task notification names, and the
    main agent's tool calls (id -> (name, input, timestamp)) in order."""
    out = {"notified": set(), "calls": {}, "order": []}
    try:
        from lib import subagent_restart as restart
    except Exception:
        restart = None
    try:
        handle = open(str(session_transcript), encoding="utf-8", errors="replace")
    except (OSError, TypeError, ValueError):
        return out
    with handle:
        for line in handle:
            if restart is not None and "task-notification" in line:
                for body in restart._iter_notification_blocks(line):
                    found = restart.TASK_NOTIFICATION_RE.search(body)
                    if found:
                        out["notified"].add(found.group(1).strip())
            try:
                record = json.loads(line)
            except ValueError:
                continue
            for block in command_span._blocks(record):
                if block.get("type") == "tool_use" and isinstance(block.get("id"), str):
                    tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
                    out["calls"][block["id"]] = (block.get("name"), tool_input, _iso(record.get("timestamp")))
                    out["order"].append(block["id"])
    return out


def _previous_main_call_writes(reading: dict, call, root: str, rel: str) -> bool:
    """The main agent's call before ``call`` names ``rel`` as a write target (a file tool's
    path, a Bash write target lib/bash_write_targets.py reads)."""
    order = [c for c in reading["order"] if c != call]
    if not order:
        return False
    name, tool_input, _ts = reading["calls"][order[-1]]
    want = os.path.normpath(os.path.join(root, rel))
    from lib.spec_path import EDIT_TOOLS  # the tools that name their target in file_path
    targets = []
    if name in EDIT_TOOLS:
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


# -- the hook-written call stream ---------------------------------------------------------
def _prompt_sha(prompt) -> str | None:
    if not isinstance(prompt, str) or not prompt:
        return None
    return hashlib.sha256(prompt.encode("utf-8", "surrogateescape")).hexdigest()


def _is_call(record) -> bool:
    return isinstance(record, dict) and record.get("k") == "call"


def _links(records: list, upto: int | None = None) -> dict:
    """{agent_id: (its first call record's index, the launch record's index or None)}: the
    QA dispatch of the main agent, recorded at that dispatch's PreToolUse, whose prompt is the
    one the subagent's own transcript held when the hook first saw the subagent call (the
    latest such launch before that call)."""
    out, launches = {}, {}
    for index, record in enumerate(records[:upto] if upto is not None else records):
        if not _is_call(record):
            continue
        if record.get("agent") == MAIN and isinstance(record.get("launch"), dict):
            launches[record["launch"].get("prompt")] = index
        elif record.get("agent") != MAIN and record.get("agent") not in out:
            link = record.get("link")
            out[record.get("agent")] = (index, launches.get(link) if isinstance(link, str) else None)
    return out


def _running(records: list, rel: str, notified: set) -> list:
    """The agents a background QA dispatch of the main agent declaring ``rel`` started, each
    seen by the hook calling a tool, with no task notification read for it."""
    out = []
    for agent, (_first, launch) in _links(records).items():
        if launch is None or agent in notified:
            continue
        spec = records[launch]["launch"]
        if spec.get("bg") is True and rel in (spec.get("declared") or []):
            out.append(agent)
    return out


def _current_call(data: dict):
    """(session_id, project, actor, call, tool_name, tool_input, session_transcript) of a hook payload."""
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    project = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd")
    raw = data.get("transcript_path")
    transcript = None
    if isinstance(raw, str) and raw:
        path = Path(raw)
        if path.parent.name == "subagents":  # <sid>/subagents/agent-x.jsonl -> <sid>.jsonl
            path = path.parent.parent.parent / f"{path.parent.parent.name}.jsonl"
        transcript = path
    return (data.get("session_id"), project, data.get("agent_id") or MAIN, data.get("tool_use_id"),
            data.get("tool_name"), tool_input, transcript)


# -- observe (PreToolUse) ----------------------------------------------------------
def observe_call(data: dict) -> None:
    """The PreToolUse hook's entry (hooks/pretool-tool-policy.py, with the CLI's payload): record
    this call in the ledger's call stream, then every watched report it sees changed (observe).
    Only this entry writes call records; a record of a subagent's is trusted only when the call
    record of that subagent's same call precedes it directly. Never raises."""
    try:
        sid, project, actor, call, tool, tool_input, transcript = _current_call(data)
        if not isinstance(call, str) or not call:
            return
        info = {}
        declared = ()
        from lib.subagent import DISPATCH_TOOLS
        if actor == MAIN and tool in DISPATCH_TOOLS:
            declared = declared_in_prompt(tool_input.get("prompt"))
            if declared:
                info["launch"] = {"bg": tool_input.get("run_in_background") is True,
                                  "prompt": _prompt_sha(tool_input.get("prompt")), "declared": sorted(declared)}
        _observe(sid, project, actor, call, transcript, declared, hooked=info)
    except Exception:
        return


def observe(session_id: str, project_dir, actor: str, call=None, session_transcript=None,
            declared=()) -> None:
    """Record ``actor`` as the writer of every watched report of ``project_dir`` whose content
    changed since the ledger last recorded it, with no call record: a record made this way,
    out of band, is one no gate trusts as a subagent's. Never raises."""
    try:
        _observe(session_id, project_dir, actor, call, session_transcript, declared, hooked=None)
    except Exception:
        return


def _observe(session_id, project_dir, actor, call, session_transcript, declared, hooked) -> None:
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
        changed = sorted(watch - set(doc.get("watch") or [])) != []
        reading = None
        changes = []
        for rel in sorted(reports | watch | {p for p in latest if isinstance(p, str)}):
            path = os.path.join(root, rel)
            entry = latest.get(rel)
            stat = _stat(path)
            if stat is None:
                if entry and entry.get("sha") is not None:
                    changes.append((rel, None, None, actor))
                continue
            if entry and entry.get("stat") == stat:
                continue
            sha = _sha(path)
            if sha is None or (entry and entry.get("sha") == sha):
                continue  # same content: the writer stays (a touch changes no writer)
            writer = actor
            if actor == MAIN and hooked is not None:
                if reading is None:
                    reading = _session_reading(session_transcript, call)
                declarers = _running(records, rel, reading["notified"])
                if declarers and not _previous_main_call_writes(reading, call, root, rel):
                    writer = declarers[-1]
            changes.append((rel, sha, stat, writer))
        if hooked is not None:
            last = records[-1] if records else None
            seen = actor == MAIN or any(_is_call(r) and r.get("agent") == actor for r in records)
            if changes or hooked.get("launch") or not seen or \
                    (actor == MAIN and not (_is_call(last) and last.get("agent") == MAIN)):
                extra = dict(hooked)
                if not seen:
                    try:
                        from lib import obligation

                        folder = _subagents(session_transcript)
                        extra["link"] = _prompt_sha(obligation.read_first_record_prompt(
                            folder / f"agent-{actor}.jsonl")) if folder and "/" not in actor else None
                    except Exception:
                        extra["link"] = None
                _append_call(doc, actor, call, extra)
                changed = True
        for rel, sha, stat, writer in changes:
            _append(doc, rel, sha, stat, writer, actor, call)
            changed = True
        doc["watch"] = sorted(watch)
        if changed:
            tmp = f"{ledger}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(doc, handle)
            os.replace(tmp, ledger)  # the ledger first: a crash between leaves it ahead, never behind
            _write_witness(ledger, doc)


def _chain(doc: dict, record: dict) -> None:
    records = doc["records"]
    record.update(seq=len(records) + 1, at=time.time(), prev=doc.get("head", ""))
    record["h"] = _digest(record)
    records.append(record)
    doc["head"] = record["h"]


def _append_call(doc: dict, agent: str, call: str, extra: dict) -> None:
    _chain(doc, {"k": "call", "agent": agent, "path": None, "actor": agent, "by": agent, "call": call, **extra})


def _append(doc: dict, rel: str, sha, stat, writer: str, observer: str, call) -> None:
    _chain(doc, {"path": rel, "sha": sha, "stat": stat, "actor": writer, "by": observer,
                 "call": call if isinstance(call, str) else None})


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


def _trusted(records: list, index: int, rel: str) -> bool:
    """A record naming a subagent as the writer holds only when the hook wrote its witnesses:
    the call record of the observing caller's same call directly precedes it (records of that
    call aside), the writer is a subagent the hook saw calling a tool, started by a QA dispatch
    of the main agent whose launch record (written at that dispatch's PreToolUse) declares
    ``rel``; the main agent's call observed it only for a background dispatch's subagent (whose
    running observe judged)."""
    record = records[index]
    call, by, actor = record.get("call"), record.get("by"), record.get("actor")
    if not isinstance(call, str) or not call or not isinstance(actor, str) or actor == MAIN:
        return False
    j = index - 1
    while j >= 0 and not _is_call(records[j]) and records[j].get("call") == call and records[j].get("by") == by:
        j -= 1
    if j < 0 or not _is_call(records[j]) or records[j].get("agent") != by or records[j].get("call") != call:
        return False
    first, launch = _links(records, index).get(actor, (None, None))
    if launch is None:
        return False
    spec = records[launch].get("launch") or {}
    if rel not in (spec.get("declared") or []):
        return False
    return by in (actor, MAIN) if spec.get("bg") is True else by == actor


def _same_round(records: list, index: int, rel: str, agent_transcript) -> bool:
    """The QA whose stop is judged was already launched, by a launch record declaring ``rel``,
    when record ``index`` was written: the latest launch record whose prompt is the one its own
    transcript holds precedes the record (parallel QAs of one round; a QA launched after another
    QA wrote the report is of a later round)."""
    try:
        from lib import obligation

        sha = _prompt_sha(obligation.read_first_record_prompt(agent_transcript)) if agent_transcript else None
    except Exception:
        sha = None
    if not sha:
        return False
    launch = None
    for j, record in enumerate(records):
        spec = record.get("launch") if _is_call(record) and record.get("agent") == MAIN else None
        if isinstance(spec, dict) and spec.get("prompt") == sha and rel in (spec.get("declared") or []):
            launch = j
    return launch is not None and launch < index


def verdict(session_id: str, project_dir, rel: str, session_transcript=None, agent=None,
            agent_transcript=None) -> str | None:
    """"main" when report ``rel``'s current content comes from the main agent: the latest
    record of that content is the main agent's, or a subagent's whose witnesses the hook did
    not write (_trusted); with ``agent`` (the QA whose stop is judged, ``agent_transcript`` its
    own transcript), the trusted writer's agent id when it is another subagent of an earlier
    round (_same_round: a QA launched after another QA wrote the content is not judged on it);
    None when it is ``agent``, a parallel QA of the same round, or no record holds it. LedgerError when
    the ledger cannot be trusted (the gate refuses). ``session_transcript`` is not read: no
    transcript content is evidence of a launch or a witness."""
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
    records = doc["records"]
    for index in range(len(records) - 1, -1, -1):
        record = records[index]
        if _is_call(record) or record.get("path") != rel or record.get("sha") != current:
            continue
        if record.get("actor") == MAIN or not _trusted(records, index, rel):
            return MAIN
        if isinstance(agent, str) and agent and record.get("actor") != agent and \
                not _same_round(records, index, rel, agent_transcript):
            return record.get("actor")
        return None
    return None


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
                cwd = record.get("cwd") or root
                for block in command_span._blocks(record, sidechain=True):
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
