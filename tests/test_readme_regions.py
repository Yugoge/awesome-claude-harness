"""scripts/generate-hero-status.py: the six canonical regions of README.md and docs/status.md, where they sit,
and the numbers and names in the prose around them.

What is covered:

* each region is regenerated from code by --write into its own document (`commands` and `agents` in README.md;
  `proof`, `limits`, `disclosure`, `status` in docs/status.md), and --check byte-compares it, with the
  fail-closed rules: a claim row degrades to not-yet when its input is missing, a count region that cannot be
  computed fails the check naming the input and is never written;
* the proof table, cell by cell, including the cells that say what CI fails on only when readme_facts'
  ci_enforces says the assertion is there, and say what is NOT asserted otherwise;
* the commands table (by group, an optional module's own commands left out, the summaries never cut), the agents
  table, and the escaping of what a summary may hold;
* the two rows added with the status region, enforcement-strength and dead-end-sites;
* the position rule (each region in its document, inside its H2 section, the claim regions in order) that
  replaced the headline-adjacency and above-the-fold assertions, and the glyph-model drift that is still consumed;
* the number rule in both documents: no numeral typed by hand in the prose, except the README's declared cited
  figures; and no internal name on the front page;
* write mode refuses before it writes (regions overlapping, duplicated, out of order, outside their sections or
  their document, unknown markers, CRLF) and replaces each document atomically, keeping its mode, link and line
  endings, and touches neither when one is refused;
* the number rule fails closed on what would hide prose from it (a fence or comment never closed, a backtick
  that closes nothing) and no comment opener or closer inside code or a fence starts or ends a comment;
* the success line says when the glyph model was not measured;
* the real README.md and docs/status.md pass the check, and scripts/verify-claims.sh still runs the generator's
  check and the hero-provenance check.

The facts are derived once for the module (about 9 s: the blocking-site enumeration dominates) and cached in
the generator; a test that needs a different fact replaces it in that cache for its own duration. Nothing
here replays the replay suite or runs the artifact check.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "generate-hero-status.py"
VERIFY = REPO / "scripts" / "verify-claims.sh"

sys.dont_write_bytecode = True  # the module under test and the facts leave no __pycache__
_spec = importlib.util.spec_from_file_location("generate_hero_status_under_test", SCRIPT)
gen = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gen
_spec.loader.exec_module(gen)

(FIGURE_A, URL), (FIGURE_B, _URL_B) = gen.CITED_FIGURES[:2]
GLYPH_IMG = ('<p align="center"><a href="x.txt"><img src=".github/assets/guard-hero.svg" width="720" '
             'alt="the hero"></a></p>')

README_SKELETON = f"""# A harness

Intro paragraph with no number in it. A study of {FIGURE_A} pull requests waited a median of {FIGURE_B}
hours ([source]({URL})).

1. First step.
2. Second step.

## The command surface

Generated from the frontmatter.

{{commands}}

## The cast of agents

Generated from the frontmatter too.

{{agents}}

## Documentation

- [Installation](docs/installation.md)
"""

STATUS_SKELETON = f"""# Status

Intro paragraph with no number in it.

1. First step.
2. Second step.

## Measured proof

Counted from the repository.

{{proof}}

## Hero recording

{GLYPH_IMG}

## Status and known limits

Generated claim rows.

{{limits}}

{{disclosure}}

{{status}}

## Documentation

- [Installation](installation.md)
"""


class Docs(NamedTuple):
    readme: Path
    status: Path


REAL = Docs(REPO / "README.md", REPO / "docs" / "status.md")


def empty_region(rid: str) -> str:
    return f"{gen.BEGIN.format(rid=rid)}\n{gen.END.format(rid=rid)}"


def empties(doc: str) -> dict[str, str]:
    return {rid: empty_region(rid) for rid in gen.DOC_REGIONS[doc]}


def skeletons() -> dict[str, str]:
    return {"readme": README_SKELETON.format(**empties("readme")), "status": STATUS_SKELETON.format(**empties("status"))}


@pytest.fixture(autouse=True)
def _restore_document_paths():
    """cmd_write and cmd_check bind the generator's README_PATH and STATUS_PATH; give them back after each test."""
    saved = gen.README_PATH, gen.STATUS_PATH
    yield
    gen.README_PATH, gen.STATUS_PATH = saved


@pytest.fixture(scope="module")
def warm():
    """Every fact of the repository, derived once and cached by the generator."""
    regions, failed, rows = gen.expected_regions()
    assert not failed, failed
    return regions, rows


def write_docs(where: Path, readme: str, status: str) -> Docs:
    docs = Docs(where / "README.md", where / "status.md")
    docs.readme.write_text(readme, encoding="utf-8")
    docs.status.write_text(status, encoding="utf-8")
    return docs


@pytest.fixture(scope="module")
def scratch_texts(warm, tmp_path_factory):
    """A README and a status page with their regions under their sections, filled by write mode."""
    sk = skeletons()
    docs = write_docs(tmp_path_factory.mktemp("regions"), sk["readme"], sk["status"])
    assert gen.cmd_write(*docs) == 0
    return docs.readme.read_text(encoding="utf-8"), docs.status.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def readme_text(scratch_texts):
    return scratch_texts[0]


@pytest.fixture(scope="module")
def status_text(scratch_texts):
    return scratch_texts[1]


@pytest.fixture
def scratch(tmp_path, scratch_texts):
    return write_docs(tmp_path, *scratch_texts)


def run_check(docs: Docs, capsys, fold: bool = False):
    rc = gen.cmd_check(docs.readme, docs.status, check_fold=fold)
    out = capsys.readouterr()
    return rc, out.err, out.out


def region(text: str, rid: str) -> str:
    i, j = gen.region_span(text, rid)
    return text[i:j]


def cut(text: str, rid: str) -> str:
    i, j = gen.region_span(text, rid)
    return text[:i] + text[j:]


def rows_of(table: str) -> list[list[str]]:
    """The cells of a pipe table's body rows: split on pipes that are not escaped."""
    lines = [l for l in table.splitlines() if l.startswith("|")]
    return [[c.strip() for c in re.split(r"(?<!\\)\|", l.strip())[1:-1]] for l in lines[2:]]


def body(text: str, rid: str) -> str:
    return "\n".join(region(text, rid).splitlines()[1:-1])


def with_fact(monkeypatch, name: str, change=None, error: str | None = None):
    """Replace one fact in the generator's cache: a changed deep copy, or an error."""
    if error is not None:
        monkeypatch.setitem(gen._FACTS, name, gen.FactUnavailable(error))
        return None
    value = copy.deepcopy(gen.fact(name))
    change(value)
    monkeypatch.setitem(gen._FACTS, name, value)
    return value


# ================================================================ 1. each region is regenerated from code

def test_the_closed_sets_agree_on_the_regions_and_the_rows():
    assert gen.REGION_IDS == ("proof", "commands", "agents", "limits", "disclosure", "status")
    assert gen.CLAIM_REGIONS == ("limits", "disclosure", "status")
    assert gen.DOC_REGIONS == {"readme": ("commands", "agents"), "status": ("proof", "limits", "disclosure", "status")}
    assert sorted(r for rids in gen.DOC_REGIONS.values() for r in rids) == sorted(gen.REGION_IDS)  # each in one document
    assert gen.SECTION_OF == {"proof": "Measured proof", "commands": "The command surface",
                              "agents": "The cast of agents", "limits": "Status and known limits",
                              "disclosure": "Status and known limits", "status": "Status and known limits"}
    # the nine rows that existed keep their order; the two new ones are added to the closed set and its maps
    assert gen.ROW_IDS[:9] == ["known-limits", "hero-recording", "hero-legibility", "hero-glyph",
                               "supported-builds", "capability-check", "blackbox-tests", "release", "os"]
    assert gen.ROW_IDS[9:] == ["enforcement-strength", "dead-end-sites"]
    assert set(gen.PREDICATES) == set(gen.REGION_OF) == set(gen.ROW_IDS)
    assert gen.REGION_OF["enforcement-strength"] == gen.REGION_OF["dead-end-sites"] == "status"


def test_write_fills_all_six_regions_from_code_and_touches_nothing_else(tmp_path, warm):
    regions, _rows = warm
    sk = skeletons()
    docs = write_docs(tmp_path, sk["readme"], sk["status"])
    assert gen.cmd_write(*docs) == 0
    for doc, path in zip(("readme", "status"), docs):
        written, skeleton = path.read_text(encoding="utf-8"), sk[doc]
        for rid in gen.DOC_REGIONS[doc]:
            assert region(written, rid) == regions[rid], rid
            assert len(region(written, rid).splitlines()) > 2, f"{rid} was written empty"
        for rid in gen.DOC_REGIONS[doc]:  # outside the regions, byte for byte what it was
            skeleton, written = cut(skeleton, rid), cut(written, rid)
        assert written == skeleton, doc
    # writing again changes nothing: the regeneration is deterministic
    before = [p.read_bytes() for p in docs]
    assert gen.cmd_write(*docs) == 0 and [p.read_bytes() for p in docs] == before


def test_a_regenerated_readme_passes_the_check(scratch, capsys):
    rc, err, out = run_check(scratch, capsys)
    assert rc == 0, err
    assert "OK" in out and "11 rows" in out and "6 canonical regions" in out and "README.md and docs/status.md" in out


def test_each_claim_region_holds_its_rows_in_the_closed_order(status_text):
    ids = {rid: [m.group("id") for m in map(gen.MARKER_RE.match, region(status_text, rid).splitlines()) if m]
           for rid in gen.CLAIM_REGIONS}
    assert ids["limits"] == ["known-limits"]
    assert ids["disclosure"] == ["hero-recording", "hero-legibility", "hero-glyph"]
    assert ids["status"] == ["supported-builds", "capability-check", "blackbox-tests", "release", "os",
                             "enforcement-strength", "dead-end-sites"]
    assert sorted(i for r in gen.CLAIM_REGIONS for i in ids[r]) == sorted(gen.ROW_IDS)


def _no_facts(monkeypatch):
    """Write mode must refuse on the documents alone: deriving the facts is the expensive step."""
    def boom():
        raise AssertionError("the facts were derived for documents that write mode had to refuse")
    monkeypatch.setattr(gen, "expected_regions", boom)


def _only(path: Path) -> list[str]:
    """What the documents' directory holds: the two documents, and no temporary file."""
    return sorted(p.name for p in path.parent.iterdir())


BOTH = ["README.md", "status.md"]


def _overlap(text):  # limits' END marker moved below disclosure's BEGIN marker
    begin = gen.BEGIN.format(rid="disclosure")
    return text.replace(gen.END.format(rid="limits"), "").replace(begin, begin + "\n" + gen.END.format(rid="limits"))


