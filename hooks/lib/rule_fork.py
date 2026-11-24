"""Run several hook files at the same time, each in a fork of this process (P12-L7).

A launcher (lib/hook_launch.py) holds an event's Python hooks and, once its interpreter has
started, runs those a call matches at once: ``run_at_once`` forks one child per hook file from
the warm process, so no new interpreter starts and no two hook files ever share an interpreter.
Each child runs its file through lib/rule_runner (``run_rule``: the file as ``__main__``, its own
stdin, captured fd 1 and fd 2, exit status, atexit handlers, excepthook), with its own process
around it, so whatever the file changes (environment, working directory, umask, signal
handlers, file descriptors, modules) ends with the child. The child hands its result back on a
pipe (one length-prefixed JSON object) and ends; the parent waits for every child and returns
the results in the jobs' order, whatever order they finished in.

A job may name earlier jobs (``after``) it must start after: it starts once each of them has
ended; every other job starts at once.

Deadlines are kept by the parent, never by a thread in the child: a forked child starts no
thread before the file's own code runs (a merged gate run as one of the jobs may fork its own
rules the same way, which is only safe in a process with one thread). When a job's budget has
passed, the parent sends the child SIGUSR2 (the runner's overrun signal: ``RuleOverrun`` ends
the file, and the child hands back an overrun); a child still running ``grace`` seconds later
is ended with SIGKILL, that child alone (never its process group or session: a helper the file
started in a session of its own lives on), and answered as an overrun. A child that ends
without handing back a result failed as that file would have failed as its own process: a
non-blocking error (its status, never 0 or 2, so never an answer or a refusal it did not make).
A child that handed back its result is answered by it, however late the parent reads it (a
fallback it ran meanwhile, or a late wake, never makes an answer an error).

No child outlives the run that keeps its deadlines: when ``run_at_once`` ends early (SIGTERM or
SIGHUP, whose default action ends this process: the CLI ending the hook; an overrun of the run
around it, a merged gate's in a launcher's fork; a fault), each child still running is sent
SIGTERM, and SIGKILL ``ENDING`` seconds later, each alone, before the run ends (by that signal,
as this process ended before it forked); those signals are held back from before each fork until the child
is noted, so one arriving in between ends that child too. A run nested in a child of another run (a merged gate
in a launcher's fork) gives its own children half the wait of the run around it (``ending_wait``),
so it has killed and reaped them before that run kills it: a fork that ignores SIGTERM never
outlives both as an orphan. A child closes the pipe its own parent's result goes back on, so a
fork it makes never holds it open. A fault of this module's own code ends every child the same
way and is raised to the caller; ``finished(index, result)``, if given, has already been called
for each job that ended before it, so the caller can run only the others another way.

``can_fork`` says when forking is safe: ``os.fork`` and ``select.poll`` exist (POSIX), this is
the main thread, no other thread is alive (the threading module's count and, where /proc gives
it, the kernel's), and no run of lib/rule_runner in this process has a watchdog thread. The
caller runs its jobs one after another otherwise. A job whose child cannot be created (or whose
child's runner failed before handing back the file's result) is given to ``fallback(index)``,
called in the parent at once (lib/hook_launch: the hook as its own process), and the other
jobs still run at once.
"""
from __future__ import annotations

import json
import os
import select
import signal
import sys
import threading
import time
from dataclasses import dataclass

from lib import rule_runner
from lib.rule_runner import RuleOverrun, RuleRun

# Standard-library modules imported once before the forks (by hooks/lib/hook_launch.py and
# hooks/pretool-write-gate.py), so each fork does not import them again:
# pkgutil is the runner's own (runpy.run_path imports it for every file); pathlib (most hooks, through
# their libraries), datetime and shlex are what the hooks import most. Their import runs only their own
# definitions (no file, environment, working directory, signal or other module of the process changes),
# and the one-after-another run already gave every hook after the first that imports one the module
# loaded, so a fork that finds one loaded decides and prints as the hook did alone. Never a harness
# module (hooks/, scripts/): a hook's library must load in the hook's own fork.
WARM = ("pkgutil", "pathlib", "datetime", "shlex")
GRACE = 2.0  # seconds a child may run past its overrun signal before it is ended
ENDING = 0.5  # seconds the children of a run that ends early (below) have between SIGTERM and SIGKILL
# The signals that end this process while its children run (their default action ends it): the
# children are ended first, then this process ends by the same signal, as it did before it forked.
ENDING_SIGNALS = tuple(getattr(signal, n) for n in ("SIGTERM", "SIGHUP") if hasattr(signal, n))
_HAND_BACK = None  # in a child: the pipe its result goes back on (a fork of its own must not hold it)
_DEPTH = 0  # how many runs this process is a child of (a merged gate in a launcher's fork: 1)


