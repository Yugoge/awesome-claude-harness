"""P5 R2, R3, R5: what no caller writes, deletes or renames, and the scheduled prompt that types a command.

hooks/pretool-tool-policy.py refuses, before every other rule and for the main agent and every
subagent alike, a write, delete or rename of the harness home's settings.machine.json,
private-literals.txt, scripts/check-public-core.sh, scripts/install/render-settings,
hooks/git-hooks/pre-commit, .git/config, .git/hooks/ and .gitattributes; of a session transcript
(``${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects/**/*.jsonl``) and the agent meta beside it; and of a
/do task sidecar (``claude-do-task-*.json`` in the state dir). A product repository's files of the
same names, the graphify sidecars and every other path stay writable. A ScheduleWakeup prompt that
types a harness command outside CONTROL is refused; a CronCreate prompt's fired record is measured
(P1's COV-7) and excluded from the human's prompts, so it is not.

The harness home is this checkout (the hook resolves it from its own location); only paths are
judged, nothing is created.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
HOOK = os.path.join(ROOT, "hooks", "pretool-tool-policy.py")
SID = "0c1d2e3f-4a5b-4c6d-8e7f-0a1b2c3d4e5f"
R3 = ("scripts/check-public-core.sh", "scripts/install/render-settings", "hooks/git-hooks/pre-commit",
      ".git/config", ".git/hooks/pre-commit", ".gitattributes")
CALLERS = {"main": None, "dev": ("a0dev", "dev"), "ba": ("a0ba", "ba")}
# A product repository outside /tmp and /var/tmp (the scratch rule denies every role there), never created.
PRODUCT = "/nonexistent-p5-protected-paths/product"


def run(tmp_path, tool: str, tool_input: dict, caller=None, state: bool = True, cwd=None):
    home = tmp_path / "home"
    payload = {"session_id": SID, "transcript_path": str(home / ".claude" / "projects" / "-p" / f"{SID}.jsonl"),
               "cwd": str(cwd or PRODUCT), "hook_event_name": "PreToolUse", "tool_name": tool,
               "tool_input": tool_input}
    if caller:
        payload.update(agent_id=caller[0], agent_type=caller[1], subagent_type=caller[1])
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_PROJECT_DIR=PRODUCT,
               PYTHONDONTWRITEBYTECODE="1")
    if state:
        env["CLAUDE_STATE_DIR"] = str(tmp_path / "state")
    return subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True,
                          cwd=str(tmp_path), env=env, timeout=60)


def forms(path: str) -> dict:
    """Each way to write, delete or rename ``path``: tool -> input."""
    return {"Write": ("Write", {"file_path": path, "content": "x"}),
            "Edit": ("Edit", {"file_path": path, "old_string": "a", "new_string": "b"}),
            "echo": ("Bash", {"command": f"echo x > {path}"}),
            "rm": ("Bash", {"command": f"rm -f {path}"}),
            "mv": ("Bash", {"command": f"mv {path} {path}.bak"}),
            "mv-in": ("Bash", {"command": f"mv /elsewhere/x '{path}'"}),
            "sed": ("Bash", {"command": f"sed -i 's/a/b/' {path}"})}


def assert_denied(proc, what: str) -> None:
    assert proc.returncode == 2, proc.stderr
    assert proc.stderr.startswith("BLOCKED by tool-policy.v1: "), proc.stderr
    reason = json.loads(proc.stderr.splitlines()[0].split(": ", 1)[1])["deny_reason"]
    assert reason.endswith(f"is {what}: no agent writes, deletes or renames it (D11/D12)"), reason


def r2_paths(tmp_path) -> dict:
    config = tmp_path / "home" / ".claude" / "projects" / "-p"
    return {"settings.machine.json": (os.path.join(ROOT, "settings.machine.json"), "the harness home's settings.machine.json"),
            "private-literals.txt": (os.path.join(ROOT, "private-literals.txt"), "the harness home's private-literals.txt"),
            "transcript": (str(config / f"{SID}.jsonl"), "a session transcript or its subagent meta"),
            "subagent transcript": (str(config / SID / "subagents" / "agent-a1.jsonl"),
                                    "a session transcript or its subagent meta"),
            "subagent meta": (str(config / SID / "subagents" / "agent-a1.meta.json"),
                              "a session transcript or its subagent meta"),
            "do sidecar": (str(tmp_path / "state" / f"claude-do-task-{SID}.json"), "a /do task sidecar")}


@pytest.mark.parametrize("caller", list(CALLERS))
@pytest.mark.parametrize("form", ["Write", "Edit", "echo", "rm", "mv", "mv-in"])
@pytest.mark.parametrize("name", ["settings.machine.json", "private-literals.txt", "transcript", "subagent transcript",
                                  "subagent meta", "do sidecar"])
def test_r2_paths_are_denied_to_every_caller(tmp_path, caller, form, name):
    path, what = r2_paths(tmp_path)[name]
    assert_denied(run(tmp_path, *forms(path)[form], CALLERS[caller]), what)


@pytest.mark.parametrize("form", ["Write", "echo", "rm", "mv"])
def test_the_do_sidecar_without_a_state_dir_is_the_default_roots(tmp_path, form):
    assert_denied(run(tmp_path, *forms(f"/tmp/claude-do-task-{SID}.json")[form], state=False), "a /do task sidecar")
    # ... and named through the variable the agent's shell holds
    proc = run(tmp_path, "Bash", {"command": f'rm -f "$CLAUDE_STATE_DIR/claude-do-task-{SID}.json"'})
    assert_denied(proc, "a /do task sidecar")


@pytest.mark.parametrize("caller", list(CALLERS))
@pytest.mark.parametrize("form", ["Write", "Edit", "rm", "sed"])
@pytest.mark.parametrize("rel", R3)
def test_r3_engines_and_git_files_of_the_harness_home_are_denied(tmp_path, caller, form, rel):
    proc = run(tmp_path, *forms(os.path.join(ROOT, rel))[form], CALLERS[caller])
    assert_denied(proc, f"the harness home's {rel}")


def test_a_relative_name_is_read_from_the_working_directory(tmp_path):
    assert_denied(run(tmp_path, "Bash", {"command": "sed -i s/a/b/ .gitattributes"}, cwd=ROOT),
                  "the harness home's .gitattributes")
    assert_denied(run(tmp_path, "Bash", {"command": "rm -r .git"}, CALLERS["dev"], cwd=ROOT),
                  "a directory holding the harness home's protected files or the session transcripts")


@pytest.mark.parametrize("form", ["Write", "Edit", "echo", "rm", "mv", "sed"])
@pytest.mark.parametrize("rel", R3 + ("settings.machine.json", "private-literals.txt"))
def test_the_same_names_in_a_product_repository_stay_writable(tmp_path, form, rel):
    proc = run(tmp_path, *forms(os.path.join(PRODUCT, rel))[form], CALLERS["dev"])
    assert proc.returncode == 0, proc.stderr
    assert not os.path.exists(os.path.dirname(PRODUCT))


def test_reads_and_other_config_files_stay_allowed(tmp_path):
    for path, _ in r2_paths(tmp_path).values():
        assert run(tmp_path, "Read", {"file_path": path}).returncode == 0
        assert run(tmp_path, "Bash", {"command": f"cat {path} | head"}).returncode == 0
    memory = tmp_path / "home" / ".claude" / "projects" / "-p" / "memory" / "MEMORY.md"
    assert run(tmp_path, "Write", {"file_path": str(memory), "content": "x"}).returncode == 0
    assert run(tmp_path, "Bash", {"command": f"git rm --cached {ROOT}/private-literals.txt"}).returncode == 0


def test_the_graphify_sidecar_commands_stay_allowed(tmp_path):
    # commands/dev-overnight.md's pre-BA hydrator block, its placeholders bound, as the main agent runs it.
    text = open(os.path.join(ROOT, "commands", "dev-overnight.md"), encoding="utf-8").read()
    block = next(b for b in re.findall(r"```bash\n(.*?)```", text, re.S) if "graphify/requirement.txt" in b)
    command = re.sub(r"<DEV_SESSION_ID>", "20261101-091100", block)
    command = re.sub(r"\{pipeline\.(\w+)\}", lambda m: {"index": "1"}.get(m[1], "x"), command)
    assert run(tmp_path, "Bash", {"command": command}).returncode == 0


def _wake_prompt():
    sys.path.insert(0, os.path.join(ROOT, "hooks"))
    try:
        from lib import overnight
    finally:
        sys.path.pop(0)
    return getattr(overnight, "WAKE_PROMPT", None)


@pytest.mark.parametrize("prompt,denied", [
    ("/spec draft the cache spec", True), ("/dev", True), ("/push origin", True), ("/codex review", True),
    ("<command-name>/close</command-name>", True),
    ("/restart", False), ("/checkpoint", False), ("/babysit-prs", False), ("check the build, then /dev", False),
    ("carry on with the checklist", False)])
def test_a_schedulewakeup_prompt_typing_a_harness_command_outside_control_is_denied(tmp_path, prompt, denied):
    proc = run(tmp_path, "ScheduleWakeup", {"prompt": prompt, "delaySeconds": 600, "reason": "r"})
    assert proc.returncode == (2 if denied else 0), proc.stderr
    if denied:
        reason = json.loads(proc.stderr.splitlines()[0].split(": ", 1)[1])["deny_reason"]
        assert reason.startswith("a ScheduleWakeup prompt that types /"), reason
    # The fired CronCreate record is measured and excluded from the human's prompts (COV-7): no rule.
    assert run(tmp_path, "CronCreate", {"cron": "*/5 * * * *", "prompt": prompt, "recurring": True}).returncode == 0


def test_the_overnight_wake_prompt_is_never_denied(tmp_path):
    wake = _wake_prompt() or "carry on with the checklist"  # lib.overnight's own text once it holds one
    for tool in ("ScheduleWakeup", "CronCreate"):
        assert run(tmp_path, tool, {"cron": "3 * * * *", "prompt": wake, "recurring": True}).returncode == 0
