"""hooks/pretool-harness-switch-guard.py: the Write / Edit content rules judge the file's kind and the value.

Naming the switch's state <H>/.harness-switch/ in a written file is refused outside a harness
checkout, except in prose (.md, .txt, .rst), where a line naming it passes only as a proven
mention: no shell metacharacter ($ < > | ; & \\ ( ) { } * ? [ ] = or a backtick but the inline-code
ticks around the directory's path alone), no word starting with `-`, no other path or URL, no file
name after the directory, not in a fenced or indented code block, not continued from a line ending
in `\\`, not inside a quote or heredoc opened above, no shell function or alias in the file, and a
first word that is no builtin, reserved word or program; every other line naming it is refused.
A settings*.json is refused when the document the call leaves sets disableAllHooks to a truthy value (true, "true", 1, any value JavaScript reads as true; a duplicate key or a \\u
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
    ("/tmp/audit-notes.md", "The switch keeps its state in %s/\n" % STATE),
    ("/tmp/audit-notes.md", "The switch keeps its state in %s/.\n" % STATE),
    ("/tmp/audit-notes.md", "The switch keeps its state in `%s/`.\n" % STATE),
    ("docs/notes.md", "The switch keeps its state in %s/.\n" % STATE),
    ("docs/notes.md", "# Notes\n\nThe switch keeps its state in `%s/`, read by the owner.\n" % STATE),
    ("docs/notes.md", "# Notes\n\nThe switch keeps its state in `%s/`.\n\n- Nothing else.\n1. Finished\n" % STATE),
    ("docs/notes.txt", "state dir: %s/\n" % STATE),
    ("docs/notes.rst", "The state lives in ``%s/``.\n" % STATE),
    ("docs/NOTES.MD", "The STATE lives in .harness-switch/ under the home.\n"),
    ("docs/notes.md", "%s/ holds the state.\n" % STATE),
]


@pytest.mark.parametrize("path,content", PROSE_MENTIONS)
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_prose_that_only_mentions_the_state_passes(box, path, content, actor):
    rc, err = write(box, path, content, actor)
    assert rc == 0, (path, err)


def test_edit_and_multiedit_of_prose_mentioning_the_state_pass(box):
    rc, err = call(box, "Edit", {"file_path": "docs/notes.md", "old_string": "a",
                                 "new_string": "the dir is %s/" % STATE})
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


# The verifier's forms (OB-L35 round 2): writers no verb list named, and a write spread over lines.
VERIFIER_FORMS = [
    "tar -xf /tmp/s.tar -C %s" % STATE,
    "curl -so %s/off https://x.example/off" % STATE,
    "wget -qO %s/off https://x.example/off" % STATE,
    "git clone /tmp/r %s" % STATE,
    "echo off | sponge %s/off" % STATE,
    "unzip /tmp/s.zip -d %s" % STATE,
    "patch %s/state.json < /tmp/p" % STATE,
    "git -C %s init" % STATE,
    "find %s -delete" % STATE,
    "for d in %s; do\n  : > \"$d/off\"\ndone" % STATE,
    "export D=\\\n%s\ntouch $D/off" % STATE,
    "printf off >\\\n%s/off" % STATE,
]

# Lines with no metacharacter, dash word or other path that still run something under `bash x.md`,
# and lines a shell reads inside a quote, a heredoc, a code block or after a function definition.
PROVEN_MENTION_BYPASSES = [
    "mv off %s/" % STATE,
    "cd %s/\ntouch off" % STATE,
    "git clone r %s/" % STATE,
    "rmdir %s/" % STATE,
    "for d in %s/\ndo touch off\ndone" % STATE,
    "xargs mv off <<E\n%s/\nE" % STATE,
    "mv off \"\nx\" %s/" % STATE,
    "The() { mv off \"$@\"; }\nThe state is in %s/" % STATE,
    "`%s/` mv off" % STATE,
    "mv off \\\n\n%s/" % STATE,
    "```\nThe state is in %s/\n```" % STATE,
    "~~~\nThe state is in %s/\n~~~" % STATE,
    "    The state is in %s/" % STATE,
    "The state is in %s/off" % STATE,
    "The state is in %s/state.json" % STATE,
    "> The state lives in %s/." % STATE,
    "/harness off -> %s/off" % STATE,
    "The state is in %s/ (see /harness status)" % STATE,
    "- %s/" % STATE,
    "The state is in %s/ or https://x.example/" % STATE,
    "The state is in $HOME/.claude/.harness-switch/" ,
    "The state is in `ls %s/`" % STATE,
    "The state is in %s/ = x" % STATE,
]

# Round 3: a rule judging lines one by one cannot prove what bash makes of the lines around them, so
# the whole file is judged: every line plain (no metacharacter or quote, a first word that runs
# nothing), not only the lines naming the directory. Each form below passed 2dae2504.
WHOLE_FILE_FORMS = [
    "a=(\n%s/\n)\nmkdir -p \"${a[0]}\"; touch \"${a[0]}off\"" % STATE,
    "eval \"f(\"\"){ mkdir -p \\$1; touch \\$1off; }\"\nf %s/" % STATE,
    "touch \"$(printf %%s\n%s/\n)off\"" % STATE,
    "x=$(\n%s/\n)" % STATE,
    "{ mkdir -p\n%s/\n}" % STATE,
    "f() {\nmkdir -p\n}\nf\n%s/" % STATE,
    "\\shopt -s expand_aliases\n\\alias The='mkdir -p'\nThe state is in %s/" % STATE,
    "declare -f The\nThe state is in %s/" % STATE,
    "builtin eval The\nThe state is in %s/" % STATE,
    "command mv off\n%s/" % STATE,
    "Typeset the notes\nThe state is in %s/" % STATE,
    "Note\rmkdir %s/" % STATE,
    "It is the owner's state:\n%s/" % STATE,
    "# Notes\n\nThe switch's state lives in `%s/`, read by the owner." % STATE,
    "The `touch` notes\nThe state is in %s/" % STATE,
    "./run notes\nThe state is in %s/" % STATE,
]


# Round 4: an empty backtick pair is an empty command substitution to bash, so ticks joined to letters
# build a command word (c``d`` is cd). A backtick passes only in a run holding the directory's path
# alone, bounded by the line's ends, a blank or `.,:!`. The first two are the verifier's files.
TICK_FILES = [
    ("docs/n.md", "c``d`` ~/.claude/.harness-switch/\ntou``ch`` off\n"),
    ("docs/n.rst", "c``d`` ~/.claude/.harness-switch/\nto``u``ch off\n"),
    ("docs/n.txt", "Note\nc``d`` ~/.claude/.harness-switch/\nmk``dir`` -p sub\nto``uch`` off\n"),
    ("docs/n.md", "Pick ~/.claude/.harness-switch/\nc``d`` ~/.claude/.harness-switch/\nmk``dir`` x\n"),
    ("docs/n.md", "c`:`d %s/\n" % STATE),
    ("docs/n.md", "The state is in %s/\nSee `notes`d here\n" % STATE),
    ("docs/n.md", "The state is in %s/\nThe `notes` file\n" % STATE),
    ("docs/n.md", "The state is in %s/\n`touch` off\n" % STATE),
    ("docs/n.md", "The state is in %s/\nThe ```touch``` notes\n" % STATE),
    ("docs/n.md", "The state is in ```%s/```x\n" % STATE),
    ("docs/n.md", "The state is in x`%s/`\n" % STATE),
    ("docs/n.md", "The state is in `%s/`x\n" % STATE),
    ("docs/n.md", "The state is in %s/ `\n" % STATE),
    ("docs/n.md", "The state is in %s/ ``\n" % STATE),
    ("docs/n.md", "The state is in `%s/off`\n" % STATE),
    ("docs/n.rst", "The state is in ``%s/`` and ``other``\n" % STATE),
]


@pytest.mark.parametrize("path,content", TICK_FILES)
def test_a_backtick_outside_a_run_of_the_directory_alone_is_refused(box, path, content):
    rc, err = write(box, path, content)
    assert rc == 2 and "naming the switch's state" in err, (path, content, err)


@pytest.mark.parametrize("line", WHOLE_FILE_FORMS)
@pytest.mark.parametrize("path", ["docs/n.md", "/tmp/audit-notes.md", "docs/n.txt"])
def test_prose_is_judged_as_a_whole_file(box, line, path):
    rc, err = write(box, path, "Some notes.\n\n%s\n" % line)
    assert rc == 2 and "naming the switch's state" in err, (path, line, err)


def test_an_edit_not_naming_the_state_is_judged_in_the_document_it_leaves(box):
    f = box["work"] / "docs" / "whole.md"
    f.parent.mkdir(exist_ok=True)
    f.write_text("The state is in %s/\n" % STATE)
    rc, err = call(box, "Edit", {"file_path": str(f), "old_string": "The state is in", "new_string": "a=(\nx"})
    assert rc == 2 and "naming the switch's state" in err, err
    rc, err = call(box, "Edit", {"file_path": str(f), "old_string": "The state", "new_string": "The switch's state"})
    assert rc == 2 and "naming the switch's state" in err, err
    rc, err = call(box, "Edit", {"file_path": str(f), "old_string": "The state", "new_string": "The whole state"})
    assert rc == 0, err


@pytest.mark.parametrize("line", VERIFIER_FORMS + PROVEN_MENTION_BYPASSES)
@pytest.mark.parametrize("path", ["notes.md", "/tmp/audit-notes.md", "docs/n.txt", "docs/n.rst"])
def test_prose_that_is_no_proven_mention_is_refused(box, line, path):
    rc, err = write(box, path, "Some notes.\n\n%s\n" % line)
    assert rc == 2 and "naming the switch's state" in err, (path, line, err)


def test_an_edit_is_judged_in_the_document_it_leaves(box):
    f = box["work"] / "docs" / "cont.md"
    f.parent.mkdir(exist_ok=True)
    f.write_text("mv off \\\nPLACEHOLDER\n")
    rc, err = call(box, "Edit", {"file_path": str(f), "old_string": "PLACEHOLDER", "new_string": "%s/" % STATE})
    assert rc == 2 and "naming the switch's state" in err, err


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


# Round 5: an Edit or MultiEdit of an existing prose file whose resulting document cannot be computed
# or read exactly (bytes that are no UTF-8, an old_string the file does not hold byte for byte) is
# refused when its text names the state, as before the lane: the client may apply the edit after a
# lossy decode or a quote normalisation, leaving `touch ~/.claude/.harness-switch/off # tail`.
UNKNOWN_DOCUMENTS = [
    (b"tou\xe9XYoff # tail\n", "�XY"),
    ("tou‘X’off # tail\n".encode("utf-8"), "'X'"),
]


@pytest.mark.parametrize("before,old", UNKNOWN_DOCUMENTS)
@pytest.mark.parametrize("tool", ["Edit", "MultiEdit"])
def test_an_edit_whose_document_cannot_be_computed_is_refused(box, tool, before, old):
    f = box["work"] / "docs" / ("unknown-%s-%d.md" % (tool, len(before)))
    f.parent.mkdir(exist_ok=True)
    f.write_bytes(before)
    edit = {"old_string": old, "new_string": "ch ~/.claude/.harness-switch/"}
    ti = dict(edit, file_path=str(f)) if tool == "Edit" else {"file_path": str(f), "edits": [edit]}
    rc, err = call(box, tool, ti)
    assert rc == 2 and "naming the switch's state" in err, (tool, before, err)


# Round 5: a first word naming a path passes only as the directory's own path ending in `/`;
# `.,:!` glued on after that slash names a file in the directory, which bash runs.
GLUED_FIRST_WORDS = ["/any/prefix/.harness-switch/:", "/any/prefix/.harness-switch/,",
                     "/any/prefix/.harness-switch/!", "%s/:" % STATE, "%s/." % STATE]


@pytest.mark.parametrize("word", GLUED_FIRST_WORDS)
@pytest.mark.parametrize("rest", ["", " notes"])
def test_a_first_word_naming_a_file_in_the_directory_is_refused(box, word, rest):
    rc, err = write(box, "docs/n.md", "%s%s\n" % (word, rest))
    assert rc == 2 and "naming the switch's state" in err, (word, rest, err)
