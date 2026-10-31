"""/redev, played compliantly: /dev's flow under the /redev command text (commands/redev.md of the
tree under test; P1b D22: /redev is /dev when saving context, minted a fresh task id exactly as /dev).

commands/redev.md runs "the /dev workflow with the full command specification already loaded in
this conversation" and makes that its precondition ("If you cannot recall the /dev step semantics
from earlier turns, abort and ask the user to run /dev instead"). So the replay's one session holds
two typed commands, as a conversation that saves context does:

1. `/dev <requirement>`: a whole /dev cycle (drivers/dev.py DevCycle, variant plain), whose typed
   command puts commands/dev.md into the conversation;
2. `/redev <a new requirement>` in the same session: the hook mints a fresh task id and registry and
   hands /redev its checklist (checked against scripts/todo/redev.py), the isMeta body is /redev's
   text, and the main agent runs /dev's plain flow on commands/dev.md's steps, already in context
   (DevCycle again, its Orchestrator reading dev.md's steps and typing /redev). The new cycle reuses
   no prior task id, artifact path or acceptance criterion (redev.md's no-reuse rule): its
   requirement is another outcome (toy.util.sub's argument check) and its artifacts carry the id the
   hook printed for it.

Driver arguments (cli.py --arg K=V):
  prior=dev      the /dev cycle that puts its text into the conversation first (default)
  prior=none     /redev typed in a fresh session (redev.md's precondition then does not hold: a
                 quick check of the /redev cycle alone, not a compliant replay)
  tier=STANDARD  BA's complexity_tier, as for drivers/dev.py
  kept=<JSON>    as for drivers/dev.py: on a tree other than the base, a declared deviation passes
                 only a block the base kit's same replay recorded

Respellings and deviations are drivers/dev.py's (RESPELLINGS, DEVIATIONS): /redev runs the same
text. Both cycles record their blocks in the one blocks.json under the same step labels; cycles.json
in the run's out dir names each cycle's typed command, registry and task id, the half-open range of
blocks.json "blocks" it recorded, and whether the /redev cycle's ids are fresh (D22).
"""
from __future__ import annotations

import json
import os

from . import dev

PIPELINE = "redev"
# The artifact check's cost of this driver (tests/artifact_graph/shards.py balances its CI shards by it):
# CPU seconds of the shipped and armed traced replays and their differential runs, measured at b8e34f4
COST = 503


def run(rp) -> None:
    prior = rp.args.get("prior", "dev")
    if prior not in ("dev", "none"):
        raise ValueError(f"prior must be dev or none, not {prior!r}")
    tier = rp.args.get("tier", "STANDARD")
    rp.pipeline = "redev" if prior == "dev" else "redev/no-prior"
    cycles, session = [], None
    if prior == "dev":
        first = dev.DevCycle(rp, "plain", tier)
        first.run()
        session = first.o.s
        cycles.append({"typed": "/dev", "registry": first.reg, "task_id": first.tid, "blocks": [0, len(rp.blocks)]})
    start = len(rp.blocks)
    cyc = dev.DevCycle(rp, "plain", tier, scenario=dev.SCENARIO_SUB, typed="redev", session=session)
    try:
        cyc.run()
    finally:
        cycles.append({"typed": "/redev", "registry": cyc.reg, "task_id": cyc.tid,
                       "blocks": [start, len(rp.blocks)],
                       "fresh_ids": all(c["task_id"] not in ("", cyc.tid) and c["registry"] != cyc.reg
                                        for c in cycles)})
        with rp.acting("driver"):
            with open(os.path.join(rp.layout.out, "cycles.json"), "w") as fh:
                json.dump(cycles, fh, indent=1)
