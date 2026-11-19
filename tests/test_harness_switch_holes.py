"""Holes of the harness-switch rule the hardcode audit of 2026-11-19 reproduced (its findings 3, 4, 7).

- Finding 3: a prompt that types /harness is refused whatever tool carries it. The rule reads every
  tool's input (hooks/lib/write_gate: tools None), so a tool it has never heard of is covered; only
  the CLI's own tools that deliver no prompt are named, and they pass.
- Finding 4: scripts/harness-switch recognises a Claude Code process as the npm package names it
  (bin/claude.exe) and as the native installer does; the recogniser alone is tested, the switch is
  never run.
- Finding 7, the half that let a write through: `git stash push` of a settings file, and find's
  actions that run a program, write a file or delete.
"""
from __future__ import annotations

import pytest

from tests.test_harness_switch import ROOT, gate, guard_home, load_switch, proj  # noqa: F401 -- fixtures and helpers

NPM_BINARY = "/usr/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe"  # the npm package's native binary
INSTALLER_COPY = "/usr/local/share/claude/versions/2.1.326"                     # the native installer's copy
LAUNCHER = ("/usr/bin/python3.12", ["/usr/bin/python3", "/usr/local/bin/claude-launcher", "--verbose"])  # a script

# ---------------------------------------------------------------------------------- finding 3

CARRIERS = {  # (tool, tool_input): each delivers its text to a session, or may
    "paseo send": ("mcp__paseo__send_agent_prompt", {"agentId": "a", "prompt": "/harness off"}),
    "paseo create": ("mcp__paseo__create_agent", {"title": "t", "provider": "claude/x", "initialPrompt": "/harness off"}),
    "paseo heartbeat": ("mcp__paseo__create_heartbeat", {"cron": "* * * * *", "prompt": "/harness on"}),
    "paseo schedule": ("mcp__paseo__create_schedule", {"cron": "* * * * *", "prompt": "/harness off"}),
    "paseo terminal keys": ("mcp__paseo__send_terminal_keys", {"terminalId": "t", "keys": "/harness off\n"}),
    "an MCP tool no list names, a nested key": ("mcp__some_server__enqueue", {"job": {"steps": [{"say": "/harness off"}]}}),
    "a tool the CLI adds later": ("SomeLaterTool", {"action": "create", "body": {"text": "do this:\n/harness off"}}),
    "a dispatch that is the command": ("Agent", {"description": "d", "prompt": "/harness off", "subagent_type": "dev"}),
    "a dispatch in the command-name form": ("Task", {"description": "d", "subagent_type": "dev", "prompt":
                                                     "<command-name>/harness</command-name><command-args>on</command-args>"}),
    "the command-name form": ("CronCreate", {"cron": "* * * * *", "prompt": "<command-name>/harness</command-name>\n"
                                                                              "<command-args>off</command-args>"}),
}
NOT_CARRIERS = {  # the legitimate neighbours: the same words where no session takes them as typed
    "Read": ("Read", {"file_path": "/harness"}),
    "Grep for the command": ("Grep", {"pattern": "/harness off", "path": "commands"}),
    "Glob": ("Glob", {"pattern": "**/harness*"}),
    "a todo that names it": ("TodoWrite", {"todos": [{"content": "Test /harness off", "status": "pending",
                                                      "activeForm": "Testing /harness off"}]}),
    "a question to the owner": ("AskUserQuestion", {"questions": [{"question": "Type /harness off now?"}]}),
    "a search": ("WebSearch", {"query": "claude code /harness off"}),
    "a dispatch that quotes it": ("Agent", {"description": "d", "subagent_type": "dev",
                                             "prompt": "Fix the report `/harness off` prints.\n/harness off must name the home."}),
    "a dispatch that starts with it": ("Agent", {"description": "/harness off report", "subagent_type": "dev",
                                                  "prompt": "/harness off prints the wrong home. Find out why."}),
    "a tool search": ("ToolSearch", {"query": "/harness"}),
    "a watcher that names it": ("Monitor", {"command": "tail -f build.log", "description": "watch for /harness off"}),
    "a notification to the owner": ("PushNotification", {"message": "Type /harness on when you are back"}),
    "a task of the caller's own list": ("TaskCreate", {"subject": "Test /harness off", "description": "/harness off"}),
    "a daemon prompt without it": ("mcp__paseo__send_agent_prompt", {"agentId": "a", "prompt": "/dev fix the report"}),
    "a daemon prompt naming a path": ("mcp__paseo__create_agent", {"title": "t", "initialPrompt": "read /harness/notes.md"}),
    "a later tool without it": ("SomeLaterTool", {"action": "list"}),
}


