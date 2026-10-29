"""The overnight boundary leaves the whole dev-registry read-only, qa.json included.

P1b E7 removed the one RW exception the boundary had under main's
.claude/dev-registry: the orchestrator flipped qa.json's `qa_mode` between QA
dispatches, so `_qa_mode_sentinel_rw_bind` bound that ONE file RW. Each QA
dispatch's obligation now declares the report it owes and the stop gates read
that record, so nothing writes qa.json mid-session and the bind went with the
flips. These tests pin what replaces it: no actor (orchestrator or subagent)
gets a writable sentinel, flag or session directory, so no write can disarm a
stop gate (subagentstop-e2e-enforce.py fails OPEN on an absent flag).

MEASURED TRAP (do not undo): every lab here is built under /var/tmp, NOT /tmp.
The boundary mounts its own `--tmpfs /tmp`, which shadows a lab placed there and
fabricates a false read-only result. (The same trap is documented in
test_overnight_gitenv_failclosed.py, which parks its labs under /dev/shm.)
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
# Overridable so the fail-first measurement can be re-run against a neutralized
# (pre-fix) copy of the guard on demand, with no other input changed. Same seam
# and same reason as OVERNIGHT_LAUNCHER_UNDER_TEST in the gitenv suite: a test
# that passes both before and after the fix proves nothing.
GUARD_PATH = Path(os.environ.get("OVERNIGHT_GUARD_UNDER_TEST")
                  or REPO / "hooks" / "pretool-overnight-hook-guard.py")
# A caller-owned lab base, used as it is; unset, each run makes its own (lab_base).
LAB_BASE_OVERRIDE = os.environ.get("OVERNIGHT_QA_SENTINEL_LAB_BASE")
SID = "dev-sentinel-test"

ORCHESTRATOR_PAYLOAD = {"session_id": SID}
SUBAGENT_PAYLOAD = {"session_id": "other-session", "agent_id": "a-child-0001"}


def _load_guard():
    spec = importlib.util.spec_from_file_location("overnight_guard_uut", GUARD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load_guard()


@pytest.fixture(scope="module")
def lab_base():
    """A fresh per-run base under /var/tmp (see MEASURED TRAP), removed after the
    module: no fixed shared /var/tmp path is left behind, or collides with a run as
    another user. OVERNIGHT_QA_SENTINEL_LAB_BASE, when set, is used as it is."""
    if LAB_BASE_OVERRIDE:
        yield Path(LAB_BASE_OVERRIDE)
        return
    base = Path(tempfile.mkdtemp(prefix="claude-qa-sentinel-bind-labs-", dir="/var/tmp"))
    yield base
    shutil.rmtree(base, ignore_errors=True)


@pytest.fixture
def lab(request, lab_base):
    """main/ + clone/ + a populated dev-registry session dir, under /var/tmp."""
    root = lab_base / uuid.uuid4().hex[:12]
    main = root / "main"
    wt = root / "clone"
    sess = main / ".claude" / "dev-registry" / SID
    sess.mkdir(parents=True)
    wt.mkdir(parents=True)
    (sess / "qa.json").write_text(json.dumps(
        {"agent_type": "qa", "session_id": SID, "qa_mode": "final_verification"}))
    (sess / "e2e-enforce.json").write_text(json.dumps({"e2e_required": True}))
    (sess / "codex-enforce.json").write_text(json.dumps({"codex_required": True}))
    request.addfinalizer(lambda: shutil.rmtree(root, ignore_errors=True))
    return {"root": root, "main": main, "wt": wt, "sess": sess,
            "qa": sess / "qa.json"}


@pytest.fixture(autouse=True)
def _clean_ctx():
    """Never let one test's actor context leak into the next."""
    yield
    G._set_request_ctx({}, {})


@pytest.fixture
def standin_bwrap(monkeypatch):
    """A stand-in bwrap path for tests that BUILD the argv but never exec it.

    `_build_bwrap_argv` returns None only when `_resolve_bwrap` finds no
    binary; the argv shape under test does not depend on one existing, so
    these tests run on hosts without bubblewrap (CI). Exec-ing tests keep
    `requires_bwrap` instead."""
    path = "/standin/bin/bwrap"
    monkeypatch.setattr(G, "_resolve_bwrap", lambda: path)
    return path


def _as(payload: dict) -> None:
    G._set_request_ctx({}, payload)


def _rw_sources(argv: list[str]) -> list[str]:
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "--bind"]


# --------------------------------------------------------------------------- #
# No RW exception under the registry, for either actor
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("kind", ["registered_worktree", "fresh_clone_checkout"])
def test_build_bwrap_argv_binds_nothing_under_the_registry(lab, kind, standin_bwrap):
    """Same input, both actors, through the real argv builder."""
    registry = str(lab["main"] / ".claude" / "dev-registry")
    for payload in (ORCHESTRATOR_PAYLOAD, SUBAGENT_PAYLOAD):
        _as(payload)
        argv = G._build_bwrap_argv("true", str(lab["main"]), str(lab["wt"]), kind)
        assert argv is not None
        assert not [src for src in _rw_sources(argv) if src.startswith(registry)], argv


