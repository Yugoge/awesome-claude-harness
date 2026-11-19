"""hooks/lib/refusal_record.py: the refusal record's one writer, and the calls that report to it.

- One refused call, stop or prompt is one line holding every field of the record, each bounded;
  an allowed call, and a payload that names no refusing event, writes nothing.
- A rule's identifier is the same for every call that rule refuses: no path, id, count or command.
- The reports of one call merge into one line whatever order they arrive in: a gate's rules, its
  launcher's other rules, the shell hook of the same call; a hook's own report replaces what its
  parent said of it. A retry is a line of its own. A let-through (UNPROVEN) is its own kind.
- Recording never decides: where the record cannot be written (no home, no space, a held lock, an
  unreadable payload) write() returns False, raises nothing, and a launcher answers as it did. A hook
  reports through report(), which runs the writer as a process of its own: a writer that is missing,
  fails or hangs changes nothing for the hook, and a payload that names no event starts no process.
  The writer's own process ends itself after REPORT_WAIT seconds: a shell hook waits for it unbounded.
- The directory is private, the days past KEEP_DAYS go, a day's file stops at MAX_DAY_BYTES, and
  writers running at once lose no line.
- Writer and reader resolve one directory in each layout: ~/.claude itself; a home elsewhere reached
  through ~/.claude and through an account's linked hooks/; any CLAUDE_* environment or none.

Run with: python3 -m pytest hooks/tests/test_refusal_record.py -q
"""
from __future__ import annotations

import calendar
import errno
import fcntl
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "hooks"
sys.path.insert(0, str(HOOKS))

try:
    from lib import refusal_record as R  # noqa: E402
except ImportError:  # the writer is gone: each test below fails by name, instead of this file not loading
    R = None

SID = "5d0c2f6e-8a41-4b7c-9e15-2f3a6b7c8d90"


def payload(tool="Bash", tool_input=None, call="toolu_01", event="PreToolUse", **more) -> dict:
    p = {"hook_event_name": event, "session_id": SID, "cwd": "/work/project", "transcript_path": "/none.jsonl",
         "permission_mode": "default", "tool_name": tool, "tool_use_id": call,
         "tool_input": tool_input if tool_input is not None or not tool else {"command": "true"}}
    p.update(more)
    return {k: v for k, v in p.items() if v is not None}


def lines() -> list[dict]:
    folder = Path(R.directory())
    return [json.loads(x) for f in sorted(folder.glob("refusals-*.jsonl")) for x in f.read_text().splitlines()] \
        if folder.is_dir() else []


# ------------------------------------------------------------------ one refusal, one line

