"""hooks/<event>-launch.py and lib/hook_launch.py: one Python process per hook event (P12-L7).

- settings.json registers at most one Python process per event (the CI check of row L7), and a
  launcher's registration has no matcher and a timeout of the sum of its rules', so the CLI never
  kills it before its last hook has decided.
- Each launcher's table names existing hook files, each once, and expands (lib/launch_settings)
  into one registration per hook.
- A hook run in the launcher answers as it did alone: its exit status (SystemExit, os._exit, an
  uncaught error, its own excepthook), stdout, stderr, atexit handlers, stdin on fd 0; nothing it
  changes (environment, working directory, signal handlers, harness modules) reaches the next.
- One hook's failure never changes another's verdict: a refusal stands next to a crash, a timeout,
  an os._exit or a hook that ignores its timeout; a fault in the launcher's own code runs the hooks
  as their own processes, and a refusal still refuses.
- The answers combine as the CLI combines parallel hooks.
- The hooks a call matches run at the same time, each in a fork of the launcher (lib/rule_fork):
  the call waits for the slowest, not the sum; the answer is read in rule order whatever order they
  end in, byte for byte what the one-after-another run prints; a rule's ``after`` (only earlier rules
  of its table) holds it until those have ended; a stuck fork is ended alone at its deadline; a fork
  that dies without an answer is a non-blocking error; with another thread alive, or inside a run
  with a watchdog thread, the hooks run one after another as before.
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

from lib import hook_launch, launch_settings  # noqa: E402
from lib.hook_launch import Result, Rule, combine  # noqa: E402
from lib.rule_runner import run_rule  # noqa: E402

PYTHON_COMMAND = ("python3 ", "python ", "python3.")


def _settings() -> dict:
    return json.loads((ROOT / "settings.json").read_text())


def _launchers() -> dict:
    out = {}
    for event, groups in _settings()["hooks"].items():
        for g in groups:
            for h in g["hooks"]:
                hook = launch_settings.launcher_of(h["command"], str(ROOT))
                if hook:
                    out[hook] = (event, g, h)
    return out


# ------------------------------------------------------------------ registrations

def test_each_event_registers_at_most_one_python_process():
    for event, groups in _settings()["hooks"].items():
        pythons = [h["command"] for g in groups for h in g["hooks"] if h["command"].startswith(PYTHON_COMMAND)]
        assert len(pythons) <= 1, f"{event} registers {len(pythons)} Python processes: {pythons}; " \
                                  "a Python hook is a Rule line of its event's launcher (lib/hook_launch.py)"


def test_launchers_cover_the_events_and_time_out_after_their_rules():
    found = _launchers()
    assert {e for e, _, _ in found.values()} == {"UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure",
                                                 "SessionStart", "SubagentStart"}
    for hook, (event, group, h) in found.items():
        assert "matcher" not in group, hook
        rules = launch_settings.rules(str(ROOT), hook)
        assert h["timeout"] == sum(t for _, _, t in rules), hook
        files = [f for f, _, _ in rules]
        assert len(files) == len(set(files)), hook
        for f, tools, timeout in rules:
            assert (HOOKS / f).is_file() and f.endswith(".py"), f
            assert tools is None or (tools and all(t for t in tools)), f
            assert timeout > 0


def test_the_expansion_gives_one_registration_per_hook():
    expanded = launch_settings.expand(_settings(), str(ROOT))
    for event, groups in expanded["hooks"].items():
        for g in groups:
            for h in g["hooks"]:
                assert launch_settings.launcher_of(h["command"], str(ROOT)) is None
    rules = sum(len(launch_settings.rules(str(ROOT), hook)) for hook in _launchers())
    count = lambda s: sum(len(g["hooks"]) for gs in s["hooks"].values() for g in gs)  # noqa: E731
    assert count(expanded) == count(_settings()) - len(_launchers()) + rules


def test_no_hook_ends_the_process_past_the_runner():
    """The runner turns os._exit into the hook's end; a hook calling the C-level exit directly
    would end the launcher and skip the hooks after it."""
    for path in list(HOOKS.glob("*.py")) + list(HOOKS.glob("lib/**/*.py")):
        text = path.read_text(errors="replace")
        assert "posix._exit" not in text and "from os import _exit" not in text, path


# ------------------------------------------------------------------ the runner

def _hook(tmp_path, name, body) -> str:
    p = tmp_path / f"{name}.py"
    p.write_text("import json, os, sys, time\n" + textwrap.dedent(body))
    return str(p)


def _alone(path, raw=b"{}"):
    p = subprocess.run([sys.executable, path], input=raw, capture_output=True, timeout=30)
    return p.returncode, p.stdout.decode(), p.stderr.decode()


@pytest.mark.parametrize("body", [
    "sys.exit(0)\n",
    "print('out'); sys.stderr.write('err\\n'); sys.exit(2)\n",
    "print(json.load(sys.stdin)['a']); sys.exit(3)\n",
    "sys.exit('a message')\n",
    "sys.stdout.write('x'); sys.stdout.flush(); os._exit(2)\n",
    "import atexit\natexit.register(lambda: print('at exit'))\nprint('body')\n",
    "import atexit\natexit.register(lambda: print('never'))\nsys.stdout.flush(); os._exit(0)\n",
    "raise ValueError('boom')\n",
    "def broken(:\n",
    "def refuse(t, v, tb):\n    sys.stderr.write('refused on load\\n'); sys.stderr.flush(); os._exit(2)\n"
    "sys.excepthook = refuse\nimport no_such_module_l7\n",
    "import subprocess\nsubprocess.run(['cat'])\n",
    "print(os.read(0, 100).decode())\n",
])
def test_a_hook_in_the_runner_answers_as_it_did_alone(tmp_path, body):
    path = _hook(tmp_path, "h", body)
    raw = b'{"a": 7}'
    run = run_rule(path, raw, 10.0)
    assert (run.code, run.stdout, run.stderr) == _alone(path, raw)


def test_nothing_a_hook_changes_reaches_the_next(tmp_path):
    import signal
    mod = tmp_path / "l7_cached.py"
    mod.write_text("VALUE = []\n")
    mutate = _hook(tmp_path, "mutate", f"""
        import signal
        sys.path.insert(0, {str(tmp_path)!r})
        os.environ['L7_LEAK'] = '1'; os.chdir('/'); os.umask(0o077)
        signal.signal(signal.SIGTERM, lambda *a: None); signal.setitimer(signal.ITIMER_REAL, 30)
        sys.excepthook = lambda *a: None
        """)
    before = signal.getsignal(signal.SIGTERM)
    hook_before = sys.excepthook
    cwd = os.getcwd()
    run_rule(mutate, b"{}", 5.0)
    assert os.environ.get("L7_LEAK") is None and os.getcwd() == cwd
    assert signal.getsignal(signal.SIGTERM) is before and signal.getitimer(signal.ITIMER_REAL)[0] == 0
    assert sys.excepthook is hook_before
    old = os.umask(0o022)
    os.umask(old)
    assert old != 0o077


def test_harness_modules_are_fresh_for_each_hook(tmp_path):
    first = _hook(tmp_path, "first", f"""
        sys.path.insert(0, {str(HOOKS)!r})
        from lib import harness_state_dir
        harness_state_dir.L7_MARK = 1
        """)
    second = _hook(tmp_path, "second", f"""
        sys.path.insert(0, {str(HOOKS)!r})
        from lib import harness_state_dir
        print(getattr(harness_state_dir, 'L7_MARK', 0))
        """)
    import lib
    sys.modules.pop("lib.harness_state_dir", None)
    if hasattr(lib, "harness_state_dir"):
        delattr(lib, "harness_state_dir")
    run_rule(first, b"{}", 5.0, fresh_modules=True)
    assert run_rule(second, b"{}", 5.0, fresh_modules=True).stdout == "0\n"


def test_runs_nest_and_an_inner_os_exit_ends_only_the_inner_hook(tmp_path):
    inner = _hook(tmp_path, "inner", "print('inner'); sys.stdout.flush(); os._exit(2)\n")
    outer = _hook(tmp_path, "outer", f"""
        sys.path.insert(0, {str(HOOKS)!r})
        from lib.rule_runner import run_rule
        r = run_rule({inner!r}, b'{{}}', 5.0)
        print(r.code, r.stdout.strip()); sys.stdout.flush(); os._exit(5)
        """)
    run = run_rule(outer, b"{}", 10.0)
    assert (run.code, run.stdout) == (5, "2 inner\n")


def test_an_inner_budget_and_an_outer_budget_each_stop_their_own_run(tmp_path):
    slow = _hook(tmp_path, "slow", "time.sleep(30)\n")
    outer = _hook(tmp_path, "outer2", f"""
        sys.path.insert(0, {str(HOOKS)!r})
        from lib.rule_runner import run_rule
        r = run_rule({slow!r}, b'{{}}', 0.3)
        print(r.overrun); sys.stdout.flush()
        time.sleep(30)
        """)
    start = time.monotonic()
    run = run_rule(outer, b"{}", 2.0)
    assert run.overrun and run.stdout == "True\n" and time.monotonic() - start < 10


# ------------------------------------------------------------------ the launcher

def _launcher(tmp_path, event, rules) -> str:
    """A launcher of `rules`: (name, file, tools, timeout[, {more Rule keywords}])."""
    rows = "".join(f"    Rule({r[0]!r}, {r[1]!r}, {r[2]!r}, timeout={r[3]!r}"
                   + "".join(f", {k}={v!r}" for k, v in (r[4] if len(r) > 4 else {}).items()) + "),\n"
                   for r in rules)
    p = tmp_path / "test-launch.py"
    p.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(HOOKS)!r})\n"
        "try:\n"
        "    from lib.hook_launch import Rule, main\n"
        "except Exception:\n"
        "    from lib.hook_launch_fallback import Rule, main\n"
        f"RULES = (\n{rows})\n"
        "if __name__ == '__main__':\n"
        f"    sys.exit(main({event!r}, RULES))\n")
    return str(p)


def _run(launcher, payload, env=None, timeout=60):
    p = subprocess.run([sys.executable, launcher], input=json.dumps(payload).encode(), capture_output=True,
                       timeout=timeout, env=env)
    return p.returncode, p.stdout.decode(), p.stderr.decode()


@pytest.mark.parametrize("bad", [
    "raise RuntimeError('crash')\n",
    "time.sleep(30)\n",
    "sys.stdout.flush(); os._exit(0)\n",
    "print('{\"hookSpecificOutput\": {\"hookEventName\": \"PreToolUse\", \"permissionDecision\": \"allow\"}}')\n",
    "while True:\n    try:\n        time.sleep(30)\n    except BaseException:\n        pass\n",
])
def test_one_hooks_failure_never_turns_anothers_refusal_into_an_allow(tmp_path, bad):
    b = _hook(tmp_path, "bad", bad)
    refuse = _hook(tmp_path, "refuse", "sys.stderr.write('no: refused\\n'); sys.exit(2)\n")
    allow = _hook(tmp_path, "allow", "sys.exit(0)\n")
    for order in ((b, refuse, allow), (refuse, b, allow)):
        launcher = _launcher(tmp_path, "PreToolUse", [(os.path.basename(p), p, ("Bash",), 1)
                                                       for p in order])
        start = time.monotonic()
        code, out, err = _run(launcher, {"tool_name": "Bash", "tool_input": {"command": "ls"}})
        assert code == 2 and "no: refused" in err, (bad, order, code, out, err)
        assert time.monotonic() - start < 20


def test_a_timeout_is_a_non_blocking_error_and_the_later_hooks_still_run(tmp_path):
    slow = _hook(tmp_path, "slow", "time.sleep(30)\n")
    ctx = _hook(tmp_path, "ctx", "print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse', "
                                 "'additionalContext': 'later ran'}}))\n")
    launcher = _launcher(tmp_path, "PostToolUse", [("slow", slow, None, 0.5), ("ctx", ctx, None, 5)])
    code, out, err = _run(launcher, {"tool_name": "Read"})
    j = json.loads(out)
    assert code == 0 and j["hookSpecificOutput"]["additionalContext"] == "later ran"
    assert "ran past its 0.5 s timeout" in j["systemMessage"]


def test_rules_run_only_on_their_tools(tmp_path):
    say = _hook(tmp_path, "say", "print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', "
                                 "'additionalContext': 'bash only'}}))\n")
    launcher = _launcher(tmp_path, "PreToolUse", [("say", say, ("Bash",), 5)])
    assert _run(launcher, {"tool_name": "Read"}) == (0, "", "")
    assert "bash only" in _run(launcher, {"tool_name": "Bash"})[1]


def test_a_runner_fault_runs_the_hooks_as_their_own_processes(tmp_path, monkeypatch):
    refuse = _hook(tmp_path, "refuse", "sys.stderr.write('still refused\\n'); sys.exit(2)\n")
    launcher = _launcher(tmp_path, "PreToolUse", [("refuse", refuse, None, 5)])
    probe = tmp_path / "probe.py"
    probe.write_text(textwrap.dedent(f"""
        import sys, runpy
        sys.path.insert(0, {str(HOOKS)!r})
        import lib.rule_runner
        def broken(*a, **k):
            raise OSError("no file descriptors")
        lib.rule_runner.run_rule = broken
        runpy.run_path({launcher!r}, run_name="__main__")
        """))
    code, out, err = _run(str(probe), {"tool_name": "Bash"})
    assert code == 2 and "still refused" in err


def test_a_launcher_whose_library_cannot_load_still_refuses(tmp_path):
    refuse = _hook(tmp_path, "refuse", "sys.stderr.write('refused without the library\\n'); sys.exit(2)\n")
    launcher = _launcher(tmp_path, "PreToolUse", [("refuse", refuse, None, 5)])
    probe = tmp_path / "probe2.py"
    probe.write_text(textwrap.dedent(f"""
        import sys, runpy
        sys.path.insert(0, {str(HOOKS)!r})
        sys.modules['lib.hook_launch'] = None
        runpy.run_path({launcher!r}, run_name="__main__")
        """))
    code, out, err = _run(str(probe), {"tool_name": "Bash"})
    assert code == 2 and "refused without the library" in err


def test_a_runner_that_cannot_load_runs_the_hooks_as_their_own_processes(tmp_path):
    refuse = _hook(tmp_path, "refuse", "sys.stderr.write('refused without the runner\\n'); sys.exit(2)\n")
    count = _hook(tmp_path, "count", f"open({str(tmp_path / 'ran')!r}, 'a').write('x')\n")
    launcher = _launcher(tmp_path, "PreToolUse", [("count", count, None, 5), ("refuse", refuse, None, 5)])
    probe = tmp_path / "probe3.py"
    probe.write_text(textwrap.dedent(f"""
        import sys, runpy
        sys.path.insert(0, {str(HOOKS)!r})
        sys.modules['lib.rule_runner'] = None
        runpy.run_path({launcher!r}, run_name="__main__")
        """))
    code, out, err = _run(str(probe), {"tool_name": "Bash"})
    assert code == 2 and "refused without the runner" in err
    assert (tmp_path / "ran").read_text() == "x"  # each hook ran once


def test_a_combine_fault_never_runs_a_hook_twice(tmp_path):
    refuse = _hook(tmp_path, "refuse", "sys.stderr.write('refused once\\n'); sys.exit(2)\n")
    count = _hook(tmp_path, "count", f"open({str(tmp_path / 'ran')!r}, 'a').write('x')\n")
    launcher = _launcher(tmp_path, "PreToolUse", [("count", count, None, 5), ("refuse", refuse, None, 5)])
    probe = tmp_path / "probe4.py"
    probe.write_text(textwrap.dedent(f"""
        import sys, runpy
        sys.path.insert(0, {str(HOOKS)!r})
        import lib.hook_launch
        def broken(*a, **k):
            raise ValueError("combine broke")
        lib.hook_launch.combine = broken
        runpy.run_path({launcher!r}, run_name="__main__")
        """))
    code, out, err = _run(str(probe), {"tool_name": "Bash"})
    assert code == 2 and "refused once" in err
    assert (tmp_path / "ran").read_text() == "x"


def test_the_record_channel_is_out_of_the_hooks_environment(tmp_path):
    show = _hook(tmp_path, "show", f"print(os.environ.get({hook_launch.RECORD_ENV!r}, 'absent'))\n")
    launcher = _launcher(tmp_path, "UserPromptSubmit", [("show", show, None, 5)])
    r, w = os.pipe()
    env = dict(os.environ, **{hook_launch.RECORD_ENV: str(w)})
    p = subprocess.run([sys.executable, launcher], input=b"{}", capture_output=True, env=env, pass_fds=(w,),
                       timeout=30)
    os.close(w)
    rec = [json.loads(line) for line in os.read(r, 1 << 20).decode().splitlines()]
    assert p.stdout.decode() == "absent\n" and rec[0]["stdout"] == "absent\n" and rec[0]["rc"] == 0


def test_a_traced_replay_learns_which_hook_runs_and_the_hooks_never_see_it(tmp_path):
    show = _hook(tmp_path, "show", f"print(os.environ.get({hook_launch.MARK_ENV!r}, 'absent'))\n")
    launcher = _launcher(tmp_path, "UserPromptSubmit", [("show", show, None, 5)])
    marks = tmp_path / "marks"
    marks.mkdir()
    env = dict(os.environ, **{hook_launch.MARK_ENV: str(marks)})
    p = subprocess.run([sys.executable, launcher], input=b"{}", capture_output=True, env=env, timeout=30)
    assert p.stdout.decode() == "absent\n"
    names = sorted(f.name for f in marks.iterdir())
    assert names == sorted(["launch.-", "launch.hooks%2F" + show.replace("/", "%2F")]), names


# ------------------------------------------------------------------ combining

def _r(code, out="", err="", path="h.py"):
    return Result(Rule(path, path), code, out, err)


def _j(event="PreToolUse", top=None, **hso):
    return json.dumps(dict(top or {}, hookSpecificOutput={"hookEventName": event, **hso}))


def test_answers_combine_as_the_cli_combines_parallel_hooks():
    one = _j(additionalContext="ctx")
    assert combine("PreToolUse", [_r(0, one)]) == (0, one, "")
    assert combine("PreToolUse", [_r(0), _r(2, "", "no\n")]) == (2, "", "no\n")
    assert combine("PreToolUse", [_r(0, _j(permissionDecision="deny", permissionDecisionReason="denied")),
                                  _r(2, "", "no\n")]) == (2, "", "denied\nno\n")
    assert combine("PreToolUse", [_r(1, "", "crashed\n")]) == (1, "", "crashed\n")
    code, out, _ = combine("PreToolUse", [_r(0, _j(permissionDecision="allow", permissionDecisionReason="a")),
                                          _r(0, _j(permissionDecision="ask", permissionDecisionReason="b",
                                                   updatedInput={"command": "x"}))])
    hso = json.loads(out)["hookSpecificOutput"]
    assert code == 0 and hso["permissionDecision"] == "ask" and hso["updatedInput"] == {"command": "x"}
    code, out, _ = combine("UserPromptSubmit", [_r(0, "plain one\n"), _r(0, _j("UserPromptSubmit",
                                                                              additionalContext="two"))])
    assert json.loads(out)["hookSpecificOutput"]["additionalContext"] == "plain one\ntwo"
    code, out, _ = combine("PostToolUse", [_r(0, json.dumps({"continue": False, "stopReason": "s"})),
                                           _r(2, "", "no\n")])
    assert (code, json.loads(out)) == (0, {"continue": False, "stopReason": "s"})
    code, out, _ = combine("PostToolUse", [_r(0, json.dumps({"decision": "block", "reason": "r"}))])
    assert code == 2
    code, out, _ = combine("PostToolUse", [_r(1, "", "warn\n"), _r(0, _j("PostToolUse", additionalContext="c"))])
    assert code == 0 and json.loads(out)["systemMessage"] == "warn"
    assert combine("PreToolUse", [_r(0, "plain\n", "quiet\n")]) == (0, "plain\n", "quiet\n")


# ------------------------------------------------------------------ at once (lib/rule_fork)

from lib import rule_fork  # noqa: E402

PRE = {"tool_name": "Bash", "tool_input": {"command": "ls"}}


def _ctx(text, event="PreToolUse"):
    return f"print(json.dumps({{'hookSpecificOutput': {{'hookEventName': {event!r}, 'additionalContext': {text!r}}}}}))\n"


def _recorded(launcher, payload, env=None, probe=None, timeout=60):
    """(rc, stdout, stderr, records, seconds) of the launcher run with the record channel open; `probe`:
    Python lines run in the launcher's process before it (the launcher then runs through runpy)."""
    r, w = os.pipe()
    env = dict(env or os.environ, **{hook_launch.RECORD_ENV: str(w)})
    argv = [sys.executable, launcher]
    if probe is not None:
        script = Path(launcher).with_name("probe-" + Path(launcher).name)
        script.write_text(f"import sys, runpy\nsys.path.insert(0, {str(HOOKS)!r})\n{textwrap.dedent(probe)}\n"
                          f"runpy.run_path({launcher!r}, run_name='__main__')\n")
        argv = [sys.executable, str(script)]
    start = time.monotonic()
    p = subprocess.run(argv, input=json.dumps(payload).encode(), capture_output=True, env=env, pass_fds=(w,),
                       timeout=timeout)
    took = time.monotonic() - start
    os.close(w)
    data = b""
    while True:
        chunk = os.read(r, 1 << 16)
        if not chunk:
            break
        data += chunk
    os.close(r)
    recs = [json.loads(line) for line in data.decode().splitlines()]
    return p.returncode, p.stdout.decode(), p.stderr.decode(), recs, took


