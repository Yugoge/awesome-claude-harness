#!/usr/bin/env python3
"""Tests for the journal-based three-way staging adjudicator and the journal-backed
canonical aggregate view (Phase C; purely additive artifacts, nothing switched).

Covers the verdict set: clean / separable / entangled / ambiguous /
insufficient-coverage (+ not-task-file), the escalation record (E1-E7 properties),
and the view's canonical shape, shard cross-check and worst-of status fold.
Fixtures are hermetic: a throwaway bare object store; the live journal, repo
and index are never touched.

Run: python3 -m pytest hooks/tests/test_attribution_adjudicator.py
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


import attribution_adjudicator as adj  # noqa: E402
import attribution_aggregate_view as view  # noqa: E402

BASE = "".join(f"line{i}\n" for i in range(1, 11))


class Fx:
    """throwaway odb + event factory"""

    def __init__(self, tmp):
        self.gd = str(tmp / "odb.git")
        subprocess.run(["git", "init", "--bare", "-q", self.gd], check=True)
        self.ts = 1000.0
        self.seq = {}
        self.events = []

    def blob(self, text):
        if text is None:
            return "absent"
        r = subprocess.run(["git", "--git-dir", self.gd, "hash-object", "-w", "--stdin"],
                           input=text.encode(), capture_output=True, check=True)
        return r.stdout.decode().strip()

    def ev(self, path, pre, post, agent, session="s1", dup_of=None):
        self.ts += 1
        n = self.seq[session] = self.seq.get(session, 0) + 1
        e = {"session_id": session, "seq": n, "path": path, "pre_sha": self.blob(pre) if not pre or len(pre) != 40 else pre,
             "post_sha": self.blob(post), "ts": self.ts, "tool": "Edit", "invocation_id": f"{session}-{n}"}
        if agent:
            e["agent_id"] = agent
        self.events.append(e)
        return e

    def task(self, path, baseline_text, agents=("T",), foreign=None):
        return adj.TaskSpec("task-1", agents, baselines={path: self.blob(baseline_text)},
                            foreign_agents=foreign or {"F": "task-2"})


def edit(text, n, new):
    lines = text.split("\n")
    lines[n - 1] = new
    return "\n".join(lines)


P = "/repo/f.txt"


def run(fx, task, text_disk, **kw):
    return adj.adjudicate_file(P, [e for e in fx.events if e["path"] == P], task, gitdir=fx.gd,
                               disk_sha=fx.blob(text_disk), **kw)


@pytest.fixture
def fx(tmp_path):
    return Fx(tmp_path)


# ---------------------------------------------------------------- clean

def test_clean_whole_file_when_every_edge_is_the_tasks(fx):
    b1 = edit(BASE, 1, "T1")
    b2 = edit(b1, 5, "T5")
    fx.ev(P, BASE, b1, "T")
    fx.ev(P, b1, b2, "T", session="s2")
    r = run(fx, fx.task(P, BASE), b2)
    assert r["verdict"] == adj.WHOLE and r["stage_blob"] == fx.blob(b2)
    assert r["owned_edges"] == ["s1#1", "s2#1"]


def test_file_the_task_never_touched_is_not_task_file(fx):
    b1 = edit(BASE, 1, "F1")
    fx.ev(P, BASE, b1, "F")
    assert run(fx, fx.task(P, BASE), b1)["verdict"] == adj.NOT_TASK


def test_event_without_agent_id_is_never_the_tasks(fx):
    b1 = edit(BASE, 1, "main")
    fx.ev(P, BASE, b1, None)
    assert run(fx, fx.task(P, BASE), b1)["verdict"] == adj.NOT_TASK


# ---------------------------------------------------------------- separable

def test_interleaved_but_separable_synthesizes_task_only_content(fx):
    t1 = edit(BASE, 1, "T1")
    f1 = edit(t1, 10, "F10")
    t2 = edit(f1, 5, "T5")
    fx.ev(P, BASE, t1, "T")
    fx.ev(P, t1, f1, "F", session="s2")
    fx.ev(P, f1, t2, "T")
    r = run(fx, fx.task(P, BASE), t2)
    assert r["verdict"] == adj.SYNTH, r
    want = edit(edit(BASE, 1, "T1"), 5, "T5")
    assert r["stage_content"].decode() == want            # the foreign line10 edit is NOT in it
    assert "F10" not in r["stage_content"].decode() and "F10" in t2
    assert r["foreign_edges"] == ["s2#1"] and r["stage_content_sha"] == fx.blob(want)


# ---------------------------------------------------------------- entangled + escalation

def _entangled_fixture(fx):
    t1 = edit(BASE, 3, "T3")
    f1 = edit(t1, 3, "F3")                    # foreign rewrites the very line the task wrote
    fx.ev(P, BASE, t1, "T", session="s1")
    fx.ev(P, t1, f1, "F", session="s2")
    return f1


def test_same_region_double_edit_is_entangled_and_never_resolved(fx):
    f1 = _entangled_fixture(fx)
    r = run(fx, fx.task(P, BASE), f1)
    assert r["verdict"] == adj.ENTANGLED
    assert "stage_content" not in r and "stage_blob" not in r      # no side selected, nothing staged
    assert sorted(r["conflicting_pair"]["edges"]) == ["s1#1", "s2#1"]


def test_escalation_record_properties_e1_to_e7(fx, tmp_path):
    f1 = _entangled_fixture(fx)
    r = run(fx, fx.task(P, BASE), f1, escalation_dir=str(tmp_path / "esc"))
    rec = r["escalation"]
    # E1 distinct, resolvable, non-anonymous claimants
    ids = [c["claimant_id"] for c in rec["claimants"]]
    assert len(ids) == 2 and len(set(ids)) == 2 and rec["E1_satisfied"]
    assert all(c["session_id"] and c["task_id"] for c in rec["claimants"])
    # E2 region by content, overlap-inclusive count, bound image, advisory line numbers
    cr = rec["contested_region"]
    assert "line3" in cr["anchor"] and cr["anchor_uniqueness"] == {"count": 1, "counting": "overlap_inclusive"}
    assert cr["bound_image_id"] == fx.blob(BASE) and cr["line_numbers"]["advisory"] is True
    # E3 one version per claimant, content-addressed + inline excerpt
    assert len(rec["versions"]) == 2
    for v in rec["versions"]:
        assert len(v["object_id"]) == 40 and v["excerpt"]
    assert any("T3" in v["excerpt"] for v in rec["versions"]) and any("F3" in v["excerpt"] for v in rec["versions"])
    # E4 literal, repeated in the rendered message
    assert "NOTHING HAS BEEN DISCARDED" in rec["no_selection_and_no_discard"]
    assert rec["rendered_message"].count(rec["no_selection_and_no_discard"]) == 2
    # E5 exactly one preview per claimant, keyed on claim_ref, distinct digests, derived record id
    assert [p["claim_ref"] for p in rec["if_chosen"]] == [c["claim_ref"] for c in rec["claimants"]]
    assert len({p["preview_digest"] for p in rec["if_chosen"]}) == 2
    assert len({p["summary"] for p in rec["if_chosen"]}) == 2
    assert all(rec["claimants"][i]["claimant_id"] not in rec["if_chosen"][i]["summary"] for i in (0, 1))
    assert rec["if_chosen"][0]["omitted_identical_bytes"] == 0
    # E6 durable ledger entry; ref half honestly NOT claimed
    saved = json.loads(Path(r["escalation_path"]).read_text())
    assert saved["conflict_record_id"] == rec["conflict_record_id"]
    assert rec["persistence"]["ref_persisted"] is False
    # E7 region-scoped
    assert rec["scope"]["kind"] == "region" and rec["scope"]["path"] == P


def test_record_id_is_derived_not_constant(fx, tmp_path):
    f1 = _entangled_fixture(fx)
    a = run(fx, fx.task(P, BASE), f1)["escalation"]["conflict_record_id"]
    fx2 = Fx(tmp_path / "x") if (tmp_path / "x").mkdir() is None else None
    t1 = edit(BASE, 7, "T7")
    f2 = edit(t1, 7, "F7")
    fx2.ev(P, BASE, t1, "T")
    fx2.ev(P, t1, f2, "F", session="s2")
    b = run(fx2, fx2.task(P, BASE), f2)["escalation"]["conflict_record_id"]
    assert a != b


def test_escalation_ref_persists_and_is_independently_readable(fx):
    f1 = _entangled_fixture(fx)
    r = run(fx, fx.task(P, BASE), f1, escalation_store=fx.gd)
    rec = r["escalation"]
    assert rec["persistence"]["ref_persisted"] is True
    ref = rec["persistence"]["ref"]
    assert ref == f"{adj.PENDING_CONFLICT_REF_NAMESPACE}/{rec['conflict_record_id']}"
    assert "ref_note" not in rec["persistence"]
    # independently readable: no --escalation-dir JSON ledger was ever supplied, only the ref
    out = subprocess.run(["git", "--git-dir", fx.gd, "cat-file", "-p", f"{ref}:record.json"],
                         capture_output=True, text=True, check=True)
    reread = json.loads(out.stdout)
    assert reread["conflict_record_id"] == rec["conflict_record_id"]
    assert reread["claimants"] == rec["claimants"]
    tree = subprocess.run(["git", "--git-dir", fx.gd, "ls-tree", "-r", ref],
                          capture_output=True, text=True, check=True).stdout
    for v in rec["versions"]:
        assert v["object_id"] in tree                        # every claimant's version blob stays reachable
    assert fx.blob(BASE) in tree                              # the baseline blob is kept reachable too


def test_escalation_ref_is_opt_in_and_off_by_default(fx):
    f1 = _entangled_fixture(fx)
    r = run(fx, fx.task(P, BASE), f1)
    assert r["escalation"]["persistence"]["ref_persisted"] is False
    assert "ref" not in r["escalation"]["persistence"]
    assert "escalation_store" in r["escalation"]["persistence"]["ref_note"]


def test_escalation_ref_rewrite_of_the_same_record_is_idempotent(fx):
    f1 = _entangled_fixture(fx)
    r1 = run(fx, fx.task(P, BASE), f1, escalation_store=fx.gd)
    r2 = run(fx, fx.task(P, BASE), f1, escalation_store=fx.gd)
    assert r1["escalation"]["persistence"]["ref"] == r2["escalation"]["persistence"]["ref"]
    assert r2["escalation"]["persistence"]["ref_persisted"] is True


def test_escalation_ref_refuses_to_clobber_a_different_pending_record(fx):
    stored, err = adj.persist_escalation_ref({"conflict_record_id": "deadbeef", "versions": []}, fx.gd)
    assert stored and err is None
    stored2, err2 = adj.persist_escalation_ref(
        {"conflict_record_id": "deadbeef", "versions": [],
         "contested_region": {"bound_image_id": fx.blob(BASE)}},     # same id, DIFFERENT content
        fx.gd)
    assert stored2 is None and "DIFFERENT pending record" in err2


def test_view_threads_escalation_store_into_the_adjudicator(fx):
    p = f"{R}/c.txt"
    t1 = edit(BASE, 3, "T3")
    f1 = edit(t1, 3, "F3")
    fx.ev(p, BASE, t1, "T")
    fx.ev(p, t1, f1, "F", session="s2")
    view.build_view(fx.events, _meta(fx, {p: BASE}), root=R, gitdir=fx.gd, disk_shas={p: fx.blob(f1)},
                    escalation_store=fx.gd)
    refs = subprocess.run(["git", "--git-dir", fx.gd, "for-each-ref", adj.PENDING_CONFLICT_REF_NAMESPACE],
                          capture_output=True, text=True, check=True).stdout
    assert refs.strip() != ""                     # the view's escalation_store reached the adjudicator


def test_unresolvable_foreign_task_is_disclosed_not_invented(fx):
    f1 = _entangled_fixture(fx)
    rec = run(fx, fx.task(P, BASE, foreign={"Z": "task-9"}), f1)["escalation"]
    assert rec["E1_satisfied"] is False and rec["E1_note"]
    assert any(c["task_id"] is None and c["resolvable"] is False for c in rec["claimants"])


def test_adjacent_edits_fail_closed(fx):
    t1 = edit(BASE, 3, "T3")
    f1 = edit(t1, 4, "F4")
    fx.ev(P, BASE, t1, "T")
    fx.ev(P, t1, f1, "F", session="s2")
    assert run(fx, fx.task(P, BASE), f1)["verdict"] == adj.ENTANGLED


# ---------------------------------------------------------------- ambiguous

def test_decisive_ambiguous_edge_is_entangled_not_owned(fx):
    t1 = edit(BASE, 2, "X2")
    fx.ev(P, BASE, t1, "T", session="s1")
    fx.ev(P, BASE, t1, "F", session="s2")       # same transition recorded by another identity
    r = run(fx, fx.task(P, BASE), t1)
    assert r["verdict"] == adj.ENTANGLED and r["reason"] == "ambiguous_writer_decisive"
    assert sorted(r["conflicting_pair"]["edges"]) == ["s1#1", "s2#1"]
    assert "stage_blob" not in r                       # never counted as the task's


def test_spanning_window_edge_by_a_task_identity_is_decisive(fx):
    a1 = edit(BASE, 1, "A")
    a2 = edit(a1, 9, "B")
    fx.ev(P, BASE, a1, "F", session="s2")
    fx.ev(P, a1, a2, "F", session="s2")
    fx.ev(P, BASE, a2, "T", session="s1")          # task window spans two foreign steps
    r = run(fx, fx.task(P, BASE), a2)
    assert r["verdict"] == adj.ENTANGLED and r["reason"] == "ambiguous_writer_decisive"


def test_ambiguity_with_no_task_witness_is_just_foreign(fx):
    t1 = edit(BASE, 1, "T1")
    f1 = edit(t1, 10, "F10")
    fx.ev(P, BASE, t1, "T", session="s1")
    fx.ev(P, t1, f1, "F", session="s2")
    fx.ev(P, t1, f1, "G", session="s3")             # two foreign identities saw the same transition
    r = run(fx, fx.task(P, BASE), f1)
    assert r["verdict"] == adj.SYNTH and r["stage_content"].decode() == t1


# ---------------------------------------------------------------- insufficient coverage

def test_coverage_starting_after_baseline_is_insufficient_not_entangled(fx):
    mid = edit(BASE, 5, "pre-journal edit")
    b1 = edit(mid, 1, "T1")
    fx.ev(P, mid, b1, "T")                            # first event's pre != task baseline
    r = run(fx, fx.task(P, BASE), b1)
    assert r["verdict"] == adj.INSUFFICIENT and r["reason"] == "coverage_window_starts_after_baseline"
    assert "escalation" not in r


def test_chain_break_is_insufficient(fx):
    b1, b2, b3 = edit(BASE, 1, "a"), edit(BASE, 2, "b"), edit(BASE, 3, "c")
    fx.ev(P, BASE, b1, "T")
    fx.ev(P, b2, b3, "T")                              # an unjournaled write between
    r = run(fx, fx.task(P, BASE), b3)
    assert r["verdict"] == adj.INSUFFICIENT and r["reason"] == "chain_break"


def test_tail_not_matching_disk_is_insufficient(fx):
    b1 = edit(BASE, 1, "a")
    fx.ev(P, BASE, b1, "T")
    r = run(fx, fx.task(P, BASE), edit(b1, 2, "unjournaled"))
    assert r["verdict"] == adj.INSUFFICIENT and r["reason"] == "tail_mismatch_unjournaled_write"


def test_no_events_and_missing_baseline_are_insufficient(fx):
    assert run(fx, fx.task(P, BASE), BASE)["reason"] == "no_journal_events"
    fx.ev(P, BASE, edit(BASE, 1, "a"), "T")
    t = adj.TaskSpec("t", {"T"}, baselines={})
    assert run(fx, t, edit(BASE, 1, "a"))["reason"] == "baseline_blob_unresolved"


def test_missing_blob_in_odb_is_insufficient_for_interleaved_file(fx):
    t1 = edit(BASE, 1, "T1")
    f1 = edit(t1, 10, "F10")
    fx.ev(P, BASE, t1, "T")
    fx.ev(P, t1, f1, "F", session="s2")
    fx.events[0]["post_sha"] = "0" * 40
    fx.events[1]["pre_sha"] = "0" * 40
    r = run(fx, fx.task(P, BASE), f1)
    assert r["verdict"] == adj.INSUFFICIENT and r["reason"] == "blob_unavailable"


def test_verdicts_are_pairwise_distinct_categories():
    assert len(set(adj.VERDICTS)) == 5 and adj.ENTANGLED != adj.INSUFFICIENT


# ---------------------------------------------------------------- dispatch-time baseline capture

def _git_repo(tmp_path, name="repo"):
    repo = tmp_path / name
    repo.mkdir()
    g = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                  check=True, capture_output=True, text=True)
    g("init", "-q")
    return repo, g


def test_capture_dispatch_baselines_hashes_current_dirty_bytes(tmp_path, monkeypatch):
    repo, g = _git_repo(tmp_path)
    (repo / "a.txt").write_text(BASE)
    g("add", "a.txt")
    g("commit", "-q", "-m", "i")
    dirty_at_dispatch = edit(BASE, 1, "ALREADY DIRTY AT DISPATCH")
    (repo / "a.txt").write_text(dirty_at_dispatch)
    monkeypatch.setenv("ATTRIBUTION_GIT_DIR", str(repo / ".git"))
    captured = adj.capture_dispatch_baselines(str(repo), " M a.txt\n")
    key = str(repo / "a.txt")
    assert key in captured
    out = subprocess.run(["git", "--git-dir", str(repo / ".git"), "cat-file", "-p", captured[key]],
                         capture_output=True, text=True, check=True)
    assert out.stdout == dirty_at_dispatch                # written as a real blob, not guessed


def test_capture_dispatch_baselines_is_a_noop_for_an_empty_snapshot():
    assert adj.capture_dispatch_baselines("/repo", "") == {}
    assert adj.capture_dispatch_baselines("/repo", None) == {}


def test_capture_dispatch_baselines_marks_a_deleted_dirty_path_absent(tmp_path, monkeypatch):
    repo, _ = _git_repo(tmp_path)
    monkeypatch.setenv("ATTRIBUTION_GIT_DIR", str(repo / ".git"))
    captured = adj.capture_dispatch_baselines(str(repo), "D  gone.txt\n")
    assert captured[str(repo / "gone.txt")] == adj.aj.ABSENT


def test_dispatch_time_dirty_file_reaches_a_normal_verdict_once_baseline_is_captured(tmp_path, monkeypatch):
    """Without a dispatch-time baseline, a file already dirty when the task starts is
    stuck at INSUFFICIENT_COVERAGE/baseline_blob_unresolved forever (the same failure
    test_no_events_and_missing_baseline_are_insufficient exercises): fill_clean_baselines()
    refuses to guess it, by design. capture_dispatch_baselines() supplies the missing
    baseline so the SAME file reaches a normal verdict instead."""
    repo, g = _git_repo(tmp_path)
    (repo / "a.txt").write_text(BASE)
    g("add", "a.txt")
    g("commit", "-q", "-m", "i")
    f = Fx(tmp_path)
    f.gd = str(repo / ".git")
    path = str(repo / "a.txt")

    dirty_at_dispatch = edit(BASE, 1, "ALREADY DIRTY AT DISPATCH")
    (repo / "a.txt").write_text(dirty_at_dispatch)                      # dirty BEFORE dispatch
    monkeypatch.setenv("ATTRIBUTION_GIT_DIR", f.gd)
    captured = adj.capture_dispatch_baselines(str(repo), " M a.txt\n")  # <-- dispatch time
    assert captured[path] == f.blob(dirty_at_dispatch)

    final_text = edit(dirty_at_dispatch, 5, "T5")
    f.ev(path, dirty_at_dispatch, final_text, "T")                     # the task's first (only) edit
    (repo / "a.txt").write_text(final_text)

    without_baseline = adj.TaskSpec("t", {"T"}, baselines={})
    r_before = adj.adjudicate_file(path, f.events, without_baseline, gitdir=f.gd, disk_sha=f.blob(final_text))
    assert r_before["verdict"] == adj.INSUFFICIENT and r_before["reason"] == "baseline_blob_unresolved"

    with_baseline = adj.TaskSpec("t", {"T"}, baselines=captured)
    r_after = adj.adjudicate_file(path, f.events, with_baseline, gitdir=f.gd, disk_sha=f.blob(final_text))
    assert r_after["verdict"] == adj.WHOLE and r_after["stage_blob"] == f.blob(final_text)


# ---------------------------------------------------------------- CLI + no side effects

def test_cli_end_to_end_exit_codes_and_no_objects_written(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    g = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                  check=True, capture_output=True, text=True)
    g("init", "-q")
    (repo / "a.txt").write_text(BASE)
    g("add", "a.txt")
    g("commit", "-q", "-m", "i")
    head = g("rev-parse", "HEAD").stdout.strip()
    gd = str(repo / ".git")
    f = Fx(tmp_path)
    f.gd = gd
    p = str(repo / "a.txt")
    t1 = edit(BASE, 3, "T3")
    f.ev(p, BASE, t1, "T")
    (repo / "a.txt").write_text(t1)
    jd = tmp_path / "j"
    jd.mkdir()
    (jd / "s1.jsonl").write_text("\n".join(json.dumps(e) for e in f.events) + "\n")
    lanes = tmp_path / "lanes.json"
    lanes.write_text(json.dumps({"task_id": "t", "baseline_head_sha": head, "baseline_dirty_snapshot": "",
                                 "lanes": [{"lane": "l1", "agent_ids": ["T"]}]}))
    before = g("count-objects", "-v").stdout
    cli = [sys.executable, str(ROOT / "scripts" / "adjudicate-attribution-staging.py"), "--lanes", str(lanes),
           "--journal-dir", str(jd), "--git-dir", gd, "--repo-root", str(repo)]
    r = subprocess.run(cli, capture_output=True, text=True)
    out = json.loads(r.stdout)
    assert r.returncode == 0 and out["verdicts"][p]["verdict"] == adj.WHOLE
    assert g("count-objects", "-v").stdout == before          # adjudication wrote no object
    (repo / "a.txt").write_text(edit(t1, 5, "unjournaled"))
    r = subprocess.run(cli, capture_output=True, text=True)
    assert r.returncode == 10 and json.loads(r.stdout)["verdicts"][p]["verdict"] == adj.INSUFFICIENT


def test_cli_capture_dispatch_baselines_into_writes_merged_lanes_and_objects(tmp_path, monkeypatch):
    repo, g = _git_repo(tmp_path)
    (repo / "a.txt").write_text(BASE)
    g("add", "a.txt")
    g("commit", "-q", "-m", "i")
    head = g("rev-parse", "HEAD").stdout.strip()
    dirty_at_dispatch = edit(BASE, 1, "DIRTY")
    (repo / "a.txt").write_text(dirty_at_dispatch)
    lanes_in = tmp_path / "lanes-in.json"
    lanes_in.write_text(json.dumps({"task_id": "t", "baseline_head_sha": head,
                                    "baseline_dirty_snapshot": " M a.txt\n",
                                    "lanes": [{"lane": "l1", "agent_ids": ["T"]}]}))
    lanes_out = tmp_path / "lanes-out.json"
    monkeypatch.setenv("ATTRIBUTION_GIT_DIR", str(repo / ".git"))     # inherited by the child process
    cli = [sys.executable, str(ROOT / "scripts" / "adjudicate-attribution-staging.py"), "--lanes", str(lanes_in),
           "--repo-root", str(repo), "--capture-dispatch-baselines-into", str(lanes_out)]
    r = subprocess.run(cli, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(lanes_out.read_text())
    key = str(repo / "a.txt")
    assert key in out["baselines"]
    cat = subprocess.run(["git", "--git-dir", str(repo / ".git"), "cat-file", "-p", out["baselines"][key]],
                         capture_output=True, text=True, check=True)
    assert cat.stdout == dirty_at_dispatch
    assert out["task_id"] == "t" and out["baseline_head_sha"] == head     # rest of lane metadata preserved


# ---------------------------------------------------------------- aggregate view

CANON = {"request_id", "task_id", "baseline_head_sha", "baseline_dirty_snapshot", "dev_report_path",
         "parallel_workers", "dev", "blocking_issues", "recommendations", "owned_edits", "pre_edit_snapshots"}
R = "/repo_root"


def _meta(fx, files, agents=("T",)):
    return {"task_id": "task-1", "baseline_head_sha": "h", "baseline_dirty_snapshot": "",
            "lanes": [{"lane": "l1", "agent_ids": list(agents)}],
            "baselines": {p: fx.blob(t) for p, t in files.items()},
            "foreign_agents": {"F": "task-2"}}


def test_view_has_the_canonical_shape_and_replayable_hunks(fx):
    p = f"{R}/docs/a.md"
    t1 = edit(BASE, 1, "T1")
    t2 = edit(t1, 6, "T6")
    fx.ev(p, BASE, t1, "T")
    fx.ev(p, t1, t2, "T", session="s2")
    doc = view.build_view(fx.events, _meta(fx, {p: BASE}), root=R, gitdir=fx.gd, disk_shas={p: fx.blob(t2)})
    assert CANON <= set(doc) and doc["dev"]["status"] == "completed"
    assert doc["dev"]["files_modified"] == ["docs/a.md"] and doc["parallel_workers"] == ["l1"]
    hunks = doc["owned_edits"]["docs/a.md"]
    text = BASE
    for h in hunks:                                   # replay: anchors found uniquely, result == final bytes
        assert text.count(h["old"]) == 1
        text = text.replace(h["old"], h["new"])
    assert text == t2
    assert doc["pre_edit_snapshots"]["docs/a.md"].startswith("git-blob:" + fx.blob(BASE))
    json.dumps(doc)


def test_view_created_file_is_listed_as_created(fx):
    p = f"{R}/new.txt"
    fx.ev(p, None, "hello\n", "T")
    doc = view.build_view(fx.events, _meta(fx, {p: None}), root=R, gitdir=fx.gd, disk_shas={p: fx.blob("hello\n")})
    assert doc["dev"]["files_created"] == ["new.txt"] and doc["dev"]["files_modified"] == []


def test_view_unresolved_file_is_not_guessed_into_owned_edits(fx):
    p = f"{R}/c.txt"
    t1 = edit(BASE, 3, "T3")
    f1 = edit(t1, 3, "F3")
    fx.ev(p, BASE, t1, "T")
    fx.ev(p, t1, f1, "F", session="s2")
    doc = view.build_view(fx.events, _meta(fx, {p: BASE}), root=R, gitdir=fx.gd, disk_shas={p: fx.blob(f1)})
    assert "c.txt" not in doc["owned_edits"] and doc["dev"]["status"] == "needs_review"
    assert doc["journal_view"]["unresolved_files"][0]["verdict"] == adj.ENTANGLED


def test_shards_are_narrative_disagreements_listed_and_never_adjudicate(fx):
    p = f"{R}/a.txt"
    fx.ev(p, BASE, edit(BASE, 1, "T1"), "T")
    shard = {"dev": {"status": "completed", "files_modified": ["claimed-only.txt"],
                     "tasks_completed": [{"id": 1}]},
             "owned_edits": {"claimed-only.txt": [{"old": "x", "new": "y"}]},
             "recommendations": ["r1"]}
    doc = view.build_view(fx.events, _meta(fx, {p: BASE}), root=R, gitdir=fx.gd, shards={"l1": shard},
                          disk_shas={p: fx.blob(edit(BASE, 1, "T1"))})
    kinds = {(d["kind"], d.get("file")) for d in doc["journal_view"]["disagreements"]}
    assert ("declared_not_journaled", "claimed-only.txt") in kinds and ("journaled_not_declared", "a.txt") in kinds
    assert "claimed-only.txt" not in doc["owned_edits"]          # a declaration never adds ownership
    assert "a.txt" in doc["owned_edits"]                          # silence never removes it
    assert doc["dev"]["tasks_completed"] == [{"id": 1}] and doc["recommendations"] == ["r1"]


def test_shard_status_can_only_worsen_the_view(fx):
    p = f"{R}/a.txt"
    fx.ev(p, BASE, edit(BASE, 1, "T1"), "T")
    doc = view.build_view(fx.events, _meta(fx, {p: BASE}), root=R, gitdir=fx.gd,
                          shards={"l1": {"dev": {"status": "blocked"}}},
                          disk_shas={p: fx.blob(edit(BASE, 1, "T1"))})
    assert doc["dev"]["status"] == "blocked" and "blocked" in doc["dev"]["status_rationale"]


def test_view_missing_shard_is_a_listed_disagreement(fx):
    p = f"{R}/a.txt"
    fx.ev(p, BASE, edit(BASE, 1, "T1"), "T")
    doc = view.build_view(fx.events, _meta(fx, {p: BASE}), root=R, gitdir=fx.gd,
                          disk_shas={p: fx.blob(edit(BASE, 1, "T1"))})
    assert doc["journal_view"]["disagreements"][0]["kind"] == "shard_missing"


def test_view_ignores_other_tasks_files_and_journal_state(fx):
    p = f"{R}/other.txt"
    fx.ev(p, BASE, edit(BASE, 1, "F1"), "F")
    fx.ev(f"{R}/state/attribution-journal/journals/x.jsonl", "a", "b", "T")
    doc = view.build_view(fx.events, _meta(fx, {}), root=R, gitdir=fx.gd)
    assert doc["owned_edits"] == {} and doc["journal_view"]["file_verdicts"] == {}


def test_view_cli_refuses_to_overwrite_an_existing_report(tmp_path):
    out = tmp_path / "dev-report-x.json"
    out.write_text("{}")
    lanes = tmp_path / "l.json"
    lanes.write_text(json.dumps({"task_id": "t", "lanes": []}))
    jd = tmp_path / "j"
    jd.mkdir()
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "attribution-aggregate-view.py"), "--lanes", str(lanes),
                        "--journal-dir", str(jd), "--repo-root", str(tmp_path), "--output", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 2 and out.read_text() == "{}"
