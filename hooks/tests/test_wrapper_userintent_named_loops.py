#!/usr/bin/env python3
"""The /stop user-intent guard and the harness scripts the texts tell an agent to run.

hooks/pretool-wrapper-userintent.py protects one thing: the /stop release wrapper (the files
named in its _GUARDED_WRAPPERS) may run only after the owner typed /stop. A loop whose run
target is built from the command's own literal assignments and a loop list the guard reads in
full (`S=~/.claude/scripts; for s in detect-orphan-agents ...; do bash $S/$s.sh; done`) is
read as the runs it spells: it is refused when one of them is the wrapper, and passes when
none is. The cleanliness inspector ran such a loop over the detections its own text names and
was refused twice (the two RECORDED commands below, with neutral paths).

The standing test: every harness script a command or agent text tells an agent to run, run
the way the text shows it, passes the guard, unless it is a guarded wrapper itself; one
definition (_GUARDED_WRAPPERS) decides both.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "pretool-wrapper-userintent.py"
SID = "named-loops"

WRAPPER_TEXT = ("#!/usr/bin/env bash\n# the harness home's /stop release wrapper (test copy)\n"
                "exec python3 \"$(dirname \"$0\")/../scripts/break-overnight-lock.py\" \"$@\"\n")
HELPER_TEXT = ("# the harness home's isolation release helper (test copy)\n"
               "import sys\nprint('released', sys.argv[1:])\n")
DETECTIONS = ("detect-orphan-agents", "detect-orphan-scripts", "detect-orphan-commands",
              "detect-dead-functions", "detect-duplicate-content")


def _guarded():
    """The guard's own definition (_GUARDED_WRAPPERS), read from its source without running it."""
    for node in ast.parse(HOOK.read_text()).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "_GUARDED_WRAPPERS" for t in node.targets):
            return {rel for files in ast.literal_eval(node.value).values() for rel in files}
    raise AssertionError("_GUARDED_WRAPPERS not found in the guard")


# A command or agent text runs a harness script: a runner word (or none) and a path in the
# harness home's hooks/ or scripts/ directory.
_HOME_RE = (r'(?:\$\{CLAUDE_HOME:-\$HOME/\.claude\}|\$CLAUDE_HOME|\$\{CLAUDE_HOME\}|~/\.claude|\$HOME/\.claude'
            r'|<HARNESS_ROOT>)')
_RUN_RE = re.compile(r'^(?:(?:bash|sh|python3?|python3 -B)\s+)?"?' + _HOME_RE
                     + r'/(hooks|scripts)/([\w.-]+\.(?:sh|py))\b')


def _text_runs():
    """(source, command, (dir, name)) of every run of a harness script in commands/ and agents/."""
    out = []
    for md in sorted(list((REPO / "commands").glob("*.md")) + list((REPO / "agents").glob("*.md"))):
        text = md.read_text(errors="replace")
        spans = re.findall(r'`([^`\n]+)`', text)
        for block in re.findall(r'```(?:bash|sh)?\n(.*?)```', text, re.S):
            spans.extend(block.splitlines())
        for span in spans:
            span = span.strip()
            m = _RUN_RE.match(span)
            if m is None:
                continue
            # placeholders of the text (`<PROJECT_ROOT>`, `<ba|dev|qa>`) become one neutral word
            cmd = re.sub(r'<[^<>]*>', 'x', span.replace('<HARNESS_ROOT>', '{H}'))
            out.append((f"{md.parent.name}/{md.name}", cmd, (m.group(1), m.group(2))))
    return out


@pytest.fixture()
def env(tmp_path):
    home = tmp_path / "home"
    harness = home / ".claude"
    (harness / "hooks").mkdir(parents=True)
    (harness / "scripts").mkdir(parents=True)
    (harness / "hooks" / "stop.sh").write_text(WRAPPER_TEXT)
    (harness / "scripts" / "break-overnight-lock.py").write_text(HELPER_TEXT)
    for _src, _cmd, (d, name) in _text_runs():
        f = harness / d / name
        if not f.exists():
            f.write_text(f"# test stub of {d}/{name}\necho {name}\n")
    for name in DETECTIONS:
        f = harness / "scripts" / f"{name}.sh"
        if not f.exists():
            f.write_text(f"# test stub\necho {name}\n")
    project = tmp_path / "project"
    project.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    return {"home": home, "harness": harness, "project": project, "scratch": scratch, "state": state}


