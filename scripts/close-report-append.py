#!/usr/bin/env python3
# Description: Deterministic read-append-reread-verify helper for the
#              close-report append operation (commands/close.md Overwrite
#              policy, M3(d-1)). Replaces "always append, verified" prose
#              instruction with a single executable step, per ticket
#              20260908-015250 Should-Have S2.
#
# Usage: close-report-append.py --report-path <path> --section-file <path>
#                                --task-id <task-id> [--repo-root <path>]
#                                [--lock-timeout-seconds <float>]
#                                [--lock-poll-seconds <float>]
#                                [--marker-dir <path>]
#
# Inputs:
#   --report-path   Path to docs/dev/close-report-<task-id>.md (created if
#                    absent; existing bytes are NEVER touched in place --
#                    see Atomicity below).
#   --section-file  Path to a file containing the new dated section's full
#                    text (prepared by QA), whose own last non-empty line
#                    must be one of the legal `CLOSE:` forms
#                    (commands/close.md's Return value section) -- this is
#                    the new attempt's verdict line.
#   --task-id       Used to name the durable failure marker (see below).
#   --repo-root     Optional; default: script's parent-parent (this repo).
#   --lock-timeout-seconds
#                   Optional override for how long to wait for the
#                   per-report advisory lock (_acquire_lock) before
#                   failing with an "append"-stage sentinel. Default
#                   10.0 seconds. Also settable via the
#                   CLOSE_REPORT_APPEND_LOCK_TIMEOUT_SECONDS environment
#                   variable; the CLI flag wins when both are given. A
#                   malformed environment value is ignored (default used).
#                   Must be a finite number in [0, _LOCK_TIMING_MAX_SECONDS]
#                   (3600) -- an out-of-range CLI/env value is rejected via
#                   the same "append"-stage sentinel, never left to reach
#                   _acquire_lock's retry loop unvalidated (round-N fix,
#                   this revision -- see _validate_lock_timing).
#   --lock-poll-seconds
#                   Optional override for the lock-acquisition retry
#                   interval. Default 0.05 seconds. Also settable via
#                   CLOSE_REPORT_APPEND_LOCK_POLL_SECONDS (same
#                   CLI-wins-over-env, malformed-value-ignored rules).
#                   Same [0, _LOCK_TIMING_MAX_SECONDS] validation as
#                   --lock-timeout-seconds above: an uncaught, unvalidated
#                   negative value here previously reached time.sleep()
#                   inside the retry loop, raising an unhandled ValueError
#                   with completely empty stdout under genuine lock
#                   contention -- the exact defect this revision fixes.
#   --marker-dir    Optional override for the durable failure-marker
#                   directory (see "On failure" below). Default
#                   /tmp/claude-close-report-markers. Also settable via
#                   CLOSE_REPORT_APPEND_MARKER_DIR (CLI wins over env).
#
# Atomicity (codex round-4 CRITICAL finding, reproduced with a
# kernel-generated EFBIG): the original design wrote directly into the
# live report with `open(path, "ab")`. A write/flush/fsync failure AFTER
# some bytes had already landed left the live report PARTIALLY
# APPENDED -- worse than the bug being fixed, since a later reader would
# see neither the old accurate verdict nor a clean new one. This version
# never writes to the live report directly: it builds the full candidate
# content (pre_bytes + separator + new section) in a same-directory temp
# file, fsyncs and verifies THAT file, then publishes it onto the report
# path with `os.replace()` (atomic on POSIX same-filesystem renames). The
# live report is therefore always EITHER the old bytes, unchanged, OR the
# fully-landed new bytes -- never a partial mix. A same-task-id advisory
# file lock (fcntl.flock, bounded retry) serializes concurrent
# invocations so two overlapping appends cannot silently discard one
# another's content.
#
# Behavior: read existing report bytes (if any) + the section file ->
# validate the section's own last non-empty line is a legal `CLOSE:` form
# -> acquire the per-task lock -> re-read the report under the lock (a
# concurrent writer may have committed between the first read and lock
# acquisition) -> build and atomically publish the candidate -> reread
# the published report from disk -> verify (a) the pre-existing bytes are
# byte-identical, and (b) the reread's last non-empty line equals the
# section's own last non-empty line. Stages ("read", "append", "readback",
# "verification") use the exact vocabulary already documented in
# commands/close.md's Overwrite policy / Return value contract.
#
# Post-publish failure semantics (round-7 CRITICAL fix, this revision):
# once os.replace() has published the candidate, a "readback" or
# "verification" failure means the live report may already contain the
# NEW content -- treating it identically to a pre-publish failure (report
# untouched) would be a lie. So on any such failure this revision first
# ATTEMPTS to restore report_path to its exact pre-attempt bytes (same
# same-directory-temp-file + os.replace() mechanism as the original
# publish), then independently re-reads and byte-compares to CONFIRM the
# restoration -- never trusting a restore that merely appears to succeed.
#   - If confirmed restored: reported through the SAME
#     `CLOSE_REPORT_APPEND_ERROR: <stage>: <detail>` / exit-1 contract as
#     today -- now truthfully, since the report really is back to its
#     pre-attempt bytes.
#   - If the restoring write itself fails, its own confirmation fails, OR
#     the post-publish bytes matched neither the candidate NOR the
#     pre-existing content (a non-cooperating concurrent writer touched
#     report_path -- restoring would silently discard ITS content, so
#     restoration is not attempted at all in this sub-case): reported
#     through a brand-new `CLOSE_REPORT_APPEND_CRITICAL: <stage>: <detail>
#     | rollback not confirmed: <rollback_detail>` sentinel and exit code 4
#     -- never emitted for any pre-publish failure, never colliding with
#     the existing sentinel text or exit codes 0/1/2/3 (see AC6).
#
# On success: stdout is one line of JSON {"status":"ok","report_path":...,
# "verdict_line":...}; exit 0.
#
# On failure at any stage: stdout is exactly
#   CLOSE_REPORT_APPEND_ERROR: <read|append|readback|verification>: <error detail>
# (the pre-existing sanctioned sentinel form QA already returns verbatim as
# its own Return-value line) and exit 1 (or 3 -- see Exit codes below -- if
# the marker-write failure's own diagnostic stderr warning could also not
# be written). Additionally, a best-effort but
# fsynced, durable JSON marker is written to a DEDICATED directory --
#   /tmp/claude-close-report-markers/close-report-<task-id>-append-error-<UTC-compact-ts>.json
# -- deliberately NOT report_path.parent (docs/dev/) any longer: QA round-4
# proved with a real forced I/O failure (chattr +i on the report's own
# directory) that a directory-level failure (disk full, quota, immutable,
# read-only remount) affecting docs/dev/ specifically also took down the
# marker write, since both targeted the SAME now-unwritable directory,
# leaving ZERO on-disk trace. ON THIS HOST, independently verified this
# revision via `findmnt`/`stat -f` (not assumed): /tmp is a genuinely
# separate tmpfs mount from /dev/shm, where this repo (including docs/dev/)
# lives -- distinct filesystem IDs and independent capacities -- so a
# failure localized to docs/dev/ or to /dev/shm's own mount does not also
# fail here. This is a HOST-SPECIFIC, verified fact, not a portable
# guarantee: a different deployment could have /tmp and the repo checkout
# on the same filesystem, or /tmp could be disk-backed rather than tmpfs.
# It is also NOT a crash/reboot durability claim on THIS host either --
# /tmp is tmpfs too, exactly as volatile across a power loss as /dev/shm --
# it is narrower still: independence from the ONE directory/mount whose
# failure caused the primary error, verified for this checkout only.
# Marker files are never overwritten -- each failed attempt gets its own
# timestamped record, mirroring this repo's own dev-report-iter<N>-/
# qa-report-<..>-round<N> append-only-evidence convention -- so that, WHEN
# THE MARKER WRITE ITSELF SUCCEEDS, a later reader inspecting the marker
# directory can tell, from what is on disk, that an attempt was made and
# failed -- even when the report's own last line still (correctly) shows
# an earlier, unrelated closure's verdict. A failure while writing the
# marker itself is still caught so it never prevents the sentinel line
# above from being printed (the sentinel/fail-closed contract never
# depends on the marker succeeding) -- but it is no longer silent: the
# helper ATTEMPTS an explicit, labeled stderr warning naming the task-id,
# the original failure stage, and the marker-write error itself. This is
# not a persistent-evidence guarantee: if the invoking caller does not
# capture or log this process's stderr, the warning is not itself durable
# -- it is a best-effort operator-visible signal, not a second on-disk
# record. KNOWN, DISCLOSED, NOT FIXED THIS REVISION (out of the two
# explicitly authorized actions -- relocate; never-fail-silently -- for
# this bounded fix): the marker file's own containing directory entry is
# not fsynced after creation (unlike the report-publish path below, which
# does fsync its directory), so even a successful marker write is not
# guaranteed to survive a crash immediately afterward. An earlier draft of
# this revision added that directory-fsync; it was removed after adversarial
# review found it exceeded the two authorized actions AND was itself
# silently swallowed on failure -- exactly the inconsistency this revision
# exists to eliminate elsewhere -- disclosed here directly rather than by
# pointing to an external review transcript.
#
# Exit codes: 0 = appended and verified; 1 = failed (sentinel printed;
# marker written on a best-effort basis); 2 = bad invocation
# (missing/invalid arguments); 3 = failed AND the marker-write failure's
# own diagnostic stderr warning could also not be written (a compounded
# I/O failure -- e.g. stderr itself is a full or broken descriptor,
# round-5-QA reproduced with a real /dev/full). The sentinel line is
# still printed on stdout in every case; exit code 3 is the only signal
# of this specific compounded failure, chosen because it is observable
# through a route (process exit status) that does not depend on stderr
# working -- unlike the stderr warning itself, which is what just failed.
# 4 = a POST-publish failure whose own rollback attempt could not itself
# be confirmed, OR a detected concurrent-writer conflict where rollback
# was deliberately not attempted (round-7 CRITICAL fix, this revision --
# see "Post-publish failure semantics" above). Checked after the exit-3
# check: a broken stderr descriptor is the more severe, higher-priority
# signal and still wins if both conditions somehow coincide.
#
# Root cause addressed: commands/close.md's close-report Overwrite policy
# specified only that a retry must "always append, verified" -- left to be
# followed correctly by an agent reading prose instructions alone; this
# script makes that sequence deterministic and self-verifying instead.

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader
from pathlib import Path