class _Ended(BaseException):
    """One of ENDING_SIGNALS arrived while this process ran its children."""

    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


@dataclass(frozen=True)
class Job:
    path: str              # the hook file
    payload: bytes         # its stdin
    budget: float          # seconds, from its start
    after: tuple = ()      # indices of earlier jobs that must have ended before it starts


def _kernel_threads() -> int:
    """This process's thread count as the kernel has it (/proc/self/stat field 20); 1 where /proc
    does not give it."""
    try:
        with open("/proc/self/stat", "rb") as fh:
            fields = fh.read().rsplit(b")", 1)[1].split()
        return int(fields[17])
    except (OSError, IndexError, ValueError):
        return 1


def ending_wait() -> float:
    """The SIGTERM-to-SIGKILL wait this process gives its children when its run ends early: ENDING,
    halved for each run this process is itself a child of, so an inner run always ends its
    children before the run around it ends this process."""
    return ENDING / (2 ** _DEPTH)


def can_fork() -> bool:
    """True when this process may fork its jobs: POSIX, the main thread, and no other thread."""
    if not hasattr(os, "fork") or not hasattr(select, "poll"):
        return False
    if threading.current_thread() is not threading.main_thread():
        return False
    if threading.active_count() > 1 or rule_runner.watched():
        return False
    return _kernel_threads() <= 1


def _write_all(fd: int, data: bytes) -> None:
    while data:
        data = data[os.write(fd, data):]


def _child(job: Job, deadline: float, wfd: int, inherited, mark, dispositions=None, held=None) -> None:
    """In the forked child: run the file, hand back its result, end. Never returns. ``held``: the signal
    mask of the parent before the fork held the ending signals back; the child has it again once the
    parent's dispositions are back, so a signal that came in between meets them."""
    global _HAND_BACK, _DEPTH
    me = os.getpid()
    try:
        try:
            for sig, handler in (dispositions or {}).items():  # the parent's, from before its run
                signal.signal(sig, handler)
            if held is not None:
                signal.pthread_sigmask(signal.SIG_SETMASK, held)
            for fd in inherited:  # the other children's pipes, and the one this process's parent
                os.close(fd)      # hands back on (a merged gate run as a job): they end with their own
            _HAND_BACK = wfd
            _DEPTH += 1
            del rule_runner._STACK[:]  # an enclosing run's frames belong to the parent process
            if mark is not None:
                mark(True)
            try:
                rr = rule_runner.run_rule(job.path, job.payload, job.budget, watchdog=False, deadline=deadline)
            except RuleOverrun:  # the overrun arrived as the run began or ended, outside its own handler
                rr = RuleRun(1, "", "", error=f"ran past its {job.budget:g} s budget", overrun=True)
            if os.getpid() != me:  # a process the file forked returned here: it ends, as it did alone
                rule_runner._REAL_OS_EXIT(rr.code & 0xFF)
            signal.signal(signal.SIGUSR2, signal.SIG_IGN)  # a late overrun signal must not end the hand-back
            if mark is not None:
                mark(False)
            body = {"code": rr.code, "stdout": rr.stdout, "stderr": rr.stderr, "error": rr.error,
                    "overrun": rr.overrun, "seconds": rr.seconds}
        except BaseException as exc:  # the runner's own fault: the parent runs the job another way
            if os.getpid() != me:
                rule_runner._REAL_OS_EXIT(1)
            body = {"fault": f"{type(exc).__name__}: {exc}"}
        data = json.dumps(body).encode("utf-8")
        _write_all(wfd, b"%d\n" % len(data) + data)
    except BaseException:
        pass
    finally:
        rule_runner._REAL_OS_EXIT(0)


class _Running:
    __slots__ = ("index", "pid", "rfd", "start", "deadline", "kill_at", "signalled", "buf")

    def __init__(self, index, pid, rfd, start, deadline):
        self.index, self.pid, self.rfd, self.start, self.deadline = index, pid, rfd, start, deadline
        self.kill_at = None
        self.signalled = False
        self.buf = b""

    def frame(self):
        """The child's result object once it has all arrived, else None."""
        head, sep, rest = self.buf.partition(b"\n")
        if not sep:
            return None
        try:
            size = int(head)
        except ValueError:
            return {"fault": "unreadable hand-back"}
        if len(rest) < size:
            return None
        try:
            value = json.loads(rest[:size])
        except ValueError:
            return {"fault": "unreadable hand-back"}
        return value if isinstance(value, dict) else {"fault": "unreadable hand-back"}


