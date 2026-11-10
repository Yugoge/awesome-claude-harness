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
    assert {e for e, _, _ in found.values()} == {"UserPromptSubmit", "PreToolUse", "PostToolUse"}
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
    rows = "".join(f"    Rule({n!r}, {p!r}, {t!r}, timeout={to!r}),\n" for n, p, t, to in rules)
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
