#!/usr/bin/env python3
"""Three-way staging adjudicator over write-time attribution journal chains.

Phase D cutover: the lane-agnostic
`ledger_structural_verdict()` / `ledger_blocks()` at the bottom of this file are the
real, executed-path callers for scripts/resolve-commit-repos.py's ownership gate,
hooks/subagentstop-artifact-contract-enforce.py's artifact-contract section, and
scripts/aggregate-dev-report.py's same-cycle-only completeness gate. The full
per-task adjudicator below (adjudicate_file, requiring real lane metadata, which no
dispatcher records yet) runs for them with a lane-agnostic task.

It reads journal events (hooks/lib/attribution_journal.py) and the chain fold
(scripts/verify-attribution-chain.py), and for each file under a task baseline
returns exactly one verdict:

  WHOLE_FILE_ELIGIBLE   every state-changing chain edge is attributed to the task
                        -> the whole file (tail blob) may be staged.
  SYNTHESIZED_STAGE     foreign edges are interleaved, but the task's edge-level
                        diffs (pre blob -> post blob per edge) apply cleanly onto
                        the baseline, AND baseline + task deltas recomposed with
                        baseline + foreign deltas reproduces the on-disk tail
                        byte for byte -> `stage_content` is the synthesized bytes.
  ENTANGLED             anything else with enough coverage to judge. NEVER
                        auto-resolved, side-selected or merged: an
                        escalation record naming the exact conflicting edge
                        pair is emitted (schemas/owned-edits-ledger.v1.json
                        x-classification-contract.escalation_record_properties
                        E1..E7).
  INSUFFICIENT_COVERAGE the journal window does not span back to the task
                        baseline (or the chain breaks / tail differs from disk /
                        a blob is unavailable). Explicitly NOT entangled: the
                        journal cannot judge this file at all.
  NOT_TASK_FILE         the journal holds no edge attributable to the task.

Conservatism rules (deliberate, not tunable):
  * An edge flagged ambiguous_writer is never counted as owned by any party.
    When any witness of an ambiguous (collapsed or spanning) edge is a task
    identity and the edge changes bytes, it is decisive -> ENTANGLED. An
    ambiguous edge no task identity witnessed is simply foreign.
  * Coverage is checked BEFORE ambiguity or ownership: chain head must equal
    the baseline blob, the chain must be unbroken, and the tail must equal the
    on-disk bytes.
  * Lane identity is agent_id based (events carry no task_id). An event with no
    agent_id is never the task's.
  * Textual 3-way merge is `git merge-file` on temp files: adjacency counts as
    overlap (fails closed). It creates no commit, ref, index entry or object.

Limits stated up front: the escalation record rides in the ENTANGLED verdict
only; nothing here persists it. A file already dirty when a task is
dispatched has no baseline (fill_clean_baselines() below only infers CLEAN
paths from the committed HEAD blob). Gate-side consumption of the region scope
(E7 / dependency D3) is still not here.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
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


aj = _load_by_path("attribution_journal", ROOT / "hooks" / "lib" / "attribution_journal.py")

WHOLE = "WHOLE_FILE_ELIGIBLE"
SYNTH = "SYNTHESIZED_STAGE"
ENTANGLED = "ENTANGLED"
INSUFFICIENT = "INSUFFICIENT_COVERAGE"
NOT_TASK = "NOT_TASK_FILE"
VERDICTS = (WHOLE, SYNTH, ENTANGLED, INSUFFICIENT, NOT_TASK)
UNUSABLE = {aj.OVERSIZE, aj.NOTFILE, "unreadable"}
NO_SELECTION_LITERAL = ("NO SIDE HAS BEEN SELECTED AND NOTHING HAS BEEN DISCARDED: both versions "
                        "are preserved below; a human must decide.")
PAIRWISE_CAP = 400


def _load_verify():
    spec = importlib.util.spec_from_file_location("verify_attr_chain", ROOT / "scripts" / "verify-attribution-chain.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


V = _load_verify()


# ------------------------------------------------------------------ task spec

class TaskSpec:
    """A task = the union of its lanes' agent identities (journal events carry
    no task_id). `session_ids`, when given, additionally pins the session."""

    def __init__(self, task_id, agent_ids, baselines=None, session_ids=None,
                 foreign_agents=None):
        self.task_id = task_id
        self.agent_ids = set(agent_ids)
        self.session_ids = set(session_ids) if session_ids else None
        self.baselines = dict(baselines or {})       # abs path -> baseline blob sha | "absent"
        self.foreign_agents = dict(foreign_agents or {})   # agent_id -> task_id (other lanes)

    def owns_identity(self, session_id, agent_id):
        if not agent_id or agent_id not in self.agent_ids:
            return False
        return self.session_ids is None or session_id in self.session_ids

    def owns(self, ev):
        return self.owns_identity(ev.get("session_id"), ev.get("agent_id"))


def edge_id(ev):
    return f"{ev.get('session_id')}#{ev.get('seq')}"


# -------------------------------------------------------------------- git io

def _clean_env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def blob_bytes(sha, gitdir):
    """bytes for a journal state id; b'' for absent; None when unavailable."""
    if sha == aj.ABSENT:
        return b""
    if sha in UNUSABLE or not sha:
        return None
    r = subprocess.run(["git", "--git-dir", gitdir, "cat-file", "blob", sha],
                       capture_output=True, env=_clean_env())
    return r.stdout if r.returncode == 0 else None


def disk_sha_nowrite(path):
    """Hash on-disk bytes WITHOUT writing an object (hash-object, no -w)."""
    if not os.path.lexists(path):
        return aj.ABSENT
    if not os.path.isfile(path):
        return aj.NOTFILE
    r = subprocess.run(["git", "hash-object", "--no-filters", "--", path],
                       capture_output=True, text=True, env=_clean_env())
    return r.stdout.strip() if r.returncode == 0 else "unreadable"


def merge3(cur, base, other):
    """Apply (base -> other) onto cur. Returns (status, bytes, conflict) where
    status is 'clean' | 'conflict' | 'unsupported'. conflict = first diff3 hunk."""
    if b"\0" in cur or b"\0" in base or b"\0" in other:
        return "unsupported", b"", None
    with tempfile.TemporaryDirectory(prefix="attr-merge-") as td:
        paths = []
        for name, data in (("cur", cur), ("base", base), ("other", other)):
            p = os.path.join(td, name)
            with open(p, "wb") as fh:
                fh.write(data)
            paths.append(p)
        r = subprocess.run(["git", "merge-file", "-p", "--diff3", "-L", "cur", "-L", "base", "-L", "other", *paths],
                           capture_output=True, env=_clean_env())
    if r.returncode == 0:
        return "clean", r.stdout, None
    if 0 < r.returncode < 127:
        return "conflict", r.stdout, _first_conflict(r.stdout)
    return "unsupported", b"", None


def _first_conflict(out):
    text = out.decode("utf-8", "replace")
    lines = text.split("\n")
    sec, got, i0 = None, {"cur": [], "base": [], "other": []}, None
    for i, ln in enumerate(lines):
        if ln.startswith("<<<<<<< "):
            sec, i0 = "cur", i
        elif ln.startswith("||||||| ") and sec:
            sec = "base"
        elif ln.startswith("=======") and sec == "base":
            sec = "other"
        elif ln.startswith(">>>>>>> ") and sec:
            return {"cur": "\n".join(got["cur"]), "base": "\n".join(got["base"]),
                    "other": "\n".join(got["other"]), "marker_line": i0 + 1}
        elif sec:
            got[sec].append(ln)
    return None


def overlap_inclusive_count(haystack, needle):
    """Occurrences of needle in haystack, overlapping matches counted (E2)."""
    if not needle:
        return 0
    n, i = 0, haystack.find(needle)
    while i != -1:
        n += 1
        i = haystack.find(needle, i + 1)
    return n


# ----------------------------------------------------------------- chain walk

def _trail_edges(events):
    """Fold the path's events with the verified fold; return
    (fold_result, trail_edges_unordered, ambiguous_records).
    Trail = collapsed representatives minus spanning edges the fold dropped."""
    res = V.fold(events)
    edges, _ = V._collapse(events)
    span_keys = {(s["pre_sha"], s["post_sha"]) for s in res["spanning_edges"]}
    trail = [e for e in edges if (e["pre_sha"], e["post_sha"]) not in span_keys]
    ambiguous = [dict(c, kind="collapsed") for c in res["collapsed_edges"] if c["ambiguous_writer"]]
    ambiguous += [dict(s, kind="spanning") for s in res["spanning_edges"]]
    return res, trail, ambiguous


def _order_trail(trail, baseline):
    """Order edges as a walk from baseline. Unique when every state has out-degree
    <= 1; otherwise timestamp order is accepted ONLY if it is a valid walk.
    Returns (ordered, None) or (None, reason)."""
    real = [e for e in trail if e["pre_sha"] != e["post_sha"]]
    out = {}
    for e in real:
        out.setdefault(e["pre_sha"], []).append(e)
    if all(len(v) == 1 for v in out.values()):
        walk, cur, used = [], baseline, set()
        while cur in out and id(out[cur][0]) not in used:
            e = out[cur][0]
            used.add(id(e))
            walk.append(e)
            cur = e["post_sha"]
        if len(walk) == len(real):
            return walk, None
        return None, "walk_does_not_reach_every_edge"
    by_ts = sorted(real, key=lambda e: (e.get("ts", 0), e.get("seq", 0)))
    cur = baseline
    for e in by_ts:
        if e["pre_sha"] != cur:
            return None, "state_revisited_and_timestamp_order_is_not_a_valid_walk"
        cur = e["post_sha"]
    return by_ts, None


# ------------------------------------------------------------------- verdicts

def _ref(path, ev):
    return f"{path}#edge:{edge_id(ev)}"


def _claimant(ev, task):
    aid = ev.get("agent_id")
    mine = task.owns(ev)
    tid = task.task_id if mine else task.foreign_agents.get(aid) if aid else None
    return {"claimant_id": aid or "unattributed-main-thread", "session_id": ev.get("session_id"),
            "task_id": tid, "is_task": mine, "claim_ref": None}


def _verdict(kind, path, **kw):
    d = {"path": path, "verdict": kind}
    d.update(kw)
    return d


def adjudicate_file(path, events, task, *, gitdir=None, disk_sha=None):
    """One file's verdict. `events` = every journal event for `path`."""
    gitdir = gitdir or aj.git_dir()
    if not events:
        return _verdict(INSUFFICIENT, path, reason="no_journal_events",
                        detail="the journal has no event for this file; it cannot judge it")
    baseline = task.baselines.get(path)
    if not baseline:
        return _verdict(INSUFFICIENT, path, reason="baseline_blob_unresolved",
                        detail="no dispatch-time baseline blob was supplied for this file")
    res, trail, ambiguous = _trail_edges(events)
    first = min(events, key=lambda e: (e.get("ts", 0), e.get("seq", 0)))
    cov = {"baseline_sha": baseline, "first_event": edge_id(first), "events": len(events)}
    if res["status"] != "continuous":
        return _verdict(INSUFFICIENT, path, reason="chain_break", coverage=cov,
                        detail="unjournaled write(s) between events; segments: " + json.dumps(res["segments"]))
    bad = [e for e in events if e["pre_sha"] in UNUSABLE or e["post_sha"] in UNUSABLE]
    if bad:
        return _verdict(INSUFFICIENT, path, reason="state_not_hashable", coverage=cov,
                        detail=f"edge {edge_id(bad[0])} carries an unreadable/oversize/non-file state")
    nodes = {e["pre_sha"] for e in events} | {e["post_sha"] for e in events}
    head = res["head"]
    if (head is not None and head != baseline) or (head is None and baseline not in nodes):
        return _verdict(INSUFFICIENT, path, reason="coverage_window_starts_after_baseline", coverage=cov,
                        detail=f"chain head {head} != task baseline {baseline}: the file changed before "
                               f"the journal's first event (or the baseline is not on the chain)")
    disk = disk_sha if disk_sha is not None else disk_sha_nowrite(path)
    if disk not in res["tails"]:
        return _verdict(INSUFFICIENT, path, reason="tail_mismatch_unjournaled_write", coverage=cov,
                        detail=f"on-disk {disk} is not the chain tail {res['tails']}; an unjournaled write followed")
    ordered, why = _order_trail(trail, baseline)
    owned_ids = lambda ev: task.owns(ev)
    # ambiguity first: decisive when a task identity witnessed a byte-changing ambiguous edge
    for amb in ambiguous:
        if amb["pre_sha"] == amb["post_sha"]:
            continue
        wit = amb["witnesses"]
        mine = [w for w in wit if task.owns_identity(w.get("session_id"), w.get("agent_id"))]
        if mine:
            other = next((w for w in wit if w not in mine), None)
            if other is None:
                other = next((e for e in trail if e["pre_sha"] == amb["pre_sha"]
                              and e["post_sha"] != amb["post_sha"]), None)
            pair = (_witness_as_event(mine[0], path, amb), _witness_as_event(other, path, amb) if other else None)
            return _entangled(path, task, gitdir, baseline, pair, "ambiguous_writer_decisive",
                              f"edge {amb['pre_sha'][:12]}->{amb['post_sha'][:12]} ({amb['kind']}) was recorded by "
                              f"more than one writer identity including a task identity; ownership is unknowable",
                              cov, derivation="ambiguous_witnesses", ambiguous=amb)
    if ordered is None:
        a, b = _first_two(trail)
        return _entangled(path, task, gitdir, baseline, (a, b), "order_not_determinable",
                          f"edge order is not provable ({why})", cov, derivation="unordered")
    mine = [e for e in ordered if owned_ids(e)]
    foreign = [e for e in ordered if not owned_ids(e)]
    if not mine:
        return _verdict(NOT_TASK, path, coverage=cov, foreign_edges=[edge_id(e) for e in foreign],
                        detail="no chain edge is attributable to the task")
    tail_bytes = blob_bytes(disk, gitdir)
    if not foreign:
        return _verdict(WHOLE, path, coverage=cov, stage_blob=disk,
                        owned_edges=[edge_id(e) for e in mine],
                        detail="every state-changing edge is the task's")
    return _separate(path, task, gitdir, baseline, ordered, tail_bytes, disk, cov)


