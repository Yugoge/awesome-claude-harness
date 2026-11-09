"""hooks/pretool-write-gate.py: one PreToolUse decision on writes, the seven guards' rules in one process.

- The gate sees what the guards saw: each rule's tool set is its guard's registered matcher.
- Differential: on one corpus (Write, Edit, NotebookEdit, Bash, Read, Agent, AskUserQuestion; the
  main agent and subagents of several roles; /do consent, an /allow grant, the hook-refactor
  sentinel; existing and new files; payloads that do not parse) the gate refuses exactly when one
  of the guards, run as the CLI ran them, refuses; its message is their refusals in rule order;
  otherwise it allows with the same rewrite (updatedInput).
- Each rule runs in its own try: a rule that raises or overruns its budget fails in its declared
  direction (open: the call goes on and the user is told; closed: refused), another rule's refusal
  still stands, and a rule's change to the environment or working directory does not reach the next.
- Declared actor scopes and exemptions hold on each rule's own refusing input.
- pretool-subagent-code-block.py is not a rule: tool-policy refuses every non-dev role's code write
  (its lesson's home), and the shim only printed a warning nobody saw.
- Each rule's measured time stays well inside its budget.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(HOOKS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import write_gate  # noqa: E402
from lib.rule_runner import RuleRun, run_rule  # noqa: E402
import write_gate_settings  # noqa: E402

SID = "sess-write-gate"
OUTSIDE = "/nonexistent-l4-write-gate/proj"  # a project path outside /tmp: role rows, not the raw-temp rule, decide
NON_DEV_ROLES = ("user", "ui-specialist", "ba", "qa", "pm", "architect", "product-owner", "cleaner",
                 "cleanliness-inspector", "git-edge-case-analyst", "prompt-inspector", "rule-inspector",
                 "style-inspector", "test-writer", "test-executor", "test-validator", "spec",
                 "changelog-analyst", "push-analyst", "merge-analyst", "pull-analyst", "graphify")


def _settings() -> dict:
    return json.loads((ROOT / "settings.json").read_text())


def _old_registrations():
    """(matcher, command, timeout) of the seven guards, in settings.json order."""
    out = []
    for group in _settings()["hooks"]["PreToolUse"]:
        for h in group["hooks"]:
            if write_gate_settings._replaced(h.get("command", "")):
                out.append((group.get("matcher", "*"), h["command"], h.get("timeout", 60)))
    return out


def _matches(matcher, tool) -> bool:
    if matcher in (None, "", "*"):
        return True
    return tool in matcher.split("|")


class Lab:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.state = tmp_path / "state"
        self.proj = tmp_path / "proj"
        for d in (self.home / ".claude", self.state / "claude-grants", self.proj / ".claude" / "hooks",
                  self.proj / "docs" / "dev" / "specs" / "s1" / "views", self.proj / "src"):
            d.mkdir(parents=True, exist_ok=True)
        (self.proj / "existing.txt").write_text("old\n")
        (self.proj / ".claude" / "hooks" / "h.sh").write_text("#!/bin/sh\n")
        subprocess.run(["git", "init", "-q", str(self.proj)], check=True)

    def env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
        env.update(HOME=str(self.home), CLAUDE_STATE_DIR=str(self.state), CLAUDE_HOME=str(ROOT),
                   CLAUDE_PROJECT_DIR=str(self.proj), PYTHONDONTWRITEBYTECODE="1")
        return env

    def consent(self, on: bool) -> None:
        flag = self.state / f"claude-orchestrator-consent-{SID}.flag"
        if on:
            flag.write_text("true\n")
        elif flag.exists():
            flag.unlink()

    def grant(self, target: str | None) -> None:
        g = self.state / "claude-grants" / f"{SID}.json"
        if target is None:
            if g.exists():
                g.unlink()
            return
        g.write_text(json.dumps({"task_id": SID, "session_id": SID,
                                 "allowed_operations": [{"op": "Write", "target": target}],
                                 "created_at": int(time.time()), "expires_at": int(time.time()) + 300}))

    def refactor_sentinel(self, on: bool) -> None:
        s = self.proj / ".claude" / ".hook-refactor-allow"
        if on:
            s.write_text("")
        elif s.exists():
            s.unlink()

    def run(self, command: str, raw: str, timeout: float = 70):
        p = subprocess.run(["bash", "-c", command], input=raw, capture_output=True, text=True,
                           env=self.env(), cwd=self.proj, timeout=timeout)
        return p.returncode, p.stdout, p.stderr


def _payload(tool: str, tool_input: dict, agent: str | None = None) -> str:
    d = {"tool_name": tool, "session_id": SID, "hook_event_name": "PreToolUse", "tool_input": tool_input}
    if agent:
        d.update(agent_id="a-" + agent, agent_type=agent)
    return json.dumps(d)


def _corpus(lab: Lab):
    p = lab.proj
    calls = [
        ("Write", {"file_path": str(p / "existing.txt"), "content": "x"}),
        ("Write", {"file_path": str(p / "new.txt"), "content": "x"}),
        ("Write", {"file_path": str(lab.state / "claude-bulk-commit-sentinel-s-n.json"), "content": "{}"}),
        ("NotebookEdit", {"notebook_path": str(lab.state / "claude-bulk-commit-sentinel-s-n.json")}),
        ("Edit", {"file_path": str(p / ".claude" / "hooks" / "h.sh"), "old_string": "a", "new_string": "b"}),
        ("Write", {"file_path": str(p / ".claude" / "commands" / "c.md"), "content": "x"}),
        ("Bash", {"command": "echo x > docs/dev/specs/s1/views/a.md"}),
        ("Bash", {"command": f"python3 {ROOT}/.claude/scripts/spec-check.py > docs/dev/specs/s1/views/a.md"}),
        ("Bash", {"command": "echo x > .claude/specs/s1/cp-state-a.json"}),
        ("Bash", {"command": "echo x > .claude/hooks/h.sh"}),
        ("Bash", {"command": "echo hello"}),
        ("Write", {"file_path": str(p / ".claude" / "specs" / "s1" / "cp-state-a.json"), "content": "{}"}),
        ("Write", {"file_path": f"{OUTSIDE}/src/app.py", "content": "x"}),
        ("Edit", {"file_path": f"{OUTSIDE}/docs/notes.md", "old_string": "a", "new_string": "b"}),
        ("Read", {"file_path": "/etc/hosts"}),
        ("Agent", {"description": "d", "prompt": "p", "subagent_type": "qa"}),
        ("AskUserQuestion", {"questions": []}),
    ]
    for tool, ti in calls:
        for agent in (None, "dev", "qa"):
            yield _payload(tool, ti, agent)
    yield "{not json"
    yield json.dumps({"tool_name": "Write", "session_id": SID, "tool_input": "not-a-dict"})


def _old(lab: Lab, raw: str):
    """The guards as the CLI ran them: every matching registration; deny wins."""
    try:
        tool = json.loads(raw).get("tool_name")
    except (ValueError, AttributeError):
        tool = None
    refusals, updated, errors = [], None, []
    for matcher, command, timeout in _old_registrations():
        if tool is not None and not _matches(matcher, tool):
            continue
        rc, out, err = lab.run(command, raw, timeout)
        decision = write_gate._decision(write_gate._json(out) or {}) if rc in (0, 2) else (None, "")
        if rc == 2 or decision[0] == "deny":
            refusals.append(decision[1] or err)
        elif rc == 0:
            hso = (write_gate._json(out) or {}).get("hookSpecificOutput") or {}
            if updated is None and isinstance(hso.get("updatedInput"), dict):
                updated = hso["updatedInput"]
        else:
            errors.append(rc)
    return refusals, updated, errors


@pytest.fixture
def lab(tmp_path):
    return Lab(tmp_path)


def test_each_rule_sees_the_tools_its_guard_was_registered_for():
    registered = {}
    for matcher, command, _ in _old_registrations():
        name = command.rstrip('"').rsplit("/", 1)[-1]
        registered[name] = None if matcher in ("", "*") else frozenset(matcher.split("|"))
    by_file = {Path(r.path).name: r for r in write_gate.RULES}
    assert registered.pop("pretool-write-guard.sh") == by_file.pop("overwrite.py").tools
    assert registered.pop("pretool-subagent-code-block.py") is not None  # not a rule: see below
    assert {k: v for k, v in registered.items()} == {k: r.tools for k, r in by_file.items()}
    assert [r.name for r in write_gate.RULES] == ["bash-views", "overnight-boundary", "tool-policy",
                                                  "cp-state", "overwrite", "claude-config"]
    assert all(Path(r.file).is_file() for r in write_gate.RULES)


def test_the_scratch_settings_register_the_gate_once_and_no_guard():
    s = write_gate_settings.gate_settings(_settings())
    commands = [(g.get("matcher"), h["command"]) for g in s["hooks"]["PreToolUse"] for h in g["hooks"]]
    assert [c for c in commands if "write-gate" in c[1]] == [("*", write_gate_settings.GATE_COMMAND)]
    assert not any(write_gate_settings._replaced(c[1]) for c in commands)
    before = sum(len(g["hooks"]) for g in _settings()["hooks"]["PreToolUse"])
    assert len(commands) == before - 7 + 1
    assert s["hooks"]["PostToolUse"] == _settings()["hooks"]["PostToolUse"]


@pytest.mark.parametrize("setup", ["plain", "consent", "grant", "refactor-sentinel"])
def test_the_gate_refuses_exactly_when_a_guard_refused(lab, setup):
    lab.consent(setup == "consent")
    lab.grant(str(lab.proj / "existing.txt") if setup == "grant" else None)
    lab.refactor_sentinel(setup == "refactor-sentinel")
    gate = write_gate_settings.GATE_COMMAND
    refused = allowed = 0
    for raw in _corpus(lab):
        refusals, updated, errors = _old(lab, raw)
        rc, out, err = lab.run(gate, raw)
        if refusals:
            assert rc == 2, (raw, err)
            assert err == "".join(r if r.endswith("\n") else r + "\n" for r in refusals), raw
            refused += 1
        else:
            assert rc == (1 if errors else 0), (raw, rc, err)
            hso = (json.loads(out).get("hookSpecificOutput") or {}) if out.strip() else {}
            assert hso.get("updatedInput") == updated, raw
            allowed += 1
    assert refused >= 10 and allowed >= 10, (refused, allowed)


def _rule_file(tmp_path: Path, name: str, body: str) -> str:
    path = tmp_path / f"{name}.py"
    path.write_text("import json, os, sys, time\n" + textwrap.dedent(body))
    return str(path)


def _rule(name, path, fail="open", budget=2.0):
    return write_gate.Rule(name, path, None, "both", fail, (), budget)


def test_a_rule_that_raises_fails_in_its_direction_and_others_still_decide(tmp_path):
    raises = _rule_file(tmp_path, "raises", "raise BaseException('boom')\n")
    refuses = _rule_file(tmp_path, "refuses", "sys.stderr.write('no\\n'); sys.exit(2)\n")
    allows = _rule_file(tmp_path, "allows", "sys.exit(0)\n")
    raw = b"{}"
    run = lambda path: run_rule(path, raw, 2.0)  # noqa: E731
    a = write_gate.combine([(_rule("r", raises, "open"), run(raises)), (_rule("a", allows), run(allows))])
    assert (a.code, a.stdout) == (1, "") and "rule r BaseException: boom" in a.stderr and "fails open" in a.stderr
    a = write_gate.combine([(_rule("r", raises, "closed"), run(raises)), (_rule("a", allows), run(allows))])
    assert a.code == 2 and "rule r BaseException: boom" in a.stderr and "fails closed" in a.stderr
    a = write_gate.combine([(_rule("r", raises, "open"), run(raises)), (_rule("n", refuses), run(refuses))])
    assert (a.code, a.stderr) == (2, "no\n")


def test_a_rule_past_its_budget_is_stopped_and_fails_in_its_direction(tmp_path):
    slow = _rule_file(tmp_path, "slow", "time.sleep(30)\n")
    start = time.monotonic()
    run = run_rule(slow, b"{}", 0.3)
    assert time.monotonic() - start < 5 and run.overrun and "0.3 s budget" in run.error
    assert write_gate.combine([(_rule("s", slow, "open", 0.3), run)]).code == 1
    assert write_gate.combine([(_rule("s", slow, "closed", 0.3), run)]).code == 2


def test_a_rule_that_swallows_exceptions_cannot_swallow_its_overrun(tmp_path):
    stubborn = _rule_file(tmp_path, "stubborn", """
        while True:
            try:
                time.sleep(30)
            except Exception:
                pass
        """)
    assert run_rule(stubborn, b"{}", 0.3).overrun


def test_one_rule_cannot_change_what_the_next_one_sees(tmp_path):
    mutate = _rule_file(tmp_path, "mutate", """
        os.environ['WG_LEAK'] = '1'; os.chdir('/'); sys.argv.append('x'); sys.path.insert(0, '/leak')
        print('out'); sys.stderr.write('err'); sys.exit(0)
        """)
    look = _rule_file(tmp_path, "look", """
        data = json.load(sys.stdin)
        print(json.dumps([os.environ.get('WG_LEAK'), os.getcwd(), sys.argv[1:], '/leak' in sys.path, data]))
        """)
    cwd = os.getcwd()
    first = run_rule(mutate, b'{"a": 1}', 2.0)
    second = run_rule(look, b'{"a": 1}', 2.0)
    assert (first.code, first.stdout, first.stderr) == (0, "out\n", "err")
    assert json.loads(second.stdout) == [None, cwd, [], False, {"a": 1}]
    assert os.getcwd() == cwd and "WG_LEAK" not in os.environ


def test_child_process_output_is_captured_per_rule(tmp_path):
    child = _rule_file(tmp_path, "child", """
        import subprocess
        subprocess.run(['sh', '-c', 'echo from-child; echo child-err >&2'])
        sys.exit(2)
        """)
    run = run_rule(child, b"{}", 5.0)
    assert (run.code, run.stdout, run.stderr) == (2, "from-child\n", "child-err\n")


def test_decisions_combine_as_the_cli_combines_parallel_hooks():
    def r(code, out="", err=""):
        return RuleRun(code, out, err)

    def j(**hso):
        return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", **hso}})

    rule = _rule("x", "x")
    ask = r(0, j(permissionDecision="ask", permissionDecisionReason="confirm"))
    rewrite = r(0, j(updatedInput={"command": "bwrap ..."}))
    deny = r(0, j(permissionDecision="deny", permissionDecisionReason="denied"))
    a = write_gate.combine([(rule, ask), (rule, rewrite)])
    hso = json.loads(a.stdout)["hookSpecificOutput"]
    assert (a.code, hso["permissionDecision"], hso["updatedInput"]) == (0, "ask", {"command": "bwrap ..."})
    a = write_gate.combine([(rule, ask), (rule, deny), (rule, r(2, "", "second\n"))])
    assert (a.code, a.stderr) == (2, "denied\nsecond\n")
    a = write_gate.combine([(rule, rewrite)])
    assert json.loads(a.stdout)["hookSpecificOutput"] == {"hookEventName": "PreToolUse",
                                                         "updatedInput": {"command": "bwrap ..."}}
    assert write_gate.combine([(rule, r(0, "plain text"))]).code == 0
    assert write_gate.combine([(rule, r(1, "", "oops\n"))]).stderr == "oops\n"


def _rule_by_name(name: str):
    return next(r for r in write_gate.RULES if r.name == name)


def test_declared_actor_scopes_hold_on_each_rules_refusing_input(lab):
    """A rule declared for subagents lets the main agent through on the input it refuses a subagent."""
    for rule in write_gate.RULES:
        assert rule.actors in ("main", "subagent", "both") and rule.fail in ("open", "closed")
        assert rule.exemptions and 0 < rule.budget <= 20
    cp = _rule_by_name("cp-state")
    target = {"file_path": str(lab.proj / ".claude" / "specs" / "s1" / "cp-state-a.json"), "content": "{}"}
    env = lab.env()
    old = os.environ.copy()
    os.environ.update(env)
    try:
        sub = run_rule(cp.file, _payload("Write", target, "qa").encode(), cp.budget)
        main = run_rule(cp.file, _payload("Write", target).encode(), cp.budget)
    finally:
        os.environ.clear()
        os.environ.update(old)
    assert (sub.code, main.code) == (2, 0), (sub.stderr, main.stderr)


def test_exemptions_are_each_rules_own(lab):
    """/do consent lets the main agent's overwrite through, never the bulk-commit sentinel."""
    gate = write_gate_settings.GATE_COMMAND
    lab.consent(True)
    rc, _, _ = lab.run(gate, _payload("Write", {"file_path": str(lab.proj / "existing.txt"), "content": "x"}))
    assert rc == 0
    rc, _, err = lab.run(gate, _payload("Write", {"file_path": str(lab.state / "claude-bulk-commit-sentinel-a.json")}))
    assert rc == 2 and err.startswith("BLOCKED: bulk-commit-sentinel-write")
    lab.consent(False)
    rc, _, err = lab.run(gate, _payload("Edit", {"file_path": str(lab.proj / ".claude" / "hooks" / "h.sh"),
                                                 "old_string": "a", "new_string": "b"}))
    assert rc == 2 and "claude config guard" in err
    lab.refactor_sentinel(True)
    rc, _, _ = lab.run(gate, _payload("Edit", {"file_path": str(lab.proj / ".claude" / "hooks" / "h.sh"),
                                               "old_string": "a", "new_string": "b"}))
    assert rc == 0


