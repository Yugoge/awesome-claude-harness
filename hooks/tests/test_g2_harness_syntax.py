#!/usr/bin/env python3
"""P6 F3.a: at a dev's or test-writer's own stop, G2 (hooks/subagentstop-
artifact-contract-enforce.py, _harness_syntax) parses every file of the
agent's own written set whose realpath is under the live harness home's
hooks/ or scripts/: the built-in compiler for Python, `bash -n` for shell.

A broken file blocks the stop: exit 2 with a G2 finding naming the file and
the message. The check only warned in the commit that introduced it, so each
case also runs a copy of the hook with SYNTAX_BLOCK set to False (that
warning mode), which prints `F3.a would block: <path>: <message>` and changes
no exit code; every clean case passes both. The harness home is a copy of
the hook tree laid out the way claude_home.resolve() finds it (settings.json,
hooks/, policies/ and scripts/ together); transcripts are synthetic, in the
records G2's tests use. After every stop, nothing has written a __pycache__
under the harness home.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

import pytest

import test_artifact_contract_enforce as base  # noqa: E402  (hooks/tests on sys.path)

TASK = base.G2_TASK
WARN = "F3.a would block"
BROKEN_PY = "def f(:\n    return 1\n"
BROKEN_SH = "#!/usr/bin/env bash\nif true; then\n  echo hi\n"


@pytest.fixture
def harness(tmp_path):
    """(home, hook, warning hook, marker): the harness home holds the hook as it
    is and a copy with SYNTAX_BLOCK set to False (the warning mode); the marker
    is older than any run."""
    hook = base._l2_hook_tree(tmp_path)
    home = hook.parent.parent
    (home / "settings.json").write_text("{}\n", encoding="utf-8")
    (home / "policies").mkdir()
    text = hook.read_text(encoding="utf-8")
    assert text.count("SYNTAX_BLOCK = True") == 1
    warning = hook.with_name("warning-" + hook.name)
    warning.write_text(text.replace("SYNTAX_BLOCK = True", "SYNTAX_BLOCK = False"), encoding="utf-8")
    resolved = subprocess.run([sys.executable, "-B", str(home / "hooks" / "lib" / "claude_home.py"), "resolve"],
                              capture_output=True, text=True, check=True).stdout.strip()
    assert resolved == str(home.resolve())
    marker = tmp_path / "marker"
    marker.touch()
    return home.resolve(), hook, warning, marker


def _agent(tmp_path, role: str):
    """A registered dev or test-writer whose dispatch obligation declares one
    report, written schema-valid, so its stop reaches G2's wires."""
    report = f"docs/dev/{role}-report-{TASK}.json"
    schema = {"dev": "dev-report.v1", "test-writer": "test-writer-report.v1"}[role]
    s = base._g2_setup(tmp_path, role, [base._g2_json(report, schema)])
    base._write(s.project / report, base._valid_dev_report_v1(TASK) if role == "dev" else {
        "task_id": TASK, "timestamp": datetime.now(timezone.utc).isoformat(),
        "manifest_path": f"tests/generated/{TASK}/manifest.json",
        "trigger_gate": {"complexity_tier": "STANDARD", "risk_level": "low", "fired": True},
        "tests_created": [], "tests_archived": [], "tests_skipped_idempotent": [], "status": "completed"})
    return s


def _stop(s, harness, calls, warning=False, env=None) -> subprocess.CompletedProcess:
    """The agent's own transcript holds these (name, input, ok) calls; it stops."""
    home, hook, flipped, marker = harness
    prompt = f'<obligation v="1">\n{json.dumps(s.obligation, indent=2)}\n</obligation>'
    base._write_obligation_transcript(s.home, s.project, s.harness, s.agent_id, prompt, calls)
    proc = base._run_hook(s.project, s.home, s.agent_id, session_id=s.harness, stopgate_mode="block",
                          hook_path=flipped if warning else hook,
                          extra_env={"PYTHONDONTWRITEBYTECODE": "1", **(env or {})})
    fresh = subprocess.run(["find", str(home), "-name", "__pycache__", "-newer", str(marker)],
                           capture_output=True, text=True, check=True).stdout
    assert fresh == "", fresh
    return proc