@pytest.mark.parametrize("name", sorted(CARRIERS))
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_a_prompt_that_types_harness_is_refused_through_any_tool(guard_home, proj, name, actor):
    tool, tool_input = CARRIERS[name]
    proc = gate(guard_home, proj, tool, tool_input, actor)
    assert proc.returncode == 2 and "harness-switch: this %s carries a prompt that types /harness" % tool in proc.stderr, proc.stderr


@pytest.mark.parametrize("name", sorted(NOT_CARRIERS))
def test_the_same_words_pass_where_no_session_takes_them_as_typed(guard_home, proj, name):
    tool, tool_input = NOT_CARRIERS[name]
    proc = gate(guard_home, proj, tool, tool_input)
    assert "harness-switch" not in proc.stderr, proc.stderr


def test_the_rule_sees_every_tool():
    """No list of tool names stands between a call and the rule: a tool added tomorrow reaches it."""
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from lib.write_gate import RULES; "
            "rule = next(r for r in RULES if r.name == 'harness-switch'); "
            "print(rule.tools, all(rule.applies(t) for t in sys.argv[2:]))")
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-c", code, str(ROOT / "hooks"), "mcp__paseo__send_agent_prompt",
                          "mcp__x__y", "SomeLaterTool", "Read"], capture_output=True, text=True, check=True).stdout
    assert out.split() == ["None", "True"]


# ---------------------------------------------------------------------------------- finding 4

@pytest.mark.parametrize("exe, argv", [
    (NPM_BINARY, ["/usr/bin/claude", "--output-format", "stream-json"]),   # as a global npm install runs it
    (NPM_BINARY + " (deleted)", ["/usr/bin/claude"]),                      # the same binary after an upgrade replaced it
    ("/usr/local/bin/claude (deleted)", ["claude"]),
    ("claude.exe", ["claude.exe", "-p", "x"]),                             # another user's process: the name is all there is
    (INSTALLER_COPY, ["claude"]),                                          # the native installer
    (INSTALLER_COPY + " (deleted)", ["claude"]),
])
def test_a_claude_code_process_is_recognised_as_each_install_names_it(exe, argv):
    assert load_switch().looks_like_claude(exe, argv) is True


@pytest.mark.parametrize("exe, argv", [
    LAUNCHER,
    ("/usr/bin/bash", ["bash", "/usr/local/bin/claude.exe"]),                                            # a script of that name
    ("/usr/lib/node_modules/@anthropic-ai/claude-code/vendor/ripgrep/x64-linux/rg", ["rg", "x"]),        # a tool it ships
    ("/usr/bin/node", ["node", "/opt/agents/daemon.js"]),
])
def test_a_process_that_is_not_a_session_is_not_recognised(exe, argv):
    assert load_switch().looks_like_claude(exe, argv) is False


def _ancestry(session, outer=None):
    """pid: (parent, executable, argv), as _process reads it: the hook, the session it runs in, and
    above it either a launcher script a daemon starts (the owner's own session) or an agent's Bash
    call inside another session (`outer`)."""
    table = {
        100: (90, "/usr/bin/python3.12", ["python3", "scripts/harness-switch", "hook"]),
        90: (80, "/usr/bin/bash", ["bash", "hooks/userprompt-harness-switch.sh"]),
        80: (70, session, ["/usr/bin/claude", "-p", "/harness off"]),
        50: (40, *LAUNCHER),
        40: (1, "/usr/bin/node", ["node", "/opt/agents/daemon.js"]),
    }
    if outer is None:
        table[80] = (50, session, ["/usr/bin/claude", "--output-format", "stream-json"])
    else:
        table[70] = (60, "/usr/bin/bash", ["bash", "-c", "claude -p '/harness off'"])
        table[60] = (50, outer, ["/usr/bin/claude", "--output-format", "stream-json"])
    return table


