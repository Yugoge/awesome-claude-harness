"""Checks that harness prompts search with path operands, not after a `cd` (OB-L10).

A `Read()` deny rule makes the CLI ask before a relative-path read after a `cd` (audit G3).
Root cause (perm-read-deny-arms-cd-guard): settings.json carries `Read()` deny rules,
and while any is configured the CLI asks for approval when a read command reads a relative path
after a `cd` in a compound command. Docs (https://code.claude.com/docs/en/permissions.md):
"a compound command like `cd packages/api && ls` runs without a prompt when each part qualifies
on its own"; "Read and Edit deny rules apply to ... file commands Claude Code recognizes in Bash,
such as cat, head, tail, sed, and tee"; "Bare filenames follow gitignore semantics and match at
any depth, so `Read(.env)` and `Read(**/.env)` are equivalent". The cd guard's prompt text is
the CLI's own (measured by the audit), not documented.

The change is prose only: tests/lint/cd_read.py finds a `cd <dir> && <read command>` in the
prompt corpus and skills, and requires CLAUDE.md to state the convention while a Read() deny
rule exists. The settings keep that intent, checked below without pinning the list (other lanes
own its entries): a Read() deny rule exists, so `cd config && cat .env` keeps the guard, and
`cat .env` stays denied under the documented matching model (the guard is the CLI's; it is
modelled here by "a Read() deny rule exists", not measured).
"""
from __future__ import annotations

import fnmatch
import json
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.lint.cd_read import CD_READ, check_cd_reads, corpus, read_denies
from tests.lint.tree import Tree

REPO = Path(__file__).resolve().parents[1]

CONVENTION_LINE = ("- Search with a path operand, not a `cd` in a compound command: while settings.json has a "
                   "`Read()` deny rule the CLI asks for approval.\n")


def make_tree(tmp_path, files: dict) -> Tree:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text), encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return Tree(tmp_path)


def deny_settings(*rules) -> str:
    return json.dumps({"permissions": {"deny": list(rules)}})


# ---------------------------------------------------------------- the pattern


@pytest.mark.parametrize("text, cmd", [
    ("cd src && grep -rn TODO .", "grep"),
    ("`cd hooks && rg -n foo`", "rg"),
    ("(cd \"$DIR\" && find . -name x)", "find"),
    ("cd docs; cat README.md", "cat"),
    ("pushd sub && git diff", "git"),
    ("cd sub || ls", "ls"),
    ("cd src && LC_ALL=C sed -n 1p a.py", "sed"),
])
def test_a_cd_joined_to_a_read_command_is_found(text, cmd):
    m = CD_READ.search(text)
    assert m and m.group("cmd") == cmd


@pytest.mark.parametrize("text", [
    "grep -rn TODO src", "rg -n TODO src", "git -C src log --oneline -3",
    "`cd` into `worktree_path` in every mode",           # a working-root change, no read
    "DIR=$(cd \"$(dirname \"$0\")\" && pwd)",              # resolves a path, reads no file
    "cd build && make", "cd app && npm test", "abcd x && grep y z", "$cd x && grep y",
    "cd src && grepx", "cd src && git-lfs ls-files",
])
def test_a_search_with_a_path_operand_or_a_cd_for_something_else_is_not_found(text):
    assert CD_READ.search(text) is None


# ---------------------------------------------------------------- the check on planted trees


def test_check_reports_each_cd_read_in_prompts_and_skills_and_nothing_else(tmp_path):
    t = make_tree(tmp_path, {
        "settings.json": deny_settings("Read(**/.env)"),
        "CLAUDE.md": "# x\n" + CONVENTION_LINE,
        "commands/dev.md": "Run `cd src && grep -rn TODO .` first.\n",
        "agents/qa.md": "```bash\ncd app && git log -3\n```\n",
        "agents/README.md": "cd src && grep x .\n",          # folder doc, not a prompt
        "skills/s/SKILL.md": "Then `pushd lib && rg -n foo`.\n",
        "skills/s/vendor/x.md": "cd a && cat b\n",            # vendored, not a prompt
        "docs/a.md": "cd src && grep x .\n",                  # not loaded as a prompt
    })
    found = [(f.path, f.line) for f in check_cd_reads(t)]
    assert found == [("agents/qa.md", 2), ("commands/dev.md", 1), ("skills/s/SKILL.md", 1)]