def _witness_as_event(w, path, amb):
    if w is None:
        return None
    ev = dict(w)
    ev.setdefault("path", path)
    ev.setdefault("pre_sha", amb["pre_sha"])
    ev.setdefault("post_sha", amb["post_sha"])
    return ev


def _first_two(trail):
    real = sorted(trail, key=lambda e: (e.get("ts", 0), e.get("seq", 0)))
    return (real[0] if real else None), (real[1] if len(real) > 1 else None)


def _delta(ev, gitdir):
    pre, post = blob_bytes(ev["pre_sha"], gitdir), blob_bytes(ev["post_sha"], gitdir)
    return pre, post


def _separate(path, task, gitdir, baseline, ordered, tail_bytes, disk, cov):
    blobs = {}
    for e in ordered:
        pre, post = _delta(e, gitdir)
        if pre is None or post is None:
            return _verdict(INSUFFICIENT, path, reason="blob_unavailable", coverage=cov,
                            detail=f"edge {edge_id(e)} references a blob missing from the object store")
        blobs[id(e)] = (pre, post)
    base_bytes = blob_bytes(baseline, gitdir)
    if base_bytes is None or tail_bytes is None:
        return _verdict(INSUFFICIENT, path, reason="blob_unavailable", coverage=cov,
                        detail="baseline or tail blob missing from the object store")
    for i, e in enumerate(ordered):
        if e["post_sha"] == aj.ABSENT:
            nb = _nearest_other_owner(ordered, i, task)
            return _entangled(path, task, gitdir, baseline, (e, nb), "deletion_interleaved",
                              f"edge {edge_id(e)} deletes the file amid interleaved writers", cov,
                              derivation="deletion_edge")
    s_cur, f_cur = base_bytes, base_bytes
    for i, e in enumerate(ordered):
        pre, post = blobs[id(e)]
        mine = task.owns(e)
        st, out, conflict = merge3(s_cur if mine else f_cur, pre, post)
        if st == "unsupported":
            return _entangled(path, task, gitdir, baseline, (e, _nearest_other_owner(ordered, i, task)),
                              "binary_or_unmergeable_interleaved",
                              f"edge {edge_id(e)}: interleaved binary content cannot be 3-way merged", cov,
                              derivation="adjacent_other_owner")
        if st == "conflict":
            other, how = _counterpart(ordered, i, task, conflict, blobs, gitdir)
            return _entangled(path, task, gitdir, baseline, (e, other),
                              "task_delta_does_not_apply_on_baseline" if mine else "foreign_delta_does_not_apply_on_baseline",
                              f"edge {edge_id(e)} does not apply onto the baseline without the other party's edits",
                              cov, derivation=how, conflict=conflict)
        if mine:
            s_cur = out
        else:
            f_cur = out
    st, recomposed, conflict = merge3(s_cur, base_bytes, f_cur)
    if st != "clean" or recomposed != tail_bytes:
        a = [e for e in ordered if task.owns(e)][-1]
        b = [e for e in ordered if not task.owns(e)][-1]
        return _entangled(path, task, gitdir, baseline, (a, b), "recomposition_mismatch",
                          "baseline + task deltas combined with baseline + foreign deltas does not reproduce "
                          "the on-disk bytes: the two parties' edits interact", cov,
                          derivation="last_edge_of_each_party", conflict=conflict,
                          recomposed=recomposed, tail=tail_bytes)
    return _verdict(SYNTH, path, coverage=cov, stage_content=s_cur,
                    stage_content_sha=_sha_nowrite(s_cur),
                    owned_edges=[edge_id(e) for e in ordered if task.owns(e)],
                    foreign_edges=[edge_id(e) for e in ordered if not task.owns(e)],
                    detail="task deltas apply cleanly onto baseline and recompose with the foreign "
                           "deltas to the exact on-disk bytes")


