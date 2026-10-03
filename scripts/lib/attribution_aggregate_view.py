#!/usr/bin/env python3
"""Journal-backed canonical aggregate view (Phase C, purely additive).

Emits the canonical dev-report document shape that /close and /commit
resolution already read (the eleven keys of
scripts/aggregate-dev-report.py _canonical_projection: request_id, task_id,
baseline_head_sha, baseline_dirty_snapshot, dev_report_path, parallel_workers,
dev, blocking_issues, recommendations, owned_edits, pre_edit_snapshots), derived
from JOURNAL EVENTS plus LANE METADATA (agent_id based lane identity; events
carry no task_id). It never reads or writes the live canonical report.

Authority split:
  journal-derived  owned_edits, pre_edit_snapshots, dev.files_modified,
                   dev.files_created, dev.status basis, per-file verdicts
  shard narrative  dev.tasks_completed, scripts_created, permissions_to_add,
                   observed_preexisting, blocking_issues, recommendations
                   (not derivable from a journal) -- passed through verbatim and
                   labelled in journal_view.narrative_fields
Self-reported shards NEVER adjudicate ownership: each shard's declared file set is
compared with the journal's attribution for that lane's agent ids and every
difference is LISTED in journal_view.disagreements; no declaration adds or
removes an owned file. Status is worst-of(journal basis, shard statuses) so a
shard cannot make the view look healthier than the journal; that is a status
fold, not an ownership decision.

Only files with verdict WHOLE_FILE_ELIGIBLE / SYNTHESIZED_STAGE appear in
owned_edits. ENTANGLED / INSUFFICIENT_COVERAGE files are listed under
journal_view.unresolved_files and push dev.status to needs_review; they are not
guessed into owned_edits.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import attribution_adjudicator as adj  # noqa: E402
aj = adj.aj

ROOT = adj.ROOT
STATUS_RANK = {"completed": 0, "needs_review": 1, "blocked": 2}
IGNORED_PREFIXES = ("state/attribution-journal/", ".git/")


def _rel(root, path):
    r = root.rstrip("/") + "/"
    return path[len(r):] if path.startswith(r) else None


def _hunks_for_edge(pre_text, post_text, ctx=2):
    """Anchor hunks {old,new}: changed lines plus context, widened until the
    `old` anchor is unique in the pre-image (insertions need context)."""
    a, b = pre_text.split("\n"), post_text.split("\n")
    hunks = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        c = ctx
        while True:
            lo, hi = max(0, i1 - c), min(len(a), i2 + c)
            old = "\n".join(a[lo:hi])
            new = "\n".join(a[lo:i1] + b[j1:j2] + a[i2:hi])
            if pre_text.count(old) <= 1 or (lo == 0 and hi == len(a)):
                break
            c += 2
        hunks.append({"old": old, "new": new})
    return hunks


def _shard_declared(shard):
    dev = shard.get("dev") or {}
    files = set(dev.get("files_modified") or []) | set(dev.get("files_created") or [])
    files |= set((shard.get("owned_edits") or {}).keys())
    return files


def build_view(events, meta, *, root=None, gitdir=None, shards=None, disk_shas=None, escalation_dir=None,
               escalation_store=None):
    """meta: lane metadata (task_id, lanes[{lane, agent_ids, shard?}], baselines,
    baseline_head_sha, baseline_dirty_snapshot, foreign_agents). shards:
    {lane_label: shard_dict} narrative reports (may be empty)."""
    root = str(root or ROOT)
    gitdir = gitdir or aj.git_dir()
    shards = shards or {}
    task = adj.task_from_metadata(meta)
    in_repo = {}
    out_of_repo = set()
    for ev in events:
        rel = _rel(root, ev["path"])
        if rel is None:
            if task.owns(ev):
                out_of_repo.add(ev["path"])
        elif not rel.startswith(IGNORED_PREFIXES):
            in_repo.setdefault(ev["path"], []).append(ev)
    # only files the task's identities touched are the task's concern
    touched = {p: evs for p, evs in in_repo.items() if any(task.owns(e) for e in evs)}
    report = adj.adjudicate_task(events, task, sorted(touched), gitdir=gitdir, disk_shas=disk_shas,
                                 escalation_dir=escalation_dir, escalation_store=escalation_store)
    owned_edits, pre_snap, modified, created, unresolved, verdicts = {}, {}, [], [], [], {}
    for p, r in sorted(report["verdicts"].items()):
        rel = _rel(root, p)
        verdicts[rel] = {k: r[k] for k in ("verdict", "reason", "detail", "owned_edges", "foreign_edges",
                                          "conflicting_pair", "stage_blob", "stage_content_sha") if k in r}
        if r["verdict"] in (adj.WHOLE, adj.SYNTH):
            base = task.baselines.get(p)
            pre_snap[rel] = f"git-blob:{base} (journal baseline)" if base != aj.ABSENT else "absent at baseline"
            hunks = []
            mine = set(r.get("owned_edges", []))
            for e in sorted(touched[p], key=lambda e: (e.get("ts", 0), e.get("seq", 0))):
                if adj.edge_id(e) not in mine and not (r["verdict"] == adj.WHOLE and task.owns(e)):
                    continue
                pre, post = adj.blob_bytes(e["pre_sha"], gitdir), adj.blob_bytes(e["post_sha"], gitdir)
                if pre is None or post is None or e["pre_sha"] == e["post_sha"]:
                    continue
                for h in _hunks_for_edge(pre.decode("utf-8", "replace"), post.decode("utf-8", "replace")):
                    h["journal_edge"] = adj.edge_id(e)
                    if h not in hunks:
                        hunks.append(h)
            owned_edits[rel] = hunks
            (created if task.baselines.get(p) == aj.ABSENT else modified).append(rel)
        elif r["verdict"] in (adj.ENTANGLED, adj.INSUFFICIENT):
            unresolved.append({"path": rel, "verdict": r["verdict"], "reason": r.get("reason"),
                               "escalation_path": r.get("escalation_path")})
    # --- shard narrative cross-check (never adjudicates)
    lane_agents = {l["lane"]: set(l.get("agent_ids", [])) for l in meta.get("lanes", [])}
    disagreements = []
    for lane, agents in sorted(lane_agents.items()):
        journal_files = {_rel(root, p) for p, evs in touched.items()
                         if any(e.get("agent_id") in agents and task.owns(e) for e in evs)}
        if lane not in shards:
            disagreements.append({"lane": lane, "kind": "shard_missing",
                                  "journal_files": sorted(journal_files)})
            continue
        declared = _shard_declared(shards[lane])
        for f in sorted(declared - journal_files):
            disagreements.append({"lane": lane, "kind": "declared_not_journaled", "file": f})
        for f in sorted(journal_files - declared):
            disagreements.append({"lane": lane, "kind": "journaled_not_declared", "file": f})
    # --- status fold: worst-of
    basis = "needs_review" if unresolved else "completed"
    shard_status = [((s.get("dev") or {}).get("status") or "completed") for s in shards.values()]
    status = max([basis] + shard_status, key=lambda s: STATUS_RANK.get(s, 1))

    def union(*path):
        seen, out = set(), []
        for s in shards.values():
            v = s
            for k in path:
                v = v.get(k) if isinstance(v, dict) else None
            for item in (v if isinstance(v, list) else []):
                j = json.dumps(item, sort_keys=True)
                if j not in seen:
                    seen.add(j)
                    out.append(item)
        return out

    dev = {"status": status,
           "tasks_completed": union("dev", "tasks_completed"),
           "scripts_created": union("dev", "scripts_created"),
           "permissions_to_add": union("dev", "permissions_to_add"),
           "files_modified": sorted(modified),
           "files_created": sorted(created),
           "observed_preexisting": union("dev", "observed_preexisting")}
    if status != "completed":
        why = []
        if unresolved:
            why.append(f"{len(unresolved)} file(s) unresolved by the journal (entangled or insufficient coverage)")
        why += [f"shard reports {s}" for s in shard_status if s != "completed"]
        dev["status_rationale"] = "; ".join(why)
    tid = meta["task_id"]
    return {
        "request_id": tid,
        "task_id": tid,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "baseline_head_sha": meta.get("baseline_head_sha", ""),
        "baseline_dirty_snapshot": meta.get("baseline_dirty_snapshot", ""),
        "dev_report_path": f"docs/dev/dev-report-{tid}.json",
        "parallel_workers": [l["lane"] for l in meta.get("lanes", [])],
        "dev": dev,
        "blocking_issues": union("blocking_issues"),
        "recommendations": union("recommendations"),
        "owned_edits": owned_edits,
        "pre_edit_snapshots": pre_snap,
        "journal_view": {
            "source": "attribution journal events + lane metadata (agent_id identity)",
            "narrative_fields": ["dev.tasks_completed", "dev.scripts_created", "dev.permissions_to_add",
                                 "dev.observed_preexisting", "blocking_issues", "recommendations"],
            "verdict_counts": report["counts"],
            "file_verdicts": verdicts,
            "unresolved_files": unresolved,
            "disagreements": disagreements,
            "out_of_repo_task_writes": sorted(out_of_repo),
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Journal-backed canonical aggregate view (read-only).")
    ap.add_argument("--lanes", required=True)
    ap.add_argument("--shard", action="append", default=[], help="LANE=PATH narrative shard (repeatable)")
    ap.add_argument("--journal-dir")
    ap.add_argument("--git-dir")
    ap.add_argument("--repo-root", default=str(ROOT))
    ap.add_argument("--escalation-store", help="opt-in: additionally keep each unresolved file's escalation "
                    "record and every object it references reachable via refs/pending-conflicts/<id> (E6)")
    ap.add_argument("--output", help="write here; refuses to overwrite an existing file; default stdout")
    a = ap.parse_args(argv)
    meta = json.loads(Path(a.lanes).read_text())
    root = a.repo_root
    events, _ = aj.read_all_journals(Path(a.journal_dir) if a.journal_dir else None)
    rels = sorted({os.path.relpath(e["path"], root) for e in events if e["path"].startswith(root.rstrip("/") + "/")})
    meta["baselines"] = adj.fill_clean_baselines(
        dict(meta, baselines={adj.abs_event_path(root, k): v for k, v in (meta.get("baselines") or {}).items()}),
        root, rels)
    shards = {}
    for spec in a.shard:
        lane, _, path = spec.partition("=")
        shards[lane] = json.loads(Path(path).read_text())
    for l in meta.get("lanes", []):
        if l["lane"] not in shards and l.get("shard") and Path(root, l["shard"]).is_file():
            shards[l["lane"]] = json.loads(Path(root, l["shard"]).read_text())
    doc = build_view(events, meta, root=root, gitdir=a.git_dir, shards=shards, escalation_store=a.escalation_store)
    text = json.dumps(doc, indent=2, sort_keys=True)
    if a.output:
        if os.path.exists(a.output):
            print(f"refusing to overwrite existing {a.output}", file=sys.stderr)
            return 2
        with open(a.output, "x") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
