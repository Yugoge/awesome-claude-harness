#!/usr/bin/env python3
"""Who last wrote each gate-read QA report: the provenance the e2e stop gate checks (CD-6).

hooks/subagentstop-e2e-enforce.py judges the ``e2e_enforcement.status`` of the
``docs/dev/qa-report-*.json`` a QA's dispatch declares. A report the orchestrator (the
main agent) wrote is not the QA's evidence, whatever route wrote it: a heredoc, ``awk``,
``sort -o``, a script, an archive. No reading of a command line can list every route,
so the writer is measured, not parsed:

* ``observe`` runs on every tool call's PreToolUse (hooks/pretool-tool-policy.py, the
  caller known from the payload's ``agent_id``). It stats each
  ``<project>/docs/dev/qa-report-*.json``; a file whose content (sha256) differs from what
  this session's ledger last recorded is recorded with the caller as its writer. The main
  agent cannot act between its own calls, and a synchronous dispatch is one of its calls,
  so a report the main agent changed is first seen at its own next PreToolUse, at the
  latest the dispatch of the QA that will be judged on it: the writer recorded is "main".
  A change a subagent makes is first seen at that subagent's (or a sibling's) next call,
  or at its own stop.
* ``held_by_main`` is the gate's question: is the report's current content exactly what
  an observation of the main agent recorded (and not rewritten since)? Read-only.

The ledger is one JSON file per (session, project) under the harness state dir
(lib/harness_state_dir.py), ``report-provenance/<key>.json``; nothing is written into the
project. Every function fails open (returns, records nothing): the gate then judges the
report as before. Content, not timestamps: a ``touch`` of a main-written report does not
make it a subagent's.
"""
from __future__ import annotations

import fcntl
import glob
import hashlib
import json
import os
import time

REPORT_GLOB = os.path.join("docs", "dev", "qa-report-*.json")
MAIN = "main"
_LIMIT = 4096  # reports per project directory looked at


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
    return os.path.join(harness_state_dir(), "report-provenance", f"{key}.json")


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


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, ValueError):
        return {}
    files = doc.get("files") if isinstance(doc, dict) else None
    return files if isinstance(files, dict) else {}


def _reports(root: str) -> list:
    return sorted(glob.glob(os.path.join(glob.escape(root), REPORT_GLOB)))[:_LIMIT]


def observe(session_id: str, project_dir, actor: str) -> None:
    """Record ``actor`` ("main" or a subagent's agent_id) as the writer of every
    qa-report of ``project_dir`` whose content changed since this session last looked."""
    try:
        root = _root(project_dir)
        ledger = ledger_path(session_id, project_dir)
        if not root or not ledger or not actor:
            return
        reports = _reports(root)
        if not reports and not os.path.exists(ledger):
            return
        os.makedirs(os.path.dirname(ledger), mode=0o700, exist_ok=True)
        with open(ledger + ".lock", "a") as lock:
            deadline = time.monotonic() + 2.0
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        return
                    time.sleep(0.02)
            files = _load(ledger)
            changed = False
            seen = set()
            for path in reports:
                rel = os.path.relpath(path, root)
                seen.add(rel)
                stat = _stat(path)
                entry = files.get(rel) if isinstance(files.get(rel), dict) else None
                if stat is None or (entry and entry.get("stat") == stat):
                    continue
                sha = _sha(path)
                if sha is None:
                    continue
                if entry and entry.get("sha") == sha:
                    entry["stat"] = stat  # same content: the writer stays
                else:
                    files[rel] = {"sha": sha, "stat": stat, "actor": actor, "at": time.time()}
                changed = True
            for rel in [r for r in files if r not in seen]:
                del files[rel]
                changed = True
            if changed:
                tmp = f"{ledger}.{os.getpid()}.tmp"
                with open(tmp, "w", encoding="utf-8") as handle:
                    json.dump({"v": 1, "files": files}, handle)
                os.replace(tmp, ledger)
    except Exception:
        return


def held_by_main(session_id: str, project_dir, rel: str) -> bool:
    """The report ``rel`` (project-relative) holds exactly the content an observation of
    the main agent recorded as its own write in this session."""
    try:
        root = _root(project_dir)
        ledger = ledger_path(session_id, project_dir)
        if not root or not ledger:
            return False
        entry = _load(ledger).get(os.path.normpath(rel))
        if not isinstance(entry, dict) or entry.get("actor") != MAIN:
            return False
        return _sha(os.path.join(root, rel)) == entry.get("sha")
    except Exception:
        return False


def own_write(transcript_path, project_dir, rel: str) -> bool:
    """The agent's own transcript shows a Write, Edit, MultiEdit or NotebookEdit of ``rel``
    with an ok result, or a Bash command whose write targets (lib/bash_write_targets.py)
    name it: that agent wrote the report itself, whoever observed the change first."""
    try:
        from lib import command_span
        from lib import bash_write_targets as bwt

        root = _root(project_dir)
        want = os.path.normpath(os.path.join(root, rel))
        written = command_span.write_set(transcript_path, root, excluded=())
        if written and os.path.normpath(rel) in written.written:
            return True
        for _number, record in command_span._records(transcript_path):
            message = record.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            cwd = record.get("cwd") or root
            for block in content if isinstance(content, list) else ():
                if not (isinstance(block, dict) and block.get("type") == "tool_use"
                        and block.get("name") == "Bash" and isinstance(block.get("input"), dict)):
                    continue
                command = block["input"].get("command")
                if not isinstance(command, str) or os.path.basename(rel) not in command:
                    continue
                for target in bwt.extract_bash_write_paths(command):
                    path = os.path.expanduser(str(target))
                    if os.path.normpath(os.path.join(cwd, path)) == want:
                        return True
    except Exception:
        return False
    return False