SEQUENTIAL = """
import threading, time
threading.Thread(target=time.sleep, args=(60,), daemon=True).start()  # another thread: no fork
"""

FAILURES = {
    "syntax error": "def broken(:\n",
    "uncaught exception": "raise RuntimeError('crash')\n",
    "os._exit(0)": "sys.stdout.write('partial'); sys.stdout.flush(); os._exit(0)\n",
    "allow JSON": "print('{\"hookSpecificOutput\": {\"hookEventName\": \"PreToolUse\", \"permissionDecision\": \"allow\"}}')\n",
    "past its timeout": "time.sleep(30)\n",
    "ignores its timeout": "while True:\n    try:\n        time.sleep(30)\n    except BaseException:\n        pass\n",
    "dies by a signal": "import signal\nos.kill(os.getpid(), signal.SIGKILL)\n",
    "C-level exit 2": "sys.stderr.write('not a refusal\\n'); sys.stderr.flush(); getattr(__import__('posix'), '_exit')(2)\n",
}


@pytest.mark.parametrize("name", sorted(FAILURES))
def test_a_refusal_stands_next_to_a_failing_hook_run_at_once_in_either_order(tmp_path, name):
    bad = _hook(tmp_path, "bad", FAILURES[name])
    refuse = _hook(tmp_path, "refuse", "time.sleep(0.2); sys.stderr.write('no: refused\\n'); sys.exit(2)\n")
    say = _hook(tmp_path, "say", _ctx("said"))
    for order in ((bad, refuse, say), (refuse, bad, say)):
        launcher = _launcher(tmp_path, "PreToolUse", [(os.path.basename(p), p, ("Bash",), 1) for p in order])
        code, out, err, recs, took = _recorded(launcher, PRE)
        assert code == 2 and err == "no: refused\n" and out == "", (name, order, code, out, err)
        assert took < 8, (name, took)
        assert [r["hook"] for r in recs] == ["hooks/" + p for p in order]
        assert {r["how"] for r in recs} == {"fork"}, recs
        rec = recs[order.index(bad)]
        if name in ("past its timeout", "ignores its timeout"):
            assert rec["rc"] == "timeout" and rec["stderr"] == "timeout"
        elif name == "dies by a signal":
            assert rec["rc"] == -9 and "ended without an answer (signal 9)" in rec["stderr"]
        elif name == "C-level exit 2":  # it handed back nothing: an error, never a refusal it did not make
            assert rec["rc"] == 1 and "ended without an answer (exit status 2)" in rec["stderr"]
        else:  # it fails as it did alone
            assert (rec["rc"], rec["stdout"], rec["stderr"]) == _alone(bad, json.dumps(PRE).encode()), name


