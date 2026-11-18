#!/usr/bin/env python3
"""The /stop user-intent guard reads computed parts without refusing reads (OB-L38 round 5).

hooks/pretool-wrapper-userintent.py:
- passes a `-n` syntax check whose operand starts with a literal (`bash -n ~/.claude/hooks/$n.sh`);
- passes a makefile piped or redirected into make unless the command names the wrapper or
  the harness hooks/ or scripts/ dir, or runs in the harness home; passes `make -n` unless a
  line still runs (`+`, $(MAKE), $(shell ...), `!=`);
- passes `git grep -O` with no program or with less / more / cat; refuses a computed -O
  program (`-O$p`, -O`...`, `-O"$(...)"`) in the harness home, and a GIT_PAGER / PAGER /
  core.pager the command sets to something else;
- passes rg under a RIPGREP_CONFIG_PATH that does not exist or holds no --pre /
  --hostname-bin; refuses rg reached through find -exec under a config with --pre;
- reads a run target with the command's own literal assignments and `$(echo ...)`
  substituted (`h=~/.claude/hooks/stop; bash $h.sh`), and fails closed on one whose readable
  parts are consistent with a wrapper path in the harness hooks/ or scripts/ dir;
- refuses a make recipe (stdin or same-command makefile) naming the harness hooks/ dir with
  a computed part, and `SHELL=<wrapper>` as a make argument or in --eval.
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
SID = "ob-l38-computed"

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

# -- harmless: refused by round 4, passing on the base ---------------------------------
SYNTAX_CHECKS = [
    ("n=stop; bash -n ~/.claude/hooks/$n.sh", "P"),
    ("n=stop; sh -n ~/.claude/hooks/$n.sh", "P"),
    ("bash -n ~/.claude/hooks/$(echo stop).sh", "P"),
    ("bash -n ~/.claude/hooks/`echo stop`.sh", "P"),
    ("n=stop; bash -n ~/.claude/hooks/${n}.sh", "P"),
    ("for n in stop other; do bash -n ~/.claude/hooks/$n.sh; done", "P"),
]

MAKE_HARMLESS = [
    ("printf 'all:\\n\\techo hi\\n' | make -f -", "P"),
    ("echo 'all: ; @echo hi' | make -f -", "P"),
    ("make -f - < docs/a.md", "P"),
    ("cat docs/a.md | make -f /dev/stdin", "P"),
    ("make -n -f - <<< $'all:\\n\\techo hi'", "P"),
    ("make -n -f - <<< $'all:\\n\\tbash ~/.claude/hooks/stop.sh'", "P"),
    ("make --dry-run -f - N=stop <<< $'all:\\n\\tbash ~/.claude/hooks/$(N).sh'", "P"),
    ("make --just-print -f - <<< $'all:\\n\\tbash ~/.claude/hooks/stop.sh'", "P"),
    ("make --recon -f - <<< $'all:\\n\\tbash ~/.claude/hooks/stop.sh'", "P"),
    ("make -sn -f - <<< $'all:\\n\\tbash ~/.claude/hooks/stop.sh'", "P"),
    ("make -f - <<< $'all:\\n\\tls ~/.claude/hooks/'", "P"),
]

GIT_GREP_HARMLESS = [
    ("cd ~/.claude && git grep -O TODO", "P"),
    ("git -C ~/.claude grep -O wrapper", "P"),
    ("git -C ~/.claude grep -O wrapper -- docs", "P"),
    ("git -C ~/.claude grep -Oless wrapper", "P"),
    ("git -C ~/.claude grep -Omore wrapper", "P"),
    ("git -C ~/.claude grep -Ocat wrapper", "P"),
    ("git -C ~/.claude grep --open-files-in-pager=less wrapper", "P"),
    ("git -C ~/.claude grep -O'less -R' wrapper", "P"),
    ("git grep -O TODO", "H"),
    ("git grep --open-files-in-pager bash", "HK"),
    ("GIT_PAGER=less git -C ~/.claude grep -O wrapper", "P"),
    ("git -C ~/.claude grep -Oless x -- hooks/stop.sh", "P"),
    ("git -C ~/.claude grep -O wrapper -- hooks/stop.sh", "P"),
    ("git -C ~/.claude -c pager.grep=true grep -O wrapper -- hooks/stop.sh", "P"),
    ("git -C ~/.claude config --get core.pager; git -C ~/.claude grep -O wrapper", "P"),
]

RG_HARMLESS = [
    ("RIPGREP_CONFIG_PATH=~/.ripgreprc rg -n stop.sh docs/", "P"),
    ("RIPGREP_CONFIG_PATH=$HOME/.config/rg/rc rg -n \"stop.sh\" .", "P"),
    ("RIPGREP_CONFIG_PATH=/nonexistent rg -n stop.sh docs/", "P"),
    (f"RIPGREP_CONFIG_PATH={{S}}/rcok rg -n stop {W}", "P"),
    (f"printf -- '--smart-case\\n' > {{S}}/x_rc_ok; RIPGREP_CONFIG_PATH={{S}}/rcok rg -n stop {W}",
     "P"),
    (f"RIPGREP_CONFIG_PATH=/nonexistent rg -n stop {W}", "P"),
    ("RIPGREP_CONFIG_PATH={S}/missing rg x ~/.claude/hooks/", "P"),
    ("RIPGREP_CONFIG_PATH=/nonexistent rg -n stop", "HK"),
    ("RIPGREP_CONFIG_PATH={S}/rcok find ~/.claude/hooks -exec rg x {} +", "P"),
    ("RIPGREP_CONFIG_PATH={S}/rcbash find ~/.claude/hooks -exec rg --no-config x {} +", "P"),
    ("RIPGREP_CONFIG_PATH={S}/rcbash find docs -exec rg x {} +", "P"),
]

OTHER_HARMLESS = [
    ("n=run; bash docs/$n.sh", "P"),
    ("bash docs/$n.sh", "P"),
    ("h=docs; bash $h/run.sh", "P"),
    ("h=~/.claude/hooks/stop; cat $h.sh", "P"),
    ("h=~/.claude/hooks/other; bash $h.sh", "P"),
    ("bash $(echo docs)/run.sh", "P"),
    ("bash $(pwd)/docs/run.sh", "P"),
]

HARMLESS = SYNTAX_CHECKS + MAKE_HARMLESS + GIT_GREP_HARMLESS + RG_HARMLESS + OTHER_HARMLESS


@pytest.mark.parametrize("command,where", HARMLESS)
def test_a_harmless_command_passes_and_keeps_the_sentinel(env, command, where):
    assert _run(env, command, where).returncode == 0
    _sentinel(env).write_text("true")
    proc = _run(env, command, where)
    assert proc.returncode == 0, proc.stderr
    assert _sentinel(env).exists(), "a harmless command consumed the single-use sentinel"


# -- runs: passing on round 4 ------------------------------------------------------------
GIT_GREP_RUNS = [
    ("p=bash; git -C ~/.claude grep -O$p wrapper", "P"),
    ("git -C ~/.claude grep -O`echo bash` wrapper", "P"),
    ("git -C ~/.claude grep -O\"$(echo bash)\" wrapper", "P"),
    ("p=bash; git -C ~/.claude grep --open-files-in-pager=$p wrapper", "P"),
    ("p=bash; git -C ~/.claude grep -iO\"$p\" wrapper", "P"),
    ("p=bash; cd ~/.claude && git grep -O$p wrapper", "P"),
    ("git grep -O$p wrapper", "H"),
    ("GIT_PAGER=bash git -C ~/.claude grep -O wrapper", "P"),
    ("git -c core.pager=bash -C ~/.claude grep -O wrapper", "P"),
    ("export PAGER=bash; git -C ~/.claude grep -O wrapper", "P"),
    ("LESSOPEN='|bash %s' git -C ~/.claude grep -Oless wrapper", "P"),
    ("git -C ~/.claude grep -O'less;bash' wrapper", "P"),
    ("git grep -O$(echo ~/.claude/hooks/stop.sh) x", "P"),
    ("git -C ~/.claude -c pager.grep=bash grep -O wrapper -- hooks/stop.sh", "P"),
    ("git -C ~/.claude config core.pager bash; git -C ~/.claude grep -O wrapper", "P"),
    ("echo '[core] pager = bash' >> ~/.claude/.git/config; git -C ~/.claude grep -O wrapper", "P"),
    ("GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.pager GIT_CONFIG_VALUE_0=bash "
     "git -C ~/.claude grep -O wrapper", "P"),
]

TARGET_RUNS = [
    ("h=~/.claude/hooks/stop; bash $h.sh", "P"),
    ("p=~/.claude/hooks/; f=stop; bash $p$f.sh", "P"),
    ("h=~/.claude/hooks; bash $h/$(echo stop).sh", "P"),
    ("d=hooks; t=top; bash ~/.claude/$d/s$t.sh", "P"),
    ("bash $(echo ~/.claude)/$(echo hooks/stop.sh)", "P"),
    ("export h=~/.claude/hooks/stop; bash \"$h.sh\"", "P"),
    ("h=~/.claude/hooks/stop; source ${h}.sh", "P"),
    ("h=~/.claude/hooks/stop; . $h.sh", "P"),
    ("h=~/.claude/hooks/stop; $h.sh", "P"),
    ("h=~/.claude/hooks/stop; env bash $h.sh", "P"),
    ("h=~/.claude/hooks/stop; timeout 5 bash $h.sh", "P"),
    ("s=~/.claude/scripts; python3 $s/break-overnight-lock.py", "P"),
    ("h=$HOME/.claude/hooks; bash $h/st`echo op`.sh", "P"),
    ("h=~/.claude/hooks; bash $h/$(cat /tmp/x)", "P"),
    ("bash $(echo ~/.claude)/hooks/$(cat /tmp/x)", "P"),
    ("bash -c 'h=~/.claude/hooks/stop; bash $h.sh'", "P"),
    ("h=hooks/stop; bash $h.sh", "H"),
]

MAKE_RUNS = [
    ("make -f - N=stop <<< $'all:\\n\\tbash ~/.claude/hooks/$(N).sh'", "P"),
    ("make -f - <<< $'all:\\n\\tbash ~/.claude/hooks/st$$(echo op).sh'", "P"),
    ("make -f - P=p <<< $'all:\\n\\t$(SHELL) ~/.claude/hooks/sto$(P).sh'", "P"),
    ("make SHELL=$HOME/.claude/hooks/stop.sh -f - <<< $'all:\\n\\techo hi'", "P"),
    ("make --eval=SHELL=$HOME/.claude/hooks/stop.sh -f - <<< $'all:\\n\\techo hi'", "P"),
    ("make -E 'SHELL=~/.claude/hooks/stop.sh' -f - <<< $'all:\\n\\techo hi'", "P"),
    (f"make SHELL={W} all", "P"),
    ("make -f - N=stop <<'EOF'\nall:\n\tbash ~/.claude/hooks/$(N).sh\nEOF", "P"),
    ("printf 'all:\\n\\tbash ~/.claude/hooks/$(N).sh\\n' | make -f - N=stop", "P"),
    ("printf 'all:\\n\\tbash hooks/$(N).sh\\n' | make -f - N=stop", "H"),
    ("make -n -f - <<< $'all:\\n\\t+bash ~/.claude/hooks/stop.sh'", "P"),
    ("make -n -f - <<< $'X := $(shell bash ~/.claude/hooks/stop.sh)\\nall:\\n\\techo'", "P"),
    ("make -n -f - <<< $'all:\\n\\t$(MAKE) -C x; bash ~/.claude/hooks/stop.sh'", "P"),
]

RG_RUNS = [
    ("RIPGREP_CONFIG_PATH={S}/rcbash find ~/.claude/hooks -exec rg x {} +", "P"),
    ("RIPGREP_CONFIG_PATH={S}/rcbash find ~/.claude/hooks -name 'stop*' -exec rg x {} \\;", "P"),
    ("export RIPGREP_CONFIG_PATH={S}/rcbash; find ~/.claude/hooks -exec rg x {} +", "P"),
    ("RIPGREP_CONFIG_PATH={S}/rcbash find ~/.claude/hooks -name stop.sh | xargs rg x", "P"),
]

RUNS = GIT_GREP_RUNS + TARGET_RUNS + MAKE_RUNS + RG_RUNS


@pytest.mark.parametrize("command,where", RUNS)
def test_a_run_with_a_computed_part_is_refused(env, command, where):
    proc = _run(env, command, where)
    assert proc.returncode == 2, (proc.returncode, proc.stderr)
    assert "USER-INTENT GUARD" in proc.stderr


@pytest.mark.parametrize("command,where", [GIT_GREP_RUNS[0], TARGET_RUNS[0], MAKE_RUNS[0],
                                           RG_RUNS[0]])
def test_a_run_under_a_live_sentinel_passes_and_consumes_it(env, command, where):
    _sentinel(env).write_text("true")
    proc = _run(env, command, where)
    assert proc.returncode == 0, proc.stderr
    assert not _sentinel(env).exists()


def test_a_pager_set_in_the_git_config_on_disk_is_read(env):
    """`git grep -O` with no program opens core.pager / pager.grep from the config on disk."""
    harness = str(env["harness"])
    git_env = dict(os.environ, HOME=str(env["home"]), GIT_CONFIG_NOSYSTEM="1")
    subprocess.run(["git", "init", "-q", harness], check=True, env=git_env)
    assert _run(env, "cd ~/.claude && git grep -O TODO").returncode == 0
    subprocess.run(["git", "-C", harness, "config", "core.pager", "bash"], check=True,
                   env=git_env)
    proc = _run(env, "cd ~/.claude && git grep -O TODO")
    assert proc.returncode == 2, proc.stderr
    subprocess.run(["git", "-C", harness, "config", "core.pager", "less -R"], check=True,
                   env=git_env)
    assert _run(env, "cd ~/.claude && git grep -O TODO").returncode == 0
