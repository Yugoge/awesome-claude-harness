"""hooks/pretool-harness-switch-guard.py: only a word a command WRITES counts as a write.

A Bash command writes the home's settings files, the switch's state or a Claude Code settings
file only through a word it writes: a redirection's target, a cp destination (and each source's
name inside it), every word of a command that is no reader (tee, dd, sed -i, perl -i, mv, rm,
touch, an interpreter, ...). A `>` elsewhere in the command, or a reader naming the file, is no
write: `grep x ~/.claude/settings.json > /tmp/out` reads. A reader is one of the listed programs
with no output operand (cat, grep, wc, nl, cut, tr, column, od, ...), sed without -i, -f or a
w / W / e command, and, for a project's settings file, awk whose program has no `>`, `|` or
system(). A written word is read from the call's directory and from every `cd` / `pushd` in the
chain, each read from the one before it, so `cd ~/.claude && sed -i ... settings.json` writes the
home's settings.json as `sed -i ... ~/.claude/settings.json` does.

Each case runs the hook as Claude Code does (a PreToolUse payload on stdin) from a harness home at
~/.claude in a throwaway HOME (a copy of the tree's hooks/), with a project holding a
.claude/settings.json.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = tmp_path_factory.mktemp("written")
    home = root / "home"
    h = home / ".claude"
    shutil.copytree(ROOT / "hooks", h / "hooks", ignore=shutil.ignore_patterns("tests", "__pycache__"))
    (h / "settings.json").write_text('{"env": {"A": "1"}, "hooks": {}}\n')
    (h / ".harness-switch").mkdir()
    (h / ".harness-switch" / "state.json").write_text("{}\n")
    proj = root / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "settings.json").write_text('{"env": {"A": "1"}, "permissions": {"deny": ["Bash(rm:*)"]}}\n')
    other = root / "other"
    other.mkdir()
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDE_CONFIG_DIR", "CLAUDE_PROJECT_DIR", "CLAUDE_HOME", "CLAUDE_TASK_ID",
                        "CLAUDE_SESSION_ID", "CLAUDE_AGENT_ID") and not k.startswith("GIT_")}
    env["HOME"] = str(home)
    return {"home": home, "h": h, "proj": proj, "other": other, "env": env,
            "hook": h / "hooks" / "pretool-harness-switch-guard.py"}


def hook(box, command, cwd, actor="main"):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd), "session_id": "S1"}
    if actor == "subagent":
        payload["agent_id"] = "sub-1"
    proc = subprocess.run([sys.executable, str(box["hook"])], input=json.dumps(payload), capture_output=True,
                          text=True, env=box["env"], cwd=str(cwd), timeout=60)
    return proc.returncode, proc.stderr


def cwds(box):
    return (box["other"], box["proj"], box["h"], box["home"])


def fill(box, command):
    return command.replace("{proj}", str(box["proj"])).replace("{F}", str(box["h"] / "settings.json"))


MUST_PASS = [
    # the lane's must-pass examples
    "sed -n '1,40p' ~/.claude/settings.json",
    "cp ~/.claude/settings.json /tmp/settings-backup.json",
    "grep -n '\"hooks\"' ~/.claude/settings.json > /tmp/hook-lines.txt",
    "wc -c ~/.claude/.harness-switch/* > /tmp/count.txt",
    # the same reads, spelled otherwise
    "sed -n '1,40p' ~/.claude/settings.json ; cp ~/.claude/settings.json /tmp/settings-backup.json",
    "cd ~/.claude && sed -n '1,40p' settings.json",
    "cd ~/.claude && grep -c env settings.json>/tmp/n",
    "cd ~/.claude && cp settings.json /tmp/settings-backup.json",
    "cp -p ~/.claude/settings.json ~/.claude/settings.local.json /tmp/",
    "cp -t /tmp ~/.claude/settings.json",
    "cut -c1-20 ~/.claude/settings.json | tr a-z A-Z | column -t > /tmp/cols.txt",
    "od -c ~/.claude/settings.json | head",
    "nl ~/.claude/settings.json > /tmp/numbered.txt",
    "cat ~/.claude/.harness-switch/state.json > /tmp/state-copy.json",
    "ls ~/.claude/.harness-switch > /tmp/ls.txt 2>&1",
    "sed -n '/disableAllHooks/p' ~/.claude/settings.json > /tmp/dah.txt",
    "sed -e 's/env/ENV/g' -e '/^$/d' ~/.claude/settings.json > /tmp/s.txt",
    "sed 's/new/old/' .claude/settings.json",
    "jq .hooks ~/.claude/settings.json > /tmp/hooks.json && wc -l /tmp/hooks.json",
    "grep -n disableAllHooks .claude/settings.json ~/.claude/settings.json > /tmp/dah.txt",
]


@pytest.mark.parametrize("command", MUST_PASS)
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_a_reader_and_a_write_elsewhere_pass(box, command, actor):
    command = fill(box, command)
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd, actor)
        assert rc == 0, (command, cwd, err)


PROJECT_READS = [  # a project's settings file read (from ~ these name the home's own, see HOME_WRITES' awk)
    "awk 'NR<=20' .claude/settings.json",
    "nl .claude/settings.json",
    "awk 'NR<=20' .claude/settings.json ; nl .claude/settings.json",
    "python3 -c \"import json; print(json.load(open('.claude/settings.json')).get('disableAllHooks'))\"",
    "awk -F: '{print $1}' {proj}/.claude/settings.json > /tmp/keys.txt",
    "cd {proj} && awk 'NR<=20' .claude/settings.json",
]


@pytest.mark.parametrize("command", PROJECT_READS)
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_a_read_of_a_projects_settings_file_passes(box, command, actor):
    command = fill(box, command)
    for cwd in (box["other"], box["proj"], box["h"]):
        rc, err = hook(box, command, cwd, actor)
        assert rc == 0, (command, cwd, err)


def test_from_home_nl_reads_the_homes_settings_too(box):
    """nl is a listed reader, for the home's own files as for a project's."""
    rc, err = hook(box, "nl .claude/settings.json", box["home"])
    assert rc == 0, err


HOME_WRITES = [
    "sed -i x ~/.claude/settings.json",
    "cp /tmp/evil.json ~/.claude/settings.json",
    "python3 -m json.tool --indent 1 {F} {F}",
    "cp /tmp/evil.json ~/.claude/settings.local.json",
    "cp /tmp/x/settings.json ~/.claude/",
    "cp -t ~/.claude /tmp/x/settings.json",
    "cp --target-directory=$HOME/.claude /tmp/x/settings.json",
    "mv /tmp/x/settings.json ~/.claude/",
    "grep x /tmp/y > ~/.claude/settings.json",
    "cat /tmp/y | tee ~/.claude/settings.json",
    "dd if=/tmp/y of=$HOME/.claude/settings.json",
    "sed -n 'w {F}' /tmp/y",
    "sed -n '1w {F}' /tmp/y",
    "sed 's/a/b/w {F}' /tmp/y",
    "sed --in-place=.bak s/a/b/ ~/.claude/settings.json",
    "sed -f /tmp/script.sed ~/.claude/settings.json",
    "perl -pi -e s/a/b/ ~/.claude/settings.json",
    "awk 'NR<=20' ~/.claude/settings.json",  # awk is no reader for the home's files
    "uniq /tmp/evil.json ~/.claude/settings.json",
    "sort -o ~/.claude/settings.json /tmp/evil.json",
    "xxd -r /tmp/hex ~/.claude/settings.json",
    "env sed -i x ~/.claude/settings.json",
    "command cp /tmp/evil.json ~/.claude/settings.json",
    "timeout 5 cp /tmp/evil.json ~/.claude/settings.json",
    "nice -n 5 tee ~/.claude/settings.json < /tmp/evil.json",
    "setsid cp /tmp/evil.json ~/.claude/settings.json",
    "exec cp /tmp/evil.json ~/.claude/settings.json",
    "bash -c 'sed -i x ~/.claude/settings.json'",
    "echo x | tee >(cat > ~/.claude/settings.json)",
    "rm ~/.claude/settings.json",
    "find ~/.claude -maxdepth 1 -name settings.json -fprint ~/.claude/settings.json",
]
CD_WRITES = [  # the under-defence: a `cd` (or pushd, or a chain of them) before the write
    "cd ~/.claude && sed -i 's/block/off/' settings.json",
    "cd ~/.claude && cp /tmp/evil.json settings.json",
    "cd ~ && cd .claude && sed -i 's/block/off/' settings.json",
    "cd ~ && cd .claude && cp /tmp/evil.json settings.json",
    "cd \"$HOME/.claude\"; sed -i 's/block/off/' settings.json",
    "cd \"$HOME/.claude\"; cp /tmp/evil.json settings.json",
    "cd $HOME/.claude && cp /tmp/evil.json ./settings.json",
    "pushd ~/.claude && sed -i 's/block/off/' settings.json",
    "pushd ~/.claude >/dev/null && cp /tmp/evil.json settings.json",
    "(cd ~/.claude && sed -i 's/block/off/' settings.json)",
    "(cd ~/.claude && cp /tmp/evil.json settings.json)",
    "cd ~/.claude/hooks && cp /tmp/evil.json ../settings.json",
    "cd ~/.claude && cp /tmp/x/settings.json .",
    "cd ~/.claude && cp -t . /tmp/x/settings.json",
    "cd ~/.claude && echo '{}' > settings.json",
    "cd ~/.claude && echo '{}'>settings.json",
    "cd ~/.claude && grep x /tmp/y > settings.json",
    "cd ~/.claude && tee settings.json < /tmp/evil.json",
    "cd ~/.claude && perl -pi -e 's/block/off/' settings.json",
    "cd ~/.claude && awk '{print > \"settings.json\"}' /tmp/x",
    "cd ~/.claude && python3 -m json.tool --indent 1 settings.json settings.json",
    "cd -P ~/.claude && sed -i x settings.json",
    "cd /tmp && cd ~/.claude && sed -i x settings.json",
    "bash -c 'cd ~/.claude && sed -i x settings.json'",
    "cd ~/.claude && bash -c 'sed -i x settings.json'",
    "cd ~/.claude && env sed -i x settings.json",
    "cd ~/.claude && timeout 5 cp /tmp/evil.json settings.json",
    "cd; cd .claude && sed -i x settings.json",
]


@pytest.mark.parametrize("command", HOME_WRITES + CD_WRITES)
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_a_write_of_the_homes_settings_is_refused(box, command, actor):
    command = fill(box, command)
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd, actor)
        assert rc == 2 and "harness-switch:" in err, (command, cwd, err)


STATE_WRITES = [
    "touch ~/.claude/.harness-switch/off",
    "cd ~/.claude && touch .harness-switch/off",
    "cd ~/.claude/.harness-switch && touch off",
    "cd ~/.claude && cd .harness-switch && touch off",
    "cd ~ && cd .claude/.harness-switch && rm state.json",
    "(cd ~/.claude/.harness-switch && echo x > off)",
    "pushd ~/.claude/.harness-switch && : > off",
    "echo x > ~/.claude/.harness-switch/off",
    "cat ~/.claude/.harness-switch/state.json > ~/.claude/.harness-switch/off",
    "wc -c ~/.claude/.harness-switch/* > ~/.claude/.harness-switch/off",
    "cp /tmp/x ~/.claude/.harness-switch/off",
    "rm -rf ~/.claude/.harness-switch",
    "mkdir -p ~/.claude/.harness-switch && touch ~/.claude/.harness-switch/off",
]


@pytest.mark.parametrize("command", STATE_WRITES)
def test_a_write_of_the_switchs_state_is_refused(box, command):
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd)
        assert rc == 2 and "harness-switch:" in err, (command, cwd, err)


def test_the_attached_redirect_from_the_home_stays_refused(box):
    """P14-12's pin: `echo x>settings.json` run in the harness home writes its settings.json."""
    for command in ("echo x>settings.json", "echo x > settings.json", "echo x >settings.json"):
        rc, err = hook(box, command, box["h"])
        assert rc == 2 and "harness-switch:" in err, (command, err)


