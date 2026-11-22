"""A dev lane's file bookkeeping, kept by code: one record per lane, written at its own tool calls, read at its stop.

``record`` (PreToolUse, hooks/pretool-lane-ledger.py, the record's one writer): before a dev subagent's call that
may change files, each path the call names that the record does not hold yet gets its baseline: the git blob of its
bytes in its own work tree, or ``absent``. The file tools name their path; a Bash command's paths are the ones the
shared parser reads (lib/bash_write_targets). A command that is not proven read-only and runs a program whose writes
no parser sees (an interpreter, a build tool, a computed name) is named under ``unattributed``, never guessed.

``at_stop`` (SubagentStop, an observe rule of hooks/subagentstop-producer-gate.py, before G2): each recorded path git
has a change for is, by its baseline and the disk now, created, modified or deleted. Where the lane's report omits
one, it is added to ``dev.files_created`` or ``dev.files_modified`` (a deletion is a change: agents/dev.md), with its
baseline in ``pre_edit_snapshots`` where that lacks it, and the lane is told in one line. Nothing is removed and
nothing the record lacks is added: what the report holds beyond the record stays for G2's A3.a check to judge.

Lifetime (inventory: lib/harness_temp_state "lane-ledger", control state): ``at_stop`` removes the record and its
lock once it has read the lane's report, so a stop the lane passes again after a refused one starts a fresh record
of the calls in between; a lane that never reaches a stop with a readable report (cut off, never resumed) leaves
its record, one small JSON, and nothing removes it or a session's emptied directory. Record and report are each
replaced whole (lib/allowlist.write_state_entry).
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


def _blob(path: Path) -> str | None:
    """The baseline of path: ``absent``, or its git blob in its own tree; None outside every tree or not a file."""
    tree, rel = _tree(path)
    if not tree:
        return None
    if not os.path.lexists(path):
        return ABSENT
    return (_git(tree, "hash-object", "-w", "--", rel).strip() or None) if path.is_file() else None


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
        files = rec.setdefault("files", {})
        for raw in paths:
            p = str(Path(cwd, os.path.expanduser(raw)).resolve())
            if p not in files and (base := _blob(Path(p))) is not None:
                files[p] = {"pre": base, "via": tool}
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


def complete(report: dict, rec: dict, project_dir: str) -> list[str]:
    """Add to report what rec shows changed and report omits; return what was added, one item per path."""
    from lib.command_span import EXCLUDED_TREES  # the pipeline's own bookkeeping trees: never a product file
    dev, root = report.get("dev"), Path(project_dir).resolve()
    if not isinstance(dev, dict):
        return []
    show = lambda p: p.relative_to(root).as_posix() if p.is_relative_to(root) else str(p)
    lists = {k: dev[k] if isinstance(dev.get(k), list) else [] for k in ("files_modified", "files_created")}
    declared = {(root / os.path.expanduser(str(p))).resolve() for v in lists.values() for p in v}
    snaps = report.get("pre_edit_snapshots") if isinstance(report.get("pre_edit_snapshots"), dict) else {}
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
    if added:
        dev.update(lists)
        report["pre_edit_snapshots"] = snaps
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
    if added := complete(report, rec, project_dir):
        write_state_entry(path, json.dumps(report, indent=2) + "\n")  # raises: the record stays for the next stop
    for done in (target, target.with_suffix(".lock")):
        done.unlink(missing_ok=True)
    if not added:
        return []
    lines = [f"lane-ledger: your report was completed from the harness's record of your writes: {'; '.join(added)}"]
    if rec.get("unattributed"):
        lines.append(f"lane-ledger: {len(rec['unattributed'])} command(s) ran programs whose writes the harness "
                     f"cannot read; their files are yours to list: {target}")
    return lines
