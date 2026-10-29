"""Sandbox build, reset and isolation (E2 modes (a) and (b)).

One scratch root holds everything a replay touches:

    <sb>/home/.claude        copy of the tree under test (the harness home), a
                             one-commit git snapshot of it, and its venv
    <sb>/home/<toy>          the toy product repository, directory "toyproj" (same
                             content as the planning kit's make_toy), origin <toy>-origin.git
    <sb>/state               CLAUDE_STATE_DIR (rule 8: never under /tmp)
    <sb>/tmp, vartmp, shm    private /tmp, /var/tmp, /dev/shm (mode ns)
    <sb>/settings            the armed copy and any custom settings file
    <sb>/replay              copy of this framework, run inside the sandbox
    <sb>/out, trace, markers per-run outputs, raw strace, step markers

Mode "ns" (a): a private mount namespace (root, or passwordless sudo) with the
kit's layout: <sb>/home bound at root's HOME (so the harness is ~/.claude and
the toy repo ~/toyproj), private temp dirs, <sb> itself at /mnt/sb.
Mode "scratch" (b): no namespace; HOME, CLAUDE_CONFIG_DIR and CLAUDE_STATE_DIR
point into <sb>, and every path written outside <sb> is reported. `guard=True`
wraps (b) in a namespace that masks the host HOME and temp dirs (except <sb>)
as a safety net for local runs; (b)'s own isolation and report are unchanged.

reset() restores the pristine state between scenarios. Nothing outside <sb> is
written; every removal is checked to lie under <sb>.
"""
from __future__ import annotations

import calendar
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field

MARK = ".replay-sandbox"
FIXED_DATE = "2026-01-01T00:00:00+0000"
COPY_IGNORE = shutil.ignore_patterns(".git", "venv", "__pycache__", ".pytest_cache", "*.pyc")
ARM = {"CLAUDE_OBLIGATION_GATE": "block", "CLAUDE_OBLIGATION_STOPGATE": "block",
       "CLAUDE_OBLIGATION_BARRIER": "block"}
TOY_FILES = {
    ".gitignore": "__pycache__/\n.pytest_cache/\n",
    "CLAUDE.md": "# CLAUDE.md\n\n> Project-specific settings for toyproj\n",
    "README.md": "# toy\n",
    "toy/__init__.py": "def add(a, b):\n    return a + b\n",
    "toy/util.py": "def sub(a,b): return a-b\n",
    "tests/test_add.py": "from toy import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
}
PROTECTED_RUNTIME = ".config/claude/protected-runtime.json"  # the empty-lists document init writes
PROTECTED_RUNTIME_SRC = "hooks/tests/fixtures/protected-runtime.json"
HERE = os.path.dirname(os.path.abspath(__file__))


@dataclass
class Layout:
    """Paths as the replay's processes see them."""
    mode: str
    sb: str
    home: str
    harness: str
    project: str
    origin: str
    state: str
    out: str
    trace: str
    markers: str
    config_dir: str | None = None
    scratch: list = field(default_factory=list)  # prefixes backed by the scratch root
    temp_dirs: list = field(default_factory=lambda: ["/tmp", "/var/tmp", "/dev/shm"])

    @property
    def python(self) -> str:
        return self.harness + "/venv/bin/python"

    def to_json(self) -> dict:
        return asdict(self)


def ns_home() -> str:
    """HOME inside the namespace: the home of the user the namespace runs as (root)."""
    return pwd.getpwuid(0).pw_dir


def layout_for(sb: str, mode: str) -> Layout:
    sb = os.path.abspath(sb)
    if mode == "ns":
        home, inner = ns_home(), "/mnt/sb"
        return Layout("ns", inner, home, home + "/.claude", home + "/toyproj", home + "/toyproj-origin.git",
                      inner + "/state", inner + "/out", inner + "/trace", inner + "/markers",
                      scratch=[home, inner, "/tmp", "/var/tmp", "/dev/shm"])
    if mode == "scratch":
        home = sb + "/home"
        return Layout("scratch", sb, home, home + "/.claude", home + "/toyproj", home + "/toyproj-origin.git",
                      sb + "/state", sb + "/out", sb + "/trace", sb + "/markers",
                      config_dir=home + "/.claude", scratch=[sb])
    raise ValueError(f"mode must be ns or scratch, not {mode!r}")


# ---------------------------------------------------------------- helpers