def _reap(pid: int, wait: float | None):
    """The child's wait status (None while it still runs after `wait` seconds; None waits for it)."""
    end = None if wait is None else time.monotonic() + wait
    while True:
        try:
            got, status = os.waitpid(pid, 0 if end is None else os.WNOHANG)
        except ChildProcessError:
            return 0
        except OSError:
            return None
        if got == pid:
            return status
        if end is not None and time.monotonic() >= end:
            return None
        time.sleep(0.005)


def _died(job: Job, status) -> RuleRun:
    """A child that ended without handing back its file's result: a non-blocking error."""
    if status is not None and os.WIFSIGNALED(status):
        code, how = -os.WTERMSIG(status), f"signal {os.WTERMSIG(status)}"
    else:
        code = os.waitstatus_to_exitcode(status) if status is not None else 1
        how = f"exit status {code}"
        code = 1 if code in (0, 2) else code  # it did not answer: never an allow or a refusal
    text = f"{os.path.basename(job.path)}: ended without an answer ({how})\n"
    return RuleRun(code, "", text, error=text.strip())


def _overran(job: Job, seconds: float) -> RuleRun:
    return RuleRun(1, "", "", error=f"ran past its {job.budget:g} s budget and did not stop", overrun=True,
                   seconds=seconds)


def _put_back(dispositions: dict) -> None:
    for sig, handler in dispositions.items():
        try:
            signal.signal(sig, handler)
        except (OSError, ValueError):
            pass


def _end_all(pids, wait: float | None = None) -> None:
    """End each child (SIGTERM, as the CLI ended a hook; SIGKILL past ``wait``), each alone."""
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    end = time.monotonic() + (ending_wait() if wait is None else wait)
    left = list(pids)
    while left:
        left = [pid for pid in left if _reap(pid, 0) is None]
        if left and time.monotonic() >= end:
            for pid in left:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
                _reap(pid, 1.0)
            return
        if left:
            time.sleep(0.005)


