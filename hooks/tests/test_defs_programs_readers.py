"""The programs that only read are one definition (hooks/lib/bash_read_only.py), read by every guard that asks.

Before, the harness-switch rule kept a private list of 27 readers and refused, as a write of the
settings file, 25 of 55 plain reads of it (`nl -ba`, `sort`, `awk 'NR<5'`, `od -c`, `cut`, `tr`, ...)
that the config guard passed on its own protected file and the orchestrator gate's proof called
read-only. Both guards now read bash_read_only.reads_only, so they decide alike on every such read,
and a program that reads in one form and writes in another (sort -o, uniq IN OUT, xxd IN OUT,
find -fprint, file -C) is a read only in the form its check admits.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS / "lib"))
import bash_read_only  # noqa: E402
sys.path.pop(0)

# The audit's reads that the harness-switch rule refused and the config guard passed.
READS = ["nl -ba {T}", "tac {T}", "sort {T}", "uniq {T}", "od -c {T}", "xxd {T}", "hexdump -C {T}",
         "strings {T}", "cut -c1-10 {T}", "tr a b < {T}", "awk 'NR<5' {T}", "b2sum {T}", "cksum {T}",
         "ag x {T}", "ack x {T}", "bat {T}", "column -t {T}", "comm {T} /dev/null", "fold {T}", "fmt {T}",
         "expand {T}", "paste {T}", "rev {T}", "du -h {T}", "true {T}",
         # and the reads both passed before
         "cat {T}", "less {T}", "jq . {T}", "find {T} -type f", "sed -n 1,5p {T}"]
# The same programs in the form that writes the named file: still refused by both.
WRITES = ["sort -o {T} /etc/hostname", "sed -i s/a/b/ {T}"]
TARGETS = {"pretool-harness-switch-guard.py": ".claude/settings.json",
           "pretool-claude-config-guard.py": ".claude/hooks/x.py"}


def _hook(name: str, command: str, project: Path, home: Path) -> int:
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
               "cwd": str(project), "session_id": "readers", "transcript_path": str(project / "t.jsonl")}
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "CODEX"))}
    env.update(HOME=str(home), CLAUDE_PROJECT_DIR=str(project), CLAUDE_CONFIG_DIR=str(home / ".claude"))
    return subprocess.run([sys.executable, str(HOOKS / name)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=str(project), env=env, timeout=60).returncode


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("readers")
    p = root / "proj"
    (p / ".claude" / "hooks").mkdir(parents=True)
    (p / ".claude" / "settings.json").write_text("{}\n")
    (p / ".claude" / "hooks" / "x.py").write_text("x = 1\n")
    (root / "home" / ".claude").mkdir(parents=True)
    return p


@pytest.mark.parametrize("template", READS)
def test_both_guards_pass_a_read_of_their_file(project, template):
    codes = {name: _hook(name, template.replace("{T}", t), project, project.parent / "home")
             for name, t in TARGETS.items()}
    assert codes == dict.fromkeys(TARGETS, 0)


@pytest.mark.parametrize("template", WRITES)
def test_both_guards_refuse_the_writing_form(project, template):
    codes = {name: _hook(name, template.replace("{T}", t), project, project.parent / "home")
             for name, t in TARGETS.items()}
    assert codes == dict.fromkeys(TARGETS, 2)


@pytest.mark.parametrize("command,reads", [
    ("uniq -c f", True), ("uniq -f 1 f", True), ("uniq a b", False), ("uniq -- -a", False),
    ("xxd -c 8 f", True), ("xxd f out", False), ("file f", True), ("file -C -m m", False),
    ("od -c f", True), ("jq . f", True), ("sort -o f x", False), ("find . -fprint f", False),
])
def test_the_proof_reads_the_same_table(command, reads):
    assert bash_read_only.is_read_only(command) is reads


def test_pagers_are_readers_only_where_running_a_command_is_not_asked():
    assert bash_read_only.reads_only("less", ["f"], pagers=True)
    assert not bash_read_only.reads_only("less", ["-o", "log", "f"], pagers=True)
    assert not bash_read_only.reads_only("less", ["f"])
    assert not bash_read_only.is_read_only("less f")
