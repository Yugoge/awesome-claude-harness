"""P1c A11, the live landing (D15, D19): a merge reaching a harness home whose sessions keep running.

The CLI keeps the hook commands it loaded at session start (the settings file a replay reads once,
replay.Replay), and each event runs whatever file is on disk at that path. So one replay models a
session running across the landing: its sandbox is built from the BASE tree (a tree from git history,
base_tree()), the tree under test is committed in the sandbox's harness home as branch `landed`, a
child of the base snapshot (add_landed()), and between two events the harness home fast-forwards to
it, as the owner's pull of the merge does (install(), driver argument `land`). Nothing else changes:
the session, its transcript, the settings it loaded, the project and the state directory go on.

Driver arguments this module reads (cli.py --arg K=V; inner.py installs it when either is given):

    land=<when>:<label glob>[#<n>]
        <when> is `before` or `after`: the harness home lands before the n-th step (default the first)
        whose label matches the glob, or after it (after its hooks: a tool call's PostToolUse).
    land=start
        The harness home lands before the driver starts (a session that loaded the base's settings.json
        and meets only this tree's files: every command it types reads this tree's text).
    hooklist=landed
        From the landing on, the session's hook list is the landed home's settings.json (A11's "again
        with your settings.json"): the hooks each later event runs and the environment settings.json
        gives hooks and Bash calls (the replay's own --env still overriding it). settings.json lands
        with the files it registers, in the one fast-forward, so no session holds the landed list
        over the base's files; the session that has it is the one (re)loaded on the landed home, its
        transcript, state and project going on (a resumed session). Without it the session keeps the
        list it loaded (D15).
    blocks=pass
        Every block passes, recorded in blocks.json as a deviation would record it, so the replay goes
        on past it as the base replay does. The test compares the two replays' blocks afterwards (same
        hook, same step by its normalised label: a todo step by its content, same refusal by its
        normalised first line). A stop block naming an artifact an injected fault (faults.py) left
        unrepaired is not passed: it goes back to that agent, as on the base (the fault's own rounds).

facts.json "landing" records where the home landed, the commit before and after, the stores of the
base G2's no-progress round found on disk at that moment and, with hooklist=landed, the settings file
the session reloaded and the environment keys that changed with it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

LANDED = "landed"
STORES = ("escalations", "escalation-admissions", "progress", "deferred-checks")


# ---------------------------------------------------------------- outside the sandbox

def base_tree(repo: str, rev: str, dest: str) -> str:
    """The tree of commit `rev` of the repository at `repo`, as files under `dest` (git archive)."""
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    arc = subprocess.run(["git", "-C", repo, "archive", "--format=tar", rev], capture_output=True)
    if arc.returncode:
        raise RuntimeError(f"git archive {rev}: {arc.stderr.decode(errors='replace').strip()}")
    subprocess.run(["tar", "-x", "-C", dest], input=arc.stdout, check=True)
    return dest


def add_landed(sb: str, tree: str) -> str:
    """Commit `tree` (the tree under test, copied as sandbox.build copies a tree) in the built sandbox
    `sb`'s harness home as branch LANDED, a child of its snapshot; the git snapshot reset() restores
    takes it too. Returns the commit."""
    from . import sandbox
    harness = os.path.join(sb, "home", ".claude")
    work, index = os.path.join(sb, "landed-tree"), os.path.join(sb, "landed-index")
    shutil.copytree(tree, work, symlinks=True, ignore=sandbox.COPY_IGNORE)
    env = dict(sandbox._git_env(sb), GIT_DIR=os.path.join(harness, ".git"), GIT_WORK_TREE=work,
               GIT_INDEX_FILE=index)

    def git(*args):
        p = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], env=env, capture_output=True,
                           text=True)
        if p.returncode:
            raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
        return p.stdout.strip()

    try:
        git("add", "-A", "-f", ".")
        commit = git("commit-tree", git("write-tree"), "-p", "HEAD", "-m", "the merge, landed")
        git("update-ref", "refs/heads/" + LANDED, commit)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if os.path.exists(index):
            os.unlink(index)
    snap = os.path.join(sb, sandbox.GIT_SNAPSHOT)
    shutil.rmtree(snap)
    shutil.copytree(os.path.join(harness, ".git"), snap, symlinks=True)
    return commit


# ---------------------------------------------------------------- inside the sandbox

def _stores(project: str) -> list[str]:
    """The base G2's no-progress stores on disk (project-relative directories holding files)."""
    root = os.path.join(project, ".claude", "dev-registry")
    found = []
    for dp, dns, fns in os.walk(root):
        if os.path.basename(dp) in STORES and fns:
            found.append(os.path.relpath(dp, project) + f" ({len(fns)} files)")
    return sorted(found)