_LOCK_TIMEOUT_SECONDS = 10.0
_LOCK_POLL_SECONDS = 0.05

# Environment-variable override names (main()'s CLI flags take precedence
# over these when both are given; see module docstring's Inputs section).
_ENV_LOCK_TIMEOUT_SECONDS = "CLOSE_REPORT_APPEND_LOCK_TIMEOUT_SECONDS"
_ENV_LOCK_POLL_SECONDS = "CLOSE_REPORT_APPEND_LOCK_POLL_SECONDS"
_ENV_MARKER_DIR = "CLOSE_REPORT_APPEND_MARKER_DIR"


def _load_close_verdict_module(repo_root: Path):
    """Load hooks/lib/close-verdict.py via SourceFileLoader (hyphenated
    filename -- not a valid Python module name for a normal import)."""
    path = repo_root / "hooks" / "lib" / "close-verdict.py"
    if not path.is_file():
        raise FileNotFoundError(f"close-verdict.py not found at {path}")
    return SourceFileLoader("close_verdict", str(path)).load_module()


def _resolve_repo_root(override: str | None) -> Path:
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def _now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# Dedicated marker directory (round-4-QA finding, this revision): NOT
# report_path.parent -- see the module docstring's "On failure" section
# for the full rationale (independence from docs/dev/'s own directory/mount
# failure modes; not a crash/reboot durability claim). Module-level so
# tests can monkeypatch it to a scratch directory instead of touching the
# real /tmp. Overridable at runtime via main()'s --marker-dir flag or the
# CLOSE_REPORT_APPEND_MARKER_DIR environment variable (see module docstring
# Inputs section); this constant is the default when neither is given.
_DEFAULT_MARKER_DIR = Path("/tmp/claude-close-report-markers")


