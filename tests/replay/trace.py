"""strace capture of a replay and its reduction to relation events (E2).

The replay runs under `strace -f --seccomp-bpf -z -y` tracing opens (with
flags), creates, mkdirs, renames, links, unlinks, execs, forks and chdirs; -y
gives the resolved path of every returned fd and of AT_FDCWD. parse() turns
the raw trace into sorted, de-duplicated relation events (component, op,
pattern):

* component: the innermost harness file a process executed (the registered
  hook, or the harness script a hook or a Bash call ran: hooks/x.py,
  scripts/y.sh); else the simulated role whose call the driver was performing
  (main, agent:<type>), from the driver's actor markers, inherited by the
  processes it spawned; else "cli" (the driver writing transcripts and other
  CLI records);
* op: read, write, create, unlink, rename ("src -> dst");
* pattern: the path under a sandbox root token (<harness>, <project>, <origin>,
  <state>, <home>, or /tmp, /var/tmp, /dev/shm), with the replay's own ids and
  timestamps replaced by value (norm.py), and in the name of a file or
  directory the run created, the pid of the creating process or one of its
  ancestors replaced by <pid> and the random part a temp-name generator minted
  (an O_RDWR|O_EXCL create with mode 0600, a mkdir with mode 0700: mkstemp, mkdtemp,
  mktemp) replaced by <rand>.

Folding (row 19 rule 1): a file created in the run and renamed onto another
path is a same-run temporary and its events count for the destination; a lock
file (.lock/.lck) that is not renamed onto its file is dropped; a file that one
process creates and removes within the run is its private scratch and is
dropped, where one process is a component's process tree (a hook's mktemp,
shell and rm are one hook run; a harness script it executes starts its own).
Every write outside the scratch root is listed separately, temporaries
included, before any folding or root filtering.

Processes: pids are reused within a replay (pid_max may be small), so a
process's lifetime ends at its "+++ exited" line (strace -q keeps those lines),
and the k-th lifetime of a pid was started by the k-th fork that returned it,
whether the child's first call or the parent's fork is reported first.

relation-events.tsv keeps, per kept file event, what the artifact check's
differential needs (E1): the component, the origin (the outermost harness file
of the process tree: the registered hook, or the script a tool call ran), the
actor, the op, the pattern, the hook event it ran under (Replay.fire's seq, from
the driver's event markers), "bulk" for a read rule (3) leaves out (a program
that is not an interpreter reading most files directly in a directory it
listed, as `git add -A` does) and the raw path as the sandbox saw it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess

from . import norm

SYSCALLS = ("open,openat,openat2,creat,mkdir,mkdirat,rename,renameat,renameat2,unlink,unlinkat,"
            "link,linkat,symlink,symlinkat,execve,execveat,clone,clone3,fork,vfork,chdir")
_LINE_RE = re.compile(r"^(\d+)\s+(\w+)\((.*)\)\s+=\s+(-?\d+)(.*)$")
_RESUMED_RE = re.compile(r"^(\d+)\s+<\.\.\. \w+ resumed>(.*)$")
_EXIT_RE = re.compile(r"^(\d+)\s+\+\+\+ (?:exited|killed) ")
EXIT = "+++exit"
_ESC_RE = re.compile(r"\\(x[0-9a-fA-F]{2}|[0-7]{1,3}|.)")
_SIMPLE_ESC = {"n": 10, "t": 9, "r": 13, "v": 11, "f": 12, "a": 7, "b": 8, "e": 27}
_INTERP_RE = re.compile(r"^(?:(?:ba|da|z|k)?sh|python[0-9.]*|perl|node)$")
_PSEUDO = ("/dev/null", "/dev/tty", "/dev/pts/", "/dev/fd/", "/dev/std", "/proc/", "/sys/", "/dev/urandom",
           "/dev/random")
_LOCK_RE = re.compile(r"\.(?:lock|lck)$")
_FORKS = ("clone", "clone3", "fork", "vfork")


def available() -> tuple[bool, str]:
    try:
        p = subprocess.run(["strace", "-V"], capture_output=True, text=True)
    except OSError:
        return False, "strace not installed"
    text = (p.stdout or p.stderr).strip()
    return p.returncode == 0, text.splitlines()[0] if text else ""


def strace_argv(raw_path: str) -> list[str]:
    # -q, not -qq: the "+++ exited" lines delimit each process's lifetime (pids are reused)
    return ["strace", "-f", "--seccomp-bpf", "-z", "-q", "-e", "signal=none", "-y", "-s", "65535",
            "-e", "trace=" + SYSCALLS, "-o", raw_path, "--"]


# ---------------------------------------------------------------- strace syntax

def _split(s: str) -> list[str]:
    """Top-level comma split of an strace argument list (strings, [], {}, <> decorations nest)."""
    out, cur, depth, i = [], [], 0, 0
    while i < len(s):
        c = s[i]
        if c == '"':
            j = i + 1
            while j < len(s) and s[j] != '"':
                j += 2 if s[j] == "\\" else 1
            cur.append(s[i:j + 1])
            i = j + 1
            continue
        if c in "[{<":
            depth += 1
        elif c in "]}>":
            depth -= 1
        elif c == "," and depth == 0:
            out.append("".join(cur).strip())
            cur, i = [], i + 1
            continue
        cur.append(c)
        i += 1
    if cur:
        out.append("".join(cur).strip())
    return out


def _unescape(body: str) -> str:
    out, pos = bytearray(), 0
    for m in _ESC_RE.finditer(body):
        out += body[pos:m.start()].encode("utf-8", "surrogateescape")
        e = m.group(1)
        if e[0] == "x" and len(e) == 3:
            out.append(int(e[1:], 16))
        elif e[0] in "01234567":
            out.append(int(e, 8) & 0xFF)
        else:
            out.append(_SIMPLE_ESC.get(e, ord(e[0])))
        pos = m.end()
    out += body[pos:].encode("utf-8", "surrogateescape")
    return out.decode("utf-8", "replace")


def _cstr(tok) -> str | None:
    tok = (tok or "").strip()
    end = tok.rfind('"')
    return _unescape(tok[1:end]) if tok.startswith('"') and end > 0 else None


def _deco(tok: str) -> str | None:
    """The path of an fd decoration: AT_FDCWD</x>, 3</x>."""
    i = tok.find("<")
    return _unescape(tok[i + 1:tok.rfind(">")]) if i != -1 and tok.endswith(">") else None


def _argv(tok: str) -> list[str]:
    tok = (tok or "").strip()
    if not tok.startswith("["):
        return []
    return [s for s in (_cstr(t) for t in _split(tok[1:tok.rfind("]")])) if s is not None]


def _records(raw_path: str):
    """(pid, syscall, args, ret, tail, start) per completed call, in completion order; interrupted
    calls are stitched back together, and `start` is the line where the call began."""
    pending = {}
    with open(raw_path, encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh):
            line = line.rstrip("\n")
            start = n
            if line.endswith("<unfinished ...>"):
                pid, _, rest = line.partition(" ")
                pending[pid] = (rest.strip()[:-len("<unfinished ...>")].rstrip(), n)
                continue
            x = _EXIT_RE.match(line)
            if x:
                pending.pop(x.group(1), None)
                yield int(x.group(1)), EXIT, "", 0, "", n
                continue
            r = _RESUMED_RE.match(line)
            if r:
                head, start = pending.pop(r.group(1), ("", n))
                line = f"{r.group(1)} {head}{r.group(2)}"
            m = _LINE_RE.match(line)
            if m:
                yield int(m.group(1)), m.group(2), m.group(3), int(m.group(4)), m.group(5).strip(), start


def _rand_name(base: str, window: norm.Window) -> str | None:
    """A generator-minted basename with its random run (the last run of 6+ word characters) as <rand>."""
    for m in reversed(list(re.finditer(r"[A-Za-z0-9_]{6,}", base))):
        if not window.holds_ts(m.group(0)):
            return base[:m.start()] + "<rand>" + base[m.end():]
    return None


# ---------------------------------------------------------------- parse

class _Proc:
    __slots__ = ("pid", "comp", "actor", "step", "cwd", "owner", "root", "event", "origin", "exe", "fork_at")

    def __init__(self, pid, owner, comp=None, actor="", step="", cwd=None, root=False, event="", origin=None,
                 exe=""):
        self.pid, self.comp, self.actor, self.step, self.cwd = pid, comp, actor, step, cwd
        self.owner, self.root = owner, root
        # event: the hook event (Replay.fire's seq) the process was spawned under; origin: the
        # outermost harness file of its process tree (the registered hook, or the script a tool
        # call ran); exe: the program it executes.
        self.event, self.origin, self.exe = event, origin, exe
        self.fork_at = -1  # which lifetime of its pid this process is (pids are reused)

    def child(self, pid: int) -> "_Proc":
        # A process the driver spawns starts its own tree; deeper ones stay in their parent's.
        return _Proc(pid, pid if self.root else self.owner, self.comp, self.actor, self.step, self.cwd,
                     event=self.event, origin=self.origin, exe=self.exe)

    def component(self) -> str:
        return self.comp or self.actor or "cli"


class _Reducer:
    def __init__(self, out_dir: str):
        with open(os.path.join(out_dir, "ids.json")) as fh:
            meta = json.load(fh)
        lay = self.lay = meta["layout"]
        self.ids = norm.Ids.from_json(meta["ids"])
        self.window = norm.Window(*meta["window"])
        self.markers = {}
        with open(os.path.join(out_dir, "markers.jsonl")) as fh:
            for line in fh:
                m = json.loads(line)
                self.markers[m["seq"]] = (m["kind"], m["value"])
        self.exists = set()
        man = os.path.join(out_dir, "start-manifest.txt")
        if os.path.exists(man):
            with open(man, encoding="utf-8", errors="surrogateescape") as fh:
                self.exists = set(fh.read().splitlines())
        self.harness, self.mark_dir = lay["harness"].rstrip("/"), lay["markers"].rstrip("/")
        self.roots = norm.Roots([(lay["harness"], "<harness>"), (lay["project"], "<project>"),
                                 (lay["origin"], "<origin>"), (lay["state"], "<state>"), (lay["home"], "<home>"),
                                 (lay["sb"], "<sb>")] + [(d, d) for d in lay["temp_dirs"]])
        self.scratch = [p.rstrip("/") for p in lay["scratch"]]
        self.procs: dict[int, _Proc] = {}
        self.parent: dict[int, int] = {}
        # Pids are reused: the k-th lifetime of a pid (lifetimes end at its "+++ exited" line) was
        # started by the k-th fork that returned it, whichever is reported first (a child can run
        # before its parent's fork call is reported complete).
        self.forks: dict[int, list] = {}  # child pid -> parent pid of each fork returning it, in order
        self.lives: dict[int, int] = {}   # pid -> lifetimes started so far
        self.forked: dict[int, int] = {}  # pid -> forks returning it reported so far
        self.root_pid: int | None = None
        self.events = []    # [comp, op, path, step, inst, extra]
        self.inst_of: dict[str, int] = {}
        self.insts = []     # {"path", "owner", "created", "end"}
        self.minted: dict[str, str] = {}
        self.dirs = {r.rstrip("/") for r in [lay["home"], lay["state"], lay["sb"]] + lay["temp_dirs"]}
        self.listed: dict[tuple, set] = {}  # (pid, fork) -> directories that process opened for listing

    # ------------------------------------------------------------ process state
    def proc(self, pid: int) -> _Proc:
        """The process `pid` is now: the live one, or the next lifetime of that pid."""
        p = self.procs.get(pid)
        if p is None:
            n = self.lives.get(pid, 0)
            self.lives[pid] = n + 1
            if self.root_pid is None:
                self.root_pid = pid
            k = n - 1 if pid == self.root_pid else n  # the replay's own process: no traced fork
            forks = self.forks.get(pid) or []
            ppid = forks[k] if 0 <= k < len(forks) else None
            par = self.procs.get(ppid) if ppid is not None else None
            p = self.procs[pid] = par.child(pid) if par else _Proc(pid, pid, root=pid == self.root_pid)
            p.fork_at = k
            if ppid is not None:
                self.parent[pid] = ppid
        return p

    def script_of(self, p: _Proc, filename: str, argv: list) -> str | None:
        h = self.harness

        def rel(x):
            if x and not x.startswith("/") and p.cwd:
                x = os.path.join(p.cwd, x)
            # normalized first: `$DIR/../venv/bin/python3` is the venv's interpreter, not a
            # harness file of its own
            x = os.path.normpath(x) if x else x
            return x[len(h) + 1:] if x and x.startswith(h + "/") and not x.startswith(h + "/venv/") else None

        if rel(filename):
            return rel(filename)
        if _INTERP_RE.match(os.path.basename(filename)) or (argv and _INTERP_RE.match(os.path.basename(argv[0]))):
            for a in argv[1:]:
                if a in ("-c", "-m", "-"):
                    return None
                if not a.startswith("-"):
                    return rel(a)
        return None

    def resolve(self, p: _Proc, dirtok, path):
        if path is None:
            return None
        if path.startswith("/"):
            return os.path.normpath(path)
        base = (_deco(dirtok) if dirtok else None) or p.cwd
        return os.path.normpath(os.path.join(base, path)) if base else None

    # ------------------------------------------------------------ path instances
    def new_inst(self, path: str, p: _Proc, created: bool) -> int:
        self.insts.append({"path": path, "owner": p.owner, "created": created, "end": None})
        self.inst_of[path] = len(self.insts) - 1
        if created:
            self.exists.add(path)
        return self.inst_of[path]

    def inst(self, path: str, p: _Proc) -> int:
        i = self.inst_of.get(path)
        return self.new_inst(path, p, False) if i is None else i

    def emit(self, p: _Proc, op: str, path: str, i: int, extra=None) -> None:
        self.events.append([p.component(), op, path, p.step, i, extra, (p.origin or "", p.actor, p.event, p.exe, (p.pid, p.fork_at))])

    def mint(self, path: str, p: _Proc, temp: bool = False) -> None:
        """Name parts the run minted, taken by value from the creating call: a temp-name
        generator's random run, and the pid of the creating process or of one of its ancestors."""
        base = os.path.basename(path)
        new = (_rand_name(base, self.window) if temp else None) or base
        anc, pid = set(), p.pid
        while pid is not None and pid not in anc and len(anc) < 64:
            anc.add(pid)
            pid = self.parent.get(pid)
        new = re.sub(r"(?<![0-9])[0-9]{2,}(?![0-9])", lambda m: "<pid>" if int(m.group(0)) in anc else m.group(0), new)
        if new != base:
            self.minted[base] = new

    # ------------------------------------------------------------ syscalls
    def opened(self, p: _Proc, path: str, flags: str, mode: str) -> None:
        if "O_DIRECTORY" in flags or "O_PATH" in flags or "O_TMPFILE" in flags:
            if "O_DIRECTORY" in flags:
                self.listed.setdefault((p.pid, p.fork_at), set()).add(path)
            return
        if "O_WRONLY" not in flags and "O_RDWR" not in flags:
            self.emit(p, "read", path, self.inst(path, p))
            self.exists.add(path)
            return
        # Existence: the start manifest for the sandbox's own roots, plus everything this trace saw.
        if "O_CREAT" in flags and path not in self.exists:
            # a temp-name generator (mkstemp, mktemp) opens read-write; a write-only exclusive
            # create is code claiming a name it chose, which holds no random run
            self.mint(path, p, temp="O_EXCL" in flags and "O_RDWR" in flags and mode.strip() == "0600")
            self.emit(p, "create", path, self.new_inst(path, p, True))
        else:
            self.emit(p, "write", path, self.inst(path, p))
        if "O_RDWR" in flags and "O_TRUNC" not in flags:
            self.emit(p, "read", path, self.inst(path, p))

    def feed(self, pid: int, name: str, args: str, ret: int, tail: str, start: int = 0) -> None:
        if name == EXIT:
            if pid not in self.procs:
                self.proc(pid)  # a lifetime that made no traced call before its exit still was one
            self.procs.pop(pid, None)
            return
        p = self.proc(pid)
        a = _split(args)
        cwd = next((_deco(t) for t in a if t.startswith("AT_FDCWD<")), None)
        if cwd:
            p.cwd = cwd
        if name in _FORKS:
            if ret > 0:
                # the child, as its parent was when it forked, unless it ran already: a child can
                # run, and even exit, before its parent's fork is reported, and that fork then
                # starts no lifetime of its own (a phantom one would hand every later lifetime of
                # the pid the wrong fork, and so no parent)
                self.forked[ret] = self.forked.get(ret, 0) + 1
                if self.lives.get(ret, 0) - (ret == self.root_pid) < self.forked[ret]:
                    self.proc(ret)
        elif name in ("execve", "execveat"):
            k = 1 if name == "execveat" else 0
            script = self.script_of(p, _cstr(a[k] if len(a) > k else "") or "", _argv(a[k + 1] if len(a) > k + 1 else ""))
            p.exe = os.path.basename(_cstr(a[k] if len(a) > k else "") or "")
            if script:
                p.comp, p.owner = script, pid
                if p.origin is None:
                    p.origin = script
        elif name == "chdir":
            p.cwd = self.resolve(p, None, _cstr(a[0] if a else "")) or p.cwd
        elif name in ("open", "openat", "openat2", "creat"):
            if name == "creat":
                path, dirtok, flags, mode = _cstr(a[0]), None, "O_WRONLY|O_CREAT|O_TRUNC", a[1] if len(a) > 1 else ""
            elif name == "open":
                path, dirtok = _cstr(a[0]), None
                flags, mode = (a[1] if len(a) > 1 else ""), (a[2] if len(a) > 2 else "")
            else:
                path, dirtok = _cstr(a[1] if len(a) > 1 else ""), a[0]
                flags, mode = (a[2] if len(a) > 2 else ""), (a[3] if len(a) > 3 else "")
                if name == "openat2":
                    fm, mm = re.search(r"flags=([A-Z_|0-9x]+)", flags), re.search(r"mode=(0[0-7]*)", flags)
                    flags, mode = (fm.group(1) if fm else ""), (mm.group(1) if mm else "")
            full = _deco(tail) if tail.startswith("<") else None
            full = os.path.normpath(full) if full and full.startswith("/") else self.resolve(p, dirtok, path)
            if not full:
                return
            if full.startswith(self.mark_dir + "/"):
                kind, value = self.markers.get(int(os.path.basename(full).split(".")[0]), ("", ""))
                if kind == "actor":
                    p.actor = value
                elif kind == "step":
                    p.step = value
                elif kind == "event":
                    p.event = value
                return
            self.opened(p, full, flags, mode)
        elif name in ("mkdir", "mkdirat"):
            k = 1 if name == "mkdirat" else 0
            path = self.resolve(p, a[0] if k else None, _cstr(a[k] if len(a) > k else ""))
            if path:
                self.dirs.add(path)
                self.mint(path, p, temp=len(a) > k + 1 and a[k + 1].strip() == "0700")
        elif name in ("unlink", "unlinkat"):
            if name == "unlinkat" and len(a) > 2 and "AT_REMOVEDIR" in a[2]:
                return
            path = self.resolve(p, a[0] if name == "unlinkat" else None,
                                _cstr(a[1] if name == "unlinkat" and len(a) > 1 else a[0] if a else ""))
            if path:
                i = self.inst(path, p)
                self.emit(p, "unlink", path, i)
                self.insts[i]["end"] = ("unlink", p.owner)
                self.exists.discard(path)
                self.inst_of.pop(path, None)
        elif name in ("rename", "renameat", "renameat2", "link", "linkat"):
            if name in ("rename", "link"):
                src = self.resolve(p, None, _cstr(a[0] if a else ""))
                dst = self.resolve(p, None, _cstr(a[1] if len(a) > 1 else ""))
            else:
                src = self.resolve(p, a[0], _cstr(a[1] if len(a) > 1 else ""))
                dst = self.resolve(p, a[2] if len(a) > 2 else None, _cstr(a[3] if len(a) > 3 else ""))
            if not src or not dst:
                return
            existed = dst in self.exists
            si = self.inst(src, p)
            di = self.inst_of.get(dst) if existed else None  # a replaced file keeps its identity
            if di is None:
                di = self.new_inst(dst, p, not existed)
                if not existed:
                    self.mint(dst, p)
            if name.startswith("link"):
                self.emit(p, "write" if existed else "create", dst, di)
                return
            self.insts[si]["end"] = ("rename", di, existed)
            self.exists.discard(src)
            self.inst_of.pop(src, None)
            self.emit(p, "rename", src, si, dst)
        elif name in ("symlink", "symlinkat"):
            path = self.resolve(p, a[1] if name == "symlinkat" and len(a) > 2 else None, _cstr(a[-1] if a else ""))
            if path:
                existed = path in self.exists
                if not existed:
                    self.mint(path, p)
                self.emit(p, "write" if existed else "create", path, self.new_inst(path, p, not existed))

    # ------------------------------------------------------------ folding and output
    def final(self, i: int, seen=()) -> tuple[int, bool]:
        """(instance, replaced_existing) a same-run temporary ends up as, following renames."""
        end = self.insts[i]["end"]
        if end and end[0] == "rename" and self.insts[i]["created"] and i not in seen:
            j, replaced = self.final(end[1], seen + (i,))
            return j, replaced or end[2]
        return i, False

    def private(self, i: int) -> bool:
        """Created and removed in the run by one process (a component's process tree)."""
        ins = self.insts[i]
        return bool(ins["created"] and ins["end"] and ins["end"][0] == "unlink" and ins["end"][1] == ins["owner"])

    def find_dirs(self) -> None:
        """A path that is an ancestor of another path seen is a directory, not a file artifact."""
        for path in list(self.exists) + [e[2] for e in self.events] + [e[5] for e in self.events if e[5]]:
            d = os.path.dirname(path)
            while d not in self.dirs and d not in ("/", ""):
                self.dirs.add(d)
                d = os.path.dirname(d)

    def bulk(self) -> set:
        """(pid, path) reads rule (3) leaves out: a program that is not an interpreter running
        harness code (git, tar, cp) reading most of the files directly in a directory it listed
        (auto-commit's `git add -A`) reads none of them as a reader."""
        out = set()
        files = {e[2] for e in self.events if e[2] not in self.dirs} | {p for p in self.exists if p not in self.dirs}
        by_dir: dict[str, set] = {}
        for f in files:
            by_dir.setdefault(os.path.dirname(f), set()).add(f)
        read_by: dict[int, set] = {}
        exe_of: dict[int, str] = {}
        for comp, op, path, step, i, extra, meta in self.events:
            if op == "read":
                read_by.setdefault(meta[4], set()).add(path)
                exe_of[meta[4]] = meta[3]
        for pid, dirs in self.listed.items():
            if _INTERP_RE.match(exe_of.get(pid, "") or "") or pid not in read_by:
                continue
            for d in dirs:
                kids = {f for f in by_dir.get(d, ()) if "/.git/" not in f + "/"}
                got = kids & read_by[pid]
                if len(got) >= 2 and len(got) * 5 >= len(kids) * 4:
                    out |= {(pid, f) for f in got}
        return out

    def kept(self):
        self.find_dirs()
        for comp, op, path, step, i, extra, _meta in self.events:
            if path in self.dirs or extra in self.dirs:
                continue
            if op == "rename" and self.insts[i]["created"]:
                continue  # a same-run temporary folds into its destination
            j, replaced = self.final(i)
            if self.private(j):
                continue  # private scratch
            if j != i:
                path = self.insts[j]["path"]
                if op == "create" and replaced:
                    op = "write"
            elif _LOCK_RE.search(path):
                continue  # a lock folds into the file it serves
            yield comp, op, path, step, extra, _meta

    def pattern(self, path: str | None) -> str | None:
        if path is None or "/__pycache__/" in path or path.startswith(self.harness + "/venv/"):
            return None
        tok = self.roots.token_path(path)
        if tok is None or tok.startswith("<sb>"):
            return None
        tok = "/".join(self.minted.get(s, s) for s in tok.split("/"))
        return norm.generic(self.window.sub(self.ids.sub(tok, self.window)))

    def outside(self) -> set:
        out = set()
        for comp, op, path, _step, _i, extra, _meta in self.events:
            if op == "read" or path in self.dirs:
                continue
            for pth in (path, extra):
                if pth and not pth.startswith(_PSEUDO) and not any(pth == s or pth.startswith(s + "/")
                                                                   for s in self.scratch):
                    out.add(f"{op}\t{pth}\t{comp}")
        return out