def _run(env, command):
    command = (command.replace("{H}", str(env["harness"])).replace("{P}", str(env["project"]))
               .replace("{X}", str(env["scratch"])))
    cwd = str(env["project"])
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": SID, "cwd": cwd}
    run_env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
    run_env.update(HOME=str(env["home"]), CLAUDE_HOME=str(env["harness"]),
                   CLAUDE_STATE_DIR=str(env["state"]), CLAUDE_USERINTENT_SENTINEL_DIR=str(env["state"]),
                   PROJECT_ROOT=cwd)
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, cwd=cwd, env=run_env, timeout=60)


def _refused(r) -> bool:
    return r.returncode == 2 or "USER-INTENT GUARD" in (r.stdout + r.stderr)


_LIST = " ".join(DETECTIONS)

# The two calls of 2026-11-21 (11:49:23 and 11:56:58), paths made neutral.
RECORDED = [
    ("cd {P}; S={H}/scripts; export PYTHONDONTWRITEBYTECODE=1; for s in " + _LIST + "; do echo \"=== $s\"; "
     "out=$(timeout 100 bash $S/$s.sh {P} 2>/dev/null); echo \"exit=$? bytes=${#out}\"; echo \"$out\" | head -c 300; "
     "echo; echo \"-- cycle hits:\"; echo \"$out\" | grep -nE 'lane_c_paths|layout_budget' | head -10; done; "
     "git status --porcelain | wc -l"),
    ("export PYTHONDONTWRITEBYTECODE=1 CLAUDE_HOME={H}; S=$CLAUDE_HOME/scripts; P={P}; for s in " + _LIST + "; "
     "do out=$(timeout 100 bash $S/$s.sh $P 2>&1); rc=$?; echo \"== $s rc=$rc bytes=${#out} "
     "cyclehits=$(printf '%s' \"$out\" | grep -cE 'lane_d_paths|do-report')\"; printf '%s' \"$out\" | head -c 500; "
     "echo; printf '%s' \"$out\" | grep -E 'lane_d_paths|do-report' | head -5; done"),
]

# The wrapper inside such a loop, behind a variable, is still refused.
PROTECTED = [
    "S={H}/scripts; for s in detect-orphan-agents break-overnight-lock; do python3 $S/$s.py; done",
    "H={H}/hooks; for s in detect-orphan-agents stop; do out=$(bash $H/$s.sh); done",
    "export CLAUDE_HOME={H}; S=$CLAUDE_HOME/hooks; for s in stop; do bash $S/$s.sh; done",
    "S={H}/scripts; S={H}/hooks; for s in stop; do bash $S/$s.sh; done",
    "S={X}; for s in stop; do bash $S/$s.sh; done",
    "cp {H}/hooks/stop.sh {X}/a.sh; S={X}; for s in a; do bash $S/$s.sh; done",
    "ln {H}/hooks/stop.sh {X}/b.sh; S={X}; for s in b; do bash $S/$s.sh; done",
    "S=$(echo {H}/hooks); for s in a b; do bash $S/$s.sh; done",
    "S={H}/hooks; S+=/x; for s in a; do bash $S/$s.sh; done",
    "S={H}/hooks; read S; for s in a; do bash $S/$s.sh; done",
]


@pytest.mark.parametrize("command", RECORDED)
def test_recorded_inspector_loop_passes(env, command):
    r = _run(env, command)
    assert not _refused(r), r.stdout + r.stderr


@pytest.mark.parametrize("command", PROTECTED)
def test_wrapper_in_a_loop_behind_a_variable_is_refused(env, command):
    r = _run(env, command)
    assert _refused(r), r.stdout + r.stderr


def test_texts_name_runs():
    runs = _text_runs()
    names = {name for _s, _c, (_d, name) in runs}
    assert set(f"{n}.sh" for n in DETECTIONS) <= names, sorted(names)
    assert any(rel in _guarded() for _s, _c, rel in runs), "no text run of a guarded wrapper found"


def test_every_script_a_text_tells_an_agent_to_run_passes(env):
    """Requirement and permission by one definition: a text's run of a harness script passes,
    unless the script is a guarded wrapper (which only the owner's /stop may start)."""
    guarded = _guarded()
    wrong = []
    for src, cmd, rel in _text_runs():
        r = _run(env, cmd)
        if _refused(r) != (rel in guarded):
            wrong.append(f"{src}: {cmd}: refused={_refused(r)}: {(r.stdout + r.stderr)[:200]}")
    assert not wrong, "\n".join(wrong)
