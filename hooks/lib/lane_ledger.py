"""A dev lane's file bookkeeping, kept by code: one record per lane, written at its own tool calls, read at its stop.

``record`` (PreToolUse, hooks/pretool-lane-ledger.py, the record's one writer): before a dev subagent's call that
may change files, each path the call names that the record does not hold yet gets its baseline: the git blob of its
bytes in its own work tree, or ``absent``. The file tools name their path; a Bash command's paths are the ones the
shared parser reads (lib/bash_write_targets). A command that is not proven read-only and runs a program whose writes
no parser sees (an interpreter, a build tool, a computed name) is named under ``unattributed``, never guessed.
Each recorded path also keeps the lane's own edits: a file-tool call's ``{"old", "new"}`` entries (agents/dev.md's
owned_edits form) and the blob they leave are held as pending; the lane's next call naming the path, or its stop,
adds them once the disk shows that blob. A disk that shows anything else (another writer between the lane's edits or
after its last one, a shell command, a call whose result is not computed here) marks the path ``unprovable``.

``at_stop`` (SubagentStop, an observe rule of hooks/subagentstop-producer-gate.py, before G2): each recorded path git
has a change for is, by its baseline and the disk now, created, modified or deleted. Where the lane's report omits
one, it is added to ``dev.files_created`` or ``dev.files_modified`` (a deletion is a change: agents/dev.md), with its
baseline in ``pre_edit_snapshots`` where that lacks it, and its proven edits in ``owned_edits`` where the report
neither claims the path there nor routes it through ``files_landed_whole`` and its snapshot is the record's baseline;
an unprovable path is named, its owned_edits left to the lane. The lane is told in one line. Nothing is removed or
replaced and nothing the record lacks is added: what the report holds beyond the record stays for G2's A3.a check.

The record's first call also keeps its lane's report as the dispatch found it (its blob); ``declared_at_start``
gives G2's A3.a check the paths it declared then, so the lane is judged by what this dispatch declared.

Lifetime (inventory: lib/harness_temp_state "lane-ledger", control state): the dispatch. ``end``, a witness rule of
the same gate, removes the record and its lock on the stop that stands; a refused stop keeps it, so the next stop of
the same dispatch is judged against the same baseline. A lane that never reaches a stop that stands (cut off, never
resumed) leaves its record, one small JSON, and nothing removes it or a session's emptied directory. Record and
report are each replaced whole (lib/allowlist.write_state_entry).
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
from pathlib import Path

from lib.allowlist import write_state_entry
from lib.harness_vocabulary import WRITE_TOOLS

ABSENT = "absent"
# commands whose every write the parser reads (lib/shell_parse write targets); any other non-read-only one is named
PLAIN_WRITERS = frozenset(("rm", "rmdir", "mv", "cp", "mkdir", "touch", "tee", "ln", "echo", "printf", "cat", "cd",
                           "sed", "true", "test", "[", "ls", "head", "tail", "chmod"))


def _path(session_id: str, agent_id: str) -> Path:
    from lib.harness_state_dir import harness_state_dir
    safe = lambda s: "".join(c if c.isalnum() or c in "-_." else "_" for c in str(s))[:120]
    return Path(harness_state_dir(), "lane-ledger", safe(session_id), safe(agent_id) + ".json")


def _tree(path: Path) -> tuple:
    tree = next((p for p in path.parents if (p / ".git").exists()), None)
    return tree, path.relative_to(tree).as_posix() if tree else ""


def _git(tree: Path, *args: str) -> str:
    return subprocess.run(["git", "--no-optional-locks", "--literal-pathspecs", "-C", str(tree), *args],
                          capture_output=True, text=True, timeout=10).stdout


def _blob(path: Path, write: bool = True) -> str | None:
    """The baseline of path: ``absent``, or its git blob in its own tree; None outside every tree or not a file."""
    tree, rel = _tree(path)
    if not tree:
        return None
    if not os.path.lexists(path):
        return ABSENT
    return (_git(tree, "hash-object", *(["-w"] if write else []), "--", rel).strip() or None) if path.is_file() else None


def _predict(tool: str, tool_input: dict, path: Path) -> tuple[list, str] | None:
    """(the owned_edits entries of a file-tool call, the bytes' blob it leaves), or None where the result is not read."""
    try:
        text = path.read_bytes().decode() if os.path.lexists(path) else None
    except (OSError, UnicodeDecodeError):
        return None
    steps = tool_input.get("edits") if tool == "MultiEdit" else [tool_input] if tool == "Edit" else None
    if tool == "Write":
        buf, entries = tool_input.get("content"), [{"old": text or "", "new": tool_input.get("content")}]
    elif not isinstance(steps, list) or not steps:
        return None  # NotebookEdit: its result is not computed here
    else:
        buf, entries = text, []
    for step in steps if tool != "Write" else []:
        step = step if isinstance(step, dict) else {}
        old, new = step.get("old_string"), step.get("new_string")
        if not (isinstance(buf, str) and isinstance(old, str) and old and isinstance(new, str)):
            return None
        count = buf.count(old)
        if count == 0 or (count > 1 and not step.get("replace_all")):
            return None  # the tool refuses it: nothing changes
        after = buf.replace(old, new) if step.get("replace_all") else buf.replace(old, new, 1)
        entries.append({"old": old, "new": new} if count == 1 else {"old": buf, "new": after})  # each old unique
        buf = after
    if not isinstance(buf, str):
        return None
    tree, rel = _tree(path)
    blob = subprocess.run(["git", "-C", str(tree), "hash-object", "--stdin", f"--path={rel}"], input=buf.encode(),
                          capture_output=True, timeout=10).stdout.decode().strip()
    return (entries, blob) if blob else None


def _settle(entry: dict, now: str | None) -> None:
    """Fold the last call's predicted result into entry once the disk shows it; mark it unprovable where it does not."""
    pending = entry.pop("pending", None)
    if "edits" not in entry or "unprovable" in entry:
        return
    if pending and pending.get("post") and pending["post"] == now:
        entry["edits"] += pending["edits"]
        entry["at"] = now
    elif now != entry["at"]:  # equal: the call changed nothing (refused, failed or a no-op)
        entry["unprovable"] = ("it changed after a shell command named it" if pending and pending["by"] == "Bash" else
                               f"it changed after a {pending['by']} call whose result the harness does not compute"
                               if pending and not pending.get("post") else
                               "another writer changed it between the lane's edits or after its last one")


def _targets(tool: str, tool_input: dict, cwd: str) -> tuple[list, str | None]:
    """(paths the call names, the command when some of its writes cannot be attributed)."""
    if tool in WRITE_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("notebook_path")
        return ([raw] if isinstance(raw, str) and raw else []), None
    command = tool_input.get("command")
    if tool != "Bash" or not isinstance(command, str):
        return [], None
    from lib import bash_read_only, bash_write_targets, shell_parse
    if bash_read_only.is_read_only(command):
        return [], None
    paths = [p for p, _ in bash_write_targets.extract_bash_touched_paths(command)]
    try:
        names = {shell_parse.resolve(site.cmd).name for site in shell_parse.walk(shell_parse.parse(command))}
    except Exception:
        names = {None}
    opaque = bool(names - PLAIN_WRITERS - {"git"}) or ("git" in names and not paths)
    return paths, (command[:300] if opaque or not paths else None)


def record(payload: dict) -> None:
    agent_id, tool = payload.get("agent_id"), payload.get("tool_name")
    if not agent_id or tool not in WRITE_TOOLS | {"Bash"}:
        return
    from lib.agent_resolver import resolve_agent_type
    if resolve_agent_type(payload) != "dev":
        return
    cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    paths, opaque = _targets(tool, payload.get("tool_input") or {}, cwd)
    if not paths and not opaque:
        return
    target = _path(payload.get("session_id") or "", agent_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            rec = json.loads(target.read_text())
        except (OSError, ValueError):
            rec = {}
        if not rec:  # the dispatch's first recorded call: its report as the dispatch found it (declared_at_start)
            rec["report"] = _report_baseline(payload, os.environ.get("CLAUDE_PROJECT_DIR") or cwd)
        files = rec.setdefault("files", {})
        for raw in paths:
            p = str(Path(cwd, os.path.expanduser(raw)).resolve())
            if p in files:
                _settle(files[p], _blob(Path(p), write=False))
            elif (base := _blob(Path(p))) is not None:
                files[p] = {"pre": base, "via": tool, "at": base, "edits": []}
            if p in files and "edits" in files[p] and "unprovable" not in files[p]:
                pred = None if tool == "Bash" else _predict(tool, payload.get("tool_input") or {}, Path(p))
                files[p]["pending"] = {"by": tool, "post": pred[1], "edits": pred[0]} if pred else {"by": tool}
        if opaque:
            rec.setdefault("unattributed", []).append({"tool_use_id": payload.get("tool_use_id"), "command": opaque})
        write_state_entry(target, json.dumps(rec, indent=1, sort_keys=True), 0o600)


def _report_path(payload: dict, project_dir: str) -> Path | None:
    from lib import obligation
    resolved = obligation.resolve_own_obligation(
        session_id=payload.get("session_id") or payload.get("sessionId"), agent_id=payload.get("agent_id"),
        project_dir=project_dir, payload_agent_transcript_path=payload.get("agent_transcript_path"),
        expected_role="dev")
    ob = getattr(resolved, "obligation", None)
    arts = [a for a in (ob or {}).get("artifacts") or [] if isinstance(a, dict) and a.get("kind") == "json"
            and str(a.get("schema", "")).startswith("dev-report.v2") and isinstance(a.get("path"), str)]
    return (Path(project_dir) / arts[0]["path"]) if arts else None


def _report_baseline(payload: dict, project_dir: str) -> dict | None:
    try:
        path = _report_path(payload, project_dir)
        pre = _blob(path.resolve()) if path else None
    except Exception:  # no obligation to resolve: no baseline, A3.a judges every entry
        return None
    return {"path": str(path.resolve()), "pre": pre} if pre else None


def declared_at_start(session_id: str, agent_id: str, report: Path, project_dir: str) -> set | None:
    """The paths (resolved) report's dev.files_modified + dev.files_created held at the lane's first recorded call,
    before any call of its could change it; None where the record holds no baseline of that report."""
    try:
        base = json.loads(_path(session_id or "", agent_id).read_text()).get("report") or {}
    except (OSError, ValueError, AttributeError):
        return None
    if not base.get("pre") or base.get("path") != str(report.resolve()):
        return None
    try:
        dev = {} if base["pre"] == ABSENT else json.loads(
            _git(_tree(report.resolve())[0], "cat-file", "blob", base["pre"])).get("dev")
    except (ValueError, AttributeError, subprocess.SubprocessError):
        dev = {}  # unreadable: it declared nothing, so every entry is judged
    lists = [dev.get(k) for k in ("files_modified", "files_created")] if isinstance(dev, dict) else []
    return {(Path(project_dir).resolve() / os.path.expanduser(str(p))).resolve()
            for v in lists if isinstance(v, list) for p in v}


def _owned(entry: dict, p: Path, snapshot) -> tuple[list | None, str | None]:
    """(the lane's own edits of p where its record proves them, else why not); (None, None): nothing of the lane's."""
    entry = json.loads(json.dumps(entry))
    _settle(entry, _blob(p, write=False))
    if "edits" not in entry or (not entry["edits"] and "unprovable" not in entry):
        return None, None  # a record of the earlier form, or the lane's calls changed nothing in it
    if entry.get("unprovable"):
        return None, entry["unprovable"]
    if snapshot is not None and snapshot != entry["pre"] and not (entry["pre"] != ABSENT and _git(
            _tree(p)[0], "cat-file", "blob", entry["pre"]) == snapshot):
        return None, "its pre_edit_snapshots entry is not the content before the lane's first change"
    return entry["edits"], None


def complete(report: dict, rec: dict, project_dir: str, notes: list | None = None) -> list[str]:
    """Add to report what rec shows changed and report omits; return what was added, one item per path.

    ``owned_edits`` of a changed path the report does not claim (nor route through ``files_landed_whole``) is set
    from the record where it proves the lane's edits; where it cannot, ``<path>: <why>`` goes to ``notes``."""
    from lib.command_span import EXCLUDED_TREES  # the pipeline's own bookkeeping trees: never a product file
    dev, root = report.get("dev"), Path(project_dir).resolve()
    if not isinstance(dev, dict):
        return []
    show = lambda p: p.relative_to(root).as_posix() if p.is_relative_to(root) else str(p)
    lists = {k: dev[k] if isinstance(dev.get(k), list) else [] for k in ("files_modified", "files_created")}
    declared = {(root / os.path.expanduser(str(p))).resolve() for v in lists.values() for p in v}
    snaps = report.get("pre_edit_snapshots") if isinstance(report.get("pre_edit_snapshots"), dict) else {}
    owned = report.get("owned_edits", {})  # another type: the report's to fix, never overwritten here
    whole = [w.get("path") for w in report.get("files_landed_whole") or [] if isinstance(w, dict)]
    claimed = {(root / os.path.expanduser(str(k))).resolve() for k in [*(owned or ()), *whole] if k}
    added = []
    for raw, entry in sorted((rec.get("files") or {}).items()):
        p, pre = Path(raw), (entry or {}).get("pre")
        tree, rel = _tree(p)
        if not tree or rel.startswith(EXCLUDED_TREES) or not _git(tree, "status", "--porcelain", "-uall", "--", rel):
            continue  # unchanged, ignored or outside a tree: nothing lands, nothing to declare
        now = os.path.lexists(p)
        if pre == ABSENT and not now:
            continue
        key = "files_created" if pre == ABSENT else "files_modified"
        if p not in declared:
            lists[key].append(show(p))
            added.append(f"dev.{key} +{show(p)}" + ("" if now else " (deleted)"))
        if pre != ABSENT and show(p) not in snaps:
            snaps[show(p)] = pre
            added.append(f"pre_edit_snapshots +{show(p)}")
        if isinstance(owned, dict) and p not in claimed:
            edits, why = _owned(entry or {}, p, snaps.get(show(p)))
            if edits:
                owned[show(p)] = edits
                added.append(f"owned_edits +{show(p)}")
            elif why and notes is not None:
                notes.append(f"{show(p)}: {why}")
    if added:
        dev.update(lists)
        report["pre_edit_snapshots"] = snaps
        if isinstance(owned, dict):
            report["owned_edits"] = owned
    return added


def at_stop(payload: dict) -> list[str]:
    """Observe rule: complete the stopping dev lane's report from its record; never refuses."""
    if not payload.get("agent_id"):
        return []
    target = _path(payload.get("session_id") or payload.get("sessionId") or "", payload["agent_id"])
    try:
        rec = json.loads(target.read_text())
    except (OSError, ValueError):
        return []
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    path = _report_path(payload, project_dir)
    try:
        report = json.loads(path.read_text()) if path else None
    except (OSError, ValueError):
        return []
    if not isinstance(report, dict):
        return []  # no report to complete yet: the record waits for the stop that has one
    notes: list = []
    if added := complete(report, rec, project_dir, notes):
        write_state_entry(path, json.dumps(report, indent=2) + "\n")
    said = ([f"your report was completed from the harness's record of your writes: {'; '.join(added)}"] if added
            else []) + ([f"owned_edits of these files is not provable from that record, so it is yours to write as "
                         f"before: {'; '.join(notes)}"] if notes else [])
    lines = [f"lane-ledger: {'. '.join(said)}"] if said else []
    if not added:
        return lines
    if rec.get("unattributed"):
        lines.append(f"lane-ledger: {len(rec['unattributed'])} command(s) ran programs whose writes the harness "
                     f"cannot read; their files are yours to list: {target}")
    return lines


def end(payload: dict) -> list[str]:
    """Witness rule: the stop stands, the dispatch is over; its record and lock are removed."""
    if payload.get("agent_id"):
        target = _path(payload.get("session_id") or payload.get("sessionId") or "", payload["agent_id"])
        for done in (target, target.with_suffix(".lock")):
            done.unlink(missing_ok=True)
    return []
