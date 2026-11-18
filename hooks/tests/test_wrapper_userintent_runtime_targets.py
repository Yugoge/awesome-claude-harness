#!/usr/bin/env python3
"""The /stop user-intent guard reads runs that hide behind run-time names (OB-L38 round 4).

hooks/pretool-wrapper-userintent.py treats as a run of the harness home's wrapper:
- rg under a RIPGREP_CONFIG_PATH the command sets (prefix, export, declare -x, env, or a
  config written in the same command): the config file is read for `--pre` /
  `--hostname-bin`; one it cannot read fails closed when rg searches the wrapper or runs
  in or names the harness hooks/ or scripts/ directory;
- a run target (command word, shell or interpreter script operand, source operand) whose
  literal part names the harness hooks/ or scripts/ directory or a wrapper basename but
  which also has a computed part (`~/.claude/hooks/$n.sh`, `$(echo $HOME)/.claude/...`);
- an array assignment read like a loop list (`a=(~/.claude/hooks/*); bash "${a[0]}"`);
- `git grep -O<prog>` / `--open-files-in-pager` (and its unique prefixes) in the harness
  home or over the wrapper;
- make with a makefile read from stdin (`-f -`, `-f /dev/stdin`, a heredoc or here-string)
  or written in the same command whose recipe names the wrapper, or that cannot be read.
Harmless reads still pass and keep the sentinel.
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
SID = "ob-l38-runtime"

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
    wrapper = harness / "hooks" / "stop.sh"
    helper = harness / "scripts" / "break-overnight-lock.py"
    wrapper.write_text(WRAPPER_TEXT)
    helper.write_text(HELPER_TEXT)
    (harness / "hooks" / "other.sh").write_text("#!/usr/bin/env bash\necho other\n")
    for f in (wrapper, helper):
        f.chmod(0o755)
    (home / "plist").write_text(str(wrapper) + "\n")
    project = tmp_path / "project"
    (project / "docs").mkdir(parents=True)
    (project / "docs" / "a.md").write_text("hello\n")
    (project / "docs" / "run.sh").write_text("echo run\n")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "rcbash").write_text("--pre=bash\n")
    (scratch / "rcsplit").write_text("# a comment\n--pre\nbash\n")
    (scratch / "rcw").write_text(f"--pre={wrapper}\n")
    (scratch / "rchost").write_text(f"--hostname-bin={wrapper}\n")
    (scratch / "rcplain").write_text("--smart-case\n--pre-glob=*.pdf\n")
    (scratch / "mkw").write_text(f"all:\n\tbash {wrapper}\n")
    (scratch / "mkok").write_text("all:\n\techo hi\n")
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
    run_env.pop("RIPGREP_CONFIG_PATH", None)
    run_env.update(HOME=str(env["home"]), CLAUDE_HOME=str(env["harness"]),
                   CLAUDE_STATE_DIR=str(env["state"]),
                   CLAUDE_USERINTENT_SENTINEL_DIR=str(env["state"]))
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, cwd=cwd, env=run_env, timeout=60)


def _sentinel(env):
    return env["state"] / f"claude-stop-userintent-{SID}.flag"


W = "~/.claude/hooks/stop.sh"

RG_CONFIG = [
    (f"RIPGREP_CONFIG_PATH={{S}}/rcbash rg x {W}", "P"),
    ("RIPGREP_CONFIG_PATH={S}/rcw rg x docs/", "P"),
    ("RIPGREP_CONFIG_PATH={S}/rchost rg x docs/", "P"),
    (f"export RIPGREP_CONFIG_PATH={{S}}/rcbash; rg x {W}", "P"),
    (f"export RIPGREP_CONFIG_PATH={{S}}/rcbash && rg -n x {W}", "P"),
    ("declare -x RIPGREP_CONFIG_PATH={S}/rcbash; rg x ~/.claude/", "P"),
    (f"env RIPGREP_CONFIG_PATH={{S}}/rcbash rg x {W}", "P"),
    (f"RIPGREP_CONFIG_PATH='{{S}}/rcsplit' rg x {W}", "P"),
    ("RIPGREP_CONFIG_PATH={S}/rcbash rg x ~/.claude/hooks/", "P"),
    ("RIPGREP_CONFIG_PATH={S}/rcbash rg x", "HK"),
    (f"printf -- '--pre=bash\\n' > {{S}}/rc3; RIPGREP_CONFIG_PATH={{S}}/rc3 rg x {W}", "P"),
    (f"RIPGREP_CONFIG_PATH=$(echo {{S}}/rcbash) rg x {W}", "P"),
    ("RIPGREP_CONFIG_PATH=$(echo {S}/rcbash) rg x", "HK"),
    (f"timeout 5 env RIPGREP_CONFIG_PATH={{S}}/rcbash rg x {W}", "P"),
]

COMPUTED_TARGETS = [
    ("n=stop; bash ~/.claude/hooks/$n.sh", "P"),
    ("bash ~/.claude/hooks/$(echo stop).sh", "P"),
    ("bash $(echo $HOME)/.claude/hooks/stop.sh", "P"),
    ("bash $(eval echo '~')/.claude/hooks/stop.sh", "P"),
    ("bash $(dirname ~/plist)/.claude/hooks/stop.sh", "P"),
    ("bash \"$(echo $HOME)/.claude/hooks/stop.sh\"", "P"),
    ("n=stop; ~/.claude/hooks/$n.sh", "P"),
    ("$(echo ~)/.claude/hooks/stop.sh", "P"),
    ("n=stop; source ~/.claude/hooks/$n.sh", "P"),
    ("n=stop; . ~/.claude/hooks/$n.sh", "P"),
    ("n=break-overnight-lock; python3 ~/.claude/scripts/$n.py", "P"),
    ("python3 $(echo $HOME)/.claude/scripts/break-overnight-lock.py", "P"),
    ("n=stop; sh -e ~/.claude/hooks/${n}.sh", "P"),
    ("n=stop; env bash ~/.claude/hooks/$n.sh", "P"),
    ("bash $X/stop.sh", "P"),
    ("bash ~/.claude/hooks/`echo stop`.sh", "P"),
]

ARRAYS = [
    ("a=(~/.claude/hooks/*); bash \"${a[0]}\"", "P"),
    ("a=(~/.claude/hooks/stop*); bash \"${a[0]}\"", "P"),
    ("a=(~/.claude/hooks/s*p.sh); \"${a[@]}\"", "P"),
    ("a=(docs/a.md ~/.claude/hooks/stop.sh); bash \"${a[1]}\"", "P"),
    ("a=(*); bash \"${a[2]}\"", "HK"),
    ("a=(~/.claude/hooks/*); for x in \"${a[@]}\"; do bash \"$x\"; done", "P"),
    ("a+=(~/.claude/hooks/stop.sh); bash ${a[-1]}", "P"),
]

GIT_GREP = [
    ("git -C ~/.claude grep -O'bash' wrapper -- hooks/stop.sh", "P"),
    ("git -C ~/.claude grep -Obash x", "P"),
    ("git -C {H} grep -iObash x", "P"),
    ("git grep -Obash x", "H"),
    ("git grep --open-files-in-pager=bash x", "H"),
    ("git grep --open=bash x", "H"),
    ("git grep --op=bash x", "H"),
    ("git grep -Obash x -- ~/.claude/hooks/stop.sh", "P"),
]

MAKE = [
    ("make -f /dev/stdin <<< $'all:\\n\\tbash ~/.claude/hooks/stop.sh'", "P"),
    ("make -f - <<'EOF'\nall:\n\tbash ~/.claude/hooks/stop.sh\nEOF", "P"),
    ("make --file=/dev/stdin <<< $'all:\\n\\tbash ~/.claude/hooks/stop.sh'", "P"),
    ("make -f/dev/stdin <<< $'all:\\n\\tbash ~/.claude/hooks/stop.sh'", "P"),
    ("gmake --makefile - <<< $'all:\\n\\tsh ~/.claude/hooks/stop.sh'", "P"),
    ("make -s -f - <<< $'all:\\n\\t~/.claude/hooks/st\\\\\\nop.sh'", "P"),
    ("make -f - < {S}/mkw", "P"),
    ("cat {S}/mkw | make -f -", "P"),
    ("make -f \"$(echo /dev/stdin)\" <<< x", "P"),
    ("printf 'all:\\n\\tbash ~/.claude/hooks/stop.sh\\n' > {S}/mk; make -f {S}/mk", "P"),
    ("cp {S}/mkw {S}/mk4 && make -f {S}/mk4", "P"),
    ("make -C /tmp -f /dev/stdin <<< $'all:\\n\\tbash ~/.claude/hooks/stop.sh'", "P"),
    ("printf 'all:\\n\\tbash ~/.claude/hooks/stop.sh\\n' > Makefile && make", "P"),
    ("cp {S}/mkw makefile; make all", "P"),
]

PARALLEL = [
    (f"parallel ::: {W}", "P"),
    (f"parallel -j2 ::: {W}", "P"),
    ("parallel ::: 'bash ~/.claude/hooks/stop.sh'", "P"),
]

RUNS = RG_CONFIG + COMPUTED_TARGETS + ARRAYS + GIT_GREP + MAKE + PARALLEL


@pytest.mark.parametrize("command,where", RUNS)
def test_a_run_behind_a_run_time_name_is_refused(env, command, where):
    proc = _run(env, command, where)
    assert proc.returncode == 2, (proc.returncode, proc.stderr)
    assert "USER-INTENT GUARD" in proc.stderr


@pytest.mark.parametrize("command,where", [RG_CONFIG[0], COMPUTED_TARGETS[0], ARRAYS[0],
                                           GIT_GREP[0], MAKE[0]])
def test_a_run_under_a_live_sentinel_passes_and_consumes_it(env, command, where):
    _sentinel(env).write_text("true")
    proc = _run(env, command, where)
    assert proc.returncode == 0, proc.stderr
    assert not _sentinel(env).exists()


HARMLESS = [
    (f"RIPGREP_CONFIG_PATH={{S}}/rcplain rg x {W}", "P"),
    ("RIPGREP_CONFIG_PATH={S}/rcbash rg x docs/", "P"),
    (f"RIPGREP_CONFIG_PATH={{S}}/rcbash rg --no-config x {W}", "P"),
    ("RIPGREP_CONFIG_PATH={S}/missing rg x docs/", "P"),
    # round 5: a config that does not exist runs no program (was pinned as refused)
    (f"RIPGREP_CONFIG_PATH={{S}}/missing rg x {W}", "P"),
    ("export RIPGREP_CONFIG_PATH={S}/rcplain; rg -n stop.sh ~/.claude/hooks/", "P"),
    ("rg -n stop.sh ~/.claude/hooks/", "P"),
    ("cat ~/.claude/hooks/$n.sh", "P"),
    ("ls $(echo $HOME)/.claude/hooks/stop.sh", "P"),
    ("grep -n exec $(echo $HOME)/.claude/hooks/stop.sh", "P"),
    ("bash $(pwd)/docs/run.sh", "P"),
    ("n=run; bash docs/$n.sh", "P"),
    ("echo ~/.claude/hooks/$n.sh", "P"),
    ("a=(~/.claude/hooks/*); ls \"${a[@]}\"", "P"),
    ("a=(~/.claude/hooks/*); echo \"${a[0]}\"", "P"),
    ("a=(~/.claude/hooks/*.sh); for f in \"${a[@]}\"; do bash -n \"$f\"; done", "P"),
    ("a=(docs/*.sh); bash \"${a[0]}\"", "P"),
    ("a=(x y); echo ${#a[@]}", "P"),
    ("git -C ~/.claude grep -n stop.sh", "P"),
    ("git -C ~/.claude grep --only-matching stop", "P"),
    ("git -C ~/.claude grep --or -e x -e y", "P"),
    ("git grep -Obash x", "P"),
    # round 5: -O with no program opens the files in less (was pinned as refused)
    ("git grep --open-files-in-pager bash", "HK"),
    ("cd ~/.claude && git grep -O x", "P"),
    ("git -C ~/.claude log -1 --oneline", "P"),
    ("make -f /dev/stdin <<< $'all:\\n\\techo hi'", "P"),
    ("make -f - < {S}/mkok", "P"),
    ("printf 'all:\\n\\techo hi\\n' > {S}/mk2; make -f {S}/mk2", "P"),
    ("make -n test", "P"),
    ("make -C docs", "P"),
    ("make -f {S}/mkok", "P"),
    ("printf 'all:\\n\\techo hi\\n' > Makefile && make", "P"),
    ("parallel echo ::: a b", "P"),
    (f"parallel wc -l ::: {W}", "P"),
    ("parallel ::: 'echo a' 'echo b'", "P"),
]


@pytest.mark.parametrize("command,where", HARMLESS)
def test_a_harmless_command_passes_and_keeps_the_sentinel(env, command, where):
    assert _run(env, command, where).returncode == 0
    _sentinel(env).write_text("true")
    proc = _run(env, command, where)
    assert proc.returncode == 0, proc.stderr
    assert _sentinel(env).exists(), "a harmless command consumed the single-use sentinel"


# /commit Phase 3 evals the session-index emitter's output (shell assignments): naming that harness
# script is no wrapper context, so the eval passes as on the base; any other harness script's eval'd
# output still fails closed, and a computed run beside the wrapper stays refused.
COMMIT_EMITTER = 'eval "$(python3 ~/.claude/scripts/session-index.py init --git-root "${GIT_ROOT}")" || exit 1'


def test_commit_phase3_session_index_eval_passes(env):
    (env["harness"] / "scripts" / "session-index.py").write_text("print('export GIT_INDEX_FILE=/tmp/i')\n")
    proc = _run(env, COMMIT_EMITTER, "P")
    assert proc.returncode == 0, (proc.returncode, proc.stderr)


def test_eval_of_another_harness_script_still_fails_closed(env):
    (env["harness"] / "scripts" / "emit.py").write_text("print('true')\n")
    proc = _run(env, 'eval "$(python3 ~/.claude/scripts/emit.py)"', "P")
    assert proc.returncode == 2 and "USER-INTENT GUARD" in proc.stderr, (proc.returncode, proc.stderr)
