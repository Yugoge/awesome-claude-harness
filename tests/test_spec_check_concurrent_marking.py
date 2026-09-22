"""Concurrent-marking tests for scripts/spec-check.py and the slot write of
hooks/pretool-cp-checkin.py (harness backlog #97).

Every mutating subcommand (check-in, mark, waive, check-out, unlock) must be atomic with
respect to concurrent commands on the same spec: no lost update, no corrupt or partial slot
file for a lock-free reader, and a bounded wait that fails explicitly (exit 75, retryable)
instead of hanging. The tests are self-contained: they build throw-away projects under the
system temporary directory and never touch a live cp-state file.

Overrides: SPEC_CHECK_UNDER_TEST and CP_CHECKIN_HOOK_UNDER_TEST point the file at another copy
of the script and the hook (the default is the repository's own), so the same tests can be run
against a baseline copy and must fail there. Every subprocess wait and every lock wait below is
bounded, so a run against a defective copy fails instead of hanging.
"""
import contextlib
import fcntl
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

TRIALS = 20
SHORT_TRIALS = 5

REPO_ROOT = Path(__file__).resolve().parents[1]
SC = os.environ.get("SPEC_CHECK_UNDER_TEST") or str(REPO_ROOT / "scripts" / "spec-check.py")
HOOK = os.environ.get("CP_CHECKIN_HOOK_UNDER_TEST") or str(REPO_ROOT / "hooks" / "pretool-cp-checkin.py")

SPEC = "S-c-test"
LOCK_NAME = ".cp-checkin.lock"
RUN_TIMEOUT = 20  # seconds; bounds every single script run
LOCK_WAIT = "0.3"  # SPEC_CHECK_LOCK_TIMEOUT_SECONDS used by the deterministic timeout tests
SLOT_FILE_RE = re.compile(r"cp-state-qa(-\d+)?\.json")  # a failure message must name the slot file

# Start every process of a storm at one instant: the child sleeps until t0, then runs the target.
GATE = ("import sys, time, runpy\n"
        "t0 = float(sys.argv[1]); tgt = sys.argv[2]; sys.argv = [tgt] + sys.argv[3:]\n"
        "d = t0 - time.time()\n"
        "if d > 0: time.sleep(d)\n"
        "runpy.run_path(tgt, run_name='__main__')\n")
# Run the target under a file size limit so that writing the slot file fails for real.
FSIZE_LIMIT = ("import sys, resource, runpy\n"
               "n = int(sys.argv[1]); resource.setrlimit(resource.RLIMIT_FSIZE, (n, n))\n"
               "tgt = sys.argv[2]; sys.argv = [tgt] + sys.argv[3:]\n"
               "runpy.run_path(tgt, run_name='__main__')\n")


# ---------------------------------------------------------------- helpers

@contextlib.contextmanager
def project():
    root = tempfile.mkdtemp(prefix="spec-check-concurrent-")
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def env_for(root, **extra):
    env = dict(os.environ)
    env.pop("CLAUDE_AGENT_ID", None)
    env.pop("SPEC_CHECK_LOCK_TIMEOUT_SECONDS", None)
    env["CLAUDE_PROJECT_DIR"] = root
    env.update(extra)
    return env


def spec_dir(root):
    return os.path.join(root, ".claude", "specs", SPEC)


def slot_name(k, agent="qa"):
    return f"cp-state-{agent}.json" if k == 0 else f"cp-state-{agent}-{k + 1}.json"


def slot_payload(k, ncp, agent="qa"):
    cps = [{"id": f"cp-{i:02d}", "action": "probe", "status": "pending", "state": "pending",
            "waived_reason": None, "updated_at": "2026-01-01T00:00:00Z"} for i in range(1, ncp + 1)]
    return {"spec_id": SPEC, "agent_type": agent, "instance_id": None if k == 0 else k + 1, "generation": 1,
            "agent_id": f"id-{k + 1}", "is_running": True, "checked_in_at": "2026-01-01T00:00:00Z",
            "checked_out_at": None, "checkpoints": cps,
            "terminal_artifact": {"path": None, "exists": False, "validated_at": None}}