def test_one_refusal_is_one_line_with_every_field(monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/project")
    p = payload(tool_input={"command": "rm -rf build"}, agent_id="a1b2c3d4e5f60718", agent_type="dev")
    before = time.time()
    assert R.write(json.dumps(p).encode(), [(str(HOOKS / "pretool-tool-policy.py"), "BLOCKED by x: no\n")],
                   str(HOOKS / "pretool-write-gate.py")) is True
    (line,) = lines()
    stamp = line.pop("ts")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", stamp)
    assert before - 1 <= calendar.timegm(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")) <= time.time() + 1
    assert line.pop("version").startswith((REPO / "VERSION").read_text().strip())
    assert line == {
        "v": 1, "kind": "refusal", "event": "PreToolUse", "session": SID, "actor": "subagent",
        "agent_id": "a1b2c3d4e5f60718", "role": "dev", "tool": "Bash", "tool_use_id": "toolu_01",
        "refused": "rm -rf build", "message": "BLOCKED by x: no", "project": "/work/project", "provider": "claude",
        "rules": [{"hook": "hooks/pretool-tool-policy.py", "id": "blocked-by-x-no", "by": "hooks/pretool-write-gate.py"}],
    }


@pytest.mark.parametrize("p, refused, actor", [
    (payload("Write", {"file_path": "/work/project/a.py", "content": "x" * 5000}), "/work/project/a.py", "main"),
    (payload("NotebookEdit", {"notebook_path": "/n.ipynb"}), "/n.ipynb", "main"),
    (payload("Agent", {"subagent_type": "qa", "prompt": "check"}), '{"prompt": "check", "subagent_type": "qa"}', "main"),
    (payload(None, None, None, "UserPromptSubmit", prompt="/dev-overnight now"), "/dev-overnight now", "main"),
    (payload(None, None, None, "SubagentStop", agent_id="a9", agent_type="qa"), "", "subagent"),
])
def test_what_was_refused_is_the_command_the_path_the_input_or_the_prompt(p, refused, actor):
    assert R.write(p, [("hooks/x.py", "no")], "hooks/x.py")
    assert (lines()[0]["refused"], lines()[0]["actor"]) == (refused, actor)


def test_the_refused_text_and_the_message_are_bounded():
    assert R.write(payload(tool_input={"command": "c" * 9000}), [("hooks/x.py", "m" * 9000)] * 40, "hooks/x.py")
    (line,) = lines()
    assert len(line["refused"]) == R.REFUSED_MAX and len(line["message"]) == R.MESSAGE_MAX
    assert len(line["rules"]) == R.RULES_MAX


@pytest.mark.parametrize("p, rules", [
    (payload(event=None), [("hooks/x.py", "no")]),                      # a canary's probe, a unit test's input
    (payload(event="SessionStart"), [("hooks/x.py", "no")]),            # an exit 2 there refuses nothing
    (payload(), []),                                                    # nothing refused
    (b"not json", [("hooks/x.py", "no")]),
])
def test_no_call_of_the_cli_or_no_refusal_writes_nothing(p, rules):
    assert R.write(p, rules, "hooks/x.py") is False
    assert not os.path.exists(R.directory())


def test_provider_is_codex_where_the_codex_wrapper_runs_the_hook(monkeypatch):
    monkeypatch.setenv("CLAUDE_COMPAT_RUNTIME", "codex")
    R.write(payload(call="c1"), [("hooks/x.py", "no")], "hooks/x.py")
    monkeypatch.delenv("CLAUDE_COMPAT_RUNTIME")
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    R.write(payload(call="c2"), [("hooks/x.py", "no")], "hooks/x.py")
    assert [x["provider"] for x in lines()] == ["codex", None]


# ------------------------------------------------------------------ a rule's identifier

SAME_RULE = [
    ('BLOCKED by tool-policy.v1: {"role":"ba","tool":"Write","target":"/tmp/a.txt","deny_reason":"write target /tmp/a.txt '
     'not in allowed_write_path_prefixes"}',
     'BLOCKED by tool-policy.v1: {"role":"dev","tool":"Edit","target":"d","deny_reason":"write target d not in '
     'allowed_write_path_prefixes"}', "blocked-by-tool-policy.v1-write-target-not-in-allowed_write_path_prefixes"),
    ('BLOCKED by tool-policy.v1: {"role":"ba","tool":"TodoWrite","target":null,"deny_reason":"tool TodoWrite not in allowed_tools"}',
     'BLOCKED by tool-policy.v1: {"role":"qa","tool":"Monitor","target":null,"deny_reason":"tool Monitor not in allowed_tools"}',
     "blocked-by-tool-policy.v1-tool-not-in-allowed_tools"),
    ('BLOCKED: removal-policy — UNRESOLVED dynamic_command_head:t=$(git ls-files "$e" | wc -l)\nCommand: a',
     "BLOCKED: removal-policy — UNRESOLVED dynamic_command_head:m=$((m+1))\nCommand: b",
     "blocked-removal-policy-unresolved-dynamic_command_head"),
    ("BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:sed:s#^(..)#\\1#",
     "BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:curl:\nCommand: date -u; for s in a b",
     "blocked-removal-policy-unresolved-unproven_boundary_with_removal_reference"),
    ('BLOCKED: removal-policy — UNRESOLVED dynamic_git_subcommand:--git-dir="$g"\nCommand: for g in a b',
     "BLOCKED: removal-policy — UNRESOLVED dynamic_git_subcommand:$sub\nCommand: git $sub",
     "blocked-removal-policy-unresolved-dynamic_git_subcommand"),
    ("BLOCKED: removal-policy — UNRESOLVED interpreter_dynamic_attribute_access:python3:\nexec\nCommand: python3 - <<'EOF'",
     "BLOCKED: removal-policy — UNRESOLVED interpreter_dynamic_attribute_access:python:(getattr\nCommand: python -c x",
     "blocked-removal-policy-unresolved-interpreter_dynamic_attribute_access"),
    ("[Write Guard] BLOCKED: File already exists: /work/a/tests/report.js\nWrite would replace",
     "[Write Guard] BLOCKED: File already exists: /srv/b.md", "write-guard-blocked-file-already-exists"),
    ("BLOCKED: hard-banned script 'alpha-recovery' is refused", "BLOCKED: hard-banned script 'beta-restart' is refused",
     "blocked-hard-banned-script-is-refused"),
    ("OBLIGATION_STOPGATE_BLOCKED: agent a0b1c2d3e4f506172 (role=ba, task_id=20260101-000001) declared 1 obligated "
     "artifact(s); 1 finding(s) to repair before you stop:\n  - docs/dev/ba-panel-20260101-000001-C.md: artifact_missing",
     "OBLIGATION_STOPGATE_BLOCKED: agent a9f8e7d6c5b4a3921 (role=dev, task_id=20260102-000002-r15) declared 3 obligated "
     "artifact(s); 2 finding(s) to repair before you stop:\n  - docs/dev/x-20260102-000002.json: artifact_missing",
     "obligation_stopgate_blocked-agent-declared-obligated-to-repair-before-you-artifact_missing"),
    ("COMMAND_GATE /dev: not complete\n- todo: not completed: Step 10", "COMMAND_GATE /push: not complete\n- todo: x",
     "command_gate-not-complete"),
    ('BLOCKED: Cannot complete "Step 12: Validate dev implementation" before its agent returned',
     'BLOCKED: Cannot complete "Step 3: Ask the owner" before its agent returned',
     "blocked-cannot-complete-before-its-agent-returned"),
]


@pytest.mark.parametrize("one, other, expected", SAME_RULE, ids=[x[2][:40] for x in SAME_RULE])
def test_a_rule_gives_one_identifier_whatever_it_refuses(one, other, expected):
    assert R.rule_id(one) == R.rule_id(other) == expected


def test_the_calls_own_tool_and_role_are_no_part_of_the_identifier():
    text = "[Orchestrator Gate] BLOCKED: {} used consecutively beyond limit ({}/5)"
    assert R.rule_id(text.format("Bash", 6), {"Bash"}) == R.rule_id(text.format("Edit", 2), {"Edit"}) \
        == "orchestrator-gate-blocked-used-consecutively-beyond-limit"
    assert len({R.rule_id(x[0]) for x in SAME_RULE}) == len(SAME_RULE)       # and two rules are two identifiers
    # a line after the first joins the identifier only as that line's detail (indented, or a list item)
    assert R.rule_id("Monitor's command, checked as a Bash call, is refused:\nBLOCKED: kill with signals is refused") \
        == "monitor's-command-checked-as-a-bash-call-is"
    assert R.rule_id("GATE BLOCK (x):\n  - docs/a-20260101-000001.md: artifact_missing: no file") == "gate-block-x-artifact_missing-no-file"


# ------------------------------------------------------------------ the reports of one call

GATE, LAUNCH, SHELL = "hooks/pretool-write-gate.py", "hooks/pretool-launch.py", "hooks/pretool-bash-safety.sh"
REPORTS = (
    ([("hooks/pretool-tool-policy.py", "BLOCKED by tool-policy.v1: no\n"), ("hooks/lib/write_gate/overwrite.py", "[Write Guard] BLOCKED: x\n")], GATE),
    ([(GATE, "BLOCKED by tool-policy.v1: no\n[Write Guard] BLOCKED: x\n"), ("hooks/pretool-git-privilege-guard.py", "BLOCKED: agent git push\n")], LAUNCH),
    ([("hooks/lib/bash_safety_rules.py", "BLOCKED: kill with signals is refused\n")], "hooks/lib/bash_safety_rules.py"),
    ([("hooks/lib/bash_safety_rules.py", "")], SHELL),
)
MERGED = [("hooks/lib/bash_safety_rules.py", "blocked-kill-with-signals-is-refused", "hooks/lib/bash_safety_rules.py"),
          ("hooks/lib/write_gate/overwrite.py", "write-guard-blocked-x", GATE),
          ("hooks/pretool-git-privilege-guard.py", "blocked-agent-git-push", LAUNCH),
          ("hooks/pretool-tool-policy.py", "blocked-by-tool-policy.v1-no", GATE)]


@pytest.mark.parametrize("order", [(0, 1, 2, 3), (2, 3, 0, 1), (2, 0, 3, 1), (0, 2, 1, 3)])
def test_the_reports_of_one_call_are_one_line_naming_every_rule(order):
    """A gate reports before its launcher and bash_safety_rules.py before its shell entry; the two processes of
    one call end in either order."""
    for i in order:
        assert R.write(payload(), *REPORTS[i])
    (line,) = lines()
    assert [(r["hook"], r["id"], r["by"]) for r in line["rules"]] == MERGED
    assert "BLOCKED by tool-policy.v1: no" in line["message"] and "kill with signals" in line["message"]


@pytest.mark.parametrize("order", [("Bash", "Monitor"), ("Monitor", "Bash")])
def test_a_call_handed_to_hooks_under_two_tool_names_names_both(order):
    """The CLI hands a Monitor's command to the Bash-matched hooks as a Bash call with the same id."""
    for tool, report in zip(order, (REPORTS[2], ([("hooks/pretool-monitor-command.py", "Monitor's command is refused\n")], LAUNCH))):
        assert R.write(payload(tool), *report)
    (line,) = lines()
    assert line["tool"] == "Bash|Monitor" and len(line["rules"]) == 2


def test_another_call_between_two_reports_is_kept_whole():
    R.write(payload(call="toolu_A"), *REPORTS[0])
    R.write(payload(call="toolu_B", session_id="another-session"), [("hooks/x.py", "B refused")], "hooks/x.py")
    R.write(payload(call="toolu_A"), *REPORTS[1])
    assert [(x["tool_use_id"], len(x["rules"])) for x in lines()] == [("toolu_A", 3), ("toolu_B", 1)]


def test_a_retry_is_a_line_of_its_own():
    for call in ("toolu_1", "toolu_2"):                 # the CLI gives the retry a new id
        R.write(payload(call=call), *REPORTS[0])
    assert len(lines()) == 2
    for _ in range(2):                                  # a payload without an id: the same hook reporting again
        R.write(payload(call=None), *REPORTS[2])
        R.write(payload(call=None), *REPORTS[3])        # and its parent, each time, is the same call's report
    assert [len(x["rules"]) for x in lines()] == [2, 2, 1, 1]
    for _ in range(2):                                  # a stop has no id and never merges
        R.write(payload(None, None, None, "SubagentStop", agent_id="a9"), [("hooks/a.py", "no")], "hooks/gate.py")
    assert len(lines()) == 6


def test_a_let_through_is_its_own_kind_beside_a_refusal_of_the_same_call():
    R.write(payload(), [("hooks/lib/bash_safety_rules.py", "BLOCKED: removal-policy — UNRESOLVED dynamic_command_head:x")],
            "hooks/lib/bash_safety_rules.py", R.UNPROVEN)
    R.write(payload(), *REPORTS[0])
    assert [(x["kind"], x["rules"][0]["id"]) for x in lines()] == [
        ("unproven", "blocked-removal-policy-unresolved-dynamic_command_head"), ("refusal", "blocked-by-tool-policy.v1-no")]


# ------------------------------------------------------------------ recording never decides

def test_a_record_that_cannot_be_written_is_false_and_raises_nothing(monkeypatch, tmp_path):
    blocked = tmp_path / "a-file"
    blocked.write_text("")
    monkeypatch.setenv("HOME", str(blocked))                                # no directory can be made below a file
    assert R.write(payload(), *REPORTS[0]) is False
    monkeypatch.setenv("HOME", str(tmp_path))
    assert R.write(payload(), *REPORTS[0]) is True

    def full(*_a, **_k):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(R.os, "pwrite", full)
    assert R.write(payload(call="toolu_02"), *REPORTS[0]) is False
    monkeypatch.undo()
    monkeypatch.setenv("HOME", str(tmp_path))
    os.chmod(R.directory(), 0o500)                                          # no permission (a non-root runner)
    R.write(payload(call="toolu_03"), *REPORTS[0])                          # whatever it returns, it returns
    os.chmod(R.directory(), 0o700)
    assert R.write(object(), [("hooks/x.py", object())], object()) is False


def test_a_held_lock_is_waited_for_a_bounded_time_then_given_up(monkeypatch):
    assert R.write(payload(), *REPORTS[0])
    day = next(Path(R.directory()).glob("*.jsonl"))
    monkeypatch.setattr(R, "LOCK_WAIT", 0.05)
    with open(day) as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        started = time.process_time()
        assert R.write(payload(call="toolu_02"), *REPORTS[0]) is False
        assert time.process_time() - started < 1.0                          # CPU seconds: it sleeps, it does not spin
    assert R.write(payload(call="toolu_02"), *REPORTS[0]) is True
    assert len(lines()) == 2


def test_a_hook_reports_through_a_writer_process_of_its_own(monkeypatch):
    R.report(json.dumps(payload()).encode(), [(str(HOOKS / "pretool-tool-policy.py"), "BLOCKED by x: no\n"),
                                              ("hooks/lib/write_gate/overwrite.py", "")], str(HOOKS / "pretool-write-gate.py"))
    R.report(payload(call="toolu_02"), [("hooks/lib/bash_safety_rules.py", "BLOCKED: removal-policy \u2014 UNRESOLVED x:y")],
             "hooks/lib/bash_safety_rules.py", R.UNPROVEN)
    first, second = lines()
    assert [(r["hook"], r["id"], r["by"]) for r in first["rules"]] == [      # one report: the rules in its order
        ("hooks/pretool-tool-policy.py", "blocked-by-x-no", "hooks/pretool-write-gate.py"),
        ("hooks/lib/write_gate/overwrite.py", "", "hooks/pretool-write-gate.py")]
    assert (first["kind"], second["kind"], second["tool_use_id"]) == ("refusal", "unproven", "toolu_02")
    assert second["rules"][0]["id"] == "blocked-removal-policy-unresolved-x"
    R.report(payload(call="toolu_03"), [("hooks/x.py", "no")], "hooks/x.py", "another kind")    # no such kind: no line


def test_a_report_never_raises_and_starts_nothing_for_a_payload_without_an_event(monkeypatch):
    def never(*_a, **_k):
        raise AssertionError("a writer process was started")
    monkeypatch.setattr(subprocess, "run", never)
    for p, rules in ((payload(event=None), [("hooks/x.py", "no")]), (payload(event="SessionStart"), [("hooks/x.py", "no")]),
                     (b"not json", [("hooks/x.py", "no")]), (payload(), [])):
        assert R.report(p, rules, "hooks/x.py") is None
    monkeypatch.undo()
    monkeypatch.setattr(R.sys, "executable", "/nonexistent/python")           # the writer cannot start
    assert R.report(payload(), [("hooks/x.py", "no")], "hooks/x.py") is None
    monkeypatch.setattr(R.sys, "executable", "/bin/false")                    # the writer fails
    assert R.report(payload(), [("hooks/x.py", "no")], "hooks/x.py") is None
    monkeypatch.setattr(R, "REPORT_WAIT", 0.2)
    monkeypatch.setattr(R.sys, "executable", "/bin/sleep")                    # the writer hangs: sleep <path> ... fails at once,
    monkeypatch.setattr(R.os.path, "abspath", lambda _p: "30")                # so it is told to sleep 30 s instead
    started = time.monotonic()
    assert R.report(payload(), [], "hooks/x.py") is None and R.report(payload(), [("1", "1")], "1", "1") is None
    assert time.monotonic() - started < 20
    assert lines() == []


LAUNCHER = """
import sys
sys.path.insert(0, {hooks!r})
from lib.{module} import Rule, main
sys.exit(main("PreToolUse", (Rule("allow", {allow!r}), Rule("refuse", {refuse!r}, ("Bash",)))))
"""


def _launch(tmp_path, home, tool, module):
    for name, body in (("allow", "import sys\nsys.exit(0)\n"),
                       ("refuse", "import sys\nsys.stderr.write('BLOCKED: scratch rule\\n')\nsys.exit(2)\n")):
        (tmp_path / f"{name}.py").write_text(body)
    launcher = tmp_path / "launch.py"
    launcher.write_text(LAUNCHER.format(hooks=str(HOOKS), module=module, allow=str(tmp_path / "allow.py"),
                                        refuse=str(tmp_path / "refuse.py")))
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
    p = subprocess.run([sys.executable, str(launcher)], input=json.dumps(payload(tool)), capture_output=True, text=True,
                       env=env, timeout=120)
    return p.returncode, p.stdout, p.stderr


@pytest.mark.parametrize("module", ["hook_launch", "hook_launch_fallback"])  # the launcher, and its fallback when it cannot load
def test_a_launcher_answers_the_same_with_and_without_a_writable_record(tmp_path, module):
    good, bad = tmp_path / "home", tmp_path / "not-a-directory"
    good.mkdir()
    bad.write_text("")
    for tool, code in (("Bash", 2), ("Read", 0)):
        assert _launch(tmp_path, good, tool, module) == _launch(tmp_path, bad, tool, module)
        assert _launch(tmp_path, good, tool, module)[0] == code
    records = list(good.rglob("refusals-*.jsonl"))
    assert len(records) == 1 and not list(bad.parent.rglob("not-a-directory/*"))
    rows = [json.loads(x) for x in records[0].read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["rules"] == [{"hook": str(tmp_path / "refuse.py"), "id": "blocked-scratch-rule",
                                                    "by": "hooks/launch.py"}]      # the allowed Read: no line


# ------------------------------------------------------------------ a private, bounded place

def test_the_directory_is_private_and_bounded(monkeypatch):
    assert R.write(payload(), *REPORTS[0])
    folder = Path(R.directory())
    day = next(folder.glob("*.jsonl"))
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700 and stat.S_IMODE(day.stat().st_mode) == 0o600
    old = folder / time.strftime("refusals-%Y-%m-%d.jsonl", time.gmtime(time.time() - (R.KEEP_DAYS + 2) * 86400))
    kept = folder / time.strftime("refusals-%Y-%m-%d.jsonl", time.gmtime(time.time() - (R.KEEP_DAYS - 2) * 86400))
    for f in (old, kept, folder / "notes.txt"):
        f.write_text("{}\n")
    day.unlink()                                                            # the next record starts the day's file
    assert R.write(payload(), *REPORTS[0])
    assert not old.exists() and kept.exists() and (folder / "notes.txt").exists()
    monkeypatch.setattr(R, "MAX_DAY_BYTES", day.stat().st_size)
    assert R.write(payload(call="toolu_02"), *REPORTS[0]) is False            # the day's file is full
    assert len(day.read_text().splitlines()) == 1


WRITER = """
import json, sys
sys.path.insert(0, {hooks!r})
from lib import refusal_record as R
R.LOCK_WAIT = 120  # a loaded runner may hold a writer off the processor longer than the hooks' bound
who, n = sys.argv[1], int(sys.argv[2])
for i in range(n):
    p = {{"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "Bash", "tool_input": {{"command": "c"}},
         "tool_use_id": f"shared-{{i}}"}}
    assert R.write(p, [(f"hooks/{{who}}.py", f"BLOCKED: rule of {{who}}")], f"hooks/{{who}}.py")
    p["tool_use_id"] = f"{{who}}-{{i}}"
    assert R.write(p, [(f"hooks/{{who}}.py", "BLOCKED: own")], f"hooks/{{who}}.py")
"""


def test_writers_running_at_once_lose_no_line_and_merge_every_shared_call(tmp_path):
    script = tmp_path / "writer.py"
    script.write_text(WRITER.format(hooks=str(HOOKS)))
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "PYTHONDONTWRITEBYTECODE": "1"}
    writers = [subprocess.Popen([sys.executable, str(script), f"w{k}", "40"], env=env) for k in range(6)]
    assert [w.wait(timeout=300) for w in writers] == [0] * 6
    found = lines()
    shared = {x["tool_use_id"]: x for x in found if x["tool_use_id"].startswith("shared-")}
    assert len(found) == 40 + 6 * 40 and len(shared) == 40
    assert all([r["hook"] for r in x["rules"]] == [f"hooks/w{k}.py" for k in range(6)] for x in shared.values())


# ------------------------------------------------------------------ one place for writer and reader

def _home(root: Path) -> Path:
    """A harness home with the record's writer and reader, and nothing else."""
    (root / "hooks" / "lib").mkdir(parents=True)
    (root / "scripts").mkdir()
    for rel in ("hooks/lib/refusal_record.py", "hooks/lib/harness_switch.py", "hooks/lib/__init__.py", "scripts/refusals"):
        shutil.copy(REPO / rel, root / rel)
    return root


def _writer_dir(hooks: Path, env: dict, cwd: Path) -> str:
    code = "import sys; sys.path.insert(0, sys.argv[1]); from lib import refusal_record as R; print(R.directory())"
    return subprocess.run([sys.executable, "-c", code, str(hooks)], env=env, cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def _reader_dir(script: Path, env: dict, cwd: Path) -> str:
    out = subprocess.run([sys.executable, str(script), "--json"], env=env, cwd=cwd, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)["record"]


def test_writer_and_reader_resolve_one_directory_in_every_layout(tmp_path):
    user = tmp_path / "user"
    base = {"PATH": os.environ["PATH"], "HOME": str(user), "PYTHONDONTWRITEBYTECODE": "1"}
    # a default install: the home is ~/.claude, no other environment
    default = _home(user / ".claude")
    here = _writer_dir(default / "hooks", base, tmp_path)
    assert here == _reader_dir(default / "scripts" / "refusals", base, tmp_path)
    assert here.startswith(str(user / ".local" / "state" / "claude-harness")) and here.endswith("/refusals")
    # a home elsewhere (a RAM disk), reached through ~/.claude and through an account's linked hooks/
    shutil.rmtree(default)
    real = _home(tmp_path / "shm" / "dot-claude")
    (user / ".claude").symlink_to(real)
    account = tmp_path / "accounts" / "one" / "claude"
    account.mkdir(parents=True)
    (account / "hooks").symlink_to(user / ".claude" / "hooks")
    seen = set()
    for hooks in (real / "hooks", user / ".claude" / "hooks", account / "hooks"):
        for extra in ({}, {"CLAUDE_CONFIG_DIR": str(account)}, {"CLAUDE_HOME": str(real), "CLAUDE_PROJECT_DIR": str(tmp_path)},
                      {"CLAUDE_STATE_DIR": str(tmp_path / "s"), "TMPDIR": str(tmp_path / "t"), "CLAUDE_COMPAT_RUNTIME": "codex"}):
            for cwd in (tmp_path, real):
                seen.add(_writer_dir(hooks, {**base, **extra}, cwd))
    seen.add(_reader_dir(user / ".claude" / "scripts" / "refusals", base, tmp_path))
    seen.add(_reader_dir(real / "scripts" / "refusals", {**base, "CLAUDE_CONFIG_DIR": str(account)}, real))
    assert len(seen) == 1 and seen != {here}                                # one place, and another home's is another
    other = _home(tmp_path / "second-home")
    assert _writer_dir(other / "hooks", base, tmp_path) not in seen


def _bash_hook(command: str, call: str, tmp_path) -> tuple[int, str]:
    """hooks/pretool-bash-safety.sh, as registered, on a Bash call; its project a git repository of its own."""
    project = tmp_path / "project"
    if not project.exists():
        project.mkdir()
        subprocess.run(["git", "init", "-q", str(project)], check=True, env={"PATH": os.environ["PATH"], "HOME": str(tmp_path),
                                                                              "GIT_CONFIG_GLOBAL": os.devnull})
    p = payload(tool_input={"command": command}, call=call, cwd=str(project))
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "CLAUDE_STATE_DIR", "CLAUDE_PYTHON_BIN",
                                                        "CLAUDE_PROTECTED_RUNTIME_FILE", "TMPDIR")}
    done = subprocess.run(["bash", str(HOOKS / "pretool-bash-safety.sh")], input=json.dumps(p), capture_output=True, text=True,
                          env={**env, "PYTHONDONTWRITEBYTECODE": "1", "GIT_CEILING_DIRECTORIES": str(tmp_path)},
                          cwd=project, timeout=300)
    return done.returncode, done.stderr


def test_the_bash_rules_report_their_own_refusal_once(tmp_path):
    """lib/bash_safety_rules.py refuses through refuse(), which reports the rule's own text; the shell entry's
    report at its exit 2 names the same file and adds no second rule and no second line."""
    code, stderr = _bash_hook("rm -rf /", "toolu_rm", tmp_path)
    assert code == 2 and stderr.strip()
    assert _bash_hook("echo hello", "toolu_echo", tmp_path)[0] == 0
    (line,) = lines()                                                      # the allowed call: no line
    (rule,) = line["rules"]
    assert (rule["hook"], rule["by"]) == ("hooks/lib/bash_safety_rules.py", "hooks/lib/bash_safety_rules.py")
    assert rule["id"] == R.rule_id(stderr, {"Bash"}) != ""
    assert line["message"] == stderr.strip("\n")[:R.MESSAGE_MAX]
    assert (line["tool_use_id"], line["refused"], line["tool"]) == ("toolu_rm", "rm -rf /", "Bash")


def test_the_bash_rules_can_report_a_command_let_through_unproven(tmp_path):
    """The seam for the removal policy's let-through: bash_safety_rules.record(text, "unproven")."""
    code = ("import json, sys; sys.argv = ['bash_safety_rules.py', sys.argv[1]]; sys.path.insert(0, sys.argv[1] + '/lib'); "
            "import bash_safety_rules as B; B.PAYLOAD = sys.stdin.read(); "
            "B.record('BLOCKED: removal-policy \u2014 UNRESOLVED dynamic_command_head:x=$(date)', 'unproven'); print('ALLOW')")
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, "-c", code, str(HOOKS)], input=json.dumps(payload(tool_input={"command": "x=$(date)"})),
                          capture_output=True, text=True, env=env, cwd=tmp_path, timeout=120)
    assert (done.returncode, done.stdout.strip()) == (0, "ALLOW"), done.stderr
    (line,) = lines()
    assert (line["kind"], line["refused"], line["tool_use_id"]) == ("unproven", "x=$(date)", "toolu_01")
    assert line["rules"] == [{"hook": "hooks/lib/bash_safety_rules.py", "by": "hooks/lib/bash_safety_rules.py",
                              "id": "blocked-removal-policy-unresolved-dynamic_command_head"}]


