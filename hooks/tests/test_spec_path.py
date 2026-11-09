"""hooks/lib/spec_path.py: the spec a session last wrote (P1b E14, PLAN-v2 P9 row 1),
and prompt-workflow.py's one decision of a run's spec built on it, replayed at
UserPromptSubmit for /dev, /dev-command and /dev-overnight (P9 R1, acceptance A3)."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
REPO = HOOKS.parent
sys.path.insert(0, str(HOOKS / "lib"))
import spec_path  # noqa: E402

PROJECT = "/work/proj"
SPEC = f"{PROJECT}/docs/dev/specs/spec-20261028-101010.md"
OTHER = f"{PROJECT}/docs/dev/specs/spec-20261028-202020.md"


def _transcript(tmp_path, calls, cwd=PROJECT):
    """calls: (name, input, result_text or None for no result, is_error)."""
    path = tmp_path / "t.jsonl"
    lines = [{"type": "user", "message": {"role": "user", "content": "/spec"}}]
    for n, (name, tool_input, result, is_error) in enumerate(calls):
        tid = f"t{n}"
        lines.append({"type": "assistant", "cwd": cwd, "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": name, "input": tool_input}]}})
        if result is not None:
            block = {"type": "tool_result", "tool_use_id": tid, "content": result}
            if is_error:
                block["is_error"] = True
            lines.append({"type": "user", "message": {"role": "user", "content": [block]}})
    path.write_text("".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8")
    return str(path)


def _bash_writer(path, op="append"):
    return ("Bash", {"command": f'python3 ~/.claude/scripts/spec-write.py {op} --spec "$spec_path" --section 5'},
            f"spec-write: {op} {path}\n", False)


def test_the_last_ok_write_wins(tmp_path):
    t = _transcript(tmp_path, [("Write", {"file_path": OTHER, "content": "x"}, "ok", False),
                               ("Edit", {"file_path": SPEC}, "ok", False)])
    assert spec_path.last_spec_write(t) == SPEC


def test_a_call_of_the_one_writer_counts_as_a_write(tmp_path):
    t = _transcript(tmp_path, [("Write", {"file_path": OTHER, "content": "x"}, "ok", False), _bash_writer(SPEC)])
    assert spec_path.last_spec_write(t) == SPEC


def test_relative_paths_resolve_against_the_record_cwd(tmp_path):
    t = _transcript(tmp_path, [("MultiEdit", {"file_path": "docs/dev/specs/spec-20261028-101010.md"}, "ok", False)])
    assert spec_path.last_spec_write(t) == SPEC


def test_what_is_not_a_spec_write(tmp_path):
    t = _transcript(tmp_path, [
        ("Write", {"file_path": SPEC, "content": "x"}, "ok", False),
        ("Write", {"file_path": OTHER, "content": "x"}, "denied", True),        # an error result
        ("Edit", {"file_path": OTHER}, None, False),                            # no result
        ("Read", {"file_path": OTHER}, "text", False),                          # a read
        ("Write", {"file_path": f"{PROJECT}/docs/dev/specs/INDEX.md"}, "ok", False),
        ("Write", {"file_path": f"{PROJECT}/docs/dev/specs/README.md"}, "ok", False),
        ("Write", {"file_path": f"{PROJECT}/docs/dev/specs/20261028-202020/views/ba.md"}, "ok", False),
        ("Bash", {"command": f"echo spec-write: append {OTHER}"}, f"spec-write: append {OTHER}\n", False),
        ("Bash", {"command": "python3 spec-write.py append --spec x --section 5"}, "refused", True),
    ])
    assert spec_path.last_spec_write(t) == SPEC


def test_no_write_or_no_transcript_is_none(tmp_path):
    assert spec_path.last_spec_write(_transcript(tmp_path, [])) is None
    assert spec_path.last_spec_write(str(tmp_path / "absent.jsonl")) is None


def _prompt_workflow(project_dir):
    spec = importlib.util.spec_from_file_location("prompt_workflow_under_test", HOOKS / "prompt-workflow.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PROJECT_DIR = Path(project_dir)
    return module


def test_decide_spec_path_explicit_first_then_the_session(tmp_path):
    pw = _prompt_workflow(tmp_path)
    explicit = tmp_path / "docs/dev/specs/spec-20261028-202020.md"
    explicit.parent.mkdir(parents=True)
    explicit.write_text("# spec\n")
    pw.CURRENT_TRANSCRIPT_PATH = _transcript(tmp_path, [_bash_writer(SPEC, "create")])
    assert pw.decide_spec_path("docs/dev/specs/spec-20261028-202020.md", "sid") == (
        str(explicit), f"Spec: {explicit} (explicit)")
    assert pw.decide_spec_path("", "sid") == (SPEC, f"Spec: {SPEC}")
    pw.CURRENT_TRANSCRIPT_PATH = _transcript(tmp_path, [])
    assert pw.decide_spec_path("", "sid") == ("", "Spec: none")


# --- A3: UserPromptSubmit through the hook's real entry point ------------------

SID = "spec-path-a3"
SPECS = Path("docs/dev/specs")
# An in-place /dev-overnight launch refuses where `bwrap --ro-bind / / -- true` cannot run
# (P2 R13), and CI's unit job has no bubblewrap: the replays' stand-in (it skips bwrap's
# options up to `--` and runs the rest) comes first on the launch's PATH, as there.
BWRAP_STAND_IN = REPO / "tests" / "replay" / "bin"


def _git_project(proj: Path, env: dict) -> None:
    """A primary checkout the overnight launcher accepts in place: HEAD on 'work',
    protected branch 'master' from local refs; no branch-creating verb is used."""
    def g(*args):
        subprocess.run(["git", "-C", str(proj), *args], env=env, capture_output=True, check=True)
    g("init", "-q")
    g("config", "user.email", "lab@example.invalid")
    g("config", "user.name", "lab")
    g("symbolic-ref", "HEAD", "refs/heads/work")
    g("commit", "--allow-empty", "-q", "-m", "init")
    sha = subprocess.run(["git", "-C", str(proj), "rev-parse", "HEAD"], env=env, capture_output=True,
                         text=True, check=True).stdout.strip()
    g("update-ref", "refs/remotes/origin/master", sha)
    g("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/master")


def _submit(tmp_path: Path, prompt: str, written=(), present=(), git=False):
    """One UserPromptSubmit of `prompt` (`@P` = the project) in a session whose
    transcript holds an ok Write of each path in `written`; `present` files exist."""
    proj, home = tmp_path / "toyproj", tmp_path / "home"
    proj.mkdir()
    (home / ".claude").mkdir(parents=True)
    env = {**os.environ, "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
           "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_STATE_DIR": str(tmp_path / "state"),
           "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    env.pop("CLAUDE_COMPAT_RUNTIME", None)
    if git:
        env.pop("CLAUDE_OVERNIGHT_FORCE_NO_BWRAP", None)
        env["PATH"] = f"{BWRAP_STAND_IN}:{env.get('PATH', '/usr/bin:/bin')}"
        _git_project(proj, env)
    for rel in present:
        (proj / rel).parent.mkdir(parents=True, exist_ok=True)
        (proj / rel).write_text("# spec\n")
    calls = [("Write", {"file_path": str(proj / rel), "content": "x"}, "ok", False) for rel in written]
    payload = {"session_id": SID, "cwd": str(proj), "prompt": prompt.replace("@P", str(proj)),
               "transcript_path": _transcript(tmp_path, calls, cwd=str(proj))}
    result = subprocess.run([sys.executable, str(HOOKS / "prompt-workflow.py")], input=json.dumps(payload),
                            capture_output=True, text=True, env=env, cwd=str(proj), timeout=300)
    assert "Traceback" not in result.stderr, result.stderr
    return proj, result


def _spec_lines(text: str) -> list:
    return [line for line in text.splitlines() if line.startswith("Spec:")]


# (transcript writes, files present, arguments, expected line with @P for the project)
CASES = {
    "session_write": ([SPECS / "foo.md"], [SPECS / "foo.md"], "", "Spec: @P/docs/dev/specs/foo.md"),
    "no_write": ([], [], "", "Spec: none"),
    "index_only": ([SPECS / "INDEX.md"], [SPECS / "INDEX.md"], "", "Spec: none"),
    "explicit_present": ([SPECS / "foo.md"], [SPECS / "foo.md", SPECS / "bar.md"],
                         "--spec @P/docs/dev/specs/bar.md", "Spec: @P/docs/dev/specs/bar.md (explicit)"),
}


@pytest.mark.parametrize("command", ["dev", "dev-command"])
@pytest.mark.parametrize("case", sorted(CASES))
def test_the_start_prints_the_spec_the_hook_decided(tmp_path, command, case):
    written, present, args, expected = CASES[case]
    proj, result = _submit(tmp_path, f"/{command} {args} x".replace("  ", " "), written, present)
    assert result.returncode == 0, result.stderr
    expected = expected.replace("@P", str(proj))
    assert _spec_lines(result.stdout) == [expected]
    [record] = (proj / ".claude" / "dev-start-replays" / SID).iterdir()  # stored for replay
    assert expected + "\n" in json.loads(record.read_text())["stdout"]
    assert len(list((proj / ".claude" / "dev-registry").iterdir())) == 1


@pytest.mark.parametrize("command", ["dev", "dev-command", "redev"])
@pytest.mark.parametrize("bad", ["docs/dev/specs/bar.md", "docs/dev/specs"])  # absent file; a directory
def test_an_unreadable_explicit_spec_blocks_the_prompt_before_any_write(tmp_path, command, bad):
    proj, result = _submit(tmp_path, f"/{command} --spec {bad} x", [SPECS / "foo.md"], [SPECS / "foo.md"])
    assert result.returncode == 2
    assert f"Spec: {proj / bad} (unresolved)" in result.stderr.splitlines()
    assert result.stdout == ""
    claude = proj / ".claude"
    assert not (claude / "dev-registry").exists()
    assert not (claude / "dev-start-replays").exists()
    assert not (claude / f"workflow-{SID}.json").exists()


@pytest.mark.parametrize("case", sorted(CASES) + ["explicit_absent"])
def test_dev_overnight_prints_the_spec_and_its_state_follows_the_line(tmp_path, case):
    if case == "explicit_absent":
        written, present, args, expected = [SPECS / "foo.md"], [SPECS / "foo.md"], "--spec @P/docs/dev/specs/bar.md", None
    else:
        written, present, args, expected = CASES[case]
    proj, result = _submit(tmp_path, f"/dev-overnight 23:59 {args}".strip(), written, present, git=True)
    claude = proj / ".claude"
    if expected is None:
        assert result.returncode == 2
        assert f"Spec: {proj / SPECS / 'bar.md'} (unresolved)" in result.stderr.splitlines()
        assert not (claude / "dev-registry").exists()
        assert not list(claude.glob("overnight-state-*.json"))
        return
    assert result.returncode == 0, result.stderr
    expected = expected.replace("@P", str(proj))
    assert _spec_lines(result.stdout) == [expected]
    state = json.loads((claude / f"overnight-state-{SID}.json").read_text())
    printed = re.match(r"Spec: (\S+)", expected).group(1)
    if printed == "none":
        assert (state["spec_mode"], state["user_spec_path"]) == ("autonomous", None)
    else:
        assert (state["spec_mode"], state["user_spec_path"]) == ("user-provided", printed)


def test_no_mtime_rule_chooses_a_spec():
    """A3's grep: the hook's line is the one spec decision; no listing or mtime rule is left."""
    rule = re.compile(r"stat -c %Y|ls -t docs/dev/specs|sort -rn")
    for rel in ("commands/dev.md", "commands/dev-command.md", "scripts/create-overnight-state.sh"):
        assert not rule.search((REPO / rel).read_text(encoding="utf-8")), rel