def build(root, slots, ncp):
    """Create `slots` running qa slots (owners id-1 ...) with `ncp` pending checkpoints each."""
    d = spec_dir(root)
    os.makedirs(d, exist_ok=True)
    for k in range(slots):
        with open(os.path.join(d, slot_name(k)), "w", encoding="utf-8") as fh:
            json.dump(slot_payload(k, ncp), fh, indent=2)
    return d


def cmd_args(cmd, k=0, i=1):
    if cmd in ("mark", "waive"):
        return [cmd, "--spec-id", SPEC, "--agent", "qa", "--agent-id", f"id-{k + 1}", "--cp-id", f"cp-{i:02d}"]
    if cmd == "check-out":
        return [cmd, "--spec-id", SPEC, "--agent", "qa", "--agent-id", f"id-{k + 1}"]
    if cmd == "check-in":
        return [cmd, "--spec-id", SPEC, "--agent", "qa", "--agent-id", f"new-{k}"]
    if cmd == "check-in-bump":
        return ["check-in", "--spec-id", SPEC, "--agent", "qa", "--agent-id", "id-1", "--bump-generation"]
    if cmd == "unlock":
        return ["unlock", "--spec-id", SPEC]
    raise ValueError(cmd)


def gated(root, target, args, t0, stdin_pipe=False):
    return subprocess.Popen([sys.executable, "-c", GATE, repr(t0), target] + args, env=env_for(root),
                            stdin=subprocess.PIPE if stdin_pipe else None, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def gather(procs, stdins=None):
    """Collect (returncode, stdout, stderr) of every process; a hung one is killed and reported."""
    out = []
    for n, proc in enumerate(procs):
        try:
            o, e = proc.communicate(input=stdins[n] if stdins else None, timeout=RUN_TIMEOUT * 2)
            out.append((proc.returncode, o, e))
        except subprocess.TimeoutExpired:
            proc.kill()
            o, e = proc.communicate()
            out.append((-999, o, "TIMEOUT (unbounded wait) " + e))
    return out


def storm_start(nprocs):
    return time.time() + 0.5 + 0.03 * nprocs


def run_sc(root, args, timeout=RUN_TIMEOUT, **extra):
    """Run the script under test once; a hung run returns rc -999 instead of hanging the suite."""
    try:
        proc = subprocess.run([sys.executable, SC] + args, env=env_for(root, **extra), capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return -999, "", f"TIMEOUT after {timeout}s (unbounded wait)"
    return proc.returncode, proc.stdout, proc.stderr


def load_slot(d, k):
    with open(os.path.join(d, slot_name(k)), encoding="utf-8") as fh:
        return json.load(fh)


def done_count(d, k):
    return sum(1 for cp in load_slot(d, k)["checkpoints"] if cp["state"] == "done")


def slot_bytes(d):
    return {n: Path(d, n).read_bytes() for n in os.listdir(d) if re.match(r"^cp-state-[a-z-]+\.json$", n)}


def leftovers(d):
    """Temporary files a writer left behind (dot-prefixed names ending .tmp)."""
    return sorted(n for n in os.listdir(d) if n.startswith(".") and n.endswith(".tmp"))


def slot_files(d):
    return sorted(n for n in os.listdir(d) if re.match(r"^cp-state-[a-z-]+(-\d+)?\.json$", n))


def explicit(stderr):
    return bool(stderr.strip()) and "Traceback" not in stderr


@contextlib.contextmanager
def held(path):
    """Hold an exclusive flock on `path` (created if absent), as a stuck script or hook would."""
    fh = open(path, "a")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    try:
        yield fh
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_main_in_process(module, monkeypatch, root, argv):
    """Run module.main() in this process; returns (rc, stdout, stderr, escaped_exception)."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", root)
    monkeypatch.delenv("CLAUDE_AGENT_ID", raising=False)
    monkeypatch.delenv("SPEC_CHECK_LOCK_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr(sys, "argv", [SC] + argv)
    out, err = io.StringIO(), io.StringIO()
    rc, escaped = None, None
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = module.main()
    except BaseException as exc:  # noqa: BLE001 - the point is to see what escapes
        escaped = exc
    return rc, out.getvalue(), err.getvalue(), escaped


class Reader(threading.Thread):
    """Lock-free reader: reads and decodes the given files in a loop, counting failures."""

    def __init__(self, paths):
        super().__init__(daemon=True)
        self.paths = list(paths)
        self.stop = threading.Event()
        self.reads = 0
        self.decode_failures = 0
        self.os_errors = 0

    def run(self):
        while not self.stop.is_set():
            for path in self.paths:
                try:
                    with open(path, encoding="utf-8") as fh:
                        json.loads(fh.read())
                    self.reads += 1
                except json.JSONDecodeError:
                    self.decode_failures += 1
                    self.reads += 1
                except OSError:
                    self.os_errors += 1

    def finish(self):
        self.stop.set()
        self.join(timeout=10)


# ---------------------------------------------------------------- storms: no lost update

def test_8_marks_one_slot_all_recorded():
    for trial in range(TRIALS):
        with project() as root:
            d = build(root, 1, 8)
            t0 = storm_start(8)
            res = gather([gated(root, SC, cmd_args("mark", 0, i), t0) for i in range(1, 9)])
            errs = " ".join(r[2] for r in res)
            assert all(r[0] == 0 for r in res), f"trial {trial}: exits {[r[0] for r in res]}: {errs[:300]}"
            assert done_count(d, 0) == 8, f"trial {trial}: only {done_count(d, 0)} of 8 marks recorded"
            assert "corrupt cp-state" not in errs and "no cp-state slot" not in errs, errs[:300]
            assert not leftovers(d), leftovers(d)
            assert os.path.exists(os.path.join(d, LOCK_NAME)), "marks must serialize on the directory lock file"


def test_27_marks_three_slots_all_recorded():
    for trial in range(TRIALS):
        with project() as root:
            d = build(root, 3, 9)
            t0 = storm_start(27)
            res = gather([gated(root, SC, cmd_args("mark", k, i), t0) for k in range(3) for i in range(1, 10)])
            errs = " ".join(r[2] for r in res)
            assert all(r[0] == 0 for r in res), f"trial {trial}: exits {sorted(set(r[0] for r in res))}: {errs[:300]}"
            got = sum(done_count(d, k) for k in range(3))
            assert got == 27, f"trial {trial}: only {got} of 27 marks recorded"
            assert "corrupt cp-state" not in errs and "no cp-state slot" not in errs, errs[:300]
            assert not leftovers(d), leftovers(d)


def test_concurrent_check_in_keeps_every_owner():
    for trial in range(TRIALS):
        with project() as root:
            t0 = time.time() + 0.7
            res = gather([gated(root, SC, cmd_args("check-in", k), t0) for k in range(8)])
            d = spec_dir(root)
            owners = set()
            for name in slot_files(d):
                owners.add(json.loads(Path(d, name).read_text(encoding="utf-8"))["agent_id"])
            assert all(r[0] == 0 for r in res), f"trial {trial}: exits {[r[0] for r in res]}"
            assert len(owners) == 8, f"trial {trial}: {len(owners)} owners kept of 8 ({slot_files(d)})"


def test_mixed_mark_waive_check_out_no_silent_loss():
    for trial in range(SHORT_TRIALS):
        with project() as root:
            d = build(root, 1, 12)
            t0 = storm_start(11)
            procs = [gated(root, SC, cmd_args("mark", 0, i), t0) for i in range(1, 6)]
            procs += [gated(root, SC, cmd_args("waive", 0, i), t0) for i in range(6, 11)]
            procs.append(gated(root, SC, cmd_args("check-out", 0), t0))
            res = gather(procs)
            state = load_slot(d, 0)  # must parse
            states = {cp["id"]: cp["state"] for cp in state["checkpoints"]}
            for n, (rc, _o, err) in enumerate(res[:10]):
                cp_id = f"cp-{n + 1:02d}"
                want = "done" if n < 5 else "waived-with-reason"
                if rc == 0:
                    assert states[cp_id] == want, f"trial {trial}: exit 0 but {cp_id} is {states[cp_id]}"
                else:
                    assert explicit(err), f"trial {trial}: non-zero exit without an explicit message: {err!r}"
            assert res[10][0] == 0, f"trial {trial}: check-out exit {res[10][0]}: {res[10][2][:200]}"
            assert state["is_running"] is False and state["checked_out_at"], "check-out was not recorded"


# ---------------------------------------------------------------- bounded waits, exit 75

def test_directory_lock_timeout_exits_75_and_retry_succeeds():
    with project() as root:
        d = build(root, 1, 6)
        before = slot_bytes(d)
        with held(os.path.join(d, LOCK_NAME)):
            for label in ("mark", "waive", "check-out", "check-in", "unlock"):
                t = time.monotonic()
                rc, out, err = run_sc(root, cmd_args(label, 0, 1), timeout=15, SPEC_CHECK_LOCK_TIMEOUT_SECONDS=LOCK_WAIT)
                took = time.monotonic() - t
                assert rc == 75, f"{label}: exit {rc} (want 75): {err[:200]}"
                assert "lock" in err.lower() and "retry" in err.lower(), f"{label}: message {err!r}"
                assert out == "", f"{label}: stdout must stay empty, got {out!r}"
                assert took < 5, f"{label}: bounded wait took {took:.1f}s"
            assert slot_bytes(d) == before, "a timed-out command changed a slot file"
        rc, out, err = run_sc(root, cmd_args("mark", 0, 1))
        assert rc == 0 and done_count(d, 0) == 1, f"the retry after release failed: rc={rc} {err[:200]}"


def test_slot_lock_timeout_exits_75_and_frees_other_callers():
    with project() as root:
        d = build(root, 2, 6)
        before = slot_bytes(d)
        with held(os.path.join(d, slot_name(0) + ".lock")):
            for label in ("mark", "waive", "check-out", "check-in-bump"):
                t = time.monotonic()
                rc, out, err = run_sc(root, cmd_args(label, 0, 2), timeout=6, SPEC_CHECK_LOCK_TIMEOUT_SECONDS=LOCK_WAIT)
                took = time.monotonic() - t
                assert rc == 75, f"{label}: exit {rc} (want 75): {err[:200]}"
                assert "lock" in err.lower() and "retry" in err.lower(), f"{label}: message {err!r}"
                assert out == "" and took < 5, f"{label}: stdout {out!r}, took {took:.1f}s"
            assert slot_bytes(d) == before
            # the timed-out callers released the directory lock: the other slot is still markable
            rc, out, err = run_sc(root, cmd_args("mark", 1, 1), timeout=6, SPEC_CHECK_LOCK_TIMEOUT_SECONDS=LOCK_WAIT)
            assert rc == 0, f"a stuck slot froze an unrelated slot: rc={rc} {err[:200]}"


def hold_for(path, seconds):
    """Hold the flock on `path` in a background thread for `seconds`; returns once it is held."""
    ready = threading.Event()

    def worker():
        with held(path):
            ready.set()
            time.sleep(seconds)
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    assert ready.wait(5), "could not take the lock for the test"
    return thread


def test_lock_timeout_env_invalid_means_default_and_zero_tries_once():
    with project() as root:
        d = build(root, 1, 8)
        lock = os.path.join(d, LOCK_NAME)
        with held(lock):
            rc, _o, err = run_sc(root, cmd_args("mark", 0, 1), timeout=10, SPEC_CHECK_LOCK_TIMEOUT_SECONDS="0")
            assert rc == 75, f"0 must try once and give up: rc={rc} {err[:200]}"
        for n, bad_value in enumerate(("abc", "", "-1", "nan", "inf"), start=2):
            holder = hold_for(lock, 1.0)
            t = time.monotonic()
            rc, _o, err = run_sc(root, cmd_args("mark", 0, n), timeout=20, SPEC_CHECK_LOCK_TIMEOUT_SECONDS=bad_value)
            took = time.monotonic() - t
            holder.join(timeout=10)
            assert rc == 0, f"value {bad_value!r} must mean the default wait, not 0: rc={rc} {err[:200]}"
            assert took >= 0.8, f"value {bad_value!r}: the mark did not wait for the holder ({took:.2f}s)"
        assert done_count(d, 0) == 5


def test_status_is_lock_free_while_the_directory_lock_is_held():
    with project() as root:
        d = build(root, 1, 3)
        with held(os.path.join(d, LOCK_NAME)):
            rc, out, err = run_sc(root, ["status", "--spec-id", SPEC], timeout=3)
        assert rc == 0 and "cp-01" in out, f"status was blocked by a held lock: rc={rc} {err[:200]}"


# ---------------------------------------------------------------- explicit failure, previous bytes intact

def test_fault_injection_replace_fails_explicitly_and_keeps_previous_bytes(monkeypatch):
    module = load_module(SC, "spec_check_under_test_replace")
    for label in ("mark", "waive", "check-out", "check-in", "check-in-bump", "unlock"):
        with project() as root:
            d = build(root, 1, 4)
            before = slot_bytes(d)

            def boom(*_a, **_k):
                raise OSError(28, "injected replace failure")
            monkeypatch.setattr(module.os, "replace", boom)
            rc, out, err, escaped = run_main_in_process(module, monkeypatch, root, cmd_args(label, 0, 1))
            monkeypatch.undo()
            assert escaped is None, f"{label}: an exception escaped instead of an explicit failure: {escaped!r}"
            assert rc not in (0, None), f"{label}: a failed replace looked like success"
            assert SLOT_FILE_RE.search(err) and "intact" in err and "retry" in err, f"{label}: message {err!r}"
            assert slot_bytes(d) == before, f"{label}: the previous slot bytes changed"
            assert not leftovers(d), f"{label}: temporary file left behind {leftovers(d)}"
            rc2, _o, err2 = run_sc(root, cmd_args("mark", 0, 1))
            assert rc2 == 0, f"{label}: the retry failed: {err2[:200]}"


def test_fault_injection_fsync_fails_explicitly_and_keeps_previous_bytes(monkeypatch):
    module = load_module(SC, "spec_check_under_test_fsync")
    with project() as root:
        d = build(root, 1, 4)
        before = slot_bytes(d)

        def boom(*_a, **_k):
            raise OSError(5, "injected fsync failure")
        monkeypatch.setattr(module.os, "fsync", boom)
        rc, _o, err, escaped = run_main_in_process(module, monkeypatch, root, cmd_args("mark", 0, 1))
        monkeypatch.undo()
        assert escaped is None and rc not in (0, None), f"rc={rc} escaped={escaped!r}"
        assert "intact" in err and slot_bytes(d) == before and not leftovers(d)


def test_fault_injection_write_file_size_limit_keeps_previous_bytes():
    for label in ("mark", "waive", "check-out", "check-in", "check-in-bump", "unlock"):
        with project() as root:
            d = build(root, 1, 4)
            before = slot_bytes(d)
            try:
                proc = subprocess.run([sys.executable, "-c", FSIZE_LIMIT, "256", SC] + cmd_args(label, 0, 1),
                                      env=env_for(root), capture_output=True, text=True, timeout=RUN_TIMEOUT)
            except subprocess.TimeoutExpired:
                pytest.fail(f"{label}: hung under a write failure")
            assert proc.returncode != 0, f"{label}: a failed write exited 0"
            assert explicit(proc.stderr), f"{label}: stderr {proc.stderr!r}"
            assert SLOT_FILE_RE.search(proc.stderr) and "intact" in proc.stderr, f"{label}: {proc.stderr!r}"
            assert slot_bytes(d) == before, f"{label}: the previous slot bytes changed"
            assert not leftovers(d), f"{label}: temporary file left behind"


def test_stale_temp_files_are_inert(monkeypatch):
    with project() as root:
        d = build(root, 1, 4)
        decoys = {".cp-state-qa.json.123.tmp": "stale", ".cp-state-qa.json.tmp": "stale2",
                  "cp-state-qa.json.tmp": "stale3", ".cp-state-qa.json.9.abcdef00.tmp": "stale4"}
        for name, text in decoys.items():
            Path(d, name).write_text(text, encoding="utf-8")
        rc, _o, err = run_sc(root, cmd_args("mark", 0, 1))
        assert rc == 0 and done_count(d, 0) == 1, err
        assert {n: Path(d, n).read_text(encoding="utf-8") for n in decoys} == decoys, "a decoy was touched"
    # a colliding temporary name (same pid, same suffix) is never overwritten: the writer picks another suffix
    module = load_module(SC, "spec_check_under_test_stale")
    with project() as root:
        d = build(root, 1, 4)
        names = iter(["deadbeef", "cafef00d"])
        monkeypatch.setattr(module.secrets, "token_hex", lambda _n=4: next(names))
        clash = f".cp-state-qa.json.{os.getpid()}.deadbeef.tmp"
        Path(d, clash).write_text("precious", encoding="utf-8")
        rc, _o, err, escaped = run_main_in_process(module, monkeypatch, root, cmd_args("mark", 0, 1))
        monkeypatch.undo()
        assert escaped is None and rc == 0, f"rc={rc} escaped={escaped!r} {err[:200]}"
        assert Path(d, clash).read_text(encoding="utf-8") == "precious", "a pre-existing temporary-like file was overwritten"
        assert done_count(d, 0) == 1


# ---------------------------------------------------------------- readers never see a partial file

def test_reader_loop_never_sees_a_partial_slot():
    for trial in range(SHORT_TRIALS):
        with project() as root:
            d = build(root, 3, 9)
            reader = Reader(os.path.join(d, slot_name(k)) for k in range(3))
            reader.start()
            try:
                t0 = time.time() + 1.0
                gather([gated(root, SC, cmd_args("mark", k, i), t0) for k in range(3) for i in range(1, 10)])
            finally:
                reader.finish()
            assert reader.reads > 100, f"trial {trial}: the reader made only {reader.reads} reads"
            assert reader.decode_failures == 0 and reader.os_errors == 0, (
                f"trial {trial}: reader saw {reader.decode_failures} partial files and {reader.os_errors} OS errors "
                f"in {reader.reads} reads")


def test_hook_slot_write_reader_loop_never_sees_a_partial_slot():
    hook = load_module(HOOK, "hook_under_test_reader")
    with project() as root:
        d = build(root, 1, 4)
        slot = Path(d, slot_name(0))
        reader = Reader([slot, slot])
        reader.start()
        try:
            for n in range(1000):
                hook._write_payload(slot, slot_payload(0, 4 + (n % 2) * 40))
        finally:
            reader.finish()
        assert reader.reads > 100
        assert reader.decode_failures == 0 and reader.os_errors == 0, (
            f"the hook's slot write is not atomic: {reader.decode_failures} partial reads, "
            f"{reader.os_errors} OS errors in {reader.reads} reads")


def test_hook_slot_write_fault_injection_keeps_previous_bytes(monkeypatch):
    hook = load_module(HOOK, "hook_under_test_fault")
    with project() as root:
        d = build(root, 1, 4)
        slot = Path(d, slot_name(0))
        before = slot.read_bytes()

        def boom(*_a, **_k):
            raise OSError(28, "injected replace failure")
        monkeypatch.setattr(hook.os, "replace", boom)
        with pytest.raises(OSError):
            hook._write_payload(slot, slot_payload(0, 40))
        monkeypatch.undo()
        assert slot.read_bytes() == before, "a failed hook write changed the previous slot bytes"
        assert not leftovers(d), leftovers(d)


def test_hook_reads_and_marks_coexist_on_one_slot():
    for trial in range(SHORT_TRIALS):
        with project() as root:
            d = build(root, 1, 8)
            lock_path = os.path.join(d, LOCK_NAME)
            Path(lock_path).touch()
            inode = os.stat(lock_path).st_ino
            slot = os.path.join(d, slot_name(0))
            t0 = storm_start(16)
            hook_in = json.dumps({"tool_name": "Read", "tool_input": {"file_path": slot}, "agent_id": "id-1"})
            procs = [gated(root, SC, cmd_args("mark", 0, i), t0) for i in range(1, 9)]
            procs += [gated(root, HOOK, [], t0, stdin_pipe=True) for _ in range(8)]
            res = gather(procs, stdins=[None] * 8 + [hook_in] * 8)
            assert all(r[0] == 0 for r in res), f"trial {trial}: exits {sorted(set(r[0] for r in res))}"
            assert done_count(d, 0) == 8, f"trial {trial}: {done_count(d, 0)} of 8 marks recorded next to 8 hook Reads"
            assert os.stat(lock_path).st_ino == inode, "the shared directory lock file was replaced"
            assert not leftovers(d), leftovers(d)


# ---------------------------------------------------------------- unlock

def test_unlock_alone_clears_every_slot_and_is_idempotent():
    with project() as root:
        d = build(root, 3, 4)
        before = {k: [cp["state"] for cp in load_slot(d, k)["checkpoints"]] for k in range(3)}
        for _ in range(2):
            rc, out, err = run_sc(root, cmd_args("unlock"))
            assert rc == 0 and "3" in out, f"rc={rc} out={out!r} err={err[:200]}"
        for k in range(3):
            data = load_slot(d, k)
            assert data["is_running"] is False and not data["agent_id"], f"slot {k} not cleared"
            assert [cp["state"] for cp in data["checkpoints"]] == before[k], "unlock changed checkpoint states"


def test_unlock_racing_marks_keeps_every_acknowledged_mark():
    for trial in range(SHORT_TRIALS):
        with project() as root:
            d = build(root, 3, 9)
            t0 = storm_start(13)
            marks = [(k, i) for k in range(3) for i in range(1, 5)]
            procs = [gated(root, SC, cmd_args("mark", k, i), t0) for k, i in marks]
            procs.append(gated(root, SC, cmd_args("unlock"), t0))
            res = gather(procs)
            assert res[-1][0] == 0, f"trial {trial}: unlock exit {res[-1][0]}: {res[-1][2][:200]}"
            for (k, i), (rc, _o, err) in zip(marks, res):
                states = {cp["id"]: cp["state"] for cp in load_slot(d, k)["checkpoints"]}
                if rc == 0:
                    assert states[f"cp-{i:02d}"] == "done", f"trial {trial}: mark k={k} i={i} exit 0 but not recorded"
                else:
                    assert explicit(err), f"trial {trial}: non-zero exit without an explicit message: {err!r}"
            for k in range(3):
                data = load_slot(d, k)
                assert data["is_running"] is False and not data["agent_id"], f"trial {trial}: slot {k} still running"


# ---------------------------------------------------------------- refusals change nothing; creation rules; modes

def test_refused_check_in_creates_nothing():
    with project() as root:
        rc, _o, err = run_sc(root, ["check-in", "--spec-id", SPEC, "--agent", "no-such-role", "--agent-id", "x"])
        assert rc != 0 and explicit(err), f"rc={rc} err={err!r}"
        assert not os.path.exists(os.path.join(root, ".claude")), "a refused check-in created files"
    with project() as root:
        rc, _o, err = run_sc(root, cmd_args("mark", 0, 1))  # spec directory does not exist
        assert rc != 0 and explicit(err), f"rc={rc} err={err!r}"
        assert not os.path.exists(os.path.join(root, ".claude")), "a refused mark on a missing spec created files"


def test_lock_file_is_created_and_never_replaced_and_slot_mode_is_kept():
    with project() as root:
        d = build(root, 1, 4)
        slot = os.path.join(d, slot_name(0))
        os.chmod(slot, 0o640)
        assert not os.path.exists(os.path.join(d, LOCK_NAME))
        assert run_sc(root, cmd_args("mark", 0, 1))[0] == 0
        lock = os.path.join(d, LOCK_NAME)
        assert os.path.exists(lock), "the marking script must create the shared directory lock file"
        inode = os.stat(lock).st_ino
        for i in (2, 3):
            assert run_sc(root, cmd_args("mark", 0, i))[0] == 0
        assert os.stat(lock).st_ino == inode, "the directory lock file was unlinked and recreated"
        assert stat.S_IMODE(os.stat(slot).st_mode) == 0o640, "an atomic replace must keep the slot mode"
        umask = os.umask(0)
        os.umask(umask)
        assert run_sc(root, cmd_args("check-in", 5))[0] == 0
        new_slots = [n for n in slot_files(d) if n != slot_name(0)]
        assert new_slots, "check-in should have allocated a second slot"
        assert stat.S_IMODE(os.stat(os.path.join(d, new_slots[0])).st_mode) == (0o666 & ~umask)
