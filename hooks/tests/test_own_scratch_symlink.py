"""An agent's own scratch directory counts only as the real directory the harness made, never through a link.

A write, removal or commit inside the caller's own scratch directory passes with fewer checks
(hooks/pretool-tool-policy.py `_own_scratch`, `_scratch_status`; lib/bash_safety_rules.py `_scratch_owner`). Both
sides used to be resolved before they were compared, so an agent that replaced its own directory, or a directory
above it, with a link had the link's target judged its own: every write there passed. Now the own directory counts
only when no component of it is a link and it is a directory (or not yet made), and a path is inside it only when it
lies there with every link resolved. The same holds for a role's drafts directory. Honest paths pass as before.

The real hooks run as subprocesses; every directory and repository is a throwaway one under pytest's tmp_path.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "hooks" / "pretool-tool-policy.py"
SAFETY = ROOT / "hooks" / "pretool-bash-safety.sh"
GUARD = ROOT / "hooks" / "pretool-git-privilege-guard.py"
START = ROOT / "hooks" / "subagentstart-scratch.py"
SID = "7b8c9d0e-1f2a-4b3c-8d4e-5f6a7b8c9d0e"
AGENT, OTHER = "a1b2c3d4e5f60718", "a9999999999999999"
ID = ("-c", "user.name=sandbox", "-c", "user.email=sandbox@example.invalid")


class Box:
    """TMPDIR as the hooks see it, the session's scratch directory below it (with its owner record), a project, and
    a directory elsewhere that no agent may write in."""

    def __init__(self, base: Path):
        self.base = base
        self.root = (base / "session-root")
        self.root.mkdir()
        self.root = self.root.resolve()
        self.session = self.root / SID
        self.session.mkdir()
        (self.session / ".owner").write_text(json.dumps({"sid": SID}))
        self.own, self.other = self.session / "dev" / AGENT, self.session / "dev" / OTHER
        self.elsewhere = base / "elsewhere"
        self.project = base / "proj"
        for d in (self.elsewhere, self.project, base / "home" / ".claude", base / "state"):
            d.mkdir(parents=True, exist_ok=True)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_", "PYTHON"))}
        self.env.update(HOME=str(base / "home"), CLAUDE_CONFIG_DIR=str(base / "home" / ".claude"),
                        CLAUDE_STATE_DIR=str(base / "state"), CLAUDE_PROJECT_DIR=str(self.project),
                        TMPDIR=str(self.root), CLAUDE_PYTHON_BIN=sys.executable, PYTHONDONTWRITEBYTECODE="1",
                        CLAUDE_PROTECTED_RUNTIME_FILE=os.environ.get("CLAUDE_PROTECTED_RUNTIME_FILE", ""),
                        CLAUDE_HOOK_BOUNDARY_TIMEOUT="120s", GIT_CONFIG_NOSYSTEM="1")

    def hook(self, program, tool, tool_input, caller=(AGENT, "dev"), cwd=None):
        payload = {"session_id": SID, "cwd": str(cwd or self.project), "hook_event_name": "PreToolUse",
                   "tool_name": tool, "tool_input": tool_input, "transcript_path": ""}
        if caller:
            payload.update(agent_id=caller[0], agent_type=caller[1], subagent_type=caller[1])
        argv = ["bash", str(program)] if str(program).endswith(".sh") else [sys.executable, "-B", str(program)]
        return subprocess.run(argv, input=json.dumps(payload), capture_output=True, text=True,
                              cwd=str(cwd or self.project), env=self.env, timeout=180)

    def write(self, path, caller=(AGENT, "dev")):
        """The write policy's verdicts on a Write of ``path`` and on a shell redirect to it: (exit codes, stderr)."""
        out = [self.hook(POLICY, "Write", {"file_path": str(path), "content": "x"}, caller),
               self.hook(POLICY, "Bash", {"command": f"echo x > {path}"}, caller)]
        return [p.returncode for p in out], "\n".join(p.stderr for p in out)

    def start(self, role="dev", agent=AGENT):
        """hooks/subagentstart-scratch.py, as the harness runs it when the agent starts."""
        payload = {"session_id": SID, "agent_type": role, "agent_id": agent, "hook_event_name": "SubagentStart"}
        proc = subprocess.run([sys.executable, "-B", str(START)], input=json.dumps(payload), capture_output=True,
                              text=True, env=self.env, timeout=60)
        assert proc.returncode == 0, proc.stderr


def _link(path: Path, target: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, path)


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


# -- writes ------------------------------------------------------------------------------------------------------

def test_an_honest_write_in_the_own_directory_passes(box):
    box.start()
    assert box.write(box.own / "x.txt")[0] == [0, 0]
    assert box.write(box.own / "deeper" / "x.txt")[0] == [0, 0]


def test_an_own_directory_not_yet_made_still_takes_a_write(box):
    """An agent started before the harness made the directory: the write makes it, as before."""
    (box.session / "dev").mkdir()
    assert box.write(box.own / "x.txt")[0] == [0, 0]


def test_the_own_directory_replaced_by_a_link_elsewhere_is_not_own(box):
    _link(box.own, box.elsewhere)
    codes, err = box.write(box.own / "x.txt")
    assert codes == [2, 2], err
    codes, err = box.write(box.elsewhere / "x.txt")      # the link's target, named directly
    assert codes == [2, 2], err


