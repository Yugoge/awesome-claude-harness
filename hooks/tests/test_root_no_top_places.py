"""The places that asked git for the top themselves now ask the shared place (locations.repo_top, repo_common_dir):
the filesystem root is no top, so each decides below a repository at the root as in a directory in no repository, and a
writer writes nothing.

Simulation as in test_root_no_top.py: a private mount namespace (hooks/tests/_private_ns.py) chroots into a made-up directory that holds a
repository at its top; the code under test sees it as "/" and a session sits in "/sub". ROOT_TOP_TREE names another copy
of hooks/ and scripts/ to run (the red run uses the tree as commit 999a89eb6 has it).
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
sim.ROOT = TREE
fake_root = sim.fake_root
_IGNORE = shutil.ignore_patterns("__pycache__", "tests", "*.pyc")


@pytest.fixture
def places(fake_root):
    fr, env = fake_root
    shutil.copytree(TREE / "hooks", fr / "h" / "hooks", ignore=_IGNORE, dirs_exist_ok=True)
    shutil.copytree(TREE / "scripts", fr / "h" / "scripts", ignore=_IGNORE, dirs_exist_ok=True)
    shutil.copytree(TREE / "scripts", fr / "home" / ".claude" / "scripts", ignore=_IGNORE, dirs_exist_ok=True)
    shutil.copytree(TREE / "hooks", fr / "home" / ".claude" / "hooks", ignore=_IGNORE, dirs_exist_ok=True)
    (fr / "docs" / "dev").mkdir(parents=True)
    (fr / "docs" / "dev" / "close-report-T1.md").write_text("report\n")
    yield fr, env
    shutil.rmtree(fr, ignore_errors=True)


def _run(fr: Path, cwd: str, *argv: str):
    return sim._in_root(fr, cwd, *argv)


def _py(fr: Path, code: str, cwd: str = "/sub") -> str:
    return sim._py(fr, cwd, code)


def test_the_common_git_directory_of_a_repository_at_the_root_is_none(places) -> None:
    fr, _ = places
    out = _py(fr, "import locations as L\nprint(L.repo_common_dir('/sub'), L.repo_common_dir('/'), L.repo_common_dir('/own'))")
    assert out == "None None /own/.git"


def test_the_safety_rules_read_a_config_write_below_a_root_repository_as_in_no_repository(places) -> None:
    fr, env = places  # bash_safety_rules.commit_guard: its query of the common git directory
    sim._git(env, fr / "h", "init", "-q")  # the harness home is a repository of its own: the root's one is not its repository
    out = _py(fr, "from lib import bash_safety_rules as b\n"
                  "print(b.commit_guard({'cwd': '/own', 'tool_input': {'command': 'git config alias.zz status'}}))\n"
                  "print(b.commit_guard({'cwd': '/sub', 'tool_input': {'command': 'git config alias.zz status'}}))")
    own, sub = out.splitlines()
    assert own == "OK" and sub.startswith("CONFIG "), out  # an own repository as before; the root's repository: unresolved


def test_the_privilege_guard_does_not_own_a_commit_below_a_root_repository(places) -> None:
    fr, _ = places  # pretool-git-privilege-guard._own_scratch_commit: its ownership query
    out = _py(fr, "import importlib.util as u\n"
                  "s = u.spec_from_file_location('g', '/h/hooks/pretool-git-privilege-guard.py'); m = u.module_from_spec(s)\n"
                  "s.loader.exec_module(m)\n"
                  "print(m._own_scratch_commit('git commit -q -m x', {'cwd': '/sub', 'tool_input': {}}))")
    assert out.splitlines()[-1].startswith("(False"), out


def test_git_rm_below_a_root_repository_is_judged_as_in_no_repository(places) -> None:
    fr, env = places  # bash_execution_boundary.prove_git_rm: a gitlink of the root repository is not looked up
    sim._git(env, fr, "update-index", "--add", "--cacheinfo", "160000," + sim._git(env, fr, "rev-parse", "HEAD") + ",sub/gl")
    out = _py(fr, "import bash_execution_boundary as b\n"
                  "r = b.prove_git_rm({'git_rm_proof': {'cwds': ['/sub'], 'removals': [{'git': [], 'paths': ['gl']}]}}, '/sub', '/none')\n"
                  "print(r.get('reason'))")
    assert out == "None", out
    out = _py(fr, "import bash_execution_boundary as b\n"
                  "r = b.prove_git_rm({'git_rm_proof': {'cwds': ['/own'], 'removals': [{'git': [], 'paths': ['o.txt']}]}}, '/own', '/none')\n"
                  "print(r.get('reason'))")
    assert out == "None", out  # an own repository is looked up as before (a file, not a gitlink: allowed)


def test_the_score_log_key_of_a_root_repository_is_the_directory_not_the_root(places) -> None:
    fr, _ = places
    out = _py(fr, "import hashlib, score_log\n"
                  "print(score_log.project_key('/sub') == hashlib.sha256(b'/sub').hexdigest()[:12])")
    assert out == "True"


def test_a_session_record_is_not_looked_for_at_the_root_of_a_root_repository(places) -> None:
    fr, _ = places
    out = _py(fr, "import overnight\nprint([str(r) for r in overnight._roots('/sub')])")
    assert out == "['/sub']"


def test_the_overnight_guard_binds_no_git_directory_of_a_root_repository(places) -> None:
    fr, _ = places
    out = _py(fr, "import importlib.util as u\n"
                  "s = u.spec_from_file_location('g', '/h/hooks/pretool-overnight-hook-guard.py'); m = u.module_from_spec(s)\n"
                  "s.loader.exec_module(m)\n"
                  "print(m._checkout_git_dirs('/sub'), m._linked_worktree_git_paths('/sub'), m._shared_common_dir_ro_rebinds('/sub'))")
    assert out.splitlines()[-1] == "[] [] []", out


def test_the_merge_writes_nothing_below_a_root_repository(places) -> None:
    fr, env = places
    sim._git(env, fr, "branch", "master")  # the default branch the merge derives, and a source ahead of it
    sim._git(env, fr, "checkout", "-q", "-b", "feat")
    sim._git(env, fr, "commit", "-q", "--allow-empty", "-m", "ahead")
    proc = _run(fr, "/sub", "bash", "/h/hooks/merge.sh", "feat")
    assert proc.returncode == 1 and "nothing is merged" in proc.stderr, proc.stdout + proc.stderr


def test_the_mutation_run_mutates_nothing_below_a_root_repository(places) -> None:
    fr, _ = places
    proc = _run(fr, "/sub", "python3", "/h/scripts/ci/diff-mutate.py", "--base", "HEAD", "--list")
    assert proc.returncode == 2 and "no file is mutated" in proc.stderr, proc.stdout + proc.stderr


def test_the_red_green_check_refuses_a_root_repository(places) -> None:
    fr, _ = places
    proc = _run(fr, "/sub", "python3", "/h/scripts/ci/red-green.py", "--base", "HEAD", "--head", "HEAD", "--repo", "/sub")
    assert proc.returncode != 0 and "below the filesystem root" in proc.stderr, proc.stdout + proc.stderr


def test_the_commit_script_finds_nothing_to_commit_below_a_root_repository(places) -> None:
    fr, _ = places  # stray.txt of the root repository is changed
    proc = _run(fr, "/sub", "bash", "/h/scripts/commit.sh", "msg")
    assert proc.returncode == 0 and "nothing to commit" in proc.stdout, proc.stdout + proc.stderr


def test_the_close_report_is_not_looked_up_below_the_root_repository(places) -> None:
    fr, _ = places  # /docs/dev/close-report-T1.md lies in the root repository
    proc = _run(fr, "/sub", "bash", "/h/scripts/resolve-close-report.sh", "T1")
    assert proc.stdout.strip() and proc.stdout.strip().replace("//", "/") != "/docs/dev/close-report-T1.md", proc.stdout + proc.stderr


@pytest.mark.parametrize("script", ["verify-claims.sh", "check-public-core.sh"])
def test_a_check_script_takes_the_directory_not_the_root_as_its_top(places, script) -> None:
    fr, _ = places
    proc = _run(fr, "/sub", "bash", "-x", f"/h/scripts/{script}")
    trace = [line for line in proc.stderr.splitlines() if line.startswith("+ cd ") and "BASH_SOURCE" not in line]
    assert trace and trace[0].startswith("+ cd /sub") or any(line.startswith("+ cd /sub") for line in trace), proc.stderr[-600:]
    assert "+ cd /\n" not in proc.stderr + "\n"


def test_the_readme_facts_do_not_take_the_root_as_the_top_of_a_work_tree(places) -> None:
    fr, _ = places
    out = _py(fr, "sys.path.insert(0, '/h/scripts')\nimport readme_facts as r\nfrom pathlib import Path\n"
                  "try:\n    r._tracked(Path('/'))\n    print('taken')\nexcept r.FactError:\n    print('refused')", cwd="/h/scripts")
    assert out == "refused"


def test_the_enforcement_evidence_check_takes_the_directory_not_the_root_as_its_root(places) -> None:
    fr, _ = places
    proc = _run(fr, "/sub", "python3", "/h/scripts/check-enforcement-evidence.py", "--ledger")
    text = proc.stdout + proc.stderr
    assert "cannot read /sub/docs/ENFORCEMENT-LEDGER.md" in text, text[-800:]


@pytest.mark.parametrize("script,args", [("push-snapshot.py", []), ("merge-snapshot.py", ["snapshot", "main"])])
def test_the_step_snapshot_does_not_take_the_root_as_the_repository(places, script, args) -> None:
    fr, _ = places
    proc = _run(fr, "/sub", "python3", f"/h/scripts/steps/{script}", *args)
    if script == "push-snapshot.py":
        assert proc.returncode == 1 and "not inside a git work tree" in proc.stderr, proc.stdout + proc.stderr
    else:
        assert "REPO_ROOT=\n" in proc.stdout + "\n", proc.stdout + proc.stderr


# -- the readers that moved to the shared place earlier (each in the simulated root) --------------------------
_LOAD = ("import importlib.util as u\n"
         "def load(path, name='m'):\n"
         "    s = u.spec_from_file_location(name, path); m = u.module_from_spec(s); s.loader.exec_module(m); return m\n")


def test_the_commit_plan_top_of_a_directory_below_a_root_repository_is_none(places) -> None:
    fr, _ = places
    out = _py(fr, _LOAD + "m = load('/h/scripts/steps/commit-plan.py')\nprint(repr(m.git_top('/sub')), m.git_top('/own'))")
    assert out == "'' /own"


def test_the_commit_repository_resolver_refuses_a_directory_below_a_root_repository(places) -> None:
    fr, _ = places
    out = _py(fr, "sys.path.insert(0, '/h/scripts')\n" + _LOAD + "from pathlib import Path\n"
                  "m = load('/h/scripts/resolve-commit-repos.py')\n"
                  "try:\n    print(m._repo_root(Path('/sub')))\nexcept Exception as e:\n    print(type(e).__name__)\n"
                  "print(m._repo_root(Path('/own')))")
    assert out.splitlines() == ["PlanError", "/own"], out


def test_a_merge_grant_of_a_root_repository_is_not_the_grant_of_a_top_level(places) -> None:
    fr, _ = places
    out = _py(fr, "import hashlib, json, os\nfrom pathlib import Path\nimport merge_grant as g\n"
                  "p = Path(g.grant_root()) / hashlib.sha256(b'/').hexdigest()[:16] / 's1' / 'n1.json'\n"
                  "p.parent.mkdir(parents=True)\n"
                  "p.write_text(json.dumps({'nonce': 'n1', 'session_id': 's1', 'repo_root': '/'}))\n"
                  "print(g.fault(str(p)))")
    assert "is not the top level of a git repository" in out, out


def test_the_merge_verdict_looks_for_the_grant_of_the_directory_not_of_the_root(places) -> None:
    fr, _ = places
    out = _py(fr, _LOAD + "from lib import command_span, merge_grant\n"
                  "class Span:\n    command = 'merge'\n    def opened_at(self): return 1\n"
                  "command_span.active_span = lambda *a, **k: Span()\n"
                  "seen = []\nmerge_grant.approval = lambda top, sid, since: (seen.append(top), ({}, 'recorded'))[1]\n"
                  "m = load('/h/hooks/pretool-merge-verdict.py')\n"
                  "m.refusal({'tool_input': {'command': 'bash /h/hooks/merge.sh feat'}, 'cwd': '/sub', 'transcript_path': 't', 'session_id': 's'})\n"
                  "print(seen)")
    assert out.splitlines()[-1] == "['/sub']", out


def test_the_stop_gate_takes_a_directory_below_a_root_repository_as_no_session_worktree(places) -> None:
    fr, _ = places
    out = _py(fr, _LOAD + "g = load('/h/hooks/stop-command-gate.py', 'stop_command_gate')\n"
                  "print(g._session_worktree('/sub', {'cwd': '/sub'}), g._session_worktree('/own', {'cwd': '/own/'}))")
    assert out.splitlines()[-1] == "/sub /own", out


def test_the_stop_gate_looks_up_the_merge_grant_of_the_directory_not_of_the_root(places) -> None:
    fr, _ = places
    out = _py(fr, _LOAD + "from lib import merge_grant\nseen = []\n"
                  "merge_grant.newest = lambda top, *a, **k: (seen.append(top), {})[1]\n"
                  "g = load('/h/hooks/stop-command-gate.py', 'stop_command_gate')\n"
                  "class Span:\n    command = 'merge'\n    args = ''\n    def opened_at(self): return 1\n    def __getattr__(self, n): return lambda *a, **k: 0\n"
                  "try:\n    g.p_merge(Span(), '/sub', {'cwd': '/sub', 'session_id': 's'})\nexcept BaseException:\n    pass\n"
                  "print(seen)")
    assert out.splitlines()[-1] in ("['/sub']", "[]"), out
    assert "'/'" not in out.splitlines()[-1], out


def test_the_privilege_guard_names_no_target_top_below_a_root_repository(places) -> None:
    fr, _ = places
    out = _py(fr, _LOAD + "g = load('/h/hooks/pretool-git-privilege-guard.py', 'g')\n"
                  "print(repr(g._commit_target_top('/sub')), g._commit_target_top('/own'))")
    assert out.splitlines()[-1] == "'' /own", out


def test_the_artifact_contract_hook_admits_no_harness_checkout_at_the_root(places) -> None:
    fr, _ = places
    out = _py(fr, _LOAD + "g = load('/h/hooks/subagentstop-artifact-contract-enforce.py', 'g')\nprint(g._nested_claude_repo())")
    assert out.splitlines()[-1] == "[]", out


def test_the_overnight_candidates_hold_no_root_top(places) -> None:
    fr, _ = places
    out = _py(fr, "import overnight\nprint('/' in [str(d) for d in overnight.candidate_project_dirs('/sub')])")
    assert out == "False"


def test_the_push_script_hashes_the_fallback_not_the_root_as_its_repository(places) -> None:
    fr, env = places
    sim._git(env, fr, "remote", "add", "origin", str(fr / "own"))
    proc = _run(fr, "/sub", "bash", "-x", "/h/hooks/push.sh")
    hashed = [line for line in proc.stderr.splitlines() if "hashlib.sha256(os.path.realpath(" in line]
    assert hashed, proc.stderr[-800:]  # the repository hash of the chain-B sentinel is computed
    assert all("realpath('/')" not in line and "realpath('\\''/'\\'')" not in line for line in hashed), hashed


def test_the_push_gate_token_is_not_bound_to_a_root_repository(places) -> None:
    fr, _ = places
    proc = _run(fr, "/sub", "python3", "/h/scripts/write-push-gate-token.py", "--repo-root", "/sub", "--branch", "main",
                "--commit", "abc", "--print-path")
    assert proc.returncode == 2 and "is not a git repository" in proc.stderr, proc.stdout + proc.stderr


def test_the_in_flight_push_token_is_not_written_for_a_root_repository(places) -> None:
    fr, _ = places
    out = _py(fr, "import hashlib\n" + _LOAD + "m = load('/h/scripts/execute-push.py', 'ep')\nseen = []\n"
                  "m._token_names_ancestor = lambda *a: (seen.append(a), True)[1]\n"
                  "m._inflight_token(hashlib.sha256(b'/').hexdigest()[:16], 'main', 'abc')\nprint(seen)")
    assert out.splitlines()[-1] == "[]", out


def test_the_commit_grant_is_not_written_for_a_root_repository(places) -> None:
    fr, _ = places
    (fr / "state" / "claude-commit-userintent-S1.flag").write_text("true\n")  # a /commit the owner typed is in progress
    proc = _run(fr, "/sub", "python3", "/h/scripts/write-commit-grant.py", "--task-id", "T1", "--sid", "S1", "--repo-root", "/sub")
    assert "not inside a git work tree whose top is not the filesystem root" in proc.stdout + proc.stderr, proc.stdout + proc.stderr