@pytest.mark.parametrize("name", ["dies by a signal", "C-level exit 2"])
def test_a_fork_that_ends_without_an_answer_is_a_non_blocking_error(tmp_path, name):
    bad = _hook(tmp_path, "bad", FAILURES[name])
    say = _hook(tmp_path, "say", _ctx("said"))
    launcher = _launcher(tmp_path, "PreToolUse", [("bad", bad, None, 5), ("say", say, None, 5)])
    code, out, err, recs, _ = _recorded(launcher, PRE)
    j = json.loads(out)
    assert code == 0 and j["hookSpecificOutput"]["additionalContext"] == "said"
    assert "ended without an answer" in j["systemMessage"]


def test_the_hooks_run_at_the_same_time(tmp_path):
    rules = [(f"s{i}", _hook(tmp_path, f"s{i}", "time.sleep(1.0)\n" + _ctx(f"s{i}")), None, 10) for i in range(4)]
    launcher = _launcher(tmp_path, "PreToolUse", rules)
    code, out, err, recs, took = _recorded(launcher, PRE)
    assert code == 0 and json.loads(out)["hookSpecificOutput"]["additionalContext"] == "s0\ns1\ns2\ns3"
    assert took < 2.5, took  # one sleep, not four
    assert [r["how"] for r in recs] == ["fork"] * 4 and all(r["ms"] >= 950 for r in recs), recs