def _sha_nowrite(data):
    return subprocess.run(["git", "hash-object", "--stdin"], input=data, capture_output=True,
                          env=_clean_env()).stdout.decode().strip()


def _nearest_other_owner(ordered, i, task):
    me = task.owns(ordered[i])
    for d in range(1, len(ordered)):
        for j in (i - d, i + d):
            if 0 <= j < len(ordered) and task.owns(ordered[j]) != me:
                return ordered[j]
    return None


def _counterpart(ordered, i, task, conflict, blobs, gitdir):
    """Name the other-party edge for a failed apply. Content overlap first
    (an earlier other-party edge whose changed lines appear in the conflict's
    base section), else the nearest earlier other-party edge, else nearest."""
    import difflib
    me = task.owns(ordered[i])
    base_lines = {ln.strip() for ln in (conflict or {}).get("base", "").split("\n") if ln.strip()}
    for j in range(i - 1, -1, -1):
        c = ordered[j]
        if task.owns(c) == me:
            continue
        pre, post = blobs[id(c)]
        a, b = pre.decode("utf-8", "replace").split("\n"), post.decode("utf-8", "replace").split("\n")
        touched = set()
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag != "equal":
                touched.update(x.strip() for x in b[j1:j2] if x.strip())
        if touched & base_lines:
            return c, "content_overlap"
    for j in range(i - 1, -1, -1):
        if task.owns(ordered[j]) != me:
            return ordered[j], "nearest_earlier_other_party_edge"
    return _nearest_other_owner(ordered, i, task), "nearest_other_party_edge"


