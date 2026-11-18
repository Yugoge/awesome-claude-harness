"""The grep backtrack probe tells a scope that never started from one that started and exploded.

The probe runs inside a transient systemd scope. A launch delay of systemd-run
itself (the scope never came up before the guard's outer margin ran out) is an
infrastructure failure and lets the command through. A probe that came up
inside its scope (it writes a start marker there before the engine runs) and
then ran out of time or memory, or hung, is still refused.

No test here uses real systemd: a fake `systemd-run` on PATH (or a simulated
`subprocess.run`) stands in for it, and a fake engine binary stands in for the
embedded grep engine.
"""

import importlib.util
import io
import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "hooks/pretool-grep-backtrack-guard.py"
SPEC = importlib.util.spec_from_file_location("grep_backtrack_guard_l44", PATH)
GUARD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(GUARD)

# The real launcher, kept before any test replaces subprocess.run.
_REAL_RUN = subprocess.run

# The search from the audit (search-08): it has the flagged shape, so it is probed.
DEF_SEARCH = r"grep -rnE 'def .*\(.*\):' src"
# The simulated systemd-run launch delay, in seconds.
LAUNCH_DELAY = 11

_FAKE_SYSTEMD_RUN = textwrap.dedent("""\
    #!/usr/bin/env python3
    # Stand-in for systemd-run --scope: skip its options, wait, exec the command.
    import os, sys, time
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] in ("-p", "--slice", "--unit"):
            i += 2
        elif args[i].startswith("-"):
            i += 1
        else:
            break
    time.sleep(float(os.environ.get("FAKE_SYSTEMD_RUN_DELAY", "0")))
    os.execvp(args[i], args[i:])
    """)

_ENGINES = {
    "fast": "#!/bin/bash\nexit 1\n",
    "hang": "#!/bin/bash\nexec sleep 4\n",
    "oom": "#!/bin/bash\nexit 137\n",  # the scope's SIGKILL exit status
}