PROJECT_WRITES = [
    "uniq /tmp/evil.json .claude/settings.json",
    "awk '{print > \".claude/settings.json\"}' /tmp/x",
    "awk '{print >> \".claude/settings.json\"}' /tmp/x",
    "awk -f /tmp/prog.awk .claude/settings.json",
    "gawk -i inplace '{print}' .claude/settings.json",
    "sed -n 'w .claude/settings.json' /tmp/x",
    "sort -o .claude/settings.json /tmp/x",
    "cp /tmp/evil.json .claude/settings.json",
    "cd .claude && cp /tmp/evil.json settings.json",
    "cd {proj} && cd .claude && sed -i x settings.json",
    "nl /tmp/x > .claude/settings.json",
]


@pytest.mark.parametrize("command", PROJECT_WRITES)
def test_a_write_of_a_projects_settings_file_is_refused(box, command):
    command = fill(box, command)
    rc, err = hook(box, command, box["proj"])
    assert rc == 2 and "Claude Code settings file" in err, (command, err)


DAH_WRITES = [
    "python3 -c \"import json; json.dump({'disableAllHooks': True}, open('.claude/settings.json', 'w'))\"",
    "python3 -c \"open('.claude/settings.local.json','w').write('{\\\"disableAllHooks\\\": 1}')\"",
    "awk 'BEGIN{print \"{\\\"disableAllHooks\\\":true}\" > \".claude/settings.local.json\"}'",
    "sed -n '1w .claude/settings.local.json' /tmp/disableAllHooks.json",
]


@pytest.mark.parametrize("command", DAH_WRITES)
def test_disable_all_hooks_written_by_an_interpreter_or_a_program_stays_refused(box, command):
    rc, err = hook(box, command, box["proj"])
    assert rc == 2 and "disableAllHooks" in err, (command, err)