# ------------------------------------------------------ escalation record E1-E7

def _sha(*parts):
    h = hashlib.sha256()
    for p in parts:
        h.update(p if isinstance(p, bytes) else str(p).encode())
        h.update(b"\0")
    return h.hexdigest()


def _excerpt(text, anchor, ctx=3, cap=4000):
    lines = text.split("\n")
    first = anchor.split("\n")[0] if anchor else ""
    at = next((i for i, ln in enumerate(lines) if first and ln == first), 0)
    return "\n".join(lines[max(0, at - ctx): at + len(anchor.split("\n")) + ctx])[:cap]


def _entangled(path, task, gitdir, baseline, pair, reason, detail, cov, *,
               derivation, conflict=None, ambiguous=None, recomposed=None, tail=None):
    a, b = pair
    out = _verdict(ENTANGLED, path, reason=reason, detail=detail, coverage=cov,
                   conflicting_pair={"derivation": derivation,
                                     "edges": [edge_id(x) if x else None for x in pair]})
    out["escalation"] = build_escalation_record(path, task, gitdir, baseline, a, b, reason, detail,
                                                conflict, recomposed, tail, ambiguous, derivation)
    return out


def build_escalation_record(path, task, gitdir, baseline, a, b, reason, detail, conflict,
                            recomposed, tail, ambiguous, derivation):
    base_bytes = blob_bytes(baseline, gitdir) or b""
    base_text = base_bytes.decode("utf-8", "replace")
    if conflict and (conflict.get("base") or conflict.get("cur") or conflict.get("other")):
        # identify the region by content IN THE BOUND IMAGE: prefer the diff3 section whose
        # text occurs in the baseline (cur is baseline-derived when a delta is applied to it)
        cands = [conflict[k] for k in ("cur", "base", "other") if conflict.get(k)]
        anchor = next((c for c in cands if overlap_inclusive_count(base_text, c)), cands[0] if cands else "")
    elif recomposed is not None and tail is not None:
        ra, rb = recomposed.decode("utf-8", "replace"), tail.decode("utf-8", "replace")
        la, lb = ra.split("\n"), rb.split("\n")
        k = next((i for i in range(min(len(la), len(lb))) if la[i] != lb[i]), min(len(la), len(lb)))
        anchor = "\n".join(lb[k:k + 5])
    else:
        anchor = ""
    claimants, versions, if_chosen = [], [], []
    for ev in (a, b):
        if ev is None:
            continue
        c = _claimant(ev, task)
        c["claim_ref"] = _ref(path, ev)
        c["edge"] = {"session_id": ev.get("session_id"), "seq": ev.get("seq"), "agent_id": ev.get("agent_id"),
                     "ts": ev.get("ts"), "tool": ev.get("tool")}
        claimants.append(c)
        post = blob_bytes(ev["post_sha"], gitdir)
        post_t = (post or b"").decode("utf-8", "replace")
        ex = _excerpt(post_t, anchor)
        versions.append({"claim_ref": c["claim_ref"], "object_id": ev["post_sha"],
                         "object_id_kind": "git blob in the journal object store", "excerpt": ex})
        if_chosen.append({"claim_ref": c["claim_ref"],
                          "summary": f"Keep the version written by {c['claim_ref']} for the contested region.",
                          "differing_bytes": ex,
                          "omitted_identical_bytes": 0,
                          "preview_digest": _sha("preview", c["claim_ref"], ex)})
    ids = [c["claimant_id"] for c in claimants]
    e1 = (len(claimants) >= 2 and len(set(ids)) == len(ids)
          and all(c["session_id"] and c["task_id"] for c in claimants)
          and not any(i.startswith("unattributed") for i in ids))
    for c in claimants:
        c["resolvable"] = bool(c["session_id"] and c["task_id"])
    rid = _sha("conflict-record", path, baseline, anchor, *[c["claim_ref"] for c in claimants],
               *[v["object_id"] for v in versions])
    msg = (f"{NO_SELECTION_LITERAL} File {path}: {detail} Claimants: "
           + "; ".join(f"{c['claim_ref']} (agent {c['claimant_id']}, session {c['session_id']}, "
                       f"task {c['task_id']})" for c in claimants)
           + ". Contested region (by content):\n" + anchor + "\n" + NO_SELECTION_LITERAL)
    return {
        "schema_id": "attribution-escalation.v1",
        "design": "owned-edits-ledger.v1 x-classification-contract.escalation_record_properties E1-E7",
        "conflict_record_id": rid,
        "classification_verdict": "ownership_conflict" if reason != "ambiguous_writer_decisive" else "classification_undeterminable",
        "journal_verdict": ENTANGLED,
        "reason": reason,
        "path": path,
        "claimants": claimants,
        "E1_satisfied": e1,
        "E1_note": None if e1 else "a claimant is not resolvable to a (session, task) or is the unattributed "
                                   "main thread; the journal alone cannot name every task, so the census is incomplete",
        "contested_region": {
            "anchor": anchor,
            "anchor_uniqueness": {"count": overlap_inclusive_count(base_text, anchor), "counting": "overlap_inclusive"},
            "bound_image_id": baseline,
            "boundary_resolution": [{"claim_ref": c["claim_ref"], "resolved": bool(anchor)} for c in claimants],
            "line_numbers": {"advisory": True,
                             "baseline_first_line": (base_text.find(anchor) >= 0 and base_text[:base_text.find(anchor)].count("\n") + 1) or None},
            "pair_derivation": derivation,
        },
        "versions": versions,
        "no_selection_and_no_discard": NO_SELECTION_LITERAL,
        "if_chosen": if_chosen,
        "rendered_message": msg,
        "scope": {"kind": "region", "path": path, "region_digest": _sha("region", anchor),
                  "gate_consumption": "dependency D3 (IAC-2), not implemented here"},
        "ambiguous_edge": ({k: ambiguous[k] for k in ("pre_sha", "post_sha", "kind", "writers")} if ambiguous else None),
    }


