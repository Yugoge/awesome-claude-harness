"""Each lint check on small trees built here: it reports the planted defect and nothing else.

These run in the ordinary suite. The checks on this repository's own tree are in
test_lint_tree.py, which only the lint CI step collects.
"""
from __future__ import annotations

import json
import subprocess
import textwrap

import pytest

from tests.lint import hooks as H
from tests.lint import prompts as P
from tests.lint.checks import CHECKS, run
from tests.lint.tree import Tree, script_of

LEDGER_HEAD = (
    "| row_id | event_class | matcher | hook | mode/precondition | behavior |\n"
    "|---|---|---|---|---|---|\n"
)


def ledger(*rows) -> str:
    return "# Ledger\n\n" + LEDGER_HEAD + "".join(f"| {r} |\n" for r in rows)


def settings(*regs) -> str:
    hooks: dict = {}
    for event, matcher, script in regs:
        cmd = ("python3 " if script.endswith(".py") else "bash ") + '"${CLAUDE_HOME:-$HOME/.claude}/' + script + '"'
        hooks.setdefault(event, []).append({"matcher": matcher, "hooks": [{"type": "command", "command": cmd}]})
    return json.dumps({"hooks": hooks})


def make_tree(tmp_path, files: dict) -> Tree:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text), encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return Tree(tmp_path)


# ---------------------------------------------------------------- the tree


def test_prompt_corpus_is_claude_md_commands_and_agents_without_folder_docs(tmp_path):
    t = make_tree(tmp_path, {"CLAUDE.md": "x", "commands/dev.md": "x", "commands/README.md": "x",
                             "agents/qa.md": "x", "agents/shared/codex.md": "x", "agents/INDEX.md": "x",
                             "skills/s/SKILL.md": "x", "docs/a.md": "x"})
    assert t.prompts == ["CLAUDE.md", "agents/qa.md", "agents/shared/codex.md", "commands/dev.md"]


@pytest.mark.parametrize("command, script", [
    ('python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/a.py"', "hooks/a.py"),
    ('bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/canary-verify.sh"', "scripts/canary-verify.sh"),
    ("bash ~/.claude/hooks/b.sh --flag", "hooks/b.sh"),
    ("echo hi", None),
])
def test_script_of_a_hook_command(command, script):
    assert script_of(command) == script


# ---------------------------------------------------------------- 1. hook strength


@pytest.mark.parametrize("mode, strength", [
    ("advisory when CP_ENFORCE_MODE is unset (the default); blocking only under CP_ENFORCE_MODE=block", "warns"),
    ("blocking when DO_REPORT_GATE_MODE is unset (the default): exits 2 while the report is missing", "blocks"),
    ("witness only, exits 0 on every path: writes a dispatch attestation", "warns"),
    ("observational: records the hash; never blocks, exits 0 on every path", "warns"),
    ("exits 2 only for a main-agent Agent call while the flag reads true; every other call exits 0", "blocks"),
    ("advisory when G is unset (the default): logged and allowed; exits 2 only under G=block; skipped under =off",
     "warns"),
    ("acts only on a push command: exits 2 on any mismatch (fails closed); every other command exits 0", "blocks"),
    ("runs the four phases in order; only timelock and coverage may block", "blocks"),
    ("off by default; enabled by FOO_ENABLE=1", "off"),
    ("disabled when GIT_WARN_UNTRACKED is unset (the default)", "off"),
    ("warn-only: prints a warning", "warns"),
    ("none", "unknown"),
])
def test_ledger_strength(mode, strength):
    assert P.ledger_strength(mode) == strength


STRENGTH_FILES = {
    "settings.json": settings(("SubagentStop", "*", "hooks/cp.py"), ("PreToolUse", "Bash", "hooks/blocker.py"),
                              ("PreToolUse", "Bash", "hooks/guard.py"), ("SessionStart", "", "hooks/off.sh")),
    "docs/ENFORCEMENT-LEDGER.md": ledger(
        "H-001 | SubagentStop | * | cp.py | advisory when CP_MODE is unset (the default); blocking only under "
        "CP_MODE=block | advisory",
        "H-002 | PreToolUse | Bash | blocker.py | blocking when B_MODE is unset (the default) | advisory",
        "H-003 | PreToolUse | Bash | guard.py | none | advisory",
        "H-004 | SessionStart | (universal) | off.sh | off by default; on under OFF_ON=1 | detected"),
    "hooks/cp.py": "", "hooks/blocker.py": "", "hooks/guard.py": "", "hooks/off.sh": "",
}


