"""`files_required_to_ship` must be sourced from the SHARD UNION, and an
unobtainable declaration must not be silently read as an empty one.

Two defects are covered here, both measured on cycle 20260809-013317 before the fix.

DEFECT 1 -- UNREACHABLE DECLARATION. The declaration for a fan-out cycle lives in
exactly one lane shard report. The stager read the category from the CANONICAL
aggregate. The canonical cannot carry it: `aggregate-dev-report.py::_build_aggregate`
emits a fixed set of list keys that excludes it, and the resolver's freshness check
compares the whole enclosing `dev` object (`_canonical_projection` selects `"dev"`),
so writing the key into the canonical flips `canonical_fresh` to False and raises
STALE_CANONICAL. The canonical route is therefore closed, and the declared path was
invisible to the stager on every fan-out cycle -- excluded from the commit as a
`foreign_session_candidate`.

DEFECT 2 -- ABSENCE CONFLATED WITH EMPTINESS. The description said an absent key was
to be treated as an empty array, and reasoned that its hard-error posture was
quantified over declared paths so an absent key gave it nothing to fire on. That is
internally consistent and operationally useless: it guaranteed the abort could never
fire for any cycle not already carrying the key -- which is every fan-out cycle. An
explicit empty declaration is a positive statement that nothing is required; an
inability to establish a declaration at all is a statement of nothing and must not be
read as permission to proceed. The fail-closed posture belongs on the DERIVATION.

STRENGTH OF THIS EVIDENCE -- read before trusting a green run. The tests split into
two kinds and they are NOT equally strong:

  * The `test_doc_*` tests inspect PROSE executed by a model. They verify the
    DESCRIPTION the stager reads is now correct and self-consistent. They do NOT and
    cannot verify the model's runtime staging behaviour; no assertion here proves a
    `git add` occurred or was withheld. This is the same caveat the sibling module
    `test_changelog_analyst_declaration_categories.py` states, and it is preserved
    here deliberately rather than quietly upgraded.

  * The `test_lib_*` tests execute `scripts/lib/candidate_tree.py` for real. These
    are ordinary executable assertions about the wired-up derivation: the mechanism
    the prose now points at genuinely returns the declared path, genuinely
    distinguishes an empty declaration from an underivable one, and genuinely raises
    on each condition the prose names as the abort case.
"""

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGER_DOC = REPO_ROOT / "agents" / "changelog-analyst.md"

sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
import candidate_tree as ct  # noqa: E402

CATEGORY = "files_required_to_ship"
CYCLE_TASK_ID = "20260809-013317"
CYCLE_REPORTS_DIR = REPO_ROOT / "docs" / "dev"
CYCLE_DECLARED_PATH = "scripts/overnight-inplace-env.sh"


@pytest.fixture(scope="module")
def doc():
    assert STAGER_DOC.is_file(), "stager description missing at %s" % STAGER_DOC
    return STAGER_DOC.read_text(encoding="utf-8")


def _window(text, anchor, before=0, after=1600):
    idx = text.find(anchor)
    assert idx != -1, "anchor vanished from the stager description: %r" % anchor
    return text[max(0, idx - before): idx + after]


# --- DEFECT 1: the declaration source ---------------------------------------


def test_doc_sources_the_category_from_the_shard_union(doc):
    """Naming the library is the whole fix; without it the category is unreachable."""
    window = _window(doc, "**Sourcing the item-3 declaration")
    assert "scripts/lib/candidate_tree.py" in window, (
        "the sourcing note must name the library that discovers the shards; "
        "otherwise the stager has no stated way to reach a fan-out declaration")
    assert "derive_declaration" in window, "the derivation entry point must be named"
    assert CATEGORY in window


def test_doc_records_why_the_canonical_route_is_closed(doc):
    """A future editor who does not know this will 'simplify' it back to the canonical."""
    window = _window(doc, "**Sourcing the item-3 declaration")
    assert "STALE_CANONICAL" in window, (
        "the note must record the measured consequence of the canonical route, "
        "or the dead route looks like a live option")


