"""The hooks P12 retired to exit-0 stubs (D15), run as the P12 base shipped them.

A test that compares a merged rule with the hook it replaced (the write gate's overwrite rule with
pretool-write-guard.sh, the write gate with the seven guards, lib/dev_loop_checks.py with the
anti-loop shells) needs that hook as it last decided, not its stub. ``materialize(name, dest)`` writes
hooks/<name> as BASE holds it to dest/hooks/<name>, beside a link to this tree's hooks/lib, so the
file finds its libraries as it did in place. BASE is in the history of every P12 checkout (CI fetches
the whole history).

CUT holds the parts of a retired hook that call a library function this tree no longer has, with
the reason; materialize leaves them out, so the hook still decides every other case as it did.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "d64fa96b0d70a22c8678a18aeadcece1e73c6e5f"  # the P12 base (merge train 2, #22)
# name -> (first line cut, first line kept after the cut). pretool-write-guard.sh: the main agent's
# per-file /allow grant for Write (lib.allowlist.match_sentinel_grant_for_write and CF-1) is gone; an
# /allow grant now releases any refused call where the pre-tool verdicts meet (lib/hook_launch), so
# no rule reads one, and without a grant this part of the hook decided nothing.
CUT = {"pretool-write-guard.sh": (b'if [ "$_WG_IS_SUB" != "1" ]; then\n',
                                  b"# If we couldn't extract a file path, allow")}


def materialize(name: str, dest: Path) -> Path:
    hooks = Path(dest) / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    if not (hooks / "lib").exists():
        os.symlink(ROOT / "hooks" / "lib", hooks / "lib")
    path = hooks / name
    if not path.exists():
        blob = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE}:hooks/{name}"], capture_output=True,
                              check=True).stdout
        if name in CUT:
            start, end = CUT[name]
            assert blob.count(start) == 1 and blob.count(end) == 1 and blob.index(start) < blob.index(end), name
            blob = blob[:blob.index(start)] + blob[blob.index(end):]
        path.write_bytes(blob)
        path.chmod(0o755)
    return path