@pytest.mark.parametrize("text, expected", [
    ("The `subagentstop` hook `cp.py` BLOCKS your exit (exit 2) if a checkpoint is pending.", 1),
    ("Pending checkpoints cause `hooks/cp.py` to block exit with code 2.", 1),
    ("`cp.py` runs when you stop. It blocks the exit while a checkpoint is pending.", 1),
    ("`off.sh` blocks a session that has no git repository.", 1),
    ("`cp.py` blocks only under `CP_MODE=block`; by default it logs.", 0),
    ("`cp.py` never blocks; it only logs a pending checkpoint.", 0),
    ("`cp.py` is non-blocking.", 0),
    ("`cp.py` prints a warning on stderr; it exits 0 and blocks nothing.", 0),
    ("`cp.py` warns and exits 0: it blocks no Write or Edit.", 0),
    ("Write the obligation block before `cp.py` reads it.", 0),
    ("`blocker.py` blocks the call (exit 2).", 0),
    ("`guard.py` blocks the call.", 0),
    ("`missing.py` blocks the call.", 0),
])
def test_hook_strength(tmp_path, text, expected):
    t = make_tree(tmp_path, dict(STRENGTH_FILES, **{"agents/a.md": text + "\n"}))
    found = P.check_hook_strength(t)
    assert len(found) == expected, [f.text() for f in found]
    if expected:
        assert found[0].path == "agents/a.md" and found[0].line == 1


def test_hook_strength_reports_one_finding_per_hook_per_sentence(tmp_path):
    t = make_tree(tmp_path, dict(STRENGTH_FILES, **{
        "agents/a.md": "Intro.\n\nSecond paragraph line.\n`cp.py` BLOCKS (exit 2) and rejects the stop.\n"}))
    found = P.check_hook_strength(t)
    assert [(f.line, f.check) for f in found] == [(4, "hook-strength")]
    assert "H-001" in found[0].message and "only warns" in found[0].message


# ---------------------------------------------------------------- 2. dead references

HOME_PATHS = {"hooks/real.py": "", "hooks/lib/mod.py": "", "scripts/tool.sh": "", "agents/qa.md": "x",
              "skills/s/SKILL.md": "", ".gitignore": "venv/\nlogs/*\n"}


@pytest.mark.parametrize("text, dead", [
    ("Run `~/.claude/scripts/tool.sh` first.", []),
    ("Run `~/.claude/scripts/gone.sh` first.", ["scripts/gone.sh"]),
    ('Run "${CLAUDE_HOME:-$HOME/.claude}/scripts/gone.py".', ["scripts/gone.py"]),
    ("Run $HOME/.claude/hooks/real.py.", []),
    ("See hooks/lib/mod.py and hooks/lib/mod.function_name.", []),
    ("See hooks/lib/mod for the helper.", []),
    ("See hooks/xxx.sh for an example.", ["hooks/xxx.sh"]),
    ("See hooks/<name>.sh for an example.", []),
    ("See commands/${CMD}.md and agents/*.md.", []),
    ("Read skills/s/missing.md.", ["skills/s/missing.md"]),
    ("Activate `~/.claude/venv/bin/activate` and read `~/.claude/logs/x.log`.", []),
    ("A product's scripts/deploy.sh and docs/dev/report.json are its own.", []),
    ("Ask the user and/or the owner.", []),
])
def test_dead_references(tmp_path, text, dead):
    t = make_tree(tmp_path, dict(HOME_PATHS, **{"commands/c.md": text + "\n"}))
    assert [f.message.split()[1].rstrip(",") for f in P.check_dead_references(t)] == dead


def test_dead_reference_under_an_author_home_is_resolved_against_the_tree(tmp_path):
    home = "/" + "roo" + "t"            # assembled: the residue gate scans this file
    t = make_tree(tmp_path, dict(HOME_PATHS, **{"commands/c.md": f"Run {home}/.claude/scripts/gone.sh\n"}))
    assert [f.line for f in P.check_dead_references(t)] == [1]


# ---------------------------------------------------------------- 3. repeated blocks


def block(n: int, tag: str = "shared") -> str:
    return "".join(f"Line {i} of the {tag} block.\n" for i in range(n))


def test_a_ten_line_block_in_two_prompts_is_reported_in_each(tmp_path):
    t = make_tree(tmp_path, {"agents/a.md": "Own intro.\n\n" + block(12) + "\nOwn end.\n",
                             "agents/b.md": "Other intro.\n" + block(12)})
    found = P.check_repeated_blocks(t)
    assert sorted((f.path, f.line) for f in found) == [("agents/a.md", 3), ("agents/b.md", 2)]
    assert "12 content lines" in found[0].message and "agents/b.md" in found[0].message


