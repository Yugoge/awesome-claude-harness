"""Run one hook file in this process as if the CLI had run it as `python3 <file>`.

A merged gate (hooks/pretool-write-gate.py) and the event dispatchers
(hooks/lib/hook_dispatch.py) hold several hook files that each ran as their own
process. Each file keeps its own ``__main__`` block, so it decides exactly as it
did alone; this module runs that file in the caller's process instead of a new
interpreter, and gives back what the interpreter would have given the CLI:

- the payload is on the file's own stdin: ``sys.stdin`` and file descriptor 0
  (a child process it starts without input reads the payload, as it did);
- what it writes to fd 1 and fd 2 (its prints, ``sys.stdout.buffer``, a child
  process it starts) is captured per run, at the file-descriptor level;
- its exit status is the ``SystemExit`` it raises (0 when it returns), or the
  status it passes to ``os._exit``, which here ends the file instead of the
  process (no atexit handler of the file runs then, as none would have);
- an exception it does not catch goes to the ``sys.excepthook`` it installed, if
  it installed one (a hook that turns its own load failure into a refusal keeps
  doing so), else its traceback is written to its stderr and its status is 1;
- the atexit handlers it registers run when it ends, newest first, and the
  non-daemon threads it starts are waited for, as the interpreter does at exit;
- ``os.environ``, the working directory, the umask, ``sys.argv``, ``sys.path``,
  the recursion limit, ``sys.excepthook``, the warning filters, every signal
  handler and any interval timer it armed are put back after it, so one file
  cannot change what the next one sees;
- with ``fresh_modules``, every module it imported from the harness (a file under
  the harness home's hooks/ or scripts/) is dropped from ``sys.modules`` after it,
  so a value a library caches at import or keeps in a global never reaches the
  next file; the standard library and third-party packages stay loaded;
- a file that runs past its budget is stopped: a watchdog thread sends SIGUSR2 to
  the main thread (not SIGALRM, which lib/allowlist's regex timeout uses and
  resets), and ``RuleOverrun`` (a BaseException, which a file's own ``except
  Exception`` cannot swallow) ends it. Runs nest (a gate run by a dispatcher runs
  its own rules): each run has its own deadline, and an overrun ends the run
  whose budget it was. ``on_stuck``, if given, is called from the watchdog thread
  when the file is still running ``grace`` seconds after the overrun was sent
  (it swallowed even that, or is stuck where no signal handler runs): the caller
  then answers for the whole process.

The caller decides what an error or an overrun means for the file (its failure
direction); this module only reports it.
"""
from __future__ import annotations

import atexit
import io
import os
import runpy
import signal
import sys
import tempfile
import threading
import time
import traceback
import warnings
from dataclasses import dataclass

HARNESS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_HARNESS_DIRS = tuple(os.path.join(HARNESS, d) + os.sep for d in ("hooks", "scripts"))


class RuleOverrun(BaseException):
    """Raised inside a file that ran past its budget."""

    def __init__(self, frame=None):
        super().__init__()
        self.frame = frame


class _OsExit(BaseException):
    """``os._exit(status)`` called by the file: it ends the file, not this process."""

    def __init__(self, status):
        super().__init__(status)
        self.status = status


@dataclass
class RuleRun:
    code: int            # the exit status the file chose (as the CLI would see it)
    stdout: str
    stderr: str
    error: str = ""      # set when the file raised past its own handlers, or overran
    overrun: bool = False
    seconds: float = 0.0


def _status(code) -> tuple[int, str]:
    """Exit status and stderr text of ``SystemExit(code)``, as the interpreter maps them."""
    if code is None:
        return 0, ""
    if isinstance(code, bool):
        return int(code), ""
    if isinstance(code, int):
        return code & 0xFF, ""
    return 1, f"{code}\n"


class _Frame:
    __slots__ = ("deadline", "fired", "active")

    def __init__(self, deadline: float):
        self.deadline, self.fired, self.active = deadline, False, True


_STACK: list = []           # the runs in progress, outermost first
_REAL_OS_EXIT = os._exit


def _on_overrun(signum, frame):  # pragma: no cover - timing dependent
    for f in _STACK:  # the outermost expired run: its budget covers the inner ones
        if f.active and f.fired:
            f.active = False
            raise RuleOverrun(f)