def test_doc_no_enumeration_site_reads_this_category_from_the_canonical(doc):
    """The bug was a SOURCE bug; it recurs the moment any site reads the canonical."""
    # Prose wraps, so the exculpating clause ("the canonical CANNOT carry it") often
    # lands on the next physical line. The neighbourhood, not the line, is the
    # semantic unit; checking per-line would flag correct wrapped prose.
    lines = doc.splitlines()
    offenders = []
    for i, line in enumerate(lines):
        if CATEGORY not in line or "canonical" not in line.lower():
            continue
        neighbourhood = " ".join(lines[max(0, i - 1): i + 3])
        # Text that says the canonical CANNOT carry it is the desired state.
        if re.search(r"cannot|never|not from|not read|closed|stale|shard.union",
                     neighbourhood, re.I):
            continue
        offenders.append(line.strip())
    assert not offenders, (
        "a site still sources %s from the canonical: %r" % (CATEGORY, offenders))


# --- DEFECT 2: absence is not emptiness -------------------------------------


def test_doc_states_the_absent_versus_empty_rule(doc):
    window = _window(doc, "**An unobtainable declaration is not an empty one.**")
    assert "Derivation succeeds, union empty" in window
    assert "Derivation is impossible" in window
    assert "MUST NOT abort" in window, (
        "the empty case must be explicitly non-aborting, or the naive fail-closed "
        "reading breaks every cycle with nothing to declare")
    assert "ABORT" in window, "the impossible case must abort"


def test_doc_does_not_treat_an_unobtainable_declaration_as_empty(doc):
    """The exact reasoning that made the hard-error posture unreachable."""
    window = _window(doc, "**An unobtainable declaration is not an empty one.**", after=2400)
    assert not re.search(r"treat an absent .{0,40} as an empty\s+array", window, re.S), (
        "the absent-key-means-empty-array conflation is back")
    assert "the derivation, not on the key" in window, (
        "the rule must say where the fail-closed posture sits, or it reads as a "
        "restatement of the defect")


# --- the wired mechanism, executed for real ---------------------------------
#
# GUARD RULE for the tests below that read this cycle's real reports: skip unless
# EVERY report they read is present -- the canonical, and every lane shard the
# canonical itself names. Guarding on `CYCLE_REPORTS_DIR.is_dir()` asked a weaker
# question than the bodies ask. These reports live under version-control-ignored
# `docs/dev/`, so the tree this cycle SHIPS carries a PARTIAL copy of that
# directory -- only the artifacts some lane declared. The directory therefore
# exists, the weak guard declines to skip, and the bodies fail there: one on the
# absent canonical, one on a union assembled from the single surviving shard.
# The lane set is read from the cycle's own `parallel_workers` record rather than
# hardcoded, so a new lane is required automatically.


def _cycle_reports_complete():
    """True when the canonical AND every lane shard it names are readable here.

    A canonical that is present but records no lane set returns True on purpose:
    that tree is malformed, not foreign, and skipping there would hide the very
    regression these tests exist to catch. Only ABSENCE means "not this tree".
    """
    canonical = CYCLE_REPORTS_DIR / ("dev-report-%s.json" % CYCLE_TASK_ID)
    if not canonical.is_file():
        return False
    lanes = json.loads(canonical.read_text(encoding="utf-8")).get("parallel_workers")
    if not isinstance(lanes, list) or not lanes:
        return True
    return all(
        (CYCLE_REPORTS_DIR / ("dev-report-%s-%s.json" % (CYCLE_TASK_ID, lane))).is_file()
        for lane in lanes)


CYCLE_REPORTS_INCOMPLETE = (
    "this cycle's reports are not all present here; they are version-control "
    "ignored, and a shipped tree carries only the ones some lane declared")


def test_lib_derives_this_cycle_declaration_from_the_shards():
    """The previously-invisible path must be reachable through the wired route."""
    if not _cycle_reports_complete():
        pytest.skip(CYCLE_REPORTS_INCOMPLETE)
    decl = ct.derive_declaration(
        CYCLE_REPORTS_DIR, CYCLE_TASK_ID, fields=(CATEGORY,))
    assert CYCLE_DECLARED_PATH in decl.paths, (
        "the declared path is still not reachable through the shard union")