def _reload(rp) -> dict:
    """The session's hook list becomes the landed settings.json (hooklist=landed): rp.settings, and its
    env in rp.env and rp.bash_env (a key the replay's --env sets keeps that value). Returns what changed."""
    from . import hookrun
    path = os.path.join(rp.layout.harness, "settings.json")
    with open(path) as fh:
        landed = json.load(fh)
    old, new = hookrun.settings_env(rp.settings), hookrun.settings_env(landed)
    changed = sorted(k for k in set(old) | set(new) if k not in rp.env_extra and old.get(k) != new.get(k))
    rp.settings = landed
    fresh = rp._env(rp.env_extra)  # the session's env as it starts with the landed list
    for env in (rp.env, rp.bash_env):
        for k in changed:
            if k in fresh:
                env[k] = fresh[k]
            else:
                env.pop(k, None)
    return {"hooklist": "landed", "settings": path, "env_changed": changed}


def _land(rp, label: str) -> None:
    from .drivers.close import fact
    lay = rp.layout
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": lay.home, "LANG": "C.UTF-8",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}

    def git(*args):
        return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=lay.harness, env=env,
                              capture_output=True, text=True)

    before = git("rev-parse", "HEAD").stdout.strip()
    with rp.acting("landing"):
        p = git("merge", "-q", "--ff-only", LANDED)
    after = git("rev-parse", "HEAD").stdout.strip()
    rec = {"at": label, "event": rp.n_events, "before": before, "after": after, "rc": p.returncode,
           "output": (p.stdout + p.stderr).strip()[-1000:], "status": git("status", "--porcelain").stdout[-2000:],
           "no_progress_stores": _stores(lay.project)}
    if not p.returncode and after != before and rp.args.get("hooklist") == "landed":
        with rp.acting("landing"):
            rec.update(_reload(rp))
    fact(rp, "landing", rec)
    if p.returncode or after == before:
        raise RuntimeError(f"the harness home did not land at {label!r}: {rec['output']}")


class _Pass:
    """A deviation that passes every block (Replay.settle asks covers(); a driver's own comes first)."""

    def __init__(self, why: str):
        self.why, self.quote = why, ""

    def covers(self, hook: str, raw: str, text: str) -> bool:
        return True


def _fault_round(rp, ev) -> bool:
    """A subagent's stop block naming an artifact an injected fault left unrepaired (faults.py)."""
    text = "\n".join((h.get("stderr") or "") + (h.get("stdout") or "") for h in ev.blocks)
    return ev.event == "SubagentStop" and any(path and path in text and not f["rec"]["repaired"]
                                              for path, f in (getattr(rp, "fault_pending", None) or {}).items())


def install(rp) -> None:
    """Register what the arguments `land`, `hooklist` and `blocks` ask for on rp (see the module text)."""
    spec = rp.args.get("land")
    if rp.args.get("hooklist") not in (None, "", "landed"):
        raise ValueError(f"hooklist wants landed, not {rp.args['hooklist']!r}")
    if rp.args.get("hooklist") and not spec:
        raise ValueError("hooklist=landed wants a landing (land=...)")
    if spec == "start":  # landed before the driver reads any text: every command typed reads this tree's
        _land(rp, "start")
    elif spec:
        when, _, glob = spec.partition(":")
        glob, _, nth = glob.partition("#")
        if when not in ("before", "after") or not glob:
            raise ValueError(f"land wants <before|after>:<label glob>[#n], not {spec!r}")
        state = {"seen": 0, "landed": False, "n": int(nth or 1)}

        def hook(rp, phase, data):
            if state["landed"]:
                return
            if phase == "before":
                state["seen"] += 1
            if phase == when and state["seen"] == state["n"]:
                state["landed"] = True
                _land(rp, data["label"])

        rp.faults.append((glob, hook))
    if rp.args.get("blocks") not in (None, "", "pass"):
        raise ValueError(f"blocks wants pass, not {rp.args['blocks']!r}")
    if rp.args.get("blocks") != "pass":
        return
    settle = rp.settle
    passes = _Pass("live landing: every block passes, recorded (compared with the base replay's after the run)")

    def settle_passing(ev, label, deviation=None):
        if ev is None or not ev.blocks or _fault_round(rp, ev):
            return settle(ev, label, deviation)
        devs = [] if deviation is None else list(deviation) if isinstance(deviation, (list, tuple)) else [deviation]
        return settle(ev, label, devs + [passes])

    rp.settle = settle_passing
