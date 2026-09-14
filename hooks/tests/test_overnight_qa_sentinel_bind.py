"""Regression suite for the qa_mode-sentinel RW bind in the overnight boundary.

`_qa_mode_sentinel_rw_bind` / `_build_bwrap_argv` had ZERO test callers, so the
two failure modes this file exists to catch were both undetectable:

  ACTOR GATE (QA F1, closed here) -- the mount-layer exemption mirrored the
  string layer's `_is_harness_state_exempt` for the SAME path but WITHOUT that
  exemption's `_is_orchestrator_actor()` gate, while `_apply_write_boundary`
  also runs for `overnight_child` / `worktree_context`. A subagent therefore got
  a writable `qa.json`; `subagentstop-e2e-enforce.py` exits 0 on
  `qa_mode == "ba_validation"`, so one write disarmed the E2E stop gate. The
  string layer cannot backstop it: `_apply_write_boundary` leaves through
  `_emit_command_rewrite`'s `sys.exit(0)` before `apply_global_worktree_
  enforcement` ever runs.

  WIDENING -- if the bind is ever widened back from the FILE to its DIRECTORY,
  the sibling enforcement flags in the same session dir become writable AND
  removable, and `subagentstop-e2e-enforce.py` fails OPEN on an absent flag.
  That is the exact bypass an earlier adversarial round caught in this lane's
  own draft, and nothing in the committed suite would have caught its return.

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
LAB_BASE = Path(os.environ.get("OVERNIGHT_QA_SENTINEL_LAB_BASE")
                or "/var/tmp/claude-qa-sentinel-bind-labs")
SID = "dev-sentinel-test"

ORCHESTRATOR_PAYLOAD = {"session_id": SID}
SUBAGENT_PAYLOAD = {"session_id": "other-session", "agent_id": "a-child-0001"}


def _load_guard():
    spec = importlib.util.spec_from_file_location("overnight_guard_uut", GUARD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load_guard()


@pytest.fixture
def lab(request):
    """main/ + clone/ + a populated dev-registry session dir, under /var/tmp."""
    root = LAB_BASE / uuid.uuid4().hex[:12]
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


def _as(payload: dict) -> None:
    G._set_request_ctx({}, payload)


def _bind(lab_, payload: dict, wt_real: str = "") -> list[str]:
    _as(payload)
    return G._qa_mode_sentinel_rw_bind(str(lab_["main"]), wt_real, str(lab_["sess"]))


# --------------------------------------------------------------------------- #
# ACTOR GATE -- the F1 regression
# --------------------------------------------------------------------------- #
def test_orchestrator_gets_the_file_bind(lab):
    assert _bind(lab, ORCHESTRATOR_PAYLOAD) == [
        "--bind", str(lab["qa"]), str(lab["qa"])]


def test_subagent_gets_no_bind(lab):
    """The F1 gap: an ungated bind hands a subagent a writable qa_mode.

    Calls the helper DIRECTLY, bypassing _build_bwrap_argv, so this also pins
    the gate INSIDE the helper: a gate placed at the call site instead would
    leave this refusal to a future call site to remember."""
    assert _bind(lab, SUBAGENT_PAYLOAD) == []


@pytest.mark.parametrize("kind", ["registered_worktree", "fresh_clone_checkout"])
def test_build_bwrap_argv_emits_bind_only_for_orchestrator(lab, kind):
    """Same input, both actors, through the real argv builder."""
    pair = f"--bind {lab['qa']} {lab['qa']}"

    _as(ORCHESTRATOR_PAYLOAD)
    orch = G._build_bwrap_argv("true", str(lab["main"]), str(lab["wt"]), kind,
                               str(lab["sess"]))
    _as(SUBAGENT_PAYLOAD)
    sub = G._build_bwrap_argv("true", str(lab["main"]), str(lab["wt"]), kind,
                              str(lab["sess"]))

    assert orch is not None and sub is not None
    assert pair in " ".join(orch)
    assert pair not in " ".join(sub)


# --------------------------------------------------------------------------- #
# WIDENING -- the bind must stay FILE-scoped, never directory-scoped
# --------------------------------------------------------------------------- #
def test_bind_target_is_the_file_never_its_directory(lab):
    args = _bind(lab, ORCHESTRATOR_PAYLOAD)
    assert args[0] == "--bind"
    for target in args[1:]:
        assert Path(target).is_file(), f"bind target must be a FILE, got {target}"
        assert Path(target).name == "qa.json"
        assert target != str(lab["sess"]), "session DIRECTORY must never be bound"


def test_session_dir_never_appears_as_a_bind_source(lab):
    _as(ORCHESTRATOR_PAYLOAD)
    argv = G._build_bwrap_argv("true", str(lab["main"]), str(lab["wt"]),
                               "fresh_clone_checkout", str(lab["sess"]))
    sess = str(lab["sess"])
    rw_sources = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "--bind"]
    assert sess not in rw_sources, "a directory bind re-ships the sibling-flag bypass"


# --------------------------------------------------------------------------- #
# PATH DEFENCES that must keep rejecting (no bind -> the write fails loudly)
# --------------------------------------------------------------------------- #
def test_symlinked_sentinel_is_refused(lab):
    lab["qa"].unlink()
    lab["qa"].symlink_to("/etc/hostname")
    assert _bind(lab, ORCHESTRATOR_PAYLOAD) == []


def test_multiply_linked_sentinel_is_refused(lab):
    """st_nlink != 1 stops a planted hardlink aliasing a main-tree inode."""
    os.link(lab["qa"], lab["sess"] / "alias.json")
    assert _bind(lab, ORCHESTRATOR_PAYLOAD) == []


def test_registry_root_itself_is_refused(lab):
    _as(ORCHESTRATOR_PAYLOAD)
    reg_root = lab["main"] / ".claude" / "dev-registry"
    assert G._qa_mode_sentinel_rw_bind(str(lab["main"]), "", str(reg_root)) == []


def test_non_direct_child_session_dir_is_refused(lab):
    _as(ORCHESTRATOR_PAYLOAD)
    nested = lab["main"] / ".claude" / "dev-registry" / SID / "deeper"
    nested.mkdir()
    assert G._qa_mode_sentinel_rw_bind(str(lab["main"]), "", str(nested)) == []


def test_in_place_emits_no_second_bind(lab):
    """worktree == main root is already RW via step 5; a second bind is wrong."""
    assert _bind(lab, ORCHESTRATOR_PAYLOAD, wt_real=str(lab["main"])) == []


@pytest.mark.parametrize("registry_dir", ["", None, 1234, {}])
def test_malformed_registry_dir_degrades_to_no_bind(lab, registry_dir):
    _as(ORCHESTRATOR_PAYLOAD)
    assert G._qa_mode_sentinel_rw_bind(str(lab["main"]), "", registry_dir) == []


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
def test_e2e_subagent_cannot_rewrite_the_sentinel(lab, kind):
    """The exploit, end-to-end: pre-fix this rewrote qa_mode on the HOST and
    disarmed subagentstop-e2e-enforce.py (which exits 0 on 'ba_validation')."""
    _write_state(lab, kind)
    rewritten = _drive_hook(lab, _tamper_cmd(lab["qa"]), SUBAGENT_PAYLOAD)
    assert rewritten, "boundary should still rewrite the command for a subagent"
    proc = subprocess.run(["/bin/bash", "-c", rewritten],
                          capture_output=True, text=True)
    assert proc.returncode != 0, "subagent write must FAIL"
    assert "Read-only file system" in proc.stderr
    assert _qa_mode(lab) == "final_verification", "sentinel must be untouched"


@requires_bwrap
@pytest.mark.parametrize("kind", ["registered_worktree", "fresh_clone_checkout"])
def test_e2e_orchestrator_mid_session_change_still_works(lab, kind):
    """The capability the bind exists for must survive the actor gate."""
    _write_state(lab, kind)
    rewritten = _drive_hook(lab, _tamper_cmd(lab["qa"]), ORCHESTRATOR_PAYLOAD)
    assert rewritten
    proc = subprocess.run(["/bin/bash", "-c", rewritten],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-400:]
    assert _qa_mode(lab) == "ba_validation", "value must persist on the HOST"


@requires_bwrap
def test_e2e_sibling_enforcement_flag_stays_non_removable(lab):
    """Widening the bind to the session DIRECTORY would make this pass-through;
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
    """Direct proof the bind is file-scoped: the enclosing dir stays RO."""
    _write_state(lab, "fresh_clone_checkout")
    newf = lab["sess"] / "planted.json"
    rewritten = _drive_hook(
        lab, f"python3 -c \"open('{newf}','w').write('{{}}')\"",
        ORCHESTRATOR_PAYLOAD)
    assert rewritten
    proc = subprocess.run(["/bin/bash", "-c", rewritten],
                          capture_output=True, text=True)
    assert proc.returncode != 0 and not newf.exists()
