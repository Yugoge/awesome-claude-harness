#!/usr/bin/env python3
"""
graphify-maintain.py — Global Graphify cache lifecycle manager (REAL CLI).

Drives the real `graphify` v0.8.25 CLI. The per-repo cache lives OUTSIDE the
repo (default /var/tmp/claude-graphify/<repo_key>); every invocation runs with
cwd=cacheDir AND GRAPHIFY_OUT=cacheDir so all byproducts (graph.json, report,
html, cache/, and the cwd-relative graphify-out/manifest.json) land in the
cache and the source repo stays clean (AC4).

Usage:
  python3 scripts/graphify-maintain.py init    # cold-start full build (user-triggered, <=300s)
  python3 scripts/graphify-maintain.py update  # incremental refresh (advisory, <=60s)
  python3 scripts/graphify-maintain.py status  # show real cache state + semantic mode

init / update both run real `graphify update <repo>` (AST). init additionally
probes semantic extraction (`graphify extract --backend claude-cli`) when a
backend is reachable, but AST is produced FIRST and never lost to a semantic
failure (M6/AC6). NO fictional --init/--update/--output-dir/--project-dir flags.

Feature flags:
  CLAUDE_GRAPHIFY_ENABLED=0   — skip all operations and exit 0
  GRAPHIFY_BIN                — override CLI path
  CLAUDE_GRAPHIFY_CACHE_ROOT  — override /var/tmp/claude-graphify (MUST be outside repo)
  GRAPHIFY_TRIAGE_BACKEND     — force semantic backend (else auto-detect / claude-cli)
  (GRAPHIFY_OUT is wrapper-internal — set to cacheDir by run_graphify_cmd; not a user override.)

Exit codes:
  0 — success or advisory no-op (binary absent, disabled, cache-root-inside-repo)
  1 — init failed with non-zero exit (real build error)
  2 — usage error
"""

import json
import os
import sys
import time
from pathlib import Path

# Locate project root from env (set by Claude harness)
_PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()
sys.path.insert(0, str(_PROJECT_DIR / "scripts"))

from graphify_lib import (
    STATUS_OK, STATUS_FAILED, STATUS_UNAVAILABLE, STATUS_SKIPPED,
    TIMEOUT_UPDATE, TIMEOUT_INIT, TIMEOUT_SEMANTIC_PROBE,
    check_cache_available, get_cache_dir, get_graphify_bin, get_repo_key,
    graph_json_path, is_cache_root_inside_repo, is_graphify_enabled,
    load_graph, run_graphify_cmd, write_json_locked,
)


def _detect_semantic_backend() -> str | None:
    """Return a semantic backend name reachable in THIS environment, or None.

    Auto-detect honours API-key env vars via graphify's own detect_backend;
    absent any key, the keyless `claude-cli` backend is usable iff /usr/bin/claude
    (the `claude` CLI) is on PATH. GRAPHIFY_TRIAGE_BACKEND forces a choice.
    """
    forced = os.environ.get("GRAPHIFY_TRIAGE_BACKEND", "").strip()
    if forced:
        return forced
    for env_key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "MOONSHOT_API_KEY",
                    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        if os.environ.get(env_key):
            return None  # let graphify auto-detect the keyed backend via `extract`
    import shutil
    if shutil.which("claude"):
        return "claude-cli"
    return None


