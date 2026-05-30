"""Shared fixtures for the 20260530-105221 graphify real-CLI integration tests.

These tests exercise the REAL `graphify` v0.8.25 binary (per the shared
healthy-path real-binary clause in the AC spec). If the real binary is not on
PATH (or GRAPHIFY_BIN), the healthy-path tests SKIP rather than pass via a stub
— a stubbed/never-executed binary does NOT satisfy a healthy-path proof (codex#1).

Every fixture builds an OUT-OF-REPO source repo + cache so a single test run can:
  - build a real graph.json (node-link schema),
  - run the wrappers with CLAUDE_PROJECT_DIR pointed at the fixture repo,
  - assert zero pollution of BOTH the fixture repo and the real .claude repo.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]   # the .claude repo
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def real_graphify_bin() -> str | None:
    """Resolve the REAL graphify binary (GRAPHIFY_BIN override or PATH)."""
    override = os.environ.get("GRAPHIFY_BIN", "").strip()
    if override and Path(override).exists():
        return override
    found = shutil.which("graphify")
    return found


def _verify_real_binary(bin_path: str) -> bool:
    """Confirm the binary is the real graphify (v0.8.x), not a shim."""
    try:
        r = subprocess.run([bin_path, "--version"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and "graphify" in (r.stdout + r.stderr).lower()
    except Exception:
        return False


@pytest.fixture
def real_binary():
    """Skip the test unless a verified real graphify binary is available."""
    bin_path = real_graphify_bin()
    if not bin_path or not _verify_real_binary(bin_path):
        pytest.skip("real graphify v0.8.25 binary not available on PATH/GRAPHIFY_BIN — "
                    "healthy-path proof requires the real binary (codex#1)")
    return bin_path


@pytest.fixture
def fixture_env(tmp_path, monkeypatch):
    """Out-of-repo source repo + cache root + dev-registry, with env wired.

    Returns a dict carrying paths and the graphify env. The source repo contains
    a small import graph (mod_a.py <- mod_b.py) so the focused subgraph has
    >=2 nodes and >=1 link (AC14). CLAUDE_PROJECT_DIR points at the fixture repo
    so cacheDir = <cache_root>/<repo_key> resolves OUTSIDE this .claude repo.
    """
    src = tmp_path / "fixrepo"
    cache_root = tmp_path / "cacheroot"
    src.mkdir()
    cache_root.mkdir()
    (src / "mod_a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (src / "mod_b.py").write_text("import mod_a\ndef beta():\n    return mod_a.alpha() + 1\n", encoding="utf-8")
    reg = src / ".claude" / "dev-registry" / "t1" / "graphify"
    reg.mkdir(parents=True)

    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(src)
    env["CLAUDE_GRAPHIFY_CACHE_ROOT"] = str(cache_root)
    env["CLAUDE_GRAPHIFY_ENABLED"] = "auto"
    env.pop("GRAPHIFY_OUT", None)  # wrapper sets this internally; must not be inherited

    repo_key = "_".join([p for p in src.parts if p][-2:])
    cache_dir = cache_root / repo_key
    return {
        "src": src,
        "cache_root": cache_root,
        "cache_dir": cache_dir,
        "graph_json": cache_dir / "graph.json",
        "registry": reg.parent,        # .../dev-registry/t1
        "env": env,
        "repo_key": repo_key,
    }


def run_script(name: str, args: list[str], env: dict, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a scripts/<name> wrapper as a subprocess with the given env."""
    cmd = [sys.executable, str(_SCRIPTS_DIR / name)] + args
    return subprocess.run(cmd, capture_output=True, text=True, env=env,
                          cwd=str(cwd) if cwd else str(_REPO_ROOT), timeout=320)


def build_cache(fixture_env: dict, real_binary: str) -> None:
    """Build a real graph.json in the fixture cache via maintain.py init."""
    r = run_script("graphify-maintain.py", ["init"], fixture_env["env"])
    assert fixture_env["graph_json"].exists(), (
        f"init did not create graph.json: stdout={r.stdout} stderr={r.stderr}")


def write_blast_radius_map(fixture_env: dict, modified_files: list[str]) -> Path:
    """Write a blast-radius-map.json into the fixture dev-registry."""
    path = fixture_env["registry"] / "blast-radius-map.json"
    path.write_text(json.dumps({"modified_files": modified_files, "edges": []}), encoding="utf-8")
    return path


def repo_pollution(repo: Path) -> list[str]:
    """Return any graphify CLI artifacts found inside repo (excluding dev-registry)."""
    forbidden_names = {"graph.json", "GRAPH_REPORT.md", "graph.html",
                       ".graphify_root", ".graphify_labels.json"}
    hits = []
    for p in repo.rglob("*"):
        rel = str(p.relative_to(repo))
        if "dev-registry" in rel:
            continue
        if p.name in forbidden_names or p.name == "graphify-out":
            hits.append(rel)
    return hits


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def serialize_all(*objs) -> str:
    """Concatenate JSON serializations of all objects for recursive substring scans."""
    return "\n".join(json.dumps(o, ensure_ascii=False) for o in objs)
