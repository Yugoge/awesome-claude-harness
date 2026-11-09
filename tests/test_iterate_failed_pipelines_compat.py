"""scripts/iterate-failed-pipelines.py, COMPATIBILITY CODE: delete with it once no session predates train 2's landing.

It answers the call origin/master's /dev-overnight Step 17 makes (commands/dev-overnight.md:1384 on a7d3a9f,
:1487 on 2acc29b) as master's script (a7d3a9f) does. Nothing in this tree calls it.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "iterate-failed-pipelines.py"
MASTER = "a7d3a9fe"  # origin/master's tree before train 2: the script as master ships it
SESSION_ID = "20261109-010000"
# master's Step 17 command line, as its text spells it
STEP_17 = ("python3 ~/.claude/scripts/iterate-failed-pipelines.py docs/dev/overnight/<session_id>/pipelines.json"
           " > docs/dev/overnight/<session_id>/iteration-plan.json")
USAGE = "Usage: iterate-failed-pipelines.py <pipelines.json>\n"

# failed and passed pipelines, of every severity, an unknown one and none, and of ties in severity
PIPELINES = [
    {"index": 0, "timestamp_suffix": "20261109-010000", "phase": "done", "status": "fixed", "severity": "critical",
     "agents_flagged": ["qa"], "spec_path": "docs/dev/overnight/S/spec-0.md", "iteration": 1},
    {"index": 1, "timestamp_suffix": "20261109-010100", "phase": "qa_failed", "severity": "minor",
     "agents_flagged": ["qa"], "spec_path": "docs/dev/overnight/S/spec-1.md", "iteration": 2},
    {"index": 2, "timestamp_suffix": "20261109-010200", "phase": "qa_failed", "severity": "critical",
     "agents_flagged": ["qa"], "spec_path": "docs/dev/overnight/S/spec-2.md"},
    {"index": 3, "timestamp_suffix": "20261109-010300", "phase": "qa_failed", "severity": "major",
     "agents_flagged": ["qa", "ui-specialist"], "spec_path": "docs/dev/overnight/S/spec-3.md", "iteration": 1},
    {"index": 4, "timestamp_suffix": "20261109-010400", "phase": "qa_failed", "severity": "critical",
     "agents_flagged": ["qa", "ui-specialist", "dev"], "spec_path": "docs/dev/overnight/S/spec-4.md", "iteration": 3},
    {"index": 5, "timestamp_suffix": "20261109-010500", "phase": "done", "status": "fixed", "severity": "minor"},
    {"index": 6, "timestamp_suffix": "20261109-010600", "phase": "qa_failed"},
    {"index": 7, "timestamp_suffix": "20261109-010700", "phase": "qa_failed", "severity": "cosmetic",
     "agents_flagged": ["qa", "dev"], "spec_path": "docs/dev/overnight/S/spec-7.md"},
    {"index": 8, "timestamp_suffix": "20261109-010800", "phase": "qa_failed", "severity": "blocker",
     "agents_flagged": ["qa"], "spec_path": "docs/dev/overnight/S/spec-8.md", "iteration": 1},
    {"index": 9, "timestamp_suffix": "20261109-010900", "phase": "qa_failed", "severity": "major",
     "agents_flagged": [], "spec_path": "docs/dev/overnight/S/spec-9.md", "iteration": 4},
]


def _entry(index: int, spec_path: str, iteration: int) -> str:
    return ('    {\n      "index": %d,\n      "timestamp_suffix": "20261109-01%02d00",\n      "spec_path": %s,\n'
            '      "current_iteration": %d,\n      "next_action": "ba_dev_qa_loop"\n    }'
            % (index, index, spec_path, iteration))


# a7d3a9f's script's stdout for PIPELINES, byte for byte (indent 2, no trailing newline), with %s the
# project directory as a JSON string
EXPECTED = '{\n  "project_dir": %s,\n  "iteration_plan": [\n' + ",\n".join(
    _entry(i, f'"docs/dev/overnight/S/spec-{i}.md"' if spec else "null", it)
    for i, spec, it in ((4, 1, 3), (2, 1, 0), (3, 1, 1), (9, 1, 4), (1, 1, 2), (7, 1, 0), (8, 1, 1), (6, 0, 0))
) + "\n  ]\n}"


def _home(tmp_path: Path, script: Path | None = None) -> Path:
    """A HOME whose ~/.claude is this checkout, or holds only `script` as its scripts/iterate-failed-pipelines.py."""
    home = tmp_path / "home"
    home.mkdir()
    if script is None:
        (home / ".claude").symlink_to(REPO, target_is_directory=True)
    else:
        (home / ".claude" / "scripts").mkdir(parents=True)
        (home / ".claude" / "scripts" / "iterate-failed-pipelines.py").write_bytes(script.read_bytes())
    return home


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    session = project / "docs" / "dev" / "overnight" / SESSION_ID
    session.mkdir(parents=True)
    (session / "pipelines.json").write_text(json.dumps(PIPELINES, indent=2), encoding="utf-8")
    return project


def _step_17(home: Path, project: Path, env_project_dir: bool, line: str = STEP_17) -> tuple:
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    env["HOME"] = str(home)
    if env_project_dir:
        env["CLAUDE_PROJECT_DIR"] = str(project)
    proc = subprocess.run(["bash", "-c", line.replace("<session_id>", SESSION_ID)], cwd=project, env=env,
                          capture_output=True, text=True, check=False)
    plan = project / "docs" / "dev" / "overnight" / SESSION_ID / "iteration-plan.json"
    return proc.returncode, proc.stdout, proc.stderr, plan.read_bytes() if plan.exists() else None


@pytest.mark.parametrize("env_project_dir", [True, False], ids=["CLAUDE_PROJECT_DIR", "cwd"])
def test_masters_step_17_gets_masters_plan(tmp_path, env_project_dir):
    project = _project(tmp_path)
    rc, out, err, plan = _step_17(_home(tmp_path), project, env_project_dir)
    project_dir = str(project) if env_project_dir else str(project.resolve())  # the env value, else getcwd()
    assert (rc, out, err) == (0, "", "")
    assert plan == (EXPECTED % json.dumps(project_dir)).encode("utf-8")


def test_no_argument_is_masters_usage_error(tmp_path):
    rc, out, err, _ = _step_17(_home(tmp_path), _project(tmp_path), True,
                               "python3 ~/.claude/scripts/iterate-failed-pipelines.py")
    assert (rc, out, err) == (1, "", USAGE)


def test_it_is_masters_script_where_master_is_in_history(tmp_path):
    blob = subprocess.run(["git", "-C", str(REPO), "show", f"{MASTER}:scripts/iterate-failed-pipelines.py"],
                          capture_output=True, check=False)
    if blob.returncode != 0:
        pytest.skip(f"{MASTER} is not in this clone's history")
    master = tmp_path / "master.py"
    master.write_bytes(blob.stdout)
    assert _below_docstring(SCRIPT) == _below_docstring(master)
    cases = [(env_project_dir, line) for env_project_dir in (True, False)
             for line in (STEP_17, "python3 ~/.claude/scripts/iterate-failed-pipelines.py")]
    for n, (env_project_dir, line) in enumerate(cases):
        ours, theirs = tmp_path / f"ours-{n}", tmp_path / f"theirs-{n}"
        ours.mkdir()
        theirs.mkdir()
        got = _step_17(_home(ours), _project(ours), env_project_dir, line)
        want = _step_17(_home(theirs, master), _project(theirs), env_project_dir, line)
        assert got[:3] == want[:3]
        assert (got[3] or b"").replace(str(ours).encode(), b"<tmp>") == \
            (want[3] or b"").replace(str(theirs).encode(), b"<tmp>")


def _below_docstring(script: Path) -> str:
    return script.read_text(encoding="utf-8").split('"""\n', 1)[1]  # the docstring opens on its first line


def test_nothing_in_this_tree_calls_it():
    files = [p for d in ("commands", "agents", "hooks", "scripts", "skills") if (REPO / d).is_dir()
             for p in (REPO / d).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    callers = [p for p in files if p != SCRIPT and p.name not in ("INDEX.md", "README.md")
               and "iterate-failed-pipelines" in p.read_text(encoding="utf-8", errors="replace")]
    assert callers == []