def test_a_shell_hook_reports_through_the_command_line(tmp_path):
    hook = tmp_path / "hook.sh"
    hook.write_text(textwrap.dedent(f"""\
        INPUT=$(cat)
        . "{HOOKS}/lib/refusal_record.sh" && trap refusal_record_on_exit EXIT
        case "$INPUT" in *refuse-me*) _SAID="BLOCKED: shell rule"; echo "$_SAID" >&2; exit 2 ;; esac
        case "$INPUT" in *relay-me*) _REFUSED_BY=hooks/lib/bash_safety_rules.py; exit 2 ;; esac
        case "$INPUT" in *fail-me*) exit 1 ;; esac
        exit 0
        """))
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "PYTHON_BIN": sys.executable, "PYTHONDONTWRITEBYTECODE": "1"}
    codes = []
    for i, command in enumerate(("refuse-me", "relay-me", "fail-me", "allow-me")):
        p = subprocess.run(["bash", str(hook)], input=json.dumps(payload(tool_input={"command": command}, call=f"t{i}")),
                           capture_output=True, text=True, env=env, timeout=120)
        codes.append(p.returncode)
    assert codes == [2, 2, 1, 0]
    assert [(x["tool_use_id"], x["rules"][0]["hook"], x["rules"][0]["id"], x["rules"][0]["by"]) for x in lines()] == [
        ("t0", str(hook), "blocked-shell-rule", str(hook)), ("t1", "hooks/lib/bash_safety_rules.py", "", str(hook))]


def test_the_writers_own_process_ends_itself_where_its_input_never_ends(tmp_path):
    """A shell hook's trap waits for the writer with no bound of its own: the writer's process ends itself
    REPORT_WAIT seconds (here 1) after it started, whatever it waits on, and leaves no line."""
    writer = _home(tmp_path / "harness") / "hooks" / "lib" / "refusal_record.py"
    text, bound = writer.read_text(), "REPORT_WAIT = 2.0, 30, 10 "
    assert text.count(bound) == 1
    writer.write_text(text.replace(bound, "REPORT_WAIT = 2.0, 30, 1 "))
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"}
    held = subprocess.Popen([sys.executable, str(writer), "refusal", "hooks/x.sh", "hooks/x.sh", "BLOCKED: no"],
                            stdin=subprocess.PIPE, env=env)                  # its input stays open: the payload never ends
    try:
        assert held.wait(timeout=60) == -signal.SIGALRM
    finally:
        held.kill()
        held.stdin.close()
    assert not list(tmp_path.glob(".local/state/claude-harness/*/refusals/*.jsonl"))