def parse(raw_path: str, out_dir: str) -> dict:
    """Reduce `raw_path` using the run's out_dir files (ids.json, markers.jsonl, start-manifest.txt);
    writes relations.tsv, relation-steps.tsv, outside-writes.txt and trace-stats.json there."""
    r = _Reducer(out_dir)
    recs = list(_records(raw_path))
    for pid, name, _a, ret, _t, _start in recs:
        if name in _FORKS and ret > 0:
            r.forks.setdefault(ret, []).append(pid)
    for rec in recs:
        r.feed(*rec)
    rel, rel_steps, rel_events, kept = set(), set(), set(), 0
    bulk = r.bulk()
    for comp, op, path, step, extra, meta in r.kept():
        kept += 1
        pat = r.pattern(path)
        raw = path
        if op == "rename":
            dst = r.pattern(extra)
            if pat is None and dst is None:
                continue
            pat = f"{pat or '?'} -> {dst or '?'}"
            raw = extra
        if pat is None:
            continue
        rel.add(f"{comp}\t{op}\t{pat}")
        rel_steps.add(f"{comp}\t{op}\t{pat}\t{norm.generic(r.window.sub(r.ids.sub(step, r.window)))}")
        origin, actor, event, exe, pid = meta
        if "\t" not in raw and "\n" not in raw:
            # one line per file event and hook event: what E1's differential re-runs and mutates
            rel_events.add(f"{comp}\t{origin}\t{actor}\t{op}\t{pat}\t{event}\t"
                           f"{'bulk' if (pid, path) in bulk else ''}\t{raw}")
    outside = r.outside()  # after kept(): directories are known

    def dump(name, lines):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8", errors="surrogateescape") as fh:
            fh.write("".join(line + "\n" for line in sorted(lines)))

    dump("relations.tsv", rel)
    dump("relation-steps.tsv", rel_steps)
    dump("relation-events.tsv", rel_events)
    dump("outside-writes.txt", outside)
    stats = {"raw_bytes": os.path.getsize(raw_path), "syscalls": len(recs), "processes": len(r.procs),
             "file_events": len(r.events), "kept_events": kept, "relations": len(rel),
             "outside_writes": len(outside), "minted_names": len(r.minted), "relation_events": len(rel_events),
             "bulk_reads": len(bulk)}
    with open(os.path.join(out_dir, "trace-stats.json"), "w") as fh:
        json.dump(stats, fh, indent=1)
    return stats


def manifest(lay, out_dir: str) -> int:
    """Regular files under the replay's own roots at replay start (tells a create from a write)."""
    roots = [lay.home, lay.state] + (lay.temp_dirs if lay.mode == "ns" else [])
    venv = os.path.join(lay.harness, "venv")
    paths = []
    for root in roots:
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if os.path.join(dp, d) != venv]
            paths.extend(os.path.join(dp, f) for f in fns)
    with open(os.path.join(out_dir, "start-manifest.txt"), "w", encoding="utf-8", errors="surrogateescape") as fh:
        fh.write("".join(p + "\n" for p in sorted(set(paths))))
    return len(paths)