def _signals() -> dict:
    out = {}
    for sig in signal.valid_signals():
        if sig in (signal.SIGKILL, signal.SIGSTOP):
            continue
        try:
            out[sig] = signal.getsignal(sig)
        except (OSError, ValueError):
            pass
    return out


def _restore_signals(saved: dict) -> None:
    for sig, handler in saved.items():
        if handler is None:
            continue
        try:
            if signal.getsignal(sig) is not handler:
                signal.signal(sig, handler)
        except (OSError, ValueError, TypeError):
            pass


def _harness_module(mod) -> bool:
    f = getattr(mod, "__file__", None) or ""
    return isinstance(f, str) and os.path.abspath(f).startswith(_HARNESS_DIRS)


def _trim(tb, path: str):
    """The traceback from the file's own frames on (the runner's and runpy's frames dropped)."""
    start = tb
    while tb is not None:
        if os.path.abspath(tb.tb_frame.f_code.co_filename) == path:
            return tb
        tb = tb.tb_next
    return start


def run_rule(path: str, payload: bytes, budget: float, *, fresh_modules: bool = False,
             on_stuck=None, grace: float = 2.0) -> RuleRun:
    """Run ``path`` as ``__main__`` with ``payload`` on stdin, within ``budget`` seconds."""
    path = os.path.abspath(path)
    saved_env = dict(os.environ)
    saved_cwd = os.getcwd()
    saved_umask = os.umask(0o022)
    os.umask(saved_umask)
    saved_argv, saved_path = list(sys.argv), list(sys.path)
    saved_limit = sys.getrecursionlimit()
    saved_hook = sys.excepthook
    saved_warnings = (list(warnings.filters), warnings.showwarning)
    saved_signals = _signals()
    saved_modules = set(sys.modules) if fresh_modules else None
    saved_threads = set(threading.enumerate())
    saved_streams = (sys.stdin, sys.stdout, sys.stderr)
    enc = {"stdin": (getattr(sys.__stdin__, "encoding", None) or "utf-8", getattr(sys.__stdin__, "errors", None) or "strict"),
           "stdout": (getattr(sys.__stdout__, "encoding", None) or "utf-8", getattr(sys.__stdout__, "errors", None) or "strict"),
           "stderr": (getattr(sys.__stderr__, "encoding", None) or "utf-8", "backslashreplace")}
    saved_fds = (os.dup(0), os.dup(1), os.dup(2))
    in_f = tempfile.TemporaryFile()
    in_f.write(payload)
    in_f.seek(0)
    out_f = tempfile.TemporaryFile()
    err_f = tempfile.TemporaryFile()
    code, extra, error, overrun = 0, "", "", False
    exits: list = []
    start = time.monotonic()
    frame = _Frame(start + max(budget, 0.001))
    outer_handler = signal.getsignal(signal.SIGUSR2) if not _STACK else None
    if not _STACK:
        signal.signal(signal.SIGUSR2, _on_overrun)
    _STACK.append(frame)
    main_thread = threading.main_thread().ident
    done = threading.Event()

    def _watch():
        if done.wait(max(budget, 0.001)) or not frame.active:
            return
        frame.fired = True
        try:
            signal.pthread_kill(main_thread, signal.SIGUSR2)
        except Exception:
            pass
        if on_stuck is not None and not done.wait(max(grace, 0.001)) and frame.fired:
            on_stuck()

    def _os_exit(status):
        raise _OsExit(status)

    def _register(func, *args, **kwargs):
        exits.append((func, args, kwargs))
        return func

    def _unregister(func):
        exits[:] = [e for e in exits if e[0] != func]

    watchdog = threading.Thread(target=_watch, daemon=True)
    ended_by_os_exit = False
    outer_exit = (os._exit, atexit.register, atexit.unregister)  # an enclosing run's, when runs nest
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(in_f.fileno(), 0)
        os.dup2(out_f.fileno(), 1)
        os.dup2(err_f.fileno(), 2)
        sys.stdin = io.TextIOWrapper(os.fdopen(os.dup(0), "rb"), encoding=enc["stdin"][0], errors=enc["stdin"][1])
        sys.stdout = io.TextIOWrapper(os.fdopen(os.dup(1), "wb"), encoding=enc["stdout"][0],
                                      errors=enc["stdout"][1], write_through=True)
        sys.stderr = io.TextIOWrapper(os.fdopen(os.dup(2), "wb"), encoding=enc["stderr"][0],
                                      errors=enc["stderr"][1], write_through=True)
        sys.argv = [path]
        os._exit = _os_exit
        atexit.register, atexit.unregister = _register, _unregister
        watchdog.start()
        try:
            runpy.run_path(path, run_name="__main__")
        except SystemExit as stop:
            code, extra = _status(stop.code)
        except _OsExit as stop:
            ended_by_os_exit = True
            code = stop.status & 0xFF if isinstance(stop.status, int) else 1
        except RuleOverrun as stop:
            if stop.frame is not frame:
                raise
            code, overrun, error = 1, True, f"ran past its {budget:g} s budget"
        except BaseException as exc:  # the file's own handlers did not catch it
            hook = sys.excepthook
            error = f"{type(exc).__name__}: {exc}"
            code = 1
            if hook is not saved_hook and hook is not sys.__excepthook__:
                try:  # the file's own excepthook decides, as the interpreter would let it
                    hook(type(exc), exc, exc.__traceback__)
                except SystemExit as stop:
                    code, extra = _status(stop.code)
                except _OsExit as stop:
                    ended_by_os_exit = True
                    code = stop.status & 0xFF if isinstance(stop.status, int) else 1
                except BaseException:
                    pass
                if code != 1:
                    error = ""
            else:
                try:
                    exc = exc.with_traceback(_trim(exc.__traceback__, path))
                    traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
                except Exception:
                    pass
        frame.active = frame.active and not frame.fired
        if not ended_by_os_exit and not overrun:
            # the interpreter's shutdown: non-daemon threads, then atexit handlers, newest first
            for t in [t for t in threading.enumerate() if t not in saved_threads and not t.daemon]:
                t.join(max(frame.deadline - time.monotonic(), 0.001))
            for func, args, kwargs in reversed(exits):
                try:
                    func(*args, **kwargs)
                except SystemExit:
                    pass
                except RuleOverrun:
                    raise
                except BaseException:
                    try:
                        sys.stderr.write("Exception ignored in atexit callback:\n" + traceback.format_exc())
                    except Exception:
                        pass
    except RuleOverrun as stop:  # the watchdog fired as the file ended, before it was disarmed
        if stop.frame is not frame:
            raise
        code, overrun, error = 1, True, f"ran past its {budget:g} s budget"
    finally:
        frame.active = False
        done.set()
        _STACK.remove(frame)
        if watchdog.is_alive():
            watchdog.join(0.5)
        os._exit, atexit.register, atexit.unregister = outer_exit
        try:
            signal.setitimer(signal.ITIMER_REAL, 0)
        except Exception:
            pass
        _restore_signals(saved_signals)
        if not _STACK:
            signal.signal(signal.SIGUSR2, outer_handler if outer_handler is not None else signal.SIG_DFL)
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            if stream in saved_streams:
                continue
            try:
                stream.flush()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        for fd, saved in zip((0, 1, 2), saved_fds):
            os.dup2(saved, fd)
            os.close(saved)
        sys.stdin, sys.stdout, sys.stderr = saved_streams
        sys.argv[:], sys.path[:] = saved_argv, saved_path
        sys.excepthook = saved_hook
        sys.setrecursionlimit(saved_limit)
        warnings.filters[:] = saved_warnings[0]
        warnings.showwarning = saved_warnings[1]
        os.umask(saved_umask)
        os.environ.clear()
        os.environ.update(saved_env)
        try:
            os.chdir(saved_cwd)
        except OSError:
            pass
        if saved_modules is not None:
            for name in [n for n in sys.modules if n not in saved_modules]:
                mod = sys.modules.get(name)
                if _harness_module(mod):
                    del sys.modules[name]
                    parent, _, child = name.rpartition(".")
                    if parent and getattr(sys.modules.get(parent), child, None) is mod:
                        delattr(sys.modules[parent], child)  # `from lib import x` would find it there
    seconds = time.monotonic() - start
    out_f.seek(0)
    err_f.seek(0)
    stdout = out_f.read().decode("utf-8", "replace")
    stderr = err_f.read().decode("utf-8", "replace") + extra
    for f in (in_f, out_f, err_f):
        f.close()
    return RuleRun(code=code, stdout=stdout, stderr=stderr, error=error, overrun=overrun, seconds=seconds)