def test_check_requires_the_convention_in_claude_md_while_a_read_deny_exists(tmp_path):
    t = make_tree(tmp_path, {"settings.json": deny_settings("Read(.env)"), "CLAUDE.md": "# rules\n"})
    assert [(f.path, f.line) for f in check_cd_reads(t)] == [("CLAUDE.md", 1)]


def test_check_needs_no_convention_without_a_read_deny(tmp_path):
    t = make_tree(tmp_path, {"settings.json": deny_settings("Bash(rm -rf:*)"), "CLAUDE.md": "# rules\n"})
    assert check_cd_reads(t) == []


def test_corpus_is_the_prompts_plus_skill_markdown(tmp_path):
    t = make_tree(tmp_path, {"CLAUDE.md": "x", "commands/a.md": "x", "agents/shared/b.md": "x",
                             "skills/s/SKILL.md": "x", "skills/s/ref.md": "x", "skills/s/vendor/v.md": "x",
                             "skills/s/run.py": "x", "docs/d.md": "x"})
    assert corpus(t) == ["CLAUDE.md", "agents/shared/b.md", "commands/a.md", "skills/s/SKILL.md",
                         "skills/s/ref.md"]


# ---------------------------------------------------------------- this tree


def test_this_tree_has_no_cd_read_and_states_the_convention():
    findings = check_cd_reads(Tree(REPO))
    assert findings == [], "\n".join(f.text() for f in findings)


# ---------------------------------------------------------------- settings unchanged (must still refuse)


def _read_denied(path: str, rules: list[str]) -> bool:
    """Model of the documented gitignore matching for the relative and `**/` forms only."""
    for rule in rules:
        pat = rule[len("Read("):-1]
        if pat.startswith("//"):
            if fnmatch.fnmatchcase("/" + path.lstrip("/"), pat[1:]):
                return True
            continue
        pat = pat[3:] if pat.startswith("**/") else pat
        if "/" not in pat and fnmatch.fnmatchcase(path.rsplit("/", 1)[-1], pat):
            return True
    return False


@pytest.mark.parametrize("path, denied", [
    (".env", True),                 # `cat .env`: denied
    ("config/.env", True),          # `cd config && cat .env` resolves here: denied once resolved
    ("src/app.py", False),          # `grep -rn TODO src` reads an ordinary file
])
def test_must_still_refuse_reads_stay_denied(path, denied):
    rules = read_denies(Tree(REPO))
    assert _read_denied(path, rules) is denied
    # Any Read() deny keeps the CLI's cd guard armed, so `cd config && cat .env` still asks.
    assert rules


def _check_read_deny_intent(rules: list[str]) -> None:
    # Any Read() deny keeps the CLI's cd guard armed; `cat .env` must stay denied. No entry is pinned.
    assert rules, "settings.json has no Read() deny rule: the CLI's cd guard is disarmed"
    assert _read_denied(".env", rules), "`cat .env` is no longer denied by a Read() deny rule"


def test_read_deny_entries_are_unchanged():
    """The Read() deny intent holds on this tree, and the check fails when that intent is broken."""
    rules = read_denies(Tree(REPO))
    _check_read_deny_intent(rules)
    with pytest.raises(AssertionError, match="no Read\\(\\) deny rule"):
        _check_read_deny_intent([])
    without_env = [r for r in rules if not _read_denied(".env", [r])]
    assert without_env, "the mutation must leave other Read() denies in place"
    with pytest.raises(AssertionError, match="`cat .env` is no longer denied"):
        _check_read_deny_intent(without_env)
