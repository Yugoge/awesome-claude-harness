"""BA's blast-radius map lands in the cycle's own registry (agents/ba.md Step 9 and its context example).

ba.md spelled the map's path `.claude/dev-registry/dev-<task_id>/blast-radius-map.json`. A /dev cycle's
registry is `dev-<timestamp>`, so there the spelling only matched by accident; a /dev-command cycle's is
`dev-command-<timestamp>` (commands/dev-command.md), so BA's map run made a stray `dev-<timestamp>/`
directory, and from then on the one rule (hooks/lib/obligation.py registry_dir_for), which takes a bare
`<timestamp>` to whichever of `dev-<ts>` and `dev-command-<ts>` exists, `dev-` first, sent the cycle's
readers (the /dev-command --codex flag and ledger) to the stray directory. A lane id (`<TASK_ID>-l1`) or
an overnight pipeline id (`<ts>-<index>`) made one stray directory per lane or pipeline as well.

The map belongs in the registry BA's own dispatch names: the directory of its FIRST ACTION sentinel,
`<DEV_SESSION_ID>` (/dev's and /dev-command's Step 4, /dev-overnight's BA dispatch), with `<task_id>` in
the file name, since the lanes or pipelines of one cycle share one registry. graphify-enrich takes the
map from the context's `blast_radius_map_path` (every dispatch passes `--context-file`), so the context
example must name the same path the tool call writes.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from hooks.lib import obligation  # noqa: E402

TS = "20260101-000000"
CYCLES = {"/dev": f"dev-{TS}", "/dev-command": f"dev-command-{TS}"}
WANT = ".claude/dev-registry/<DEV_SESSION_ID>/blast-radius-map-<task_id>.json"
PENDING = pytest.mark.xfail(strict=True, reason=(
    "agents/ba.md Step 9 still writes the map at dev-<task_id>/; its fix spells <DEV_SESSION_ID>, which the "
    "replay drivers' BA text calls (tests/replay/drivers/dev.py, dev_command.py, overnight.py) must bind "
    "first; drop this marker with that fix"))


def _ba() -> str:
    return (REPO / "agents" / "ba.md").read_text(encoding="utf-8")


def _tool_output() -> str:
    step9 = _ba().split("### Step 9:", 1)[1].split("\n### ", 1)[0]
    return re.search(r"--output (\S+)", step9).group(1)


def _context_path() -> str:
    return re.search(r'"blast_radius_map_path": "([^"]+)"', _ba()).group(1)


def test_the_context_example_names_the_path_the_tool_call_writes() -> None:
    assert _tool_output() == _context_path()


@PENDING
def test_the_map_path_is_the_dispatch_registry_with_a_task_keyed_name() -> None:
    assert _tool_output() == WANT


def test_ba_dispatches_name_the_registry_by_dev_session_id() -> None:
    """The name ba.md's path uses is the one each BA dispatch binds in its FIRST ACTION line."""
    dev = (REPO / "commands" / "dev.md").read_text(encoding="utf-8")
    step4 = dev.split("### Step 4:", 1)[1].split("\n### ", 1)[0]
    assert ".claude/dev-registry/<DEV_SESSION_ID>/ba.json" in step4
    command = (REPO / "commands" / "dev-command.md").read_text(encoding="utf-8")
    assert "`DEV_SESSION_ID` (`dev-command-<timestamp>`) names the registry directory" in command
    assert "As `/dev` Step 4" in command.split("### Step 4:", 1)[1].split("\n### ", 1)[0]
    overnight = (REPO / "commands" / "dev-overnight.md").read_text(encoding="utf-8")
    ba = overnight[overnight.index('Agent(subagent_type: "ba")'):]
    assert ".claude/dev-registry/$DEV_SESSION_ID/ba.json" in ba.split("\n```", 1)[0]


def _run_map(project: Path, cycle: str) -> Path:
    """BA's Step 9 call, filled for a cycle whose hook-made registry exists, run in the project."""
    registry = project / ".claude" / "dev-registry" / CYCLES[cycle]
    registry.mkdir(parents=True)
    (project / "src.py").write_text("x = 1\n", encoding="utf-8")
    out = _tool_output().replace("<DEV_SESSION_ID>", CYCLES[cycle]).replace("<task_id>", TS)
    run = subprocess.run([sys.executable, str(REPO / "scripts" / "blast-radius-tool.py"), "--files", "src.py",
                          "--output", out, "--task-id", TS, "--root", str(project)],
                         cwd=project, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return project / out


@pytest.mark.parametrize("cycle", [pytest.param("/dev", id="dev"),
                                   pytest.param("/dev-command", id="dev-command", marks=PENDING)])
def test_the_map_lands_in_the_cycle_registry_and_leaves_the_rule_on_it(tmp_path, cycle) -> None:
    written = _run_map(tmp_path, cycle)
    registry = tmp_path / ".claude" / "dev-registry" / CYCLES[cycle]
    assert written.is_file() and written.parent == registry
    assert sorted(p.name for p in registry.parent.iterdir()) == [CYCLES[cycle]]
    assert obligation.registry_dir_for(tmp_path, TS) == registry


@pytest.mark.parametrize("cycle", ["/dev", "/dev-command"])
def test_graphify_enrich_finds_the_map_through_the_context(tmp_path, cycle) -> None:
    _run_map(tmp_path, cycle)
    context = tmp_path / "docs" / "dev" / f"context-{TS}.json"
    context.parent.mkdir(parents=True)
    context.write_text(json.dumps({"task_id": TS, "blast_radius_map_path": _context_path().replace(
        "<DEV_SESSION_ID>", CYCLES[cycle]).replace("<task_id>", TS)}), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_HOME"}
    env.update(CLAUDE_PROJECT_DIR=str(tmp_path), CLAUDE_GRAPHIFY_ENABLED="1", PATH="/usr/bin:/bin")
    run = subprocess.run([sys.executable, str(REPO / "scripts" / "graphify-enrich.py"), "--task-id", CYCLES[cycle],
                          "--context-file", str(context)], cwd=tmp_path, capture_output=True, text=True,
                         env=env, timeout=120)
    assert run.returncode == 0, run.stderr
    record = json.loads((tmp_path / ".claude" / "dev-registry" / CYCLES[cycle] / "graphify" / "graphify-run.json").read_text(encoding="utf-8"))
    assert record.get("status") != "skipped" and "blast-radius-map.json absent" not in json.dumps(record), record