def run_at_once(jobs, *, fallback=None, mark=None, grace: float = GRACE, finished=None) -> list:
    """Run every job at once (each after its ``after`` jobs), each in a fork of this process; their
    results (lib/rule_runner.RuleRun, or what ``fallback(index)`` gave) in the jobs' order.
    ``mark(index, running)``, if given, is called in each child before (True) and after (False)
    its file runs. ``finished(index, result)``, if given, is called in this process as each job's
    result is settled (so a caller whose run raised knows which jobs ended). The caller checks
    ``can_fork()`` first."""
    jobs = list(jobs)
    n = len(jobs)
    results: list = [None] * n
    state = ["waiting"] * n  # waiting, running, done
    running: list = []       # _Running, in start order
    poller = select.poll()

    def finish(i, result):
        results[i] = result
        state[i] = "done"
        if finished is not None:
            finished(i, result)

    def other(i):
        if fallback is not None:
            return fallback(i)
        return RuleRun(1, "", f"{os.path.basename(jobs[i].path)}: could not start\n", error="could not start")

    def start(i):
        state[i] = "running"
        job = jobs[i]
        try:
            rfd, wfd = os.pipe()
        except OSError:
            finish(i, other(i))
            return
        for stream in (sys.stdout, sys.stderr):  # what this process buffered must not reach a child
            try:
                stream.flush()
            except Exception:
                pass
        begun = time.monotonic()
        deadline = begun + max(job.budget, 0.001)
        # The ending signals are held from before the child exists until it is in ``running``: one that
        # arrives between would end this run with the child in no list ``_end_all`` reads, and it would
        # outlive the run. Held, it is acted on right after, with the child noted.
        held = signal.pthread_sigmask(signal.SIG_BLOCK, ENDING_SIGNALS)
        try:
            pid = os.fork()
        except OSError:
            signal.pthread_sigmask(signal.SIG_SETMASK, held)
            os.close(rfd)
            os.close(wfd)
            finish(i, other(i))
            return
        if pid == 0:
            os.close(rfd)
            _child(job, deadline, wfd, [r.rfd for r in running if r.rfd is not None]
                   + ([_HAND_BACK] if _HAND_BACK is not None else []),
                   None if mark is None else (lambda on: mark(i, on)), dispositions, held)
        try:
            os.close(wfd)
            os.set_blocking(rfd, False)
            running.append(_Running(i, pid, rfd, begun, deadline))
            poller.register(rfd, select.POLLIN | select.POLLHUP | select.POLLERR)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, held)  # a held signal is handled here: the child is noted

    def start_ready():
        moved = True
        while moved:  # a job its fallback answered at once may let a later one start
            moved = False
            for i in range(n):
                if state[i] == "waiting" and all(state[k] == "done" for k in jobs[i].after if 0 <= k < i):
                    start(i)
                    moved = True

    def close(run: _Running):
        if run.rfd is not None:
            poller.unregister(run.rfd)
            os.close(run.rfd)
            run.rfd = None

    def drain(run: _Running):
        """What the child wrote that this process has not read yet (it may have handed back its
        result, and ended, while this process was busy: a fallback, or a late wake)."""
        while run.rfd is not None and run.frame() is None:
            try:
                chunk = os.read(run.rfd, 1 << 16)
            except BlockingIOError:
                return
            except OSError:
                chunk = b""
            if not chunk:
                return
            run.buf += chunk

    def end(run: _Running, result=None, status=None):
        if result is None:
            drain(run)
        close(run)
        running.remove(run)
        i, job = run.index, jobs[run.index]
        if result is None:
            frame = run.frame()
            if frame is not None and "fault" in frame:
                result = other(i)
            elif frame is not None:
                result = RuleRun(int(frame.get("code", 1)), str(frame.get("stdout", "")),
                                 str(frame.get("stderr", "")), str(frame.get("error", "")),
                                 bool(frame.get("overrun")), float(frame.get("seconds", 0.0)))
            elif run.signalled:  # ended by (or past) its overrun signal before handing back
                result = _overran(job, time.monotonic() - run.start)
            else:
                result = _died(job, status)
        finish(i, result)
        start_ready()

    def ending(signum, frame):  # pragma: no cover - needs a signal from outside
        if os.getpid() != owner:  # a child that has not yet put back its parent's dispositions
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)
            return
        raise _Ended(signum)

    def loop():
        start_ready()
        while running:
            now = time.monotonic()
            wake = None
            for run in list(running):
                if run.rfd is None:  # its pipe closed without a whole result: it ends, or is ended
                    status = _reap(run.pid, 0)
                    if status is not None:
                        end(run, status=status)
                        continue
                if not run.signalled and now >= run.deadline:
                    status = _reap(run.pid, 0)
                    if status is not None:  # it already ended (its pipe is held by a process it forked)
                        end(run, status=status)
                        continue
                    run.signalled, run.kill_at = True, now + max(grace, 0.001)
                    try:
                        os.kill(run.pid, signal.SIGUSR2)
                    except OSError:
                        pass
                if run.signalled and now >= run.kill_at:
                    try:
                        os.kill(run.pid, signal.SIGKILL)  # this child alone, not its group or session
                    except OSError:
                        pass
                    _reap(run.pid, 1.0)
                    end(run)  # what it handed back before it was ended, else an overrun (signalled)
                    continue
                due = run.kill_at if run.signalled else run.deadline
                if run.rfd is None:
                    due = min(due, now + 0.01)  # no pipe to wake on: look again soon
                wake = due if wake is None else min(wake, due)
            if not running:
                break
            timeout = None if wake is None else max(0, int((wake - time.monotonic()) * 1000) + 1)
            for fd, _ in poller.poll(timeout):
                run = next((r for r in running if r.rfd == fd), None)
                if run is None:
                    continue
                try:
                    chunk = os.read(fd, 1 << 16)
                except BlockingIOError:
                    continue
                except OSError:
                    chunk = b""
                if chunk:
                    run.buf += chunk
                    if run.frame() is not None:
                        _reap(run.pid, None)  # it has handed back its result: it is ending
                        end(run)
                    continue
                close(run)  # end of its pipe
                status = _reap(run.pid, 0)
                if status is not None or run.frame() is not None:
                    end(run, status=status)

    owner = os.getpid()
    dispositions = {}  # each ending signal's disposition before this run: a child puts it back
    for sig in ENDING_SIGNALS:
        try:
            if signal.getsignal(sig) is signal.SIG_DFL:
                dispositions[sig] = signal.SIG_DFL
                signal.signal(sig, ending)
        except (OSError, ValueError):
            pass
    try:
        loop()
    except BaseException as exc:  # ended early (a signal, an overrun of the enclosing run, a fault):
        pending = []              # no child outlives the run whose deadlines it kept
        for sig in dispositions:
            signal.signal(sig, lambda signum, frame: pending.append(signum))
        _end_all([r.pid for r in running])
        for run in running:
            if run.rfd is not None:
                try:
                    os.close(run.rfd)
                except OSError:
                    pass
        _put_back(dispositions)
        signum = exc.signum if isinstance(exc, _Ended) else (pending[0] if pending else None)
        if signum is not None:  # end as that signal ended this process before it forked
            os.kill(os.getpid(), signum)
        raise
    _put_back(dispositions)
    return results