def _duplicate_begin(text):  # a BEGIN pasted earlier than the real one
    return text.replace("## Measured proof\n", "## Measured proof\n\n" + gen.BEGIN.format(rid="status") + "\n", 1)


def _out_of_order(text):
    a, b = region(text, "limits"), region(text, "disclosure")
    return text.replace(a, "@@A@@").replace(b, a).replace("@@A@@", b)


def _outside_section(text):
    return cut(text, "limits").replace("## Measured proof\n", "## Measured proof\n\n" + region(text, "limits") + "\n", 1)


def _end_before_begin(text):
    begin, end = gen.BEGIN.format(rid="proof"), gen.END.format(rid="proof")
    return text.replace(begin, "@@").replace(end, begin).replace("@@", end)


def _agents_outside_section(text):
    return cut(text, "agents").replace("## Documentation\n", "## Documentation\n\n" + region(text, "agents") + "\n", 1)


@pytest.mark.parametrize("doc,mutate,fragments", [
    ("status", _overlap, ["region 'limits' overlaps region 'disclosure'"]),
    ("status", _duplicate_begin, ["region 'status' is duplicated"]),
    ("status", _out_of_order, ["region 'limits' is out of order", "region 'disclosure' is out of order"]),
    ("status", _outside_section, ["region 'limits' lies outside the H2 section 'Status and known limits'"]),
    ("status", _end_before_begin, ["region 'proof' has 1 BEGIN and 1 END markers, but not a BEGIN followed by an END"]),
    ("readme", lambda t: t.replace(gen.BEGIN.format(rid="commands"), ""), ["README.md: [region-position] region 'commands'"]),
    ("readme", _agents_outside_section, ["region 'agents' lies outside the H2 section 'The cast of agents'"]),
    ("status", lambda t: t + "\n" + gen.BEGIN.format(rid="extra") + "\n", ["names region 'extra'"]),
    ("status", lambda t: t + "\n" + empty_region("commands") + "\n",
     ["docs/status.md: [region-position] a BEGIN marker of region 'commands' is in docs/status.md; the region belongs in README.md"]),
    ("status", lambda t: t.replace("\n", "\r\n"), ["[line-endings] line 1 of docs/status.md", "carriage return",
                                                    "a CRLF document is refused"]),
    ("readme", lambda t: t.replace("\n", "\r\n"), ["[line-endings] line 1 of README.md"]),
], ids=["overlap", "duplicate-begin", "out-of-order", "outside-section", "end-before-begin", "missing-begin",
        "agents-outside-section", "unknown-region", "other-documents-region", "crlf", "crlf-readme"])
def test_write_refuses_documents_whose_regions_are_not_where_they_must_be(tmp_path, scratch_texts, capsys, monkeypatch,
                                                                          doc, mutate, fragments):
    """A span replaced where it overlaps another, or is not where it was taken to be, deletes the prose between
    them; write mode used to exit 0 on each of these and drop dozens of lines. Neither document is touched."""
    texts = dict(zip(("readme", "status"), scratch_texts))
    broken = mutate(texts[doc])
    assert broken != texts[doc]
    texts[doc] = broken
    docs = Docs(tmp_path / "README.md", tmp_path / "status.md")
    for d, path in zip(("readme", "status"), docs):
        path.write_bytes(texts[d].encode("utf-8"))
    _no_facts(monkeypatch)
    assert gen.cmd_write(*docs) == 1
    err = capsys.readouterr().err
    assert all(f in err for f in fragments), err
    assert "write refused" in err and err.count("was NOT touched") == 2
    for d, path in zip(("readme", "status"), docs):
        assert path.read_bytes() == texts[d].encode("utf-8")
    assert _only(docs.readme) == BOTH


def test_write_refuses_a_readme_that_lacks_a_regions_markers_before_deriving_anything(tmp_path, monkeypatch):
    sk = skeletons()
    text = sk["readme"].replace(gen.BEGIN.format(rid="commands"), "")
    docs = write_docs(tmp_path, text, sk["status"])
    _no_facts(monkeypatch)
    assert gen.cmd_write(*docs) == 1
    assert docs.readme.read_text(encoding="utf-8") == text and docs.status.read_text(encoding="utf-8") == sk["status"]


def test_write_replaces_each_document_through_a_temporary_file_beside_it(tmp_path, scratch_texts, monkeypatch):
    readme, status = scratch_texts
    stale = status.replace(region(status, "proof"), empty_region("proof"))
    docs = write_docs(tmp_path, readme, stale)
    seen, real = [], os.replace

    def spy(src, dst):
        seen.append(dict(src=Path(src), dst=Path(dst), src_text=Path(src).read_text(encoding="utf-8"),
                         dst_text=Path(dst).read_text(encoding="utf-8")))
        return real(src, dst)
    monkeypatch.setattr(os, "replace", spy)
    assert gen.cmd_write(*docs) == 0
    assert [c["dst"] for c in seen] == [docs.readme, docs.status]
    for call in seen:
        assert call["src"].parent == call["dst"].parent == tmp_path and call["src"] != call["dst"]
    assert seen[1]["dst_text"] == stale  # the status page itself was not touched until the rename
    assert seen[1]["src_text"] == docs.status.read_text(encoding="utf-8") == status  # and the new one was whole by then
    assert seen[0]["src_text"] == readme
    assert _only(docs.readme) == BOTH


@pytest.mark.parametrize("where", ["replace", "fsync"])
def test_a_failure_while_writing_leaves_the_documents_whole_and_no_temporary_file(tmp_path, scratch_texts, monkeypatch, where):
    """A full disk (fsync) or a failed rename must not leave a document empty or partial."""
    readme, status = scratch_texts
    stale = status.replace(region(status, "proof"), empty_region("proof"))
    docs = write_docs(tmp_path, readme, stale)

    def fail(*_args):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(os, where, fail)
    with pytest.raises(OSError, match="No space"):
        gen.cmd_write(*docs)
    monkeypatch.undo()
    assert docs.status.read_text(encoding="utf-8") == stale and docs.readme.read_text(encoding="utf-8") == readme
    assert _only(docs.readme) == BOTH


def test_write_keeps_the_mode_the_link_and_the_line_endings(tmp_path, scratch_texts):
    readme, status = scratch_texts
    stale = status.replace(region(status, "proof"), empty_region("proof"))
    real = tmp_path / "docs" / "status.md"
    real.parent.mkdir()
    real.write_text(stale.rstrip("\n"), encoding="utf-8")  # no final newline
    real.chmod(0o640)
    link = tmp_path / "status.md"
    link.symlink_to(real)
    (tmp_path / "README.md").write_text(readme, encoding="utf-8")
    assert gen.cmd_write(tmp_path / "README.md", link) == 0
    assert link.is_symlink() and os.stat(real).st_mode & 0o777 == 0o640
    written = real.read_bytes()
    assert written == status.rstrip("\n").encode("utf-8") and b"\r" not in written
    assert sorted(p.name for p in real.parent.iterdir()) == ["status.md"]


@pytest.mark.parametrize("doc", ["readme", "status"])
def test_write_refuses_a_document_that_changed_while_the_facts_were_derived(tmp_path, scratch_texts, capsys, monkeypatch,
                                                                            doc):
    readme, status = scratch_texts
    stale = status.replace(region(status, "proof"), empty_region("proof"))
    docs = write_docs(tmp_path, readme, stale)
    target = docs.readme if doc == "readme" else docs.status
    before = target.read_text(encoding="utf-8")
    derive = gen.expected_regions

    def saved_meanwhile():
        out = derive()
        target.write_text(before + "A paragraph someone saved meanwhile.\n", encoding="utf-8")
        return out
    monkeypatch.setattr(gen, "expected_regions", saved_meanwhile)
    assert gen.cmd_write(*docs) == 1
    assert f"{gen.DOC_NAME[doc]} changed while the regions were being derived" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8").endswith("someone saved meanwhile.\n") and _only(docs.readme) == BOTH
    assert docs.status.read_text(encoding="utf-8").startswith(stale)  # the other one was not written either


@pytest.mark.parametrize("doc", ["readme", "status"])
def test_check_names_the_line_of_a_carriage_return_and_the_document(scratch, capsys, doc):
    path = getattr(scratch, doc)
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and f"{gen.DOC_NAME[doc]}: [line-endings] line 1 of {gen.DOC_NAME[doc]} has a carriage return" in err


# ================================================================ 2. the proof table

def test_the_proof_table_has_its_header_and_one_row_for_each_thing_counted(status_text):
    lines = body(status_text, "proof").splitlines()
    assert lines[0] == "| Counted from the repository | Now | CI fails when |"
    assert lines[1] == "|---|---|---|"
    rows = rows_of(body(status_text, "proof"))
    assert len(rows) == 7 and all(len(r) == 3 for r in rows)
    assert [r[0] for r in rows][:4] == ["Python versions CI runs the baseline job on", "Pipelines replayed",
                                        "Faults injected", "Blocking sites of the registered hooks"]
    assert rows[5][0].startswith("Tests") and rows[6][0].startswith("Hook registrations")


def test_every_proof_cell_comes_from_the_facts(status_text):
    rows = {r[0]: r for r in rows_of(body(status_text, "proof"))}
    versions, replay = gen.fact("ci_python_versions"), gen.fact("replay_suite_size")
    assert rows["Python versions CI runs the baseline job on"][1] == ", ".join(versions)
    pipelines = rows["Pipelines replayed"][1]
    for value in (replay["pipelines"], replay["compliant_scenarios"], len(replay["settings_modes"]),
                  replay["compliant_replays"]):
        assert re.search(rf"\b{value}\b", pipelines), (value, pipelines)
    assert all(mode in pipelines for mode in replay["settings_modes"])
    faults = rows["Faults injected"][1]
    assert f"{replay['fault_classes']} fault classes in {replay['fault_ids']} variants" in faults
    assert f"{replay['regression_replays']} regression replays" in faults
    sites, by = gen.fact("blocking_sites"), gen.fact("blocking_sites")["by_class"]
    cell = rows["Blocking sites of the registered hooks"][1]
    assert cell.startswith(f"{sites['sites']} sites") and f"{by['G']} own-obligation gates" in cell
    assert f"{by['D']} denials of a forbidden operation" in cell and f"{by['H']} time-lock" in cell
    assert cell.endswith(f"{sites['no_class']} with no clearing class")
    tests = gen.fact("count_tests")
    cell = rows["Tests, counted statically (parametrization not expanded)"][1]
    total = tests["hooks_tests"]["test_functions"] + tests["tests"]["test_functions"]
    assert f"{total:,} test functions in {tests['hooks_tests']['files'] + tests['tests']['files']} files" in cell
    assert f"`hooks/tests` {tests['hooks_tests']['test_functions']:,} in {tests['hooks_tests']['files']} files" in cell
    hooks = gen.fact("hook_registrations")
    cell = next(r for k, r in rows.items() if k.startswith("Hook registrations"))[1]
    assert cell.startswith(f"{hooks['entries']} entries in {hooks['events']} events")
    for event, n in hooks["by_event"].items():
        assert f"{event} {n}" in cell


