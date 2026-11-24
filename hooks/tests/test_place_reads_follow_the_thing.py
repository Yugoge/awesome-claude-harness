"""Three readings that took a place by accident decide from what the thing is (g-locfind2: F8, F9, F10).

F8  The capability doctor never takes the user's home, the harness home or / as the session's project when it walks
    up from its own directory; a CLAUDE_PROJECT_DIR that names one of them is the same non-project.
F9  A TMPDIR that is a foreground dispatch's temp directory (<root>/<session>/dispatch-*) names the same session
    scratch root as the root itself: the directory belongs to the session whose .owner lies one level up.
F10 The overnight record that releases the worktree rule is the record of the project the CALL names (its own
    directory and that directory's repository top, and the CLI's project variable), not of the directory the hook
    process happens to run in.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "hooks" / "lib"
STRICT = REPO / "scripts" / "capability-doctor-strict.py"
PROBE = "import sys; sys.path.insert(0, sys.argv[1]); import locations; print(locations.session_scratch_root())"


def _strict_mod():
    sys.path.insert(0, str(REPO / "hooks"))
    spec = importlib.util.spec_from_file_location("capdoctor_strict_f8", STRICT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("which", ["user-home", "harness-home", "filesystem-root"])
def test_a_project_variable_naming_a_non_project_place_reads_as_unset(tmp_path, monkeypatch, which):
    """F8: the same call with the variable unset and set to a place that is never a project gets one answer."""
    home, harness = tmp_path / "userhome", tmp_path / "harness"
    work = home / "work"
    for d in (home, harness, work):
        d.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(work)
    mod = _strict_mod()
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    unset = mod.resolve_project(None, False, harness)
    named = {"user-home": home, "harness-home": harness, "filesystem-root": Path("/")}[which]
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(named))
    assert mod.resolve_project(None, False, harness) == unset


def test_a_project_variable_naming_a_real_project_is_still_taken(tmp_path, monkeypatch):
    home, harness, proj = tmp_path / "userhome", tmp_path / "harness", tmp_path / "proj"
    for d in (home, harness, proj):
        d.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    monkeypatch.chdir(home)
    assert _strict_mod().resolve_project(None, False, harness) == proj


@pytest.mark.parametrize("below_owner", [False, True])
def test_a_dispatch_temp_dir_names_the_same_session_root(tmp_path, below_owner):
    """F9: TMPDIR = the root, or the open dispatch's directory inside a session's directory: one root."""
    root = tmp_path / "root"
    session = root / "sid-1"
    dispatch = session / "dispatch-abc123"
    dispatch.mkdir(parents=True)
    (session / ".owner").write_text("{}")
    tmpdir = dispatch if below_owner else root
    out = subprocess.run([sys.executable, "-I", "-c", PROBE, str(LIB)], capture_output=True, text=True,
                         env={**os.environ, "TMPDIR": str(tmpdir)}, timeout=30)
    assert out.stdout.strip() == os.path.realpath(root), out.stderr


def test_a_directory_named_like_a_dispatch_without_an_owner_above_is_its_own_root(tmp_path):
    """The strip needs the session's .owner one level up: a bare dispatch-named directory is a root as any other."""
    lone = tmp_path / "root" / "plain" / "dispatch-x"
    lone.mkdir(parents=True)
    out = subprocess.run([sys.executable, "-I", "-c", PROBE, str(LIB)], capture_output=True, text=True,
                         env={**os.environ, "TMPDIR": str(lone)}, timeout=30)
    assert out.stdout.strip() == os.path.realpath(lone), out.stderr


def _live_record(project):
    (project / ".claude").mkdir(parents=True, exist_ok=True)
    (project / ".claude" / "overnight-state-s.json").write_text(json.dumps(
        {"current_phase": "exploring", "end_time": "2099-01-01T00:00:00Z", "session_id": "s"}))


@pytest.mark.parametrize("process_in", ["calls-project", "other-project"])
def test_the_overnight_record_read_is_the_one_of_the_project_the_call_names(tmp_path, monkeypatch, process_in):
    """F10: the call's project has no live record, another project has; where the hook process runs cannot matter."""
    sys.path.insert(0, str(LIB))
    import overnight
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _live_record(b)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir({"calls-project": a, "other-project": b}[process_in])
    assert overnight.is_overnight_active(str(a)) is False
    assert overnight.is_overnight_active(str(b)) is True


def test_without_a_named_project_the_process_directory_still_decides(tmp_path, monkeypatch):
    sys.path.insert(0, str(LIB))
    import overnight
    b = tmp_path / "b"
    b.mkdir()
    _live_record(b)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(b)
    assert overnight.is_overnight_active(None) is True