def _mixed(tmp_path, refuse: bool):
    """Rules whose answers end in the reverse of their order, each with something combine() keeps."""
    bodies = [
        "time.sleep(0.6)\nprint(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', "
        "'additionalContext': 'first', 'updatedInput': {'command': 'one'}}, 'systemMessage': 'm1'}))\n",
        "time.sleep(0.4)\nsys.stderr.write('warned\\n'); sys.exit(1)\n",
        "time.sleep(0.2)\nprint(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', "
        "'additionalContext': 'third', 'updatedInput': {'command': 'three'}, 'permissionDecision': 'ask', "
        "'permissionDecisionReason': 'r3'}, 'systemMessage': 'm3'}))\n",
        ("sys.stderr.write('refused last\\n'); sys.exit(2)\n" if refuse else _ctx("fourth")),
    ]
    if refuse:
        bodies[0] = "time.sleep(0.6)\nsys.stderr.write('refused first\\n'); sys.exit(2)\n"
    return _launcher(tmp_path, "PreToolUse", [(f"m{i}", _hook(tmp_path, f"m{i}", b), None, 10)
                                              for i, b in enumerate(bodies)])


@pytest.mark.parametrize("refuse", [False, True])
def test_the_answer_is_read_in_rule_order_byte_for_byte_as_one_after_another(tmp_path, refuse):
    launcher = _mixed(tmp_path, refuse)
    at_once = _recorded(launcher, PRE)
    in_order = _recorded(launcher, PRE, probe=SEQUENTIAL)
    assert [r["how"] for r in at_once[3]] == ["fork"] * 4
    assert [r["how"] for r in in_order[3]] == ["in-process"] * 4
    assert at_once[:3] == in_order[:3]
    assert [r["hook"] for r in at_once[3]] == [r["hook"] for r in in_order[3]]
    assert [(r["rc"], r["stdout"], r["stderr"]) for r in at_once[3]] == \
           [(r["rc"], r["stdout"], r["stderr"]) for r in in_order[3]]
    code, out, err = at_once[:3]
    if refuse:
        assert (code, out, err) == (2, "", "refused first\nrefused last\n")
    else:
        hso = json.loads(out)["hookSpecificOutput"]
        assert code == 0 and hso["additionalContext"] == "first\nthird\nfourth"
        assert hso["updatedInput"] == {"command": "one"}
        assert json.loads(out)["systemMessage"] == "m1\nm3\nwarned"


