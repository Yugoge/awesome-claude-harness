"""The hooks P12 retired to exit-0 stubs (D15), run as the P12 base shipped them.

A test that compares a merged rule with the hook it replaced (the write gate's overwrite rule with
pretool-write-guard.sh, the write gate with the seven guards, lib/dev_loop_checks.py with the
anti-loop shells) needs that hook as it last decided, not its stub. ``materialize(name, dest)`` writes
hooks/<name> as BASE holds it to dest/hooks/<name>, beside a link to this tree's hooks/lib, so the
file finds its libraries as it did in place. BASE is in the history of every P12 checkout (CI fetches
the whole history).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "d64fa96b0d70a22c8678a18aeadcece1e73c6e5f"  # the P12 base (merge train 2, #22)


def materialize(name: str, dest: Path) -> Path:
    hooks = Path(dest) / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    if not (hooks / "lib").exists():
        os.symlink(ROOT / "hooks" / "lib", hooks / "lib")
    path = hooks / name
    if not path.exists():
        blob = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE}:hooks/{name}"], capture_output=True,
                              check=True).stdout
        path.write_bytes(blob)
        path.chmod(0o755)
    return path