def test_the_artifact_row_is_labelled_exactly_as_readme_facts_labels_it(status_text):
    arts = gen.fact("static_artifacts")
    row = next(r for r in rows_of(body(status_text, "proof")) if r[0].startswith("file artifacts declared"))
    assert row[0] == gen.md_cell(arts["label"])
    assert row[0].replace("\\", "") == arts["label"]  # nothing but escapes differs from the label
    assert row[1].startswith(f"{arts['declared_file_artifacts']} ")
    assert "artifact check (traced replays)" in row[0]  # it says it is not the total that job reports
    assert "one producer" in row[2] and "deciding reader" in row[2] and "no exception list" in row[2]
    assert "tests/test_artifact_graph.py" in row[2]


def test_the_proof_table_moves_with_its_facts(monkeypatch):
    before = gen.render_proof()
    with_fact(monkeypatch, "count_tests", lambda t: t["tests"].update(test_functions=t["tests"]["test_functions"] + 1000))
    with_fact(monkeypatch, "ci_python_versions", lambda v: v.append("3.99"))
    with_fact(monkeypatch, "hook_registrations", lambda h: h["by_event"].update(Invented=7))
    after = gen.render_proof()
    assert after != before
    assert "3.10, 3.11, 3.12, 3.99" in after and "Invented 7" in after
    assert before.count("\n") == after.count("\n")  # same rows, other figures


@pytest.mark.parametrize("name,row,fragment", [
    ("compliant_replays_clean", "Pipelines replayed", "gate block"),
    ("faults_returned_and_repaired", "Faults injected", "does not repair"),
    ("artifact_check_clean", "file artifacts declared", "deciding reader"),
    ("unit_suite_on_every_version", "Tests, counted", "unit suite fails"),
])
def test_a_ci_cell_makes_its_claim_only_while_the_assertion_is_found(monkeypatch, name, row, fragment):
    real = gen.fact("ci_enforces")
    assert real[name]["holds"] and fragment in rows_by_prefix(gen.render_proof(), row)[2]

    def drop(ci):
        ci[name] = dict(ci[name], holds=False, missing=["gone"], claim=f"the claim of {name}")
    with_fact(monkeypatch, "ci_enforces", drop)
    cell = rows_by_prefix(gen.render_proof(), row)[2]
    assert cell.startswith("not asserted: the claim of " + name), cell
    assert fragment not in cell and real[name]["file"] in cell  # it names the file, claims no assertion


def rows_by_prefix(table: str, prefix: str) -> list[str]:
    return next(r for r in rows_of(table) if r[0].startswith(prefix))


def test_the_blocking_sites_cell_makes_the_weaker_claim_and_never_the_literal_one(status_text, monkeypatch):
    cell = rows_by_prefix(body(status_text, "proof"), "Blocking sites")[2]
    assert cell == "a replay that reaches a blocking site with no clearing class fails CI (`tests/replay/test_no_dead_end.py`)"
    assert gen.fact("ci_enforces")["no_site_without_class"]["holds"] is False  # the suite does not assert it
    for forbidden in ("no site lacks", "no blocking site lacks", "no site may lack", "no blocking site may lack",
                      "lacks a class", "none lacks"):
        assert forbidden not in status_text, forbidden
    # when the suite one day does assert it, the cell may say so; when it asserts neither, it says so
    with_fact(monkeypatch, "ci_enforces", lambda ci: ci["no_site_without_class"].update(holds=True, missing=[]))
    assert rows_by_prefix(gen.render_proof(), "Blocking sites")[2].startswith("a blocking site with no clearing class fails CI")
    with_fact(monkeypatch, "ci_enforces", lambda ci: (ci["no_site_without_class"].update(holds=False, missing=["x"]),
                                                      ci["no_site_without_class"]["weaker"].update(holds=False)))
    cell = rows_by_prefix(gen.render_proof(), "Blocking sites")[2]
    assert cell.startswith("not asserted:") and "fails CI" not in cell


def test_unreachable_sites_are_counted_only_when_there_are_some(monkeypatch):
    assert "unreachable" not in gen.render_proof()
    with_fact(monkeypatch, "blocking_sites", lambda b: b["by_class"].update(U=3))
    assert "3 unreachable" in gen.render_proof()


def test_the_unit_suite_cell_lists_the_versions_and_what_the_suite_leaves_out(status_text):
    cell = rows_by_prefix(body(status_text, "proof"), "Tests")[2]
    unit = gen.fact("ci_enforces")["unit_suite_on_every_version"]
    assert cell.startswith("the unit suite fails on any of " + ", ".join(unit["versions"]))
    assert unit["ignored"] and all(f"`{p}`" in cell for p in unit["ignored"])


def test_the_hook_registration_cell_names_the_gate_that_fails(status_text):
    cell = rows_by_prefix(body(status_text, "proof"), "Hook registrations")[2]
    assert cell == "ledger rows that differ from the registered hooks fail `scripts/check-enforcement-evidence.py`"
    assert (REPO / "scripts/check-enforcement-evidence.py").is_file()


# ================================================================ 3. the commands table and the cast of agents

def test_the_commands_table_is_built_from_the_command_rows_by_group(readme_text):
    lines = body(readme_text, "commands").splitlines()
    assert lines[0] == "| Command | Group | Typed by | What it does |" and lines[1] == "|---|---|---|---|"
    rows = rows_of(body(readme_text, "commands"))
    facts = gen.fact("command_rows")
    order = {g: i for i, g in enumerate(gen.facts_module().COMMAND_GROUPS)}
    shown = sorted((f for f in facts if not f["module"]), key=lambda f: (order[f["group"]], f["name"]))
    assert len(rows) == len(shown) and all(len(r) == 4 for r in rows)
    for cells, fact in zip(rows, shown):
        usage = f"/{fact['name']}" + (f" {fact['argument_hint']}" if fact["argument_hint"] else "")
        assert cells[0] == "`" + usage.replace("|", "\\|") + "`", cells
        assert cells[1] == fact["group"]
        assert cells[2] == ("owner only" if fact["human_only"] else "owner or agent")
        assert cells[3] == gen.md_cell(fact["summary"])  # the summary as written, never cut
        assert not cells[3].endswith("…")
    assert {c[2] for c in rows} == {"owner only", "owner or agent"}
    assert [c[1] for c in rows] == sorted((c[1] for c in rows), key=order.__getitem__)  # grouped, in the groups' order


def test_an_optional_modules_command_is_left_off_the_front_page_and_pointed_to(readme_text, monkeypatch):
    facts = gen.fact("command_rows")
    module = [f for f in facts if f["module"]]
    assert module, "no command of an optional module any more"
    table = body(readme_text, "commands")
    for f in module:
        assert f"`/{f['name']}" not in table
    assert table.splitlines()[-1] == (
        f"{len(facts) - len(module)} commands, generated from the frontmatter of `commands/*.md`. An optional "
        f"module's own commands are described with the module in the [installation guide](docs/installation.md).")
    assert (REPO / "docs/installation.md").is_file()
    monkeypatch.setitem(gen._FACTS, "command_rows", [dict(f, module=None) for f in facts])
    last = gen.render_commands().splitlines()[-1]  # with no module command there is nothing to point to
    assert last == f"{len(facts)} commands, generated from the frontmatter of `commands/*.md`."


def test_the_agents_table_is_built_from_the_agent_rows(readme_text):
    lines = body(readme_text, "agents").splitlines()
    assert lines[0] == "| Agent | What it does |" and lines[1] == "|---|---|"
    rows = rows_of(body(readme_text, "agents"))
    facts = gen.fact("agent_rows")
    assert [r[0] for r in rows] == [f"`{f['name']}`" for f in facts] and len(rows) == len(facts)
    assert [r[1] for r in rows] == [gen.md_cell(f["summary"]) for f in facts]
    assert lines[-1] == f"{len(facts)} agents, generated from the frontmatter of `agents/*.md`."
    names = sorted(p.stem for p in (REPO / "agents").glob("*.md") if p.stem not in ("README", "INDEX"))
    assert [f["name"] for f in facts] == names


def test_the_tables_move_with_their_facts(monkeypatch):
    with_fact(monkeypatch, "agent_rows", lambda rows: rows.append({"name": "zz-new", "summary": "A new agent."}))
    assert "| `zz-new` | A new agent. |" in gen.render_agents()
    with_fact(monkeypatch, "command_rows", lambda rows: rows[0].update(summary="Changed.", group="Quality"))
    first = gen.fact("command_rows")[0]
    assert f"| Quality | {'owner only' if first['human_only'] else 'owner or agent'} | Changed. |" in gen.render_commands()


HOSTILE = {"name": "evil", "argument_hint": "[a|b] <what> `x`", "human_only": False, "group": "Control", "module": None,
           "summary": "Pick a | b, run <script>alert(1)</script> & `code|with <pipe>` and \\| a backslash"}


def test_a_summary_can_neither_break_the_table_nor_be_read_as_html(monkeypatch):
    commands = copy.deepcopy(gen.fact("command_rows")) + [HOSTILE]
    monkeypatch.setitem(gen._FACTS, "command_rows", commands)
    table = gen.render_commands()
    lines = [l for l in table.splitlines() if "/evil" in l]
    assert len(lines) == 1
    assert len(re.split(r"(?<!\\)\|", lines[0].strip())) == 6  # '', four cells, '' : the pipes did not add cells
    cells = next(r for r in rows_of(table) if "/evil" in r[0])
    # outside code spans no angle bracket survives; inside one it is literal already
    prose = gen._CODE_SPAN.sub("", cells[3])
    assert "<" not in prose and ">" not in prose and "&lt;script&gt;" in prose and "&amp;" in prose
    assert "`code\\|with <pipe>`" in cells[3]
    assert cells[0].startswith("``") or cells[0].startswith("`/evil")  # a code span, backticks in the hint kept
    assert "<what>" in cells[0] and "\\|" in cells[0]


