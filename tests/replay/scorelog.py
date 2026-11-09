"""P13-2 B2: the score log of a replay, and the observer hook run once more on the final transcript.

Driver argument (cli.py --arg K=V; inner.py calls resweep() when it is given, after the driver ran):

    resweep=1

The score observer is the PostToolUse hook that carries the Agent matcher (hooks/posttool-close-rating.py);
it sweeps the active command span after each main-agent dispatch and appends score events to the score log
(logs/lifecycle.jsonl under the config directory). resweep() runs it twice more, each time as the CLI would run
it on the last main-agent dispatch's return: with the payload that dispatch's PostToolUse carried
(invocations.jsonl), the environment every hook got, the project as its working directory, and the transcript
as it stands at the end of the run.

* The first run uses the replay's own config directory: the log must be left byte for byte as it was (a
  second sweep adds no row).
* The second run uses an empty config directory beside it (out/score-rebuild), so it appends every event the
  final transcript yields to an empty log: the first run's silence is then not a hook that did nothing.

facts.json "score resweep" records both runs (exit code, output, the log's size and sha256 before and after,
the rebuilt event rows); out/score-log.jsonl is the replay's score log as the run left it.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil

HOOK = "hooks/posttool-close-rating.py"
LOG = os.path.join("logs", "lifecycle.jsonl")


def _read(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return b""


def _last_dispatch_payload(rp) -> dict | None:
    """The PostToolUse payload of the main agent's last Agent call (the event the observer reacts to)."""
    last = None
    with open(os.path.join(rp.layout.out, "invocations.jsonl")) as fh:
        for line in fh:
            inv = json.loads(line)
            payload = inv.get("payload") or {}
            if inv.get("event") == "PostToolUse" and payload.get("tool_name") == "Agent" and not payload.get("agent_id"):
                last = payload
    return last


def _run(rp, payload: dict, config_dir: str) -> dict:
    """The observer hook as settings.json registers it for this payload, with `config_dir` as its config directory."""
    from . import hookrun
    hooks = [h for h in hookrun.select(rp.settings, "PostToolUse", payload) if h["hook"] == HOOK]
    if len(hooks) != 1:
        return {"hooks": len(hooks)}
    env = dict(rp.env, CLAUDE_CONFIG_DIR=config_dir)
    res = hookrun._run_one(hooks[0], json.dumps(payload), env, rp.layout.project)
    return {"hooks": 1, "rc": res["rc"], "stdout": res["stdout"], "stderr": res["stderr"]}


def _events(raw: bytes) -> list:
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    return [row for row in rows if row.get("kind") == "event"]


def resweep(rp) -> None:
    from .drivers.close import fact
    payload = _last_dispatch_payload(rp)
    if payload is None:
        fact(rp, "score resweep", {"error": "the replay made no main-agent dispatch"})
        return
    config = rp.env.get("CLAUDE_CONFIG_DIR") or os.path.join(rp.env["HOME"], ".claude")
    log = os.path.join(config, LOG)
    before = _read(log)
    again = _run(rp, payload, config)
    after = _read(log)
    rebuild = os.path.join(rp.layout.out, "score-rebuild")
    shutil.rmtree(rebuild, ignore_errors=True)
    rebuilt = _run(rp, payload, rebuild)
    rebuilt["events"] = _events(_read(os.path.join(rebuild, LOG)))
    fact(rp, "score resweep", dict(again, tool_use_id=payload.get("tool_use_id"), rebuilt=rebuilt, log={
        "bytes_before": len(before), "bytes_after": len(after), "unchanged": before == after,
        "sha256_before": hashlib.sha256(before).hexdigest(), "sha256_after": hashlib.sha256(after).hexdigest()}))
    if os.path.exists(log):
        shutil.copyfile(log, os.path.join(rp.layout.out, "score-log.jsonl"))