def _git_env(home: str) -> dict:
    """git without the host's global or system config."""
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": home, "LANG": "C.UTF-8",
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_DATE": FIXED_DATE, "GIT_COMMITTER_DATE": FIXED_DATE,
            "GIT_AUTHOR_NAME": "sandbox", "GIT_AUTHOR_EMAIL": "sandbox@example.invalid",
            "GIT_COMMITTER_NAME": "sandbox", "GIT_COMMITTER_EMAIL": "sandbox@example.invalid"}


def _git(sb: str, *args, cwd=None) -> str:
    p = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
                       cwd=cwd, env=_git_env(sb), capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout.strip()


def _under(path: str, root: str) -> bool:
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root + "/")


def _rm(sb: str, path: str) -> None:
    if not os.path.isfile(os.path.join(sb, MARK)) or not _under(path, sb) or os.path.realpath(path) == os.path.realpath(sb):
        raise RuntimeError(f"refusing to remove {path}: not inside sandbox {sb}")
    if os.path.islink(path) or os.path.isfile(path):
        os.unlink(path)
    elif os.path.isdir(path):
        shutil.rmtree(path)


def _requirement_names(tree: str) -> list[str]:
    names = []
    try:
        with open(os.path.join(tree, "requirements.txt")) as fh:
            for line in fh:
                m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line.split("#", 1)[0])
                if m:
                    names.append(m.group(1))
    except OSError:
        pass
    return names


def _dist_closure(names):
    """Installed distributions of the running interpreter needed by `names` (extras skipped)."""
    from importlib import metadata
    seen, todo, missing = {}, list(names), []
    while todo:
        name = todo.pop()
        key = re.sub(r"[-_.]+", "-", name).lower()
        if key in seen:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            if name in names:
                missing.append(name)
            continue
        seen[key] = dist
        for req in dist.requires or []:
            if "extra ==" in req.replace("extra==", "extra =="):
                continue
            todo.append(re.match(r"[A-Za-z0-9._-]+", req).group(0))
    return list(seen.values()), missing


_POLYGLOT = "#!/bin/sh\n'''exec' \"$(dirname -- \"$0\")/python\" \"$0\" \"$@\"\n' '''\n"


def _console_scripts(dist, venv: str) -> None:
    """The bin/ entry points pip would install (pytest, ...): copying package files skips them."""
    for ep in dist.entry_points:
        if ep.group != "console_scripts":
            continue
        module, _, attr = ep.value.partition(":")
        path = os.path.join(venv, "bin", ep.name)
        with open(path, "w") as fh:  # a sh/python polyglot: runs the venv python beside it, in either mode
            fh.write(_POLYGLOT + f"import sys\nfrom {module} import {attr.split('.')[0]}\nsys.exit({attr}())\n")
        os.chmod(path, 0o755)


