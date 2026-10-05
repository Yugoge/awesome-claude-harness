"""Tests for hooks/sessionstart-artifact-census.py (lane L12 / AC1-AC10).

Every run is a subprocess against throwaway directories; the real restart
state and project history are never touched.
"""

import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "sessionstart-artifact-census.py"
RESOLVER = HOOK.parent.parent / "scripts" / "resolve-dev-artifact-chain.py"

STUB_SRC = """\
import json, os, sys, time
log = os.environ.get("STUB_LOG")
if log:
    open(log, "a").write(" ".join(sys.argv[1:]) + "\\n")
time.sleep(float(os.environ.get("STUB_SLEEP", "0")))
mode = os.environ.get("STUB_MODE", "pass")
if mode == "garbage":
    sys.stdout.write("not json"); sys.exit(2)
if mode == "gap":
    print(json.dumps({"status": "fail", "errors": [{"code": "MISSING_ARTIFACT"}]})); sys.exit(2)
print(json.dumps({"status": "pass", "errors": []}))
"""


class Env:
    def __init__(self, tmp_path, **extra):
        self.root = tmp_path
        self.project = tmp_path / "proj"
        self.dev = self.project / "docs" / "dev"
        self.dev.mkdir(parents=True)
        self.census = tmp_path / "census"
        self.state = tmp_path / "restart-state"
        self.state.mkdir()
        self.stub = tmp_path / "stub.py"
        self.stub.write_text(STUB_SRC)
        self.log = tmp_path / "stub.log"
        self.ctl = tmp_path / "ctl"
        self.env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(tmp_path / "home"),
            "CLAUDE_PROJECT_DIR": str(self.project),
            "CLAUDE_ARTIFACT_CENSUS_DIR": str(self.census),
            "CLAUDE_RESTART_STATE_DIR": str(self.state),
            "CONTROL_ROOT": str(self.ctl),
            "CLAUDE_CENSUS_TEST_MODE": "1",
            "CLAUDE_CENSUS_RESOLVER_CMD": f"{shlex.quote(sys.executable)} {shlex.quote(str(self.stub))}",
            "STUB_LOG": str(self.log),
        }
        self.env.update(extra)

    def report(self, tid, age_days=0):
        p = self.dev / f"dev-report-{tid}.json"
        p.write_text("{}")
        if age_days:
            t = time.time() - age_days * 86400
            os.utime(p, (t, t))
        return p

    def close(self, tid):
        (self.dev / f"close-report-{tid}.md").write_text("closed")

    def run(self, **env_over):
        env = dict(self.env)
        env.update(env_over)
        return subprocess.run(
            [sys.executable, str(HOOK)], input='{"session_id":"s-test"}',
            capture_output=True, text=True, env=env, timeout=60,
        )

    def record(self, tid):
        return json.loads((self.census / f"{tid}.json").read_text())


def ctx(cp):
    assert cp.returncode == 0, cp.stderr
    return json.loads(cp.stdout)["hookSpecificOutput"]["additionalContext"]


def listed_ids(text):
    m = re.search(r"^chains: (.*)$", text, re.M)
    return [s.strip() for s in m.group(1).split(",")] if m else []


def test_AC1(tmp_path):
    e = Env(tmp_path)
    e.report("T-1")
    cp = e.run()
    assert "T-1" in listed_ids(ctx(cp))
    assert e.record("T-1")["task_id"] == "T-1"


def test_AC2(tmp_path):
    e = Env(tmp_path)
    e.report("T-2"); e.close("T-2")
    e.report("U-2")
    e.report("V-2"); e.report("V-2-l1"); e.report("V-2-l2")
    ids = listed_ids(ctx(e.run()))
    assert "U-2" in ids and "T-2" not in ids
    assert ids.count("V-2") == 1 and "V-2-l1" not in ids and "V-2-l2" not in ids


def test_AC3(tmp_path):
    e = Env(tmp_path)
    e.report("A-3"); e.report("B-3")
    ctx(e.run())
    calls = e.log.read_text().splitlines()
    for tid in ("A-3", "B-3"):
        assert any(f"--task-id {tid}" in c for c in calls)
    # source comparator: only the two gap codes may be named
    src = HOOK.read_text()
    codes = set(re.findall(r'error\("([A-Z_]+)"', RESOLVER.read_text()))
    codes |= set(re.findall(r'"code": "([A-Z_]+)"', RESOLVER.read_text()))
    assert codes
    named = {c for c in codes if re.search(rf"\b{c}\b", src)}
    assert named <= {"MISSING_ARTIFACT", "EMPTY_ARTIFACT"}
    # stub ignored without test mode (real resolver runs instead, stub log untouched)
    e.log.unlink()
    env = dict(e.env); env.pop("CLAUDE_CENSUS_TEST_MODE")
    subprocess.run([sys.executable, str(HOOK)], input="{}", capture_output=True,
                   text=True, env=env, timeout=60)
    assert not e.log.exists()


def test_AC4(tmp_path):
    e = Env(tmp_path)
    e.report("T-4")
    before = sorted(p.name for p in e.dev.iterdir())
    e.run()
    first = e.record("T-4")
    assert sorted(p.name for p in e.dev.iterdir()) == before
    time.sleep(0.02)
    e.run()
    second = e.record("T-4")
    assert second["first_seen"] == first["first_seen"]
    assert second["last_seen"] != first["last_seen"]
    # default location under restart state
    env = dict(e.env); env.pop("CLAUDE_ARTIFACT_CENSUS_DIR")
    subprocess.run([sys.executable, str(HOOK)], input="{}", capture_output=True,
                   text=True, env=env, timeout=60)
    assert (e.state / "artifact-census" / "T-4.json").is_file()