def test_a_rule_waits_for_the_rule_it_names_and_starts_at_once_without_it(tmp_path):
    flag = tmp_path / "written"
    write = _hook(tmp_path, "write", f"time.sleep(0.5); open({str(flag)!r}, 'w').write('written')\n")
    read = _hook(tmp_path, "read", f"print(open({str(flag)!r}).read() if os.path.exists({str(flag)!r}) "
                                   "else 'missing')\n")
    other = _hook(tmp_path, "other", "time.sleep(0.5)\n")
    launcher = _launcher(tmp_path, "PreToolUse", [("write", write, ("Read",), 5), ("other", other, None, 5),
                                                  ("read", read, None, 5, {"after": ("write",)})])
    code, out, err, recs, took = _recorded(launcher, {"tool_name": "Read"})
    assert (code, out) == (0, "written\n") and took < 2.5
    flag.unlink()
    code, out, err, recs, took = _recorded(launcher, {"tool_name": "Bash"})  # `write` not selected
    assert (code, out) == (0, "missing\n") and [r["how"] for r in recs] == ["fork", "fork"]
    assert recs[1]["ms"] < 400  # it did not wait for `other` either


def _tables() -> dict:
    """{launcher: [(name, after)]} of every launcher's RULES table, read statically."""
    import ast
    out = {}
    for hook in _launchers():
        tree = ast.parse((ROOT / hook).read_text())
        for st in tree.body:
            if isinstance(st, ast.Assign) and any(getattr(t, "id", "") == "RULES" for t in st.targets):
                rows = []
                for call in st.value.elts:
                    kw = {k.arg: ast.literal_eval(k.value) for k in call.keywords}
                    rows.append((ast.literal_eval(call.args[0]), tuple(kw.get("after", ()))))
                out[hook] = rows
    return out