@pytest.mark.parametrize("role", NON_DEV_ROLES)
def test_tool_policy_refuses_every_non_dev_roles_code_write(lab, role):
    """The lesson pretool-subagent-code-block.py stated ("only dev writes source code") lives here."""
    tool_policy = HOOKS / "pretool-tool-policy.py"
    for target in ("src/app.py", "web/view.tsx", "docs/style.css"):
        raw = _payload("Write", {"file_path": f"{OUTSIDE}/{target}", "content": "x"}, role)
        rc, _, err = lab.run(f'python3 "{tool_policy}"', raw)
        assert rc == 2, (role, target, err)
    rc, _, err = lab.run(f'python3 "{tool_policy}"', _payload("Write", {"file_path": f"{OUTSIDE}/src/app.py"}, "dev"))
    assert rc == 0, err


def test_budgets_cover_the_measured_times(lab):
    """Each rule's slowest call on the corpus stays under a fifth of its budget."""
    env = lab.env()
    old = os.environ.copy()
    os.environ.update(env)
    cwd = os.getcwd()
    os.chdir(lab.proj)
    worst = {r.name: 0.0 for r in write_gate.RULES}
    try:
        for raw in _corpus(lab):
            try:
                tool = json.loads(raw).get("tool_name")
            except (ValueError, AttributeError):
                tool = None
            for rule in write_gate.RULES:
                if rule.applies(tool):
                    worst[rule.name] = max(worst[rule.name], run_rule(rule.file, raw.encode(), rule.budget).seconds)
    finally:
        os.chdir(cwd)
        os.environ.clear()
        os.environ.update(old)
    print("slowest call per rule (s):", {k: round(v, 3) for k, v in worst.items()})
    for rule in write_gate.RULES:
        assert worst[rule.name] < rule.budget / 5, (rule.name, worst[rule.name])
    assert sum(r.budget for r in write_gate.RULES) < write_gate_settings.GATE_TIMEOUT