def test_session_dir_never_appears_as_a_bind_source(lab, standin_bwrap):
    _as(ORCHESTRATOR_PAYLOAD)
    argv = G._build_bwrap_argv("true", str(lab["main"]), str(lab["wt"]),
                               "fresh_clone_checkout")
    sess = str(lab["sess"])
    assert sess not in _rw_sources(argv), "a directory bind re-ships the sibling-flag bypass"


# --------------------------------------------------------------------------- #
# END-TO-END through the real boundary (the measurement, not a proxy)
# --------------------------------------------------------------------------- #
def _bwrap_ready() -> bool:
    return bool(shutil.which("bwrap")) and G._userns_available()


requires_bwrap = pytest.mark.skipif(
    not _bwrap_ready(), reason="bubblewrap / user namespace unavailable")


def _write_state(lab_, kind: str) -> None:
    state = {
        "session_id": SID, "schema_version": 9, "isolation_kind": kind,
        "main_root": str(lab_["main"]), "main_git_dir": str(lab_["main"] / ".git"),
        "worktree_path": str(lab_["wt"]), "dev_registry_dir": str(lab_["sess"]),
        "protected_branch": "master",
        "end_time": (datetime.now() + timedelta(hours=6)).strftime("%H:%M"),
        "isolation_active_until": (datetime.now() + timedelta(hours=6)).isoformat(),
    }
    (lab_["main"] / ".claude" / f"overnight-state-{SID}.json").write_text(
        json.dumps(state))


def _drive_hook(lab_, command: str, payload_extra: dict) -> str | None:
    """Run the REAL hook entrypoint over stdin; return the bwrap re-exec it emits."""
    payload = {"tool_name": "Bash", "tool_input": {"command": command},
               "cwd": str(lab_["wt"]), **payload_extra}
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(lab_["main"]))
    env.pop("PWD", None)
    proc = subprocess.run([sys.executable, str(GUARD_PATH)],
                          input=json.dumps(payload), capture_output=True,
                          text=True, env=env, cwd=str(lab_["wt"]))
    try:
        return json.loads(proc.stdout)["hookSpecificOutput"]["updatedInput"]["command"]
    except Exception:
        return None


def _tamper_cmd(target: Path, value: str = "ba_validation") -> str:
    return ("python3 -c \"import json,pathlib;"
            f"p=pathlib.Path('{target}');d=json.loads(p.read_text());"
            f"d['qa_mode']='{value}';p.write_text(json.dumps(d))\"")


def _qa_mode(lab_) -> str:
    return json.loads(lab_["qa"].read_text())["qa_mode"]


@requires_bwrap
@pytest.mark.parametrize("kind", ["registered_worktree", "fresh_clone_checkout"])
@pytest.mark.parametrize("payload", [SUBAGENT_PAYLOAD, ORCHESTRATOR_PAYLOAD], ids=["subagent", "orchestrator"])
def test_e2e_no_actor_can_rewrite_the_sentinel(lab, kind, payload):
    """End-to-end: neither actor's write reaches qa.json on the HOST."""
    _write_state(lab, kind)
    rewritten = _drive_hook(lab, _tamper_cmd(lab["qa"]), payload)
    assert rewritten, "boundary should still rewrite the command"
    proc = subprocess.run(["/bin/bash", "-c", rewritten],
                          capture_output=True, text=True)
    assert proc.returncode != 0, "the write must FAIL"
    assert "Read-only file system" in proc.stderr
    assert _qa_mode(lab) == "final_verification", "sentinel must be untouched"


@requires_bwrap
def test_e2e_sibling_enforcement_flag_stays_non_removable(lab):
    """A writable session DIRECTORY would make this pass-through;
    subagentstop-e2e-enforce.py fails OPEN on an absent flag."""
    _write_state(lab, "fresh_clone_checkout")
    flag = lab["sess"] / "e2e-enforce.json"
    for cmd in (f"python3 -c \"import os;os.unlink('{flag}')\"",
                _tamper_cmd(flag, "x")):
        rewritten = _drive_hook(lab, cmd, ORCHESTRATOR_PAYLOAD)
        assert rewritten
        proc = subprocess.run(["/bin/bash", "-c", rewritten],
                              capture_output=True, text=True)
        assert proc.returncode != 0, f"must be refused: {cmd}"
    assert flag.exists() and json.loads(flag.read_text()) == {"e2e_required": True}


@requires_bwrap
def test_e2e_new_file_in_session_dir_is_refused(lab):
    """The session directory stays RO for the orchestrator too."""
    _write_state(lab, "fresh_clone_checkout")
    newf = lab["sess"] / "planted.json"
    rewritten = _drive_hook(
        lab, f"python3 -c \"open('{newf}','w').write('{{}}')\"",
        ORCHESTRATOR_PAYLOAD)
    assert rewritten
    proc = subprocess.run(["/bin/bash", "-c", rewritten],
                          capture_output=True, text=True)
    assert proc.returncode != 0 and not newf.exists()
