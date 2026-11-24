"""The filesystem root is never the top of a repository or of a project (locations.repo_top, is_fs_root, refuses_root).

hooks/tests/test_checkpoint_root_top.py closed the checkpoint; this closes the writers that resolve a top and write
below it, and shows the shared answer to "which repository am I in" for a directory below a repository at the root.
The root is simulated as that test does: a private mount namespace (hooks/tests/_private_ns.py) of the test process alone chroots into a
made-up directory that holds a repository at its top. ROOT_TOP_TREE names another copy of hooks/ and scripts/ to run
(the red run uses the tree as it was before this change).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("_root_top_sim", _HERE / "test_checkpoint_root_top.py")
sim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sim)
TREE = Path(os.environ.get("ROOT_TOP_TREE") or sim.ROOT)
SCRIPTS = ("create-worktree.sh", "install-git-keystone.sh", "apply-permissions.sh", "create-overnight-state.sh",
           "spec-check.py", "write-commit-grant.py", "write-push-gate-token.py")
HOOKS = ("posttool-codex-skill-ledger.py", "pretool-worktree-guard.sh")


sim.ROOT = TREE
fake_root = sim.fake_root  # the made-up root of that test, built from TREE


@pytest.fixture
def root_sim(fake_root):
    fr, env = fake_root
    (fr / "h" / "scripts").mkdir()
    for name in SCRIPTS:
        if (TREE / "scripts" / name).exists():
            shutil.copy2(TREE / "scripts" / name, fr / "h" / "scripts" / name)
    for name in HOOKS:
        shutil.copy2(TREE / "hooks" / name, fr / "h" / "hooks" / name)
    shutil.copytree(TREE / "hooks" / "git-keystone", fr / "h" / "hooks" / "git-keystone")
    sim._git(env, fr, "update-ref", "refs/remotes/origin/main", "HEAD")  # the default branch the overnight launch reads
    sim._git(env, fr, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    sim._git(env, fr, "checkout", "-q", "-b", "work")  # an overnight launch refuses the protected branch itself
    return fr, env


def _entries(fr: Path) -> set:
    return {p.name for p in fr.iterdir()}


def _py(fr: Path, cwd: str, code: str) -> str:
    return sim._py(fr, cwd, code)


def test_the_shared_answer_is_none_for_a_directory_below_a_repository_at_the_root(root_sim) -> None:
    fr, _ = root_sim
    out = _py(fr, "/sub", "import locations as L\nprint(L.repo_top('/sub'), L.repo_top('/'), L.repo_top('/own'), "
                          "L.is_fs_root('/'), L.is_fs_root('/own'), L.is_fs_root('/sub/..'))")
    assert out == "None None /own True False True"


def test_a_write_below_a_project_at_the_root_is_refused_once_and_other_places_are_not(root_sim) -> None:
    fr, _ = root_sim
    proc = sim._in_root(fr, "/", "python3", "-I", "-c", "import sys; sys.path[:0] = ['/h/hooks/lib']\nimport locations as L\n"
                        "print(L.refuses_root('/.claude/x', '/', 'w'), L.refuses_root('/.claude/y', '/', 'w'), "
                        "L.refuses_root('/tmp/x', '/', 'w'), L.refuses_root('/own/x', '/own', 'w'))")
    assert proc.stdout.split() == ["True", "True", "False", "False"], proc.stdout + proc.stderr
    assert proc.stderr.count("nothing is written below it") == 1, proc.stderr


def test_the_workflow_hook_writes_nothing_below_a_project_at_the_root(root_sim) -> None:
    fr, _ = root_sim
    out = _py(fr, "/", "import importlib.util as u\n"
                       "s = u.spec_from_file_location('pw', '/h/hooks/prompt-workflow.py'); m = u.module_from_spec(s)\n"
                       "s.loader.exec_module(m)\nfrom pathlib import Path\n"
                       "m._atomic_write_json(Path('/.claude/workflow-x.json'), {})\n"
                       "m._write_new_file(Path('/.claude/dev-registry/dev-1/requirement.md'), b'x')\n"
                       "try:\n    m._reserve_dev_registry('dev', Path('/'))\nexcept RuntimeError:\n    pass\n"
                       "with m._exclusive_lock(Path('/.claude/workflow-locks/x.lock')):\n    pass\n"
                       "print('done')")
    assert out == "done"
    assert ".claude" not in _entries(fr), "the root's own .claude folder was created"


def test_the_workflow_hook_still_writes_below_an_own_project(root_sim) -> None:
    fr, _ = root_sim
    out = _py(fr, "/own", "import importlib.util as u\n"
                          "s = u.spec_from_file_location('pw', '/h/hooks/prompt-workflow.py'); m = u.module_from_spec(s)\n"
                          "s.loader.exec_module(m)\nfrom pathlib import Path\n"
                          "m._atomic_write_json(Path('/own/.claude/workflow-x.json'), {})\nprint('done')")
    assert out == "done" and (fr / "own" / ".claude" / "workflow-x.json").exists()


def test_the_yield_log_is_not_written_below_a_project_at_the_root(root_sim) -> None:
    fr, _ = root_sim
    _py(fr, "/", "import specialist_yield as y\n"
                 "y.record_yield('/none', 'qa', 's', 1, 'productive', 'none')")
    assert ".claude" not in _entries(fr)


def test_the_codex_ledger_is_not_written_into_the_root_registry(root_sim) -> None:
    fr, _ = root_sim
    registry = fr / ".claude" / "dev-registry"
    (registry / "dev-s1").mkdir(parents=True)
    (registry / "agent-index.json").write_text(json.dumps({"a1": {"agent_type": "qa", "dev_session_id": "dev-s1"}}))
    payload = json.dumps({"tool_name": "Skill", "tool_input": {"skill": "codex"}, "agent_id": "a1", "session_id": "x"})
    proc = sim._in_root(fr, "/", "bash", "-c", f"echo '{payload}' | python3 /h/hooks/posttool-codex-skill-ledger.py")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (registry / "dev-s1" / "codex-ledger").exists(), "a ledger was written below the root's registry"


def test_the_spec_checkin_writes_nothing_below_a_project_at_the_root(root_sim) -> None:
    fr, _ = root_sim
    _py(fr, "/", "import importlib.util as u\ns = u.spec_from_file_location('sc', '/h/scripts/spec-check.py')\n"
                 "m = u.module_from_spec(s); s.loader.exec_module(m)\nm._write_payload('spec-1', 'ba', {})")
    assert ".claude" not in _entries(fr)


@pytest.mark.parametrize("script,args", [
    ("create-worktree.sh", ["--project-dir", "/", "wt"]),
    ("install-git-keystone.sh", ["--project-dir", "/"]),
    ("apply-permissions.sh", ["/h/perms.json"]),
    ("create-overnight-state.sh", ["--project-dir", "/", "--session-id", "s1", "--worktree"]),
])
def test_a_script_writes_nothing_into_a_repository_at_the_root(root_sim, script, args) -> None:
    fr, _ = root_sim
    (fr / "h" / "perms.json").write_text('[{"section": "allow", "pattern": "Read(x)"}]')
    before = _entries(fr)
    proc = sim._in_root(fr, "/", "bash", f"/h/scripts/{script}", *args)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert _entries(fr) == before and not (fr / ".git" / "keystone-hooks").exists(), proc.stdout + proc.stderr


def test_the_worktree_guard_decides_below_a_repository_at_the_root_as_in_no_repository(root_sim) -> None:
    fr, _ = root_sim
    made = sim._in_root(fr, "/", "bash", "-c", "git worktree add -q /.claude/worktrees/agent-x -b agent-x && "
                        "git checkout -q main && git commit -q --allow-empty -m next")
    assert made.returncode == 0, made.stdout + made.stderr  # an agent worktree of the repository at the root, behind main
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git status"}, "cwd": "/sub"})
    proc = sim._in_root(fr, "/sub", "bash", "-c", f"echo '{payload}' | bash /h/hooks/pretool-worktree-guard.sh")
    assert proc.returncode == 0 and proc.stdout == "" and proc.stderr == "", proc.stdout + proc.stderr