def _write(path, text: str) -> tuple:
    """The file as the agent's Write left it, and that Write's call."""
    assert not path.resolve().is_relative_to(base.REPO_ROOT)  # the scratch tree, never the repository
    base._write(path, text)
    return ("Write", {"file_path": str(path), "content": text}, True)


def _compiled(path) -> str:
    try:
        compile(path.read_bytes(), str(path), "exec")
    except SyntaxError as exc:
        return str(exc)
    raise AssertionError(f"{path} compiles")


def _warned(proc, path, message: str) -> None:
    assert proc.returncode == 0, proc.stderr
    assert f"{WARN}: {path}: {message}\n" in proc.stderr, proc.stderr
    assert "harness_syntax_error" not in proc.stderr, proc.stderr


def _blocked(proc, path, message: str) -> None:
    assert proc.returncode == 2, proc.stderr
    assert WARN not in proc.stderr, proc.stderr
    assert f"  - {path}: harness_syntax_error\n    {message}\n" in proc.stderr, proc.stderr


def _unchecked(proc) -> None:
    assert proc.returncode == 0, proc.stderr
    assert "F3.a" not in proc.stderr and "harness_syntax_error" not in proc.stderr, proc.stderr


def test_dev_broken_python_hook_warns_then_blocks_with_the_compiler_message(tmp_path, harness):
    s, x = _agent(tmp_path, "dev"), harness[0] / "hooks" / "x.py"
    calls = [_write(x, BROKEN_PY)]
    message = _compiled(x)
    assert "(x.py, line 1)" in message
    _blocked(_stop(s, harness, calls), x, message)
    _warned(_stop(s, harness, calls, warning=True), x, message)


def test_dev_unclosed_if_in_a_harness_script_warns_then_blocks_with_bash_n_message(tmp_path, harness):
    s, x = _agent(tmp_path, "dev"), harness[0] / "scripts" / "x.sh"
    calls = [_write(x, BROKEN_SH)]
    proc = _stop(s, harness, calls)
    message = proc.stderr.split(f"  - {x}: harness_syntax_error\n    ", 1)[-1].split("\n", 1)[0]
    assert re.match(r"x\.sh: line \d+: syntax error", message), proc.stderr
    _blocked(proc, x, message)
    _warned(_stop(s, harness, calls, warning=True), x, message)


def test_extensionless_files_are_parsed_by_their_shebang_interpreter(tmp_path, harness):
    """scripts/bootstrap, scripts/install/land, render-settings and the git hooks
    carry no extension: a bash or python shebang picks the parser; a file with
    neither is not checked."""
    home, s = harness[0], _agent(tmp_path, "dev")
    tool, render, notes = home / "scripts" / "tool", home / "hooks" / "render", home / "scripts" / "notes"
    calls = [_write(tool, BROKEN_SH), _write(render, "#!/usr/bin/env python3\n" + BROKEN_PY),
             _write(notes, BROKEN_PY)]
    for warning in (False, True):
        proc = _stop(s, harness, calls, warning)
        assert proc.returncode == (0 if warning else 2), proc.stderr
        assert _compiled(render) in proc.stderr and re.search(r"tool: line \d+: syntax error", proc.stderr)
        assert str(notes) not in proc.stderr, proc.stderr


