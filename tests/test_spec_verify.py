"""scripts/spec-verify/spec-verify.py --strict on /spec splits (P1b lane SPX).

The overlap and uniqueness rules do not count the lines the split rules route into
every view (agents/spec.md M7: Section 9 whole; `consumers: [all]` blocks), so a
compliant split of a small spec passes while a fan-out dump still fails; the structural
rule lets a consumer view omit `## Role Mandate` exactly where R3.4 does (the monolith
annotates no role for the view's agent) and names the view and the section when it may
not; the verifier writes nothing into the views it checks.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERIFY_DIR = REPO / "scripts" / "spec-verify"
VERIFIER = VERIFY_DIR / "spec-verify.py"
TEMPLATE = (REPO / "templates" / "overnight-spec.md").read_text(encoding="utf-8")
REF = "- `docs/dev/specs/20261029-101010/design/turn-3-check.md` — where the type check goes"


def _verifier():
    sys.path.insert(0, str(VERIFY_DIR))
    spec = importlib.util.spec_from_file_location("spec_verify_cli", VERIFIER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _small_monolith() -> str:
    """The template as /spec fills it for a small requirement (the replay's req=small)."""
    text = TEMPLATE.replace("<issue_description>", "toy.add input validation")
    text = text.replace("_Not yet populated._\n\n---\n\n## Section 2", (
        "_Not yet populated._\n\ntoy/__init__.py:1 defines add(a, b) as `return a + b`.\n"
        "tests/test_add.py:3 covers only add(2, 3) == 5.\n\n---\n\n## Section 2"), 1)
    five = ("add input validation to toy.add: raise TypeError naming the offending argument.\n\n"
            "Acceptance:\n- toy.add(1, 2) still returns 3\n- toy.add('1', 2) raises TypeError naming a\n"
            "- toy.add(1, '2') raises TypeError naming b\n- tests/test_add.py keeps passing\n\n"
            "Constraints:\n- change only toy/__init__.py\n- keep the signature add(a, b)\n\n"
            "### 5.2: keep toy.sub unchanged\nAlso keep toy.sub unchanged for its callers.\n")
    head, rest = text.split("## Section 5:", 1)
    rest = rest.replace("_Not yet populated._\n", five, 1)
    text = head + "## Section 5:" + rest
    head, rest = text.split("### 9.1: Design References", 1)
    return head + "### 9.1: Design References" + rest.replace("_Not yet populated._", REF, 1)


def _section(mono: str, n: str) -> list[str]:
    lines = mono.split("\n")
    start = next(i for i, l in enumerate(lines) if l.startswith(f"## Section {n}:"))
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    return [l for l in lines[start:end] if l.strip() != "---"]


def _pick(mono: str, n: str, *starts: str) -> list[str]:
    """Lines of Section n from each line starting with one of `starts` to the next blank line."""
    lines, out = _section(mono, n), []
    for s in starts:
        i = next(k for k, l in enumerate(lines) if l.startswith(s))
        while i < len(lines) and lines[i].strip():
            out.append(lines[i])
            i += 1
        out.append("")
    return out


def _view(agent: str, body: list[str], mandate: str | None) -> str:
    out = [f"<!-- AUTO-GENERATED VIEW for {agent} | source: m | extracted: now -->", "",
           f"# {agent} view of x", "", "**Monolith**: m", "", "---", ""]
    if mandate:
        out += ["## Role Mandate", "", "> " + mandate, ""]
    return "\n".join(out + body) + "\n"


def _split(mono: str, omit_qa_mandate=False, dump=False) -> dict:
    """A compliant two-view split (Section 9 whole in every view, M7), or with `dump` the
    coverage-fallback ANTI-PATTERN: every qa block dumped into dev as well."""
    s9 = _section(mono, "9")
    qa = (_section(mono, "4") + _pick(mono, "5", "## Section 5", "<!-- WHO WRITES", "add input", "Acceptance:")
          + _section(mono, "6") + _section(mono, "7") + s9)
    dev = (_section(mono, "1") + _section(mono, "2") + _section(mono, "3")
           + _pick(mono, "5", "add input", "Constraints:", "### 5.2") + _section(mono, "8") + s9)
    if dump:
        dev = dev + qa
    lines = mono.split("\n")
    orch = ["## Pipeline Workflow", ""] + lines[:lines.index("---")] + [""] + s9
    # A mandate quotes a monolith line verbatim: the WHO WRITES comment of the view's own section.
    dev_mandate, qa_mandate = (next(l for l in _section(mono, n) if l.startswith("<!-- WHO WRITES"))
                               for n in ("2", "4"))
    return {"dev.md": _view("dev", dev, dev_mandate),
            "qa.md": _view("qa", qa, None if omit_qa_mandate else qa_mandate),
            "orchestrator.md": _view("orchestrator", orch, None)}


def _run(tmp_path: Path, mono: str, views: dict):
    (tmp_path / "views").mkdir(parents=True, exist_ok=True)
    (tmp_path / "spec.md").write_text(mono, encoding="utf-8")
    for name, text in views.items():
        (tmp_path / "views" / name).write_text(text, encoding="utf-8")
    run = subprocess.run([sys.executable, str(VERIFIER), "--monolith", str(tmp_path / "spec.md"),
                          "--views-dir", str(tmp_path / "views"), "--strict"],
                         capture_output=True, text=True, timeout=60)
    rows = {}
    for line in run.stdout.split("=== Verification Summary ===")[-1].splitlines():
        name, sep, rest = line.strip().partition(":")
        if sep and name.isidentifier():
            rows[name] = rest.strip()
    return run, rows


def test_a_compliant_split_of_a_small_spec_passes_strict(tmp_path):
    mono = _small_monolith()
    run, rows = _run(tmp_path, mono, _split(mono))
    assert run.returncode == 0, run.stdout + run.stderr
    assert rows["coverage"].startswith("PASS") and rows["overlap"] == "PASS" and rows["uniqueness"] == "PASS"
    # The case is real: counted whole, the Section 9 lines alone put the pair over the threshold.
    mod = _verifier()
    views = mod.load_consumer_views(str(tmp_path / "views"))
    pct, _shared = mod._pair_overlap_pct(views["dev.md"], views["qa.md"])
    assert pct > 30.0


def test_a_bad_split_still_fails_strict(tmp_path):
    mono = _small_monolith()
    run, rows = _run(tmp_path, mono, _split(mono, dump=True))
    assert run.returncode == 1
    assert rows["overlap"].startswith("FAIL") and rows["uniqueness"].startswith("FAIL")


def test_the_lines_every_view_carries_are_section_9_and_all_blocks_only():
    mod = _verifier()
    mono = _small_monolith()
    by_rule = mod.lines_every_view_carries(mono)
    assert {l.strip() for l in _section(mono, "9") if l.strip()} == by_rule
    assert "Also keep toy.sub unchanged for its callers." not in by_rule
    extra = mono.replace("Also keep toy.sub", "<!-- consumers: [all] -->\nAlso keep toy.sub", 1)
    assert "Also keep toy.sub unchanged for its callers." in mod.lines_every_view_carries(extra)
    assert "- change only toy/__init__.py" not in mod.lines_every_view_carries(
        mono.replace("Constraints:", "<!-- consumers: [dev, qa] -->\nConstraints:", 1))


def test_all_names_no_role_and_a_heading_or_a_named_consumer_does():
    mod = _verifier()
    assert mod.role_annotated_agents(_small_monolith()) == set()
    assert mod.role_annotated_agents("## Role: ba\nx\n<!-- consumers: [dev, qa] -->\ny\n") == {"ba", "dev", "qa"}


def test_a_view_may_omit_its_role_mandate_where_the_monolith_annotates_no_role(tmp_path):
    mono = _small_monolith()
    run, rows = _run(tmp_path, mono, _split(mono, omit_qa_mandate=True))
    assert run.returncode == 0, run.stdout + run.stderr
    assert rows["structural"] == "PASS"


def test_an_annotated_role_may_not_be_omitted_and_the_failure_names_view_and_section(tmp_path):
    mono = _small_monolith().replace("### Cycle 1\n\n_Not yet populated._\n\n---\n\n## Section 7",
                                     "### Role: qa\n\n_Not yet populated._\n\n---\n\n## Section 7", 1)
    run, rows = _run(tmp_path, mono, _split(mono, omit_qa_mandate=True))
    assert run.returncode == 1
    assert rows["structural"] == "FAIL (qa.md: ## Role Mandate missing)"
    run, rows = _run(tmp_path / "with", mono, _split(mono))
    assert rows["structural"] == "PASS"


def test_the_verifier_writes_nothing_into_the_views(tmp_path):
    mono = "---\nguide_version: 1\n---\n" + _small_monolith()
    _run(tmp_path, mono, _split(mono, omit_qa_mandate=True))
    assert sorted(p.name for p in (tmp_path / "views").iterdir()) == ["dev.md", "orchestrator.md", "qa.md"]
