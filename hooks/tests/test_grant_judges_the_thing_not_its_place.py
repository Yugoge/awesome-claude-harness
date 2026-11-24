"""A write grant decides from what the target is, never from where a copy of its name happens to lie.

The same thing put at two places gets the same verdict:
- a temp grant that names a fixed machine place (`*/var/tmp/codex-outputs/`) admits that place only, not any
  path that ends in its spelling (an arbitrary /tmp file stays refused, as row 4 of the tool policy says);
- a device grant (`*/dev/null`, `*/dev/stdout`, `*/dev/stderr`) admits the device only, not an ordinary file
  whose path ends in `dev/null`;
- a path of the scratch shape `.claude/scratch/<session>/<role>/<agent>/` that is not the caller's is
  another actor's scratch in any project, not only in the current one.
Only paths are judged: no target is created.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
POLICY = os.path.join(ROOT, "hooks", "pretool-tool-policy.py")
SID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
AGENT = "f0e1d2c3b4a59687"
PROJECT = "/nonexistent-grant-place/proj"


def run(tmp_path, hook, tool_input, role=None, project=PROJECT, tool="Write"):
    home = tmp_path / "home"
    payload = {"session_id": SID, "cwd": project, "hook_event_name": "PreToolUse", "tool_name": tool,
               "tool_input": tool_input}
    if role:
        payload.update(agent_id=AGENT, agent_type=role, subagent_type=role)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    root = tmp_path / "session-root"
    root.mkdir(exist_ok=True)
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_PROJECT_DIR=project,
               CLAUDE_STATE_DIR=str(tmp_path / "state"), TMPDIR=str(root), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, hook], input=json.dumps(payload), capture_output=True, text=True,
                          cwd=str(tmp_path), env=env, timeout=60)


def verdict(tmp_path, role, target):
    proc = run(tmp_path, POLICY, {"file_path": target, "content": "x"}, role)
    assert proc.returncode in (0, 2), proc.stderr
    return proc.returncode


# U7: a temp grant written as `*/var/tmp/codex-outputs/` is the place /var/tmp/codex-outputs/, not a suffix.
@pytest.mark.parametrize("role", ["qa", "ba"])
def test_a_temp_grant_admits_its_place_and_no_path_ending_in_its_spelling(tmp_path, role):
    assert verdict(tmp_path, role, "/var/tmp/codex-outputs/r.txt") == 0
    for arbitrary in ("/tmp/other/a.sh", "/tmp/x/var/tmp/codex-outputs/a.sh", "/tmp/var/tmp/codex-outputs/r.txt"):
        assert verdict(tmp_path, role, arbitrary) == 2, arbitrary
    # outside temp: the same file at two places, both outside the role's list
    assert verdict(tmp_path, role, "/srv/x/a.sh") == verdict(tmp_path, role, "/srv/x/var/tmp/codex-outputs/a.sh") == 2


# U8: a device grant (`*/dev/null`, `*/dev/stdout`, `*/dev/stderr`) is the device, not a file whose path ends so.
@pytest.mark.parametrize("role", ["push-analyst", "qa"])
def test_a_device_grant_admits_the_device_and_no_file_named_like_it(tmp_path, role):
    assert verdict(tmp_path, role, "/dev/null") == 0
    for name in ("dev/null", "dev/stdout", "dev/stderr"):
        for base in ("/srv/x", PROJECT):  # an ordinary file, at two places: as refused as any other file there
            assert verdict(tmp_path, role, f"{base}/{name}") == verdict(tmp_path, role, f"{base}/out") == 2, (base, name)


# U21: another actor's scratch (`.claude/scratch/<session>/<role>/<agent>/`) is refused in every project.
@pytest.mark.parametrize("role", ["push-analyst", "qa"])
def test_another_actors_scratch_is_refused_wherever_the_project_lies(tmp_path, role):
    assert verdict(tmp_path, role, f"{PROJECT}/.claude/scratch/{SID}/{role}/{AGENT}/f") == 0  # the caller's own
    other = "push-analyst" if role == "qa" else "qa"
    for base in (PROJECT, "/srv/other", "/tmp/other"):
        for rest in (f"{SID}/{other}/A9/f", f"{SID}/{role}/A9/f", "f"):
            assert verdict(tmp_path, role, f"{base}/.claude/scratch/{rest}") == 2, (base, rest)


# A docs grant (`*/docs/codex/`, `*/docs/dev/overnight/`, ...) is the project's docs folder, not any folder named so.
@pytest.mark.parametrize("role", ["qa", "ba"])
def test_a_docs_grant_admits_the_projects_docs_and_no_other_directorys(tmp_path, role):
    for sub in ("docs/codex/x.md", "docs/dev/overnight/x.md"):
        assert verdict(tmp_path, role, f"{PROJECT}/{sub}") == 0, sub
        assert verdict(tmp_path, role, f"{PROJECT}/.claude/worktrees/w1/{sub}") == 0, sub  # a worktree in it
        for other in ("/srv/other", "/opt/elsewhere"):
            assert verdict(tmp_path, role, f"{other}/{sub}") == verdict(tmp_path, role, f"{other}/x.md") == 2, other


# U26: a harness checkout is the harness home, or the session's project when it holds hooks/lib/harness_switch.py;
# not any directory an agent gave a file of that name.
def test_a_script_naming_the_switch_state_is_refused_in_a_made_up_checkout(tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "hooks", "lib"))
    import harness_switch  # the switch's directory name, as the guard reads it
    sys.path.pop(0)
    guard = os.path.join(ROOT, "hooks", "pretool-harness-switch-guard.py")
    content = f"ls ~/{harness_switch.DIR_NAME}/\n"

    def switch_verdict(target, project):
        proc = run(tmp_path, guard, {"file_path": str(target), "content": content}, project=str(project))
        assert proc.returncode in (0, 2), proc.stderr
        return proc.returncode

    checkout, fake = tmp_path / "checkout", tmp_path / "fake"
    for d in (checkout, fake):
        (d / "hooks" / "lib").mkdir(parents=True)
        (d / "hooks" / "lib" / "harness_switch.py").write_text("")
    assert switch_verdict(fake / "s.sh", checkout) == switch_verdict(tmp_path / "s.sh", checkout) == 2
    assert switch_verdict(fake / "sub" / "s.sh", PROJECT) == switch_verdict(tmp_path / "s.sh", PROJECT) == 2
    assert switch_verdict(checkout / "s.sh", checkout) == 0  # the session's project is a checkout
    assert switch_verdict(os.path.join(ROOT, "hooks", "x.sh"), PROJECT) == 0  # the harness home