def _marker_dir() -> Path:
    return _DEFAULT_MARKER_DIR


# Set by _safe_write_failure_marker (round-5-QA finding, this revision)
# when its own terminal-layer stderr diagnostic write itself fails (e.g.
# stderr is a full/broken descriptor). Reset at the top of every run()
# invocation so state never leaks between calls in the same process
# (this script's own test suite calls run() directly, more than once,
# in-process). main() reads this after run() returns to choose exit
# code 3; a test calling run()/_safe_write_failure_marker directly can
# read it the same way.
_stderr_diagnostic_write_failed = False


def _write_failure_marker(report_path: Path, task_id: str, stage: str, detail: str,
                           prior_last_line: str, expected_last_line: str | None,
                           actual_last_line: str | None,
                           failure_class: str = "pre_publish",
                           rollback_detail: str | None = None) -> Path | None:
    """Best-effort write of a durable, never-overwritten JSON marker
    recording a failed append attempt, into _marker_dir() -- a directory
    independent of report_path's own directory/mount (see module
    docstring). Each failure gets its own timestamped, fsynced file (its
    own contents only -- the containing directory entry is NOT fsynced;
    see module docstring's "KNOWN, DISCLOSED, NOT FIXED" note) so multiple
    failed attempts remain independently visible (same append-only-evidence
    principle as the close-report's own Overwrite policy). Any exception
    here (OSError from the filesystem, or e.g. UnicodeEncodeError from
    json.dump if a field contains a surrogate-escaped byte from invalid-
    UTF-8 argv -- codex adversarial finding) is caught by the caller --
    marker durability is best-effort and must never prevent the sentinel
    line (the primary fail-closed contract) from being printed, but the
    caller now surfaces that exception on stderr rather than swallowing
    it silently."""
    marker_dir = _marker_dir()
    marker_dir.mkdir(parents=True, exist_ok=True)
    base_ts = _now_compact()
    suffix = 0
    while True:
        name = f"close-report-{task_id}-append-error-{base_ts}.json" if suffix == 0 \
            else f"close-report-{task_id}-append-error-{base_ts}-{suffix}.json"
        marker_path = marker_dir / name
        payload = {
            "task_id": task_id,
            "report_path": str(report_path),
            "attempted_at": datetime.now(timezone.utc).isoformat(),
            "failure_stage": stage,
            "error_detail": detail,
            "prior_last_nonempty_line": prior_last_line,
            "expected_last_line": expected_last_line,
            "actual_last_line_after_readback": actual_last_line,
            # round-7 CRITICAL fix (M7), this revision: which of the three
            # failure classes this marker records. Pre-publish call sites
            # pass no override and get the default "pre_publish" -- their
            # payload shape is otherwise unchanged (AC6 concerns stdout
            # sentinel text/exit codes, not this JSON marker's schema).
            "failure_class": failure_class,
            "rollback_detail": rollback_detail,
        }
        try:
            with open(marker_path, "x", encoding="utf-8") as fp:
                json.dump(payload, fp, indent=2, ensure_ascii=False)
                fp.write("\n")
                fp.flush()
                os.fsync(fp.fileno())
            return marker_path
        except FileExistsError:
            suffix += 1
            continue
        except Exception:
            # A failure partway through serialization/write (e.g. the
            # UnicodeEncodeError codex's adversarial review reproduced,
            # from a surrogate-escaped byte in a field such as task_id)
            # can leave a partially-written or empty file at marker_path.
            # Clean it up before propagating to _safe_write_failure_marker,
            # so a later reader never finds a corrupt, misleading
            # half-written marker sitting next to genuine ones.
            try:
                marker_path.unlink()
            except OSError:
                pass
            raise