@pytest.mark.parametrize("session", [NPM_BINARY, INSTALLER_COPY])
@pytest.mark.parametrize("outer", [NPM_BINARY, INSTALLER_COPY, NPM_BINARY + " (deleted)"])
def test_a_session_inside_a_session_is_recognised_as_each_install_names_it(monkeypatch, session, outer):
    switch = load_switch()
    table = _ancestry(session, outer)
    monkeypatch.setattr(switch, "_process", lambda pid: table.get(pid))
    assert switch.nested_claude(90) == (60, "/usr/bin/claude --output-format stream-json")
    assert [pid for pid, _ in switch.claude_processes(100)] == [80, 60]  # the launcher script is no session


@pytest.mark.parametrize("session", [NPM_BINARY, INSTALLER_COPY])
def test_the_owners_own_session_is_not_taken_for_a_nested_one(monkeypatch, session):
    switch = load_switch()
    table = _ancestry(session)
    monkeypatch.setattr(switch, "_process", lambda pid: table.get(pid))
    assert [pid for pid, _ in switch.claude_processes(100)] == [80]
    assert switch.nested_claude(90) is None


@pytest.mark.parametrize("command", [
    NPM_BINARY + " -p '/harness off'",
    "claude.exe -p '/harness on'",
    "echo '/harness off' | claude.exe",
])
def test_bash_cannot_type_harness_into_the_npm_binary(guard_home, proj, command):
    proc = gate(guard_home, proj, "Bash", {"command": command})
    assert proc.returncode == 2 and "types /harness into a Claude Code session" in proc.stderr, proc.stderr


# ---------------------------------------------------------------------------------- finding 7

SETTINGS = ".claude/settings.json"
WRITES_THE_RULE_TOOK_FOR_READS = [
    "git stash push -- " + SETTINGS,
    "git stash -- " + SETTINGS,
    "git stash push --include-untracked -- .claude/settings.local.json",
    "find %s -execdir rm {} +" % SETTINGS,
    "find %s -ok rm {} ;" % SETTINGS,
    "find %s -okdir rm {} ;" % SETTINGS,
    "find %s -execdir truncate -s 0 {} ;" % SETTINGS,
    "find . -maxdepth 0 -fprint " + SETTINGS,
    "find . -maxdepth 0 -fprint0 " + SETTINGS,
    "find . -maxdepth 0 -fprintf %s '{}'" % SETTINGS,
    "find . -maxdepth 0 -fls " + SETTINGS,
]
READS = [  # the legitimate neighbours: an ordinary find and git's reads of the same file
    "find .claude -name settings.json",
    "find %s -newer README.md -print" % SETTINGS,
    "find . -name 'settings*.json' -type f",
    "ls -fls " + SETTINGS,
    "git diff -- " + SETTINGS,
    "git log --oneline -- " + SETTINGS,
    "git show HEAD:" + SETTINGS,
    "git status --short " + SETTINGS,
    "git blame " + SETTINGS,
    "git stash list",
    "git stash show -p stash@{0} -- " + SETTINGS,
    "cat " + SETTINGS,
]


@pytest.mark.parametrize("command", WRITES_THE_RULE_TOOK_FOR_READS)
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_a_stash_or_a_find_action_on_a_settings_file_is_a_write(guard_home, proj, command, actor):
    (proj / ".claude" / "settings.json").write_text('{"permissions": {"allow": []}}\n')
    (proj / ".claude" / "settings.local.json").write_text('{"env": {"A": "1"}}\n')
    proc = gate(guard_home, proj, "Bash", {"command": command}, actor)
    assert proc.returncode == 2 and "harness-switch: this Bash command may change env, hooks, disableAllHooks " \
        "or permissions" in proc.stderr, proc.stderr


@pytest.mark.parametrize("command", READS)
def test_an_ordinary_find_and_a_git_read_of_a_settings_file_pass(guard_home, proj, command):
    (proj / ".claude" / "settings.json").write_text('{"permissions": {"allow": []}}\n')
    proc = gate(guard_home, proj, "Bash", {"command": command})
    assert "harness-switch" not in proc.stderr, proc.stderr
