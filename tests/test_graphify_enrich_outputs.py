"""graphify-enrich.py writes only its own outputs (P1b E10, scope row 4); it and
graphify-query.py check their results against their schemas before writing (P10 A17).

The script reads the context file it is given and never writes it; it writes the run
record (with the fingerprint /dev-overnight Step 11g compares) on every path and the
focused subgraph dev's and QA's dispatches name only when enrichment produced one; the
graph cache it refreshes is written by graphify-maintain.py alone. Every run here uses a
stub graphify binary and a cache root under the test's own tmp_path.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from hooks.lib.contract_runtime import validate

ROOT = Path(__file__).resolve().parent.parent
ENRICH = ROOT / "scripts" / "graphify-enrich.py"
QUERY = ROOT / "scripts" / "graphify-query.py"
REFINE = ROOT / "scripts" / "refine-context.sh"

GRAPH = {
    "nodes": [
        {"id": "f_init", "label": "__init__.py", "source_file": "toy/__init__.py"},
        {"id": "s_add", "label": "add", "source_file": "toy/__init__.py"},
        {"id": "f_test", "label": "test_add.py", "source_file": "tests/test_add.py"},
    ],
    "links": [
        {"source": "f_init", "target": "s_add", "relation": "contains"},
        {"source": "f_test", "target": "f_init", "relation": "imports_from"},
    ],
}

# The stub logs each call with the command line of the process that ran it, so a test
# can tell which script wrote the cache.
STUB = """#!{python}
import json, os, sys
args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as fh:
    caller = open(f"/proc/{{os.getppid()}}/cmdline", "rb").read().replace(b"\\0", b" ").decode()
    fh.write(json.dumps({{"args": args, "caller": caller}}) + "\\n")
if args and args[0] == "update":
    with open(os.path.join(os.environ["GRAPHIFY_OUT"], "graph.json"), "w") as fh:
        json.dump({graph}, fh)
elif args and args[0] == "affected":
    print("affected: tests/test_add.py")
elif args and args[0] == "--version":
    print("graphify stub")
"""


def _project(tmp_path: Path, with_map: bool = True) -> tuple[Path, Path, dict]:
    proj = tmp_path / "proj"
    (proj / "docs" / "dev").mkdir(parents=True)
    registry = proj / ".claude" / "dev-registry" / "dev-T1"
    registry.mkdir(parents=True)
    if with_map:
        (registry / "blast-radius-map.json").write_text(
            json.dumps({"modified_files": ["toy/__init__.py"]}), encoding="utf-8")
    context = proj / "docs" / "dev" / "context-T1.json"
    context.write_text(json.dumps({"task_id": "T1", "requirement": {}, "root_cause_analysis": {},
                                   "waves": [{"wave_id": 1, "tasks": []}],
                                   "blast_radius_map_path": ".claude/dev-registry/dev-T1/blast-radius-map.json"}),
                       encoding="utf-8")
    stub = tmp_path / "bin" / "graphify"
    stub.parent.mkdir()
    stub.write_text(STUB.format(python=sys.executable, graph=json.dumps(GRAPH)), encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj), GRAPHIFY_BIN=str(stub),
               CLAUDE_GRAPHIFY_CACHE_ROOT=str(tmp_path / "cache"), STUB_LOG=str(tmp_path / "stub.log"),
               PYTHONDONTWRITEBYTECODE="1")
    env.pop("CLAUDE_GRAPHIFY_ENABLED", None)
    return proj, context, env


def _seed_cache(tmp_path: Path, env: dict) -> None:
    """An earlier run's cache, as graphify-maintain.py init leaves it."""
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "graphify-maintain.py"), "init"],
                          env=env, cwd=env["CLAUDE_PROJECT_DIR"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    (tmp_path / "stub.log").unlink()


def _enrich(proj: Path, env: dict, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ENRICH), "--task-id", "dev-T1",
                           "--context-file", "docs/dev/context-T1.json", *extra],
                          env=env, cwd=proj, capture_output=True, text=True)


def _outputs(proj: Path) -> set[str]:
    out = proj / ".claude" / "dev-registry" / "dev-T1" / "graphify"
    return {p.name for p in out.iterdir() if not p.name.endswith(".lock")}