def test_after_names_only_earlier_rules_of_the_same_table():
    tables = _tables()
    for hook, rows in tables.items():
        names = [n for n, _ in rows]
        assert len(names) == len(set(names)), hook
        for i, (name, after) in enumerate(rows):
            assert all(a in names[:i] for a in after), (hook, name, after)
    # the same-call read-after-write pairs, in their old order
    assert dict(tables["hooks/pretool-launch.py"])["cp-checkin"] == ("write-gate",)
    assert dict(tables["hooks/posttool-launch.py"])["doc-sync"] == ("attribution-post",)
    assert sum(len(a) for rows in tables.values() for _, a in rows) == 2


def test_after_changes_nothing_the_table_readers_give(tmp_path):
    plain = _launcher(tmp_path, "PreToolUse", [("a", "a.py", ("Read",), 5), ("b", "b.py", None, 7)])
    before = launch_settings.rules(str(tmp_path), os.path.basename(plain))
    _launcher(tmp_path, "PreToolUse", [("a", "a.py", ("Read",), 5), ("b", "b.py", None, 7, {"after": ("a",)})])
    assert launch_settings.rules(str(tmp_path), os.path.basename(plain)) == before == \
        [("a.py", ("Read",), 5), ("b.py", None, 7)]


def test_with_another_thread_alive_the_hooks_run_one_after_another(tmp_path):
    rules = [(f"s{i}", _hook(tmp_path, f"s{i}", "time.sleep(0.4)\n"), None, 5) for i in range(3)]
    launcher = _launcher(tmp_path, "PreToolUse", rules)
    code, out, err, recs, took = _recorded(launcher, PRE, probe=SEQUENTIAL)
    assert code == 0 and [r["how"] for r in recs] == ["in-process"] * 3 and took >= 1.2


def _script(tmp_path, body) -> str:
    """Python run as its own process, with hooks/ on its path: its stdout."""
    p = tmp_path / "script.py"
    p.write_text(f"import json, os, sys\nsys.path.insert(0, {str(HOOKS)!r})\n" + textwrap.dedent(body))
    run = subprocess.run([sys.executable, str(p)], capture_output=True, timeout=60)
    assert run.returncode == 0, run.stderr.decode()
    return run.stdout.decode()


def test_no_fork_inside_a_run_with_a_watchdog_thread(tmp_path):
    probe = _hook(tmp_path, "probe", f"sys.path.insert(0, {str(HOOKS)!r})\nfrom lib import rule_fork\n"
                                     "print(rule_fork.can_fork())\n")
    assert _script(tmp_path, f"""
        from lib.rule_runner import run_rule
        print(run_rule({probe!r}, b"{{}}", 5.0).stdout.strip(), run_rule({probe!r}, b"{{}}", 5.0, watchdog=False).stdout.strip())
        """) == "False True\n"
    assert _alone(probe)[1] == "True\n"


def test_a_forked_hook_starts_with_one_thread(tmp_path):
    show = _hook(tmp_path, "show", f"import threading\nsys.path.insert(0, {str(HOOKS)!r})\n"
                                   "from lib import rule_fork\n"
                                   "print(threading.active_count(), rule_fork._kernel_threads())\n")
    other = _hook(tmp_path, "other", "pass\n")
    launcher = _launcher(tmp_path, "PreToolUse", [("show", show, None, 5), ("other", other, None, 5)])
    code, out, err, recs, _ = _recorded(launcher, PRE)
    assert (code, out) == (0, "1 1\n") and recs[0]["how"] == "fork"


def test_a_stuck_fork_is_ended_alone_and_a_helper_in_its_own_session_lives_on(tmp_path):
    alive, pidfile = tmp_path / "helper-alive", tmp_path / "stuck.pid"
    stuck = _hook(tmp_path, "stuck", f"""
        import subprocess
        open({str(pidfile)!r}, 'w').write(str(os.getpid()))
        code = "import sys, time; time.sleep(3); open(sys.argv[1], 'w').write('x')"
        subprocess.Popen([sys.executable, '-c', code, {str(alive)!r}],
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while True:
            try:
                time.sleep(30)
            except BaseException:
                pass
        """)
    say = _hook(tmp_path, "say", "time.sleep(0.2)\n" + _ctx("still answered"))
    slow = _hook(tmp_path, "slow", "time.sleep(30)\n")
    launcher = _launcher(tmp_path, "PreToolUse", [("stuck", stuck, None, 0.5), ("slow", slow, None, 0.5),
                                                  ("say", say, None, 5)])
    code, out, err, recs, took = _recorded(launcher, PRE)
    j = json.loads(out)
    assert code == 0 and j["hookSpecificOutput"]["additionalContext"] == "still answered"
    assert "pretool" not in j["systemMessage"] and j["systemMessage"].count("ran past its 0.5 s timeout") == 2
    assert [r["rc"] for r in recs] == ["timeout", "timeout", 0]
    assert recs[1]["ms"] < 1500  # it stopped at its overrun signal
    assert took < 4.5  # the stuck one ended after the grace
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)
    deadline = time.monotonic() + 10
    while not alive.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert alive.exists(), "the helper the hook started in its own session was ended with it"


