"""The one-process gates: hooks/lib/gate_runner.py and the three gate files built on it.

- The runner keeps each rule's decision: a rule runs as its own hook would run alone,
  in its own try; an observer's or a witness's error never blocks; refusals are
  reported together, once.
- The dispatch gate writes the changelog-analyst's dispatch witness only after every
  refusing rule let the dispatch through (a witness never records a dispatch the gate
  refused), and never blocks on the witness.
- Each gate refuses exactly when one of its hooks, run alone, refuses, and its stderr
  carries every refusing hook's reason (a differential over the same payloads).

Run with: python3 -m pytest hooks/tests/test_one_process_gates.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS))

from lib import gate_runner  # noqa: E402
from lib.gate_runner import ADVISE, CONSULT, OBSERVE, REFUSE, WITNESS, Rule  # noqa: E402


def _hook(tmp_path: Path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text("import sys, json, os\n" + body)
    return str(path)


def _run(script: str, payload: dict, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, script], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, timeout=120)


# ---------------------------------------------------------------- the runner


def test_rules_run_in_order_and_a_witness_follows_every_pass(tmp_path):
    log = tmp_path / "log"
    mark = lambda tag: f"open({str(log)!r}, 'a').write({tag!r} + '\\n')\n"  # noqa: E731
    rules = [
        Rule("a", _hook(tmp_path, "a.py", mark("a") + "sys.exit(0)\n")),
        Rule("o", _hook(tmp_path, "o.py", mark("o") + "raise RuntimeError('observer bug')\n"), OBSERVE),
        Rule("b", _hook(tmp_path, "b.py", mark("b") + "sys.stdin.read()\n")),
        Rule("w", _hook(tmp_path, "w.py", mark("w") + "sys.exit(2)\n"), WITNESS),
    ]
    outcomes = gate_runner.evaluate(rules, b"{}")
    assert log.read_text().split() == ["a", "o", "b", "w"]
    assert [o.code for o in outcomes] == [0, 1, 0, 2]
    assert gate_runner.report(outcomes) == 0  # neither the observer's error nor the witness's 2 blocks


def test_refusals_are_reported_together_and_the_witness_is_skipped(tmp_path, capsys):
    witness_ran = tmp_path / "witness"
    rules = [
        Rule("x", _hook(tmp_path, "x.py", "print('x out'); sys.stderr.write('x refuses\\n'); sys.exit(2)\n")),
        Rule("y", _hook(tmp_path, "y.py", "sys.stderr.write('y note\\n')\n")),
        Rule("z", _hook(tmp_path, "z.py", "sys.stderr.write('z refuses\\n'); sys.exit(2)\n")),
        Rule("w", _hook(tmp_path, "w.py", f"open({str(witness_ran)!r}, 'w')\n"), WITNESS),
    ]
    outcomes = gate_runner.evaluate(rules, b"{}")
    assert not witness_ran.exists() and outcomes[-1].ran is False
    assert gate_runner.report(outcomes) == 2
    err = capsys.readouterr()
    assert err.err == "x refuses\nz refuses\n" and err.out == ""


def test_a_consulted_refusal_skips_the_witness_and_is_not_reported(tmp_path, capsys):
    witness_ran = tmp_path / "witness"
    rules = [Rule("c", _hook(tmp_path, "c.py", "print('c out'); sys.stderr.write('c refuses\\n'); sys.exit(2)\n"),
                  CONSULT),
             Rule("w", _hook(tmp_path, "w.py", f"open({str(witness_ran)!r}, 'w')\n"), WITNESS)]
    outcomes = gate_runner.evaluate(rules, b"{}")
    assert not witness_ran.exists() and outcomes[-1].ran is False
    assert gate_runner.report(outcomes) == 0
    assert capsys.readouterr() == ("", "")
    with pytest.raises(ValueError):
        gate_runner.check_order(list(reversed(rules)))


def test_each_rule_has_its_own_try_and_its_own_stdin(tmp_path):
    rules = [
        Rule("boom", _hook(tmp_path, "boom.py", "raise ValueError('rule bug')\n")),
        Rule("reads", _hook(tmp_path, "reads.py",
                            "d = json.load(sys.stdin); sys.stderr.write(d['k']); sys.exit(2 if d['k'] else 0)\n")),
    ]
    outcomes = gate_runner.evaluate(rules, json.dumps({"k": "seen"}).encode())
    assert outcomes[0].code == 1 and "ValueError: rule bug" in outcomes[0].stderr
    assert outcomes[1].refused and outcomes[1].stderr == "seen"


def test_a_child_process_output_is_captured_with_its_rule(tmp_path):
    rule = Rule("child", _hook(tmp_path, "child.py",
                               "import subprocess; subprocess.run(['sh', '-c', 'echo child-err >&2'])\n"))
    (outcome,) = gate_runner.evaluate([rule], b"")
    assert outcome.stderr == "child-err\n"


def test_a_non_blocking_error_stays_one_when_nothing_refuses(tmp_path):
    rules = [Rule("boom", _hook(tmp_path, "boom.py", "raise ValueError('x')\n")),
             Rule("ok", _hook(tmp_path, "ok.py", "pass\n"))]
    assert gate_runner.report(gate_runner.evaluate(rules, b"")) == 1


def _ctx(text):
    return ("print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse', "
            f"'additionalContext': {text!r}}}}}))\n")


def test_contexts_merge_into_one_object_and_follow_a_refusal(tmp_path, capsys):
    a = Rule("a", _hook(tmp_path, "a.py", _ctx("first")), OBSERVE)
    b = Rule("b", _hook(tmp_path, "b.py", _ctx("second") + "print('plain line')\n"), OBSERVE)
    assert gate_runner.report(gate_runner.evaluate([a], b"")) == 0
    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"] == "first"
    c = Rule("c", _hook(tmp_path, "c.py", _ctx("third")), OBSERVE)
    assert gate_runner.report(gate_runner.evaluate([a, c], b"")) == 0
    out = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert out == {"hookEventName": "PostToolUse", "additionalContext": "first\nthird"}
    r = Rule("r", _hook(tmp_path, "r.py", "sys.stderr.write('refused\\n'); sys.exit(2)\n"))
    assert gate_runner.report(gate_runner.evaluate([a, r], b"")) == 2
    assert capsys.readouterr().err == "refused\nfirst\n"
    assert gate_runner._context(gate_runner.run_rule(b, b"").stdout) is None  # two lines: not one object


@pytest.fixture
def rules_module(tmp_path, monkeypatch):
    """A function-rule module, importable as the gates import hooks/lib modules."""
    (tmp_path / "l5_rules_fixture.py").write_text(
        "import sys\n"
        "def refuse(p):\n    return ['reason one: ' + str(p.get('k')), 'reason two'] if p.get('k') else []\n"
        "def advise(p):\n    print('stray print')\n    return ['look at ' + str(p.get('k'))]\n"
        "def boom(p):\n    raise RuntimeError('rule bug')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    yield "l5_rules_fixture"
    sys.modules.pop("l5_rules_fixture", None)


def test_a_function_rule_refuses_by_returning_its_reasons(rules_module, capsys):
    rule = Rule("f", call=f"{rules_module}:refuse")
    assert gate_runner.report(gate_runner.evaluate([rule], b'{"k": "x"}')) == 2
    assert capsys.readouterr().err == "reason one: x\nreason two\n"
    assert gate_runner.report(gate_runner.evaluate([rule], b"{}")) == 0


def test_an_advise_rule_reaches_the_agent_and_never_blocks(rules_module, capsys):
    raw = b'{"k": "y", "hook_event_name": "PreToolUse"}'
    rules = [Rule("a", call=f"{rules_module}:advise", kind=ADVISE),
             Rule("b", call=f"{rules_module}:boom", kind=ADVISE)]
    outcomes = gate_runner.evaluate(rules, raw)
    assert outcomes[1].code == 1 and "RuntimeError: rule bug" in outcomes[1].stderr
    assert gate_runner.report(outcomes) == 0
    printed = capsys.readouterr()
    assert json.loads(printed.out) == {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                             "additionalContext": "look at y"}}
    assert "stray print" in printed.err


def test_a_refuse_function_that_raises_is_a_non_blocking_error(rules_module):
    (outcome,) = gate_runner.evaluate([Rule("b", call=f"{rules_module}:boom")], b"{}")
    assert outcome.code == 1 and not outcome.refused


def test_a_rule_names_a_file_or_a_function(tmp_path):
    ok = _hook(tmp_path, "ok.py", "pass\n")
    for bad in (Rule("none"), Rule("both", path=ok, call="m:f")):
        with pytest.raises(ValueError):
            gate_runner.check_order([bad])


def test_a_refuse_rule_after_a_witness_is_rejected(tmp_path):
    ok = _hook(tmp_path, "ok.py", "pass\n")
    with pytest.raises(ValueError):
        gate_runner.evaluate([Rule("w", ok, WITNESS), Rule("r", ok, REFUSE)], b"")


@pytest.mark.parametrize("gate", ["pretool-dispatch-gate.py", "subagentstop-producer-gate.py",
                                  "posttool-dispatch-record.py"])
def test_every_gate_rule_is_a_hook_file_and_in_a_valid_order(gate):
    rules = _rules(gate)
    gate_runner.check_order(rules)
    assert rules and all(Path(r.path).is_file() and Path(r.path).parent == HOOKS for r in rules)
    assert len({r.path for r in rules}) == len(rules)


# ---------------------------------------------------------------- the dispatch witness


@pytest.fixture
def env(tmp_path):
    state = tmp_path / "state"
    project = tmp_path / "project"
    state.mkdir()
    (project / "docs" / "dev").mkdir(parents=True)
    e = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "CP_ENFORCE"))}
    e.update(CLAUDE_STATE_DIR=str(state), CLAUDE_PROJECT_DIR=str(project), HOME=str(tmp_path / "home"),
             CLAUDE_OBLIGATION_GATE="block", CLAUDE_OBLIGATION_BARRIER="block", TMPDIR=str(tmp_path))
    (tmp_path / "home").mkdir()
    return e


def _analyst(prompt: str, **extra) -> dict:
    tool_input = {"subagent_type": "changelog-analyst", "prompt": prompt, "description": "commit",
                  "run_in_background": False}
    tool_input.update(extra)
    return {"session_id": "s-c7", "tool_name": "Agent", "hook_event_name": "PreToolUse", "tool_input": tool_input}


def _witnesses(env: dict) -> list:
    return sorted(p.name for p in Path(env["CLAUDE_STATE_DIR"]).glob("claude-commit-dispatch-*.json"))


def test_a_refused_dispatch_leaves_no_witness(env):
    """G1 refuses a malformed obligation block; alone, the attest hook would still
    have written its witness beside it."""
    payload = _analyst("Commit the task.\n<obligation v=\"1\">{not json</obligation>\n")
    alone = _run(str(HOOKS / "pretool-obligation-gate.py"), payload, env)
    assert alone.returncode == 2
    gate = _run(str(HOOKS / "pretool-dispatch-gate.py"), payload, env)
    assert gate.returncode == 2 and gate.stderr.strip() == alone.stderr.strip()
    assert _witnesses(env) == []
    assert _run(str(HOOKS / "pretool-commit-dispatch-attest.py"), payload, env).returncode == 0
    assert len(_witnesses(env)) == 1  # what the side-by-side registration left on disk


def test_a_dispatch_every_rule_lets_through_is_witnessed(env):
    gate = _run(str(HOOKS / "pretool-dispatch-gate.py"), _analyst("Commit the task."), env)
    assert gate.returncode == 0, gate.stderr
    (name,) = _witnesses(env)
    record = json.loads((Path(env["CLAUDE_STATE_DIR"]) / name).read_text())
    assert record["subagent_type"] == "changelog-analyst" and record["sid"] == "s-c7"


def test_a_dispatch_another_hook_refuses_leaves_no_witness(env):
    """The background rule refuses this dispatch from its own registration (the case where the
    orchestrator forgot run_in_background: false). The gate consults it: no witness is
    written, and the gate itself refuses nothing and repeats no reason."""
    payload = _analyst("Commit the task.")
    del payload["tool_input"]["run_in_background"]
    own = _run(str(HOOKS / "pretool-block-background-tasks.py"), payload, env)
    assert own.returncode == 2
    gate = _run(str(HOOKS / "pretool-dispatch-gate.py"), payload, env)
    assert gate.returncode == 0 and own.stderr.strip() not in gate.stderr
    assert _witnesses(env) == []


def test_a_witness_that_cannot_write_never_blocks(env):
    env = dict(env, CLAUDE_STATE_DIR=str(Path(env["CLAUDE_STATE_DIR"]) / "missing" / "deeper"))
    Path(env["CLAUDE_STATE_DIR"]).parent.mkdir()
    Path(env["CLAUDE_STATE_DIR"]).parent.chmod(0o500)
    try:
        gate = _run(str(HOOKS / "pretool-dispatch-gate.py"), _analyst("Commit the task."), env)
    finally:
        Path(env["CLAUDE_STATE_DIR"]).parent.chmod(0o700)
    assert gate.returncode == 0, gate.stderr


# ---------------------------------------------------------------- differential: gate vs its hooks alone


def _rules(gate: str) -> list:
    ns = {"__name__": "gate", "__file__": str(HOOKS / gate)}
    exec(compile((HOOKS / gate).read_text(), str(HOOKS / gate), "exec"), ns)
    return ns["RULES"]


def _differential(gate: str, payload: dict, env: dict, unstated: tuple = ()):
    """The gate refuses exactly when one of its refuse rules alone refuses, and states
    every refusing rule's reason, except the rules in `unstated` (stated by another)."""
    alone = {r.name: _run(r.path, payload, env) for r in _rules(gate) if r.kind == REFUSE}
    merged = _run(str(HOOKS / gate), payload, env)
    refusing = {k: p for k, p in alone.items() if p.returncode == 2}
    assert (merged.returncode == 2) == bool(refusing), (merged.stderr, {k: v.stderr for k, v in alone.items()})
    for name, p in refusing.items():
        assert (p.stderr.strip() in merged.stderr) == (name not in unstated), (name, merged.stderr)
    return merged, alone


