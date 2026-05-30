"""
graphify_lib.py — shared library for Graphify knowledge-graph integration.

Drives the REAL `graphifyy` v0.8.25 CLI (command `graphify`). Provides: status
state machine, EXCLUDE_FRAGMENTS sensitive-path scrubbing (applied ON READ),
file locking, out-of-repo cache resolution, cache-root-inside-repo refusal,
node-link graph.json parsing, and the subprocess runner that EVERY graphify
call must route through (so cwd=cacheDir + GRAPHIFY_OUT=cacheDir + numeric
timeout are enforced unconditionally — see M1a/AC4/AC13).

Real CLI surface (empirically verified against graphify 0.8.25):
  graphify update <repo>                          AST-only re-extract; writes
                                                  graph.json/report/html/cache to
                                                  $GRAPHIFY_OUT (absolute), manifest
                                                  to <cwd>/graphify-out/manifest.json.
  graphify extract <repo> --out DIR --backend B   AST + semantic (docs/papers/images
                                                  via LLM backend); writes to
                                                  DIR/graphify-out/graph.json.
  graphify query "<q>" --graph G --budget N       BFS traversal, human-readable TEXT.
  graphify affected "<node.id>" --graph G --depth N  reverse traversal, TEXT.

Graph schema (verified): NetworkX node-link. Top keys
  {directed, multigraph, graph, nodes, links, hyperedges}.
  Edges are under `links` (NOT `edges`) with keys source/target/relation/
  confidence/source_file. Nodes carry id/label/source_file/community/file_type.

Status state machine (all 5 states):
  ok          — binary present, cache hit (cacheDir/graph.json exists), data extracted
  degraded    — binary ran but output parse error / partial data
  failed      — binary present but runtime error: non-zero exit, timeout, exception
  unavailable — binary absent OR cache-root missing/empty OR no cacheDir/graph.json
                OR cache_root_inside_repo refusal
  skipped     — CLAUDE_GRAPHIFY_ENABLED=0 OR --no-graphify OR nil blast-radius-map

Advisory vs blocking:
  Graphify tool failure (degraded/failed/unavailable/skipped) is ADVISORY — DEV/BA
  always receive a valid (possibly empty) artifact; tool failure NEVER blocks /dev.
  Requirement ambiguity (ambiguity_hypotheses in pre_query.json) is the only
  CLARIFICATION-BLOCKING signal (BA returns needs_clarification).
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Exclusion fragments — two authority sources (kept separate for auditability)
# ---------------------------------------------------------------------------

# Sensitive-data patterns — authority: spec §5 Risk item 7 + arch-8 + AC15.
# These prevent credentials and secrets from leaking from the REAL graph.json
# (which may contain more nodes than the old fictional cache) into the
# structural_context / graph_context surfaced to BA / DEV.
_SENSITIVE_DATA_FRAGMENTS = (
    ".env",
    "credentials",
    "keys",
    "/logs/",
    ".pem",
    ".key",
    ".secret",
    "secrets/",
)

# Filesystem-noise patterns — authority: scripts/blast-radius-tool.py:35-38.
_FILESYSTEM_NOISE_FRAGMENTS = (
    "/venv/",
    "/worktrees/",
    "/.archive/",
    "/plugins/",
    "/.git/",
    "/__pycache__/",
    "/node_modules/",
)

# Combined tuple exposed as the public API.
EXCLUDE_FRAGMENTS = _SENSITIVE_DATA_FRAGMENTS + _FILESYSTEM_NOISE_FRAGMENTS

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_FAILED = "failed"
STATUS_UNAVAILABLE = "unavailable"
STATUS_SKIPPED = "skipped"

# ---------------------------------------------------------------------------
# Concrete numeric timeouts (seconds) — AC13. NO timeout=None anywhere.
# ---------------------------------------------------------------------------

TIMEOUT_QUERY = 15          # Step 1.5 advisory `graphify query`
TIMEOUT_AFFECTED = 20       # Step 7.5 advisory `graphify affected`/`query`
TIMEOUT_SEMANTIC_PROBE = 30  # /usr/bin/claude-routed semantic extract probe
TIMEOUT_UPDATE = 60         # incremental Step 7.5 `graphify update`
TIMEOUT_INIT = 300          # user-triggered full-repo `graphify update`


# ---------------------------------------------------------------------------
# Feature flag helpers
# ---------------------------------------------------------------------------

def is_graphify_enabled() -> bool:
    """Return False only when CLAUDE_GRAPHIFY_ENABLED=0 (explicit disable).

    Default (unset) and "auto"/"1" all enable. Re-enabled gate per M4/AC5.
    """
    val = os.environ.get("CLAUDE_GRAPHIFY_ENABLED", "auto").strip().lower()
    return val != "0"


def get_graphify_bin() -> str | None:
    """Return graphify CLI path from GRAPHIFY_BIN env or PATH search, or None."""
    override = os.environ.get("GRAPHIFY_BIN", "").strip()
    if override:
        return override if Path(override).exists() else None
    import shutil
    return shutil.which("graphify")


def get_project_dir() -> Path:
    """Return the project (repo) directory the wrappers operate on."""
    return Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()


def get_cache_root() -> Path:
    """Return the global Graphify cache root (OUTSIDE the repo by default)."""
    override = os.environ.get("CLAUDE_GRAPHIFY_CACHE_ROOT", "").strip()
    return (Path(override) if override else Path("/var/tmp/claude-graphify")).resolve()


def get_repo_key(project_dir: Path | None = None) -> str:
    """Derive a stable repo key from the project directory path."""
    root = project_dir or get_project_dir()
    parts = [p for p in root.parts if p not in ("/", "")]
    return "_".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else "unknown")


def get_cache_dir(project_dir: Path | None = None) -> Path:
    """Return the per-repo cache directory: <cache_root>/<repo_key>.

    This is the directory used as BOTH the subprocess cwd AND GRAPHIFY_OUT for
    every graphify invocation, so all CLI byproducts (graph.json, report, html,
    cache/, AND the cwd-relative graphify-out/manifest.json) land inside it and
    the source repo stays clean (AC4).
    """
    root = project_dir or get_project_dir()
    return (get_cache_root() / get_repo_key(root)).resolve()


def graph_json_path(project_dir: Path | None = None) -> Path:
    """Return the canonical graph.json path inside the cache dir."""
    return get_cache_dir(project_dir) / "graph.json"


def is_cache_root_inside_repo(project_dir: Path | None = None) -> bool:
    """Return True if the resolved cache dir lives inside the target repo (R-9/AC13).

    A cache inside the repo would pollute it even with cwd=cacheDir, so callers
    must refuse to run graphify in that case.
    """
    repo = (project_dir or get_project_dir()).resolve()
    cache = get_cache_dir(project_dir)
    try:
        cache.relative_to(repo)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# File locking (mirrors scripts/spec-check.py:171)
# ---------------------------------------------------------------------------

def write_json_locked(path: Path, data: Any, indent: int = 2) -> None:
    """Write JSON to path under fcntl.LOCK_EX to prevent concurrent corruption."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with open(lock_path, "w") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        try:
            path.write_text(json.dumps(data, indent=indent, ensure_ascii=False), encoding="utf-8")
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


