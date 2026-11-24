"""cd-read lint: reports a prompt that searches after a `cd` in a compound command.

A `Read()` deny rule makes the CLI ask before a relative-path read after a `cd`.
While settings.json carries any `Read()` deny rule, the Claude Code CLI cannot resolve
statically which file a read command reads by a relative path after a `cd` in a compound
command, so it asks for approval (`grep reads a file by a relative path after a cd in a
compound command; ... while a Read() deny rule is configured, so this needs approval`).
The search convention is a path operand and no `cd`: `grep -rn PAT src`, `rg -n PAT src`,
`git -C src log`.

Two kinds of finding, over the prompt corpus (CLAUDE.md, commands/, agents/) and skills/:

- a `cd <dir>` or `pushd <dir>` joined by `&&`, `;` or `||` to a read command (grep, rg,
  cat, sed, find, git, ...), in prose or in a code block; a `cd` joined to anything else
  (`pwd`, a build, a write) is not a read and is not reported;
- settings.json denies a `Read()` path but CLAUDE.md states no convention: no line names
  `cd`, `Read()` and a path operand together.

settings.json's deny list holds no `Read()` entry now: the entries moved to
policies/cli-deny.v1.json, and the pre-tool rule hooks/pretool-deny-list.py refuses
`cat .env` and, following the `cd`, `cd config && cat .env`, as well as a relative read after
a `cd` to a directory it cannot know whose name an entry could match. `read_denies` reads
settings.json only, so the second finding finds nothing; the convention still keeps agents
clear of that refusal.
"""
from __future__ import annotations

import json
import os
import re

from .tree import PROMPT_FILES, SETTINGS, Finding, Tree

CHECK = "cd-read"
SKILL_DIR = "skills"
READ_COMMANDS = ("grep", "egrep", "fgrep", "rg", "ag", "ack", "cat", "head", "tail", "less", "more", "sed",
                 "awk", "find", "fd", "ls", "tree", "wc", "diff", "jq", "file", "stat", "git")
CD_READ = re.compile(
    r"(?<![\w$-])(?:cd|pushd)\s+(?P<dir>[^\s;&|`)]+)\s*(?:&&|;|\|\|)\s*"
    r"(?:\w+=\S*\s+)*(?P<cmd>" + "|".join(READ_COMMANDS) + r")(?![\w-])")
# The convention line: it names `cd`, `Read()` and a path operand.
CONVENTION = (re.compile(r"\bcd\b"), re.compile(r"Read\(\)"), re.compile(r"path operand", re.I))


def corpus(tree: Tree) -> list[str]:
    """The prompt corpus plus every Markdown file under skills/ (vendored code excluded)."""
    out = list(tree.prompts)
    base = tree.abspath(SKILL_DIR)
    if base.is_dir():
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in ("vendor", "node_modules"))
            out += [os.path.relpath(os.path.join(dirpath, f), tree.root) for f in sorted(files) if f.endswith(".md")]
    return sorted(set(out))


def read_denies(tree: Tree) -> list[str]:
    """The `Read(...)` entries of settings.json permissions.deny."""
    if not tree.exists(SETTINGS):
        return []
    deny = (json.loads(tree.read(SETTINGS)).get("permissions") or {}).get("deny") or []
    return [r for r in deny if isinstance(r, str) and r.startswith("Read(")]


def states_convention(text: str) -> bool:
    return any(all(p.search(line) for p in CONVENTION) for line in text.split("\n"))


def check_cd_reads(tree: Tree) -> list[Finding]:
    out = []
    for rel in corpus(tree):
        for n, line in enumerate(tree.lines(rel), 1):
            for m in CD_READ.finditer(line):
                out.append(Finding(CHECK, rel, n, f"`{m.group(0)}`: search with a path operand and no cd "
                                                  f"(`{m.group('cmd')} ... {m.group('dir')}`, `git -C {m.group('dir')}`)"))
    claude_md = PROMPT_FILES[0]
    if read_denies(tree) and tree.exists(claude_md) and not states_convention(tree.read(claude_md)):
        out.append(Finding(CHECK, claude_md, 1, "settings.json denies Read() paths, but no line states the "
                                                "no-cd search convention (`cd`, `Read()` and a path operand)"))
    return out
