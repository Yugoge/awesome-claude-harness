"""P2 R1-R3: a product repository never supplies the harness's own files.

A product whose scripts/todo/<command>.py and hooks/lib/close-verdict.py exist
(each printing or carrying a marker) is the project: every todo-script resolver
(prompt-workflow.py's run_todo_script, lib.todo_canonical, which the todo
tracker, todo count and workflow gate read through, and the Codex path of
pretool-workflow-gate.py) runs the harness's script, and dev-lifecycle.py loads
the harness's close-verdict.py. R1: every harness slash command (a commands/*.md
stem, with or without a todo script) starts its output with the two roots its
text's Read paths use, PROJECT_ROOT=<abs> and HARNESS_ROOT=<abs>; in
/dev-overnight PROJECT_ROOT is the record's worktree_path (the command's
<PROJECT_ROOT>); any other slash command prints neither.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MARKER = "PRODUCT-TODO-MARKER"
PRODUCT_TODO = (
    "import json\n"
    f"print(json.dumps([{{'content': '{MARKER}', 'activeForm': '{MARKER}', 'status': 'pending'}}]))\n"
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _harness_list(command: str, project: Path) -> list:
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "todo" / f"{command}.py")],
                         capture_output=True, text=True, cwd=project, check=True)
    return json.loads(out.stdout)


@pytest.fixture
def product(tmp_path, monkeypatch):
    project = tmp_path / "product"
    for command in ("dev", "close", "commit", "status"):
        script = project / "scripts" / "todo" / f"{command}.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(PRODUCT_TODO)
    verdict = project / "hooks" / "lib" / "close-verdict.py"
    verdict.parent.mkdir(parents=True)
    verdict.write_text(f"MARKER = '{MARKER}'\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.chdir(project)
    return project


def _prompt(project: Path, tmp_path: Path, text: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=str(tmp_path / "home"), CLAUDE_CONFIG_DIR=str(tmp_path / "home" / ".claude"),
               CLAUDE_STATE_DIR=str(tmp_path / "state"), CLAUDE_PROJECT_DIR=str(project),
               TMPDIR=str(tmp_path), GIT_CEILING_DIRECTORIES=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    (tmp_path / "state").mkdir(exist_ok=True)
    transcript = tmp_path / "transcript.jsonl"
    transcript.touch()
    payload = {"session_id": str(uuid.uuid4()), "prompt": text, "cwd": str(project),
               "transcript_path": str(transcript), "hook_event_name": "UserPromptSubmit"}
    return subprocess.run([sys.executable, str(ROOT / "hooks" / "prompt-workflow.py")],
                          input=json.dumps(payload), capture_output=True, text=True, env=env,
                          cwd=project, timeout=60)


def test_dev_start_runs_the_harness_todo_script_and_prints_both_roots_first(product, tmp_path):
    proc = _prompt(product, tmp_path, "/dev probe requirement")
    assert proc.returncode == 0, proc.stderr
    assert MARKER not in proc.stdout
    assert proc.stdout.splitlines()[:2] == [f"PROJECT_ROOT={product}", f"HARNESS_ROOT={ROOT}"]
    canonical = _harness_list("dev", product)
    assert "CHECKLIST PRE-INITIALIZED for /DEV:" in proc.stdout
    assert f"({len(canonical)} steps)" in proc.stdout


def test_push_prints_heads_branch_and_commit_after_the_roots(product, tmp_path):
    """P5 review H2: /push then prints HEAD's branch (or `detached`) and commit, the line the /push
    Stop reads through hooks/lib/command_span.py's OPENER_HEAD_LINE_RE; none while HEAD names no
    commit (no repository, no commit yet), and no other command prints one."""
    span = _load(ROOT / "hooks" / "lib" / "command_span.py", "command_span_todo_root")
    roots = f"PROJECT_ROOT={product}\nHARNESS_ROOT={ROOT}\n"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_"))}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CEILING_DIRECTORIES=str(tmp_path))

    def git(*args):
        return subprocess.run(["git", "-C", str(product), *args], capture_output=True, text=True, env=env,
                              check=True).stdout.strip()
    assert _prompt(product, tmp_path, "/push").stdout == roots
    git("init", "-q", "-b", "topic/x")
    assert _prompt(product, tmp_path, "/push").stdout == roots
    git("add", "-A")
    git("commit", "-q", "-m", "c")
    head = git("rev-parse", "HEAD")
    for ref in ("refs/heads/topic/x", "detached"):
        if ref == "detached":
            git("checkout", "-q", "--detach")
        out = _prompt(product, tmp_path, "/push origin").stdout
        assert out == roots + f"[/push] HEAD at the opener: {ref} {head}\n", out
        assert [m.groups() for m in span.OPENER_HEAD_LINE_RE.finditer(out)] == [(ref, head)]
    assert _prompt(product, tmp_path, "/merge").stdout == roots


@pytest.mark.parametrize("command, printed", [("commit", True), ("merge", True), ("status", False)])
def test_roots_for_every_harness_command_only(product, tmp_path, command, printed):
    """/commit and /merge have no todo script; /status is no harness command."""
    proc = _prompt(product, tmp_path, f"/{command}")
    assert proc.returncode == 0, proc.stderr
    expected = f"PROJECT_ROOT={product}\nHARNESS_ROOT={ROOT}\n" if printed else ""
    assert proc.stdout == expected


def test_overnight_project_root_is_the_records_worktree_path(product, tmp_path, capsys):
    module = _load(ROOT / "hooks" / "prompt-workflow.py", "prompt_workflow_todo_root")
    module.PROJECT_DIR = product
    worktree = product / ".claude" / "worktrees" / "w1"
    state = product / ".claude" / "overnight-state-s1.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"session_id": "s1", "worktree_path": str(worktree)}))
    module.print_roots("dev-overnight", "s1")
    assert capsys.readouterr().out == f"PROJECT_ROOT={worktree}\nHARNESS_ROOT={ROOT}\n"


def test_lib_todo_canonical_runs_the_harness_script(product):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from hooks.lib import todo_canonical
    for command in ("dev", "close"):
        assert todo_canonical.run_todo_script(command) == _harness_list(command, product)
    assert todo_canonical.run_todo_script("status") is None  # the harness has none


def test_workflow_gate_codex_path_runs_the_harness_script(product):
    gate = _load(ROOT / "hooks" / "pretool-workflow-gate.py", "workflow_gate_todo_root")
    assert gate.run_canonical_todos("dev", product) == _harness_list("dev", product)
    assert gate.run_canonical_todos("status", product) == []


def test_dev_lifecycle_loads_the_harness_close_verdict(product):
    lifecycle = _load(ROOT / "scripts" / "dev-lifecycle.py", "dev_lifecycle_todo_root")
    verdict = lifecycle._load_close_verdict_module()
    assert Path(verdict.__file__) == ROOT / "hooks" / "lib" / "close-verdict.py"
    assert not hasattr(verdict, "MARKER")
