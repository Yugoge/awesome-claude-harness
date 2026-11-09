"""scripts/generate-hero-status.py: the README's five canonical regions, where they sit, and the numbers in
the prose around them.

What is covered:

* each region (`proof`, `commands`, `limits`, `disclosure`, `status`) is regenerated from code by --write,
  and --check byte-compares it, with the fail-closed rules: a claim row degrades to not-yet when its input
  is missing, a count region that cannot be computed fails the check naming the input and is never written;
* the proof table, cell by cell, including the cells that say what CI fails on only when readme_facts'
  ci_enforces says the assertion is there, and say what is NOT asserted otherwise;
* the commands table and the escaping of what a summary may hold;
* the two rows added with the status region, enforcement-strength and dead-end-sites;
* the position rule (each region inside its H2 section, the claim regions in order) that replaced the
  headline-adjacency and above-the-fold assertions, and the glyph-model drift that is still consumed;
* the number rule: no numeral typed by hand in the prose, except the declared cited figures;
* the real README.md passes the check, and scripts/verify-claims.sh still runs the generator's check and the
  hero-provenance check.

The facts are derived once for the module (about 9 s: the blocking-site enumeration dominates) and cached in
the generator; a test that needs a different fact replaces it in that cache for its own duration. Nothing
here replays the replay suite or runs the artifact check.
"""
from __future__ import annotations

import copy
import importlib.util
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

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

SKELETON = f"""# A harness

Intro paragraph with no number in it. A study of {FIGURE_A} pull requests waited a median of {FIGURE_B}
hours ([source]({URL})).

1. First step.
2. Second step.

{GLYPH_IMG}

## Measured proof

Counted from the repository.

{{proof}}

## Commands

Generated from the frontmatter.

{{commands}}

## Status and known limits

Generated claim rows.

{{limits}}

{{disclosure}}

{{status}}

## Documentation

- [Installation](docs/installation.md)
"""


def empty_region(rid: str) -> str:
    return f"{gen.BEGIN.format(rid=rid)}\n{gen.END.format(rid=rid)}"


@pytest.fixture(autouse=True)
def _restore_readme_path():
    """cmd_write and cmd_check bind the generator's README_PATH; give it back after each test."""
    saved = gen.README_PATH
    yield
    gen.README_PATH = saved


@pytest.fixture(scope="module")
def warm():
    """Every fact of the repository, derived once and cached by the generator."""
    regions, failed, rows = gen.expected_regions()
    assert not failed, failed
    return regions, rows


@pytest.fixture(scope="module")
def scratch_text(warm, tmp_path_factory):
    """A README with the five regions under their sections, filled by write mode."""
    path = tmp_path_factory.mktemp("regions") / "README.md"
    path.write_text(SKELETON.format(**{rid: empty_region(rid) for rid in gen.REGION_IDS}), encoding="utf-8")
    assert gen.cmd_write(path) == 0
    return path.read_text(encoding="utf-8")


@pytest.fixture
def scratch(tmp_path, scratch_text):
    path = tmp_path / "README.md"
    path.write_text(scratch_text, encoding="utf-8")
    return path


def run_check(path: Path, capsys, fold: bool = False):
    rc = gen.cmd_check(path, check_fold=fold)
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
    assert gen.REGION_IDS == ("proof", "commands", "limits", "disclosure", "status")
    assert gen.CLAIM_REGIONS == ("limits", "disclosure", "status")
    assert gen.SECTION_OF == {"proof": "Measured proof", "commands": "Commands", "limits": "Status and known limits",
                              "disclosure": "Status and known limits", "status": "Status and known limits"}
    # the nine rows that existed keep their order; the two new ones are added to the closed set and its maps
    assert gen.ROW_IDS[:9] == ["known-limits", "hero-recording", "hero-legibility", "hero-glyph",
                               "supported-builds", "capability-check", "blackbox-tests", "release", "os"]
    assert gen.ROW_IDS[9:] == ["enforcement-strength", "dead-end-sites"]
    assert set(gen.PREDICATES) == set(gen.REGION_OF) == set(gen.ROW_IDS)
    assert gen.REGION_OF["enforcement-strength"] == gen.REGION_OF["dead-end-sites"] == "status"


