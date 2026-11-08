"""LANE-B non-destructive receipt writers and serialized Stop coordinator."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
HOOKS = ROOT / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))
from lib import session_resources

spec = importlib.util.spec_from_file_location(
    "laneb_coordinator", HOOKS / "stop-workflow-coordinator.py"
)
assert spec and spec.loader
coordinator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = coordinator
spec.loader.exec_module(coordinator)

TRACKER = HOOKS / "posttool-todo-tracker.py"


@pytest.fixture(autouse=True)
def _external_trusted_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trust_root = tmp_path.parent / f"{tmp_path.name}-laneb-trust"
    trust_root.mkdir(mode=0o700)
    monkeypatch.setenv(session_resources.TRUST_ROOT_ENV, str(trust_root))
    monkeypatch.setenv(session_resources.TRUST_KEY_ENV, "cd" * 32)
    yield
    shutil.rmtree(trust_root, ignore_errors=True)


def _binding(label: str, *, command: str = "dev", session: str | None = None) -> dict:
    claude = session or f"claude-{label}"
    resource = f"resource-{label}"
    workflow = f"workflow-{label}"
    if command == "dev-overnight":
        resource = f"overnight-resource-{label}"
        workflow = f"overnight:{claude}"
    return {
        "claude_session_id": claude,
        "resource_session_id": resource,
        "role": "dev",
        "dispatch_id": f"dispatch-{label}",
        "agent_id": f"dispatch-{label}",
        "command": command,
        "workflow_instance_id": workflow,
        "workflow_generation": 1,
        "spec_id": "20260808-035658",
    }


def _publish(root: Path, binding: dict) -> None:
    session_resources.publish_terminal_receipt(
        root,
        claude_session_id=binding["claude_session_id"],
        resource_session_id=binding["resource_session_id"],
        command=binding["command"],
        terminal_status="completed",
        workflow_instance_id=binding["workflow_instance_id"],
        workflow_generation=binding["workflow_generation"],
    )


def _closeout_on_disk(root: Path, sid: str) -> None:
    """The overnight closeout the time-lock reads after end_time (lib/overnight
    closeout_gaps): Step 20's PM retrospective and Step 21's summary."""
    retro = root / "docs" / "dev" / "overnight" / sid / "retro-report-cycle1.json"
    retro.parent.mkdir(parents=True, exist_ok=True)
    retro.write_text("{}")
    (root / "docs" / "dev" / "overnight-summary-2026-11-01.md").write_text("done")


def _tree_digest(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {
        str(item.relative_to(path)): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(path.rglob("*"))
        if item.is_file() and not item.is_symlink()
    }


def _phase_script(root: Path, name: str, body: str = "") -> Path:
    path = root / f"phase-{name}.py"
    path.write_text(
        "import json,pathlib,sys,time\n"
        f"log=pathlib.Path({str(root / 'phase.log')!r})\n"
        f"log.write_text(log.read_text() + {name!r} + '\\n' if log.exists() else {name!r} + '\\n')\n"
        "payload=sys.stdin.buffer.read()\n" + body + "\n",
        encoding="utf-8",
    )
    return path


# The repair plan's tools/proto/crash.py (an instrument that dies before its pause
# check, exit 1) and slow.py (outlives its phase timeout). Neither writes phase.log.
CRASH_SOURCE = (
    "import sys\n"
    'raise ImportError("simulated: lib/overnight import failure before the pause check")\n'
)
SLOW_SOURCE = "import time; time.sleep(3)\n"
SLOW_TIMEOUT = 0.5  # below slow.py's 3 s sleep
# The phase a non-success outcome lands on when _phases names no target.
OUTCOME_PHASE = {
    "block": "coverage",
    "fail": "auto_commit",
    "timeout": "cleanup",
}
_OUTCOME_BODY = {
    "allow": "",
    "block": "raise SystemExit(2)",
    "fail": "raise SystemExit(1)",
    "timeout": "time.sleep(0.2)",
}


def _outcome_phase(root: Path, name: str, outcome: str):
    if outcome in ("crash", "slow"):
        script = root / f"{outcome}-{name}.py"
        script.write_text(CRASH_SOURCE if outcome == "crash" else SLOW_SOURCE, encoding="utf-8")
        timeout = SLOW_TIMEOUT if outcome == "slow" else 1.0
        return coordinator.Phase(name, (sys.executable, str(script)), timeout)
    if outcome == "missing":  # argv names a .py file that does not exist
        return coordinator.Phase(name, (sys.executable, str(root / f"missing-{name}.py")), 1.0)
    if outcome == "launch":  # the script exists, the interpreter does not
        script = _phase_script(root, name)
        return coordinator.Phase(name, (str(root / "no-such-interpreter"), str(script)), 1.0)
    script = _phase_script(root, name, _OUTCOME_BODY[outcome])
    timeout = 0.03 if outcome == "timeout" else 1.0
    return coordinator.Phase(name, (sys.executable, str(script)), timeout)


def _phases(root: Path, outcome: str = "allow", target: str | None = None) -> list:
    """The four phases in PHASE_ORDER, each logging its name to phase.log and
    allowing, except ``target`` (default OUTCOME_PHASE[outcome]), which runs
    ``outcome``: block (exit 2), fail (exit 1), timeout, crash, slow, missing or
    launch (error)."""
    target = target or OUTCOME_PHASE.get(outcome)
    return [
        _outcome_phase(root, name, outcome if name == target else "allow")
        for name in coordinator.PHASE_ORDER
    ]


def _overnight_state(root: Path, sid: str, binding: dict) -> None:
    """The session's overnight record, which the coordinator's receipt call reads."""
    state = {
        "session_id": sid,
        "dev_registry_session_id": binding["resource_session_id"],
        "end_time": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
    }
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / f"overnight-state-{sid}.json").write_text(json.dumps(state))


def _terminal_completion(root: Path, terminal: str = "completed_by_deadline"):
    """A completion phase that allows and prints the gate's terminal time-lock line."""
    body = f"print(json.dumps({{'timelock_terminal': {terminal!r}}}))"
    return coordinator.Phase("completion", (sys.executable, str(_phase_script(root, "completion", body))))


