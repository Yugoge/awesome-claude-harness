#!/usr/bin/env python3
"""The /stop guard refuses a run it cannot read only where the wrapper's name can become that run.

Two recorded refusals: a for loop whose script name is computed from the loop variable, every value
written out in the list (`for c in dev close ...; do python3 -B scripts/todo/$c.py ...; done`, run in
the harness home), and a read-only inspection that names a harness hook that is not the wrapper in a
loop list it cannot fully read. Neither names break-overnight-lock.py or stop.sh. The first is
resolved to the list's values (none is the wrapper); the second runs and goes to the refusal record
as let through unproven. The controls still refuse: the wrapper run directly, through a shell or
python, through a variable assigned its path, through a for list that holds it, through xargs or
find -exec, and through text handed to eval; a run target computed in the wrapper's directory that
the guard cannot resolve is refused with what it could not resolve, not as a "direct invocation".
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "pretool-wrapper-userintent.py"
SID = "unread-names-session"


@pytest.fixture()
def env(tmp_path):
    home = tmp_path / "home"
    harness = home / ".claude"
    for d in ("hooks", "scripts/todo"):
        (harness / d).mkdir(parents=True)
    (harness / "hooks" / "stop.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    (harness / "scripts" / "break-overnight-lock.py").write_text("print('x')\n")
    (harness / "hooks" / "session-gitignore-propagate.sh").write_text("#!/usr/bin/env bash\nRUNTIME_DIRS=1\n")
    for name in ("dev", "close", "spec"):
        (harness / "scripts" / "todo" / f"{name}.py").write_text("print('[]')\n")
    project = tmp_path / "project"
    (project / "docs").mkdir(parents=True)
    (project / "docs" / "a.json").write_text("{}\n")
    state = tmp_path / "state"
    state.mkdir()
    return {"home": home, "harness": harness, "project": project, "state": state}


def _run(env, command, cwd=None):
    cwd = str(cwd or env["project"])
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": SID, "cwd": cwd,
               "hook_event_name": "PreToolUse"}
    run_env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
    run_env.update(HOME=str(env["home"]), CLAUDE_HOME=str(env["harness"]), CLAUDE_STATE_DIR=str(env["state"]),
                   CLAUDE_USERINTENT_SENTINEL_DIR=str(env["state"]))
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, cwd=cwd, env=run_env, timeout=60)


TODO_LOOP = ("for c in dev close spec; do PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/todo/$c.py 2>/dev/null"
             " | python3 -B -c \"import json,sys; print('$c', len(json.load(sys.stdin)))\"; done; ls scripts/todo/")

INSPECTION = ('H="${CLAUDE_HOME:-$HOME/.claude}"; for f in "$H/hooks/session-gitignore-propagate.sh" '
              '"$HOME/.claude/hooks/session-gitignore-propagate.sh"; do [ -f "$f" ] && '
              '{ echo "$f: $(grep -c RUNTIME_DIRS "$f")"; } || echo "absent $f"; done; '
              'for f in docs/a.json; do m=$(md5sum "$f" | cut -d" " -f1); s=$(stat -c %s "$f"); '
              'echo "$f $m dupes: $(find docs -type f -size ${s}c ! -path "./$f" | xargs -r md5sum | grep -c "$m")"; done')


def test_a_script_name_from_a_written_out_loop_list_is_resolved(env):
    r = _run(env, TODO_LOOP, cwd=env["harness"])
    assert r.returncode == 0, r.stderr


def test_an_inspection_that_cannot_become_the_wrapper_runs_and_is_recorded_unproven(env):
    r = _run(env, INSPECTION)
    assert r.returncode == 0, r.stderr
    records = list((env["home"] / ".local" / "state" / "claude-harness").rglob("refusals-*.jsonl"))
    lines = [json.loads(x) for f in records for x in f.read_text().splitlines() if x.strip()]
    assert any("let through unproven" in json.dumps(x) for x in lines), lines


@pytest.mark.parametrize("command", [
    "bash {H}/hooks/stop.sh",
    "python3 {H}/scripts/break-overnight-lock.py",
    "p={H}/hooks/stop.sh; bash \"$p\"",
    "for f in {H}/hooks/session-gitignore-propagate.sh {H}/hooks/stop.sh; do bash \"$f\"; done",
    "for c in dev stop; do bash {H}/hooks/$c.sh; done",
    "echo {H}/hooks/stop.sh | xargs bash",
    "find {H}/hooks -name stop.sh -exec bash {{}} \\;",
    "eval \"bash {H}/hooks/stop.sh\"",
])
def test_a_real_run_of_the_wrapper_is_still_refused(env, command):
    r = _run(env, command.format(H=env["harness"]))
    assert r.returncode == 2, (command, r.stderr)


def test_an_unresolved_run_in_the_wrappers_directory_says_what_it_could_not_resolve(env):
    r = _run(env, "bash {H}/hooks/$n.sh".format(H=env["harness"]))
    assert r.returncode == 2
    assert "direct invocation" not in r.stderr and "could not resolve" in r.stderr, r.stderr