def test_write_fills_all_five_regions_from_code_and_touches_nothing_else(tmp_path, warm):
    regions, _rows = warm
    skeleton = SKELETON.format(**{rid: empty_region(rid) for rid in gen.REGION_IDS})
    path = tmp_path / "README.md"
    path.write_text(skeleton, encoding="utf-8")
    assert gen.cmd_write(path) == 0
    written = path.read_text(encoding="utf-8")
    for rid in gen.REGION_IDS:
        assert region(written, rid) == regions[rid], rid
        assert len(region(written, rid).splitlines()) > 2, f"{rid} was written empty"
    for rid in gen.REGION_IDS:  # outside the regions, byte for byte what it was
        skeleton, written = cut(skeleton, rid), cut(written, rid)
    assert written == skeleton
    # writing again changes nothing: the regeneration is deterministic
    before = path.read_bytes()
    assert gen.cmd_write(path) == 0 and path.read_bytes() == before


def test_a_regenerated_readme_passes_the_check(scratch, capsys):
    rc, err, out = run_check(scratch, capsys)
    assert rc == 0, err
    assert "OK" in out and "11 rows" in out and "5 canonical regions" in out


def test_each_claim_region_holds_its_rows_in_the_closed_order(scratch_text):
    ids = {rid: [m.group("id") for m in map(gen.MARKER_RE.match, region(scratch_text, rid).splitlines()) if m]
           for rid in gen.CLAIM_REGIONS}
    assert ids["limits"] == ["known-limits"]
    assert ids["disclosure"] == ["hero-recording", "hero-legibility", "hero-glyph"]
    assert ids["status"] == ["supported-builds", "capability-check", "blackbox-tests", "release", "os",
                             "enforcement-strength", "dead-end-sites"]
    assert sorted(i for r in gen.CLAIM_REGIONS for i in ids[r]) == sorted(gen.ROW_IDS)


def test_write_refuses_a_readme_that_lacks_a_regions_markers_before_deriving_anything(tmp_path):
    path = tmp_path / "README.md"
    text = SKELETON.format(**{rid: empty_region(rid) for rid in gen.REGION_IDS}).replace(
        gen.BEGIN.format(rid="commands"), "")
    path.write_text(text, encoding="utf-8")
    assert gen.cmd_write(path) == 1
    assert path.read_text(encoding="utf-8") == text


# ================================================================ 2. the proof table

def test_the_proof_table_has_its_header_and_one_row_for_each_thing_counted(scratch_text):
    lines = body(scratch_text, "proof").splitlines()
    assert lines[0] == "| Counted from the repository | Now | CI fails when |"
    assert lines[1] == "|---|---|---|"
    rows = rows_of(body(scratch_text, "proof"))
    assert len(rows) == 7 and all(len(r) == 3 for r in rows)
    assert [r[0] for r in rows][:4] == ["Python versions CI runs the baseline job on", "Pipelines replayed",
                                        "Faults injected", "Blocking sites of the registered hooks"]
    assert rows[5][0].startswith("Tests") and rows[6][0].startswith("Hook registrations")


def test_every_proof_cell_comes_from_the_facts(scratch_text):
    rows = {r[0]: r for r in rows_of(body(scratch_text, "proof"))}
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


def test_the_artifact_row_is_labelled_exactly_as_readme_facts_labels_it(scratch_text):
    arts = gen.fact("static_artifacts")
    row = next(r for r in rows_of(body(scratch_text, "proof")) if r[0].startswith("file artifacts declared"))
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