def test_blank_lines_fences_and_spacing_do_not_hide_a_repeat(tmp_path):
    spaced = block(10).replace("\n", "\n\n```\n", 1).replace("block.", "block.   ")
    t = make_tree(tmp_path, {"agents/a.md": block(10), "commands/b.md": spaced})
    assert len(P.check_repeated_blocks(t)) == 2


def test_nine_lines_or_one_file_is_not_a_repeat(tmp_path):
    t = make_tree(tmp_path, {"agents/a.md": block(9) + "\n" + block(9), "agents/b.md": block(9),
                             "agents/c.md": block(10, "own") + block(10, "own")})
    assert P.check_repeated_blocks(t) == []


# ---------------------------------------------------------------- 4. emphasis


def test_more_than_three_emphasis_words_is_reported(tmp_path):
    t = make_tree(tmp_path, {
        "agents/a.md": "CRITICAL: one.\nMANDATORY two.\nNON-NEGOTIABLE three.\nA HARD RULE four.\n",
        "agents/b.md": "CRITICAL one. PARAMOUNT two. MANDATORY three.\n",
        "agents/c.md": "critical path, a hard rule, `CRITICAL`, `MANDATORY`.\n```json\n"
                       '{"severity": "CRITICAL", "x": "MANDATORY", "y": "PARAMOUNT"}\n```\nCRITICAL once.\n',
        "agents/d.md": "```\nCRITICAL MANDATORY\n```\nPARAMOUNT and HARD RULES.\n",
    })
    found = P.check_emphasis(t)
    assert [(f.path, f.line) for f in found] == [("agents/a.md", 1), ("agents/d.md", 2)]
    assert found[0].message.startswith("4 emphasis words")


# ---------------------------------------------------------------- 5. unreachable output

PY_SILENT_WARN = """\
import sys
def main():
    print("warning: something", file=sys.stderr)
    return 0
if __name__ == "__main__":
    sys.exit(main())
"""
PY_BLOCKS = """\
import sys
BLOCK = 2
def main():
    print("blocked: something", file=sys.stderr)
    return BLOCK
sys.exit(main())
"""
PY_JSON = """\
import json, sys
print(json.dumps({"hookSpecificOutput": {"additionalContext": "note"}}))
"""
PY_DIAGNOSTIC_ONLY = """\
import sys
try:
    work = 1
except Exception as exc:
    print(f"hook error: {exc}", file=sys.stderr)
sys.exit(0)
"""
PY_STDOUT = """\
print("progress: 3 of 5")
"""
PY_DELEGATES = """\
import sys
from lib import gate
print("checking", file=sys.stderr)
sys.exit(gate.decide())
"""
PY_LIB_DECIDES = """\
import sys
def deny(msg):
    print(msg, file=sys.stderr)
    sys.exit(2)
"""
PY_WRAPPER = """\
import sys
from lib import gate
print("deciding", file=sys.stderr)
gate.deny("no")
"""
SH_SILENT_WARN = """\
#!/bin/bash
# exit 2 is mentioned only in this comment
x=$(echo hidden || echo 999)
cat >&2 <<EOF
warning text, and the words exit 2 inside the heredoc
EOF
exit 0
"""
SH_BLOCKS = """\
#!/bin/bash
echo "blocked" >&2
exit 2
"""
SH_PIPED = """\
#!/bin/bash
printf '%s' "$INPUT" | python3 -c 'import sys'
echo "x" > "$LOG"
exit 0
"""
SH_EXEC_STDERR = """\
#!/bin/bash
exec >&2   # all output to stderr
echo "note"
exit 0
"""


@pytest.mark.parametrize("event, name, source, reported", [
    ("PreToolUse", "warn.py", PY_SILENT_WARN, True),
    ("PreToolUse", "blocks.py", PY_BLOCKS, False),
    ("PostToolUse", "json.py", PY_JSON, False),
    ("PreToolUse", "diag.py", PY_DIAGNOSTIC_ONLY, False),
    ("PostToolUse", "stdout.py", PY_STDOUT, True),
    ("SessionStart", "stdout.py", PY_STDOUT, False),
    ("UserPromptSubmit", "warn.py", PY_SILENT_WARN, True),
    ("PreToolUse", "delegates.py", PY_DELEGATES, False),
    ("PreToolUse", "wrapper.py", PY_WRAPPER, False),
    ("SubagentStop", "warn.sh", SH_SILENT_WARN, True),
    ("SubagentStop", "blocks.sh", SH_BLOCKS, False),
    ("PostToolUse", "piped.sh", SH_PIPED, False),
    ("SessionEnd", "exec.sh", SH_EXEC_STDERR, True),
])
def test_unreachable_output(tmp_path, event, name, source, reported):
    t = make_tree(tmp_path, {"settings.json": settings((event, "*", "hooks/" + name)), "hooks/" + name: source,
                             "hooks/lib/__init__.py": "", "hooks/lib/gate.py": PY_LIB_DECIDES})
    found = H.check_unreachable_output(t)
    assert bool(found) is reported, [f.text() for f in found]
    if found:
        assert found[0].path == "hooks/" + name and event in found[0].message


