"""P10-42 (R9, D18): what the clean settings form's PYTHONDONTWRITEBYTECODE buys and costs.

R9 set `"PYTHONDONTWRITEBYTECODE": "1"` in settings.json's env so that hooks stop writing
__pycache__ into the harness home. Measured for P10-42 (one Bash call through the 22 hooks the clean
form registers for Bash, 20 Python and 2 shell, 40 interleaved rounds, Python 3.13): with the
variable every Python hook recompiles every harness module it imports on every call, a median
277 ms more CPU per Bash call (p10 190, p90 386) than with a warm __pycache__, and about 100 ms
per call of any other tool (the hooks registered for every tool); without it the bytecode lands
only in __pycache__ directories the tracked .gitignore ignores, nothing lands in the product repo,
and no check (git status, render-settings check, check-public-core, release membership from git)
changes. The variable is dropped from the clean form (integration lane).

The first test pins that drop (strict xfail until the integration lane lands it). The second pins
the effect the drop relies on, on a copy of this tree: the Bash hook chain run without the variable
exits as it does with it, writes __pycache__ only where git ignores it, leaves the harness home's
`git status` and the product repo untouched.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
VAR = "PYTHONDONTWRITEBYTECODE"


def _clean_form() -> dict:
    with open(REPO / "settings.json", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.xfail(strict=True, reason="P10-42, integration: settings.json env still sets "
                   "PYTHONDONTWRITEBYTECODE; the integration lane drops it from the clean form")
def test_the_clean_form_leaves_hook_bytecode_on():
    assert VAR not in _clean_form().get("env", {}), (
        f"settings.json env sets {VAR}: every Python hook recompiles its imports on every call")


def _bash_chain(settings: dict) -> list:
    """The commands settings.json runs for one Bash tool call, in registration order."""
    out = []
    for event in ("PreToolUse", "PostToolUse"):
        for group in settings.get("hooks", {}).get(event, []):
            matcher = group.get("matcher") or ""
            if matcher in ("", "*") or re.fullmatch(matcher, "Bash"):
                out += [(event, h["command"]) for h in group.get("hooks", []) if h.get("command")]
    return out


def _git(cwd, *args, env):
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=cwd, env=env,
                          capture_output=True, text=True, check=True).stdout


def _caches(root: Path) -> list:
    return sorted(str(p.relative_to(root)) for p in root.rglob("__pycache__")
                  if ".git" not in p.relative_to(root).parts)


def test_hooks_without_the_variable_write_only_ignored_bytecode(tmp_path):
    base = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_", "PYTHON"))}
    base.update(HOME=str(tmp_path / "home"), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    home = tmp_path / "home" / ".claude"
    tracked = _git(REPO, "ls-files", "-z", env=base).split("\0")
    for rel in filter(None, tracked):
        src = REPO / rel
        if src.is_file() or src.is_symlink():
            (home / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, home / rel, follow_symlinks=False)
    _git(home, "init", "-q", env=base)
    _git(home, "add", "-A", env=base)
    _git(home, "commit", "-qm", "tree", env=base)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "a.txt").write_text("a\n")
    _git(project, "init", "-q", env=base)
    _git(project, "add", "-A", env=base)
    _git(project, "commit", "-qm", "p", env=base)
    assert _caches(home) == [], "the copy starts without bytecode"
    home_status = _git(home, "status", "--porcelain", "--untracked-files=all", env=base)

    settings = _clean_form()
    chain = _bash_chain(settings)
    assert sum('python3 "' in cmd for _, cmd in chain) >= 7, chain
    sid = "p10-42-0000-0000-0000-000000000000"
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": "list"}}) + "\n")

    def run(with_var: bool) -> list:
        state = tmp_path / ("state-var" if with_var else "state-novar")
        (tmp_path / "tmp").mkdir(exist_ok=True)
        env = dict(base, **{k: str(v) for k, v in settings.get("env", {}).items() if k != VAR})
        env.update(CLAUDE_HOME=str(home), CLAUDE_CONFIG_DIR=str(home), CLAUDE_PROJECT_DIR=str(project),
                   CLAUDE_STATE_DIR=str(state), TMPDIR=str(tmp_path / "tmp"), CLAUDE_CODE_SESSION_ID=sid)
        if with_var:
            env[VAR] = "1"
        rcs = []
        for event, cmd in chain:
            payload = {"session_id": sid, "transcript_path": str(transcript), "cwd": str(project),
                       "hook_event_name": event, "permission_mode": "default", "tool_name": "Bash",
                       "tool_input": {"command": "ls -la", "description": "List files"}}
            if event == "PostToolUse":
                payload["tool_response"] = {"stdout": "a.txt\n", "stderr": "", "interrupted": False}
            proc = subprocess.run(["bash", "-c", cmd], input=json.dumps(payload), cwd=project, env=env,
                                  capture_output=True, text=True, timeout=120)
            rcs.append((cmd, proc.returncode))
        return rcs

    with_var = run(True)
    assert _caches(home) == [], "with the variable the hooks write no bytecode"
    without_var = run(False)
    assert without_var == with_var, "the hooks decide the same without the variable"

    written = _caches(home)
    assert written, "without the variable the hooks write __pycache__ (the cost R9 traded away)"
    ignored = set(filter(None, subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"], cwd=home, env=base, capture_output=True,
        text=True, input="\n".join(d + "/" for d in written)).stdout.splitlines()))
    assert {d + "/" for d in written} == ignored, f"bytecode the tracked .gitignore does not ignore: {written}"
    assert _git(home, "status", "--porcelain", "--untracked-files=all", env=base) == home_status
    assert _caches(project) == [] and _git(project, "status", "--porcelain", "--untracked-files=all",
                                           env=base) == "", "a hook wrote into the product repo"
