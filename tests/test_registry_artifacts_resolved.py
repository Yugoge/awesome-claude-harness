"""The registry files P9 A23's one-rule sites write, as the artifact check sees them.

761b72c routed every registry-dir site through hooks/lib/obligation.py, and
CI's artifact check (tests/test_artifact_graph.py, run 42679184684) went from
0 to 5 violations. Two causes, both in how the check's static half reads the
sites, neither in the check:

* registry_dir_named mapped a minted name through registry_dir_for, whose
  ``dev-<ts>`` / ``dev-command-<ts>`` f-strings the static half follows. So
  graphify-enrich.py's focused-subgraph.json was written at those two keys
  while its readers (the command text's
  ``.claude/dev-registry/<DEV_SESSION_ID>/...`` dispatch line) read it by the
  name: written and never read, twice.
* write-enforce-flag.sh took its directory from the printed output of
  ``prompt-workflow.py registry-dir``, which the static half cannot follow, so
  codex-enforce.json lost its writer: read and never written, and a second
  deciding rule (the script's symlink test) beside the codex gate's.

These tests run the static half on this tree and derive the check from it
alone (no replays: the two files are written only where no replay goes), and
check the flag writer's behaviour, which moved into hooks/prompt-workflow.py.
On 761b72c the first two fail; the full check over the replays is
tests/test_artifact_graph.py's.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FLAG_WRITER = REPO / "scripts" / "write-enforce-flag.sh"
CODEX_READ = "<proj>/.claude/dev-registry/<sid>/codex-enforce.json"


@pytest.fixture(scope="module")
def static():
    from tests.artifact_graph import static_half
    return static_half.derive(str(REPO))


def test_the_registry_files_the_one_rule_sites_write_have_a_writer_and_a_reader(static):
    from tests.artifact_graph import check
    found = check.violations(check.derive(str(REPO), static, []), static.records)
    mine = [v.text() for v in found if v.rule.startswith(("2-", "4-")) and "/.claude/dev-registry/" in v.artifact
            and v.artifact.endswith(("/codex-enforce.json", "/graphify/focused-subgraph.json"))]
    assert not mine, "\n\n".join(mine)


def test_the_codex_flag_is_written_where_its_gate_reads_it(static):
    from tests.artifact_graph import check, patterns
    reads = [r for r in static.relations if r["op"] == "read" and r["path"] == CODEX_READ
             and r["component"] == "hooks/subagentstop-codex-enforce.py"]
    assert reads, "the codex gate reads no " + CODEX_READ
    writes = sorted({(r["path"], r["site"]) for r in static.relations if r["op"] == "write"
                     and r["path"].endswith("/codex-enforce.json")})
    joined = [w for w in writes if patterns.pattern_root(w[0]) == "proj"
              and (w[0] == CODEX_READ or check.matches(w[0], CODEX_READ))]
    assert joined, f"no write of codex-enforce.json joins the gate's read {CODEX_READ}: {writes}"


def _flag_writer(project: Path, *args: str, **env_extra: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
    env.update(HOME=str(project.parent / "home"), PYTHONDONTWRITEBYTECODE="1", **env_extra)
    return subprocess.run(["bash", str(FLAG_WRITER), *args], capture_output=True, text=True, env=env, timeout=60)


def test_the_flag_writer_writes_the_sentinel_and_reports_it(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    run = _flag_writer(project, "--source-command", "dev", "--session-id", "dev-20260101-000000", "--flag",
                       "codex", CLAUDE_PROJECT_DIR=str(project), CLAUDE_SESSION_ID="sess-1")
    assert run.returncode == 0, run.stderr
    target = project / ".claude" / "dev-registry" / "dev-20260101-000000" / "codex-enforce.json"
    assert run.stdout == f"Codex enforcement active: {target}\n"
    text = target.read_text()
    flag = json.loads(text)
    assert text.startswith('{\n  "schema_version": 1,\n  "enabled": true,\n') and text.endswith("}\n")
    assert {k: v for k, v in flag.items() if k != "created_at"} == {
        "schema_version": 1, "enabled": True, "source_command": "dev",
        "dev_session_id": "dev-20260101-000000", "claude_session_id": "sess-1"}
    run = _flag_writer(project, "--source-command", "dev-overnight", "--session-id", "s-1", "--flag", "codex",
                       CLAUDE_PROJECT_DIR=str(project))
    assert run.returncode == 0, run.stderr
    other = json.loads((project / ".claude" / "dev-registry" / "s-1" / "codex-enforce.json").read_text())
    assert other["claude_session_id"] == "unknown"


@pytest.mark.parametrize("args, message", [
    (["--session-id", "s", "--flag", "codex"], "--source-command required"),
    (["--source-command", "dev", "--flag", "codex"], "--session-id required"),
    (["--source-command", "dev", "--session-id", "s"], "at least one --flag required"),
    (["--source-command", "dev", "--session-id", "../x", "--flag", "codex"], "unsafe characters"),
    (["--source-command", "dev", "--session-id", "s", "--flag", "codex", "--flag", "bogus"], "(expected: codex)"),
    (["--source-command", "dev", "--session-id", "s", "--bogus", "x"], "Unknown arg: --bogus"),
])
def test_the_flag_writer_refuses_before_writing_anything(tmp_path, args, message):
    project = tmp_path / "project"
    project.mkdir()
    run = _flag_writer(project, *args, CLAUDE_PROJECT_DIR=str(project))
    assert run.returncode == 1 and message in run.stderr, run.stderr
    assert not (project / ".claude").exists()


def test_the_flag_writer_refuses_a_symlinked_sentinel_and_a_missing_project(tmp_path):
    project = tmp_path / "project"
    registry = project / ".claude" / "dev-registry" / "s"
    registry.mkdir(parents=True)
    (registry / "codex-enforce.json").symlink_to(tmp_path / "elsewhere.json")
    run = _flag_writer(project, "--source-command", "dev", "--session-id", "s", "--flag", "codex",
                       CLAUDE_PROJECT_DIR=str(project))
    assert run.returncode == 1 and "refusing to write through a symlink" in run.stderr
    assert not (tmp_path / "elsewhere.json").exists()
    run = _flag_writer(project, "--source-command", "dev", "--session-id", "s", "--flag", "codex")
    assert run.returncode == 1 and "CLAUDE_PROJECT_DIR not set" in run.stderr