def test_the_blocking_sites_cell_makes_the_weaker_claim_and_never_the_literal_one(scratch_text, monkeypatch):
    cell = rows_by_prefix(body(scratch_text, "proof"), "Blocking sites")[2]
    assert cell == "a replay that reaches a blocking site with no clearing class fails CI (`tests/replay/test_no_dead_end.py`)"
    assert gen.fact("ci_enforces")["no_site_without_class"]["holds"] is False  # the suite does not assert it
    for forbidden in ("no site lacks", "no blocking site lacks", "no site may lack", "no blocking site may lack",
                      "lacks a class", "none lacks"):
        assert forbidden not in scratch_text, forbidden
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


def test_the_unit_suite_cell_lists_the_versions_and_what_the_suite_leaves_out(scratch_text):
    cell = rows_by_prefix(body(scratch_text, "proof"), "Tests")[2]
    unit = gen.fact("ci_enforces")["unit_suite_on_every_version"]
    assert cell.startswith("the unit suite fails on any of " + ", ".join(unit["versions"]))
    assert unit["ignored"] and all(f"`{p}`" in cell for p in unit["ignored"])


def test_the_hook_registration_cell_names_the_gate_that_fails(scratch_text):
    cell = rows_by_prefix(body(scratch_text, "proof"), "Hook registrations")[2]
    assert cell == "ledger rows that differ from the registered hooks fail `scripts/check-enforcement-evidence.py`"
    assert (REPO / "scripts/check-enforcement-evidence.py").is_file()


# ================================================================ 3. the commands table

def test_the_commands_table_is_built_from_the_command_rows(scratch_text):
    lines = body(scratch_text, "commands").splitlines()
    assert lines[0] == "| Command | Typed by | What it does |" and lines[1] == "|---|---|---|"
    rows = rows_of(body(scratch_text, "commands"))
    facts = gen.fact("command_rows")
    assert len(rows) == len(facts) and all(len(r) == 3 for r in rows)
    for cells, fact in zip(rows, facts):
        usage = f"/{fact['name']}" + (f" {fact['argument_hint']}" if fact["argument_hint"] else "")
        assert cells[0] == "`" + usage.replace("|", "\\|") + "`", cells
        assert cells[1] == ("owner only" if fact["human_only"] else "owner or agent")
        assert cells[2] and "|" not in cells[2].replace("\\|", "")
    assert {c[1] for c in rows} == {"owner only", "owner or agent"}


HOSTILE = {"name": "evil", "argument_hint": "[a|b] <what> `x`", "human_only": False,
           "summary": "Pick a | b, run <script>alert(1)</script> & `code|with <pipe>` and \\| a backslash",
           "summary_source": "description"}


def test_a_summary_can_neither_break_the_table_nor_be_read_as_html(monkeypatch):
    commands = copy.deepcopy(gen.fact("command_rows")) + [HOSTILE]
    monkeypatch.setitem(gen._FACTS, "command_rows", commands)
    table = gen.render_commands()
    lines = [l for l in table.splitlines() if "/evil" in l]
    assert len(lines) == 1
    assert len(re.split(r"(?<!\\)\|", lines[0].strip())) == 5  # '', three cells, '' : the pipes did not add cells
    cells = rows_of(table)[-1]
    # outside code spans no angle bracket survives; inside one it is literal already
    prose = gen._CODE_SPAN.sub("", cells[2])
    assert "<" not in prose and ">" not in prose and "&lt;script&gt;" in prose and "&amp;" in prose
    assert "`code\\|with <pipe>`" in cells[2]
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


def test_enforcement_strength_reports_the_ledger_and_what_an_exit_code_is(scratch_text):
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
    assert marker + "\n- " + text in region(scratch_text, "status")


def test_enforcement_strength_follows_the_proof_layers(monkeypatch):
    some = lambda e: e["by_proof_layer"].update({"host-observed": 5, "source-level": e["by_proof_layer"]["source-level"] - 5})
    with_fact(monkeypatch, "enforcement_strength", some)
    state, text, *_ = new_row("enforcement-strength")
    assert state == "partial" and "**5** of the 78 rows are host-observed." in text and "No row" not in text
    with_fact(monkeypatch, "enforcement_strength", lambda e: e.update(
        by_proof_layer={**e["by_proof_layer"], "host-observed": e["rows"]}))
    state, text, *_ = new_row("enforcement-strength")
    assert state == "passed" and "all **78** ledger rows are host-observed" in text


