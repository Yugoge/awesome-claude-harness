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
one of them at least must make the file refuse. So a registered hook that refuses and reports
nothing fails here, as does one this test has no way to make refuse, and so does every case once
the writer is gone (scripts/refusals, the reader, is tests/test_refusals_reader.py's).

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

from lib import launch_settings, refusal_record  # noqa: E402
from tests.replay import sites  # noqa: E402

MARK = "STAND-IN REFUSAL"
INPUTS = {"Bash": {"command": "true"}, "Monitor": {"command": "true"}, "TodoWrite": {"todos": []},
          "Agent": {"description": "d", "prompt": "p", "subagent_type": "general-purpose", "run_in_background": False}}
STAND_IN = {".py": {2: f"import sys\nsys.stderr.write({MARK!r} + '\\n')\nsys.exit(2)\n", 1: "import sys\nsys.exit(1)\n",
                    0: "import sys\nsys.exit(0)\n"},
            ".sh": {2: f"echo '{MARK}' >&2\nexit 2\n", 1: "exit 1\n", 0: "exit 0\n"}}


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
    """A copy of hooks/ (the other folders linked) with a home, state, temp and project directory of its own."""

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

    def payload(self, event: str, matcher: str) -> dict:
        self.n += 1
        p = {"session_id": "0c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f", "hook_event_name": event, "cwd": str(self.root / "project"),
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
        target = self.home / stand_in
        kept = target.read_bytes()
        shutil.rmtree(self.root / "home" / ".local", ignore_errors=True)
        try:
            target.write_text(STAND_IN[target.suffix][code])
            done = subprocess.run([sys.executable if command.endswith(".py") else "bash", str(self.home / command)],
                                  input=json.dumps(self.payload(event, matcher)), capture_output=True, text=True,
                                  env=self.env, cwd=self.root / "project", timeout=600)
        finally:
            target.write_bytes(kept)
        lines = [json.loads(x) for f in (self.root / "home").glob(".local/state/claude-harness/*/refusals/*.jsonl")
                 for x in f.read_text().splitlines()]
        return done.returncode, done.stderr, lines


@pytest.fixture(scope="module")
def scratch(tmp_path_factory):
    return Scratch(tmp_path_factory.mktemp("sites"))


def test_every_blocking_site_refuses_into_the_record(scratch):
    enumerated = sites.Enumerator(str(REPO))
    commands = registered_commands()
    cases, skipped = {}, set()          # (command, event, stand-in file) -> (matcher, the stand-in is a rule of the command)
    for site in enumerated.sites():
        for hook, event, matcher in site.regs:
            command = commands[(event, hook)]
            if event not in refusal_record.EVENTS:
                skipped.add((event, command))
            elif site.file != command:
                cases.setdefault((command, event, site.file), (matcher, site.role in ("main", "rule")))
            else:  # the registered file's own site: through each file it runs
                for child in enumerated.children.get(command, []):
                    cases.setdefault((command, event, child), (matcher, False))
                assert enumerated.children.get(command), f"{command} refuses at {site.id} and runs no file a test can replace"
    assert cases and all(event in ("SessionStart", "SessionEnd", "SubagentStart", "Notification") for event, _ in skipped)

    problems, refused, rows = [], set(), []
    for (command, event, stand_in), (matcher, is_rule) in sorted(cases.items()):
        for code in (2, 1, 0) if stand_in in enumerated.children.get(command, []) else (2,):
            status, stderr, lines = scratch.run(command, stand_in, code, event, matcher)
            rows.append(f"{event:18s} {command:36s} {stand_in:48s} stand-in exit {code}: exit {status}, {len(lines)} line(s)")
            where = f"{command} at {event} with {stand_in} exiting {code}"
            if (status == 2) != (len(lines) == 1) or len(lines) > 1:
                problems.append(f"{where}: exit {status} and {len(lines)} line(s) in the record\n{stderr[-600:]}")
            elif status == 2:
                refused.add((command, event))
                if lines[0]["event"] != event or lines[0]["kind"] != refusal_record.REFUSAL or not lines[0]["rules"]:
                    problems.append(f"{where}: the line is {lines[0]}")
            if is_rule and code == 2 and not (status == 2 and lines and MARK in lines[0]["message"]
                                              and any(r["hook"] == stand_in for r in lines[0]["rules"])):
                problems.append(f"{where}: a rule's refusal is not in the record under its file\n{stderr[-600:]}")
    print("\n" + "\n".join(rows))
    silent = sorted({(c, e) for c, e, _ in cases} - refused)
    assert not silent, f"no stand-in made these registered commands refuse, so nothing shows they report: {silent}"
    assert not problems, f"{len(problems)} of {len(rows)} runs:\n" + "\n\n".join(problems)