def test_the_coordinator_publishes_the_receipt_from_the_gates_terminal_line_and_finalize_reads_it(
    tmp_path: Path,
) -> None:
    """R9, P1b row 15 (acceptance 21): the coordinator alone makes the receipt call, on the
    gate's terminal time-lock line; finalize reads the receipt at that Stop and its own
    finalized.json at the next one, where the receipt is not written again. No phase gets
    either trust key."""
    root = tmp_path / "project"
    root.mkdir()
    sid = "claude-overnight"
    binding = _binding("overnight", command="dev-overnight", session=sid)
    provisioned = session_resources.provision(root, binding)
    _overnight_state(root, sid, binding)
    phase_list = []
    for name in coordinator.PHASE_ORDER:
        if name == "completion":
            phase_list.append(_terminal_completion(root))
            continue
        body = (
            "import os\n"
            f"pathlib.Path({str(root / f'{name}-keys.json')!r}).write_text(json.dumps(["
            f"os.environ.get({session_resources.TRUST_KEY_ENV!r}),"
            f"os.environ.get({session_resources.TRUST_ROOT_ENV!r})]))"
        )
        phase_list.append(
            coordinator.Phase(name, (sys.executable, str(_phase_script(root, name, body))))
        )
    receipt = (
        root / ".claude/session-resources" / binding["resource_session_id"] / "terminal.json"
    )

    def stop() -> tuple[dict, int]:
        return coordinator.run_coordinator(
            {"session_id": sid, "cwd": str(root)},
            project_dir=root,
            environment={**os.environ, "CLAUDE_PROJECT_DIR": str(root)},
            phases=phase_list,
        )

    first, first_exit = stop()
    assert first_exit == 0 and first["status"] == "pass", first
    assert first["finalizer_called"] is True and first["finalizer"]["idempotent"] is False
    assert json.loads(receipt.read_text())["terminal_status"] == "completed_by_deadline"
    assert not Path(provisioned["scratch_path"]).exists()
    written = receipt.read_bytes()

    second, second_exit = stop()
    assert second_exit == 0 and second["status"] == "pass", second
    assert second["finalizer_called"] is True and second["finalizer"]["idempotent"] is True
    assert receipt.read_bytes() == written
    for name in ("coverage", "auto_commit", "cleanup"):
        assert json.loads((root / f"{name}-keys.json").read_text()) == [None, None]


def test_no_receipt_without_a_terminal_line_or_without_a_resource_session(tmp_path: Path) -> None:
    """An allowed completion that prints no terminal line publishes nothing; a terminal
    line with no resource session provisioned publishes nothing either."""
    root = tmp_path / "project"
    root.mkdir()
    sid = "claude-overnight"
    binding = _binding("overnight", command="dev-overnight", session=sid)
    _overnight_state(root, sid, binding)
    phase_list = _phases(root)
    phase_list[coordinator.PHASE_ORDER.index("completion")] = _terminal_completion(root)
    plain = {k: v for k, v in os.environ.items() if k not in coordinator.TRUST_ENVIRONMENT_KEYS}
    result, exit_code = coordinator.run_coordinator(
        {"session_id": sid, "cwd": str(root)}, project_dir=root,
        environment={**plain, "CLAUDE_PROJECT_DIR": str(root)}, phases=phase_list,
    )
    assert exit_code == 0 and result["reason"] == "resource_broker_not_configured", result
    assert not (root / ".claude/session-resources").exists()


