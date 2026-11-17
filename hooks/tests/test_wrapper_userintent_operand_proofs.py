#!/usr/bin/env python3
"""The /stop user-intent guard proves `-n` operands and reads computed values (OB-L38 round 6).

hooks/pretool-wrapper-userintent.py:
- passes `bash -n` / `sh -n` whose computed operand (a loop variable over a glob or an
  `$(ls ...)` list, `$(ls ...)`, `$(echo ...)`) can only start with a character other than
  `-` / `+`, so it is the script operand; refuses when a value can start an option (`+n`,
  `-i`, `--rcfile`), when a later `+n` / `+o noexec` undoes the check, or under BASH_ENV;
- evaluates `${x#..}`, `${x%..}`, `${x/../..}`, `${x^^}`, `${x,,}`, `${x:off:len}`,
  `${x:-..}` on the command's own literal assignments, and fails closed on an operator it
  cannot evaluate when the value is in or names the harness hooks/ dir;
- evaluates `$(readlink -f PATH)` / `$(realpath PATH)` on a literal path;
- reads a relative RIPGREP_CONFIG_PATH against the directories the command `cd`s into;
- reads `cat < FILE | make -f -` like `cat FILE`, and treats `include` / `-include` /
  `sinclude` under `make -n` as a run (GNU make remakes included makefiles under -n).
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
SID = "ob-l38-operands"

WRAPPER_TEXT = ("#!/usr/bin/env bash\n# the harness home's /stop release wrapper (test copy)\n"
                "exec python3 \"$(dirname \"$0\")/../scripts/break-overnight-lock.py\" \"$@\"\n")
HELPER_TEXT = ("# the harness home's isolation release helper (test copy)\n"
               "import sys\nprint('released', sys.argv[1:])\n")


@pytest.fixture()
def env(tmp_path):
    home = tmp_path / "home"
    harness = home / ".claude"
    (harness / "hooks").mkdir(parents=True)
    (harness / "scripts").mkdir(parents=True)
    (harness / "docs").mkdir(parents=True)
    wrapper = harness / "hooks" / "stop.sh"
    helper = harness / "scripts" / "break-overnight-lock.py"
    wrapper.write_text(WRAPPER_TEXT)
    helper.write_text(HELPER_TEXT)
    (harness / "hooks" / "other.sh").write_text("#!/usr/bin/env bash\necho other\n")
    (harness / "docs" / "notes.md").write_text("wrapper TODO\n")
    for f in (wrapper, helper):
        f.chmod(0o755)
    project = tmp_path / "project"
    (project / "docs").mkdir(parents=True)
    (project / "docs" / "a.md").write_text("hello\n")
    (project / "docs" / "run.sh").write_text("echo run\n")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "rcbash").write_text("--pre=bash\n")
    (scratch / "rcok").write_text("--smart-case\n")
    state = tmp_path / "state"
    state.mkdir()
    return {"home": home, "harness": harness, "project": project, "scratch": scratch,
            "state": state}


def _cwd(env, where):
    return {"P": env["project"], "H": env["harness"], "HK": env["harness"] / "hooks"}[where]


def _run(env, command, where="P"):
    command = command.replace("{S}", str(env["scratch"])).replace("{H}", str(env["harness"]))
    cwd = str(_cwd(env, where))
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": SID,
               "cwd": cwd}
    run_env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
    for name in ("RIPGREP_CONFIG_PATH", "GIT_PAGER", "PAGER", "LESSOPEN", "LESSCLOSE"):
        run_env.pop(name, None)
    run_env.update(HOME=str(env["home"]), CLAUDE_HOME=str(env["harness"]),
                   CLAUDE_STATE_DIR=str(env["state"]),
                   CLAUDE_USERINTENT_SENTINEL_DIR=str(env["state"]))
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, cwd=cwd, env=run_env, timeout=60)


def _sentinel(env):
    return env["state"] / f"claude-stop-userintent-{SID}.flag"


W = "~/.claude/hooks/stop.sh"

HARMLESS = [
    ("for f in ~/.claude/hooks/*.sh; do bash -n $f; done", "P"),
    ("for f in ~/.claude/hooks/*.sh; do sh -n $f; done", "P"),
    ("cd ~/.claude/hooks && for f in *.sh; do bash -n $f; done", "P"),
    ("for f in $(ls ~/.claude/hooks/*.sh); do bash -n $f; done", "P"),
    ("cd ~/.claude/hooks && bash -n $(ls *.sh)", "P"),
    ("bash -n $(echo ~/.claude/hooks/stop.sh)", "P"),
    ("bash -n \"$(echo ~/.claude/hooks/stop.sh)\"", "P"),
    ("for f in ~/.claude/hooks/*.sh; do bash -n \"$f\"; done", "P"),
    ("for f in ~/.claude/hooks/*.sh; do bash -n $f; done", "HK"),
    ("x=~/.claude/hooks/other.sh; bash \"${x%.sh}.sh\"", "P"),
    ("x=~/.claude/hooks/Stop.sh; bash -n \"${x,,}\"", "P"),
    ("x=$(readlink -f docs/run.sh); bash \"$x\"", "P"),
    ("cd {S} && RIPGREP_CONFIG_PATH=rcok rg x ~/.claude/hooks/stop.sh", "P"),
    ("cat < docs/a.md | make -f -", "P"),
    ("make -n -f - <<< $'all:\\n\\tbash ~/.claude/hooks/stop.sh'", "P"),
    ("make -n -f - <<< $'include x.mk\\nall:\\n\\techo hi'", "P"),
]

REFUSED = [
    # a computed operand that can start an option, or a -n undone
    ("for f in +n ~/.claude/hooks/stop.sh; do bash -n $f; done", "P"),
    ("f=\"+n ~/.claude/hooks/stop.sh\"; bash -n $f", "P"),
    ("f=\"-i ~/.claude/hooks/stop.sh\"; bash -n $f", "P"),
    ("f=\"--rcfile $HOME/.claude/hooks/stop.sh -i\"; bash -n $f", "P"),
    ("bash -n \"$(echo +n)\" ~/.claude/hooks/stop.sh", "P"),
    ("bash -n $(echo +n ~/.claude/hooks/stop.sh)", "P"),
    ("f=+n; bash -n \"$f\" ~/.claude/hooks/stop.sh", "P"),
    ("for f in ~/.claude/hooks/*.sh; do bash -n $f; bash $f; done", "P"),
    ("for f in ~/.claude/hooks/*.sh; do f=+n; bash -n $f ~/.claude/hooks/stop.sh; done", "P"),
    ("for f in ~/.claude/hooks/*.sh; do bash -n -o noexec +o noexec $f; done", "P"),
    ("for f in ~/.claude/hooks/*.sh; do BASH_ENV=$f bash -n $f; done", "P"),
    ("cd ~/.claude/hooks && bash -n +n $(ls *.sh)", "P"),
    ("cd ~/.claude/hooks && for f in *.sh; do bash -n $f; bash $f; done", "P"),
    ("cd {S} && for f in *; do bash -n $f ~/.claude/hooks/stop.sh; done", "P"),
    # parameter expansion operators on the command's own assignments
    ("x=~/.claude/hooks/stopx.sh; bash \"${x/x.sh/.sh}\"", "P"),
    ("x=~/.claude/hooks/STOP.sh; bash \"${x,,}\"", "P"),
    ("x=~/.claude/hooks/stop.shx; bash \"${x%x}\"", "P"),
    ("x=~/.claude/hooks/stop.shxx; bash ${x%%x*}", "P"),
    ("x=~/.claude/hooks/xstop.sh; bash \"${x/xstop/stop}\"", "P"),
    ("x=~/.claude/hooks/stopx; bash \"${x/%x/.sh}\"", "P"),
    ("x=/zz/.claude/hooks/stop.sh; bash \"$HOME${x#/zz}\"", "P"),
    ("x=~/.claude/hooks/stop.sh; bash \"${x:0:200}\"", "P"),
    ("bash \"${x:-$HOME/.claude/hooks/stop.sh}\"", "P"),
    ("x=~/.claude/hooks/stop.shx; bash \"${x@Q}\"", "P"),
    ("x=~/.claude/hooks/sto; bash \"${x//o/o}p.sh\"", "P"),
    # readlink -f / realpath of a literal path
    ("x=$(readlink -f {S}/sl2); bash \"$x\"", "P"),
    ("x=$(realpath {S}/sl2); bash \"$x\"", "P"),
    ("bash \"$(readlink -f {S}/sl1)\"", "P"),
    # a relative RIPGREP_CONFIG_PATH read after cd
    ("cd {S} && RIPGREP_CONFIG_PATH=rcbash rg x ~/.claude/hooks/stop.sh", "P"),
    ("cd {S}; RIPGREP_CONFIG_PATH=./rcbash rg x ~/.claude/hooks/stop.sh", "P"),
    ("cd {S} && RIPGREP_CONFIG_PATH=rcbash rg x", "P"),
    ("cd ~/.claude/hooks && RIPGREP_CONFIG_PATH=../../../scratch/rcbash rg x", "P"),
    ("cd {S} && export RIPGREP_CONFIG_PATH=rcbash && rg x ~/.claude/hooks/stop.sh", "P"),
    # make: cat < FILE, and include under -n
    ("cat < {S}/mkin | make -f -", "P"),
    ("make -n -f - <<< $'-include x.mk\\nx.mk:\\n\\tbash ~/.claude/hooks/stop.sh > /dev/null; touch x.mk\\nall:\\n\\techo hi'", "P"),
    ("make -n -f - <<< $'include x.mk\\nx.mk:\\n\\tbash ~/.claude/hooks/stop.sh; echo > x.mk\\nall: ; echo hi'", "P"),
    ("make -n -f - <<< $'sinclude x.mk\\nx.mk:\\n\\tbash ~/.claude/hooks/stop.sh\\nall: ; echo hi'", "P"),
]


@pytest.fixture()
def links(env):
    wrapper = env["harness"] / "hooks" / "stop.sh"
    s = env["scratch"]
    os.link(wrapper, s / "hl")
    (s / "sl1").symlink_to(s / "hl")
    (s / "sl2").symlink_to(s / "sl1")
    (s / "+n").write_text("")
    (s / "mkin").write_text("all:\n\tbash ~/.claude/hooks/stop.sh\n")
    return env


@pytest.mark.parametrize("command,where", HARMLESS)
def test_a_harmless_command_passes_and_keeps_the_sentinel(links, command, where):
    env = links
    _sentinel(env).write_text("true")
    proc = _run(env, command, where)
    assert proc.returncode == 0, proc.stderr
    assert _sentinel(env).exists(), "a harmless command consumed the single-use sentinel"


@pytest.mark.parametrize("command,where", REFUSED)
def test_a_run_is_refused(links, command, where):
    proc = _run(links, command, where)
    assert proc.returncode == 2, (proc.returncode, proc.stderr)


@pytest.mark.parametrize("command,where", REFUSED[:3] + REFUSED[14:16] + REFUSED[-4:-2])
def test_a_run_under_a_live_sentinel_passes_and_consumes_it(links, command, where):
    _sentinel(links).write_text("true")
    proc = _run(links, command, where)
    assert proc.returncode == 0, proc.stderr
    assert not _sentinel(links).exists()