def _run_record(proj: Path) -> dict:
    return json.loads((proj / ".claude" / "dev-registry" / "dev-T1" / "graphify" /
                       "graphify-run.json").read_text(encoding="utf-8"))


def test_enrichment_writes_its_own_two_files_and_never_the_context(tmp_path):
    proj, context, env = _project(tmp_path)
    _seed_cache(tmp_path, env)
    before = context.read_bytes()
    proc = _enrich(proj, env)
    assert proc.returncode == 0, proc.stderr
    assert context.read_bytes() == before
    assert _outputs(proj) == {"graphify-run.json", "focused-subgraph.json"}
    run = _run_record(proj)
    assert run["status"] == "ok"
    assert "context_patch" not in run
    focused = json.loads((proj / ".claude" / "dev-registry" / "dev-T1" / "graphify" /
                          "focused-subgraph.json").read_text(encoding="utf-8"))
    # Everything the base's in-place graph_context carried reaches dev through this file.
    for key in ("nodes", "edges", "impact_files", "orientation_mode", "expansion_stats",
                "resolved_node_ids", "unresolved_paths", "affected_cli_status",
                "graphify_affected_results", "summary"):
        assert key in focused, key
    assert focused["status"] == "ok" and focused["nodes"]
    assert validate(focused, "graphify-focused-subgraph.v1")["ok"]


def test_run_record_carries_the_step_11g_fingerprint(tmp_path):
    proj, context, env = _project(tmp_path)
    _seed_cache(tmp_path, env)
    proc = _enrich(proj, env, "--pipeline-index", "2", "--iteration", "1")
    assert proc.returncode == 0, proc.stderr
    run = _run_record(proj)
    assert run["pipeline_index"] == 2
    assert run["iteration"] == 1
    assert run["context_path"] == "docs/dev/context-T1.json"
    assert run["context_sha256"] == hashlib.sha256(context.read_bytes()).hexdigest()


def test_skip_and_unavailable_paths_write_only_the_run_record(tmp_path):
    proj, context, env = _project(tmp_path, with_map=False)
    before = context.read_bytes()
    assert _enrich(proj, env).returncode == 0
    assert _outputs(proj) == {"graphify-run.json"}
    assert _run_record(proj)["status"] == "skipped"
    assert context.read_bytes() == before

    proj2, context2, env2 = _project(tmp_path / "second")
    env2["GRAPHIFY_BIN"] = str(tmp_path / "no-such-binary")
    before2 = context2.read_bytes()
    assert _enrich(proj2, env2, "--iteration", "0").returncode == 0
    assert _outputs(proj2) == {"graphify-run.json"}
    run = _run_record(proj2)
    assert run["status"] == "unavailable"
    assert run["iteration"] == 0 and run["pipeline_index"] is None
    assert run["context_sha256"] == hashlib.sha256(before2).hexdigest()
    assert context2.read_bytes() == before2


def test_the_cache_refresh_runs_through_graphify_maintain(tmp_path):
    proj, _context, env = _project(tmp_path)
    _seed_cache(tmp_path, env)
    assert _enrich(proj, env).returncode == 0
    calls = [json.loads(line) for line in (tmp_path / "stub.log").read_text().splitlines()]
    updates = [c for c in calls if c["args"][:1] == ["update"]]
    assert updates, calls
    assert all("graphify-maintain.py" in c["caller"] for c in updates), updates
    # enrich itself only queries the graph
    own = [c for c in calls if "graphify-enrich.py" in c["caller"]]
    assert own and all(c["args"][0] in ("affected", "--version") for c in own), own