def test_dead_end_sites_says_how_many_of_how_many_and_that_it_is_a_limit(scratch_text):
    b = gen.fact("blocking_sites")
    state, text, evidence, tracked = new_row("dead-end-sites")
    assert state == "partial" and b["no_class"] > 0
    assert (evidence, tracked) == ("tests/replay/test_no_dead_end.py", "none")
    assert f"**{b['no_class']} of {b['sites']}** blocking sites" in text
    assert "The suite fails only when a replay reaches one" in text
    assert "known limit and not a proof that there are none" in text
    marker = f"<!-- claim-row id=dead-end-sites state=partial evidence={evidence} tracked=none -->"
    assert marker + "\n- " + text in region(scratch_text, "status")


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
    assert "[region:proof] cannot be computed" in err and "no test file under hooks/tests/" in err
    assert "[region:commands]" not in err  # the other count region is unaffected


def test_a_count_region_is_never_regenerated_from_a_stale_value(tmp_path, scratch_text, capsys, monkeypatch):
    stale = tmp_path / "README.md"
    stale.write_text(scratch_text, encoding="utf-8")
    with_fact(monkeypatch, "command_rows", error="command_rows: no command file (commands/*.md) in the git index")
    assert gen.cmd_write(stale) == 1
    err = capsys.readouterr().err
    assert "region 'commands' cannot be computed" in err and "commands/*.md" in err and "NOT written" in err
    assert stale.read_text(encoding="utf-8") == scratch_text  # not one byte written, not even the other regions


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
    assert gen.expected_regions()[1].keys() == {"proof", "commands"}


# ================================================================ 6. a byte-compare failure on an edited region

def edited(scratch, old: str, new: str) -> None:
    text = scratch.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    scratch.write_text(text.replace(old, new), encoding="utf-8")


def test_an_edited_proof_cell_fails_the_byte_compare_and_names_the_region(scratch, capsys):
    replay = gen.fact("replay_suite_size")
    edited(scratch, f"{replay['compliant_replays']} compliant replays", f"{replay['compliant_replays'] + 1} compliant replays")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "[region-byte-compare] region 'proof'" in err
    assert err.count("FAIL") == 1  # only that region differs


def test_an_edited_commands_row_fails_the_byte_compare(scratch, capsys):
    edited(scratch, "| `/commit` | owner only |", "| `/commit` | owner or agent |")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "[region-byte-compare] region 'commands'" in err


def test_an_edited_claim_row_names_the_row_and_the_region(scratch, capsys):
    edited(scratch, "- **Release** — unreleased (no tags).", "- **Release** — shipping soon!")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "row 'release': visible text differs" in err and "region 'status'" in err


def test_a_flipped_state_fails_the_predicate_check(scratch, capsys):
    edited(scratch, "id=dead-end-sites state=partial", "id=dead-end-sites state=passed")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "row 'dead-end-sites' claims state='passed' but its named predicate evaluates to 'partial'" in err


def test_an_extra_bullet_inside_a_region_is_caught(scratch, capsys):
    edited(scratch, gen.END.format(rid="status"), "- **Everything works** — trust us.\n" + gen.END.format(rid="status"))
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "[region-byte-compare] region 'status'" in err


def test_a_missing_new_row_is_a_completeness_failure(scratch, capsys):
    text = scratch.read_text(encoding="utf-8")
    kept = [l for l in text.splitlines() if "dead-end-sites" not in l and not l.startswith("- **Dead-end sites**")]
    scratch.write_text("\n".join(kept) + "\n", encoding="utf-8")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "row 'dead-end-sites' is missing" in err


def test_a_claim_row_outside_every_region_is_caught(scratch, capsys):
    scratch.write_text(scratch.read_text(encoding="utf-8") + "\n<!-- claim-row id=os state=passed evidence=none tracked=none -->\n",
                       encoding="utf-8")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "claim-row marker outside any canonical region" in err


