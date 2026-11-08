#!/usr/bin/env python3
"""Tests for the journal-based three-way staging adjudicator (Phase C).

Covers the verdict set: clean / separable / entangled / ambiguous /
insufficient-coverage (+ not-task-file) and the escalation record (E1-E7 properties).
Fixtures are hermetic: a throwaway bare object store; the live journal, repo
and index are never touched.

Run: python3 -m pytest hooks/tests/test_attribution_adjudicator.py
"""
import importlib.util
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


def test_escalation_record_properties_e1_to_e7(fx):
    f1 = _entangled_fixture(fx)
    r = run(fx, fx.task(P, BASE), f1)
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
