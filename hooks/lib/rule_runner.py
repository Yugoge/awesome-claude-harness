"""Run one rule file in this process as if the CLI had run it as a hook.

A merged gate (hooks/pretool-write-gate.py) holds several rules that were
separate hooks. Each rule keeps its own file and its own ``__main__`` block, so
it decides exactly as it did alone; this module runs that file in the gate's
process instead of a new interpreter:

- the rule reads the hook payload from its own ``sys.stdin``;
- what it writes to fd 1 and fd 2 (its prints, ``sys.stdout.buffer``, a child
  process it starts) is captured per rule, at the file-descriptor level;
- its exit status is the ``SystemExit`` it raises (0 when it returns);
- ``os.environ``, the working directory, ``sys.argv`` and ``sys.path`` are
  restored after it, so one rule cannot change what the next one sees;
- a rule that runs past its budget is stopped: a watchdog thread sends SIGUSR2 to
  the main thread (not SIGALRM, which lib/allowlist's regex timeout uses and resets).

The caller decides what an error or an overrun means for that rule (its
failure direction); this module only reports it.
"""
from __future__ import annotations

import io
import os
import runpy
import signal
import sys
import tempfile
import threading
import time
from dataclasses import dataclass


class RuleOverrun(BaseException):
    """Raised inside a rule that ran past its budget (BaseException, so a rule's
    own ``except Exception`` cannot swallow it)."""


@dataclass
class RuleRun:
    code: int            # the exit status the rule chose (as the CLI would see it)
    stdout: str
    stderr: str
    error: str = ""      # set when the rule raised past its own handlers, or overran
    overrun: bool = False
    seconds: float = 0.0


def _status(code) -> tuple[int, str]:
    """Exit status and stderr text of ``SystemExit(code)``, as the interpreter maps them."""
    if code is None:
        return 0, ""
    if isinstance(code, bool):
        return int(code), ""
    if isinstance(code, int):
        return code & 0xFF if code >= 0 else (code % 256), ""
    return 1, f"{code}\n"


_ARMED = [False]   # True only while a rule's own code runs: a late signal is ignored


def _on_overrun(signum, frame):  # pragma: no cover - timing dependent
    if _ARMED[0]:
        _ARMED[0] = False
        raise RuleOverrun()


def run_rule(path: str, payload: bytes, budget: float) -> RuleRun:
    """Run ``path`` as ``__main__`` with ``payload`` on stdin, within ``budget`` seconds."""
    saved_env = dict(os.environ)
    saved_cwd = os.getcwd()
    saved_argv, saved_path = list(sys.argv), list(sys.path)
    saved_streams = (sys.stdin, sys.stdout, sys.stderr)
    saved_fds = (os.dup(1), os.dup(2))
    out_f = tempfile.TemporaryFile()
    err_f = tempfile.TemporaryFile()
    code, extra, error, overrun = 0, "", "", False
    start = time.monotonic()
    old_handler = signal.signal(signal.SIGUSR2, _on_overrun)
    main_thread = threading.main_thread().ident
    done = threading.Event()

    def _watch():
        if not done.wait(max(budget, 0.001)) and _ARMED[0]:
            signal.pthread_kill(main_thread, signal.SIGUSR2)

    watchdog = threading.Thread(target=_watch, daemon=True)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(out_f.fileno(), 1)
        os.dup2(err_f.fileno(), 2)
        sys.stdin = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")
        sys.stdout = io.TextIOWrapper(os.fdopen(os.dup(1), "wb"), encoding="utf-8", write_through=True)
        sys.stderr = io.TextIOWrapper(os.fdopen(os.dup(2), "wb"), encoding="utf-8", write_through=True)
        sys.argv = [path]
        _ARMED[0] = True
        watchdog.start()
        try:
            runpy.run_path(path, run_name="__main__")
        except SystemExit as stop:
            _ARMED[0] = False
            code, extra = _status(stop.code)
        except RuleOverrun:
            code, overrun, error = 1, True, f"ran past its {budget:g} s budget"
        except BaseException as exc:  # the rule's own handlers did not catch it
            _ARMED[0] = False
            code, error = 1, f"{type(exc).__name__}: {exc}"
        finally:
            _ARMED[0] = False
            done.set()
    except RuleOverrun:  # the watchdog fired as the rule ended, before it was disarmed
        code, overrun, error = 1, True, f"ran past its {budget:g} s budget"
    finally:
        _ARMED[0] = False
        done.set()
        if watchdog.is_alive():
            watchdog.join()
        signal.signal(signal.SIGUSR2, old_handler)
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
                stream.close()
            except Exception:
                pass
        os.dup2(saved_fds[0], 1)
        os.dup2(saved_fds[1], 2)
        os.close(saved_fds[0])
        os.close(saved_fds[1])
        sys.stdin, sys.stdout, sys.stderr = saved_streams
        sys.argv[:], sys.path[:] = saved_argv, saved_path
        os.environ.clear()
        os.environ.update(saved_env)
        try:
            os.chdir(saved_cwd)
        except OSError:
            pass
    seconds = time.monotonic() - start
    out_f.seek(0)
    err_f.seek(0)
    stdout = out_f.read().decode("utf-8", "replace")
    stderr = err_f.read().decode("utf-8", "replace") + extra
    out_f.close()
    err_f.close()
    return RuleRun(code=code, stdout=stdout, stderr=stderr, error=error, overrun=overrun, seconds=seconds)