def test_the_records_are_in_rule_order_with_each_hooks_own_time(tmp_path):
    slow = _hook(tmp_path, "slow", "time.sleep(0.6)\nprint('slow')\n")
    fast = _hook(tmp_path, "fast", "print('fast')\n")
    show = _hook(tmp_path, "show", f"print(os.environ.get({hook_launch.RECORD_ENV!r}, 'absent'), "
                                   f"os.environ.get({hook_launch.MARK_ENV!r}, 'absent'))\n")
    marks = tmp_path / "marks"
    marks.mkdir()
    launcher = _launcher(tmp_path, "UserPromptSubmit", [("slow", slow, None, 5), ("fast", fast, None, 5),
                                                        ("show", show, None, 5)])
    code, out, err, recs, _ = _recorded(launcher, {}, env=dict(os.environ, **{hook_launch.MARK_ENV: str(marks)}))
    assert [r["hook"] for r in recs] == ["hooks/" + p for p in (slow, fast, show)]
    assert [r["stdout"] for r in recs] == ["slow\n", "fast\n", "absent absent\n"]
    assert recs[0]["ms"] >= 550 and recs[1]["ms"] < 400 and {r["how"] for r in recs} == {"fork"}
    names = sorted(f.name for f in marks.iterdir())
    assert names == sorted(["launch.-"] + ["launch.hooks%2F" + p.replace("/", "%2F") for p in (slow, fast, show)])


def test_each_fork_marks_its_own_hook_before_it_runs(tmp_path):
    """lib/rule_fork.run_at_once calls mark(i, True) in job i's own process before its file runs and
    mark(i, False) after: the trace (tests/replay/trace.py LAUNCH_MARK) names each hook per process."""
    log = tmp_path / "log"
    hooks = [_hook(tmp_path, f"j{i}", f"open({str(log)!r}, 'a').write(f'run {i} {{os.getpid()}}\\n')\n")
             for i in range(3)]
    parent = _script(tmp_path, f"""
        from lib import rule_fork
        def mark(i, on):
            with open({str(log)!r}, "a") as fh:
                fh.write(("mark" if on else "end") + f" {{i}} {{os.getpid()}}\\n")
        assert rule_fork.can_fork()
        runs = rule_fork.run_at_once([rule_fork.Job(h, b"{{}}", 5.0) for h in {hooks!r}], mark=mark)
        assert [r.code for r in runs] == [0, 0, 0], runs
        print(os.getpid())
        """).strip()
    lines = [line.split() for line in log.read_text().splitlines()]
    for i in range(3):
        mine = [(what, pid) for what, j, pid in lines if j == str(i)]
        assert [w for w, _ in mine] == ["mark", "run", "end"], lines
        assert len({p for _, p in mine}) == 1 and mine[0][1] != parent  # its own process, not the launcher
    assert len({p for _, j, p in lines}) == 3


def test_nothing_a_forked_hook_changes_reaches_another(tmp_path):
    mutate = _hook(tmp_path, "mutate", """
        import signal
        os.environ['L7_LEAK'] = '1'; os.chdir('/'); os.umask(0o077)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        os.dup2(os.open(os.devnull, os.O_WRONLY), 1)  # its own stdout gone
        """)
    probe = """
        import signal
        u = os.umask(0); os.umask(u)
        print(os.environ.get('L7_LEAK'), os.getcwd(), signal.getsignal(signal.SIGTERM) == signal.SIG_DFL, oct(u))
        """
    first, second = _hook(tmp_path, "first", probe), _hook(tmp_path, "second", probe)
    launcher = _launcher(tmp_path, "UserPromptSubmit", [("mutate", mutate, None, 5), ("first", first, None, 5),
                                                        ("second", second, None, 5, {"after": ("mutate",)})])
    p = subprocess.run([sys.executable, launcher], input=b"{}", capture_output=True, timeout=30,
                       cwd=str(tmp_path))
    want = f"None {tmp_path} True 0o22"
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"] == f"{want}\n{want}", p.stdout


def test_a_fork_that_cannot_be_made_runs_that_hook_as_its_own_process(tmp_path):
    refuse = _hook(tmp_path, "refuse", "sys.stderr.write('refused anyway\\n'); sys.exit(2)\n")
    say = _hook(tmp_path, "say", "time.sleep(0.5)\n" + _ctx("a"))
    say2 = _hook(tmp_path, "say2", "time.sleep(0.5)\n" + _ctx("b"))
    launcher = _launcher(tmp_path, "PreToolUse", [("say", say, None, 5), ("refuse", refuse, None, 5),
                                                  ("say2", say2, None, 5)])
    probe = """
        import os
        real, calls = os.fork, []
        def fork():
            calls.append(1)
            if len(calls) == 2:
                raise OSError(11, "Resource temporarily unavailable")
            return real()
        os.fork = fork
        """
    code, out, err, recs, took = _recorded(launcher, PRE, probe=probe)
    assert (code, err) == (2, "refused anyway\n") and [r["how"] for r in recs] == ["fork", "process", "fork"]
    assert took < 1.5  # the other two still ran at once


