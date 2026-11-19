"""The harness's own vocabulary is written once and every consumer reads it.

Each test below pins one fact the 2026-11-19 duplicate audit found written in several places
whose copies answered the same question differently (a defect family), on the inputs on which
the copies disagreed: after the merge every consumer gives the same answer, and no consumer
holds a copy of its own.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
SOURCES = [p for d in ("hooks", "scripts") for p in sorted((ROOT / d).rglob("*.py"))
           if "tests" not in p.relative_to(ROOT).parts and "__pycache__" not in p.parts]


def _lib(name: str):
    sys.path.insert(0, str(HOOKS))
    try:
        return __import__(f"lib.{name}", fromlist=["_"])
    finally:
        sys.path.pop(0)


def _string_tables(path: Path):
    """(line, members) of every tuple/set/list literal of two or more strings, and of every
    `x == "a" or x == "b"` / `!= and !=` chain, in one file."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Tuple, ast.Set, ast.List)):
            vals = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if len(vals) >= 2 and len(vals) == len(node.elts):
                yield node.lineno, frozenset(vals)
        elif isinstance(node, ast.BoolOp):
            vals = [c.comparators[0].value for c in node.values
                    if isinstance(c, ast.Compare) and len(c.ops) == 1 and isinstance(c.ops[0], (ast.Eq, ast.NotEq))
                    and isinstance(c.comparators[0], ast.Constant) and isinstance(c.comparators[0].value, str)]
            if len(vals) >= 2:
                yield node.lineno, frozenset(vals)


def _copies(members: set, home: str) -> list[str]:
    """Every literal table of exactly `members` in hooks/ and scripts/ outside `home`."""
    want = frozenset(members)
    return [f"{p.relative_to(ROOT)}:{line}" for p in SOURCES if str(p.relative_to(ROOT)) != home
            for line, vals in _string_tables(p) if vals == want]


# ---------------------------------------------------------------- tool-subagent-dispatch
DISPATCH = {"Agent", "Task"}  # "Agent", and "Task", the name the CLI used before and still accepts


def test_dispatch_tool_names_are_defined_once():
    assert set(_lib("subagent").DISPATCH_TOOLS) == DISPATCH
    assert _copies(DISPATCH, "hooks/lib/subagent.py") == []


def test_launchers_select_the_dispatch_rules_for_every_dispatch_name():
    """The audit's input: tool_name=Task. The launchers selected dispatch-gate, dispatch-record and
    close-rating for "Agent" only, while every hook of those rules answers for both names."""
    launch_settings = _lib("launch_settings")
    seen = []
    for launcher in ("hooks/pretool-launch.py", "hooks/posttool-launch.py"):
        for path, tools, _timeout in launch_settings.rules(str(ROOT), launcher):
            if tools is not None and DISPATCH & set(tools):
                seen.append(path)
                assert DISPATCH <= set(tools), f"{launcher}: {path} selects {tools}"
    assert {"pretool-dispatch-gate.py", "posttool-dispatch-record.py", "posttool-close-rating.py"} <= set(seen)


# ---------------------------------------------------------------- subagent-recognition
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

import pytest  # noqa: E402


def _hook(name: str):
    sys.path.insert(0, str(HOOKS))
    try:
        spec = importlib.util.spec_from_file_location(f"_defs_tools_{name.replace('-', '_')[:-3]}", HOOKS / name)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.pop(0)


# (payload fields, environment): the audit's inputs (an alias of agent_id; an environment name
# of a spawned agent) and two controls (the main agent; a Claude Code subagent).
RECOGNITION_INPUTS = [
    ({"agent_path": "/x"}, {}),
    ({}, {"CLAUDE_AGENT_ID": "x"}),
    ({}, {}),
    ({"agent_id": "a1", "agent_type": "qa"}, {}),
]