def _load(script: Path, env: dict, monkeypatch):
    """The producer loaded in this process with the test project's environment, so a test
    can replace one of its builders."""
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("CLAUDE_GRAPHIFY_ENABLED", raising=False)
    monkeypatch.chdir(env["CLAUDE_PROJECT_DIR"])
    spec = importlib.util.spec_from_file_location(script.stem.replace("-", "_"), script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _graphify_out(proj: Path, name: str) -> dict:
    return json.loads((proj / ".claude" / "dev-registry" / "dev-T1" / "graphify" / name).read_text(encoding="utf-8"))


def test_a_malformed_focused_subgraph_is_written_as_failed_and_so_is_the_run(tmp_path, monkeypatch):
    proj, _context, env = _project(tmp_path)
    _seed_cache(tmp_path, env)
    enrich = _load(ENRICH, env, monkeypatch)
    build = enrich._build_focused_subgraph
    monkeypatch.setattr(enrich, "_build_focused_subgraph", lambda *a: {**build(*a), "edges": "not a list"})
    monkeypatch.setattr(sys, "argv", ["graphify-enrich.py", "--task-id", "dev-T1",
                                      "--context-file", "docs/dev/context-T1.json"])
    assert enrich.main() == 0
    focused = _graphify_out(proj, "focused-subgraph.json")
    assert focused["status"] == "failed" and focused["task_id"] == "dev-T1"
    assert focused["error_detail"].startswith("graphify-focused-subgraph.v1: edges:")
    assert validate(focused, "graphify-focused-subgraph.v1")["ok"]
    run = _run_record(proj)
    assert run["status"] == "failed" and run["error_detail"] == focused["error_detail"]


def _query_project(tmp_path: Path) -> tuple[Path, Path, dict]:
    proj, _context, env = _project(tmp_path)
    _seed_cache(tmp_path, env)
    req = proj / "docs" / "dev" / "requirement-T1.md"
    req.write_text("Fix add in toy/__init__.py\n", encoding="utf-8")
    return proj, req, env


def test_well_formed_pre_queries_validate_and_are_written_as_produced(tmp_path):
    proj, req, env = _query_project(tmp_path)
    for extra, status in (([], "ok"), (["--no-graphify"], "skipped")):
        proc = subprocess.run([sys.executable, str(QUERY), "--task-id", "dev-T1",
                               "--requirement-file", str(req), *extra],
                              env=env, cwd=proj, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        pre = _graphify_out(proj, "pre_query.json")
        assert pre["status"] == status, pre
        assert validate(pre, "graphify-prequery.v1")["ok"]
    env["GRAPHIFY_BIN"] = str(tmp_path / "no-such-binary")
    assert subprocess.run([sys.executable, str(QUERY), "--task-id", "dev-T1", "--requirement-file", str(req)],
                          env=env, cwd=proj, capture_output=True).returncode == 0
    pre = _graphify_out(proj, "pre_query.json")
    assert pre["status"] == "unavailable" and validate(pre, "graphify-prequery.v1")["ok"]


def test_a_malformed_pre_query_is_written_as_failed(tmp_path, monkeypatch):
    proj, req, env = _query_project(tmp_path)
    query = _load(QUERY, env, monkeypatch)
    monkeypatch.setattr(query, "_build_import_excerpt", lambda graph, anchors: [{"not": "a string"}])
    monkeypatch.setattr(sys, "argv", ["graphify-query.py", "--task-id", "dev-T1", "--requirement-file", str(req)])
    assert query.main() == 0
    pre = _graphify_out(proj, "pre_query.json")
    assert pre["status"] == "failed" and pre["task_id"] == "dev-T1"
    assert pre["structural_context"] == {} and pre["ambiguity_hypotheses"] == []
    assert pre["error_detail"].startswith("graphify-prequery.v1: structural_context.import_graph_excerpt.0:")
    assert validate(pre, "graphify-prequery.v1")["ok"]


def test_refine_context_stub_passes_the_context_through(tmp_path):
    text = REFINE.read_text(encoding="utf-8")
    assert any(line.startswith("# STUB:") for line in text.splitlines())
    assert os.access(REFINE, os.X_OK)
    ctx = tmp_path / "context.json"
    ctx.write_text('{"task_id": "T1"}\n', encoding="utf-8")
    qa = tmp_path / "qa-report.json"
    qa.write_text('{"qa": {"refined_context": {"x": 1}}}', encoding="utf-8")
    proc = subprocess.run(["bash", str(REFINE), str(ctx), str(qa), "2"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert proc.stdout == ctx.read_text(encoding="utf-8")
    proc = subprocess.run(["bash", str(REFINE)], capture_output=True, text=True)
    assert proc.returncode == 0 and proc.stdout == ""
