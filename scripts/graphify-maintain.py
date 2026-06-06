#!/usr/bin/env python3
"""
graphify-maintain.py — Global Graphify cache lifecycle manager (REAL CLI).

Drives the real `graphify` v0.8.25 CLI. The per-repo cache lives OUTSIDE the
repo (default /var/tmp/claude-graphify/<repo_key>); every invocation runs with
cwd=cacheDir AND GRAPHIFY_OUT=cacheDir so all byproducts (graph.json, report,
html, cache/, and the cwd-relative graphify-out/manifest.json) land in the
cache and the source repo stays clean (AC4).

Usage:
  python3 scripts/graphify-maintain.py init               # cold-start full build (user-triggered, <=300s)
  python3 scripts/graphify-maintain.py update             # incremental refresh (advisory, <=60s)
  python3 scripts/graphify-maintain.py semantic [--timeout SECONDS]  # user-triggered semantic extract (<=3600s)
  python3 scripts/graphify-maintain.py ensure-async       # non-blocking auto-init: launch a background full build if no cached graph exists (used by /dev pre-BA hydrator, between Step 1 and Step 2)
  python3 scripts/graphify-maintain.py status             # show real cache state + semantic mode

init / update both run real `graphify update <repo>` (AST-only) and stay fast;
they NEVER auto-probe semantic extraction. Semantic enrichment is user-triggered
via the explicit `semantic` subcommand, which runs `graphify extract`, applies an
edge-signature set-diff proof-gate over valid confidences, and promotes the
semantic graph only when it adds NEW edges. AST is produced FIRST and never lost
to a semantic failure (M6). NO fictional --init/--update/--output-dir flags.

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

# Locate project root from env (set by Claude harness). _PROJECT_DIR is the
# SUBJECT repo (what gets graphed); the tool's own libs live next to this script,
# resolved via __file__ so a single global install (~/.claude) serves any repo.
_PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

from graphify_lib import (
    STATUS_OK, STATUS_FAILED, STATUS_UNAVAILABLE, STATUS_SKIPPED,
    TIMEOUT_UPDATE, TIMEOUT_INIT, TIMEOUT_SEMANTIC_PROBE, TIMEOUT_SEMANTIC,
    check_cache_available, get_cache_dir, get_graphify_bin, get_repo_key,
    graph_json_path, is_cache_root_inside_repo, is_graphify_enabled,
    load_graph, run_graphify_cmd, write_json_locked,
    reset_semantic_mode_in_manifest,
)

# Edge-signature confidence whitelist for the semantic proof-gate (verdict P, codex round-2).
VALID_CONFIDENCES = {"EXTRACTED", "INFERRED", "AMBIGUOUS"}


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


def _canonicalize(value) -> object:
    """Canonicalize a link field so a 7-tuple signature stays hashable (codex #5).

    Scalars pass through; non-scalar (list/dict) values are JSON-serialized with
    sorted keys so two structurally-equal `context` values compare equal.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except Exception:
        return str(value)


def _link_signature(link: dict) -> tuple:
    """Full 7-tuple edge signature: (source,target,relation,confidence,source_file,source_location,context).

    `context` is present on only some links; link.get('context') defaults to None
    so two links that both OMIT context compare EQUAL, and two links differing ONLY
    in context compare DISTINCT (codex #5).
    """
    return (
        _canonicalize(link.get("source")),
        _canonicalize(link.get("target")),
        _canonicalize(link.get("relation")),
        _canonicalize(link.get("confidence")),
        _canonicalize(link.get("source_file")),
        _canonicalize(link.get("source_location")),
        _canonicalize(link.get("context")),
    )


def compute_added_semantic_edges(ast_graph: dict, sem_graph: dict) -> list:
    """Return the list of sem links whose FULL signature is absent from the AST
    link set AND whose confidence is in VALID_CONFIDENCES (verdict P, codex round-2).

    BOTH graphs MUST already be normalized through graphify_lib.load_graph so the
    set-diff never compares a scrubbed graph against a raw one (codex #4). The
    live AST graph ALREADY carries EXTRACTED/INFERRED confidences, so confidence
    PRESENCE is not a discriminator — only NEW edges by full signature count.
    """
    ast_sigs = {_link_signature(l) for l in ast_graph.get("links", []) if isinstance(l, dict)}
    added = []
    seen = set()
    for l in sem_graph.get("links", []):
        if not isinstance(l, dict):
            continue
        if l.get("confidence") not in VALID_CONFIDENCES:
            continue
        sig = _link_signature(l)
        if sig in ast_sigs or sig in seen:
            continue
        seen.add(sig)
        added.append(l)
    return added


def _semantic_promotable(ast_graph: dict, sem_graph: dict) -> tuple[bool, dict]:
    """Apply the corrected proof-gate. Returns (promotable, counts).

    semantic_ok = len(sem_nodes)>=len(ast_nodes) AND len(sem_links)>=len(ast_links)
                  AND bool(added_semantic_edges by full-signature set-diff over valid confidences).
    (The status==ok precondition is applied by the caller against load_graph's status.)
    """
    ast_nodes = len(ast_graph.get("nodes", []))
    sem_nodes = len(sem_graph.get("nodes", []))
    ast_links = len(ast_graph.get("links", []))
    sem_links = len(sem_graph.get("links", []))
    added = compute_added_semantic_edges(ast_graph, sem_graph)
    added_valid_inferred = sum(
        1 for l in added if l.get("confidence") in ("INFERRED", "AMBIGUOUS"))
    counts = {
        "ast_nodes": ast_nodes, "sem_nodes": sem_nodes,
        "ast_links": ast_links, "sem_links": sem_links,
        "added_links": len(added),
        "added_inferred_or_ambiguous": added_valid_inferred,
    }
    promotable = (
        sem_nodes >= ast_nodes
        and sem_links >= ast_links
        and bool(added)
    )
    return promotable, counts


def _not_promoted_reason(label: str, counts: dict) -> str:
    """Build an ACCURATE, non-contradictory reason for a NOT-promoted semantic run.

    The reason names the FIRST gate clause that actually failed and always reports
    the real node/link counts. It must NEVER say "added no new edges" when
    added_links>0 (that case is a monotonicity failure, not a no-new-edges failure).
    Clause order mirrors _semantic_promotable: node-monotonicity, then
    link-monotonicity, then the no-new-signature-edges case.
    """
    an, sn = counts["ast_nodes"], counts["sem_nodes"]
    al, sl = counts["ast_links"], counts["sem_links"]
    added = counts["added_links"]
    base = (f"semantic extract via {label} added {added} candidate edge(s) by signature set-diff "
            f"(ast_nodes={an}, sem_nodes={sn}, ast_links={al}, sem_links={sl})")
    if sn < an:
        return (f"{base} but not promoted: semantic node count {sn} < AST node count {an} "
                f"(node-monotonicity guard)")
    if sl < al:
        return (f"{base} but not promoted: semantic link count {sl} < AST link count {al} "
                f"(link-monotonicity guard)")
    # monotonicity satisfied -> the blocker is genuinely zero new signature edges
    return (f"semantic extract via {label} added no new edges by signature set-diff "
            f"(ast_nodes={an}, sem_nodes={sn}, ast_links={al}, sem_links={sl})")


def _run_ast_build(repo: Path, cache_dir: Path, timeout: int) -> tuple[int, str, str]:
    """Run real `graphify update <repo>` (AST). cwd+GRAPHIFY_OUT=cacheDir enforced in lib."""
    return run_graphify_cmd(["update", str(repo)], timeout_seconds=timeout, cache_dir=cache_dir)


def _graph_snapshot(path: Path) -> str | None:
    """Return a content-hash snapshot of graph.json, or None if absent.

    Used to PROVE whether a failed/timed-out AST update mutated the canonical
    graph (codex iter #3). A content hash (not mtime alone) is authoritative.
    """
    import hashlib
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _current_semantic_mode(cache_dir: Path) -> str | None:
    """Return the semantic_mode currently persisted in run-manifest.json, or None.

    Used to decide whether a failed-but-unchanged baseline must PROTECT a still-valid
    prior 'semantic:<backend>' promotion (codex finding #2 / AC10 branch iii).
    """
    path = Path(cache_dir) / "run-manifest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("semantic_mode")
    except Exception:
        return None


def _reconcile_after_ast_overwrite(cache_dir: Path, exit_code: int,
                                   pre_snapshot: str | None) -> str:
    """Three-branch semantic-state reconciliation after an AST `update` (AC10/AC11).

    (i)  success (exit_code == 0): graph.json overwritten -> RESET semantic_mode.
    (ii) failed/timed-out BUT graph.json mutated (pre != post): INVALIDATE -> RESET.
    (iii)failed/timed-out AND graph.json proven unchanged: leave manifest UNTOUCHED.

    Advisory: any error is swallowed. Returns a short reason string for logging.
    The reset uses the SHARED graphify_lib.reset_semantic_mode_in_manifest helper
    and is called AFTER the graph overwrite (graph-then-manifest ordering).
    """
    post_snapshot = _graph_snapshot(graph_json_path(_PROJECT_DIR))
    mutated = (exit_code == 0) or (pre_snapshot != post_snapshot)
    if not mutated:
        return "graph.json proven unchanged; manifest untouched"
    try:
        reset_semantic_mode_in_manifest(cache_dir)
    except Exception as exc:  # advisory — never break the caller
        return f"reconcile error (swallowed): {exc}"
    if exit_code == 0:
        return "AST overwrite reset semantic_mode to ast_only"
    return "AST update mutated graph before failing; semantic state invalidated"


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

    # init is AST-only and fast: NO auto semantic probe (the unreachable 30s init
    # probe is removed). Semantic enrichment is user-triggered via the `semantic`
    # subcommand. Report ast_only with an explicit user-triggered/retained reason
    # so existing AC6 (mode=='ast_only', 'retained' in reason) holds (Option b).
    semantic_mode = "ast_only"
    probe_reason = "semantic is user-triggered (run `graphify-maintain.py semantic`); AST retained"
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

    # Capture a pre-update snapshot so we can prove whether a failed/timed-out
    # update still mutated graph.json (codex iter #3 / AC10 three-branch reset).
    pre_snapshot = _graph_snapshot(graph_json_path(_PROJECT_DIR))

    start = time.time()
    exit_code, stdout, stderr = _run_ast_build(_PROJECT_DIR, cache_dir, TIMEOUT_UPDATE)
    elapsed = time.time() - start

    # Graph-then-manifest ordering: the graph (if any) is already on disk now;
    # reconcile maintain's stale semantic_mode AFTER it (codex iter #2).
    reconcile_reason = _reconcile_after_ast_overwrite(cache_dir, exit_code, pre_snapshot)

    if exit_code == 0:
        graph, _ = load_graph(graph_json_path(_PROJECT_DIR))
        print(f"graphify-maintain update: ok in {elapsed:.1f}s "
              f"({len(graph.get('nodes', []))} nodes); {reconcile_reason}", flush=True)
        _write_run_manifest(cache_dir, repo_key, bin_path, None, "incremental update", verb="update")
        return 0
    print(f"graphify-maintain update: failed (exit={exit_code}) in {elapsed:.1f}s — advisory, continuing "
          f"({reconcile_reason})", file=sys.stderr, flush=True)
    return 0  # advisory: always exit 0 so callers are not blocked


def _select_semantic_backend() -> tuple[str, str | None, str]:
    """Resolve the 4-case backend matrix (OBJ-3 / AC13-OBJ3).

    Mirrors _detect_semantic_backend's precedence: forced -> key -> claude -> none.
    Returns (kind, backend_flag, label) where:
      kind == "forced"  -> pass --backend <flag>, label "semantic:<flag>"
      kind == "keyed"   -> NO --backend arg (graphify auto-detects), label "semantic:auto"
      kind == "claude"  -> pass --backend claude-cli, label "semantic:claude-cli"
      kind == "none"    -> no usable backend; caller must NOT invoke extract
    backend_flag is None for the keyed and none cases. The literal token 'None'
    is NEVER produced as a flag and 'semantic:None' is NEVER a label.
    """
    forced = os.environ.get("GRAPHIFY_TRIAGE_BACKEND", "").strip()
    if forced:
        # Degenerate forced value -> treat as no usable backend (never --backend None).
        if forced.lower() in ("none", "null", ""):
            return "none", None, ""
        return "forced", forced, f"semantic:{forced}"
    for env_key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "MOONSHOT_API_KEY",
                    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        if os.environ.get(env_key):
            # Keyed: let graphify auto-detect; do NOT pass --backend (codex #6).
            return "keyed", None, "semantic:auto"
    import shutil
    if shutil.which("claude"):
        return "claude", "claude-cli", "semantic:claude-cli"
    return "none", None, ""


def cmd_semantic(timeout_seconds: int = TIMEOUT_SEMANTIC) -> int:
    """User-triggered semantic extraction with the corrected proof-gate (R2/AC3/AC4/AC9/AC12/AC13).

    Flow: gate/bin/cache-inside-repo guards -> AST baseline `update` (fresh
    baseline, codex #2) -> resolve 4-case backend -> clear-before-extract
    (MANDATORY, AC12) -> `graphify extract` -> same-normalize both sides via
    load_graph -> apply the set-diff gate -> promote IFF a fresh parseable
    extract output adds NEW valid-confidence edges. AST is never lost. Advisory
    exit 0 on every no-promote branch.
    """
    if not is_graphify_enabled():
        print("graphify-maintain: CLAUDE_GRAPHIFY_ENABLED=0 — skipping semantic", flush=True)
        return 0
    bin_path = get_graphify_bin()
    if not bin_path:
        print("graphify-maintain semantic: GRAPHIFY_BIN absent — advisory no-op", flush=True)
        return 0
    if _refuse_if_cache_inside_repo("semantic"):
        return 0

    cache_dir = get_cache_dir(_PROJECT_DIR)
    repo_key = get_repo_key(_PROJECT_DIR)
    gpath = graph_json_path(_PROJECT_DIR)
    print(f"graphify-maintain semantic: repo_key={repo_key}, timeout={timeout_seconds}s", flush=True)

    # 1) Fresh AST baseline FIRST (codex #2). Never diff extract output against a
    #    stale/garbage baseline. Capture a pre-update snapshot for the iter #3 guard.
    #    The baseline is a FULL-REPO `graphify update` (not an incremental Step-7.5
    #    refresh), so it MUST use the full-repo init budget (TIMEOUT_INIT), not the
    #    60s incremental TIMEOUT_UPDATE: a cold/full AST pass on a large repo takes
    #    ~77s+ and would otherwise always time out (exit=-1), permanently skipping
    #    extract and making the user-triggered semantic command non-functional.
    pre_snapshot = _graph_snapshot(gpath)
    up_exit, _, up_err = _run_ast_build(_PROJECT_DIR, cache_dir, TIMEOUT_INIT)

    # Three-branch reconciliation on the baseline update (AC10/AC12 branch iii,
    # codex iter #3): only INVALIDATE the stale semantic state when the failed
    # update actually MUTATED graph.json. A failed update that left graph.json
    # PROVEN UNCHANGED must leave the manifest UNTOUCHED — otherwise a prior manual
    # semantic promotion is wrongly turned off even though the graph didn't change.
    baseline_mutated = False
    if up_exit != 0:
        post_snapshot = _graph_snapshot(gpath)
        baseline_mutated = (pre_snapshot != post_snapshot)
        if baseline_mutated:
            try:
                reset_semantic_mode_in_manifest(cache_dir)
            except Exception:
                pass
    ast_graph, ast_st = load_graph(gpath)
    if up_exit != 0 or ast_st != STATUS_OK or len(ast_graph.get("nodes", [])) == 0:
        reason = f"no fresh AST baseline (update exit={up_exit}, status={ast_st}); extract skipped, AST retained"
        print(f"graphify-maintain semantic: {reason}", flush=True)
        # Branch iii (codex finding #2): a FAILED baseline update that left graph.json
        # PROVEN UNCHANGED must NOT clobber a still-valid prior 'semantic:<backend>'
        # promotion — the on-disk graph is unchanged, so the persisted mode is still
        # honest. Leave the manifest UNTOUCHED only in that exact case. In every
        # other no-baseline case (success-but-empty graph, or a failed update that
        # mutated the graph, or no prior semantic promotion to protect) write the
        # ast_only+reason manifest so status reports honestly.
        prior_mode = _current_semantic_mode(cache_dir)
        protect_prior = (up_exit != 0 and not baseline_mutated
                         and str(prior_mode).startswith("semantic:"))
        if not protect_prior:
            _write_run_manifest(cache_dir, repo_key, bin_path, "ast_only", reason, verb="semantic")
        return 0

    # 2) Resolve backend (4-case matrix). No usable backend -> clean fail, no extract.
    kind, backend_flag, label = _select_semantic_backend()
    if kind == "none":
        reason = "no semantic backend reachable (no API key, claude CLI absent, no usable forced backend); AST retained"
        print(f"graphify-maintain semantic: {reason}", flush=True)
        _write_run_manifest(cache_dir, repo_key, bin_path, "ast_only", reason, verb="semantic")
        return 0

    # 3) clear-before-extract (MANDATORY, AC12): remove any stale prior extract
    #    output INSIDE the cache so a failed/timed-out current run cannot promote it.
    extracted = cache_dir / "graphify-out" / "graph.json"
    try:
        if extracted.exists() or extracted.is_symlink():
            extracted.unlink()
    except Exception as exc:
        print(f"graphify-maintain semantic: could not clear stale extract output: {exc}", flush=True)
    # ENFORCE the clear (AC12): if the stale file still exists, a current extract
    # that exits 0 without replacing it could promote the STALE prior graph. Refuse
    # to run extract and RETAIN AST rather than risk promoting an unproven graph.
    if extracted.exists() or extracted.is_symlink():
        reason = f"could not clear stale extract output at {extracted}; extract skipped, AST retained"
        print(f"graphify-maintain semantic: {reason}", flush=True)
        _write_run_manifest(cache_dir, repo_key, bin_path, "ast_only", reason, verb="semantic")
        return 0

    # 4) Build + run extract. Never put the literal 'None' in argv.
    args = ["extract", str(_PROJECT_DIR), "--out", str(cache_dir)]
    if backend_flag is not None:
        args += ["--backend", backend_flag]
    start = time.time()
    ex_exit, _, ex_err = run_graphify_cmd(args, timeout_seconds=timeout_seconds, cache_dir=cache_dir)
    elapsed = time.time() - start

    if ex_exit != 0:
        reason = f"extract via {label} failed/timed-out (exit={ex_exit}) in {elapsed:.1f}s; AST retained"
        print(f"graphify-maintain semantic: {reason}", flush=True)
        _write_run_manifest(cache_dir, repo_key, bin_path, "ast_only", reason, verb="semantic")
        return 0

    # 5) Require a FRESH parseable output at the exact cleared path (AC12).
    if not extracted.exists():
        reason = f"extract via {label} produced no graph.json at {extracted}; AST retained"
        print(f"graphify-maintain semantic: {reason}", flush=True)
        _write_run_manifest(cache_dir, repo_key, bin_path, "ast_only", reason, verb="semantic")
        return 0

    sem_graph, sem_st = load_graph(extracted)
    if sem_st != STATUS_OK:
        reason = f"extract via {label} output unparseable (status={sem_st}); AST retained"
        print(f"graphify-maintain semantic: {reason}", flush=True)
        _write_run_manifest(cache_dir, repo_key, bin_path, "ast_only", reason, verb="semantic")
        return 0

    # 6) Apply the corrected gate on same-normalized graphs (both via load_graph).
    promotable, counts = _semantic_promotable(ast_graph, sem_graph)
    if not promotable:
        reason = _not_promoted_reason(label, counts) + "; AST retained"
        print(f"graphify-maintain semantic: {reason}", flush=True)
        _write_run_manifest(cache_dir, repo_key, bin_path, "ast_only", reason, verb="semantic")
        return 0

    # 7) Promote: copy the raw extract output to canonical graph.json ATOMICALLY
    #    (same-dir temp + os.replace) so a partial/failed write can never corrupt
    #    or truncate the existing AST graph ("AST never lost", ticket edge-case).
    try:
        payload = extracted.read_text(encoding="utf-8")
        tmp = gpath.with_suffix(gpath.suffix + ".promote.tmp")
        try:
            tmp.write_text(payload, encoding="utf-8")
            os.replace(str(tmp), str(gpath))  # atomic on POSIX; never a partial file
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass
    except Exception as exc:
        reason = f"semantic graph promote failed: {exc}; AST retained"
        print(f"graphify-maintain semantic: {reason}", flush=True)
        _write_run_manifest(cache_dir, repo_key, bin_path, "ast_only", reason, verb="semantic")
        return 0

    reason = (f"semantic path added {counts['added_links']} new edge(s) "
              f"({counts['added_inferred_or_ambiguous']} INFERRED/AMBIGUOUS) via {label}")
    print(f"graphify-maintain semantic: PROMOTED — {reason}", flush=True)
    _write_run_manifest(cache_dir, repo_key, bin_path, label, reason, verb="semantic",
                        semantic_counts=counts)
    return 0


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
            mode = rm.get("semantic_mode", "unknown")
            print(f"  semantic_mode: {mode}")
            print(f"  semantic_backend_probe: {rm.get('semantic_backend_probe', 'n/a')}")
            # Surface added-link counts only when actually promoted (mirrors the
            # persisted run-manifest exactly — never claims semantic when ast_only).
            if str(mode).startswith("semantic:"):
                print(f"  semantic_added_links: {rm.get('semantic_added_links', 0)}")
                print(f"  semantic_added_inferred_or_ambiguous: "
                      f"{rm.get('semantic_added_inferred_or_ambiguous', 0)}")
        except Exception:
            pass
    return 0


def _write_run_manifest(cache_dir: Path, repo_key: str, bin_path: str,
                        semantic_mode: str | None, probe_reason: str, verb: str,
                        semantic_counts: dict | None = None) -> None:
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
        # Surface added-link counts on a promotion; clear them otherwise so a
        # later ast_only never carries stale counts (AC6 cross-check with AC10).
        if semantic_counts is not None and str(semantic_mode).startswith("semantic:"):
            data["semantic_added_links"] = semantic_counts.get("added_links", 0)
            data["semantic_added_inferred_or_ambiguous"] = semantic_counts.get(
                "added_inferred_or_ambiguous", 0)
        else:
            for key in ("semantic_added_links", "semantic_added_inferred_or_ambiguous",
                        "semantic_added_edge_count"):
                data.pop(key, None)
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


def cmd_ensure_async() -> int:
    """Non-blocking auto-init for the /dev workflow.

    If no usable cached graph exists, launch a DETACHED background full `init`
    build so the graph is ready for the NEXT /dev run, then return IMMEDIATELY.
    This NEVER blocks /dev (R-7: a full build is ~77s-minutes and must not stall
    the pipeline). Strictly advisory: any error/condition yields a clean exit 0.

    Concurrency- and re-hammer-safe via a staleness-bounded lock
    (`<cacheDir>/.autoinit.lock`): at most one background build per
    TIMEOUT_INIT+buffer window, even across parallel /dev sessions. Once the
    build finishes, the graph-present short-circuit (step 1) makes every
    subsequent call a no-op, so the lock needs no explicit cleanup.
    """
    try:
        if not is_graphify_enabled():
            print("graphify-maintain ensure-async: disabled (CLAUDE_GRAPHIFY_ENABLED=0) — no-op", flush=True)
            return 0
        if not get_graphify_bin():
            print("graphify-maintain ensure-async: GRAPHIFY_BIN absent — no-op", flush=True)
            return 0
        if _refuse_if_cache_inside_repo("ensure-async"):
            return 0

        cache_dir = get_cache_dir(_PROJECT_DIR)
        gpath = graph_json_path(_PROJECT_DIR)

        # 1) Graph already present + usable -> nothing to do (covers "build finished").
        graph, st = load_graph(gpath)
        if st == STATUS_OK and len(graph.get("nodes", [])) > 0:
            print("graphify-maintain ensure-async: cached graph present — no auto-init needed", flush=True)
            return 0

        # 2) Staleness-bounded lock: prevents duplicate/concurrent builds and
        #    re-hammering a failed build. Window = full-build budget + buffer.
        lock = cache_dir / ".autoinit.lock"
        window = TIMEOUT_INIT + 120
        try:
            if lock.exists() and (time.time() - lock.stat().st_mtime) < window:
                print("graphify-maintain ensure-async: background auto-init already in progress/backoff — no-op",
                      flush=True)
                return 0
        except OSError:
            pass

        # 3) Launch a DETACHED background `init`; return immediately (non-blocking).
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            lock.write_text(f'{{"launcher_pid": {os.getpid()}, "at": "{_now_iso()}"}}\n', encoding="utf-8")
        except OSError:
            pass
        import subprocess as _sp
        log_path = cache_dir / "autoinit.log"
        try:
            logf = open(log_path, "ab")
        except OSError:
            logf = _sp.DEVNULL
        proc = _sp.Popen(
            [sys.executable, str(_SCRIPT_DIR / "graphify-maintain.py"), "init"],
            stdout=logf, stderr=logf, stdin=_sp.DEVNULL,
            start_new_session=True,  # detach so it survives the /dev turn and never blocks
            cwd=str(_PROJECT_DIR), env=os.environ.copy(),
        )
        print(f"graphify-maintain ensure-async: no cached graph — launched background init "
              f"(pid={proc.pid}, log={log_path}); /dev proceeds NOW, graph ready next run", flush=True)
        return 0
    except Exception as exc:
        # Auto-init is strictly advisory — never block /dev on any failure.
        print(f"graphify-maintain ensure-async: advisory no-op ({exc})", file=sys.stderr, flush=True)
        return 0


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
    elif subcmd == "semantic":
        import argparse
        parser = argparse.ArgumentParser(prog="graphify-maintain.py semantic")
        parser.add_argument("--timeout", type=int, default=TIMEOUT_SEMANTIC,
                            help=f"extract timeout in seconds (default {TIMEOUT_SEMANTIC})")
        ns = parser.parse_args(sys.argv[2:])
        sys.exit(cmd_semantic(timeout_seconds=ns.timeout))
    elif subcmd == "status":
        sys.exit(cmd_status())
    elif subcmd == "ensure-async":
        sys.exit(cmd_ensure_async())
    else:
        print(f"Unknown subcommand: {subcmd!r}. Use init, update, semantic, ensure-async, or status.",
              file=sys.stderr)
        sys.exit(2)
