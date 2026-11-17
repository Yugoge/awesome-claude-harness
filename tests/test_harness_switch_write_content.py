"""hooks/pretool-harness-switch-guard.py: the Write / Edit content rules judge the file's kind and the value.

Naming the switch's state <H>/.harness-switch/ in a written file is refused outside a harness
checkout, except in prose (.md, .txt, .rst), where only a line that writes it (rm, touch, mkdir,
mv, cp, tee, a `>` redirect, sed -i, a `cd` into it, an assignment of it, an open(..., 'w'), ...)
is refused. A settings*.json is refused when the document the call leaves sets disableAllHooks to
a truthy value (true, "true", 1, any value JavaScript reads as true; a duplicate key or a \\u
escape included), and when that document cannot be read while the call's text names the key;
`{"disableAllHooks": false}` in a fixture passes.

Each case runs the hook as Claude Code does (a PreToolUse payload on stdin) from a harness home at
~/.claude in a throwaway HOME (a copy of the tree's hooks/), the call made from a directory
outside any harness checkout.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATE = "~/.claude/.harness-switch"


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = tmp_path_factory.mktemp("content")
    home = root / "home"
    h = home / ".claude"
    shutil.copytree(ROOT / "hooks", h / "hooks", ignore=shutil.ignore_patterns("tests", "__pycache__"))
    (h / "settings.json").write_text('{"env": {"A": "1"}, "hooks": {}}\n')
    (h / ".harness-switch").mkdir()
    (h / ".harness-switch" / "state.json").write_text("{}\n")
    work = root / "work"
    (work / ".claude").mkdir(parents=True)
    (work / "tests" / "fixtures").mkdir(parents=True)
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDE_CONFIG_DIR", "CLAUDE_PROJECT_DIR", "CLAUDE_HOME", "CLAUDE_TASK_ID",
                        "CLAUDE_SESSION_ID", "CLAUDE_AGENT_ID") and not k.startswith("GIT_")}
    env["HOME"] = str(home)
    return {"home": home, "h": h, "work": work, "env": env, "hook": h / "hooks" / "pretool-harness-switch-guard.py"}


def call(box, tool, tool_input, actor="main"):
    payload = {"tool_name": tool, "tool_input": tool_input, "cwd": str(box["work"]), "session_id": "S1"}
    if actor == "subagent":
        payload["agent_id"] = "sub-1"
    proc = subprocess.run([sys.executable, str(box["hook"])], input=json.dumps(payload), capture_output=True,
                          text=True, env=box["env"], cwd=str(box["work"]), timeout=60)
    return proc.returncode, proc.stderr


def write(box, path, content, actor="main"):
    return call(box, "Write", {"file_path": path, "content": content}, actor)


# ------------------------------------------------------------- naming the switch's state

PROSE_MENTIONS = [
    ("/tmp/audit-notes.md", "The switch keeps its state in %s/ (read it with /harness status).\n" % STATE),
    ("docs/notes.md", "The switch keeps its state in %s/.\n" % STATE),
    ("docs/notes.txt", "state dir: %s/\n" % STATE),
    ("docs/notes.rst", "The state lives in ``%s/``.\n" % STATE),
    ("docs/NOTES.MD", "See %s/state.json.\n" % STATE),
    ("docs/quote.md", "> The state lives in %s/.\n" % STATE),
    ("docs/read.md", "```bash\ncat %s/state.json\nls -la %s/\n```\n" % (STATE, STATE)),
    ("docs/arrow.md", "/harness off -> %s/off\n" % STATE),
]


@pytest.mark.parametrize("path,content", PROSE_MENTIONS)
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_prose_that_only_mentions_the_state_passes(box, path, content, actor):
    rc, err = write(box, path, content, actor)
    assert rc == 0, (path, err)


def test_edit_and_multiedit_of_prose_mentioning_the_state_pass(box):
    rc, err = call(box, "Edit", {"file_path": "docs/notes.md", "old_string": "a",
                                 "new_string": "see %s/state.json" % STATE})
    assert rc == 0, err
    rc, err = call(box, "MultiEdit", {"file_path": "docs/notes.md", "edits": [
        {"old_string": "a", "new_string": "the dir %s/" % STATE}]})
    assert rc == 0, err


PROSE_WRITES = [
    "rm -rf %s" % STATE,
    "touch %s/off" % STATE,
    "mkdir -p %s" % STATE,
    "echo x > %s/off" % STATE,
    "echo x>%s/off" % STATE,
    "echo x >> %s/state.json" % STATE,
    "printf x | tee %s/off" % STATE,
    "mv /tmp/s %s/state.json" % STATE,
    "cp /tmp/s %s/state.json" % STATE,
    "ln -s /tmp/s %s/off" % STATE,
    "sed -i s/a/b/ %s/state.json" % STATE,
    "cd %s && touch off" % STATE,
    "D=%s; touch $D/off" % STATE,
    "export D=%s" % STATE,
    "open('%s/off', 'w').write('x')" % STATE,
    "Path('%s/off').write_text('x')" % STATE,
    "    rmdir %s" % STATE,
    "`rm -r %s`" % STATE,
    "exec 3<>%s/off" % STATE,
    "python3 -c \"import os; os.mknod('%s/off')\"" % STATE,
    "bash -c 'eval x %s'" % STATE,
]


@pytest.mark.parametrize("line", PROSE_WRITES)
@pytest.mark.parametrize("path", ["notes.md", "/tmp/audit-notes.md", "docs/n.txt", "docs/n.rst"])
def test_prose_with_a_write_near_the_state_is_refused(box, line, path):
    rc, err = write(box, path, "Some notes.\n\n%s\n" % line)
    assert rc == 2 and "naming the switch's state" in err, (path, line, err)


def test_edit_and_multiedit_of_prose_writing_the_state_are_refused(box):
    rc, err = call(box, "Edit", {"file_path": "notes.md", "old_string": "a", "new_string": "rm -rf %s" % STATE})
    assert rc == 2, err
    rc, err = call(box, "MultiEdit", {"file_path": "notes.md", "edits": [
        {"old_string": "a", "new_string": "ok"}, {"old_string": "b", "new_string": "touch %s/off" % STATE}]},
        "subagent")
    assert rc == 2, err


NON_PROSE = ["scripts/x.sh", "x.json", "conf/x.yaml", "conf/x.yml", "conf/x.toml", "x.ini", "x.cfg", "x.py",
             "x.js", "x.ts", "Makefile", "x", "x.mdx", "x.md.sh", "x.bash", "x.zsh", "x.ps1", "x.html",
             "notes.markdown"]


@pytest.mark.parametrize("path", NON_PROSE)
def test_any_other_kind_naming_the_state_is_refused(box, path):
    rc, err = write(box, path, "# the state: %s/\n" % STATE)
    assert rc == 2 and "naming the switch's state" in err, (path, err)


def test_a_script_writing_the_state_is_refused(box):
    rc, err = write(box, "scripts/x.sh", "#!/bin/sh\ntouch %s/off\n" % STATE)
    assert rc == 2, err
    rc, err = call(box, "Edit", {"file_path": "x.py", "old_string": "a", "new_string": "'%s'" % STATE}, "subagent")
    assert rc == 2, err


def test_writing_under_the_state_is_refused_whatever_the_kind(box):
    rc, err = write(box, str(box["h"] / ".harness-switch" / "notes.md"), "x")
    assert rc == 2 and "writes the switch's state" in err, err


# --------------------------------------------------------------------- disableAllHooks

FALSY = ['{"disableAllHooks": false}', '{"disableAllHooks": null}', '{"disableAllHooks": 0}',
         '{"disableAllHooks": ""}', '{"model": "x", "disableAllHooks": false, "env": {}}',
         '﻿{"disableAllHooks": false}']


@pytest.mark.parametrize("content", FALSY)
@pytest.mark.parametrize("path", ["tests/fixtures/settings.example.json", "settings.local.json",
                                  "tests/fixtures/settings.json"])
def test_a_falsy_disableallhooks_outside_the_cli_files_passes(box, content, path):
    rc, err = write(box, path, content)
    assert rc == 0, (path, content, err)


def test_the_lane_fixture_example_passes(box):
    rc, err = write(box, "tests/fixtures/settings.example.json", '{"disableAllHooks": false}', "subagent")
    assert rc == 0, err


def test_an_edit_leaving_disableallhooks_false_passes(box):
    f = box["work"] / "tests" / "fixtures" / "settings.edit.json"
    f.write_text('{"model": "x"}\n')
    rc, err = call(box, "Edit", {"file_path": str(f), "old_string": '"model": "x"',
                                 "new_string": '"model": "x", "disableAllHooks": false'})
    assert rc == 0, err


TRUTHY = ['{"disableAllHooks": true}', '{"disableAllHooks": "true"}', '{"disableAllHooks": 1}',
          '{"disableAllHooks": "false"}', '{"disableAllHooks": []}', '{"disableAllHooks": {}}',
          '{"disableAllHooks": -1}', '{"disableAllHooks": false, "disableAllHooks": true}',
          '{"disableAllHooks": true, "disableAllHooks": false}', '{"disableAll\\u0048ooks": true}']


@pytest.mark.parametrize("content", TRUTHY)
@pytest.mark.parametrize("path", [".claude/settings.json", "tests/fixtures/settings.example.json",
                                  ".claude/settings.local.json", "settings.json"])
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_a_truthy_disableallhooks_is_refused(box, content, path, actor):
    rc, err = write(box, path, content, actor)
    assert rc == 2 and "disableAllHooks" in err, (path, content, err)


def test_an_unreadable_settings_document_naming_the_key_is_refused(box):
    for content in ('{"disableAllHooks": false, // c\n}', '{"disableAllHooks": false,}', "disableAllHooks"):
        rc, err = write(box, "tests/fixtures/settings.example.json", content)
        assert rc == 2 and "disableAllHooks" in err, (content, err)


def test_an_edit_flipping_disableallhooks_to_true_is_refused(box):
    f = box["work"] / "tests" / "fixtures" / "settings.flip.json"
    f.write_text('{"disableAllHooks": false}\n')
    rc, err = call(box, "Edit", {"file_path": str(f), "old_string": "false", "new_string": "true"})
    assert rc == 2 and "disableAllHooks" in err, err
    rc, err = call(box, "MultiEdit", {"file_path": str(f), "edits": [{"old_string": "false", "new_string": "1"}]})
    assert rc == 2 and "disableAllHooks" in err, err


def test_an_edit_naming_the_key_whose_result_is_unknown_is_refused(box):
    f = box["work"] / "tests" / "fixtures" / "settings.unknown.json"
    f.write_text('{"model": "x"}\n')
    rc, err = call(box, "Edit", {"file_path": str(f), "old_string": "absent", "new_string": '"disableAllHooks": false'})
    assert rc == 2 and "disableAllHooks" in err, err
    rc, err = call(box, "NotebookEdit", {"notebook_path": str(f), "new_source": '"disableAllHooks": false'})
    assert rc == 2 and "disableAllHooks" in err, err


def test_the_cli_settings_files_keep_their_key_rule(box):
    # a falsy value passes the disableAllHooks rule, but adding the key to a CLI-loaded file stays the owner's
    rc, err = write(box, ".claude/settings.json", '{"disableAllHooks": false}')
    assert rc == 2 and "settings file" in err, err
    rc, err = write(box, str(box["h"] / "settings.json"), '{"disableAllHooks": false}')
    assert rc == 2, err


def test_a_link_is_judged_by_both_its_names(box):
    work = box["work"]
    (work / "real.md").write_text("")
    (work / "real.sh").write_text("")
    for link, target in (("link.sh", "real.md"), ("link.md", "real.sh")):
        if not (work / link).is_symlink():
            (work / link).symlink_to(work / target)
        rc, err = write(box, str(work / link), "the state: %s/\n" % STATE)
        assert rc == 2 and "naming the switch's state" in err, (link, err)
