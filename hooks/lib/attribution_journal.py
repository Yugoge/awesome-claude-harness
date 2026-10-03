#!/usr/bin/env python3
"""Write-time attribution journal: shared capture + fold primitives (Phase 0).

Capture side (used by pretool-attribution-pre.py / posttool-attribution-post.py):
  PreToolUse records each target's content hash keyed to the tool invocation;
  PostToolUse records the resulting hash and appends ONE event per target to a
  per-session append-only journal.

Concurrency design (deliberately lock-free):
  * one journal file per session -> no cross-session writers;
  * a single O_APPEND write() per event (atomic for one short line);
  * per-file total order comes from hash-chain linkage (event.pre_sha must equal
    the file's prior event.post_sha), NEVER from timestamps (diagnostic only).
Writes that bypass the hooks surface later as chain breaks -- by design.

Blob store: file contents live in the harness repository's git object database
(`git hash-object -w`); the hash used in events IS the git blob id, so every
byte-state is recoverable with `git cat-file blob <sha>` and deduplicated.

Shell commands are MEASURED, never parsed (see record_pre / record_post):
  parsing a command line cannot see writes performed inside interpreter code
  (python heredocs, node -e, scripts that open() files...). So for Bash the
  pre hook snapshots the repository worktree's change-state -- the content
  blob id of every currently modified/untracked/deleted file (one batched
  `git hash-object -w`) plus the index blob map (`git ls-files -s`, the "cheap
  index of the rest": a clean file's bytes ARE its index blob) -- and the post
  hook re-measures and emits one event per file whose bytes actually changed
  (creations: pre=absent; deletions: post=absent; truncations: post=empty blob).
  Such events carry `"measured": true`. The command-line parser is demoted to a
  hint: paths it names OUTSIDE the repository (invisible to the worktree
  measurement) are hashed pre/post as before (no `measured` flag), and in-repo
  hints are added to the measured candidate set so gitignored in-repo files the
  command names are still covered.
  Concurrency: parallel shell calls may interleave measurements, so a file
  changed by call A can also be observed as changed by overlapping call B. The
  per-file hash chain (pre_sha == prior post_sha) still orders each file's
  history; this is documented, not locked around. The fold collapses such
  IDENTICAL duplicate transitions (same path/pre/post) into one edge, keeps all
  recording events as witnesses, and flags the edge ambiguous_writer when the
  witnesses span more than one session/agent. Same-pre/different-post stays a
  real fork (break).
  Coverage limit: gitignored in-repo files are only seen when the command text
  names them; a file's coverage window starts at its first event.

Known Phase-0 limits: seq is best-effort monotone per session (parallel tool
calls may tie; invocation_id disambiguates); a cp/mv whose destination is a
directory is skipped (the written basename is not resolved). A file written by
a DIFFERENT PostToolUse hook as a side effect of this call (e.g. doc-sync
regenerating INDEX.md for a sibling edit) is outside this capture window and
is a known, documented boundary -- see
docs/reference/attribution-journal-phase0-facility.md #3 for the ruling and
its detection signature (ordinary chain BREAK on the hook-managed path).

Never raises into the tool pipeline: callers wrap in try/except and exit 0.
`autoseal_hook_trigger()` (below) follows the same contract for the periodic
seal-to-persistent-storage step; see scripts/seal-attribution-journal.py and
docs/reference/attribution-journal-phase0-facility.md #1.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ABSENT = "absent"            # file does not exist (pre of a create / post of a delete)
OVERSIZE = "oversize"        # too large to blob; hash not recorded
NOTFILE = "notfile"          # directory / special file
MAX_BLOB_BYTES = 64 * 1024 * 1024
REQUIRED_KEYS = ("seq", "session_id", "path", "pre_sha", "post_sha", "ts", "tool", "invocation_id")
EDIT_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path",
              "NotebookEdit": "notebook_path"}


def harness_root() -> Path:
    """Repo root = parent of hooks/ (override: ATTRIBUTION_HARNESS_ROOT, for tests)."""
    env = os.environ.get("ATTRIBUTION_HARNESS_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent


def state_dir() -> Path:
    env = os.environ.get("ATTRIBUTION_STATE_DIR")
    return Path(env) if env else harness_root() / "state" / "attribution-journal"


def journal_dir() -> Path:
    return state_dir() / "journals"


def pending_dir() -> Path:
    return state_dir() / "pending"


def _safe(name: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(name))[:200] or "unknown"


def git_dir() -> str:
    env = os.environ.get("ATTRIBUTION_GIT_DIR")
    return env if env else str(harness_root() / ".git")


def hash_file(path: str) -> str:
    """Store the file's bytes as a git blob (idempotent) and return its blob id."""
    try:
        if not os.path.lexists(path):
            return ABSENT
        if not os.path.isfile(path):
            return NOTFILE
        if os.path.getsize(path) > MAX_BLOB_BYTES:
            return OVERSIZE
        out = subprocess.run(
            ["git", "--git-dir", git_dir(), "hash-object", "-w", "--no-filters", "--", path],
            capture_output=True, text=True, timeout=20, check=True,
            env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        )
        return out.stdout.strip()
    except Exception:
        return "unreadable"