@pytest.mark.parametrize("text,expected", [
    ("plain", "plain"),
    ("a | b", "a \\| b"),
    ("<b>x</b>", "&lt;b&gt;x&lt;/b&gt;"),
    ("R&D &amp; Q", "R&amp;D &amp;amp; Q"),
    ("use `a|b` and `<c>`", "use `a\\|b` and `<c>`"),
    ("two\nlines   here", "two lines here"),
    ("a\\b", "a\\\\b"),
])
def test_md_cell(text, expected):
    assert gen.md_cell(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("/dev", "`/dev`"),
    ("/x [a|b]", "`/x [a|b]`"),
    ("/x `y`", "`` /x `y` ``"),
    ("`edge", "`` `edge ``"),
])
def test_code_span(text, expected):
    assert gen.code_span(text) == expected


# ================================================================ 4. the two new claim rows

def new_row(rid: str):
    state, text, evidence, tracked = gen.PREDICATES[rid]()
    return state, text, evidence, tracked


def test_enforcement_strength_reports_the_ledger_and_what_an_exit_code_is(status_text):
    e = gen.fact("enforcement_strength")
    state, text, evidence, _tracked = new_row("enforcement-strength")
    assert state == "partial" and e["by_proof_layer"]["host-observed"] == 0
    assert evidence == "docs/ENFORCEMENT-LEDGER.md"
    assert f"**{e['rows']}** rows" in text
    for label, n in {**e["by_behavior"], **e["by_proof_layer"]}.items():
        assert f"**{n}** {label}" in text, label  # every closed-set value, zero included
    assert "No row is host-observed." in text
    assert "A script that exits 2 is evidence about the script, not about a Claude Code host honouring it." in text
    marker = f"<!-- claim-row id=enforcement-strength state=partial evidence={evidence} tracked=none -->"
    assert marker + "\n- " + text in region(status_text, "status")


def test_enforcement_strength_follows_the_proof_layers(monkeypatch):
    rows = {}

    def some(e):
        rows["n"] = e["rows"]
        e["by_proof_layer"].update({"host-observed": 5, "source-level": e["by_proof_layer"]["source-level"] - 5})
    with_fact(monkeypatch, "enforcement_strength", some)
    state, text, *_ = new_row("enforcement-strength")
    assert state == "partial" and f"**5** of the {rows['n']} rows are host-observed." in text and "No row" not in text
    with_fact(monkeypatch, "enforcement_strength", lambda e: e.update(
        by_proof_layer={**e["by_proof_layer"], "host-observed": e["rows"]}))
    state, text, *_ = new_row("enforcement-strength")
    assert state == "passed" and f"all **{rows['n']}** ledger rows are host-observed" in text


def test_dead_end_sites_says_how_many_of_how_many_and_that_it_is_a_limit(status_text):
    b = gen.fact("blocking_sites")
    state, text, evidence, tracked = new_row("dead-end-sites")
    assert state == "partial" and b["no_class"] > 0
    assert (evidence, tracked) == ("tests/replay/test_no_dead_end.py", "none")
    assert text.startswith("**Blocking sites with no clearing class** — ")
    assert f"**{b['no_class']} of {b['sites']}** blocking sites" in text
    assert "The suite fails only when a replay reaches one" in text
    assert "known limit and not a proof that there are none" in text
    marker = f"<!-- claim-row id=dead-end-sites state=partial evidence={evidence} tracked=none -->"
    assert marker + "\n- " + text in region(status_text, "status")


def test_dead_end_sites_names_no_stranding_it_cannot_show_and_gives_the_reasons_from_the_fact(monkeypatch):
    """Most classless sites are a hook refusing because it cannot decide: not a stranding. The row says what the
    enumerator says each is, counts generated from the fact, and does not call any of them a dead end."""
    b = gen.fact("blocking_sites")
    text = new_row("dead-end-sites")[1]
    assert "Dead-end" not in text and "dead end" not in text.lower()
    assert sum(b["no_class_reasons"].values()) == b["no_class"]
    for reason, n in b["no_class_reasons"].items():
        assert f"**{n}** × {reason}" in text, reason
    ranked = sorted(b["no_class_reasons"].items(), key=lambda kv: (-kv[1], kv[0]))
    assert text.index(f"× {ranked[0][0]}") < text.index(f"× {ranked[-1][0]}")  # most frequent first
    with_fact(monkeypatch, "blocking_sites", lambda f: f.update(no_class=5, sites=40, no_class_reasons={"made up b": 2, "made up a": 3}))
    text = new_row("dead-end-sites")[1]
    assert "**5 of 40** blocking sites" in text
    assert "The enumerator's reasons: **3** × made up a; **2** × made up b." in text
    with_fact(monkeypatch, "blocking_sites", lambda f: f.update(no_class_reasons={}))
    assert "reasons" not in new_row("dead-end-sites")[1]  # nothing is invented when the fact gives none


def test_dead_end_sites_follows_the_count_and_what_the_suite_asserts(monkeypatch):
    with_fact(monkeypatch, "blocking_sites", lambda b: b.update(no_class=0))
    state, text, *_ = new_row("dead-end-sites")  # none counted, but the suite does not assert there can be none
    assert state == "partial" and "does not assert that" in text and "known limit" in text
    with_fact(monkeypatch, "ci_enforces", lambda ci: ci["no_site_without_class"].update(holds=True, missing=[]))
    state, text, *_ = new_row("dead-end-sites")
    assert state == "passed" and "and the suite fails if one does" in text


@pytest.mark.parametrize("rid,fact_name", [("enforcement-strength", "enforcement_strength"),
                                           ("dead-end-sites", "blocking_sites")])
def test_a_new_row_whose_input_is_missing_degrades_to_not_yet_and_publishes_no_figure(monkeypatch, rid, fact_name):
    with_fact(monkeypatch, fact_name, error=f"{fact_name}: missing input docs/ENFORCEMENT-LEDGER.md")
    state, text, evidence, _tracked = new_row(rid)
    assert state == "not-yet" and evidence == "none"
    assert "could not" in text and not re.search(r"\d", text.replace("settings.json", ""))


def test_the_existing_rows_keep_their_predicates_and_states(warm):
    _regions, rows = warm
    by_id = {m.group("id"): m.group("state") for pairs in rows.values() for marker, _v in pairs
             if (m := gen.MARKER_RE.match(marker))}
    assert by_id["known-limits"] == "not-yet" and by_id["os"] == "partial"
    assert by_id["hero-legibility"] == by_id["hero-glyph"] == "partial"
    assert by_id["enforcement-strength"] == by_id["dead-end-sites"] == "partial"
    for rid, fn in [("known-limits", "pred_known_limits"), ("hero-recording", "pred_hero_recording"),
                    ("hero-legibility", "pred_hero_legibility"), ("hero-glyph", "pred_hero_glyph"),
                    ("supported-builds", "pred_supported_builds"), ("capability-check", "pred_capability_check"),
                    ("blackbox-tests", "pred_blackbox"), ("release", "pred_release"), ("os", "pred_os")]:
        assert gen.PREDICATES[rid] is getattr(gen, fn)


