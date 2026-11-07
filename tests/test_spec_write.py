"""scripts/spec-write.py, the one writer of a spec monolith (P1b E14).

Each test runs the script as a subprocess against a throw-away project under
tmp_path; nothing outside it is written.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WRITER = REPO / "scripts" / "spec-write.py"
TEMPLATE = (REPO / "templates" / "overnight-spec.md").read_text(encoding="utf-8")


def _run(args, stdin: str):
    return subprocess.run([sys.executable, str(WRITER), *args], input=stdin, text=True,
                          capture_output=True, timeout=30)


def _spec(tmp_path: Path, name: str = "spec-20261028-101010.md") -> Path:
    return tmp_path / "docs" / "dev" / "specs" / name


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    nxt = text.find("\n## ", start + 1)
    return text[start:nxt if nxt != -1 else len(text)]


def test_create_writes_the_file_and_names_it(tmp_path):
    spec = _spec(tmp_path)
    run = _run(["create", "--spec", str(spec)], TEMPLATE)
    assert run.returncode == 0, run.stderr
    assert spec.read_text(encoding="utf-8") == TEMPLATE
    assert run.stdout.strip() == f"spec-write: create {spec}"
    assert sorted(p.name for p in spec.parent.iterdir()) == [spec.name]  # no temp or lock file left


def test_create_refuses_an_existing_spec(tmp_path):
    spec = _spec(tmp_path)
    _run(["create", "--spec", str(spec)], TEMPLATE)
    run = _run(["create", "--spec", str(spec)], "other\n")
    assert run.returncode == 1
    assert spec.read_text(encoding="utf-8") == TEMPLATE


def test_append_replaces_a_lone_placeholder(tmp_path):
    spec = _spec(tmp_path)
    _run(["create", "--spec", str(spec)], TEMPLATE)
    run = _run(["append", "--spec", str(spec), "--section", "5"], "Make the header 64px tall.\n")
    assert run.returncode == 0, run.stderr
    section = _section(spec.read_text(encoding="utf-8"), "## Section 5:")
    assert "Make the header 64px tall." in section
    assert "_Not yet populated._" not in section
    assert section.rstrip().endswith("---")  # the closing separator stays last


def test_append_adds_after_existing_content_and_keeps_prior_cycles(tmp_path):
    spec = _spec(tmp_path)
    _run(["create", "--spec", str(spec)], TEMPLATE)
    _run(["append", "--spec", str(spec), "--section", "5"], "first\n")
    _run(["append", "--spec", str(spec), "--section", "5"], "### 5.2: more\nsecond\n")
    run = _run(["append", "--spec", str(spec), "--section", "4"], "### Cycle 2\nheader 48px\n")
    assert run.returncode == 0, run.stderr
    text = spec.read_text(encoding="utf-8")
    five = _section(text, "## Section 5:")
    assert five.index("first") < five.index("### 5.2: more") < five.index("second")
    four = _section(text, "## Section 4:")
    assert "### Cycle 1\n\n_Not yet populated._" in four  # the prior cycle is untouched
    assert four.index("### Cycle 1") < four.index("### Cycle 2") < four.index("header 48px")
    assert text.count("## Section ") == TEMPLATE.count("## Section ")


def test_append_to_a_subsection_keeps_its_consumers_line(tmp_path):
    spec = _spec(tmp_path)
    _run(["create", "--spec", str(spec)], TEMPLATE)
    line = "- `docs/dev/specs/20261028-101010/design/turn-1-layout.md` — layout\n"
    run = _run(["append", "--spec", str(spec), "--section", "9.1"], line)
    assert run.returncode == 0, run.stderr
    text = spec.read_text(encoding="utf-8")
    sub = text[text.index("### 9.1"):text.index("### 9.2")]
    assert "<!-- consumers: [all] -->\n" + line in sub
    assert "_Not yet populated._" not in sub
    assert "_Not yet populated._" in text[text.index("### 9.2"):]  # 9.2 keeps its placeholder


def test_refusals_write_nothing(tmp_path):
    spec = _spec(tmp_path)
    _run(["create", "--spec", str(spec)], TEMPLATE)
    before = spec.read_bytes()
    assert _run(["append", "--spec", str(spec), "--section", "12"], "x\n").returncode == 1
    assert _run(["append", "--spec", str(spec), "--section", "five"], "x\n").returncode == 2
    assert _run(["append", "--spec", str(spec), "--section", "5"], "  \n").returncode == 1
    assert spec.read_bytes() == before
    for other in (tmp_path / "docs" / "dev" / "notes.md", _spec(tmp_path, "INDEX.md"),
                  tmp_path / "docs" / "dev" / "specs" / "x" / "views" / "ba.md"):
        assert _run(["create", "--spec", str(other)], "x\n").returncode == 2
        assert not other.exists()


def test_a_new_file_gets_a_readable_mode_and_an_append_keeps_the_mode(tmp_path):
    spec = _spec(tmp_path)
    _run(["create", "--spec", str(spec)], TEMPLATE)
    assert spec.stat().st_mode & 0o777 == 0o644
    os.chmod(spec, 0o600)
    _run(["append", "--spec", str(spec), "--section", "8"], "note\n")
    assert spec.stat().st_mode & 0o777 == 0o600


def _update_example(spec: Path, sections: list[str]) -> str:
    """commands/spec-update.md's writer example as one Bash call appending a `### Cycle 2` block to
    each of `sections`: its chained appends repeated, the last one closing the chain."""
    text = (REPO / "commands" / "spec-update.md").read_text(encoding="utf-8")
    block = next(b for b in text.split("```bash\n")[1:] if "spec-write.py append" in b).split("```")[0]
    appends = block.split("python3 ")[1:]
    chained, last = "python3 " + appends[0], "python3 " + appends[-1]
    assert chained.split("\n", 1)[0].endswith("&&") and not last.split("\n", 1)[0].endswith("&&")
    out = []
    for n, sec in enumerate(sections):
        one = chained if n < len(sections) - 1 else last
        one = re.sub(r"--section \S+", f"--section {sec}", one)
        out.append(one.replace("~/.claude/scripts/spec-write.py", str(WRITER))
                   .replace("/abs/path/docs/dev/specs/spec-<ts>.md", str(spec))
                   .replace("<N>", "2").replace("<content>", f"cycle 2 of section {sec}"))
    return "".join(out)


def test_spec_update_writes_a_run_in_one_bash_call(tmp_path):
    spec = _spec(tmp_path)
    _run(["create", "--spec", str(spec)], TEMPLATE)
    sections = ["2", "3", "4", "6", "7", "8"]
    run = subprocess.run(["bash", "-c", _update_example(spec, sections)], text=True, capture_output=True,
                         timeout=60)
    assert run.returncode == 0, run.stderr
    assert run.stdout.splitlines() == [f"spec-write: append {spec}"] * len(sections)
    text = spec.read_text(encoding="utf-8")
    for sec in sections:
        assert f"### Cycle 2\ncycle 2 of section {sec}" in _section(text, f"## Section {sec}:")


def test_a_refused_append_stops_the_chain_and_keeps_what_came_before(tmp_path):
    spec = _spec(tmp_path)
    _run(["create", "--spec", str(spec)], TEMPLATE)
    run = subprocess.run(["bash", "-c", _update_example(spec, ["2", "12", "4"])], text=True,
                         capture_output=True, timeout=60)
    assert run.returncode == 1
    text = spec.read_text(encoding="utf-8")
    assert "cycle 2 of section 2" in text
    assert "cycle 2 of section 4" not in text
