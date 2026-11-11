"""P9 A23 (D24), task identity: every script that builds a cycle's registry
directory takes it from the one rule (hooks/lib/obligation.py,
registry_dir_for, and registry_dir_named for the scripts handed a registry
name instead of a task id: that name under the registry root, where every
reader looks for it).

The sites: scripts/write-enforce-flag.sh, scripts/overnight-init.sh,
scripts/create-overnight-state.sh (through `prompt-workflow.py registry-dir
--project-dir D --name N`), scripts/graphify-query.py and
scripts/graphify-enrich.py (its output directory and its default
blast-radius-map path). Each runs for real in a scratch layout, with
CLAUDE_HOME unset and with CLAUDE_HOME outside HOME, and must put the
directory where the rule says. On d64fa96 each built the path by hand, and
agreed with the rule on every name a caller passes; so the pin is a
mutation: in a copy of the harness whose registry_dir_for names other
directories (another root, another name for a /dev cycle), every site must
follow it. On d64fa96 none followed, and the "mutated" cases fail there.
A script handed a registry name follows the rule's root; the name it is
handed is the directory's name already (the command text reads
`.claude/dev-registry/<DEV_SESSION_ID>/`), so a renamed /dev directory
moves only the producer's reservation, which turns a task id into the name.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
UUID = "3f2a9c1e-4b5d-4e6f-8a7b-9c0d1e2f3a4b"
MINTED = ["dev-20260101-000000", "dev-command-20260101-000000"]
# Names that are no minted task id: an overnight session id (a UUID, and one
# holding a stamp), a bare stamp and a lane id (as replays pass them), and
# /dev-overnight's per-pipeline graphify name. Each keeps its own directory.
OTHER = [UUID, "s-20260101-000000", "20260101-000000", "dev-20260101-000000-l1", f"{UUID}-pipeline-2"]
NAMES = MINTED + OTHER
GIT_ENV = dict(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
               GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.invalid")
# The mutation: the registry root and the name of a /dev cycle's directory.
MUTATIONS = [('/ ".claude" / "dev-registry"', '/ ".claude" / "mutated-registry"'),
             ('candidates = [root / f"dev-{stamp}"]', 'candidates = [root / f"cycle-{stamp}"]')]


@pytest.fixture(scope="module", params=["tree", "mutated"])
def harness(request, tmp_path_factory):
    if request.param == "tree":
        return REPO
    copy = tmp_path_factory.mktemp("harness") / "claude"
    shutil.copytree(REPO, copy, symlinks=True, ignore=shutil.ignore_patterns(
        ".git", "tests", "docs", "__pycache__", "*.pyc"))
    lib = copy / "hooks" / "lib" / "obligation.py"
    text = lib.read_text(encoding="utf-8")
    for old, new in MUTATIONS:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    lib.write_text(text, encoding="utf-8")
    return copy


def _expected(harness: Path, project: Path, name: str, task_id: bool = False) -> Path:
    """Where the rule of ``harness`` puts ``name``'s registry: for a registry
    name, the directory of that name under the root registry_dir_for uses;
    with ``task_id``, registry_dir_for's directory for the minted task id."""
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from hooks.lib.obligation import registry_dir_for; "
            "print(registry_dir_for(sys.argv[2], sys.argv[3]))")
    minted = task_id and re.fullmatch(r"dev-(?:command-)?\d{8}-\d{6}", name) is not None
    probe = name if minted else MINTED[0]
    out = Path(subprocess.run([sys.executable, "-I", "-B", "-c", code, str(harness), str(project), probe],
                              capture_output=True, text=True, check=True).stdout.strip())
    return (out if minted else out.parent / name).resolve()


