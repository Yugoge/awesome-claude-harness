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
#   --task-id       The close task-id commands/close.md passes. Still
#                    required (the CLI contract is unchanged), but the
#                    append itself does not use it.
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
#     the existing sentinel text or exit codes 0/1/2 (see AC6).
#
# On success: stdout is one line of JSON {"status":"ok","report_path":...,
# "verdict_line":...}; exit 0.
#
# On failure at any stage: stdout is exactly
#   CLOSE_REPORT_APPEND_ERROR: <read|append|readback|verification>: <error detail>
# (the pre-existing sanctioned sentinel form QA already returns verbatim as
# its own Return-value line) and exit 1.
#
# Exit codes: 0 = appended and verified; 1 = failed (sentinel printed);
# 2 = bad invocation (missing/invalid arguments);
# 4 = a POST-publish failure whose own rollback attempt could not itself
# be confirmed, OR a detected concurrent-writer conflict where rollback
# was deliberately not attempted (round-7 CRITICAL fix, this revision --
# see "Post-publish failure semantics" above).
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
from importlib.machinery import SourceFileLoader
from pathlib import Path

_LOCK_TIMEOUT_SECONDS = 10.0
_LOCK_POLL_SECONDS = 0.05

# Environment-variable override names (main()'s CLI flags take precedence
# over these when both are given; see module docstring's Inputs section).
_ENV_LOCK_TIMEOUT_SECONDS = "CLOSE_REPORT_APPEND_LOCK_TIMEOUT_SECONDS"
_ENV_LOCK_POLL_SECONDS = "CLOSE_REPORT_APPEND_LOCK_POLL_SECONDS"


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


def _handle_post_publish_failure(report_path: Path, stage: str, detail: str, pre_bytes: bytes,
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
        return False, f"CLOSE_REPORT_APPEND_ERROR: {stage}: {detail}"

    return False, (f"{_POST_PUBLISH_CRITICAL_PREFIX}: {stage}: {detail} "
                    f"| rollback not confirmed: {rollback_detail}")


def run(report_path: Path, section_path: Path, repo_root: Path) -> tuple[bool, str]:
    """Returns (ok, stdout_line). On failure the live report is guaranteed
    unchanged."""
    cv = _load_close_verdict_module(repo_root)

    # Stage: read (section file QA prepared) -- read this first since it
    # does not depend on the report's own state.
    try:
        section_text = section_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        detail = f"section-file: {e}"
        return False, f"CLOSE_REPORT_APPEND_ERROR: read: {detail}"

    expected_last_line = cv.last_nonempty(section_text)
    if not expected_last_line:
        detail = "section file has no non-empty content"
        return False, f"CLOSE_REPORT_APPEND_ERROR: append: {detail}"

    if cv.classify_line(expected_last_line) not in ("yes", "no"):
        detail = f"section's own last non-empty line is not a legal CLOSE: form: {expected_last_line!r}"
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
        # "append"-stage sentinel as every other lock-related failure,
        # never left to propagate uncaught.
        detail = str(e)
        return False, f"CLOSE_REPORT_APPEND_ERROR: append: {detail}"

    try:
        # Stage: read (existing report, if any) -- re-read under the lock;
        # a concurrent writer may have committed between an earlier,
        # unlocked read and lock acquisition.
        try:
            pre_bytes = report_path.read_bytes() if report_path.exists() else b""
        except OSError as e:
            detail = f"report-path: {e}"
            return False, f"CLOSE_REPORT_APPEND_ERROR: read: {detail}"

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
            return False, f"CLOSE_REPORT_APPEND_ERROR: readback: {detail}"

        if staged_bytes != candidate_bytes:
            detail = "staged candidate bytes do not match on readback (pre-publish)"
            try:
                tmp_path.unlink()
            except OSError:
                pass
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
                report_path, "readback", detail, pre_bytes, conflict_detected=False,
            )

        if post_bytes != candidate_bytes:
            detail = "published report bytes do not match the verified candidate"
            # M6: bytes matching neither the candidate NOR the pre-existing
            # content means a non-cooperating concurrent writer's own data
            # is on disk -- restoring would silently discard it, so treat
            # that as a conflict and skip the rollback attempt entirely
            # (AC4). Bytes matching pre_bytes exactly are not a conflict --
            # _attempt_rollback_to_pre_bytes short-circuits as already
            # restored (AC3's generic-mismatch case).
            conflict_detected = post_bytes != pre_bytes
            return _handle_post_publish_failure(
                report_path, "verification", detail, pre_bytes,
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
                report_path, "verification", detail, pre_bytes,
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
    parser.add_argument("--task-id", required=True,
                         help="the close task-id commands/close.md passes (not used by the append)")
    parser.add_argument("--repo-root", default=None, help="repo-root override")
    parser.add_argument("--lock-timeout-seconds", type=float, default=None,
                         help="override _LOCK_TIMEOUT_SECONDS (default 10.0; "
                              "env CLOSE_REPORT_APPEND_LOCK_TIMEOUT_SECONDS; "
                              "must be within [0, 3600])")
    parser.add_argument("--lock-poll-seconds", type=float, default=None,
                         help="override _LOCK_POLL_SECONDS (default 0.05; "
                              "env CLOSE_REPORT_APPEND_LOCK_POLL_SECONDS; "
                              "must be within [0, 3600])")

    try:
        args = parser.parse_args(argv[1:])
    except SystemExit:
        raise

    # CLI flag wins over environment variable, which wins over the
    # hardcoded module-level default. Malformed environment values are
    # ignored (default used) rather than treated as a fatal error.
    global _LOCK_TIMEOUT_SECONDS, _LOCK_POLL_SECONDS
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

    report_path = Path(args.report_path)
    section_path = Path(args.section_file)
    repo_root = _resolve_repo_root(args.repo_root)

    if not section_path.is_file():
        sys.stderr.write(f"close-report-append.py: --section-file not found: {section_path}\n")
        return 2

    try:
        ok, line = run(report_path, section_path, repo_root)
    except FileNotFoundError as e:
        sys.stderr.write(f"close-report-append.py: {e}\n")
        return 2

    sys.stdout.write(line + "\n")
    if not ok and line.startswith(f"{_POST_PUBLISH_CRITICAL_PREFIX}:"):
        # round-7 CRITICAL fix, this revision: a post-publish failure whose
        # own rollback could not be confirmed, or a detected concurrent-
        # writer conflict where rollback was deliberately skipped (M5/M6).
        # Distinct exit code so a caller keying off exit status alone (not
        # only stdout text) also cannot conflate this with the unchanged
        # exit-1 "nothing landed" contract (AC6).
        return 4
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