def test_the_real_gate_hands_the_receipt_its_terminal_status_once_the_closeout_is_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P2's time-lock receipt where it now lives: the completion phase is the real gate
    (hooks/stop-command-gate.py, P2's real window_open and closeout_gaps) on a session whose
    end_time has passed, in no gated span. With the closeout incomplete the gate allows and
    prints no terminal status, so there is no receipt to publish. With Step 20's
    retrospective and Step 21's summary on disk it prints completed_by_deadline, and the
    coordinator publishes that receipt (one cycle ended: its generation is 2) and
    finalizes."""
    root = tmp_path / "project"
    root.mkdir()
    sid = "claude-overnight"
    binding = {**_binding("overnight", command="dev-overnight", session=sid), "workflow_generation": 2}
    provisioned = session_resources.provision(root, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_text("preserve")
    before = _tree_digest(scratch)
    _overnight_state(root, sid, binding)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))  # the coordinator's own process, as the CLI starts it
    transcript = _transcript(tmp_path / "transcript.jsonl", ["summarise the night"])
    phase_list = _phases(root)
    phase_list[COMPLETION] = coordinator.Phase(
        "completion", (sys.executable, str(HOOKS / "stop-command-gate.py"), "--mode", "block"), 60.0)
    receipt = root / ".claude/session-resources" / binding["resource_session_id"] / "terminal.json"

    def stop() -> tuple[dict, int]:
        return coordinator.run_coordinator(
            {"session_id": sid, "transcript_path": str(transcript), "cwd": str(root)},
            project_dir=root, environment={**os.environ, "CLAUDE_PROJECT_DIR": str(root)}, phases=phase_list)

    def gate() -> subprocess.CompletedProcess:
        return subprocess.run(list(phase_list[COMPLETION].argv), text=True, capture_output=True,
                              input=json.dumps({"session_id": sid, "transcript_path": str(transcript),
                                                "cwd": str(root)}),
                              env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)}, cwd=str(root), timeout=60)

    held = gate()
    assert (held.returncode, held.stdout, held.stderr) == (0, "", "")
    assert not receipt.exists() and _tree_digest(scratch) == before
    _closeout_on_disk(root, sid)
    done = gate()
    assert (done.returncode, done.stdout) == (0, '{"timelock_terminal": "completed_by_deadline"}\n'), done.stderr
    result, exit_code = stop()
    assert exit_code == 0 and result["status"] == "pass" and result["finalizer_called"] is True, result
    assert json.loads(receipt.read_text())["terminal_status"] == "completed_by_deadline"
    assert not scratch.exists()


@pytest.mark.parametrize("outcome", ["block", "fail", "timeout"])
def test_non_success_phase_changes_zero_resource_bytes(
    tmp_path: Path, outcome: str
) -> None:
    """P1 (TC-11): coverage exit 2 blocks; an auto_commit exit 1 and a cleanup timeout
    are recorded and allowed. No outcome reaches the finalizer or changes a resource
    byte."""
    root = tmp_path / outcome
    root.mkdir()
    binding = _binding(outcome)
    session_resources.provision(root, binding)
    _publish(root, binding)
    resource_tree = root / ".claude"
    before = _tree_digest(resource_tree)
    result, exit_code = coordinator.run_coordinator(
        {"session_id": binding["claude_session_id"], "cwd": str(root)},
        project_dir=root,
        environment={**os.environ, "CLAUDE_PROJECT_DIR": str(root)},
        phases=_phases(root, outcome),
    )
    target = OUTCOME_PHASE[outcome]
    assert result["finalizer_called"] is False
    if outcome == "block":
        assert exit_code == 2 and result["status"] == "blocked"
        assert result["failed_phase"] == "coverage"
        assert result["_relay"] == "failed_phase=coverage\n"
        assert [p["phase"] for p in result["phases"]] == ["coverage"]
    else:
        assert exit_code == 0 and result["status"] == "pass"
        assert result["reason"] == "phase_failure_recorded"
        assert "failed_phase" not in result and "_relay" not in result
        assert [p["phase"] for p in result["phases"]] == list(coordinator.PHASE_ORDER)
        failed = [p for p in result["phases"] if p["status"] != "allow"]
        assert [(p["phase"], p["status"], p["failure"]) for p in failed] == [
            (
                target,
                outcome,
                {"fail": "exit code 1", "timeout": "timeout"}[outcome],
            )
        ]
    assert _tree_digest(resource_tree) == before


def test_all_success_finalizes_only_exact_resource_session(tmp_path: Path) -> None:
    root = tmp_path / "success"
    root.mkdir()
    actor_a = _binding("A")
    actor_b = _binding("B")
    a = session_resources.provision(root, actor_a)
    b = session_resources.provision(root, actor_b)
    Path(a["scratch_path"], "A").write_text("A")
    Path(b["scratch_path"], "B").write_text("B")
    b_before = _tree_digest(Path(b["scratch_path"]))
    _publish(root, actor_a)
    result, exit_code = coordinator.run_coordinator(
        {"session_id": actor_a["claude_session_id"], "cwd": str(root)},
        project_dir=root,
        environment={**os.environ, "CLAUDE_PROJECT_DIR": str(root)},
        phases=_phases(root),
    )
    assert exit_code == 0 and result["status"] == "pass"
    assert result["finalizer_called"] is True
    assert not Path(a["scratch_path"]).exists()
    assert _tree_digest(Path(b["scratch_path"])) == b_before
    assert (root / "phase.log").read_text().splitlines() == list(
        coordinator.PHASE_ORDER
    )


def test_subagent_stop_runs_no_phase_and_never_finalizes(tmp_path: Path) -> None:
    root = tmp_path / "subagent"
    root.mkdir()
    binding = _binding("subagent")
    provisioned = session_resources.provision(root, binding)
    _publish(root, binding)
    before = _tree_digest(root / ".claude")
    result, exit_code = coordinator.run_coordinator(
        {"session_id": binding["claude_session_id"], "agent_id": "child"},
        project_dir=root,
        phases=_phases(root),
    )
    assert exit_code == 0 and result["status"] == "nonterminal"
    assert result["phases"] == [] and result["finalizer_called"] is False
    assert _tree_digest(root / ".claude") == before
    assert Path(provisioned["scratch_path"]).exists()


def test_receipt_before_delayed_barrier_signals_nothing_until_release(
    tmp_path: Path,
) -> None:
    root = tmp_path / "barrier"
    root.mkdir()
    binding = _binding("barrier")
    provisioned = session_resources.provision(root, binding)
    ready = Path(provisioned["scratch_path"]) / "ready"
    code = (
        "import pathlib,signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        f"pathlib.Path({str(ready)!r}).write_text('ready');time.sleep(60)"
    )
    spawned = session_resources.spawn_owned(root, binding, [sys.executable, "-c", code])
    deadline = time.monotonic() + 3
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ready.exists()
    _publish(root, binding)
    barrier = root / "release"
    phase_list = _phases(root)
    coverage = _phase_script(
        root,
        "coverage-barrier",
        f"\nwhile not pathlib.Path({str(barrier)!r}).exists(): time.sleep(0.02)\n",
    )
    phase_list[1] = coordinator.Phase("coverage", (sys.executable, str(coverage)), 3.0)
    holder: dict = {}

    def run() -> None:
        holder["result"] = coordinator.run_coordinator(
            {"session_id": binding["claude_session_id"], "cwd": str(root)},
            project_dir=root,
            phases=phase_list,
        )

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.15)
    assert thread.is_alive()
    assert Path(f"/proc/{spawned['pid']}").exists()
    assert Path(provisioned["scratch_path"]).exists()
    barrier.write_text("release")
    thread.join(timeout=5)
    assert holder["result"][1] == 0
    assert not Path(provisioned["scratch_path"]).exists()


def test_preflight_precedes_phases_and_finalizes_retained_exact_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "preflight-order"
    root.mkdir()
    event_log = root / "phase.log"
    trust_environment = {
        session_resources.TRUST_KEY_ENV: "a5" * 32,
        session_resources.TRUST_ROOT_ENV: str(tmp_path / "private-trust"),
    }
    supplied_environment = {
        **trust_environment,
        "VISIBLE_PHASE_VALUE": "retained",
        "LANEB_UNRELATED": "ordinary",
    }
    pointer = {"resource_session_id": "resource-retained"}
    trust_calls: list[tuple[str, dict[str, str]]] = []

    def append_event(value: str) -> None:
        with event_log.open("a", encoding="utf-8") as handle:
            handle.write(value + "\n")

    def resolve(
        project_dir: Path,
        session_id: str,
        *,
        trust_environment: dict[str, str],
    ) -> dict:
        assert Path(project_dir) == root
        assert session_id == "claude-retained"
        trust_calls.append(("resolve", trust_environment))
        append_event("resolve")
        return pointer

    def finalize(
        project_dir: Path,
        *,
        claude_session_id: str,
        resource_session_id: str,
        trust_environment: dict[str, str],
    ) -> dict:
        assert Path(project_dir) == root
        assert claude_session_id == "claude-retained"
        assert resource_session_id == "resource-retained"
        trust_calls.append(("finalize", trust_environment))
        append_event(f"finalize:{resource_session_id}")
        return {"status": "pass", "idempotent": False}

    monkeypatch.setattr(
        coordinator.session_resources, "resolve_current_resource_session", resolve
    )
    monkeypatch.setattr(coordinator.session_resources, "finalize", finalize)

    phase_list = []
    for name in coordinator.PHASE_ORDER:
        observation = root / f"{name}-environment.json"
        body = (
            "import os\n"
            f"pathlib.Path({str(observation)!r}).write_text(json.dumps({{"
            f"'key':os.environ.get({session_resources.TRUST_KEY_ENV!r}),"
            f"'root':os.environ.get({session_resources.TRUST_ROOT_ENV!r}),"
            "'visible':os.environ.get('VISIBLE_PHASE_VALUE'),"
            "'ordinary':os.environ.get('LANEB_UNRELATED'),"
            "'coordinated':os.environ.get('LANEB_COORDINATED_STOP'),"
            "'project':os.environ.get('CLAUDE_PROJECT_DIR')}, sort_keys=True))"
        )
        script = _phase_script(root, name, body)
        phase_list.append(coordinator.Phase(name, (sys.executable, str(script))))

    original_run_phase = coordinator._run_phase

    def mutate_pointer_after_first_phase(*args: object, **kwargs: object) -> dict:
        result = original_run_phase(*args, **kwargs)
        phase = args[0] if args else kwargs["phase"]
        if phase.name == "coverage":
            pointer["resource_session_id"] = "resource-rebound"
        return result

    monkeypatch.setattr(coordinator, "_run_phase", mutate_pointer_after_first_phase)
    result, exit_code = coordinator.run_coordinator(
        {"session_id": "claude-retained", "cwd": str(root)},
        project_dir=root,
        environment=supplied_environment,
        phases=phase_list,
    )

    assert exit_code == 0 and result["resource_session_id"] == "resource-retained"
    assert event_log.read_text().splitlines() == [
        "resolve",
        *coordinator.PHASE_ORDER,
        "finalize:resource-retained",
    ]
    assert [item[0] for item in trust_calls] == ["resolve", "finalize"]
    assert trust_calls[0][1] == trust_environment == trust_calls[1][1]
    assert trust_calls[0][1] is trust_calls[1][1]
    for name in coordinator.PHASE_ORDER:
        observed = json.loads((root / f"{name}-environment.json").read_text())
        # R9: no phase gets either key; the coordinator itself makes the receipt call.
        keys: dict = {}
        assert observed == {
            "coordinated": "1",
            "key": keys.get(session_resources.TRUST_KEY_ENV),
            "ordinary": "ordinary",
            "project": str(root),
            "root": keys.get(session_resources.TRUST_ROOT_ENV),
            "visible": "retained",
        }


def test_preflight_failure_is_fixed_redacted_and_runs_zero_phases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "preflight-redaction"
    root.mkdir()
    trust_key = "b6" * 32
    trust_root = str(tmp_path / "secret-trust-root")
    observed_trust: list[dict[str, str]] = []

    def reject(*args: object, **kwargs: object) -> dict:
        observed_trust.append(dict(kwargs["trust_environment"]))
        raise RuntimeError(f"private failure {trust_key} {trust_root}")

    monkeypatch.setattr(
        coordinator.session_resources, "resolve_current_resource_session", reject
    )
    result, exit_code = coordinator.run_coordinator(
        {"session_id": "claude-redacted", "cwd": str(root)},
        project_dir=root,
        environment={
            session_resources.TRUST_KEY_ENV: trust_key,
            session_resources.TRUST_ROOT_ENV: trust_root,
        },
        phases=_phases(root),
    )

    serialized = json.dumps(result, sort_keys=True)
    assert exit_code == 2
    assert result == {
        "status": "blocked",
        "reason": "resource_preflight_contract_error",
        "phases": [],
        "finalizer_called": False,
    }
    assert trust_key not in serialized and trust_root not in serialized
    assert not (root / "phase.log").exists()
    assert observed_trust == [
        {
            session_resources.TRUST_KEY_ENV: trust_key,
            session_resources.TRUST_ROOT_ENV: trust_root,
        }
    ]


def test_finalizer_failure_is_fixed_and_cannot_echo_trust_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "finalizer-redaction"
    root.mkdir()
    trust_key = "c7" * 32
    trust_root = str(tmp_path / "finalizer-secret-root")

    monkeypatch.setattr(
        coordinator.session_resources,
        "resolve_current_resource_session",
        lambda *args, **kwargs: {"resource_session_id": "resource-redacted"},
    )
    monkeypatch.setattr(
        coordinator.session_resources,
        "finalize",
        lambda *args, **kwargs: {
            "status": "fail",
            "error_code": trust_key,
            "detail": trust_root,
        },
    )
    result, exit_code = coordinator.run_coordinator(
        {"session_id": "claude-redacted", "cwd": str(root)},
        project_dir=root,
        environment={
            session_resources.TRUST_KEY_ENV: trust_key,
            session_resources.TRUST_ROOT_ENV: trust_root,
        },
        phases=_phases(root),
    )

    serialized = json.dumps(result, sort_keys=True)
    assert exit_code == 2
    assert result["reason"] == "resource_finalize_failed"
    assert result["finalizer_called"] is True
    assert "finalizer" not in result
    assert trust_key not in serialized and trust_root not in serialized
    assert (root / "phase.log").read_text().splitlines() == list(
        coordinator.PHASE_ORDER
    )


# --------------------------------------------------------------------------
# P5 R9: the coordinator's phases, mode, fallback and relay (acceptance 9, 11, 13; P1's TC-11)
# --------------------------------------------------------------------------

COORDINATOR = HOOKS / "stop-workflow-coordinator.py"
STOP_SESSION = "8b2f4c1d-6a3e-4f70-9d12-3c5e7a9b0f14"
# The prompts each transcript records: (command, args) is a typed slash command,
# a str a plain typed prompt. ACTIVE is command_span.active_command of each.
TRANSCRIPTS = {
    "dev-overnight": [("dev-overnight", "8h fix the flaky suite")],
    "dev-overnight-then-stop": [("dev-overnight", "8h fix the flaky suite"), ("stop", "")],
    "dev-overnight-then-spec": [("dev-overnight", "8h fix the flaky suite"), ("spec", "add a flag")],
    "dev": [("dev", "fix the flaky suite")],
    "dev-then-stop": [("dev", "fix the flaky suite"), "keep going", ("stop", "")],
    "spec": [("spec", "a spec")],
    "no-command": ["summarise the open issues"],
}
ACTIVE = {
    "dev-overnight": "dev-overnight",
    "dev-overnight-then-stop": "stop",
    "dev-overnight-then-spec": "spec",
    "dev": "dev",
    "dev-then-stop": "stop",
    "spec": "spec",
    "no-command": None,
}
# (status, returncode, failure) the result JSON records for each instrument failure.
INSTRUMENT_FAILURES = {
    "crash": ("fail", 1, "exit code 1"),
    "slow": ("timeout", None, "timeout"),
    "missing": ("fail", None, "missing file"),
    "launch": ("fail", None, "launch error"),
}
NOTICE = "Checkpoint snapshot refused: settings.json carries machine-local paths."
COMPLETION = coordinator.PHASE_ORDER.index("completion")


def _cli_record(index: int, record_type: str, **fields) -> dict:
    record = {
        "parentUuid": f"uuid-{index - 1:04d}" if index > 1 else None,
        "isSidechain": False,
        "type": record_type,
        "uuid": f"uuid-{index:04d}",
        "timestamp": f"2026-10-19T11:00:{index % 60:02d}.000Z",
        "userType": "external",
        "entrypoint": "cli",
        "cwd": "/opt/demo/toyproj",
        "sessionId": STOP_SESSION,
        "version": "2.1.303",
    }
    record.update(fields)
    return record


def _transcript(path: Path, prompts: list) -> Path:
    """A CLI-shaped main transcript: per typed prompt an enqueue/dequeue
    queue-operation pair, the human-typed user record (a slash command as
    <command-name>, followed by its isMeta command body) and an assistant reply."""
    records: list = []
    for prompt in prompts:
        if isinstance(prompt, tuple):
            name, args = prompt
            text = (
                f"<command-message>{name}</command-message>\n"
                f"<command-name>/{name}</command-name>\n"
                f"<command-args>{args}</command-args>"
            )
            queued = f"/{name} {args}".strip()
        else:
            name, text, queued = None, prompt, prompt
        stamp = f"2026-10-19T10:59:{len(records) % 60:02d}.000Z"
        records.append(
            {"type": "queue-operation", "operation": "enqueue", "timestamp": stamp,
             "sessionId": STOP_SESSION, "content": queued}
        )
        records.append(
            {"type": "queue-operation", "operation": "dequeue", "timestamp": stamp,
             "sessionId": STOP_SESSION}
        )
        index = len(records) + 1
        records.append(
            _cli_record(
                index, "user", promptId=f"prompt-{index:04d}",
                message={"role": "user", "content": text},
                permissionMode="default", origin={"kind": "human"},
            )
        )
        if name:
            records.append(
                _cli_record(
                    len(records) + 1, "user", isMeta=True,
                    promptId=f"prompt-{index:04d}",
                    message={"role": "user", "content": [
                        {"type": "text", "text": f"# /{name}\nFollow the steps."}
                    ]},
                )
            )
        records.append(
            _cli_record(
                len(records) + 1, "assistant",
                message={"role": "assistant", "content": [
                    {"type": "text", "text": "Working on it."}
                ]},
            )
        )
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def _project(tmp_path: Path, transcript: str) -> tuple[Path, Path]:
    root = tmp_path / "project"
    root.mkdir()
    path = _transcript(tmp_path / "transcript.jsonl", TRANSCRIPTS[transcript])
    assert coordinator.command_span.active_command(path) == ACTIVE[transcript]
    return root, path


def _plain_environment(tmp_path: Path, root: Path, gate: str | None = None) -> dict:
    """The ambient environment without the resource-broker trust keys (so no
    broker runs), HOME and CLAUDE_CONFIG_DIR pinned to a tmp home, and
    CLAUDE_COMMAND_GATE set to ``gate`` (unset for None)."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in coordinator.TRUST_ENVIRONMENT_KEYS and key != "CLAUDE_COMMAND_GATE"
    }
    environment.update(
        {
            "HOME": str(home),
            "CLAUDE_CONFIG_DIR": str(home / ".claude"),
            "CLAUDE_PROJECT_DIR": str(root),
        }
    )
    if gate is not None:
        environment["CLAUDE_COMMAND_GATE"] = gate
    return environment