# ================================================================ 7. the position rule

def positions(text: str) -> list[str]:
    return gen.assert_region_positions(text)


def named(violations: list[str], rid: str) -> list[str]:
    return [v for v in violations if f"region {rid!r}" in v]


def test_regions_in_their_sections_in_order_have_no_violation(scratch_text):
    assert positions(scratch_text) == []


def test_the_headline_and_fold_assertions_are_gone(scratch_text):
    """The old rule, a limits statement next to the headline and above the fold, is not what is asserted."""
    assert not hasattr(gen, "assert_limits_above_fold")
    assert "headline" not in " ".join(positions(scratch_text))
    far = scratch_text.replace("Generated claim rows.\n", "Generated claim rows.\n\n" + "A paragraph.\n\n" * 12)
    assert positions(far) == []  # nothing needs to be adjacent to anything
    doc = gen.__doc__
    assert "moved the claim rows" in doc and "assert_region_positions" in doc and "replaced" in doc


def test_a_region_moved_out_of_its_section_is_named(scratch_text):
    moved = cut(scratch_text, "limits").replace("## Commands\n", "## Commands\n\n" + region(scratch_text, "limits") + "\n", 1)
    v = positions(moved)
    assert len(v) == 1 and "region 'limits' lies outside the H2 section 'Status and known limits'" in v[0]
    assert "'Commands'" in v[0]  # and says where it sits instead
    again = cut(scratch_text, "proof").replace("## Documentation\n", "## Documentation\n\n" + region(scratch_text, "proof") + "\n", 1)
    assert len(positions(again)) == 1 and named(positions(again), "proof")


def test_a_region_before_every_heading_is_outside_its_section(scratch_text):
    v = positions(region(scratch_text, "commands") + "\n\n" + cut(scratch_text, "commands"))
    assert len(v) == 1 and "region 'commands' lies outside" in v[0] and "no H2 section" in v[0]


def test_a_duplicated_region_is_named(scratch_text):
    status = region(scratch_text, "status")
    v = positions(scratch_text.replace(status, status + "\n\n" + status))
    assert len(v) == 1 and "region 'status' is duplicated" in v[0]


def test_a_missing_region_is_named(scratch_text):
    v = positions(cut(scratch_text, "proof"))
    assert len(v) == 1 and "region 'proof' is missing" in v[0]
    half = positions(scratch_text.replace(gen.BEGIN.format(rid="disclosure"), ""))
    assert len(half) == 1 and "region 'disclosure'" in half[0] and "not a BEGIN followed by an END" in half[0]


def test_claim_regions_out_of_order_are_named(scratch_text):
    a, b = region(scratch_text, "limits"), region(scratch_text, "disclosure")
    swapped = scratch_text.replace(a, "@@A@@").replace(b, a).replace("@@A@@", b)
    v = positions(swapped)
    assert named(v, "limits") and named(v, "disclosure") and not named(v, "status")
    assert all("out of order" in x for x in v)
    c = region(scratch_text, "status")
    v = positions(scratch_text.replace(c, "@@C@@").replace(a, c).replace("@@C@@", a))
    assert named(v, "limits") and named(v, "status")


def test_a_missing_or_renamed_section_heading_is_named_for_each_region_in_it(scratch_text):
    v = positions(scratch_text.replace("## Status and known limits", "## Status"))
    assert [bool(named(v, r)) for r in gen.CLAIM_REGIONS] == [True, True, True]
    assert all("has no H2 section 'Status and known limits'" in x for x in v) and len(v) == 3
    v = positions(scratch_text.replace("## Documentation", "## Status and known limits"))
    assert len(v) == 3 and all("appears 2 times" in x for x in v)


