"""The canonical todo script, run in a fork of the reading hook (P1b FX1).

lib.todo_canonical.run_todo_script runs a harness todo script in a fork of the
hook instead of a new ``python3`` when the result cannot differ: the workflow
gate reads the checklist at every tool call, and the interpreter start was the
largest part of that read. These tests hold the fork to the subprocess it
replaces: the same exit status and the same stdout, for every todo script the
harness ships and for the ways a script can end, and the fork is taken only
where those tests reach (the harness's own scripts, this interpreter, no
interpreter option).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
REPO = HOOKS.parent
sys.path.insert(0, str(REPO))
from hooks.lib import todo_canonical  # noqa: E402

SCRIPTS = sorted((REPO / "scripts" / "todo").glob("*.py"))
PROMPTS = ("", "--force", "fix the parser --force --x", "résumé — über")


def _fresh(script, cwd, env):
    """What run_todo_script ran before the fork: a new interpreter."""
    done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, cwd=str(cwd), env=env)
    return done.returncode, done.stdout


def _forked(script, cwd, env):
    done = todo_canonical._run_forked(script, str(cwd), env)
    return done.returncode, done.stdout


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.stem)
def test_every_harness_todo_script_prints_the_same_in_a_fork(script, tmp_path):
    assert SCRIPTS, "no todo scripts found"
    for prompt in PROMPTS:
        env = {**os.environ, "CLAUDE_TODO_PROMPT": prompt}
        assert _forked(script.resolve(), tmp_path, env) == _fresh(script.resolve(), tmp_path, env), prompt


ENDINGS = {
    "raises": "raise ValueError('x')\n",
    "exit-3": "import sys\nsys.exit(3)\n",
    "exit-text": "import sys\nsys.exit('stopped')\n",
    "exit-none": "import sys\nprint('[]')\nsys.exit(None)\n",
    "exit-256": "import sys\nsys.exit(256)\n",
    "os-exit": "import os\nos._exit(5)\n",
    "killed": "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n",
    "crlf": "import sys\nsys.stdout.write('[{\"a\": 1}]\\r\\n\\r')\n",
    "unicode": "print('[{\"content\": \"é—ü\"}]')\n",
    "prompt-and-cwd": "import json, os\nprint(json.dumps([{'p': os.environ['CLAUDE_TODO_PROMPT'], 'cwd': os.getcwd()}]))\n",
    "main-only": "if __name__ == '__main__':\n    print('[{\"main\": true}]')\n",
    "stderr": "import sys\nsys.stderr.write('noise\\n')\nprint('[]')\n",
    "sibling": "from sibling_mod import STEPS\nimport json\nprint(json.dumps(STEPS))\n",
}


@pytest.mark.parametrize("ending", sorted(ENDINGS))
def test_a_script_ends_the_same_in_a_fork(ending, tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "sibling_mod.py").write_text("STEPS = [{'content': 'Step 1'}]\n", encoding="utf-8")
    script = scripts / f"{ending}.py"
    script.write_text(ENDINGS[ending], encoding="utf-8")
    cwd = tmp_path / "project"
    cwd.mkdir()
    env = {**os.environ, "CLAUDE_TODO_PROMPT": "a b", "PYTHONDONTWRITEBYTECODE": "1"}
    assert _forked(script, cwd, env) == _fresh(script, cwd, env)


_PROBE = """
import json, os, sys
sys.path.insert(0, {hooks!r})
from lib import todo_canonical
env = dict(os.environ)
print(json.dumps([todo_canonical._forkable(p, env) for p in sys.argv[1:]]))
"""


def _probe(tmp_path, *scripts, python, options=(), path=None):
    """_forkable as a hook started as ``<python> <hook file>`` sees it."""
    probe = tmp_path / "probe.py"
    probe.write_text(_PROBE.format(hooks=str(HOOKS)), encoding="utf-8")
    env = {**os.environ, "PATH": path or (str(Path(python).parent) + os.pathsep + os.environ.get("PATH", "")),
           "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([python, *options, str(probe), *map(str, scripts)], capture_output=True, text=True,
                          env=env, check=True)
    return json.loads(done.stdout)


def test_the_fork_is_taken_only_where_it_prints_the_same(tmp_path):
    python = tmp_path / "interpreter" / "python3"  # started by this name, as settings.json starts the hooks
    python.parent.mkdir()
    python.symlink_to(sys.executable)
    harness = REPO / "scripts" / "todo" / "dev.py"
    copy = tmp_path / "project" / "scripts" / "todo" / "dev.py"
    copy.parent.mkdir(parents=True)
    shutil.copy(harness, copy)
    # The harness's own script, started as the hooks are: forked.
    # A project's own todo script: a new interpreter, as before.
    assert _probe(tmp_path, harness, copy, python=str(python)) == [True, False]
    # An interpreter option, or another python3 first on the PATH: a new interpreter.
    assert _probe(tmp_path, harness, python=str(python), options=("-B",)) == [False]
    other = tmp_path / "bin"
    other.mkdir()
    (other / "python3").symlink_to(python)
    assert _probe(tmp_path, harness, python=str(python),
                  path=str(other) + os.pathsep + str(python.parent)) == [False]


def test_run_todo_script_reads_the_same_list_either_way(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    for command, prompt in (("dev", ""), ("close", "--force"), ("close", ""), ("redev", "x"), ("spec", "y")):
        monkeypatch.setattr(todo_canonical, "_forkable", lambda *_: True)
        forked = todo_canonical.run_todo_script(command, prompt)
        monkeypatch.setattr(todo_canonical, "_forkable", lambda *_: False)
        assert forked == todo_canonical.run_todo_script(command, prompt) and forked, (command, prompt)