def resolve_target(raw: str, cwd: str) -> str:
    p = os.path.expanduser(os.path.expandvars(raw))
    if not os.path.isabs(p):
        p = os.path.join(cwd or os.getcwd(), p)
    return os.path.normpath(p)


def extract_targets(tool_name: str, tool_input: dict, cwd: str) -> List[str]:
    """Mutation targets for the tool call, absolute and de-duplicated, in order."""
    raw: List[str] = []
    if tool_name in EDIT_TOOLS:
        v = (tool_input or {}).get(EDIT_TOOLS[tool_name])
        if isinstance(v, str) and v:
            raw.append(v)
    elif tool_name == "Bash":
        from lib.bash_write_targets import extract_bash_write_paths
        cmd = (tool_input or {}).get("command")
        if isinstance(cmd, str) and cmd:
            raw.extend(extract_bash_write_paths(cmd))
    seen, out = set(), []
    for r in raw:
        if not r or "$" in r:                            # unresolved vars
            continue
        p = resolve_target(r, cwd)
        # device sinks (/dev/null, /dev/stderr, ...) -- but /dev/shm is a real tmpfs tree
        if p.startswith("/dev/") and not p.startswith("/dev/shm/"):
            continue
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def invocation_id(payload: dict) -> str:
    tid = payload.get("tool_use_id")
    if isinstance(tid, str) and tid:
        return tid
    import hashlib
    blob = json.dumps([payload.get("tool_name"), payload.get("tool_input")], sort_keys=True, default=str)
    return "derived-" + hashlib.sha1(blob.encode()).hexdigest()[:20]


def pending_path(session_id: str, inv: str) -> Path:
    return pending_dir() / _safe(session_id) / (_safe(inv) + ".json")


def _clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _in_repo(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def hash_files(paths: List[str]) -> Dict[str, str]:
    """Batch variant of hash_file: ONE `git hash-object -w --stdin-paths` for all
    regular files (the per-file subprocess dominated the naive cost)."""
    res: Dict[str, str] = {}
    todo: List[str] = []
    for p in paths:
        try:
            if not os.path.lexists(p):
                res[p] = ABSENT
            elif not os.path.isfile(p):
                res[p] = NOTFILE
            elif os.path.getsize(p) > MAX_BLOB_BYTES:
                res[p] = OVERSIZE
            elif "\n" in p:
                res[p] = hash_file(p)
            else:
                todo.append(p)
        except Exception:
            res[p] = "unreadable"
    if todo:
        try:
            out = subprocess.run(
                ["git", "--git-dir", git_dir(), "hash-object", "-w", "--no-filters", "--stdin-paths"],
                input="\n".join(todo) + "\n", capture_output=True, text=True, timeout=60,
                check=True, env=_clean_env())
            shas = out.stdout.split()
            if len(shas) != len(todo):
                raise ValueError("hash-object count mismatch")
            res.update(zip(todo, shas))
        except Exception:
            for p in todo:                       # fall back per file; never lose a target
                res[p] = hash_file(p)
    return res


def _git_tree(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "--no-optional-locks", "-C", str(root), *args],
        capture_output=True, timeout=60, check=True, env=_clean_env()).stdout


