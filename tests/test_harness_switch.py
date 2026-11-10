"""/harness off | on | status (commands/harness.md, scripts/harness-switch).

Each test builds a harness home the way the full install leaves one: a git checkout of this
tree, the settings filter registered, an overlay with the owner's own entries, the machine form
rendered, Claude Code's config dir the home itself. The switch is driven as the owner drives it:
a UserPromptSubmit payload with the typed prompt, through the registered hook.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
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

    def switch(self, verb, env=None):
        payload = {"hook_event_name": "UserPromptSubmit", "prompt": "/harness " + verb, "session_id": "S1",
                   "transcript_path": str(self.transcript), "cwd": str(self.path)}
        return run(["bash", str(self.path / "hooks" / "userprompt-harness-switch.sh")], self.path,
                   dict(self.env, **(env or {})), json.dumps(payload), check=False)

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


def test_the_command_is_owner_only_and_its_hook_ignores_a_subagent(home):
    text = (ROOT / "commands" / "harness.md").read_text()
    assert "\ndisable-model-invocation: true\n" in text.split("\n---", 1)[0]
    assert "Skill(harness:*)" in json.loads((ROOT / "settings.json").read_text())["permissions"]["deny"]
    assert home.prompt("/harness off", agent_id="sub-1") is None
    assert not (home.path / ".harness-switch").exists()
    assert home.prompt("please run /harness off for me") is None
    assert not (home.path / ".harness-switch").exists()


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
