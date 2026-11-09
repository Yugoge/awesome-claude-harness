"""P10 A25's removal faults (R13, R14): an agent removes a tracked file of the product repository
with `git rm`, recoverably, or tries a forced removal that the registered hooks refuse.

Driver argument `removal=<kind>@<label glob>=<path>[;...]` (cli.py --arg; inner.py installs it).
Before the first step whose label matches the glob and whose actor is a subagent, that subagent
makes the calls of <kind> on <path> (a path of the toy project), each a Bash call through every
hook the settings register, then goes on with its own step:

    recover   `git rev-parse HEAD`, then `git rm -- <path>` (no -f) of a file as HEAD has it, and its
              DISCARDED line (R14: `DISCARDED <path> - recover: git checkout <sha> -- <path>`, <sha>
              HEAD at removal) said in the agent's transcript; then the line's own recover command.
    modified  `git rm -- <path>` of a file that differs from HEAD (the agent's own edit): the hooks
              let it run and git refuses it, so the file stays with the agent's change.
    forced    `git rm -f -- <path>`: refused at PreToolUse. The agent reads the refusal; where it
              names a recoverable `git rm` without -f, the agent's next call is that one (the force
              option dropped), then the recover kind's DISCARDED line and recover command, so the
              pipeline goes on from the state the fault met.

Each part records in faults.json (beside the other faults' records): kind, label, path, agent and
role, and per call its command, whether a hook refused it (which hooks, their text normalised),
whether it ran and its error; the path's state before, after the removal and at the end (exists,
sha256, index entry `git ls-files -s`, `git status --porcelain`), the DISCARDED line, and for
`forced` whether the refusal named the action the agent took next. The driver-side git reads take
no lock and run no git hook.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess

DISCARDED = "DISCARDED {path} - recover: git checkout {sha} -- {path}"
_RECOVER = re.compile(r"^DISCARDED (\S+) - recover: (git checkout \S+ -- \S+)$")
# What the refusal must name for the agent to take it: a recoverable git rm, without -f.
_NAMES_PLAIN_RM = re.compile(r"recoverable git rm \(no -f\b")


def _record(rp, rec: dict) -> None:
    if not any(r is rec for r in rp.fault_records):
        rp.fault_records.append(rec)
    with rp.acting("driver"):
        with open(os.path.join(rp.layout.out, "faults.json"), "w") as fh:
            json.dump(rp.fault_records, fh, indent=1)


def _git(rp, *args) -> str:
    p = subprocess.run(["git", "--no-optional-locks", "-c", "core.hooksPath=/dev/null", "-C", rp.layout.project,
                        *args], capture_output=True, text=True, env=rp.bash_env)
    return p.stdout.rstrip("\n")  # a status line starts with a space


def path_state(rp, path: str) -> dict:
    full = os.path.join(rp.layout.project, path)
    with rp.acting("fault"):
        try:
            with open(full, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            digest = ""
        return {"exists": os.path.exists(full), "sha256": digest, "index": _git(rp, "ls-files", "-s", "--", path),
                "status": _git(rp, "status", "--porcelain=v1", "--", path)}


def _call(rp, sub, command: str, label: str) -> tuple:
    call = sub.bash(command, label, label=label)
    blocks = call.pre.blocks if call.pre else []
    text = "\n".join((h.get("stderr") or "") + (h.get("stdout") or "") for h in blocks)
    return call, text, {"command": command, "label": label, "refused": call.blocked,
                        "hooks": [h["hook"] for h in blocks], "text": rp.norm_text(text),
                        "ran": call.ok, "error": rp.norm_text(call.error)[:600],
                        "stdout": ((call.response or {}).get("stdout") or "").strip()}


def _remove_and_recover(rp, sub, path: str, rec: dict, rm: str) -> None:
    c = _call(rp, sub, "git rev-parse HEAD", f"{sub.role} removal: git rev-parse HEAD")[2]
    rec["calls"].append(c)
    sha = c["stdout"]
    rec["calls"].append(_call(rp, sub, rm, f"{sub.role} removal: {rm}")[2])
    rec["removed"] = path_state(rp, path)
    line = DISCARDED.format(path=path, sha=sha)
    sub.s.say(line, sub.aid)
    rec["discarded"] = line
    m = _RECOVER.match(line)
    recover = m.group(2) if m else ""
    c = _call(rp, sub, recover, f"{sub.role} removal: recover {path}")[2]
    rec["calls"].append(c)


def _part(rp, kind: str, glob: str, path: str):
    done: list = []

    def fn(rp_, phase, step):
        actor = step.get("actor")
        if phase != "before" or done or getattr(actor, "agent", None) is None:
            return
        done.append(1)
        rec = {"kind": f"removal-{kind}", "label": step["label"], "removal_path": path, "agent": actor.aid,
               "role": actor.role, "calls": [], "before": path_state(rp, path)}
        if kind == "recover":
            _remove_and_recover(rp, actor, path, rec, f"git rm -- {path}")
        elif kind == "modified":
            rec["calls"].append(_call(rp, actor, f"git rm -- {path}", f"{actor.role} removal: git rm -- {path}")[2])
        elif kind == "forced":
            forced = f"git rm -f -- {path}"
            _c, text, c = _call(rp, actor, forced, f"{actor.role} removal: {forced}")
            rec["calls"].append(c)
            rec["refused_state"] = path_state(rp, path)
            rec["named"] = bool(c["refused"] and _NAMES_PLAIN_RM.search(text))
            if rec["named"]:  # the action the refusal names: the same removal without -f
                _remove_and_recover(rp, actor, path, rec, f"git rm -- {path}")
        rec["after"] = path_state(rp, path)
        _record(rp, rec)
    return fn


def install(rp, spec: str) -> None:
    """Register the removal parts `spec` names on rp (Replay.step's fault hooks)."""
    for part in [p for p in spec.split(";") if p.strip()]:
        kind, _, rest = part.partition("@")
        glob, _, path = rest.rpartition("=")
        if kind not in ("recover", "modified", "forced") or not glob or not path:
            raise ValueError(f"removal takes recover|modified|forced@<label glob>=<path>, not {part!r}")
        rp.faults.append((glob, _part(rp, kind, glob, path)))