# ----------------------------------------------------------------- task level

def task_from_metadata(meta):
    agent_ids = {a for lane in meta.get("lanes", []) for a in lane.get("agent_ids", [])}
    foreign = dict(meta.get("foreign_agents") or {})
    return TaskSpec(meta["task_id"], agent_ids, baselines=meta.get("baselines"),
                    session_ids=meta.get("session_ids"), foreign_agents=foreign)


def _dirty_rel_paths(dirty_snapshot_text):
    """Repo-relative paths named by a `git status --porcelain` style snapshot
    (a rename line keeps the NEW path, the reading fill_clean_baselines needs)."""
    out = []
    for ln in (dirty_snapshot_text or "").split("\n"):
        if len(ln) > 3:
            out.append(ln[3:].split(" -> ")[-1].strip().strip('"'))
    return out


def fill_clean_baselines(meta, root, rel_paths):
    """Baselines for files CLEAN at dispatch (absent from baseline_dirty_snapshot):
    their dispatch-time bytes ARE the baseline_head_sha blob (read-only
    rev-parse; a path not in that tree and not dirty/untracked at baseline is
    'absent'). Dirty files keep ONLY an explicitly supplied blob -- never
    guessed."""
    dirty = set(_dirty_rel_paths(meta.get("baseline_dirty_snapshot")))
    head = meta.get("baseline_head_sha")
    out = dict(meta.get("baselines") or {})
    for rel in rel_paths:
        ap_ = abs_event_path(root, rel)
        if ap_ in out or rel in dirty or not head:
            continue
        r = subprocess.run(["git", "-C", root, "rev-parse", "--verify", "-q", f"{head}:{rel}"],
                           capture_output=True, text=True, env=_clean_env())
        out[ap_] = r.stdout.strip() if r.returncode == 0 else aj.ABSENT
    return out