DISPATCHES = [
    {},
    {"tool_name": "Read", "tool_input": {"file_path": "/x"}},
    {"session_id": "s", "tool_name": "Agent", "tool_input": {"subagent_type": "dev", "prompt": "do it"}},
    {"session_id": "s", "tool_name": "Agent",
     "tool_input": {"subagent_type": "dev", "prompt": "x\n<obligation v=\"1\">{\"role\": \"qa\"}</obligation>"}},
    {"session_id": "s", "tool_name": "Agent",
     "tool_input": {"subagent_type": "qa", "prompt": "verify\n<obligation v=\"1\">[]</obligation>"}},
]


@pytest.mark.parametrize("payload", DISPATCHES)
@pytest.mark.parametrize("gate_mode", ["block", "advisory"])
def test_the_dispatch_gate_decides_as_its_hooks_alone(env, payload, gate_mode):
    _differential("pretool-dispatch-gate.py", payload,
                  dict(env, CLAUDE_OBLIGATION_GATE=gate_mode, CLAUDE_OBLIGATION_BARRIER=gate_mode))


STOPS = [
    {},
    {"session_id": "s", "hook_event_name": "SubagentStop"},
    {"session_id": "s", "hook_event_name": "SubagentStop", "agent_id": "a1", "agent_type": "qa",
     "last_assistant_message": "done"},
    {"session_id": "s", "hook_event_name": "SubagentStop", "agent_id": "a2", "agent_type": "dev",
     "last_assistant_message": "done"},
]