def _safe_write_failure_marker(report_path: Path, task_id: str, stage: str, detail: str,
                                prior_last_line: str, expected_last_line: str | None,
                                actual_last_line: str | None,
                                failure_class: str = "pre_publish",
                                rollback_detail: str | None = None) -> None:
    """Wrapper: marker durability is best-effort. If writing the marker
    itself raises -- disk full, permission denied, a directory-level
    failure (OSError), OR a non-OSError failure such as UnicodeEncodeError
    from serializing a pathological field (codex adversarial finding: an
    invalid-UTF-8 --task-id argument is decoded by Python with
    surrogateescape, and json.dump(..., ensure_ascii=False) then raises
    UnicodeEncodeError writing it to a UTF-8 file, NOT an OSError) -- it
    must never crash past the sentinel line this function's caller is
    about to print. Deliberately catches Exception (not bare OSError, and
    not BaseException, so KeyboardInterrupt/SystemExit still propagate):
    this is a narrowly-scoped, best-effort side operation, and ANY failure
    in it must degrade to the same outcome -- an explicit, labeled stderr
    warning naming the task-id, the ORIGINAL failure stage this marker was
    trying to record, the marker directory that could not be written, and
    the marker-write error itself -- never a crash that would also destroy
    the primary sentinel line. 'Best-effort' no longer means 'silent', but
    it is also not a persistent-evidence guarantee: if the caller does not
    capture/log this process's stderr, the warning itself leaves no
    separate on-disk trace.

    That stderr write is itself guarded (round-5-QA finding): if stderr
    cannot accept it either (e.g. a full/broken descriptor), the failure
    is swallowed here unconditionally -- there is no channel below stderr
    to report through -- and recorded on the _stderr_diagnostic_write_failed
    module flag instead, so main() can still make the compounded failure
    observable via a distinct exit code."""
    global _stderr_diagnostic_write_failed
    try:
        _write_failure_marker(report_path, task_id, stage, detail, prior_last_line,
                               expected_last_line, actual_last_line,
                               failure_class=failure_class, rollback_detail=rollback_detail)
    except Exception as marker_err:
        try:
            sys.stderr.write(
                f"close-report-append.py: WARNING: failed to write durable failure "
                f"marker for task_id={task_id!r} (original failure stage={stage!r}) "
                f"into {_marker_dir()}: {marker_err!r}\n"
            )
            # Explicit flush (round-6 codex finding): write() alone only
            # raises synchronously under line/unbuffered stderr. Under the
            # default block buffering a real non-tty stderr destination
            # normally has, write() of a short line just fills the internal
            # buffer and returns successfully -- the actual OSError (e.g.
            # ENOSPC) would only surface on a LATER flush/close, by which
            # point this except block has already moved on and the failure
            # would go undetected. Flushing here, inside this same guarded
            # block, makes detection independent of the caller's buffering
            # mode.
            sys.stderr.flush()
        except Exception:
            _stderr_diagnostic_write_failed = True


class _LockTimeout(Exception):
    pass


