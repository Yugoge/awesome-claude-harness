"""The product repository as a replay left it (P10 A25: a product repository left clean after the
pipelines; R8, the A11 checks), read once the driver has ended, before the sandbox goes.

record() writes endstate.json beside blocks.json (untraced runs; inner.py): for the toy product
repository the replay ran in, `git status --porcelain=v1 -uall` (each entry's code and path), the
ignored paths (`--ignored=matching`), and for each ignored path the rule `git check-ignore -v`
names (source file, line, pattern); the lines of its `.git/info/exclude` (resolved through `git
rev-parse --git-path`, as a hook resolves it); each tracked file a line of that exclude file matches
(`git check-ignore --no-index -v` over `git ls-files`: git never hides a tracked file, so a match is a
pattern that also covers the project's own files, whose untracked siblings it would hide); and whether its tracked .gitignore is still HEAD's
at the replay's start (the `sb-init` tag sandbox.py puts on the toy's first commit) and in HEAD,
byte for byte. Its git calls take no lock and run no git hook; they change nothing in the toy.
"""
from __future__ import annotations

import json
import os
import subprocess

START = "sb-init"  # sandbox._make_toy's tag on the toy's first commit


def _git(rp, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "--no-optional-locks", "-c", "core.hooksPath=/dev/null", "-C",
                           rp.layout.project, *args], capture_output=True, text=True, env=rp.bash_env)


def _entries(z: str) -> list[dict]:
    """`git status --porcelain=v1 -z` -> [{code, path}] (a rename's source dropped)."""
    out, parts, i = [], z.split("\0"), 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        out.append({"code": e[:2], "path": e[3:]})
        if e[0] in "RC":
            i += 1
    return out


def state(rp) -> dict:
    """The toy's state now (see the module docstring)."""
    rec: dict = {"project": rp.norm_text(rp.layout.project)}
    st = _git(rp, "status", "--porcelain=v1", "-z", "-uall")
    if st.returncode:
        return dict(rec, error=st.stderr.strip()[-400:])
    rec["status"] = _entries(st.stdout)
    ign = _git(rp, "status", "--porcelain=v1", "-z", "-uall", "--ignored=matching")
    ignored = [e["path"] for e in _entries(ign.stdout) if e["code"] == "!!"]
    rules = {}
    if ignored:
        chk = subprocess.run(["git", "--no-optional-locks", "-C", rp.layout.project, "check-ignore", "-v", "-z",
                              "--stdin"], input="\0".join(ignored) + "\0", capture_output=True, text=True,
                             env=rp.bash_env)
        f = chk.stdout.split("\0")
        for j in range(0, len(f) - 3, 4):  # source, line, pattern, path
            rules[f[j + 3]] = {"source": f[j], "line": f[j + 1], "pattern": f[j + 2]}
    rec["ignored"] = [{"path": p, **rules.get(p, {})} for p in ignored]
    tracked = [p for p in _git(rp, "ls-files", "-z").stdout.split("\0") if p]
    rec["tracked_excluded"] = []
    if tracked:
        chk = subprocess.run(["git", "--no-optional-locks", "-C", rp.layout.project, "check-ignore", "--no-index", "-v",
                              "-z", "--stdin"], input="\0".join(tracked) + "\0", capture_output=True, text=True,
                             env=rp.bash_env)
        f = chk.stdout.split("\0")
        rec["tracked_excluded"] = [{"path": f[j + 3], "pattern": f[j + 2]} for j in range(0, len(f) - 3, 4)
                                   if f[j].endswith("info/exclude")]
    gp = _git(rp, "rev-parse", "--git-path", "info/exclude").stdout.strip()
    exclude = gp if os.path.isabs(gp) else os.path.join(rp.layout.project, gp)
    try:
        with open(exclude, encoding="utf-8") as fh:
            rec["exclude"] = [ln.rstrip("\n") for ln in fh if ln.strip() and not ln.startswith("#")]
    except OSError:
        rec["exclude"] = []
    rec["exclude_source"] = rp.norm_text(exclude)
    blob = _git(rp, "hash-object", "--no-filters", "--", ".gitignore").stdout.strip()
    rec["gitignore"] = {"worktree": blob,
                        "start": _git(rp, "rev-parse", "-q", "--verify", f"{START}:.gitignore").stdout.strip(),
                        "head": _git(rp, "rev-parse", "-q", "--verify", "HEAD:.gitignore").stdout.strip()}
    rec["head_moved"] = _git(rp, "rev-parse", "HEAD").stdout.strip() != \
        _git(rp, "rev-parse", f"{START}^{{commit}}").stdout.strip()
    return rec


def record(rp) -> None:
    """Write endstate.json (best effort: a replay whose toy is gone records why)."""
    try:
        rec = state(rp) if os.path.isdir(os.path.join(rp.layout.project, ".git")) else {"error": "no toy repository"}
    except Exception as e:  # noqa: BLE001 - the record never fails the replay; the test reads the reason
        rec = {"error": f"{type(e).__name__}: {e}"}
    with open(os.path.join(rp.layout.out, "endstate.json"), "w") as fh:
        json.dump(rec, fh, indent=1)


def load(run_dir: str) -> dict:
    try:
        with open(os.path.join(run_dir, "endstate.json")) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}