def _decide(monkeypatch, command):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    monkeypatch.setattr(GUARD.sys, "stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc:
        GUARD.main()
    return exc.value.code


@pytest.fixture
def probe_root(tmp_path, monkeypatch):
    """A private temp dir for the probe's own directories."""
    root = tmp_path / "probes"
    root.mkdir()
    monkeypatch.setattr(GUARD.tempfile, "tempdir", str(root))
    return root


def _fake_tools(tmp_path, monkeypatch, engine, delay=0, wall=1, outer=3):
    """Put a fake systemd-run first on PATH and point the guard at a fake engine."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    sd = bindir / "systemd-run"
    sd.write_text(_FAKE_SYSTEMD_RUN)
    sd.chmod(0o755)
    eng = bindir / "engine"
    eng.write_text(_ENGINES[engine])
    eng.chmod(0o755)
    monkeypatch.setenv("PATH", "{}{}{}".format(bindir, os.pathsep, os.environ.get("PATH", "")))
    monkeypatch.setenv("CLAUDE_CODE_EXECPATH", str(eng))
    monkeypatch.setenv("FAKE_SYSTEMD_RUN_DELAY", str(delay))
    monkeypatch.setattr(GUARD, "PROBE_WALL_SECS", wall)
    monkeypatch.setattr(GUARD, "PROBE_OUTER_SECS", outer)


def _scope_command(argv):
    """The part of the systemd-run argv that runs inside the scope, after `timeout N`."""
    i = argv.index("timeout")
    return argv[i + 2:]


def _simulate(monkeypatch, tmp_path, *, start, then):
    """Replace the probe launch with a deterministic simulation.

    start: run the in-scope command for real before `then` happens (the scope
           came up), or not at all (the launch was still delayed).
    then:  "outer-timeout" -> the guard's outer margin runs out after
           LAUNCH_DELAY seconds; an int -> the probe exits with that code.
    """
    eng = tmp_path / "engine"
    eng.write_text(_ENGINES["fast"])
    eng.chmod(0o755)
    monkeypatch.setenv("CLAUDE_CODE_EXECPATH", str(eng))
    monkeypatch.setattr(GUARD.os.path, "exists",
                        lambda p, _real=os.path.exists: True if p == "/usr/bin/systemd-run" else _real(p))
    calls = []

    def fake_run(argv, timeout=None, **kwargs):
        calls.append(argv)
        if start:
            _REAL_RUN(_scope_command(argv), stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, check=False)
            if callable(start):
                start()
        if then == "outer-timeout":
            assert timeout is not None and LAUNCH_DELAY > timeout
            raise subprocess.TimeoutExpired(argv, timeout)
        return subprocess.CompletedProcess(argv, then)

    monkeypatch.setattr(GUARD.subprocess, "run", fake_run)
    return calls


# --- the allow this lane adds (red on the base, green after the fix) ---------

def test_a_launch_delayed_eleven_seconds_never_started_and_is_let_through(monkeypatch, tmp_path, probe_root):
    calls = _simulate(monkeypatch, tmp_path, start=False, then="outer-timeout")
    assert _decide(monkeypatch, DEF_SEARCH) == 0
    assert len(calls) == 1  # the pattern really was probed


def test_a_delayed_fake_systemd_run_is_let_through(monkeypatch, tmp_path, probe_root):
    # The fake systemd-run sleeps past the outer margin before it execs the scope.
    _fake_tools(tmp_path, monkeypatch, "hang", delay=LAUNCH_DELAY, wall=1, outer=2)
    assert _decide(monkeypatch, DEF_SEARCH) == 0


# --- what stays refused ------------------------------------------------------

@pytest.mark.parametrize("engine, rc", (("hang", 124), ("oom", 137)))
def test_a_probe_that_started_and_was_killed_is_refused(monkeypatch, tmp_path, probe_root, engine, rc):
    _fake_tools(tmp_path, monkeypatch, engine, wall=1, outer=6)
    assert _decide(monkeypatch, DEF_SEARCH) == 2


@pytest.mark.parametrize("rc", (124, 137))
def test_a_kill_code_is_refused_whatever_the_marker_says(monkeypatch, tmp_path, probe_root, rc):
    # The kill codes come from inside the scope; they refuse with no marker too,
    # so removing or spoiling a marker cannot turn an explosion into an allow.
    _simulate(monkeypatch, tmp_path, start=False, then=rc)
    assert _decide(monkeypatch, DEF_SEARCH) == 2


def test_a_probe_that_started_in_scope_then_hung_is_refused(monkeypatch, tmp_path, probe_root):
    # Started, then throttled (e.g. MemoryHigh) past the outer margin.
    _simulate(monkeypatch, tmp_path, start=True, then="outer-timeout")
    assert _decide(monkeypatch, DEF_SEARCH) == 2


def test_a_fake_probe_that_started_then_hung_past_the_outer_margin_is_refused(monkeypatch, tmp_path, probe_root):
    # The wall limit is longer than the outer margin, so the probe is still
    # running inside its scope when the guard's outer margin runs out.
    _fake_tools(tmp_path, monkeypatch, "hang", wall=30, outer=1)
    assert _decide(monkeypatch, DEF_SEARCH) == 2


def _overwrite_markers(root, how):
    for d in root.glob("grepguard-probe-*"):
        for f in d.iterdir():
            if f.name == "dense.txt":
                continue
            f.unlink()
            if how == "garbage":
                f.write_text("never-started\n")
            elif how == "symlink":
                f.symlink_to("/nonexistent")


@pytest.mark.parametrize("how", ("garbage", "symlink"))
def test_a_forged_marker_cannot_turn_a_started_probe_into_an_allow(monkeypatch, tmp_path, probe_root, how):
    _simulate(monkeypatch, tmp_path, start=lambda: _overwrite_markers(probe_root, how),
              then="outer-timeout")
    assert _decide(monkeypatch, DEF_SEARCH) == 2


def test_a_marker_outside_the_probes_own_directory_does_not_count(monkeypatch, tmp_path, probe_root):
    # A planted or stale marker in a neighbouring probe-looking directory is not
    # this probe's: a real explosion is still refused, a launch that never came
    # up is still let through.
    stale = probe_root / "grepguard-probe-stale"
    stale.mkdir()
    (stale / "started").write_text("started\n")
    _simulate(monkeypatch, tmp_path, start=False, then=124)
    assert _decide(monkeypatch, DEF_SEARCH) == 2
    _simulate(monkeypatch, tmp_path, start=False, then="outer-timeout")
    assert _decide(monkeypatch, DEF_SEARCH) == 0


def test_a_previous_probes_marker_cannot_leak_into_the_next_run(monkeypatch, tmp_path, probe_root):
    _simulate(monkeypatch, tmp_path, start=True, then=1)
    assert _decide(monkeypatch, DEF_SEARCH) == 0
    # The probe leaves nothing behind for the next run to read.
    assert list(probe_root.iterdir()) == []
    _simulate(monkeypatch, tmp_path, start=False, then="outer-timeout")
    assert _decide(monkeypatch, DEF_SEARCH) == 0
    assert list(probe_root.iterdir()) == []


def test_a_marker_that_cannot_be_written_keeps_the_engine_from_running(monkeypatch, tmp_path, probe_root):
    # The scope writes its marker before it runs the engine, and stops (125, a
    # launch failure that fails open) when it cannot: the engine never runs
    # without a marker, so no explosion can happen unmarked.
    witness = tmp_path / "engine-ran"
    eng = tmp_path / "witness-engine"
    eng.write_text("#!/bin/bash\ntouch {}\nexit 1\n".format(witness))
    eng.chmod(0o755)
    monkeypatch.setenv("CLAUDE_CODE_EXECPATH", str(eng))
    monkeypatch.setattr(GUARD.os.path, "exists",
                        lambda p, _real=os.path.exists: True if p == "/usr/bin/systemd-run" else _real(p))
    codes = []

    def fake_run(argv, timeout=None, **kwargs):
        for d in probe_root.glob("grepguard-probe-*"):
            for name in ("started",):
                (d / name).mkdir()  # the marker path cannot be written as a file
        cp = _REAL_RUN(_scope_command(argv), stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
        codes.append(cp.returncode)
        return cp

    monkeypatch.setattr(GUARD.subprocess, "run", fake_run)
    assert _decide(monkeypatch, DEF_SEARCH) == 0
    assert codes == [125]
    assert not witness.exists()