def dirty_paths(root: Path) -> Optional[List[str]]:
    """Absolute paths of every modified / deleted / untracked file in the worktree
    (None when root is not a usable git worktree)."""
    try:
        raw = _git_tree(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames")
    except Exception:
        return None
    out = []
    for ent in raw.split(b"\0"):
        if len(ent) > 3:
            out.append(os.path.join(str(root), os.fsdecode(ent[3:])))
    return out


def index_blobs(root: Path) -> Dict[str, str]:
    try:
        raw = _git_tree(root, "ls-files", "-s", "-z")
    except Exception:
        return {}
    m: Dict[str, str] = {}
    for ent in raw.split(b"\0"):
        meta, _, name = ent.partition(b"\t")
        parts = meta.split()
        if len(parts) == 3 and name:
            m[os.path.join(str(root), os.fsdecode(name))] = parts[1].decode()
    return m


def record_pre(payload: dict) -> int:
    tool = payload.get("tool_name", "")
    targets = extract_targets(tool, payload.get("tool_input") or {}, payload.get("cwd", ""))
    sid = str(payload.get("session_id") or "unknown")
    inv = invocation_id(payload)
    rec: dict = {"tool": tool}
    if tool == "Bash":
        root = harness_root()
        rs = str(root)
        dirty = dirty_paths(root)
        if dirty is not None:
            hints_in = [t for t in targets if _in_repo(t, rs)]
            targets = [t for t in targets if not _in_repo(t, rs)]   # parser demoted to out-of-repo hint
            snap = hash_files(list(dict.fromkeys(dirty + hints_in)))
            rec["measured"] = {"root": rs, "snapshot": snap, "index": index_blobs(root)}
    if not targets and "measured" not in rec:
        return 0
    rec["targets"] = [{"path": t, "pre_sha": hash_file(t)} for t in targets]
    p = pending_path(sid, inv)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp%d" % os.getpid())
    tmp.write_text(json.dumps(rec))
    os.replace(tmp, p)
    return len(targets)


def _last_seq_and_tail_ok(path: Path) -> Tuple[int, bool]:
    """(last seq, file ends with newline) reading only the tail of the journal."""
    try:
        size = path.stat().st_size
    except OSError:
        return 0, True
    if size == 0:
        return 0, True
    with open(path, "rb") as fh:
        fh.seek(max(0, size - 8192))
        tail = fh.read()
    ends_nl = tail.endswith(b"\n")
    for line in reversed(tail.split(b"\n")):
        try:
            return int(json.loads(line)["seq"]), ends_nl
        except Exception:
            continue
    return 0, ends_nl


def append_events(session_id: str, events: List[dict]) -> None:
    jp = journal_dir() / (_safe(session_id) + ".jsonl")
    jp.parent.mkdir(parents=True, exist_ok=True)
    last, ends_nl = _last_seq_and_tail_ok(jp)
    chunks = []
    for i, ev in enumerate(events, 1):
        ev["seq"] = last + i
        chunks.append(json.dumps(ev, sort_keys=True, separators=(",", ":")))
    data = ("\n".join(chunks) + "\n").encode()
    if not ends_nl:          # torn tail from a crashed writer: fence it off
        data = b"\n" + data
    fd = os.open(jp, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)   # one write() => O_APPEND-atomic, no lock
    finally:
        os.close(fd)


def record_post(payload: dict) -> int:
    sid = str(payload.get("session_id") or "unknown")
    inv = invocation_id(payload)
    p = pending_path(sid, inv)
    try:
        rec = json.loads(p.read_text())
    except (OSError, ValueError):
        return 0
    events = []
    now = time.time()
    tool_name = rec.get("tool") or payload.get("tool_name", "")

    def mk(path: str, pre: str, post: str, measured: bool) -> dict:
        ev = {"session_id": sid, "path": path, "pre_sha": pre, "post_sha": post,
              "ts": round(now, 6), "tool": tool_name, "invocation_id": inv}
        if measured:
            ev["measured"] = True
        if payload.get("agent_id"):
            ev["agent_id"] = str(payload["agent_id"])
        tid = os.environ.get("CLAUDE_TASK_ID")
        if tid:
            ev["task_id"] = tid
        return ev

    for t in rec.get("targets", []):
        events.append(mk(t["path"], t["pre_sha"], hash_file(t["path"]), False))
    m = rec.get("measured")
    if m:
        snap, idx = m["snapshot"], m["index"]
        post_dirty = dirty_paths(Path(m["root"])) or []
        cands = list(dict.fromkeys(list(snap) + post_dirty))
        post = hash_files(cands)
        for path in cands:
            pre = snap.get(path) or idx.get(path) or ABSENT
            if post[path] != pre:
                events.append(mk(path, pre, post[path], True))
    if events:
        append_events(sid, events)
    try:
        p.unlink()
    except OSError:
        pass
    return len(events)


# ----------------------------------------------------------------- reading

def read_journal(path: Path) -> Tuple[List[dict], List[dict]]:
    """Parse one journal. Returns (events, discarded) -- torn/malformed lines are
    discarded (never fatal) and described in `discarded`."""
    events, bad = [], []
    try:
        raw = path.read_bytes()
    except OSError:
        return events, bad
    lines = raw.split(b"\n")
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        torn_tail = (i == len(lines) - 1)   # last segment had no terminating newline
        try:
            ev = json.loads(line)
            if not isinstance(ev, dict) or any(k not in ev for k in REQUIRED_KEYS):
                raise ValueError("missing keys")
            if torn_tail:
                # complete JSON but unterminated: still a full event, keep it.
                pass
            events.append(ev)
        except Exception as exc:
            bad.append({"journal": str(path), "line": i + 1, "torn_tail": torn_tail,
                        "reason": str(exc)[:80]})
    return events, bad


def read_all_journals(jdir: Optional[Path] = None) -> Tuple[List[dict], List[dict]]:
    jdir = jdir or journal_dir()
    events, bad = [], []
    if jdir.is_dir():
        for jp in sorted(jdir.glob("*.jsonl")):
            e, b = read_journal(jp)
            events.extend(e)
            bad.extend(b)
    return events, bad


# ------------------------------------------------------------- auto-seal hook

def autoseal_hook_trigger() -> None:
    """Best-effort periodic seal-to-persistent-storage, called from
    posttool-attribution-post.py after every capture. This is the ONLY
    production trigger for scripts/seal-attribution-journal.py's
    autoseal_if_due(): no cron/heartbeat is used, so the seal cadence survives
    exactly as long as tool calls keep happening -- which is also exactly when
    there is new evidence worth sealing.

    Disable with ATTRIBUTION_AUTOSEAL_DISABLE=1 (tests set this by default to
    stay hermetic). Interval is $ATTRIBUTION_SEAL_INTERVAL_SECONDS, default
    scripts/seal-attribution-journal.py:DEFAULT_AUTOSEAL_INTERVAL_SECONDS.
    Never raises -- sealing is persistence hygiene, not part of the capture
    contract; a disabled/missing/broken seal script must never break capture.
    """
    if os.environ.get("ATTRIBUTION_AUTOSEAL_DISABLE", "").strip().lower() in ("1", "true", "yes"):
        return
    try:
        import importlib.util
        # NOT harness_root(): that is overridden by ATTRIBUTION_HARNESS_ROOT in
        # tests to point at a throwaway worktree for the Bash dirty-scan target
        # (see record_pre). The seal script's own location never moves with it --
        # it sits next to this file regardless of which repo is being measured.
        facility_root = Path(__file__).resolve().parent.parent.parent
        path = facility_root / "scripts" / "seal-attribution-journal.py"
        spec = importlib.util.spec_from_file_location("attribution_journal_autoseal", path)
        if spec is None or spec.loader is None:
            return
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        interval_env = os.environ.get("ATTRIBUTION_SEAL_INTERVAL_SECONDS")
        interval = float(interval_env) if interval_env else mod.DEFAULT_AUTOSEAL_INTERVAL_SECONDS
        mod.autoseal_if_due(interval=interval, trigger="auto")
    except Exception:
        return
