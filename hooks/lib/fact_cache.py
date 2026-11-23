"""A computation's result kept while every fact it read is unchanged (the Stop gate's per-task disposition).

watch() records, while a computation runs in this process, every file it opens, stats or lists and every
git repository it runs git in; facts() turns that record into its key: each path's (inode, size, mtime) or
its absence, each repository's HEAD, refs, staged entries and working-tree status (with each listed path's stat),
the harness modules loaded, and the GIT_* environment. A result is reused only while recheck() finds every
one of those facts as it was, so a changed input (a commit, an edited or new report, a new record of
another producer) computes it again. The saved conversations a computation read through the dispatch records of a
task (obligation._task_records) are no path facts: a conversation that grew is not a changed input unless the
answer changed, so the key holds each answer's digest beside the stat of the conversations behind it; while
those stats hold nothing is asked, and when one differs the answers are asked again and the record is kept
(its stats renewed) if they are the same. The refusal record, which every block appends to, is no path fact: what a
computation asked of it is, per session, a digest of the refused ids. A computation that runs any program but git is never kept: what that
program reads is not seen. A record lives in `stop-disposition/<digest>.json` under the state root (lib/
harness_temp_state LOCATIONS), replaced by its next computation; one older than KEEP goes at the next write.
"""
from __future__ import annotations

import builtins
import hashlib
import importlib
import io
import json
import os
import re
import stat as stat_mod
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import locations  # noqa: E402  (the filesystem root is no repository top)

DIR = "stop-disposition"
KEEP = 7 * 86400
VERSION = 1
_GIT_ENV = {"GIT_NO_REPLACE_OBJECTS": "1", "GIT_GRAFT_FILE": os.devnull}


class Reads:
    def __init__(self) -> None:
        self.paths: set[str] = set()
        self.slugs: set[str] = set()  # the project folders of the conversation stores
        self.quiet = 0  # inside a call whose answer is kept by digest (tasks)
        self.covered: dict[str, list | None] = {}  # conversation paths that call read: stat before first use
        self.tasks: dict[str, list] = {}  # json of (task id, project dir, roots) -> [..., digest of the answer]
        self.refusals: set[str] = set()  # sessions whose refusals (command_span.recorded_refusals) it asked
        self.repos: set[str] = set()
        self.foreign: list[str] = []


def _name(path) -> str | None:
    if isinstance(path, int):
        return None
    try:
        return os.path.abspath(os.fsdecode(os.fspath(path)))
    except TypeError:
        return None


def _command_spans() -> list:
    """Every copy of the transcript reader that this process holds or can load: the harness imports it as
    lib.command_span (the hooks), hooks.lib.command_span (the chain script) and, in tests, command_span."""
    root = str(Path(__file__).resolve().parent.parent.parent)
    found = []
    for name in ("lib.command_span", "hooks.lib.command_span", "command_span"):
        module = sys.modules.get(name)
        if module is None and name != "command_span":
            if name.startswith("hooks.") and root not in sys.path:
                sys.path.insert(0, root)
            try:
                module = importlib.import_module(name)
            except ImportError:
                continue
        if module is not None:
            found.append(module)
    return found


def _obligations() -> list:
    """Every copy of the module that holds the dispatch records this process holds or can load (as _command_spans)."""
    root = str(Path(__file__).resolve().parent.parent.parent)
    found = []
    for name in ("lib.obligation", "hooks.lib.obligation", "obligation"):
        module = sys.modules.get(name)
        if module is None and name == "hooks.lib.obligation":
            if root not in sys.path:
                sys.path.insert(0, root)
            try:
                module = importlib.import_module(name)
            except ImportError:
                continue
        if module is not None and hasattr(module, "_task_records"):
            found.append(module)
    return found


def _answer(task_id, project_dir, roots) -> str | None:
    """The digest of the dispatch records of a task's family (obligation._task_records), asked on the copy whose
    scan is open (it keeps what it read), else on the first copy; None with no copy to ask."""
    found = _obligations()
    found.sort(key=lambda m: getattr(m, "_SCAN", None) is None)
    if not found:
        return None
    try:
        records = found[0]._task_records(task_id, project_dir, None if roots is None else tuple(roots))
    except Exception:
        return None
    return hashlib.sha256(json.dumps(records, default=str, sort_keys=True).encode()).hexdigest()


def _refusal_digest(session: str) -> str | None:
    """A digest of the tool_use ids the refusal record holds for ``session``; None with no reader to ask."""
    found = _command_spans()
    return hashlib.sha256("\0".join(sorted(found[0].recorded_refusals(session))).encode()).hexdigest() if found else None