def test_the_fallback_answers_as_the_gate(lab, monkeypatch):
    """If the gate's own code fails before a rule runs, each rule runs as its own process instead."""
    gate = HOOKS / "pretool-write-gate.py"
    probe = textwrap.dedent(f"""
        import importlib.util, io, sys
        spec = importlib.util.spec_from_file_location('gate', {str(gate)!r})
        gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
        raw = sys.stdin.buffer.read()
        sys.exit(gate._fallback(raw))
        """)
    for raw in list(_corpus(lab))[::3]:
        expected = lab.run(write_gate_settings.GATE_COMMAND, raw)
        got = subprocess.run([sys.executable, "-c", probe], input=raw, capture_output=True, text=True,
                             env=lab.env(), cwd=lab.proj, timeout=120)
        assert (got.returncode, got.stdout, got.stderr) == expected, raw


def test_l4s_whole_registration_change():
    """The registration change L4 asks the integration lane for (hooks/tests/write_gate_settings.py)."""
    base = _settings()
    s = write_gate_settings.l4_settings(base)
    regs = [(event, g.get("matcher"), h["command"]) for event, groups in s["hooks"].items()
            for g in groups for h in g["hooks"]]
    gone = write_gate_settings.REPLACED + write_gate_settings.ANTI_LOOP + write_gate_settings.STUBS
    assert not [r for r in regs if write_gate_settings._names(r[2], gone)]
    dev_loop = [(e, m) for e, m, c in regs if c == write_gate_settings.DEV_LOOP_COMMAND]
    assert dev_loop == [("PreToolUse", "Agent"), ("PostToolUse", "Agent")]
    assert [m for e, m, c in regs if c.rstrip('"').endswith("/posttool-git-warn.sh")] == ["Bash"]
    before = sum(len(g["hooks"]) for groups in base["hooks"].values() for g in groups)
    assert len(regs) == before - 7 + 1 - 5 + 2 - 3
    for _, _, command in regs:  # every registered file exists
        path = command.split('$HOME/.claude}/')[-1].rstrip('"')
        assert (ROOT / path).is_file(), command