def _make_venv(tree: str, venv: str, log) -> str:
    """A venv on the runner's base interpreter; its dependencies copied from the runner, else pip."""
    base = getattr(sys, "_base_executable", None) or sys.executable
    subprocess.run([base, "-m", "venv", "--without-pip", venv], check=True)
    site = subprocess.run([venv + "/bin/python", "-c", "import sysconfig;print(sysconfig.get_paths()['purelib'])"],
                          check=True, capture_output=True, text=True).stdout.strip()
    names = _requirement_names(tree)
    dists, missing = _dist_closure(names)
    if not missing:
        for dist in dists:
            root = str(dist.locate_file(""))
            for f in dist.files or []:
                rel = str(f)
                if rel.startswith("..") or "__pycache__" in rel:
                    continue
                dst = os.path.join(site, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(os.path.join(root, rel), dst)
            _console_scripts(dist, venv)
        return f"copied from runner: {', '.join(sorted(d.metadata['Name'] for d in dists))}"
    ver = f"py{sys.version_info[0]}{sys.version_info[1]}"
    req = os.path.join(tree, "requirements", ver + ".txt")
    args = ["--require-hashes", "-r", req] if os.path.isfile(req) else ["-r", os.path.join(tree, "requirements.txt")]
    log(f"runner lacks {missing}; installing {args[-1]} with pip (network)")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--target", site, *args], check=True)
    return f"pip install {args[-1]}"


# ---------------------------------------------------------------- build / reset

def build(tree: str, sb: str, log=print) -> dict:
    """Build a sandbox at `sb` from the harness tree at `tree` (working tree or a clone at any commit)."""
    tree, sb = os.path.abspath(tree), os.path.abspath(sb)
    if _under(sb, tree) or _under(tree, sb):
        raise RuntimeError("the sandbox and the tree under test must not contain each other")
    if _under(sb, "/mnt"):
        raise RuntimeError("the sandbox must not lie under /mnt (the namespace mounts over it)")
    if os.path.exists(sb):
        if os.listdir(sb) and not os.path.isfile(os.path.join(sb, MARK)):
            raise RuntimeError(f"{sb} exists and is not a sandbox; refusing to replace it")
        if os.path.isfile(os.path.join(sb, MARK)):
            for name in os.listdir(sb):
                if name != MARK:
                    _rm(sb, os.path.join(sb, name))
    os.makedirs(sb, exist_ok=True)
    t0 = time.monotonic()
    with open(os.path.join(sb, MARK), "w") as fh:
        json.dump({"tree": tree}, fh)
    harness = os.path.join(sb, "home", ".claude")
    shutil.copytree(tree, harness, symlinks=True, ignore=COPY_IGNORE)
    _git(sb, "init", "-q", "-b", "master", cwd=harness)
    _git(sb, "add", "-A", "-f", ".", cwd=harness)
    _git(sb, "commit", "-q", "--allow-empty", "-m", "sandbox snapshot", cwd=harness)
    snapshot = _git(sb, "rev-parse", "HEAD", cwd=harness)
    deps = _make_venv(tree, os.path.join(harness, "venv"), log)
    shutil.copytree(HERE, os.path.join(sb, "replay"), ignore=COPY_IGNORE)
    os.makedirs(os.path.join(sb, "settings"))
    with open(os.path.join(harness, "settings.json")) as fh:
        shipped = json.load(fh)
    with open(os.path.join(sb, "settings", "armed.json"), "w") as fh:
        json.dump(armed(shipped), fh, indent=2)
    tree_rev = ""
    if os.path.exists(os.path.join(tree, ".git")):
        p = subprocess.run(["git", "-C", tree, "rev-parse", "HEAD"], capture_output=True, text=True,
                           env=_git_env(sb))
        tree_rev = p.stdout.strip()
    info = {"tree": tree, "tree_head": tree_rev, "snapshot": snapshot, "deps": deps,
            "python": os.path.realpath(getattr(sys, "_base_executable", sys.executable)),
            "built_s": round(time.monotonic() - t0, 1)}
    with open(os.path.join(sb, MARK), "w") as fh:
        json.dump(info, fh, indent=1)
    return info


def armed(settings: dict) -> dict:
    """The sandbox-armed copy (P1 "Sandbox and arming"): G1-G3 block, G4 left advisory."""
    s = json.loads(json.dumps(settings))
    env = s.setdefault("env", {})
    env.update(ARM)
    env.pop("CLAUDE_OBLIGATION_TERMINAL", None)
    return s


def info(sb: str) -> dict:
    with open(os.path.join(sb, MARK)) as fh:
        return json.load(fh)


def _make_toy(sb: str, home: str, origin_inner: str) -> None:
    toy, origin = os.path.join(home, "toyproj"), os.path.join(home, "toyproj-origin.git")
    for rel, text in TOY_FILES.items():
        os.makedirs(os.path.dirname(os.path.join(toy, rel)), exist_ok=True)
        with open(os.path.join(toy, rel), "w") as fh:
            fh.write(text)
    _git(sb, "init", "-q", "-b", "master", cwd=toy)
    _git(sb, "config", "user.name", "sandbox", cwd=toy)
    _git(sb, "config", "user.email", "sandbox@example.invalid", cwd=toy)
    _git(sb, "add", "-A", cwd=toy)
    _git(sb, "commit", "-qm", "init toy", cwd=toy)
    _git(sb, "tag", "sb-init", cwd=toy)
    # Not racily clean: whether a later `git status` rewrites the index must not depend on timing.
    stamp = calendar.timegm(time.strptime(FIXED_DATE[:19], "%Y-%m-%dT%H:%M:%S"))
    for rel in TOY_FILES:
        os.utime(os.path.join(toy, rel), (stamp, stamp))
    _git(sb, "update-index", "-q", "--really-refresh", cwd=toy)
    _git(sb, "clone", "-q", "--bare", toy, origin)
    _git(sb, "remote", "add", "origin", origin_inner, cwd=toy)
    _git(sb, "fetch", "-q", origin, "+refs/heads/*:refs/remotes/origin/*", cwd=toy)


def reset(sb: str, mode: str) -> None:
    """Pristine state: harness at its snapshot, a fresh toy pair, empty state, temp and output dirs."""
    sb = os.path.abspath(sb)
    lay = layout_for(sb, mode)
    home = os.path.join(sb, "home")
    harness = os.path.join(home, ".claude")
    snap = info(sb)["snapshot"]
    _git(sb, "checkout", "-q", "-f", "master", cwd=harness)
    _git(sb, "reset", "-q", "--hard", snap, cwd=harness)
    _git(sb, "clean", "-qffdx", "-e", "/venv", cwd=harness)
    for name in os.listdir(home):
        if name != ".claude":
            _rm(sb, os.path.join(home, name))
    for d in ("state", "tmp", "vartmp", "shm", "out", "trace", "markers", "replay"):
        if os.path.exists(os.path.join(sb, d)):
            _rm(sb, os.path.join(sb, d))
        if d != "replay":
            os.makedirs(os.path.join(sb, d))
    shutil.copytree(HERE, os.path.join(sb, "replay"), ignore=COPY_IGNORE)  # the framework as it is now
    os.makedirs(os.path.join(sb, "vartmp", "claude-scratch"))
    src = os.path.join(harness, PROTECTED_RUNTIME_SRC)
    if os.path.isfile(src):
        os.makedirs(os.path.dirname(os.path.join(home, PROTECTED_RUNTIME)))
        shutil.copyfile(src, os.path.join(home, PROTECTED_RUNTIME))
    _make_toy(sb, home, lay.origin)


def settings_file(sb: str, mode: str, choice: str) -> tuple[str, str]:
    """(label, inner path) for 'shipped', 'armed' or a path to any other settings file."""
    lay = layout_for(sb, mode)
    if choice == "shipped":
        return "shipped", lay.harness + "/settings.json"
    if choice == "armed":
        return "armed", lay.sb + "/settings/armed.json"
    label = os.path.splitext(os.path.basename(choice))[0]
    shutil.copyfile(choice, os.path.join(sb, "settings", "custom-" + label + ".json"))
    return label, f"{lay.sb}/settings/custom-{label}.json"


# ---------------------------------------------------------------- isolation

_NS_SCRIPT = r'''
set -e
SB="$1"; NSHOME="$2"; OWNER="$3"; shift 3
mount -t tmpfs none /mnt
mkdir -p /mnt/sb
mount --bind "$SB" /mnt/sb
mount --bind /mnt/sb/home "$NSHOME"
mount --bind /mnt/sb/tmp /tmp
mount --bind /mnt/sb/vartmp /var/tmp
[ -d /dev/shm ] && mount --bind /mnt/sb/shm /dev/shm
[ -z "$OWNER" ] || chown -R 0:0 /mnt/sb
set +e
"$@"; rc=$?
[ -z "$OWNER" ] || chown -R "$OWNER" /mnt/sb
exit $rc
'''

_GUARD_SCRIPT = r'''
set -e
OWNER="$1"; KEEP="$2"; shift 2
mount -t tmpfs none /mnt
masks=()
for m in /tmp /var/tmp /dev/shm "$HOST_HOME"; do [ -d "$m" ] && masks+=("$m"); done
for m in "${masks[@]}"; do mkdir -p "/mnt/orig$m"; mount --bind "$m" "/mnt/orig$m"; done
for m in "${masks[@]}"; do mount -t tmpfs none "$m"; done
for m in "${masks[@]}"; do case "$KEEP/" in "$m"/*) mkdir -p "$KEEP"; mount --bind "/mnt/orig$KEEP" "$KEEP";; esac; done
[ -z "$OWNER" ] || chown -R 0:0 "$KEEP"
set +e
"$@"; rc=$?
[ -z "$OWNER" ] || chown -R "$OWNER" "$KEEP"
exit $rc
'''


def _priv() -> tuple[list, str]:
    if os.geteuid() == 0:
        return [], ""
    return ["sudo", "-n"], f"{os.getuid()}:{os.getgid()}"


def launch(sb: str, lay: Layout, argv: list, env: dict, guard: bool = False) -> int:
    """Run argv (with exactly `env`) isolated as `lay.mode` says; returns its exit code."""
    sb = os.path.abspath(sb)
    cmd = ["env", "-i"] + [f"{k}={v}" for k, v in sorted(env.items())] + list(argv)
    if lay.mode == "ns":
        pre, owner = _priv()
        cmd = pre + ["unshare", "--mount", "--propagation", "private", "bash", "-c", _NS_SCRIPT, "ns",
                     sb, lay.home, owner] + cmd
    elif guard:
        pre, owner = _priv()
        host_home = os.path.realpath(os.environ.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir)
        if _under(sb, host_home):
            raise RuntimeError("guard masks the host HOME; put the sandbox outside it")
        cmd = pre + ["unshare", "--mount", "--propagation", "private", "env", f"HOST_HOME={host_home}",
                     "bash", "-c", _GUARD_SCRIPT, "guard", owner, sb] + cmd
    return subprocess.run(cmd).returncode