@pytest.fixture(params=["CLAUDE_HOME unset", "CLAUDE_HOME outside HOME"])
def layout(request, tmp_path):
    """A project reached through a symlink, a scratch HOME, and the environment."""
    real = tmp_path / "real-project"
    real.mkdir()
    project = tmp_path / "project"
    project.symlink_to(real)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
    env.update(HOME=str(tmp_path / "home"), PYTHONDONTWRITEBYTECODE="1", **GIT_ENV)
    (tmp_path / "home").mkdir()
    if request.param != "CLAUDE_HOME unset":
        (tmp_path / "elsewhere" / "claude-home").mkdir(parents=True)
        env["CLAUDE_HOME"] = str(tmp_path / "elsewhere" / "claude-home")
    return tmp_path, project, env


def _only(project: Path, filename: str) -> Path:
    hits = list((project / ".claude").rglob(filename))
    assert len(hits) == 1, hits
    return hits[0].parent.resolve()


def _site_dirs(harness: Path, project: Path, name: str, env: dict) -> dict:
    """The registry directory each site used for ``name``."""
    env = {**env, "CLAUDE_PROJECT_DIR": str(project)}
    got = {}
    source = "dev-overnight" if name in (UUID, "s-20260101-000000") else "dev"
    run = subprocess.run(["bash", str(harness / "scripts" / "write-enforce-flag.sh"), "--source-command", source,
                          "--session-id", name, "--flag", "codex"], capture_output=True, text=True, env=env)
    assert run.returncode == 0, run.stderr
    got["write-enforce-flag.sh"] = _only(project, "codex-enforce.json")

    requirement = project / "requirement.md"
    requirement.write_text("x\n")
    run = subprocess.run([sys.executable, str(harness / "scripts" / "graphify-query.py"), "--task-id", name,
                          "--requirement-file", str(requirement), "--no-graphify"],
                         capture_output=True, text=True, env=env, cwd=project)
    assert run.returncode == 0, run.stderr
    got["graphify-query.py"] = _only(project, "pre_query.json").parent

    run = subprocess.run([sys.executable, str(harness / "scripts" / "graphify-enrich.py"), "--task-id", name],
                         capture_output=True, text=True, env={**env, "CLAUDE_GRAPHIFY_ENABLED": "1"}, cwd=project)
    assert run.returncode == 0, run.stderr
    record = _only(project, "graphify-run.json")
    got["graphify-enrich.py (output)"] = record.parent
    detail = json.loads((record / "graphify-run.json").read_text())["error_detail"]
    assert "blast-radius-map.json absent at " in detail, detail
    got["graphify-enrich.py (map default)"] = Path(detail.split(" absent at ", 1)[1]).parent.resolve()

    run = subprocess.run(["bash", str(harness / "scripts" / "overnight-init.sh"), "--session-id", name,
                          "--project-dir", str(project), "--verify-only"], capture_output=True, text=True, env=env)
    lines = [line for line in run.stdout.splitlines() if line.startswith("REGISTRY_DIR=")]
    assert run.returncode == 0 and len(lines) == 1, run.stdout + run.stderr
    got["overnight-init.sh"] = Path(lines[0].split("=", 1)[1]).resolve()
    return got


@pytest.mark.parametrize("name", NAMES)
def test_each_site_uses_the_rule(harness, layout, name):
    _, project, env = layout
    expected = _expected(harness, project, name)
    if harness != REPO:  # the mutation bites: the copy's rule names another directory
        assert expected != _expected(REPO, project, name)
    for site, used in _site_dirs(harness, project, name, env).items():
        assert used == expected, f"{site}: {used} != the rule's {expected}"


def _toy_repo(root: Path, env: dict) -> Path:
    repo = root / "toy"
    def git(*args, cwd=repo):
        subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)
    git("init", "-q", "-b", "master", str(repo), cwd=root)
    git("commit", "-q", "--allow-empty", "-m", "init")
    git("clone", "-q", "--bare", str(repo), str(root / "origin.git"), cwd=root)
    for args in (("remote", "add", "origin", str(root / "origin.git")), ("fetch", "-q", "origin"),
                 ("remote", "set-head", "origin", "master"), ("checkout", "-q", "-b", "night-work")):
        git(*args)
    return repo