def test_a_process_a_forked_hook_forks_ends_at_its_own_exit(tmp_path):
    """A hook that forks without exec (lib/todo_canonical runs a todo script so) has its fork end at
    os._exit, or at the end of the file, as when the hook ran alone: it never answers for the hook."""
    forks = _hook(tmp_path, "forks", """
        pid = os.fork()
        if pid == 0:
            print('child'); sys.stdout.flush()
            os._exit(3)
        _, status = os.waitpid(pid, 0)
        print('parent', os.waitstatus_to_exitcode(status)); sys.stdout.flush()  # as todo_canonical does
        pid = os.fork()
        if pid == 0:
            sys.exit(4)
        _, status = os.waitpid(pid, 0)
        print('parent', os.waitstatus_to_exitcode(status))
        """)
    other = _hook(tmp_path, "other", "time.sleep(0.2)\n")
    launcher = _launcher(tmp_path, "UserPromptSubmit", [("forks", forks, None, 5), ("other", other, None, 5)])
    code, out, err, recs, _ = _recorded(launcher, {})
    assert recs[0]["how"] == "fork" and len(recs) == 2
    assert (recs[0]["rc"], recs[0]["stdout"], recs[0]["stderr"]) == _alone(forks) == (0, "child\nparent 3\nparent 4\n", "")


def test_an_answer_handed_back_while_the_launcher_was_busy_still_answers(tmp_path):
    """A fork that answered within its budget, and ended, while the launcher ran another hook as
    its own process past that budget: its answer stands (read from its pipe), never an error."""
    refuse = _hook(tmp_path, "refuse", "time.sleep(0.4); sys.stderr.write('no: refused\\n'); sys.exit(2)\n")
    slow = _hook(tmp_path, "slow", "time.sleep(1.5)\n" + _ctx("slow"))
    launcher = _launcher(tmp_path, "PreToolUse", [("refuse", refuse, None, 1), ("slow", slow, None, 5)])
    probe = """
        import os
        real, calls = os.fork, []
        def fork():
            calls.append(1)
            if len(calls) == 2:  # `slow` runs as its own process, in the launcher, for 1.5 s
                raise OSError(11, "Resource temporarily unavailable")
            return real()
        os.fork = fork
        """
    code, out, err, recs, _ = _recorded(launcher, PRE, probe=probe)
    assert [r["how"] for r in recs] == ["fork", "process"]
    assert (recs[0]["rc"], recs[0]["stderr"]) == (2, "no: refused\n"), recs[0]
    assert (code, out, err) == (2, "", "no: refused\n")


def _gate(tmp_path, name, job_body, budget=20.0) -> str:
    """A hook that runs two jobs of `job_body` at once through lib/rule_fork, as the write gate does."""
    job = _hook(tmp_path, name + "-job", job_body)
    return _hook(tmp_path, name, f"""
        sys.path.insert(0, {str(HOOKS)!r})
        from lib import rule_fork
        assert rule_fork.can_fork()
        rule_fork.run_at_once([rule_fork.Job({job!r}, b"{{}}", {budget!r})] * 2)
        print('gate done')
        """)


def test_a_gates_forks_end_with_the_gate_when_its_launcher_ends_it(tmp_path):
    """The launcher's overrun signal ends a gate that forks its own rules: the gate's forks end with
    it, so none runs past the call or holds the launcher's stdout open."""
    late = tmp_path / "late"
    gate = _gate(tmp_path, "gate", f"time.sleep(4)\nopen({str(late)!r}, 'w').write('ran past the call')\n")
    other = _hook(tmp_path, "other", _ctx("other"))
    launcher = _launcher(tmp_path, "PreToolUse", [("gate", gate, None, 1), ("other", other, None, 5)])
    code, out, err, recs, took = _recorded(launcher, PRE)
    assert took < 3, took  # its stdout closed when it ended, not when the gate's forks did
    assert code == 0 and [r["rc"] for r in recs] == ["timeout", 0]
    time.sleep(4.5)
    assert not late.exists(), "a gate's fork ran on past the call"


def test_a_fork_a_forked_gate_makes_does_not_hold_the_launchers_pipe(tmp_path):
    """A gate that dies (here its own fork ends it, as a kill from outside would) is answered for at
    once: its forks do not hold the pipe it hands back on to the launcher."""
    gate = _gate(tmp_path, "gate", "import signal\nos.kill(os.getppid(), signal.SIGKILL)\ntime.sleep(4)\n")
    other = _hook(tmp_path, "other", _ctx("other"))
    launcher = _launcher(tmp_path, "PreToolUse", [("gate", gate, None, 30), ("other", other, None, 5)])
    out = tmp_path / "out"
    with open(out, "wb") as fh:  # a file, not a pipe: the gate's orphaned forks still hold it a while
        p = subprocess.Popen([sys.executable, launcher], stdin=subprocess.PIPE, stdout=fh, stderr=fh)
        p.stdin.write(json.dumps(PRE).encode())
        p.stdin.close()
        start = time.monotonic()
        assert p.wait(timeout=30) == 0
    assert time.monotonic() - start < 3  # not when the gate's forks ended (4 s), nor at its deadline
    assert "gate.py: ended without an answer (signal 9)" in json.loads(out.read_text())["systemMessage"]


def test_a_launcher_ended_by_sigterm_ends_its_forks_first(tmp_path):
    """The CLI ends a hook with SIGTERM: the launcher's forks end with it (no hook runs on after the
    launcher, with no one keeping its deadline), and the launcher ends by that signal, as before."""
    import signal
    late = tmp_path / "late"
    slow = _hook(tmp_path, "slow", f"time.sleep(3)\nopen({str(late)!r}, 'w').write('after the launcher')\n")
    other = _hook(tmp_path, "other", "time.sleep(3)\n")
    launcher = _launcher(tmp_path, "PreToolUse", [("slow", slow, None, 30), ("other", other, None, 30)])
    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps(PRE))
    with open(payload, "rb") as fh:
        p = subprocess.Popen([sys.executable, launcher], stdin=fh, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(0.8)
    p.send_signal(signal.SIGTERM)
    start = time.monotonic()
    out, err = p.communicate(timeout=10)
    assert p.returncode == -signal.SIGTERM, (p.returncode, err)
    assert time.monotonic() - start < 2  # its stdout closed: no fork holds it
    time.sleep(3)
    assert not late.exists(), "a fork ran on after its launcher was ended"