def test_AC5(tmp_path):
    e = Env(tmp_path)
    e.report("T-5")
    shim = tmp_path / "shim"
    shim.mkdir()
    trip = tmp_path / "tripped"
    for name in ("claude", "git", "close", "commit", "restart"):
        f = shim / name
        f.write_text(f"#!/bin/sh\necho {name} >> {trip}\nexit 1\n")
        f.chmod(0o755)
    (e.state / "grants").mkdir()
    (e.state / "sess-1.json").write_text(json.dumps({
        "parent_session_id": "sess-1",
        "candidates": [{"agent_id": "a1", "parent_session_id": "sess-1", "status": "pending"},
                       {"agent_id": "a2", "status": "response_observed"}]}))
    path = f"{shim}{os.pathsep}{e.env['PATH']}"
    text = ctx(e.run(PATH=path))
    assert not trip.exists()
    assert "1 interrupted agent(s) await restart" in text
    assert "human-only restart" in e.record("T-5")["next_action"]
    # next_action unchanged by restart state
    base = Env(tmp_path / "b")  if (tmp_path / "b").mkdir() is None else None
    base.report("T-5")
    base.run()
    assert base.record("T-5")["next_action"] == e.record("T-5")["next_action"]


def test_AC6(tmp_path):
    e = Env(tmp_path, STUB_MODE="garbage")
    e.report("T-6")
    cp = e.run()
    assert "T-6" in listed_ids(ctx(cp))
    assert e.record("T-6")["resolver_status"] == "resolver_error"
    # unreadable docs/dev (a file where the directory should be)
    f = Env(tmp_path / "f") if (tmp_path / "f").mkdir() is None else None
    (f.project / "docs" / "dev").rmdir()
    (f.project / "docs" / "dev").write_text("x")
    cp = f.run()
    assert cp.returncode == 0
    assert "NotADirectoryError" in cp.stderr
    err = json.loads((f.census / "census-error.json").read_text())
    assert err["exception_class"] == "NotADirectoryError"
    # unwritable census dir: stderr still names the class
    g = Env(tmp_path / "g") if (tmp_path / "g").mkdir() is None else None
    g.report("T-6g")
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    cp = g.run(CLAUDE_ARTIFACT_CENSUS_DIR=str(blocker / "sub"))
    assert cp.returncode == 0
    assert "artifact census FAILED" in cp.stderr and "Error" in cp.stderr
    if cp.stdout:
        json.loads(cp.stdout)


def test_AC7(tmp_path):
    e = Env(tmp_path)
    target = e.dev / "dev-report-K-7.json"
    child = subprocess.Popen([sys.executable, "-c",
        f"import time; open({str(target)!r},'w').write('{{}}'); time.sleep(60)"])
    try:
        for _ in range(100):
            if target.exists() and target.stat().st_size:
                break
            time.sleep(0.05)
        child.send_signal(signal.SIGKILL)
        child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
    reports = {p.name[len("dev-report-"):-5] for p in e.dev.glob("dev-report-*.json")}
    closes = {p.name[len("close-report-"):-3] for p in e.dev.glob("close-report-*.md")}
    expected = reports - closes
    assert expected == {"K-7"}
    assert "K-7" in listed_ids(ctx(e.run(CLAUDE_SESSION_ID="fresh-1")))
    assert (e.census / "K-7.json").is_file()
    e.close("K-7")
    cp = e.run(CLAUDE_SESSION_ID="fresh-2")
    assert cp.returncode == 0 and cp.stdout == ""
    assert e.record("K-7")["resolver_status"] == "closed"


def test_AC8(tmp_path):
    e = Env(tmp_path)
    cp = e.run()
    assert cp.returncode == 0 and cp.stdout == "" and not e.census.exists()
    ids = [f"C-8-{i:02d}" for i in range(12)]
    for i, tid in enumerate(ids):
        p = e.report(tid)
        t = time.time() - i
        os.utime(p, (t, t))
    cp = e.run(CLAUDE_CENSUS_MAX_CHAINS="3", CLAUDE_CENSUS_NOTICE_CHARS="600")
    text = ctx(cp)
    assert len(text) <= 600
    assert "omitted_for_cap=9" in text
    for tid in ids:
        assert (e.census / f"{tid}.json").is_file()


def test_AC9(tmp_path):
    e = Env(tmp_path)
    e.report("NEW-9")
    e.report("OLD-9", age_days=60)
    text = ctx(e.run())
    assert e.record("OLD-9")["in_notice_window"] is False
    assert "OLD-9" not in listed_ids(text) and "NEW-9" in listed_ids(text)
    assert "omitted_for_age=1" in text
    assert f"queue_dir={e.census}" in text


def test_AC10(tmp_path):
    e = Env(tmp_path, STUB_SLEEP="2", CLAUDE_CENSUS_TOTAL_BUDGET_SECONDS="1",
            CLAUDE_CENSUS_RESOLVER_TIMEOUT="5")
    ids = ["P-10-a", "P-10-b", "P-10-c"]
    for tid in ids:
        e.report(tid)
    t0 = time.monotonic()
    cp = e.run()
    assert time.monotonic() - t0 < 1 + 5
    text = ctx(cp)
    recs = [e.record(t) for t in ids]
    assert all(r["task_id"] for r in recs)
    pending = [r for r in recs if r["resolver_status"] == "resolver_pending"]
    assert len(pending) >= 1
    assert f"resolver_pending={len(pending)}" in text
    default = re.search(r'"CLAUDE_CENSUS_TOTAL_BUDGET_SECONDS", (\d+)', HOOK.read_text())
    assert default and int(default.group(1)) < 30
