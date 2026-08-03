#!/usr/bin/env python3
"""Capture harness for the README hero: run the five-beat guard demo and record it.

Description: Builds a hermetic fixture, installs one narrowly-scoped single-use grant,
  runs examples/guard-demo/run-hero-demo.sh, and captures the REAL hooks' own streams
  into a timestamped byte-exact capture. Performs every safety and correlation assertion.

Usage: capture-hero-run.py [--capture <path>] [--evidence <path>] [--check-only]

Exit codes: 0 = capture written and every assertion held
            1 = precondition failure (nothing was installed, nothing ran)
            2 = an assertion failed after the run

CAPTURE MODE (binding constraint, ticket dev-20260719-193823-f):
  The demo is captured through a PIPE, never a pseudo-terminal. Rationale: under a PTY
  git's transfer plumbing emits a wall-clock-derived throughput field ("N KiB | M MiB/s")
  which is non-deterministic per run and which the normalizer's deliberately narrow
  closed substitution set (absolute paths, timestamps, PIDs, temp-dir names) cannot
  cover -- widening it to cover throughput would push the normalizer into rewriting
  arbitrary hook output, which is exactly what must never happen. Under a pipe git
  suppresses progress entirely and emits no ANSI, so the byte-diff of AC13 is exact.

  CONSEQUENCE, resolved rather than left vacuous: because the capture carries zero ANSI
  and zero color, the "choose an accessible terminal theme before capture" clause has no
  captured colour to govern. Its intent is preserved and in fact strengthened -- there is
  no captured colour to semantically recolour, so the "post-capture semantic recolouring
  is FORBIDDEN" rule holds by construction. All rendered colour originates in
  tools/demo/gen-svg.mjs's paper substrate, which is README-authored presentation and is
  therefore governed by the README-authored APCA Lc >= 60 requirement, not by the
  captured-asset exception.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The fixed, reserved, demo-specific task id (M4). Fixed rather than random so it never
# has to be normalized away, which would weaken the byte-diff linkage.
RESERVED_TASK_ID = "readme-hero-demo-reserved"
SENTINEL_GRANT_DIR = Path("/tmp/claude-grants")
GRANT_PATH = SENTINEL_GRANT_DIR / f"{RESERVED_TASK_ID}.json"

DEFAULT_CAPTURE = REPO_ROOT / ".github/assets/hero-capture.txt"
DEFAULT_EVIDENCE = REPO_ROOT / ".github/assets/hero-capture-evidence.json"

CONSUMPTION_MARKER = f"[ALLOW-SENTINEL] grant CONSUMED for task_id={RESERVED_TASK_ID}"

WATCH_INTERVAL_S = 0.05


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def inventory_foreign_grants() -> dict:
    """Content hash + mtime of every grant that is NOT ours.

    Proves not-mutated and not-consumed. It cannot prove not-read -- a read leaves no
    trace on either field -- so that claim is not made here; non-disclosure of foreign
    state is verified separately against the committed artifacts.
    """
    inv = {}
    if not SENTINEL_GRANT_DIR.is_dir():
        return inv
    for p in sorted(SENTINEL_GRANT_DIR.iterdir()):
        if not p.is_file():
            continue
        if p.name == GRANT_PATH.name or p.name.startswith(f"{RESERVED_TASK_ID}-"):
            continue
        st = p.stat()
        inv[p.name] = {"sha256": sha256_file(p), "mtime_ns": st.st_mtime_ns}
    return inv


def reserved_grant_files() -> list[Path]:
    """Only the two reserved-token paths. No directory glob, ever."""
    out = []
    if GRANT_PATH.exists():
        out.append(GRANT_PATH)
    if SENTINEL_GRANT_DIR.is_dir():
        for p in sorted(SENTINEL_GRANT_DIR.glob(f"{RESERVED_TASK_ID}-*")):
            if p.is_file():
                out.append(p)
    return out


def preflight() -> None:
    """Abort BEFORE anything is installed if the reserved token could collide."""
    for var in ("CLAUDE_TASK_ID", "CLAUDE_SESSION_ID"):
        if os.environ.get(var, "") == RESERVED_TASK_ID:
            sys.exit(
                f"capture-hero-run: PRECONDITION FAILED -- ${var} equals the reserved "
                f"token {RESERVED_TASK_ID!r}. Refusing to run rather than risk touching "
                f"a live session's grant."
            )
    existing = reserved_grant_files()
    if existing:
        sys.exit(
            "capture-hero-run: PRECONDITION FAILED -- a grant matching the reserved "
            f"task id already exists: {[str(p) for p in existing]}. Refusing to run."
        )


def build_fixture(fixture: Path) -> None:
    """Hermetic fixture: a local BARE remote addressed by a RELATIVE path.

    The relative URL (../hero-remote.git) is what keeps the capture deterministic -- an
    absolute mktemp path would differ every run and would have to be normalized away.
    """
    work = fixture / "work"
    bare = fixture / "hero-remote.git"
    (fixture / "home").mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ALLOW_PROTOCOL": "file",
            "HOME": str(fixture / "home"),
        }
    )

    def run(args, cwd):
        subprocess.run(args, cwd=cwd, env=env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    run(["git", "init", "--bare", "--initial-branch=main", str(bare)], fixture)
    run(["git", "init", "--initial-branch=main"], work)
    run(["git", "config", "user.email", "hero-demo@example.invalid"], work)
    run(["git", "config", "user.name", "hero demo"], work)
    (work / "README.md").write_text("hero demo fixture\n", encoding="utf-8")
    run(["git", "add", "README.md"], work)
    run(["git", "commit", "-m", "hero demo fixture"], work)
    # RELATIVE remote URL: keeps the captured `To ../hero-remote.git` line deterministic.
    run(["git", "remote", "add", "hero-remote", "../hero-remote.git"], work)


def install_grant() -> None:
    """One grant, one operation. args_contain is prefix-matched by allowlist.py."""
    SENTINEL_GRANT_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    grant = {
        "task_id": RESERVED_TASK_ID,
        "session_id": RESERVED_TASK_ID,
        "allowed_operations": [
            {"op": "git", "target": "push", "args_contain": ["push hero-remote main"]}
        ],
        "created_at": now,
        "expires_at": now + 300,
    }
    GRANT_PATH.write_text(json.dumps(grant, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")


class GrantWatcher(threading.Thread):
    """Samples the demo's OWN grant path only. A thread, not a child process -- there is
    no PID to orphan, so the shell trap contract's failure mode is structurally absent;
    the equivalent guarantee is the finally: block that installs cleanup before any grant
    is installed."""

    def __init__(self, t0: float):
        super().__init__(daemon=True)
        self.t0 = t0
        self.samples: list[dict] = []
        # NB: named _halt, not _stop -- threading.Thread._stop is an inherited method.
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.is_set():
            try:
                present = GRANT_PATH.is_file()
                digest = sha256_file(GRANT_PATH) if present else None
            except (OSError, FileNotFoundError):
                present, digest = False, None
            self.samples.append(
                {"t": round(time.monotonic() - self.t0, 4),
                 "present": present, "sha256": digest}
            )
            self._halt.wait(WATCH_INTERVAL_S)

    def halt(self) -> None:
        self._halt.set()


def capture_run(fixture: Path, capture_path: Path, watcher: GrantWatcher,
                t0: float) -> tuple[int, list[str]]:
    """Run the demo through a PIPE and timestamp every line as it arrives."""
    runner = REPO_ROOT / "examples/guard-demo/run-hero-demo.sh"
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ALLOW_PROTOCOL": "file",
        }
    )
    proc = subprocess.Popen(
        ["bash", str(runner), str(fixture), str(GRANT_PATH), RESERVED_TASK_ID],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,   # merged; PIPE, never a PTY (see module docstring)
        env=env,
        cwd=str(fixture / "work"),
        text=True,
        bufsize=1,
    )
    lines: list[str] = []
    assert proc.stdout is not None
    for raw in proc.stdout:
        text = raw.rstrip("\n")
        if text == "":
            continue
        lines.append(f"[{time.monotonic() - t0:8.3f}] {text}")
    rc = proc.wait()
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    capture_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rc, lines


def parse_ts(line: str) -> float:
    return float(line[1:line.index("]")])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture", default=str(DEFAULT_CAPTURE))
    ap.add_argument("--evidence", default=str(DEFAULT_EVIDENCE))
    ap.add_argument("--check-only", action="store_true",
                    help="run and assert, but write the capture to a scratch path")
    args = ap.parse_args()

    preflight()
    before = inventory_foreign_grants()

    capture_path = Path(args.capture)
    if args.check_only:
        capture_path = Path(tempfile.mkstemp(suffix=".txt", prefix="hero-fresh-")[1])

    fixture = Path(tempfile.mkdtemp(prefix="claude-hero-fixture-"))
    failures: list[str] = []
    watcher = GrantWatcher(0.0)

    # Cleanup is installed BEFORE any grant is installed, and it removes ONLY the two
    # reserved-token paths -- no directory glob, no pkill, no reap_expired_sentinel_grants,
    # no hooks/stop-cleanup-allowlist.sh. On the success path it removes ZERO files, which
    # is itself independent proof that the real consumer performed the removal.
    swept: list[str] = []
    try:
        build_fixture(fixture)
        install_grant()
        grant_hash_at_install = sha256_file(GRANT_PATH)

        t0 = time.monotonic()
        watcher.t0 = t0
        watcher.start()
        rc, lines = capture_run(fixture, capture_path, watcher, t0)
        watcher.stop()
        watcher.join(timeout=2.0)

        # ---- assertions (all evaluated; never short-circuited) ----------------------
        if rc != 0:
            failures.append(f"demo exited {rc}, expected 0")

        blob = "\n".join(lines)
        if CONSUMPTION_MARKER not in blob:
            failures.append("consumption marker absent from capture")

        # Causal correlation: present immediately BEFORE consumption, absent immediately
        # AFTER. Established from verifier-owned samples, never from demo self-report.
        marker_line = next((l for l in lines if CONSUMPTION_MARKER in l), None)
        if marker_line is None:
            failures.append("cannot correlate: no marker line")
        else:
            t_marker = parse_ts(marker_line)
            pre = [s for s in watcher.samples if s["t"] < t_marker]
            post = [s for s in watcher.samples if s["t"] > t_marker]
            if not pre or not pre[-1]["present"]:
                failures.append("grant was NOT present immediately before consumption")
            elif pre[-1]["sha256"] != grant_hash_at_install:
                failures.append("grant content changed before consumption")
            if not post or any(s["present"] for s in post):
                failures.append("grant was NOT absent immediately after consumption")

        # Duration measured from the raw capture (never from the SVG's dur attribute).
        duration = parse_ts(lines[-1]) - parse_ts(lines[0]) if len(lines) >= 2 else 0.0
        if not (10.0 <= duration <= 15.0):
            failures.append(f"raw duration {duration:.3f}s outside [10,15]")

        # No grant belonging to the demo outlives the run.
        if GRANT_PATH.exists():
            failures.append("demo grant outlived the run (real consumer did not remove it)")

        # Foreign grants byte-identical and mtime-unchanged.
        after = inventory_foreign_grants()
        if after != before:
            failures.append(f"foreign grant state changed: {before} -> {after}")

        # M4b non-disclosure: no foreign task_id, no foreign grant path in the capture.
        for ln in lines:
            if "/tmp/claude-grants/" in ln and RESERVED_TASK_ID not in ln:
                failures.append(f"capture discloses a foreign grant path: {ln!r}")

        evidence = {
            "task_id": RESERVED_TASK_ID,
            "capture_path": str(capture_path.relative_to(REPO_ROOT))
            if not args.check_only else str(capture_path),
            "capture_mode": "pipe (never a pseudo-terminal) -- see module docstring",
            "demo_exit": rc,
            "raw_duration_s": round(duration, 3),
            "line_count": len(lines),
            "inter_arrival_deltas": [
                round(parse_ts(lines[i + 1]) - parse_ts(lines[i]), 3)
                for i in range(len(lines) - 1)
            ],
            "grant_sha256_at_install": grant_hash_at_install,
            "grant_present_before_consumption": bool(
                marker_line and pre and pre[-1]["present"]
            ),
            "grant_absent_after_consumption": bool(
                marker_line and post and not any(s["present"] for s in post)
            ),
            "foreign_grants_unchanged": after == before,
            "foreign_grant_count": len(before),
            "cleanup_removed_files": swept,
            "failures": failures,
        }
        Path(args.evidence).parent.mkdir(parents=True, exist_ok=True)
        Path(args.evidence).write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    finally:
        # Poisoned-state recovery. Ordering is load-bearing: this runs only AFTER the
        # present-before / absent-after observations above have been recorded, so it can
        # never manufacture the absence it is supposed to be observing.
        for p in reserved_grant_files():
            try:
                p.unlink()
                swept.append(str(p))
            except OSError:
                pass
        shutil.rmtree(fixture, ignore_errors=True)

    if swept:
        failures.append(f"cleanup removed {swept} -- on a clean run it must remove none")

    for f in failures:
        print(f"capture-hero-run: FAIL: {f}", file=sys.stderr)
    if failures:
        return 2
    print(f"capture-hero-run: OK  duration={duration:.3f}s lines={len(lines)} "
          f"capture={capture_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