def read_json_safe(path: Path) -> tuple[Any, str]:
    """Read JSON from path. Returns (data, status) — STATUS_OK / UNAVAILABLE / DEGRADED."""
    try:
        text = Path(path).read_text(encoding="utf-8")
        return json.loads(text), STATUS_OK
    except (FileNotFoundError, PermissionError):
        return None, STATUS_UNAVAILABLE
    except json.JSONDecodeError:
        return None, STATUS_DEGRADED


# ---------------------------------------------------------------------------
# Cache availability check — keyed on cacheDir/graph.json (AC12), NOT the old
# fictional <cache_root>/<repo_key>/manifest.json path.
# ---------------------------------------------------------------------------

def check_cache_available(repo_key: str | None = None,
                          project_dir: Path | None = None) -> tuple[bool, str]:
    """Return (available, reason).

    Available requires: gate enabled, graphify binary present, cache-root NOT
    inside the repo, AND cacheDir/graph.json exists. The presence of graph.json
    (not a legacy manifest path) is the real availability signal (AC12).
    """
    if not is_graphify_enabled():
        return False, "CLAUDE_GRAPHIFY_ENABLED=0"
    bin_path = get_graphify_bin()
    if not bin_path:
        return False, "GRAPHIFY_BIN absent (binary not found in PATH or GRAPHIFY_BIN override)"
    if is_cache_root_inside_repo(project_dir):
        return False, "cache_root_inside_repo"
    gpath = graph_json_path(project_dir)
    if not gpath.exists():
        return False, f"no graph.json at {gpath}"
    return True, "ok"