def test_a_region_in_a_subsection_of_its_section_is_inside_it(scratch_text):
    deeper = scratch_text.replace(region(scratch_text, "limits"), "### Limits\n\n" + region(scratch_text, "limits"))
    assert positions(deeper) == []
    sibling = scratch_text.replace(region(scratch_text, "limits"), "## Limits\n\n" + region(scratch_text, "limits"))
    v = positions(sibling)  # an H2 of its own ends the section: the region and the two that follow it are outside
    assert [bool(named(v, r)) for r in gen.CLAIM_REGIONS] == [True, True, True] and len(v) == 3


def test_a_heading_inside_a_fence_or_a_comment_is_no_heading(scratch_text):
    fenced = scratch_text.replace("## Status and known limits", "## Elsewhere\n\n```\n## Status and known limits\n```")
    v = positions(fenced)
    assert len(v) == 3 and all("has no H2 section" in x for x in v)
    commented = scratch_text.replace("## Status and known limits", "## Elsewhere\n\n<!--\n## Status and known limits\n-->")
    assert len(positions(commented)) == 3


def test_check_reports_a_moved_region_with_the_tag_and_exit_2(scratch, capsys):
    text = scratch.read_text(encoding="utf-8")
    scratch.write_text(cut(text, "limits").replace("## Commands\n", "## Commands\n\n" + region(text, "limits") + "\n", 1),
                       encoding="utf-8")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "[region-position] region 'limits' lies outside" in err


# ================================================================ 8. the number rule

def numbers(text: str) -> list[str]:
    return gen.assert_no_hand_typed_numbers(text)


def test_the_declared_figures_and_their_source(scratch_text):
    assert dict(gen.CITED_FIGURES) == {"37,623": "https://arxiv.org/pdf/2609.17598", "12.6": "https://arxiv.org/pdf/2609.17598"}
    assert numbers(scratch_text) == []  # the cited figures pass, the regions' own numbers are not read


def test_a_stray_numeral_in_the_prose_fails_naming_the_line_and_the_number(scratch_text):
    lines = scratch_text.splitlines()
    at = lines.index("Generated claim rows.")
    lines[at] = "Generated claim rows, 47 of them."
    v = numbers("\n".join(lines) + "\n")
    assert len(v) == 1
    assert f"line {at + 1}" in v[0] and "'47'" in v[0] and "[hand-typed-number]" in v[0]


def test_every_stray_numeral_is_reported_with_its_own_line(scratch_text):
    text = scratch_text.replace("Intro paragraph with no number in it.", "Intro with 3 and 4.5 and 1,000 numbers.")
    v = numbers(text)
    assert [re.search(r"the numeral '([^']+)'", x).group(1) for x in v] == ["3", "4.5", "1,000"]
    assert all("line 3" in x for x in v)


def test_a_cited_figure_passes_and_a_near_miss_does_not(scratch_text):
    assert numbers(scratch_text) == []
    near = scratch_text.replace(FIGURE_A, "37,624")
    v = numbers(near)
    assert any("'37,624'" in x and "[hand-typed-number]" in x for x in v)
    assert any("declared figure" in x and repr(FIGURE_A) in x for x in v)  # and the declared one is now stale too


def test_a_stale_cited_figure_fails(scratch_text):
    gone = scratch_text.replace(f"a median of {FIGURE_B}\nhours", "a median of some\nhours")
    v = numbers(gone)
    assert len(v) == 1 and "[cited-figure]" in v[0] and repr(FIGURE_B) in v[0] and "no longer appears" in v[0]
    in_code = scratch_text.replace(f"a median of {FIGURE_B}", f"a median of `{FIGURE_B}`")
    assert any(repr(FIGURE_B) in x and "no longer appears" in x for x in numbers(in_code))  # code is not prose


def test_a_missing_source_url_fails(scratch_text):
    v = numbers(scratch_text.replace(URL, "https://example.org/x"))
    assert len(v) == 2 and all("is absent from the README" in x and URL in x for x in v)  # one per figure it sources


