#!/usr/bin/env python3
"""Verify write-time attribution chains (Phase 0).

Folds each file's events across ALL session journals into a hash chain and
reports, per file, one of:
  CONTINUOUS_TAIL_MATCH     chain unbroken AND tail hash == current on-disk hash
  CONTINUOUS_TAIL_MISMATCH  chain unbroken but disk differs from tail (an
                            unjournaled write happened after the last event)
  BREAK                     chain discontinuity: the two bracketing events and
                            both hashes on each side are printed

Model: events are edges pre_sha -> post_sha in a directed multigraph. The chain
is continuous iff all edges form ONE trail (Eulerian path), checked in O(E)
from node out/in-degree surplus plus union-find connectivity. Timestamps are
never used to establish continuity; they are used only to *label* which broken
segment came first when reporting bracketing events (diagnostic).

Usage: verify-attribution-chain.py [--file PATH ...] [--all] [--journal-dir DIR]
                                   [--json]   (default: --all)
Note: the first journaled event of a file is not itself verified against any
earlier state (nothing precedes it), so chains cover the journaled window only.
Exit: 0 all continuous+match, 1 any break/mismatch, 2 usage/no events.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
from lib import attribution_journal as aj  # noqa: E402


def _brief(ev):
    return {k: ev.get(k) for k in ("session_id", "seq", "tool", "invocation_id", "ts",
                                   "pre_sha", "post_sha")}


def _identity(ev):
    return {"session_id": ev.get("session_id"), "agent_id": ev.get("agent_id")}


def _collapse(events):
    """Collapse IDENTICAL transitions (same pre_sha, post_sha) into one edge.

    Overlapping measured shell windows observe the same file change twice; that
    is one transition, not two. Returns (edges, collapsed): edges = one
    representative (earliest) event per distinct transition; collapsed = list of
    {pre_sha, post_sha, witnesses[], ambiguous_writer, writers[]} for transitions
    recorded more than once. ambiguous_writer is set when the witnesses span
    more than one (session, agent) identity: causal attribution is then
    honestly unknowable. Divergent duplicates (same pre, different post) are
    different keys and stay a real fork."""
    groups = {}
    for ev in events:
        groups.setdefault((ev["pre_sha"], ev["post_sha"]), []).append(ev)
    by_ts = lambda e: (e.get("ts", 0), e.get("seq", 0))
    edges, collapsed = [], []
    for (pre, post), evs in groups.items():
        evs = sorted(evs, key=by_ts)
        edges.append(evs[0])
        if len(evs) > 1:
            writers = []
            for e in evs:
                w = _identity(e)
                if w not in writers:
                    writers.append(w)
            collapsed.append({"pre_sha": pre, "post_sha": post,
                              "witnesses": [_brief(e) | {"agent_id": e.get("agent_id")} for e in evs],
                              "ambiguous_writer": len(writers) > 1, "writers": writers})
    return edges, collapsed


def fold(events):
    """events: all events of ONE path. Returns dict(status=..., ...).

    Identical duplicate transitions collapse to one edge (see _collapse); the
    result carries `collapsed_edges` (witnesses + ambiguous_writer flag) and
    `ambiguous_writer` (any collapsed edge ambiguous). `events` in the result
    still counts raw events."""
    total = len(events)
    events, collapsed = _collapse(events)
    res = _fold_edges(events)
    spanning = []
    if res["status"] == "break":
        # A coalesced window can record A->C for two steps A->B->C that other
        # events also record. Drop such spanning edges ONLY if that makes the
        # chain exactly continuous; otherwise the original break stands.
        kept, spanning = _drop_spanning(events)
        if spanning:
            retry = _fold_edges(kept)
            if retry["status"] == "continuous":
                res = retry
            else:
                spanning = []
    res["events"] = total
    res["collapsed_edges"] = collapsed
    res["spanning_edges"] = spanning
    res["ambiguous_writer"] = any(c["ambiguous_writer"] for c in collapsed + spanning)
    return res


def _reaches(edges, skip, src, dst):
    """True if dst is reachable from src using >=2 edges other than `skip`."""
    adj = defaultdict(list)
    for e in edges:
        if e is not skip:
            adj[e["pre_sha"]].append(e["post_sha"])
    seen, stack = set(), [(n, 1) for n in adj[src]]
    while stack:
        n, d = stack.pop()
        if n == dst and d >= 2:
            return True
        if n in seen:
            continue
        seen.add(n)
        stack.extend((m, d + 1) for m in adj[n])
    return False


def _drop_spanning(edges):
    kept, spanning = list(edges), []
    for e in edges:
        if e["pre_sha"] != e["post_sha"] and _reaches(kept, e, e["pre_sha"], e["post_sha"]):
            kept.remove(e)
            spanning.append({"pre_sha": e["pre_sha"], "post_sha": e["post_sha"],
                             "witnesses": [_brief(e) | {"agent_id": e.get("agent_id")}],
                             "ambiguous_writer": True, "writers": [_identity(e)],
                             "note": "spans a multi-step path recorded by other events"})
    return kept, spanning


def _fold_edges(events):
    out_edges = defaultdict(list)   # pre -> events
    in_edges = defaultdict(list)    # post -> events
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for ev in events:
        out_edges[ev["pre_sha"]].append(ev)
        in_edges[ev["post_sha"]].append(ev)
        parent[find(ev["pre_sha"])] = find(ev["post_sha"])
    nodes = set(out_edges) | set(in_edges)
    starts, ends = [], []           # surplus nodes (with multiplicity)
    for n in nodes:
        d = len(out_edges[n]) - len(in_edges[n])
        starts.extend([n] * d if d > 0 else [])
        ends.extend([n] * (-d) if d < 0 else [])
    comps = {find(n) for n in nodes}
    if len(starts) <= 1 and len(ends) <= 1 and len(comps) == 1:
        if starts:
            head, tail = starts[0], ends[0]
            tails = [tail]
        else:                       # closed circuit: any node may be the tail
            head, tails = None, sorted(nodes)
        return {"status": "continuous", "head": head, "tails": tails, "events": len(events)}
    return {"status": "break", "segments": _segments(events, out_edges, in_edges, starts, ends, find),
            "events": len(events)}


def _segments(events, out_edges, in_edges, starts, ends, find):
    """Describe discontinuities as (dangling end event, dangling start event)."""
    by_ts = lambda e: (e.get("ts", 0), e.get("seq", 0))
    d_ends = [max(in_edges[n], key=by_ts) for n in ends]
    d_starts = [min(out_edges[n], key=by_ts) for n in starts]
    # genuine head = earliest dangling start, genuine tail = latest dangling end
    # (diagnostic ordering only); the rest are the break pairs.
    d_starts.sort(key=by_ts)
    d_ends.sort(key=by_ts)
    breaks = []
    if len(d_starts) > 1 and len(d_ends) > 1:
        for e, s in zip(d_ends[:-1], d_starts[1:]):
            breaks.append({"before": _brief(e), "after": _brief(s),
                           "hash_before": e["post_sha"], "hash_after": s["pre_sha"]})
    else:  # balanced degrees but disconnected components (e.g. two closed loops)
        reps = {}
        for ev in events:
            reps.setdefault(find(ev["pre_sha"]), ev)
        rl = sorted(reps.values(), key=by_ts)
        for a, b in zip(rl, rl[1:]):
            breaks.append({"before": _brief(a), "after": _brief(b),
                           "hash_before": a["post_sha"], "hash_after": b["pre_sha"],
                           "note": "disconnected components"})
    return breaks


def verify_path(path, events, disk_hash=None):
    res = fold(events)
    res["path"] = path
    if res["status"] == "continuous":
        disk = aj.hash_file(path) if disk_hash is None else disk_hash
        res["disk_sha"] = disk
        if disk in res["tails"]:
            res["verdict"] = "CONTINUOUS_TAIL_MATCH"
        else:
            res["verdict"] = "CONTINUOUS_TAIL_MISMATCH"
            last = max((e for e in events if e["post_sha"] in res["tails"]),
                       key=lambda e: (e.get("ts", 0), e.get("seq", 0)))
            res["last_event"] = _brief(last)
    else:
        res["verdict"] = "BREAK"
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", action="append", default=[], help="file to verify (repeatable)")
    ap.add_argument("--all", action="store_true", help="verify every journaled file (default)")
    ap.add_argument("--journal-dir", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    events, bad = aj.read_all_journals(Path(a.journal_dir) if a.journal_dir else None)
    by_path = defaultdict(list)
    for ev in events:
        by_path[ev["path"]].append(ev)
    if a.file:
        wanted = [os.path.abspath(f) for f in a.file]
    else:
        wanted = sorted(by_path)
    results, missing = [], []
    for p in wanted:
        if p in by_path:
            results.append(verify_path(p, by_path[p]))
        else:
            missing.append(p)
    if a.json:
        print(json.dumps({"results": results, "no_events": missing, "discarded_lines": bad}, indent=1))
    else:
        for r in results:
            print(f"{r['verdict']:26s} {r['path']}  (events={r['events']}; coverage starts at first event)")
            if r["verdict"] == "BREAK":
                for b in r["segments"]:
                    print(f"    break between {b['before']['session_id']}#{b['before']['seq']} "
                          f"({b['before']['tool']}) post_sha={b['hash_before']}")
                    print(f"              and {b['after']['session_id']}#{b['after']['seq']} "
                          f"({b['after']['tool']}) pre_sha={b['hash_after']}")
            for c in r.get("collapsed_edges", []):
                tag = "AMBIGUOUS_WRITER" if c["ambiguous_writer"] else "duplicate"
                ids = ", ".join(f"{w['session_id']}/{w['agent_id'] or '-'}" for w in c["writers"])
                print(f"    {tag}: {len(c['witnesses'])} witnesses of {c['pre_sha'][:12]}->{c['post_sha'][:12]} ({ids})")
            for c in r.get("spanning_edges", []):
                w = c["writers"][0]
                print(f"    AMBIGUOUS_WRITER (spanning window): {c['pre_sha'][:12]}->{c['post_sha'][:12]} "
                      f"by {w['session_id']}/{w['agent_id'] or '-'} covers a multi-step path")
            if r["verdict"] == "CONTINUOUS_TAIL_MISMATCH":
                le = r["last_event"]
                print(f"    last event {le['session_id']}#{le['seq']} post_sha={le['post_sha']}"
                      f" != disk {r['disk_sha']}")
        for p in missing:
            print(f"NO_EVENTS                  {p}")
        for b in bad:
            print(f"discarded malformed line {b['journal']}:{b['line']} ({b['reason']})", file=sys.stderr)
    if not results:
        return 2
    return 0 if all(r["verdict"] == "CONTINUOUS_TAIL_MATCH" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
