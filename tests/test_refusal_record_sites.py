"""Every blocking site of the registered hooks leaves a line in the refusal record.

The sites are the replay suite's own enumeration (tests/replay/sites.py), read when the test runs:
nothing here lists a hook, a rule or a site. For each registered command of an event at which an
exit 2 refuses (hooks/lib/refusal_record.py EVENTS), and each file the enumeration finds a blocking
site in under that command, a scratch copy of the hooks runs the command, as settings.json registers
it, with that file standing in: it prints a marked reason and exits 2. Whatever the command answers,
it exits 2 if and only if the record then holds exactly one line for the call; and where the
stand-in is a rule of a launcher or of a gate, the command does refuse and the line carries the
stand-in's reason.

A site in the registered file itself is reached through the files that file runs (its children):
each stands in refusing, failing (exit 1) and silent (exit 0), with the same if-and-only-if, and
one of them at least must make the file refuse. The second test holds every such site to it: the
runs are traced, so each names the line it refuses at, and a site of the enumeration that no run
refuses at fails (REACH stages the states the children's stand-ins alone do not reach). So a
registered hook that refuses and reports nothing fails here, as does one these tests have no way
to make refuse, and so does every case once the writer is gone (scripts/refusals, the reader, is
tests/test_refusals_reader.py's).

Run with: python3 -m pytest tests/test_refusal_record_sites.py -q -s
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "hooks"))

from lib import launch_settings  # noqa: E402
from tests.replay import sites  # noqa: E402

try:
    from lib import refusal_record  # noqa: E402
except ImportError:  # the writer is gone: every command below fails, by name, instead of this file not loading
    refusal_record = None

MARK = "STAND-IN REFUSAL"
INPUTS = {"Bash": {"command": "true"}, "Monitor": {"command": "true"}, "TodoWrite": {"todos": []},
          "Agent": {"description": "d", "prompt": "p", "subagent_type": "general-purpose", "run_in_background": False}}
STAND_IN = {".py": {2: f"import sys\nsys.stderr.write({MARK!r} + '\\n')\nsys.exit(2)\n", 1: "import sys\nsys.exit(1)\n",
                    0: "import sys\nsys.exit(0)\n"},
            ".sh": {2: f"echo '{MARK}' >&2\nexit 2\n", 1: "exit 1\n", 0: "exit 0\n"}}
SESSION = "0c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f"
# A run that names on stderr each line of the registered file it executes: +@<line>@ (a shell file: and the command).
TRACED = {".sh": ["bash", "-c", "PS4='+@${LINENO}@ '; set -x; . \"$0\""],
          ".py": [sys.executable, "-c", "import runpy, sys\npath = sys.argv[1]\nsys.argv = [path]\n"
                  "def lines(frame, event, arg):\n    if frame.f_code.co_filename != path:\n        return None\n"
                  "    if event == 'line':\n        sys.stderr.write('+@%d@\\n' % frame.f_lineno)\n    return lines\n"
                  "sys.settrace(lines)\nrunpy.run_path(path, run_name='__main__')\n"]}
# The states that reach the sites of a registered file itself where one child standing in does not: {file below
# the scratch harness: its text for the run (None: the file is gone)}. The enumeration says which sites there are.
_SAYS = "import sys\nsys.stdout.write({!r})\nsys.exit({})\n"
_GUARD, _SNAPSHOT = "hooks/lib/git_clean_guard.py", "hooks/lib/checkpoint-core.sh"
_GRANTED = {"hooks/lib/bash_safety_rules.py": _SAYS.format("CONSENT", 0)}  # a destructive clean the human released
_TYPED_DEV = "".join(json.dumps(x) + "\n" for x in (
    {"type": "queue-operation", "operation": "enqueue", "content": "/dev"},
    {"type": "user", "sessionId": SESSION, "message": {"role": "user", "content":
     "<command-message>dev</command-message>\n<command-name>/dev</command-name>\n<command-args></command-args>"}},
    {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}))
REACH = {
    "hooks/pretool-bash-safety.sh": [
        {**_GRANTED, _GUARD: None}, {**_GRANTED, _GUARD: _SAYS.format("", 0)}, {**_GRANTED, _GUARD: _SAYS.format("", 127)},
        {**_GRANTED, _GUARD: _SAYS.format("", 11)}, {**_GRANTED, _GUARD: _SAYS.format("", 10), _SNAPSHOT: None},
        {**_GRANTED, _GUARD: _SAYS.format("", 10), _SNAPSHOT: "write_checkpoint() { trap : EXIT; return 1; }\n"},
        {**_GRANTED, _GUARD: _SAYS.format("", 10), _SNAPSHOT: "write_checkpoint() { return 0; }\n"}],
    "hooks/stop-launch.py": [  # the coordinator cannot decide: under a typed /dev the launcher blocks, else it allows
        {"hooks/stop-workflow-coordinator.py": _SAYS.format("", 1), "../none.jsonl": _TYPED_DEV},
        {"hooks/stop-workflow-coordinator.py": _SAYS.format("", 1)}],
}


def registered_commands() -> dict:
    """{(event, hook file as the enumeration names it): the command file settings.json registers for it}: the
    hook itself, or the launcher whose table runs it."""
    settings = json.loads((REPO / "settings.json").read_text())
    out = {}
    for event, groups in settings["hooks"].items():
        for group in groups:
            for hook in group["hooks"]:
                found = re.findall(r"""/((?:hooks|scripts)/[^"'\s]+)""", hook.get("command") or "")
                if found:
                    rules = launch_settings.rules(str(REPO), found[-1])
                    for file in [found[-1]] if rules is None else ["hooks/" + r[0] for r in rules]:
                        out[(event, file)] = found[-1]
    return out


class Scratch:
    """A copy of hooks/ (the other folders linked) with a home, state, temp and project directory of its own. The
    harness copy and the project are each a git repository: a hook that runs git there stays inside it."""

    def __init__(self, root: Path):
        self.root, self.home, self.n = root, root / "harness", 0
        shutil.copytree(REPO / "hooks", self.home / "hooks", ignore=shutil.ignore_patterns("tests", "__pycache__"))
        for name in ("scripts", "policies", "commands", "agents", "templates", "schemas"):
            (self.home / name).symlink_to(REPO / name)
        for name in ("settings.json", "VERSION"):
            shutil.copy(REPO / name, self.home / name)
        for name in ("home", "state", "tmp", "project"):
            (root / name).mkdir()
        self.env = {"PATH": os.environ["PATH"], "HOME": str(root / "home"), "CLAUDE_CONFIG_DIR": str(root / "home" / ".claude"),
                    "CLAUDE_STATE_DIR": str(root / "state"), "TMPDIR": str(root / "tmp"), "CLAUDE_HOME": str(self.home),
                    "CLAUDE_PROJECT_DIR": str(root / "project"), "CLAUDE_PYTHON_BIN": sys.executable, "LANG": "C.UTF-8",
                    "PYTHONDONTWRITEBYTECODE": "1", "GIT_CEILING_DIRECTORIES": str(root), "GIT_CONFIG_GLOBAL": os.devnull,
                    "GIT_CONFIG_NOSYSTEM": "1"}
        for repo in (self.home, root / "project"):
            subprocess.run(["git", "init", "-q", str(repo)], check=True, env=self.env)

    def payload(self, event: str, matcher: str) -> dict:
        self.n += 1
        p = {"session_id": SESSION, "hook_event_name": event, "cwd": str(self.root / "project"),
             "transcript_path": str(self.root / "none.jsonl"), "permission_mode": "default", "stop_hook_active": False}
        if event in refusal_record.EVENTS[:3]:
            tool = matcher.split("|")[0] if re.fullmatch(r"[A-Za-z0-9_|]+", matcher) else "Glob"
            p.update(tool_name=tool, tool_use_id=f"toolu_{self.n:04d}", tool_response={},
                     tool_input=INPUTS.get(tool, {"file_path": str(self.root / "project" / "new.txt"), "content": "x",
                                                  "old_string": "a", "new_string": "b"}))
        elif event == "UserPromptSubmit":
            p["prompt"] = "hello"
        elif event == "SubagentStop":
            p.update(agent_id="a0123456789abcdef", agent_type="general-purpose",
                     agent_transcript_path=str(self.root / "none-agent.jsonl"))
        return p

    def run(self, command: str, stand_in: str, code: int, event: str, matcher: str) -> tuple[int, str, list]:
        """(exit status, stderr, the record's lines) of `command` run with `stand_in` exiting `code`."""
        return self.staged(command, {stand_in: STAND_IN[Path(stand_in).suffix][code]}, event, matcher)

    def staged(self, command: str, files: dict, event: str, matcher: str, traced: bool = False) -> tuple[int, str, list]:
        """(exit status, stderr, the record's lines) of `command` run, as registered or `traced`, with each of `files`
        holding the given text or gone (None); every file is as it was afterwards."""
        kept = {}
        shutil.rmtree(self.root / "home" / ".local", ignore_errors=True)
        try:
            for name, text in files.items():
                target = self.home / name
                kept[target] = target.exists()
                if kept[target]:
                    target.rename(target.with_name(target.name + ".kept"))
                if text is not None:
                    target.write_text(text)
            start = TRACED[Path(command).suffix] if traced else [sys.executable if command.endswith(".py") else "bash"]
            done = subprocess.run([*start, str(self.home / command)],
                                  input=json.dumps(self.payload(event, matcher)), capture_output=True, text=True,
                                  env=self.env, cwd=self.root / "project", timeout=600)
        finally:
            for target, existed in kept.items():
                target.unlink(missing_ok=True)
                if existed:
                    target.with_name(target.name + ".kept").rename(target)
        lines = [json.loads(x) for f in (self.root / "home").glob(".local/state/claude-harness/*/refusals/*.jsonl")
                 for x in f.read_text().splitlines()]
        return done.returncode, done.stderr, lines


@pytest.fixture(scope="module")
def scratch(tmp_path_factory):
    return Scratch(tmp_path_factory.mktemp("sites"))


@pytest.fixture(scope="module")
def cases():
    """{registered command: {(event, stand-in file): (matcher, the stand-in is a rule of the command)}} for
    every blocking site of the enumeration, at the events an exit 2 refuses; the files each command runs; and
    {registered command: {(event, matcher): the lines of the sites in the command's file itself}}."""
    assert refusal_record is not None, "hooks/lib/refusal_record.py, the refusal record's writer, does not load"
    enumerated, commands = sites.Enumerator(str(REPO)), registered_commands()
    out, elsewhere, own = {}, set(), {}
    for site in enumerated.sites():
        for hook, event, matcher in site.regs:
            command = commands[(event, hook)]
            if event not in refusal_record.EVENTS:
                elsewhere.add(event)
            elif site.file != command:
                out.setdefault(command, {}).setdefault((event, site.file), (matcher, site.role in ("main", "rule")))
            else:  # the registered file's own site: through each file it runs
                own.setdefault(command, {}).setdefault((event, matcher), set()).add(int(site.line))
                children = enumerated.children.get(command, [])
                assert children, f"{command} refuses at {site.id} and runs no file a test can stand in for"
                for child in children:
                    out.setdefault(command, {}).setdefault((event, child), (matcher, False))
    assert out and elsewhere <= {"SessionStart", "SessionEnd", "SubagentStart", "Notification"}, elsewhere
    return out, enumerated.children, own


@pytest.mark.parametrize("command", sorted(set(registered_commands().values())))
def test_every_blocking_site_refuses_into_the_record(scratch, cases, command):
    """One registered command of settings.json: every file with a blocking site under it, at the events an exit 2
    refuses. A command the enumeration finds no such site under has nothing to report and passes."""
    by_command, children, _own = cases
    problems, refused, rows = [], set(), []
    for (event, stand_in), (matcher, is_rule) in sorted(by_command.get(command, {}).items()):
        for code in (2, 1, 0) if stand_in in children.get(command, []) else (2,):
            status, stderr, lines = scratch.run(command, stand_in, code, event, matcher)
            rows.append(f"{event:18s} {command:36s} {stand_in:48s} stand-in exit {code}: exit {status}, {len(lines)} line(s)")
            where = f"{command} at {event} with {stand_in} exiting {code}"
            if (status == 2) != (len(lines) == 1) or len(lines) > 1:
                problems.append(f"{where}: exit {status} and {len(lines)} line(s) in the record\n{stderr[-600:]}")
            elif status == 2:
                refused.add(event)
                if lines[0]["event"] != event or lines[0]["kind"] != refusal_record.REFUSAL or not lines[0]["rules"]:
                    problems.append(f"{where}: the line is {lines[0]}")
            if is_rule and code == 2 and not (status == 2 and lines and MARK in lines[0]["message"]
                                              and any(r["hook"] == stand_in for r in lines[0]["rules"])):
                problems.append(f"{where}: a rule's refusal is not in the record under its file\n{stderr[-600:]}")
    print("\n" + "\n".join(rows or [f"{command}: no blocking site at an event where an exit 2 refuses"]))
    silent = sorted({event for event, _ in by_command.get(command, {})} - refused)
    assert not silent, f"no stand-in made {command} refuse at {silent}, so nothing shows it reports there"
    assert not problems, f"{len(problems)} of {len(rows)} runs:\n" + "\n\n".join(problems)


def test_every_site_in_a_registered_file_itself_is_reached_and_recorded(scratch, cases):
    """The blocking sites the enumeration finds in the registered files themselves (the Bash hook's fail-closed
    blocks around a released clean, the Stop launcher's own block, ...): each is refused at by a traced run, a
    child standing in or a state of REACH, and every run exits 2 if and only if the record holds one line."""
    _by_command, children, own = cases
    assert own, "the enumeration finds no blocking site in a registered file: this test would hold nothing"
    problems, rows = [], []
    for command, registrations in sorted(own.items()):
        at_exit = " exit 2" if command.endswith(".sh") else ""
        runs = [{child: STAND_IN[Path(child).suffix][code]} for child in children.get(command, []) for code in (2, 1, 0)]
        for (event, matcher), sites_at in sorted(registrations.items()):
            reached = set()
            for files in runs + REACH.get(command, []):
                status, stderr, lines = scratch.staged(command, files, event, matcher, traced=True)
                at = {n for n in sites_at if re.search(rf"^\++@{n}@{at_exit}$", stderr, re.M)}
                rows.append(f"{event:12s} {command:36s} exit {status}, {len(lines)} line(s), site line {sorted(at) or '-'}: "
                            f"{', '.join(f'{k}={v if v is None else len(v)}' for k, v in sorted(files.items()))}")
                if (status == 2) != (len(lines) == 1) or len(lines) > 1 or (at and status != 2):
                    problems.append(f"{rows[-1]}\n{stderr[-600:]}")
                reached |= at
            if sites_at - reached:
                problems.append(f"{command} at {event}: no run refuses at line(s) {sorted(sites_at - reached)}, "
                                "so nothing shows the site there reports; stage the state in REACH")
    print("\n" + "\n".join(rows))
    assert not problems, f"{len(problems)} problem(s) in {len(rows)} runs:\n" + "\n\n".join(problems)