def abs_event_path(root, rel):
    return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(root, rel))


# ------------------------------------------------- lane-agnostic consumer gate

def ledger_structural_verdict(path, *, root=None, journal_dir=None, gitdir=None, task_id=None):
    """Lane-agnostic ledger verdict for ONE path, for a consumer that is
    switching off the self-reported ("replay owned_edits hunks, compare to
    disk") judgment, without per-task lane metadata (no dispatcher records any
    yet, so no `agent_id -> task_id` map or dispatch-time baseline exists for
    any real task today).

    Without that map every event is foreign, so WHOLE_FILE_ELIGIBLE /
    SYNTHESIZED_STAGE can never be reached here -- this never claims
    ownership, only structure. The baseline attempted is the CURRENT git HEAD
    blob (not a dispatch-time capture), so a chain that does not reach back
    to it returns INSUFFICIENT_COVERAGE ("coverage_window_starts_after_baseline"
    or "no_journal_events") rather than being treated as explained: chain
    continuity and a tail match only prove the journal's OWN window is
    self-consistent, never that it covers every byte back to the last commit
    (constraint 2 of the cutover task). A file absent from the journal
    entirely (it predates the ledger, or was never touched this session) is
    INSUFFICIENT_COVERAGE too -- never a block.

    The one verdict this CAN respect without any lane data is ENTANGLED via
    `order_not_determinable`: the chain's own edge structure (which does not
    depend on who owns what) has no provable walk from the baseline. That is
    a measured defect in the journal's own record for this path, not a
    judgment about ownership, so it is the only verdict callers should treat
    as blocking.
    """
    root = str(root or ROOT)
    gitdir = gitdir or aj.git_dir()
    events, _ = aj.read_all_journals(Path(journal_dir) if journal_dir else None)
    path_events = [e for e in events if e["path"] == path]
    head = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True,
                          text=True, env=_clean_env()).stdout.strip()
    rel = os.path.relpath(path, root) if os.path.isabs(path) else path
    meta = {"task_id": task_id or "ledger-judgment-unscoped",
            "baseline_head_sha": head, "baseline_dirty_snapshot": ""}
    meta["baselines"] = fill_clean_baselines(meta, root, [rel])
    task = task_from_metadata(meta)
    return adjudicate_file(path, path_events, task, gitdir=gitdir)


def ledger_blocks(path, **kw):
    """True only for a MEASURED structural conflict (ENTANGLED). Every other
    verdict -- including no journal evidence at all -- is non-blocking; see
    ledger_structural_verdict()'s docstring for why that is deliberate, not a
    gap."""
    return ledger_structural_verdict(path, **kw)["verdict"] == ENTANGLED
