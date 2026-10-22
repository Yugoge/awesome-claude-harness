"""The root conftest drops the inherited variables that point a run at the runner's own project or home.

conftest.py removes CLAUDE_PROJECT_DIR, PASEO_CONFIG_DIR, CLAUDE_HOME, CODEX_HOME
and CLAUDE_RESTART_ACCOUNTS_ROOT at import, before any test module is
collected, and removes its scratch root (harness-tests-*) when the session
ends. Inherited, CLAUDE_PROJECT_DIR made tests/test_prompt_workflow_liveness_tz.py
create 30 paths (.claude/dev-registry/ and docs/dev) under the runner's
project, and PASEO_CONFIG_DIR made tests/test_paseo_usage_read.py run the live
paseo adapter against the runner's config. A test that needs one of them sets
it itself.

CI does not set these variables, so the first test alone would only fail on a
developer machine. The second runs a child pytest that inherits all five, each
pointed at a scratch directory, over the first test and those two modules, and
checks that nothing is written into any of the five directories and that the
child leaves no scratch root behind. So the check also runs in CI.
"""

import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

INHERITED = ("CLAUDE_PROJECT_DIR", "PASEO_CONFIG_DIR", "CLAUDE_HOME",
             "CODEX_HOME", "CLAUDE_RESTART_ACCOUNTS_ROOT")

# The modules that wrote into, or read from, an inherited directory before the
# conftest dropped the variables.
AFFECTED = ("tests/test_prompt_workflow_liveness_tz.py",
            "tests/test_paseo_usage_read.py")

# Taken when this module is collected: modules that bind a path at import
# (hooks/lib/subagent_restart.py reads CLAUDE_RESTART_ACCOUNTS_ROOT) see this view.
_AT_COLLECTION = {name: os.environ.get(name) for name in INHERITED}


def _contents(root):
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None
            for p in sorted(root.rglob("*"))}


def test_inherited_variables_are_absent_at_collection():
    assert {n: v for n, v in _AT_COLLECTION.items() if v is not None} == {}


def test_a_run_that_inherits_the_variables_writes_nothing_into_them(tmp_path):
    inherited = {}
    for name in INHERITED:
        target = tmp_path / "inherited" / name
        target.mkdir(parents=True)
        inherited[name] = target
    # A config the live adapter cannot use: had the variable reached
    # tests/test_paseo_usage_read.py, its live case would run on it and fail.
    (inherited["PASEO_CONFIG_DIR"] / "config.json").write_text("{}\n")
    before = {name: _contents(path) for name, path in inherited.items()}
    child_tmp = tmp_path / "tmp"
    child_tmp.mkdir()
    env = dict(os.environ)
    env.update({name: str(path) for name, path in inherited.items()})
    env["TMPDIR"] = str(child_tmp)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
         f"{pathlib.Path(__file__).resolve()}::test_inherited_variables_are_absent_at_collection",
         *(str(REPO / module) for module in AFFECTED)],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=300,
    )

    after = {name: _contents(path) for name, path in inherited.items()}
    assert [n for n in INHERITED if after[n] != before[n]] == [], proc.stdout + proc.stderr
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sorted(p.name for p in child_tmp.glob("harness-tests-*")) == []