# Reasonable upper bound for either lock-timing override (ticket
# 20260908-015250, final bounded fix round): a value outside
# [0, _LOCK_TIMING_MAX_SECONDS] is rejected outright by
# _validate_lock_timing below rather than silently accepted.
_LOCK_TIMING_MAX_SECONDS = 3600.0


def _validate_lock_timing(timeout: float, poll_seconds: float) -> None:
    """Raise ValueError if either lock-timing value is not a finite,
    non-negative number within [0, _LOCK_TIMING_MAX_SECONDS]. Called
    unconditionally at the top of _acquire_lock -- not only when the
    retry loop happens to be entered -- so a malformed value (negative,
    NaN, or +inf, from either the CLI flag or its env-var fallback) is
    rejected deterministically before it can ever reach time.sleep()'s
    own strict validation. A negative argument there raises an
    uncaught, stage-less ValueError with completely empty stdout under
    genuine lock contention -- the exact defect this closes. NaN or
    +inf instead pass every numeric comparison silently (NaN comparisons
    are always False; `time.monotonic() >= float('inf')` is never True)
    and the retry loop would never terminate -- caught here for the same
    reason, before either can reach _acquire_lock's loop."""
    for flag, value in (("--lock-timeout-seconds", timeout), ("--lock-poll-seconds", poll_seconds)):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{flag} must be a number, got {value!r}")
        if math.isnan(value) or math.isinf(value):
            raise ValueError(f"{flag} must be a finite number, got {value!r}")
        if value < 0 or value > _LOCK_TIMING_MAX_SECONDS:
            raise ValueError(
                f"{flag} must be within [0, {_LOCK_TIMING_MAX_SECONDS}] seconds, got {value!r}"
            )


def _acquire_lock(report_path: Path, timeout: float | None = None):
    """Bounded-wait advisory exclusive lock on a sibling lock file, scoped
    to this report path. Serializes concurrent close-report-append.py
    invocations against the SAME report so two overlapping appends cannot
    both read the same prior bytes and silently discard one another's
    content on publish (codex round-4 finding #3). Returns an open file
    handle the caller must close (which releases the flock) when done.
    Raises _LockTimeout if the lock cannot be acquired within `timeout`.

    `timeout` defaults to the module-level `_LOCK_TIMEOUT_SECONDS`, read
    here at call time (not bound as a def-time default) so a CLI/env
    override applied by main() before run()/_acquire_lock is invoked still
    takes effect."""
    if timeout is None:
        timeout = _LOCK_TIMEOUT_SECONDS
    _validate_lock_timing(timeout, _LOCK_POLL_SECONDS)
    lock_path = report_path.parent / f".{report_path.name}.append-lock"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+")
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fh
        except OSError:
            if time.monotonic() >= deadline:
                fh.close()
                raise _LockTimeout(f"could not acquire exclusive lock on {lock_path} within {timeout}s")
            time.sleep(_LOCK_POLL_SECONDS)


# New sentinel prefix (round-7 CRITICAL fix, this revision): NEVER emitted
# for any pre-publish failure path (see AC6) -- strictly additive, reserved
# for the one compounded post-publish outcome where a rollback attempt
# could not itself be confirmed, or was correctly not attempted at all
# because the on-disk content looked like a concurrent writer's own data.
# Distinct from CLOSE_REPORT_APPEND_ERROR so a caller keying off that exact
# prefix (commands/close.md, commands/commit.md) cannot mistake this for
# the existing "safe to retry, nothing landed" sentinel.
_POST_PUBLISH_CRITICAL_PREFIX = "CLOSE_REPORT_APPEND_CRITICAL"


def _attempt_rollback_to_pre_bytes(report_path: Path, pre_bytes: bytes) -> tuple[bool, str | None]:
    """Best-effort restoration of report_path to pre_bytes after a
    post-publish failure (round-7 CRITICAL fix, M3). Uses the same
    same-directory-temp-file + os.replace() atomic mechanism as the
    original publish, then independently re-reads and byte-compares to
    CONFIRM the restoration actually landed -- a restore that merely
    appears to succeed is never trusted. Returns (verified, error_detail):
    verified=True means report_path is now confirmed byte-identical to
    pre_bytes; verified=False means either the restoring write failed or
    the restoration could not be confirmed, and error_detail names which."""
    try:
        if report_path.read_bytes() == pre_bytes:
            return True, None  # already matches -- nothing to restore
    except OSError:
        pass  # current bytes unreadable; fall through to an unconditional restore write

    restore_tmp = report_path.parent / f".{report_path.name}.rollback-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    try:
        with open(restore_tmp, "xb") as fp:
            fp.write(pre_bytes)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(restore_tmp, report_path)
    except OSError as e:
        try:
            restore_tmp.unlink()
        except OSError:
            pass
        return False, f"rollback-write: {e}"

    try:
        verify_bytes = report_path.read_bytes()
    except OSError as e:
        return False, f"rollback-readback: {e}"

    if verify_bytes != pre_bytes:
        return False, "rollback-verification: restored bytes do not match pre-existing content"

    return True, None