def test_lib_confirms_the_canonical_does_not_carry_the_category():
    """Guards the premise: if the canonical ever carries it, the fix's reason changed."""
    canonical = CYCLE_REPORTS_DIR / ("dev-report-%s.json" % CYCLE_TASK_ID)
    if not canonical.is_file():
        pytest.skip("cycle canonical absent (version-control ignored)")
    dev = json.loads(canonical.read_text(encoding="utf-8")).get("dev") or {}
    assert CATEGORY not in dev, (
        "the canonical now carries %s; re-measure the STALE_CANONICAL premise" % CATEGORY)


def _write_report(directory, name, baseline, dev_node):
    (directory / name).write_text(
        json.dumps({"baseline_head_sha": baseline, "dev": dev_node}), encoding="utf-8")


def test_lib_empty_declaration_derives_successfully_and_is_not_an_abort(tmp_path):
    """The legitimate cycle with nothing to declare must NOT be broken."""
    _write_report(tmp_path, "dev-report-T.json", "b" * 40, {"files_created": ["a.py"]})
    _write_report(tmp_path, "dev-report-T-one.json", "b" * 40, {"files_created": ["a.py"]})
    decl = ct.derive_declaration(tmp_path, "T", fields=(CATEGORY,))
    assert decl.paths == (), "an omitted key must derive to an empty declaration"


def test_lib_explicit_empty_list_also_derives_successfully(tmp_path):
    """An explicit [] is a positive statement that nothing is required."""
    _write_report(tmp_path, "dev-report-T.json", "b" * 40, {CATEGORY: []})
    decl = ct.derive_declaration(tmp_path, "T", fields=(CATEGORY,))
    assert decl.paths == ()


# The abort case, condition by condition. Each parameter is a condition the prose
# names; each must raise, or the prose promises an abort the mechanism cannot fire.


def test_lib_missing_reports_directory_is_impossible_not_empty(tmp_path):
    with pytest.raises(ct.DeclarationError):
        ct.derive_declaration(tmp_path / "no-such-dir", "T", fields=(CATEGORY,))


def test_lib_no_report_matching_task_id_is_impossible_not_empty(tmp_path):
    _write_report(tmp_path, "dev-report-OTHER.json", "b" * 40, {CATEGORY: ["x.py"]})
    with pytest.raises(ct.DeclarationError):
        ct.derive_declaration(tmp_path, "T", fields=(CATEGORY,))


