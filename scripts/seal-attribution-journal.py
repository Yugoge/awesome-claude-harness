#!/usr/bin/env python3
"""Seal the attribution journal onto reboot-surviving storage (Phase 0).

The repo tree (journals under state/attribution-journal/ AND the git object
database holding the content blobs) lives on tmpfs (/dev/shm) and dies on
reboot. This copies:
  * every session journal  -> <dest>/journals/<session>.jsonl   (atomic replace)
  * every blob referenced by any event's pre_sha/post_sha
                           -> <dest>/objects.git  (bare repo, same blob ids)
Default dest: $CLAUDE_CONFIG_DIR/attribution-seals (the account's persistent
harness-state dir, /var/lib/claude-accounts/<acct>/claude on the root ext4
disk) -- override with $ATTRIBUTION_SEAL_DEST or --dest. Refuses a RAM-backed
destination unless --allow-volatile. See
docs/reference/attribution-journal-phase0-facility.md #1 for the measured
persistence tier of each resolution path.

Idempotent; safe to re-run (journals are append-only, blobs content-addressed).
Recover a byte-state: git --git-dir <dest>/objects.git cat-file blob <sha>.

Automatic periodic sealing (no cron/heartbeat; see
hooks/lib/attribution_journal.py:autoseal_hook_trigger, the sole production
caller): autoseal_if_due() seals only when more than `interval` seconds have
passed since the last recorded attempt (success OR error) in
<dest>/seal-log.jsonl, so the destination carries its own verifiable,
append-only evidence trail of every automatic (and, via `main`, manual) seal
attempt -- `--show-last` prints the most recent entry.

Usage: seal-attribution-journal.py [--dest DIR] [--allow-volatile] [--json]
                                    [--autoseal [--interval SECONDS]] [--show-last]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
from lib import attribution_journal as aj  # noqa: E402

RAM_FS = {"tmpfs", "ramfs", "devtmpfs"}
DEFAULT_AUTOSEAL_INTERVAL_SECONDS = 600


def mount_class(path: Path) -> dict:
    """fstype / source / persistence class of the mount holding `path`."""
    best = ("", "", "", "")
    real = os.path.realpath(path)
    for line in Path("/proc/mounts").read_text().splitlines():
        src, mnt, fst, opts = line.split()[:4]
        mnt = mnt.replace("\\040", " ")
        if (real == mnt or real.startswith(mnt.rstrip("/") + "/")) and len(mnt) >= len(best[1]):
            best = (src, mnt, fst, opts)
    src, mnt, fst, _ = best
    return {"source": src, "mount": mnt, "fstype": fst,
            "persistent": fst not in RAM_FS, "class": "volatile-ram" if fst in RAM_FS else "disk-backed"}


def default_dest() -> Path:
    env = os.environ.get("ATTRIBUTION_SEAL_DEST")
    if env:
        return Path(env)
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    if not base:
        base = os.path.realpath(str(Path.home() / ".claude"))
    return Path(base) / "attribution-seals"


def _git(gd, *args, inp=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", "--git-dir", str(gd), *args], input=inp, capture_output=True,
                          timeout=30, env=env)


def seal(dest: Path, allow_volatile=False) -> dict:
    mc = mount_class(dest)
    if not mc["persistent"] and not allow_volatile:
        raise SystemExit(f"refusing: {dest} is on {mc['fstype']} (volatile)")
    dest.mkdir(parents=True, exist_ok=True)
    jdest = dest / "journals"
    jdest.mkdir(exist_ok=True)
    odb = dest / "objects.git"
    if not (odb / "HEAD").exists():
        subprocess.run(["git", "init", "--bare", "-q", str(odb)], check=True, timeout=30)
    events, bad = aj.read_all_journals()
    shas = {s for ev in events for s in (ev["pre_sha"], ev["post_sha"])
            if len(s) == 40 and all(c in "0123456789abcdef" for c in s)}
    copied = 0
    for jp in sorted(aj.journal_dir().glob("*.jsonl")):
        tgt = jdest / jp.name
        if tgt.exists() and tgt.stat().st_size == jp.stat().st_size:
            continue
        tmp = tgt.with_suffix(".tmp")
        shutil.copyfile(jp, tmp)
        fd = os.open(tmp, os.O_RDONLY)
        os.fsync(fd)
        os.close(fd)
        os.replace(tmp, tgt)
        copied += 1
    new_blobs, missing = 0, []
    src = aj.git_dir()
    for sha in sorted(shas):
        if _git(odb, "cat-file", "-e", sha).returncode == 0:
            continue
        r = _git(src, "cat-file", "blob", sha)
        if r.returncode != 0:
            missing.append(sha)
            continue
        w = _git(odb, "hash-object", "-w", "--stdin", "--no-filters", inp=r.stdout)
        if w.returncode == 0 and w.stdout.decode().strip() == sha:
            new_blobs += 1
        else:
            missing.append(sha)
    # make the seal itself durable
    subprocess.run(["sync", "-f", str(dest)], timeout=60)
    return {"dest": str(dest), "mount": mc, "events": len(events), "journals_copied": copied,
            "blobs_referenced": len(shas), "blobs_added": new_blobs, "blobs_missing_in_source": missing,
            "discarded_lines": len(bad)}


# --------------------------------------------------------- evidence + autoseal

def evidence_log_path(dest: Path) -> Path:
    return dest / "seal-log.jsonl"


def _append_evidence(dest: Path, entry: dict) -> None:
    """One O_APPEND write() per entry -- atomic for one short line, lock-free,
    same pattern as attribution_journal.append_events."""
    dest.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    fd = os.open(evidence_log_path(dest), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def read_last_evidence(dest: Path) -> Optional[dict]:
    """Last well-formed entry in <dest>/seal-log.jsonl, tail-read (torn-tail safe,
    mirrors attribution_journal's journal tail reader), or None if absent/empty."""
    p = evidence_log_path(dest)
    try:
        size = p.stat().st_size
    except OSError:
        return None
    if size == 0:
        return None
    with open(p, "rb") as fh:
        fh.seek(max(0, size - 8192))
        tail = fh.read()
    for line in reversed(tail.split(b"\n")):
        if not line.strip():
            continue
        try:
            return json.loads(line)
        except Exception:
            continue
    return None


def autoseal_if_due(dest: Optional[Path] = None, interval: Optional[float] = None,
                     allow_volatile: bool = False, trigger: str = "auto") -> Optional[dict]:
    """Seal iff >= `interval` seconds have passed since the last recorded
    attempt (success OR error) at `dest`, per its own seal-log.jsonl -- so a
    persistently failing destination keeps retrying every interval rather than
    going silent forever. Returns the appended evidence entry (status "ok" with
    the seal() result, or "error" with the failure) when a seal was attempted,
    or None when skipped because it was not yet due. Idempotent by construction
    (seal() is content-addressed; two due calls in a row just re-seal
    harmlessly) and never raises -- a failure, including a volatile-destination
    refusal, is itself recorded as an error evidence entry."""
    dest = dest if dest is not None else default_dest()
    interval = DEFAULT_AUTOSEAL_INTERVAL_SECONDS if interval is None else interval
    now = time.time()
    last = read_last_evidence(dest)
    if last is not None and (now - last.get("ts", 0)) < interval:
        return None
    entry: dict = {"ts": round(now, 6), "trigger": trigger}
    try:
        entry["status"] = "ok"
        entry["result"] = seal(dest, allow_volatile=allow_volatile)
    except SystemExit as exc:
        entry["status"] = "error"
        entry["error"] = str(exc)[:200]
    except Exception as exc:
        entry["status"] = "error"
        entry["error"] = f"{type(exc).__name__}: {exc}"[:200]
    _append_evidence(dest, entry)
    return entry


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dest", default=None)
    ap.add_argument("--allow-volatile", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--autoseal", action="store_true",
                     help="seal only if due (periodic + idempotent); see autoseal_if_due")
    ap.add_argument("--interval", type=float, default=None,
                     help="autoseal due-interval in seconds "
                          "(default $ATTRIBUTION_SEAL_INTERVAL_SECONDS or %d)" % DEFAULT_AUTOSEAL_INTERVAL_SECONDS)
    ap.add_argument("--show-last", action="store_true",
                     help="print the last seal-log.jsonl entry and exit (no seal attempted)")
    a = ap.parse_args(argv)
    dest = Path(a.dest) if a.dest else default_dest()
    if a.show_last:
        print(json.dumps(read_last_evidence(dest), indent=1))
        return 0
    if a.autoseal:
        interval = a.interval
        if interval is None:
            interval = float(os.environ.get("ATTRIBUTION_SEAL_INTERVAL_SECONDS", DEFAULT_AUTOSEAL_INTERVAL_SECONDS))
        entry = autoseal_if_due(dest, interval, a.allow_volatile, trigger="manual-check")
        print(json.dumps(entry, indent=1))
        return 1 if (entry and entry.get("status") == "error") else 0
    res = seal(dest, a.allow_volatile)
    _append_evidence(dest, {"ts": round(time.time(), 6), "trigger": "manual", "status": "ok", "result": res})
    print(json.dumps(res, indent=1))
    return 1 if res["blobs_missing_in_source"] else 0


if __name__ == "__main__":
    sys.exit(main())