def test_the_declared_figures_live_in_one_place(scratch_text, monkeypatch):
    monkeypatch.setattr(gen, "CITED_FIGURES", gen.CITED_FIGURES + (("99", "https://example.org/nine"),))
    v = numbers(scratch_text)
    assert any("'99'" in x and "https://example.org/nine" in x and "is absent" in x for x in v)
    assert any("'99'" in x and "no longer appears" in x for x in v)
    assert numbers(scratch_text + "\nSee https://example.org/nine: 99 cases.\n") == []


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


def test_the_line_numbers_survive_everything_that_is_blanked():
    text = "# T\n\n<!-- one\ntwo -->\n\n```\ncode\n```\n\nprose 5\n"
    assert gen.prose_numerals(text) == [(10, "5")]


def test_numbers_inside_the_regions_are_not_read(scratch_text):
    assert re.search(r"\d", region(scratch_text, "proof"))
    assert gen.prose_numerals(region(scratch_text, "proof")) == []
    assert numbers(scratch_text) == []


def test_check_reports_a_hand_typed_number_with_the_tag_and_exit_2(scratch, capsys):
    edited(scratch, "Second step.", "Second step, of 12.")
    rc, err, _ = run_check(scratch, capsys)
    assert rc == 2 and "[hand-typed-number] line 7: the numeral '12'" in err


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
    violations, notes = gen.assert_glyph_model(tmp_path / "README.md", script)
    assert violations == [f"[fold] {drift}"] and len(notes) == 1


def test_a_headline_and_limits_below_the_fold_and_the_glyph_floor_are_no_violation(tmp_path):
    script = stub_measure(tmp_path, {"results": [COMBO], "model_drift": [],
                                     "failures": ["1280x800/light: not above the fold: headline, limits",
                                                  "1280x800/light: hero glyph height 7.55px < 11.0px"]})
    violations, notes = gen.assert_glyph_model(tmp_path / "README.md", script)
    assert violations == [] and notes


def test_a_measurement_that_produced_nothing_is_a_violation_and_one_that_cannot_run_is_a_note(tmp_path):
    empty = stub_measure(tmp_path, {"results": [], "model_drift": []})
    assert gen.assert_glyph_model(tmp_path / "README.md", empty)[0]
    broken = tmp_path / "broken.py"
    broken.write_text("raise SystemExit('no browser')\n", encoding="utf-8")
    violations, notes = gen.assert_glyph_model(tmp_path / "README.md", broken)
    assert violations == [] and "UNVERIFIED" in notes[0]
    violations, notes = gen.assert_glyph_model(tmp_path / "README.md", tmp_path / "absent.py")
    assert violations == [] and "did NOT run" in notes[0]


def test_check_consumes_the_drift_report_of_the_real_fold_script_when_it_runs(scratch, capsys, monkeypatch):
    calls = []
    monkeypatch.setattr(gen, "assert_glyph_model", lambda readme: calls.append(readme) or (["[fold] drifted"], ["[fold] ran"]))
    rc, err, out = run_check(scratch, capsys, fold=True)
    assert calls == [scratch] and rc == 2 and "[fold] drifted" in err and "[fold] ran" in out
    calls.clear()
    assert run_check(scratch, capsys, fold=False)[0] == 0 and calls == []  # --no-fold leaves the measurement out


# ================================================================ 10. the real README, the command line, verify-claims.sh

def test_the_real_readme_passes_the_check(capsys):
    rc, err, out = run_check(REPO / "README.md", capsys)
    assert rc == 0, err
    assert "11 rows and 5 canonical regions verified" in out


def test_the_real_readme_holds_each_region_in_its_section_in_order():
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert positions(text) == []
    assert numbers(text) == []
    heads = [h for h in gen.headings(text) if h[0] == 2]
    order = [t for _l, t, _o in heads]
    assert {"Measured proof", "Commands", "Status and known limits"} <= set(order)


def run_cli(*args, readme: Path | None = None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "PYTHONDONTWRITEBYTECODE"}
    return subprocess.run([sys.executable, str(SCRIPT), *args] + (["--readme", str(readme)] if readme else []),
                          capture_output=True, text=True, cwd=str(REPO), env=env, timeout=600)