@contextmanager
def watch():
    """Record what the code run inside reads (Reads); every patch is undone on leaving."""
    reads = Reads()
    real = {"open": builtins.open, "io_open": io.open, "stat": os.stat, "lstat": os.lstat,
            "scandir": os.scandir, "listdir": os.listdir, "popen": subprocess.Popen}

    refused = _command_spans()
    answers = _obligations()
    folder = refused[0].refusal_folder() if refused else None

    def note(path):
        name = _name(path)
        # The refusal record is appended by every refusal and every block, this very gate's own included: its
        # bytes are no fact (the key holds what was asked of it instead, recorded_refusals below).
        if not name or (folder and (name == folder or name.startswith(folder + os.sep))):
            return
        if os.path.basename(name) == "transcript-index" or os.path.basename(os.path.dirname(name)) == "transcript-index":
            return  # what the reader keeps of a conversation: derived from the conversation, no input of its own
        if reads.quiet and (name.endswith(".jsonl") or os.path.basename(name) in reads.slugs):
            reads.covered.setdefault(name, _stat(name))
        else:
            reads.paths.add(name)

    def counting(original):
        def recorded_refusals(session):
            reads.refusals.add(session)
            return original(session)
        return recorded_refusals

    def answering(original):
        def _task_records(task_id, project_dir, roots):
            slug = _slug(project_dir)
            reads.quiet += 1
            reads.slugs.add(slug)
            try:
                records = original(task_id, project_dir, roots)
            finally:
                reads.quiet -= 1
            digest = hashlib.sha256(json.dumps(records, default=str, sort_keys=True).encode()).hexdigest()
            asked = [task_id, str(project_dir), None if roots is None else [str(r) for r in roots]]
            reads.tasks[json.dumps(asked)] = asked + [digest]
            return records
        return _task_records

    def opener(file, *args, **kwargs):
        note(file)
        return real["open"](file, *args, **kwargs)

    def stat(path, *args, **kwargs):
        note(path)
        return real["stat"](path, *args, **kwargs)

    def lstat(path, *args, **kwargs):
        note(path)
        return real["lstat"](path, *args, **kwargs)

    def scandir(path="."):
        note(path)
        return real["scandir"](path)

    def listdir(path="."):
        note(path)
        return real["listdir"](path)

    class Watched(real["popen"]):
        def __init__(self, args, *rest, **kwargs):
            argv = [args] if isinstance(args, (str, bytes)) else list(args)
            program = os.path.basename(os.fsdecode(argv[0])) if argv else ""
            if program == "git":
                where = kwargs.get("cwd") or os.getcwd()
                for k, arg in enumerate(argv[:-1]):
                    if arg == "-C":
                        where = os.path.join(where, os.fsdecode(argv[k + 1]))
                reads.repos.add(os.path.abspath(where))
            else:
                reads.foreign.append(program or "?")
            super().__init__(args, *rest, **kwargs)

    real_refusals = [module.recorded_refusals for module in refused]
    real_tasks = [module._task_records for module in answers]
    builtins.open, io.open = opener, opener
    os.stat, os.lstat, os.scandir, os.listdir = stat, lstat, scandir, listdir
    subprocess.Popen = Watched
    for module, original in zip(refused, real_refusals):
        module.recorded_refusals = counting(original)
    for module, original in zip(answers, real_tasks):
        module._task_records = answering(original)
    try:
        yield reads
    finally:
        for module, original in zip(refused, real_refusals):
            module.recorded_refusals = original
        for module, original in zip(answers, real_tasks):
            module._task_records = original
        builtins.open, io.open = real["open"], real["io_open"]
        os.stat, os.lstat, os.scandir, os.listdir = real["stat"], real["lstat"], real["scandir"], real["listdir"]
        subprocess.Popen = real["popen"]