@pytest.mark.parametrize("name", [UUID, "s-20260101-000000"])
def test_the_launcher_records_and_makes_the_rules_directory(harness, layout, name):
    """create-overnight-state.sh, in place with a bubblewrap stand-in: the
    dev_registry_dir it records (and creates) is the rule's."""
    root, _, env = layout
    repo = _toy_repo(root, env)
    bin_dir = root / "bin"
    bin_dir.mkdir()
    (bin_dir / "bwrap").write_text('#!/bin/sh\nwhile [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done\n'
                                   '[ "$#" -gt 0 ] && shift\nexec "$@"\n')
    (bin_dir / "bwrap").chmod(0o755)
    run = subprocess.run(["bash", str(harness / "scripts" / "create-overnight-state.sh"), "--end-time", "2h",
                          "--session-id", name, "--project-dir", str(repo)], cwd=repo, capture_output=True,
                         text=True, timeout=300, env={**env, "PATH": f"{bin_dir}:{env.get('PATH', '/usr/bin:/bin')}"})
    assert run.returncode == 0, run.stderr
    recorded = json.loads((repo / ".claude" / f"overnight-state-{name}.json").read_text())["dev_registry_dir"]
    expected = _expected(harness, repo, name)
    assert Path(recorded).resolve() == expected and expected.is_dir()


@pytest.mark.parametrize("command", ["dev", "dev-command"])
def test_the_producer_reserves_the_rules_directory(harness, layout, command):
    """The registry's producer (prompt-workflow.py, a /dev or /dev-command
    start) reserves the directory the readers' rule names for the id it prints."""
    root, project, env = layout
    env = {**env, "CLAUDE_PROJECT_DIR": str(project), "CLAUDE_STATE_DIR": str(root / "state"),
           "CLAUDE_CONFIG_DIR": str(root / "home" / ".claude"), "CLAUDE_CODE_SESSION_ID": "sess-a23"}
    run = subprocess.run([sys.executable, str(harness / "hooks" / "prompt-workflow.py"), "start"],
                         input=f"/{command} a requirement\n", capture_output=True, text=True, env=env, cwd=project,
                         timeout=60)
    assert run.returncode == 0, run.stderr
    prefix = "DEV_SESSION_ID pre-initialized by hook:"
    names = [line[len(prefix):].strip() for line in run.stdout.splitlines() if line.startswith(prefix)]
    assert len(names) == 1 and names[0].startswith(f"{command}-"), run.stdout
    expected = _expected(harness, project, names[0], task_id=True)
    stamp = names[0][len(command) + 1:]
    made = [p.resolve() for p in (project / ".claude").glob(f"*/*{stamp}") if p.is_dir()]
    assert made == [expected]


def test_a_name_that_is_no_path_component_names_no_directory(tmp_path):
    """The rule refuses a traversal; the scripts handed one refuse it, writing nothing."""
    sys.path.insert(0, str(REPO))
    try:
        from hooks.lib.obligation import registry_dir_named
    finally:
        sys.path.remove(str(REPO))
    for bad in ("", ".", "..", "../escape", "a/b"):
        assert registry_dir_named(tmp_path, bad) is None, bad
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")},
           "CLAUDE_PROJECT_DIR": str(tmp_path), "HOME": str(tmp_path / "home"), "PYTHONDONTWRITEBYTECODE": "1"}
    run = subprocess.run([sys.executable, str(REPO / "hooks" / "prompt-workflow.py"), "registry-dir",
                          "--project-dir", str(tmp_path), "--name", "../escape"], capture_output=True, text=True,
                         env=env)
    assert run.returncode == 2 and run.stdout == ""
    run = subprocess.run([sys.executable, str(REPO / "scripts" / "graphify-query.py"), "--task-id", "../escape",
                          "--requirement-file", str(tmp_path / "r.md"), "--no-graphify"],
                         capture_output=True, text=True, env=env, cwd=tmp_path)
    assert run.returncode == 2 and "names no registry directory" in run.stderr
    assert not (tmp_path / ".claude").exists()