def _handle_post_publish_failure(report_path: Path, task_id: str, stage: str, detail: str,
                                  prior_last_line: str, expected_last_line: str | None,
                                  actual_last_line: str | None, pre_bytes: bytes,
                                  conflict_detected: bool) -> tuple[bool, str]:
    """Dispatch a failure detected AFTER os.replace() has already
    published the candidate (round-7 CRITICAL fix) to one of exactly two
    caller-distinguishable outcomes:

    - Recoverable (M4): rollback attempted and independently verified --
      reported through the EXISTING `CLOSE_REPORT_APPEND_ERROR` sentinel
      and exit-1 contract, since the report really is back to its
      pre-attempt bytes and that contract's meaning is now truthful.
    - Compounded (M5): rollback could not be attempted safely
      (`conflict_detected=True` -- M6, published bytes matched neither the
      candidate nor the pre-existing content, so a concurrent, non-
      cooperating writer's own bytes are on disk and restoring would
      silently discard them) or could not be verified -- reported through
      the brand-new `_POST_PUBLISH_CRITICAL_PREFIX` sentinel (exit code 4
      in main()) that can never be mistaken for the recoverable case or
      for success."""
    if conflict_detected:
        rollback_ok = False
        rollback_detail = (
            "skipped: published bytes match neither the candidate nor the "
            "pre-existing content (concurrent external modification detected); "
            "refusing to overwrite and discard the other writer's content"
        )
    else:
        rollback_ok, rollback_detail = _attempt_rollback_to_pre_bytes(report_path, pre_bytes)

    if rollback_ok:
        _safe_write_failure_marker(report_path, task_id, stage, detail, prior_last_line,
                                    expected_last_line, actual_last_line,
                                    failure_class="post_publish_recovered")
        return False, f"CLOSE_REPORT_APPEND_ERROR: {stage}: {detail}"

    _safe_write_failure_marker(report_path, task_id, stage, detail, prior_last_line,
                                expected_last_line, actual_last_line,
                                failure_class="post_publish_compounded",
                                rollback_detail=rollback_detail)
    return False, (f"{_POST_PUBLISH_CRITICAL_PREFIX}: {stage}: {detail} "
                    f"| rollback not confirmed: {rollback_detail}")


