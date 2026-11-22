"""The deny-list rule refuses when it cannot give its verdict, and names why; the permission-request hook reads the
same list through the same function.

What the launcher does with a rule that cannot answer (lib/hook_launch.py, "Failure direction"): a rule past its Rule
timeout is a non-blocking error, and the call goes on; so does an uncaught error (exit 1). The CLI does the same
with the launcher itself when it errors or runs past its registered timeout. hooks/pretool-deny-list.py therefore
keeps its own deadline (DEADLINE, below its Rule timeout) and refuses (exit 2) on a deadline, a read failure or a
fault, the refusal naming the step and the cause. The first test pins the launcher's side as it is; the others run
a copy of the rule's few files (hooks/pretool-deny-list.py, hooks/lib/deny_list.py) whose list or matcher is made to
hang, to be unreadable or to fail, the slow ones through the launcher with the rule's real timeout.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HOOKS = REPO / "hooks"
COPIED = ("pretool-deny-list.py", "lib/deny_list.py", "lib/claude_home.py", "lib/harness_switch.py", "lib/__init__.py")
PAYLOAD = {"hook_event_name": "PreToolUse", "session_id": "sess-0001", "tool_name": "Bash",
           "tool_input": {"command": "ls"}, "tool_use_id": "toolu_noverdict_1"}


def _rule_timeout() -> float:
    spec = importlib.util.spec_from_file_location("_pretool_launch_table", HOOKS / "pretool-launch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # its __main__ guard keeps it from running
    return next(r.timeout for r in mod.RULES if r.path == "pretool-deny-list.py")


def _load_rule():
    spec = importlib.util.spec_from_file_location("_pretool_deny_list", HOOKS / "pretool-deny-list.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def env(tmp_path):
    state, home, proj = tmp_path / "state", tmp_path / "home", tmp_path / "proj"
    for d in (state, home, proj):
        d.mkdir()
    e = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "CODEX_"))}
    e.update(CLAUDE_STATE_DIR=str(state), HOME=str(home), CLAUDE_SESSION_ID="sess-0001",
             CLAUDE_PROJECT_DIR=str(proj), PYTHONDONTWRITEBYTECODE="1")
    return {"env": e, "proj": proj, "tmp": tmp_path}


def _copy(tmp_path, matcher_tail: str = "") -> Path:
    """A harness home holding the rule's own files, a settings.json with no deny entry and the real policy file;
    ``matcher_tail`` is appended to the copied hooks/lib/deny_list.py."""
    home = tmp_path / "copy"
    (home / "hooks" / "lib").mkdir(parents=True)
    (home / "policies").mkdir()
    for name in COPIED:
        if (HOOKS / name).exists():
            (home / "hooks" / name).write_bytes((HOOKS / name).read_bytes())
    (home / "hooks" / "lib" / "deny_list.py").write_text((HOOKS / "lib" / "deny_list.py").read_text() + matcher_tail)
    (home / "settings.json").write_text(json.dumps({"permissions": {"deny": []}}))
    (home / "policies" / "cli-deny.v1.json").write_bytes((REPO / "policies" / "cli-deny.v1.json").read_bytes())
    return home


def _launch(env, rules: str) -> tuple[subprocess.CompletedProcess, float]:
    """The pre-tool launcher (lib/hook_launch.main) over ``rules`` (Rule(...) source; a path may be absolute)."""
    code = (f"import sys; sys.path.insert(0, {str(HOOKS)!r})\n"
            "from lib.hook_launch import Rule, main\n"
            f"sys.exit(main('PreToolUse', ({rules},)))\n")
    payload = dict(PAYLOAD, cwd=str(env["proj"]), transcript_path=str(env["tmp"] / "none.jsonl"))
    t0 = time.monotonic()
    p = subprocess.run([sys.executable, "-c", code], input=json.dumps(payload), capture_output=True, text=True,
                       env=env["env"], timeout=120)
    return p, time.monotonic() - t0


def _alone(env, home: Path) -> subprocess.CompletedProcess:
    payload = dict(PAYLOAD, cwd=str(env["proj"]))
    return subprocess.run([sys.executable, str(home / "hooks" / "pretool-deny-list.py")], input=json.dumps(payload),
                          capture_output=True, text=True, env=env["env"], timeout=120)


# ------------------------------------------------------------------ the launcher, as it is
def test_the_launcher_lets_a_call_go_on_past_a_rule_timeout(env, tmp_path):
    """Why the rule keeps its own deadline: a rule the launcher stops at its timeout does not refuse."""
    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text("import time\ntime.sleep(30)\n")
    p, _ = _launch(env, f"Rule('sleeper', {str(sleeper)!r}, ('Bash',), timeout=1)")
    assert p.returncode == 1 and "ran past its 1 s timeout" in p.stderr, (p.returncode, p.stderr)


def test_the_rule_answers_before_its_launcher_timeout():
    assert _load_rule().DEADLINE + 2 <= _rule_timeout()  # 2: the fork's grace past its overrun signal


# ------------------------------------------------------------------ no verdict: refused, the cause named
def _wrapper(tmp_path, patch: str) -> Path:
    """A rule file that patches lib/deny_list in its own run (the launcher's process has loaded the real lib/, so a
    copied deny_list.py would not be the one imported) and then runs the real hooks/pretool-deny-list.py."""
    w = tmp_path / "deny_rule_patched.py"
    w.write_text(f"import runpy, sys\nsys.path.insert(0, {str(HOOKS)!r})\nfrom lib import deny_list\n{patch}\n"
                 f"runpy.run_path({str(HOOKS / 'pretool-deny-list.py')!r}, run_name='__main__')\n")
    return w


def test_a_list_that_never_finishes_reading_is_refused_in_time(env, tmp_path):
    """The policy file a FIFO no one writes: the read hangs. Through the launcher, with the rule's real timeout
    and a second rule beside it (so it runs in a fork)."""
    fifo = tmp_path / "cli-deny.v1.json"
    os.mkfifo(fifo)
    rule = _wrapper(tmp_path, "_e = deny_list.entries\n"
                              f"deny_list.entries = lambda *a, **k: _e({str(fifo)!r}, settings=None)")
    other = tmp_path / "other_rule.py"
    other.write_text("import sys\nsys.exit(0)\n")
    p, took = _launch(env, f"Rule('deny-list', {str(rule)!r}, ('Bash',), timeout={_rule_timeout()}), "
                           f"Rule('other', {str(other)!r}, ('Bash',))")
    assert p.returncode == 2, (p.returncode, p.stderr)
    assert "ran out of time while reading the list" in p.stderr and "no verdict within" in p.stderr, p.stderr
    assert took < _rule_timeout(), took


def test_a_matcher_that_runs_past_the_deadline_is_refused(env, tmp_path):
    rule = _wrapper(tmp_path, "import time\ndeny_list.Policy.refusal = lambda self, payload: time.sleep(60)")
    p, took = _launch(env, f"Rule('deny-list', {str(rule)!r}, ('Bash',), timeout={_rule_timeout()})")
    assert p.returncode == 2 and "ran out of time while matching this call" in p.stderr, (p.returncode, p.stderr)
    assert took < _rule_timeout(), took


@pytest.mark.parametrize("damage,word", [("directory", "IsADirectoryError"), ("truncated", "JSONDecodeError")])
def test_an_unreadable_list_is_refused_naming_the_read(env, tmp_path, damage, word):
    home = _copy(tmp_path)
    policy = home / "policies" / "cli-deny.v1.json"
    if damage == "directory":
        policy.unlink()
        policy.mkdir()
    else:
        policy.write_text(policy.read_text()[:100])
    p = _alone(env, home)
    assert p.returncode == 2 and "reading the list" in p.stderr and word in p.stderr, (p.returncode, p.stderr)


def test_a_fault_in_the_matcher_is_refused_naming_the_match(env, tmp_path):
    home = _copy(tmp_path, "\n\ndef _boom(self, payload):\n    raise RuntimeError('neutral fault')\n\n\n"
                           "Policy.refusal = _boom\n")
    p = _alone(env, home)
    assert p.returncode == 2, (p.returncode, p.stderr)
    assert "matching this call failed (RuntimeError: neutral fault)" in p.stderr and "reading" not in p.stderr, p.stderr


# ------------------------------------------------------------------ one reader
def _answer_module():
    spec = importlib.util.spec_from_file_location("_permissionrequest_answer", HOOKS / "permissionrequest-answer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_permission_request_hook_reads_the_rules_list(monkeypatch):
    """Both readers take the list from lib/deny_list.entries: what it returns is what the hook finds in text."""
    sys.path.insert(0, str(HOOKS))
    try:
        from lib import deny_list
        ans = _answer_module()
        assert not ans.denied_in_text("x; neutralcmd --go")
        monkeypatch.setattr(deny_list, "entries", lambda *a, **k: [("Bash(neutralcmd:*)", "neutral purpose")])
        assert ans.denied_in_text("x; neutralcmd --go") == "Bash(neutralcmd:*)"
        assert deny_list.Policy(listed=deny_list.entries()).bash_entry("neutralcmd --go")[0] == "Bash(neutralcmd:*)"
    finally:
        sys.path.remove(str(HOOKS))


def test_the_permission_request_hook_denies_when_the_list_cannot_be_read(monkeypatch, capsys):
    sys.path.insert(0, str(HOOKS))
    try:
        from lib import deny_list
        ans = _answer_module()

        def unreadable(*a, **k):
            raise PermissionError("neutral: the list cannot be read")
        monkeypatch.setattr(deny_list, "entries", unreadable)
        monkeypatch.setattr(ans, "bash_rules", lambda payload: None)
        monkeypatch.setattr(ans, "record", lambda raw, message: None)
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
            {"hook_event_name": "PermissionRequest", "tool_name": "Bash", "permission_mode": "bypassPermissions",
             "tool_input": {"command": "ls"}})))
        assert ans.main() == 0
        decision = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["decision"]
        assert decision["behavior"] == "deny" and "PermissionError" in decision["message"], decision
    finally:
        sys.path.remove(str(HOOKS))