# ---------------------------------------------------------------------------
# Subprocess runner — EVERY graphify call routes through here. Enforces
# cwd=cacheDir + GRAPHIFY_OUT=cacheDir (M1a) + a mandatory numeric timeout (AC13).
# ---------------------------------------------------------------------------

def run_graphify_cmd(
    args: list[str],
    timeout_seconds: int,
    cache_dir: Path,
) -> tuple[int, str, str]:
    """Run the graphify CLI with the given args list (subcommand + flags).

    `args` MUST be the real subcommand vector, e.g. ["update", repo] or
    ["query", question, "--graph", graph, "--budget", "2000"]. The binary path
    is prepended internally — callers never pass the executable.

    cwd and GRAPHIFY_OUT are BOTH set to cache_dir (absolute) unconditionally so
    every byproduct lands in the cache and the repo stays clean. The wrappers
    MUST NOT inherit an ambient GRAPHIFY_OUT for the call (M1a).

    timeout_seconds is REQUIRED and numeric (AC13 — no timeout=None ever).
    Returns (exit_code, stdout, stderr). exit_code == -1 on timeout/exception.
    """
    bin_path = get_graphify_bin()
    if not bin_path:
        return -1, "", "GRAPHIFY_BIN absent"
    cache_dir = Path(cache_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["GRAPHIFY_OUT"] = str(cache_dir)  # absolute; overrides any ambient value
    cmd = [bin_path] + list(args)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(cache_dir),
            env=env,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {timeout_seconds}s"
    except FileNotFoundError as exc:
        return -1, "", f"binary not found: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        return -1, "", f"subprocess error: {exc}"


# ---------------------------------------------------------------------------
# Path exclusion helpers — sensitive scrubbing applied ON READ (AC15).
# ---------------------------------------------------------------------------

def _normalize_path(value: str) -> str:
    """Normalize a string for fragment scanning: unify separators + collapse slashes."""
    s = str(value).replace("\\", "/")
    while "//" in s:
        s = s.replace("//", "/")
    return s


def should_exclude_path(path: str) -> bool:
    """Return True if path (normalized) matches any EXCLUDE_FRAGMENTS entry."""
    norm = _normalize_path(path)
    return any(fragment in norm for fragment in EXCLUDE_FRAGMENTS)


def contains_sensitive_fragment(text: str) -> bool:
    """Return True if arbitrary text (e.g. raw CLI stdout) carries a sensitive fragment.

    Only the SENSITIVE-DATA fragments matter for stdout redaction (filesystem
    noise like /venv/ is not a leak). Used to gate whether raw graphify stdout
    may be emitted into an artifact (AC15).
    """
    norm = _normalize_path(text)
    return any(frag in norm for frag in _SENSITIVE_DATA_FRAGMENTS)


def node_references_sensitive(node: dict) -> bool:
    """Return True if any of a graph node's identifying fields is sensitive."""
    for field in ("id", "label", "source_file", "norm_label"):
        val = node.get(field)
        if isinstance(val, str) and should_exclude_path(val):
            return True
    return False


def scrub_sensitive(obj: Any) -> Any:
    """Recursively drop sensitive substrings from any JSON-serializable structure.

    Used as a final guard on emitted artifacts (AC15): strings carrying a
    sensitive fragment are redacted, dict entries whose key/value is sensitive
    are dropped, and list elements that are sensitive strings are removed.
    """
    if isinstance(obj, str):
        return "[redacted]" if contains_sensitive_fragment(obj) else obj
    if isinstance(obj, dict):
        out: dict = {}
        for k, v in obj.items():
            if isinstance(k, str) and contains_sensitive_fragment(k):
                continue
            out[k] = scrub_sensitive(v)
        return out
    if isinstance(obj, list):
        result = []
        for item in obj:
            if isinstance(item, str) and contains_sensitive_fragment(item):
                continue
            result.append(scrub_sensitive(item))
        return result
    return obj


# ---------------------------------------------------------------------------
# Node-link graph.json parsing — real schema (links/source/target/relation).
# ---------------------------------------------------------------------------

def load_graph(graph_path: Path) -> tuple[dict, str]:
    """Load + parse graph.json. Returns (graph_dict, status).

    On success the dict carries nodes[] and links[]. Sensitive nodes and any
    link touching a sensitive node are dropped ON READ (AC15) before the graph
    is handed to callers.
    """
    data, status = read_json_safe(Path(graph_path))
    if data is None or not isinstance(data, dict):
        return ({"nodes": [], "links": []},
                status if status != STATUS_OK else STATUS_DEGRADED)
    nodes = data.get("nodes", []) if isinstance(data.get("nodes"), list) else []
    links = data.get("links", []) if isinstance(data.get("links"), list) else []

    safe_nodes = [n for n in nodes if isinstance(n, dict) and not node_references_sensitive(n)]
    safe_ids = {n.get("id") for n in safe_nodes}
    excluded_ids = {n.get("id") for n in nodes
                    if isinstance(n, dict) and node_references_sensitive(n)}

    safe_links = []
    for l in links:
        if not isinstance(l, dict):
            continue
        src, tgt = l.get("source"), l.get("target")
        # Drop links touching an excluded node, or whose own source_file is sensitive.
        if src in excluded_ids or tgt in excluded_ids:
            continue
        sf = l.get("source_file")
        if isinstance(sf, str) and should_exclude_path(sf):
            continue
        # Keep only links whose endpoints survived the node scrub.
        if src in safe_ids and tgt in safe_ids:
            safe_links.append(l)
    return ({"nodes": safe_nodes, "links": safe_links,
             "directed": data.get("directed"), "graph": data.get("graph")},
            STATUS_OK)


def resolve_paths_to_node_ids(modified_paths: list[str], graph: dict,
                              max_ids_per_path: int = 8) -> tuple[dict, list[str]]:
    """Map modified file paths to a bounded set of real node.id values.

    Matches on normalized source_file / relative-path suffix / label, INCLUDING
    symbol nodes whose source_file is the modified file (M3a). Returns
    (resolved_map {path: [node_id,...]}, unresolved_paths[]).
    """
    nodes = graph.get("nodes", [])
    resolved: dict[str, list[str]] = {}
    unresolved: list[str] = []
    for raw in modified_paths:
        if not raw or should_exclude_path(raw):
            continue
        norm = _normalize_path(raw)
        base = norm.rsplit("/", 1)[-1]
        ids: list[str] = []
        for n in nodes:
            nid = n.get("id")
            if not nid:
                continue
            sf = _normalize_path(n.get("source_file", "") or "")
            label = _normalize_path(n.get("label", "") or "")
            # source_file match (exact, suffix, or basename) catches file + symbol nodes.
            if sf and (sf == norm or norm.endswith(sf) or sf.endswith(norm)
                       or sf == base or sf.endswith("/" + base)):
                ids.append(nid)
            elif label and (label == base or label == norm):
                ids.append(nid)
        ids = list(dict.fromkeys(ids))[:max_ids_per_path]  # dedupe, preserve order
        if ids:
            resolved[raw] = ids
        else:
            unresolved.append(raw)
    return resolved, unresolved


# ---------------------------------------------------------------------------
# Build empty graph_context (advisory pass-through for unavailable/failed/skipped)
# ---------------------------------------------------------------------------

def empty_graph_context(status: str, reason: str = "") -> dict:
    """Return a minimal valid graph_context object for non-ok statuses.

    DEV always receives this object; tool failure is advisory (never blocks DEV).
    """
    return {
        "status": status,
        "structural_context": {},
        "summary": {"node_count": 0, "edge_count": 0, "high_centrality_nodes": []},
        "nodes": [],
        "edges": [],
        "ambiguity_hypotheses": [],
        "advisory": True,
        "error_detail": reason,
    }
