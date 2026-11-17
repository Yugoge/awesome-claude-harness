"""/harness off | on | status (commands/harness.md, scripts/harness-switch).

Each test builds a harness home the way the full install leaves one: a git checkout of this
tree, the settings filter registered, an overlay with the owner's own entries, the machine form
rendered, Claude Code's config dir the home itself. The switch is driven as the owner drives it:
a UserPromptSubmit payload with the typed prompt, through the registered hook.
"""
from __future__ import annotations

import functools
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
OWNER_HOOK = {"type": "command", "command": "/usr/local/bin/owner-own-hook"}
REFUSED = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}}


def run(cmd, cwd, env=None, input=None, check=True):
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, input=input, capture_output=True, text=True,
                          timeout=120)
    if check and proc.returncode != 0:
        raise AssertionError("%s: %d\n%s\n%s" % (cmd, proc.returncode, proc.stdout, proc.stderr))
    return proc


def tree_files():
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT,
                         capture_output=True, check=True).stdout.decode()
    return [f for f in out.split("\0") if f and (ROOT / f).is_file() and not f.startswith("tests/")]


class Home:
    def __init__(self, path: Path, env: dict):
        self.path, self.env = path, env
        self.transcript = path.parent / "transcript.jsonl"

    def git(self, *args, check=True):
        return run(["git", *args], self.path, self.env, check=check)

    def settings(self) -> bytes:
        return (self.path / "settings.json").read_bytes()

    def prompt(self, text, session="S1", **extra):
        payload = {"hook_event_name": "UserPromptSubmit", "prompt": text, "session_id": session,
                   "transcript_path": str(self.transcript), "cwd": str(self.path), **extra}
        proc = run(["bash", str(self.path / "hooks" / "userprompt-harness-switch.sh")], self.path, self.env,
                   json.dumps(payload))
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def switch(self, verb, env=None, under=0, claude=None):
        """Type /harness <verb> through the registered hook, `under` stand-in Claude Code
        processes (`claude`, a copy of bash) deep: the hook's parent chain gains that many."""
        payload = {"hook_event_name": "UserPromptSubmit", "prompt": "/harness " + verb, "session_id": "S1",
                   "transcript_path": str(self.transcript), "cwd": str(self.path)}
        hook = str(self.path / "hooks" / "userprompt-harness-switch.sh")
        cmd = ["bash", hook]
        if under:
            line = "bash " + shlex.quote(hook)
            for _ in range(under):  # `; exit` keeps bash from exec'ing the last command in place
                line = "%s -c %s" % (shlex.quote(str(claude)), shlex.quote(line + "; rc=$?; exit $rc"))
            cmd = ["bash", "-c", line + "; rc=$?; exit $rc"]
        return run(cmd, self.path, dict(self.env, **(env or {})), json.dumps(payload), check=False)

    def status(self):
        return run([PY, str(self.path / "scripts" / "harness-switch"), "status"], self.path, self.env, check=False)

    def hook(self, rel, payload, kind=None):
        kind = kind or ("bash" if rel.endswith(".sh") else PY)
        data = dict({"session_id": "S1", "cwd": str(self.path), "hook_event_name": "PreToolUse",
                     "transcript_path": str(self.transcript)}, **payload)
        return run([kind, str(self.path / rel)], self.path, self.env, json.dumps(data), check=False)