def test_product_repository_and_a_harness_copy_outside_the_home_are_not_checked(tmp_path, harness):
    """A product repository's hooks/ and a harness tree outside the live home (no
    git worktree), even named by CLAUDE_HOME, whose realpath is not the walk's."""
    s, copy = _agent(tmp_path, "dev"), tmp_path / "harness-copy"
    for sub in ("hooks", "policies", "scripts"):
        (copy / sub).mkdir(parents=True)
    (copy / "settings.json").write_text("{}\n", encoding="utf-8")
    calls = [_write(s.project / "hooks" / "x.py", BROKEN_PY), _write(copy / "hooks" / "x.py", BROKEN_PY),
             _write(copy / "scripts" / "x.sh", BROKEN_SH)]
    for warning in (False, True):
        _unchecked(_stop(s, harness, calls, warning, env={"CLAUDE_HOME": str(copy)}))


def test_fixed_gone_or_refused_before_the_stop_is_clean(tmp_path, harness):
    """Fixed by a later Edit, deleted by Bash before the stop, or a Write the
    policy refused (in no written set) although a broken file sits there; a
    script `bash -n` only warns about (exit 0) parses."""
    home, s = harness[0], _agent(tmp_path, "dev")
    fixed, gone, refused = (home / "hooks" / f"{n}.py" for n in ("fixed", "gone", "refused"))
    calls = [_write(fixed, BROKEN_PY), ("Edit", {"file_path": str(fixed), "old_string": "(:", "new_string": "():"},
                                        True),
             _write(gone, BROKEN_PY), ("Bash", {"command": f"rm {gone}"}, True),
             ("Write", {"file_path": str(refused), "content": BROKEN_PY}, False),
             _write(home / "scripts" / "heredoc.sh", "cat <<EOF\nunterminated here-document\n")]
    base._write(fixed, BROKEN_PY.replace("(:", "():"))
    gone.unlink()
    base._write(refused, BROKEN_PY)
    for warning in (False, True):
        _unchecked(_stop(s, harness, calls, warning))


def test_test_writer_broken_write_its_policy_admits_is_checked_as_dev(tmp_path, harness):
    s = _agent(tmp_path, "test-writer")
    x = harness[0] / "hooks" / "tests" / "generated" / "20261012-000000" / "test_x.py"
    calls = [_write(x, BROKEN_PY)]
    message = _compiled(x)
    _blocked(_stop(s, harness, calls), x, message)
    _warned(_stop(s, harness, calls, warning=True), x, message)


def test_five_changed_hook_files_take_the_predicate_under_a_second(tmp_path, harness):
    """The five largest hooks, rewritten by one dev: the predicate alone, timed
    in a fresh interpreter loading the hook from the harness home."""
    home, hook, _, marker = harness
    calls = []
    for name in ("pretool-bash-safety.sh", "pretool-overnight-hook-guard.py", "prompt-workflow.py",
                 "pretool-git-privilege-guard.py", "pretool-grep-backtrack-guard.py"):
        target = home / "hooks" / f"f3a-{name}"
        shutil.copy(base.REPO_ROOT / "hooks" / name, target)
        calls.append(("Write", {"file_path": str(target), "content": "..."}, True))
    transcript = tmp_path / "agent.jsonl"
    transcript.write_text("".join(json.dumps(r) + "\n" for r in base._tool_records(tmp_path, calls)),
                          encoding="utf-8")
    timed = ("import importlib.util, sys, time, types\n"
             "spec = importlib.util.spec_from_file_location('g2', sys.argv[1])\n"
             "g2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(g2)\n"
             "start = time.perf_counter()\n"
             "found = g2._harness_syntax(types.SimpleNamespace(transcript_path=sys.argv[2]))\n"
             "print(time.perf_counter() - start, len(found))\n")
    proc = subprocess.run([sys.executable, "-B", "-c", timed, str(hook), str(transcript)],
                          capture_output=True, text=True, check=True)
    elapsed, found = proc.stdout.split()
    print(f"F3.a predicate on 5 changed hook files: {float(elapsed):.3f} s")
    assert found == "0" and proc.stderr == "", proc.stderr
    assert float(elapsed) < 1.0
    assert subprocess.run(["find", str(home), "-name", "__pycache__", "-newer", str(marker)],
                          capture_output=True, text=True, check=True).stdout == ""