def test_the_own_directory_replaced_by_a_link_to_another_agents_directory_is_not_own(box):
    box.other.mkdir(parents=True)
    _link(box.own, box.other)
    for path in (box.own / "x.txt", box.other / "x.txt"):
        codes, err = box.write(path)
        assert codes == [2, 2], (path, err)


def test_a_link_in_a_middle_component_makes_nothing_below_it_own(box):
    (box.base / "role-elsewhere" / AGENT).mkdir(parents=True)
    _link(box.session / "dev", box.base / "role-elsewhere")
    for path in (box.own / "x.txt", box.base / "role-elsewhere" / AGENT / "x.txt"):
        codes, err = box.write(path)
        assert codes == [2, 2], (path, err)


def test_a_link_put_in_place_after_the_harness_made_the_directory_is_not_own(box):
    box.start()
    assert box.own.is_dir() and not box.own.is_symlink()
    assert box.write(box.own / "x.txt")[0] == [0, 0]
    box.own.rmdir()
    _link(box.own, box.elsewhere)
    codes, err = box.write(box.own / "x.txt")
    assert codes == [2, 2], err


def test_a_file_in_place_of_the_own_directory_is_not_own(box):
    (box.session / "dev").mkdir()
    box.own.write_text("x")
    assert box.write(box.own / "x.txt")[0] == [2, 2]


def test_a_role_directory_replaced_by_a_link_takes_no_drafts(box):
    """<session>/<role>/<file> is a same-role draft only where <session>/<role> is the real directory."""
    box.other.mkdir(parents=True)
    _link(box.session / "qa", box.other)                 # qa's drafts would land in a dev agent's own directory
    codes, err = box.write(box.session / "qa" / "draft.md", caller=(AGENT, "qa"))
    assert codes == [2, 2], err


def test_an_honest_draft_in_the_role_directory_passes(box):
    (box.session / "qa").mkdir()
    assert box.write(box.session / "qa" / "draft.md", caller=(AGENT, "qa"))[0] == [0, 0]


def test_the_session_directory_replaced_by_a_link_is_not_own(box):
    """The main agent's own, and the session's for every actor's removals (the main agent's writes are not judged
    by role, so its removal shows it)."""
    (box.session / "a.txt").write_text("x")
    for caller in (None, (AGENT, "dev")):
        proc = box.hook(SAFETY, "Bash", {"command": f"rm -f {box.session}/a.txt"}, caller=caller)
        assert proc.returncode == 0, proc.stderr
    (box.elsewhere / ".owner").write_text(json.dumps({"sid": SID}))
    (box.elsewhere / "a.txt").write_text("x")
    os.rename(box.session, box.base / "moved-session")
    _link(box.session, box.elsewhere)
    for caller in (None, (AGENT, "dev")):
        proc = box.hook(SAFETY, "Bash", {"command": f"rm -f {box.session}/a.txt"}, caller=caller)
        assert proc.returncode == 2 and "removal-policy" in proc.stderr, (caller, proc.stderr)


def test_the_in_project_place_replaced_by_a_link_is_not_own(box):
    old = box.project / ".claude" / "scratch" / SID / "dev" / AGENT
    old.mkdir(parents=True)
    assert box.write(old / "x.txt")[0] == [0, 0]
    old.rmdir()
    _link(old, box.elsewhere)
    codes, err = box.write(old / "x.txt")
    assert codes == [2, 2], err


# -- removals and commits: the same judgement --------------------------------------------------------------------

def test_a_removal_through_a_linked_own_directory_is_refused(box):
    box.start()
    (box.own / "a.txt").write_text("x")
    proc = box.hook(SAFETY, "Bash", {"command": f"rm -f {box.own}/a.txt"})
    assert proc.returncode == 0, proc.stderr
    box.own.joinpath("a.txt").unlink()
    box.own.rmdir()
    (box.elsewhere / "a.txt").write_text("x")
    _link(box.own, box.elsewhere)
    proc = box.hook(SAFETY, "Bash", {"command": f"rm -f {box.own}/a.txt"})
    assert proc.returncode == 2 and "removal-policy" in proc.stderr, proc.stderr


def test_a_removal_through_a_linked_role_directory_is_refused(box):
    (box.base / "role-elsewhere" / AGENT).mkdir(parents=True)
    (box.base / "role-elsewhere" / AGENT / "a.txt").write_text("x")
    _link(box.session / "dev", box.base / "role-elsewhere")
    proc = box.hook(SAFETY, "Bash", {"command": f"rm -f {box.own}/a.txt"})
    assert proc.returncode == 2 and "removal-policy" in proc.stderr, proc.stderr


def _repo(path: Path, env):
    path.mkdir(parents=True, exist_ok=True)
    for args in (("init", "-q", "-b", "main"), ("add", "-A"), (*ID, "commit", "-q", "--allow-empty", "-m", "base")):
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, env=env)


def test_a_commit_through_a_linked_own_directory_is_refused(box):
    box.start()
    _repo(box.own / "repo", box.env)
    proc = box.hook(GUARD, "Bash", {"command": f"git -C {box.own}/repo commit -qm x"})
    assert proc.returncode == 0, proc.stderr
    os.rename(box.own, box.base / "moved-own")
    _repo(box.elsewhere / "repo", box.env)
    _link(box.own, box.elsewhere)
    proc = box.hook(GUARD, "Bash", {"command": f"git -C {box.own}/repo commit -qm x"})
    assert proc.returncode == 2 and "BLOCKED: agent git commit" in proc.stderr, proc.stderr
