#!/usr/bin/env python3
"""Dispatch-time metadata: the two missing halves write-time attribution needs to
answer "which bytes are this task's" -- (1) nothing records which agent identity
belongs to which task's lane (the attribution journal records "some agent changed
these bytes" but no file maps agent_id -> task_id/lane), and (2) nothing captures
dispatch-time baseline CONTENT for a path already dirty when a task is dispatched
(attribution_adjudicator.capture_dispatch_baselines() does the capture but, per its
own docstring, is "unwired to any dispatcher").

This module is the dispatcher-side wiring for both: init_task() captures baseline_
head_sha, baseline_dirty_snapshot, and (via capture_dispatch_baselines, re-used
verbatim -- not reimplemented) a content-fingerprint blob for every dirty path;
add_lane() records an agent_id under a lane as each dispatch returns one. The
persisted record is exactly the --lanes input shape scripts/adjudicate-attribution-
staging.py and scripts/attribution-aggregate-view.py already require (see
docs/reference/attribution-journal-cutover-flip-plan-20261003.md "Input contract"):
task_id, baseline_head_sha, baseline_dirty_snapshot, lanes[].{lane,agent_ids},
baselines{path: blob}. No new shape is invented.

init_task() MUST be called by the dispatcher AT the moment of dispatch -- same
constraint as capture_dispatch_baselines() itself: the bytes hashed for a dirty
path are whatever is on disk RIGHT NOW. A second init_task() for a task already on
disk is refused by the CLI (main() below), not silently re-run -- recapturing after
the task has started editing would hash the task's OWN edits as if they were the
pre-dispatch baseline, which is the exact failure mode this module exists to
prevent (mirrors the never-guess-a-baseline rule adjudicate_file() already enforces
for a path with no baseline at all).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def _load_by_path(name, path):
    # by path, not `from lib import ...`: scripts/lib and hooks/lib share the package name `lib`
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


adj = _load_by_path("attribution_adjudicator", HERE / "attribution_adjudicator.py")

REQUIRED_KEYS = ("task_id", "lanes", "baselines", "baseline_head_sha", "baseline_dirty_snapshot")


def _clean_env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(root, *args):
    """stdout with only the trailing newline(s) removed (matches shell `$(...)`
    semantics) -- NOT .strip(): `git status --porcelain` lines lead with a
    meaningful status-column space (" M path") that a full strip would eat,
    corrupting _dirty_rel_paths()'s fixed-width ln[3:] parse."""
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, env=_clean_env())
    return r.stdout.rstrip("\n") if r.returncode == 0 else ""


def default_metadata_path(root, task_id):
    return Path(root) / ".claude" / "dev-registry" / task_id / "dispatch-metadata.json"


def init_task(task_id, root, *, baseline_head_sha=None, baseline_dirty_snapshot=None):
    """Dispatch-time metadata skeleton for `task_id`. baseline_head_sha / baseline_
    dirty_snapshot are taken verbatim when the caller already captured them (e.g.
    commands/dev.md Step 10's existing shell capture), so the persisted record is
    byte-identical to what also goes into the dispatch prompt text; a value of None
    means "capture it now" (both must then be captured in the same call so they
    describe the same instant). `lanes` starts empty -- add_lane() fills it in as
    each dispatch returns an agent_id.

    Returns the metadata dict (not yet persisted; see save())."""
    head = baseline_head_sha if baseline_head_sha is not None else _git(root, "rev-parse", "HEAD")
    dirty = baseline_dirty_snapshot if baseline_dirty_snapshot is not None else _git(root, "status", "--porcelain")
    baselines = adj.capture_dispatch_baselines(root, dirty)
    return {
        "task_id": task_id,
        "lanes": [],
        "baselines": baselines,
        "baseline_head_sha": head,
        "baseline_dirty_snapshot": dirty,
    }


def add_lane(meta, lane, agent_id):
    """Register `agent_id` under `lane` (new entry, or append-dedup onto an
    existing one -- a lane re-dispatched for a QA repair round keeps every agent_id
    it ever ran under, since a later round's events are still that lane's)."""
    if not isinstance(meta, dict) or "lanes" not in meta:
        raise ValueError("add_lane requires an already-initialized metadata dict (call init_task first)")
    for entry in meta["lanes"]:
        if entry["lane"] == lane:
            if agent_id not in entry["agent_ids"]:
                entry["agent_ids"].append(agent_id)
            return meta
    meta["lanes"].append({"lane": lane, "agent_ids": [agent_id]})
    return meta


def load(path):
    return json.loads(Path(path).read_text())


def save(meta, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp%d" % os.getpid())
    tmp.write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, p)
    return str(p)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Persist write-time dispatch metadata (agent-identity-to-"
                                              "lane mapping + dispatch-time baseline content) in the --lanes "
                                              "shape scripts/adjudicate-attribution-staging.py and "
                                              "scripts/attribution-aggregate-view.py already require.")
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--repo-root", default=str(ROOT))
    ap.add_argument("--out", help="defaults to <repo-root>/.claude/dev-registry/<task-id>/dispatch-metadata.json")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--init", action="store_true", help="DISPATCH-TIME ONLY: capture baseline_head_sha, "
                      "baseline_dirty_snapshot, and a dispatch-time baseline content blob for every path "
                      "the dirty snapshot names. Refuses if metadata already exists for this task -- the "
                      "dispatch moment has passed; recapturing now would hash the task's own edits.")
    mode.add_argument("--add-lane", metavar="LANE", help="register --agent-id under this lane; requires "
                      "--init to have already run for this task (refuses to invent a task record)")
    ap.add_argument("--agent-id", help="required with --add-lane")
    ap.add_argument("--baseline-head-sha", help="--init only: use this value verbatim instead of capturing "
                    "it now (keeps the persisted record byte-identical to a value the caller already captured)")
    ap.add_argument("--baseline-dirty-snapshot", help="--init only: ditto for baseline_dirty_snapshot")
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else default_metadata_path(a.repo_root, a.task_id)

    if a.init:
        if out.exists():
            print(f"refusing to re-initialize dispatch metadata already at {out}: the dispatch moment has "
                  f"passed; recapturing now would hash the task's own edits as if they were the pre-dispatch "
                  f"baseline (see init_task()'s docstring)", file=sys.stderr)
            return 2
        meta = init_task(a.task_id, a.repo_root, baseline_head_sha=a.baseline_head_sha,
                         baseline_dirty_snapshot=a.baseline_dirty_snapshot)
        save(meta, out)
        print(json.dumps({"written": str(out), "dirty_paths_captured": len(meta["baselines"])}))
        return 0

    if not a.agent_id:
        print("--add-lane requires --agent-id", file=sys.stderr)
        return 2
    if not out.exists():
        print(f"no dispatch metadata at {out}: run --init for this task before registering a lane "
              f"(refusing to invent a task record with no captured baseline)", file=sys.stderr)
        return 2
    meta = load(out)
    add_lane(meta, a.add_lane, a.agent_id)
    save(meta, out)
    print(json.dumps({"written": str(out), "lane": a.add_lane, "agent_id": a.agent_id}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