@pytest.fixture()
def home(tmp_path):
    h = tmp_path / "claude"
    for rel in tree_files():
        dst = h / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dst)
    env = dict(os.environ, **GIT_ENV, HOME=str(tmp_path), CLAUDE_CONFIG_DIR=str(h), CLAUDE_HOME=str(h),
               CLAUDE_STATE_DIR=str(tmp_path / "state"), CLAUDE_PROJECT_DIR=str(h))
    env.pop("HARNESS_SWITCH_STOP_AFTER", None)
    (tmp_path / "state").mkdir()
    home = Home(h, env)
    home.git("init", "-q", "-b", "master")
    home.git("config", "filter.claude-settings.clean", "python3 scripts/install/render-settings clean")
    home.git("config", "filter.claude-settings.smudge", "python3 scripts/install/render-settings smudge")
    home.git("config", "filter.claude-settings.required", "true")
    home.git("add", "-A")
    home.git("commit", "-qm", "harness")
    (h / "settings.machine.json").write_text(json.dumps({
        "modules": {}, "env": {"CLAUDE_HOME": str(h), "OWNER_OWN_VAR": "1"},
        "permissions": {"allow": ["Bash(owner-own-tool:*)"]},
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [OWNER_HOOK]}]}}, indent=2))
    run([PY, "scripts/install/render-settings", "render"], h, env)
    data = json.loads(home.settings())
    data["model"] = "opus"  # a CLI-owned key, as /model writes it
    (h / "settings.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    refresh_stat(home)  # as the landing does after a CLI write (render-settings refresh_index)
    (h / ".claude.json").write_text(json.dumps({"mcpServers": {"playwright": {"command": "npx"}}}))
    (h / "plugins").mkdir()
    (h / "plugins" / "installed.json").write_text("{}")
    (h / ".credentials.json").write_text("{}")
    (h / "commands" / "owner-own.md").write_text("---\ndescription: mine\n---\nmine\n")
    home.transcript.write_text(json.dumps({"type": "user", "timestamp": "2000-01-01T00:00:00Z"}) + "\n")
    assert home.git("status", "--porcelain").stdout.strip() == "?? commands/owner-own.md"
    return home


def refresh_stat(home):
    code = ("import importlib.machinery as m, importlib.util as u, sys; p = 'scripts/install/render-settings'; "
            "l = m.SourceFileLoader('rs', p); mod = u.module_from_spec(u.spec_from_loader('rs', l)); "
            "l.exec_module(mod); mod.refresh_index(sys.argv[1])")
    run([PY, "-c", code, str(home.path)], home.path, home.env)


def registered(settings_bytes):
    """Every hook command the settings register (the expansion of a launcher too, when one exists)."""
    out = []
    for event, groups in json.loads(settings_bytes)["hooks"].items():
        for group in groups:
            for hook in group["hooks"]:
                out.append((event, hook["command"]))
    return out


def run_registered(home, command, event):
    payload = {"session_id": "S1", "cwd": str(home.path), "hook_event_name": event, "prompt": "hello",
               "transcript_path": str(home.transcript), "stop_hook_active": False,
               "tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}, "tool_response": {}}
    return run(["bash", "-c", command], home.path, home.env, json.dumps(payload), check=False)


# ------------------------------------------------------------------------------------- off / on

def test_off_lets_a_refused_call_pass_silently_and_on_refuses_it_again(home):
    loaded = home.settings()  # what a session started now holds for its whole life
    assert home.hook("hooks/pretool-bash-safety.sh", REFUSED).returncode == 2
    assert home.hook("hooks/pretool-write-gate.py", {"tool_name": "Skill", "tool_input": {"skill": "harness"}}).returncode == 2
    assert home.switch("off").returncode == 0
    switch_hook = "userprompt-harness-switch.sh"
    for event, command in registered(loaded):
        if switch_hook in command or command == OWNER_HOOK["command"]:
            continue  # the switch itself, and the owner's own hook (not the harness's)
        proc = run_registered(home, command, event)
        assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", ""), (event, command, proc)
    assert home.switch("on").returncode == 0
    proc = home.hook("hooks/pretool-bash-safety.sh", REFUSED)
    assert proc.returncode == 2 and proc.stderr


def test_off_report_reaches_the_owner_and_status_names_the_home(home):
    out = home.prompt("/harness off")
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["systemMessage"].startswith("Harness: OFF")
    assert "Home: %s" % home.path in ctx and "Config dir: the same directory" in ctx
    assert "Restart needed: yes" in ctx
    proc = home.status()
    assert proc.returncode == 3 and proc.stdout.startswith("Harness: OFF")
    other = home.prompt("/harness status", session="S2")["hookSpecificOutput"]["additionalContext"]
    assert "Harness: OFF" in other


def test_next_session_loads_no_harness_settings_prompts_or_agents(home):
    home.switch("off")
    s = json.loads(home.settings())
    commands = [c for _, c in registered(home.settings())]
    assert commands == ['bash "${CLAUDE_HOME:-$HOME/.claude}/hooks/userprompt-harness-switch.sh"', OWNER_HOOK["command"]]
    shipped = json.loads(home.git("show", "HEAD:settings.json").stdout)
    assert not set(s.get("env", {})) & set(shipped["env"])
    assert s["env"] == {"CLAUDE_HOME": str(home.path), "OWNER_OWN_VAR": "1"}
    assert s["permissions"] == {"allow": ["Bash(owner-own-tool:*)"],
                                "deny": ["Edit(**/.harness-switch/**)", "Skill(harness:*)"]}
    assert s["model"] == "opus" and s["cleanupPeriodDays"] == 365 and "deniedMcpServers" in s
    assert "includeCoAuthoredBy" not in s
    h = home.path
    assert not (h / "CLAUDE.md").exists() and not (h / "agents").exists() and not (h / "skills").exists()
    assert sorted(p.name for p in (h / "commands").iterdir()) == ["harness.md", "owner-own.md"]
    assert (h / "hooks" / "pretool-bash-safety.sh").exists()
    assert home.git("status", "--porcelain").stdout.strip() == "?? commands/owner-own.md"


def test_on_restores_settings_byte_identical(home):
    before = home.settings()
    home.switch("off")
    assert home.settings() != before
    home.switch("on")
    assert home.settings() == before
    assert (home.path / "CLAUDE.md").exists() and (home.path / "agents" / "dev.md").exists()
    assert home.git("status", "--porcelain").stdout.strip() == "?? commands/owner-own.md"
    assert home.status().returncode == 0


def test_on_keeps_the_owners_changes_made_while_off(home):
    before = json.loads(home.settings())
    untouched = {p: hashlib.sha256((home.path / p).read_bytes()).hexdigest()
                 for p in (".credentials.json", "plugins/installed.json")}
    home.switch("off")
    off = json.loads(home.settings())
    off["permissions"]["allow"].append("Bash(new-owner-tool:*)")
    off["env"]["NEW_OWNER_VAR"] = "2"
    off["model"] = "sonnet"
    off["enabledPlugins"] = {"a@b": True}
    (home.path / "settings.json").write_text(json.dumps(off, indent=2) + "\n")
    mcp = json.loads((home.path / ".claude.json").read_text())
    mcp["mcpServers"]["added-while-off"] = {"command": "x"}
    (home.path / ".claude.json").write_text(json.dumps(mcp))
    home.switch("on")
    after = json.loads(home.settings())
    expected = json.loads(json.dumps(before))
    expected["permissions"]["allow"].append("Bash(new-owner-tool:*)")
    expected["env"]["NEW_OWNER_VAR"] = "2"
    expected["model"] = "sonnet"
    expected["enabledPlugins"] = {"a@b": True}
    assert after == expected
    assert json.loads((home.path / ".claude.json").read_text()) == mcp
    for p, digest in untouched.items():
        assert hashlib.sha256((home.path / p).read_bytes()).hexdigest() == digest


def test_a_pull_while_off_stays_off_and_on_gives_the_pulled_version(home, tmp_path):
    upstream = tmp_path / "upstream"
    run(["git", "clone", "-q", str(home.path), str(upstream)], tmp_path, home.env)
    run(["git", "config", "filter.claude-settings.clean", "cat"], upstream, home.env)
    run(["git", "config", "filter.claude-settings.smudge", "cat"], upstream, home.env)
    shipped = json.loads((upstream / "settings.json").read_text())
    shipped["env"]["PULLED_VAR"] = "1"
    (upstream / "settings.json").write_text(json.dumps(shipped, indent=2, ensure_ascii=False) + "\n")
    (upstream / "commands" / "pulled.md").write_text("---\ndescription: pulled\n---\npulled\n")
    run(["git", "add", "-A"], upstream, home.env)
    run(["git", "commit", "-qm", "upstream"], upstream, home.env)
    home.switch("off")
    home.git("pull", "-q", "--no-rebase", str(upstream), "master")
    assert home.git("log", "-1", "--format=%s").stdout.strip() == "upstream"
    s = json.loads(home.settings())
    assert "PULLED_VAR" not in s["env"] and len(registered(home.settings())) == 2
    assert not (home.path / "commands" / "pulled.md").exists()
    assert home.status().returncode == 3
    home.switch("on")
    s = json.loads(home.settings())
    assert s["env"]["PULLED_VAR"] == "1" and s["env"]["OWNER_OWN_VAR"] == "1" and s["model"] == "opus"
    assert (home.path / "commands" / "pulled.md").exists()
    assert home.git("status", "--porcelain").stdout.strip() == "?? commands/owner-own.md"


# --------------------------------------------------------------------------- interrupted switch

@pytest.mark.parametrize("cut", ["off:save", "off:marker", "off:settings", "on:show", "on:settings", "on:marker"])
def test_a_cut_switch_is_named_by_status_and_repaired_by_the_next_switch(home, cut):
    before = home.settings()
    op, step = cut.split(":")
    if op == "on":
        home.switch("off")
    proc = home.switch(op, env={"HARNESS_SWITCH_STOP_AFTER": cut})
    assert proc.returncode != 0  # the process died after the step
    status = home.status()
    assert status.returncode == 4 and status.stdout.startswith("Harness: PARTIAL")
    assert "/harness %s was cut after step %s" % (op, step) in status.stdout
    hooks_off = (home.path / ".harness-switch" / "off").exists()
    rc = home.hook("hooks/pretool-bash-safety.sh", REFUSED).returncode
    assert rc == (0 if hooks_off else 2)  # every hook follows the one marker: all on or all off
    other = "on" if op == "off" else "off"
    out = home.prompt("/harness " + other)["hookSpecificOutput"]["additionalContext"]
    assert "finished the /harness %s that was cut after step %s" % (op, step) in out
    assert home.status().returncode == (0 if other == "on" else 3)
    if other == "off":
        home.switch("on")
    assert home.settings() == before
    assert home.status().returncode == 0


def test_a_hidden_file_with_local_changes_is_named_and_hidden_by_the_next_off(home):
    dev = home.path / "commands" / "dev.md"
    original = dev.read_text()
    dev.write_text(original + "\nlocal edit\n")
    home.switch("off")
    assert dev.exists()
    status = home.status()
    assert status.returncode == 4 and "commands/dev.md" in status.stdout and "partial off" in status.stdout
    since = json.loads((home.path / ".harness-switch" / "state.json").read_text())["since"]
    assert home.hook("hooks/pretool-bash-safety.sh", REFUSED).returncode == 0  # the hooks are off all the same
    dev.write_text(original)
    home.switch("off")
    assert not dev.exists() and home.status().returncode == 3
    assert json.loads((home.path / ".harness-switch" / "state.json").read_text())["since"] == since
    before_on = home.switch("on")
    assert before_on.returncode == 0 and dev.read_text() == original and home.status().returncode == 0


# ------------------------------------------------------------------------------- owner only

AGENT_PATHS = {
    "Skill": {"tool_name": "Skill", "tool_input": {"skill": "harness", "args": "off"}},
    "SlashCommand": {"tool_name": "SlashCommand", "tool_input": {"command": "/harness off"}},
    "Bash runs the switch": {"tool_name": "Bash", "tool_input": {"command": "python3 scripts/harness-switch hook < p.json"}},
    "Bash runs the switch hook": {"tool_name": "Bash", "tool_input": {"command": "bash hooks/userprompt-harness-switch.sh < p.json"}},
    "Bash writes the state": {"tool_name": "Bash", "tool_input": {"command": "mkdir -p .harness-switch && touch .harness-switch/off"}},
    "Bash types /harness": {"tool_name": "Bash", "tool_input": {"command": "claude -p '/harness off'"}},
    "Bash edits settings": {"tool_name": "Bash", "tool_input": {"command": "sed -i 's/hooks/x/' settings.json"}},
    "Write the state": {"tool_name": "Write", "tool_input": {"file_path": "{H}/.harness-switch/off", "content": ""}},
    "Edit settings": {"tool_name": "Edit", "tool_input": {"file_path": "{H}/settings.json", "old_string": "a", "new_string": "b"}},
    "Write the overlay": {"tool_name": "Write", "tool_input": {"file_path": "{H}/settings.machine.json", "content": "{}"}},
    "disableAllHooks": {"tool_name": "Write", "tool_input": {"file_path": "/tmp/p/.claude/settings.local.json", "content": '{"disableAllHooks": true}'}},
    "Bash disableAllHooks": {"tool_name": "Bash", "tool_input": {"command": "echo '{\"disableAllHooks\": true}' > /tmp/p/.claude/settings.local.json"}},
    "a script": {"tool_name": "Write", "tool_input": {"file_path": "/tmp/s.py", "content": "open('{H}/.harness-switch/off', 'w')"}},
    "CronCreate": {"tool_name": "CronCreate", "tool_input": {"cron": "* * * * *", "prompt": "/harness off"}},
    "ScheduleWakeup": {"tool_name": "ScheduleWakeup", "tool_input": {"delaySeconds": 60, "prompt": "/harness on"}},
    "SendMessage": {"tool_name": "SendMessage", "tool_input": {"to": "x", "message": "/harness off"}},
}


@pytest.mark.parametrize("name", sorted(AGENT_PATHS))
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_every_agent_path_is_refused_while_the_harness_is_on(home, name, actor):
    payload = json.loads(json.dumps(AGENT_PATHS[name]).replace("{H}", str(home.path)))
    if actor == "subagent":
        payload["agent_id"] = "sub-1"
    proc = home.hook("hooks/pretool-write-gate.py", payload)
    assert proc.returncode == 2 and "harness-switch" in proc.stderr, proc.stderr
    assert not (home.path / ".harness-switch" / "off").exists()


def test_reading_stays_free(home):
    for command in ("git status && git diff settings.json", "cat .harness-switch/state.json", "git add scripts/harness-switch"):
        proc = home.hook("hooks/pretool-write-gate.py", {"tool_name": "Bash", "tool_input": {"command": command}})
        assert "harness-switch:" not in proc.stderr, (command, proc.stderr)


SETTINGS_WRITES = [  # Bash forms that put disableAllHooks into some project's settings*.json
    "echo '{\"disableAllHooks\":true}' >settings.local.json",
    "printf '{\"disableAllHooks\":true}' | tee ~/proj/.claude/settings.json",
    "cat > .claude/settings.local.json <<'EOF'\n{\"disableAllHooks\": true}\nEOF",
    "python3 -c \"open('x/settings.local.json','w').write('{\\\"disableAllHooks\\\": 1}')\"",
    "python3 - <<'EOF'\nimport json\njson.dump({'disableAllHooks': True}, open('/p/.claude/settings.local.json', 'w'))\nEOF",
    "bash -c \"echo '{\\\"disableAllHooks\\\":true}' > p/.claude/settings.local.json\"",
    "sed -i 's/{/{\"disableAllHooks\":true,/' .claude/settings.local.json",
    "jq '.disableAllHooks=true' s.json > t && mv t .claude/settings.json",
    "cat > /tmp/s.py <<'EOF'\nopen('/p/.claude/settings.local.json', 'w').write('{\"disableAllHooks\": true}')\nEOF\npython3 /tmp/s.py",
]
SETTINGS_READS = [  # the same words, no settings file written
    "grep -n disableAllHooks .claude/settings.json",
    "jq .disableAllHooks .claude/settings.local.json",
    "grep -c disableAllHooks .claude/settings.json > /tmp/n",
    "sed -n '/disableAllHooks/p' .claude/settings.json",
    "echo '{\"model\":\"opus\"}' > .claude/settings.local.json",
    "echo disableAllHooks > notes.txt",
    "git commit -m \"Refuse a Bash write of disableAllHooks to settings.local.json\"",
    "git commit -m \"$(cat <<'EOF'\nRefuse disableAllHooks\n\nA write of {\"disableAllHooks\": true} to /p/.claude/settings.local.json (> or tee) is refused.\nEOF\n)\"",
    "gh pr create --title t --body \"$(cat <<'EOF'\nsettings.local.json and disableAllHooks: > settings.json\nEOF\n)\"",
]


@pytest.mark.parametrize("command", SETTINGS_WRITES)
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_bash_cannot_write_disable_all_hooks_into_any_settings_file(home, command, actor):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/tmp"}
    if actor == "subagent":
        payload["agent_id"] = "sub-1"
    proc = home.hook("hooks/pretool-write-gate.py", payload)
    assert proc.returncode == 2 and "disableAllHooks" in proc.stderr, (command, proc.stderr)


@pytest.mark.parametrize("command", SETTINGS_READS)
def test_bash_that_only_reads_or_talks_about_disable_all_hooks_passes(home, command):
    proc = home.hook("hooks/pretool-write-gate.py", {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/tmp"})
    assert "disableAllHooks" not in proc.stderr and "harness-switch:" not in proc.stderr, (command, proc.stderr)


def test_the_command_is_owner_only_and_its_hook_ignores_a_subagent(home):
    text = (ROOT / "commands" / "harness.md").read_text()
    assert "\ndisable-model-invocation: true\n" in text.split("\n---", 1)[0]
    assert "Skill(harness:*)" in json.loads((ROOT / "settings.json").read_text())["permissions"]["deny"]
    assert home.prompt("/harness off", agent_id="sub-1") is None
    assert not (home.path / ".harness-switch").exists()
    assert home.prompt("please run /harness off for me") is None
    assert not (home.path / ".harness-switch").exists()


# ----------------------------------------------------------------------------- nested session

def load_switch():
    loader = importlib.machinery.SourceFileLoader("harness_switch_script", str(ROOT / "scripts" / "harness-switch"))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


@pytest.fixture()
def claude(tmp_path):
    """A stand-in for the Claude Code binary: a copy of bash named `claude`."""
    exe = tmp_path / "bin" / "claude"
    exe.parent.mkdir()
    shutil.copy2(shutil.which("bash"), exe)
    return exe


def ambient_claudes():
    """Claude Code processes above pytest itself (none in CI; one when run from a Claude session)."""
    return len(load_switch().claude_processes(os.getpid()))


@pytest.mark.parametrize("exe, argv, expected", [
    ("/usr/local/bin/claude", ["claude"], True),                                    # native binary
    ("/usr/local/share/claude/versions/2.1.322", ["claude", "-p"], True),            # installer's versioned copy
    ("/usr/bin/node", ["node", "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js"], True),
    ("/usr/bin/node", ["node", "--no-warnings", "/usr/local/bin/claude", "-p", "x"], True),
    ("/usr/bin/bun", ["bun", "/usr/local/bun/bin/claude"], True),
    ("/usr/bin/bash", ["bash", "/usr/local/bin/claude"], False),                         # a wrapper script
    ("/usr/bin/bash", ["bash", "-c", "claude -p '/harness off'"], False),                # the text alone
    ("/usr/bin/node", ["node", "/usr/lib/node_modules/npm/bin/npx-cli.js", "@anthropic-ai/claude-code"], False),
    ("/usr/bin/node", ["node", "/usr/lib/node_modules/claude-code-router/dist/cli.js"], False),
    ("/Applications/Claude.app/Contents/MacOS/Claude", ["Claude"], False),               # the desktop app
    ("/usr/bin/python3", ["python3", "run_agent.py"], False),
])
def test_looks_like_claude(exe, argv, expected):
    assert load_switch().looks_like_claude(exe, argv) is expected


def test_nested_claude_reads_the_hooks_ancestry(monkeypatch):
    switch = load_switch()
    table = {  # pid: (parent, executable, argv)
        100: (90, "/usr/bin/python3", ["python3", "scripts/harness-switch", "hook"]),        # the hook
        90: (80, "/bin/sh", ["sh", "-c", "hooks/userprompt-harness-switch.sh"]),
        80: (70, "/usr/local/bin/claude", ["claude", "-p", "/harness off"]),            # the session's own
        70: (60, "/usr/bin/bash", ["bash", "-c", "python3 /tmp/x.py"]),                      # an agent's Bash call
        60: (50, "/usr/bin/python3", ["python3", "/tmp/x.py"]),
        50: (40, "/usr/bin/node", ["node", "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js"]),
        40: (30, "/bin/zsh", ["zsh"]),
        30: (1, "/usr/sbin/sshd", ["sshd"]),
    }
    monkeypatch.setattr(switch, "_process", lambda pid: table.get(pid))
    assert switch.nested_claude(90) == (50, "node /usr/lib/node_modules/@anthropic-ai/claude-code/cli.js")
    assert switch.nested_claude(70) is None      # from the agent's shell up: only the owner's `claude`
    assert switch.nested_claude(40) is None      # no Claude Code process at all (a test, a script)
    table[30] = (90, "/usr/sbin/sshd", ["sshd"])  # a loop in the table ends the walk
    assert switch.nested_claude(90) is not None
    monkeypatch.setattr(switch, "_process", lambda pid: None)
    assert switch.nested_claude(90) is None      # nothing readable: not refused


@pytest.mark.parametrize("levels", [2, 3])
def test_a_session_started_inside_another_claude_session_cannot_switch(home, claude, levels):
    """The agent's script starts `claude -p "/harness off"`: the nested session's hook finds a
    Claude Code process above the session's own, refuses, and changes nothing."""
    ambient = ambient_claudes()
    if ambient > levels:
        pytest.skip("pytest itself runs deeper inside Claude Code sessions than this case")
    before = home.settings()
    proc = home.switch("off", under=levels - ambient, claude=claude)
    out = json.loads(proc.stdout)
    assert out["decision"] == "block" and "started from inside another Claude Code session" in out["reason"], proc
    assert "/harness off refused, nothing changed" in out["reason"]
    assert not (home.path / ".harness-switch").exists()
    assert home.settings() == before and home.status().returncode == 0
    assert (home.path / "commands" / "dev.md").exists()


def test_a_nested_session_cannot_switch_the_harness_back_on_either(home, claude):
    if ambient_claudes() > 1:
        pytest.skip("pytest itself runs inside a nested Claude Code session")
    assert home.switch("off", under=1 - ambient_claudes(), claude=claude).returncode == 0
    assert home.status().returncode == 3
    proc = home.switch("on", under=2 - ambient_claudes(), claude=claude)
    assert "started from inside another Claude Code session" in json.loads(proc.stdout)["reason"]
    assert home.status().returncode == 3 and (home.path / ".harness-switch" / "off").exists()


def test_a_nested_session_may_still_read_the_status(home, claude):
    ambient = ambient_claudes()
    proc = home.switch("status", under=max(0, 2 - ambient), claude=claude)
    out = json.loads(proc.stdout)
    assert "decision" not in out and "Harness: ON" in out["hookSpecificOutput"]["additionalContext"]


def test_the_owners_top_level_session_still_switches_off_and_on(home, claude):
    """One Claude Code process above the hook: the owner's terminal, desktop app or IDE session."""
    ambient = ambient_claudes()
    if ambient > 1:
        pytest.skip("pytest itself runs inside a nested Claude Code session")
    off = home.switch("off", under=1 - ambient, claude=claude)
    assert off.returncode == 0 and "HARNESS SWITCH" in off.stdout and "decision" not in off.stdout
    assert (home.path / ".harness-switch" / "off").exists() and home.status().returncode == 3
    on = home.switch("on", under=1 - ambient, claude=claude)
    assert on.returncode == 0 and "HARNESS SWITCH" in on.stdout and home.status().returncode == 0


# ------------------------------------------------------------------------- background, doctor

def test_background_jobs_are_inert_while_off(home):
    home.switch("off")
    h, env = home.path, dict(home.env, CLAUDE_OVERNIGHT_ACTOR="1")
    proc = run(["bash", "-c", '. hooks/lib/checkpoint-core.sh; write_checkpoint "$PWD" test; echo rc=$?'], h, env)
    assert "rc=0" in proc.stdout and not home.git("for-each-ref", "refs/checkpoints").stdout.strip()
    proc = run(["bash", "-c", 'git config harness.autoPush true; . hooks/lib/auto_push.sh; harness_auto_push .; echo rc=$?'], h, env)
    assert "rc=1" in proc.stdout
    keystone = run(["bash", str(h / "hooks" / "git-keystone" / "reference-transaction"), "prepared"], h, env,
                   "0" * 40 + " " + "1" * 40 + " HEAD\n", check=False)
    assert keystone.returncode == 0
    assert run(["bash", "scripts/install/land"], h, env).stdout == ""
    home.switch("on")
    proc = run(["bash", "-c", '. hooks/lib/auto_push.sh; harness_auto_push .; echo rc=$?'], h, env)
    assert "rc=0" in proc.stdout


def test_an_overnight_run_cut_by_off_holds_nothing_after_on(home):
    start = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (datetime.now(timezone.utc) + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {"session_id": "S1", "start_time": start, "end_time": end, "current_phase": "cycle"}
    (home.path / ".claude").mkdir(exist_ok=True)
    (home.path / ".claude" / "overnight-state-S1.json").write_text(json.dumps(record))
    probe = ("import sys, json; sys.path.insert(0, 'hooks/lib'); import overnight; "
             "r = json.load(open('.claude/overnight-state-S1.json')); v = overnight.state_verdicts(r); "
             "print(v.window_live, v.before_end, v.isolation_held)")
    assert run([PY, "-c", probe], home.path, home.env).stdout.split() == ["True", "True", "True"]
    home.switch("off")
    home.switch("on")
    assert run([PY, "-c", probe], home.path, home.env).stdout.split() == ["False", "False", "False"]


def test_a_wake_prompt_is_refused_while_off(home):
    home.switch("off")
    out = home.prompt("[awesome-claude-harness/overnight-wake-v1] Scheduled wake of this /dev-overnight session")
    assert out["decision"] == "block" and "/harness on" in out["reason"]
    home.switch("on")
    assert home.prompt("[awesome-claude-harness/overnight-wake-v1] Scheduled wake") is None


@pytest.mark.parametrize("args", [["--strict"], []])
def test_doctor_reports_the_off_state_plainly(home, args):
    home.switch("off")
    proc = run(["bash", str(home.path / "scripts" / "doctor"), *args], home.path, home.env, check=False)
    assert proc.returncode == 3
    assert "the harness is switched off (/harness off)" in proc.stdout
    assert "Harness: OFF" in proc.stdout and "type /harness on" in proc.stdout


def test_render_settings_check_passes_while_off(home):
    home.switch("off")
    proc = run([PY, "scripts/install/render-settings", "check"], home.path, home.env, check=False)
    assert "round trip" in proc.stdout and "[FAIL] settings filter" not in proc.stdout, proc.stdout
    assert "the harness is off (/harness off)" in proc.stdout
    proc = run([PY, "scripts/install/render-settings", "render"], home.path, home.env)
    assert "off form" in proc.stdout and len(registered(home.settings())) == 2


# ------------------------------------------------------------------------------- the guards

def guarded_files():
    """Every file settings.json registers, but the switch's own hook."""
    out = set()
    for _, command in registered((ROOT / "settings.json").read_bytes()):
        rel = command.split("/.claude}/", 1)[1].split('"', 1)[0]
        if not rel.endswith("userprompt-harness-switch.sh"):
            out.add(rel)
    return sorted(out)


@pytest.mark.parametrize("rel", guarded_files())
def test_every_registered_hook_asks_the_switch_first(rel):
    text = (ROOT / rel).read_text()
    assert ("harness_switch.exit_if_off()" in text) or ("harness_switch_exit_if_off" in text), rel


# ------------------------------------------------- a Claude Code settings file's switch keys

SWITCH_KEYS = {  # payload: (key, the value an agent writes, the value the file holds before)
    "env CLAUDE_COMMAND_GATE=off": ("env", {"CLAUDE_COMMAND_GATE": "off"}, {"CLAUDE_COMMAND_GATE": "on"}),
    "env CLAUDE_OBLIGATION_STOPGATE=off": ("env", {"CLAUDE_OBLIGATION_STOPGATE": "off"},
                                           {"CLAUDE_OBLIGATION_STOPGATE": "block"}),
    "env CLAUDE_COMPAT_RUNTIME=codex": ("env", {"CLAUDE_COMPAT_RUNTIME": "codex"}, {"CLAUDE_COMPAT_RUNTIME": "claude"}),
    "hooks": ("hooks", {"PreToolUse": [{"hooks": [{"type": "command", "command": "true"}]}]},
              {"PreToolUse": [{"hooks": [{"type": "command", "command": "false"}]}]}),
    "permissions.allow": ("permissions", {"allow": ["Bash(rm:*)"]}, {"allow": ["Bash(ls:*)"]}),
}
SETTINGS_FORMS = ("Write", "Edit", "MultiEdit", "Bash >", "Bash tee", "Bash cp onto", "Bash mv onto",
                  "Bash sed -i", "Bash rm", "Bash mv away")


@pytest.fixture(scope="module")
def guard_home(tmp_path_factory):
    """One harness home (the tree's files) for the settings-file cases; each case has its own project."""
    root = tmp_path_factory.mktemp("guard")
    h = root / "claude"
    for rel in tree_files():
        dst = h / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dst)
    (root / "state").mkdir()
    env = dict(os.environ, HOME=str(root), CLAUDE_CONFIG_DIR=str(h), CLAUDE_HOME=str(h),
               CLAUDE_STATE_DIR=str(root / "state"), CLAUDE_PROJECT_DIR=str(root / "proj"))
    for name in ("CLAUDE_TASK_ID", "CLAUDE_SESSION_ID", "CLAUDE_COMPAT_RUNTIME", "CLAUDE_AGENT_ID"):
        env.pop(name, None)
    return Home(h, env)


@pytest.fixture()
def proj(tmp_path):
    (tmp_path / "proj" / ".claude").mkdir(parents=True)
    return tmp_path / "proj"


def gate(home, proj, tool, tool_input, actor="main", session="S1"):
    payload = {"tool_name": tool, "tool_input": tool_input, "cwd": str(proj), "session_id": session}
    if actor == "subagent":
        payload["agent_id"] = "sub-1"
    return home.hook("hooks/pretool-write-gate.py", payload)


def switch_call(proj, payload, fname, form):
    """(tool, tool_input) of one A1 case, the file and its source set up as the form needs."""
    key, value, before = SWITCH_KEYS[payload]
    target, rel = proj / ".claude" / fname, ".claude/" + fname
    wanted = json.dumps({"model": "opus", key: value})
    source = proj.parent / "payload.json"
    source.write_text(wanted)
    if form in ("Edit", "MultiEdit"):
        target.write_text('{"model": "opus"}')
        edit = {"old_string": '"model": "opus"', "new_string": '"model": "opus", "%s": %s' % (key, json.dumps(value))}
        return form, (dict(edit, file_path=str(target)) if form == "Edit" else {"file_path": str(target), "edits": [edit]})
    if form == "Write":
        return "Write", {"file_path": str(target), "content": wanted}
    if form in ("Bash sed -i", "Bash rm", "Bash mv away"):
        target.write_text(json.dumps({"model": "opus", key: before}))
    old, new = json.dumps(before).split('"')[3], json.dumps(value).split('"')[3]  # a value inside the key, no key named
    return "Bash", {"command": {
        "Bash >": "echo '%s' > %s" % (wanted, rel),
        "Bash tee": "echo '%s' | tee %s" % (wanted, rel),
        "Bash cp onto": "cp %s %s" % (source, rel),
        "Bash mv onto": "mv %s %s" % (source, rel),
        "Bash sed -i": "sed -i 's/%s/%s/' %s" % (old, new, rel),
        "Bash rm": "rm %s" % rel,
        "Bash mv away": "mv %s /tmp/away.json" % rel}[form]}


@pytest.mark.parametrize("form", SETTINGS_FORMS)
@pytest.mark.parametrize("fname", ["settings.local.json", "settings.json"])
@pytest.mark.parametrize("payload", sorted(SWITCH_KEYS))
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_an_agent_cannot_change_a_settings_files_switch_keys(guard_home, proj, payload, fname, form, actor):
    tool, tool_input = switch_call(proj, payload, fname, form)
    proc = gate(guard_home, proj, tool, tool_input, actor)
    assert proc.returncode == 2 and "harness-switch:" in proc.stderr and "Claude Code settings file" in proc.stderr, \
        (tool_input, proc.stderr)
    assert "edit the file yourself, or type /allow" in proc.stderr


@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_disable_all_hooks_stays_refused_in_a_projects_settings_file(guard_home, proj, actor):
    target = proj / ".claude" / "settings.local.json"
    proc = gate(guard_home, proj, "Write", {"file_path": str(target), "content": '{"disableAllHooks": true}'}, actor)
    assert proc.returncode == 2 and "sets disableAllHooks" in proc.stderr, proc.stderr
    proc = gate(guard_home, proj, "Bash", {"command": "echo '{\"disableAllHooks\": true}'>.claude/settings.json"}, actor)
    assert proc.returncode == 2 and "disableAllHooks" in proc.stderr, proc.stderr  # an attached redirect too


@pytest.mark.parametrize("name, setup, tool, tool_input", [
    ("Edit drops permissions.deny", '{"permissions": {"deny": ["Bash(rm:*)"]}}', "Edit",
     {"old_string": '"deny": ["Bash(rm:*)"]', "new_string": '"deny": []'}),
    ("Edit breaks the JSON", '{"permissions": {"deny": ["Bash(rm:*)"]}}', "Edit",
     {"old_string": "}}", "new_string": "}"}),
    ("Edit removes hooks", '{"model": "opus", "hooks": {"Stop": []}}', "Edit",
     {"old_string": ', "hooks": {"Stop": []}', "new_string": ""}),
    ("Edit an old_string the file lacks", '{"env": {"A": "1"}}', "Edit", {"old_string": "nowhere", "new_string": "x"}),
    ("NotebookEdit", '{"env": {"A": "1"}}', "NotebookEdit", {"new_source": "{}"}),
    ("Edit a file load_settings finds unusable", '{"model": "opus", "env": []}', "Edit",
     {"old_string": '"opus"', "new_string": '"sonnet"'}),
    ("Write with NaN", None, "Write", {"content": '{"model": NaN}'}),
])
def test_a_settings_change_the_rule_cannot_prove_harmless_is_refused(guard_home, proj, name, setup, tool, tool_input):
    target = proj / ".claude" / "settings.local.json"
    if setup is not None:
        target.write_text(setup)
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    proc = gate(guard_home, proj, tool, dict(tool_input, **{key: str(target)}))
    if name == "Write with NaN":  # JSON.parse refuses NaN: no keys there to change, nothing refused
        assert proc.returncode == 0, proc.stderr
    else:
        assert proc.returncode == 2 and "Claude Code settings file" in proc.stderr, (name, proc.stderr)


@pytest.mark.parametrize("rel", ["managed-settings.json", "managed-settings.d/50-team.json", ".claude.json",
                                 "deep/dir/.claude/settings.local.json"])
def test_every_settings_source_the_cli_reads_is_covered(guard_home, proj, rel):
    target = proj / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"mcpServers": {}}')
    edit = {"file_path": str(target), "old_string": '"mcpServers": {}', "new_string": '"mcpServers": {"x": {}}'}
    assert gate(guard_home, proj, "Edit", edit).returncode == 0  # another key: free
    edit["new_string"] = '"mcpServers": {}, "env": {"CLAUDE_COMMAND_GATE": "off"}'
    proc = gate(guard_home, proj, "Edit", edit)
    assert proc.returncode == 2 and "changes env in" in proc.stderr, proc.stderr


@pytest.mark.parametrize("command", [
    "echo '{\"env\": {\"CLAUDE_COMMAND_GATE\": \"off\"}}'>.claude/settings.local.json",
    "cd .claude && echo '{\"env\": {}}' > settings.json",
    "rm -rf .claude",
    "mv .claude /tmp/gone",
    "cp -r /tmp/elsewhere/.claude ./",
    "cp /tmp/settings.local.json .claude/",
    "perl -pi -e 's/on/off/' .claude/settings.local.json",
    "bash -c \"sed -i 's/on/off/' .claude/settings.local.json\"",
    "git checkout HEAD~1 -- .claude/settings.local.json",
    "dd if=/tmp/p.json of=.claude/settings.local.json",
    "cat > .claude/settings.json <<'EOF'\n{\"model\": \"opus\"}\nEOF",
    "bash <<'EOF'\nrm .claude/settings.local.json\nEOF",
    "echo '{\"model\": \"opus\"}' > .claude/settings.local.json",  # the literal echo, onto a file with env
])
def test_bash_writes_the_rule_refuses(guard_home, proj, command):
    (proj / ".claude" / "settings.local.json").write_text('{"env": {"CLAUDE_COMMAND_GATE": "on"}}')
    (proj / ".claude" / "settings.json").write_text('{"permissions": {"deny": ["Bash(rm:*)"]}}')
    proc = gate(guard_home, proj, "Bash", {"command": command})
    assert proc.returncode == 2 and "Claude Code settings file" in proc.stderr, (command, proc.stderr)


@pytest.mark.parametrize("command", [
    "(echo '{\"env\": {}}' > .claude/settings.json)",
    "{ echo '{\"env\": {}}'; } > .claude/settings.json",
    "for f in a; do echo x; done > .claude/settings.json",
    "X=.claude; echo '{}' > $X/settings.json",
    "echo $(rm .claude/settings.local.json)",
    "echo `rm .claude/settings.local.json`",
    "bash <<< 'rm .claude/settings.local.json'",
    "echo \"unterminated > .claude/settings.json",
])
def test_bash_writes_the_parser_reads_are_refused(guard_home, proj, command):
    """A subshell, a group, a loop's redirection, an assigned name, a substitution, a here-string fed
    to a shell: each writes the file as the plain redirect does. Text bash cannot read stays refused."""
    (proj / ".claude" / "settings.local.json").write_text('{"env": {"CLAUDE_COMMAND_GATE": "on"}}')
    (proj / ".claude" / "settings.json").write_text('{"permissions": {"deny": ["Bash(rm:*)"]}}')
    proc = gate(guard_home, proj, "Bash", {"command": command})
    assert proc.returncode == 2 and "Claude Code settings file" in proc.stderr, (command, proc.stderr)


@pytest.mark.parametrize("spaced, attached", [
    ("echo '{\"disableAllHooks\":true}' > settings.local.json", "echo '{\"disableAllHooks\":true}'>settings.local.json"),
    ("echo disableAllHooks > settings.json", "echo disableAllHooks>settings.json"),
    ("echo x > settings.json", "echo x>settings.json"),
    ("grep -c env /tmp/n > settings.json", "grep -c env /tmp/n>settings.json"),
])
def test_an_attached_redirect_reads_as_the_spaced_one(guard_home, spaced, attached):
    """From the harness home: `x>settings.json` is the write `x > settings.json` is."""
    decisions = []
    for command in (spaced, attached):
        proc = guard_home.hook("hooks/pretool-write-gate.py", {"tool_name": "Bash", "tool_input": {"command": command}})
        decisions.append((proc.returncode, "harness-switch:" in proc.stderr))
    assert decisions[0] == decisions[1] == (2, True), (spaced, attached, decisions)


def test_a_settings_file_reached_through_a_link_is_one(guard_home, proj):
    real = proj / "real.json"
    real.write_text('{"model": "opus"}')
    (proj / ".claude" / "settings.local.json").symlink_to(real)
    edit = {"file_path": str(proj / ".claude" / "settings.local.json"), "old_string": '"model": "opus"',
            "new_string": '"model": "opus", "env": {"CLAUDE_COMMAND_GATE": "off"}'}
    assert gate(guard_home, proj, "Edit", edit).returncode == 2


# A padded command: the rule reads every written word from the call's directory and every `cd`'s,
# so `cd . && ` repeated made its work grow with the square of the command and run past its budget.
ENV_WRITE = "echo '{\"env\": {}}' > .claude/settings.local.json"


@functools.lru_cache(maxsize=None)
def rule_budget(name: str) -> float:
    """The rule's budget as the write gate's table declares it (hooks/lib/write_gate)."""
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from lib.write_gate import RULES; "
            "print(next(r.budget for r in RULES if r.name == sys.argv[2]))")
    return float(run([PY, "-c", code, str(ROOT / "hooks"), name], ROOT).stdout)


def timed_gate(home, proj, command, actor="main"):
    start = time.monotonic()
    proc = gate(home, proj, "Bash", {"command": command}, actor)
    return proc, time.monotonic() - start


@pytest.mark.parametrize("pads", [300, 1000, 5000])
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_a_padded_settings_write_is_refused_within_the_budget(guard_home, proj, pads, actor):
    (proj / ".claude" / "settings.local.json").write_text('{"env": {"CLAUDE_COMMAND_GATE": "on"}}')
    proc, took = timed_gate(guard_home, proj, "cd . && " * pads + ENV_WRITE, actor)
    assert proc.returncode == 2 and "harness-switch: this Bash command" in proc.stderr, proc.stderr
    assert "Claude Code settings file" in proc.stderr and "budget" not in proc.stderr, proc.stderr  # its own refusal
    assert took < rule_budget("harness-switch"), took  # the whole gate, the rule's run inside it


@pytest.mark.parametrize("pads", [300, 1000, 5000])
@pytest.mark.parametrize("target", ["notes.txt", "config/settings.json"])
def test_a_padded_ordinary_write_is_still_allowed(guard_home, proj, pads, target):
    (proj / ".claude" / "settings.local.json").write_text('{"env": {"CLAUDE_COMMAND_GATE": "on"}}')
    (proj / "config").mkdir()
    proc, took = timed_gate(guard_home, proj, "cd . && " * pads + "echo '{\"env\": {}}' > " + target)
    assert proc.returncode == 0 and "harness-switch" not in proc.stderr and "budget" not in proc.stderr, proc.stderr
    assert took < rule_budget("harness-switch"), took


@pytest.mark.parametrize("command", [
    "echo '{\"env\": {}}' > s",  # s: a link to the settings file, a name no settings file has
    "cd .claude && rm -rf .",
    "cd .claude && rm -rf ./",
    "cd .claude/sub && rm -rf ..",
    "cd .claude/sub && rm -rf ../settings.local.json",
])
def test_a_padded_write_through_a_link_or_a_dot_is_refused(guard_home, proj, command):
    """The rule resolves only a word that can name a settings file: a .json name, .claude,
    managed-settings.d, `.`, `..`, or a link; padding does not hide one."""
    (proj / ".claude" / "settings.local.json").write_text('{"env": {"CLAUDE_COMMAND_GATE": "on"}}')
    (proj / ".claude" / "sub").mkdir()
    (proj / "s").symlink_to(proj / ".claude" / "settings.local.json")
    proc = gate(guard_home, proj, "Bash", {"command": "cd . && " * 300 + command})
    assert proc.returncode == 2 and "Claude Code settings file" in proc.stderr, (command, proc.stderr)
    assert "budget" not in proc.stderr, proc.stderr


def test_a_command_the_rule_cannot_read_inside_its_budget_is_refused(guard_home, proj):
    """Distinct directories times distinct .json words: work no deduplication saves, so the rule can
    still run past its budget. It fails closed: the overrun refuses the call, never lets the env
    write through, as a fail-open overrun did."""
    (proj / ".claude" / "settings.local.json").write_text('{"env": {"CLAUDE_COMMAND_GATE": "on"}}')
    pads = 1000
    command = ("".join("cd d%d && " % i for i in range(pads)) + "touch " +
               " ".join("a%d.json" % i for i in range(pads)) + " && " + ENV_WRITE)
    proc = gate(guard_home, proj, "Bash", {"command": command}, "subagent")
    assert proc.returncode == 2 and "harness-switch" in proc.stderr, proc.stderr


SETTINGS_FREE = [  # reads of settings files, other JSON files, messages, other keys
    ("Bash", {"command": "cat .claude/settings.json .claude/settings.local.json ~/.claude.json"}),
    ("Bash", {"command": "jq .env .claude/settings.local.json"}),
    ("Bash", {"command": "jq '.hooks' .claude/settings.json > /tmp/hooks.json"}),
    ("Bash", {"command": "grep -n CLAUDE_COMMAND_GATE .claude/settings.local.json"}),
    ("Bash", {"command": "git diff .claude/settings.json && git show HEAD:.claude/settings.local.json"}),
    ("Bash", {"command": "git log -p -- .claude/settings.json | head"}),
    ("Bash", {"command": "python3 -c \"import json; print(json.load(open('.claude/settings.json'))['env'])\""}),
    ("Bash", {"command": "python3 -m json.tool .claude/settings.local.json"}),
    ("Bash", {"command": "cp .claude/settings.json /tmp/settings-backup.json"}),
    ("Bash", {"command": "echo '{\"env\": {\"A\": \"1\"}, \"hooks\": {}}' > config/settings.json"}),
    ("Bash", {"command": "sed -i 's/on/off/' config/settings.json package.json"}),
    ("Bash", {"command": "cat > notes.md <<'EOF'\nrm .claude/settings.json; cp x .claude/settings.local.json\nEOF"}),
    ("Bash", {"command": "git commit -m \"Refuse env CLAUDE_COMMAND_GATE=off in /p/.claude/settings.local.json\""}),
    ("Bash", {"command": "git commit -m \"$(cat <<'EOF'\nGuard the settings files\n\necho '{\"env\": {\"CLAUDE_COMPAT_RUNTIME\": \"codex\"}}' > .claude/settings.json, cp x .claude/settings.local.json, sed -i, rm .claude/settings.json: refused.\nEOF\n)\""}),
    ("Bash", {"command": "gh pr create --title t --body \"hooks and permissions of .claude/settings.json; tee /p/.claude/settings.local.json\""}),
    ("Write", {"file_path": "{P}/config/settings.json", "content": '{"env": {"CLAUDE_COMMAND_GATE": "off"}}'}),
    ("Write", {"file_path": "{P}/package.json", "content": '{"hooks": {"pre-commit": "x"}, "env": {}}'}),
    ("Write", {"file_path": "{P}/.claude/settings.local.json", "content": '{"model": "opus", "statusLine": {}}'}),
    ("Edit", {"file_path": "{P}/.claude/settings.json", "old_string": '"model": "opus"', "new_string": '"model": "sonnet"'}),
    ("MultiEdit", {"file_path": "{P}/.claude/settings.json", "edits": [
        {"old_string": '"model": "opus"', "new_string": '"model": "sonnet"'},
        {"old_string": '"env"', "new_string": '"statusLine": {}, "env"'}]}),
]


@pytest.mark.parametrize("tool, tool_input", SETTINGS_FREE)
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_reads_other_files_messages_and_other_keys_stay_free(guard_home, proj, tool, tool_input, actor):
    (proj / ".claude" / "settings.json").write_text(
        '{"model": "opus", "env": {"CLAUDE_COMMAND_GATE": "on"}, "permissions": {"deny": ["Bash(rm:*)"]}}')
    (proj / "config").mkdir()
    tool_input = json.loads(json.dumps(tool_input).replace("{P}", str(proj)))
    proc = gate(guard_home, proj, tool, tool_input, actor)
    assert "harness-switch:" not in proc.stderr, (tool_input, proc.stderr)
    if actor == "main":
        assert proc.returncode == 0, (tool_input, proc.stderr)


def test_dev_step_15s_permission_writer_is_not_refused(guard_home, proj):
    """/dev's Step 15 (commands/dev.md) applies QA-validated permissions to .claude/settings.json through
    `bash scripts/apply-permissions.sh`: an interpreter, whose writes this rule does not see."""
    line = next(ln for ln in (ROOT / "commands" / "dev.md").read_text().splitlines()
                if "apply-permissions.sh" in ln and ln.startswith("python3"))
    command = line.replace("<HARNESS_ROOT>", str(guard_home.path)).replace("<timestamp>", "20260101-120000")
    (proj / ".claude" / "settings.json").write_text('{"permissions": {"allow": []}}')
    proc = gate(guard_home, proj, "Bash", {"command": command})
    assert "harness-switch:" not in proc.stderr and proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------- the owner's /allow, once

def allow(home, proj, text, session):
    """The owner types `/allow <text>`: the registered UserPromptSubmit hook writes the grant."""
    payload = {"hook_event_name": "UserPromptSubmit", "prompt": "/allow " + text, "session_id": session,
               "cwd": str(proj), "transcript_path": str(home.transcript)}
    run(["bash", str(home.path / "hooks" / "userprompt-consent-allowlist.sh")], proj,
        dict(home.env, CLAUDE_PROJECT_DIR=str(proj)), json.dumps(payload))
    assert (Path(home.env["CLAUDE_STATE_DIR"]) / "claude-grants" / ("%s.json" % session)).is_file()


def spent(home, proj, tool, tool_input, session, actor="main"):
    """The call ran: the registered PostToolUse consumer spends the grant it used."""
    payload = {"hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": tool_input, "session_id": session,
               "cwd": str(proj), "tool_response": {"stdout": "", "stderr": "", "interrupted": False}}
    if actor == "subagent":
        payload["agent_id"] = "sub-1"
    run([PY, str(home.path / "hooks" / "posttool-allowlist-consume.py")], proj, home.env, json.dumps(payload))


@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_an_allow_grant_naming_the_command_lets_one_bash_write_through(guard_home, proj, actor):
    target = proj / ".claude" / "settings.local.json"
    target.write_text('{"env": {"CLAUDE_COMMAND_GATE": "on"}}')
    command = "sed -i s/on/off/ .claude/settings.local.json"
    session = "grant-bash-" + actor
    assert gate(guard_home, proj, "Bash", {"command": command}, actor, session).returncode == 2
    allow(guard_home, proj, command, session)
    other = gate(guard_home, proj, "Bash", {"command": "rm .claude/settings.local.json"}, actor, session)
    assert other.returncode == 2  # the grant names one command, not this one
    proc = gate(guard_home, proj, "Bash", {"command": command}, actor, session)
    assert proc.returncode == 0 and "harness-switch:" not in proc.stderr, proc.stderr  # a Bash grant reaches a subagent
    spent(guard_home, proj, "Bash", {"command": command}, session, actor)
    assert gate(guard_home, proj, "Bash", {"command": command}, actor, session).returncode == 2


@pytest.mark.parametrize("tool, grant", [("Write", "Write {T}"), ("Write", "Write"), ("Edit", "Edit"), ("MultiEdit", "MultiEdit")])
def test_an_allow_grant_lets_one_main_agent_write_through_and_never_a_subagents(guard_home, proj, tool, grant):
    target = proj / ".claude" / "settings.json"
    if tool == "Write":
        tool_input = {"file_path": str(target), "content": '{"env": {"CLAUDE_COMMAND_GATE": "off"}}'}
    else:
        target.write_text('{"env": {"CLAUDE_COMMAND_GATE": "on"}}')
        edit = {"old_string": '"on"', "new_string": '"off"'}
        tool_input = dict(edit, file_path=str(target)) if tool == "Edit" else {"file_path": str(target), "edits": [edit]}
    session = "grant-%s-%s" % (tool, grant.split()[-1] == "{T}")
    allow(guard_home, proj, grant.replace("{T}", str(target)), session)
    sub = gate(guard_home, proj, tool, tool_input, "subagent", session)
    assert sub.returncode == 2 and "Claude Code settings file" in sub.stderr  # a Write or tool grant is the main agent's
    proc = gate(guard_home, proj, tool, tool_input, "main", session)
    assert proc.returncode == 0 and "harness-switch:" not in proc.stderr, proc.stderr
    spent(guard_home, proj, tool, tool_input, session)
    assert gate(guard_home, proj, tool, tool_input, "main", session).returncode == 2


def test_an_allow_grant_does_not_open_disable_all_hooks(guard_home, proj):
    target = proj / ".claude" / "settings.local.json"
    allow(guard_home, proj, "Write %s" % target, "grant-dah")
    proc = gate(guard_home, proj, "Write", {"file_path": str(target), "content": '{"disableAllHooks": true}'}, "main", "grant-dah")
    assert proc.returncode == 2 and "sets disableAllHooks" in proc.stderr