def _probe_semantic(repo: Path, cache_dir: Path, ast_node_count: int) -> tuple[str, str]:
    """Bounded semantic probe (AC6 — proof not presence).

    Runs `graphify extract --backend <b> --out cacheDir` and only declares
    semantic mode active if the resulting graph actually changed (node count
    differs from the AST baseline). AST graph is already on disk and is never
    lost: on any failure we keep it and report ast_only.

    Returns (semantic_mode, semantic_backend_probe_reason).
    """
    backend = _detect_semantic_backend()
    if not backend:
        return "ast_only", "no semantic backend reachable (no API key, claude CLI absent)"
    args = ["extract", str(repo), "--out", str(cache_dir), "--backend", backend]
    exit_code, stdout, stderr = run_graphify_cmd(
        args, timeout_seconds=TIMEOUT_SEMANTIC_PROBE, cache_dir=cache_dir,
    )
    if exit_code != 0:
        return "ast_only", f"semantic probe via {backend} failed (exit={exit_code}); AST graph retained"
    # extract writes to <cacheDir>/graphify-out/graph.json — promote it to cacheDir/graph.json
    extracted = cache_dir / "graphify-out" / "graph.json"
    if not extracted.exists():
        return "ast_only", f"semantic probe via {backend} produced no graph.json; AST retained"
    sem_graph, st = load_graph(extracted)
    sem_nodes = len(sem_graph.get("nodes", []))
    if st == STATUS_OK and sem_nodes > ast_node_count:
        # Proof: semantic path materially changed the graph. Promote it.
        try:
            graph_json_path(_PROJECT_DIR).write_text(
                extracted.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception as exc:
            return "ast_only", f"semantic graph promote failed: {exc}; AST retained"
        return f"semantic:{backend}", f"semantic path changed graph ({ast_node_count}->{sem_nodes} nodes) via {backend}"
    return "ast_only", (f"semantic probe via {backend} did not change graph "
                        f"(ast={ast_node_count}, sem={sem_nodes}); AST retained")


def _run_ast_build(repo: Path, cache_dir: Path, timeout: int) -> tuple[int, str, str]:
    """Run real `graphify update <repo>` (AST). cwd+GRAPHIFY_OUT=cacheDir enforced in lib."""
    return run_graphify_cmd(["update", str(repo)], timeout_seconds=timeout, cache_dir=cache_dir)


def _refuse_if_cache_inside_repo(verb: str) -> bool:
    """Print + return True when cache resolves inside the repo (advisory refusal, AC13)."""
    if is_cache_root_inside_repo(_PROJECT_DIR):
        print(f"graphify-maintain {verb}: cache_root_inside_repo "
              f"({get_cache_dir(_PROJECT_DIR)}) — refusing to run graphify (advisory)", flush=True)
        return True
    return False


def cmd_init() -> int:
    """Cold-start full build — run manually by the user, never auto-triggered (AC1b)."""
    if not is_graphify_enabled():
        print("graphify-maintain: CLAUDE_GRAPHIFY_ENABLED=0 — skipping init", flush=True)
        return 0
    bin_path = get_graphify_bin()
    if not bin_path:
        print("graphify-maintain: GRAPHIFY_BIN absent — cannot init (advisory)", flush=True)
        return 0
    if _refuse_if_cache_inside_repo("init"):
        return 0

    cache_dir = get_cache_dir(_PROJECT_DIR)
    repo_key = get_repo_key(_PROJECT_DIR)
    print(f"graphify-maintain init: building graph for repo_key={repo_key}", flush=True)
    print(f"  cache_dir: {cache_dir}", flush=True)
    print(f"  timeout: {TIMEOUT_INIT}s", flush=True)

    start = time.time()
    exit_code, stdout, stderr = _run_ast_build(_PROJECT_DIR, cache_dir, TIMEOUT_INIT)
    elapsed = time.time() - start

    if exit_code != 0:
        print(f"graphify-maintain init: AST build failed (exit={exit_code}) in {elapsed:.1f}s",
              file=sys.stderr, flush=True)
        if stderr:
            print(f"  stderr: {stderr[:500]}", file=sys.stderr, flush=True)
        return 1

    graph, st = load_graph(graph_json_path(_PROJECT_DIR))
    ast_nodes = len(graph.get("nodes", []))
    print(f"graphify-maintain init: AST graph ok in {elapsed:.1f}s ({ast_nodes} nodes)", flush=True)

    # Semantic probe is additive best-effort; AST graph already on disk (M6/AC6).
    semantic_mode, probe_reason = _probe_semantic(_PROJECT_DIR, cache_dir, ast_nodes)
    print(f"graphify-maintain init: semantic_mode={semantic_mode} ({probe_reason})", flush=True)

    _write_run_manifest(cache_dir, repo_key, bin_path, semantic_mode, probe_reason, verb="init")
    return 0


def cmd_update() -> int:
    """Incremental refresh — non-blocking advisory; called from /pull and /dev Step 7.5."""
    if not is_graphify_enabled():
        print("graphify-maintain: CLAUDE_GRAPHIFY_ENABLED=0 — skipping update", flush=True)
        return 0
    bin_path = get_graphify_bin()
    if not bin_path:
        print("graphify-maintain update: GRAPHIFY_BIN absent — advisory no-op", flush=True)
        return 0
    if _refuse_if_cache_inside_repo("update"):
        return 0

    cache_dir = get_cache_dir(_PROJECT_DIR)
    repo_key = get_repo_key(_PROJECT_DIR)
    print(f"graphify-maintain update: incremental refresh for repo_key={repo_key}", flush=True)

    start = time.time()
    exit_code, stdout, stderr = _run_ast_build(_PROJECT_DIR, cache_dir, TIMEOUT_UPDATE)
    elapsed = time.time() - start

    if exit_code == 0:
        graph, _ = load_graph(graph_json_path(_PROJECT_DIR))
        print(f"graphify-maintain update: ok in {elapsed:.1f}s "
              f"({len(graph.get('nodes', []))} nodes)", flush=True)
        _write_run_manifest(cache_dir, repo_key, bin_path, None, "incremental update", verb="update")
        return 0
    print(f"graphify-maintain update: failed (exit={exit_code}) in {elapsed:.1f}s — advisory, continuing",
          file=sys.stderr, flush=True)
    return 0  # advisory: always exit 0 so callers are not blocked


def cmd_status() -> int:
    """Show real cache state, node/edge counts, and semantic mode (S1)."""
    available, reason = check_cache_available(project_dir=_PROJECT_DIR)
    repo_key = get_repo_key(_PROJECT_DIR)
    cache_dir = get_cache_dir(_PROJECT_DIR)
    gpath = graph_json_path(_PROJECT_DIR)

    print("graphify-maintain status:")
    print(f"  enabled: {is_graphify_enabled()}")
    print(f"  binary: {get_graphify_bin() or 'absent'}")
    print(f"  cache_dir: {cache_dir}")
    print(f"  repo_key: {repo_key}")
    print(f"  cache_root_inside_repo: {is_cache_root_inside_repo(_PROJECT_DIR)}")
    print(f"  graph_json: {gpath} ({'present' if gpath.exists() else 'absent'})")
    print(f"  cache_available: {available}")
    if not available:
        print(f"  unavailable_reason: {reason}")

    if gpath.exists():
        graph, st = load_graph(gpath)
        print(f"  status: {STATUS_OK if available else st}")
        print(f"  nodes: {len(graph.get('nodes', []))}")
        print(f"  links: {len(graph.get('links', []))}")

    run_manifest = cache_dir / "run-manifest.json"
    if run_manifest.exists():
        try:
            rm = json.loads(run_manifest.read_text(encoding="utf-8"))
            print(f"  semantic_mode: {rm.get('semantic_mode', 'unknown')}")
            print(f"  semantic_backend_probe: {rm.get('semantic_backend_probe', 'n/a')}")
        except Exception:
            pass
    return 0


def _write_run_manifest(cache_dir: Path, repo_key: str, bin_path: str,
                        semantic_mode: str | None, probe_reason: str, verb: str) -> None:
    """Persist a small run-manifest.json inside the cache (NOT in the repo)."""
    path = cache_dir / "run-manifest.json"
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data.update({
        "repo_key": repo_key,
        "branch": _get_git_branch(),
        "head_sha": _get_git_head(),
        "graphify_version": _get_graphify_version(bin_path),
        f"{verb}_at": _now_iso(),
    })
    if semantic_mode is not None:
        data["semantic_mode"] = semantic_mode
        data["semantic_backend_probe"] = probe_reason
    write_json_locked(path, data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_git_branch() -> str:
    try:
        import subprocess as _sp
        r = _sp.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True, text=True, cwd=str(_PROJECT_DIR))
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _get_git_head() -> str:
    try:
        import subprocess as _sp
        r = _sp.run(["git", "rev-parse", "HEAD"],
                    capture_output=True, text=True, cwd=str(_PROJECT_DIR))
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _get_graphify_version(bin_path: str) -> str:
    try:
        import subprocess as _sp
        r = _sp.run([bin_path, "--version"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    subcmd = sys.argv[1]
    if subcmd == "init":
        sys.exit(cmd_init())
    elif subcmd == "update":
        sys.exit(cmd_update())
    elif subcmd == "status":
        sys.exit(cmd_status())
    else:
        print(f"Unknown subcommand: {subcmd!r}. Use init, update, or status.", file=sys.stderr)
        sys.exit(2)