def _settings_repo(tmp_path, monkeypatch, tracked: dict | None, working: dict | None):
    """A scratch repository holding the facts module, with settings.json tracked as `tracked` and on disk as
    `working` (None: left out), and the generator pointed at it."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(REPO / "scripts" / "readme_facts.py", root / "scripts" / "readme_facts.py")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)
    git("init", "-q")
    if tracked is not None:
        (root / "settings.json").write_text(json.dumps(tracked), encoding="utf-8")
        git("add", "settings.json")
    if working is not None:
        (root / "settings.json").write_text(json.dumps(working), encoding="utf-8")
    monkeypatch.setattr(gen, "REPO_ROOT", root)
    monkeypatch.setattr(gen, "_FACT_MODULE", None)
    monkeypatch.setattr(gen, "_FACTS", {})


def deny(*rules):
    return {"permissions": {"deny": list(rules)}}


def test_the_deny_rules_are_counted_from_the_tracked_settings_not_the_working_file(tmp_path, monkeypatch):
    """Every other fact reads settings.json as the git index holds it; a machine's working file may carry
    additions no commit holds, and a fresh clone sees none of them."""
    _settings_repo(tmp_path, monkeypatch, tracked=deny("Bash(rm:*)"), working=deny("Bash(git push:*)", "Bash(rm:*)"))
    assert gen.measure_deny_rules() == (1, 0, "settings.json")  # the working file's git rule is not counted
    assert gen.pred_known_limits()[1].startswith("**Known limits — this guard does not cover everything.**")


def test_the_deny_rules_follow_the_index_and_are_not_measured_without_one(tmp_path, monkeypatch):
    _settings_repo(tmp_path, monkeypatch, tracked=deny("Bash(git push:*)", "Bash(rm:*)"), working=deny())
    assert gen.measure_deny_rules() == (2, 1, "settings.json")
    _settings_repo(tmp_path / "untracked", monkeypatch, tracked=None, working=deny("Bash(git push:*)"))
    assert gen.measure_deny_rules() is None  # on disk only: a fresh clone has none, so nothing is measured
    state, text, *_ = gen.pred_known_limits()
    assert state == "not-yet" and "could not be measured" in text


def test_a_claim_row_whose_input_is_not_committed_is_false(monkeypatch):
    assert gen.pred_supported_builds()[0] == "passed"
    monkeypatch.setattr(gen, "is_committed", lambda rel: False)
    state, text, *_ = gen.pred_supported_builds()
    assert state == "not-yet" and "not yet" in text


# ================================================================ 5. fail closed: a count region that cannot be computed

def test_check_fails_naming_the_missing_input_when_a_count_region_cannot_be_computed(scratch, capsys, monkeypatch):
    with_fact(monkeypatch, "count_tests", error="count_tests: no test file under hooks/tests/ in the git index")
    rc, err, _out = run_check(scratch, capsys)
    assert rc == 2
    assert "docs/status.md: [region:proof] cannot be computed" in err and "no test file under hooks/tests/" in err
    assert "[region:commands]" not in err and "[region:agents]" not in err  # the other count regions are unaffected


@pytest.mark.parametrize("fact_name,rid,why", [
    ("command_rows", "commands", "commands/dev.md: the summary has 170 characters, more than 160; shorten it"),
    ("agent_rows", "agents", "agents/qa.md: the summary names 'gpt-5', an internal name the front page does not show"),
])
def test_a_summary_that_breaks_the_rules_fails_the_check_naming_the_file(scratch, capsys, monkeypatch, fact_name, rid, why):
    with_fact(monkeypatch, fact_name, error=f"{fact_name}: {why}")
    rc, err, _out = run_check(scratch, capsys)
    assert rc == 2 and f"README.md: [region:{rid}] cannot be computed" in err and why in err
    assert "[region:proof]" not in err


@pytest.mark.parametrize("fact_name,rid", [("command_rows", "commands"), ("agent_rows", "agents"),
                                           ("count_tests", "proof")])
def test_a_count_region_is_never_regenerated_from_a_stale_value(tmp_path, scratch_texts, capsys, monkeypatch,
                                                                fact_name, rid):
    docs = write_docs(tmp_path, *scratch_texts)
    with_fact(monkeypatch, fact_name, error=f"{fact_name}: no such file in the git index")
    assert gen.cmd_write(*docs) == 1
    err = capsys.readouterr().err
    assert f"region {rid!r} cannot be computed" in err and "no such file" in err and err.count("was NOT touched") == 2
    # not one byte written, not even the other regions or the other document
    assert (docs.readme.read_text(encoding="utf-8"), docs.status.read_text(encoding="utf-8")) == scratch_texts


def test_a_fact_that_raises_is_remembered_and_reported_once(monkeypatch):
    calls = []

    def boom(root):
        calls.append(root)
        raise RuntimeError("explodes")
    monkeypatch.setattr(gen, "_FACTS", {})
    monkeypatch.setattr(gen, "_FACT_MODULE", type("M", (), {"FACTS": {"x": staticmethod(boom)}}))
    for _ in range(2):
        with pytest.raises(gen.FactUnavailable, match="x: explodes"):
            gen.fact("x")
    assert len(calls) == 1


def test_the_facts_module_missing_is_named(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gen, "_FACT_MODULE", None)
    monkeypatch.setattr(gen, "_FACTS", {})
    with pytest.raises(gen.FactUnavailable, match=r"scripts/readme_facts\.py"):
        gen.fact("count_tests")
    assert gen.pred_enforcement_strength()[0] == "not-yet"
    assert gen.expected_regions()[1].keys() == {"proof", "commands", "agents"}


# ================================================================ 6. a byte-compare failure on an edited region

def edited(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_an_edited_proof_cell_fails_the_byte_compare_and_names_the_region(scratch, capsys):
    replay = gen.fact("replay_suite_size")
    edited(scratch.status, f"{replay['compliant_replays']} compliant replays",
           f"{replay['compliant_replays'] + 1} compliant replays")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "docs/status.md: [region-byte-compare] region 'proof'" in err
    assert err.count("FAIL") == 1  # only that region differs


def test_an_edited_commands_row_fails_the_byte_compare(scratch, capsys):
    edited(scratch.readme, "| `/commit` | Ship | owner only |", "| `/commit` | Ship | owner or agent |")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "README.md: [region-byte-compare] region 'commands'" in err


def test_an_edited_agents_row_fails_the_byte_compare(scratch, capsys):
    qa = next(a for a in gen.fact("agent_rows") if a["name"] == "qa")
    edited(scratch.readme, f"| `qa` | {gen.md_cell(qa['summary'])} |", "| `qa` | Approves everything. |")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "README.md: [region-byte-compare] region 'agents'" in err and err.count("FAIL") == 1


def test_an_edited_claim_row_names_the_row_and_the_region(scratch, capsys):
    edited(scratch.status, "- **Release** — unreleased (no tags).", "- **Release** — shipping soon!")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "row 'release': visible text differs" in err and "region 'status'" in err


def test_a_flipped_state_fails_the_predicate_check(scratch, capsys):
    edited(scratch.status, "id=dead-end-sites state=partial", "id=dead-end-sites state=passed")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "row 'dead-end-sites' claims state='passed' but its named predicate evaluates to 'partial'" in err


def test_an_extra_bullet_inside_a_region_is_caught(scratch, capsys):
    edited(scratch.status, gen.END.format(rid="status"), "- **Everything works** — trust us.\n" + gen.END.format(rid="status"))
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "[region-byte-compare] region 'status'" in err


def test_a_missing_new_row_is_a_completeness_failure(scratch, capsys):
    text = scratch.status.read_text(encoding="utf-8")
    kept = [l for l in text.splitlines() if "dead-end-sites" not in l and not l.startswith("- **Dead-end sites**")]
    scratch.status.write_text("\n".join(kept) + "\n", encoding="utf-8")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "row 'dead-end-sites' is missing" in err


@pytest.mark.parametrize("doc", ["readme", "status"])
def test_a_claim_row_outside_every_region_is_caught(scratch, capsys, doc):
    path = getattr(scratch, doc)
    path.write_text(path.read_text(encoding="utf-8") + "\n<!-- claim-row id=os state=passed evidence=none tracked=none -->\n",
                    encoding="utf-8")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and f"{gen.DOC_NAME[doc]}: [region-byte-compare] claim-row marker outside any canonical region" in err


# ================================================================ 7. the position rule

def positions(text: str, doc: str = "status") -> list[str]:
    return gen.assert_region_positions(text, doc)


def named(violations: list[str], rid: str) -> list[str]:
    return [v for v in violations if f"region {rid!r}" in v]


def test_regions_in_their_sections_in_order_have_no_violation(status_text):
    assert positions(status_text) == []


def test_the_headline_and_fold_assertions_are_gone(status_text):
    """The old rule, a limits statement next to the headline and above the fold, is not what is asserted."""
    assert not hasattr(gen, "assert_limits_above_fold")
    assert "headline" not in " ".join(positions(status_text))
    far = status_text.replace("Generated claim rows.\n", "Generated claim rows.\n\n" + "A paragraph.\n\n" * 12)
    assert positions(far) == []  # nothing needs to be adjacent to anything
    doc = gen.__doc__
    assert "moved the claim rows" in doc and "assert_region_positions" in doc and "replaced" in doc


def test_a_region_moved_out_of_its_section_is_named(status_text):
    moved = cut(status_text, "limits").replace("## Measured proof\n", "## Measured proof\n\n" + region(status_text, "limits") + "\n", 1)
    v = positions(moved)
    assert len(v) == 1 and "region 'limits' lies outside the H2 section 'Status and known limits'" in v[0]
    assert "'Measured proof'" in v[0]  # and says where it sits instead
    again = cut(status_text, "proof").replace("## Documentation\n", "## Documentation\n\n" + region(status_text, "proof") + "\n", 1)
    assert len(positions(again)) == 1 and named(positions(again), "proof")


def test_a_region_before_every_heading_is_outside_its_section(readme_text, status_text):
    v = positions(region(readme_text, "commands") + "\n\n" + cut(readme_text, "commands"), "readme")
    assert len(v) == 1 and "region 'commands' lies outside" in v[0] and "no H2 section" in v[0]
    v = positions(region(status_text, "proof") + "\n\n" + cut(status_text, "proof"))
    assert len(v) == 1 and "region 'proof' lies outside" in v[0] and "no H2 section" in v[0]


def test_the_readmes_regions_in_their_sections_have_no_violation_and_a_moved_one_is_named(readme_text):
    assert positions(readme_text, "readme") == []
    a, b = region(readme_text, "commands"), region(readme_text, "agents")
    v = positions(readme_text.replace(a, "@@A@@").replace(b, a).replace("@@A@@", b), "readme")
    assert named(v, "commands") and named(v, "agents") and all("lies outside" in x for x in v)
    v = positions(readme_text.replace("## The cast of agents", "## Agents"), "readme")
    assert len(v) == 1 and "region 'agents' has no H2 section 'The cast of agents'" in v[0]


def test_a_region_in_the_other_document_is_named(readme_text, status_text):
    v = positions(readme_text + "\n" + region(status_text, "proof") + "\n", "readme")
    assert len(v) == 2 and all("of region 'proof' is in README.md; the region belongs in docs/status.md" in x for x in v)
    v = positions(status_text.replace("## Documentation\n", "## Documentation\n\n" + region(readme_text, "agents") + "\n"))
    assert len(v) == 2 and all("of region 'agents' is in docs/status.md; the region belongs in README.md" in x for x in v)
    v = positions(cut(status_text, "limits"))  # and the status page without its own region is still named
    assert len(v) == 1 and "region 'limits' is missing" in v[0]


def test_a_duplicated_region_is_named(status_text):
    status = region(status_text, "status")
    v = positions(status_text.replace(status, status + "\n\n" + status))
    assert len(v) == 1 and "region 'status' is duplicated" in v[0]


def test_a_missing_region_is_named(status_text):
    v = positions(cut(status_text, "proof"))
    assert len(v) == 1 and "region 'proof' is missing" in v[0]
    half = positions(status_text.replace(gen.BEGIN.format(rid="disclosure"), ""))
    assert len(half) == 1 and "region 'disclosure'" in half[0] and "not a BEGIN followed by an END" in half[0]


def test_claim_regions_out_of_order_are_named(status_text):
    a, b = region(status_text, "limits"), region(status_text, "disclosure")
    swapped = status_text.replace(a, "@@A@@").replace(b, a).replace("@@A@@", b)
    v = positions(swapped)
    assert named(v, "limits") and named(v, "disclosure") and not named(v, "status")
    assert all("out of order" in x for x in v)
    c = region(status_text, "status")
    v = positions(status_text.replace(c, "@@C@@").replace(a, c).replace("@@C@@", a))
    assert named(v, "limits") and named(v, "status")


def test_a_missing_or_renamed_section_heading_is_named_for_each_region_in_it(status_text):
    v = positions(status_text.replace("## Status and known limits", "## Status"))
    assert [bool(named(v, r)) for r in gen.CLAIM_REGIONS] == [True, True, True]
    assert all("has no H2 section 'Status and known limits'" in x for x in v) and len(v) == 3
    v = positions(status_text.replace("## Documentation", "## Status and known limits"))
    assert len(v) == 3 and all("appears 2 times" in x for x in v)


def test_a_region_in_a_subsection_of_its_section_is_inside_it(status_text):
    deeper = status_text.replace(region(status_text, "limits"), "### Limits\n\n" + region(status_text, "limits"))
    assert positions(deeper) == []
    sibling = status_text.replace(region(status_text, "limits"), "## Limits\n\n" + region(status_text, "limits"))
    v = positions(sibling)  # an H2 of its own ends the section: the region and the two that follow it are outside
    assert [bool(named(v, r)) for r in gen.CLAIM_REGIONS] == [True, True, True] and len(v) == 3


def test_a_heading_inside_a_fence_or_a_comment_is_no_heading(status_text):
    fenced = status_text.replace("## Status and known limits", "## Elsewhere\n\n```\n## Status and known limits\n```")
    v = positions(fenced)
    assert len(v) == 3 and all("has no H2 section" in x for x in v)
    commented = status_text.replace("## Status and known limits", "## Elsewhere\n\n<!--\n## Status and known limits\n-->")
    assert len(positions(commented)) == 3


def test_check_reports_a_moved_region_with_the_tag_and_exit_2(scratch, capsys):
    text = scratch.status.read_text(encoding="utf-8")
    scratch.status.write_text(cut(text, "limits").replace("## Measured proof\n", "## Measured proof\n\n"
                                                          + region(text, "limits") + "\n", 1), encoding="utf-8")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "docs/status.md: [region-position] region 'limits' lies outside" in err


# ================================================================ 8. the number rule

def numbers(text: str, doc: str = "readme") -> list[str]:
    return gen.assert_no_hand_typed_numbers(text, doc)


def test_the_declared_figures_and_their_source(readme_text, status_text):
    assert dict(gen.CITED_FIGURES) == {"37,623": "https://arxiv.org/pdf/2609.17598", "12.6": "https://arxiv.org/pdf/2609.17598"}
    assert numbers(readme_text) == []  # the cited figures pass, the regions' own numbers are not read
    assert numbers(status_text, "status") == []  # the status page cites nothing, so it is not asked to


def test_a_stray_numeral_in_the_prose_fails_naming_the_line_and_the_number(status_text):
    lines = status_text.splitlines()
    at = lines.index("Generated claim rows.")
    lines[at] = "Generated claim rows, 47 of them."
    v = numbers("\n".join(lines) + "\n", "status")
    assert len(v) == 1
    assert f"line {at + 1}" in v[0] and "'47'" in v[0] and "[hand-typed-number]" in v[0]


def test_every_stray_numeral_is_reported_with_its_own_line(readme_text):
    text = readme_text.replace("Intro paragraph with no number in it.", "Intro with 3 and 4.5 and 1,000 numbers.")
    v = numbers(text)
    assert [re.search(r"the numeral '([^']+)'", x).group(1) for x in v] == ["3", "4.5", "1,000"]
    assert all("line 3" in x for x in v)


def test_a_cited_figure_passes_and_a_near_miss_does_not(readme_text):
    assert numbers(readme_text) == []
    near = readme_text.replace(FIGURE_A, "37,624")
    v = numbers(near)
    assert any("'37,624'" in x and "[hand-typed-number]" in x for x in v)
    assert any("declared figure" in x and repr(FIGURE_A) in x for x in v)  # and the declared one is now stale too


def test_a_cited_figure_is_no_exemption_on_the_status_page(status_text):
    cited = status_text + f"\nA study of {FIGURE_A} pull requests ([source]({URL})).\n"
    v = numbers(cited, "status")
    assert len(v) == 1 and f"the numeral {FIGURE_A!r}" in v[0] and "[hand-typed-number]" in v[0]


def test_a_stale_cited_figure_fails(readme_text):
    gone = readme_text.replace(f"a median of {FIGURE_B}\nhours", "a median of some\nhours")
    v = numbers(gone)
    assert len(v) == 1 and "[cited-figure]" in v[0] and repr(FIGURE_B) in v[0] and "no longer appears" in v[0]
    in_code = readme_text.replace(f"a median of {FIGURE_B}", f"a median of `{FIGURE_B}`")
    assert any(repr(FIGURE_B) in x and "no longer appears" in x for x in numbers(in_code))  # code is not prose


def test_a_missing_source_url_fails(readme_text):
    v = numbers(readme_text.replace(URL, "https://example.org/x"))
    assert len(v) == 2 and all("is absent from the README" in x and URL in x for x in v)  # one per figure it sources


def test_the_declared_figures_live_in_one_place(readme_text, monkeypatch):
    monkeypatch.setattr(gen, "CITED_FIGURES", gen.CITED_FIGURES + (("99", "https://example.org/nine"),))
    v = numbers(readme_text)
    assert any("'99'" in x and "https://example.org/nine" in x and "is absent" in x for x in v)
    assert any("'99'" in x and "no longer appears" in x for x in v)
    assert numbers(readme_text + "\nSee https://example.org/nine: 99 cases.\n") == []


@pytest.mark.parametrize("snippet", [
    "1. an ordered item\n2. another\n   3) nested, with a paren\n",                 # (a) list markers
    "Run `python3 -m pytest -n 4` now.\n",                                            # (b) code span
    "Run ``a `42` b`` now.\n",                                                        # a longer fence
    "```bash\nsleep 30\necho 7\n```\n",                                               # fenced block
    "~~~\n99\n~~~\n",
    "<!-- a comment, 12 of them\nover two lines 13 -->\n",                             # HTML comment
    '<img src="a.svg" width="720" alt="x">\n',                                         # tag and attributes
    '<a href="https://x.org/v2/3" title="4">link</a>\n',
    "<p align=\"center\"><sub>a <strong>b</strong></sub></p>\n",
    "See [the docs](https://example.org/docs/2026/01/26/) and [a](b.md#sec-3).\n",    # link target
    "[ref]: https://example.org/9\n\nUse [ref][].\n",                                  # reference definition
    "![alt 5](assets/hero-3.svg)\n",                                                   # image
    "Bare https://example.org/pdf/2609.17598 url.\n",                                  # bare URL
    "Reproduce with <code>python3 scripts/x.py --n 8</code> here.\n",                 # HTML code element
    "<pre>\nx = 8\n</pre>\n",
    "Names: python3, L8, P12, R-E1, v1.2.3, sha256, F3a, x86.\n",                     # identifiers, not numbers
    "A&nbsp;b &#160; c &#x41; d.\n",                                                   # entities
    "A <https://example.org/a/5> autolink.\n",
])
def test_a_numeral_in_an_exempt_place_passes(snippet):
    assert gen.prose_numerals(snippet) == [], gen.prose_view(snippet)


@pytest.mark.parametrize("snippet,expected", [
    ("There are 3 apples.\n", ["3"]),
    ("In 2026, 3.10 and 1,000.\n", ["2026", "3.10", "1,000"]),
    ("**5** and _6_ and (7) and $8 and #9\n", ["5", "6", "7", "8", "9"]),
    ("| Step | n |\n|---|---|\n| a | 10 |\n", ["10"]),
    ("## Step 2\n", ["2"]),
    ("1. item with 4 words\n", ["4"]),
    ("10x faster, 2nd place\n", ["10", "2"]),
    ("`code` then 5 and `more 6` then 7\n", ["5", "7"]),
    ("a\n\n`unclosed 8\n\n9`\n", ["8", "9"]),                                          # a span does not cross a blank line
])
def test_a_numeral_in_the_prose_is_found(snippet, expected):
    assert [n for _line, n in gen.prose_numerals(snippet)] == expected


# What would hide prose from the number rule has to be visible in the rendered page too, or the hiding is a bypass.
# Every case below hid a numeral from the first version of the rule, which reported nothing.

def violations_of(text: str) -> list[str]:
    return [v for v in numbers(text) if "[cited-figure]" not in v]


def test_a_code_fence_that_is_never_closed_is_a_violation_naming_its_line():
    text = "# T\n\nIntro.\n\n```\ncode\n\nProse with 5 in it.\n"
    v = violations_of(text)
    assert len(v) == 1 and v[0].startswith("[number-rule] line 5:") and "never closed" in v[0]
    assert "rest of the file is hidden" in v[0]


def test_a_longer_or_other_fence_is_not_closed_by_a_shorter_or_other_one():
    assert violations_of("````\ncode\n```\nProse 5\n") != []             # three backticks do not close four
    assert violations_of("~~~\ncode\n```\nProse 5\n") != []              # a tilde fence needs a tilde fence
    assert violations_of("```\ncode\n```\nProse 5\n")[0].startswith("[hand-typed-number] line 4")
    inline = violations_of("```code``` then 4\nProse 5\n")  # backticks in the info string: an inline span, no fence
    assert [x.split(":")[0] for x in inline] == ["[hand-typed-number] line 1", "[hand-typed-number] line 2"]


@pytest.mark.parametrize("text,line", [
    ("- a `b\n- c 5 d `e\n", 1),                                  # across list items
    ("## Title `x\nprose 7 and `y`\n", 1),                         # across a heading
    ("| a | `b |\n|---|---|\n| 5 | `c` |\n", 1),                  # across table rows
    ("| a | b |\n|---|---|\n| `x | 8 |\n| y | z |\n", 3),       # across table cells
    ("Intro `stray.\n\nSecond paragraph 6 `fine`.\n", 1),         # across paragraphs
    ("A \\` escaped tick, then 9 and `code`.\n", None),            # an escaped backtick opens nothing
])
def test_a_stray_backtick_hides_nothing_and_is_named(text, line):
    v = violations_of(text)
    problems = [x for x in v if x.startswith("[number-rule]")]
    if line is None:
        assert problems == [] and any("the numeral '9'" in x for x in v)
        return
    assert [x.split(":")[0] for x in problems][:1] == [f"[number-rule] line {line}"], v
    assert "no closing run" in problems[0] and "never pairs across them" in problems[0]
    assert any(x.startswith("[hand-typed-number]") for x in v)  # and the numeral it would have hidden is found


def test_a_balanced_span_still_hides_its_numeral_and_a_span_may_cross_lines_of_one_paragraph():
    assert violations_of("Run `python3 -n 4` now, and `a\nb 5` too.\n") == []
    assert violations_of("A ``tick ` and 6`` pair.\n") == []


def test_an_html_comment_that_is_never_closed_is_a_violation_naming_its_line():
    v = violations_of("# T\n\n<!-- opened\nand never closed\n")
    assert len(v) == 1 and v[0].startswith("[number-rule] line 3:") and "comment" in v[0] and "never closed" in v[0]
    v = violations_of("Text <!-- opened mid-line\n\nProse 9 -->\n")  # a renderer shows this as text
    assert v[0].startswith("[number-rule] line 1:") and "not closed in the same paragraph" in v[0]
    assert any("the numeral '9'" in x for x in v)


def test_a_comment_opener_or_closer_inside_code_does_not_start_or_end_a_comment():
    spans = "Write `<!--` to open a comment.\nProse 5 here.\nWrite `-->` to close it.\n"
    v = violations_of(spans)
    assert len(v) == 1 and "the numeral '5'" in v[0] and "line 2" in v[0]
    fenced = "```\n<!--\n```\nProse 7 here.\n-->\n"
    v = violations_of(fenced)
    assert len(v) == 1 and "the numeral '7'" in v[0] and "line 4" in v[0]
    assert violations_of("```\n-->\n```\n<!-- a comment 8 -->\n") == []
    # inside a comment, as in the rendered page, the first closer ends it, a code span or not
    v = violations_of("<!-- see `-->` and 6 -->\n")
    assert any("the numeral '6'" in x for x in v)


def test_a_comment_that_starts_a_line_may_run_over_blank_lines_and_closes_at_the_first_closer():
    assert violations_of("<!-- one\n\ntwo 5\n\nthree -->\nProse.\n") == []
    v = violations_of("<!-- one\ntwo --> then 6 here\n")
    assert len(v) == 1 and "the numeral '6'" in v[0] and "line 2" in v[0]
    assert violations_of("<!-- 4 --> Prose.\n<!--> Prose.\n") == []


@pytest.mark.parametrize("snippet", [
    '[a link](https://example.org/x "a title with 5 in it")\n',
    "![an image 6](assets/x.svg 'and a title 7')\n",
    '<img src="x.svg" alt="alt text 8" title="title 9">\n',
    '<a href="https://example.org" title="10 things" data-n="11">link</a>\n',
])
def test_a_numeral_in_a_title_or_alt_stays_exempt(snippet):
    assert gen.prose_numerals(snippet) == []


@pytest.mark.parametrize("word,numeral", [("UTF-8", "8"), ("SHA-256", "256"), ("HTTP/2", "2"), ("a footnote[^1]", "1")])
def test_the_known_false_positives_are_left_and_a_code_span_is_the_escape(word, numeral):
    assert [n for _l, n in gen.prose_numerals(f"Uses {word} here.\n")] == [numeral]
    wrapped = word.split("[")[0]
    assert gen.prose_numerals(f"Uses `{wrapped}` here.\n") == []
    for fragment in ("false positives", "UTF-8", "SHA-256", "HTTP/2", "footnote", "code span"):
        assert fragment in gen.__doc__, fragment


def test_the_problems_are_reported_by_the_check_with_their_tag(scratch, capsys):
    edited(scratch.readme, "Second step.", "Second step, with a stray ` tick.")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "[number-rule] line 7:" in err and "no closing run" in err


def test_the_line_numbers_survive_everything_that_is_blanked():
    text = "# T\n\n<!-- one\ntwo -->\n\n```\ncode\n```\n\nprose 5\n"
    assert gen.prose_numerals(text) == [(10, "5")]


def test_numbers_inside_the_regions_are_not_read(readme_text, status_text):
    for text, rid in ((status_text, "proof"), (readme_text, "commands"), (readme_text, "agents")):
        assert re.search(r"\d", region(text, rid))
        assert gen.prose_numerals(region(text, rid)) == []
    assert numbers(readme_text) == [] and numbers(status_text, "status") == []


@pytest.mark.parametrize("doc,line", [("readme", 7), ("status", 6)])
def test_check_reports_a_hand_typed_number_in_either_document_with_the_tag_and_exit_2(scratch, capsys, doc, line):
    edited(getattr(scratch, doc), "Second step.", "Second step, of 12.")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and f"{gen.DOC_NAME[doc]}: [hand-typed-number] line {line}: the numeral '12'" in err


# ================================================================ 8b. no internal name on the front page

@pytest.mark.parametrize("name", ["paseo", "Unfuddle", "gpt-5.6-sol", "claude-opus-5-5", "codex-mini"])
def test_an_internal_name_on_the_front_page_fails_naming_the_line(readme_text, name):
    lines = readme_text.splitlines()
    at = lines.index("Generated from the frontmatter too.")
    lines[at] = f"Generated from the frontmatter too, like the {name} module."
    v = gen.assert_no_internal_names("\n".join(lines) + "\n")
    assert len(v) == 1 and f"[internal-name] line {at + 1}:" in v[0] and v[0].count("'") >= 2
    assert gen.assert_no_internal_names(readme_text) == []


def test_the_internal_names_are_checked_on_the_front_page_only(scratch, capsys):
    edited(scratch.status, "Generated claim rows.", "Generated claim rows, see the paseo module.")
    assert run_check(scratch, capsys)[0] == 0  # the status page may name what the front page does not
    edited(scratch.readme, "Generated from the frontmatter too.", "Generated by the paseo module too.")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "README.md: [internal-name] line" in err and "'paseo'" in err
    assert gen.assert_no_internal_names("the claude-codex-settings repository") == []  # a name that holds a word is not one


# ================================================================ 9. the glyph model: only its drift is consumed

STUB = """import json, sys
print(json.dumps(PAYLOAD))
sys.exit(2)
"""


def stub_measure(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "measure-hero-fold.py"
    path.write_text(f"PAYLOAD = {payload!r}\n" + STUB, encoding="utf-8")
    return path


COMBO = {"viewport": "1280x800", "scheme": "light", "glyph_px": 7.55,
         "above_fold": {"headline": False, "limits": False, "hero": False}}


def test_drift_is_a_violation_and_the_old_fold_assertions_are_not(tmp_path):
    drift = "1280x800/light: the browser renders the hero glyph at 9px but the published model predicts 7.55px"
    script = stub_measure(tmp_path, {"results": [COMBO], "model_drift": [drift],
                                     "failures": [drift, "1280x800/light: not above the fold: headline, limits"]})
    violations, notes, measured = gen.assert_glyph_model(tmp_path / "README.md", script)
    assert violations == [f"[fold] {drift}"] and len(notes) == 1 and measured is True


def test_a_headline_and_limits_below_the_fold_and_the_glyph_floor_are_no_violation(tmp_path):
    script = stub_measure(tmp_path, {"results": [COMBO], "model_drift": [],
                                     "failures": ["1280x800/light: not above the fold: headline, limits",
                                                  "1280x800/light: hero glyph height 7.55px < 11.0px"]})
    violations, notes, measured = gen.assert_glyph_model(tmp_path / "README.md", script)
    assert violations == [] and notes and measured is True


def test_a_measurement_that_produced_nothing_is_a_violation_and_one_that_cannot_run_is_a_note(tmp_path):
    empty = stub_measure(tmp_path, {"results": [], "model_drift": []})
    violations, _notes, measured = gen.assert_glyph_model(tmp_path / "README.md", empty)
    assert violations and measured is False
    broken = tmp_path / "broken.py"
    broken.write_text("raise SystemExit('no browser')\n", encoding="utf-8")
    violations, notes, measured = gen.assert_glyph_model(tmp_path / "README.md", broken)
    assert violations == [] and "UNVERIFIED" in notes[0] and "no browser" in notes[0] and measured is False
    violations, notes, measured = gen.assert_glyph_model(tmp_path / "README.md", tmp_path / "absent.py")
    assert violations == [] and "did NOT run" in notes[0] and measured is False


def test_a_missing_playwright_is_named_in_the_note(tmp_path):
    script = tmp_path / "measure-hero-fold.py"
    script.write_text("import playwright_that_is_not_installed\n", encoding="utf-8")
    violations, notes, measured = gen.assert_glyph_model(tmp_path / "README.md", script)
    assert violations == [] and measured is False
    assert "ModuleNotFoundError" in notes[0] and "playwright_that_is_not_installed" in notes[0]
    assert "model prediction" in notes[0] and "UNVERIFIED" in notes[0]


def test_a_relative_page_path_reaches_the_fold_script_as_an_absolute_one(tmp_path, monkeypatch):
    """The fold script runs from the repository root, not from where the generator was started."""
    log = tmp_path / "argv.json"
    script = tmp_path / "measure-hero-fold.py"
    script.write_text("import json, os, sys\n"
                      f"json.dump([sys.argv[1:], os.getcwd()], open({str(log)!r}, 'w'))\n"
                      f"print(json.dumps({{'results': [{COMBO!r}], 'model_drift': []}}))\n", encoding="utf-8")
    (tmp_path / "status.md").write_text("# r\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert gen.assert_glyph_model(Path("status.md"), script)[2] is True
    argv, cwd = json.loads(log.read_text(encoding="utf-8"))
    assert argv == ["--doc", str(tmp_path.resolve() / "status.md")]
    assert Path(cwd).resolve() == gen.REPO_ROOT.resolve() != tmp_path.resolve()  # and it is another directory


def test_the_fold_script_measures_the_status_page_and_resolves_its_hero_from_docs():
    """The hero moved to docs/status.md: the measurement defaults to that page, and the page's own relative src
    (../.github/assets/...) must reach the asset, or the page is measured with an alt-text box in its place."""
    spec = importlib.util.spec_from_file_location("fold_under_test", REPO / "scripts" / "measure-hero-fold.py")
    fold = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fold)
    page = REAL.status.read_text(encoding="utf-8")
    html = fold.md_to_html(page, REAL.status.parent)
    src = re.search(r'src="(file:[^"]*guard-hero\.svg)"', html).group(1)
    assert Path(src[len("file://"):]).resolve() == (REPO / ".github" / "assets" / "guard-hero.svg").resolve()
    assert fold.hero_img_width(page) == 720 and fold.hero_img_width(REAL.readme.read_text(encoding="utf-8")) is None
    source = (REPO / "scripts" / "measure-hero-fold.py").read_text(encoding="utf-8")
    assert '"--doc", "--readme", dest="doc", default=str(REPO_ROOT / "docs" / "status.md")' in source


def test_check_consumes_the_drift_report_of_the_real_fold_script_when_it_runs(scratch, capsys, monkeypatch):
    calls = []
    monkeypatch.setattr(gen, "assert_glyph_model",
                        lambda page: calls.append(page) or (["[fold] drifted"], ["[fold] ran"], True))
    rc, err, out = run_check(scratch, capsys, fold=True)
    assert calls == [scratch.status] and rc == 2 and "docs/status.md: [fold] drifted" in err and "[fold] ran" in out
    calls.clear()
    assert run_check(scratch, capsys, fold=False)[0] == 0 and calls == []  # --no-fold leaves the measurement out


def test_the_success_line_says_what_was_measured(scratch, capsys, monkeypatch):
    """It used to end '... and glyph model asserted' even when the fold measurement could not run."""
    real = gen.assert_glyph_model
    stub = scratch.status.parent / "no-browser.py"
    stub.write_text("raise ModuleNotFoundError(\"No module named 'playwright'\")\n", encoding="utf-8")
    monkeypatch.setattr(gen, "assert_glyph_model", lambda page: real(page, stub))
    rc, err, out = run_check(scratch, capsys, fold=True)
    assert rc == 0, err
    assert "NOTE: [fold] the fold measurement produced no report" in out and "No module named 'playwright'" in out
    ok = next(l for l in out.splitlines() if "OK  " in l)
    assert "glyph model asserted" not in ok
    assert "the glyph model was NOT measured, so the hero figures are model predictions" in ok
    assert "position, hand-typed numbers and internal names asserted" in ok
    drifting = stub_measure(scratch.status.parent, {"results": [COMBO], "model_drift": []})
    monkeypatch.setattr(gen, "assert_glyph_model", lambda page: real(page, drifting))
    rc, err, out = run_check(scratch, capsys, fold=True)
    assert rc == 0 and "(position, hand-typed numbers, internal names and glyph model asserted)" in out
    assert "NOT measured" not in out
    rc, err, out = run_check(scratch, capsys, fold=False)
    ok = next(l for l in out.splitlines() if "OK  " in l)
    assert "glyph model was not measured (--no-fold), so the hero figures are model predictions" in ok
    assert "glyph model asserted" not in ok


def test_the_documentation_says_the_hero_figures_are_predictions_without_a_browser():
    header = re.sub(r"(?m)^#\s?", "", VERIFY.read_text(encoding="utf-8").split("set -uo pipefail", 1)[0])
    for text in (gen.__doc__, header):
        flat = " ".join(text.lower().split())
        assert "model predictions, not measurements" in flat, text[:200]
        assert "playwright" in flat


# ================================================================ 10. the real documents, the command line, verify-claims.sh

def test_the_real_documents_pass_the_check(capsys):
    rc, err, out = run_check(REAL, capsys)
    assert rc == 0, err
    assert "11 rows and 6 canonical regions verified in README.md and docs/status.md" in out


def test_the_real_documents_hold_each_region_in_its_section_in_order():
    readme, status = (p.read_text(encoding="utf-8") for p in REAL)
    assert positions(readme, "readme") == [] and positions(status, "status") == []
    assert numbers(readme) == [] and numbers(status, "status") == []
    assert gen.assert_no_internal_names(readme) == []
    h2 = {doc: {t for level, t, _o in gen.headings(text) if level == 2} for doc, text in (("readme", readme), ("status", status))}
    assert {"The command surface", "The cast of agents"} <= h2["readme"]
    assert {"Measured proof", "Status and known limits"} <= h2["status"]
    assert not h2["readme"] & {"Measured proof", "Status and known limits"}  # the status material left the README
    assert "guard-hero" not in readme and "claim-row" not in readme
    assert 'src="../.github/assets/guard-hero.svg"' in status and "docs/status.md" in readme  # and it is linked


def run_cli(*args, docs: Docs | None = None, env_extra: dict | None = None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "PYTHONDONTWRITEBYTECODE"}
    env.update(env_extra or {})
    paths = ["--readme", str(docs.readme), "--status", str(docs.status)] if docs else []
    return subprocess.run([sys.executable, str(SCRIPT), *args] + paths,
                          capture_output=True, text=True, cwd=str(REPO), env=env, timeout=600)


def test_the_command_line_checks_both_documents_and_its_last_line_says_what_was_asserted(scratch):
    done = run_cli("--check", "--no-fold", docs=scratch)
    assert done.returncode == 0, done.stderr
    assert ("OK  11 rows and 6 canonical regions verified in README.md and docs/status.md (position, hand-typed "
            "numbers and internal names asserted; the glyph model was not measured (--no-fold), so the hero "
            "figures are model predictions)") in done.stdout


def test_a_run_writes_no_bytecode_anywhere(tmp_path, scratch):
    """Python is told to write every byte-code file into a directory only this test's processes use, so another
    process cannot disturb the count: a file there after the run is one this run wrote. What loading the script's
    own imports writes before it switches byte-code off is taken as the baseline (`--help` stops there)."""
    prefix = tmp_path / "pyc"
    env = {"PYTHONPYCACHEPREFIX": str(prefix)}

    def written() -> set[str]:
        return {str(p.relative_to(prefix)) for p in prefix.rglob("*.pyc")} if prefix.is_dir() else set()
    assert run_cli("--help", env_extra=env).returncode == 0
    baseline = written()
    done = run_cli("--check", "--no-fold", docs=scratch, env_extra=env)
    assert done.returncode == 0, done.stderr
    assert written() == baseline, sorted(written() - baseline)
    # the method does detect a write: a module imported with byte-code on lands in the prefix
    (tmp_path / "probe.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {str(tmp_path)!r}); import probe"],
                   check=True, env={**os.environ, **env, "PYTHONDONTWRITEBYTECODE": ""}, timeout=60)
    assert any(name.endswith("probe.cpython-" + f"{sys.version_info[0]}{sys.version_info[1]}.pyc") for name in written())


def test_the_command_line_exits_1_for_a_document_it_cannot_read_and_for_missing_markers(tmp_path, scratch):
    done = run_cli("--check", "--no-fold", docs=Docs(tmp_path / "absent.md", scratch.status))
    assert done.returncode == 1 and "cannot read or write" in done.stderr
    done = run_cli("--check", "--no-fold", docs=Docs(scratch.readme, tmp_path / "absent.md"))
    assert done.returncode == 1 and "cannot read or write" in done.stderr
    bare = Docs(tmp_path / "bare-README.md", tmp_path / "bare-status.md")
    for path in bare:
        path.write_text("# nothing\n", encoding="utf-8")
    done = run_cli("--write", docs=bare)
    assert done.returncode == 1 and "was NOT touched" in done.stderr
    assert "region 'commands' is missing" in done.stderr and "region 'proof' is missing" in done.stderr
    assert all(path.read_text(encoding="utf-8") == "# nothing\n" for path in bare)
    binary = tmp_path / "binary.md"
    binary.write_bytes(b"\xff\xfe not utf-8")
    assert run_cli("--check", "--no-fold", docs=Docs(binary, scratch.status)).returncode == 1
    assert run_cli().returncode == 2  # one of --write and --check is required


def make_verify_repo(tmp_path: Path) -> tuple[Path, dict, Path]:
    """A repository in which every step of verify-claims.sh passes: the three audits (node is a stub that
    succeeds, the assets exist), the corpus, and the generator, provenance and evidence scripts (stubs that log
    their arguments and exit with the code the environment gives them, 0 by default)."""
    root, log = tmp_path / "repo", tmp_path / "calls.log"
    (root / "scripts").mkdir(parents=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("python3", f'exec {shlex.quote(sys.executable)} "$@"'), ("node", "exit 0")):
        (bindir / name).write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
        (bindir / name).chmod(0o755)
    shutil.copy2(VERIFY, root / "scripts" / "verify-claims.sh")
    stub = ("import os, sys\nopen(os.environ['CALLS'], 'a').write(os.path.basename(sys.argv[0]) + ' ' + "
            "' '.join(sys.argv[1:]) + '\\n')\nsys.exit(int(os.environ.get('STUB_RC_' + os.path.basename(sys.argv[0])[:-3].replace('-', '_'), '0')))\n")
    for name in ("generate-hero-status.py", "verify-hero-provenance.py", "check-enforcement-evidence.py"):
        (root / "scripts" / name).write_text(stub, encoding="utf-8")
    for asset in ("demo-trace.json", "pipeline-hero.svg", "hook-trace.json", "hook-hero.svg", "guard-hero.json", "guard-hero.svg"):
        (root / ".github" / "assets").mkdir(parents=True, exist_ok=True)
        (root / ".github" / "assets" / asset).write_text("{}", encoding="utf-8")
    corpus = root / "hooks" / "tests" / "fixtures" / "adversarial_corpus.json"
    corpus.parent.mkdir(parents=True)
    corpus.write_text('[{"case": 1}]', encoding="utf-8")
    (root / "settings.json").write_text('{"hooks": {}}\n', encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(PATH=f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}", CALLS=str(log), HOME=str(tmp_path),
               PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_NOSYSTEM="1", GIT_CEILING_DIRECTORIES=str(tmp_path))
    for args in (["init", "-q"], ["add", "-A"]):
        subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True)
    return root, env, log


def verify(root: Path, env: dict):
    return subprocess.run(["bash", "scripts/verify-claims.sh"], cwd=root, env=env, capture_output=True, text=True, timeout=120)


def test_verify_claims_runs_the_generators_check_and_the_provenance_check_and_passes_when_both_do(tmp_path):
    root, env, log = make_verify_repo(tmp_path)
    done = verify(root, env)
    assert done.returncode == 0, done.stdout + done.stderr  # every step of the stub repository passes
    assert "verify-claims: ALL CHECKS PASSED" in done.stdout
    assert "PASS: hero-status:" in done.stdout and "PASS: hero-provenance:" in done.stdout
    assert "FAIL" not in done.stdout
    calls = [c.rstrip() for c in log.read_text(encoding="utf-8").splitlines()]
    # unchanged in substance: the check as before (with the fold measurement), the provenance audit with its rerun
    assert calls.count("generate-hero-status.py --check") == 1
    assert calls.count("verify-hero-provenance.py") == 1
    assert not any("--skip-rerun" in c or "--tamper" in c or "--no-fold" in c or "--write" in c for c in calls)


@pytest.mark.parametrize("failing,line,other", [
    ("generate_hero_status", "hero-status:", "hero-provenance:"),
    ("verify_hero_provenance", "hero-provenance:", "hero-status:"),
])
def test_verify_claims_fails_when_either_of_the_two_does_and_names_which(tmp_path, failing, line, other):
    root, env, _log = make_verify_repo(tmp_path)
    done = verify(root, dict(env, **{f"STUB_RC_{failing}": "2"}))
    assert done.returncode == 1
    assert f"FAIL: {line}" in done.stdout and f"PASS: {line}" not in done.stdout
    assert f"PASS: {other}" in done.stdout  # the other one still ran and passed: every check reports
    assert "verify-claims: FAILURES DETECTED" in done.stdout


def test_verify_claims_invokes_the_two_checks_unconditionally_on_executable_lines():
    code = [l for l in VERIFY.read_text(encoding="utf-8").splitlines() if l.strip() and not l.lstrip().startswith("#")]
    for command in ("python3 scripts/generate-hero-status.py --check", "python3 scripts/verify-hero-provenance.py"):
        lines = [l for l in code if command in l]
        assert lines == [f"if {command}; then"], (command, lines)  # once, as the condition of its PASS/FAIL branch
    assert not [l for l in code if "generate-hero-status" in l and "|| true" in l]
    assert not [l for l in code if "verify-hero-provenance" in l and ("|| true" in l or "--skip-rerun" in l)]


def test_the_generator_has_no_personal_value_and_no_network_call():
    source = SCRIPT.read_text(encoding="utf-8") + Path(__file__).read_text(encoding="utf-8")
    assert not re.search("/ho" + "me/|/Us" + "ers/|[A-Za-z0-9._+-]+@[A-Za-z0-9-]+\\.[A-Za-z]{2,}", source)
    import ast
    imported = {a.name.split(".")[0] for n in ast.walk(ast.parse(SCRIPT.read_text(encoding="utf-8")))
                if isinstance(n, ast.Import) for a in n.names}
    assert not imported & {"socket", "urllib", "http", "requests", "ssl"}