def test_shell_facts_ignore_substitutions_comments_and_heredoc_bodies(tmp_path):
    t = make_tree(tmp_path, {"hooks/w.sh": SH_SILENT_WARN})
    f = H.shell_facts(t, "hooks/w.sh")
    assert (f.can_block, f.json_channel, f.stderr_lines, f.stdout_lines) == (False, False, [4], [])


SH_TRICKY = """\
#!/bin/bash
read -r x <<< "$INPUT"
n=$(( 1 << 2 ))
echo "saved ${TIP:-?} on ${REF}; done" >&2
echo 'a } b' > "$LOG"
echo "plain"
"""


def test_shell_facts_quotes_expansions_here_strings_and_arithmetic(tmp_path):
    t = make_tree(tmp_path, {"hooks/t.sh": SH_TRICKY})
    f = H.shell_facts(t, "hooks/t.sh")
    assert (f.stderr_lines, f.stdout_lines) == ([4], [6])


def test_python_print_to_stdout_by_name_is_stdout(tmp_path):
    t = make_tree(tmp_path, {"hooks/p.py": "import sys\nprint('x', file=sys.stdout)\nsys.exit(0)\n"})
    f = H.python_facts(t, "hooks/p.py")
    assert (f.can_block, f.stdout_lines, f.stderr_lines) == (False, [2], [])


def test_an_unregistered_or_missing_hook_is_not_checked(tmp_path):
    t = make_tree(tmp_path, {"settings.json": settings(("PreToolUse", "*", "hooks/gone.py")),
                             "hooks/unregistered.py": PY_SILENT_WARN})
    assert H.check_unreachable_output(t) == []


# ---------------------------------------------------------------- 6. two writers


def artifact(key, producers, kind="file"):
    return {"key": key, "kind": kind, "producers": producers,
            "writers": [[p, f"{p}:{10 + i}"] for i, p in enumerate(producers)]}


def test_a_state_file_with_two_producers_is_reported_at_its_first_writer():
    found = H.state_writer_findings([
        artifact("<proj>/.claude/workflow-<sid>.json", ["hooks/a.py", "hooks/b.py"]),
        artifact("<state>/claude-flag-<sid>.flag", ["hooks/a.py"]),
        artifact("<proj>/docs/dev/dev-report-<task>.json", ["agent:dev", "scripts/agg.py"]),
        artifact("response:qa:CLOSE:", ["agent:qa", "main"], kind="response"),
        artifact("<tmpdir>/<sid>/x.json", ["hooks/c.sh", "scripts/d.py", "main"]),
    ])
    assert [(f.path, f.line) for f in found] == [("hooks/a.py", 10), ("hooks/c.sh", 10)]
    assert found[0].message.startswith("<proj>/.claude/workflow-<sid>.json has 2 writers")


def test_two_writers_without_the_artifact_check_is_a_finding_not_a_pass(tmp_path):
    t = make_tree(tmp_path, {"hooks/a.py": ""})
    found = H.check_two_writers(t)
    assert len(found) == 1 and "artifact check" in found[0].message


# ---------------------------------------------------------------- the registry


def test_the_six_checks_run_by_name_and_a_clean_tree_has_no_findings(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "derive_artifacts", lambda tree: [artifact("<state>/x.json", ["hooks/ok.py"])])
    t = make_tree(tmp_path, {
        "settings.json": settings(("PreToolUse", "Bash", "hooks/ok.py")),
        "docs/ENFORCEMENT-LEDGER.md": ledger("H-001 | PreToolUse | Bash | ok.py | blocking when OK_MODE is unset "
                                             "(the default) | advisory"),
        "hooks/ok.py": PY_BLOCKS,
        "CLAUDE.md": "`ok.py` blocks a destructive command. See `~/.claude/hooks/ok.py`.\n",
        "commands/dev.md": "One CRITICAL rule.\n",
    })
    assert list(CHECKS) == ["hook-strength", "dead-reference", "repeated-block", "emphasis",
                            "unreachable-output", "two-writers"]
    assert run(t) == {name: [] for name in CHECKS}