def run(report_path: Path, section_path: Path, task_id: str, repo_root: Path) -> tuple[bool, str]:
    """Returns (ok, stdout_line). On failure a best-effort marker has
    already been written and the live report is guaranteed unchanged."""
    global _stderr_diagnostic_write_failed
    _stderr_diagnostic_write_failed = False
    cv = _load_close_verdict_module(repo_root)

    # Stage: read (section file QA prepared) -- read this first since it
    # does not depend on the report's own state.
    try:
        section_text = section_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        detail = f"section-file: {e}"
        _safe_write_failure_marker(report_path, task_id, "read", detail, "", None, None)
        return False, f"CLOSE_REPORT_APPEND_ERROR: read: {detail}"

    expected_last_line = cv.last_nonempty(section_text)
    if not expected_last_line:
        detail = "section file has no non-empty content"
        _safe_write_failure_marker(report_path, task_id, "append", detail, "", None, None)
        return False, f"CLOSE_REPORT_APPEND_ERROR: append: {detail}"

    if cv.classify_line(expected_last_line) not in ("yes", "no"):
        detail = f"section's own last non-empty line is not a legal CLOSE: form: {expected_last_line!r}"
        _safe_write_failure_marker(report_path, task_id, "append", detail, "", expected_last_line, None)
        return False, f"CLOSE_REPORT_APPEND_ERROR: append: {detail}"

    normalized_section = section_text.rstrip("\n") + "\n"

    # Serialize concurrent invocations against this exact report path
    # before doing ANY report read/write below.
    try:
        lock_fh = _acquire_lock(report_path)
    except (_LockTimeout, OSError, ValueError) as e:
        # ValueError here is _validate_lock_timing rejecting an illegal
        # --lock-timeout-seconds/--lock-poll-seconds value (see that
        # function's docstring) -- routed through the exact same
        # "append"-stage sentinel + best-effort marker as every other
        # lock-related failure, never left to propagate uncaught.
        detail = str(e)
        _safe_write_failure_marker(report_path, task_id, "append", detail, "", expected_last_line, None)
        return False, f"CLOSE_REPORT_APPEND_ERROR: append: {detail}"

    try:
        # Stage: read (existing report, if any) -- re-read under the lock;
        # a concurrent writer may have committed between an earlier,
        # unlocked read and lock acquisition.
        try:
            pre_bytes = report_path.read_bytes() if report_path.exists() else b""
        except OSError as e:
            detail = f"report-path: {e}"
            _safe_write_failure_marker(report_path, task_id, "read", detail, "", expected_last_line, None)
            return False, f"CLOSE_REPORT_APPEND_ERROR: read: {detail}"

        prior_last_line = cv.last_nonempty(pre_bytes.decode("utf-8", errors="replace"))
        sep = b"" if not pre_bytes else b"\n\n"
        candidate_bytes = pre_bytes + sep + normalized_section.encode("utf-8")

        # Stage: append -- build the full candidate in a same-directory
        # temp file and fsync it. The live report is not touched yet, so
        # any failure here leaves it byte-for-byte untouched by
        # construction (fixes codex round-4 finding #1).
        tmp_path = report_path.parent / f".{report_path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        try:
            with open(tmp_path, "xb") as fp:
                fp.write(candidate_bytes)
                fp.flush()
                os.fsync(fp.fileno())
        except OSError as e:
            detail = str(e)
            try:
                tmp_path.unlink()
            except OSError:
                pass
            _safe_write_failure_marker(report_path, task_id, "append", detail, prior_last_line, expected_last_line, None)
            return False, f"CLOSE_REPORT_APPEND_ERROR: append: {detail}"

        # Stage: readback + verification of the STAGED temp file, before
        # it is ever published over the live report.
        try:
            staged_bytes = tmp_path.read_bytes()
        except OSError as e:
            detail = f"staged-file: {e}"
            try:
                tmp_path.unlink()
            except OSError:
                pass
            _safe_write_failure_marker(report_path, task_id, "readback", detail, prior_last_line, expected_last_line, None)
            return False, f"CLOSE_REPORT_APPEND_ERROR: readback: {detail}"

        if staged_bytes != candidate_bytes:
            detail = "staged candidate bytes do not match on readback (pre-publish)"
            try:
                tmp_path.unlink()
            except OSError:
                pass
            _safe_write_failure_marker(report_path, task_id, "verification", detail, prior_last_line, expected_last_line, None)
            return False, f"CLOSE_REPORT_APPEND_ERROR: verification: {detail}"

        # Publish: atomic rename onto the live report. On any POSIX
        # same-filesystem rename this either fully lands or fully fails --
        # never a partial write to report_path.
        try:
            os.replace(tmp_path, report_path)
            try:
                dir_fd = os.open(str(report_path.parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass  # directory fsync is best-effort; not all platforms support it
        except OSError as e:
            detail = str(e)
            try:
                tmp_path.unlink()
            except OSError:
                pass
            _safe_write_failure_marker(report_path, task_id, "append", detail, prior_last_line, expected_last_line, None)
            return False, f"CLOSE_REPORT_APPEND_ERROR: append: {detail}"

        # Stage: readback + verification of the PUBLISHED report.
        try:
            post_bytes = report_path.read_bytes()
        except OSError as e:
            detail = str(e)
            # Cannot tell whether a concurrent writer touched report_path
            # (the read itself failed) -- attempt the blind restore per M3;
            # AC2 covers exactly this branch.
            return _handle_post_publish_failure(
                report_path, task_id, "readback", detail, prior_last_line,
                expected_last_line, None, pre_bytes, conflict_detected=False,
            )

        if post_bytes != candidate_bytes:
            detail = "published report bytes do not match the verified candidate"
            actual_last_line = cv.last_nonempty(post_bytes.decode("utf-8", errors="replace"))
            # M6: bytes matching neither the candidate NOR the pre-existing
            # content means a non-cooperating concurrent writer's own data
            # is on disk -- restoring would silently discard it, so treat
            # that as a conflict and skip the rollback attempt entirely
            # (AC4). Bytes matching pre_bytes exactly are not a conflict --
            # _attempt_rollback_to_pre_bytes short-circuits as already
            # restored (AC3's generic-mismatch case).
            conflict_detected = post_bytes != pre_bytes
            return _handle_post_publish_failure(
                report_path, task_id, "verification", detail, prior_last_line,
                expected_last_line, actual_last_line, pre_bytes,
                conflict_detected=conflict_detected,
            )

        actual_last_line = cv.last_nonempty(post_bytes.decode("utf-8", errors="replace"))
        if actual_last_line != expected_last_line:
            detail = f"published last non-empty line {actual_last_line!r} != expected {expected_last_line!r}"
            # post_bytes == candidate_bytes here (the branch above already
            # excluded a byte mismatch), so this is never a third-party
            # conflict -- just this function's own last-line classification
            # disagreeing with itself. Still routed through the same
            # recover-or-compound handling for consistency.
            return _handle_post_publish_failure(
                report_path, task_id, "verification", detail, prior_last_line,
                expected_last_line, actual_last_line, pre_bytes,
                conflict_detected=False,
            )

        result = {"status": "ok", "report_path": str(report_path), "verdict_line": expected_last_line}
        return True, json.dumps(result, ensure_ascii=False)
    finally:
        lock_fh.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="close-report-append.py",
        description="Deterministic read-append-reread-verify for close-report append (M3-d1 / S2).",
    )
    parser.add_argument("--report-path", required=True, help="docs/dev/close-report-<task-id>.md")
    parser.add_argument("--section-file", required=True, help="file containing the new dated section text")
    parser.add_argument("--task-id", required=True, help="used to name the durable failure marker")
    parser.add_argument("--repo-root", default=None, help="repo-root override")
    parser.add_argument("--lock-timeout-seconds", type=float, default=None,
                         help="override _LOCK_TIMEOUT_SECONDS (default 10.0; "
                              "env CLOSE_REPORT_APPEND_LOCK_TIMEOUT_SECONDS; "
                              "must be within [0, 3600])")
    parser.add_argument("--lock-poll-seconds", type=float, default=None,
                         help="override _LOCK_POLL_SECONDS (default 0.05; "
                              "env CLOSE_REPORT_APPEND_LOCK_POLL_SECONDS; "
                              "must be within [0, 3600])")
    parser.add_argument("--marker-dir", default=None,
                         help="override the failure-marker directory (default "
                              "/tmp/claude-close-report-markers; env "
                              "CLOSE_REPORT_APPEND_MARKER_DIR)")

    try:
        args = parser.parse_args(argv[1:])
    except SystemExit:
        raise

    # CLI flag wins over environment variable, which wins over the
    # hardcoded module-level default. Malformed environment values are
    # ignored (default used) rather than treated as a fatal error.
    global _LOCK_TIMEOUT_SECONDS, _LOCK_POLL_SECONDS, _DEFAULT_MARKER_DIR
    if args.lock_timeout_seconds is not None:
        _LOCK_TIMEOUT_SECONDS = args.lock_timeout_seconds
    elif os.environ.get(_ENV_LOCK_TIMEOUT_SECONDS):
        try:
            _LOCK_TIMEOUT_SECONDS = float(os.environ[_ENV_LOCK_TIMEOUT_SECONDS])
        except ValueError:
            pass
    if args.lock_poll_seconds is not None:
        _LOCK_POLL_SECONDS = args.lock_poll_seconds
    elif os.environ.get(_ENV_LOCK_POLL_SECONDS):
        try:
            _LOCK_POLL_SECONDS = float(os.environ[_ENV_LOCK_POLL_SECONDS])
        except ValueError:
            pass
    if args.marker_dir:
        _DEFAULT_MARKER_DIR = Path(args.marker_dir)
    elif os.environ.get(_ENV_MARKER_DIR):
        _DEFAULT_MARKER_DIR = Path(os.environ[_ENV_MARKER_DIR])

    report_path = Path(args.report_path)
    section_path = Path(args.section_file)
    repo_root = _resolve_repo_root(args.repo_root)

    if not section_path.is_file():
        sys.stderr.write(f"close-report-append.py: --section-file not found: {section_path}\n")
        return 2

    try:
        ok, line = run(report_path, section_path, args.task_id, repo_root)
    except FileNotFoundError as e:
        sys.stderr.write(f"close-report-append.py: {e}\n")
        return 2

    sys.stdout.write(line + "\n")
    if not ok and _stderr_diagnostic_write_failed:
        # A broken stderr can also poison Python's own interpreter-shutdown
        # stdio flush, silently overriding a plain `return 3` here (round-6
        # codex adversarial finding, independently reproduced with a real
        # /dev/full on fd 2: the OS-observed exit code was 120, not 3,
        # because CPython's shutdown sequence retries flushing the
        # still-broken sys.stderr and that retry's failure takes over the
        # process's exit status). os._exit() bypasses all Python-level
        # finalization (no atexit handlers, no stdio reflush), so the exit
        # code chosen here is the one actually observed by a caller or
        # monitor. Flush stdout explicitly first since os._exit() skips the
        # normal buffered-stream flush that would otherwise land the
        # sentinel line just written above.
        sys.stdout.flush()
        os._exit(3)
    if not ok and line.startswith(f"{_POST_PUBLISH_CRITICAL_PREFIX}:"):
        # round-7 CRITICAL fix, this revision: a post-publish failure whose
        # own rollback could not be confirmed, or a detected concurrent-
        # writer conflict where rollback was deliberately skipped (M5/M6).
        # Distinct exit code so a caller keying off exit status alone (not
        # only stdout text) also cannot conflate this with the unchanged
        # exit-1 "nothing landed" contract (AC6). Checked after the exit-3
        # branch above -- a broken stderr descriptor is the more severe
        # signal and still wins if both somehow coincide.
        return 4
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