def _payload(root: Path, transcript: Path) -> dict:
    return {
        "session_id": STOP_SESSION,
        "transcript_path": str(transcript),
        "cwd": str(root),
        "hook_event_name": "Stop",
        "stop_hook_active": False,
    }


def _stop(tmp_path: Path, root: Path, phases: list, transcript: Path, gate: str | None = None,
          extra: dict | None = None, marked: bool = True) -> subprocess.CompletedProcess:
    """One Stop through the coordinator's main(), the phases passed through its
    LANEB_COORDINATOR_PHASES_JSON override, CLAUDE_COMMAND_GATE=``gate`` (None:
    unset), run as the launcher runs it (``marked``) or directly by an older hook
    list."""
    environment = _plain_environment(tmp_path, root, gate)
    environment.update(extra or {})
    if marked:
        environment[coordinator.LAUNCHER_MARK] = "1"
    environment["LANEB_COORDINATOR_PHASES_JSON"] = json.dumps(
        [{"name": p.name, "argv": list(p.argv), "timeout": p.timeout} for p in phases]
    )
    return subprocess.run(
        [sys.executable, str(COORDINATOR)],
        input=json.dumps(_payload(root, transcript)),
        text=True,
        capture_output=True,
        cwd=str(root),
        env=environment,
        timeout=60,
    )


