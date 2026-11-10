"""P10-42 (R9, D18): the clean settings form keeps PYTHONDONTWRITEBYTECODE, the accepted choice.

R9 set `"PYTHONDONTWRITEBYTECODE": "1"` in settings.json's env so that hooks stop writing
__pycache__ into the harness home. Two measurements, one decision:

- Group 2 (fc0d6a6, P10-42): one Bash call through the 22 hooks the pre-P12 clean form registered
  for Bash (20 Python, 2 shell), run one after another, 40 interleaved rounds, Python 3.13: with
  the variable every Python hook recompiles every harness module it imports, a median +277 ms CPU
  summed over the chain (p10 190, p90 386) against a warm __pycache__; it proposed dropping it.
- P12's integration lane (fc8d436, PR #33 "Decisions"): "PYTHONDONTWRITEBYTECODE=1 stays: about
  +63 ms per Bash call, and without it 36 .pyc files land in the harness home (15 alternating
  runs)". That decision is on master and stands.

Re-measured on the merged tree with fc0d6a6's method (17 hooks for Bash after P12's consolidation,
14 Python and 3 shell, 30 interleaved rounds): +190 ms CPU median (p10 136, p90 252) on Python 3.13
and +173 ms on 3.12, summed over the chain; the per-hook deltas are 0-44 ms. The two figures measure
different things: +277/+190 is the CPU the whole chain pays, while +63 is of the order of one
call's added latency when the CLI runs each event's hooks side by side on an idle host, where only
the slowest hook's delta shows. P12 recorded no method beyond "15 alternating runs", so that
reading is an inference, not a reproduction.

The first test pins the accepted choice. The second pins the variable's effect, on a copy of this
tree: the Bash hook chain decides the same with and without it, writes no __pycache__ with it, and
without it writes __pycache__ only where the tracked .gitignore ignores it, leaving the harness
home's `git status` and the product repo untouched.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VAR = "PYTHONDONTWRITEBYTECODE"


def _clean_form() -> dict:
    with open(REPO / "settings.json", encoding="utf-8") as fh:
        return json.load(fh)


def test_the_clean_form_keeps_hook_bytecode_off():
    """P12's integration lane kept the variable by experiment (fc8d436, PR #33 "Decisions": about
    +63 ms per Bash call, and without it 36 .pyc files land in the harness home), over P10-42's
    +277 ms CPU median per Bash call (fc0d6a6). A change here reopens that decision."""
    assert _clean_form().get("env", {}).get(VAR) == "1", (
        f"settings.json env no longer sets {VAR}=1, which P12's integration lane decided to keep")


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
    # The chain runs as registered (P12-L7: one launcher process per event); the Python hooks it
    # runs are counted through the launchers' expansion (hooks/lib/launch_settings.py).
    spec = importlib.util.spec_from_file_location("_launch_settings", REPO / "hooks" / "lib" / "launch_settings.py")
    launch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launch)
    expanded = _bash_chain(launch.expand(settings, str(REPO)))
    assert sum('python3 "' in cmd for _, cmd in expanded) >= 7, expanded
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
    assert written, "without the variable the hooks write __pycache__ (what R9 keeps out)"
    ignored = set(filter(None, subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"], cwd=home, env=base, capture_output=True,
        text=True, input="\n".join(d + "/" for d in written)).stdout.splitlines()))
    assert {d + "/" for d in written} == ignored, f"bytecode the tracked .gitignore does not ignore: {written}"
    assert _git(home, "status", "--porcelain", "--untracked-files=all", env=base) == home_status
    assert _caches(project) == [] and _git(project, "status", "--porcelain", "--untracked-files=all",
                                           env=base) == "", "a hook wrote into the product repo"