def test_lib_unreadable_report_is_impossible_not_empty(tmp_path):
    (tmp_path / "dev-report-T.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ct.DeclarationError):
        ct.derive_declaration(tmp_path, "T", fields=(CATEGORY,))


def test_lib_non_list_category_is_impossible_not_empty(tmp_path):
    _write_report(tmp_path, "dev-report-T.json", "b" * 40, {CATEGORY: "one/path.sh"})
    with pytest.raises(ct.DeclarationError):
        ct.derive_declaration(tmp_path, "T", fields=(CATEGORY,))


def test_lib_no_recorded_baseline_is_impossible_not_empty(tmp_path):
    (tmp_path / "dev-report-T.json").write_text(
        json.dumps({"dev": {CATEGORY: ["x.py"]}}), encoding="utf-8")
    with pytest.raises(ct.DeclarationError):
        ct.derive_declaration(tmp_path, "T", fields=(CATEGORY,))


def test_lib_impossible_and_empty_are_distinguishable(tmp_path):
    """The distinction the fix rests on, asserted directly rather than implied."""
    empty_dir = tmp_path / "empty-decl"
    empty_dir.mkdir()
    _write_report(empty_dir, "dev-report-T.json", "b" * 40, {"files_created": []})
    assert ct.derive_declaration(empty_dir, "T", fields=(CATEGORY,)).paths == ()

    broken_dir = tmp_path / "broken-decl"
    broken_dir.mkdir()
    (broken_dir / "dev-report-T.json").write_text("{", encoding="utf-8")
    with pytest.raises(ct.DeclarationError):
        ct.derive_declaration(broken_dir, "T", fields=(CATEGORY,))


def test_lib_hard_error_posture_is_reachable_only_via_the_shard_union():
    """The posture could not fire before, because its subject was invisible.

    Item 3 aborts when a DECLARED path is absent from the working tree and from HEAD.
    Quantified over the canonical's (necessarily empty) declaration that abort has no
    subject and can never fire on a fan-out cycle. Quantified over the shard union it
    has one. This asserts the change of subject directly, on this cycle's real reports.
    """
    if not _cycle_reports_complete():
        pytest.skip(CYCLE_REPORTS_INCOMPLETE)
    canonical = CYCLE_REPORTS_DIR / ("dev-report-%s.json" % CYCLE_TASK_ID)
    canonical_dev = json.loads(canonical.read_text(encoding="utf-8")).get("dev") or {}

    from_canonical = canonical_dev.get(CATEGORY) or []
    from_shards = ct.derive_declaration(
        CYCLE_REPORTS_DIR, CYCLE_TASK_ID, fields=(CATEGORY,)).paths

    assert from_canonical == [], "premise changed: the canonical now declares something"
    assert from_shards, "the wired route yields no declaration; the posture is still inert"
    assert CYCLE_DECLARED_PATH in from_shards


def test_lib_abort_predicate_fires_on_a_declared_path_absent_from_the_tree(tmp_path):
    """Demonstrate the firing case, not merely that a subject exists.

    Self-contained on purpose: this owns the FIRING half and reads no cycle
    artifact, so it keeps EXECUTING in the shipped tree, where the complementary
    non-firing half below can only skip.
    """
    absent = "scripts/declared-but-never-written.sh"
    _write_report(tmp_path, "dev-report-T.json", "b" * 40, {"files_created": []})
    _write_report(tmp_path, "dev-report-T-lane.json", "b" * 40, {CATEGORY: [absent]})

    declared = ct.derive_declaration(tmp_path, "T", fields=(CATEGORY,)).paths
    assert declared == (absent,), "the shard union must carry the lane's declaration"

    # Item 3's abort predicate: declared AND absent from the working tree AND from HEAD.
    fired = [p for p in declared if not (REPO_ROOT / p).exists()]
    assert fired == [absent], (
        "the hard-error posture did not fire for a declared, nonexistent path")


def test_lib_abort_predicate_does_not_fire_on_this_cycle_declared_paths():
    """The non-firing half: the posture must NOT abort a commit that is good.

    Split out of the firing case above rather than guarded together with it. The
    two halves once shared one body, and the cycle-reading half is why that body
    failed in the shipped tree. Guarding the shared body would have converted the
    self-contained half to a skip there too, deleting the only half that can still
    run. Splitting keeps the firing half executing everywhere and confines the
    skip to the half that genuinely depends on this cycle's artifacts.
    """
    if not _cycle_reports_complete():
        pytest.skip(CYCLE_REPORTS_INCOMPLETE)
    real = ct.derive_declaration(
        CYCLE_REPORTS_DIR, CYCLE_TASK_ID, fields=(CATEGORY,)).paths
    assert [p for p in real if not (REPO_ROOT / p).exists()] == [], (
        "the posture fired on a path that is present; it would abort a good commit")


# --- the boundary that must NOT move ----------------------------------------
#
# The three document-level boundary guards — staging confined to declared files,
# membership still requiring a report, and no stage-all/force-add path — are NOT
# repeated here. They are asserted against the same prose anchors in the same
# target file by tests/test_changelog_analyst_declaration_categories.py, which
# owns them; one of the copies that stood here was AST-identical in body to its
# counterpart there. Two modules asserting one clause cannot disagree, so the
# duplicate bought no coverage and only added a second place to update.
#
# Do not re-add them here. If the boundary needs a new guard, put it in the
# module named above so there stays exactly one authority for it. The executable
# membership check below is deliberately kept: it exercises the derivation
# mechanism rather than the prose, so it is not a duplicate of anything there.


def test_lib_declaration_membership_still_comes_only_from_a_report(tmp_path):
    """An untracked file present on disk must not enter the declaration by existing."""
    (tmp_path / "undeclared.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    _write_report(tmp_path, "dev-report-T.json", "b" * 40, {CATEGORY: ["declared.sh"]})
    decl = ct.derive_declaration(tmp_path, "T", fields=(CATEGORY,))
    assert decl.paths == ("declared.sh",), (
        "a file present in the tree but named by no report entered the declaration")