def _logged(root: Path) -> list:
    log = root / "phase.log"
    return log.read_text().splitlines() if log.exists() else []


def _completion(root: Path, body: str):
    return coordinator.Phase("completion", (sys.executable, str(_phase_script(root, "completion", body))), 5.0)


INSTRUMENT_LINE = "COMMAND_GATE instrument failure: {}. The gate is broken; the human can type /stop\n"


@pytest.mark.parametrize("failure", sorted(INSTRUMENT_FAILURES))
def test_a9_completion_instrument_failure_blocks_a_gated_span_naming_stop(
    tmp_path: Path, failure: str
) -> None:
    """A9: a crashing (tools/proto crash.py), slow (slow.py past its lowered timeout),
    missing or unlaunchable gate blocks a /dev Stop in block mode with the fixed line
    naming /stop: no exception text, argv or gate stderr, and cleanup does not run."""
    root, transcript = _project(tmp_path, "dev")
    phases = _phases(root, failure, target="completion")
    status, returncode, reason = INSTRUMENT_FAILURES[failure]

    started = time.monotonic()
    proc = _stop(tmp_path, root, phases, transcript)

    assert time.monotonic() - started < 300
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert proc.stderr == INSTRUMENT_LINE.format(reason)
    for leaked in ("ImportError", "simulated", "Traceback", "failed_phase=", phases[COMPLETION].argv[-1]):
        assert leaked not in proc.stderr and leaked not in proc.stdout
    out = json.loads(proc.stdout)
    assert out["status"] == "blocked" and out["failed_phase"] == "completion"
    assert out["reason"] == "completion_instrument_failure"
    assert out["finalizer_called"] is False and "_relay" not in out
    assert [
        (p["phase"], p["status"], p["returncode"], p.get("failure")) for p in out["phases"]
    ] == [("coverage", "allow", 0, None), ("auto_commit", "allow", 0, None),
          ("completion", status, returncode, reason)]
    assert _logged(root) == ["coverage", "auto_commit"]  # no cleanup on a blocked Stop