def pycache_files() -> set[str]:
    return {str(p) for p in (REPO / "scripts").rglob("*.pyc")}


def test_the_command_line_checks_the_real_readme_and_leaves_no_bytecode():
    before = pycache_files()
    done = run_cli("--check", "--no-fold")
    assert done.returncode == 0, done.stderr
    assert "OK  11 rows and 5 canonical regions verified (position, hand-typed numbers asserted)" in done.stdout
    assert pycache_files() == before


def test_the_command_line_exits_1_for_a_readme_it_cannot_read_and_for_missing_markers(tmp_path):
    done = run_cli("--check", "--no-fold", readme=tmp_path / "absent.md")
    assert done.returncode == 1 and "cannot read or write" in done.stderr
    bare = tmp_path / "README.md"
    bare.write_text("# nothing\n", encoding="utf-8")
    done = run_cli("--write", readme=bare)
    assert done.returncode == 1 and "region 'proof' markers not found" in done.stderr
    assert bare.read_text(encoding="utf-8") == "# nothing\n"
    assert run_cli().returncode == 2  # one of --write and --check is required


def make_verify_repo(tmp_path: Path) -> tuple[Path, dict, Path]:
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
    (root / "settings.json").write_text('{"hooks": {}}\n', encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(PATH=f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}", CALLS=str(log), HOME=str(tmp_path),
               PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_NOSYSTEM="1", GIT_CEILING_DIRECTORIES=str(tmp_path))
    for args in (["init", "-q"], ["add", "-A"]):
        subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True)
    return root, env, log


def test_verify_claims_still_runs_the_generators_check_and_the_provenance_check(tmp_path):
    root, env, log = make_verify_repo(tmp_path)
    done = subprocess.run(["bash", "scripts/verify-claims.sh"], cwd=root, env=env, capture_output=True, text=True, timeout=120)
    out = done.stdout
    assert "PASS: hero-status:" in out and "PASS: hero-provenance:" in out and "FAIL: hero-status" not in out
    calls = log.read_text(encoding="utf-8").splitlines()
    assert "generate-hero-status.py --check" in calls  # the check, with the fold measurement, as before
    assert "verify-hero-provenance.py " in calls or "verify-hero-provenance.py" in [c.rstrip() for c in calls]
    assert not any("--skip-rerun" in c or "--tamper" in c or "--no-fold" in c for c in calls)
    failing = dict(env, STUB_RC_generate_hero_status="2")
    done = subprocess.run(["bash", "scripts/verify-claims.sh"], cwd=root, env=failing, capture_output=True, text=True, timeout=120)
    assert "FAIL: hero-status:" in done.stdout and done.returncode == 1
    failing = dict(env, STUB_RC_verify_hero_provenance="2")
    done = subprocess.run(["bash", "scripts/verify-claims.sh"], cwd=root, env=failing, capture_output=True, text=True, timeout=120)
    assert "FAIL: hero-provenance:" in done.stdout and "PASS: hero-status:" in done.stdout


def test_verify_claims_comments_describe_the_new_layout():
    text = VERIFY.read_text(encoding="utf-8")
    assert "five canonical regions" in text and "Measured proof" in text and "Status and known limits" in text
    assert "headline-adjacent" not in text and "headline adjacency" not in text


def test_the_generator_has_no_personal_value_and_no_network_call():
    source = SCRIPT.read_text(encoding="utf-8") + Path(__file__).read_text(encoding="utf-8")
    assert not re.search("/ho" + "me/|/Us" + "ers/|[A-Za-z0-9._+-]+@[A-Za-z0-9-]+\\.[A-Za-z]{2,}", source)
    import ast
    imported = {a.name.split(".")[0] for n in ast.walk(ast.parse(SCRIPT.read_text(encoding="utf-8")))
                if isinstance(n, ast.Import) for a in n.names}
    assert not imported & {"socket", "urllib", "http", "requests", "ssl"}
