"""The one way the tests reach a private mount namespace, as root inside it, on any runner.

Ways, probed in order: "root" (already root: ``unshare -m``); else "user" (``unshare -rm``, an unprivileged user
namespace; refused where the kernel restricts them, as GitHub's Ubuntu runners and many hosts do), then "sudo"
(``sudo -n ... unshare -m``, the runner's passwordless sudo). The command always passes its environment through
``env -i`` (sudo would reset it). A test that needs the namespace calls ``require``: where no way works it is skipped
with every way's answer and a warning, and on GitHub Actions it fails instead (CI's runner has passwordless sudo, so
such tests must run there). ``as_root`` runs one command as root the same two ways (directly, else sudo).
"""
from __future__ import annotations

import functools
import os
import shutil
import subprocess
import warnings

import pytest


def unshare_argv(way: str, env: dict, argv: list[str]) -> list[str]:
    """argv in a private mount namespace made `way` ("root", "user" or "sudo"), with exactly `env`."""
    pre = ["sudo", "-n"] if way == "sudo" else []
    flags = ["-rm"] if way == "user" else ["-m"]
    return [*pre, "env", "-i", *(f"{k}={v}" for k, v in sorted(env.items())),
            "unshare", *flags, "--propagation", "private", *argv]


@functools.lru_cache(maxsize=None)
def way() -> tuple[str | None, str]:
    """The first way to a namespace that can mount a tmpfs over /tmp, or None and what each way answered."""
    ways = ["root"] if os.geteuid() == 0 else ["user"] + (["sudo"] if shutil.which("sudo") else [])
    why = []
    for w in ways:
        try:
            p = subprocess.run(unshare_argv(w, dict(os.environ), ["bash", "-c", "mount -t tmpfs none /tmp"]),
                               capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            why.append(f"{w}: {e}")
            continue
        if p.returncode == 0:
            return w, ""
        why.append(f"{w}: {p.stderr.strip()[:160] or p.returncode}")
    return None, "; ".join(why)


def _cannot(msg: str):
    if os.environ.get("GITHUB_ACTIONS") == "true":
        pytest.fail(msg + "; CI's runner has passwordless sudo, so they must run there")
    warnings.warn(msg)  # shown in the warnings summary of every run, -q included
    pytest.skip(msg)


def require(what: str) -> str:
    """The way to the namespace `what` needs; skips (failing on GitHub Actions) where there is none."""
    w, why = way()
    if w is None:
        _cannot(f"{what} cannot run here, no private mount namespace ({why})")
    return w


def as_root(what: str, argv: list[str]) -> None:
    """Run argv as root (directly when root, else through passwordless sudo); skips (failing on GitHub Actions)
    where neither works."""
    cmd = argv if os.geteuid() == 0 else ["sudo", "-n", *argv]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except OSError as e:
        _cannot(f"{what} cannot run here, nothing runs as root ({e})")
    if p.returncode:
        _cannot(f"{what} cannot run here, nothing runs as root ({p.stderr.strip()[:160] or p.returncode})")