@pytest.mark.parametrize("failure", sorted(INSTRUMENT_FAILURES))
@pytest.mark.parametrize(
    ("transcript", "marked"),
    [("dev-then-stop", True), ("dev-overnight-then-stop", True), ("no-command", True), ("dev", False)],
)
def test_a9_completion_instrument_failure_outside_a_gated_armed_span_is_recorded_and_allowed(
    tmp_path: Path, transcript: str, marked: bool, failure: str
) -> None:
    """A9: after the human's /stop (the gate still failing), with no typed command, or run
    directly by an older hook list (advisory, arming option 1), a gate instrument failure
    with no open window is recorded and allowed, and cleanup runs."""
    root, path = _project(tmp_path, transcript)
    status, returncode, reason = INSTRUMENT_FAILURES[failure]

    proc = _stop(tmp_path, root, _phases(root, failure, target="completion"), path, marked=marked)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stderr == ""
    out = json.loads(proc.stdout)
    assert out["status"] == "pass" and out["reason"] == "phase_failure_recorded"
    assert out["finalizer_called"] is False and "failed_phase" not in out
    assert [p["phase"] for p in out["phases"]] == list(coordinator.PHASE_ORDER)
    recorded = out["phases"][COMPLETION]
    assert (recorded["status"], recorded["returncode"], recorded["failure"], recorded["fallback"]) == (
        status, returncode, reason, "allow")
    assert _logged(root) == ["coverage", "auto_commit", "cleanup"]


def _window(root: Path, is_open: bool) -> None:
    """The session's overnight record, read by P2's real overnight.window_open (its end_time an
    hour ahead, or an hour past)."""
    (root / ".claude").mkdir(exist_ok=True)
    end = datetime.now(timezone.utc) + timedelta(hours=1 if is_open else -1)
    (root / ".claude" / f"overnight-state-{STOP_SESSION}.json").write_text(json.dumps(
        {"session_id": STOP_SESSION, "end_time": end.strftime("%Y-%m-%dT%H:%M:%SZ")}))


@pytest.mark.parametrize("failure", ["crash", "slow", "missing"])
@pytest.mark.parametrize(
    ("transcript", "window", "code"),
    [
        ("dev-overnight-then-spec", True, 2),  # a human /spec inside the window
        ("dev-overnight-then-stop", True, 0),  # the human's /stop closes the window
        ("no-command", False, 0),  # no window and no gated command
    ],
)
def test_a9_a_failed_gate_blocks_while_the_window_is_open_whatever_the_command(
    tmp_path: Path, failure: str, transcript: str, window: bool, code: int
) -> None:
    """P2 acceptance 9, where the time-lock now lives (the completion phase, P5 R9): copies of
    the plan's crash.py and slow.py (and a missing phase file) as the gate. While the
    session's time-lock window is open (its state's end_time ahead, no human /stop since its
    /dev-overnight: P2's real lib/overnight window_open) the failure blocks with the fixed
    line naming /stop, whatever command the human typed last; after the human's /stop, or
    with no window and no gated command, it is recorded and allowed."""
    root, path = _project(tmp_path, transcript)
    if window:
        _window(root, True)
    proc = _stop(tmp_path, root, _phases(root, failure, target="completion"), path)
    assert proc.returncode == code, proc.stdout + proc.stderr
    reason = INSTRUMENT_FAILURES[failure][2]
    assert proc.stderr == (INSTRUMENT_LINE.format(reason) if code else "")


@pytest.mark.parametrize("marked", [True, False])
def test_a9_an_open_window_blocks_a_failed_gate_whatever_the_latest_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, marked: bool
) -> None:
    """A9: the window open (P2's real window_open on the session's record) and the latest
    human command /spec: a crashing gate still blocks, armed or run directly by an older hook
    list; the window closed (end_time passed), it allows."""
    root, transcript = _project(tmp_path, "spec")
    environment = _plain_environment(tmp_path, root)
    environment.update({coordinator.LAUNCHER_MARK: "1"} if marked else {})
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)  # the in-process fallback reads the payload's cwd
    for is_open, code in ((True, 2), (False, 0)):
        _window(root, is_open)
        result, exit_code = coordinator.run_coordinator(
            _payload(root, transcript), project_dir=root, environment=environment,
            phases=_phases(root, "crash", target="completion"),
        )
        assert exit_code == code, result
        if code == 2:
            assert result["_relay"] == INSTRUMENT_LINE.format("exit code 1")