@pytest.mark.parametrize("payload", STOPS)
def test_the_producer_gate_decides_as_its_hooks_alone(env, payload):
    _differential("subagentstop-producer-gate.py", payload, dict(env, CP_ENFORCE_MODE="block",
                                                                 CLAUDE_OBLIGATION_STOPGATE="block"))


def _qa_stop_with_three_refusals(project: Path, agent_id: str = "agent-qa-9") -> dict:
    """A QA whose own obligation declares a qa-report.v2 it never wrote, and whose own
    cp-state slot still has a pending checkpoint."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    task = "20261109-010101"
    registry = project / ".claude" / "dev-registry"
    registry.mkdir(parents=True, exist_ok=True)
    (registry / "agent-index.json").write_text(json.dumps(
        {agent_id: {"agent_type": "qa", "dev_session_id": "dev-" + task}}))
    (registry / ("dev-" + task)).mkdir()
    (registry / ("dev-" + task) / "e2e-enforce.json").write_text(json.dumps({"enabled": True}))
    spec = project / ".claude" / "specs" / "sp1"
    spec.mkdir(parents=True)
    (spec / "cp-state-qa.json").write_text(json.dumps({
        "spec_id": "sp1", "agent_type": "qa", "agent_id": agent_id, "is_running": True,
        "checked_in_at": now, "checked_out_at": None, "checkpoints": [{"id": "cp-01", "state": "pending"}]}))
    doc = {"task_id": task, "role": "qa", "pipeline": "dev", "profile": "final_verification",
           "dispatched_at": now, "artifacts": [{"kind": "json", "path": f"docs/dev/qa-report-{task}.json",
                                                "schema": "qa-report.v2", "identity": {"task_id": task}}]}
    transcript = project / "transcripts" / f"agent-{agent_id}.jsonl"
    transcript.parent.mkdir(parents=True)
    prompt = f'<obligation v="1">\n{json.dumps(doc)}\n</obligation>\nYou are the QA subagent.'
    transcript.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
    return {"session_id": "s", "hook_event_name": "SubagentStop", "agent_id": agent_id, "agent_type": "qa",
            "agent_transcript_path": str(transcript), "last_assistant_message": "done"}


def test_the_producer_gate_reports_every_refusal_once(env):
    """One stop meets the e2e, G2 and cp refusals; the gate states each fact once, in
    one round, where the three hooks used to answer side by side. The missing QA
    report is stated by G2, which names it; the e2e rule still refuses."""
    payload = _qa_stop_with_three_refusals(Path(env["CLAUDE_PROJECT_DIR"]))
    merged, alone = _differential("subagentstop-producer-gate.py", payload,
                                  dict(env, CP_ENFORCE_MODE="block", CLAUDE_OBLIGATION_STOPGATE="block"),
                                  unstated=("qa-e2e",))
    assert {k for k, p in alone.items() if p.returncode == 2} == {"qa-e2e", "g2-artifact-contract", "cp-pending"}
    assert merged.returncode == 2
    assert "E2E_ENFORCE_BLOCKED" not in merged.stderr
    for marker in ("OBLIGATION_STOPGATE_BLOCKED", "obligation-named artifact absent",
                   "subagentstop-cp-enforce: BLOCKED"):
        assert merged.stderr.count(marker) == 1, merged.stderr


@pytest.mark.parametrize("stopgate", ["advisory", "off"])
def test_the_producer_gate_keeps_each_rules_switch(env, stopgate):
    """G2's switch still governs G2 alone: with it advisory or off, the e2e and cp
    refusals still return the stop to the QA."""
    payload = _qa_stop_with_three_refusals(Path(env["CLAUDE_PROJECT_DIR"]))
    merged, alone = _differential("subagentstop-producer-gate.py", payload,
                                  dict(env, CP_ENFORCE_MODE="block", CLAUDE_OBLIGATION_STOPGATE=stopgate))
    assert alone["g2-artifact-contract"].returncode == 0 and merged.returncode == 2
    assert "OBLIGATION_STOPGATE_BLOCKED" not in merged.stderr
    assert merged.stderr.count("E2E_ENFORCE_BLOCKED") == 1  # the e2e rule states it alone


@pytest.mark.parametrize("payload", DISPATCHES[:3])
def test_the_dispatch_record_decides_as_its_hooks_alone(env, payload):
    _differential("posttool-dispatch-record.py", dict(payload, hook_event_name="PostToolUse",
                                                       tool_response={"content": "done"}), env)
