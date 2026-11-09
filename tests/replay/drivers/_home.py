"""A session whose project is the harness home itself (P1c A11's pre-merge check in the harness home).

The owner's own session in ~/.claude: SessionStart, a read-only question about the harness, the main
agent's Grep, Read and `git status`, its answer and the Stop. It types no command: the /dev scenarios
(drivers/dev.py) edit the toy package, which the harness home does not hold, so the Stops of the harness
home are met here by a plain session. Outside the artifact check's driver set (a leading underscore).
"""
from __future__ import annotations

import os
import re

PIPELINE = "home"


def run(rp) -> None:
    lay = rp.layout
    lay.project = lay.harness  # the CLI runs in the harness home: hooks' cwd and CLAUDE_PROJECT_DIR
    rp.slug = re.sub(r"[^A-Za-z0-9]", "-", lay.project)
    rp.ids.add("slug", rp.slug)
    rp.env["CLAUDE_PROJECT_DIR"] = lay.project
    os.chdir(lay.project)
    s = rp.session()
    s.prompt("Which hook refuses a /dev-overnight session's Stop before end_time? Look; change nothing.",
             label="prompt")
    s.tool("Grep", {"pattern": "end_time", "path": f"{lay.project}/hooks", "output_mode": "files_with_matches"},
           label="main Grep")
    s.read(f"{lay.project}/hooks/stop-command-gate.py", label="main Read", limit=40)
    s.bash("git status --short", "Show working tree status", label="main Bash git-status")
    ev = s.stop("hooks/stop-command-gate.py refuses it (the time-lock, its step 4); nothing was changed.")
    rp.terminal("home", True, ev)
