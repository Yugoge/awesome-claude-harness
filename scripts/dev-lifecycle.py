#!/usr/bin/env python3
"""Read-only lifecycle-state scanner for docs/dev/ tickets, specs, and lanes.

Derives, per on-disk task-id, a state (docs/dev/ticket-20260808-035658-lanel.md):

  BA-QA     -- only when no dev-report-<id>.json exists yet: the ba-qa-report's
               verdict
  do track  -- a do-report: its terminal status through the one decision
               (hooks/lib/obligation.terminal_status)
  dev chain -- a dev-report and no close-report: ONE call of the chain function
               (resolve-dev-artifact-chain.py resolve_chain), its result used
               verbatim; the --auto close discovery hands that same result to
               the walked task's own step, so the task's chain is called once
  close     -- a close-report exists: the one classifier's class of its last
               line (hooks/lib/close-verdict.py), then commit detection; the
               chain is not called

Never mutates docs/dev/, .git refs/index/worktree, or /tmp grant/sentinel
files.

Root-cause reference: docs/dev/ticket-20260808-035658-lanel.md and
docs/dev/acceptance-criteria-20260808-035658-lanel.json (AC-L1..AC-L22).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hooks.lib.obligation import terminal_status  # noqa: E402  (the one terminal decision)

# A docs/dev/ file names a task only when its id part passes the one task-id
# rule (hooks/lib/obligation.py).
from hooks.lib.obligation import TASK_ID_RE  # noqa: E402

_HOOK_DENY_RE = re.compile(
    r"(?:PreToolUse|PostToolUse|Stop):[^\n]*hook error:[^\n]*BLOCKED",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------
# Read-only reuse of sibling scripts (module exec, never their main()/CLI).
# --------------------------------------------------------------------------


def _scripts_dir() -> Path:
    return Path(__file__).resolve().parent


def _load_module(path: Path, name: str) -> ModuleType:
    module = ModuleType(name)
    module.__file__ = str(path)
    source = path.read_bytes()
    exec(compile(source, str(path), "exec"), module.__dict__)  # noqa: S102
    return module


_MODULE_CACHE: dict[str, ModuleType] = {}


def _cached_module(path: Path, name: str) -> ModuleType:
    key = str(path)
    cached = _MODULE_CACHE.get(key)
    if cached is not None:
        return cached
    module = _load_module(path, name)
    _MODULE_CACHE[key] = module
    return module


def _load_resolver_module() -> ModuleType:
    return _cached_module(_scripts_dir() / "resolve-dev-artifact-chain.py", "_dlc_resolver")


def _load_commit_repos_module() -> ModuleType:
    return _cached_module(_scripts_dir() / "resolve-commit-repos.py", "_dlc_commit_repos")


def _load_close_verdict_module() -> ModuleType:
    return _cached_module(_scripts_dir().parent / "hooks" / "lib" / "close-verdict.py", "_dlc_close_verdict")


# --------------------------------------------------------------------------
# Small read-only file helpers
# --------------------------------------------------------------------------


def _read_json(path: Path) -> Optional[dict]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


# --------------------------------------------------------------------------
# BA-QA-awareness (Must-Have #0, objection 6/9)
# --------------------------------------------------------------------------


def ba_qa_verdict(doc: dict) -> Optional[str]:
    """doc.get('verdict') or doc.get('qa', {}).get('status') -- top-level first.

    Both shapes exist on this branch today (schema drift, objection 9):
    ba-qa-report-20260808-035658-lanel.json carries a top-level `verdict`;
    ba-qa-report-20260808-035658-lanepolcatchup.json does not.
    """
    top = doc.get("verdict")
    if isinstance(top, str) and top:
        return top
    qa = doc.get("qa")
    if isinstance(qa, dict):
        nested = qa.get("status")
        if isinstance(nested, str) and nested:
            return nested
    return None


# --------------------------------------------------------------------------
# do-report lite preflight (mirrors commands/close.md:157-162,224-233)
# --------------------------------------------------------------------------


def do_report_lite_preflight(doc: dict) -> Optional[str]:
    """Return None when the do-report shape is valid; else the offending field."""
    if doc.get("source") != "do":
        return "source"
    do = doc.get("do")
    if not isinstance(do, dict):
        return "do"
    if terminal_status("do-report.v1", doc) != "completed":
        return "do.status"
    files_modified = do.get("files_modified")
    if not isinstance(files_modified, list):
        return "do.files_modified"
    return None


# --------------------------------------------------------------------------
# dev chain -- one call of the chain function, its result used verbatim
# --------------------------------------------------------------------------


def chain_state(task_id: str, result: dict) -> dict:
    """The row a dev-chain task takes from its one chain call.

    The chain's own verdict decides (its `exit_status`); its result is carried
    whole (`artifact_chain`), and a fan-out's lanes are the ones it lists.
    """
    row: dict[str, Any] = {
        "invoke_resolver": True,
        "artifact_chain": result,
        "lanes": [
            {"task_id": lane["task_id"], "kind": "lane", "next_action": "none", "parent_task_id": task_id}
            for lane in result["lanes"]
        ],
    }
    if _load_resolver_module().exit_status(result) == 0:
        row.update(state="close_pending", next_action="close")
    else:
        row.update(state="blocked", next_action="inspect", blocker="RESOLVER_FAIL")
    return row


# --------------------------------------------------------------------------
# close-report verdict + sound commit detection (objections 4, 5)
# --------------------------------------------------------------------------


def _head_reachable_trailer(repo_root: Path, trailer_line: str) -> bool:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "log", "HEAD", "--format=%B"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    return any(line.strip() == trailer_line for line in proc.stdout.splitlines())


def _porcelain_dirty(repo_root: Path, owned_paths: list[str]) -> bool:
    if not owned_paths:
        return False
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain", "--", *owned_paths],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return True  # fail closed: unknown state is treated as dirty
    if proc.returncode != 0:
        return True
    return bool(proc.stdout.strip())


def _combine_commit_repo_statuses(per_repo: list[str]) -> dict:
    """Pure combination step (AC-L13's case a/b/c), split out for direct testing
    without requiring a multi-repository git fixture per call site.

    case (a) every repo "committed" -> committed
    case (b) every repo "no_evidence" -> commit_pending, commit_evidence=unknown
    case (c) anything else (mixed, or any "mismatch") -> blocked/PARTIAL_COMMIT
             -- a trailer match with dirty owned content NEVER counts as
             committed (objection 5's negative fixture).
    """
    if per_repo and all(status == "committed" for status in per_repo):
        return {"state": "committed", "next_action": "none"}
    if per_repo and all(status == "no_evidence" for status in per_repo):
        return {"state": "commit_pending", "next_action": "commit", "commit_evidence": "unknown"}
    return {"state": "blocked", "next_action": "inspect", "blocker": "PARTIAL_COMMIT"}


def commit_detection(
    project_root: Path,
    task_id: str,
    report_path: Path,
    commit_repos_mod: ModuleType,
) -> dict:
    """Sound, per-repository, HEAD-reachable commit-detection (objection 5).

    Never `git log --all` (that is not sound proof of committed -- it would
    match foreign branches). Repository ownership comes from
    resolve-commit-repos.py's build_plan(), read-only reuse, never a
    hand-rolled path-ownership guess.
    """
    try:
        plan = commit_repos_mod.build_plan(
            task_id=task_id,
            control_root_arg=str(project_root),
            supported_repo_args=[],
            report_arg=str(report_path),
            # Read-only historical-status reuse predates the owned_edits
            # ownership ledger and reports on already-landed tasks; a
            # majority of already-committed dev-reports have a legitimate
            # files_modified/owned_edits gap (ticket 20260922-215750,
            # Root-Cause #6: 59.2% of Sept-2026 reports alone). Do NOT
            # restore the build_plan() default here -- that would misreport
            # most historical tasks as "blocked".
            verify_ownership=False,
        )
    except commit_repos_mod.PlanError as exc:
        return {"state": "blocked", "next_action": "inspect", "blocker": f"REPO_PLAN_ERROR:{exc}"}

    trailer_line = f"Task-id: {task_id}"
    per_repo: list[str] = []
    for repo in plan["repositories"]:
        root = Path(repo["repo_root"])
        owned = repo["owned_paths"]
        has_trailer = _head_reachable_trailer(root, trailer_line)
        dirty = _porcelain_dirty(root, owned)
        if has_trailer and not dirty:
            per_repo.append("committed")
        elif not has_trailer and not dirty:
            per_repo.append("no_evidence")
        else:
            # trailer present but dirty owned content -- NEVER a false
            # `committed`; also covers "trailer absent but dirty" as a
            # genuine partial/ambiguous state.
            per_repo.append("mismatch")

    return _combine_commit_repo_statuses(per_repo)


def close_and_commit(
    project_root: Path,
    task_id: str,
    close_report_path: Path,
    report_path: Path,
    close_verdict_mod: ModuleType,
    commit_repos_mod: ModuleType,
) -> dict:
    text = _read_text(close_report_path)
    if text is None:
        return {"state": "blocked", "next_action": "inspect", "blocker": "UNREADABLE_CLOSE_REPORT"}
    verdict = close_verdict_mod.classify_line(close_verdict_mod.last_nonempty(text))
    if verdict in ("no", "unknown"):
        return {"state": "close_failed", "next_action": "resume_close"}
    return commit_detection(project_root, task_id, report_path, commit_repos_mod)


# --------------------------------------------------------------------------
# Top-level derivation
# --------------------------------------------------------------------------


def derive_state(project_root: Path, task_id: str) -> dict:
    """Derive one task-id's lifecycle row.

    Precedence resolution (dev implementation decision, documented in the dev
    report): the ba-qa-report check and the do-report branch are both
    reached only when no canonical dev-report exists; between them, a
    ba-qa-report's PRESENCE takes precedence over a do-report's presence,
    because a ba-qa-report is direct evidence of an in-progress /dev-track
    attempt for this id. A do-report is a deliberate /do-track substitute for
    the ENTIRE dev-chain (BA-QA included by design -- commands/close.md's
    do-report lite preflight applies no ticket/context/QA checks), so it is
    consulted only when no ba-qa-report exists either. This keeps AC-L1/L2/L3
    (ba-qa-report-driven) and AC-L9/L10 (do-report-driven, real corpus has no
    ba-qa-report for that id) both satisfied without contradiction.
    """
    project_root = Path(project_root)
    dev_dir = project_root / "docs" / "dev"
    row: dict[str, Any] = {
        "task_id": task_id,
        "kind": "ticket",
        "parent_task_id": None,
        "parent_spec_id": None,
        "source_path": None,
        "lanes": [],
    }

    try:
        dev_report_path = dev_dir / f"dev-report-{task_id}.json"
        ba_qa_path = dev_dir / f"ba-qa-report-{task_id}.json"
        do_report_path = dev_dir / f"do-report-{task_id}.json"

        if dev_report_path.is_file():
            close_report_path = dev_dir / f"close-report-{task_id}.md"
            if close_report_path.is_file():
                row.update(invoke_resolver=False)
                row.update(close_and_commit(
                    project_root, task_id, close_report_path, dev_report_path,
                    _load_close_verdict_module(), _load_commit_repos_module(),
                ))
                return row
            row.update(chain_state(task_id, _load_resolver_module().resolve_chain(project_root, task_id)))
            return row

        if ba_qa_path.is_file():
            doc = _read_json(ba_qa_path)
            if doc is None:
                row.update(state="blocked", next_action="inspect", invoke_resolver=False, blocker="MALFORMED_BA_QA_REPORT")
                return row
            verdict = ba_qa_verdict(doc)
            if verdict == "pass":
                row.update(state="ba_approved", next_action="develop", invoke_resolver=False)
            elif verdict == "fail":
                row.update(state="ba_rejected", next_action="resume_ba", invoke_resolver=False)
            else:
                row.update(state="blocked", next_action="inspect", invoke_resolver=False, blocker="UNREADABLE_BA_QA_VERDICT")
            return row

        if do_report_path.is_file():
            do_doc = _read_json(do_report_path)
            if do_doc is None:
                row.update(state="blocked", next_action="inspect", invoke_resolver=False, blocker="MALFORMED_DO_REPORT")
                return row
            malformed_field = do_report_lite_preflight(do_doc)
            if malformed_field is not None:
                row.update(
                    state="blocked", next_action="inspect", invoke_resolver=False,
                    blocker=f"MALFORMED_DO_REPORT_FIELD:{malformed_field}",
                )
                return row
            close_report_path = dev_dir / f"close-report-{task_id}.md"
            if close_report_path.is_file():
                row.update(invoke_resolver=False)
                row.update(close_and_commit(
                    project_root, task_id, close_report_path, do_report_path,
                    _load_close_verdict_module(), _load_commit_repos_module(),
                ))
                return row
            row.update(state="close_pending", next_action="close", invoke_resolver=False, chain_origin="do_report")
            return row

        row.update(state="analyzed", next_action="develop", invoke_resolver=False)
        return row
    except Exception as exc:  # fail-closed: the scan must never crash (AC-L14)
        row.update(state="blocked", next_action="inspect", invoke_resolver=None, blocker=f"SCAN_EXCEPTION:{exc}")
        return row


# --------------------------------------------------------------------------
# Discovery + row taxonomy (spec rows, parent/lane grouping)
# --------------------------------------------------------------------------


def discover_task_ids(dev_dir: Path) -> dict[str, Any]:
    tickets: set[str] = set()
    if dev_dir.is_dir():
        for pattern, prefix, suffix in (
            ("ticket-*.md", "ticket-", ".md"),
            ("ba-spec-*.md", "ba-spec-", ".md"),
            ("do-report-*.json", "do-report-", ".json"),
            ("dev-report-*.json", "dev-report-", ".json"),
        ):
            for path in dev_dir.glob(pattern):
                candidate = path.name[len(prefix) : -len(suffix)]
                if TASK_ID_RE.fullmatch(candidate):
                    tickets.add(candidate)
    specs = sorted(str(p) for p in dev_dir.glob("specs/spec-*.md")) if dev_dir.is_dir() else []
    context_spec_links: dict[str, str] = {}
    for tid in tickets:
        ctx_path = dev_dir / f"context-{tid}.json"
        if ctx_path.is_file():
            doc = _read_json(ctx_path)
            if isinstance(doc, dict):
                spec_path = doc.get("spec_path")
                if isinstance(spec_path, str) and spec_path:
                    context_spec_links[tid] = spec_path
    return {"tickets": sorted(tickets), "specs": specs, "context_spec_links": context_spec_links}


def scan(project_root: Path) -> list[dict]:
    project_root = Path(project_root)
    dev_dir = project_root / "docs" / "dev"
    discovered = discover_task_ids(dev_dir)

    rows: list[dict] = []
    lane_owner: dict[str, str] = {}
    for tid in discovered["tickets"]:
        row = derive_state(project_root, tid)
        rows.append(row)
        for lane in row.get("lanes", []):
            lane_owner[lane["task_id"]] = tid

    by_id = {r["task_id"]: r for r in rows}
    for lane_tid, parent_tid in lane_owner.items():
        target = by_id.get(lane_tid)
        if target is not None:
            target["kind"] = "lane"
            target["parent_task_id"] = parent_tid
            target["next_action"] = "none"

    for tid, spec_path in discovered["context_spec_links"].items():
        if tid in by_id:
            by_id[tid]["parent_spec_id"] = spec_path

    linked_specs = set(discovered["context_spec_links"].values())
    for spec_path in discovered["specs"]:
        if spec_path not in linked_specs:
            rows.append(
                {
                    "task_id": None,
                    "kind": "spec",
                    "state": "analysis_pending",
                    "next_action": None,
                    "parent_spec_id": None,
                    "parent_task_id": None,
                    "source_path": spec_path,
                    "lanes": [],
                }
            )

    return rows


# --------------------------------------------------------------------------
# --auto support: pure helpers consumed by commands/close.md / commit.md
# --------------------------------------------------------------------------


def actionable_parents(rows: list[dict], next_action: str) -> list[str]:
    """Deterministically sorted PARENT task-ids with the given next_action.

    Lane rows (next_action forced to "none") and spec rows (task_id is None)
    never qualify -- only kind=="ticket" parent rows are ever actionable
    (Must-Have #3).
    """
    return sorted(
        r["task_id"]
        for r in rows
        if r.get("kind") == "ticket" and r.get("task_id") and r.get("next_action") == next_action
    )


def validate_auto_flag_combination(
    auto: bool, explicit_task_id: Optional[str], force: bool, bulk: bool
) -> Optional[str]:
    """Return an error string when --auto is illegally combined; else None.

    Must-Have #8: --auto is rejected (before any action) when combined with
    an explicit task-id/path, --force, or --bulk.
    """
    if not auto:
        return None
    if explicit_task_id:
        return "--auto cannot be combined with an explicit task-id/path"
    if force:
        return "--auto cannot be combined with --force"
    if bulk:
        return "--auto cannot be combined with --bulk"
    return None


def classify_walk_outcome(tool_result_text: str, *, partial_multi_repo_commit: bool = False) -> str:
    """Classify one parent's Step-walk outcome (objection 7's structured taxonomy).

    The walk itself is an orchestrator PROCEDURE (commands/close.md Step 0-3 /
    commands/commit.md Step 3-8 -- prose an agent follows via individual tool
    calls, not a literal bash script an exit code terminates). This pure
    function is the recognition predicate --auto applies to each walk's
    terminal tool-call result text:

      hook_deny        -- a PreToolUse/PostToolUse/Stop hook literally
                           blocked a tool call ("hook error: ... BLOCKED")
      partial_abort     -- a partial multi-repository commit (commit.md only)
      success            -- the last line's close verdict classifies yes
                             (hooks/lib/close-verdict.py), or COMMIT: APPROVE
                             observed
      ordinary_reject    -- everything else (a script's own exit 1/2,
                             CLOSE_FINDINGS, COMMIT: REJECT, ...)
    """
    if partial_multi_repo_commit:
        return "partial_abort"
    text = tool_result_text or ""
    if _HOOK_DENY_RE.search(text):
        return "hook_deny"
    verdict = _load_close_verdict_module()
    if verdict.classify_line(verdict.last_nonempty(text)) == "yes":
        return "success"
    if re.search(r"COMMIT:\s*APPROVE", text, re.IGNORECASE) or re.search(r"\bcommitted\b", text, re.IGNORECASE):
        return "success"
    return "ordinary_reject"


# --------------------------------------------------------------------------
# /tickets table rendering
# --------------------------------------------------------------------------

_TABLE_HEADERS = ["task_id", "kind", "state", "next_action", "parent_task_id", "parent_spec_id"]


def render_table(rows: list[dict]) -> str:
    str_rows = []
    widths = {h: len(h) for h in _TABLE_HEADERS}
    for r in rows:
        sr = {h: ("" if r.get(h) is None else str(r.get(h))) for h in _TABLE_HEADERS}
        str_rows.append(sr)
        for h in _TABLE_HEADERS:
            widths[h] = max(widths[h], len(sr[h]))
    lines = ["  ".join(h.ljust(widths[h]) for h in _TABLE_HEADERS)]
    lines.append("  ".join("-" * widths[h] for h in _TABLE_HEADERS))
    for sr in str_rows:
        lines.append("  ".join(sr[h].ljust(widths[h]) for h in _TABLE_HEADERS))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _default_project_dir() -> str:
    return str(Path(__file__).resolve().parent.parent)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="dev-lifecycle.py")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_parser = sub.add_parser("scan", help="Scan docs/dev/ and print the lifecycle rows.")
    scan_parser.add_argument("--format", choices=["table", "json"], default="table")
    scan_parser.add_argument("--project-dir", default=_default_project_dir())

    list_parser = sub.add_parser("list-actionable", help="List parent task-ids with a given next_action.")
    list_parser.add_argument("--next-action", required=True, choices=["close", "commit"])
    list_parser.add_argument("--project-dir", default=_default_project_dir())

    args = parser.parse_args(argv)
    project_root = Path(args.project_dir).resolve()

    if args.command == "scan":
        rows = scan(project_root)
        if args.format == "json":
            print(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True, default=str))
        else:
            print(render_table(rows))
        return 0

    if args.command == "list-actionable":
        # One line per parent: its task-id, then, for a dev-chain parent, its
        # chain result as the chain's own CLI prints it -- the walked task's
        # step takes it from here instead of calling the chain again.
        rows = scan(project_root)
        by_id = {row["task_id"]: row for row in rows if row.get("kind") == "ticket"}
        for task_id in actionable_parents(rows, args.next_action):
            chain = by_id[task_id].get("artifact_chain")
            if chain is None:
                print(task_id)
            else:
                print(task_id, json.dumps(chain, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
