"""P6 A17 (P6-3): the base master's /dev -> /close -> /commit, its commit grant minted before the pull.

A driver for the BASE master's own replay framework, not for this tree's: the drivers here play this
tree's command text, and the base's /close and /commit text is the base's own drivers' to play
(tests/replay/test_live_landing_p6.py copies this file into the base tree's tests/replay/drivers/,
builds the sandbox with the base's framework and runs it there). It runs the base's drivers/commit.py
unchanged, with the base's landing.py (`land=before:agent:changelog-analyst Write MSGFILE 1`): Step 5
mints the grant with the base's writer, Step 6 plans and reviews, Step 7 dispatches the analyst, and
the harness home fast-forwards to the tree under test right before the analyst's message-file Write;
its lock, stage and commit Bash (the grant spent) and its push-gate token step follow on this tree's
hooks.

`hooklist=landed` (which the base's landing.py does not know) gives the session this tree's
settings.json from the landing on, as this tree's landing.py does (_reload): the hooks each later
event runs and the environment settings.json gives hooks and Bash calls. facts.json "hooklist"
records the environment keys that changed with it.
"""
from __future__ import annotations

import json
import os

from .. import hookrun, landing
from . import commit
from .close import fact

PIPELINE = commit.PIPELINE
_land = landing._land


def _reload(rp) -> dict:
    path = os.path.join(rp.layout.harness, "settings.json")
    with open(path) as fh:
        landed = json.load(fh)
    old, new = hookrun.settings_env(rp.settings), hookrun.settings_env(landed)
    changed = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
    rp.settings = landed
    fresh = rp._env({})
    for env in (rp.env, rp.bash_env):
        for k in changed:
            if k in fresh:
                env[k] = fresh[k]
            else:
                env.pop(k, None)
    return {"hooklist": "landed", "settings": path, "env_changed": changed}


def _land_and_reload(rp, label: str) -> None:
    _land(rp, label)
    if rp.args.get("hooklist") == "landed":
        with rp.acting("landing"):
            fact(rp, "hooklist", _reload(rp))


landing._land = _land_and_reload  # landing.install's hook looks the name up when it lands


def run(rp) -> None:
    commit.run(rp)