@pytest.mark.parametrize("fields,env", RECOGNITION_INPUTS)
def test_every_subagent_predicate_agrees(fields, env, monkeypatch, tmp_path):
    """The orchestrator gate's predicate (lib/subagent) said "subagent" where tool-policy, the
    cp-state guard and the overnight guard read the payload's agent_id and said "main agent"."""
    for key in ("CLAUDE_AGENT_ID", "CLAUDE_SUBAGENT_ID", "CODEX_AGENT_ID", "CODEX_AGENT_PATH", "OPENAI_AGENT_ID",
                "CLAUDE_COMPAT_RUNTIME"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    payload = {"session_id": "s1", "tool_name": "Write", "cwd": str(tmp_path), **fields}
    expected = _lib("subagent").is_subagent_context(payload)
    assert (_hook("pretool-tool-policy.py")._caller_label(None, payload) != "main") is expected
    guard = _hook("pretool-overnight-hook-guard.py")
    guard._REQUEST_CTX["payload"] = payload
    assert guard._is_orchestrator_actor() is (not expected)
    # the cp-state guard refuses a subagent's direct write of a cp-state file, and only a subagent's
    target = tmp_path / ".claude" / "specs" / "s1" / "cp-state-dev.json"
    target.parent.mkdir(parents=True)
    body = {**payload, "tool_input": {"file_path": str(target), "content": "{}"}}
    run = subprocess.run([sys.executable, str(HOOKS / "pretool-cp-state-write-guard.py")], input=json.dumps(body),
                         capture_output=True, text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)},
                         cwd=tmp_path)
    assert (run.returncode == 2) is expected, run.stderr


# ---------------------------------------------------------------- subagent-env-variables
SPAWNED_AGENT_ENV = ("CLAUDE_AGENT_ID", "CLAUDE_SUBAGENT_ID", "CODEX_AGENT_ID", "CODEX_AGENT_PATH", "OPENAI_AGENT_ID")


@pytest.mark.parametrize("name", SPAWNED_AGENT_ENV)
def test_one_list_of_spawned_agent_environment_names(name, monkeypatch, tmp_path):
    """scripts/write-git-residual-override.py refused an agent by CLAUDE_AGENT_ID and
    CLAUDE_SUBAGENT_ID; lib/subagent knew CLAUDE_AGENT_ID and three Codex names. Each name now
    marks a subagent for both."""
    for key in SPAWNED_AGENT_ENV + ("CLAUDE_COMPAT_RUNTIME",):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(name, "x")
    assert _lib("subagent").is_subagent_context({}) is True
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "write-git-residual-override.py"),
                          "--command-sha256", "not-a-digest", "--residual-kinds", "x", "--reason", "r",
                          "--dir", str(tmp_path / "override")],
                         capture_output=True, text=True, env=dict(os.environ))
    assert run.returncode == 1 and f"{name} is set" in run.stderr, run.stderr
    assert not (tmp_path / "override").exists()


# ---------------------------------------------------------------- docsync-skip-files
def _doc_sync(name: str):
    sys.path.insert(0, str(ROOT))
    try:
        return __import__(f"hooks.doc_sync.{name}", fromlist=["_"])
    finally:
        sys.path.pop(0)


def test_every_doc_sync_listing_leaves_out_the_same_files(tmp_path, monkeypatch):
    """The audit's input: a watched folder that holds lifecycle.jsonl. The INDEX statistics
    (regen_index._build_stats) and the inventory line (patch._count_entries, _build_file_list)
    counted it; the rendered tree and the README listing left it out."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    folder = tmp_path / "hooks"
    folder.mkdir()
    for name in ("a.md", "lifecycle.jsonl", "agent-scores.json", "INDEX.md"):
        (folder / name).write_text("# a\n")
    entries = 1  # a.md
    assert _doc_sync("regen_index")._build_stats(folder)["total"] == entries
    patch = _doc_sync("patch")
    assert patch._count_entries(folder, False) == entries
    assert f"({entries} entries)" in patch._build_file_list(folder)
    assert len(_doc_sync("tree").build_tree(folder)) == entries
    readme = _doc_sync("regen_readme")
    assert [n for n in ("a.md", "lifecycle.jsonl", "agent-scores.json") if not readme._is_skipped(n)] == ["a.md"]
    relay = _hook("userprompt-doc-sync-check.py")
    assert relay.get_dir_snapshot(folder) == {"a.md"}
    assert {"lifecycle.jsonl", "agent-scores.json"} <= set(_doc_sync("main").SKIP_FILES)