def _slug(project_dir) -> str:
    """The store folder's name for a project (subagent_restart.project_slug: every character but a letter or digit is -)."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(str(project_dir)))


def _stat(path: str, stat=os.stat):  # the stat of the module's import: a watch patches os.stat
    try:
        st = stat(path)
    except OSError:
        return None
    # a directory's entries change its mtime; its size is the file system's own (an overlay's copy-up changes it)
    return [st.st_ino, None if stat_mod.S_ISDIR(st.st_mode) else st.st_size, st.st_mtime_ns]


def _git(top: str, *args: str) -> bytes | None:
    try:
        done = subprocess.run(["git", "-C", top, *args], capture_output=True, timeout=60,
                              env={**os.environ, **_GIT_ENV})
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


_REPOS: dict = {}


def repository(where: str) -> tuple[str, str] | None:
    """(top level, digest of HEAD, refs, staged entries and working-tree status with each listed path's stat); None
    when ``where`` is no repository. Computed once per process."""
    top = locations.repo_top(where)  # never the filesystem root: its tree is never scanned
    if top is None:
        return None
    if top not in _REPOS:
        status = _git(top, "status", "--porcelain=v1", "-z", "--untracked-files=normal") or b""
        listed = [entry[3:].decode("utf-8", "surrogateescape") for entry in status.split(b"\0") if len(entry) > 3]
        parts = [_git(top, "rev-parse", "HEAD"), _git(top, "for-each-ref", "--format=%(refname) %(objectname)"),
                 _git(top, "diff-index", "--cached", "--raw", "HEAD"),  # what is staged, not the index's stat
                 status, json.dumps([_stat(os.path.join(top, p)) for p in listed]).encode()]
        _REPOS[top] = hashlib.sha256(b"\0".join(p or b"-" for p in parts)).hexdigest()
    return top, _REPOS[top]


def _modules(harness: Path) -> dict:
    found = {}
    for module in list(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if isinstance(name, str) and name.startswith(str(harness)):
            found[name] = _stat(name)
    return found


def facts(reads: Reads, harness: Path) -> dict | None:
    """The key of a finished computation; None when it ran a program other than git."""
    if reads.foreign:
        return None
    repos = {}
    for where in sorted(reads.repos):
        found = repository(where)
        repos[where] = found[1] if found else None
    return {"paths": {p: _stat(p) for p in sorted(reads.paths)}, "repos": repos,
            "transcripts": {p: reads.covered[p] for p in sorted(reads.covered)},
            "answers": [reads.tasks[k] for k in sorted(reads.tasks)],
            "refusals": {s: _refusal_digest(s) for s in sorted(reads.refusals)}, "modules": _modules(harness),
            "env": sorted((k, v) for k, v in os.environ.items() if k.startswith("GIT_"))}


def recheck(key: dict, harness: Path) -> bool:
    """Whether every fact of ``key`` is as it was."""
    return _recheck(key, harness) is not None


def _recheck(key: dict, harness: Path) -> dict | None:
    """The stat of the conversations behind ``key``'s answers as they are now (the key's own while they are as
    they were) when every fact holds; None when one does not. A conversation that differs asks the answers again."""
    if any(_stat(p) != sig for p, sig in key.get("paths", {}).items()):
        return None
    if any(_stat(p) != sig for p, sig in key.get("modules", {}).items()):
        return None
    if any(_refusal_digest(s) != d for s, d in key.get("refusals", {}).items()):
        return None
    if key.get("env") != [list(kv) for kv in sorted((k, v) for k, v in os.environ.items() if k.startswith("GIT_"))]:
        return None
    for where, digest in key.get("repos", {}).items():
        found = repository(where)
        if (found[1] if found else None) != digest:
            return None
    kept = key.get("transcripts") or {}
    now = {p: _stat(p) for p in kept}
    if now != kept and any(_answer(*a[:3]) != a[3] for a in key.get("answers", ())):
        return None
    return now


def record_path(state_root: str, *names: str) -> Path:
    return Path(state_root) / DIR / (hashlib.sha256("\0".join(names).encode()).hexdigest()[:32] + ".json")


def load(path: Path, harness: Path):
    """The kept result at ``path`` while its facts hold; None otherwise."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("version") != VERSION or not isinstance(doc.get("key"), dict):
        return None
    now = _recheck(doc["key"], harness)
    if now is None:
        return None
    if now != (doc["key"].get("transcripts") or {}):  # the answers held while the conversations grew: renew the stats
        doc["key"]["transcripts"] = now
        _replace(path, doc)
    return doc.get("result")


def save(path: Path, key: dict, result) -> None:
    """Keep ``result`` under ``key`` (atomic replace); a record older than KEEP goes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for old in path.parent.glob("*.json"):
        try:
            if old.stat().st_mtime < now - KEEP:
                old.unlink()
        except OSError:
            pass
    _replace(path, {"version": VERSION, "key": key, "result": result})


def _replace(path: Path, doc: dict) -> None:
    """The record at ``path``, atomically replaced; an unwritable folder keeps the old one."""
    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(doc, handle)
        os.replace(tmp, path)
    except OSError:
        pass
