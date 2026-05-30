"""Shared fixtures/helpers for the 20260530-170350 graphify semantic-path tests.

Most ACs here are IN-PROCESS (gate helper, cmd_semantic with run_graphify_cmd
spied to materialize controlled update/extract outputs) so they do NOT require
the real binary. AC2/AC4/AC5 are real-binary; they SKIP (neutral) when the
binary is absent — SKIP is NEVER PASS (codex #8).
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def load_script_module(filename: str, modname: str):
    """Import a hyphenated scripts/<filename> file as a fresh module object."""
    spec = importlib.util.spec_from_file_location(modname, str(_SCRIPTS / filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def real_graphify_bin() -> str | None:
    override = os.environ.get("GRAPHIFY_BIN", "").strip()
    if override and Path(override).exists():
        return override
    return shutil.which("graphify")


def _verify_real_binary(bin_path: str) -> bool:
    try:
        r = subprocess.run([bin_path, "--version"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and "graphify" in (r.stdout + r.stderr).lower()
    except Exception:
        return False


@pytest.fixture
def real_binary():
    bin_path = real_graphify_bin()
    if not bin_path or not _verify_real_binary(bin_path):
        pytest.skip("real graphify v0.8.25 binary not available — real-binary proof "
                    "requires it; SKIP is neutral, not pass (codex #8/#1)")
    return bin_path


@pytest.fixture
def cache_env(tmp_path, monkeypatch):
    """Out-of-repo source repo + cache root with env wired (no binary needed).

    Returns paths + an env dict. CLAUDE_PROJECT_DIR points at the fixture repo so
    cacheDir resolves OUTSIDE this .claude repo.
    """
    src = tmp_path / "fixrepo"
    cache_root = tmp_path / "cacheroot"
    src.mkdir()
    cache_root.mkdir()
    (src / "mod_a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")

    repo_key = "_".join([p for p in src.parts if p][-2:])
    cache_dir = cache_root / repo_key
    cache_dir.mkdir(parents=True)

    env = {
        "CLAUDE_PROJECT_DIR": str(src),
        "CLAUDE_GRAPHIFY_CACHE_ROOT": str(cache_root),
        "CLAUDE_GRAPHIFY_ENABLED": "auto",
    }
    return {
        "src": src,
        "cache_root": cache_root,
        "cache_dir": cache_dir,
        "graph_json": cache_dir / "graph.json",
        "run_manifest": cache_dir / "run-manifest.json",
        "extract_out": cache_dir / "graphify-out" / "graph.json",
        "repo_key": repo_key,
        "env": env,
    }


def apply_env(monkeypatch, env: dict, extra: dict | None = None, clear_keys=()):
    """Apply env vars onto os.environ via monkeypatch; optionally clear some keys."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    if extra:
        for k, v in extra.items():
            monkeypatch.setenv(k, v)
    for k in clear_keys:
        monkeypatch.delenv(k, raising=False)


def graph_dict(nodes, links):
    return {"nodes": [{"id": n, "label": n, "source_file": f"{n}.py"} for n in nodes],
            "links": links}


def link(src, tgt, rel="references", conf="EXTRACTED", sf="a.py", loc="L1", ctx=None):
    d = {"source": src, "target": tgt, "relation": rel, "confidence": conf,
         "source_file": sf, "source_location": loc, "weight": 1.0, "confidence_score": 1.0}
    if ctx is not None:
        d["context"] = ctx
    return d


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def repo_pollution(repo: Path) -> list[str]:
    forbidden = {"graph.json", "GRAPH_REPORT.md", "graph.html",
                 ".graphify_root", ".graphify_labels.json", "graphify-out"}
    hits = []
    for p in repo.rglob("*"):
        rel = str(p.relative_to(repo))
        if "dev-registry" in rel:
            continue
        if p.name in forbidden:
            hits.append(rel)
    return hits