def test_a9_gate_off_skips_completion_and_its_failure(tmp_path: Path) -> None:
    """A9, A11: CLAUDE_COMMAND_GATE=off skips the completion phase (and the time-lock it
    holds): a /dev Stop whose gate would block or crash is allowed, cleanup runs."""
    root, transcript = _project(tmp_path, "dev")
    for phases in (_phases(root, "crash", target="completion"),
                   _phases(root, "block", target="completion")):
        proc = _stop(tmp_path, root, phases, transcript, gate="off")
        assert proc.returncode == 0 and proc.stderr == "", proc.stdout + proc.stderr
        out = json.loads(proc.stdout)
        assert out["phases"][COMPLETION] == {"phase": "completion", "status": "skipped", "returncode": None,
                                             "reason": "CLAUDE_COMMAND_GATE=off"}
    assert "completion" not in _logged(root)


def test_a11_the_mode_comes_from_the_process_environment_only(tmp_path: Path) -> None:
    """A11: CLAUDE_COMMAND_GATE=off written into settings.machine.json between two Stops
    of one session changes nothing: the mode is read from the process environment."""
    root, transcript = _project(tmp_path, "dev")
    body = "sys.stderr.write('COMMAND_GATE /dev: not complete\\n- todo: not completed: x\\n')\nraise SystemExit(2)"
    phases = _phases(root)
    phases[COMPLETION] = _completion(root, body)
    first = _stop(tmp_path, root, phases, transcript)
    machine = tmp_path / "home" / ".claude" / "settings.machine.json"
    machine.write_text(json.dumps({"env": {"CLAUDE_COMMAND_GATE": "off"}}))
    second = _stop(tmp_path, root, phases, transcript, extra={"CLAUDE_HOME": str(machine.parent)})
    assert first.returncode == second.returncode == 2
    assert first.stderr == second.stderr == "COMMAND_GATE /dev: not complete\n- todo: not completed: x\n"


def test_a11_after_p5_d_any_value_but_off_blocks_and_only_the_launchers_mark_arms() -> None:
    """A11 (P5-d), arming option 1: launched, unset, `advisory`, `block` or any other value
    blocks and `off` is off; run directly by an older hook list (no mark), the gate runs
    advisory and `off` is still off; a forged mark only arms."""
    mark = {coordinator.LAUNCHER_MARK: "1"}
    for value, launched, direct in (("", "block", "advisory"), ("advisory", "block", "advisory"),
                                    ("block", "block", "advisory"), ("on", "block", "advisory"),
                                    ("off", "off", "off")):
        gate = {"CLAUDE_COMMAND_GATE": value} if value else {}
        assert coordinator.gate_mode({**gate, **mark}) == launched, value
        assert coordinator.gate_mode(gate) == direct, value
    assert coordinator._default_phases().pop(COMPLETION).argv[-1] == "block"


def test_completion_block_relays_the_gates_whole_stderr_first(tmp_path: Path) -> None:
    """R9: a completion block relays the gate's stderr whole and first (its head line
    `COMMAND_GATE /<command>: not complete` survives any length), with no phase prefix."""
    root, transcript = _project(tmp_path, "dev")
    text = "COMMAND_GATE /dev: not complete\n" + "".join(f"- gap {k}\n" for k in range(600))
    assert len(text) > 4096
    phases = _phases(root)
    phases[COMPLETION] = _completion(root, f"sys.stderr.write({text!r})\nraise SystemExit(2)")

    proc = _stop(tmp_path, root, phases, transcript)

    assert proc.returncode == 2 and proc.stderr == text
    out = json.loads(proc.stdout)
    assert out["status"] == "blocked" and out["failed_phase"] == "completion" and out["reason"] == "phase_block"
    assert _logged(root) == ["coverage", "auto_commit", "completion"]


def test_an_allowed_completions_stderr_is_relayed(tmp_path: Path) -> None:
    """A11, A21 (advisory, run directly by an older hook list): the gate's `would block`
    text on an allowed Stop reaches the coordinator's stderr; the Stop is allowed and
    cleanup runs."""
    root, transcript = _project(tmp_path, "dev")
    text = "would block\nCOMMAND_GATE /dev: not complete\n- todo: not completed: x\n"
    phases = _phases(root)
    phases[COMPLETION] = _completion(root, f"sys.stderr.write({text!r})")

    proc = _stop(tmp_path, root, phases, transcript, marked=False)

    assert proc.returncode == 0 and proc.stderr == text, proc.stdout
    assert _logged(root) == list(coordinator.PHASE_ORDER)


def test_coverage_block_relays_failed_phase_and_last_4kb_of_its_stderr(tmp_path: Path) -> None:
    """A coverage exit 2 blocks whatever the typed command, relaying failed_phase=coverage
    and the last 4 KB of its stderr; no later phase runs."""
    root, transcript = _project(tmp_path, "no-command")
    reason = "coverage: the split is short"
    phase_stderr = "diagnostic padding line\n" * 300 + reason + "\n"
    phases = _phases(root)
    phases[0] = coordinator.Phase(
        "coverage",
        (sys.executable, str(_phase_script(root, "coverage", f"sys.stderr.write({phase_stderr!r})\nraise SystemExit(2)"))),
        1.0,
    )

    proc = _stop(tmp_path, root, phases, transcript)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert proc.stderr == "failed_phase=coverage\n" + phase_stderr[-4096:]
    out = json.loads(proc.stdout)
    assert out["status"] == "blocked" and out["failed_phase"] == "coverage"
    assert [p["phase"] for p in out["phases"]] == ["coverage"]
    assert _logged(root) == ["coverage"]


