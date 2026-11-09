"""scripts/close-route-select.py, COMPATIBILITY CODE: delete with it once no session predates train 2's landing.

It answers the two calls origin/master's /close Step 0 makes (commands/close.md:296 on a7d3a9f, :345 on
2acc29b): `--task-id T --project-dir P`, and the same with `--late-repair`. Nothing in this tree calls it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _late_repair_fixtures as fx  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "close-route-select.py"
RESOLVER = REPO / "scripts" / "resolve-dev-artifact-chain.py"
TASK_ID = "20260101-000530"


@pytest.fixture(autouse=True)
def _config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))  # the fixtures' dispatch records


def _run(script: Path, root: Path, *extra: str) -> tuple[int, dict]:
    proc = subprocess.run([sys.executable, str(script), "--task-id", TASK_ID, "--project-dir", str(root), *extra],
                          capture_output=True, text=True, check=False)
    assert "Traceback" not in proc.stderr, proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def _files(root: Path) -> dict:
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("build, rc", [(fx.build_complete, 0), (fx.build_qa_only, 2), (fx.build_beyond_qa_clean, 2)])
def test_the_bare_call_is_the_resolver_verbatim_and_writes_nothing(tmp_path, build, rc):
    build(tmp_path / "p", TASK_ID)
    before = _files(tmp_path)
    got_rc, got = _run(SCRIPT, tmp_path / "p")
    resolver_rc, chain = _run(RESOLVER, tmp_path / "p")
    assert (got_rc, resolver_rc) == (rc, rc)
    assert got == {"outcome": "not_selected", "artifact_chain": chain}
    assert _files(tmp_path) == before


@pytest.mark.parametrize("build, rc", [(fx.build_complete, 0), (fx.build_qa_only, 2)])
def test_late_repair_declined_by_init_goes_on_the_ordinary_route(tmp_path, build, rc):
    build(tmp_path / "p", TASK_ID)
    before = _files(tmp_path)
    got_rc, got = _run(SCRIPT, tmp_path / "p", "--late-repair")
    _, chain = _run(RESOLVER, tmp_path / "p")
    assert got_rc == rc
    assert got == {"outcome": "not_selected", "artifact_chain": chain,
                   "late_repair": {"outcome": "refuse", "reason": "not a beyond-QA gap; use R1's route"}}
    assert _files(tmp_path) == before


def test_late_repair_on_a_beyond_qa_gap_is_init(tmp_path):
    fx.build_beyond_qa_clean(tmp_path / "p", TASK_ID)
    rc, first = _run(SCRIPT, tmp_path / "p", "--late-repair")
    assert rc == 0 and first["outcome"] == "initialized" and first["repair_run_id"]
    rc, again = _run(SCRIPT, tmp_path / "p", "--late-repair")
    assert (rc, again) == (0, {"outcome": "already_initialized", "repair_run_id": first["repair_run_id"]})


def test_nothing_in_this_tree_calls_it():
    files = [p for d in ("commands", "agents", "hooks", "scripts", "skills") if (REPO / d).is_dir()
             for p in (REPO / d).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    callers = [p for p in files if p != SCRIPT and p.name not in ("INDEX.md", "README.md")
               and "close-route-select" in p.read_text(encoding="utf-8", errors="replace")]
    assert callers == []