@pytest.mark.parametrize("failure", ["crash", "slow", "missing", "launch"])
@pytest.mark.parametrize("phase", ["coverage", "auto_commit", "cleanup"])
def test_non_completion_failure_is_recorded_and_allowed_and_later_phases_run(
    tmp_path: Path, phase: str, failure: str
) -> None:
    """TC-11, A13: coverage blocks only by exit 2. A coverage exit 1, an auto_commit exit 1,
    a cleanup timeout, and any other coverage, auto_commit or cleanup failure is recorded
    and allowed, also under a typed /dev-overnight; after an auto_commit failure the
    completion and cleanup phases still run."""
    root, transcript = _project(tmp_path, "dev-overnight")

    result, exit_code = coordinator.run_coordinator(
        _payload(root, transcript),
        project_dir=root,
        environment={**_plain_environment(tmp_path, root), coordinator.LAUNCHER_MARK: "1"},
        phases=_phases(root, failure, target=phase),
    )

    assert exit_code == 0
    assert result["status"] == "pass" and result["reason"] == "phase_failure_recorded"
    assert result["finalizer_called"] is False
    assert "failed_phase" not in result and "_relay" not in result
    assert [p["phase"] for p in result["phases"]] == list(coordinator.PHASE_ORDER)
    recorded = {
        p["phase"]: (p["status"], p["returncode"], p.get("failure"))
        for p in result["phases"]
    }
    assert recorded.pop(phase) == INSTRUMENT_FAILURES[failure]
    assert set(recorded.values()) == {("allow", 0, None)}
    # crash, slow, missing and launch never log; every other phase ran.
    assert _logged(root) == [name for name in coordinator.PHASE_ORDER if name != phase]


def test_a13_phase_order_and_timeouts_fit_the_launcher_and_the_registration() -> None:
    """A13, R9: coverage, auto_commit, completion (the gate, 60 s), cleanup; 30 + 120 + 60
    + 30 = 240 s of phase timeouts under the launcher's 280 s and the Stop entry's 300 s."""
    defaults = coordinator._default_phases("block")
    assert tuple(p.name for p in defaults) == coordinator.PHASE_ORDER == (
        "coverage", "auto_commit", "completion", "cleanup")
    assert coordinator.BLOCKING_PHASES == ("coverage", "completion")
    completion = defaults[COMPLETION]
    assert completion.argv[1:] == (str(HOOKS / "stop-command-gate.py"), "--mode", "block")
    assert completion.timeout == 60
    total = sum(p.timeout for p in defaults)
    launcher = (HOOKS / "stop-launch.py").read_text(encoding="utf-8")
    assert total == 240 < 280 and "COORDINATOR_TIMEOUT = 280" in launcher
    # The pre-launch missing-file check finds every default phase script.
    assert all(Path(coordinator._phase_script(p.argv)).is_file() for p in defaults)
    settings = json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))
    entries = [hook for group in settings["hooks"]["Stop"] for hook in group["hooks"]
               if "stop-launch.py" in hook.get("command", "")]
    assert len(entries) == 1 and entries[0]["timeout"] == 300


def test_a13_a_blocked_stop_runs_auto_commit_before_the_gate_and_no_cleanup(tmp_path: Path) -> None:
    """A13: a blocked Stop has run auto_commit (the refs/checkpoints snapshot) and keeps
    the /allow grants (cleanup does not run); an allowed one runs cleanup; an auto_commit
    failure on a complete span is recorded in the JSON, allowed, and cleanup runs."""
    root, transcript = _project(tmp_path, "dev")
    phases = _phases(root, "block", target="completion")
    assert _stop(tmp_path, root, phases, transcript).returncode == 2
    assert _logged(root) == ["coverage", "auto_commit", "completion"]
    (root / "phase.log").unlink()
    assert _stop(tmp_path, root, _phases(root), transcript).returncode == 0
    assert _logged(root) == list(coordinator.PHASE_ORDER)
    (root / "phase.log").unlink()
    proc = _stop(tmp_path, root, _phases(root, "fail", target="auto_commit"), transcript)
    out = json.loads(proc.stdout)
    assert proc.returncode == 0 and out["reason"] == "phase_failure_recorded"
    assert out["phases"][1]["failure"] == "exit code 1"
    assert _logged(root) == list(coordinator.PHASE_ORDER)


def test_a13_coverage_blocks_nothing_at_a_spec_orchestrator_stop(tmp_path: Path) -> None:
    """A13: the registered coverage phase (an exit-0 stub) allows a /spec Stop with no
    window, whatever its split."""
    root, transcript = _project(tmp_path, "spec")
    coverage = coordinator._default_phases()[0]
    done = subprocess.run(list(coverage.argv), input=json.dumps(_payload(root, transcript)), text=True,
                          capture_output=True, cwd=str(root), env=_plain_environment(tmp_path, root, "block"))
    assert (done.returncode, done.stderr) == (0, "")


def test_passing_phase_notice_is_still_relayed(tmp_path: Path) -> None:
    """P7: a passing phase's last-line systemMessage is shown as the coordinator's own."""
    root, transcript = _project(tmp_path, "no-command")
    phases = _phases(root)
    body = f"print('snapshot refused')\nprint(json.dumps({{'systemMessage': {NOTICE!r}}}))"
    phases[1] = coordinator.Phase(
        "auto_commit", (sys.executable, str(_phase_script(root, "auto_commit", body))), 1.0
    )

    proc = _stop(tmp_path, root, phases, transcript)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stderr == ""
    out = json.loads(proc.stdout)
    assert out["systemMessage"] == NOTICE
    assert all("notice" not in p for p in out["phases"])
    assert out["status"] == "pass" and out["finalizer_called"] is False


@pytest.mark.parametrize("phase", ["auto_commit", "cleanup"])
def test_auto_commit_or_cleanup_exit_2_is_recorded_and_never_relayed(
    tmp_path: Path, phase: str
) -> None:
    """TC-11: only coverage and completion may block. An auto_commit or cleanup exit 2
    under a typed /dev-overnight is recorded and allowed, its stderr is not relayed."""
    root, transcript = _project(tmp_path, "dev-overnight")
    phases = _phases(root)
    index = coordinator.PHASE_ORDER.index(phase)
    body = f"sys.stderr.write({phase + ' diagnostic: snapshot write failed'!r})\nraise SystemExit(2)"
    phases[index] = coordinator.Phase(
        phase, (sys.executable, str(_phase_script(root, phase, body))), 1.0
    )

    proc = _stop(tmp_path, root, phases, transcript)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stderr == ""
    out = json.loads(proc.stdout)
    assert out["status"] == "pass" and out["reason"] == "phase_failure_recorded"
    assert out["finalizer_called"] is False and "failed_phase" not in out
    recorded = out["phases"][index]
    assert recorded["returncode"] == 2 and recorded["status"] != "allow"
    assert "diagnostic" not in proc.stdout
    assert _logged(root) == list(coordinator.PHASE_ORDER)
